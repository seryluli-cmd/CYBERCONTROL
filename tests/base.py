"""
tests/base.py
===============
Fixture compartida entre tests/test_kiosko.py y tests/test_control_pcs.py.
A propósito NO se llama "test_algo.py": ese nombre coincide con el patrón
que usa "python -m unittest discover tests" para buscar módulos de test,
y este archivo no tiene ningún test adentro, solo la base que los otros
dos heredan.
"""

import os
import tempfile
import unittest

import database


class BaseConBaseTemporal(unittest.TestCase):
    """Apunta database.DATA_DIR/DB_PATH a un archivo temporal antes de
    cada test, y lo restaura al terminar."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._data_dir_original = database.DATA_DIR
        self._db_path_original = database.DB_PATH
        database.DATA_DIR = self._tmp_dir.name
        database.DB_PATH = os.path.join(self._tmp_dir.name, "kiosko_test.db")
        database.inicializar_base_de_datos()

    def tearDown(self):
        database.DATA_DIR = self._data_dir_original
        database.DB_PATH = self._db_path_original
        self._tmp_dir.cleanup()
