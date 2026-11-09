"""
pcs_aviso_sin_respuesta.py
============================
El aviso antes de cerrar la sesión de una PC que no responde (pedido del dueño,
2026-11-09; eligió la maqueta B de PROPUESTA_AVISO_PC_SIN_RESPUESTA, con la
cabecera oscura de ui/piezas_ventana.py). Lo abren "Finalizar Sesión" del panel
de la PC (pcs_detalle.py) y "Cerrar sesión y reiniciar" del clic derecho
(pcs_window.py) en vez de la pregunta de siempre. Qué decir lo decide
control_pcs/repositories/pcs_sin_respuesta_repo.py; acá solo se dibuja.

"NO CERRAR" es la tecla de entrada, así un Enter apurado no cierra nada. "CERRAR
IGUAL" queda para la PC que el cliente apagó al irse.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QVBoxLayout

from ui.piezas_ventana import TONO_ROJO, agregar_pastilla, cabecera_oscura, panel_blanco, tecla
from ui.utils import formato_tiempo

ANCHO = 620


def _tiempo(segundos) -> str:
    """"1h 04m" sin que se corte en dos renglones."""
    return formato_tiempo(segundos or 0).replace(" ", "&nbsp;")


class DialogoPcSinRespuesta(QDialog):
    """`aviso`: lo que devuelve pcs_sin_respuesta_repo.aviso_antes_de_cerrar. Se
    acepta (exec() da verdadero) solo con CERRAR IGUAL."""

    def __init__(self, aviso: dict, parent=None):
        super().__init__(parent)
        nombre = aviso["estacion_nombre"]
        self.setWindowTitle(f"{nombre} no responde")
        self.setFixedWidth(ANCHO)

        sin_noticias = aviso["segundos_sin_noticias"]
        detalle = ("Hace un rato que no tiene noticias del mostrador" if sin_noticias is None
                   else f"Hace {formato_tiempo(sin_noticias)} que no tiene noticias del mostrador")
        cabecera = cabecera_oscura("⚠", f"{nombre} NO RESPONDE", detalle)
        cortadas = aviso["cortadas_a_la_vez"]
        self.pastilla = agregar_pastilla(cabecera, f"{cortadas} PCs SIN RESPUESTA", TONO_ROJO)
        self.pastilla.setVisible(cortadas > 1)

        # Solo si se cortaron varias a la vez: es lo que pasó el 02/11 (la red del mostrador).
        self.aviso_red = QLabel(
            f"<b>Hay {cortadas} PCs que dejaron de responder a la vez: seguramente es la red del "
            "mostrador.</b><br>Revisá el cable o el internet del mostrador antes de cerrar nada."
        )
        self.aviso_red.setObjectName("avisoRedDelMostrador")
        self.aviso_red.setWordWrap(True)
        self.aviso_red.setVisible(cortadas > 1)

        panel, capa_panel = panel_blanco()
        for texto in (
            "<b>Si se cortó la red, no hace falta cerrarla.</b> La PC sigue contando sola y, "
            "cuando vuelve la conexión, sigue con su tiempo.",
            "<b>Si la cerrás ahora</b>, cuando vuelva la conexión la PC se va a reiniciar y el "
            f"cliente pierde <b>{_tiempo(aviso['segundos_restantes'])}</b>.",
            "Si el cliente apagó la PC y se fue, tocá <b>CERRAR IGUAL</b>.",
        ):
            etiqueta = QLabel(texto)
            etiqueta.setObjectName("textoSinRespuesta")
            etiqueta.setWordWrap(True)
            capa_panel.addWidget(etiqueta)

        self.boton_cerrar_igual = tecla("✕  CERRAR IGUAL", self.accept, "teclaRoja")
        self.boton_no_cerrar = tecla("NO CERRAR", self.reject, "teclaAzul")
        self.boton_cerrar_igual.setAutoDefault(False)
        self.boton_no_cerrar.setDefault(True)
        fila = QHBoxLayout()
        fila.addStretch()
        fila.addWidget(self.boton_cerrar_igual)
        fila.addSpacing(8)
        fila.addWidget(self.boton_no_cerrar)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(16, 16, 16, 16)
        capa.setSpacing(12)
        capa.addWidget(cabecera)
        capa.addWidget(self.aviso_red)
        capa.addWidget(panel)
        capa.addStretch(1)
        capa.addLayout(fila)
        # Qt arma el alto de la ventana con los textos partidos para un ancho más angosto y
        # sobraba lugar: estiraba la cabecera oscura o dejaba un hueco abajo. Se le da el
        # alto justo para su ancho.
        self.resize(ANCHO, capa.heightForWidth(ANCHO))
        self.boton_no_cerrar.setFocus(Qt.OtherFocusReason)


def cerrar_igual(padre, aviso: dict) -> bool:
    """Muestra el aviso y devuelve True solo si se eligió CERRAR IGUAL."""
    return DialogoPcSinRespuesta(aviso, padre).exec() == QDialog.Accepted
