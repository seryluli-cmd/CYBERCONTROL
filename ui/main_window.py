"""
main_window.py
================
Ventana principal: aparece después del login, con accesos a cada módulo
del sistema. Qué botones se ven depende del rol del usuario logueado:
- EMPLEADA: solo Ventas, Caja y Cierre de Turno.
- ADMIN: todo lo anterior más Artículos, Compras, Consulta de Ventas,
  Reportes y Administración de Usuarios.
"""

from PySide6.QtWidgets import QMainWindow, QWidget, QVBoxLayout, QPushButton, QLabel, QFrame
from PySide6.QtCore import Qt

from ui.articulos_window import ArticulosWindow
from ui.compras_window import ComprasWindow
from ui.ventas_window import VentasWindow
from ui.consulta_ventas_window import ConsultaVentasWindow
from ui.caja_window import CajaWindow, CierreTurnoWindow, ControlCierresWindow
from ui.reportes_window import ReportesWindow
from ui.usuarios_window import UsuariosWindow
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

        titulo = QLabel(f"Hola, {self.usuario['nombre']}")
        titulo.setStyleSheet("font-size: 20px; font-weight: 700; color: #1F2430;")
        titulo.setAlignment(Qt.AlignCenter)
        etiqueta_rol = QLabel(self.usuario["rol"])
        etiqueta_rol.setStyleSheet("color: #6B7280; font-size: 11px; font-weight: 600; letter-spacing: 1px;")
        etiqueta_rol.setAlignment(Qt.AlignCenter)
        layout.addWidget(titulo)
        layout.addWidget(etiqueta_rol)
        layout.addSpacing(22)

        # Botones disponibles para cualquier usuario logueado. Ventas es
        # la acción principal (la que más se usa en el día a día), así
        # que se destaca con el estilo "primario" (azul, más peso visual).
        self._agregar_boton(layout, "🛒  Ventas", self._abrir_ventas, clase="primario")
        self._agregar_boton(layout, "💵  Caja (consulta)", self._abrir_caja)
        self._agregar_boton(layout, "🧾  Cierre de Turno", self._abrir_cierre_turno)

        # Botones solo para Admin, agrupados visualmente con un separador
        # y un subtítulo, para distinguirlos del uso diario de arriba.
        if self.es_admin:
            layout.addSpacing(22)
            separador = QFrame()
            separador.setFrameShape(QFrame.HLine)
            separador.setStyleSheet("color: #D3D8E0;")
            layout.addWidget(separador)
            layout.addSpacing(10)
            subtitulo = QLabel("ADMINISTRACIÓN")
            subtitulo.setAlignment(Qt.AlignCenter)
            subtitulo.setStyleSheet("color: #6B7280; font-size: 11px; font-weight: 700; letter-spacing: 2px;")
            layout.addWidget(subtitulo)
            layout.addSpacing(8)
            self._agregar_boton(layout, "📦  Artículos", self._abrir_articulos)
            self._agregar_boton(layout, "🚚  Compras", self._abrir_compras)
            self._agregar_boton(layout, "🔍  Consulta de Ventas / Anular", self._abrir_consulta_ventas)
            self._agregar_boton(layout, "📊  Reportes", self._abrir_reportes)
            self._agregar_boton(layout, "🗂️  Control de Cierres de Turno", self._abrir_control_cierres)
            self._agregar_boton(layout, "👤  Usuarios", self._abrir_usuarios)

        layout.addStretch()
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

    def _cerrar_sesion(self):
        self.close()
        self._al_cerrar_sesion()
