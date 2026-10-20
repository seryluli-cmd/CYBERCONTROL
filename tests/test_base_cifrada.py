"""
tests/test_base_cifrada.py
===========================
La base de datos va cifrada (pedido del dueño, 2026-10-19: que quien consiga el
archivo `data/kiosko.db` —de la PC, de una copia de seguridad, de un pendrive— no
pueda abrirlo con ningún programa). La clave vive dentro del .exe, no en el repo
(ver CLAUDE.md, "La base de datos va cifrada"); acá se prueba con claves al azar.

Lo que se vigila:
- una base nueva nace cifrada y sin la clave no se lee;
- una base común (la que ya tiene el dueño) se cifra sola al arrancar, SIN perder
  ni una fila ni un número automático, y deja una copia común de antes;
- si algo sale mal al cifrar, la base común queda como estaba;
- con la clave equivocada, o sin clave, el programa avisa en castellano;
- las copias de seguridad también salen cifradas;
- abrir una conexión sigue siendo rápido (clave cruda, no una frase: con una frase
  SQLCipher tarda ~100 ms POR CONEXIÓN y el programa abre una en cada consulta).
"""

import hashlib
import os
import secrets
import sqlite3 as sqlite3_comun
import tempfile
import time
import unittest
from unittest import mock

import database
import dominio
from motor_sql import PUEDE_CIFRAR, sqlite3

import mostrador_de_prueba

ENCABEZADO_COMUN = b"SQLite format 3\x00"


def _es_comun(ruta) -> bool:
    with open(ruta, "rb") as archivo:
        return archivo.read(16) == ENCABEZADO_COMUN


def _bytes_de(ruta) -> bytes:
    with open(ruta, "rb") as archivo:
        return archivo.read()


def _contenido_de_todo(ruta, clave=None) -> dict:
    """Cada tabla con TODAS sus filas (en orden), más sqlite_sequence por nombre."""
    conexion = sqlite3.connect(ruta)
    try:
        if clave:
            conexion.execute(f"PRAGMA key = \"x'{clave}'\"")
        tablas = [fila[0] for fila in conexion.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
        )]
        todo = {t: [tuple(f) for f in conexion.execute(f'SELECT rowid, * FROM "{t}" ORDER BY rowid')] for t in tablas}
        todo["sqlite_sequence"] = sorted(tuple(f) for f in conexion.execute("SELECT name, seq FROM sqlite_sequence"))
        todo["esquema"] = sorted(tuple(f) for f in conexion.execute("SELECT type, name, sql FROM sqlite_master"))
        return todo
    finally:
        conexion.close()


@unittest.skipUnless(PUEDE_CIFRAR, "falta instalar sqlcipher3")
class _ConCarpetaTemporal(unittest.TestCase):
    """Una carpeta de datos temporal, y SIN clave hasta que la prueba la pone."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        for nombre, valor in (
            ("DATA_DIR", self._tmp.name),
            ("DB_PATH", os.path.join(self._tmp.name, "kiosko_test.db")),
            ("CLAVE_HEX", None),
        ):
            parche = mock.patch.object(database, nombre, valor)
            parche.start()
            self.addCleanup(parche.stop)

    def carpeta_de_copias(self):
        return os.path.join(database.DATA_DIR, "backups")

    def copias_de_antes_de_cifrar(self):
        carpeta = self.carpeta_de_copias()
        if not os.path.isdir(carpeta):
            return []
        return sorted(n for n in os.listdir(carpeta) if n.startswith("antes_de_cifrar_"))


class TestBaseNueva(_ConCarpetaTemporal):
    def test_una_base_nueva_nace_cifrada(self):
        database.CLAVE_HEX = secrets.token_hex(32)
        database.inicializar_base_de_datos()

        self.assertFalse(_es_comun(database.DB_PATH))
        with database.conexion_db() as conexion:
            self.assertGreaterEqual(conexion.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 1)

    def test_los_datos_no_se_ven_en_el_archivo(self):
        from repositories import usuarios_repo

        database.CLAVE_HEX = secrets.token_hex(32)
        database.inicializar_base_de_datos()
        usuarios_repo.crear_usuario("NOMBRE_RARISIMO_QWERTY", "1234", dominio.ROL_EMPLEADA)

        self.assertNotIn(b"NOMBRE_RARISIMO_QWERTY", _bytes_de(database.DB_PATH))

    def test_la_misma_prueba_sin_clave_si_se_ve(self):
        """El control de la prueba de arriba: en una base común el nombre SÍ aparece
        en el archivo, así que 'no se ve' de verdad es obra del cifrado."""
        from repositories import usuarios_repo

        database.inicializar_base_de_datos()
        usuarios_repo.crear_usuario("NOMBRE_RARISIMO_QWERTY", "1234", dominio.ROL_EMPLEADA)

        self.assertIn(b"NOMBRE_RARISIMO_QWERTY", _bytes_de(database.DB_PATH))

    def test_sin_la_clave_o_con_otra_no_se_puede_abrir(self):
        clave = secrets.token_hex(32)
        database.CLAVE_HEX = clave
        database.inicializar_base_de_datos()

        consulta = "SELECT COUNT(*) FROM sqlite_master"
        # sqlite3 común, sqlcipher3 sin clave, y sqlcipher3 con una clave que no es: ninguna lee.
        comun = sqlite3_comun.connect(database.DB_PATH)
        sin_clave = sqlite3.connect(database.DB_PATH)
        otra = sqlite3.connect(database.DB_PATH)
        otra.execute(f"PRAGMA key = \"x'{secrets.token_hex(32)}'\"")
        for conexion, modulo in ((comun, sqlite3_comun), (sin_clave, sqlite3), (otra, sqlite3)):
            with self.subTest(conexion=conexion):
                with self.assertRaises(modulo.DatabaseError):
                    conexion.execute(consulta).fetchone()
            conexion.close()
        # y con la clave buena sí
        buena = database.abrir_archivo(database.DB_PATH)
        self.assertGreater(buena.execute(consulta).fetchone()[0], 10)
        buena.close()

    def test_un_archivo_vacio_no_molesta(self):
        open(database.DB_PATH, "wb").close()
        database.CLAVE_HEX = secrets.token_hex(32)
        database.inicializar_base_de_datos()

        self.assertFalse(_es_comun(database.DB_PATH))


class TestCifrarUnaBaseComun(_ConCarpetaTemporal):
    """La base que ya tiene el dueño: común, con datos de verdad."""

    def setUp(self):
        super().setUp()
        # La base común, armada y con datos por el camino de siempre (sin clave).
        mostrador_de_prueba.preparar_base(self._tmp.name)
        self.assertTrue(_es_comun(database.DB_PATH))
        with database.conexion_db() as conexion:
            # Un hueco en un número automático: se creó el id 3 y se borró. SQLite se
            # acuerda de que el último fue el 3 (sqlite_sequence) y el próximo es el 4.
            for nombre in ("A", "B", "C"):
                conexion.execute("INSERT INTO bonos_tiempo (nombre, minutos, precio) VALUES (?, 30, 1000)", (nombre,))
            conexion.execute("DELETE FROM bonos_tiempo WHERE nombre = 'C'")
        self.antes = _contenido_de_todo(database.DB_PATH)
        self.bytes_antes = _bytes_de(database.DB_PATH)
        self.clave = secrets.token_hex(32)

    def cifrar(self):
        database.CLAVE_HEX = self.clave
        database.inicializar_base_de_datos()

    def test_se_cifra_sola_al_arrancar_y_no_pierde_nada(self):
        self.cifrar()

        self.assertFalse(_es_comun(database.DB_PATH))
        self.assertEqual(_contenido_de_todo(database.DB_PATH, self.clave), self.antes)

    def test_deja_una_copia_comun_de_antes(self):
        self.cifrar()

        copias = self.copias_de_antes_de_cifrar()
        self.assertEqual(len(copias), 1)
        ruta = os.path.join(self.carpeta_de_copias(), copias[0])
        self.assertTrue(_es_comun(ruta))
        self.assertEqual(_contenido_de_todo(ruta), self.antes)

    def test_los_numeros_automaticos_siguen_donde_estaban(self):
        self.cifrar()

        with database.conexion_db() as conexion:
            nuevo = conexion.execute(
                "INSERT INTO bonos_tiempo (nombre, minutos, precio) VALUES ('D', 30, 1000)"
            ).lastrowid
        self.assertEqual(nuevo, 4)  # no vuelve a usar el 3 que se borró

    def test_arrancar_otra_vez_no_vuelve_a_cifrar(self):
        self.cifrar()
        cifrada = _bytes_de(database.DB_PATH)

        database.inicializar_base_de_datos()

        self.assertEqual(len(self.copias_de_antes_de_cifrar()), 1)
        self.assertEqual(_contenido_de_todo(database.DB_PATH, self.clave), self.antes)
        self.assertTrue(len(cifrada) > 0)

    def test_si_la_verificacion_falla_la_base_comun_queda_como_estaba(self):
        database.CLAVE_HEX = self.clave
        with mock.patch.object(database, "_comprobar_que_quedo_igual", side_effect=database.ErrorDeCifrado("no coincide")):
            with self.assertRaises(database.ErrorDeCifrado):
                database.inicializar_base_de_datos()

        self.assertEqual(_bytes_de(database.DB_PATH), self.bytes_antes)
        self.assertFalse(os.path.exists(database.DB_PATH + ".cifrando"))

    def test_si_falla_al_exportar_la_base_comun_queda_como_estaba(self):
        database.CLAVE_HEX = self.clave
        with mock.patch.object(database, "_exportar_cifrada", side_effect=sqlite3.OperationalError("disco lleno")):
            with self.assertRaises(database.ErrorDeCifrado) as contexto:
                database.inicializar_base_de_datos()
        self.assertIn("disco lleno", str(contexto.exception))
        self.assertIn("quedó como estaba", str(contexto.exception))

        self.assertEqual(_bytes_de(database.DB_PATH), self.bytes_antes)
        self.assertFalse(os.path.exists(database.DB_PATH + ".cifrando"))

    def test_un_resto_de_un_intento_anterior_no_molesta(self):
        with open(database.DB_PATH + ".cifrando", "wb") as resto:
            resto.write(b"a medias")

        self.cifrar()

        self.assertEqual(_contenido_de_todo(database.DB_PATH, self.clave), self.antes)
        self.assertFalse(os.path.exists(database.DB_PATH + ".cifrando"))

    def test_la_verificacion_de_verdad_nota_una_fila_que_falta(self):
        """No alcanza con que la verificación exista: tiene que ver una diferencia."""
        self.cifrar()  # ya está cifrada
        copia = database.DB_PATH + ".prueba"
        database._backup_consistente(copia)
        conexion = database.abrir_archivo(copia)
        conexion.execute("DELETE FROM bonos_tiempo WHERE nombre = 'A'")
        conexion.commit()
        conexion.close()
        # contra la base común de antes, a la copia cifrada le falta una fila
        original = os.path.join(self.carpeta_de_copias(), self.copias_de_antes_de_cifrar()[0])
        with self.assertRaises(database.ErrorDeCifrado):
            database._comprobar_que_quedo_igual(original, copia)


class TestClaves(_ConCarpetaTemporal):
    def test_con_otra_clave_avisa(self):
        database.CLAVE_HEX = secrets.token_hex(32)
        database.inicializar_base_de_datos()

        database.CLAVE_HEX = secrets.token_hex(32)
        with self.assertRaises(database.ErrorDeCifrado) as contexto:
            database.inicializar_base_de_datos()
        self.assertIn("clave", str(contexto.exception).lower())

    def test_una_base_cifrada_sin_clave_avisa(self):
        database.CLAVE_HEX = secrets.token_hex(32)
        database.inicializar_base_de_datos()

        database.CLAVE_HEX = None
        with self.assertRaises(database.ErrorDeCifrado) as contexto:
            database.inicializar_base_de_datos()
        self.assertIn("cifrada", str(contexto.exception).lower())

    def test_una_clave_mal_armada_no_se_usa(self):
        for mala in ("123", "z" * 64, "ab" * 33, "'; DROP TABLE usuarios; --"):
            database.CLAVE_HEX = mala
            with self.assertRaises(database.ErrorDeCifrado, msg=mala):
                database.abrir_archivo(database.DB_PATH)

    def test_sin_clave_todo_sigue_como_siempre(self):
        database.inicializar_base_de_datos()

        self.assertTrue(_es_comun(database.DB_PATH))
        self.assertEqual(self.copias_de_antes_de_cifrar(), [])


class TestCopiasDeSeguridad(_ConCarpetaTemporal):
    def setUp(self):
        super().setUp()
        self.clave = secrets.token_hex(32)
        database.CLAVE_HEX = self.clave
        database.inicializar_base_de_datos()

    def test_la_copia_consistente_sale_cifrada_y_se_abre_con_la_clave(self):
        destino = os.path.join(self._tmp.name, "copia.db")
        database._backup_consistente(destino)

        self.assertFalse(_es_comun(destino))
        copia = database.abrir_archivo(destino)
        self.assertGreaterEqual(copia.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 1)
        self.assertEqual(copia.execute("PRAGMA integrity_check").fetchone()[0], "ok")
        copia.close()

    def test_la_copia_para_un_pendrive_sale_cifrada(self):
        pendrive = os.path.join(self._tmp.name, "pendrive")
        os.makedirs(pendrive)

        ruta = database.copiar_backup_a(pendrive)

        self.assertFalse(_es_comun(ruta))

    def test_la_copia_automatica_sale_cifrada(self):
        from repositories import copias_repo

        ruta = copias_repo.copia_automatica_si_corresponde()

        self.assertIsNotNone(ruta)
        self.assertFalse(_es_comun(ruta))


class TestComoAndaCifrada(_ConCarpetaTemporal):
    def setUp(self):
        super().setUp()
        database.CLAVE_HEX = secrets.token_hex(32)
        database.inicializar_base_de_datos()

    def test_los_errores_de_la_base_se_atrapan_como_siempre(self):
        """Los repos hacen `except sqlite3.IntegrityError` y lo vuelven un cartel
        entendible. Con la base cifrada esa clase es OTRA (la de sqlcipher3): si
        algún repo siguiera con el `import sqlite3` común, saldría el error crudo."""
        from repositories import articulos_repo

        rubros = articulos_repo.listar_rubros()
        self.assertGreaterEqual(len(rubros), 2)
        with self.assertRaises(ValueError):
            articulos_repo.renombrar_rubro(rubros[0]["id"], rubros[1]["nombre"])

    def test_abrir_una_conexion_sigue_siendo_rapido(self):
        """Guardia de la clave CRUDA: con una frase, SQLCipher hace 256.000 vueltas
        de PBKDF2 por conexión (medido: ~100 ms) y el programa abre una por consulta."""
        inicio = time.perf_counter()
        for _ in range(30):
            with database.conexion_db() as conexion:
                conexion.execute("SELECT COUNT(*) FROM usuarios").fetchone()
        milisegundos = (time.perf_counter() - inicio) / 30 * 1000

        self.assertLess(milisegundos, 25, f"abrir una conexión tarda {milisegundos:.1f} ms")

    def test_las_filas_se_leen_por_nombre(self):
        with database.conexion_db() as conexion:
            fila = conexion.execute("SELECT * FROM usuarios LIMIT 1").fetchone()
        self.assertIn("nombre", fila.keys())
        self.assertEqual(fila["nombre"], fila[1])

    def test_las_claves_foraneas_siguen_activas(self):
        with database.conexion_db() as conexion:
            self.assertEqual(conexion.execute("PRAGMA foreign_keys").fetchone()[0], 1)


if __name__ == "__main__":
    unittest.main()
