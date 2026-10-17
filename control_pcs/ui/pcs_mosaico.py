"""
pcs_mosaico.py
===============
El mosaico de equipos de "Control de PCs": un monitor dibujado por cada PC (y
uno para la PlayStation 5), con la pantalla pintada del color de su estado, un
dibujito encima (reloj si está en uso, el socio si la abrió un Miembro, un
aviso si hay que mirarla), las monedas si corre con un bono, y abajo el tiempo
que le queda y su nombre. Pedido del dueño (2026-10-16), con el aspecto de los
programas de cyber que ya conocía, respetando los colores de cada estado.

Este archivo solo DIBUJA: qué estado, color y dibujito le toca a cada equipo lo
decide `pcs_window.PanelControlPcs` y llega acá armado como una `Ficha`. Los
monitores se pintan con QPainter (no son imágenes): así cualquier color de
estado sirve sin tener que preparar un archivo por cada uno, y se ven nítidos
en cualquier pantalla.
"""

from dataclasses import dataclass, replace

from PySide6.QtCore import Qt, QSize, QRectF, QPointF
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QBrush, QLinearGradient, QFont
from PySide6.QtWidgets import (
    QListWidget, QListWidgetItem, QListView, QStyledItemDelegate, QStyle, QAbstractItemView,
    QWidget, QHBoxLayout, QLabel,
)

# Qué se dibuja sobre la pantalla del monitor.
DIBUJO_NINGUNO = ""
DIBUJO_RELOJ = "reloj"                   # sesión con tiempo corriendo
DIBUJO_SOCIO = "socio"                   # sesión abierta por un Miembro
DIBUJO_ALERTA = "alerta"                 # hay que mirarla ya (sin Cliente PC, tiempo agotado)
DIBUJO_CANDADO_ABIERTO = "candado"       # Cliente PC cerrado por un admin: está sin bloqueo

# Tamaño del dibujo del monitor: se dibuja siempre con las mismas medidas
# (marco de 92x64, ver _DibujanteDeEquipo.paint) y se achica o agranda con esta
# escala. El dueño lo pidió un 25% más chico (2026-10-16) para que entren más
# PCs a la vista; los textos de abajo NO se escalan, para que se sigan leyendo.
ESCALA_MONITOR = 0.75
# Alto del monitor sin escalar: margen de arriba + marco + pie.
_ALTO_MONITOR = 12 + 64 + 12

# Tamaño de cada casillero del mosaico (monitor + tiempo + nombre + aviso). El
# ancho tiene que alcanzar para "PLAYSTATION 5" sin cortarse.
ANCHO_CASILLERO = 108
ALTO_CASILLERO = int(_ALTO_MONITOR * ESCALA_MONITOR) + 54

# Cuántos equipos van en cada fila del mosaico: siempre los mismos, repartidos a
# lo ancho, en vez de "los que entren" (pedido del dueño, 2026-10-17: 8 arriba,
# 8 abajo, y así). Solo si la ventana es tan angosta que no entran 8 casilleros
# enteros, se pasa a la fila de abajo antes (para no cortar los nombres).
EQUIPOS_POR_FILA = 8

# Rol de Qt donde cada casillero guarda su Ficha y el color con que se pinta
# AHORA (que no siempre es el de la ficha: el parpadeo lo alterna).
_ROL_FICHA = Qt.UserRole
_ROL_COLOR = Qt.UserRole + 1

_COLOR_TEXTO = QColor("#F3F5F9")
_COLOR_TEXTO_SUAVE = QColor("#AEB5C2")
_COLOR_MARCO_MONITOR = QColor("#2B2F38")
_COLOR_BORDE_MONITOR = QColor("#0C0E12")
_COLOR_TRAZO_DIBUJO = QColor(18, 20, 24, 225)
_COLOR_SELECCION = QColor("#4F8EF7")


@dataclass(frozen=True)
class Ficha:
    """Todo lo que hace falta para dibujar un equipo en el mosaico."""
    clave: tuple          # identidad del equipo (ver pcs_window._clave_de_item)
    nombre: str
    estado: str           # texto completo del estado ("▶ En uso"), va en el cartelito
    restante: str         # tiempo que le queda, o "—"
    quien: str            # "Bono", el nombre del socio, o "—"
    color: QColor         # color de la pantalla según el estado
    en_alerta: bool = False
    dibujo: str = DIBUJO_NINGUNO
    con_bono: bool = False        # dibuja las monedas en la esquina
    es_consola: bool = False      # dibuja el joystick en la esquina
    aviso: str = ""               # renglón corto debajo del nombre (solo si hay algo que avisar)


class MosaicoDeEquipos(QListWidget):
    """
    La lista de equipos como mosaico (un QListWidget en modo íconos, así la
    selección, el teclado, el desplazamiento y el acomodo en filas según el
    ancho de la ventana los resuelve Qt). Cada casillero lo pinta
    `_DibujanteDeEquipo`.

    `mostrar()` se llama en cada refresco (cada 5s): si siguen siendo los
    mismos equipos en el mismo orden, actualiza los casilleros en su lugar en
    vez de borrarlos y volver a crearlos, así no parpadea todo ni se pierde
    hasta dónde se había bajado con la ruedita.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("mosaicoPcs")
        self.setViewMode(QListView.IconMode)
        self.setMovement(QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(True)
        self.setFlow(QListView.LeftToRight)
        self.setGridSize(QSize(ANCHO_CASILLERO, ALTO_CASILLERO))
        self.setUniformItemSizes(True)
        self.setSelectionMode(QAbstractItemView.SingleSelection)
        self.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.setVerticalScrollMode(QAbstractItemView.ScrollPerPixel)
        self.setDragEnabled(False)
        self.setFrameShape(QListWidget.NoFrame)
        self.setMouseTracking(True)
        self.setItemDelegate(_DibujanteDeEquipo(self))

    # --- acomodo en filas ------------------------------------------------

    def resizeEvent(self, evento):
        self._repartir_columnas()
        super().resizeEvent(evento)

    def _repartir_columnas(self):
        """Divide el ancho en EQUIPOS_POR_FILA columnas iguales: Qt pone en cada
        fila los casilleros que entran, así que con esta medida entran justo
        esos. El monitor se dibuja centrado en su columna."""
        # Qt acomoda las filas en el ancho SIN la barra de desplazamiento
        # vertical, aunque no esté a la vista (así no se rearma todo cuando
        # aparece), y cuenta como ocupado el último píxel de la derecha: si se
        # reparte el ancho entero, en algunos anchos entra uno menos por fila.
        barra = 0 if self.style().pixelMetric(QStyle.PM_ScrollView_ScrollBarOverlap, None, self) \
            else self.style().pixelMetric(QStyle.PM_ScrollBarExtent, None, self.verticalScrollBar())
        ancho_util = self.maximumViewportSize().width() - barra - 1
        ancho_columna = max(ANCHO_CASILLERO, ancho_util // EQUIPOS_POR_FILA)
        if self.gridSize().width() != ancho_columna:
            self.setGridSize(QSize(ancho_columna, ALTO_CASILLERO))

    # --- contenido -------------------------------------------------------

    def mostrar(self, fichas):
        """Deja en el mosaico exactamente estas fichas, en este orden."""
        claves_actuales = [self.ficha(fila).clave for fila in range(self.count())]
        if claves_actuales != [ficha.clave for ficha in fichas]:
            self.clear()
            for _ in fichas:
                casillero = QListWidgetItem()
                casillero.setSizeHint(QSize(ANCHO_CASILLERO, ALTO_CASILLERO))
                self.addItem(casillero)
        for fila, ficha in enumerate(fichas):
            self._poner_ficha(self.item(fila), ficha)

    def _poner_ficha(self, casillero, ficha):
        casillero.setText(ficha.nombre)  # para buscar tecleando el nombre
        casillero.setToolTip(f"{ficha.nombre}\n{ficha.estado}\nTiempo: {ficha.restante}\nQuién: {ficha.quien}")
        casillero.setData(_ROL_FICHA, ficha)
        casillero.setData(_ROL_COLOR, QColor(ficha.color))

    def ficha(self, fila) -> Ficha:
        return self.item(fila).data(_ROL_FICHA)

    def color(self, fila) -> QColor:
        """El color con que está pintada AHORA la pantalla de ese equipo."""
        return QColor(self.item(fila).data(_ROL_COLOR))

    def pintar(self, fila, color):
        """Cambia solo el color de la pantalla (lo usa el parpadeo)."""
        self.item(fila).setData(_ROL_COLOR, QColor(color))

    def cambiar_restante(self, fila, texto):
        """Cambia solo el tiempo que le queda (la cuenta regresiva de cada segundo)."""
        casillero = self.item(fila)
        ficha = casillero.data(_ROL_FICHA)
        nueva = replace(ficha, restante=texto)
        color_actual = casillero.data(_ROL_COLOR)
        self._poner_ficha(casillero, nueva)
        casillero.setData(_ROL_COLOR, color_actual)

    def fila_en(self, posicion) -> int:
        """La fila del equipo bajo ese punto (coordenadas del viewport), o -1."""
        casillero = self.itemAt(posicion)
        return self.row(casillero) if casillero is not None else -1

    def fila_elegida(self) -> int:
        elegidos = self.selectedItems()
        return self.row(elegidos[0]) if elegidos else -1

    def elegir(self, fila):
        """Selecciona ese equipo (o ninguno, con -1)."""
        if 0 <= fila < self.count():
            self.setCurrentRow(fila)
        else:
            self.clearSelection()


class _DibujanteDeEquipo(QStyledItemDelegate):
    """Pinta un casillero: monitor con la pantalla del color del estado, el
    dibujito y las insignias, y debajo tiempo, nombre y aviso."""

    def sizeHint(self, opcion, indice):
        return QSize(ANCHO_CASILLERO, ALTO_CASILLERO)

    def paint(self, pintor, opcion, indice):
        ficha = indice.data(_ROL_FICHA)
        if ficha is None:
            return
        color = QColor(indice.data(_ROL_COLOR))
        caja = QRectF(opcion.rect)

        pintor.save()
        pintor.setRenderHint(QPainter.Antialiasing)

        self._pintar_fondo_del_casillero(pintor, caja, opcion)

        # El monitor se dibuja con medidas fijas alrededor de x=0 y se escala
        # con ESCALA_MONITOR; los textos van después, sin escalar.
        pintor.save()
        pintor.translate(caja.center().x(), caja.top())
        pintor.scale(ESCALA_MONITOR, ESCALA_MONITOR)
        marco = QRectF(-46, 12, 92, 64)
        pantalla = marco.adjusted(4, 4, -4, -4)
        _pintar_monitor(pintor, marco, pantalla, color)

        centro = pantalla.center()
        if ficha.dibujo == DIBUJO_RELOJ:
            _pintar_reloj(pintor, centro, 15)
        elif ficha.dibujo == DIBUJO_SOCIO:
            _pintar_socio(pintor, centro, pantalla)
        elif ficha.dibujo == DIBUJO_ALERTA:
            _pintar_alerta(pintor, centro)
        elif ficha.dibujo == DIBUJO_CANDADO_ABIERTO:
            _pintar_candado_abierto(pintor, centro)

        if ficha.con_bono:
            _pintar_monedas(pintor, QPointF(marco.right() - 2, marco.top() + 2))
        if ficha.es_consola:
            _pintar_joystick(pintor, QPointF(marco.left() + 2, marco.top() + 2))
        pintor.restore()

        self._pintar_textos(pintor, caja, caja.top() + _ALTO_MONITOR * ESCALA_MONITOR, ficha)
        pintor.restore()

    @staticmethod
    def _pintar_fondo_del_casillero(pintor, caja, opcion):
        fondo = caja.adjusted(3, 3, -3, -3)
        if opcion.state & QStyle.State_Selected:
            pintor.setPen(QPen(_COLOR_SELECCION, 2))
            pintor.setBrush(QColor(79, 142, 247, 45))
            pintor.drawRoundedRect(fondo, 10, 10)
        elif opcion.state & QStyle.State_MouseOver:
            pintor.setPen(Qt.NoPen)
            pintor.setBrush(QColor(255, 255, 255, 18))
            pintor.drawRoundedRect(fondo, 10, 10)

    @staticmethod
    def _pintar_textos(pintor, caja, arriba, ficha):
        ancho = caja.width() - 10
        izquierda = caja.left() + 5

        fuente = QFont(pintor.font())
        fuente.setPixelSize(12)
        fuente.setBold(True)
        pintor.setFont(fuente)
        if ficha.restante and ficha.restante != "—":
            pintor.setPen(_COLOR_TEXTO)
            pintor.drawText(QRectF(izquierda, arriba, ancho, 16), Qt.AlignCenter, ficha.restante)

        pintor.setPen(_COLOR_TEXTO)
        nombre = pintor.fontMetrics().elidedText(ficha.nombre, Qt.ElideRight, int(ancho))
        pintor.drawText(QRectF(izquierda, arriba + 16, ancho, 16), Qt.AlignCenter, nombre)

        if ficha.aviso:
            fuente.setBold(False)
            fuente.setPixelSize(11)
            pintor.setFont(fuente)
            pintor.setPen(_COLOR_TEXTO_SUAVE)
            aviso = pintor.fontMetrics().elidedText(ficha.aviso, Qt.ElideRight, int(ancho))
            pintor.drawText(QRectF(izquierda, arriba + 32, ancho, 14), Qt.AlignCenter, aviso)


# ---------------------------------------------------------------------
# Las piezas del dibujo
# ---------------------------------------------------------------------

def _pintar_monitor(pintor, marco, pantalla, color):
    # Pie: cuello y base, detrás del marco.
    cx = marco.center().x()
    pintor.setPen(Qt.NoPen)
    pintor.setBrush(QColor("#3A3F4A"))
    pintor.drawRect(QRectF(cx - 7, marco.bottom() - 1, 14, 7))
    pintor.setBrush(QColor("#454B57"))
    pintor.drawRoundedRect(QRectF(cx - 24, marco.bottom() + 5, 48, 5), 2.5, 2.5)

    # Marco del monitor.
    pintor.setPen(QPen(_COLOR_BORDE_MONITOR, 1))
    pintor.setBrush(_COLOR_MARCO_MONITOR)
    pintor.drawRoundedRect(marco, 4, 4)

    # Pantalla: degradé del color del estado, más claro arriba.
    degrade = QLinearGradient(pantalla.topLeft(), pantalla.bottomLeft())
    degrade.setColorAt(0.0, color.lighter(135))
    degrade.setColorAt(0.55, color)
    degrade.setColorAt(1.0, color.darker(135))
    pintor.setPen(Qt.NoPen)
    pintor.setBrush(QBrush(degrade))
    pintor.drawRect(pantalla)

    # Brillo en diagonal, como un vidrio.
    brillo = QPainterPath()
    brillo.moveTo(pantalla.topLeft())
    brillo.lineTo(pantalla.right(), pantalla.top())
    brillo.lineTo(pantalla.right(), pantalla.top() + pantalla.height() * 0.18)
    brillo.cubicTo(
        pantalla.left() + pantalla.width() * 0.62, pantalla.top() + pantalla.height() * 0.30,
        pantalla.left() + pantalla.width() * 0.35, pantalla.top() + pantalla.height() * 0.62,
        pantalla.left(), pantalla.bottom() - pantalla.height() * 0.12,
    )
    brillo.closeSubpath()
    pintor.setBrush(QColor(255, 255, 255, 48))
    pintor.drawPath(brillo)


def _pintar_reloj(pintor, centro, radio):
    pintor.setPen(QPen(_COLOR_TRAZO_DIBUJO, 2.6))
    pintor.setBrush(QColor(0, 0, 0, 28))
    pintor.drawEllipse(centro, radio, radio)
    # Las 12 marcas de las horas.
    pintor.setPen(QPen(_COLOR_TRAZO_DIBUJO, 1.6, Qt.SolidLine, Qt.RoundCap))
    for hora in range(12):
        pintor.save()
        pintor.translate(centro)
        pintor.rotate(hora * 30)
        pintor.drawLine(QPointF(0, -radio + 3), QPointF(0, -radio + (6 if hora % 3 == 0 else 4.5)))
        pintor.restore()
    # Agujas: las diez en punto.
    pintor.setPen(QPen(_COLOR_TRAZO_DIBUJO, 2.4, Qt.SolidLine, Qt.RoundCap))
    pintor.drawLine(centro, centro + QPointF(0, -radio + 5))
    pintor.drawLine(centro, centro + QPointF(-radio * 0.45, -radio * 0.22))
    pintor.setBrush(_COLOR_TRAZO_DIBUJO)
    pintor.drawEllipse(centro, 1.8, 1.8)


def _pintar_socio(pintor, centro, pantalla):
    pintor.save()
    pintor.setClipRect(pantalla)
    pintor.setPen(Qt.NoPen)
    # Uno atrás (más claro) y uno adelante, como en el ícono de "usuarios".
    for desplazamiento, alfa in ((QPointF(8, -2), 120), (QPointF(-3, 0), 225)):
        base = centro + desplazamiento
        pintor.setBrush(QColor(18, 20, 24, alfa))
        pintor.drawEllipse(base + QPointF(0, -9), 7, 7.5)
        pintor.drawRoundedRect(QRectF(base.x() - 12, base.y() + 1, 24, 22), 11, 11)
    pintor.restore()


def _pintar_alerta(pintor, centro):
    triangulo = QPainterPath()
    triangulo.moveTo(centro + QPointF(0, -15))
    triangulo.lineTo(centro + QPointF(16, 13))
    triangulo.lineTo(centro + QPointF(-16, 13))
    triangulo.closeSubpath()
    pintor.setPen(QPen(_COLOR_TRAZO_DIBUJO, 2.4, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pintor.setBrush(QColor(255, 214, 10))
    pintor.drawPath(triangulo)
    pintor.setPen(QPen(_COLOR_TRAZO_DIBUJO, 3, Qt.SolidLine, Qt.RoundCap))
    pintor.drawLine(centro + QPointF(0, -6), centro + QPointF(0, 3))
    pintor.drawPoint(centro + QPointF(0, 8.5))


def _pintar_candado_abierto(pintor, centro):
    pintor.setPen(QPen(_COLOR_TRAZO_DIBUJO, 2.6, Qt.SolidLine, Qt.RoundCap))
    pintor.setBrush(Qt.NoBrush)
    # Arco abierto, corrido a la derecha.
    pintor.drawArc(QRectF(centro.x() - 2, centro.y() - 16, 16, 18), 0, 180 * 16)
    pintor.drawLine(centro + QPointF(14, -7), centro + QPointF(14, -2))
    pintor.setPen(Qt.NoPen)
    pintor.setBrush(_COLOR_TRAZO_DIBUJO)
    pintor.drawRoundedRect(QRectF(centro.x() - 11, centro.y() - 2, 20, 15), 3, 3)


def _pintar_monedas(pintor, esquina):
    """Pila de monedas en la esquina de arriba a la derecha (sesión con bono)."""
    pintor.setPen(QPen(QColor("#7A5A0C"), 1))
    for i in range(3):
        moneda = QRectF(esquina.x() - 11, esquina.y() - 4 - i * 4.5, 20, 8)
        degrade = QLinearGradient(moneda.topLeft(), moneda.bottomLeft())
        degrade.setColorAt(0, QColor("#FFE58A"))
        degrade.setColorAt(1, QColor("#D49A12"))
        pintor.setBrush(QBrush(degrade))
        pintor.drawEllipse(moneda)


def _pintar_joystick(pintor, esquina):
    """Joystick en la esquina de arriba a la izquierda (es la PlayStation 5)."""
    cuerpo = QPainterPath()
    cuerpo.addRoundedRect(QRectF(esquina.x() - 9, esquina.y() - 9, 26, 13), 6, 6)
    cuerpo.addEllipse(QRectF(esquina.x() - 10, esquina.y() - 5, 9, 11))
    cuerpo.addEllipse(QRectF(esquina.x() + 9, esquina.y() - 5, 9, 11))
    cuerpo.setFillRule(Qt.WindingFill)
    pintor.setPen(QPen(QColor("#0C0E12"), 1))
    pintor.setBrush(QColor("#EDEFF3"))
    pintor.drawPath(cuerpo.simplified())
    pintor.setPen(Qt.NoPen)
    pintor.setBrush(QColor("#2B2F38"))
    pintor.drawEllipse(QPointF(esquina.x() - 3, esquina.y() - 3), 1.8, 1.8)
    pintor.drawEllipse(QPointF(esquina.x() + 11, esquina.y() - 3), 1.8, 1.8)


# ---------------------------------------------------------------------
# Leyenda de colores
# ---------------------------------------------------------------------

class LeyendaDeColores(QWidget):
    """Fila de cuadraditos con qué quiere decir cada color, arriba del mosaico
    (sobre todo para quien recién empieza en el mostrador)."""

    def __init__(self, colores_y_textos, parent=None):
        super().__init__(parent)
        layout = QHBoxLayout()
        layout.setContentsMargins(4, 0, 4, 0)
        layout.setSpacing(14)
        for color, texto in colores_y_textos:
            muestra = QLabel()
            muestra.setFixedSize(12, 12)
            muestra.setStyleSheet(
                f"background-color: {QColor(color).name()}; border-radius: 3px; border: 1px solid #0C0E12;"
            )
            etiqueta = QLabel(texto)
            etiqueta.setObjectName("textoLeyendaMosaico")
            fila = QHBoxLayout()
            fila.setSpacing(6)
            fila.addWidget(muestra)
            fila.addWidget(etiqueta)
            layout.addLayout(fila)
        layout.addStretch()
        self.setLayout(layout)
