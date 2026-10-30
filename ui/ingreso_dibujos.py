"""
ingreso_dibujos.py
==================
Los dibujos de la pantalla de ingreso con el diseño "Portal" (la maqueta D que
eligió el dueño el 2026-10-30 entre cinco, en PROPUESTA_PANTALLA_INGRESO): el
joystick en el centro de anillos de neón que giran, con estrellas que salen hacia
afuera, sobre un fondo casi negro. Solo es adorno: ui/login_window.py arma los
campos encima y decide cada cuánto se redibuja.

Todo se dibuja con QPainter (como el cometa del mosaico): hay emojis que el
Windows del mostrador no trae, y una imagen fija no se podría mover.
"""

import math
import random

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QBrush, QColor, QLinearGradient, QPainter, QPen, QPixmap,
                           QRadialGradient)
from PySide6.QtWidgets import QLabel

# Los colores del ícono del joystick (assets/icono.svg).
CIAN = "#22D3EE"
AZUL = "#4C8DFF"
VIOLETA = "#A855F7"

# Una vuelta de la animación: los anillos y las estrellas vuelven al mismo lugar.
SEGUNDOS_POR_VUELTA = 4.0
CANTIDAD_DE_ESTRELLAS = 170
# Hasta dónde llegan las estrellas: debajo de esa altura se apagan, para no
# pasar por encima del nombre, la clave y ENTRAR.
ALTO_DE_LAS_ESTRELLAS = 400
LADO_DEL_ICONO = 112

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
_MESES = ("enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto",
          "septiembre", "octubre", "noviembre", "diciembre")


def hora_y_fecha(momento) -> str:
    """El renglón de abajo de la pantalla: "23:41   ·   jueves 30 de octubre".
    En castellano siempre, sin depender del idioma de Windows."""
    return (f"{momento:%H:%M}   ·   {_DIAS[momento.weekday()]} {momento.day} "
            f"de {_MESES[momento.month - 1]}")


def _color(nombre: str, alfa: float) -> QColor:
    color = QColor(nombre)
    color.setAlpha(int(max(0, min(255, alfa))))
    return color


def _lapiz(nombre: str, ancho: float, alfa: float, punta=Qt.RoundCap) -> QPen:
    lapiz = QPen(_color(nombre, alfa), ancho)
    lapiz.setCapStyle(punta)
    return lapiz


class TextoConDegradado(QLabel):
    """Una etiqueta común (su texto es el de siempre, las pruebas lo buscan) que se
    pinta con un degradado de colores de izquierda a derecha. La letra la pone la
    hoja de estilos, por objectName."""

    def __init__(self, texto: str, colores):
        super().__init__(texto)
        self._colores = colores
        self.setAlignment(Qt.AlignCenter)

    def paintEvent(self, _evento):
        pintor = QPainter(self)
        pintor.setRenderHint(QPainter.TextAntialiasing)
        pintor.setFont(self.font())
        caja = QRectF(self.contentsRect())
        ancho = pintor.fontMetrics().horizontalAdvance(self.text())
        izquierda = caja.center().x() - ancho / 2
        degradado = QLinearGradient(izquierda, 0, izquierda + ancho, 0)
        for i, color in enumerate(self._colores):
            degradado.setColorAt(i / (len(self._colores) - 1), QColor(color))
        pintor.setPen(QPen(QBrush(degradado), 1))
        pintor.drawText(caja, int(self.alignment()), self.text())
        pintor.end()


class Portal:
    """El fondo animado. `pintar(pintor, segundos)` dibuja el cuadro de ese momento;
    lo que no se mueve (el fondo con su luz) se dibuja una sola vez y se guarda."""

    def __init__(self, ancho: int, alto: int, centro: QPointF, icono: QPixmap):
        self._ancho, self._alto = ancho, alto
        self._centro = centro
        self._icono = icono
        self._fondo = None
        # Siempre las mismas estrellas (semilla fija): ángulo, dónde arranca, cuántas
        # vueltas da en SEGUNDOS_POR_VUELTA (1 o 2, para que la vuelta cierre justa) y grosor.
        azar = random.Random(3)
        self._estrellas = [(azar.uniform(0, 2 * math.pi), azar.uniform(0, 1), azar.choice((1, 1, 2)),
                            azar.uniform(0.6, 1.6)) for _ in range(CANTIDAD_DE_ESTRELLAS)]

    def _fondo_fijo(self, escala: float) -> QPixmap:
        if self._fondo is None or self._fondo.devicePixelRatio() != escala:
            self._fondo = QPixmap(int(self._ancho * escala), int(self._alto * escala))
            self._fondo.setDevicePixelRatio(escala)
            pintor = QPainter(self._fondo)
            luz = QRadialGradient(self._centro, 700)
            luz.setColorAt(0, QColor("#0E1B3D"))
            luz.setColorAt(0.5, QColor("#060B1C"))
            luz.setColorAt(1, QColor("#020309"))
            pintor.fillRect(QRectF(0, 0, self._ancho, self._alto), luz)
            pintor.end()
        return self._fondo

    def pintar(self, pintor: QPainter, segundos: float, escala: float = 1.0):
        pintor.setRenderHint(QPainter.Antialiasing)
        pintor.setRenderHint(QPainter.SmoothPixmapTransform)
        pintor.drawPixmap(0, 0, self._fondo_fijo(escala))
        vuelta = (segundos / SEGUNDOS_POR_VUELTA) % 1.0
        self._pintar_estrellas(pintor, vuelta)
        self._pintar_anillos(pintor, vuelta * 360)
        if not self._icono.isNull():
            lado = self._icono.width() / self._icono.devicePixelRatio()
            pintor.drawPixmap(QPointF(self._centro.x() - lado / 2, self._centro.y() - lado / 2), self._icono)

    def _pintar_estrellas(self, pintor, vuelta):
        c = self._centro
        maximo = 640
        for angulo, arranque, vueltas, grosor in self._estrellas:
            recorrido = (arranque + vueltas * vuelta) % 1.0
            # Salen despacio del centro y aceleran hacia afuera, como al entrar en un salto.
            radio = 30 + recorrido ** 1.8 * maximo
            x, y = c.x() + math.cos(angulo) * radio, c.y() + math.sin(angulo) * radio
            alfa = 255 * min(1, recorrido * 2.2) * (1 - max(0, recorrido - 0.85) / 0.15)
            alfa *= max(0.0, min(1.0, (ALTO_DE_LAS_ESTRELLAS - y) / 80))
            if alfa <= 0:
                continue
            atras = 30 + max(0.0, recorrido - 0.02) ** 1.8 * maximo
            pintor.setPen(_lapiz("#CFEFFF", grosor * (0.5 + recorrido), alfa * 0.9))
            pintor.drawLine(QPointF(x, y), QPointF(c.x() + math.cos(angulo) * atras,
                                                   c.y() + math.sin(angulo) * atras))

    def _pintar_anillos(self, pintor, giro):
        c = self._centro
        nucleo = QRadialGradient(c, 190)
        nucleo.setColorAt(0, _color(AZUL, 120))
        nucleo.setColorAt(0.45, _color("#2563EB", 50))
        nucleo.setColorAt(1, _color("#000000", 0))
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(nucleo)
        pintor.drawEllipse(c, 190, 190)

        # Tres anillos de arcos que giran a distinta velocidad y en distinto sentido.
        # Cada arco se pinta tres veces, de ancho y transparente a fino y fuerte: el brillo del neón.
        # Con 3, 2 y 4 arcos parejos, una vuelta de la animación los deja donde estaban.
        for radio, cantidad, largo, angulo, color, ancho in (
                (150, 3, 70, giro, CIAN, 3), (128, 2, 120, -giro * 0.5, VIOLETA, 2.5),
                (104, 4, 40, giro + 20, AZUL, 4)):
            caja = QRectF(c.x() - radio, c.y() - radio, radio * 2, radio * 2)
            for i in range(cantidad):
                inicio = angulo + i * 360 / cantidad
                for factor, alfa in ((4.5, 23), (2.2, 69), (1, 230)):
                    pintor.setPen(_lapiz(color, ancho * factor, alfa, Qt.FlatCap))
                    pintor.drawArc(caja, int(inicio * 16), int(largo * 16))

        # El aro fino de afuera, con sus marcas, gira despacio.
        pintor.setPen(_lapiz("#9CC9FF", 1, 70))
        pintor.setBrush(Qt.NoBrush)
        pintor.drawEllipse(c, 170, 170)
        for i in range(60):
            angulo = math.radians(i * 6 - giro * 0.25)
            larga = i % 5 == 0
            pintor.setPen(_lapiz("#9CC9FF", 1, 120 if larga else 50))
            hasta = 178 if larga else 174
            pintor.drawLine(QPointF(c.x() + math.cos(angulo) * 170, c.y() + math.sin(angulo) * 170),
                            QPointF(c.x() + math.cos(angulo) * hasta, c.y() + math.sin(angulo) * hasta))

        # Un disco oscuro detrás del joystick, para que se destaque sobre la luz.
        disco = QRadialGradient(c, 84)
        disco.setColorAt(0, _color("#0B1226", 255))
        disco.setColorAt(0.8, _color("#0B1226", 240))
        disco.setColorAt(1, _color("#0B1226", 0))
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(disco)
        pintor.drawEllipse(c, 84, 84)
