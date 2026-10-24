"""
control_stock_window.py
=========================
CONTROL DE STOCK (pedido del dueño, 2026-10-24): la lista de los artículos que
tienen stock, en orden alfabético y con cuántas unidades hay de cada uno, para
imprimirla y que la supervisora, con la lista en la mano, cuente si el estante
coincide. Los que están en 0 o en negativo no salen.

El botón va debajo del mosaico de Control de PCs, a la derecha de APAGAR (ahí
lo pidió el dueño, aunque el stock es del kiosko). Lo ven todos, pero solo el
Admin lo abre: con otro operador se ve igual y no hace nada al apretarlo, como
Admin Kiosko en la barra de arriba (en gris se vería distinto del resto). El
repo vuelve a exigir Admin (articulos_repo.listar_para_control_de_stock).

Solo muestra: para corregir un stock mal contado está ORDENAR Stock, en
Artículos. La hoja impresa trae además una columna "Contado" vacía, para
anotar a mano lo que hay en el estante.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QVBoxLayout

import dominio
from repositories import articulos_repo
from ui import imprimir
from ui.utils import aplicar_clase, crear_tabla, manejar_errores, sin_boton_por_defecto

TITULO = "Control de Stock"
COLUMNAS = ["Artículo", "Unidades"]
COLUMNA_UNIDADES = 1
# La hoja impresa suma "Contado": una raya en cada renglón para escribir encima.
COLUMNAS_IMPRESAS = COLUMNAS + ["Contado"]
_PARA_ANOTAR = "_" * 14


class BotonControlStock(QPushButton):
    """La tecla "📦 CONTROL DE STOCK" de debajo del mosaico, con el mismo relieve
    que las de al lado."""

    def __init__(self, usuario, parent=None):
        super().__init__("📦  CONTROL DE STOCK", parent)
        self.usuario = usuario
        aplicar_clase(self, "barra")
        if dominio.es_admin(usuario):
            self.clicked.connect(self._abrir)

    @manejar_errores
    def _abrir(self):
        VentanaControlStock(self.usuario["id"], self.window()).exec()


def _subtitulo(cantidad: int) -> str:
    if cantidad == 0:
        return "No hay ningún artículo con stock."
    articulos = "1 artículo" if cantidad == 1 else f"{cantidad} artículos"
    return f"{articulos} con stock, de la A a la Z (los que están en 0 o en negativo no aparecen)."


class VentanaControlStock(QDialog):
    def __init__(self, usuario_id: int, parent=None):
        super().__init__(parent)
        # Si no es Admin, el repo no deja y la ventana no llega a abrirse.
        self._articulos = articulos_repo.listar_para_control_de_stock(usuario_id)
        self.setWindowTitle(TITULO)
        self.resize(620, 720)
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.etiqueta = QLabel(_subtitulo(len(self._articulos)))
        self.etiqueta.setWordWrap(True)

        self.tabla = crear_tabla(COLUMNAS, estirar=0, por_filas=True)
        self.tabla.setRowCount(len(self._articulos))
        for fila, articulo in enumerate(self._articulos):
            self.tabla.setItem(fila, 0, QTableWidgetItem(articulo["descripcion"]))
            unidades = QTableWidgetItem(str(articulo["stock"]))
            unidades.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla.setItem(fila, COLUMNA_UNIDADES, unidades)
        self.tabla.resizeColumnToContents(COLUMNA_UNIDADES)

        self.boton_imprimir = QPushButton("🖨️  Imprimir")
        self.boton_imprimir.setToolTip("Abre la vista previa para imprimir la lista (o guardarla en PDF).")
        aplicar_clase(self.boton_imprimir, "primario")
        self.boton_imprimir.clicked.connect(self._imprimir)
        self.boton_imprimir.setEnabled(bool(self._articulos))
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        fila_abajo = QHBoxLayout()
        fila_abajo.addStretch()
        fila_abajo.addWidget(self.boton_imprimir)
        fila_abajo.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_abajo)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def html_para_imprimir(self, impreso=None) -> str:
        filas = [((articulo["descripcion"], articulo["stock"], _PARA_ANOTAR), False) for articulo in self._articulos]
        return imprimir.html_del_listado(
            TITULO, _subtitulo(len(self._articulos)), COLUMNAS_IMPRESAS, filas,
            a_la_derecha=(COLUMNA_UNIDADES,), impreso=impreso,
        )

    def _imprimir(self):
        imprimir.vista_previa(self, self.html_para_imprimir(), TITULO)
