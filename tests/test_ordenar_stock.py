"""
tests/test_ordenar_stock.py
=============================
ORDENAR Stock (botón de Artículos; pedido del dueño, 2026-10-20): un Admin con
la contraseña de ORDENAR Stock corrige el stock de cualquier artículo sin tocar
precios, costos ni plata, y cada cambio queda en los Movimientos del artículo.

La contraseña real no se escribe acá (el repo es público): cada prueba usa una
de prueba en lugar de la del dueño. Las pantallas se prueban sin abrir ninguna
ventana (plataforma "offscreen" de Qt).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import sqlite3
import unittest
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QAbstractItemView, QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import articulos_repo, compras_repo, usuarios_repo, ventas_repo  # noqa: E402
from ui.articulos_tabla import COLUMNA_CODIGO, COLUMNA_STOCK  # noqa: E402
from ui.articulos_window import ArticulosWindow  # noqa: E402
from ui.ordenar_stock_window import OrdenarStockWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

CLAVE = "clave-de-prueba"


class BaseOrdenarStock(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        parche = mock.patch.object(articulos_repo, "CLAVE_ORDENAR_STOCK", database.hash_clave(CLAVE))
        parche.start()
        self.addCleanup(parche.stop)
        self.admin_id = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.empleada_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 2)
        articulos_repo.crear_articulo("AGUA", "Agua 500", None, None, 800.0, 400.0, 0)
        articulos_repo.crear_articulo("ALFA", "Alfajor", None, None, 600.0, 300.0, 5)

    def _stock(self, codigo):
        return articulos_repo.buscar_por_codigo(codigo)["stock"]

    def _ajustes(self):
        with conexion_db() as conexion:
            return conexion.execute("SELECT * FROM ajustes_stock ORDER BY id").fetchall()


class TestAjustarStock(BaseOrdenarStock):
    def test_cambia_solo_el_stock_y_lo_deja_anotado(self):
        resultado = articulos_repo.ajustar_stock(self.admin_id, "COCA", 7, CLAVE)

        self.assertEqual(resultado, {"stock_anterior": 0, "stock_nuevo": 7})
        articulo = articulos_repo.buscar_por_codigo("COCA")
        self.assertEqual(articulo["stock"], 7)
        self.assertEqual((articulo["precio_venta"], articulo["precio_compra"], articulo["stock_minimo"]),
                         (1000.0, 500.0, 2))
        [ajuste] = self._ajustes()
        self.assertEqual((ajuste["articulo_codigo"], ajuste["stock_anterior"], ajuste["stock_nuevo"],
                          ajuste["usuario_id"]), ("COCA", 0, 7, self.admin_id))

    def test_no_mueve_plata_ni_inventa_compras(self):
        articulos_repo.ajustar_stock(self.admin_id, "COCA", 40, CLAVE)
        with conexion_db() as conexion:
            for tabla in ("ventas", "venta_pagos", "compras", "compra_detalle"):
                with self.subTest(tabla=tabla):
                    self.assertEqual(conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"], 0)

    def test_lo_de_antes_es_lo_que_dice_la_base(self):
        # Si se vendió algo mientras la grilla estaba abierta, lo anotado como
        # "antes" es el stock real de ese momento, no el que se veía en pantalla.
        with conexion_db() as conexion:
            conexion.execute("UPDATE articulos SET stock = -3 WHERE codigo = 'COCA'")
        resultado = articulos_repo.ajustar_stock(self.admin_id, "COCA", 4, CLAVE)
        self.assertEqual(resultado["stock_anterior"], -3)
        self.assertEqual(self._ajustes()[0]["stock_anterior"], -3)

    def test_aparece_en_movimientos_con_lo_que_sumo_o_resto(self):
        articulos_repo.ajustar_stock(self.admin_id, "COCA", 7, CLAVE)
        articulos_repo.ajustar_stock(self.admin_id, "COCA", 4, CLAVE)
        hoy = date.today().isoformat()
        movimientos = articulos_repo.obtener_movimientos("COCA", hoy, hoy)
        self.assertEqual([(m["comprobante"], m["cantidad"]) for m in movimientos],
                         [("ajuste de stock", 7), ("ajuste de stock", -3)])

    def test_el_mismo_numero_no_anota_nada(self):
        articulos_repo.ajustar_stock(self.admin_id, "COCA", 7, CLAVE)
        resultado = articulos_repo.ajustar_stock(self.admin_id, "COCA", "7", CLAVE)
        self.assertEqual(resultado, {"stock_anterior": 7, "stock_nuevo": 7})
        self.assertEqual(len(self._ajustes()), 1)

    def test_acepta_el_numero_escrito_como_texto(self):
        articulos_repo.ajustar_stock(self.admin_id, "COCA", " 12 ", CLAVE)
        self.assertEqual(self._stock("COCA"), 12)

    def test_cantidades_que_no_son_un_entero_de_0_para_arriba(self):
        for valor in ("-1", -1, "2,5", 2.5, "abc", "", "  ", None, True, "²"):
            with self.subTest(valor=valor):
                with self.assertRaises(ValueError):
                    articulos_repo.ajustar_stock(self.admin_id, "COCA", valor, CLAVE)
        self.assertEqual(self._stock("COCA"), 0)
        self.assertEqual(self._ajustes(), [])

    def test_contrasena_incorrecta(self):
        for clave in ("otra", "", None, CLAVE.upper()):
            with self.subTest(clave=clave):
                with self.assertRaises(PermissionError):
                    articulos_repo.ajustar_stock(self.admin_id, "COCA", 7, clave)
        self.assertEqual(self._stock("COCA"), 0)
        self.assertEqual(self._ajustes(), [])

    def test_una_empleada_no_puede_aunque_sepa_la_contrasena(self):
        with self.assertRaises(PermissionError):
            articulos_repo.comprobar_clave_para_ordenar_stock(self.empleada_id, CLAVE)
        with self.assertRaises(PermissionError):
            articulos_repo.ajustar_stock(self.empleada_id, "COCA", 7, CLAVE)
        self.assertEqual(self._stock("COCA"), 0)

    def test_un_admin_dado_de_baja_no_puede_seguir(self):
        articulos_repo.comprobar_clave_para_ordenar_stock(self.admin_id, CLAVE)
        otro_admin = usuarios_repo.crear_usuario("Otro", "1234", dominio.ROL_ADMIN)
        usuarios_repo.desactivar_usuario(otro_admin)
        with self.assertRaises(PermissionError):
            articulos_repo.ajustar_stock(otro_admin, "COCA", 7, CLAVE)

    def test_articulo_que_no_existe(self):
        with self.assertRaises(ValueError):
            articulos_repo.ajustar_stock(self.admin_id, "NO-EXISTE", 7, CLAVE)
        self.assertEqual(self._ajustes(), [])

    def test_un_articulo_con_ajustes_no_se_puede_borrar(self):
        # Como uno con compras o ventas: se perdería el rastro de lo que se corrigió.
        articulos_repo.ajustar_stock(self.admin_id, "AGUA", 3, CLAVE)
        with self.assertRaises(ValueError):
            articulos_repo.borrar_articulo("AGUA")
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("AGUA"))
        articulos_repo.borrar_articulo("ALFA")  # sin nada anotado, sí
        self.assertIsNone(articulos_repo.buscar_por_codigo("ALFA"))


class TestCambiarCodigo(BaseOrdenarStock):
    """Un código escrito mal a mano en vez de leído con la pistola (pedido del dueño,
    2026-10-20): ORDENAR Stock lo corrige y el historial del artículo lo sigue."""

    NUEVO = "7790580001234"

    def _con_historial(self):
        # Una compra, una venta y un ajuste del Alfajor, cargado con el código "ALFA".
        compras_repo.registrar_compra(self.admin_id, [{"codigo": "ALFA", "cantidad": 10, "costo_unitario": 300.0}])
        ventas_repo.confirmar_venta(
            self.admin_id,
            [{"codigo": "ALFA", "descripcion": "Alfajor", "cantidad": 2, "precio_unitario": 600.0}],
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1200.0}],
        )
        articulos_repo.ajustar_stock(self.admin_id, "ALFA", 9, CLAVE)

    def _cuantos(self, tabla, codigo):
        with conexion_db() as conexion:
            return conexion.execute(
                f"SELECT COUNT(*) AS n FROM {tabla} WHERE articulo_codigo = ?", (codigo,)
            ).fetchone()["n"]

    def _cambios(self):
        with conexion_db() as conexion:
            return conexion.execute("SELECT * FROM cambios_codigo ORDER BY id").fetchall()

    def test_cambia_el_codigo_y_sus_ventas_compras_y_ajustes_lo_siguen(self):
        self._con_historial()

        resultado = articulos_repo.cambiar_codigo(self.admin_id, "ALFA", self.NUEVO, CLAVE)

        self.assertEqual(resultado, {"codigo_anterior": "ALFA", "codigo_nuevo": self.NUEVO})
        self.assertIsNone(articulos_repo.buscar_por_codigo("ALFA"))
        articulo = articulos_repo.buscar_por_codigo(self.NUEVO)
        self.assertEqual((articulo["descripcion"], articulo["precio_venta"], articulo["stock"]), ("Alfajor", 600.0, 9))
        for tabla in ("venta_detalle", "compra_detalle", "ajustes_stock"):
            with self.subTest(tabla=tabla):
                self.assertEqual((self._cuantos(tabla, "ALFA"), self._cuantos(tabla, self.NUEVO)), (0, 1))
        with conexion_db() as conexion:
            self.assertEqual(conexion.execute("PRAGMA foreign_key_check").fetchall(), [])

    def test_queda_anotado_y_se_ve_en_movimientos(self):
        self._con_historial()
        articulos_repo.cambiar_codigo(self.admin_id, "ALFA", self.NUEVO, CLAVE)

        [cambio] = self._cambios()
        self.assertEqual(
            (cambio["articulo_codigo"], cambio["codigo_anterior"], cambio["codigo_nuevo"], cambio["usuario_id"]),
            (self.NUEVO, "ALFA", self.NUEVO, self.admin_id),
        )
        hoy = date.today().isoformat()
        movimientos = articulos_repo.obtener_movimientos(self.NUEVO, hoy, hoy)
        self.assertCountEqual(
            [(m["comprobante"], m["cantidad"]) for m in movimientos],
            [("compras", 10), ("ventas", -2), ("ajuste de stock", 1),
             (f"cambio de código ALFA → {self.NUEVO}", 0)],
        )

    def test_corregido_dos_veces_se_ven_los_dos_cambios(self):
        articulos_repo.cambiar_codigo(self.admin_id, "ALFA", "779", CLAVE)
        articulos_repo.cambiar_codigo(self.admin_id, "779", self.NUEVO, CLAVE)
        hoy = date.today().isoformat()
        movimientos = articulos_repo.obtener_movimientos(self.NUEVO, hoy, hoy)
        self.assertEqual([m["comprobante"] for m in movimientos],
                         ["cambio de código ALFA → 779", f"cambio de código 779 → {self.NUEVO}"])

    def test_no_se_puede_usar_el_codigo_de_otro_articulo(self):
        with self.assertRaises(ValueError) as error:
            articulos_repo.cambiar_codigo(self.admin_id, "ALFA", "COCA", CLAVE)
        self.assertIn("Coca 500", str(error.exception))
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("ALFA"))
        self.assertEqual(self._cambios(), [])

    def test_vacio_no_y_el_mismo_codigo_no_anota_nada(self):
        for vacio in ("", "   ", None):
            with self.subTest(codigo=vacio):
                with self.assertRaises(ValueError):
                    articulos_repo.cambiar_codigo(self.admin_id, "ALFA", vacio, CLAVE)
        resultado = articulos_repo.cambiar_codigo(self.admin_id, "ALFA", " ALFA ", CLAVE)
        self.assertEqual(resultado, {"codigo_anterior": "ALFA", "codigo_nuevo": "ALFA"})
        self.assertEqual(self._cambios(), [])

    def test_saca_los_espacios_de_los_costados(self):
        articulos_repo.cambiar_codigo(self.admin_id, "ALFA", f"  {self.NUEVO} ", CLAVE)
        self.assertIsNotNone(articulos_repo.buscar_por_codigo(self.NUEVO))

    def test_el_codigo_de_impresiones_no_se_cambia_ni_se_le_pone_a_otro(self):
        impresiones = dominio.CODIGO_ARTICULO_IMPRESIONES
        with self.assertRaises(ValueError):
            articulos_repo.cambiar_codigo(self.admin_id, "ALFA", impresiones, CLAVE)
        articulos_repo.crear_articulo(impresiones, "IMPRESIONES", None, None, 150.0, 0.0, 0)
        with self.assertRaises(ValueError):
            articulos_repo.cambiar_codigo(self.admin_id, impresiones, "44", CLAVE)
        self.assertIsNotNone(articulos_repo.buscar_por_codigo(impresiones))
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("ALFA"))

    def test_pide_admin_y_la_contrasena(self):
        for usuario_id, clave in ((self.admin_id, "otra"), (self.admin_id, None), (self.empleada_id, CLAVE)):
            with self.subTest(usuario_id=usuario_id, clave=clave):
                with self.assertRaises(PermissionError):
                    articulos_repo.cambiar_codigo(usuario_id, "ALFA", self.NUEVO, clave)
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("ALFA"))

    def test_articulo_que_no_existe(self):
        with self.assertRaises(ValueError):
            articulos_repo.cambiar_codigo(self.admin_id, "NO-EXISTE", self.NUEVO, CLAVE)
        self.assertEqual(self._cambios(), [])

    def test_corrige_todas_las_tablas_que_apuntan_a_un_articulo(self):
        # Si mañana una tabla nueva guarda el código de un artículo, cambiar_codigo
        # tiene que corregirla también: si no, el cambio fallaría al guardar.
        with conexion_db() as conexion:
            tablas = [fila["name"] for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")]
            apuntan = {
                tabla for tabla in tablas
                for clave_foranea in conexion.execute(f"PRAGMA foreign_key_list({tabla})")
                if clave_foranea["table"] == "articulos"
            }
        self.assertEqual(apuntan, set(articulos_repo._TABLAS_CON_CODIGO_DE_ARTICULO))

    def test_si_se_olvida_una_tabla_no_queda_nada_a_medias(self):
        self._con_historial()
        sin_ventas = tuple(t for t in articulos_repo._TABLAS_CON_CODIGO_DE_ARTICULO if t != "venta_detalle")
        with mock.patch.object(articulos_repo, "_TABLAS_CON_CODIGO_DE_ARTICULO", sin_ventas):
            with self.assertRaises(sqlite3.IntegrityError):
                articulos_repo.cambiar_codigo(self.admin_id, "ALFA", self.NUEVO, CLAVE)
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("ALFA"))
        self.assertEqual((self._cuantos("compra_detalle", "ALFA"), self._cambios()), (1, []))


class BasePantallas(BaseOrdenarStock):
    def _abrir(self, ventana):
        self.addCleanup(ventana.deleteLater)
        ventana.show()
        _app.processEvents()
        return ventana


class TestBotonEnArticulos(BasePantallas):
    def test_solo_lo_ve_un_admin(self):
        admin = usuarios_repo.obtener_usuario(self.admin_id)
        empleada = usuarios_repo.obtener_usuario(self.empleada_id)
        for usuario, lo_ve in ((admin, True), (empleada, False), (None, False)):
            with self.subTest(usuario=usuario and usuario["nombre"]):
                ventana = self._abrir(ArticulosWindow(None, usuario))
                self.assertEqual(ventana.boton_ordenar_stock.isVisible(), lo_ve)
                self.assertEqual(ventana.boton_ordenar_stock.text(), "ORDENAR Stock")

    def _apretar_con(self, respuesta):
        ventana = self._abrir(ArticulosWindow(None, usuarios_repo.obtener_usuario(self.admin_id)))
        with mock.patch("ui.articulos_window.QInputDialog.getText", return_value=respuesta), \
                mock.patch("ui.articulos_window.OrdenarStockWindow") as pantalla, \
                mock.patch("ui.utils.mostrar_error") as error:
            ventana.boton_ordenar_stock.click()
        return pantalla, error

    def test_con_la_contrasena_abre_la_pantalla(self):
        pantalla, error = self._apretar_con((CLAVE, True))
        pantalla.assert_called_once()
        self.assertEqual(pantalla.call_args.args[1:], (self.admin_id, CLAVE))
        error.assert_not_called()

    def test_con_otra_contrasena_no_abre_y_avisa(self):
        pantalla, error = self._apretar_con(("mala", True))
        pantalla.assert_not_called()
        error.assert_called_once()

    def test_cancelar_no_abre_nada(self):
        pantalla, error = self._apretar_con((CLAVE, False))
        pantalla.assert_not_called()
        error.assert_not_called()


class TestPantallaOrdenarStock(BasePantallas):
    def setUp(self):
        super().setUp()
        self.ventana = self._abrir(OrdenarStockWindow(None, self.admin_id, CLAVE))
        self.tabla = self.ventana.tabla

    def _fila(self, codigo):
        for fila in range(self.tabla.rowCount()):
            if self.tabla.item(fila, COLUMNA_CODIGO).text() == codigo:
                return fila
        self.fail(f"{codigo} no está en la grilla")

    def _celda_stock(self, codigo):
        return self.tabla.item(self._fila(codigo), COLUMNA_STOCK)

    def test_muestra_todos_los_articulos(self):
        self.assertEqual(self.tabla.rowCount(), 3)

    def test_solo_se_puede_escribir_el_stock_y_el_codigo(self):
        for fila in range(self.tabla.rowCount()):
            for columna in range(self.tabla.columnCount()):
                editable = bool(self.tabla.item(fila, columna).flags() & Qt.ItemIsEditable)
                with self.subTest(fila=fila, columna=columna):
                    self.assertEqual(editable, columna in (COLUMNA_STOCK, COLUMNA_CODIGO))

    def test_en_articulos_el_codigo_no_se_escribe(self):
        ventana = self._abrir(ArticulosWindow(None, usuarios_repo.obtener_usuario(self.admin_id)))
        tabla = ventana.tabla
        for fila in range(tabla.rowCount()):
            self.assertFalse(tabla.item(fila, COLUMNA_CODIGO).flags() & Qt.ItemIsEditable)

    def _escribir_codigo(self, codigo, nuevo, confirma=True):
        """Escribe `nuevo` en la celda del código de `codigo`, contestando la pregunta."""
        with mock.patch("ui.ordenar_stock_window.confirmar", return_value=confirma) as pregunta, \
                mock.patch("ui.ordenar_stock_window.mostrar_error") as error:
            self.tabla.item(self._fila(codigo), COLUMNA_CODIGO).setText(nuevo)
            _app.processEvents()
        return pregunta, error

    def test_escribir_el_codigo_pregunta_y_lo_cambia(self):
        pregunta, error = self._escribir_codigo("ALFA", "7790580001234")

        pregunta.assert_called_once()
        self.assertIn("7790580001234", pregunta.call_args.args[2])
        error.assert_not_called()
        self.assertIsNone(articulos_repo.buscar_por_codigo("ALFA"))
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("7790580001234"))
        self.assertEqual(self.tabla.item(self._fila("7790580001234"), COLUMNA_CODIGO).data(Qt.UserRole),
                         "7790580001234")
        self.assertIn("ALFA → 7790580001234", self.ventana.etiqueta_estado.text())

    def test_si_no_confirma_queda_el_codigo_de_antes(self):
        self._escribir_codigo("ALFA", "7790580001234", confirma=False)
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("ALFA"))
        self.assertEqual(self.tabla.item(self._fila("ALFA"), COLUMNA_CODIGO).text(), "ALFA")

    def test_el_codigo_de_otro_articulo_avisa_y_vuelve_atras(self):
        _pregunta, error = self._escribir_codigo("ALFA", "COCA")
        error.assert_called_once()
        self.assertEqual(self.tabla.item(self._fila("ALFA"), COLUMNA_CODIGO).text(), "ALFA")
        self.assertEqual(articulos_repo.buscar_por_codigo("COCA")["descripcion"], "Coca 500")

    def test_borrar_el_codigo_y_enter_es_cancelar(self):
        pregunta, error = self._escribir_codigo("ALFA", "   ")
        pregunta.assert_not_called()
        error.assert_not_called()
        self.assertEqual(self.tabla.item(self._fila("ALFA"), COLUMNA_CODIGO).text(), "ALFA")

    def test_con_el_codigo_cambiado_el_stock_se_sigue_guardando(self):
        self._escribir_codigo("ALFA", "7790580001234")
        self.tabla.item(self._fila("7790580001234"), COLUMNA_STOCK).setText("6")
        _app.processEvents()
        self.assertEqual(self._stock("7790580001234"), 6)

    def test_doble_clic_abre_el_codigo_y_al_cerrarlo_vuelve_al_stock(self):
        # Un clic sigue yendo al stock (test de abajo): el código se abre solo con
        # doble clic, así no se cambia sin querer.
        fila = self._fila("ALFA")
        centro = self.tabla.visualItemRect(self.tabla.item(fila, COLUMNA_CODIGO)).center()
        # Lo que manda un mouse de verdad: apretar, soltar, doble clic, soltar. QTest.mouseDClick
        # solo manda el doble clic, y sin el primer clic la tabla lo toma como un clic suelto.
        area = self.tabla.viewport()
        QTest.mousePress(area, Qt.LeftButton, Qt.NoModifier, centro)
        QTest.mouseRelease(area, Qt.LeftButton, Qt.NoModifier, centro)
        QTest.mouseDClick(area, Qt.LeftButton, Qt.NoModifier, centro)
        QTest.mouseRelease(area, Qt.LeftButton, Qt.NoModifier, centro)
        _app.processEvents()

        self.assertEqual(self.tabla.state(), QAbstractItemView.EditingState)
        editor = self.tabla.indexWidget(self.tabla.model().index(fila, COLUMNA_CODIGO))
        self.assertIsNotNone(editor)
        QTest.keyClick(editor, Qt.Key_Escape)
        _app.processEvents()

        self.assertNotEqual(self.tabla.state(), QAbstractItemView.EditingState)
        self.assertEqual((self.tabla.currentRow(), self.tabla.currentColumn()), (fila, COLUMNA_STOCK))
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("ALFA"))

    def test_escribir_el_stock_lo_guarda(self):
        self._celda_stock("COCA").setText("9")
        _app.processEvents()
        self.assertEqual(self._stock("COCA"), 9)
        self.assertEqual(self._celda_stock("COCA").text(), "9")
        self.assertIn("0 → 9", self.ventana.etiqueta_estado.text())

    def test_en_rojo_si_queda_por_debajo_del_minimo(self):
        # Coca tiene mínimo 2.
        self._celda_stock("COCA").setText("1")
        self.assertEqual(self._celda_stock("COCA").foreground().color(), Qt.red)
        self._celda_stock("COCA").setText("5")
        self.assertIsNone(self._celda_stock("COCA").data(Qt.ForegroundRole))

    def test_lo_mal_escrito_vuelve_atras_y_avisa(self):
        with mock.patch("ui.ordenar_stock_window.mostrar_error") as error:
            self._celda_stock("COCA").setText("diez")
            _app.processEvents()
        error.assert_called_once()
        self.assertEqual(self._celda_stock("COCA").text(), "0")
        self.assertEqual(self._stock("COCA"), 0)
        self.assertEqual(self._ajustes(), [])

    def test_despues_de_guardar_queda_listo_el_de_abajo(self):
        self.tabla.item(0, COLUMNA_STOCK).setText("4")
        _app.processEvents()
        self.assertEqual((self.tabla.currentRow(), self.tabla.currentColumn()), (1, COLUMNA_STOCK))

    def test_un_clic_en_el_renglon_deja_lista_la_celda_del_stock(self):
        self.tabla.cellClicked.emit(2, COLUMNA_CODIGO)
        self.assertEqual((self.tabla.currentRow(), self.tabla.currentColumn()), (2, COLUMNA_STOCK))

    def test_con_la_pistola_escanear_escribir_y_enter(self):
        QTest.keyClicks(self.ventana.campo_buscar, "AGUA")
        QTest.keyClick(self.ventana.campo_buscar, Qt.Key_Return)
        self.assertEqual(self.tabla.rowCount(), 1)
        self.assertEqual(self.tabla.state(), QAbstractItemView.EditingState)

        editor = self.tabla.indexWidget(self.tabla.model().index(0, COLUMNA_STOCK))
        self.assertIsNotNone(editor)
        editor.selectAll()
        QTest.keyClicks(editor, "15")
        QTest.keyClick(editor, Qt.Key_Return)
        _app.processEvents()
        _app.processEvents()

        self.assertEqual(self._stock("AGUA"), 15)
        self.assertNotEqual(self.tabla.state(), QAbstractItemView.EditingState)

    def test_enter_con_varios_articulos_no_abre_ninguno_para_escribir(self):
        QTest.keyClicks(self.ventana.campo_buscar, "500")  # Coca 500 y Agua 500
        QTest.keyClick(self.ventana.campo_buscar, Qt.Key_Return)
        self.assertEqual(self.tabla.rowCount(), 2)
        self.assertNotEqual(self.tabla.state(), QAbstractItemView.EditingState)
        self.assertEqual((self.tabla.currentRow(), self.tabla.currentColumn()), (0, COLUMNA_STOCK))


if __name__ == "__main__":
    unittest.main()
