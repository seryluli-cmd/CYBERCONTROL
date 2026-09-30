"""
reportes_repo.py
==================
Consultas para la sección de Reportes: el Resumen (cuánta plata se
trabajó en un rango de fechas), el desglose Kiosko vs. Alquiler de PCs
(por turno, día, semana o el rango completo) y el Ranking de Ventas por
artículo (qué se vende más). Son solo consultas SQL con agregación (SUM,
GROUP BY), apoyadas en los índices que se crean en database.py — por
eso van a ser rápidas incluso con años de ventas acumuladas.
"""

from datetime import date, timedelta

import dominio
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
            WHERE estado = ? AND date(fecha) BETWEEN date(?) AND date(?)
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchone()

        por_metodo = conexion.execute(
            """
            SELECT venta_pagos.metodo, SUM(venta_pagos.monto) AS total
            FROM venta_pagos
            JOIN ventas ON ventas.id = venta_pagos.venta_id
            WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY venta_pagos.metodo
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchall()

    totales_por_metodo = {metodo: 0.0 for metodo in dominio.METODOS_PAGO}
    for fila in por_metodo:
        totales_por_metodo[fila["metodo"]] = fila["total"] or 0.0

    return {
        "total": total_general["total"],
        "cantidad_ventas": total_general["cantidad_ventas"],
        "efectivo": totales_por_metodo[dominio.PAGO_EFECTIVO],
        "digital": totales_por_metodo[dominio.PAGO_DIGITAL],
    }


def resumen_por_turno(desde: str, hasta: str):
    """
    Lo mismo que resumen_ventas(), pero desglosado por turno (Mañana/
    Tarde/Noche) en vez de un único total — para responder "¿cuánto
    trabajó la Tarde esta semana?" sin tener que sumar a mano los
    cierres cargados en Control de Cierres de Turno. Devuelve siempre
    los 3 turnos, en orden, aunque alguno no tenga ventas en el rango
    (por ejemplo, si el rango son puros domingos, Tarde da $0 — ver
    turnos.calcular_turno, que ese día no genera ventas con turno
    "TARDE").
    """
    with conexion_db() as conexion:
        por_turno = conexion.execute(
            """
            SELECT turno, COALESCE(SUM(total), 0) AS total, COUNT(*) AS cantidad_ventas
            FROM ventas
            WHERE estado = ? AND date(fecha) BETWEEN date(?) AND date(?)
            GROUP BY turno
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchall()

        pagos_por_turno = conexion.execute(
            """
            SELECT ventas.turno, venta_pagos.metodo, SUM(venta_pagos.monto) AS total
            FROM venta_pagos
            JOIN ventas ON ventas.id = venta_pagos.venta_id
            WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY ventas.turno, venta_pagos.metodo
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchall()

    totales = {turno: {"total": 0.0, "cantidad_ventas": 0, "efectivo": 0.0, "digital": 0.0}
               for turno in dominio.TURNOS}
    for fila in por_turno:
        totales[fila["turno"]]["total"] = fila["total"]
        totales[fila["turno"]]["cantidad_ventas"] = fila["cantidad_ventas"]
    for fila in pagos_por_turno:
        clave = "efectivo" if fila["metodo"] == dominio.PAGO_EFECTIVO else "digital"
        totales[fila["turno"]][clave] = fila["total"] or 0.0

    return [{"turno": turno, **datos} for turno, datos in totales.items()]


_COLUMNA_AGRUPACION = {
    "turno": "ventas.turno",
    "dia": "date(ventas.fecha)",
    # 'weekday 0' avanza a el próximo domingo (0 = domingo) y '-6 days'
    # retrocede al lunes de esa misma semana -- modismo estándar de
    # SQLite para "lunes de la semana que contiene esta fecha".
    "semana": "date(ventas.fecha, 'weekday 0', '-6 days')",
    "rango": "1",
}


def _etiqueta_agrupacion(clave, agrupar_por: str) -> str:
    if agrupar_por == "turno":
        return clave.capitalize()
    if agrupar_por == "rango":
        return "Total del período"
    fecha = date.fromisoformat(clave)
    if agrupar_por == "dia":
        return fecha.strftime("%d/%m/%Y")
    # "semana": la columna de agrupación ya devuelve el lunes de esa semana.
    fin_semana = fecha + timedelta(days=6)
    return f"Semana del {fecha.strftime('%d/%m')} al {fin_semana.strftime('%d/%m/%Y')}"


def resumen_por_origen(desde: str, hasta: str, agrupar_por: str = "rango"):
    """
    Desglosa lo facturado en Kiosko vs. Alquiler de PCs (ver
    dominio.ORIGENES_VENTA) entre dos fechas, agrupado según
    `agrupar_por`:
      - "rango" (default): una sola fila con el total del período completo.
      - "turno": una fila por turno (Mañana/Tarde/Noche), siempre las 3
        aunque alguno no tenga ventas en el rango -- mismo criterio que
        resumen_por_turno().
      - "dia": una fila por día calendario con al menos una venta.
      - "semana": una fila por semana (lunes a domingo) con al menos una
        venta.
    Cada fila trae "etiqueta" (ya lista para mostrar), "kiosko", "pcs" y
    "total" (= kiosko + pcs). Usa `ventas.total` (no venta_pagos): acá
    no importa el medio de pago, solo de qué negocio vino cada peso.
    """
    columna_grupo = _COLUMNA_AGRUPACION[agrupar_por]

    with conexion_db() as conexion:
        filas = conexion.execute(
            f"""
            SELECT {columna_grupo} AS clave, ventas.origen AS origen,
                   COALESCE(SUM(ventas.total), 0) AS total
            FROM ventas
            WHERE estado = ? AND date(fecha) BETWEEN date(?) AND date(?)
            GROUP BY clave, ventas.origen
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchall()

    totales_por_clave = {}
    for fila in filas:
        totales = totales_por_clave.setdefault(
            fila["clave"], {origen: 0.0 for origen in dominio.ORIGENES_VENTA}
        )
        totales[fila["origen"]] = fila["total"] or 0.0

    if agrupar_por == "turno":
        claves = list(dominio.TURNOS)
    elif agrupar_por == "rango":
        claves = [1]
    else:
        claves = sorted(totales_por_clave.keys())
    for clave in claves:
        totales_por_clave.setdefault(clave, {origen: 0.0 for origen in dominio.ORIGENES_VENTA})

    resultado = []
    for clave in claves:
        totales = totales_por_clave[clave]
        kiosko = totales[dominio.ORIGEN_KIOSKO]
        pcs = totales[dominio.ORIGEN_ALQUILER_PCS]
        resultado.append({
            "etiqueta": _etiqueta_agrupacion(clave, agrupar_por),
            "kiosko": kiosko,
            "pcs": pcs,
            "total": kiosko + pcs,
        })
    return resultado


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
            WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY venta_detalle.articulo_codigo, venta_detalle.descripcion
            ORDER BY {columna_orden} DESC
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchall()
