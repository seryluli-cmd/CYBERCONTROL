"""
tests/test_noche_del_dia.py
==============================
El día del local va de 06:00 a 06:00 (pedido del dueño, 2026-10-17): el día 1 es
Mañana (06-14), Tarde (14-22) y Noche (22 a 06 del día 2), y la Noche entra
ENTERA en el día 1 aunque termine el día 2. Acá se prueba que el Resumen del Día
lo respete también cuando un cierre cae pasada la medianoche (la Noche cerrada
dos veces porque cambió quien atendía, o la Tarde cerrada tarde), que Caja
nombre bien ese turno, y que el "hoy" de los reportes siga siendo el día 1
hasta las 06:00. Los límites de los demás reportes están en
tests/test_reportes_fechas.py.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import date, datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from repositories import articulos_repo, compras_repo, turnos_repo, usuarios_repo, ventas_repo  # noqa: E402
from ui import utils  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class _ConTurnos(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", "ADMIN")
        self.lucia_id = usuarios_repo.crear_usuario("Lucia", "1234", "EMPLEADA")
        self.pedro_id = usuarios_repo.crear_usuario("Pedro", "1234", "EMPLEADA")
        articulos_repo.crear_articulo("COD9", "Producto", None, None, 10.0, 5.0, 0)
        compras_repo.registrar_compra(self.admin_id, [{"codigo": "COD9", "cantidad": 50, "costo_unitario": 5.0}])

    def _vender(self, momento, total):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            return ventas_repo.confirmar_venta(
                self.lucia_id,
                [{"codigo": "COD9", "descripcion": "Producto", "cantidad": 1, "precio_unitario": total}],
                [{"metodo": "EFECTIVO", "monto": total}],
            )

    def _con_reloj(self, momento):
        parche = mock.patch("repositories.turnos_repo.datetime")
        datetime_mock = parche.start()
        self.addCleanup(parche.stop)
        datetime_mock.now.return_value = momento
        datetime_mock.fromisoformat = datetime.fromisoformat

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

    @staticmethod
    def _por_turno(resumen):
        return {fila["etiqueta"]: fila for fila in resumen["turnos"]}


class TestLaNocheEntraEnteraEnElDiaEnQueEmpezo(_ConTurnos):
    """Lunes 5 de enero de 2026: Mañana, Tarde y Noche (que termina el martes 6)."""

    def test_noche_cerrada_dos_veces_pasada_la_medianoche(self):
        # Lucía atiende la Noche hasta las 02:00 y cierra; sigue Pedro hasta las 06:05.
        self._cerrar(datetime(2026, 1, 5, 6, 0))
        self._vender(datetime(2026, 1, 5, 9, 0), 10.0)
        self._cerrar(datetime(2026, 1, 5, 14, 5))
        self._vender(datetime(2026, 1, 5, 15, 0), 20.0)
        self._cerrar(datetime(2026, 1, 5, 22, 5))
        self._vender(datetime(2026, 1, 5, 23, 0), 5.0)
        self._cerrar(datetime(2026, 1, 6, 2, 0), self.lucia_id)
        self._vender(datetime(2026, 1, 6, 3, 0), 7.0)
        self._cerrar(datetime(2026, 1, 6, 6, 5), self.pedro_id)

        lunes = self._por_turno(self._resumen(date(2026, 1, 5), datetime(2026, 1, 6, 10, 0)))
        martes = self._por_turno(self._resumen(date(2026, 1, 6), datetime(2026, 1, 6, 10, 0)))

        self.assertEqual(lunes["Noche"]["total"], 12.0)
        self.assertEqual(lunes["Noche"]["estado"], turnos_repo.ESTADO_CERRADO)
        self.assertEqual(lunes["Noche"]["responsables"], ["Lucia", "Pedro"])
        self.assertEqual(sum(fila["total"] for fila in lunes.values()), 10.0 + 20.0 + 12.0)
        # La Noche del martes todavía no empezó: nada de la madrugada del martes va ahí.
        self.assertEqual(martes["Noche"]["total"], 0.0)
        self.assertEqual(martes["Noche"]["estado"], turnos_repo.ESTADO_PENDIENTE)

    def test_tarde_cerrada_pasada_la_medianoche(self):
        # Se olvidaron de cerrar la Tarde y la cerraron a las 00:30: lo que sigue
        # hasta las 06:00 es la Noche del lunes, no la del martes.
        self._cerrar(datetime(2026, 1, 5, 6, 0))
        self._cerrar(datetime(2026, 1, 5, 14, 5))
        self._vender(datetime(2026, 1, 5, 15, 0), 20.0)
        self._cerrar(datetime(2026, 1, 6, 0, 30))
        self._vender(datetime(2026, 1, 6, 1, 0), 7.0)
        self._cerrar(datetime(2026, 1, 6, 6, 5))

        lunes = self._por_turno(self._resumen(date(2026, 1, 5), datetime(2026, 1, 6, 10, 0)))
        martes = self._por_turno(self._resumen(date(2026, 1, 6), datetime(2026, 1, 6, 10, 0)))

        self.assertEqual(lunes["Tarde"]["total"], 20.0)
        self.assertEqual(lunes["Noche"]["total"], 7.0)
        self.assertEqual(lunes["Noche"]["estado"], turnos_repo.ESTADO_CERRADO)
        self.assertEqual(martes["Noche"]["total"], 0.0)

    def test_la_noche_en_curso_de_madrugada_se_ve_en_el_dia_en_que_empezo(self):
        self._cerrar(datetime(2026, 1, 5, 22, 5))
        self._cerrar(datetime(2026, 1, 6, 2, 0))  # cambio de quien atiende
        self._vender(datetime(2026, 1, 6, 3, 0), 7.0)

        lunes = self._por_turno(self._resumen(date(2026, 1, 5), datetime(2026, 1, 6, 4, 0)))

        self.assertEqual(lunes["Noche"]["estado"], turnos_repo.ESTADO_EN_CURSO)
        self.assertEqual(lunes["Noche"]["total"], 7.0)

    def test_caja_nombra_bien_la_noche_del_domingo_pasada_la_medianoche(self):
        # Domingo 4 de enero: la Noche es "Domingo T2" (18 a 06 del lunes). Cerrada
        # una vez a las 02:00 del lunes, lo que sigue sigue siendo "Domingo T2".
        self._cerrar(datetime(2026, 1, 4, 18, 5))
        self._cerrar(datetime(2026, 1, 5, 2, 0))
        self._con_reloj(datetime(2026, 1, 5, 3, 0))

        caja = turnos_repo.resumen_turno_actual()

        self.assertEqual(caja["turno_actual_label"], "Domingo T2")


class TestHoyDeLosReportes(_ConTurnos):
    def _hoy_a_las(self, momento):
        with mock.patch("ui.utils.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            return utils.hoy_del_local()

    def test_hasta_las_06_hoy_es_el_dia_anterior(self):
        self.assertEqual(self._hoy_a_las(datetime(2026, 1, 6, 2, 0)), QDate(2026, 1, 5))
        self.assertEqual(self._hoy_a_las(datetime(2026, 1, 6, 6, 0)), QDate(2026, 1, 6))

    def test_solo_hoy_de_un_reporte_es_el_dia_del_local(self):
        buscar = mock.Mock()
        with mock.patch("ui.utils.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 6, 2, 0)
            desde, hasta, _ = utils.armar_filtro_por_fechas(buscar, solo_hoy=True, dias_del_local=True)

        self.assertEqual((desde.date(), hasta.date()), (QDate(2026, 1, 5), QDate(2026, 1, 5)))
