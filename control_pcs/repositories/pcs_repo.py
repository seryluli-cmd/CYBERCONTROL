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
bonos, estado en vivo del dashboard, abrir/extender/trasladar/finalizar una
sesión (con el reintegro de saldo a socios) y el feed de actividad reciente.
"""

import sqlite3
from datetime import datetime
import dominio
from database import conexion_db
from repositories import ventas_repo
from control_pcs.repositories import accesos_admin_pc_repo, playstation_repo
from control_pcs.repositories.catalogo_bonos import CatalogoDeBonos

# Más que el intervalo de consulta del Cliente PC (5s, ver
# control_pcs/ui/pcs_window.py) para darle margen de red antes de
# considerar "sin conexión" a una estación que en realidad sigue
# prendida -- se resetea a "enlazada" en su próxima consulta, sin
# necesitar que nadie la reinicie a mano.
UMBRAL_ENLACE_SEGUNDOS = 15

# Mismo valor que miembros_repo.MINUTOS_POR_FRACCION (no se importa de
# ahí a propósito: miembros_repo ya importa este módulo, e importar en
# el otro sentido crearía un ciclo -- son dos constantes que hoy
# coinciden en valor pero describen granularidades de negocio distintas).
MINUTOS_POR_FRACCION = 30


# ---------------------------------------------------------------------
# Estaciones (catálogo de PCs físicas)
# ---------------------------------------------------------------------

def listar_estaciones(solo_activas: bool = True):
    """Las estaciones ordenadas por nombre; por defecto solo las activas."""
    with conexion_db() as conexion:
        if solo_activas:
            return conexion.execute(
                "SELECT * FROM estaciones WHERE activa = 1 ORDER BY nombre"
            ).fetchall()
        return conexion.execute("SELECT * FROM estaciones ORDER BY nombre").fetchall()


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


def registrar_conexion(estacion_id: int, ip: str = None):
    """
    Deja constancia de que el Cliente PC de esa estación acaba de preguntar
    su estado (GET /estado en servidor_red.py) -- es la única señal que
    tenemos de que la PC física está prendida, con el Cliente PC corriendo y
    con red hacia el mostrador. Se llama en TODO pedido válido, exista o
    no una sesión activa: una estación "enlazada" sin sesión es la que se
    muestra disponible en el dashboard.

    `ip` es la IP LAN desde la que llegó ese pedido (self.client_address
    en servidor_red.py, no un dato que mande el Cliente PC) -- se guarda en
    estaciones.ultima_ip, que es lo que lee el botón "Traer IP" de
    Gestionar Estaciones. Puede venir None (por ejemplo desde un test que
    no simula una conexión real); en ese caso no se pisa la IP ya
    guardada.
    """
    with conexion_db() as conexion:
        if ip:
            conexion.execute(
                "UPDATE estaciones SET ultima_conexion = ?, ultima_ip = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), ip, estacion_id),
            )
        else:
            conexion.execute(
                "UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                (datetime.now().isoformat(timespec="seconds"), estacion_id),
            )


def obtener_estacion(estacion_id: int):
    """Fila cruda de una estación por id, incluida ultima_ip -- usada por
    el botón "Traer IP" de Gestionar Estaciones para releer el dato más
    fresco sin recargar toda la lista."""
    with conexion_db() as conexion:
        return conexion.execute(
            "SELECT * FROM estaciones WHERE id = ?", (estacion_id,)
        ).fetchone()


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
    nombre (para mostrarlo en la tabla en vez de un simple "Activa").

    También trae "enlazada": si el Cliente PC de esa PC preguntó su estado
    (ver registrar_conexion, actualizado desde servidor_red.py) hace
    UMBRAL_ENLACE_SEGUNDOS o menos. Es la única forma de distinguir una
    estación prendida-pero-libre de una apagada o sin red -- sin sesión
    activa, las dos se ven igual de "sin uso" si no se mira esto.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        estaciones = conexion.execute(
            "SELECT * FROM estaciones WHERE activa = 1 ORDER BY nombre"
        ).fetchall()
        sesiones = conexion.execute("""
            SELECT sesiones_pc.*, miembros.nombre AS miembro_nombre
            FROM sesiones_pc
            LEFT JOIN miembros ON miembros.id = sesiones_pc.miembro_id
            WHERE sesiones_pc.estado = ?
        """, (dominio.SESION_ACTIVA,)).fetchall()

    sesiones_por_estacion = {sesion["estacion_id"]: sesion for sesion in sesiones}

    resultado = []
    for estacion in estaciones:
        sesion = sesiones_por_estacion.get(estacion["id"])
        segundos_restantes = None
        if sesion is not None:
            fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
            segundos_restantes = dominio.segundos_restantes(fin_previsto, ahora)

        enlazada = False
        ultima_conexion = None
        if estacion["ultima_conexion"] is not None:
            ultima_conexion = datetime.fromisoformat(estacion["ultima_conexion"])
            enlazada = (ahora - ultima_conexion).total_seconds() <= UMBRAL_ENLACE_SEGUNDOS

        # Sesión activa en una PC que NO estaba enlazada cuando arrancó la
        # sesión y todavía no se conectó desde entonces: el operador la
        # habilitó antes de que el cliente la prendiera (típico cuando
        # llegan muchos juntos). El tiempo ya corre desde que se activó el
        # bono -- el Cliente PC, al prenderse, lo toma solo del servidor --
        # pero esto NO es una alerta: es una espera normal. La alerta de
        # "SIN CLIENTE" queda para una PC que SÍ estuvo enlazada durante la
        # sesión (o justo antes) y dejó de responder.
        #
        # Si en cambio alguien cerró el Cliente PC desde su panel admin
        # (ver accesos_admin_pc_repo), la PC NO va a volver sola: tampoco es
        # una espera normal, es una PC sin bloqueo con tiempo pago corriendo.
        cliente_cerrado_admin_desde = None
        if estacion["cliente_cerrado_desde"] is not None and not enlazada:
            cliente_cerrado_admin_desde = datetime.fromisoformat(estacion["cliente_cerrado_desde"])

        esperando_cliente = False
        if sesion is not None and not enlazada and cliente_cerrado_admin_desde is None:
            inicio_sesion = datetime.fromisoformat(sesion["fecha_inicio"])
            esperando_cliente = (
                ultima_conexion is None
                or (inicio_sesion - ultima_conexion).total_seconds() > UMBRAL_ENLACE_SEGUNDOS
            )

        resultado.append({
            # La grilla mezcla estas filas con la de la PlayStation 5 (ver
            # playstation_repo.estado): esto es lo que las distingue.
            "dispositivo": dominio.DISPOSITIVO_PC,
            "estacion": estacion,
            "sesion": sesion,
            "segundos_restantes": segundos_restantes,
            "enlazada": enlazada,
            "esperando_cliente": esperando_cliente,
            # datetime desde cuándo la PC está sin Cliente PC por un cierre
            # desde el panel admin, o None (ver comentario de arriba).
            "cliente_cerrado_admin_desde": cliente_cerrado_admin_desde,
        })
    return resultado


def estado_de_estacion(nombre: str):
    """
    Como estado_estaciones(), pero para una sola estación por nombre --
    es lo que consulta el Cliente PC de cada estación (ver
    servidor_red.py y la carpeta hermana "CLIENTE PC") para
    decidir si debe mostrarse bloqueada o no. Devuelve None si no existe
    una estación activa con ese nombre.
    """
    for item in estado_estaciones():
        if item["estacion"]["nombre"] == nombre:
            return item
    return None


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
    """
    sesion = conexion.execute(
        "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
        (estacion_id, dominio.SESION_ACTIVA),
    ).fetchone()

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

    # Si ya venció y todavía no se finalizó (el refresco automático de la
    # pantalla no pasó todavía), el tiempo nuevo se cuenta desde ahora, no
    # desde un vencimiento que ya pasó (eso lo decide fin_al_sumar_minutos,
    # la misma cuenta que usa la PlayStation 5).
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
    o Digital, dos filas (Efectivo + Digital) para un cobro Mixto, ver
    control_pcs/ui/pcs_detalle.PanelDetalleEstacion._confirmar_bono.

    Solo sirve para una PC (una fila activa de `estaciones`) con un bono de
    ESTE catálogo (bonos_tiempo). La PlayStation 5 tiene su propio camino y su
    propio catálogo (ver playstation_repo.vender_bono) y no es una estación:
    no hay forma de que un bono de PC termine en la consola ni al revés.
    """
    bono = obtener_bono(bono_id)
    if bono is None or not bono["activo"]:
        raise ValueError("Ese bono ya no está disponible.")

    ahora = datetime.now()

    with conexion_db() as conexion:
        if conexion.execute(
            "SELECT 1 FROM estaciones WHERE id = ? AND activa = 1", (estacion_id,)
        ).fetchone() is None:
            raise ValueError("Esa PC ya no está disponible. Actualizá la pantalla e intentá de nuevo.")

        sesion_id = _abrir_o_extender_sesion(conexion, estacion_id, bono["minutos"], ahora)

        venta_id = ventas_repo.registrar_venta_sin_detalle(
            conexion, usuario_id, bono["precio"], pagos, dominio.ORIGEN_ALQUILER_PCS, ahora
        )
        conexion.execute(
            """
            INSERT INTO sesion_bonos (sesion_id, bono_id, minutos, precio, venta_id)
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


def _contribuciones_de_sesion(conexion, sesion_id: int):
    """
    Reconstruye, en orden cronológico, de dónde salió cada tramo de
    minutos que se le fue sumando a una sesión (bono del mostrador o
    saldo de un socio) -- no hace falta una tabla nueva para esto:
    sesion_bonos y movimientos_saldo_miembro (tipo CONSUMO) ya guardan
    cada aporte por otras razones (facturación, ledger de saldo). El
    orden de aparición coincide con el orden en que se fueron sumando a
    la sesión porque asignar_bono() y abrir_estacion_por_miembro() usan
    el mismo `ahora` tanto para extender la sesión (_abrir_o_extender_sesion)
    como para grabar su propio registro -- ver _reintegros_por_miembro,
    el único que usa esto.
    """
    return conexion.execute(
        """
        SELECT 'BONO' AS tipo, NULL AS miembro_id, sb.minutos AS minutos, v.fecha AS fecha
        FROM sesion_bonos sb
        JOIN ventas v ON v.id = sb.venta_id
        WHERE sb.sesion_id = ?
        UNION ALL
        SELECT 'SOCIO' AS tipo, m.miembro_id AS miembro_id, m.minutos AS minutos, m.fecha AS fecha
        FROM movimientos_saldo_miembro m
        WHERE m.sesion_id = ? AND m.tipo = ?
        ORDER BY fecha
        """,
        (sesion_id, sesion_id, dominio.MOVIMIENTO_CONSUMO),
    ).fetchall()


def _reintegros_por_miembro(conexion, sesion_id: int, minutos_restantes: int) -> dict:
    """
    De los minutos que le quedaban a una sesión al cortarla, calcula
    cuántos hay que devolverle a CADA socio que la financió -- nunca a un
    socio distinto del que puso ese tramo, y nunca a costa de un bono
    (ver finalizar_sesion).

    No alcanza con mirar `sesiones_pc.miembro_id`: se graba solo al CREAR
    la sesión (ver _abrir_o_extender_sesion), y una sesión puede haberse
    extendido después con un bono del mostrador o con el saldo de OTRO
    socio. Por eso se reconstruye el aporte de cada uno.

    El tiempo restante es siempre el TRAMO MÁS NUEVO de la sesión (el
    reloj cuenta para atrás desde fecha_fin_prevista, y cada aporte nuevo
    -- bono o saldo -- estira ese final más lejos en el tiempo): por eso
    se recorren las contribuciones de atrás para adelante, "gastando"
    minutos_restantes contra cada una hasta agotarlo. El tramo de cada
    aporte de un socio que cae, total o parcialmente, dentro de esa cola
    se le suma a lo que hay que devolverle a ESE socio puntual --
    redondeado hacia abajo a bloques de 30 al final, cada socio por
    separado (mismo criterio que el resto del sistema). El tramo que cae
    en un aporte de tipo BONO simplemente se descarta: un bono no
    reintegra, se pierda o no dentro del tiempo restante.
    """
    contribuciones = _contribuciones_de_sesion(conexion, sesion_id)
    restantes = minutos_restantes
    por_miembro = {}
    for fila in reversed(contribuciones):
        if restantes <= 0:
            break
        tramo = min(fila["minutos"], restantes)
        if fila["tipo"] == "SOCIO":
            por_miembro[fila["miembro_id"]] = por_miembro.get(fila["miembro_id"], 0) + tramo
        restantes -= tramo
    return {
        miembro_id: (minutos // MINUTOS_POR_FRACCION) * MINUTOS_POR_FRACCION
        for miembro_id, minutos in por_miembro.items()
        if minutos >= MINUTOS_POR_FRACCION
    }


def finalizar_sesion(sesion_id: int):
    """
    Cierra una sesión en curso: la usa tanto "Finalizar antes de tiempo"
    como el refresco automático de la pantalla cuando el tiempo restante
    llega a 0.

    Si a la sesión, en algún momento, la financió (total o parcialmente)
    el saldo de un socio y todavía quedaba tiempo sin usar, ESE tramo --
    y ningún otro, ver _reintegros_por_miembro -- se le devuelve a su
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

        conexion.execute(
            "UPDATE sesiones_pc SET estado = ?, fecha_fin_real = ? WHERE id = ?",
            (dominio.SESION_FINALIZADA, ahora.isoformat(timespec="seconds"), sesion_id),
        )

        fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
        segundos_restantes = dominio.segundos_restantes(fin_previsto, ahora)
        minutos_restantes = segundos_restantes // 60
        if minutos_restantes <= 0:
            return

        reintegros = _reintegros_por_miembro(conexion, sesion_id, minutos_restantes)
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
                 ahora.isoformat(timespec="seconds"), sesion_id),
            )


def actividad_reciente(limite: int = 30):
    """
    Feed de eventos recientes para el panel de actividad de "Control de
    PCs". No existe una tabla de log aparte: esto relee
    sesiones_pc/sesion_bonos/movimientos_saldo_miembro, que ya guardan
    todo esto por otras razones (facturación, auditoría de saldo de
    socios) — acá solo se junta todo, se ordena por fecha y se corta a
    `limite`. Devuelve datos crudos; el texto para mostrar se arma en la
    UI (ver control_pcs/ui/pcs_actividad.py:_texto_evento), no acá. Incluye los
    movimientos de la PlayStation 5.
    """
    eventos = []
    with conexion_db() as conexion:
        for fila in conexion.execute("""
            SELECT s.fecha_inicio AS fecha, e.nombre AS estacion_nombre
            FROM sesiones_pc s JOIN estaciones e ON e.id = s.estacion_id
            ORDER BY s.fecha_inicio DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "INICIO",
                             "estacion_nombre": fila["estacion_nombre"]})

        for fila in conexion.execute("""
            SELECT s.fecha_fin_real AS fecha, e.nombre AS estacion_nombre
            FROM sesiones_pc s JOIN estaciones e ON e.id = s.estacion_id
            WHERE s.fecha_fin_real IS NOT NULL
            ORDER BY s.fecha_fin_real DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "FIN",
                             "estacion_nombre": fila["estacion_nombre"]})

        for fila in conexion.execute("""
            SELECT v.fecha AS fecha, e.nombre AS estacion_nombre,
                   b.nombre AS bono_nombre, sb.precio AS precio
            FROM sesion_bonos sb
            JOIN ventas v ON v.id = sb.venta_id
            JOIN bonos_tiempo b ON b.id = sb.bono_id
            JOIN sesiones_pc s ON s.id = sb.sesion_id
            JOIN estaciones e ON e.id = s.estacion_id
            ORDER BY v.fecha DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "BONO",
                             "estacion_nombre": fila["estacion_nombre"],
                             "bono_nombre": fila["bono_nombre"], "precio": fila["precio"]})

        for fila in conexion.execute("""
            SELECT m.fecha AS fecha, m.tipo AS tipo, m.minutos AS minutos,
                   mi.nombre AS miembro_nombre, e.nombre AS estacion_nombre, v.total AS monto
            FROM movimientos_saldo_miembro m
            JOIN miembros mi ON mi.id = m.miembro_id
            LEFT JOIN sesiones_pc s ON s.id = m.sesion_id
            LEFT JOIN estaciones e ON e.id = s.estacion_id
            LEFT JOIN ventas v ON v.id = m.venta_id
            ORDER BY m.fecha DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": fila["tipo"],
                             "miembro_nombre": fila["miembro_nombre"],
                             "estacion_nombre": fila["estacion_nombre"],
                             "minutos": fila["minutos"], "monto": fila["monto"]})

        # Los eventos de arriba toman el nombre de la estación de
        # sesiones_pc.estacion_id, que es la ACTUAL: si una sesión se pasó
        # de PC (ver trasladar_sesion), su INICIO/BONO se muestran en la PC
        # nueva. Estos eventos TRASLADO dejan a la vista el recorrido.
        for fila in conexion.execute("""
            SELECT t.fecha AS fecha, eo.nombre AS origen_nombre, ed.nombre AS destino_nombre
            FROM traslados_sesion t
            JOIN estaciones eo ON eo.id = t.estacion_origen_id
            JOIN estaciones ed ON ed.id = t.estacion_destino_id
            ORDER BY t.fecha DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "TRASLADO",
                             "origen_nombre": fila["origen_nombre"],
                             "destino_nombre": fila["destino_nombre"]})

        for fila in accesos_admin_pc_repo.listar_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "ADMIN_PC",
                             "evento_admin": fila["tipo"],
                             "estacion_nombre": fila["estacion_nombre"],
                             "segundos_sin_cliente": fila["segundos_sin_cliente"]})

    # La PlayStation 5 comparte el panel con las PCs: sus sesiones y bonos
    # llegan con la misma forma (ver playstation_repo.eventos_recientes).
    eventos.extend(playstation_repo.eventos_recientes(limite))

    eventos.sort(key=lambda evento: evento["fecha"], reverse=True)
    return eventos[:limite]
