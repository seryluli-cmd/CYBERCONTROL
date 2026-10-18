"""
tests/test_dialogo_pago.py
============================
El cuadro de cobro (ui/dialogo_pago.DialogoPago), que usan las ventas de kiosko,
los bonos de Control de PCs (PC, PCSTREAM, PlayStation 5) y el Mixto de la carga de
saldo y los trámites.
Pedido del dueño (2026-10-18): el monto arranca escrito con el total, porque casi
siempre pagan justo; si pagan justo, un Enter cobra; si pagan con otro billete, lo
que se escribe reemplaza al total. Y un Enter que queda apretado no cobra solo.
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


class TestDialogoPago(unittest.TestCase):
    def _abrir(self, total=2100.0):
        dialogo = DialogoPago(None, total)
        self.addCleanup(dialogo.deleteLater)
        dialogo.show()
        QApplication.processEvents()
        return dialogo

    @staticmethod
    def _enter(widget, repetido=False):
        """Un Enter en `widget`; `repetido` es la repetición del teclado (tecla apretada)."""
        destino = widget.lineEdit() if hasattr(widget, "lineEdit") and widget.lineEdit() else widget
        for tipo in (QEvent.KeyPress, QEvent.KeyRelease):
            QApplication.sendEvent(destino, QKeyEvent(tipo, Qt.Key_Return, Qt.NoModifier, "\r", repetido))

    @staticmethod
    def _escribir(dialogo, texto):
        QTest.keyClicks(dialogo.spin_monto.lineEdit(), texto)

    def _elegir_medio(self, dialogo, metodo):
        dialogo.combo_metodo.setCurrentIndex(dialogo.combo_metodo.findData(metodo))

    def test_arranca_con_el_total_escrito_y_seleccionado(self):
        dialogo = self._abrir(2100.0)

        self.assertEqual(dialogo.spin_monto.value(), 2100.0)
        self.assertTrue(dialogo.spin_monto.lineEdit().hasSelectedText())
        self.assertEqual(dialogo.vuelto, 0.0)

    def test_pago_justo_en_efectivo_cobra_con_un_enter(self):
        dialogo = self._abrir(2100.0)

        self._enter(dialogo.spin_monto)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 2100.0}])
        self.assertEqual(dialogo.vuelto, 0.0)

    def test_pago_justo_digital_cobra_con_un_enter(self):
        dialogo = self._abrir(2100.0)
        self._elegir_medio(dialogo, _DIGITAL)

        self._enter(dialogo.spin_monto)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertEqual(dialogo.pagos, [{"metodo": _DIGITAL, "monto": 2100.0}])

    def test_al_volver_del_medio_de_pago_el_monto_queda_seleccionado(self):
        dialogo = self._abrir(2100.0)
        dialogo.combo_metodo.setFocus()
        self._elegir_medio(dialogo, _DIGITAL)

        self._enter(dialogo.combo_metodo)
        self._escribir(dialogo, "1000")

        self.assertTrue(dialogo.spin_monto.hasFocus())
        self.assertEqual(dialogo.spin_monto.value(), 1000.0)

    def test_con_otro_billete_lo_escrito_reemplaza_al_total_y_frena_para_ver_el_vuelto(self):
        dialogo = self._abrir(2100.0)

        self._escribir(dialogo, "5000")
        self.assertEqual(dialogo.spin_monto.value(), 5000.0)
        self._enter(dialogo.spin_monto)

        # Todavía no cobró: la empleada tiene que ver el vuelto antes.
        self.assertEqual(dialogo.result(), QDialog.Rejected)
        self.assertTrue(dialogo.isVisible())
        self.assertEqual(dialogo.vuelto, 2900.0)
        self.assertIn("2.900", dialogo.etiqueta_vuelto.text())
        self.assertTrue(dialogo.boton_confirmar.hasFocus())

        QTest.keyClick(dialogo.boton_confirmar, Qt.Key_Return)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        # Lo que queda en la caja, neto del vuelto.
        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 2100.0}])
        self.assertEqual(dialogo.vuelto, 2900.0)

    def test_una_parte_en_efectivo_completa_el_resto_digital_y_frena_para_revisar(self):
        # Así arranca también el cobro Mixto de PCs, PlayStation 5, socios y trámites.
        dialogo = self._abrir(2100.0)

        self._escribir(dialogo, "1000")
        self._enter(dialogo.spin_monto)

        self.assertTrue(dialogo.isVisible())
        self.assertEqual(dialogo.pagos, [
            {"metodo": _EFECTIVO, "monto": 1000.0},
            {"metodo": _DIGITAL, "monto": 1100.0},
        ])
        self.assertEqual(dialogo.spin_monto.value(), 0.0)

        QTest.keyClick(dialogo.boton_confirmar, Qt.Key_Return)

        self.assertEqual(dialogo.result(), QDialog.Accepted)

    def test_un_enter_apretado_no_cobra(self):
        dialogo = self._abrir(2100.0)

        self._enter(dialogo.spin_monto, repetido=True)

        self.assertTrue(dialogo.isVisible())
        self.assertEqual(dialogo.pagos, [])

    def test_un_enter_apretado_en_confirmar_no_confirma(self):
        dialogo = self._abrir(2100.0)
        self._escribir(dialogo, "5000")
        self._enter(dialogo.spin_monto)

        self.assertTrue(dialogo.boton_confirmar.hasFocus())

        self._enter(dialogo.boton_confirmar, repetido=True)
        self.assertTrue(dialogo.isVisible())

        self._enter(dialogo.boton_confirmar)
        self.assertEqual(dialogo.result(), QDialog.Accepted)

    def test_un_enter_de_mas_no_cobra_dos_veces(self):
        dialogo = self._abrir(2100.0)
        self._enter(dialogo.spin_monto)

        self._enter(dialogo.spin_monto)
        self._enter(dialogo.boton_confirmar)

        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 2100.0}])

    def test_al_quitar_un_pago_vuelve_a_proponer_lo_que_falta(self):
        dialogo = self._abrir(2100.0)
        self._escribir(dialogo, "1000")
        self._enter(dialogo.spin_monto)

        dialogo.tabla_pagos.setCurrentCell(1, 0)
        dialogo._quitar_pago()

        self.assertEqual(dialogo.spin_monto.value(), 1100.0)
        self.assertTrue(dialogo.spin_monto.lineEdit().hasSelectedText())

    def test_el_boton_agregar_pago_propone_lo_que_falta(self):
        dialogo = self._abrir(2100.0)
        self._escribir(dialogo, "600")

        dialogo._agregar_pago()

        self.assertEqual(dialogo.pagos, [{"metodo": _EFECTIVO, "monto": 600.0}])
        self.assertEqual(dialogo.spin_monto.value(), 1500.0)


class TestCobrar(unittest.TestCase):
    """`cobrar` abre el cuadro de verdad (modal): lo que haría la empleada se
    manda apenas aparece, desde el mismo bucle de eventos."""

    def _con_el_cuadro_abierto(self, accion):
        def hacer():
            QApplication.processEvents()  # que termine de mostrarse (deja el monto seleccionado)
            dialogo = QApplication.activeModalWidget()
            try:
                accion(dialogo)
            finally:
                # Si la prueba falla, que la ventana no quede abierta para siempre.
                if isinstance(dialogo, DialogoPago) and dialogo.isVisible():
                    dialogo.reject()
        QTimer.singleShot(0, hacer)

    def test_pago_justo_devuelve_los_pagos(self):
        self._con_el_cuadro_abierto(lambda dialogo: TestDialogoPago._enter(dialogo.spin_monto))

        pagos = cobrar(None, 4000.0)

        self.assertEqual(pagos, [{"metodo": _EFECTIVO, "monto": 4000.0}])

    def test_con_vuelto_devuelve_lo_que_queda_en_la_caja(self):
        def pagar_con_5000(dialogo):
            QTest.keyClicks(dialogo.spin_monto.lineEdit(), "5000")
            TestDialogoPago._enter(dialogo.spin_monto)  # frena en Confirmar por el vuelto
            self.assertEqual(dialogo.vuelto, 1000.0)
            dialogo.boton_confirmar.click()
        self._con_el_cuadro_abierto(pagar_con_5000)

        pagos = cobrar(None, 4000.0)

        self.assertEqual(pagos, [{"metodo": _EFECTIVO, "monto": 4000.0}])

    def test_cancelar_devuelve_none(self):
        self._con_el_cuadro_abierto(lambda dialogo: dialogo.reject())

        self.assertIsNone(cobrar(None, 4000.0))


if __name__ == "__main__":
    unittest.main()
