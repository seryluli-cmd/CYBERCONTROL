"""
reportes_detalle_dia.py
========================
El detalle de lo vendido en un día, abajo de los turnos de Reportes > Resumen
del Día (pedido del dueño, 2026-10-18): venta por venta (hora, turno, operador
y qué se vendió, con cantidades), cuánto se vendió de cada cosa y cuánto vendió
cada operador. Muestra el día entero o el turno que se toque arriba.

Los datos los arma repositories/detalle_dia_repo.py (con los mismos turnos que
las filas de arriba); esta pantalla solo los muestra.
"""

from datetime import datetime

from PySide6.QtWidgets import QLabel, QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ui.utils import crear_tabla, formato_pesos

_COLOR_ANULADA = QColor("#C62828")
_COLOR_GRIS = QColor("#7A869A")


def _texto_hora(venta, dia) -> str:
    """"14:35", o "01:20 del 19/10" si fue pasada la medianoche (la Noche
    sigue siendo de este día del local)."""
    momento = datetime.fromisoformat(venta["fecha"])
    if momento.date() == dia:
        return momento.strftime("%H:%M")
    return f"{momento.strftime('%H:%M')} del {momento.strftime('%d/%m')}"


def _texto_operador(venta) -> str:
    """El operador a cuyo nombre quedó la venta y, si la cobró otra persona (el
    Administrador con la caja de ella abierta), quién la cargó."""
    if venta["cargada_por"] and venta["cargada_por"] != venta["operador"]:
        return f"{venta['operador']} (cargó {venta['cargada_por']})"
    return venta["operador"]


def _texto_estado(venta) -> str:
    if venta["anulada_despues_del_cierre"]:
        return "ANULADA después del cierre"
    return "ANULADA" if venta["anulada"] else ""


class PanelDetalleDelDia(QWidget):
    """Tres pestañas (venta por venta, lo vendido, por operador) sobre el detalle
    de detalle_dia_repo.detalle_del_dia, del día entero o de un turno."""

    _COLUMNAS_VENTAS = ["Nº", "Hora", "Turno", "Operador", "Rubro", "Qué se vendió",
                        "Efectivo", "Digital", "Total", "Estado"]
    _COLUMNAS_PRODUCTOS = ["Rubro", "Producto", "Cantidad", "Importe"]
    _COLUMNAS_OPERADORES = ["Operador", "Ventas", "Anuladas", "Efectivo", "Digital", "Total"]

    def __init__(self):
        super().__init__()
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.titulo.setWordWrap(True)

        self.tabla_ventas = crear_tabla(self._COLUMNAS_VENTAS, estirar=5)
        self.tabla_productos = crear_tabla(self._COLUMNAS_PRODUCTOS, estirar=1)
        self.tabla_operadores = crear_tabla(self._COLUMNAS_OPERADORES, estirar=0)
        self.pestañas = QTabWidget()
        self.pestañas.addTab(self.tabla_ventas, "Venta por venta")
        self.pestañas.addTab(self.tabla_productos, "Lo vendido (cantidades)")
        self.pestañas.addTab(self.tabla_operadores, "Por operador")

        nota = QLabel(
            "Tocá un turno de arriba para ver solo ese turno (o TOTAL DEL DÍA para ver todo). Las ventas "
            "anuladas se ven en rojo y no suman; \"anulada después del cierre\": el sobre de ese turno "
            "se armó con ella adentro."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.titulo)
        layout.addWidget(self.pestañas, 1)
        layout.addWidget(nota)
        self.setLayout(layout)

    def mostrar(self, detalle, turno=None):
        """Muestra el detalle del día entero (`turno` None) o de un turno (uno de
        dominio.TURNOS; si no tuvo ventas, las tablas quedan vacías)."""
        if turno is None:
            parte = detalle
            nombre = "Todo el día"
        else:
            parte = next((t for t in detalle["turnos"] if t["turno"] == turno), None)
            nombre = parte["etiqueta"] if parte else "Este turno"
        if parte is None or not parte["ventas"]:
            self.titulo.setText(f"{nombre}: sin ventas.")
            for tabla in (self.tabla_ventas, self.tabla_productos, self.tabla_operadores):
                tabla.setRowCount(0)
            return

        totales = parte["totales"]
        anuladas = f" ({totales['anuladas']} anulada{'s' if totales['anuladas'] != 1 else ''})" if totales["anuladas"] else ""
        texto = (
            f"{nombre}: {totales['ventas']} venta{'s' if totales['ventas'] != 1 else ''}{anuladas} · "
            f"Efectivo {formato_pesos(totales['efectivo'])} · Digital {formato_pesos(totales['digital'])} · "
            f"Total {formato_pesos(totales['total'])}"
        )
        # Lo que explica que la fila del turno, arriba, diga más: el cierre guardó
        # una foto con esas ventas adentro.
        foto = sum(venta["total"] for venta in parte["ventas"] if venta["anulada_despues_del_cierre"])
        if foto:
            texto += f"  (el cierre, arriba, cuenta además {formato_pesos(foto)} anulados después de cerrar)"
        self.titulo.setText(texto)
        self._llenar_ventas(parte["ventas"], detalle["fecha"])
        self._llenar_productos(parte["por_producto"])
        self._llenar_operadores(parte["por_operador"])

    @staticmethod
    def _poner(tabla, fila, valores, derecha_desde, color=None, negrita=False):
        tabla.insertRow(fila)
        for columna, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            if derecha_desde is not None and columna >= derecha_desde:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if color is not None:
                item.setForeground(color)
            if negrita:
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
            tabla.setItem(fila, columna, item)

    def _llenar_ventas(self, ventas, dia):
        tabla = self.tabla_ventas
        tabla.setRowCount(0)
        for fila, venta in enumerate(ventas):
            valores = [
                str(venta["id"]), _texto_hora(venta, dia), venta["etiqueta_turno"], _texto_operador(venta),
                venta["rubro"], venta["detalle"], formato_pesos(venta["efectivo"]),
                formato_pesos(venta["digital"]), formato_pesos(venta["total"]), _texto_estado(venta),
            ]
            self._poner(tabla, fila, valores, None, color=_COLOR_ANULADA if venta["anulada"] else None)
            for columna in (6, 7, 8):
                tabla.item(fila, columna).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            tabla.item(fila, 5).setToolTip(venta["detalle"])
        tabla.resizeColumnsToContents()

    def _llenar_productos(self, productos):
        tabla = self.tabla_productos
        tabla.setRowCount(0)
        for fila, producto in enumerate(productos):
            cantidad = producto["cantidad"]
            self._poner(tabla, fila, [
                producto["rubro"], producto["producto"],
                str(int(cantidad)) if float(cantidad).is_integer() else str(cantidad),
                formato_pesos(producto["importe"]),
            ], 2)
        self._poner(tabla, len(productos), [
            "TOTAL", "", "", formato_pesos(sum(producto["importe"] for producto in productos)),
        ], 2, negrita=True)
        tabla.resizeColumnsToContents()

    def _llenar_operadores(self, operadores):
        tabla = self.tabla_operadores
        tabla.setRowCount(0)
        for fila, operador in enumerate(operadores):
            self._poner(tabla, fila, [
                operador["operador"], str(operador["ventas"]), str(operador["anuladas"]) if operador["anuladas"] else "",
                formato_pesos(operador["efectivo"]), formato_pesos(operador["digital"]),
                formato_pesos(operador["total"]),
            ], 1, color=_COLOR_GRIS if not operador["ventas"] else None)
        tabla.resizeColumnsToContents()
