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
import http.client
import json
import os
import threading
import unittest
from datetime import datetime
from http.server import ThreadingHTTPServer
from unittest import mock

import database
import dominio
import servidor_red
from repositories import config_repo, usuarios_repo, ventas_repo
from control_pcs.repositories import (
    accesos_admin_pc_repo, clientes_repo, comandos_pc_repo, config_red_repo, miembros_repo, pcs_repo,
    bonos_miembro_repo,
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

    def _estado_a(self, momento):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.estado_estaciones()[0]

    def _conectar_a(self, estacion_id, momento):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.registrar_conexion(estacion_id)

    def _preparar_bono_en(self, momento):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        self._asignar(estacion_id, bono_id, usuario_id, momento)
        return estacion_id

    def test_bono_en_pc_apagada_corre_desde_que_se_activa_y_espera_al_cliente(self):
        # El operador habilita la PC antes de que el cliente la prenda
        # (llegan muchos juntos): el tiempo corre desde el momento de
        # activar el bono, y no es una alerta sino una espera normal.
        self._preparar_bono_en(datetime(2026, 1, 1, 10, 0, 0))

        item = self._estado_a(datetime(2026, 1, 1, 10, 20, 0))

        self.assertEqual(item["segundos_restantes"], 40 * 60)
        self.assertFalse(item["enlazada"])
        self.assertTrue(item["esperando_cliente"])

    def test_al_prenderse_la_pc_toma_el_tiempo_que_ya_venia_corriendo(self):
        estacion_id = self._preparar_bono_en(datetime(2026, 1, 1, 10, 0, 0))

        self._conectar_a(estacion_id, datetime(2026, 1, 1, 10, 20, 0))
        item = self._estado_a(datetime(2026, 1, 1, 10, 20, 5))

        self.assertTrue(item["enlazada"])
        self.assertFalse(item["esperando_cliente"])
        self.assertEqual(item["segundos_restantes"], 40 * 60 - 5)

    def test_pc_que_se_conecto_durante_la_sesion_y_deja_de_responder_es_alerta(self):
        estacion_id = self._preparar_bono_en(datetime(2026, 1, 1, 10, 0, 0))

        self._conectar_a(estacion_id, datetime(2026, 1, 1, 10, 5, 0))
        item = self._estado_a(datetime(2026, 1, 1, 10, 10, 0))

        self.assertFalse(item["enlazada"])
        self.assertFalse(item["esperando_cliente"])

    def test_pc_enlazada_justo_antes_de_activar_el_bono_y_que_se_corta_es_alerta(self):
        # Estaba prendida y enlazada cuando el operador activó el bono:
        # si después deja de responder, no es "esperando al cliente".
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        self._conectar_a(estacion_id, datetime(2026, 1, 1, 9, 59, 55))
        self._asignar(estacion_id, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))

        item = self._estado_a(datetime(2026, 1, 1, 10, 10, 0))

        self.assertFalse(item["enlazada"])
        self.assertFalse(item["esperando_cliente"])

    def _trasladar(self, origen_id, destino_id, usuario_id, momento):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.trasladar_sesion(origen_id, destino_id, usuario_id)

    def _estacion(self, estacion_id):
        return next(e for e in pcs_repo.estado_estaciones() if e["estacion"]["id"] == estacion_id)

    def test_trasladar_sesion_a_una_pc_libre_la_mueve_con_todo_su_tiempo(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pc8 = pcs_repo.crear_estacion("PC 8")
        pc15 = pcs_repo.crear_estacion("PC 15")
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        self._asignar(pc8, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        sesion_id = self._estacion(pc8)["sesion"]["id"]
        with database.conexion_db() as conexion:
            ventas_antes = conexion.execute("SELECT COUNT(*) FROM ventas").fetchone()[0]

        resultado = self._trasladar(pc8, pc15, usuario_id, datetime(2026, 1, 1, 12, 0, 0))

        self.assertEqual(resultado, {"tipo": "MOVER", "origen": "PC 8", "destino": "PC 15"})
        self.assertIsNone(self._estacion(pc8)["sesion"])
        sesion = self._estacion(pc15)["sesion"]
        self.assertEqual(sesion["id"], sesion_id)
        self.assertEqual(sesion["fecha_fin_prevista"], "2026-01-01T13:00:00")
        with database.conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM ventas").fetchone()[0], ventas_antes)

    def test_trasladar_sesion_a_una_pc_ocupada_intercambia_las_dos(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pc8 = pcs_repo.crear_estacion("PC 8")
        pc15 = pcs_repo.crear_estacion("PC 15")
        bono_1h = pcs_repo.crear_bono("1 hora", 60, 3000)
        bono_3h = pcs_repo.crear_bono("3 horas", 180, 9000)
        self._asignar(pc8, bono_1h, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        self._asignar(pc15, bono_3h, usuario_id, datetime(2026, 1, 1, 10, 0, 0))

        resultado = self._trasladar(pc8, pc15, usuario_id, datetime(2026, 1, 1, 10, 20, 0))

        self.assertEqual(resultado["tipo"], "INTERCAMBIAR")
        self.assertEqual(self._estacion(pc8)["sesion"]["fecha_fin_prevista"], "2026-01-01T13:00:00")
        self.assertEqual(self._estacion(pc15)["sesion"]["fecha_fin_prevista"], "2026-01-01T11:00:00")

    def test_trasladar_sesion_destino_con_sesion_vencida_cuenta_como_libre(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pc8 = pcs_repo.crear_estacion("PC 8")
        pc15 = pcs_repo.crear_estacion("PC 15")
        bono_1h = pcs_repo.crear_bono("1 hora", 60, 3000)
        bono_3h = pcs_repo.crear_bono("3 horas", 180, 9000)
        self._asignar(pc15, bono_1h, usuario_id, datetime(2026, 1, 1, 9, 0, 0))   # vence 10:00
        self._asignar(pc8, bono_3h, usuario_id, datetime(2026, 1, 1, 10, 30, 0))  # vence 13:30

        resultado = self._trasladar(pc8, pc15, usuario_id, datetime(2026, 1, 1, 10, 45, 0))

        self.assertEqual(resultado["tipo"], "MOVER")
        self.assertIsNone(self._estacion(pc8)["sesion"])
        self.assertEqual(self._estacion(pc15)["sesion"]["fecha_fin_prevista"], "2026-01-01T13:30:00")

    def test_trasladar_sesion_rechaza_casos_invalidos(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pc8 = pcs_repo.crear_estacion("PC 8")
        pc15 = pcs_repo.crear_estacion("PC 15")
        pc20 = pcs_repo.crear_estacion("PC 20")
        pcs_repo.desactivar_estacion(pc20)
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        momento = datetime(2026, 1, 1, 10, 30, 0)

        with self.assertRaises(ValueError):  # origen sin sesión
            self._trasladar(pc8, pc15, usuario_id, momento)

        self._asignar(pc8, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        with self.assertRaises(ValueError):  # misma PC
            self._trasladar(pc8, pc8, usuario_id, momento)
        with self.assertRaises(ValueError):  # destino desactivado
            self._trasladar(pc8, pc20, usuario_id, momento)
        with self.assertRaises(ValueError):  # la sesión de origen ya venció
            self._trasladar(pc8, pc15, usuario_id, datetime(2026, 1, 1, 11, 30, 0))

        self.assertIsNotNone(self._estacion(pc8)["sesion"])

    def test_trasladar_sesion_de_socio_mantiene_el_reintegro_correcto(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pc8 = pcs_repo.crear_estacion("PC 8")
        pc15 = pcs_repo.crear_estacion("PC 15")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 120 WHERE id = ?", (miembro_id,))
        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            miembros_repo.abrir_estacion_por_miembro(pc8, "juan", "clave123")
        sesion_id = self._estacion(pc8)["sesion"]["id"]

        self._trasladar(pc8, pc15, usuario_id, datetime(2026, 1, 1, 10, 30, 0))
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 11, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.finalizar_sesion(sesion_id)

        # Usó 60 de 120: se le reintegran los 60 que quedaban, sin
        # importar que se haya pasado de PC en el medio.
        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 60)

    def test_actividad_reciente_incluye_los_traslados(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pc8 = pcs_repo.crear_estacion("PC 8")
        pc15 = pcs_repo.crear_estacion("PC 15")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        self._asignar(pc8, bono_id, usuario_id, datetime(2026, 1, 1, 10, 0, 0))
        self._trasladar(pc8, pc15, usuario_id, datetime(2026, 1, 1, 10, 20, 0))

        traslados = [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "TRASLADO"]

        self.assertEqual(len(traslados), 1)
        self.assertEqual((traslados[0]["origen_nombre"], traslados[0]["destino_nombre"]), ("PC 8", "PC 15"))

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
        # control_pcs/ui/pcs_detalle.PanelDetalleEstacion._confirmar_bono)
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

    def test_finalizar_sesion_dos_pedidos_simultaneos_no_duplican_el_reintegro(self):
        # Reproduce el bug real: el socio cerrando desde su PC (POST
        # /logout) y la empleada tocando "Finalizar antes de tiempo" desde
        # el mostrador -- dos pedidos legítimos, cada uno en su propio
        # hilo -- podían los dos leer la sesión todavía ACTIVA antes de
        # que cualquiera terminara de cerrarla, y reintegrar el tiempo
        # restante los dos: un socio con 30 minutos por devolver terminaba
        # con 60 acreditados. Con el BEGIN IMMEDIATE de finalizar_sesion,
        # el segundo pedido espera a que el primero termine y recién ahí
        # la lee ya FINALIZADA, sin volver a reintegrar (mismo patrón que
        # test_abrir_estacion_por_miembro_dos_pedidos_simultaneos_no_duplican_el_saldo).
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 60 WHERE id = ?", (miembro_id,))

        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0)
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        barrera = threading.Barrier(2)

        def cerrar():
            barrera.wait(timeout=5)
            pcs_repo.finalizar_sesion(sesion_id)

        # El mock se aplica UNA sola vez, desde este hilo, antes de lanzar
        # los otros dos -- nunca dos mock.patch() sobre el MISMO objetivo
        # desde hilos distintos: cada entrada/salida del "with" guarda y
        # restaura pcs_repo.datetime, y dos hilos hacíendolo a la vez
        # sobre el mismo atributo es en sí mismo una carrera -- el
        # restaurado final podía quedar en un Mock a medio pisar en vez
        # de en el datetime real, rompiendo (en silencio, sin ningún
        # AssertionError acá) TODOS los tests que corrieran después en la
        # misma corrida de la suite (se confirmó así: sacando este test
        # con git stash, el resto de la suite volvía a pasar entera).
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            # 10 min usados de los 60 -> quedan 50 -> se redondea hacia
            # abajo a bloques de 30 -> corresponde reintegrar 30.
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 10, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat

            hilos = [threading.Thread(target=cerrar) for _ in range(2)]
            for hilo in hilos:
                hilo.start()
            for hilo in hilos:
                hilo.join(timeout=10)

        self.assertFalse(any(hilo.is_alive() for hilo in hilos), "un hilo quedó colgado")
        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 30)

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

    def test_finalizar_sesion_ordena_bien_aportes_del_mismo_segundo(self):
        # Reproduce el bug real: un bono y un consumo de saldo caen
        # DENTRO DEL MISMO SEGUNDO (ej. el mostrador asigna un bono y,
        # casi enseguida, un socio se loguea solo en la misma estación).
        # Antes, el consumo del socio se grababa con precisión de
        # SEGUNDO mientras que la venta del bono ya usaba microsegundos
        # -- al ordenar los aportes por fecha, el string truncado del
        # socio ("...10:00:00") quedaba ANTES que el del bono
        # ("...10:00:00.100000") aunque el socio se haya logueado 800ms
        # DESPUÉS. _reintegros_por_miembro recorre los aportes de más
        # nuevo a más viejo hasta agotar el tiempo restante: con el orden
        # invertido, el tramo sin usar se le atribuía al bono (que nunca
        # reintegra) en vez de al socio, y este perdía su saldo entero.
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        bono_mostrador_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 60 WHERE id = ?", (miembro_id,))

        # El bono arranca la sesión a las 10:00:00.100000 (fin: 11:00:00).
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0, 100000)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(
                estacion_id, bono_mostrador_id, operador_id, [{"metodo": "EFECTIVO", "monto": 3000}]
            )

        # El socio se loguea 800ms más tarde -- MISMO segundo de reloj
        # (10:00:00), pero después -- y extiende la misma sesión con sus
        # 60 min de saldo (fin queda en 12:00:00).
        with mock.patch("control_pcs.repositories.miembros_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 0, 0, 900000)
            miembros_repo.abrir_estacion_por_miembro(estacion_id, "juan", "clave123")

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        # Corta a las 11:30: quedan 30 min -- son el tramo del socio (el
        # aporte más nuevo), no del bono. Le corresponde ese reintegro
        # entero, no cero.
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 11, 30, 0)
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


class TestMinutosPorMonto(unittest.TestCase):
    """miembros_repo.minutos_por_monto: la conversión monto -> minutos que
    usan tanto el cobro (cargar_saldo_por_monto) como la vista previa de la
    pantalla de Cargar Saldo. No toca la base: recibe los tramos."""

    TRAMOS = [
        {"monto_minimo": 0, "tarifa_hora": 1000},
        {"monto_minimo": 5000, "tarifa_hora": 800},
    ]

    def test_un_monto_exacto_devuelve_los_minutos_justos(self):
        self.assertEqual(miembros_repo.minutos_por_monto(self.TRAMOS, 1500), (1000, 90))

    def test_redondea_hacia_abajo_al_bloque_de_30_minutos(self):
        # $1.400 a $1.000/h son 84 minutos: se cargan 60, nunca 90.
        self.assertEqual(miembros_repo.minutos_por_monto(self.TRAMOS, 1400), (1000, 60))

    def test_usa_la_tarifa_del_tramo_que_le_toca_al_monto(self):
        # $5.000 ya cae en el tramo de $800/h: 375 minutos -> 360.
        self.assertEqual(miembros_repo.minutos_por_monto(self.TRAMOS, 5000), (800, 360))

    def test_un_monto_que_no_alcanza_para_un_bloque_da_cero_minutos(self):
        self.assertEqual(miembros_repo.minutos_por_monto(self.TRAMOS, 100), (1000, 0))


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


class TestClientesRepo(BaseConBaseTemporal):
    def test_sin_clave_generada_todavia_devuelve_vacio(self):
        self.assertEqual(clientes_repo.obtener_clave_clientes(), "")

    def test_generar_clave_clientes_la_deja_disponible_para_leer(self):
        clave = clientes_repo.generar_clave_clientes()

        self.assertGreaterEqual(len(clave), 32)
        self.assertEqual(clientes_repo.obtener_clave_clientes(), clave)

    def test_generar_clave_clientes_de_nuevo_rota_la_anterior(self):
        clave_vieja = clientes_repo.generar_clave_clientes()
        clave_nueva = clientes_repo.generar_clave_clientes()

        self.assertNotEqual(clave_vieja, clave_nueva)
        self.assertEqual(clientes_repo.obtener_clave_clientes(), clave_nueva)

    def test_sin_clave_admin_pcs_todavia_devuelve_vacio(self):
        self.assertEqual(clientes_repo.obtener_clave_admin_pcs(), "")

    def test_establecer_clave_admin_pcs_la_deja_disponible_para_leer(self):
        clientes_repo.establecer_clave_admin_pcs("1234")

        self.assertEqual(clientes_repo.obtener_clave_admin_pcs(), "1234")

    def test_establecer_clave_admin_pcs_de_nuevo_reemplaza_la_anterior(self):
        clientes_repo.establecer_clave_admin_pcs("1234")
        clientes_repo.establecer_clave_admin_pcs("5678")

        self.assertEqual(clientes_repo.obtener_clave_admin_pcs(), "5678")


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


class _ConServidorRed(BaseConBaseTemporal):
    """
    Levanta un servidor real (puerto efímero, mismo manejador que usa
    main.py) para probar la capa HTTP de servidor_red.py -- a diferencia
    del resto de la suite, hay bugs que están en cómo servidor_red.py arma
    su respuesta y no en pcs_repo/miembros_repo (que funcionan bien solos).
    """

    def setUp(self):
        super().setUp()
        self._clave = clientes_repo.generar_clave_clientes()
        self._servidor = ThreadingHTTPServer(("127.0.0.1", 0), servidor_red._ManejadorEstado)
        self._puerto = self._servidor.server_address[1]
        self._hilo = threading.Thread(target=self._servidor.serve_forever, daemon=True)
        self._hilo.start()

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
                headers={"Authorization": "Bearer " + self._clave, "Content-Type": "application/json"},
            )
            respuesta = conexion.getresponse()
            return respuesta.status, json.loads(respuesta.read().decode("utf-8"))
        finally:
            conexion.close()

    def _post(self, ruta: str, cuerpo: dict):
        return self._pedir("POST", ruta, cuerpo)

    def _get(self, ruta: str):
        return self._pedir("GET", ruta)


class TestServidorRedLogout(_ConServidorRed):
    """POST /logout (ver _ConServidorRed)."""

    def test_logout_con_sesion_id_vieja_no_toca_la_sesion_nueva(self):
        # Reproduce el bug real: un pedido de cierre que tarda en
        # llegar/procesarse puede hacerlo DESPUÉS de que esa sesión ya se
        # cerró (el mostrador la finalizó a mano) y de que se abrió una
        # sesión NUEVA en la misma estación para otro cliente. Antes,
        # /logout solo miraba "qué sesión está activa ahora en esta
        # estación" y la cerraba, sin importar si era la que el Cliente PC
        # tenía en mente -- un pedido viejo de Juan terminaba cortándole
        # a María la sesión recién pagada.
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 8")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)

        # Sesión 1: Juan.
        pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])
        sesion_1_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        # El mostrador ya la cerró (Juan avisó que se iba).
        pcs_repo.finalizar_sesion(sesion_1_id)

        # Se habilita la misma PC para María -- sesión 2, nueva.
        pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])
        sesion_2_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]
        self.assertNotEqual(sesion_1_id, sesion_2_id)

        # Recién ahora se procesa el pedido de cierre VIEJO de Juan --
        # todavía referencia la sesión 1, que ya no existe.
        status, datos = self._post("/logout", {"estacion": "PC 8", "sesion_id": sesion_1_id})

        self.assertEqual(status, 200)
        self.assertTrue(datos["ok"])
        item = pcs_repo.estado_estaciones()[0]
        self.assertIsNotNone(item["sesion"], "la sesion de Maria no tenia que haberse cerrado")
        self.assertEqual(item["sesion"]["id"], sesion_2_id)

    def test_logout_sin_sesion_id_sigue_cerrando_lo_que_este_activo(self):
        # Compatibilidad con un Cliente PC viejo que todavía no manda
        # sesion_id: se sigue comportando como antes (cierra lo que esté
        # activo en la estación).
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 8")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])

        status, datos = self._post("/logout", {"estacion": "PC 8"})

        self.assertEqual(status, 200)
        self.assertTrue(datos["ok"])
        self.assertIsNone(pcs_repo.estado_estaciones()[0]["sesion"])

    def test_estado_y_login_devuelven_el_sesion_id(self):
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 8")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 60 WHERE id = ?", (miembro_id,))

        status, datos = self._post("/login", {"estacion": "PC 8", "usuario": "juan", "clave": "clave123"})
        self.assertEqual(status, 200)
        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]
        self.assertEqual(datos["sesion_id"], sesion_id)

        _, datos_estado = self._get("/estado?estacion=PC+8")
        self.assertEqual(datos_estado["sesion_id"], sesion_id)


class TestAccesosAdminPc(BaseConBaseTemporal):
    """Registro de lo que pasa en el panel admin de un Cliente PC
    (accesos_admin_pc_repo): quién cierra el Cliente PC y cuánto tiempo
    queda la PC sin bloqueo."""

    def setUp(self):
        super().setUp()
        self.estacion_id = pcs_repo.crear_estacion("PC 12")

    def _registrar(self, tipo, ahora, segundos_atras=0):
        with mock.patch("control_pcs.repositories.accesos_admin_pc_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = ahora
            datetime_mock.fromisoformat = datetime.fromisoformat
            accesos_admin_pc_repo.registrar_evento(self.estacion_id, tipo, segundos_atras)

    def _regreso(self, ahora):
        with mock.patch("control_pcs.repositories.accesos_admin_pc_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = ahora
            datetime_mock.fromisoformat = datetime.fromisoformat
            return accesos_admin_pc_repo.registrar_regreso_del_cliente(self.estacion_id)

    def _estado_a(self, momento):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.estado_estaciones()[0]

    def _estados_a(self, momento):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.estado_estaciones()

    def _tipos(self):
        return [e["tipo"] for e in reversed(accesos_admin_pc_repo.listar_eventos("2000-01-01", "2100-01-01"))]

    def test_entrar_al_panel_se_anota_pero_no_marca_la_pc_como_sin_cliente(self):
        self._registrar("ACCESO", datetime(2026, 1, 5, 10, 0, 0))

        self.assertEqual(self._tipos(), ["ACCESO"])
        self.assertIsNone(self._estado_a(datetime(2026, 1, 5, 10, 30, 0))["cliente_cerrado_admin_desde"])

    def test_cerrar_el_cliente_marca_la_pc_y_la_grilla_sabe_desde_cuando(self):
        self._registrar("ACCESO", datetime(2026, 1, 5, 10, 0, 0))
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 1, 0))

        item = self._estado_a(datetime(2026, 1, 5, 12, 30, 0))

        self.assertFalse(item["enlazada"])
        self.assertEqual(item["cliente_cerrado_admin_desde"], datetime(2026, 1, 5, 10, 1, 0))

    def test_reconfigurar_tambien_deja_la_pc_sin_cliente(self):
        self._registrar("RECONFIGURAR", datetime(2026, 1, 5, 10, 0, 0))

        item = self._estado_a(datetime(2026, 1, 5, 10, 10, 0))
        self.assertEqual(item["cliente_cerrado_admin_desde"], datetime(2026, 1, 5, 10, 0, 0))

    def test_al_volver_el_cliente_se_anota_cuanto_estuvo_sin_bloqueo(self):
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 0, 0))

        self.assertTrue(self._regreso(datetime(2026, 1, 5, 12, 10, 0)))

        eventos = accesos_admin_pc_repo.listar_eventos("2026-01-05", "2026-01-05")
        reanudado = eventos[0]
        self.assertEqual(reanudado["tipo"], "CLIENTE_REANUDADO")
        self.assertEqual(reanudado["fecha_hora"], "2026-01-05T12:10:00")
        self.assertEqual(reanudado["segundos_sin_cliente"], 2 * 3600 + 10 * 60)
        # La marca se limpió: la grilla ya no la muestra como sin bloqueo.
        self.assertIsNone(self._estado_a(datetime(2026, 1, 5, 12, 10, 5))["cliente_cerrado_admin_desde"])

    def test_el_regreso_se_anota_una_sola_vez(self):
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 0, 0))

        self.assertTrue(self._regreso(datetime(2026, 1, 5, 12, 0, 0)))
        self.assertFalse(self._regreso(datetime(2026, 1, 5, 12, 0, 5)))

        self.assertEqual(self._tipos(), ["CIERRE_CLIENTE", "CLIENTE_REANUDADO"])

    def test_un_regreso_sin_cierre_previo_no_anota_nada(self):
        self.assertFalse(self._regreso(datetime(2026, 1, 5, 12, 0, 0)))
        self.assertEqual(self._tipos(), [])

    def test_un_aviso_demorado_queda_con_la_hora_en_que_paso_de_verdad(self):
        # El Cliente PC no pudo avisar (servidor apagado) y lo manda una
        # hora después diciendo "esto pasó hace 3600 segundos".
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 11, 0, 0), segundos_atras=3600)

        evento = accesos_admin_pc_repo.listar_eventos("2026-01-05", "2026-01-05")[0]
        self.assertEqual(evento["fecha_hora"], "2026-01-05T10:00:00")
        self.assertEqual(
            self._estado_a(datetime(2026, 1, 5, 11, 0, 5))["cliente_cerrado_admin_desde"],
            datetime(2026, 1, 5, 10, 0, 0),
        )

    def test_segundos_atras_absurdos_se_acotan(self):
        self._registrar("ACCESO", datetime(2026, 6, 1, 10, 0, 0), segundos_atras=-500)
        self._registrar("ACCESO", datetime(2026, 6, 1, 10, 0, 0), segundos_atras=10 ** 12)

        fechas = sorted(e["fecha_hora"] for e in accesos_admin_pc_repo.listar_eventos("2000-01-01", "2100-01-01"))
        self.assertEqual(fechas[1], "2026-06-01T10:00:00")  # el negativo cuenta como "recién"
        self.assertEqual(fechas[0], "2026-05-02T10:00:00")  # y el enorme se frena en 30 días

    def test_un_aviso_viejo_que_llega_tarde_no_pisa_a_uno_mas_nuevo(self):
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 12, 0, 0))
        self._registrar("RECONFIGURAR", datetime(2026, 1, 5, 12, 5, 0), segundos_atras=3600)

        item = self._estado_a(datetime(2026, 1, 5, 12, 10, 0))
        self.assertEqual(item["cliente_cerrado_admin_desde"], datetime(2026, 1, 5, 12, 0, 0))

    def test_no_acepta_desde_afuera_el_evento_que_anota_el_servidor_ni_basura(self):
        with self.assertRaises(ValueError):
            accesos_admin_pc_repo.registrar_evento(self.estacion_id, "CLIENTE_REANUDADO")
        with self.assertRaises(ValueError):
            accesos_admin_pc_repo.registrar_evento(self.estacion_id, "LO_QUE_SEA")
        self.assertEqual(self._tipos(), [])

    def test_sesion_con_el_cliente_cerrado_por_admin_no_es_una_espera_normal(self):
        # Un bono activado en una PC que nunca se conectó es "esperando al
        # cliente" (ver pcs_repo.estado_estaciones)... salvo que alguien
        # haya cerrado el Cliente PC: ahí no va a volver solo.
        usuario_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(self.estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])

        self.assertTrue(self._estado_a(datetime(2026, 1, 5, 10, 20, 0))["esperando_cliente"])

        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 5, 0))
        item = self._estado_a(datetime(2026, 1, 5, 10, 20, 0))
        self.assertFalse(item["esperando_cliente"])
        self.assertIsNotNone(item["cliente_cerrado_admin_desde"])

    def test_apagar_la_pc_desde_cybercontrol_la_deja_de_marcar_como_sin_bloqueo_y_sin_avisos(self):
        self._registrar("ACCESO", datetime(2026, 1, 5, 10, 0, 0))
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 1, 0))
        self.assertIsNotNone(self._estado_a(datetime(2026, 1, 5, 10, 30, 0))["cliente_cerrado_admin_desde"])

        comandos_pc_repo.encolar_comando(self.estacion_id, comandos_pc_repo.TIPO_APAGAR)

        self.assertIsNone(self._estado_a(datetime(2026, 1, 5, 10, 31, 0))["cliente_cerrado_admin_desde"])
        # Cuando la PC vuelva a prenderse mañana no aparece ninguna
        # advertencia ni evento nuevo: el historial queda como estaba.
        self.assertFalse(self._regreso(datetime(2026, 1, 6, 9, 0, 0)))
        self.assertEqual(self._tipos(), ["ACCESO", "CIERRE_CLIENTE"])

    def test_reiniciar_no_cierra_el_episodio_pero_apagar_otra_pc_tampoco_toca_esta(self):
        otra_id = pcs_repo.crear_estacion("PC 13")
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 0, 0))

        comandos_pc_repo.encolar_comando(self.estacion_id, comandos_pc_repo.TIPO_REINICIAR)
        comandos_pc_repo.encolar_comando(otra_id, comandos_pc_repo.TIPO_APAGAR)

        item = next(i for i in self._estados_a(datetime(2026, 1, 5, 10, 30, 0)) if i["estacion"]["id"] == self.estacion_id)
        self.assertEqual(item["cliente_cerrado_admin_desde"], datetime(2026, 1, 5, 10, 0, 0))

    def test_listar_eventos_filtra_por_fecha_y_va_del_mas_nuevo_al_mas_viejo(self):
        self._registrar("ACCESO", datetime(2026, 1, 4, 23, 0, 0))
        self._registrar("ACCESO", datetime(2026, 1, 5, 9, 0, 0))
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 9, 1, 0))
        self._registrar("ACCESO", datetime(2026, 1, 6, 0, 0, 0))

        eventos = accesos_admin_pc_repo.listar_eventos("2026-01-05", "2026-01-05")

        self.assertEqual([e["tipo"] for e in eventos], ["CIERRE_CLIENTE", "ACCESO"])
        self.assertEqual(eventos[0]["estacion_nombre"], "PC 12")

    def test_aparece_en_la_actividad_reciente(self):
        self._registrar("CIERRE_CLIENTE", datetime(2026, 1, 5, 10, 0, 0))

        eventos = [e for e in pcs_repo.actividad_reciente() if e["tipo"] == "ADMIN_PC"]

        self.assertEqual(len(eventos), 1)
        self.assertEqual(eventos[0]["evento_admin"], "CIERRE_CLIENTE")
        self.assertEqual(eventos[0]["estacion_nombre"], "PC 12")


class TestServidorRedEventoAdmin(_ConServidorRed):
    """POST /evento_admin y el aviso de regreso en GET /estado."""

    def setUp(self):
        super().setUp()
        self.estacion_id = pcs_repo.crear_estacion("PC 12")

    def _eventos(self):
        return [e["tipo"] for e in reversed(accesos_admin_pc_repo.listar_eventos("2000-01-01", "2100-01-01"))]

    def test_el_aviso_del_cliente_queda_registrado_y_marca_la_pc(self):
        status, datos = self._post("/evento_admin", {"estacion": "PC 12", "tipo": "CIERRE_CLIENTE", "segundos_atras": 0})

        self.assertEqual(status, 200)
        self.assertTrue(datos["ok"])
        self.assertEqual(self._eventos(), ["CIERRE_CLIENTE"])
        self.assertIsNotNone(pcs_repo.obtener_estacion(self.estacion_id)["cliente_cerrado_desde"])

    def test_segundos_atras_es_opcional(self):
        status, _ = self._post("/evento_admin", {"estacion": "PC 12", "tipo": "ACCESO"})
        self.assertEqual(status, 200)

    def test_rechaza_el_evento_que_solo_anota_el_servidor_y_los_pedidos_mal_armados(self):
        self.assertEqual(self._post("/evento_admin", {"estacion": "PC 12", "tipo": "CLIENTE_REANUDADO"})[0], 400)
        self.assertEqual(self._post("/evento_admin", {"estacion": "PC 12", "tipo": "XXX"})[0], 400)
        self.assertEqual(self._post("/evento_admin", {"estacion": "PC 12"})[0], 400)
        self.assertEqual(
            self._post("/evento_admin", {"estacion": "PC 12", "tipo": "ACCESO", "segundos_atras": "mucho"})[0], 400,
        )
        self.assertEqual(self._eventos(), [])

    def test_estacion_desconocida_da_404_y_no_anota_nada(self):
        status, _ = self._post("/evento_admin", {"estacion": "PC 99", "tipo": "ACCESO"})
        self.assertEqual(status, 404)
        self.assertEqual(self._eventos(), [])

    def test_sin_la_clave_de_clientes_pc_no_se_acepta(self):
        conexion = http.client.HTTPConnection("127.0.0.1", self._puerto, timeout=5)
        try:
            conexion.request(
                "POST", "/evento_admin", body=json.dumps({"estacion": "PC 12", "tipo": "ACCESO"}),
                headers={"Authorization": "Bearer clave-equivocada"},
            )
            self.assertEqual(conexion.getresponse().status, 403)
        finally:
            conexion.close()
        self.assertEqual(self._eventos(), [])

    def test_cuando_el_cliente_vuelve_a_preguntar_su_estado_se_anota_el_regreso(self):
        self._post("/evento_admin", {"estacion": "PC 12", "tipo": "CIERRE_CLIENTE"})

        status, _ = self._get("/estado?estacion=PC+12")

        self.assertEqual(status, 200)
        self.assertEqual(self._eventos(), ["CIERRE_CLIENTE", "CLIENTE_REANUDADO"])
        self.assertIsNone(pcs_repo.obtener_estacion(self.estacion_id)["cliente_cerrado_desde"])

        # Y los siguientes pedidos normales no anotan nada más.
        self._get("/estado?estacion=PC+12")
        self.assertEqual(self._eventos(), ["CIERRE_CLIENTE", "CLIENTE_REANUDADO"])


if __name__ == "__main__":
    unittest.main()
