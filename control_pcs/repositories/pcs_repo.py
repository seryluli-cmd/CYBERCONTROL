"""
pcs_repo.py
============
Control de PCs: catálogo de estaciones (las PCs físicas del local) y de
bonos de tiempo prearmados ("3 horas" -> 180 min / $X), más el manejo de
las sesiones de uso que se arman al venderle un bono a una estación.

No existe la noción de "tiempo libre" ni de cobro por hora/minuto suelto:
todo pasa por bonos con TIEMPO y MONTO fijos, definidos por el Admin.

Un detalle de diseño importante: el cobro de un bono se registra en
"ventas"/"venta_pagos" (las mismas tablas que usa ventas_repo, así
aparece solo en Caja/Cierre de Turno/Consulta de Ventas), pero SIN fila
en "venta_detalle" — esa tabla exige un articulo_codigo real (tiene una
foreign key contra articulos), y un bono de tiempo no es un producto de
stock. Forzarlo como un artículo falso solo para poder facturarlo iba a
terminar ensuciando el catálogo de Artículos y las alertas de stock bajo
con productos que no son productos.

Los Miembros (socios con saldo prepago, ver `miembros_repo.py`, mismo paquete)
usan una estación distinto a un bono: en vez de comprarlo en el momento,
gastan de un saldo que ya tenían cargado. `_abrir_o_extender_sesion` es
el mecanismo compartido entre ambos flujos — lo único que cambia es de
dónde sale el tiempo.

El archivo se lee de arriba hacia abajo así: estaciones, catálogo de
bonos, estado en vivo y abrir/extender/trasladar/finalizar una sesión.
El feed de actividad vive en actividad_repo.py y se reexporta desde acá; la
cuenta de cuánto se le devuelve a cada socio al cortar una sesión, en
reintegros_repo.py. PCSTREAM (la PC de streaming) es una estación más, con su
propio catálogo de bonos en pcstream_repo.py.
"""

import re
import sqlite3
from datetime import datetime
import dominio
from database import conexion_db
from repositories import ventas_repo
from control_pcs.repositories import (
    avisos_fin_pc_repo, cortes_pc_repo, deudas_pc_repo, pcstream_repo, reservas_horario_repo, temperatura_pc_repo,
)
from control_pcs.repositories.catalogo_bonos import CatalogoDeBonos
from control_pcs.repositories.actividad_repo import actividad_reciente  # noqa: F401 (API de las pantallas y las pruebas)
from control_pcs.repositories.reintegros_repo import reintegros_por_miembro

# Más que el intervalo de consulta del Cliente PC (5s, ver
# control_pcs/ui/pcs_window.py) para darle margen de red antes de
# considerar "sin conexión" a una estación que en realidad sigue
# prendida -- se resetea a "enlazada" en su próxima consulta, sin
# necesitar que nadie la reinicie a mano. Era 15 s hasta el 2026-10-19:
# con una consulta cada 5 s y 3 s de espera, alcanzaban 2 o 3 consultas
# perdidas para que una PC en uso titilara "SIN CLIENTE" (pedido del dueño:
# que un corte cortito de red no dispare la alerta). Un Cliente PC cerrado
# se sigue viendo, 15 s más tarde. Por qué se cortó: cortes_pc_repo.
UMBRAL_ENLACE_SEGUNDOS = 30


# ---------------------------------------------------------------------
# Estaciones (catálogo de PCs físicas)
# ---------------------------------------------------------------------

def _orden_natural(estacion):
    """
    Clave para ordenar estaciones por nombre como lo haría una persona: "PC2"
    antes que "PC10" (el ORDER BY de SQLite compara letra por letra y pondría
    PC1, PC10, PC11... PC2). Los números del nombre se comparan como números;
    el resto, sin distinguir mayúsculas. PCSTREAM va antes que todas: en el
    mosaico queda al lado de la PlayStation 5 (pedido del dueño, 2026-10-17).
    """
    partes = re.split(r"(\d+)", estacion["nombre"].strip().lower())
    return (
        not dominio.es_pcstream(estacion["nombre"]),
        [(0, int(parte), "") if parte.isdigit() else (1, 0, parte) for parte in partes],
    )


def listar_estaciones(solo_activas: bool = True):
    """Las estaciones ordenadas por nombre (orden natural, ver _orden_natural);
    por defecto solo las activas."""
    with conexion_db() as conexion:
        if solo_activas:
            filas = conexion.execute("SELECT * FROM estaciones WHERE activa = 1").fetchall()
        else:
            filas = conexion.execute("SELECT * FROM estaciones").fetchall()
    return sorted(filas, key=_orden_natural)


def crear_estacion(nombre: str) -> int:
    """
    Crea una estación y devuelve su id. Si ya existe una DESACTIVADA con
    ese nombre exacto, la reactiva en vez de crear otra.

    Hace falta porque `nombre` es UNIQUE en el esquema sin importar
    `activa`: una estación desactivada (ver `desactivar_estacion`) no se
    borra, y un INSERT con el mismo nombre chocaría con la constraint y
    tiraría "ya existe". No hay botón "Reactivar" en la UI
    (`DialogoGestionEstaciones` solo lista las activas), así que "Agregar"
    con el mismo nombre es, en la práctica, la única forma de recuperarla.
    """
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la estación no puede quedar vacío.")
    with conexion_db() as conexion:
        inactiva = conexion.execute(
            "SELECT id FROM estaciones WHERE nombre = ? AND activa = 0", (nombre,)
        ).fetchone()
        if inactiva is not None:
            conexion.execute("UPDATE estaciones SET activa = 1 WHERE id = ?", (inactiva["id"],))
            return inactiva["id"]
        try:
            cursor = conexion.execute("INSERT INTO estaciones (nombre) VALUES (?)", (nombre,))
            return cursor.lastrowid
        except sqlite3.IntegrityError:
            raise ValueError(f"Ya existe una estación llamada '{nombre}'.")


def renombrar_estacion(estacion_id: int, nuevo_nombre: str):
    nuevo_nombre = nuevo_nombre.strip()
    if not nuevo_nombre:
        raise ValueError("El nombre de la estación no puede quedar vacío.")
    try:
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET nombre = ? WHERE id = ?", (nuevo_nombre, estacion_id))
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe una estación llamada '{nuevo_nombre}'.")


def desactivar_estacion(estacion_id: int):
    """
    Da de baja una estación (deja de listarse para asignarle bonos
    nuevos). No se borra del todo: si ya tiene sesiones en su historial,
    borrarla rompería esas referencias.
    """
    with conexion_db() as conexion:
        conexion.execute("UPDATE estaciones SET activa = 0 WHERE id = ?", (estacion_id,))


def registrar_conexion(estacion_id: int, ip: str = None, arranque: str = None):
    """
    Deja constancia de que el Cliente PC de esa estación acaba de preguntar
    su estado (GET /estado en servidor_red.py) -- es la única señal que
    tenemos de que la PC física está prendida, con el Cliente PC corriendo y
    con red hacia el mostrador. Se llama en TODO pedido válido, exista o
    no una sesión activa: una estación "enlazada" sin sesión es la que se
    muestra disponible en el dashboard.

    `ip` es la IP LAN desde la que llegó ese pedido (self.client_address
    en servidor_red.py, no un dato que mande el Cliente PC) -- se guarda en
    estaciones.ultima_ip, y si la estación todavía no tenía IP asentada (es
    su primer enlace, o el Admin la borró) también queda como ip_asentada,
    que después ya no se pisa sola (ver estado_de_estacion). Puede venir None
    (por ejemplo desde un test que no simula una conexión real); en ese caso
    no se toca ninguna IP.

    `arranque` identifica al Cliente PC abierto que hizo el pedido (ver
    cortes_pc_repo): se guarda en estaciones.cliente_arranque. Un Cliente PC
    viejo no lo manda (None) y queda el que había.

    De paso, la PC ya se enteró de que terminaron las sesiones suyas que se cerraron
    antes de esta consulta (ver avisos_fin_pc_repo): la respuesta le dice que no tiene.
    """
    ahora_texto = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        if ip:
            conexion.execute(
                """
                UPDATE estaciones SET ultima_conexion = ?, ultima_ip = ?,
                                      ip_asentada = COALESCE(ip_asentada, ?),
                                      cliente_arranque = COALESCE(?, cliente_arranque)
                WHERE id = ?
                """,
                (ahora_texto, ip, ip, arranque, estacion_id),
            )
        else:
            conexion.execute(
                """
                UPDATE estaciones SET ultima_conexion = ?, cliente_arranque = COALESCE(?, cliente_arranque)
                WHERE id = ?
                """,
                (ahora_texto, arranque, estacion_id),
            )
        avisos_fin_pc_repo.marcar_enterada(conexion, estacion_id, ahora_texto)


def obtener_estacion(estacion_id: int):
    """Fila cruda de una estación por id, incluidas sus IPs -- usada por
    el botón "Traer IP" de Gestionar Estaciones para releer el dato más
    fresco sin recargar toda la lista."""
    with conexion_db() as conexion:
        return conexion.execute(
            "SELECT * FROM estaciones WHERE id = ?", (estacion_id,)
        ).fetchone()


def borrar_ip_asentada(estacion_id: int):
    """Olvida la IP asentada de una estación (botón de Gestionar Estaciones,
    por ejemplo si se cambió la PC o su IP). La próxima vez que esa PC se
    conecte por su nombre, registrar_conexion asienta la IP nueva."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE estaciones SET ip_asentada = NULL WHERE id = ?", (estacion_id,))


def ips_asentadas_repetidas() -> set:
    """Las IPs asentadas en más de una estación activa. Con esas IPs no se
    reconoce a ninguna PC (estado_de_estacion no adivina) y Gestionar
    Estaciones lo avisa para que el Admin borre la que no corresponde."""
    with conexion_db() as conexion:
        filas = conexion.execute(
            """
            SELECT ip_asentada FROM estaciones
            WHERE activa = 1 AND ip_asentada IS NOT NULL
            GROUP BY ip_asentada HAVING COUNT(*) > 1
            """
        ).fetchall()
    return {fila["ip_asentada"] for fila in filas}


# ---------------------------------------------------------------------
# Bonos de tiempo (catálogo de combos vendibles)
# ---------------------------------------------------------------------

# Catálogo de bonos de walk-ins (tabla bonos_tiempo). La mecánica es la de
# CatalogoDeBonos; los bonos exclusivos de socios son OTRO catálogo, en
# bonos_miembro_repo. Un bono dado de baja (desactivar_bono) no se borra: queda
# referenciado desde sesion_bonos.
_catalogo_bonos = CatalogoDeBonos("bonos_tiempo")
listar_bonos = _catalogo_bonos.listar
obtener_bono = _catalogo_bonos.obtener
crear_bono = _catalogo_bonos.crear
modificar_bono = _catalogo_bonos.modificar
desactivar_bono = _catalogo_bonos.desactivar


# ---------------------------------------------------------------------
# Sesiones (uso de una estación)
# ---------------------------------------------------------------------

def estado_estaciones():
    """
    Para el dashboard de "Control de PCs": cada estación activa, con su
    sesión en curso (si tiene) y cuántos segundos le quedan, calculado al
    vuelo contra datetime.now() — mismo enfoque que
    turnos.turno_vencimiento, no se guarda un contador que haya que ir
    actualizando aparte. Si la sesión es de un Miembro, también trae su
    nombre (para mostrarlo en el mosaico en vez de un simple "Bono").

    También trae "enlazada": si el Cliente PC de esa PC preguntó su estado
    (ver registrar_conexion, actualizado desde servidor_red.py) hace
    UMBRAL_ENLACE_SEGUNDOS o menos. Es la única forma de distinguir una
    estación prendida-pero-libre de una apagada o sin red -- sin sesión
    activa, las dos se ven igual de "sin uso" si no se mira esto.

    Y "cortes": las veces que la PC estuvo en la alerta "SIN CLIENTE" durante
    la sesión en curso y volvió sola, con la causa (ver cortes_pc_repo).

    Y "reserva": la próxima reserva Pendiente de esa PC (o de PCSTREAM), como la
    arma reservas_horario_repo.pendientes, o None. Con "marcada" en True la PC ya
    se ve RESERVADA.

    Y "fin_sin_aviso": si a una PC sin sesión se le terminó la última y no se enteró
    (su Cliente PC no volvió a preguntar), ver avisos_fin_pc_repo.fin_sin_aviso.

    Y "deuda": lo que se debe en esa PC por la Cuenta de la PC (ver
    deudas_pc_repo.por_estacion), o None si no debe nada. Con "de_la_sesion", la
    cuenta de la sesión en curso (o None): las demás son de clientes anteriores
    que se fueron debiendo.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        estaciones = sorted(
            conexion.execute("SELECT * FROM estaciones WHERE activa = 1").fetchall(),
            key=_orden_natural,
        )
        sesiones = conexion.execute("""
            SELECT sesiones_pc.*, miembros.nombre AS miembro_nombre
            FROM sesiones_pc
            LEFT JOIN miembros ON miembros.id = sesiones_pc.miembro_id
            WHERE sesiones_pc.estado = ?
        """, (dominio.SESION_ACTIVA,)).fetchall()
        cortes = cortes_pc_repo.cortes_de_sesiones(conexion, [sesion["id"] for sesion in sesiones])
        reservas = reservas_horario_repo.pendientes(conexion, ahora)
        fines_pendientes = avisos_fin_pc_repo.pendientes(conexion)
        deudas = deudas_pc_repo.por_estacion(conexion)

    sesiones_por_estacion = {sesion["estacion_id"]: sesion for sesion in sesiones}

    estados = []
    for estacion in estaciones:
        sesion = sesiones_por_estacion.get(estacion["id"])
        cortes_de_la_sesion = cortes.get(sesion["id"], []) if sesion is not None else []
        estado = _estado_para_estacion(estacion, sesion, ahora, cortes_de_la_sesion,
                                       fines_pendientes.get(estacion["id"]))
        estado["reserva"] = reservas_horario_repo.proxima(reservas, estacion)
        deuda = deudas.get(estacion["id"])
        if deuda is not None:
            deuda["de_la_sesion"] = next(
                (cuenta for cuenta in deuda["cuentas"] if sesion is not None and cuenta["sesion_id"] == sesion["id"]),
                None,
            )
        estado["deuda"] = deuda
        estados.append(estado)
    return estados


def _estado_para_estacion(estacion, sesion, ahora, cortes=(), fin_pendiente=None):
    """Misma cuenta para la grilla y para la consulta individual de un Cliente PC
    (esa no necesita los cortes: ver estado_de_estacion). `fin_pendiente`: la última
    sesión de esa PC que todavía no se sabe si se enteró de su fin (avisos_fin_pc_repo)."""
    segundos_restantes = None
    if sesion is not None:
        fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
        segundos_restantes = dominio.segundos_restantes(fin_previsto, ahora)

    enlazada = False
    ultima_conexion = None
    if estacion["ultima_conexion"] is not None:
        ultima_conexion = datetime.fromisoformat(estacion["ultima_conexion"])
        enlazada = (ahora - ultima_conexion).total_seconds() <= UMBRAL_ENLACE_SEGUNDOS

    # Una PC habilitada antes de encender su Cliente PC está esperando; una
    # que ya estuvo enlazada y dejó de responder necesita una alerta.
    cliente_cerrado_admin_desde = None
    if estacion["cliente_cerrado_desde"] is not None and not enlazada:
        cliente_cerrado_admin_desde = datetime.fromisoformat(estacion["cliente_cerrado_desde"])

    # Sin sesión y sin noticias desde que se terminó la última: la PC no se enteró y
    # puede que sigan usándola. Una PC con el Cliente PC cerrado desde su panel admin
    # ya está a la vista como "Sin bloqueo".
    fin_sin_aviso = None
    if sesion is None and cliente_cerrado_admin_desde is None:
        fin_sin_aviso = avisos_fin_pc_repo.fin_sin_aviso(fin_pendiente, estacion, ahora, UMBRAL_ENLACE_SEGUNDOS)

    esperando_cliente = False
    if sesion is not None and not enlazada and cliente_cerrado_admin_desde is None:
        inicio_sesion = datetime.fromisoformat(sesion["fecha_inicio"])
        esperando_cliente = (
            ultima_conexion is None
            or (inicio_sesion - ultima_conexion).total_seconds() > UMBRAL_ENLACE_SEGUNDOS
        )

    return {
        "dispositivo": dominio.DISPOSITIVO_PC,
        # La PC de streaming: se le venden los bonos de pcstream_repo, no los comunes.
        "es_pcstream": dominio.es_pcstream(estacion["nombre"]),
        "estacion": estacion,
        "sesion": sesion,
        "segundos_restantes": segundos_restantes,
        "enlazada": enlazada,
        # La del procesador y la placa de video ({"cpu", "gpu"}), solo si está enlazada.
        "temperatura": temperatura_pc_repo.vigente(estacion, enlazada),
        # La última vez que preguntó su Cliente PC (None = nunca): de cuándo es la última noticia.
        "ultima_conexion": ultima_conexion,
        "esperando_cliente": esperando_cliente,
        "cliente_cerrado_admin_desde": cliente_cerrado_admin_desde,
        "cortes": list(cortes),
        "fin_sin_aviso": fin_sin_aviso,
        # Solo la completa estado_estaciones (la grilla): al Cliente PC le llega
        # aparte, en su propio try (servidor_red, "reserva"), para que nunca toque el bloqueo.
        "reserva": None,
        # Solo la completa estado_estaciones: la Cuenta de la PC es cosa del mostrador.
        "deuda": None,
    }


def estado_de_estacion(nombre: str, ip: str = None):
    """
    Como estado_estaciones(), pero para una sola estación -- es lo que
    consulta el Cliente PC de cada estación (ver servidor_red.py y la carpeta
    hermana "CLIENTE PC") para decidir si debe mostrarse bloqueada o no.

    Es el ÚNICO lugar que decide qué estación es una PC que se conecta
    (pedido del dueño, 2026-10-17): primero por el nombre que manda su Cliente
    PC; si ninguna estación activa se llama así, por la IP desde la que llegó
    el pedido (`ip`, la del socket), comparada con la IP asentada en su primer
    enlace. Así sigue andando una PC cuyo nombre se cambió acá o se tipeó
    distinto allá. Si esa IP está asentada en más de una estación activa no se
    adivina (ver ips_asentadas_repetidas). Devuelve None si no se la reconoce.
    """
    with conexion_db() as conexion:
        estacion = conexion.execute(
            "SELECT * FROM estaciones WHERE nombre = ? AND activa = 1", (nombre,)
        ).fetchone()
        if estacion is None and ip:
            por_ip = conexion.execute(
                "SELECT * FROM estaciones WHERE ip_asentada = ? AND activa = 1 LIMIT 2", (ip,)
            ).fetchall()
            if len(por_ip) == 1:
                estacion = por_ip[0]
        if estacion is None:
            return None
        sesion = conexion.execute(
            """
            SELECT sesiones_pc.*, miembros.nombre AS miembro_nombre
            FROM sesiones_pc
            LEFT JOIN miembros ON miembros.id = sesiones_pc.miembro_id
            WHERE sesiones_pc.estacion_id = ? AND sesiones_pc.estado = ?
            ORDER BY sesiones_pc.id DESC LIMIT 1
            """,
            (estacion["id"], dominio.SESION_ACTIVA),
        ).fetchone()
        # Si volvió después de que se le terminó una sesión sin enterarse, el corte se anota
        # (cortes_pc_repo). Con una sesión en curso no hace falta mirar.
        fin_pendiente = (avisos_fin_pc_repo.pendientes(conexion, estacion["id"]).get(estacion["id"])
                         if sesion is None else None)
    return _estado_para_estacion(estacion, sesion, datetime.now(), fin_pendiente=fin_pendiente)


def _abrir_o_extender_sesion(conexion, estacion_id: int, minutos: int, ahora: datetime, miembro_id: int = None) -> int:
    """
    Crea una sesión nueva para la estación si no tiene una activa, o le
    suma `minutos` a la que ya está en curso (el cliente sigue jugando).
    Devuelve el id de la sesión. Compartido entre `asignar_bono` (bono
    vendido por el mostrador) y `miembros_repo.abrir_estacion_por_miembro`
    (socio que abre con su propio saldo) — la mecánica de "sumar tiempo a
    una estación" es la misma, solo cambia de dónde sale el tiempo.

    `miembro_id` se graba solo al CREAR la sesión (identifica si viene
    del saldo de ese socio o es un walk-in/bono, ver
    pcs_repo.finalizar_sesion y database.miembros); si se está
    extendiendo una sesión que ya existía, se respeta lo que ya tenía.

    Una sesión que ya llegó a cero no se estira: se cierra y se abre otra.
    Normalmente la cierra el refresco de la pantalla de PCs a los pocos
    segundos, pero con nadie logueado en el mostrador no hay pantalla, y un
    socio que entraba a esa PC quedaba pegado a la sesión del cliente
    anterior y la PC mostraba el nombre del otro (revisión del 2026-10-20).
    """
    sesion = conexion.execute(
        "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
        (estacion_id, dominio.SESION_ACTIVA),
    ).fetchone()
    if sesion is not None and dominio.segundos_restantes(
        datetime.fromisoformat(sesion["fecha_fin_prevista"]), ahora
    ) == 0:
        _cerrar_sesion(conexion, sesion, ahora)
        sesion = None

    if sesion is None:
        fin_previsto = dominio.fin_al_sumar_minutos(None, minutos, ahora)
        cursor = conexion.execute(
            """
            INSERT INTO sesiones_pc (estacion_id, fecha_inicio, fecha_fin_prevista, estado, miembro_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (estacion_id, ahora.isoformat(timespec="seconds"),
             fin_previsto.isoformat(timespec="seconds"), dominio.SESION_ACTIVA, miembro_id),
        )
        return cursor.lastrowid

    fin_previo = datetime.fromisoformat(sesion["fecha_fin_prevista"])
    fin_previsto = dominio.fin_al_sumar_minutos(fin_previo, minutos, ahora)
    conexion.execute(
        "UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
        (fin_previsto.isoformat(timespec="seconds"), sesion["id"]),
    )
    return sesion["id"]


def asignar_bono(estacion_id: int, bono_id: int, usuario_id: int, pagos: list) -> int:
    """
    Vende un bono de tiempo para una estación: si no tiene sesión activa,
    arranca una nueva; si ya tiene una en curso (el cliente sigue
    jugando), le suma los minutos del bono a la que ya está abierta en
    vez de crear otra. Devuelve el id de la venta generada.

    `pagos`: lista de {"metodo", "monto"} -- una sola fila para Efectivo
    o Digital, dos filas si pagaron una parte en cada medio, ver
    control_pcs/ui/pcs_detalle.PanelDetalleEstacion._cobrar_bono.

    Solo sirve para una PC (una fila activa de `estaciones`). El bono se busca
    en el catálogo que le toca a ESA PC: el de PCSTREAM (pcstream_repo) si es la
    PC de streaming, el común (bonos_tiempo) si no -- así a PCSTREAM nunca se le
    cobra un bono común ni a otra PC uno de PCSTREAM (la pantalla, además, toma
    el bono de la lista del equipo elegido). La PlayStation 5 tiene su propio
    camino y su propio catálogo (ver playstation_repo.vender_bono) y no es una
    estación: no hay forma de que un bono de PC termine en la consola ni al revés.

    Lo cobrado entra como Alquiler de PCs, también el de PCSTREAM (es una PC);
    cuánto vendió PCSTREAM se ve en Reportes (pcstream_repo.uso_por_dia).
    """
    ahora = datetime.now()

    with conexion_db() as conexion:
        estacion = conexion.execute(
            "SELECT nombre FROM estaciones WHERE id = ? AND activa = 1", (estacion_id,)
        ).fetchone()
        if estacion is None:
            raise ValueError("Esa PC ya no está disponible. Actualizá la pantalla e intentá de nuevo.")

        # Cada catálogo tiene su tabla de vínculo con la sesión (ver
        # database_esquema, "PCSTREAM"): sesion_bonos solo admite bonos comunes.
        if dominio.es_pcstream(estacion["nombre"]):
            bono, tabla_vinculo = pcstream_repo.obtener_bono(bono_id), "sesion_pcstream_bonos"
        else:
            bono, tabla_vinculo = obtener_bono(bono_id), "sesion_bonos"
        if bono is None or not bono["activo"]:
            raise ValueError("Ese bono ya no está disponible.")

        sesion_id = _abrir_o_extender_sesion(conexion, estacion_id, bono["minutos"], ahora)

        venta_id = ventas_repo.registrar_venta_sin_detalle(
            conexion, usuario_id, bono["precio"], pagos, dominio.ORIGEN_ALQUILER_PCS, ahora
        )
        conexion.execute(
            f"""
            INSERT INTO {tabla_vinculo} (sesion_id, bono_id, minutos, precio, venta_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sesion_id, bono_id, bono["minutos"], round(bono["precio"], 2), venta_id),
        )
        return venta_id


def trasladar_sesion(estacion_origen_id: int, estacion_destino_id: int, usuario_id: int) -> dict:
    """
    Pasa la sesión activa de una PC a otra sin perder tiempo ni cobrar de
    nuevo: el cliente se sentó en la PC que había libre y quiere pasarse a
    su favorita cuando se libera (o dos clientes quieren cambiarse de
    lugar entre ellos). Es la MISMA sesión con otro `estacion_id` -- el
    vencimiento (`fecha_fin_prevista`), los bonos, el saldo del socio y el
    reintegro no se tocan.

    - Destino libre: la sesión se MUEVE. La PC de origen queda sin sesión
      y su Cliente PC la bloquea y reinicia sola (mismo camino que cuando
      se acaba el tiempo).
    - Destino ocupado: las dos sesiones se INTERCAMBIAN. Las dos PCs
      siguen con sesión (cada una con la del otro cliente), así que ninguna
      se reinicia.
    - Destino con una sesión que ya venció pero que el refresco automático
      todavía no dio de baja: se la da de baja acá y cuenta como libre.
    - PCSTREAM no entra, ni como origen ni como destino: tiene sus propios
      precios y no la pueden usar los socios, y pasarle una sesión (o sacarle la
      suya) le daría a una PC el tiempo cobrado con la tarifa de la otra.

    Todo corre con "BEGIN IMMEDIATE", mismo motivo que `finalizar_sesion`:
    comprobar el estado de las dos PCs y moverlas es un solo paso, para que
    un cierre simultáneo desde el mostrador o desde la PC del cliente no
    deje una sesión ya cerrada apareciendo en otra estación.

    Devuelve {"tipo": "MOVER" | "INTERCAMBIAR", "origen": nombre,
    "destino": nombre}. Levanta ValueError (mensaje listo para mostrar) si
    algo ya no es como lo veía la pantalla.
    """
    if estacion_origen_id == estacion_destino_id:
        raise ValueError("Elegí una PC distinta a la actual.")

    ahora = datetime.now()
    ahora_iso = ahora.isoformat(timespec="microseconds")

    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")

        origen = conexion.execute(
            "SELECT * FROM estaciones WHERE id = ? AND activa = 1", (estacion_origen_id,)
        ).fetchone()
        destino = conexion.execute(
            "SELECT * FROM estaciones WHERE id = ? AND activa = 1", (estacion_destino_id,)
        ).fetchone()
        if origen is None or destino is None:
            raise ValueError("Esa PC ya no está disponible. Actualizá la pantalla e intentá de nuevo.")
        if dominio.es_pcstream(origen["nombre"]) or dominio.es_pcstream(destino["nombre"]):
            raise ValueError(
                f"{dominio.NOMBRE_PCSTREAM} tiene sus propios precios: no se le puede pasar "
                "la sesión de otra PC ni pasar la suya a otra."
            )

        sesion_origen = conexion.execute(
            "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
            (estacion_origen_id, dominio.SESION_ACTIVA),
        ).fetchone()
        if sesion_origen is None or datetime.fromisoformat(sesion_origen["fecha_fin_prevista"]) <= ahora:
            raise ValueError(f"'{origen['nombre']}' ya no tiene una sesión activa.")

        sesion_destino = conexion.execute(
            "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
            (estacion_destino_id, dominio.SESION_ACTIVA),
        ).fetchone()
        if sesion_destino is not None and datetime.fromisoformat(sesion_destino["fecha_fin_prevista"]) <= ahora:
            conexion.execute(
                "UPDATE sesiones_pc SET estado = ?, fecha_fin_real = ? WHERE id = ?",
                (dominio.SESION_FINALIZADA, ahora.isoformat(timespec="seconds"), sesion_destino["id"]),
            )
            sesion_destino = None

        movimientos = [(sesion_origen["id"], estacion_origen_id, estacion_destino_id)]
        if sesion_destino is not None:
            movimientos.append((sesion_destino["id"], estacion_destino_id, estacion_origen_id))

        for sesion_id, desde_id, hacia_id in movimientos:
            conexion.execute(
                "UPDATE sesiones_pc SET estacion_id = ? WHERE id = ?", (hacia_id, sesion_id)
            )
            conexion.execute(
                """
                INSERT INTO traslados_sesion
                    (sesion_id, estacion_origen_id, estacion_destino_id, fecha, usuario_id)
                VALUES (?, ?, ?, ?, ?)
                """,
                (sesion_id, desde_id, hacia_id, ahora_iso, usuario_id),
            )

    return {
        "tipo": "INTERCAMBIAR" if sesion_destino is not None else "MOVER",
        "origen": origen["nombre"],
        "destino": destino["nombre"],
    }


def finalizar_sesion(sesion_id: int):
    """
    Cierra una sesión en curso: la usa tanto "Finalizar antes de tiempo"
    como el refresco automático de la pantalla cuando el tiempo restante
    llega a 0.

    Si a la sesión, en algún momento, la financió (total o parcialmente)
    el saldo de un socio y todavía quedaba tiempo sin usar, ESE tramo --
    y ningún otro, ver reintegros_repo.reintegros_por_miembro -- se le devuelve a su
    saldo en bloques de 30 minutos, aunque la sesión se haya reutilizado
    mezclando un bono del mostrador de por medio. A diferencia de un bono
    (consumible de una sola vez, sin reintegro), el saldo de un socio es
    plata suya: cortar antes no se la hace perder.

    Corre con "BEGIN IMMEDIATE" (toma el lock de escritura de entrada,
    antes de leer nada) -- mismo motivo que
    miembros_repo.abrir_estacion_por_miembro. Comprobar que la sesión
    sigue ACTIVA y cerrarla son dos pasos, y el socio cerrando desde su PC
    (POST /logout) y la empleada tocando "Finalizar antes de tiempo" son
    dos pedidos legítimos en hilos distintos: sin el lock, los dos leían
    la sesión ACTIVA y reintegraban el tiempo restante por separado (un
    socio con 30 minutos por devolver terminaba con 60). Con el lock, el
    segundo pedido espera, la lee ya FINALIZADA, y sale por el primer
    "return" sin reintegrar nada de nuevo.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")

        sesion = conexion.execute(
            "SELECT * FROM sesiones_pc WHERE id = ? AND estado = ?",
            (sesion_id, dominio.SESION_ACTIVA),
        ).fetchone()
        if sesion is None:
            return
        _cerrar_sesion(conexion, sesion, ahora)


def _cerrar_sesion(conexion, sesion, ahora: datetime):
    """
    El núcleo de finalizar_sesion, dentro de una transacción ya abierta (la usa
    también _abrir_o_extender_sesion con una sesión que ya llegó a cero).

    La hora de fin real nunca pasa de la prevista: una sesión que llegó a cero
    a las 02:30 terminó a las 02:30 aunque se cierre más tarde (con nadie
    logueado en el mostrador, nadie la cierra hasta que alguien entra). Si no,
    "Actividad reciente" y el uso real de PCSTREAM mostrarían la hora del
    ingreso al mostrador.
    """
    fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
    # Queda PENDIENTE hasta que la PC vuelva a preguntar y reciba "sin sesión"
    # (ver avisos_fin_pc_repo): si no pregunta, la grilla avisa.
    conexion.execute(
        "UPDATE sesiones_pc SET estado = ?, fecha_fin_real = ?, aviso_fin = ? WHERE id = ?",
        (dominio.SESION_FINALIZADA, min(ahora, fin_previsto).isoformat(timespec="seconds"),
         dominio.AVISO_FIN_PENDIENTE, sesion["id"]),
    )

    minutos_restantes = dominio.segundos_restantes(fin_previsto, ahora) // 60
    if minutos_restantes <= 0:
        return

    reintegros = reintegros_por_miembro(conexion, sesion["id"], minutos_restantes)
    for miembro_id, minutos_a_reintegrar in reintegros.items():
        conexion.execute(
            "UPDATE miembros SET saldo_minutos = saldo_minutos + ? WHERE id = ?",
            (minutos_a_reintegrar, miembro_id),
        )
        conexion.execute(
            """
            INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (miembro_id, dominio.MOVIMIENTO_REINTEGRO, minutos_a_reintegrar,
             ahora.isoformat(timespec="seconds"), sesion["id"]),
        )
