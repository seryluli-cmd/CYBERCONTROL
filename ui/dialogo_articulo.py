"""
dialogo_articulo.py
=====================
El cuadro de alta y modificación de un artículo (salió de articulos_window.py,
que pasaba las 600 líneas). Lo abre Artículos; nunca toca el stock: el stock se
carga desde Compras y solo se corrige con ORDENAR Stock.

Con la maqueta B que eligió el dueño el 2026-10-31 para el kiosko y pidió también
acá ("dos columnas con el precio en grande"): arriba la cabecera oscura con el nombre del artículo, su código,
marca y rubro, y el stock actual y el mínimo; a la izquierda una ficha blanca con
los datos, cada uno con su rótulo arriba; a la derecha una tarjeta oscura con el
precio de venta bien grande, cuánto se gana por unidad y la calculadora de
precios (COSTO, GANANCIA %, VENTA, cada uno con su "＝ Calcular"). Los campos de
números no tienen las flechitas de subir y bajar, que no se usaban.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit,
    QSpinBox, QVBoxLayout,
)

import dominio
from control_pcs.ui.dibujos_de_ventana import pixmap_de
from repositories import articulos_repo
from ui.piezas_ventana import agregar_indicador, cabecera_oscura, poner_indicador, tecla
from ui.utils import (
    CampoPesos, CampoPorcentaje, encadenar_enter, fila_guardar_cancelar, formato_pesos, manejar_errores,
    mostrar_aviso, mostrar_error, sin_boton_por_defecto,
)

AYUDA_DE_LA_CALCULADORA = "Cargá dos y apretá Calcular en el que falta"


def _rotulo(texto: str, nombre: str = "rotuloFicha") -> QLabel:
    etiqueta = QLabel(texto.upper())
    etiqueta.setObjectName(nombre)
    return etiqueta


def _sin_flechitas(campo: QAbstractSpinBox):
    """Sin las flechitas de subir y bajar (las "rayitas" de la derecha) y con el
    número contra la derecha, como en las grillas."""
    campo.setButtonSymbols(QAbstractSpinBox.NoButtons)
    campo.setAlignment(Qt.AlignRight | Qt.AlignVCenter)


class DialogoArticulo(QDialog):
    """Cuadro de alta o edición de un artículo (según si se le pasa un
    código existente o no)."""

    def __init__(self, parent, codigo_existente: str = None):
        super().__init__(parent)
        self.codigo_existente = codigo_existente
        self._stock_actual = 0
        self.setWindowTitle("Modificación de Artículos" if codigo_existente else "Nuevo Artículo")
        self.resize(920, 580)
        self._armar_interfaz()
        if codigo_existente:
            self._cargar_datos(codigo_existente)
        self._actualizar_cabecera()
        self._actualizar_precios()

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

        # Calculadora de precios (la maqueta D que eligió el dueño el 2026-10-31):
        # COSTO + GANANCIA % = PRECIO DE VENTA, cada casillero con su "＝ Calcular",
        # que lo saca de los otros dos. Así sirve para las tres cosas: con el costo
        # y el % sale la venta; con la venta y el % se estima el costo (cuando se
        # perdió la factura y se sabe el precio de otro local); y con el costo y la
        # venta sale el % que se le está ganando (Impresiones: $ 20 y $ 200, 900%).
        # Es a botón, no en vivo: así no pisa un precio que ya se cargó a mano. El %
        # arranca en dominio.MARGEN_POR_DEFECTO (80%, pedido del dueño); el precio
        # grande y la ganancia de arriba sí van en vivo, con los dos precios cargados.
        self.spin_precio_compra = CampoPesos()
        self.campo_porcentaje = CampoPorcentaje()
        self.campo_porcentaje.setValue(dominio.MARGEN_POR_DEFECTO)
        self.spin_precio_venta = CampoPesos()
        self.boton_calcular_costo = tecla("＝  Calcular", self._calcular_costo_desde_venta)
        self.boton_calcular_porcentaje = tecla("＝  Calcular", self._calcular_porcentaje)
        self.boton_calcular_venta = tecla("＝  Calcular", self._calcular_venta_desde_costo)
        self.spin_precio_compra.valueChanged.connect(self._actualizar_precios)
        self.spin_precio_venta.valueChanged.connect(self._actualizar_precios)

        self.spin_stock_minimo = QSpinBox()
        self.spin_stock_minimo.setMaximum(999_999)
        self.spin_stock_minimo.valueChanged.connect(self._actualizar_cabecera)
        for campo in (self.spin_precio_compra, self.campo_porcentaje, self.spin_precio_venta, self.spin_stock_minimo):
            _sin_flechitas(campo)

        # La pistola lectora escribe el código y manda un Enter sola. Ese
        # Enter pasa el foco al siguiente campo, como si se apretara Tab,
        # para seguir cargando el artículo sin tocar el mouse — encadenado
        # por todo el formulario, terminando en Guardar (ver encadenar_enter).
        # Va en el orden en que se ven: la columna de los datos y después la
        # calculadora.
        encadenar_enter(
            self.campo_codigo, self.campo_descripcion, self.combo_marca, self.combo_rubro,
            self.spin_stock_minimo, self.spin_precio_compra, self.campo_porcentaje, self.spin_precio_venta,
            accion_final=self._guardar,
        )

        self.cabecera = cabecera_oscura("", "")
        # El lápiz y el más dibujados: el ✎ no sale en el Windows del mostrador.
        self.cabecera.icono.setPixmap(pixmap_de("lapiz" if self.codigo_existente else "mas", 30, "#EAF4FF", 1.6))
        # El stock actual y el mínimo, solo al modificar: uno nuevo arranca sin stock.
        self.indicador_stock = self.indicador_minimo = None
        if self.codigo_existente:
            self.indicador_stock = agregar_indicador(self.cabecera, "Stock actual")
            self.indicador_minimo = agregar_indicador(self.cabecera, "Mínimo")
        self.campo_descripcion.textChanged.connect(self._actualizar_cabecera)
        self.combo_marca.currentTextChanged.connect(self._actualizar_cabecera)
        self.combo_rubro.currentIndexChanged.connect(self._actualizar_cabecera)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        cuerpo.addWidget(self._armar_ficha_de_datos(), 5)
        cuerpo.addWidget(self._armar_tarjeta_de_precio(), 6)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 14)
        layout.setSpacing(12)
        layout.addWidget(self.cabecera)
        layout.addLayout(cuerpo, 1)
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _armar_ficha_de_datos(self) -> QFrame:
        """La ficha blanca de la izquierda: cada dato con su rótulo arriba."""
        ficha = QFrame()
        ficha.setObjectName("fichaArticulo")
        capa = QVBoxLayout(ficha)
        capa.setContentsMargins(16, 14, 16, 14)
        capa.setSpacing(4)
        capa.addWidget(_rotulo("Datos", "seccionFicha"))
        raya = QFrame()
        raya.setObjectName("rayaFicha")
        capa.addWidget(raya)
        for texto, campo in (
            ("Código de barras", self.campo_codigo), ("Descripción", self.campo_descripcion),
            ("Marca", self.combo_marca), ("Rubro", self.combo_rubro), ("Stock mínimo", self.spin_stock_minimo),
        ):
            capa.addSpacing(6)
            capa.addWidget(_rotulo(texto))
            capa.addWidget(campo)
        capa.addStretch()
        return ficha

    def _armar_tarjeta_de_precio(self) -> QFrame:
        """La tarjeta oscura de la derecha: el precio de venta en grande, lo que se
        gana por unidad y la calculadora, un renglón por casillero."""
        tarjeta = QFrame()
        tarjeta.setObjectName("tarjetaPrecio")
        capa = QVBoxLayout(tarjeta)
        capa.setContentsMargins(20, 16, 20, 16)
        capa.setSpacing(6)
        capa.addWidget(_rotulo("Precio de venta", "tituloTarjetaPrecio"))
        self.precio_grande = QLabel()
        self.precio_grande.setObjectName("precioGrande")
        capa.addWidget(self.precio_grande)
        self.ayuda_de_precios = QLabel()
        self.ayuda_de_precios.setObjectName("gananciaGrande")
        self.ayuda_de_precios.setWordWrap(True)
        capa.addWidget(self.ayuda_de_precios)
        capa.addSpacing(10)

        grilla = QGridLayout()
        grilla.setHorizontalSpacing(8)
        grilla.setVerticalSpacing(8)
        for fila, (titulo, campo, boton) in enumerate((
            ("Costo", self.spin_precio_compra, self.boton_calcular_costo),
            ("Ganancia %", self.campo_porcentaje, self.boton_calcular_porcentaje),
            ("Venta", self.spin_precio_venta, self.boton_calcular_venta),
        )):
            grilla.addWidget(_rotulo(titulo, "rotuloTarjetaPrecio"), fila, 0)
            grilla.addWidget(campo, fila, 1)
            grilla.addWidget(boton, fila, 2)
        grilla.setColumnStretch(1, 1)
        capa.addLayout(grilla)
        pista = QLabel(AYUDA_DE_LA_CALCULADORA)
        pista.setObjectName("pistaTarjetaPrecio")
        capa.addWidget(pista)
        capa.addStretch()
        return tarjeta

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
        self._stock_actual = articulo["stock"]
        self.spin_stock_minimo.setValue(articulo["stock_minimo"])

    def _actualizar_cabecera(self):
        """El nombre, el código, la marca y el rubro arriba, como se van escribiendo;
        y el stock actual, en rojo si queda por debajo del mínimo."""
        nombre = self.campo_descripcion.text().strip()
        if self.codigo_existente:
            titulo = nombre or "Modificar artículo"
            partes = [f"Código {self.codigo_existente}", self.combo_marca.currentText().strip()]
            if self.combo_rubro.currentData() is not None:
                partes.append(self.combo_rubro.currentText())
            detalle = "  ·  ".join(parte for parte in partes if parte)
        else:
            titulo = nombre or "Nuevo artículo"
            detalle = "Escaneá el código y completá los datos: el stock se carga desde Compras"
        self.cabecera.titulo.setText(titulo)
        self.cabecera.detalle.setText(detalle)
        if self.indicador_stock is not None:
            minimo = self.spin_stock_minimo.value()
            poner_indicador(self.indicador_stock, dominio.texto_cantidad(self._stock_actual),
                            alerta=dominio.bajo_el_minimo(self._stock_actual, minimo))
            poner_indicador(self.indicador_minimo, dominio.texto_cantidad(minimo))

    def _actualizar_precios(self):
        """El precio de venta en grande y, con los dos precios cargados, cuánto se
        gana (o se pierde) por unidad."""
        costo, venta = self.spin_precio_compra.value(), self.spin_precio_venta.value()
        self.precio_grande.setText(formato_pesos(venta))
        ganancia = dominio.ganancia_por_unidad(costo, venta)
        perdida = costo > 0 and venta > 0 and ganancia < 0
        if perdida:
            texto = f"▼ ¡Se vende por debajo del costo! Perdés {formato_pesos(-ganancia)} por unidad"
        elif costo > 0 and venta > 0:
            texto = f"▲ Ganás {formato_pesos(ganancia)} por unidad"
        else:
            texto = "Con el costo y la venta cargados, acá sale cuánto ganás"
        self.ayuda_de_precios.setText(texto)
        self.ayuda_de_precios.setProperty("alerta", perdida)
        self.ayuda_de_precios.setProperty("apagada", not (costo > 0 and venta > 0))
        self.ayuda_de_precios.style().unpolish(self.ayuda_de_precios)
        self.ayuda_de_precios.style().polish(self.ayuda_de_precios)

    def _calcular_venta_desde_costo(self):
        costo = self.spin_precio_compra.value()
        porcentaje = self.campo_porcentaje.value()
        self.spin_precio_venta.setValue(dominio.precio_con_margen(costo, porcentaje))

    def _calcular_costo_desde_venta(self):
        venta = self.spin_precio_venta.value()
        porcentaje = self.campo_porcentaje.value()
        self.spin_precio_compra.setValue(dominio.costo_sin_margen(venta, porcentaje))

    def _calcular_porcentaje(self):
        """El % que se le gana con el costo y la venta que ya están cargados."""
        costo, venta = self.spin_precio_compra.value(), self.spin_precio_venta.value()
        porcentaje = dominio.porcentaje_de_ganancia(costo, venta)
        if porcentaje is None:
            mostrar_aviso(self, "Calcular la ganancia", "Primero cargá el costo.")
        elif porcentaje < 0:
            mostrar_aviso(self, "Calcular la ganancia",
                          "El precio de venta es menor que el costo: con ese precio se pierde plata.")
        else:
            self.campo_porcentaje.setValue(porcentaje)

    def _resolver_marca(self):
        texto = self.combo_marca.currentText().strip()
        if not texto:
            return None, None
        indice = self.combo_marca.findText(texto)
        if indice >= 0:
            return self.combo_marca.itemData(indice), None
        return None, texto  # el repo la crea junto con el artículo

    @manejar_errores
    def _guardar(self):
        codigo = self.campo_codigo.text().strip()
        descripcion = self.campo_descripcion.text().strip()

        if not codigo or not descripcion:
            mostrar_error(self, "Faltan datos", "El código y la descripción son obligatorios.")
            return

        marca_id, nombre_marca_nueva = self._resolver_marca()
        rubro_id = self.combo_rubro.currentData()  # ya viene resuelto: no es editable

        if self.codigo_existente:
            articulos_repo.modificar_articulo(
                codigo, descripcion, marca_id, rubro_id,
                self.spin_precio_venta.value(), self.spin_precio_compra.value(),
                self.spin_stock_minimo.value(), nombre_marca_nueva=nombre_marca_nueva,
            )
        else:
            if articulos_repo.buscar_por_codigo(codigo):
                mostrar_error(self, "Código repetido", "Ya existe un artículo con ese código.")
                return
            articulos_repo.crear_articulo(
                codigo, descripcion, marca_id, rubro_id,
                self.spin_precio_venta.value(), self.spin_precio_compra.value(),
                self.spin_stock_minimo.value(), nombre_marca_nueva=nombre_marca_nueva,
            )
        self.accept()
