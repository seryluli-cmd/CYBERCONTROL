"""
tests/test_historial_turno.py
=============================
HISTORIAL DEL TURNO (botón de debajo del mosaico, a la derecha de CONTROL DE
STOCK; pedido del dueño, 2026-11-02, maqueta A): todo lo cobrado en el turno
abierto, venta por venta, con su rubro, qué se cobró, cómo se pagó y el total.
Las mismas ventas que suma el Cierre de Turno. El botón lo ven todos, pero solo
el Admin lo abre. Ver repositories/historial_turno_repo.py y
ui/historial_turno_window.py. Las pantallas se prueban sin abrir ninguna ventana
(plataforma "offscreen" de Qt).
"""

import os
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from admin_remoto import lista_blanca  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    bonos_miembro_repo, miembros_repo, pcs_repo, pcstream_repo, playstation_repo,
)
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from repositories import (  # noqa: E402
    articulos_repo, historial_turno_repo as repo, impresiones_repo, relevo_repo, tramites_repo, turnos_repo,
    usuarios_repo, ventas_repo,
)
from ui.historial_turno_window import (  # noqa: E402
    COLUMNA_PAGO, COLUMNA_RUBRO, COLUMNA_TOTAL, FILTRO_ANULADAS, BotonHistorialTurno, VentanaHistorialTurno,
)
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _digital(monto):
    return [{"metodo": dominio.PAGO_DIGITAL, "monto": monto}]


class BaseHistorial(BaseConBaseTemporal):
    """Un turno de Lucía con de todo: lo de antes del último cierre no es de este turno."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.lucia_id = usuarios_repo.crear_usuario("LUCIA", "4321", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 0)
        articulos_repo.crear_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "Impresión B/N", None, None,
                                      200.0, 0.0, 0)
        self.pc = pcs_repo.crear_estacion("PC12X")
        self.pcstream = pcs_repo.crear_estacion(dominio.NOMBRE_PCSTREAM)
        self.bono_pc = pcs_repo.crear_bono("Promo 5hs", 300, 8000.0)
        self.bono_stream = pcstream_repo.crear_bono("1 hora", 60, 2000.0)
        self.bono_ps5 = playstation_repo.crear_bono(self.admin_id, "Promo 2hs", 120, 6000.0)
        self.bono_socio = bonos_miembro_repo.crear_bono("Promo 10hs", 600, 9700.0)
        self.tramite = tramites_repo.crear_tramite("Turno ANSES")
        self.socio = miembros_repo.crear_miembro("ulises", "1111", nombre="Ulises")

    def vender_coca(self, usuario_id, cantidad=1, pagos=None):
        return ventas_repo.confirmar_venta(
            usuario_id, [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": cantidad,
                          "precio_unitario": 1000.0}],
            pagos or _efectivo(1000.0 * cantidad),
        )

    def turno_con_de_todo(self):
        """Un turno cerrado de antes (no tiene que salir) y el de Lucía, abierto."""
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)
        self.v_de_antes = self.vender_coca(self.lucia_id, 5)
        turnos_repo.cerrar_turno(self.lucia_id)
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)

        self.v_kiosko = self.vender_coca(self.lucia_id, 2)
        self.v_pc = pcs_repo.asignar_bono(self.pc, self.bono_pc, self.lucia_id, _efectivo(8000.0))
        self.v_stream = pcs_repo.asignar_bono(self.pcstream, self.bono_stream, self.lucia_id, _digital(2000.0))
        self.v_ps5 = playstation_repo.vender_bono(self.lucia_id, self.bono_ps5, _efectivo(6000.0))
        self.v_socio = miembros_repo.cargar_saldo_por_bono(
            self.socio, self.bono_socio, _digital(9700.0), self.lucia_id)["venta_id"]
        self.v_carga = miembros_repo.cargar_saldo_por_monto(
            self.socio, 3000.0, _efectivo(3000.0), self.lucia_id)["venta_id"]
        self.v_tramite = tramites_repo.registrar_tramite(self.lucia_id, self.tramite, 1500.0, _efectivo(1500.0))
        self.v_impresiones = impresiones_repo.cobrar_impresiones(self.lucia_id, 14, 200.0, _efectivo(2800.0))
        self.v_mixta = ventas_repo.confirmar_venta(
            self.lucia_id,
            [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": 1, "precio_unitario": 1000.0},
             {"codigo": dominio.CODIGO_ARTICULO_IMPRESIONES, "descripcion": "Impresión B/N", "cantidad": 2,
              "precio_unitario": 200.0}],
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 700.0}, {"metodo": dominio.PAGO_DIGITAL, "monto": 700.0}],
        )
        self.v_repetida = pcs_repo.asignar_bono(self.pc, self.bono_pc, self.lucia_id, _efectivo(8000.0))
        ventas_repo.anular_venta(self.v_repetida, self.admin_id, "cargado 2 veces")
        # El Admin cobra con la caja de Lucía abierta: queda a nombre de ella.
        self.v_admin = self.vender_coca(self.admin_id, 1)

    def historial(self):
        return repo.historial_del_turno(self.admin_id)

    def venta(self, historial, venta_id):
        return next(v for v in historial["ventas"] if v["id"] == venta_id)


class TestQueSeCobro(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()

    def test_cada_venta_con_su_rubro_y_lo_que_se_cobro(self):
        historial = self.historial()
        esperado = {
            self.v_kiosko: (repo.RUBRO_KIOSKO, "2 x Coca 500"),
            self.v_pc: (repo.RUBRO_BONO_PC, "PC12X · Promo 5hs (5 h)"),
            self.v_stream: (repo.RUBRO_PCSTREAM, f"{dominio.NOMBRE_PCSTREAM} · 1 hora (1 h)"),
            self.v_ps5: (repo.RUBRO_PS5, f"{dominio.NOMBRE_PLAYSTATION} · Promo 2hs (2 h)"),
            self.v_socio: (repo.RUBRO_MIEMBRO, "Socio Ulises · Promo 10hs (10 h)"),
            self.v_tramite: (repo.RUBRO_TRAMITE, "Trámite: Turno ANSES"),
            self.v_impresiones: (repo.RUBRO_IMPRESIONES, "14 x Impresión B/N"),
        }
        for venta_id, (rubro, detalle) in esperado.items():
            venta = self.venta(historial, venta_id)
            self.assertEqual((venta["rubro"], venta["detalle"]), (rubro, detalle))
        carga = self.venta(historial, self.v_carga)
        self.assertEqual(carga["rubro"], repo.RUBRO_MIEMBRO)
        self.assertTrue(carga["detalle"].startswith("Socio Ulises · carga de saldo ("), carga["detalle"])

    def test_impresiones_con_otra_cosa_es_kiosko_pero_sale_al_filtrar_impresiones(self):
        mixta = self.venta(self.historial(), self.v_mixta)
        self.assertEqual(mixta["rubro"], repo.RUBRO_KIOSKO)
        self.assertEqual(set(mixta["rubros"]), {repo.RUBRO_KIOSKO, repo.RUBRO_IMPRESIONES})

    def test_lo_de_antes_del_ultimo_cierre_no_es_de_este_turno(self):
        ids = [venta["id"] for venta in self.historial()["ventas"]]
        self.assertNotIn(self.v_de_antes, ids)
        self.assertEqual(ids, sorted(ids))   # de la primera a la última

    def test_hora_y_forma_de_pago(self):
        historial = self.historial()
        self.assertEqual(self.venta(historial, self.v_pc)["pago"], repo.PAGO_EFECTIVO)
        self.assertEqual(self.venta(historial, self.v_stream)["pago"], repo.PAGO_DIGITAL)
        self.assertEqual(self.venta(historial, self.v_mixta)["pago"], repo.PAGO_LOS_DOS)
        venta = self.venta(historial, self.v_pc)
        self.assertEqual(venta["hora"], datetime.fromisoformat(venta["fecha"]).strftime("%H:%M"))

    def test_la_anulada_dice_quien_cuando_y_por_que_y_no_suma(self):
        historial = self.historial()
        repetida = self.venta(historial, self.v_repetida)
        self.assertTrue(repetida["anulada"])
        self.assertRegex(repetida["nota"], r"^anulada por Duenio a las \d\d:\d\d: cargado 2 veces$")
        self.assertEqual(historial["anuladas"], 1)
        self.assertEqual(historial["cantidad"], len(historial["ventas"]) - 1)

    def test_lo_que_cobro_el_admin_queda_en_la_caja_de_ella_y_lo_dice(self):
        venta = self.venta(self.historial(), self.v_admin)
        self.assertEqual(venta["operador"], "LUCIA")
        self.assertEqual(venta["nota"], "cobró Duenio")

    def test_el_total_es_el_mismo_que_el_del_cierre_de_turno(self):
        historial = self.historial()
        cierre = turnos_repo.resumen_turno_actual()
        self.assertEqual(historial["total"], cierre["ventas_total"])
        self.assertEqual(historial["efectivo"], cierre["ventas_efectivo"])
        self.assertEqual(historial["digital"], cierre["ventas_digital"])
        self.assertEqual(historial["total"], 2000 + 8000 + 2000 + 6000 + 9700 + 3000 + 1500 + 2800 + 1400 + 1000)

    def test_la_caja_de_quien_agarro_el_turno(self):
        historial = self.historial()
        caja = relevo_repo.estado_de_la_caja()
        self.assertEqual(historial["caja_numero"], caja["caja_numero"])
        self.assertEqual(historial["responsable"], "LUCIA")
        self.assertRegex(historial["abrio_a_las"], r"^\d\d:\d\d$")
        self.assertEqual(historial["turno_label"], caja["turno_label"])


class TestSoloElAdmin(BaseHistorial):
    def test_una_empleada_no_puede(self):
        with self.assertRaisesRegex(PermissionError, "Solo un Administrador puede ver el Historial del Turno"):
            repo.historial_del_turno(self.lucia_id)

    def test_se_puede_mirar_desde_otra_pc_a_nombre_del_admin_que_entro(self):
        self.assertTrue(lista_blanca.permitida("historial_turno_repo", "historial_del_turno"))
        self.assertEqual(lista_blanca.ACTOR[("historial_turno_repo", "historial_del_turno")], "usuario_id")

    def test_sin_caja_abierta_es_lo_vendido_desde_el_ultimo_cierre(self):
        venta = self.vender_coca(self.lucia_id)
        historial = self.historial()
        self.assertIsNone(historial["caja_numero"])
        self.assertEqual([v["id"] for v in historial["ventas"]], [venta])


class TestVentana(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()

    def ventana(self):
        ventana = VentanaHistorialTurno(self.admin_id)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def filas(self, ventana, columna):
        return [ventana.tabla.item(fila, columna).text() for fila in range(ventana.tabla.rowCount())]

    def elegir(self, ventana, texto):
        next(p for p in ventana.filtros.pastillas if p.text() == texto.upper()).click()

    def test_muestra_todo_el_turno_con_la_caja_arriba(self):
        ventana = self.ventana()
        historial = self.historial()
        self.assertEqual(ventana.tabla.rowCount(), len(historial["ventas"]))
        self.assertIn(f"Caja Nº {historial['caja_numero']} de LUCIA · Turno ", ventana.etiqueta.text())
        anulada = [v["id"] for v in historial["ventas"]].index(self.v_repetida)
        self.assertEqual(ventana.tabla.item(anulada, COLUMNA_PAGO).text(), "ANULADA")
        self.assertTrue(ventana.tabla.item(anulada, COLUMNA_TOTAL).font().strikeOut())
        self.assertEqual(ventana.tabla.item(0, COLUMNA_TOTAL).textAlignment(), Qt.AlignRight | Qt.AlignVCenter)

    def test_cada_pastilla_deja_solo_lo_suyo_con_lo_que_suma(self):
        ventana = self.ventana()
        self.elegir(ventana, "Miembros")
        self.assertEqual(self.filas(ventana, COLUMNA_RUBRO), [repo.RUBRO_MIEMBRO] * 2)
        self.assertEqual(ventana.etiqueta_visible.text(), "2 ventas · $ 12.700")
        self.elegir(ventana, "Bonos de PC")
        self.assertEqual(self.filas(ventana, COLUMNA_RUBRO), [repo.RUBRO_BONO_PC] * 2)
        # La repetida se ve (en rojo) pero no suma.
        self.assertEqual(ventana.etiqueta_visible.text(), "1 venta · $ 8.000")
        self.elegir(ventana, "Impresiones")
        self.assertEqual(self.filas(ventana, COLUMNA_RUBRO), [repo.RUBRO_IMPRESIONES, repo.RUBRO_KIOSKO])
        self.elegir(ventana, "Anuladas")
        self.assertEqual(ventana._filtro, FILTRO_ANULADAS)
        self.assertEqual(self.filas(ventana, COLUMNA_PAGO), ["ANULADA"])
        self.elegir(ventana, "Todo")
        self.assertEqual(ventana.tabla.rowCount(), len(self.historial()["ventas"]))

    def test_el_buscador_no_mira_mayusculas_ni_acentos(self):
        ventana = self.ventana()
        ventana.buscador.setText("ulises")
        self.assertEqual(ventana.tabla.rowCount(), 2)
        ventana.buscador.setText("TRAMITE")
        self.assertEqual(self.filas(ventana, COLUMNA_RUBRO), [repo.RUBRO_TRAMITE])

    def test_imprime_lo_que_se_ve(self):
        ventana = self.ventana()
        self.elegir(ventana, "Miembros")
        html = ventana.html_para_imprimir(datetime(2026, 11, 2, 2, 30))
        self.assertIn("Historial del Turno", html)
        self.assertIn("Impreso el 02/11/2026 02:30", html)
        self.assertIn("solo Miembros", html)
        self.assertIn("Socio Ulises", html)
        self.assertNotIn("Coca 500", html)
        self.assertIn("$ 12.700", html)
        with mock.patch("ui.historial_turno_window.imprimir.vista_previa") as vista_previa:
            ventana.boton_imprimir.click()
        vista_previa.assert_called_once()
        self.assertEqual(vista_previa.call_args.args[2], "Historial del Turno")


class TestTurnoVacio(BaseHistorial):
    def test_sin_nada_cobrado_no_hay_nada_que_imprimir(self):
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)
        ventana = VentanaHistorialTurno(self.admin_id)
        self.addCleanup(ventana.deleteLater)
        self.assertEqual(ventana.tabla.rowCount(), 0)
        self.assertFalse(ventana.boton_imprimir.isEnabled())
        self.assertEqual(ventana.etiqueta_visible.text(), "Todavía no se cobró nada en este turno.")


class TestBoton(BaseHistorial):
    def boton(self, usuario_id):
        boton = BotonHistorialTurno(usuarios_repo.obtener_usuario(usuario_id))
        self.addCleanup(boton.deleteLater)
        return boton

    def test_lo_ven_todos_igual(self):
        for usuario_id in (self.admin_id, self.lucia_id):
            boton = self.boton(usuario_id)
            self.assertEqual(boton.text(), "📋  HISTORIAL DEL TURNO")
            self.assertEqual(boton.property("clase"), "barra")
            self.assertTrue(boton.isEnabled())

    def test_solo_el_admin_lo_abre(self):
        with mock.patch("ui.historial_turno_window.VentanaHistorialTurno") as ventana:
            self.boton(self.lucia_id).click()
            ventana.assert_not_called()
            self.boton(self.admin_id).click()
            ventana.assert_called_once()
            self.assertEqual(ventana.call_args.args[0], self.admin_id)

    def test_va_pegado_a_la_derecha_de_control_de_stock(self):
        panel = PanelControlPcs(usuarios_repo.obtener_usuario(self.lucia_id))
        panel.detener_actualizacion()
        self.addCleanup(panel.deleteLater)
        panel.setAttribute(Qt.WA_DontShowOnScreen)
        panel.resize(1600, 900)
        panel.show()
        self.addCleanup(panel.hide)
        _app.processEvents()

        stock = panel.boton_control_stock
        historial = panel.boton_historial_turno
        borde_de_stock = stock.mapTo(panel, QPoint(stock.width(), 0))
        inicio_de_historial = historial.mapTo(panel, QPoint(0, 0))
        self.assertTrue(0 <= inicio_de_historial.x() - borde_de_stock.x() < 20,
                        (borde_de_stock.x(), inicio_de_historial.x()))
        self.assertLessEqual(abs((inicio_de_historial.y() + historial.height() / 2)
                                 - (borde_de_stock.y() + stock.height() / 2)), 3)
