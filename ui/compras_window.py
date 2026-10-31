"""
compras_window.py
===================
Ingreso de Mercadería (Compras). La usa el Admin o una Empleada con
`permiso_compras`. Es la única pantalla del sistema que puede sumar stock:
se escanea (o se tipea) el código de cada producto que llegó, se indica la
cantidad, y al Aceptar se guarda todo junto y se actualiza el stock de
cada artículo.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QInputDialog
from PySide6.QtGui import QShortcut, QKeySequence
from datetime import datetime

from repositories import articulos_repo, compras_repo
from ui.piezas_ventana import (
    agregar_indicador, buscador, cabecera_oscura, panel_de_tabla, pie_de_ventana, poner_indicador, tecla,
)
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_info, manejar_errores, aplicar_clase,
    sin_boton_por_defecto, crear_tabla, mostrar_columna_entera, pedir_pesos,
)
from ui.buscar_articulo import armar_botones_de_busqueda, avisar_codigo_no_encontrado

COLUMNA_CANTIDAD = 0
COLUMNA_CODIGO = 1
COLUMNA_DESCRIPCION = 2
COLUMNA_COSTO = 3
COLUMNA_STOCK_ANTES = 4
COLUMNA_STOCK_ACTUAL = 5


class ComprasWindow(QDialog):
    """Arma una compra renglón por renglón en memoria; recién `registrar_compra`
    (al Aceptar) graba algo y mueve el stock.

    Con la maqueta B que eligió el dueño el 2026-10-30 (ui/piezas_ventana.py), como
    Artículos: la cabecera oscura con el número de la compra y cuánto se lleva
    cargado, las teclas arriba, el campo grande para escanear, la grilla en su
    panel y la ayuda abajo."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.lineas = []  # cada línea: {codigo, descripcion, cantidad, costo_unitario, stock_antes, stock_despues}
        self.setWindowTitle("Ingreso de Mercadería")
        self.resize(1100, 680)
        self._armar_interfaz()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura("🚚", "Ingreso de Mercadería",
                                   "La mercadería que entra al kiosko: al Aceptar se suma al stock")
        poner_indicador(agregar_indicador(cabecera, "Compra Nº"), str(compras_repo.proximo_numero_compra()))
        poner_indicador(agregar_indicador(cabecera, "Fecha"), datetime.now().strftime("%d/%m/%Y"))
        # Lo que se lleva cargado: se actualizan con cada renglón (_refrescar_tabla).
        self.indicador_productos = agregar_indicador(cabecera, "Productos")
        self.indicador_unidades = agregar_indicador(cabecera, "Unidades")

        # F5/F6/F7 los arma buscar_articulo (los mismos de Ventas); acá se ven como
        # las demás teclas y en mayúscula.
        botones_de_busqueda = armar_botones_de_busqueda(self, self._procesar_codigo)
        for boton in botones_de_busqueda:
            aplicar_clase(boton, "teclaBlanca")
            boton.setText(boton.text().upper())
        boton_borrar_linea = tecla("✕  BORRAR RENGLÓN (Supr)", self._borrar_linea, "teclaRoja")

        # Supr borra el renglón elegido, igual que en Ventas.
        QShortcut(QKeySequence("Delete"), self, activated=self._borrar_linea)

        boton_aceptar = tecla("✔  ACEPTAR COMPRA", self._confirmar_compra, "teclaAzul")
        boton_salir = tecla("SALIR", self.close)

        botones = QHBoxLayout()
        botones.setSpacing(8)
        for boton in botones_de_busqueda:
            botones.addWidget(boton)
        botones.addWidget(boton_borrar_linea)
        botones.addStretch()
        botones.addWidget(boton_aceptar)
        botones.addWidget(boton_salir)

        self.campo_codigo = buscador("Escaneá o tipeá el código de barras y apretá Enter...")
        self.campo_codigo.returnPressed.connect(self._escanear)

        self.tabla = crear_tabla(
            ["Cant.", "Código", "Descripción", "Costo", "Stock Antes", "Stock Actual"],
            estirar=COLUMNA_DESCRIPCION,
        )
        # Anchas para que los títulos en mayúscula de la hoja de estilos no se corten.
        for columna, ancho in ((COLUMNA_CANTIDAD, 80), (COLUMNA_CODIGO, 150), (COLUMNA_COSTO, 120),
                               (COLUMNA_STOCK_ANTES, 130), (COLUMNA_STOCK_ACTUAL, 140)):
            self.tabla.setColumnWidth(columna, ancho)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(botones)
        layout.addWidget(self.campo_codigo)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        layout.addWidget(pie_de_ventana(
            "Escaneá cada producto que llegó: pide la cantidad y el costo  ·  Sin código, buscalo con F5, F6 o F7  ·  "
            "Supr borra el renglón elegido  ·  Nada se guarda hasta Aceptar"))
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self._poner_numeros()

        self.campo_codigo.setFocus()

    def _poner_numeros(self):
        poner_indicador(self.indicador_productos, str(len(self.lineas)))
        poner_indicador(self.indicador_unidades, str(sum(linea["cantidad"] for linea in self.lineas)))

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
            avisar_codigo_no_encontrado(self, codigo, "Cargalo primero en Artículos.")
            return

        cantidad, aceptado = QInputDialog.getInt(
            self, "Ingrese Cantidad", f"{articulo['descripcion']}\nCantidad:", 1, 1, 999_999
        )
        if not aceptado:
            return

        costo, aceptado = pedir_pesos(
            self, "Costo", f"Costo unitario de {articulo['descripcion']}:", articulo["precio_compra"]
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
        mostrar_columna_entera(self.tabla, 1)
        self._poner_numeros()

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
