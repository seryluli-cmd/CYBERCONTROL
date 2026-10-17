"""Los rangos de los reportes cuentan los días como el local: de 06:00 a 06:00.

El día 1 es Mañana (06-14), Tarde (14-22) y Noche (22 a 06 del día 2): la Noche
entra ENTERA en el día 1, y la madrugada del día 1 es la Noche del día anterior
(pedido del dueño, 2026-10-17).
"""

from datetime import date, datetime, timedelta

from base import BaseConBaseTemporal
from database import conexion_db
import dominio
import turnos
from repositories import reportes_repo


def _venta(fecha: str, monto: float, turno: str = dominio.TURNO_NOCHE):
    with conexion_db() as conexion:
        venta_id = conexion.execute(
            """INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen)
               VALUES (?, 1, ?, ?, ?, ?)""",
            (fecha, turno, monto, dominio.VENTA_CONFIRMADA, dominio.ORIGEN_KIOSKO),
        ).lastrowid
        conexion.execute(
            "INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (?, ?, ?)",
            (venta_id, dominio.PAGO_EFECTIVO, monto),
        )


class TestLimitesDeReportes(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        _venta("2026-01-31T05:59:59.999999", 1)      # Noche del 30: afuera
        _venta("2026-01-31T06:00:00.000000", 10, dominio.TURNO_MANANA)
        _venta("2026-01-31T23:59:59.999999", 100)    # Noche del 31
        _venta("2026-02-01T05:59:59.999999", 1000)   # Noche del 31, pasada la medianoche
        _venta("2026-02-01T06:00:00.000000", 10000, dominio.TURNO_MANANA)  # ya es el 1/2

    def test_el_dia_va_de_las_06_a_las_06_del_dia_siguiente(self):
        resumen = reportes_repo.resumen_ventas("2026-01-31", "2026-01-31")

        self.assertEqual(resumen["cantidad_ventas"], 3)
        self.assertEqual(resumen["total"], 1110)
        self.assertEqual(resumen["efectivo"], 1110)

    def test_la_noche_entera_suma_en_el_dia_en_que_empezo(self):
        por_turno = {fila["turno"]: fila["total"] for fila in reportes_repo.resumen_por_turno("2026-01-31", "2026-01-31")}

        self.assertEqual(por_turno[dominio.TURNO_NOCHE], 1100)
        self.assertEqual(por_turno[dominio.TURNO_MANANA], 10)

    def test_agrupado_por_dia_la_madrugada_va_al_dia_anterior(self):
        filas = reportes_repo.resumen_por_origen("2026-01-30", "2026-02-01", "dia")

        self.assertEqual(
            [(fila["etiqueta"], fila["total"]) for fila in filas],
            [("30/01/2026", 1), ("31/01/2026", 1110), ("01/02/2026", 10000)],
        )


class TestDiaDelLocal(BaseConBaseTemporal):
    def test_limites_de_un_dia(self):
        self.assertEqual(
            turnos.limites_de_los_dias("2026-01-31", "2026-01-31"),
            ("2026-01-31T06:00:00", "2026-02-01T06:00:00"),
        )

    def test_hasta_las_06_sigue_siendo_el_dia_anterior(self):
        self.assertEqual(turnos.dia_en_que_empezo_el_turno(datetime(2026, 2, 1, 5, 59)), date(2026, 1, 31))
        self.assertEqual(turnos.dia_en_que_empezo_el_turno(datetime(2026, 2, 1, 6, 0)), date(2026, 2, 1))

    def test_el_turno_que_sigue_a_un_cierre_de_madrugada_es_del_dia_anterior(self):
        # La Tarde del 31 cerrada a las 00:30 del 1/2: lo que sigue es la Noche del 31.
        cierre = datetime(2026, 2, 1, 0, 30)
        self.assertEqual(turnos.turno_que_arranca_tras_un_cierre(cierre), dominio.TURNO_NOCHE)
        self.assertEqual(turnos.dia_del_turno_que_arranca_tras_un_cierre(cierre), date(2026, 1, 31))

    def test_un_cierre_de_la_noche_poco_antes_de_las_06_deja_la_manana_del_dia_nuevo(self):
        # Con la tolerancia de siempre (TURNO_GRACIA_MIN): cerrar la Noche a las 05:30
        # es cerrar la Noche, y lo que sigue es la Mañana del 1/2.
        cierre = datetime(2026, 2, 1, 6, 0) - timedelta(minutes=30)
        self.assertEqual(turnos.turno_que_arranca_tras_un_cierre(cierre), dominio.TURNO_MANANA)
        self.assertEqual(turnos.dia_del_turno_que_arranca_tras_un_cierre(cierre), date(2026, 2, 1))
