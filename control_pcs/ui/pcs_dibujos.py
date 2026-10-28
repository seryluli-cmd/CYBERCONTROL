"""
pcs_dibujos.py
==============
Los dibujitos de Control de PCs que no pueden ser emojis: el cubito de hielo 🧊
salía como un rectángulo en la PC del mostrador, porque su Windows no lo trae, y
al de apagar ⏻ le pasa lo mismo (pedido del dueño, 2026-10-23). Se dibujan con
QPainter y se ven igual en cualquier PC: el copo de nieve (DESCONGELAR y la
ventana de Congelar / descongelar PCs), el símbolo de APAGAR y las flechas rojas
de REINICIAR (pedido del dueño, 2026-10-24: antes era el 🔄 azul, el mismo que
quedó en el botón Operador de la barra de arriba).
"""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap, QPolygonF

# Los íconos se dibujan grandes y Qt los achica al tamaño del botón: así salen
# prolijos también en un monitor con la escala de Windows al 125 % o al 150 %.
_LADO_DIBUJO = 64
TAMANO_ICONO = QSize(18, 18)
COLOR_HIELO = "#8FD8FF"
COLOR_HIELO_FUERTE = "#2D9CDB"
COLOR_APAGAR = "#FF6B6B"
# El mismo rojo que APAGAR (pedido del dueño, 2026-10-24: era el 🔄 azul, igual al de Operador).
COLOR_REINICIAR = COLOR_APAGAR


def _lienzo(color: str, grosor: float):
    """Un dibujo transparente de _LADO_DIBUJO x _LADO_DIBUJO, y su pincel ya
    listo para trazar con `color`."""
    dibujo = QPixmap(_LADO_DIBUJO, _LADO_DIBUJO)
    dibujo.fill(Qt.transparent)
    pincel = QPainter(dibujo)
    pincel.setRenderHint(QPainter.Antialiasing)
    pincel.setPen(QPen(QColor(color), grosor, Qt.SolidLine, Qt.RoundCap))
    return dibujo, pincel


def icono_copo_de_nieve(color: str = COLOR_HIELO) -> QIcon:
    """Un copo de nieve celeste: seis brazos, cada uno con dos pares de ramitas.
    Sobre fondo blanco va mejor `COLOR_HIELO_FUERTE`."""
    dibujo, pincel = _lienzo(color, 5)
    centro = _LADO_DIBUJO / 2
    largo = _LADO_DIBUJO / 2 - 4

    def punto(distancia, angulo):
        return QPointF(centro + distancia * math.cos(angulo), centro - distancia * math.sin(angulo))

    for brazo in range(6):
        angulo = math.radians(90 + 60 * brazo)
        pincel.drawLine(punto(0, 0), punto(largo, angulo))
        for donde, ramita in ((0.45, 0.32), (0.72, 0.24)):
            base = punto(largo * donde, angulo)
            for lado in (-1, 1):
                direccion = angulo + lado * math.radians(45)
                pincel.drawLine(base, QPointF(base.x() + largo * ramita * math.cos(direccion),
                                              base.y() - largo * ramita * math.sin(direccion)))
    pincel.end()
    return QIcon(dibujo)


def icono_apagar() -> QIcon:
    """El símbolo de encendido de siempre: un círculo abierto arriba con una
    rayita que entra por la abertura."""
    dibujo, pincel = _lienzo(COLOR_APAGAR, 6)
    margen = 9
    circulo = QRectF(margen, margen + 2, _LADO_DIBUJO - 2 * margen, _LADO_DIBUJO - 2 * margen)
    # Qt mide los ángulos en dieciseisavos de grado, desde las 3 en contra del reloj.
    pincel.drawArc(circulo, 125 * 16, 290 * 16)
    pincel.drawLine(QPointF(_LADO_DIBUJO / 2, 5), QPointF(_LADO_DIBUJO / 2, _LADO_DIBUJO / 2))
    pincel.end()
    return QIcon(dibujo)


def icono_reiniciar() -> QIcon:
    """Dos flechas que giran en círculo, contra el reloj, cada una con su punta."""
    dibujo, pincel = _lienzo(COLOR_REINICIAR, 6)
    margen = 11
    centro, radio = _LADO_DIBUJO / 2, _LADO_DIBUJO / 2 - margen
    circulo = QRectF(margen, margen, 2 * radio, 2 * radio)
    pincel.setBrush(QColor(COLOR_REINICIAR))
    for desde in (25, 205):
        pincel.drawArc(circulo, desde * 16, 125 * 16)
        fin = math.radians(desde + 125)
        punta = QPointF(centro + radio * math.cos(fin), centro - radio * math.sin(fin))
        avance = QPointF(-math.sin(fin), -math.cos(fin))   # hacia donde gira
        afuera = QPointF(math.cos(fin), -math.sin(fin))
        trazo = pincel.pen()
        pincel.setPen(Qt.NoPen)
        pincel.drawPolygon(QPolygonF([punta + avance * 11, punta + afuera * 9, punta - afuera * 9]))
        pincel.setPen(trazo)
    pincel.end()
    return QIcon(dibujo)
