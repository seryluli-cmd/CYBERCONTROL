"""
tests/test_ofertas.py
=====================
Las ofertas 2x1 y 50% en los bonos, por día y turno (pedido del dueño, 2026-11-13;
ver control_pcs/repositories/ofertas_repo.py). Lo que se prueba: la Noche que cruza la
medianoche, el domingo con T1 y T2, las fechas (la Noche del último día entra entera),
que dos ofertas no toquen el mismo bono en el mismo turno, que solo el Administrador las
arme, las cuentas del 2x1 y del 50%, que se cobre con la oferta de la hora del cobro
(PCs, PCSTREAM, PlayStation 5 y la Cuenta de la PC) y que quitar un bono con oferta le
saque el tiempo que sumó de verdad. Y lo que NO lleva oferta: socios y reservas.

El 13/11/2026 es viernes: las pruebas usan esa semana con la hora fija.
"""

import contextlib
import sqlite3
from datetime import date, datetime, timedelta
from unittest import mock

import database
import database_migraciones
import dominio
from admin_remoto import lista_blanca
from control_pcs.repositories import (
    anular_bono_repo, cuentas_pc_repo, ofertas_repo, pcs_repo, pcstream_repo, playstation_repo,
    reservas_habilitar_repo, reservas_repo,
)
from database import conexion_db
from repositories import usuarios_repo
from base import BaseConBaseTemporal

PC, PCSTREAM, PS5 = dominio.EQUIPO_RESERVA_PC, dominio.EQUIPO_RESERVA_PCSTREAM, dominio.EQUIPO_RESERVA_PLAYSTATION
LUN, MAR, MIE, JUE, VIE, SAB, DOM = range(7)
MANANA, TARDE, NOCHE = dominio.TURNO_MANANA, dominio.TURNO_TARDE, dominio.TURNO_NOCHE

VIERNES = date(2026, 11, 13)
SABADO = date(2026, 11, 14)
DOMINGO = date(2026, 11, 15)


def _a_las(dia: date, hora: int, minuto: int = 0, segundo: int = 0) -> datetime:
    return datetime(dia.year, dia.month, dia.day, hora, minuto, segundo)


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _oferta(tipo=dominio.OFERTA_2X1, desde=VIERNES, hasta=VIERNES, franjas=((VIE, NOCHE),), bonos=(), pausada=False,
            terminada=None, id=1, nombre="Prueba"):
    """Una oferta como la devuelve el repo, para las cuentas que no tocan la base."""
    return {"id": id, "nombre": nombre, "tipo": tipo, "desde": desde, "hasta": hasta, "franjas": list(franjas),
            "bonos": list(bonos), "pausada": pausada, "terminada_fecha": terminada}


@contextlib.contextmanager
def reloj(momento: datetime):
    """La hora del programa fija en `momento`, en los repos que venden y en el de las
    ofertas. Con una subclase de datetime (y no un Mock): el repo pregunta isinstance."""

    class _Reloj(datetime):
        @classmethod
        def now(cls, tz=None):
            return momento

    with contextlib.ExitStack() as pila:
        for modulo in ("ofertas_repo", "pcs_repo", "playstation_repo", "cuentas_pc_repo", "anular_bono_repo"):
            pila.enter_context(mock.patch(f"control_pcs.repositories.{modulo}.datetime", _Reloj))
        yield


# ---------------------------------------------------------------------------
# Las cuentas y la semana (sin base)
# ---------------------------------------------------------------------------

class TestLasCuentas(BaseConBaseTemporal):
    def test_2x1_da_el_doble_de_tiempo_por_la_misma_plata(self):
        self.assertEqual(ofertas_repo.con_oferta(dominio.OFERTA_2X1, 180, 6700.0), (360, 6700.0))

    def test_50_es_el_mismo_tiempo_a_mitad_de_precio_redondeado_al_peso(self):
        self.assertEqual(ofertas_repo.con_oferta(dominio.OFERTA_MITAD, 180, 6700.0), (180, 3350.0))
        self.assertEqual(ofertas_repo.con_oferta(dominio.OFERTA_MITAD, 60, 8001.0), (60, 4001.0))
        self.assertEqual(ofertas_repo.con_oferta(dominio.OFERTA_MITAD, 60, 999.0), (60, 500.0))

    def test_la_semana_tiene_tres_turnos_de_lunes_a_sabado_y_dos_el_domingo(self):
        franjas = ofertas_repo.franjas_de_la_semana()
        self.assertEqual(len(franjas), 6 * 3 + 2)
        self.assertEqual([turno for dia, turno in franjas if dia == DOM], [MANANA, NOCHE])
        self.assertEqual(ofertas_repo.nombre_de_la_franja(DOM, MANANA), "T1 (06 a 18)")
        self.assertEqual(ofertas_repo.nombre_de_la_franja(DOM, NOCHE), "T2 (18 a 06)")
        self.assertEqual(ofertas_repo.nombre_de_la_franja(VIE, NOCHE), "Noche (22 a 06)")

    def test_la_madrugada_es_la_noche_del_dia_anterior(self):
        self.assertEqual(ofertas_repo.franja_de(_a_las(SABADO, 3)), (VIE, NOCHE))
        self.assertEqual(ofertas_repo.franja_de(_a_las(VIERNES, 21, 59)), (VIE, TARDE))
        # El lunes a las 03:00 todavía es "Domingo T2".
        self.assertEqual(ofertas_repo.franja_de(_a_las(DOMINGO + timedelta(days=1), 3)), (DOM, NOCHE))
        self.assertEqual(ofertas_repo.franja_de(_a_las(DOMINGO, 17, 59)), (DOM, MANANA))
        self.assertEqual(ofertas_repo.franja_de(_a_las(DOMINGO, 18)), (DOM, NOCHE))


class TestCuandoCorre(BaseConBaseTemporal):
    def test_la_noche_del_viernes_va_del_viernes_22_al_sabado_06(self):
        oferta = _oferta(franjas=[(VIE, NOCHE)], desde=VIERNES, hasta=VIERNES)
        self.assertFalse(ofertas_repo.aplica_en(oferta, _a_las(VIERNES, 21, 59)))
        self.assertTrue(ofertas_repo.aplica_en(oferta, _a_las(VIERNES, 22)))
        # Pasada la medianoche sigue: la Noche del último día entra entera.
        self.assertTrue(ofertas_repo.aplica_en(oferta, _a_las(SABADO, 5, 59)))
        self.assertFalse(ofertas_repo.aplica_en(oferta, _a_las(SABADO, 6)))
        self.assertEqual(ofertas_repo.hasta_cuando(oferta, _a_las(VIERNES, 23)), _a_las(SABADO, 6))

    def test_la_madrugada_del_primer_dia_es_de_la_noche_anterior_y_no_entra(self):
        oferta = _oferta(franjas=[(VIE, NOCHE), (JUE, NOCHE)], desde=VIERNES, hasta=VIERNES + timedelta(days=7))
        # El viernes 13 a las 02:00 es la Noche del jueves 12: antes del DESDE.
        self.assertFalse(ofertas_repo.aplica_en(oferta, _a_las(VIERNES, 2)))
        self.assertTrue(ofertas_repo.aplica_en(oferta, _a_las(VIERNES, 23)))

    def test_el_domingo_tiene_t1_de_06_a_18_y_t2_de_18_a_06(self):
        t1 = _oferta(franjas=[(DOM, MANANA)], desde=DOMINGO, hasta=DOMINGO)
        t2 = _oferta(franjas=[(DOM, NOCHE)], desde=DOMINGO, hasta=DOMINGO)
        self.assertTrue(ofertas_repo.aplica_en(t1, _a_las(DOMINGO, 6)))
        self.assertTrue(ofertas_repo.aplica_en(t1, _a_las(DOMINGO, 17, 59)))
        self.assertFalse(ofertas_repo.aplica_en(t1, _a_las(DOMINGO, 18)))
        self.assertTrue(ofertas_repo.aplica_en(t2, _a_las(DOMINGO, 18)))
        self.assertTrue(ofertas_repo.aplica_en(t2, _a_las(DOMINGO + timedelta(days=1), 5, 59)))
        # El domingo a las 03:00 es la Noche del SÁBADO, no la del domingo.
        self.assertFalse(ofertas_repo.aplica_en(t2, _a_las(DOMINGO, 3)))

    def test_fuera_de_las_fechas_no_corre(self):
        oferta = _oferta(franjas=[(VIE, NOCHE)], desde=VIERNES, hasta=VIERNES + timedelta(days=7))
        self.assertFalse(ofertas_repo.aplica_en(oferta, _a_las(VIERNES - timedelta(days=7), 23)))
        self.assertTrue(ofertas_repo.aplica_en(oferta, _a_las(VIERNES + timedelta(days=7), 23)))
        self.assertFalse(ofertas_repo.aplica_en(oferta, _a_las(VIERNES + timedelta(days=14), 23)))

    def test_pausada_o_terminada_no_corre(self):
        self.assertFalse(ofertas_repo.aplica_en(_oferta(pausada=True), _a_las(VIERNES, 23)))
        terminada = _oferta(terminada=_a_las(VIERNES, 23))
        self.assertTrue(ofertas_repo.aplica_en(terminada, _a_las(VIERNES, 22, 30)))
        self.assertFalse(ofertas_repo.aplica_en(terminada, _a_las(VIERNES, 23)))

    def test_turnos_seguidos_son_una_sola_vez(self):
        oferta = _oferta(franjas=[(SAB, TARDE), (SAB, NOCHE)], desde=VIERNES, hasta=SABADO + timedelta(days=7))
        veces = ofertas_repo.proximas_veces(oferta, _a_las(VIERNES, 12))
        self.assertEqual(veces[0], (_a_las(SABADO, 14), _a_las(DOMINGO, 6)))
        self.assertEqual(len(veces), 2)
        self.assertEqual(ofertas_repo.hasta_cuando(oferta, _a_las(SABADO, 15)), _a_las(DOMINGO, 6))

    def test_el_estado_sale_de_la_hora(self):
        oferta = _oferta(franjas=[(VIE, NOCHE)], desde=VIERNES, hasta=VIERNES)
        self.assertEqual(ofertas_repo.estado(oferta, _a_las(VIERNES, 12)), dominio.OFERTA_PROGRAMADA)
        self.assertEqual(ofertas_repo.estado(oferta, _a_las(SABADO, 1)), dominio.OFERTA_ACTIVA)
        self.assertEqual(ofertas_repo.estado(oferta, _a_las(SABADO, 6)), dominio.OFERTA_TERMINADA)
        oferta["pausada"] = True
        self.assertEqual(ofertas_repo.estado(oferta, _a_las(VIERNES, 23)), dominio.OFERTA_PAUSADA)

    def test_la_frase_dice_la_oferta_en_castellano(self):
        oferta = _oferta(franjas=[(VIE, NOCHE), (SAB, NOCHE)], desde=VIERNES, hasta=date(2026, 11, 30),
                         bonos=[(PC, 2), (PC, 3), (PS5, 1)])
        nombres = {(PC, 2): "Promo 3hs", (PC, 3): "Promo 5hs", (PS5, 1): "Promo 2hs"}
        self.assertEqual(
            ofertas_repo.frase(oferta, nombres),
            "2x1 en Promo 3hs y Promo 5hs de las PCs y Promo 2hs de la PlayStation 5, los viernes y sábados "
            "en el turno Noche (22 a 06), del 13/11 al 30/11.",
        )
        un_dia = _oferta(tipo=dominio.OFERTA_MITAD, franjas=[(SAB, TARDE), (SAB, NOCHE)], desde=SABADO,
                         hasta=SABADO, bonos=[(PC, 2)])
        self.assertEqual(ofertas_repo.frase(un_dia, nombres),
                         "50% en Promo 3hs de las PCs, el sábado 14/11 en los turnos Tarde (14 a 22) y "
                         "Noche (22 a 06).")
        semana = _oferta(franjas=[(dia, TARDE) for dia in range(5)] + [(DOM, MANANA)], hasta=VIERNES + timedelta(7),
                         bonos=[(PC, 2)])
        self.assertIn("de lunes a viernes en el turno Tarde (14 a 22) y los domingos en el turno T1 (06 a 18)",
                      ofertas_repo.frase(semana, nombres))

    def test_cada_proxima_vez_se_dice_con_su_dia_y_su_hora(self):
        ahora = _a_las(VIERNES, 23)
        self.assertEqual(ofertas_repo.frase_de_la_vez(_a_las(VIERNES, 22), _a_las(SABADO, 6), ahora),
                         "Hoy, viernes 13/11, de 22:00 a 06:00 — andando ahora")
        self.assertEqual(ofertas_repo.frase_de_la_vez(_a_las(SABADO, 22), _a_las(DOMINGO, 6), ahora, ultima=True),
                         "Sábado 14/11, de 22:00 a 06:00 — la última")
        # A la madrugada sigue siendo "hoy" la Noche que empezó ayer.
        self.assertTrue(ofertas_repo.frase_de_la_vez(_a_las(VIERNES, 22), _a_las(SABADO, 6),
                                                     _a_las(SABADO, 3)).startswith("Hoy, viernes"))
        # Turnos seguidos de varios días: desde y hasta con su día.
        self.assertEqual(ofertas_repo.frase_de_la_vez(_a_las(SABADO, 14), _a_las(DOMINGO + timedelta(1), 6), ahora),
                         "Del sábado 14/11 a las 14:00 al lunes 16/11 a las 06:00")
        # Y si empieza hoy, "desde hoy ... hasta el ..." (no "Del hoy, ...").
        self.assertEqual(ofertas_repo.frase_de_la_vez(_a_las(SABADO, 22), _a_las(DOMINGO + timedelta(1), 6),
                                                      _a_las(SABADO, 21)),
                         "Desde hoy, sábado 14/11 a las 22:00, hasta el lunes 16/11 a las 06:00")
        # Un día entero dice hasta qué día: "de 14:00 a 14:00" parecería que no dura nada.
        self.assertEqual(ofertas_repo.frase_de_la_vez(_a_las(VIERNES, 14), _a_las(SABADO, 14), _a_las(VIERNES, 15)),
                         "Desde hoy, viernes 13/11 a las 14:00, hasta el sábado 14/11 a las 14:00 — andando ahora")

    def test_un_bono_de_otro_catalogo_con_el_mismo_numero_no_lleva_la_oferta(self):
        oferta = _oferta(bonos=[(PC, 1)])
        bono = {"id": 1, "nombre": "1 Hora", "minutos": 60, "precio": 4000.0, "activo": 1}
        self.assertIsNotNone(ofertas_repo.con_las_ofertas(PC, [bono], [oferta])[0]["oferta"])
        self.assertIsNone(ofertas_repo.con_las_ofertas(PS5, [bono], [oferta])[0]["oferta"])
        # Pasar dos veces por la cuenta no aplica dos veces la oferta.
        una_vez = ofertas_repo.con_las_ofertas(PC, [bono], [oferta])
        self.assertEqual(ofertas_repo.con_las_ofertas(PC, una_vez, [oferta])[0]["minutos"], 120)
        self.assertEqual(ofertas_repo.con_las_ofertas(PC, una_vez, [])[0]["minutos"], 60)


# ---------------------------------------------------------------------------
# Armar ofertas (con la base)
# ---------------------------------------------------------------------------

class _ConCatalogos(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.pc = pcs_repo.crear_estacion("PC 3")
        self.stream = pcs_repo.crear_estacion("PCSTREAM")
        self.una_hora = pcs_repo.crear_bono("1 Hora", 60, 5000.0)
        self.promo3 = pcs_repo.crear_bono("Promo 3hs", 180, 6700.0)
        self.stream5 = pcstream_repo.crear_bono("Promo 5hs", 300, 8500.0)
        self.ps5_hora = playstation_repo.crear_bono(self.admin, "1 Hora", 60, 4000.0)

    def armar(self, momento=None, oferta_id=None, nombre="Noche de finde", tipo=dominio.OFERTA_2X1, desde=VIERNES,
              hasta=date(2026, 11, 30), franjas=((VIE, NOCHE), (SAB, NOCHE)), bonos=None, usuario=None):
        with reloj(momento or _a_las(VIERNES, 12)):
            return ofertas_repo.guardar_oferta(
                usuario or self.admin, oferta_id, nombre, tipo, desde, hasta, list(franjas),
                bonos if bonos is not None else [(PC, self.promo3)],
            )

    def vinculo(self, tabla, venta_id):
        with conexion_db() as conexion:
            return conexion.execute(f"SELECT * FROM {tabla} WHERE venta_id = ?", (venta_id,)).fetchone()

    def total_de(self, venta_id):
        with conexion_db() as conexion:
            return conexion.execute("SELECT total FROM ventas WHERE id = ?", (venta_id,)).fetchone()["total"]


class TestArmarOfertas(_ConCatalogos):
    def test_solo_el_administrador_las_arma_pausa_y_termina(self):
        with self.assertRaises(PermissionError):
            self.armar(usuario=self.toby)
        oferta = self.armar()
        with reloj(_a_las(VIERNES, 12)):
            for funcion in (ofertas_repo.pausar_oferta, ofertas_repo.reanudar_oferta, ofertas_repo.terminar_oferta):
                with self.assertRaises(PermissionError):
                    funcion(self.toby, oferta)

    def test_se_guarda_y_se_lee_igual(self):
        oferta_id = self.armar()
        with reloj(_a_las(VIERNES, 23)):
            oferta, = ofertas_repo.listar_ofertas()
            activas = ofertas_repo.activas()
        self.assertEqual(oferta["id"], oferta_id)
        self.assertEqual(oferta["franjas"], [(VIE, NOCHE), (SAB, NOCHE)])
        self.assertEqual(oferta["bonos"], [(PC, self.promo3)])
        self.assertEqual(oferta["estado"], dominio.OFERTA_ACTIVA)
        self.assertEqual(activas[0]["hasta_el_fin"], _a_las(SABADO, 6))

    def test_lo_que_no_vale_no_se_guarda(self):
        casos = [
            ({"nombre": "  "}, "nombre"),
            ({"franjas": []}, "al menos un día"),
            ({"bonos": []}, "al menos un bono"),
            ({"desde": SABADO, "hasta": VIERNES}, "anterior"),
            ({"desde": date(2026, 11, 1), "hasta": date(2026, 11, 10)}, "ya pasó"),
            ({"franjas": [(DOM, TARDE)]}, "turno del local"),
            # Del sábado al domingo no hay ningún viernes.
            ({"desde": SABADO, "hasta": DOMINGO, "franjas": [(VIE, NOCHE)]}, "ningún día"),
            # Los bonos de Socios nunca (decisión del dueño).
            ({"bonos": [("SOCIOS", 1)]}, "solo en los bonos"),
            ({"bonos": [(PC, 999)]}, "ya no está a la venta"),
        ]
        for cambios, texto in casos:
            with self.subTest(texto):
                with self.assertRaises(ValueError) as error:
                    self.armar(**cambios)
                self.assertIn(texto, str(error.exception))
        with reloj(_a_las(VIERNES, 12)):
            self.assertEqual(ofertas_repo.listar_ofertas(), [])

    def test_dos_ofertas_no_tocan_el_mismo_bono_en_el_mismo_turno(self):
        self.armar(nombre="Noche de finde")
        with self.assertRaises(ofertas_repo.ChocaConOtraOferta) as choque:
            self.armar(nombre="Finde gamer", tipo=dominio.OFERTA_MITAD, franjas=[(SAB, NOCHE)])
        self.assertEqual(choque.exception.otra, "Noche de finde")
        self.assertIn("Promo 3hs de las PCs los sábados en el turno Noche (22 a 06)", str(choque.exception))

    def test_otro_bono_otro_turno_u_otras_fechas_no_chocan(self):
        self.armar(nombre="Noche de finde", hasta=date(2026, 11, 20))
        self.armar(nombre="Otro bono", bonos=[(PC, self.una_hora)])
        self.armar(nombre="Otro turno", franjas=[(SAB, TARDE)])
        self.armar(nombre="Después", desde=date(2026, 11, 21), hasta=date(2026, 11, 30))
        # Mismo bono y turno, pero en las fechas que comparten (lun 16 y mar 17) no hay viernes.
        self.armar(nombre="Lun y mar", desde=date(2026, 11, 16), hasta=date(2026, 11, 17),
                   franjas=[(VIE, NOCHE), (LUN, NOCHE), (MAR, NOCHE)])
        # El mismo número de bono en otro catálogo es otro bono ("Otro bono" ya tiene el 1 de las PCs).
        self.assertEqual(self.una_hora, self.ps5_hora)
        self.armar(nombre="La consola", bonos=[(PS5, self.ps5_hora)])

    def test_un_turno_compartido_solo_en_dias_que_ya_pasaron_no_choca(self):
        # Armada el lunes 02/11: los lunes y viernes a la Noche, hasta el sábado 14/11.
        lunes_2 = date(2026, 11, 2)
        self.armar(momento=_a_las(lunes_2, 12), nombre="Primera quincena", desde=lunes_2, hasta=SABADO,
                   franjas=[(LUN, NOCHE), (VIE, NOCHE)])
        # El viernes 13 sus lunes (02 y 09) ya pasaron: otra los lunes, aunque arranque el 02, no choca.
        self.armar(nombre="Lunes gamer", desde=lunes_2, franjas=[(LUN, NOCHE)])
        # El viernes a la Noche sí: es hoy.
        with self.assertRaises(ofertas_repo.ChocaConOtraOferta):
            self.armar(nombre="Viernes", franjas=[(VIE, NOCHE)])

    def test_un_turno_de_hoy_que_ya_termino_tampoco_choca(self):
        self.armar(momento=_a_las(VIERNES, 10), nombre="Viernes", hasta=VIERNES, franjas=[(VIE, MANANA), (VIE, NOCHE)])
        # A las 23:00 la Mañana del viernes ya pasó y «Viernes» no tiene otros viernes.
        self.armar(momento=_a_las(VIERNES, 23), nombre="Mañanas", franjas=[(dia, MANANA) for dia in range(6)])
        # La Noche del viernes sí: está corriendo.
        with self.assertRaises(ofertas_repo.ChocaConOtraOferta):
            self.armar(momento=_a_las(VIERNES, 23), nombre="Noches", franjas=[(VIE, NOCHE)])

    def test_una_pausada_sigue_ocupando_su_lugar_y_una_terminada_no(self):
        primera = self.armar(nombre="Noche de finde")
        with reloj(_a_las(VIERNES, 12)):
            ofertas_repo.pausar_oferta(self.admin, primera)
        with self.assertRaises(ofertas_repo.ChocaConOtraOferta):
            self.armar(nombre="Encima")
        with reloj(_a_las(VIERNES, 12)):
            ofertas_repo.terminar_oferta(self.admin, primera)
        self.armar(nombre="Encima")

    def test_cambiarla_no_choca_consigo_misma_y_una_terminada_no_se_cambia(self):
        oferta = self.armar()
        self.armar(oferta_id=oferta, nombre="Noche de finde XL", hasta=date(2026, 12, 15))
        with reloj(_a_las(VIERNES, 12)):
            self.assertEqual(ofertas_repo.listar_ofertas()[0]["nombre"], "Noche de finde XL")
            ofertas_repo.terminar_oferta(self.admin, oferta)
            self.assertEqual(ofertas_repo.listar_ofertas()[0]["estado"], dominio.OFERTA_TERMINADA)
        with self.assertRaises(ValueError):
            self.armar(oferta_id=oferta)

    def test_nada_se_borra_terminada_queda_con_quien_y_cuando(self):
        oferta = self.armar()
        with reloj(_a_las(VIERNES, 12, 30)):
            ofertas_repo.terminar_oferta(self.admin, oferta)
            terminada, = ofertas_repo.listar_ofertas()
        self.assertEqual(terminada["terminada_por"], self.admin)
        self.assertEqual(terminada["terminada_fecha"], _a_las(VIERNES, 12, 30))

    def test_pausada_no_se_aplica_y_al_reanudarla_vuelve(self):
        oferta = self.armar()
        with reloj(_a_las(VIERNES, 23)):
            ofertas_repo.pausar_oferta(self.admin, oferta)
            self.assertEqual(ofertas_repo.activas(), [])
            ofertas_repo.reanudar_oferta(self.admin, oferta)
            self.assertEqual(len(ofertas_repo.activas()), 1)


# ---------------------------------------------------------------------------
# Vender con la oferta
# ---------------------------------------------------------------------------

class TestVenderConOferta(_ConCatalogos):
    def test_un_bono_de_pc_con_2x1_da_el_doble_de_tiempo_y_cobra_lo_mismo(self):
        oferta = self.armar()
        with reloj(_a_las(VIERNES, 23)):
            venta = pcs_repo.asignar_bono(self.pc, self.promo3, self.toby, _efectivo(6700.0))
        vinculo = self.vinculo("sesion_bonos", venta)
        self.assertEqual((vinculo["minutos"], vinculo["precio"], vinculo["oferta_id"]), (360, 6700.0, oferta))
        self.assertEqual(self.total_de(venta), 6700.0)
        with conexion_db() as conexion:
            sesion = conexion.execute("SELECT * FROM sesiones_pc WHERE id = ?", (vinculo["sesion_id"],)).fetchone()
        self.assertEqual(sesion["fecha_fin_prevista"], _a_las(SABADO, 5).isoformat(timespec="seconds"))

    def test_fuera_del_turno_o_en_otro_bono_se_vende_como_siempre(self):
        self.armar()
        with reloj(_a_las(VIERNES, 21)):
            venta = pcs_repo.asignar_bono(self.pc, self.promo3, self.toby, _efectivo(6700.0))
        self.assertEqual((self.vinculo("sesion_bonos", venta)["minutos"], self.vinculo("sesion_bonos", venta)["oferta_id"]),
                         (180, None))
        with reloj(_a_las(VIERNES, 23)):
            venta = pcs_repo.asignar_bono(self.pc, self.una_hora, self.toby, _efectivo(5000.0))
        self.assertIsNone(self.vinculo("sesion_bonos", venta)["oferta_id"])

    def test_la_playstation_con_50_cobra_la_mitad(self):
        oferta = self.armar(tipo=dominio.OFERTA_MITAD, franjas=[(VIE, TARDE)], bonos=[(PS5, self.ps5_hora)])
        with reloj(_a_las(VIERNES, 15)):
            venta = playstation_repo.vender_bono(self.toby, self.ps5_hora, _efectivo(2000.0))
        vinculo = self.vinculo("sesion_playstation_bonos", venta)
        self.assertEqual((vinculo["minutos"], vinculo["precio"], vinculo["oferta_id"]), (60, 2000.0, oferta))
        self.assertEqual(self.total_de(venta), 2000.0)

    def test_pcstream_con_su_oferta(self):
        oferta = self.armar(bonos=[(PCSTREAM, self.stream5)])
        with reloj(_a_las(SABADO, 23)):
            venta = pcs_repo.asignar_bono(self.stream, self.stream5, self.toby, _efectivo(8500.0))
        vinculo = self.vinculo("sesion_pcstream_bonos", venta)
        self.assertEqual((vinculo["minutos"], vinculo["oferta_id"]), (600, oferta))

    def test_vale_el_precio_que_se_mostro_al_abrir_el_cobro(self):
        self.armar()
        # Se apretó Cobrar a las 05:58 con la oferta y se terminó de cobrar a las 06:01.
        with reloj(_a_las(SABADO, 6, 1)):
            venta = pcs_repo.asignar_bono(self.pc, self.promo3, self.toby, _efectivo(6700.0),
                                          momento_del_precio=_a_las(SABADO, 5, 58))
        self.assertEqual(self.vinculo("sesion_bonos", venta)["minutos"], 360)
        # Una ventana de cobro olvidada media hora no.
        with reloj(_a_las(SABADO, 6, 40)):
            with self.assertRaises(ValueError):
                pcs_repo.asignar_bono(self.pc, self.promo3, self.toby, _efectivo(6700.0),
                                      momento_del_precio=_a_las(SABADO, 5, 58))

    def como_se_ve(self, equipo, bono, momento):
        """El bono como lo muestra el panel a esa hora (lo que se le cobra al cliente)."""
        with reloj(momento):
            return ofertas_repo.con_las_ofertas(equipo, [bono], ofertas_repo.activas(momento))[0]

    def cuantas_ventas(self):
        with conexion_db() as conexion:
            return conexion.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]

    def test_lo_que_se_mostro_y_lo_que_se_graba_dan_lo_mismo(self):
        oferta = self.armar(tipo=dominio.OFERTA_MITAD, bonos=[(PC, self.una_hora)])
        visto = self.como_se_ve(PC, pcs_repo.obtener_bono(self.una_hora), _a_las(VIERNES, 22))
        self.assertEqual((visto["precio"], visto["oferta"]["id"]), (2500.0, oferta))
        with reloj(_a_las(VIERNES, 22, 0, 30)):
            venta = pcs_repo.asignar_bono(self.pc, self.una_hora, self.toby, _efectivo(2500.0),
                                          momento_del_precio=_a_las(VIERNES, 22), bono_mostrado=visto)
        self.assertEqual(self.total_de(venta), 2500.0)

    def test_si_la_oferta_cambia_con_el_cobro_abierto_no_se_graba_nada(self):
        # Revisión del 13/11: sin esto la venta quedaba con un total distinto de la plata cobrada.
        oferta = self.armar(tipo=dominio.OFERTA_MITAD, bonos=[(PC, self.una_hora), (PS5, self.ps5_hora)])
        a_la_pc = self.como_se_ve(PC, pcs_repo.obtener_bono(self.una_hora), _a_las(VIERNES, 22))
        a_la_consola = self.como_se_ve(PS5, playstation_repo.obtener_bono(self.ps5_hora), _a_las(VIERNES, 22))
        # El Admin la pausa desde su PC mientras la empleada cobra.
        with reloj(_a_las(VIERNES, 22, 0, 20)):
            ofertas_repo.pausar_oferta(self.admin, oferta)
        with reloj(_a_las(VIERNES, 22, 0, 30)):
            with self.assertRaises(ValueError) as error:
                pcs_repo.asignar_bono(self.pc, self.una_hora, self.toby, _efectivo(2500.0),
                                      momento_del_precio=_a_las(VIERNES, 22), bono_mostrado=a_la_pc)
            self.assertIn("cambió mientras se cobraba", str(error.exception))
            with self.assertRaises(ValueError):
                playstation_repo.vender_bono(self.toby, self.ps5_hora, _efectivo(2000.0),
                                             momento_del_precio=_a_las(VIERNES, 22), bono_mostrado=a_la_consola)
        self.assertEqual(self.cuantas_ventas(), 0)
        with conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM sesiones_pc").fetchone()[0], 0)

    def test_una_oferta_nueva_con_el_cobro_abierto_tampoco(self):
        sin_oferta = self.como_se_ve(PC, pcs_repo.obtener_bono(self.promo3), _a_las(VIERNES, 22, 10))
        self.armar(momento=_a_las(VIERNES, 22, 10, 20), tipo=dominio.OFERTA_MITAD)
        with reloj(_a_las(VIERNES, 22, 10, 40)):
            with self.assertRaises(ValueError):
                pcs_repo.asignar_bono(self.pc, self.promo3, self.toby, _efectivo(6700.0),
                                      momento_del_precio=_a_las(VIERNES, 22, 10), bono_mostrado=sin_oferta)
        self.assertEqual(self.cuantas_ventas(), 0)

    def test_anotar_a_la_cuenta_con_la_oferta_cambiada_no_anota(self):
        oferta = self.armar(tipo=dominio.OFERTA_MITAD)
        with reloj(_a_las(VIERNES, 22, 30)):
            pcs_repo.asignar_bono(self.pc, self.una_hora, self.toby, _efectivo(5000.0))
        visto = self.como_se_ve(PC, pcs_repo.obtener_bono(self.promo3), _a_las(VIERNES, 22, 31))
        self.armar(momento=_a_las(VIERNES, 22, 31, 10), oferta_id=oferta, tipo=dominio.OFERTA_2X1)
        with reloj(_a_las(VIERNES, 22, 31, 20)):
            with self.assertRaises(ValueError):
                cuentas_pc_repo.anotar_bono(self.pc, self.promo3, self.toby, momento_del_precio=_a_las(VIERNES, 22, 31),
                                            bono_mostrado=visto)
            self.assertEqual(cuentas_pc_repo.cuentas_de_la_estacion(self.pc), [])

    def test_la_cuenta_de_la_pc_conserva_la_oferta_aunque_se_cobre_despues(self):
        oferta = self.armar(tipo=dominio.OFERTA_MITAD)
        with reloj(_a_las(VIERNES, 22, 30)):
            pcs_repo.asignar_bono(self.pc, self.una_hora, self.toby, _efectivo(5000.0))
            cuentas_pc_repo.anotar_bono(self.pc, self.promo3, self.toby)
            cuenta, = cuentas_pc_repo.cuentas_de_la_estacion(self.pc)
        self.assertEqual(cuenta["total"], 3350.0)
        self.assertEqual(cuenta["renglones"][0]["descripcion"], "Bono Promo 3hs (50%)")
        # Se cobra el sábado a la tarde, con la oferta ya terminada.
        with reloj(_a_las(SABADO, 16)):
            venta, = cuentas_pc_repo.cobrar([cuenta["id"]], self.toby, _efectivo(3350.0))
        vinculo = self.vinculo("sesion_bonos", venta)
        self.assertEqual((vinculo["minutos"], vinculo["precio"], vinculo["oferta_id"]), (180, 3350.0, oferta))

    def test_quitar_un_bono_con_2x1_le_saca_el_tiempo_doble(self):
        self.armar()
        with reloj(_a_las(VIERNES, 23)):
            venta = pcs_repo.asignar_bono(self.pc, self.promo3, self.toby, _efectivo(6700.0))
        with reloj(_a_las(VIERNES, 23, 30)):
            anular_bono_repo.anular_bono(venta, self.admin, "se cargó de más")
        with conexion_db() as conexion:
            sesion = conexion.execute("SELECT * FROM sesiones_pc WHERE estacion_id = ?", (self.pc,)).fetchone()
        # Tenía hasta las 05:00 (6 h): sin el bono no le queda nada, se corta ahora.
        self.assertLessEqual(datetime.fromisoformat(sesion["fecha_fin_prevista"]), _a_las(VIERNES, 23, 30))

    def test_las_reservas_van_siempre_sin_oferta(self):
        # Una oferta que corre toda la semana, todo el día: la reserva igual va sin ella.
        hoy = ofertas_repo.turnos.dia_en_que_empezo_el_turno(datetime.now())
        self.armar(momento=datetime.now(), desde=hoy, hasta=hoy + timedelta(days=7),
                   franjas=ofertas_repo.franjas_de_la_semana())
        manana = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=10)
        reserva = reservas_repo.crear_reserva(self.toby, "Juan", "11 5555-4444", PC, self.pc, self.promo3,
                                              manana, 6700.0, _efectivo(6700.0))
        reservas_habilitar_repo.habilitar(reserva, self.toby, self.pc, [])
        with conexion_db() as conexion:
            vinculo = conexion.execute("SELECT * FROM sesion_bonos").fetchone()
        self.assertEqual((vinculo["minutos"], vinculo["oferta_id"]), (180, None))


class TestDesdeOtraPC(BaseConBaseTemporal):
    def test_armar_ofertas_se_puede_desde_otra_pc_y_queda_a_nombre_de_quien_entro(self):
        for funcion in ("guardar_oferta", "pausar_oferta", "reanudar_oferta", "terminar_oferta"):
            self.assertTrue(lista_blanca.permitida("ofertas_repo", funcion), funcion)
            self.assertEqual(lista_blanca.ACTOR[("ofertas_repo", funcion)], "usuario_id")
        self.assertTrue(lista_blanca.permitida("ofertas_repo", "listar_ofertas"))
        self.assertTrue(lista_blanca.permitida("ofertas_repo", "activas"))
        # Vender con la oferta es del mostrador, como vender sin ella.
        self.assertFalse(lista_blanca.permitida("ofertas_repo", "como_se_vende"))


class TestMigracionDeLasOfertas(BaseConBaseTemporal):
    """database_migraciones._migrar_columna_oferta_en_bonos_vendidos: una base de antes
    de las ofertas (sin `oferta_id` en lo vendido) la recibe en NULL sin tocar lo que ya
    había, y correrla de nuevo no hace nada (regla 6 de CLAUDE.md)."""

    TABLAS = ("sesion_bonos", "sesion_pcstream_bonos", "sesion_playstation_bonos", "cuenta_pc_items")

    def test_una_base_vieja_recibe_la_columna_en_null_y_dos_veces_no_rompe(self):
        conexion = sqlite3.connect(":memory:")
        conexion.row_factory = sqlite3.Row
        self.addCleanup(conexion.close)
        conexion.execute("CREATE TABLE ofertas (id INTEGER PRIMARY KEY)")
        for tabla in self.TABLAS:
            conexion.execute(f"CREATE TABLE {tabla} (id INTEGER PRIMARY KEY, minutos INTEGER)")
            conexion.execute(f"INSERT INTO {tabla} (minutos) VALUES (180)")
        for _ in range(2):
            database_migraciones._migrar_columna_oferta_en_bonos_vendidos(conexion)
        for tabla in self.TABLAS:
            with self.subTest(tabla):
                columnas = [fila["name"] for fila in conexion.execute(f"PRAGMA table_info({tabla})")]
                self.assertEqual(columnas.count("oferta_id"), 1)
                fila = conexion.execute(f"SELECT minutos, oferta_id FROM {tabla}").fetchone()
                self.assertEqual((fila["minutos"], fila["oferta_id"]), (180, None))

    def test_abrir_el_programa_otra_vez_deja_la_columna_apuntando_a_las_ofertas(self):
        database.inicializar_base_de_datos()
        with conexion_db() as conexion:
            for tabla in self.TABLAS:
                with self.subTest(tabla):
                    claves = [(fila["from"], fila["table"]) for fila in conexion.execute(
                        f"PRAGMA foreign_key_list({tabla})")]
                    self.assertIn(("oferta_id", "ofertas"), claves)
