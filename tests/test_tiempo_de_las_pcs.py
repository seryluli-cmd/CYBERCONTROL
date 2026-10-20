"""
tests/test_tiempo_de_las_pcs.py
=================================
El tiempo de las PCs cuando el mostrador no está (pedido del dueño, 2026-10-20;
la explicación para él está en docs/TIEMPO_DE_LAS_PCS.md):

- Cerrar sesión en el mostrador no toca a las PCs: el servidor sigue contestando.
- Una sesión que ya llegó a cero y nadie cerró (nadie logueado) no se estira: el
  que entra arranca una sesión nueva, y la vieja termina a la hora en que llegó a
  cero, no a la hora en que alguien la cerró.
- Al volver de un corte, gana el tiempo MENOR entre el de la PC y el del
  mostrador, contando lo que se cargó durante el corte (reconexion_repo), y el
  mostrador lo guarda.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import actividad_repo, miembros_repo, pcs_repo, reconexion_repo  # noqa: E402
from control_pcs.ui import pcs_actividad  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO_1500 = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}]


def _iso(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def _sesiones():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM sesiones_pc ORDER BY id").fetchall()


def _ajustes():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM ajustes_reconexion_pc ORDER BY id").fetchall()


class _ConPc(BaseConBaseTemporal):
    """Una PC, un Admin y un bono de 1 hora."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.bono_id = pcs_repo.crear_bono("1 hora", 60, 1500)
        self.estacion = pcs_repo.crear_estacion("PC05X")

    def vender_bono(self, estacion=None):
        pcs_repo.asignar_bono(estacion or self.estacion, self.bono_id, self.admin_id, EFECTIVO_1500)

    def sesion_que_termina(self, fin: datetime, inicio: datetime = None, sesion_id: int = None):
        """Corre a mano la sesión (y lo que se cargó) como si hubiera empezado en `inicio`."""
        with conexion_db() as conexion:
            sesion = conexion.execute(
                "SELECT * FROM sesiones_pc WHERE id = ?" if sesion_id else
                "SELECT * FROM sesiones_pc ORDER BY id DESC LIMIT 1",
                (sesion_id,) if sesion_id else (),
            ).fetchone()
            inicio = inicio or fin - timedelta(hours=1)
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?, fecha_fin_prevista = ? WHERE id = ?",
                             (_iso(inicio), _iso(fin), sesion["id"]))
            conexion.execute(
                "UPDATE ventas SET fecha = ? WHERE id IN (SELECT venta_id FROM sesion_bonos WHERE sesion_id = ?)",
                (inicio.isoformat(timespec="microseconds"), sesion["id"]),
            )
            conexion.execute("UPDATE movimientos_saldo_miembro SET fecha = ? WHERE sesion_id = ?",
                             (inicio.isoformat(timespec="microseconds"), sesion["id"]))
        return sesion["id"]

    def socio(self, usuario="lucas", minutos=120):
        miembro_id = miembros_repo.crear_miembro(usuario, "clave123", usuario.capitalize())
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, miembro_id))
        return miembro_id


class TestCerrarSesionNoTocaLasPcs(test_control_pcs._ConServidorRed):
    def test_despues_de_cerrar_sesion_la_pc_sigue_con_su_tiempo(self):
        from ui.main_window import MainWindow

        admin = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        estacion = pcs_repo.crear_estacion("PC05X")
        pcs_repo.asignar_bono(estacion, pcs_repo.crear_bono("1 hora", 60, 1500), admin, EFECTIVO_1500)
        ventana = MainWindow(usuarios_repo.obtener_usuario(admin), al_cerrar_sesion=lambda: None)

        ventana._cerrar_sesion()

        status, datos = self._get("/estado?estacion=PC05X")
        self.assertEqual(status, 200)
        self.assertFalse(datos["bloqueada"])
        self.assertGreater(datos["segundos_restantes"], 59 * 60)


class TestSesionQueYaTermino(_ConPc):
    """Una sesión que llegó a cero y nadie cerró (no había nadie logueado)."""

    def test_un_socio_que_entra_arranca_una_sesion_nueva_con_su_nombre(self):
        self.vender_bono()
        vieja = self.sesion_que_termina(datetime.now() - timedelta(minutes=20))
        self.socio("lucas")

        miembros_repo.abrir_estacion_por_miembro(self.estacion, "lucas", "clave123")

        primera, segunda = _sesiones()
        self.assertEqual(primera["id"], vieja)
        self.assertEqual(primera["estado"], dominio.SESION_FINALIZADA)
        self.assertEqual(segunda["estado"], dominio.SESION_ACTIVA)
        self.assertEqual(pcs_repo.estado_de_estacion("PC05X")["sesion"]["miembro_nombre"], "Lucas")

    def test_la_vieja_termina_a_la_hora_en_que_llego_a_cero(self):
        self.vender_bono()
        fin = (datetime.now() - timedelta(minutes=20)).replace(microsecond=0)
        self.sesion_que_termina(fin)

        self.vender_bono()   # otro cliente, 20 minutos después

        primera, segunda = _sesiones()
        self.assertEqual(primera["fecha_fin_real"], _iso(fin))
        self.assertNotEqual(segunda["id"], primera["id"])
        self.assertGreater(pcs_repo.estado_de_estacion("PC05X")["segundos_restantes"], 59 * 60)

    def test_cerrarla_tarde_desde_el_mostrador_tambien_anota_la_hora_en_que_llego_a_cero(self):
        self.vender_bono()
        fin = (datetime.now() - timedelta(hours=2)).replace(microsecond=0)
        sesion_id = self.sesion_que_termina(fin)

        pcs_repo.finalizar_sesion(sesion_id)   # el refresco de la pantalla, al volver a entrar

        self.assertEqual(_sesiones()[0]["fecha_fin_real"], _iso(fin))

    def test_cortarla_antes_de_tiempo_anota_la_hora_del_corte(self):
        self.vender_bono()
        sesion_id = _sesiones()[0]["id"]
        antes = datetime.now().replace(microsecond=0)

        pcs_repo.finalizar_sesion(sesion_id)

        self.assertGreaterEqual(datetime.fromisoformat(_sesiones()[0]["fecha_fin_real"]), antes)

    def test_una_que_sigue_corriendo_se_estira_como_siempre(self):
        self.vender_bono()
        self.vender_bono()

        sesion, = _sesiones()
        self.assertGreater(pcs_repo.estado_de_estacion("PC05X")["segundos_restantes"], 119 * 60)
        self.assertEqual(sesion["estado"], dominio.SESION_ACTIVA)


class TestLeerTiempoDeLaPc(BaseConBaseTemporal):
    def test_lee_los_tres_numeros(self):
        self.assertEqual(reconexion_repo.leer_tiempo_de_la_pc({"sesion": "7", "resto": "3600", "desde": "120"}),
                         {"sesion_id": 7, "segundos": 3600, "desde": 120})

    def test_sin_corte_o_con_algo_raro_no_hay_nada(self):
        for parametros in ({}, {"sesion": "7", "resto": "3600"}, {"sesion": "x", "resto": "3600", "desde": "1"},
                           {"sesion": "7", "resto": "-5", "desde": "1"}, {"sesion": "7", "resto": "", "desde": "1"}):
            with self.subTest(parametros=parametros):
                self.assertIsNone(reconexion_repo.leer_tiempo_de_la_pc(parametros))


class TestGanaElMenor(_ConPc):
    """La PC vuelve de un corte de 2 horas (el mostrador estuvo apagado)."""

    def setUp(self):
        super().setUp()
        self.ahora = datetime.now().replace(microsecond=0)
        self.vender_bono()
        # 3 horas cargadas hace 2 h 10 min: según el mostrador le quedan 50 minutos.
        self.sesion_id = self.sesion_que_termina(self.ahora + timedelta(minutes=50),
                                                 inicio=self.ahora - timedelta(minutes=130))

    def volver(self, minutos_pc, sesion_id=None, desde=2 * 3600):
        return reconexion_repo.tomar_el_menor(
            self.estacion, {"sesion_id": sesion_id or self.sesion_id, "segundos": int(minutos_pc * 60),
                            "desde": desde},
            ahora=self.ahora,
        )

    def fin(self):
        return datetime.fromisoformat(_sesiones()[-1]["fecha_fin_prevista"])

    def test_si_la_pc_tiene_menos_se_toma_el_de_la_pc_y_queda_anotado(self):
        ajuste = self.volver(40)

        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=40))
        self.assertEqual((ajuste["segundos_mostrador"], ajuste["segundos_pc"]), (50 * 60, 40 * 60))
        anotado, = _ajustes()
        self.assertEqual((anotado["sesion_id"], anotado["fin_antes"], anotado["fin_despues"]),
                         (self.sesion_id, _iso(self.ahora + timedelta(minutes=50)),
                          _iso(self.ahora + timedelta(minutes=40))))

    def test_nunca_sube_el_tiempo(self):
        self.assertIsNone(self.volver(70))
        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=50))
        self.assertEqual(_ajustes(), [])

    def test_unos_segundos_de_diferencia_no_se_tocan(self):
        self.assertIsNone(self.volver(50 - 0.5))
        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=50))

    def test_lo_que_se_cargo_durante_el_corte_no_se_pierde(self):
        # Durante el corte (hace 20 min) le vendieron otra hora: el mostrador dice 110 min.
        self.vender_bono()
        with conexion_db() as conexion:
            conexion.execute("UPDATE ventas SET fecha = ? WHERE id = (SELECT MAX(venta_id) FROM sesion_bonos)",
                             ((self.ahora - timedelta(minutes=20)).isoformat(timespec="microseconds"),))
        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=110))

        # La PC no lo sabe y cuenta 50: con la hora que se cargó, da 110. No se toca nada.
        self.assertIsNone(self.volver(50))
        # Si la PC contó 40, se le baja a 100: los 10 minutos de diferencia, no la hora que pagó.
        self.assertEqual(self.volver(40)["minutos_cargados"], 60)
        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=100))

    def test_lo_cargado_antes_del_corte_no_se_suma_otra_vez(self):
        # El bono de la sesión se vendió hace 130 min; el corte empezó hace 30.
        ajuste = self.volver(40, desde=30 * 60)
        self.assertEqual(ajuste["minutos_cargados"], 0)

    def test_si_la_pc_contaba_otra_sesion_no_se_compara(self):
        self.assertIsNone(self.volver(10, sesion_id=self.sesion_id + 100))
        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=50))

    def test_si_la_sesion_se_paso_a_otra_pc_no_se_compara(self):
        otra = pcs_repo.crear_estacion("PC06X")
        pcs_repo.trasladar_sesion(self.estacion, otra, self.admin_id)

        self.assertIsNone(self.volver(10))
        self.assertEqual(self.fin(), self.ahora + timedelta(minutes=50))

    def test_una_pc_que_se_reinicio_porque_se_le_termino_el_tiempo_la_termina(self):
        self.volver(0)
        self.assertEqual(self.fin(), self.ahora)

    def test_se_ve_en_actividad_reciente(self):
        self.volver(40)

        evento = next(e for e in actividad_repo.actividad_reciente() if e["tipo"] == "AJUSTE_TIEMPO")
        texto = pcs_actividad._texto_evento(evento)
        self.assertIn("PC05X", texto)
        self.assertIn("se tomó el tiempo de la PC", texto)
        self.assertIn("40m", texto)
        self.assertIn("50m", texto)


class TestSocioConElTiempoAjustado(_ConPc):
    def test_al_cortar_se_le_devuelve_lo_que_quedaba_despues_del_ajuste(self):
        miembro_id = self.socio("lucas", minutos=180)
        miembros_repo.abrir_estacion_por_miembro(self.estacion, "lucas", "clave123")
        ahora = datetime.now().replace(microsecond=0)
        # Usó 1 hora: según el mostrador le quedan 2 h; según su PC, 1 h 30.
        sesion_id = self.sesion_que_termina(ahora + timedelta(hours=2), inicio=ahora - timedelta(hours=1))
        reconexion_repo.tomar_el_menor(self.estacion, {"sesion_id": sesion_id, "segundos": 90 * 60, "desde": 600},
                                       ahora=ahora)

        pcs_repo.finalizar_sesion(sesion_id)

        # Le quedaban ~90 minutos: se devuelven en bloques de 30 (60, por los segundos que pasaron).
        self.assertIn(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], (60, 90))


class TestServidorTomaElMenor(test_control_pcs._ConServidorRed):
    """GET /estado con lo que cuenta la PC al volver de un corte (ver _ConServidorRed)."""

    def setUp(self):
        super().setUp()
        admin = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.estacion = pcs_repo.crear_estacion("PC05X")
        pcs_repo.asignar_bono(self.estacion, pcs_repo.crear_bono("1 hora", 60, 1500), admin, EFECTIVO_1500)
        self.sesion_id = pcs_repo.estado_de_estacion("PC05X")["sesion"]["id"]
        # El bono se vendió hace 20 minutos (antes del corte): le quedan 40.
        ahora = datetime.now()
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?, fecha_fin_prevista = ?",
                             (_iso(ahora - timedelta(minutes=20)), _iso(ahora + timedelta(minutes=40))))
            conexion.execute("UPDATE ventas SET fecha = ?",
                             ((ahora - timedelta(minutes=20)).isoformat(timespec="microseconds"),))

    def test_la_respuesta_ya_trae_el_tiempo_de_la_pc_y_el_mostrador_lo_guarda(self):
        status, datos = self._get(f"/estado?estacion=PC05X&sesion={self.sesion_id}&resto=1800&desde=300")

        self.assertEqual(status, 200)
        self.assertFalse(datos["bloqueada"])
        self.assertAlmostEqual(datos["segundos_restantes"], 1800, delta=3)
        self.assertAlmostEqual(pcs_repo.estado_de_estacion("PC05X")["segundos_restantes"], 1800, delta=3)

    def test_una_pc_que_se_quedo_sin_tiempo_en_el_corte_queda_bloqueada(self):
        status, datos = self._get(f"/estado?estacion=PC05X&sesion={self.sesion_id}&resto=0&desde=600")

        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])

    def test_un_cliente_pc_viejo_o_sin_corte_no_cambia_nada(self):
        for consulta in ("/estado?estacion=PC05X", f"/estado?estacion=PC05X&sesion={self.sesion_id}&resto=xx"):
            with self.subTest(consulta=consulta):
                status, datos = self._get(consulta)
                self.assertEqual(status, 200)
                self.assertGreater(datos["segundos_restantes"], 39 * 60)
        self.assertEqual(_ajustes(), [])
