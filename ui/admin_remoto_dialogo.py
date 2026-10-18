"""
admin_remoto_dialogo.py
========================
"Entrar desde otra PC" (Configuración ADMIN, solo en el mostrador): prender o
apagar que el Administrador administre desde otra PC del local, con los pasos
para hacerlo. La regla (viene apagado, solo Admin) vive en
repositories/admin_remoto_repo.py; cómo viaja cada pedido, en admin_remoto/.
"""

import socket

from PySide6.QtWidgets import QCheckBox, QDialog, QLabel, QVBoxLayout

from repositories import admin_remoto_repo
from ui.utils import fila_guardar_cancelar, manejar_errores, mostrar_info, sin_boton_por_defecto


def _nombre_y_ips_de_esta_pc():
    """El nombre de esta PC en la red y sus IP del local (para escribir la
    carpeta compartida en la otra PC). Si Windows no las da, lo que haya."""
    nombre = socket.gethostname()
    try:
        ips = sorted({ip for ip in socket.gethostbyname_ex(nombre)[2] if not ip.startswith("127.")})
    except OSError:
        ips = []
    return nombre, ips


class DialogoEntrarDesdeOtraPC(QDialog):
    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Entrar desde otra PC")
        self.resize(560, 470)
        self._armar_interfaz()

    def _armar_interfaz(self):
        nombre, ips = _nombre_y_ips_de_esta_pc()
        ips_texto = " o ".join(ips) if ips else "(no se pudo saber)"

        titulo = QLabel("🌐  Entrar desde otra PC del local")
        titulo.setStyleSheet("font-size: 17px; font-weight: 700; color: #1B2233;")

        explicacion = QLabel(
            "Con esto prendido, el <b>Administrador</b> puede administrar desde otra PC del local "
            "(artículos y precios, compras, ventas, reportes, cierres, usuarios y Configuración ADMIN) "
            "mientras acá se sigue atendiendo normal. Los datos son siempre los de esta PC: la otra "
            "no tiene base propia.<br><br>"
            "<b>Cómo se entra:</b><ol>"
            "<li>Compartí en la red la carpeta donde está CyberBios.exe (con contraseña).</li>"
            "<li>En la otra PC, abrí CyberBios.exe <b>desde esa carpeta compartida</b>. Si la "
            "carpeta se comparte con el nombre CyberBios, es:<br>"
            f"<b>\\\\{nombre}\\CyberBios\\CyberBios.exe</b></li>"
            "<li>Entrá con el usuario Administrador y su clave.</li></ol>"
            f"Esta PC es <b>{nombre}</b> (IP {ips_texto}). Este programa tiene que estar abierto acá.<br><br>"
            "Las empleadas no pueden entrar desde otra PC. Vender, cobrar, cerrar el turno y atender las "
            "PCs se sigue haciendo solo acá."
        )
        explicacion.setWordWrap(True)

        self.check_activo = QCheckBox("Permitir que el Administrador entre desde otra PC")
        self.check_activo.setChecked(admin_remoto_repo.esta_activo())

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 20)
        layout.addWidget(titulo)
        layout.addWidget(explicacion)
        layout.addSpacing(8)
        layout.addWidget(self.check_activo)
        layout.addStretch()
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _guardar(self):
        activo = self.check_activo.isChecked()
        admin_remoto_repo.activar(self.usuario["id"], activo)
        mostrar_info(
            self, "Listo",
            "La entrada desde otra PC quedó PRENDIDA." if activo else
            "La entrada desde otra PC quedó APAGADA (si alguien estaba adentro desde otra PC, ya no puede seguir).",
        )
        self.accept()
