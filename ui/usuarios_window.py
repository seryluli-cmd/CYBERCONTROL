"""
usuarios_window.py
=====================
Administración de Usuarios: alta, edición y baja de usuarios (Admin o
Empleada), la configuración del Cambio Fijo (fondo de cambio) que se usa en los
cierres de turno y las copias de seguridad (ui/copias_dialogo.py). Es exclusivo del rol ADMIN
(no se delega con ningún permiso), con una excepción: DialogoCambiarClave,
que vive acá pero la usa cualquier usuario para su propia clave.
"""

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QLineEdit, QLabel,
    QComboBox, QFormLayout, QCheckBox,
)

import dominio
from admin_remoto import modo as modo_remoto
from repositories import usuarios_repo, config_repo
from ui.copias_dialogo import DialogoCopiasDeSeguridad
from ui.dibujos_tabla import DelegadoEtiqueta
from ui.piezas_ventana import (
    agregar_indicador, cabecera_oscura, panel_blanco, panel_de_tabla, pie_de_ventana, poner_indicador, tecla,
    titulo_de_seccion,
)
from ui.utils import (
    CampoPesos, mostrar_error, confirmar, mostrar_info, manejar_errores,
    encadenar_enter, sin_boton_por_defecto, fila_guardar_cancelar, crear_tabla,
)

COLUMNA_ROL = 2
COLUMNA_ESTADO = 3
# Un usuario dado de baja se ve apagado: sigue en la lista para poder borrarlo del todo.
_COLOR_INACTIVO = QColor("#A7ADB8")


class UsuariosWindow(QDialog):
    """Grilla de usuarios con alta/modificación/baja, Cambio Fijo y
    copias de seguridad. `usuario_actual` es quien está logueado (no puede borrarse a
    sí mismo).

    Con la maqueta B que eligió el dueño el 2026-10-30 (como Artículos): la cabecera
    oscura con cuántos usuarios activos hay y de qué rol, las teclas, la grilla con el
    rol en una etiqueta de color y una línea de ayuda abajo."""

    def __init__(self, usuario_actual, parent=None):
        super().__init__(parent)
        self.usuario_actual = usuario_actual
        self.setWindowTitle("Administración de Usuarios")
        self.resize(1000, 640)
        self._armar_interfaz()
        self._cargar_grilla()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura("👤", "Usuarios", "Quién entra, claves, permisos y copias")
        self.indicador_activos = agregar_indicador(cabecera, "Activos")
        self.indicador_admins = agregar_indicador(cabecera, "Administradores")
        self.indicador_empleadas = agregar_indicador(cabecera, "Empleadas")

        barra_botones = QHBoxLayout()
        barra_botones.setSpacing(8)
        self.boton_nuevo = tecla("＋  NUEVO", self._nuevo_usuario, "teclaAzul")
        self.boton_modificar = tecla("✎  MODIFICAR", self._modificar_usuario)
        self.boton_cambio_fijo = tecla("＄  CAMBIO FIJO", self._configurar_fondo)
        self.boton_copias = tecla("⎘  COPIAS DE SEGURIDAD", self._abrir_copias)
        self.boton_copias.setToolTip(
            "Cuándo se hacen solas las copias de la base, cuál es la última, las "
            "otras carpetas donde se guardan, hacer una copia ahora o una suelta a un pendrive."
        )
        self.boton_borrar = tecla("✕  BORRAR", self._borrar_usuario, "teclaRoja")
        self.boton_salir = tecla("SALIR", self.close)
        botones = [self.boton_nuevo, self.boton_modificar, self.boton_cambio_fijo, self.boton_copias,
                   self.boton_borrar]
        # Las copias son del archivo de la base de ESTA PC: desde otra PC
        # (admin_remoto/) no hay ninguno, se hacen en el mostrador.
        if modo_remoto.es_copia_remota():
            botones.remove(self.boton_copias)
            self.boton_copias.deleteLater()
        for boton in botones:
            barra_botones.addWidget(boton)
        barra_botones.addStretch()
        barra_botones.addWidget(self.boton_salir)

        # Los usuarios desactivados no aparecen en la grilla por defecto, así
        # que sin este check no habría forma de encontrarlos para borrarlos
        # del todo y liberar su número.
        self.check_inactivos = QCheckBox("Mostrar inactivos")
        self.check_inactivos.stateChanged.connect(self._cargar_grilla)
        fila_inactivos = QHBoxLayout()
        fila_inactivos.addWidget(self.check_inactivos)
        fila_inactivos.addStretch()

        self.tabla = crear_tabla(["Usuario Nº", "Nombre", "Rol", "Estado"], estirar=1, por_filas=True)
        self.tabla.doubleClicked.connect(self._modificar_usuario)
        etiqueta_rol = DelegadoEtiqueta(self.tabla)
        etiqueta_rol.colores_en_orden(dominio.ROLES)
        self.tabla.setItemDelegateForColumn(COLUMNA_ROL, etiqueta_rol)
        self.tabla.setColumnWidth(0, 130)
        self.tabla.setColumnWidth(COLUMNA_ROL, 170)
        self.tabla.setColumnWidth(COLUMNA_ESTADO, 130)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(barra_botones)
        layout.addLayout(fila_inactivos)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        layout.addWidget(pie_de_ventana(
            "Doble clic en un usuario para modificarlo  ·  Quien ya vendió, compró o cerró un turno no se "
            "borra: se desactiva  ·  \"Mostrar inactivos\" trae a los dados de baja"))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar_grilla(self, _=None):
        # El "_=None" no se usa: absorbe el estado que manda `stateChanged` (ver
        # ArticulosWindow._cargar_grilla).
        usuarios = usuarios_repo.listar_usuarios(incluir_inactivos=self.check_inactivos.isChecked())
        self.tabla.setRowCount(0)
        for usuario in usuarios:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            celdas = [str(usuario["id"]), usuario["nombre"], usuario["rol"],
                      "Activo" if usuario["activo"] else "Inactivo"]
            for columna, texto in enumerate(celdas):
                item = QTableWidgetItem(texto)
                if not usuario["activo"]:
                    item.setForeground(_COLOR_INACTIVO)
                self.tabla.setItem(fila, columna, item)
        # Los números de arriba cuentan solo a los activos (los que pueden entrar),
        # se muestren o no los inactivos en la grilla.
        activos = [usuario for usuario in usuarios if usuario["activo"]]
        admins = sum(1 for usuario in activos if dominio.es_admin(usuario))
        poner_indicador(self.indicador_activos, str(len(activos)))
        poner_indicador(self.indicador_admins, str(admins))
        poner_indicador(self.indicador_empleadas, str(len(activos) - admins))

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
            mostrar_info(self, "Guardado", "Se actualizó el cambio fijo.")

    def _abrir_copias(self):
        DialogoCopiasDeSeguridad(self.usuario_actual, self).exec()


class DialogoUsuario(QDialog):
    """Alta (sin `usuario_id`) o edición de un usuario: nombre, clave, rol
    y, para una Empleada, sus permisos extra. Con la cabecera oscura y los datos
    en paneles blancos (maqueta B, 2026-10-30)."""

    def __init__(self, parent, usuario_id: int = None):
        super().__init__(parent)
        self.usuario_id = usuario_id
        self.setWindowTitle("Modificación de Usuario" if usuario_id else "Nuevo Usuario")
        self.resize(500, 600)
        self._armar_interfaz()
        if usuario_id:
            self._cargar_datos(usuario_id)

    def _armar_interfaz(self):
        cabecera = cabecera_oscura(
            "👤", "Modificar usuario" if self.usuario_id else "Nuevo usuario",
            "Nombre, clave, rol y qué puede usar")

        self.campo_nombre = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)
        if self.usuario_id:
            self.campo_clave.setPlaceholderText("(dejar vacío para no cambiarla)")
        self.combo_rol = QComboBox()
        self.combo_rol.addItem("Empleada — según los permisos de abajo", dominio.ROL_EMPLEADA)
        self.combo_rol.addItem("Admin — acceso completo", dominio.ROL_ADMIN)
        self.combo_rol.currentIndexChanged.connect(self._actualizar_visibilidad_permisos)

        panel_datos, capa_datos = panel_blanco()
        formulario = QFormLayout()
        formulario.setSpacing(10)
        formulario.addRow("Nombre:", self.campo_nombre)
        formulario.addRow("Clave:", self.campo_clave)
        formulario.addRow("Rol:", self.combo_rol)
        capa_datos.addWidget(titulo_de_seccion("Datos"))
        capa_datos.addLayout(formulario)

        # Permisos extra para una Empleada, además de lo que ya puede
        # hacer cualquiera (Ventas/Caja/Cierre de Turno/Cambiar mi
        # Clave) — un Admin ya tiene todo esto siempre, así que la
        # sección se oculta cuando el Rol de arriba es Admin (ver
        # _actualizar_visibilidad_permisos).
        self.checks_permisos = {}
        self.grupo_permisos, layout_permisos = panel_blanco()
        layout_permisos.addWidget(titulo_de_seccion("Permisos extra (Empleada)"))
        for columna, etiqueta in usuarios_repo.PERMISOS_EMPLEADA:
            check = QCheckBox(etiqueta)
            layout_permisos.addWidget(check)
            self.checks_permisos[columna] = check

        botones = fila_guardar_cancelar(self, self._guardar)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(panel_datos)
        layout.addWidget(self.grupo_permisos)
        layout.addStretch()
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
    """Pide el monto del Cambio Fijo (fondo de cambio); quien lo abre lo lee de
    `spin_monto` si se aceptó (ver UsuariosWindow._configurar_fondo). Con la
    cabecera oscura y el monto en un panel blanco (maqueta B, 2026-10-30)."""

    def __init__(self, parent, valor_actual: float):
        super().__init__(parent)
        self.setWindowTitle("Cambio Fijo")
        self.resize(440, 270)

        cabecera = cabecera_oscura("💵", "Cambio Fijo", "La plata para dar cambio en el cajón")

        self.spin_monto = CampoPesos()
        self.spin_monto.setValue(valor_actual)
        self.spin_monto.setMinimumHeight(36)
        encadenar_enter(self.spin_monto, accion_final=self.accept)

        panel, capa = panel_blanco()
        capa.addWidget(QLabel("Cambio Fijo que arranca cada turno:"))
        capa.addWidget(self.spin_monto)

        botones = fila_guardar_cancelar(self)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(panel)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)


class DialogoCambiarClave(QDialog):
    """Para que cualquier usuario logueado (Admin o Empleada) cambie su
    propia clave — a diferencia de DialogoUsuario, que es Admin-only y
    puede resetear la clave de cualquier otra persona sin pedir la
    vieja. Se abre desde el menú principal, no desde esta pantalla. Con la
    cabecera oscura y los campos en un panel blanco (maqueta B, 2026-10-30)."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Cambiar mi Clave")
        self.resize(460, 330)
        self._armar_interfaz()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura("🔑", "Cambiar mi clave", f"{self.usuario['nombre']} · pide la clave de ahora")

        self.campo_actual = QLineEdit()
        self.campo_actual.setEchoMode(QLineEdit.Password)
        self.campo_nueva = QLineEdit()
        self.campo_nueva.setEchoMode(QLineEdit.Password)
        self.campo_confirmar = QLineEdit()
        self.campo_confirmar.setEchoMode(QLineEdit.Password)

        panel, capa = panel_blanco()
        formulario = QFormLayout()
        formulario.setSpacing(10)
        formulario.addRow("Clave actual:", self.campo_actual)
        formulario.addRow("Clave nueva:", self.campo_nueva)
        formulario.addRow("Confirmar clave nueva:", self.campo_confirmar)
        capa.addLayout(formulario)
        encadenar_enter(self.campo_actual, self.campo_nueva, self.campo_confirmar, accion_final=self._guardar)

        botones = fila_guardar_cancelar(self, self._guardar)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(panel)
        layout.addStretch()
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
