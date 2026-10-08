"""
tests/test_playstation.py
===========================
La PlayStation 5 (control_pcs/repositories/playstation_repo.py): quién puede
administrar y vender sus bonos, que sus bonos y los de PC nunca se mezclen,
cómo se registran sus ventas (origen PLAYSTATION, aparte de Kiosko y de
Alquiler de PCs, en Caja, Cierre de Turno y Reportes), y que el tiempo
restante y el vencimiento sean correctos aunque se cierre y reabra el
programa. También la migración de `ventas` que le hace lugar al origen nuevo
en una base ya existente. La pantalla (grilla y panel) se prueba en
tests/test_playstation_ui.py.

Se ejecutan con:

    python -m unittest discover tests
"""

import contextlib
import os
import sqlite3
import unittest
from datetime import date, datetime
from unittest import mock

import database
import dominio
from repositories import reportes_repo, turnos_repo, usuarios_repo, ventas_repo
from control_pcs.repositories import bonos_miembro_repo, pcs_repo, playstation_repo
from base import BaseConBaseTemporal


@contextlib.contextmanager
def _reloj(momento):
    """Dentro del bloque, la PlayStation cree que ahora es `momento`."""
    with mock.patch("control_pcs.repositories.playstation_repo.datetime") as datetime_mock:
        datetime_mock.now.return_value = momento
        datetime_mock.fromisoformat = datetime.fromisoformat
        yield


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _contar(tabla):
    with database.conexion_db() as conexion:
        return conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]


class _ConPlaystation(BaseConBaseTemporal):
    """Un Admin, una operadora con el permiso de operar PCs y una empleada sin
    ningún permiso, más un bono de "1 hora" ($3.000) en el catálogo de la consola."""

    HORA = datetime(2026, 1, 5, 10, 0, 0)

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.operadora_id = usuarios_repo.crear_usuario(
            "Operadora", "1234", dominio.ROL_EMPLEADA, {playstation_repo.PERMISO_OPERAR: True}
        )
        self.empleada_id = usuarios_repo.crear_usuario("Empleada", "1234", dominio.ROL_EMPLEADA)
        self.bono_id = playstation_repo.crear_bono(self.admin_id, "1 hora", 60, 3000)

    def _vender(self, momento, bono_id=None, usuario_id=None, pagos=None):
        bono_id = bono_id or self.bono_id
        if pagos is None:
            pagos = _efectivo(playstation_repo.obtener_bono(bono_id)["precio"])
        with _reloj(momento):
            return playstation_repo.vender_bono(usuario_id or self.operadora_id, bono_id, pagos)

    def _estado(self, momento):
        with _reloj(momento):
            return playstation_repo.estado()


class TestPermisosDeLaPlaystation(_ConPlaystation):
    def test_solo_el_admin_crea_modifica_y_da_de_baja_bonos(self):
        # Ni siquiera quien tiene el permiso de operar PCs puede administrar el catálogo.
        for usuario_id in (self.operadora_id, self.empleada_id):
            with self.assertRaises(PermissionError):
                playstation_repo.crear_bono(usuario_id, "2 horas", 120, 5000)
            with self.assertRaises(PermissionError):
                playstation_repo.modificar_bono(usuario_id, self.bono_id, "Otro", 30, 100)
            with self.assertRaises(PermissionError):
                playstation_repo.desactivar_bono(usuario_id, self.bono_id)

        bono = playstation_repo.obtener_bono(self.bono_id)
        self.assertEqual((bono["nombre"], bono["minutos"], bono["precio"], bono["activo"]), ("1 hora", 60, 3000.0, 1))
        self.assertEqual(len(playstation_repo.listar_bonos(solo_activos=False)), 1)

    def test_el_admin_administra_los_bonos(self):
        nuevo_id = playstation_repo.crear_bono(self.admin_id, "2 horas", 120, 5000)
        playstation_repo.modificar_bono(self.admin_id, nuevo_id, "2 horas PS5", 120, 5500)
        bono = playstation_repo.obtener_bono(nuevo_id)
        self.assertEqual((bono["nombre"], bono["precio"]), ("2 horas PS5", 5500.0))

        playstation_repo.desactivar_bono(self.admin_id, nuevo_id)

        self.assertEqual([b["id"] for b in playstation_repo.listar_bonos()], [self.bono_id])
        # Nada se borra: queda en el catálogo, solo que dado de baja.
        self.assertEqual(playstation_repo.obtener_bono(nuevo_id)["activo"], 0)

    def test_las_pantallas_de_bonos_tambien_exigen_ser_admin(self):
        # Las pantallas de alta/edición usan este objeto, que lleva el usuario por dentro.
        sin_poder = playstation_repo.AdministradorDeBonos(self.operadora_id)
        with self.assertRaises(PermissionError):
            sin_poder.crear_bono("2 horas", 120, 5000)
        with self.assertRaises(PermissionError):
            sin_poder.modificar_bono(self.bono_id, "x", 30, 100)
        with self.assertRaises(PermissionError):
            sin_poder.desactivar_bono(self.bono_id)
        self.assertEqual(len(sin_poder.listar_bonos()), 1)  # mirar el catálogo no cuesta nada

        admin = playstation_repo.AdministradorDeBonos(self.admin_id)
        bono_id = admin.crear_bono("30 minutos", 30, 1800)
        admin.modificar_bono(bono_id, "30 min", 30, 1900)
        admin.desactivar_bono(bono_id)
        self.assertEqual([b["id"] for b in admin.listar_bonos()], [self.bono_id])

    def test_quien_tiene_el_permiso_operativo_vende_y_libera_pero_no_administra(self):
        self._vender(self.HORA, usuario_id=self.operadora_id)
        self.assertIsNotNone(self._estado(self.HORA)["sesion"])

        with _reloj(self.HORA):
            playstation_repo.finalizar_sesion(self.operadora_id)
        self.assertIsNone(self._estado(self.HORA)["sesion"])

        with self.assertRaises(PermissionError):
            playstation_repo.crear_bono(self.operadora_id, "2 horas", 120, 5000)

    def test_una_empleada_sin_el_permiso_no_vende_ni_libera(self):
        with self.assertRaises(PermissionError):
            self._vender(self.HORA, usuario_id=self.empleada_id)
        self.assertEqual((_contar("ventas"), _contar("sesiones_playstation")), (0, 0))

        self._vender(self.HORA, usuario_id=self.operadora_id)
        with self.assertRaises(PermissionError):
            playstation_repo.finalizar_sesion(self.empleada_id)
        self.assertIsNotNone(self._estado(self.HORA)["sesion"])  # sigue corriendo

    def test_el_admin_opera_sin_necesitar_el_permiso_marcado(self):
        # tiene_permiso deja pasar siempre a un Admin, aunque su columna esté en 0.
        self.assertEqual(usuarios_repo.obtener_usuario(self.admin_id)[playstation_repo.PERMISO_OPERAR], 0)
        self._vender(self.HORA, usuario_id=self.admin_id)
        with _reloj(self.HORA):
            playstation_repo.finalizar_sesion(self.admin_id)

    def test_puede_operar_se_pregunta_con_la_fila_del_usuario(self):
        self.assertTrue(playstation_repo.puede_operar(usuarios_repo.obtener_usuario(self.admin_id)))
        self.assertTrue(playstation_repo.puede_operar(usuarios_repo.obtener_usuario(self.operadora_id)))
        self.assertFalse(playstation_repo.puede_operar(usuarios_repo.obtener_usuario(self.empleada_id)))

    def test_un_permiso_quitado_corta_el_acceso_en_el_acto(self):
        # La operadora sigue "logueada" con la fila que tenía al entrar; el Admin
        # le saca el permiso: la próxima venta se rechaza igual.
        self._vender(self.HORA, usuario_id=self.operadora_id)
        usuarios_repo.modificar_usuario(self.operadora_id, "Operadora", dominio.ROL_EMPLEADA, permisos={})

        with self.assertRaises(PermissionError):
            self._vender(self.HORA, usuario_id=self.operadora_id)
        self.assertEqual(_contar("sesion_playstation_bonos"), 1)

    def test_un_usuario_desactivado_o_inexistente_no_opera(self):
        usuarios_repo.desactivar_usuario(self.operadora_id)
        with self.assertRaises(PermissionError):
            self._vender(self.HORA, usuario_id=self.operadora_id)
        with self.assertRaises(PermissionError):
            self._vender(self.HORA, usuario_id=9999)
        with self.assertRaises(PermissionError):
            playstation_repo.crear_bono(9999, "2 horas", 120, 5000)


class TestCatalogosSeparados(_ConPlaystation):
    def test_los_bonos_de_la_consola_no_aparecen_en_los_de_pc_ni_en_los_de_socios(self):
        pcs_repo.crear_bono("3 horas", 180, 9000)

        self.assertEqual([b["nombre"] for b in playstation_repo.listar_bonos()], ["1 hora"])
        self.assertEqual([b["nombre"] for b in pcs_repo.listar_bonos()], ["3 horas"])
        self.assertEqual(list(bonos_miembro_repo.listar_bonos()), [])

    def test_un_bono_se_valida_igual_que_en_los_otros_catalogos(self):
        for nombre, minutos, precio in (("", 60, 1000), ("Algo", 0, 1000), ("Algo", 60, 0)):
            with self.assertRaises(ValueError):
                playstation_repo.crear_bono(self.admin_id, nombre, minutos, precio)
        self.assertEqual(len(playstation_repo.listar_bonos(solo_activos=False)), 1)


class TestIncompatibilidadEntreBonos(_ConPlaystation):
    """Un bono de PC no se le puede vender a la consola, ni uno de la consola a una PC."""

    def _asignar_pc(self, estacion_id, bono_id, momento, monto):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.asignar_bono(estacion_id, bono_id, self.operadora_id, _efectivo(monto))

    def test_un_bono_de_pc_no_se_puede_vender_en_la_consola(self):
        pcs_repo.crear_bono("3 horas", 180, 9000)                   # id 1: existe en las dos tablas
        bono_solo_de_pc = pcs_repo.crear_bono("5 horas", 300, 12000)  # id 2: la consola no lo tiene

        with self.assertRaises(ValueError):
            self._vender(self.HORA, bono_id=bono_solo_de_pc, pagos=_efectivo(12000))

        self.assertEqual((_contar("ventas"), _contar("sesiones_playstation")), (0, 0))

    def test_un_bono_de_la_consola_no_se_puede_vender_a_una_pc(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_solo_de_consola = playstation_repo.crear_bono(self.admin_id, "2 horas", 120, 5000)  # id 2

        with self.assertRaises(ValueError):
            self._asignar_pc(estacion_id, bono_solo_de_consola, self.HORA, 5000)

        self.assertEqual((_contar("ventas"), _contar("sesiones_pc"), _contar("sesion_bonos")), (0, 0, 0))

    def test_con_el_mismo_numero_de_bono_cada_catalogo_vende_lo_suyo(self):
        # El id 1 existe en las dos tablas, con tiempo y precio distintos: nunca
        # se confunden, porque cada camino lee SOLO su catálogo.
        bono_pc_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        self.assertEqual(bono_pc_id, self.bono_id)
        estacion_id = pcs_repo.crear_estacion("PC 1")

        venta_consola = self._vender(self.HORA)
        venta_pc = self._asignar_pc(estacion_id, bono_pc_id, self.HORA, 9000)

        ventas = {fila["id"]: fila for fila in ventas_repo.listar_ventas_recientes()}
        self.assertEqual((ventas[venta_consola]["total"], ventas[venta_consola]["origen"]),
                         (3000.0, dominio.ORIGEN_PLAYSTATION))
        self.assertEqual((ventas[venta_pc]["total"], ventas[venta_pc]["origen"]),
                         (9000.0, dominio.ORIGEN_ALQUILER_PCS))
        self.assertEqual(self._estado(self.HORA)["sesion"]["fecha_fin_prevista"], "2026-01-05T11:00:00")
        self.assertEqual(pcs_repo.estado_estaciones()[0]["sesion"]["fecha_fin_prevista"], "2026-01-05T13:00:00")

    def test_vender_en_un_lado_no_crea_sesiones_en_el_otro(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_pc_id = pcs_repo.crear_bono("3 horas", 180, 9000)

        self._vender(self.HORA)
        self.assertEqual((_contar("sesiones_playstation"), _contar("sesiones_pc"), _contar("sesion_bonos")), (1, 0, 0))

        self._asignar_pc(estacion_id, bono_pc_id, self.HORA, 9000)
        self.assertEqual((_contar("sesiones_playstation"), _contar("sesiones_pc"), _contar("sesion_bonos")), (1, 1, 1))
        self.assertEqual(_contar("sesion_playstation_bonos"), 1)

    def test_la_consola_no_es_una_estacion_de_pc(self):
        pcs_repo.crear_estacion("PC 1")
        self._vender(self.HORA)

        self.assertEqual([e["nombre"] for e in pcs_repo.listar_estaciones(solo_activas=False)], ["PC 1"])
        # El servidor de red (que atiende a los Clientes PC por nombre) no la encuentra.
        self.assertIsNone(pcs_repo.estado_de_estacion(dominio.NOMBRE_PLAYSTATION))
        self.assertTrue(all(item["dispositivo"] == dominio.DISPOSITIVO_PC for item in pcs_repo.estado_estaciones()))

        consola = self._estado(self.HORA)
        self.assertEqual(consola["dispositivo"], dominio.DISPOSITIVO_PLAYSTATION)
        self.assertEqual(consola["nombre"], "PLAYSTATION 5")

    def test_un_bono_de_pc_solo_va_a_una_pc_que_existe_y_esta_activa(self):
        bono_pc_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        estacion_id = pcs_repo.crear_estacion("PC 1")
        pcs_repo.desactivar_estacion(estacion_id)

        for estacion_invalida in (estacion_id, 9999):
            with self.assertRaises(ValueError):
                self._asignar_pc(estacion_invalida, bono_pc_id, self.HORA, 9000)
        self.assertEqual((_contar("ventas"), _contar("sesiones_pc")), (0, 0))


class TestVentasDeLaPlaystation(_ConPlaystation):
    def test_la_venta_queda_con_origen_playstation_y_enlazada_a_su_bono(self):
        venta_id = self._vender(self.HORA)

        venta = ventas_repo.buscar_venta(venta_id)[0]
        self.assertEqual(venta["origen"], dominio.ORIGEN_PLAYSTATION)
        self.assertEqual(venta["total"], 3000.0)
        self.assertEqual(venta["estado"], dominio.VENTA_CONFIRMADA)
        self.assertEqual(venta["usuario_id"], self.operadora_id)
        with database.conexion_db() as conexion:
            fila = conexion.execute("SELECT * FROM sesion_playstation_bonos").fetchone()
        self.assertEqual((fila["venta_id"], fila["bono_id"], fila["minutos"], fila["precio"]),
                         (venta_id, self.bono_id, 60, 3000.0))

    def test_se_puede_cobrar_en_efectivo_digital_o_mixto(self):
        pagos_mixtos = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0},
                        {"metodo": dominio.PAGO_DIGITAL, "monto": 2000.0}]
        venta_id = self._vender(self.HORA, pagos=pagos_mixtos)

        _, _, pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual({p["metodo"]: p["monto"] for p in pagos},
                         {dominio.PAGO_EFECTIVO: 1000.0, dominio.PAGO_DIGITAL: 2000.0})

    def test_los_pagos_tienen_que_cubrir_el_precio(self):
        with self.assertRaises(ValueError):
            self._vender(self.HORA, pagos=_efectivo(2000.0))
        self.assertEqual((_contar("ventas"), _contar("sesiones_playstation")), (0, 0))

    def test_un_bono_dado_de_baja_o_inexistente_no_se_vende(self):
        playstation_repo.desactivar_bono(self.admin_id, self.bono_id)

        for bono_id in (self.bono_id, 9999):
            with self.assertRaises(ValueError):
                self._vender(self.HORA, bono_id=bono_id, pagos=_efectivo(3000.0))
        self.assertEqual((_contar("ventas"), _contar("sesiones_playstation")), (0, 0))

    def test_si_la_venta_falla_no_queda_la_sesion_a_medio_grabar(self):
        with mock.patch("repositories.ventas_repo.registrar_venta_sin_detalle", side_effect=RuntimeError("falla")):
            with self.assertRaises(RuntimeError):
                self._vender(self.HORA)

        self.assertEqual((_contar("ventas"), _contar("sesiones_playstation"), _contar("sesion_playstation_bonos")),
                         (0, 0, 0))
        self.assertIsNone(self._estado(self.HORA)["sesion"])

    def test_el_historial_distingue_el_origen_de_cada_venta(self):
        playstation_repo_venta = self._vender(self.HORA)
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_pc_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = self.HORA
            datetime_mock.fromisoformat = datetime.fromisoformat
            venta_pc = pcs_repo.asignar_bono(estacion_id, bono_pc_id, self.operadora_id, _efectivo(3000.0))

        origenes = {fila["id"]: fila["origen"] for fila in ventas_repo.listar_ventas_recientes()}

        self.assertEqual(origenes, {playstation_repo_venta: dominio.ORIGEN_PLAYSTATION,
                                    venta_pc: dominio.ORIGEN_ALQUILER_PCS})
        self.assertEqual(dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION], "PlayStation 5")

    def test_la_actividad_reciente_muestra_la_consola_junto_a_las_pcs(self):
        self._vender(self.HORA)

        eventos = [(e["tipo"], e["estacion_nombre"]) for e in pcs_repo.actividad_reciente()]

        self.assertIn(("INICIO", "PLAYSTATION 5"), eventos)
        self.assertIn(("BONO", "PLAYSTATION 5"), eventos)

    def test_anular_la_venta_la_saca_de_la_caja_y_de_los_reportes(self):
        venta_id = self._vender(self.HORA)
        ventas_repo.anular_venta(venta_id, self.admin_id, "Se cobró de más")

        self.assertEqual(turnos_repo.resumen_turno_actual()["playstation_efectivo"], 0.0)
        fila = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-05")[0]
        self.assertEqual((fila["playstation"], fila["total"]), (0.0, 0.0))


class TestTiempoDeLaPlaystation(_ConPlaystation):
    def test_la_cuenta_regresiva_baja_con_el_reloj(self):
        self._vender(self.HORA)

        antes = self._estado(datetime(2026, 1, 5, 10, 0, 0))
        despues = self._estado(datetime(2026, 1, 5, 10, 45, 0))

        self.assertEqual(antes["segundos_restantes"], 3600)
        self.assertEqual(despues["segundos_restantes"], 15 * 60)
        self.assertFalse(despues["tiempo_agotado"])

    def test_sin_sesion_no_hay_cuenta_ni_aviso(self):
        estado = self._estado(self.HORA)

        self.assertIsNone(estado["sesion"])
        self.assertIsNone(estado["segundos_restantes"])
        self.assertFalse(estado["tiempo_agotado"])

    def test_al_llegar_a_cero_queda_avisando_y_no_se_libera_sola(self):
        self._vender(self.HORA)

        un_segundo_antes = self._estado(datetime(2026, 1, 5, 10, 59, 59))
        justo = self._estado(datetime(2026, 1, 5, 11, 0, 0))
        mucho_despues = self._estado(datetime(2026, 1, 5, 15, 0, 0))

        self.assertEqual((un_segundo_antes["segundos_restantes"], un_segundo_antes["tiempo_agotado"]), (1, False))
        self.assertEqual((justo["segundos_restantes"], justo["tiempo_agotado"]), (0, True))
        # A diferencia de una PC, la sesión sigue ahí (ACTIVA) hasta que alguien la libere.
        self.assertEqual((mucho_despues["segundos_restantes"], mucho_despues["tiempo_agotado"]), (0, True))
        self.assertEqual(mucho_despues["sesion"]["estado"], dominio.SESION_ACTIVA)

    def test_un_segundo_bono_con_la_sesion_en_curso_extiende_la_misma(self):
        self._vender(datetime(2026, 1, 5, 10, 0, 0))
        sesion_id = self._estado(self.HORA)["sesion"]["id"]

        self._vender(datetime(2026, 1, 5, 10, 20, 0))

        estado = self._estado(datetime(2026, 1, 5, 10, 20, 0))
        self.assertEqual(estado["sesion"]["id"], sesion_id)
        self.assertEqual(estado["sesion"]["fecha_fin_prevista"], "2026-01-05T12:00:00")
        self.assertEqual((_contar("sesiones_playstation"), _contar("sesion_playstation_bonos")), (1, 2))

    def test_vender_con_el_tiempo_agotado_cuenta_desde_ahora_y_apaga_el_aviso(self):
        self._vender(datetime(2026, 1, 5, 10, 0, 0))
        self.assertTrue(self._estado(datetime(2026, 1, 5, 11, 30, 0))["tiempo_agotado"])

        # Los clientes piden más tiempo media hora DESPUÉS de que se acabó el primero.
        self._vender(datetime(2026, 1, 5, 11, 30, 0))

        estado = self._estado(datetime(2026, 1, 5, 11, 30, 0))
        self.assertEqual(estado["sesion"]["fecha_fin_prevista"], "2026-01-05T12:30:00")
        self.assertEqual(estado["segundos_restantes"], 3600)
        self.assertFalse(estado["tiempo_agotado"])

    def test_el_tiempo_sigue_correcto_aunque_se_cierre_y_se_vuelva_a_abrir_el_programa(self):
        self._vender(self.HORA)

        # Se cierra el programa y se vuelve a abrir: arranca la base de cero y no
        # queda nada en memoria. El vencimiento está grabado como fecha absoluta.
        database.inicializar_base_de_datos()

        reabierto = self._estado(datetime(2026, 1, 5, 10, 30, 0))
        self.assertEqual(reabierto["segundos_restantes"], 30 * 60)
        self.assertFalse(reabierto["tiempo_agotado"])

        # Si mientras estuvo cerrado se acabó el tiempo, al abrir sigue avisando.
        self.assertTrue(self._estado(datetime(2026, 1, 5, 13, 0, 0))["tiempo_agotado"])

    def test_liberar_la_consola_apaga_el_aviso_y_deja_la_sesion_cerrada(self):
        self._vender(self.HORA)
        with _reloj(datetime(2026, 1, 5, 11, 5, 0)):
            playstation_repo.finalizar_sesion(self.operadora_id)

        estado = self._estado(datetime(2026, 1, 5, 11, 5, 0))
        self.assertIsNone(estado["sesion"])
        self.assertFalse(estado["tiempo_agotado"])
        with database.conexion_db() as conexion:
            sesion = conexion.execute("SELECT * FROM sesiones_playstation").fetchone()
        self.assertEqual((sesion["estado"], sesion["fecha_fin_real"]),
                         (dominio.SESION_FINALIZADA, "2026-01-05T11:05:00"))

    def test_liberar_sin_sesion_no_hace_nada(self):
        playstation_repo.finalizar_sesion(self.operadora_id)
        self.assertEqual(_contar("sesiones_playstation"), 0)

    def test_despues_de_liberar_la_proxima_venta_arranca_una_sesion_nueva(self):
        self._vender(self.HORA)
        primera = self._estado(self.HORA)["sesion"]["id"]
        with _reloj(self.HORA):
            playstation_repo.finalizar_sesion(self.operadora_id)

        self._vender(datetime(2026, 1, 5, 12, 0, 0))

        estado = self._estado(datetime(2026, 1, 5, 12, 0, 0))
        self.assertNotEqual(estado["sesion"]["id"], primera)
        self.assertEqual(estado["sesion"]["fecha_fin_prevista"], "2026-01-05T13:00:00")

    def test_la_base_no_deja_abrir_dos_sesiones_activas_a_la_vez(self):
        self._vender(self.HORA)

        with self.assertRaises(sqlite3.IntegrityError):
            with database.conexion_db() as conexion:
                conexion.execute(
                    "INSERT INTO sesiones_playstation (fecha_inicio, fecha_fin_prevista, estado) "
                    "VALUES ('2026-01-05T10:00:00', '2026-01-05T11:00:00', 'ACTIVA')"
                )


class TestCuentaDelTiempoCompartida(unittest.TestCase):
    """Las dos funciones de dominio que usan las PCs y la consola (una sola cuenta)."""

    def test_segundos_restantes_nunca_es_negativo(self):
        fin = datetime(2026, 1, 5, 11, 0, 0)
        self.assertEqual(dominio.segundos_restantes(fin, datetime(2026, 1, 5, 10, 59, 0)), 60)
        self.assertEqual(dominio.segundos_restantes(fin, fin), 0)
        self.assertEqual(dominio.segundos_restantes(fin, datetime(2026, 1, 5, 12, 0, 0)), 0)

    def test_fin_al_sumar_minutos(self):
        ahora = datetime(2026, 1, 5, 10, 0, 0)
        # Sin sesión: desde ahora.
        self.assertEqual(dominio.fin_al_sumar_minutos(None, 60, ahora), datetime(2026, 1, 5, 11, 0, 0))
        # Con sesión en curso: se suma a su vencimiento.
        self.assertEqual(dominio.fin_al_sumar_minutos(datetime(2026, 1, 5, 10, 30, 0), 60, ahora),
                         datetime(2026, 1, 5, 11, 30, 0))
        # Con sesión ya vencida: desde ahora, no desde el vencimiento viejo.
        self.assertEqual(dominio.fin_al_sumar_minutos(datetime(2026, 1, 5, 9, 0, 0), 60, ahora),
                         datetime(2026, 1, 5, 11, 0, 0))


class TestPlaystationEnCajaYReportes(_ConPlaystation):
    """La consola es un negocio más de la caja: su plata no se pierde ni se mezcla."""

    def _vender_pc(self, momento, monto, metodo=dominio.PAGO_EFECTIVO):
        estacion_id = pcs_repo.crear_estacion(f"PC {momento.isoformat()}")
        bono_id = pcs_repo.crear_bono(f"Bono {momento.isoformat()}", 60, monto)
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(estacion_id, bono_id, self.operadora_id, [{"metodo": metodo, "monto": monto}])

    def _cerrar(self, momento):
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return turnos_repo.cerrar_turno(self.operadora_id)

    def _resumen_del_dia(self, dia, ahora):
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = ahora
            datetime_mock.fromisoformat = datetime.fromisoformat
            return turnos_repo.resumen_del_dia(dia)

    def test_la_caja_cuenta_la_consola_como_un_negocio_aparte(self):
        self._vender(self.HORA)  # $3.000 en efectivo
        self._vender_pc(self.HORA, 2000.0, dominio.PAGO_DIGITAL)

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual((resumen["playstation_efectivo"], resumen["playstation_digital"]), (3000.0, 0.0))
        self.assertEqual((resumen["pcs_efectivo"], resumen["pcs_digital"]), (0.0, 2000.0))
        self.assertEqual((resumen["kiosko_efectivo"], resumen["kiosko_digital"]), (0.0, 0.0))
        # El efectivo del cajón incluye la consola.
        self.assertEqual((resumen["ventas_efectivo"], resumen["ventas_digital"]), (3000.0, 2000.0))
        self.assertEqual(resumen["caja_actual"], resumen["fondo_cambio"] + 3000.0)

    def test_el_cierre_de_turno_guarda_el_desglose_de_la_consola(self):
        self._vender(self.HORA, pagos=[{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0},
                                       {"metodo": dominio.PAGO_DIGITAL, "monto": 2000.0}])

        cierre = self._cerrar(datetime(2026, 1, 5, 14, 5, 0))

        self.assertEqual((cierre["playstation_efectivo"], cierre["playstation_digital"]), (1000.0, 2000.0))
        self.assertEqual(cierre["monto_a_retirar"], 1000.0)
        guardado = turnos_repo.listar_cierres()[0]
        self.assertEqual((guardado["playstation_efectivo"], guardado["playstation_digital"]), (1000.0, 2000.0))
        self.assertEqual((guardado["ventas_efectivo"], guardado["ventas_digital"]), (1000.0, 2000.0))

    def test_totales_separa_la_consola_y_las_columnas_suman_el_total(self):
        self._vender(self.HORA)
        self._vender_pc(datetime(2026, 1, 5, 11, 0, 0), 2000.0)

        fila = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-05")[0]

        self.assertEqual((fila["playstation"], fila["pcs"], fila["kiosko"]), (3000.0, 2000.0, 0.0))
        self.assertEqual(fila["total"], 5000.0)
        self.assertEqual(fila["total"], reportes_repo.resumen_ventas("2026-01-05", "2026-01-05")["total"])

    def test_totales_por_dia_y_por_turno_traen_la_consola(self):
        self._vender(datetime(2026, 1, 5, 9, 0, 0))
        self._vender(datetime(2026, 1, 6, 15, 0, 0))

        por_dia = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-06", "dia")
        por_turno = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-06", "turno")

        self.assertEqual([fila["playstation"] for fila in por_dia], [3000.0, 3000.0])
        self.assertEqual({fila["etiqueta"]: fila["playstation"] for fila in por_turno},
                         {"Mañana": 3000.0, "Tarde": 3000.0, "Noche": 0.0})

    def test_resumen_del_dia_muestra_la_consola_en_su_propia_columna(self):
        self._cerrar(datetime(2026, 1, 5, 6, 0, 0))  # punto de partida, sin ventas
        self._vender(datetime(2026, 1, 5, 9, 0, 0))
        self._cerrar(datetime(2026, 1, 5, 14, 5, 0))
        self._vender(datetime(2026, 1, 5, 15, 0, 0), pagos=[{"metodo": dominio.PAGO_DIGITAL, "monto": 3000.0}])

        resumen = self._resumen_del_dia(date(2026, 1, 5), datetime(2026, 1, 5, 16, 0, 0))
        manana, tarde = resumen["turnos"][0], resumen["turnos"][1]

        self.assertEqual((manana["playstation"], manana["kiosko"], manana["pcs"], manana["total"]),
                         (3000.0, 0.0, 0.0, 3000.0))
        self.assertEqual((manana["efectivo"], manana["digital"]), (3000.0, 0.0))
        self.assertEqual(tarde["estado"], turnos_repo.ESTADO_EN_CURSO)
        self.assertEqual((tarde["playstation"], tarde["efectivo"], tarde["digital"]), (3000.0, 0.0, 3000.0))
        total = resumen["total"]
        self.assertEqual(total["playstation"], 6000.0)
        self.assertEqual(
            total["kiosko"] + total["impresiones"] + total["tramites"] + total["pcs"] + total["playstation"],
            total["total"],
        )

    def test_el_ranking_incluye_los_bonos_de_la_consola(self):
        self._vender(datetime(2026, 1, 5, 9, 0, 0))
        self._vender(datetime(2026, 1, 5, 10, 0, 0))

        filas = [f for f in reportes_repo.ranking_ventas("2026-01-05", "2026-01-05")
                 if f["categoria"] == reportes_repo.CATEGORIA_BONO_PLAYSTATION]

        self.assertEqual([(f["descripcion"], f["cantidad"], f["importe"]) for f in filas], [("1 hora", 2, 6000.0)])


class TestCadaOrigenSumaEnLaCaja(BaseConBaseTemporal):
    """Red de seguridad: sumar un origen de venta nuevo y olvidarse de la caja
    haría "faltar" su plata en cada cierre, sin ningún error a la vista."""

    def test_toda_la_plata_de_cada_origen_entra_en_el_cajon_y_en_el_cierre(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", dominio.ROL_ADMIN)
        momento = datetime(2026, 1, 5, 10, 0, 0)
        with database.conexion_db() as conexion:
            for origen in dominio.ORIGENES_VENTA:
                ventas_repo.registrar_venta_sin_detalle(
                    conexion, usuario_id, 150.0,
                    [{"metodo": dominio.PAGO_EFECTIVO, "monto": 100.0},
                     {"metodo": dominio.PAGO_DIGITAL, "monto": 50.0}],
                    origen, momento,
                )
        cantidad = len(dominio.ORIGENES_VENTA)

        resumen = turnos_repo.resumen_turno_actual()
        self.assertEqual(resumen["ventas_efectivo"], 100.0 * cantidad)
        self.assertEqual(resumen["ventas_digital"], 50.0 * cantidad)
        self.assertEqual(sum(resumen[campo] for campo in turnos_repo._CAMPOS_PLATA), 150.0 * cantidad)

        turnos_repo.cerrar_turno(usuario_id)
        guardado = turnos_repo.listar_cierres()[0]
        self.assertEqual(guardado["ventas_efectivo"], 100.0 * cantidad)
        self.assertEqual(sum(guardado[campo] for campo in turnos_repo._CAMPOS_PLATA), 150.0 * cantidad)

    def test_cada_origen_tiene_sus_columnas_en_el_cierre(self):
        self.assertEqual(set(turnos_repo._PREFIJO_COLUMNAS_POR_ORIGEN), set(dominio.ORIGENES_VENTA))
        with database.conexion_db() as conexion:
            columnas = {fila["name"] for fila in conexion.execute("PRAGMA table_info(cierres_turno)")}
        self.assertTrue(set(turnos_repo._CAMPOS_PLATA) <= columnas)

    def test_el_esquema_de_ventas_admite_todos_los_origenes(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", dominio.ROL_ADMIN)
        with database.conexion_db() as conexion:
            for origen in dominio.ORIGENES_VENTA:
                ventas_repo.registrar_venta_sin_detalle(conexion, usuario_id, 10.0, [], origen, datetime(2026, 1, 5, 10, 0))
            with self.assertRaises(sqlite3.IntegrityError):
                ventas_repo.registrar_venta_sin_detalle(conexion, usuario_id, 10.0, [], "INVENTADO", datetime(2026, 1, 5, 10, 0))


class TestMigracionOrigenEnVentas(BaseConBaseTemporal):
    """database._migrar_check_origen_en_ventas: una base creada antes de la
    PlayStation 5 tiene el CHECK viejo en `ventas` y no deja grabar el origen nuevo."""

    def setUp(self):
        super().setUp()
        self.usuario_id = usuarios_repo.crear_usuario("Test", "1234", dominio.ROL_ADMIN)
        self._armar_base_vieja()

    def _armar_base_vieja(self):
        """Deja la base como la de una versión anterior: `ventas` con el CHECK de
        dos orígenes, y las ventas de antes (con sus pagos) apuntándole."""
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            self.venta_pc = pcs_repo.asignar_bono(
                estacion_id, bono_id, self.usuario_id, [{"metodo": "EFECTIVO", "monto": 3000.0}]
            )
        with database.conexion_db() as conexion:
            self.venta_kiosko = ventas_repo.registrar_venta_sin_detalle(
                conexion, self.usuario_id, 500.0, [{"metodo": "DIGITAL", "monto": 500.0}],
                dominio.ORIGEN_KIOSKO, datetime(2026, 1, 5, 11, 0, 0),
            )
        ventas_repo.anular_venta(self.venta_kiosko, self.usuario_id, "Prueba")

        sql_viejo = database._sql_tabla_ventas().replace(", 'PLAYSTATION'", "")
        self.assertNotIn("PLAYSTATION", sql_viejo)
        conexion = database.get_connection()
        try:
            conexion.execute("PRAGMA foreign_keys = OFF")
            filas = conexion.execute("SELECT * FROM ventas ORDER BY id").fetchall()
            conexion.execute("DROP TABLE ventas")
            conexion.execute(sql_viejo)
            for fila in filas:
                conexion.execute(
                    f"INSERT INTO ventas ({', '.join(database._COLUMNAS_VENTAS)}) "
                    f"VALUES ({', '.join('?' for _ in database._COLUMNAS_VENTAS)})",
                    tuple(fila[columna] for columna in database._COLUMNAS_VENTAS),
                )
            conexion.commit()
        finally:
            conexion.close()
        self.ventas_antes = self._ventas()

    def _ventas(self):
        with database.conexion_db() as conexion:
            return [tuple(fila) for fila in conexion.execute("SELECT * FROM ventas ORDER BY id").fetchall()]

    def _intentar_venta_playstation(self):
        with database.conexion_db() as conexion:
            return ventas_repo.registrar_venta_sin_detalle(
                conexion, self.usuario_id, 3000.0, [], dominio.ORIGEN_PLAYSTATION, datetime(2026, 1, 5, 12, 0)
            )

    def test_la_base_vieja_no_admite_el_origen_nuevo(self):
        with self.assertRaises(sqlite3.IntegrityError):
            self._intentar_venta_playstation()

    def test_al_arrancar_se_migra_y_no_se_pierde_ni_se_cambia_ninguna_venta(self):
        database.inicializar_base_de_datos()

        self.assertEqual(self._ventas(), self.ventas_antes)
        venta_nueva = self._intentar_venta_playstation()
        # La numeración sigue donde estaba: no se reutiliza ningún número de venta.
        self.assertGreater(venta_nueva, max(self.venta_pc, self.venta_kiosko))

    def test_lo_que_apuntaba_a_ventas_sigue_apuntando_a_ventas(self):
        database.inicializar_base_de_datos()

        with database.conexion_db() as conexion:
            self.assertEqual(conexion.execute("PRAGMA foreign_key_check").fetchall(), [])
            self.assertEqual(conexion.execute("PRAGMA integrity_check").fetchone()[0], "ok")
            # Las claves foráneas siguen vivas (apuntan a la tabla "ventas" nueva, no a una vieja).
            with self.assertRaises(sqlite3.IntegrityError):
                conexion.execute("INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (9999, 'EFECTIVO', 1)")
            self.assertEqual(
                conexion.execute("SELECT COUNT(*) FROM sesion_bonos WHERE venta_id = ?", (self.venta_pc,)).fetchone()[0], 1
            )
            tablas = {fila["name"] for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        self.assertTrue({"ventas_nueva", "ventas_viejo"}.isdisjoint(tablas))

    def test_recrea_los_indices_de_ventas_y_deja_la_tabla_con_el_esquema_nuevo(self):
        database.inicializar_base_de_datos()

        with database.conexion_db() as conexion:
            indices = {fila["name"] for fila in conexion.execute(
                "SELECT name FROM sqlite_master WHERE type = 'index' AND tbl_name = 'ventas'")}
            sql = conexion.execute("SELECT sql FROM sqlite_master WHERE name = 'ventas'").fetchone()["sql"]
        self.assertTrue({"idx_ventas_fecha", "idx_ventas_turno"} <= indices)
        for origen in dominio.ORIGENES_VENTA:
            self.assertIn(f"'{origen}'", sql)

    def test_deja_una_copia_de_seguridad_antes_de_tocar_nada(self):
        database.inicializar_base_de_datos()

        carpeta = os.path.join(database.DATA_DIR, "backups")
        copias = [nombre for nombre in os.listdir(carpeta) if nombre.startswith("antes_de_")]
        self.assertEqual(len(copias), 1)
        # La copia es la base ANTES de migrar: todavía con el CHECK viejo.
        copia = sqlite3.connect(os.path.join(carpeta, copias[0]))
        try:
            sql = copia.execute("SELECT sql FROM sqlite_master WHERE name = 'ventas'").fetchone()[0]
            ventas = copia.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]
        finally:
            copia.close()
        self.assertNotIn("PLAYSTATION", sql)
        self.assertEqual(ventas, len(self.ventas_antes))

    def test_correrla_de_nuevo_no_hace_nada(self):
        database.inicializar_base_de_datos()
        database.inicializar_base_de_datos()

        self.assertEqual(self._ventas(), self.ventas_antes)
        carpeta = os.path.join(database.DATA_DIR, "backups")
        self.assertEqual(len([n for n in os.listdir(carpeta) if n.startswith("antes_de_")]), 1)

    def test_si_algo_falla_a_mitad_de_camino_la_tabla_queda_como_estaba(self):
        conexion = database.get_connection()
        try:
            with mock.patch.object(database, "_COLUMNAS_VENTAS", ("id", "columna_que_no_existe")):
                with self.assertRaises(sqlite3.OperationalError):
                    database._migrar_check_origen_en_ventas(conexion)
            # Las claves foráneas vuelven a quedar activas aunque la migración haya fallado.
            self.assertEqual(conexion.execute("PRAGMA foreign_keys").fetchone()[0], 1)
            tablas = {fila["name"] for fila in conexion.execute("SELECT name FROM sqlite_master WHERE type = 'table'")}
        finally:
            conexion.close()
        self.assertNotIn("ventas_nueva", tablas)
        self.assertEqual(self._ventas(), self.ventas_antes)
        with self.assertRaises(sqlite3.IntegrityError):
            self._intentar_venta_playstation()  # sigue siendo la tabla vieja, sin ningún cambio a medias


if __name__ == "__main__":
    unittest.main()
