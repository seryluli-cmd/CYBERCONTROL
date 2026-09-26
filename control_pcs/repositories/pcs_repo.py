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
"""

import sqlite3
from datetime import datetime, timedelta
import dominio
from database import conexion_db
from repositories import ventas_repo


# ---------------------------------------------------------------------
# Estaciones (catálogo de PCs físicas)
# ---------------------------------------------------------------------

def listar_estaciones(solo_activas: bool = True):
    with conexion_db() as conexion:
        if solo_activas:
            return conexion.execute(
                "SELECT * FROM estaciones WHERE activa = 1 ORDER BY nombre"
            ).fetchall()
        return conexion.execute("SELECT * FROM estaciones ORDER BY nombre").fetchall()


def crear_estacion(nombre: str) -> int:
    nombre = nombre.strip()
    if not nombre:
        raise ValueError("El nombre de la estación no puede quedar vacío.")
    try:
        with conexion_db() as conexion:
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


# ---------------------------------------------------------------------
# Bonos de tiempo (catálogo de combos vendibles)
# ---------------------------------------------------------------------

def listar_bonos(solo_activos: bool = True):
    with conexion_db() as conexion:
        if solo_activos:
            return conexion.execute(
                "SELECT * FROM bonos_tiempo WHERE activo = 1 ORDER BY minutos"
            ).fetchall()
        return conexion.execute("SELECT * FROM bonos_tiempo ORDER BY minutos").fetchall()


def obtener_bono(bono_id: int):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM bonos_tiempo WHERE id = ?", (bono_id,)).fetchone()


def _validar_datos_bono(nombre: str, minutos: int, precio: float):
    if not nombre.strip():
        raise ValueError("El nombre del bono no puede quedar vacío.")
    if minutos <= 0:
        raise ValueError("Los minutos del bono tienen que ser mayores a 0.")
    if precio <= 0:
        raise ValueError("El precio del bono tiene que ser mayor a 0.")


def crear_bono(nombre: str, minutos: int, precio: float) -> int:
    _validar_datos_bono(nombre, minutos, precio)
    with conexion_db() as conexion:
        cursor = conexion.execute(
            "INSERT INTO bonos_tiempo (nombre, minutos, precio) VALUES (?, ?, ?)",
            (nombre.strip(), minutos, round(precio, 2)),
        )
        return cursor.lastrowid


def modificar_bono(bono_id: int, nombre: str, minutos: int, precio: float):
    _validar_datos_bono(nombre, minutos, precio)
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE bonos_tiempo SET nombre = ?, minutos = ?, precio = ? WHERE id = ?",
            (nombre.strip(), minutos, round(precio, 2), bono_id),
        )


def desactivar_bono(bono_id: int):
    """No se borra (un bono ya vendido queda referenciado desde
    sesion_bonos), solo deja de ofrecerse para sesiones nuevas."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE bonos_tiempo SET activo = 0 WHERE id = ?", (bono_id,))


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
            WHERE sesiones_pc.estado = 'ACTIVA'
        """).fetchall()

    sesiones_por_estacion = {sesion["estacion_id"]: sesion for sesion in sesiones}

    resultado = []
    for estacion in estaciones:
        sesion = sesiones_por_estacion.get(estacion["id"])
        segundos_restantes = None
        if sesion is not None:
            fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
            segundos_restantes = max(0, int((fin_previsto - ahora).total_seconds()))
        resultado.append({
            "estacion": estacion,
            "sesion": sesion,
            "segundos_restantes": segundos_restantes,
        })
    return resultado


def estado_de_estacion(nombre: str):
    """
    Como estado_estaciones(), pero para una sola estación por nombre --
    es lo que consulta el agente de bloqueo de cada PC cliente (ver
    servidor_red.py y la carpeta hermana "AGENTE PC KIOSKO") para
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
        "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = 'ACTIVA'",
        (estacion_id,),
    ).fetchone()

    if sesion is None:
        fin_previsto = ahora + timedelta(minutes=minutos)
        cursor = conexion.execute(
            """
            INSERT INTO sesiones_pc (estacion_id, fecha_inicio, fecha_fin_prevista, estado, miembro_id)
            VALUES (?, ?, ?, 'ACTIVA', ?)
            """,
            (estacion_id, ahora.isoformat(timespec="seconds"),
             fin_previsto.isoformat(timespec="seconds"), miembro_id),
        )
        return cursor.lastrowid

    # Si ya venció y todavía no se finalizó (el refresco automático de la
    # pantalla no pasó todavía), el tiempo nuevo se cuenta desde ahora, no
    # desde un vencimiento que ya pasó — si no, se perderían los minutos
    # entre que se agotó el tiempo anterior y que se cargó el siguiente.
    fin_previo = datetime.fromisoformat(sesion["fecha_fin_prevista"])
    base = max(fin_previo, ahora)
    fin_previsto = base + timedelta(minutes=minutos)
    conexion.execute(
        "UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
        (fin_previsto.isoformat(timespec="seconds"), sesion["id"]),
    )
    return sesion["id"]


def asignar_bono(estacion_id: int, bono_id: int, usuario_id: int, metodo_pago: str) -> int:
    """
    Vende un bono de tiempo para una estación: si no tiene sesión activa,
    arranca una nueva; si ya tiene una en curso (el cliente sigue
    jugando), le suma los minutos del bono a la que ya está abierta en
    vez de crear otra. Devuelve el id de la venta generada.
    """
    bono = obtener_bono(bono_id)
    if bono is None or not bono["activo"]:
        raise ValueError("Ese bono ya no está disponible.")

    ahora = datetime.now()

    with conexion_db() as conexion:
        sesion_id = _abrir_o_extender_sesion(conexion, estacion_id, bono["minutos"], ahora)

        venta_id = ventas_repo.registrar_venta_sin_detalle(
            conexion, usuario_id, bono["precio"], metodo_pago, dominio.ORIGEN_ALQUILER_PCS, ahora
        )
        conexion.execute(
            """
            INSERT INTO sesion_bonos (sesion_id, bono_id, minutos, precio, venta_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sesion_id, bono_id, bono["minutos"], round(bono["precio"], 2), venta_id),
        )
        return venta_id


def finalizar_sesion(sesion_id: int):
    """
    Cierra una sesión en curso: la usa tanto "Finalizar antes de tiempo"
    como el refresco automático de la pantalla cuando el tiempo restante
    llega a 0.

    Si la sesión era de un Miembro (`miembro_id` seteado, ver
    database.miembros) y todavía le quedaba tiempo, ese resto se le
    devuelve a su saldo en bloques de 30 minutos — a diferencia de un
    bono (consumible de una sola vez, sin reintegro), el saldo de un
    socio es plata suya: cortar antes no se la hace perder.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        sesion = conexion.execute(
            "SELECT * FROM sesiones_pc WHERE id = ? AND estado = 'ACTIVA'", (sesion_id,)
        ).fetchone()
        if sesion is None:
            return

        conexion.execute(
            "UPDATE sesiones_pc SET estado = 'FINALIZADA', fecha_fin_real = ? WHERE id = ?",
            (ahora.isoformat(timespec="seconds"), sesion_id),
        )

        if sesion["miembro_id"] is not None:
            fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
            segundos_restantes = max(0, int((fin_previsto - ahora).total_seconds()))
            minutos_a_reintegrar = (segundos_restantes // 60 // 30) * 30
            if minutos_a_reintegrar > 0:
                conexion.execute(
                    "UPDATE miembros SET saldo_minutos = saldo_minutos + ? WHERE id = ?",
                    (minutos_a_reintegrar, sesion["miembro_id"]),
                )
                conexion.execute(
                    """
                    INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id)
                    VALUES (?, 'REINTEGRO', ?, ?, ?)
                    """,
                    (sesion["miembro_id"], minutos_a_reintegrar,
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
    UI (ver control_pcs/ui/pcs_window.py:_texto_evento), no acá.
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

    eventos.sort(key=lambda evento: evento["fecha"], reverse=True)
    return eventos[:limite]
