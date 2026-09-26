"""
miembros_window.py
====================
Administración de Miembros (socios con saldo prepago de tiempo): alta,
edición y baja de cuentas, y la carga de saldo — que siempre hace el
Operador, porque implica cobrar plata (a diferencia de "Abrir PC con
Miembro" en pcs_window.py, que es autoservicio del socio). También la
configuración de la tarifa $/hora usada para convertir un pago en
minutos (ver config_repo.obtener_tarifa_hora_miembro).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QCheckBox, QFormLayout,
    QHeaderView, QDoubleSpinBox, QStackedWidget, QWidget
)

from repositories import config_repo, miembros_repo, pcs_repo
from ui.utils import (
    formato_pesos, formato_tiempo, mostrar_error, mostrar_info, confirmar, manejar_errores,
    aplicar_clase, encadenar_enter,
)


class MiembrosWindow(QDialog):
    def __init__(self, usuario_operador, parent=None):
        super().__init__(parent)
        self.usuario_operador = usuario_operador
        self.setWindowTitle("Administración de Miembros")
        self.resize(700, 480)
        self._armar_interfaz()
        self._cargar_grilla()

    def _armar_interfaz(self):
        barra_botones = QHBoxLayout()
        boton_nuevo = QPushButton("Nuevo")
        aplicar_clase(boton_nuevo, "primario")
        boton_nuevo.clicked.connect(self._nuevo_miembro)
        boton_modificar = QPushButton("Modificar")
        boton_modificar.clicked.connect(self._modificar_miembro)
        boton_cargar_saldo = QPushButton("Cargar Saldo")
        aplicar_clase(boton_cargar_saldo, "primario")
        boton_cargar_saldo.clicked.connect(self._cargar_saldo)
        boton_desactivar = QPushButton("Desactivar")
        aplicar_clase(boton_desactivar, "peligro")
        boton_desactivar.clicked.connect(self._desactivar_miembro)
        boton_tarifa = QPushButton("Configurar Tarifa por Hora")
        boton_tarifa.clicked.connect(self._configurar_tarifa)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        for boton in (boton_nuevo, boton_modificar, boton_cargar_saldo,
                      boton_desactivar, boton_tarifa, boton_salir):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        self.check_inactivos = QCheckBox("Mostrar inactivos")
        self.check_inactivos.stateChanged.connect(self._cargar_grilla)

        self.tabla = QTableWidget(0, 6)
        self.tabla.setHorizontalHeaderLabels(["Usuario", "Nombre", "DNI", "Teléfono", "Saldo", "Estado"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.doubleClicked.connect(self._modificar_miembro)

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.check_inactivos)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _cargar_grilla(self):
        self.miembros = miembros_repo.listar_miembros(incluir_inactivos=self.check_inactivos.isChecked())
        self.tabla.setRowCount(0)
        for miembro in self.miembros:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(miembro["usuario"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(miembro["nombre"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(miembro["dni"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(miembro["telefono"]))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_tiempo(miembro["saldo_minutos"] * 60)))
            self.tabla.setItem(fila, 5, QTableWidgetItem("Activo" if miembro["activo"] else "Inactivo"))

    def _seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un socio de la lista.")
            return None
        return self.miembros[fila]

    def _nuevo_miembro(self):
        if DialogoMiembro(self).exec():
            self._cargar_grilla()

    def _modificar_miembro(self):
        miembro = self._seleccionado()
        if miembro is None:
            return
        if DialogoMiembro(self, miembro).exec():
            self._cargar_grilla()

    def _cargar_saldo(self):
        miembro = self._seleccionado()
        if miembro is None:
            return
        if DialogoCargarSaldo(self.usuario_operador, miembro, self).exec():
            self._cargar_grilla()

    @manejar_errores
    def _desactivar_miembro(self):
        miembro = self._seleccionado()
        if miembro is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar a '{miembro['nombre']}'? Deja de poder loguearse para abrir "
                     "PCs, pero su saldo e historial se conservan."):
            miembros_repo.desactivar_miembro(miembro["id"])
            self._cargar_grilla()

    @manejar_errores
    def _configurar_tarifa(self):
        actual = config_repo.obtener_tarifa_hora_miembro()
        dialogo = DialogoTarifaMiembro(self, actual)
        if dialogo.exec():
            config_repo.actualizar_tarifa_hora_miembro(dialogo.spin_tarifa.value())
            mostrar_info(self, "Guardado", "Se actualizó la tarifa por hora para socios.")


class DialogoMiembro(QDialog):
    def __init__(self, parent, miembro=None):
        super().__init__(parent)
        self.miembro = miembro
        self.setWindowTitle("Modificar Miembro" if miembro else "Nuevo Miembro")
        self.resize(380, 380)
        self._armar_interfaz()
        if miembro:
            self._cargar_datos(miembro)

    def _armar_interfaz(self):
        self.campo_usuario = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)
        if self.miembro:
            self.campo_clave.setPlaceholderText("(dejar vacío para no cambiarla)")
        self.campo_nombre = QLineEdit()
        self.campo_dni = QLineEdit()
        self.campo_telefono = QLineEdit()
        self.campo_email = QLineEdit()
        self.campo_email.setPlaceholderText("(opcional)")

        formulario = QFormLayout()
        formulario.addRow("Usuario:", self.campo_usuario)
        formulario.addRow("Contraseña:", self.campo_clave)
        formulario.addRow("Nombre:", self.campo_nombre)
        formulario.addRow("DNI:", self.campo_dni)
        formulario.addRow("Teléfono:", self.campo_telefono)
        formulario.addRow("Email:", self.campo_email)

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
        encadenar_enter(self.campo_usuario, self.campo_clave, self.campo_nombre, self.campo_dni,
                         self.campo_telefono, self.campo_email, accion_final=self._guardar)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _cargar_datos(self, miembro):
        self.campo_usuario.setText(miembro["usuario"])
        self.campo_nombre.setText(miembro["nombre"])
        self.campo_dni.setText(miembro["dni"])
        self.campo_telefono.setText(miembro["telefono"])
        self.campo_email.setText(miembro["email"] or "")

    @manejar_errores
    def _guardar(self):
        usuario = self.campo_usuario.text().strip()
        nombre = self.campo_nombre.text().strip()
        dni = self.campo_dni.text().strip()
        telefono = self.campo_telefono.text().strip()
        email = self.campo_email.text().strip() or None
        clave = self.campo_clave.text()

        if self.miembro:
            miembros_repo.modificar_miembro(self.miembro["id"], usuario, nombre, dni, telefono,
                                             email, clave or None)
        else:
            if not clave:
                mostrar_error(self, "Falta la contraseña", "Un socio nuevo necesita una contraseña.")
                return
            miembros_repo.crear_miembro(usuario, clave, nombre, dni, telefono, email)
        self.accept()


class DialogoCargarSaldo(QDialog):
    """Dos formas de cargar saldo: un monto libre en $ (convertido a
    minutos según config_repo.obtener_tarifa_hora_miembro) o uno de los
    bonos fijos del mismo catálogo que se usa para venderle tiempo a un
    walk-in (pcs_repo.listar_bonos) — siempre lo hace el Operador, porque
    implica cobrar plata."""

    def __init__(self, usuario_operador, miembro, parent=None):
        super().__init__(parent)
        self.usuario_operador = usuario_operador
        self.miembro = miembro
        self.setWindowTitle(f"Cargar Saldo — {miembro['nombre']}")
        self.resize(380, 300)
        self._armar_interfaz()

    def _armar_interfaz(self):
        etiqueta_saldo = QLabel(
            f"Saldo actual: {formato_tiempo(self.miembro['saldo_minutos'] * 60)}"
        )

        self.combo_modo = QComboBox()
        self.combo_modo.addItem("Monto en $", "MONTO")
        self.combo_modo.addItem("Bono fijo", "BONO")
        self.combo_modo.currentIndexChanged.connect(self._actualizar_modo)

        # --- Modo Monto ---
        self.tarifa_hora = config_repo.obtener_tarifa_hora_miembro()
        pagina_monto = QWidget()
        layout_monto = QVBoxLayout()
        layout_monto.addWidget(QLabel(f"Tarifa actual: {formato_pesos(self.tarifa_hora)} / hora"))
        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        self.spin_monto.valueChanged.connect(self._actualizar_preview_monto)
        self.etiqueta_preview_monto = QLabel()
        layout_monto.addWidget(self.spin_monto)
        layout_monto.addWidget(self.etiqueta_preview_monto)
        pagina_monto.setLayout(layout_monto)

        # --- Modo Bono ---
        pagina_bono = QWidget()
        layout_bono = QVBoxLayout()
        self.combo_bono = QComboBox()
        self.bonos = pcs_repo.listar_bonos()
        for bono in self.bonos:
            self.combo_bono.addItem(f"{bono['nombre']} — {formato_pesos(bono['precio'])}", bono["id"])
        layout_bono.addWidget(self.combo_bono)
        pagina_bono.setLayout(layout_bono)

        self.paginas = QStackedWidget()
        self.paginas.addWidget(pagina_monto)
        self.paginas.addWidget(pagina_bono)

        self.combo_metodo = QComboBox()
        self.combo_metodo.addItem("Efectivo", "EFECTIVO")
        self.combo_metodo.addItem("Digital (Mercado Pago / Transferencia)", "DIGITAL")

        boton_confirmar = QPushButton("Cobrar y cargar saldo")
        aplicar_clase(boton_confirmar, "primario")
        boton_confirmar.clicked.connect(self._confirmar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_confirmar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(etiqueta_saldo)
        layout.addWidget(QLabel("Forma de carga:"))
        layout.addWidget(self.combo_modo)
        layout.addWidget(self.paginas)
        layout.addWidget(QLabel("Medio de pago:"))
        layout.addWidget(self.combo_metodo)
        layout.addLayout(botones)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)
        self._actualizar_preview_monto()

    def _actualizar_modo(self):
        self.paginas.setCurrentIndex(self.combo_modo.currentIndex())

    def _actualizar_preview_monto(self):
        minutos = int((self.spin_monto.value() / self.tarifa_hora * 60) // 30) * 30
        self.etiqueta_preview_monto.setText(f"Equivale a {formato_tiempo(minutos * 60)} de saldo.")

    @manejar_errores
    def _confirmar(self):
        metodo = self.combo_metodo.currentData()
        if self.combo_modo.currentData() == "MONTO":
            miembros_repo.cargar_saldo_por_monto(
                self.miembro["id"], self.spin_monto.value(), metodo, self.usuario_operador["id"]
            )
        else:
            if not self.bonos:
                mostrar_error(self, "Sin bonos", "Todavía no hay ningún bono de tiempo cargado — "
                                                  "creá uno primero desde 'Gestionar Bonos'.")
                return
            bono_id = self.combo_bono.currentData()
            miembros_repo.cargar_saldo_por_bono(
                self.miembro["id"], bono_id, metodo, self.usuario_operador["id"]
            )
        self.accept()


class DialogoTarifaMiembro(QDialog):
    def __init__(self, parent, valor_actual: float):
        super().__init__(parent)
        self.setWindowTitle("Tarifa por Hora para Socios")
        self.resize(320, 140)

        self.spin_tarifa = QDoubleSpinBox()
        self.spin_tarifa.setMaximum(99_999_999)
        self.spin_tarifa.setPrefix("$ ")
        self.spin_tarifa.setValue(valor_actual)
        encadenar_enter(self.spin_tarifa, accion_final=self.accept)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self.accept)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Cuánto vale una hora de saldo al cargar por monto:"))
        layout.addWidget(self.spin_tarifa)
        layout.addLayout(botones)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)
