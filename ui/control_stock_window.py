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
from PySide6.QtWidgets import QDialog, QHBoxLayout, QPushButton, QTableWidgetItem, QVBoxLayout

import dominio
from repositories import articulos_repo
from ui import imprimir
from ui.piezas_ventana import agregar_indicador, cabecera_oscura, panel_de_tabla, pie_de_ventana, poner_indicador, tecla
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
    """La lista para contar el estante, lista para imprimir.

    Con la maqueta B que eligió el dueño el 2026-10-30 (ui/piezas_ventana.py), como
    Artículos: la cabecera oscura con cuántos artículos y unidades hay que contar,
    las teclas arriba, la grilla en su panel y la ayuda abajo."""

    def __init__(self, usuario_id: int, parent=None):
        super().__init__(parent)
        # Si no es Admin, el repo no deja y la ventana no llega a abrirse.
        self._articulos = articulos_repo.listar_para_control_de_stock(usuario_id)
        self.setWindowTitle(TITULO)
        self.resize(820, 720)
        self._armar_interfaz()

    def _armar_interfaz(self):
        # La línea de la cabecera dice cuántos son y que los de 0 o negativo no
        # salen: es la misma frase que encabeza la hoja impresa.
        cabecera = cabecera_oscura("📦", TITULO, _subtitulo(len(self._articulos)))
        self.etiqueta = cabecera.detalle
        # Para la supervisora: cuántos renglones tiene la hoja y cuántas unidades
        # tendría que encontrar en total. Salen de la lista que ya se muestra.
        poner_indicador(agregar_indicador(cabecera, "Artículos"), str(len(self._articulos)))
        poner_indicador(agregar_indicador(cabecera, "Unidades"),
                        str(sum(articulo["stock"] for articulo in self._articulos)))

        self.boton_imprimir = tecla("🖨  IMPRIMIR", self._imprimir, "teclaAzul")
        self.boton_imprimir.setToolTip("Abre la vista previa para imprimir la lista (o guardarla en PDF).")
        self.boton_imprimir.setEnabled(bool(self._articulos))
        barra_botones = QHBoxLayout()
        barra_botones.setSpacing(8)
        barra_botones.addWidget(self.boton_imprimir)
        barra_botones.addStretch()
        barra_botones.addWidget(tecla("CERRAR", self.close))

        self.tabla = crear_tabla(COLUMNAS, estirar=0, por_filas=True)
        self.tabla.setRowCount(len(self._articulos))
        for fila, articulo in enumerate(self._articulos):
            self.tabla.setItem(fila, 0, QTableWidgetItem(articulo["descripcion"]))
            unidades = QTableWidgetItem(str(articulo["stock"]))
            unidades.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla.setItem(fila, COLUMNA_UNIDADES, unidades)
        # Ancha como para el título en mayúscula de la hoja de estilos, con aire, y el
        # título contra la derecha, encima de los números.
        self.tabla.setColumnWidth(COLUMNA_UNIDADES, 140)
        self.tabla.horizontalHeaderItem(COLUMNA_UNIDADES).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(barra_botones)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        layout.addWidget(pie_de_ventana(
            "La hoja impresa trae la columna \"Contado\" para anotar a mano  ·  "
            "Un stock mal contado se corrige con ORDENAR Stock, en Artículos"))
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
