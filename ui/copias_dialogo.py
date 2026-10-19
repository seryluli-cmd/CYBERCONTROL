"""
copias_dialogo.py
===================
La pantalla de COPIAS DE SEGURIDAD (Usuarios > "Copias de Seguridad", solo Admin y
solo en el mostrador: desde otra PC no hay base que copiar). Muestra cuándo se
hacen solas, la última en esta PC y cómo anduvo cada una de las otras carpetas
(otro disco, otra PC de la red); deja agregarlas y quitarlas, hacer una copia ya
y guardar una suelta en un pendrive. Las reglas (cuándo, cuántas, dónde) viven en
repositories/copias_repo.py.
"""

from PySide6.QtCore import Qt, QUrl
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QApplication, QDialog, QFileDialog, QFormLayout, QGroupBox, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QTableWidgetItem, QVBoxLayout,
)

from repositories import copias_repo
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, encadenar_enter, fila_guardar_cancelar, formato_fecha_hora,
    manejar_errores, mostrar_error, mostrar_info, sin_boton_por_defecto,
)

_ESTILO_ERROR = "color: #C62828; font-weight: 600;"
_ESTILO_AYUDA = "color: #7A869A;"
_COLOR_ERROR = QColor("#C62828")


def _cuando(momento) -> str:
    return formato_fecha_hora(momento.isoformat()) if momento else "todavía ninguna"


class _Esperando:
    """Reloj de arena mientras se copia: una carpeta de otra PC apagada tarda
    unos segundos en contestar."""

    def __enter__(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def __exit__(self, *_):
        QApplication.restoreOverrideCursor()


class DialogoCopiasDeSeguridad(QDialog):
    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Copias de Seguridad")
        self.resize(720, 520)
        self._armar_interfaz()
        self._actualizar()

    def _armar_interfaz(self):
        explicacion = QLabel(
            "El programa guarda solo una copia de la base, sin cerrarse: después de cada "
            f"<b>Cierre de Turno</b> y, si no hubo ninguno, cada <b>{copias_repo.HORAS_ENTRE_COPIAS} "
            f"horas</b>. Quedan todas las de los últimos {copias_repo.DIAS_CON_TODAS_LAS_COPIAS} días "
            f"y, más atrás, una por día hasta {copias_repo.DIAS_CON_UNA_COPIA} días."
        )
        explicacion.setWordWrap(True)

        # En esta PC
        self.etiqueta_local = QLabel()
        self.error_local = QLabel()
        self.error_local.setStyleSheet(_ESTILO_ERROR)
        self.error_local.setWordWrap(True)
        boton_abrir_local = QPushButton("Abrir carpeta")
        boton_abrir_local.clicked.connect(lambda: self._abrir(copias_repo.carpeta_local()))
        fila_local = QHBoxLayout()
        fila_local.addWidget(self.etiqueta_local, 1)
        fila_local.addWidget(boton_abrir_local)
        grupo_local = QGroupBox("En esta PC (carpeta del programa, data\\backups)")
        layout_local = QVBoxLayout()
        layout_local.addLayout(fila_local)
        layout_local.addWidget(self.error_local)
        grupo_local.setLayout(layout_local)

        # Las otras carpetas
        self.tabla = crear_tabla(["Carpeta", "Última copia ahí", "Cómo anda"], estirar=2,
                                 por_filas=True, una_sola=True)
        ayuda = QLabel(
            "Cada copia se guarda también en estas carpetas. Si una no está (la otra PC "
            "apagada, el disco desconectado), la copia llega sola cuando vuelve."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(_ESTILO_AYUDA)
        # El porqué de cada carpeta que no anda, entero (en la tabla no entra).
        self.errores_extra = QLabel()
        self.errores_extra.setStyleSheet(_ESTILO_ERROR)
        self.errores_extra.setWordWrap(True)
        boton_agregar = QPushButton("Agregar carpeta...")
        boton_agregar.clicked.connect(self._agregar_carpeta)
        self.boton_abrir_extra = QPushButton("Abrir carpeta")
        self.boton_abrir_extra.clicked.connect(lambda: self._abrir(self._carpeta_elegida()))
        self.boton_quitar = QPushButton("Quitar")
        self.boton_quitar.clicked.connect(self._quitar_carpeta)
        botones_extra = QHBoxLayout()
        botones_extra.addWidget(boton_agregar)
        botones_extra.addWidget(self.boton_abrir_extra)
        botones_extra.addWidget(self.boton_quitar)
        botones_extra.addStretch()
        grupo_extra = QGroupBox("Otras carpetas (otro disco u otra PC de la red)")
        layout_extra = QVBoxLayout()
        layout_extra.addWidget(ayuda)
        layout_extra.addWidget(self.tabla)
        layout_extra.addWidget(self.errores_extra)
        layout_extra.addLayout(botones_extra)
        grupo_extra.setLayout(layout_extra)

        boton_ahora = QPushButton("Hacer copia de seguridad ahora")
        aplicar_clase(boton_ahora, "primario")
        boton_ahora.clicked.connect(self._copiar_ahora)
        boton_pendrive = QPushButton("Guardar una copia en un pendrive...")
        boton_pendrive.setToolTip(
            "Una copia suelta en la carpeta que elijas, con fecha y hora en el nombre. "
            "Esa no se borra nunca sola."
        )
        boton_pendrive.clicked.connect(self._copiar_a_pendrive)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.accept)
        botones = QHBoxLayout()
        botones.addWidget(boton_ahora)
        botones.addWidget(boton_pendrive)
        botones.addStretch()
        botones.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addWidget(explicacion)
        layout.addWidget(grupo_local)
        layout.addWidget(grupo_extra, 1)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _actualizar(self):
        estado = copias_repo.estado()
        self.etiqueta_local.setText(
            f"Última copia: <b>{_cuando(estado['ultima_local'])}</b> · "
            f"{estado['cantidad_local']} copia(s) guardada(s)"
        )
        self.error_local.setText(estado["error_local"] or "")
        self.error_local.setVisible(bool(estado["error_local"]))

        self.tabla.clearSelection()
        self.tabla.setRowCount(0)
        for carpeta in estado["extra"]:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            if carpeta["error"]:
                como_anda = "No anda (ver abajo)"
            elif carpeta["revisada"]:
                como_anda = "Bien"
            else:
                como_anda = "Se revisa en un minuto"
            celdas = [carpeta["carpeta"], _cuando(carpeta["ultima"]), como_anda]
            for columna, texto in enumerate(celdas):
                item = QTableWidgetItem(texto)
                if carpeta["error"]:
                    item.setForeground(_COLOR_ERROR)
                    item.setToolTip(carpeta["error"])
                self.tabla.setItem(fila, columna, item)
        self.tabla.resizeColumnToContents(0)
        self.tabla.resizeColumnToContents(1)
        errores = [carpeta["error"] for carpeta in estado["extra"] if carpeta["error"]]
        self.errores_extra.setText("\n".join(errores))
        self.errores_extra.setVisible(bool(errores))
        hay = self.tabla.rowCount() > 0
        self.boton_abrir_extra.setEnabled(hay)
        self.boton_quitar.setEnabled(hay)

    def _carpeta_elegida(self) -> str:
        fila = self.tabla.currentRow()
        if fila < 0 or not self.tabla.selectionModel().hasSelection():
            mostrar_error(self, "Nada elegido", "Elegí primero una carpeta de la lista.")
            return ""
        return self.tabla.item(fila, 0).text()

    def _abrir(self, carpeta: str):
        if carpeta:
            QDesktopServices.openUrl(QUrl.fromLocalFile(carpeta))

    def _agregar_carpeta(self):
        if DialogoAgregarCarpeta(self.usuario, self).exec():
            # Se prueba enseguida: así se ve ya si anda y la última copia queda ahí.
            self._copiar_ahora()

    @manejar_errores
    def _quitar_carpeta(self):
        carpeta = self._carpeta_elegida()
        if not carpeta:
            return
        if not confirmar(
            self, "Quitar carpeta",
            f"¿Dejar de guardar las copias en {carpeta}? Las que ya están ahí no se borran.",
        ):
            return
        copias_repo.quitar_carpeta_extra(self.usuario["id"], carpeta)
        self._actualizar()

    @manejar_errores
    def _copiar_ahora(self):
        try:
            with _Esperando():
                resultado = copias_repo.hacer_copia_ahora()
        finally:
            self._actualizar()
        fallaron = [r for r in resultado["extra"] if r["error"]]
        anduvieron = len(resultado["extra"]) - len(fallaron)
        if fallaron:
            mostrar_error(
                self, "Copia hecha, pero no en todas las carpetas",
                "La copia quedó en esta PC"
                + (f" y en {anduvieron} carpeta(s) más" if anduvieron else "")
                + ", pero no en:\n\n" + "\n\n".join(r["error"] for r in fallaron),
            )
            return
        donde = f"en esta PC y en las {anduvieron} carpeta(s) de la lista" if anduvieron else "en esta PC"
        mostrar_info(self, "Copia hecha", f"Listo: la copia quedó guardada {donde}.")

    @manejar_errores
    def _copiar_a_pendrive(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Elegí dónde guardar la copia de seguridad")
        if not carpeta:
            return
        ruta_final = copias_repo.guardar_copia_en(carpeta)
        mostrar_info(self, "Copia guardada", f"Se guardó la copia de seguridad en:\n{ruta_final}")


class DialogoAgregarCarpeta(QDialog):
    """Una carpeta más para las copias: de otro disco (D:\\BACKUPS) o de otra PC
    de la red (\\\\192.168.1.111\\backups), con el usuario y la clave que pide."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Agregar carpeta para las copias")
        self.resize(520, 260)
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.campo_carpeta = QLineEdit()
        self.campo_carpeta.setPlaceholderText("D:\\BACKUPS  o  \\\\192.168.1.111\\backups")
        boton_buscar = QPushButton("Buscar...")
        boton_buscar.clicked.connect(self._buscar)
        fila_carpeta = QHBoxLayout()
        fila_carpeta.addWidget(self.campo_carpeta, 1)
        fila_carpeta.addWidget(boton_buscar)

        self.campo_usuario = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)

        formulario = QFormLayout()
        formulario.addRow("Carpeta:", fila_carpeta)
        formulario.addRow("Usuario:", self.campo_usuario)
        formulario.addRow("Clave:", self.campo_clave)

        ayuda = QLabel(
            "Usuario y clave, solo si la carpeta es de otra PC (empieza con \\\\) y los pide. "
            "El programa se los pasa a Windows, que los recuerda (como \"Recordar mis "
            "credenciales\"): no quedan guardados en el programa."
        )
        ayuda.setWordWrap(True)
        ayuda.setStyleSheet(_ESTILO_AYUDA)

        layout = QVBoxLayout()
        layout.addLayout(formulario)
        layout.addWidget(ayuda)
        layout.addStretch()
        layout.addLayout(fila_guardar_cancelar(self, self._guardar, "Agregar"))
        self.setLayout(layout)
        encadenar_enter(self.campo_carpeta, self.campo_usuario, self.campo_clave, accion_final=self._guardar)
        sin_boton_por_defecto(self)

    def _buscar(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Elegí la carpeta para las copias")
        if carpeta:
            self.campo_carpeta.setText(carpeta.replace("/", "\\"))

    @manejar_errores
    def _guardar(self):
        with _Esperando():
            copias_repo.agregar_carpeta_extra(
                self.usuario["id"], self.campo_carpeta.text(), self.campo_usuario.text(), self.campo_clave.text()
            )
        self.accept()
