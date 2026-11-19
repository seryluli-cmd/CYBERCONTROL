"""
tests/test_tareas_turno_cuentas.py
===================================
TAREAS DEL TURNO (pedido del dueño, 2026-11-03): las cuentas puras, sin base, que
usan el repo, la pantalla y el aviso (dominio.py y turnos.momento_de_la_tarea):
cómo se escribe la hora y el texto, qué días se repite, cuándo pasa (la Noche que
cruza la medianoche), en qué estado está y cómo se muestra. Las reglas de adentro,
con la base, en tests/test_tareas_turno.py.

Se ejecutan con:

    python -m unittest discover tests -p "test_tareas_turno_cuentas.py"
"""

import unittest
from datetime import date, datetime, time, timedelta

import dominio
import turnos

MARTES = date(2026, 11, 3)
MIERCOLES = date(2026, 11, 4)

TODOS = dominio.TAREA_TODOS_LOS_DIAS
ALGUNOS = dominio.TAREA_ALGUNOS_DIAS
SOLO_HOY = dominio.TAREA_UN_SOLO_DIA


def _el(dia: date, hora: str) -> datetime:
    """Un momento del CALENDARIO (no del local): el 04/11 a las 02:00 es la Noche del 03/11."""
    return datetime.combine(dia, time.fromisoformat(hora))


class TestCuentasDeLasTareas(unittest.TestCase):
    def test_la_hora_se_escribe_de_varias_formas(self):
        casos = {
            "1930": "19:30", "19:30": "19:30", "19.30": "19:30", "19,30": "19:30", "7:05": "07:05",
            "730": "07:30", "19": "19:00", "7": "07:00", "19:30 hs": "19:30", "19hs": "19:00",
            " 19 : 30 ": "19:30", "0": "00:00", "00:00": "00:00", "23:59": "23:59", "5:59": "05:59",
        }
        for escrito, hora in casos.items():
            with self.subTest(escrito=escrito):
                self.assertEqual(dominio.hora_de_tarea(escrito), hora)

    def test_una_hora_que_no_se_entiende_da_error(self):
        for escrito in ("24:00", "19:60", "7:5", "abc", "12345", "-1:30", "1:2:3", "１９:３０", "2400"):
            with self.subTest(escrito=escrito):
                with self.assertRaisesRegex(ValueError, "No entiendo la hora"):
                    dominio.hora_de_tarea(escrito)
        for vacia in ("", "  ", None, "hs"):
            with self.subTest(vacia=vacia):
                with self.assertRaisesRegex(ValueError, "Escribí a qué hora"):
                    dominio.hora_de_tarea(vacia)

    def test_el_texto_de_la_tarea(self):
        self.assertEqual(dominio.revisar_tarea("  PRENDER   las luces​ "), "PRENDER las luces")
        largo = dominio.LARGO_MAXIMO_TAREA
        self.assertEqual(dominio.revisar_tarea("x" * largo), "x" * largo)
        with self.assertRaisesRegex(ValueError, "muy larga"):
            dominio.revisar_tarea("x" * (largo + 1))
        for vacio in ("", "   ", None, "​"):
            with self.subTest(vacio=vacio):
                with self.assertRaisesRegex(ValueError, "Escribí qué hay que hacer"):
                    dominio.revisar_tarea(vacio)

    def test_la_repeticion(self):
        self.assertEqual(dominio.revisar_repeticion(TODOS, [1, 2]), (TODOS, None))
        self.assertEqual(dominio.revisar_repeticion(SOLO_HOY), (SOLO_HOY, None))
        self.assertEqual(dominio.revisar_repeticion(ALGUNOS, (6, 0, 6)), (ALGUNOS, "0,6"))
        self.assertEqual(dominio.revisar_repeticion(ALGUNOS, range(7)), (TODOS, None))
        self.assertEqual(dominio.dias_de_la_tarea("0,6"), (0, 6))
        self.assertEqual(dominio.dias_de_la_tarea(None), ())
        with self.assertRaises(ValueError):
            dominio.revisar_repeticion(None)
        self.assertEqual(set(dominio.NOMBRE_REPETICION_TAREA), set(dominio.REPETICIONES_TAREA))
        self.assertEqual(dominio.NOMBRE_REPETICION_TAREA[ALGUNOS], "ELEGIR DÍAS")
        self.assertEqual(dominio.NOMBRE_REPETICION_TAREA[SOLO_HOY], "SOLO HOY")

    def test_el_momento_de_la_tarea_es_del_dia_del_local(self):
        self.assertEqual(turnos.momento_de_la_tarea(MARTES, "19:30"), _el(MARTES, "19:30"))
        self.assertEqual(turnos.momento_de_la_tarea("2026-11-03", "06:00"), _el(MARTES, "06:00"))
        self.assertEqual(turnos.momento_de_la_tarea(MARTES, "05:59"), _el(MIERCOLES, "05:59"))
        self.assertEqual(turnos.momento_de_la_tarea(MARTES, "00:00"), _el(MIERCOLES, "00:00"))
        # Siempre vuelve al mismo día del local, a cualquier hora.
        for hora in range(24):
            momento = turnos.momento_de_la_tarea(MARTES, f"{hora:02d}:30")
            self.assertEqual(turnos.dia_en_que_empezo_el_turno(momento), MARTES, hora)

    def test_el_estado_en_sus_bordes(self):
        las_19 = _el(MARTES, "19:00")
        estado = dominio.estado_de_la_tarea
        self.assertEqual(estado(True, True, las_19, las_19), dominio.TAREA_HECHA)
        self.assertEqual(estado(False, True, las_19, las_19), dominio.TAREA_NO_SE_HIZO)
        self.assertEqual(estado(False, False, las_19, las_19), dominio.TAREA_ATRASADA)
        self.assertEqual(estado(False, False, las_19, las_19 - timedelta(minutes=30)), dominio.TAREA_MAS_TARDE)
        self.assertEqual(estado(False, False, las_19, las_19 - timedelta(minutes=29, seconds=59)),
                         dominio.TAREA_PRONTO)
        self.assertEqual(len(set(dominio.ESTADOS_TAREA_DEL_DIA)), 5)

    def test_textos_para_mostrar(self):
        self.assertEqual([dominio.texto_minutos(m) for m in (0, 18, 60, 72, 125)],
                         ["0 min", "18 min", "1 h", "1 h 12 min", "2 h 5 min"])
        self.assertEqual(dominio.nombre_del_dia(MARTES), "martes 03/11")
        self.assertEqual(dominio.nombre_del_dia("2026-11-08"), "domingo 08/11")
        self.assertEqual(dominio.texto_se_repite(TODOS), "Todos los días")
        self.assertEqual(dominio.texto_se_repite(ALGUNOS, "0,2,4"), "Lun · Mié · Vie")
        self.assertEqual(dominio.texto_se_repite(SOLO_HOY, None, "2026-11-03"), "Solo el martes 03/11")

    def test_no_pisa_otros_estados(self):
        # Los de las ventas siguen como estaban.
        self.assertEqual(dominio.ESTADOS_VENTA, ("CONFIRMADA", "ANULADA"))
        self.assertEqual(dominio.ESTADOS_TAREA, ("ACTIVA", "BORRADA"))
        self.assertEqual(dominio.ACCIONES_TAREA, ("HECHA", "POSPUESTA"))


if __name__ == "__main__":
    unittest.main()
