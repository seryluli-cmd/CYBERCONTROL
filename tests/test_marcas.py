"""
tests/test_marcas.py
====================
Gestionar Marcas (botón de Artículos; pedido del dueño, 2026-10-23): solo un
Admin agrega, renombra, junta y borra marcas. Las marcas nuevas se siguen
pudiendo escribir al cargar un artículo. Las pantallas se prueban sin abrir
ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from ui.articulos_window import ArticulosWindow, DialogoGestionMarcas  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class BaseMarcas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.empleada_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COCA1", "Coca 500", None, None, 1000.0, 500.0, 0,
                                      nombre_marca_nueva="COCA")
        articulos_repo.crear_articulo("COCA2", "Coca 1L", None, None, 1500.0, 800.0, 0,
                                      nombre_marca_nueva="Coca")
        articulos_repo.crear_articulo("COCA3", "Coca 2L", None, None, 2000.0, 1000.0, 0,
                                      nombre_marca_nueva="Coca")
        self.coca_mayus = articulos_repo.buscar_marca_por_nombre("COCA")["id"]
        self.coca = articulos_repo.buscar_marca_por_nombre("Coca")["id"]

    def marca_de(self, codigo):
        return articulos_repo.buscar_por_codigo(codigo)["marca"]

    def cantidades(self):
        return {fila["nombre"]: fila["cantidad"] for fila in articulos_repo.listar_marcas_con_cantidad()}


class TestRepo(BaseMarcas):
    def test_lista_cada_marca_con_cuantos_articulos_tiene(self):
        articulos_repo.crear_marca(self.admin_id, "Pepsi")
        self.assertEqual(self.cantidades(), {"COCA": 1, "Coca": 2, "Pepsi": 0})

    def test_renombrar_cambia_el_nombre_en_todos_sus_articulos(self):
        articulos_repo.renombrar_marca(self.admin_id, self.coca, "  Coca-Cola ")
        self.assertEqual(self.marca_de("COCA2"), "Coca-Cola")
        self.assertEqual(self.marca_de("COCA3"), "Coca-Cola")

    def test_no_se_puede_renombrar_a_vacio_ni_al_nombre_de_otra(self):
        with self.assertRaisesRegex(ValueError, "vacío"):
            articulos_repo.renombrar_marca(self.admin_id, self.coca, "  ")
        with self.assertRaisesRegex(ValueError, "Ya existe una marca llamada 'COCA'"):
            articulos_repo.renombrar_marca(self.admin_id, self.coca, "COCA")

    def test_juntar_pasa_los_articulos_y_borra_la_otra(self):
        cambiados = articulos_repo.juntar_marcas(self.admin_id, self.coca_mayus, self.coca)

        self.assertEqual(cambiados, 1)
        self.assertEqual(self.marca_de("COCA1"), "Coca")
        self.assertEqual(self.cantidades(), {"Coca": 3})

    def test_juntar_una_marca_consigo_misma_o_con_una_que_ya_no_esta(self):
        with self.assertRaisesRegex(ValueError, "misma"):
            articulos_repo.juntar_marcas(self.admin_id, self.coca, self.coca)
        with self.assertRaisesRegex(ValueError, "ya no existe"):
            articulos_repo.juntar_marcas(self.admin_id, self.coca, 9999)
        self.assertEqual(self.cantidades(), {"COCA": 1, "Coca": 2})

    def test_se_borra_una_sin_articulos_y_no_una_que_tiene(self):
        pepsi = articulos_repo.crear_marca(self.admin_id, "Pepsi")
        articulos_repo.borrar_marca(self.admin_id, pepsi)
        self.assertNotIn("Pepsi", self.cantidades())

        with self.assertRaisesRegex(ValueError, "la tienen 2 artículo"):
            articulos_repo.borrar_marca(self.admin_id, self.coca)
        self.assertEqual(self.marca_de("COCA2"), "Coca")

    def test_crear_una_que_ya_existe_devuelve_la_que_habia(self):
        self.assertEqual(articulos_repo.crear_marca(self.admin_id, "Coca"), self.coca)
        with self.assertRaisesRegex(ValueError, "Escribí"):
            articulos_repo.crear_marca(self.admin_id, " ")

    def test_solo_un_admin_las_cambia(self):
        pepsi = articulos_repo.crear_marca(self.admin_id, "Pepsi")
        cambios = [
            lambda quien: articulos_repo.crear_marca(quien, "Fanta"),
            lambda quien: articulos_repo.renombrar_marca(quien, self.coca, "Coca-Cola"),
            lambda quien: articulos_repo.juntar_marcas(quien, self.coca_mayus, self.coca),
            lambda quien: articulos_repo.borrar_marca(quien, pepsi),
        ]
        for cambio in cambios:
            with self.assertRaisesRegex(PermissionError, "Solo un Administrador puede editar las marcas"):
                cambio(self.empleada_id)
        self.assertEqual(self.cantidades(), {"COCA": 1, "Coca": 2, "Pepsi": 0})

    def test_un_admin_dado_de_baja_tampoco(self):
        usuarios_repo.desactivar_usuario(self.admin_id)
        with self.assertRaises(PermissionError):
            articulos_repo.renombrar_marca(self.admin_id, self.coca, "Coca-Cola")

    def test_cualquiera_puede_seguir_escribiendo_una_marca_nueva_en_un_articulo(self):
        articulos_repo.crear_articulo("PEP", "Pepsi 500", None, None, 900.0, 400.0, 0,
                                      nombre_marca_nueva="Pepsi")
        self.assertEqual(self.marca_de("PEP"), "Pepsi")


class TestPantalla(BaseMarcas):
    def ventana(self, usuario_id):
        ventana = ArticulosWindow(None, usuarios_repo.obtener_usuario(usuario_id))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_el_boton_solo_lo_ve_el_admin(self):
        self.assertFalse(self.ventana(self.admin_id).boton_marcas.isHidden())
        self.assertTrue(self.ventana(self.empleada_id).boton_marcas.isHidden())

    def dialogo(self):
        dialogo = DialogoGestionMarcas(None, self.admin_id)
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def elegir(self, dialogo, nombre):
        fila = [marca["nombre"] for marca in dialogo.marcas].index(nombre)
        dialogo.lista.selectRow(fila)

    def test_muestra_las_marcas_con_su_cantidad(self):
        dialogo = self.dialogo()
        filas = [(dialogo.lista.item(f, 0).text(), dialogo.lista.item(f, 1).text())
                 for f in range(dialogo.lista.rowCount())]
        self.assertEqual(filas, [("COCA", "1"), ("Coca", "2")])

    def test_renombrar_con_el_nombre_de_otra_pregunta_y_las_junta(self):
        dialogo = self.dialogo()
        self.elegir(dialogo, "COCA")
        with mock.patch("ui.articulos_window.QInputDialog.getText", return_value=("Coca", True)), \
                mock.patch("ui.articulos_window.confirmar", return_value=True) as pregunta:
            dialogo.boton_renombrar.click()

        self.assertIn("¿Pasar los 1 artículo(s) de 'COCA' a 'Coca'", pregunta.call_args.args[2])
        self.assertEqual(self.cantidades(), {"Coca": 3})
        self.assertEqual(dialogo.lista.rowCount(), 1)

    def test_si_no_quiere_juntarlas_no_cambia_nada(self):
        dialogo = self.dialogo()
        self.elegir(dialogo, "COCA")
        with mock.patch("ui.articulos_window.QInputDialog.getText", return_value=("Coca", True)), \
                mock.patch("ui.articulos_window.confirmar", return_value=False):
            dialogo.boton_renombrar.click()
        self.assertEqual(self.cantidades(), {"COCA": 1, "Coca": 2})

    def test_renombrar_a_un_nombre_libre(self):
        dialogo = self.dialogo()
        self.elegir(dialogo, "Coca")
        with mock.patch("ui.articulos_window.QInputDialog.getText", return_value=("Coca-Cola", True)):
            dialogo.boton_renombrar.click()
        self.assertEqual(self.cantidades(), {"COCA": 1, "Coca-Cola": 2})

    def test_borrar_una_que_tiene_articulos_avisa_y_no_borra(self):
        dialogo = self.dialogo()
        self.elegir(dialogo, "Coca")
        with mock.patch("ui.articulos_window.confirmar", return_value=True), \
                mock.patch("ui.utils.QMessageBox") as cartel:
            dialogo.boton_borrar.click()
        self.assertTrue(cartel.mock_calls)   # mostró el motivo
        self.assertEqual(self.cantidades(), {"COCA": 1, "Coca": 2})
