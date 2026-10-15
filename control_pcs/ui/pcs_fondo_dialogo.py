"""
pcs_fondo_dialogo.py
====================
"Fondo de pantalla de las PCs...": el Admin elige la imagen que se ve detrás del
cartel de la pantalla de bloqueo de cada PC cliente. Se abre desde Gestionar
Estaciones (Configuración ADMIN, exclusiva de ADMIN). La imagen se guarda con
`fondo_repo` y cada Cliente PC la pide solo: al arrancar, y de nuevo si cambia
mientras está prendido (ver `servidor_red.py`, `GET /fondo`).

Acá está la parte que necesita Qt: abrir un PNG o JPG cualquiera (con la
orientación correcta de las fotos de celular), achicarlo y pasarlo a JPEG
(`preparar_jpeg`). Las reglas -tamaño máximo, calidad, peso- son de `fondo_repo`.
"""

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter, QPixmap
from PySide6.QtWidgets import QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from control_pcs.repositories import fondo_repo
from ui.utils import aplicar_clase, confirmar, manejar_errores, mostrar_info, sin_boton_por_defecto

# El azul liso de la pantalla de bloqueo (COLOR_FONDO_BLOQUEADA en CLIENTE PC/cliente_pc.py,
# otro proyecto: si allá cambia, cambiarlo acá). Es lo que se ve donde una imagen con
# transparencia no tapa nada, igual que sin fondo, y detrás de la vista previa.
COLOR_BLOQUEO = "#1B4B91"

# Calidades JPEG que se prueban, de la mejor a la peor, hasta que entre en el peso máximo.
# Una foto muy "ruidosa" (césped, arena, mucho detalle fino) puede pasarse con la primera.
CALIDADES_A_PROBAR = (fondo_repo.CALIDAD_JPEG, 70, 55, 40)

FILTRO_IMAGENES = "Imágenes (*.jpg *.jpeg *.png *.bmp *.webp *.gif);;Todos los archivos (*)"

VISTA_ANCHO = 480
VISTA_ALTO = 270


def _sobre_el_azul(imagen: QImage) -> QImage:
    """`imagen` con sus transparencias rellenas con el azul de la pantalla de
    bloqueo: un JPEG no tiene transparencia, y sin esto lo transparente saldría negro."""
    fondo = QImage(imagen.size(), QImage.Format.Format_RGB32)
    fondo.fill(QColor(COLOR_BLOQUEO))
    pintor = QPainter(fondo)
    pintor.drawImage(0, 0, imagen)
    pintor.end()
    return fondo


def _a_jpeg(imagen: QImage, calidad: int) -> bytes:
    buffer = QBuffer()
    buffer.open(QIODevice.OpenModeFlag.WriteOnly)
    if not imagen.save(buffer, "JPEG", calidad):
        raise ValueError("No se pudo preparar la imagen.")
    return bytes(buffer.data())


def preparar_jpeg(ruta: str) -> bytes:
    """Abre la imagen de `ruta` y la deja lista para `fondo_repo.guardar_jpeg`: entra en
    ANCHO_MAXIMO x ALTO_MAXIMO sin deformarse (una más chica no se agranda: la PC cliente
    la ajusta a su pantalla), sin transparencias y como JPEG que entre en el peso máximo.
    Levanta ValueError con un mensaje para mostrarle a la persona."""
    lector = QImageReader(ruta)
    lector.setAutoTransform(True)  # las fotos de celular traen la orientación aparte: se respeta
    imagen = lector.read()
    if imagen.isNull():
        raise ValueError("No se pudo abrir esa imagen. Probá con un archivo JPG o PNG.")
    if imagen.width() > fondo_repo.ANCHO_MAXIMO or imagen.height() > fondo_repo.ALTO_MAXIMO:
        imagen = imagen.scaled(
            fondo_repo.ANCHO_MAXIMO, fondo_repo.ALTO_MAXIMO,
            Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        )
    if imagen.hasAlphaChannel():
        imagen = _sobre_el_azul(imagen)
    for calidad in CALIDADES_A_PROBAR:
        datos = _a_jpeg(imagen, calidad)
        if len(datos) <= fondo_repo.TAMANO_MAXIMO_BYTES:
            return datos
    raise ValueError("La imagen pesa demasiado aun comprimida al máximo. Probá con otra más simple.")


class DialogoFondoPantalla(QDialog):
    """Vista previa del fondo actual y botones para elegir otra imagen o quitarlo."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fondo de pantalla de las PCs")
        self.resize(540, 480)
        self._armar_interfaz()
        self._mostrar_fondo_actual()

    def _armar_interfaz(self):
        self.vista = QLabel()
        self.vista.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.vista.setFixedSize(VISTA_ANCHO, VISTA_ALTO)
        self.vista.setStyleSheet(f"background: {COLOR_BLOQUEO}; color: white;")

        self.detalle = QLabel()
        self.detalle.setAlignment(Qt.AlignmentFlag.AlignCenter)

        nota = QLabel(
            "Es la imagen que se ve detrás del cartel de bloqueo de cada PC. Las PCs la "
            "piden al arrancar y, si la cambiás, las que estén prendidas la toman solas en "
            "unos segundos. Se ve mejor una imagen apaisada (16:9): si la pantalla de una "
            "PC tiene otra proporción, se recorta lo que sobre. El nombre de la PC, las "
            "instrucciones y el cuadro de ingreso se dibujan encima."
        )
        nota.setWordWrap(True)

        boton_elegir = QPushButton("Elegir imagen...")
        aplicar_clase(boton_elegir, "primario")
        boton_elegir.clicked.connect(self._elegir)
        self.boton_quitar = QPushButton("Quitar fondo")
        aplicar_clase(self.boton_quitar, "peligro")
        self.boton_quitar.clicked.connect(self._quitar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        fila_botones = QHBoxLayout()
        fila_botones.addWidget(boton_elegir)
        fila_botones.addWidget(self.boton_quitar)

        layout = QVBoxLayout()
        layout.addWidget(self.vista, alignment=Qt.AlignmentFlag.AlignCenter)
        layout.addWidget(self.detalle)
        layout.addWidget(nota)
        layout.addLayout(fila_botones)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _mostrar_fondo_actual(self):
        fondo = fondo_repo.obtener()
        if fondo is None:
            self.vista.setPixmap(QPixmap())
            self.vista.setText("Sin fondo: las PCs muestran el azul de siempre.")
            self.detalle.setText("")
            self.boton_quitar.setEnabled(False)
            return
        datos, _version = fondo
        pixmap = QPixmap()
        pixmap.loadFromData(datos)
        self.vista.setPixmap(pixmap.scaled(
            VISTA_ANCHO, VISTA_ALTO, Qt.AspectRatioMode.KeepAspectRatio, Qt.TransformationMode.SmoothTransformation,
        ))
        self.detalle.setText(f"Fondo actual: {pixmap.width()} x {pixmap.height()} px, {len(datos) // 1024} KB")
        self.boton_quitar.setEnabled(True)

    @manejar_errores
    def _elegir(self):
        ruta, _filtro = QFileDialog.getOpenFileName(self, "Elegir la imagen de fondo", "", FILTRO_IMAGENES)
        if not ruta:
            return
        fondo_repo.guardar_jpeg(preparar_jpeg(ruta))
        self._mostrar_fondo_actual()
        mostrar_info(
            self, "Listo",
            "Fondo guardado. Las PCs que estén prendidas lo toman solas en unos segundos; "
            "las que arranquen después lo piden al arrancar."
        )

    @manejar_errores
    def _quitar(self):
        if not confirmar(self, "Quitar el fondo", "¿Quitar el fondo? Las PCs vuelven al azul de siempre."):
            return
        fondo_repo.quitar()
        self._mostrar_fondo_actual()
