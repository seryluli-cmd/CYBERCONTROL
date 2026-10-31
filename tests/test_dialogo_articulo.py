"""
tests/test_dialogo_articulo.py
================================
Modificar artículo con la maqueta B que eligió el dueño el 2026-10-31 (la misma
del kiosko): la cabecera con el artículo y su stock, los datos a la izquierda y la
tarjeta oscura del precio de venta con la calculadora COSTO + GANANCIA % = VENTA.
Las pantallas se prueban sin abrir ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QAbstractSpinBox, QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import articulos_repo  # noqa: E402
from ui.articulos_window import DialogoArticulo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestLasCuentas(unittest.TestCase):
    def test_margen_y_su_vuelta(self):
        self.assertEqual(dominio.precio_con_margen(1000, 80), 1800)
        self.assertEqual(dominio.costo_sin_margen(1800, 80), 1000)
        for costo in range(0, 20_001, 137):
            for porcentaje in range(0, 501, 5):
                precio = dominio.precio_con_margen(costo, porcentaje)
                self.assertEqual(dominio.costo_sin_margen(precio, porcentaje), costo, (costo, porcentaje))

    def test_la_ganancia(self):
        self.assertEqual(dominio.MARGEN_POR_DEFECTO, 80)
        self.assertEqual(dominio.porcentaje_de_ganancia(20, 200), 900)
        self.assertIsNone(dominio.porcentaje_de_ganancia(0, 200))
        self.assertEqual(dominio.ganancia_por_unidad(20, 200), 180)
        self.assertEqual(dominio.ganancia_por_unidad(300, 200), -100)

    def test_bajo_el_minimo_y_las_unidades(self):
        self.assertTrue(dominio.bajo_el_minimo(1, 2))
        self.assertFalse(dominio.bajo_el_minimo(2, 2))
        self.assertTrue(dominio.bajo_el_minimo(-1, 0))
        self.assertEqual(dominio.texto_cantidad(-13055), "-13.055")
        self.assertEqual(dominio.texto_cantidad(4), "4")


class TestCalculadora(BaseConBaseTemporal):
    def _dialogo(self, codigo=None):
        dialogo = DialogoArticulo(None, codigo)
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_la_venta_desde_el_costo_y_al_reves(self):
        dialogo = self._dialogo()
        self.assertEqual(dialogo.campo_porcentaje.text(), "80%")
        dialogo.spin_precio_compra.setValue(1000)
        dialogo.boton_calcular_venta.click()
        self.assertEqual(dialogo.spin_precio_venta.text(), "$ 1.800")
        dialogo.spin_precio_compra.setValue(0)
        dialogo.boton_calcular_costo.click()
        self.assertEqual(dialogo.spin_precio_compra.value(), 1000.0)

    def test_el_porcentaje_con_el_costo_y_la_venta(self):
        # El caso de Impresiones: cuesta $ 20 y se vende a $ 200.
        dialogo = self._dialogo()
        dialogo.spin_precio_compra.setValue(20)
        dialogo.spin_precio_venta.setValue(200)
        dialogo.boton_calcular_porcentaje.click()
        self.assertEqual(dialogo.campo_porcentaje.text(), "900%")
        self.assertEqual(dialogo.precio_grande.text(), "$ 200")
        self.assertEqual(dialogo.ayuda_de_precios.text(), "▲ Ganás $ 180 por unidad")

    def test_el_porcentaje_con_decimales_vuelve_a_dar_la_misma_venta(self):
        dialogo = self._dialogo()
        dialogo.spin_precio_compra.setValue(30)
        dialogo.spin_precio_venta.setValue(100)
        dialogo.boton_calcular_porcentaje.click()
        self.assertEqual(dialogo.campo_porcentaje.text(), "233,33%")
        dialogo.spin_precio_venta.setValue(0)
        dialogo.boton_calcular_venta.click()
        self.assertEqual(dialogo.spin_precio_venta.value(), 100.0)

    def test_sin_costo_o_vendiendo_por_debajo_avisa_y_no_toca_el_porcentaje(self):
        dialogo = self._dialogo()
        self.assertTrue(dialogo.ayuda_de_precios.property("apagada"))
        avisos = []
        with mock.patch("ui.dialogo_articulo.mostrar_aviso", lambda _p, _t, texto: avisos.append(texto)):
            dialogo.spin_precio_venta.setValue(200)
            dialogo.boton_calcular_porcentaje.click()
            dialogo.spin_precio_compra.setValue(300)
            dialogo.boton_calcular_porcentaje.click()
        self.assertEqual(avisos, ["Primero cargá el costo.",
                                  "El precio de venta es menor que el costo: con ese precio se pierde plata."])
        self.assertEqual(dialogo.campo_porcentaje.value(), 80)
        self.assertIn("Perdés $ 100 por unidad", dialogo.ayuda_de_precios.text())
        self.assertTrue(dialogo.ayuda_de_precios.property("alerta"))

    def test_los_campos_de_numeros_no_tienen_flechitas(self):
        dialogo = self._dialogo()
        for campo in (dialogo.spin_precio_compra, dialogo.campo_porcentaje,
                      dialogo.spin_precio_venta, dialogo.spin_stock_minimo):
            self.assertEqual(campo.buttonSymbols(), QAbstractSpinBox.NoButtons)
            self.assertTrue(campo.alignment() & Qt.AlignRight)


class TestCabecera(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        rubro = articulos_repo.crear_rubro("Bebidas Prueba")
        articulos_repo.crear_articulo("77", "Agua 500", None, rubro, 1000.0, 500.0, 2,
                                      nombre_marca_nueva="Villavicencio")

    def _con_stock(self, stock):
        with conexion_db() as conexion:
            conexion.execute("UPDATE articulos SET stock = ? WHERE codigo = '77'", (stock,))
        dialogo = DialogoArticulo(None, "77")
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_muestra_el_articulo_como_se_va_escribiendo(self):
        nuevo = DialogoArticulo(None)
        self.addCleanup(nuevo.deleteLater)
        self.assertEqual(nuevo.cabecera.titulo.text(), "Nuevo artículo")
        self.assertIsNone(nuevo.indicador_stock)
        nuevo.campo_descripcion.setText("Coca 500")
        self.assertEqual(nuevo.cabecera.titulo.text(), "Coca 500")

        dialogo = self._con_stock(0)
        self.assertEqual(dialogo.cabecera.titulo.text(), "Agua 500")
        self.assertEqual(dialogo.cabecera.detalle.text(), "Código 77  ·  Villavicencio  ·  Bebidas Prueba")
        self.assertEqual(dialogo.indicador_minimo.valor.text(), "2")

    def test_el_stock_en_rojo_solo_por_debajo_del_minimo(self):
        for stock, en_rojo in ((1, True), (2, False), (15000, False), (-1, True)):
            with self.subTest(stock=stock):
                dialogo = self._con_stock(stock)
                self.assertEqual(dialogo.indicador_stock.valor.text(), dominio.texto_cantidad(stock))
                self.assertEqual(bool(dialogo.indicador_stock.property("alerta")), en_rojo)


if __name__ == "__main__":
    unittest.main()
