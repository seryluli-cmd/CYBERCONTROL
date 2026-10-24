"""
historial_cargas_repo.py
========================
El Historial de Cargas de saldo de los socios (pedido del dueño, 2026-10-24;
botón de la ventana de Miembros, para cualquier operador): cada carga con a
qué socio, cuánto tiempo, cuánta plata y cómo se pagó, quién la cargó y la
fecha y hora. Solo lee: no toca saldos ni la caja.

- Solo los movimientos CARGA de movimientos_saldo_miembro: los consumos y los
  reintegros no son cargas, y los saldos IMPORTACION (los socios traídos del
  programa anterior, 2026-10-19) no los cargó ningún operador.
- Una carga que pasó directo a la PC del socio que estaba jugando
  (miembros_repo._sumar_carga_a_la_sesion) sigue siendo una CARGA: sale.
- Quién la cargó es el que apretó el botón. Cuando el Admin cobra con la caja
  de una empleada abierta, la venta queda a nombre de ella
  (cajas_repo._quien_vende) y él queda en ventas_caja.cargada_por: acá sale él.
- Una carga anulada (Consulta de Ventas, miembros_repo.anular_carga) sale con
  quién la anuló y por qué, y no suma en los totales.
- Los días son los del local, de 06:00 a 06:00 (turnos.limites_de_los_dias),
  como en los reportes de ventas: la Noche entra entera en su día.
"""

import dominio
from database import conexion_db
from turnos import limites_de_los_dias

_NOMBRES_DE_PAGO = {dominio.PAGO_EFECTIVO: "Efectivo", dominio.PAGO_DIGITAL: "Digital"}


def _medio_de_pago(metodos) -> str:
    """"Efectivo", "Digital" o "Efectivo y digital", según los pagos de la venta
    (`metodos`: los métodos separados por coma, como los junta GROUP_CONCAT)."""
    usados = [metodo for metodo in dominio.METODOS_PAGO if metodo in (metodos or "").split(",")]
    if len(usados) > 1:
        return "Efectivo y digital"
    return _NOMBRES_DE_PAGO.get(usados[0], usados[0]) if usados else ""


def _nombre_del_socio(usuario: str, nombre: str) -> str:
    """El usuario del socio y, si cargó otro nombre, entre paréntesis. Un socio
    sin nombre lo tiene guardado igual que el usuario (ver miembros_repo)."""
    if nombre and nombre.strip() and nombre.strip().lower() != usuario.lower():
        return f"{usuario} ({nombre.strip()})"
    return usuario


def listar_cargas(desde, hasta, buscar: str = "", miembro_id: int = None) -> list:
    """
    Las cargas de los días `desde` a `hasta` (incluidos los dos; date o
    "YYYY-MM-DD"), de la más nueva a la más vieja. Con `miembro_id`, solo las
    de ese socio; si no, con `buscar`, las de los socios cuyo usuario o nombre
    lo contiene, sin mirar mayúsculas ni acentos ("ana" también trae a
    "mariana": por eso Miembros, con un socio marcado, pasa su id). Cada una es
    un diccionario con fecha, socio, minutos, monto, medio (de pago), bono
    (None si fue un monto libre), operador, anulada y, si lo está,
    anulada_por, anulada_fecha y anulada_motivo.
    """
    inicio, fin = limites_de_los_dias(desde, hasta)
    del_socio, parametros = "", [dominio.MOVIMIENTO_CARGA, inicio, fin]
    if miembro_id is not None:
        del_socio, buscar = " AND m.miembro_id = ?", ""
        parametros.append(miembro_id)
    with conexion_db() as conexion:
        filas = conexion.execute(
            """
            SELECT m.id, m.fecha, m.minutos,
                   mi.usuario AS socio_usuario, mi.nombre AS socio_nombre,
                   b.nombre AS bono,
                   v.total, v.estado, v.anulada_fecha, v.anulada_motivo,
                   op.nombre AS operador, an.nombre AS anulada_por,
                   (SELECT GROUP_CONCAT(p.metodo) FROM venta_pagos p WHERE p.venta_id = v.id) AS metodos
            FROM movimientos_saldo_miembro m
            JOIN miembros mi ON mi.id = m.miembro_id
            LEFT JOIN bonos_miembro b ON b.id = m.bono_id
            LEFT JOIN ventas v ON v.id = m.venta_id
            LEFT JOIN ventas_caja vc ON vc.venta_id = v.id
            LEFT JOIN usuarios op ON op.id = COALESCE(vc.cargada_por, v.usuario_id)
            LEFT JOIN usuarios an ON an.id = v.anulada_por
            WHERE m.tipo = ? AND m.fecha >= ? AND m.fecha < ?""" + del_socio + """
            ORDER BY m.fecha DESC, m.id DESC
            """,
            parametros,
        ).fetchall()

    buscado = dominio.sin_acentos(buscar).strip()
    cargas = []
    for fila in filas:
        if buscado and buscado not in dominio.sin_acentos(f"{fila['socio_usuario']} {fila['socio_nombre']}"):
            continue
        anulada = fila["estado"] == dominio.VENTA_ANULADA
        cargas.append({
            "fecha": fila["fecha"],
            "socio": _nombre_del_socio(fila["socio_usuario"], fila["socio_nombre"]),
            "minutos": fila["minutos"],
            "monto": fila["total"] or 0.0,
            "medio": _medio_de_pago(fila["metodos"]),
            "bono": fila["bono"],
            "operador": fila["operador"] or "",
            "anulada": anulada,
            "anulada_por": fila["anulada_por"] if anulada else None,
            "anulada_fecha": fila["anulada_fecha"] if anulada else None,
            "anulada_motivo": fila["anulada_motivo"] if anulada else None,
        })
    return cargas


def totales(cargas: list) -> dict:
    """Cuántas cargas, cuántos minutos y cuánta plata suman `cargas` (de
    listar_cargas), sin las anuladas: esa plata no quedó en la caja."""
    vigentes = [carga for carga in cargas if not carga["anulada"]]
    return {
        "cantidad": len(vigentes),
        "minutos": sum(carga["minutos"] for carga in vigentes),
        "monto": round(sum(carga["monto"] for carga in vigentes), 2),
        "anuladas": len(cargas) - len(vigentes),
    }
