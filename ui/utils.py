"""
utils.py
=========
Funciones chiquitas que se repiten en varias pantallas: dar formato a
números (pesos argentinos, tiempos), mostrar cuadros de mensaje (avisos,
errores, confirmaciones), un decorador para que ningún error inesperado
rompa una pantalla en silencio, y los ajustes de widgets que hay que
repetir en cada formulario (clase de botón, salto con Enter, sin botón
por defecto).
"""

import functools
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QDate, QEvent, QObject, Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QWidget,
)

import database

# Junto al archivo de la base de datos, para tenerlo todo en la misma
# carpeta "data" (ver database.DATA_DIR, que ya sabe resolver esta
# ubicación tanto corriendo desde código como empaquetado en un .exe).
_RUTA_LOG_ERRORES = Path(database.DATA_DIR) / "errores.log"


def registrar_error(excepcion: Exception):
    """
    Guarda la traza completa de un error en data/errores.log, con fecha
    y hora, para poder revisarla después sin tener que reproducir el
    problema en vivo. La usuaria nunca ve este archivo: solo el cartel
    amigable que muestra `manejar_errores`.
    """
    try:
        _RUTA_LOG_ERRORES.parent.mkdir(parents=True, exist_ok=True)
        with open(_RUTA_LOG_ERRORES, "a", encoding="utf-8") as archivo:
            archivo.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n")
            archivo.write("".join(
                traceback.format_exception(type(excepcion), excepcion, excepcion.__traceback__)
            ))
    except Exception:
        pass  # si ni siquiera se puede escribir el log, no hay mucho más para hacer acá


def manejar_errores(func):
    """
    Decorador para los métodos de una pantalla que llaman a la base de
    datos (guardar, borrar, confirmar una venta, etc.). Antes, si algo
    fallaba ahí adentro, la excepción se propagaba sin control y la
    usuaria se encontraba con la pantalla rota. Con esto:

    - Un ValueError (los errores "de negocio", como intentar borrar un
      artículo que ya tiene ventas) se muestra tal cual, con su mensaje
      pensado para leerse directamente. Un PermissionError ("no tenés
      permiso para esto", ver playstation_repo) también: es un rechazo de
      negocio con su mensaje listo, no una falla del programa.
    - Cualquier otro error inesperado se guarda en el log de errores y
      se le muestra a la usuaria un cartel genérico, en vez de que la
      aplicación se rompa o quede en un estado raro.
    - Un RuntimeError de "objeto C++ ya borrado" (libshiboken) es un caso
      aparte: pasa cuando el refresco automático de 5s de Control de PCs
      (`PanelControlPcs._refrescar`) dispara justo mientras esa pantalla
      se está cerrando (logout o cierre del programa) y toca un widget
      que ya no existe. Ahí no hay a quién mostrarle un cartel -- el
      padre puede estar tan destruido como lo que falló, e intentarlo
      igual repetía el mismo error y se escapaba sin control (ver
      data/errores.log, 2026-09-28: "PanelActividad already deleted"
      seguido de "PanelControlPcs already deleted" al querer avisarle a
      esa misma ventana). Se registra en el log y se ignora en silencio.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (ValueError, PermissionError) as error:
            mostrar_error(self, "No se pudo completar", str(error))
        except RuntimeError as error:
            registrar_error(error)
            if "already deleted" not in str(error):
                _mostrar_error_seguro(self, error)
        except Exception as error:
            registrar_error(error)
            _mostrar_error_seguro(self, error)
    return wrapper


def _mostrar_error_seguro(padre, error):
    """Mismo cartel genérico de `manejar_errores`, pero sin dejar que un
    segundo "objeto ya borrado" (el propio `padre`) se escape sin
    control -- ver el comentario de `manejar_errores` sobre el caso
    RuntimeError."""
    try:
        mostrar_error(
            padre, "Ocurrió un error inesperado",
            "Algo falló y la acción no se pudo completar.\n"
            "El detalle quedó guardado en data/errores.log para revisarlo después.\n\n"
            f"({error.__class__.__name__}: {error})"
        )
    except RuntimeError:
        pass


def formato_pesos(monto) -> str:
    """
    Convierte un número (1234.5) en un texto con formato de pesos
    argentinos ("$ 1.234,50"): punto para miles, coma para decimales.
    """
    try:
        monto = float(monto)
    except (TypeError, ValueError):
        monto = 0.0
    texto = f"{monto:,.2f}"
    # f-string nos da el formato "en inglés" (1,234.50); lo invertimos
    # a formato argentino cambiando temporalmente los separadores.
    texto = texto.replace(",", "TEMP").replace(".", ",").replace("TEMP", ".")
    return f"$ {texto}"


def formato_tiempo(segundos: int, con_segundos: bool = False) -> str:
    """
    Convierte segundos en un texto legible ("2h 05m" o "45m 12s"). Con
    `con_segundos` también muestra los segundos pasada la hora ("2h 05m 31s"):
    es lo que usa la cuenta regresiva de la PlayStation 5, que se redibuja
    cada segundo y tiene que verse correr. Vive acá (y no en control_pcs/)
    porque tanto control_pcs/ui/pcs_window.py como
    control_pcs/ui/miembros_window.py lo necesitan, y ui/utils.py ya es el
    módulo compartido genérico que ambos lados de la app usan (ver
    CLAUDE.md) — puesto en cualquiera de los dos, el otro tendría que
    importarlo cruzado.
    """
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}m {seg:02d}s" if con_segundos else f"{horas}h {minutos:02d}m"
    return f"{minutos}m {seg:02d}s"


def formato_transcurrido(desde: datetime) -> str:
    """Cuánto pasó desde `desde` hasta ahora, como formato_tiempo ("2h 05m").
    Nunca negativo: un reloj apenas corrido no tiene que mostrar "-1m"."""
    return formato_tiempo(max(0, int((datetime.now() - desde).total_seconds())))


def aplicar_clase(widget, clase: str):
    """
    Marca un botón como "primario" (acción principal, ej. Cobrar,
    Guardar) o "peligro" (acción destructiva, ej. Cancelar, Borrar,
    Cerrar sesión) para que tome el color correspondiente de la hoja de
    estilos global (ver main.py). No alcanza con setProperty solo: Qt
    necesita que se le pida "repintar" el widget con el selector CSS
    nuevo, si no el botón se queda con el aspecto neutro de siempre.
    """
    widget.setProperty("clase", clase)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def sin_boton_por_defecto(ventana):
    """
    Le saca a todos los botones de `ventana` la condición de "botón por
    defecto". Se llama una vez, al terminar de armar la interfaz.

    Sin esto, Qt marca como "default" el primer botón que se arma en cada
    diálogo, y apretar Enter en cualquier campo de texto lo activa como si
    se hubiera hecho clic en él. Se vio en Ventas: escanear un código de
    barras y apretar Enter abría la búsqueda F5, porque ese era el primer
    botón de la pantalla.
    """
    for boton in ventana.findChildren(QPushButton):
        boton.setAutoDefault(False)
        boton.setDefault(False)


def fila_guardar_cancelar(dialogo, al_guardar=None, texto_guardar: str = "Guardar"):
    """
    La fila de botones de un formulario: "Guardar" (azul, la acción
    principal) y "Cancelar" (cierra el diálogo con `reject`). `al_guardar`
    es lo que hace el primero (por defecto, aceptar el diálogo tal cual) y
    `texto_guardar` cómo se llama ("Ingresar", "Cobrar y cargar saldo"...).
    Devuelve el layout, para agregarlo al del diálogo.
    """
    boton_guardar = QPushButton(texto_guardar)
    aplicar_clase(boton_guardar, "primario")
    boton_guardar.clicked.connect(al_guardar or dialogo.accept)
    boton_cancelar = QPushButton("Cancelar")
    boton_cancelar.clicked.connect(dialogo.reject)
    botones = QHBoxLayout()
    botones.addWidget(boton_guardar)
    botones.addWidget(boton_cancelar)
    return botones


def fila_agregar_quitar(tabla: QTableWidget, texto_agregar: str, al_agregar):
    """
    Los botones de una tabla que se edita a mano: uno para agregar una fila
    (`texto_agregar`, y `al_agregar` es lo que hace) y "Quitar seleccionado",
    que borra la fila elegida de `tabla`. Devuelve el layout, para agregarlo
    al del diálogo.
    """
    def quitar_la_elegida():
        fila = tabla.currentRow()
        if fila >= 0:
            tabla.removeRow(fila)

    boton_agregar = QPushButton(texto_agregar)
    boton_agregar.clicked.connect(al_agregar)
    boton_quitar = QPushButton("Quitar seleccionado")
    aplicar_clase(boton_quitar, "peligro")
    boton_quitar.clicked.connect(quitar_la_elegida)
    botones = QHBoxLayout()
    botones.addWidget(boton_agregar)
    botones.addWidget(boton_quitar)
    return botones


class _FiltroEnter(QObject):
    """Intercepta la tecla Enter/Intro en el widget donde se instala y,
    en vez de dejarla pasar, ejecuta `accion` (ver `encadenar_enter`)."""

    def __init__(self, accion):
        super().__init__()
        self._accion = accion

    def eventFilter(self, watched, evento):
        if evento.type() == QEvent.KeyPress and evento.key() in (Qt.Key_Return, Qt.Key_Enter):
            self._accion()
            return True
        return False


def _widget_de_teclado(widget):
    """
    El widget que realmente recibe las teclas al escribir no siempre es
    el que uno arma (QComboBox editable, QSpinBox, QDoubleSpinBox y
    QDateEdit por dentro tienen su propio QLineEdit, y es ESE el que
    recibe el evento de tecla) — hay que engancharse ahí, si no el
    filtro de Enter nunca se llega a disparar.
    """
    if isinstance(widget, QAbstractSpinBox) or (isinstance(widget, QComboBox) and widget.isEditable()):
        return widget.lineEdit()
    return widget


def encadenar_enter(*widgets, accion_final=None):
    """
    Hace que apretar Enter en cualquiera de estos campos de un
    formulario pase el foco al siguiente, como si se apretara Tab, en
    vez de no hacer nada (el comportamiento por defecto de Qt para la
    mayoría de estos campos). Sirve para QLineEdit, QComboBox, QSpinBox,
    QDoubleSpinBox y QDateEdit indistintamente, y se puede mezclar
    cualquier combinación de esos tipos en la misma cadena.

    En el último campo, si se pasa `accion_final` (una función sin
    argumentos, típicamente el método que guarda o busca), Enter la
    ejecuta directamente en vez de pasar el foco a ningún lado.
    """
    destinos = list(widgets[1:])
    if accion_final is not None:
        destinos.append(accion_final)

    for widget, destino in zip(widgets, destinos):
        accion = destino.setFocus if isinstance(destino, QWidget) else destino
        filtro = _FiltroEnter(accion)
        # Qt no retiene una referencia propia al filtro (solo la usa por
        # fuera, en C++); si no la guardamos nosotros en algún lado,
        # Python lo destruye enseguida y el filtro deja de funcionar.
        widget._filtro_enter = filtro
        _widget_de_teclado(widget).installEventFilter(filtro)


def crear_tabla(titulos, estirar=None, por_filas=False, una_sola=False) -> QTableWidget:
    """
    Una tabla de solo lectura, con filas alternadas, columnas `titulos` y
    sin filas todavía: así se muestran todas las listas del programa.

    - `estirar`: número de la columna que ocupa el ancho que sobra (las
      demás se ajustan solas).
    - `por_filas`: elegir una celda selecciona la fila entera.
    - `una_sola`: se puede elegir una sola fila a la vez.
    """
    tabla = QTableWidget(0, len(titulos))
    tabla.setHorizontalHeaderLabels(list(titulos))
    if por_filas:
        tabla.setSelectionBehavior(QTableWidget.SelectRows)
    if una_sola:
        tabla.setSelectionMode(QTableWidget.SingleSelection)
    tabla.setEditTriggers(QTableWidget.NoEditTriggers)
    tabla.setAlternatingRowColors(True)
    if estirar is not None:
        tabla.horizontalHeader().setSectionResizeMode(estirar, QHeaderView.Stretch)
    return tabla


def crear_selector_de_fecha(fecha_inicial: QDate = None) -> QDateEdit:
    """
    Un campo de fecha con calendario desplegable, que arranca en
    `fecha_inicial` (hoy, por defecto). Qt pinta de rojo los sábados y
    domingos del calendario; acá se los deja como cualquier otro día, para
    que en los reportes el rojo no parezca un aviso.
    """
    campo = QDateEdit(fecha_inicial or QDate.currentDate())
    campo.setCalendarPopup(True)
    calendario = campo.calendarWidget()
    dia_comun = calendario.weekdayTextFormat(Qt.Monday)
    for dia in (Qt.Saturday, Qt.Sunday):
        calendario.setWeekdayTextFormat(dia, dia_comun)
    return campo


def armar_filtro_por_fechas(buscar, desde_inicial=None, extras=(), solo_hoy=False, estirar=True):
    """
    Arma la fila de filtros de las pantallas que consultan un rango de
    fechas: "Desde", "Hasta", lo que cada pantalla agregue (`extras`), el
    botón "Solo Hoy" (si se pide) y "Buscar".

    Devuelve (fecha_desde, fecha_hasta, layout): los dos QDateEdit, con
    calendario desplegable, para que la pantalla lea el rango, y la fila ya
    armada para agregarla a su layout.

    - `buscar`: función sin argumentos que hace la búsqueda; la disparan el
      botón "Buscar" y Enter en el último campo.
    - `desde_inicial`: QDate con el que arranca "Desde" (hoy, por defecto);
      "Hasta" siempre arranca en hoy.
    - `extras`: lista de (etiqueta, widget) que van entre "Hasta" y los
      botones (por ejemplo, un combo "Agrupar:"). Entran en la cadena de
      Enter, en ese orden.
    - `solo_hoy`: agrega "Solo Hoy", que pone las dos fechas en hoy y busca.
    - `estirar`: deja los botones pegados a la izquierda.
    """
    fecha_desde = crear_selector_de_fecha(desde_inicial)
    fecha_hasta = crear_selector_de_fecha()

    filtros = QHBoxLayout()
    filtros.addWidget(QLabel("Desde:"))
    filtros.addWidget(fecha_desde)
    filtros.addWidget(QLabel("Hasta:"))
    filtros.addWidget(fecha_hasta)
    for etiqueta, widget in extras:
        filtros.addWidget(QLabel(etiqueta))
        filtros.addWidget(widget)

    if solo_hoy:
        def poner_solo_hoy():
            fecha_desde.setDate(QDate.currentDate())
            fecha_hasta.setDate(QDate.currentDate())
            buscar()

        boton_hoy = QPushButton("Solo Hoy")
        boton_hoy.clicked.connect(poner_solo_hoy)
        filtros.addWidget(boton_hoy)
    boton_buscar = QPushButton("Buscar")
    boton_buscar.clicked.connect(buscar)
    filtros.addWidget(boton_buscar)
    if estirar:
        filtros.addStretch()

    encadenar_enter(fecha_desde, fecha_hasta, *[widget for _, widget in extras], accion_final=buscar)
    return fecha_desde, fecha_hasta, filtros


def fecha_iso(fecha: QDate) -> str:
    """Una fecha de Qt como "YYYY-MM-DD", el formato con que los repos
    guardan y comparan fechas."""
    return fecha.toString("yyyy-MM-dd")


def rango_de_fechas(fecha_desde: QDateEdit, fecha_hasta: QDateEdit):
    """Las dos puntas de un filtro Desde/Hasta (ver `armar_filtro_por_fechas`)
    como "YYYY-MM-DD", listas para pasarle a un repo: `(desde, hasta)`."""
    return fecha_iso(fecha_desde.date()), fecha_iso(fecha_hasta.date())


# Cuadros de mensaje. Siempre usarlos en vez de QMessageBox directo, así el
# tono (error / aviso / información) queda igual en todas las pantallas.

def mostrar_error(padre, titulo: str, mensaje: str):
    """Algo no se pudo hacer (dato inválido, falta un campo, etc.)."""
    QMessageBox.critical(padre, titulo, mensaje)


def mostrar_aviso(padre, titulo: str, mensaje: str):
    """Advertencia que no impide seguir."""
    QMessageBox.warning(padre, titulo, mensaje)


def mostrar_info(padre, titulo: str, mensaje: str):
    """Confirmación de que algo salió bien."""
    QMessageBox.information(padre, titulo, mensaje)


def confirmar(padre, titulo: str, mensaje: str) -> bool:
    """Pregunta Sí/No (No por defecto, para que un Enter apurado no
    confirme algo destructivo). True si eligió Sí."""
    respuesta = QMessageBox.question(
        padre, titulo, mensaje, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    return respuesta == QMessageBox.Yes
