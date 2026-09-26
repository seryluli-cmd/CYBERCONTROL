"""
utils.py
=========
Funciones chiquitas que se repiten en varias pantallas: dar formato a
números como pesos argentinos, mostrar cuadros de mensaje (avisos,
errores, confirmaciones), y un decorador para que ningún error
inesperado rompa una pantalla en silencio.
"""

import functools
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, Qt
from PySide6.QtWidgets import QAbstractSpinBox, QComboBox, QMessageBox, QWidget

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
      pensado para leerse directamente.
    - Cualquier otro error inesperado se guarda en el log de errores y
      se le muestra a la usuaria un cartel genérico, en vez de que la
      aplicación se rompa o quede en un estado raro.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except ValueError as error:
            mostrar_error(self, "No se pudo completar", str(error))
        except Exception as error:
            registrar_error(error)
            mostrar_error(
                self, "Ocurrió un error inesperado",
                "Algo falló y la acción no se pudo completar.\n"
                "El detalle quedó guardado en data/errores.log para revisarlo después.\n\n"
                f"({error.__class__.__name__}: {error})"
            )
    return wrapper


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


def formato_tiempo(segundos: int) -> str:
    """
    Convierte segundos en un texto legible ("2h 05m" o "45m 12s"). Vive
    acá (y no en un solo módulo de Control de PCs) porque tanto
    ui/pcs_window.py como ui/miembros_window.py lo necesitan — puesto
    en cualquiera de los dos, el otro tendría que importarlo cruzado.
    """
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}m"
    return f"{minutos}m {seg:02d}s"


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


def mostrar_error(padre, titulo: str, mensaje: str):
    QMessageBox.critical(padre, titulo, mensaje)


def mostrar_aviso(padre, titulo: str, mensaje: str):
    QMessageBox.warning(padre, titulo, mensaje)


def mostrar_info(padre, titulo: str, mensaje: str):
    QMessageBox.information(padre, titulo, mensaje)


def confirmar(padre, titulo: str, mensaje: str) -> bool:
    respuesta = QMessageBox.question(
        padre, titulo, mensaje, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    return respuesta == QMessageBox.Yes
