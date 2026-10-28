"""
tests/test_actualizacion_cliente.py
=====================================
Actualizar el Cliente PC de las PCs desde acá (pedido del dueño, 2026-10-18):

- `actualizacion_cliente_repo`: firmar y guardar una versión, a qué PCs va (las que marca el
  Admin), lo que cuenta cada PC y cómo está cada una (`situacion`, rehecho el 2026-10-19).
- `servidor_red.py`: `cliente_version` y el reporte en `GET /estado`, `GET /cliente_pc` y
  `GET /cliente_pc/exe` (con el servidor real).
- La pantalla "Actualizar el Cliente PC de las PCs..." y su botón en Gestionar Estaciones.
- El número de versión (V1, V1.1...; 2026-10-19): leerlo del exe, lo que manda cada PC y cómo se
  ve en la pantalla.

Con una clave de firma de PRUEBA generada en cada corrida: la del dueño vive fuera de los repos
y ningún test la toca.

Se ejecutan con:

    python -m unittest discover tests
"""

import base64
import hashlib
import http.client
import importlib.util
import io
import json
import os
import shutil
import struct
import tempfile
import unittest
import zipfile
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


def datos_de_version(entero: int, decimo: int) -> bytes:
    """Lo que graba PyInstaller en el exe con el número de versión (lo que Windows muestra en
    Propiedades -> Detalles): el principio de la estructura VS_VERSION_INFO."""
    return (struct.pack("<HHH", 0, 52, 0) + "VS_VERSION_INFO\0".encode("utf-16-le") + b"\0\0"
            + struct.pack("<IIIIII", 0xFEEF04BD, 0x00010000, (entero << 16) | decimo, 0, (entero << 16) | decimo, 0))


def exe_de_cliente(texto=b"version de prueba", v=None) -> bytes:
    """Lo que tiene un PCcliente.exe para el repo: empieza como un exe y, al final, la lista de
    PyInstaller con el programa principal (cliente_pc). Con `v` ("1.2"), trae ese número de versión."""
    adelante = b""
    if v:
        entero, _punto, decimo = v.partition(".")
        adelante = b"\0" * 300 + datos_de_version(int(entero), int(decimo or 0))
    return b"MZ" + adelante + texto * 200 + b"...pyiboot01_bootstrap...cliente_pc...MEI"


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


def zip_de_cliente(v="2", archivos: dict = None) -> bytes:
    """El .zip de una versión en carpeta (lo que arma CLIENTE PC/armar_paquete.py): PCcliente.exe
    arriba de todo y su `_internal/`. `archivos` pisa o agrega lo que se quiera ({ruta: bytes},
    None para sacar uno)."""
    contenido = {"PCcliente.exe": exe_de_cliente(v=v), "_internal/python312.dll": b"dll" * 500,
                 "_internal/sub/modulo.pyd": b"pyd" * 50, "_internal/vacio.txt": b""}
    contenido.update(archivos or {})
    memoria = io.BytesIO()
    with zipfile.ZipFile(memoria, "w", zipfile.ZIP_DEFLATED) as paquete:
        for nombre, datos in contenido.items():
            if datos is not None:
                paquete.writestr(nombre, datos)
    return memoria.getvalue()


class TestPublicarEnCarpeta(_ConClaveDePrueba):
    """Desde la V2 del Cliente PC (2026-10-28): la versión es un .zip con la carpeta, y se firma
    la lista de los archivos de adentro."""

    def test_firma_el_zip_con_la_lista_de_archivos(self):
        datos = zip_de_cliente()

        manifiesto = repo.publicar(datos, ahora=datetime(2026, 10, 28, 9, 0, 0))

        self.assertEqual(manifiesto["programa"], "PCcliente-carpeta")
        self.assertEqual((manifiesto["sha256"], manifiesto["tamano"]), (hashlib.sha256(datos).hexdigest(), len(datos)))
        self.assertEqual(manifiesto["v"], "2")
        self.assertEqual(manifiesto["archivos"]["_internal/python312.dll"],
                         [hashlib.sha256(b"dll" * 500).hexdigest(), 1500])
        self.assertEqual(manifiesto["archivos"]["_internal/vacio.txt"], [hashlib.sha256(b"").hexdigest(), 0])
        self.assertEqual(len(manifiesto["archivos"]), 4)
        paquete = repo.paquete()
        self.assertEqual(self.verificar(paquete), manifiesto)
        self.assertTrue(paquete["en_carpeta"])
        self.assertEqual(repo.datos_exe(), datos)
        carpeta = os.path.join(database.DATA_DIR, "cliente_pc")
        self.assertEqual(sorted(os.listdir(carpeta)), ["PCcliente.zip", "version.json"])

    def test_cargar_un_exe_despues_borra_el_zip_y_al_reves(self):
        carpeta = os.path.join(database.DATA_DIR, "cliente_pc")
        repo.publicar(zip_de_cliente())
        repo.publicar(exe_de_cliente(v="1.9"))
        self.assertEqual(sorted(os.listdir(carpeta)), ["PCcliente.exe", "version.json"])
        self.assertFalse(repo.paquete()["en_carpeta"])
        self.assertEqual(repo.datos_exe(), exe_de_cliente(v="1.9"))
        repo.publicar(zip_de_cliente())
        self.assertEqual(sorted(os.listdir(carpeta)), ["PCcliente.zip", "version.json"])
        self.assertEqual(repo.datos_exe(), zip_de_cliente())

    def test_rechaza_un_zip_que_las_pcs_no_aceptarian(self):
        malos = (
            ({"PCcliente.exe": None}, "no está PCcliente.exe"),
            ({"../fuera.dll": b"x"}, "no se puede usar"),
            ({"_internal/./x.dll": b"x"}, "no se puede usar"),
            ({"version.json": b"{}"}, "no se puede usar"),
            ({"pccliente.EXE": b"MZ"}, "no se puede usar"),                   # Windows no distingue mayúsculas
            ({"_internal/sub": b"x"}, "mismo nombre"),                        # archivo y carpeta
            ({"PCcliente.exe": b"MZ" + b"CyberBios" * 1000}, "no es el Cliente PC"),
        )
        for cambios, texto in malos:
            with self.assertRaises(ValueError, msg=cambios) as error:
                repo.publicar(zip_de_cliente(archivos=cambios))
            self.assertIn(texto, str(error.exception))
        with self.assertRaises(ValueError) as error:
            repo.publicar(zip_de_cliente()[:300])
        self.assertIn("roto", str(error.exception))
        self.assertIsNone(repo.paquete())

    def test_respeta_los_topes(self):
        with mock.patch.object(repo, "ARCHIVOS_MAXIMOS", 3), self.assertRaises(ValueError):
            repo.publicar(zip_de_cliente())
        with mock.patch.object(repo, "TAMANO_MAXIMO_CARPETA", 100), self.assertRaises(ValueError):
            repo.publicar(zip_de_cliente())

    def test_el_numero_de_version_sale_del_exe_de_adentro(self):
        self.assertEqual(repo.numero_de_version_del_paquete(zip_de_cliente(v="2.1")), "2.1")
        self.assertEqual(repo.numero_de_version_del_paquete(exe_de_cliente(v="1.9")), "1.9")
        self.assertIsNone(repo.numero_de_version_del_paquete(zip_de_cliente()[:300]))
        self.assertTrue(repo.es_en_carpeta(zip_de_cliente()))
        self.assertFalse(repo.es_en_carpeta(exe_de_cliente()))

    def test_lo_firmado_lo_acepta_y_lo_desempaqueta_el_cliente_pc_de_verdad(self):
        # La misma regla de los dos lados: con el actualizacion.py de CLIENTE PC (la carpeta de al lado).
        ruta = Path(__file__).resolve().parents[2] / "CLIENTE PC" / "actualizacion.py"
        if not ruta.exists():
            self.skipTest("No está la carpeta CLIENTE PC al lado")
        especificacion = importlib.util.spec_from_file_location("actualizacion_del_cliente_pc", ruta)
        cliente = importlib.util.module_from_spec(especificacion)
        especificacion.loader.exec_module(cliente)
        cliente.CLAVE_PUBLICA_FIRMA = PUBLICA_DE_PRUEBA
        datos = zip_de_cliente()
        repo.publicar(datos)
        paquete = repo.paquete()

        manifiesto = cliente.verificar_manifiesto(paquete["manifiesto"], paquete["firma"])

        with tempfile.TemporaryDirectory() as carpeta:
            ruta_zip = Path(carpeta) / "PCcliente.zip"
            ruta_zip.write_bytes(repo.datos_exe())
            cliente.comprobar_exe(ruta_zip, manifiesto)
            cliente.desempaquetar(ruta_zip, Path(carpeta) / "nueva", manifiesto)
            self.assertEqual((Path(carpeta) / "nueva" / "_internal" / "python312.dll").read_bytes(), b"dll" * 500)
            self.assertEqual(cliente.ARCHIVOS_MAXIMOS, repo.ARCHIVOS_MAXIMOS)
            self.assertEqual(cliente.TAMANO_MAXIMO_CARPETA, repo.TAMANO_MAXIMO_CARPETA)
            self.assertEqual(cliente.PROGRAMA_EN_CARPETA, repo.PROGRAMA_EN_CARPETA)


class TestSoloALasQueSabenPonerla(_ConClaveDePrueba):
    """Una versión en carpeta solo le llega a una PC que manda `formato=2` (Cliente PC V1.9 o más
    con el Lanzador 3): las demás la rechazarían en cada arranque."""

    REPORTE = {"version": "1", "carpeta": "C:\\c", "act": "", "act_detalle": ""}

    def setUp(self):
        super().setUp()
        self.pc1 = pcs_repo.crear_estacion("PC1")

    def test_en_carpeta_solo_si_la_pc_avisa_que_la_sabe_poner(self):
        version = repo.publicar(zip_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1])
        self.assertIsNone(repo.version_para_estacion(self.pc1))                # todavía no consultó

        repo.registrar_reporte(self.pc1, self.REPORTE)                          # un Cliente PC de antes
        self.assertIsNone(repo.version_para_estacion(self.pc1))

        repo.registrar_reporte(self.pc1, {**self.REPORTE, "formato": "2"})
        self.assertEqual(repo.version_para_estacion(self.pc1), version)

    def test_un_exe_le_llega_a_cualquiera(self):
        version = repo.publicar(exe_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1])
        repo.registrar_reporte(self.pc1, self.REPORTE)
        self.assertEqual(repo.version_para_estacion(self.pc1), version)

    def test_la_pantalla_dice_que_le_falta_la_v1_9(self):
        repo.publicar(zip_de_cliente())
        pc2 = pcs_repo.crear_estacion("PC2")
        repo.guardar_seleccion([self.pc1, pc2])
        repo.registrar_reporte(self.pc1, self.REPORTE)
        repo.registrar_reporte(pc2, {**self.REPORTE, "formato": "2"})

        pcs = {pc["nombre"]: pc for pc in repo.estado_de_las_pcs()}

        self.assertTrue(pcs["PC1"]["va_en_carpeta"])
        self.assertEqual([pcs[n]["sabe_poner_carpetas"] for n in ("PC1", "PC2")], [False, True])
        self.assertEqual(repo.situacion(pcs["PC1"]), repo.FALTA_PUENTE)
        self.assertEqual(repo.situacion(pcs["PC2"]), repo.APAGADA)     # la sabe poner (y no consultó hace poco)
        self.assertNotIn(repo.FALTA_PUENTE, repo.SITUACIONES_LISTAS)
        self.assertIn("Le falta la V1.9", pcs_actualizacion_dialogo.texto_del_estado(pcs["PC1"]))

    def test_sin_consultar_desde_que_se_abrio_se_adivina_por_su_lanzador(self):
        self.assertFalse(repo.sabe_poner_carpetas(self.pc1, numero_lanzador=2))
        self.assertTrue(repo.sabe_poner_carpetas(self.pc1, numero_lanzador=3))
        self.assertFalse(repo.sabe_poner_carpetas(self.pc1))
        repo.registrar_reporte(self.pc1, self.REPORTE)                          # lo que dijo gana
        self.assertFalse(repo.sabe_poner_carpetas(self.pc1, numero_lanzador=3))

    def test_ya_funcionando_con_ella_no_le_falta_nada(self):
        base = {"carpeta": "C:\\c", "ultima_conexion": "2026-10-28T12:00:00", "conectada": True, "le_toca": 5,
                "version": 5, "estado": "", "detalle": "", "version_bajada": None, "seleccionada": True,
                "va_en_carpeta": True, "sabe_poner_carpetas": False}
        self.assertEqual(repo.situacion(base), repo.FUNCIONANDO)


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

    def test_guarda_el_numero_de_lanzador(self):
        reporte = {"version": "1", "carpeta": "C:\\c", "act": "", "act_detalle": ""}
        repo.registrar_reporte(self.pc1, {**reporte, "lanzador": "2"})
        repo.registrar_reporte(self.pc2, reporte)                       # Cliente PC anterior a la V1.4

        self.assertEqual(self.estacion(self.pc1)["numero_lanzador"], 2)
        self.assertIsNone(self.estacion(self.pc2)["numero_lanzador"])
        pcs = {pc["nombre"]: pc for pc in repo.estado_de_las_pcs()}
        self.assertEqual((pcs["PC1"]["lanzador"], pcs["PC2"]["lanzador"]), (2, None))

    def reporte_de(self, estacion_id, estado, version, ahora, prendida_hace):
        """Lo que manda una PC con la versión `version` copiada (o no, según `estado`) y Windows
        prendido hace `prendida_hace` (un timedelta), visto a la hora `ahora`."""
        repo.registrar_reporte(estacion_id, {
            "version": "1", "carpeta": "C:\\c", "act": estado, "act_detalle": "",
            "act_version": str(version) if estado else "",
            "encendida": str(int(prendida_hace.total_seconds())),
        }, ahora=ahora)

    def situacion_de(self, nombre):
        return repo.situacion({pc["nombre"]: pc for pc in repo.estado_de_las_pcs()}[nombre])

    def test_copiada_y_reiniciada_sin_ponerse_dice_por_que(self):
        version = repo.publicar(exe_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1, self.pc2])
        a_las_10 = datetime(2026, 10, 22, 10, 0, 0)
        for pc in (self.pc1, self.pc2):         # las dos la copian; Windows prendido desde las 8
            self.reporte_de(pc, "descargada", version, a_las_10, timedelta(hours=2))
        self.assertEqual((self.situacion_de("PC1"), self.situacion_de("PC2")), (repo.LISTA, repo.LISTA))

        # Las 11: se reiniciaron (Windows prendido hace 1 minuto).
        a_las_11 = datetime(2026, 10, 22, 11, 0, 0)
        # PC1: Shadow Defender borró la copia; la PC la ve sin copiar y la vuelve a copiar.
        self.reporte_de(self.pc1, "", version, a_las_11, timedelta(minutes=1))
        self.reporte_de(self.pc1, "bajando", version, a_las_11 + timedelta(seconds=5), timedelta(minutes=1, seconds=5))
        self.reporte_de(self.pc1, "descargada", version, a_las_11 + timedelta(seconds=10), timedelta(minutes=1, seconds=10))
        # PC2: la copia siguió ahí y nadie la puso (arrancó sin Lanzador.exe).
        self.reporte_de(self.pc2, "descargada", version, a_las_11, timedelta(minutes=1))

        self.assertEqual((self.situacion_de("PC1"), self.situacion_de("PC2")), (repo.SE_BORRA, repo.SIN_LANZADOR))
        repo.olvidar_reportes()                 # el mostrador se cerró y se volvió a abrir
        self.assertEqual((self.situacion_de("PC1"), self.situacion_de("PC2")), (repo.SE_BORRA, repo.SIN_LANZADOR))

        # Arreglada, la PC2 se reinicia y la pone: no queda nada que seguir.
        repo.registrar_reporte(self.pc2, {"version": str(version), "carpeta": "C:\\c", "act": "", "act_detalle": "",
                                          "encendida": "30"}, ahora=datetime(2026, 10, 22, 12, 0, 0))
        self.assertEqual(self.situacion_de("PC2"), repo.FUNCIONANDO)
        self.assertIsNone(self.estacion(self.pc2)["seguimiento_actualizacion"])

    def test_sin_reinicio_o_sin_saber_cuando_arranco_no_dice_nada(self):
        version = repo.publicar(exe_de_cliente())["version"]
        repo.guardar_seleccion([self.pc1, self.pc2])
        a_las_10 = datetime(2026, 10, 22, 10, 0, 0)
        self.reporte_de(self.pc1, "descargada", version, a_las_10, timedelta(hours=2))
        # La desmarcan y la vuelven a marcar (la descarta y la copia de nuevo) sin reiniciarla; y la
        # cuenta de cuándo arrancó Windows baila unos segundos de una consulta a otra.
        self.reporte_de(self.pc1, "", version, a_las_10 + timedelta(minutes=1), timedelta(hours=2, minutes=1, seconds=-3))
        self.reporte_de(self.pc1, "descargada", version, a_las_10 + timedelta(minutes=2), timedelta(hours=2, minutes=2, seconds=4))
        # Un Cliente PC que no manda `encendida`: no hay cómo saber si se reinició.
        repo.registrar_reporte(self.pc2, {"version": "1", "carpeta": "C:\\c", "act": "descargada", "act_detalle": "",
                                          "act_version": str(version)})

        self.assertEqual((self.situacion_de("PC1"), self.situacion_de("PC2")), (repo.LISTA, repo.LISTA))

    def test_el_motivo_es_de_la_copia_que_tiene(self):
        # Le cargan otra versión: lo que se supo de la vieja no vale para la nueva.
        vieja = 20261022090000
        repo.publicar(exe_de_cliente())
        repo.guardar_seleccion([self.pc1])
        a_las_10 = datetime(2026, 10, 22, 10, 0, 0)
        self.reporte_de(self.pc1, "descargada", vieja, a_las_10, timedelta(hours=2))
        self.reporte_de(self.pc1, "descargada", vieja, a_las_10 + timedelta(hours=1), timedelta(minutes=1))
        self.assertEqual(json.loads(self.estacion(self.pc1)["seguimiento_actualizacion"])["motivo"],
                         dominio.NO_SE_PUSO_SIN_LANZADOR)
        nueva = repo.version_publicada()

        self.reporte_de(self.pc1, "descargada", nueva, a_las_10 + timedelta(hours=1, minutes=1), timedelta(minutes=2))

        self.assertEqual(self.situacion_de("PC1"), repo.LISTA)

    def test_texto_de_una_version(self):
        self.assertEqual(repo.texto_version(20261018193005), "18/10/2026 19:30")
        self.assertEqual(repo.texto_version(7), "7")
        self.assertEqual(repo.texto_version(None), "")


class TestNumeroDeVersion(_ConClaveDePrueba):
    """El número de versión que ve el dueño (V1, V1.1 ... V1.9, V2): el que trae el exe y el que
    manda cada PC."""

    def setUp(self):
        super().setUp()
        self.pc1, self.pc2 = pcs_repo.crear_estacion("PC1"), pcs_repo.crear_estacion("PC2")

    def test_lo_lee_del_exe(self):
        leer = repo.numero_de_version_del_exe
        self.assertEqual(leer(exe_de_cliente(v="1.2")), "1.2")
        self.assertEqual(leer(exe_de_cliente(v="2")), "2")              # 2.0 es la V2
        self.assertIsNone(leer(exe_de_cliente()))                       # uno armado antes de la V1
        self.assertIsNone(leer(b"MZ" + datos_de_version(1, 10)))        # "1.10" no existe
        self.assertIsNone(leer(b"MZ" + datos_de_version(0, 5)))
        self.assertIsNone(leer(b"MZ" + "VS_VERSION_INFO\0".encode("utf-16-le") + b"\0" * 40))   # sin la marca

    def test_lo_lee_de_un_exe_de_verdad(self):
        # El exe chiquito de PyInstaller con el número grabado como lo graba PCcliente.spec.
        try:
            import PyInstaller
            from PyInstaller.utils.win32 import versioninfo as vi
        except ImportError:
            self.skipTest("hace falta PyInstaller")
        original = Path(PyInstaller.__file__).parent / "bootloader" / "Windows-64bit-intel" / "runw.exe"
        if not original.exists():
            self.skipTest(f"no está {original}")
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        exe = Path(carpeta.name) / "PCcliente.exe"
        shutil.copyfile(original, exe)
        self.assertIsNone(repo.numero_de_version_del_exe(exe.read_bytes()))

        vi.write_version_info_to_executable(str(exe), vi.VSVersionInfo(
            ffi=vi.FixedFileInfo(filevers=(1, 3, 0, 0), prodvers=(1, 3, 0, 0)),
            kids=[vi.StringFileInfo([vi.StringTable("0C0A04B0", [vi.StringStruct("ProductVersion", "V1.3")])]),
                  vi.VarFileInfo([vi.VarStruct("Translation", [0x0C0A, 1200])])]))

        self.assertEqual(repo.numero_de_version_del_exe(exe.read_bytes()), "1.3")

    def test_como_se_escribe_y_cual_es_mas_vieja(self):
        self.assertEqual([repo.numero_de_version_valido(x) for x in ("1", "1.2", " 2.9 ", "1.0", "1.10", "V1", "", None, "0")],
                         ["1", "1.2", "2.9", None, None, None, None, None, None])
        self.assertEqual((repo.nombre_de_version("1.2"), repo.nombre_de_version(None)), ("V1.2", ""))
        self.assertTrue(repo.es_mas_vieja("1.9", "2"))
        self.assertTrue(repo.es_mas_vieja("1.2", "1.3"))
        self.assertFalse(repo.es_mas_vieja("2", "1.9"))
        self.assertFalse(repo.es_mas_vieja("1.2", "1.2"))

    def test_va_firmado_en_el_manifiesto_y_las_pcs_lo_ignoran(self):
        manifiesto = repo.publicar(exe_de_cliente(v="1.2"))

        self.assertEqual(manifiesto["v"], "1.2")
        self.assertEqual(self.verificar(repo.paquete()), manifiesto)
        self.assertEqual(repo.paquete()["v"], "1.2")

    def test_un_exe_sin_numero_se_carga_igual(self):
        manifiesto = repo.publicar(exe_de_cliente())

        self.assertNotIn("v", manifiesto)
        self.assertIsNone(repo.paquete()["v"])

    def test_guarda_el_que_manda_la_pc_aunque_no_tenga_lanzador(self):
        repo.registrar_reporte(self.pc1, {"estacion": "PC1", "v": "1.2"})                 # sin lanzador
        repo.registrar_reporte(self.pc2, {"estacion": "PC2", "v": "2", "version": "5", "carpeta": "C:\\c"})

        self.assertEqual(pcs_repo.obtener_estacion(self.pc1)["numero_version_cliente"], "1.2")
        self.assertIsNone(pcs_repo.obtener_estacion(self.pc1)["carpeta_cliente"])   # lo demás no se toca
        self.assertEqual(pcs_repo.obtener_estacion(self.pc2)["numero_version_cliente"], "2")

    def test_si_vuelve_a_uno_sin_numero_o_manda_cualquier_cosa_queda_sin_numero(self):
        repo.registrar_reporte(self.pc1, {"v": "1.2"})
        repo.registrar_reporte(self.pc1, {})
        self.assertIsNone(pcs_repo.obtener_estacion(self.pc1)["numero_version_cliente"])
        repo.registrar_reporte(self.pc1, {"v": "1.2'; DROP TABLE estaciones;--"})
        self.assertIsNone(pcs_repo.obtener_estacion(self.pc1)["numero_version_cliente"])

    def test_solo_escribe_si_cambio(self):
        repo.registrar_reporte(self.pc1, {"v": "1.2"})
        with database.conexion_db() as conexion:     # alguien lo cambia por fuera
            conexion.execute("UPDATE estaciones SET numero_version_cliente = 'x' WHERE id = ?", (self.pc1,))

        repo.registrar_reporte(self.pc1, {"v": "1.2"})
        self.assertEqual(pcs_repo.obtener_estacion(self.pc1)["numero_version_cliente"], "x")
        repo.registrar_reporte(self.pc1, {"v": "1.3"})
        self.assertEqual(pcs_repo.obtener_estacion(self.pc1)["numero_version_cliente"], "1.3")

    def test_en_el_estado_de_las_pcs(self):
        repo.publicar(exe_de_cliente(v="1.3"))
        repo.guardar_seleccion([self.pc1])
        repo.registrar_reporte(self.pc1, {"v": "1.2"})

        pcs = {pc["nombre"]: pc for pc in repo.estado_de_las_pcs()}
        self.assertEqual((pcs["PC1"]["v"], pcs["PC1"]["v_le_toca"]), ("1.2", "1.3"))
        self.assertEqual((pcs["PC2"]["v"], pcs["PC2"]["v_le_toca"]), (None, None))   # sin marcar


class TestSeguirLaCopia(unittest.TestCase):
    """`seguir_la_copia`: si una PC que ya copió la versión se reinició sin ponerla, y por qué."""

    ANTES = datetime(2026, 10, 22, 8, 0, 0)

    def seguir(self, previo, estado, bajada=7, instalada=6, arranque=ANTES):
        return repo.seguir_la_copia(previo, estado, bajada, instalada, arranque)

    def test_al_copiarla_empieza_a_seguirla(self):
        self.assertEqual(self.seguir(None, "descargada"),
                         {"version": 7, "arranque": "2026-10-22T08:00:00", "salio": False, "motivo": ""})
        self.assertIsNone(self.seguir(None, "bajando"))
        self.assertIsNone(self.seguir(None, ""))

    def test_reiniciada_con_la_copia_ahi_no_arranco_con_el_lanzador(self):
        copiada = self.seguir(None, "descargada")
        despues = self.seguir(copiada, "descargada", arranque=self.ANTES + timedelta(hours=1))
        self.assertEqual(despues["motivo"], dominio.NO_SE_PUSO_SIN_LANZADOR)
        self.assertEqual(despues["arranque"], "2026-10-22T09:00:00")

    def test_reiniciada_y_copiada_de_nuevo_se_la_borro_el_reinicio(self):
        copiada = self.seguir(None, "descargada")
        sin_copia = self.seguir(copiada, "", bajada=None, arranque=self.ANTES + timedelta(hours=1))
        self.assertTrue(sin_copia["salio"])
        copiando = self.seguir(sin_copia, "bajando", arranque=self.ANTES + timedelta(hours=1))
        despues = self.seguir(copiando, "descargada", arranque=self.ANTES + timedelta(hours=1))
        self.assertEqual(despues["motivo"], dominio.NO_SE_PUSO_SE_BORRO)
        self.assertFalse(despues["salio"])

    def test_poca_diferencia_no_es_un_reinicio(self):
        copiada = self.seguir(None, "descargada")
        casi = self.seguir(copiada, "descargada", arranque=self.ANTES + timedelta(seconds=repo.MARGEN_REINICIO_SEGUNDOS))
        self.assertEqual(casi["motivo"], "")

    def test_sin_saber_cuando_arranco_no_decide_nada_y_lo_anota_cuando_lo_sabe(self):
        copiada = self.seguir(None, "descargada", arranque=None)
        self.assertEqual(self.seguir(copiada, "descargada", arranque=None), copiada)
        sabido = self.seguir(copiada, "descargada")
        self.assertEqual((sabido["arranque"], sabido["motivo"]), ("2026-10-22T08:00:00", ""))

    def test_al_ponerla_o_si_fallo_deja_de_seguirla(self):
        copiada = self.seguir(None, "descargada")
        self.assertIsNone(self.seguir(copiada, "", bajada=None, instalada=7))
        self.assertIsNone(self.seguir(copiada, "", bajada=None, instalada=8))
        self.assertIsNone(self.seguir(copiada, "fallo", bajada=None))

    def test_el_motivo_queda_hasta_que_la_pone(self):
        copiada = self.seguir(None, "descargada")
        con_motivo = self.seguir(copiada, "descargada", arranque=self.ANTES + timedelta(hours=1))
        self.assertEqual(self.seguir(con_motivo, "descargada", arranque=self.ANTES + timedelta(hours=1))["motivo"],
                         dominio.NO_SE_PUSO_SIN_LANZADOR)


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

    def test_copiada_que_no_se_puso_al_reiniciar(self):
        lista = {"estado": "descargada", "version_bajada": 5}
        self.assertEqual(self.situacion(**lista, no_se_puso=dominio.NO_SE_PUSO_SE_BORRO), repo.SE_BORRA)
        self.assertEqual(self.situacion(**lista, no_se_puso=dominio.NO_SE_PUSO_SIN_LANZADOR), repo.SIN_LANZADOR)
        self.assertEqual(self.situacion(**lista, no_se_puso=""), repo.LISTA)
        self.assertEqual(self.situacion(**lista, no_se_puso=dominio.NO_SE_PUSO_SE_BORRO, conectada=False), repo.SE_BORRA)
        self.assertNotIn(repo.SE_BORRA, repo.SITUACIONES_LISTAS)
        self.assertNotIn(repo.SIN_LANZADOR, repo.SITUACIONES_LISTAS)

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

    def test_una_version_en_carpeta_solo_le_llega_a_la_pc_que_la_sabe_poner(self):
        datos = zip_de_cliente()
        version = repo.publicar(datos)["version"]
        repo.guardar_seleccion([self.pc1])

        status, estado = self._get("/estado?estacion=PC1&version=1&carpeta=C%3A%5Cc&lanzador=2")
        self.assertEqual((status, estado["cliente_version"]), (200, None))

        status, estado = self._get("/estado?estacion=PC1&version=1&carpeta=C%3A%5Cc&lanzador=3&formato=2")
        self.assertEqual((status, estado["cliente_version"]), (200, version))
        status, _tipo, cuerpo = self._get_crudo("/cliente_pc")
        manifiesto = json.loads(json.loads(cuerpo)["manifiesto"])
        self.assertEqual(manifiesto["programa"], "PCcliente-carpeta")
        status, _tipo, recibido = self._get_crudo("/cliente_pc/exe")
        self.assertEqual((status, recibido), (200, datos))

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

    def test_la_consulta_de_estado_guarda_el_numero_de_version(self):
        self._get("/estado?estacion=PC1&v=1.2")

        self.assertEqual(pcs_repo.obtener_estacion(self.pc1)["numero_version_cliente"], "1.2")

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
        self.assertEqual(d.tabla.item(0, 2).text(), "Actualizada con éxito · se aplica al reiniciarse (sola, si está libre)")
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
        self.assertEqual(texto({**base, "estado": "descargada"}), "Actualizada con éxito · se aplica al reiniciarse (sola, si está libre)")
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
        lista = {**base, "estado": "descargada", "version_bajada": 5}
        self.assertIn("Shadow Defender y reiniciala", texto({**lista, "no_se_puso": dominio.NO_SE_PUSO_SE_BORRO}))
        self.assertIn("«Lanzador.exe --configurar» como Administrador",
                      texto({**lista, "no_se_puso": dominio.NO_SE_PUSO_SIN_LANZADOR}))
        version = pcs_actualizacion_dialogo.texto_de_la_version
        self.assertEqual(version({"v": "1.2", "version": 20261018193005, "carpeta": "C:\\c"}), "V1.2")
        self.assertEqual(version({"v": "2", "version": None, "carpeta": "", "ultima_conexion": "2026-10-19T12:00:00"}), "V2")
        # Se conectó y no manda número: un Cliente PC armado antes de la V1 (con lanzador o sin él).
        self.assertEqual(version({"v": None, "version": 20261018193005, "carpeta": "C:\\c"}), "anterior a la V1")
        self.assertEqual(version({"v": None, "version": None, "carpeta": "", "ultima_conexion": "2026-10-19T12:00:00"}),
                         "anterior a la V1")
        self.assertEqual(version({"v": None, "version": None, "carpeta": "", "ultima_conexion": None}), "")

    def test_con_numero_de_version_dice_cual(self):
        texto = pcs_actualizacion_dialogo.texto_del_estado
        base = {"estado": "", "detalle": "", "carpeta": "C:\\c", "le_toca": 20261019120000, "version": 4,
                "version_bajada": None, "ultima_conexion": "2026-10-19T12:00:00", "conectada": True,
                "seleccionada": True, "v": "1.2", "v_le_toca": "1.3"}
        self.assertEqual(texto({**base, "version": 20261019120000}), "Funcionando con la V1.3")
        self.assertEqual(texto({**base, "estado": "fallo", "detalle": "La versión 20261019120000 se cerró"}),
                         "Falló al arrancar: La versión V1.3 se cerró")
        # Otra versión que no es la que le toca, o la cargada sin número: por la fecha.
        self.assertEqual(texto({**base, "estado": "fallo", "detalle": "La versión 20261018005701 se cerró"}),
                         "Falló al arrancar: La versión 18/10/2026 00:57 se cerró")
        self.assertEqual(texto({**base, "v_le_toca": None, "estado": "fallo", "detalle": "La versión 20261019120000 se cerró"}),
                         "Falló al arrancar: La versión 19/10/2026 12:00 se cerró")

    def test_la_version_cargada_con_su_numero(self):
        cargada = pcs_actualizacion_dialogo.texto_de_la_version_cargada
        self.assertEqual(cargada({"version": 20261019092300, "v": "1.2"}), "V1.2 (cargada el 19/10/2026 09:23)")
        self.assertEqual(cargada({"version": 20261019092300, "v": None}),
                         "19/10/2026 09:23 (sin número: armada antes de la V1)")

    def test_cargar_una_con_numero_lo_dice_y_avisa_si_es_mas_vieja(self):
        preguntas = []
        with open(self.ruta_elegida, "wb") as archivo:
            archivo.write(exe_de_cliente(v="1.3"))
        with mock.patch.object(pcs_actualizacion_dialogo, "confirmar",
                               side_effect=lambda *a, **k: preguntas.append(a[2]) or True):
            d = self.dialogo()
            d._cargar_version()
            self.assertIn("(V1.3)", preguntas[-1])
            self.assertNotIn("más vieja", preguntas[-1])
            self.assertTrue(d.etiqueta_version.text().startswith("Versión cargada: V1.3 (cargada el "))
            self.assertTrue(self.infos[-1].startswith("V1.3 cargada y firmada."))

            with open(self.ruta_elegida, "wb") as archivo:
                archivo.write(exe_de_cliente(v="1.2"))
            d._cargar_version()
            self.assertIn("la V1.2 es más vieja que la V1.3", preguntas[-1])

            with open(self.ruta_elegida, "wb") as archivo:
                archivo.write(exe_de_cliente())
            d._cargar_version()
            self.assertIn("No tiene número de versión", preguntas[-1])

    def test_cargar_una_version_en_carpeta_avisa_que_solo_va_a_las_que_tienen_la_v1_9(self):
        preguntas = []
        with open(self.ruta_elegida, "wb") as archivo:
            archivo.write(zip_de_cliente(v="2"))
        with mock.patch.object(pcs_actualizacion_dialogo, "confirmar",
                               side_effect=lambda *a, **k: preguntas.append(a[2]) or True):
            self.dialogo()._cargar_version()
        self.assertIn("esta versión en carpeta (.zip) (V2)", preguntas[-1])
        self.assertIn("solo la pueden poner las PCs que ya tienen la V1.9", preguntas[-1])
        self.assertTrue(repo.paquete()["en_carpeta"])
        self.assertIn("*.zip", pcs_actualizacion_dialogo.FILTRO_EXE)

    def test_la_columna_muestra_el_numero_que_manda_cada_pc(self):
        repo.registrar_reporte(self.pc1, {"v": "1.2"})
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET ultima_conexion = '2026-10-19T12:00:00' WHERE id = ?", (self.pc2,))
        d = self.dialogo()

        self.assertEqual([d.tabla.item(f, 3).text() for f in range(d.tabla.rowCount())], ["V1.2", "anterior a la V1"])

    def test_la_columna_lanzador(self):
        repo.registrar_reporte(self.pc1, {"version": "1", "carpeta": "C:\\c", "act": "", "act_detalle": "", "lanzador": "2"})
        repo.registrar_reporte(self.pc2, {"version": "1", "carpeta": "C:\\c", "act": "", "act_detalle": ""})
        d = self.dialogo()

        columna = pcs_actualizacion_dialogo.COLUMNA_LANZADOR
        self.assertEqual(d.tabla.horizontalHeaderItem(columna).text(), "Lanzador")
        self.assertEqual([d.tabla.item(f, columna).text() for f in range(d.tabla.rowCount())], ["2", "—"])
        self.assertIn("anterior a la V1.4", d.tabla.item(1, columna).toolTip())
        self.assertEqual(pcs_actualizacion_dialogo.texto_del_lanzador({"lanzador": None, "carpeta": ""}), "")

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
        no_se_puso = [{**base, "nombre": "PC6", "estado": "descargada", "no_se_puso": dominio.NO_SE_PUSO_SE_BORRO},
                      {**base, "nombre": "PC7", "estado": "descargada", "no_se_puso": dominio.NO_SE_PUSO_SIN_LANZADOR}]
        self.assertEqual(resumen(no_se_puso, True),
                         "0 de 2 listas · faltan: PC6 (se borra al reiniciar), PC7 (no arranca con el Lanzador)")
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
        botones = [b for b in gestion.findChildren(QPushButton) if b.accessibleName() == "Actualizar el Cliente PC"]
        self.assertEqual(len(botones), 1)

        with mock.patch.object(pcs_gestion_dialogos.DialogoActualizarCliente, "exec") as abrir:
            botones[0].click()

        abrir.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
