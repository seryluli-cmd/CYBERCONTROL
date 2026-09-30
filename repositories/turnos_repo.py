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
