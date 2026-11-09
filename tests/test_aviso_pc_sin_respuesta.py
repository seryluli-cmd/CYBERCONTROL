"""
tests/test_aviso_pc_sin_respuesta.py
======================================
El aviso antes de cerrar la sesión de una PC que no responde (pedido del dueño, 2026-11-09,
maqueta B). El 02/11 se cortó la red del mostrador y a cuatro PCs en uso se les cerró la
sesión con "Finalizar Sesión"; al volver la red se reiniciaron y perdieron su tiempo. Ahora
"Finalizar Sesión" y "Cerrar sesión y reiniciar" avisan antes, con lo que pierde el cliente y,
si se cortaron varias a la vez, que seguramente es la red del mostrador. NO CERRAR es la tecla
de entrada; CERRAR IGUAL sigue cerrando (la PC que el cliente apagó al irse).
Ver pcs_sin_respuesta_repo y control_pcs/ui/pcs_aviso_sin_respuesta.py.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QDialog  # noqa: E402

import dominio  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import pcs_repo, pcs_sin_respuesta_repo  # noqa: E402
from control_pcs.ui import pcs_aviso_sin_respuesta  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 8000}]


def _iso(momento):
    return momento.isoformat(timespec="seconds")


class _ConPcs(BaseConBaseTemporal):
    """Una empleada y un bono de 5 horas; las PCs se crean en cada prueba."""

    def setUp(self):
        super().setUp()
        self.empleada_id = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.bono_id = pcs_repo.crear_bono("Promo 5hs", 300, 8000)

    def pc_en_uso(self, nombre, sin_noticias_hace=None):
        """Una PC con un bono vendido hace 10 minutos. Con `sin_noticias_hace` (segundos),
        su Cliente PC preguntó por última vez hace eso; sin él, recién (responde)."""
        estacion_id = pcs_repo.crear_estacion(nombre)
        pcs_repo.asignar_bono(estacion_id, self.bono_id, self.empleada_id, EFECTIVO)
        ahora = datetime.now()
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ? WHERE estacion_id = ?",
                             (_iso(ahora - timedelta(minutes=10)), estacion_id))
            conexion.execute("UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                             (_iso(ahora - timedelta(seconds=sin_noticias_hace or 0)), estacion_id))
        return estacion_id

    def item(self, estacion_id):
        return next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == estacion_id)

    def usuario(self):
        return usuarios_repo.obtener_usuario(self.empleada_id)


class TestCuandoAvisa(_ConPcs):
    def test_una_pc_que_responde_no_avisa(self):
        pc = self.pc_en_uso("PC16X")
        self.assertIsNone(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(pc))

    def test_una_pc_sin_noticias_avisa_hace_cuanto_y_lo_que_pierde(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)

        aviso = pcs_sin_respuesta_repo.aviso_antes_de_cerrar(pc)

        self.assertEqual(aviso["estacion_nombre"], "PC16X")
        self.assertAlmostEqual(aviso["segundos_sin_noticias"], 80, delta=3)
        # El bono de 5 horas se vendió recién (pc_en_uso solo corre la hora de inicio): le
        # quedan las 5 horas, que es lo que perdería.
        self.assertAlmostEqual(aviso["segundos_restantes"], 300 * 60, delta=5)
        self.assertEqual(aviso["cortadas_a_la_vez"], 1)

    def test_la_que_todavia_no_se_prendio_no_avisa(self):
        # "Esperando al cliente": se vendió el bono antes de prender la PC. Cerrarla no le
        # saca nada a nadie.
        estacion_id = pcs_repo.crear_estacion("PC16X")
        pcs_repo.asignar_bono(estacion_id, self.bono_id, self.empleada_id, EFECTIVO)
        self.assertIsNone(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(estacion_id))

    def test_la_que_tiene_el_cliente_pc_cerrado_por_admin_no_avisa(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET cliente_cerrado_desde = ? WHERE id = ?",
                             (_iso(datetime.now() - timedelta(seconds=80)), pc))
        self.assertIsNone(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(pc))

    def test_una_pc_libre_no_avisa(self):
        estacion_id = pcs_repo.crear_estacion("PC16X")
        self.assertIsNone(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(estacion_id))


class TestVariasALaVez(_ConPcs):
    def test_las_que_se_cortaron_juntas_se_cuentan(self):
        # Como el 02/11: cuatro PCs en uso dejan de responder en la misma consulta.
        pcs = [self.pc_en_uso(f"PC{n}X", sin_noticias_hace=80 + n) for n in (5, 14, 16, 23)]
        self.assertEqual(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(pcs[2])["cortadas_a_la_vez"], 4)

    def test_no_cuenta_la_que_se_corto_mucho_antes(self):
        # Una PC que el cliente apagó hace 20 minutos no es parte del mismo corte.
        juntas = [self.pc_en_uso(f"PC{n}X", sin_noticias_hace=80) for n in (14, 16)]
        self.pc_en_uso("PC05X", sin_noticias_hace=20 * 60)
        self.assertEqual(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(juntas[0])["cortadas_a_la_vez"], 2)

    def test_no_cuenta_las_que_responden_ni_las_libres(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)
        self.pc_en_uso("PC14X")
        pcs_repo.crear_estacion("PC23X")
        self.assertEqual(pcs_sin_respuesta_repo.aviso_antes_de_cerrar(pc)["cortadas_a_la_vez"], 1)


class TestLaVentana(unittest.TestCase):
    def aviso(self, cortadas):
        return {"estacion_nombre": "PC16X", "segundos_sin_noticias": 80,
                "segundos_restantes": 64 * 60, "cortadas_a_la_vez": cortadas}

    def textos(self, dialogo):
        from PySide6.QtWidgets import QLabel
        return " ".join(etiqueta.text() for etiqueta in dialogo.findChildren(QLabel))

    def test_dice_la_pc_hace_cuanto_y_lo_que_pierde(self):
        dialogo = pcs_aviso_sin_respuesta.DialogoPcSinRespuesta(self.aviso(1))
        self.addCleanup(dialogo.deleteLater)
        textos = self.textos(dialogo)
        self.assertIn("PC16X NO RESPONDE", textos)
        self.assertIn("Hace 1m 20s que no tiene noticias del mostrador", textos)
        self.assertIn("pierde <b>1h&nbsp;04m</b>", textos)

    def test_con_una_sola_no_habla_de_la_red(self):
        dialogo = pcs_aviso_sin_respuesta.DialogoPcSinRespuesta(self.aviso(1))
        self.addCleanup(dialogo.deleteLater)
        self.assertTrue(dialogo.aviso_red.isHidden())
        self.assertTrue(dialogo.pastilla.isHidden())

    def test_con_varias_dice_que_seguramente_es_la_red(self):
        dialogo = pcs_aviso_sin_respuesta.DialogoPcSinRespuesta(self.aviso(4))
        self.addCleanup(dialogo.deleteLater)
        self.assertFalse(dialogo.aviso_red.isHidden())
        self.assertIn("Hay 4 PCs que dejaron de responder a la vez", dialogo.aviso_red.text())
        self.assertEqual(dialogo.pastilla.text(), "4 PCs SIN RESPUESTA")

    def test_no_cerrar_es_la_tecla_de_entrada(self):
        dialogo = pcs_aviso_sin_respuesta.DialogoPcSinRespuesta(self.aviso(4))
        self.addCleanup(dialogo.deleteLater)
        self.assertTrue(dialogo.boton_no_cerrar.isDefault())
        self.assertFalse(dialogo.boton_cerrar_igual.isDefault())
        self.assertFalse(dialogo.boton_cerrar_igual.autoDefault())

    def test_solo_cerrar_igual_acepta(self):
        for boton, resultado in (("boton_no_cerrar", QDialog.Rejected), ("boton_cerrar_igual", QDialog.Accepted)):
            dialogo = pcs_aviso_sin_respuesta.DialogoPcSinRespuesta(self.aviso(1))
            self.addCleanup(dialogo.deleteLater)
            getattr(dialogo, boton).click()
            self.assertEqual(dialogo.result(), resultado, boton)


class TestLosBotones(_ConPcs):
    """Finalizar Sesión y Cerrar sesión y reiniciar abren el aviso solo con una PC que no
    responde; con una que responde, la pregunta de siempre."""

    def setUp(self):
        super().setUp()
        parche = mock.patch("control_pcs.ui.pcs_window.mostrar_info")
        parche.start()
        self.addCleanup(parche.stop)

    def panel(self, estacion_id):
        panel = PanelDetalleEstacion(self.usuario(), lambda: None)
        self.addCleanup(panel.deleteLater)
        panel.mostrar(self.item(estacion_id))
        return panel

    def grilla(self):
        grilla = PanelControlPcs(self.usuario())
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def cerrar_y_reiniciar(self, estacion_id):
        item = self.item(estacion_id)
        self.grilla()._cerrar_sesion_y_reiniciar(item["estacion"], item["sesion"], item["segundos_restantes"])

    def sigue_activa(self, estacion_id):
        return self.item(estacion_id)["sesion"] is not None

    def test_finalizar_en_una_pc_que_no_responde_y_no_cerrar(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)
        with mock.patch.object(pcs_aviso_sin_respuesta, "cerrar_igual", return_value=False) as aviso, \
                mock.patch("control_pcs.ui.pcs_detalle.confirmar") as pregunta:
            self.panel(pc).boton_finalizar.click()
        aviso.assert_called_once()
        self.assertEqual(aviso.call_args.args[1]["estacion_nombre"], "PC16X")
        pregunta.assert_not_called()
        self.assertTrue(self.sigue_activa(pc))

    def test_finalizar_en_una_pc_que_no_responde_y_cerrar_igual(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)
        with mock.patch.object(pcs_aviso_sin_respuesta, "cerrar_igual", return_value=True):
            self.panel(pc).boton_finalizar.click()
        self.assertFalse(self.sigue_activa(pc))

    def test_finalizar_en_una_pc_que_responde_pregunta_lo_de_siempre(self):
        pc = self.pc_en_uso("PC16X")
        with mock.patch.object(pcs_aviso_sin_respuesta, "cerrar_igual") as aviso, \
                mock.patch("control_pcs.ui.pcs_detalle.confirmar", return_value=True) as pregunta:
            self.panel(pc).boton_finalizar.click()
        aviso.assert_not_called()
        self.assertTrue(pregunta.call_args.args[2].startswith("Todavía le quedan"))
        self.assertFalse(self.sigue_activa(pc))

    def test_cerrar_y_reiniciar_en_una_pc_que_no_responde_y_no_cerrar(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)
        with mock.patch.object(pcs_aviso_sin_respuesta, "cerrar_igual", return_value=False) as aviso, \
                mock.patch("control_pcs.ui.pcs_window.confirmar") as pregunta:
            self.cerrar_y_reiniciar(pc)
        aviso.assert_called_once()
        pregunta.assert_not_called()
        self.assertTrue(self.sigue_activa(pc))

    def test_cerrar_y_reiniciar_en_una_pc_que_no_responde_y_cerrar_igual(self):
        pc = self.pc_en_uso("PC16X", sin_noticias_hace=80)
        with mock.patch.object(pcs_aviso_sin_respuesta, "cerrar_igual", return_value=True):
            self.cerrar_y_reiniciar(pc)
        self.assertFalse(self.sigue_activa(pc))

    def test_cerrar_y_reiniciar_en_una_pc_que_responde_pregunta_lo_de_siempre(self):
        pc = self.pc_en_uso("PC16X")
        with mock.patch.object(pcs_aviso_sin_respuesta, "cerrar_igual") as aviso, \
                mock.patch("control_pcs.ui.pcs_window.confirmar", return_value=True):
            self.cerrar_y_reiniciar(pc)
        aviso.assert_not_called()
        self.assertFalse(self.sigue_activa(pc))


if __name__ == "__main__":
    unittest.main()
