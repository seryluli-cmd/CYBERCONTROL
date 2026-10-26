"""
tests/test_vuelta_del_admin.py
===============================
La sesión del Administrador vuelve sola, en silencio, a los 10 minutos (pedido
del dueño, 2026-10-26: entra como Administrador para algo rápido y se olvida de
volver a cambiar de usuario). A quién vuelve lo decide
repositories/vuelta_admin_repo.py (la empleada que estaba, si su caja sigue
abierta a su nombre; si no, la pantalla de ingreso); el reloj y la vuelta están
en ui/vuelta_del_admin.py. Las pantallas se prueban sin abrir ninguna ventana
(plataforma "offscreen") y con un reloj de mentira.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import date, datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
import main  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import relevo_repo, turnos_repo, usuarios_repo, vuelta_admin_repo  # noqa: E402
from ui import vuelta_del_admin  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from ui.vuelta_del_admin import VueltaDelAdmin  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

LUNES = date(2026, 1, 5)
DIEZ_MINUTOS = dominio.MINUTOS_ADMIN_VUELVE_SOLO * 60


def _a_las(hora, minuto=0):
    return datetime(LUNES.year, LUNES.month, LUNES.day, hora, minuto)


class _Reloj:
    """Un reloj de mentira, en segundos (como time.monotonic)."""

    def __init__(self):
        self.ahora = 1000.0

    def __call__(self):
        return self.ahora

    def pasar(self, segundos):
        self.ahora += segundos


class _ConEmpleadas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.toby_id = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.gaby_id = usuarios_repo.crear_usuario("GABRIELA", "1234", dominio.ROL_EMPLEADA)

    def _ingresos(self, usuario_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT desde_ip FROM sesiones WHERE usuario_id = ?", (usuario_id,)
            ).fetchall()


class TestAQuienVuelve(_ConEmpleadas):
    def test_vuelve_a_la_empleada_si_su_caja_sigue_abierta(self):
        relevo_repo.abrir_caja(self.toby_id, 50000.0, _a_las(5, 55))

        usuario = vuelta_admin_repo.volver(self.toby_id, _a_las(9))

        self.assertEqual(usuario["nombre"], "TOBY")
        # Su ingreso queda anotado como si hubiera entrado con su clave, en el mostrador.
        self.assertEqual([fila["desde_ip"] for fila in self._ingresos(self.toby_id)], [None])

    def test_sin_nadie_antes_va_al_ingreso(self):
        self.assertIsNone(vuelta_admin_repo.volver(None))

    def test_no_vuelve_a_una_empleada_dada_de_baja(self):
        relevo_repo.abrir_caja(self.toby_id, 50000.0, _a_las(5, 55))
        usuarios_repo.desactivar_usuario(self.toby_id)

        self.assertIsNone(vuelta_admin_repo.volver(self.toby_id, _a_las(9)))
        self.assertEqual(self._ingresos(self.toby_id), [])

    def test_no_vuelve_a_otro_administrador(self):
        self.assertIsNone(vuelta_admin_repo.volver(self.admin_id, _a_las(9)))

    def test_si_su_caja_se_cerro_va_al_ingreso(self):
        relevo_repo.abrir_caja(self.toby_id, 50000.0, _a_las(5, 55))
        turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14))

        self.assertIsNone(vuelta_admin_repo.volver(self.toby_id, _a_las(14, 5)))
        self.assertEqual(self._ingresos(self.toby_id), [])

    def test_si_otra_recibio_la_caja_no_vuelve_a_la_primera(self):
        caja = relevo_repo.abrir_caja(self.toby_id, 50000.0, _a_las(5, 55))
        relevo_repo.recibir_caja(self.gaby_id, caja["caja_numero"], 50000.0, _a_las(10))

        self.assertIsNone(vuelta_admin_repo.volver(self.toby_id, _a_las(10, 5)))
        self.assertEqual(vuelta_admin_repo.volver(self.gaby_id, _a_las(10, 5))["nombre"], "GABRIELA")

    def test_si_su_turno_ya_vencio_va_al_ingreso(self):
        # La Mañana termina a las 14 y la caja se cierra sola a los 30 minutos: a
        # las 15 entra por el ingreso, que cierra su caja como corresponde.
        relevo_repo.abrir_caja(self.toby_id, 50000.0, _a_las(5, 55))

        self.assertIsNone(vuelta_admin_repo.volver(self.toby_id, _a_las(15)))


class TestElReloj(BaseConBaseTemporal):
    """El reloj del Administrador con el repo de mentira."""

    def setUp(self):
        super().setUp()
        self.reloj = _Reloj()
        self.vueltas = []
        self.cobro_a_medias = mock.Mock(return_value=False)
        self.repo = mock.patch.object(vuelta_del_admin, "vuelta_admin_repo").start()
        self.repo.volver.return_value = {"id": 7, "nombre": "TOBY"}
        self.addCleanup(mock.patch.stopall)
        self.vuelta = VueltaDelAdmin(None, 7, self.vueltas.append, self.cobro_a_medias, self.reloj)
        self.addCleanup(self.vuelta.detener)

    def test_antes_de_los_diez_minutos_no_pasa_nada(self):
        self.reloj.pasar(DIEZ_MINUTOS - 1)
        self.vuelta._revisar()

        self.repo.volver.assert_not_called()
        self.assertEqual(self.vueltas, [])

    def test_a_los_diez_minutos_vuelve_en_silencio_a_la_empleada(self):
        self.reloj.pasar(DIEZ_MINUTOS)
        self.vuelta._revisar()

        self.repo.volver.assert_called_once_with(7)
        self.assertEqual(self.vueltas, [{"id": 7, "nombre": "TOBY"}])
        # Ningún cartel: no quedó ninguna ventana abierta encima.
        self.assertIsNone(QApplication.activeModalWidget())

    def test_vuelve_una_sola_vez(self):
        self.reloj.pasar(DIEZ_MINUTOS)
        self.vuelta._revisar()
        self.vuelta._revisar()

        self.assertEqual(len(self.vueltas), 1)

    def test_sin_nadie_a_quien_volver_va_al_ingreso(self):
        self.repo.volver.return_value = None
        self.reloj.pasar(DIEZ_MINUTOS)
        self.vuelta._revisar()

        self.assertEqual(self.vueltas, [None])

    def test_con_algo_a_medias_espera_a_que_se_cierre(self):
        # Un cobro o un formulario abierto: espera. Ventas vacía o Caja se cierran
        # solas (eso lo hace _hay_un_cobro_a_medias) y vuelve en la próxima revisión.
        self.cobro_a_medias.side_effect = [True, True, False]
        self.reloj.pasar(DIEZ_MINUTOS + 300)
        self.vuelta._revisar()
        self.vuelta._revisar()
        self.assertEqual(self.vueltas, [])

        self.vuelta._revisar()
        self.assertEqual(len(self.vueltas), 1)

    def test_si_falla_la_base_no_queda_abierto_el_administrador(self):
        self.repo.volver.side_effect = RuntimeError("disco lleno")
        self.reloj.pasar(DIEZ_MINUTOS)
        with mock.patch.object(vuelta_del_admin, "registrar_error"):
            self.vuelta._revisar()

        self.assertEqual(self.vueltas, [None])


class TestLaVentanaPrincipal(_ConEmpleadas):
    def _ventana(self, usuario_id, **kwargs):
        ventana = MainWindow(usuarios_repo.obtener_usuario(usuario_id), kwargs.pop("al_cerrar_sesion", lambda: None),
                             **kwargs)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)
        return ventana

    def test_solo_el_administrador_tiene_reloj(self):
        self.assertIsNotNone(self._ventana(self.admin_id)._vuelta)
        self.assertIsNone(self._ventana(self.toby_id)._vuelta)

    def test_desde_otra_pc_no_hay_reloj(self):
        with mock.patch("ui.main_window.modo_remoto.es_copia_remota", return_value=True), \
                mock.patch("ui.main_window.modo_remoto.mostrador_en_uso", return_value="MOSTRADOR"):
            ventana = self._ventana(self.admin_id)
        self.assertIsNone(ventana._vuelta)

    def test_operador_recuerda_a_quien_volver(self):
        empleada = self._ventana(self.toby_id)
        empleada._cambiar_operador()
        self.assertEqual(empleada.a_quien_volveria, self.toby_id)

        # El Administrador que sale y vuelve a entrar no la pierde.
        admin = self._ventana(self.admin_id, volver_a=self.toby_id)
        admin._cambiar_operador()
        self.assertEqual(admin.a_quien_volveria, self.toby_id)

    def test_un_cierre_de_turno_no_deja_a_nadie_para_volver(self):
        empleada = self._ventana(self.toby_id)
        empleada._cerrar_sesion()
        self.assertIsNone(empleada.a_quien_volveria)

    def test_la_vuelta_abre_la_sesion_de_ella_o_el_ingreso(self):
        al_ingreso, a_ella = [], []
        admin = self._ventana(self.admin_id, al_cerrar_sesion=lambda: al_ingreso.append(True),
                              volver_a=self.toby_id, al_volver_a=a_ella.append)
        toby = usuarios_repo.obtener_usuario(self.toby_id)

        admin._volver_sola(toby)
        self.assertEqual((a_ella, al_ingreso), ([toby], []))

        admin._volver_sola(None)
        self.assertEqual(al_ingreso, [True])


class TestDeTobyAlAdministradorYDeVuelta(_ConEmpleadas):
    """Todo el camino, con la base de verdad: TOBY aprieta "🔄 Operador", entra el
    Administrador y a los 10 minutos vuelve TOBY sin escribir su clave."""

    def test_a_los_diez_minutos_vuelve_toby(self):
        relevo_repo.abrir_caja(self.toby_id, 50000.0)   # su caja, abierta ahora
        with mock.patch.object(main, "LoginWindow"), \
                mock.patch.object(main, "resolver_caja_al_entrar", return_value=True), \
                mock.patch.object(MainWindow, "showMaximized"):
            aplicacion = main.Aplicacion()
            aplicacion._al_loguearse(usuarios_repo.obtener_usuario(self.toby_id))
            aplicacion.ventana_principal._cambiar_operador()

            aplicacion._al_loguearse(usuarios_repo.obtener_usuario(self.admin_id))
            admin = aplicacion.ventana_principal
            self.addCleanup(admin.deleteLater)
            self.addCleanup(admin.panel_pcs.detener_actualizacion)
            self.assertEqual(admin._vuelta._volver_a_id, self.toby_id)

            admin._vuelta._vence = 0   # pasaron los 10 minutos
            admin._vuelta._revisar()

            de_vuelta = aplicacion.ventana_principal
            self.addCleanup(de_vuelta.deleteLater)
            self.addCleanup(de_vuelta.panel_pcs.detener_actualizacion)
        self.assertEqual(de_vuelta.usuario["nombre"], "TOBY")
        self.assertIsNone(de_vuelta._vuelta)
        self.assertEqual(len(self._ingresos(self.toby_id)), 1)
