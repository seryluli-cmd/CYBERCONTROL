"""
tests/test_enter_como_tab.py
==============================
Enter pasa al siguiente campo, como Tab, y en el último hace la acción principal
(pedido del dueño, 2026-10-18: que el mostrador ande sin tocar el mouse). Acá van
las pantallas que lo sumaron ese día: el login, Cargar Saldo de un socio, Trámites,
el panel de venta de bonos de Control de PCs e "Intercambiar de máquina". Las que
cobran abren todas la misma ventana de cobro, que acá se reemplaza por un pago
justo; la ventana en sí está en tests/test_dialogo_pago.py. Se prueba sin abrir ninguna ventana,
plataforma "offscreen" de Qt.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import dominio  # noqa: E402
from repositories import tramites_repo, usuarios_repo, ventas_repo  # noqa: E402
from control_pcs.repositories import bonos_miembro_repo, miembros_repo, pcs_repo  # noqa: E402
from control_pcs.ui.miembros_window import DialogoCargarSaldo  # noqa: E402
from control_pcs.ui.pcs_comandos_dialogos import DialogoTrasladarSesion  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from ui.login_window import LoginWindow  # noqa: E402
from ui.tramites_window import DialogoTramites  # noqa: E402
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


def _cobro_en_efectivo(prueba, donde):
    """Reemplaza la ventana de cobro (modal) de la pantalla `donde` por un pago
    justo en efectivo."""
    cobrar = mock.patch(
        f"{donde}.cobrar",
        side_effect=lambda ventana, monto: [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}],
    ).start()
    prueba.addCleanup(mock.patch.stopall)
    return cobrar


class TestCargarSaldo(_ConUsuario):
    """Cargar Saldo de un socio cobra con la misma ventana que una venta de kiosko
    (pedido del dueño, 2026-10-18: antes tenía un combo "Medio de pago")."""

    def setUp(self):
        super().setUp()
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        self.miembro = miembros_repo.obtener_miembro(miembro_id)

    def _dialogo(self):
        return self._mostrar(DialogoCargarSaldo(self.usuario, self.miembro))

    def _saldo(self):
        return miembros_repo.obtener_miembro(self.miembro["id"])["saldo_minutos"]

    def test_enter_en_el_monto_abre_el_cobro_y_carga(self):
        cobrar = _cobro_en_efectivo(self, "control_pcs.ui.miembros_window")
        dialogo = self._dialogo()
        dialogo.combo_modo.setFocus()

        _enter(dialogo.combo_modo)
        self.assertTrue(dialogo.spin_monto.hasFocus())

        dialogo.spin_monto.lineEdit().selectAll()
        QTest.keyClicks(dialogo.spin_monto.lineEdit(), "2000")
        _enter(dialogo.spin_monto)

        cobrar.assert_called_once_with(dialogo, 2000.0)
        self.assertEqual(dialogo.result(), QDialog.Accepted)
        self.assertGreater(self._saldo(), 0)

    def test_con_bono_fijo_enter_en_el_bono_abre_el_cobro(self):
        bonos_miembro_repo.crear_bono("Combo Socio", 120, 2000.0)
        cobrar = _cobro_en_efectivo(self, "control_pcs.ui.miembros_window")
        dialogo = self._dialogo()
        dialogo.combo_modo.setCurrentIndex(dialogo.combo_modo.findData("BONO"))
        dialogo.combo_modo.setFocus()

        _enter(dialogo.combo_modo)
        self.assertTrue(dialogo.combo_bono.hasFocus())

        _enter(dialogo.combo_bono)

        cobrar.assert_called_once_with(dialogo, 2000.0)
        self.assertEqual(self._saldo(), 120)

    def test_si_se_cancela_el_cobro_no_carga_nada(self):
        cobrar = mock.patch("control_pcs.ui.miembros_window.cobrar", return_value=None).start()
        self.addCleanup(mock.patch.stopall)
        dialogo = self._dialogo()
        dialogo.spin_monto.setValue(2000)
        dialogo.spin_monto.setFocus()

        _enter(dialogo.spin_monto)

        cobrar.assert_called_once()
        self.assertTrue(dialogo.isVisible())
        self.assertEqual(self._saldo(), 0)

    def test_un_enter_apretado_no_abre_el_cobro(self):
        cobrar = _cobro_en_efectivo(self, "control_pcs.ui.miembros_window")
        dialogo = self._dialogo()
        dialogo.spin_monto.setValue(2000)
        dialogo.spin_monto.setFocus()

        _enter(dialogo.spin_monto, repetido=True)

        cobrar.assert_not_called()
        self.assertEqual(self._saldo(), 0)

    def test_ya_no_hay_combo_de_medio_de_pago(self):
        self.assertFalse(hasattr(self._dialogo(), "combo_metodo"))


class TestTramites(_ConUsuario):
    """Trámites cobra con la misma ventana que una venta de kiosko (pedido del
    dueño, 2026-10-18: antes tenía un combo "Medio de pago")."""

    def setUp(self):
        super().setUp()
        self.tramite_id = tramites_repo.crear_tramite("Boleta de luz")
        mock.patch("ui.tramites_window.mostrar_info").start()
        self.addCleanup(mock.patch.stopall)

    def _dialogo(self):
        dialogo = self._mostrar(DialogoTramites(self.usuario))
        dialogo.spin_monto.setValue(2500)
        dialogo.spin_monto.setFocus()
        return dialogo

    def test_enter_en_el_monto_abre_el_cobro_y_graba_el_tramite(self):
        cobrar = _cobro_en_efectivo(self, "ui.tramites_window")
        dialogo = self._dialogo()

        _enter(dialogo.spin_monto)

        cobrar.assert_called_once_with(dialogo, 2500.0)
        self.assertEqual(dialogo.result(), QDialog.Accepted)
        venta = ventas_repo.listar_ventas_recientes()[0]
        self.assertEqual(tramites_repo.tramite_de_venta(venta["id"]), "Boleta de luz")

    def test_si_se_cancela_el_cobro_no_graba_nada(self):
        mock.patch("ui.tramites_window.cobrar", return_value=None).start()
        dialogo = self._dialogo()

        _enter(dialogo.spin_monto)

        self.assertTrue(dialogo.isVisible())
        self.assertEqual(len(ventas_repo.listar_ventas_recientes()), 0)

    def test_un_enter_apretado_no_abre_el_cobro(self):
        cobrar = _cobro_en_efectivo(self, "ui.tramites_window")
        dialogo = self._dialogo()

        _enter(dialogo.spin_monto, repetido=True)

        cobrar.assert_not_called()
        self.assertEqual(len(ventas_repo.listar_ventas_recientes()), 0)

    def test_ya_no_hay_combo_de_medio_de_pago(self):
        self.assertFalse(hasattr(self._dialogo(), "combo_metodo"))


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
        panel.boton_cobrar.setFocus()
        return panel

    def test_enter_en_cobrar_abre_el_cobro_y_arranca_la_sesion(self):
        panel = self._panel()
        cobrar = _cobro_en_efectivo(self, "control_pcs.ui.pcs_detalle")

        _enter(panel.boton_cobrar)

        cobrar.assert_called_once_with(panel, 1000.0)
        self.assertIsNotNone(self._item()["sesion"])

    def test_un_enter_apretado_no_abre_el_cobro(self):
        panel = self._panel()
        cobrar = _cobro_en_efectivo(self, "control_pcs.ui.pcs_detalle")

        _enter(panel.boton_cobrar, repetido=True)

        cobrar.assert_not_called()
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
