"""
miembros_window.py
====================
Administración de Miembros (socios con saldo prepago de tiempo): alta,
edición y baja de cuentas, y la carga de saldo — que siempre hace el
Operador, porque implica cobrar plata (a diferencia de "Abrir PC con
Miembro" en pcs_window.py, que es autoservicio del socio). Botón propio
de la barra superior ("Miembros"), accesible con permiso_control_pcs o
Admin — son tareas de *usar* el catálogo (cargar saldo con la tarifa y
los bonos ya definidos), no de editarlo.

La configuración de la tabla de tramos de tarifa $/hora (ver
config_repo.obtener_tramos_tarifa_hora_miembro) y la gestión del
catálogo de Bonos exclusivo de socios (bonos_miembro_repo, distinto del
de walk-ins que administra pcs_window.DialogoGestionBonos) son tareas de
EDICIÓN de catálogo, exclusivas de ADMIN — sus pantallas
(DialogoTramosTarifaMiembro, DialogoGestionBonosMiembro) siguen viviendo
acá porque son del dominio de Miembros, pero el botón que las abre está
en ui/main_window.ConfiguracionAdminWindow, no en esta ventana.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem,
    QPushButton, QLineEdit, QLabel, QComboBox, QCheckBox, QFormLayout,
    QHeaderView, QDoubleSpinBox, QSpinBox, QStackedWidget, QWidget
)

import dominio
from repositories import config_repo
from control_pcs.repositories import miembros_repo, bonos_miembro_repo
from ui.dialogo_pago import resolver_pagos
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
        botones = [boton_nuevo, boton_modificar, boton_cargar_saldo, boton_desactivar]
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        botones.append(boton_salir)
        for boton in botones:
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

        self.combo_metodo = QComboBox()
        for metodo in (dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL, dominio.PAGO_MIXTO):
            self.combo_metodo.addItem(dominio.NOMBRE_METODO_PAGO[metodo], metodo)

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
        monto = self.spin_monto.value()
        tarifa_hora = dominio.tarifa_hora_para_monto(self.tramos_tarifa, monto)
        self.etiqueta_tarifa_aplicada.setText(f"Tarifa a esta carga: {formato_pesos(tarifa_hora)} / hora")
        minutos = int((monto / tarifa_hora * 60) // 30) * 30
        self.etiqueta_preview_monto.setText(f"Equivale a {formato_tiempo(minutos * 60)} de saldo.")

    @manejar_errores
    def _confirmar(self):
        metodo = self.combo_metodo.currentData()
        if self.combo_modo.currentData() == "MONTO":
            monto = self.spin_monto.value()
            pagos = resolver_pagos(self, metodo, monto)
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
            pagos = resolver_pagos(self, metodo, bono["precio"])
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
    dominio.tarifa_hora_para_monto) -- reemplaza la tarifa única que
    había hasta 2026-09-30. Cada fila es "a partir de $X, $Y la hora";
    no hace falta cargarlas en orden ni con precios crecientes o
    decrecientes, dominio.tarifa_hora_para_monto las ordena solo. Mismo
    patrón de edición que pcs_window.DialogoEditarGateways: se guarda la
    tabla entera de una, no fila por fila.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Tarifa por Hora para Socios")
        self.resize(420, 340)

        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Monto mínimo", "Tarifa por hora"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for tramo in config_repo.obtener_tramos_tarifa_hora_miembro():
            self._agregar_fila(tramo["monto_minimo"], tramo["tarifa_hora"])

        boton_agregar = QPushButton("Agregar tramo")
        boton_agregar.clicked.connect(lambda: self._agregar_fila(0, 0))
        boton_quitar = QPushButton("Quitar seleccionado")
        aplicar_clase(boton_quitar, "peligro")
        boton_quitar.clicked.connect(self._quitar_seleccionado)
        fila_botones = QHBoxLayout()
        fila_botones.addWidget(boton_agregar)
        fila_botones.addWidget(boton_quitar)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(
            "Tramos según cuánta plata carga el socio (ej. $0 en adelante = $1.000/h,\n"
            "$5.000 en adelante = $1.500/h). Se usa el tramo más alto que no supere el monto\n"
            "cargado; un monto menor al tramo más bajo igual usa la tarifa de ese tramo."
        ))
        layout.addWidget(self.tabla)
        layout.addLayout(fila_botones)
        layout.addLayout(botones)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

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
        self.tabla.setCellWidget(fila, 0, self._spin_monto(monto_minimo))
        self.tabla.setCellWidget(fila, 1, self._spin_monto(tarifa_hora))

    def _quitar_seleccionado(self):
        fila = self.tabla.currentRow()
        if fila >= 0:
            self.tabla.removeRow(fila)

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


class DialogoGestionBonosMiembro(QDialog):
    """
    Catálogo de Bonos EXCLUSIVO de socios (bonos_miembro_repo) — mismo
    espíritu que pcs_window.DialogoGestionBonos (el de walk-ins), pero
    tabla y pantalla separadas a propósito (ver el docstring del módulo).
    Solo se llega acá desde ui.main_window.ConfiguracionAdminWindow, que
    es exclusiva de ADMIN: nadie más ve el botón que abre este diálogo.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Bonos de Socios")
        self.resize(460, 440)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Nombre", "Tiempo", "Precio"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

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
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _cargar(self):
        self.bonos = bonos_miembro_repo.listar_bonos()
        self.tabla.setRowCount(0)
        for bono in self.bonos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(bono["nombre"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(formato_tiempo(bono["minutos"] * 60)))
            self.tabla.setItem(fila, 2, QTableWidgetItem(formato_pesos(bono["precio"])))

    def _seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un bono de la lista.")
            return None
        return self.bonos[fila]

    def _nuevo(self):
        dialogo = DialogoBonoMiembro(self)
        if dialogo.exec():
            self._cargar()

    def _modificar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        dialogo = DialogoBonoMiembro(self, bono)
        if dialogo.exec():
            self._cargar()

    @manejar_errores
    def _desactivar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar el bono de socios '{bono['nombre']}'? Deja de poder cargarse, "
                     "pero los socios que ya lo usaron conservan su historial."):
            bonos_miembro_repo.desactivar_bono(bono["id"])
            self._cargar()


class DialogoBonoMiembro(QDialog):
    """Alta/edición de un bono de socios. Mismo formulario que
    pcs_window.DialogoBono (horas/minutos en pasos de 30, nunca minuto
    suelto) — es el mismo concepto de combo prearmado, solo que este
    catálogo es exclusivo de Miembros."""

    def __init__(self, parent, bono=None):
        super().__init__(parent)
        self.bono = bono
        self.setWindowTitle("Modificar Bono de Socios" if bono else "Nuevo Bono de Socios")
        self.resize(340, 260)
        self._armar_interfaz()
        if bono:
            self._cargar_datos(bono)

    def _armar_interfaz(self):
        self.campo_nombre = QLineEdit()
        self.campo_nombre.setPlaceholderText("Ej: 3 horas Socio")

        self.spin_horas = QSpinBox()
        self.spin_horas.setRange(0, 99)
        self.spin_minutos = QSpinBox()
        self.spin_minutos.setRange(0, 30)
        self.spin_minutos.setSingleStep(30)
        fila_tiempo = QHBoxLayout()
        fila_tiempo.addWidget(self.spin_horas)
        fila_tiempo.addWidget(QLabel("hs"))
        fila_tiempo.addWidget(self.spin_minutos)
        fila_tiempo.addWidget(QLabel("min"))

        self.spin_precio = QDoubleSpinBox()
        self.spin_precio.setMaximum(99_999_999)
        self.spin_precio.setPrefix("$ ")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.campo_nombre)
        layout.addWidget(QLabel("Tiempo:"))
        layout.addLayout(fila_tiempo)
        layout.addWidget(QLabel("Precio:"))
        layout.addWidget(self.spin_precio)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_nombre, self.spin_horas, self.spin_minutos, self.spin_precio,
                         accion_final=self._guardar)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _cargar_datos(self, bono):
        self.campo_nombre.setText(bono["nombre"])
        self.spin_horas.setValue(bono["minutos"] // 60)
        self.spin_minutos.setValue(bono["minutos"] % 60)
        self.spin_precio.setValue(bono["precio"])

    @manejar_errores
    def _guardar(self):
        nombre = self.campo_nombre.text().strip()
        minutos = self.spin_horas.value() * 60 + self.spin_minutos.value()
        precio = self.spin_precio.value()
        if self.bono:
            bonos_miembro_repo.modificar_bono(self.bono["id"], nombre, minutos, precio)
        else:
            bonos_miembro_repo.crear_bono(nombre, minutos, precio)
        self.accept()
