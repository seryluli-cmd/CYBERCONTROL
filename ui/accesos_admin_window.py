"""
accesos_admin_window.py
=========================
"Accesos de Admin" (Configuración ADMIN): el registro de quién entró con
una cuenta de administrador y cuándo. Exclusiva de ADMIN, igual que el
resto de Configuración ADMIN.

Tiene dos pestañas: los logins en CYBERCONTROL (los lee de la tabla
`sesiones`, que se llena con cada login, vía usuarios_repo.listar_logins)
y lo que pasó en el panel admin de las PCs cliente (quién cerró el Cliente
PC y dejó una PC sin bloqueo, ver control_pcs/ui/accesos_admin_pc_tab.py).
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QLabel, QTableWidgetItem, QComboBox, QTabWidget, QWidget,
)
from PySide6.QtCore import QDate

from repositories import usuarios_repo
from control_pcs.ui.accesos_admin_pc_tab import PestañaAccesosAdminPc
from ui.utils import (
    armar_filtro_por_fechas, manejar_errores, sin_boton_por_defecto, crear_tabla,
)


class AccesosAdminWindow(QDialog):
    """Contenedor de las dos pestañas de accesos de admin."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accesos de Admin")
        self.resize(820, 520)

        pestañas = QTabWidget()
        pestañas.addTab(PestañaLoginsAdmin(), "Logins en CYBERCONTROL")
        pestañas.addTab(PestañaAccesosAdminPc(), "Admin en PCs cliente")

        layout = QVBoxLayout()
        layout.addWidget(pestañas)
        self.setLayout(layout)
        sin_boton_por_defecto(self)


class PestañaLoginsAdmin(QWidget):
    """Cada vez que alguien entró a CYBERCONTROL con usuario y clave. Por
    defecto solo los de rol ADMIN; el combo permite ver también a las
    empleadas (útil para ver quién estaba en el mostrador a cierta hora)."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_quien = QComboBox()
        self.combo_quien.addItem("Solo Admin", True)
        self.combo_quien.addItem("Todos los usuarios", False)
        self.combo_quien.currentIndexChanged.connect(self._buscar)

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, QDate.currentDate().addDays(-7), extras=[("Mostrar:", self.combo_quien)]
        )

        self.etiqueta_cantidad = QLabel()
        self.etiqueta_cantidad.setStyleSheet("font-weight: bold;")

        self.tabla = crear_tabla(["Fecha", "Hora", "Usuario", "Rol"], estirar=2)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_cantidad)
        layout.addWidget(self.tabla)
        self.setLayout(layout)

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" no se usa: currentIndexChanged manda el índice nuevo
        # y, sin él, cambiar el combo tiraba un error en vez de refrescar.
        desde = self.fecha_desde.date().toString("yyyy-MM-dd")
        hasta = self.fecha_hasta.date().toString("yyyy-MM-dd")
        logins = usuarios_repo.listar_logins(desde, hasta, solo_admin=self.combo_quien.currentData())

        self.tabla.setRowCount(0)
        for login in logins:
            momento = datetime.fromisoformat(login["fecha_hora"])
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            for columna, valor in enumerate([
                momento.strftime("%d/%m/%Y"), momento.strftime("%H:%M:%S"), login["nombre"], login["rol"],
            ]):
                self.tabla.setItem(fila, columna, QTableWidgetItem(valor))
        self.etiqueta_cantidad.setText(f"{len(logins)} login(s) en el período")
