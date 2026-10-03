"""
turnos_repo.py
===============
Lógica de Caja (consulta en vivo) y Cierre de Turno.

Idea central: en vez de calcular los turnos con horarios rígidos (lo cual
se complica porque el turno "NOCHE" cruza la medianoche, y porque a veces
una empleada llega unos minutos tarde), un turno "en curso" es
simplemente: *todo lo vendido desde el último cierre hasta ahora*.
Así, sin importar la hora exacta a la que alguien cierra, nunca se cuenta
una venta dos veces ni se pierde ninguna.
"""

from datetime import date, datetime, timedelta
import dominio
from database import conexion_db
from turnos import calcular_turno, etiqueta_turno, turno_vencimiento, turnos_del_dia
from repositories.config_repo import obtener_fondo_cambio


def _obtener_ultimo_cierre(conexion):
    return conexion.execute(
        "SELECT * FROM cierres_turno ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _sumar_ventas_por_origen_y_metodo(conexion, desde: str, hasta: str):
    """
    Como antes, pero separado también por origen (ver dominio.ORIGENES_VENTA)
    y no solo por método de pago: es lo que le permite al dueño ver, en
    Caja y en Cierre de Turno, cuánto entró por productos de kiosko contra
    cuánto por alquiler de PCs, en vez de un solo total mezclado.
    Devuelve {origen: {metodo: total}}, considerando solo ventas
    CONFIRMADAS (una venta anulada no debe contar en la caja).
    """
    filas = conexion.execute(
        """
        SELECT ventas.origen AS origen, venta_pagos.metodo AS metodo,
               SUM(venta_pagos.monto) AS total
        FROM venta_pagos
        JOIN ventas ON ventas.id = venta_pagos.venta_id
        WHERE ventas.estado = ?
          AND ventas.fecha > ?
          AND ventas.fecha <= ?
        GROUP BY ventas.origen, venta_pagos.metodo
        """,
        (dominio.VENTA_CONFIRMADA, desde, hasta),
    ).fetchall()
    totales = {origen: {metodo: 0.0 for metodo in dominio.METODOS_PAGO} for origen in dominio.ORIGENES_VENTA}
    for fila in filas:
        totales[fila["origen"]][fila["metodo"]] = fila["total"] or 0.0
    return totales


def _desde_y_turno_en_curso(ultimo_cierre, ahora_dt):
    """
    Desde cuándo se viene sumando el turno en curso (`fecha_cierre` del
    último cierre, o el principio de los tiempos si todavía no hay
    ninguno) y a qué turno pertenece esa ventana -- el turno que va a
    quedar grabado si alguien confirma el cierre ahora mismo. Único lugar
    donde se decide esto: antes `resumen_turno_actual` mostraba el turno
    de la hora ACTUAL (calcular_turno(ahora)) mientras que `cerrar_turno`
    grababa el turno de cuándo ARRANCÓ lo que sigue sin cerrar, y podían
    no coincidir -- ej. a las 14:05, con la Mañana todavía sin cerrar, el
    título de Caja/Cierre de Turno ya decía "Tarde" pero al confirmar
    quedaba grabado como "Mañana". Con esta única función, lo que se
    muestra en pantalla SIEMPRE coincide con lo que se va a grabar.
    """
    desde = ultimo_cierre["fecha_cierre"] if ultimo_cierre else "0000-01-01T00:00:00"
    inicio_del_turno = datetime.fromisoformat(desde) if ultimo_cierre else ahora_dt
    turno = calcular_turno(inicio_del_turno)
    return desde, turno, inicio_del_turno


def resumen_turno_actual():
    """
    Para la pantalla "Caja": muestra cómo viene el turno en curso sin
    cerrarlo. Devuelve un diccionario con fondo de cambio, ventas en
    efectivo y digital acumuladas desde el último cierre, y cuánto
    debería haber ahora mismo en el cajón.
    """
    with conexion_db() as conexion:
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        ahora_dt = datetime.now()
        desde, turno_actual, inicio_del_turno = _desde_y_turno_en_curso(ultimo_cierre, ahora_dt)
        # Microsegundos, no segundos: mismo motivo que ventas_repo (ver ahí)
        # -- acá "ahora" se compara contra "ventas.fecha" para armar la
        # vista en vivo de Caja.
        ahora = ahora_dt.isoformat(timespec="microseconds")
        totales = _sumar_ventas_por_origen_y_metodo(conexion, desde, ahora)

    kiosko_efectivo = totales[dominio.ORIGEN_KIOSKO][dominio.PAGO_EFECTIVO]
    kiosko_digital = totales[dominio.ORIGEN_KIOSKO][dominio.PAGO_DIGITAL]
    pcs_efectivo = totales[dominio.ORIGEN_ALQUILER_PCS][dominio.PAGO_EFECTIVO]
    pcs_digital = totales[dominio.ORIGEN_ALQUILER_PCS][dominio.PAGO_DIGITAL]
    ventas_efectivo = kiosko_efectivo + pcs_efectivo
    ventas_digital = kiosko_digital + pcs_digital

    fondo_cambio = obtener_fondo_cambio()

    return {
        "turno_actual": turno_actual,
        "turno_actual_label": etiqueta_turno(inicio_del_turno.date(), turno_actual),
        "fondo_cambio": fondo_cambio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_digital": ventas_digital,
        "kiosko_efectivo": kiosko_efectivo,
        "kiosko_digital": kiosko_digital,
        "pcs_efectivo": pcs_efectivo,
        "pcs_digital": pcs_digital,
        "caja_actual": fondo_cambio + ventas_efectivo,
        "desde": desde,
        "hasta": ahora,
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
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        ahora_dt = datetime.now()
        desde, turno, inicio_del_turno = _desde_y_turno_en_curso(ultimo_cierre, ahora_dt)
        # Microsegundos, no segundos: esto graba "cierres_turno.fecha_cierre",
        # el límite que separa un turno del siguiente (ver
        # _sumar_ventas_por_origen_y_metodo, fecha > desde AND fecha <=
        # hasta). Con precisión de un segundo, una venta hecha justo al
        # abrir el turno siguiente podía caer en el mismo segundo que este
        # cierre y quedar afuera de los DOS turnos -- ni en el que se
        # estaba cerrando (llegó después del corte) ni en el siguiente (el
        # ">" estricto la excluía por el empate). Ver el mismo comentario
        # en ventas_repo.confirmar_venta / registrar_venta_sin_detalle.
        ahora = ahora_dt.isoformat(timespec="microseconds")

        totales = _sumar_ventas_por_origen_y_metodo(conexion, desde, ahora)
        kiosko_efectivo = totales[dominio.ORIGEN_KIOSKO][dominio.PAGO_EFECTIVO]
        kiosko_digital = totales[dominio.ORIGEN_KIOSKO][dominio.PAGO_DIGITAL]
        pcs_efectivo = totales[dominio.ORIGEN_ALQUILER_PCS][dominio.PAGO_EFECTIVO]
        pcs_digital = totales[dominio.ORIGEN_ALQUILER_PCS][dominio.PAGO_DIGITAL]
        ventas_efectivo = kiosko_efectivo + pcs_efectivo
        ventas_digital = kiosko_digital + pcs_digital
        monto_a_retirar = ventas_efectivo

        # "fecha" guarda el día en que ARRANCÓ el turno (el mismo criterio
        # que "turno", justo arriba) y no el día en que se lo cerró: para
        # un turno Noche cerrado ya pasada la medianoche, esos dos días son
        # distintos, y turnos_faltantes() necesita que coincida con el día
        # que arma turnos_del_mes_actual() para poder cruzarlos.
        fecha_turno = inicio_del_turno.date()

        cursor = conexion.execute(
            """
            INSERT INTO cierres_turno
                (fecha, turno, usuario_id, fecha_cierre, fondo_cambio,
                 ventas_efectivo, ventas_digital, monto_a_retirar,
                 kiosko_efectivo, kiosko_digital, pcs_efectivo, pcs_digital)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fecha_turno.isoformat(),
                turno,
                usuario_id,
                ahora,
                fondo_cambio,
                ventas_efectivo,
                ventas_digital,
                monto_a_retirar,
                kiosko_efectivo,
                kiosko_digital,
                pcs_efectivo,
                pcs_digital,
            ),
        )
        cierre_id = cursor.lastrowid

    return {
        "id": cierre_id,
        "turno": turno,
        "turno_label": etiqueta_turno(fecha_turno, turno),
        "fondo_cambio": fondo_cambio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_digital": ventas_digital,
        "kiosko_efectivo": kiosko_efectivo,
        "kiosko_digital": kiosko_digital,
        "pcs_efectivo": pcs_efectivo,
        "pcs_digital": pcs_digital,
        "monto_a_retirar": monto_a_retirar,
    }


# Estados de un turno en el reporte del día (resumen_del_dia). Son un
# rótulo de la pantalla, no algo que se guarde en la base: por eso viven
# acá y no en dominio.py.
ESTADO_CERRADO = "CERRADO"
ESTADO_EN_CURSO = "EN_CURSO"
ESTADO_SIN_CERRAR = "SIN_CERRAR"
ESTADO_PENDIENTE = "PENDIENTE"

_CAMPOS_PLATA = ("kiosko_efectivo", "kiosko_digital", "pcs_efectivo", "pcs_digital")


def _contar_ventas_entre(conexion, desde: str, hasta: str):
    """(confirmadas, anuladas) que cayeron en la ventana (desde, hasta] --
    mismo rango que `_sumar_ventas_por_origen_y_metodo`."""
    fila = conexion.execute(
        """
        SELECT COALESCE(SUM(estado = ?), 0) AS confirmadas,
               COALESCE(SUM(estado = ?), 0) AS anuladas
        FROM ventas
        WHERE fecha > ? AND fecha <= ?
        """,
        (dominio.VENTA_CONFIRMADA, dominio.VENTA_ANULADA, desde, hasta),
    ).fetchone()
    return fila["confirmadas"], fila["anuladas"]


def resumen_del_dia(dia):
    """
    El reporte de UN día calendario, abierto por turno (Mañana/Tarde/Noche,
    o Domingo T1/T2): qué se vendió en cada uno, quién lo cerró y cuánto
    faltó o sobró al contar el sobre.

    Un turno pertenece al día en que ARRANCÓ (mismo criterio que
    `cierres_turno.fecha`, ver cerrar_turno): la Noche del lunes incluye lo
    vendido hasta las 06:00 del martes. Y la plata de cada turno es la de
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

    Devuelve {"fecha", "turnos": [...], "total": {...}} con el total del
    día sumando los turnos.
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
        for cierre in cierres:
            anterior = conexion.execute(
                "SELECT fecha_cierre FROM cierres_turno WHERE id < ? ORDER BY id DESC LIMIT 1",
                (cierre["id"],),
            ).fetchone()
            desde = anterior["fecha_cierre"] if anterior else "0000-01-01T00:00:00"
            confirmadas, anuladas = _contar_ventas_entre(conexion, desde, cierre["fecha_cierre"])
            cierres_por_turno.setdefault(cierre["turno"], []).append((cierre, confirmadas, anuladas))

        # La ventana que está abierta ahora, si pertenece a este día.
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        desde_abierta, turno_abierto, inicio_abierto = _desde_y_turno_en_curso(ultimo_cierre, ahora_dt)
        abierta = None
        if inicio_abierto.date() == dia:
            ahora = ahora_dt.isoformat(timespec="microseconds")
            totales = _sumar_ventas_por_origen_y_metodo(conexion, desde_abierta, ahora)
            confirmadas, anuladas = _contar_ventas_entre(conexion, desde_abierta, ahora)
            abierta = {
                "turno": turno_abierto, "confirmadas": confirmadas, "anuladas": anuladas,
                "kiosko_efectivo": totales[dominio.ORIGEN_KIOSKO][dominio.PAGO_EFECTIVO],
                "kiosko_digital": totales[dominio.ORIGEN_KIOSKO][dominio.PAGO_DIGITAL],
                "pcs_efectivo": totales[dominio.ORIGEN_ALQUILER_PCS][dominio.PAGO_EFECTIVO],
                "pcs_digital": totales[dominio.ORIGEN_ALQUILER_PCS][dominio.PAGO_DIGITAL],
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

        resultado.append({
            "turno": turno,
            "etiqueta": etiqueta_turno(dia, turno),
            "estado": estado,
            "responsables": list(dict.fromkeys(c["empleada"] for c, _, _ in grupo)),
            "cerrado_a": grupo[-1][0]["fecha_cierre"] if grupo and parcial is None else None,
            "cantidad_ventas": sum(g[1] for g in grupo) + (parcial["confirmadas"] if parcial else 0),
            "cantidad_anuladas": sum(g[2] for g in grupo) + (parcial["anuladas"] if parcial else 0),
            **plata,
            "kiosko": plata["kiosko_efectivo"] + plata["kiosko_digital"],
            "pcs": plata["pcs_efectivo"] + plata["pcs_digital"],
            "efectivo": plata["kiosko_efectivo"] + plata["pcs_efectivo"],
            "digital": plata["kiosko_digital"] + plata["pcs_digital"],
            "total": sum(plata.values()),
            "verificado": verificado,
            "diferencia": round(sum(c["diferencia"] for c, _, _ in grupo), 2) if verificado else None,
        })

    total = {
        clave: sum(fila[clave] for fila in resultado)
        for clave in ("kiosko", "pcs", "efectivo", "digital", "total", "cantidad_ventas", "cantidad_anuladas")
    }
    return {"fecha": dia, "turnos": resultado, "total": total}


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
        cierre = conexion.execute(
            "SELECT * FROM cierres_turno WHERE id = ?", (cierre_id,)
        ).fetchone()
        if cierre is None:
            raise ValueError("El cierre no existe.")

        anterior = conexion.execute(
            "SELECT fecha_cierre FROM cierres_turno WHERE id < ? ORDER BY id DESC LIMIT 1",
            (cierre_id,),
        ).fetchone()
        desde = anterior["fecha_cierre"] if anterior else "0000-01-01T00:00:00"

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
        cierre = conexion.execute(
            "SELECT * FROM cierres_turno WHERE id = ?", (cierre_id,)
        ).fetchone()
        if cierre is None:
            raise ValueError("El cierre no existe.")

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
    """
    Los turnos esperados del mes en curso, de día 1 a hoy — domingo
    tiene solo 2 (Mañana, Noche); el resto de los días tiene los 3 de
    siempre (ver turnos.calcular_turno). Todavía no dice cuáles ya
    tienen cierre cargado ni cuáles vencieron — eso lo hace
    turnos_faltantes().
    """
    hoy = datetime.now().date()
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


def turnos_faltantes():
    """
    De los turnos esperados del mes en curso (turnos_del_mes_actual), los
    que YA vencieron (ventana nominal + 40 min de gracia, ver
    turnos.turno_vencimiento) y todavía no tienen un cierre cargado en
    cierres_turno. Se usa en "Control de Cierres de Turno" para que el
    Admin se entere de un turno sin cerrar antes de que se pierda en el
    historial, en vez de notarlo recién a fin de mes. Cada resultado
    incluye "usuarios": quién vendió o se logueó durante esa ventana
    (ver _responsables_del_mes), para saber a quién preguntarle.
    """
    ahora = datetime.now()
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
    for slot in turnos_del_mes_actual():
        if (slot["fecha"].isoformat(), slot["turno"]) in cerrados:
            continue
        if turno_vencimiento(slot["fecha"], slot["turno"]) <= ahora:
            slot = dict(slot)
            slot["usuarios"] = sorted(responsables.get((slot["fecha"], slot["turno"]), ()))
            faltantes.append(slot)
    return faltantes
