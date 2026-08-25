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

import sys
import traceback
from pathlib import Path
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from database import inicializar_base_de_datos, hacer_backup_automatico
from ui.login_window import LoginWindow
from ui.main_window import MainWindow

# Carpeta del programa (donde está este archivo), para ubicar el ícono
# sin importar desde qué directorio se lo ejecute.
CARPETA_BASE = Path(__file__).resolve().parent
RUTA_ICONO = CARPETA_BASE / "assets" / "icono.ico"


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
        color: #1F2430;
    }
    QMainWindow, QDialog {
        background-color: #F2F4F7;
    }
    QPushButton {
        background-color: #FFFFFF;
        border: 1px solid #C7CDD6;
        padding: 9px 16px;
        border-radius: 6px;
        color: #1F2430;
    }
    QPushButton:hover {
        background-color: #EEF1F6;
        border-color: #B7BFCB;
    }
    QPushButton:pressed {
        background-color: #E0E4EA;
    }
    QPushButton:disabled {
        color: #A7ADB8;
        background-color: #F5F6F8;
        border-color: #E1E4E9;
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
        padding: 7px 8px;
        border: 1px solid #C7CDD6;
        border-radius: 6px;
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
    QTableWidget {
        gridline-color: #E4E7EC;
        background-color: #FFFFFF;
        border: 1px solid #D3D8E0;
        border-radius: 6px;
        alternate-background-color: #F7F9FC;
        selection-background-color: #DCE7FD;
        selection-color: #1F2430;
    }
    QTableWidget::item {
        padding: 4px;
    }
    QHeaderView::section {
        background-color: #EEF1F6;
        padding: 8px;
        border: none;
        border-bottom: 1px solid #D3D8E0;
        font-weight: 600;
        color: #3C4350;
    }
    QTabWidget::pane {
        border: 1px solid #D3D8E0;
        border-radius: 6px;
        top: -1px;
    }
    QTabBar::tab {
        padding: 8px 18px;
        background: #EEF1F6;
        border: 1px solid #D3D8E0;
        border-bottom: none;
        border-top-left-radius: 6px;
        border-top-right-radius: 6px;
        margin-right: 2px;
    }
    QTabBar::tab:selected {
        background: #FFFFFF;
        font-weight: 600;
    }
    QScrollBar:vertical {
        width: 11px;
        background: #F2F4F7;
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
        border: 1px solid #D3D8E0;
        border-radius: 12px;
    }
"""


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
        self.ventana_principal.show()


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
    sys.excepthook = _manejar_excepcion_no_capturada
    inicializar_base_de_datos()
    hacer_backup_automatico()
    app = QApplication(sys.argv)
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
