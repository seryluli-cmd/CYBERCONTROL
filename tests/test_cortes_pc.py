"""
tests/test_cortes_pc.py
=========================
Los cortes de las PCs (pedido del dueño, 2026-10-19): una PC en uso que titila "SIN CLIENTE" y
vuelve sola. Cuando vuelve, el servidor anota cuánto estuvo sin noticias y por qué, con lo que
cuenta su Cliente PC (CLIENTE PC/pulso.py). Además, la alerta pasó a saltar a los 30 s sin
noticias (antes 15).

- `cortes_pc_repo`: leer lo que manda la PC, la causa y cuándo se anota (y cuándo no).
- `servidor_red.py`: con el servidor real, como los demás tests de la capa HTTP.
- Lo que se ve: "Actividad reciente", el panel de la PC y el cartelito de su monitor (Qt
  "offscreen", sin abrir ventanas).

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
from control_pcs.repositories import cortes_pc_repo, pcs_repo  # noqa: E402
from control_pcs.ui import pcs_actividad, pcs_cortes  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402

_app = QApplication.instance() or QApplication([])

ARRANQUE = "1760000000-4321"


def _pulso(arranque=ARRANQUE, fallas=0, sin_ok=None, encendida=None):
    return {"arranque": arranque, "fallas": fallas, "sin_ok": sin_ok, "encendida": encendida}


def _cortes():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM cortes_pc ORDER BY id").fetchall()


class TestLeerPulso(BaseConBaseTemporal):
    def test_lee_lo_que_manda_el_cliente_pc(self):
        self.assertEqual(
            cortes_pc_repo.leer_pulso({"estacion": "PC1", "arranque": ARRANQUE, "fallas": "5",
                                       "sin_ok": "42", "encendida": "3600"}),
            {"arranque": ARRANQUE, "fallas": 5, "sin_ok": 42, "encendida": 3600},
        )

    def test_un_cliente_pc_viejo_no_manda_nada(self):
        self.assertEqual(cortes_pc_repo.leer_pulso({"estacion": "PC1", "version": ""}),
                         {"arranque": None, "fallas": None, "sin_ok": None, "encendida": None})

    def test_lo_que_no_se_entiende_queda_en_none(self):
        pulso = cortes_pc_repo.leer_pulso({"arranque": "  ", "fallas": "muchas", "sin_ok": "-3",
                                          "encendida": str(10 ** 12)})
        self.assertEqual(pulso, {"arranque": None, "fallas": None, "sin_ok": None, "encendida": None})

    def test_un_arranque_larguisimo_se_corta(self):
        self.assertEqual(len(cortes_pc_repo.leer_pulso({"arranque": "x" * 500})["arranque"]), 40)


class TestCausaDelCorte(BaseConBaseTemporal):
    def causa(self, pulso, segundos=60, arranque_anterior=ARRANQUE):
        return cortes_pc_repo.causa_del_corte(segundos, pulso, arranque_anterior)

    def test_un_cliente_pc_viejo_no_dice_por_que(self):
        self.assertEqual(self.causa(_pulso(arranque=None)), dominio.CORTE_SIN_DATOS)

    def test_el_mismo_programa_con_consultas_que_fallaron_es_la_red(self):
        self.assertEqual(self.causa(_pulso(fallas=6, sin_ok=58, encendida=90000)), dominio.CORTE_RED)

    def test_el_mismo_programa_sin_ninguna_falla_estuvo_trabado(self):
        self.assertEqual(self.causa(_pulso(fallas=0, sin_ok=59, encendida=90000)), dominio.CORTE_CLIENTE_TRABADO)

    def test_si_la_pc_tuvo_respuestas_que_el_mostrador_no_anoto_es_el_mostrador(self):
        self.assertEqual(self.causa(_pulso(fallas=0, sin_ok=5, encendida=90000)), dominio.CORTE_MOSTRADOR)
        # Dentro del margen sigue siendo de la PC: la hora guardada no tiene fracciones de segundo.
        self.assertEqual(self.causa(_pulso(fallas=2, sin_ok=52, encendida=90000)), dominio.CORTE_RED)

    def test_otro_programa_abierto_es_el_cliente_pc_reabierto(self):
        self.assertEqual(self.causa(_pulso(arranque="1760000099-777", encendida=90000)),
                         dominio.CORTE_CLIENTE_REABIERTO)
        self.assertEqual(self.causa(_pulso(arranque="1760000099-777")), dominio.CORTE_CLIENTE_REABIERTO)

    def test_si_windows_lleva_prendido_menos_que_el_corte_se_reinicio_la_pc(self):
        self.assertEqual(self.causa(_pulso(arranque="1760000099-777", encendida=45), segundos=120),
                         dominio.CORTE_PC_REINICIADA)

    def test_si_el_de_antes_no_dijo_quien_era_mira_si_este_ya_tuvo_respuesta(self):
        # El Cliente PC de antes era una versión vieja (no mandaba `arranque`).
        self.assertEqual(self.causa(_pulso(fallas=4, sin_ok=None, encendida=90000), arranque_anterior=None),
                         dominio.CORTE_CLIENTE_REABIERTO)
        self.assertEqual(self.causa(_pulso(fallas=4, sin_ok=58, encendida=90000), arranque_anterior=None),
                         dominio.CORTE_RED)


class _ConPcEnUso(BaseConBaseTemporal):
    """Una PC con un bono corriendo hace 10 minutos cuyo Cliente PC habló por última vez hace
    `sin_noticias` segundos (con el arranque ARRANQUE)."""

    def setUp(self):
        super().setUp()
        # Los cortes que empezaron antes de abrir el programa no se anotan (ver el test de eso):
        # acá el "programa" se abrió hace mucho.
        parche = mock.patch.object(cortes_pc_repo, "_PROGRAMA_ABIERTO_DESDE", datetime(2000, 1, 1))
        parche.start()
        self.addCleanup(parche.stop)
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.bono_id = pcs_repo.crear_bono("1 hora", 60, 1500)

    def pc_en_uso(self, nombre="PC11X", sin_noticias=60, arranque=ARRANQUE):
        estacion = pcs_repo.crear_estacion(nombre)
        pcs_repo.asignar_bono(estacion, self.bono_id, self.admin_id,
                              [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}])
        ahora = datetime.now()
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ? WHERE estacion_id = ?",
                             ((ahora - timedelta(minutes=10)).isoformat(timespec="seconds"), estacion))
            conexion.execute("UPDATE estaciones SET ultima_conexion = ?, cliente_arranque = ? WHERE id = ?",
                             ((ahora - timedelta(seconds=sin_noticias)).isoformat(timespec="seconds"),
                              arranque, estacion))
        return estacion

    def item(self, nombre="PC11X"):
        return pcs_repo.estado_de_estacion(nombre)


class TestUmbralDe30Segundos(_ConPcEnUso):
    def test_veinte_segundos_sin_noticias_todavia_no_es_alerta(self):
        self.pc_en_uso(sin_noticias=20)
        self.assertTrue(self.item()["enlazada"])
        self.assertFalse(cortes_pc_repo.estaba_en_alerta(self.item()))

    def test_mas_de_treinta_si(self):
        self.pc_en_uso(sin_noticias=31)
        self.assertFalse(self.item()["enlazada"])
        self.assertTrue(cortes_pc_repo.estaba_en_alerta(self.item()))


class TestRegistrarElCorte(_ConPcEnUso):
    def test_la_pc_que_vuelve_de_la_alerta_deja_anotado_el_corte(self):
        estacion = self.pc_en_uso(sin_noticias=60)

        causa = cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso(fallas=6, sin_ok=59))

        self.assertEqual(causa, dominio.CORTE_RED)
        corte, = _cortes()
        self.assertEqual((corte["estacion_id"], corte["causa"], corte["fallas"]), (estacion, dominio.CORTE_RED, 6))
        self.assertAlmostEqual(corte["segundos"], 60, delta=2)
        self.assertEqual(corte["sesion_id"], self.item()["sesion"]["id"])

    def test_una_pc_que_viene_hablando_normal_no_anota_nada(self):
        self.pc_en_uso(sin_noticias=5)
        self.assertIsNone(cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso()))
        self.assertEqual(_cortes(), [])

    def test_una_pc_libre_que_se_apago_no_es_un_corte(self):
        estacion = pcs_repo.crear_estacion("PC2")
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                             ((datetime.now() - timedelta(hours=8)).isoformat(timespec="seconds"), estacion))
        self.assertIsNone(cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item("PC2"), _pulso()))
        self.assertEqual(_cortes(), [])

    def test_la_pc_que_esperaba_que_el_cliente_la_prenda_no_es_un_corte(self):
        estacion = self.pc_en_uso()
        with conexion_db() as conexion:   # el bono se vendió con la PC apagada desde hace horas
            conexion.execute("UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                             ((datetime.now() - timedelta(hours=8)).isoformat(timespec="seconds"), estacion))
        self.assertTrue(self.item()["esperando_cliente"])
        self.assertIsNone(cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso()))

    def test_el_cliente_pc_cerrado_desde_el_panel_admin_ya_tiene_su_propio_aviso(self):
        estacion = self.pc_en_uso()
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET cliente_cerrado_desde = ? WHERE id = ?",
                             ((datetime.now() - timedelta(seconds=50)).isoformat(timespec="seconds"), estacion))
        self.assertIsNone(cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso()))

    def test_un_corte_que_empezo_con_el_mostrador_cerrado_no_es_de_la_pc(self):
        self.pc_en_uso(sin_noticias=60)
        recien_abierto = datetime.now() - timedelta(seconds=20)

        self.assertIsNone(cortes_pc_repo.registrar_si_volvio_de_un_corte(
            self.item(), _pulso(fallas=3), programa_abierto_desde=recien_abierto))
        self.assertEqual(_cortes(), [])

    def test_la_pc_muestra_solo_los_cortes_de_su_sesion_en_curso(self):
        estacion = self.pc_en_uso()
        cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso(fallas=3, sin_ok=59))
        pcs_repo.registrar_conexion(estacion)
        self.assertEqual([c["causa"] for c in pcs_repo.estado_estaciones()[0]["cortes"]], [dominio.CORTE_RED])

        pcs_repo.finalizar_sesion(self.item()["sesion"]["id"])
        pcs_repo.asignar_bono(estacion, self.bono_id, self.admin_id,
                              [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}])

        self.assertEqual(pcs_repo.estado_estaciones()[0]["cortes"], [])

    def test_aparece_en_la_actividad_reciente(self):
        self.pc_en_uso()
        cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso(arranque="otro-1"))

        corte, = [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "CORTE"]
        self.assertEqual((corte["estacion_nombre"], corte["causa"]), ("PC11X", dominio.CORTE_CLIENTE_REABIERTO))


class TestServidorConPulso(test_control_pcs._ConServidorRed):
    """GET /estado con el pulso del Cliente PC (ver _ConServidorRed)."""

    def setUp(self):
        super().setUp()
        parche = mock.patch.object(cortes_pc_repo, "_PROGRAMA_ABIERTO_DESDE", datetime(2000, 1, 1))
        parche.start()
        self.addCleanup(parche.stop)
        admin = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.estacion = pcs_repo.crear_estacion("PC11X")
        pcs_repo.asignar_bono(self.estacion, pcs_repo.crear_bono("1 hora", 60, 1500), admin,
                              [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}])

    def _sin_noticias_hace(self, segundos):
        ahora = datetime.now()
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?",
                             ((ahora - timedelta(minutes=10)).isoformat(timespec="seconds"),))
            conexion.execute("UPDATE estaciones SET ultima_conexion = ?",
                             ((ahora - timedelta(seconds=segundos)).isoformat(timespec="seconds"),))

    def test_guarda_el_arranque_y_al_volver_de_un_corte_anota_la_causa(self):
        status, _ = self._get(f"/estado?estacion=PC11X&arranque={ARRANQUE}&fallas=0&encendida=90000")
        self.assertEqual(status, 200)
        self.assertEqual(pcs_repo.obtener_estacion(self.estacion)["cliente_arranque"], ARRANQUE)
        self.assertEqual(_cortes(), [])   # una consulta normal no anota nada

        self._sin_noticias_hace(70)
        status, datos = self._get(f"/estado?estacion=PC11X&arranque={ARRANQUE}&fallas=8&sin_ok=69&encendida=90070")

        self.assertEqual(status, 200)
        self.assertFalse(datos["bloqueada"])
        corte, = _cortes()
        self.assertEqual((corte["causa"], corte["fallas"]), (dominio.CORTE_RED, 8))
        self.assertTrue(pcs_repo.estado_de_estacion("PC11X")["enlazada"])

    def test_un_cliente_pc_reabierto_cambia_el_arranque(self):
        self._get(f"/estado?estacion=PC11X&arranque={ARRANQUE}&fallas=0")
        self._sin_noticias_hace(70)

        self._get("/estado?estacion=PC11X&arranque=1760000300-99&fallas=0&encendida=90000")

        self.assertEqual(_cortes()[0]["causa"], dominio.CORTE_CLIENTE_REABIERTO)
        self.assertEqual(pcs_repo.obtener_estacion(self.estacion)["cliente_arranque"], "1760000300-99")

    def test_un_cliente_pc_viejo_igual_anota_el_corte_sin_causa(self):
        self._sin_noticias_hace(70)

        status, _ = self._get("/estado?estacion=PC11X&version=")

        self.assertEqual(status, 200)
        self.assertEqual(_cortes()[0]["causa"], dominio.CORTE_SIN_DATOS)
        self.assertIsNone(_cortes()[0]["fallas"])


class TestLoQueSeVe(_ConPcEnUso):
    CORTE = {"causa": dominio.CORTE_RED, "segundos": 40, "fallas": 5, "fecha_hora": "2026-10-19T05:12:00"}

    def test_la_linea_de_actividad_dice_cuanto_y_por_que(self):
        linea = pcs_actividad._texto_evento({"fecha": "2026-10-19T05:12:00", "tipo": "CORTE",
                                             "estacion_nombre": "PC11X", **self.CORTE})
        self.assertEqual(linea, "05:12 — PC11X: estuvo 0m 40s sin noticias: se cortó la comunicación con el "
                                "mostrador (red), 5 consultas sin respuesta.")

    def test_las_fallas_solo_se_nombran_cuando_es_la_red(self):
        self.assertEqual(pcs_cortes.detalle_del_corte(dominio.CORTE_PC_REINICIADA, 95, 7),
                         "estuvo 1m 35s sin noticias: la PC se reinició")

    def test_el_resumen_cuenta_los_cortes_de_la_sesion_por_causa(self):
        cortes = [self.CORTE, {**self.CORTE, "causa": dominio.CORTE_PC_REINICIADA}, self.CORTE]
        self.assertEqual(pcs_cortes.resumen_de_cortes(cortes), "3 cortes en esta sesión (red ×2, PC reiniciada)")
        self.assertEqual(pcs_cortes.resumen_de_cortes([self.CORTE]), "1 corte en esta sesión (red)")

    def _panel(self):
        panel = PanelDetalleEstacion(usuarios_repo.obtener_usuario(self.admin_id), lambda: None)
        self.addCleanup(panel.deleteLater)
        return panel

    def _ficha(self, nombre):
        """La ficha de `nombre` en el mosaico (la primera es la PlayStation 5)."""
        grilla = PanelControlPcs(usuarios_repo.obtener_usuario(self.admin_id))
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        fichas = [grilla.mosaico.ficha(fila) for fila in range(grilla.mosaico.count())]
        ficha, = [ficha for ficha in fichas if ficha.nombre == nombre]
        return ficha

    def test_el_panel_avisa_desde_cuando_no_hay_noticias(self):
        self.pc_en_uso(sin_noticias=45)
        panel = self._panel()

        panel.mostrar(pcs_repo.estado_estaciones()[0])

        self.assertIn("Sin noticias de esta PC hace 0m 4", panel.etiqueta_estado.text())
        self.assertNotIn("corte", panel.etiqueta_estado.text())

    def test_cuando_vuelve_el_panel_y_el_cartelito_dicen_por_que_se_corto(self):
        estacion = self.pc_en_uso(sin_noticias=45)
        cortes_pc_repo.registrar_si_volvio_de_un_corte(self.item(), _pulso(fallas=5, sin_ok=44))
        pcs_repo.registrar_conexion(estacion)
        panel = self._panel()

        panel.mostrar(pcs_repo.estado_estaciones()[0])

        texto = panel.etiqueta_estado.text()
        self.assertNotIn("Sin noticias", texto)
        self.assertIn("1 corte en esta sesión (red). El último fue hace 0m 0", texto)
        self.assertIn(" y estuvo 0m 4", texto)
        self.assertIn("se cortó la comunicación con el mostrador (red), 5 consultas sin respuesta", texto)

        self.assertEqual(self._ficha("PC11X").estado, "▶ En uso\n⚠ 1 corte en esta sesión (red)")

    def test_mientras_titila_el_cartelito_dice_desde_cuando(self):
        self.pc_en_uso(sin_noticias=125)

        ficha = self._ficha("PC11X")

        self.assertTrue(ficha.en_alerta)
        self.assertRegex(ficha.estado, r"^🚨 SIN CLIENTE hace 2m 0\ds \(revisar\)$")
