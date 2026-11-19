"""
tests/base_tareas_turno.py
===========================
Lo que comparten las pruebas de las reglas de TAREAS DEL TURNO
(tests/test_tareas_turno.py y tests/test_tareas_turno_cambios.py): los días de la
semana de las pruebas, la base temporal con dos empleadas y el Administrador, y cómo
cargar y mirar las tareas. A propósito NO se llama "test_algo.py", como tests/base.py.
"""

from datetime import date, datetime, time

import dominio
from database import conexion_db
from repositories import tareas_turno_repo as repo
from repositories import usuarios_repo
from base import BaseConBaseTemporal

LUNES = date(2026, 11, 2)
MARTES = date(2026, 11, 3)
MIERCOLES = date(2026, 11, 4)

LUCES = "PRENDER LAS LUCES DE AFUERA"
TODOS = dominio.TAREA_TODOS_LOS_DIAS
ALGUNOS = dominio.TAREA_ALGUNOS_DIAS
SOLO_HOY = dominio.TAREA_UN_SOLO_DIA


def _el(dia: date, hora: str) -> datetime:
    """Un momento del CALENDARIO (no del local): el 04/11 a las 02:00 es la Noche del 03/11."""
    return datetime.combine(dia, time.fromisoformat(hora))


class _ConTareas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.lucia_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        self.gaby_id = usuarios_repo.crear_usuario("Gaby", "1234", dominio.ROL_EMPLEADA)
        self.admin_id = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)

    def _crear(self, texto=LUCES, hora="19:30", repeticion=TODOS, dias=None, a_las=None):
        """Una tarea cargada por el Admin, por defecto el martes a las 08:00."""
        return repo.crear_tarea(self.admin_id, texto, hora, repeticion, dias, ahora=a_las or _el(MARTES, "08:00"))

    @staticmethod
    def _del_dia(dia, ahora):
        return [(t["texto"], t["estado"]) for t in repo.tareas_del_dia(dia, ahora)]

    @staticmethod
    def _avisos(ahora):
        return [t["texto"] for t in repo.tareas_para_avisar(ahora)]

    def _fila(self, tabla, fila_id):
        with conexion_db() as conexion:
            return conexion.execute(f"SELECT * FROM {tabla} WHERE id = ?", (fila_id,)).fetchone()

    def _marcas(self):
        with conexion_db() as conexion:
            return [tuple(fila) for fila in conexion.execute(
                "SELECT tarea_id, dia, accion, minutos, usuario_id, fecha FROM tareas_turno_marcas ORDER BY id"
            )]
