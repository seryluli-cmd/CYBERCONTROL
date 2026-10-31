"""
tests/test_listas_maqueta_b.py
================================
Las listas con la maqueta B que eligió el dueño para el kiosko (2026-10-30) y pidió
también acá (2026-10-31): los números de arriba de Artículos
(`dominio.numeros_de_los_articulos`), el filtro por rubro con el buscador, y lo que
cambia respecto del kiosko: el Origen de cada venta en Consulta de Ventas y los
turnos del domingo en Control de Cierres.
Las pantallas se prueban sin abrir ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
import unittest
from datetime import date

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
import turnos  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from ui import consulta_ventas_window, control_cierres_window  # noqa: E402
from ui.articulos_window import ArticulosWindow  # noqa: E402
from ui.consulta_ventas_window import ConsultaVentasWindow  # noqa: E402
from ui.control_cierres_window import ControlCierresWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestNumerosDeLosArticulos(unittest.TestCase):
    def _articulo(self, codigo, stock, minimo, compra):
        return {"codigo": codigo, "stock": stock, "stock_minimo": minimo, "precio_compra": compra}

    def test_cuenta_los_bajo_el_minimo_y_el_valor_a_precio_de_compra(self):
        numeros = dominio.numeros_de_los_articulos([
            self._articulo("A", 10, 2, 150.5),   # 1505
            self._articulo("B", 1, 2, 100.0),    # bajo el mínimo: 100
            self._articulo("C", 2, 2, 300.0),    # justo en el mínimo: no avisa; 600
        ])
        self.assertEqual(numeros, {"cantidad": 3, "bajo_el_minimo": 1, "valor_del_stock": 2205.0})

    def test_el_stock_negativo_vale_cero_pero_cuenta_como_bajo_el_minimo(self):
        numeros = dominio.numeros_de_los_articulos([self._articulo("A", -5, 0, 100.0)])
        self.assertEqual(numeros, {"cantidad": 1, "bajo_el_minimo": 1, "valor_del_stock": 0})

    def test_impresiones_no_entra(self):
        numeros = dominio.numeros_de_los_articulos(
            [self._articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, -130, 0, 40.0)])
        self.assertEqual(numeros, {"cantidad": 0, "bajo_el_minimo": 0, "valor_del_stock": 0})


class TestArticulosConLaMaquetaB(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        bebidas = articulos_repo.crear_rubro("BEBIDAS PRUEBA")
        golosinas = articulos_repo.crear_rubro("GOLOSINAS PRUEBA")
        articulos_repo.crear_articulo("AGUA", "Agua", None, bebidas, 1000.0, 500.0, 2)
        articulos_repo.crear_articulo("ALFAJOR", "Alfajor", None, golosinas, 900.0, 480.0, 0)
        with conexion_db() as conexion:
            conexion.execute("UPDATE articulos SET stock = 1 WHERE codigo = 'AGUA'")
        self.ventana = ArticulosWindow(None, None)
        self.addCleanup(self.ventana.deleteLater)

    def _codigos(self):
        return sorted(self.ventana.tabla.item(fila, 0).text() for fila in range(self.ventana.tabla.rowCount()))

    def test_arriba_dice_cuantos_hay_y_cuantos_quedaron_bajo_el_minimo(self):
        articulos = articulos_repo.listar_articulos("")
        numeros = dominio.numeros_de_los_articulos(articulos)
        self.assertEqual(self.ventana.indicador_articulos.valor.text(), str(numeros["cantidad"]))
        self.assertEqual(self.ventana.indicador_bajo_minimo.valor.text(), str(numeros["bajo_el_minimo"]))
        self.assertTrue(self.ventana.indicador_bajo_minimo.property("alerta"))
        self.assertEqual(self.ventana.indicador_rubros.valor.text(), str(len(articulos_repo.listar_rubros())))

    def test_el_filtro_por_rubro_y_el_buscador_se_suman(self):
        pastilla = next(p for p in self.ventana.filtros.pastillas if p.text() == "BEBIDAS PRUEBA")
        pastilla.click()
        self.assertEqual(self._codigos(), ["AGUA"])
        self.ventana.campo_buscar.setText("ALFAJOR")
        self.assertEqual(self._codigos(), [])
        self.ventana.filtros.pastillas[0].click()   # Todos
        self.assertEqual(self._codigos(), ["ALFAJOR"])


class TestConsultaDeVentasConElOrigen(BaseConBaseTemporal):
    def test_cada_dato_en_su_columna(self):
        admin = next(u for u in usuarios_repo.listar_usuarios() if dominio.es_admin(u))
        ventana = ConsultaVentasWindow(admin)
        self.addCleanup(ventana.deleteLater)
        titulos = [ventana.tabla.horizontalHeaderItem(c).text() for c in range(ventana.tabla.columnCount())]
        modulo = consulta_ventas_window
        for columna, titulo in ((modulo._COLUMNA_TURNO, "Turno"), (modulo._COLUMNA_ORIGEN, "Origen"),
                                (modulo._COLUMNA_VENDEDOR, "Vendedor"), (modulo._COLUMNA_TOTAL, "Total"),
                                (modulo._COLUMNA_ESTADO, "Estado")):
            self.assertEqual(titulos[columna], titulo)
        # El Origen y el Estado, en etiquetas de color.
        self.assertIs(ventana.tabla.itemDelegateForColumn(modulo._COLUMNA_ORIGEN), ventana.etiqueta_origen)
        self.assertIs(ventana.tabla.itemDelegateForColumn(modulo._COLUMNA_ESTADO), ventana.etiqueta_estado)


class TestControlDeCierresConLosTurnosDelDomingo(BaseConBaseTemporal):
    def test_cada_turno_tiene_su_color_tambien_los_del_domingo(self):
        # Los domingos son "Domingo T1"/"T2" (turnos.etiqueta_turno): con la etiqueta
        # del kiosko, que no los tiene, la ventana ni abría.
        admin = next(u for u in usuarios_repo.listar_usuarios() if dominio.es_admin(u))
        ventana = ControlCierresWindow(admin)
        self.addCleanup(ventana.deleteLater)
        colores = ventana.etiqueta_turno._colores
        domingo = date(2026, 11, 1)
        for turno in dominio.TURNOS_DOMINGO:
            self.assertIn(turnos.etiqueta_turno(domingo, turno), colores)
        for turno in dominio.TURNOS:
            self.assertIn(turnos.etiqueta_turno(date(2026, 11, 2), turno), colores)
        self.assertEqual(len(set(colores.values())), len(colores))   # ninguno repetido
        self.assertEqual(ventana.tabla.columnCount(), max(control_cierres_window._COLUMNAS_DE_PLATA) + 1)


if __name__ == "__main__":
    unittest.main()
