"""
tests/test_codigos_de_barras.py
=================================
Un código de barras se guarda y se encuentra ENTERO, con todos sus dígitos
(EAN-8, EAN-13 y los de 14 de las cajas), desde el alta hasta la venta.

Caso del dueño (2026-10-18): dio de alta Manaos con 7798113301024 y en la
lista de Artículos se veía "77981133010…", como si se hubiera guardado con
dos dígitos menos. Estaba guardado bien: la columna de 100 px cortaba el
texto con "...". Ahora la columna se ensancha hasta mostrarlo entero (se
prueba sin abrir ninguna ventana, plataforma "offscreen" de Qt).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from ui.articulos_window import ArticulosWindow, DialogoArticulo  # noqa: E402
from ui.buscar_articulo import DialogoBuscarArticulo  # noqa: E402
from ui.compras_window import ComprasWindow  # noqa: E402
from ui.ventas_window import VentasWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

MANAOS = "7798113301024"     # EAN-13, el del dueño
EAN_8 = "77981133"
CAJA_14 = "17798113301021"   # DUN-14, el de los bultos
CON_CERO = "0012345678905"   # los ceros de adelante también son parte del código
CODIGOS = (MANAOS, EAN_8, CAJA_14, CON_CERO)


class BaseCodigos(BaseConBaseTemporal):
    def _abrir(self, ventana):
        self.addCleanup(ventana.deleteLater)
        ventana.show()
        _app.processEvents()
        return ventana

    def _dar_de_alta_con_la_pistola(self, codigo):
        """Como la pistola en el alta: el código, Enter, y después el resto."""
        dialogo = self._abrir(DialogoArticulo(None))
        QTest.keyClicks(dialogo.campo_codigo, codigo)
        QTest.keyClick(dialogo.campo_codigo, Qt.Key_Return)
        # Sin acentos: QTest.keyClicks se cuelga con una "í" en la plataforma
        # "offscreen" (con un teclado de verdad no pasa).
        QTest.keyClicks(dialogo.campo_descripcion, f"Articulo {codigo}")
        dialogo.spin_precio_venta.setValue(1500)
        dialogo._guardar()

    def _cargar_todos(self):
        for codigo in CODIGOS:
            articulos_repo.crear_articulo(codigo, f"Artículo {codigo}", None, None, 1500.0, 900.0, 0)


class TestSeGuardaEntero(BaseCodigos):
    def test_el_alta_guarda_todos_los_digitos(self):
        for codigo in CODIGOS:
            with self.subTest(codigo=codigo):
                self._dar_de_alta_con_la_pistola(codigo)
                articulo = articulos_repo.buscar_por_codigo(codigo)
                self.assertIsNotNone(articulo)
                self.assertEqual(articulo["codigo"], codigo)

    def test_en_la_base_queda_como_texto_y_no_como_numero(self):
        # Como número, 0012345678905 perdería los ceros y uno de 14 cifras
        # podría redondearse: tiene que quedar tal cual se leyó.
        self._cargar_todos()
        with conexion_db() as conexion:
            filas = conexion.execute("SELECT codigo, typeof(codigo) AS tipo FROM articulos").fetchall()
        self.assertEqual(sorted(f["codigo"] for f in filas), sorted(CODIGOS))
        self.assertEqual({f["tipo"] for f in filas}, {"text"})


class TestSeEncuentra(BaseCodigos):
    def setUp(self):
        super().setUp()
        self._cargar_todos()
        self.usuario = usuarios_repo.obtener_usuario(
            usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))

    def test_buscar_por_codigo_f5_con_el_codigo_entero_o_una_parte(self):
        for texto, esperado in ((MANAOS, MANAOS), ("3301024", MANAOS), (EAN_8, EAN_8), (CAJA_14, CAJA_14)):
            with self.subTest(texto=texto):
                dialogo = self._abrir(DialogoBuscarArticulo(None, "codigo"))
                QTest.keyClicks(dialogo.campo_busqueda, texto)
                codigos = [dialogo.tabla.item(f, 0).text() for f in range(dialogo.tabla.rowCount())]
                self.assertIn(esperado, codigos)
                dialogo._elegir_seleccion()
                self.assertEqual(dialogo.codigo_elegido, esperado)

    def test_escanear_en_ventas(self):
        ventas = self._abrir(VentasWindow(self.usuario))
        for codigo in CODIGOS:
            QTest.keyClicks(ventas.campo_codigo, codigo)
            QTest.keyClick(ventas.campo_codigo, Qt.Key_Return)
        self.assertEqual([l["codigo"] for l in ventas.carrito], list(CODIGOS))
        self.assertEqual(ventas.tabla.item(0, 1).text(), MANAOS)

    def test_escanear_en_compras(self):
        compras = self._abrir(ComprasWindow(self.usuario))
        with mock.patch("ui.compras_window.QInputDialog.getInt", return_value=(6, True)), \
                mock.patch("ui.compras_window.QInputDialog.getDouble", return_value=(900.0, True)):
            for codigo in CODIGOS:
                QTest.keyClicks(compras.campo_codigo, codigo)
                QTest.keyClick(compras.campo_codigo, Qt.Key_Return)
        self.assertEqual([l["codigo"] for l in compras.lineas], list(CODIGOS))

    def test_si_no_lo_encuentra_dice_que_codigo_leyo_y_cuantos_digitos(self):
        # Para comparar con la lista de Artículos si la pistola lee distinto
        # de lo que se tipeó en el alta.
        ventas = self._abrir(VentasWindow(self.usuario))
        with mock.patch("ui.buscar_articulo.mostrar_error") as aviso:
            QTest.keyClicks(ventas.campo_codigo, "779811330102")
            QTest.keyClick(ventas.campo_codigo, Qt.Key_Return)
        aviso.assert_called_once()
        self.assertIn("779811330102 (12 dígitos)", aviso.call_args.args[2])
        self.assertEqual(ventas.carrito, [])


class TestLaColumnaMuestraElCodigoEntero(BaseCodigos):
    """Qt corta con "..." el texto que no entra en la columna."""

    def _assert_entra_entero(self, tabla, columna):
        self.assertGreater(tabla.rowCount(), 0)
        self.assertGreaterEqual(tabla.columnWidth(columna), tabla.sizeHintForColumn(columna))

    def test_lista_de_articulos(self):
        self._cargar_todos()
        ventana = self._abrir(ArticulosWindow())
        self._assert_entra_entero(ventana.tabla, 0)

    def test_carrito_de_ventas(self):
        self._cargar_todos()
        usuario = usuarios_repo.obtener_usuario(
            usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))
        ventas = self._abrir(VentasWindow(usuario))
        QTest.keyClicks(ventas.campo_codigo, CAJA_14)
        QTest.keyClick(ventas.campo_codigo, Qt.Key_Return)
        self._assert_entra_entero(ventas.tabla, 1)

    def test_cuadro_de_busqueda(self):
        self._cargar_todos()
        dialogo = self._abrir(DialogoBuscarArticulo(None, "codigo"))
        self._assert_entra_entero(dialogo.tabla, 0)


if __name__ == "__main__":
    unittest.main()
