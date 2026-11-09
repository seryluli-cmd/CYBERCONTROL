"""
tests/test_quien_cierra_la_sesion.py
======================================
Cómo se cerró cada sesión de PC (pedido del dueño, 2026-11-09): con qué botón, quién y
cuánto le quedaba. Dos PCs se cerraron con "Finalizar Sesión" estando sin conexión, se
reiniciaron al volver la red y perdieron su tiempo, y en la base no quedaba quién lo
había hecho. Ahora cada camino que cierra una sesión lo deja anotado
(pcs_repo._cerrar_sesion) y Actividad reciente lo dice. Solo se anota: no cambia cómo se
cierra ni lo que se le devuelve a un socio.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from database import conexion_db  # noqa: E402
from database_migraciones import _migrar_columnas_cierre_en_sesiones  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import actividad_repo, miembros_repo, pcs_repo  # noqa: E402
from control_pcs.ui import pcs_actividad  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 5000}]


def _sesion(sesion_id):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM sesiones_pc WHERE id = ?", (sesion_id,)).fetchone()


def _ultimo_fin():
    fin, = [e for e in actividad_repo.actividad_reciente() if e["tipo"] == "FIN"][:1]
    return fin


class _ConPc(BaseConBaseTemporal):
    """Una PC, una empleada y un bono de 1 hora vendido."""

    def setUp(self):
        super().setUp()
        self.empleada_id = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.estacion_id = pcs_repo.crear_estacion("PC16X")
        self.bono_id = pcs_repo.crear_bono("1 Hora", 60, 5000)
        pcs_repo.asignar_bono(self.estacion_id, self.bono_id, self.empleada_id, EFECTIVO)
        self.sesion_id = self.item()["sesion"]["id"]

    def item(self):
        return next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.estacion_id)

    def usuario(self):
        return usuarios_repo.obtener_usuario(self.empleada_id)


class TestQuedaAnotado(_ConPc):
    def test_finalizar_deja_el_boton_quien_y_cuanto_le_quedaba(self):
        pcs_repo.finalizar_sesion(self.sesion_id, dominio.CIERRE_FINALIZAR, self.empleada_id)

        sesion = _sesion(self.sesion_id)
        self.assertEqual(sesion["estado"], dominio.SESION_FINALIZADA)
        self.assertEqual(sesion["motivo_cierre"], dominio.CIERRE_FINALIZAR)
        self.assertEqual(sesion["cerrada_por"], self.empleada_id)
        # Le quedaba casi la hora entera.
        self.assertGreater(sesion["segundos_quedaban_al_cerrar"], 59 * 60)
        self.assertLessEqual(sesion["segundos_quedaban_al_cerrar"], 60 * 60)

    def test_una_que_llego_a_cero_queda_con_cero(self):
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds"),
                              self.sesion_id))
        pcs_repo.finalizar_sesion(self.sesion_id, dominio.CIERRE_TIEMPO_TERMINADO)

        sesion = _sesion(self.sesion_id)
        self.assertEqual(sesion["motivo_cierre"], dominio.CIERRE_TIEMPO_TERMINADO)
        self.assertIsNone(sesion["cerrada_por"])
        self.assertEqual(sesion["segundos_quedaban_al_cerrar"], 0)

    def test_un_bono_vendido_sobre_una_sesion_vencida_la_cierra_por_tiempo(self):
        # _abrir_o_extender_sesion no estira una sesión que ya llegó a cero: la cierra.
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds"),
                              self.sesion_id))
        pcs_repo.asignar_bono(self.estacion_id, self.bono_id, self.empleada_id, EFECTIVO)

        self.assertEqual(_sesion(self.sesion_id)["motivo_cierre"], dominio.CIERRE_TIEMPO_TERMINADO)

    def test_un_motivo_que_no_existe_no_cierra_nada(self):
        with self.assertRaises(ValueError):
            pcs_repo.finalizar_sesion(self.sesion_id, "BORRAR")
        self.assertEqual(_sesion(self.sesion_id)["estado"], dominio.SESION_ACTIVA)

    def test_sin_motivo_queda_como_las_de_antes(self):
        pcs_repo.finalizar_sesion(self.sesion_id)
        sesion = _sesion(self.sesion_id)
        self.assertEqual(sesion["estado"], dominio.SESION_FINALIZADA)
        self.assertIsNone(sesion["motivo_cierre"])
        self.assertIsNone(sesion["cerrada_por"])


class TestCadaBoton(_ConPc):
    """Cada camino del programa que cierra una sesión dice cuál fue."""

    def setUp(self):
        super().setUp()
        # Un cartel abierto de verdad dejaría la prueba colgada esperando que alguien lo cierre.
        for nombre in ("control_pcs.ui.pcs_detalle.confirmar", "control_pcs.ui.pcs_window.confirmar"):
            parche = mock.patch(nombre, return_value=True)
            parche.start()
            self.addCleanup(parche.stop)
        parche = mock.patch("control_pcs.ui.pcs_window.mostrar_info")
        parche.start()
        self.addCleanup(parche.stop)

    def grilla(self):
        grilla = PanelControlPcs(self.usuario())
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def test_el_boton_finalizar_sesion_del_panel(self):
        panel = PanelDetalleEstacion(self.usuario(), lambda: None)
        self.addCleanup(panel.deleteLater)
        panel.mostrar(self.item())

        panel.boton_finalizar.click()

        sesion = _sesion(self.sesion_id)
        self.assertEqual(sesion["motivo_cierre"], dominio.CIERRE_FINALIZAR)
        self.assertEqual(sesion["cerrada_por"], self.empleada_id)

    def test_cerrar_sesion_y_reiniciar_del_clic_derecho(self):
        item = self.item()
        self.grilla()._cerrar_sesion_y_reiniciar(item["estacion"], item["sesion"], item["segundos_restantes"])

        sesion = _sesion(self.sesion_id)
        self.assertEqual(sesion["motivo_cierre"], dominio.CIERRE_Y_REINICIAR)
        self.assertEqual(sesion["cerrada_por"], self.empleada_id)

    def test_la_que_llega_a_cero_la_cierra_el_refresco_sin_nombre(self):
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=5)).isoformat(timespec="seconds"),
                              self.sesion_id))
        grilla = self.grilla()
        grilla._dar_de_baja_las_vencidas(pcs_repo.estado_estaciones())

        sesion = _sesion(self.sesion_id)
        self.assertEqual(sesion["motivo_cierre"], dominio.CIERRE_TIEMPO_TERMINADO)
        # La empleada que tiene abierto el mostrador no la cerró: no lleva su nombre.
        self.assertIsNone(sesion["cerrada_por"])


class TestActividadReciente(_ConPc):
    def test_dice_quien_con_que_boton_y_cuanto_le_quedaba(self):
        with mock.patch.object(pcs_repo, "datetime", wraps=datetime) as reloj:
            # Le quedaban 1 h 04 min cuando la cerraron.
            fin = datetime.fromisoformat(_sesion(self.sesion_id)["fecha_fin_prevista"])
            reloj.now.return_value = fin - timedelta(minutes=4, seconds=30)
            with conexion_db() as conexion:
                conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                                 ((fin + timedelta(hours=1)).isoformat(timespec="seconds"), self.sesion_id))
            pcs_repo.finalizar_sesion(self.sesion_id, dominio.CIERRE_FINALIZAR, self.empleada_id)

        texto = pcs_actividad._texto_evento(_ultimo_fin())

        self.assertTrue(texto.endswith(
            "PC16X: Ana la cerró con \"Finalizar Sesión\" (le quedaban 1h 04m)."), texto)

    def test_cerrar_y_reiniciar(self):
        pcs_repo.finalizar_sesion(self.sesion_id, dominio.CIERRE_Y_REINICIAR, self.empleada_id)
        self.assertIn("Ana la cerró con \"Cerrar sesión y reiniciar\" (le quedaban",
                      pcs_actividad._texto_evento(_ultimo_fin()))

    def test_se_termino_el_tiempo(self):
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"),
                              self.sesion_id))
        pcs_repo.finalizar_sesion(self.sesion_id, dominio.CIERRE_TIEMPO_TERMINADO)
        self.assertTrue(pcs_actividad._texto_evento(_ultimo_fin()).endswith("PC16X: se terminó el tiempo."))

    def test_las_sesiones_de_antes_siguen_diciendo_sesion_finalizada(self):
        pcs_repo.finalizar_sesion(self.sesion_id)
        self.assertTrue(pcs_actividad._texto_evento(_ultimo_fin()).endswith("PC16X: sesión finalizada."))

    def test_con_menos_de_un_minuto_no_dice_cuanto_le_quedaba(self):
        texto = pcs_actividad.texto_del_cierre({"motivo": dominio.CIERRE_FINALIZAR, "usuario_nombre": "Ana",
                                                "segundos_quedaban": 40})
        self.assertEqual(texto, "Ana la cerró con \"Finalizar Sesión\"")


class TestElSocioDesdeSuPc(test_control_pcs._ConServidorRed):
    """POST /logout: el socio cierra su sesión con "Cerrar sesión" en la PC."""

    def test_queda_que_lo_cerro_el_socio(self):
        usuarios_repo.crear_usuario("Test", "1234", dominio.ROL_ADMIN)
        pcs_repo.crear_estacion("PC 8")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 120 WHERE id = ?", (miembro_id,))
        status, _datos = self._post("/login", {"estacion": "PC 8", "usuario": "juan", "clave": "clave123"})
        self.assertEqual(status, 200)
        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        status, _datos = self._post("/logout", {"estacion": "PC 8", "sesion_id": sesion_id})

        self.assertEqual(status, 200)
        sesion = _sesion(sesion_id)
        self.assertEqual(sesion["motivo_cierre"], dominio.CIERRE_SOCIO_DESDE_LA_PC)
        self.assertIsNone(sesion["cerrada_por"])
        self.assertIn("Juan cerró su sesión desde la PC (le quedaban",
                      pcs_actividad._texto_evento(_ultimo_fin()))


class TestMigracion(BaseConBaseTemporal):
    def test_se_puede_correr_dos_veces(self):
        with conexion_db() as conexion:
            _migrar_columnas_cierre_en_sesiones(conexion)
            _migrar_columnas_cierre_en_sesiones(conexion)
            columnas = {fila["name"] for fila in conexion.execute("PRAGMA table_info(sesiones_pc)")}
        self.assertTrue({"motivo_cierre", "cerrada_por", "segundos_quedaban_al_cerrar"} <= columnas)


if __name__ == "__main__":
    unittest.main()
