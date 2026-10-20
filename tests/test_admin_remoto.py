"""
tests/test_admin_remoto.py
===========================
Administrar desde otra PC del local (pedido del dueño, 2026-10-18; ver
admin_remoto/ y repositories/admin_remoto_repo.py):

- Cómo viajan los datos (codec) y cómo se reconoce que el programa se abrió
  desde la carpeta compartida del mostrador (modo).
- Quién puede entrar: solo un Administrador, y solo con la entrada prendida.
- El servidor del mostrador: lista blanca, sesiones atadas a la PC que entró,
  bloqueo tras claves mal puestas, el "quién lo hizo" lo pone el mostrador.
- Una copia remota de verdad (este proceso) contra un mostrador de prueba en
  otro proceso (tests/mostrador_de_prueba.py): las pantallas abren sin errores,
  lo que se guarda queda en la base del mostrador, y esta copia nunca abre ni
  crea una base propia.

Se ejecutan con:

    python -m unittest discover tests
"""

import ast
import json
import os
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import unittest
from datetime import date, datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
import servidor_red  # noqa: E402
from admin_remoto import cliente, codec, lista_blanca, modo, servidor  # noqa: E402
from repositories import admin_remoto_repo, turnos_faltantes_repo, usuarios_repo, ventas_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402
import mostrador_de_prueba  # noqa: E402

_app = QApplication.instance() or QApplication([])

RAIZ = Path(__file__).resolve().parent.parent
IP = "10.0.0.5"
OTRA_IP = "10.0.0.6"


# ---------------------------------------------------------------------------
# Cómo viajan los datos
# ---------------------------------------------------------------------------

def _ida_y_vuelta(valor):
    return codec.de_json(json.loads(json.dumps(codec.a_json(valor))))


class TestCodec(unittest.TestCase):
    def test_una_fila_de_la_base_llega_y_se_lee_igual(self):
        conexion = sqlite3.connect(":memory:")
        conexion.row_factory = sqlite3.Row
        fila = conexion.execute("SELECT 7 AS id, 'Lucía' AS nombre, 'sal$hash' AS clave_hash").fetchone()

        llegada = _ida_y_vuelta(fila)

        self.assertEqual(llegada["id"], 7)
        self.assertEqual(llegada[1], "Lucía")
        self.assertEqual(llegada["NOMBRE"], "Lucía")  # sin distinguir mayúsculas, como sqlite3.Row
        self.assertEqual(list(llegada), [7, "Lucía", ""])
        self.assertEqual(llegada.keys(), ["id", "nombre", "clave_hash"])
        with self.assertRaises(IndexError):
            llegada["no_existe"]

    def test_el_hash_de_una_clave_nunca_viaja(self):
        conexion = sqlite3.connect(":memory:")
        conexion.row_factory = sqlite3.Row
        fila = conexion.execute("SELECT 'sal$hash' AS clave_hash").fetchone()
        self.assertNotIn("sal$hash", json.dumps(codec.a_json([fila])))

    def test_tuplas_conjuntos_fechas_imagenes_y_claves_que_no_son_texto(self):
        valor = {
            "tupla": (1, "a", None),
            "conjunto": {"10.0.0.1", "10.0.0.2"},
            "momento": datetime(2026, 10, 18, 22, 5, 30, 123456),
            "dia": date(2026, 10, 18),
            "jpeg": b"\xff\xd8\xff\x00datos",
            "por_turno": {(date(2026, 10, 18), dominio.TURNO_NOCHE): {"LUCIA"}, 3: "tres"},
            "lista": [True, 1.5, -2, "texto"],
        }
        self.assertEqual(_ida_y_vuelta(valor), valor)

    def test_un_diccionario_que_parece_una_etiqueta_vuelve_igual(self):
        self.assertEqual(_ida_y_vuelta({"__t": [1, 2]}), {"__t": [1, 2]})

    def test_un_tipo_que_no_sabe_mandar_es_un_error_claro(self):
        with self.assertRaises(TypeError):
            codec.a_json(object())

    def test_del_otro_lado_no_se_arma_nada_raro(self):
        self.assertEqual(codec.de_json({"__x": 1}), {"__x": 1})
        with self.assertRaises(ValueError):
            codec.de_json({"__d": [[[1, 2], "una lista no puede ser clave"]]})


# ---------------------------------------------------------------------------
# ¿Copia del mostrador o copia remota?
# ---------------------------------------------------------------------------

class TestModo(unittest.TestCase):
    def test_una_carpeta_compartida_es_de_la_pc_que_la_comparte(self):
        self.assertEqual(modo.pc_de_la_carpeta(r"\\MOSTRADOR\CyberBios"), "MOSTRADOR")
        self.assertEqual(modo.pc_de_la_carpeta(r"\\192.168.0.10\CyberBios\sub"), "192.168.0.10")
        self.assertEqual(modo.pc_de_la_carpeta("//MOSTRADOR/CyberBios"), "MOSTRADOR")
        self.assertEqual(modo.pc_de_la_carpeta(r"\\?\UNC\SERVIDOR\carpeta"), "SERVIDOR")

    def test_una_carpeta_de_esta_pc_no_es_remota(self):
        self.assertIsNone(modo.pc_de_la_carpeta(r"\\?\C:\Users\CyberBIOS\Desktop\CyberBios"))
        self.assertIsNone(modo.pc_de_la_carpeta(os.path.dirname(os.path.abspath(__file__))))

    def test_se_puede_decir_a_mano_a_que_pc_hablarle(self):
        self.assertEqual(
            modo.direccion_del_mostrador(["CyberBios.exe", "--mostrador", "192.168.0.10"], r"C:\CyberBios"),
            "192.168.0.10",
        )
        self.assertEqual(modo.direccion_del_mostrador(["CyberBios.exe"], r"\\MOSTRADOR\CyberBios"), "MOSTRADOR")
        self.assertIsNone(modo.direccion_del_mostrador(["CyberBios.exe"], r"\\?\C:\CyberBios"))

    def test_el_mostrador_no_es_una_copia_remota(self):
        self.assertFalse(modo.es_copia_remota())


# ---------------------------------------------------------------------------
# Quién puede entrar desde otra PC
# ---------------------------------------------------------------------------

class TestQuienEntra(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.listar_usuarios()[0]
        usuarios_repo.crear_usuario("LUCIA", "4321", dominio.ROL_EMPLEADA)
        self.lucia = next(u for u in usuarios_repo.listar_usuarios() if u["nombre"] == "LUCIA")

    def test_viene_apagada(self):
        self.assertFalse(admin_remoto_repo.esta_activo())
        with self.assertRaises(PermissionError):
            admin_remoto_repo.entrar("Administrador", "1234", IP)

    def test_solo_un_administrador_la_prende(self):
        with self.assertRaises(PermissionError):
            admin_remoto_repo.activar(self.lucia["id"], True)
        admin_remoto_repo.activar(self.admin["id"], True)
        self.assertTrue(admin_remoto_repo.esta_activo())
        admin_remoto_repo.activar(self.admin["id"], False)
        self.assertFalse(admin_remoto_repo.esta_activo())

    def test_entra_el_administrador_y_queda_anotada_la_pc(self):
        admin_remoto_repo.activar(self.admin["id"], True)
        usuario = admin_remoto_repo.entrar("  administrador ", "1234", IP)
        self.assertEqual(usuario["id"], self.admin["id"])

        hoy = date.today().isoformat()
        ultimo = usuarios_repo.listar_logins(hoy, hoy)[0]
        self.assertEqual(ultimo["desde_ip"], IP)

    def test_un_ingreso_en_el_mostrador_queda_sin_ip(self):
        usuarios_repo.autenticar_por_nombre("LUCIA", "4321")
        hoy = date.today().isoformat()
        self.assertIsNone(usuarios_repo.listar_logins(hoy, hoy, solo_admin=False)[0]["desde_ip"])

    def test_una_empleada_no_entra_ni_con_su_clave(self):
        admin_remoto_repo.activar(self.admin["id"], True)
        self.assertIsNone(admin_remoto_repo.entrar("LUCIA", "4321", IP))
        hoy = date.today().isoformat()
        self.assertEqual(usuarios_repo.listar_logins(hoy, hoy, solo_admin=False), [])

    def test_una_clave_mal_no_entra(self):
        admin_remoto_repo.activar(self.admin["id"], True)
        self.assertIsNone(admin_remoto_repo.entrar("Administrador", "0000", IP))

    def test_la_lista_para_entrar_tiene_solo_administradores(self):
        self.assertEqual(admin_remoto_repo.administradores_para_entrar(), ["Administrador"])

    def test_entrar_desde_otra_pc_no_es_estar_en_el_mostrador(self):
        # La pista de quién podría ser responsable de un turno sin cerrar sale de
        # los ingresos al mostrador, no de los de otra PC.
        admin_remoto_repo.activar(self.admin["id"], True)
        admin_remoto_repo.entrar("Administrador", "1234", IP)
        inicio_mes = datetime.now().replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        with database.conexion_db() as conexion:
            responsables = turnos_faltantes_repo._responsables_del_mes(conexion, inicio_mes)
        self.assertFalse(any("Administrador" in nombres for nombres in responsables.values()))

        usuarios_repo.autenticar_por_nombre("Administrador", "1234")
        with database.conexion_db() as conexion:
            responsables = turnos_faltantes_repo._responsables_del_mes(conexion, inicio_mes)
        self.assertTrue(any("Administrador" in nombres for nombres in responsables.values()))


class TestMigracionDesdeIp(unittest.TestCase):
    def test_una_base_vieja_gana_la_columna_sin_perder_sus_ingresos(self):
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        ruta = os.path.join(carpeta.name, "vieja.db")
        conexion = sqlite3.connect(ruta)
        conexion.execute("""
            CREATE TABLE sesiones (
                id INTEGER PRIMARY KEY AUTOINCREMENT, usuario_id INTEGER NOT NULL, fecha_hora TEXT NOT NULL
            )
        """)
        conexion.execute("INSERT INTO sesiones (usuario_id, fecha_hora) VALUES (1, '2026-10-01T10:00:00')")
        conexion.commit()
        conexion.close()

        with mock.patch.object(database, "DATA_DIR", carpeta.name), mock.patch.object(database, "DB_PATH", ruta):
            database.inicializar_base_de_datos()
            database.inicializar_base_de_datos()  # dos veces: no pasa nada

        conexion = sqlite3.connect(ruta)
        columnas = [fila[1] for fila in conexion.execute("PRAGMA table_info(sesiones)")]
        filas = conexion.execute("SELECT usuario_id, desde_ip FROM sesiones").fetchall()
        conexion.close()
        self.assertIn("desde_ip", columnas)
        self.assertEqual(filas, [(1, None)])


# ---------------------------------------------------------------------------
# El servidor del mostrador
# ---------------------------------------------------------------------------

class _ConServidor(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        servidor._olvidar_todo()
        self.addCleanup(servidor._olvidar_todo)
        self.admin = usuarios_repo.listar_usuarios()[0]
        admin_remoto_repo.activar(self.admin["id"], True)
        usuarios_repo.crear_usuario("LUCIA", "4321", dominio.ROL_EMPLEADA)
        self.lucia = next(u for u in usuarios_repo.listar_usuarios() if u["nombre"] == "LUCIA")

    def _pedir(self, ruta, cuerpo, ip=IP):
        return servidor.atender(servidor.PREFIJO + ruta, json.dumps(cuerpo).encode("utf-8"), ip)

    def _entrar(self, nombre="Administrador", clave="1234", ip=IP):
        status, respuesta = self._pedir("entrar", {"huella": lista_blanca.huella(), "nombre": nombre, "clave": clave}, ip)
        self.assertEqual(status, 200)
        return respuesta

    def _llamar(self, token, modulo_repo, funcion, args=(), kwargs=None, ip=IP):
        return self._pedir("llamar", {
            "token": token, "modulo": modulo_repo, "funcion": funcion,
            "args": codec.a_json(list(args)), "kwargs": codec.a_json(kwargs or {}),
        }, ip)[1]


class TestServidorDelMostrador(_ConServidor):
    def test_hola_dice_si_esta_prendida_y_si_es_el_mismo_programa(self):
        status, respuesta = self._pedir("hola", {"huella": lista_blanca.huella()})
        self.assertEqual((status, respuesta["activo"], respuesta["misma_version"]), (200, True, True))
        admin_remoto_repo.activar(self.admin["id"], False)
        respuesta = self._pedir("hola", {"huella": "otra"})[1]
        self.assertEqual((respuesta["activo"], respuesta["misma_version"]), (False, False))

    def test_con_otro_programa_no_se_entra(self):
        respuesta = self._pedir("entrar", {"huella": "otra", "nombre": "Administrador", "clave": "1234"})[1]
        self.assertEqual(respuesta["error"]["tipo"], "Version")

    def test_la_lista_de_nombres_es_solo_de_administradores(self):
        respuesta = self._pedir("usuarios", {"huella": lista_blanca.huella()})[1]
        self.assertEqual(respuesta["nombres"], ["Administrador"])

    def test_se_entra_y_se_hace_una_funcion_de_la_lista(self):
        token = self._entrar()["token"]
        respuesta = self._llamar(token, "usuarios_repo", "listar_usuarios")
        self.assertTrue(respuesta["ok"])
        nombres = [fila["nombre"] for fila in codec.de_json(respuesta["resultado"])]
        self.assertEqual(sorted(nombres), ["Administrador", "LUCIA"])

    def test_el_hash_de_las_claves_no_sale_del_mostrador(self):
        respuesta = self._entrar()
        self.assertEqual(codec.de_json(respuesta["usuario"])["clave_hash"], "")
        resultado = self._llamar(respuesta["token"], "usuarios_repo", "listar_usuarios")["resultado"]
        self.assertTrue(all(fila["clave_hash"] == "" for fila in codec.de_json(resultado)))

    def test_lo_que_no_esta_en_la_lista_se_rechaza(self):
        token = self._entrar()["token"]
        linea = {"codigo": "x", "descripcion": "x", "cantidad": 1, "precio_unitario": 1.0}
        for modulo_repo, funcion in [
            ("ventas_repo", "confirmar_venta"), ("limpieza_repo", "limpiar_base"),
            ("turnos_repo", "cerrar_turno"), ("database", "conexion_db"), ("usuarios_repo", "__dict__"),
        ]:
            respuesta = self._llamar(token, modulo_repo, funcion, [self.admin["id"], [linea], []])
            self.assertEqual(respuesta["error"]["tipo"], "Permiso", (modulo_repo, funcion))

    def test_sin_entrar_no_se_hace_nada(self):
        respuesta = self._llamar("inventado", "usuarios_repo", "listar_usuarios")
        self.assertEqual(respuesta["error"]["tipo"], "Sesion")

    def test_la_sesion_vale_solo_desde_la_pc_que_entro(self):
        token = self._entrar()["token"]
        self.assertEqual(self._llamar(token, "usuarios_repo", "listar_usuarios", ip=OTRA_IP)["error"]["tipo"], "Sesion")
        self.assertTrue(self._llamar(token, "usuarios_repo", "listar_usuarios")["ok"])

    def test_apagar_la_entrada_corta_al_que_estaba_adentro(self):
        token = self._entrar()["token"]
        admin_remoto_repo.activar(self.admin["id"], False)
        self.assertEqual(self._llamar(token, "usuarios_repo", "listar_usuarios")["error"]["tipo"], "Sesion")
        admin_remoto_repo.activar(self.admin["id"], True)
        # La sesión no revive: hay que volver a entrar.
        self.assertEqual(self._llamar(token, "usuarios_repo", "listar_usuarios")["error"]["tipo"], "Sesion")

    def test_un_administrador_dado_de_baja_no_sigue(self):
        usuarios_repo.crear_usuario("NAIR", "5555", dominio.ROL_ADMIN)
        nair = next(u for u in usuarios_repo.listar_usuarios() if u["nombre"] == "NAIR")
        token = self._entrar("NAIR", "5555")["token"]
        usuarios_repo.desactivar_usuario(nair["id"])
        self.assertEqual(self._llamar(token, "usuarios_repo", "listar_usuarios")["error"]["tipo"], "Sesion")

    def test_quien_anula_es_el_que_entro_aunque_la_otra_pc_mande_otro(self):
        from repositories import articulos_repo
        rubro = articulos_repo.listar_rubros()[0]["id"]
        articulos_repo.crear_articulo("111", "Chicle", None, rubro, 100.0, 50.0, 0)
        venta_id = ventas_repo.confirmar_venta(
            self.lucia["id"], [{"codigo": "111", "descripcion": "Chicle", "cantidad": 1, "precio_unitario": 100.0}],
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 100.0}],
        )
        token = self._entrar()["token"]
        respuesta = self._llamar(token, "ventas_repo", "anular_venta", [venta_id, self.lucia["id"], "se equivocó"])
        self.assertTrue(respuesta["ok"], respuesta)
        venta = ventas_repo.buscar_venta(venta_id)[0]
        self.assertEqual(venta["estado"], dominio.VENTA_ANULADA)
        self.assertEqual(venta["anulada_por"], self.admin["id"])

    def test_cambiar_la_clave_es_siempre_la_propia(self):
        token = self._entrar()["token"]
        respuesta = self._llamar(token, "usuarios_repo", "cambiar_clave", [self.lucia["id"], "1234", "nueva"])
        self.assertTrue(respuesta["ok"], respuesta)
        self.assertIsNotNone(usuarios_repo.autenticar_por_nombre("Administrador", "nueva"))
        self.assertIsNotNone(usuarios_repo.autenticar_por_nombre("LUCIA", "4321"))

    def test_los_rechazos_de_negocio_llegan_con_su_mensaje(self):
        token = self._entrar()["token"]
        respuesta = self._llamar(token, "usuarios_repo", "cambiar_clave", [self.admin["id"], "mal", "nueva"])
        self.assertEqual(respuesta["error"], {"tipo": "ValueError", "mensaje": "La clave actual no es correcta."})

    def test_cinco_claves_mal_seguidas_frenan_a_esa_pc_y_no_a_las_demas(self):
        for _ in range(servidor.MAX_INTENTOS - 1):
            self.assertEqual(self._entrar(clave="mal")["error"]["tipo"], "Clave")
        self.assertEqual(self._entrar(clave="mal")["error"]["tipo"], "Bloqueo")
        self.assertEqual(self._entrar()["error"]["tipo"], "Bloqueo")  # ni con la clave buena
        self.assertTrue(self._entrar(ip=OTRA_IP)["ok"])

        ahora = servidor._ahora()
        with mock.patch.object(servidor, "_ahora", return_value=ahora + servidor.BLOQUEO_MINUTOS * 60 + 1):
            self.assertTrue(self._entrar()["ok"])

    def test_mientras_se_comprueba_una_clave_esa_pc_no_puede_mandar_otra(self):
        # Sin esto, muchos intentos mandados juntos pasaban todos el control antes
        # de que se anotara la primera clave mal (revisión de seguridad, 2026-10-18).
        sigue = threading.Event()
        entrar_de_verdad = admin_remoto_repo.entrar

        def entrar_lento(*args):
            sigue.wait(5)
            return entrar_de_verdad(*args)

        respuestas = []
        with mock.patch.object(admin_remoto_repo, "entrar", side_effect=entrar_lento):
            hilo = threading.Thread(target=lambda: respuestas.append(self._entrar(clave="mal")))
            hilo.start()
            for _ in range(500):
                if IP in servidor._probando:
                    break
                threading.Event().wait(0.01)
            segunda = self._entrar(clave="otra")
            sigue.set()
            hilo.join(5)
        self.assertEqual(segunda["error"]["tipo"], "Bloqueo")
        self.assertIn("en curso", segunda["error"]["mensaje"])
        self.assertEqual(respuestas[0]["error"]["tipo"], "Clave")
        self.assertTrue(self._entrar()["ok"])  # terminada esa, se puede volver a probar

    def test_una_clave_mal_que_termina_tarde_no_borra_un_bloqueo(self):
        def mientras_tanto_se_bloqueo(*_args):
            servidor._intentos[IP] = (0, servidor._ahora() + servidor.BLOQUEO_MINUTOS * 60)
            return None

        with mock.patch.object(admin_remoto_repo, "entrar", side_effect=mientras_tanto_se_bloqueo):
            self.assertEqual(self._entrar(clave="mal")["error"]["tipo"], "Bloqueo")
        self.assertEqual(self._entrar()["error"]["tipo"], "Bloqueo")

    def test_muchas_claves_mal_desde_varias_pcs_frenan_la_entrada_para_todas(self):
        pcs = [f"10.0.1.{numero}" for numero in range(servidor.MAX_FALLIDOS_EN_TOTAL // servidor.MAX_INTENTOS)]
        for ip in pcs:
            for _ in range(servidor.MAX_INTENTOS):
                self._entrar(clave="mal", ip=ip)
        respuesta = self._entrar(ip="10.0.2.1")
        self.assertEqual(respuesta["error"]["tipo"], "Bloqueo")
        self.assertIn("En el mostrador se sigue entrando normal", respuesta["error"]["mensaje"])

        ahora = servidor._ahora()
        with mock.patch.object(servidor, "_ahora", return_value=ahora + servidor.VENTANA_TOTAL_MINUTOS * 60 + 1):
            self.assertTrue(self._entrar(ip="10.0.2.1")["ok"])

    def test_la_sesion_vence_sin_uso_y_al_salir(self):
        token = self._entrar()["token"]
        ahora = servidor._ahora()
        with mock.patch.object(servidor, "_ahora", return_value=ahora + servidor.SESION_VENCE_MINUTOS * 60 + 1):
            self.assertEqual(self._llamar(token, "usuarios_repo", "listar_usuarios")["error"]["tipo"], "Sesion")

        token = self._entrar()["token"]
        self._pedir("salir", {"token": token})
        self.assertEqual(self._llamar(token, "usuarios_repo", "listar_usuarios")["error"]["tipo"], "Sesion")

    def test_un_pedido_roto_no_rompe_nada(self):
        self.assertEqual(servidor.atender("/admin/hola", b"esto no es json", IP)[0], 400)
        self.assertEqual(self._pedir("no_existe", {})[0], 404)
        token = self._entrar()["token"]
        respuesta = self._llamar(token, "usuarios_repo", "obtener_usuario", [1, 2, 3])
        self.assertEqual(respuesta["error"]["tipo"], "Pedido")

    def test_un_fallo_inesperado_queda_en_el_log_sin_la_clave(self):
        with mock.patch.object(admin_remoto_repo, "entrar", side_effect=RuntimeError("se cortó la luz")):
            status, respuesta = self._pedir(
                "entrar", {"huella": lista_blanca.huella(), "nombre": "Administrador", "clave": "secreta"}
            )
        self.assertEqual((status, respuesta["error"]["tipo"]), (500, "Interno"))
        log = Path(database.DATA_DIR, "errores.log").read_text(encoding="utf-8")
        self.assertIn("se cortó la luz", log)
        self.assertNotIn("secreta", log)


class TestPorLaRed(_ConServidor):
    """El ida y vuelta de verdad, por HTTP, con el servidor de red de siempre."""

    def setUp(self):
        super().setUp()
        self.servidor_http = ThreadingHTTPServer(("127.0.0.1", 0), servidor_red._ManejadorEstado)
        threading.Thread(target=self.servidor_http.serve_forever, daemon=True).start()
        self.addCleanup(self.servidor_http.server_close)
        self.addCleanup(self.servidor_http.shutdown)
        self.puerto = self.servidor_http.server_address[1]

    def test_entrar_y_pedir_por_la_red(self):
        conexion = cliente.conectar("127.0.0.1", self.puerto)
        self.assertEqual(conexion.nombres_para_entrar(), ["Administrador"])
        self.assertIsNone(conexion.entrar("Administrador", "mal"))
        usuario = conexion.entrar("Administrador", "1234")
        self.assertEqual(usuario["nombre"], "Administrador")

        estaciones = conexion.llamar("pcs_repo", "ips_asentadas_repetidas", (), {})
        self.assertEqual(estaciones, set())
        with self.assertRaises(ValueError) as error:
            conexion.llamar("usuarios_repo", "cambiar_clave", (usuario["id"], "mal", "x"), {})
        self.assertEqual(str(error.exception), "La clave actual no es correcta.")
        with self.assertRaises(PermissionError):
            conexion.llamar("ventas_repo", "confirmar_venta", (1, [], []), {})

        conexion.salir()
        self.assertFalse(conexion.adentro)

    def test_las_pcs_del_cyber_siguen_necesitando_su_clave(self):
        import urllib.error
        import urllib.request
        with self.assertRaises(urllib.error.HTTPError) as error:
            urllib.request.urlopen(f"http://127.0.0.1:{self.puerto}/estado?estacion=PC1", timeout=5)
        self.assertEqual(error.exception.code, 403)

    def test_con_la_entrada_apagada_o_con_otro_programa_avisa(self):
        admin_remoto_repo.activar(self.admin["id"], False)
        with self.assertRaises(PermissionError) as error:
            cliente.conectar("127.0.0.1", self.puerto)
        self.assertIn("apagada", str(error.exception))

        admin_remoto_repo.activar(self.admin["id"], True)
        with self.assertRaises(PermissionError) as error:
            cliente.conectar("127.0.0.1", self.puerto, huella="la de otro programa")
        self.assertIn("no es el mismo", str(error.exception))

    def test_sin_mostrador_avisa_que_no_lo_encuentra(self):
        enchufe = socket.socket()
        enchufe.bind(("127.0.0.1", 0))
        puerto_libre = enchufe.getsockname()[1]
        enchufe.close()
        with self.assertRaises(cliente.SinConexion) as error:
            cliente.conectar("127.0.0.1", puerto_libre)
        self.assertIn("No encuentro el CyberBIOS del mostrador", str(error.exception))


# ---------------------------------------------------------------------------
# Las pantallas solo piden lo que está en la lista
# ---------------------------------------------------------------------------

# (archivo, clases que se abren desde otra PC; None = el archivo entero)
_PANTALLAS_DE_OTRA_PC = [
    ("ui/articulos_window.py", None),
    ("ui/articulos_tabla.py", None),
    ("ui/ordenar_stock_window.py", None),
    ("ui/buscar_articulo.py", None),
    ("ui/compras_window.py", None),
    ("ui/consulta_ventas_window.py", None),
    ("ui/detalle_venta.py", None),
    ("ui/reportes_window.py", None),
    ("ui/reportes_resumen_dia.py", None),
    ("ui/reportes_detalle_dia.py", None),
    ("ui/reportes_operador.py", None),
    ("ui/reportes_pcstream.py", None),
    ("ui/control_cierres_window.py", None),
    ("ui/tarjeta_cierre.py", None),
    ("ui/caja_window.py", {"CajaWindow", "_PantallaDeCaja"}),
    ("ui/usuarios_window.py", None),
    ("ui/accesos_admin_window.py", None),
    ("ui/login_window.py", None),
    ("ui/tramites_window.py", {"DialogoTramite", "DialogoGestionTramites"}),
    ("control_pcs/ui/accesos_admin_pc_tab.py", None),
    ("control_pcs/ui/pcs_gestion_dialogos.py", None),
    ("control_pcs/ui/pcs_filtro_dialogo.py", None),
    ("control_pcs/ui/pcs_fondo_dialogo.py", None),
    ("control_pcs/ui/miembros_window.py", {"DialogoTramosTarifaMiembro", "DialogoBonoMiembro",
                                           "DialogoGestionBonosMiembro"}),
]

# Lo que las pantallas usan de un repo sin ir a la base (se queda en esta PC), y
# lo que la copia remota resuelve aparte (la pantalla de ingreso).
_SE_USAN_SIN_IR_AL_MOSTRADOR = {
    ("usuarios_repo", "tiene_permiso"),
    ("playstation_repo", "AdministradorDeBonos"),
    ("usuarios_repo", "autenticar_por_nombre"),
}


class TestLasPantallasSoloPidenLoQueEstaEnLaLista(unittest.TestCase):
    def test_cada_funcion_de_un_repo_que_usan_esta_en_la_lista(self):
        faltan = []
        for archivo, clases in _PANTALLAS_DE_OTRA_PC:
            arbol = ast.parse((RAIZ / archivo).read_text(encoding="utf-8"))
            nodos = [arbol] if clases is None else [
                nodo for nodo in arbol.body if isinstance(nodo, ast.ClassDef) and nodo.name in clases
            ]
            if clases is not None:
                self.assertEqual({nodo.name for nodo in nodos}, clases, archivo)
            for nodo in nodos:
                for uso in ast.walk(nodo):
                    if not (isinstance(uso, ast.Attribute) and isinstance(uso.value, ast.Name)):
                        continue
                    repo, nombre = uso.value.id, uso.attr
                    if repo not in lista_blanca.nombres_de_modulos() or nombre.isupper():
                        continue  # no es un repo, o es una constante (ESTADO_CERRADO, ANCHO_MAXIMO...)
                    if lista_blanca.permitida(repo, nombre) or (repo, nombre) in _SE_USAN_SIN_IR_AL_MOSTRADOR:
                        continue
                    faltan.append(f"{archivo}: {repo}.{nombre}")
        self.assertEqual(faltan, [], "Sumalas a admin_remoto/lista_blanca.py (o sacá la pantalla de la otra PC)")

    def test_ninguna_pantalla_se_trae_una_funcion_suelta_de_un_repo(self):
        # La copia remota reemplaza las funciones EN su módulo: una función
        # traída suelta (`from repositories.x import f`) seguiría yendo a la base.
        sueltas = []
        for carpeta in ("ui", "control_pcs/ui"):
            for archivo in (RAIZ / carpeta).glob("*.py"):
                for nodo in ast.walk(ast.parse(archivo.read_text(encoding="utf-8"))):
                    if isinstance(nodo, ast.ImportFrom) and nodo.module and ".repositories." in f".{nodo.module}.":
                        if nodo.module.split(".")[-1].endswith("_repo"):
                            sueltas.append(f"{archivo.name}: from {nodo.module} import ...")
        self.assertEqual(sueltas, [])

    def test_cada_actor_es_un_parametro_de_su_funcion(self):
        import inspect
        for (repo, nombre), actor in lista_blanca.ACTOR.items():
            self.assertTrue(lista_blanca.permitida(repo, nombre), (repo, nombre))
            self.assertIn(actor, inspect.signature(lista_blanca.funcion(repo, nombre)).parameters, (repo, nombre))

    def test_vender_cobrar_y_cerrar_no_estan_en_la_lista(self):
        for repo, nombre in [
            ("ventas_repo", "confirmar_venta"), ("ventas_repo", "registrar_venta_sin_detalle"),
            ("turnos_repo", "cerrar_turno"), ("pcs_repo", "asignar_bono"), ("pcs_repo", "finalizar_sesion"),
            ("playstation_repo", "vender_bono"), ("miembros_repo", "cargar_saldo_por_monto"),
            ("relevo_repo", "cierre_forzoso_si_corresponde"), ("relevo_repo", "abrir_caja"),
            ("tramites_repo", "registrar_tramite"),
        ]:
            self.assertFalse(lista_blanca.permitida(repo, nombre), (repo, nombre))


# ---------------------------------------------------------------------------
# Una copia remota de verdad contra un mostrador de prueba
# ---------------------------------------------------------------------------

class TestCopiaRemota(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._carpeta_mostrador = tempfile.TemporaryDirectory()
        cls._carpeta_local = tempfile.TemporaryDirectory()
        cls.mostrador = subprocess.Popen(
            [sys.executable, str(RAIZ / "tests" / "mostrador_de_prueba.py"), cls._carpeta_mostrador.name],
            cwd=str(RAIZ), stdin=subprocess.PIPE, stdout=subprocess.PIPE, text=True,
        )
        puerto = int(cls.mostrador.stdout.readline())
        cls.ruta_base_mostrador = os.path.join(cls._carpeta_mostrador.name, "kiosko_prueba.db")

        with mock.patch.object(cliente, "_carpeta_local", return_value=cls._carpeta_local.name):
            cls.conexion = cliente.conectar("127.0.0.1", puerto)
            cliente.instalar(cls.conexion)
        cls.usuario = usuarios_repo.autenticar_por_nombre("Administrador", mostrador_de_prueba.CLAVE_ADMIN)

    @classmethod
    def tearDownClass(cls):
        cliente.desinstalar()
        cls.mostrador.stdin.close()
        cls.mostrador.wait(timeout=10)
        cls.mostrador.stdout.close()
        cls._carpeta_mostrador.cleanup()
        cls._carpeta_local.cleanup()

    def _base_del_mostrador(self):
        conexion = sqlite3.connect(f"file:{self.ruta_base_mostrador}?mode=ro", uri=True)
        self.addCleanup(conexion.close)
        conexion.row_factory = sqlite3.Row
        return conexion

    def test_entro_el_administrador(self):
        self.assertTrue(modo.es_copia_remota())
        self.assertEqual(self.usuario["nombre"], "Administrador")
        self.assertEqual(self.conexion.nombres_para_entrar(), ["Administrador"])
        # La pantalla de ingreso ya no ve la lista de antes de entrar: con la sesión
        # abierta, listar_usuarios es la de siempre (todos los usuarios del mostrador).
        self.assertEqual(sorted(u["nombre"] for u in usuarios_repo.listar_usuarios()), ["Administrador", "LUCIA"])

    def test_entrar_y_cerrar_sesion_como_lo_hace_el_dueño(self):
        import main
        # Al final, la sesión de la clase queda abierta como antes (las demás
        # pruebas la usan).
        self.addCleanup(self.conexion.entrar, "Administrador", mostrador_de_prueba.CLAVE_ADMIN)
        with mock.patch.object(main, "resolver_caja_al_entrar") as caja:
            aplicacion = main.Aplicacion(self.conexion)
            login = aplicacion.ventana_login
            self.addCleanup(login.deleteLater)
            self.assertEqual([login.combo_nombre.itemText(i) for i in range(login.combo_nombre.count())],
                             ["Administrador"])
            login.campo_clave.setText(mostrador_de_prueba.CLAVE_ADMIN)
            login._intentar_ingresar()

            principal = aplicacion.ventana_principal
            self.assertIsNotNone(principal)
            self.addCleanup(principal.deleteLater)
            self.assertIn("desde otra PC", principal.windowTitle())
            caja.assert_not_called()  # desde otra PC no se abre ni se recibe ninguna caja

            principal._cerrar_sesion()
            self.addCleanup(aplicacion.ventana_login.deleteLater)
        self.assertFalse(self.conexion.adentro)
        with self.assertRaises(PermissionError):
            usuarios_repo.obtener_usuario(1)

    def test_esta_copia_no_tiene_base_propia(self):
        with self.assertRaises(PermissionError):
            ventas_repo.confirmar_venta(self.usuario["id"], [], [])
        with self.assertRaises(PermissionError):
            with database.conexion_db():
                pass
        self.assertEqual([p for p in os.listdir(self._carpeta_local.name) if p.endswith(".db")], [])

    def test_un_precio_cambiado_desde_aca_queda_en_el_mostrador(self):
        from repositories import articulos_repo
        codigo = mostrador_de_prueba.CODIGO_ALFAJOR
        articulo = articulos_repo.buscar_por_codigo(codigo)
        articulos_repo.modificar_articulo(
            codigo, articulo["descripcion"], articulo["marca_id"], articulo["rubro_id"], 1250.0,
            articulo["precio_compra"], articulo["stock_minimo"],
        )
        self.assertEqual(articulos_repo.buscar_por_codigo(codigo)["precio_venta"], 1250.0)
        fila = self._base_del_mostrador().execute(
            "SELECT precio_venta FROM articulos WHERE codigo = ?", (codigo,)
        ).fetchone()
        self.assertEqual(fila["precio_venta"], 1250.0)

    def test_una_compra_queda_a_nombre_del_que_entro(self):
        from repositories import compras_repo
        codigo = mostrador_de_prueba.CODIGO_ALFAJOR
        antes = self._base_del_mostrador().execute("SELECT stock FROM articulos WHERE codigo = ?", (codigo,)).fetchone()
        compras_repo.registrar_compra(99999, [{"codigo": codigo, "cantidad": 10, "costo_unitario": 650.0}])
        base = self._base_del_mostrador()
        compra = base.execute("SELECT usuario_id FROM compras ORDER BY id DESC LIMIT 1").fetchone()
        despues = base.execute("SELECT stock FROM articulos WHERE codigo = ?", (codigo,)).fetchone()
        self.assertEqual(compra["usuario_id"], self.usuario["id"])
        self.assertEqual(despues["stock"], antes["stock"] + 10)

    def test_ordenar_stock_desde_aca_queda_en_el_mostrador_a_nombre_del_que_entro(self):
        from repositories import articulos_repo
        codigo = mostrador_de_prueba.CODIGO_ALFAJOR
        with self.assertRaises(PermissionError):
            articulos_repo.ajustar_stock(99999, codigo, 50, "otra")
        articulos_repo.ajustar_stock(99999, codigo, 50, mostrador_de_prueba.CLAVE_ORDENAR_STOCK)

        base = self._base_del_mostrador()
        stock = base.execute("SELECT stock FROM articulos WHERE codigo = ?", (codigo,)).fetchone()
        ajuste = base.execute("SELECT usuario_id, stock_nuevo FROM ajustes_stock ORDER BY id DESC").fetchone()
        self.assertEqual(stock["stock"], 50)
        self.assertEqual((ajuste["usuario_id"], ajuste["stock_nuevo"]), (self.usuario["id"], 50))

    def test_anular_una_venta_y_cargar_el_sobre(self):
        from repositories import turnos_repo
        venta = ventas_repo.listar_ventas_recientes(1)[0]
        ventas_repo.anular_venta(venta["id"], 99999, "prueba desde otra PC")
        cierre = turnos_repo.listar_cierres()[0]
        turnos_repo.verificar_cierre(cierre["id"], cierre["monto_a_retirar"], 99999)

        base = self._base_del_mostrador()
        anulada = base.execute("SELECT estado, anulada_por FROM ventas WHERE id = ?", (venta["id"],)).fetchone()
        verificacion = base.execute("SELECT verificado_por FROM verificaciones_cierre").fetchone()
        self.assertEqual((anulada["estado"], anulada["anulada_por"]), (dominio.VENTA_ANULADA, self.usuario["id"]))
        self.assertEqual(verificacion["verificado_por"], self.usuario["id"])

    def test_el_fondo_de_las_pcs_viaja_como_imagen(self):
        from control_pcs.repositories import fondo_repo
        jpeg = b"\xff\xd8\xff\xe0" + bytes(range(256)) * 4
        version = fondo_repo.guardar_jpeg(jpeg)
        self.assertEqual(fondo_repo.obtener(), (jpeg, version))
        self.assertTrue(os.path.exists(os.path.join(self._carpeta_mostrador.name, "fondo_bloqueo.jpg")))
        self.assertTrue(fondo_repo.quitar())

    def test_las_pantallas_de_administracion_abren_sin_errores(self):
        from control_pcs.ui.accesos_admin_pc_tab import PestañaAccesosAdminPc  # noqa: F401 (la abre Accesos)
        from control_pcs.ui.miembros_window import DialogoGestionBonosMiembro, DialogoTramosTarifaMiembro
        from control_pcs.ui.pcs_filtro_dialogo import DialogoFiltroPalabras
        from control_pcs.ui.pcs_fondo_dialogo import DialogoFondoPantalla
        from control_pcs.ui.pcs_gestion_dialogos import (
            DialogoGestionBonos, DialogoGestionBonosPcstream, DialogoGestionBonosPlaystation,
            DialogoGestionEstaciones,
        )
        from ui.accesos_admin_window import AccesosAdminWindow
        from ui.articulos_window import ArticulosWindow
        from ui.caja_window import CajaWindow, ControlCierresWindow
        from ui.compras_window import ComprasWindow
        from ui.consulta_ventas_window import ConsultaVentasWindow
        from ui.login_window import LoginWindow
        from ui.main_window import AdministrarKioskoWindow, ConfiguracionAdminWindow, MainWindow
        from ui.ordenar_stock_window import OrdenarStockWindow
        from ui.reportes_window import ReportesWindow
        from ui.tramites_window import DialogoGestionTramites
        from ui.usuarios_window import DialogoCambiarClave, UsuariosWindow
        import ui.utils

        errores = []
        with mock.patch.object(ui.utils, "mostrar_error", lambda _p, titulo, texto: errores.append(texto)), \
                mock.patch.object(ui.utils, "_mostrar_error_seguro", lambda _p, error: errores.append(repr(error))), \
                mock.patch.object(ui.utils, "registrar_error", lambda error, *_: errores.append(repr(error))):
            ventana = MainWindow(self.usuario, al_cerrar_sesion=lambda: None)
            self.addCleanup(ventana.deleteLater)
            barra = [boton.text() for boton in ventana.findChildren(QPushButton)]
            self.assertIsNone(ventana.panel_pcs)
            self.assertIsNone(ventana.boton_cierre_turno)
            self.assertFalse(any(
                "Vender" in texto or "Impresiones" in texto or "Trámites" in texto or "Miembros" in texto
                for texto in barra
            ))
            self.assertIn("Sin caja abierta", ventana.etiqueta_caja.text())

            pantallas = [
                LoginWindow(lambda _u: None),
                AdministrarKioskoWindow(self.usuario, True, ventana),
                ConfiguracionAdminWindow(self.usuario, ventana),
                ArticulosWindow(ventana), ComprasWindow(self.usuario, ventana),
                ConsultaVentasWindow(self.usuario, ventana), ReportesWindow(ventana),
                ControlCierresWindow(self.usuario, ventana), UsuariosWindow(self.usuario, ventana),
                DialogoCambiarClave(self.usuario, ventana), CajaWindow(ventana),
                DialogoGestionEstaciones(self.usuario, ventana), DialogoGestionBonos(ventana),
                DialogoGestionBonosPlaystation(self.usuario, ventana), DialogoGestionBonosPcstream(ventana),
                DialogoTramosTarifaMiembro(ventana), DialogoGestionBonosMiembro(ventana),
                DialogoGestionTramites(ventana), AccesosAdminWindow(ventana),
                DialogoFiltroPalabras(ventana), DialogoFondoPantalla(ventana),
                ArticulosWindow(ventana, self.usuario),
                OrdenarStockWindow(ventana, self.usuario["id"], mostrador_de_prueba.CLAVE_ORDENAR_STOCK),
            ]
            for pantalla in pantallas:
                self.addCleanup(pantalla.deleteLater)
        self.assertEqual(errores, [])

        login, _kiosko, configuracion = pantallas[:3]
        estaciones, usuarios = pantallas[11], pantallas[8]

        def textos(pantalla, tipo=QPushButton):
            return [widget.text() for widget in pantalla.findChildren(tipo)]

        # Lo que solo se hace en el mostrador no aparece.
        self.assertFalse(any("LIMPIAR" in texto or "OTRA PC" in texto for texto in textos(configuracion)))
        self.assertFalse(any("Actualizar el Cliente PC" in texto for texto in textos(estaciones)))
        self.assertNotIn("Copia de Seguridad", textos(usuarios))
        self.assertTrue(any("Entra solo un Administrador" in texto for texto in textos(login, QLabel)))


if __name__ == "__main__":
    unittest.main()
