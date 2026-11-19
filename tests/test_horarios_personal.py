"""
tests/test_horarios_personal.py
================================
HORARIOS DEL PERSONAL (pedido del dueño, 2026-11-19, maqueta B): cuántos días
llegó temprano o tarde cada empleada y si le debe tiempo al local o el local a
ella, según cuándo abre y cierra (o recibe y entrega) su caja. Las cajas se
abren y se cierran con las funciones de verdad (relevo_repo, turnos_repo), así
la prueba ve lo mismo que quedaría grabado en el local. Ver
repositories/horarios_repo.py y ui/horarios_personal_window.py; la pantalla se
prueba sin abrir ninguna ventana (plataforma "offscreen" de Qt).

    python -m unittest discover tests -p "test_horarios_personal.py"
"""

import os
from datetime import date, datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, QPoint, Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from admin_remoto import lista_blanca  # noqa: E402
from repositories import horarios_repo, relevo_repo, turnos_repo, usuarios_repo  # noqa: E402
from ui import horarios_personal_window as ventana  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

LUNES = date(2026, 1, 5)
DOMINGO = date(2026, 1, 4)


def _a_las(hora, minuto=0, dia=LUNES):
    return datetime(dia.year, dia.month, dia.day, hora, minuto)


class _BaseDeHorarios(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Dueño", "1234", dominio.ROL_ADMIN)
        self.antonella_id = usuarios_repo.crear_usuario("Antonella", "1234", dominio.ROL_EMPLEADA)
        self.lucia_id = usuarios_repo.crear_usuario("Lucía", "1234", dominio.ROL_EMPLEADA)
        self.gaby_id = usuarios_repo.crear_usuario("Gaby", "1234", dominio.ROL_EMPLEADA)

    def abrir(self, usuario_id, momento):
        situacion = relevo_repo.situacion_al_entrar(usuario_id, momento)
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_ABRIR)
        contado = situacion["cambio_esperado"] if situacion["cuenta_cambio"] else None
        return relevo_repo.abrir_caja(usuario_id, contado, momento)["caja_numero"]

    def cerrar(self, usuario_id, momento):
        turnos_repo.cerrar_turno(usuario_id, ahora_dt=momento)

    def recibir(self, usuario_id, momento):
        situacion = relevo_repo.situacion_al_entrar(usuario_id, momento)
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_RECIBIR)
        relevo_repo.recibir_caja(usuario_id, situacion["caja_id"], situacion["esperado"], momento)

    def horarios(self, desde=LUNES, hasta=LUNES, ahora=None):
        return horarios_repo.horarios_del_personal(self.admin_id, desde, hasta, ahora or _a_las(23, 59, date(2026, 1, 12)))

    def de(self, nombre, datos=None):
        datos = datos or self.horarios()
        return next(empleada for empleada in datos["empleadas"] if empleada["nombre"] == nombre)


class TestElEjemploDelDueno(_BaseDeHorarios):
    def test_abre_5_antes_y_cierra_5_antes_cumple_justo(self):
        # "Antonella llega siempre 5 minutos temprano, abre la caja del turno tarde a
        # las 13:55... si se va 5 min antes, estaría cumpliendo solo sus 8 horas".
        self.abrir(self.antonella_id, _a_las(13, 55))
        self.cerrar(self.antonella_id, _a_las(21, 55))

        antonella = self.de("Antonella")
        dia = antonella["detalle"][0]
        self.assertEqual((dia["inicio"], dia["fin"]), (_a_las(14), _a_las(22)))
        self.assertEqual((dia["al_llegar"], dia["al_irse"], dia["del_dia"]), (5, -5, 0))
        self.assertEqual(antonella["dias"], 1)
        self.assertEqual(antonella["llego_temprano"], 1)
        self.assertEqual(antonella["llego_tarde"], 0)
        self.assertEqual(antonella["se_fue_antes"], 1)
        self.assertEqual(antonella["saldo"], 0)
        self.assertEqual(antonella["turno_habitual"], "Tarde")

    def test_hasta_2_minutos_es_a_horario(self):
        self.abrir(self.antonella_id, _a_las(14, 2))
        self.cerrar(self.antonella_id, _a_las(21, 58))

        antonella = self.de("Antonella")
        self.assertEqual((antonella["detalle"][0]["al_llegar"], antonella["detalle"][0]["al_irse"]), (0, 0))
        self.assertEqual((antonella["llego_tarde"], antonella["se_fue_antes"], antonella["saldo"]), (0, 0, 0))

    def test_los_segundos_no_cuentan(self):
        # La pantalla muestra 14:17; con los segundos se contaban 18 minutos tarde.
        self.abrir(self.antonella_id, datetime(2026, 1, 5, 14, 17, 50))
        self.cerrar(self.antonella_id, _a_las(22))

        self.assertEqual(self.de("Antonella")["detalle"][0]["al_llegar"], -17)


class TestCubrirYRelevos(_BaseDeHorarios):
    def setUp(self):
        super().setUp()
        # Lucía hace la Mañana; Gaby, la de la Tarde, llega 20 minutos tarde y Lucía
        # la cubre: cierra a horario, abre otra caja sin contar y se la entrega.
        self.abrir(self.lucia_id, _a_las(5, 50))
        self.cerrar(self.lucia_id, _a_las(14))
        self.abrir(self.lucia_id, _a_las(14))
        self.recibir(self.gaby_id, _a_las(14, 20))
        self.cerrar(self.gaby_id, _a_las(22))

    def test_la_que_cubre_suma_lo_que_se_quedo_en_un_solo_dia(self):
        lucia = self.de("Lucía")
        self.assertEqual(lucia["dias"], 1)
        dia = lucia["detalle"][0]
        self.assertEqual(dia["turno"], dominio.TURNO_MANANA)
        self.assertEqual(dia["salida"], _a_las(14, 20))
        self.assertEqual((dia["al_llegar"], dia["al_irse"], dia["del_dia"]), (10, 20, 30))
        self.assertEqual(dia["que_paso"], "Cubrió hasta que llegó Gaby")
        self.assertEqual(lucia["saldo"], 30)

    def test_la_que_llega_tarde_recibe_la_caja_y_debe_esos_minutos(self):
        gaby = self.de("Gaby")
        dia = gaby["detalle"][0]
        self.assertEqual(dia["turno"], dominio.TURNO_TARDE)
        self.assertEqual(dia["llegada"], _a_las(14, 20))
        self.assertEqual((dia["al_llegar"], dia["al_irse"]), (-20, 0))
        self.assertEqual(dia["que_paso"], "Recibió la caja de Lucía")
        self.assertEqual((gaby["llego_tarde"], gaby["saldo"]), (1, -20))

    def test_el_admin_no_aparece(self):
        nombres = [empleada["nombre"] for empleada in self.horarios()["empleadas"]]
        self.assertEqual(nombres, ["Gaby", "Lucía"])


class TestLlegarAntesYRecibir(_BaseDeHorarios):
    def test_la_que_llega_antes_del_aviso_recibe_la_caja_y_se_compara_con_su_turno(self):
        # Antes de las 13:55 la caja de la Mañana no titila: quien llega la recibe.
        self.abrir(self.lucia_id, _a_las(6))
        self.recibir(self.antonella_id, _a_las(13, 40))
        self.cerrar(self.antonella_id, _a_las(14, 5))
        self.abrir(self.antonella_id, _a_las(14, 5))
        self.cerrar(self.antonella_id, _a_las(22))

        antonella = self.de("Antonella")
        self.assertEqual(antonella["dias"], 1)
        dia = antonella["detalle"][0]
        self.assertEqual(dia["turno"], dominio.TURNO_TARDE)
        self.assertEqual((dia["al_llegar"], dia["al_irse"]), (20, 0))
        lucia = self.de("Lucía")["detalle"][0]
        self.assertEqual((lucia["salida"], lucia["al_irse"]), (_a_las(13, 40), -20))
        self.assertEqual(lucia["que_paso"], "Le entregó la caja a Antonella")


class TestSalidaSinDato(_BaseDeHorarios):
    def test_si_la_cerro_otra_no_se_sabe_cuando_se_fue(self):
        self.abrir(self.lucia_id, _a_las(6, 5))
        situacion = relevo_repo.situacion_al_entrar(self.gaby_id, _a_las(13, 56))
        self.assertEqual(situacion["situacion"], relevo_repo.SITUACION_CERRAR_LA_DE_OTRA)
        relevo_repo.cerrar_para_entrar(self.gaby_id, relevo_repo.SITUACION_CERRAR_LA_DE_OTRA, _a_las(13, 56))
        self.abrir(self.gaby_id, _a_las(13, 57))
        self.cerrar(self.gaby_id, _a_las(22))

        lucia = self.de("Lucía")
        dia = lucia["detalle"][0]
        self.assertIsNone(dia["salida"])
        self.assertIsNone(dia["al_irse"])
        self.assertEqual(dia["que_paso"], "La caja la cerró Gaby: no se sabe a qué hora se fue")
        # Lo que llegó tarde sí cuenta; la salida, no.
        self.assertEqual((lucia["sin_dato"], lucia["saldo"], lucia["se_fue_antes"]), (1, -5, 0))
        self.assertEqual(self.de("Gaby")["detalle"][0]["al_llegar"], 3)

    def test_si_la_cerro_el_programa_no_se_sabe_cuando_se_fue(self):
        self.abrir(self.lucia_id, _a_las(6))
        relevo_repo.cierre_forzoso_si_corresponde(_a_las(14, 31))

        dia = self.de("Lucía")["detalle"][0]
        self.assertIsNone(dia["al_irse"])
        self.assertIn("el programa", dia["que_paso"])

    def test_si_todavia_esta_trabajando_no_es_sin_dato(self):
        self.abrir(self.lucia_id, _a_las(5, 50))

        lucia = self.de("Lucía", self.horarios(ahora=_a_las(10)))
        self.assertTrue(lucia["detalle"][0]["en_curso"])
        self.assertEqual((lucia["sin_dato"], lucia["saldo"]), (0, 10))
        self.assertEqual(lucia["detalle"][0]["que_paso"], "Está trabajando ahora")


class TestTurnosLargos(_BaseDeHorarios):
    def test_un_doble_turno_se_compara_de_punta_a_punta_sin_sumar_8_horas(self):
        self.abrir(self.lucia_id, _a_las(5, 55))
        self.cerrar(self.lucia_id, _a_las(14))
        self.abrir(self.lucia_id, _a_las(14))
        self.cerrar(self.lucia_id, _a_las(22))

        lucia = self.de("Lucía")
        dia = lucia["detalle"][0]
        self.assertEqual(lucia["dias"], 1)
        self.assertEqual((dia["inicio"], dia["fin"]), (_a_las(6), _a_las(22)))
        self.assertEqual(dia["turno_label"], "Mañana y Tarde")
        self.assertEqual(lucia["saldo"], 5)
        self.assertIn("Turno doble", dia["que_paso"])

    def test_el_domingo_el_turno_es_de_12_horas(self):
        self.abrir(self.lucia_id, _a_las(6, dia=DOMINGO))
        self.cerrar(self.lucia_id, _a_las(17, 50, dia=DOMINGO))

        lucia = self.de("Lucía", self.horarios(DOMINGO, DOMINGO))
        dia = lucia["detalle"][0]
        self.assertEqual(dia["fin"], _a_las(18, dia=DOMINGO))
        self.assertEqual(dia["al_irse"], -10)
        self.assertEqual(dia["turno_label"], "Domingo T1")

    def test_la_noche_va_en_el_dia_en_que_empezo(self):
        self.abrir(self.gaby_id, _a_las(21, 50))
        self.cerrar(self.gaby_id, datetime(2026, 1, 6, 6, 15))

        gaby = self.de("Gaby")
        self.assertEqual(gaby["detalle"][0]["dia"], LUNES)
        self.assertEqual(gaby["saldo"], 25)
        siguiente = self.horarios(date(2026, 1, 6), date(2026, 1, 6))
        self.assertEqual(siguiente["empleadas"], [])


class TestQuienLoVe(_BaseDeHorarios):
    def test_solo_el_administrador(self):
        with self.assertRaises(PermissionError):
            horarios_repo.horarios_del_personal(self.lucia_id, LUNES, LUNES)

    def test_se_mira_tambien_desde_otra_pc(self):
        self.assertTrue(lista_blanca.permitida("horarios_repo", "horarios_del_personal"))
        self.assertEqual(lista_blanca.ACTOR[("horarios_repo", "horarios_del_personal")], "usuario_id")


class TestTextos(BaseConBaseTemporal):
    def test_el_saldo_se_lee_desde_el_dueno(self):
        self.assertEqual(ventana.frase_del_saldo(80), ("LE DEBÉS 1 h 20 min", ventana.TONO_A_FAVOR))
        self.assertEqual(ventana.frase_del_saldo(-35), ("TE DEBE 35 min", ventana.TONO_EN_CONTRA))
        self.assertEqual(ventana.frase_del_saldo(-120), ("TE DEBE 2 h", ventana.TONO_EN_CONTRA))
        self.assertEqual(ventana.frase_del_saldo(0), ("ESTÁN A MANO", ventana.TONO_A_MANO))

    def test_el_periodo_de_la_cabecera(self):
        hoy = date(2026, 11, 19)
        self.assertEqual(ventana.nombre_del_periodo(date(2026, 11, 1), hoy, hoy), "NOVIEMBRE 2026")
        self.assertEqual(ventana.nombre_del_periodo(date(2026, 10, 1), date(2026, 10, 31), hoy), "OCTUBRE 2026")
        self.assertEqual(ventana.nombre_del_periodo(date(2026, 10, 18), date(2026, 11, 3), hoy), "18/10 AL 03/11")


class TestPantalla(_BaseDeHorarios):
    def setUp(self):
        super().setUp()
        self.abrir(self.antonella_id, _a_las(13, 55))
        self.cerrar(self.antonella_id, _a_las(21, 55))
        self.abrir(self.gaby_id, _a_las(21, 56))
        self.cerrar(self.gaby_id, datetime(2026, 1, 6, 6, 30))
        self.ventana = ventana.HorariosPersonalWindow(usuarios_repo.obtener_usuario(self.admin_id))
        self.addCleanup(self.ventana.deleteLater)
        self.ventana.fecha_desde.setDate(QDate(2026, 1, 5))
        self.ventana.fecha_hasta.setDate(QDate(2026, 1, 5))
        self.ventana._cargar()

    def test_una_tarjeta_por_empleada_y_el_detalle_de_la_primera(self):
        self.assertEqual(
            [tarjeta.accessibleName() for tarjeta in self.ventana.tarjetas.values()], ["Antonella", "Gaby"])
        self.assertEqual(self.ventana.elegida, self.antonella_id)
        self.assertEqual(self.ventana.tarjetas[self.antonella_id].property("elegida"), "true")
        self.assertEqual(self.ventana.tarjetas[self.gaby_id].saldo.text(), "LE DEBÉS 34 min")
        self.assertEqual(self.ventana.tabla.rowCount(), 1)
        self.assertEqual(self.ventana.tabla.item(0, 3).text(), "13:55")
        self.assertEqual(self.ventana.tabla.item(0, 4).text(), "5 min antes")

    def test_al_tocar_una_tarjeta_muestra_su_detalle(self):
        tarjeta = self.ventana.tarjetas[self.gaby_id]
        QTest.mouseClick(tarjeta, Qt.LeftButton, Qt.NoModifier, QPoint(10, 10))

        self.assertEqual(self.ventana.elegida, self.gaby_id)
        self.assertEqual(self.ventana.tarjetas[self.antonella_id].property("elegida"), "false")
        self.assertEqual(self.ventana.titulo_detalle.text(), "GABY — DÍA POR DÍA")
        self.assertEqual(self.ventana.tabla.item(0, 6).text(), "se quedó 30 min")

    def test_sin_nadie_en_las_fechas_lo_dice(self):
        self.ventana.fecha_desde.setDate(QDate(2026, 2, 1))
        self.ventana.fecha_hasta.setDate(QDate(2026, 2, 2))
        self.ventana._cargar()

        self.assertEqual(self.ventana.tarjetas, {})
        self.assertFalse(self.ventana.sin_nadie.isHidden())
        self.assertEqual(self.ventana.tabla.rowCount(), 0)
