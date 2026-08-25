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

from PySide6.QtWidgets import QMessageBox

# Junto al archivo de la base de datos, para tenerlo todo en la misma
# carpeta "data" (ver database.py).
_RUTA_LOG_ERRORES = Path(__file__).resolve().parent.parent / "data" / "errores.log"


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
