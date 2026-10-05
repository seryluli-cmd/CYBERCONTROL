"""
ventas_window.py
==================
Pantalla de Ventas (facturación): la que más van a usar las empleadas,
todo el día. Se escanea (o busca) cada producto, se arma el carrito, y
al cobrar se abre el cuadro de pago que permite combinar Efectivo y
Digital hasta cubrir el total.

Reglas de permisos, tal como se definieron:
- Cualquier usuario puede borrar un renglón del carrito MIENTRAS la
  venta no esté confirmada (todo lo que se ve acá es "en memoria": no
  se graba nada hasta apretar Aceptar y completar el pago).
- Una vez que la venta se confirma, ya no se puede tocar desde acá.
  Si hay un error, un Admin la anula desde "Consulta de Ventas"
  (ver consulta_ventas_window.py) — eso repone el stock automáticamente.
- Solo el rol ADMIN puede modificar el precio de un renglón en el
  momento de facturar (doble clic en la columna "$ Unit."). Una
  EMPLEADA nunca puede tocar precios.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QHeaderView, QInputDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence
from datetime import datetime

import dominio
from repositories import articulos_repo, ventas_repo
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_info, confirmar, manejar_errores,
    aplicar_clase,
    sin_boton_por_defecto,
)
from ui.buscar_articulo import DialogoBuscarArticulo
from ui.dialogo_pago import DialogoPago


class VentasWindow(QDialog):
    """El carrito vive solo en `self.carrito` (memoria) hasta que se cobra."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self.carrito = []  # cada línea: {codigo, descripcion, cantidad, precio_unitario}
        self._cantidad_pendiente = 1  # usado por el atajo "*" (cambiar cantidad antes de escanear)
        self.setWindowTitle("Venta de Mercadería")
        self.resize(780, 520)
        self._armar_interfaz()

    def _armar_interfaz(self):
        encabezado = QHBoxLayout()
        etiqueta_usuario = QLabel(f"Usuario: {self.usuario['nombre']}")
        etiqueta_fecha = QLabel(f"Fecha: {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        encabezado.addWidget(QLabel("<b>Venta de Mercadería</b>"))
        encabezado.addStretch()
        encabezado.addWidget(etiqueta_usuario)
        encabezado.addWidget(etiqueta_fecha)

        self.campo_codigo = QLineEdit()
        self.campo_codigo.setPlaceholderText("Escaneá el código de barras y apretá Enter...")
        self.campo_codigo.returnPressed.connect(self._escanear)

        self.etiqueta_aviso_stock = QLabel("")
        self.etiqueta_aviso_stock.setStyleSheet("color: #A6323C; font-weight: bold;")

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Cantidad", "Código", "Descripción", "$ Unit.", "$ Total"])
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)
        self.tabla.cellDoubleClicked.connect(self._al_hacer_doble_clic)

        boton_f5 = QPushButton("F5 Cód.")
        boton_f5.clicked.connect(lambda: self._buscar_articulo("codigo"))
        boton_f6 = QPushButton("F6 Descrip.")
        boton_f6.clicked.connect(lambda: self._buscar_articulo("descripcion"))
        boton_f7 = QPushButton("F7 Marca")
        boton_f7.clicked.connect(lambda: self._buscar_articulo("marca"))
        boton_cantidad = QPushButton("* Cant.")
        boton_cantidad.setToolTip("Cargar la cantidad antes de escanear (ej: 3 personas piden lo mismo)")
        boton_cantidad.clicked.connect(self._cambiar_cantidad_pendiente)
        boton_borrar = QPushButton("Supr")
        boton_borrar.clicked.connect(self._borrar_linea)

        QShortcut(QKeySequence("F5"), self, activated=lambda: self._buscar_articulo("codigo"))
        QShortcut(QKeySequence("F6"), self, activated=lambda: self._buscar_articulo("descripcion"))
        QShortcut(QKeySequence("F7"), self, activated=lambda: self._buscar_articulo("marca"))
        QShortcut(QKeySequence("Delete"), self, activated=self._borrar_linea)

        fila_atajos = QHBoxLayout()
        fila_atajos.addWidget(boton_f5)
        fila_atajos.addWidget(boton_f6)
        fila_atajos.addWidget(boton_f7)
        fila_atajos.addWidget(boton_cantidad)
        fila_atajos.addWidget(boton_borrar)
        fila_atajos.addStretch()

        self.etiqueta_total = QLabel("TOTAL: $ 0,00")
        self.etiqueta_total.setStyleSheet("font-size: 22px; font-weight: 700; color: #2F6FED;")
        self.etiqueta_total.setAlignment(Qt.AlignRight)

        self.boton_aceptar = QPushButton("Aceptar / Cobrar")
        aplicar_clase(self.boton_aceptar, "primario")
        self.boton_aceptar.clicked.connect(self._ir_a_cobrar)
        boton_cancelar = QPushButton("Cancelar Venta")
        aplicar_clase(boton_cancelar, "peligro")
        boton_cancelar.clicked.connect(self._cancelar_venta)

        pie = QHBoxLayout()
        pie.addWidget(boton_cancelar)
        pie.addStretch()
        pie.addWidget(self.boton_aceptar)

        layout = QVBoxLayout()
        layout.addLayout(encabezado)
        layout.addWidget(QLabel("Código:"))
        layout.addWidget(self.campo_codigo)
        layout.addWidget(self.etiqueta_aviso_stock)
        layout.addLayout(fila_atajos)
        layout.addWidget(self.tabla)
        layout.addWidget(self.etiqueta_total)
        layout.addLayout(pie)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        self.campo_codigo.setFocus()

    # -----------------------------------------------------------------
    # Escaneo / búsqueda de artículos
    # -----------------------------------------------------------------

    def _buscar_articulo(self, modo):
        dialogo = DialogoBuscarArticulo(self, modo)
        if dialogo.exec() and dialogo.codigo_elegido:
            self._agregar_al_carrito(dialogo.codigo_elegido)

    def _escanear(self):
        codigo = self.campo_codigo.text().strip()
        self.campo_codigo.clear()
        if codigo:
            self._agregar_al_carrito(codigo)
        elif self.carrito:
            # Enter con el campo de código vacío, habiendo ya algo
            # cargado en el carrito: se interpreta como "ya terminé de
            # escanear". El foco pasa a Aceptar / Cobrar y se abre
            # directo la pantalla de pago, sin tener que tocar el mouse.
            self.boton_aceptar.setFocus()
            self._ir_a_cobrar()

    def _cambiar_cantidad_pendiente(self):
        cantidad, aceptado = QInputDialog.getInt(
            self, "Cambiar Cantidad",
            "Cantidad a cargar en el próximo producto escaneado:",
            self._cantidad_pendiente, 1, 999
        )
        if aceptado:
            self._cantidad_pendiente = cantidad
            self.campo_codigo.setFocus()

    @manejar_errores
    def _agregar_al_carrito(self, codigo):
        articulo = articulos_repo.buscar_por_codigo(codigo)
        if articulo is None:
            mostrar_error(self, "Artículo no encontrado", f"No hay ningún artículo con el código {codigo}.")
            self._cantidad_pendiente = 1
            return

        cantidad = self._cantidad_pendiente
        self._cantidad_pendiente = 1  # se resetea después de usarse una vez

        # Si el artículo ya está en el carrito, se suma la cantidad en
        # vez de agregar un renglón duplicado (así se puede escanear el
        # mismo producto varias veces seguidas).
        linea_existente = next((l for l in self.carrito if l["codigo"] == codigo), None)
        if linea_existente:
            linea_existente["cantidad"] += cantidad
        else:
            self.carrito.append({
                "codigo": codigo,
                "descripcion": articulo["descripcion"],
                "cantidad": cantidad,
                "precio_unitario": articulo["precio_venta"],
            })

        self._verificar_stock_minimo(articulo, codigo)
        self._refrescar_tabla()
        self.campo_codigo.setFocus()

    def _verificar_stock_minimo(self, articulo, codigo):
        cantidad_en_carrito = sum(l["cantidad"] for l in self.carrito if l["codigo"] == codigo)
        stock_proyectado = articulo["stock"] - cantidad_en_carrito
        if stock_proyectado < articulo["stock_minimo"]:
            self.etiqueta_aviso_stock.setText(
                f"{articulo['descripcion']} debajo de Stock Mín. Actualmente hay {stock_proyectado}"
            )
        else:
            self.etiqueta_aviso_stock.setText("")

    # -----------------------------------------------------------------
    # Edición del carrito (mientras la venta no está confirmada)
    # -----------------------------------------------------------------

    def _al_hacer_doble_clic(self, fila, columna):
        if columna == 0:  # Cantidad: cualquiera puede corregirla antes de cobrar
            self._editar_cantidad(fila)
        elif columna == 3 and self.es_admin:  # $ Unit.: precio, solo Admin
            self._editar_precio(fila)

    def _editar_cantidad(self, fila):
        linea = self.carrito[fila]
        nueva_cantidad, aceptado = QInputDialog.getInt(
            self, "Cantidad", f"{linea['descripcion']}\nNueva cantidad:", linea["cantidad"], 1, 999
        )
        if aceptado:
            linea["cantidad"] = nueva_cantidad
            self._refrescar_tabla()

    def _editar_precio(self, fila):
        linea = self.carrito[fila]
        nuevo_precio, aceptado = QInputDialog.getDouble(
            self, "Modificar Precio", f"{linea['descripcion']}\nNuevo precio unitario:",
            linea["precio_unitario"], 0, 99_999_999, 2
        )
        if aceptado:
            linea["precio_unitario"] = nuevo_precio
            self._refrescar_tabla()

    def _borrar_linea(self):
        fila = self.tabla.currentRow()
        if fila >= 0:
            del self.carrito[fila]
            self._refrescar_tabla()

    def _refrescar_tabla(self):
        self.tabla.setRowCount(0)
        total = 0.0
        for linea in self.carrito:
            subtotal = ventas_repo.subtotal_linea(linea)
            total += subtotal
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(linea["cantidad"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(linea["codigo"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(linea["descripcion"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(linea["precio_unitario"])))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(subtotal)))
        self.etiqueta_total.setText(f"TOTAL: {formato_pesos(total)}")

    def _total_carrito(self):
        return ventas_repo.total_carrito(self.carrito)

    # -----------------------------------------------------------------
    # Cobro
    # -----------------------------------------------------------------

    @manejar_errores
    def _ir_a_cobrar(self):
        if not self.carrito:
            mostrar_error(self, "Venta vacía", "Todavía no escaneaste ningún producto.")
            return

        total = self._total_carrito()
        dialogo = DialogoPago(self, total)
        if dialogo.exec():
            # El carrito ya tiene exactamente los campos que espera el repo
            # (código, descripción, cantidad y precio); el subtotal lo
            # calcula `confirmar_venta` solo, así que no hay que armarle
            # una copia con la cuenta hecha desde acá.
            numero_factura = ventas_repo.confirmar_venta(self.usuario["id"], self.carrito, dialogo.pagos)

            mensaje = f"Venta Nº {numero_factura} cobrada correctamente."
            if dialogo.vuelto > 0:
                mensaje += f"\nVuelto a entregar: {formato_pesos(dialogo.vuelto)}"
            mostrar_info(self, "Venta confirmada", mensaje)

            self.carrito = []
            self.etiqueta_aviso_stock.setText("")
            self._refrescar_tabla()
            self.campo_codigo.setFocus()

    def _cancelar_venta(self):
        """
        Cancela la venta en curso (pidiendo confirmación si ya hay algo
        cargado) y cierra la pantalla, volviendo a la ventana principal.
        """
        if self.carrito and not confirmar(self, "Cancelar venta",
                                            "¿Cancelar esta venta y volver al menú? "
                                            "Se va a vaciar el carrito actual."):
            return
        self.carrito = []
        self._refrescar_tabla()
        self.reject()
