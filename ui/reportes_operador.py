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
from ui.piezas_ventana import pie_de_ventana
from ui.reportes_piezas import (
    como_plata, etiqueta_de_origenes, panel_de_reporte, tarjeta_de_filtros, titulos_en_mayuscula,
)
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, formato_fecha_hora, manejar_errores,
    sin_boton_por_defecto, crear_tabla, rango_de_fechas,
)

_COLOR_ANULADA = QColor("#C62828")

# Columnas de plata de cada tabla: van a la derecha y en negrita (como_plata).
_COLUMNAS_PLATA_OPERADORES = (3, 4, 5)
# Cantidades (ventas y anuladas): a la derecha como la plata, pero sin negrita.
_COLUMNAS_NUMERO_OPERADORES = (1, 2)
_COLUMNAS_PLATA_VENTAS = (4, 5, 6)
_COLUMNA_ORIGEN = 2


def _celda(texto, derecha=False, color=None, plata=False):
    item = QTableWidgetItem(texto)
    if derecha:
        item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    if color is not None:
        item.setForeground(color)
    if plata:
        como_plata(item)
    return item


class PestañaPorOperador(QWidget):
    """Arriba, un resumen por operador; abajo, las ventas del elegido. Con la
    maqueta B (2026-10-30): cada grilla en su panel blanco (panel_de_reporte) y la
    nota abajo como pie_de_ventana."""

    def __init__(self):
        super().__init__()
        self._operadores = []   # filas de reportes_repo.resumen_por_operador
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True, dias_del_local=True)

        self.tabla_operadores = crear_tabla(
            ["Operador", "Ventas", "Anuladas", "Efectivo", "Digital", "Total"],
            estirar=0, por_filas=True, una_sola=True,
        )
        self.tabla_operadores.itemSelectionChanged.connect(self._mostrar_ventas_del_elegido)
        titulos_en_mayuscula(self.tabla_operadores, a_la_derecha=(*_COLUMNAS_NUMERO_OPERADORES, *_COLUMNAS_PLATA_OPERADORES))
        for columna in range(1, self.tabla_operadores.columnCount()):
            self.tabla_operadores.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)

        self.etiqueta_detalle = QLabel()
        self.etiqueta_detalle.setObjectName("tituloDeTablaReporte")

        self.tabla_ventas = crear_tabla(
            ["Fecha y hora", "Turno", "Origen", "Concepto", "Efectivo", "Digital", "Total", "Estado"],
            estirar=3, por_filas=True,
        )
        titulos_en_mayuscula(self.tabla_ventas, a_la_derecha=_COLUMNAS_PLATA_VENTAS)
        # Todas al ancho de su contenido menos "Concepto", que se estira: con el
        # ancho por defecto, "Fecha y hora" cortaba justo la hora.
        for columna in range(self.tabla_ventas.columnCount()):
            if columna != 3:
                self.tabla_ventas.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)
        # El origen en una etiqueta del color de su rubro, como en Consulta de Ventas.
        self.etiqueta_origen = etiqueta_de_origenes(self.tabla_ventas)
        self.tabla_ventas.setItemDelegateForColumn(_COLUMNA_ORIGEN, self.etiqueta_origen)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 12, 0, 0)   # como las demás secciones (ver reportes_window)
        layout.setSpacing(12)
        layout.addWidget(tarjeta_de_filtros(filtros))
        layout.addWidget(panel_de_reporte(self.tabla_operadores), 2)
        layout.addWidget(self.etiqueta_detalle)
        layout.addWidget(panel_de_reporte(self.tabla_ventas), 3)
        layout.addWidget(pie_de_ventana(
            "Cada venta queda a nombre de quien tenía la sesión abierta. Las anuladas se "
            "muestran en rojo y no suman en los totales."
        ))
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
                    fila, columna, _celda(valor, derecha=columna in _COLUMNAS_NUMERO_OPERADORES,
                                         plata=columna in _COLUMNAS_PLATA_OPERADORES)
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
                celda = _celda(valor, color=color, plata=columna in _COLUMNAS_PLATA_VENTAS)
                if columna == 3 and valor != "—":
                    celda.setToolTip(valor)  # un ticket largo se lee entero al pasar el mouse
                self.tabla_ventas.setItem(fila, columna, celda)
