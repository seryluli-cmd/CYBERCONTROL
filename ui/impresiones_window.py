"""
impresiones_window.py
=======================
El botón "Impresiones" de la barra de arriba (pedido del dueño, 2026-10-19):
cobrar impresiones sin entrar a Vender ni buscar el artículo. Se escribe
cuántas son, Enter abre la ventana de cobro de siempre (ui.dialogo_pago) y
otro Enter cobra.

Es una venta de kiosko común del artículo de impresiones (ver
repositories/impresiones_repo.py): la pantalla solo junta la cantidad y
muestra la cuenta.
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import QDialog, QLabel, QSpinBox, QVBoxLayout

from repositories import impresiones_repo, ventas_repo
from ui.dialogo_pago import DialogoPago
from ui.utils import (
    encadenar_enter, fila_guardar_cancelar, formato_pesos, manejar_errores, mostrar_info,
    sin_boton_por_defecto,
)


class DialogoImpresiones(QDialog):
    """Cantidad de impresiones, precio por unidad y total; Cobrar abre la
    ventana de cobro. `articulo` es el de impresiones_repo.articulo_impresiones()
    (quien abre la ventana ya comprobó que existe)."""

    def __init__(self, usuario, articulo, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.articulo = articulo
        self.setWindowTitle("Impresiones")
        self.resize(340, 200)
        self._armar_interfaz()
        self._actualizar_total()

    def se_puede_cerrar_sola(self) -> bool:
        """Mientras solo se está eligiendo la cantidad no se pierde nada: el
        cierre forzoso de la caja la puede cerrar (ver
        MainWindow._hay_un_cobro_a_medias). Con la ventana de cobro abierta
        encima, la que se consulta es esa, y esa espera."""
        return True

    def _armar_interfaz(self):
        precio = QLabel(f"{self.articulo['descripcion']} · {formato_pesos(self.articulo['precio_venta'])} cada una")
        precio.setStyleSheet("color: #6B7585;")

        self.spin_cantidad = QSpinBox()
        self.spin_cantidad.setRange(1, impresiones_repo.CANTIDAD_MAXIMA)
        self.spin_cantidad.setValue(1)
        # Sin flechitas, como los importes de la ventana de cobro: se escribe el
        # número (las flechas del teclado igual suben y bajan).
        self.spin_cantidad.setButtonSymbols(QSpinBox.NoButtons)
        self.spin_cantidad.setMinimumHeight(40)
        self.spin_cantidad.setStyleSheet("font-size: 18px; font-weight: bold;")
        self.spin_cantidad.valueChanged.connect(self._actualizar_total)

        self.etiqueta_total = QLabel()
        self.etiqueta_total.setAlignment(Qt.AlignCenter)
        self.etiqueta_total.setStyleSheet("font-size: 20px; font-weight: bold; color: #2F6FED;")

        layout = QVBoxLayout()
        layout.addWidget(precio)
        layout.addWidget(QLabel("¿Cuántas impresiones?"))
        layout.addWidget(self.spin_cantidad)
        layout.addWidget(self.etiqueta_total)
        layout.addStretch()
        layout.addLayout(fila_guardar_cancelar(self, self._cobrar, texto_guardar="Cobrar"))
        self.setLayout(layout)
        encadenar_enter(self.spin_cantidad, accion_final=self._cobrar)
        sin_boton_por_defecto(self)
        self.spin_cantidad.setFocus()

    def showEvent(self, evento):
        super().showEvent(evento)
        # Con el 1 seleccionado, lo que se escribe lo reemplaza (mismo truco que
        # la ventana de cobro: recién después de mostrarse se puede seleccionar).
        QTimer.singleShot(0, self.spin_cantidad.selectAll)

    def _linea(self):
        return {"cantidad": self.spin_cantidad.value(), "precio_unitario": self.articulo["precio_venta"]}

    def _actualizar_total(self):
        self.etiqueta_total.setText(f"TOTAL: {formato_pesos(ventas_repo.subtotal_linea(self._linea()))}")

    @manejar_errores
    def _cobrar(self):
        cantidad = self.spin_cantidad.value()
        total = ventas_repo.subtotal_linea(self._linea())
        dialogo = DialogoPago(self, total)
        if not dialogo.exec():
            return
        numero = impresiones_repo.cobrar_impresiones(
            self.usuario["id"], cantidad, self.articulo["precio_venta"], dialogo.pagos
        )
        mensaje = f"{cantidad} {'impresión' if cantidad == 1 else 'impresiones'}: {formato_pesos(total)}\nVenta Nº {numero}"
        if dialogo.vuelto > 0:
            mensaje += f"\nVuelto a entregar: {formato_pesos(dialogo.vuelto)}"
        mostrar_info(self, "Impresiones cobradas", mensaje)
        self.accept()
