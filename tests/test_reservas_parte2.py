"""
tests/test_reservas_parte2.py
===============================
RESERVAS, parte 2: "que el programa cuide la hora" (pedido del dueño,
2026-10-20; control_pcs/repositories/reservas_horario_repo.py). Las reglas del
dueño que se prueban acá:

- una PC puntual, PCSTREAM o la consola se ve RESERVADA 2 h antes de la hora y
  hasta la hora + los 20 minutos de tolerancia (celeste en el mosaico si está
  libre; en uso conserva su color y avisa "Res. 10:00");
- la pantalla de bloqueo de esa PC recibe el cartel en GET /estado;
- venderle a otro cliente un bono que se pasa de la hora AVISA (no frena);
- un socio entra a una PC reservada solo hasta la hora, y lo demás le queda en
  el saldo;
- "Cualquier PC disponible" no aparta ninguna PC: va en un aviso arriba del
  mosaico con cuántas PCs libres hay.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import date, datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
import servidor_red  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    miembros_repo, pcs_repo, pcstream_repo, playstation_repo, reservas_habilitar_repo, reservas_horario_repo,
    reservas_repo,
)
from control_pcs.ui import pcs_window  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _manana_a_las(hora, minuto=0):
    """Mañana a esa hora: siempre en el futuro, corra la prueba cuando corra."""
    return datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=hora, minute=minuto)


def _en(minutos):
    """Dentro de tantos minutos, sin segundos (así se guarda una reserva)."""
    return (datetime.now() + timedelta(minutes=minutos)).replace(second=0, microsecond=0)


class _ConReservas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.pcstream = pcs_repo.crear_estacion("PCSTREAM")
        self.promo = pcs_repo.crear_bono("Promo 10 hs", 600, 10000.0)
        self.una_hora = pcs_repo.crear_bono("1 hora", 60, 1500.0)
        self.bono_stream = pcstream_repo.crear_bono("3 hs PCSTREAM", 180, 4500.0)
        self.bono_ps5 = playstation_repo.crear_bono(self.admin, "2 horas PS5", 120, 6000.0)

    def _reservar(self, cuando, equipo=dominio.EQUIPO_RESERVA_PC, estacion="pc1", bono=None, cliente="Juan Pérez"):
        estacion_id = getattr(self, estacion) if estacion else None
        return reservas_repo.crear_reserva(
            self.ana, cliente, "11 5555-4444", equipo, estacion_id, bono or self.promo, cuando, 1000.0,
            _efectivo(1000.0),
        )

    def _estacion(self, estacion_id):
        return pcs_repo.obtener_estacion(estacion_id)

    def _pendientes(self, ahora):
        with conexion_db() as conexion:
            return reservas_horario_repo.pendientes(conexion, ahora)


class TestCuandoSeVeReservada(_ConReservas):
    def test_se_ve_reservada_dos_horas_antes_y_hasta_los_20_minutos_de_tolerancia(self):
        self._reservar(_manana_a_las(10))

        self.assertFalse(self._pendientes(_manana_a_las(7, 59))[0]["marcada"])
        self.assertTrue(self._pendientes(_manana_a_las(8))[0]["marcada"])
        self.assertTrue(self._pendientes(_manana_a_las(10, 20))[0]["marcada"])
        # Pasada la tolerancia ya no espera a nadie (al listarla pasa a No vino).
        self.assertEqual(self._pendientes(_manana_a_las(10, 21)), [])

    def test_una_reserva_que_ya_no_esta_pendiente_no_aparta_nada(self):
        reserva = self._reservar(_manana_a_las(10))
        reservas_repo.marcar_no_vino(reserva, self.ana)

        self.assertEqual(self._pendientes(_manana_a_las(9)), [])

    def test_cada_reserva_aparta_solo_su_equipo(self):
        self._reservar(_manana_a_las(10), estacion="pc1", cliente="Juan")
        self._reservar(_manana_a_las(10), equipo=dominio.EQUIPO_RESERVA_PCSTREAM, estacion=None,
                       bono=self.bono_stream, cliente="Lucas")
        self._reservar(_manana_a_las(10), equipo=dominio.EQUIPO_RESERVA_PLAYSTATION, estacion=None,
                       bono=self.bono_ps5, cliente="Mía")
        self._reservar(_manana_a_las(10), estacion=None, cliente="Marta")  # cualquier PC disponible
        reservas = self._pendientes(_manana_a_las(9))

        self.assertEqual(reservas_horario_repo.proxima(reservas, self._estacion(self.pc1))["cliente"], "Juan")
        self.assertIsNone(reservas_horario_repo.proxima(reservas, self._estacion(self.pc2)))
        self.assertEqual(reservas_horario_repo.proxima(reservas, self._estacion(self.pcstream))["cliente"], "Lucas")
        self.assertEqual(reservas_horario_repo.proxima(reservas)["cliente"], "Mía")
        self.assertEqual([r["cliente"] for r in reservas_horario_repo.sin_pc_fija(reservas)], ["Marta"])

    def test_la_hora_se_nombra_hoy_manana_o_con_el_dia(self):
        ahora = datetime(2026, 10, 21, 23, 0)
        self.assertEqual(reservas_horario_repo.texto_de_la_hora(datetime(2026, 10, 21, 23, 30), ahora), "hoy 23:30")
        self.assertEqual(reservas_horario_repo.texto_de_la_hora(datetime(2026, 10, 22, 0, 30), ahora),
                         "mañana 00:30")
        self.assertEqual(reservas_horario_repo.texto_de_la_hora(datetime(2026, 10, 25, 10, 0), ahora), "25/10 10:00")


class TestCartelDeLaPantallaDeBloqueo(_ConReservas):
    def test_el_cartel_llega_recien_dos_horas_antes_y_solo_a_esa_pc(self):
        self._reservar(_manana_a_las(10))

        self.assertIsNone(reservas_horario_repo.cartel_para_la_pc(self._estacion(self.pc1), _manana_a_las(7)))
        self.assertEqual(
            reservas_horario_repo.cartel_para_la_pc(self._estacion(self.pc1), _manana_a_las(8, 30)),
            {"cliente": "Juan Pérez", "inicio": _manana_a_las(10).isoformat(timespec="seconds")},
        )
        self.assertIsNone(reservas_horario_repo.cartel_para_la_pc(self._estacion(self.pc2), _manana_a_las(8, 30)))

    def test_una_reserva_sin_pc_fija_no_pone_cartel_en_ninguna(self):
        self._reservar(_manana_a_las(10), estacion=None)

        for estacion in (self.pc1, self.pc2, self.pcstream):
            self.assertIsNone(reservas_horario_repo.cartel_para_la_pc(self._estacion(estacion), _manana_a_las(9)))


class TestAvisoAlVender(_ConReservas):
    def test_avisa_si_el_bono_se_pasa_de_la_hora_de_la_reserva(self):
        self._reservar(_manana_a_las(10))

        aviso = reservas_horario_repo.aviso_al_vender(self.pc1, 180, _manana_a_las(8))

        self.assertIn("PC1 está reservada para Juan Pérez hoy 10:00", aviso)
        self.assertIn("hasta las 11:00", aviso)

    def test_un_bono_que_termina_antes_de_la_hora_no_avisa(self):
        self._reservar(_manana_a_las(10))

        self.assertIsNone(reservas_horario_repo.aviso_al_vender(self.pc1, 60, _manana_a_las(8)))
        self.assertIsNone(reservas_horario_repo.aviso_al_vender(self.pc2, 600, _manana_a_las(8)))

    def test_sumarle_tiempo_a_una_sesion_en_curso_cuenta_desde_que_termina(self):
        self._reservar(_en(90))
        pcs_repo.asignar_bono(self.pc1, self.una_hora, self.ana, _efectivo(1500.0))  # hasta dentro de 60 min

        self.assertIsNone(reservas_horario_repo.aviso_al_vender(self.pc1, 15))
        self.assertIsNotNone(reservas_horario_repo.aviso_al_vender(self.pc1, 60))

    def test_la_playstation_y_pcstream_tambien_avisan(self):
        self._reservar(_manana_a_las(10), equipo=dominio.EQUIPO_RESERVA_PLAYSTATION, estacion=None,
                       bono=self.bono_ps5)
        self._reservar(_manana_a_las(10), equipo=dominio.EQUIPO_RESERVA_PCSTREAM, estacion=None,
                       bono=self.bono_stream)

        self.assertIn(dominio.NOMBRE_PLAYSTATION, reservas_horario_repo.aviso_al_vender(None, 180, _manana_a_las(8)))
        self.assertIn("PCSTREAM", reservas_horario_repo.aviso_al_vender(self.pcstream, 180, _manana_a_las(8)))

    def test_avisar_no_impide_vender(self):
        # Es un aviso para el operador: si decide cobrar igual, se vende.
        self._reservar(_en(30))

        pcs_repo.asignar_bono(self.pc1, self.una_hora, self.ana, _efectivo(1500.0))

        self.assertIsNotNone(pcs_repo.estado_estaciones()[1]["sesion"])


class TestSocioEnUnaPcReservada(_ConReservas):
    def setUp(self):
        super().setUp()
        self.socio = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

    def _poner_saldo(self, minutos):
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, self.socio))

    def _saldo(self):
        return miembros_repo.obtener_miembro(self.socio)["saldo_minutos"]

    def _sesion(self, estacion_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?", (estacion_id, dominio.SESION_ACTIVA)
            ).fetchone()

    def test_entra_solo_hasta_la_hora_y_lo_demas_le_queda_en_el_saldo(self):
        self._poner_saldo(300)
        inicio = _en(60)
        self._reservar(inicio)

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertGreaterEqual(resumen["minutos_usados"], 57)
        self.assertLessEqual(resumen["minutos_usados"], 60)
        self.assertEqual(self._saldo(), 300 - resumen["minutos_usados"])
        self.assertLessEqual(datetime.fromisoformat(self._sesion(self.pc1)["fecha_fin_prevista"]), inicio)
        self.assertEqual(resumen["hasta_la_reserva"], f"{inicio:%H:%M}")

    def test_si_quedaria_muy_poco_no_entra_y_no_se_le_toca_el_saldo(self):
        self._poner_saldo(300)
        self._reservar(_en(10))

        with self.assertRaisesRegex(ValueError, "reservada"):
            miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertEqual(self._saldo(), 300)
        self.assertIsNone(self._sesion(self.pc1))

    def test_si_su_saldo_termina_antes_de_la_reserva_usa_todo_como_siempre(self):
        self._poner_saldo(60)
        self._reservar(_en(180))

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertEqual((resumen["minutos_usados"], resumen["hasta_la_reserva"], self._saldo()), (60, None, 0))

    def test_la_reserva_de_otra_pc_no_lo_corta(self):
        self._poner_saldo(300)
        self._reservar(_en(60), estacion="pc2")

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertEqual(resumen["minutos_usados"], 300)

    def test_si_no_vino_y_paso_la_tolerancia_la_pc_vuelve_a_ser_libre(self):
        self._poner_saldo(300)
        reserva = self._reservar(_en(60))
        with conexion_db() as conexion:
            conexion.execute("UPDATE reservas SET fecha_reserva = ? WHERE id = ?",
                             (_en(-25).isoformat(timespec="seconds"), reserva))

        self.assertEqual(miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")["minutos_usados"], 300)


class TestHabilitarEnUnaPcReservadaParaOtro(_ConReservas):
    def test_la_pc_reservada_para_otro_se_avisa_y_va_al_final(self):
        sin_pc_fija = self._reservar(_en(30), estacion=None, cliente="Marta")
        self._reservar(_en(90), estacion="pc1", cliente="Juan")  # Marta, con 10 hs, la pisaría

        lugares = reservas_habilitar_repo.lugares_para_habilitar(sin_pc_fija)

        self.assertEqual([lugar["nombre"] for lugar in lugares], ["PC2", "PC1"])
        self.assertIsNone(lugares[0]["reservada_para"])
        self.assertTrue(lugares[1]["reservada_para"].startswith("Juan "))

    def test_la_propia_reserva_no_cuenta_como_de_otro(self):
        reserva = self._reservar(_en(30), estacion="pc1")

        lugares = reservas_habilitar_repo.lugares_para_habilitar(reserva)

        self.assertEqual(lugares[0]["nombre"], "PC1")
        self.assertIsNone(lugares[0]["reservada_para"])


class TestMosaico(_ConReservas):
    def _grilla(self):
        grilla = PanelControlPcs(usuarios_repo.obtener_usuario(self.admin))
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def _ficha(self, grilla, nombre):
        for fila in range(grilla.mosaico.count()):
            if grilla.mosaico.ficha(fila).nombre == nombre:
                return grilla.mosaico.ficha(fila)
        self.fail(f"No está {nombre} en el mosaico")

    def test_la_pc_libre_reservada_se_ve_celeste_con_el_cliente_y_la_hora(self):
        pcs_repo.registrar_conexion(self.pc1)
        inicio = _en(60)
        self._reservar(inicio)

        ficha = self._ficha(self._grilla(), "PC1")

        self.assertEqual(ficha.color, pcs_window.COLOR_RESERVADA)
        self.assertEqual(ficha.aviso, f"Juan Pérez {inicio:%H:%M}")
        self.assertIn("Reservada para Juan Pérez", ficha.estado)
        self.assertIn((pcs_window.COLOR_RESERVADA, "Reservada"), pcs_window.LEYENDA)

    def test_falta_mas_de_dos_horas_y_se_ve_disponible(self):
        pcs_repo.registrar_conexion(self.pc1)
        self._reservar(_en(150))

        self.assertEqual(self._ficha(self._grilla(), "PC1").color, pcs_window.COLOR_DISPONIBLE)

    def test_la_pc_en_uso_conserva_su_color_y_avisa_la_hora(self):
        pcs_repo.registrar_conexion(self.pc1)
        inicio = _en(90)
        self._reservar(inicio)
        pcs_repo.asignar_bono(self.pc1, self.una_hora, self.ana, _efectivo(1500.0))

        ficha = self._ficha(self._grilla(), "PC1")

        self.assertEqual(ficha.color, pcs_window.COLOR_EN_USO)
        self.assertEqual(ficha.aviso, f"Res. {inicio:%H:%M}")

    def test_la_playstation_libre_reservada_tambien_se_ve_celeste(self):
        self._reservar(_en(60), equipo=dominio.EQUIPO_RESERVA_PLAYSTATION, estacion=None, bono=self.bono_ps5)

        self.assertEqual(self._ficha(self._grilla(), dominio.NOMBRE_PLAYSTATION).color, pcs_window.COLOR_RESERVADA)

    def test_las_de_cualquier_pc_van_en_el_aviso_de_arriba_con_las_libres(self):
        for estacion in (self.pc1, self.pc2, self.pcstream):
            pcs_repo.registrar_conexion(estacion)
        self._reservar(_en(60), estacion=None, cliente="Marta")
        self._reservar(_en(60), estacion="pc1", cliente="Juan")

        grilla = self._grilla()

        self.assertFalse(grilla.aviso_reservas.isHidden())
        self.assertIn("Marta", grilla.aviso_reservas.text())
        # PC2 es la única libre para Marta: PC1 está reservada y PCSTREAM tiene sus precios.
        self.assertIn("libres ahora: 1", grilla.aviso_reservas.text())
        # Y ninguna PC se pinta por la reserva de Marta.
        self.assertEqual(self._ficha(grilla, "PC2").color, pcs_window.COLOR_DISPONIBLE)

    def test_sin_reservas_sin_pc_fija_el_aviso_no_se_ve(self):
        self.assertTrue(self._grilla().aviso_reservas.isHidden())


class TestServidorRedReservas(test_control_pcs._ConServidorRed):
    """El cartel viaja en GET /estado y el corte del socio en POST /login, con el servidor real."""

    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        pcs_repo.crear_estacion("PC2")
        self.inicio = _en(60)
        bono = pcs_repo.crear_bono("Promo 10 hs", 600, 10000.0)
        reservas_repo.crear_reserva(self.ana, "Juan", "", dominio.EQUIPO_RESERVA_PC, self.pc1, bono, self.inicio,
                                    5000.0, _efectivo(5000.0))

    def test_estado_trae_la_reserva_solo_a_la_pc_reservada(self):
        _, datos = self._get("/estado?estacion=PC1")
        self.assertEqual(datos["reserva"], {"cliente": "Juan", "inicio": self.inicio.isoformat(timespec="seconds")})

        _, datos = self._get("/estado?estacion=PC2")
        self.assertIsNone(datos["reserva"])

    def test_si_falla_leer_la_reserva_el_estado_contesta_igual(self):
        with mock.patch.object(reservas_horario_repo, "cartel_para_la_pc", side_effect=OSError("disco roto")), \
                mock.patch.object(servidor_red, "registrar_error"):
            status, datos = self._get("/estado?estacion=PC1")

        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertNotIn("reserva", datos)

    def test_el_login_del_socio_dice_hasta_que_hora(self):
        socio = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 300 WHERE id = ?", (socio,))

        status, datos = self._post("/login", {"estacion": "PC1", "usuario": "juan", "clave": "clave123"})

        self.assertEqual(status, 200)
        self.assertEqual(datos["hasta_la_reserva"], f"{self.inicio:%H:%M}")
