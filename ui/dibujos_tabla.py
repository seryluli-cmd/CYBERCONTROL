"""
ui/dibujos_tabla.py
===================
Lo que se dibuja adentro de las celdas de una lista con el diseño B (maqueta que
eligió el dueño el 2026-10-30): una etiqueta de color (el rubro de un artículo) y
el stock con una barrita que lo compara con el mínimo.

Son "delegados" de Qt: pintan la celda pero no la reemplazan, así que la celda
sigue teniendo su texto (para ordenar por la columna, buscar y las pruebas).

Acá vive también el color de cada rubro (TONO_PCS, TONO_KIOSKO...), uno solo para
todo el programa, y la cabecera con una barra de color por rubro de Reportes.
"""

import zlib

from PySide6.QtCore import QRect, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter, QPen
from PySide6.QtWidgets import QApplication, QHeaderView, QStyle, QStyledItemDelegate, QStyleOptionViewItem

import dominio

# (letra, fondo, borde) de las etiquetas, en tonos claros. Una lista con pocos
# textos fijos (los rubros) les da un color a cada uno en orden, sin repetir
# (DelegadoEtiqueta.colores_en_orden); un texto que tiene que ir de un color en
# particular (Kiosko en verde) lo elige por nombre (DelegadoEtiqueta.colores_fijos);
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

# El rojo de una venta ANULADA (ui.detalle_venta.etiqueta_de_estado), aparte de los
# ocho de arriba: no lo reparte nadie (ni en orden ni por nombre) ni es el de un
# rubro. Hasta el 2026-11-19 ANULADA iba en rosa, pero ese día el rosa pasó a ser
# el de la PlayStation 5 y en Consulta de Ventas una venta de la PS5 anulada
# llevaba dos etiquetas rosas en el mismo renglón.
TONO_ALERTA = "rojo"
TONOS_DE_ETIQUETA[TONO_ALERTA] = ("#B42318", "#FDECEC", "#F1A9A3")

# Un color por rubro, EL MISMO en todo el programa: Reportes (el Ranking, los
# títulos de TOTALES y del Resumen del Día, Socios y Bonos), el Historial del Turno
# y el Origen de Consulta de Ventas y Control de Cierres. Pedido del dueño
# (2026-11-19): "bono de PC y bono de PlayStation diferentes colores, lo que sea de
# una misma categoría que mantengan color". La PS5 va en rosa y no en celeste: el
# celeste se confundía con el azul de las PCs. Los socios (cargas y bonos) van
# juntos en violeta: en el Ranking el naranja se confundía con el ámbar de los
# trámites. Las reservas se quedan con el naranja, el único que quedaba libre: no
# salen en el Ranking, pero en el Historial del Turno y el Detalle del Día pueden
# quedar cerca de un trámite (ámbar); si se confunden, la salida es un tono nuevo
# (distinto también del rojo de ANULADA, TONO_ALERTA), mostrándoselo antes al dueño. El mapa se le mostró antes (PROPUESTA_REPORTES).
TONO_PCS = "azul"              # bonos de PC del mostrador y "Alquiler de PCs"
TONO_PLAYSTATION = "rosa"
TONO_PCSTREAM = "celeste"
TONO_KIOSKO = "verde"
TONO_IMPRESIONES = "gris"
TONO_TRAMITES = "ámbar"
TONO_SOCIOS = "violeta"
TONO_RESERVAS = "naranja"

# El negocio de una venta (dominio.ORIGENES_VENTA) con el tono de su rubro.
TONO_DE_ORIGEN = {
    dominio.ORIGEN_KIOSKO: TONO_KIOSKO,
    dominio.ORIGEN_ALQUILER_PCS: TONO_PCS,
    dominio.ORIGEN_PLAYSTATION: TONO_PLAYSTATION,
}


def tonos_de_los_origenes() -> dict:
    """{nombre que se ve del origen ("Kiosko", "Alquiler de PCs"...): tono}, para
    DelegadoEtiqueta.colores_fijos en las columnas Origen."""
    return {dominio.NOMBRE_ORIGEN_VENTA[origen]: tono for origen, tono in TONO_DE_ORIGEN.items()}


def color_fuerte(tono: str) -> QColor:
    """El color de la letra de un tono (el más fuerte de los tres): el de una barra
    o una franja que tiene que decir de qué rubro es."""
    return QColor(TONOS_DE_ETIQUETA[tono][0])


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
    """El texto de la celda en una etiqueta redondeada de color ("BEBIDAS").

    `grande`: la letra un punto más chica que la de la tabla (no dos), más alta y
    con menos espacio entre letras; la usan las columnas de Reportes (2026-11-19):
    la Categoría del Ranking y el Rubro del Detalle del Día
    (reportes_piezas.etiqueta_de_rubros), el Origen de Por Operador
    (etiqueta_de_origenes) y el Turno de Por Turno. Con `grande`, un texto sin color
    fijo va en gris en vez de tomar uno de su nombre."""

    def __init__(self, parent=None, grande=False):
        super().__init__(parent)
        self._colores = {}
        self.grande = grande

    def colores_en_orden(self, textos):
        """Un color distinto para cada uno de `textos`, en ese orden (se repiten
        recién pasados los ocho)."""
        self._colores = {texto: COLORES_DE_ETIQUETA[numero % len(COLORES_DE_ETIQUETA)]
                         for numero, texto in enumerate(textos)}

    def colores_fijos(self, tonos: dict):
        """Cada texto con el tono que se le pide por nombre ({"Kiosko": "verde"}),
        uno de TONOS_DE_ETIQUETA."""
        self._colores = {texto: TONOS_DE_ETIQUETA[tono] for texto, tono in tonos.items()}

    def fuente(self, base: QFont) -> QFont:
        """La letra de la etiqueta, sacada de la de la celda."""
        fuente = QFont(base)
        if self.grande:
            fuente.setPointSizeF(max(8.0, fuente.pointSizeF() - 1))
        else:
            fuente.setPointSizeF(max(7.0, fuente.pointSizeF() - 2))
        fuente.setBold(True)
        fuente.setLetterSpacing(QFont.AbsoluteSpacing, 0.3 if self.grande else 0.6)
        return fuente

    def ancho_para(self, texto: str, base: QFont) -> int:
        """Lo que necesita una columna para que la etiqueta de `texto` entre entera
        (sin "...")."""
        return QFontMetrics(self.fuente(base)).horizontalAdvance(texto.upper()) + (22 if self.grande else 20) + 24

    def sizeHint(self, option, index):
        # La grande, en mayúscula y negrita, es más ancha que el texto de la celda:
        # una columna "al ancho del contenido" la cortaba con "...".
        tamaño = super().sizeHint(option, index)
        if self.grande:
            texto = (index.data() or "").strip()
            if texto:
                tamaño.setWidth(max(tamaño.width(), self.ancho_para(texto, option.font)))
        return tamaño

    def paint(self, painter, option, index):
        _pintar_fondo(painter, option, index)
        texto = (index.data() or "").strip()
        if not texto:
            return
        colores = self._colores.get(texto)
        if colores is None:
            colores = TONOS_DE_ETIQUETA["gris"] if self.grande else color_de_etiqueta(texto)
        letra, fondo, borde = colores
        painter.save()
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setFont(self.fuente(option.font))
        medida = painter.fontMetrics()
        celda = option.rect
        ancho = min(medida.horizontalAdvance(texto.upper()) + (22 if self.grande else 20), celda.width() - 12)
        alto = medida.height() + (8 if self.grande else 6)
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


class CabeceraConColores(QHeaderView):
    """
    Los títulos de columna de siempre, con una barra del color del rubro abajo de
    los que son de un rubro (TOTALES y Resumen del Día de Reportes, 2026-11-19): así
    "PLAYSTATION 5" se reconoce por el mismo rosa que en el Ranking y el Historial.
    `tonos_por_columna`: {número de columna: tono}; las que no están quedan sin barra.
    """

    def __init__(self, tonos_por_columna: dict, parent=None):
        super().__init__(Qt.Horizontal, parent)
        self.tonos_por_columna = dict(tonos_por_columna)

    def paintSection(self, painter, rect, indice):
        super().paintSection(painter, rect, indice)
        tono = self.tonos_por_columna.get(indice)
        if tono:
            painter.save()
            painter.fillRect(QRect(rect.x() + 2, rect.bottom() - 3, rect.width() - 4, 4), color_fuerte(tono))
            painter.restore()


def poner_cabecera_con_colores(tabla, tonos_por_columna: dict) -> CabeceraConColores:
    """
    Cambia la cabecera de `tabla` por una CabeceraConColores con los mismos modos,
    anchos y alineación (llamarla con la tabla ya armada). La tabla pasa a llamarse
    "tablaConRubros": la hoja de estilos le pone a esos títulos una línea gris finita
    abajo, porque la azul de siempre se peleaba con las barras de color. El nombre
    va antes de crear la cabecera nueva: la hoja se lee al crearla, y con el nombre
    puesto después la cabecera se mediría con la línea vieja.
    """
    tabla.setObjectName("tablaConRubros")
    vieja = tabla.horizontalHeader()
    columnas = range(tabla.columnCount())
    modos = [vieja.sectionResizeMode(i) for i in columnas]
    anchos = [vieja.sectionSize(i) for i in columnas]
    nueva = CabeceraConColores(tonos_por_columna, tabla)
    nueva.setDefaultAlignment(vieja.defaultAlignment())
    nueva.setStretchLastSection(vieja.stretchLastSection())
    nueva.setHighlightSections(False)
    tabla.setHorizontalHeader(nueva)       # Qt borra la vieja
    for i, (modo, ancho) in zip(columnas, zip(modos, anchos)):
        nueva.setSectionResizeMode(i, modo)
        if modo != QHeaderView.Stretch:
            nueva.resizeSection(i, ancho)
    return nueva
