"""
tests/test_control_stock.py
===========================
CONTROL DE STOCK (botón de debajo del mosaico, a la derecha de APAGAR; pedido
del dueño, 2026-10-24): la lista de los artículos con stock, de la A a la Z,
para imprimirla y contar el estante. Los de 0 o negativo no salen. El botón lo
ven todos, pero solo el Admin lo abre. Las pantallas se prueban sin abrir
ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
import weakref
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from ui.control_stock_window import COLUMNA_UNIDADES, BotonControlStock, VentanaControlStock  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class BaseControlStock(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.operador_id = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        for codigo, descripcion, stock in [
            ("1", "Zucaritas 300 g", 4), ("2", "alfajor Jorgito", 15), ("3", "Coca 500", 7),
            ("4", "Álamo chicles", 2), ("5", "Bon o Bon", 0), ("6", "Agua 500", -3),
        ]:
            articulos_repo.crear_articulo(codigo, descripcion, None, None, 100.0, 50.0, 0)
            with conexion_db() as conexion:
                conexion.execute("UPDATE articulos SET stock = ? WHERE codigo = ?", (stock, codigo))

    def usuario(self, usuario_id):
        return usuarios_repo.obtener_usuario(usuario_id)


class TestLaLista(BaseControlStock):
    def test_solo_los_que_tienen_stock_de_la_a_a_la_z_sin_mirar_mayusculas_ni_acentos(self):
        lista = articulos_repo.listar_para_control_de_stock(self.admin_id)
        self.assertEqual([(a["descripcion"], a["stock"]) for a in lista], [
            ("Álamo chicles", 2), ("alfajor Jorgito", 15), ("Coca 500", 7), ("Zucaritas 300 g", 4),
        ])

    def test_solo_el_admin(self):
        with self.assertRaisesRegex(PermissionError, "Solo un Administrador puede ver el Control de Stock"):
            articulos_repo.listar_para_control_de_stock(self.operador_id)

    def test_sin_acentos_es_para_buscar_y_ordenar(self):
        self.assertEqual(dominio.sin_acentos("Álamo PÉREZ"), "alamo perez")
        self.assertEqual(dominio.sin_acentos(None), "")


class TestVentana(BaseControlStock):
    def ventana(self):
        ventana = VentanaControlStock(self.admin_id)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_muestra_cada_articulo_con_sus_unidades(self):
        tabla = self.ventana().tabla
        filas = [(tabla.item(fila, 0).text(), tabla.item(fila, COLUMNA_UNIDADES).text())
                 for fila in range(tabla.rowCount())]
        self.assertEqual(filas, [("Álamo chicles", "2"), ("alfajor Jorgito", "15"),
                                 ("Coca 500", "7"), ("Zucaritas 300 g", "4")])
        self.assertEqual(tabla.item(0, COLUMNA_UNIDADES).textAlignment(), Qt.AlignRight | Qt.AlignVCenter)

    def test_la_hoja_impresa_trae_la_columna_contado_para_anotar_a_mano(self):
        html = self.ventana().html_para_imprimir(datetime(2026, 10, 24, 9, 30))
        self.assertIn("Control de Stock", html)
        self.assertIn("Impreso el 24/10/2026 09:30", html)
        self.assertIn("4 artículos con stock", html)
        self.assertIn(">Contado<", html)
        self.assertLess(html.index("Álamo chicles"), html.index("alfajor Jorgito"))
        self.assertNotIn("Bon o Bon", html)
        self.assertNotIn("Agua 500", html)

    def test_imprimir_abre_la_vista_previa(self):
        ventana = self.ventana()
        with mock.patch("ui.control_stock_window.imprimir.vista_previa") as vista_previa:
            ventana.boton_imprimir.click()
        vista_previa.assert_called_once()
        self.assertEqual(vista_previa.call_args.args[2], "Control de Stock")

    def test_la_impresora_sigue_viva_mientras_esta_abierta_la_vista_previa(self):
        """La vista previa de Qt usa la impresora sin guardarla: si nadie la
        retiene, Python la borra y la vista previa lee memoria liberada (en el
        local el programa se cerró sin ningún cartel, 2026-10-26). Acá la vista
        previa es de mentira y solo mira si la impresora sigue viva al abrirse."""
        viva_al_abrir = []

        class VistaPreviaDeMentira:
            def __init__(self, impresora, parent):
                self._impresora = weakref.ref(impresora)  # sin retenerla, como Qt
                self.paintRequested = mock.Mock()

            def setWindowTitle(self, titulo):
                pass

            def resize(self, ancho, alto):
                pass

            def exec(self):
                viva_al_abrir.append(self._impresora() is not None)

        with mock.patch("ui.imprimir.QPrintPreviewDialog", VistaPreviaDeMentira):
            self.ventana().boton_imprimir.click()
        self.assertEqual(viva_al_abrir, [True])

    def test_sin_articulos_con_stock_no_hay_nada_que_imprimir(self):
        with conexion_db() as conexion:
            conexion.execute("UPDATE articulos SET stock = 0")
        ventana = self.ventana()
        self.assertEqual(ventana.tabla.rowCount(), 0)
        self.assertFalse(ventana.boton_imprimir.isEnabled())
        self.assertEqual(ventana.etiqueta.text(), "No hay ningún artículo con stock.")


class TestBoton(BaseControlStock):
    def boton(self, usuario_id):
        boton = BotonControlStock(self.usuario(usuario_id))
        self.addCleanup(boton.deleteLater)
        return boton

    def test_lo_ven_todos_igual(self):
        for usuario_id in (self.admin_id, self.operador_id):
            boton = self.boton(usuario_id)
            self.assertEqual(boton.text(), "📦  CONTROL DE STOCK")
            self.assertEqual(boton.property("clase"), "barra")
            self.assertTrue(boton.isEnabled())

    def test_solo_el_admin_lo_abre(self):
        with mock.patch("ui.control_stock_window.VentanaControlStock") as ventana:
            self.boton(self.operador_id).click()
            ventana.assert_not_called()
            self.boton(self.admin_id).click()
            ventana.assert_called_once()
            self.assertEqual(ventana.call_args.args[0], self.admin_id)

    def test_va_pegado_a_la_derecha_de_apagar_debajo_del_mosaico(self):
        panel = PanelControlPcs(self.usuario(self.operador_id))
        panel.detener_actualizacion()
        self.addCleanup(panel.deleteLater)
        panel.setAttribute(Qt.WA_DontShowOnScreen)
        panel.resize(1600, 900)
        panel.show()
        self.addCleanup(panel.hide)
        _app.processEvents()

        apagar = panel.botones_libres.boton_apagar
        stock = panel.boton_control_stock
        borde_de_apagar = apagar.mapTo(panel, QPoint(apagar.width(), 0))
        inicio_de_stock = stock.mapTo(panel, QPoint(0, 0))
        self.assertTrue(0 <= inicio_de_stock.x() - borde_de_apagar.x() < 20,
                        (borde_de_apagar.x(), inicio_de_stock.x()))
        # En la misma fila: los centros a la misma altura (con o sin ícono, una
        # tecla puede medir un par de píxeles más que la otra).
        centro_de_apagar = borde_de_apagar.y() + apagar.height() / 2
        centro_de_stock = inicio_de_stock.y() + stock.height() / 2
        self.assertLessEqual(abs(centro_de_stock - centro_de_apagar), 3)
        self.assertFalse(panel.mosaico.parentWidget().isAncestorOf(stock))
