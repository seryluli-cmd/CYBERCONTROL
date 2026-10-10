"""
tests/test_cierre_turno_ui.py
===============================
La pantalla de Cierre de Turno es el resumen que las empleadas le mandan al dueño
(se prueba sin abrir ninguna ventana, plataforma "offscreen" de Qt): que muestre lo
vendido en Impresiones, que el cambio fijo se llame "Cambio Fijo" (nunca "fondo") y
que el aviso al cerrar también lo diga así. La cuenta de fondo está en
tests/test_kiosko.py (TestResumenDelDia).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import dominio  # noqa: E402
from repositories import articulos_repo, usuarios_repo, ventas_repo  # noqa: E402
from ui.caja_window import CierreTurnoWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestCierreDeTurnoEnPantalla(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.usuario_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", None, None, 150.0, 0.0, 0)
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)

    def _vender(self, codigo, descripcion, cantidad, precio):
        ventas_repo.confirmar_venta(
            self.usuario_id,
            [{"codigo": codigo, "descripcion": descripcion, "cantidad": cantidad, "precio_unitario": precio}],
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": cantidad * precio}],
        )

    def _abrir(self):
        ventana = CierreTurnoWindow(usuarios_repo.obtener_usuario(self.usuario_id))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_muestra_lo_vendido_en_impresiones_sin_sacarlo_de_kiosko(self):
        self._vender(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", 3, 150.0)  # $450
        self._vender("COD9", "Producto", 1, 10.0)

        ventana = self._abrir()

        self.assertEqual(ventana.valor_impresiones.text(), "$ 450,00")
        # Siguen dentro de Kiosko y del efectivo a retirar: no es un monto extra.
        self.assertIn("$ 460,00 ef.", ventana.valor_kiosko.text())
        self.assertEqual(ventana.valor_retirar.text(), "$ 460,00")

    def test_sin_impresiones_muestra_cero(self):
        self._vender("COD9", "Producto", 1, 10.0)

        self.assertEqual(self._abrir().valor_impresiones.text(), "$ 0,00")

    def test_el_cambio_fijo_no_se_llama_fondo_en_ningun_texto_de_la_pantalla(self):
        textos = [etiqueta.text() for etiqueta in self._abrir().findChildren(QLabel)]

        self.assertIn("Cambio Fijo", textos)
        self.assertFalse([t for t in textos if "fondo" in t.lower()], textos)

    def test_el_aviso_al_cerrar_habla_de_cambio_fijo(self):
        ventana = self._abrir()

        with mock.patch("ui.caja_window.confirmar", return_value=True), \
                mock.patch("ui.caja_window.mostrar_info") as mostrar_info:
            ventana._cerrar_turno()

        mensaje = mostrar_info.call_args.args[2]
        self.assertIn("de cambio fijo para el próximo turno", mensaje)
        self.assertNotIn("fondo", mensaje.lower())


if __name__ == "__main__":
    unittest.main()
