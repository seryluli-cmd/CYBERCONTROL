"""
ultima_visita_repo.py
=====================
Hace cuánto no viene cada socio (columna "No viene hace" de Miembros, pedido
del dueño 2026-10-24: para saber a quién escribirle por WhatsApp). Solo lee.

No hay un registro aparte de visitas: sale de lo que el programa ya guarda,
así funciona con fecha desde el primer día y no hay nada que mantener.
"Vino" es lo último de estas dos cosas:

1. Su última sesión de PC con su usuario (sesiones_pc.miembro_id): la hora
   en que terminó, o AHORA si todavía la está usando.
2. Su última carga de saldo (movimientos_saldo_miembro CARGA), sin contar
   las anuladas.

Un socio que viene y paga un bono en el mostrador sin entrar con su usuario
no queda como visita: esa sesión no sabe de qué socio es.

Los días son los del local, de 06:00 a 06:00 (turnos.dia_en_que_empezo_el_turno):
el que se fue anoche a las 02:00 vino "hoy" si todavía no son las 06:00.
"""

from datetime import datetime

import dominio
from database import conexion_db
from turnos import dia_en_que_empezo_el_turno


def ultimas_visitas(ahora: datetime = None) -> dict:
    """
    {miembro_id: visita} de los socios que vinieron alguna vez (el que no
    está, nunca vino). Cada visita es un diccionario con:
    - "ultima": el último momento en que estuvo (datetime);
    - "pc": la PC de su última sesión, "pc_desde" (cuándo entró) y
      "jugando" (si la sigue usando), o None si nunca entró a una PC;
    - "carga": su última carga vigente (datetime), o None.
    """
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        # El MAX junto con columnas sueltas: SQLite trae las de la fila del MAX
        # (la última sesión de cada socio), apoyado en idx_sesiones_pc_miembro.
        sesiones = conexion.execute(
            """
            SELECT s.miembro_id, MAX(s.fecha_inicio) AS desde, s.fecha_fin_real, s.estado, e.nombre AS pc
            FROM sesiones_pc s
            JOIN estaciones e ON e.id = s.estacion_id
            WHERE s.miembro_id IS NOT NULL
            GROUP BY s.miembro_id
            """
        ).fetchall()
        cargas = conexion.execute(
            """
            SELECT m.miembro_id, MAX(m.fecha) AS fecha
            FROM movimientos_saldo_miembro m
            LEFT JOIN ventas v ON v.id = m.venta_id
            WHERE m.tipo = ? AND (v.estado IS NULL OR v.estado != ?)
            GROUP BY m.miembro_id
            """,
            (dominio.MOVIMIENTO_CARGA, dominio.VENTA_ANULADA),
        ).fetchall()

    visitas = {}
    for sesion in sesiones:
        jugando = sesion["estado"] == dominio.SESION_ACTIVA
        desde = datetime.fromisoformat(sesion["desde"])
        if jugando:
            hasta = ahora
        elif sesion["fecha_fin_real"]:
            hasta = datetime.fromisoformat(sesion["fecha_fin_real"])
        else:
            hasta = desde
        visitas[sesion["miembro_id"]] = {
            "ultima": hasta, "pc": sesion["pc"], "pc_desde": desde, "jugando": jugando, "carga": None,
        }
    for carga in cargas:
        fecha = datetime.fromisoformat(carga["fecha"])
        visita = visitas.setdefault(carga["miembro_id"], {
            "ultima": fecha, "pc": None, "pc_desde": None, "jugando": False, "carga": None,
        })
        visita["carga"] = fecha
        visita["ultima"] = max(visita["ultima"], fecha)
    return visitas


def dias_sin_venir(visita, ahora: datetime = None):
    """Cuántos días del local pasaron desde que vino (0 = hoy), o None si
    nunca vino (`visita` None, ver ultimas_visitas)."""
    if visita is None:
        return None
    ahora = ahora or datetime.now()
    return max(0, (dia_en_que_empezo_el_turno(ahora) - dia_en_que_empezo_el_turno(visita["ultima"])).days)


def no_viene_hace_mas_de(dias, limite: int) -> bool:
    """Si un socio con `dias` sin venir (de dias_sin_venir) entra en "No vienen
    hace más de `limite` días". El que nunca vino también: es a quien más
    sirve escribirle."""
    return dias is None or dias > limite
