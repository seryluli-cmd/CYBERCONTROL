"""
pcs_botones_libres.py
=====================
Los botones de abajo del mosaico de Control de PCs (pedido del dueño,
2026-10-22; APAGAR el 2026-10-23), para hacer algo con todas las PCs prendidas
y libres de una vez. Todos abren una ventana con esas PCs ya marcadas, donde se
desmarcan las que no se quieren tocar (pedido del dueño, 2026-10-22):

- DESCONGELAR abre la ventana de Shadow Defender; desde ahí se descongelan o
  se congelan (con la clave de Shadow Defender, que se escribe cada vez).
- REINICIAR y APAGAR abren pcs_reiniciar_dialogo.

Son para cualquier operador (pedido del dueño, 2026-10-22: el mantenimiento
de las PCs lo suelen hacer los operadores). "Congelar / descongelar..." del
clic derecho sigue siendo solo del Admin.

El copo de nieve de DESCONGELAR y el símbolo de APAGAR se dibujan acá (pedido
del dueño, 2026-10-23): el emoji del cubito de hielo 🧊 salía como un
rectángulo en la PC del mostrador, porque su Windows no lo trae, y al de
apagar ⏻ le pasa lo mismo. Así se ven igual en cualquier PC.

Van debajo del fondo negro del mosaico, no adentro (pedido del dueño, mismo
día): ver PanelControlPcs._armar_interfaz.

Cuáles son las prendidas y libres lo decide pcs_libres_repo: las PCs con un
cliente nunca se tocan.
"""

import math

from PySide6.QtCore import QPointF, QRectF, QSize, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from control_pcs.repositories import pcs_libres_repo
from control_pcs.ui.pcs_congelado_dialogo import DialogoCongelado
from control_pcs.ui.pcs_reiniciar_dialogo import DialogoApagar, DialogoReiniciar
from ui.utils import aplicar_clase, manejar_errores, mostrar_info

# Los íconos se dibujan grandes y Qt los achica al tamaño del botón: así salen
# prolijos también en un monitor con la escala de Windows al 125 % o al 150 %.
_LADO_DIBUJO = 64
TAMANO_ICONO = QSize(18, 18)
COLOR_HIELO = "#8FD8FF"
COLOR_APAGAR = "#FF6B6B"


def _lienzo(color: str, grosor: float):
    """Un dibujo transparente de _LADO_DIBUJO x _LADO_DIBUJO, y su pincel ya
    listo para trazar con `color`."""
    dibujo = QPixmap(_LADO_DIBUJO, _LADO_DIBUJO)
    dibujo.fill(Qt.transparent)
    pincel = QPainter(dibujo)
    pincel.setRenderHint(QPainter.Antialiasing)
    pincel.setPen(QPen(QColor(color), grosor, Qt.SolidLine, Qt.RoundCap))
    return dibujo, pincel


def icono_copo_de_nieve() -> QIcon:
    """Un copo de nieve celeste: seis brazos, cada uno con dos pares de ramitas."""
    dibujo, pincel = _lienzo(COLOR_HIELO, 5)
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


class BotonesParaLasLibres(QWidget):
    def __init__(self, estados, parent=None):
        """`estados` devuelve lo último que leyó la pantalla de PCs
        (pcs_repo.estado_estaciones): las PCs, sin la PlayStation 5."""
        super().__init__(parent)
        self._estados = estados

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        # Mismas teclas en relieve que la barra de arriba.
        self.boton_descongelar = self._agregar_boton(layout, " Descongelar", self._descongelar,
                                                     icono_copo_de_nieve())
        self.boton_reiniciar = self._agregar_boton(layout, "🔄  Reiniciar", self._reiniciar)
        self.boton_apagar = self._agregar_boton(layout, " Apagar", self._apagar, icono_apagar())
        layout.addStretch()
        self.setLayout(layout)

    @staticmethod
    def _agregar_boton(layout, texto, accion, icono=None):
        boton = QPushButton(texto.upper())
        if icono is not None:
            boton.setIcon(icono)
            boton.setIconSize(TAMANO_ICONO)
        aplicar_clase(boton, "barra")
        boton.clicked.connect(accion)
        layout.addWidget(boton)
        return boton

    @manejar_errores
    def _descongelar(self):
        DialogoCongelado(None, self._estados(), self).exec()

    @manejar_errores
    def _reiniciar(self):
        self._abrir_si_hay_libres(DialogoReiniciar)

    @manejar_errores
    def _apagar(self):
        self._abrir_si_hay_libres(DialogoApagar)

    def _abrir_si_hay_libres(self, ventana):
        """Abre `ventana` (DialogoReiniciar o DialogoApagar) con las PCs
        prendidas y libres; si no hay ninguna, solo avisa."""
        estados = self._estados()
        if not pcs_libres_repo.prendidas_y_libres(estados):
            mostrar_info(self, ventana.TITULO,
                         f"No hay ninguna PC prendida y libre para {ventana.INFINITIVO}.")
            return
        ventana(estados, self).exec()
