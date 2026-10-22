"""
ui/hoja_de_estilos.py
=====================
La hoja de estilos Qt de TODO el programa (`HOJA_DE_ESTILOS`). La aplica
`main.aplicar_estilo(app)`, junto con el estilo Fusion y el esquema de color claro.

Estaba en main.py y se mudó acá el 2026-10-22 (revisión de limpieza: main.py pasaba
las 600 líneas, regla 12 de CLAUDE.md), sin cambiar nada. Es solo texto: no importa
nada del programa.
"""

from pathlib import Path

# Qt QSS quiere barras "/" en las rutas de imagen (incluso en Windows) y
# no admite f-strings acá abajo (la hoja de estilos ya usa { } para CSS),
# por eso el path se arma aparte y se reemplaza con .replace() al final.
# La carpeta assets está junto al código, un nivel arriba de ui/ (igual que
# el ícono de ui/login_window.py).
RUTA_FLECHA_ABAJO = (Path(__file__).resolve().parent.parent / "assets" / "flecha_abajo.svg").as_posix()


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
       lejos de los demás. Todos en negrita y mayúscula (pedido del dueño, 2026-10-22;
       la mayúscula la pone MainWindow._agregar_boton_barra). */
    QPushButton[clase="barra"] {
        background-color: #2C3345;
        border: 1px solid #3A4358;
        border-top-color: #4B5570;
        border-bottom: 3px solid #0B0D12;
        color: #E6EAF2;
        font-weight: 700;
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
        font-weight: 700;
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
        font-weight: 700;
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
        font-weight: 700;
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
