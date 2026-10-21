"""
tests/test_avisos_fin_pc.py
=============================
¿La PC se enteró de que se terminó su sesión? (pedido del dueño, 2026-10-21: en la PC 30 se
le terminó el tiempo a un cliente y siguió jugando, con el Cliente PC cerrado). Si la PC no
vuelve a preguntar después del fin, titila como la PlayStation 5 con el tiempo agotado hasta
que vuelva o el operador apriete "Ya revisé la PC". Ver avisos_fin_pc_repo.

Y lo que el dueño pidió cuidar el mismo día: una PC que se reinicia (se colgó un juego) sigue
con su sesión y su tiempo; al socio solo se le redondea a 30 minutos cuando cierra la sesión.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import avisos_fin_pc_repo, cortes_pc_repo, miembros_repo, pcs_repo  # noqa: E402
from control_pcs.ui import pcs_actividad  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO_1500 = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}]
ARRANQUE = "1760000000-4321"


def _iso(momento):
    return momento.isoformat(timespec="seconds")


def _sesion(sesion_id):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM sesiones_pc WHERE id = ?", (sesion_id,)).fetchone()


class _ConPc(BaseConBaseTemporal):
    """Una PC, un Admin y un bono de 1 hora."""

    def setUp(self):
        super().setUp()
        parche = mock.patch.object(cortes_pc_repo, "_PROGRAMA_ABIERTO_DESDE", datetime(2000, 1, 1))
        parche.start()
        self.addCleanup(parche.stop)
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.bono_id = pcs_repo.crear_bono("1 hora", 60, 1500)
        self.estacion = pcs_repo.crear_estacion("PC30X")

    def terminada(self, hace_segundos, ultima_noticia_hace, por_tiempo=True):
        """Vende un bono y lo termina: la sesión terminó hace `hace_segundos` y la PC preguntó
        por última vez hace `ultima_noticia_hace`. Devuelve el id de la sesión."""
        pcs_repo.asignar_bono(self.estacion, self.bono_id, self.admin_id, EFECTIVO_1500)
        ahora = datetime.now()
        fin = ahora - timedelta(seconds=hace_segundos)
        with conexion_db() as conexion:
            sesion_id = conexion.execute("SELECT MAX(id) FROM sesiones_pc").fetchone()[0]
            prevista = fin if por_tiempo else fin + timedelta(minutes=20)
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?, fecha_fin_prevista = ? WHERE id = ?",
                             (_iso(fin - timedelta(minutes=40)), _iso(prevista), sesion_id))
        with mock.patch.object(pcs_repo, "datetime", wraps=datetime) as reloj:
            reloj.now.return_value = fin
            pcs_repo.finalizar_sesion(sesion_id)
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET ultima_conexion = ?, cliente_arranque = ? WHERE id = ?",
                             (_iso(ahora - timedelta(seconds=ultima_noticia_hace)), ARRANQUE, self.estacion))
        return sesion_id

    def item(self):
        item, = [e for e in pcs_repo.estado_estaciones() if e["estacion"]["id"] == self.estacion]
        return item


class TestLaPcNoSeEntero(_ConPc):
    def test_sin_noticias_desde_antes_del_fin_titila(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        fin = self.item()["fin_sin_aviso"]
        self.assertEqual((fin["sesion_id"], fin["por_tiempo"], fin["quien"]), (sesion_id, True, "Bono"))
        self.assertEqual(_sesion(sesion_id)["aviso_fin"], dominio.AVISO_FIN_PENDIENTE)

    def test_si_pregunto_despues_del_fin_ya_se_entero(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=60)
        self.assertIsNone(self.item()["fin_sin_aviso"])

    def test_los_primeros_segundos_tiene_tiempo_de_preguntar(self):
        self.terminada(hace_segundos=pcs_repo.UMBRAL_ENLACE_SEGUNDOS - 5, ultima_noticia_hace=600)
        self.assertIsNone(self.item()["fin_sin_aviso"])

    def test_cortada_antes_de_tiempo_no_dice_que_se_termino_el_tiempo(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=600, por_tiempo=False)
        self.assertFalse(self.item()["fin_sin_aviso"]["por_tiempo"])

    def test_de_un_socio_dice_su_nombre(self):
        miembros_repo.crear_miembro("lucas", "clave123", "Lucas")
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET miembro_id = (SELECT id FROM miembros) WHERE id = ?",
                             (sesion_id,))
        self.assertEqual(self.item()["fin_sin_aviso"]["quien"], "Lucas")

    def test_las_sesiones_de_antes_de_esto_no_titilan(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET aviso_fin = NULL WHERE id = ?", (sesion_id,))
        self.assertIsNone(self.item()["fin_sin_aviso"])

    def test_una_sesion_nueva_en_esa_pc_la_saca_de_la_alerta(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        pcs_repo.asignar_bono(self.estacion, self.bono_id, self.admin_id, EFECTIVO_1500)
        self.assertIsNone(self.item()["fin_sin_aviso"])

    def test_cuando_la_pc_vuelve_a_preguntar_queda_enterada(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        pcs_repo.registrar_conexion(self.estacion)
        self.assertIsNone(self.item()["fin_sin_aviso"])
        self.assertEqual(_sesion(sesion_id)["aviso_fin"], dominio.AVISO_FIN_ENTERADA)

    def test_una_consulta_del_mismo_segundo_del_cierre_no_cuenta(self):
        # Pudo salir antes del cierre: la PC recién se entera en la siguiente.
        sesion_id = self.terminada(hace_segundos=0, ultima_noticia_hace=600)
        with conexion_db() as conexion:
            fin = conexion.execute("SELECT fecha_fin_real FROM sesiones_pc WHERE id = ?", (sesion_id,)).fetchone()[0]
        with conexion_db() as conexion:
            avisos_fin_pc_repo.marcar_enterada(conexion, self.estacion, fin)
        self.assertEqual(_sesion(sesion_id)["aviso_fin"], dominio.AVISO_FIN_PENDIENTE)


class TestYaRevise(_ConPc):
    def test_apaga_la_alerta_y_queda_quien_y_cuando(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        avisos_fin_pc_repo.marcar_revisada(sesion_id, self.admin_id)
        self.assertIsNone(self.item()["fin_sin_aviso"])
        sesion = _sesion(sesion_id)
        self.assertEqual((sesion["aviso_fin"], sesion["aviso_fin_revisado_por"]),
                         (dominio.AVISO_FIN_REVISADO, self.admin_id))
        evento, = [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "FIN_REVISADO"]
        self.assertIn('PC30X: Admin marcó "Ya revisé la PC"', pcs_actividad._texto_evento(evento))

    def test_si_la_pc_ya_habia_vuelto_no_cambia_nada(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        pcs_repo.registrar_conexion(self.estacion)
        avisos_fin_pc_repo.marcar_revisada(sesion_id, self.admin_id)
        self.assertEqual(_sesion(sesion_id)["aviso_fin"], dominio.AVISO_FIN_ENTERADA)

    def test_un_usuario_dado_de_baja_no_puede(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        with conexion_db() as conexion:
            conexion.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (self.admin_id,))
        with self.assertRaises(PermissionError):
            avisos_fin_pc_repo.marcar_revisada(sesion_id, self.admin_id)


class TestCuandoVuelve(_ConPc):
    def test_se_anota_el_corte_y_se_ve_que_fue_despues_del_fin(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        causa = cortes_pc_repo.registrar_si_volvio_de_un_corte(
            pcs_repo.estado_de_estacion("PC30X"),
            {"arranque": "otro-1", "fallas": 0, "sin_ok": None, "encendida": 900})
        self.assertEqual(causa, dominio.CORTE_CLIENTE_REABIERTO)
        with conexion_db() as conexion:
            corte = conexion.execute("SELECT * FROM cortes_pc").fetchone()
        self.assertEqual(corte["sesion_id"], sesion_id)
        evento, = [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "CORTE"]
        self.assertTrue(evento["despues_del_fin"])
        self.assertIn("volvió después de terminada su sesión", pcs_actividad._texto_evento(evento))

    def test_una_pc_libre_que_vuelve_no_anota_nada(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=60)
        self.assertIsNone(cortes_pc_repo.registrar_si_volvio_de_un_corte(
            pcs_repo.estado_de_estacion("PC30X"),
            {"arranque": "otro-1", "fallas": 0, "sin_ok": None, "encendida": 900}))


class TestPantalla(_ConPc):
    def test_el_monitor_titila_con_tiempo_agotado(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        ficha = PanelControlPcs._ficha_de_pc(self.item())
        self.assertTrue(ficha.en_alerta)
        self.assertEqual(ficha.aviso, "TIEMPO AGOTADO")
        self.assertIn("la PC no se enteró", ficha.estado)

    def test_cortada_a_mano_dice_que_no_se_bloqueo(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=600, por_tiempo=False)
        self.assertEqual(PanelControlPcs._ficha_de_pc(self.item()).aviso, "NO SE BLOQUEÓ")

    def test_una_pc_que_se_entero_y_se_apago_no_titila(self):
        # Preguntó después del fin (se bloqueó) y después la apagaron: rojo fijo, como siempre.
        self.terminada(hace_segundos=120, ultima_noticia_hace=60)
        ficha = PanelControlPcs._ficha_de_pc(self.item())
        self.assertFalse(ficha.en_alerta)
        self.assertIn("Sin conexión", ficha.estado)

    def test_el_panel_ofrece_ya_revise_la_pc(self):
        sesion_id = self.terminada(hace_segundos=120, ultima_noticia_hace=600)
        panel = PanelDetalleEstacion(usuarios_repo.obtener_usuario(self.admin_id), lambda: None)
        panel.mostrar(self.item())
        self.assertEqual(panel.boton_finalizar.text(), "Ya revisé la PC")
        self.assertTrue(panel.boton_finalizar.isEnabled())
        with mock.patch("control_pcs.ui.pcs_detalle.confirmar", return_value=True):
            panel.boton_finalizar.click()
        self.assertEqual(_sesion(sesion_id)["aviso_fin"], dominio.AVISO_FIN_REVISADO)

    def test_una_pc_bloqueada_normal_sigue_igual(self):
        self.terminada(hace_segundos=120, ultima_noticia_hace=60)
        panel = PanelDetalleEstacion(usuarios_repo.obtener_usuario(self.admin_id), lambda: None)
        panel.mostrar(self.item())
        self.assertEqual(panel.boton_finalizar.text(), "Finalizar Sesión")
        self.assertFalse(panel.boton_finalizar.isEnabled())


class TestServidor(test_control_pcs._ConServidorRed):
    """GET /estado (ver _ConServidorRed)."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.bono_id = pcs_repo.crear_bono("1 hora", 60, 1500)
        self.estacion = pcs_repo.crear_estacion("PC30X")

    def test_la_consulta_despues_del_fin_la_deja_enterada(self):
        pcs_repo.asignar_bono(self.estacion, self.bono_id, self.admin_id, EFECTIVO_1500)
        with conexion_db() as conexion:
            sesion_id = conexion.execute("SELECT id FROM sesiones_pc").fetchone()[0]
        pcs_repo.finalizar_sesion(sesion_id)
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_real = ?",
                             (_iso(datetime.now() - timedelta(minutes=1)),))
        status, datos = self._get("/estado?estacion=PC30X")
        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertEqual(_sesion(sesion_id)["aviso_fin"], dominio.AVISO_FIN_ENTERADA)

    def test_una_pc_que_se_reinicia_sigue_con_su_sesion_y_su_tiempo(self):
        # Pedido del dueño: si un juego se colgó y la PC se reinicia, no se le descuenta nada.
        # El socio entra con 2 horas; la PC se reinicia y vuelve: misma sesión, mismo vencimiento,
        # sin reintegro ni redondeo a 30 minutos (eso es solo al cerrar la sesión).
        miembro_id = miembros_repo.crear_miembro("lucas", "clave123", "Lucas")
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 120 WHERE id = ?", (miembro_id,))
        miembros_repo.abrir_estacion_por_miembro(self.estacion, "lucas", "clave123")
        antes = pcs_repo.estado_de_estacion("PC30X")["sesion"]
        parche = mock.patch.object(cortes_pc_repo, "_PROGRAMA_ABIERTO_DESDE", datetime(2000, 1, 1))
        parche.start()
        self.addCleanup(parche.stop)
        with conexion_db() as conexion:
            # Estaba jugando hace rato y hace 2 minutos que no se sabe nada de la PC.
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?",
                             (_iso(datetime.now() - timedelta(minutes=10)),))
            conexion.execute("UPDATE estaciones SET ultima_conexion = ?, cliente_arranque = ?",
                             (_iso(datetime.now() - timedelta(minutes=2)), ARRANQUE))
            movimientos_antes = conexion.execute("SELECT COUNT(*) FROM movimientos_saldo_miembro").fetchone()[0]

        status, datos = self._get("/estado?estacion=PC30X&arranque=otro-1&encendida=40")

        self.assertEqual(status, 200)
        self.assertFalse(datos["bloqueada"])
        self.assertEqual(datos["sesion_id"], antes["id"])
        despues = _sesion(antes["id"])
        self.assertEqual((despues["estado"], despues["fecha_fin_prevista"]),
                         (dominio.SESION_ACTIVA, antes["fecha_fin_prevista"]))
        with conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM movimientos_saldo_miembro").fetchone()[0],
                             movimientos_antes)
            self.assertEqual(conexion.execute("SELECT saldo_minutos FROM miembros").fetchone()[0], 0)
            corte = conexion.execute("SELECT causa FROM cortes_pc").fetchone()
        self.assertEqual(corte["causa"], dominio.CORTE_PC_REINICIADA)
