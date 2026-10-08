"""
tests/test_selector_de_fecha.py
=================================
El calendario desplegable de los filtros de fecha (Reportes, Accesos de
Admin, movimientos de un artículo...): Qt pinta de rojo los sábados y
domingos, y en los reportes ese rojo se confundía con un aviso. Se prueba sin
abrir ninguna ventana (plataforma "offscreen" de Qt).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from ui.utils import armar_filtro_por_fechas, crear_selector_de_fecha  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _hay_color_propio(calendario, dia):
    """True si ese día de la semana tiene un color de texto distinto del común."""
    return calendario.weekdayTextFormat(dia).foreground().style() != Qt.NoBrush


class TestSelectorDeFecha(unittest.TestCase):
    def test_sabado_y_domingo_no_van_en_rojo(self):
        campo = crear_selector_de_fecha()   # el calendario vive mientras viva el campo

        for dia in (Qt.Saturday, Qt.Sunday):
            self.assertFalse(_hay_color_propio(campo.calendarWidget(), dia), dia)

    def test_arranca_en_la_fecha_pedida_o_en_hoy(self):
        self.assertEqual(crear_selector_de_fecha(QDate(2026, 10, 1)).date(), QDate(2026, 10, 1))
        self.assertEqual(crear_selector_de_fecha().date(), QDate.currentDate())

    def test_es_un_campo_con_calendario_desplegable(self):
        self.assertTrue(crear_selector_de_fecha().calendarPopup())

    def test_los_dos_campos_del_filtro_desde_hasta_tampoco_llevan_rojo(self):
        desde, hasta, _filtros = armar_filtro_por_fechas(lambda: None, QDate(2026, 10, 1))

        for campo in (desde, hasta):
            for dia in (Qt.Saturday, Qt.Sunday):
                self.assertFalse(_hay_color_propio(campo.calendarWidget(), dia))
        self.assertEqual(desde.date(), QDate(2026, 10, 1))


if __name__ == "__main__":
    unittest.main()
