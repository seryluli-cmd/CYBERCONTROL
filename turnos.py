"""
turnos.py
==========
Todo lo que define los turnos del kiosko: a cuál pertenece una hora, qué
turnos existen en un día, cómo se llaman en pantalla y cuándo se
considera que uno ya debería estar cerrado.

Son funciones puras — no tocan la base de datos ni Qt — y por eso viven
acá y no en database.py: el archivo de la base había crecido mezclando
dos temas que no tienen nada que ver entre sí (el esquema SQL por un
lado, el calendario del local por el otro). Separados, se puede cambiar
un horario sin abrir el archivo donde vive el esquema (ver CLAUDE.md,
regla 12).

Los nombres de los turnos ("MAÑANA", "TARDE", "NOCHE") están en
dominio.py; acá está la lógica que los usa.
"""

from datetime import date, datetime, timedelta

import dominio


def calcular_turno(fecha_hora: datetime) -> str:
    """
    Devuelve a qué turno pertenece una fecha/hora determinada, según los
    horarios fijos del local (abierto las 24 hs):
        MAÑANA:  06:00 a 13:59
        TARDE:   14:00 a 21:59
        NOCHE:   22:00 a 05:59 (cruza la medianoche)
    Esto es independiente de qué usuario esté logueado, así que aunque
    una empleada llegue tarde, cada venta se clasifica sola por su hora
    real.

    EXCEPCIÓN: los domingos son distintos — solo hay 2 turnos de 12hs en
    vez de 3. "MAÑANA" pasa a durar 06:00-17:59 (absorbe lo que sería
    "TARDE", que no existe ese día) y "NOCHE" pasa a ser 18:00-05:59 del
    lunes. El sábado a la noche sigue siendo el turno normal 22-06
    (termina el domingo a la mañana), eso no cambia — por eso se mira el
    día de `fecha_hora` tal cual, sin correcciones.
    """
    domingo = fecha_hora.weekday() == 6  # Monday=0 ... Sunday=6
    hora = fecha_hora.hour
    fin_manana = 18 if domingo else 14
    if 6 <= hora < fin_manana:
        return dominio.TURNO_MANANA
    elif not domingo and 14 <= hora < 22:
        return dominio.TURNO_TARDE
    else:
        return dominio.TURNO_NOCHE


def es_domingo(fecha) -> bool:
    """Acepta un date, un datetime, o un string 'YYYY-MM-DD' (o con hora
    al final, se ignora)."""
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    elif isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])
    return fecha.weekday() == 6


def turnos_del_dia(fecha) -> tuple:
    """
    Qué turnos existen en un día calendario dado: los tres de siempre, o
    los dos de 12hs si es domingo (ver calcular_turno). `fecha` acepta lo
    mismo que es_domingo().

    Único lugar donde se decide esto. Cualquier pantalla o reporte que
    recorra "los turnos de un día" tiene que preguntar acá, si no el día
    que cambien los horarios habría que acordarse de todos los lugares
    donde está escrita la lista a mano.
    """
    return dominio.TURNOS_DOMINGO if es_domingo(fecha) else dominio.TURNOS


def dia_en_que_empezo_el_turno(fecha_hora: datetime) -> date:
    """
    El día calendario en que EMPEZÓ el turno al que pertenece un momento (ver
    calcular_turno). Es el mismo día, salvo de madrugada (antes de las 06:00):
    eso es el turno Noche que arrancó el día anterior. Sin esto, una venta del
    lunes a la 01:00 (Noche del domingo, "Domingo T2") se mostraría como
    "Noche", y una del domingo a las 03:00 (Noche del sábado) como "Domingo T2".
    Se usa para pasarle el día correcto a etiqueta_turno.
    """
    if fecha_hora.hour < 6:
        return (fecha_hora - timedelta(days=1)).date()
    return fecha_hora.date()


def etiqueta_turno(fecha, turno: str) -> str:
    """
    Nombre legible de un turno según el día calendario al que
    pertenece: los domingos "MAÑANA"/"NOCHE" se muestran como "Domingo
    T1"/"Domingo T2" en vez de "Mañana"/"Noche", porque ese día no
    existe el turno Tarde — son 2 turnos de 12hs en vez de 3 (ver
    calcular_turno). `fecha` acepta lo mismo que es_domingo().
    """
    if es_domingo(fecha):
        if turno == dominio.TURNO_MANANA:
            return "Domingo T1"
        if turno == dominio.TURNO_NOCHE:
            return "Domingo T2"
    return turno.capitalize()


# Cuántos minutos de gracia se le dan a un turno vencido antes de
# considerarlo realmente "sin cerrar": quien cierra un turno tarda un
# rato en cargarlo, así que no tiene sentido avisar apenas termina su
# horario nominal — ver turno_vencimiento.
TURNO_GRACIA_MIN = 40


def turno_que_arranca_tras_un_cierre(momento_del_cierre: datetime) -> str:
    """
    A qué turno pertenece lo que se venda DESPUÉS de un cierre hecho en
    `momento_del_cierre`: es el turno con el que va a quedar anotado el cierre
    siguiente (ver turnos_repo._desde_y_turno_en_curso).

    Un cierre hecho hasta TURNO_GRACIA_MIN minutos ANTES del cambio de turno
    (quien cierra y se va a las 13:55, con la Tarde ya llegando) cuenta como el
    cierre del turno que termina, no como el arranque del que sigue. Sin esa
    tolerancia, lo que se cerraba después quedaba anotado un turno corrido (la
    Tarde como "Mañana", la Noche como "Tarde") y el reporte mostraba como "sin
    cerrar" un turno que sí se había cerrado. Es la misma gracia que
    turno_vencimiento da a los cierres tardíos, pero en el otro sentido.
    """
    return calcular_turno(momento_del_cierre + timedelta(minutes=TURNO_GRACIA_MIN))


def turno_vencimiento(dia_base, turno: str) -> datetime:
    """
    Momento exacto en que el turno `turno` de un día calendario dado
    (`dia_base`, acepta lo mismo que es_domingo()) queda vencido: fin de
    su ventana nominal + TURNO_GRACIA_MIN de gracia. Se usa para saber
    si un turno del mes en curso que todavía no tiene cierre cargado ya
    "debería" estarlo, o si puede seguir en curso.

    NOCHE cruza la medianoche, por eso vence a la madrugada del día
    SIGUIENTE al que arrancó — esto no cambia los domingos: tanto la
    noche normal como "Domingo T2" terminan igual a las 06:00 del día
    siguiente, lo único que cambia es a qué hora arrancan.
    """
    if isinstance(dia_base, datetime):
        dia_base = dia_base.date()
    elif isinstance(dia_base, str):
        dia_base = date.fromisoformat(dia_base[:10])
    domingo = dia_base.weekday() == 6
    inicio_dia = datetime(dia_base.year, dia_base.month, dia_base.day)

    if turno == dominio.TURNO_MANANA:
        hora_fin = 18 if domingo else 14
        return inicio_dia.replace(hour=hora_fin, minute=TURNO_GRACIA_MIN)
    if turno == dominio.TURNO_TARDE:
        return inicio_dia.replace(hour=22, minute=TURNO_GRACIA_MIN)
    # NOCHE: vence a la madrugada del día siguiente.
    return (inicio_dia + timedelta(days=1)).replace(hour=6, minute=TURNO_GRACIA_MIN)
