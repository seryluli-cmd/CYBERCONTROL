"""
tests/test_excel.py
===================
Bajar a Excel (pedido del dueño, 2026-10-24): el Historial de Cargas y Reportes
> PCs: Socios y Bonos se bajan a un .xlsx de verdad (ui/excel.py, escrito sin
librerías aparte), con fechas, tiempos, pesos y porcentajes como números que
Excel suma. Acá se revisa el archivo por dentro; abrirlo con Excel 16 se probó
a mano el mismo día.
"""

import os
import shutil
import tempfile
import unittest
import zipfile
from datetime import datetime
from unittest import mock
from xml.etree import ElementTree

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from ui import excel  # noqa: E402
from test_historial_cargas import BaseHistorial  # noqa: E402
from test_socios_bonos import BaseVentasDePcs  # noqa: E402
from control_pcs.ui.miembros_historial_cargas import VentanaHistorialCargas  # noqa: E402
from ui.reportes_socios_bonos import PestañaSociosYBonos  # noqa: E402

_app = QApplication.instance() or QApplication([])
_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


def _celdas(ruta) -> dict:
    """{"A1": (valor, estilo, es_texto)} de la hoja del .xlsx."""
    with zipfile.ZipFile(ruta) as archivo:
        hoja = ElementTree.fromstring(archivo.read("xl/worksheets/sheet1.xml"))
    celdas = {}
    for celda in hoja.iterfind(".//x:c", _NS):
        es_texto = celda.get("t") == "inlineStr"
        valor = celda.find("x:is/x:t", _NS).text if es_texto else float(celda.find("x:v", _NS).text)
        celdas[celda.get("r")] = (valor, celda.get("s"), es_texto)
    return celdas


class BaseConCarpeta(unittest.TestCase):
    def setUp(self):
        super().setUp()
        self.carpeta = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.carpeta, True)
        self.ruta = os.path.join(self.carpeta, "prueba.xlsx")


class TestElArchivo(BaseConCarpeta):
    def guardar(self, **extra):
        columnas = [("Fecha", excel.FECHA_HORA), ("Socio", excel.TEXTO), ("Tiempo", excel.HORAS),
                    ("Plata", excel.PESOS), ("Cargas", excel.ENTERO), ("%", excel.PORCENTAJE)]
        filas = [[datetime(2026, 10, 24, 18, 0), 'Pérez & <Cía> "el pibe"', 90, 1500.5, 2, 47.5],
                 [datetime(2026, 10, 25, 6, 0), "mica", 60, 1000.0, 1, None]]
        excel.guardar_xlsx(self.ruta, extra.get("hoja", "Historial de Cargas"), columnas, filas,
                           totales=["TOTAL", None, 150, 2500.5, 3, 100.0])

    def test_todas_las_partes_son_xml_validos(self):
        self.guardar()
        with zipfile.ZipFile(self.ruta) as archivo:
            self.assertEqual(sorted(archivo.namelist()), sorted([
                "[Content_Types].xml", "_rels/.rels", "xl/workbook.xml", "xl/_rels/workbook.xml.rels",
                "xl/styles.xml", "xl/worksheets/sheet1.xml",
            ]))
            for parte in archivo.namelist():
                ElementTree.fromstring(archivo.read(parte))

    def test_numeros_de_verdad_y_textos_escapados(self):
        self.guardar()
        celdas = _celdas(self.ruta)
        self.assertEqual(celdas["A1"][0], "Fecha")
        self.assertEqual(celdas["B2"], ('Pérez & <Cía> "el pibe"', "1", True))
        # Fecha: días desde el 30/12/1899; tiempo: fracción de día; porcentaje: de 0 a 1.
        self.assertAlmostEqual(celdas["A2"][0], 46319.75)
        self.assertAlmostEqual(celdas["C2"][0], 90 / 1440)
        self.assertEqual(celdas["D2"][:2], (1500.5, "5"))
        self.assertAlmostEqual(celdas["F2"][0], 0.475)
        self.assertNotIn("F3", celdas)  # None queda vacía

    def test_totales_en_negrita_despues_de_un_renglon_vacio(self):
        self.guardar()
        celdas = _celdas(self.ruta)
        self.assertFalse(any(referencia.endswith("4") for referencia in celdas))
        self.assertEqual(celdas["A5"], ("TOTAL", "2", True))
        self.assertEqual(celdas["D5"][:2], (2500.5, "6"))

    def test_nombre_de_hoja_que_excel_acepta(self):
        self.guardar(hoja="Ventas 24/10: [todas] las de la semana entera")
        with zipfile.ZipFile(self.ruta) as archivo:
            libro = ElementTree.fromstring(archivo.read("xl/workbook.xml"))
        nombre = libro.find("x:sheets/x:sheet", _NS).get("name")
        self.assertLessEqual(len(nombre), 31)
        self.assertFalse(set(nombre) & set('[]:*?/\\'))

    def test_letras_de_columna(self):
        self.assertEqual([excel._columna(n) for n in (0, 25, 26, 27, 51, 52)], ["A", "Z", "AA", "AB", "AZ", "BA"])

    def test_nombre_de_archivo(self):
        self.assertEqual(excel.nombre_de_archivo("Historial de Cargas", "2026-10-01", "2026-10-24"),
                         "Historial de Cargas del 01-10-2026 al 24-10-2026.xlsx")
        self.assertEqual(excel.nombre_de_archivo("PCs: Socios", "2026-10-24", "2026-10-24"),
                         "PCs- Socios del 24-10-2026.xlsx")


class TestBajarAExcel(BaseConCarpeta):
    columnas = [("Algo", excel.TEXTO)]

    def bajar(self, ruta_elegida, abrir=False):
        with mock.patch("ui.excel.QFileDialog.getSaveFileName", return_value=(ruta_elegida, "")), \
                mock.patch("ui.excel.confirmar", return_value=abrir) as pregunta, \
                mock.patch("ui.excel.QDesktopServices.openUrl") as abrir_archivo, \
                mock.patch("ui.excel.mostrar_error") as error:
            ruta = excel.bajar_a_excel(None, "x.xlsx", "Hoja", self.columnas, [["uno"]])
        return ruta, pregunta, abrir_archivo, error

    def test_guarda_y_ofrece_abrirlo(self):
        ruta, pregunta, abrir_archivo, _ = self.bajar(os.path.join(self.carpeta, "lista"), abrir=True)
        self.assertTrue(ruta.endswith("lista.xlsx"))
        self.assertTrue(os.path.exists(ruta))
        pregunta.assert_called_once()
        abrir_archivo.assert_called_once()

    def test_cancelar_no_graba_nada(self):
        ruta, pregunta, _, _ = self.bajar("")
        self.assertEqual(ruta, "")
        pregunta.assert_not_called()

    def test_si_no_se_puede_grabar_avisa(self):
        ruta, pregunta, _, error = self.bajar(os.path.join(self.carpeta, "no_existe", "lista.xlsx"))
        self.assertEqual(ruta, "")
        error.assert_called_once()
        self.assertIn("abierto en Excel", error.call_args.args[2])
        pregunta.assert_not_called()


class TestHistorialDeCargas(BaseHistorial):
    def test_los_datos_que_van_a_excel(self):
        self.cargar_bono()
        ventana = VentanaHistorialCargas(None)
        self.addCleanup(ventana.deleteLater)
        self.assertTrue(ventana.boton_excel.isEnabled())
        columnas, filas, totales = ventana.datos_para_excel()
        self.assertEqual([titulo for titulo, _ in columnas][:4], ["Fecha y hora", "Socio", "Tiempo", "Plata"])
        [fila] = filas
        self.assertIsInstance(fila[0], datetime)
        self.assertEqual(fila[1:6], ["ana (Ana Pérez)", 180, 3000, "Efectivo", "3 horas"])
        self.assertEqual(totales[:4], ["TOTAL", "1 carga", 180, 3000])

    def test_sin_cargas_no_se_baja(self):
        ventana = VentanaHistorialCargas(None)
        self.addCleanup(ventana.deleteLater)
        self.assertFalse(ventana.boton_excel.isEnabled())


class TestSociosYBonos(BaseVentasDePcs):
    def test_los_datos_que_van_a_excel(self):
        pestaña = PestañaSociosYBonos()
        self.addCleanup(pestaña.deleteLater)
        columnas, filas, totales = pestaña.datos_para_excel()
        self.assertEqual(len(columnas), 10)
        self.assertEqual(len(filas), 1)
        self.assertEqual(totales, ["TOTAL", 5000, 2, 300, 5500, 2, 180, 10500, 47.6, 52.4])
