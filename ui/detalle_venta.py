"""
detalle_venta.py
==================
Lo que comparten Consulta de Ventas y el Detalle de un cierre de turno: una
lista de ventas y, al lado o abajo, los artículos de la venta que se elija.
Las dos con la maqueta B (2026-10-30): cada grilla en su panel_de_tabla y el
estado de la venta en una etiqueta de color.
"""

from PySide6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem

import dominio
from repositories import tramites_repo, ventas_repo
from ui.dibujos_tabla import DelegadoEtiqueta
from ui.utils import formato_pesos, manejar_errores, crear_tabla, mostrar_columna_entera

# Columnas de la tabla de artículos de una venta.
_COLUMNA_CANTIDAD = 2
_COLUMNA_SUBTOTAL = 3


def crear_tabla_detalle_venta() -> QTableWidget:
    """La tabla (vacía) con los artículos de una venta: código, descripción,
    cantidad y subtotal."""
    tabla = crear_tabla(["Código", "Descripción", "Cantidad", "Subtotal"], estirar=1)
    # Con los títulos en negrita y espaciados de la maqueta B, el ancho de fábrica
    # cortaba "Cantidad".
    tabla.setColumnWidth(_COLUMNA_CANTIDAD, 98)
    tabla.setColumnWidth(_COLUMNA_SUBTOTAL, 100)
    return tabla


def etiqueta_de_estado(tabla: QTableWidget, columna: int) -> DelegadoEtiqueta:
    """El estado de cada venta en una etiqueta: CONFIRMADA en verde y ANULADA en
    rosa (rojiza, como el rojo que tenía antes la letra)."""
    delegado = DelegadoEtiqueta(tabla)
    delegado.colores_fijos({dominio.VENTA_CONFIRMADA: "verde", dominio.VENTA_ANULADA: "rosa"})
    tabla.setItemDelegateForColumn(columna, delegado)
    tabla.setColumnWidth(columna, 130)
    return delegado


class VentanaConDetalleDeVenta(QDialog):
    """
    Base de las pantallas con una lista de ventas (`self.tabla`, con las
    ventas en `self.ventas`, en el mismo orden) y los artículos de la venta
    elegida (`self.tabla_detalle`). Una venta sin artículos de por medio (un
    bono de PC, una carga de saldo de socio) deja esa tabla vacía; un trámite
    deja una sola fila con su nombre.

    La subclase arma sus tablas, crea `self.tabla_detalle` con
    `crear_tabla_detalle_venta()` y conecta
    `self.tabla.itemSelectionChanged` a `self._mostrar_detalle`.
    """

    def _venta_seleccionada(self):
        """La venta elegida en `self.tabla`, o None si no hay ninguna."""
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
        lineas = [
            (linea["articulo_codigo"], linea["descripcion"], str(linea["cantidad"]), linea["subtotal"])
            for linea in detalle
        ]
        # Un trámite se cobra sin artículo de por medio (no hay detalle), pero
        # sí hay que poder ver de qué se trató.
        tramite = tramites_repo.tramite_de_venta(venta["id"])
        if tramite is not None:
            lineas.append(("", f"Trámite: {tramite}", "1", venta["total"]))
        for codigo, descripcion, cantidad, subtotal in lineas:
            fila = self.tabla_detalle.rowCount()
            self.tabla_detalle.insertRow(fila)
            self.tabla_detalle.setItem(fila, 0, QTableWidgetItem(codigo))
            self.tabla_detalle.setItem(fila, 1, QTableWidgetItem(descripcion))
            self.tabla_detalle.setItem(fila, 2, QTableWidgetItem(cantidad))
            self.tabla_detalle.setItem(fila, 3, QTableWidgetItem(formato_pesos(subtotal)))
        mostrar_columna_entera(self.tabla_detalle, 0)
