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

from datetime import date, datetime, time, timedelta

import dominio

# A qué hora empieza el día del local (pedido del dueño, 2026-10-17): el día 1
# es Mañana (06-14), Tarde (14-22) y Noche (22 a 06 del día 2). La Noche se
# factura desde el día 1 a las 22, así que cuenta ENTERA en el día 1: un día va
# de las 06:00 a las 06:00 del día siguiente, no de medianoche a medianoche. Los
# domingos también, aunque tengan 2 turnos de 12 hs (ver calcular_turno).
HORA_CAMBIO_DE_DIA = 6


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
    if HORA_CAMBIO_DE_DIA <= hora < fin_manana:
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

    Es también "a qué día del local pertenece este momento" (ver
    HORA_CAMBIO_DE_DIA): el día del turno y el día del local son lo mismo.
    """
    if fecha_hora.hour < HORA_CAMBIO_DE_DIA:
        return (fecha_hora - timedelta(days=1)).date()
    return fecha_hora.date()


def _como_date(fecha) -> date:
    """Un date a partir de un date, un datetime o un string "YYYY-MM-DD..."."""
    if isinstance(fecha, datetime):
        return fecha.date()
    if isinstance(fecha, str):
        return date.fromisoformat(fecha[:10])
    return fecha


def limites_de_los_dias(desde, hasta) -> tuple:
    """
    Las dos puntas, como texto ISO, de los días `desde` a `hasta` (incluidos los
    dos; date, datetime o "YYYY-MM-DD") contados como los cuenta el local: del
    `desde` a las 06:00 hasta el día SIGUIENTE a `hasta` a las 06:00 (ver
    HORA_CAMBIO_DE_DIA). Así la Noche del último día entra entera, y la madrugada
    del primero (que es la Noche del día anterior) queda afuera.

    Se usan como `fecha >= inicio AND fecha < fin`: comparan bien como texto
    contra las fechas que graba el programa (ISO, con "T"), y una venta de las
    06:00:00 en punto ya es del día siguiente.
    """
    inicio = datetime.combine(_como_date(desde), time(HORA_CAMBIO_DE_DIA))
    fin = datetime.combine(_como_date(hasta) + timedelta(days=1), time(HORA_CAMBIO_DE_DIA))
    return inicio.isoformat(), fin.isoformat()


def sql_dia_del_local(columna: str) -> str:
    """
    La misma regla que dia_en_que_empezo_el_turno, escrita en SQL, para agrupar
    por día en una consulta: el día del local al que pertenece la fecha ISO de
    `columna` (un nombre de columna fijo del programa, nunca un dato de la
    usuaria). Una venta del día 2 a la 01:00 da el día 1.

    Se cortan los microsegundos antes de calcular (substr hasta los segundos):
    SQLite redondea al milisegundo, y una venta de las 05:59:59.9999 pasaba a
    las 06:00 y caía en el día siguiente, en desacuerdo con limites_de_los_dias.
    """
    return f"date(substr({columna}, 1, 19), '-{HORA_CAMBIO_DE_DIA} hours')"


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


# Tolerancia para decidir a qué turno pertenece lo que arranca a cierta hora
# (una caja que se abre, lo que sigue a un cierre): quien llega a las 13:25 ya
# es de la Tarde. Ver turno_que_arranca_tras_un_cierre. NO es lo que tarda en
# cerrarse sola una caja: eso es MINUTOS_PARA_CIERRE_FORZOSO.
TURNO_GRACIA_MIN = 40

# Cuántos minutos antes del fin del turno empieza a titilar en rojo el botón
# Cierre de Turno (pedido del dueño, 2026-10-18). Ver inicio_del_aviso_de_cierre.
MINUTOS_AVISO_ANTES_DEL_FIN = 5

# Cuántos minutos después del fin del turno la caja se cierra sola (cierre
# forzoso) y el turno pasa a contar como "sin cerrar" (pedido del dueño,
# 2026-10-18: "el programa aprieta solo Cierre de Turno"; eran 15 minutos de
# gracia y el 2026-10-20 pidió 30). Ver turno_vencimiento. Los carteles que lo
# nombran leen esta constante: cambiarla acá alcanza.
MINUTOS_PARA_CIERRE_FORZOSO = 30


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
    cerrar" un turno que sí se había cerrado. Con la misma regla se decide el
    turno de una caja que se abre (relevo_repo.abrir_caja): quien abre a las
    05:55 abre la Mañana.
    """
    return calcular_turno(momento_del_cierre + timedelta(minutes=TURNO_GRACIA_MIN))


def dia_del_turno_que_arranca_tras_un_cierre(momento_del_cierre: datetime) -> date:
    """
    El día al que pertenece el turno que arranca tras un cierre (el de
    turno_que_arranca_tras_un_cierre, con la misma tolerancia): es el día con el
    que va a quedar anotado el cierre siguiente.

    No alcanza con la fecha del cierre anterior: si ese cierre se hizo pasada la
    medianoche (la Tarde que se cerró a las 00:30, o una Noche cerrada dos veces
    porque cambió quien atendía), lo que sigue es todavía la Noche del día
    ANTERIOR, y tiene que sumar ahí. Con la tolerancia, un cierre de las 05:30
    deja lo que sigue en la Mañana del mismo día, como corresponde.
    """
    return dia_en_que_empezo_el_turno(momento_del_cierre + timedelta(minutes=TURNO_GRACIA_MIN))


def fin_del_turno(dia_base, turno: str) -> datetime:
    """
    A qué hora termina, según el horario del local, el turno `turno` del día
    `dia_base` (acepta lo mismo que es_domingo()): Mañana a las 14:00 (el
    domingo, a las 18:00), Tarde a las 22:00 y Noche a las 06:00.

    NOCHE cruza la medianoche, por eso termina a la madrugada del día
    SIGUIENTE al que arrancó — esto no cambia los domingos: tanto la
    noche normal como "Domingo T2" terminan igual a las 06:00 del día
    siguiente, lo único que cambia es a qué hora arrancan.
    """
    dia_base = _como_date(dia_base)
    domingo = dia_base.weekday() == 6
    inicio_dia = datetime(dia_base.year, dia_base.month, dia_base.day)

    if turno == dominio.TURNO_MANANA:
        return inicio_dia.replace(hour=18 if domingo else 14)
    if turno == dominio.TURNO_TARDE:
        return inicio_dia.replace(hour=22)
    return (inicio_dia + timedelta(days=1)).replace(hour=HORA_CAMBIO_DE_DIA)


def inicio_del_aviso_de_cierre(dia_base, turno: str) -> datetime:
    """Desde cuándo titila en rojo el botón Cierre de Turno: 5 minutos antes del
    fin del turno (ver MINUTOS_AVISO_ANTES_DEL_FIN). Desde ese mismo momento, a
    quien llega y encuentra abierta la caja de otra persona se le pide cerrarla
    en vez de recibirla (relevo_repo.situacion_al_entrar)."""
    return fin_del_turno(dia_base, turno) - timedelta(minutes=MINUTOS_AVISO_ANTES_DEL_FIN)


def turno_vencimiento(dia_base, turno: str) -> datetime:
    """
    Momento exacto en que el turno `turno` de un día calendario dado
    (`dia_base`, acepta lo mismo que es_domingo()) queda vencido: fin de
    su horario (fin_del_turno) + MINUTOS_PARA_CIERRE_FORZOSO de gracia.
    A esa hora la caja se cierra sola (cierre forzoso, ver MainWindow) y un
    turno del mes en curso que todavía no tiene cierre pasa a contar como
    "sin cerrar".
    """
    return fin_del_turno(dia_base, turno) + timedelta(minutes=MINUTOS_PARA_CIERRE_FORZOSO)
