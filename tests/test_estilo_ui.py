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
from PySide6.QtWidgets import QApplication, QFrame, QLabel, QPushButton  # noqa: E402

import dominio  # noqa: E402
import main as programa  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from ui.login_window import LoginWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.utils import crear_tabla  # noqa: E402
from control_pcs.ui.miembros_window import DialogoTramosTarifaMiembro  # noqa: E402
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

    def test_la_pantalla_de_ingreso_se_llama_cyberbios(self):
        # Pedido del dueño (2026-10-10): el título de la primera pantalla es la marca,
        # no "Sistema de Kiosko", y escrita igual (CyberBIOS) en la barra de la ventana.
        ventana = LoginWindow(lambda usuario: None)
        self.addCleanup(ventana.deleteLater)

        textos = [etiqueta.text() for etiqueta in ventana.findChildren(QLabel)]

        self.assertIn("CyberBIOS", textos)
        self.assertNotIn("Sistema de Kiosko", textos)
        self.assertEqual(ventana.windowTitle(), "CyberBIOS - Ingreso")

    def test_la_barra_de_la_ventana_principal_dice_cyberbios_con_el_nombre_y_el_rol(self):
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        ventana = MainWindow(admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        self.assertEqual(ventana.windowTitle(), f"CyberBIOS - Admin ({dominio.ROL_ADMIN})")

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

    def test_la_barra_de_arriba_dice_operador_y_el_nombre_sin_saludo_ni_rol(self):
        # Pedido del dueño (2026-10-16): "Operador: TOBY", no "Hola, TOBY · EMPLEADA".
        empleada = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA))
        ventana = MainWindow(empleada, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        barra = ventana.findChild(QFrame, "encabezadoInicio")
        textos = [etiqueta.text() for etiqueta in barra.findChildren(QLabel)]

        self.assertIn("Operador: TOBY", textos)
        self.assertFalse(any("Hola" in texto or dominio.ROL_EMPLEADA in texto for texto in textos), textos)

    def test_el_admin_figura_como_administrador_y_la_barra_va_en_dos_renglones(self):
        # Pedido del dueño (2026-10-18): arriba quién está y la caja; abajo los botones
        # desde Vender, con nombres cortos ("Admin Kiosko", "Config ADMIN") y una sola
        # carita en Miembros, para que todo entre en la pantalla del mostrador.
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN))
        ventana = MainWindow(admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        barra = ventana.findChild(QFrame, "encabezadoInicio")

        titulo = next(e for e in barra.findChildren(QLabel) if e.text() == "Administrador: Sergio")
        botones = {boton.text(): boton for boton in barra.findChildren(QPushButton)}
        for texto in ("🧑  Miembros", "🛠️  Admin Kiosko", "⚙️  Config ADMIN"):
            self.assertIn(texto, botones)
        ventana.resize(1340, 700)
        ventana.show()
        QApplication.processEvents()
        self.addCleanup(ventana.close)
        vender = botones["🛒  Vender"]
        # Los botones van debajo del nombre, Vender primero a la izquierda.
        self.assertGreater(vender.mapTo(barra, vender.rect().topLeft()).y(), titulo.mapTo(barra, titulo.rect().topLeft()).y())
        self.assertLessEqual(vender.mapTo(barra, vender.rect().topLeft()).x(), titulo.mapTo(barra, titulo.rect().topLeft()).x())
        # (Que entre en 1366 de ancho se midió con la pantalla real de Windows: acá,
        # sin pantalla, las letras son otras y los anchos no sirven.)

    def test_los_montos_de_la_tarifa_de_socios_entran_en_su_fila(self):
        # Reportado por el dueño (2026-10-17): en "Tarifa por Hora para Socios" los
        # campos de monto quedaban cortados por la fila y no se podía leer ni cargar nada.
        # El relleno de los campos sale de la hoja de estilos, que en el programa se le
        # pone a toda la aplicación al arrancar (antes de abrir cualquier diálogo).
        self.addCleanup(_app.setStyleSheet, _app.styleSheet())
        _app.setStyleSheet(programa.HOJA_DE_ESTILOS)
        dialogo = DialogoTramosTarifaMiembro()
        self.addCleanup(dialogo.deleteLater)
        dialogo._agregar_fila(5000, 1500)

        tabla = dialogo.tabla
        for fila in range(tabla.rowCount()):
            for columna in range(tabla.columnCount()):
                campo = tabla.cellWidget(fila, columna)
                self.assertGreaterEqual(tabla.rowHeight(fila), campo.sizeHint().height(), (fila, columna))
        self.assertFalse(tabla.verticalHeader().isVisible())


if __name__ == "__main__":
    unittest.main()
