"""
tests/test_reinicios_pc.py
============================
Por qué el Cliente PC reinició o apagó una PC (revisión del 2026-10-21: a un chico se le
reinició la PC jugando y no se sabía si había sido el programa). La PC lo cuenta en su
próxima consulta (CLIENTE PC/motivo_reinicio.py) y el mostrador lo muestra en "Actividad
reciente"; un corte "la PC se reinició" sin ese aviso no lo pidió el Cliente PC.

- `reinicios_pc_repo`: leer lo que manda la PC, anotarlo una sola vez y saber si un reinicio
  de un corte lo pidió el programa.
- `servidor_red.py`: con el servidor real.
- Lo que se ve: las líneas de "Actividad reciente".

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
from control_pcs.repositories import cortes_pc_repo, pcs_repo, reinicios_pc_repo  # noqa: E402
from control_pcs.ui import pcs_actividad  # noqa: E402

_app = QApplication.instance() or QApplication([])

ARRANQUE = "1760000000-4321"


def _reinicios():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM reinicios_pc ORDER BY id").fetchall()


def _aviso(motivo=dominio.REINICIO_ORDEN_REINICIAR, marca=1, hace=30, quedaban=None):
    return {"motivo": motivo, "marca": marca, "hace": hace, "quedaban": quedaban}


class TestLeerReinicio(BaseConBaseTemporal):
    def test_lee_lo_que_manda_el_cliente_pc(self):
        self.assertEqual(
            reinicios_pc_repo.leer_reinicio({"estacion": "PC1", "reinicio": "SESION_TERMINADA",
                                             "reinicio_marca": "123", "reinicio_hace": "40",
                                             "reinicio_quedaban": "600"}),
            {"motivo": dominio.REINICIO_SESION_TERMINADA, "marca": 123, "hace": 40, "quedaban": 600},
        )

    def test_sin_aviso_no_hay_nada(self):
        self.assertIsNone(reinicios_pc_repo.leer_reinicio({"estacion": "PC1"}))

    def test_un_motivo_desconocido_o_datos_rotos_no_se_anotan(self):
        bien = {"reinicio": "ORDEN_REINICIAR", "reinicio_marca": "1", "reinicio_hace": "5"}
        for cambio in ({"reinicio": "OTRA_COSA"}, {"reinicio_marca": "x"}, {"reinicio_hace": "-1"},
                       {"reinicio_hace": str(reinicios_pc_repo.MAXIMO_SEGUNDOS_ATRAS + 1)}):
            with self.subTest(cambio=cambio):
                self.assertIsNone(reinicios_pc_repo.leer_reinicio({**bien, **cambio}))

    def test_sin_lo_que_quedaba_igual_vale(self):
        aviso = reinicios_pc_repo.leer_reinicio({"reinicio": "ORDEN_APAGAR", "reinicio_marca": "1",
                                                 "reinicio_hace": "5"})
        self.assertIsNone(aviso["quedaban"])


class _ConPc(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        parche = mock.patch.object(cortes_pc_repo, "_PROGRAMA_ABIERTO_DESDE", datetime(2000, 1, 1))
        parche.start()
        self.addCleanup(parche.stop)
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.bono_id = pcs_repo.crear_bono("1 hora", 60, 1500)
        self.estacion = pcs_repo.crear_estacion("PC11X")

    def version(self, numero):
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET numero_version_cliente = ?", (numero,))

    def en_uso_sin_noticias(self, segundos):
        pcs_repo.asignar_bono(self.estacion, self.bono_id, self.admin_id,
                              [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}])
        ahora = datetime.now()
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?",
                             ((ahora - timedelta(minutes=10)).isoformat(timespec="seconds"),))
            conexion.execute("UPDATE estaciones SET ultima_conexion = ?, cliente_arranque = ?",
                             ((ahora - timedelta(seconds=segundos)).isoformat(timespec="seconds"), ARRANQUE))

    def volvio_reiniciada(self):
        """La PC vuelve de un corte con otro programa y Windows recién prendido: PC_REINICIADA."""
        cortes_pc_repo.registrar_si_volvio_de_un_corte(
            pcs_repo.estado_de_estacion("PC11X"),
            {"arranque": "otro-1", "fallas": 0, "sin_ok": None, "encendida": 20})

    def corte_en_actividad(self):
        corte, = [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "CORTE"]
        return corte


class TestRegistrar(_ConPc):
    def test_anota_cuando_lo_pidio_con_el_motivo_y_lo_que_quedaba(self):
        ahora = datetime(2026, 10, 21, 20, 0, 0)
        reinicios_pc_repo.registrar(self.estacion, _aviso(dominio.REINICIO_SESION_TERMINADA, hace=90,
                                                          quedaban=1500), ahora=ahora)

        fila, = _reinicios()
        self.assertEqual((fila["estacion_id"], fila["fecha_hora"], fila["motivo"], fila["segundos_quedaban"]),
                         (self.estacion, "2026-10-21T19:58:30", dominio.REINICIO_SESION_TERMINADA, 1500))

    def test_el_mismo_aviso_dos_veces_queda_uno(self):
        reinicios_pc_repo.registrar(self.estacion, _aviso(marca=5))
        reinicios_pc_repo.registrar(self.estacion, _aviso(marca=5, hace=40))
        reinicios_pc_repo.registrar(self.estacion, _aviso(marca=6))
        self.assertEqual(len(_reinicios()), 2)


class TestFuePedido(_ConPc):
    def test_un_reinicio_que_pidio_el_cliente_pc(self):
        self.version("1.3")
        self.en_uso_sin_noticias(90)
        reinicios_pc_repo.registrar(self.estacion, _aviso(hace=95))
        self.volvio_reiniciada()
        self.assertIs(self.corte_en_actividad()["reinicio_pedido"], True)

    def test_un_reinicio_sin_aviso_no_lo_pidio_el_cliente_pc(self):
        self.version("1.3")
        self.en_uso_sin_noticias(90)
        self.volvio_reiniciada()
        self.assertIs(self.corte_en_actividad()["reinicio_pedido"], False)

    def test_un_aviso_de_mucho_antes_no_es_de_este_reinicio(self):
        self.version("1.3")
        self.en_uso_sin_noticias(90)
        reinicios_pc_repo.registrar(self.estacion, _aviso(hace=3600))
        self.volvio_reiniciada()
        self.assertIs(self.corte_en_actividad()["reinicio_pedido"], False)

    def test_un_cliente_pc_anterior_a_la_v13_no_avisa_asi_que_no_se_sabe(self):
        for version in (None, "1.2"):
            with self.subTest(version=version):
                self.version(version)
                self.assertIsNone(reinicios_pc_repo.fue_pedido(None, self.estacion, "2026-10-21T20:00:00", 90,
                                                               version))

    def test_un_reinicio_del_seguro_de_fin_de_sesion_se_distingue(self):
        # El Cliente PC no estaba andando y la reinició la tarea de Windows (CLIENTE PC/seguro_fin.py).
        self.version("1.3")
        self.en_uso_sin_noticias(90)
        reinicios_pc_repo.registrar(self.estacion, _aviso(dominio.REINICIO_SEGURO_FIN, hace=95, quedaban=0))
        self.volvio_reiniciada()
        corte = self.corte_en_actividad()
        self.assertIs(corte["reinicio_pedido"], True)
        self.assertTrue(corte["reinicio_por_seguro"])
        self.assertIn("(la reinició el seguro de fin de sesión: el Cliente PC no estaba andando).",
                      pcs_actividad._texto_evento(corte))

    def test_un_reinicio_del_cliente_pc_no_es_del_seguro(self):
        self.version("1.3")
        self.en_uso_sin_noticias(90)
        reinicios_pc_repo.registrar(self.estacion, _aviso(hace=95))
        self.volvio_reiniciada()
        self.assertFalse(self.corte_en_actividad()["reinicio_por_seguro"])

    def test_un_corte_que_no_es_un_reinicio_no_dice_nada(self):
        self.version("1.3")
        self.en_uso_sin_noticias(90)
        cortes_pc_repo.registrar_si_volvio_de_un_corte(
            pcs_repo.estado_de_estacion("PC11X"), {"arranque": ARRANQUE, "fallas": 5, "sin_ok": 89, "encendida": 9000})
        self.assertIsNone(self.corte_en_actividad()["reinicio_pedido"])


class TestActividad(_ConPc):
    def reinicios_en_actividad(self):
        return [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "REINICIO"]

    def test_el_reinicio_de_todos_los_dias_no_aparece(self):
        reinicios_pc_repo.registrar(self.estacion, _aviso(dominio.REINICIO_SESION_TERMINADA, marca=1, quedaban=4))
        self.assertEqual(self.reinicios_en_actividad(), [])

    def test_los_demas_si(self):
        reinicios_pc_repo.registrar(self.estacion, _aviso(dominio.REINICIO_SESION_TERMINADA, marca=1, quedaban=1500))
        reinicios_pc_repo.registrar(self.estacion, _aviso(dominio.REINICIO_ORDEN_REINICIAR, marca=2))
        self.assertEqual({e["motivo"] for e in self.reinicios_en_actividad()},
                         {dominio.REINICIO_SESION_TERMINADA, dominio.REINICIO_ORDEN_REINICIAR})

    def linea(self, motivo, quedaban=None):
        return pcs_actividad._texto_evento({"fecha": "2026-10-21T20:05:00", "tipo": "REINICIO",
                                            "estacion_nombre": "PC11X", "motivo": motivo,
                                            "segundos_quedaban": quedaban})

    def test_las_lineas_dicen_por_que(self):
        self.assertEqual(self.linea(dominio.REINICIO_ORDEN_REINICIAR),
                         "20:05 — PC11X: el Cliente PC la reinició por la orden Reiniciar del mostrador.")
        self.assertEqual(self.linea(dominio.REINICIO_ORDEN_APAGAR),
                         "20:05 — PC11X: el Cliente PC la apagó por la orden Apagar del mostrador.")
        self.assertIn("descongelarla", self.linea(dominio.REINICIO_DESCONGELAR))
        self.assertIn("sin conexión", self.linea(dominio.REINICIO_TIEMPO_SIN_CONEXION))
        self.assertIn("seguro de fin de sesión", self.linea(dominio.REINICIO_SEGURO_FIN, quedaban=0))
        self.assertEqual(self.linea(dominio.REINICIO_SESION_TERMINADA, quedaban=1500),
                         "20:05 — PC11X: el Cliente PC la reinició porque el mostrador dio la sesión por "
                         "terminada cuando, según la PC, le quedaban 25m 00s (se cerró, se finalizó o se "
                         "pasó a otra PC).")

    def test_un_corte_por_reinicio_dice_si_lo_pidio_el_cliente_pc(self):
        corte = {"fecha": "2026-10-21T20:05:00", "tipo": "CORTE", "estacion_nombre": "PC11X",
                 "causa": dominio.CORTE_PC_REINICIADA, "segundos": 95, "fallas": 0}
        self.assertIn("(la reinició el Cliente PC).", pcs_actividad._texto_evento({**corte, "reinicio_pedido": True}))
        sin_pedido = pcs_actividad._texto_evento({**corte, "reinicio_pedido": False})
        self.assertIn("SIN que la reiniciara el Cliente PC", sin_pedido)
        self.assertEqual(pcs_actividad._texto_evento({**corte, "reinicio_pedido": None}),
                         "20:05 — PC11X: estuvo 1m 35s sin noticias: la PC se reinició.")


class TestServidor(test_control_pcs._ConServidorRed):
    """GET /estado con el aviso del Cliente PC (ver _ConServidorRed)."""

    def setUp(self):
        super().setUp()
        self.estacion = pcs_repo.crear_estacion("PC11X")

    def test_el_aviso_queda_anotado(self):
        status, _ = self._get("/estado?estacion=PC11X&v=1.3&reinicio=ORDEN_REINICIAR&reinicio_marca=77"
                              "&reinicio_hace=20")
        self.assertEqual(status, 200)
        fila, = _reinicios()
        self.assertEqual((fila["estacion_id"], fila["motivo"], fila["marca"]),
                         (self.estacion, dominio.REINICIO_ORDEN_REINICIAR, 77))

    def test_un_aviso_roto_no_rompe_la_consulta(self):
        status, datos = self._get("/estado?estacion=PC11X&reinicio=CUALQUIERA&reinicio_marca=1&reinicio_hace=2")
        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertEqual(_reinicios(), [])
