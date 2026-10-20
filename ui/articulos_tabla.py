"""
articulos_tabla.py
====================
La grilla de artículos que comparten Artículos y ORDENAR Stock: las mismas
columnas, el mismo orden y el stock en rojo cuando queda por debajo del
mínimo. Vive aparte para que las dos pantallas la usen sin importarse entre
sí (Artículos es la que abre ORDENAR Stock).
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QTableWidgetItem

from ui.utils import crear_tabla, formato_pesos, mostrar_columna_entera

TITULOS = ("Código", "Descripción", "Marca", "Rubro", "Precio Venta",
           "Precio Compra", "Stock", "Stock Mínimo")
COLUMNA_CODIGO = 0
COLUMNA_DESCRIPCION = 1
COLUMNA_STOCK = 6
COLUMNA_STOCK_MINIMO = 7

# El fondo de la celda de stock cuando se puede escribir (ORDENAR Stock), para
# que se vea de un vistazo cuál es la única columna que se toca.
FONDO_EDITABLE = QColor("#FFF4C2")


def crear_tabla_de_articulos():
    tabla = crear_tabla(TITULOS, estirar=COLUMNA_DESCRIPCION, por_filas=True, una_sola=True)
    # Clickeando el título de una columna se ordena la grilla por ella.
    tabla.setSortingEnabled(True)
    return tabla


def llenar_tabla_de_articulos(tabla, articulos, *, stock_editable=False):
    """
    Vuelve a llenar `tabla` con `articulos` (filas de articulos_repo). Ninguna
    celda queda para escribir salvo el stock con `stock_editable` (ORDENAR
    Stock). Se arma con el orden por columnas apagado: con él prendido, cada
    celda que se agrega o se pinta puede mover su fila a mitad del armado.
    """
    tabla.setSortingEnabled(False)
    tabla.setRowCount(0)
    for datos in articulos:
        fila = tabla.rowCount()
        tabla.insertRow(fila)
        textos = (
            datos["codigo"], datos["descripcion"], datos["marca"] or "", datos["rubro"] or "",
            formato_pesos(datos["precio_venta"]), formato_pesos(datos["precio_compra"]),
            str(datos["stock"]), str(datos["stock_minimo"]),
        )
        for columna, texto in enumerate(textos):
            item = QTableWidgetItem(texto)
            item.setFlags(item.flags() & ~Qt.ItemIsEditable)
            tabla.setItem(fila, columna, item)
        item_stock = tabla.item(fila, COLUMNA_STOCK)
        poner_stock(item_stock, datos["stock"], datos["stock_minimo"])
        if stock_editable:
            item_stock.setFlags(item_stock.flags() | Qt.ItemIsEditable)
            item_stock.setBackground(FONDO_EDITABLE)
    tabla.setSortingEnabled(True)
    mostrar_columna_entera(tabla, COLUMNA_CODIGO)


def poner_stock(item, stock: int, stock_minimo: int):
    """Muestra `stock` en su celda, en rojo si quedó por debajo del mínimo. El
    número también queda guardado en la celda (Qt.UserRole): ORDENAR Stock lo
    usa para volver atrás si lo que se escribió no se pudo guardar."""
    item.setText(str(stock))
    item.setData(Qt.UserRole, stock)
    item.setData(Qt.ForegroundRole, QBrush(Qt.red) if stock < stock_minimo else None)
