"""
tests/test_formato_pesos.py
=============================
La plata se ve como se lee en el local: "$ 1.500", "$ 30.000", con el punto de
los miles y sin centavos (pedido del dueño, 2026-10-26: todos los precios son en
miles y "$ 1.500,00" o "1500,00" se leían mal). Los centavos se ven solo si un
monto los tiene de verdad, para que una suma de la caja no parezca no cerrar.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import pathlib
import re
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from ui.utils import CampoPesos, formato_pesos  # noqa: E402

_app = QApplication.instance() or QApplication([])
RAIZ = pathlib.Path(__file__).resolve().parent.parent


class TestTextoPesos(unittest.TestCase):
    def test_en_miles_y_sin_centavos(self):
        for monto, esperado in ((1500, "$ 1.500"), (9000.0, "$ 9.000"), (30000, "$ 30.000"),
                                (150000, "$ 150.000"), (0, "$ 0"), (50, "$ 50"), (1_234_567, "$ 1.234.567")):
            with self.subTest(monto=monto):
                self.assertEqual(dominio.texto_pesos(monto), esperado)

    def test_los_centavos_solo_si_los_tiene(self):
        self.assertEqual(dominio.texto_pesos(1234.5), "$ 1.234,50")
        self.assertEqual(dominio.texto_pesos(0.25), "$ 0,25")
        # Lo que queda de una cuenta con decimales de la computadora no son centavos.
        self.assertEqual(dominio.texto_pesos(1500.0000001), "$ 1.500")
        self.assertEqual(dominio.texto_pesos(0.1 + 0.2), "$ 0,30")

    def test_negativo_y_vacio(self):
        self.assertEqual(dominio.texto_pesos(-500), "$ -500")
        self.assertEqual(dominio.texto_pesos(None), "$ 0")
        self.assertEqual(dominio.texto_pesos("no es un número"), "$ 0")

    def test_la_pantalla_usa_el_mismo_formato(self):
        self.assertEqual(formato_pesos(30000), dominio.texto_pesos(30000))


class TestCampoPesos(unittest.TestCase):
    def setUp(self):
        self.campo = CampoPesos()
        self.addCleanup(self.campo.deleteLater)
        self.campo.show()

    def _escribir(self, texto):
        self.campo.lineEdit().selectAll()
        QTest.keyClicks(self.campo.lineEdit(), texto)
        self.campo.interpretText()

    def test_se_ve_en_miles_sin_centavos(self):
        self.campo.setValue(1500)
        self.assertEqual(self.campo.text(), "$ 1.500")
        self.campo.setValue(30000)
        self.assertEqual(self.campo.text(), "$ 30.000")

    def test_se_escribe_con_o_sin_el_punto_de_los_miles(self):
        for texto in ("30000", "30.000"):
            with self.subTest(texto=texto):
                self._escribir(texto)
                self.assertEqual(self.campo.value(), 30000)

    def test_la_coma_es_para_los_centavos(self):
        self._escribir("1.500,50")
        self.assertEqual(self.campo.value(), 1500.5)
        self.assertEqual(self.campo.text(), "$ 1.500,50")

    def test_no_deja_escribir_letras_ni_pasarse_del_maximo(self):
        self.campo.setValue(700)
        self._escribir("12a")
        self.assertEqual(self.campo.value(), 12)
        self._escribir("999999999")
        self.assertLessEqual(self.campo.value(), self.campo.maximum())


class TestUnSoloLugar(unittest.TestCase):
    """Una pantalla nueva sale con el formato sin acordarse: los montos se escriben
    en un CampoPesos y se piden con pedir_pesos, nunca con un QDoubleSpinBox o un
    QInputDialog.getDouble sueltos (mostraban "1500,00")."""

    def test_ninguna_pantalla_arma_un_campo_de_plata_suelto(self):
        sueltos = []
        for carpeta in ("ui", "control_pcs/ui"):
            for archivo in (RAIZ / carpeta).glob("*.py"):
                texto = archivo.read_text(encoding="utf-8")
                for patron in (r"QDoubleSpinBox\(\)", r"getDouble\("):
                    if re.search(patron, texto):
                        sueltos.append(f"{carpeta}/{archivo.name}: {patron}")
        self.assertEqual(sueltos, [])


if __name__ == "__main__":
    unittest.main()
