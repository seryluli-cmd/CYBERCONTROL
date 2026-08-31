"""
reportes_window.py
=====================
Reportes: Resumen (cuánta plata se trabajó en un rango de fechas) y
Ranking de Ventas por artículo (qué se vendió más), replicando el
formato de columnas (Cantidad, Código, Descripción, Importe) que ya
usaba el sistema anterior.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDateEdit,
    QTableWidget, QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QWidget
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QFont

from repositories import reportes_repo
from ui.utils import formato_pesos, manejar_errores, aplicar_clase, encadenar_enter


class ReportesWindow(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reportes")
        self.resize(750, 550)

        pestañas = QTabWidget()
        pestañas.addTab(PestañaResumen(), "Resumen de Ventas")
        pestañas.addTab(PestañaPorTurno(), "Por Turno")
        pestañas.addTab(PestañaRanking(), "Ranking de Ventas")

        layout = QVBoxLayout()
        layout.addWidget(pestañas)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)


class PestañaResumen(QWidget):
    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde = QDateEdit(QDate.currentDate())
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_hasta = QDateEdit(QDate.currentDate())
        self.fecha_hasta.setCalendarPopup(True)
        boton_hoy = QPushButton("Solo Hoy")
        boton_hoy.clicked.connect(self._poner_solo_hoy)
        boton_buscar = QPushButton("Buscar")
        boton_buscar.clicked.connect(self._buscar)
        encadenar_enter(self.fecha_desde, self.fecha_hasta, accion_final=self._buscar)

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Desde:"))
        filtros.addWidget(self.fecha_desde)
        filtros.addWidget(QLabel("Hasta:"))
        filtros.addWidget(self.fecha_hasta)
        filtros.addWidget(boton_hoy)
        filtros.addWidget(boton_buscar)
        filtros.addStretch()

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
        layout.addWidget(QLabel("TOTAL VENDIDO", alignment=Qt.AlignCenter))
        layout.addWidget(self.etiqueta_total)
        layout.addWidget(self.etiqueta_cantidad)
        layout.addSpacing(10)
        layout.addLayout(detalle_pagos)
        layout.addStretch()
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _poner_solo_hoy(self):
        self.fecha_desde.setDate(QDate.currentDate())
        self.fecha_hasta.setDate(QDate.currentDate())
        self._buscar()

    @manejar_errores
    def _buscar(self):
        desde = self.fecha_desde.date().toString("yyyy-MM-dd")
        hasta = self.fecha_hasta.date().toString("yyyy-MM-dd")
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
        self.fecha_desde = QDateEdit(QDate.currentDate())
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_hasta = QDateEdit(QDate.currentDate())
        self.fecha_hasta.setCalendarPopup(True)
        boton_hoy = QPushButton("Solo Hoy")
        boton_hoy.clicked.connect(self._poner_solo_hoy)
        boton_buscar = QPushButton("Buscar")
        boton_buscar.clicked.connect(self._buscar)
        encadenar_enter(self.fecha_desde, self.fecha_hasta, accion_final=self._buscar)

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Desde:"))
        filtros.addWidget(self.fecha_desde)
        filtros.addWidget(QLabel("Hasta:"))
        filtros.addWidget(self.fecha_hasta)
        filtros.addWidget(boton_hoy)
        filtros.addWidget(boton_buscar)
        filtros.addStretch()

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Turno", "Total vendido", "Ventas", "Efectivo", "Digital"])
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(10)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _poner_solo_hoy(self):
        self.fecha_desde.setDate(QDate.currentDate())
        self.fecha_hasta.setDate(QDate.currentDate())
        self._buscar()

    @manejar_errores
    def _buscar(self):
        desde = self.fecha_desde.date().toString("yyyy-MM-dd")
        hasta = self.fecha_hasta.date().toString("yyyy-MM-dd")
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


class PestañaRanking(QWidget):
    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde = QDateEdit(QDate.currentDate().addMonths(-1))
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_hasta = QDateEdit(QDate.currentDate())
        self.fecha_hasta.setCalendarPopup(True)

        self.combo_orden = QComboBox()
        self.combo_orden.addItem("Por Cantidad vendida", "cantidad")
        self.combo_orden.addItem("Por Monto ($)", "monto")

        boton_buscar = QPushButton("Buscar")
        boton_buscar.clicked.connect(self._buscar)
        encadenar_enter(self.fecha_desde, self.fecha_hasta, self.combo_orden, accion_final=self._buscar)

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Desde:"))
        filtros.addWidget(self.fecha_desde)
        filtros.addWidget(QLabel("Hasta:"))
        filtros.addWidget(self.fecha_hasta)
        filtros.addWidget(QLabel("Ordenar:"))
        filtros.addWidget(self.combo_orden)
        filtros.addWidget(boton_buscar)

        self.etiqueta_titulo = QLabel()
        self.etiqueta_titulo.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.etiqueta_titulo.setAlignment(Qt.AlignCenter)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Cantidad", "Código", "Descripción", "Importe"])
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _buscar(self):
        desde = self.fecha_desde.date().toString("yyyy-MM-dd")
        hasta = self.fecha_hasta.date().toString("yyyy-MM-dd")
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
            self.tabla.setItem(fila, 1, QTableWidgetItem(fila_datos["codigo"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(fila_datos["descripcion"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(fila_datos["importe"])))
