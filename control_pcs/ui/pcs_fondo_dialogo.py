"""
pcs_fondo_dialogo.py
====================
"Fondos de pantalla" de las PCs clientes: el Admin elige las dos imágenes que se ven en
cada PC. Se abre desde Gestionar Estaciones (Configuración ADMIN). Con el diseño de la
maqueta "B" que eligió el dueño el 2026-10-28 (las piezas de ui/piezas_ventana.py): lado
a lado, la pantalla de bloqueo (detrás del nombre de la PC y del recuadro de ingreso) y
el escritorio de Windows (el wallpaper que ve el cliente mientras juega, pedido ese mismo
día), cada una con su vista previa (`pcs_fondo_vista`), "Elegir imagen..." y "Quitar",
y abajo "Usar la misma imagen en los dos".

Las imágenes se guardan con `fondo_repo` y cada Cliente PC las pide solo: al arrancar, y
de nuevo si cambian mientras está prendido (ver `servidor_red.py`, `GET /fondo` y
`GET /escritorio`). El wallpaper lo pone el Cliente PC desde la V2.1, con la PC libre.

Acá está la parte que necesita Qt: abrir un PNG o JPG cualquiera (con la orientación
correcta de las fotos de celular), achicarlo y pasarlo a JPEG (`preparar_jpeg`). Las
reglas -tamaño máximo, calidad, peso- son de `fondo_repo`.
"""

from PySide6.QtCore import QBuffer, QIODevice, Qt
from PySide6.QtGui import QColor, QImage, QImageReader, QPainter
from PySide6.QtWidgets import QDialog, QFileDialog, QFrame, QHBoxLayout, QLabel, QVBoxLayout

from control_pcs.repositories import fondo_repo
from control_pcs.ui.pcs_fondo_vista import COLOR_BLOQUEO, TAMANO_VISTA, vista_en_monitor
from ui.piezas_ventana import (
    TONO_GRIS, TONO_VERDE, agregar_pastilla, cabecera_oscura, panel_blanco, tecla, titulo_de_seccion,
)
from ui.utils import confirmar, manejar_errores, sin_boton_por_defecto

# Calidades JPEG que se prueban, de la mejor a la peor, hasta que entre en el peso máximo.
# Una foto muy "ruidosa" (césped, arena, mucho detalle fino) puede pasarse con la primera.
CALIDADES_A_PROBAR = (fondo_repo.CALIDAD_JPEG, 70, 55, 40)

FILTRO_IMAGENES = "Imágenes (*.jpg *.jpeg *.png *.bmp *.webp *.gif);;Todos los archivos (*)"

# Desde qué Cliente PC se pone el wallpaper (CLIENTE PC/version_cliente.py): las PCs con
# uno más viejo no se enteran. Solo para avisarlo.
VERSION_CLIENTE_ESCRITORIO = "V2.1"

# Lo que cambia entre los dos fondos; el resto de la ventana es igual para los dos.
TEXTOS = {
    fondo_repo.BLOQUEO: {
        "titulo": "Pantalla de bloqueo",
        "nota": "Detrás del nombre de la PC y del recuadro de ingreso.",
        "sin_imagen": "Sin imagen: las PCs muestran el gris liso de siempre.",
        "pastilla": "BLOQUEO",
        "quitar": "¿Quitar el fondo de la pantalla de bloqueo? Las PCs vuelven al gris liso de siempre.",
        "guardado": "Fondo de bloqueo guardado. Las PCs prendidas lo toman solas en unos segundos; "
                    "las que arranquen después, al arrancar.",
        "quitado": "Fondo de bloqueo quitado: las PCs vuelven al gris liso de siempre.",
    },
    fondo_repo.ESCRITORIO: {
        "titulo": "Escritorio de Windows (wallpaper)",
        "nota": "Lo que ve el cliente mientras juega. Se pone con la PC libre.",
        "sin_imagen": "Sin imagen: cada PC deja el wallpaper que tiene Windows.",
        "pastilla": "ESCRITORIO",
        "quitar": "¿Quitar el wallpaper? Las PCs dejan de cambiarlo: las congeladas vuelven a su "
                  "fondo de Windows cuando se reinician.",
        "guardado": "Wallpaper guardado. Las PCs libres lo ponen solas en unos segundos y las que "
                    f"están en uso cuando quedan libres (desde el Cliente PC {VERSION_CLIENTE_ESCRITORIO}).",
        "quitado": "Wallpaper quitado: las PCs dejan de cambiarlo.",
    },
}


def _sobre_el_gris(imagen: QImage) -> QImage:
    """`imagen` con sus transparencias rellenas con el gris liso de la pantalla de
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
        imagen = _sobre_el_gris(imagen)
    for calidad in CALIDADES_A_PROBAR:
        datos = _a_jpeg(imagen, calidad)
        if len(datos) <= fondo_repo.TAMANO_MAXIMO_BYTES:
            return datos
    raise ValueError("La imagen pesa demasiado aun comprimida al máximo. Probá con otra más simple.")


class DialogoFondoPantalla(QDialog):
    """Los dos fondos de las PCs lado a lado, cada uno con su vista previa y sus botones."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Fondos de pantalla de las PCs")
        self.resize(1080, 660)
        self.vistas, self.detalles, self.botones_quitar, self.pastillas = {}, {}, {}, {}
        self._armar_interfaz()
        for cual in fondo_repo.FONDOS:
            self._mostrar(cual)

    def _armar_interfaz(self):
        cabecera = cabecera_oscura(
            "🖼️", "Fondos de las PCs", "La pantalla de bloqueo y el escritorio de Windows · cada PC los toma sola")
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        for cual in fondo_repo.FONDOS:
            self.pastillas[cual] = agregar_pastilla(cabecera, "", TONO_GRIS)
            cuerpo.addWidget(self._panel(cual), 1)

        fila_misma = QHBoxLayout()
        fila_misma.addStretch()
        self.boton_la_misma = tecla("⇄  USAR LA MISMA IMAGEN EN LOS DOS", lambda: self._usar_la_misma())
        fila_misma.addWidget(self.boton_la_misma)
        fila_misma.addStretch()

        # Abajo: qué pasó con lo último que se tocó, y Cerrar.
        self.etiqueta_estado = QLabel(
            "Las PCs prendidas toman los cambios solas en unos segundos; congeladas, los vuelven a poner al arrancar.")
        self.etiqueta_estado.setWordWrap(True)
        barra_estado = QFrame()
        barra_estado.setObjectName("pieAyuda")
        capa_estado = QHBoxLayout(barra_estado)
        capa_estado.setContentsMargins(12, 8, 12, 8)
        capa_estado.addWidget(self.etiqueta_estado, 1)
        pie = QHBoxLayout()
        pie.addWidget(barra_estado, 1)
        pie.addSpacing(8)
        pie.addWidget(tecla("CERRAR", self.close, "teclaRoja"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(cuerpo, 1)
        layout.addLayout(fila_misma)
        layout.addLayout(pie)
        sin_boton_por_defecto(self)

    def _panel(self, cual):
        textos = TEXTOS[cual]
        self.vistas[cual] = QLabel()
        self.vistas[cual].setAlignment(Qt.AlignmentFlag.AlignCenter)
        # Sin esto, si el texto de abajo ocupa un renglón más, el monitor se corta por abajo.
        self.vistas[cual].setMinimumSize(*TAMANO_VISTA)
        self.detalles[cual] = QLabel()
        self.detalles[cual].setObjectName("ayudaChica")
        nota = QLabel(textos["nota"])
        nota.setWordWrap(True)
        self.botones_quitar[cual] = tecla("QUITAR", lambda: self._quitar(cual), "teclaRoja")
        fila_botones = QHBoxLayout()
        fila_botones.addWidget(tecla("🖼️  ELEGIR IMAGEN...", lambda: self._elegir(cual), "teclaAzul"), 1)
        fila_botones.addWidget(self.botones_quitar[cual])

        panel, capa = panel_blanco()
        capa.setSpacing(8)
        capa.addWidget(titulo_de_seccion(textos["titulo"]))
        capa.addWidget(self.vistas[cual], 1)
        capa.addWidget(self.detalles[cual])
        capa.addWidget(nota)
        capa.addLayout(fila_botones)
        return panel

    def _mostrar(self, cual):
        """La vista previa, el detalle, Quitar y la pastilla de ese fondo, como está guardado."""
        fondo = fondo_repo.obtener(cual)
        datos = fondo[0] if fondo else None
        self.vistas[cual].setPixmap(vista_en_monitor(datos, cual))
        nombre = TEXTOS[cual]["pastilla"]
        pastilla = self.pastillas[cual]
        if fondo is None:
            self.detalles[cual].setText(TEXTOS[cual]["sin_imagen"])
            pastilla.setText(f"{nombre}: SIN IMAGEN")
            pastilla.setProperty("tono", TONO_GRIS)
        else:
            imagen = QImage.fromData(datos)
            self.detalles[cual].setText(
                f"Imagen actual: {imagen.width()} × {imagen.height()}, {len(datos) // 1024} KB")
            pastilla.setText(f"{nombre} ✔")
            pastilla.setProperty("tono", TONO_VERDE)
        # Qt no vuelve a pintar sola una propiedad de estilo que cambió.
        pastilla.style().unpolish(pastilla)
        pastilla.style().polish(pastilla)
        self.botones_quitar[cual].setEnabled(fondo is not None)

    def _pedir_imagen(self, titulo: str):
        """La imagen elegida, lista para guardar, o None si se cancela el selector."""
        ruta, _filtro = QFileDialog.getOpenFileName(self, titulo, "", FILTRO_IMAGENES)
        return preparar_jpeg(ruta) if ruta else None

    @manejar_errores
    def _elegir(self, cual):
        datos = self._pedir_imagen(f"Elegir la imagen: {TEXTOS[cual]['titulo'].lower()}")
        if datos is None:
            return
        fondo_repo.guardar_jpeg(datos, cual)
        self._mostrar(cual)
        self.etiqueta_estado.setText(TEXTOS[cual]["guardado"])

    @manejar_errores
    def _usar_la_misma(self):
        datos = self._pedir_imagen("Elegir la imagen para los dos fondos")
        if datos is None:
            return
        for cual in fondo_repo.FONDOS:
            fondo_repo.guardar_jpeg(datos, cual)
            self._mostrar(cual)
        self.etiqueta_estado.setText(
            "La misma imagen quedó en la pantalla de bloqueo y en el escritorio. Las PCs la toman solas "
            f"(el wallpaper, con la PC libre y desde el Cliente PC {VERSION_CLIENTE_ESCRITORIO}).")

    @manejar_errores
    def _quitar(self, cual):
        if not confirmar(self, "Quitar el fondo", TEXTOS[cual]["quitar"]):
            return
        fondo_repo.quitar(cual)
        self._mostrar(cual)
        self.etiqueta_estado.setText(TEXTOS[cual]["quitado"])
