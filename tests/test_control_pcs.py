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
import unittest
from datetime import datetime
from unittest import mock

import database
from repositories import config_repo, usuarios_repo, ventas_repo
from control_pcs.repositories import agentes_repo, comandos_pc_repo, miembros_repo, pcs_repo, bonos_miembro_repo
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
        config_repo.actualizar_tarifa_hora_miembro(1000)
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
        config_repo.actualizar_tarifa_hora_miembro(1000)

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
        config_repo.actualizar_tarifa_hora_miembro(1000)

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
        config_repo.actualizar_tarifa_hora_miembro(1000)

        with self.assertRaises(ValueError):
            miembros_repo.cargar_saldo_por_monto(
                miembro_id, 100, [{"metodo": "EFECTIVO", "monto": 100}], operador_id
            )

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


if __name__ == "__main__":
    unittest.main()
