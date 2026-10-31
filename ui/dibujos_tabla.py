"""
ui/dibujos_tabla.py
===================
Lo que se dibuja adentro de las celdas de una lista con el diseño B (maqueta que
eligió el dueño el 2026-10-30): una etiqueta de color (el rubro de un artículo) y
el stock con una barrita que lo compara con el mínimo.

Son "delegados" de Qt: pintan la celda pero no la reemplazan, así que la celda
sigue teniendo su texto (para ordenar por la columna, buscar y las pruebas).
"""

import zlib

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QApplication, QStyle, QStyledItemDelegate, QStyleOptionViewItem

import dominio

# (letra, fondo, borde) de las etiquetas, en tonos claros. Una lista con pocos
# textos fijos (los rubros) les da un color a cada uno en orden, sin repetir
# (DelegadoEtiqueta.colores_en_orden); un texto que tiene que ir de un color en
# particular (ANULADA en rosa) lo elige por nombre (DelegadoEtiqueta.colores_fijos);
# si no, cada texto sale de su nombre.
TONOS_DE_ETIQUETA = {
    "azul": ("#1D4FA8", "#EAF1FF", "#BFD3FB"),
    "violeta": ("#6D3FC0", "#F2ECFE", "#D6C6FA"),
    "verde": ("#1D7A48", "#E9F8EF", "#B6E5C8"),
    "ámbar": ("#9A5B00", "#FFF4DE", "#F6D79A"),
    "rosa": ("#B02A6B", "#FDEBF4", "#F5BCD8"),
    "celeste": ("#0E6F86", "#E5F7FB", "#AEE2EE"),
    "naranja": ("#B4471A", "#FFEEE5", "#F6C3A8"),
    "gris": ("#3E5672", "#EEF2F7", "#C9D3E0"),
}
COLORES_DE_ETIQUETA = tuple(TONOS_DE_ETIQUETA.values())

ROJO = QColor("#D93A45")
AMBAR = QColor("#E8A317")
AZUL = QColor("#2F6FED")
VACIO = QColor("#E6EAF0")
GRIS = QColor("#8A93A3")
TEXTO = QColor("#1B2233")


def color_de_etiqueta(texto: str) -> tuple:
    """(letra, fondo, borde) de la etiqueta de `texto` sacado de su nombre: siempre
    el mismo, aunque dos textos pueden caer en el mismo color."""
    return COLORES_DE_ETIQUETA[zlib.crc32(texto.encode("utf-8")) % len(COLORES_DE_ETIQUETA)]


def _pintar_fondo(painter, option, index):
    """El fondo de la celda (renglón alternado o elegido) sin el texto, que lo
    dibuja cada delegado a su manera."""
    opcion = QStyleOptionViewItem(option)
    delegado = QStyledItemDelegate()
    delegado.initStyleOption(opcion, index)
    opcion.text = ""
    estilo = opcion.widget.style() if opcion.widget else QApplication.style()
    estilo.drawControl(QStyle.CE_ItemViewItem, opcion, painter, opcion.widget)


class DelegadoEtiqueta(QStyledItemDelegate):
    """El texto de la celda en una etiqueta redondeada de color ("BEBIDAS")."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._colores = {}

    def colores_en_orden(self, textos):
        """Un color distinto para cada uno de `textos`, en ese orden (se repiten
        recién pasados los ocho)."""
        self._colores = {texto: COLORES_DE_ETIQUETA[numero % len(COLORES_DE_ETIQUETA)]
                         for numero, texto in enumerate(textos)}

    def colores_fijos(self, tonos: dict):
        """Cada texto con el tono que se le pide por nombre ({"ANULADA": "rosa"}),
        uno de TONOS_DE_ETIQUETA."""
        self._colores = {texto: TONOS_DE_ETIQUETA[tono] for texto, tono in tonos.items()}

    def paint(self, painter, option, index):
        _pintar_fondo(painter, option, index)
        texto = (index.data() or "").strip()
        if not texto:
            return
        letra, fondo, borde = self._colores.get(texto) or color_de_etiqueta(texto)
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        fuente = QFont(option.font)
        fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 2))
        fuente.setBold(True)
        fuente.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
        painter.setFont(fuente)
        medida = painter.fontMetrics()
        celda = option.rect
        ancho = min(medida.horizontalAdvance(texto.upper()) + 20, celda.width() - 12)
        alto = medida.height() + 6
        caja = QRectF(celda.x() + 8, celda.y() + (celda.height() - alto) / 2, ancho, alto)
        painter.setPen(QPen(QColor(borde), 1))
        painter.setBrush(QColor(fondo))
        painter.drawRoundedRect(caja, alto / 2, alto / 2)
        painter.setPen(QColor(letra))
        visible = medida.elidedText(texto.upper(), Qt.ElideRight, int(ancho - 16))
        painter.drawText(caja, Qt.AlignCenter, visible)
        painter.restore()


class DelegadoStock(QStyledItemDelegate):
    """
    El stock con una barrita al lado que lo compara con el mínimo (la columna
    `columna_minimo` del mismo renglón): en rojo si quedó por debajo, en ámbar si
    está cerca (hasta una vez y media el mínimo) y en azul si sobra. La barra se
    llena del todo con el triple del mínimo.
    """

    def __init__(self, columna_minimo: int, parent=None):
        super().__init__(parent)
        self.columna_minimo = columna_minimo

    def paint(self, painter, option, index):
        _pintar_fondo(painter, option, index)
        try:
            stock = int(index.data())
            minimo = int(index.sibling(index.row(), self.columna_minimo).data())
        except (TypeError, ValueError):
            return super().paint(painter, option, index)
        bajo = dominio.bajo_el_minimo(stock, minimo)
        if bajo:
            color = ROJO
        elif stock <= minimo * 1.5:
            color = AMBAR
        else:
            color = AZUL
        lleno = 1.0 if minimo <= 0 and stock > 0 else max(0.0, min(1.0, stock / max(1, minimo * 3)))

        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        celda = option.rect.adjusted(10, 0, -10, 0)
        fuente = QFont(option.font)
        fuente.setBold(True)
        painter.setFont(fuente)
        ancho_numero = max(painter.fontMetrics().horizontalAdvance("-888"), 34)
        painter.setPen(ROJO if bajo else TEXTO)
        painter.drawText(QRectF(celda.x(), celda.y(), ancho_numero, celda.height()),
                         Qt.AlignVCenter | Qt.AlignLeft, str(stock))
        barra = QRectF(celda.x() + ancho_numero + 6, celda.center().y() - 3,
                       max(0, celda.width() - ancho_numero - 6), 6)
        if barra.width() > 12:
            painter.setPen(Qt.NoPen)
            painter.setBrush(VACIO)
            painter.drawRoundedRect(barra, 3, 3)
            if lleno > 0:
                painter.setBrush(color)
                painter.drawRoundedRect(QRectF(barra.x(), barra.y(), max(6.0, barra.width() * lleno), 6), 3, 3)
        painter.restore()
