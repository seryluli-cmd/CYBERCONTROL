"""
main_window.py
================
Ventana principal: aparece después del login y muestra de entrada la
grilla de "Control de PCs" (`control_pcs/ui/pcs_window.py:PanelControlPcs`) — es lo
que se usa todo el día en el mostrador, así que es la pantalla misma, no
una opción más de un menú. Desde la barra de arriba se llega a Vender
(kiosko), a "Trámites" (servicios con monto libre, ej. sacar una boleta de
luz), a "Miembros" (alta/carga de saldo de socios) y, para
"encargados", a "Administrar Kiosko" (el resto de las pantallas de
gestión) y, solo para Admin, a "Configuración ADMIN". Qué se ve depende
del rol y los permisos:

- Cualquiera logueado: operar la grilla de PCs (asignar un bono ya
  creado, abrir con Miembro, finalizar sesión — es una venta más, como
  Vender), Vender, cobrar un Trámite, Caja, Cierre de Turno, y Cambiar mi
  Clave.
- Con `permiso_control_pcs` (o Admin): además ve "Miembros" (alta,
  modificar datos, cargar saldo, desactivar — usa la tarifa y los bonos
  ya definidos, no los edita).
- "Encargado" (ADMIN, o EMPLEADA con al menos uno de los permisos de
  usuarios_repo.PERMISOS_EMPLEADA): además ve "Administrar Kiosko", que
  agrupa Artículos/Compras/Consulta de Ventas/Reportes/Control de
  Cierres, y Usuarios si es Admin (eso no se puede delegar con permisos).
- Solo ADMIN, sin excepción: "Configuración ADMIN" — Gestionar
  Estaciones (agregar/quitar/renombrar PC), Gestionar Bonos (catálogo de
  walk-ins), Tarifa por Hora de Socios, Gestionar Bonos de Socios,
  Gestionar Trámites y Accesos de Admin (registro de logins de
  administradores).
  Pedido explícito del dueño: editar estos catálogos es tarea de super
  admin; usarlos (asignar un bono, cobrar con la tarifa ya fijada) sigue
  delegable con `permiso_control_pcs`.

Cada módulo se abre como un diálogo modal (QDialog.exec) encima de esta
ventana.
"""

from PySide6.QtWidgets import (
    QMainWindow, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
)
from PySide6.QtCore import Qt

import dominio
from repositories import usuarios_repo
from ui.accesos_admin_window import AccesosAdminWindow
from ui.articulos_window import ArticulosWindow
from ui.compras_window import ComprasWindow
from ui.ventas_window import VentasWindow
from ui.consulta_ventas_window import ConsultaVentasWindow
from ui.caja_window import CajaWindow, CierreTurnoWindow, ControlCierresWindow
from ui.reportes_window import ReportesWindow
from ui.tramites_window import DialogoTramites, DialogoGestionTramites
from ui.usuarios_window import UsuariosWindow, DialogoCambiarClave
from control_pcs.ui.pcs_window import PanelControlPcs
from control_pcs.ui.pcs_gestion_dialogos import DialogoGestionEstaciones, DialogoGestionBonos
from control_pcs.ui.miembros_window import MiembrosWindow, DialogoTramosTarifaMiembro, DialogoGestionBonosMiembro
from ui.utils import aplicar_clase, sin_boton_por_defecto


class MainWindow(QMainWindow):
    """Barra de botones (según rol y permisos) y, debajo, la grilla de PCs."""

    def __init__(self, usuario, al_cerrar_sesion):
        """
        `usuario` es la fila del usuario logueado (con su rol).
        `al_cerrar_sesion` es una función que se llama al elegir
        "Cerrar sesión", para volver a la pantalla de login.
        """
        super().__init__()
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        # "Encargado" no es un rol propio en la base — es un Admin, o una
        # Empleada con al menos uno de los permisos de administración de
        # usuarios_repo.PERMISOS_EMPLEADA. Decide si se ve el botón
        # "Administrar Kiosko".
        self._es_encargado = self.es_admin or any(
            usuarios_repo.tiene_permiso(usuario, clave_permiso)
            for clave_permiso, _ in usuarios_repo.PERMISOS_EMPLEADA
        )
        self._al_cerrar_sesion = al_cerrar_sesion
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.setWindowTitle(f"CYBERBIOS - {self.usuario['nombre']} ({self.usuario['rol']})")
        self.resize(980, 680)

        # Tarjeta blanca "#encabezadoInicio" (estilo en la hoja de estilos
        # global de main.py), armada como barra horizontal.
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
        self._agregar_boton_barra(layout_barra, "📄  Trámites", self._abrir_tramites)
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_control_pcs"):
            self._agregar_boton_barra(layout_barra, "🧑‍🤝‍🧑  Miembros", self._abrir_miembros)
        if self._es_encargado:
            self._agregar_boton_barra(layout_barra, "🛠️  Administrar Kiosko", self._abrir_administrar_kiosko)
        if self.es_admin:
            self._agregar_boton_barra(layout_barra, "⚙️  Configuración ADMIN", self._abrir_configuracion_admin)
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
        (van en fila, así que no hace falta que midan todos igual)."""
        boton = QPushButton(texto)
        boton.setFixedHeight(38)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton)
        return boton

    def closeEvent(self, evento):
        # QMainWindow no tiene la señal `finished` de los QDialog, así que
        # el refresco automático de la grilla de PCs se frena acá, al cerrar.
        self.panel_pcs.detener_actualizacion()
        super().closeEvent(evento)

    # -----------------------------------------------------------------
    # Abrir cada módulo (diálogos modales)
    # -----------------------------------------------------------------

    def _abrir_ventas(self):
        VentasWindow(self.usuario, self).exec()

    def _abrir_tramites(self):
        DialogoTramites(self.usuario, self).exec()

    def _abrir_caja(self):
        CajaWindow(self).exec()

    def _abrir_cierre_turno(self):
        dialogo = CierreTurnoWindow(self.usuario, self)
        dialogo.exec()
        # Cerrar un turno implica que ya llegó el relevo -- en vez de
        # dejar la sesión de quien cerró abierta, se vuelve sola al Login
        # (mismo camino que el botón "Cerrar sesión") para que la próxima
        # persona entre con su propio usuario. Si se canceló el diálogo
        # sin confirmar el cierre (turno_cerrado sigue en False), no pasa
        # nada -- sigue todo como estaba.
        if dialogo.turno_cerrado:
            self._cerrar_sesion()

    def _abrir_cambiar_clave(self):
        DialogoCambiarClave(self.usuario, self).exec()

    def _abrir_administrar_kiosko(self):
        AdministrarKioskoWindow(self.usuario, self.es_admin, self).exec()

    def _abrir_miembros(self):
        MiembrosWindow(self.usuario, self).exec()

    def _abrir_configuracion_admin(self):
        ConfiguracionAdminWindow(self).exec()

    def _cerrar_sesion(self):
        self.close()
        self._al_cerrar_sesion()


class _VentanaDeBotones(QDialog):
    """
    Diálogo angosto con un título y una columna de botones grandes, todos
    del mismo tamaño para que la pantalla quede prolija, y un "Cerrar" al
    final. Es la base de "Administrar Kiosko" y de "Configuración ADMIN":
    cada una dice qué botones tiene (`_armar_botones`) y qué hace cada uno.
    """

    ANCHO_BOTON = 320
    ALTO_BOTON = 48

    def __init__(self, titulo: str, alto: int, parent=None):
        super().__init__(parent)
        self._titulo = titulo
        self.setWindowTitle(titulo)
        self.resize(360, alto)

    def _armar_botones(self, botones: list):
        """`botones`: lista de (texto, función), en el orden en que se ven."""
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)

        titulo = QLabel(self._titulo)
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet("font-size: 17px; font-weight: 700; color: #1B2233;")
        layout.addWidget(titulo)
        layout.addSpacing(16)

        for texto, funcion in botones:
            self._agregar_boton(layout, texto, funcion)

        layout.addStretch()
        self._agregar_boton(layout, "Cerrar", self.close, clase="peligro")
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_boton(self, layout, texto, funcion, clase=None):
        boton = QPushButton(texto.upper())
        boton.setFixedSize(self.ANCHO_BOTON, self.ALTO_BOTON)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton, alignment=Qt.AlignHCenter)
        return boton


class AdministrarKioskoWindow(_VentanaDeBotones):
    """
    Agrupa las pantallas de gestión del kiosko detrás de un único acceso
    ("Administrar Kiosko"), visible solo para encargados (ver
    MainWindow._es_encargado). Un Admin las ve todas; una Empleada solo las
    que tenga habilitadas en usuarios_repo.PERMISOS_EMPLEADA.
    """

    def __init__(self, usuario, es_admin, parent=None):
        super().__init__("Administrar Kiosko", 540, parent)
        self.usuario = usuario
        self.es_admin = es_admin
        self._armar_interfaz()

    def _armar_interfaz(self):
        # (permiso que la habilita, texto, qué abre). "Usuarios" no está
        # acá: es solo del Admin, no se delega con ningún permiso.
        pantallas = [
            ("permiso_articulos", "📦  Artículos", self._abrir_articulos),
            ("permiso_compras", "🚚  Compras", self._abrir_compras),
            ("permiso_consulta_ventas",
             "🔍  Consulta de Ventas / Anular" if self.es_admin else "🔍  Consulta de Ventas",
             self._abrir_consulta_ventas),
            ("permiso_reportes", "📊  Reportes", self._abrir_reportes),
            ("permiso_control_cierres", "🗂️  Control de Cierres de Turno", self._abrir_control_cierres),
        ]
        botones = [
            (texto, funcion) for permiso, texto, funcion in pantallas
            if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, permiso)
        ]
        if self.es_admin:
            botones.append(("👤  Usuarios", self._abrir_usuarios))
        self._armar_botones(botones)

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


class ConfiguracionAdminWindow(_VentanaDeBotones):
    """
    Agrupa las pantallas de EDICIÓN de catálogos -- Estaciones, Bonos de
    Tiempo (walk-in), Tarifa por Hora de Socios, Bonos de Socios y Trámites
    -- más "Accesos de Admin" (quién entró con una cuenta de administrador, ver
    ui/accesos_admin_window.py). Exclusiva de ADMIN, sin excepción: no hay
    permiso delegable para esto (ver MainWindow._armar_interfaz).

    *Usar* esos catálogos (asignarle un bono ya creado a una PC, cargar
    saldo con la tarifa ya fijada) sigue abierto a cualquier operador con
    permiso_control_pcs desde la grilla de PCs y "Miembros". Separación
    pedida explícitamente por el dueño: editar el catálogo es tarea de
    super admin, usarlo no.
    """

    def __init__(self, parent=None):
        super().__init__("Configuración ADMIN", 520, parent)
        self._armar_botones([
            ("🖥️  Gestionar Estaciones", self._abrir_estaciones),
            ("🎟️  Gestionar Bonos", self._abrir_bonos),
            ("💲  Tarifa por Hora de Socios", self._configurar_tarifa),
            ("🎁  Gestionar Bonos de Socios", self._abrir_bonos_miembro),
            ("📄  Gestionar Trámites", self._abrir_tramites),
            ("🔐  Accesos de Admin", self._abrir_accesos_admin),
        ])

    def _abrir_estaciones(self):
        DialogoGestionEstaciones(self).exec()

    def _abrir_bonos(self):
        DialogoGestionBonos(self).exec()

    def _configurar_tarifa(self):
        DialogoTramosTarifaMiembro(self).exec()

    def _abrir_bonos_miembro(self):
        DialogoGestionBonosMiembro(self).exec()

    def _abrir_tramites(self):
        DialogoGestionTramites(self).exec()

    def _abrir_accesos_admin(self):
        AccesosAdminWindow(self).exec()
