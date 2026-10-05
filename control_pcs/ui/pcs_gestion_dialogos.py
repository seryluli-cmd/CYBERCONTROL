"""
pcs_gestion_dialogos.py
=========================
Diálogos para ADMINISTRAR los catálogos de Estaciones (las PCs del local, su
IP y las claves de los Clientes PC) y de Bonos de Tiempo de walk-ins (mismo
espíritu que "Gestionar Rubros" en Artículos). Solo se abren desde
`ConfiguracionAdminWindow` (ui/main_window.py), exclusiva de ADMIN. Los bonos
exclusivos de socios se gestionan aparte, en miembros_window.py.
"""

from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QHeaderView, QInputDialog, QLabel,
    QLineEdit, QPushButton, QSpinBox, QTableWidget, QTableWidgetItem, QVBoxLayout,
)

from control_pcs.repositories import clientes_repo, pcs_repo
from ui.utils import (
    aplicar_clase, confirmar, encadenar_enter, formato_pesos, formato_tiempo,
    manejar_errores, mostrar_error, mostrar_info, sin_boton_por_defecto,
)

class DialogoGestionEstaciones(QDialog):
    """Alta, renombre y baja de estaciones, IP de cada una y las dos claves
    que usan los Clientes PC. Solo se llega desde Configuración ADMIN."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Estaciones")
        self.resize(360, 420)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.lista = QTableWidget(0, 1)
        self.lista.setHorizontalHeaderLabels(["Estación"])
        self.lista.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lista.horizontalHeader().setVisible(False)
        self.lista.setSelectionBehavior(QTableWidget.SelectRows)
        self.lista.setSelectionMode(QTableWidget.SingleSelection)
        self.lista.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lista.setAlternatingRowColors(True)

        self.campo_nuevo = QLineEdit()
        self.campo_nuevo.setPlaceholderText("Nombre de la estación nueva (ej. PC 5)...")
        boton_agregar = QPushButton("Agregar")
        aplicar_clase(boton_agregar, "primario")
        boton_agregar.clicked.connect(self._agregar)
        encadenar_enter(self.campo_nuevo, accion_final=self._agregar)

        fila_agregar = QHBoxLayout()
        fila_agregar.addWidget(self.campo_nuevo)
        fila_agregar.addWidget(boton_agregar)

        boton_renombrar = QPushButton("Renombrar seleccionada")
        boton_renombrar.clicked.connect(self._renombrar)
        boton_desactivar = QPushButton("Desactivar seleccionada")
        aplicar_clase(boton_desactivar, "peligro")
        boton_desactivar.clicked.connect(self._desactivar)

        fila_acciones = QHBoxLayout()
        fila_acciones.addWidget(boton_renombrar)
        fila_acciones.addWidget(boton_desactivar)

        # IP de la estación seleccionada: la guarda sola servidor_red.py
        # (self.client_address de cada GET /estado, ver
        # pcs_repo.registrar_conexion) en cuanto el Cliente PC de esa PC hace
        # su primer pedido DESPUÉS de que la estación ya existe acá -- una
        # estación recién creada, o cuyo Cliente PC todavía no conectó, no
        # tiene nada que mostrar. "Traer IP" relee el dato fresco desde la
        # base por si el Cliente PC conectó recién, sin tener que cerrar y
        # volver a abrir todo el diálogo.
        self.campo_ip = QLineEdit()
        self.campo_ip.setReadOnly(True)
        self.campo_ip.setPlaceholderText("Todavía no se conoce")
        boton_traer_ip = QPushButton("Traer IP")
        boton_traer_ip.clicked.connect(self._traer_ip)

        fila_ip = QHBoxLayout()
        fila_ip.addWidget(QLabel("IP de la seleccionada:"))
        fila_ip.addWidget(self.campo_ip)
        fila_ip.addWidget(boton_traer_ip)

        self.lista.itemSelectionChanged.connect(self._al_cambiar_seleccion)

        boton_clave_clientes = QPushButton("Generar/renovar clave de Clientes PC...")
        boton_clave_clientes.clicked.connect(self._generar_clave_clientes)

        boton_clave_admin = QPushButton("Cambiar contraseña de PC clientes...")
        boton_clave_admin.clicked.connect(self._cambiar_clave_admin_pcs)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Estaciones activas:"))
        layout.addWidget(self.lista)
        layout.addLayout(fila_agregar)
        layout.addLayout(fila_acciones)
        layout.addLayout(fila_ip)
        layout.addWidget(boton_clave_clientes)
        layout.addWidget(boton_clave_admin)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.campo_nuevo.setFocus()

    @manejar_errores
    def _cargar(self):
        self.estaciones = pcs_repo.listar_estaciones()
        self.lista.setRowCount(0)
        for estacion in self.estaciones:
            fila = self.lista.rowCount()
            self.lista.insertRow(fila)
            self.lista.setItem(fila, 0, QTableWidgetItem(estacion["nombre"]))

    def _seleccionada(self):
        fila = self.lista.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero una estación de la lista.")
            return None
        return self.estaciones[fila]

    @manejar_errores
    def _agregar(self):
        nombre = self.campo_nuevo.text().strip()
        if not nombre:
            mostrar_error(self, "Falta el nombre", "Escribí el nombre de la estación nueva.")
            return
        pcs_repo.crear_estacion(nombre)
        self.campo_nuevo.clear()
        self._cargar()
        self.campo_nuevo.setFocus()

    @manejar_errores
    def _renombrar(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        nuevo_nombre, aceptado = QInputDialog.getText(
            self, "Renombrar estación", "Nuevo nombre:", text=estacion["nombre"]
        )
        if not aceptado:
            return
        pcs_repo.renombrar_estacion(estacion["id"], nuevo_nombre)
        self._cargar()

    @manejar_errores
    def _desactivar(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar '{estacion['nombre']}'? Deja de listarse acá, pero su "
                     "historial de sesiones se conserva."):
            pcs_repo.desactivar_estacion(estacion["id"])
            self._cargar()

    def _al_cambiar_seleccion(self):
        """Al cambiar de fila, muestra la IP ya cargada en memoria (la que
        trajo el último `_cargar()`) sin ir a la base -- `_traer_ip` es la
        que relee fresco si hace falta."""
        fila = self.lista.currentRow()
        if fila < 0 or fila >= len(self.estaciones):
            self.campo_ip.clear()
            return
        self.campo_ip.setText(self.estaciones[fila]["ultima_ip"] or "")

    @manejar_errores
    def _traer_ip(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        fresca = pcs_repo.obtener_estacion(estacion["id"])
        ip = fresca["ultima_ip"] if fresca is not None else None
        if ip:
            self.campo_ip.setText(ip)
        else:
            self.campo_ip.clear()
            mostrar_error(
                self, "Todavía no hay IP",
                f"'{estacion['nombre']}' todavía no registró ninguna conexión con IP.\n\n"
                "Configurá el Cliente PC en esa PC con este mismo nombre de "
                "estación y esperá unos segundos: pregunta solo cada 5s, y "
                "recién ahí queda la IP guardada acá."
            )

    @manejar_errores
    def _generar_clave_clientes(self):
        """
        Genera (o rota) la clave única que exige `servidor_red.py` en el
        header `Authorization` de cada Cliente PC (ver CLIENTE PC,
        `red_kiosko._cabeceras_cliente`). Al rotarla, la clave anterior
        deja de servir para CUALQUIER PC hasta que se la actualice ahí --
        por eso pide confirmación explícita si ya había una generada.
        """
        clave_actual = clientes_repo.obtener_clave_clientes()
        if clave_actual:
            aviso = (
                "Se va a generar una clave nueva para los Clientes PC.\n\n"
                "Esto ROTA la clave de las estaciones que ya están conectadas: "
                "la anterior deja de servir para cualquier PC hasta que se "
                "actualice ahí con la nueva. ¿Continuar?"
            )
        else:
            aviso = "Se va a generar la clave que necesitan los Clientes PC para conectarse a este servidor. ¿Continuar?"
        if not confirmar(self, "Generar/renovar clave de Clientes PC", aviso):
            return
        clave_nueva = clientes_repo.generar_clave_clientes()
        QInputDialog.getText(
            self, "Clave de Clientes PC generada",
            "Copiá esta clave (Ctrl+A, Ctrl+C) y pegala en el config.json\n"
            "o en el asistente de configuración de cada PC cliente:",
            text=clave_nueva,
        )

    @manejar_errores
    def _cambiar_clave_admin_pcs(self):
        """
        Contraseña que destraba el panel admin en la pantalla de bloqueo
        de cada PC cliente (ícono "A", ver cliente_pc.py). A
        diferencia de la clave de Clientes PC, la elige el dueño (tiene que
        poder recordarla) y cada PC cliente la actualiza sola en su
        próximo `GET /estado` -- no hace falta ir PC por PC.
        """
        nueva, aceptado = QInputDialog.getText(
            self, "Cambiar contraseña de PC clientes",
            "Nueva contraseña de administrador:",
            QLineEdit.EchoMode.Password,
        )
        if not aceptado:
            return
        if len(nueva) < 4:
            mostrar_error(self, "Contraseña muy corta", "Usá al menos 4 caracteres.")
            return
        confirmacion, aceptado = QInputDialog.getText(
            self, "Cambiar contraseña de PC clientes",
            "Repetí la contraseña:",
            QLineEdit.EchoMode.Password,
        )
        if not aceptado:
            return
        if confirmacion != nueva:
            mostrar_error(self, "No coincide", "Las dos contraseñas no son iguales.")
            return
        clientes_repo.establecer_clave_admin_pcs(nueva)
        mostrar_info(
            self, "Listo",
            "Contraseña actualizada. Cada PC cliente la va a tomar sola "
            "la próxima vez que se conecte con el Servidor (hasta 5 "
            "segundos, si ya está prendida y conectada)."
        )


class DialogoGestionBonos(QDialog):
    """Catálogo de bonos de walk-ins (pcs_repo). Los de socios se gestionan
    aparte, en miembros_window.DialogoGestionBonosMiembro. Solo se llega
    desde Configuración ADMIN."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Bonos de Tiempo")
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
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        self.bonos = pcs_repo.listar_bonos()
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
        dialogo = DialogoBono(self)
        if dialogo.exec():
            self._cargar()

    def _modificar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        dialogo = DialogoBono(self, bono)
        if dialogo.exec():
            self._cargar()

    @manejar_errores
    def _desactivar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar el bono '{bono['nombre']}'? Deja de poder venderse, pero "
                     "las sesiones que ya lo usaron conservan su historial."):
            pcs_repo.desactivar_bono(bono["id"])
            self._cargar()


class DialogoBono(QDialog):
    """Alta/edición de un bono de tiempo. El tiempo se carga en horas y
    minutos por separado (en pasos de 30 min) porque acá nunca se vende
    por minuto suelto — solo combos prearmados como "3 horas" o
    "1 hora y media"."""

    def __init__(self, parent, bono=None):
        super().__init__(parent)
        self.bono = bono
        self.setWindowTitle("Modificar Bono" if bono else "Nuevo Bono")
        self.resize(340, 260)
        self._armar_interfaz()
        if bono:
            self._cargar_datos(bono)

    def _armar_interfaz(self):
        self.campo_nombre = QLineEdit()
        self.campo_nombre.setPlaceholderText("Ej: 3 horas")

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
        sin_boton_por_defecto(self)

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
            pcs_repo.modificar_bono(self.bono["id"], nombre, minutos, precio)
        else:
            pcs_repo.crear_bono(nombre, minutos, precio)
        self.accept()
