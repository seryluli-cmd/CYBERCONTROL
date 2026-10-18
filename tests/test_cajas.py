"""
tests/test_cajas.py
====================
Las cajas con número (pedido del dueño, 2026-10-18; reglas en
repositories/relevo_repo.py): abrir contando el Cambio Fijo, recibir la caja de
quien cubrió el turno, cerrar la de quien se fue, el cierre forzoso a los 15
minutos, las ventas del Admin a nombre de la responsable y el sobre que carga
solo el Admin.

Se ejecutan con:

    python -m unittest discover tests
"""

import unittest
from datetime import date, datetime
from unittest import mock

import dominio
from database import conexion_db
from repositories import (
    articulos_repo, compras_repo, limpieza_repo, relevo_repo, turnos_repo, usuarios_repo, ventas_repo,
)
from base import BaseConBaseTemporal

LUNES = date(2026, 1, 5)
DOMINGO = date(2026, 1, 4)


def _a_las(hora, minuto=0, dia=LUNES):
    return datetime(dia.year, dia.month, dia.day, hora, minuto)


class _BaseDeCajas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Dueño", "1234", dominio.ROL_ADMIN)
        self.lucia_id = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        self.gaby_id = usuarios_repo.crear_usuario("Gaby", "1234", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COD1", "Turrón", None, None, 500.0, 300.0, 0)
        compras_repo.registrar_compra(self.admin_id, [{"codigo": "COD1", "cantidad": 100, "costo_unitario": 300.0}])

    def _vender(self, usuario_id, momento, monto=500.0, metodo=dominio.PAGO_EFECTIVO):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            return ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD1", "descripcion": "Turrón", "cantidad": 1, "precio_unitario": monto}],
                [{"metodo": metodo, "monto": monto}],
            )

    def _situacion(self, usuario_id, momento):
        return relevo_repo.situacion_al_entrar(usuario_id, momento)

    def _caja_de_la_venta(self, venta_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT ventas.usuario_id, ventas_caja.caja_id, ventas_caja.cargada_por "
                "FROM ventas LEFT JOIN ventas_caja ON ventas_caja.venta_id = ventas.id WHERE ventas.id = ?",
                (venta_id,),
            ).fetchone()


class TestAbrirCaja(_BaseDeCajas):
    def test_sin_caja_abierta_la_empleada_abre_una_contando_el_cambio_fijo(self):
        situacion = self._situacion(self.lucia_id, _a_las(5, 55))

        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_ABRIR)
        self.assertTrue(situacion["cuenta_cambio"])
        self.assertEqual(situacion["cambio_esperado"], 50000.0)
        self.assertEqual(situacion["turno_label"], "Mañana")

    def test_quien_abre_a_las_05_55_abre_la_manana(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 49500.0, _a_las(5, 55))

        self.assertEqual(caja["turno_label"], "Mañana")
        self.assertEqual(caja["diferencia"], -500.0)
        self.assertEqual(self._situacion(self.lucia_id, _a_las(6, 0))["situacion"], relevo_repo.SITUACION_SU_CAJA)

    def test_si_hay_que_contar_no_se_puede_abrir_sin_el_monto(self):
        with self.assertRaises(ValueError):
            relevo_repo.abrir_caja(self.lucia_id, None, _a_las(5, 55))

    def test_el_admin_entra_sin_caja_y_no_puede_abrir_una(self):
        self.assertEqual(self._situacion(self.admin_id, _a_las(10))["situacion"], relevo_repo.SITUACION_ADMIN)
        with self.assertRaises(ValueError):
            relevo_repo.abrir_caja(self.admin_id, 50000.0, _a_las(10))

    def test_con_una_caja_abierta_otra_persona_no_puede_abrir_otra(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))

        self.assertEqual(self._situacion(self.gaby_id, _a_las(10))["situacion"], relevo_repo.SITUACION_RECIBIR)
        with self.assertRaises(ValueError):
            relevo_repo.abrir_caja(self.gaby_id, 50000.0, _a_las(10))

    def test_la_misma_persona_que_cerro_reabre_sin_contar(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))

        situacion = self._situacion(self.lucia_id, _a_las(14, 1))
        caja = relevo_repo.abrir_caja(self.lucia_id, None, _a_las(14, 1))

        self.assertFalse(situacion["cuenta_cambio"])
        self.assertEqual(caja["turno_label"], "Tarde")
        self.assertIsNone(caja["cambio_contado"])

    def test_la_siguiente_espera_el_cambio_que_dejo_la_anterior(self):
        # Lucía contó $500 de menos al abrir: deja lo que recibió, y eso es lo que
        # se espera en la caja siguiente (el faltante se ve una sola vez).
        relevo_repo.abrir_caja(self.lucia_id, 49500.0, _a_las(5, 55))
        cierre = turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))

        situacion = self._situacion(self.gaby_id, _a_las(14, 2))

        self.assertEqual(cierre["cambio_que_queda"], 49500.0)
        self.assertTrue(situacion["cuenta_cambio"])
        self.assertEqual(situacion["cambio_esperado"], 49500.0)


class TestVentasEnLaCaja(_BaseDeCajas):
    def test_la_venta_queda_en_la_caja_abierta(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        venta = self._vender(self.lucia_id, _a_las(9))

        fila = self._caja_de_la_venta(venta)
        self.assertEqual((fila["usuario_id"], fila["caja_id"], fila["cargada_por"]),
                         (self.lucia_id, caja["caja_numero"], None))

    def test_lo_que_cobra_el_admin_queda_a_nombre_de_la_responsable(self):
        # Pedido del dueño: "que lo asiente como la empleada que estaba antes de
        # que yo entrara como administrador".
        caja = relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        venta = self._vender(self.admin_id, _a_las(9))

        fila = self._caja_de_la_venta(venta)
        self.assertEqual((fila["usuario_id"], fila["caja_id"], fila["cargada_por"]),
                         (self.lucia_id, caja["caja_numero"], self.admin_id))
        cierre = turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))
        detalle = turnos_repo.detalle_cierre(cierre["id"])
        self.assertEqual(detalle["ventas"][0]["vendedor"], "Lucia")
        self.assertEqual(detalle["ventas"][0]["cargada_por_nombre"], "Dueño")

    def test_sin_caja_abierta_la_venta_queda_como_siempre(self):
        venta = self._vender(self.admin_id, _a_las(3))

        fila = self._caja_de_la_venta(venta)
        self.assertEqual((fila["usuario_id"], fila["caja_id"]), (self.admin_id, None))


class TestCerrarCaja(_BaseDeCajas):
    def test_el_cierre_queda_unido_a_su_caja(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)
        self._vender(self.lucia_id, _a_las(10), 600.0, dominio.PAGO_DIGITAL)

        cierre = turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))

        self.assertEqual((cierre["caja_numero"], cierre["responsable"], cierre["turno"]),
                         (caja["caja_numero"], "Lucia", dominio.TURNO_MANANA))
        self.assertEqual(cierre["monto_a_retirar"], 1000.0)
        guardado = turnos_repo.listar_cierres()[0]
        self.assertEqual(guardado["caja_numero"], caja["caja_numero"])
        self.assertEqual(guardado["responsables"], ["Lucia"])
        self.assertFalse(guardado["cerrada_en_ausencia"])
        self.assertFalse(guardado["cierre_forzoso"])
        self.assertEqual(guardado["minutos_despues_del_fin"], 0)
        self.assertEqual(guardado["cambio_contado"], 50000.0)
        self.assertIsNone(relevo_repo.estado_de_la_caja(_a_las(14, 1)))

    def test_el_turno_del_cierre_es_el_de_la_caja_aunque_el_cierre_anterior_sea_de_hace_horas(self):
        # Último cierre el domingo 22:05 y el programa sin uso a la noche: la caja
        # que se abre el lunes a las 07:00 es la Mañana del lunes, no la Noche del
        # domingo (que es lo que daría contar desde el cierre anterior).
        turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(22, 5, DOMINGO))
        relevo_repo.abrir_caja(self.gaby_id, 50000.0, _a_las(7))

        cierre = turnos_repo.cerrar_turno(self.gaby_id, ahora_dt=_a_las(14, 0))

        self.assertEqual(cierre["turno"], dominio.TURNO_MANANA)
        self.assertEqual(turnos_repo.listar_cierres()[0]["fecha"], LUNES.isoformat())

    def test_el_resumen_de_la_caja_muestra_el_numero_y_el_cambio_contado(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 49800.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["caja_numero"], resumen["responsable"]), (caja["caja_numero"], "Lucia"))
        self.assertEqual(resumen["cambio_inicial"], 49800.0)
        self.assertEqual(resumen["caja_actual"], 50800.0)


class TestReemplazoQueLlegaTarde(_BaseDeCajas):
    """El ejemplo del dueño: Lucía hace la Mañana y Gaby llega 14:50."""

    def test_lucia_cubre_y_gaby_recibe_la_caja_contando_todo(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)
        manana = turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))
        self.assertEqual(manana["monto_a_retirar"], 1000.0)   # el sobre de la Mañana es solo de la Mañana

        cubre = relevo_repo.abrir_caja(self.lucia_id, None, _a_las(14, 0))   # sin contar: lo dejó ella
        self._vender(self.lucia_id, _a_las(14, 20), 6200.0)
        self._vender(self.lucia_id, _a_las(14, 30), 800.0, dominio.PAGO_DIGITAL)

        situacion = self._situacion(self.gaby_id, _a_las(14, 50))
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_RECIBIR)
        self.assertEqual((situacion["esperado"], situacion["cambio_inicial"], situacion["ventas_efectivo"]),
                         (56200.0, 50000.0, 6200.0))

        relevo = relevo_repo.recibir_caja(self.gaby_id, cubre["caja_numero"], 56000.0, _a_las(14, 50))
        self.assertEqual((relevo["diferencia"], relevo["de"]), (-200.0, "Lucia"))
        self.assertEqual(self._situacion(self.gaby_id, _a_las(15))["situacion"], relevo_repo.SITUACION_SU_CAJA)
        # Lucía ya no tiene la caja: si vuelve a entrar, es la caja de Gaby.
        self.assertEqual(self._situacion(self.lucia_id, _a_las(15))["situacion"], relevo_repo.SITUACION_RECIBIR)

        self._vender(self.gaby_id, _a_las(16), 3000.0)
        tarde = turnos_repo.cerrar_turno(self.gaby_id, ahora_dt=_a_las(22, 0))

        # Lo que vendió Lucía en esos 50 minutos va en el sobre de Gaby.
        self.assertEqual(tarde["monto_a_retirar"], 9200.0)
        self.assertEqual(tarde["turno"], dominio.TURNO_TARDE)
        guardado = turnos_repo.listar_cierres()[0]
        self.assertEqual(guardado["responsables"], ["Lucia", "Gaby"])
        self.assertEqual(len(guardado["relevos"]), 1)
        self.assertEqual(guardado["relevos"][0]["monto_contado"], 56000.0)
        self.assertFalse(guardado["cerrada_en_ausencia"])

    def test_no_se_puede_recibir_otra_caja_que_la_abierta(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        with self.assertRaises(ValueError):
            relevo_repo.recibir_caja(self.gaby_id, caja["caja_numero"] + 1, 50000.0, _a_las(10))


class TestCerrarLaCajaDeOtra(_BaseDeCajas):
    def test_si_su_turno_termino_la_que_llega_la_cierra_en_su_ausencia(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)

        situacion = self._situacion(self.gaby_id, _a_las(13, 56))
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_CERRAR_LA_DE_OTRA)
        self.assertEqual((situacion["a_retirar"], situacion["cambio_que_queda"]), (1000.0, 50000.0))

        cierre = relevo_repo.cerrar_para_entrar(self.gaby_id, relevo_repo.SITUACION_CERRAR_LA_DE_OTRA, _a_las(13, 56))

        self.assertEqual((cierre["caja_numero"], cierre["responsable"]), (caja["caja_numero"], "Lucia"))
        guardado = turnos_repo.listar_cierres()[0]
        self.assertTrue(guardado["cerrada_en_ausencia"])
        self.assertEqual((guardado["empleada"], guardado["responsable"]), ("Gaby", "Lucia"))
        # En el Resumen del Día la caja sigue siendo de Lucía.
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = _a_las(14, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            manana = turnos_repo.resumen_del_dia(LUNES)["turnos"][0]
        self.assertEqual(manana["responsables"], ["Lucia"])
        # Y después Gaby abre la suya contando.
        apertura = self._situacion(self.gaby_id, _a_las(13, 57))
        self.assertEqual(apertura["situacion"], relevo_repo.SITUACION_ABRIR)
        self.assertTrue(apertura["cuenta_cambio"])
        self.assertEqual(relevo_repo.abrir_caja(self.gaby_id, 50000.0, _a_las(13, 57))["turno_label"], "Tarde")

    def test_antes_del_aviso_la_caja_de_otra_se_recibe(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))

        self.assertEqual(self._situacion(self.gaby_id, _a_las(13, 54))["situacion"], relevo_repo.SITUACION_RECIBIR)

    def test_cerrar_para_entrar_no_cierra_si_la_situacion_cambio(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))

        with self.assertRaises(ValueError):
            relevo_repo.cerrar_para_entrar(self.gaby_id, relevo_repo.SITUACION_CERRAR_LA_DE_OTRA, _a_las(10))
        self.assertEqual(turnos_repo.listar_cierres(), [])


class TestCierreForzoso(_BaseDeCajas):
    def test_el_boton_titila_desde_5_minutos_antes_y_vence_a_los_15_despues(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))

        for momento, titilar, vencida in (
            (_a_las(13, 54), False, False), (_a_las(13, 55), True, False),
            (_a_las(14, 14), True, False), (_a_las(14, 15), True, True),
        ):
            with self.subTest(momento=momento):
                estado = relevo_repo.estado_de_la_caja(momento)
                self.assertEqual((estado["titilar"], estado["vencida"]), (titilar, vencida))

    def test_el_domingo_la_manana_titila_a_las_17_55(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(6, 0, DOMINGO))

        self.assertFalse(relevo_repo.estado_de_la_caja(_a_las(17, 54, DOMINGO))["titilar"])
        self.assertTrue(relevo_repo.estado_de_la_caja(_a_las(17, 55, DOMINGO))["titilar"])
        self.assertEqual(relevo_repo.estado_de_la_caja(_a_las(17, 55, DOMINGO))["turno_label"], "Domingo T1")

    def test_a_los_15_minutos_la_caja_se_cierra_sola(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)

        self.assertIsNone(relevo_repo.cierre_forzoso_si_corresponde(_a_las(14, 14)))
        cierre = relevo_repo.cierre_forzoso_si_corresponde(_a_las(14, 15))

        self.assertTrue(cierre["forzoso"])
        self.assertEqual((cierre["monto_a_retirar"], cierre["responsable"]), (1000.0, "Lucia"))
        guardado = turnos_repo.listar_cierres()[0]
        self.assertTrue(guardado["cierre_forzoso"])
        self.assertFalse(guardado["cerrada_en_ausencia"])
        self.assertEqual(guardado["minutos_despues_del_fin"], 15)
        # Lucía, si sigue atendiendo, vuelve a entrar sin contar.
        self.assertFalse(self._situacion(self.lucia_id, _a_las(14, 16))["cuenta_cambio"])

    def test_si_el_programa_estuvo_cerrado_la_propia_caja_vencida_se_cierra_al_entrar(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))

        situacion = self._situacion(self.lucia_id, _a_las(15))
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_SU_CAJA_VENCIDA)
        cierre = relevo_repo.cerrar_para_entrar(self.lucia_id, relevo_repo.SITUACION_SU_CAJA_VENCIDA, _a_las(15))

        self.assertTrue(cierre["forzoso"])
        self.assertEqual(self._situacion(self.lucia_id, _a_las(15))["situacion"], relevo_repo.SITUACION_ABRIR)


class TestVentasSinCaja(_BaseDeCajas):
    def test_las_ventas_sin_caja_se_cierran_aparte_antes_de_abrir(self):
        self._vender(self.admin_id, _a_las(2, 36), 1500.0)   # el Admin, sin nadie en el mostrador
        self._vender(self.admin_id, _a_las(4, 50), 500.0)

        situacion = self._situacion(self.lucia_id, _a_las(5, 55))
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_VENTAS_SIN_CAJA)
        self.assertEqual((situacion["cantidad"], situacion["a_retirar"]), (2, 2000.0))
        self.assertTrue(situacion["desde"].startswith("2026-01-05T02:36"))
        with self.assertRaises(ValueError):
            relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))

        cierre = relevo_repo.cerrar_para_entrar(self.lucia_id, relevo_repo.SITUACION_VENTAS_SIN_CAJA, _a_las(5, 55))

        self.assertIsNone(cierre["caja_numero"])
        self.assertEqual(cierre["monto_a_retirar"], 2000.0)
        self.assertIsNone(turnos_repo.listar_cierres()[0]["caja_numero"])
        apertura = self._situacion(self.lucia_id, _a_las(5, 56))
        self.assertEqual(apertura["situacion"], relevo_repo.SITUACION_ABRIR)
        self.assertTrue(apertura["cuenta_cambio"])


class TestSobreLoCargaSoloElAdmin(_BaseDeCajas):
    def _un_cierre(self):
        relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)
        return turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))

    def test_una_empleada_no_puede_cargar_lo_contado(self):
        cierre = self._un_cierre()
        with self.assertRaises(PermissionError):
            turnos_repo.verificar_cierre(cierre["id"], 1000.0, self.gaby_id)

    def test_cada_conteo_queda_guardado_y_el_cierre_muestra_el_ultimo(self):
        cierre = self._un_cierre()

        turnos_repo.verificar_cierre(cierre["id"], 900.0, self.admin_id)
        turnos_repo.verificar_cierre(cierre["id"], 1000.0, self.admin_id)

        detalle = turnos_repo.detalle_cierre(cierre["id"])
        self.assertEqual([v["monto_contado"] for v in detalle["verificaciones"]], [900.0, 1000.0])
        self.assertEqual([v["diferencia"] for v in detalle["verificaciones"]], [-100.0, 0.0])
        guardado = turnos_repo.listar_cierres()[0]
        self.assertEqual((guardado["monto_contado"], guardado["diferencia"]), (1000.0, 0.0))


class TestLimpiarBaseConCajas(_BaseDeCajas):
    def test_limpiar_la_base_borra_tambien_las_cajas(self):
        caja = relevo_repo.abrir_caja(self.lucia_id, 50000.0, _a_las(5, 55))
        self._vender(self.lucia_id, _a_las(9), 1000.0)
        cierre = turnos_repo.cerrar_turno(self.lucia_id, ahora_dt=_a_las(14, 0))
        turnos_repo.verificar_cierre(cierre["id"], 1000.0, self.admin_id)
        relevo_repo.abrir_caja(self.lucia_id, None, _a_las(14, 0))
        relevo_repo.recibir_caja(self.gaby_id, caja["caja_numero"] + 1, 50000.0, _a_las(14, 50))

        limpieza_repo.limpiar_base(self.admin_id)

        with conexion_db() as conexion:
            for tabla in ("cajas", "relevos_caja", "ventas_caja", "verificaciones_cierre"):
                with self.subTest(tabla=tabla):
                    self.assertEqual(conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0], 0)


if __name__ == "__main__":
    unittest.main()
