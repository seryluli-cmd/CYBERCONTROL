"""
tests/test_cajas_ui.py
=======================
Las pantallas de las cajas con número (sin abrir ninguna ventana, plataforma
"offscreen" de Qt): el conteo a ciegas, el ingreso que abre o cierra la caja, y
la ventana principal con el botón Cierre de Turno que titila y el cierre
forzoso. Las reglas se prueban en tests/test_cajas.py.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import relevo_repo, turnos_repo, usuarios_repo, ventas_repo  # noqa: E402
from ui import ingreso_caja  # noqa: E402
from ui.caja_window import CierreTurnoWindow  # noqa: E402
from ui.control_cierres_window import DialogoDetalleCierre  # noqa: E402
from ui.ingreso_caja import DialogoContarPlata, resolver_caja_al_entrar  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Una caja de un lunes viejo: a la hora real de la prueba ya pasó su fin y sus
# minutos de gracia (titila y toca el cierre forzoso).
_HACE_TIEMPO = datetime(2026, 1, 5, 5, 55)


class TestContarAciegas(unittest.TestCase):
    def test_primero_se_escribe_lo_contado_y_recien_despues_se_ve_la_diferencia(self):
        dialogo = DialogoContarPlata(None, "Abrir caja", "Contá el Cambio Fijo:", 50000.0, "lo que dejó la anterior")
        self.addCleanup(dialogo.deleteLater)
        self.assertTrue(dialogo.resultado.isHidden())

        dialogo.spin_monto.setValue(49500.0)
        dialogo._listo()

        self.assertFalse(dialogo.resultado.isHidden())
        self.assertIn("Tendría que haber $ 50.000 (lo que dejó la anterior)", dialogo.resultado.text())
        self.assertIn("faltan $ 500", dialogo.resultado.text())
        dialogo._confirmar()
        self.assertEqual(dialogo.contado, 49500.0)

    def test_volver_a_contar_esconde_el_resultado(self):
        dialogo = DialogoContarPlata(None, "Abrir caja", "Contá:", 100.0)
        self.addCleanup(dialogo.deleteLater)
        dialogo.spin_monto.setValue(100.0)
        dialogo._listo()
        self.assertIn("coincide", dialogo.resultado.text())

        dialogo._volver_a_contar()

        self.assertTrue(dialogo.resultado.isHidden())
        self.assertTrue(dialogo.spin_monto.isEnabled())


class TestTextoDelCierre(unittest.TestCase):
    """Cómo se ve en Control de Cierres la forma en que se cerró cada caja."""

    def _texto(self, **datos):
        from ui.control_cierres_window import texto_del_cierre
        cierre = {"fecha_cierre": "2026-01-05T14:00:00", "cierre_forzoso": False, "cerrada_en_ausencia": False,
                  "caja_numero": 1, "minutos_despues_del_fin": 0, "empleada": "Gaby", "responsable": "Lucia"}
        return texto_del_cierre({**cierre, **datos})

    def test_cada_forma_de_cerrar(self):
        self.assertEqual(self._texto(), "A horario 14:00")
        self.assertEqual(self._texto(minutos_despues_del_fin=-5), "A horario 14:00")
        self.assertEqual(self._texto(minutos_despues_del_fin=-30), "14:00 (30 min antes)")
        self.assertEqual(self._texto(minutos_despues_del_fin=12), "14:00 (12 min después)")
        self.assertEqual(self._texto(cierre_forzoso=True), "Forzoso 14:00")
        self.assertEqual(self._texto(cerrada_en_ausencia=True), "Gaby, en ausencia de Lucia · 14:00")
        self.assertEqual(self._texto(caja_numero=None, minutos_despues_del_fin=-200), "14:00")


def _contar(monto):
    """Reemplaza exec() del conteo: escribe `monto` y confirma."""
    def exec_(dialogo):
        dialogo.contado = monto
        return QDialog.Accepted
    return exec_


class TestIngresoConCaja(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.lucia = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))
        self.gaby = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Gaby", "1234", dominio.ROL_EMPLEADA))
        self.admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Dueño", "1234", dominio.ROL_ADMIN))

    def test_la_empleada_sin_caja_cuenta_el_cambio_y_entra_con_su_caja_abierta(self):
        with mock.patch.object(DialogoContarPlata, "exec", _contar(50000.0)):
            self.assertTrue(resolver_caja_al_entrar(None, self.lucia))

        estado = relevo_repo.estado_de_la_caja()
        self.assertEqual(estado["responsable"], "Lucia")

    def test_si_cancela_el_conteo_no_entra_ni_abre_caja(self):
        with mock.patch.object(DialogoContarPlata, "exec", lambda dialogo: QDialog.Rejected):
            self.assertFalse(resolver_caja_al_entrar(None, self.lucia))

        self.assertIsNone(relevo_repo.estado_de_la_caja())

    def test_el_admin_entra_directo(self):
        with mock.patch.object(DialogoContarPlata, "exec") as conteo:
            self.assertTrue(resolver_caja_al_entrar(None, self.admin))
        conteo.assert_not_called()
        self.assertIsNone(relevo_repo.estado_de_la_caja())

    def test_la_que_llega_cierra_la_caja_vencida_de_otra_y_abre_la_suya(self):
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0, _HACE_TIEMPO)

        with mock.patch.object(ingreso_caja, "confirmar", return_value=True), \
                mock.patch.object(ingreso_caja, "mostrar_info") as aviso, \
                mock.patch.object(DialogoContarPlata, "exec", _contar(50000.0)):
            self.assertTrue(resolver_caja_al_entrar(None, self.gaby))

        self.assertIn("Armá el sobre de Lucia", aviso.call_args[0][2])
        cierre = turnos_repo.listar_cierres()[0]
        self.assertTrue(cierre["cerrada_en_ausencia"])
        self.assertEqual(relevo_repo.estado_de_la_caja()["responsable"], "Gaby")


class TestVentanaPrincipalConCaja(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.lucia = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))
        self.admin = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Dueño", "1234", dominio.ROL_ADMIN))

    def _ventana(self, usuario, al_cerrar_sesion=lambda: None):
        ventana = MainWindow(usuario, al_cerrar_sesion)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)
        return ventana

    def test_se_ve_la_caja_y_el_boton_titila_en_rojo_cuando_toca_cerrar(self):
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0, _HACE_TIEMPO)
        ventana = self._ventana(self.lucia)

        self.assertEqual(ventana.etiqueta_caja.text(), "·  Caja Nº 1 · Mañana")
        ventana._parpadear()
        self.assertEqual(ventana.boton_cierre_turno.property("clase"), "alerta")
        ventana._parpadear()
        self.assertEqual(ventana.boton_cierre_turno.property("clase"), "barra")

    def test_sin_nada_que_cerrar_el_boton_no_titila(self):
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0)   # recién abierta: falta para el fin del turno
        ventana = self._ventana(self.lucia)

        ventana._parpadear()
        self.assertEqual(ventana.boton_cierre_turno.property("clase"), "barra")

    def test_el_cierre_forzoso_cierra_la_caja_y_vuelve_al_ingreso(self):
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0, _HACE_TIEMPO)
        volvio_al_ingreso = mock.Mock()
        ventana = self._ventana(self.lucia, volvio_al_ingreso)

        with mock.patch("ui.main_window.mostrar_info") as aviso:
            ventana._revisar_la_caja()

        self.assertIn("se cerró sola", aviso.call_args[0][2])
        self.assertIn("pasaron 30 minutos del fin del turno", aviso.call_args[0][2])
        volvio_al_ingreso.assert_called_once()
        self.assertTrue(turnos_repo.listar_cierres()[0]["cierre_forzoso"])

    def test_con_el_admin_adentro_la_caja_de_ella_se_cierra_pero_el_admin_sigue(self):
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0, _HACE_TIEMPO)
        volvio_al_ingreso = mock.Mock()
        ventana = self._ventana(self.admin, volvio_al_ingreso)
        self.assertEqual(ventana.etiqueta_caja.text(), "·  Caja Nº 1 de Lucia · Mañana")

        with mock.patch("ui.main_window.mostrar_info") as aviso:
            ventana._revisar_la_caja()

        self.assertIn("Lucia tiene que armar el sobre", aviso.call_args[0][2])
        volvio_al_ingreso.assert_not_called()
        self.assertEqual(ventana.etiqueta_caja.text(), "·  Sin caja abierta")

    def test_el_cierre_forzoso_espera_si_hay_un_cobro_a_medias(self):
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0, _HACE_TIEMPO)
        ventana = self._ventana(self.lucia)
        cobro = QDialog()   # una pantalla encima que no avisa que se puede cerrar sola
        self.addCleanup(cobro.deleteLater)

        with mock.patch("ui.main_window.QApplication.activeModalWidget", return_value=cobro), \
                mock.patch("ui.main_window.mostrar_info") as aviso:
            ventana._revisar_la_caja()

        aviso.assert_not_called()
        self.assertEqual(turnos_repo.listar_cierres(), [])


class TestDetalleDeUnCierreHecho(BaseConBaseTemporal):
    """Pedido del dueño (2026-10-20): "Ver Detalle" de Control de Cierres muestra
    cada cierre como la pantalla Cierre de Turno, también el forzoso. Los números
    se prueban en tests/test_cajas.py (TestUnCierreHechoSeVeComoAlCerrarlo)."""

    def setUp(self):
        super().setUp()
        self.lucia = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA))
        self.gaby = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Gaby", "1234", dominio.ROL_EMPLEADA))
        relevo_repo.abrir_caja(self.lucia["id"], 50000.0, _HACE_TIEMPO)
        with conexion_db() as conexion:
            ventas_repo.registrar_venta_sin_detalle(
                conexion, self.lucia["id"], 3000.0, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3000.0}],
                dominio.ORIGEN_ALQUILER_PCS, _HACE_TIEMPO.replace(hour=9),
            )

    def _detalle(self):
        dialogo = DialogoDetalleCierre(turnos_repo.listar_cierres()[0])
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_un_cierre_forzoso_se_ve_como_la_pantalla_cierre_de_turno(self):
        relevo_repo.cierre_forzoso_si_corresponde(_HACE_TIEMPO.replace(hour=14, minute=30))

        tarjeta = self._detalle().tarjeta

        # La misma tarjeta que la pantalla de todos los días, no una copia que se desactualice.
        cierre_de_turno = CierreTurnoWindow(self.gaby)
        self.addCleanup(cierre_de_turno.deleteLater)
        self.assertIs(type(tarjeta), type(cierre_de_turno.tarjeta))
        self.assertEqual(tarjeta.cabecera.detalle.text(), "Caja Nº 1 de Lucia · Turno Mañana")
        self.assertEqual(tarjeta.valor_fondo.text(), "$ 50.000")
        renglon = tarjeta.renglon("pcs_solo")
        self.assertEqual((renglon.efectivo.text(), renglon.digital.text()), ("$ 3.000", "$ 0"))
        self.assertEqual(tarjeta.valor_total.text(), "$ 3.000")
        self.assertEqual(tarjeta.valor_retirar.text(), "$ 3.000")
        # En vez de "Retirá el efectivo...", cómo se cerró, en rojo como en la tabla.
        self.assertIn("Se cerró sola a las 14:30", tarjeta.nota.text())
        self.assertIn("pasaron 30 minutos", tarjeta.nota.text())
        self.assertTrue(tarjeta.nota.property("alerta"))

    def test_un_cierre_comun_dice_quien_lo_cerro_en_gris(self):
        turnos_repo.cerrar_turno(self.lucia["id"], ahora_dt=_HACE_TIEMPO.replace(hour=14, minute=12))

        tarjeta = self._detalle().tarjeta

        self.assertEqual(tarjeta.nota.text(), "La cerró Lucia: 14:12 (12 min después).")
        self.assertFalse(tarjeta.nota.property("alerta"))
        self.assertEqual(tarjeta.valor_retirar.text(), "$ 3.000")

    def test_un_cierre_en_ausencia_dice_quien_lo_cerro_en_lugar_de_quien(self):
        turnos_repo.cerrar_turno(self.gaby["id"], ahora_dt=_HACE_TIEMPO.replace(hour=14, minute=5))

        tarjeta = self._detalle().tarjeta

        self.assertEqual(tarjeta.nota.text(), "La cerró Gaby, en ausencia de Lucia · 14:05.")
        self.assertTrue(tarjeta.nota.property("alerta"))


if __name__ == "__main__":
    unittest.main()
