"""
login_window.py
=================
Pantalla de login. Elige el nombre de la persona de una listita
desplegable (en vez de tipearlo, para evitar errores de tipeo y que sea
más cómodo con pantalla táctil) y pide "Clave"; si coinciden, abre la
ventana principal con los permisos que correspondan según el rol
(ADMIN o EMPLEADA).

Desde el 2026-10-30 tiene el diseño "Portal" que eligió el dueño ("demasiado
básica, nuestro programa está a otro nivel"; maqueta D de cinco): el joystick
en el centro de anillos de neón que giran, con estrellas, y el nombre, la clave
y ENTRAR en una fila. Los dibujos están en ui/ingreso_dibujos.py y los colores
de los campos en ui/hoja_de_estilos.py.
"""

import time
from datetime import datetime
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QHBoxLayout, QGridLayout, QComboBox,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt, QPointF, QRect, QTimer
from PySide6.QtGui import QColor, QPainter, QPalette, QPixmap

import dominio
from admin_remoto import modo as modo_remoto
from database import verificar_clave
# El módulo y no las funciones sueltas: en la copia para administrar desde otra
# PC, admin_remoto/cliente.py las cambia por las que le preguntan al mostrador.
from repositories import usuarios_repo
from ui.ingreso_dibujos import CIAN, LADO_DEL_ICONO, VIOLETA, Portal, TextoConDegradado, hora_y_fecha
from ui.utils import mostrar_error, mostrar_aviso, manejar_errores, encadenar_enter

# Mismo ícono que usa main.py para las ventanas (carpeta assets, junto al código).
RUTA_ICONO_PNG = Path(__file__).resolve().parent.parent / "assets" / "icono.png"

# Protección simple contra prueba y error de claves: después de
# MAX_INTENTOS fallidos seguidos con el mismo nombre, se bloquea ese
# nombre por BLOQUEO_SEGUNDOS antes de dejar reintentar. Es un
# diccionario a nivel de módulo (no de instancia) para que el conteo
# sobreviva a un "cerrar sesión" y no se resetee volviendo a abrir la
# pantalla de Login dentro de la misma ejecución del programa.
MAX_INTENTOS = 5
BLOQUEO_SEGUNDOS = 60
_intentos_fallidos = {}  # nombre (en minúsculas) -> (cantidad_seguidos, bloqueado_hasta)

ANCHO, ALTO = 960, 600
# Dónde va el centro de los anillos, y hasta qué altura cambia algo de un cuadro al
# siguiente (los anillos y las estrellas): de ahí para abajo, los campos y ENTRAR
# quedan quietos y no hace falta redibujarlos 30 veces por segundo.
CENTRO_DEL_PORTAL = QPointF(ANCHO / 2, 196)
ALTO_QUE_SE_MUEVE = 430
# Unos 30 cuadros por segundo, como el cometa del mosaico.
MILISEGUNDOS_POR_CUADRO = 33
# El mismo azul noche de QComboBox#nombreIngreso QAbstractItemView en ui/hoja_de_estilos.py.
FONDO_DE_LA_LISTA = "#0B1226"


def _brillo(widget, color: str, radio: int, alfa: int):
    """El resplandor de neón alrededor de un widget. Es un efecto de Qt: el motor de
    hojas de estilo no tiene box-shadow."""
    efecto = QGraphicsDropShadowEffect(widget)
    efecto.setBlurRadius(radio)
    efecto.setOffset(0, 0)
    color_del_brillo = QColor(color)
    color_del_brillo.setAlpha(alfa)
    efecto.setColor(color_del_brillo)
    widget.setGraphicsEffect(efecto)


class _ListaDeNombres(QComboBox):
    """La lista de nombres. Lo que se despliega es una ventanita aparte y la hoja de
    estilos no llega a su marco: quedaban franjas blancas arriba y abajo de los
    nombres sobre el fondo oscuro. Se oscurece con la paleta, solo esa ventanita y
    justo antes de abrirla: puesta antes, la hoja de estilos la pisaba al mostrar
    la pantalla."""

    def showPopup(self):
        desplegable = self.view().window()
        paleta = desplegable.palette()
        paleta.setColor(QPalette.Window, QColor(FONDO_DE_LA_LISTA))
        paleta.setColor(QPalette.Base, QColor(FONDO_DE_LA_LISTA))
        desplegable.setPalette(paleta)
        super().showPopup()


class LoginWindow(QWidget):
    def __init__(self, al_loguearse):
        """
        `al_loguearse` es una función que este cuadro llama apenas el
        login es correcto, pasándole la fila del usuario logueado. La
        usa main.py para abrir la ventana principal.
        """
        super().__init__()
        self._al_loguearse = al_loguearse
        self._inicio = time.monotonic()
        # La animación corre solo mientras la ventana se ve (showEvent / hideEvent).
        self._animacion = QTimer(self)
        self._animacion.setInterval(MILISEGUNDOS_POR_CUADRO)
        self._animacion.timeout.connect(self._siguiente_cuadro)
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.setWindowTitle("CyberBIOS - Ingreso")
        self.setFixedSize(ANCHO, ALTO)
        # El fondo lo pinta entero paintEvent, así Qt no lo borra antes de cada cuadro.
        # Nada de setStyleSheet ni colores de paleta en esta ventana: los avisos y la
        # caja al entrar se abren como hijos suyos y tienen que verse como siempre.
        # Los campos oscuros se pintan por objectName en ui/hoja_de_estilos.py.
        self.setAttribute(Qt.WA_OpaquePaintEvent)

        # El ícono real del programa (el joystick), en el centro de los anillos. Si el
        # archivo no estuviera, los anillos giran igual alrededor del hueco.
        icono = QPixmap(str(RUTA_ICONO_PNG))
        if not icono.isNull():
            escala = self.devicePixelRatioF()
            icono = icono.scaled(int(LADO_DEL_ICONO * escala), int(LADO_DEL_ICONO * escala),
                                 Qt.KeepAspectRatio, Qt.SmoothTransformation)
            icono.setDevicePixelRatio(escala)
        self._portal = Portal(ANCHO, ALTO, CENTRO_DEL_PORTAL, icono)

        titulo = TextoConDegradado("CyberBIOS", ["#FFFFFF", "#BFE9FF"])
        titulo.setObjectName("tituloIngreso")
        _brillo(titulo, CIAN, 34, 190)

        if modo_remoto.es_copia_remota():
            subtitulo = QLabel(
                f"Desde otra PC · mostrador: {modo_remoto.mostrador_en_uso()}\n"
                "Entra solo un Administrador."
            )
        else:
            subtitulo = QLabel("Elegí tu nombre e ingresá la clave para continuar")
        subtitulo.setObjectName("subtituloIngreso")
        subtitulo.setAlignment(Qt.AlignCenter)
        subtitulo.setWordWrap(True)

        # Lista desplegable en vez de campo de texto: se arma de nuevo
        # cada vez que se abre esta pantalla (con listar_usuarios(), sin
        # incluir inactivos) para reflejar altas/bajas recientes de
        # Usuarios sin tener que reiniciar el programa. Se ordena acá
        # con Python (nombre.lower()), no con el ORDER BY del repo: en
        # SQLite el orden por defecto es por valor de byte, así que
        # "admin" (minúscula) quedaría después de cualquier nombre en
        # mayúscula en vez de intercalarse alfabéticamente de verdad.
        self.combo_nombre = _ListaDeNombres()
        self.combo_nombre.setObjectName("nombreIngreso")
        usuarios_ordenados = sorted(usuarios_repo.listar_usuarios(), key=lambda u: u["nombre"].lower())
        for usuario in usuarios_ordenados:
            self.combo_nombre.addItem(usuario["nombre"])
        self.campo_clave = QLineEdit()
        self.campo_clave.setObjectName("claveIngreso")
        self.campo_clave.setEchoMode(QLineEdit.Password)
        # Al apretar Enter en la clave, intenta entrar directamente (más
        # rápido para el uso diario que tener que hacer clic siempre).
        self.campo_clave.returnPressed.connect(self._intentar_ingresar)
        # Enter en el nombre pasa a la clave, como Tab.
        encadenar_enter(self.combo_nombre, self.campo_clave)

        boton_entrar = QPushButton("ENTRAR")
        boton_entrar.setObjectName("botonEntrar")
        boton_entrar.setDefault(True)
        boton_entrar.clicked.connect(self._intentar_ingresar)
        # El brillo se ve porque el botón cuelga de esta ventana (los layouts no
        # recortan): dentro de un widget justo de su tamaño quedaría cortado.
        _brillo(boton_entrar, VIOLETA, 34, 190)

        # Nombre, clave y ENTRAR en una sola fila, cada uno con su rótulo arriba.
        fila = QGridLayout()
        fila.setHorizontalSpacing(14)
        fila.setVerticalSpacing(6)
        for columna, texto in enumerate(("NOMBRE", "CLAVE")):
            rotulo = QLabel(texto)
            rotulo.setObjectName("rotuloIngreso")
            fila.addWidget(rotulo, 0, columna)
        fila.addWidget(self.combo_nombre, 1, 0)
        fila.addWidget(self.campo_clave, 1, 1)
        fila.addWidget(boton_entrar, 1, 2)
        fila.setColumnMinimumWidth(0, 230)
        fila.setColumnMinimumWidth(1, 230)
        fila.setColumnMinimumWidth(2, 160)
        centrada = QHBoxLayout()
        centrada.addStretch()
        centrada.addLayout(fila)
        centrada.addStretch()

        self.reloj = QLabel(hora_y_fecha(datetime.now()))
        self.reloj.setObjectName("relojIngreso")
        self.reloj.setAlignment(Qt.AlignCenter)

        # De arriba abajo: el lugar de los anillos (los dibuja paintEvent), el
        # nombre, la línea de ayuda, la fila para entrar y la hora.
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 18)
        layout.setSpacing(0)
        layout.addSpacing(330)
        layout.addWidget(titulo)
        layout.addWidget(subtitulo)
        layout.addSpacing(22)
        layout.addLayout(centrada)
        layout.addStretch()
        layout.addWidget(self.reloj)
        self.setLayout(layout)

        self.combo_nombre.setFocus()

    def paintEvent(self, _evento):
        pintor = QPainter(self)
        self._portal.pintar(pintor, time.monotonic() - self._inicio, self.devicePixelRatioF())
        pintor.end()

    def showEvent(self, evento):
        super().showEvent(evento)
        self._animacion.start()

    def hideEvent(self, evento):
        # Al entrar, la ventana se cierra (se oculta): sin esto los anillos
        # seguirían girando de fondo todo el turno.
        super().hideEvent(evento)
        self._animacion.stop()

    def _siguiente_cuadro(self):
        if self.isMinimized():
            return
        texto = hora_y_fecha(datetime.now())
        if self.reloj.text() != texto:
            self.reloj.setText(texto)
        self.update(QRect(0, 0, ANCHO, ALTO_QUE_SE_MUEVE))

    @manejar_errores
    def _intentar_ingresar(self):
        if self.combo_nombre.count() == 0:
            mostrar_error(self, "No hay usuarios", "Todavía no hay ningún usuario cargado en el sistema.")
            return

        nombre = self.combo_nombre.currentText().strip()
        clave = self.campo_clave.text()

        if not clave:
            mostrar_error(self, "Falta la clave", "Ingresá tu clave.")
            return

        # Clave del diccionario de intentos fallidos: en minúsculas, para
        # que "Matias" y "matias" compartan el mismo contador (autenticar_por_nombre
        # tampoco distingue mayúsculas al buscar).
        clave_intentos = nombre.lower()

        intentos, bloqueado_hasta = _intentos_fallidos.get(clave_intentos, (0, 0.0))
        ahora = time.monotonic()
        if bloqueado_hasta > ahora:
            segundos_restantes = int(bloqueado_hasta - ahora) + 1
            mostrar_error(
                self, "Demasiados intentos",
                f"Se bloqueó este usuario {segundos_restantes} segundos por varias claves "
                "incorrectas seguidas. Esperá un momento y volvé a intentar."
            )
            self.campo_clave.clear()
            return

        usuario = usuarios_repo.autenticar_por_nombre(nombre, clave)
        if usuario is None:
            intentos += 1
            if intentos >= MAX_INTENTOS:
                _intentos_fallidos[clave_intentos] = (0, ahora + BLOQUEO_SEGUNDOS)
                mostrar_error(
                    self, "Demasiados intentos",
                    f"Usuario bloqueado por {BLOQUEO_SEGUNDOS} segundos por reiteradas claves incorrectas."
                )
            else:
                _intentos_fallidos[clave_intentos] = (intentos, 0.0)
                mostrar_error(self, "Datos incorrectos", "Nombre o clave incorrectos.")
            self.campo_clave.clear()
            self.campo_clave.setFocus()
            return

        _intentos_fallidos.pop(clave_intentos, None)
        self.campo_clave.clear()

        # Aviso suave si el Admin todavía tiene la clave por defecto
        # ("1234") con la que se crea el primer usuario del sistema —
        # no bloquea el ingreso, solo recuerda cambiarla.
        if dominio.es_admin(usuario) and verificar_clave("1234", usuario["clave_hash"]):
            mostrar_aviso(
                self, "Cambiá la clave por defecto",
                "Este usuario Admin todavía tiene la clave de fábrica (1234).\n"
                "Te recomendamos cambiarla desde 'Usuarios' apenas puedas."
            )

        self._al_loguearse(usuario)
