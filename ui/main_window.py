"""
main_window.py
================
Ventana principal: aparece después del login, con accesos a cada módulo
del sistema. Qué botones se ven depende del rol y los permisos del
usuario logueado:
- Cualquiera: Ventas, Caja, Cierre de Turno, y Cambiar mi Clave.
- EMPLEADA: además, Artículos/Compras/Consulta de Ventas (sin Anular)/
  Reportes/Control de Cierres si el Admin le dio el permiso puntual
  correspondiente (ver usuarios_repo.PERMISOS_EMPLEADA).
- ADMIN: todo lo anterior siempre, más Administración de Usuarios (esto
  no se puede delegar con permisos).
"""

from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFrame
from PySide6.QtCore import Qt

from repositories import usuarios_repo
from ui.articulos_window import ArticulosWindow
from ui.compras_window import ComprasWindow
from ui.ventas_window import VentasWindow
from ui.consulta_ventas_window import ConsultaVentasWindow
from ui.caja_window import CajaWindow, CierreTurnoWindow, ControlCierresWindow
from ui.reportes_window import ReportesWindow
from ui.usuarios_window import UsuariosWindow, DialogoCambiarClave
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
        self._al_cerrar_sesion = al_cerrar_sesion
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.setWindowTitle(f"Kiosko - {self.usuario['nombre']} ({self.usuario['rol']})")
        self.resize(460, 640)
        # No se le pone un setStyleSheet propio a esta ventana (el fondo
        # ya lo define "QMainWindow { background-color: ... }" en la hoja
        # de estilos global de main.py): ponerle una hoja de estilos LOCAL
        # acá rompe la cascada de las reglas [clase="primario"/"peligro"]
        # para los botones de más abajo (limitación del motor de QSS de
        # Qt: un widget con su propia hoja de estilos deja de heredar
        # bien los selectores complejos de la hoja de estilos de la app).

        contenedor = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(28, 26, 28, 26)
        layout.setSpacing(4)

        # Encabezado en tarjeta (mismo patrón que "#tarjetaLogin" en
        # main.py): un objectName + estilo en la hoja GLOBAL, no un
        # setStyleSheet local acá — eso rompería la cascada de las
        # reglas [clase="primario"/"peligro"] de los botones de abajo.
        encabezado = QFrame()
        encabezado.setObjectName("encabezadoInicio")
        layout_encabezado = QVBoxLayout()
        layout_encabezado.setContentsMargins(20, 16, 20, 16)
        layout_encabezado.setSpacing(4)
        titulo = QLabel(f"Hola, {self.usuario['nombre']}")
        titulo.setStyleSheet("font-size: 19px; font-weight: 700; color: #1B2233;")
        titulo.setAlignment(Qt.AlignCenter)
        etiqueta_rol = QLabel(self.usuario["rol"])
        etiqueta_rol.setStyleSheet("color: #2F6FED; font-size: 11px; font-weight: 700; letter-spacing: 1.2px;")
        etiqueta_rol.setAlignment(Qt.AlignCenter)
        layout_encabezado.addWidget(titulo)
        layout_encabezado.addWidget(etiqueta_rol)
        encabezado.setLayout(layout_encabezado)

        layout.addWidget(encabezado)
        layout.addSpacing(22)

        # Botones disponibles para cualquier usuario logueado. Ventas es
        # la acción principal (la que más se usa en el día a día), así
        # que se destaca con el estilo "primario" (azul, más peso visual).
        self._agregar_boton(layout, "🛒  Vender", self._abrir_ventas, clase="primario")
        self._agregar_boton(layout, "💵  Caja (consulta)", self._abrir_caja)
        self._agregar_boton(layout, "🧾  Cierre de Turno", self._abrir_cierre_turno)

        # Botones extra según rol/permisos, agrupados visualmente con un
        # separador y un subtítulo para distinguirlos del uso diario de
        # arriba. Un Admin los ve todos siempre; una Empleada solo ve los
        # que tenga habilitados en usuarios_repo.PERMISOS_EMPLEADA (ver
        # tiene_permiso) — "Usuarios" queda exclusivo de Admin, no se
        # puede delegar. Si a una Empleada no le dieron ningún permiso,
        # la sección entera no aparece.
        extras = []
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_articulos"):
            extras.append(("📦  Artículos", self._abrir_articulos))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_compras"):
            extras.append(("🚚  Compras", self._abrir_compras))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_consulta_ventas"):
            texto_consulta = "🔍  Consulta de Ventas / Anular" if self.es_admin else "🔍  Consulta de Ventas"
            extras.append((texto_consulta, self._abrir_consulta_ventas))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_reportes"):
            extras.append(("📊  Reportes", self._abrir_reportes))
        if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_control_cierres"):
            extras.append(("🗂️  Control de Cierres de Turno", self._abrir_control_cierres))
        if self.es_admin:
            extras.append(("👤  Usuarios", self._abrir_usuarios))

        if extras:
            layout.addSpacing(22)
            separador = QFrame()
            separador.setFrameShape(QFrame.HLine)
            separador.setStyleSheet("color: #D3D8E0;")
            layout.addWidget(separador)
            layout.addSpacing(10)
            subtitulo = QLabel("ADMINISTRACIÓN" if self.es_admin else "PERMISOS EXTRA")
            subtitulo.setAlignment(Qt.AlignCenter)
            subtitulo.setStyleSheet("color: #6B7280; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
            layout.addWidget(subtitulo)
            layout.addSpacing(8)
            for texto, funcion in extras:
                self._agregar_boton(layout, texto, funcion)

        layout.addStretch()
        # Disponible para cualquier usuario logueado (Admin o Empleada):
        # antes solo el Admin podía cambiar la clave de alguien desde
        # Usuarios, así que una Empleada no tenía forma de cambiar la
        # suya propia sin pedírselo al Admin.
        self._agregar_boton(layout, "🔑  Cambiar mi Clave", self._abrir_cambiar_clave)
        self._agregar_boton(layout, "Cerrar sesión", self._cerrar_sesion, clase="peligro")

        contenedor.setLayout(layout)
        self.setCentralWidget(contenedor)

    # Ancho y alto fijos para que TODOS los botones del menú principal
    # queden exactamente del mismo tamaño, sin importar cuánto texto
    # tengan (algunas opciones tienen nombres más largos que otras).
    ANCHO_BOTON = 320
    ALTO_BOTON = 48

    def _agregar_boton(self, layout, texto, funcion, clase=None):
        """Crea un botón del menú principal (en MAYÚSCULA, tamaño fijo
        e igual para todos) y lo agrega centrado al layout. `clase`
        opcionalmente le da el estilo "primario" (acción principal) o
        "peligro" (cerrar sesión), definidos en la hoja de estilos global."""
        boton = QPushButton(texto.upper())
        boton.setFixedSize(self.ANCHO_BOTON, self.ALTO_BOTON)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton, alignment=Qt.AlignHCenter)
        return boton

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

    def _abrir_cambiar_clave(self):
        DialogoCambiarClave(self.usuario, self).exec()

    def _cerrar_sesion(self):
        self.close()
        self._al_cerrar_sesion()
