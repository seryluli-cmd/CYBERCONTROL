"""
reportes_operador.py
======================
Pestaña "Por Operador" de Reportes (pedido del dueño, 2026-10-17): quién
vendió cuánto en un rango de fechas y, al elegir a alguien, sus ventas una por
una con la fecha y la hora en que se registraron. Vive aparte de
reportes_window.py porque ese archivo ya estaba cerca del tope de ~600 líneas
(CLAUDE.md, regla 12).

La venta queda a nombre de quien tenía la sesión abierta en el mostrador: si
alguien vende con la sesión de otro, sale a nombre del otro (ver
reportes_repo.resumen_por_operador).
"""

from datetime import datetime

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

import dominio
from repositories import reportes_repo
from turnos import dia_en_que_empezo_el_turno, etiqueta_turno
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, formato_fecha_hora, manejar_errores,
    sin_boton_por_defecto, crear_tabla, rango_de_fechas,
)

_COLOR_ANULADA = QColor("#C62828")

# Columnas de plata de cada tabla: se alinean a la derecha.
_COLUMNAS_PLATA_OPERADORES = (3, 4, 5)
_COLUMNAS_PLATA_VENTAS = (4, 5, 6)


def _celda(texto, derecha=False, color=None):
    item = QTableWidgetItem(texto)
    if derecha:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color is not None:
        item.setForeground(color)
    return item


class PestañaPorOperador(QWidget):
    """Arriba, un resumen por operador; abajo, las ventas del elegido."""

    def __init__(self):
        super().__init__()
        self._operadores = []   # filas de reportes_repo.resumen_por_operador
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True)

        self.tabla_operadores = crear_tabla(
            ["Operador", "Ventas", "Anuladas", "Efectivo", "Digital", "Total"],
            estirar=0, por_filas=True, una_sola=True,
        )
        self.tabla_operadores.itemSelectionChanged.connect(self._mostrar_ventas_del_elegido)

        self.etiqueta_detalle = QLabel()
        self.etiqueta_detalle.setStyleSheet("font-weight: bold; font-size: 13px; padding-top: 6px;")

        self.tabla_ventas = crear_tabla(
            ["Fecha y hora", "Turno", "Origen", "Concepto", "Efectivo", "Digital", "Total", "Estado"],
            estirar=3, por_filas=True,
        )
        # Todas al ancho de su contenido menos "Concepto", que se estira: con el
        # ancho por defecto, "Fecha y hora" cortaba justo la hora.
        for columna in range(self.tabla_ventas.columnCount()):
            if columna != 3:
                self.tabla_ventas.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)

        nota = QLabel(
            "Cada venta queda a nombre de quien tenía la sesión abierta. Las anuladas se "
            "muestran en rojo y no suman en los totales."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.tabla_operadores, 2)
        layout.addWidget(self.etiqueta_detalle)
        layout.addWidget(self.tabla_ventas, 3)
        layout.addWidget(nota)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        elegido_antes = self._usuario_elegido()
        self._operadores = reportes_repo.resumen_por_operador(desde, hasta)

        self.tabla_operadores.blockSignals(True)
        self.tabla_operadores.setRowCount(0)
        for operador in self._operadores:
            fila = self.tabla_operadores.rowCount()
            self.tabla_operadores.insertRow(fila)
            valores = [
                operador["nombre"],
                str(operador["cantidad_ventas"]),
                str(operador["cantidad_anuladas"]) if operador["cantidad_anuladas"] else "—",
                formato_pesos(operador["efectivo"]),
                formato_pesos(operador["digital"]),
                formato_pesos(operador["total"]),
            ]
            for columna, valor in enumerate(valores):
                self.tabla_operadores.setItem(
                    fila, columna, _celda(valor, derecha=columna in _COLUMNAS_PLATA_OPERADORES)
                )
        # Queda elegido el mismo operador de antes si sigue en la lista; si no, el
        # primero. Con las señales todavía apagadas: las ventas se cargan una sola
        # vez, abajo.
        ids = [operador["usuario_id"] for operador in self._operadores]
        if self._operadores:
            self.tabla_operadores.selectRow(ids.index(elegido_antes) if elegido_antes in ids else 0)
        self.tabla_operadores.blockSignals(False)
        self._mostrar_ventas_del_elegido()

    def _usuario_elegido(self):
        filas = self.tabla_operadores.selectionModel().selectedRows()
        if not filas or filas[0].row() >= len(self._operadores):
            return None
        return self._operadores[filas[0].row()]["usuario_id"]

    @manejar_errores
    def _mostrar_ventas_del_elegido(self):
        self.tabla_ventas.setRowCount(0)
        usuario_id = self._usuario_elegido()
        if usuario_id is None:
            self.etiqueta_detalle.setText("No hay ventas en esas fechas.")
            return

        operador = next(o for o in self._operadores if o["usuario_id"] == usuario_id)
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        ventas = reportes_repo.ventas_de_operador(usuario_id, desde, hasta)
        self.etiqueta_detalle.setText(
            f"Ventas de {operador['nombre']} del {self.fecha_desde.date().toString('dd/MM/yyyy')} "
            f"al {self.fecha_hasta.date().toString('dd/MM/yyyy')} ({len(ventas)})"
        )

        for venta in ventas:
            momento = datetime.fromisoformat(venta["fecha"])
            anulada = venta["estado"] == dominio.VENTA_ANULADA
            color = _COLOR_ANULADA if anulada else None
            valores = [
                formato_fecha_hora(venta["fecha"]),
                etiqueta_turno(dia_en_que_empezo_el_turno(momento), venta["turno"]),
                dominio.NOMBRE_ORIGEN_VENTA.get(venta["origen"], venta["origen"]),
                venta["concepto"] or "—",
                formato_pesos(venta["efectivo"]),
                formato_pesos(venta["digital"]),
                formato_pesos(venta["total"]),
                "ANULADA" if anulada else "Confirmada",
            ]
            fila = self.tabla_ventas.rowCount()
            self.tabla_ventas.insertRow(fila)
            for columna, valor in enumerate(valores):
                celda = _celda(valor, derecha=columna in _COLUMNAS_PLATA_VENTAS, color=color)
                if columna == 3 and valor != "—":
                    celda.setToolTip(valor)  # un ticket largo se lee entero al pasar el mouse
                self.tabla_ventas.setItem(fila, columna, celda)
