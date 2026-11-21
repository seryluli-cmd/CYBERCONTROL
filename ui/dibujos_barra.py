"""
ui/dibujos_barra.py
===================
Los dibujitos de la barra de arriba que van dibujados con QPainter en vez de emoji.

El de MIEMBROS (pedido del dueño, 2026-11-21: "quiero cambiar el iconito por unos como el
del Messenger que sean azules"; eligió la maqueta B entre tres): dos muñequitos azules con
brillo, el de atrás más clarito y un poco más chico. Va dibujado y no como emoji porque el
emoji de "dos personas", en el Windows del mostrador, salía como tres caras sueltas (por eso,
desde el 2026-10-18 hasta este cambio, el botón tuvo una sola carita amarilla, 🧑).

El dibujo es propio: cabeza redonda y cuerpo de frijol con degradé, un borde finito y un brillo
blanco, como los íconos de esa época (no es el logo del Messenger). Se dibuja a cuatro veces el
tamaño y Qt lo achica, así se ve nítido con Windows al 100, 125 o 150 %.
"""

from PySide6.QtCore import QPointF, QSize, Qt
from PySide6.QtGui import QBrush, QColor, QIcon, QLinearGradient, QPainter, QPainterPath, QPen, QPixmap, \
    QRadialGradient

_ESCALA = 4

# El tamaño del dibujito de MIEMBROS en la barra (el de la maqueta que eligió el dueño): más
# grande que un emoji dentro del texto, que mide lo que la letra (13 px), porque son dos muñequitos.
LADO_ICONO_MIEMBROS = 26

# (claro arriba, oscuro abajo, borde): el de adelante en el azul de la barra (#2F6FED), el de atrás
# más clarito para que se distingan sin otro color.
_AZUL_ADELANTE = ("#9CC8FF", "#1D5BD8", "#123E9A")
_AZUL_ATRAS = ("#CFE2FF", "#5E9BFF", "#2D63C8")


def _cuerpo(cx: float, base: float, ancho: float, alto: float) -> QPainterPath:
    """Los hombros y el cuerpo redondeados, como un frijol cortado abajo."""
    camino = QPainterPath()
    izquierda, derecha, arriba = cx - ancho / 2, cx + ancho / 2, base - alto
    camino.moveTo(izquierda, base)
    camino.cubicTo(izquierda, arriba + alto * 0.25, cx - ancho * 0.3, arriba, cx, arriba)
    camino.cubicTo(cx + ancho * 0.3, arriba, derecha, arriba + alto * 0.25, derecha, base)
    camino.quadTo(cx, base + alto * 0.22, izquierda, base)
    return camino


def _munequito(pintor: QPainter, cx: float, cy: float, tam: float, colores: tuple):
    """Un muñequito de `tam` de alto centrado en (cx, cy): cabeza y cuerpo con degradé, borde y brillo."""
    claro, oscuro, borde = colores
    radio = tam * 0.21
    cabeza = QPointF(cx, cy - tam * 0.2)
    cuerpo = _cuerpo(cx, cy + tam * 0.42, tam * 0.78, tam * 0.36)
    pintor.setPen(QPen(QColor(borde), tam * 0.045))

    caja = cuerpo.boundingRect()
    degradado = QLinearGradient(caja.topLeft(), caja.bottomLeft())
    degradado.setColorAt(0, QColor(claro))
    degradado.setColorAt(1, QColor(oscuro))
    pintor.setBrush(QBrush(degradado))
    pintor.drawPath(cuerpo)

    degradado = QRadialGradient(cabeza + QPointF(-radio * 0.35, -radio * 0.35), radio * 1.4)
    degradado.setColorAt(0, QColor(claro))
    degradado.setColorAt(1, QColor(oscuro))
    pintor.setBrush(QBrush(degradado))
    pintor.drawEllipse(cabeza, radio, radio)

    # El brillo: una manchita blanca arriba a la izquierda de la cabeza y otra más suave en el cuerpo.
    pintor.setPen(Qt.NoPen)
    pintor.setBrush(QColor(255, 255, 255, 150))
    pintor.drawEllipse(cabeza + QPointF(-radio * 0.3, -radio * 0.4), radio * 0.45, radio * 0.3)
    pintor.setBrush(QColor(255, 255, 255, 70))
    pintor.drawEllipse(QPointF(caja.center().x() - caja.width() * 0.15, caja.top() + caja.height() * 0.32),
                       caja.width() * 0.22, caja.height() * 0.16)


def pixmap_miembros(lado: int = LADO_ICONO_MIEMBROS) -> QPixmap:
    """Los dos muñequitos azules de MIEMBROS en un cuadrado de `lado` x `lado` píxeles."""
    pixmap = QPixmap(lado * _ESCALA, lado * _ESCALA)
    pixmap.fill(Qt.transparent)
    pintor = QPainter(pixmap)
    pintor.setRenderHint(QPainter.Antialiasing)
    pintor.scale(_ESCALA, _ESCALA)
    # Primero el de atrás (arriba a la derecha), después el de adelante, que lo tapa en parte.
    _munequito(pintor, lado * 0.64, lado * 0.42, lado * 0.82, _AZUL_ATRAS)
    _munequito(pintor, lado * 0.40, lado * 0.50, lado * 0.92, _AZUL_ADELANTE)
    pintor.end()
    pixmap.setDevicePixelRatio(_ESCALA)
    return pixmap


def icono_miembros(lado: int = LADO_ICONO_MIEMBROS) -> tuple:
    """El dibujito de MIEMBROS para ponerle al botón: (QIcon, QSize), como `ui.utils.icono_de_emoji`."""
    return QIcon(pixmap_miembros(lado)), QSize(lado, lado)
