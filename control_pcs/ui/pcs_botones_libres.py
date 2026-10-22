"""
pcs_botones_libres.py
=====================
Los dos botones de abajo del mosaico de Control de PCs (pedido del dueño,
2026-10-22), para hacer algo con todas las PCs prendidas y libres de una vez:

- DESCONGELAR abre la ventana de Shadow Defender con todas esas PCs ya
  marcadas; desde ahí se descongelan o se congelan. Lo ve solo el Admin, igual
  que "Congelar / descongelar..." del clic derecho: pide la clave de Shadow
  Defender, que las empleadas no tienen.
- REINICIAR las reinicia a todas, después de preguntar cuáles. Lo puede usar
  cualquiera, como "Reiniciar PC" del clic derecho.

Cuáles son las prendidas y libres lo decide pcs_libres_repo: las PCs con un
cliente nunca se tocan.
"""

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

import dominio
from control_pcs.repositories import comandos_pc_repo, pcs_libres_repo
from control_pcs.ui.pcs_congelado_dialogo import DialogoCongelado
from ui.utils import aplicar_clase, confirmar, manejar_errores, mostrar_info


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
        libres = pcs_libres_repo.prendidas_y_libres(self._estados())
        if not libres:
            mostrar_info(self, "Reiniciar", "No hay ninguna PC prendida y libre para reiniciar.")
            return
        nombres = ", ".join(item["estacion"]["nombre"] for item in libres)
        if not confirmar(
            self, "Reiniciar",
            f"Se van a reiniciar {len(libres)} PC(s) prendidas y libres:\n{nombres}\n\n"
            "Las que tienen un cliente no se tocan. ¿Seguir?",
        ):
            return
        reiniciadas, salteadas = pcs_libres_repo.reiniciar([item["estacion"]["id"] for item in libres])
        if reiniciadas:
            texto = (f"Se les va a avisar a {len(reiniciadas)} PC(s) en los próximos segundos.\n\n"
                     f"Si alguna no lo recibe en {comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO} minutos "
                     "(apagada o sin conexión), se descarta: así no le llega más tarde a otro cliente.")
        else:
            texto = "No se reinició ninguna PC."
        if salteadas:
            texto += f"\n\nNo se reiniciaron porque ya no estaban libres: {', '.join(salteadas)}."
        mostrar_info(self, "Reiniciar", texto)
