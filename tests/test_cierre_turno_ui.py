"""
tests/test_cierre_turno_ui.py
===============================
La pantalla de Cierre de Turno es el resumen que las empleadas le mandan al dueño
(se prueba sin abrir ninguna ventana, plataforma "offscreen" de Qt): que muestre
Kiosko, Impresiones y Trámites separados (pedido del dueño, 2026-10-19), que el cambio fijo se llame "Cambio Fijo" (nunca "fondo") y
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
from ui.utils import formato_pesos  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _montos(renglon):
    """Lo que muestra un renglón de la tabla de dónde vino la plata: (efectivo, digital)."""
    return renglon.efectivo.text(), renglon.digital.text()


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

    def test_muestra_las_impresiones_aparte_de_kiosko(self):
        self._vender(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", 3, 150.0)  # $450
        self._vender("COD9", "Producto", 1, 10.0)

        ventana = self._abrir()

        self.assertEqual(_montos(ventana.tarjeta.renglon("impresiones")), ("$ 450", "$ 0"))
        self.assertEqual(_montos(ventana.tarjeta.renglon("kiosko_solo")), ("$ 10", "$ 0"))
        # El efectivo a retirar sigue siendo todo: separarlas es solo cómo se muestra.
        self.assertEqual(ventana.tarjeta.valor_retirar.text(), "$ 460")

    def test_muestra_efectivo_digital_y_total_sin_duplicar_las_impresiones(self):
        self._vender(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", 3, 150.0)  # $450 efectivo
        ventas_repo.confirmar_venta(
            self.usuario_id,
            [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": 10.0}],
            [{"metodo": dominio.PAGO_DIGITAL, "monto": 10.0}],
        )

        ventana = self._abrir()
        textos = [e.text() for e in ventana.findChildren(QLabel)]

        self.assertEqual(ventana.tarjeta.valor_efectivo.text(), "$ 450")
        self.assertEqual(ventana.tarjeta.valor_digital.text(), "$ 10")
        self.assertEqual(ventana.tarjeta.valor_total.text(), "$ 460")
        self.assertTrue({"Efectivo", "Digital", "TOTAL (EFECTIVO + DIGITAL)"} <= set(textos), textos)

    def test_muestra_los_tramites_sin_duplicarlos_en_el_total(self):
        from repositories import tramites_repo

        tramite_id = tramites_repo.crear_tramite("Sacar boleta de luz")
        tramites_repo.registrar_tramite(
            self.usuario_id, tramite_id, 2500.0, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 2500.0}]
        )
        self._vender("COD9", "Producto", 1, 10.0)

        ventana = self._abrir()

        self.assertEqual(_montos(ventana.tarjeta.renglon("tramites")), ("$ 2.500", "$ 0"))
        self.assertEqual(_montos(ventana.tarjeta.renglon("kiosko_solo")), ("$ 10", "$ 0"))
        self.assertEqual(ventana.tarjeta.valor_total.text(), "$ 2.510")      # cuenta una sola vez

    def test_sin_impresiones_muestra_cero(self):
        self._vender("COD9", "Producto", 1, 10.0)

        self.assertEqual(_montos(self._abrir().tarjeta.renglon("impresiones")), ("$ 0", "$ 0"))

    def test_el_cambio_fijo_no_se_llama_fondo_en_ningun_texto_de_la_pantalla(self):
        textos = [etiqueta.text() for etiqueta in self._abrir().findChildren(QLabel)]

        self.assertIn("Cambio Fijo", textos)
        self.assertFalse([t for t in textos if "fondo" in t.lower()], textos)

    def test_ninguna_otra_pantalla_llama_fondo_al_cambio_fijo(self):
        from PySide6.QtWidgets import QPushButton
        from ui.caja_window import CajaWindow, ControlCierresWindow
        from ui.usuarios_window import DialogoFondoCambio, UsuariosWindow

        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        caja = CajaWindow()
        control = ControlCierresWindow(admin)
        usuarios = UsuariosWindow(admin)
        dialogo = DialogoFondoCambio(None, 50000.0)
        for ventana in (caja, control, usuarios, dialogo):
            self.addCleanup(ventana.deleteLater)

        textos = []
        for ventana in (caja, usuarios, dialogo):
            textos += [e.text() for e in ventana.findChildren(QLabel)]
            textos += [b.text() for b in ventana.findChildren(QPushButton)]
        textos.append(dialogo.windowTitle())
        textos += [control.tabla.horizontalHeaderItem(c).text() for c in range(control.tabla.columnCount())]

        self.assertFalse([t for t in textos if "fondo" in t.lower()], textos)
        self.assertIn("Caja inicial (Cambio Fijo)", textos)
        self.assertIn("Configurar Cambio Fijo", textos)
        self.assertIn("Cambio Fijo", [control.tabla.horizontalHeaderItem(c).text() for c in range(control.tabla.columnCount())])

    def _cifra(self, ventana, titulo):
        """El recuadro de la cifra grande que tiene ese título (ui/piezas_ventana.cifra_destacada)."""
        etiqueta = next(e for e in ventana.findChildren(QLabel) if e.text() == titulo)
        return etiqueta.parentWidget()

    def test_a_retirar_en_efectivo_es_la_cifra_grande_verde(self):
        """Pedido del dueño (2026-10-20): es lo que se guarda en el sobre, tiene que
        resaltar. En verde, como la Caja Actual de la pantalla Caja."""
        ventana = self._abrir()

        cifra = self._cifra(ventana, "A RETIRAR EN EFECTIVO")

        self.assertEqual(cifra.objectName(), "cifraDestacada")
        self.assertEqual(cifra.property("tono"), "verde")
        self.assertIs(ventana.tarjeta.valor_retirar.parentWidget(), cifra)

    def test_el_total_dice_que_suma_y_es_la_cifra_grande_azul(self):
        ventana = self._abrir()

        cifra = self._cifra(ventana, "TOTAL (EFECTIVO + DIGITAL)")

        self.assertEqual(cifra.property("tono"), "azul")
        self.assertIs(ventana.tarjeta.valor_total.parentWidget(), cifra)

    def test_un_negocio_sin_ventas_se_ve_apagado(self):
        """Así salta a la vista de dónde vino la plata del turno."""
        self._vender("COD9", "Producto", 1, 10.0)

        tarjeta = self._abrir().tarjeta

        self.assertFalse(tarjeta.renglon("kiosko_solo").efectivo.property("vacio"))
        self.assertTrue(tarjeta.renglon("tramites").efectivo.property("vacio"))
        self.assertTrue(tarjeta.renglon("tramites").nombre.property("vacio"))

    def test_la_pantalla_caja_se_parece_al_cierre_y_la_caja_actual_no_suma_el_cambio(self):
        """Pedido del dueño (2026-10-20): Caja con los mismos renglones que el Cierre de Turno,
        TOTAL y CAJA ACTUAL, sin el cartel azul de "Suma Total". Desde el 2026-10-26 la Caja
        Actual es solo el efectivo cobrado: el cambio "que no esté sumado" (hasta ese día lo
        sumaba y decía "Incluye el cambio")."""
        from ui.caja_window import CajaWindow

        self._vender(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", 3, 150.0)  # $450 efectivo
        ventas_repo.confirmar_venta(
            self.usuario_id,
            [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": 10.0}],
            [{"metodo": dominio.PAGO_DIGITAL, "monto": 10.0}],
        )
        caja = CajaWindow()
        self.addCleanup(caja.deleteLater)
        textos = [e.text() for e in caja.findChildren(QLabel)]

        self.assertEqual(caja.valor_ventas.text(), "$ 450")
        self.assertEqual(caja.valor_digital.text(), "$ 10")
        self.assertEqual(caja.valor_total.text(), "$ 460")           # efectivo + digital, sin el cambio
        self.assertEqual(caja.valor_actual.text(), "$ 450")           # solo el efectivo cobrado, sin el cambio
        self.assertEqual(caja.valor_fondo.text(), formato_pesos(50000.0))   # el cambio, aparte
        for titulo in ("Caja inicial (Cambio Fijo)", "Efectivo", "Digital", "TOTAL (EFECTIVO + DIGITAL)",
                       "CAJA ACTUAL (solo efectivo)", "Sin el cambio: lo cobrado en efectivo"):
            self.assertIn(titulo, textos)
        self.assertFalse([t for t in textos if "Suma Total" in t or "Incluye el cambio" in t], textos)
        self.assertEqual(self._cifra(caja, "CAJA ACTUAL (solo efectivo)").property("tono"), "verde")

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
