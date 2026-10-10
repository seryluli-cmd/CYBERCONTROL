"""Los rangos indexables incluyen todo el último día pedido."""

from base import BaseConBaseTemporal
from database import conexion_db
import dominio
from repositories import reportes_repo


class TestLimitesDeReportes(BaseConBaseTemporal):
    def test_ultimo_instante_del_dia_entra_y_medianoche_siguiente_no(self):
        with conexion_db() as conexion:
            for fecha, monto in (
                ("2026-01-31T23:59:59.999999", 100),
                ("2026-02-01T00:00:00", 200),
            ):
                venta_id = conexion.execute(
                    """INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen)
                       VALUES (?, 1, ?, ?, ?, ?)""",
                    (fecha, dominio.TURNO_NOCHE, monto,
                     dominio.VENTA_CONFIRMADA, dominio.ORIGEN_KIOSKO),
                ).lastrowid
                conexion.execute(
                    "INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (?, ?, ?)",
                    (venta_id, dominio.PAGO_EFECTIVO, monto),
                )

        resumen = reportes_repo.resumen_ventas("2026-01-31", "2026-01-31")
        self.assertEqual(resumen["cantidad_ventas"], 1)
        self.assertEqual(resumen["total"], 100)
        self.assertEqual(resumen["efectivo"], 100)
