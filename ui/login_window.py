"""
login_window.py
=================
Pantalla de login. Elige el nombre de la persona de una listita
desplegable (en vez de tipearlo, para evitar errores de tipeo y que sea
más cómodo con pantalla táctil) y pide "Clave"; si coinciden, abre la
ventana principal con los permisos que correspondan según el rol
(ADMIN o EMPLEADA).
"""

import time
from pathlib import Path

from PySide6.QtWidgets import (
    QWidget, QLabel, QLineEdit, QPushButton, QVBoxLayout, QFormLayout, QFrame, QComboBox,
    QGraphicsDropShadowEffect
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QPalette, QColor, QPixmap

import dominio
from database import verificar_clave
from repositories.usuarios_repo import autenticar_por_nombre, listar_usuarios
from ui.utils import mostrar_error, mostrar_aviso, manejar_errores, aplicar_clase

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


class LoginWindow(QWidget):
    def __init__(self, al_loguearse):
        """
        `al_loguearse` es una función que este cuadro llama apenas el
        login es correcto, pasándole la fila del usuario logueado. La
        usa main.py para abrir la ventana principal.
        """
        super().__init__()
        self._al_loguearse = al_loguearse
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.setWindowTitle("CYBERBIOS - Ingreso")
        self.setFixedSize(400, 420)
        # Fondo gris claro detrás de la tarjeta blanca, para que la
        # tarjeta se destaque en vez de que todo sea un único blanco liso.
        # Se hace con QPalette (no setStyleSheet): ponerle una hoja de
        # estilos LOCAL a esta ventana rompe la cascada de la regla
        # [clase="primario"] de la hoja de estilos global para el botón
        # "Entrar" de más abajo (limitación del motor de QSS de Qt).
        self.setAutoFillBackground(True)
        paleta = self.palette()
        paleta.setColor(QPalette.Window, QColor("#EEF1F6"))
        self.setPalette(paleta)

        # El ícono real del programa (la caja registradora). Si el archivo no
        # estuviera, se cae al emoji de siempre en vez de dejar el hueco vacío.
        icono = QLabel()
        imagen = QPixmap(str(RUTA_ICONO_PNG))
        if imagen.isNull():
            icono.setText("🏪")
            icono.setStyleSheet("font-size: 42px;")
        else:
            icono.setPixmap(imagen.scaled(64, 64, Qt.KeepAspectRatio, Qt.SmoothTransformation))
        icono.setAlignment(Qt.AlignCenter)

        titulo = QLabel("Sistema de Kiosko")
        titulo.setStyleSheet("font-size: 21px; font-weight: 700; color: #1F2430;")
        titulo.setAlignment(Qt.AlignCenter)

        subtitulo = QLabel("Elegí tu nombre e ingresá la clave para continuar")
        subtitulo.setStyleSheet("color: #6B7280; font-size: 12px;")
        subtitulo.setAlignment(Qt.AlignCenter)

        # Lista desplegable en vez de campo de texto: se arma de nuevo
        # cada vez que se abre esta pantalla (con listar_usuarios(), sin
        # incluir inactivos) para reflejar altas/bajas recientes de
        # Usuarios sin tener que reiniciar el programa. Se ordena acá
        # con Python (nombre.lower()), no con el ORDER BY del repo: en
        # SQLite el orden por defecto es por valor de byte, así que
        # "admin" (minúscula) quedaría después de cualquier nombre en
        # mayúscula en vez de intercalarse alfabéticamente de verdad.
        self.combo_nombre = QComboBox()
        usuarios_ordenados = sorted(listar_usuarios(), key=lambda u: u["nombre"].lower())
        for usuario in usuarios_ordenados:
            self.combo_nombre.addItem(usuario["nombre"])
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)
        # Al apretar Enter en la clave, intenta entrar directamente (más
        # rápido para el uso diario que tener que hacer clic siempre).
        self.campo_clave.returnPressed.connect(self._intentar_ingresar)

        formulario = QFormLayout()
        formulario.setSpacing(10)
        formulario.addRow("Nombre:", self.combo_nombre)
        formulario.addRow("Clave:", self.campo_clave)

        boton_entrar = QPushButton("Entrar")
        aplicar_clase(boton_entrar, "primario")
        boton_entrar.setFixedHeight(42)
        boton_entrar.setDefault(True)
        boton_entrar.clicked.connect(self._intentar_ingresar)

        # Tarjeta blanca centrada, con borde suave, que agrupa todo el
        # formulario. Su estilo vive en la hoja de estilos GLOBAL de main.py
        # (selector "#tarjetaLogin"), no en un setStyleSheet local, por el
        # mismo motivo que el fondo de arriba: una hoja local rompería la
        # regla [clase="primario"] del botón "Entrar" que va adentro.
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaLogin")
        layout_tarjeta = QVBoxLayout()
        layout_tarjeta.setContentsMargins(36, 32, 36, 32)
        layout_tarjeta.setSpacing(6)
        layout_tarjeta.addWidget(icono)
        layout_tarjeta.addWidget(titulo)
        layout_tarjeta.addWidget(subtitulo)
        layout_tarjeta.addSpacing(20)
        layout_tarjeta.addLayout(formulario)
        layout_tarjeta.addSpacing(20)
        layout_tarjeta.addWidget(boton_entrar)
        tarjeta.setLayout(layout_tarjeta)

        # Sombra suave para que la tarjeta se sienta "flotando" sobre el
        # fondo gris, en vez de quedar pegada — un detalle chico que
        # ayuda a que la pantalla de entrada se vea más cuidada. Tiene
        # que ser un efecto de Qt (QGraphicsDropShadowEffect), no CSS:
        # el motor de hojas de estilo de Qt no soporta box-shadow.
        sombra = QGraphicsDropShadowEffect(self)
        sombra.setBlurRadius(28)
        sombra.setXOffset(0)
        sombra.setYOffset(6)
        sombra.setColor(QColor(31, 41, 61, 45))
        tarjeta.setGraphicsEffect(sombra)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)
        layout.addWidget(tarjeta)
        self.setLayout(layout)

        self.combo_nombre.setFocus()

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

        usuario = autenticar_por_nombre(nombre, clave)
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
