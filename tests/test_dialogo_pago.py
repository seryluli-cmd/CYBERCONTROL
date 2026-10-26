"""
tests/test_dialogo_pago.py
============================
El cuadro de cobro (ui/dialogo_pago.DialogoPago), que usan las ventas de kiosko,
los bonos de Control de PCs (PC, PCSTREAM, PlayStation 5) y el Mixto de la carga de
saldo y los trámites, y su cuenta (dominio.cuenta_del_cobro).

Pedidos del dueño (2026-10-18): arranca con el total escrito en Efectivo, porque casi
siempre pagan justo, y si pagan justo un Enter cobra; si pagan con otro billete, lo
que se escribe reemplaza al total. Efectivo y Digital están siempre a la vista: al
escribir en uno, el otro se completa con lo que falta; "Paga con" da el vuelto sin
tocar lo digital. Un Enter cobra siempre, también con vuelto (pedido del dueño, esa
misma noche). Un Enter que queda apretado no cobra solo.
Se prueba sin abrir ninguna ventana, plataforma "offscreen" de Qt.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt, QTimer  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import dominio  # noqa: E402

from ui.dialogo_pago import DialogoPago, cobrar  # noqa: E402

_app = QApplication.instance() or QApplication([])

_EFECTIVO = dominio.PAGO_EFECTIVO
_DIGITAL = dominio.PAGO_DIGITAL


class TestCuentaDelCobro(unittest.TestCase):
    """La cuenta, sin pantalla."""

    def test_pago_justo_en_efectivo(self):
        cuenta = dominio.cuenta_del_cobro(1500.0, 1500.0, 0.0)
        self.assertEqual((cuenta["vuelto"], cuenta["falta"]), (0.0, 0.0))
        self.assertEqual(cuenta["pagos"], [{"metodo": _EFECTIVO, "monto": 1500.0}])

    def test_una_parte_en_cada_medio(self):
        cuenta = dominio.cuenta_del_cobro(1500.0, 1000.0, 500.0)
        self.assertEqual(cuenta["pagos"], [{"metodo": _EFECTIVO, "monto": 1000.0}, {"metodo": _DIGITAL, "monto": 500.0}])
        self.assertEqual(cuenta["vuelto"], 0.0)

    def test_el_billete_escrito_en_efectivo_da_vuelto_y_en_la_caja_queda_el_total(self):
        cuenta = dominio.cuenta_del_cobro(1500.0, 2000.0, 0.0)
        self.assertEqual(cuenta["vuelto"], 500.0)
        self.assertEqual(cuenta["pagos"], [{"metodo": _EFECTIVO, "monto": 1500.0}])

    def test_paga_con_da_vuelto_sin_tocar_lo_digital(self):
        # El ejemplo del dueño: $1.500 = $1.000 efectivo + $500 digital, y los
        # $1.000 los paga con uno de $2.000.
        cuenta = dominio.cuenta_del_cobro(1500.0, 1000.0, 500.0, paga_con=2000.0)
        self.assertEqual(cuenta["vuelto"], 1000.0)
        self.assertEqual(cuenta["pagos"], [{"metodo": _EFECTIVO, "monto": 1000.0}, {"metodo": _DIGITAL, "monto": 500.0}])

    def test_si_paga_con_menos_que_la_parte_en_efectivo_falta(self):
        cuenta = dominio.cuenta_del_cobro(1500.0, 1000.0, 500.0, paga_con=800.0)
        self.assertEqual((cuenta["falta"], cuenta["vuelto"]), (200.0, 0.0))

    def test_todo_digital_no_da_vuelto_aunque_quede_un_billete_escrito(self):
        cuenta = dominio.cuenta_del_cobro(1500.0, 0.0, 1500.0, paga_con=2000.0)
        self.assertEqual((cuenta["vuelto"], cuenta["falta"]), (0.0, 0.0))
        self.assertEqual(cuenta["pagos"], [{"metodo": _DIGITAL, "monto": 1500.0}])

    def test_lo_digital_nunca_pasa_el_total(self):
        cuenta = dominio.cuenta_del_cobro(1500.0, 0.0, 9999.0)
        self.assertEqual(cuenta["pagos"], [{"metodo": _DIGITAL, "monto": 1500.0}])


class TestDialogoPago(unittest.TestCase):
    def _abrir(self, total=2100.0):
        dialogo = DialogoPago(None, total)
        self.addCleanup(dialogo.deleteLater)
        dialogo.show()
        dialogo.activateWindow()
        QApplication.processEvents()
        return dialogo

    @staticmethod
    def _enter(widget, repetido=False):
        """Un Enter en `widget`, adonde lo manda el teclado de verdad (al campo, no
        a su QLineEdit de adentro: mandándolo ahí las pruebas pasaban y en el
        mostrador Enter no cobraba, ver ui.utils._widgets_de_teclado); `repetido`
        es la repetición del teclado (tecla apretada)."""
        for tipo in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(widget,QKeyEvent(tipo, Qt.Key_Return, Qt.NoModifier, "\r", repetido))

    @staticmethod
    def _escribir(campo, texto):
        """Como la empleada: entra al campo (queda seleccionado) y escribe encima."""
        campo.setFocus()
        campo.selectAll()
        QTest.keyClicks(campo.lineEdit(), texto)

    def test_arranca_con_el_total_en_efectivo_y_seleccionado(self):
        dialogo = self._abrir(2100.0)

        self.assertEqual((dialogo.campo_efectivo.value(), dialogo.campo_digital.value()), (2100.0, 0.0))
        self.assertTrue(dialogo.campo_efectivo.hasFocus())
        self.assertTrue(dialogo.campo_efectivo.lineEdit().hasSelectedText())
        self.assertEqual(dialogo.campo_paga_con.text(), "paga justo")
        self.assertEqual(dialogo.vuelto, 0.0)

    def test_pago_justo_en_efectivo_cobra_con_un_enter(self):
        dialogo = self._abrir(2100.0)

        self._enter(dialogo.campo_efectivo)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 2100.0}])
        self.assertEqual(dialogo.vuelto, 0.0)

    def test_todo_digital_y_enter_cobra(self):
        dialogo = self._abrir(2100.0)

        dialogo.boton_todo_digital.click()
        self.assertEqual((dialogo.campo_efectivo.value(), dialogo.campo_digital.value()), (0.0, 2100.0))
        self.assertFalse(dialogo.campo_paga_con.isEnabled())
        self.assertTrue(dialogo.campo_digital.hasFocus())
        self._enter(dialogo.campo_digital)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertEqual(dialogo.pagos, [{"metodo": _DIGITAL, "monto": 2100.0}])

    def test_una_parte_en_efectivo_completa_sola_la_digital_y_enter_cobra(self):
        # Así arranca también el cobro Mixto de PCs, PlayStation 5, socios y trámites.
        dialogo = self._abrir(1500.0)

        self._escribir(dialogo.campo_efectivo, "1000")
        self.assertEqual(dialogo.campo_digital.value(), 500.0)
        self._enter(dialogo.campo_efectivo)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 1000.0}, {"metodo": _DIGITAL, "monto": 500.0}])

    def test_escribir_en_digital_completa_el_efectivo(self):
        dialogo = self._abrir(1500.0)

        self._escribir(dialogo.campo_digital, "300")

        self.assertEqual(dialogo.campo_efectivo.value(), 1200.0)
        dialogo.boton_todo_efectivo.click()
        self.assertEqual((dialogo.campo_efectivo.value(), dialogo.campo_digital.value()), (1500.0, 0.0))

    def test_con_otro_billete_en_efectivo_muestra_el_vuelto_y_un_enter_cobra(self):
        dialogo = self._abrir(2100.0)

        self._escribir(dialogo.campo_efectivo, "5000")
        self.assertEqual(dialogo.campo_digital.value(), 0.0)
        # El vuelto se ve mientras se escribe el billete.
        self.assertIn("2.900", dialogo.etiqueta_vuelto.text())
        self._enter(dialogo.campo_efectivo)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        # Lo que queda en la caja, neto del vuelto.
        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 2100.0}])
        self.assertEqual(dialogo.vuelto, 2900.0)

    def test_paga_con_da_el_vuelto_sin_tocar_lo_digital(self):
        dialogo = self._abrir(1500.0)
        self._escribir(dialogo.campo_digital, "500")

        self._escribir(dialogo.campo_paga_con, "2000")

        self.assertEqual(dialogo.campo_digital.value(), 500.0)
        self.assertEqual(dialogo.vuelto, 1000.0)
        self._enter(dialogo.campo_paga_con)
        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 1000.0}, {"metodo": _DIGITAL, "monto": 500.0}])

    def test_si_paga_con_menos_no_deja_cobrar(self):
        dialogo = self._abrir(1500.0)

        self._escribir(dialogo.campo_paga_con, "1000")

        self.assertFalse(dialogo.boton_confirmar.isEnabled())
        self.assertIn("faltan $ 500", dialogo.etiqueta_falta.text())
        self._enter(dialogo.campo_paga_con)
        self.assertTrue(dialogo.isVisible())
        self.assertEqual(dialogo.pagos, [])

    def test_un_enter_apretado_no_cobra(self):
        dialogo = self._abrir(2100.0)

        self._enter(dialogo.campo_efectivo, repetido=True)

        self.assertTrue(dialogo.isVisible())
        self.assertEqual(dialogo.pagos, [])

    def test_un_enter_apretado_en_confirmar_no_confirma(self):
        dialogo = self._abrir(2100.0)
        self._escribir(dialogo.campo_efectivo, "5000")
        dialogo.boton_confirmar.setFocus()  # llegando con Tab

        self._enter(dialogo.boton_confirmar, repetido=True)
        self.assertTrue(dialogo.isVisible())

        self._enter(dialogo.boton_confirmar)
        self.assertEqual(dialogo.result(), QDialog.Accepted)

    def test_un_enter_de_mas_no_cobra_dos_veces(self):
        dialogo = self._abrir(2100.0)
        self._enter(dialogo.campo_efectivo)

        self._enter(dialogo.campo_efectivo)
        self._enter(dialogo.boton_confirmar)

        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 2100.0}])


class TestCobrar(unittest.TestCase):
    """`cobrar` abre el cuadro de verdad (modal): lo que haría la empleada se
    manda apenas aparece, desde el mismo bucle de eventos."""

    def _con_el_cuadro_abierto(self, accion):
        def hacer():
            QApplication.processEvents()  # que termine de mostrarse (deja el total seleccionado)
            dialogo = QApplication.activeModalWidget()
            try:
                accion(dialogo)
            finally:
                # Si la prueba falla, que la ventana no quede abierta para siempre.
                if isinstance(dialogo, DialogoPago) and dialogo.isVisible():
                    dialogo.reject()
        QTimer.singleShot(0, hacer)

    def test_pago_justo_devuelve_los_pagos(self):
        self._con_el_cuadro_abierto(lambda dialogo: TestDialogoPago._enter(dialogo.campo_efectivo))

        pagos = cobrar(None, 4000.0)

        self.assertEqual(pagos, [{"metodo": _EFECTIVO, "monto": 4000.0}])

    def test_con_vuelto_devuelve_lo_que_queda_en_la_caja(self):
        def pagar_con_5000(dialogo):
            TestDialogoPago._escribir(dialogo.campo_efectivo, "5000")
            self.assertEqual(dialogo.vuelto, 1000.0)
            TestDialogoPago._enter(dialogo.campo_efectivo)
        self._con_el_cuadro_abierto(pagar_con_5000)

        pagos = cobrar(None, 4000.0)

        self.assertEqual(pagos, [{"metodo": _EFECTIVO, "monto": 4000.0}])

    def test_cancelar_devuelve_none(self):
        self._con_el_cuadro_abierto(lambda dialogo: dialogo.reject())

        self.assertIsNone(cobrar(None, 4000.0))


if __name__ == "__main__":
    unittest.main()
