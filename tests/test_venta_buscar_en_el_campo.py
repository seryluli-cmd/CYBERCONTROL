"""
tests/test_venta_buscar_en_el_campo.py
========================================
Venta de Mercadería tiene UN campo que sirve para todo, sin que el operador elija
nada (pedido del dueño, 2026-11-09): sin letras es un código de barras (la
pistola); con alguna letra busca por nombre O por marca, cada palabra en
cualquier orden, y lo encontrado se elige en una lista debajo del campo. Ya no
están los botones F5/F6/F7 (ver ui/venta_buscador.py).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import dominio  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from ui.buscar_articulo import DialogoBuscarArticulo  # noqa: E402
from ui.venta_buscador import AYUDA_DEL_CAMPO, es_para_buscar  # noqa: E402
from ui.ventas_dibujos import ROL_DETALLE  # noqa: E402
from ui.ventas_window import VentasWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

COCA = "7790895000997"
COCA_ZERO = "7790895001000"
JORGITO = "7790580000001"
AGUA = "7798062540017"
CON_LETRAS = "123A"


class TestUnSoloCampoSinElegir(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        articulos_repo.crear_articulo(COCA, "Coca Cola 500", None, None, 1500.0, 900.0, 0,
                                      nombre_marca_nueva="Coca-Cola")
        articulos_repo.crear_articulo(COCA_ZERO, "Coca Cola Zero 500", None, None, 1600.0, 950.0, 0,
                                      nombre_marca_nueva="Coca-Cola")
        articulos_repo.crear_articulo(JORGITO, "Alfajor Jorgito", None, None, 800.0, 400.0, 0,
                                      nombre_marca_nueva="Jorgito")
        # La marca no está en el nombre: solo se encuentra buscando también por marca.
        articulos_repo.crear_articulo(AGUA, "Agua sin gas 500", None, None, 900.0, 450.0, 0,
                                      nombre_marca_nueva="Villavicencio")
        articulos_repo.crear_articulo(CON_LETRAS, "Bolsa chica", None, None, 50.0, 20.0, 0)
        usuario = usuarios_repo.obtener_usuario(
            usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))
        self.ventas = VentasWindow(usuario)
        self.addCleanup(self.ventas.deleteLater)
        self.ventas.show()
        _app.processEvents()
        self.campo = self.ventas.campo_codigo
        self.lista = self.ventas.buscador

    def _escribir(self, texto):
        QTest.keyClicks(self.campo, texto)

    def _en_la_lista(self):
        return [self.lista.item(fila, 0).text() for fila in range(self.lista.rowCount())]

    def _carrito(self):
        return [(linea["codigo"], linea["cantidad"]) for linea in self.ventas.carrito]

    def test_que_es_para_buscar(self):
        self.assertFalse(es_para_buscar(COCA))
        self.assertFalse(es_para_buscar(""))
        self.assertTrue(es_para_buscar("coca"))
        self.assertTrue(es_para_buscar("7up"))
        self.assertTrue(es_para_buscar(CON_LETRAS))

    def test_arranca_lista_para_la_pistola_y_sin_botones_para_elegir(self):
        self.assertEqual(self.campo.placeholderText(), AYUDA_DEL_CAMPO)
        self.assertFalse(self.lista.isVisible())
        textos = {boton.text() for boton in self.ventas.findChildren(QPushButton)}
        self.assertTrue({"Cantidad", "Quitar"} <= textos)
        self.assertFalse({"Código", "Descripción", "Marca"} & textos)
        self.assertFalse(hasattr(self.lista, "botones"))

    def test_una_letra_abre_la_lista_y_enter_agrega_el_primero(self):
        with mock.patch.object(DialogoBuscarArticulo, "exec") as cuadro_aparte:
            self._escribir("coca")
        cuadro_aparte.assert_not_called()
        self.assertTrue(self.lista.isVisible())
        self.assertEqual(self._en_la_lista(), ["Coca Cola 500", "Coca Cola Zero 500"])
        # Debajo, chiquito, el código y la marca; a la derecha, el precio.
        self.assertEqual(self.lista.item(0, 0).data(ROL_DETALLE), f"{COCA}  ·  Coca-Cola")
        self.assertEqual(self.lista.item(0, 1).text(), "$ 1.500")
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual(self._carrito(), [(COCA, 1)])
        self.assertEqual(self.campo.text(), "")
        self.assertFalse(self.lista.isVisible())

    def test_busca_tambien_por_marca_sin_apretar_nada(self):
        self._escribir("villa")
        self.assertEqual(self._en_la_lista(), ["Agua sin gas 500"])
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual(self._carrito(), [(AGUA, 1)])

    def test_las_palabras_van_en_cualquier_orden_y_mezclan_nombre_y_marca(self):
        self._escribir("zero coca")
        self.assertEqual(self._en_la_lista(), ["Coca Cola Zero 500"])
        self.campo.clear()
        self._escribir("villavicencio agua")
        self.assertEqual(self._en_la_lista(), ["Agua sin gas 500"])
        self.campo.clear()
        self._escribir("500  coca")   # dos espacios: da lo mismo
        self.assertEqual(self._en_la_lista(), ["Coca Cola 500", "Coca Cola Zero 500"])
        self.campo.clear()
        self._escribir("cola alfajor")   # tienen que estar TODAS las palabras
        self.assertEqual(self._en_la_lista(), ["No hay ningún producto que diga “cola alfajor”"])

    def test_las_flechas_eligen_otro_de_la_lista(self):
        self._escribir("coca")
        QTest.keyClick(self.campo, Qt.Key_Up)      # ya está en el primero: no se va
        self.assertEqual(self.lista.currentRow(), 0)
        QTest.keyClick(self.campo, Qt.Key_Down)
        QTest.keyClick(self.campo, Qt.Key_Down)    # no hay tercero: se queda en el último
        self.assertEqual(self.lista.currentRow(), 1)
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual(self._carrito(), [(COCA_ZERO, 1)])

    def test_un_clic_en_la_lista_lo_agrega(self):
        self._escribir("coca")
        renglon = self.lista.visualItemRect(self.lista.item(1, 0)).center()
        QTest.mouseClick(self.lista.viewport(), Qt.LeftButton, pos=renglon)
        self.assertEqual(self._carrito(), [(COCA_ZERO, 1)])
        self.assertEqual(self.campo.text(), "")
        self.assertFalse(self.lista.isVisible())

    def test_sin_nada_que_coincida_lo_dice_la_lista_y_enter_no_agrega_ni_cobra(self):
        self._escribir(JORGITO)
        QTest.keyClick(self.campo, Qt.Key_Return)
        self._escribir("zzz")
        self.assertEqual(self._en_la_lista(), ["No hay ningún producto que diga “zzz”"])
        with mock.patch.object(self.ventas, "_ir_a_cobrar") as cobrar:
            QTest.keyClick(self.campo, Qt.Key_Return)
        cobrar.assert_not_called()
        self.assertEqual(self._carrito(), [(JORGITO, 1)])
        self.assertEqual(self.campo.text(), "zzz")   # queda para corregirlo

    def test_despues_de_buscar_por_nombre_la_pistola_entra_como_codigo(self):
        self._escribir("jorg")
        self.assertEqual(self._en_la_lista(), ["Alfajor Jorgito"])
        QTest.keyClick(self.campo, Qt.Key_Return)
        self._escribir(COCA)
        self.assertFalse(self.lista.isVisible())
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual(self._carrito(), [(JORGITO, 1), (COCA, 1)])

    def test_borrar_las_letras_cierra_la_lista(self):
        self._escribir("500 coca")
        self.assertTrue(self.lista.isVisible())
        for _ in "coca":
            QTest.keyClick(self.campo, Qt.Key_Backspace)
        self.assertEqual(self.campo.text(), "500 ")
        self.assertFalse(self.lista.isVisible())

    def test_un_codigo_con_letras_entra_igual(self):
        self._escribir(CON_LETRAS)
        self.assertEqual(self._en_la_lista(), [f"No hay ningún producto que diga “{CON_LETRAS}”"])
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual(self._carrito(), [(CON_LETRAS, 1)])

    def test_un_codigo_que_no_existe_se_avisa_como_siempre(self):
        with mock.patch("ui.buscar_articulo.mostrar_error") as aviso:
            self._escribir("12345")
            QTest.keyClick(self.campo, Qt.Key_Return)
        aviso.assert_called_once()
        self.assertEqual(self._carrito(), [])

    def test_la_cantidad_del_asterisco_vale_tambien(self):
        with mock.patch("ui.ventas_window.QInputDialog.getInt", return_value=(3, True)):
            self.ventas._cambiar_cantidad_pendiente()
        self._escribir("jorg")
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual(self._carrito(), [(JORGITO, 3)])

    def test_esc_borra_lo_escrito_sin_cerrar_la_venta(self):
        for texto in ("coca", COCA):
            with self.subTest(texto):
                self._escribir(texto)
                QTest.keyClick(self.campo, Qt.Key_Escape)
                self.assertEqual(self.campo.text(), "")
                self.assertFalse(self.lista.isVisible())
                self.assertTrue(self.ventas.isVisible())

    def test_las_teclas_f5_f6_f7_ya_no_cambian_nada(self):
        for tecla in (Qt.Key_F5, Qt.Key_F6, Qt.Key_F7):
            QTest.keyClick(self.campo, tecla)
        self._escribir("villa")
        self.assertEqual(self._en_la_lista(), ["Agua sin gas 500"])


class TestVenderLePideCienALaBase(BaseConBaseTemporal):
    """Con más de 100 coincidencias, Vender le pide a la base solo las 100 que muestra
    (LIMIT en SQL, en vez de traerlas todas y recortar), en el mismo orden de siempre.
    Las demás llamadas (Compras, otra PC) siguen trayendo todas."""

    CUANTOS = 130
    TOPE = 100

    def setUp(self):
        super().setUp()
        # Los códigos no siguen el orden de las descripciones, y de a dos se repite la
        # descripción: con tope tienen que salir los mismos primeros, empates incluidos.
        for numero in range(self.CUANTOS):
            articulos_repo.crear_articulo(
                str(9000000000000 + numero * 37 % self.CUANTOS), f"Galletita {self.CUANTOS - numero // 2:03d}",
                None, None, 1000.0, 500.0, 0, nombre_marca_nueva="Bagley")
        usuario = usuarios_repo.obtener_usuario(
            usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))
        self.ventas = VentasWindow(usuario)
        self.addCleanup(self.ventas.deleteLater)
        self.ventas.show()
        _app.processEvents()
        self.campo = self.ventas.campo_codigo
        self.lista = self.ventas.buscador

    @staticmethod
    def _codigos(articulos):
        return [articulo["codigo"] for articulo in articulos]

    def test_con_tope_salen_los_primeros_del_mismo_orden_y_sin_tope_todos(self):
        buscar = articulos_repo.buscar_para_vender
        for texto in ("galletita", "bagley", "bagley galletita"):
            with self.subTest(texto):
                todos = buscar(texto)
                self.assertEqual(len(todos), self.CUANTOS)
                self.assertEqual(self._codigos(buscar(texto, limite=self.TOPE)), self._codigos(todos[:self.TOPE]))

    def _buscar_en_vender(self, texto):
        """Tipea `texto` en Vender y devuelve, por cada letra, qué tope pidió y cuántos
        artículos le dio la base. (Sin assert adentro: `_buscar` atrapa los errores
        con un cartel.)"""
        original = articulos_repo.buscar_para_vender
        traidos = []

        def contar(*args, **kwargs):
            filas = original(*args, **kwargs)
            traidos.append((kwargs.get("limite"), len(filas)))
            return filas

        with mock.patch.object(articulos_repo, "buscar_para_vender", side_effect=contar):
            QTest.keyClicks(self.campo, texto)
        return traidos

    def test_la_base_da_cien_y_se_elige_igual(self):
        esperados = self._codigos(articulos_repo.buscar_para_vender("galletita")[:self.TOPE])
        traidos = self._buscar_en_vender("galletita")
        self.assertEqual(set(traidos), {(self.TOPE, self.TOPE)})
        self.assertEqual(self.lista.rowCount(), self.TOPE)
        self.assertEqual(self._codigos(self.lista._resultados), esperados)
        # Con las flechas se llega hasta el último de los 100, y Enter lo agrega.
        QTest.keyClick(self.campo, Qt.Key_PageDown)
        for _ in range(self.TOPE):
            QTest.keyClick(self.campo, Qt.Key_Down)
        self.assertEqual(self.lista.currentRow(), self.TOPE - 1)
        QTest.keyClick(self.campo, Qt.Key_Return)
        self.assertEqual([linea["codigo"] for linea in self.ventas.carrito], [esperados[-1]])

    def test_por_la_marca_tambien_da_cien(self):
        esperados = self._codigos(articulos_repo.buscar_por_marca("bagley")[:self.TOPE])
        traidos = self._buscar_en_vender("bagley")
        self.assertEqual(set(traidos), {(self.TOPE, self.TOPE)})
        self.assertEqual(self._codigos(self.lista._resultados), esperados)


if __name__ == "__main__":
    unittest.main()
