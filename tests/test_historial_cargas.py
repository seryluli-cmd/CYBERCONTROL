"""
tests/test_historial_cargas.py
==============================
HISTORIAL DE CARGAS (botón de Miembros, al lado de Cargar Saldo; pedido del
dueño, 2026-10-24): cada carga de saldo con el socio, el tiempo, la plata y
cómo se pagó, quién la cargó y la fecha y hora. Solo las cargas (no los
consumos, reintegros ni los saldos importados); las anuladas salen pero no
suman. Las pantallas se prueban sin abrir ninguna ventana (plataforma
"offscreen" de Qt).
"""

import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import bonos_miembro_repo, historial_cargas_repo, miembros_repo, pcs_repo  # noqa: E402
from control_pcs.ui.miembros_historial_cargas import (  # noqa: E402
    COLUMNA_ESTADO, COLUMNA_SOCIO, VentanaHistorialCargas,
)
from control_pcs.ui.miembros_window import MiembrosWindow  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import config_repo, relevo_repo, usuarios_repo  # noqa: E402
from turnos import dia_en_que_empezo_el_turno  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3000}]


class BaseHistorial(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.ana = miembros_repo.crear_miembro("ana", "clave123", "Ana Pérez", "30111222", "1155554444")
        self.mariana = miembros_repo.crear_miembro("mariana", "clave123", "", "30111333", "1155553333")
        self.bono_3h = bonos_miembro_repo.crear_bono("3 horas", 180, 3000)
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])
        self.hoy = dia_en_que_empezo_el_turno(datetime.now())

    def cargar_bono(self, miembro=None, operador=None, pagos=EFECTIVO):
        return miembros_repo.cargar_saldo_por_bono(miembro or self.ana, self.bono_3h, pagos,
                                                   operador or self.toby)["venta_id"]

    def cargas(self, desde=None, hasta=None, **filtros):
        return historial_cargas_repo.listar_cargas(desde or self.hoy, hasta or self.hoy, **filtros)

    def mover_la_carga(self, venta_id, fecha: datetime):
        with conexion_db() as conexion:
            conexion.execute("UPDATE movimientos_saldo_miembro SET fecha = ? WHERE venta_id = ?",
                             (fecha.isoformat(timespec="seconds"), venta_id))


class TestQueEntra(BaseHistorial):
    def test_cada_carga_con_socio_tiempo_plata_pago_bono_operador_y_fecha(self):
        self.cargar_bono()
        [carga] = self.cargas()
        self.assertEqual(carga["socio"], "ana (Ana Pérez)")
        self.assertEqual(carga["minutos"], 180)
        self.assertEqual(carga["monto"], 3000)
        self.assertEqual(carga["medio"], "Efectivo")
        self.assertEqual(carga["bono"], "3 horas")
        self.assertEqual(carga["operador"], "TOBY")
        self.assertFalse(carga["anulada"])
        self.assertAlmostEqual(datetime.fromisoformat(carga["fecha"]), datetime.now(), delta=timedelta(minutes=1))

    def test_monto_libre_sin_bono_y_pagado_en_los_dos_medios(self):
        miembros_repo.cargar_saldo_por_monto(
            self.mariana, 2000, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 500},
                                 {"metodo": dominio.PAGO_DIGITAL, "monto": 1500}], self.toby)
        [carga] = self.cargas()
        # Sin nombre, el socio sale solo con su usuario.
        self.assertEqual(carga["socio"], "mariana")
        self.assertIsNone(carga["bono"])
        self.assertEqual(carga["minutos"], 120)
        self.assertEqual(carga["medio"], "Efectivo y digital")

    def test_de_la_mas_nueva_a_la_mas_vieja(self):
        vieja = self.cargar_bono(self.mariana)
        self.mover_la_carga(vieja, datetime.now() - timedelta(minutes=10))
        self.cargar_bono(self.ana)
        self.assertEqual([c["socio"] for c in self.cargas()], ["ana (Ana Pérez)", "mariana"])

    def test_ni_consumos_ni_saldos_importados(self):
        self.cargar_bono()
        pc = pcs_repo.crear_estacion("PC07")
        miembros_repo.abrir_estacion_por_miembro(pc, "ana", "clave123")
        with conexion_db() as conexion:
            conexion.execute(
                "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha) VALUES (?, ?, ?, ?)",
                (self.mariana, dominio.MOVIMIENTO_IMPORTACION, 600, datetime.now().isoformat(timespec="seconds")),
            )
        self.assertEqual([c["socio"] for c in self.cargas()], ["ana (Ana Pérez)"])

    def test_la_carga_que_paso_directo_a_la_pc_tambien_sale(self):
        miembros_repo.cargar_saldo_por_bono(self.ana, bonos_miembro_repo.crear_bono("Media hora", 30, 500),
                                            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 500}], self.toby)
        miembros_repo.abrir_estacion_por_miembro(pcs_repo.crear_estacion("PC07"), "ana", "clave123")
        self.assertIsNotNone(miembros_repo.cargar_saldo_por_bono(self.ana, self.bono_3h, EFECTIVO,
                                                                 self.toby)["sumado_a_la_sesion"])
        self.assertEqual([c["minutos"] for c in self.cargas()], [180, 30])

    def test_si_cobra_el_admin_con_la_caja_de_una_empleada_sale_el_admin(self):
        # La venta queda a nombre de TOBY (su caja), pero el que cargó fue el dueño.
        relevo_repo.abrir_caja(self.toby, 50000.0)
        self.cargar_bono(operador=self.admin)
        self.assertEqual(self.cargas()[0]["operador"], "Duenio")


class TestAnuladasYTotales(BaseHistorial):
    def test_la_anulada_sale_con_quien_y_por_que_y_no_suma(self):
        anulada = self.cargar_bono()
        self.cargar_bono(self.mariana)
        miembros_repo.anular_carga(anulada, self.admin, "se cargó a otro socio")

        cargas = self.cargas()
        carga = next(c for c in cargas if c["anulada"])
        self.assertEqual((carga["anulada_por"], carga["anulada_motivo"]), ("Duenio", "se cargó a otro socio"))
        self.assertEqual(historial_cargas_repo.totales(cargas),
                         {"cantidad": 1, "minutos": 180, "monto": 3000, "anuladas": 1})


class TestFiltros(BaseHistorial):
    def test_dias_del_local_de_las_6_a_las_6(self):
        # Una carga del día 2 a las 02:00 es de la Noche del día 1.
        venta = self.cargar_bono()
        dia_1 = self.hoy - timedelta(days=5)
        self.mover_la_carga(venta, datetime.combine(dia_1 + timedelta(days=1), datetime.min.time()).replace(hour=2))
        self.assertEqual(len(self.cargas(dia_1, dia_1)), 1)
        self.assertEqual(self.cargas(dia_1 + timedelta(days=1), dia_1 + timedelta(days=1)), [])
        self.assertEqual(self.cargas(), [])

    def test_buscar_sin_mayusculas_ni_acentos(self):
        self.cargar_bono(self.ana)
        self.cargar_bono(self.mariana)
        self.assertEqual([c["socio"] for c in self.cargas(buscar="PEREZ")], ["ana (Ana Pérez)"])
        # Buscando el texto, "ana" trae también a "mariana"...
        self.assertEqual(len(self.cargas(buscar="ana")), 2)
        # ...por eso Miembros, con un socio marcado, pasa su id.
        self.assertEqual([c["socio"] for c in self.cargas(miembro_id=self.ana)], ["ana (Ana Pérez)"])


class TestVentana(BaseHistorial):
    def ventana(self, miembro=None):
        ventana = VentanaHistorialCargas(None, miembro)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def socios_en_la_tabla(self, ventana):
        return [ventana.tabla.item(fila, COLUMNA_SOCIO).text() for fila in range(ventana.tabla.rowCount())]

    def test_muestra_las_cargas_del_mes_con_los_totales(self):
        anulada = self.cargar_bono(self.ana)
        self.cargar_bono(self.mariana)
        miembros_repo.anular_carga(anulada, self.admin, "error")

        ventana = self.ventana()
        self.assertEqual(self.socios_en_la_tabla(ventana), ["mariana", "ana (Ana Pérez)"])
        fila_anulada = 1
        self.assertTrue(ventana.tabla.item(fila_anulada, COLUMNA_ESTADO).text().startswith("ANULADA por Duenio"))
        self.assertEqual(ventana.tabla.item(fila_anulada, COLUMNA_SOCIO).foreground().color().name(), "#c62828")
        self.assertEqual(ventana.etiqueta_totales.text(), "1 carga · 3h 00m · $ 3.000  (sin contar 1 anulada)")

    def test_con_un_socio_abre_solo_con_sus_cargas_y_al_borrar_el_buscador_ve_todas(self):
        self.cargar_bono(self.ana)
        self.cargar_bono(self.mariana)
        ventana = self.ventana(miembros_repo.obtener_miembro(self.ana))
        self.assertEqual(ventana.campo_socio.text(), "ana")
        self.assertEqual(self.socios_en_la_tabla(ventana), ["ana (Ana Pérez)"])

        ventana.campo_socio.clear()
        self.assertEqual(len(self.socios_en_la_tabla(ventana)), 2)

    def test_sin_cargas_no_hay_nada_que_imprimir(self):
        ventana = self.ventana()
        self.assertEqual(ventana.tabla.rowCount(), 0)
        self.assertFalse(ventana.boton_imprimir.isEnabled())

    def test_la_hoja_impresa(self):
        self.cargar_bono()
        ventana = self.ventana()
        html = ventana.html_para_imprimir(datetime(2026, 10, 24, 9, 30))
        self.assertIn("Historial de Cargas", html)
        self.assertIn("Impreso el 24/10/2026 09:30", html)
        self.assertIn("ana (Ana Pérez)", html)
        self.assertIn("1 carga", html)
        with mock.patch("control_pcs.ui.miembros_historial_cargas.imprimir.vista_previa") as vista_previa:
            ventana.boton_imprimir.click()
        vista_previa.assert_called_once()


class TestBotonEnMiembros(BaseHistorial):
    def miembros(self):
        ventana = MiembrosWindow(usuarios_repo.obtener_usuario(self.toby))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_el_de_un_socio_esta_en_su_ficha_al_lado_de_cargar_saldo_y_el_de_todos_abajo(self):
        ventana = self.miembros()
        ficha = ventana.ficha
        self.assertEqual(ficha.boton_historial.text(), "Historial de este socio")
        # En la ficha, los botones van en este orden: Cargar Saldo, Historial de este socio.
        acciones = [boton for boton in ficha.findChildren(type(ficha.boton_historial))
                    if boton in (ficha.boton_cargar_saldo, ficha.boton_historial)]
        self.assertEqual([boton.text() for boton in acciones], ["Cargar Saldo", "Historial de este socio"])
        self.assertEqual(ventana.boton_historial_todos.text(), "Historial de Cargas")

    def test_el_de_la_ficha_abre_con_ese_socio_y_el_de_abajo_con_todos(self):
        ventana = self.miembros()
        with mock.patch("control_pcs.ui.miembros_window.VentanaHistorialCargas") as historial:
            ventana.boton_historial_todos.click()
            self.assertIsNone(historial.call_args.args[1])

            fila = next(i for i, m in enumerate(ventana.miembros) if m["usuario"] == "mariana")
            ventana.lista.setCurrentRow(fila)
            ventana.ficha.boton_historial.click()
            self.assertEqual(historial.call_args.args[1]["id"], self.mariana)
