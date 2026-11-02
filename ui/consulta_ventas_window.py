"""
consulta_ventas_window.py
============================
Pantalla de Consulta de Ventas: muestra las últimas ventas cargadas, con
su detalle. La ve el Admin o una Empleada con `permiso_consulta_ventas`,
pero solo el Admin puede "Anular" una venta ya confirmada desde acá (a
propósito no es delegable: es por donde se podría "arreglar" una caja).
Anular repone el stock automáticamente y deja registrado quién la anuló,
cuándo y por qué (nunca se borra el registro original).
"""

from PySide6.QtWidgets import QVBoxLayout, QHBoxLayout, QTableWidgetItem, QInputDialog
from PySide6.QtCore import Qt

import dominio
from repositories import ventas_repo
from control_pcs.repositories import miembros_repo
from control_pcs.ui.anular_carga import anular_carga_con_cartel
from ui.detalle_venta import VentanaConDetalleDeVenta, crear_tabla_detalle_venta, etiqueta_de_estado
from ui.dibujos_tabla import DelegadoEtiqueta
from ui.piezas_ventana import (
    agregar_indicador, buscador, cabecera_oscura, fila_de_filtros, marcar_solo_admin, panel_de_tabla,
    pie_de_ventana, poner_indicador, tecla, titulo_de_seccion,
)
from ui.utils import (
    formato_pesos, formato_fecha_hora, mostrar_error, mostrar_info, confirmar, manejar_errores,
    sin_boton_por_defecto, crear_tabla,
)

# Las ventas que se traen: las últimas, de la más nueva a la más vieja.
CANTIDAD_DE_VENTAS = 100

_COLUMNA_FACTURA = 0
_COLUMNA_FECHA = 1
_COLUMNA_TURNO = 2
_COLUMNA_ORIGEN = 3
_COLUMNA_VENDEDOR = 4
_COLUMNA_TOTAL = 5
_COLUMNA_ESTADO = 6


class ConsultaVentasWindow(VentanaConDetalleDeVenta):
    """Lista de las últimas 100 ventas y, al lado, los artículos de la elegida.

    Con la maqueta B que eligió el dueño el 2026-10-30 (ui/piezas_ventana.py, el
    modelo es ArticulosWindow): la cabecera oscura con cuántas ventas hay en la
    lista y cuántas están anuladas, las teclas, el buscador con los filtros por
    estado y las dos grillas en sus paneles, con el turno y el estado en etiquetas
    de color. Buscar y filtrar miran solo las ventas ya traídas: no van a la base."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self._todas = []
        self._estado_elegido = None
        self.setWindowTitle("Consulta de Ventas")
        # Más ancha que en el kiosko por la columna Origen: con 1240 Vendedor quedaba
        # en "Ve" y la lista se corría de costado.
        self.resize(1460, 700)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura(
            "🔍", "Consulta de Ventas",
            "Las últimas ventas y qué se llevó cada una"
            + (" · el Administrador las puede anular" if self.es_admin else ""),
        )
        self.indicador_ventas = agregar_indicador(cabecera, "Ventas")
        self.indicador_anuladas = agregar_indicador(cabecera, "Anuladas")

        barra_botones = QHBoxLayout()
        barra_botones.setSpacing(8)
        self.boton_refrescar = tecla("⟳  REFRESCAR", self._cargar)
        barra_botones.addWidget(self.boton_refrescar)
        if self.es_admin:
            self.boton_anular = tecla("✕  ANULAR VENTA", self._anular, "teclaRoja")
            marcar_solo_admin(self.boton_anular)
            barra_botones.addWidget(self.boton_anular)
        barra_botones.addStretch()
        self.boton_salir = tecla("SALIR", self.close)
        barra_botones.addWidget(self.boton_salir)

        self.campo_buscar = buscador("Buscar por Nº de factura o vendedor...")
        self.campo_buscar.setMinimumWidth(380)
        self.campo_buscar.textChanged.connect(self._mostrar_lista)
        self.filtros = fila_de_filtros(
            [("Confirmadas", dominio.VENTA_CONFIRMADA), ("Anuladas", dominio.VENTA_ANULADA)],
            self._elegir_estado, todos="Todas",
        )
        fila_buscar = QHBoxLayout()
        fila_buscar.setSpacing(12)
        fila_buscar.addWidget(self.campo_buscar)
        fila_buscar.addWidget(self.filtros, 1)

        self.tabla = crear_tabla(
            ["Nº Factura", "Fecha", "Turno", "Origen", "Vendedor", "Total", "Estado"],
            estirar=_COLUMNA_VENDEDOR, por_filas=True,
        )
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)
        self.etiqueta_turno = DelegadoEtiqueta(self.tabla)
        self.etiqueta_turno.colores_en_orden(dominio.TURNOS)
        self.tabla.setItemDelegateForColumn(_COLUMNA_TURNO, self.etiqueta_turno)
        # El negocio de la venta (Kiosko, Alquiler de PCs...) también en etiqueta.
        self.etiqueta_origen = DelegadoEtiqueta(self.tabla)
        self.etiqueta_origen.colores_en_orden(dominio.NOMBRE_ORIGEN_VENTA.values())
        self.tabla.setItemDelegateForColumn(_COLUMNA_ORIGEN, self.etiqueta_origen)
        self.etiqueta_estado = etiqueta_de_estado(self.tabla, _COLUMNA_ESTADO)
        for columna, ancho in ((_COLUMNA_FACTURA, 100), (_COLUMNA_FECHA, 140), (_COLUMNA_TURNO, 100),
                               (_COLUMNA_ORIGEN, 150), (_COLUMNA_TOTAL, 100)):
            self.tabla.setColumnWidth(columna, ancho)

        self.tabla_detalle = crear_tabla_detalle_venta()

        columna_ventas = QVBoxLayout()
        columna_ventas.setSpacing(6)
        columna_ventas.addWidget(titulo_de_seccion("Ventas · la más nueva arriba"))
        columna_ventas.addWidget(panel_de_tabla(self.tabla), 1)
        columna_detalle = QVBoxLayout()
        columna_detalle.setSpacing(6)
        columna_detalle.addWidget(titulo_de_seccion("Qué se llevó en la venta elegida"))
        columna_detalle.addWidget(panel_de_tabla(self.tabla_detalle), 1)
        columnas = QHBoxLayout()
        columnas.setSpacing(14)
        columnas.addLayout(columna_ventas, 3)
        columnas.addLayout(columna_detalle, 2)

        ayuda = "Elegí una venta para ver sus artículos  ·  Buscar y filtrar miran solo esta lista"
        if self.es_admin:
            ayuda += "  ·  Anular repone el stock y deja anotado quién, cuándo y por qué"

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(barra_botones)
        layout.addLayout(fila_buscar)
        layout.addLayout(columnas, 1)
        layout.addWidget(pie_de_ventana(ayuda))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _elegir_estado(self, estado):
        self._estado_elegido = estado
        self._mostrar_lista()

    @manejar_errores
    def _cargar(self):
        self._todas = ventas_repo.listar_ventas_recientes(CANTIDAD_DE_VENTAS)
        # Los números de arriba son de todas las ventas traídas, no de lo que se busca.
        anuladas = sum(1 for venta in self._todas if venta["estado"] == dominio.VENTA_ANULADA)
        poner_indicador(self.indicador_ventas, str(len(self._todas)))
        poner_indicador(self.indicador_anuladas, str(anuladas), alerta=anuladas > 0)
        self._mostrar_lista()

    def _mostrar_lista(self, _=None):
        # El "_=None" absorbe el texto que manda `textChanged`. `self.ventas` queda
        # con las filas que se ven y en su orden: de ahí sale la venta elegida.
        texto = dominio.sin_acentos(self.campo_buscar.text().strip())
        self.ventas = [
            venta for venta in self._todas
            if (self._estado_elegido is None or venta["estado"] == self._estado_elegido)
            and (not texto or texto in str(venta["id"]) or texto in dominio.sin_acentos(venta["vendedor"]))
        ]
        self.tabla.setRowCount(0)
        for venta in self.ventas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, _COLUMNA_FACTURA, QTableWidgetItem(str(venta["id"])))
            self.tabla.setItem(fila, _COLUMNA_FECHA, QTableWidgetItem(formato_fecha_hora(venta["fecha"])))
            self.tabla.setItem(fila, _COLUMNA_TURNO, QTableWidgetItem(venta["turno"]))
            self.tabla.setItem(fila, _COLUMNA_ORIGEN, QTableWidgetItem(dominio.NOMBRE_ORIGEN_VENTA[venta["origen"]]))
            self.tabla.setItem(fila, _COLUMNA_VENDEDOR, QTableWidgetItem(venta["vendedor"]))
            self.tabla.setItem(fila, _COLUMNA_TOTAL, QTableWidgetItem(formato_pesos(venta["total"])))
            item_estado = QTableWidgetItem(venta["estado"])
            if venta["estado"] == dominio.VENTA_ANULADA:
                item_estado.setForeground(Qt.red)
            self.tabla.setItem(fila, _COLUMNA_ESTADO, item_estado)
        self.tabla_detalle.setRowCount(0)

    @manejar_errores
    def _anular(self):
        venta = self._venta_seleccionada()
        if venta is None:
            mostrar_error(self, "Nada seleccionado", "Elegí primero una venta de la lista.")
            return
        if venta["estado"] == dominio.VENTA_ANULADA:
            mostrar_error(self, "Ya anulada", "Esa venta ya estaba anulada.")
            return

        # La venta que cargó saldo a un socio se anula con su propio cartel, que dice
        # qué pasa con la plata y con el tiempo del socio (y si está jugando, con su
        # PC): el mismo que el botón "Anular carga" del Historial de Cargas.
        if venta["origen"] == dominio.ORIGEN_ALQUILER_PCS and miembros_repo.resumen_de_carga(venta["id"]):
            if anular_carga_con_cartel(self, self.usuario, venta["id"]):
                self._cargar()
            return

        if not confirmar(self, "Anular venta",
                          f"¿Anular la venta Nº {venta['id']} por {formato_pesos(venta['total'])}?\n"
                          "El stock de los artículos se repone automáticamente."):
            return

        motivo, aceptado = QInputDialog.getText(
            self, "Motivo de la anulación", "Contá brevemente por qué se anula esta venta:"
        )
        if not aceptado or not motivo.strip():
            mostrar_error(self, "Falta el motivo", "Tenés que indicar un motivo para anular la venta.")
            return

        # Una venta de "Alquiler de PCs" puede ser una carga de saldo de
        # socio -- esa sí necesita revertir los minutos ya acreditados,
        # no solo cambiar el estado de la venta (ver
        # miembros_repo.anular_carga). Las de Kiosko y las de PlayStation 5
        # nunca cargan saldo, así que siguen con el camino simple de siempre
        # (anular la venta de la consola no corta su cuenta regresiva: se la
        # libera aparte, desde Control de PCs, como con un bono de PC).
        if venta["origen"] == dominio.ORIGEN_ALQUILER_PCS:
            miembros_repo.anular_carga(venta["id"], self.usuario["id"], motivo.strip())
        else:
            ventas_repo.anular_venta(venta["id"], self.usuario["id"], motivo.strip())
        mostrar_info(self, "Venta anulada", f"Se anuló la venta Nº {venta['id']}.")
        self._cargar()
