"""
tests/test_reinicio_actualizacion.py
====================================
Una PC libre que terminó de copiar el Cliente PC nuevo se reinicia sola para ponerlo, y el mosaico
la muestra REINICIANDO hasta que vuelve (pedido del dueño, 2026-10-28; ver
reinicio_actualizacion_repo y comandos_pc_repo). Todo por el servidor de red, como lo ve la PC.
"""

import os
from datetime import datetime, timedelta
from unittest import mock
from urllib.parse import urlencode

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    actualizacion_cliente_repo, comandos_pc_repo, pcs_repo, reinicio_actualizacion_repo,
)
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from test_control_pcs import _ConServidorRed  # noqa: E402

_app = QApplication.instance() or QApplication([])

INSTALADA = 20261001120000
NUEVA = 20261028100000
OTRA_NUEVA = 20261028180000


def reinicios():
    """Los Reiniciar que hay en la cola (de cualquier estado), del más viejo al más nuevo."""
    with conexion_db() as conexion:
        return conexion.execute(
            "SELECT * FROM comandos_pc WHERE tipo = ? ORDER BY id", (comandos_pc_repo.TIPO_REINICIAR,)
        ).fetchall()


def envejecer(comando_id, minutos):
    """Hace de cuenta que el comando se encoló hace `minutos`."""
    antes = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")
    with conexion_db() as conexion:
        conexion.execute("UPDATE comandos_pc SET fecha_creacion = ? WHERE id = ?", (antes, comando_id))


class _ConPcActualizandose(_ConServidorRed):
    def setUp(self):
        super().setUp()
        actualizacion_cliente_repo.olvidar_reportes()
        self.addCleanup(actualizacion_cliente_repo.olvidar_reportes)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.le_toca = NUEVA
        parche = mock.patch.object(actualizacion_cliente_repo, "version_para_estacion",
                                   side_effect=lambda _estacion_id: self.le_toca)
        parche.start()
        self.addCleanup(parche.stop)

    def consultar(self, **cambios):
        """Un GET /estado de la PC1 que cuenta que ya copió la versión NUEVA (lo que manda el Cliente
        PC; `cambios` pisa o, con None, saca un parámetro). Devuelve el comando que le tocó, o None."""
        parametros = {"estacion": "PC1", "version": INSTALADA, "carpeta": r"C:\Program Files\AAAAA26\cliente",
                      "act": "descargada", "act_version": NUEVA, "encendida": 3600, **cambios}
        parametros = {clave: valor for clave, valor in parametros.items() if valor is not None}
        estado, datos = self._get("/estado?" + urlencode(parametros))
        self.assertEqual(estado, 200)
        return datos["comando"]

    def item(self):
        return next(item for item in pcs_repo.estado_estaciones() if item["estacion"]["id"] == self.pc1)

    def ocupar(self):
        usuario_id = usuarios_repo.crear_usuario("Operador", "1234", "ADMIN")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        pcs_repo.asignar_bono(self.pc1, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])


class TestSeReiniciaSola(_ConPcActualizandose):
    def test_una_pc_libre_que_copio_la_version_se_reinicia_y_dice_reiniciando(self):
        # La primera consulta solo cuenta que la copió; en la siguiente sale el Reiniciar.
        self.assertIsNone(self.consultar())
        comando = self.consultar()

        self.assertEqual(comando["tipo"], "REINICIAR")
        self.assertEqual(comando["payload"], comandos_pc_repo.payload_reinicio_por_actualizacion(NUEVA))
        self.assertTrue(self.item()["reiniciando"])
        ficha = PanelControlPcs._ficha_de_pc(self.item())
        self.assertEqual(ficha.aviso, "REINICIANDO")
        self.assertIn("Reiniciando", ficha.estado)

    def test_da_igual_que_sea_un_exe_o_un_zip(self):
        # La PC cuenta lo mismo en los dos casos: lo que se mira es la versión que le toca.
        self.consultar(formato=2)
        self.assertEqual(self.consultar(formato=2)["tipo"], "REINICIAR")

    def test_una_sola_vez_por_version(self):
        # Si el reinicio no la pone (Shadow Defender borra la copia), la PC la vuelve a copiar:
        # no se la reinicia de nuevo, eso lo dice la pantalla de actualizar.
        self.consultar()
        self.consultar()
        for _ in range(3):
            self.assertIsNone(self.consultar(encendida=30))
        self.assertEqual(len(reinicios()), 1)

        # Una versión nueva sí vuelve a reiniciarla.
        self.le_toca = OTRA_NUEVA
        self.consultar(act_version=OTRA_NUEVA)
        self.assertEqual(self.consultar(act_version=OTRA_NUEVA)["payload"],
                         comandos_pc_repo.payload_reinicio_por_actualizacion(OTRA_NUEVA))


class TestNoSeReinicia(_ConPcActualizandose):
    def assertNoSeReinicia(self, **cambios):
        for _ in range(3):
            self.assertIsNone(self.consultar(**cambios))
        self.assertEqual(reinicios(), [])
        self.assertFalse(self.item()["reiniciando"])

    def test_con_un_cliente_jugando(self):
        self.ocupar()
        self.assertNoSeReinicia()

    def test_en_mantenimiento_y_si_cuando_termina(self):
        self.assertNoSeReinicia(mant=12)
        self.consultar()                       # terminó el mantenimiento: lo cuenta
        self.assertEqual(self.consultar()["tipo"], "REINICIAR")

    def test_mientras_la_copia(self):
        self.assertNoSeReinicia(act="bajando")

    def test_si_la_que_copio_no_es_la_que_le_toca(self):
        self.assertNoSeReinicia(act_version=INSTALADA + 1)

    def test_si_no_esta_marcada_para_actualizar(self):
        self.le_toca = None
        self.assertNoSeReinicia()

    def test_si_ya_la_tiene_puesta(self):
        self.assertNoSeReinicia(version=NUEVA, act=None, act_version=None)


class TestCuandoVuelve(_ConPcActualizandose):
    def mandado(self):
        """Deja mandado (y entregado) el Reiniciar por actualización y lo devuelve."""
        self.consultar()
        comando = self.consultar()
        self.assertEqual(comando["tipo"], "REINICIAR")
        return comando["id"]

    def test_deja_de_decir_reiniciando_cuando_vuelve_reiniciada(self):
        comando_id = self.mandado()
        envejecer(comando_id, 1)

        self.assertIsNone(self.consultar(version=NUEVA, act=None, act_version=None, encendida=40))

        self.assertFalse(self.item()["reiniciando"])
        self.assertEqual(comandos_pc_repo.obtener_comando(comando_id)["resultado"],
                         comandos_pc_repo.RESULTADO_YA_REINICIADA)
        self.assertNotEqual(PanelControlPcs._ficha_de_pc(self.item()).aviso, "REINICIANDO")

    def test_mientras_no_se_reinicio_sigue_diciendo_reiniciando(self):
        comando_id = self.mandado()
        envejecer(comando_id, 1)
        self.consultar(encendida=3600)    # todavía no arrancó de nuevo
        self.assertTrue(self.item()["reiniciando"])

    def test_si_no_vuelve_deja_de_decirlo_a_los_minutos(self):
        envejecer(self.mandado(), comandos_pc_repo.MINUTOS_REINICIANDO + 1)
        self.assertFalse(self.item()["reiniciando"])

    def test_si_se_reinicio_sola_antes_de_pedirlo_no_se_le_da(self):
        # Por ejemplo al terminar un cliente: se reiniciaría dos veces.
        self.consultar()
        comando_id = reinicio_actualizacion_repo.reiniciar_si_corresponde(pcs_repo.estado_de_estacion("PC1"))
        self.assertIsNotNone(comando_id)
        envejecer(comando_id, 1)

        self.assertIsNone(self.consultar(encendida=30))

        self.assertEqual(comandos_pc_repo.obtener_comando(comando_id)["resultado"],
                         comandos_pc_repo.RESULTADO_YA_REINICIADA)
        self.assertEqual(len(reinicios()), 1)
        self.assertFalse(self.item()["reiniciando"])

    def test_un_reiniciar_del_boton_no_cambia(self):
        # Ni dice REINICIANDO ni se descarta por el arranque: solo el de la actualización.
        comando_id = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_REINICIAR)
        self.assertFalse(self.item()["reiniciando"])
        envejecer(comando_id, 1)

        comando = self.consultar(act=None, act_version=None, encendida=10)

        self.assertEqual((comando["id"], comando["payload"]), (comando_id, None))

    def test_con_un_cliente_no_dice_reiniciando(self):
        self.mandado()
        self.ocupar()
        self.assertNotEqual(PanelControlPcs._ficha_de_pc(self.item()).aviso, "REINICIANDO")
