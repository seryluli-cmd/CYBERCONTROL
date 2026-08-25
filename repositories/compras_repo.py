"""
compras_repo.py
================
Ingreso de mercadería (compras). Esta es la ÚNICA parte del sistema que
puede sumar stock a un artículo (además de que las ventas lo restan).
Cada compra queda registrada con número correlativo, fecha, quién la
cargó, y el detalle línea por línea con el stock antes/después de cada
ingreso — igual que en el sistema actual.
"""

from datetime import datetime
from database import conexion_db


def proximo_numero_compra() -> int:
    """Calcula cuál sería el próximo número de compra (para mostrarlo
    en la pantalla antes incluso de guardar nada, igual que 'Compra Nº')."""
    with conexion_db() as conexion:
        fila = conexion.execute("SELECT COALESCE(MAX(id), 0) + 1 AS proximo FROM compras").fetchone()
        return fila["proximo"]


def registrar_compra(usuario_id: int, lineas: list):
    """
    Guarda una compra completa (cabecera + líneas) y actualiza el stock
    de cada artículo involucrado. `lineas` es una lista de diccionarios:
        {"codigo": ..., "cantidad": ..., "costo_unitario": ...}

    Además, si el costo cargado es distinto al que tenía el artículo,
    actualiza el "precio_compra" del artículo para que quede al día
    (así no hay que ir aparte a Artículos a corregirlo).

    Se guarda todo (cabecera, cada línea y cada actualización de stock)
    dentro de una única transacción: si algo falla a mitad de camino
    (por ejemplo, un código que ya no existe), no queda la compra a
    medio cargar con el stock desactualizado.

    Devuelve el número de compra generado.
    """
    ahora = datetime.now().isoformat(timespec="seconds")

    with conexion_db() as conexion:
        cursor = conexion.execute(
            "INSERT INTO compras (fecha, usuario_id) VALUES (?, ?)", (ahora, usuario_id)
        )
        compra_id = cursor.lastrowid

        for linea in lineas:
            costo_unitario = round(linea["costo_unitario"], 2)
            articulo = conexion.execute(
                "SELECT stock FROM articulos WHERE codigo = ?", (linea["codigo"],)
            ).fetchone()
            stock_antes = articulo["stock"]
            stock_despues = stock_antes + linea["cantidad"]

            conexion.execute(
                """
                INSERT INTO compra_detalle
                    (compra_id, articulo_codigo, cantidad, costo_unitario, stock_antes, stock_despues)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (compra_id, linea["codigo"], linea["cantidad"], costo_unitario, stock_antes, stock_despues),
            )

            conexion.execute(
                """
                UPDATE articulos
                SET stock = ?, precio_compra = ?, fecha_modif = ?
                WHERE codigo = ?
                """,
                (stock_despues, costo_unitario, ahora, linea["codigo"]),
            )

        return compra_id
