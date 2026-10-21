"""
avisos_fin_pc_repo.py
=====================
¿La PC se enteró de que se terminó su sesión? (pedido del dueño, 2026-10-21: en la PC 30
se le terminó el tiempo a un cliente y siguió jugando, con el Cliente PC cerrado).

Una PC se bloquea, y se reinicia, porque su Cliente PC pregunta cada 5 s y el mostrador le
contesta que ya no tiene sesión. Si el Cliente PC no está andando (lo cerraron, se colgó, la
PC quedó sin red), no hay a quién contestarle: el mostrador cerraba la sesión igual y el
monitor pasaba al rojo fijo de "Sin conexión", el mismo de una PC apagada. Nadie se enteraba.
Mandarle a la PC una orden de reiniciar no lo arregla: viaja por la misma consulta que no llega.

Ahora cada sesión que se cierra (por tiempo, Finalizar, Cerrar sesión del socio) queda
AVISO_FIN_PENDIENTE (`pcs_repo._cerrar_sesion`) hasta que la PC vuelve a preguntar
(`marcar_enterada`, desde `pcs_repo.registrar_conexion`): esa consulta ya recibe "sin sesión"
y la PC se bloquea. Si pasa el plazo sin noticias (`fin_sin_aviso`), la PC titila en rojo,
como la PlayStation 5 con el tiempo agotado (`pcs_window._ficha_de_pc`), hasta que la PC
vuelve o el operador aprieta "Ya revisé la PC" (`marcar_revisada`: queda quién y cuándo, y se
ve en "Actividad reciente"). Cuando la PC vuelve, el corte se anota con su causa como
cualquier otro (cortes_pc_repo): ahí se sabe si el Cliente PC se había cerrado, si la PC se
reinició o si fue la red.

Las sesiones cerradas antes de esto no tienen aviso (NULL): no titila ninguna PC vieja.
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import usuarios_repo


def pendientes(conexion, estacion_id: int = None) -> dict:
    """{estacion_id: la última sesión de esa PC que todavía no se sabe si se enteró de su fin}.
    Con `estacion_id`, solo esa PC (la consulta de un Cliente PC). Lee solo las PENDIENTE, con
    su índice: son pocas, la PC las marca en su próxima consulta."""
    sql = """
        SELECT sesiones_pc.id AS sesion_id, sesiones_pc.estacion_id, sesiones_pc.fecha_fin_real,
               sesiones_pc.fecha_fin_prevista, miembros.nombre AS miembro_nombre
        FROM sesiones_pc
        LEFT JOIN miembros ON miembros.id = sesiones_pc.miembro_id
        WHERE sesiones_pc.aviso_fin = ?
    """
    parametros = [dominio.AVISO_FIN_PENDIENTE]
    if estacion_id is not None:
        sql += " AND sesiones_pc.estacion_id = ?"
        parametros.append(estacion_id)
    por_estacion = {}
    for fila in conexion.execute(sql + " ORDER BY sesiones_pc.fecha_fin_real, sesiones_pc.id", parametros):
        por_estacion[fila["estacion_id"]] = fila  # queda la última
    return por_estacion


def fin_sin_aviso(pendiente, estacion, ahora: datetime, segundos_para_enterarse: int):
    """
    Si la PC `estacion` no se enteró de que terminó la sesión `pendiente` (una fila de
    `pendientes`, o None): {"sesion_id", "fin", "por_tiempo", "quien"}. None si ya se enteró o
    si todavía está a tiempo: una PC andando pregunta cada 5 s, así que se le da el mismo plazo
    que a una PC en uso antes de la alerta "SIN CLIENTE" (`segundos_para_enterarse`,
    pcs_repo.UMBRAL_ENLACE_SEGUNDOS).

    "Se enteró" es que preguntó DESPUÉS del fin, aunque todavía no se haya marcado. Una
    consulta en el mismo segundo del fin no cuenta: puede haber salido antes del cierre.
    """
    if pendiente is None or pendiente["fecha_fin_real"] is None:
        return None
    fin = datetime.fromisoformat(pendiente["fecha_fin_real"])
    if (ahora - fin).total_seconds() <= segundos_para_enterarse:
        return None
    if estacion["ultima_conexion"] is not None and datetime.fromisoformat(estacion["ultima_conexion"]) > fin:
        return None
    previsto = datetime.fromisoformat(pendiente["fecha_fin_prevista"])
    return {
        "sesion_id": pendiente["sesion_id"],
        "fin": fin,
        # Se terminó el tiempo (la hora de fin real nunca pasa de la prevista, ver
        # pcs_repo._cerrar_sesion) o la cortaron antes: Finalizar, Cerrar sesión del socio.
        "por_tiempo": (previsto - fin).total_seconds() < 1,
        "quien": pendiente["miembro_nombre"] or "Bono",
    }


def marcar_enterada(conexion, estacion_id: int, ahora_texto: str):
    """La PC acaba de preguntar (pcs_repo.registrar_conexion, misma transacción): las sesiones
    suyas que terminaron ANTES de este segundo ya no son una duda."""
    conexion.execute(
        """
        UPDATE sesiones_pc SET aviso_fin = ?
        WHERE aviso_fin = ? AND estacion_id = ? AND fecha_fin_real < ?
        """,
        (dominio.AVISO_FIN_ENTERADA, dominio.AVISO_FIN_PENDIENTE, estacion_id, ahora_texto),
    )


def marcar_revisada(sesion_id: int, usuario_id: int):
    """"Ya revisé la PC": el operador fue a ver la PC que no se enteró del fin de su sesión y
    apaga la alerta. Queda quién y cuándo. Si mientras tanto la PC volvió, no cambia nada."""
    usuarios_repo.usuario_habilitado(usuario_id)
    with conexion_db() as conexion:
        conexion.execute(
            """
            UPDATE sesiones_pc SET aviso_fin = ?, aviso_fin_revisado_por = ?, aviso_fin_revisado_fecha = ?
            WHERE id = ? AND aviso_fin = ?
            """,
            (dominio.AVISO_FIN_REVISADO, usuario_id, datetime.now().isoformat(timespec="seconds"),
             sesion_id, dominio.AVISO_FIN_PENDIENTE),
        )


def listar_revisadas_recientes(limite: int):
    """Las últimas `limite` alertas que un operador dio por revisadas, para "Actividad
    reciente" (actividad_repo): la PC, a qué hora terminó su sesión, quién y cuándo."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT s.aviso_fin_revisado_fecha AS fecha_hora, s.fecha_fin_real,
                   e.nombre AS estacion_nombre, u.nombre AS usuario_nombre
            FROM sesiones_pc s
            JOIN estaciones e ON e.id = s.estacion_id
            LEFT JOIN usuarios u ON u.id = s.aviso_fin_revisado_por
            WHERE s.aviso_fin_revisado_fecha IS NOT NULL
            ORDER BY s.aviso_fin_revisado_fecha DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
