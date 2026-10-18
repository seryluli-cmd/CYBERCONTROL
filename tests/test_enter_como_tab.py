"""
tests/test_enter_como_tab.py
==============================
Enter pasa al siguiente campo, como Tab, y en el último hace la acción principal
(pedido del dueño, 2026-10-18: que el mostrador ande sin tocar el mouse). Acá van
las pantallas que lo sumaron ese día: el login, Cargar Saldo de un socio, el
panel de venta de bonos de Control de PCs e "Intercambiar de máquina". El cobro
en sí está en tests/test_dialogo_pago.py. Se prueba sin abrir ninguna ventana,
plataforma "offscreen" de Qt.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import dominio  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import bonos_miembro_repo, miembros_repo, pcs_repo  # noqa: E402
from control_pcs.ui.miembros_window import DialogoCargarSaldo  # noqa: E402
from control_pcs.ui.pcs_comandos_dialogos import DialogoTrasladarSesion  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from ui.login_window import LoginWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _enter(widget, repetido=False):
    """Un Enter en `widget`; `repetido` es la repetición del teclado (tecla apretada)."""
    destino = widget.lineEdit() if hasattr(widget, "lineEdit") and widget.lineEdit() else widget
    for tipo in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(destino, QKeyEvent(tipo, Qt.Key_Return, Qt.NoModifier, "\r", repetido))


class _ConUsuario(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        usuario_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_ADMIN)
        self.usuario = usuarios_repo.obtener_usuario(usuario_id)

    def _mostrar(self, ventana):
        self.addCleanup(ventana.deleteLater)
        ventana.show()
        ventana.activateWindow()
        QApplication.processEvents()
        return ventana


class TestLogin(_ConUsuario):
    def test_enter_en_el_nombre_pasa_a_la_clave(self):
        login = self._mostrar(LoginWindow(lambda usuario: None))
        login.combo_nombre.setFocus()

        _enter(login.combo_nombre)

        self.assertTrue(login.campo_clave.hasFocus())


class TestCargarSaldo(_ConUsuario):
    def setUp(self):
        super().setUp()
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        self.miembro = miembros_repo.obtener_miembro(miembro_id)

    def _dialogo(self):
        return self._mostrar(DialogoCargarSaldo(self.usuario, self.miembro))

    def test_enter_recorre_monto_y_medio_de_pago_y_cobra(self):
        dialogo = self._dialogo()
        dialogo.combo_modo.setFocus()

        _enter(dialogo.combo_modo)
        self.assertTrue(dialogo.spin_monto.hasFocus())

        dialogo.spin_monto.lineEdit().selectAll()
        QTest.keyClicks(dialogo.spin_monto.lineEdit(), "2000")
        _enter(dialogo.spin_monto)
        self.assertTrue(dialogo.combo_metodo.hasFocus())

        _enter(dialogo.combo_metodo)  # Efectivo: cobra

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertGreater(miembros_repo.obtener_miembro(self.miembro["id"])["saldo_minutos"], 0)

    def test_con_bono_fijo_enter_pasa_al_bono(self):
        bonos_miembro_repo.crear_bono("Combo Socio", 120, 2000.0)
        dialogo = self._dialogo()
        dialogo.combo_modo.setCurrentIndex(dialogo.combo_modo.findData("BONO"))
        dialogo.combo_modo.setFocus()

        _enter(dialogo.combo_modo)
        self.assertTrue(dialogo.combo_bono.hasFocus())

        _enter(dialogo.combo_bono)
        self.assertTrue(dialogo.combo_metodo.hasFocus())

    def test_un_enter_apretado_no_cobra(self):
        dialogo = self._dialogo()
        dialogo.spin_monto.setValue(2000)
        dialogo.combo_metodo.setFocus()

        _enter(dialogo.combo_metodo, repetido=True)

        self.assertTrue(dialogo.isVisible())
        self.assertEqual(miembros_repo.obtener_miembro(self.miembro["id"])["saldo_minutos"], 0)


class TestPanelDeBonos(_ConUsuario):
    def setUp(self):
        super().setUp()
        self.estacion_id = pcs_repo.crear_estacion("PC 1")
        pcs_repo.crear_bono("1 hora", 60, 1000.0)

    def _item(self):
        return next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.estacion_id)

    def _panel(self):
        panel = self._mostrar(PanelDetalleEstacion(self.usuario, lambda: None))
        panel.mostrar(self._item())
        panel.combo_metodo.setFocus()
        return panel

    def test_enter_en_el_medio_de_pago_inicia_la_sesion(self):
        panel = self._panel()

        _enter(panel.combo_metodo)  # Efectivo: cobra el bono elegido

        self.assertIsNotNone(self._item()["sesion"])

    def test_un_enter_apretado_no_inicia_la_sesion(self):
        panel = self._panel()

        _enter(panel.combo_metodo, repetido=True)

        self.assertIsNone(self._item()["sesion"])


class TestTrasladarSesion(_ConUsuario):
    def test_enter_en_la_pc_de_destino_pasa_la_sesion(self):
        origen_id = pcs_repo.crear_estacion("PC 1")
        destino_id = pcs_repo.crear_estacion("PC 2")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 1000.0)
        pcs_repo.asignar_bono(origen_id, bono_id, self.usuario["id"], [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0}])
        estados = pcs_repo.estado_estaciones()
        origen = next(i["estacion"] for i in estados if i["estacion"]["id"] == origen_id)
        dialogo = self._mostrar(DialogoTrasladarSesion(origen, estados, self.usuario))
        dialogo.combo_destino.setFocus()

        _enter(dialogo.combo_destino)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        en_destino = next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == destino_id)
        self.assertIsNotNone(en_destino["sesion"])


if __name__ == "__main__":
    unittest.main()
