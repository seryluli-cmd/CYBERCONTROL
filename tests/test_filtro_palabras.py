"""
tests/test_filtro_palabras.py
===============================
El filtro de palabras de las PCs cliente (pedido del dueño, 2026-10-17), del lado del
Servidor:

- `filtro_palabras_repo`: la lista por defecto, cómo se guarda (minúsculas, sin
  repetidas), lo que rechaza, su versión y los bloqueos que avisan las PCs.
- `servidor_red.py`: `GET /filtro`, la `filtro_version` de `GET /estado` y
  `POST /filtro_bloqueo` (con el servidor real, como los demás tests de la capa HTTP).
- "Actividad reciente" y la pantalla "Filtro de palabras de las PCs..." con su botón
  en Gestionar Estaciones.

Cómo busca cada PC las palabras se prueba en `CLIENTE PC/tests/test_filtro_palabras.py`.

Se ejecutan con:

    python -m unittest discover tests
"""

import http.client
import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import dominio  # noqa: E402
import servidor_red  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from control_pcs.repositories import actividad_repo, filtro_palabras_repo, pcs_repo  # noqa: E402
from control_pcs.ui import pcs_actividad, pcs_filtro_dialogo, pcs_gestion_dialogos  # noqa: E402
from database import conexion_db  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestListaDelFiltro(BaseConBaseTemporal):
    def test_sin_tocar_nada_viene_prendido_con_la_lista_del_dueno(self):
        filtro = filtro_palabras_repo.obtener()

        self.assertTrue(filtro["activo"])
        self.assertIn("porno", filtro["palabras"])
        self.assertIn("xvideos", filtro["palabras"])
        self.assertNotIn("dp", filtro["palabras"])   # demasiado común (monitores, cables)
        self.assertTrue(filtro["mensaje"])
        self.assertRegex(filtro["version"], r"^[0-9a-f]{16}$")

    def test_guardar_deja_minusculas_sin_repetidas_ni_renglones_vacios(self):
        filtro = filtro_palabras_repo.guardar(True, "  Porno \n\nXXX\nporno\n sexo   gratis \n", "  Fuera.  ")

        self.assertEqual(filtro["palabras"], ["porno", "xxx", "sexo gratis"])
        self.assertEqual(filtro["mensaje"], "Fuera.")
        self.assertEqual(filtro_palabras_repo.obtener(), filtro)

    def test_se_puede_apagar_y_dejar_sin_mensaje(self):
        filtro = filtro_palabras_repo.guardar(False, "porno", "")

        self.assertFalse(filtro["activo"])
        self.assertEqual(filtro["mensaje"], "")
        self.assertEqual(filtro_palabras_repo.obtener(), filtro)

    def test_la_version_cambia_si_cambia_cualquier_cosa_y_no_si_se_guarda_lo_mismo(self):
        primera = filtro_palabras_repo.guardar(True, "porno", "No.")["version"]

        self.assertEqual(filtro_palabras_repo.guardar(True, "porno", "No.")["version"], primera)
        self.assertEqual(filtro_palabras_repo.version_actual(), primera)
        versiones = {
            filtro_palabras_repo.guardar(False, "porno", "No.")["version"],
            filtro_palabras_repo.guardar(True, "porno\nxxx", "No.")["version"],
            filtro_palabras_repo.guardar(True, "porno", "Otro mensaje.")["version"],
        }
        self.assertEqual(len(versiones), 3)
        self.assertNotIn(primera, versiones)

    def test_rechaza_palabras_que_no_sirven_y_no_toca_lo_guardado(self):
        guardado = filtro_palabras_repo.guardar(True, "porno", "No.")
        for texto, motivo in (("x", "demasiado corta"), ("a" * 61, "demasiado larga"), ("...", "ninguna letra"),
                              ("\n".join(f"palabra{n}" for n in range(1001)), "el máximo es 1000")):
            with self.assertRaises(ValueError) as contexto:
                filtro_palabras_repo.guardar(True, texto, "No.")
            self.assertIn(motivo, str(contexto.exception))
        self.assertEqual(filtro_palabras_repo.obtener(), guardado)

    def test_rechaza_un_mensaje_demasiado_largo(self):
        with self.assertRaises(ValueError):
            filtro_palabras_repo.guardar(True, "porno", "a" * 501)

    def test_un_valor_roto_en_la_base_vuelve_a_la_lista_por_defecto(self):
        with conexion_db() as conexion:
            conexion.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES ('filtro_palabras', '{roto')")

        self.assertIn("porno", filtro_palabras_repo.obtener()["palabras"])


class TestBloqueos(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC 3")

    def test_se_anotan_y_se_listan_del_mas_nuevo_al_mas_viejo_con_el_nombre_de_la_pc(self):
        filtro_palabras_repo.registrar_bloqueo(self.pc, "porno", "Porno gratis - Chrome", segundos_atras=60)
        filtro_palabras_repo.registrar_bloqueo(self.pc, "xxx", "XXX - Chrome")

        bloqueos = filtro_palabras_repo.listar_recientes(10)

        self.assertEqual([(b["palabra"], b["titulo"], b["estacion_nombre"]) for b in bloqueos],
                         [("xxx", "XXX - Chrome", "PC 3"), ("porno", "Porno gratis - Chrome", "PC 3")])
        hace_un_minuto = datetime.fromisoformat(bloqueos[1]["fecha_hora"])
        self.assertAlmostEqual((datetime.now() - hace_un_minuto).total_seconds(), 60, delta=5)

    def test_un_aviso_muy_viejo_o_del_futuro_se_acota(self):
        filtro_palabras_repo.registrar_bloqueo(self.pc, "porno", "t", segundos_atras=10 ** 9)
        filtro_palabras_repo.registrar_bloqueo(self.pc, "xxx", "t", segundos_atras=-500)

        fechas = {b["palabra"]: datetime.fromisoformat(b["fecha_hora"]) for b in filtro_palabras_repo.listar_recientes(5)}
        self.assertGreater(fechas["porno"], datetime.now() - timedelta(days=31))
        self.assertLessEqual(fechas["xxx"], datetime.now() + timedelta(seconds=1))

    def test_titulo_y_palabra_se_guardan_cortados(self):
        filtro_palabras_repo.registrar_bloqueo(self.pc, "p" * 100, "t" * 1000)

        (bloqueo,) = filtro_palabras_repo.listar_recientes(5)
        self.assertEqual(len(bloqueo["palabra"]), filtro_palabras_repo.MAXIMO_LARGO_PALABRA)
        self.assertEqual(len(bloqueo["titulo"]), filtro_palabras_repo.MAXIMO_LARGO_TITULO)

    def test_sin_palabra_no_se_anota(self):
        with self.assertRaises(ValueError):
            filtro_palabras_repo.registrar_bloqueo(self.pc, "  ", "t")
        self.assertEqual(filtro_palabras_repo.listar_recientes(5), [])

    def test_aparecen_en_la_actividad_reciente_del_mostrador(self):
        filtro_palabras_repo.registrar_bloqueo(self.pc, "porno", "Porno gratis - " + "x" * 100)

        (evento,) = [e for e in actividad_repo.actividad_reciente() if e["tipo"] == "FILTRO"]
        texto = pcs_actividad._texto_evento(evento)

        self.assertIn("PC 3: el filtro cerró una página con \"porno\"", texto)
        self.assertIn("…", texto)          # el título va cortado para que entre en un renglón
        self.assertLess(len(texto), 140)


class TestServidorRedFiltro(test_control_pcs._ConServidorRed):
    """GET /filtro, `filtro_version` de GET /estado y POST /filtro_bloqueo, con el servidor real."""

    def test_get_filtro_manda_la_lista_completa_con_su_version(self):
        guardado = filtro_palabras_repo.guardar(True, "porno\nxxx", "No.")

        status, datos = self._get("/filtro")

        self.assertEqual(status, 200)
        self.assertEqual(datos, guardado)

    def test_sin_la_clave_de_los_clientes_responde_403(self):
        conexion = http.client.HTTPConnection("127.0.0.1", self._puerto, timeout=5)
        try:
            conexion.request("GET", "/filtro")
            self.assertEqual(conexion.getresponse().status, 403)
        finally:
            conexion.close()

    def test_estado_trae_la_version_y_cambia_cuando_el_admin_guarda(self):
        pcs_repo.crear_estacion("PC 1")
        _status, antes = self._get("/estado?estacion=PC+1")

        nueva = filtro_palabras_repo.guardar(True, "casino", "No.")["version"]
        _status, despues = self._get("/estado?estacion=PC+1")

        self.assertEqual(antes["filtro_version"], filtro_palabras_repo._version(
            True, list(filtro_palabras_repo.PALABRAS_POR_DEFECTO), filtro_palabras_repo.MENSAJE_POR_DEFECTO))
        self.assertEqual(despues["filtro_version"], nueva)

    def test_estado_de_una_estacion_desconocida_tambien_trae_la_version(self):
        _status, datos = self._get("/estado?estacion=NO+EXISTE")
        self.assertEqual(datos["filtro_version"], filtro_palabras_repo.version_actual())

    def test_si_falla_la_version_el_estado_sigue_contestando_sin_ese_dato(self):
        pcs_repo.crear_estacion("PC 1")
        with mock.patch.object(filtro_palabras_repo, "version_actual", side_effect=OSError("disco")), \
                mock.patch.object(servidor_red, "registrar_error"):
            status, datos = self._get("/estado?estacion=PC+1")

        self.assertEqual(status, 200)
        self.assertNotIn("filtro_version", datos)
        self.assertIn("bloqueada", datos)

    def test_post_filtro_bloqueo_lo_anota(self):
        pcs_repo.crear_estacion("PC 1")

        status, datos = self._post("/filtro_bloqueo", {
            "estacion": "PC 1", "palabra": "porno", "titulo": "Porno - Chrome", "segundos_atras": 3,
        })

        self.assertEqual((status, datos), (200, {"ok": True}))
        (bloqueo,) = filtro_palabras_repo.listar_recientes(5)
        self.assertEqual((bloqueo["estacion_nombre"], bloqueo["palabra"], bloqueo["titulo"]),
                         ("PC 1", "porno", "Porno - Chrome"))

    def test_una_estacion_desconocida_responde_404_y_no_anota_nada(self):
        status, datos = self._post("/filtro_bloqueo", {"estacion": "NO EXISTE", "palabra": "porno", "titulo": "t"})

        self.assertEqual(status, 404)
        self.assertIn("desconocida", datos["error"])   # la PC lo descarta en vez de reintentarlo
        self.assertEqual(filtro_palabras_repo.listar_recientes(5), [])

    def test_un_pedido_sin_palabra_responde_400(self):
        pcs_repo.crear_estacion("PC 1")
        for cuerpo in ({"estacion": "PC 1", "titulo": "t"}, {"estacion": "PC 1", "palabra": " ", "titulo": "t"},
                       {"estacion": "PC 1", "palabra": "porno", "segundos_atras": "ayer"}):
            status, _datos = self._post("/filtro_bloqueo", cuerpo)
            self.assertEqual(status, 400, cuerpo)
        self.assertEqual(filtro_palabras_repo.listar_recientes(5), [])


class _ConDialogo(BaseConBaseTemporal):
    """La pantalla con los cuadros de mensaje reemplazados: uno abierto de verdad dejaría el
    test colgado esperando que alguien lo cierre."""

    def setUp(self):
        super().setUp()
        self.errores, self.infos = [], []
        self.respuesta_confirmar = True
        self.preguntas = []
        parches = [
            mock.patch("ui.utils.mostrar_error", side_effect=lambda *a, **k: self.errores.append(a[2])),
            mock.patch.object(pcs_filtro_dialogo, "mostrar_info", side_effect=lambda *a, **k: self.infos.append(a[2])),
            mock.patch.object(pcs_filtro_dialogo, "confirmar", side_effect=self._confirmar),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)

    def _confirmar(self, *args, **kwargs):
        self.preguntas.append(args[2])
        return self.respuesta_confirmar

    def _dialogo(self):
        dialogo = pcs_filtro_dialogo.DialogoFiltroPalabras()
        self.addCleanup(dialogo.deleteLater)
        return dialogo


class TestPantallaDelFiltro(_ConDialogo):
    def test_muestra_lo_guardado_y_los_ultimos_bloqueos(self):
        filtro_palabras_repo.guardar(False, "porno\nxxx", "No se puede.")
        pc = pcs_repo.crear_estacion("PC 7")
        filtro_palabras_repo.registrar_bloqueo(pc, "porno", "Porno - Chrome")

        dialogo = self._dialogo()

        self.assertFalse(dialogo.casilla_activo.isChecked())
        self.assertEqual(dialogo.campo_palabras.toPlainText(), "porno\nxxx")
        self.assertEqual(dialogo.campo_mensaje.toPlainText(), "No se puede.")
        self.assertEqual(dialogo.cuenta_palabras.text(), "2 palabras")
        self.assertEqual(dialogo.tabla_bloqueos.rowCount(), 1)
        self.assertEqual([dialogo.tabla_bloqueos.item(0, c).text() for c in (1, 2, 3)], ["PC 7", "porno", "Porno - Chrome"])

    def test_guardar_lo_deja_en_la_base_y_muestra_como_quedo(self):
        dialogo = self._dialogo()
        dialogo.casilla_activo.setChecked(True)
        dialogo.campo_palabras.setPlainText("Casino\n\ncasino\nApuestas")
        dialogo.campo_mensaje.setPlainText("Acá no.")

        dialogo._guardar()

        self.assertEqual(filtro_palabras_repo.obtener()["palabras"], ["casino", "apuestas"])
        self.assertEqual(dialogo.campo_palabras.toPlainText(), "casino\napuestas")
        self.assertEqual(len(self.infos), 1)
        self.assertIn("2 palabras", self.infos[0])
        self.assertEqual(self.errores, [])

    def test_una_palabra_que_no_sirve_muestra_el_motivo_y_no_guarda(self):
        antes = filtro_palabras_repo.obtener()
        dialogo = self._dialogo()
        dialogo.campo_palabras.setPlainText("porno\nx")

        dialogo._guardar()

        self.assertEqual(filtro_palabras_repo.obtener(), antes)
        self.assertEqual(len(self.errores), 1)
        self.assertIn("demasiado corta", self.errores[0])

    def test_cerrar_con_cambios_sin_guardar_pregunta_y_si_se_dice_que_no_sigue_abierta(self):
        dialogo = self._dialogo()
        dialogo.campo_palabras.appendPlainText("casino")
        self.respuesta_confirmar = False

        with mock.patch.object(pcs_filtro_dialogo.QDialog, "reject") as cerrar:
            dialogo.reject()

        self.assertEqual(len(self.preguntas), 1)
        cerrar.assert_not_called()

    def test_cerrar_sin_cambios_no_pregunta(self):
        dialogo = self._dialogo()

        with mock.patch.object(pcs_filtro_dialogo.QDialog, "reject") as cerrar:
            dialogo.reject()

        self.assertEqual(self.preguntas, [])
        cerrar.assert_called_once()


class TestBotonEnGestionarEstaciones(_ConDialogo):
    def test_gestionar_estaciones_tiene_el_boton_y_abre_la_pantalla_del_filtro(self):
        gestion = pcs_gestion_dialogos.DialogoGestionEstaciones({"rol": dominio.ROL_ADMIN})
        self.addCleanup(gestion.deleteLater)
        botones = [b for b in gestion.findChildren(QPushButton) if b.text() == "Filtro de palabras de las PCs..."]
        self.assertEqual(len(botones), 1)

        with mock.patch.object(pcs_gestion_dialogos.DialogoFiltroPalabras, "exec") as abrir:
            botones[0].click()

        abrir.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
