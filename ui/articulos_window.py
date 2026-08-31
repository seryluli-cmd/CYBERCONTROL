"""
articulos_window.py
=====================
Pantalla de Artículos: la grilla con todos los productos, y el cuadro de
alta/edición. Solo la usa el Admin (las empleadas no tienen acceso a
este módulo). Importante: acá NUNCA se edita el stock a mano — el stock
solo se mueve desde Compras (ver compras_window.py).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QDoubleSpinBox, QSpinBox,
    QFormLayout, QMessageBox, QDateEdit, QHeaderView, QInputDialog
)
from PySide6.QtCore import Qt, QDate

from repositories import articulos_repo
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_aviso, confirmar, manejar_errores,
    aplicar_clase, encadenar_enter,
)


class ArticulosWindow(QDialog):
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

        self.tabla = QTableWidget(0, 8)
        self.tabla.setHorizontalHeaderLabels(
            ["Código", "Descripción", "Marca", "Rubro", "Precio Venta",
             "Precio Compra", "Stock", "Stock Mínimo"]
        )
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        # Con esto, clickeando el título de una columna se ordena la
        # grilla por esa columna: cumple la misma función que el botón
        # "Ordenar" del sistema anterior, sin necesitar un botón aparte.
        self.tabla.setSortingEnabled(True)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.doubleClicked.connect(self._modificar_articulo)

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.campo_buscar)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _cargar_grilla(self):
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
        self.resize(420, 380)
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

        self.spin_stock_minimo = QSpinBox()
        self.spin_stock_minimo.setMaximum(999_999)

        self.etiqueta_stock = QLabel("(el stock se carga desde Compras)")
        self.etiqueta_stock.setStyleSheet("color: gray; font-style: italic;")

        # La pistola lectora escribe el código y después manda un Enter
        # sola, automáticamente. Antes ese Enter no hacía nada útil (en
        # versiones viejas, incluso llegaba a disparar "Guardar" antes
        # de tiempo). Ahora ese Enter pasa prolijamente el foco al
        # siguiente campo, como si se apretara Tab, para poder seguir
        # cargando el artículo sin tocar el mouse — encadenado por todo
        # el formulario, terminando en Guardar (ver encadenar_enter).
        encadenar_enter(
            self.campo_codigo, self.campo_descripcion, self.combo_marca, self.combo_rubro,
            self.spin_precio_venta, self.spin_precio_compra, self.spin_stock_minimo,
            accion_final=self._guardar,
        )

        formulario = QFormLayout()
        formulario.addRow("Código (de barras):", self.campo_codigo)
        formulario.addRow("Descripción:", self.campo_descripcion)
        formulario.addRow("Marca:", self.combo_marca)
        formulario.addRow("Rubro:", self.combo_rubro)
        formulario.addRow("Precio Venta:", self.spin_precio_venta)
        formulario.addRow("Precio Compra (costo):", self.spin_precio_compra)
        formulario.addRow("Stock Mínimo:", self.spin_stock_minimo)
        formulario.addRow("Stock actual:", self.etiqueta_stock)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)

        botones = QHBoxLayout()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addLayout(formulario)
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
        self.fecha_desde = QDateEdit(QDate.currentDate().addMonths(-1))
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_hasta = QDateEdit(QDate.currentDate())
        self.fecha_hasta.setCalendarPopup(True)
        boton_buscar = QPushButton("Buscar")
        boton_buscar.clicked.connect(self._buscar)
        encadenar_enter(self.fecha_desde, self.fecha_hasta, accion_final=self._buscar)

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Desde:"))
        filtros.addWidget(self.fecha_desde)
        filtros.addWidget(QLabel("Hasta:"))
        filtros.addWidget(self.fecha_hasta)
        filtros.addWidget(boton_buscar)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Fecha", "Comprobante", "Nro", "Cantidad"])
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

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
    Administración del catálogo de Rubros (solo Admin, se abre desde
    Artículos). Acá es el ÚNICO lugar donde se pueden crear, renombrar o
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
        self.lista = QTableWidget(0, 1)
        self.lista.setHorizontalHeaderLabels(["Rubro"])
        self.lista.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lista.horizontalHeader().setVisible(False)
        self.lista.setSelectionBehavior(QTableWidget.SelectRows)
        self.lista.setSelectionMode(QTableWidget.SingleSelection)
        self.lista.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lista.setAlternatingRowColors(True)

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
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

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
