"""
pcs_botones_libres.py
=====================
Los dos botones de abajo del mosaico de Control de PCs (pedido del dueño,
2026-10-22), para hacer algo con todas las PCs prendidas y libres de una vez.
Los dos abren una ventana con esas PCs ya marcadas, donde se desmarcan las que
no se quieren tocar (pedido del dueño, mismo día):

- DESCONGELAR abre la ventana de Shadow Defender; desde ahí se descongelan o
  se congelan. Lo ve solo el Admin, igual que "Congelar / descongelar..." del
  clic derecho: pide la clave de Shadow Defender, que las empleadas no tienen.
- REINICIAR abre pcs_reiniciar_dialogo. Lo puede usar cualquiera, como
  "Reiniciar PC" del clic derecho.

Cuáles son las prendidas y libres lo decide pcs_libres_repo: las PCs con un
cliente nunca se tocan.
"""

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

import dominio
from control_pcs.repositories import pcs_libres_repo
from control_pcs.ui.pcs_congelado_dialogo import DialogoCongelado
from control_pcs.ui.pcs_reiniciar_dialogo import DialogoReiniciar
from ui.utils import aplicar_clase, manejar_errores, mostrar_info


class BotonesParaLasLibres(QWidget):
    def __init__(self, usuario, estados, parent=None):
        """`estados` devuelve lo último que leyó la pantalla de PCs
        (pcs_repo.estado_estaciones): las PCs, sin la PlayStation 5."""
        super().__init__(parent)
        self._estados = estados

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        # Mismas teclas en relieve que la barra de arriba, que también va sobre oscuro.
        self.boton_descongelar = None
        if dominio.es_admin(usuario):
            self.boton_descongelar = self._agregar_boton(layout, "🧊  Descongelar", self._descongelar)
        self.boton_reiniciar = self._agregar_boton(layout, "🔄  Reiniciar", self._reiniciar)
        layout.addStretch()
        self.setLayout(layout)

    @staticmethod
    def _agregar_boton(layout, texto, accion):
        boton = QPushButton(texto.upper())
        aplicar_clase(boton, "barra")
        boton.clicked.connect(accion)
        layout.addWidget(boton)
        return boton

    @manejar_errores
    def _descongelar(self):
        DialogoCongelado(None, self._estados(), self).exec()

    @manejar_errores
    def _reiniciar(self):
        estados = self._estados()
        if not pcs_libres_repo.prendidas_y_libres(estados):
            mostrar_info(self, "Reiniciar", "No hay ninguna PC prendida y libre para reiniciar.")
            return
        DialogoReiniciar(estados, self).exec()
