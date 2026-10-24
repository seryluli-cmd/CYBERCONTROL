"""
tests/test_estilo_ui.py
=========================
El aspecto del programa (se prueba sin abrir ninguna ventana, plataforma "offscreen"
de Qt): que se le pida a Qt el esquema de color CLARO aunque Windows esté en modo
oscuro (si no, los cuadros que la hoja de estilos no pinta, como el log de "Actividad
reciente", salen negros con la letra oscura encima), que las tablas no muestren la
numeración de filas, que la barra oscura de arriba use sus teclas (y que Cierre de
Turno no cambie de tamaño al titilar) y que las ventanas que abre el panel gris de
Control de PCs no hereden sus letras claras.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import (  # noqa: E402
    QAbstractItemView, QApplication, QDialog, QFrame, QLabel, QLineEdit, QPushButton, QStyle,
    QStyleOptionFrame, QTableWidgetItem, QVBoxLayout,
)

import dominio  # noqa: E402
import main as programa  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from ui.login_window import LoginWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.utils import crear_tabla  # noqa: E402
from control_pcs.ui.miembros_window import DialogoTramosTarifaMiembro  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _regla(selector: str) -> dict:
    """Las propiedades de `selector { ... }` en la hoja de estilos del programa."""
    cuerpo = programa.HOJA_DE_ESTILOS.split(selector + " {", 1)[1].split("}", 1)[0]
    propiedades = (linea.strip().rstrip(";").split(":", 1) for linea in cuerpo.splitlines() if ":" in linea)
    return {nombre.strip(): valor.strip() for nombre, valor in propiedades}


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

    def test_la_barra_de_arriba_usa_teclas_de_barra_salvo_vender_y_operador(self):
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        ventana = MainWindow(admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        barra = ventana.findChild(QFrame, "encabezadoInicio")
        clases = {b.text().strip(): b.property("clase") for b in barra.findChildren(QPushButton)}

        # Se llamó "CERRAR SESIÓN" y después "CAMB OPERADOR" (pedidos del dueño, 2026-10-23 y 24).
        self.assertEqual(clases["🔄  OPERADOR"], "peligro")
        self.assertNotIn("CERRAR SESIÓN", clases)
        self.assertNotIn("CAMB OPERADOR", clases)
        self.assertEqual(clases["🛒  VENDER"], "primario")
        otros = [clase for texto, clase in clases.items() if texto not in ("🔄  OPERADOR", "🛒  VENDER")]
        self.assertTrue(otros and all(clase == "barra" for clase in otros), clases)

    def test_operador_vuelve_al_ingreso(self):
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        al_cerrar = []
        ventana = MainWindow(admin, lambda: al_cerrar.append(True))
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        barra = ventana.findChild(QFrame, "encabezadoInicio")
        next(b for b in barra.findChildren(QPushButton) if b.text() == "🔄  OPERADOR").click()
        self.assertEqual(al_cerrar, [True])

    def test_operador_va_pegado_a_la_derecha_de_clave(self):
        # Pedido del dueño (2026-10-23): antes iba solo en la punta derecha y con
        # la pantalla de 1920 del mostrador quedaba lejos de todo.
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        ventana = MainWindow(admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)
        ventana.setAttribute(Qt.WA_DontShowOnScreen)
        ventana.resize(1920, 1000)
        ventana.show()
        self.addCleanup(ventana.hide)
        _app.processEvents()

        barra = ventana.findChild(QFrame, "encabezadoInicio")
        botones = {b.text(): b for b in barra.findChildren(QPushButton)}
        clave = next(boton for texto, boton in botones.items() if texto.endswith("CLAVE"))
        operador = botones["🔄  OPERADOR"]
        hueco = operador.geometry().left() - clave.geometry().right()
        self.assertTrue(0 < hueco < 20, hueco)
        self.assertEqual(max(b.geometry().right() for b in botones.values()), operador.geometry().right())

    def test_los_botones_de_la_barra_de_arriba_van_en_mayuscula_y_negrita(self):
        # Pedido del dueño (2026-10-22). Reservas pone su texto aparte (cuántas hay hoy).
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        ventana = MainWindow(admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        textos = [b.text() for b in ventana.findChild(QFrame, "encabezadoInicio").findChildren(QPushButton)]

        self.assertIn("📅  RESERVAS", textos)
        self.assertTrue(all(texto == texto.upper() for texto in textos), textos)
        for selector in ('QPushButton[clase="barra"]', '#encabezadoInicio QPushButton[clase="primario"]',
                         '#encabezadoInicio QPushButton[clase="peligro"]', 'QPushButton[clase="alerta"]'):
            self.assertEqual(_regla(selector)["font-weight"], "700", selector)

    def test_cierre_de_turno_no_cambia_de_tamano_al_titilar(self):
        # Barra oscura (2026-10-19): el rojo de "alerta" lleva los mismos bordes,
        # relleno y letra que "barra". Antes la letra pasaba a negrita y el botón
        # crecía 4 px y empujaba a los de al lado cada vez que titilaba (medido con la
        # pantalla real de Windows; acá, sin pantalla, las letras miden lo mismo en
        # negrita, así que se comparan las reglas de la hoja de estilos).
        barra = _regla('QPushButton[clase="barra"]')
        alerta = _regla('QPushButton[clase="alerta"]')

        self.assertEqual(alerta["font-weight"], barra["font-weight"])
        self.assertEqual(alerta["padding"], barra["padding"])
        self.assertEqual(alerta["border"].split()[0], barra["border"].split()[0])
        self.assertEqual(alerta["border-bottom"].split()[0], barra["border-bottom"].split()[0])

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
        for texto in ("🧑  MIEMBROS", "🛠️  ADMIN KIOSKO", "⚙️  CONFIG ADMIN"):
            self.assertIn(texto, botones)
        ventana.resize(1340, 700)
        ventana.show()
        QApplication.processEvents()
        self.addCleanup(ventana.close)
        vender = botones["🛒  VENDER"]
        # Los botones van debajo del nombre, Vender primero a la izquierda.
        self.assertGreater(vender.mapTo(barra, vender.rect().topLeft()).y(), titulo.mapTo(barra, titulo.rect().topLeft()).y())
        self.assertLessEqual(vender.mapTo(barra, vender.rect().topLeft()).x(), titulo.mapTo(barra, titulo.rect().topLeft()).x())
        # (El ancho se mide con la pantalla real de Windows: acá, sin pantalla, las letras
        # son otras y los anchos no sirven. Con mayúscula y negrita, 2026-10-22, la ventana
        # pide unos 1490 px; antes, unos 1370. El mostrador tiene 1920.)

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

    def test_el_numero_entra_en_la_celda_que_se_esta_escribiendo(self):
        # Reportado por el dueño (2026-10-20): en ORDENAR Stock, al escribir el stock, el
        # número se veía como una rayita. El campo que abre la celda tenía el relleno de
        # todos los campos y en un renglón de tabla le quedaba ~1 px a la letra. Pasa en
        # cualquier tabla donde se escribe en la celda (también "Editar módems").
        self.addCleanup(_app.setStyleSheet, _app.styleSheet())
        _app.setStyleSheet(programa.HOJA_DE_ESTILOS)
        tabla = crear_tabla(["Código", "Stock"])
        self.addCleanup(tabla.deleteLater)
        tabla.setEditTriggers(QAbstractItemView.DoubleClicked)
        tabla.insertRow(0)
        for columna, texto in enumerate(("COCA", "54")):
            tabla.setItem(0, columna, QTableWidgetItem(texto))
        tabla.resize(400, 200)
        tabla.show()
        _app.processEvents()

        tabla.editItem(tabla.item(0, 1))
        _app.processEvents()
        campo = next(c for c in tabla.viewport().findChildren(QLineEdit) if c.isVisible())
        opcion = QStyleOptionFrame()
        campo.initStyleOption(opcion)
        lugar_para_la_letra = campo.style().subElementRect(QStyle.SE_LineEditContents, opcion, campo)

        self.assertGreaterEqual(lugar_para_la_letra.height(), campo.fontMetrics().height())

    def test_las_ventanas_que_abre_el_panel_gris_no_heredan_sus_letras_claras(self):
        # El panel del costado de Control de PCs es gris medio con letras claras
        # (eligió el dueño, 2026-10-19). El cobro, el login del socio y los avisos se
        # abren con el panel como padre: si sus reglas no fueran solo para los hijos
        # directos (">"), esas ventanas quedarían con letras claras sobre fondo claro.
        self.addCleanup(_app.setStyleSheet, _app.styleSheet())
        _app.setStyleSheet(programa.HOJA_DE_ESTILOS)
        admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN))
        panel = PanelDetalleEstacion(admin, lambda: None)
        self.addCleanup(panel.deleteLater)
        dialogo = QDialog(panel)
        texto_del_dialogo = QLabel("¿Finalizar la sesión?", dialogo)
        QVBoxLayout(dialogo).addWidget(texto_del_dialogo)

        for etiqueta in (panel.etiqueta_titulo, texto_del_dialogo):
            etiqueta.ensurePolished()

        letra_del_panel = panel.etiqueta_titulo.palette().color(QPalette.WindowText).name()
        letra_del_dialogo = texto_del_dialogo.palette().color(QPalette.WindowText).name()

        self.assertEqual(letra_del_dialogo, _regla("QWidget")["color"].lower())
        self.assertNotEqual(letra_del_panel, letra_del_dialogo)  # el panel sí, con su letra clara


if __name__ == "__main__":
    unittest.main()
