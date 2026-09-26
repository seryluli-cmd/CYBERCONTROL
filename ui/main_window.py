"""
main_window.py
================
Ventana principal: aparece después del login y muestra de entrada la
grilla de "Control de PCs" (`ui/pcs_window.py:PanelControlPcs`) — es lo
que se usa todo el día en el mostrador, así que es la pantalla misma, no
una opción más de un menú. Desde la barra de arriba se llega a Vender
(kiosko), a "Gestionar PCs" (catálogo de Estaciones/Bonos/Miembros) y,
para "encargados", a "Administrar Kiosko" (el resto de las pantallas de
gestión). "Gestionar PCs" se sacó como botón propio de la barra en vez de
quedar un paso adentro de "Administrar Kiosko" porque el operador del
cyber necesita llegar rápido (alta de PC, bono nuevo, carga de saldo a un
socio) — no es una tarea ocasional como Reportes o Compras. Qué se ve
depende del rol y los permisos:

- Cualquiera logueado: operar la grilla de PCs (asignar un bono, abrir
  con Miembro, finalizar sesión — es una venta más, como Vender), Vender,
  Caja, Cierre de Turno, y Cambiar mi Clave.
- Con `permiso_control_pcs` (o Admin): además ve "Gestionar PCs"
  (Estaciones/Bonos/Miembros).
- "Encargado" (ADMIN, o EMPLEADA con al menos uno de los permisos de
  usuarios_repo.PERMISOS_EMPLEADA): además ve "Administrar Kiosko", que
  agrupa Artículos/Compras/Consulta de Ventas/Reportes/Control de
  Cierres, y Usuarios si es Admin (eso no se puede delegar con permisos).
"""

from PySide6.QtWidgets import (
    QMainWindow, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
)
from PySide6.QtCore import Qt

from repositories import usuarios_repo
from ui.articulos_window import ArticulosWindow
from ui.compras_window import ComprasWindow
from ui.ventas_window import VentasWindow
from ui.consulta_ventas_window import ConsultaVentasWindow
from ui.caja_window import CajaWindow, CierreTurnoWindow, ControlCierresWindow
from ui.reportes_window import ReportesWindow
from ui.usuarios_window import UsuariosWindow, DialogoCambiarClave
from ui.pcs_window import PanelControlPcs, DialogoGestionEstaciones, DialogoGestionBonos
from ui.miembros_window import MiembrosWindow
from ui.utils import aplicar_clase


class MainWindow(QMainWindow):
    def __init__(self, usuario, al_cerrar_sesion):
        """
        `usuario` es la fila del usuario logueado (con su rol).
        `al_cerrar_sesion` es una función que se llama al elegir
        "Cerrar sesión", para volver a la pantalla de login.
        """
        super().__init__()
        self.usuario = usuario
        self.es_admin = usuario["rol"] == "ADMIN"
        # "Encargado" no es un rol propio en la base — es un Admin, o una
        # Empleada con al menos uno de los permisos de administración de
        # usuarios_repo.PERMISOS_EMPLEADA. Es el mismo criterio que ya
        # armaba la sección "extras" del menú viejo, ahora usado para
        # decidir si se ve el botón "Administrar Kiosko".
        self._es_encargado = self.es_admin or any(
            usuarios_repo.tiene_permiso(usuario, clave_permiso)
            for clave_permiso, _ in usuarios_repo.PERMISOS_EMPLEADA
        )
        self._al_cerrar_sesion = al_cerrar_sesion
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.setWindowTitle(f"Kiosko - {self.usuario['nombre']} ({self.usuario['rol']})")
        self.resize(980, 680)

        # Misma tarjeta blanca "#encabezadoInicio" que usaba el menú
        # viejo (hoja de estilos global en main.py), ahora como barra
        # horizontal en vez de encabezado vertical.
        barra = QFrame()
        barra.setObjectName("encabezadoInicio")
        layout_barra = QHBoxLayout()
        layout_barra.setContentsMargins(20, 12, 20, 12)
        layout_barra.setSpacing(10)

        titulo = QLabel(f"Hola, {self.usuario['nombre']} · {self.usuario['rol']}")
        titulo.setStyleSheet("font-size: 15px; font-weight: 700; color: #1B2233;")
        layout_barra.addWidget(titulo)
        layout_barra.addStretch()

        self._agregar_boton_barra(layout_barra, "🛒  Vender", self._abrir_ventas, clase="primario")
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_control_pcs"):
            self._agregar_boton_barra(layout_barra, "🖥️  Gestionar PCs", self._abrir_gestionar_pcs)
        if self._es_encargado:
            self._agregar_boton_barra(layout_barra, "🛠️  Administrar Kiosko", self._abrir_administrar_kiosko)
        self._agregar_boton_barra(layout_barra, "💵  Caja", self._abrir_caja)
        self._agregar_boton_barra(layout_barra, "🧾  Cierre de Turno", self._abrir_cierre_turno)
        self._agregar_boton_barra(layout_barra, "🔑  Clave", self._abrir_cambiar_clave)
        self._agregar_boton_barra(layout_barra, "Cerrar sesión", self._cerrar_sesion, clase="peligro")
        barra.setLayout(layout_barra)

        self.panel_pcs = PanelControlPcs(self.usuario, self)

        contenedor = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(barra)
        layout.addWidget(self.panel_pcs, 1)
        contenedor.setLayout(layout)
        self.setCentralWidget(contenedor)

    def _agregar_boton_barra(self, layout, texto, funcion, clase=None):
        """Botón de la barra superior: alto fijo, ancho según el texto
        (a diferencia de los botones grandes y centrados del viejo menú
        principal, acá van en fila y no hace falta que midan todos igual)."""
        boton = QPushButton(texto)
        boton.setFixedHeight(38)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton)
        return boton

    def closeEvent(self, evento):
        # Reemplaza al self.finished.connect(...) que usaban los diálogos
        # con timer propio: QMainWindow no tiene esa señal, closeEvent es
        # el equivalente para parar el refresco automático al cerrar.
        self.panel_pcs.detener_actualizacion()
        super().closeEvent(evento)

    # -----------------------------------------------------------------
    # Cada módulo se abre como una ventana aparte (QDialog), igual que
    # en el sistema original.
    # -----------------------------------------------------------------

    def _abrir_ventas(self):
        VentasWindow(self.usuario, self).exec()

    def _abrir_caja(self):
        CajaWindow(self).exec()

    def _abrir_cierre_turno(self):
        CierreTurnoWindow(self.usuario, self).exec()

    def _abrir_cambiar_clave(self):
        DialogoCambiarClave(self.usuario, self).exec()

    def _abrir_administrar_kiosko(self):
        AdministrarKioskoWindow(self.usuario, self.es_admin, self).exec()

    def _abrir_gestionar_pcs(self):
        GestionarPcsWindow(self.usuario, self.es_admin, self).exec()

    def _cerrar_sesion(self):
        self.close()
        self._al_cerrar_sesion()


class AdministrarKioskoWindow(QDialog):
    """
    Agrupa las pantallas de gestión que antes eran botones sueltos del
    menú principal — ahora detrás de un único acceso ("Administrar
    Kiosko") visible solo para encargados (ver MainWindow._es_encargado).
    Mismo criterio de permisos que usaba el menú viejo: un Admin las ve
    todas, una Empleada solo las que tenga habilitadas en
    usuarios_repo.PERMISOS_EMPLEADA. La gestión del catálogo de PCs
    (Estaciones/Bonos/Miembros) se cuelga acá por ahora, hasta que exista
    una sección de Configuración propia.
    """

    # Mismo criterio que el viejo menú principal: todos los botones del
    # mismo tamaño para que la pantalla quede prolija.
    ANCHO_BOTON = 320
    ALTO_BOTON = 48

    def __init__(self, usuario, es_admin, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = es_admin
        self.setWindowTitle("Administrar Kiosko")
        self.resize(360, 540)
        self._armar_interfaz()

    def _armar_interfaz(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)

        titulo = QLabel("Administrar Kiosko")
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet("font-size: 17px; font-weight: 700; color: #1B2233;")
        layout.addWidget(titulo)
        layout.addSpacing(16)

        botones = []
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_articulos"):
            botones.append(("📦  Artículos", self._abrir_articulos))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_compras"):
            botones.append(("🚚  Compras", self._abrir_compras))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_consulta_ventas"):
            texto_consulta = "🔍  Consulta de Ventas / Anular" if self.es_admin else "🔍  Consulta de Ventas"
            botones.append((texto_consulta, self._abrir_consulta_ventas))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_reportes"):
            botones.append(("📊  Reportes", self._abrir_reportes))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_control_cierres"):
            botones.append(("🗂️  Control de Cierres de Turno", self._abrir_control_cierres))
        if self.es_admin:
            botones.append(("👤  Usuarios", self._abrir_usuarios))

        for texto, funcion in botones:
            self._agregar_boton(layout, texto, funcion)

        layout.addStretch()
        self._agregar_boton(layout, "Cerrar", self.close, clase="peligro")
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _agregar_boton(self, layout, texto, funcion, clase=None):
        boton = QPushButton(texto.upper())
        boton.setFixedSize(self.ANCHO_BOTON, self.ALTO_BOTON)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton, alignment=Qt.AlignHCenter)
        return boton

    def _abrir_articulos(self):
        ArticulosWindow(self).exec()

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


class GestionarPcsWindow(QDialog):
    """
    Administración del catálogo de PCs (Estaciones/Bonos/Miembros), como
    botón propio de la barra superior en vez de un paso más adentro de
    "Administrar Kiosko" — el operador del cyber necesita llegar rápido
    (alta de PC, bono nuevo, carga de saldo a un socio), no es una tarea
    ocasional como Reportes o Compras. Mismo permiso de siempre
    (permiso_control_pcs / Admin), solo cambia dónde se accede.
    """

    ANCHO_BOTON = 320
    ALTO_BOTON = 48

    def __init__(self, usuario, es_admin, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = es_admin
        self.setWindowTitle("Gestionar PCs")
        self.resize(360, 320)
        self._armar_interfaz()

    def _armar_interfaz(self):
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)

        titulo = QLabel("Gestionar PCs")
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet("font-size: 17px; font-weight: 700; color: #1B2233;")
        layout.addWidget(titulo)
        layout.addSpacing(16)

        self._agregar_boton(layout, "🖥️  Gestionar Estaciones", self._abrir_estaciones)
        self._agregar_boton(layout, "🎟️  Gestionar Bonos", self._abrir_bonos)
        self._agregar_boton(layout, "🧑‍🤝‍🧑  Gestionar Miembros", self._abrir_miembros)

        layout.addStretch()
        self._agregar_boton(layout, "Cerrar", self.close, clase="peligro")
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _agregar_boton(self, layout, texto, funcion, clase=None):
        boton = QPushButton(texto.upper())
        boton.setFixedSize(self.ANCHO_BOTON, self.ALTO_BOTON)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton, alignment=Qt.AlignHCenter)
        return boton

    def _abrir_estaciones(self):
        DialogoGestionEstaciones(self).exec()

    def _abrir_bonos(self):
        DialogoGestionBonos(self).exec()

    def _abrir_miembros(self):
        MiembrosWindow(self.usuario, self).exec()
