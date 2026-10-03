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
import unittest
from datetime import date, datetime
from unittest import mock

import database
import dominio
import turnos
from repositories import (
    articulos_repo, compras_repo, config_repo, reportes_repo, turnos_repo, usuarios_repo, ventas_repo,
)
from control_pcs.repositories import bonos_miembro_repo, miembros_repo, pcs_repo
from base import BaseConBaseTemporal


class TestCalcularTurno(unittest.TestCase):
    def test_manana_empieza_a_las_6(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 6, 0)), "MAÑANA")

    def test_manana_hasta_las_13_59(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 13, 59)), "MAÑANA")

    def test_tarde_empieza_a_las_14(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 14, 0)), "TARDE")

    def test_tarde_hasta_las_21_59(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 21, 59)), "TARDE")

    def test_noche_empieza_a_las_22(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 22, 0)), "NOCHE")

    def test_noche_cruza_la_medianoche(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 0, 0)), "NOCHE")
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 1, 5, 59)), "NOCHE")

    # El 2026-01-04 es domingo, el 2026-01-03 es sábado (usados también en
    # TestEtiquetaTurno / TestTurnoVencimiento / TestTurnosFaltantes).
    def test_domingo_manana_dura_hasta_las_18(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 4, 17, 59)), "MAÑANA")

    def test_domingo_no_existe_el_turno_tarde(self):
        # A las 14:00, un día de semana normal ya sería Tarde.
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 4, 14, 0)), "MAÑANA")

    def test_domingo_noche_empieza_a_las_18(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 4, 18, 0)), "NOCHE")

    def test_sabado_a_la_noche_sigue_siendo_el_turno_normal(self):
        self.assertEqual(turnos.calcular_turno(datetime(2026, 1, 3, 22, 0)), "NOCHE")


class TestEtiquetaTurno(unittest.TestCase):
    def test_dia_de_semana_usa_los_nombres_normales(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(turnos.etiqueta_turno(lunes, "MAÑANA"), "Mañana")
        self.assertEqual(turnos.etiqueta_turno(lunes, "TARDE"), "Tarde")
        self.assertEqual(turnos.etiqueta_turno(lunes, "NOCHE"), "Noche")

    def test_domingo_usa_las_etiquetas_de_2_turnos(self):
        domingo = date(2026, 1, 4)
        self.assertEqual(turnos.etiqueta_turno(domingo, "MAÑANA"), "Domingo T1")
        self.assertEqual(turnos.etiqueta_turno(domingo, "NOCHE"), "Domingo T2")


class TestTurnosDelDia(unittest.TestCase):
    """`turnos_del_dia` es el único lugar donde se decide qué turnos
    existen en un día; antes esa lista estaba escrita a mano en
    turnos_repo."""

    def test_dia_de_semana_tiene_los_tres_turnos(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(
            turnos.turnos_del_dia(lunes),
            (dominio.TURNO_MANANA, dominio.TURNO_TARDE, dominio.TURNO_NOCHE),
        )

    def test_domingo_tiene_solo_dos_turnos_y_sin_tarde(self):
        domingo = date(2026, 1, 4)
        turnos_domingo = turnos.turnos_del_dia(domingo)
        self.assertEqual(turnos_domingo, (dominio.TURNO_MANANA, dominio.TURNO_NOCHE))
        self.assertNotIn(dominio.TURNO_TARDE, turnos_domingo)

    def test_acepta_string_igual_que_es_domingo(self):
        self.assertEqual(turnos.turnos_del_dia("2026-01-04"), dominio.TURNOS_DOMINGO)


class TestSubtotalDeLinea(unittest.TestCase):
    """El subtotal de un renglón se calcula en un solo lugar
    (`ventas_repo.subtotal_linea`), y `confirmar_venta` lo usa en vez de
    confiar en lo que le manda la pantalla."""

    def test_subtotal_es_cantidad_por_precio(self):
        linea = {"cantidad": 3, "precio_unitario": 100.0}
        self.assertEqual(ventas_repo.subtotal_linea(linea), 300.0)

    def test_total_del_carrito_suma_todos_los_renglones(self):
        carrito = [
            {"cantidad": 3, "precio_unitario": 100.0},
            {"cantidad": 2, "precio_unitario": 50.5},
        ]
        self.assertEqual(ventas_repo.total_carrito(carrito), 401.0)

    def test_carrito_vacio_da_cero(self):
        self.assertEqual(ventas_repo.total_carrito([]), 0)


class TestPagosNetosDeVuelto(unittest.TestCase):
    """Reproduce el bug real: una venta de $1.000 pagada con un billete
    de $2.000 sumaba $2.000 a caja aunque se hayan devuelto $1.000 de
    vuelto. dominio.pagos_netos_de_vuelto es lo que usa
    ui/dialogo_pago.DialogoPago._confirmar antes de devolver self.pagos,
    para que lo que se graba en venta_pagos sea neto del vuelto."""

    def test_descuenta_el_vuelto_del_unico_pago_en_efectivo(self):
        pagos = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 2000.0}]
        resultado = dominio.pagos_netos_de_vuelto(pagos, vuelto=1000.0)
        self.assertEqual(resultado, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0}])

    def test_no_toca_el_pago_digital(self):
        pagos = [
            {"metodo": dominio.PAGO_DIGITAL, "monto": 500.0},
            {"metodo": dominio.PAGO_EFECTIVO, "monto": 1200.0},
        ]
        # Total real $1.500: $500 digital + $1.000 efectivo: sobraron $200.
        resultado = dominio.pagos_netos_de_vuelto(pagos, vuelto=200.0)
        self.assertEqual(resultado, [
            {"metodo": dominio.PAGO_DIGITAL, "monto": 500.0},
            {"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0},
        ])

    def test_descarta_un_pago_que_queda_en_cero(self):
        # Un pago en Efectivo que era EXACTAMENTE el vuelto que se llevó
        # puesto (por ejemplo, dos pagos en efectivo donde el segundo
        # sobraba entero) no debe dejar una fila de $0 en venta_pagos.
        pagos = [
            {"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0},
            {"metodo": dominio.PAGO_EFECTIVO, "monto": 500.0},
        ]
        resultado = dominio.pagos_netos_de_vuelto(pagos, vuelto=500.0)
        self.assertEqual(resultado, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0}])

    def test_no_modifica_la_lista_original(self):
        pagos = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 2000.0}]
        dominio.pagos_netos_de_vuelto(pagos, vuelto=1000.0)
        self.assertEqual(pagos, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 2000.0}])


class TestTarifaHoraParaMonto(unittest.TestCase):
    """dominio.tarifa_hora_para_monto: qué tarifa $/hora corresponde a un
    monto cargado, según la tabla de tramos que reemplazó a la tarifa
    única de Socios (pedido del dueño, 2026-09-30, para poder cobrar
    distinto según cuánta plata carga el socio de una vez)."""

    def test_usa_el_tramo_mas_alto_que_no_supera_el_monto(self):
        tramos = [
            {"monto_minimo": 0, "tarifa_hora": 1000},
            {"monto_minimo": 5000, "tarifa_hora": 800},
            {"monto_minimo": 10000, "tarifa_hora": 600},
        ]
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 4999), 1000)
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 5000), 800)
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 9999), 800)
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 15000), 600)

    def test_no_asume_que_el_tramo_mas_caro_es_el_de_mas_plata(self):
        # El dueño puede cargar los tramos en cualquier relación de
        # precios, no necesariamente "cuanto más plata, más barato".
        tramos = [
            {"monto_minimo": 0, "tarifa_hora": 800},
            {"monto_minimo": 5000, "tarifa_hora": 1500},
        ]
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 100), 800)
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 6000), 1500)

    def test_monto_menor_al_tramo_mas_bajo_usa_igual_esa_tarifa(self):
        tramos = [{"monto_minimo": 5000, "tarifa_hora": 800}]
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 100), 800)

    def test_no_depende_del_orden_en_que_vienen_los_tramos(self):
        tramos = [
            {"monto_minimo": 10000, "tarifa_hora": 600},
            {"monto_minimo": 0, "tarifa_hora": 1000},
            {"monto_minimo": 5000, "tarifa_hora": 800},
        ]
        self.assertEqual(dominio.tarifa_hora_para_monto(tramos, 7000), 800)


class TestValidarTramosTarifaHoraMiembro(unittest.TestCase):
    def test_lista_vacia_no_es_valida(self):
        with self.assertRaises(ValueError):
            dominio.validar_tramos_tarifa_hora_miembro([])

    def test_monto_minimo_negativo_no_es_valido(self):
        with self.assertRaises(ValueError):
            dominio.validar_tramos_tarifa_hora_miembro([{"monto_minimo": -1, "tarifa_hora": 1000}])

    def test_tarifa_cero_o_negativa_no_es_valida(self):
        with self.assertRaises(ValueError):
            dominio.validar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 0}])

    def test_dos_tramos_con_el_mismo_monto_minimo_no_es_valido(self):
        with self.assertRaises(ValueError):
            dominio.validar_tramos_tarifa_hora_miembro([
                {"monto_minimo": 0, "tarifa_hora": 1000},
                {"monto_minimo": 0, "tarifa_hora": 800},
            ])

    def test_tramos_validos_no_tira_error(self):
        dominio.validar_tramos_tarifa_hora_miembro([
            {"monto_minimo": 0, "tarifa_hora": 1000},
            {"monto_minimo": 5000, "tarifa_hora": 800},
        ])


class TestEsAdmin(unittest.TestCase):
    def test_reconoce_el_rol_admin_y_rechaza_el_resto(self):
        self.assertTrue(dominio.es_admin({"rol": dominio.ROL_ADMIN}))
        self.assertFalse(dominio.es_admin({"rol": dominio.ROL_EMPLEADA}))
        self.assertFalse(dominio.es_admin(None))


class TestTurnoVencimiento(unittest.TestCase):
    def test_manana_vence_a_las_14_40_entre_semana(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(turnos.turno_vencimiento(lunes, "MAÑANA"), datetime(2026, 1, 5, 14, 40))

    def test_manana_vence_a_las_18_40_el_domingo(self):
        domingo = date(2026, 1, 4)
        self.assertEqual(turnos.turno_vencimiento(domingo, "MAÑANA"), datetime(2026, 1, 4, 18, 40))

    def test_noche_vence_a_la_madrugada_del_dia_siguiente(self):
        lunes = date(2026, 1, 5)
        self.assertEqual(turnos.turno_vencimiento(lunes, "NOCHE"), datetime(2026, 1, 6, 6, 40))


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
              "precio_unitario": 10.0}],
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
              "precio_unitario": 100.0}],
            [{"metodo": "EFECTIVO", "monto": 300.0}],
        )
        articulo = articulos_repo.buscar_por_codigo("COD1")
        self.assertEqual(articulo["stock"], 7)

    def test_anular_venta_repone_stock_y_cambia_estado(self):
        usuario_id = self._crear_admin_y_articulo()
        venta_id = ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COD1", "descripcion": "Producto de prueba", "cantidad": 3,
              "precio_unitario": 100.0}],
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
              "precio_unitario": 100.0}],
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
              "precio_unitario": 33.333333}],
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
              "precio_unitario": 10.0}],
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


class TestResumenTurnoActualCoincideConElCierre(BaseConBaseTemporal):
    """
    Antes, la vista previa de Caja/Cierre de Turno (resumen_turno_actual)
    calculaba el turno mirando la hora ACTUAL, mientras que cerrar_turno
    lo calculaba mirando cuándo arrancó lo que sigue sin cerrar -- podían
    no coincidir. Ver _desde_y_turno_en_curso.
    """

    def test_el_titulo_en_pantalla_anticipa_el_turno_que_va_a_quedar_grabado(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")

        # Primer cierre a las 10:00 (turno MAÑANA).
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            turnos_repo.cerrar_turno(usuario_id)

        # Son las 14:05: ya empezó TARDE, pero la MAÑANA todavía no se
        # cerró. La vista previa tiene que seguir mostrando MAÑANA (el
        # turno que efectivamente se va a grabar si alguien cierra ahora),
        # no TARDE.
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 14, 5, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            resumen = turnos_repo.resumen_turno_actual()
            self.assertEqual(resumen["turno_actual"], "MAÑANA")
            self.assertEqual(resumen["turno_actual_label"], "Mañana")

            cierre = turnos_repo.cerrar_turno(usuario_id)
            self.assertEqual(cierre["turno"], "MAÑANA")


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


class TestDetalleCierre(BaseConBaseTemporal):
    def _vender(self, usuario_id, momento, total=10.0):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            return ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1,
                  "precio_unitario": total}],
                [{"metodo": "EFECTIVO", "monto": total}],
            )

    def _cerrar(self, usuario_id, momento):
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return turnos_repo.cerrar_turno(usuario_id)

    def test_cada_cierre_solo_trae_las_ventas_de_su_propia_ventana(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD9", "cantidad": 5, "costo_unitario": 5.0}])

        venta_1 = self._vender(usuario_id, datetime(2026, 1, 1, 9, 0, 0))
        cierre_1 = self._cerrar(usuario_id, datetime(2026, 1, 1, 10, 0, 0))

        venta_2 = self._vender(usuario_id, datetime(2026, 1, 1, 11, 0, 0))
        cierre_2 = self._cerrar(usuario_id, datetime(2026, 1, 1, 14, 0, 0))

        detalle_1 = turnos_repo.detalle_cierre(cierre_1["id"])
        self.assertEqual([v["id"] for v in detalle_1["ventas"]], [venta_1])

        detalle_2 = turnos_repo.detalle_cierre(cierre_2["id"])
        self.assertEqual([v["id"] for v in detalle_2["ventas"]], [venta_2])

    def test_incluye_ventas_anuladas_de_la_ventana_pero_no_cuentan_para_el_total(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD9", "cantidad": 5, "costo_unitario": 5.0}])

        venta_ok = self._vender(usuario_id, datetime(2026, 1, 1, 9, 0, 0))
        venta_anulada = self._vender(usuario_id, datetime(2026, 1, 1, 9, 30, 0))
        ventas_repo.anular_venta(venta_anulada, usuario_id, "Test")

        cierre = self._cerrar(usuario_id, datetime(2026, 1, 1, 10, 0, 0))

        # El total del cierre solo contó la confirmada (la anulada no
        # suma, ver _sumar_ventas_por_origen_y_metodo).
        self.assertEqual(cierre["ventas_efectivo"], 10.0)

        detalle = turnos_repo.detalle_cierre(cierre["id"])
        ids = {v["id"]: v["estado"] for v in detalle["ventas"]}
        self.assertEqual(ids[venta_ok], dominio.VENTA_CONFIRMADA)
        self.assertEqual(ids[venta_anulada], dominio.VENTA_ANULADA)

    def test_venta_en_el_mismo_segundo_que_un_cierre_no_se_pierde(self):
        # Reproduce el bug real: una venta hecha justo al abrir el turno
        # siguiente, en el MISMO segundo de reloj que el cierre anterior
        # (pero microsegundos después). Con fecha_cierre y ventas.fecha
        # grabados con precisión de un solo segundo, los dos strings
        # empataban y esta venta quedaba afuera de los DOS turnos: no la
        # contaba el cierre que se estaba cerrando (llegó después del
        # corte) ni el siguiente (el ">" estricto la excluía por el
        # empate) -- ver el porqué de la precisión de microsegundos en
        # ventas_repo.confirmar_venta / turnos_repo.cerrar_turno.
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD9", "cantidad": 5, "costo_unitario": 5.0}])

        cierre_1 = self._cerrar(usuario_id, datetime(2026, 1, 1, 10, 0, 0, 500000))
        venta_2 = self._vender(usuario_id, datetime(2026, 1, 1, 10, 0, 0, 800000))
        cierre_2 = self._cerrar(usuario_id, datetime(2026, 1, 1, 11, 0, 0))

        detalle_2 = turnos_repo.detalle_cierre(cierre_2["id"])
        self.assertEqual([v["id"] for v in detalle_2["ventas"]], [venta_2])
        self.assertEqual(cierre_2["ventas_efectivo"], 10.0)


class TestResumenDelDia(BaseConBaseTemporal):
    """El reporte de un día abierto por turno (turnos_repo.resumen_del_dia)."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", "ADMIN")
        self.lucia_id = usuarios_repo.crear_usuario("Lucia", "1234", "EMPLEADA")
        self.pedro_id = usuarios_repo.crear_usuario("Pedro", "1234", "EMPLEADA")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(self.admin_id, [{"codigo": "COD9", "cantidad": 50, "costo_unitario": 5.0}])

    def _vender(self, momento, total, metodo="EFECTIVO", usuario_id=None):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            return ventas_repo.confirmar_venta(
                usuario_id or self.lucia_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": total}],
                [{"metodo": metodo, "monto": total}],
            )

    def _cerrar(self, momento, usuario_id=None):
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return turnos_repo.cerrar_turno(usuario_id or self.lucia_id)

    def _resumen(self, dia, ahora):
        with mock.patch("repositories.turnos_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = ahora
            datetime_mock.fromisoformat = datetime.fromisoformat
            return turnos_repo.resumen_del_dia(dia)

    def test_un_dia_con_mañana_y_tarde_cerradas_y_la_noche_en_curso(self):
        # Lunes 5 de enero de 2026. Mañana cerrada a las 14:05, Tarde
        # cerrada a las 22:10 y la Noche todavía abierta a las 23:00.
        self._cerrar(datetime(2026, 1, 5, 6, 0))  # punto de partida, sin ventas
        self._vender(datetime(2026, 1, 5, 9, 0), 10.0)
        self._cerrar(datetime(2026, 1, 5, 14, 5), self.lucia_id)
        self._vender(datetime(2026, 1, 5, 15, 0), 20.0)
        self._vender(datetime(2026, 1, 5, 16, 0), 30.0, metodo="DIGITAL")
        self._cerrar(datetime(2026, 1, 5, 22, 10), self.pedro_id)
        self._vender(datetime(2026, 1, 5, 22, 30), 5.0)

        resumen = self._resumen(date(2026, 1, 5), datetime(2026, 1, 5, 23, 0))
        manana, tarde, noche = resumen["turnos"]

        self.assertEqual([t["etiqueta"] for t in resumen["turnos"]], ["Mañana", "Tarde", "Noche"])
        self.assertEqual([t["estado"] for t in resumen["turnos"]],
                         [turnos_repo.ESTADO_CERRADO, turnos_repo.ESTADO_CERRADO, turnos_repo.ESTADO_EN_CURSO])

        self.assertEqual(manana["total"], 10.0)
        self.assertEqual(manana["responsables"], ["Lucia"])
        self.assertEqual(manana["cantidad_ventas"], 1)

        self.assertEqual(tarde["efectivo"], 20.0)
        self.assertEqual(tarde["digital"], 30.0)
        self.assertEqual(tarde["total"], 50.0)
        self.assertEqual(tarde["kiosko"], 50.0)
        self.assertEqual(tarde["pcs"], 0.0)
        self.assertEqual(tarde["responsables"], ["Pedro"])
        self.assertEqual(tarde["cantidad_ventas"], 2)

        # La Noche sigue abierta: se ve lo que lleva, sin responsable ni hora de cierre.
        self.assertEqual(noche["total"], 5.0)
        self.assertEqual(noche["responsables"], [])
        self.assertIsNone(noche["cerrado_a"])

        self.assertEqual(resumen["total"]["total"], 65.0)
        self.assertEqual(resumen["total"]["cantidad_ventas"], 4)

    def test_el_domingo_tiene_dos_turnos_y_un_dia_pasado_sin_cierres_queda_sin_cerrar(self):
        resumen = self._resumen(date(2026, 1, 4), datetime(2026, 1, 7, 10, 0))
        self.assertEqual([t["etiqueta"] for t in resumen["turnos"]], ["Domingo T1", "Domingo T2"])
        self.assertTrue(all(t["estado"] == turnos_repo.ESTADO_SIN_CERRAR for t in resumen["turnos"]))
        self.assertEqual(resumen["total"]["total"], 0.0)

    def test_turnos_que_todavia_no_empezaron_estan_pendientes(self):
        # Sin ningún cierre previo la ventana abierta arranca ahora (10:00,
        # Mañana): la Tarde y la Noche todavía no tienen por qué estar cerradas.
        resumen = self._resumen(date(2026, 1, 5), datetime(2026, 1, 5, 10, 0))
        estados = [t["estado"] for t in resumen["turnos"]]
        self.assertEqual(estados, [turnos_repo.ESTADO_EN_CURSO, turnos_repo.ESTADO_PENDIENTE,
                                   turnos_repo.ESTADO_PENDIENTE])

    def test_un_turno_cerrado_dos_veces_suma_los_dos_cierres(self):
        self._cerrar(datetime(2026, 1, 5, 6, 0))
        self._vender(datetime(2026, 1, 5, 9, 0), 10.0)
        self._cerrar(datetime(2026, 1, 5, 12, 0), self.lucia_id)
        self._vender(datetime(2026, 1, 5, 12, 30), 7.0)
        self._cerrar(datetime(2026, 1, 5, 14, 5), self.pedro_id)

        manana = self._resumen(date(2026, 1, 5), datetime(2026, 1, 5, 15, 0))["turnos"][0]
        self.assertEqual(manana["estado"], turnos_repo.ESTADO_CERRADO)
        self.assertEqual(manana["total"], 17.0)
        self.assertEqual(manana["cantidad_ventas"], 2)
        self.assertEqual(manana["responsables"], ["Lucia", "Pedro"])

    def test_la_noche_que_cruza_la_medianoche_se_cuenta_en_el_dia_que_arranco(self):
        self._cerrar(datetime(2026, 1, 5, 22, 5))  # arranca la Noche del lunes 5
        self._vender(datetime(2026, 1, 5, 23, 30), 10.0)
        self._vender(datetime(2026, 1, 6, 2, 0), 20.0)
        self._cerrar(datetime(2026, 1, 6, 6, 30), self.pedro_id)

        ahora = datetime(2026, 1, 6, 7, 0)
        noche_del_5 = self._resumen(date(2026, 1, 5), ahora)["turnos"][2]
        self.assertEqual(noche_del_5["estado"], turnos_repo.ESTADO_CERRADO)
        self.assertEqual(noche_del_5["total"], 30.0)

        # Esas dos ventas NO aparecen en el día 6, aunque pasaron de la medianoche.
        dia_6 = self._resumen(date(2026, 1, 6), ahora)
        self.assertEqual(dia_6["total"]["total"], 0.0)

    def test_muestra_la_diferencia_solo_si_el_admin_ya_conto_el_sobre(self):
        cierre_inicial = self._cerrar(datetime(2026, 1, 5, 6, 0))
        self._vender(datetime(2026, 1, 5, 9, 0), 10.0)
        cierre_manana = self._cerrar(datetime(2026, 1, 5, 14, 5))
        self._vender(datetime(2026, 1, 5, 15, 0), 20.0)
        self._cerrar(datetime(2026, 1, 5, 22, 10))

        # La Mañana tiene dos cierres (el inicial, vacío, y el de las 14:05):
        # recién cuenta como verificada cuando el Admin contó los dos.
        turnos_repo.verificar_cierre(cierre_manana["id"], 8.0, self.admin_id)
        manana = self._resumen(date(2026, 1, 5), datetime(2026, 1, 5, 23, 0))["turnos"][0]
        self.assertFalse(manana["verificado"])

        turnos_repo.verificar_cierre(cierre_inicial["id"], 0.0, self.admin_id)

        manana, tarde, _ = self._resumen(date(2026, 1, 5), datetime(2026, 1, 5, 23, 0))["turnos"]
        self.assertTrue(manana["verificado"])
        self.assertEqual(manana["diferencia"], -2.0)
        self.assertFalse(tarde["verificado"])
        self.assertIsNone(tarde["diferencia"])

    def test_cuenta_las_ventas_anuladas_aparte_y_no_las_suma_al_total(self):
        self._cerrar(datetime(2026, 1, 5, 6, 0))
        self._vender(datetime(2026, 1, 5, 9, 0), 10.0)
        anulada = self._vender(datetime(2026, 1, 5, 9, 30), 99.0)
        ventas_repo.anular_venta(anulada, self.admin_id, "Test")
        self._cerrar(datetime(2026, 1, 5, 14, 5))

        manana = self._resumen(date(2026, 1, 5), datetime(2026, 1, 5, 15, 0))["turnos"][0]
        self.assertEqual(manana["total"], 10.0)
        self.assertEqual(manana["cantidad_ventas"], 1)
        self.assertEqual(manana["cantidad_anuladas"], 1)


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
                  "precio_unitario": 10.0}],
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
                  "precio_unitario": 10.0}],
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


class TestResumenPorOrigen(BaseConBaseTemporal):
    """reportes_repo.resumen_por_origen: desglose Kiosko vs. Alquiler de
    PCs por turno/día/semana/rango, para la pestaña "Totales" de
    Reportes."""

    def _preparar_articulo(self, usuario_id):
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 100.0, 50.0, 0)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD9", "cantidad": 1000, "costo_unitario": 50.0}])

    def _vender_kiosko(self, usuario_id, momento, monto=100.0):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": monto}],
                [{"metodo": "EFECTIVO", "monto": monto}],
            )

    def _vender_pcs(self, usuario_id, momento, monto=200.0):
        # Estación y bono nuevos por venta -- evita depender de la lógica
        # de "extender sesión existente" de asignar_bono, que no viene al
        # caso acá (solo interesa que la plata quede clasificada ALQUILER_PCS).
        estacion_id = pcs_repo.crear_estacion(f"PC {momento.isoformat()}")
        bono_id = pcs_repo.crear_bono(f"Bono {momento.isoformat()}", 60, monto)
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": monto}])

    def test_rango_separa_kiosko_de_pcs(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        self._preparar_articulo(usuario_id)
        self._vender_kiosko(usuario_id, datetime(2026, 1, 5, 8, 0, 0), 100.0)
        self._vender_pcs(usuario_id, datetime(2026, 1, 5, 9, 0, 0), 3000.0)

        filas = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-05", "rango")

        self.assertEqual(filas, [{"etiqueta": "Total del período", "kiosko": 100.0, "pcs": 3000.0, "total": 3100.0}])

    def test_rango_sin_ventas_devuelve_una_fila_en_cero(self):
        filas = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-05", "rango")

        self.assertEqual(filas, [{"etiqueta": "Total del período", "kiosko": 0.0, "pcs": 0.0, "total": 0.0}])

    def test_turno_siempre_devuelve_los_tres_aunque_falten_ventas(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        self._preparar_articulo(usuario_id)
        self._vender_kiosko(usuario_id, datetime(2026, 1, 5, 8, 0, 0), 100.0)  # Mañana

        filas = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-05", "turno")
        por_turno = {f["etiqueta"]: f for f in filas}

        self.assertEqual(set(por_turno.keys()), {"Mañana", "Tarde", "Noche"})
        self.assertEqual(por_turno["Mañana"]["kiosko"], 100.0)
        self.assertEqual(por_turno["Tarde"]["total"], 0.0)
        self.assertEqual(por_turno["Noche"]["total"], 0.0)

    def test_dia_una_fila_por_cada_dia_con_ventas(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        self._preparar_articulo(usuario_id)
        self._vender_kiosko(usuario_id, datetime(2026, 1, 5, 8, 0, 0), 100.0)
        self._vender_pcs(usuario_id, datetime(2026, 1, 6, 9, 0, 0), 3000.0)

        filas = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-06", "dia")

        self.assertEqual([f["etiqueta"] for f in filas], ["05/01/2026", "06/01/2026"])
        self.assertEqual(filas[0]["kiosko"], 100.0)
        self.assertEqual(filas[0]["pcs"], 0.0)
        self.assertEqual(filas[1]["pcs"], 3000.0)

    def test_semana_junta_lunes_a_domingo_y_corta_en_el_lunes_siguiente(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        self._preparar_articulo(usuario_id)
        # 2026-01-05 es lunes; 2026-01-11 es domingo de la misma semana;
        # 2026-01-12 ya es lunes de la semana siguiente.
        self._vender_kiosko(usuario_id, datetime(2026, 1, 5, 8, 0, 0), 100.0)
        self._vender_kiosko(usuario_id, datetime(2026, 1, 11, 8, 0, 0), 50.0)
        self._vender_kiosko(usuario_id, datetime(2026, 1, 12, 8, 0, 0), 25.0)

        filas = reportes_repo.resumen_por_origen("2026-01-05", "2026-01-12", "semana")

        self.assertEqual(len(filas), 2)
        self.assertEqual(filas[0]["etiqueta"], "Semana del 05/01 al 11/01/2026")
        self.assertEqual(filas[0]["kiosko"], 150.0)
        self.assertEqual(filas[1]["etiqueta"], "Semana del 12/01 al 18/01/2026")
        self.assertEqual(filas[1]["kiosko"], 25.0)


class TestRankingVentas(BaseConBaseTemporal):
    """reportes_repo.ranking_ventas: el Ranking de Ventas tiene que traer
    las CUATRO fuentes de venta del programa (artículo de kiosko, bono de
    PC walk-in, bono de socio, carga de saldo por tarifa), no solo los
    artículos -- pedido explícito del dueño (2026-09-30) para poder ver
    en un solo lugar qué es lo que más funciona de cada negocio."""

    def setUp(self):
        super().setUp()
        self.usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        self.hoy = date.today().isoformat()

    def _ranking(self, ordenar_por="cantidad"):
        return {f["descripcion"]: f for f in reportes_repo.ranking_ventas(self.hoy, self.hoy, ordenar_por)}

    def test_incluye_articulo_de_kiosko(self):
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 100.0, 50.0, 0)
        compras_repo.registrar_compra(self.usuario_id, [{"codigo": "COD9", "cantidad": 10, "costo_unitario": 50.0}])
        ventas_repo.confirmar_venta(
            self.usuario_id,
            [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 3, "precio_unitario": 100.0}],
            [{"metodo": "EFECTIVO", "monto": 300.0}],
        )

        fila = self._ranking()["Producto"]

        self.assertEqual(fila["categoria"], reportes_repo.CATEGORIA_KIOSKO)
        self.assertEqual(fila["codigo"], "COD9")
        self.assertEqual(fila["cantidad"], 3)
        self.assertEqual(fila["importe"], 300.0)

    def test_incluye_bono_de_pc_walkin(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("3 hs", 180, 5000.0)
        pcs_repo.asignar_bono(estacion_id, bono_id, self.usuario_id, [{"metodo": "EFECTIVO", "monto": 5000.0}])

        fila = self._ranking()["3 hs"]

        self.assertEqual(fila["categoria"], reportes_repo.CATEGORIA_BONO_PC)
        self.assertEqual(fila["cantidad"], 1)
        self.assertEqual(fila["importe"], 5000.0)

    def test_incluye_bono_de_socio(self):
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = bonos_miembro_repo.crear_bono("Combo Socio", 120, 2000.0)
        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, [{"metodo": "EFECTIVO", "monto": 2000.0}], self.usuario_id)

        fila = self._ranking()["Combo Socio"]

        self.assertEqual(fila["categoria"], reportes_repo.CATEGORIA_BONO_SOCIO)
        self.assertEqual(fila["cantidad"], 1)
        self.assertEqual(fila["importe"], 2000.0)

    def test_incluye_carga_por_tarifa_de_socio(self):
        # Tarifa por defecto (sin configurar): $1000/hora -- ver
        # config_repo.obtener_tarifa_hora_miembro.
        miembro_id = miembros_repo.crear_miembro("ana", "clave123", "Ana", "30333444", "1155556666")
        miembros_repo.cargar_saldo_por_monto(miembro_id, 1000.0, [{"metodo": "EFECTIVO", "monto": 1000.0}], self.usuario_id)

        fila = self._ranking()[reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO]

        self.assertEqual(fila["categoria"], reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO)
        self.assertEqual(fila["cantidad"], 1)
        self.assertEqual(fila["importe"], 1000.0)

    def test_no_confunde_bono_de_pc_con_bono_de_socio_del_mismo_nombre(self):
        # Los dos catálogos son independientes (ver dominio.py) -- un
        # mismo nombre de bono en cada uno no puede pisarse en el ranking.
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_pc_id = pcs_repo.crear_bono("Combo", 180, 5000.0)
        pcs_repo.asignar_bono(estacion_id, bono_pc_id, self.usuario_id, [{"metodo": "EFECTIVO", "monto": 5000.0}])

        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_socio_id = bonos_miembro_repo.crear_bono("Combo", 120, 2000.0)
        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_socio_id, [{"metodo": "EFECTIVO", "monto": 2000.0}], self.usuario_id)

        filas = [f for f in reportes_repo.ranking_ventas(self.hoy, self.hoy) if f["descripcion"] == "Combo"]

        self.assertEqual(len(filas), 2)
        categorias = {f["categoria"] for f in filas}
        self.assertEqual(categorias, {reportes_repo.CATEGORIA_BONO_PC, reportes_repo.CATEGORIA_BONO_SOCIO})

    def test_ordena_todas_las_categorias_juntas_por_cantidad(self):
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 100.0, 50.0, 0)
        compras_repo.registrar_compra(self.usuario_id, [{"codigo": "COD9", "cantidad": 10, "costo_unitario": 50.0}])
        for _ in range(5):
            ventas_repo.confirmar_venta(
                self.usuario_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": 100.0}],
                [{"metodo": "EFECTIVO", "monto": 100.0}],
            )

        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("3 hs", 180, 5000.0)
        pcs_repo.asignar_bono(estacion_id, bono_id, self.usuario_id, [{"metodo": "EFECTIVO", "monto": 5000.0}])

        filas = reportes_repo.ranking_ventas(self.hoy, self.hoy, "cantidad")

        self.assertEqual(filas[0]["descripcion"], "Producto")
        self.assertEqual(filas[0]["cantidad"], 5)

    def test_no_incluye_cargas_anuladas_ni_fuera_de_rango(self):
        miembro_id = miembros_repo.crear_miembro("ana", "clave123", "Ana", "30333444", "1155556666")
        miembros_repo.cargar_saldo_por_monto(miembro_id, 1000.0, [{"metodo": "EFECTIVO", "monto": 1000.0}], self.usuario_id)

        filas = reportes_repo.ranking_ventas("2000-01-01", "2000-01-01")

        self.assertEqual(filas, [])


class TestMigracionOrigenEnVentas(BaseConBaseTemporal):
    def test_agrega_columna_origen_y_reclasifica_ventas_viejas_de_pcs(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with database.conexion_db() as conexion:
            # Ventas armadas a mano (sin pasar por los repos) para no
            # depender de que "origen" ya exista al insertarlas -- después
            # se le saca la columna a la tabla para simular una base de
            # antes de que existiera, y recién ahí se corre la migración.
            venta_kiosko = conexion.execute(
                "INSERT INTO ventas (fecha, usuario_id, turno, total, estado) VALUES (?, ?, ?, ?, 'CONFIRMADA')",
                ("2026-01-01T10:00:00", usuario_id, "MAÑANA", 500),
            ).lastrowid
            venta_bono = conexion.execute(
                "INSERT INTO ventas (fecha, usuario_id, turno, total, estado) VALUES (?, ?, ?, ?, 'CONFIRMADA')",
                ("2026-01-01T10:00:00", usuario_id, "MAÑANA", 3000),
            ).lastrowid
            sesion_id = conexion.execute(
                "INSERT INTO sesiones_pc (estacion_id, fecha_inicio, fecha_fin_prevista, estado) "
                "VALUES (?, ?, ?, 'ACTIVA')",
                (estacion_id, "2026-01-01T10:00:00", "2026-01-01T11:00:00"),
            ).lastrowid
            conexion.execute(
                "INSERT INTO sesion_bonos (sesion_id, bono_id, minutos, precio, venta_id) VALUES (?, ?, ?, ?, ?)",
                (sesion_id, bono_id, 60, 3000, venta_bono),
            )
            venta_carga = conexion.execute(
                "INSERT INTO ventas (fecha, usuario_id, turno, total, estado) VALUES (?, ?, ?, ?, 'CONFIRMADA')",
                ("2026-01-01T10:00:00", usuario_id, "MAÑANA", 1000),
            ).lastrowid
            conexion.execute(
                "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id) "
                "VALUES (?, 'CARGA', ?, ?, ?)",
                (miembro_id, 60, "2026-01-01T10:00:00", venta_carga),
            )

            # Recién ahora se simula la base "vieja": se le saca la columna
            # que inicializar_base_de_datos() ya le había puesto, y se
            # corre la migración directo, como en TestMigracionColumnasPermisos.
            conexion.execute("ALTER TABLE ventas DROP COLUMN origen")

            database._migrar_columna_origen_en_ventas(conexion)

            self.assertEqual(
                conexion.execute("SELECT origen FROM ventas WHERE id = ?", (venta_kiosko,)).fetchone()["origen"],
                "KIOSKO",
            )
            self.assertEqual(
                conexion.execute("SELECT origen FROM ventas WHERE id = ?", (venta_bono,)).fetchone()["origen"],
                "ALQUILER_PCS",
            )
            self.assertEqual(
                conexion.execute("SELECT origen FROM ventas WHERE id = ?", (venta_carga,)).fetchone()["origen"],
                "ALQUILER_PCS",
            )


class TestMigracionReferenciaBonoEnMovimientosSaldoMiembro(BaseConBaseTemporal):
    def test_reconstruye_la_tabla_con_la_referencia_nueva_sin_perder_filas(self):
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with database.conexion_db() as conexion:
            # Se simula una base "vieja" (de antes de que existiera
            # bonos_miembro, 2026-09-28): se recrea la tabla a mano con
            # la referencia original a bonos_tiempo, y se le mete una
            # fila real -- igual que TestMigracionOrigenEnVentas simula
            # la base de antes saliéndose de columnas nuevas.
            conexion.execute("DROP TABLE movimientos_saldo_miembro")
            conexion.execute("""
                CREATE TABLE movimientos_saldo_miembro (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
                    tipo        TEXT NOT NULL CHECK (tipo IN ('CARGA', 'CONSUMO', 'REINTEGRO')),
                    minutos     INTEGER NOT NULL,
                    fecha       TEXT NOT NULL,
                    venta_id    INTEGER REFERENCES ventas(id),
                    bono_id     INTEGER REFERENCES bonos_tiempo(id),
                    sesion_id   INTEGER REFERENCES sesiones_pc(id)
                )
            """)
            movimiento_id = conexion.execute(
                "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha) "
                "VALUES (?, 'CONSUMO', ?, ?)",
                (miembro_id, 60, "2026-01-01T10:00:00"),
            ).lastrowid

            database._migrar_referencia_bono_en_movimientos_saldo_miembro(conexion)

            definicion = conexion.execute(
                "SELECT sql FROM sqlite_master WHERE name = 'movimientos_saldo_miembro'"
            ).fetchone()["sql"]
            self.assertIn("bonos_miembro(id)", definicion)
            self.assertNotIn("bonos_tiempo(id)", definicion)

            fila = conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE id = ?", (movimiento_id,)
            ).fetchone()
            self.assertEqual(fila["miembro_id"], miembro_id)
            self.assertEqual(fila["minutos"], 60)

    def test_cargar_un_bono_de_socios_con_id_que_no_existe_en_bonos_tiempo_ya_no_rompe(self):
        # Reproduce el escenario real que motivó el fix: un bono de
        # socios cuyo id no coincide con ningún walk-in -- antes de la
        # migración esto rompía con "FOREIGN KEY constraint failed"
        # porque bono_id seguía apuntando a bonos_tiempo en cualquier
        # base ya existente. BaseConBaseTemporal ya corre
        # inicializar_base_de_datos() (con la migración incluida) en su
        # setUp, así que este test cubre el caso de una base NUEVA
        # (nunca migrada a mano) para que no se rompa al revés.
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        # Solo 1 bono común (bonos_tiempo, id 1) contra 3 de socios
        # (bonos_miembro, ids 1-3) -- el tercero (id 3) no tiene ningún
        # id equivalente en bonos_tiempo.
        pcs_repo.crear_bono("1 hora (común)", 60, 3000)
        bonos_miembro_repo.crear_bono("1 hora (socios)", 60, 3000)
        bonos_miembro_repo.crear_bono("2 horas (socios)", 120, 6000)
        bono_id = bonos_miembro_repo.crear_bono("3 horas (socios)", 180, 9000)

        miembros_repo.cargar_saldo_por_bono(
            miembro_id, bono_id, [{"metodo": "EFECTIVO", "monto": 9000}], operador_id
        )

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 180)

    def test_no_rompe_si_el_bono_id_heredado_no_existe_en_bonos_miembro(self):
        # Reproduce el otro escenario real (además del de arriba): bajo el
        # esquema viejo, bono_id apuntaba a bonos_tiempo y una CARGA con
        # bono_id=1 era perfectamente válida ahí. Migrar esa fila tal cual
        # a la tabla nueva (bono_id -> bonos_miembro) rompía con FK si
        # bonos_miembro nunca tuvo un bono con ese mismo id -- antes esto
        # cortaba la migración ENTERA a mitad de copiar.
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_tiempo_id = pcs_repo.crear_bono("1 hora", 60, 3000)

        with database.conexion_db() as conexion:
            conexion.execute("DROP TABLE movimientos_saldo_miembro")
            conexion.execute("""
                CREATE TABLE movimientos_saldo_miembro (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
                    tipo        TEXT NOT NULL CHECK (tipo IN ('CARGA', 'CONSUMO', 'REINTEGRO')),
                    minutos     INTEGER NOT NULL,
                    fecha       TEXT NOT NULL,
                    venta_id    INTEGER REFERENCES ventas(id),
                    bono_id     INTEGER REFERENCES bonos_tiempo(id),
                    sesion_id   INTEGER REFERENCES sesiones_pc(id)
                )
            """)
            movimiento_id = conexion.execute(
                "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, bono_id) "
                "VALUES (?, 'CARGA', ?, ?, ?)",
                (miembro_id, 60, "2026-01-01T10:00:00", bono_tiempo_id),
            ).lastrowid

            # bonos_miembro nunca tuvo ningún bono creado: el id heredado
            # no existe ahí, aunque sí era válido en bonos_tiempo.
            self.assertIsNone(bonos_miembro_repo.obtener_bono(bono_tiempo_id))

            database._migrar_referencia_bono_en_movimientos_saldo_miembro(conexion)

            fila = conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE id = ?", (movimiento_id,)
            ).fetchone()
            self.assertEqual(fila["bono_id"], bono_tiempo_id)

    def test_recupera_movimientos_de_una_tabla_viejo_dejada_por_un_corte_anterior(self):
        # Simula el escenario del corte de luz: la tabla nueva ya quedó con
        # el esquema correcto (recreada de cero por el propio
        # CREATE TABLE IF NOT EXISTS del arranque siguiente) pero VACÍA,
        # mientras el historial real quedó atrapado en "..._viejo" porque
        # el programa se cerró antes de terminar de copiarlo la vez
        # anterior. Antes, ver la tabla nueva con el esquema ya correcto
        # bastaba para dar la migración por terminada, perdiendo ese
        # historial para siempre (invisible, nunca más migrado).
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with database.conexion_db() as conexion:
            conexion.execute("ALTER TABLE movimientos_saldo_miembro RENAME TO movimientos_saldo_miembro_viejo")
            movimiento_id = conexion.execute(
                "INSERT INTO movimientos_saldo_miembro_viejo (miembro_id, tipo, minutos, fecha) "
                "VALUES (?, 'CONSUMO', ?, ?)",
                (miembro_id, 45, "2026-01-01T10:00:00"),
            ).lastrowid
            conexion.execute("""
                CREATE TABLE movimientos_saldo_miembro (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
                    tipo        TEXT NOT NULL CHECK (tipo IN ('CARGA', 'CONSUMO', 'REINTEGRO')),
                    minutos     INTEGER NOT NULL,
                    fecha       TEXT NOT NULL,
                    venta_id    INTEGER REFERENCES ventas(id),
                    bono_id     INTEGER REFERENCES bonos_miembro(id),
                    sesion_id   INTEGER REFERENCES sesiones_pc(id)
                )
            """)

            database._migrar_referencia_bono_en_movimientos_saldo_miembro(conexion)

            fila = conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE id = ?", (movimiento_id,)
            ).fetchone()
            self.assertIsNotNone(fila)
            self.assertEqual(fila["minutos"], 45)
            tabla_vieja = conexion.execute(
                "SELECT name FROM sqlite_master WHERE name = 'movimientos_saldo_miembro_viejo'"
            ).fetchone()
            self.assertIsNone(tabla_vieja)


class TestMigracionCheckTipoEnMovimientosSaldoMiembro(BaseConBaseTemporal):
    def test_agrega_anulacion_al_check_sin_perder_filas(self):
        # Simula una base "vieja" (de antes de que existiera ANULACION,
        # 2026-09-29): recrea la tabla a mano con el CHECK original (solo
        # CARGA/CONSUMO/REINTEGRO) y una fila real, igual que
        # TestMigracionReferenciaBonoEnMovimientosSaldoMiembro simula la
        # base de antes de bonos_miembro.
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with database.conexion_db() as conexion:
            conexion.execute("DROP TABLE movimientos_saldo_miembro")
            conexion.execute("""
                CREATE TABLE movimientos_saldo_miembro (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
                    tipo        TEXT NOT NULL CHECK (tipo IN ('CARGA', 'CONSUMO', 'REINTEGRO')),
                    minutos     INTEGER NOT NULL,
                    fecha       TEXT NOT NULL,
                    venta_id    INTEGER REFERENCES ventas(id),
                    bono_id     INTEGER REFERENCES bonos_miembro(id),
                    sesion_id   INTEGER REFERENCES sesiones_pc(id)
                )
            """)
            movimiento_id = conexion.execute(
                "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha) "
                "VALUES (?, 'CONSUMO', ?, ?)",
                (miembro_id, 60, "2026-01-01T10:00:00"),
            ).lastrowid

            database._migrar_check_tipo_en_movimientos_saldo_miembro(conexion)

            # El CHECK viejo hubiera rechazado esto con
            # "CHECK constraint failed" -- si no rompe, ya se migró.
            conexion.execute(
                "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id) "
                "VALUES (?, 'ANULACION', ?, ?, ?)",
                (miembro_id, 30, "2026-01-01T10:05:00", None),
            )

            fila = conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE id = ?", (movimiento_id,)
            ).fetchone()
            self.assertEqual(fila["minutos"], 60)

    def test_recupera_movimientos_de_una_tabla_viejo_dejada_por_un_corte_anterior(self):
        # Mismo escenario de corte de luz que la migración hermana (ver
        # TestMigracionReferenciaBonoEnMovimientosSaldoMiembro): la tabla
        # nueva ya quedó con el CHECK correcto (recreada de cero por el
        # CREATE TABLE IF NOT EXISTS del arranque siguiente) pero VACÍA,
        # mientras el historial real quedó atrapado en "..._viejo".
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with database.conexion_db() as conexion:
            conexion.execute("ALTER TABLE movimientos_saldo_miembro RENAME TO movimientos_saldo_miembro_viejo")
            movimiento_id = conexion.execute(
                "INSERT INTO movimientos_saldo_miembro_viejo (miembro_id, tipo, minutos, fecha) "
                "VALUES (?, 'CONSUMO', ?, ?)",
                (miembro_id, 45, "2026-01-01T10:00:00"),
            ).lastrowid
            conexion.execute("""
                CREATE TABLE movimientos_saldo_miembro (
                    id          INTEGER PRIMARY KEY AUTOINCREMENT,
                    miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
                    tipo        TEXT NOT NULL CHECK (tipo IN ('CARGA', 'CONSUMO', 'REINTEGRO', 'ANULACION')),
                    minutos     INTEGER NOT NULL,
                    fecha       TEXT NOT NULL,
                    venta_id    INTEGER REFERENCES ventas(id),
                    bono_id     INTEGER REFERENCES bonos_miembro(id),
                    sesion_id   INTEGER REFERENCES sesiones_pc(id)
                )
            """)

            database._migrar_check_tipo_en_movimientos_saldo_miembro(conexion)

            fila = conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE id = ?", (movimiento_id,)
            ).fetchone()
            self.assertIsNotNone(fila)
            self.assertEqual(fila["minutos"], 45)
            tabla_vieja = conexion.execute(
                "SELECT name FROM sqlite_master WHERE name = 'movimientos_saldo_miembro_viejo'"
            ).fetchone()
            self.assertIsNone(tabla_vieja)


class TestDesglosePorOrigenEnCierreDeTurno(BaseConBaseTemporal):
    def test_cierre_de_turno_separa_kiosko_de_alquiler_de_pcs(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 100.0, 50.0, 5)
        compras_repo.registrar_compra(usuario_id, [{"codigo": "COD9", "cantidad": 5, "costo_unitario": 50.0}])
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])
        momento = datetime(2026, 1, 5, 10, 0, 0)

        # Una venta de kiosko en efectivo.
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": 100.0}],
                [{"metodo": "EFECTIVO", "monto": 100.0}],
            )

        # Un bono de PC pagado en digital.
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "DIGITAL", "monto": 3000}])

        # Una carga de saldo de Miembro en efectivo.
        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            miembros_repo.cargar_saldo_por_monto(
                miembro_id, 2000, [{"metodo": "EFECTIVO", "monto": 2000}], usuario_id
            )

        resumen = turnos_repo.resumen_turno_actual()
        self.assertEqual(resumen["kiosko_efectivo"], 100.0)
        self.assertEqual(resumen["kiosko_digital"], 0.0)
        self.assertEqual(resumen["pcs_efectivo"], 2000.0)
        self.assertEqual(resumen["pcs_digital"], 3000.0)
        self.assertEqual(resumen["ventas_efectivo"], 2100.0)
        self.assertEqual(resumen["ventas_digital"], 3000.0)

        cierre = turnos_repo.cerrar_turno(usuario_id)
        self.assertEqual(cierre["kiosko_efectivo"], 100.0)
        self.assertEqual(cierre["kiosko_digital"], 0.0)
        self.assertEqual(cierre["pcs_efectivo"], 2000.0)
        self.assertEqual(cierre["pcs_digital"], 3000.0)

        # El desglose tiene que quedar guardado en cierres_turno, no solo
        # devuelto una vez -- es lo que le permite al dueño auditar turno
        # por turno más adelante, no solo mirar el número de "ahora".
        guardado = turnos_repo.listar_cierres()[0]
        self.assertEqual(guardado["kiosko_efectivo"], 100.0)
        self.assertEqual(guardado["kiosko_digital"], 0.0)
        self.assertEqual(guardado["pcs_efectivo"], 2000.0)
        self.assertEqual(guardado["pcs_digital"], 3000.0)


if __name__ == "__main__":
    unittest.main()
