"""
buscar_articulo.py
====================
Cuadro de búsqueda de artículos reutilizable, usado tanto en Ventas como
en Compras. Replica los atajos F5 (buscar por código), F6 (buscar por
descripción) y F7 (buscar por marca) del sistema actual: alguien lo abre
cuando no tiene a mano o no puede leer el código de barras.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLineEdit, QPushButton, QLabel,
    QTableWidget, QTableWidgetItem, QHeaderView
)
from PySide6.QtCore import Qt

from repositories import articulos_repo
from ui.utils import manejar_errores, aplicar_clase, formato_pesos


class DialogoBuscarArticulo(QDialog):
    def __init__(self, parent, modo: str = "descripcion"):
        """
        `modo` define qué campo se busca por defecto: "codigo",
        "descripcion" o "marca" (equivalentes a F5 / F6 / F7).
        """
        super().__init__(parent)
        self.modo = modo
        self.codigo_elegido = None
        titulos = {"codigo": "Buscar por Código (F5)",
                   "descripcion": "Buscar por Descripción (F6)",
                   "marca": "Buscar por Marca (F7)"}
        self.setWindowTitle(titulos.get(modo, "Buscar artículo"))
        self.resize(600, 400)
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.campo_busqueda = QLineEdit()
        self.campo_busqueda.textChanged.connect(self._buscar)
        self.campo_busqueda.returnPressed.connect(self._elegir_seleccion)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Código", "Descripción", "Marca", "Precio Venta"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.doubleClicked.connect(self._elegir_seleccion)

        boton_elegir = QPushButton("Seleccionar")
        aplicar_clase(boton_elegir, "primario")
        boton_elegir.clicked.connect(self._elegir_seleccion)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)

        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_elegir)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Escribí para buscar:"))
        layout.addWidget(self.campo_busqueda)
        layout.addWidget(self.tabla)
        layout.addLayout(botones)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

        self.campo_busqueda.setFocus()
        self._buscar("")

    @manejar_errores
    def _buscar(self, texto):
        if self.modo == "codigo":
            resultados = articulos_repo.listar_articulos(texto)
        elif self.modo == "marca":
            resultados = articulos_repo.buscar_por_marca(texto) if texto else articulos_repo.listar_articulos("")
        else:
            resultados = articulos_repo.buscar_por_descripcion(texto) if texto else articulos_repo.listar_articulos("")

        self.tabla.setRowCount(0)
        for articulo in resultados[:200]:  # tope razonable para no trabar la grilla
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(articulo["codigo"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(articulo["descripcion"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(articulo["marca"] or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(articulo["precio_venta"])))

    def _elegir_seleccion(self):
        fila = self.tabla.currentRow()
        if fila < 0 and self.tabla.rowCount() > 0:
            fila = 0
        if fila < 0:
            return
        self.codigo_elegido = self.tabla.item(fila, 0).text()
        self.accept()
