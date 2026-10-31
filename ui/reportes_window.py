"""
reportes_window.py
=====================
Reportes, una pestaña por cada pregunta que se le hace a las ventas:

- Resumen de Ventas: cuánta plata se trabajó en un rango de fechas.
- Resumen del Día: un día abierto por turno, con quién cerró y si el sobre
  cuadró; Kiosko, Impresiones, Trámites, Alquiler de PCs y PlayStation 5 van en
  columnas aparte. Abajo, el detalle de todo lo vendido (venta por venta, por
  producto y por operador) del día o del turno que se toque (en su propio
  archivo, ui/reportes_detalle_dia.py).
- Por Turno: el total de un rango repartido entre Mañana/Tarde/Noche.
- Totales: Kiosko / Impresiones / Trámites / Alquiler de PCs / PlayStation 5,
  por turno, día, semana o rango.
- Ranking de Ventas: qué se vendió más -- artículos de kiosko, bonos de PC,
  bonos de socios, cargas de saldo por tarifa, trámites y bonos de la
  PlayStation 5, todo junto, con una columna Categoría para distinguir de qué
  rubro vino cada fila (ver reportes_repo.ranking_ventas).
- Por Operador: quién vendió cuánto y, de cada uno, sus ventas con fecha y
  hora (en su propio archivo, ui/reportes_operador.py).
- PCSTREAM: cuánto se usa la PC de streaming, en tiempo y en plata, día por día
  (en su propio archivo, ui/reportes_pcstream.py).
- PCs: Socios y Bonos: lo que dejaron las PCs, separado en cargas a socios y
  bonos del mostrador, y comparado (ui/reportes_socios_bonos.py).

Las usa el Admin o una Empleada con `permiso_reportes`.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout,
    QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QWidget,
)

import dominio
from repositories import reportes_repo
from ui.dibujos_tabla import DelegadoEtiqueta
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_VERDE, agregar_pastilla, cabecera_oscura, cifra_destacada, panel_de_tabla,
    pie_de_ventana, titulo_de_seccion,
)
# Resumen del Día vive en su propio archivo; se importa también desde acá
# (ui.reportes_window.PestañaResumenDelDia), como antes de partirlo.
from ui.reportes_resumen_dia import PestañaResumenDelDia
from ui.reportes_operador import PestañaPorOperador
from ui.reportes_pcstream import PestañaPcstream
from ui.reportes_socios_bonos import PestañaSociosYBonos
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, manejar_errores, sin_boton_por_defecto,
    crear_tabla, rango_de_fechas, hoy_del_local,
    mostrar_columna_entera,
)

# Margen de arriba del contenido de cada pestaña: con las pestañas sin recuadro
# (documentMode) el contenido queda alineado con la cabecera y la nota de abajo.
MARGENES_DE_PESTAÑA = (0, 12, 0, 0)


class ReportesWindow(QDialog):
    """Contenedor de las pestañas de reportes (cada una es un QWidget
    independiente que busca y se muestra sola, ver las clases de abajo).

    Con la maqueta B que eligió el dueño el 2026-10-30 (ui/piezas_ventana.py): la
    cabecera oscura arriba de las pestañas, cada pestaña con su grilla en un panel
    blanco (panel_de_tabla) y abajo la línea de cómo se cuenta un día. La cabecera no
    lleva números: cada pestaña tiene su propio rango de fechas y un número arriba
    no diría de cuál es."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reportes")
        # El Resumen del Día tiene 13 columnas: con menos ancho la de "Cerró" (el
        # nombre de quien cerró cada turno) queda tan angosta que corta el nombre.
        # No más ancho que la pantalla, para que la ventana no se salga de ella.
        # Alto: el Resumen del Día lleva abajo el detalle de las ventas.
        ancho, alto = 1420, 820
        if self.screen() is not None:
            ancho = min(ancho, self.screen().availableGeometry().width() - 20)
            alto = min(alto, self.screen().availableGeometry().height() - 40)
        self.resize(ancho, alto)

        cabecera = cabecera_oscura(
            "📊", "Reportes", "Lo vendido por día, por turno, por negocio, por artículo y por operador")
        agregar_pastilla(cabecera, "DÍAS DE 06:00 A 06:00", TONO_GRIS)

        # Sin el recuadro de las pestañas: cada una ya pone sus grillas en un panel
        # blanco, y con los dos bordes juntos se veía un cuadro adentro de otro.
        self.pestañas = QTabWidget()
        self.pestañas.setDocumentMode(True)
        self.pestañas.addTab(PestañaResumen(), "Resumen de Ventas")
        self.pestañas.addTab(PestañaResumenDelDia(), "Resumen del Día")
        self.pestañas.addTab(PestañaPorTurno(), "Por Turno")
        self.pestañas.addTab(PestañaKioskoVsPCs(), "Totales")
        self.pestañas.addTab(PestañaRanking(), "Ranking de Ventas")
        self.pestañas.addTab(PestañaPorOperador(), "Por Operador")
        self.pestañas.addTab(PestañaPcstream(), dominio.NOMBRE_PCSTREAM)
        self.pestañas.addTab(PestañaSociosYBonos(), "PCs: Socios y Bonos")

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(self.pestañas, 1)
        # Cómo se cuenta un día en TODAS las pestañas (pedido del dueño): sin
        # esto, ver la madrugada del 2 sumada en el día 1 parecería un error.
        layout.addWidget(pie_de_ventana(
            "Cada día va de las 06:00 a las 06:00 del día siguiente: el turno Noche "
            "(22 a 06) cuenta entero en el día en que empezó."
        ))
        self.setLayout(layout)
        sin_boton_por_defecto(self)


class PestañaResumen(QWidget):
    """Total vendido, cantidad de ventas y desglose Efectivo/Digital de un
    rango de fechas, en las cifras grandes de Caja (piezas_ventana.cifra_destacada)."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True, dias_del_local=True)

        total = cifra_destacada("TOTAL VENDIDO", "", TONO_AZUL)
        efectivo = cifra_destacada("EFECTIVO", "Lo cobrado en efectivo", TONO_VERDE)
        digital = cifra_destacada("DIGITAL", "Lo cobrado por medios digitales", TONO_AZUL)
        self.etiqueta_total = total.valor
        self.etiqueta_cantidad = total.aclaracion
        self.etiqueta_efectivo = efectivo.valor
        self.etiqueta_digital = digital.valor
        cifras = QHBoxLayout()
        cifras.setSpacing(12)
        for cifra in (total, efectivo, digital):
            cifras.addWidget(cifra, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addLayout(filtros)
        layout.addLayout(cifras)
        layout.addStretch()
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        resumen = reportes_repo.resumen_ventas(desde, hasta)
        self.etiqueta_total.setText(formato_pesos(resumen["total"]))
        self.etiqueta_cantidad.setText(f"{resumen['cantidad_ventas']} venta(s)")
        self.etiqueta_efectivo.setText(formato_pesos(resumen["efectivo"]))
        self.etiqueta_digital.setText(formato_pesos(resumen["digital"]))


class PestañaPorTurno(QWidget):
    """Desglosa el total vendido en un rango de fechas por turno
    (Mañana/Tarde/Noche), para responder "¿cuánto trabajó la Tarde esta
    semana?" sin tener que sumar a mano los cierres cargados."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True, dias_del_local=True)

        # Se estira la última: estirada la del turno, la etiqueta quedaba sola a la
        # izquierda y los números lejos, del otro lado.
        self.tabla = crear_tabla(["Turno", "Total vendido", "Ventas", "Efectivo", "Digital"], estirar=4)
        for columna, ancho in enumerate((150, 160, 110, 160)):
            self.tabla.setColumnWidth(columna, ancho)
        # El turno en una etiqueta de color, siempre el mismo para cada uno (como el
        # rubro en Artículos); la celda sigue teniendo su texto.
        etiqueta_turno = DelegadoEtiqueta(self.tabla)
        etiqueta_turno.colores_en_orden([turno.capitalize() for turno in dominio.TURNOS])
        self.tabla.setItemDelegateForColumn(0, etiqueta_turno)

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addLayout(filtros)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        filas = reportes_repo.resumen_por_turno(desde, hasta)

        self.tabla.setRowCount(0)
        for fila_datos in filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(fila_datos["turno"].capitalize()))
            self.tabla.setItem(fila, 1, QTableWidgetItem(formato_pesos(fila_datos["total"])))
            self.tabla.setItem(fila, 2, QTableWidgetItem(str(fila_datos["cantidad_ventas"])))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(fila_datos["efectivo"])))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(fila_datos["digital"])))


# Las columnas de plata de la pestaña "Totales", en el orden en que se ven: son
# las claves de cada fila de reportes_repo.resumen_por_origen.
_COLUMNAS_DE_TOTALES = ("kiosko", "impresiones", "tramites", "pcs", "playstation", "total")


class PestañaKioskoVsPCs(QWidget):
    """Desglosa lo facturado en Kiosko, Impresiones, Trámites, Alquiler de PCs y
    PlayStation 5 (ver dominio.NOMBRE_ORIGEN_VENTA) en un rango de fechas,
    agrupado a elección por turno, día, semana o el total del rango completo."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_agrupar = QComboBox()
        self.combo_agrupar.addItem("Total del rango", "rango")
        self.combo_agrupar.addItem("Por Turno", "turno")
        self.combo_agrupar.addItem("Por Día", "dia")
        self.combo_agrupar.addItem("Por Semana", "semana")
        self.combo_agrupar.currentIndexChanged.connect(self._buscar)

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, extras=[("Agrupar:", self.combo_agrupar)], solo_hoy=True, dias_del_local=True
        )

        self.tabla = crear_tabla(
            ["Período", "Kiosko", "Impresiones", "Trámites", "Alquiler de PCs", "PlayStation 5", "Total"],
            estirar=0,
        )

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addLayout(filtros)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        layout.addWidget(pie_de_ventana("Impresiones y Trámites se muestran aparte: no están sumados en Kiosko."))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_fila(self, datos: dict, negrita: bool = False):
        """Una fila de la tabla; `datos` es una fila de
        reportes_repo.resumen_por_origen (o una armada igual, ver el TOTAL
        de _buscar)."""
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        for columna, valor in enumerate([
            datos["etiqueta"],
            *(formato_pesos(datos[clave]) for clave in _COLUMNAS_DE_TOTALES),
        ]):
            item = QTableWidgetItem(valor)
            if negrita:
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
            self.tabla.setItem(fila, columna, item)

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" no se usa: absorbe el índice que manda
        # `currentIndexChanged` (ver ControlCierresWindow._ver_detalle en
        # caja_window.py).
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        agrupar_por = self.combo_agrupar.currentData()
        filas = reportes_repo.resumen_por_origen(desde, hasta, agrupar_por)

        self.tabla.setRowCount(0)
        for fila_datos in filas:
            self._agregar_fila(fila_datos)

        # Fila TOTAL al pie cuando hay más de un período listado -- con
        # "Total del rango" ya sobraría, es la única fila que hay.
        if agrupar_por != "rango" and len(filas) > 1:
            sumas = {
                clave: sum(fila[clave] for fila in filas)
                for clave in _COLUMNAS_DE_TOTALES
            }
            self._agregar_fila({"etiqueta": "TOTAL", **sumas}, negrita=True)


class PestañaRanking(QWidget):
    """Ranking de TODO lo vendido (kiosko, bonos de PC, de socios y de la
    PlayStation 5, cargas de saldo y trámites) en un rango de fechas, ordenable
    por cantidad o por monto."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_orden = QComboBox()
        self.combo_orden.addItem("Por Cantidad vendida", "cantidad")
        self.combo_orden.addItem("Por Monto ($)", "monto")

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, hoy_del_local().addMonths(-1),
            extras=[("Ordenar:", self.combo_orden)], dias_del_local=True,
        )

        self.etiqueta_titulo = titulo_de_seccion("")

        self.tabla = crear_tabla(["Cantidad", "Categoría", "Código", "Descripción", "Importe"], estirar=3)
        # La categoría se muestra entera: con el ancho fijo de siempre, "Bono de
        # PlayStation 5" y "Bono de Socio" se cortaban igual ("Bono de ...") y no
        # se podían distinguir.
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        orden = self.combo_orden.currentData()

        # En mayúscula, como todo título de sección (titulo_de_seccion lo pone solo al armarlo).
        self.etiqueta_titulo.setText(
            f"Ranking de Ventas del {self.fecha_desde.date().toString('dd/MM/yyyy')} "
            f"al {self.fecha_hasta.date().toString('dd/MM/yyyy')}".upper()
        )

        filas = reportes_repo.ranking_ventas(desde, hasta, orden)
        self.tabla.setRowCount(0)
        for fila_datos in filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(fila_datos["cantidad"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(fila_datos["categoria"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(fila_datos["codigo"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(fila_datos["descripcion"]))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(fila_datos["importe"])))
        mostrar_columna_entera(self.tabla, 2)
