"""
tests/test_impresiones.py
===========================
Pedido del dueño (2026-10-19):

- En su base, IMPRESIONES es el artículo código 4 (hasta ese día el programa
  buscaba el 1, y las impresiones salían en $0 en todos los resúmenes).
- Botón "Impresiones" en la barra de arriba, entre Vender y Trámites: cantidad,
  ventana de cobro de siempre, y se graba como una venta de kiosko común del
  artículo (repositories/impresiones_repo.py, ui/impresiones_window.py).
- En Caja y Cierre de Turno, Kiosko, Impresiones y Trámites separados, cada uno
  con su efectivo y digital, sin que cambie el efectivo del cajón
  (turnos_ventas_repo._aparte_por_metodo, turnos_repo._separar_de_kiosko).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QEvent, Qt  # noqa: E402
from PySide6.QtGui import QKeyEvent  # noqa: E402
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QPushButton  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import (  # noqa: E402
    articulos_repo, impresiones_repo, relevo_repo, reportes_repo, tramites_repo, turnos_repo, usuarios_repo,
    ventas_repo,
)
from repositories.config_repo import obtener_fondo_cambio  # noqa: E402
from turnos import dia_en_que_empezo_el_turno  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

EF = dominio.PAGO_EFECTIVO
DIG = dominio.PAGO_DIGITAL


def _pago(metodo, monto):
    return {"metodo": metodo, "monto": monto}


def _enter(widget):
    """Un Enter en `widget`, adonde lo manda el teclado de verdad (ver
    tests/test_enter_como_tab.py, TestDondeLlegaElEnter)."""
    for tipo in (QEvent.KeyPress, QEvent.KeyRelease):
        QApplication.sendEvent(widget, QKeyEvent(tipo, Qt.Key_Return, Qt.NoModifier, "\r"))


class _ConArticulo(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.usuario_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        self.usuario = usuarios_repo.obtener_usuario(self.usuario_id)
        articulos_repo.crear_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", None, None, 150.0, 0.0, 0)
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 100.0, 50.0, 0)

    def _vender(self, lineas, pagos):
        return ventas_repo.confirmar_venta(self.usuario_id, lineas, pagos)

    def _linea(self, codigo, cantidad, precio):
        return {"codigo": codigo, "descripcion": codigo, "cantidad": cantidad, "precio_unitario": precio}


class TestCodigoDeImpresiones(_ConArticulo):
    def test_impresiones_es_el_articulo_codigo_4(self):
        # Dato del dueño, 2026-10-19: en la base con la que trabaja es el 4.
        self.assertEqual(dominio.CODIGO_ARTICULO_IMPRESIONES, "4")

    def test_lo_vendido_del_articulo_4_sale_en_impresiones_y_el_1_ya_no(self):
        articulos_repo.crear_articulo("1", "Otro producto", None, None, 500.0, 0.0, 0)
        self._vender([self._linea("4", 2, 150.0)], [_pago(EF, 300.0)])
        self._vender([self._linea("1", 1, 500.0)], [_pago(EF, 500.0)])

        resumen = turnos_repo.resumen_turno_actual()
        hoy = dia_en_que_empezo_el_turno(datetime.now()).isoformat()
        totales = reportes_repo.resumen_por_origen(hoy, hoy)[0]

        self.assertEqual(resumen["impresiones"], 300.0)
        self.assertEqual(totales["impresiones"], 300.0)
        self.assertEqual(totales["kiosko"], 500.0)


class TestCobrarImpresiones(_ConArticulo):
    def test_graba_una_venta_de_kiosko_del_articulo_con_su_cantidad_y_su_pago(self):
        venta_id = impresiones_repo.cobrar_impresiones(self.usuario_id, 14, 150.0, [_pago(DIG, 2100.0)])

        venta, detalle, pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["origen"], dominio.ORIGEN_KIOSKO)
        self.assertEqual(venta["total"], 2100.0)
        self.assertEqual(venta["usuario_id"], self.usuario_id)
        self.assertEqual([(d["articulo_codigo"], d["cantidad"], d["precio_unitario"], d["subtotal"]) for d in detalle],
                         [(dominio.CODIGO_ARTICULO_IMPRESIONES, 14, 150.0, 2100.0)])
        self.assertEqual([(p["metodo"], p["monto"]) for p in pagos], [(DIG, 2100.0)])
        # Descuenta stock como cualquier venta (puede quedar negativo, a propósito).
        self.assertEqual(articulos_repo.buscar_por_codigo(dominio.CODIGO_ARTICULO_IMPRESIONES)["stock"], -14)

    def test_entra_en_la_caja_abierta(self):
        caja = relevo_repo.abrir_caja(self.usuario_id, obtener_fondo_cambio())

        venta_id = impresiones_repo.cobrar_impresiones(self.usuario_id, 2, 150.0, [_pago(EF, 300.0)])

        with conexion_db() as conexion:
            fila = conexion.execute("SELECT caja_id FROM ventas_caja WHERE venta_id = ?", (venta_id,)).fetchone()
        self.assertEqual(fila["caja_id"], caja["caja_numero"])
        self.assertEqual(turnos_repo.resumen_turno_actual()["impresiones_efectivo"], 300.0)

    def test_sin_el_articulo_no_graba_nada(self):
        with conexion_db() as conexion:
            conexion.execute("DELETE FROM articulos WHERE codigo = ?", (dominio.CODIGO_ARTICULO_IMPRESIONES,))

        self.assertIsNone(impresiones_repo.articulo_impresiones())
        with self.assertRaises(ValueError) as error:
            impresiones_repo.cobrar_impresiones(self.usuario_id, 1, 150.0, [_pago(EF, 150.0)])
        self.assertIn("código 4", str(error.exception))
        self.assertEqual(ventas_repo.listar_ventas_recientes(), [])

    def test_si_el_precio_cambio_mientras_se_cobraba_no_graba_nada(self):
        articulos_repo.modificar_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", None, None,
                                          200.0, 0.0, 0)

        with self.assertRaises(ValueError):
            impresiones_repo.cobrar_impresiones(self.usuario_id, 2, 150.0, [_pago(EF, 300.0)])
        self.assertEqual(ventas_repo.listar_ventas_recientes(), [])

    def test_rechaza_cantidades_imposibles_y_pagos_que_no_cubren(self):
        for cantidad in (0, -3, impresiones_repo.CANTIDAD_MAXIMA + 1):
            with self.assertRaises(ValueError, msg=cantidad):
                impresiones_repo.cobrar_impresiones(self.usuario_id, cantidad, 150.0, [_pago(EF, 1_000_000.0)])
        with self.assertRaises(ValueError):
            impresiones_repo.cobrar_impresiones(self.usuario_id, 3, 150.0, [_pago(EF, 300.0)])
        self.assertEqual(ventas_repo.listar_ventas_recientes(), [])

    def test_sin_precio_no_cobra(self):
        articulos_repo.modificar_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "IMPRESIONES", None, None,
                                          0.0, 0.0, 0)

        with self.assertRaises(ValueError):
            impresiones_repo.cobrar_impresiones(self.usuario_id, 1, 0.0, [])


class TestKioskoSinImpresionesEnLaCaja(_ConArticulo):
    """Lo que muestran Caja y Cierre de Turno (eligió el dueño, 2026-10-19):
    Kiosko, Impresiones y Trámites, cada uno con su ef. + dig., y los tres suman
    lo que se graba como Kiosko en el cierre."""

    def _suman_kiosko(self, resumen):
        for metodo in ("efectivo", "digital"):
            partes = (resumen[f"kiosko_solo_{metodo}"] + resumen[f"impresiones_{metodo}"]
                      + resumen[f"tramites_{metodo}"])
            self.assertAlmostEqual(partes, resumen[f"kiosko_{metodo}"], places=2, msg=metodo)

    def test_impresiones_cobradas_solas_quedan_con_su_medio_exacto(self):
        impresiones_repo.cobrar_impresiones(self.usuario_id, 4, 150.0, [_pago(DIG, 600.0)])
        self._vender([self._linea("COD9", 1, 100.0)], [_pago(EF, 100.0)])

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["impresiones_efectivo"], resumen["impresiones_digital"]), (0.0, 600.0))
        self.assertEqual((resumen["kiosko_solo_efectivo"], resumen["kiosko_solo_digital"]), (100.0, 0.0))
        self._suman_kiosko(resumen)

    def test_en_un_carrito_pagado_mitad_y_mitad_se_reparten_en_proporcion(self):
        # $300 de impresiones + $100 de otra cosa, pagado $200 ef. + $200 dig.
        self._vender([self._linea("4", 2, 150.0), self._linea("COD9", 1, 100.0)],
                     [_pago(EF, 200.0), _pago(DIG, 200.0)])

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["impresiones_efectivo"], resumen["impresiones_digital"]), (150.0, 150.0))
        self.assertEqual((resumen["kiosko_solo_efectivo"], resumen["kiosko_solo_digital"]), (50.0, 50.0))
        self.assertEqual(resumen["impresiones"], 300.0)
        self._suman_kiosko(resumen)

    def test_los_centavos_que_sobran_del_reparto_no_descuadran_kiosko(self):
        # $100 de impresiones en un carrito de $300 pagado $100 ef. + $200 dig.:
        # un tercio de cada pago (33,333...) no se puede escribir en centavos.
        articulos_repo.modificar_articulo("4", "IMPRESIONES", None, None, 100.0, 0.0, 0)
        self._vender([self._linea("4", 1, 100.0), self._linea("COD9", 2, 100.0)],
                     [_pago(EF, 100.0), _pago(DIG, 200.0)])

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["impresiones_efectivo"], resumen["impresiones_digital"]), (33.33, 66.67))
        self.assertEqual((resumen["kiosko_solo_efectivo"], resumen["kiosko_solo_digital"]), (66.67, 133.33))
        self._suman_kiosko(resumen)

    def test_los_tramites_salen_de_kiosko_con_su_pago(self):
        tramite_id = tramites_repo.crear_tramite("Boleta de luz")
        tramites_repo.registrar_tramite(self.usuario_id, tramite_id, 2500.0, [_pago(EF, 1000.0), _pago(DIG, 1500.0)])
        self._vender([self._linea("COD9", 1, 100.0)], [_pago(DIG, 100.0)])

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["tramites_efectivo"], resumen["tramites_digital"]), (1000.0, 1500.0))
        self.assertEqual((resumen["kiosko_solo_efectivo"], resumen["kiosko_solo_digital"]), (0.0, 100.0))
        self.assertEqual(resumen["tramites"], 2500.0)
        self._suman_kiosko(resumen)

    def test_el_efectivo_del_cajon_y_el_total_no_cambian(self):
        impresiones_repo.cobrar_impresiones(self.usuario_id, 2, 150.0, [_pago(EF, 300.0)])
        self._vender([self._linea("COD9", 1, 100.0)], [_pago(DIG, 100.0)])

        resumen = turnos_repo.resumen_turno_actual()
        cierre = turnos_repo.cerrar_turno(self.usuario_id)

        self.assertEqual(resumen["ventas_efectivo"], 300.0)
        self.assertEqual(resumen["ventas_total"], 400.0)
        # Lo que se graba en el cierre sigue siendo Kiosko entero.
        self.assertEqual((cierre["kiosko_efectivo"], cierre["kiosko_digital"]), (300.0, 100.0))
        self.assertEqual(cierre["monto_a_retirar"], 300.0)

    def test_una_venta_anulada_no_cuenta(self):
        venta_id = impresiones_repo.cobrar_impresiones(self.usuario_id, 2, 150.0, [_pago(EF, 300.0)])
        admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        ventas_repo.anular_venta(venta_id, admin_id, "se cobró de más")

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["impresiones_efectivo"], resumen["impresiones_digital"]), (0.0, 0.0))
        self.assertEqual(resumen["kiosko_solo_efectivo"], 0.0)


class TestPantallaDeImpresiones(_ConArticulo):
    def _dialogo(self):
        from ui.impresiones_window import DialogoImpresiones

        dialogo = DialogoImpresiones(self.usuario, impresiones_repo.articulo_impresiones())
        self.addCleanup(dialogo.deleteLater)
        dialogo.show()
        QApplication.processEvents()
        return dialogo

    def _cobro_justo(self, aceptar=True):
        """Reemplaza la ventana de cobro (modal) por un pago justo en efectivo."""
        llamados = []

        class _Pago:
            def __init__(self, _parent, total):
                llamados.append(total)
                self.pagos = [_pago(EF, total)]
                self.vuelto = 0.0

            def exec(self):
                return aceptar

        mock.patch("ui.impresiones_window.DialogoPago", _Pago).start()
        mock.patch("ui.impresiones_window.mostrar_info").start()
        self.addCleanup(mock.patch.stopall)
        return llamados

    def test_arranca_en_una_y_muestra_el_total(self):
        dialogo = self._dialogo()

        self.assertEqual(dialogo.spin_cantidad.value(), 1)
        self.assertEqual(dialogo.etiqueta_total.text(), "TOTAL: $ 150")
        dialogo.spin_cantidad.setValue(14)
        self.assertEqual(dialogo.etiqueta_total.text(), "TOTAL: $ 2.100")

    def test_enter_en_la_cantidad_abre_el_cobro_y_graba_la_venta(self):
        llamados = self._cobro_justo()
        dialogo = self._dialogo()
        dialogo.spin_cantidad.setValue(14)
        dialogo.spin_cantidad.setFocus()

        _enter(dialogo.spin_cantidad)

        self.assertEqual(llamados, [2100.0])
        self.assertEqual(dialogo.result(), QDialog.Accepted)
        venta = ventas_repo.listar_ventas_recientes()[0]
        _, detalle, _ = ventas_repo.buscar_venta(venta["id"])
        self.assertEqual([(d["articulo_codigo"], d["cantidad"]) for d in detalle],
                         [(dominio.CODIGO_ARTICULO_IMPRESIONES, 14)])

    def test_si_se_cancela_el_cobro_no_graba_nada(self):
        self._cobro_justo(aceptar=False)
        dialogo = self._dialogo()

        dialogo._cobrar()

        self.assertEqual(ventas_repo.listar_ventas_recientes(), [])
        self.assertNotEqual(dialogo.result(), QDialog.Accepted)


class TestBotonEnLaBarra(_ConArticulo):
    def _ventana(self, usuario):
        from ui.main_window import MainWindow

        ventana = MainWindow(usuario, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)
        return ventana

    def test_va_entre_vender_y_tramites_con_la_tecla_de_la_barra(self):
        ventana = self._ventana(self.usuario)
        barra = ventana.findChild(QFrame, "encabezadoInicio")
        botones = [boton for boton in barra.findChildren(QPushButton)]
        textos = [boton.text() for boton in botones]

        i = textos.index("🖨️  IMPRESIONES")
        self.assertEqual(textos[i - 1], "🛒  VENDER")
        self.assertEqual(textos[i + 1], "📄  TRÁMITES")
        self.assertEqual(botones[i].property("clase"), "barra")

    def test_abre_la_ventana_con_el_articulo(self):
        ventana = self._ventana(self.usuario)

        with mock.patch("ui.main_window.DialogoImpresiones") as dialogo:
            ventana._abrir_impresiones()

        usuario, articulo, padre = dialogo.call_args.args
        self.assertEqual(articulo["codigo"], dominio.CODIGO_ARTICULO_IMPRESIONES)
        self.assertIs(padre, ventana)
        dialogo.return_value.exec.assert_called_once()

    def test_sin_el_articulo_avisa_y_no_abre_nada(self):
        with conexion_db() as conexion:
            conexion.execute("DELETE FROM articulos WHERE codigo = ?", (dominio.CODIGO_ARTICULO_IMPRESIONES,))
        ventana = self._ventana(self.usuario)

        with mock.patch("ui.main_window.DialogoImpresiones") as dialogo, \
                mock.patch("ui.main_window.mostrar_error") as mostrar_error:
            ventana._abrir_impresiones()

        dialogo.assert_not_called()
        self.assertIn("código 4", mostrar_error.call_args.args[2])


class TestCajaMuestraImpresionesAparte(_ConArticulo):
    def test_caja_muestra_kiosko_impresiones_y_tramites_por_separado(self):
        from ui.caja_window import CajaWindow

        impresiones_repo.cobrar_impresiones(self.usuario_id, 2, 150.0, [_pago(DIG, 300.0)])
        self._vender([self._linea("COD9", 1, 100.0)], [_pago(EF, 100.0)])

        ventana = CajaWindow()
        self.addCleanup(ventana.deleteLater)

        montos = {clave: (ventana.renglon(clave).efectivo.text(), ventana.renglon(clave).digital.text())
                  for clave in ("kiosko_solo", "impresiones", "tramites")}
        self.assertEqual(montos, {"kiosko_solo": ("$ 100", "$ 0"), "impresiones": ("$ 0", "$ 300"),
                                  "tramites": ("$ 0", "$ 0")})
        # La Caja Actual son los $100 en efectivo (sin el cambio): separar no cambia nada.
        self.assertEqual(ventana.valor_actual.text(), "$ 100")


if __name__ == "__main__":
    unittest.main()
