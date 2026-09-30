"""
miembros_repo.py
==================
Socios del Cyber con cuenta propia y saldo prepago de tiempo (en
minutos). Se cargan de dos formas — pagando un monto en pesos que se
convierte a minutos según la tarifa que corresponda a ese monto (ver
config_repo.obtener_tramos_tarifa_hora_miembro), o comprando uno de los bonos
del catálogo EXCLUSIVO de socios (bonos_miembro_repo.listar_bonos, no el
de walk-ins de pcs_repo — ver ese módulo para la diferencia) — y se
gastan abriendo una estación con el usuario/clave del socio, sin que el
mostrador decida cuánto tiempo asignarle: un Miembro se loguea solo y
usa TODO lo que tenga disponible en ese momento (ver
abrir_estacion_por_miembro).

Diferencia clave con un bono: un bono se cobra y se consume en el
momento, sin reintegro. El saldo de un socio es una cuenta que persiste
entre visitas — si corta antes de gastarlo todo, lo que no usó se le
devuelve (ver pcs_repo.finalizar_sesion). Por eso cada movimiento de
saldo (carga, consumo, reintegro) queda en el ledger
`movimientos_saldo_miembro`: esto maneja plata real de terceros, así que
tiene que poder auditarse.
"""

import sqlite3
from datetime import datetime
import dominio
from database import conexion_db, hash_clave, verificar_clave
from repositories import config_repo, ventas_repo
from control_pcs.repositories import pcs_repo, bonos_miembro_repo

MINUTOS_POR_FRACCION = 30


def _validar_datos_miembro(usuario: str, nombre: str, dni: str, telefono: str):
    if not usuario.strip():
        raise ValueError("El usuario no puede quedar vacío.")
    if not nombre.strip():
        raise ValueError("El nombre no puede quedar vacío.")
    if not dni.strip():
        raise ValueError("El DNI no puede quedar vacío.")
    if not telefono.strip():
        raise ValueError("El teléfono no puede quedar vacío.")


def crear_miembro(usuario: str, clave: str, nombre: str, dni: str, telefono: str, email: str = None) -> int:
    _validar_datos_miembro(usuario, nombre, dni, telefono)
    if not clave:
        raise ValueError("El socio necesita una contraseña para poder loguearse solo.")
    ahora = datetime.now().isoformat(timespec="seconds")
    try:
        with conexion_db() as conexion:
            cursor = conexion.execute(
                """
                INSERT INTO miembros (usuario, clave_hash, nombre, dni, telefono, email, fecha_creacion)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (usuario.strip(), hash_clave(clave), nombre.strip(), dni.strip(),
                 telefono.strip(), (email or "").strip() or None, ahora),
            )
            return cursor.lastrowid
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe un socio con el usuario '{usuario.strip()}'.")


def modificar_miembro(miembro_id: int, usuario: str, nombre: str, dni: str, telefono: str,
                       email: str = None, clave: str = None):
    _validar_datos_miembro(usuario, nombre, dni, telefono)
    try:
        with conexion_db() as conexion:
            if clave:
                conexion.execute(
                    """
                    UPDATE miembros SET usuario = ?, clave_hash = ?, nombre = ?, dni = ?,
                                         telefono = ?, email = ?
                    WHERE id = ?
                    """,
                    (usuario.strip(), hash_clave(clave), nombre.strip(), dni.strip(),
                     telefono.strip(), (email or "").strip() or None, miembro_id),
                )
            else:
                conexion.execute(
                    """
                    UPDATE miembros SET usuario = ?, nombre = ?, dni = ?, telefono = ?, email = ?
                    WHERE id = ?
                    """,
                    (usuario.strip(), nombre.strip(), dni.strip(),
                     telefono.strip(), (email or "").strip() or None, miembro_id),
                )
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe un socio con el usuario '{usuario.strip()}'.")


def desactivar_miembro(miembro_id: int):
    """No se borra (queda el ledger de movimientos y el historial de
    sesiones), solo deja de poder loguearse."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE miembros SET activo = 0 WHERE id = ?", (miembro_id,))


def listar_miembros(incluir_inactivos: bool = False):
    with conexion_db() as conexion:
        if incluir_inactivos:
            return conexion.execute("SELECT * FROM miembros ORDER BY nombre").fetchall()
        return conexion.execute("SELECT * FROM miembros WHERE activo = 1 ORDER BY nombre").fetchall()


def obtener_miembro(miembro_id: int):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM miembros WHERE id = ?", (miembro_id,)).fetchone()


def _buscar_miembro_autenticado(conexion, usuario: str, clave: str):
    """
    Núcleo compartido de autenticar_miembro y abrir_estacion_por_miembro:
    busca al socio por usuario/clave usando una conexión YA ABIERTA. Existe
    aparte de autenticar_miembro (que abre la suya propia) para que
    abrir_estacion_por_miembro pueda autenticar DENTRO de su propia
    transacción con lock -- ver el porqué en su docstring -- en vez de en
    una lectura aparte, ya cerrada y comiteada, como hacía antes.
    """
    fila = conexion.execute(
        "SELECT * FROM miembros WHERE usuario = ? AND activo = 1", (usuario.strip(),)
    ).fetchone()
    if fila is None or not verificar_clave(clave, fila["clave_hash"]):
        return None
    return fila


def autenticar_miembro(usuario: str, clave: str):
    """
    Devuelve la fila del socio si el usuario/clave coinciden y está
    activo, o None si no. Mismo mecanismo que
    usuarios_repo._validar_credenciales_y_registrar_sesion, sin la parte
    de migrar hash legacy (acá no hay socios viejos que migrar) ni de
    registrar sesión (eso es para turnos de empleadas, no aplica a un
    socio abriendo una PC).
    """
    with conexion_db() as conexion:
        return _buscar_miembro_autenticado(conexion, usuario, clave)


def _registrar_carga(conexion, miembro_id: int, minutos: int, precio: float, pagos: list,
                      usuario_operador_id: int, bono_id: int = None) -> int:
    """Núcleo común de cargar_saldo_por_monto/cargar_saldo_por_bono: la
    venta se registra vía ventas_repo.registrar_venta_sin_detalle (mismo
    mecanismo que pcs_repo.asignar_bono, por la misma razón: no hay un
    artículo real de por medio), se suma el saldo, y queda el movimiento
    CARGA en el ledger. A diferencia de abrir_estacion_por_miembro
    (autoservicio puro), cargar saldo siempre lo hace el Operador porque
    implica cobrar plata — por eso necesita `usuario_operador_id`, igual
    que cualquier otra venta del sistema.

    `pagos`: lista de {"metodo", "monto"} — ver
    ventas_repo.registrar_venta_sin_detalle."""
    ahora = datetime.now()
    ahora_iso = ahora.isoformat(timespec="seconds")

    venta_id = ventas_repo.registrar_venta_sin_detalle(
        conexion, usuario_operador_id, precio, pagos, dominio.ORIGEN_ALQUILER_PCS, ahora
    )
    conexion.execute(
        "UPDATE miembros SET saldo_minutos = saldo_minutos + ? WHERE id = ?",
        (minutos, miembro_id),
    )
    conexion.execute(
        """
        INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id, bono_id)
        VALUES (?, 'CARGA', ?, ?, ?, ?)
        """,
        (miembro_id, minutos, ahora_iso, venta_id, bono_id),
    )
    return venta_id


def cargar_saldo_por_monto(miembro_id: int, monto: float, pagos: list, usuario_operador_id: int) -> int:
    """
    Convierte un pago en pesos a minutos de saldo, según la tarifa $/hora
    que corresponda a ESE monto (ver
    config_repo.obtener_tramos_tarifa_hora_miembro y
    dominio.tarifa_hora_para_monto -- tabla de tramos por monto mínimo,
    no una tarifa única). Se redondea siempre hacia ABAJO al bloque de 30
    minutos más cercano — nunca se regala tiempo de más por un
    redondeo, y el saldo solo se gasta en esos mismos bloques de 30 (ver
    abrir_estacion_por_miembro).
    """
    if monto <= 0:
        raise ValueError("El monto tiene que ser mayor a 0.")
    tramos = config_repo.obtener_tramos_tarifa_hora_miembro()
    tarifa_hora = dominio.tarifa_hora_para_monto(tramos, monto)
    minutos = int((monto / tarifa_hora * 60) // MINUTOS_POR_FRACCION) * MINUTOS_POR_FRACCION
    if minutos <= 0:
        raise ValueError(
            f"Ese monto no alcanza para {MINUTOS_POR_FRACCION} minutos a la tarifa actual "
            f"(${tarifa_hora:.0f}/hora)."
        )
    with conexion_db() as conexion:
        return _registrar_carga(conexion, miembro_id, minutos, monto, pagos, usuario_operador_id)


def cargar_saldo_por_bono(miembro_id: int, bono_id: int, pagos: list, usuario_operador_id: int) -> int:
    """Agrega al saldo del socio un bono del catálogo EXCLUSIVO de socios
    (bonos_miembro_repo, no pcs_repo.listar_bonos -- ese es para
    walk-ins) — ya viene en minutos múltiplos de 30 por construcción del
    catálogo."""
    bono = bonos_miembro_repo.obtener_bono(bono_id)
    if bono is None or not bono["activo"]:
        raise ValueError("Ese bono ya no está disponible.")
    with conexion_db() as conexion:
        return _registrar_carga(conexion, miembro_id, bono["minutos"], bono["precio"], pagos,
                                 usuario_operador_id, bono_id=bono_id)


def anular_carga(venta_id: int, usuario_admin_id: int, motivo: str):
    """
    Anula, desde Consulta de Ventas, una venta que había cargado saldo a
    un socio (ver _registrar_carga) -- y revierte esa carga del saldo
    actual, todo en la MISMA transacción que la anulación en sí (ver
    ventas_repo._anular_venta). Antes, "Anular" en Consulta de Ventas
    (que no distingue de dónde vino cada venta) usaba
    ventas_repo.anular_venta para TODAS: eso le sacaba la plata del
    cierre/caja a una carga anulada, pero le dejaba los minutos intactos
    al socio, como si el negocio le hubiera regalado ese tiempo (bug
    reportado 2026-09-29).

    La reversión queda topeada a lo que el socio TENGA en este momento:
    si ya gastó parte o todo el saldo cargado (abriendo una PC, ver
    abrir_estacion_por_miembro) antes de que alguien anule la carga, no
    se le puede sacar más de lo que le queda -- ahí ya es plata/tiempo
    que se usó de verdad, revertir no puede dejarlo en saldo negativo. El
    movimiento que se deja en el ledger es 'ANULACION', nunca un CONSUMO
    ni un REINTEGRO disimulados: son conceptos distintos y mezclarlos
    rompería la trazabilidad que este ledger existe para dar.

    Sirve para CUALQUIER venta, no solo una carga: si la venta no tiene
    ninguna CARGA asociada (un bono de PC walk-in, por ejemplo), se
    comporta exactamente igual que ventas_repo.anular_venta.
    """
    with conexion_db() as conexion:
        ventas_repo._anular_venta(conexion, venta_id, usuario_admin_id, motivo)

        ahora_iso = datetime.now().isoformat(timespec="seconds")
        cargas = conexion.execute(
            "SELECT * FROM movimientos_saldo_miembro WHERE venta_id = ? AND tipo = 'CARGA'",
            (venta_id,),
        ).fetchall()
        for carga in cargas:
            saldo_actual = conexion.execute(
                "SELECT saldo_minutos FROM miembros WHERE id = ?", (carga["miembro_id"],)
            ).fetchone()["saldo_minutos"]
            a_revertir = min(carga["minutos"], saldo_actual)
            if a_revertir <= 0:
                continue
            conexion.execute(
                "UPDATE miembros SET saldo_minutos = saldo_minutos - ? WHERE id = ?",
                (a_revertir, carga["miembro_id"]),
            )
            conexion.execute(
                """
                INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id)
                VALUES (?, 'ANULACION', ?, ?, ?)
                """,
                (carga["miembro_id"], a_revertir, ahora_iso, venta_id),
            )


def abrir_estacion_por_miembro(estacion_id: int, usuario: str, clave: str) -> dict:
    """
    El socio se loguea solo (usuario/clave) para abrir una estación con
    TODO su saldo disponible — no es el mostrador quien elige cuánto
    tiempo asignarle, es autoservicio puro. Levanta ValueError si las
    credenciales no coinciden o si no le queda al menos un bloque de 30
    minutos. Devuelve un resumen simple para mostrar en pantalla.

    Autentica y consume el saldo DENTRO de una sola transacción con
    "BEGIN IMMEDIATE" (toma el lock de escritura de entrada, antes de
    leer nada) -- antes, autenticar_miembro corría en su propia
    transacción, ya cerrada y comiteada, antes de llegar acá. Con el
    servidor de red atendiendo cada pedido en su propio hilo (ver
    servidor_red.ThreadingHTTPServer), dos POST /login simultáneos del
    MISMO socio (doble clic, reintento de red) podían autenticarse los
    dos leyendo el mismo saldo_minutos, y terminar gastándolo los dos:
    un socio con 60 minutos disponibles podía terminar con 120 asignados
    entre dos sesiones. Con el lock tomado de entrada, el segundo pedido
    espera a que el primero termine de commitear y recién ahí lee el
    saldo ya en 0 -- coherente con MINUTOS_POR_FRACCION, no le alcanza y
    se le rechaza en vez de duplicarle el tiempo.
    """
    ahora = datetime.now()
    ahora_iso = ahora.isoformat(timespec="seconds")

    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")

        miembro = _buscar_miembro_autenticado(conexion, usuario, clave)
        if miembro is None:
            raise ValueError("Usuario o contraseña incorrectos.")
        if miembro["saldo_minutos"] < MINUTOS_POR_FRACCION:
            raise ValueError(
                f"{miembro['nombre']} no tiene saldo suficiente (le quedan "
                f"{miembro['saldo_minutos']} minutos, hace falta al menos {MINUTOS_POR_FRACCION})."
            )

        minutos_a_usar = miembro["saldo_minutos"]

        sesion_id = pcs_repo._abrir_o_extender_sesion(
            conexion, estacion_id, minutos_a_usar, ahora, miembro_id=miembro["id"]
        )
        conexion.execute(
            "UPDATE miembros SET saldo_minutos = 0 WHERE id = ?", (miembro["id"],)
        )
        conexion.execute(
            """
            INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id)
            VALUES (?, 'CONSUMO', ?, ?, ?)
            """,
            (miembro["id"], minutos_a_usar, ahora_iso, sesion_id),
        )

    return {"miembro": miembro["nombre"], "minutos_usados": minutos_a_usar}
