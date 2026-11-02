"""
historial_turno_repo.py
========================
HISTORIAL DEL TURNO (pedido del dueño, 2026-11-02: "al lado de CONTROL DE
STOCK, quiero que aparezca todo el historial del operador que agarró el
turno"; eligió la maqueta A, en PROPUESTA_HISTORIAL_DEL_TURNO): todo lo cobrado
en el turno que está abierto, venta por venta, con la hora, el rubro, qué se
cobró, cómo se pagó y el total. Lo muestra ui/historial_turno_window.py.

Las ventas son las mismas que suma el Cierre de Turno (turnos_repo._ventana_en_curso:
desde el último cierre hasta ahora), así el total de acá da lo mismo que el del
cierre. Con una caja abierta, son las de esa caja: la de quien agarró el turno,
aunque cobre el Admin (quedan a nombre de ella, ver cajas_repo._quien_vende).
Qué se vendió en cada una sale de detalle_dia_repo, el mismo detalle de
Reportes > Resumen del Día.

Solo un Admin: el botón lo ven todos, pero solo el Admin lo abre (como CONTROL
DE STOCK).
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import detalle_dia_repo, reportes_repo, turnos_repo, usuarios_repo
from turnos import etiqueta_turno

# El rubro de cada venta, como se lee en la etiqueta de color de la lista y en
# los filtros de arriba.
RUBRO_BONO_PC = "BONO PC"
RUBRO_MIEMBRO = "MIEMBRO"
RUBRO_KIOSKO = "KIOSKO"
RUBRO_IMPRESIONES = "IMPRESIONES"
RUBRO_TRAMITE = "TRÁMITE"
RUBRO_PS5 = "PS5"
RUBRO_PCSTREAM = "PCSTREAM"
RUBRO_RESERVA = "RESERVA"
# Una venta sin nada anotado de qué fue (no debería haber: ver detalle_dia_repo).
RUBRO_OTRO = "OTRO"

_RUBRO_DE_CATEGORIA = {
    reportes_repo.CATEGORIA_KIOSKO: RUBRO_KIOSKO,
    reportes_repo.CATEGORIA_BONO_PC: RUBRO_BONO_PC,
    reportes_repo.CATEGORIA_BONO_SOCIO: RUBRO_MIEMBRO,
    reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO: RUBRO_MIEMBRO,
    reportes_repo.CATEGORIA_TRAMITE: RUBRO_TRAMITE,
    reportes_repo.CATEGORIA_BONO_PLAYSTATION: RUBRO_PS5,
    reportes_repo.CATEGORIA_BONO_PCSTREAM: RUBRO_PCSTREAM,
    reportes_repo.CATEGORIA_RESERVA: RUBRO_RESERVA,
}

PAGO_EFECTIVO = "Efectivo"
PAGO_DIGITAL = "Digital"
PAGO_LOS_DOS = "Efectivo y digital"


def _hora(fecha: str) -> str:
    return datetime.fromisoformat(fecha).strftime("%H:%M")


def _rubros(categoria: str, lineas: list) -> tuple:
    """(el rubro que se ve, todos los rubros por los que se la encuentra al
    filtrar). Las impresiones son un artículo del kiosko (el código 4): una
    venta de solo impresiones es IMPRESIONES; una con impresiones y otra cosa
    es KIOSKO, pero sale también al filtrar por impresiones."""
    rubro = _RUBRO_DE_CATEGORIA.get(categoria, RUBRO_OTRO)
    if rubro != RUBRO_KIOSKO:
        return rubro, (rubro,)
    impresiones = [linea["codigo"] == dominio.CODIGO_ARTICULO_IMPRESIONES for linea in lineas]
    if impresiones and all(impresiones):
        return RUBRO_IMPRESIONES, (RUBRO_IMPRESIONES,)
    if any(impresiones):
        return RUBRO_KIOSKO, (RUBRO_KIOSKO, RUBRO_IMPRESIONES)
    return RUBRO_KIOSKO, (RUBRO_KIOSKO,)


def _pago(efectivo: float, digital: float) -> str:
    if efectivo > 0 and digital > 0:
        return PAGO_LOS_DOS
    return PAGO_DIGITAL if digital > 0 else PAGO_EFECTIVO


def _nota(fila) -> str:
    """Lo que se aclara después de qué se cobró: quién la anuló, cuándo y por
    qué, y si la cobró el Admin en la caja de la empleada."""
    partes = []
    if fila["estado"] == dominio.VENTA_ANULADA:
        anulada = "anulada"
        if fila["anulada_por"]:
            anulada += f" por {fila['anulada_por']}"
        if fila["anulada_fecha"]:
            anulada += f" a las {_hora(fila['anulada_fecha'])}"
        if fila["anulada_motivo"]:
            anulada += f": {fila['anulada_motivo']}"
        partes.append(anulada)
    if fila["cargada_por"]:
        partes.append(f"cobró {fila['cargada_por']}")
    return " · ".join(partes)


def _venta(fila, vendido) -> dict:
    origen = dominio.NOMBRE_ORIGEN_VENTA.get(fila["origen"], fila["origen"])
    categoria, detalle, _renglones, lineas = vendido.get(
        fila["id"], detalle_dia_repo._sin_articulo(origen, "(sin detalle)", "(sin detalle)", fila["total"])
    )
    rubro, rubros = _rubros(categoria, lineas)
    return {
        "id": fila["id"],
        "fecha": fila["fecha"],
        "hora": _hora(fila["fecha"]),
        "rubro": rubro,
        "rubros": rubros,
        "detalle": detalle,
        "nota": _nota(fila),
        "pago": _pago(fila["efectivo"], fila["digital"]),
        "efectivo": round(fila["efectivo"], 2),
        "digital": round(fila["digital"], 2),
        "total": round(fila["total"], 2),
        "anulada": fila["estado"] == dominio.VENTA_ANULADA,
        "operador": fila["operador"],
        "cargada_por": fila["cargada_por"],
    }


def historial_del_turno(usuario_id: int) -> dict:
    """
    Todo lo cobrado en el turno abierto, de la primera venta a la última:

    {"caja_numero", "responsable", "abrio_a_las" ("18:02"; None los tres sin
    caja abierta), "turno_label", "ventas": [...], "cantidad", "anuladas",
    "efectivo", "digital", "total"}

    Cada venta: {"id", "fecha", "hora", "rubro" (uno de los RUBRO_*), "rubros"
    (por los que se la encuentra al filtrar), "detalle", "nota", "pago",
    "efectivo", "digital", "total", "anulada", "operador", "cargada_por"}.
    Las anuladas vienen en la lista, pero los números de abajo no las cuentan.
    """
    usuarios_repo.exigir_admin(usuario_id, "ver el Historial del Turno")
    with conexion_db() as conexion:
        ventana = turnos_repo._ventana_en_curso(conexion)
        vendido = detalle_dia_repo._que_se_vendio_entre(conexion, ventana["desde"], ventana["hasta"])
        ventas = [_venta(fila, vendido)
                  for fila in detalle_dia_repo._ventas_entre(conexion, ventana["desde"], ventana["hasta"])]
    validas = [venta for venta in ventas if not venta["anulada"]]
    caja = ventana["caja"]
    return {
        "caja_numero": caja["id"] if caja is not None else None,
        "responsable": caja["responsable"] if caja is not None else None,
        "abrio_a_las": _hora(caja["abierta_en"]) if caja is not None else None,
        "turno_label": etiqueta_turno(ventana["dia"], ventana["turno"]),
        "ventas": ventas,
        "cantidad": len(validas),
        "anuladas": len(ventas) - len(validas),
        **{campo: round(sum(venta[campo] for venta in validas), 2) for campo in ("efectivo", "digital", "total")},
    }
