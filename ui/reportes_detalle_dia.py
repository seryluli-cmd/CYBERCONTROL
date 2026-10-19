"""
reportes_detalle_dia.py
========================
El detalle de lo vendido en un día, abajo de los turnos de Reportes > Resumen
del Día (pedido del dueño, 2026-10-18): renglón por renglón tal cual se cobró
(hora, turno, operador, código, descripción, cantidad y total; se imprime con
"Imprimir", como la planilla de su programa anterior), venta por venta (con el
medio de pago), cuánto se vendió de cada cosa y cuánto vendió cada operador.
Muestra el día entero o el turno que se toque arriba.

Los datos los arma repositories/detalle_dia_repo.py (con los mismos turnos que
las filas de arriba); esta pantalla solo los muestra.
"""

from datetime import datetime

from PySide6.QtWidgets import QHBoxLayout, QLabel, QPushButton, QTabWidget, QTableWidgetItem, QVBoxLayout, QWidget
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor

from ui import imprimir
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


def _texto_cantidad(cantidad) -> str:
    return str(int(cantidad)) if float(cantidad).is_integer() else str(cantidad)


# Las columnas del listado renglón por renglón: las mismas en pantalla y en papel.
_COLUMNAS_RENGLONES = ["Hora", "Turno", "Operador", "Nº venta", "Código", "Descripción", "Cantidad", "Total", "Estado"]
_COLUMNA_DESCRIPCION = 5
_A_LA_DERECHA = (6, 7)


def _renglones(ventas, dia) -> list:
    """Una fila por cada renglón cobrado, en el orden en que se cobró: [(valores,
    anulada)]. Catorce impresiones cobradas juntas son UN renglón de 14; cuatro
    cobradas por separado son cuatro renglones, cada uno con su hora y su
    operador."""
    filas = []
    for venta in ventas:
        for linea in venta["lineas"]:
            filas.append(([
                _texto_hora(venta, dia), venta["etiqueta_turno"], _texto_operador(venta), str(venta["id"]),
                linea["codigo"], linea["descripcion"], _texto_cantidad(linea["cantidad"]),
                formato_pesos(linea["importe"]), _texto_estado(venta),
            ], venta["anulada"]))
    return filas


def _pie_de_renglones(totales) -> list:
    """La fila de totales del listado (sin las anuladas)."""
    return ["TOTAL", "", "", "", "", "", _texto_cantidad(totales["unidades"]), formato_pesos(totales["total"]), ""]


class PanelDetalleDelDia(QWidget):
    """Cuatro pestañas (renglón por renglón, venta por venta, lo vendido, por
    operador) sobre el detalle de detalle_dia_repo.detalle_del_dia, del día
    entero o de un turno, y el botón para imprimir el renglón por renglón."""

    _COLUMNAS_VENTAS = ["Nº", "Hora", "Turno", "Operador", "Rubro", "Qué se vendió",
                        "Efectivo", "Digital", "Total", "Estado"]
    _COLUMNAS_PRODUCTOS = ["Rubro", "Producto", "Cantidad", "Importe"]
    _COLUMNAS_OPERADORES = ["Operador", "Ventas", "Anuladas", "Efectivo", "Digital", "Total"]

    def __init__(self):
        super().__init__()
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.titulo.setWordWrap(True)
        self.boton_imprimir = QPushButton("🖨️  Imprimir")
        self.boton_imprimir.setToolTip("Imprime el renglón por renglón de lo que se ve (o lo guarda en PDF).")
        self.boton_imprimir.clicked.connect(self._imprimir)
        self.boton_imprimir.setEnabled(False)
        # Lo que se está viendo, para imprimirlo: (nombre, día, parte, resumen).
        self._a_la_vista = None

        self.tabla_renglones = crear_tabla(_COLUMNAS_RENGLONES, estirar=_COLUMNA_DESCRIPCION)
        self.tabla_ventas = crear_tabla(self._COLUMNAS_VENTAS, estirar=5)
        self.tabla_productos = crear_tabla(self._COLUMNAS_PRODUCTOS, estirar=1)
        self.tabla_operadores = crear_tabla(self._COLUMNAS_OPERADORES, estirar=0)
        self.pestañas = QTabWidget()
        self.pestañas.addTab(self.tabla_renglones, "Renglón por renglón")
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

        encabezado = QHBoxLayout()
        encabezado.addWidget(self.titulo, 1)
        encabezado.addWidget(self.boton_imprimir)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addLayout(encabezado)
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
            for tabla in (self.tabla_renglones, self.tabla_ventas, self.tabla_productos, self.tabla_operadores):
                tabla.setRowCount(0)
            self._a_la_vista = None
            self.boton_imprimir.setEnabled(False)
            return

        totales = parte["totales"]
        anuladas = f" ({totales['anuladas']} anulada{'s' if totales['anuladas'] != 1 else ''})" if totales["anuladas"] else ""
        resumen = (
            f"{totales['ventas']} venta{'s' if totales['ventas'] != 1 else ''}{anuladas} · "
            f"Efectivo {formato_pesos(totales['efectivo'])} · Digital {formato_pesos(totales['digital'])} · "
            f"Total {formato_pesos(totales['total'])}"
        )
        texto = f"{nombre}: {resumen}"
        # Lo que explica que la fila del turno, arriba, diga más: el cierre guardó
        # una foto con esas ventas adentro.
        foto = sum(venta["total"] for venta in parte["ventas"] if venta["anulada_despues_del_cierre"])
        if foto:
            texto += f"  (el cierre, arriba, cuenta además {formato_pesos(foto)} anulados después de cerrar)"
        self.titulo.setText(texto)
        self._a_la_vista = (nombre, detalle["fecha"], parte, resumen)
        self.boton_imprimir.setEnabled(True)
        self._llenar_renglones(parte, detalle["fecha"])
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

    def _llenar_renglones(self, parte, dia):
        tabla = self.tabla_renglones
        tabla.setRowCount(0)
        filas = _renglones(parte["ventas"], dia)
        for fila, (valores, anulada) in enumerate(filas):
            self._poner(tabla, fila, valores, None, color=_COLOR_ANULADA if anulada else None)
            for columna in _A_LA_DERECHA:
                tabla.item(fila, columna).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self._poner(tabla, len(filas), _pie_de_renglones(parte["totales"]), None, negrita=True)
        for columna in _A_LA_DERECHA:
            tabla.item(len(filas), columna).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        tabla.resizeColumnsToContents()

    def _html_para_imprimir(self, impreso=None) -> str:
        nombre, dia, parte, resumen = self._a_la_vista
        return imprimir.html_del_listado(
            f"Ventas del {dia.strftime('%d/%m/%Y')} · {nombre}", resumen, _COLUMNAS_RENGLONES,
            _renglones(parte["ventas"], dia), _A_LA_DERECHA, _pie_de_renglones(parte["totales"]), impreso,
        )

    def _imprimir(self):
        if self._a_la_vista is None:
            return
        nombre, dia, _, _ = self._a_la_vista
        imprimir.vista_previa(self, self._html_para_imprimir(), f"Ventas del {dia.strftime('%d-%m-%Y')} - {nombre}")

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
            self._poner(tabla, fila, [
                producto["rubro"], producto["producto"], _texto_cantidad(producto["cantidad"]),
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
