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

Desde el 2026-10-29 la ventana es la "ficha del socio" (maqueta B, que eligió el dueño entre
tres): la lista a la izquierda y, a la derecha, la ficha del elegido con sus botones (ver
miembros_ficha.py). "Historial de este socio" y "Historial de Cargas" (el de todos, abajo; el
historial nació el 2026-10-24) abren miembros_historial_cargas.py. "$ Para Reserva" (2026-10-26,
solo el Admin) abre reservas_socio_dialogo.DialogoSaldoParaReserva. "Hace cuánto no viene" (y su
filtro, con los días a elección, y su orden) salen de ultima_visita_repo: en naranja pasados
dominio.DIAS_SIN_VENIR_AVISO días.

La configuración de la tabla de tramos de tarifa $/hora (ver
config_repo.obtener_tramos_tarifa_hora_miembro) y la gestión del
catálogo de Bonos exclusivo de socios (bonos_miembro_repo, distinto del
de walk-ins que administra pcs_gestion_dialogos.DialogoGestionBonos) son tareas de
EDICIÓN de catálogo, exclusivas de ADMIN — sus pantallas
(DialogoTramosTarifaMiembro, DialogoGestionBonosMiembro) siguen viviendo
acá porque son del dominio de Miembros, pero el botón que las abre está
en ui/main_window.ConfiguracionAdminWindow, no en esta ventana.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QFormLayout, QHBoxLayout, QHeaderView, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QSpinBox, QStackedWidget, QTableWidget, QVBoxLayout, QWidget,
)

import dominio
from repositories import config_repo
from control_pcs.repositories import (
    bonos_miembro_repo, historial_cargas_repo, miembros_repo, ultima_visita_repo,
)
from control_pcs.ui.bonos_dialogos import DialogoBonoBase, DialogoGestionBonosBase
from control_pcs.ui.dibujos_de_ventana import icono_de, pixmap_de, poner_icono
# texto_no_viene y detalle_de_la_visita viven en miembros_ficha: texto_no_viene se sigue
# pudiendo importar de acá (lo usan las pruebas).
from control_pcs.ui.miembros_ficha import (  # noqa: F401
    ROL_DATOS, DelegadoDeSocios, FichaDelSocio, Segmentos, detalle_de_la_visita, texto_no_viene,
)
from control_pcs.ui.miembros_historial_cargas import VentanaHistorialCargas
from control_pcs.ui.reservas_socio_dialogo import DialogoSaldoParaReserva
from ui.dialogo_pago import cobrar
from ui.piezas_ventana import TONO_AZUL, TONO_GRIS, TONO_NARANJA, TONO_VERDE, agregar_pastilla, cabecera_oscura, \
    panel_blanco, tecla
from ui.utils import (
    CampoPesos, formato_pesos, formato_tiempo, mostrar_error, mostrar_info, confirmar, manejar_errores,
    encadenar_enter, sin_boton_por_defecto, fila_guardar_cancelar, fila_agregar_quitar, fecha_iso, hoy_del_local,
)

# Tamaño de la ventana: alta, para ver muchos socios en la lista sin bajar (pedido del dueño,
# 2026-10-20), y ancha para tener la ficha del socio al lado (diseño del 2026-10-29). Ninguna
# pasa del tamaño de la pantalla.
ALTO_DE_LA_VENTANA = 960
ANCHO_DE_LA_VENTANA = 1240

# Los filtros de arriba de la lista: (clave, texto). El de "no vienen" lleva los días que se
# elijan (ver MiembrosWindow._al_cambiar_los_dias).
FILTROS = (("todos", "Todos"), ("con_saldo", "Con saldo"),
           ("no_vienen", f"No vienen +{dominio.DIAS_SIN_VENIR_AVISO} días"), ("sin_dni", "Sin DNI"))
# Cómo se ordena la lista (clave, texto). "usuario" es el de siempre.
ORDENES = (("usuario", "Por usuario (A-Z)"), ("mas", "Más tiempo sin venir"), ("menos", "Menos tiempo sin venir"))


class MiembrosWindow(QDialog):
    """Administración de Miembros: a la izquierda la lista de socios (con buscador y filtros) y a
    la derecha la ficha del que está elegido, con los botones que actúan sobre él: modificar,
    cargar saldo, ver sus cargas y desactivarlo. Abajo, lo que no es de un socio en particular:
    "$ Para Reserva", el Historial de Cargas de todos y Salir."""

    def __init__(self, usuario_operador, parent=None):
        super().__init__(parent)
        self.usuario_operador = usuario_operador
        self.setWindowTitle("Administración de Miembros")
        alto, ancho = ALTO_DE_LA_VENTANA, ANCHO_DE_LA_VENTANA
        if self.screen() is not None:
            disponible = self.screen().availableGeometry()
            alto = min(alto, disponible.height() - 80)
            ancho = min(ancho, disponible.width() - 20)
        self.resize(ancho, alto)
        # Lo que se ve, en el mismo orden que la lista: _seleccionado lee de acá por número de fila.
        self.miembros = []
        self._visitas = {}
        self._dias = {}
        self._armar_interfaz()
        self._cargar_grilla()

    def _armar_interfaz(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(12, 12, 12, 12)
        raiz.setSpacing(10)

        cabecera = cabecera_oscura("", "Miembros", "Elegí un socio y hacé todo desde su ficha")
        cabecera.icono.setPixmap(pixmap_de("usuario", 30, "#EAF4FF", 1.6))
        self.pastilla_socios = agregar_pastilla(cabecera, "", TONO_AZUL)
        self.pastilla_con_saldo = agregar_pastilla(cabecera, "", TONO_VERDE)
        self.pastilla_sin_dni = agregar_pastilla(cabecera, "", TONO_NARANJA)
        self.pastilla_sin_venir = agregar_pastilla(cabecera, "", TONO_GRIS)
        self.pastilla_sin_venir.setToolTip("Incluye a los que nunca vinieron.")
        raiz.addWidget(cabecera)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)

        # ---- la lista
        izquierda, capa = panel_blanco()
        izquierda.setFixedWidth(480)
        self.campo_buscar = QLineEdit()
        self.campo_buscar.setPlaceholderText("Buscar por usuario...")
        self.campo_buscar.setClearButtonEnabled(True)
        self.campo_buscar.addAction(icono_de("lupa", 18, "#8A94A6"), QLineEdit.ActionPosition.LeadingPosition)
        self.campo_buscar.textChanged.connect(self._cargar_grilla)
        self.boton_nuevo = tecla("Nuevo", self._nuevo_miembro, "teclaVerde")
        poner_icono(self.boton_nuevo, "mas", 16, "#FFFFFF")
        fila_buscar = QHBoxLayout()
        fila_buscar.setSpacing(8)
        fila_buscar.addWidget(self.campo_buscar, 1)
        fila_buscar.addWidget(self.boton_nuevo)
        capa.addLayout(fila_buscar)

        self.segmentos = Segmentos(FILTROS)
        self.segmentos.cambio.connect(self._al_cambiar_el_filtro)
        capa.addWidget(self.segmentos)

        self.check_inactivos = QCheckBox("Mostrar inactivos")
        self.check_inactivos.stateChanged.connect(self._cargar_grilla)
        # Los que no vienen hace más de N días (pedido del dueño, 2026-10-24): para armar la
        # lista de a quién escribirle por WhatsApp. Solo se ve con ese filtro elegido.
        self.campo_dias_sin_venir = QSpinBox()
        self.campo_dias_sin_venir.setRange(1, 999)
        self.campo_dias_sin_venir.setValue(dominio.DIAS_SIN_VENIR_AVISO)
        self.campo_dias_sin_venir.setSuffix(" días")
        # Sin flechitas, como la cantidad de Impresiones: con esta hoja de estilos salían
        # como una rayita, y el número se escribe.
        self.campo_dias_sin_venir.setButtonSymbols(QSpinBox.NoButtons)
        self.campo_dias_sin_venir.setFixedWidth(90)
        self.campo_dias_sin_venir.valueChanged.connect(self._al_cambiar_los_dias)
        self.caja_dias = QWidget()
        capa_dias = QHBoxLayout(self.caja_dias)
        capa_dias.setContentsMargins(0, 0, 0, 0)
        capa_dias.setSpacing(8)
        capa_dias.addWidget(QLabel("No vienen hace más de"))
        capa_dias.addWidget(self.campo_dias_sin_venir)
        capa_dias.addStretch()
        self.caja_dias.setVisible(False)
        capa.addWidget(self.caja_dias)
        self.combo_orden = QComboBox()
        for clave, texto in ORDENES:
            self.combo_orden.addItem(texto, clave)
        self.combo_orden.setMinimumWidth(190)
        self.combo_orden.currentIndexChanged.connect(self._cargar_grilla)
        fila_opciones = QHBoxLayout()
        fila_opciones.setSpacing(10)
        fila_opciones.addWidget(self.check_inactivos)
        fila_opciones.addStretch()
        fila_opciones.addWidget(self.combo_orden)
        capa.addLayout(fila_opciones)

        self.lista = QListWidget()
        self.lista.setItemDelegate(DelegadoDeSocios(self.lista))
        self.lista.setStyleSheet("QListWidget { border: none; background: transparent; outline: none; }")
        self.lista.setMouseTracking(True)
        self.lista.setUniformItemSizes(True)
        self.lista.setVerticalScrollMode(QListWidget.ScrollPerPixel)
        self.lista.currentRowChanged.connect(self._al_cambiar_la_fila)
        self.lista.itemDoubleClicked.connect(lambda _item: self._modificar_miembro())
        capa.addWidget(self.lista, 1)
        cuerpo.addWidget(izquierda)

        # ---- la ficha del elegido
        self.ficha = FichaDelSocio()
        self.ficha.boton_modificar.clicked.connect(self._modificar_miembro)
        self.ficha.boton_cargar_saldo.clicked.connect(self._cargar_saldo)
        self.ficha.boton_historial.clicked.connect(self._ver_historial_del_socio)
        self.ficha.boton_desactivar.clicked.connect(self._desactivar_miembro)
        cuerpo.addWidget(self.ficha, 1)
        raiz.addLayout(cuerpo, 1)

        # ---- abajo: lo que no es de un socio en particular
        # Cuántas horas de saldo necesita un socio para reservar sin seña (pedido del dueño,
        # 2026-10-26): lo cambia solo el Admin; los demás lo ven en gris y con candado.
        es_admin = dominio.es_admin(self.usuario_operador)
        self.boton_saldo_para_reserva = tecla("$ Para Reserva" if es_admin else "$ Para Reserva  🔒")
        self.boton_saldo_para_reserva.setEnabled(es_admin)
        self.boton_saldo_para_reserva.setToolTip(
            "Las horas de saldo que necesita un socio para reservar" if es_admin else "Solo el Administrador")
        self.boton_saldo_para_reserva.clicked.connect(
            lambda: DialogoSaldoParaReserva(self.usuario_operador, self).exec())
        # Las cargas de TODOS los socios (pedido del dueño, 2026-10-24); las de uno solo se ven
        # con "Historial de este socio", en su ficha.
        self.boton_historial_todos = tecla("Historial de Cargas", self._ver_historial_de_todos)
        poner_icono(self.boton_historial_todos, "reloj")
        boton_salir = tecla("Salir", self.close)
        pie = QHBoxLayout()
        pie.setSpacing(8)
        pie.addWidget(self.boton_saldo_para_reserva)
        pie.addWidget(self.boton_historial_todos)
        pie.addStretch()
        pie.addWidget(boton_salir)
        raiz.addLayout(pie)

        sin_boton_por_defecto(self)
        # Se abre escribiendo el usuario: casi siempre se busca a alguien.
        self.campo_buscar.setFocus()

    @manejar_errores
    def _cargar_grilla(self, _=None):
        # El "_=None" absorbe lo que mandan textChanged, stateChanged y currentIndexChanged.
        elegido = self._id_elegido()
        miembros = miembros_repo.listar_miembros(
            incluir_inactivos=self.check_inactivos.isChecked(), texto_busqueda=self.campo_buscar.text(),
        )
        visitas = ultima_visita_repo.ultimas_visitas()
        ahora = datetime.now()
        # Las cifras de la cabecera son de todos los socios activos, se filtre lo que se filtre.
        activos = miembros_repo.listar_miembros()
        dias = {m["id"]: ultima_visita_repo.dias_sin_venir(visitas.get(m["id"]), ahora) for m in (*activos, *miembros)}
        self._actualizar_cifras(activos, dias)
        miembros = self._filtrar(miembros, dias)
        orden = self.combo_orden.currentData()
        if orden != "usuario":
            # El que nunca vino cuenta como el que hace más que no viene.
            miembros = sorted(miembros, key=lambda m: float("inf") if dias[m["id"]] is None else dias[m["id"]],
                              reverse=orden == "mas")
        self.miembros, self._visitas, self._dias = miembros, visitas, dias

        self.lista.blockSignals(True)
        self.lista.clear()
        for miembro in miembros:
            renglon = QListWidgetItem()
            renglon.setData(ROL_DATOS, {"miembro": miembro, "dias": dias[miembro["id"]]})
            renglon.setToolTip(detalle_de_la_visita(visitas.get(miembro["id"])))
            self.lista.addItem(renglon)
        # Sigue elegido el mismo socio (o el primero): la ficha nunca queda vacía habiendo socios.
        fila = next((i for i, m in enumerate(miembros) if m["id"] == elegido), 0 if miembros else -1)
        self.lista.setCurrentRow(fila)
        self.lista.blockSignals(False)
        if fila >= 0:
            self.lista.scrollToItem(self.lista.item(fila))
        self._mostrar_la_ficha()

    def _filtrar(self, miembros, dias):
        filtro = self.segmentos.elegido()
        if filtro == "con_saldo":
            return [m for m in miembros if m["saldo_minutos"] > 0]
        if filtro == "sin_dni":
            return [m for m in miembros if not miembros_repo.tiene_dni(m)]
        if filtro == "no_vienen":
            limite = self.campo_dias_sin_venir.value()
            return [m for m in miembros if ultima_visita_repo.no_viene_hace_mas_de(dias[m["id"]], limite)]
        return miembros

    def _actualizar_cifras(self, activos, dias):
        limite = dominio.DIAS_SIN_VENIR_AVISO
        con_saldo = sum(1 for m in activos if m["saldo_minutos"] > 0)
        sin_dni = sum(1 for m in activos if not miembros_repo.tiene_dni(m))
        sin_venir = sum(1 for m in activos if ultima_visita_repo.no_viene_hace_mas_de(dias[m["id"]], limite))
        self.pastilla_socios.setText("1 SOCIO" if len(activos) == 1 else f"{len(activos)} SOCIOS")
        self.pastilla_con_saldo.setText(f"{con_saldo} CON SALDO")
        self.pastilla_sin_dni.setText(f"{sin_dni} SIN DNI")
        self.pastilla_sin_venir.setText(f"{sin_venir} NO VIENEN HACE +{limite} DÍAS")

    @manejar_errores
    def _mostrar_la_ficha(self):
        miembro = self._elegido()
        if miembro is None:
            self.ficha.vaciar()
            return
        hoy = hoy_del_local()
        cargas = historial_cargas_repo.listar_cargas(
            fecha_iso(hoy.addYears(-1)), fecha_iso(hoy), miembro_id=miembro["id"])
        self.ficha.mostrar(miembro, self._dias[miembro["id"]], self._visitas.get(miembro["id"]), cargas)

    def _al_cambiar_la_fila(self, _fila):
        self._mostrar_la_ficha()

    def _al_cambiar_el_filtro(self, clave):
        self.caja_dias.setVisible(clave == "no_vienen")
        self._cargar_grilla()

    def _al_cambiar_los_dias(self, dias):
        self.segmentos.poner_texto("no_vienen", f"No vienen +{dias} días")
        if self.segmentos.elegido() == "no_vienen":
            self._cargar_grilla()

    def _elegido(self):
        fila = self.lista.currentRow()
        return self.miembros[fila] if 0 <= fila < len(self.miembros) else None

    def _id_elegido(self):
        miembro = self._elegido()
        return miembro["id"] if miembro is not None else None

    def _seleccionado(self):
        miembro = self._elegido()
        if miembro is None:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un socio de la lista.")
        return miembro

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

    def _ver_historial_del_socio(self):
        miembro = self._seleccionado()
        if miembro is not None:
            VentanaHistorialCargas(self, miembro).exec()

    def _ver_historial_de_todos(self):
        VentanaHistorialCargas(self, None).exec()

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
    cobrar plata.

    `a_la_sesion=False` (lo usa Reserva de socio): lo cargado queda en el saldo
    aunque el socio esté usando una PC, porque es para el día de la reserva."""

    def __init__(self, usuario_operador, miembro, parent=None, a_la_sesion: bool = True):
        super().__init__(parent)
        self.usuario_operador = usuario_operador
        self.miembro = miembro
        self.a_la_sesion = a_la_sesion
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
        self.spin_monto = CampoPesos()
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
            resultado = miembros_repo.cargar_saldo_por_monto(
                self.miembro["id"], monto, pagos, self.usuario_operador["id"], a_la_sesion=self.a_la_sesion
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
            resultado = miembros_repo.cargar_saldo_por_bono(
                self.miembro["id"], bono_id, pagos, self.usuario_operador["id"], a_la_sesion=self.a_la_sesion
            )
        # Si el socio está usando una PC, lo cargado ya corre en esa sesión
        # (miembros_repo._sumar_carga_a_la_sesion): que el operador lo sepa.
        sumado = resultado["sumado_a_la_sesion"]
        if sumado is not None:
            mostrar_info(
                self, "Saldo cargado",
                f"Se le sumaron {formato_tiempo(sumado['minutos'] * 60)} a su sesión en "
                f"{sumado['estacion']}: le aparecen en la PC en unos segundos.",
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
        spin = CampoPesos()
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
