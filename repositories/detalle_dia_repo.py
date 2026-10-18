"""
detalle_dia_repo.py
====================
El detalle de TODO lo que se vendió en un día del local, venta por venta, para
Reportes > Resumen del Día (pedido del dueño, 2026-10-18: "que me aparezcan
todos los turnos, y operadores, y el detalle de todo lo que se vendió:
cantidades, hora, turno, operador... de kiosko y de bonos de PC, PlayStation y
PCSTREAM, absolutamente todo").

Qué venta es de qué turno lo decide `turnos_repo._ventanas_del_dia`, la misma
función que arma las filas de cada turno del Resumen del Día: así la suma del
detalle de un turno da lo mismo que su fila (salvo una venta anulada DESPUÉS de
cerrar: el cierre guardó una foto con ella adentro; acá se la marca).

Qué se vendió en cada venta sale de la tabla que corresponde a cada cosa (como
en reportes_repo.ranking_ventas, con sus mismas categorías): venta_detalle
(artículos de kiosko), tramites_venta, sesion_bonos (bono de PC, con la PC
donde estaba la sesión AL VENDERLO aunque después se haya cambiado de máquina),
sesion_pcstream_bonos, sesion_playstation_bonos y movimientos_saldo_miembro
(bono o carga de saldo de un socio).
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import reportes_repo, turnos_repo
from turnos import etiqueta_turno


def _texto_minutos(minutos: int) -> str:
    """180 -> "3 h", 90 -> "1 h 30 min", 45 -> "45 min"."""
    horas, resto = divmod(int(minutos), 60)
    if horas and resto:
        return f"{horas} h {resto} min"
    return f"{horas} h" if horas else f"{resto} min"


def _texto_cantidad(cantidad) -> str:
    return str(int(cantidad)) if float(cantidad).is_integer() else str(cantidad)


def _ventas_entre(conexion, desde: str, hasta: str):
    return conexion.execute(
        """
        SELECT ventas.id, ventas.fecha, ventas.origen, ventas.estado, ventas.total, ventas.anulada_fecha,
               usuarios.nombre AS operador, cargadores.nombre AS cargada_por,
               COALESCE((SELECT SUM(monto) FROM venta_pagos
                         WHERE venta_id = ventas.id AND metodo = ?), 0) AS efectivo,
               COALESCE((SELECT SUM(monto) FROM venta_pagos
                         WHERE venta_id = ventas.id AND metodo = ?), 0) AS digital
        FROM ventas
        JOIN usuarios ON usuarios.id = ventas.usuario_id
        LEFT JOIN ventas_caja ON ventas_caja.venta_id = ventas.id
        LEFT JOIN usuarios AS cargadores ON cargadores.id = ventas_caja.cargada_por
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        ORDER BY ventas.fecha, ventas.id
        """,
        (dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL, desde, hasta),
    ).fetchall()


def _que_se_vendio_entre(conexion, desde: str, hasta: str) -> dict:
    """
    {venta_id: (rubro, detalle, renglones)} de las ventas de (desde, hasta] que
    tienen algo vendido anotado. `renglones` es [(rubro, producto, cantidad,
    importe)] para sumar por producto.
    """
    rango = (desde, hasta)
    resultado = {}

    lineas = {}
    for fila in conexion.execute(
        """
        SELECT venta_detalle.venta_id, venta_detalle.descripcion, venta_detalle.cantidad, venta_detalle.subtotal
        FROM venta_detalle JOIN ventas ON ventas.id = venta_detalle.venta_id
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        ORDER BY venta_detalle.id
        """, rango,
    ):
        lineas.setdefault(fila["venta_id"], []).append(fila)
    for venta_id, filas in lineas.items():
        resultado[venta_id] = (
            reportes_repo.CATEGORIA_KIOSKO,
            ", ".join(f"{_texto_cantidad(f['cantidad'])} x {f['descripcion']}" for f in filas),
            [(reportes_repo.CATEGORIA_KIOSKO, f["descripcion"], f["cantidad"], f["subtotal"]) for f in filas],
        )

    for fila in conexion.execute(
        """
        SELECT tramites_venta.venta_id, tramites_venta.descripcion, ventas.total
        FROM tramites_venta JOIN ventas ON ventas.id = tramites_venta.venta_id
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        """, rango,
    ):
        resultado[fila["venta_id"]] = (
            reportes_repo.CATEGORIA_TRAMITE, f"Trámite: {fila['descripcion']}",
            [(reportes_repo.CATEGORIA_TRAMITE, fila["descripcion"], 1, fila["total"])],
        )

    # La PC donde estaba la sesión al vender el bono: si después la cambiaron de
    # máquina (traslados_sesion), la del primer traslado posterior a la venta;
    # si no, la de la sesión.
    for fila in conexion.execute(
        """
        SELECT sesion_bonos.venta_id, sesion_bonos.minutos, bonos_tiempo.nombre AS bono, ventas.total,
               COALESCE(
                   (SELECT origen.nombre FROM traslados_sesion
                    JOIN estaciones AS origen ON origen.id = traslados_sesion.estacion_origen_id
                    WHERE traslados_sesion.sesion_id = sesion_bonos.sesion_id
                      AND traslados_sesion.fecha > ventas.fecha
                    ORDER BY traslados_sesion.fecha, traslados_sesion.id LIMIT 1),
                   estaciones.nombre
               ) AS pc
        FROM sesion_bonos
        JOIN ventas ON ventas.id = sesion_bonos.venta_id
        JOIN bonos_tiempo ON bonos_tiempo.id = sesion_bonos.bono_id
        JOIN sesiones_pc ON sesiones_pc.id = sesion_bonos.sesion_id
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        """, rango,
    ):
        resultado[fila["venta_id"]] = (
            reportes_repo.CATEGORIA_BONO_PC, f"{fila['pc']} · {fila['bono']} ({_texto_minutos(fila['minutos'])})",
            [(reportes_repo.CATEGORIA_BONO_PC, fila["bono"], 1, fila["total"])],
        )

    for fila in conexion.execute(
        """
        SELECT sesion_pcstream_bonos.venta_id, sesion_pcstream_bonos.minutos, bonos_pcstream.nombre AS bono,
               ventas.total, estaciones.nombre AS pc
        FROM sesion_pcstream_bonos
        JOIN ventas ON ventas.id = sesion_pcstream_bonos.venta_id
        JOIN bonos_pcstream ON bonos_pcstream.id = sesion_pcstream_bonos.bono_id
        JOIN sesiones_pc ON sesiones_pc.id = sesion_pcstream_bonos.sesion_id
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        """, rango,
    ):
        resultado[fila["venta_id"]] = (
            reportes_repo.CATEGORIA_BONO_PCSTREAM,
            f"{fila['pc']} · {fila['bono']} ({_texto_minutos(fila['minutos'])})",
            [(reportes_repo.CATEGORIA_BONO_PCSTREAM, fila["bono"], 1, fila["total"])],
        )

    for fila in conexion.execute(
        """
        SELECT sesion_playstation_bonos.venta_id, sesion_playstation_bonos.minutos,
               bonos_playstation.nombre AS bono, ventas.total
        FROM sesion_playstation_bonos
        JOIN ventas ON ventas.id = sesion_playstation_bonos.venta_id
        JOIN bonos_playstation ON bonos_playstation.id = sesion_playstation_bonos.bono_id
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        """, rango,
    ):
        resultado[fila["venta_id"]] = (
            reportes_repo.CATEGORIA_BONO_PLAYSTATION,
            f"{dominio.NOMBRE_PLAYSTATION} · {fila['bono']} ({_texto_minutos(fila['minutos'])})",
            [(reportes_repo.CATEGORIA_BONO_PLAYSTATION, fila["bono"], 1, fila["total"])],
        )

    for fila in conexion.execute(
        """
        SELECT movimientos_saldo_miembro.venta_id, movimientos_saldo_miembro.minutos,
               bonos_miembro.nombre AS bono, miembros.nombre AS socio, ventas.total
        FROM movimientos_saldo_miembro
        JOIN ventas ON ventas.id = movimientos_saldo_miembro.venta_id
        JOIN miembros ON miembros.id = movimientos_saldo_miembro.miembro_id
        LEFT JOIN bonos_miembro ON bonos_miembro.id = movimientos_saldo_miembro.bono_id
        WHERE movimientos_saldo_miembro.tipo = ? AND ventas.fecha > ? AND ventas.fecha <= ?
        """, (dominio.MOVIMIENTO_CARGA, *rango),
    ):
        minutos = _texto_minutos(fila["minutos"])
        if fila["bono"] is not None:
            resultado[fila["venta_id"]] = (
                reportes_repo.CATEGORIA_BONO_SOCIO, f"Socio {fila['socio']} · {fila['bono']} ({minutos})",
                [(reportes_repo.CATEGORIA_BONO_SOCIO, fila["bono"], 1, fila["total"])],
            )
        else:
            resultado[fila["venta_id"]] = (
                reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO, f"Socio {fila['socio']} · carga de saldo ({minutos})",
                [(reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO, "Carga por monto", 1, fila["total"])],
            )
    return resultado


def _por_producto(ventas: list) -> list:
    """Cuánto se vendió de cada cosa (solo las ventas no anuladas): una fila
    {"rubro", "producto", "cantidad", "importe"} por producto, agrupadas por
    rubro y de la que más se vendió a la que menos."""
    acumulado = {}
    for venta in ventas:
        if venta["anulada"]:
            continue
        for rubro, producto, cantidad, importe in venta["renglones"]:
            fila = acumulado.setdefault((rubro, producto), {"rubro": rubro, "producto": producto,
                                                            "cantidad": 0, "importe": 0.0})
            fila["cantidad"] += cantidad
            fila["importe"] = round(fila["importe"] + importe, 2)
    return sorted(acumulado.values(), key=lambda f: (f["rubro"], -f["cantidad"], f["producto"]))


def _por_operador(ventas: list) -> list:
    """Cuánto vendió cada operador (a nombre de quien quedó cada venta, como en
    Reportes > Por Operador): ventas, anuladas, efectivo, digital y total (sin
    las anuladas). Del que más vendió al que menos."""
    acumulado = {}
    for venta in ventas:
        fila = acumulado.setdefault(venta["operador"], {
            "operador": venta["operador"], "ventas": 0, "anuladas": 0,
            "efectivo": 0.0, "digital": 0.0, "total": 0.0,
        })
        if venta["anulada"]:
            fila["anuladas"] += 1
            continue
        fila["ventas"] += 1
        for campo in ("efectivo", "digital", "total"):
            fila[campo] = round(fila[campo] + venta[campo], 2)
    return sorted(acumulado.values(), key=lambda f: (-f["total"], f["operador"]))


def _totales(ventas: list) -> dict:
    validas = [venta for venta in ventas if not venta["anulada"]]
    return {
        "ventas": len(validas),
        "anuladas": len(ventas) - len(validas),
        **{campo: round(sum(venta[campo] for venta in validas), 2) for campo in ("efectivo", "digital", "total")},
    }


def detalle_del_dia(dia) -> dict:
    """
    Todo lo vendido en `dia` (date o "YYYY-MM-DD", el día del local: la Noche
    entera, hasta su cierre). Devuelve:

    {"fecha", "turnos": [...], "ventas": [...], "por_producto": [...],
     "por_operador": [...], "totales": {...}}

    Cada turno: {"turno", "etiqueta", "ventas", "por_producto", "por_operador",
    "totales"} (solo los turnos que tienen un cierre o están abiertos, en el
    orden del día). Cada venta: {"id", "fecha", "turno", "etiqueta_turno",
    "operador", "cargada_por" (quien la cobró si no fue el operador, o None),
    "rubro", "detalle", "efectivo", "digital", "total", "anulada",
    "anulada_despues_del_cierre", "renglones"}. "totales" y los resúmenes
    cuentan solo las ventas no anuladas.
    """
    dia = datetime.fromisoformat((dia if isinstance(dia, str) else dia.isoformat())[:10]).date()
    with conexion_db() as conexion:
        ventanas = turnos_repo._ventanas_del_dia(conexion, dia, datetime.now())
        ventas_por_turno = {}
        for ventana in ventanas:
            ventas_por_turno.setdefault(ventana["turno"], [])
            vendido = _que_se_vendio_entre(conexion, ventana["desde"], ventana["hasta"])
            etiqueta = etiqueta_turno(dia, ventana["turno"])
            for fila in _ventas_entre(conexion, ventana["desde"], ventana["hasta"]):
                anulada = fila["estado"] == dominio.VENTA_ANULADA
                rubro, detalle, renglones = vendido.get(fila["id"], (
                    dominio.NOMBRE_ORIGEN_VENTA.get(fila["origen"], fila["origen"]), "(sin detalle)",
                    [(dominio.NOMBRE_ORIGEN_VENTA.get(fila["origen"], fila["origen"]), "(sin detalle)", 1, fila["total"])],
                ))
                ventas_por_turno.setdefault(ventana["turno"], []).append({
                    "id": fila["id"],
                    "fecha": fila["fecha"],
                    "turno": ventana["turno"],
                    "etiqueta_turno": etiqueta,
                    "operador": fila["operador"],
                    "cargada_por": fila["cargada_por"],
                    "rubro": rubro,
                    "detalle": detalle,
                    "efectivo": round(fila["efectivo"], 2),
                    "digital": round(fila["digital"], 2),
                    "total": round(fila["total"], 2),
                    "anulada": anulada,
                    # El cierre ya la había contado (guardó una foto de lo cobrado).
                    "anulada_despues_del_cierre": bool(
                        anulada and ventana["cierre"] is not None and fila["anulada_fecha"]
                        and datetime.fromisoformat(fila["anulada_fecha"]) > datetime.fromisoformat(ventana["hasta"])
                    ),
                    "renglones": renglones,
                })

    orden = {turno: posicion for posicion, turno in enumerate(dominio.TURNOS)}
    turnos = []
    todas = []
    for turno in sorted(ventas_por_turno, key=lambda t: orden.get(t, len(orden))):
        ventas = sorted(ventas_por_turno[turno], key=lambda v: (v["fecha"], v["id"]))
        todas += ventas
        turnos.append({
            "turno": turno,
            "etiqueta": etiqueta_turno(dia, turno),
            "ventas": ventas,
            "por_producto": _por_producto(ventas),
            "por_operador": _por_operador(ventas),
            "totales": _totales(ventas),
        })
    return {
        "fecha": dia,
        "turnos": turnos,
        "ventas": todas,
        "por_producto": _por_producto(todas),
        "por_operador": _por_operador(todas),
        "totales": _totales(todas),
    }
