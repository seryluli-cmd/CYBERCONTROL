"""
tests/test_carga_con_sesion.py
==============================
Cargarle saldo a un socio que está usando una PC le suma el tiempo a esa sesión
(pedido del dueño, 2026-10-22: un socio con 20 minutos por delante cargó 13 h y
la PC siguió contando hasta cero; tuvo que cerrar sesión y volver a entrar). Ver
miembros_repo._sumar_carga_a_la_sesion.
"""

from datetime import datetime, timedelta
from unittest import mock

import dominio
from control_pcs.repositories import bonos_miembro_repo, miembros_repo, pcs_repo, reintegros_repo
from database import conexion_db
from repositories import config_repo, usuarios_repo
from base import BaseConBaseTemporal

TRECE_HORAS = 13 * 60


class TestCargaConSesion(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.operador = usuarios_repo.crear_usuario("Operador", "1234", dominio.ROL_EMPLEADA)
        self.pc = pcs_repo.crear_estacion("PC07")
        self.socio = miembros_repo.crear_miembro("rodrigo", "clave123", "Rodrigo", "30111222", "1155554444")
        self.bono_13h = bonos_miembro_repo.crear_bono("13 horas", TRECE_HORAS, 13000)

    def cargar(self, bono_id=None):
        return miembros_repo.cargar_saldo_por_bono(
            self.socio, bono_id or self.bono_13h, [{"metodo": "EFECTIVO", "monto": 13000}], self.operador
        )

    def entrar_con_media_hora(self):
        """El socio entra a la PC con 30 minutos de saldo (todo lo que tiene)."""
        self.cargar(bonos_miembro_repo.crear_bono("Media hora", 30, 500))
        return miembros_repo.abrir_estacion_por_miembro(self.pc, "rodrigo", "clave123")["sesion_id"]

    def sesion(self, sesion_id):
        with conexion_db() as conexion:
            return conexion.execute("SELECT * FROM sesiones_pc WHERE id = ?", (sesion_id,)).fetchone()

    def minutos_que_le_quedan(self, sesion_id):
        fin = datetime.fromisoformat(self.sesion(sesion_id)["fecha_fin_prevista"])
        return dominio.segundos_restantes(fin, datetime.now()) / 60

    def saldo(self):
        return miembros_repo.obtener_miembro(self.socio)["saldo_minutos"]

    def test_lo_cargado_pasa_a_la_sesion_que_esta_usando(self):
        sesion_id = self.entrar_con_media_hora()

        resultado = self.cargar()

        self.assertEqual(resultado["sumado_a_la_sesion"], {"estacion": "PC07", "minutos": TRECE_HORAS})
        self.assertEqual(self.saldo(), 0)
        self.assertAlmostEqual(self.minutos_que_le_quedan(sesion_id), 30 + TRECE_HORAS, delta=1)
        # Queda como un consumo de esa sesión, igual que al entrar: así lo cuentan
        # los reintegros y la reconexión de la PC.
        with conexion_db() as conexion:
            aportes = reintegros_repo.contribuciones_de_sesion(conexion, sesion_id)
        self.assertEqual([(a["tipo"], a["minutos"]) for a in aportes], [("SOCIO", 30), ("SOCIO", TRECE_HORAS)])

    def test_si_se_va_antes_se_le_devuelve_lo_que_no_uso(self):
        sesion_id = self.entrar_con_media_hora()
        self.cargar()

        pcs_repo.finalizar_sesion(sesion_id)

        # Le quedaban ~13 h 30 m: vuelve al saldo en bloques de 30 (hacia abajo).
        self.assertEqual(self.saldo(), TRECE_HORAS)

    def test_sin_sesion_va_al_saldo_como_siempre(self):
        resultado = self.cargar()
        self.assertIsNone(resultado["sumado_a_la_sesion"])
        self.assertEqual(self.saldo(), TRECE_HORAS)

    def test_una_sesion_que_ya_llego_a_cero_no_se_estira(self):
        sesion_id = self.entrar_con_media_hora()
        antes = (datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds")
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?", (antes, sesion_id))

        resultado = self.cargar()

        self.assertIsNone(resultado["sumado_a_la_sesion"])
        self.assertEqual(self.saldo(), TRECE_HORAS)
        self.assertEqual(self.sesion(sesion_id)["fecha_fin_prevista"], antes)

    def test_la_sesion_de_otro_socio_o_de_un_bono_no_se_toca(self):
        bono_pc = pcs_repo.crear_bono("1 hora", 60, 1500)
        pcs_repo.asignar_bono(self.pc, bono_pc, self.operador, [{"metodo": "EFECTIVO", "monto": 1500}])

        self.assertIsNone(self.cargar()["sumado_a_la_sesion"])
        self.assertEqual(self.saldo(), TRECE_HORAS)

    def test_con_una_reserva_por_delante_suma_hasta_la_reserva_y_lo_demas_queda_en_el_saldo(self):
        sesion_id = self.entrar_con_media_hora()
        hora = datetime.now() + timedelta(hours=3)
        with mock.patch("control_pcs.repositories.reservas_horario_repo.minutos_para_el_socio",
                        return_value=(150, hora)):
            resultado = self.cargar()

        self.assertEqual(resultado["sumado_a_la_sesion"]["minutos"], 150)
        self.assertEqual(self.saldo(), TRECE_HORAS - 150)
        self.assertAlmostEqual(self.minutos_que_le_quedan(sesion_id), 30 + 150, delta=1)

    def test_si_la_reserva_esta_muy_cerca_todo_queda_en_el_saldo(self):
        sesion_id = self.entrar_con_media_hora()
        with mock.patch("control_pcs.repositories.reservas_horario_repo.minutos_para_el_socio",
                        side_effect=ValueError("Esta PC está reservada")):
            resultado = self.cargar()

        self.assertIsNone(resultado["sumado_a_la_sesion"])
        self.assertEqual(self.saldo(), TRECE_HORAS)
        self.assertAlmostEqual(self.minutos_que_le_quedan(sesion_id), 30, delta=1)

    def test_por_monto_tambien(self):
        sesion_id = self.entrar_con_media_hora()
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])
        resultado = miembros_repo.cargar_saldo_por_monto(
            self.socio, 2000, [{"metodo": "EFECTIVO", "monto": 2000}], self.operador
        )

        self.assertEqual(resultado["sumado_a_la_sesion"], {"estacion": "PC07", "minutos": 120})
        self.assertAlmostEqual(self.minutos_que_le_quedan(sesion_id), 30 + 120, delta=1)
