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
  momento de facturar (doble clic en el producto, que muestra su precio
  por unidad, o en su total). Una EMPLEADA nunca puede tocar precios.
- "A cuenta de una PC..." (pedido del dueño, 2026-10-25): en vez de cobrar,
  anota el carrito en la Cuenta de la PC de un cliente que está jugando y se
  cobra después (ver control_pcs/repositories/cuentas_pc_repo.py).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QPushButton, QLineEdit, QLabel,
    QInputDialog, QFrame, QWidget, QHeaderView,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QShortcut, QKeySequence
from datetime import datetime

import dominio
from control_pcs.repositories import cuentas_pc_repo
from control_pcs.ui.cuenta_pc_dialogos import DialogoElegirPc, anotar_en_la_cuenta
from repositories import articulos_repo, ventas_repo
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_info, confirmar, manejar_errores, aplicar_clase,
    sin_boton_por_defecto, crear_tabla, pedir_pesos,
)
from ui.buscar_articulo import armar_botones_de_busqueda, avisar_codigo_no_encontrado
from ui.dialogo_pago import DialogoPago
from ui.ventas_dibujos import ROL_DETALLE, DelegadoProducto, icono_codigo_de_barras, icono_de_tecla


class VentasWindow(QDialog):
    """El carrito vive solo en `self.carrito` (memoria) hasta que se cobra."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self.carrito = []  # cada línea: {codigo, descripcion, cantidad, precio_unitario}
        self._cantidad_pendiente = 1  # usado por el atajo "*" (cambiar cantidad antes de escanear)
        self.setWindowTitle("Venta de Mercadería")
        self.setMinimumSize(820, 500)
        self.resize(960, 600)
        self._armar_interfaz()

    def se_puede_cerrar_sola(self) -> bool:
        """Para el cierre forzoso de la caja (MainWindow._hay_un_cobro_a_medias):
        con el carrito vacío no se pierde nada si esta ventana se cierra sola; con
        artículos cargados, el cierre espera a que se cobre o se cancele."""
        return not self.carrito

    def _armar_interfaz(self):
        # El diseño que eligió el dueño (2026-10-26, maqueta "B"): a la izquierda se
        # escanea y se ve el carrito; a la derecha, el total y COBRAR siempre grandes.
        # Los colores están en la hoja de estilos (ui/hoja_de_estilos.py, "Venta de
        # Mercadería"); los dibujos, en ui/ventas_dibujos.py.
        encabezado = QFrame()
        encabezado.setObjectName("encabezadoVenta")
        fila_encabezado = QHBoxLayout(encabezado)
        fila_encabezado.setContentsMargins(16, 10, 16, 10)
        titulo = QLabel("🛒  Venta de Mercadería")
        titulo.setObjectName("tituloVenta")
        datos = QLabel(f"{self.usuario['nombre']}   ·   {datetime.now().strftime('%d/%m/%Y %H:%M')}")
        datos.setObjectName("datosVenta")
        fila_encabezado.addWidget(titulo)
        fila_encabezado.addStretch()
        fila_encabezado.addWidget(datos)

        self.campo_codigo = QLineEdit()
        self.campo_codigo.setObjectName("campoEscaneo")
        self.campo_codigo.setPlaceholderText("Escaneá el código de barras y apretá Enter...")
        self.campo_codigo.addAction(icono_codigo_de_barras(), QLineEdit.LeadingPosition)
        self.campo_codigo.returnPressed.connect(self._escanear)

        # Solo se ve cuando avisa algo: vacío no tiene que dejar un hueco.
        self.etiqueta_aviso_stock = QLabel("")
        self.etiqueta_aviso_stock.setObjectName("avisoStockVenta")
        self.etiqueta_aviso_stock.setVisible(False)

        # El código y el precio por unidad van chiquitos debajo del producto
        # (ui.ventas_dibujos.DelegadoProducto): la descripción se lee mejor.
        self.tabla = crear_tabla(["Cant.", "Producto", "$ Total"], estirar=1)
        self.tabla.setItemDelegateForColumn(1, DelegadoProducto(self.tabla))
        self.tabla.verticalHeader().setDefaultSectionSize(46)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Fixed)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Fixed)
        self.tabla.setColumnWidth(0, 64)
        self.tabla.setColumnWidth(2, 130)
        self.tabla.horizontalHeaderItem(2).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.tabla.cellDoubleClicked.connect(self._al_hacer_doble_clic)

        botones_de_busqueda = armar_botones_de_busqueda(self, self._agregar_al_carrito, tecla_aparte=True)
        boton_cantidad = self._boton_con_tecla("*", "Cantidad")
        boton_cantidad.setToolTip("Cargar la cantidad antes de escanear (ej: 3 personas piden lo mismo)")
        boton_cantidad.clicked.connect(self._cambiar_cantidad_pendiente)
        boton_borrar = self._boton_con_tecla("Supr", "Quitar")
        boton_borrar.setToolTip("Quitar del carrito el producto marcado")
        boton_borrar.clicked.connect(self._borrar_linea)

        QShortcut(QKeySequence("Delete"), self, activated=self._borrar_linea)

        fila_atajos = QHBoxLayout()
        fila_atajos.setSpacing(6)
        for boton in botones_de_busqueda + [boton_cantidad, boton_borrar]:
            aplicar_clase(boton, "tecla")
            fila_atajos.addWidget(boton)
        fila_atajos.addStretch()

        izquierda = QVBoxLayout()
        izquierda.setSpacing(10)
        izquierda.addWidget(self.campo_codigo)
        izquierda.addWidget(self.etiqueta_aviso_stock)
        izquierda.addLayout(fila_atajos)
        izquierda.addWidget(self.tabla)

        # El "ticket" de la derecha: el total oscuro, como la barra de arriba de la
        # ventana principal.
        recuadro_total = QFrame()
        recuadro_total.setObjectName("totalVenta")
        columna_total = QVBoxLayout(recuadro_total)
        columna_total.setContentsMargins(12, 14, 12, 14)
        columna_total.setSpacing(4)
        titulo_total = QLabel("TOTAL A COBRAR")
        titulo_total.setObjectName("totalVentaTitulo")
        self.etiqueta_total = QLabel(formato_pesos(0))
        self.etiqueta_total.setObjectName("totalVentaMonto")
        self.etiqueta_unidades = QLabel("")
        self.etiqueta_unidades.setObjectName("totalVentaUnidades")
        for etiqueta in (titulo_total, self.etiqueta_total, self.etiqueta_unidades):
            etiqueta.setAlignment(Qt.AlignCenter)
            columna_total.addWidget(etiqueta)

        self.boton_aceptar = QPushButton("COBRAR (Enter)")
        self.boton_aceptar.setObjectName("botonCobrarVenta")
        aplicar_clase(self.boton_aceptar, "primario")
        self.boton_aceptar.clicked.connect(self._ir_a_cobrar)
        self.boton_a_cuenta = QPushButton("A cuenta de una PC")
        self.boton_a_cuenta.setObjectName("botonACuentaVenta")
        aplicar_clase(self.boton_a_cuenta, "cuenta")
        self.boton_a_cuenta.clicked.connect(self._anotar_a_cuenta)
        boton_cancelar = QPushButton("Cancelar venta")
        aplicar_clase(boton_cancelar, "peligro")
        boton_cancelar.clicked.connect(self._cancelar_venta)

        derecha = QVBoxLayout()
        derecha.setSpacing(8)
        derecha.addWidget(recuadro_total)
        derecha.addWidget(self.boton_aceptar)
        derecha.addWidget(self.boton_a_cuenta)
        derecha.addStretch()
        derecha.addWidget(boton_cancelar)
        columna_derecha = QWidget()
        columna_derecha.setFixedWidth(220)
        columna_derecha.setLayout(derecha)
        derecha.setContentsMargins(0, 0, 0, 0)

        cuerpo = QHBoxLayout()
        cuerpo.setContentsMargins(14, 12, 14, 14)
        cuerpo.setSpacing(14)
        cuerpo.addLayout(izquierda, 1)
        cuerpo.addWidget(columna_derecha)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(0)
        layout.addWidget(encabezado)
        layout.addLayout(cuerpo, 1)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        self._refrescar_tabla()
        self.campo_codigo.setFocus()

    @staticmethod
    def _boton_con_tecla(tecla, nombre):
        """Un botón con su tecla dibujada adelante, como F5/F6/F7."""
        boton = QPushButton(nombre)
        icono, tamano = icono_de_tecla(tecla)
        boton.setIcon(icono)
        boton.setIconSize(tamano)
        return boton

    def _avisar_stock(self, texto):
        self.etiqueta_aviso_stock.setText(texto)
        self.etiqueta_aviso_stock.setVisible(bool(texto))

    # -----------------------------------------------------------------
    # Escaneo / búsqueda de artículos
    # -----------------------------------------------------------------

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
            avisar_codigo_no_encontrado(self, codigo)
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
            self._avisar_stock(f"{articulo['descripcion']} debajo de Stock Mín. Actualmente hay {stock_proyectado}")
        else:
            self._avisar_stock("")

    # -----------------------------------------------------------------
    # Edición del carrito (mientras la venta no está confirmada)
    # -----------------------------------------------------------------

    def _al_hacer_doble_clic(self, fila, columna):
        if columna == 0:  # Cantidad: cualquiera puede corregirla antes de cobrar
            self._editar_cantidad(fila)
        elif columna in (1, 2) and self.es_admin:  # el producto (con su precio c/u) o su total: precio, solo Admin
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
        nuevo_precio, aceptado = pedir_pesos(
            self, "Modificar Precio", f"{linea['descripcion']}\nNuevo precio unitario:", linea["precio_unitario"]
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
        for linea in self.carrito:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            cantidad = QTableWidgetItem(str(linea["cantidad"]))
            cantidad.setTextAlignment(Qt.AlignCenter)
            producto = QTableWidgetItem(linea["descripcion"])
            producto.setData(ROL_DETALLE, f"{linea['codigo']}  ·  {formato_pesos(linea['precio_unitario'])} c/u")
            subtotal = QTableWidgetItem(formato_pesos(ventas_repo.subtotal_linea(linea)))
            subtotal.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla.setItem(fila, 0, cantidad)
            self.tabla.setItem(fila, 1, producto)
            self.tabla.setItem(fila, 2, subtotal)
        self.etiqueta_total.setText(formato_pesos(self._total_carrito()))
        unidades = sum(linea["cantidad"] for linea in self.carrito)
        self.etiqueta_unidades.setText(
            "Sin productos" if not unidades else f"{unidades} unidad{'' if unidades == 1 else 'es'}"
        )

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
            self._avisar_stock("")
            self._refrescar_tabla()
            self.campo_codigo.setFocus()

    @manejar_errores
    def _anotar_a_cuenta(self):
        """El carrito no se cobra: se anota en la Cuenta de la PC que se elija y
        se cobra después (el stock baja ya, ver cuentas_pc_repo.anotar_articulos)."""
        if not self.carrito:
            mostrar_error(self, "Venta vacía", "Todavía no escaneaste ningún producto.")
            return
        elegir = DialogoElegirPc(self._total_carrito(), self)
        if not elegir.exec():
            return
        item = elegir.item
        resultado = anotar_en_la_cuenta(
            self, item,
            lambda **datos: cuentas_pc_repo.anotar_articulos(
                item["estacion"]["id"], self.carrito, self.usuario["id"], **datos
            ),
        )
        if resultado is None:
            return
        a_nombre = f" ({resultado['nombre']})" if resultado["nombre"] else ""
        mostrar_info(self, "Anotado en la cuenta",
                     f"Anotado en la cuenta de {resultado['estacion']}{a_nombre}.\n"
                     f"Debe ahora {formato_pesos(resultado['debe'])}: su PC titila en fucsia hasta que se cobre.")
        self.carrito = []
        self._avisar_stock("")
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
