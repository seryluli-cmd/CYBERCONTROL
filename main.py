"""
main.py
========
Punto de entrada del programa. Al ejecutar este archivo:
1. Se prepara la base de datos (si es la primera vez, se crea).
2. Se muestra la pantalla de Login.
3. Al loguearse correctamente, se abre la ventana principal con los
   permisos que correspondan según el rol del usuario.
4. Al cerrar sesión desde la ventana principal, se vuelve al Login
   (sin tener que reabrir todo el programa).

Para arrancar el sistema, se ejecuta:  python main.py
"""

import gc
import socket
import sys
import traceback
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from database import inicializar_base_de_datos, hacer_backup_automatico
from servidor_red import iniciar_servidor
from ui.login_window import LoginWindow
from ui.main_window import MainWindow

# Puerto dedicado SOLO para detectar una segunda copia de Kiosko abierta
# en la misma PC -- no tiene nada que ver con servidor_red.PUERTO_SERVIDOR
# (8899, el que hablan los Clientes PC de las PCs cliente). Bindear un socket
# TCP en localhost es un "mutex" de instancia única liviano y sin
# dependencias nuevas: el sistema operativo libera el puerto solo en
# cuanto el proceso termina, sea un cierre normal o un crash, así que
# nunca queda un candado colgado que obligue a reiniciar Windows para
# poder volver a abrir el programa.
PUERTO_INSTANCIA_UNICA = 8898

# Referencia viva al socket-candado: si se dejara que el recolector de
# basura la destruya, el socket se cerraría solo y el "candado" dejaría de
# valer apenas terminara main(). Mantenerla acá arriba lo mantiene abierto
# mientras el proceso siga vivo.
_candado_instancia_unica = None


def _ya_hay_una_copia_abierta() -> bool:
    global _candado_instancia_unica
    candado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        candado.bind(("127.0.0.1", PUERTO_INSTANCIA_UNICA))
    except OSError:
        candado.close()
        return True
    _candado_instancia_unica = candado
    return False

# Carpeta del programa (donde está este archivo), para ubicar el ícono
# sin importar desde qué directorio se lo ejecute.
CARPETA_BASE = Path(__file__).resolve().parent
RUTA_ICONO = CARPETA_BASE / "assets" / "icono.ico"
# Qt QSS quiere barras "/" en las rutas de imagen (incluso en Windows) y
# no admite f-strings acá abajo (la hoja de estilos ya usa { } para CSS),
# por eso el path se arma aparte y se reemplaza con .replace() al final.
RUTA_FLECHA_ABAJO = (CARPETA_BASE / "assets" / "flecha_abajo.svg").as_posix()


# Estilo visual general de todo el programa: paleta de color consistente
# (azul para la acción principal de cada pantalla, bordó para lo
# destructivo/cerrar sesión, verde para confirmaciones), tipografía más
# grande y botones con más espacio interno, pensado para que sea cómodo
# de usar rápido con mouse o con pantalla táctil detrás de un mostrador.
#
# Los botones "importantes" de cada pantalla se marcan en el código con
# boton.setProperty("clase", "primario") (acción principal, ej. Cobrar,
# Guardar) o "peligro" (acción destructiva, ej. Cancelar, Borrar, Cerrar
# sesión) — eso es lo que activa los selectores QPushButton[clase=...]
# de acá abajo. Sin esa propiedad, un botón usa el estilo neutro de
# siempre.
HOJA_DE_ESTILOS = """
    QWidget {
        font-family: "Segoe UI";
        font-size: 13px;
        color: #1B2233;
    }
    QMainWindow, QDialog {
        background-color: #EEF1F6;
    }
    QPushButton {
        background-color: #FFFFFF;
        border: 1px solid #CDD3DE;
        padding: 9px 18px;
        border-radius: 8px;
        color: #1B2233;
    }
    QPushButton:hover {
        background-color: #F5F7FA;
        border-color: #B7BFCC;
    }
    QPushButton:pressed {
        background-color: #E7EAF0;
    }
    QPushButton:disabled {
        color: #A7ADB8;
        background-color: #F5F6F8;
        border-color: #E1E4E9;
    }
    QPushButton:checked {
        background-color: #2F6FED;
        border: 1px solid #2F6FED;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton:checked:hover {
        background-color: #255BC7;
        border-color: #255BC7;
    }
    QPushButton[clase="primario"] {
        background-color: #2F6FED;
        border: 1px solid #2F6FED;
        color: #FFFFFF;
        font-weight: 600;
    }
    QPushButton[clase="primario"]:hover {
        background-color: #255BC7;
        border-color: #255BC7;
    }
    QPushButton[clase="primario"]:pressed {
        background-color: #1D48A0;
        border-color: #1D48A0;
    }
    QPushButton[clase="primario"]:disabled {
        background-color: #AEC3F2;
        border-color: #AEC3F2;
        color: #EFF3FE;
    }
    QPushButton[clase="peligro"] {
        background-color: #FFFFFF;
        border: 1px solid #D9838A;
        color: #A6323C;
        font-weight: 600;
    }
    QPushButton[clase="peligro"]:hover {
        background-color: #FBEAEA;
        border-color: #C96870;
    }
    QPushButton[clase="peligro"]:pressed {
        background-color: #F3D3D3;
    }
    QLineEdit, QDoubleSpinBox, QSpinBox, QComboBox, QDateEdit {
        padding: 7px 9px;
        border: 1px solid #CDD3DE;
        border-radius: 7px;
        background-color: #FFFFFF;
        selection-background-color: #2F6FED;
    }
    QLineEdit:focus, QDoubleSpinBox:focus, QSpinBox:focus, QComboBox:focus, QDateEdit:focus {
        border: 1.5px solid #2F6FED;
    }
    QLineEdit:disabled {
        background-color: #F5F6F8;
        color: #A7ADB8;
    }
    QComboBox {
        padding-right: 8px;
    }
    QComboBox::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border-left: 1px solid #CDD3DE;
        border-top-right-radius: 7px;
        border-bottom-right-radius: 7px;
        background-color: #F5F7FA;
    }
    QComboBox::drop-down:hover {
        background-color: #EAEFF7;
    }
    QComboBox::down-arrow {
        image: url(__RUTA_FLECHA_ABAJO__);
        width: 10px;
        height: 6px;
        margin-right: 9px;
    }
    QComboBox QAbstractItemView {
        border: 1px solid #CDD3DE;
        selection-background-color: #DCE7FD;
        selection-color: #1B2233;
        outline: none;
    }
    QCheckBox {
        spacing: 8px;
        padding: 2px 0;
    }
    QCheckBox::indicator {
        width: 17px;
        height: 17px;
        border: 1.5px solid #B7BFCC;
        border-radius: 4px;
        background-color: #FFFFFF;
    }
    QCheckBox::indicator:hover {
        border-color: #2F6FED;
    }
    QCheckBox::indicator:checked {
        background-color: #2F6FED;
        border-color: #2F6FED;
    }
    QGroupBox {
        border: 1px solid #D3D8E0;
        border-radius: 8px;
        margin-top: 14px;
        padding-top: 6px;
        font-weight: 600;
        color: #3C4350;
    }
    QGroupBox::title {
        subcontrol-origin: margin;
        left: 10px;
        padding: 0 6px;
        color: #3C4350;
    }
    QTableWidget {
        gridline-color: #E4E7EC;
        background-color: #FFFFFF;
        border: 1px solid #D3D8E0;
        border-radius: 8px;
        alternate-background-color: #F7F9FC;
        selection-background-color: #DCE7FD;
        selection-color: #1B2233;
    }
    QTableWidget::item {
        padding: 5px;
    }
    QHeaderView::section {
        background-color: #F5F7FA;
        padding: 9px 8px;
        border: none;
        border-bottom: 1.5px solid #D3D8E0;
        font-weight: 600;
        font-size: 11px;
        letter-spacing: 0.4px;
        color: #5B6472;
    }
    QTabWidget::pane {
        border: 1px solid #D3D8E0;
        border-radius: 8px;
        top: -1px;
        background-color: #FFFFFF;
    }
    QTabBar::tab {
        padding: 9px 20px;
        background: transparent;
        border: none;
        border-bottom: 2.5px solid transparent;
        color: #5B6472;
        margin-right: 4px;
    }
    QTabBar::tab:hover {
        color: #1B2233;
    }
    QTabBar::tab:selected {
        color: #2F6FED;
        border-bottom: 2.5px solid #2F6FED;
        font-weight: 600;
    }
    QScrollBar:vertical {
        width: 11px;
        background: #EEF1F6;
    }
    QScrollBar::handle:vertical {
        background: #C7CDD6;
        border-radius: 5px;
        min-height: 24px;
    }
    QScrollBar::handle:vertical:hover {
        background: #AEB4BF;
    }
    QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical {
        height: 0px;
    }
    #tarjetaLogin {
        background-color: #FFFFFF;
        border: 1px solid #E1E4EA;
        border-radius: 14px;
    }
    #encabezadoInicio {
        background-color: #FFFFFF;
        border: 1px solid #E1E4EA;
        border-radius: 12px;
    }
""".replace("__RUTA_FLECHA_ABAJO__", RUTA_FLECHA_ABAJO)


class Aplicacion:
    """
    Pequeña clase que coordina el ir y venir entre la pantalla de Login
    y la ventana principal, para poder "cerrar sesión" y volver a
    loguearse sin cerrar todo el programa.
    """

    def __init__(self):
        self.ventana_principal = None
        self.ventana_login = None
        self._mostrar_login()

    def _mostrar_login(self):
        self.ventana_login = LoginWindow(al_loguearse=self._al_loguearse)
        self.ventana_login.show()

    def _al_loguearse(self, usuario):
        self.ventana_login.close()
        self.ventana_principal = MainWindow(usuario, al_cerrar_sesion=self._mostrar_login)
        self.ventana_principal.showMaximized()


def _manejar_excepcion_no_capturada(tipo, valor, tb):
    """
    Red de seguridad final: cada pantalla ya envuelve sus propias
    acciones con el decorador `manejar_errores` (ver ui/utils.py), pero
    esto cubre cualquier excepción que igual se escape de ahí (por
    ejemplo, durante la construcción de una ventana). En vez de que la
    aplicación se cierre en silencio o quede en un estado raro, se deja
    el detalle en el log y se avisa con un cartel.
    """
    traceback.print_exception(tipo, valor, tb)
    try:
        from ui.utils import registrar_error
        registrar_error(valor)
    except Exception:
        pass
    try:
        QMessageBox.critical(
            None, "Ocurrió un error inesperado",
            "Algo falló y quedó registrado en data/errores.log.\n"
            "Conviene cerrar y volver a abrir el programa si algo se ve raro.\n\n"
            f"({tipo.__name__}: {valor})"
        )
    except Exception:
        pass


def main():
    # Desactivado a propósito: un QTimer conectado a un método propio (ej.
    # PanelControlPcs._timer -> self._refrescar) arma un ciclo de
    # referencias Python que solo el recolector CÍCLICO puede romper -- y
    # ese recolector puede dispararse desde CUALQUIER hilo que esté
    # asignando memoria en ese momento, no solo el hilo dueño del QObject.
    # servidor_red.py corre un hilo de fondo real (threading.Thread, no
    # QThread) todo el tiempo que Kiosko está abierto: si ese hilo dispara
    # la recolección justo cuando le toca destruir un QTimer de la
    # interfaz, Qt tira "QObject::killTimer: Timers cannot be stopped from
    # another thread" y deja el objeto C++ roto -- exactamente el origen
    # de los crashes "Internal C++ object already deleted" que veníamos
    # viendo en data/errores.log (PanelControlPcs, PanelActividad, QTimer)
    # antes de encontrar la causa real. Qt ya libera sus QObject solos por
    # relación padre/hijo (QTimer(self)) y el resto del programa se apoya
    # en refcounting normal, no en ciclos -- lo único que se pierde acá es
    # no limpiar los pocos ciclos puramente Python que arma la propia UI
    # (uno por pantalla con timer, no uno por refresco), que en un programa
    # que se reinicia a diario no llega a pesar en memoria.
    gc.disable()
    sys.excepthook = _manejar_excepcion_no_capturada
    # QApplication se crea PRIMERO (antes de tocar la base o el servidor)
    # porque el cartel de "ya hay una copia abierta" necesita una
    # QApplication viva para poder mostrarse.
    app = QApplication(sys.argv)
    if _ya_hay_una_copia_abierta():
        QMessageBox.warning(
            None, "Kiosko ya está abierto",
            "Ya hay una copia de Kiosko abierta en esta PC.\n\n"
            "Cerrala antes de abrir otra -- tener dos copias a la vez "
            "puede pisar cambios entre ellas."
        )
        sys.exit(0)
    inicializar_base_de_datos()
    hacer_backup_automatico()
    # Corre todo el tiempo que Kiosko esté abierto, sin importar quién
    # esté logueado -- es lo que consultan las PCs bloqueadas del local
    # (ver servidor_red.py y la carpeta hermana "CLIENTE PC").
    iniciar_servidor()
    app.setStyle("Fusion")  # look más limpio y consistente entre sistemas operativos
    app.setStyleSheet(HOJA_DE_ESTILOS)
    # Ícono de la caja registradora: al ponerlo en la aplicación (y no en
    # cada ventana por separado), TODAS las ventanas y cuadros de diálogo
    # lo heredan automáticamente en la esquina superior izquierda, en vez
    # del ícono genérico de Qt.
    app.setWindowIcon(QIcon(str(RUTA_ICONO)))
    Aplicacion()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
