"""
tests/base_tareas_turno_pantalla.py
====================================
Lo que comparten las pruebas de pantalla de TAREAS DEL TURNO
(tests/test_tareas_turno_aviso.py y tests/test_tareas_turno_pantalla.py): la base
temporal con una empleada y el Administrador, los textos de las tareas y la trampa
de los carteles de error. A propósito NO se llama "test_algo.py", como tests/base.py.
"""

import os
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from repositories import tareas_turno_repo, usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Un martes: las tareas se cargan a la mañana y las pruebas pasan a la tarde.
CARGA = datetime(2026, 11, 3, 8, 0)
LUCES = "PRENDER LAS LUCES DE AFUERA"
BASURA = "SACAR LA BASURA"
PERSIANA = "BAJAR LA PERSIANA"
CIGARRILLOS = "CONTAR CIGARRILLOS"
HELADERA = "LIMPIAR LA HELADERA"
DIARIOS = "ATAR LOS DIARIOS"


class _ConTareas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.carla_id = usuarios_repo.crear_usuario("Carla", "1234", dominio.ROL_EMPLEADA)
        self.admin_id = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.carla = usuarios_repo.obtener_usuario(self.carla_id)
        self.admin = usuarios_repo.obtener_usuario(self.admin_id)
        # Las preguntas Sí/No contestan que sí (salvo que la prueba diga otra cosa) y
        # los avisos no se abren.
        self.pregunta = mock.patch("ui.tareas_turno_window.confirmar", return_value=True).start()
        self.avisos = mock.patch("ui.tareas_turno_window.mostrar_aviso").start()
        # Un error que agarra manejar_errores abriría un cartel modal que nadie cierra,
        # y uno que va al log (la revisión de los avisos no muestra carteles) pasaría
        # callado. Se anotan y la prueba falla al terminar, con su texto: un self.fail
        # acá no alcanzaba, porque un error que sale dentro de un clic
        # (QPushButton.click) PySide6 solo lo imprime y la prueba seguía en OK. Una
        # prueba que espera un cartel pone su propio mostrar_error.
        self._errores = []
        mock.patch("ui.utils.mostrar_error",
                   side_effect=lambda _padre, titulo, texto: self._errores.append(f"{titulo}: {texto}")).start()
        for donde in ("ui.aviso_tarea.registrar_error", "ui.tareas_turno_window.registrar_error"):
            mock.patch(donde, side_effect=lambda error, contexto: self._errores.append(f"{contexto}: {error!r}")).start()
        self.addCleanup(self._sin_errores)
        self.addCleanup(mock.patch.stopall)

    def _sin_errores(self):
        self.assertEqual(self._errores, [], "salió un cartel de error o algo fue al log")

    def _cargar(self, texto, hora, repeticion=dominio.TAREA_TODOS_LOS_DIAS, dias=None, ahora=CARGA):
        return tareas_turno_repo.crear_tarea(self.admin_id, texto, hora, repeticion, dias, ahora=ahora)

    @staticmethod
    def _de_hoy(ahora):
        return {tarea["texto"]: tarea for tarea in tareas_turno_repo.tareas_del_dia(None, ahora)}
