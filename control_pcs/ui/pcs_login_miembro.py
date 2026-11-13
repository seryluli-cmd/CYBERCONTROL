"""
pcs_login_miembro.py
====================
El diálogo con el que un socio abre una PC con su usuario y su clave desde el
mostrador ("Abrir con Miembro..." del panel de la PC). Estaba en pcs_detalle.py y se
mudó acá el 2026-11-13, cuando ese archivo pasó las 600 líneas con las ofertas.
"""

from PySide6.QtWidgets import QDialog, QLabel, QLineEdit, QVBoxLayout

from control_pcs.repositories import miembros_repo
from ui.utils import (
    encadenar_enter, fila_guardar_cancelar, formato_tiempo, manejar_errores, mostrar_error, mostrar_info,
    sin_boton_por_defecto,
)


class DialogoLoginMiembro(QDialog):
    """
    A diferencia de vender un bono (lo maneja el Operador, que elige el
    bono desde PanelDetalleEstacion), acá el Miembro se loguea SOLO con
    su usuario y contraseña — pensado para que lo tipee el socio mismo en
    el mostrador. No hay que elegir cuánto tiempo asignar: entrar con las
    credenciales correctas alcanza, se usa todo el saldo disponible en
    ese momento (ver miembros_repo.abrir_estacion_por_miembro).
    """

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Abrir PC con Miembro — {estacion['nombre']}")
        self.resize(340, 200)
        self._armar_interfaz()

    def _armar_interfaz(self):
        etiqueta = QLabel(f"Ingresá tu usuario y contraseña de socio para abrir '{self.estacion['nombre']}':")
        etiqueta.setWordWrap(True)

        self.campo_usuario = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)

        botones = fila_guardar_cancelar(self, self._confirmar, texto_guardar="Ingresar")

        layout = QVBoxLayout()
        layout.addWidget(etiqueta)
        layout.addWidget(QLabel("Usuario:"))
        layout.addWidget(self.campo_usuario)
        layout.addWidget(QLabel("Contraseña:"))
        layout.addWidget(self.campo_clave)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_usuario, self.campo_clave, accion_final=self._confirmar)
        sin_boton_por_defecto(self)
        self.campo_usuario.setFocus()

    @manejar_errores
    def _confirmar(self):
        usuario = self.campo_usuario.text().strip()
        clave = self.campo_clave.text()
        if not usuario or not clave:
            mostrar_error(self, "Faltan datos", "Ingresá tu usuario y tu contraseña.")
            return
        resultado = miembros_repo.abrir_estacion_por_miembro(self.estacion["id"], usuario, clave)
        texto = (f"Hola {resultado['miembro']}, se activó '{self.estacion['nombre']}' con "
                 f"{formato_tiempo(resultado['minutos_usados'] * 60)} de tu saldo.")
        if resultado["hasta_la_reserva"]:
            texto += (f"\n\nLa PC está reservada a las {resultado['hasta_la_reserva']}: se corta a esa hora "
                      "y el resto te queda en el saldo.")
        mostrar_info(self, "PC activada", texto)
        self.accept()
