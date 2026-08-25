"""
tests/test_kiosko.py
======================
Tests de las reglas de negocio más sensibles del sistema: las que
tocan plata y stock (turnos, ventas, anulaciones), la protección del
borrado de artículos, y la migración de contraseñas al formato con
salt. Todos corren contra una base de datos SQLite temporal — nunca
contra data/kiosko.db — así se pueden correr las veces que haga falta
sin riesgo de tocar datos reales.

Se ejecutan con:

    python -m unittest discover tests
"""

import hashlib
import os
import tempfile
import unittest
from datetime import datetime
from unittest import mock

import database
from repositories import articulos_repo, compras_repo, turnos_repo, usuarios_repo, ventas_repo


class BaseConBaseTemporal(unittest.TestCase):
    """Apunta database.DATA_DIR/DB_PATH a un archivo temporal antes de
    cada test, y lo restaura al terminar."""

    def setUp(self):
        self._tmp_dir = tempfile.TemporaryDirectory()
        self._data_dir_original = database.DATA_DIR
        self._db_path_original = database.DB_PATH
        database.DATA_DIR = self._tmp_dir.name
        database.DB_PATH = os.path.join(self._tmp_dir.name, "kiosko_test.db")
        database.inicializar_base_de_datos()

    def tearDown(self):
        database.DATA_DIR = self._data_dir_original
        database.DB_PATH = self._db_path_original
        self._tmp_dir.cleanup()


class TestCalcularTurno(unittest.TestCase):
    def test_manana_empieza_a_las_6(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 6, 0)), "MAÑANA")

    def test_manana_hasta_las_13_59(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 13, 59)), "MAÑANA")

    def test_tarde_empieza_a_las_14(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 14, 0)), "TARDE")

    def test_tarde_hasta_las_21_59(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 21, 59)), "TARDE")

    def test_noche_empieza_a_las_22(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 22, 0)), "NOCHE")

    def test_noche_cruza_la_medianoche(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 0, 0)), "NOCHE")
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 1, 5, 59)), "NOCHE")


class TestHashClave(unittest.TestCase):
    def test_hash_nuevo_tiene_salt_y_verifica_ok(self):
        hash_generado = database.hash_clave("miClave123")
        self.assertIn("$", hash_generado)
        self.assertTrue(database.verificar_clave("miClave123", hash_generado))
        self.assertFalse(database.verificar_clave("otraClave", hash_generado))

    def test_dos_claves_iguales_dan_hashes_distintos(self):
        # Gracias al salt al azar, dos usuarios con la misma clave no
        # quedan con el mismo hash guardado en la base.
        self.assertNotEqual(database.hash_clave("1234"), database.hash_clave("1234"))

    def test_verifica_hash_formato_viejo_sin_salt(self):
        hash_viejo = hashlib.sha256("miClave123".encode("utf-8")).hexdigest()
        self.assertTrue(database.verificar_clave("miClave123", hash_viejo))
        self.assertFalse(database.verificar_clave("otraClave", hash_viejo))


class TestMigracionHashEnLogin(BaseConBaseTemporal):
    def test_login_migra_hash_viejo_al_formato_nuevo(self):
        hash_viejo = hashlib.sha256("clave123".encode("utf-8")).hexdigest()
        with database.conexion_db() as conexion:
            conexion.execute(
                """
                INSERT INTO usuarios (nombre, clave_hash, rol, activo, fecha_creacion)
                VALUES (?, ?, 'EMPLEADA', 1, ?)
                """,
                ("Empleada Vieja", hash_viejo, datetime.now().isoformat(timespec="seconds")),
            )
            usuario_id = conexion.execute(
                "SELECT id FROM usuarios WHERE nombre = ?", ("Empleada Vieja",)
            ).fetchone()["id"]

        usuario = usuarios_repo.autenticar(usuario_id, "clave123")
        self.assertIsNotNone(usuario)

        usuario_actualizado = usuarios_repo.obtener_usuario(usuario_id)
        self.assertIn("$", usuario_actualizado["clave_hash"])
        # Y sigue pudiendo loguearse con la misma clave después de migrar.
        self.assertIsNotNone(usuarios_repo.autenticar(usuario_id, "clave123"))


class TestVentasYStock(BaseConBaseTemporal):
    def _crear_admin_y_articulo(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("COD1", "Producto de prueba", None, None, 100.0, 50.0, 5)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD1", "cantidad": 10, "costo_unitario": 50.0}])
        return usuario_id

    def test_confirmar_venta_descuenta_stock(self):
        usuario_id = self._crear_admin_y_articulo()
        ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COD1", "descripcion": "Producto de prueba", "cantidad": 3,
              "precio_unitario": 100.0, "subtotal": 300.0}],
            [{"metodo": "EFECTIVO", "monto": 300.0}],
        )
        articulo = articulos_repo.buscar_por_codigo("COD1")
        self.assertEqual(articulo["stock"], 7)

    def test_anular_venta_repone_stock_y_cambia_estado(self):
        usuario_id = self._crear_admin_y_articulo()
        venta_id = ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COD1", "descripcion": "Producto de prueba", "cantidad": 3,
              "precio_unitario": 100.0, "subtotal": 300.0}],
            [{"metodo": "EFECTIVO", "monto": 300.0}],
        )
        ventas_repo.anular_venta(venta_id, usuario_id, "prueba")

        articulo = articulos_repo.buscar_por_codigo("COD1")
        self.assertEqual(articulo["stock"], 10)

        venta, _detalle, _pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["estado"], "ANULADA")

    def test_no_se_puede_anular_una_venta_dos_veces(self):
        usuario_id = self._crear_admin_y_articulo()
        venta_id = ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COD1", "descripcion": "Producto de prueba", "cantidad": 1,
              "precio_unitario": 100.0, "subtotal": 100.0}],
            [{"metodo": "EFECTIVO", "monto": 100.0}],
        )
        ventas_repo.anular_venta(venta_id, usuario_id, "prueba")
        with self.assertRaises(ValueError):
            ventas_repo.anular_venta(venta_id, usuario_id, "de nuevo")

    def test_montos_quedan_redondeados_a_dos_decimales(self):
        usuario_id = self._crear_admin_y_articulo()
        # cantidad * precio con más de 2 decimales, a propósito.
        ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COD1", "descripcion": "Producto de prueba", "cantidad": 3,
              "precio_unitario": 33.333333, "subtotal": 99.999999}],
            [{"metodo": "EFECTIVO", "monto": 99.999999}],
        )
        venta = ventas_repo.listar_ventas_recientes(1)[0]
        self.assertEqual(venta["total"], 100.0)


class TestBorrarArticuloProtegido(BaseConBaseTemporal):
    def test_borrar_articulo_sin_movimientos_funciona(self):
        articulos_repo.crear_articulo("SINMOV", "Sin movimientos", None, None, 10.0, 5.0, 0)
        articulos_repo.borrar_articulo("SINMOV")
        self.assertIsNone(articulos_repo.buscar_por_codigo("SINMOV"))

    def test_borrar_articulo_con_ventas_tira_error_claro_y_no_borra_nada(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("CONVENTA", "Con venta", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "CONVENTA", "cantidad": 5, "costo_unitario": 5.0}])
        ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "CONVENTA", "descripcion": "Con venta", "cantidad": 1,
              "precio_unitario": 10.0, "subtotal": 10.0}],
            [{"metodo": "EFECTIVO", "monto": 10.0}],
        )

        with self.assertRaises(ValueError):
            articulos_repo.borrar_articulo("CONVENTA")

        # El artículo sigue existiendo: el rechazo fue limpio, no quedó
        # nada a mitad de camino.
        self.assertIsNotNone(articulos_repo.buscar_por_codigo("CONVENTA"))


class TestEtiquetaDeTurnoEnElCierre(BaseConBaseTemporal):
    def test_turno_del_cierre_es_el_que_empezo_no_el_que_esta_corriendo_al_cerrar(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")

        # Primer cierre: se hace a las 10:00 (turno MAÑANA).
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            turnos_repo.cerrar_turno(usuario_id)

        # Segundo cierre: el turno arrancó a las 10:00 (MAÑANA), pero
        # la empleada recién cierra a las 14:05 — ya entrada la hora
        # del turno TARDE. El cierre tiene que quedar etiquetado como
        # MAÑANA (el turno que efectivamente se está cerrando), no TARDE.
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 14, 5, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            turnos_repo.cerrar_turno(usuario_id)

        cierres = turnos_repo.listar_cierres()
        cierre_mas_reciente = cierres[0]
        self.assertEqual(cierre_mas_reciente["turno"], "MAÑANA")


if __name__ == "__main__":
    unittest.main()
