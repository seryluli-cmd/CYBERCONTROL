"""
accesos_admin_window.py
=========================
"Accesos de Admin" (Configuración ADMIN): el registro de quién entró con
una cuenta de administrador y cuándo. Exclusiva de ADMIN, igual que el
resto de Configuración ADMIN.

Tiene dos pestañas: los logins en CYBERCONTROL (los lee de la tabla
`sesiones`, que se llena con cada login, vía usuarios_repo.listar_logins; dice
si fue en el mostrador o desde otra PC del local, con su IP)
y lo que pasó en el panel admin de las PCs cliente (quién cerró el Cliente
PC y dejó una PC sin bloqueo, ver control_pcs/ui/accesos_admin_pc_tab.py).
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QVBoxLayout, QTableWidgetItem, QComboBox, QTabWidget, QWidget,
)
from PySide6.QtCore import QDate

import dominio
from repositories import usuarios_repo
from control_pcs.ui.accesos_admin_pc_tab import PestañaAccesosAdminPc
from ui.dibujos_tabla import DelegadoEtiqueta
from ui.piezas_ventana import (
    agregar_indicador, cabecera_oscura, panel_de_tabla, pie_de_ventana, poner_indicador, tecla,
)
from ui.utils import (
    armar_filtro_por_fechas, manejar_errores, sin_boton_por_defecto, crear_tabla,
    mostrar_columna_entera, rango_de_fechas,
)

COLUMNA_ROL = 3
COLUMNA_DESDE = 4


class AccesosAdminWindow(QDialog):
    """Contenedor de las dos pestañas de accesos de admin.

    Con la maqueta B que eligió el dueño para el kiosko el 2026-10-30 y pidió también
    acá (como Artículos): la cabecera oscura con los números de los logins que se
    están mirando, arriba de las pestañas; adentro, las fechas y la grilla en su
    panel, con el rol en una etiqueta de color."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Accesos de Admin")
        self.resize(1000, 640)

        cabecera = cabecera_oscura("🔐", "Accesos de Admin", "Quién entró al programa, cuándo y desde qué PC")
        self.indicador_ingresos = agregar_indicador(cabecera, "Ingresos")
        self.indicador_personas = agregar_indicador(cabecera, "Personas")
        self.indicador_otra_pc = agregar_indicador(cabecera, "Desde otra PC")

        pestañas = QTabWidget()
        pestañas.addTab(PestañaLoginsAdmin(self._poner_numeros), "Logins en CYBERCONTROL")
        pestañas.addTab(PestañaAccesosAdminPc(), "Admin en PCs cliente")

        abajo = QHBoxLayout()
        abajo.addWidget(pie_de_ventana(
            "Los números de arriba son de los logins en CYBERCONTROL  ·  \"Otra PC\" es la copia para "
            "administrar desde otra PC del local, con la IP de esa PC"), 1)
        abajo.addWidget(tecla("CERRAR", self.close))

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(pestañas, 1)
        layout.addLayout(abajo)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _poner_numeros(self, logins):
        """Los números de la cabecera: de los ingresos que muestra la grilla."""
        poner_indicador(self.indicador_ingresos, str(len(logins)))
        poner_indicador(self.indicador_personas, str(len({login["nombre"] for login in logins})))
        poner_indicador(self.indicador_otra_pc, str(sum(1 for login in logins if login["desde_ip"])))


class PestañaLoginsAdmin(QWidget):
    """Cada vez que alguien entró a CYBERCONTROL con usuario y clave. Por
    defecto solo los de rol ADMIN; el combo permite ver también a las
    empleadas (útil para ver quién estaba en el mostrador a cierta hora).
    `al_buscar(logins)`, si se pasa, recibe lo encontrado en cada búsqueda (la
    ventana pone ahí sus números)."""

    def __init__(self, al_buscar=None):
        super().__init__()
        self._al_buscar = al_buscar
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

        self.tabla = crear_tabla(["Fecha", "Hora", "Usuario", "Rol", "Desde"], estirar=2)
        etiqueta_rol = DelegadoEtiqueta(self.tabla)
        etiqueta_rol.colores_en_orden(dominio.ROLES)
        self.tabla.setItemDelegateForColumn(COLUMNA_ROL, etiqueta_rol)
        self.tabla.setColumnWidth(0, 130)
        self.tabla.setColumnWidth(1, 110)
        self.tabla.setColumnWidth(COLUMNA_ROL, 150)
        self.tabla.setColumnWidth(COLUMNA_DESDE, 200)

        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addLayout(filtros)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        self.setLayout(layout)

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" no se usa: currentIndexChanged manda el índice nuevo
        # y, sin él, cambiar el combo tiraba un error en vez de refrescar.
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        logins = usuarios_repo.listar_logins(desde, hasta, solo_admin=self.combo_quien.currentData())

        self.tabla.setRowCount(0)
        for login in logins:
            momento = datetime.fromisoformat(login["fecha_hora"])
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            # El Administrador puede entrar desde otra PC del local (admin_remoto/):
            # ahí queda anotada la IP de esa PC.
            desde = f"Otra PC ({login['desde_ip']})" if login["desde_ip"] else "Mostrador"
            for columna, valor in enumerate([
                momento.strftime("%d/%m/%Y"), momento.strftime("%H:%M:%S"), login["nombre"], login["rol"], desde,
            ]):
                self.tabla.setItem(fila, columna, QTableWidgetItem(valor))
        mostrar_columna_entera(self.tabla, COLUMNA_DESDE)  # "Otra PC (192.168.0.25)" no entra en el ancho de siempre
        if self._al_buscar is not None:
            self._al_buscar(logins)
