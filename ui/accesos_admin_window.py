"""
accesos_admin_window.py
=========================
"Accesos de Admin" (Configuración ADMIN): el registro de quién entró con
una cuenta de administrador y cuándo. Exclusiva de ADMIN, igual que el
resto de Configuración ADMIN.

Tiene dos pestañas: los logins en CYBERCONTROL (los lee de la tabla
`sesiones` vía usuarios_repo.listar_logins; esa tabla ya se llenaba con
cada login, solo faltaba una pantalla para verla) y lo que pasó en el
panel admin de las PCs cliente (quién cerró el Cliente PC y dejó una PC sin
bloqueo, ver control_pcs/ui/accesos_admin_pc_tab.py).
"""

from datetime import datetime, timedelta

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QWidget,
)
from PySide6.QtCore import Qt, QDate

from repositories import usuarios_repo
from control_pcs.ui.accesos_admin_pc_tab import PestañaAccesosAdminPc
from ui.utils import manejar_errores, encadenar_enter


class AccesosAdminWindow(QDialog):
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
        # Evita que Qt elija automaticamente el primer boton como "default"
        # (mismo motivo que en ui/reportes_window.py).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)


class PestañaLoginsAdmin(QWidget):
    """Cada vez que alguien entró a CYBERCONTROL con usuario y clave. Por
    defecto solo los de rol ADMIN; el combo permite ver también a las
    empleadas (útil para ver quién estaba en el mostrador a cierta hora)."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde = QDateEdit(QDate.currentDate().addDays(-7))
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_hasta = QDateEdit(QDate.currentDate())
        self.fecha_hasta.setCalendarPopup(True)

        self.combo_quien = QComboBox()
        self.combo_quien.addItem("Solo Admin", True)
        self.combo_quien.addItem("Todos los usuarios", False)
        self.combo_quien.currentIndexChanged.connect(self._buscar)

        boton_buscar = QPushButton("Buscar")
        boton_buscar.clicked.connect(self._buscar)
        encadenar_enter(self.fecha_desde, self.fecha_hasta, self.combo_quien, accion_final=self._buscar)

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Desde:"))
        filtros.addWidget(self.fecha_desde)
        filtros.addWidget(QLabel("Hasta:"))
        filtros.addWidget(self.fecha_hasta)
        filtros.addWidget(QLabel("Mostrar:"))
        filtros.addWidget(self.combo_quien)
        filtros.addWidget(boton_buscar)
        filtros.addStretch()

        self.etiqueta_cantidad = QLabel()
        self.etiqueta_cantidad.setStyleSheet("font-weight: bold;")

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Fecha", "Hora", "Usuario", "Rol"])
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

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
