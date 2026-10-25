"""
cuenta_pc_reglas_dialogo.py
=============================
Configuración ADMIN > "Reglas de Cuenta de PC" (pedido del dueño, 2026-10-25:
"el tope que sea definible por el admin, como una regla"): cuánto puede deber
una PC por su Cuenta de la PC, qué pasa si se quiere anotar más y si se puede
anotar tiempo. Solo el Admin (el repo lo vuelve a exigir). Se abre también
desde otra PC (admin_remoto/lista_blanca.py).
"""

from PySide6.QtWidgets import QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QRadioButton, QVBoxLayout

import dominio
from control_pcs.repositories import cuentas_pc_repo
from ui.utils import encadenar_enter, fila_guardar_cancelar, manejar_errores, mostrar_info, sin_boton_por_defecto


class DialogoReglasCuentaPc(QDialog):
    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Reglas de Cuenta de PC")
        self.resize(400, 330)
        self._armar_interfaz()

    def _armar_interfaz(self):
        reglas = cuentas_pc_repo.obtener_reglas()

        explicacion = QLabel(
            "Lo que una PC puede deber sin pagar (un pancho, más tiempo) mientras el cliente juega. "
            "Vale para todos los operadores."
        )
        explicacion.setWordWrap(True)

        self.campo_tope = QDoubleSpinBox()
        self.campo_tope.setMaximum(99_999_999)
        self.campo_tope.setDecimals(0)
        self.campo_tope.setGroupSeparatorShown(True)
        self.campo_tope.setPrefix("$ ")
        self.campo_tope.setValue(float(reglas["tope"]))
        fila_tope = QHBoxLayout()
        fila_tope.addWidget(QLabel("Tope por PC:"))
        fila_tope.addWidget(self.campo_tope, 1)
        aclaracion = QLabel("En $ 0 no se puede anotar nada a cuenta.")
        aclaracion.setStyleSheet("color: #5F6670; font-size: 12px;")

        self.opcion_no_deja = QRadioButton("No deja anotar más hasta que pague")
        self.opcion_con_clave = QRadioButton("Deja pasarse con la clave de un Administrador")
        self._grupo = QButtonGroup(self)
        self._grupo.addButton(self.opcion_no_deja)
        self._grupo.addButton(self.opcion_con_clave)
        con_clave = reglas["al_pasar_el_tope"] == dominio.TOPE_CUENTA_CON_CLAVE_ADMIN
        (self.opcion_con_clave if con_clave else self.opcion_no_deja).setChecked(True)

        self.casilla_tiempo = QCheckBox("Se puede anotar tiempo (bonos) a cuenta")
        self.casilla_tiempo.setChecked(bool(reglas["tiempo_a_cuenta"]))

        layout = QVBoxLayout()
        layout.addWidget(explicacion)
        layout.addSpacing(6)
        layout.addLayout(fila_tope)
        layout.addWidget(aclaracion)
        layout.addSpacing(6)
        layout.addWidget(QLabel("<b>Si se pasa del tope:</b>"))
        layout.addWidget(self.opcion_no_deja)
        layout.addWidget(self.opcion_con_clave)
        layout.addSpacing(6)
        layout.addWidget(self.casilla_tiempo)
        layout.addStretch()
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        encadenar_enter(self.campo_tope, accion_final=self._guardar)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _guardar(self):
        accion = (dominio.TOPE_CUENTA_CON_CLAVE_ADMIN if self.opcion_con_clave.isChecked()
                  else dominio.TOPE_CUENTA_NO_DEJA)
        cuentas_pc_repo.guardar_reglas(self.usuario["id"], self.campo_tope.value(), accion,
                                       self.casilla_tiempo.isChecked())
        mostrar_info(self, "Guardado", "Listo: las reglas de la Cuenta de la PC quedaron guardadas.")
        self.accept()
