"""
pcs_gestion_dialogos.py
=========================
Diálogos para ADMINISTRAR los catálogos de Estaciones (las PCs del local, su
IP y las claves de los Clientes PC) y de Bonos de Tiempo de walk-ins (mismo
espíritu que "Gestionar Rubros" en Artículos), más los de la PlayStation 5. Solo
se abren desde `ConfiguracionAdminWindow` (ui/main_window.py), exclusiva de
ADMIN. Los bonos exclusivos de socios se gestionan aparte, en miembros_window.py.
"""

from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QPushButton,
    QTableWidgetItem, QVBoxLayout,
)

from control_pcs.repositories import clientes_repo, pcs_repo, playstation_repo
from control_pcs.ui.bonos_dialogos import DialogoBonoBase, DialogoGestionBonosBase
from ui.utils import (
    aplicar_clase, confirmar, encadenar_enter, manejar_errores, mostrar_error,
    mostrar_info, sin_boton_por_defecto, crear_tabla,
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
        self.lista = crear_tabla(["Estación"], estirar=0, por_filas=True, una_sola=True)
        self.lista.horizontalHeader().setVisible(False)

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


class DialogoBono(DialogoBonoBase):
    """Alta/edición de un bono de walk-ins (pcs_repo)."""

    repo = pcs_repo
    TITULO_NUEVO = "Nuevo Bono"
    TITULO_EDICION = "Modificar Bono"
    EJEMPLO_NOMBRE = "Ej: 3 horas"


class DialogoGestionBonos(DialogoGestionBonosBase):
    """Catálogo de bonos de walk-ins (pcs_repo). Los de socios se gestionan
    aparte, en miembros_window.DialogoGestionBonosMiembro. Solo se llega
    desde Configuración ADMIN."""

    repo = pcs_repo
    CLASE_FORMULARIO = DialogoBono
    TITULO = "Gestionar Bonos de Tiempo"
    CONFIRMAR_DESACTIVAR = (
        "¿Desactivar el bono '{nombre}'? Deja de poder venderse, pero "
        "las sesiones que ya lo usaron conservan su historial."
    )


class DialogoBonoPlaystation(DialogoBonoBase):
    """Alta/edición de un bono de la PlayStation 5. Mismo formulario que los
    otros catálogos (horas/minutos en pasos de 30, nunca minuto suelto); el
    `repo` llega al abrirse, atado al usuario (ver
    playstation_repo.AdministradorDeBonos)."""

    TITULO_NUEVO = "Nuevo Bono de PlayStation 5"
    TITULO_EDICION = "Modificar Bono de PlayStation 5"
    EJEMPLO_NOMBRE = "Ej: 1 hora de PlayStation"


class DialogoGestionBonosPlaystation(DialogoGestionBonosBase):
    """
    Catálogo de bonos EXCLUSIVO de la PlayStation 5 (playstation_repo) -- misma
    pantalla que la de bonos de PC y la de socios, con su propia tabla. Solo se
    llega desde Configuración ADMIN (exclusiva de ADMIN); aun así, cada
    alta/cambio/baja vuelve a exigir que el usuario sea Admin en el repo, así que
    la regla no depende de que este botón esté escondido.
    """

    CLASE_FORMULARIO = DialogoBonoPlaystation
    TITULO = "Gestionar Bonos de PlayStation 5"
    CONFIRMAR_DESACTIVAR = (
        "¿Desactivar el bono '{nombre}'? Deja de poder venderse, pero "
        "las ventas que ya lo usaron conservan su historial."
    )

    def __init__(self, usuario, parent=None):
        super().__init__(parent, repo=playstation_repo.AdministradorDeBonos(usuario["id"]))
