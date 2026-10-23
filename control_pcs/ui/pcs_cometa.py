"""
pcs_cometa.py
=============
Un cometa celeste que da vueltas sin parar por el borde del fondo negro del
mosaico de Control de PCs (pedido del dueño, 2026-10-23: "una estela que va
recorriendo los bordes, tipo un cometa"). Es solo adorno: no muestra nada ni
se puede tocar.

Va en un widget transparente encima del fondo negro (`#marcoMosaico`), que lo
cubre entero y deja pasar los clics a los monitores de abajo. Sigue el borde
redondeado del fondo negro por adentro, en el margen que queda libre alrededor
de la leyenda y los monitores.

Para que no le cueste nada al mostrador, cada cuadro vuelve a pintar solo el
pedacito donde estaba y donde está el cometa (no todo el mosaico), y mientras
la pantalla de PCs no se ve no hace nada.
"""

from PySide6.QtCore import QEvent, QPointF, QRectF, Qt, QTimer
from PySide6.QtGui import QColor, QPainter, QPainterPath, QPen, QRadialGradient
from PySide6.QtWidgets import QWidget

# Una vuelta entera, y cada cuánto se mueve (unos 30 cuadros por segundo).
SEGUNDOS_POR_VUELTA = 6
MILISEGUNDOS_POR_CUADRO = 33
# Qué parte de la vuelta ocupa la cola, y en cuántos tramos se dibuja.
LARGO_COLA = 0.22
TRAMOS_COLA = 120
# La cola se dibuja en capas encimadas, cada una más corta, gruesa y clara (ver paintEvent).
CAPAS_COLA = 16
OPACIDAD_CAPA = 0.22
# A qué distancia del borde pasa y cómo redondea las esquinas: el fondo negro
# tiene border-radius 12 (hoja_de_estilos, "#marcoMosaico").
DISTANCIA_AL_BORDE = 6
RADIO_ESQUINAS = 7
GROSOR_CABEZA = 4.5
RADIO_BRILLO = 11

COLOR_CABEZA = QColor("#EAF4FF")   # casi blanco
COLOR_COLA = QColor("#4C8DFF")     # el azul de la barra de arriba


def _mezcla(desde: QColor, hasta: QColor, cuanto: float) -> QColor:
    """El color que está `cuanto` (0 a 1) del camino entre `desde` y `hasta`."""
    return QColor(
        round(desde.red() + (hasta.red() - desde.red()) * cuanto),
        round(desde.green() + (hasta.green() - desde.green()) * cuanto),
        round(desde.blue() + (hasta.blue() - desde.blue()) * cuanto),
    )


class CometaEnElBorde(QWidget):
    def __init__(self, marco: QWidget):
        """Se pone encima de `marco` (el fondo negro) y lo sigue si cambia de tamaño."""
        super().__init__(marco)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.avance = 0.0          # dónde va la cabeza: 0 a 1 de la vuelta
        self._camino = QPainterPath()
        self._zona_pintada = QRectF()
        marco.installEventFilter(self)
        self._acomodar()
        # Si el fondo negro ya estaba a la vista, un hijo nuevo no se muestra solo.
        self.show()

        self._timer = QTimer(self)
        self._timer.setInterval(MILISEGUNDOS_POR_CUADRO)
        self._timer.timeout.connect(self._avanzar)
        self._timer.start()

    def detener(self):
        """Lo deja quieto para siempre (al cerrarse la pantalla de PCs)."""
        self._timer.stop()

    def eventFilter(self, objeto, evento):
        if objeto is self.parent() and evento.type() == QEvent.Resize:
            self._acomodar()
        return False

    def _acomodar(self):
        """Lo estira al tamaño del fondo negro, lo deja encima de todo lo de
        adentro y vuelve a calcular el borde por donde pasa."""
        self.setGeometry(self.parent().rect())
        self.raise_()
        borde = QRectF(self.rect()).adjusted(DISTANCIA_AL_BORDE, DISTANCIA_AL_BORDE,
                                             -DISTANCIA_AL_BORDE, -DISTANCIA_AL_BORDE)
        self._camino = QPainterPath()
        self._camino.addRoundedRect(borde, RADIO_ESQUINAS, RADIO_ESQUINAS)
        self.update()

    def puntos(self) -> list:
        """Los puntos del cometa, de la cabeza a la punta de la cola."""
        if self._camino.isEmpty():
            return []
        # addRoundedRect da la vuelta como las agujas del reloj (en pantalla, con la
        # y para abajo): la cola queda atrás, en lo que ya recorrió.
        return [
            self._camino.pointAtPercent((self.avance - LARGO_COLA * tramo / TRAMOS_COLA) % 1.0)
            for tramo in range(TRAMOS_COLA + 1)
        ]

    def _zona_de(self, puntos) -> QRectF:
        """El rectángulo que ocupa el cometa, con lugar para el brillo de la cabeza."""
        if not puntos:
            return QRectF()
        xs = [punto.x() for punto in puntos]
        ys = [punto.y() for punto in puntos]
        zona = QRectF(QPointF(min(xs), min(ys)), QPointF(max(xs), max(ys)))
        return zona.adjusted(-RADIO_BRILLO - 2, -RADIO_BRILLO - 2, RADIO_BRILLO + 2, RADIO_BRILLO + 2)

    def _avanzar(self):
        if not self.isVisible():
            return  # la pantalla de PCs no se ve: no se gasta nada
        self.avance = (self.avance + MILISEGUNDOS_POR_CUADRO / 1000 / SEGUNDOS_POR_VUELTA) % 1.0
        zona_nueva = self._zona_de(self.puntos())
        # Se borra donde estaba y se pinta donde está: nada más.
        self.update(self._zona_pintada.united(zona_nueva).toAlignedRect())
        self._zona_pintada = zona_nueva

    def paintEvent(self, _evento):
        puntos = self.puntos()
        if not puntos:
            return
        pincel = QPainter(self)
        pincel.setRenderHint(QPainter.Antialiasing)
        # La cola: capas encimadas que salen todas de la cabeza, cada una más corta,
        # más gruesa y más clara que la anterior. Cerca de la cabeza se juntan todas
        # (gruesa, blanca y opaca) y en la punta queda solo la primera (finita, azul y
        # casi transparente). Cada capa es un solo trazo continuo: dibujada en tramos
        # sueltos, se notaban los cortes entre uno y otro.
        for capa in range(CAPAS_COLA):
            hasta = round(TRAMOS_COLA * (CAPAS_COLA - capa) / CAPAS_COLA)
            cerca = (capa + 1) / CAPAS_COLA          # la última capa es la de la cabeza
            trazo = QPainterPath(puntos[0])
            for punto in puntos[1:hasta + 1]:
                trazo.lineTo(punto)
            color = _mezcla(COLOR_COLA, COLOR_CABEZA, cerca ** 2)
            color.setAlphaF(OPACIDAD_CAPA)
            pincel.setPen(QPen(color, 1 + (GROSOR_CABEZA - 1) * cerca, Qt.SolidLine, Qt.FlatCap, Qt.RoundJoin))
            pincel.drawPath(trazo)
        # El brillo de la cabeza.
        brillo = QRadialGradient(puntos[0], RADIO_BRILLO)
        brillo.setColorAt(0.0, QColor(234, 244, 255, 235))
        brillo.setColorAt(0.3, QColor(120, 175, 255, 170))
        brillo.setColorAt(1.0, QColor(76, 141, 255, 0))
        pincel.setPen(Qt.NoPen)
        pincel.setBrush(brillo)
        pincel.drawEllipse(puntos[0], RADIO_BRILLO, RADIO_BRILLO)
        pincel.end()
