"""
tiempo_del_socio_repo.py
==========================
Cuánto tiempo tiene un socio, contando el que se llevó a la PC donde está jugando
(pedido del dueño, 2026-11-07: "los tiempos de los miembros no concuerdan, a veces, entre
lo que dice el servidor y lo que dice el cliente").

Al entrar a una PC, el socio se lleva su saldo a esa PC
(miembros_repo.abrir_estacion_por_miembro). Mientras juega, `miembros.saldo_minutos` es
solo lo GUARDADO aparte, y lo que corre en la PC está en su sesión. Normalmente lo guardado
queda en cero. Queda algo cuando la PC está reservada más tarde por otro: entra solo hasta la
hora de la reserva (reservas_horario_repo.minutos_para_el_socio). El caso que lo hizo ver:
Eros en la PC15X el 06/11. La PC decía 6h 33m y la ficha de Miembros 32h 18m, y las dos
cosas eran ciertas: entre las dos tenía 38h 51m, y nada decía que la PC se cortaba a las
22:00 por una reserva.

Solo lee. Lo usa la pantalla de Miembros (la lista y la ficha del socio). El tiempo de cada
PC sale de la misma cuenta que el mosaico (dominio.segundos_restantes) y el corte por
reserva, de reservas_horario_repo.reserva_que_corta.
"""

from datetime import datetime

import dominio
from database import conexion_db
from control_pcs.repositories import reservas_horario_repo


def socios_jugando(ahora: datetime = None) -> dict:
    """
    {miembro_id: {"pcs": [...], "segundos_en_pcs": int}} de los socios que están jugando
    ahora con su usuario y con tiempo por delante. La sesión es del socio que muestra el
    mosaico (sesiones_pc.miembro_id), igual que "Está usando la PC..." de
    ultima_visita_repo.

    Cada PC es {"estacion": nombre, "segundos": lo que le queda, "hasta_la_reserva": la
    reserva que la corta (con "inicio" y "cliente") o None}, de la que termina antes a la que
    termina después. Casi siempre es una sola; dos, si entró a otra PC con lo que le quedó
    guardado. "segundos_en_pcs" es la suma.
    """
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        sesiones = conexion.execute(
            """
            SELECT s.*, e.nombre AS estacion_nombre
            FROM sesiones_pc s JOIN estaciones e ON e.id = s.estacion_id
            WHERE s.estado = ? AND s.miembro_id IS NOT NULL
            """,
            (dominio.SESION_ACTIVA,),
        ).fetchall()
        reservas = reservas_horario_repo.pendientes(conexion, ahora) if sesiones else []

    jugando = {}
    for sesion in sesiones:
        segundos = dominio.segundos_restantes(datetime.fromisoformat(sesion["fecha_fin_prevista"]), ahora)
        if segundos <= 0:
            # Llegó a cero y el mostrador todavía no la dio de baja: ya no juega con ese tiempo.
            continue
        estacion = {"id": sesion["estacion_id"], "nombre": sesion["estacion_nombre"]}
        socio = jugando.setdefault(sesion["miembro_id"], {"pcs": [], "segundos_en_pcs": 0})
        socio["pcs"].append({
            "estacion": sesion["estacion_nombre"],
            "segundos": segundos,
            "hasta_la_reserva": reservas_horario_repo.reserva_que_corta(reservas, estacion, sesion),
        })
        socio["segundos_en_pcs"] += segundos
    for socio in jugando.values():
        socio["pcs"].sort(key=lambda pc: pc["segundos"])
    return jugando


def segundos_totales(miembro, jugando=None) -> int:
    """
    Todo el tiempo que tiene un socio: lo guardado (`miembro["saldo_minutos"]`) más lo que le
    queda en las PCs donde está jugando (`jugando`: lo de socios_jugando para él, o None si no
    juega). Es lo que muestran la lista y la ficha de Miembros.
    """
    return miembro["saldo_minutos"] * 60 + (jugando["segundos_en_pcs"] if jugando else 0)
