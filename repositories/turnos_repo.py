"""
turnos_repo.py
===============
Todo lo que gira alrededor del turno y su cierre:
- Caja (consulta en vivo del turno en curso) y Cierre de Turno.
- Resumen del Día (un día abierto por turno).
Control de Cierres (historial, detalle venta por venta y verificación del
sobre) vive en control_cierres_repo.py y se reexporta acá con los mismos
nombres. Las cajas con número (quién tiene la caja, relevos) están en
cajas_repo.py y relevo_repo.py: acá solo se las une a su cierre.
Los turnos vencidos sin cierre viven en turnos_faltantes_repo.py y se
reexportan acá para conservar la API de las pantallas.
Las consultas de "qué se vendió en una ventana (desde, hasta]" (por origen y
método, cuántas ventas, impresiones y trámites aparte) viven en
turnos_ventas_repo.py (se separaron el 2026-10-17, cuando este archivo pasó
las 600 líneas) y se usan desde acá con los mismos nombres.

Idea central: en vez de calcular los turnos con horarios rígidos (lo cual
se complica porque el turno "NOCHE" cruza la medianoche, y porque a veces
una empleada llega unos minutos tarde), un turno "en curso" es
simplemente: *todo lo vendido desde el último cierre hasta ahora*.
Así, sin importar la hora exacta a la que alguien cierra, nunca se cuenta
una venta dos veces ni se pierde ninguna.

Las fechas se comparan como texto ISO con microsegundos (ver el comentario
en `cerrar_turno`): la ventana de un turno es (último cierre, ahora].
"""

from datetime import date, datetime
import dominio
from database import conexion_db
from turnos import (
    calcular_turno, dia_del_turno_que_arranca_tras_un_cierre, dia_en_que_empezo_el_turno, etiqueta_turno,
    limites_de_los_dias, turno_que_arranca_tras_un_cierre, turno_vencimiento, turnos_del_dia,
)
from repositories.config_repo import obtener_fondo_cambio
from repositories import cajas_repo
from repositories import turnos_faltantes_repo as _faltantes_repo
from repositories.control_cierres_repo import (  # noqa: F401 (API de las pantallas y las pruebas)
    _PRINCIPIO_DE_LOS_TIEMPOS, _cierre_o_error, _desde_del_cierre, detalle_cierre, listar_cierres,
    verificar_cierre,
)
from repositories.turnos_ventas_repo import (
    _LINEAS_APARTE, _contar_ventas_entre, _sumar_ventas_por_origen_y_metodo, _vendido_aparte_entre,
)


# Con qué prefijo se llaman, en el desglose de un turno y en las columnas de
# "cierres_turno", los importes de cada origen de venta (kiosko_efectivo,
# pcs_digital, ...). Tiene que tener TODOS los dominio.ORIGENES_VENTA: un origen
# que falte acá haría desaparecer su plata del cierre (ver _desglose_de_totales y
# TestCadaOrigenSumaEnLaCaja).
_PREFIJO_COLUMNAS_POR_ORIGEN = {
    dominio.ORIGEN_KIOSKO: "kiosko",
    dominio.ORIGEN_ALQUILER_PCS: "pcs",
    dominio.ORIGEN_PLAYSTATION: "playstation",
}

# Los importes en que se desglosa lo cobrado en un turno (origen x método): son
# las columnas de cierres_turno (ver _desglose_de_totales).
_CAMPOS_PLATA = tuple(
    f"{prefijo}_{metodo}"
    for prefijo in _PREFIJO_COLUMNAS_POR_ORIGEN.values()
    for metodo in ("efectivo", "digital")
)


def _obtener_ultimo_cierre(conexion):
    """El cierre más reciente (por id), o None si todavía no hubo ninguno."""
    return conexion.execute(
        "SELECT * FROM cierres_turno ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _desde_y_turno_en_curso(ultimo_cierre, ahora_dt):
    """
    Desde cuándo se viene sumando el turno en curso (`fecha_cierre` del
    último cierre, o el principio de los tiempos si todavía no hay
    ninguno) y a qué turno y a qué DÍA pertenece esa ventana -- el turno y
    el día que van a quedar grabados si alguien confirma el cierre ahora mismo.

    Único lugar donde se decide esto, para que lo que muestra Caja
    (`resumen_turno_actual`) SIEMPRE coincida con lo que graba
    `cerrar_turno`. El turno es el de cuándo ARRANCÓ lo que sigue sin
    cerrar, no el de la hora actual: a las 14:05, con la Mañana todavía
    sin cerrar, el cierre se graba como "Mañana", no como "Tarde".

    "Cuándo arrancó" es la hora del cierre anterior con una tolerancia
    (turnos.turno_que_arranca_tras_un_cierre): si ese cierre se hizo unos
    minutos ANTES del cambio de turno (13:55), lo que sigue es de la Tarde.
    El primer cierre de todos no tiene cierre anterior: arranca "ahora".

    El día es el del local (de 06:00 a 06:00, ver turnos.HORA_CAMBIO_DE_DIA), no
    la fecha del cierre anterior: si ese cierre fue pasada la medianoche (la
    Tarde cerrada a las 00:30, o la Noche cerrada dos veces), lo que sigue sigue
    siendo la Noche del día anterior y tiene que sumar ahí.
    """
    if ultimo_cierre:
        desde = ultimo_cierre["fecha_cierre"]
        inicio_del_turno = datetime.fromisoformat(desde)
        turno = turno_que_arranca_tras_un_cierre(inicio_del_turno)
        dia = dia_del_turno_que_arranca_tras_un_cierre(inicio_del_turno)
    else:
        desde = _PRINCIPIO_DE_LOS_TIEMPOS
        inicio_del_turno = ahora_dt
        turno = calcular_turno(inicio_del_turno)
        dia = dia_en_que_empezo_el_turno(inicio_del_turno)
    return desde, turno, dia


def _ventana_en_curso(conexion, ahora_dt=None) -> dict:
    """
    La ventana del turno que está abierto ahora: {"desde", "hasta", "turno",
    "dia", "caja"} (`dia` es el date del día del local al que pertenece, ver
    _desde_y_turno_en_curso).

    Con una caja abierta (cajas_repo), el turno y el día son los de la caja,
    decididos al abrirla: quien abre a las 05:55 abre la Mañana, aunque el
    cierre anterior haya sido de madrugada o de hace horas. "desde" sigue siendo
    el último cierre: entre ese cierre y la apertura no se puede vender sin caja
    (relevo_repo pide cerrar antes lo que haya quedado). "caja" es la fila de la
    caja abierta, o None.

    `ahora_dt` solo se pasa si quien llama ya tomó la hora antes (como
    resumen_del_dia, que la necesita también para otras cosas); si no, se
    toma acá, después de leer el último cierre.

    "hasta" lleva microsegundos, no segundos: en cerrar_turno es lo que se
    graba en "cierres_turno.fecha_cierre", el límite que separa un turno del
    siguiente (fecha > desde AND fecha <= hasta, ver
    _sumar_ventas_por_origen_y_metodo). Con precisión de un segundo, una
    venta hecha justo al abrir el turno siguiente podía empatar con ese
    cierre y quedar afuera de los DOS turnos. ventas_repo graba
    "ventas.fecha" con la misma precisión por la misma razón.
    """
    ultimo_cierre = _obtener_ultimo_cierre(conexion)
    if ahora_dt is None:
        ahora_dt = datetime.now()
    desde, turno, dia = _desde_y_turno_en_curso(ultimo_cierre, ahora_dt)
    caja = cajas_repo._caja_abierta(conexion)
    if caja is not None:
        turno, dia = caja["turno"], date.fromisoformat(caja["fecha"])
    return {
        "desde": desde,
        "hasta": ahora_dt.isoformat(timespec="microseconds"),
        "turno": turno,
        "dia": dia,
        "caja": caja,
    }


def _desglose_de_totales(totales: dict) -> dict:
    """
    Pasa {origen: {metodo: total}} (lo que devuelve
    _sumar_ventas_por_origen_y_metodo) al desglose que muestran Caja y los
    cierres: los importes de _CAMPOS_PLATA más el total en efectivo y el total
    digital de todos los negocios juntos. Único lugar donde se hace esta cuenta.

    Los dos totales suman TODOS los dominio.ORIGENES_VENTA, no una lista
    escrita a mano: es lo que dice cuánto efectivo tiene que haber en el cajón,
    y un origen que se olvide acá haría "faltar" esa plata en cada cierre.
    """
    desglose = {}
    for origen, prefijo in _PREFIJO_COLUMNAS_POR_ORIGEN.items():
        desglose[f"{prefijo}_efectivo"] = totales[origen][dominio.PAGO_EFECTIVO]
        desglose[f"{prefijo}_digital"] = totales[origen][dominio.PAGO_DIGITAL]
    desglose["ventas_efectivo"] = sum(totales[origen][dominio.PAGO_EFECTIVO] for origen in dominio.ORIGENES_VENTA)
    desglose["ventas_digital"] = sum(totales[origen][dominio.PAGO_DIGITAL] for origen in dominio.ORIGENES_VENTA)
    return desglose


def resumen_turno_actual():
    """
    Para la pantalla "Caja" y la vista previa de "Cierre de Turno": muestra
    cómo viene el turno en curso sin cerrarlo. Devuelve un diccionario con
    fondo de cambio, ventas en efectivo y digital acumuladas desde el último
    cierre, y cuánto debería haber ahora mismo en el cajón.

    "impresiones" (lo vendido del artículo IMPRESIONES) y "tramites" (lo cobrado
    por trámites) en esta ventana son datos informativos para el Cierre de
    Turno: YA están sumados dentro de kiosko_efectivo/kiosko_digital, no se les
    resta, porque esos dos importes llevan el desglose por medio de pago y estas
    dos líneas se cuentan por renglón de venta, no por medio de pago.

    Con una caja abierta trae también "caja_numero" y "responsable" (si no,
    None), y "cambio_inicial" es el cambio con que arrancó esa caja (lo que se
    contó al abrirla); sin caja, el Cambio Fijo. "caja_actual" (lo que tendría
    que haber en el cajón) sale de ahí: es lo que cuenta quien recibe la caja en
    un relevo (relevo_repo.recibir_caja).
    """
    with conexion_db() as conexion:
        return _resumen_en_curso(conexion)


def _resumen_en_curso(conexion, ahora_dt=None) -> dict:
    """resumen_turno_actual() sobre una conexión ya abierta (y, si se pasa,
    a la hora `ahora_dt`): relevo_repo lo usa dentro de su propia transacción
    para saber cuánto tiene que haber en el cajón al recibir una caja."""
    ventana = _ventana_en_curso(conexion, ahora_dt)
    desglose = _desglose_de_totales(
        _sumar_ventas_por_origen_y_metodo(conexion, ventana["desde"], ventana["hasta"])
    )
    aparte = _vendido_aparte_entre(conexion, ventana["desde"], ventana["hasta"])

    fondo_cambio = obtener_fondo_cambio()
    caja = ventana["caja"]
    cambio_inicial = cajas_repo.cambio_inicial(caja) if caja is not None else fondo_cambio

    return {
        "turno_actual": ventana["turno"],
        "turno_actual_label": etiqueta_turno(ventana["dia"], ventana["turno"]),
        "fondo_cambio": fondo_cambio,
        **desglose,
        "impresiones": round(aparte["impresiones"], 2),
        "tramites": round(aparte["tramites"], 2),
        # Todo lo cobrado en el turno (efectivo + digital de todos los negocios).
        # Las impresiones y los trámites no se suman: ya están dentro de Kiosko.
        "ventas_total": round(desglose["ventas_efectivo"] + desglose["ventas_digital"], 2),
        "cambio_inicial": cambio_inicial,
        "caja_actual": round(cambio_inicial + desglose["ventas_efectivo"], 2),
        "caja_numero": caja["id"] if caja is not None else None,
        "responsable": caja["responsable"] if caja is not None else None,
        "desde": ventana["desde"],
        "hasta": ventana["hasta"],
    }


def cerrar_turno(usuario_id: int, forzoso: bool = False, ahora_dt=None):
    """
    Cierra el turno en curso: calcula lo mismo que `resumen_turno_actual`
    y lo deja grabado en `cierres_turno`, listo para que la empleada
    sepa cuánto retirar (dejando el fondo de cambio en el cajón para el
    próximo turno). Devuelve el resumen guardado.

    Si hay una caja abierta, queda unida a este cierre (deja de estar abierta).
    `usuario_id` es quien cierra: si no es la responsable de la caja, queda
    como cerrada en su ausencia (ver control_cierres_repo._datos_de_la_caja).
    `forzoso` es el cierre que hace el programa solo a los 15 minutos del fin
    del turno (ver MainWindow y relevo_repo). `ahora_dt` es la hora del cierre
    si quien llama ya la tomó (relevo_repo); si no, ahora.

    Lo que queda en el cajón ("cambio_que_queda") es el cambio con que arrancó
    la caja: lo que contó quien la abrió. Así un faltante del cambio se ve una
    sola vez, en la caja donde apareció, y no en todas las que siguen.
    """
    fondo_cambio = obtener_fondo_cambio()

    with conexion_db() as conexion:
        ventana = _ventana_en_curso(conexion, ahora_dt)
        caja = ventana["caja"]
        desglose = _desglose_de_totales(
            _sumar_ventas_por_origen_y_metodo(conexion, ventana["desde"], ventana["hasta"])
        )
        turno = ventana["turno"]
        monto_a_retirar = desglose["ventas_efectivo"]

        # "fecha" guarda el día en que ARRANCÓ el turno (el mismo criterio
        # que "turno", justo arriba) y no el día en que se lo cerró: para
        # un turno Noche cerrado ya pasada la medianoche, esos dos días son
        # distintos, y turnos_faltantes() necesita que coincida con el día
        # que arma turnos_del_mes_actual() para poder cruzarlos. Es el día del
        # local (06:00 a 06:00): una Noche entra entera en el día en que empezó.
        fecha_turno = ventana["dia"]

        # Los nombres de columna salen de _CAMPOS_PLATA (texto fijo del
        # programa, nunca un dato de la usuaria): sumar un origen nuevo no
        # obliga a tocar este INSERT.
        cursor = conexion.execute(
            f"""
            INSERT INTO cierres_turno
                (fecha, turno, usuario_id, fecha_cierre, fondo_cambio,
                 ventas_efectivo, ventas_digital, monto_a_retirar,
                 {", ".join(_CAMPOS_PLATA)})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, {", ".join("?" for _ in _CAMPOS_PLATA)})
            """,
            (
                fecha_turno.isoformat(),
                turno,
                usuario_id,
                ventana["hasta"],
                fondo_cambio,
                desglose["ventas_efectivo"],
                desglose["ventas_digital"],
                monto_a_retirar,
                *(desglose[campo] for campo in _CAMPOS_PLATA),
            ),
        )
        cierre_id = cursor.lastrowid
        if caja is not None:
            cajas_repo._marcar_cerrada(conexion, caja["id"], cierre_id, forzoso)

    return {
        "id": cierre_id,
        "turno": turno,
        "turno_label": etiqueta_turno(fecha_turno, turno),
        "fondo_cambio": fondo_cambio,
        **desglose,
        "monto_a_retirar": monto_a_retirar,
        "caja_numero": caja["id"] if caja is not None else None,
        "responsable": caja["responsable"] if caja is not None else None,
        "cambio_que_queda": cajas_repo.cambio_inicial(caja) if caja is not None else fondo_cambio,
        "forzoso": forzoso,
    }


# Estados de un turno en el reporte del día (resumen_del_dia). Son un
# rótulo de la pantalla, no algo que se guarde en la base: por eso viven
# acá y no en dominio.py.
ESTADO_CERRADO = "CERRADO"
ESTADO_EN_CURSO = "EN_CURSO"
ESTADO_SIN_CERRAR = "SIN_CERRAR"
ESTADO_PENDIENTE = "PENDIENTE"


def _cerrado_pasado_su_vencimiento(dia_del_turno, turno: str, cerrado_a: str) -> bool:
    """
    Si el turno `turno` del día `dia_del_turno` (date o "YYYY-MM-DD") se cerró en
    `cerrado_a` (fecha ISO del cierre) pasado su vencimiento, con su gracia (ver
    turnos.turno_vencimiento). La Noche que se cierra a la madrugada siguiente es lo
    normal y no cuenta; un turno que quedó abierto hasta el día siguiente o más, sí.
    Es lo que decide qué cierres avisa y aclara el Resumen del Día. Se compara como
    texto ISO, igual que el resto del archivo.
    """
    return cerrado_a > turno_vencimiento(dia_del_turno, turno).isoformat()


def _cierres_hechos_ese_dia_y_anotados_antes(conexion, dia: date) -> list:
    """
    Los cierres que se HICIERON el día `dia` pero quedaron anotados
    (`cierres_turno.fecha`) en un día anterior. Un cierre se anota en el turno
    donde ARRANCÓ lo que cierra, o sea desde el cierre anterior (ver
    _desde_y_turno_en_curso): si pasaron días sin cerrar, el cierre de hoy cae
    en el turno viejo y su plata NO figura en las filas de hoy. El reporte lo
    avisa para que no parezca que esa plata se perdió.

    No se avisa la Noche que se cierra a la madrugada siguiente, que es lo normal
    (ver _cerrado_pasado_su_vencimiento). "Ese día" es el día del local, de
    06:00 a 06:00 (ver turnos.limites_de_los_dias).
    """
    hecho_desde, hecho_hasta = limites_de_los_dias(dia, dia)
    filas = conexion.execute(
        """
        SELECT cierres_turno.fecha, cierres_turno.turno, cierres_turno.fecha_cierre,
               usuarios.nombre AS empleada
        FROM cierres_turno
        JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
        WHERE cierres_turno.fecha < ?
          AND cierres_turno.fecha_cierre >= ?
          AND cierres_turno.fecha_cierre < ?
        ORDER BY cierres_turno.id
        """,
        # cierres_turno.fecha es solo el día ("YYYY-MM-DD"): se compara contra el
        # día, no contra las 06:00 (como texto, "2026-10-01" < "2026-10-01T06:00").
        (dia.isoformat(), hecho_desde, hecho_hasta),
    ).fetchall()
    return [
        {
            "fecha": fila["fecha"],
            "turno": fila["turno"],
            "etiqueta": etiqueta_turno(fila["fecha"], fila["turno"]),
            "responsable": fila["empleada"],
            "cerrado_a": fila["fecha_cierre"],
        }
        for fila in filas
        if _cerrado_pasado_su_vencimiento(fila["fecha"], fila["turno"], fila["fecha_cierre"])
    ]


def _ventanas_del_dia(conexion, dia, ahora_dt) -> list:
    """
    Los tramos de ventas que forman los turnos de `dia` (un date), en orden:
    uno por cada cierre anotado en ese día -- (cierre anterior, este cierre] --
    y, si la ventana abierta ahora es de ese día, también ella (hasta ahora).
    Cada uno es {"turno", "desde", "hasta", "cierre"}; "cierre" es la fila del
    cierre (con "empleada": quien tenía la caja, o quien cerró si no había
    caja) o None para la ventana abierta.

    Es la única definición de "qué ventas son de qué turno de un día": la usan
    resumen_del_dia (las filas de cada turno) y detalle_dia_repo (venta por
    venta), así el detalle siempre suma lo mismo que la fila de su turno.
    """
    # "empleada" es quien tenía la caja (cajas_repo), no quien la cerró: la
    # caja que cierra la que llega, en ausencia de la otra, sigue siendo de la
    # otra. Un cierre sin caja (de antes de las cajas) muestra quién cerró.
    cierres = conexion.execute(
        """
        SELECT cierres_turno.*, COALESCE(responsables.nombre, usuarios.nombre) AS empleada
        FROM cierres_turno
        JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
        LEFT JOIN cajas ON cajas.cierre_id = cierres_turno.id
        LEFT JOIN usuarios AS responsables ON responsables.id = cajas.responsable_id
        WHERE cierres_turno.fecha = ?
        ORDER BY cierres_turno.id
        """,
        (dia.isoformat(),),
    ).fetchall()
    ventanas = [
        {"turno": cierre["turno"], "desde": _desde_del_cierre(conexion, cierre["id"]),
         "hasta": cierre["fecha_cierre"], "cierre": cierre}
        for cierre in cierres
    ]
    abierta = _ventana_en_curso(conexion, ahora_dt)
    if abierta["dia"] == dia:
        ventanas.append({"turno": abierta["turno"], "desde": abierta["desde"], "hasta": abierta["hasta"], "cierre": None})
    return ventanas


def resumen_del_dia(dia):
    """
    El reporte de UN día del local, abierto por turno (Mañana/Tarde/Noche,
    o Domingo T1/T2): qué se vendió en cada uno, quién lo cerró y cuánto
    faltó o sobró al contar el sobre.

    Un turno pertenece al día en que ARRANCÓ (mismo criterio que
    `cierres_turno.fecha`, ver cerrar_turno): la Noche del lunes incluye lo
    vendido hasta las 06:00 del martes, y entra entera en el lunes (pedido del
    dueño: el día va de 06:00 a 06:00, ver turnos.HORA_CAMBIO_DE_DIA). Y la plata de cada turno es la de
    su CIERRE, no la que daría mirar el reloj: si quien atiende la Mañana
    se queda hasta las 17, esas ventas son de su turno aunque pasen de las
    14 -- coherente con lo que se ve en Caja y Cierre de Turno.

    Por cada turno esperado ese día (turnos.turnos_del_dia) devuelve uno de
    cuatro estados:
      - CERRADO: tiene al menos un cierre. Si se cerró más de una vez
        (cierre de más, o turno partido) se suman todos.
      - EN_CURSO: es la ventana abierta ahora mismo (lo vendido desde el
        último cierre) -- se muestra en vivo, todavía sin cerrar.
      - SIN_CERRAR: ya venció (con su gracia, ver turnos.turno_vencimiento)
        y nadie lo cerró.
      - PENDIENTE: todavía no es hora de que esté cerrado.

    Devuelve {"fecha", "turnos": [...], "total": {...}, "cierres_de_otro_dia":
    [...]} con el total del día sumando los turnos. "cierres_de_otro_dia" son
    los cierres que se hicieron este día pero quedaron anotados en un turno de
    un día anterior (ver _cierres_hechos_ese_dia_y_anotados_antes): su plata
    está en las filas de ESE día, no en las de este.

    "impresiones" (lo vendido del artículo IMPRESIONES, ver
    dominio.CODIGO_ARTICULO_IMPRESIONES) y "tramites" (lo cobrado por
    trámites, ver tramites_repo) salen aparte de "kiosko": el cierre guarda
    un solo importe de Kiosko, así que acá se les resta, y kiosko +
    impresiones + tramites + pcs + playstation sigue dando "total" ("playstation"
    es lo cobrado por los bonos de la consola, origen aparte, así que no se resta
    de nada). Efectivo/Digital no cambian (se cobraron igual, por esos medios).
    """
    dia = date.fromisoformat((dia if isinstance(dia, str) else dia.isoformat())[:10])
    ahora_dt = datetime.now()

    with conexion_db() as conexion:
        cierres_por_turno = {}
        aparte_por_turno = {}
        abierta = None
        for ventana in _ventanas_del_dia(conexion, dia, ahora_dt):
            desde, hasta = ventana["desde"], ventana["hasta"]
            cierre = ventana["cierre"]
            confirmadas, anuladas = _contar_ventas_entre(conexion, desde, hasta)
            if cierre is None:
                # La ventana que está abierta ahora: se muestra en vivo.
                desglose = _desglose_de_totales(_sumar_ventas_por_origen_y_metodo(conexion, desde, hasta))
                abierta = {
                    "turno": ventana["turno"], "confirmadas": confirmadas, "anuladas": anuladas,
                    **_vendido_aparte_entre(conexion, desde, hasta),
                    **{campo: desglose[campo] for campo in _CAMPOS_PLATA},
                }
                continue
            cierres_por_turno.setdefault(cierre["turno"], []).append((cierre, confirmadas, anuladas))
            vendido = _vendido_aparte_entre(conexion, desde, hasta, cierre_grabado=True)
            acumulado = aparte_por_turno.setdefault(cierre["turno"], {linea: 0.0 for linea in _LINEAS_APARTE})
            for linea in _LINEAS_APARTE:
                acumulado[linea] += vendido[linea]

        cierres_de_otro_dia = _cierres_hechos_ese_dia_y_anotados_antes(conexion, dia)

    # Los turnos esperados del día, más cualquier otro que tenga cierre o
    # esté abierto (no debería pasar, pero un dato raro no puede esconder
    # plata): así el total del día nunca queda corto.
    turnos = list(turnos_del_dia(dia))
    extras = set(cierres_por_turno) | ({abierta["turno"]} if abierta else set())
    turnos += [t for t in dominio.TURNOS if t in extras and t not in turnos]

    resultado = []
    for turno in turnos:
        grupo = cierres_por_turno.get(turno, [])
        parcial = abierta if (abierta is not None and abierta["turno"] == turno) else None

        plata = {campo: 0.0 for campo in _CAMPOS_PLATA}
        for cierre, _, _ in grupo:
            for campo in _CAMPOS_PLATA:
                plata[campo] += cierre[campo] or 0.0
        if parcial is not None:
            for campo in _CAMPOS_PLATA:
                plata[campo] += parcial[campo]

        aparte = {
            linea: aparte_por_turno.get(turno, {}).get(linea, 0.0) + (parcial[linea] if parcial else 0.0)
            for linea in _LINEAS_APARTE
        }

        if parcial is not None:
            estado = ESTADO_EN_CURSO
        elif grupo:
            estado = ESTADO_CERRADO
        elif turno_vencimiento(dia, turno) <= ahora_dt:
            estado = ESTADO_SIN_CERRAR
        else:
            estado = ESTADO_PENDIENTE

        # El sobre solo se puede dar por contado si TODOS los cierres del
        # turno ya fueron verificados por un Admin y no hay una ventana
        # abierta sumando más plata encima.
        verificado = bool(grupo) and parcial is None and all(c["monto_contado"] is not None for c, _, _ in grupo)

        cerrado_a = grupo[-1][0]["fecha_cierre"] if grupo and parcial is None else None
        resultado.append({
            "turno": turno,
            "etiqueta": etiqueta_turno(dia, turno),
            "estado": estado,
            "responsables": list(dict.fromkeys(c["empleada"] for c, _, _ in grupo)),
            "cerrado_a": cerrado_a,
            # Se terminó de cerrar OTRO día y pasado su vencimiento (no la Noche que se
            # cierra a la madrugada): la pantalla lo aclara ("Cerrado el 10/10"), porque
            # la hora sola parecería de este mismo día.
            "cerrado_otro_dia": bool(
                cerrado_a
                and cerrado_a[:10] != dia.isoformat()
                and _cerrado_pasado_su_vencimiento(dia, turno, cerrado_a)
            ),
            "cantidad_ventas": sum(g[1] for g in grupo) + (parcial["confirmadas"] if parcial else 0),
            "cantidad_anuladas": sum(g[2] for g in grupo) + (parcial["anuladas"] if parcial else 0),
            **plata,
            "kiosko": round(plata["kiosko_efectivo"] + plata["kiosko_digital"] - sum(aparte.values()), 2),
            **{linea: round(monto, 2) for linea, monto in aparte.items()},
            "pcs": plata["pcs_efectivo"] + plata["pcs_digital"],
            "playstation": plata["playstation_efectivo"] + plata["playstation_digital"],
            "efectivo": sum(plata[campo] for campo in _CAMPOS_PLATA if campo.endswith("_efectivo")),
            "digital": sum(plata[campo] for campo in _CAMPOS_PLATA if campo.endswith("_digital")),
            "total": sum(plata.values()),
            "verificado": verificado,
            "diferencia": round(sum(c["diferencia"] for c, _, _ in grupo), 2) if verificado else None,
        })

    total = {
        clave: sum(fila[clave] for fila in resultado)
        for clave in ("kiosko", *_LINEAS_APARTE, "pcs", "playstation", "efectivo", "digital", "total",
                      "cantidad_ventas", "cantidad_anuladas")
    }
    return {"fecha": dia, "turnos": resultado, "total": total, "cierres_de_otro_dia": cierres_de_otro_dia}


def turnos_del_mes_actual():
    return _faltantes_repo.turnos_del_mes_actual(datetime.now().date())


def turnos_faltantes():
    return _faltantes_repo.turnos_faltantes(datetime.now())
