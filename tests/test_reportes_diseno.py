"""
tests/test_reportes_diseno.py
=============================
El diseño de Reportes que eligió el dueño el 2026-11-19 (la opción C con un color
por rubro): el menú de la izquierda que elige la sección, los títulos en
mayúscula, la plata en negrita con los ceros en gris, el Ranking con las
impresiones aparte y cada rubro en una etiqueta de su color, los títulos de
TOTALES con una barra del color de su rubro, y que ese color sea EL MISMO en
todo el programa (Historial del Turno, Consulta de Ventas, Control de Cierres,
Socios y Bonos, el Detalle del Día). Se prueba sin abrir ninguna ventana
(plataforma "offscreen"); lo que depende de cómo se miden los títulos, con la hoja
de estilos de verdad.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QHeaderView, QLabel, QPushButton, QTableWidget  # noqa: E402

import dominio  # noqa: E402
from repositories import (  # noqa: E402
    articulos_repo, detalle_dia_repo, historial_turno_repo, reportes_repo, usuarios_repo, ventas_repo,
)
from turnos import dia_en_que_empezo_el_turno  # noqa: E402
from ui import reportes_piezas, reportes_socios_bonos, reportes_window  # noqa: E402
from ui.detalle_venta import etiqueta_de_estado  # noqa: E402
from ui.dibujos_tabla import (  # noqa: E402
    TONO_ALERTA, TONO_IMPRESIONES, TONO_KIOSKO, TONO_PCS, TONO_PLAYSTATION, TONO_SOCIOS, TONO_TRAMITES,
    TONOS_DE_ETIQUETA, CabeceraConColores, color_fuerte,
)
from ui.historial_turno_window import TONOS as TONOS_DEL_HISTORIAL  # noqa: E402
from ui.hoja_de_estilos import HOJA_DE_ESTILOS  # noqa: E402
from ui.reportes_resumen_dia import PestañaResumenDelDia  # noqa: E402
from ui.utils import armar_filtro_por_fechas, formato_pesos  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestElRankingMuestraLasImpresionesAparte(unittest.TestCase):
    def test_la_de_kiosko_con_el_codigo_de_impresiones_pasa_a_impresiones(self):
        self.assertEqual(
            reportes_repo.categoria_a_la_vista(reportes_repo.CATEGORIA_KIOSKO, dominio.CODIGO_ARTICULO_IMPRESIONES),
            reportes_repo.CATEGORIA_IMPRESIONES)

    def test_las_demas_quedan_como_vienen(self):
        self.assertEqual(reportes_repo.categoria_a_la_vista(reportes_repo.CATEGORIA_KIOSKO, "COCA"),
                         reportes_repo.CATEGORIA_KIOSKO)
        # Un bono no tiene código de artículo: aunque viniera el "4", no es una impresión.
        self.assertEqual(
            reportes_repo.categoria_a_la_vista(reportes_repo.CATEGORIA_BONO_PC, dominio.CODIGO_ARTICULO_IMPRESIONES),
            reportes_repo.CATEGORIA_BONO_PC)


class TestUnColorPorRubroEnTodoElPrograma(unittest.TestCase):
    """Pedido del dueño: "bono de PC y bono de PlayStation diferentes colores, lo
    que sea de una misma categoría que mantengan color"."""

    def test_cada_categoria_del_ranking_tiene_su_nombre_corto_y_su_color(self):
        # Una categoría nueva en reportes_repo sin su lugar en RUBROS saldría en gris
        # y con el nombre largo, sin que nadie se entere: esta prueba avisa.
        categorias = {valor for nombre, valor in vars(reportes_repo).items() if nombre.startswith("CATEGORIA_")}
        self.assertEqual(categorias, set(reportes_piezas.RUBROS))
        for corto, tono in reportes_piezas.RUBROS.values():
            self.assertIn(tono, TONOS_DE_ETIQUETA, corto)

    def test_bono_de_pc_y_bono_de_playstation_van_de_colores_distintos(self):
        rubros = reportes_piezas.RUBROS
        self.assertNotEqual(rubros[reportes_repo.CATEGORIA_BONO_PC][1],
                            rubros[reportes_repo.CATEGORIA_BONO_PLAYSTATION][1])
        self.assertNotEqual(rubros[reportes_repo.CATEGORIA_BONO_PC][1], rubros[reportes_repo.CATEGORIA_KIOSKO][1])
        # Los dos de socios son el mismo rubro: el mismo color.
        self.assertEqual(rubros[reportes_repo.CATEGORIA_BONO_SOCIO][1],
                         rubros[reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO][1])

    def test_el_historial_del_turno_usa_los_mismos_colores_que_reportes(self):
        rubros = reportes_piezas.RUBROS
        for rubro_del_historial, categoria in (
            (historial_turno_repo.RUBRO_BONO_PC, reportes_repo.CATEGORIA_BONO_PC),
            (historial_turno_repo.RUBRO_PS5, reportes_repo.CATEGORIA_BONO_PLAYSTATION),
            (historial_turno_repo.RUBRO_PCSTREAM, reportes_repo.CATEGORIA_BONO_PCSTREAM),
            (historial_turno_repo.RUBRO_KIOSKO, reportes_repo.CATEGORIA_KIOSKO),
            (historial_turno_repo.RUBRO_IMPRESIONES, reportes_repo.CATEGORIA_IMPRESIONES),
            (historial_turno_repo.RUBRO_TRAMITE, reportes_repo.CATEGORIA_TRAMITE),
            (historial_turno_repo.RUBRO_MIEMBRO, reportes_repo.CATEGORIA_BONO_SOCIO),
            (historial_turno_repo.RUBRO_RESERVA, reportes_repo.CATEGORIA_RESERVA),
        ):
            with self.subTest(rubro=rubro_del_historial):
                self.assertEqual(TONOS_DEL_HISTORIAL[rubro_del_historial], rubros[categoria][1])

    def test_socios_y_bonos_usa_el_violeta_de_los_socios_y_el_azul_de_las_pcs(self):
        self.assertEqual(reportes_socios_bonos.COLOR_SOCIOS, color_fuerte(TONO_SOCIOS).name())
        self.assertEqual(reportes_socios_bonos.COLOR_BONOS, color_fuerte(TONO_PCS).name())

    def test_anulada_va_en_un_rojo_que_no_es_el_de_ningun_rubro(self):
        # En Consulta de Ventas una venta de la PS5 anulada llevaba dos etiquetas
        # rosas en el mismo renglón: el origen y el estado.
        tabla = QTableWidget(1, 1)
        self.addCleanup(tabla.deleteLater)
        anulada = etiqueta_de_estado(tabla, 0)._colores[dominio.VENTA_ANULADA]
        self.assertEqual(anulada, TONOS_DE_ETIQUETA[TONO_ALERTA])
        for corto, tono in reportes_piezas.RUBROS.values():
            self.assertNotEqual(anulada, TONOS_DE_ETIQUETA[tono], corto)

    def test_una_venta_sin_detalle_lleva_el_color_de_su_origen(self):
        # detalle_dia_repo._sin_articulo la nombra por su origen ("Alquiler de PCs").
        tabla = QTableWidget()
        self.addCleanup(tabla.deleteLater)
        colores = reportes_piezas.etiqueta_de_rubros(tabla)._colores
        nombre = dominio.NOMBRE_ORIGEN_VENTA
        self.assertEqual(colores[nombre[dominio.ORIGEN_ALQUILER_PCS]], TONOS_DE_ETIQUETA[TONO_PCS])
        self.assertEqual(colores[nombre[dominio.ORIGEN_PLAYSTATION]], TONOS_DE_ETIQUETA[TONO_PLAYSTATION])
        self.assertEqual(colores[nombre[dominio.ORIGEN_KIOSKO]], TONOS_DE_ETIQUETA[TONO_KIOSKO])


class _ConUnaVentaDeCadaCosa(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = next(u for u in usuarios_repo.listar_usuarios() if dominio.es_admin(u))
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 0)
        articulos_repo.crear_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "Impresión B/N", None, None,
                                      150.0, 0.0, 0)
        for codigo, descripcion, precio in (("COCA", "Coca 500", 1000.0),
                                            (dominio.CODIGO_ARTICULO_IMPRESIONES, "Impresión B/N", 150.0)):
            ventas_repo.confirmar_venta(
                self.admin["id"],
                [{"codigo": codigo, "descripcion": descripcion, "cantidad": 1, "precio_unitario": precio}],
                [{"metodo": dominio.PAGO_EFECTIVO, "monto": precio}],
            )
        # Y una con las dos cosas juntas: es de Kiosko.
        ventas_repo.confirmar_venta(
            self.admin["id"],
            [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": 1, "precio_unitario": 1000.0},
             {"codigo": dominio.CODIGO_ARTICULO_IMPRESIONES, "descripcion": "Impresión B/N", "cantidad": 2,
              "precio_unitario": 150.0}],
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1300.0}],
        )

    def _abrir(self, pantalla):
        self.addCleanup(pantalla.deleteLater)
        return pantalla


class TestLaVentanaConElMenuAlCostado(_ConUnaVentaDeCadaCosa):
    def test_el_menu_tiene_una_entrada_por_seccion_y_las_pestañas_no_se_ven(self):
        ventana = self._abrir(reportes_window.ReportesWindow())
        self.assertEqual(ventana.menu.count(), ventana.pestañas.count())
        self.assertEqual(ventana.menu.count(), len(reportes_window.SECCIONES))
        self.assertTrue(ventana.pestañas.tabBar().isHidden())
        # El menú, en mayúscula y con el nombre de cada pestaña.
        for fila in range(ventana.menu.count()):
            self.assertTrue(ventana.menu.item(fila).text().endswith(ventana.pestañas.tabText(fila).upper()))

    def test_elegir_en_el_menu_muestra_la_seccion_con_su_titulo_y_al_reves(self):
        ventana = self._abrir(reportes_window.ReportesWindow())
        self.assertEqual(ventana.titulo.text(), "RESUMEN DE VENTAS")

        ventana.menu.setCurrentRow(4)
        self.assertIsInstance(ventana.pestañas.currentWidget(), reportes_window.PestañaRanking)
        self.assertEqual(ventana.titulo.text(), "RANKING DE VENTAS")
        self.assertEqual(ventana.para_que.text(), reportes_window.SECCIONES[4][3])

        # Quien elija una pestaña por código mueve también el menú.
        ventana.pestañas.setCurrentIndex(5)
        self.assertEqual(ventana.menu.currentRow(), 5)
        self.assertEqual(ventana.titulo.text(), "POR OPERADOR")

    def test_el_titulo_de_arriba_va_en_mayuscula(self):
        ventana = self._abrir(reportes_window.ReportesWindow())
        titulos = [e.text() for e in ventana.findChildren(QLabel) if e.objectName() == "tituloCabecera"]
        self.assertEqual(titulos, ["REPORTES"])


class TestLosFiltrosVanEnSuTarjeta(_ConUnaVentaDeCadaCosa):
    def test_los_rotulos_y_botones_de_los_filtros_en_mayuscula(self):
        pestaña = self._abrir(reportes_window.PestañaPorTurno())
        tarjeta = next(f for f in pestaña.findChildren(QFrame) if f.objectName() == "tarjetaFiltrosReporte")
        rotulos = [e.text() for e in tarjeta.findChildren(QLabel) if e.objectName() == "rotuloFiltro"]
        self.assertEqual(rotulos, ["DESDE:", "HASTA:"])
        self.assertEqual([b.text() for b in tarjeta.findChildren(QPushButton)], ["SOLO HOY", "BUSCAR"])

    def test_fuera_de_reportes_los_filtros_quedan_como_estaban(self):
        # armar_filtro_por_fechas la usan también Artículos, Accesos de Admin...
        _desde, _hasta, filtros = armar_filtro_por_fechas(lambda: None)
        textos = [filtros.itemAt(i).widget().text() for i in range(filtros.count())
                  if isinstance(filtros.itemAt(i).widget(), (QLabel, QPushButton))]
        self.assertEqual(textos, ["Desde:", "Hasta:", "Buscar"])


class TestElRankingConLasEtiquetasDeColor(_ConUnaVentaDeCadaCosa):
    def _categorias(self, pestaña):
        tabla = pestaña.tabla
        return {tabla.item(fila, 3).text(): tabla.item(fila, 1) for fila in range(tabla.rowCount())}

    def test_las_impresiones_salen_aparte_de_kiosko_con_su_nombre_corto(self):
        pestaña = self._abrir(reportes_window.PestañaRanking())
        categorias = self._categorias(pestaña)
        self.assertEqual(categorias["Impresión B/N"].text(), "Impresiones")
        self.assertEqual(categorias["Coca 500"].text(), "Kiosko")
        self.assertEqual(categorias["Coca 500"].toolTip(), reportes_repo.CATEGORIA_KIOSKO)

    def test_la_categoria_es_una_etiqueta_grande_que_entra_entera(self):
        pestaña = self._abrir(reportes_window.PestañaRanking())
        tabla = pestaña.tabla
        delegado = tabla.itemDelegateForColumn(1)
        self.assertIs(delegado, pestaña.etiqueta_categoria)
        self.assertTrue(delegado.grande)
        self.assertEqual(delegado._colores["Impresiones"], TONOS_DE_ETIQUETA["gris"])
        self.assertEqual(delegado._colores["Bono de PC"], TONOS_DE_ETIQUETA[TONO_PCS])
        self.assertEqual(delegado._colores["Bono de PlayStation 5"], TONOS_DE_ETIQUETA[TONO_PLAYSTATION])
        # Del ancho de la más larga de todas, aunque esta búsqueda no la tenga.
        self.assertGreaterEqual(tabla.columnWidth(1), delegado.ancho_para("Bono de PlayStation 5", tabla.font()))

    def test_el_importe_en_negrita_a_la_derecha_y_el_titulo_en_mayuscula(self):
        pestaña = self._abrir(reportes_window.PestañaRanking())
        tabla = pestaña.tabla
        titulos = [tabla.horizontalHeaderItem(c).text() for c in range(tabla.columnCount())]
        self.assertEqual(titulos, ["CANTIDAD", "CATEGORÍA", "CÓDIGO", "DESCRIPCIÓN", "IMPORTE"])
        importe = tabla.item(0, 4)
        self.assertTrue(importe.font().bold())
        self.assertTrue(importe.textAlignment() & Qt.AlignRight)


class TestTotalesConLaBarraDeColorDeCadaRubro(_ConUnaVentaDeCadaCosa):
    # Cada título de rubro con el color que tiene que llevar su barra (escrito con
    # las constantes, no con el mapa que usa la pantalla: si no, se probaría solo).
    _BARRAS = {"KIOSKO": TONO_KIOSKO, "IMPRESIONES": TONO_IMPRESIONES, "TRÁMITES": TONO_TRAMITES,
               "ALQUILER DE PCS": TONO_PCS, "PLAYSTATION 5": TONO_PLAYSTATION}

    def _barras_esperadas(self, tabla):
        titulos = [tabla.horizontalHeaderItem(c).text() for c in range(tabla.columnCount())]
        return {titulos.index(titulo): tono for titulo, tono in self._BARRAS.items()}

    def _color_de_abajo_de_cada_titulo(self, pestaña):
        """{columna: el color que se ve en la franja de abajo de su título}."""
        pestaña.resize(1600, 700)
        pestaña.show()
        _app.processEvents()
        cabecera = pestaña.tabla.horizontalHeader()
        imagen = cabecera.grab().toImage()
        escala = imagen.devicePixelRatio()
        return {
            columna: imagen.pixelColor(
                int((cabecera.sectionViewportPosition(columna) + cabecera.sectionSize(columna) // 2) * escala),
                int((cabecera.height() - 2) * escala)).name()
            for columna in range(pestaña.tabla.columnCount())
        }

    def test_cada_rubro_tiene_la_barra_de_su_color(self):
        pestaña = self._abrir(reportes_window.PestañaKioskoVsPCs())
        tabla = pestaña.tabla
        cabecera = tabla.horizontalHeader()
        self.assertIsInstance(cabecera, CabeceraConColores)
        self.assertEqual(tabla.objectName(), "tablaConRubros")
        # Los cinco rubros y nada más: el período y el total no son un rubro.
        self.assertEqual(cabecera.tonos_por_columna, self._barras_esperadas(tabla))

    def test_las_barras_se_ven_pintadas_bajo_cada_titulo(self):
        pestaña = self._abrir(reportes_window.PestañaKioskoVsPCs())
        esperadas = self._barras_esperadas(pestaña.tabla)
        colores_de_rubro = {color_fuerte(tono).name() for tono in self._BARRAS.values()}
        for columna, color in self._color_de_abajo_de_cada_titulo(pestaña).items():
            with self.subTest(columna=pestaña.tabla.horizontalHeaderItem(columna).text()):
                if columna in esperadas:
                    self.assertEqual(color, color_fuerte(esperadas[columna]).name())
                else:
                    self.assertNotIn(color, colores_de_rubro)

    def test_la_plata_en_negrita_y_los_ceros_en_gris(self):
        pestaña = self._abrir(reportes_window.PestañaKioskoVsPCs())
        tabla = pestaña.tabla
        titulos = [tabla.horizontalHeaderItem(c).text() for c in range(tabla.columnCount())]
        kiosko = tabla.item(0, titulos.index("KIOSKO"))
        self.assertEqual(kiosko.text(), formato_pesos(2000.0))  # las dos Coca, sin las impresiones
        self.assertTrue(kiosko.font().bold())
        cero = tabla.item(0, titulos.index("PLAYSTATION 5"))
        self.assertEqual(cero.text(), reportes_piezas.CERO_PESOS)
        self.assertFalse(cero.font().bold())
        self.assertEqual(cero.foreground().color(), reportes_piezas.COLOR_CERO)

    def test_el_resumen_del_dia_tambien_tiene_las_barras(self):
        pestaña = self._abrir(PestañaResumenDelDia())
        cabecera = pestaña.tabla.horizontalHeader()
        self.assertIsInstance(cabecera, CabeceraConColores)
        # Bajo el título de cada rubro, no en otra columna.
        self.assertEqual(cabecera.tonos_por_columna, self._barras_esperadas(pestaña.tabla))
        # "Cerró" sigue siendo la que se estira, también con la cabecera nueva.
        self.assertEqual(cabecera.sectionResizeMode(2), QHeaderView.Stretch)


class TestElOrigenConElColorDeSuRubro(_ConUnaVentaDeCadaCosa):
    def test_consulta_de_ventas_y_por_operador_pintan_el_origen_igual(self):
        from ui.consulta_ventas_window import ConsultaVentasWindow
        from ui.reportes_operador import PestañaPorOperador

        consulta = self._abrir(ConsultaVentasWindow(self.admin))
        por_operador = self._abrir(PestañaPorOperador())
        for delegado in (consulta.etiqueta_origen, por_operador.etiqueta_origen):
            colores = delegado._colores
            self.assertEqual(colores[dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO]], TONOS_DE_ETIQUETA[TONO_KIOSKO])
            self.assertEqual(colores[dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS]],
                             TONOS_DE_ETIQUETA[TONO_PCS])
            self.assertEqual(colores[dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION]],
                             TONOS_DE_ETIQUETA[TONO_PLAYSTATION])


class TestElDetalleDelDiaMuestraLasImpresionesAparte(_ConUnaVentaDeCadaCosa):
    """Como el Ranking y TOTALES: una venta de solo impresiones es de Impresiones
    (gris); una con impresiones y otra cosa sigue siendo de Kiosko (verde)."""

    def _detalle(self):
        return detalle_dia_repo.detalle_del_dia(dia_en_que_empezo_el_turno(datetime.now()))

    def test_cada_venta_con_su_rubro(self):
        rubros = {venta["detalle"]: venta["rubro"] for venta in self._detalle()["ventas"]}
        self.assertEqual(rubros["1 x Impresión B/N"], reportes_repo.CATEGORIA_IMPRESIONES)
        self.assertEqual(rubros["1 x Coca 500"], reportes_repo.CATEGORIA_KIOSKO)
        self.assertEqual(rubros["1 x Coca 500, 2 x Impresión B/N"], reportes_repo.CATEGORIA_KIOSKO)

    def test_lo_vendido_suma_las_impresiones_aparte_aunque_vengan_con_otra_cosa(self):
        productos = {(f["rubro"], f["producto"]): f["cantidad"] for f in self._detalle()["por_producto"]}
        self.assertEqual(productos, {(reportes_repo.CATEGORIA_IMPRESIONES, "Impresión B/N"): 3,
                                     (reportes_repo.CATEGORIA_KIOSKO, "Coca 500"): 2})

    def test_el_historial_del_turno_sigue_igual(self):
        # Usa la misma lectura de lo vendido: la de solo impresiones es IMPRESIONES y la
        # mezclada, KIOSKO, que se encuentra también al filtrar por impresiones.
        ventas = {v["detalle"]: v for v in historial_turno_repo.historial_del_turno(self.admin["id"])["ventas"]}
        self.assertEqual(ventas["1 x Impresión B/N"]["rubro"], historial_turno_repo.RUBRO_IMPRESIONES)
        mezclada = ventas["1 x Coca 500, 2 x Impresión B/N"]
        self.assertEqual(mezclada["rubro"], historial_turno_repo.RUBRO_KIOSKO)
        self.assertIn(historial_turno_repo.RUBRO_IMPRESIONES, mezclada["rubros"])

    def test_la_pantalla_pinta_la_etiqueta_de_impresiones_en_gris(self):
        pestaña = self._abrir(PestañaResumenDelDia())
        tabla = pestaña.panel_detalle.tabla_productos
        etiquetas = {tabla.item(fila, 1).text(): tabla.item(fila, 0).text() for fila in range(tabla.rowCount())
                     if tabla.item(fila, 1) is not None}
        self.assertEqual(etiquetas["Impresión B/N"], "Impresiones")
        delegado = tabla.itemDelegateForColumn(0)
        self.assertEqual(delegado._colores["Impresiones"], TONOS_DE_ETIQUETA[TONO_IMPRESIONES])


class TestLosTitulosSeMidenComoSeDibujan(_ConUnaVentaDeCadaCosa):
    """Con la hoja de estilos de verdad: las secciones se llenan (y fijan el alto o
    el ancho de las columnas según los títulos) ANTES de entrar a la ventana de
    Reportes. Si los títulos se midieran ahí con otra letra que la que tienen
    adentro, saldrían mordidos y el TOTAL DEL DÍA, cortado (revisión del 2026-11-19)."""

    def setUp(self):
        super().setUp()
        hoja_de_antes = _app.styleSheet()
        _app.setStyleSheet(HOJA_DE_ESTILOS)
        self.addCleanup(_app.setStyleSheet, hoja_de_antes)

    def _abrir_en(self, clase, ancho=1840, alto=900):
        """La ventana abierta en la sección `clase`, del tamaño con que se abre en la
        pantalla de 1920 del mostrador (o del que se pida)."""
        ventana = self._abrir(reportes_window.ReportesWindow())
        ventana.setAttribute(Qt.WA_DontShowOnScreen)
        ventana.show()
        ventana.resize(ancho, alto)
        ventana.menu.setCurrentRow(next(i for i, seccion in enumerate(reportes_window.SECCIONES) if seccion[0] is clase))
        for _ in range(5):
            _app.processEvents()
        return ventana.pestañas.currentWidget()

    def _el_total_del_dia_se_ve_entero(self, tabla):
        self.assertEqual(tabla.verticalScrollBar().maximum(), 0)
        ultima = tabla.visualRect(tabla.model().index(tabla.rowCount() - 1, 0))
        self.assertEqual(tabla.item(tabla.rowCount() - 1, 0).text(), "TOTAL DEL DÍA")
        self.assertLessEqual(ultima.bottom(), tabla.viewport().rect().bottom())

    def test_la_grilla_de_los_turnos_mide_justo_lo_que_muestra(self):
        # Sin hueco abajo: los títulos, los renglones y (si las columnas no entran a lo
        # ancho; acá, en "offscreen", la letra sale más ancha que en Windows) la barra.
        tabla = self._abrir_en(PestañaResumenDelDia).tabla
        barra = tabla.horizontalScrollBar()
        hace_falta = (tabla.horizontalHeader().sizeHint().height() + tabla.verticalHeader().length()
                      + 2 * tabla.frameWidth() + (barra.height() if barra.isVisible() else 0))
        self.assertEqual(tabla.height(), hace_falta)
        self._el_total_del_dia_se_ve_entero(tabla)

    def test_en_una_pantalla_angosta_la_barra_de_abajo_no_tapa_el_total_del_dia(self):
        tabla = self._abrir_en(PestañaResumenDelDia, ancho=1000, alto=760).tabla
        self.assertTrue(tabla.horizontalScrollBar().isVisible())
        self._el_total_del_dia_se_ve_entero(tabla)

    def test_los_titulos_del_detalle_del_dia_entran_enteros(self):
        panel = self._abrir_en(PestañaResumenDelDia).panel_detalle
        for tabla in (panel.tabla_renglones, panel.tabla_ventas, panel.tabla_productos, panel.tabla_operadores):
            cabecera = tabla.horizontalHeader()
            for columna in range(tabla.columnCount()):
                if cabecera.sectionResizeMode(columna) == QHeaderView.Stretch:
                    continue
                with self.subTest(titulo=tabla.horizontalHeaderItem(columna).text()):
                    self.assertGreaterEqual(tabla.columnWidth(columna), cabecera.sectionSizeHint(columna))


if __name__ == "__main__":
    unittest.main()
