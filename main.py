"""
main.py
========
Punto de entrada del programa. Al ejecutar este archivo:
1. Se verifica que no haya otra copia abierta en la misma PC.
2. Se prepara la base de datos (si es la primera vez, se crea) y arrancan
   las copias de seguridad automáticas (repositories/copias_repo.py: después
   de cada Cierre de Turno y cada 8 horas, con el programa abierto).
3. Se levanta el servidor de red que consultan las PCs cliente
   (servidor_red.py).
4. Se muestra la pantalla de Login.
5. Al loguearse correctamente, se abre la ventana principal con los
   permisos que correspondan según el rol del usuario.
6. Al cerrar sesión desde la ventana principal, se vuelve al Login
   (sin tener que reabrir todo el programa).

Si el programa se abrió desde la carpeta compartida del mostrador (otra PC del
local, ver admin_remoto/modo.py), es una copia para ADMINISTRAR desde ahí: no
toca ninguna base ni levanta el servidor de las PCs, se conecta al CyberBIOS
del mostrador y le pide todo a él (pasos 2 y 3 los hace el mostrador).

Para arrancar el sistema, se ejecuta:  python main.py
"""

import gc
import socket
import sys
import traceback
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from admin_remoto import cliente as cliente_remoto, modo as modo_remoto
from database import inicializar_base_de_datos
from repositories import copias_repo
from servidor_red import iniciar_servidor
from ui.ingreso_caja import resolver_caja_al_entrar
from ui.login_window import LoginWindow
from ui.main_window import MainWindow


# --------------------------------------------------------------------
# Rutas de recursos
# --------------------------------------------------------------------
# Carpeta del programa (donde está este archivo), para ubicar el ícono
# sin importar desde qué directorio se lo ejecute.
CARPETA_BASE = Path(__file__).resolve().parent
RUTA_ICONO = CARPETA_BASE / "assets" / "icono.ico"
# Qt QSS quiere barras "/" en las rutas de imagen (incluso en Windows) y
# no admite f-strings acá abajo (la hoja de estilos ya usa { } para CSS),
# por eso el path se arma aparte y se reemplaza con .replace() al final.
RUTA_FLECHA_ABAJO = (CARPETA_BASE / "assets" / "flecha_abajo.svg").as_posix()


# --------------------------------------------------------------------
# Instancia única (una sola copia de Kiosko por PC)
# --------------------------------------------------------------------
# Puerto dedicado SOLO para detectar una segunda copia abierta -- no tiene
# nada que ver con servidor_red.PUERTO_SERVIDOR (8899, el que hablan los
# Clientes PC). Bindear un socket TCP en localhost es un "mutex" de
# instancia única liviano y sin dependencias nuevas: el sistema operativo
# libera el puerto solo en cuanto el proceso termina, sea un cierre normal
# o un crash, así que nunca queda un candado colgado que obligue a
# reiniciar Windows para poder volver a abrir el programa.
PUERTO_INSTANCIA_UNICA = 8898

# Referencia viva al socket-candado: si se dejara que el recolector de
# basura la destruya, el socket se cerraría solo y el "candado" dejaría de
# valer apenas terminara main(). Mantenerla acá arriba lo mantiene abierto
# mientras el proceso siga vivo.
_candado_instancia_unica = None


def _ya_hay_una_copia_abierta() -> bool:
    """True si otra copia del programa ya tiene tomado el puerto-candado.
    Si no, toma el candado para esta copia y devuelve False."""
    global _candado_instancia_unica
    candado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        candado.bind(("127.0.0.1", PUERTO_INSTANCIA_UNICA))
    except OSError:
        candado.close()
        return True
    _candado_instancia_unica = candado
    return False


# --------------------------------------------------------------------
# Estilo visual
# --------------------------------------------------------------------
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
    /* Un bono tildado dentro de una lista deshabilitada (la de PC cuando está
       elegida la PlayStation, y al revés) no tiene que verse tan fuerte como
       uno activo: es lo que deja claro cuál de las dos listas se puede usar. */
    QPushButton:checked:disabled {
        background-color: #AEC3F2;
        border: 1px solid #AEC3F2;
        color: #EFF3FE;
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
    QPushButton[clase="peligro"]:disabled {
        background-color: #F5F6F8;
        border-color: #E1E4E9;
        color: #A7ADB8;
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
    /* Barra de arriba oscura, estilo cyber, haciendo juego con el mosaico de PCs
       (pedido del dueño, 2026-10-19: "no parecen ni botones"). */
    #encabezadoInicio {
        background-color: #1E2330;
        border: 1px solid #2B3242;
        border-radius: 12px;
    }
    QLabel#nombreEncabezado {
        font-size: 15px;
        font-weight: 700;
        color: #F1F4F9;
    }
    QLabel#cajaEncabezado {
        font-size: 13px;
        color: #9AA4B5;
    }

    /* Mosaico de PCs (control_pcs/ui/pcs_mosaico.py): fondo oscuro para que
       resalten los colores de las pantallas, como en los programas de cyber. */
    QFrame#marcoMosaico {
        background-color: #181B21;
        border: 1px solid #0C0E12;
        border-radius: 12px;
    }
    QListWidget#mosaicoPcs {
        background-color: transparent;
        border: none;
        outline: none;
    }
    QLabel#textoLeyendaMosaico {
        color: #C9CED8;
        font-size: 12px;
    }
    /* Las reservas de "Cualquier PC disponible", arriba del mosaico (maqueta 7 de
       PROPUESTA_RESERVAS: recuadro claro con letra azul). */
    QLabel#avisoReservasMosaico {
        background-color: #EAF1FE;
        color: #1D4FB8;
        border-radius: 6px;
        padding: 5px 12px;
        font-size: 12px;
    }
    QListWidget#mosaicoPcs QScrollBar:vertical {
        background: #181B21;
    }
    QListWidget#mosaicoPcs QScrollBar::handle:vertical {
        background: #3A404C;
    }
    QListWidget#mosaicoPcs QScrollBar::handle:vertical:hover {
        background: #4A5160;
    }

    /* Panel del costado de Control de PCs (control_pcs/ui/pcs_detalle.py) en gris
       medio: lo eligió el dueño entre 5 maquetas (2026-10-19). Todo va con ">"
       (solo los hijos directos del panel y de su lista de bonos) a propósito: las
       ventanas que abre el panel (el cobro, el login del socio, los avisos) son
       hijas suyas, y con un selector común heredarían las letras claras sobre su
       fondo claro. */
    QFrame#panelDetalle {
        background-color: #5E636B;
        border: 1px solid #4A4E55;
        border-radius: 12px;
    }
    QFrame#panelDetalle > QLabel, QWidget#contenedorBonos > QLabel {
        color: #F3F4F6;
        background: transparent;
    }
    /* La lista de bonos que no corresponde al equipo elegido, con su título apagado. */
    QFrame#panelDetalle > QLabel:disabled, QWidget#contenedorBonos > QLabel:disabled {
        color: #A3A8B0;
    }
    QWidget#contenedorBonos > QLabel#avisoSinBonos {
        color: #D5D8DD;
    }
    QFrame#panelDetalle > QPushButton, QWidget#contenedorBonos > QPushButton {
        background-color: #F2F3F5;
        border: 1px solid #C3C7CD;
        color: #1E2229;
    }
    QFrame#panelDetalle > QPushButton:hover, QWidget#contenedorBonos > QPushButton:hover {
        background-color: #FFFFFF;
        border-color: #E1E4E8;
    }
    QFrame#panelDetalle > QPushButton:pressed, QWidget#contenedorBonos > QPushButton:pressed {
        background-color: #DADDE2;
    }
    QWidget#contenedorBonos > QPushButton:checked,
    QFrame#panelDetalle > QPushButton[clase="primario"] {
        background-color: #2F6FED;
        border-color: #2F6FED;
        color: #FFFFFF;
    }
    QWidget#contenedorBonos > QPushButton:checked:hover,
    QFrame#panelDetalle > QPushButton[clase="primario"]:hover {
        background-color: #255BC7;
        border-color: #255BC7;
    }
    QFrame#panelDetalle > QPushButton[clase="primario"]:pressed {
        background-color: #1D48A0;
        border-color: #1D48A0;
    }
    QFrame#panelDetalle > QPushButton[clase="peligro"] {
        border-color: #D9838A;
        color: #A6323C;
    }
    QFrame#panelDetalle > QPushButton[clase="peligro"]:hover {
        background-color: #FBEAEA;
        border-color: #C96870;
    }
    QFrame#panelDetalle > QPushButton[clase="peligro"]:pressed {
        background-color: #F3D3D3;
    }
    QFrame#panelDetalle > QPushButton:disabled, QWidget#contenedorBonos > QPushButton:disabled,
    QFrame#panelDetalle > QPushButton[clase="peligro"]:disabled {
        background-color: #6B7078;
        border-color: #767B83;
        color: #A9AEB6;
    }
    QWidget#contenedorBonos > QPushButton:checked:disabled,
    QFrame#panelDetalle > QPushButton[clase="primario"]:disabled {
        background-color: #5B72A3;
        border-color: #5B72A3;
        color: #C9D3EA;
    }
    QScrollArea#areaBonos QScrollBar:vertical {
        background: #5E636B;
    }

    /* --- Pulido visual (2026-10-10) --- */

    /* Botones de la barra oscura de arriba (2026-10-19): cada uno es una tecla con
       relieve (el borde de abajo, más grueso y oscuro) que se prende en azul al
       pasarle el mouse y se hunde al apretarla (baja 2 px y pierde el relieve).
       Vender (primario) en azul lleno y Cerrar sesión (peligro) con borde rojo,
       lejos de los demás. */
    QPushButton[clase="barra"] {
        background-color: #2C3345;
        border: 1px solid #3A4358;
        border-top-color: #4B5570;
        border-bottom: 3px solid #0B0D12;
        color: #E6EAF2;
        font-weight: 600;
        padding: 7px 12px;
    }
    QPushButton[clase="barra"]:hover {
        background-color: #323B50;
        border-color: #4C8DFF;
        border-bottom-color: #1D48A0;
        color: #FFFFFF;
    }
    QPushButton[clase="barra"]:pressed,
    QPushButton[clase="alerta"]:pressed,
    #encabezadoInicio QPushButton[clase="primario"]:pressed,
    #encabezadoInicio QPushButton[clase="peligro"]:pressed {
        border-bottom-width: 1px;
        margin-top: 2px;
    }
    QPushButton[clase="barra"]:pressed {
        background-color: #252B3A;
    }
    #encabezadoInicio QPushButton[clase="primario"] {
        background-color: #2F6FED;
        border: 1px solid #4C8DFF;
        border-top-color: #7AAAFF;
        border-bottom: 3px solid #173A85;
        color: #FFFFFF;
        font-weight: 600;
        padding: 7px 16px;
    }
    #encabezadoInicio QPushButton[clase="primario"]:hover {
        background-color: #3D7BFF;
        border-color: #7AAAFF;
        border-bottom-color: #173A85;
    }
    #encabezadoInicio QPushButton[clase="primario"]:pressed {
        background-color: #255BC7;
    }
    #encabezadoInicio QPushButton[clase="peligro"] {
        background-color: transparent;
        border: 1px solid #8A3A42;
        border-bottom: 3px solid #4A1A1F;
        color: #FF8A93;
        font-weight: 600;
        padding: 7px 16px;
    }
    #encabezadoInicio QPushButton[clase="peligro"]:hover {
        background-color: #3A2328;
        border-color: #C24B57;
        border-bottom-color: #4A1A1F;
        color: #FFB3B9;
    }
    #encabezadoInicio QPushButton[clase="peligro"]:pressed {
        background-color: #2E1C20;
    }
    /* Cierre de Turno cuando toca cerrar la caja (desde 5 minutos antes del fin
       del turno, pedido del dueño 2026-10-18): titila alternando este rojo lleno
       con el estilo "barra" (ver MainWindow._parpadear). Mismos bordes, relleno y
       letra que "barra", para que el botón no cambie de tamaño al titilar. */
    QPushButton[clase="alerta"] {
        background-color: #D92D3A;
        border: 1px solid #FF5A66;
        border-top-color: #FF8A93;
        border-bottom: 3px solid #6E141C;
        color: #FFFFFF;
        font-weight: 600;
        padding: 7px 12px;
    }
    QPushButton[clase="alerta"]:hover {
        background-color: #E5404C;
    }

    QLabel#tituloSeccion {
        font-size: 12px;
        font-weight: 600;
        color: #5B6472;
        padding: 6px 2px 2px 2px;
    }

    /* Aviso informativo, en azul suave (no es una alarma): lo usa el Resumen del
       Día cuando un cierre de ese día quedó anotado en otro. */
    QFrame#avisoInformativo {
        background-color: #EEF4FF;
        border: 1px solid #C9D9FB;
        border-radius: 10px;
    }
    QFrame#avisoInformativo QLabel#avisoTitulo {
        color: #1D48A0;
        font-weight: 600;
    }

    /* Cuadros de texto de solo lectura (el log de "Actividad reciente"). */
    QTextEdit, QPlainTextEdit {
        background-color: #FFFFFF;
        border: 1px solid #D3D8E0;
        border-radius: 8px;
        padding: 6px 8px;
        color: #3C4350;
        selection-background-color: #DCE7FD;
        selection-color: #1B2233;
    }

    /* Numeración de filas y esquina de las tablas (por defecto toman el color de
       Windows); en las tablas del programa la numeración ni se muestra. */
    QHeaderView {
        background-color: #F5F7FA;
    }
    QHeaderView::section:vertical {
        background-color: #F5F7FA;
        color: #8A93A3;
        border: none;
        border-right: 1px solid #E4E7EC;
        padding: 0 8px;
    }
    QTableCornerButton::section {
        background-color: #F5F7FA;
        border: none;
    }
    QHeaderView::section:horizontal {
        text-align: left;
    }
    QTableWidget::item:selected {
        border: none;
    }
    /* El campo que se abre al escribir en una celda (el stock de ORDENAR Stock, los
       módems): con el relleno de 7 px de los demás campos, en un renglón de tabla le
       quedaba ~1 px a la letra y el número se veía como una rayita (reportado por el
       dueño, 2026-10-20). Va con ">" (campo hijo del área de la tabla) para no tocar el
       campo de adentro de un QSpinBox puesto en una celda, como los montos de la Tarifa
       por Hora para Socios: ese cuelga del QSpinBox, no de la tabla. */
    QAbstractItemView > QWidget > QLineEdit {
        padding: 0 4px;
        border-radius: 3px;
    }
    QAbstractItemView > QWidget > QLineEdit:focus {
        border: 1px solid #2F6FED;
    }

    /* Selector de fecha: mismo aspecto que el desplegable. */
    QDateEdit::drop-down {
        subcontrol-origin: padding;
        subcontrol-position: top right;
        width: 28px;
        border-left: 1px solid #CDD3DE;
        border-top-right-radius: 7px;
        border-bottom-right-radius: 7px;
        background-color: #F5F7FA;
    }
    QDateEdit::drop-down:hover {
        background-color: #EAEFF7;
    }
    QDateEdit::down-arrow {
        image: url(__RUTA_FLECHA_ABAJO__);
        width: 10px;
        height: 6px;
        margin-right: 9px;
    }

    /* Menús (clic derecho en una PC) y avisos flotantes. */
    QMenu {
        background-color: #FFFFFF;
        border: 1px solid #D3D8E0;
        border-radius: 8px;
        padding: 5px;
    }
    QMenu::item {
        padding: 8px 26px 8px 14px;
        border-radius: 6px;
    }
    QMenu::item:selected {
        background-color: #DCE7FD;
        color: #1B2233;
    }
    QMenu::separator {
        height: 1px;
        background: #E4E7EC;
        margin: 5px 8px;
    }
    QToolTip {
        background-color: #1B2233;
        color: #FFFFFF;
        border: none;
        padding: 5px 8px;
    }

    /* Carteles de aviso y confirmación: botones parejos. */
    QMessageBox QPushButton {
        min-width: 88px;
    }

    QScrollBar:horizontal {
        height: 11px;
        background: #EEF1F6;
    }
    QScrollBar::handle:horizontal {
        background: #C7CDD6;
        border-radius: 5px;
        min-width: 24px;
    }
    QScrollBar::handle:horizontal:hover {
        background: #AEB4BF;
    }
    QScrollBar::add-line:horizontal, QScrollBar::sub-line:horizontal {
        width: 0px;
    }
""".replace("__RUTA_FLECHA_ABAJO__", RUTA_FLECHA_ABAJO)


def aplicar_estilo(app):
    """
    Deja el aspecto de todo el programa en un solo lugar (lo usan main() y las
    pruebas de pantalla): estilo Fusion (look limpio y parejo entre PCs), esquema
    de color CLARO y la hoja de estilos de arriba.

    El esquema claro se fija a propósito: Fusion toma los colores de Windows, y con
    el modo oscuro puesto los cuadros que la hoja no pinta (el log de "Actividad
    reciente", la numeración de las filas) salían negros y con la letra oscura de la
    hoja encima, o sea casi ilegibles. El programa está diseñado en claro.
    """
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setStyleSheet(HOJA_DE_ESTILOS)


class Aplicacion:
    """
    Pequeña clase que coordina el ir y venir entre la pantalla de Login
    y la ventana principal, para poder "cerrar sesión" y volver a
    loguearse sin cerrar todo el programa.
    """

    def __init__(self, conexion_remota=None):
        # La conexión con el mostrador si esta es una copia para administrar
        # desde otra PC (ver main y admin_remoto/); None en el mostrador.
        self.conexion_remota = conexion_remota
        self.ventana_principal = None
        self.ventana_login = None
        self._mostrar_login()

    def _mostrar_login(self):
        if self.conexion_remota is not None:
            # Cerrar sesión en la otra PC también la cierra en el mostrador.
            self.conexion_remota.salir()
            try:
                self.ventana_login = LoginWindow(al_loguearse=self._al_loguearse)
            except (ValueError, PermissionError) as error:  # sin red, o la entrada se apagó
                QMessageBox.warning(None, "Administrar desde otra PC", str(error))
                QApplication.quit()
                return
        else:
            self.ventana_login = LoginWindow(al_loguearse=self._al_loguearse)
        self.ventana_login.show()

    def _al_loguearse(self, usuario):
        # Antes de entrar, la caja tiene que quedar lista: abrirla contando el
        # cambio, recibirla de quien cubrió el turno o cerrar la de quien se fue
        # (ver ui/ingreso_caja.py). Si se cancela, se queda en el ingreso. Desde
        # otra PC no: ahí no hay cajón (y solo entra el Administrador).
        if self.conexion_remota is None and not resolver_caja_al_entrar(self.ventana_login, usuario):
            return
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
        from errores import registrar_error
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
    # Recolector cíclico de basura desactivado a propósito. Un QTimer
    # conectado a un método propio (ej. PanelControlPcs._timer ->
    # self._refrescar) arma un ciclo de referencias que solo ese recolector
    # puede romper, y puede dispararse desde CUALQUIER hilo que esté
    # asignando memoria, no solo el hilo dueño del QObject. Como
    # servidor_red.py corre un hilo de fondo real todo el tiempo, ese hilo
    # podía destruir un QTimer de la interfaz: Qt tira "QObject::killTimer:
    # Timers cannot be stopped from another thread" y deja el objeto C++
    # roto -- el origen de los "Internal C++ object already deleted" de
    # data/errores.log. Qt libera sus QObject solo por relación
    # padre/hijo y el resto del programa no depende de ciclos; lo único que
    # se pierde son unos pocos ciclos de la UI (uno por pantalla con
    # timer), que en un programa que se reinicia a diario no pesan.
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
    aplicar_estilo(app)
    # Ícono de la caja registradora: al ponerlo en la aplicación (y no en
    # cada ventana por separado), TODAS las ventanas y cuadros de diálogo
    # lo heredan automáticamente en la esquina superior izquierda, en vez
    # del ícono genérico de Qt.
    app.setWindowIcon(QIcon(str(RUTA_ICONO)))

    mostrador = modo_remoto.direccion_del_mostrador()
    if mostrador is not None:
        conexion_remota = _conectar_con_el_mostrador(mostrador)
        if conexion_remota is None:
            sys.exit(0)
        Aplicacion(conexion_remota)
        sys.exit(app.exec())

    inicializar_base_de_datos()
    copias_repo.iniciar_copias_automaticas()
    # Corre todo el tiempo que Kiosko esté abierto, sin importar quién
    # esté logueado -- es lo que consultan las PCs bloqueadas del local
    # (ver servidor_red.py y la carpeta hermana "CLIENTE PC").
    iniciar_servidor()
    Aplicacion()
    sys.exit(app.exec())


def _conectar_con_el_mostrador(mostrador: str):
    """
    Esta copia se abrió desde otra PC (ver admin_remoto/modo.py): se presenta al
    CyberBIOS del mostrador y, si está y deja entrar, hace que todas las
    pantallas le pidan los datos a él. Devuelve la conexión, o None después de
    avisar por qué no se puede (el mostrador cerrado, la entrada apagada, otro
    .exe).
    """
    try:
        conexion = cliente_remoto.conectar(mostrador)
    except (ValueError, PermissionError) as error:
        QMessageBox.warning(None, "Administrar desde otra PC", str(error))
        return None
    cliente_remoto.instalar(conexion)
    return conexion


if __name__ == "__main__":
    main()
