"""
consulta_ventas_window.py
============================
Pantalla de Consulta de Ventas: muestra las últimas ventas cargadas, con
su detalle. La ve el Admin o una Empleada con `permiso_consulta_ventas`,
pero solo el Admin puede "Anular" una venta ya confirmada desde acá (a
propósito no es delegable: es por donde se podría "arreglar" una caja).
Anular repone el stock automáticamente y deja registrado quién la anuló,
cuándo y por qué (nunca se borra el registro original).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLabel, QHeaderView, QInputDialog
)
from PySide6.QtCore import Qt

import dominio
from repositories import ventas_repo
from control_pcs.repositories import miembros_repo
from ui.utils import formato_pesos, mostrar_error, mostrar_info, confirmar, manejar_errores, aplicar_clase, sin_boton_por_defecto


class ConsultaVentasWindow(QDialog):
    """Lista de las últimas 100 ventas y, abajo, el detalle de la elegida."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self.setWindowTitle("Consulta de Ventas")
        self.resize(850, 500)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(
            ["Nº Factura", "Fecha", "Turno", "Vendedor", "Total", "Estado"]
        )
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)

        self.tabla_detalle = QTableWidget(0, 4)
        self.tabla_detalle.setHorizontalHeaderLabels(["Código", "Descripción", "Cantidad", "Subtotal"])
        self.tabla_detalle.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_detalle.setAlternatingRowColors(True)
        self.tabla_detalle.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)

        botones = QHBoxLayout()
        boton_refrescar = QPushButton("Refrescar")
        boton_refrescar.clicked.connect(self._cargar)
        botones.addWidget(boton_refrescar)
        botones.addStretch()

        if self.es_admin:
            self.boton_anular = QPushButton("Anular venta seleccionada")
            aplicar_clase(self.boton_anular, "peligro")
            self.boton_anular.clicked.connect(self._anular)
            botones.addWidget(self.boton_anular)

        boton_cerrar = QPushButton("Salir")
        boton_cerrar.clicked.connect(self.close)
        botones.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addLayout(botones)
        layout.addWidget(QLabel("Ventas (más recientes primero):"))
        layout.addWidget(self.tabla)
        layout.addWidget(QLabel("Detalle de la venta seleccionada:"))
        layout.addWidget(self.tabla_detalle)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        self.ventas = ventas_repo.listar_ventas_recientes(100)
        self.tabla.setRowCount(0)
        for venta in self.ventas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(venta["id"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(venta["fecha"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(venta["turno"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(venta["vendedor"]))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(venta["total"])))
            item_estado = QTableWidgetItem(venta["estado"])
            if venta["estado"] == dominio.VENTA_ANULADA:
                item_estado.setForeground(Qt.red)
            self.tabla.setItem(fila, 5, item_estado)
        self.tabla_detalle.setRowCount(0)

    def _venta_seleccionada(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            return None
        return self.ventas[fila]

    @manejar_errores
    def _mostrar_detalle(self):
        venta = self._venta_seleccionada()
        self.tabla_detalle.setRowCount(0)
        if venta is None:
            return
        _venta, detalle, _pagos = ventas_repo.buscar_venta(venta["id"])
        for linea in detalle:
            fila = self.tabla_detalle.rowCount()
            self.tabla_detalle.insertRow(fila)
            self.tabla_detalle.setItem(fila, 0, QTableWidgetItem(linea["articulo_codigo"]))
            self.tabla_detalle.setItem(fila, 1, QTableWidgetItem(linea["descripcion"]))
            self.tabla_detalle.setItem(fila, 2, QTableWidgetItem(str(linea["cantidad"])))
            self.tabla_detalle.setItem(fila, 3, QTableWidgetItem(formato_pesos(linea["subtotal"])))

    @manejar_errores
    def _anular(self):
        venta = self._venta_seleccionada()
        if venta is None:
            mostrar_error(self, "Nada seleccionado", "Elegí primero una venta de la lista.")
            return
        if venta["estado"] == dominio.VENTA_ANULADA:
            mostrar_error(self, "Ya anulada", "Esa venta ya estaba anulada.")
            return

        if not confirmar(self, "Anular venta",
                          f"¿Anular la venta Nº {venta['id']} por {formato_pesos(venta['total'])}?\n"
                          "El stock de los artículos se repone automáticamente."):
            return

        motivo, aceptado = QInputDialog.getText(
            self, "Motivo de la anulación", "Contá brevemente por qué se anula esta venta:"
        )
        if not aceptado or not motivo.strip():
            mostrar_error(self, "Falta el motivo", "Tenés que indicar un motivo para anular la venta.")
            return

        # Una venta de "Alquiler de PCs" puede ser una carga de saldo de
        # socio -- esa sí necesita revertir los minutos ya acreditados,
        # no solo cambiar el estado de la venta (ver
        # miembros_repo.anular_carga). Las de Kiosko nunca cargan saldo,
        # así que siguen con el camino simple de siempre.
        if venta["origen"] == dominio.ORIGEN_ALQUILER_PCS:
            miembros_repo.anular_carga(venta["id"], self.usuario["id"], motivo.strip())
        else:
            ventas_repo.anular_venta(venta["id"], self.usuario["id"], motivo.strip())
        mostrar_info(self, "Venta anulada", f"Se anuló la venta Nº {venta['id']}.")
        self._cargar()
