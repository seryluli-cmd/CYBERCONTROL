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

# El fondo de las celdas que se pueden escribir (stock y código en ORDENAR
# Stock), para que se vea de un vistazo qué columnas se tocan.
FONDO_EDITABLE = QColor("#FFF4C2")

# Lo que la columna del código se ensancha de más cuando se escribe (ORDENAR
# Stock): el campo que se abre tiene borde y relleno, y sin esto, al escribir
# un EAN-13 quedaba escondido el primer dígito.
DE_MAS_PARA_ESCRIBIR_EL_CODIGO = 20


def crear_tabla_de_articulos():
    tabla = crear_tabla(TITULOS, estirar=COLUMNA_DESCRIPCION, por_filas=True, una_sola=True)
    # Clickeando el título de una columna se ordena la grilla por ella.
    tabla.setSortingEnabled(True)
    return tabla


def llenar_tabla_de_articulos(tabla, articulos, *, stock_editable=False, codigo_editable=False):
    """
    Vuelve a llenar `tabla` con `articulos` (filas de articulos_repo). Ninguna
    celda queda para escribir salvo el stock con `stock_editable` y el código
    con `codigo_editable` (las dos, solo en ORDENAR Stock). Se arma con el orden
    por columnas apagado: con él prendido, cada celda que se agrega o se pinta
    puede mover su fila a mitad del armado.
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
        item_codigo = tabla.item(fila, COLUMNA_CODIGO)
        poner_codigo(item_codigo, datos["codigo"])
        editables = ((item_stock, stock_editable), (item_codigo, codigo_editable))
        for item, editable in editables:
            if editable:
                item.setFlags(item.flags() | Qt.ItemIsEditable)
                item.setBackground(FONDO_EDITABLE)
    tabla.setSortingEnabled(True)
    mostrar_columna_entera(tabla, COLUMNA_CODIGO, DE_MAS_PARA_ESCRIBIR_EL_CODIGO if codigo_editable else 0)


def poner_codigo(item, codigo: str):
    """Muestra `codigo` en su celda y lo guarda también en ella (Qt.UserRole):
    es el código de verdad del artículo aunque la celda se esté escribiendo, y
    ORDENAR Stock lo usa para volver atrás si el nuevo no se pudo guardar."""
    item.setText(codigo)
    item.setData(Qt.UserRole, codigo)


def poner_stock(item, stock: int, stock_minimo: int):
    """Muestra `stock` en su celda, en rojo si quedó por debajo del mínimo. El
    número también queda guardado en la celda (Qt.UserRole): ORDENAR Stock lo
    usa para volver atrás si lo que se escribió no se pudo guardar."""
    item.setText(str(stock))
    item.setData(Qt.UserRole, stock)
    item.setData(Qt.ForegroundRole, QBrush(Qt.red) if stock < stock_minimo else None)
