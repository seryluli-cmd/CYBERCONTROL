"""
tests/test_reportes_ui.py
===========================
La pestaña "Resumen del Día" de Reportes (se prueba sin abrir ninguna ventana,
plataforma "offscreen" de Qt): el aviso de los cierres que se hicieron ese día pero
quedaron anotados en otro (un cierre hecho tras varios días sin cerrar cae en el turno
viejo y las filas de hoy salen en cero) y el "Cerrado el 10/10" del estado cuando un turno
se cerró otro día. Las cuentas de fondo están en tests/test_kiosko.py (TestResumenDelDia).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import dominio  # noqa: E402
from repositories import turnos_repo, usuarios_repo  # noqa: E402
from ui.reportes_window import PestañaResumenDelDia  # noqa: E402
from ui.utils import hoy_del_local  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

_COLUMNA_ESTADO = 1
_COLUMNA_CERRO = 2
_FILA_NOCHE = 2     # los lunes (y cualquier día que no sea domingo): Mañana, Tarde, Noche


class TestResumenDelDiaEnPantalla(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.usuario_id = usuarios_repo.crear_usuario("Pedro", "1234", dominio.ROL_EMPLEADA)

    def _cerrar(self, momento):
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            turnos_repo.cerrar_turno(self.usuario_id)

    def _abrir(self, dia: QDate):
        pestaña = PestañaResumenDelDia()
        self.addCleanup(pestaña.deleteLater)
        pestaña.fecha.setDate(dia)
        return pestaña

    @staticmethod
    def _textos_del_aviso(pestaña):
        return [etiqueta.text() for etiqueta in pestaña.aviso.findChildren(QLabel)]

    def test_avisa_el_cierre_que_quedo_anotado_en_otro_dia_y_el_boton_lleva_a_ese_dia(self):
        # El lunes 5 a la noche se cierra por primera vez; el siguiente cierre es
        # recién el jueves 8 a las 19:58, así que queda anotado en la Noche del lunes.
        self._cerrar(datetime(2026, 1, 5, 23, 58))
        self._cerrar(datetime(2026, 1, 8, 19, 58))

        pestaña = self._abrir(QDate(2026, 1, 8))

        self.assertTrue(pestaña.aviso.isVisibleTo(pestaña))
        textos = self._textos_del_aviso(pestaña)
        self.assertIn("Este día se cerró un turno que quedó anotado en otro día:", textos)
        self.assertIn("•  Noche del 05/01/2026 — cerró Pedro a las 19:58", textos)
        botones = pestaña.aviso.findChildren(QPushButton)
        self.assertEqual([b.text() for b in botones], ["Ver el 05/01/2026"])

        botones[0].click()

        # Lleva al lunes: ahí no hay nada que avisar y el turno figura cerrado, aclarando
        # el día en que se cerró (si no, "19:58" parecería de ese mismo lunes).
        self.assertEqual(pestaña.fecha.date(), QDate(2026, 1, 5))
        self.assertFalse(pestaña.aviso.isVisibleTo(pestaña))
        self.assertEqual(pestaña.tabla.item(_FILA_NOCHE, _COLUMNA_ESTADO).text(), "Cerrado el 08/01")
        self.assertEqual(pestaña.tabla.item(_FILA_NOCHE, _COLUMNA_CERRO).text(), "Pedro · 19:58")

    def test_los_dias_sin_cierres_anotados_en_otro_dia_no_muestran_el_aviso(self):
        self._cerrar(datetime(2026, 1, 5, 23, 58))
        self._cerrar(datetime(2026, 1, 8, 19, 58))

        # El lunes (donde quedó anotado) y los dos días del medio, donde no se cerró nada.
        for dia in (QDate(2026, 1, 5), QDate(2026, 1, 6), QDate(2026, 1, 7)):
            with self.subTest(dia=dia):
                pestaña = self._abrir(dia)
                self.assertFalse(pestaña.aviso.isVisibleTo(pestaña))

    def test_dice_hoy_cuando_el_cierre_se_hizo_hoy(self):
        ahora = datetime.now()
        self._cerrar(ahora - timedelta(days=11))
        self._cerrar(ahora)

        # El "hoy" del local, no el calendario (QDate.currentDate): de 00:00 a 06:00
        # un cierre hecho recién es del día anterior y no figuraba en el de calendario.
        pestaña = self._abrir(hoy_del_local())

        self.assertTrue(pestaña.aviso.isVisibleTo(pestaña))
        self.assertIn("Hoy se cerró un turno que quedó anotado en otro día:", self._textos_del_aviso(pestaña))

    def test_un_turno_cerrado_el_mismo_dia_se_ve_como_siempre(self):
        self._cerrar(datetime(2026, 1, 5, 6, 5))
        self._cerrar(datetime(2026, 1, 5, 14, 5))

        pestaña = self._abrir(QDate(2026, 1, 5))

        self.assertEqual(pestaña.tabla.item(0, _COLUMNA_ESTADO).text(), "Cerrado")
        self.assertEqual(pestaña.tabla.item(0, _COLUMNA_CERRO).text(), "Pedro · 14:05")

    def test_la_noche_cerrada_a_la_madrugada_se_ve_como_siempre_y_no_dispara_el_aviso(self):
        self._cerrar(datetime(2026, 1, 5, 22, 5))
        self._cerrar(datetime(2026, 1, 6, 6, 30))

        del_lunes = self._abrir(QDate(2026, 1, 5))
        del_martes = self._abrir(QDate(2026, 1, 6))

        self.assertEqual(del_lunes.tabla.item(_FILA_NOCHE, _COLUMNA_ESTADO).text(), "Cerrado")
        self.assertEqual(del_lunes.tabla.item(_FILA_NOCHE, _COLUMNA_CERRO).text(), "Pedro · 06:30")
        self.assertFalse(del_martes.aviso.isVisibleTo(del_martes))


if __name__ == "__main__":
    unittest.main()
