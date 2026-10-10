"""
tests/test_estilo_ui.py
=========================
El aspecto del programa (se prueba sin abrir ninguna ventana, plataforma "offscreen"
de Qt): que se le pida a Qt el esquema de color CLARO aunque Windows esté en modo
oscuro (si no, los cuadros que la hoja de estilos no pinta, como el log de "Actividad
reciente", salen negros con la letra oscura encima), que las tablas no muestren la
numeración de filas y que la barra de arriba use los botones sin borde.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QPushButton  # noqa: E402

import dominio  # noqa: E402
import main as programa  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.utils import crear_tabla  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestAspectoDelPrograma(BaseConBaseTemporal):
    def test_aplicar_estilo_fija_el_esquema_claro_y_la_hoja_de_estilos(self):
        # La plataforma "offscreen" de las pruebas no aplica el esquema de color, así
        # que acá se verifica lo que se le pide a Qt (en Windows real se comprobó
        # dibujando las pantallas: con el modo oscuro puesto, el log salía negro).
        app = mock.Mock()

        programa.aplicar_estilo(app)

        app.setStyle.assert_called_once_with("Fusion")
        app.styleHints.return_value.setColorScheme.assert_called_once_with(Qt.ColorScheme.Light)
        app.setStyleSheet.assert_called_once_with(programa.HOJA_DE_ESTILOS)

    def test_las_tablas_no_muestran_la_numeracion_de_filas(self):
        tabla = crear_tabla(["Nombre", "Precio"])
        self.addCleanup(tabla.deleteLater)

        self.assertFalse(tabla.verticalHeader().isVisible())

    def test_la_barra_de_arriba_usa_botones_sin_borde_salvo_vender_y_cerrar_sesion(self):
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        ventana = MainWindow(admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        barra = ventana.findChild(QFrame, "encabezadoInicio")
        clases = {b.text().strip(): b.property("clase") for b in barra.findChildren(QPushButton)}

        self.assertEqual(clases["Cerrar sesión"], "peligro")
        self.assertEqual(clases["🛒  Vender"], "primario")
        otros = [clase for texto, clase in clases.items() if texto not in ("Cerrar sesión", "🛒  Vender")]
        self.assertTrue(otros and all(clase == "barra" for clase in otros), clases)


if __name__ == "__main__":
    unittest.main()
