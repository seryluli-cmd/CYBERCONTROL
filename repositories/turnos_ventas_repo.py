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


def _vendido_aparte_entre(conexion, desde: str, hasta: str, cierre_grabado: bool = False) -> dict:
    """
    {"impresiones": ..., "tramites": ...}: cuánta plata se vendió de cada una
    en la ventana (desde, hasta] -- mismo rango que
    `_sumar_ventas_por_origen_y_metodo`. Las impresiones son el artículo
    dominio.CODIGO_ARTICULO_IMPRESIONES (de venta_detalle); los trámites
    salen de tramites_venta. Las dos cosas ya están sumadas dentro de lo
    cobrado como Kiosko (resumen_del_dia las muestra aparte), no son un
    monto extra.

    Solo cuentan las ventas confirmadas, salvo con `cierre_grabado=True`
    (la ventana de un cierre que YA se guardó, `hasta` = su fecha_cierre):
    la plata de ese cierre es una foto de lo que estaba confirmado al
    cerrar, así que una venta anulada DESPUÉS del cierre sigue sumada en el
    importe de Kiosko que quedó guardado y acá se la sigue contando. Si no,
    esos pesos dejarían de figurar como impresiones/trámites y pasarían a
    verse como Kiosko. (`julianday` y no una comparación de texto porque
    `anulada_fecha` se graba con segundos y `fecha_cierre` con microsegundos.)
    """
    if cierre_grabado:
        vigente = "(ventas.estado = ? OR (ventas.estado = ? AND julianday(ventas.anulada_fecha) > julianday(?)))"
        parametros_vigente = (dominio.VENTA_CONFIRMADA, dominio.VENTA_ANULADA, hasta)
    else:
        vigente = "ventas.estado = ?"
        parametros_vigente = (dominio.VENTA_CONFIRMADA,)

    # `vigente` es un texto fijo de arriba (nunca un dato de la usuaria),
    # por eso es seguro armarlo dentro del SQL.
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
