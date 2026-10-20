"""
ingreso_caja.py
================
Lo que pasa con la caja entre el login y la ventana principal (pedido del
dueño, 2026-10-18): abrir la caja contando el cambio, recibir la caja de quien
cubrió el turno contando todo el cajón, o cerrar la caja de quien se fue sin
cerrar. Las reglas viven en repositories/relevo_repo.py; acá solo se pregunta y
se muestra.

El conteo es a ciegas: primero se escribe lo que se contó y recién después el
programa dice cuánto tendría que haber y si falta o sobra. Así nadie copia el
número de la pantalla sin contar.
"""

from datetime import datetime

from PySide6.QtWidgets import QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from repositories import relevo_repo
from turnos import MINUTOS_PARA_CIERRE_FORZOSO
from ui.utils import (
    aplicar_clase, confirmar, encadenar_enter, formato_pesos, manejar_errores, mostrar_info,
    sin_boton_por_defecto,
)


def _hora(fecha_iso: str) -> str:
    """"14:05" a partir de una fecha ISO de la base."""
    return datetime.fromisoformat(fecha_iso).strftime("%H:%M")


def texto_de_la_diferencia(diferencia: float) -> str:
    """"coincide", "faltan $ 500,00" o "sobran $ 200,00"."""
    if abs(diferencia) < 0.005:
        return "coincide"
    return f"faltan {formato_pesos(-diferencia)}" if diferencia < 0 else f"sobran {formato_pesos(diferencia)}"


class DialogoContarPlata(QDialog):
    """
    Pide un monto contado y, recién cuando se escribió, muestra cuánto tendría
    que haber y la diferencia, para confirmar o volver a contar. `explicacion`
    va arriba del campo; `detalle_esperado` (opcional) dice de dónde sale lo que
    tendría que haber. Si se confirmó, el monto queda en `self.contado`.
    """

    def __init__(self, parent, titulo: str, explicacion: str, esperado: float,
                 detalle_esperado: str = "", texto_confirmar: str = "Confirmar"):
        super().__init__(parent)
        self.setWindowTitle(titulo)
        self.resize(460, 260)
        self._esperado = esperado
        self._detalle_esperado = detalle_esperado
        self.contado = None

        texto = QLabel(explicacion)
        texto.setWordWrap(True)

        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        encadenar_enter(self.spin_monto, accion_final=self._listo)

        self.resultado = QLabel()
        self.resultado.setWordWrap(True)
        self.resultado.setStyleSheet("font-weight: 600;")
        self.resultado.hide()

        self.boton_listo = QPushButton("Listo")
        aplicar_clase(self.boton_listo, "primario")
        self.boton_listo.clicked.connect(self._listo)
        self.boton_confirmar = QPushButton(texto_confirmar)
        aplicar_clase(self.boton_confirmar, "primario")
        self.boton_confirmar.clicked.connect(self._confirmar)
        self.boton_confirmar.hide()
        self.boton_recontar = QPushButton("Volver a contar")
        self.boton_recontar.clicked.connect(self._volver_a_contar)
        self.boton_recontar.hide()
        boton_cancelar = QPushButton("Cancelar")
        aplicar_clase(boton_cancelar, "peligro")
        boton_cancelar.clicked.connect(self.reject)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(self.boton_recontar)
        botones.addWidget(self.boton_listo)
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout()
        layout.addWidget(texto)
        layout.addWidget(self.spin_monto)
        layout.addWidget(self.resultado)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.spin_monto.setFocus()
        self.spin_monto.selectAll()

    def _listo(self):
        contado = self.spin_monto.value()
        diferencia = relevo_repo.diferencia(contado, self._esperado)
        detalle = f" ({self._detalle_esperado})" if self._detalle_esperado else ""
        self.resultado.setText(
            f"Tendría que haber {formato_pesos(self._esperado)}{detalle}.\n"
            f"Contaste {formato_pesos(contado)}: {texto_de_la_diferencia(diferencia)}."
        )
        self.resultado.setStyleSheet(
            "font-weight: 600; color: " + ("#1E7B45;" if abs(diferencia) < 0.005 else "#A6323C;")
        )
        self.resultado.show()
        self.spin_monto.setEnabled(False)
        self.boton_listo.hide()
        self.boton_recontar.show()
        self.boton_confirmar.show()
        self.boton_confirmar.setFocus()

    def _volver_a_contar(self):
        self.resultado.hide()
        self.spin_monto.setEnabled(True)
        self.boton_confirmar.hide()
        self.boton_recontar.hide()
        self.boton_listo.show()
        self.spin_monto.setFocus()
        self.spin_monto.selectAll()

    def _confirmar(self):
        self.contado = self.spin_monto.value()
        self.accept()


def _abrir(parent, usuario, situacion) -> bool:
    """Abre la caja de `usuario`, contando el cambio si hace falta."""
    contado = None
    if situacion["cuenta_cambio"]:
        dialogo = DialogoContarPlata(
            parent, "Abrir caja",
            f"No hay ninguna caja abierta: vas a abrir una para el turno {situacion['turno_label']}.\n\n"
            "Contá el Cambio Fijo que hay en el cajón y escribilo:",
            situacion["cambio_esperado"], "lo que dejó la caja anterior", texto_confirmar="Abrir caja",
        )
        if dialogo.exec() != QDialog.Accepted:
            return False
        contado = dialogo.contado
    relevo_repo.abrir_caja(usuario["id"], contado)
    return True


def _recibir(parent, usuario, situacion) -> bool:
    """Recibe la caja de quien la tenía, contando todo el cajón."""
    dialogo = DialogoContarPlata(
        parent, "Recibir la caja",
        f"La caja Nº {situacion['caja_numero']} ({situacion['turno_label']}) la tiene "
        f"{situacion['responsable']} desde las {_hora(situacion['abierta_en'])}.\n\n"
        f"Vas a recibirla: desde ahora queda a tu cargo, y lo que vendió {situacion['responsable']} "
        "va en tu sobre. Contá TODA la plata del cajón (el Cambio Fijo y lo vendido) y escribila:",
        situacion["esperado"],
        f"{formato_pesos(situacion['cambio_inicial'])} de Cambio Fijo + "
        f"{formato_pesos(situacion['ventas_efectivo'])} vendidos en efectivo",
        texto_confirmar="Recibir la caja",
    )
    if dialogo.exec() != QDialog.Accepted:
        return False
    relevo_repo.recibir_caja(usuario["id"], situacion["caja_id"], dialogo.contado)
    return True


def mensaje_del_sobre(resultado) -> str:
    """Cuánto va al sobre y cuánto queda de cambio, después de un cierre."""
    return (
        f"Retirá {formato_pesos(resultado['monto_a_retirar'])} para el sobre y guardalo en la caja fuerte.\n"
        f"Dejá {formato_pesos(resultado['cambio_que_queda'])} de Cambio Fijo en el cajón."
    )


def _cerrar_la_de_otra(parent, usuario, situacion) -> bool:
    """Cierra la caja de quien se fue sin cerrar (queda anotado)."""
    otra = situacion["responsable"]
    if not confirmar(
        parent, f"Cerrar la caja de {otra}",
        f"La caja Nº {situacion['caja_numero']} ({situacion['turno_label']}) de {otra} sigue abierta "
        "y su turno ya terminó.\n\n"
        f"Para abrir tu caja, primero hay que cerrar la de {otra}. Queda anotado que la cerraste "
        f"vos en su ausencia.\n\n¿La cerrás ahora?",
    ):
        return False
    resultado = relevo_repo.cerrar_para_entrar(usuario["id"], relevo_repo.SITUACION_CERRAR_LA_DE_OTRA)
    mostrar_info(
        parent, "Caja cerrada",
        f"Caja Nº {resultado['caja_numero']} de {otra} cerrada.\n\n"
        f"Armá el sobre de {otra}: {mensaje_del_sobre(resultado)}\n\n"
        "Ahora abrís tu caja.",
    )
    return True


def _cerrar_la_propia_vencida(parent, usuario, situacion) -> bool:
    """Su propia caja pasó el cierre forzoso mientras el programa estaba cerrado."""
    resultado = relevo_repo.cerrar_para_entrar(usuario["id"], relevo_repo.SITUACION_SU_CAJA_VENCIDA)
    mostrar_info(
        parent, "Cierre forzoso",
        f"Tu caja Nº {resultado['caja_numero']} ({situacion['turno_label']}) se cerró sola: pasaron "
        f"{MINUTOS_PARA_CIERRE_FORZOSO} minutos del fin del turno.\n\n"
        f"{mensaje_del_sobre(resultado)}\n\n"
        "Si seguís atendiendo, entrás con una caja nueva.",
    )
    return True


def _cerrar_ventas_sin_caja(parent, usuario, situacion) -> bool:
    """Cierra aparte las ventas que quedaron sin caja."""
    if not confirmar(
        parent, "Ventas sin cerrar",
        f"Hay {situacion['cantidad']} ventas sin cerrar desde el "
        f"{datetime.fromisoformat(situacion['desde']).strftime('%d/%m %H:%M')}, hechas sin una caja "
        "abierta (de antes de las cajas, o del Administrador sin nadie en el mostrador).\n\n"
        "Antes de abrir tu caja hay que cerrarlas en un cierre aparte. ¿Las cerrás ahora?",
    ):
        return False
    resultado = relevo_repo.cerrar_para_entrar(usuario["id"], relevo_repo.SITUACION_VENTAS_SIN_CAJA)
    mostrar_info(
        parent, "Ventas cerradas",
        f"Listo. Armá un sobre aparte para esas ventas. {mensaje_del_sobre(resultado)}\n\nAhora abrís tu caja.",
    )
    return True


_QUE_HACER = {
    relevo_repo.SITUACION_ABRIR: _abrir,
    relevo_repo.SITUACION_RECIBIR: _recibir,
    relevo_repo.SITUACION_CERRAR_LA_DE_OTRA: _cerrar_la_de_otra,
    relevo_repo.SITUACION_SU_CAJA_VENCIDA: _cerrar_la_propia_vencida,
    relevo_repo.SITUACION_VENTAS_SIN_CAJA: _cerrar_ventas_sin_caja,
}

# Más vueltas que esto sería un error (cada paso deja la caja en otra situación):
# mejor cortar que quedar preguntando para siempre.
_MAXIMO_DE_PASOS = 6


@manejar_errores
def _resolver(parent, usuario) -> bool:
    for _ in range(_MAXIMO_DE_PASOS):
        situacion = relevo_repo.situacion_al_entrar(usuario["id"])
        if situacion["situacion"] in (relevo_repo.SITUACION_SU_CAJA, relevo_repo.SITUACION_ADMIN):
            return True
        if not _QUE_HACER[situacion["situacion"]](parent, usuario, situacion):
            return False
    raise RuntimeError("No se pudo dejar la caja lista para entrar.")


def resolver_caja_al_entrar(parent, usuario) -> bool:
    """
    Deja la caja lista para que `usuario` entre: la abre, la recibe o cierra
    antes lo que haga falta, preguntando lo necesario. True si puede entrar;
    False si canceló o algo falló (el error ya se mostró), y se queda en el
    ingreso.
    """
    return _resolver(parent, usuario) is True
