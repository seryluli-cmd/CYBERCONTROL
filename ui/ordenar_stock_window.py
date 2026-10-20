"""
ordenar_stock_window.py
=========================
ORDENAR Stock (botón de Artículos; pedido del dueño, 2026-10-20): la misma
grilla de Artículos, pero con la columna Stock para escribir cuántos hay de
verdad en el local. Al empezar a usar el programa en el local quedaron muchos
stocks desarreglados, y hasta ese día el stock solo se movía con Compras y
Ventas.

Solo cambia la cantidad: precios, costos y la plata de la caja no se tocan. La
abre solo un Admin con la contraseña de ORDENAR Stock, y el repo vuelve a
exigir las dos cosas en cada cambio (articulos_repo.ajustar_stock), que queda
anotado en los Movimientos del artículo con quién y cuándo.

Cómo se usa: un clic en el artículo y escribir el número (o doble clic en su
stock); Enter lo guarda y pasa al de abajo. Con la pistola: escanear en el
buscador y, si queda un solo artículo, el Enter de la pistola abre su stock
para escribirlo; al guardarlo se vuelve al buscador para el próximo.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QAbstractItemView, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout,
)

from repositories import articulos_repo
from ui.articulos_tabla import (
    COLUMNA_CODIGO, COLUMNA_DESCRIPCION, COLUMNA_STOCK, COLUMNA_STOCK_MINIMO,
    crear_tabla_de_articulos, llenar_tabla_de_articulos, poner_stock,
)
from ui.utils import encadenar_enter, manejar_errores, mostrar_error, sin_boton_por_defecto


class OrdenarStockWindow(QDialog):
    def __init__(self, parent, usuario_id: int, clave: str):
        super().__init__(parent)
        self.usuario_id = usuario_id
        # La contraseña viaja en cada cambio porque el repo la vuelve a pedir;
        # no se guarda en ningún lado y se va con la ventana.
        self._clave = clave
        # Mientras el programa mismo escribe en la grilla, `itemChanged` no es
        # algo que tecleó el Admin y no hay que guardarlo.
        self._llenando = False
        self.setWindowTitle("ORDENAR Stock")
        self.resize(950, 600)
        self._armar_interfaz()
        self._cargar_grilla()

    def _armar_interfaz(self):
        aviso = QLabel(
            "Acá se corrige solo el STOCK (la columna amarilla): un clic en el artículo, "
            "escribí cuántos hay de verdad y Enter. Los precios, los costos y la caja no se "
            "tocan; cada cambio queda anotado en los Movimientos del artículo."
        )
        aviso.setWordWrap(True)

        self.campo_buscar = QLineEdit()
        self.campo_buscar.setPlaceholderText("Buscar por código o descripción (o escanear con la pistola)...")
        self.campo_buscar.textChanged.connect(self._cargar_grilla)
        encadenar_enter(self.campo_buscar, accion_final=self._ir_a_la_lista)

        self.tabla = crear_tabla_de_articulos()
        # Solo la celda del stock se arma con permiso para escribir
        # (llenar_tabla_de_articulos), así que estos disparadores no abren ninguna
        # otra. "Cualquier tecla" es para escribir el número sin doble clic.
        self.tabla.setEditTriggers(
            QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
            | QAbstractItemView.AnyKeyPressed
        )
        self.tabla.cellClicked.connect(self._apuntar_al_stock)
        self.tabla.itemChanged.connect(self._stock_escrito)

        self.etiqueta_estado = QLabel("")
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        fila_abajo = QHBoxLayout()
        fila_abajo.addWidget(self.etiqueta_estado, 1)
        fila_abajo.addWidget(boton_salir)

        layout = QVBoxLayout()
        layout.addWidget(aviso)
        layout.addWidget(self.campo_buscar)
        layout.addWidget(self.tabla)
        layout.addLayout(fila_abajo)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.campo_buscar.setFocus()

    @manejar_errores
    def _cargar_grilla(self, _=None):
        # El "_=None" absorbe el texto que manda `textChanged` (ver
        # ArticulosWindow._cargar_grilla).
        articulos = articulos_repo.listar_articulos(self.campo_buscar.text().strip())
        self._llenando = True
        try:
            llenar_tabla_de_articulos(self.tabla, articulos, stock_editable=True)
        finally:
            self._llenando = False

    def _apuntar_al_stock(self, fila, _columna):
        # Un clic en cualquier parte del renglón deja lista la celda del stock: así
        # se escribe el número de una, sin apuntarle justo a esa columna.
        self.tabla.setCurrentCell(fila, COLUMNA_STOCK)

    def _ir_a_la_lista(self):
        """Enter en el buscador (el que manda la pistola al escanear)."""
        if self.tabla.rowCount() == 0:
            return
        self.tabla.setFocus()
        self.tabla.setCurrentCell(0, COLUMNA_STOCK)
        # Solo con UN artículo en la lista se abre su stock para escribir: con
        # varios, el Enter de la pistola dejaría escribiendo en el que no es.
        if self.tabla.rowCount() == 1:
            self.tabla.editItem(self.tabla.item(0, COLUMNA_STOCK))

    @manejar_errores
    def _stock_escrito(self, item):
        if self._llenando or item.column() != COLUMNA_STOCK:
            return
        fila = item.row()
        codigo = self.tabla.item(fila, COLUMNA_CODIGO).text()
        descripcion = self.tabla.item(fila, COLUMNA_DESCRIPCION).text()
        minimo = int(self.tabla.item(fila, COLUMNA_STOCK_MINIMO).text())
        anterior = item.data(Qt.UserRole)
        try:
            resultado = articulos_repo.ajustar_stock(self.usuario_id, codigo, item.text(), self._clave)
        except (ValueError, PermissionError) as error:
            self._mostrar_stock(item, anterior, minimo)
            self.etiqueta_estado.setText("")
            # El cartel sale cuando ya se cerró la celda: abierto ahora, la celda
            # pierde el foco, Qt la vuelve a guardar con lo mal escrito y salían
            # dos carteles.
            mensaje = str(error)
            QTimer.singleShot(0, lambda: mostrar_error(self, "No se pudo guardar", mensaje))
            return
        except Exception:
            self._mostrar_stock(item, anterior, minimo)
            raise
        self._mostrar_stock(item, resultado["stock_nuevo"], minimo)
        self.etiqueta_estado.setText(
            f"Guardado: {descripcion}, stock {resultado['stock_anterior']} → {resultado['stock_nuevo']}"
        )
        # Se pregunta recién ahora: con la grilla ordenada por Stock, el renglón
        # ya se movió a su lugar nuevo.
        fila = self.tabla.row(item)
        QTimer.singleShot(0, lambda: self._pasar_al_siguiente(fila))

    def _mostrar_stock(self, item, stock, minimo):
        self._llenando = True
        try:
            poner_stock(item, stock, minimo)
        finally:
            self._llenando = False

    def _pasar_al_siguiente(self, fila):
        """Después de guardar: el renglón de abajo queda listo para escribir (o se
        saltea con la flecha); si era el último, o el único que dejó la pistola,
        se vuelve al buscador con el texto marcado para el próximo escaneo."""
        if 0 <= fila < self.tabla.rowCount() - 1:
            self.tabla.setFocus()
            self.tabla.setCurrentCell(fila + 1, COLUMNA_STOCK)
        else:
            self.campo_buscar.setFocus()
            self.campo_buscar.selectAll()
