"""
tramites_window.py
====================
Trámites: servicios que se cobran en el mostrador con un monto libre en $
(ej. "Sacar boleta de luz"). Dos pantallas:

- `DialogoTramites`: la que usa cualquiera que atiende. Se elige el trámite
  de la lista, se escribe el monto, se elige el medio de pago y se cobra.
  Si el usuario es Admin, desde acá mismo puede abrir la gestión del catálogo.
- `DialogoGestionTramites` / `DialogoTramite`: alta, edición y baja de los
  trámites del catálogo. Solo Admin (también se abre desde "Configuración
  ADMIN"; ver ui/main_window.py).

La regla de negocio (validar el monto, grabar la venta) vive en
repositories/tramites_repo.py.
"""

from PySide6.QtWidgets import (
    QComboBox, QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton,
    QTableWidgetItem, QVBoxLayout,
)

import dominio
from repositories import tramites_repo
from ui.dialogo_pago import resolver_pagos
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, encadenar_enter, fila_guardar_cancelar, formato_pesos,
    manejar_errores, mostrar_error, mostrar_info, sin_boton_por_defecto,
)


class DialogoTramites(QDialog):
    """Cobro de un trámite: elegir cuál, tipear el monto y cobrar."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self.setWindowTitle("Trámites")
        self.resize(400, 320)
        self._armar_interfaz()
        self._cargar_tramites()

    def _armar_interfaz(self):
        self.combo_tramite = QComboBox()

        self.etiqueta_vacio = QLabel()
        self.etiqueta_vacio.setWordWrap(True)
        self.etiqueta_vacio.setStyleSheet("color: #A6323C;")

        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")

        self.combo_metodo = QComboBox()
        for metodo in (dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL, dominio.PAGO_MIXTO):
            self.combo_metodo.addItem(dominio.NOMBRE_METODO_PAGO[metodo], metodo)

        botones = fila_guardar_cancelar(self, self._cobrar, texto_guardar="Cobrar")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Trámite:"))
        layout.addWidget(self.combo_tramite)
        layout.addWidget(self.etiqueta_vacio)
        layout.addWidget(QLabel("Monto:"))
        layout.addWidget(self.spin_monto)
        layout.addWidget(QLabel("Medio de pago:"))
        layout.addWidget(self.combo_metodo)
        layout.addLayout(botones)
        if self.es_admin:
            boton_gestionar = QPushButton("⚙️  Gestionar trámites")
            boton_gestionar.clicked.connect(self._gestionar)
            layout.addWidget(boton_gestionar)
        self.setLayout(layout)
        encadenar_enter(self.combo_tramite, self.spin_monto, self.combo_metodo, accion_final=self._cobrar)
        sin_boton_por_defecto(self)
        self.spin_monto.setFocus()

    def _cargar_tramites(self):
        """Rellena el combo con los trámites activos, conservando el que
        estaba elegido si sigue existiendo."""
        elegido = self.combo_tramite.currentData()
        self.combo_tramite.clear()
        for tramite in tramites_repo.listar_tramites():
            self.combo_tramite.addItem(tramite["nombre"], tramite["id"])
        indice = self.combo_tramite.findData(elegido)
        if indice >= 0:
            self.combo_tramite.setCurrentIndex(indice)

        if self.combo_tramite.count() == 0:
            self.etiqueta_vacio.setText(
                "Todavía no hay trámites cargados." if self.es_admin
                else "Todavía no hay trámites cargados — pedile a un Administrador que cree uno."
            )
        else:
            self.etiqueta_vacio.setText("")

    def _gestionar(self):
        DialogoGestionTramites(self).exec()
        self._cargar_tramites()

    @manejar_errores
    def _cobrar(self):
        tramite_id = self.combo_tramite.currentData()
        if tramite_id is None:
            mostrar_error(self, "Sin trámite", "Elegí primero un trámite de la lista.")
            return
        monto = self.spin_monto.value()
        if monto <= 0:
            mostrar_error(self, "Monto inválido", "Ingresá un monto mayor a cero.")
            return

        pagos = resolver_pagos(self, self.combo_metodo.currentData(), monto)
        if pagos is None:
            return
        tramites_repo.registrar_tramite(self.usuario["id"], tramite_id, monto, pagos)
        mostrar_info(self, "Trámite cobrado", f"{self.combo_tramite.currentText()}: {formato_pesos(monto)}")
        self.accept()


class DialogoTramite(QDialog):
    """Alta y edición de un trámite del catálogo (solo tiene nombre: el
    monto se tipea cada vez que se cobra)."""

    def __init__(self, parent, tramite=None):
        super().__init__(parent)
        self.tramite = tramite
        self.setWindowTitle("Modificar Trámite" if tramite else "Nuevo Trámite")
        self.resize(340, 140)
        self._armar_interfaz()
        if tramite:
            self.campo_nombre.setText(tramite["nombre"])

    def _armar_interfaz(self):
        self.campo_nombre = QLineEdit()
        self.campo_nombre.setPlaceholderText("Ej: Sacar boleta de luz")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.campo_nombre)
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        encadenar_enter(self.campo_nombre, accion_final=self._guardar)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _guardar(self):
        nombre = self.campo_nombre.text()
        if self.tramite:
            tramites_repo.modificar_tramite(self.tramite["id"], nombre)
        else:
            tramites_repo.crear_tramite(nombre)
        self.accept()


class DialogoGestionTramites(QDialog):
    """Lista de los trámites del catálogo, con Nuevo / Modificar / Desactivar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Trámites")
        self.resize(420, 400)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.tabla = crear_tabla(["Trámite"], estirar=0, por_filas=True, una_sola=True)

        boton_nuevo = QPushButton("Nuevo")
        aplicar_clase(boton_nuevo, "primario")
        boton_nuevo.clicked.connect(self._nuevo)
        boton_modificar = QPushButton("Modificar")
        boton_modificar.clicked.connect(self._modificar)
        boton_desactivar = QPushButton("Desactivar")
        aplicar_clase(boton_desactivar, "peligro")
        boton_desactivar.clicked.connect(self._desactivar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        barra_botones = QHBoxLayout()
        for boton in (boton_nuevo, boton_modificar, boton_desactivar, boton_cerrar):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        self.tramites = tramites_repo.listar_tramites()
        self.tabla.setRowCount(0)
        for tramite in self.tramites:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(tramite["nombre"]))

    def _seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un trámite de la lista.")
            return None
        return self.tramites[fila]

    def _nuevo(self):
        if DialogoTramite(self).exec():
            self._cargar()

    def _modificar(self):
        tramite = self._seleccionado()
        if tramite is None:
            return
        if DialogoTramite(self, tramite).exec():
            self._cargar()

    @manejar_errores
    def _desactivar(self):
        tramite = self._seleccionado()
        if tramite is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar el trámite '{tramite['nombre']}'?\n"
                     "Deja de ofrecerse, pero las ventas ya cobradas no cambian."):
            tramites_repo.desactivar_tramite(tramite["id"])
            self._cargar()
