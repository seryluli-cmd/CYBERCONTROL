"""
miembros_window.py
====================
Administración de Miembros (socios con saldo prepago de tiempo): alta,
edición y baja de cuentas, y la carga de saldo — que siempre hace el
Operador, porque implica cobrar plata (a diferencia de "Abrir PC con
Miembro" en pcs_detalle.py, que es autoservicio del socio). Botón propio
de la barra superior ("Miembros"), accesible para cualquier operador
logueado (pedido del dueño, 2026-10-19: antes pedía permiso_control_pcs o
Admin, pero cargarle saldo a un socio tiene que poder hacerlo cualquiera)
— son tareas de *usar* el catálogo (cargar saldo con la tarifa y los
bonos ya definidos), no de editarlo.

La configuración de la tabla de tramos de tarifa $/hora (ver
config_repo.obtener_tramos_tarifa_hora_miembro) y la gestión del
catálogo de Bonos exclusivo de socios (bonos_miembro_repo, distinto del
de walk-ins que administra pcs_gestion_dialogos.DialogoGestionBonos) son tareas de
EDICIÓN de catálogo, exclusivas de ADMIN — sus pantallas
(DialogoTramosTarifaMiembro, DialogoGestionBonosMiembro) siguen viviendo
acá porque son del dominio de Miembros, pero el botón que las abre está
en ui/main_window.ConfiguracionAdminWindow, no en esta ventana.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QCheckBox, QFormLayout,
    QHeaderView, QDoubleSpinBox, QStackedWidget, QWidget
)

import dominio
from repositories import config_repo
from control_pcs.repositories import miembros_repo, bonos_miembro_repo
from control_pcs.ui.bonos_dialogos import DialogoBonoBase, DialogoGestionBonosBase
from ui.dialogo_pago import cobrar
from ui.utils import (
    formato_pesos, formato_tiempo, mostrar_error, confirmar, manejar_errores,
    aplicar_clase, encadenar_enter, sin_boton_por_defecto, fila_guardar_cancelar,
    crear_tabla, fila_agregar_quitar,
)


class MiembrosWindow(QDialog):
    """Grilla de socios con alta, modificación, carga de saldo y baja."""

    def __init__(self, usuario_operador, parent=None):
        super().__init__(parent)
        self.usuario_operador = usuario_operador
        self.setWindowTitle("Administración de Miembros")
        self.resize(860, 480)
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
        botones = [boton_nuevo, boton_modificar, boton_cargar_saldo, boton_desactivar]
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        botones.append(boton_salir)
        for boton in botones:
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        self.check_inactivos = QCheckBox("Mostrar inactivos")
        self.check_inactivos.stateChanged.connect(self._cargar_grilla)

        self.tabla = crear_tabla(
            ["Usuario", "Nombre", "DNI", "Celular", "WhatsApp", "Saldo", "Estado"],
            estirar=1, por_filas=True,
        )
        self.tabla.doubleClicked.connect(self._modificar_miembro)

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.check_inactivos)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar_grilla(self):
        self.miembros = miembros_repo.listar_miembros(incluir_inactivos=self.check_inactivos.isChecked())
        self.tabla.setRowCount(0)
        for miembro in self.miembros:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(miembro["usuario"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(miembro["nombre"]))
            if miembros_repo.tiene_dni(miembro):
                item_dni = QTableWidgetItem(miembro["dni"])
            else:
                # Se lo pide su PC la primera vez que entra (ver miembros_repo).
                item_dni = QTableWidgetItem("Falta DNI")
                item_dni.setForeground(Qt.red)
            self.tabla.setItem(fila, 2, item_dni)
            self.tabla.setItem(fila, 3, QTableWidgetItem(miembro["telefono"]))
            self.tabla.setItem(fila, 4, QTableWidgetItem(miembro["whatsapp"]))
            self.tabla.setItem(fila, 5, QTableWidgetItem(formato_tiempo(miembro["saldo_minutos"] * 60)))
            self.tabla.setItem(fila, 6, QTableWidgetItem("Activo" if miembro["activo"] else "Inactivo"))
        # Con el ancho fijo de siempre, un WhatsApp con +54 9 se veía cortado.
        self.tabla.resizeColumnsToContents()

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


class DialogoMiembro(QDialog):
    """Alta (sin `miembro`) o edición de los datos de un socio."""

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
        self.campo_whatsapp = QLineEdit()
        self.campo_email = QLineEdit()
        for campo in (self.campo_nombre, self.campo_dni, self.campo_telefono, self.campo_whatsapp,
                      self.campo_email):
            campo.setPlaceholderText("(opcional)")

        # Alcanzan usuario y contraseña (pedido del dueño, 2026-10-17): el DNI, el
        # celular y el WhatsApp los completa el socio al entrar desde su PC.
        aclaracion = QLabel(
            "Alcanza con usuario y contraseña: el DNI, el celular y el WhatsApp\n"
            "se los pide la PC al socio la primera vez que entra."
        )
        aclaracion.setStyleSheet("color: gray; font-style: italic;")

        formulario = QFormLayout()
        formulario.addRow("Usuario:", self.campo_usuario)
        formulario.addRow("Contraseña:", self.campo_clave)
        formulario.addRow("Nombre:", self.campo_nombre)
        formulario.addRow("DNI:", self.campo_dni)
        formulario.addRow("Celular:", self.campo_telefono)
        formulario.addRow("WhatsApp:", self.campo_whatsapp)
        formulario.addRow("Email:", self.campo_email)

        botones = fila_guardar_cancelar(self, self._guardar)

        layout = QVBoxLayout()
        layout.addLayout(formulario)
        layout.addWidget(aclaracion)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_usuario, self.campo_clave, self.campo_nombre, self.campo_dni,
                         self.campo_telefono, self.campo_whatsapp, self.campo_email,
                         accion_final=self._guardar)
        sin_boton_por_defecto(self)

    def _cargar_datos(self, miembro):
        self.campo_usuario.setText(miembro["usuario"])
        self.campo_nombre.setText(miembro["nombre"])
        self.campo_dni.setText(miembro["dni"])
        self.campo_telefono.setText(miembro["telefono"])
        self.campo_whatsapp.setText(miembro["whatsapp"])
        self.campo_email.setText(miembro["email"] or "")

    @manejar_errores
    def _guardar(self):
        usuario = self.campo_usuario.text().strip()
        nombre = self.campo_nombre.text().strip()
        dni = self.campo_dni.text().strip()
        telefono = self.campo_telefono.text().strip()
        whatsapp = self.campo_whatsapp.text().strip()
        email = self.campo_email.text().strip() or None
        clave = self.campo_clave.text()

        if self.miembro:
            miembros_repo.modificar_miembro(self.miembro["id"], usuario, nombre, dni, telefono,
                                             email, clave or None, whatsapp=whatsapp)
        else:
            if not clave:
                mostrar_error(self, "Falta la contraseña", "Un socio nuevo necesita una contraseña.")
                return
            miembros_repo.crear_miembro(usuario, clave, nombre, dni, telefono, email, whatsapp=whatsapp)
        self.accept()


class DialogoCargarSaldo(QDialog):
    """Dos formas de cargar saldo: un monto libre en $ (convertido a
    minutos según la tarifa del tramo que corresponda a ese monto, ver
    config_repo.obtener_tramos_tarifa_hora_miembro y
    dominio.tarifa_hora_para_monto) o uno de los bonos del catálogo
    EXCLUSIVO de socios (bonos_miembro_repo.listar_bonos -- no el de
    walk-ins de pcs_repo) — siempre lo hace el Operador, porque implica
    cobrar plata."""

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
        # La tarifa ya no es un valor único: depende de en qué tramo cae
        # el monto que se está por cargar (ver
        # config_repo.obtener_tramos_tarifa_hora_miembro), así que la
        # etiqueta de tarifa se recalcula junto con la preview de minutos
        # cada vez que cambia el monto tipeado.
        self.tramos_tarifa = config_repo.obtener_tramos_tarifa_hora_miembro()
        pagina_monto = QWidget()
        layout_monto = QVBoxLayout()
        self.etiqueta_tarifa_aplicada = QLabel()
        layout_monto.addWidget(self.etiqueta_tarifa_aplicada)
        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        self.spin_monto.valueChanged.connect(self._actualizar_preview_monto)
        self.etiqueta_preview_monto = QLabel()
        layout_monto.addWidget(self.spin_monto)
        layout_monto.addWidget(self.etiqueta_preview_monto)
        pagina_monto.setLayout(layout_monto)

        # --- Modo Bono ---
        # Catálogo EXCLUSIVO de socios (bonos_miembro_repo), no el de
        # walk-ins de pcs_repo -- ver el docstring del módulo.
        pagina_bono = QWidget()
        layout_bono = QVBoxLayout()
        self.combo_bono = QComboBox()
        self.bonos = bonos_miembro_repo.listar_bonos()
        for bono in self.bonos:
            self.combo_bono.addItem(f"{bono['nombre']} — {formato_pesos(bono['precio'])}", bono["id"])
        layout_bono.addWidget(self.combo_bono)
        pagina_bono.setLayout(layout_bono)

        self.paginas = QStackedWidget()
        self.paginas.addWidget(pagina_monto)
        self.paginas.addWidget(pagina_bono)

        botones = fila_guardar_cancelar(self, self._confirmar, texto_guardar="Cobrar y cargar saldo")

        layout = QVBoxLayout()
        layout.addWidget(etiqueta_saldo)
        layout.addWidget(QLabel("Forma de carga:"))
        layout.addWidget(self.combo_modo)
        layout.addWidget(self.paginas)
        layout.addLayout(botones)
        self.setLayout(layout)
        # Enter pasa al siguiente campo, como Tab: de la forma de carga al
        # monto o al bono (según cuál se ve), y ahí abre la ventana de cobro
        # (la misma de una venta de kiosko: medio de pago, reparto y vuelto;
        # pedido del dueño, 2026-10-18: antes había un combo "Medio de pago").
        encadenar_enter(self.combo_modo, accion_final=self._ir_al_monto_o_al_bono)
        encadenar_enter(self.spin_monto, accion_final=self._confirmar)
        encadenar_enter(self.combo_bono, accion_final=self._confirmar)
        sin_boton_por_defecto(self)
        self._actualizar_preview_monto()

    def _ir_al_monto_o_al_bono(self):
        campo = self.spin_monto if self.combo_modo.currentData() == "MONTO" else self.combo_bono
        campo.setFocus()

    def _actualizar_modo(self):
        self.paginas.setCurrentIndex(self.combo_modo.currentIndex())

    def _actualizar_preview_monto(self):
        monto = self.spin_monto.value()
        # Es la misma cuenta que hace cargar_saldo_por_monto al cobrar.
        tarifa_hora, minutos = miembros_repo.minutos_por_monto(self.tramos_tarifa, monto)
        self.etiqueta_tarifa_aplicada.setText(f"Tarifa a esta carga: {formato_pesos(tarifa_hora)} / hora")
        minima = dominio.carga_minima_de_saldo(self.tramos_tarifa)
        if monto < minima:
            self.etiqueta_preview_monto.setText(f"La carga mínima es de {formato_pesos(minima)}.")
            self.etiqueta_preview_monto.setStyleSheet("color: #C62828; font-weight: bold;")
        else:
            self.etiqueta_preview_monto.setText(f"Equivale a {formato_tiempo(minutos * 60)} de saldo.")
            self.etiqueta_preview_monto.setStyleSheet("")

    @manejar_errores
    def _confirmar(self):
        if self.combo_modo.currentData() == "MONTO":
            monto = self.spin_monto.value()
            miembros_repo.validar_monto_de_carga(self.tramos_tarifa, monto)
            pagos = cobrar(self, monto)
            if pagos is None:
                return
            miembros_repo.cargar_saldo_por_monto(
                self.miembro["id"], monto, pagos, self.usuario_operador["id"]
            )
        else:
            if not self.bonos:
                mostrar_error(self, "Sin bonos", "Todavía no hay ningún bono de socios cargado — "
                                                  "pedile a un Administrador que cree uno primero "
                                                  "desde 'Gestionar Bonos de Socios'.")
                return
            bono_id = self.combo_bono.currentData()
            bono = next(b for b in self.bonos if b["id"] == bono_id)
            pagos = cobrar(self, bono["precio"])
            if pagos is None:
                return
            miembros_repo.cargar_saldo_por_bono(
                self.miembro["id"], bono_id, pagos, self.usuario_operador["id"]
            )
        self.accept()


class DialogoTramosTarifaMiembro(QDialog):
    """
    Tabla de tramos de tarifa $/hora para la carga de saldo por monto
    (ver config_repo.obtener_tramos_tarifa_hora_miembro y
    dominio.tarifa_hora_para_monto). Cada fila es "a partir de $X, $Y la
    hora"; no hace falta cargarlas en orden ni con precios crecientes o
    decrecientes, dominio.tarifa_hora_para_monto las ordena solo. Mismo
    patrón de edición que pcs_comandos_dialogos.DialogoEditarGateways: se guarda la
    tabla entera de una, no fila por fila.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tarifa por Hora para Socios")
        self.resize(480, 420)

        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Monto mínimo", "Tarifa por hora"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        self.tabla.verticalHeader().setVisible(False)  # como todas las tablas (ui.utils.crear_tabla)
        for tramo in config_repo.obtener_tramos_tarifa_hora_miembro():
            self._agregar_fila(tramo["monto_minimo"], tramo["tarifa_hora"])

        fila_botones = fila_agregar_quitar(self.tabla, "Agregar tramo", lambda: self._agregar_fila(0, 0))

        botones = fila_guardar_cancelar(self, self._guardar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(
            "Tramos según cuánta plata carga el socio (ej. $13.000 en adelante = $1.000/h,\n"
            "$20.000 en adelante = $900/h). Se usa el tramo más alto que no supere el monto\n"
            "cargado. El monto del tramo más bajo es la carga mínima: no se puede cargar menos."
        ))
        layout.addWidget(self.tabla)
        layout.addLayout(fila_botones)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @staticmethod
    def _spin_monto(valor):
        # Mismo widget que usa el resto de la app para cualquier monto
        # en pesos (ver DialogoGestionBonos.spin_precio) -- evita tener
        # que parsear a mano un texto con "$"/separadores de miles como
        # los que arma formato_pesos.
        spin = QDoubleSpinBox()
        spin.setMaximum(99_999_999)
        spin.setPrefix("$ ")
        spin.setValue(valor)
        return spin

    def _agregar_fila(self, monto_minimo, tarifa_hora):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        spin_minimo = self._spin_monto(monto_minimo)
        self.tabla.setCellWidget(fila, 0, spin_minimo)
        self.tabla.setCellWidget(fila, 1, self._spin_monto(tarifa_hora))
        # La fila tiene que ser tan alta como el campo: con el alto por defecto de
        # la tabla, el relleno que la hoja de estilos le da a los QDoubleSpinBox
        # dejaba los números cortados por la mitad e imposibles de leer.
        self.tabla.setRowHeight(fila, spin_minimo.sizeHint().height() + 6)

    @manejar_errores
    def _guardar(self):
        tramos = [
            {
                "monto_minimo": self.tabla.cellWidget(fila, 0).value(),
                "tarifa_hora": self.tabla.cellWidget(fila, 1).value(),
            }
            for fila in range(self.tabla.rowCount())
        ]
        try:
            dominio.validar_tramos_tarifa_hora_miembro(tramos)
        except ValueError as error:
            mostrar_error(self, "Tramo inválido", str(error))
            return
        config_repo.guardar_tramos_tarifa_hora_miembro(tramos)
        self.accept()


class DialogoBonoMiembro(DialogoBonoBase):
    """Alta/edición de un bono de socios (bonos_miembro_repo). Mismo
    formulario que el de walk-ins (horas/minutos en pasos de 30, nunca
    minuto suelto): es el mismo concepto de combo prearmado, solo que este
    catálogo es exclusivo de Miembros."""

    repo = bonos_miembro_repo
    TITULO_NUEVO = "Nuevo Bono de Socios"
    TITULO_EDICION = "Modificar Bono de Socios"
    EJEMPLO_NOMBRE = "Ej: 3 horas Socio"


class DialogoGestionBonosMiembro(DialogoGestionBonosBase):
    """
    Catálogo de Bonos EXCLUSIVO de socios (bonos_miembro_repo) — mismo
    espíritu que pcs_gestion_dialogos.DialogoGestionBonos (el de walk-ins),
    pero tabla y pantalla separadas a propósito (ver el docstring del
    módulo). Solo se llega acá desde ui.main_window.ConfiguracionAdminWindow,
    que es exclusiva de ADMIN: nadie más ve el botón que abre este diálogo.
    """

    repo = bonos_miembro_repo
    CLASE_FORMULARIO = DialogoBonoMiembro
    TITULO = "Gestionar Bonos de Socios"
    CONFIRMAR_DESACTIVAR = (
        "¿Desactivar el bono de socios '{nombre}'? Deja de poder cargarse, "
        "pero los socios que ya lo usaron conservan su historial."
    )
