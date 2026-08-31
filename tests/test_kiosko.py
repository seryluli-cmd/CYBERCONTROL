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
from datetime import date, datetime
from unittest import mock

import database
from repositories import articulos_repo, compras_repo, reportes_repo, turnos_repo, usuarios_repo, ventas_repo


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

    # El 2026-01-04 es domingo, el 2026-01-03 es sábado (usados también en
    # TestEtiquetaTurno / TestTurnoVencimiento / TestTurnosFaltantes).
    def test_domingo_manana_dura_hasta_las_18(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 4, 17, 59)), "MAÑANA")

    def test_domingo_no_existe_el_turno_tarde(self):
        # A las 14:00, un día de semana normal ya sería Tarde.
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 4, 14, 0)), "MAÑANA")

    def test_domingo_noche_empieza_a_las_18(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 4, 18, 0)), "NOCHE")

    def test_sabado_a_la_noche_sigue_siendo_el_turno_normal(self):
        self.assertEqual(database.calcular_turno(datetime(2026, 1, 3, 22, 0)), "NOCHE")


class TestEtiquetaTurno(unittest.TestCase):
    def test_dia_de_semana_usa_los_nombres_normales(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(database.etiqueta_turno(lunes, "MAÑANA"), "Mañana")
        self.assertEqual(database.etiqueta_turno(lunes, "TARDE"), "Tarde")
        self.assertEqual(database.etiqueta_turno(lunes, "NOCHE"), "Noche")

    def test_domingo_usa_las_etiquetas_de_2_turnos(self):
        domingo = date(2026, 1, 4)
        self.assertEqual(database.etiqueta_turno(domingo, "MAÑANA"), "Domingo T1")
        self.assertEqual(database.etiqueta_turno(domingo, "NOCHE"), "Domingo T2")


class TestTurnoVencimiento(unittest.TestCase):
    def test_manana_vence_a_las_14_40_entre_semana(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(database.turno_vencimiento(lunes, "MAÑANA"), datetime(2026, 1, 5, 14, 40))

    def test_manana_vence_a_las_18_40_el_domingo(self):
        domingo = date(2026, 1, 4)
        self.assertEqual(database.turno_vencimiento(domingo, "MAÑANA"), datetime(2026, 1, 4, 18, 40))

    def test_noche_vence_a_la_madrugada_del_dia_siguiente(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(database.turno_vencimiento(lunes, "NOCHE"), datetime(2026, 1, 6, 6, 40))


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


class TestCambiarClave(BaseConBaseTemporal):
    def test_cambia_la_clave_propia_con_la_actual_correcta(self):
        usuario_id = usuarios_repo.crear_usuario("Empleada", "vieja123", "EMPLEADA")

        usuarios_repo.cambiar_clave(usuario_id, "vieja123", "nueva456")

        self.assertIsNone(usuarios_repo.autenticar(usuario_id, "vieja123"))
        self.assertIsNotNone(usuarios_repo.autenticar(usuario_id, "nueva456"))

    def test_no_cambia_nada_si_la_clave_actual_es_incorrecta(self):
        usuario_id = usuarios_repo.crear_usuario("Empleada", "vieja123", "EMPLEADA")

        with self.assertRaises(ValueError):
            usuarios_repo.cambiar_clave(usuario_id, "clave_equivocada", "nueva456")

        # La clave vieja sigue funcionando: el rechazo fue limpio.
        self.assertIsNotNone(usuarios_repo.autenticar(usuario_id, "vieja123"))


class TestAutenticarPorNombre(BaseConBaseTemporal):
    def test_loguea_ignorando_mayusculas_y_espacios(self):
        usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")

        self.assertIsNotNone(usuarios_repo.autenticar_por_nombre("matías", "1234"))
        self.assertIsNotNone(usuarios_repo.autenticar_por_nombre("MATÍAS", "1234"))
        self.assertIsNotNone(usuarios_repo.autenticar_por_nombre("  Matías  ", "1234"))

    def test_no_loguea_con_nombre_inexistente_o_clave_incorrecta(self):
        usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")

        self.assertIsNone(usuarios_repo.autenticar_por_nombre("Nadie", "1234"))
        self.assertIsNone(usuarios_repo.autenticar_por_nombre("Matías", "clave_mala"))

    def test_no_loguea_un_usuario_inactivo_por_nombre(self):
        usuario_id = usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")
        usuarios_repo.desactivar_usuario(usuario_id)

        self.assertIsNone(usuarios_repo.autenticar_por_nombre("Matías", "1234"))


class TestPermisosDeEmpleada(BaseConBaseTemporal):
    def test_crear_usuario_guarda_los_permisos_pedidos(self):
        usuario_id = usuarios_repo.crear_usuario(
            "Miguel", "1234", "EMPLEADA",
            permisos={"permiso_articulos": True, "permiso_compras": True},
        )
        usuario = usuarios_repo.obtener_usuario(usuario_id)

        self.assertTrue(usuarios_repo.tiene_permiso(usuario, "permiso_articulos"))
        self.assertTrue(usuarios_repo.tiene_permiso(usuario, "permiso_compras"))
        # Los que no se pidieron quedan en False, no en True por las dudas.
        self.assertFalse(usuarios_repo.tiene_permiso(usuario, "permiso_reportes"))
        self.assertFalse(usuarios_repo.tiene_permiso(usuario, "permiso_consulta_ventas"))
        self.assertFalse(usuarios_repo.tiene_permiso(usuario, "permiso_control_cierres"))

    def test_admin_tiene_todos_los_permisos_sin_importar_las_columnas(self):
        usuario_id = usuarios_repo.crear_usuario("Jefa", "1234", "ADMIN")
        usuario = usuarios_repo.obtener_usuario(usuario_id)

        for columna, _ in usuarios_repo.PERMISOS_EMPLEADA:
            self.assertTrue(usuarios_repo.tiene_permiso(usuario, columna))

    def test_modificar_usuario_reemplaza_los_permisos_en_vez_de_sumarlos(self):
        usuario_id = usuarios_repo.crear_usuario(
            "Miguel", "1234", "EMPLEADA", permisos={"permiso_articulos": True}
        )

        usuarios_repo.modificar_usuario(
            usuario_id, "Miguel", "EMPLEADA", permisos={"permiso_compras": True}
        )
        usuario = usuarios_repo.obtener_usuario(usuario_id)

        # El permiso nuevo quedó, y el viejo que no se volvió a tildar se sacó.
        self.assertTrue(usuarios_repo.tiene_permiso(usuario, "permiso_compras"))
        self.assertFalse(usuarios_repo.tiene_permiso(usuario, "permiso_articulos"))

    def test_crear_usuario_sin_pasar_permisos_los_deja_todos_en_false(self):
        usuario_id = usuarios_repo.crear_usuario("Empleada", "1234", "EMPLEADA")
        usuario = usuarios_repo.obtener_usuario(usuario_id)

        for columna, _ in usuarios_repo.PERMISOS_EMPLEADA:
            self.assertFalse(usuarios_repo.tiene_permiso(usuario, columna))


class TestMigracionColumnasPermisos(BaseConBaseTemporal):
    def test_agrega_columnas_permiso_a_una_tabla_usuarios_vieja(self):
        # Simula una base creada antes de que existieran los permisos
        # por empleada: la tabla usuarios sin las columnas permiso_*.
        with database.conexion_db() as conexion:
            conexion.execute("DROP TABLE usuarios")
            conexion.execute("""
                CREATE TABLE usuarios (
                    id              INTEGER PRIMARY KEY AUTOINCREMENT,
                    nombre          TEXT NOT NULL,
                    clave_hash      TEXT NOT NULL,
                    rol             TEXT NOT NULL,
                    activo          INTEGER NOT NULL DEFAULT 1,
                    fecha_creacion  TEXT NOT NULL
                )
            """)
            conexion.execute(
                "INSERT INTO usuarios (nombre, clave_hash, rol, activo, fecha_creacion) VALUES (?, ?, ?, ?, ?)",
                ("Vieja", "hash", "EMPLEADA", 1, "2026-01-01T00:00:00"),
            )

            database._migrar_columnas_permisos(conexion)

            columnas = {fila["name"] for fila in conexion.execute("PRAGMA table_info(usuarios)")}
            for columna, _ in usuarios_repo.PERMISOS_EMPLEADA:
                self.assertIn(columna, columnas)

            # La fila que ya existía no se pierde, y sus permisos nuevos
            # arrancan en 0 (no rompe nada, no le da acceso de más a nadie).
            fila = conexion.execute("SELECT * FROM usuarios WHERE nombre = 'Vieja'").fetchone()
            for columna, _ in usuarios_repo.PERMISOS_EMPLEADA:
                self.assertEqual(fila[columna], 0)


class TestGestionDeUsuarios(BaseConBaseTemporal):
    def test_crear_usuario_asigna_numeros_correlativos(self):
        # El id 1 ya lo tiene el Administrador que se siembra solo.
        id_a = usuarios_repo.crear_usuario("A", "1234", "EMPLEADA")
        id_b = usuarios_repo.crear_usuario("B", "1234", "EMPLEADA")
        self.assertEqual(id_a, 2)
        self.assertEqual(id_b, 3)

    def test_borrar_usuario_sin_historial_libera_su_numero(self):
        id_a = usuarios_repo.crear_usuario("A", "1234", "EMPLEADA")

        usuarios_repo.borrar_usuario(id_a)
        self.assertIsNone(usuarios_repo.obtener_usuario(id_a))

        # El próximo usuario que se crea reutiliza el número liberado,
        # en vez de saltar directo al siguiente más alto.
        id_c = usuarios_repo.crear_usuario("C", "1234", "EMPLEADA")
        self.assertEqual(id_c, id_a)

    def test_borrar_usuario_con_ventas_tira_error_y_no_borra_nada(self):
        vendedor_id = usuarios_repo.crear_usuario("Vendedor", "1234", "EMPLEADA")
        articulos_repo.crear_articulo("CODU", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(vendedor_id, [{"codigo": "CODU", "cantidad": 5, "costo_unitario": 5.0}])
        ventas_repo.confirmar_venta(
            vendedor_id,
            [{"codigo": "CODU", "descripcion": "Producto", "cantidad": 1,
              "precio_unitario": 10.0, "subtotal": 10.0}],
            [{"metodo": "EFECTIVO", "monto": 10.0}],
        )

        with self.assertRaises(ValueError):
            usuarios_repo.borrar_usuario(vendedor_id)

        # Sigue existiendo: el rechazo fue limpio, no quedó nada a mitad
        # de camino (mismo criterio que articulos_repo.borrar_articulo).
        self.assertIsNotNone(usuarios_repo.obtener_usuario(vendedor_id))

    def test_no_se_puede_crear_dos_usuarios_activos_con_el_mismo_nombre(self):
        usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")

        # Ni exactamente igual, ni con mayúsculas/espacios distintos:
        # el login es por nombre, así que dos activos iguales quedarían
        # ambiguos (ver usuarios_repo.autenticar_por_nombre).
        with self.assertRaises(ValueError):
            usuarios_repo.crear_usuario("  MATÍAS  ", "otraClave", "EMPLEADA")

    def test_se_puede_reusar_el_nombre_de_un_usuario_inactivo(self):
        usuario_id = usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")
        usuarios_repo.desactivar_usuario(usuario_id)

        # No está activo, así que no genera ambigüedad para el login.
        nuevo_id = usuarios_repo.crear_usuario("Matías", "5678", "EMPLEADA")
        self.assertNotEqual(nuevo_id, usuario_id)

    def test_modificar_usuario_no_deja_renombrar_a_uno_ya_usado(self):
        usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")
        otro_id = usuarios_repo.crear_usuario("Rocío", "1234", "EMPLEADA")

        with self.assertRaises(ValueError):
            usuarios_repo.modificar_usuario(otro_id, "Matías", "EMPLEADA")

        # No cambió nada: sigue llamándose Rocío.
        self.assertEqual(usuarios_repo.obtener_usuario(otro_id)["nombre"], "Rocío")

    def test_modificar_usuario_permite_dejar_el_mismo_nombre(self):
        # Guardar sin cambiar el nombre no debe chocar contra sí mismo.
        usuario_id = usuarios_repo.crear_usuario("Matías", "1234", "EMPLEADA")
        usuarios_repo.modificar_usuario(usuario_id, "Matías", "ADMIN")
        self.assertEqual(usuarios_repo.obtener_usuario(usuario_id)["rol"], "ADMIN")


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


class TestFechaDelCierreEsElDiaQueArrancoElTurno(BaseConBaseTemporal):
    def test_turno_noche_cerrado_pasada_la_medianoche_guarda_la_fecha_de_inicio(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")

        # Primer cierre del sistema, ya entrada la Noche del 5 de enero.
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 22, 5, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            turnos_repo.cerrar_turno(usuario_id)

        # Se cierra recién a las 00:40 del día siguiente: el turno Noche
        # arrancó el 5 (justo después del cierre anterior), no el 6 —
        # "fecha" tiene que quedar en el día 5, aunque el cierre en sí se
        # haga ya entrado el día 6 (mismo criterio que ya se usa para
        # "turno", ver TestEtiquetaDeTurnoEnElCierre).
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 6, 0, 40, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            resultado = turnos_repo.cerrar_turno(usuario_id)

        cierre = turnos_repo.listar_cierres()[0]
        self.assertEqual(cierre["id"], resultado["id"])
        self.assertEqual(cierre["fecha"], "2026-01-05")
        self.assertEqual(cierre["turno"], "NOCHE")
        self.assertEqual(resultado["turno_label"], "Noche")


class TestTurnosFaltantes(BaseConBaseTemporal):
    def test_turno_cerrado_no_aparece_pero_los_vencidos_sin_cerrar_si(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")

        # Primer (y único) cierre: arranca a las 10:00 del lunes 5 de
        # enero de 2026, turno MAÑANA.
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            turnos_repo.cerrar_turno(usuario_id)

        # "Ahora" es ese mismo lunes a las 20:00: todos los turnos de los
        # días 1 a 4 de enero (y el Mañana del día 5, recién cerrado) ya
        # vencieron con su gracia de 40 min.
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 20, 0, 0)
            faltantes = turnos_repo.turnos_faltantes()

        claves = {(f["fecha"], f["turno"]) for f in faltantes}

        # El turno recién cerrado no figura como faltante...
        self.assertNotIn((date(2026, 1, 5), "MAÑANA"), claves)
        # ...pero un turno vencido de un día anterior que nunca se cerró, sí.
        self.assertIn((date(2026, 1, 1), "TARDE"), claves)
        # El domingo 4 de enero no tiene turno Tarde (2 turnos de 12hs).
        self.assertIn((date(2026, 1, 4), "MAÑANA"), claves)
        self.assertNotIn((date(2026, 1, 4), "TARDE"), claves)
        # La Tarde de hoy (día 5) todavía no venció (recién son las 20:00,
        # vence a las 22:40): no debería figurar todavía.
        self.assertNotIn((date(2026, 1, 5), "TARDE"), claves)


class TestUsuariosDeTurnoFaltante(BaseConBaseTemporal):
    def _vender(self, usuario_id, momento):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1,
                  "precio_unitario": 10.0, "subtotal": 10.0}],
                [{"metodo": "EFECTIVO", "monto": 10.0}],
            )

    def _loguear(self, usuario_id, clave, momento):
        with mock.patch("repositories.usuarios_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            usuarios_repo.autenticar(usuario_id, clave)

    def test_turno_faltante_muestra_quien_vendio_incluyendo_noche_que_cruza_medianoche(self):
        vendedora_id = usuarios_repo.crear_usuario("Vendedora Noche", "1234", "EMPLEADA")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(vendedora_id, [{"codigo": "COD9", "cantidad": 5, "costo_unitario": 5.0}])

        # Una venta a las 23:30 del 5 de enero (Noche, mismo día que
        # arranca) y otra a las 02:00 del 6 (Noche, ya pasada la
        # medianoche) — las dos tienen que atribuirse al turno Noche del
        # día 5, no al del día 6.
        self._vender(vendedora_id, datetime(2026, 1, 5, 23, 30, 0))
        self._vender(vendedora_id, datetime(2026, 1, 6, 2, 0, 0))

        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 6, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            faltantes = turnos_repo.turnos_faltantes()

        slot_noche_5 = next(f for f in faltantes if f["fecha"] == date(2026, 1, 5) and f["turno"] == "NOCHE")
        self.assertEqual(slot_noche_5["usuarios"], ["Vendedora Noche"])

        slot_noche_6 = next((f for f in faltantes if f["fecha"] == date(2026, 1, 6) and f["turno"] == "NOCHE"), None)
        self.assertIsNone(slot_noche_6)  # el 6 a las 10:00 el turno Noche del día 6 ni empezó a vencer

        # Un turno vencido sin ninguna venta ni login muestra la lista vacía.
        slot_manana_5 = next(f for f in faltantes if f["fecha"] == date(2026, 1, 5) and f["turno"] == "MAÑANA")
        self.assertEqual(slot_manana_5["usuarios"], [])

    def test_turno_faltante_sin_ventas_muestra_quien_se_logueo(self):
        # Una empleada se loguea a las 07:00 del 5 de enero (turno Mañana)
        # pero no llega a cargar ninguna venta: sin el login, ese turno
        # faltante no tendría a quién preguntarle.
        empleada_id = usuarios_repo.crear_usuario("Empleada Sin Ventas", "1234", "EMPLEADA")
        self._loguear(empleada_id, "1234", datetime(2026, 1, 5, 7, 0, 0))

        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 20, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            faltantes = turnos_repo.turnos_faltantes()

        slot_manana_5 = next(f for f in faltantes if f["fecha"] == date(2026, 1, 5) and f["turno"] == "MAÑANA")
        self.assertEqual(slot_manana_5["usuarios"], ["Empleada Sin Ventas"])


class TestResumenPorTurno(BaseConBaseTemporal):
    def _vender(self, usuario_id, momento, metodo="EFECTIVO"):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD8", "descripcion": "Producto", "cantidad": 1,
                  "precio_unitario": 10.0, "subtotal": 10.0}],
                [{"metodo": metodo, "monto": 10.0}],
            )

    def test_desglosa_ventas_por_turno(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("COD8", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD8", "cantidad": 10, "costo_unitario": 5.0}])

        # Un lunes: una venta de Mañana y dos de Tarde (una en efectivo,
        # otra digital) — Noche queda sin ninguna venta ese día.
        self._vender(usuario_id, datetime(2026, 1, 5, 8, 0, 0))
        self._vender(usuario_id, datetime(2026, 1, 5, 15, 0, 0))
        self._vender(usuario_id, datetime(2026, 1, 5, 16, 0, 0), metodo="DIGITAL")

        filas = reportes_repo.resumen_por_turno("2026-01-05", "2026-01-05")
        por_turno = {f["turno"]: f for f in filas}

        self.assertEqual(por_turno["MAÑANA"]["total"], 10.0)
        self.assertEqual(por_turno["MAÑANA"]["cantidad_ventas"], 1)

        self.assertEqual(por_turno["TARDE"]["total"], 20.0)
        self.assertEqual(por_turno["TARDE"]["cantidad_ventas"], 2)
        self.assertEqual(por_turno["TARDE"]["efectivo"], 10.0)
        self.assertEqual(por_turno["TARDE"]["digital"], 10.0)

        self.assertEqual(por_turno["NOCHE"]["total"], 0.0)
        self.assertEqual(por_turno["NOCHE"]["cantidad_ventas"], 0)


if __name__ == "__main__":
    unittest.main()
