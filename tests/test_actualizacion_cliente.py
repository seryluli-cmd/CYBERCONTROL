"""
tests/test_actualizacion_cliente.py
=====================================
Actualizar el Cliente PC de las PCs desde acá (pedido del dueño, 2026-10-18):

- `actualizacion_cliente_repo`: firmar y guardar una versión, a qué PCs va (las que marca el
  Admin), lo que cuenta cada PC y cómo está cada una (`situacion`, rehecho el 2026-10-19).
- `servidor_red.py`: `cliente_version` y el reporte en `GET /estado`, `GET /cliente_pc` y
  `GET /cliente_pc/exe` (con el servidor real).
- La pantalla "Actualizar el Cliente PC de las PCs..." y su botón en Gestionar Estaciones.

Con una clave de firma de PRUEBA generada en cada corrida: la del dueño vive fuera de los repos
y ningún test la toca.

Se ejecutan con:

    python -m unittest discover tests
"""

import base64
import hashlib
import http.client
import json
import os
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from cryptography.hazmat.primitives import serialization  # noqa: E402
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey, Ed25519PublicKey  # noqa: E402
from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from control_pcs.repositories import actualizacion_cliente_repo as repo  # noqa: E402
from control_pcs.repositories import pcs_repo  # noqa: E402
from control_pcs.ui import pcs_actualizacion_dialogo, pcs_gestion_dialogos  # noqa: E402

_app = QApplication.instance() or QApplication([])

CLAVE_DE_PRUEBA = Ed25519PrivateKey.generate()
PUBLICA_DE_PRUEBA = base64.b64encode(CLAVE_DE_PRUEBA.public_key().public_bytes(
    serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def exe_de_cliente(texto=b"version de prueba") -> bytes:
    """Lo que tiene un PCcliente.exe para el repo: empieza como un exe y, al final, la lista de
    PyInstaller con el programa principal (cliente_pc)."""
    return b"MZ" + texto * 200 + b"...pyiboot01_bootstrap...cliente_pc...MEI"


class _ConClaveDePrueba(BaseConBaseTemporal):
    """La clave privada de PRUEBA en un archivo temporal y su pública como la que conocen las PCs."""

    def setUp(self):
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta_clave = Path(carpeta.name) / "clave.pem"
        self.ruta_clave.write_bytes(CLAVE_DE_PRUEBA.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        for parche in (mock.patch.object(repo, "ruta_clave_privada", lambda: self.ruta_clave),
                       mock.patch.object(repo, "CLAVE_PUBLICA_FIRMA", PUBLICA_DE_PRUEBA)):
            parche.start()
            self.addCleanup(parche.stop)
        repo._ultimo.update(clave=None, paquete=None, exe=None)
        repo.olvidar_reportes()
        self.addCleanup(repo.olvidar_reportes)

    def verificar(self, paquete) -> dict:
        """Lo que hace la PC con lo que recibe: comprobar la firma con la clave pública."""
        Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLICA_DE_PRUEBA)).verify(
            base64.b64decode(paquete["firma"]), paquete["manifiesto"].encode("utf-8"))
        return json.loads(paquete["manifiesto"])


class TestPublicar(_ConClaveDePrueba):
    def test_firma_y_guarda_la_version_en_data(self):
        datos = exe_de_cliente()

        manifiesto = repo.publicar(datos, ahora=datetime(2026, 10, 18, 19, 30, 5))

        self.assertEqual(manifiesto, {"programa": "PCcliente", "version": 20261018193005,
                                      "sha256": hashlib.sha256(datos).hexdigest(), "tamano": len(datos),
                                      "creado": "2026-10-18T19:30:05"})
        paquete = repo.paquete()
        self.assertEqual(self.verificar(paquete), manifiesto)          # la firma la acepta la clave pública
        self.assertEqual(repo.datos_exe(), datos)
        carpeta = os.path.join(database.DATA_DIR, "cliente_pc")
        self.assertEqual(sorted(os.listdir(carpeta)), ["PCcliente.exe", "version.json"])   # sin temporales

    def test_la_version_siempre_crece_aunque_se_cargue_dos_veces_en_el_mismo_segundo(self):
        ahora = datetime(2026, 10, 18, 19, 30, 5)
        primera = repo.publicar(exe_de_cliente(b"uno"), ahora=ahora)["version"]
        segunda = repo.publicar(exe_de_cliente(b"dos"), ahora=ahora)["version"]

        self.assertEqual(segunda, primera + 1)
        self.assertEqual(repo.version_publicada(), segunda)
        self.assertEqual(repo.datos_exe(), exe_de_cliente(b"dos"))

    def test_una_version_nueva_no_va_a_ninguna_hasta_que_se_marquen(self):
        a = pcs_repo.crear_estacion("PC1")
        repo.guardar_seleccion([a])

        repo.publicar(exe_de_cliente())

        self.assertEqual(repo.obtener_seleccion(), set())
        self.assertIsNone(repo.version_para_estacion(a))

    def test_rechaza_lo_que_no_es_el_cliente_pc(self):
        for datos, texto in ((b"", "no es un programa"), (b"PK zip", "no es un programa"),
                             (b"MZ" + b"CyberBios" * 1000, "no es el Cliente PC")):
            with self.assertRaises(ValueError, msg=datos[:10]) as error:
                repo.publicar(datos)
            self.assertIn(texto, str(error.exception))
        self.assertIsNone(repo.paquete())

    def test_rechaza_uno_desmedido(self):
        with mock.patch.object(repo, "TAMANO_MAXIMO_EXE", 100):
            with self.assertRaises(ValueError):
                repo.publicar(exe_de_cliente())

    def test_sin_la_clave_de_firma_dice_donde_tiene_que_estar(self):
        self.ruta_clave.unlink()

        with self.assertRaises(ValueError) as error:
            repo.publicar(exe_de_cliente())

        self.assertIn(str(self.ruta_clave), str(error.exception))
        self.assertIsNone(repo.paquete())

    def test_con_una_clave_que_no_es_la_que_conocen_las_pcs_no_firma(self):
        otra = Ed25519PrivateKey.generate()
        self.ruta_clave.write_bytes(otra.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))

        with self.assertRaises(ValueError) as error:
            repo.publicar(exe_de_cliente())

        self.assertIn("no es la que conocen las PCs", str(error.exception))

    def test_un_version_json_roto_es_como_no_tener_version(self):
        repo.publicar(exe_de_cliente())
        with open(os.path.join(database.DATA_DIR, "cliente_pc", "version.json"), "w", encoding="utf-8") as archivo:
            archivo.write("{roto")

        self.assertIsNone(repo.paquete())
        self.assertIsNone(repo.version_publicada())


class TestClaveDeLasPcs(unittest.TestCase):
    def test_es_la_misma_que_trae_el_cliente_pc(self):
        ruta = Path(__file__).resolve().parents[2] / "CLIENTE PC" / "actualizacion.py"
        if not ruta.exists():
            self.skipTest("No está la carpeta CLIENTE PC al lado")
        self.assertIn(f'CLAVE_PUBLICA_FIRMA = "{repo.CLAVE_PUBLICA_FIRMA}"', ruta.read_text(encoding="utf-8"))

    def test_es_una_clave_publica_ed25519(self):
        Ed25519PublicKey.from_public_bytes(base64.b64decode(repo.CLAVE_PUBLICA_FIRMA))


class TestAlcanceYReporte(_ConClaveDePrueba):
    def setUp(self):
        super().setUp()
        self.pc1, self.pc2 = pcs_repo.crear_estacion("PC1"), pcs_repo.crear_estacion("PC2")

    def test_sin_version_cargada_no_le_toca_nada_a_nadie(self):
        repo.guardar_seleccion([self.pc1])
        self.assertIsNone(repo.version_para_estacion(self.pc1))

    def test_le_toca_solo_a_las_marcadas(self):
        version = repo.publicar(exe_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1])
        self.assertEqual((repo.version_para_estacion(self.pc1), repo.version_para_estacion(self.pc2)), (version, None))

        repo.guardar_seleccion([self.pc1, self.pc2])
        self.assertEqual((repo.version_para_estacion(self.pc1), repo.version_para_estacion(self.pc2)), (version, version))

        repo.guardar_seleccion([])
        self.assertIsNone(repo.version_para_estacion(self.pc1))

    def test_lo_que_guardo_la_pantalla_vieja_cuenta_como_marcadas_las_de_prueba(self):
        with database.conexion_db() as conexion:
            conexion.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
                             ("actualizacion_cliente_alcance", json.dumps({"para_todas": True, "prueba": [self.pc2]})))
        self.assertEqual(repo.obtener_seleccion(), {self.pc2})

    def estacion(self, estacion_id):
        return pcs_repo.obtener_estacion(estacion_id)

    def test_guarda_lo_que_cuenta_la_pc(self):
        repo.registrar_reporte(self.pc1, {"estacion": "PC1", "version": "20261018193005",
                                          "carpeta": "C:\\Program Files\\AAAAA26\\cliente",
                                          "act": "descargada", "act_detalle": "Se pone en el próximo reinicio.",
                                          "act_version": "20261019120000"})

        fila = self.estacion(self.pc1)
        self.assertEqual((fila["version_cliente"], fila["carpeta_cliente"], fila["estado_actualizacion"],
                          fila["detalle_actualizacion"], fila["version_bajada"]),
                         (20261018193005, "C:\\Program Files\\AAAAA26\\cliente", "descargada",
                          "Se pone en el próximo reinicio.", 20261019120000))

    def test_un_cliente_pc_sin_act_version_deja_la_bajada_sin_dato(self):
        repo.registrar_reporte(self.pc1, {"version": "1", "carpeta": "C:\\c", "act": "descargada", "act_detalle": ""})
        self.assertIsNone(self.estacion(self.pc1)["version_bajada"])

    def test_un_cliente_pc_viejo_no_manda_nada_y_no_se_toca_nada(self):
        repo.registrar_reporte(self.pc1, {"estacion": "PC1"})
        self.assertIsNone(self.estacion(self.pc1)["carpeta_cliente"])

    def test_uno_instalado_a_mano_cuenta_sin_version(self):
        repo.registrar_reporte(self.pc1, {"version": "", "carpeta": "C:\\c", "act": "", "act_detalle": ""})
        fila = self.estacion(self.pc1)
        self.assertEqual((fila["version_cliente"], fila["carpeta_cliente"], fila["estado_actualizacion"]), (None, "C:\\c", ""))

    def test_un_estado_desconocido_cuenta_como_nada_pendiente_y_los_textos_tienen_tope(self):
        repo.registrar_reporte(self.pc1, {"version": "x", "carpeta": "C" * 1000, "act": "hackeado",
                                          "act_detalle": "d" * 1000})
        fila = self.estacion(self.pc1)
        self.assertEqual((fila["version_cliente"], len(fila["carpeta_cliente"]), fila["estado_actualizacion"],
                          fila["detalle_actualizacion"]), (None, 260, "", ""))
        repo.registrar_reporte(self.pc2, {"version": "1", "act": "error", "act_detalle": "d" * 1000})
        self.assertEqual(len(self.estacion(self.pc2)["detalle_actualizacion"]), 300)

    def test_solo_escribe_en_la_base_si_cambio_algo(self):
        reporte = {"version": "5", "carpeta": "C:\\c", "act": "", "act_detalle": ""}
        repo.registrar_reporte(self.pc1, reporte)
        with database.conexion_db() as conexion:     # alguien lo cambia por fuera
            conexion.execute("UPDATE estaciones SET carpeta_cliente = 'tocada' WHERE id = ?", (self.pc1,))

        repo.registrar_reporte(self.pc1, reporte)                       # lo mismo: no escribe
        self.assertEqual(self.estacion(self.pc1)["carpeta_cliente"], "tocada")
        repo.registrar_reporte(self.pc1, {**reporte, "act": "bajando"})   # algo distinto: escribe
        self.assertEqual(self.estacion(self.pc1)["carpeta_cliente"], "C:\\c")

    def test_estado_de_las_pcs(self):
        version = repo.publicar(exe_de_cliente())["version"]
        pc3 = pcs_repo.crear_estacion("PC3")
        repo.guardar_seleccion([self.pc1, self.pc2])
        for estacion_id, estado in ((self.pc1, "descargada"), (self.pc2, "bajando"), (pc3, "")):
            repo.registrar_reporte(estacion_id, {"version": "1", "carpeta": "C:\\c", "act": estado, "act_detalle": "",
                                                 "act_version": str(version) if estado else ""})
        ahora = datetime(2026, 10, 19, 12, 0, 0)
        with database.conexion_db() as conexion:     # PC2 tiene a un cliente usándola
            conexion.execute(
                "INSERT INTO sesiones_pc (estacion_id, fecha_inicio, fecha_fin_prevista, estado) VALUES (?, ?, ?, ?)",
                (self.pc2, "2026-10-18T19:00:00", "2099-01-01T00:00:00", dominio.SESION_ACTIVA))
            for estacion_id, hace in ((self.pc1, 5), (self.pc2, 31)):
                conexion.execute("UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                                 ((ahora - timedelta(seconds=hace)).isoformat(timespec="seconds"), estacion_id))

        pcs = {pc["nombre"]: pc for pc in repo.estado_de_las_pcs(ahora)}
        nombres = ("PC1", "PC2", "PC3")
        self.assertEqual([pcs[n]["ocupada"] for n in nombres], [False, True, False])
        self.assertEqual([pcs[n]["seleccionada"] for n in nombres], [True, True, False])
        self.assertEqual([pcs[n]["conectada"] for n in nombres], [True, False, False])   # 30 s, como SIN CLIENTE
        self.assertEqual([pcs[n]["le_toca"] for n in nombres], [version, version, None])
        self.assertEqual(pcs["PC1"]["version_bajada"], version)
        self.assertEqual([repo.situacion(pcs[n]) for n in nombres], [repo.LISTA, repo.APAGADA, repo.NO_SELECCIONADA])

    def test_texto_de_una_version(self):
        self.assertEqual(repo.texto_version(20261018193005), "18/10/2026 19:30")
        self.assertEqual(repo.texto_version(7), "7")
        self.assertEqual(repo.texto_version(None), "")


class TestSituacion(unittest.TestCase):
    """Cómo está cada PC con la versión cargada: lo que dice la pantalla, en palabras."""

    BASE = {"carpeta": "C:\\c", "ultima_conexion": "2026-10-19T12:00:00", "conectada": True,
            "le_toca": 5, "version": 4, "estado": "", "detalle": "", "version_bajada": None, "seleccionada": True}

    def situacion(self, **cambios):
        return repo.situacion({**self.BASE, **cambios})

    def test_cada_caso(self):
        self.assertEqual(self.situacion(), repo.ESPERANDO)
        self.assertEqual(self.situacion(estado="bajando", version_bajada=5), repo.COPIANDO)
        self.assertEqual(self.situacion(estado="descargada", version_bajada=5), repo.LISTA)
        self.assertEqual(self.situacion(estado="descargada"), repo.LISTA)              # un Cliente PC sin act_version
        self.assertEqual(self.situacion(version=5), repo.FUNCIONANDO)
        self.assertEqual(self.situacion(estado="error", detalle="x"), repo.ERROR)
        self.assertEqual(self.situacion(estado="fallo", detalle="x"), repo.FALLO)
        self.assertEqual(self.situacion(conectada=False), repo.APAGADA)
        self.assertEqual(self.situacion(le_toca=None, seleccionada=False), repo.NO_SELECCIONADA)
        self.assertEqual(self.situacion(carpeta=""), repo.INSTALACION_VIEJA)
        self.assertEqual(self.situacion(carpeta="", ultima_conexion=None, conectada=False), repo.NUNCA_CONECTADA)

    def test_una_vieja_copiada_no_cuenta_como_lista_con_la_nueva(self):
        self.assertEqual(self.situacion(estado="descargada", version_bajada=3), repo.ESPERANDO)

    def test_lo_que_ya_paso_vale_aunque_este_apagada_y_lo_que_esta_pasando_no(self):
        apagada = {"conectada": False}
        self.assertEqual(self.situacion(estado="descargada", version_bajada=5, **apagada), repo.LISTA)
        self.assertEqual(self.situacion(version=5, **apagada), repo.FUNCIONANDO)
        self.assertEqual(self.situacion(estado="fallo", **apagada), repo.FALLO)
        self.assertEqual(self.situacion(estado="bajando", **apagada), repo.APAGADA)
        self.assertEqual(self.situacion(estado="error", **apagada), repo.APAGADA)


class TestServidorRedActualizacion(test_control_pcs._ConServidorRed):
    """`cliente_version` y el reporte en GET /estado, GET /cliente_pc y GET /cliente_pc/exe."""

    def setUp(self):
        super().setUp()
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        ruta = Path(carpeta.name) / "clave.pem"
        ruta.write_bytes(CLAVE_DE_PRUEBA.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
        for parche in (mock.patch.object(repo, "ruta_clave_privada", lambda: ruta),
                       mock.patch.object(repo, "CLAVE_PUBLICA_FIRMA", PUBLICA_DE_PRUEBA)):
            parche.start()
            self.addCleanup(parche.stop)
        repo._ultimo.update(clave=None, paquete=None, exe=None)
        repo.olvidar_reportes()
        self.addCleanup(repo.olvidar_reportes)
        self.pc1 = pcs_repo.crear_estacion("PC1")

    def _get_crudo(self, ruta, con_clave=True):
        conexion = http.client.HTTPConnection("127.0.0.1", self._puerto, timeout=5)
        try:
            cabeceras = {"Authorization": "Bearer " + self._clave} if con_clave else {}
            conexion.request("GET", ruta, headers=cabeceras)
            respuesta = conexion.getresponse()
            return respuesta.status, respuesta.getheader("Content-Type"), respuesta.read()
        finally:
            conexion.close()

    def test_sin_version_cargada_cliente_version_es_None_y_los_pedidos_dan_404(self):
        status, datos = self._get("/estado?estacion=PC1")

        self.assertEqual((status, datos["cliente_version"]), (200, None))
        self.assertEqual(self._get_crudo("/cliente_pc")[0], 404)
        self.assertEqual(self._get_crudo("/cliente_pc/exe")[0], 404)

    def test_la_pc_marcada_recibe_su_version_y_puede_bajarla_entera(self):
        datos = exe_de_cliente()
        version = repo.publicar(datos)["version"]
        repo.guardar_seleccion([self.pc1])

        status, estado = self._get("/estado?estacion=PC1")
        self.assertEqual((status, estado["cliente_version"]), (200, version))

        status, _tipo, cuerpo = self._get_crudo("/cliente_pc")
        paquete = json.loads(cuerpo)
        self.assertEqual((status, paquete["version"]), (200, version))
        manifiesto = json.loads(paquete["manifiesto"])
        Ed25519PublicKey.from_public_bytes(base64.b64decode(PUBLICA_DE_PRUEBA)).verify(
            base64.b64decode(paquete["firma"]), paquete["manifiesto"].encode("utf-8"))

        status, tipo, exe = self._get_crudo("/cliente_pc/exe")
        self.assertEqual((status, tipo), (200, "application/octet-stream"))
        self.assertEqual(hashlib.sha256(exe).hexdigest(), manifiesto["sha256"])

    def test_una_pc_sin_marcar_no_recibe_version(self):
        repo.publicar(exe_de_cliente())

        self.assertIsNone(self._get("/estado?estacion=PC1")[1]["cliente_version"])

    def test_sin_la_clave_de_los_clientes_no_regala_el_exe(self):
        repo.publicar(exe_de_cliente())

        self.assertEqual(self._get_crudo("/cliente_pc", con_clave=False), (403, None, b""))
        self.assertEqual(self._get_crudo("/cliente_pc/exe", con_clave=False), (403, None, b""))

    def test_la_consulta_de_estado_guarda_lo_que_cuenta_la_pc(self):
        self._get("/estado?estacion=PC1&version=20261018193005&carpeta=C%3A%5Ccliente&act=bajando"
                  "&act_detalle=Bajando&act_version=20261019120000")

        fila = pcs_repo.obtener_estacion(self.pc1)
        self.assertEqual((fila["version_cliente"], fila["carpeta_cliente"], fila["estado_actualizacion"],
                          fila["detalle_actualizacion"], fila["version_bajada"]),
                         (20261018193005, "C:\\cliente", "bajando", "Bajando", 20261019120000))

    def test_una_instalada_a_mano_manda_la_version_vacia_y_cuenta_igual(self):
        self._get("/estado?estacion=PC1&version=&carpeta=C%3A%5Ccliente&act=&act_detalle=")

        self.assertEqual(pcs_repo.obtener_estacion(self.pc1)["carpeta_cliente"], "C:\\cliente")

    def test_si_falla_leer_la_version_el_estado_sale_igual_sin_ella(self):
        with mock.patch.object(repo, "version_para_estacion", side_effect=RuntimeError("disco")), \
                mock.patch.object(repo, "registrar_reporte", side_effect=RuntimeError("disco")), \
                mock.patch("servidor_red.registrar_error"):
            status, datos = self._get("/estado?estacion=PC1&version=1")

        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertNotIn("cliente_version", datos)


class TestDialogoActualizarCliente(_ConClaveDePrueba):
    def setUp(self):
        super().setUp()
        self.infos = []
        self.respuesta_confirmar = True
        self.ruta_elegida = ""
        parches = [
            mock.patch("ui.utils.mostrar_error", side_effect=lambda *a, **k: self.infos.append(("error", a[2]))),
            mock.patch.object(pcs_actualizacion_dialogo, "mostrar_info", side_effect=lambda *a, **k: self.infos.append(a[2])),
            mock.patch.object(pcs_actualizacion_dialogo, "confirmar", side_effect=lambda *a, **k: self.respuesta_confirmar),
            mock.patch.object(pcs_actualizacion_dialogo.QFileDialog, "getOpenFileName",
                              side_effect=lambda *a, **k: (self.ruta_elegida, "")),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)
        self.pc1, self.pc2 = pcs_repo.crear_estacion("PC1"), pcs_repo.crear_estacion("PC2")
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        self.ruta_elegida = os.path.join(carpeta.name, "PCcliente.exe")
        with open(self.ruta_elegida, "wb") as archivo:
            archivo.write(exe_de_cliente())

    def dialogo(self):
        dialogo = pcs_actualizacion_dialogo.DialogoActualizarCliente()
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def casillas(self, d):
        return [d.tabla.item(f, 0).checkState() == Qt.CheckState.Checked for f in range(d.tabla.rowCount())]

    def test_sin_version_lo_dice_y_lista_las_pcs(self):
        d = self.dialogo()

        self.assertEqual(d.etiqueta_version.text(), "Todavía no cargaste ninguna versión.")
        self.assertEqual([d.tabla.item(f, 1).text() for f in range(d.tabla.rowCount())], ["PC1", "PC2"])
        self.assertIn("Primero cargá la versión nueva", d.etiqueta_resumen.text())

    def test_cargar_una_version_la_firma_y_deja_todas_sin_marcar(self):
        repo.guardar_seleccion([self.pc1])
        d = self.dialogo()
        self.assertEqual(self.casillas(d), [True, False])

        d._cargar_version()

        self.assertIsNotNone(repo.paquete())
        self.assertIn("Versión cargada:", d.etiqueta_version.text())
        self.assertIn("Ahora marcá las PCs", self.infos[-1])
        self.assertEqual(self.casillas(d), [False, False])
        self.assertEqual(repo.obtener_seleccion(), set())

    def test_si_no_confirma_no_carga_nada(self):
        self.respuesta_confirmar = False
        self.dialogo()._cargar_version()
        self.assertIsNone(repo.paquete())

    def test_un_exe_que_no_es_el_cliente_muestra_el_error_y_no_carga_nada(self):
        with open(self.ruta_elegida, "wb") as archivo:
            archivo.write(b"MZ" + b"CyberBios" * 100)

        self.dialogo()._cargar_version()

        self.assertIsNone(repo.paquete())
        self.assertIn("no es el Cliente PC", self.infos[-1][1])

    def test_marcar_y_actualizar_las_seleccionadas(self):
        repo.publicar(exe_de_cliente())
        d = self.dialogo()
        d.tabla.item(1, 0).setCheckState(Qt.CheckState.Checked)

        d._actualizar_seleccionadas()

        self.assertEqual(repo.obtener_seleccion(), {self.pc2})
        self.assertIn("Listo: va a 1 PC.", self.infos[-1])
        self.assertEqual(d.tabla.item(1, 2).text(), "Nunca se conectó a este CYBERCONTROL (¿apagada o con otro nombre?)")
        self.assertEqual(d.tabla.item(0, 2).text(), "Nunca se conectó a este CYBERCONTROL (¿apagada o con otro nombre?)")

    def test_marcar_y_desmarcar_todas(self):
        repo.publicar(exe_de_cliente())
        d = self.dialogo()
        d._marcar_todas(True)
        self.assertEqual(self.casillas(d), [True, True])
        d._actualizar_seleccionadas()
        self.assertEqual(repo.obtener_seleccion(), {self.pc1, self.pc2})

        d._marcar_todas(False)
        d._actualizar_seleccionadas()
        self.assertEqual(repo.obtener_seleccion(), set())
        self.assertIn("no va a ninguna PC", self.infos[-1])

    def test_sin_version_cargada_no_deja_actualizar(self):
        d = self.dialogo()
        d._marcar_todas(True)

        d._actualizar_seleccionadas()

        self.assertEqual(repo.obtener_seleccion(), set())
        self.assertIn("Primero cargá la versión nueva", self.infos[-1])

    def test_desmarcar_una_que_ya_la_copio_pregunta_antes(self):
        version = repo.publicar(exe_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1])
        repo.registrar_reporte(self.pc1, {"version": "1", "carpeta": "C:\\c", "act": "descargada",
                                          "act_detalle": "", "act_version": str(version)})
        d = self.dialogo()
        self.assertEqual(d.tabla.item(0, 2).text(), "Actualizada con éxito · se aplica en el próximo reinicio")
        d._marcar_todas(False)
        self.respuesta_confirmar = False

        d._actualizar_seleccionadas()
        self.assertEqual(repo.obtener_seleccion(), {self.pc1})

        self.respuesta_confirmar = True
        d._actualizar_seleccionadas()
        self.assertEqual(repo.obtener_seleccion(), set())

    def test_el_refresco_solo_cambia_los_estados_y_respeta_lo_tildado(self):
        version = repo.publicar(exe_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1])
        d = self.dialogo()
        d.tabla.item(1, 0).setCheckState(Qt.CheckState.Checked)       # tildada y sin guardar
        repo.registrar_reporte(self.pc1, {"version": str(version), "carpeta": "C:\\c", "act": "", "act_detalle": ""})

        d._refrescar_solo()

        self.assertEqual(self.casillas(d), [True, True])
        self.assertEqual(d.tabla.item(0, 2).text(), "Funcionando con la versión nueva")
        self.assertEqual(d.etiqueta_resumen.text(), "✔ La PC seleccionada está actualizada.")

    def test_el_refresco_no_muestra_carteles_si_algo_falla(self):
        d = self.dialogo()
        with mock.patch.object(repo, "estado_de_las_pcs", side_effect=RuntimeError("disco")), \
                mock.patch.object(pcs_actualizacion_dialogo, "registrar_error") as registrar:
            d._refrescar_solo()
        registrar.assert_called_once()
        self.assertEqual(self.infos, [])

    def test_el_estado_de_cada_pc_en_palabras(self):
        texto = pcs_actualizacion_dialogo.texto_del_estado
        base = {"estado": "", "detalle": "", "carpeta": "C:\\c", "le_toca": 5, "version": 4, "version_bajada": None,
                "ultima_conexion": "2026-10-19T12:00:00", "conectada": True, "seleccionada": True}
        self.assertEqual(texto(base), "Esperando")
        self.assertEqual(texto({**base, "version": 5}), "Funcionando con la versión nueva")
        self.assertEqual(texto({**base, "estado": "bajando"}), "Copiando…")
        self.assertEqual(texto({**base, "estado": "descargada"}), "Actualizada con éxito · se aplica en el próximo reinicio")
        self.assertEqual(texto({**base, "estado": "error", "detalle": "No se pudo conectar con el Servidor."}),
                         "Error: No se pudo conectar con el Servidor · reintenta sola")
        self.assertEqual(texto({**base, "conectada": False}), "Apagada / sin conexión · se actualiza sola al prenderla")
        self.assertEqual(texto({**base, "le_toca": None, "seleccionada": False}), "No seleccionada")
        self.assertEqual(texto({**base, "carpeta": "", "ultima_conexion": None}),
                         "Nunca se conectó a este CYBERCONTROL (¿apagada o con otro nombre?)")
        self.assertEqual(texto({**base, "carpeta": ""}),
                         "Instalación vieja: hay que reinstalarla con el pendrive (preparar_pc.bat)")
        self.assertEqual(texto({**base, "estado": "fallo", "detalle": "La versión 20261018005701 se cerró"}),
                         "Falló al arrancar: La versión 18/10/2026 00:57 se cerró")
        version = pcs_actualizacion_dialogo.texto_de_la_version
        self.assertEqual(version({"version": 20261018193005, "carpeta": "C:\\c"}), "18/10/2026 19:30")
        self.assertEqual(version({"version": None, "carpeta": "C:\\c"}), "a mano (sin versión)")
        self.assertEqual(version({"version": None, "carpeta": ""}), "")

    def test_el_resumen_dice_cuantas_estan_listas_y_que_les_falta(self):
        resumen = pcs_actualizacion_dialogo.texto_del_resumen
        base = {"estado": "", "detalle": "", "carpeta": "C:\\c", "le_toca": 5, "version": 4, "version_bajada": None,
                "ultima_conexion": "2026-10-19T12:00:00", "conectada": True, "seleccionada": True}
        pcs = [{**base, "nombre": "PC1", "version": 5},
               {**base, "nombre": "PC2", "estado": "descargada"},
               {**base, "nombre": "PC3", "estado": "bajando"},
               {**base, "nombre": "PC4", "conectada": False},
               {**base, "nombre": "PC5", "le_toca": None, "seleccionada": False}]
        self.assertEqual(resumen(pcs, True), "2 de 4 listas · faltan: PC3 (copiando), PC4 (apagada)")
        self.assertEqual(resumen(pcs[:2], True), "✔ Las 2 PCs seleccionadas están actualizadas.")
        self.assertIn("Marcá las PCs", resumen(pcs[4:], True))
        self.assertIn("Primero cargá", resumen(pcs, False))

    def test_cerrar_con_casillas_cambiadas_pregunta(self):
        d = self.dialogo()
        d._marcar_todas(True)
        self.respuesta_confirmar = False

        d.reject()

        self.assertEqual(d.result(), 0)
        self.assertTrue(d._timer.isActive())
        self.assertEqual(repo.obtener_seleccion(), set())

        self.respuesta_confirmar = True
        d.reject()
        self.assertFalse(d._timer.isActive())

    def test_gestionar_estaciones_tiene_el_boton(self):
        gestion = pcs_gestion_dialogos.DialogoGestionEstaciones({"rol": dominio.ROL_ADMIN})
        self.addCleanup(gestion.deleteLater)
        botones = [b for b in gestion.findChildren(QPushButton) if b.text() == "Actualizar el Cliente PC de las PCs..."]
        self.assertEqual(len(botones), 1)

        with mock.patch.object(pcs_gestion_dialogos.DialogoActualizarCliente, "exec") as abrir:
            botones[0].click()

        abrir.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
