"""
reportes_repo.py
==================
Consultas para la sección de Reportes: el Resumen (cuánta plata se
trabajó en un rango de fechas), el desglose Kiosko / Impresiones / Trámites
/ Alquiler de PCs / PlayStation 5 (por turno, día, semana o el rango completo) y el Ranking
de Ventas (qué se vende más, de cualquiera de los rubros del programa).
Son solo consultas SQL con agregación (SUM, GROUP BY), apoyadas en los
índices que se crean en database.py — por eso van a ser rápidas incluso
con años de ventas acumuladas.
"""

from datetime import date, timedelta

import dominio
from database import conexion_db

# Categorías del Ranking de Ventas -- son un rótulo de la pantalla, no un
# valor que se guarda en la base (por eso viven acá y no en dominio.py,
# que es para strings que sí viajan hasta una columna). Un artículo de
# kiosko sale de venta_detalle; los otros no tienen fila ahí (ver
# ventas_repo.registrar_venta_sin_detalle) y hay que ir a buscarlos a
# sesion_bonos / movimientos_saldo_miembro / tramites_venta para saber qué
# se vendió.
CATEGORIA_KIOSKO = "Kiosko"
CATEGORIA_BONO_PC = "Bono de PC (walk-in)"
CATEGORIA_BONO_SOCIO = "Bono de Socio"
CATEGORIA_CARGA_TARIFA_SOCIO = "Carga de saldo de Socio (tarifa por hora)"
CATEGORIA_TRAMITE = "Trámite"
CATEGORIA_BONO_PLAYSTATION = "Bono de PlayStation 5"


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
    """El texto que se muestra para una fila de resumen_por_origen, según
    cómo se agrupó (`clave` es el valor de _COLUMNA_AGRUPACION)."""
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


def _sumar_por_clave(conexion, consulta: str, parametros) -> dict:
    """{clave: total} de una consulta que devuelve las columnas `clave`
    (el período, ver _COLUMNA_AGRUPACION) y `total`."""
    return {fila["clave"]: fila["total"] or 0.0 for fila in conexion.execute(consulta, parametros)}


def resumen_por_origen(desde: str, hasta: str, agrupar_por: str = "rango"):
    """
    Desglosa lo facturado en Kiosko, Impresiones, Trámites, Alquiler de PCs y
    PlayStation 5 (ver dominio.ORIGENES_VENTA) entre dos fechas, agrupado según
    `agrupar_por`:
      - "rango" (default): una sola fila con el total del período completo.
      - "turno": una fila por turno (Mañana/Tarde/Noche), siempre las 3
        aunque alguno no tenga ventas en el rango -- mismo criterio que
        resumen_por_turno().
      - "dia": una fila por día calendario con al menos una venta.
      - "semana": una fila por semana (lunes a domingo) con al menos una
        venta.
    Cada fila trae "etiqueta" (ya lista para mostrar), "kiosko",
    "impresiones", "tramites", "pcs", "playstation" y "total" (= kiosko +
    impresiones + tramites + pcs + playstation). Usa `ventas.total` (no
    venta_pagos): acá no importa el medio de pago, solo de qué negocio vino
    cada peso.

    "impresiones" es lo vendido del artículo dominio.CODIGO_ARTICULO_IMPRESIONES
    (se saca de venta_detalle) y "tramites" lo cobrado por trámites (se saca
    de tramites_venta, ver tramites_repo). Los dos se cobran por el mostrador
    como cualquier venta de origen Kiosko, pero acá salen en columna propia:
    "kiosko" es el resto de las ventas de origen Kiosko, SIN ellos -- así las
    columnas suman el total y nada se cuenta dos veces.
    """
    columna_grupo = _COLUMNA_AGRUPACION[agrupar_por]
    rango = (dominio.VENTA_CONFIRMADA, desde, hasta)

    with conexion_db() as conexion:
        filas = conexion.execute(
            f"""
            SELECT {columna_grupo} AS clave, ventas.origen AS origen,
                   COALESCE(SUM(ventas.total), 0) AS total
            FROM ventas
            WHERE estado = ? AND date(fecha) BETWEEN date(?) AND date(?)
            GROUP BY clave, ventas.origen
            """,
            rango,
        ).fetchall()

        impresiones_por_clave = _sumar_por_clave(
            conexion,
            f"""
            SELECT {columna_grupo} AS clave, COALESCE(SUM(venta_detalle.subtotal), 0) AS total
            FROM venta_detalle
            JOIN ventas ON ventas.id = venta_detalle.venta_id
            WHERE venta_detalle.articulo_codigo = ?
              AND ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY clave
            """,
            (dominio.CODIGO_ARTICULO_IMPRESIONES, *rango),
        )

        tramites_por_clave = _sumar_por_clave(
            conexion,
            f"""
            SELECT {columna_grupo} AS clave, COALESCE(SUM(ventas.total), 0) AS total
            FROM tramites_venta
            JOIN ventas ON ventas.id = tramites_venta.venta_id
            WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
            GROUP BY clave
            """,
            rango,
        )

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
        impresiones = round(impresiones_por_clave.get(clave, 0.0), 2)
        tramites = round(tramites_por_clave.get(clave, 0.0), 2)
        kiosko = round(totales[dominio.ORIGEN_KIOSKO] - impresiones - tramites, 2)
        pcs = totales[dominio.ORIGEN_ALQUILER_PCS]
        playstation = totales[dominio.ORIGEN_PLAYSTATION]
        resultado.append({
            "etiqueta": _etiqueta_agrupacion(clave, agrupar_por),
            "kiosko": kiosko,
            "impresiones": impresiones,
            "tramites": tramites,
            "pcs": pcs,
            "playstation": playstation,
            "total": kiosko + impresiones + tramites + pcs + playstation,
        })
    return resultado


def ranking_ventas(desde: str, hasta: str, ordenar_por: str = "cantidad"):
    """
    Ranking de TODO lo que se vendió entre dos fechas -- artículos de
    kiosko, bonos de tiempo de walk-ins, bonos de socios, cargas de saldo
    por tarifa, trámites y bonos de la PlayStation 5 -- con la cantidad
    total vendida y el importe total facturado de cada uno. `ordenar_por`
    puede ser "cantidad" o "monto".

    Un artículo de kiosko deja su fila en venta_detalle, pero un bono, una
    carga de saldo o un trámite se registran sin detalle (ver
    ventas_repo.registrar_venta_sin_detalle): para saber QUÉ se vendió
    hay que ir a sesion_bonos (bono de PC), movimientos_saldo_miembro
    (bono de socio o carga por tarifa, distinguidos por si el movimiento
    de tipo 'CARGA' trae bono_id o no -- ver
    miembros_repo.cargar_saldo_por_monto/_por_bono), tramites_venta
    (trámite, agrupado por el nombre que tenía al cobrarse) o
    sesion_playstation_bonos (bono de la consola). Las seis fuentes se
    traen con UNION ALL y se ordenan juntas al final, para que el dueño
    vea en un solo ranking qué es lo que más funciona de cualquiera de los
    rubros.
    """
    columna_orden = "cantidad" if ordenar_por == "cantidad" else "importe"
    rango = (dominio.VENTA_CONFIRMADA, desde, hasta)

    with conexion_db() as conexion:
        return conexion.execute(
            f"""
            SELECT categoria, codigo, descripcion, cantidad, importe FROM (
                SELECT
                    ? AS categoria,
                    venta_detalle.articulo_codigo AS codigo,
                    venta_detalle.descripcion AS descripcion,
                    SUM(venta_detalle.cantidad) AS cantidad,
                    SUM(venta_detalle.subtotal) AS importe
                FROM venta_detalle
                JOIN ventas ON ventas.id = venta_detalle.venta_id
                WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
                GROUP BY venta_detalle.articulo_codigo, venta_detalle.descripcion

                UNION ALL

                SELECT
                    ? AS categoria,
                    '' AS codigo,
                    bonos_tiempo.nombre AS descripcion,
                    COUNT(*) AS cantidad,
                    SUM(sesion_bonos.precio) AS importe
                FROM sesion_bonos
                JOIN bonos_tiempo ON bonos_tiempo.id = sesion_bonos.bono_id
                JOIN ventas ON ventas.id = sesion_bonos.venta_id
                WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
                GROUP BY bonos_tiempo.id, bonos_tiempo.nombre

                UNION ALL

                SELECT
                    ? AS categoria,
                    '' AS codigo,
                    bonos_miembro.nombre AS descripcion,
                    COUNT(*) AS cantidad,
                    SUM(ventas.total) AS importe
                FROM movimientos_saldo_miembro
                JOIN bonos_miembro ON bonos_miembro.id = movimientos_saldo_miembro.bono_id
                JOIN ventas ON ventas.id = movimientos_saldo_miembro.venta_id
                WHERE movimientos_saldo_miembro.tipo = ?
                  AND ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
                GROUP BY bonos_miembro.id, bonos_miembro.nombre

                UNION ALL

                SELECT
                    ? AS categoria,
                    '' AS codigo,
                    ? AS descripcion,
                    COUNT(*) AS cantidad,
                    SUM(ventas.total) AS importe
                FROM movimientos_saldo_miembro
                JOIN ventas ON ventas.id = movimientos_saldo_miembro.venta_id
                WHERE movimientos_saldo_miembro.tipo = ?
                  AND movimientos_saldo_miembro.bono_id IS NULL
                  AND ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
                HAVING COUNT(*) > 0

                UNION ALL

                SELECT
                    ? AS categoria,
                    '' AS codigo,
                    tramites_venta.descripcion AS descripcion,
                    COUNT(*) AS cantidad,
                    SUM(ventas.total) AS importe
                FROM tramites_venta
                JOIN ventas ON ventas.id = tramites_venta.venta_id
                WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
                GROUP BY tramites_venta.tramite_id, tramites_venta.descripcion

                UNION ALL

                SELECT
                    ? AS categoria,
                    '' AS codigo,
                    bonos_playstation.nombre AS descripcion,
                    COUNT(*) AS cantidad,
                    SUM(sesion_playstation_bonos.precio) AS importe
                FROM sesion_playstation_bonos
                JOIN bonos_playstation ON bonos_playstation.id = sesion_playstation_bonos.bono_id
                JOIN ventas ON ventas.id = sesion_playstation_bonos.venta_id
                WHERE ventas.estado = ? AND date(ventas.fecha) BETWEEN date(?) AND date(?)
                GROUP BY bonos_playstation.id, bonos_playstation.nombre
            )
            ORDER BY {columna_orden} DESC
            """,
            (
                CATEGORIA_KIOSKO, *rango,
                CATEGORIA_BONO_PC, *rango,
                CATEGORIA_BONO_SOCIO, dominio.MOVIMIENTO_CARGA, *rango,
                CATEGORIA_CARGA_TARIFA_SOCIO, CATEGORIA_CARGA_TARIFA_SOCIO,
                dominio.MOVIMIENTO_CARGA, *rango,
                CATEGORIA_TRAMITE, *rango,
                CATEGORIA_BONO_PLAYSTATION, *rango,
            ),
        ).fetchall()
