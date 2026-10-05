"""
usuarios_window.py
=====================
Administración de Usuarios: alta, edición y baja de usuarios (Admin o
Empleada), la configuración del fondo de cambio fijo que se usa en los
cierres de turno y la copia de seguridad manual. Es exclusivo del rol ADMIN
(no se delega con ningún permiso), con una excepción: DialogoCambiarClave,
que vive acá pero la usa cualquier usuario para su propia clave.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QFormLayout, QHeaderView,
    QDoubleSpinBox, QFileDialog, QCheckBox, QGroupBox
)

import dominio
import database
from repositories import usuarios_repo, config_repo
from ui.utils import (
    mostrar_error, confirmar, mostrar_info, manejar_errores, aplicar_clase, encadenar_enter,
    sin_boton_por_defecto,
)


class UsuariosWindow(QDialog):
    """Grilla de usuarios con alta/modificación/baja, fondo de cambio y
    backup. `usuario_actual` es quien está logueado (no puede borrarse a
    sí mismo)."""

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
        boton_borrar = QPushButton("Borrar")
        boton_borrar.clicked.connect(self._borrar_usuario)
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
        aplicar_clase(boton_borrar, "peligro")
        for boton in (boton_nuevo, boton_modificar, boton_borrar, boton_fondo, boton_backup, boton_salir):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        # Los usuarios desactivados no aparecen en la grilla por defecto, así
        # que sin este check no habría forma de encontrarlos para borrarlos
        # del todo y liberar su número.
        self.check_inactivos = QCheckBox("Mostrar inactivos")
        self.check_inactivos.stateChanged.connect(self._cargar_grilla)

        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Usuario Nº", "Nombre", "Rol", "Estado"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.doubleClicked.connect(self._modificar_usuario)

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.check_inactivos)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar_grilla(self):
        usuarios = usuarios_repo.listar_usuarios(incluir_inactivos=self.check_inactivos.isChecked())
        self.tabla.setRowCount(0)
        for usuario in usuarios:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(usuario["id"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(usuario["nombre"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(usuario["rol"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem("Activo" if usuario["activo"] else "Inactivo"))

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
    def _borrar_usuario(self):
        usuario_id = self._id_seleccionado()
        if usuario_id is None:
            return
        if usuario_id == self.usuario_actual["id"]:
            mostrar_error(self, "No permitido", "No podés borrar tu propio usuario mientras estás logueado.")
            return
        if not confirmar(self, "Confirmar", "¿Borrar este usuario? Si nunca vendió, compró ni cerró un "
                                             "turno, se borra del todo y su número queda libre para el "
                                             "próximo usuario que se cree."):
            return

        try:
            usuarios_repo.borrar_usuario(usuario_id)
            self._cargar_grilla()
        except ValueError as error:
            # Ya tiene historial real (ventas/compras/cierres): no se
            # puede borrar sin perderlo. Se ofrece desactivar en su
            # lugar, con una confirmación aparte, en vez de fallar y
            # dejar a la usuaria sin ninguna forma de sacarle el acceso.
            if confirmar(self, "No se puede borrar del todo",
                         f"{error}\n\n¿Desactivarlo en su lugar? Deja de poder loguearse, "
                         "pero su número de usuario queda reservado (no se reutiliza)."):
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
    """Alta (sin `usuario_id`) o edición de un usuario: nombre, clave, rol
    y, para una Empleada, sus permisos extra."""

    def __init__(self, parent, usuario_id: int = None):
        super().__init__(parent)
        self.usuario_id = usuario_id
        self.setWindowTitle("Modificación de Usuario" if usuario_id else "Nuevo Usuario")
        self.resize(400, 380)
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
        self.combo_rol.addItem("Empleada — según los permisos de abajo", dominio.ROL_EMPLEADA)
        self.combo_rol.addItem("Admin — acceso completo", dominio.ROL_ADMIN)
        self.combo_rol.currentIndexChanged.connect(self._actualizar_visibilidad_permisos)

        formulario = QFormLayout()
        formulario.addRow("Nombre:", self.campo_nombre)
        formulario.addRow("Clave:", self.campo_clave)
        formulario.addRow("Rol:", self.combo_rol)

        # Permisos extra para una Empleada, además de lo que ya puede
        # hacer cualquiera (Ventas/Caja/Cierre de Turno/Cambiar mi
        # Clave) — un Admin ya tiene todo esto siempre, así que la
        # sección se oculta cuando el Rol de arriba es Admin (ver
        # _actualizar_visibilidad_permisos).
        self.checks_permisos = {}
        self.grupo_permisos = QGroupBox("Permisos extra (Empleada)")
        layout_permisos = QVBoxLayout()
        for columna, etiqueta in usuarios_repo.PERMISOS_EMPLEADA:
            check = QCheckBox(etiqueta)
            layout_permisos.addWidget(check)
            self.checks_permisos[columna] = check
        self.grupo_permisos.setLayout(layout_permisos)

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
        layout.addWidget(self.grupo_permisos)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_nombre, self.campo_clave, self.combo_rol, accion_final=self._guardar)
        self._actualizar_visibilidad_permisos()
        sin_boton_por_defecto(self)

    def _actualizar_visibilidad_permisos(self):
        """Un Admin ya tiene acceso a todo (ver usuarios_repo.tiene_permiso),
        así que la sección de permisos solo tiene sentido — y solo se
        muestra — para el rol Empleada."""
        self.grupo_permisos.setVisible(self.combo_rol.currentData() == dominio.ROL_EMPLEADA)

    @manejar_errores
    def _cargar_datos(self, usuario_id):
        usuario = usuarios_repo.obtener_usuario(usuario_id)
        self.campo_nombre.setText(usuario["nombre"])
        indice = self.combo_rol.findData(usuario["rol"])
        if indice >= 0:
            self.combo_rol.setCurrentIndex(indice)
        for columna, check in self.checks_permisos.items():
            check.setChecked(bool(usuario[columna]))
        self._actualizar_visibilidad_permisos()

    @manejar_errores
    def _guardar(self):
        nombre = self.campo_nombre.text().strip()
        if not nombre:
            mostrar_error(self, "Falta el nombre", "Ingresá el nombre de la persona.")
            return
        rol = self.combo_rol.currentData()
        clave = self.campo_clave.text()
        permisos = {columna: check.isChecked() for columna, check in self.checks_permisos.items()}

        if self.usuario_id:
            usuarios_repo.modificar_usuario(self.usuario_id, nombre, rol, clave or None, permisos)
        else:
            if not clave:
                mostrar_error(self, "Falta la clave", "Un usuario nuevo necesita una clave.")
                return
            usuarios_repo.crear_usuario(nombre, clave, rol, permisos)
        self.accept()


class DialogoFondoCambio(QDialog):
    """Pide el monto del fondo de cambio; quien lo abre lo lee de
    `spin_monto` si se aceptó (ver UsuariosWindow._configurar_fondo)."""

    def __init__(self, parent, valor_actual: float):
        super().__init__(parent)
        self.setWindowTitle("Fondo de Cambio")
        self.resize(320, 140)

        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        self.spin_monto.setValue(valor_actual)
        encadenar_enter(self.spin_monto, accion_final=self.accept)

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
        sin_boton_por_defecto(self)


class DialogoCambiarClave(QDialog):
    """Para que cualquier usuario logueado (Admin o Empleada) cambie su
    propia clave — a diferencia de DialogoUsuario, que es Admin-only y
    puede resetear la clave de cualquier otra persona sin pedir la
    vieja. Se abre desde el menú principal, no desde esta pantalla."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Cambiar mi Clave")
        self.resize(340, 220)
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.campo_actual = QLineEdit()
        self.campo_actual.setEchoMode(QLineEdit.Password)
        self.campo_nueva = QLineEdit()
        self.campo_nueva.setEchoMode(QLineEdit.Password)
        self.campo_confirmar = QLineEdit()
        self.campo_confirmar.setEchoMode(QLineEdit.Password)

        formulario = QFormLayout()
        formulario.addRow("Clave actual:", self.campo_actual)
        formulario.addRow("Clave nueva:", self.campo_nueva)
        formulario.addRow("Confirmar clave nueva:", self.campo_confirmar)
        encadenar_enter(self.campo_actual, self.campo_nueva, self.campo_confirmar, accion_final=self._guardar)

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
        sin_boton_por_defecto(self)

    @manejar_errores
    def _guardar(self):
        actual = self.campo_actual.text()
        nueva = self.campo_nueva.text()
        confirmar_clave = self.campo_confirmar.text()

        if not actual or not nueva:
            mostrar_error(self, "Faltan datos", "Completá la clave actual y la nueva.")
            return
        if nueva != confirmar_clave:
            mostrar_error(self, "No coinciden", "La clave nueva y su confirmación no son iguales.")
            return

        usuarios_repo.cambiar_clave(self.usuario["id"], actual, nueva)
        mostrar_info(self, "Listo", "Tu clave se actualizó correctamente.")
        self.accept()
