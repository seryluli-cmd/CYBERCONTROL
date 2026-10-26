"""
ui/administrar_kiosko_window.py
===============================
La ventana "Administrar Kiosko" (botón 🛠️ ADMIN KIOSKO de la barra). Estaba en
ui/main_window.py y se mudó acá el 2026-10-26, cuando el dueño pidió que tuviera el
mismo diseño que Configuración ADMIN ("usa el mismo criterio que en los anteriores
diseños"): cabecera oscura y tarjetas agrupadas, con las piezas de
ui/piezas_ventana.py. Los botones hacen lo mismo que antes.
"""

from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QVBoxLayout

from repositories import usuarios_repo
from ui.articulos_window import ArticulosWindow
from ui.caja_window import ControlCierresWindow
from ui.compras_window import ComprasWindow
from ui.consulta_ventas_window import ConsultaVentasWindow
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, agregar_pastilla, bloquear_tarjeta, cabecera_oscura, tarjeta_de_menu, tecla,
    titulo_de_seccion,
)
from ui.reportes_window import ReportesWindow
from ui.usuarios_window import UsuariosWindow
from ui.utils import sin_boton_por_defecto

# Lo que dice una tarjeta que la encargada no tiene habilitada.
TEXTO_SIN_PERMISO = "Sin permiso: lo habilita el Admin en Usuarios"


class AdministrarKioskoWindow(QDialog):
    """
    Agrupa las pantallas de gestión del kiosko detrás de un único acceso
    ("Administrar Kiosko"), que solo abren los encargados (ver
    MainWindow._es_encargado). Un Admin las usa todas; una Empleada solo las
    que tenga habilitadas en usuarios_repo.PERMISOS_EMPLEADA. Las demás las ve en
    gris y con candado (desde el 2026-10-26, como en Configuración ADMIN; antes no
    aparecían). "Usuarios" es solo del Admin: no se delega con ningún permiso.
    """

    def __init__(self, usuario, es_admin, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = es_admin
        self.setWindowTitle("Administrar Kiosko")
        self.resize(660, 470)
        self._armar_interfaz()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura(
            "🛠️", "Administrar Kiosko",
            f"{self.usuario['nombre']} · "
            + ("Administrador" if self.es_admin else "Encargado: usa lo que tiene habilitado"),
        )
        agregar_pastilla(cabecera, "ADMIN" if self.es_admin else "ENCARGADO", TONO_AZUL if self.es_admin else TONO_GRIS)

        # (permiso que la habilita, dibujito, título, para qué es, qué abre). Usuarios
        # no tiene permiso: es solo del Admin.
        grupos = [
            ("Mercadería", [
                ("permiso_articulos", "📦", "Artículos", "Precios, stock, rubros y marcas", self._abrir_articulos),
                ("permiso_compras", "🚚", "Compras", "La mercadería que entra al kiosko", self._abrir_compras),
            ]),
            ("Ventas", [
                ("permiso_consulta_ventas", "🔍",
                 "Consulta de Ventas / Anular" if self.es_admin else "Consulta de Ventas",
                 "Buscar una venta, ver qué se vendió y anularla" if self.es_admin
                 else "Buscar una venta y ver qué se vendió",
                 self._abrir_consulta_ventas),
                ("permiso_reportes", "📊", "Reportes", "Resumen del día, totales y por operador", self._abrir_reportes),
            ]),
            ("Caja y personal", [
                ("permiso_control_cierres", "🗂️", "Control de Cierres de Turno", "Cada cierre de caja y su sobre",
                 self._abrir_control_cierres),
                (None, "👤", "Usuarios", "Quién entra, claves, permisos y copias", self._abrir_usuarios),
            ]),
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(cabecera)
        for titulo, tarjetas in grupos:
            layout.addSpacing(4)
            layout.addWidget(titulo_de_seccion(titulo))
            grilla = QGridLayout()
            grilla.setSpacing(10)
            for numero, (permiso, icono, nombre, detalle, funcion) in enumerate(tarjetas):
                tarjeta = tarjeta_de_menu(icono, nombre, detalle, funcion)
                if permiso is None and not self.es_admin:
                    bloquear_tarjeta(tarjeta)
                elif permiso and not (self.es_admin or usuarios_repo.tiene_permiso(self.usuario, permiso)):
                    bloquear_tarjeta(tarjeta, TEXTO_SIN_PERMISO)
                grilla.addWidget(tarjeta, numero // 2, numero % 2)
            grilla.setColumnStretch(0, 1)
            grilla.setColumnStretch(1, 1)
            layout.addLayout(grilla)
        layout.addStretch()

        pie = QHBoxLayout()
        pie.addStretch()
        pie.addWidget(tecla("CERRAR", self.close, "teclaRoja"))
        layout.addLayout(pie)
        sin_boton_por_defecto(self)

    def _abrir_articulos(self):
        ArticulosWindow(self, self.usuario).exec()

    def _abrir_compras(self):
        ComprasWindow(self.usuario, self).exec()

    def _abrir_consulta_ventas(self):
        ConsultaVentasWindow(self.usuario, self).exec()

    def _abrir_reportes(self):
        ReportesWindow(self).exec()

    def _abrir_control_cierres(self):
        ControlCierresWindow(self.usuario, self).exec()

    def _abrir_usuarios(self):
        UsuariosWindow(self.usuario, self).exec()
