"""
detalle_venta.py
==================
Lo que comparten Consulta de Ventas y el Detalle de un cierre de turno: una
lista de ventas arriba y, abajo, los artículos de la venta que se elija.
"""

from PySide6.QtWidgets import QDialog, QTableWidget, QTableWidgetItem

from repositories import tramites_repo, ventas_repo
from ui.utils import formato_pesos, manejar_errores, crear_tabla


def crear_tabla_detalle_venta() -> QTableWidget:
    """La tabla (vacía) con los artículos de una venta: código, descripción,
    cantidad y subtotal."""
    return crear_tabla(["Código", "Descripción", "Cantidad", "Subtotal"], estirar=1)


class VentanaConDetalleDeVenta(QDialog):
    """
    Base de las pantallas con una lista de ventas (`self.tabla`, con las
    ventas en `self.ventas`, en el mismo orden) y, abajo, los artículos de la
    venta elegida (`self.tabla_detalle`). Una venta sin artículos de por
    medio (un bono de PC, una carga de saldo de socio) deja esa tabla vacía;
    un trámite deja una sola fila con su nombre.

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
