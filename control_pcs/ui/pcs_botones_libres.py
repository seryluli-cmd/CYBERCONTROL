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
clic derecho sigue siendo solo del Admin. Desde otra PC se ven igual y avisan
que eso se hace en el mostrador (pedido del dueño, 2026-10-24).

El copo de nieve de DESCONGELAR, el símbolo de APAGAR y las flechas de
REINICIAR van dibujados (pcs_dibujos): los emojis salían como un rectángulo
en el Windows del mostrador.

Van debajo del fondo negro del mosaico, no adentro (pedido del dueño, mismo
día): ver PanelControlPcs._armar_interfaz.

Cuáles son las prendidas y libres lo decide pcs_libres_repo: las PCs con un
cliente nunca se tocan.
"""

from PySide6.QtWidgets import QHBoxLayout, QPushButton, QWidget

from control_pcs.repositories import pcs_libres_repo
from control_pcs.ui.pcs_congelado_dialogo import DialogoCongelado
from control_pcs.ui.pcs_dibujos import TAMANO_ICONO, icono_apagar, icono_copo_de_nieve, icono_reiniciar
from control_pcs.ui.pcs_reiniciar_dialogo import DialogoApagar, DialogoReiniciar
from ui.utils import aplicar_clase, manejar_errores, mostrar_info, solo_en_el_mostrador


class BotonesParaLasLibres(QWidget):
    def __init__(self, estados, usuario=None, parent=None):
        """`estados` devuelve lo último que leyó la pantalla de PCs
        (pcs_repo.estado_estaciones): las PCs, sin la PlayStation 5. `usuario` es
        quien está logueado (el Administrador ve ACTUALIZAR CLIENTES en DESCONGELAR)."""
        super().__init__(parent)
        self._estados = estados
        self._usuario = usuario

        layout = QHBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(10)
        # Mismas teclas en relieve que la barra de arriba.
        self.boton_descongelar = self._agregar_boton(layout, " Descongelar", self._descongelar,
                                                     icono_copo_de_nieve())
        self.boton_reiniciar = self._agregar_boton(layout, " Reiniciar", self._reiniciar, icono_reiniciar())
        self.boton_apagar = self._agregar_boton(layout, " Apagar", self._apagar, icono_apagar())
        # Sin estirarse al final: a la derecha de APAGAR va CONTROL DE STOCK, en la
        # misma fila (la arma PanelControlPcs._armar_interfaz).
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

    @solo_en_el_mostrador
    @manejar_errores
    def _descongelar(self):
        DialogoCongelado(None, self._estados(), self._usuario, self).exec()

    @solo_en_el_mostrador
    @manejar_errores
    def _reiniciar(self):
        self._abrir_si_hay_libres(DialogoReiniciar)

    @solo_en_el_mostrador
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
