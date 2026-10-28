"""
pcs_fondo_vista.py
==================
La vista previa de "Fondos de pantalla" (`pcs_fondo_dialogo`): la imagen dentro de un
monitor dibujado, recortada como la pone cada PC (llena la pantalla sin deformarse, lo
que sobra queda afuera) y con un esbozo encima de lo que se ve en esa pantalla: el
nombre de la PC y el recuadro de ingreso en la de bloqueo, los íconos y la barra de
tareas en el escritorio. Así se entiende de un vistazo cuál es cuál (maqueta "B" que
eligió el dueño el 2026-10-28). Solo dibuja: no lee ni guarda nada.
"""

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap

from control_pcs.repositories import fondo_repo

# El gris clarito liso de la pantalla de bloqueo (COLOR_FONDO_BLOQUEADA en CLIENTE PC/cliente_pc.py,
# otro proyecto: si allá cambia, cambiarlo acá; hasta el 2026-10-19 era azul, #1B4B91), y el
# nombre de la PC encima (COLOR_TEXTO_NOMBRE). Es lo que se ve sin fondo, y donde una imagen
# con transparencia no tapa nada (ver `pcs_fondo_dialogo.preparar_jpeg`).
COLOR_BLOQUEO = "#D4D7DB"
COLOR_NOMBRE_SIN_FONDO = "#1F2933"
# El escritorio sin imagen elegida: cada PC deja el wallpaper que tenga Windows, que acá no
# se conoce; un gris neutro.
COLOR_ESCRITORIO_SIN_IMAGEN = "#3A4150"

ANCHO_PANTALLA = 440
ALTO_PANTALLA = ANCHO_PANTALLA * 9 // 16
MARCO = 10
PIE = 34
# Lo que mide el dibujo entero (monitor y pie): `vista_en_monitor` siempre da esto.
TAMANO_VISTA = (ANCHO_PANTALLA + 2 * MARCO, ALTO_PANTALLA + 2 * MARCO + PIE)


def _recortada(imagen: QPixmap, ancho: int, alto: int) -> QPixmap:
    """La imagen tapando justo `ancho` x `alto`, centrada y sin deformarse, como
    "Rellenar" de Windows y como la pantalla de bloqueo del Cliente PC."""
    grande = imagen.scaled(ancho, alto, Qt.AspectRatioMode.KeepAspectRatioByExpanding,
                           Qt.TransformationMode.SmoothTransformation)
    return grande.copy((grande.width() - ancho) // 2, (grande.height() - alto) // 2, ancho, alto)


def _esbozo_de_bloqueo(pintor: QPainter, pantalla: QRectF, con_imagen: bool):
    """El monitorcito y el nombre de la PC arriba a la izquierda (blanco sobre una imagen,
    oscuro sobre el gris liso), y el recuadro de ingreso abajo al medio (como lo dibuja
    CLIENTE PC/fondo_pantalla.py)."""
    x, y, a, h = pantalla.x(), pantalla.y(), pantalla.width(), pantalla.height()
    pintor.setPen(QColor("white" if con_imagen else COLOR_NOMBRE_SIN_FONDO))
    pintor.setBrush(Qt.BrushStyle.NoBrush)
    pintor.drawRoundedRect(QRectF(x + a * 0.03, y + h * 0.05, a * 0.045, h * 0.055), 1.5, 1.5)
    pintor.setFont(QFont("Segoe UI", 10, QFont.Weight.Bold))
    pintor.drawText(QRectF(x + a * 0.09, y + h * 0.03, a * 0.4, h * 0.1),
                    Qt.AlignmentFlag.AlignLeft | Qt.AlignmentFlag.AlignVCenter, "PC07")
    caja = QRectF(x + a * 0.36, y + h * 0.64, a * 0.28, h * 0.27)
    pintor.setPen(Qt.PenStyle.NoPen if con_imagen else QColor("#B8BEC7"))
    pintor.setBrush(QColor(200, 205, 215, 170) if con_imagen else QColor("white"))
    pintor.drawRoundedRect(caja, 5, 5)
    pintor.setPen(Qt.PenStyle.NoPen if con_imagen else QColor("#C9CED6"))
    pintor.setBrush(QColor(255, 255, 255, 235))
    for renglon in range(2):
        pintor.drawRoundedRect(QRectF(caja.x() + caja.width() * 0.1, caja.y() + caja.height() * (0.14 + renglon * 0.28),
                                      caja.width() * 0.8, caja.height() * 0.17), 2, 2)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor("#2F6FED"))
    pintor.drawRoundedRect(QRectF(caja.x() + caja.width() * 0.3, caja.y() + caja.height() * 0.71,
                                  caja.width() * 0.4, caja.height() * 0.17), 2, 2)


def _esbozo_de_escritorio(pintor: QPainter, pantalla: QRectF):
    """Unos íconos a la izquierda y la barra de tareas de Windows abajo."""
    x, y, a, h = pantalla.x(), pantalla.y(), pantalla.width(), pantalla.height()
    lado = h * 0.07
    pintor.setPen(Qt.PenStyle.NoPen)
    for numero in range(4):
        arriba = y + h * 0.05 + numero * lado * 1.6
        pintor.setBrush(QColor(255, 255, 255, 215))
        pintor.drawRoundedRect(QRectF(x + a * 0.02, arriba, lado, lado), 2, 2)
        pintor.setBrush(QColor(255, 255, 255, 150))
        pintor.drawRect(QRectF(x + a * 0.02 - lado * 0.1, arriba + lado * 1.1, lado * 1.2, lado * 0.16))
    barra = h * 0.075
    pintor.setBrush(QColor(20, 22, 30, 225))
    pintor.drawRect(QRectF(x, y + h - barra, a, barra))
    for lugar in range(-3, 4):
        izquierda = x + a / 2 + lugar * barra * 1.1 - barra * 0.3
        pintor.setBrush(QColor("#3B8BEB") if lugar == -3 else QColor(255, 255, 255, 190))
        pintor.drawRoundedRect(QRectF(izquierda, y + h - barra * 0.78, barra * 0.6, barra * 0.6), 1.5, 1.5)


def vista_en_monitor(datos, cual: str) -> QPixmap:
    """El monitor con ese fondo (`datos`: los bytes del JPEG, o None si no hay) y el
    esbozo de su pantalla encima."""
    imagen = QPixmap()
    if datos:
        imagen.loadFromData(datos)
    lienzo = QPixmap(*TAMANO_VISTA)
    lienzo.fill(Qt.GlobalColor.transparent)
    pintor = QPainter(lienzo)
    pintor.setRenderHint(QPainter.RenderHint.Antialiasing)
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor("#1C1F26"))
    pintor.drawRoundedRect(QRectF(0, 0, ANCHO_PANTALLA + 2 * MARCO, ALTO_PANTALLA + 2 * MARCO), 10, 10)
    pantalla = QRectF(MARCO, MARCO, ANCHO_PANTALLA, ALTO_PANTALLA)
    if imagen.isNull():
        liso = COLOR_BLOQUEO if cual == fondo_repo.BLOQUEO else COLOR_ESCRITORIO_SIN_IMAGEN
        pintor.fillRect(pantalla, QColor(liso))
    else:
        pintor.drawPixmap(QPointF(MARCO, MARCO), _recortada(imagen, ANCHO_PANTALLA, ALTO_PANTALLA))
    if cual == fondo_repo.BLOQUEO:
        _esbozo_de_bloqueo(pintor, pantalla, con_imagen=not imagen.isNull())
    else:
        _esbozo_de_escritorio(pintor, pantalla)
    # El pie del monitor.
    centro = (ANCHO_PANTALLA + 2 * MARCO) / 2
    pintor.setPen(Qt.PenStyle.NoPen)
    pintor.setBrush(QColor("#2A2E37"))
    pintor.drawRect(QRectF(centro - 18, ALTO_PANTALLA + 2 * MARCO, 36, PIE - 8))
    pintor.drawRoundedRect(QRectF(centro - 70, ALTO_PANTALLA + 2 * MARCO + PIE - 10, 140, 10), 4, 4)
    pintor.end()
    return lienzo
