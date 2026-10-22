"""
tests/test_detalle_dia.py
==========================
El detalle de lo vendido en un día (Reportes > Resumen del Día, pedido del
dueño 2026-10-18; repositories/detalle_dia_repo.py y ui/reportes_detalle_dia.py):
cada venta con su hora, turno, operador y qué se vendió (kiosko, trámite, bono
de PC con la PC donde estaba al venderlo, PCSTREAM, PlayStation 5, socios), lo
vendido por producto y por operador, que el detalle de cada turno sume lo
mismo que su fila del Resumen del Día, y el listado renglón por renglón que se
imprime (ui/imprimir.py).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    bonos_miembro_repo, miembros_repo, pcs_repo, pcstream_repo, playstation_repo,
)
from repositories import (  # noqa: E402
    articulos_repo, detalle_dia_repo, relevo_repo, reportes_repo, tramites_repo, turnos_repo, usuarios_repo,
    ventas_repo,
)
from ui import imprimir  # noqa: E402
from ui.reportes_detalle_dia import _COLUMNAS_RENGLONES, _renglones  # noqa: E402
from ui.reportes_resumen_dia import PestañaResumenDelDia  # noqa: E402
from ui.utils import formato_pesos  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _digital(monto):
    return [{"metodo": dominio.PAGO_DIGITAL, "monto": monto}]


class _UnDiaConDeTodo(BaseConBaseTemporal):
    """Lucía abre su caja y vende de todo; el Administrador cobra algo con la caja
    de ella abierta; se anula una venta antes del cierre; se cierra el turno; se
    anula otra DESPUÉS del cierre; y Gaby vende algo en el turno siguiente."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.listar_usuarios()[0]["id"]
        self.lucia_id = usuarios_repo.crear_usuario(
            "LUCIA", "4321", dominio.ROL_EMPLEADA,
        )
        self.gaby_id = usuarios_repo.crear_usuario("GABY", "4321", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 0)
        articulos_repo.crear_articulo("AGUA", "Agua 500", None, None, 800.0, 400.0, 0)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.pcstream = pcs_repo.crear_estacion(dominio.NOMBRE_PCSTREAM)
        bono_pc = pcs_repo.crear_bono("3 horas", 180, 3000.0)
        bono_stream = pcstream_repo.crear_bono("1 hora", 60, 2000.0)
        bono_ps5 = playstation_repo.crear_bono(self.admin_id, "Media hora", 30, 1500.0)
        bono_socio = bonos_miembro_repo.crear_bono("Pack 5 h", 300, 4000.0)
        tramite = tramites_repo.crear_tramite("Boleta de luz")
        socio = miembros_repo.crear_miembro("juan", "1111", nombre="Juan")

        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=50000.0)
        self.v_kiosko = self._vender(self.lucia_id, 2)
        self.v_tramite = tramites_repo.registrar_tramite(self.lucia_id, tramite, 500.0, _digital(500.0))
        self.v_pc = pcs_repo.asignar_bono(self.pc1, bono_pc, self.lucia_id, _efectivo(3000.0))
        pcs_repo.trasladar_sesion(self.pc1, self.pc2, self.lucia_id)  # después de venderlo
        with conexion_db() as conexion:
            # Un minuto después de la venta, como en la vida real (son dos clics de
            # una persona). El reloj de Windows avanza de a saltos de ~0,5 ms: hechos
            # uno atrás del otro, la venta y el traslado quedaban la mitad de las veces
            # con la MISMA hora, el traslado no era "posterior" a la venta y el bono
            # salía en la PC2 (medido el 2026-10-19: 8 de 15 corridas).
            vendido = conexion.execute("SELECT fecha FROM ventas WHERE id = ?", (self.v_pc,)).fetchone()["fecha"]
            conexion.execute(
                "UPDATE traslados_sesion SET fecha = ?",
                ((datetime.fromisoformat(vendido) + timedelta(minutes=1)).isoformat(timespec="microseconds"),),
            )
        self.v_stream = pcs_repo.asignar_bono(self.pcstream, bono_stream, self.lucia_id, _digital(2000.0))
        self.v_ps5 = playstation_repo.vender_bono(self.lucia_id, bono_ps5, _efectivo(1500.0))
        self.v_carga = miembros_repo.cargar_saldo_por_monto(socio, 3000.0, _efectivo(3000.0), self.lucia_id)
        self.v_pack = miembros_repo.cargar_saldo_por_bono(socio, bono_socio, _digital(4000.0), self.lucia_id)
        self.v_admin = self._vender(self.admin_id, 1)  # queda a nombre de Lucía
        self.v_anulada_antes = self._vender(self.lucia_id, 3)
        ventas_repo.anular_venta(self.v_anulada_antes, self.admin_id, "mal cobrada")

        turnos_repo.cerrar_turno(self.lucia_id)
        self.dia = turnos_repo.listar_cierres()[0]["fecha"]
        ventas_repo.anular_venta(self.v_admin, self.admin_id, "devolución")
        with conexion_db() as conexion:
            # Un minuto después del cierre (en la vida real nadie anula en el
            # mismo segundo en que se cierra).
            cierre = conexion.execute("SELECT fecha_cierre FROM cierres_turno").fetchone()["fecha_cierre"]
            despues = (datetime.fromisoformat(cierre) + timedelta(minutes=1)).isoformat(timespec="seconds")
            conexion.execute("UPDATE ventas SET anulada_fecha = ? WHERE id = ?", (despues, self.v_admin))
        self.v_gaby = ventas_repo.confirmar_venta(
            self.gaby_id, [{"codigo": "AGUA", "descripcion": "Agua 500", "cantidad": 1, "precio_unitario": 800.0}],
            _efectivo(800.0),
        )

    def _vender(self, usuario_id, cantidad):
        return ventas_repo.confirmar_venta(
            usuario_id,
            [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": cantidad, "precio_unitario": 1000.0}],
            _efectivo(1000.0 * cantidad),
        )

    def _turno_cerrado(self, detalle):
        turno = turnos_repo.listar_cierres()[0]["turno"]
        return next(t for t in detalle["turnos"] if t["turno"] == turno)

    def _venta(self, detalle, venta_id):
        return next(v for v in detalle["ventas"] if v["id"] == venta_id)


class TestCadaVentaDiceQueSeVendio(_UnDiaConDeTodo):
    def test_cada_cosa_con_su_rubro_y_su_detalle(self):
        detalle = detalle_dia_repo.detalle_del_dia(self.dia)
        esperado = {
            self.v_kiosko: (reportes_repo.CATEGORIA_KIOSKO, "2 x Coca 500"),
            self.v_tramite: (reportes_repo.CATEGORIA_TRAMITE, "Trámite: Boleta de luz"),
            # La PC donde estaba al venderlo, aunque después se la cambió a la PC2.
            self.v_pc: (reportes_repo.CATEGORIA_BONO_PC, "PC1 · 3 horas (3 h)"),
            self.v_stream: (reportes_repo.CATEGORIA_BONO_PCSTREAM, f"{dominio.NOMBRE_PCSTREAM} · 1 hora (1 h)"),
            self.v_ps5: (reportes_repo.CATEGORIA_BONO_PLAYSTATION, f"{dominio.NOMBRE_PLAYSTATION} · Media hora (30 min)"),
            self.v_pack: (reportes_repo.CATEGORIA_BONO_SOCIO, "Socio Juan · Pack 5 h (5 h)"),
        }
        for venta_id, (rubro, texto) in esperado.items():
            venta = self._venta(detalle, venta_id)
            self.assertEqual((venta["rubro"], venta["detalle"]), (rubro, texto))
        carga = self._venta(detalle, self.v_carga)
        self.assertEqual(carga["rubro"], reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO)
        self.assertTrue(carga["detalle"].startswith("Socio Juan · carga de saldo ("))

    def test_operador_turno_hora_y_medio_de_pago(self):
        detalle = detalle_dia_repo.detalle_del_dia(self.dia)
        tramite = self._venta(detalle, self.v_tramite)
        self.assertEqual((tramite["operador"], tramite["cargada_por"]), ("LUCIA", None))
        self.assertEqual((tramite["efectivo"], tramite["digital"], tramite["total"]), (0.0, 500.0, 500.0))
        self.assertEqual(tramite["turno"], turnos_repo.listar_cierres()[0]["turno"])
        # Lo cobrado por el Administrador con la caja de Lucía queda a nombre de ella.
        admin = self._venta(detalle, self.v_admin)
        self.assertEqual((admin["operador"], admin["cargada_por"]), ("LUCIA", "Administrador"))
        fechas = [venta["fecha"] for venta in self._turno_cerrado(detalle)["ventas"]]
        self.assertEqual(fechas, sorted(fechas))

    def test_las_anuladas_aparecen_marcadas(self):
        detalle = detalle_dia_repo.detalle_del_dia(self.dia)
        antes = self._venta(detalle, self.v_anulada_antes)
        despues = self._venta(detalle, self.v_admin)
        self.assertEqual((antes["anulada"], antes["anulada_despues_del_cierre"]), (True, False))
        self.assertEqual((despues["anulada"], despues["anulada_despues_del_cierre"]), (True, True))


class TestElDetalleSumaLoMismoQueLosTurnos(_UnDiaConDeTodo):
    def test_cada_turno_del_resumen_coincide_con_su_detalle(self):
        # El día del turno cerrado y el de la ventana abierta (la venta de Gaby):
        # según la hora a la que corra la prueba, pueden ser el mismo o no.
        with conexion_db() as conexion:
            dia_abierto = turnos_repo._ventana_en_curso(conexion)["dia"].isoformat()
        for dia in {self.dia, dia_abierto}:
            resumen = turnos_repo.resumen_del_dia(dia)
            detalle = detalle_dia_repo.detalle_del_dia(dia)
            for fila in resumen["turnos"]:
                parte = next((t for t in detalle["turnos"] if t["turno"] == fila["turno"]), None)
                if parte is None:
                    self.assertEqual(fila["total"], 0, fila["turno"])
                    continue
                # El cierre guardó una foto con la venta anulada después adentro.
                foto = sum(v["total"] for v in parte["ventas"] if v["anulada_despues_del_cierre"])
                self.assertAlmostEqual(parte["totales"]["total"] + foto, fila["total"], places=2)
                efectivo_foto = sum(v["efectivo"] for v in parte["ventas"] if v["anulada_despues_del_cierre"])
                self.assertAlmostEqual(parte["totales"]["efectivo"] + efectivo_foto, fila["efectivo"], places=2)
                self.assertEqual(parte["totales"]["ventas"], fila["cantidad_ventas"])
                self.assertEqual(parte["totales"]["anuladas"], fila["cantidad_anuladas"])

    def test_la_venta_de_despues_del_cierre_va_a_la_ventana_abierta(self):
        # Si el turno de la ventana abierta es el mismo que el del cierre (cerrar
        # antes de hora), las dos partes van juntas, como en la fila del resumen.
        with conexion_db() as conexion:
            abierta = turnos_repo._ventana_en_curso(conexion)
        detalle = detalle_dia_repo.detalle_del_dia(abierta["dia"])
        turno = next(t for t in detalle["turnos"] if t["turno"] == abierta["turno"])
        venta = next(v for v in turno["ventas"] if v["id"] == self.v_gaby)
        self.assertEqual((venta["operador"], venta["detalle"]), ("GABY", "1 x Agua 500"))

    def test_lo_vendido_por_producto_y_por_operador(self):
        cerrado = self._turno_cerrado(detalle_dia_repo.detalle_del_dia(self.dia))
        productos = {(p["rubro"], p["producto"]): (p["cantidad"], p["importe"]) for p in cerrado["por_producto"]}
        # 2 Cocas de Lucía; las 3 anuladas y la del Administrador (anulada después) no cuentan.
        self.assertEqual(productos[(reportes_repo.CATEGORIA_KIOSKO, "Coca 500")], (2, 2000.0))
        self.assertEqual(productos[(reportes_repo.CATEGORIA_BONO_PC, "3 horas")], (1, 3000.0))
        self.assertEqual(productos[(reportes_repo.CATEGORIA_BONO_PLAYSTATION, "Media hora")], (1, 1500.0))
        self.assertEqual(sum(importe for _, importe in productos.values()), cerrado["totales"]["total"])

        operadores = {o["operador"]: o for o in cerrado["por_operador"]}
        self.assertNotIn("Administrador", operadores)  # lo que cobró quedó a nombre de Lucía
        self.assertEqual(operadores["LUCIA"]["anuladas"], 2)
        de_lucia = [v for v in cerrado["ventas"] if v["operador"] == "LUCIA" and not v["anulada"]]
        self.assertEqual(operadores["LUCIA"]["ventas"], len(de_lucia))
        self.assertEqual(operadores["LUCIA"]["total"], sum(v["total"] for v in de_lucia))

    def test_un_dia_sin_nada(self):
        detalle = detalle_dia_repo.detalle_del_dia("2020-01-01")
        self.assertEqual((detalle["turnos"], detalle["ventas"]), ([], []))
        self.assertEqual(detalle["totales"]["total"], 0)


class TestPantallaDelDetalle(_UnDiaConDeTodo):
    def test_tocar_un_turno_muestra_solo_ese_y_total_muestra_todo(self):
        pestaña = PestañaResumenDelDia()
        self.addCleanup(pestaña.deleteLater)
        pestaña.fecha.setDate(QDate.fromString(self.dia, "yyyy-MM-dd"))
        panel = pestaña.panel_detalle
        detalle = detalle_dia_repo.detalle_del_dia(self.dia)

        self.assertTrue(panel.titulo.text().startswith("Todo el día"))
        self.assertIn("cuenta además $ 1.000,00 anulados después de cerrar", panel.titulo.text())
        self.assertEqual(panel.tabla_ventas.rowCount(), len(detalle["ventas"]))

        turno = turnos_repo.listar_cierres()[0]["turno"]
        fila_del_turno = pestaña._turno_de_cada_fila.index(turno)
        pestaña.tabla.selectRow(fila_del_turno)
        cerrado = self._turno_cerrado(detalle)
        self.assertTrue(panel.titulo.text().startswith(cerrado["etiqueta"]))
        self.assertEqual(panel.tabla_ventas.rowCount(), len(cerrado["ventas"]))
        textos = [panel.tabla_ventas.item(fila, 5).text() for fila in range(panel.tabla_ventas.rowCount())]
        self.assertIn("PC1 · 3 horas (3 h)", textos)
        estados = [panel.tabla_ventas.item(fila, 9).text() for fila in range(panel.tabla_ventas.rowCount())]
        self.assertIn("ANULADA después del cierre", estados)
        self.assertEqual(panel.tabla_operadores.item(0, 0).text(), "LUCIA")

        pestaña.tabla.selectRow(pestaña.tabla.rowCount() - 1)  # TOTAL DEL DÍA
        self.assertTrue(panel.titulo.text().startswith("Todo el día"))


class TestRenglonPorRenglon(BaseConBaseTemporal):
    """El listado renglón por renglón que se imprime (pedido del dueño,
    2026-10-18): "si se cobran 14 impresiones juntas, que diga 14; si se hacen 4
    por separado, que las ponga tal cual se cobraron, con su horario y su
    operador"."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.listar_usuarios()[0]["id"]
        self.lucia_id = usuarios_repo.crear_usuario("LUCIA", "4321", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("4", "IMPRESION", None, None, 150.0, 0.0, 0)
        articulos_repo.crear_articulo("7790895000232", "COCA LATA", None, None, 2700.0, 1500.0, 0)
        pc1 = pcs_repo.crear_estacion("PC1")
        bono = pcs_repo.crear_bono("1 hora", 60, 1000.0)

        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=5000.0)
        self.juntas = self._vender(self.lucia_id, ("4", "IMPRESION", 14, 150.0))
        self.separadas = [self._vender(self.lucia_id, ("4", "IMPRESION", 1, 150.0)) for _ in range(3)]
        self.separadas.append(self._vender(self.admin_id, ("4", "IMPRESION", 1, 150.0)))  # a nombre de Lucía
        self.mezcla = self._vender(
            self.lucia_id, ("7790895000232", "COCA LATA", 2, 2700.0), ("4", "IMPRESION", 3, 150.0),
        )
        self.bono = pcs_repo.asignar_bono(pc1, bono, self.lucia_id, _efectivo(1000.0))
        self.anulada = self._vender(self.lucia_id, ("4", "IMPRESION", 5, 150.0))
        ventas_repo.anular_venta(self.anulada, self.admin_id, "mal cobrada")
        with conexion_db() as conexion:
            self.dia = turnos_repo._ventana_en_curso(conexion)["dia"].isoformat()

    def _vender(self, usuario_id, *renglones):
        lineas = [{"codigo": codigo, "descripcion": descripcion, "cantidad": cantidad, "precio_unitario": precio}
                  for codigo, descripcion, cantidad, precio in renglones]
        return ventas_repo.confirmar_venta(
            usuario_id, lineas, _efectivo(sum(l["cantidad"] * l["precio_unitario"] for l in lineas)),
        )

    def _lineas(self, venta_id):
        detalle = detalle_dia_repo.detalle_del_dia(self.dia)
        return next(v for v in detalle["ventas"] if v["id"] == venta_id)["lineas"]

    def test_catorce_juntas_son_un_renglon_de_catorce(self):
        self.assertEqual(self._lineas(self.juntas), [
            {"codigo": "4", "descripcion": "IMPRESION", "cantidad": 14, "importe": 2100.0},
        ])

    def test_cuatro_por_separado_son_cuatro_renglones_con_su_hora_y_su_operador(self):
        detalle = detalle_dia_repo.detalle_del_dia(self.dia)
        filas = [valores for valores, _ in _renglones(detalle["ventas"], detalle["fecha"])
                 if int(valores[3]) in self.separadas]
        self.assertEqual([int(valores[3]) for valores in filas], self.separadas)
        self.assertEqual({valores[6] for valores in filas}, {"1"})
        for valores in filas:
            venta = next(v for v in detalle["ventas"] if v["id"] == int(valores[3]))
            # "01:20 del 19/10" si la prueba corre de madrugada (la Noche sigue siendo de ese día).
            self.assertTrue(valores[0].startswith(datetime.fromisoformat(venta["fecha"]).strftime("%H:%M")))
            self.assertEqual(valores[1], venta["etiqueta_turno"])
        self.assertEqual([valores[2] for valores in filas], ["LUCIA"] * 3 + ["LUCIA (cargó Administrador)"])

    def test_una_venta_con_dos_cosas_son_dos_renglones_con_el_mismo_numero(self):
        self.assertEqual(self._lineas(self.mezcla), [
            {"codigo": "7790895000232", "descripcion": "COCA LATA", "cantidad": 2, "importe": 5400.0},
            {"codigo": "4", "descripcion": "IMPRESION", "cantidad": 3, "importe": 450.0},
        ])

    def test_un_bono_es_un_renglon_sin_codigo_con_la_pc(self):
        self.assertEqual(self._lineas(self.bono), [
            {"codigo": "", "descripcion": "PC1 · 1 hora (1 h)", "cantidad": 1, "importe": 1000.0},
        ])

    def test_los_totales_no_cuentan_las_anuladas(self):
        totales = detalle_dia_repo.detalle_del_dia(self.dia)["totales"]
        self.assertEqual(totales["unidades"], 14 + 4 + 2 + 3 + 1)
        self.assertEqual(totales["total"], 2100.0 + 600.0 + 5400.0 + 450.0 + 1000.0)

    def _panel(self):
        pestaña = PestañaResumenDelDia()
        self.addCleanup(pestaña.deleteLater)
        pestaña.fecha.setDate(QDate.fromString(self.dia, "yyyy-MM-dd"))
        return pestaña.panel_detalle

    def test_la_pantalla_muestra_cada_renglon_y_el_total(self):
        panel = self._panel()
        tabla = panel.tabla_renglones
        # 1 + 4 + 2 + 1 + la anulada (en rojo), y la fila del TOTAL.
        self.assertEqual(tabla.rowCount(), 10)
        self.assertEqual(panel.pestañas.tabText(0), "Renglón por renglón")
        ultima = [tabla.item(9, columna).text() for columna in range(tabla.columnCount())]
        self.assertEqual(ultima, ["TOTAL", "", "", "", "", "", "24", formato_pesos(9550.0), ""])
        anulada = next(fila for fila in range(9) if int(tabla.item(fila, 3).text()) == self.anulada)
        self.assertEqual(tabla.item(anulada, 8).text(), "ANULADA")
        self.assertTrue(panel.boton_imprimir.isEnabled())

    def test_lo_que_se_imprime(self):
        panel = self._panel()
        html = panel._html_para_imprimir(impreso=datetime(2026, 10, 18, 21, 40))
        self.assertIn("Impreso el 18/10/2026 21:40", html)
        self.assertIn(f"Ventas del {datetime.fromisoformat(self.dia).strftime('%d/%m/%Y')} · Todo el día", html)
        self.assertEqual(html.count(">IMPRESION<"), 1 + 4 + 1 + 1)
        self.assertEqual(html.count(imprimir._COLOR_ANULADA), len(_COLUMNAS_RENGLONES))  # la anulada, en rojo
        self.assertIn(f">{formato_pesos(9550.0)}<", html)

        with mock.patch("ui.reportes_detalle_dia.imprimir.vista_previa") as vista_previa:
            panel.boton_imprimir.click()
        vista_previa.assert_called_once()
        self.assertIn(">IMPRESION<", vista_previa.call_args.args[1])

    def test_un_dia_sin_ventas_no_se_imprime(self):
        panel = self._panel()
        panel.mostrar(detalle_dia_repo.detalle_del_dia("2020-01-01"))
        self.assertFalse(panel.boton_imprimir.isEnabled())
        self.assertEqual(panel.tabla_renglones.rowCount(), 0)


class TestHtmlParaImprimir(unittest.TestCase):
    def test_el_texto_se_escapa_y_los_importes_van_a_la_derecha(self):
        html = imprimir.html_del_listado(
            "Título", "resumen", ["Descripción", "Total"], [(["Papas <grandes> & co", "$ 10,00"], False)],
            a_la_derecha=(1,), pie=["TOTAL", "$ 10,00"],
        )
        self.assertIn("Papas &lt;grandes&gt; &amp; co", html)
        self.assertNotIn("<grandes>", html)
        self.assertIn('<td align="right">$ 10,00</td>', html)
        self.assertIn("<thead>", html)  # Qt repite los títulos arriba de cada hoja


if __name__ == "__main__":
    unittest.main()
