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
    QPushButton, QLineEdit, QLabel, QHeaderView, QInputDialog, QRadioButton,
    QButtonGroup, QDoubleSpinBox, QComboBox
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence, QFont
from datetime import datetime

from repositories import articulos_repo, ventas_repo
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_info, mostrar_aviso, confirmar, manejar_errores, aplicar_clase
)
from ui.buscar_articulo import DialogoBuscarArticulo


class VentasWindow(QDialog):
    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = usuario["rol"] == "ADMIN"
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
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

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
            subtotal = linea["cantidad"] * linea["precio_unitario"]
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
        return sum(l["cantidad"] * l["precio_unitario"] for l in self.carrito)

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
            lineas_para_guardar = [
                {
                    "codigo": l["codigo"],
                    "descripcion": l["descripcion"],
                    "cantidad": l["cantidad"],
                    "precio_unitario": l["precio_unitario"],
                    "subtotal": l["cantidad"] * l["precio_unitario"],
                }
                for l in self.carrito
            ]
            numero_factura = ventas_repo.confirmar_venta(self.usuario["id"], lineas_para_guardar, dialogo.pagos)

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
        Cancela la venta en curso y vuelve al menú principal — hace lo
        mismo que apretar la X de la ventana. Antes este botón solo
        vaciaba el carrito y se quedaba en la misma pantalla, lo que
        obligaba a usar la X para salir; ahora "Cancelar Venta" también
        cierra la pantalla, como espera la empleada.
        """
        if self.carrito and not confirmar(self, "Cancelar venta",
                                            "¿Cancelar esta venta y volver al menú? "
                                            "Se va a vaciar el carrito actual."):
            return
        self.carrito = []
        self._refrescar_tabla()
        self.reject()


class DialogoPago(QDialog):
    """
    Cuadro de cobro. A diferencia del sistema anterior (que solo dejaba
    elegir UN medio de pago para el total completo), acá se pueden ir
    agregando pagos parciales — por ejemplo, una parte en Efectivo y el
    resto en Digital (Mercado Pago / transferencia) — hasta cubrir el
    total. El botón Confirmar recién se habilita cuando ya está cubierto.
    """

    def __init__(self, parent, total: float):
        super().__init__(parent)
        self.total = total
        self.pagos = []  # lista de {"metodo": "EFECTIVO"|"DIGITAL", "monto": ...}
        self.vuelto = 0.0
        self.setWindowTitle("Cobrar Venta")
        self.resize(420, 420)
        self._armar_interfaz()
        self._refrescar()
        # Por las dudas se cierre el cuadro (Cancelar o Confirmar) con el
        # vuelto titilando, apagamos el timer para que no siga corriendo
        # de fondo sin sentido.
        self.finished.connect(lambda _resultado: self._parpadeo_timer.stop())

    def _armar_interfaz(self):
        fuente_total = QFont()
        fuente_total.setPointSize(18)
        fuente_total.setBold(True)

        self.etiqueta_total = QLabel()
        self.etiqueta_total.setFont(fuente_total)

        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Efectivo", "EFECTIVO")
        self.combo_metodo.addItem("Digital (Mercado Pago / Transferencia)", "DIGITAL")

        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        # Apretar Enter en el monto no solo agrega ese pago: si sobra
        # algo para llegar al total, lo completa solo con el OTRO medio
        # de pago (ver _agregar_pago_y_completar). Es el caso más común
        # en el mostrador: "una parte en efectivo, el resto digital", o
        # al revés — así se resuelve en un solo Enter, sin calculadora.
        self.spin_monto.lineEdit().returnPressed.connect(self._agregar_pago_y_completar)

        boton_agregar = QPushButton("Agregar pago")
        boton_agregar.setToolTip("Agrega únicamente el monto tipeado, con el medio elegido.")
        boton_agregar.clicked.connect(self._agregar_pago)

        fila_agregar = QHBoxLayout()
        fila_agregar.addWidget(self.combo_metodo)
        fila_agregar.addWidget(self.spin_monto)
        fila_agregar.addWidget(boton_agregar)

        etiqueta_ayuda = QLabel(
            "Tip: escribí el monto de un medio de pago y apretá Enter — si sobra algo "
            "para llegar al total, se completa solo con el otro medio."
        )
        etiqueta_ayuda.setWordWrap(True)
        etiqueta_ayuda.setStyleSheet("color: gray; font-style: italic; font-size: 11px;")

        self.tabla_pagos = QTableWidget(0, 2)
        self.tabla_pagos.setHorizontalHeaderLabels(["Medio de pago", "Monto"])
        self.tabla_pagos.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla_pagos.setAlternatingRowColors(True)
        self.tabla_pagos.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        boton_quitar_pago = QPushButton("Quitar pago seleccionado")
        boton_quitar_pago.clicked.connect(self._quitar_pago)

        self.etiqueta_falta = QLabel()

        # El vuelto se destaca a propósito: rojo, negrita y titilando,
        # para que a la empleada no se le pase entregarlo (es plata que
        # tiene que devolver, y en el ajetreo del mostrador es fácil
        # olvidarlo). El titileo se logra con un QTimer que alterna el
        # COLOR del texto (visible <-> transparente) cada medio segundo,
        # en vez de mostrar/ocultar la etiqueta: si se usara setVisible(),
        # Qt le saca el espacio reservado en el layout cuando está oculta,
        # y todo lo de abajo (los botones) se corre de lugar cada medio
        # segundo. Manteniendo la etiqueta siempre visible, con solo el
        # color titilando, el espacio ocupado nunca cambia y nada se mueve.
        self.etiqueta_vuelto = QLabel()
        self.etiqueta_vuelto.setAlignment(Qt.AlignCenter)
        self._estilo_vuelto_prendido = "color: #A6323C; font-weight: bold; font-size: 16px;"
        self._estilo_vuelto_apagado = "color: rgba(0, 0, 0, 0); font-weight: bold; font-size: 16px;"
        self.etiqueta_vuelto.setStyleSheet(self._estilo_vuelto_prendido)
        self._parpadeo_timer = QTimer(self)
        self._parpadeo_timer.setInterval(500)  # medio segundo prendido, medio apagado
        self._parpadeo_timer.timeout.connect(self._alternar_parpadeo_vuelto)
        self._parpadeo_visible = True

        self.boton_confirmar = QPushButton("Confirmar")
        aplicar_clase(self.boton_confirmar, "primario")
        self.boton_confirmar.clicked.connect(self._confirmar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)

        # Con Confirmar sin ser el botón "default" (ver el bucle de más
        # abajo, necesario para que Enter en el código de barras no
        # dispare botones ajenos), apretar Enter estando el foco EN el
        # botón Confirmar no lo activa solo. Se agrega un atajo de
        # teclado con contexto WidgetShortcut: solo responde a Enter
        # cuando el foco está puesto justo en ese botón, así que no
        # reintroduce el problema de "Enter en cualquier lado dispara el
        # botón". Se cubren Key_Return (Enter del teclado) y Key_Enter
        # (Enter del teclado numérico).
        self._atajo_confirmar_return = QShortcut(QKeySequence(Qt.Key_Return), self.boton_confirmar)
        self._atajo_confirmar_return.setContext(Qt.WidgetShortcut)
        self._atajo_confirmar_return.activated.connect(self.boton_confirmar.click)
        self._atajo_confirmar_enter = QShortcut(QKeySequence(Qt.Key_Enter), self.boton_confirmar)
        self._atajo_confirmar_enter.setContext(Qt.WidgetShortcut)
        self._atajo_confirmar_enter.activated.connect(self.boton_confirmar.click)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_total)
        layout.addLayout(fila_agregar)
        layout.addWidget(etiqueta_ayuda)
        layout.addWidget(self.tabla_pagos)
        layout.addWidget(boton_quitar_pago)
        layout.addWidget(self.etiqueta_falta)
        layout.addWidget(self.etiqueta_vuelto)
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

        self.spin_monto.setFocus()

    def _validar_y_agregar(self, metodo, monto):
        """
        Valida y agrega UN pago a self.pagos. Devuelve True si se pudo
        agregar (y ya queda cargado); False si no era válido (y ya se
        le mostró el error a la usuaria). Lo comparten _agregar_pago
        (botón) y _agregar_pago_y_completar (Enter).
        """
        if monto <= 0:
            mostrar_error(self, "Monto inválido", "Ingresá un monto mayor a cero.")
            return False

        # Un pago Digital no puede superar lo que todavía falta cubrir
        # (a diferencia del Efectivo, que sí puede pasarse: ahí se
        # calcula el vuelto).
        if metodo == "DIGITAL":
            cubierto_digital = sum(p["monto"] for p in self.pagos if p["metodo"] == "DIGITAL")
            falta_sin_efectivo = self.total - cubierto_digital
            if monto > falta_sin_efectivo + 0.01:
                mostrar_aviso(self, "Monto demasiado alto",
                              "El pago Digital no puede superar lo que falta cubrir del total.")
                return False

        self.pagos.append({"metodo": metodo, "monto": monto})
        return True

    def _agregar_pago(self):
        """Botón "Agregar pago": suma únicamente el monto tipeado, tal
        cual, sin tocar nada más."""
        monto = self.spin_monto.value()
        metodo = self.combo_metodo.currentData()
        if self._validar_y_agregar(metodo, monto):
            self.spin_monto.setValue(0)
            self._refrescar()

    def _agregar_pago_y_completar(self):
        """
        Se dispara al apretar Enter en el campo de monto. Agrega el pago
        tipeado y, si con eso todavía no se cubre el total de la venta,
        completa automáticamente lo que falta con el OTRO medio de pago
        (Efectivo <-> Digital). Cubre el caso más frecuente en el
        mostrador: "una parte en efectivo, el resto en digital" (o al
        revés) en un solo paso, sin tener que calcular el resto a mano.
        """
        monto = self.spin_monto.value()
        if monto <= 0:
            # Un Enter con el campo en $0 no hace nada (por ejemplo, el
            # que queda pendiente justo después de agregar un pago, que
            # deja el campo en cero listo para el siguiente). No tiene
            # sentido molestar con un cartel de error acá.
            return
        metodo = self.combo_metodo.currentData()

        falta_antes = self.total - sum(p["monto"] for p in self.pagos)

        if not self._validar_y_agregar(metodo, monto):
            return

        resto = falta_antes - monto
        if resto > 0.01:
            otro_metodo = "DIGITAL" if metodo == "EFECTIVO" else "EFECTIVO"
            # El resto siempre es, como mucho, lo que faltaba cubrir, así
            # que nunca puede superar el tope de Digital: no hace falta
            # volver a validar acá.
            self.pagos.append({"metodo": otro_metodo, "monto": round(resto, 2)})

        self.spin_monto.setValue(0)
        self._refrescar()

        # Si con este Enter ya quedó todo cubierto, el foco pasa directo
        # a Confirmar: así, apretando Enter una vez más (ahora con el
        # atajo de teclado que responde solo cuando el foco está en ese
        # botón), se confirma la venta sin tocar el mouse.
        if self.boton_confirmar.isEnabled():
            self.boton_confirmar.setFocus()

    def _quitar_pago(self):
        fila = self.tabla_pagos.currentRow()
        if fila >= 0:
            del self.pagos[fila]
            self._refrescar()

    def _alternar_parpadeo_vuelto(self):
        """Cada vez que dispara el timer, alterna el color del texto del
        vuelto entre visible y transparente — eso es lo que se ve como
        un titileo. La etiqueta en sí queda SIEMPRE visible (nunca se usa
        setVisible), para que su espacio en el layout no cambie y nada
        se corra de lugar en la pantalla."""
        self._parpadeo_visible = not self._parpadeo_visible
        estilo = self._estilo_vuelto_prendido if self._parpadeo_visible else self._estilo_vuelto_apagado
        self.etiqueta_vuelto.setStyleSheet(estilo)

    def _refrescar(self):
        self.etiqueta_total.setText(f"Total: {formato_pesos(self.total)}")

        self.tabla_pagos.setRowCount(0)
        for pago in self.pagos:
            fila = self.tabla_pagos.rowCount()
            self.tabla_pagos.insertRow(fila)
            nombre_metodo = "Efectivo" if pago["metodo"] == "EFECTIVO" else "Digital"
            self.tabla_pagos.setItem(fila, 0, QTableWidgetItem(nombre_metodo))
            self.tabla_pagos.setItem(fila, 1, QTableWidgetItem(formato_pesos(pago["monto"])))

        total_efectivo = sum(p["monto"] for p in self.pagos if p["metodo"] == "EFECTIVO")
        total_digital = sum(p["monto"] for p in self.pagos if p["metodo"] == "DIGITAL")
        falta = self.total - total_digital - total_efectivo

        if falta > 0.01:
            self.etiqueta_falta.setText(f"Falta cobrar: {formato_pesos(falta)}")
            self.etiqueta_falta.setStyleSheet("color: #A6323C; font-weight: bold;")
            self.vuelto = 0.0
            self._detener_parpadeo_vuelto()
            self.boton_confirmar.setEnabled(False)
        else:
            self.vuelto = max(0.0, total_efectivo - (self.total - total_digital))
            self.etiqueta_falta.setText("Cobro completo ✓")
            self.etiqueta_falta.setStyleSheet("color: #1E8E5A; font-weight: bold;")
            if self.vuelto > 0:
                self.etiqueta_vuelto.setText(f"VUELTO: {formato_pesos(self.vuelto)}")
                if not self._parpadeo_timer.isActive():
                    self._parpadeo_timer.start()
            else:
                self._detener_parpadeo_vuelto()
            self.boton_confirmar.setEnabled(True)

    def _detener_parpadeo_vuelto(self):
        """Apaga el titileo y deja la etiqueta vacía, con el color
        "prendido" de base, lista para la próxima vez que haga falta
        mostrar un vuelto. La etiqueta nunca se oculta (setVisible), así
        que esto no afecta el espacio que ocupa en el layout."""
        self._parpadeo_timer.stop()
        self._parpadeo_visible = True
        self.etiqueta_vuelto.setStyleSheet(self._estilo_vuelto_prendido)
        self.etiqueta_vuelto.setText("")

    def _confirmar(self):
        self.accept()
