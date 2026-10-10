"""Registro de fallos compartido por la interfaz y el servidor de red."""

import traceback
import threading
from datetime import datetime
from pathlib import Path

import database

_LOG_LOCK = threading.Lock()


def registrar_error(excepcion: Exception, contexto: str = None):
    """Guarda una traza en data/errores.log sin depender de Qt.

    La ruta se resuelve al escribir para respetar la base temporal de los tests.
    El contexto debe describir la operación, nunca incluir claves ni pedidos.
    """
    try:
        ruta = Path(database.DATA_DIR) / "errores.log"
        ruta.parent.mkdir(parents=True, exist_ok=True)
        with _LOG_LOCK, ruta.open("a", encoding="utf-8") as archivo:
            archivo.write(f"\n--- {datetime.now().isoformat(timespec='seconds')} ---\n")
            if contexto:
                archivo.write(f"{contexto}\n")
            archivo.write("".join(traceback.format_exception(
                type(excepcion), excepcion, excepcion.__traceback__,
            )))
    except Exception:
        pass  # registrar un error no puede causar un segundo fallo
