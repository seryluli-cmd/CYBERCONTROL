"""Turnos vencidos sin cierre y responsables probables del mes."""

from datetime import date, datetime, timedelta

import dominio
from database import conexion_db
from turnos import calcular_turno, turno_vencimiento, turnos_del_dia


def turnos_del_mes_actual(hoy):
    """
    Los turnos esperados del mes en curso, de día 1 a hoy — domingo
    tiene solo 2 (Mañana, Noche); el resto de los días tiene los 3 de
    siempre (ver turnos.calcular_turno). Todavía no dice cuáles ya
    tienen cierre cargado ni cuáles vencieron — eso lo hace
    turnos_faltantes().
    """
    dia = date(hoy.year, hoy.month, 1)
    slots = []
    while dia <= hoy:
        for turno in turnos_del_dia(dia):
            slots.append({"fecha": dia, "turno": turno})
        dia += timedelta(days=1)
    return slots


def _responsables_del_mes(conexion, inicio_mes):
    """
    Mapa (día, turno) -> nombres de quienes vendieron algo o iniciaron
    sesión durante esa ventana, para el mes en curso. Es la mejor pista
    disponible de quién podría ser responsable de un turno que quedó
    sin cerrar: el sistema no tiene un horario asignado por empleada,
    así que ni las ventas ni los logins son una certeza, pero entre las
    dos señales alcanza para saber a quién preguntarle incluso en un
    turno sin ninguna venta (por ejemplo, alguien que se logueó pero
    todavía no facturó nada, o que atendió sin cobrar nada por sistema).

    NOCHE cruza la medianoche: un evento de esas horas puede tener
    fecha del día en que arrancó el turno (22-23:59, o 18-23:59 el
    domingo) o del día siguiente (00-05:59) — se le atribuye al día en
    que arrancó, mismo criterio que turno_vencimiento().
    """
    responsables = {}

    def agregar(momento, turno, nombre):
        dia_slot = momento.date()
        if turno == dominio.TURNO_NOCHE and momento.hour < 12:
            dia_slot -= timedelta(days=1)
        responsables.setdefault((dia_slot, turno), set()).add(nombre)

    filas_ventas = conexion.execute(
        """
        SELECT ventas.fecha, ventas.turno, usuarios.nombre
        FROM ventas
        JOIN usuarios ON usuarios.id = ventas.usuario_id
        WHERE ventas.estado = ? AND ventas.fecha >= ?
        """,
        (dominio.VENTA_CONFIRMADA, inicio_mes.isoformat()),
    ).fetchall()
    for fila in filas_ventas:
        agregar(datetime.fromisoformat(fila["fecha"]), fila["turno"], fila["nombre"])

    # Las sesiones no tienen "turno" guardado (a diferencia de las
    # ventas): se calcula al vuelo con la misma calcular_turno() que usa
    # todo el resto del sistema, para que quede consistente incluso con
    # la excepción de los domingos.
    filas_sesiones = conexion.execute(
        """
        SELECT sesiones.fecha_hora, usuarios.nombre
        FROM sesiones
        JOIN usuarios ON usuarios.id = sesiones.usuario_id
        WHERE sesiones.fecha_hora >= ?
        """,
        (inicio_mes.isoformat(),),
    ).fetchall()
    for fila in filas_sesiones:
        momento = datetime.fromisoformat(fila["fecha_hora"])
        agregar(momento, calcular_turno(momento), fila["nombre"])

    return responsables


def turnos_faltantes(ahora):
    """
    De los turnos esperados del mes en curso (turnos_del_mes_actual), los
    que YA vencieron (ventana nominal + turnos.TURNO_GRACIA_MIN de gracia, ver
    turnos.turno_vencimiento) y todavía no tienen un cierre cargado en
    cierres_turno. Se usa en "Control de Cierres de Turno" para que el
    Admin se entere de un turno sin cerrar antes de que se pierda en el
    historial, en vez de notarlo recién a fin de mes. Cada resultado
    incluye "usuarios": quién vendió o se logueó durante esa ventana
    (ver _responsables_del_mes), para saber a quién preguntarle.
    """
    hoy = ahora.date()
    inicio_mes = date(hoy.year, hoy.month, 1)

    with conexion_db() as conexion:
        filas_cierres = conexion.execute(
            "SELECT fecha, turno FROM cierres_turno WHERE fecha >= ?",
            (inicio_mes.isoformat(),),
        ).fetchall()
        responsables = _responsables_del_mes(conexion, inicio_mes)
    cerrados = {(fila["fecha"], fila["turno"]) for fila in filas_cierres}

    faltantes = []
    for slot in turnos_del_mes_actual(hoy):
        if (slot["fecha"].isoformat(), slot["turno"]) in cerrados:
            continue
        if turno_vencimiento(slot["fecha"], slot["turno"]) <= ahora:
            slot = dict(slot)
            slot["usuarios"] = sorted(responsables.get((slot["fecha"], slot["turno"]), ()))
            faltantes.append(slot)
    return faltantes
