"""
tests/test_control_pcs.py
============================
Tests del módulo control_pcs/ (Control de PCs + Miembros): asignar bonos,
sesiones, saldo prepago de socios. Separado de tests/test_kiosko.py
siguiendo la misma separación de código entre control_pcs/ y el resto de
la app (ver CLAUDE.md). Corre igual que el resto de la suite:

    python -m unittest discover tests
"""

import base64
import os
import threading
import unittest
from datetime import datetime
from unittest import mock

import database
import dominio
from repositories import config_repo, usuarios_repo, ventas_repo
from control_pcs.repositories import (
    agentes_repo, comandos_pc_repo, config_red_repo, miembros_repo, pcs_repo, bonos_miembro_repo,
)
from base import BaseConBaseTemporal


class TestPcsRepo(BaseConBaseTemporal):
    def _asignar(self, estacion_id, bono_id, usuario_id, momento, metodo="EFECTIVO", pagos=None):
        if pagos is None:
            precio = pcs_repo.obtener_bono(bono_id)["precio"]
            pagos = [{"metodo": metodo, "monto": precio}]
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, pagos)

    def test_asignar_bono_a_estacion_libre_crea_sesion(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)

        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))

        estados = pcs_repo.estado_estaciones()
        item = next(e for e in estados if e["estacion"]["id"] == estacion_id)
        self.assertIsNotNone(item["sesion"])
        self.assertEqual(item["sesion"]["fecha_fin_prevista"], "2026-01-01T13:00:00")

    def test_asignar_segundo_bono_a_estacion_activa_extiende_la_misma_sesion(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)

        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        sesion_id_1 = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        # Se vende un segundo bono 20 minutos después, con la sesión
        # todavía en curso: tiene que sumarse a la misma sesión (no crear
        # otra), extendiendo el vencimiento desde el que ya tenía.
        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 20, 0))

        item = pcs_repo.estado_estaciones()[0]
        self.assertEqual(item["sesion"]["id"], sesion_id_1)
        self.assertEqual(item["sesion"]["fecha_fin_prevista"], "2026-01-01T12:00:00")

    def test_asignar_bono_despues_de_vencido_cuenta_desde_ahora_no_desde_el_vencimiento_viejo(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)

        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        # La sesión anterior vencía a las 11:00; se le vende un bono
        # nuevo recién a las 11:30, ya vencida (por ejemplo porque el
        # refresco automático todavía no la dio de baja).
        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 11, 30, 0))

        item = pcs_repo.estado_estaciones()[0]
        self.assertEqual(item["sesion"]["fecha_fin_prevista"], "2026-01-01T12:30:00")

    def test_finalizar_sesion_la_saca_de_estado_estaciones(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        pcs_repo.finalizar_sesion(sesion_id)

        item = pcs_repo.estado_estaciones()[0]
        self.assertIsNone(item["sesion"])

    def test_estado_estaciones_calcula_segundos_restantes(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))

        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 45, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            item = pcs_repo.estado_estaciones()[0]

        self.assertEqual(item["segundos_restantes"], 15 * 60)

    def test_no_se_puede_asignar_un_bono_desactivado(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        pcs_repo.desactivar_bono(bono_id)

        with self.assertRaises(ValueError):
            pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])

    def test_asignar_bono_genera_una_venta_por_el_total_del_bono(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)

        venta_id = self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0),
                                  metodo="DIGITAL")

        venta, _detalle, pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["total"], 9000)
        self.assertEqual(venta["estado"], "CONFIRMADA")
        self.assertEqual(len(pagos), 1)
        self.assertEqual(pagos[0]["metodo"], "DIGITAL")
        self.assertEqual(pagos[0]["monto"], 9000)

    def test_asignar_bono_con_pago_mixto_graba_las_dos_filas_de_pago(self):
        # "Mixto" nunca es un método que se guarde: la pantalla reparte el
        # precio del bono en Efectivo + Digital (ver
        # control_pcs/ui/pcs_window.PanelDetalleEstacion._resolver_pagos)
        # y acá le llegan ya las dos filas armadas.
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)

        venta_id = self._asignar(
            estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0),
            pagos=[{"metodo": "EFECTIVO", "monto": 4000}, {"metodo": "DIGITAL", "monto": 5000}],
        )

        venta, _detalle, pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["total"], 9000)
        self.assertEqual(len(pagos), 2)
        totales = {pago["metodo"]: pago["monto"] for pago in pagos}
        self.assertEqual(totales["EFECTIVO"], 4000)
        self.assertEqual(totales["DIGITAL"], 5000)

    def test_actividad_reciente_incluye_bono_carga_y_consumo_ordenados_por_fecha(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_bono = pcs_repo.crear_estacion("PC 1")
        estacion_miembro = pcs_repo.crear_estacion("PC 2")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        pcs_repo.asignar_bono(estacion_bono, bono_id, operador_id, [{"metodo": "EFECTIVO", "monto": 3000}])

        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])
        miembros_repo.cargar_saldo_por_monto(
            miembro_id, 3000, [{"metodo": "EFECTIVO", "monto": 3000}], operador_id
        )
        miembros_repo.abrir_estacion_por_miembro(estacion_miembro, "juan", "clave123")

        eventos = pcs_repo.actividad_reciente()
        tipos = [evento["tipo"] for evento in eventos]

        self.assertIn("BONO", tipos)
        self.assertIn("CARGA", tipos)
        self.assertIn("CONSUMO", tipos)
        self.assertIn("INICIO", tipos)
        fechas = [evento["fecha"] for evento in eventos]
        self.assertEqual(fechas, sorted(fechas, reverse=True))

    def test_crear_estacion_con_nombre_de_una_desactivada_la_reactiva(self):
        # Bug real reportado por el dueño (2026-09-29): desactivar una
        # estación y volver a crearla con el mismo nombre tiraba "ya
        # existe" para siempre, porque el nombre es UNIQUE en el esquema
        # sin importar "activa" y no hay ningún botón para reactivarla.
        estacion_id = pcs_repo.crear_estacion("PC 1")
        pcs_repo.desactivar_estacion(estacion_id)

        reactivada_id = pcs_repo.crear_estacion("PC 1")

        self.assertEqual(reactivada_id, estacion_id)
        activas = [e["nombre"] for e in pcs_repo.listar_estaciones()]
        self.assertIn("PC 1", activas)

    def test_crear_estacion_con_nombre_de_una_activa_sigue_rechazando(self):
        pcs_repo.crear_estacion("PC 1")

        with self.assertRaises(ValueError):
            pcs_repo.crear_estacion("PC 1")


class TestMiembrosRepo(BaseConBaseTemporal):
    def test_crear_miembro_y_autenticar(self):
        miembros_repo.crear_miembro("juan", "clave123", "Juan Pérez", "30111222", "1155554444")

        self.assertIsNotNone(miembros_repo.autenticar_miembro("juan", "clave123"))
        self.assertIsNone(miembros_repo.autenticar_miembro("juan", "clave_mala"))
        self.assertIsNone(miembros_repo.autenticar_miembro("no_existe", "clave123"))

    def test_no_se_puede_crear_dos_miembros_con_el_mismo_usuario(self):
        miembros_repo.crear_miembro("juan", "clave123", "Juan Pérez", "30111222", "1155554444")
        with self.assertRaises(ValueError):
            miembros_repo.crear_miembro("juan", "otraClave", "Otro Juan", "30999888", "1166667777")

    def test_cargar_saldo_por_monto_redondea_a_bloques_de_30(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])

        venta_id = miembros_repo.cargar_saldo_por_monto(
            miembro_id, 13000, [{"metodo": "EFECTIVO", "monto": 13000}], operador_id
        )

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 780)  # 13 horas exactas

        venta, _detalle, pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["total"], 13000)
        self.assertEqual(pagos[0]["metodo"], "EFECTIVO")

    def test_cargar_saldo_por_monto_redondea_hacia_abajo_si_no_calza_justo(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])

        # $1300 a $1000/hora = 78 min exactos -> el bloque de 30 más
        # cercano hacia abajo es 60, nunca se regala tiempo de más.
        miembros_repo.cargar_saldo_por_monto(
            miembro_id, 1300, [{"metodo": "EFECTIVO", "monto": 1300}], operador_id
        )

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 60)

    def test_cargar_saldo_por_monto_insuficiente_no_alcanza_ni_30_min(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])

        with self.assertRaises(ValueError):
            miembros_repo.cargar_saldo_por_monto(
                miembro_id, 100, [{"metodo": "EFECTIVO", "monto": 100}], operador_id
            )

    def test_cargar_saldo_por_monto_usa_la_tarifa_del_tramo_que_corresponde(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        # Tramos a propósito NO ordenados ni crecientes -- el dueño puede
        # cargarlos en cualquier orden y con cualquier relación de precios
        # (ver dominio.validar_tramos_tarifa_hora_miembro).
        config_repo.guardar_tramos_tarifa_hora_miembro([
            {"monto_minimo": 5000, "tarifa_hora": 800},
            {"monto_minimo": 0, "tarifa_hora": 1000},
        ])

        # $4000 cae por debajo del tramo de $5000 -> tarifa de $1000/hora
        # (4000/1000*60 = 240 min).
        venta_id = miembros_repo.cargar_saldo_por_monto(
            miembro_id, 4000, [{"metodo": "EFECTIVO", "monto": 4000}], operador_id
        )
        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 240)

        # $8000 sí llega al tramo de $5000 -> tarifa de $800/hora
        # (8000/800*60 = 600 min), se suma al saldo anterior.
        miembros_repo.cargar_saldo_por_monto(
            miembro_id, 8000, [{"metodo": "EFECTIVO", "monto": 8000}], operador_id
        )
        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 240 + 600)

    def test_cargar_saldo_por_monto_debajo_del_tramo_mas_bajo_usa_igual_esa_tarifa(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 5000, "tarifa_hora": 800}])

        # No hay ningún tramo que empiece en $0 -- un monto chico no se
        # rechaza, usa igual la tarifa del único tramo que hay.
        miembros_repo.cargar_saldo_por_monto(
            miembro_id, 800, [{"metodo": "EFECTIVO", "monto": 800}], operador_id
        )

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 60)  # 800/800*60 = 60 min

    def test_cargar_saldo_por_bono(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = bonos_miembro_repo.crear_bono("5 horas", 300, 15000)

        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, [{"metodo": "DIGITAL", "monto": 15000}], operador_id)

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 300)

    def test_cargar_saldo_por_bono_usa_el_catalogo_exclusivo_de_socios_no_el_de_walk_ins(self):
        # bonos_tiempo (walk-ins) y bonos_miembro (socios) son catálogos
        # separados a propósito -- un id que existe en uno no tiene que
        # "colar" en el otro. Se crea un bono común con MISMO precio para
        # confirmar que cargar_saldo_por_bono usa el catálogo de socios
        # (300 min / $15000) y no el común (60 min / $3000).
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        pcs_repo.crear_bono("1 hora (común)", 60, 3000)
        bono_id = bonos_miembro_repo.crear_bono("5 horas (socios)", 300, 15000)

        venta_id = miembros_repo.cargar_saldo_por_bono(
            miembro_id, bono_id, [{"metodo": "EFECTIVO", "monto": 15000}], operador_id
        )

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 300)
        venta, _detalle, _pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["total"], 15000)

    def test_no_se_puede_cargar_un_bono_de_socios_desactivado(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = bonos_miembro_repo.crear_bono("5 horas", 300, 15000)
        bonos_miembro_repo.desactivar_bono(bono_id)

        with self.assertRaises(ValueError):
            miembros_repo.cargar_saldo_por_bono(
                miembro_id, bono_id, [{"metodo": "EFECTIVO", "monto": 15000}], operador_id
            )

    def test_cargar_saldo_por_bono_con_pago_mixto_graba_las_dos_filas_de_pago(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = bonos_miembro_repo.crear_bono("5 horas", 300, 15000)

        venta_id = miembros_repo.cargar_saldo_por_bono(
            miembro_id, bono_id,
            [{"metodo": "EFECTIVO", "monto": 10000}, {"metodo": "DIGITAL", "monto": 5000}],
            operador_id,
        )

        venta, _detalle, pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["total"], 15000)
        totales = {pago["metodo"]: pago["monto"] for pago in pagos}
        self.assertEqual(totales["EFECTIVO"], 10000)
        self.assertEqual(totales["DIGITAL"], 5000)

    def test_abrir_estacion_por_miembro_usa_todo_el_saldo_disponible(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = bonos_miembro_repo.crear_bono("3 horas", 180, 9000)
        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, [{"metodo": "EFECTIVO", "monto": 9000}], operador_id)

        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            resultado = miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

        self.assertEqual(resultado["minutos_usados"], 180)
        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 0)

        item = pcs_repo.estado_estaciones()[0]
        self.assertIsNotNone(item["sesion"])
        self.assertEqual(item["sesion"]["miembro_id"], miembro_id)
        self.assertEqual(item["sesion"]["fecha_fin_prevista"], "2026-01-01T13:00:00")

    def test_abrir_estacion_por_miembro_con_credenciales_invalidas(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with self.assertRaises(ValueError):
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave_mala")

    def test_abrir_estacion_por_miembro_sin_saldo_suficiente(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")

        with self.assertRaises(ValueError):
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

    def test_abrir_estacion_por_miembro_dos_pedidos_simultaneos_no_duplican_el_saldo(self):
        # Reproduce el escenario real del bug: dos pedidos concurrentes
        # (dos hilos del ThreadingHTTPServer, por doble clic o reintento
        # de red) autenticándose para el MISMO socio al mismo tiempo.
        # Antes, autenticar_miembro leía el saldo en su PROPIA transacción
        # ya comiteada, así que los dos hilos podían leer el mismo saldo y
        # terminar gastándolo los dos -- un socio con 60 minutos
        # terminaba con 120 asignados. Con el BEGIN IMMEDIATE de
        # abrir_estacion_por_miembro, el segundo pedido tiene que esperar
        # a que el primero termine y recién ahí lee el saldo ya en 0.
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 60 WHERE id = ?", (miembro_id,))

        barrera = threading.Barrier(2)
        resultados = []

        def intentar_abrir():
            barrera.wait(timeout=5)
            try:
                miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")
                resultados.append("OK")
            except ValueError:
                resultados.append("RECHAZADO")

        hilos = [threading.Thread(target=intentar_abrir) for _ in range(2)]
        for hilo in hilos:
            hilo.start()
        for hilo in hilos:
            hilo.join(timeout=10)

        # Exactamente uno de los dos se queda con el saldo -- nunca los
        # dos, y nunca ninguno.
        self.assertEqual(sorted(resultados), ["OK", "RECHAZADO"])
        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 0)

        item = pcs_repo.estado_estaciones()[0]
        segundos_restantes = item["segundos_restantes"]
        # Solo se le tienen que haber acreditado los 60 minutos originales
        # a la sesión -- nunca 120 (los de las dos "consumidas" juntas).
        self.assertLessEqual(segundos_restantes, 60 * 60)

    def test_finalizar_sesion_de_miembro_reintegra_minutos_no_usados(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = bonos_miembro_repo.crear_bono("3 horas", 180, 9000)
        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, [{"metodo": "EFECTIVO", "monto": 9000}], operador_id)

        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        # Corta a la hora exacta de haber arrancado: usó 60 de los 180
        # minutos, le quedaban 120 -> se le devuelven esos 120 al saldo.
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 11, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.finalizar_sesion(sesion_id)

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 120)

    def test_finalizar_sesion_de_bono_no_reintegra_nada(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)

        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 9000}])

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 30, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.finalizar_sesion(sesion_id)

        self.assertIsNone(pcs_repo.estado_estaciones()[0]["sesion"])

    def test_finalizar_sesion_reutilizada_reintegra_solo_el_tramo_del_socio_no_el_del_bono(self):
        # Reproduce el bug real: un socio abre una estación con su saldo
        # y, mientras sigue jugando, el mostrador le suma un bono encima
        # (mismo flujo que "cliente sigue jugando", ver asignar_bono).
        # Antes, al cortar la sesión, se le devolvía a ESE socio TODO lo
        # que quedaba sin usar -- incluido el tramo pagado con el bono,
        # que nunca debería reintegrarse.
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_socio_id = bonos_miembro_repo.crear_bono("90 min", 90, 4500)
        miembros_repo.cargar_saldo_por_bono(
            miembro_id, bono_socio_id, [{"metodo": "EFECTIVO", "monto": 4500}], operador_id
        )
        bono_mostrador_id = pcs_repo.crear_bono("1 hora", 60, 3000)

        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 5, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(
                estacion_id, bono_mostrador_id, operador_id, [{"metodo": "EFECTIVO", "monto": 3000}]
            )

        # fin_previsto quedó en 12:30 (11:30 del socio + 60 min del bono).
        # Corta a las 11:00: quedan 90 min -- 60 son del bono (se
        # pierden) y 30 son del socio (se le devuelven a ÉL, no más).
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 11, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.finalizar_sesion(sesion_id)

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 30)

    def test_finalizar_sesion_reintegra_al_socio_que_extendio_una_sesion_de_bono(self):
        # Caso inverso: una sesión arranca con un bono del mostrador y,
        # mientras sigue activa, un socio la extiende logueándose con su
        # propio saldo (mismo _abrir_o_extender_sesion compartido).
        # miembro_id solo se graba al CREAR la sesión, así que queda en
        # None -- antes esto significaba que, aunque el socio haya puesto
        # plata real (su saldo) en la sesión, cortarla antes de tiempo no
        # le devolvía nada.
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_socio_id = bonos_miembro_repo.crear_bono("90 min", 90, 4500)
        miembros_repo.cargar_saldo_por_bono(
            miembro_id, bono_socio_id, [{"metodo": "EFECTIVO", "monto": 4500}], operador_id
        )
        bono_mostrador_id = pcs_repo.crear_bono("1 hora", 60, 3000)

        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(
                estacion_id, bono_mostrador_id, operador_id, [{"metodo": "EFECTIVO", "monto": 3000}]
            )

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 10, 0)
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

        # fin_previsto quedó en 12:30 (11:00 del bono + 90 min del
        # socio). Corta a las 11:30: quedan 60 min, todos dentro del
        # tramo que puso el socio -> se le devuelven los 60, aunque la
        # sesión la haya creado originalmente un bono del mostrador.
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 11, 30, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.finalizar_sesion(sesion_id)

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 60)

    def test_anular_carga_revierte_el_saldo_y_deja_movimiento_anulacion(self):
        # Reproduce el bug real: antes, anular desde Consulta de Ventas la
        # venta que había cargado saldo a un socio le sacaba la plata del
        # cierre/caja pero le dejaba los minutos intactos, como si el
        # negocio se los hubiera regalado.
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        venta_id = miembros_repo.cargar_saldo_por_monto(
            miembro_id, 1000, [{"metodo": "EFECTIVO", "monto": 1000}], operador_id
        )
        saldo_cargado = miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"]
        self.assertGreater(saldo_cargado, 0)

        miembros_repo.anular_carga(venta_id, operador_id, "Cargado por error")

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 0)
        venta, _detalle, _pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["estado"], dominio.VENTA_ANULADA)

        with database.conexion_db() as conexion:
            movimiento = conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE venta_id = ? AND tipo = 'ANULACION'",
                (venta_id,),
            ).fetchone()
        self.assertEqual(movimiento["minutos"], saldo_cargado)
        self.assertEqual(movimiento["miembro_id"], miembro_id)

    def test_anular_carga_no_deja_el_saldo_en_negativo_si_ya_se_gasto(self):
        # Si el socio ya gastó (parte o todo) el saldo que esa carga le
        # había dado, revertir no puede sacarle más de lo que le queda --
        # ya es tiempo que se usó de verdad, no se le puede pedir de
        # vuelta. Se simula "ya gastó la mitad" tocando el saldo
        # directo (abrir_estacion_por_miembro siempre consume TODO el
        # saldo disponible, no deja armar un resto parcial fácil).
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        venta_id = miembros_repo.cargar_saldo_por_monto(
            miembro_id, 1000, [{"metodo": "EFECTIVO", "monto": 1000}], operador_id
        )
        saldo_cargado = miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"]

        with database.conexion_db() as conexion:
            conexion.execute(
                "UPDATE miembros SET saldo_minutos = saldo_minutos - ? WHERE id = ?",
                (saldo_cargado, miembro_id),
            )
        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 0)

        miembros_repo.anular_carga(venta_id, operador_id, "Cargado por error")

        # No se le puede sacar nada más: ya estaba en 0, y anular no lo
        # manda a negativo.
        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 0)
        venta, _detalle, _pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["estado"], dominio.VENTA_ANULADA)

    def test_anular_carga_de_una_venta_sin_carga_asociada_funciona_igual_que_anular_venta(self):
        # Una venta de "Alquiler de PCs" también puede ser un bono de PC
        # walk-in (sin ninguna CARGA de socio asociada) -- Consulta de
        # Ventas no distingue esto de antemano, así que anular_carga tiene
        # que poder manejarla igual que un anular_venta común.
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        venta_id = pcs_repo.asignar_bono(estacion_id, bono_id, operador_id, [{"metodo": "EFECTIVO", "monto": 3000}])

        miembros_repo.anular_carga(venta_id, operador_id, "Test")

        venta, _detalle, _pagos = ventas_repo.buscar_venta(venta_id)
        self.assertEqual(venta["estado"], dominio.VENTA_ANULADA)


class TestTramosTarifaHoraMiembroRepo(BaseConBaseTemporal):
    """config_repo.obtener_tramos_tarifa_hora_miembro/guardar_...: la
    tabla de tramos que reemplazó a la tarifa única de Socios, y su
    migración desde una base vieja que solo tenía esa tarifa única."""

    def test_base_nueva_sin_configurar_nada_da_un_tramo_de_1000_desde_0(self):
        # database.inicializar_base_de_datos ya siembra 'tarifa_hora_miembro'
        # = 1000 (ver database.py) -- una base recién creada tiene que
        # devolver exactamente eso como tramo único, sin cambiarle a
        # nadie el precio de un día para el otro.
        tramos = config_repo.obtener_tramos_tarifa_hora_miembro()
        self.assertEqual(tramos, [{"monto_minimo": 0.0, "tarifa_hora": 1000.0}])

    def test_guardar_y_releer_tramos(self):
        nuevos = [
            {"monto_minimo": 0, "tarifa_hora": 1000},
            {"monto_minimo": 5000, "tarifa_hora": 800},
        ]
        config_repo.guardar_tramos_tarifa_hora_miembro(nuevos)

        self.assertEqual(config_repo.obtener_tramos_tarifa_hora_miembro(), nuevos)

    def test_una_vez_guardados_los_tramos_nuevos_ya_no_mira_la_tarifa_unica_vieja(self):
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1500}])

        tramos = config_repo.obtener_tramos_tarifa_hora_miembro()

        self.assertEqual(tramos, [{"monto_minimo": 0, "tarifa_hora": 1500}])


class TestComandosPcRepo(BaseConBaseTemporal):
    """Control remoto de una estación (reiniciar, apagar, mensaje,
    screenshot) desde el mostrador -- ver docstring de comandos_pc_repo.py."""

    def test_proximo_comando_pendiente_devuelve_el_mas_viejo_primero(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_REINICIAR)
        id_mensaje = comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_MENSAJE, "Hola")

        primero = comandos_pc_repo.proximo_comando_pendiente(estacion_id)
        self.assertEqual(primero["tipo"], comandos_pc_repo.TIPO_REINICIAR)

        comandos_pc_repo.marcar_entregado(primero["id"])
        segundo = comandos_pc_repo.proximo_comando_pendiente(estacion_id)
        self.assertEqual(segundo["id"], id_mensaje)
        self.assertEqual(segundo["payload"], "Hola")

    def test_marcar_entregado_lo_saca_de_pendientes_para_siempre(self):
        estacion_id = pcs_repo.crear_estacion("PC 1")
        comando_id = comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_APAGAR)

        comandos_pc_repo.marcar_entregado(comando_id)

        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(estacion_id))
        self.assertEqual(comandos_pc_repo.obtener_comando(comando_id)["estado"], "ENTREGADO")

    def test_comandos_pendientes_de_otra_estacion_no_se_mezclan(self):
        estacion_1 = pcs_repo.crear_estacion("PC 1")
        estacion_2 = pcs_repo.crear_estacion("PC 2")
        comandos_pc_repo.encolar_comando(estacion_1, comandos_pc_repo.TIPO_REINICIAR)

        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(estacion_2))

    def test_guardar_screenshot_deja_el_archivo_en_la_carpeta_temporal_de_datos(self):
        # No en la carpeta "data" real -- database.DATA_DIR está apuntado
        # a un directorio temporal por BaseConBaseTemporal.setUp(), y
        # guardar_screenshot tiene que respetar eso (ver el comentario en
        # comandos_pc_repo.py sobre por qué no es una constante de módulo).
        estacion_id = pcs_repo.crear_estacion("PC 1")
        comando_id = comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_SCREENSHOT)
        imagen_falsa = base64.b64encode(b"no es un PNG real, solo bytes de prueba").decode("ascii")

        ruta_relativa = comandos_pc_repo.guardar_screenshot(comando_id, imagen_falsa)
        comandos_pc_repo.marcar_resultado(comando_id, ruta_relativa)

        ruta_completa = os.path.join(database.DATA_DIR, ruta_relativa)
        self.assertTrue(os.path.exists(ruta_completa))
        with open(ruta_completa, "rb") as archivo:
            self.assertEqual(archivo.read(), b"no es un PNG real, solo bytes de prueba")
        self.assertEqual(comandos_pc_repo.obtener_comando(comando_id)["resultado"], ruta_relativa)


class TestAgentesRepo(BaseConBaseTemporal):
    def test_sin_clave_generada_todavia_devuelve_vacio(self):
        self.assertEqual(agentes_repo.obtener_clave_agentes(), "")

    def test_generar_clave_agentes_la_deja_disponible_para_leer(self):
        clave = agentes_repo.generar_clave_agentes()

        self.assertGreaterEqual(len(clave), 32)
        self.assertEqual(agentes_repo.obtener_clave_agentes(), clave)

    def test_generar_clave_agentes_de_nuevo_rota_la_anterior(self):
        clave_vieja = agentes_repo.generar_clave_agentes()
        clave_nueva = agentes_repo.generar_clave_agentes()

        self.assertNotEqual(clave_vieja, clave_nueva)
        self.assertEqual(agentes_repo.obtener_clave_agentes(), clave_nueva)

    def test_sin_clave_admin_pcs_todavia_devuelve_vacio(self):
        self.assertEqual(agentes_repo.obtener_clave_admin_pcs(), "")

    def test_establecer_clave_admin_pcs_la_deja_disponible_para_leer(self):
        agentes_repo.establecer_clave_admin_pcs("1234")

        self.assertEqual(agentes_repo.obtener_clave_admin_pcs(), "1234")

    def test_establecer_clave_admin_pcs_de_nuevo_reemplaza_la_anterior(self):
        agentes_repo.establecer_clave_admin_pcs("1234")
        agentes_repo.establecer_clave_admin_pcs("5678")

        self.assertEqual(agentes_repo.obtener_clave_admin_pcs(), "5678")


class TestConfigRedRepo(BaseConBaseTemporal):
    """Catálogo de módems del local (ver "Cambiar red..." en Control de
    PCs) -- ver docstring de config_red_repo.py."""

    def test_sin_nada_guardado_todavia_devuelve_los_dos_modems_de_ejemplo(self):
        gateways = config_red_repo.obtener_gateways()

        self.assertEqual(
            [g["ip"] for g in gateways], ["192.168.1.201", "192.168.1.202"]
        )

    def test_guardar_gateways_reemplaza_la_lista_entera(self):
        config_red_repo.guardar_gateways([{"nombre": "Fibra", "ip": "192.168.1.50"}])

        self.assertEqual(
            config_red_repo.obtener_gateways(), [{"nombre": "Fibra", "ip": "192.168.1.50"}]
        )

    def test_guardar_gateways_dos_veces_pisa_la_version_anterior(self):
        config_red_repo.guardar_gateways([{"nombre": "Módem A", "ip": "192.168.1.201"}])
        config_red_repo.guardar_gateways([{"nombre": "Módem B", "ip": "192.168.1.202"}])

        self.assertEqual(
            config_red_repo.obtener_gateways(), [{"nombre": "Módem B", "ip": "192.168.1.202"}]
        )

    def test_es_ip_valida_acepta_ips_bien_formadas(self):
        self.assertTrue(config_red_repo.es_ip_valida("192.168.1.201"))
        self.assertTrue(config_red_repo.es_ip_valida("10.0.0.1"))

    def test_es_ip_valida_rechaza_octetos_fuera_de_rango_y_texto_libre(self):
        self.assertFalse(config_red_repo.es_ip_valida("192.168.1.999"))
        self.assertFalse(config_red_repo.es_ip_valida("no es una ip"))
        self.assertFalse(config_red_repo.es_ip_valida(""))
        self.assertFalse(config_red_repo.es_ip_valida("192.168.1"))


if __name__ == "__main__":
    unittest.main()
