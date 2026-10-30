"""
tests/test_pantalla_ingreso.py
==============================
La pantalla de ingreso con el diseño "Portal" (maqueta D que eligió el dueño el
2026-10-30, ui/login_window.py y ui/ingreso_dibujos.py): que los avisos que se
abren encima se vean como siempre aunque la pantalla sea oscura, que la animación
corra solo mientras se ve (al entrar, la ventana se oculta y no puede quedar
girando todo el turno) y que la hora de abajo esté en castellano.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QPalette  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QLabel, QPushButton, QVBoxLayout  # noqa: E402

import dominio  # noqa: E402
import main as programa  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from ui.ingreso_dibujos import hora_y_fecha  # noqa: E402
from ui.login_window import LoginWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestPantallaDeIngreso(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.addCleanup(_app.setStyleSheet, _app.styleSheet())
        _app.setStyleSheet(programa.HOJA_DE_ESTILOS)
        self.ventana = LoginWindow(lambda usuario: None)
        self.addCleanup(self.ventana.deleteLater)

    def test_los_avisos_que_se_abren_encima_no_heredan_lo_oscuro(self):
        # "Nombre o clave incorrectos" y la caja al entrar se abren como hijos de esta
        # ventana: por eso sus colores van por objectName y no en una hoja propia.
        dialogo = QDialog(self.ventana)
        texto_del_dialogo = QLabel("Nombre o clave incorrectos.", dialogo)
        boton_del_dialogo = QPushButton("OK", dialogo)
        capa = QVBoxLayout(dialogo)
        capa.addWidget(texto_del_dialogo)
        capa.addWidget(boton_del_dialogo)
        subtitulo = self.ventana.findChild(QLabel, "subtituloIngreso")
        entrar = self.ventana.findChild(QPushButton, "botonEntrar")
        for widget in (subtitulo, texto_del_dialogo, entrar, boton_del_dialogo):
            widget.ensurePolished()

        letra_del_dialogo = texto_del_dialogo.palette().color(QPalette.WindowText).name()
        self.assertEqual(letra_del_dialogo, "#1b2233")  # la letra de todo el programa
        self.assertNotEqual(subtitulo.palette().color(QPalette.WindowText).name(), letra_del_dialogo)
        self.assertNotEqual(entrar.palette().color(QPalette.ButtonText).name(),
                            boton_del_dialogo.palette().color(QPalette.ButtonText).name())

    def test_la_animacion_corre_solo_mientras_se_ve_la_pantalla(self):
        self.assertFalse(self.ventana._animacion.isActive())

        self.ventana.show()
        self.assertTrue(self.ventana._animacion.isActive())

        # Al entrar, main.py cierra (oculta) la pantalla de ingreso.
        self.ventana.close()
        self.assertFalse(self.ventana._animacion.isActive())

    def test_un_cuadro_de_la_animacion_se_dibuja_sin_errores(self):
        self.ventana.show()
        self.ventana._inicio -= 1.5
        self.ventana._siguiente_cuadro()
        self.assertFalse(self.ventana.grab().isNull())

    def test_sigue_entrando_con_enter_en_la_clave(self):
        entradas = []
        ventana = LoginWindow(entradas.append)
        self.addCleanup(ventana.deleteLater)
        ventana.combo_nombre.setCurrentText("Sergio")
        ventana.campo_clave.setText("1234")

        # La clave de fábrica avisa antes de entrar: acá no hace falta ver el aviso.
        with mock.patch("ui.login_window.mostrar_aviso"):
            ventana.campo_clave.returnPressed.emit()

        self.assertEqual([usuario["nombre"] for usuario in entradas], ["Sergio"])


class TestHoraDeAbajo(unittest.TestCase):
    def test_va_en_castellano_sin_depender_de_windows(self):
        self.assertEqual(hora_y_fecha(datetime(2026, 10, 30, 23, 41)), "23:41   ·   viernes 30 de octubre")
        self.assertEqual(hora_y_fecha(datetime(2026, 3, 2, 7, 5)), "07:05   ·   lunes 2 de marzo")


if __name__ == "__main__":
    unittest.main()
