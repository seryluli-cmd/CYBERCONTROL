"""
usuarios_window.py
=====================
Administración de Usuarios: alta, edición y baja de usuarios (Admin o
Empleada), y la configuración del fondo de cambio fijo que se usa en
los cierres de turno. Todo este módulo es exclusivo del rol ADMIN.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QFormLayout, QHeaderView,
    QDoubleSpinBox, QFileDialog
)
from PySide6.QtCore import Qt

import database
from repositories import usuarios_repo, config_repo
from ui.utils import mostrar_error, confirmar, mostrar_info, manejar_errores, aplicar_clase


class UsuariosWindow(QDialog):
    def __init__(self, usuario_actual, parent=None):
        super().__init__(parent)
        self.usuario_actual = usuario_actual
        self.setWindowTitle("Administración de Usuarios")
        self.resize(650, 480)
        self._armar_interfaz()
        self._cargar_grilla()

    def _armar_interfaz(self):
        barra_botones = QHBoxLayout()
        boton_nuevo = QPushButton("Nuevo")
        boton_nuevo.clicked.connect(self._nuevo_usuario)
        boton_modificar = QPushButton("Modificar")
        boton_modificar.clicked.connect(self._modificar_usuario)
        boton_desactivar = QPushButton("Desactivar")
        boton_desactivar.clicked.connect(self._desactivar_usuario)
        boton_fondo = QPushButton("Configurar Fondo de Cambio")
        boton_fondo.clicked.connect(self._configurar_fondo)
        boton_backup = QPushButton("Copia de Seguridad")
        boton_backup.setToolTip(
            "Copia el archivo de la base de datos a una carpeta a elección "
            "(por ejemplo, un pendrive). El sistema ya guarda una copia "
            "automática por día en data/backups, pero esto sirve para "
            "sacar una copia extra fuera de esta PC."
        )
        boton_backup.clicked.connect(self._hacer_backup)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        aplicar_clase(boton_nuevo, "primario")
        aplicar_clase(boton_desactivar, "peligro")
        for boton in (boton_nuevo, boton_modificar, boton_desactivar, boton_fondo, boton_backup, boton_salir):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Usuario Nº", "Nombre", "Rol"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.doubleClicked.connect(self._modificar_usuario)

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
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
        usuarios = usuarios_repo.listar_usuarios()
        self.tabla.setRowCount(0)
        for usuario in usuarios:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(usuario["id"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(usuario["nombre"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(usuario["rol"]))

    def _id_seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un usuario de la lista.")
            return None
        return int(self.tabla.item(fila, 0).text())

    def _nuevo_usuario(self):
        dialogo = DialogoUsuario(self)
        if dialogo.exec():
            self._cargar_grilla()

    def _modificar_usuario(self):
        usuario_id = self._id_seleccionado()
        if usuario_id is None:
            return
        dialogo = DialogoUsuario(self, usuario_id)
        if dialogo.exec():
            self._cargar_grilla()

    @manejar_errores
    def _desactivar_usuario(self):
        usuario_id = self._id_seleccionado()
        if usuario_id is None:
            return
        if usuario_id == self.usuario_actual["id"]:
            mostrar_error(self, "No permitido", "No podés desactivar tu propio usuario mientras estás logueado.")
            return
        if confirmar(self, "Confirmar", "¿Desactivar este usuario? No va a poder loguearse más, "
                                          "pero su historial de ventas y cierres se conserva."):
            usuarios_repo.desactivar_usuario(usuario_id)
            self._cargar_grilla()

    @manejar_errores
    def _configurar_fondo(self):
        actual = config_repo.obtener_fondo_cambio()
        dialogo = DialogoFondoCambio(self, actual)
        if dialogo.exec():
            config_repo.actualizar_fondo_cambio(dialogo.spin_monto.value())
            mostrar_info(self, "Guardado", "Se actualizó el fondo de cambio.")

    @manejar_errores
    def _hacer_backup(self):
        carpeta = QFileDialog.getExistingDirectory(self, "Elegí dónde guardar la copia de seguridad")
        if not carpeta:
            return
        ruta_final = database.copiar_backup_a(carpeta)
        mostrar_info(self, "Copia guardada", f"Se guardó la copia de seguridad en:\n{ruta_final}")


class DialogoUsuario(QDialog):
    def __init__(self, parent, usuario_id: int = None):
        super().__init__(parent)
        self.usuario_id = usuario_id
        self.setWindowTitle("Modificación de Usuario" if usuario_id else "Nuevo Usuario")
        self.resize(360, 220)
        self._armar_interfaz()
        if usuario_id:
            self._cargar_datos(usuario_id)

    def _armar_interfaz(self):
        self.campo_nombre = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)
        if self.usuario_id:
            self.campo_clave.setPlaceholderText("(dejar vacío para no cambiarla)")
        self.combo_rol = QComboBox()
        self.combo_rol.addItem("Empleada — solo puede vender", "EMPLEADA")
        self.combo_rol.addItem("Admin — acceso completo", "ADMIN")

        formulario = QFormLayout()
        formulario.addRow("Nombre:", self.campo_nombre)
        formulario.addRow("Clave:", self.campo_clave)
        formulario.addRow("Rol:", self.combo_rol)

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
    def _cargar_datos(self, usuario_id):
        usuario = usuarios_repo.obtener_usuario(usuario_id)
        self.campo_nombre.setText(usuario["nombre"])
        indice = self.combo_rol.findData(usuario["rol"])
        if indice >= 0:
            self.combo_rol.setCurrentIndex(indice)

    @manejar_errores
    def _guardar(self):
        nombre = self.campo_nombre.text().strip()
        if not nombre:
            mostrar_error(self, "Falta el nombre", "Ingresá el nombre de la persona.")
            return
        rol = self.combo_rol.currentData()
        clave = self.campo_clave.text()

        if self.usuario_id:
            usuarios_repo.modificar_usuario(self.usuario_id, nombre, rol, clave or None)
        else:
            if not clave:
                mostrar_error(self, "Falta la clave", "Un usuario nuevo necesita una clave.")
                return
            usuarios_repo.crear_usuario(nombre, clave, rol)
        self.accept()


class DialogoFondoCambio(QDialog):
    def __init__(self, parent, valor_actual: float):
        super().__init__(parent)
        self.setWindowTitle("Fondo de Cambio")
        self.resize(320, 140)

        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        self.spin_monto.setValue(valor_actual)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self.accept)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Fondo de cambio fijo que arranca cada turno:"))
        layout.addWidget(self.spin_monto)
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
