"""
socios_bonos_repo.py
====================
Reportes > "PCs: Socios y Bonos" (pedido del dueño, 2026-10-24): lo que dejaron
las PCs, separado en cargas de saldo a socios y bonos vendidos en el mostrador,
y comparado.

- Socios: las cargas de saldo (movimientos CARGA, con bono de socio o por
  monto), con su plata, cuántas y cuánto tiempo.
- Bonos: todo lo demás de "Alquiler de PCs": los bonos de walk-ins, los de
  PCSTREAM y lo cobrado por reservas de PCs. Su plata sale por resta (Alquiler
  de PCs menos las cargas), así las dos partes suman justo lo que muestran
  Caja, Cierre de Turno y Reportes > Totales. La cantidad y el tiempo salen de
  los bonos puestos en una sesión (sesion_bonos y sesion_pcstream_bonos): una
  reserva cuenta una vez, cuando se cobró su primer pago, y una que no vino no
  suma tiempo (su plata sí).

Solo ventas confirmadas, en días del local (06:00 a 06:00), agrupadas como
Reportes > Totales (reportes_repo._COLUMNA_AGRUPACION).
"""

import dominio
from database import conexion_db
from repositories import reportes_repo
from turnos import limites_de_los_dias


def _parte(plata=0.0, cantidad=0, minutos=0) -> dict:
    return {"plata": round(plata or 0.0, 2), "cantidad": cantidad or 0, "minutos": minutos or 0}


def _comparacion(etiqueta: str, socios: dict, bonos: dict) -> dict:
    total = round(socios["plata"] + bonos["plata"], 2)
    for parte in (socios, bonos):
        parte["porcentaje"] = round(parte["plata"] * 100 / total, 1) if total else 0.0
        # Cuánto deja cada hora vendida (None si no se vendió tiempo).
        parte["por_hora"] = round(parte["plata"] * 60 / parte["minutos"], 2) if parte["minutos"] else None
    return {"etiqueta": etiqueta, "socios": socios, "bonos": bonos, "total": total}


def comparar(desde: str, hasta: str, agrupar_por: str = "rango") -> dict:
    """
    {"filas": [...], "total": {...}} entre dos fechas ("YYYY-MM-DD", incluidas
    las dos). `agrupar_por` como reportes_repo.resumen_por_origen: "rango" (una
    sola fila), "turno", "dia" o "semana". Cada fila y el total traen
    "etiqueta", "total" (lo que dejaron las PCs) y "socios" / "bonos", cada uno
    con "plata", "cantidad", "minutos", "porcentaje" (de la plata) y "por_hora"
    (plata por hora vendida, o None).
    """
    columna_grupo = reportes_repo._COLUMNA_AGRUPACION[agrupar_por]
    rango = (dominio.VENTA_CONFIRMADA, *limites_de_los_dias(desde, hasta))
    with conexion_db() as conexion:
        pcs = {fila["clave"]: fila["plata"] for fila in conexion.execute(
            f"""
            SELECT {columna_grupo} AS clave, SUM(ventas.total) AS plata
            FROM ventas
            WHERE ventas.origen = ? AND ventas.estado = ? AND ventas.fecha >= ? AND ventas.fecha < ?
            GROUP BY clave
            """,
            (dominio.ORIGEN_ALQUILER_PCS, *rango),
        )}
        socios = {fila["clave"]: fila for fila in conexion.execute(
            f"""
            SELECT {columna_grupo} AS clave, SUM(ventas.total) AS plata, COUNT(*) AS cantidad,
                   SUM(m.minutos) AS minutos
            FROM movimientos_saldo_miembro m
            JOIN ventas ON ventas.id = m.venta_id
            WHERE m.tipo = ? AND ventas.estado = ? AND ventas.fecha >= ? AND ventas.fecha < ?
            GROUP BY clave
            """,
            (dominio.MOVIMIENTO_CARGA, *rango),
        )}
        bonos = {fila["clave"]: fila for fila in conexion.execute(
            f"""
            SELECT {columna_grupo} AS clave, COUNT(*) AS cantidad, SUM(b.minutos) AS minutos
            FROM (SELECT venta_id, minutos FROM sesion_bonos
                  UNION ALL
                  SELECT venta_id, minutos FROM sesion_pcstream_bonos) b
            JOIN ventas ON ventas.id = b.venta_id
            WHERE ventas.origen = ? AND ventas.estado = ? AND ventas.fecha >= ? AND ventas.fecha < ?
            GROUP BY clave
            """,
            (dominio.ORIGEN_ALQUILER_PCS, *rango),
        )}

    if agrupar_por == "turno":
        claves = list(dominio.TURNOS)
    elif agrupar_por == "rango":
        claves = [1]
    else:
        claves = sorted(set(pcs) | set(socios) | set(bonos))

    filas = []
    for clave in claves:
        de_socios = socios.get(clave)
        parte_socios = _parte(*(de_socios[c] for c in ("plata", "cantidad", "minutos"))) if de_socios else _parte()
        de_bonos = bonos.get(clave)
        parte_bonos = _parte(
            (pcs.get(clave) or 0.0) - parte_socios["plata"],
            de_bonos["cantidad"] if de_bonos else 0,
            de_bonos["minutos"] if de_bonos else 0,
        )
        filas.append(_comparacion(reportes_repo._etiqueta_agrupacion(clave, agrupar_por), parte_socios, parte_bonos))

    def suma(parte: str) -> dict:
        return _parte(*(sum(fila[parte][campo] for fila in filas) for campo in ("plata", "cantidad", "minutos")))

    return {"filas": filas, "total": _comparacion("TOTAL", suma("socios"), suma("bonos"))}
