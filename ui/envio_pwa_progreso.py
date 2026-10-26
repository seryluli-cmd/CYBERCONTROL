"""
ui/envio_pwa_progreso.py
========================
La barra "ENVIANDO CIERRE DE TURNO" que se ve al confirmar un Cierre de Turno con el
envío a la app de gastos prendido (pedido del dueño, 2026-10-26: "una barra de
progreso que se vaya llenando, que dure 3 segundos al menos"). El envío lo hace el
hilo de repositories/envio_pwa_repo.py; esta pantalla NO manda nada: mira cómo va ese
cierre en la cola y lo cuenta. Se llena del todo recién cuando la app lo confirmó;
si no hay internet lo dice (en rojo, con el porqué) y aclara que se manda solo
después, porque el cierre ya quedó guardado acá.
"""

import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QProgressBar, QVBoxLayout

import dominio
from repositories import envio_pwa_repo
from ui.piezas_ventana import tecla
from ui.utils import sin_boton_por_defecto

SEGUNDOS_MINIMOS = 3           # la barra tarda esto como mínimo, aunque el envío sea instantáneo
SEGUNDOS_MAXIMOS = 25          # pasado esto deja de esperar: el hilo lo sigue intentando solo
MILISEGUNDOS_ENTRE_TICS = 100
MILISEGUNDOS_PARA_CERRARSE = 1200   # ya enviado: lo que queda a la vista "CIERRE ENVIADO"
# Hasta que la app confirma, la barra no pasa de acá: llena del todo = enviado.
TOPE_SIN_CONFIRMAR = 90

ENVIADO = "enviado"
ERROR = "error"
PENDIENTE = "pendiente"


class DialogoEnviandoCierre(QDialog):
    """`terminado` queda en ENVIADO, ERROR o PENDIENTE cuando la barra terminó (None
    mientras corre). `reloj` es para las pruebas (segundos, como time.monotonic)."""

    def __init__(self, cierre_id: int, parent=None, reloj=time.monotonic):
        super().__init__(parent)
        self.cierre_id = cierre_id
        self._reloj = reloj
        self._desde = reloj()
        self.terminado = None
        self.setWindowTitle("Cierre de Turno")
        self.setModal(True)
        # No se cierra con la cruz: termina sola o con CONTINUAR.
        self.setWindowFlag(Qt.WindowCloseButtonHint, False)
        self._armar_interfaz()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tic)
        self._timer.start(MILISEGUNDOS_ENTRE_TICS)
        self._cerrarse = QTimer(self)
        self._cerrarse.setSingleShot(True)
        self._cerrarse.timeout.connect(self.accept)

    def _armar_interfaz(self):
        self.titulo = QLabel("ENVIANDO CIERRE DE TURNO")
        self.titulo.setObjectName("tituloEnvio")
        self.titulo.setAlignment(Qt.AlignCenter)
        self.barra = QProgressBar()
        self.barra.setObjectName("barraEnvio")
        self.barra.setRange(0, 100)
        self.barra.setValue(0)
        self.barra.setTextVisible(False)
        self.barra.setFixedHeight(22)
        self.detalle = QLabel("A la app de gastos (Gastos — CyberBIOS)…")
        self.detalle.setObjectName("detalleEnvio")
        self.detalle.setAlignment(Qt.AlignCenter)
        self.detalle.setWordWrap(True)
        self.tecla_continuar = tecla("CONTINUAR", self.accept, "teclaAzul")
        self.tecla_continuar.setVisible(False)  # recién cuando terminó

        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.tecla_continuar)
        botones.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(self.titulo)
        layout.addWidget(self.barra)
        layout.addWidget(self.detalle)
        layout.addLayout(botones)
        self.resize(480, 190)
        sin_boton_por_defecto(self)

    def _tic(self):
        transcurrido = self._reloj() - self._desde
        if transcurrido < SEGUNDOS_MINIMOS:
            # Los primeros 3 segundos se llena pase lo que pase: que se vea que se manda.
            self.barra.setValue(int(transcurrido / SEGUNDOS_MINIMOS * TOPE_SIN_CONFIRMAR))
            return
        como_va = envio_pwa_repo.estado_del_cierre(self.cierre_id)
        if como_va is not None and como_va["estado"] == dominio.ENVIO_ENVIADO:
            self._terminar(ENVIADO, 100, "✔ CIERRE ENVIADO", "Ya quedó asentado en la app de gastos.")
        elif como_va is not None and como_va["estado"] == dominio.ENVIO_ERROR:
            self._terminar(
                ERROR, TOPE_SIN_CONFIRMAR, "NO SE PUDO ENVIAR AHORA",
                f"{como_va['ultimo_error']}\nSe vuelve a intentar solo; el cierre ya quedó guardado acá.",
            )
        elif como_va is None or transcurrido >= SEGUNDOS_MAXIMOS:
            self._terminar(
                PENDIENTE, TOPE_SIN_CONFIRMAR, "SE ENVÍA ENSEGUIDA",
                "Está tardando. Se manda solo apenas haya conexión; el cierre ya quedó guardado acá.",
            )
        else:
            self.barra.setValue(TOPE_SIN_CONFIRMAR)  # esperando a que la app conteste

    def _terminar(self, como: str, valor: int, titulo: str, detalle: str):
        self._timer.stop()
        self.terminado = como
        self.barra.setValue(valor)
        self.titulo.setText(titulo)
        self.titulo.setProperty("estado", como)
        # Qt no vuelve a pintar sola una propiedad de estilo que cambió.
        self.titulo.style().unpolish(self.titulo)
        self.titulo.style().polish(self.titulo)
        self.detalle.setText(detalle)
        self.tecla_continuar.setVisible(True)
        # Con el porqué de un error (dos o tres renglones) la ventana crece lo que haga
        # falta: si no, el texto se encima con la barra y la tecla.
        self.layout().activate()
        self.resize(self.width(), max(self.height(), self.sizeHint().height()))
        if como == ENVIADO:
            self._cerrarse.start(MILISEGUNDOS_PARA_CERRARSE)  # se va sola; CONTINUAR por si apuran
