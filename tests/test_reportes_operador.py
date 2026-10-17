"""
tests/test_reportes_operador.py
=================================
Reportes > "Por Operador" (pedido del dueño, 2026-10-17): cuánto vendió cada
usuario en un rango de fechas y sus ventas una por una con fecha y hora
(reportes_repo.resumen_por_operador / ventas_de_operador y la pestaña de
ui/reportes_operador.py), más el día en que empezó el turno de una venta de
madrugada (turnos.dia_en_que_empezo_el_turno), que decide si se ve como
"Noche" o "Domingo T2". La pantalla se prueba con Qt "offscreen".

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import articulos_repo, reportes_repo, tramites_repo, usuarios_repo, ventas_repo  # noqa: E402
from turnos import dia_en_que_empezo_el_turno, etiqueta_turno  # noqa: E402
from ui.reportes_operador import PestañaPorOperador  # noqa: E402
from ui.reportes_window import ReportesWindow  # noqa: E402
from ui.utils import formato_fecha_hora  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

_EFECTIVO = dominio.PAGO_EFECTIVO
_DIGITAL = dominio.PAGO_DIGITAL


class _ConVentas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.toby_id = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.nair_id = usuarios_repo.crear_usuario("Nair", "1234", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 0)

    def _vender(self, usuario_id, cantidad, pagos, cuando):
        """Una venta de kiosko de `cantidad` Cocas, grabada en el momento `cuando`."""
        venta_id = ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": cantidad, "precio_unitario": 1000.0}],
            pagos,
        )
        self._mover(venta_id, cuando)
        return venta_id

    @staticmethod
    def _mover(venta_id, cuando):
        with conexion_db() as conexion:
            conexion.execute(
                "UPDATE ventas SET fecha = ? WHERE id = ?",
                (cuando.isoformat(timespec="microseconds"), venta_id),
            )


class TestResumenPorOperador(_ConVentas):
    def test_suma_efectivo_digital_y_total_de_cada_operador(self):
        self._vender(self.toby_id, 2, [{"metodo": _EFECTIVO, "monto": 2000.0}], datetime(2026, 10, 16, 9, 0))
        self._vender(self.toby_id, 3, [{"metodo": _EFECTIVO, "monto": 1000.0},
                                       {"metodo": _DIGITAL, "monto": 2000.0}], datetime(2026, 10, 16, 10, 0))
        self._vender(self.nair_id, 1, [{"metodo": _DIGITAL, "monto": 1000.0}], datetime(2026, 10, 16, 15, 0))

        filas = reportes_repo.resumen_por_operador("2026-10-16", "2026-10-16")

        self.assertEqual([f["nombre"] for f in filas], ["TOBY", "Nair"])  # de mayor a menor total
        toby = filas[0]
        self.assertEqual(toby["cantidad_ventas"], 2)
        self.assertEqual(toby["efectivo"], 3000.0)
        self.assertEqual(toby["digital"], 2000.0)
        self.assertEqual(toby["total"], 5000.0)
        self.assertEqual(filas[1]["total"], 1000.0)

    def test_las_anuladas_se_cuentan_aparte_y_no_suman(self):
        self._vender(self.toby_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], datetime(2026, 10, 16, 9, 0))
        anulada = self._vender(self.toby_id, 5, [{"metodo": _EFECTIVO, "monto": 5000.0}], datetime(2026, 10, 16, 9, 30))
        ventas_repo.anular_venta(anulada, self.admin_id, "se equivocó")

        toby = reportes_repo.resumen_por_operador("2026-10-16", "2026-10-16")[0]

        self.assertEqual(toby["cantidad_ventas"], 1)
        self.assertEqual(toby["cantidad_anuladas"], 1)
        self.assertEqual(toby["total"], 1000.0)
        self.assertEqual(toby["efectivo"], 1000.0)

    def test_solo_cuenta_las_ventas_del_rango(self):
        # El día 16 va del 16 a las 06:00 al 17 a las 06:00 (días del local): la
        # madrugada del 16 es la Noche del 15, y la del 17 es la Noche del 16.
        self._vender(self.toby_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], datetime(2026, 10, 16, 5, 59))
        self._vender(self.toby_id, 2, [{"metodo": _EFECTIVO, "monto": 2000.0}], datetime(2026, 10, 16, 6, 0))
        self._vender(self.nair_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], datetime(2026, 10, 17, 1, 0))
        self._vender(self.nair_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], datetime(2026, 10, 17, 6, 0))

        filas = reportes_repo.resumen_por_operador("2026-10-16", "2026-10-16")

        self.assertEqual([(f["nombre"], f["total"]) for f in filas], [("TOBY", 2000.0), ("Nair", 1000.0)])


class TestVentasDeOperador(_ConVentas):
    def test_trae_cada_venta_con_su_hora_concepto_y_estado(self):
        self._vender(self.toby_id, 2, [{"metodo": _EFECTIVO, "monto": 2000.0}], datetime(2026, 10, 16, 9, 15))
        tramite_id = tramites_repo.crear_tramite("Boleta de luz")
        venta_tramite = tramites_repo.registrar_tramite(
            self.toby_id, tramite_id, 500.0, [{"metodo": _DIGITAL, "monto": 500.0}]
        )
        self._mover(venta_tramite, datetime(2026, 10, 16, 8, 0))
        anulada = self._vender(self.toby_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], datetime(2026, 10, 16, 11, 0))
        ventas_repo.anular_venta(anulada, self.admin_id, "prueba")
        self._vender(self.nair_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], datetime(2026, 10, 16, 10, 0))

        ventas = reportes_repo.ventas_de_operador(self.toby_id, "2026-10-16", "2026-10-16")

        self.assertEqual([v["concepto"] for v in ventas], ["Trámite: Boleta de luz", "2 x Coca 500", "1 x Coca 500"])
        self.assertEqual(ventas[0]["digital"], 500.0)
        self.assertEqual(ventas[1]["efectivo"], 2000.0)
        self.assertEqual(ventas[2]["estado"], dominio.VENTA_ANULADA)
        self.assertTrue(ventas[1]["fecha"].startswith("2026-10-16T09:15"))


class TestDiaEnQueEmpezoElTurno(unittest.TestCase):
    def test_de_madrugada_es_el_turno_noche_del_dia_anterior(self):
        lunes_1am = datetime(2026, 10, 19, 1, 0)      # el domingo 18 a la noche
        domingo_3am = datetime(2026, 10, 18, 3, 0)    # el sábado 17 a la noche

        self.assertEqual(dia_en_que_empezo_el_turno(lunes_1am), date(2026, 10, 18))
        self.assertEqual(etiqueta_turno(dia_en_que_empezo_el_turno(lunes_1am), dominio.TURNO_NOCHE), "Domingo T2")
        self.assertEqual(etiqueta_turno(dia_en_que_empezo_el_turno(domingo_3am), dominio.TURNO_NOCHE), "Noche")

    def test_desde_las_6_es_el_mismo_dia(self):
        self.assertEqual(dia_en_que_empezo_el_turno(datetime(2026, 10, 18, 6, 0)), date(2026, 10, 18))
        self.assertEqual(dia_en_que_empezo_el_turno(datetime(2026, 10, 16, 23, 30)), date(2026, 10, 16))


class TestFormatoFechaHora(unittest.TestCase):
    def test_muestra_dia_mes_anio_hora_y_minutos(self):
        self.assertEqual(formato_fecha_hora("2026-10-16T22:13:28.123456"), "16/10/2026 22:13")
        self.assertEqual(formato_fecha_hora("2026-10-16T09:05:00"), "16/10/2026 09:05")

    def test_un_dato_raro_se_muestra_tal_cual(self):
        self.assertEqual(formato_fecha_hora("cualquier cosa"), "cualquier cosa")


class TestPestañaPorOperador(_ConVentas):
    def test_reportes_tiene_la_pestaña_por_operador(self):
        ventana = ReportesWindow()
        self.addCleanup(ventana.deleteLater)
        from PySide6.QtWidgets import QTabWidget
        pestañas = ventana.findChild(QTabWidget)

        self.assertIn("Por Operador", [pestañas.tabText(i) for i in range(pestañas.count())])

    def test_elegir_un_operador_muestra_sus_ventas_con_la_hora(self):
        ahora = datetime.now().replace(hour=10, minute=30, second=0, microsecond=0)
        self._vender(self.toby_id, 2, [{"metodo": _EFECTIVO, "monto": 2000.0}], ahora)
        self._vender(self.nair_id, 1, [{"metodo": _DIGITAL, "monto": 1000.0}], ahora.replace(minute=45))
        anulada = self._vender(self.nair_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], ahora.replace(minute=50))
        ventas_repo.anular_venta(anulada, self.admin_id, "prueba")

        pestaña = PestañaPorOperador()  # arranca en "hoy"
        self.addCleanup(pestaña.deleteLater)

        operadores = [pestaña.tabla_operadores.item(f, 0).text() for f in range(pestaña.tabla_operadores.rowCount())]
        self.assertEqual(operadores, ["TOBY", "Nair"])
        # Arranca con el primero elegido.
        self.assertEqual(pestaña.tabla_ventas.rowCount(), 1)
        self.assertEqual(pestaña.tabla_ventas.item(0, 0).text(), ahora.strftime("%d/%m/%Y 10:30"))
        self.assertEqual(pestaña.tabla_ventas.item(0, 3).text(), "2 x Coca 500")

        pestaña.tabla_operadores.selectRow(1)

        self.assertIn("Nair", pestaña.etiqueta_detalle.text())
        self.assertEqual(pestaña.tabla_ventas.rowCount(), 2)
        self.assertEqual(pestaña.tabla_ventas.item(1, 7).text(), "ANULADA")
        self.assertEqual(pestaña.tabla_ventas.item(1, 0).foreground().color().name(), "#c62828")

    def test_buscar_de_nuevo_conserva_el_operador_elegido(self):
        ahora = datetime.now().replace(hour=10, minute=0, second=0, microsecond=0)
        self._vender(self.toby_id, 2, [{"metodo": _EFECTIVO, "monto": 2000.0}], ahora)
        self._vender(self.nair_id, 1, [{"metodo": _EFECTIVO, "monto": 1000.0}], ahora)
        pestaña = PestañaPorOperador()
        self.addCleanup(pestaña.deleteLater)
        pestaña.tabla_operadores.selectRow(1)

        pestaña._buscar()

        self.assertIn("Nair", pestaña.etiqueta_detalle.text())

    def test_sin_ventas_lo_dice(self):
        pestaña = PestañaPorOperador()
        self.addCleanup(pestaña.deleteLater)

        self.assertEqual(pestaña.tabla_operadores.rowCount(), 0)
        self.assertEqual(pestaña.etiqueta_detalle.text(), "No hay ventas en esas fechas.")


if __name__ == "__main__":
    unittest.main()
