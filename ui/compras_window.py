"""
compras_window.py
===================
Ingreso de Mercadería (Compras). La usa el Admin o una Empleada con
`permiso_compras`. Es la única pantalla del sistema que puede sumar stock:
se escanea (o se tipea) el código de cada producto que llegó, se indica la
cantidad, y al Aceptar se guarda todo junto y se actualiza el stock de
cada artículo.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QPushButton, QLineEdit, QLabel,
    QInputDialog,
)
from PySide6.QtGui import QShortcut, QKeySequence
from datetime import datetime

from repositories import articulos_repo, compras_repo
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_info, manejar_errores, aplicar_clase,
    sin_boton_por_defecto, crear_tabla,
)
from ui.buscar_articulo import DialogoBuscarArticulo


class ComprasWindow(QDialog):
    """Arma una compra renglón por renglón en memoria; recién `registrar_compra`
    (al Aceptar) graba algo y mueve el stock."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.lineas = []  # cada línea: {codigo, descripcion, cantidad, costo_unitario, stock_antes, stock_despues}
        self.setWindowTitle("Ingreso de Mercadería")
        self.resize(750, 450)
        self._armar_interfaz()

    def _armar_interfaz(self):
        encabezado = QHBoxLayout()
        etiqueta_numero = QLabel(f"Compra Nº: {compras_repo.proximo_numero_compra()}")
        etiqueta_numero.setStyleSheet("font-weight: bold;")
        etiqueta_fecha = QLabel(f"Fecha: {datetime.now().strftime('%d/%m/%Y')}")
        encabezado.addWidget(etiqueta_numero)
        encabezado.addStretch()
        encabezado.addWidget(etiqueta_fecha)

        self.campo_codigo = QLineEdit()
        self.campo_codigo.setPlaceholderText("Escaneá o tipeá el código de barras y apretá Enter...")
        self.campo_codigo.returnPressed.connect(self._escanear)

        self.tabla = crear_tabla(
            ["Cant.", "Código", "Descripción", "Costo", "Stock Antes", "Stock Actual"],
            estirar=2,
        )

        boton_f5 = QPushButton("F5 Cód.")
        boton_f5.clicked.connect(lambda: self._buscar_articulo("codigo"))
        boton_f6 = QPushButton("F6 Descrip.")
        boton_f6.clicked.connect(lambda: self._buscar_articulo("descripcion"))
        boton_f7 = QPushButton("F7 Marca")
        boton_f7.clicked.connect(lambda: self._buscar_articulo("marca"))
        boton_borrar_linea = QPushButton("Supr (borrar renglón)")
        boton_borrar_linea.clicked.connect(self._borrar_linea)

        # Atajos de teclado (los mismos que en Ventas).
        QShortcut(QKeySequence("F5"), self, activated=lambda: self._buscar_articulo("codigo"))
        QShortcut(QKeySequence("F6"), self, activated=lambda: self._buscar_articulo("descripcion"))
        QShortcut(QKeySequence("F7"), self, activated=lambda: self._buscar_articulo("marca"))
        QShortcut(QKeySequence("Delete"), self, activated=self._borrar_linea)

        boton_aceptar = QPushButton("Aceptar")
        aplicar_clase(boton_aceptar, "primario")
        boton_aceptar.clicked.connect(self._confirmar_compra)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)

        botones = QHBoxLayout()
        botones.addWidget(boton_f5)
        botones.addWidget(boton_f6)
        botones.addWidget(boton_f7)
        botones.addWidget(boton_borrar_linea)
        botones.addStretch()
        botones.addWidget(boton_aceptar)
        botones.addWidget(boton_salir)

        layout = QVBoxLayout()
        layout.addLayout(encabezado)
        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.campo_codigo)
        layout.addWidget(self.tabla)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        self.campo_codigo.setFocus()

    def _buscar_articulo(self, modo):
        dialogo = DialogoBuscarArticulo(self, modo)
        if dialogo.exec() and dialogo.codigo_elegido:
            self._procesar_codigo(dialogo.codigo_elegido)

    def _escanear(self):
        codigo = self.campo_codigo.text().strip()
        self.campo_codigo.clear()
        if not codigo:
            return
        self._procesar_codigo(codigo)

    @manejar_errores
    def _procesar_codigo(self, codigo):
        articulo = articulos_repo.buscar_por_codigo(codigo)
        if articulo is None:
            mostrar_error(self, "Artículo no encontrado",
                           f"No hay ningún artículo con el código {codigo}.\n"
                           "Cargalo primero en Artículos.")
            return

        cantidad, aceptado = QInputDialog.getInt(
            self, "Ingrese Cantidad", f"{articulo['descripcion']}\nCantidad:", 1, 1, 999_999
        )
        if not aceptado:
            return

        costo, aceptado = QInputDialog.getDouble(
            self, "Costo", f"Costo unitario de {articulo['descripcion']}:",
            articulo["precio_compra"], 0, 99_999_999, 2
        )
        if not aceptado:
            return

        stock_antes = articulo["stock"] + sum(
            l["cantidad"] for l in self.lineas if l["codigo"] == codigo
        )
        stock_despues = stock_antes + cantidad

        self.lineas.append({
            "codigo": codigo,
            "descripcion": articulo["descripcion"],
            "cantidad": cantidad,
            "costo_unitario": costo,
            "stock_antes": stock_antes,
            "stock_despues": stock_despues,
        })
        self._refrescar_tabla()

    def _refrescar_tabla(self):
        self.tabla.setRowCount(0)
        for linea in self.lineas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(linea["cantidad"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(linea["codigo"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(linea["descripcion"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(linea["costo_unitario"])))
            self.tabla.setItem(fila, 4, QTableWidgetItem(str(linea["stock_antes"])))
            self.tabla.setItem(fila, 5, QTableWidgetItem(str(linea["stock_despues"])))

    def _borrar_linea(self):
        fila = self.tabla.currentRow()
        if fila >= 0:
            del self.lineas[fila]
            self._refrescar_tabla()

    @manejar_errores
    def _confirmar_compra(self):
        if not self.lineas:
            mostrar_error(self, "Compra vacía", "Todavía no cargaste ningún producto.")
            return
        numero = compras_repo.registrar_compra(self.usuario["id"], self.lineas)
        mostrar_info(self, "Compra registrada", f"Se guardó la compra Nº {numero}.")
        self.lineas = []
        self._refrescar_tabla()
        self.close()
