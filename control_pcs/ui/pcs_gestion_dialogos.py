"""
pcs_gestion_dialogos.py
=========================
Diálogos para ADMINISTRAR los catálogos de Estaciones (las PCs del local, su
IP y la contraseña de admin de los Clientes PC) y de Bonos de Tiempo de walk-ins (mismo
espíritu que "Gestionar Rubros" en Artículos), más los de la PlayStation 5 y los
de PCSTREAM. Solo se abren desde `ConfiguracionAdminWindow` (ui/configuracion_admin_window.py):
los de bonos, solo un ADMIN; Gestionar Estaciones, también un Operador, salvo
la contraseña de las PCs clientes y Actualizar el Cliente PC (pedido del dueño,
2026-10-19). Los bonos exclusivos de socios se gestionan aparte, en
miembros_window.py.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableWidgetItem, QVBoxLayout,
)

import dominio
from admin_remoto import modo as modo_remoto
from control_pcs.repositories import clientes_repo, pcs_repo, pcstream_repo, playstation_repo
from control_pcs.ui.bonos_dialogos import DialogoBonoBase, DialogoGestionBonosBase
from control_pcs.ui.pcs_actualizacion_dialogo import DialogoActualizarCliente
from control_pcs.ui.pcs_filtro_dialogo import DialogoFiltroPalabras
from control_pcs.ui.pcs_fondo_dialogo import DialogoFondoPantalla
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_ROJO, agregar_pastilla, bloquear_tarjeta, cabecera_oscura, linea_divisoria,
    panel_blanco, tarjeta_de_menu, tecla, titulo_de_seccion,
)
from ui.utils import (
    confirmar, encadenar_enter, manejar_errores, mostrar_error,
    mostrar_info, sin_boton_por_defecto, crear_tabla,
)


class _DelegadoIp(QStyledItemDelegate):
    """La columna "IP asentada" de Gestionar Estaciones: la IP en letra de máquina
    (se leen mejor los números) y, si la estación no tiene, "todavía no se conectó"
    en gris. El texto de la celda sigue siendo la IP o nada: esto es solo cómo se ve."""

    def paint(self, pintor, opcion, indice):
        opcion = QStyleOptionViewItem(opcion)
        self.initStyleOption(opcion, indice)
        if opcion.text:
            opcion.font = QFont("Consolas", 10)
        opcion.widget.style().drawControl(QStyle.CE_ItemViewItem, opcion, pintor, opcion.widget)
        if opcion.text:
            return
        pintor.save()
        letra = QFont(opcion.font)
        letra.setItalic(True)
        pintor.setFont(letra)
        pintor.setPen(QColor("#A7ADB8"))
        pintor.drawText(opcion.rect.adjusted(9, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, "todavía no se conectó")
        pintor.restore()


class DialogoGestionEstaciones(QDialog):
    """Alta, renombre y baja de estaciones, IP de cada una, la contraseña de
    admin que usan los Clientes PC, el fondo de su pantalla de bloqueo, su
    filtro de palabras y la actualización de su Cliente PC. (La
    clave de conexión de los Clientes PC es fija: no se gestiona desde ninguna
    pantalla, ver `clientes_repo`.) Solo se llega desde Configuración ADMIN, y la
    usa también un Operador: todo menos la contraseña de las PCs clientes y
    Actualizar el Cliente PC, que ve en gris (pedido del dueño, 2026-10-19).
    Recibe el `usuario` para eso."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Gestionar Estaciones")
        self.resize(920, 760)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        """El diseño que eligió el dueño el 2026-10-26 (maqueta "A"): cabecera oscura
        con cuántas estaciones hay, la lista a la izquierda y a la derecha la elegida
        (su IP, Renombrar y, aparte, Desactivar) y lo que se manda a todas las PCs."""
        es_admin = dominio.es_admin(self.usuario)
        cabecera = cabecera_oscura("🖥️", "Gestionar Estaciones", "Las PCs del local, su IP y lo que se les manda a todas")
        self.pastilla_estaciones = agregar_pastilla(cabecera, "", TONO_AZUL)
        self.pastilla_sin_conectar = agregar_pastilla(cabecera, "", TONO_GRIS)
        self.pastilla_ip_repetida = agregar_pastilla(cabecera, "", TONO_ROJO)

        # Izquierda: la lista, con el alta arriba.
        self.lista = crear_tabla(["Estación", "IP asentada"], estirar=1, por_filas=True, una_sola=True)
        self.lista.setObjectName("tablaEstaciones")
        self.lista.setShowGrid(False)
        self.lista.verticalHeader().setDefaultSectionSize(32)
        self.lista.setColumnWidth(0, 150)
        self.lista.setItemDelegateForColumn(1, _DelegadoIp(self.lista))
        self.lista.itemSelectionChanged.connect(self._al_cambiar_seleccion)

        self.campo_nuevo = QLineEdit()
        self.campo_nuevo.setPlaceholderText("Nombre de la estación nueva (ej. PC 5)...")
        encadenar_enter(self.campo_nuevo, accion_final=self._agregar)
        fila_agregar = QHBoxLayout()
        fila_agregar.addWidget(self.campo_nuevo)
        fila_agregar.addWidget(tecla("＋  AGREGAR", self._agregar, "teclaAzul"))

        panel_lista, capa_lista = panel_blanco()
        capa_lista.addWidget(titulo_de_seccion("Estaciones activas"))
        capa_lista.addLayout(fila_agregar)
        capa_lista.addWidget(self.lista, 1)

        # Derecha, arriba: la estación elegida.
        self.nombre_elegida = QLabel()
        self.nombre_elegida.setObjectName("nombreEstacion")

        # IP asentada de la estación seleccionada: la asienta sola
        # pcs_repo.registrar_conexion la PRIMERA vez que el Cliente PC de esa PC
        # se conecta (la IP real del pedido, no un dato que mande el cliente) y
        # después no se pisa: con ella se reconoce a la PC si el nombre que
        # manda no coincide con ninguna estación (pcs_repo.estado_de_estacion).
        # Una estación cuyo Cliente PC todavía no conectó no tiene nada que
        # mostrar. "Traer IP" relee la base por si la PC conectó recién, sin
        # cerrar el diálogo; "Borrar IP" la olvida para que se asiente de nuevo.
        self.campo_ip = QLineEdit()
        self.campo_ip.setObjectName("campoIpAsentada")
        self.campo_ip.setReadOnly(True)
        self.campo_ip.setPlaceholderText("Se asienta sola al conectarse")
        fila_ip = QHBoxLayout()
        fila_ip.addWidget(self.campo_ip, 1)
        fila_ip.addWidget(tecla("TRAER IP", self._traer_ip))
        fila_ip.addWidget(tecla("BORRAR IP", self._borrar_ip))

        # Lo que conviene saber de esa IP (repetida en otra estación, o la PC se
        # conecta desde otra); oculto si está todo bien.
        self.aviso_ip = QLabel()
        self.aviso_ip.setObjectName("avisoIp")
        self.aviso_ip.setWordWrap(True)
        self.aviso_ip.hide()

        # Desactivar, en rojo y en la otra punta: que no se apriete por Renombrar.
        fila_acciones = QHBoxLayout()
        fila_acciones.addWidget(tecla("✏️  RENOMBRAR", self._renombrar))
        fila_acciones.addStretch()
        fila_acciones.addWidget(tecla("DESACTIVAR", self._desactivar, "teclaRoja"))

        panel_elegida, capa_elegida = panel_blanco()
        capa_elegida.addWidget(titulo_de_seccion("Estación elegida"))
        capa_elegida.addWidget(self.nombre_elegida)
        capa_elegida.addWidget(titulo_de_seccion("IP asentada"))
        capa_elegida.addLayout(fila_ip)
        capa_elegida.addWidget(self.aviso_ip)
        capa_elegida.addWidget(linea_divisoria())
        capa_elegida.addLayout(fila_acciones)

        # Derecha, abajo: lo que se manda a todas las PCs.
        panel_todas, capa_todas = panel_blanco()
        capa_todas.setSpacing(8)
        capa_todas.addWidget(titulo_de_seccion("Para todas las PCs"))
        capa_todas.addWidget(tarjeta_de_menu(
            "🖼️", "Fondo de pantalla", "La imagen de la pantalla de bloqueo", self._abrir_fondo, alto=50))
        capa_todas.addWidget(tarjeta_de_menu(
            "🚫", "Filtro de palabras", "Lo que no se puede escribir en las PCs", self._abrir_filtro, alto=50))
        # Solo un Admin (con esa contraseña se sale del bloqueo de una PC): el
        # Operador la ve en gris, con candado.
        tarjeta_clave = tarjeta_de_menu(
            "🔑", "Contraseña de las PCs", "La de la \"A\" de la pantalla de bloqueo",
            self._cambiar_clave_admin_pcs, alto=50)
        if not es_admin:
            bloquear_tarjeta(tarjeta_clave)
        capa_todas.addWidget(tarjeta_clave)
        # Mandar una versión nueva del Cliente PC firma el .exe con la clave que
        # vive en la PC del mostrador: solo se hace ahí (no desde otra PC).
        if not modo_remoto.es_copia_remota():
            tarjeta_actualizar = tarjeta_de_menu(
                "⬆️", "Actualizar el Cliente PC", "Manda la versión nueva a todas las PCs",
                self._abrir_actualizacion, alto=50)
            # Y solo un Admin: lo que se manda se instala en todas las PCs. El
            # Operador lo ve en gris.
            if not es_admin:
                bloquear_tarjeta(tarjeta_actualizar)
            capa_todas.addWidget(tarjeta_actualizar)

        derecha = QVBoxLayout()
        derecha.setSpacing(12)
        derecha.addWidget(panel_elegida)
        derecha.addWidget(panel_todas)
        derecha.addStretch()
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        cuerpo.addWidget(panel_lista, 11)
        cuerpo.addLayout(derecha, 10)

        pie = QHBoxLayout()
        pie.addStretch()
        pie.addWidget(tecla("CERRAR", self.close, "teclaRoja"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(cuerpo, 1)
        layout.addLayout(pie)
        sin_boton_por_defecto(self)
        self.campo_nuevo.setFocus()

    @manejar_errores
    def _cargar(self, seleccionar_id: int = None):
        """Recarga la lista (con la IP asentada de cada una; en rojo si está
        repetida), las pastillas de la cabecera y, si se pide, vuelve a dejar
        elegida esa estación."""
        self.estaciones = pcs_repo.listar_estaciones()
        self.ips_repetidas = pcs_repo.ips_asentadas_repetidas()
        self.lista.setRowCount(0)
        for estacion in self.estaciones:
            fila = self.lista.rowCount()
            self.lista.insertRow(fila)
            item_nombre = QTableWidgetItem(estacion["nombre"])
            letra = item_nombre.font()
            letra.setBold(True)
            item_nombre.setFont(letra)
            self.lista.setItem(fila, 0, item_nombre)
            item_ip = QTableWidgetItem(estacion["ip_asentada"] or "")
            if estacion["ip_asentada"] in self.ips_repetidas:
                item_ip.setForeground(Qt.red)
            self.lista.setItem(fila, 1, item_ip)
            if estacion["id"] == seleccionar_id:
                self.lista.setCurrentCell(fila, 0)

        sin_conectar = sum(1 for estacion in self.estaciones if not estacion["ip_asentada"])
        con_ip_repetida = sum(1 for estacion in self.estaciones if estacion["ip_asentada"] in self.ips_repetidas)
        self.pastilla_estaciones.setText(f"{len(self.estaciones)} ESTACIONES")
        self.pastilla_sin_conectar.setText(f"{sin_conectar} SIN CONECTAR")
        self.pastilla_sin_conectar.setVisible(bool(sin_conectar))
        self.pastilla_ip_repetida.setText(f"{con_ip_repetida} CON IP REPETIDA")
        self.pastilla_ip_repetida.setVisible(bool(con_ip_repetida))
        self._al_cambiar_seleccion()

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
        """Al cambiar de fila, muestra la IP asentada ya cargada en memoria (la
        que trajo el último `_cargar()`) sin ir a la base -- `_traer_ip` es la
        que relee fresco si hace falta -- y, si corresponde, un aviso sobre ella."""
        fila = self.lista.currentRow()
        if fila < 0 or fila >= len(self.estaciones):
            self.nombre_elegida.setText("—")
            self.campo_ip.clear()
            self.aviso_ip.hide()
            return
        estacion = self.estaciones[fila]
        self.nombre_elegida.setText(estacion["nombre"])
        self.campo_ip.setText(estacion["ip_asentada"] or "")
        aviso = self._aviso_de_ip(estacion)
        self.aviso_ip.setText(aviso)
        self.aviso_ip.setVisible(bool(aviso))

    def _aviso_de_ip(self, estacion) -> str:
        ip = estacion["ip_asentada"]
        if ip in self.ips_repetidas:
            otras = ", ".join(
                otra["nombre"] for otra in self.estaciones
                if otra["ip_asentada"] == ip and otra["id"] != estacion["id"]
            )
            return (
                f"⚠ Esta IP también está asentada en {otras}. Mientras esté repetida, "
                "ninguna de esas PCs se reconoce por su IP: borrá la que no corresponde."
            )
        if ip and estacion["ultima_ip"] and estacion["ultima_ip"] != ip:
            return (
                f"La última conexión llegó desde {estacion['ultima_ip']}, no desde la IP "
                "asentada. Si le cambiaste la IP a esta PC, borrá la asentada: se asienta "
                "la nueva sola."
            )
        return ""

    @manejar_errores
    def _traer_ip(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        self._cargar(seleccionar_id=estacion["id"])
        if not self.campo_ip.text():
            mostrar_error(
                self, "Todavía no hay IP",
                f"'{estacion['nombre']}' todavía no se conectó nunca.\n\n"
                "Configurá el Cliente PC en esa PC con este mismo nombre de "
                "estación y esperá unos segundos: pregunta solo cada 5s, y "
                "recién ahí queda la IP asentada acá."
            )

    @manejar_errores
    def _borrar_ip(self):
        estacion = self._seleccionada()
        if estacion is None or not estacion["ip_asentada"]:
            return
        if confirmar(self, "Borrar IP asentada",
                     f"¿Borrar la IP asentada de '{estacion['nombre']}' ({estacion['ip_asentada']})?\n\n"
                     "La próxima vez que esa PC se conecte con su nombre, se asienta sola "
                     "la IP que tenga en ese momento."):
            pcs_repo.borrar_ip_asentada(estacion["id"])
            self._cargar(seleccionar_id=estacion["id"])

    def _abrir_fondo(self):
        """El fondo de la pantalla de bloqueo de todas las PCs (ver pcs_fondo_dialogo)."""
        DialogoFondoPantalla(self).exec()

    def _abrir_filtro(self):
        """El filtro de palabras de todas las PCs (ver pcs_filtro_dialogo)."""
        DialogoFiltroPalabras(self).exec()

    def _abrir_actualizacion(self):
        """Mandar una versión nueva del Cliente PC a las PCs (ver pcs_actualizacion_dialogo)."""
        DialogoActualizarCliente(self).exec()

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


class DialogoBonoPcstream(DialogoBonoBase):
    """Alta/edición de un bono de PCSTREAM (pcstream_repo). Mismo formulario
    que los otros catálogos."""

    repo = pcstream_repo
    TITULO_NUEVO = f"Nuevo Bono de {dominio.NOMBRE_PCSTREAM}"
    TITULO_EDICION = f"Modificar Bono de {dominio.NOMBRE_PCSTREAM}"
    EJEMPLO_NOMBRE = "Ej: 2 horas de stream"


class DialogoGestionBonosPcstream(DialogoGestionBonosBase):
    """
    Catálogo de bonos EXCLUSIVO de PCSTREAM, la PC de streaming (pcstream_repo):
    lo que se le ofrece en el panel de Control de PCs cuando se la elige, en vez
    de los bonos comunes. Solo se llega desde Configuración ADMIN, igual que el
    catálogo de las demás PCs.
    """

    repo = pcstream_repo
    CLASE_FORMULARIO = DialogoBonoPcstream
    TITULO = f"Gestionar Bonos de {dominio.NOMBRE_PCSTREAM}"
    CONFIRMAR_DESACTIVAR = (
        "¿Desactivar el bono '{nombre}'? Deja de poder venderse, pero "
        "las sesiones que ya lo usaron conservan su historial."
    )
