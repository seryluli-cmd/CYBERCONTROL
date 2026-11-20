"""
tests/test_historial_turno_anteriores.py
========================================
HISTORIAL DEL TURNO: los turnos ya cerrados y la barra del Administrador para
elegir el día y el turno (pedido del dueño, 2026-11-20: "que se guarden todos
los historiales de todos los días de todos los turnos, y poder elegir el día y el
turno; pero que al ingresar por defecto solo muestre el turno actual"; "el
operador solo puede ver su turno actual, el admin puede navegar entre todos los
días y turnos"). Salió de tests/test_historial_turno.py (regla 12), de donde
toma el turno de prueba con de todo (BaseHistorial).
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QPushButton  # noqa: E402

from database import conexion_db  # noqa: E402
from repositories import historial_turno_repo as repo, relevo_repo, turnos_repo, ventas_repo  # noqa: E402
from ui.historial_turno_barra import texto_de_la_pastilla  # noqa: E402
from ui.historial_turno_window import COLUMNA_TIPO, VentanaHistorialTurno  # noqa: E402
from base import esperar_que_avance_el_reloj  # noqa: E402
from test_historial_turno import BaseHistorial, esperar_al_segundo_siguiente  # noqa: E402


class TestTurnosAnteriores(BaseHistorial):
    """Pedido del dueño (2026-11-20): "que se guarden todos los historiales de todos
    los días de todos los turnos, y poder elegir el día y el turno"; solo el Admin."""

    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()
        self.total_al_cerrar = self.historial()["total"]
        self.cierre = turnos_repo.cerrar_turno(self.lucia_id)["id"]
        esperar_que_avance_el_reloj()

    def test_un_turno_cerrado_se_ve_entero_con_su_cierre_al_final(self):
        historial = self.historial(self.cierre)
        self.assertFalse(historial["es_el_actual"])
        self.assertEqual(historial["responsable"], "LUCIA")
        self.assertRegex(historial["cerro_a_las"], r"^\d\d:\d\d$")
        self.assertIn(self.v_pc, [v["id"] for v in historial["ventas"]])
        self.assertNotIn(self.v_de_antes, [v["id"] for v in historial["ventas"]])
        ultimo = historial["movimientos"][-1]
        self.assertEqual(ultimo["tipo"], repo.TIPO_CIERRE)
        empieza = f"LUCIA cerró la Caja Nº {historial['caja_numero']} · a retirar $ "
        self.assertTrue(ultimo["detalle"].startswith(empieza), ultimo["detalle"])

    def test_el_total_es_el_de_su_cierre(self):
        historial = self.historial(self.cierre)
        with conexion_db() as conexion:
            cierre = conexion.execute("SELECT * FROM cierres_turno WHERE id = ?", (self.cierre,)).fetchone()
        self.assertEqual(historial["total"], round(cierre["ventas_efectivo"] + cierre["ventas_digital"], 2))
        self.assertEqual(historial["total"], self.total_al_cerrar)

    def test_una_venta_anulada_despues_del_cierre_sigue_sumando_en_ese_turno(self):
        esperar_al_segundo_siguiente()
        ventas_repo.anular_venta(self.v_kiosko, self.admin_id, "se cobró mal")
        historial = self.historial(self.cierre)
        venta = self.venta(historial, self.v_kiosko)
        self.assertFalse(venta["anulada"])
        self.assertRegex(venta["nota"], r"^anulada después del cierre por Duenio el \d\d/\d\d a las \d\d:\d\d: "
                                        r"se cobró mal$")
        self.assertEqual(historial["total"], self.total_al_cerrar)

    def test_la_empleada_no_puede_mirar_otros_turnos(self):
        with self.assertRaisesRegex(PermissionError, "Solo un Administrador puede mirar los turnos anteriores"):
            repo.historial_del_turno(self.lucia_id, self.cierre)
        with self.assertRaises(PermissionError):
            repo.turnos_del_dia(self.lucia_id, self.historial()["dia"])

    def test_un_cierre_que_no_existe(self):
        with self.assertRaisesRegex(ValueError, "El cierre no existe"):
            self.historial(self.cierre + 99)

    def test_anterior_y_siguiente_van_de_a_un_turno(self):
        actual = self.historial()
        self.assertEqual((actual["anterior"], actual["siguiente"]), (self.cierre, None))
        self.assertTrue(actual["es_el_actual"])
        ultimo = self.historial(self.cierre)
        # "siguiente" None en un turno cerrado: el que sigue es el actual.
        self.assertEqual((ultimo["anterior"], ultimo["siguiente"]), (self.cierre_de_antes, None))
        primero = self.historial(self.cierre_de_antes)
        self.assertEqual((primero["anterior"], primero["siguiente"]), (None, self.cierre))
        self.assertIsNone(primero["desde"])   # el primero de todos: no hay cierre anterior

    def test_los_turnos_de_un_dia(self):
        dia = self.historial(self.cierre)["dia"]
        datos = repo.turnos_del_dia(self.admin_id, dia)
        cerrados = [t for t in datos["turnos"] if t["cierre_id"] is not None]
        self.assertEqual([t["cierre_id"] for t in cerrados], [self.cierre_de_antes, self.cierre])
        self.assertEqual(cerrados[-1]["responsable"], "LUCIA")
        self.assertRegex(cerrados[-1]["desde"], r"^\d\d:\d\d$")
        self.assertRegex(cerrados[-1]["hasta"], r"^\d\d:\d\d$")
        self.assertIsNone(cerrados[0]["desde"])
        self.assertEqual(datos["primer_dia"], dia)
        # El abierto, si es del mismo día, va último y sin hora de cierre.
        if self.historial()["dia"] == dia:
            self.assertEqual((datos["turnos"][-1]["cierre_id"], datos["turnos"][-1]["hasta"]), (None, None))
        # También con el día escrito, como llega desde otra PC.
        self.assertEqual(repo.turnos_del_dia(self.admin_id, dia.isoformat()), datos)

    def test_un_dia_sin_turnos(self):
        datos = repo.turnos_del_dia(self.admin_id, "2020-01-01")
        self.assertEqual(datos["turnos"], [])


class TestBarraDelAdmin(BaseHistorial):
    """El Admin elige el día y el turno; al abrir, siempre el actual."""

    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()
        self.cierre = turnos_repo.cerrar_turno(self.lucia_id)["id"]
        esperar_que_avance_el_reloj()
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)
        self.v_nueva = self.vender_coca(self.lucia_id)
        self.ventana = VentanaHistorialTurno(self.admin_id)
        self.addCleanup(self.ventana.deleteLater)

    def test_abre_en_el_turno_actual(self):
        self.assertTrue(self.ventana._historial["es_el_actual"])
        self.assertIn(self.v_nueva, [v["id"] for v in self.ventana._historial["ventas"]])
        barra = self.ventana.barra
        self.assertTrue(barra.boton_anterior.isEnabled())
        self.assertFalse(barra.boton_siguiente.isEnabled())
        [marcada] = [p for p in barra.pastillas if p.isChecked()]
        self.assertIn("EN CURSO", marcada.text())

    def test_el_anterior_es_el_turno_cerrado_y_se_vuelve_al_actual(self):
        self.ventana.barra.boton_anterior.click()
        historial = self.ventana._historial
        self.assertEqual(historial["cierre_id"], self.cierre)
        self.assertTrue(self.ventana.aviso.isVisibleTo(self.ventana))
        self.assertTrue(self.ventana.pastilla_cerrado.isVisibleTo(self.ventana))
        self.assertIn("cerró", self.ventana.etiqueta.text())
        self.assertEqual(self.ventana.tabla.item(self.ventana.tabla.rowCount() - 1, COLUMNA_TIPO).text(),
                         repo.TIPO_CIERRE)
        self.assertTrue(self.ventana.barra.boton_siguiente.isEnabled())
        self.ventana.aviso.boton_volver.click()
        self.assertTrue(self.ventana._historial["es_el_actual"])
        self.assertFalse(self.ventana.aviso.isVisibleTo(self.ventana))

    def test_al_cambiar_de_dia_no_quedan_las_pastillas_del_otro(self):
        barra = self.ventana.barra
        barra.campo_dia.setMinimumDate(QDate(2020, 1, 1))
        barra.campo_dia.setDate(QDate(2020, 1, 1))
        self.ventana._ir_a(self.cierre)
        en_la_barra = [boton for boton in barra.findChildren(QPushButton) if boton.property("clase") == "filtro"]
        self.assertEqual(en_la_barra, barra.pastillas)
        self.assertEqual(sum(1 for boton in en_la_barra if boton.isChecked()), 1)

    def test_siguiente_vuelve_al_actual(self):
        self.ventana.barra.boton_anterior.click()
        self.ventana.barra.boton_anterior.click()
        self.assertEqual(self.ventana._historial["cierre_id"], self.cierre_de_antes)
        self.assertFalse(self.ventana.barra.boton_anterior.isEnabled())
        self.ventana.barra.boton_siguiente.click()
        self.assertEqual(self.ventana._historial["cierre_id"], self.cierre)
        self.ventana.barra.boton_siguiente.click()
        self.assertTrue(self.ventana._historial["es_el_actual"])

    def test_tocar_la_pastilla_de_un_turno(self):
        pastilla = next(p for p, t in zip(self.ventana.barra.pastillas, self.ventana.barra.turnos)
                        if t["cierre_id"] == self.cierre)
        pastilla.click()
        self.assertEqual(self.ventana._historial["cierre_id"], self.cierre)
        self.assertTrue(pastilla.isChecked())

    def test_un_dia_sin_turnos_lo_dice(self):
        barra = self.ventana.barra
        barra.campo_dia.setMinimumDate(QDate(2020, 1, 1))
        barra.campo_dia.setDate(QDate(2020, 1, 1))
        self.assertEqual(barra.pastillas, [])
        self.assertTrue(barra.etiqueta_sin_turnos.isVisibleTo(barra))

    def test_elegir_otro_dia_muestra_su_primer_turno(self):
        dia = self.historial(self.cierre)["dia"]
        barra = self.ventana.barra
        self.ventana._ir_a(self.cierre)
        barra._cambio_el_dia(QDate(dia.year, dia.month, dia.day))
        self.assertEqual(self.ventana._historial["cierre_id"], self.cierre_de_antes)

    def test_el_texto_de_cada_pastilla(self):
        self.assertEqual(texto_de_la_pastilla({"turno_label": "Noche", "desde": "22:01", "hasta": "06:04",
                                               "responsable": "MATI", "cierre_id": 3}),
                         "NOCHE  ·  22:01 a 06:04  ·  MATI")
        self.assertEqual(texto_de_la_pastilla({"turno_label": "Tarde", "desde": "14:01", "hasta": None,
                                               "responsable": "ANTONELLA", "cierre_id": None}),
                         "●  TARDE  ·  EN CURSO desde las 14:01  ·  ANTONELLA")
        self.assertEqual(texto_de_la_pastilla({"turno_label": "Mañana", "desde": None, "hasta": "14:03",
                                               "responsable": None, "cierre_id": 1}),
                         "MAÑANA  ·  hasta las 14:03")
