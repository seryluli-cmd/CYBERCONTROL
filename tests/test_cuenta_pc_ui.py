"""
tests/test_cuenta_pc_ui.py
==========================
Las pantallas de la Cuenta de la PC (pedido del dueño, 2026-10-25): la PC que
debe titila con un borde fucsia y dice "DEBE", el panel muestra cuánto y deja
cobrarlo, VENDER anota el carrito en la cuenta de una PC. Con Qt "offscreen",
sin abrir ventanas. La lógica está en tests/test_cuenta_pc.py.
"""

import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from control_pcs.repositories import cuentas_pc_repo, pcs_repo  # noqa: E402
from control_pcs.ui import cuenta_pc_dialogos  # noqa: E402
from control_pcs.ui.cuenta_pc_dialogos import DialogoCuentaPc  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from ui import ventas_window  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

_EFECTIVO = dominio.PAGO_EFECTIVO
_PANCHO = {"codigo": "PANCHO", "descripcion": "Pancho", "cantidad": 1, "precio_unitario": 1200.0}


class BasePantallasCuenta(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA))
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.bono = pcs_repo.crear_bono("1 hora", 60, 1100)
        articulos_repo.crear_articulo("PANCHO", "Pancho", None, None, 1200.0, 500.0, 0)
        for pc in (self.pc1, self.pc2):
            pcs_repo.asignar_bono(pc, self.bono, self.ana["id"], [{"metodo": _EFECTIVO, "monto": 1100}])

    def grilla(self):
        grilla = PanelControlPcs(self.ana)
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def fila_de(self, grilla, nombre):
        return next(fila for fila in range(grilla.mosaico.count()) if grilla.mosaico.ficha(fila).nombre == nombre)


class TestMosaicoYPanel(BasePantallasCuenta):
    def setUp(self):
        super().setUp()
        cuentas_pc_repo.anotar_articulos(self.pc1, [_PANCHO], self.ana["id"], nombre="Pedro")

    def test_la_pc_que_debe_lo_dice_y_titila(self):
        grilla = self.grilla()
        fila = self.fila_de(grilla, "PC1")
        ficha = grilla.mosaico.ficha(fila)
        self.assertEqual(ficha.debe, "$ 1.200")
        self.assertIn("Debe $ 1.200 (Pedro)", ficha.estado)
        self.assertEqual(grilla.mosaico.ficha(self.fila_de(grilla, "PC2")).debe, "")

        self.assertTrue(grilla.mosaico.deuda_visible(fila))
        grilla._alternar_parpadeo()
        self.assertFalse(grilla.mosaico.deuda_visible(fila))
        grilla._alternar_parpadeo()
        self.assertTrue(grilla.mosaico.deuda_visible(fila))

    def test_el_panel_muestra_lo_que_debe_y_el_boton_para_cobrarlo(self):
        grilla = self.grilla()
        panel = grilla.panel_detalle
        grilla.mosaico.elegir(self.fila_de(grilla, "PC1"))
        self.assertFalse(panel.etiqueta_cuenta.isHidden())
        self.assertIn("Pedro: $ 1.200", panel.etiqueta_cuenta.text())
        self.assertEqual(panel.boton_cuenta.text(), "Cobrar cuenta $ 1.200")
        self.assertTrue(panel.boton_bono_a_cuenta.isEnabled())

        grilla.mosaico.elegir(self.fila_de(grilla, "PC2"))
        self.assertTrue(panel.etiqueta_cuenta.isHidden())
        self.assertTrue(panel.boton_cuenta.isHidden())

    def test_agregar_bono_a_cuenta_le_suma_el_tiempo(self):
        grilla = self.grilla()
        grilla.mosaico.elegir(self.fila_de(grilla, "PC1"))
        with mock.patch("control_pcs.ui.pcs_detalle.confirmar", return_value=True), \
                mock.patch("control_pcs.ui.pcs_detalle.mostrar_info"):
            grilla.panel_detalle._agregar_bono_a_cuenta()
        self.assertEqual(cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]["total"], 2300.0)


class TestVentanaDeLaCuenta(BasePantallasCuenta):
    def setUp(self):
        super().setUp()
        cuentas_pc_repo.anotar_articulos(self.pc1, [_PANCHO], self.ana["id"], nombre="Pedro")
        self.dialogo = DialogoCuentaPc(self.ana, pcs_repo.obtener_estacion(self.pc1))
        self.addCleanup(self.dialogo.deleteLater)

    def test_muestra_los_renglones_y_el_total(self):
        self.assertEqual(self.dialogo.tabla.rowCount(), 1)
        self.assertEqual(self.dialogo.tabla.item(0, 1).text(), "Pancho")
        self.assertEqual(self.dialogo.boton_cobrar.text(), "Cobrar $ 1.200")
        # Quitar y dar por perdida son del Admin.
        self.assertTrue(self.dialogo.boton_quitar.isHidden())
        self.assertTrue(self.dialogo.boton_perdida.isHidden())

    def test_cobrar_usa_la_ventana_de_cobro_y_la_pc_deja_de_deber(self):
        with mock.patch.object(cuenta_pc_dialogos.dialogo_pago, "cobrar",
                               return_value=[{"metodo": _EFECTIVO, "monto": 1200.0}]) as cobro, \
                mock.patch("control_pcs.ui.cuenta_pc_dialogos.mostrar_info"):
            self.dialogo._cobrar()
        cobro.assert_called_once_with(self.dialogo, 1200.0)
        self.assertTrue(self.dialogo.cobro_hecho)
        self.assertEqual(cuentas_pc_repo.cuentas_de_la_estacion(self.pc1), [])

    def test_si_se_cancela_el_cobro_no_pasa_nada(self):
        with mock.patch.object(cuenta_pc_dialogos.dialogo_pago, "cobrar", return_value=None):
            self.dialogo._cobrar()
        self.assertFalse(self.dialogo.cobro_hecho)
        self.assertEqual(cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]["total"], 1200.0)


class TestVenderACuenta(BasePantallasCuenta):
    def test_el_carrito_se_anota_en_la_pc_elegida_y_se_vacia(self):
        ventana = ventas_window.VentasWindow(self.ana)
        self.addCleanup(ventana.deleteLater)
        ventana.carrito = [dict(_PANCHO)]
        item = next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.pc2)

        class _Elegir:
            def __init__(self, *_args):
                self.item = item

            def exec(self):
                return True

        with mock.patch.object(ventas_window, "DialogoElegirPc", _Elegir), \
                mock.patch.object(cuenta_pc_dialogos.QInputDialog, "getText", return_value=("Lucas", True)), \
                mock.patch("ui.ventas_window.mostrar_info"):
            ventana._anotar_a_cuenta()

        self.assertEqual(ventana.carrito, [])
        cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc2)[0]
        self.assertEqual((cuenta["nombre"], cuenta["total"]), ("Lucas", 1200.0))

    def test_si_pasa_el_tope_y_la_regla_pide_clave_la_pide(self):
        admin = usuarios_repo.crear_usuario("Jefe", "clave-jefe", dominio.ROL_ADMIN)
        cuentas_pc_repo.guardar_reglas(admin, 1000, dominio.TOPE_CUENTA_CON_CLAVE_ADMIN, True)
        item = next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.pc2)

        def autorizar(dialogo):
            dialogo.autoriza = {"nombre": "Jefe", "clave": "clave-jefe"}
            return True

        with mock.patch.object(cuenta_pc_dialogos.QInputDialog, "getText", return_value=("", True)), \
                mock.patch.object(cuenta_pc_dialogos.DialogoClaveAdmin, "exec", autorizar):
            resultado = cuenta_pc_dialogos.anotar_en_la_cuenta(
                None, item, lambda **datos: cuentas_pc_repo.anotar_articulos(self.pc2, [_PANCHO], self.ana["id"], **datos)
            )
        self.assertEqual(resultado["debe"], 1200.0)


class TestCobrarAntesDelCierre(BasePantallasCuenta):
    def setUp(self):
        super().setUp()
        cuentas_pc_repo.anotar_articulos(self.pc1, [_PANCHO], self.ana["id"], nombre="Pedro")

    def test_el_cartel_lista_lo_fiado_y_cobrar_lo_saca(self):
        cartel = cuenta_pc_dialogos.DialogoCobrarAntesDelCierre(
            self.ana, cuenta_pc_dialogos.DialogoCobrarAntesDelCierre.CIERRE)
        self.addCleanup(cartel.deleteLater)
        self.assertEqual([(c["estacion"], c["debe"]) for c in cartel.cuentas], [("PC1", 1200.0)])
        self.assertTrue(cartel.se_puede_cerrar_sola())  # el cierre forzoso no lo espera

        def cobrar_en_la_ventana(dialogo):
            cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]
            cuentas_pc_repo.cobrar([cuenta["id"]], self.ana["id"], [{"metodo": _EFECTIVO, "monto": 1200.0}])
            return True

        with mock.patch.object(cuenta_pc_dialogos.DialogoCuentaPc, "exec", cobrar_en_la_ventana):
            cartel._cobrar(cartel.cuentas[0])
        self.assertEqual(cartel.cuentas, [])

    def test_cerrar_igual_deja_el_fiado_en_el_cierre(self):
        from ui import caja_window

        class _Pregunta:
            CIERRE = "CIERRE"

            def __init__(self, *_args):
                self.cerrar_igual = True

            def exec(self):
                return True

        ventana = caja_window.CierreTurnoWindow(self.ana)
        self.addCleanup(ventana.deleteLater)
        self.assertFalse(ventana.aviso_cuentas.isHidden())
        with mock.patch.object(caja_window, "DialogoCobrarAntesDelCierre", _Pregunta), \
                mock.patch("ui.caja_window.mostrar_info") as aviso:
            ventana._cerrar_turno()
        self.assertTrue(ventana.turno_cerrado)
        self.assertIn("fiado sin cobrar", aviso.call_args[0][2])

    def test_faltando_15_minutos_titilan_mas_rapido(self):
        grilla = self.grilla()
        fila = self.fila_de(grilla, "PC1")
        self.assertEqual((grilla._filas_que_deben, grilla._filas_que_deben_ya), ([fila], []))
        grilla.marcar_cuentas_urgentes({self.pc1})
        self.assertEqual((grilla._filas_que_deben, grilla._filas_que_deben_ya), ([], [fila]))
        grilla._alternar_parpadeo_rapido()
        self.assertFalse(grilla.mosaico.deuda_visible(fila))
        grilla.marcar_cuentas_urgentes(set())
        self.assertEqual(grilla._filas_que_deben_ya, [])


class TestTiempoDeSocioDesdeElPanel(BasePantallasCuenta):
    def test_a_un_socio_le_anota_tiempo_de_socio(self):
        from control_pcs.repositories import bonos_miembro_repo, miembros_repo
        from control_pcs.ui import pcs_detalle
        socio = miembros_repo.crear_miembro("rodri", "clave123", "Rodrigo", "30111222", "1155554444")
        miembros_repo.cargar_saldo_por_bono(socio, bonos_miembro_repo.crear_bono("1 h", 60, 1000),
                                            [{"metodo": _EFECTIVO, "monto": 1000}], self.ana["id"])
        pc3 = pcs_repo.crear_estacion("PC3")
        miembros_repo.abrir_estacion_por_miembro(pc3, "rodri", "clave123")
        bono_socio = bonos_miembro_repo.crear_bono("2 h socio", 120, 1500)
        grilla = self.grilla()
        grilla.mosaico.elegir(self.fila_de(grilla, "PC3"))
        self.assertTrue(grilla.panel_detalle.boton_bono_a_cuenta.isEnabled())

        class _Elegir:
            def __init__(self, *_args):
                self.bono_id, self.monto = bono_socio, None

            def exec(self):
                return True

        with mock.patch.object(pcs_detalle, "DialogoTiempoSocio", _Elegir), \
                mock.patch("control_pcs.ui.pcs_detalle.mostrar_info"):
            grilla.panel_detalle._agregar_bono_a_cuenta()
        renglon = cuentas_pc_repo.cuentas_de_la_estacion(pc3)[0]["renglones"][0]
        self.assertEqual((renglon["tipo"], renglon["subtotal"]), (dominio.ITEM_CUENTA_TIEMPO_SOCIO, 1500.0))
