"""
tests/base.py
===============
Fixture compartida por casi todas las pruebas (`BaseConBaseTemporal`).
A propósito NO se llama "test_algo.py": ese nombre coincide con el patrón
que usa "python -m unittest discover tests" para buscar módulos de test,
y este archivo no tiene ningún test adentro, solo la base que los otros
heredan.

Tres cosas que hace por todas las pruebas (revisión general del 2026-11-16,
mejora 1):

1. **Nunca `data\\` del proyecto.** Apenas se importa este archivo,
   `database.DATA_DIR` y `database.DB_PATH` pasan a una carpeta temporal del
   proceso, y al terminar cada prueba vuelven ahí, no a `data\\`. Antes volvían
   a `data\\` y el reloj de una ventana principal que quedaba viva llegó a
   grabar un cierre forzoso en la base que hubiera en esa carpeta.

2. **Ventanas principales cerradas de verdad.** `deleteLater` sin bucle de
   eventos no destruye nada, y el reloj de la caja (`MainWindow._timer_caja`)
   seguía andando. Al terminar cada prueba se cierran (`close()`, que frena
   sus relojes en `closeEvent`) todas las `MainWindow` que queden abiertas.
   Con eso, además, la suite entera en un solo proceso ya no revienta con un
   "access violation".

3. **Base plantilla.** La base de prueba se crea UNA vez por proceso con el
   mismo `database.inicializar_base_de_datos()` y en cada `setUp` se copia el
   archivo (1 ms en vez de 0,7 s). Es la misma base: las pruebas de migración
   siguen armando su tabla vieja encima y llamando a `inicializar...` ellas.
   Con `CYBERCONTROL_PRUEBAS_SIN_PLANTILLA=1` cada prueba la crea de cero
   como antes (para comparar si alguna vez se sospecha de la plantilla).
"""

import atexit
import os
import shutil
import sys
import tempfile
import unittest
from datetime import datetime

import database

# --- 1. Nunca data\ del proyecto -------------------------------------------

_CARPETA_DEL_PROCESO = tempfile.mkdtemp(prefix="cybercontrol_pruebas_")
atexit.register(shutil.rmtree, _CARPETA_DEL_PROCESO, True)

database.DATA_DIR = os.path.join(_CARPETA_DEL_PROCESO, "data")
database.DB_PATH = os.path.join(database.DATA_DIR, "kiosko.db")

# --- 3. Base plantilla ------------------------------------------------------

_SIN_PLANTILLA = os.environ.get("CYBERCONTROL_PRUEBAS_SIN_PLANTILLA") == "1"


def _crear_plantilla():
    """Crea la base de prueba una sola vez, al importar este archivo: antes de
    que cualquier prueba (o su setUpClass) cambie algo de dominio o de los repos."""
    carpeta = os.path.join(_CARPETA_DEL_PROCESO, "plantilla")
    ruta = os.path.join(carpeta, "kiosko_plantilla.db")
    anteriores = database.DATA_DIR, database.DB_PATH
    database.DATA_DIR, database.DB_PATH = carpeta, ruta
    try:
        database.inicializar_base_de_datos()
    finally:
        database.DATA_DIR, database.DB_PATH = anteriores
    if os.path.exists(ruta + "-journal"):
        raise RuntimeError("La base plantilla quedó con su -journal: no se puede copiar como archivo.")
    return ruta


_PLANTILLA = None if _SIN_PLANTILLA else _crear_plantilla()

# --- 2. Ventanas principales cerradas de verdad ------------------------------


def cerrar_ventanas_principales():
    """Cierra todas las MainWindow que sigan abiertas (aunque nunca se hayan
    mostrado): `closeEvent` frena el reloj de la caja, el del parpadeo, la
    grilla de PCs y la vuelta del Admin."""
    main_window = sys.modules.get("ui.main_window")
    if main_window is None:
        return  # nadie importó la ventana principal: no puede haber ninguna
    from PySide6.QtWidgets import QApplication
    if QApplication.instance() is None:
        return
    for ventana in QApplication.topLevelWidgets():
        if isinstance(ventana, main_window.MainWindow):
            ventana.close()


def esperar_que_avance_el_reloj():
    """Espera hasta que `datetime.now()` cambie (en Windows avanza a saltos de
    hasta ~16 ms). Para pruebas que cierran un turno y enseguida venden: sin
    esto la venta puede quedar con la MISMA hora del cierre y caer en el turno
    cerrado, que va con `fecha > desde`. En el mostrador entre un cierre y la
    venta siguiente siempre pasa una persona."""
    antes = datetime.now()
    while datetime.now() <= antes:
        pass


class BaseConBaseTemporal(unittest.TestCase):
    """Apunta database.DATA_DIR/DB_PATH a una carpeta temporal propia de la
    prueba, con la base ya creada, y al terminar los devuelve a la carpeta
    temporal del proceso (nunca a data\\ del proyecto)."""

    def setUp(self):
        # Se anota primero para que corra ÚLTIMO, después de los addCleanup de
        # la propia prueba (que suelen hacer deleteLater y frenar la grilla).
        self.addCleanup(cerrar_ventanas_principales)
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._data_dir_original = database.DATA_DIR
        self._db_path_original = database.DB_PATH
        database.DATA_DIR = self._tmp_dir.name
        database.DB_PATH = os.path.join(self._tmp_dir.name, "kiosko_test.db")
        if _PLANTILLA is None:
            database.inicializar_base_de_datos()
        else:
            shutil.copyfile(_PLANTILLA, database.DB_PATH)

    def tearDown(self):
        database.DATA_DIR = self._data_dir_original
        database.DB_PATH = self._db_path_original
        self._tmp_dir.cleanup()
