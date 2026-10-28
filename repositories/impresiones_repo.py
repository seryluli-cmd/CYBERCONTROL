"""
impresiones_repo.py
=====================
El cobro rápido de IMPRESIONES desde el botón de la barra de arriba (pedido
del dueño, 2026-10-19: "quiero una tarjeta para que esté más a mano"), sin
tener que entrar a Vender y buscar el artículo.

No es un negocio aparte: es una venta de kiosko común del artículo
dominio.CODIGO_ARTICULO_IMPRESIONES, con su renglón en venta_detalle, que
descuenta stock y entra en la caja abierta igual que si se la hubiera
escaneado en Vender. Por eso Caja, Cierre de Turno, Reportes, el Detalle del
Día y anular desde Consulta de Ventas la tratan sin saber de dónde vino.
"""

import dominio
from database import conexion_db
from repositories import ventas_repo

# Tope de una sola vez: alcanza de sobra para un pedido grande y frena un
# número tipeado de más (un 1500 en vez de 15) antes de cobrarlo.
CANTIDAD_MAXIMA = 999


def _leer_articulo(conexion):
    return conexion.execute(
        "SELECT codigo, descripcion, precio_venta FROM articulos WHERE codigo = ?",
        (dominio.CODIGO_ARTICULO_IMPRESIONES,),
    ).fetchone()


def articulo_impresiones():
    """El artículo de las impresiones (código, descripción y precio), o None
    si no está cargado con el código dominio.CODIGO_ARTICULO_IMPRESIONES."""
    with conexion_db() as conexion:
        return _leer_articulo(conexion)


def mensaje_sin_articulo() -> str:
    """Qué decirle a quien atiende si el artículo no está cargado."""
    return (
        f"No hay ningún artículo con el código {dominio.CODIGO_ARTICULO_IMPRESIONES} "
        "(IMPRESIONES). Un encargado lo tiene que cargar en Admin Kiosko > Artículos "
        "con ese código."
    )


def cobrar_impresiones(usuario_id: int, cantidad: int, precio_unitario: float, pagos: list) -> int:
    """
    Graba la venta de `cantidad` impresiones y devuelve su número. `pagos` son
    los que devuelve la ventana de cobro (netos de vuelto): tienen que sumar
    el total, si no, no se graba nada.

    `precio_unitario` es el que vio quien atiende al cobrar: si alguien cambió
    el precio en Artículos mientras tanto, no se graba (se le cobró al cliente
    otra plata que la que quedaría anotada). El precio y la venta se leen y se
    graban en la misma transacción.
    """
    if not isinstance(cantidad, int) or cantidad < 1:
        raise ValueError("Ingresá cuántas impresiones son (al menos 1).")
    if cantidad > CANTIDAD_MAXIMA:
        raise ValueError(f"Son más de {CANTIDAD_MAXIMA} impresiones: revisá la cantidad.")

    with conexion_db() as conexion:
        articulo = _leer_articulo(conexion)
        if articulo is None:
            raise ValueError(mensaje_sin_articulo())
        if articulo["precio_venta"] <= 0:
            raise ValueError(
                "Las impresiones no tienen precio cargado. Un encargado lo tiene que "
                "poner en Admin Kiosko > Artículos."
            )
        if round(articulo["precio_venta"], 2) != round(precio_unitario, 2):
            raise ValueError(
                "El precio de las impresiones cambió mientras cobrabas. No se grabó nada: "
                "volvé a abrir Impresiones."
            )

        linea = {
            "codigo": articulo["codigo"],
            "descripcion": articulo["descripcion"],
            "cantidad": cantidad,
            "precio_unitario": articulo["precio_venta"],
        }
        # Que los pagos sumen el total lo revisa _grabar_venta_kiosko, igual
        # que para cualquier venta de kiosko.
        return ventas_repo._grabar_venta_kiosko(conexion, usuario_id, [linea], pagos)
