"""
dibujos_de_ventana.py
=====================
Los dibujitos de las ventanas de Miembros y de Actualizar el Cliente PC (diseños que eligió
el dueño el 2026-10-29): íconos de botón, el círculo con las iniciales de un socio y una
casilla de tildar. Se dibujan con QPainter, como los de `pcs_dibujos`, porque hay emojis que
el Windows del mostrador no trae y salen como un rectángulo.

Cada ícono se dibuja en una caja de 22 x 22 y se achica o agranda al tamaño pedido; el
pixmap sale al triple de tamaño para verse nítido con la escala de Windows al 125 o 150 %.
"""

import hashlib

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QFont, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QAbstractButton

_ESCALA = 3
_CAJA = 22


def _usuario(p):
    p.drawEllipse(QPointF(11, 7.5), 3.8, 3.8)
    p.drawArc(QRectF(3.5, 13, 15, 15), 0, 180 * 16)


def _mas(p):
    p.drawLine(QPointF(11, 4.5), QPointF(11, 17.5))
    p.drawLine(QPointF(4.5, 11), QPointF(17.5, 11))


def _lupa(p):
    p.drawEllipse(QPointF(9.5, 9.5), 5.5, 5.5)
    p.drawLine(QPointF(13.6, 13.6), QPointF(18.5, 18.5))


def _lapiz(p):
    p.save()
    p.translate(11, 11)
    p.rotate(45)
    p.drawRoundedRect(QRectF(-2.4, -8.5, 4.8, 12.5), 1, 1)
    p.drawPolyline([QPointF(-2.4, 4), QPointF(0, 8.5), QPointF(2.4, 4)])
    p.restore()


def _moneda(p):
    p.drawEllipse(QPointF(11, 11), 8, 8)
    letra = QFont("Segoe UI")
    letra.setPixelSize(11)
    letra.setBold(True)
    p.setFont(letra)
    p.drawText(QRectF(0, 0, _CAJA, 22.5), Qt.AlignCenter, "$")


def _reloj(p):
    p.drawEllipse(QPointF(11, 11), 8, 8)
    p.drawPolyline([QPointF(11, 6.5), QPointF(11, 11), QPointF(14.5, 13)])


def _prohibido(p):
    p.drawEllipse(QPointF(11, 11), 7.5, 7.5)
    p.drawLine(QPointF(5.7, 5.7), QPointF(16.3, 16.3))


def _subir(p):
    p.drawLine(QPointF(11, 15.5), QPointF(11, 5))
    p.drawPolyline([QPointF(7, 9), QPointF(11, 5), QPointF(15, 9)])
    p.drawLine(QPointF(5, 18.5), QPointF(17, 18.5))


def _flecha(p):
    p.drawLine(QPointF(5, 11), QPointF(17, 11))
    p.drawPolyline([QPointF(12, 6), QPointF(17, 11), QPointF(12, 16)])


_DIBUJOS = {"usuario": _usuario, "mas": _mas, "lupa": _lupa, "lapiz": _lapiz, "moneda": _moneda,
            "reloj": _reloj, "prohibido": _prohibido, "subir": _subir, "flecha": _flecha}


def pixmap_de(nombre: str, lado: int = 20, color: str = "#FFFFFF", grosor: float = 1.8) -> QPixmap:
    """El ícono `nombre` (usuario, mas, lupa, lapiz, moneda, reloj, prohibido, subir o flecha)
    como un trazo de `color` de `lado` x `lado` píxeles."""
    pixmap = QPixmap(lado * _ESCALA, lado * _ESCALA)
    pixmap.fill(Qt.transparent)
    pincel = QPainter(pixmap)
    pincel.setRenderHint(QPainter.Antialiasing)
    pincel.scale(_ESCALA * lado / _CAJA, _ESCALA * lado / _CAJA)
    pincel.setPen(QPen(QColor(color), grosor, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
    pincel.setBrush(Qt.NoBrush)
    _DIBUJOS[nombre](pincel)
    pincel.end()
    pixmap.setDevicePixelRatio(_ESCALA)
    return pixmap


def icono_de(nombre: str, lado: int = 16, color: str = "#3C4350", grosor: float = 1.8) -> QIcon:
    """Lo mismo que `pixmap_de`, para ponerle a un botón (`boton.setIconSize(QSize(lado, lado))`)."""
    return QIcon(pixmap_de(nombre, lado, color, grosor))


def poner_icono(boton, nombre: str, lado: int = 16, color: str = "#3C4350"):
    boton.setIcon(icono_de(nombre, lado, color))
    boton.setIconSize(QSize(lado, lado))


# Colores de fondo y de letra de los círculos con iniciales: uno por socio, siempre el mismo.
_COLORES_DE_AVATAR = (("#DCE8FB", "#1D4FA8"), ("#DCF3E1", "#1B6B3D"), ("#FFF0D9", "#9A5A00"),
                      ("#F3E1F7", "#7B2D8E"), ("#DDF3F7", "#13707F"), ("#FBE3E1", "#B3261E"))


def pixmap_de_avatar(nombre: str, lado: int = 24) -> QPixmap:
    """Un círculo con las dos primeras letras de `nombre`; el color sale del nombre, así un
    socio se ve siempre igual."""
    fondo, letra = _COLORES_DE_AVATAR[int(hashlib.md5(nombre.encode("utf-8")).hexdigest(), 16)
                                      % len(_COLORES_DE_AVATAR)]
    pixmap = QPixmap(lado * _ESCALA, lado * _ESCALA)
    pixmap.fill(Qt.transparent)
    pincel = QPainter(pixmap)
    pincel.setRenderHint(QPainter.Antialiasing)
    pincel.setPen(Qt.NoPen)
    pincel.setBrush(QColor(fondo))
    pincel.drawEllipse(QRectF(0, 0, lado * _ESCALA, lado * _ESCALA))
    pincel.setPen(QColor(letra))
    fuente = QFont("Segoe UI")
    fuente.setPixelSize(int(lado * _ESCALA * 0.40))
    fuente.setBold(True)
    pincel.setFont(fuente)
    pincel.drawText(QRectF(0, 0, lado * _ESCALA, lado * _ESCALA), Qt.AlignCenter, nombre[:2].upper())
    pincel.end()
    pixmap.setDevicePixelRatio(_ESCALA)
    return pixmap


class CasillaDibujada(QAbstractButton):
    """Una casilla de tildar con el tilde blanco sobre azul. La de la hoja de estilos del
    programa se ve como un cuadrado azul liso (no trae el tilde): acá, con 30 casillas
    marcadas juntas, se leería mal. Se usa como un QCheckBox (`isChecked`, `setChecked`,
    `toggled`) y se tilda con un clic."""

    def __init__(self, marcada: bool = False, lado: int = 18, parent=None):
        super().__init__(parent)
        self._lado = lado
        self.setCheckable(True)
        self.setChecked(marcada)
        self.setFixedSize(lado, lado)
        self.setCursor(Qt.PointingHandCursor)
        self.setFocusPolicy(Qt.NoFocus)
        self.setAttribute(Qt.WA_Hover)

    def paintEvent(self, _evento):
        pincel = QPainter(self)
        pincel.setRenderHint(QPainter.Antialiasing)
        lado = self._lado
        if self.isChecked():
            pincel.setPen(Qt.NoPen)
            pincel.setBrush(QColor("#3D7BFF" if self.underMouse() else "#2F6FED"))
            pincel.drawRoundedRect(QRectF(0.5, 0.5, lado - 1, lado - 1), 4.5, 4.5)
            pincel.setPen(QPen(QColor("#FFFFFF"), 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
            pincel.setBrush(Qt.NoBrush)
            pincel.drawPolyline([QPointF(lado * .25, lado * .52), QPointF(lado * .43, lado * .70),
                                 QPointF(lado * .76, lado * .30)])
        else:
            pincel.setPen(QPen(QColor("#2F6FED" if self.underMouse() else "#B7BFCC"), 1.5))
            pincel.setBrush(QColor("#FFFFFF"))
            pincel.drawRoundedRect(QRectF(0.75, 0.75, lado - 1.5, lado - 1.5), 4.5, 4.5)
