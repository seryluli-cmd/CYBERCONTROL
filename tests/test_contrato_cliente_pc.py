"""
tests/test_contrato_cliente_pc.py
==================================
Lo que se hablan el mostrador y el Cliente PC de las ~40 PCs, por GET /estado
(revisión general del 2026-11-16, mejora 4). El Cliente PC está en otro repo
(la carpeta "CLIENTE PC", al lado de esta): un cambio acá que lo rompe no lo ve
ninguna prueba de allá, y el error aparece en todas las PCs a la vez, con gente
jugando.

- 4a, el contrato: GET /estado trae los 11 datos que lee el Cliente PC
  (`red_kiosko.consultar_estado`). Si alguien renombra `quien`, el socio deja de
  ver "Cerrar sesión"; si renombra `clave_admin`, las PCs se quedan con la clave
  vieja del panel admin. Ninguna de las dos cosas avisa nada. Si la carpeta
  CLIENTE PC está al lado, además se lee la respuesta con SU código y se sacan de
  SU código los nombres que lee (como la prueba de la firma de versiones, en
  test_actualizacion_cliente.py). Sin la carpeta, esas dos se saltean.
- 4b: una consulta sin novedades toma el permiso de escritura de la base UNA
  vez (la "última conexión" de la PC). Antes eran 4: temperatura, mantenimiento
  y la cola de comandos lo tomaban sin cambiar nada, y una venta justo en ese
  instante esperaba.
- 4c: una respuesta que no llega (la PC se cansó de esperar) queda en
  errores.log. Antes no quedaba ningún rastro: el .exe no tiene consola.

    python -m unittest discover -s tests -p test_contrato_cliente_pc.py
"""

import ast
import http.client
import importlib.util
import json
import sqlite3
import sys
import threading
import time
import types
import unittest
from contextlib import contextmanager
from datetime import datetime, timedelta
from http.server import ThreadingHTTPServer
from pathlib import Path
from unittest import mock

import database
import dominio
import servidor_red
from repositories import usuarios_repo
from control_pcs.repositories import (
    clientes_repo, comandos_pc_repo, filtro_palabras_repo, mantenimiento_pc_repo, miembros_repo, pcs_repo,
    reservas_repo, temperatura_pc_repo,
)
from base import BaseConBaseTemporal

# Lo que lee el Cliente PC de GET /estado (CLIENTE PC/red_kiosko.py, consultar_estado). Si el Cliente
# PC empieza a leer otro, va acá y el mostrador lo tiene que mandar.
CAMPOS_QUE_LEE_EL_CLIENTE_PC = (
    "bloqueada", "quien", "segundos_restantes", "sesion_id", "comando", "clave_admin",
    "fondo_version", "escritorio_version", "filtro_version", "cliente_version", "reserva",
)
CARPETA_CLIENTE_PC = Path(__file__).resolve().parents[2] / "CLIENTE PC"

# La clave de conexión real es fija y NO va en este repo (es público): se usa una de prueba.
CLAVE_DE_PRUEBA = "clave-de-prueba-de-los-clientes-pc"
CLAVE_ADMIN_DE_PRUEBA = "admin-de-prueba"
SOCIO = "Juan"
CLIENTE_DE_LA_RESERVA = "Lucía Gómez"


def _cargar(nombre: str, ruta: Path):
    especificacion = importlib.util.spec_from_file_location(nombre, ruta)
    modulo = importlib.util.module_from_spec(especificacion)
    especificacion.loader.exec_module(modulo)
    return modulo


def _red_kiosko_del_cliente_pc():
    """El red_kiosko.py de verdad del Cliente PC, o None si la carpeta no está al lado. Se carga
    con un nombre propio, para no mezclarse con los módulos de acá. De lo que importa, el número
    de versión es el de verdad; `configuracion` abre ventanas de tkinter y para consultar el
    estado no hace falta: va vacío."""
    ruta = CARPETA_CLIENTE_PC / "red_kiosko.py"
    if not ruta.exists():
        return None
    prestados = {
        "configuracion": types.ModuleType("configuracion"),
        "version_cliente": _cargar("version_cliente_del_cliente_pc", CARPETA_CLIENTE_PC / "version_cliente.py"),
    }
    anteriores = {nombre: sys.modules.get(nombre) for nombre in prestados}
    sys.modules.update(prestados)
    try:
        return _cargar("red_kiosko_del_cliente_pc", ruta)
    finally:
        for nombre, modulo in anteriores.items():
            if modulo is None:
                sys.modules.pop(nombre, None)
            else:
                sys.modules[nombre] = modulo


def _campos_que_lee(ruta: Path) -> set:
    """Los nombres que `consultar_estado` saca de la respuesta (`datos.get("x")` y `"x" in datos`),
    leídos del código del Cliente PC sin correrlo."""
    arbol = ast.parse(ruta.read_text(encoding="utf-8"))
    funcion = next(nodo for nodo in ast.walk(arbol)
                   if isinstance(nodo, ast.FunctionDef) and nodo.name == "consultar_estado")
    campos = set()
    for nodo in ast.walk(funcion):
        if (isinstance(nodo, ast.Call) and isinstance(nodo.func, ast.Attribute) and nodo.func.attr == "get"
                and isinstance(nodo.func.value, ast.Name) and nodo.func.value.id == "datos"
                and nodo.args and isinstance(nodo.args[0], ast.Constant)):
            campos.add(nodo.args[0].value)
        if (isinstance(nodo, ast.Compare) and isinstance(nodo.left, ast.Constant)
                and isinstance(nodo.ops[0], ast.In)
                and isinstance(nodo.comparators[0], ast.Name) and nodo.comparators[0].id == "datos"):
            campos.add(nodo.left.value)
    return campos


@contextmanager
def _sentencias_de_la_base():
    """Junta todo lo que se le manda a la base mientras dura (de cualquier hilo, también del
    servidor). Cada "BEGIN" es una vez que se tomó el permiso de escritura."""
    sentencias = []
    original = database.get_connection

    def con_registro():
        conexion = original()
        conexion.set_trace_callback(sentencias.append)
        return conexion

    with mock.patch.object(database, "get_connection", con_registro):
        yield sentencias


@contextmanager
def _base_tomada_para_escribir():
    """Otra conexión con el permiso de escritura tomado, como una venta a mitad de grabarse, y una
    espera corta: lo que necesite escribir falla enseguida ("database is locked") en vez de
    esperar los 30 s de siempre. Leer se puede igual."""
    otra = sqlite3.connect(database.DB_PATH, isolation_level=None)
    otra.execute("BEGIN IMMEDIATE")
    try:
        with mock.patch.object(database, "ESPERA_BASE_OCUPADA_SEGUNDOS", 0.2):
            yield
    finally:
        otra.execute("ROLLBACK")
        otra.close()


class _ConServidor(BaseConBaseTemporal):
    """El servidor de red de verdad (el mismo manejador que levanta main.py) en un puerto libre,
    con una base que tiene un poco de todo:

    - PC1 con un socio adentro (entró desde su PC, con POST /login);
    - PC2 libre, RESERVADA (la reserva es en una hora) y con un MENSAJE esperando;
    - la clave del panel admin de las PCs puesta.
    """

    def setUp(self):
        super().setUp()
        parche = mock.patch.object(clientes_repo, "HUELLA_CLAVE_CLIENTES",
                                   clientes_repo.huella_de_clave(CLAVE_DE_PRUEBA))
        parche.start()
        self.addCleanup(parche.stop)
        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), servidor_red._ManejadorEstado)
        self._puerto = self._servidor.server_address[1]
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True)
        self._hilo.start()

        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        bono = pcs_repo.crear_bono("1 hora", 60, 1500.0)
        socio = miembros_repo.crear_miembro("juan", "clave123", SOCIO, "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 120 WHERE id = ?", (socio,))
        status, datos = self._pedir("POST", "/login", {"estacion": "PC1", "usuario": "juan", "clave": "clave123"})
        self.assertEqual((status, datos["ok"]), (200, True), datos)
        self.sesion_pc1 = pcs_repo.estado_de_estacion("PC1")["sesion"]["id"]
        self.hora_reserva = (datetime.now() + timedelta(hours=1)).replace(second=0, microsecond=0)
        reservas_repo.crear_reserva(
            self.ana, CLIENTE_DE_LA_RESERVA, "11 5555-4444", dominio.EQUIPO_RESERVA_PC, self.pc2, bono,
            self.hora_reserva, 1000.0, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0}],
        )
        self.mensaje = comandos_pc_repo.encolar_comando(self.pc2, comandos_pc_repo.TIPO_MENSAJE, "Hola")
        clientes_repo.establecer_clave_admin_pcs(CLAVE_ADMIN_DE_PRUEBA)

    def tearDown(self):
        self._servidor.shutdown()
        self._hilo.join(timeout=5)
        self._servidor.server_close()
        super().tearDown()

    def _pedir(self, metodo: str, ruta: str, cuerpo: dict = None):
        conexion = http.client.HTTPConnection("127.0.0.1", self._puerto, timeout=5)
        try:
            conexion.request(
                metodo, ruta, body=json.dumps(cuerpo) if cuerpo is not None else None,
                headers={"Authorization": "Bearer " + CLAVE_DE_PRUEBA, "Content-Type": "application/json"},
            )
            respuesta = conexion.getresponse()
            return respuesta.status, json.loads(respuesta.read().decode("utf-8"))
        finally:
            conexion.close()

    def _estado(self, consulta: str):
        status, datos = self._pedir("GET", "/estado?" + consulta)
        self.assertEqual(status, 200)
        return datos

    def _errores_log(self) -> str:
        ruta = Path(database.DATA_DIR) / "errores.log"
        return ruta.read_text(encoding="utf-8") if ruta.exists() else ""


class TestContratoConElClientePc(_ConServidor):
    """4a: lo que manda el mostrador es lo que lee el Cliente PC."""

    def test_el_estado_trae_los_11_datos_que_lee_el_cliente_pc(self):
        pc1 = self._estado("estacion=PC1")
        pc2 = self._estado("estacion=PC2")

        for nombre, datos in (("PC1", pc1), ("PC2", pc2)):
            for campo in CAMPOS_QUE_LEE_EL_CLIENTE_PC:
                self.assertIn(campo, datos, f"GET /estado de {nombre} no trae '{campo}', que lee el Cliente PC")
        # PC1: el socio adentro. Sin `quien`, en su PC no aparece "Cerrar sesión".
        self.assertFalse(pc1["bloqueada"])
        self.assertEqual(pc1["quien"], SOCIO)
        self.assertGreater(pc1["segundos_restantes"], 0)
        self.assertEqual(pc1["sesion_id"], self.sesion_pc1)
        self.assertIsNone(pc1["comando"])
        self.assertIsNone(pc1["reserva"])
        # PC2: libre, con su mensaje y el cartel de la reserva.
        self.assertTrue(pc2["bloqueada"])
        self.assertIsNone(pc2["quien"])
        self.assertIsNone(pc2["sesion_id"])
        self.assertEqual(pc2["comando"], {"id": self.mensaje, "tipo": comandos_pc_repo.TIPO_MENSAJE, "payload": "Hola"})
        self.assertEqual(pc2["reserva"], {"cliente": CLIENTE_DE_LA_RESERVA,
                                          "inicio": self.hora_reserva.isoformat(timespec="seconds")})
        # Lo de todas las PCs.
        for datos in (pc1, pc2):
            self.assertEqual(datos["clave_admin"], CLAVE_ADMIN_DE_PRUEBA)
            self.assertEqual(datos["fondo_version"], "")
            self.assertEqual(datos["escritorio_version"], "")
            self.assertEqual(datos["filtro_version"], filtro_palabras_repo.version_actual())
            self.assertIsNone(datos["cliente_version"])  # no hay ninguna versión cargada

    def test_el_cliente_pc_de_verdad_lee_lo_que_manda_el_mostrador(self):
        red_kiosko = _red_kiosko_del_cliente_pc()
        if red_kiosko is None:
            self.skipTest("No está la carpeta CLIENTE PC al lado")

        def consultar(estacion, **extra):
            config = {"nombre_estacion": estacion, "servidor_ip": "127.0.0.1", "servidor_puerto": self._puerto,
                      "clave_clientes": CLAVE_DE_PRUEBA}
            resultado = red_kiosko.consultar_estado(config, **extra)
            self.assertIsNone(resultado["error"])
            return resultado

        pc1 = consultar("PC1", mantenimiento=7)
        pc2 = consultar("PC2")

        self.assertFalse(pc1["bloqueada"])
        self.assertEqual(pc1["quien"], SOCIO)
        self.assertGreater(pc1["segundos_restantes"], 0)
        self.assertEqual(pc1["sesion_id"], self.sesion_pc1)
        self.assertTrue(pc2["bloqueada"])
        self.assertEqual(pc2["comando"]["id"], self.mensaje)
        self.assertEqual(pc2["comando"]["tipo"], comandos_pc_repo.TIPO_MENSAJE)
        self.assertEqual(pc2["comando"]["payload"], "Hola")
        self.assertEqual(pc2["reserva"]["cliente"], CLIENTE_DE_LA_RESERVA)
        for resultado in (pc1, pc2):
            self.assertEqual(resultado["clave_admin"], CLAVE_ADMIN_DE_PRUEBA)
            self.assertEqual(resultado["fondo_version"], "")
            self.assertEqual(resultado["escritorio_version"], "")
            self.assertEqual(resultado["filtro_version"], filtro_palabras_repo.version_actual())
            self.assertTrue(resultado["cliente_version_informada"])
        # Y al revés: lo que manda la PC en la consulta lo entiende el mostrador.
        fila = pcs_repo.obtener_estacion(self.pc1)
        self.assertEqual(fila["mant_min"], 7)
        self.assertIsNotNone(fila["numero_version_cliente"])
        self.assertIsNotNone(fila["ultima_conexion"])

    def test_los_datos_que_lee_el_cliente_pc_son_los_de_la_lista(self):
        ruta = CARPETA_CLIENTE_PC / "red_kiosko.py"
        if not ruta.exists():
            self.skipTest("No está la carpeta CLIENTE PC al lado")
        self.assertEqual(
            _campos_que_lee(ruta), set(CAMPOS_QUE_LEE_EL_CLIENTE_PC),
            "El Cliente PC lee de GET /estado otros datos que los de CAMPOS_QUE_LEE_EL_CLIENTE_PC: "
            "actualizar la lista y que el mostrador los mande.",
        )


class TestEstadoSinEscriturasDeMas(_ConServidor):
    """4b: una consulta sin novedades no toma el permiso de escritura de la base para nada."""

    def test_una_consulta_sin_novedades_toma_el_permiso_de_escritura_una_sola_vez(self):
        consulta = "estacion=PC1&temp_cpu=55&temp_gpu=61&mant=7&encendida=3600"
        self._estado(consulta)  # la primera guarda la temperatura y el mantenimiento

        with _sentencias_de_la_base() as sentencias:
            self._estado(consulta)

        sentencias = [s.strip() for s in sentencias]
        escrituras = [s for s in sentencias if s.startswith("BEGIN")]
        cambios = [s for s in sentencias if s.startswith(("UPDATE", "INSERT", "DELETE"))]
        self.assertEqual(len(escrituras), 1, "\n".join(cambios))
        # La que queda es la "última conexión" (pcs_repo.registrar_conexion): el latido con que el
        # mosaico sabe que la PC sigue ahí.
        self.assertIn("ultima_conexion", cambios[0])

    def test_temperatura_y_mantenimiento_iguales_no_esperan_a_la_venta(self):
        temperatura_pc_repo.registrar(self.pc1, {"cpu": 55, "gpu": 61})
        mantenimiento_pc_repo.registrar(self.pc1, 7)
        fila = pcs_repo.obtener_estacion(self.pc1)

        with _base_tomada_para_escribir():
            self.assertFalse(temperatura_pc_repo.registrar_si_cambio(fila, {"cpu": 55, "gpu": 61}))
            self.assertFalse(mantenimiento_pc_repo.registrar_si_cambio(fila, 7))

        self.assertTrue(temperatura_pc_repo.registrar_si_cambio(fila, {"cpu": 56, "gpu": None}))
        self.assertTrue(mantenimiento_pc_repo.registrar_si_cambio(fila, None))
        fila = pcs_repo.obtener_estacion(self.pc1)
        self.assertEqual((fila["temp_cpu"], fila["temp_gpu"], fila["mant_min"]), (56, None, None))

    def test_buscar_el_comando_sin_nada_que_vencer_no_espera_a_la_venta(self):
        with _base_tomada_para_escribir():
            self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1, 3600))
            self.assertEqual(comandos_pc_repo.proximo_comando_pendiente(self.pc2, 3600)["id"], self.mensaje)

    def test_lo_que_hay_que_vencer_se_sigue_venciendo(self):
        reiniciar = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_REINICIAR)
        hace_rato = (datetime.now() - timedelta(minutes=comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO + 1))
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE comandos_pc SET fecha_creacion = ? WHERE id = ?",
                             (hace_rato.isoformat(timespec="seconds"), reiniciar))

        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1, 3600))
        fila = comandos_pc_repo.obtener_comando(reiniciar)
        self.assertEqual(fila["estado"], dominio.ESTADO_COMANDO_ENTREGADO)
        self.assertEqual(fila["resultado"], comandos_pc_repo.RESULTADO_REINICIO_VENCIDO)


class TestRespuestaQueNoLlega(_ConServidor):
    """4c: si la PC se cansa de esperar y corta, queda anotado en errores.log."""

    def _esperar_en_el_log(self, texto: str, segundos: float = 3) -> str:
        limite = time.monotonic() + segundos
        while time.monotonic() < limite:
            log = self._errores_log()
            if texto in log:
                return log
            time.sleep(0.02)
        self.fail(f"errores.log no dice '{texto}':\n{self._errores_log()}")

    def test_la_respuesta_que_no_llega_queda_en_errores_log_con_el_comando(self):
        la_pc_corto = threading.Event()
        version_de_verdad = filtro_palabras_repo.version_actual

        def version_lenta():
            la_pc_corto.wait(5)  # el mostrador tarda más de lo que espera la PC
            return version_de_verdad()

        with mock.patch.object(filtro_palabras_repo, "version_actual", version_lenta):
            conexion = http.client.HTTPConnection("127.0.0.1", self._puerto, timeout=0.5)
            try:
                conexion.request("GET", "/estado?estacion=PC2", headers={"Authorization": "Bearer " + CLAVE_DE_PRUEBA})
                with self.assertRaises(TimeoutError):
                    conexion.getresponse()
            finally:
                conexion.close()
            la_pc_corto.set()
            log = self._esperar_en_el_log("no le llegó la respuesta")

        self.assertIn("/estado", log)
        self.assertIn("la PC PC2 (127.0.0.1)", log)
        self.assertIn(f"Iba el comando {self.mensaje} (MENSAJE)", log)
        # El comando ya había quedado como entregado: por eso el aviso dice que hay que volver a mandarlo.
        self.assertEqual(comandos_pc_repo.obtener_comando(self.mensaje)["estado"], dominio.ESTADO_COMANDO_ENTREGADO)

    def test_las_respuestas_que_llegan_no_anotan_nada(self):
        self._estado("estacion=PC1")
        self._estado("estacion=PC2")
        self.assertNotIn("no le llegó la respuesta", self._errores_log())


if __name__ == "__main__":
    unittest.main()
