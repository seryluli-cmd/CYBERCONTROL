"""
tests/test_socios_bonos.py
==========================
Reportes > "PCs: Socios y Bonos" (pedido del dueño, 2026-10-24): lo que
dejaron las PCs, separado en cargas de saldo a socios y bonos del mostrador
(walk-ins, PCSTREAM y reservas de PCs), y comparado. Las dos partes suman
justo "Alquiler de PCs" de Reportes > Totales. Las pantallas se prueban sin
abrir ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QTabWidget  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    bonos_miembro_repo, miembros_repo, pcs_repo, pcstream_repo, socios_bonos_repo,
)
from database import conexion_db  # noqa: E402
from repositories import config_repo, reportes_repo, usuarios_repo  # noqa: E402
from turnos import dia_en_que_empezo_el_turno  # noqa: E402
from ui.reportes_socios_bonos import PestañaSociosYBonos, texto_de_la_diferencia  # noqa: E402
from ui.reportes_window import ReportesWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


class BaseVentasDePcs(BaseConBaseTemporal):
    """Hoy: un bono de PC ($1.500, 1 h), uno de PCSTREAM ($4.000, 2 h), una
    carga de socio con bono ($3.000, 3 h) y otra por monto ($2.000, 2 h)."""

    def setUp(self):
        super().setUp()
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.hoy = dia_en_que_empezo_el_turno(datetime.now())
        pc = pcs_repo.crear_estacion("PC01")
        stream = pcs_repo.crear_estacion(dominio.NOMBRE_PCSTREAM)
        self.venta_pc = pcs_repo.asignar_bono(pc, pcs_repo.crear_bono("1 hora", 60, 1500), self.toby,
                                              _efectivo(1500))
        pcs_repo.asignar_bono(stream, pcstream_repo.crear_bono("2 horas stream", 120, 4000), self.toby,
                              _efectivo(4000))
        socio = miembros_repo.crear_miembro("ana", "clave123", "Ana", "", "")
        self.carga_bono = miembros_repo.cargar_saldo_por_bono(
            socio, bonos_miembro_repo.crear_bono("3 horas", 180, 3000), _efectivo(3000), self.toby)["venta_id"]
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])
        miembros_repo.cargar_saldo_por_monto(socio, 2000, _efectivo(2000), self.toby)

    def comparar(self, agrupar_por="rango", desde=None, hasta=None):
        return socios_bonos_repo.comparar(desde or self.hoy, hasta or self.hoy, agrupar_por)

    def mover_venta(self, venta_id, cuando: datetime):
        with conexion_db() as conexion:
            conexion.execute("UPDATE ventas SET fecha = ? WHERE id = ?", (cuando.isoformat(timespec="seconds"), venta_id))


class TestLaCuenta(BaseVentasDePcs):
    def test_socios_y_bonos_por_separado(self):
        total = self.comparar()["total"]
        self.assertEqual(total["socios"], {"plata": 5000, "cantidad": 2, "minutos": 300,
                                           "porcentaje": 47.6, "por_hora": 1000})
        self.assertEqual(total["bonos"], {"plata": 5500, "cantidad": 2, "minutos": 180,
                                          "porcentaje": 52.4, "por_hora": 1833.33})
        self.assertEqual(total["total"], 10500)

    def test_suman_justo_alquiler_de_pcs_de_totales(self):
        [totales] = reportes_repo.resumen_por_origen(self.hoy, self.hoy)
        self.assertEqual(self.comparar()["total"]["total"], totales["pcs"])

    def test_una_carga_anulada_no_cuenta(self):
        miembros_repo.anular_carga(self.carga_bono, self.admin, "error")
        total = self.comparar()["total"]
        self.assertEqual((total["socios"]["plata"], total["socios"]["cantidad"]), (2000, 1))
        self.assertEqual(total["bonos"]["plata"], 5500)

    def test_por_dia_y_por_turno(self):
        ayer = self.hoy - timedelta(days=1)
        self.mover_venta(self.venta_pc, datetime.combine(ayer, datetime.min.time()).replace(hour=15))
        resultado = self.comparar("dia", ayer, self.hoy)
        self.assertEqual([fila["etiqueta"] for fila in resultado["filas"]],
                         [ayer.strftime("%d/%m/%Y"), self.hoy.strftime("%d/%m/%Y")])
        self.assertEqual([fila["bonos"]["plata"] for fila in resultado["filas"]], [1500, 4000])
        self.assertEqual(resultado["total"]["total"], 10500)
        self.assertEqual(len(self.comparar("turno")["filas"]), len(dominio.TURNOS))

    def test_sin_ventas(self):
        resultado = self.comparar(desde=self.hoy - timedelta(days=30), hasta=self.hoy - timedelta(days=29))
        self.assertEqual(resultado["total"]["total"], 0)
        self.assertIsNone(resultado["total"]["socios"]["por_hora"])
        self.assertEqual(texto_de_la_diferencia(resultado["total"]), "No hubo ventas de PCs en estas fechas.")


class TestPestaña(BaseVentasDePcs):
    def pestaña(self):
        pestaña = PestañaSociosYBonos()
        self.addCleanup(pestaña.deleteLater)
        return pestaña

    def test_tarjetas_barra_y_diferencia(self):
        pestaña = self.pestaña()
        self.assertEqual(pestaña.tarjeta_socios.etiqueta_plata.text(), "$ 5.000,00")
        self.assertEqual(pestaña.tarjeta_socios.etiqueta_porcentaje.text(), "47,6 %")
        self.assertEqual(pestaña.tarjeta_socios.etiqueta_detalle.text(),
                         "2 cargas · 5h 00m · $ 1.000,00 por hora")
        self.assertEqual(pestaña.tarjeta_bonos.etiqueta_plata.text(), "$ 5.500,00")
        self.assertEqual((pestaña.barra.socios, pestaña.barra.bonos), (5000, 5500))
        self.assertEqual(pestaña.etiqueta_diferencia.text(),
                         "Total PCs: $ 10.500,00. Los bonos dejaron $ 500,00 más que los socios.")
        self.assertEqual(pestaña.tabla.rowCount(), 1)

    def test_por_dia_con_fila_total(self):
        ayer = self.hoy - timedelta(days=1)
        self.mover_venta(self.venta_pc, datetime.combine(ayer, datetime.min.time()).replace(hour=15))
        pestaña = self.pestaña()
        pestaña.fecha_desde.setDate(pestaña.fecha_desde.date().addDays(-40))
        pestaña.combo_agrupar.setCurrentIndex(pestaña.combo_agrupar.findData("dia"))
        self.assertEqual(pestaña.tabla.rowCount(), 3)
        self.assertEqual(pestaña.tabla.item(2, 0).text(), "TOTAL")
        self.assertEqual(pestaña.tabla.item(2, 5).text(), "$ 10.500,00")

    def test_esta_en_reportes(self):
        ventana = ReportesWindow()
        self.addCleanup(ventana.deleteLater)
        pestañas = ventana.findChild(QTabWidget)
        self.assertIn("PCs: Socios y Bonos", [pestañas.tabText(i) for i in range(pestañas.count())])
