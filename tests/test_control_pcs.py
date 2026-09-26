"""
tests/test_control_pcs.py
============================
Tests del módulo control_pcs/ (Control de PCs + Miembros): asignar bonos,
sesiones, saldo prepago de socios. Separado de tests/test_kiosko.py
siguiendo la misma separación de código entre control_pcs/ y el resto de
la app (ver CLAUDE.md). Corre igual que el resto de la suite:

    python -m unittest discover tests
"""

import unittest
from datetime import datetime
from unittest import mock

from repositories import config_repo, usuarios_repo, ventas_repo
from control_pcs.repositories import miembros_repo, pcs_repo
from base import BaseConBaseTemporal


class TestPcsRepo(BaseConBaseTemporal):
    def _asignar(self, estacion_id, bono_id, usuario_id, momento, metodo="EFECTIVO"):
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
            return pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, metodo)

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
            pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, "EFECTIVO")

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

    def test_actividad_reciente_incluye_bono_carga_y_consumo_ordenados_por_fecha(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_bono = pcs_repo.crear_estacion("PC 1")
        estacion_miembro = pcs_repo.crear_estacion("PC 2")
        bono_id = pcs_repo.crear_bono("1 hora", 60, 3000)
        pcs_repo.asignar_bono(estacion_bono, bono_id, operador_id, "EFECTIVO")

        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.actualizar_tarifa_hora_miembro(1000)
        miembros_repo.cargar_saldo_por_monto(miembro_id, 3000, "EFECTIVO", operador_id)
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

        venta_id = miembros_repo.cargar_saldo_por_monto(miembro_id, 13000, "EFECTIVO", operador_id)

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
        miembros_repo.cargar_saldo_por_monto(miembro_id, 1300, "EFECTIVO", operador_id)

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 60)

    def test_cargar_saldo_por_monto_insuficiente_no_alcanza_ni_30_min(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        config_repo.actualizar_tarifa_hora_miembro(1000)

        with self.assertRaises(ValueError):
            miembros_repo.cargar_saldo_por_monto(miembro_id, 100, "EFECTIVO", operador_id)

    def test_cargar_saldo_por_bono(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = pcs_repo.crear_bono("5 horas", 300, 15000)

        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, "DIGITAL", operador_id)

        miembro = miembros_repo.obtener_miembro(miembro_id)
        self.assertEqual(miembro["saldo_minutos"], 300)

    def test_abrir_estacion_por_miembro_usa_todo_el_saldo_disponible(self):
        operador_id = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        estacion_id = pcs_repo.crear_estacion("PC 1")
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, "EFECTIVO", operador_id)

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
        bono_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        miembros_repo.cargar_saldo_por_bono(miembro_id, bono_id, "EFECTIVO", operador_id)

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
            pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, "EFECTIVO")

        sesion_id = pcs_repo.estado_estaciones()[0]["sesion"]["id"]

        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 1, 10, 30, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.finalizar_sesion(sesion_id)

        self.assertIsNone(pcs_repo.estado_estaciones()[0]["sesion"])


if __name__ == "__main__":
    unittest.main()
