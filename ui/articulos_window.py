"""
articulos_window.py
=====================
Pantalla de Artículos: la grilla con todos los productos, y el cuadro de
alta/edición. La usa el Admin o una Empleada con `permiso_articulos`.
Importante: acá NUNCA se edita el stock a mano — el stock solo se mueve
desde Compras (ver compras_window.py).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QPushButton, QLineEdit, QLabel,
    QComboBox, QDoubleSpinBox, QSpinBox, QFormLayout, QInputDialog,
)
from PySide6.QtCore import Qt, QDate

from repositories import articulos_repo
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_aviso, confirmar, manejar_errores, aplicar_clase,
    encadenar_enter, armar_filtro_por_fechas, sin_boton_por_defecto, fila_guardar_cancelar,
    crear_tabla,
)


class ArticulosWindow(QDialog):
    """Grilla de artículos con buscador; desde acá se abre el alta/edición,
    los movimientos de stock y la gestión de rubros."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Artículos")
        self.resize(950, 550)
        self._armar_interfaz()
        self._cargar_grilla()

    def _armar_interfaz(self):
        barra_botones = QHBoxLayout()
        self.boton_nuevo = QPushButton("Nuevo")
        self.boton_modificar = QPushButton("Modificar")
        self.boton_borrar = QPushButton("Borrar")
        self.boton_movimientos = QPushButton("Movimientos")
        self.boton_rubros = QPushButton("Gestionar Rubros")
        self.boton_salir = QPushButton("Salir")
        for boton in (self.boton_nuevo, self.boton_modificar, self.boton_borrar,
                      self.boton_movimientos, self.boton_rubros, self.boton_salir):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        aplicar_clase(self.boton_nuevo, "primario")
        aplicar_clase(self.boton_borrar, "peligro")
        self.boton_nuevo.clicked.connect(self._nuevo_articulo)
        self.boton_modificar.clicked.connect(self._modificar_articulo)
        self.boton_borrar.clicked.connect(self._borrar_articulo)
        self.boton_movimientos.clicked.connect(self._ver_movimientos)
        self.boton_rubros.clicked.connect(self._gestionar_rubros)
        self.boton_salir.clicked.connect(self.close)

        self.campo_buscar = QLineEdit()
        self.campo_buscar.setPlaceholderText("Buscar por código o descripción...")
        self.campo_buscar.textChanged.connect(self._cargar_grilla)

        self.tabla = crear_tabla(
            ["Código", "Descripción", "Marca", "Rubro", "Precio Venta",
             "Precio Compra", "Stock", "Stock Mínimo"],
            estirar=1, por_filas=True, una_sola=True,
        )
        # Clickeando el título de una columna se ordena la grilla por ella.
        self.tabla.setSortingEnabled(True)
        self.tabla.doubleClicked.connect(self._modificar_articulo)

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.campo_buscar)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar_grilla(self, _=None):
        # El "_=None" no se usa: absorbe el texto que manda `textChanged`
        # (ver ControlCierresWindow._ver_detalle en caja_window.py, que
        # explica por qué hace falta con @manejar_errores).
        texto = self.campo_buscar.text().strip()
        articulos = articulos_repo.listar_articulos(texto)
        self.tabla.setSortingEnabled(False)
        self.tabla.setRowCount(0)
        for fila_datos in articulos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(fila_datos["codigo"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(fila_datos["descripcion"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(fila_datos["marca"] or ""))
            self.tabla.setItem(fila, 3, QTableWidgetItem(fila_datos["rubro"] or ""))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(fila_datos["precio_venta"])))
            self.tabla.setItem(fila, 5, QTableWidgetItem(formato_pesos(fila_datos["precio_compra"])))

            item_stock = QTableWidgetItem(str(fila_datos["stock"]))
            if fila_datos["stock"] < fila_datos["stock_minimo"]:
                item_stock.setForeground(Qt.red)
            self.tabla.setItem(fila, 6, item_stock)
            self.tabla.setItem(fila, 7, QTableWidgetItem(str(fila_datos["stock_minimo"])))
        self.tabla.setSortingEnabled(True)

    def _codigo_seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_aviso(self, "Nada seleccionado", "Elegí primero un artículo de la lista.")
            return None
        return self.tabla.item(fila, 0).text()

    def _nuevo_articulo(self):
        dialogo = DialogoArticulo(self)
        if dialogo.exec():
            self._cargar_grilla()

    def _modificar_articulo(self):
        codigo = self._codigo_seleccionado()
        if not codigo:
            return
        dialogo = DialogoArticulo(self, codigo)
        if dialogo.exec():
            self._cargar_grilla()

    @manejar_errores
    def _borrar_articulo(self):
        codigo = self._codigo_seleccionado()
        if not codigo:
            return
        if confirmar(self, "Confirmar borrado", f"¿Borrar el artículo {codigo}? Esta acción no se puede deshacer."):
            # Si el artículo ya tiene compras o ventas registradas,
            # articulos_repo.borrar_articulo tira un ValueError con un
            # mensaje claro en vez de dejar pasar el error de SQLite;
            # el decorador @manejar_errores se encarga de mostrarlo.
            articulos_repo.borrar_articulo(codigo)
            self._cargar_grilla()

    def _ver_movimientos(self):
        codigo = self._codigo_seleccionado()
        if not codigo:
            return
        dialogo = DialogoMovimientos(self, codigo)
        dialogo.exec()

    def _gestionar_rubros(self):
        DialogoGestionRubros(self).exec()


class DialogoArticulo(QDialog):
    """Cuadro de alta o edición de un artículo (según si se le pasa un
    código existente o no)."""

    def __init__(self, parent, codigo_existente: str = None):
        super().__init__(parent)
        self.codigo_existente = codigo_existente
        self.setWindowTitle("Modificación de Artículos" if codigo_existente else "Nuevo Artículo")
        self.resize(520, 380)
        self._armar_interfaz()
        if codigo_existente:
            self._cargar_datos(codigo_existente)

    def _armar_interfaz(self):
        self.campo_codigo = QLineEdit()
        if self.codigo_existente:
            self.campo_codigo.setText(self.codigo_existente)
            self.campo_codigo.setReadOnly(True)  # no se cambia el código de un artículo ya creado

        self.campo_descripcion = QLineEdit()

        self.combo_marca = QComboBox()
        self.combo_marca.setEditable(True)
        for marca in articulos_repo.listar_marcas():
            self.combo_marca.addItem(marca["nombre"], marca["id"])

        # A diferencia de Marca, Rubro NO es editable a mano: solo se puede
        # elegir de la lista que administra el Admin (ver "Gestionar
        # Rubros"), para que no queden rubros mal escritos o duplicados
        # por typos ("Bebidas" vs "BEBIDAS" vs "Bebida").
        self.combo_rubro = QComboBox()
        self.combo_rubro.addItem("(Sin rubro)", None)
        for rubro in articulos_repo.listar_rubros():
            self.combo_rubro.addItem(rubro["nombre"], rubro["id"])

        self.spin_precio_venta = QDoubleSpinBox()
        self.spin_precio_venta.setMaximum(99_999_999)
        self.spin_precio_venta.setPrefix("$ ")

        self.spin_precio_compra = QDoubleSpinBox()
        self.spin_precio_compra.setMaximum(99_999_999)
        self.spin_precio_compra.setPrefix("$ ")

        # Calculadora de margen: a veces se pierde la factura de compra y no
        # se sabe el costo real, pero se puede averiguar el precio de venta
        # de ese mismo artículo en otro local — con eso y un % de margen
        # aproximado, se estima el costo (o al revés, con el costo conocido
        # se estima la venta). El % es editable porque el margen no es
        # siempre el mismo para todos los rubros. Es a botón, no en vivo:
        # así no pisa un precio que ya se cargó a mano al tocar el otro campo.
        self.spin_pct_desde_costo = QSpinBox()
        self.spin_pct_desde_costo.setRange(0, 500)
        self.spin_pct_desde_costo.setValue(80)
        self.spin_pct_desde_costo.setSuffix("%")
        boton_calc_venta = QPushButton("Calcular")
        boton_calc_venta.clicked.connect(self._calcular_venta_desde_costo)

        self.spin_pct_desde_venta = QSpinBox()
        self.spin_pct_desde_venta.setRange(0, 500)
        self.spin_pct_desde_venta.setValue(80)
        self.spin_pct_desde_venta.setSuffix("%")
        boton_calc_costo = QPushButton("Calcular")
        boton_calc_costo.clicked.connect(self._calcular_costo_desde_venta)

        self.spin_stock_minimo = QSpinBox()
        self.spin_stock_minimo.setMaximum(999_999)

        self.etiqueta_stock = QLabel("(el stock se carga desde Compras)")
        self.etiqueta_stock.setStyleSheet("color: gray; font-style: italic;")

        # La pistola lectora escribe el código y manda un Enter sola. Ese
        # Enter pasa el foco al siguiente campo, como si se apretara Tab,
        # para seguir cargando el artículo sin tocar el mouse — encadenado
        # por todo el formulario, terminando en Guardar (ver encadenar_enter).
        encadenar_enter(
            self.campo_codigo, self.campo_descripcion, self.combo_marca, self.combo_rubro,
            self.spin_precio_venta, self.spin_precio_compra, self.spin_stock_minimo,
            accion_final=self._guardar,
        )

        fila_precio_venta = QHBoxLayout()
        fila_precio_venta.addWidget(self.spin_precio_venta)
        fila_precio_venta.addWidget(QLabel("→ Costo al"))
        fila_precio_venta.addWidget(self.spin_pct_desde_venta)
        fila_precio_venta.addWidget(boton_calc_costo)

        fila_precio_compra = QHBoxLayout()
        fila_precio_compra.addWidget(self.spin_precio_compra)
        fila_precio_compra.addWidget(QLabel("→ Venta al"))
        fila_precio_compra.addWidget(self.spin_pct_desde_costo)
        fila_precio_compra.addWidget(boton_calc_venta)

        formulario = QFormLayout()
        formulario.addRow("Código (de barras):", self.campo_codigo)
        formulario.addRow("Descripción:", self.campo_descripcion)
        formulario.addRow("Marca:", self.combo_marca)
        formulario.addRow("Rubro:", self.combo_rubro)
        formulario.addRow("Precio Venta:", fila_precio_venta)
        formulario.addRow("Precio Compra (costo):", fila_precio_compra)
        formulario.addRow("Stock Mínimo:", self.spin_stock_minimo)
        formulario.addRow("Stock actual:", self.etiqueta_stock)

        botones = fila_guardar_cancelar(self, self._guardar)

        layout = QVBoxLayout()
        layout.addLayout(formulario)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar_datos(self, codigo):
        articulo = articulos_repo.buscar_por_codigo(codigo)
        if articulo is None:
            return
        self.campo_descripcion.setText(articulo["descripcion"])
        if articulo["marca"]:
            self.combo_marca.setCurrentText(articulo["marca"])
        indice_rubro = self.combo_rubro.findData(articulo["rubro_id"])
        self.combo_rubro.setCurrentIndex(indice_rubro if indice_rubro >= 0 else 0)
        self.spin_precio_venta.setValue(articulo["precio_venta"])
        self.spin_precio_compra.setValue(articulo["precio_compra"])
        self.spin_stock_minimo.setValue(articulo["stock_minimo"])
        self.etiqueta_stock.setText(str(articulo["stock"]))
        self.etiqueta_stock.setStyleSheet("color: red;" if articulo["stock"] < articulo["stock_minimo"] else "")

    def _calcular_venta_desde_costo(self):
        costo = self.spin_precio_compra.value()
        porcentaje = self.spin_pct_desde_costo.value()
        self.spin_precio_venta.setValue(round(costo * (1 + porcentaje / 100), 2))

    def _calcular_costo_desde_venta(self):
        venta = self.spin_precio_venta.value()
        porcentaje = self.spin_pct_desde_venta.value()
        self.spin_precio_compra.setValue(round(venta / (1 + porcentaje / 100), 2))

    def _resolver_marca_id(self):
        texto = self.combo_marca.currentText().strip()
        if not texto:
            return None
        indice = self.combo_marca.findText(texto)
        if indice >= 0:
            return self.combo_marca.itemData(indice)
        return articulos_repo.crear_marca(texto)  # marca nueva, se crea al vuelo

    @manejar_errores
    def _guardar(self):
        codigo = self.campo_codigo.text().strip()
        descripcion = self.campo_descripcion.text().strip()

        if not codigo or not descripcion:
            mostrar_error(self, "Faltan datos", "El código y la descripción son obligatorios.")
            return

        marca_id = self._resolver_marca_id()
        rubro_id = self.combo_rubro.currentData()  # ya viene resuelto: no es editable

        if self.codigo_existente:
            articulos_repo.modificar_articulo(
                codigo, descripcion, marca_id, rubro_id,
                self.spin_precio_venta.value(), self.spin_precio_compra.value(),
                self.spin_stock_minimo.value(),
            )
        else:
            if articulos_repo.buscar_por_codigo(codigo):
                mostrar_error(self, "Código repetido", "Ya existe un artículo con ese código.")
                return
            articulos_repo.crear_articulo(
                codigo, descripcion, marca_id, rubro_id,
                self.spin_precio_venta.value(), self.spin_precio_compra.value(),
                self.spin_stock_minimo.value(),
            )
        self.accept()


class DialogoMovimientos(QDialog):
    """Historial de Movimientos de stock de un artículo (compras y
    ventas), filtrable por rango de fechas."""

    def __init__(self, parent, codigo: str):
        super().__init__(parent)
        self.codigo = codigo
        self.setWindowTitle(f"Histórico de Movimientos de {codigo}")
        self.resize(500, 450)
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, QDate.currentDate().addMonths(-1), estirar=False
        )

        self.tabla = crear_tabla(["Fecha", "Comprobante", "Nro", "Cantidad"], estirar=0)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde = self.fecha_desde.date().toString("yyyy-MM-dd")
        hasta = self.fecha_hasta.date().toString("yyyy-MM-dd")
        movimientos = articulos_repo.obtener_movimientos(self.codigo, desde, hasta)
        self.tabla.setRowCount(0)
        for movimiento in movimientos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(movimiento["fecha"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(movimiento["comprobante"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(str(movimiento["numero"])))
            item_cantidad = QTableWidgetItem(str(movimiento["cantidad"]))
            if movimiento["cantidad"] < 0:
                item_cantidad.setForeground(Qt.red)
            self.tabla.setItem(fila, 3, item_cantidad)


class DialogoGestionRubros(QDialog):
    """
    Administración del catálogo de Rubros (se abre desde Artículos, así
    que la ve quien tenga acceso a esa pantalla). Acá es el ÚNICO lugar donde se pueden crear, renombrar o
    borrar rubros — en el alta/edición de un artículo, Rubro es un
    desplegable cerrado que solo permite elegir uno de los ya existentes,
    para que no queden rubros mal escritos o duplicados por typos.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Rubros")
        self.resize(380, 420)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.lista = crear_tabla(["Rubro"], estirar=0, por_filas=True, una_sola=True)
        self.lista.horizontalHeader().setVisible(False)

        self.campo_nuevo = QLineEdit()
        self.campo_nuevo.setPlaceholderText("Nombre del rubro nuevo...")
        boton_agregar = QPushButton("Agregar")
        aplicar_clase(boton_agregar, "primario")
        boton_agregar.clicked.connect(self._agregar)
        encadenar_enter(self.campo_nuevo, accion_final=self._agregar)

        fila_agregar = QHBoxLayout()
        fila_agregar.addWidget(self.campo_nuevo)
        fila_agregar.addWidget(boton_agregar)

        boton_renombrar = QPushButton("Renombrar seleccionado")
        boton_renombrar.clicked.connect(self._renombrar)
        boton_borrar = QPushButton("Borrar seleccionado")
        aplicar_clase(boton_borrar, "peligro")
        boton_borrar.clicked.connect(self._borrar)

        fila_acciones = QHBoxLayout()
        fila_acciones.addWidget(boton_renombrar)
        fila_acciones.addWidget(boton_borrar)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Rubros disponibles para cargar en Artículos:"))
        layout.addWidget(self.lista)
        layout.addLayout(fila_agregar)
        layout.addLayout(fila_acciones)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        self.campo_nuevo.setFocus()

    @manejar_errores
    def _cargar(self):
        self.rubros = articulos_repo.listar_rubros()
        self.lista.setRowCount(0)
        for rubro in self.rubros:
            fila = self.lista.rowCount()
            self.lista.insertRow(fila)
            self.lista.setItem(fila, 0, QTableWidgetItem(rubro["nombre"]))

    def _rubro_seleccionado(self):
        fila = self.lista.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un rubro de la lista.")
            return None
        return self.rubros[fila]

    @manejar_errores
    def _agregar(self):
        nombre = self.campo_nuevo.text().strip()
        if not nombre:
            mostrar_error(self, "Falta el nombre", "Escribí el nombre del rubro nuevo.")
            return
        articulos_repo.crear_rubro(nombre)
        self.campo_nuevo.clear()
        self._cargar()
        self.campo_nuevo.setFocus()

    @manejar_errores
    def _renombrar(self):
        rubro = self._rubro_seleccionado()
        if rubro is None:
            return
        nuevo_nombre, aceptado = QInputDialog.getText(
            self, "Renombrar rubro", "Nuevo nombre:", text=rubro["nombre"]
        )
        if not aceptado:
            return
        articulos_repo.renombrar_rubro(rubro["id"], nuevo_nombre)
        self._cargar()

    @manejar_errores
    def _borrar(self):
        rubro = self._rubro_seleccionado()
        if rubro is None:
            return
        if confirmar(self, "Confirmar borrado",
                     f"¿Borrar el rubro '{rubro['nombre']}'? Esta acción no se puede deshacer."):
            articulos_repo.borrar_rubro(rubro["id"])
            self._cargar()
