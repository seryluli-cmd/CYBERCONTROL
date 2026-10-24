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
    QDialog, QVBoxLayout, QHBoxLayout, QLabel,
    QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

import dominio
from repositories import reportes_repo
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


class ReportesWindow(QDialog):
    """Contenedor de las pestañas de reportes (cada una es un QWidget
    independiente que busca y se muestra sola, ver las clases de abajo)."""

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

        pestañas = QTabWidget()
        pestañas.addTab(PestañaResumen(), "Resumen de Ventas")
        pestañas.addTab(PestañaResumenDelDia(), "Resumen del Día")
        pestañas.addTab(PestañaPorTurno(), "Por Turno")
        pestañas.addTab(PestañaKioskoVsPCs(), "Totales")
        pestañas.addTab(PestañaRanking(), "Ranking de Ventas")
        pestañas.addTab(PestañaPorOperador(), "Por Operador")
        pestañas.addTab(PestañaPcstream(), dominio.NOMBRE_PCSTREAM)
        pestañas.addTab(PestañaSociosYBonos(), "PCs: Socios y Bonos")

        # Cómo se cuenta un día en TODAS las pestañas (pedido del dueño): sin
        # esto, ver la madrugada del 2 sumada en el día 1 parecería un error.
        nota_dias = QLabel(
            "Cada día va de las 06:00 a las 06:00 del día siguiente: el turno Noche "
            "(22 a 06) cuenta entero en el día en que empezó."
        )
        nota_dias.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addWidget(pestañas)
        layout.addWidget(nota_dias)
        self.setLayout(layout)
        sin_boton_por_defecto(self)


class PestañaResumen(QWidget):
    """Total vendido, cantidad de ventas y desglose Efectivo/Digital de un
    rango de fechas."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True, dias_del_local=True)

        fuente_grande = QFont()
        fuente_grande.setPointSize(20)
        fuente_grande.setBold(True)

        self.etiqueta_total = QLabel()
        self.etiqueta_total.setFont(fuente_grande)
        self.etiqueta_total.setStyleSheet("color: #2F6FED;")
        self.etiqueta_total.setAlignment(Qt.AlignCenter)

        self.etiqueta_cantidad = QLabel()
        self.etiqueta_cantidad.setAlignment(Qt.AlignCenter)

        self.etiqueta_efectivo = QLabel()
        self.etiqueta_digital = QLabel()
        detalle_pagos = QHBoxLayout()
        detalle_pagos.addStretch()
        detalle_pagos.addWidget(self.etiqueta_efectivo)
        detalle_pagos.addSpacing(30)
        detalle_pagos.addWidget(self.etiqueta_digital)
        detalle_pagos.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(20)
        titulo_total = QLabel("TOTAL VENDIDO", alignment=Qt.AlignCenter)
        titulo_total.setStyleSheet("color: #6B7585; font-size: 12px; font-weight: 600;")
        layout.addWidget(titulo_total)
        layout.addWidget(self.etiqueta_total)
        layout.addWidget(self.etiqueta_cantidad)
        layout.addSpacing(10)
        layout.addLayout(detalle_pagos)
        layout.addStretch()
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        resumen = reportes_repo.resumen_ventas(desde, hasta)
        self.etiqueta_total.setText(formato_pesos(resumen["total"]))
        self.etiqueta_cantidad.setText(f"{resumen['cantidad_ventas']} venta(s)")
        self.etiqueta_efectivo.setText(f"Efectivo: {formato_pesos(resumen['efectivo'])}")
        self.etiqueta_digital.setText(f"Digital: {formato_pesos(resumen['digital'])}")


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

        self.tabla = crear_tabla(["Turno", "Total vendido", "Ventas", "Efectivo", "Digital"], estirar=0)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(10)
        layout.addWidget(self.tabla)
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

        nota = QLabel("Impresiones y Trámites se muestran aparte: no están sumados en Kiosko.")
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(10)
        layout.addWidget(self.tabla)
        layout.addWidget(nota)
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
            extras=[("Ordenar:", self.combo_orden)], estirar=False, dias_del_local=True,
        )

        self.etiqueta_titulo = QLabel()
        self.etiqueta_titulo.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.etiqueta_titulo.setAlignment(Qt.AlignCenter)

        self.tabla = crear_tabla(["Cantidad", "Categoría", "Código", "Descripción", "Importe"], estirar=3)
        # La categoría se muestra entera: con el ancho fijo de siempre, "Bono de
        # PlayStation 5" y "Bono de Socio" se cortaban igual ("Bono de ...") y no
        # se podían distinguir.
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        orden = self.combo_orden.currentData()

        self.etiqueta_titulo.setText(
            f"Ranking de Ventas del {self.fecha_desde.date().toString('dd/MM/yyyy')} "
            f"al {self.fecha_hasta.date().toString('dd/MM/yyyy')}"
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
