"""
venta_buscador.py
===================
El campo de arriba de Venta de Mercadería sirve para todo y el operador no elige
nada (pedido del dueño, 2026-11-09: "que no tenga que estar eligiendo el operador"):

- Sin letras (la pistola, o el código tipeado a mano): es un código de barras. No
  abre lista: entra con Enter como siempre, y un código que no existe se avisa con
  cuántos dígitos llegaron (ver ui/buscar_articulo.avisar_codigo_no_encontrado).
- Con alguna letra: busca el producto por su nombre O por su marca, cada palabra en
  cualquier orden ("coca zero", "jorgito"; ver articulos_repo.buscar_para_vender).
  Lo encontrado sale en una lista debajo del campo, encima del carrito: las flechas
  eligen (arranca marcado el primero), Enter o un clic lo agregan y la lista se
  cierra. Un código con letras ("123A") entra igual: si la lista no trae nada,
  Enter busca el código exacto.

Esc borra lo escrito; con el campo vacío hace lo de siempre (sale de la venta).

Antes (hasta el 09/11) Venta tenía los botones F5/F6/F7, que abrían el cuadro
chico aparte para buscar por código, descripción o marca. Compras sigue con ese
cuadro (ui/buscar_articulo.py).
"""

from PySide6.QtCore import QEvent, QPoint, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QGraphicsDropShadowEffect, QHeaderView, QLabel, QLineEdit, QTableWidget, QTableWidgetItem

from repositories import articulos_repo
from ui.utils import formato_pesos, manejar_errores
from ui.ventas_dibujos import (
    ALTO_DIBUJO_CAMPO, ANCHO_DIBUJO_CODIGO_O_ABC, ROL_DETALLE, DelegadoProducto, dibujo_codigo_o_abc,
)

AYUDA_DEL_CAMPO = "Escaneá el código de barras, o escribí el nombre o la marca del producto..."

_TOPE_DE_RESULTADOS = 100   # se recorre con las flechas o la rueda: más no ayuda a elegir (va como LIMIT a la base)
_RENGLONES_A_LA_VISTA = 6
_ALTO_RENGLON = 46          # el mismo renglón de dos pisos del carrito
_ANCHO_PRECIO = 120
_X_DIBUJO = 10              # el borde (2 px) y el relleno (8 px) del campo en la hoja de estilos


def es_para_buscar(texto: str) -> bool:
    """True si lo escrito se busca por nombre o marca (tiene alguna letra); False si es
    un código de barras (solo números, como lo que manda la pistola)."""
    return any(letra.isalpha() for letra in texto)


class BuscadorDeLaVenta(QTableWidget):
    """La lista que se abre debajo del campo con lo encontrado. Es hija de la ventana
    y flota encima del carrito: no ocupa lugar mientras está cerrada.
    `al_elegir(codigo)` agrega al carrito, lo mismo que la pistola."""

    def __init__(self, ventana, campo: QLineEdit, al_elegir):
        super().__init__(0, 2, ventana)
        self.campo = campo
        self.al_elegir = al_elegir
        self._resultados = []
        self._armar_lista()
        # El dibujo (el código de barras con "Abc" al lado: da lo mismo escanear que
        # escribir) va en una etiqueta encima del campo, con lugar reservado a la
        # izquierda del texto: como ícono del campo (addAction) Qt lo achica a 16 px.
        self.dibujo_del_campo = QLabel(campo)
        self.dibujo_del_campo.setFixedSize(ANCHO_DIBUJO_CODIGO_O_ABC, ALTO_DIBUJO_CAMPO)
        self.dibujo_del_campo.setAlignment(Qt.AlignLeft | Qt.AlignVCenter)
        self.dibujo_del_campo.setAttribute(Qt.WA_TransparentForMouseEvents)   # un clic ahí es en el campo
        self.dibujo_del_campo.setPixmap(dibujo_codigo_o_abc())
        campo.setTextMargins(ANCHO_DIBUJO_CODIGO_O_ABC + 8, 0, 0, 0)
        campo.setPlaceholderText(AYUDA_DEL_CAMPO)
        campo.textChanged.connect(self._buscar)
        campo.installEventFilter(self)

    def _armar_lista(self):
        self.setObjectName("resultadosVenta")
        self.setEditTriggers(QTableWidget.NoEditTriggers)
        self.setSelectionBehavior(QTableWidget.SelectRows)
        self.setSelectionMode(QTableWidget.SingleSelection)
        self.setAlternatingRowColors(True)
        self.setShowGrid(False)
        self.horizontalHeader().setVisible(False)
        self.verticalHeader().setVisible(False)
        self.verticalHeader().setDefaultSectionSize(_ALTO_RENGLON)
        self.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.horizontalHeader().setSectionResizeMode(1, QHeaderView.Fixed)
        self.setColumnWidth(1, _ANCHO_PRECIO)
        self.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        # La letra sigue en el campo mientras se elige: las flechas y Enter van ahí.
        self.setFocusPolicy(Qt.NoFocus)
        # Como el carrito: la descripción grande y, chiquito debajo, el código y la marca.
        self.setItemDelegateForColumn(0, DelegadoProducto(self))
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(18)
        sombra.setOffset(0, 4)
        sombra.setColor(QColor(20, 30, 50, 70))
        self.setGraphicsEffect(sombra)
        self.cellClicked.connect(self._al_hacer_clic)
        self.hide()

    def codigo_elegido(self, texto):
        """El código que agrega un Enter con `texto` escrito en el campo. Un código de
        barras, tal cual (si no es ningún artículo, Ventas avisa como siempre). Si se
        buscó por nombre o marca, el renglón marcado de la lista; si no hay ninguno, el
        código exacto. None: no hay nada que agregar, y la lista ya dice por qué."""
        if not es_para_buscar(texto):
            return texto
        fila = self.currentRow()
        if 0 <= fila < len(self._resultados):
            return self._resultados[fila]["codigo"]
        if articulos_repo.buscar_por_codigo(texto) is not None:
            return texto
        return None

    @manejar_errores
    def _buscar(self, texto):
        texto = texto.strip()
        if not es_para_buscar(texto):
            self._resultados = []
            self.hide()
            return
        self._resultados = list(articulos_repo.buscar_para_vender(texto, limite=_TOPE_DE_RESULTADOS))
        self._llenar(texto)
        self._mostrar()

    def _llenar(self, texto):
        self.clearSpans()
        self.setRowCount(0)
        for articulo in self._resultados:
            fila = self.rowCount()
            self.insertRow(fila)
            producto = QTableWidgetItem(articulo["descripcion"])
            producto.setData(ROL_DETALLE, "  ·  ".join(filter(None, (articulo["codigo"], articulo["marca"]))))
            precio = QTableWidgetItem(formato_pesos(articulo["precio_venta"]))
            precio.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.setItem(fila, 0, producto)
            self.setItem(fila, 1, precio)
        if self._resultados:
            self.setCurrentCell(0, 0)   # Enter agrega el primero sin tocar las flechas
            return
        aviso = QTableWidgetItem(f"No hay ningún producto que diga “{texto}”")
        aviso.setData(ROL_DETALLE, "Probá con otra palabra: sirve el nombre o la marca del producto")
        aviso.setFlags(Qt.ItemIsEnabled)
        self.insertRow(0)
        self.setItem(0, 0, aviso)
        self.setSpan(0, 0, 1, 2)

    def _mostrar(self):
        """Abre la lista justo debajo del campo, de su mismo ancho y con hasta
        `_RENGLONES_A_LA_VISTA` renglones (los demás, con la rueda)."""
        abajo_del_campo = self.campo.mapTo(self.parentWidget(), QPoint(0, self.campo.height() + 4))
        renglones = min(max(self.rowCount(), 1), _RENGLONES_A_LA_VISTA)
        self.setGeometry(abajo_del_campo.x(), abajo_del_campo.y(), self.campo.width(),
                         renglones * _ALTO_RENGLON + 2 * self.frameWidth() + 2)
        self.show()
        self.raise_()

    def _al_hacer_clic(self, fila, _columna):
        if 0 <= fila < len(self._resultados):
            codigo = self._resultados[fila]["codigo"]
            self.campo.clear()
            self.al_elegir(codigo)

    def eventFilter(self, objeto, evento):
        if objeto is self.campo:
            tipo = evento.type()
            if tipo == QEvent.KeyPress:
                return self._tecla_en_el_campo(evento.key())
            if tipo == QEvent.Resize:
                self.dibujo_del_campo.move(_X_DIBUJO, (self.campo.height() - ALTO_DIBUJO_CAMPO) // 2)
            if tipo in (QEvent.Resize, QEvent.Move) and self.isVisible():
                self._mostrar()
            elif tipo == QEvent.FocusOut:
                # Un clic en el carrito o en otra ventana la cierra: si no, taparía los
                # renglones. Al volver al campo se abre de nuevo con lo que esté escrito.
                self.hide()
            elif tipo == QEvent.FocusIn and es_para_buscar(self.campo.text().strip()):
                self._mostrar()
        return False

    def _tecla_en_el_campo(self, tecla):
        """True si la tecla la usó la lista (y el campo no la recibe)."""
        pasos = {Qt.Key_Down: 1, Qt.Key_Up: -1,
                 Qt.Key_PageDown: _RENGLONES_A_LA_VISTA, Qt.Key_PageUp: -_RENGLONES_A_LA_VISTA}
        if tecla in pasos and self.isVisible() and self._resultados:
            fila = min(max(self.currentRow() + pasos[tecla], 0), len(self._resultados) - 1)
            self.setCurrentCell(fila, 0)
            self.scrollToItem(self.item(fila, 0))
            return True
        if tecla == Qt.Key_Escape and self.campo.text():
            self.campo.clear()   # con el campo vacío, Esc sigue de largo (sale de la venta)
            return True
        return False
