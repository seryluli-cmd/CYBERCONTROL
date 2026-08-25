"""
reportes_repo.py
==================
Consultas para la sección de Reportes: el Resumen (cuánta plata se
trabajó en un rango de fechas) y el Ranking de Ventas por artículo
(qué se vende más). Son solo dos consultas SQL con agregación (SUM,
GROUP BY), apoyadas en los índices que se crean en database.py — por
eso van a ser rápidas incluso con años de ventas acumuladas.
"""

from database import conexion_db


def resumen_ventas(desde: str, hasta: str):
    """
    Totales de ventas confirmadas entre dos fechas (incluidas ambas
    puntas), separados por medio de pago. `desde` y `hasta` son fechas
    en formato "YYYY-MM-DD".
    """
    with conexion_db() as conexion:
        total_general = conexion.execute(
            """
            SELECT COALESCE(SUM(total), 0) AS total, COUNT(*) AS cantidad_ventas
            FROM ventas
            WHERE estado = 'CONFIRMADA' AND date(fecha) BETWEEN date(?) AND date(?)
            """,
            (desde, hasta),
        ).fetchone()

        por_metodo = conexion.execute(
            """
            SELECT venta_pagos.metodo, SUM(venta_pagos.monto) AS total
            FROM venta_pagos
            JOIN ventas ON ventas.id = venta_pagos.venta_id
            WHERE ventas.estado = 'CONFIRMADA' AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY venta_pagos.metodo
            """,
            (desde, hasta),
        ).fetchall()

    totales_por_metodo = {"EFECTIVO": 0.0, "DIGITAL": 0.0}
    for fila in por_metodo:
        totales_por_metodo[fila["metodo"]] = fila["total"] or 0.0

    return {
        "total": total_general["total"],
        "cantidad_ventas": total_general["cantidad_ventas"],
        "efectivo": totales_por_metodo["EFECTIVO"],
        "digital": totales_por_metodo["DIGITAL"],
    }


def ranking_ventas(desde: str, hasta: str, ordenar_por: str = "cantidad"):
    """
    Ranking de artículos vendidos entre dos fechas, con la cantidad total
    vendida y el importe total facturado de cada uno. `ordenar_por` puede
    ser "cantidad" o "monto" (equivalente a las dos variantes que tenía
    el sistema viejo: "por cantidad" y "por monto").
    """
    columna_orden = "cantidad" if ordenar_por == "cantidad" else "importe"

    with conexion_db() as conexion:
        return conexion.execute(
            f"""
            SELECT
                venta_detalle.articulo_codigo AS codigo,
                venta_detalle.descripcion,
                SUM(venta_detalle.cantidad) AS cantidad,
                SUM(venta_detalle.subtotal) AS importe
            FROM venta_detalle
            JOIN ventas ON ventas.id = venta_detalle.venta_id
            WHERE ventas.estado = 'CONFIRMADA' AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY venta_detalle.articulo_codigo, venta_detalle.descripcion
            ORDER BY {columna_orden} DESC
            """,
            (desde, hasta),
        ).fetchall()
