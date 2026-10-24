"""
tests/test_no_viene_hace.py
===========================
"No viene hace" en Miembros (pedido del dueño, 2026-10-24): hace cuántos días
no viene cada socio, contando su última sesión de PC con su usuario y su última
carga de saldo (sin las anuladas), en días del local. En naranja pasados 15
días, con un filtro "No vienen hace más de N días" y orden con un clic en el
título. Las pantallas se prueban sin abrir ninguna ventana (plataforma
"offscreen" de Qt).
"""

import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import bonos_miembro_repo, miembros_repo, pcs_repo, ultima_visita_repo  # noqa: E402
from control_pcs.ui.miembros_window import (  # noqa: E402
    COLOR_NO_VIENE, COLOR_NUNCA_VINO, COLUMNA_NO_VIENE, MiembrosWindow, texto_no_viene,
)
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _visita(ultima):
    return {"ultima": ultima, "pc": None, "pc_desde": None, "jugando": False, "carga": None}


class TestLaCuenta(BaseConBaseTemporal):
    def test_dias_del_local(self):
        # Se fue a las 02:00: hasta las 06:00 sigue siendo "hoy" (la Noche de ayer).
        visita = _visita(datetime(2026, 10, 24, 2, 0))
        self.assertEqual(ultima_visita_repo.dias_sin_venir(visita, datetime(2026, 10, 24, 5, 0)), 0)
        self.assertEqual(ultima_visita_repo.dias_sin_venir(visita, datetime(2026, 10, 24, 7, 0)), 1)
        self.assertEqual(ultima_visita_repo.dias_sin_venir(visita, datetime(2026, 11, 8, 12, 0)), 16)
        self.assertIsNone(ultima_visita_repo.dias_sin_venir(None))

    def test_el_filtro_incluye_a_los_que_nunca_vinieron(self):
        self.assertTrue(ultima_visita_repo.no_viene_hace_mas_de(16, 15))
        self.assertFalse(ultima_visita_repo.no_viene_hace_mas_de(15, 15))
        self.assertTrue(ultima_visita_repo.no_viene_hace_mas_de(None, 15))

    def test_lo_que_dice_la_columna(self):
        self.assertEqual([texto_no_viene(d) for d in (None, 0, 1, 15, 59, 60, 95)],
                         ["Nunca vino", "Hoy", "Ayer", "15 días", "59 días", "2 meses", "3 meses"])


class BaseSocios(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.pc = pcs_repo.crear_estacion("PC07")
        self.bono = bonos_miembro_repo.crear_bono("3 horas", 180, 3000)
        self.nunca = miembros_repo.crear_miembro("nunca", "clave123", "", "", "")
        self.cargo = miembros_repo.crear_miembro("cargo", "clave123", "", "", "")
        self.jugo = miembros_repo.crear_miembro("jugo", "clave123", "", "", "")
        self.hace = lambda **cuanto: datetime.now() - timedelta(**cuanto)

    def cargar(self, miembro, cuando=None):
        venta = miembros_repo.cargar_saldo_por_bono(
            miembro, self.bono, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3000}], self.toby)["venta_id"]
        if cuando is not None:
            with conexion_db() as conexion:
                conexion.execute("UPDATE movimientos_saldo_miembro SET fecha = ? WHERE venta_id = ?",
                                 (cuando.isoformat(timespec="seconds"), venta))
        return venta

    def jugar(self, usuario, desde, hasta=None):
        """El socio entra a la PC con su usuario; con `hasta`, ya se fue."""
        sesion = miembros_repo.abrir_estacion_por_miembro(self.pc, usuario, "clave123")["sesion_id"]
        if hasta is not None:
            pcs_repo.finalizar_sesion(sesion)
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_inicio = ?, fecha_fin_real = ? WHERE id = ?",
                             (desde.isoformat(timespec="seconds"),
                              hasta.isoformat(timespec="seconds") if hasta else None, sesion))

    def dias(self, miembro_id):
        return ultima_visita_repo.dias_sin_venir(ultima_visita_repo.ultimas_visitas().get(miembro_id))


class TestDeDondeSale(BaseSocios):
    def test_nunca_vino(self):
        self.assertIsNone(self.dias(self.nunca))

    def test_por_su_ultima_carga(self):
        self.cargar(self.cargo, self.hace(days=3))
        self.assertEqual(self.dias(self.cargo), 3)

    def test_por_cuando_se_fue_de_la_pc(self):
        self.cargar(self.jugo, self.hace(days=40))
        self.jugar("jugo", self.hace(days=20, hours=3), self.hace(days=20))
        visita = ultima_visita_repo.ultimas_visitas()[self.jugo]
        self.assertEqual(self.dias(self.jugo), 20)
        self.assertEqual((visita["pc"], visita["jugando"]), ("PC07", False))

    def test_el_que_esta_jugando_vino_hoy_aunque_haya_entrado_ayer(self):
        self.cargar(self.jugo, self.hace(days=2))
        self.jugar("jugo", self.hace(days=1))
        visita = ultima_visita_repo.ultimas_visitas()[self.jugo]
        self.assertTrue(visita["jugando"])
        self.assertEqual(self.dias(self.jugo), 0)

    def test_gana_lo_mas_nuevo_y_una_carga_anulada_no_cuenta(self):
        self.cargar(self.jugo, self.hace(days=30))
        self.jugar("jugo", self.hace(days=10, hours=2), self.hace(days=10))
        anulada = self.cargar(self.jugo, self.hace(days=1))
        self.assertEqual(self.dias(self.jugo), 1)
        miembros_repo.anular_carga(anulada, self.admin, "error")
        self.assertEqual(self.dias(self.jugo), 10)


class TestEnMiembros(BaseSocios):
    def setUp(self):
        super().setUp()
        self.cargar(self.cargo, self.hace(days=3))
        self.cargar(self.jugo, self.hace(days=40))
        self.jugar("jugo", self.hace(days=20, hours=3), self.hace(days=20))

    def ventana(self):
        ventana = MiembrosWindow(usuarios_repo.obtener_usuario(self.toby))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def filas(self, ventana):
        return {ventana.tabla.item(fila, 0).text(): ventana.tabla.item(fila, COLUMNA_NO_VIENE)
                for fila in range(ventana.tabla.rowCount())}

    def test_la_columna_con_colores_y_el_detalle_al_pasar_el_mouse(self):
        filas = self.filas(self.ventana())
        self.assertEqual({usuario: item.text() for usuario, item in filas.items()},
                         {"cargo": "3 días", "jugo": "20 días", "nunca": "Nunca vino"})
        self.assertEqual(filas["jugo"].foreground().color(), COLOR_NO_VIENE)
        self.assertEqual(filas["nunca"].foreground().color(), COLOR_NUNCA_VINO)
        self.assertNotEqual(filas["cargo"].foreground().color(), COLOR_NO_VIENE)
        self.assertIn("Entró a la PC07 el", filas["jugo"].toolTip())
        self.assertIn("Última carga", filas["jugo"].toolTip())

    def test_el_filtro_de_los_que_no_vienen(self):
        ventana = self.ventana()
        ventana.check_sin_venir.setChecked(True)
        self.assertEqual(set(self.filas(ventana)), {"jugo", "nunca"})
        ventana.campo_dias_sin_venir.setValue(30)
        self.assertEqual(set(self.filas(ventana)), {"nunca"})
        ventana.campo_dias_sin_venir.setValue(2)
        self.assertEqual(set(self.filas(ventana)), {"cargo", "jugo", "nunca"})

    def test_la_tabla_sigue_ocupando_todo_el_ancho_despues_de_filtrar(self):
        # Hasta el 2026-10-24, cada búsqueda achicaba Nombre a su texto y la tabla
        # quedaba más angosta que la ventana.
        ventana = self.ventana()
        ventana.setAttribute(Qt.WA_DontShowOnScreen)
        ventana.resize(860, 400)
        ventana.show()
        self.addCleanup(ventana.hide)
        ventana.check_sin_venir.setChecked(True)
        ventana.campo_buscar.setText("o")
        _app.processEvents()
        self.assertEqual(ventana.tabla.horizontalHeader().length(), ventana.tabla.viewport().width())

    def test_ordenar_con_un_clic_en_el_titulo_y_elegir_sigue_andando(self):
        ventana = self.ventana()
        titulo = ventana.tabla.horizontalHeader()
        titulo.sectionClicked.emit(COLUMNA_NO_VIENE)
        self.assertEqual(list(self.filas(ventana)), ["nunca", "jugo", "cargo"])
        self.assertTrue(ventana.tabla.horizontalHeaderItem(COLUMNA_NO_VIENE).text().endswith("▼"))
        titulo.sectionClicked.emit(COLUMNA_NO_VIENE)
        self.assertEqual(list(self.filas(ventana)), ["cargo", "jugo", "nunca"])
        # El socio de la fila elegida es el que se ve, no el del orden de antes.
        ventana.tabla.selectRow(1)
        with mock.patch("control_pcs.ui.miembros_window.VentanaHistorialCargas") as historial:
            ventana.boton_historial.click()
        self.assertEqual(historial.call_args.args[1]["usuario"], "jugo")
        titulo.sectionClicked.emit(COLUMNA_NO_VIENE)
        self.assertEqual(list(self.filas(ventana)), ["cargo", "jugo", "nunca"])
        self.assertEqual(ventana.tabla.horizontalHeaderItem(COLUMNA_NO_VIENE).text(), "No viene hace")
