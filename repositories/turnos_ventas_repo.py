"""
turnos_ventas_repo.py
======================
Qué se vendió en una ventana de tiempo (desde, hasta]: lo cobrado por origen y
método de pago, cuántas ventas se confirmaron y anularon, y cuánto de Kiosko
fue impresiones y trámites. Son las consultas con que turnos_repo arma Caja,
Cierre de Turno, Control de Cierres y el Resumen del Día; se separaron de ahí
el 2026-10-17, cuando turnos_repo.py pasó las 600 líneas (regla 12 de
CLAUDE.md). turnos_repo las sigue ofreciendo con los mismos nombres.

Ninguna mira la hora: reciben la ventana ya armada. Las fechas se comparan
como texto ISO, igual que en turnos_repo.
"""

import dominio


def _sumar_ventas_por_origen_y_metodo(conexion, desde: str, hasta: str):
    """
    Suma lo cobrado en la ventana (desde, hasta], separado por origen (ver
    dominio.ORIGENES_VENTA) y por método de pago: es lo que le permite al
    dueño ver, en Caja y en Cierre de Turno, cuánto entró por productos de
    kiosko contra cuánto por alquiler de PCs, en vez de un solo total
    mezclado. Devuelve {origen: {metodo: total}}, considerando solo ventas
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


# Lo que se cobra por el mostrador como cualquier venta de Kiosko pero que el
# reporte "Resumen del Día" muestra en una columna propia (ver
# _vendido_aparte_entre): las impresiones (un artículo) y los trámites (un
# servicio, ver tramites_repo).
_LINEAS_APARTE = ("impresiones", "tramites")


def _condicion_vigente(hasta: str, cierre_grabado: bool) -> tuple:
    """
    (sql, parámetros) que dicen qué ventas cuentan como cobradas en una ventana
    que termina en `hasta`. Normalmente solo las confirmadas; con
    `cierre_grabado=True` (la ventana de un cierre que YA se guardó, `hasta` =
    su fecha_cierre) también las anuladas DESPUÉS de ese cierre: la plata del
    cierre es una foto de lo que estaba confirmado al cerrar, así que esa venta
    sigue sumada en el Kiosko que quedó guardado. Si no se la contara acá, esos
    pesos dejarían de figurar como impresiones/trámites y pasarían a verse como
    Kiosko. (`julianday` y no una comparación de texto porque `anulada_fecha`
    se graba con segundos y `fecha_cierre` con microsegundos.)

    El sql es texto fijo (nunca un dato de la usuaria): es seguro armarlo
    dentro de una consulta.
    """
    if cierre_grabado:
        return (
            "(ventas.estado = ? OR (ventas.estado = ? AND julianday(ventas.anulada_fecha) > julianday(?)))",
            (dominio.VENTA_CONFIRMADA, dominio.VENTA_ANULADA, hasta),
        )
    return "ventas.estado = ?", (dominio.VENTA_CONFIRMADA,)


def _vendido_aparte_entre(conexion, desde: str, hasta: str, cierre_grabado: bool = False) -> dict:
    """
    {"impresiones": ..., "tramites": ...}: cuánta plata se vendió de cada una
    en la ventana (desde, hasta] -- mismo rango que
    `_sumar_ventas_por_origen_y_metodo`. Las impresiones son el artículo
    dominio.CODIGO_ARTICULO_IMPRESIONES (de venta_detalle); los trámites
    salen de tramites_venta. Las dos cosas ya están sumadas dentro de lo
    cobrado como Kiosko (resumen_del_dia las muestra aparte), no son un
    monto extra.

    Solo cuentan las ventas confirmadas, salvo con `cierre_grabado=True`: ver
    _condicion_vigente.
    """
    vigente, parametros_vigente = _condicion_vigente(hasta, cierre_grabado)
    impresiones = conexion.execute(
        f"""
        SELECT COALESCE(SUM(venta_detalle.subtotal), 0) AS total
        FROM venta_detalle
        JOIN ventas ON ventas.id = venta_detalle.venta_id
        WHERE venta_detalle.articulo_codigo = ?
          AND {vigente}
          AND ventas.fecha > ?
          AND ventas.fecha <= ?
        """,
        (dominio.CODIGO_ARTICULO_IMPRESIONES, *parametros_vigente, desde, hasta),
    ).fetchone()["total"]
    tramites = conexion.execute(
        f"""
        SELECT COALESCE(SUM(ventas.total), 0) AS total
        FROM tramites_venta
        JOIN ventas ON ventas.id = tramites_venta.venta_id
        WHERE {vigente}
          AND ventas.fecha > ?
          AND ventas.fecha <= ?
        """,
        (*parametros_vigente, desde, hasta),
    ).fetchone()["total"]
    return {"impresiones": impresiones, "tramites": tramites}


def _aparte_por_metodo(conexion, desde: str, hasta: str, cierre_grabado: bool = False) -> dict:
    """
    {"impresiones": {metodo: monto}, "tramites": {metodo: monto}}: lo mismo que
    `_vendido_aparte_entre` (ventas confirmadas de la ventana), pero repartido
    entre efectivo y digital, para que Caja y Cierre de Turno muestren Kiosko,
    Impresiones y Trámites cada uno con su "ef. + dig." (pedido del dueño,
    2026-10-19: eligió ver Kiosko sin impresiones). Con `cierre_grabado=True`
    es la ventana de un cierre ya guardado (ver _condicion_vigente): lo usa el
    detalle de un cierre en Control de Cierres.

    El reparto se hace venta por venta con los pagos de ESA venta: un trámite o
    unas impresiones cobradas solas (el botón Impresiones) quedan exactas; si las
    impresiones iban en un carrito con otras cosas y se pagó una parte en cada
    medio, se reparten en la misma proporción que se pagó. Las dos partes de una
    venta suman siempre su importe de impresiones/trámite, así que Kiosko menos
    esto da justo lo demás: el efectivo del cajón no se toca.
    """
    vigente, parametros_vigente = _condicion_vigente(hasta, cierre_grabado)
    filas = conexion.execute(
        f"""
        SELECT
            (SELECT COALESCE(SUM(venta_detalle.subtotal), 0) FROM venta_detalle
              WHERE venta_detalle.venta_id = ventas.id
                AND venta_detalle.articulo_codigo = ?) AS impresiones,
            CASE WHEN EXISTS (SELECT 1 FROM tramites_venta WHERE tramites_venta.venta_id = ventas.id)
                 THEN ventas.total ELSE 0 END AS tramites,
            (SELECT COALESCE(SUM(venta_pagos.monto), 0) FROM venta_pagos
              WHERE venta_pagos.venta_id = ventas.id AND venta_pagos.metodo = ?) AS efectivo,
            (SELECT COALESCE(SUM(venta_pagos.monto), 0) FROM venta_pagos
              WHERE venta_pagos.venta_id = ventas.id AND venta_pagos.metodo = ?) AS digital
        FROM ventas
        WHERE {vigente}
          AND ventas.origen = ?
          AND ventas.fecha > ?
          AND ventas.fecha <= ?
          AND (EXISTS (SELECT 1 FROM venta_detalle
                        WHERE venta_detalle.venta_id = ventas.id AND venta_detalle.articulo_codigo = ?)
               OR EXISTS (SELECT 1 FROM tramites_venta WHERE tramites_venta.venta_id = ventas.id))
        """,
        (dominio.CODIGO_ARTICULO_IMPRESIONES, dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL,
         *parametros_vigente, dominio.ORIGEN_KIOSKO, desde, hasta, dominio.CODIGO_ARTICULO_IMPRESIONES),
    ).fetchall()

    sumas = {linea: {metodo: 0.0 for metodo in dominio.METODOS_PAGO} for linea in _LINEAS_APARTE}
    for fila in filas:
        pagado = fila["efectivo"] + fila["digital"]
        if pagado <= 0:
            continue  # sin pagos tampoco sumó nada en Kiosko: no hay qué restarle
        for linea in _LINEAS_APARTE:
            monto = fila[linea]
            if not monto:
                continue
            parte_efectivo = monto * fila["efectivo"] / pagado
            sumas[linea][dominio.PAGO_EFECTIVO] += parte_efectivo
            sumas[linea][dominio.PAGO_DIGITAL] += monto - parte_efectivo
    return sumas


def _separar_de_kiosko(desglose: dict, por_metodo: dict) -> dict:
    """
    Las claves de turnos_repo.resumen_turno_actual que separan Impresiones y
    Trámites de Kiosko (ver ahí), a partir del desglose del turno (o de un
    cierre ya guardado: alcanza con que traiga kiosko_efectivo/kiosko_digital)
    y de _aparte_por_metodo. Se redondea cada parte una sola vez y Kiosko sale
    por resta, así los tres renglones suman exactamente lo que dice Kiosko en el
    cierre, al centavo.
    """
    resultado = {}
    resto = {"efectivo": desglose["kiosko_efectivo"], "digital": desglose["kiosko_digital"]}
    for linea in _LINEAS_APARTE:
        total = round(por_metodo[linea][dominio.PAGO_EFECTIVO] + por_metodo[linea][dominio.PAGO_DIGITAL], 2)
        efectivo = round(por_metodo[linea][dominio.PAGO_EFECTIVO], 2)
        digital = round(total - efectivo, 2)
        resultado[linea] = total
        resultado[f"{linea}_efectivo"] = efectivo
        resultado[f"{linea}_digital"] = digital
        resto["efectivo"] -= efectivo
        resto["digital"] -= digital
    resultado["kiosko_solo_efectivo"] = round(resto["efectivo"], 2)
    resultado["kiosko_solo_digital"] = round(resto["digital"], 2)
    return resultado
