"""
tests/test_temperatura_pc.py
=============================
La temperatura de las PCs (pedido del dueño, 2026-10-22): cada Cliente PC la manda en su
GET /estado (CLIENTE PC/temperatura.py) y el mosaico la muestra con un termómetro al costado del
monitor; desde dominio.TEMPERATURA_CALIENTE dice "CALIENTE" titilando.

- `dominio.nivel_de_temperatura` y `temperatura_pc_repo`: leer, guardar, cuándo vale.
- `servidor_red.py`: con el servidor real, como los demás tests de la capa HTTP.
- Lo que se ve: la ficha de cada PC y el parpadeo (Qt "offscreen", sin abrir ventanas).

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
from control_pcs.repositories import pcs_repo, temperatura_pc_repo  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _poner(estacion, cpu, gpu=None, hace_segundos=2):
    """La PC preguntó hace `hace_segundos` y su última temperatura fue esa."""
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE estaciones SET temp_cpu = ?, temp_gpu = ?, ultima_conexion = ? WHERE id = ?",
            (cpu, gpu, (datetime.now() - timedelta(seconds=hace_segundos)).isoformat(timespec="seconds"),
             estacion),
        )


class TestNivel(BaseConBaseTemporal):
    def test_los_umbrales(self):
        self.assertIsNone(dominio.nivel_de_temperatura(None))
        self.assertEqual(dominio.nivel_de_temperatura(74), dominio.TEMPERATURA_NORMAL_NIVEL)
        self.assertEqual(dominio.nivel_de_temperatura(75), dominio.TEMPERATURA_TIBIA_NIVEL)
        self.assertEqual(dominio.nivel_de_temperatura(84), dominio.TEMPERATURA_TIBIA_NIVEL)
        self.assertEqual(dominio.nivel_de_temperatura(85), dominio.TEMPERATURA_CALIENTE_NIVEL)


class TestRepo(BaseConBaseTemporal):
    def test_lee_lo_que_manda_el_cliente_pc(self):
        self.assertEqual(temperatura_pc_repo.leer_temperatura({"temp_cpu": "67", "temp_gpu": "48"}),
                         {"cpu": 67, "gpu": 48})

    def test_un_cliente_pc_viejo_o_sin_pawnio_no_manda_el_procesador(self):
        self.assertEqual(temperatura_pc_repo.leer_temperatura({"estacion": "PC1"}), {"cpu": None, "gpu": None})
        self.assertEqual(temperatura_pc_repo.leer_temperatura({"temp_gpu": "31"}), {"cpu": None, "gpu": 31})

    def test_lo_que_no_es_una_temperatura_queda_en_none(self):
        self.assertEqual(temperatura_pc_repo.leer_temperatura({"temp_cpu": "0", "temp_gpu": "255"}),
                         {"cpu": None, "gpu": None})
        self.assertEqual(temperatura_pc_repo.leer_temperatura({"temp_cpu": "mucha", "temp_gpu": "-4"}),
                         {"cpu": None, "gpu": None})

    def test_guarda_la_ultima_y_la_borra_si_deja_de_llegar(self):
        estacion = pcs_repo.crear_estacion("PC1")
        temperatura_pc_repo.registrar(estacion, {"cpu": 70, "gpu": 50})
        self.assertEqual(tuple(pcs_repo.obtener_estacion(estacion)[c] for c in ("temp_cpu", "temp_gpu")), (70, 50))
        temperatura_pc_repo.registrar(estacion, {"cpu": None, "gpu": 50})
        self.assertIsNone(pcs_repo.obtener_estacion(estacion)["temp_cpu"])

    def test_solo_escribe_si_cambio(self):
        # Llega en cada consulta de cada PC (cada 5 s): repetida no se vuelve a grabar.
        estacion = pcs_repo.crear_estacion("PC1")
        self.assertTrue(temperatura_pc_repo.registrar(estacion, {"cpu": 70, "gpu": 50}))
        self.assertFalse(temperatura_pc_repo.registrar(estacion, {"cpu": 70, "gpu": 50}))
        self.assertTrue(temperatura_pc_repo.registrar(estacion, {"cpu": 71, "gpu": 50}))
        self.assertFalse(temperatura_pc_repo.registrar(estacion + 1000, {"cpu": 71, "gpu": 50}))

    def test_de_una_pc_sin_conexion_no_se_muestra_la_vieja(self):
        estacion = pcs_repo.crear_estacion("PC1")
        _poner(estacion, 66, 40, hace_segundos=2)
        self.assertEqual(pcs_repo.estado_de_estacion("PC1")["temperatura"], {"cpu": 66, "gpu": 40})
        _poner(estacion, 66, 40, hace_segundos=pcs_repo.UMBRAL_ENLACE_SEGUNDOS + 5)
        self.assertEqual(pcs_repo.estado_de_estacion("PC1")["temperatura"], {"cpu": None, "gpu": None})


class TestServidor(test_control_pcs._ConServidorRed):
    def test_guarda_la_temperatura_que_manda_la_pc(self):
        estacion = pcs_repo.crear_estacion("PC11X")

        status, datos = self._get("/estado?estacion=PC11X&temp_cpu=88&temp_gpu=61")

        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertEqual(pcs_repo.estado_de_estacion("PC11X")["temperatura"], {"cpu": 88, "gpu": 61})
        self.assertEqual(pcs_repo.obtener_estacion(estacion)["temp_cpu"], 88)

    def test_una_temperatura_rara_no_cambia_la_respuesta(self):
        pcs_repo.crear_estacion("PC11X")
        status, datos = self._get("/estado?estacion=PC11X&temp_cpu=abc")
        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])


class TestLoQueSeVe(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)

    def _grilla(self):
        grilla = PanelControlPcs(usuarios_repo.obtener_usuario(self.admin_id))
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def _fila(self, grilla, nombre):
        fila, = [f for f in range(grilla.mosaico.count()) if grilla.mosaico.ficha(f).nombre == nombre]
        return fila

    def test_cada_pc_lleva_termometro_y_la_consola_no(self):
        _poner(pcs_repo.crear_estacion("PC1"), 62, 48)
        grilla = self._grilla()

        ficha = grilla.mosaico.ficha(self._fila(grilla, "PC1"))
        self.assertTrue(ficha.con_termometro)
        self.assertEqual((ficha.temperatura, ficha.nivel_temperatura), (62, dominio.TEMPERATURA_NORMAL_NIVEL))
        self.assertFalse(ficha.caliente)
        self.assertIn("🌡 Procesador 62° · Placa de video 48°", ficha.estado)
        self.assertFalse(grilla.mosaico.ficha(0).con_termometro)   # la PlayStation 5

    def test_sin_pawnio_el_cartelito_dice_solo_la_placa_de_video(self):
        _poner(pcs_repo.crear_estacion("PC1"), None, 31)
        grilla = self._grilla()

        ficha = grilla.mosaico.ficha(self._fila(grilla, "PC1"))
        self.assertIsNone(ficha.temperatura)
        self.assertIn("🌡 Placa de video 31°", ficha.estado)

    def test_caliente_titila_y_lo_dice_en_el_cartelito(self):
        _poner(pcs_repo.crear_estacion("PC1"), 91, 70)
        _poner(pcs_repo.crear_estacion("PC2"), 60)
        grilla = self._grilla()
        caliente, normal = self._fila(grilla, "PC1"), self._fila(grilla, "PC2")

        ficha = grilla.mosaico.ficha(caliente)
        self.assertTrue(ficha.caliente)
        self.assertIn("CALIENTE", ficha.estado)
        self.assertTrue(grilla.mosaico.calor_visible(caliente))

        grilla._alternar_parpadeo()
        self.assertFalse(grilla.mosaico.calor_visible(caliente))
        self.assertTrue(grilla.mosaico.calor_visible(normal))   # la que está bien no titila
        grilla._alternar_parpadeo()
        self.assertTrue(grilla.mosaico.calor_visible(caliente))

    def test_se_dibuja_sin_errores(self):
        # Termómetro lleno, vacío y sin dato, y "CALIENTE" prendido y apagado.
        _poner(pcs_repo.crear_estacion("PC1"), 91, 70)
        _poner(pcs_repo.crear_estacion("PC2"), 78)
        _poner(pcs_repo.crear_estacion("PC3"), None, 31)
        grilla = self._grilla()
        grilla.resize(1200, 600)
        self.assertFalse(grilla.grab().isNull())
        grilla._alternar_parpadeo()
        self.assertFalse(grilla.grab().isNull())


if __name__ == "__main__":
    import unittest
    unittest.main()
