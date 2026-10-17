"""
turnos_repo.py
===============
Todo lo que gira alrededor del turno y su cierre:
- Caja (consulta en vivo del turno en curso) y Cierre de Turno.
- Control de Cierres: historial, detalle venta por venta y verificación
  del sobre por el Admin.
- Resumen del Día (un día abierto por turno).
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
from repositories import turnos_faltantes_repo as _faltantes_repo
from repositories.turnos_ventas_repo import (
    _LINEAS_APARTE, _contar_ventas_entre, _sumar_ventas_por_origen_y_metodo, _vendido_aparte_entre,
)


# Desde cuándo cuenta la ventana del primer turno de la historia (todavía no
# hay un cierre anterior).
_PRINCIPIO_DE_LOS_TIEMPOS = "0000-01-01T00:00:00"

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
    "dia"} (`dia` es el date del día del local al que pertenece, ver
    _desde_y_turno_en_curso).

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
    return {
        "desde": desde,
        "hasta": ahora_dt.isoformat(timespec="microseconds"),
        "turno": turno,
        "dia": dia,
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


def _desde_del_cierre(conexion, cierre_id: int) -> str:
    """
    Desde cuándo cuenta lo vendido en el cierre `cierre_id`: la
    `fecha_cierre` del cierre anterior (por id), o el principio de los
    tiempos si es el primero que existe. Mismo criterio de ventana que
    usa cerrar_turno() para el turno en curso.
    """
    anterior = conexion.execute(
        "SELECT fecha_cierre FROM cierres_turno WHERE id < ? ORDER BY id DESC LIMIT 1",
        (cierre_id,),
    ).fetchone()
    return anterior["fecha_cierre"] if anterior else _PRINCIPIO_DE_LOS_TIEMPOS


def _cierre_o_error(conexion, cierre_id: int):
    """La fila del cierre `cierre_id`; ValueError si ese cierre no existe."""
    cierre = conexion.execute(
        "SELECT * FROM cierres_turno WHERE id = ?", (cierre_id,)
    ).fetchone()
    if cierre is None:
        raise ValueError("El cierre no existe.")
    return cierre


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
    """
    with conexion_db() as conexion:
        ventana = _ventana_en_curso(conexion)
        desglose = _desglose_de_totales(
            _sumar_ventas_por_origen_y_metodo(conexion, ventana["desde"], ventana["hasta"])
        )
        aparte = _vendido_aparte_entre(conexion, ventana["desde"], ventana["hasta"])

    fondo_cambio = obtener_fondo_cambio()

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
        "caja_actual": fondo_cambio + desglose["ventas_efectivo"],
        "desde": ventana["desde"],
        "hasta": ventana["hasta"],
    }


def cerrar_turno(usuario_id: int):
    """
    Cierra el turno en curso: calcula lo mismo que `resumen_turno_actual`
    y lo deja grabado en `cierres_turno`, listo para que la empleada
    sepa cuánto retirar (dejando el fondo de cambio en el cajón para el
    próximo turno). Devuelve el resumen guardado.
    """
    fondo_cambio = obtener_fondo_cambio()

    with conexion_db() as conexion:
        ventana = _ventana_en_curso(conexion)
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

    return {
        "id": cierre_id,
        "turno": turno,
        "turno_label": etiqueta_turno(fecha_turno, turno),
        "fondo_cambio": fondo_cambio,
        **desglose,
        "monto_a_retirar": monto_a_retirar,
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
        cierres = conexion.execute(
            """
            SELECT cierres_turno.*, usuarios.nombre AS empleada
            FROM cierres_turno
            JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
            WHERE cierres_turno.fecha = ?
            ORDER BY cierres_turno.id
            """,
            (dia.isoformat(),),
        ).fetchall()

        cierres_por_turno = {}
        aparte_por_turno = {}
        for cierre in cierres:
            desde = _desde_del_cierre(conexion, cierre["id"])
            confirmadas, anuladas = _contar_ventas_entre(conexion, desde, cierre["fecha_cierre"])
            cierres_por_turno.setdefault(cierre["turno"], []).append((cierre, confirmadas, anuladas))
            vendido = _vendido_aparte_entre(conexion, desde, cierre["fecha_cierre"], cierre_grabado=True)
            acumulado = aparte_por_turno.setdefault(cierre["turno"], {linea: 0.0 for linea in _LINEAS_APARTE})
            for linea in _LINEAS_APARTE:
                acumulado[linea] += vendido[linea]

        cierres_de_otro_dia = _cierres_hechos_ese_dia_y_anotados_antes(conexion, dia)

        # La ventana que está abierta ahora, si pertenece a este día.
        ventana = _ventana_en_curso(conexion, ahora_dt)
        abierta = None
        if ventana["dia"] == dia:
            totales = _sumar_ventas_por_origen_y_metodo(conexion, ventana["desde"], ventana["hasta"])
            confirmadas, anuladas = _contar_ventas_entre(conexion, ventana["desde"], ventana["hasta"])
            desglose = _desglose_de_totales(totales)
            abierta = {
                "turno": ventana["turno"], "confirmadas": confirmadas, "anuladas": anuladas,
                **_vendido_aparte_entre(conexion, ventana["desde"], ventana["hasta"]),
                **{campo: desglose[campo] for campo in _CAMPOS_PLATA},
            }

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


def listar_cierres(limite: int = 100):
    """Historial de cierres, para que el Admin controle turno por turno
    (y cargue el monto que contó en cada sobre)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT cierres_turno.*, usuarios.nombre AS empleada,
                   verificadores.nombre AS verificado_por_nombre
            FROM cierres_turno
            JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
            LEFT JOIN usuarios AS verificadores ON verificadores.id = cierres_turno.verificado_por
            ORDER BY cierres_turno.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()


def detalle_cierre(cierre_id: int):
    """
    Las ventas que componen un cierre puntual -- las que cayeron entre el
    cierre anterior y este (mismo criterio de rango que cerrar_turno() /
    resumen_turno_actual(): "desde" es el fecha_cierre del cierre previo
    por id, o el principio de los tiempos si es el primer cierre que
    existe). Es lo que le permite al Admin, desde "Control de Cierres de
    Turno", ver venta por venta cómo se llegó al total de un sobre en vez
    de confiar solo en el número agregado.

    Incluye ventas ANULADAS que hayan caído en la ventana (no se
    filtran): no suman al total ya grabado en el cierre (ese total se
    calculó en su momento solo con CONFIRMADAS, ver
    _sumar_ventas_por_origen_y_metodo), pero conviene poder verlas acá
    para entender un cierre que no cuadra. La pantalla las remarca aparte
    (mismo criterio que Consulta de Ventas), nunca se ocultan.
    """
    with conexion_db() as conexion:
        cierre = _cierre_o_error(conexion, cierre_id)
        desde = _desde_del_cierre(conexion, cierre_id)

        ventas = conexion.execute(
            """
            SELECT ventas.*, usuarios.nombre AS vendedor,
                   GROUP_CONCAT(DISTINCT venta_pagos.metodo) AS metodos
            FROM ventas
            JOIN usuarios ON usuarios.id = ventas.usuario_id
            LEFT JOIN venta_pagos ON venta_pagos.venta_id = ventas.id
            WHERE ventas.fecha > ? AND ventas.fecha <= ?
            GROUP BY ventas.id
            ORDER BY ventas.fecha
            """,
            (desde, cierre["fecha_cierre"]),
        ).fetchall()

    return {"cierre": cierre, "desde": desde, "ventas": ventas}


def verificar_cierre(cierre_id: int, monto_contado: float, usuario_admin_id: int):
    """
    El Admin carga cuánta plata contó realmente en el sobre de un cierre
    puntual. Se calcula la diferencia contra lo esperado (monto_a_retirar)
    para detectar faltantes o sobrantes por empleada/turno.
    """
    with conexion_db() as conexion:
        cierre = _cierre_o_error(conexion, cierre_id)

        monto_contado = round(monto_contado, 2)
        diferencia = round(monto_contado - cierre["monto_a_retirar"], 2)
        ahora = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """
            UPDATE cierres_turno
            SET monto_contado = ?, diferencia = ?, verificado_por = ?, fecha_verificacion = ?
            WHERE id = ?
            """,
            (monto_contado, diferencia, usuario_admin_id, ahora, cierre_id),
        )


def turnos_del_mes_actual():
    return _faltantes_repo.turnos_del_mes_actual(datetime.now().date())


def turnos_faltantes():
    return _faltantes_repo.turnos_faltantes(datetime.now())
