"""
pcs_detalle.py
===============
Panel lateral de "Control de PCs" (`PanelDetalleEstacion`): todas las
acciones sobre lo que esté seleccionado en la grilla de pcs_window.py — una
PC o la PlayStation 5 — vender/agregar un bono, abrir con Miembro (solo PCs),
finalizar la sesión — y el diálogo con el que un socio se loguea solo
(`DialogoLoginMiembro`).
"""

from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)
from PySide6.QtCore import Qt, QTimer

import dominio
from control_pcs.repositories import miembros_repo, pcs_repo, playstation_repo
from ui.dialogo_pago import resolver_pagos
from ui.utils import (
    aplicar_clase, confirmar, encadenar_enter, fila_guardar_cancelar, formato_pesos,
    formato_tiempo, manejar_errores, mostrar_error, mostrar_info, sin_boton_por_defecto,
)


class _ListaDeBonos:
    """
    Una lista de bonos como botones (uno elegido a la vez) con su título. El
    panel tiene DOS, separadas y una debajo de la otra: la de los bonos de PC y
    la de los bonos de la PlayStation 5 (catálogos distintos, ver
    playstation_repo). Nunca comparten botones ni grupo, así que lo que está
    tildado en una no puede terminar usándose para la otra.
    """

    def __init__(self, titulo: str, aviso_sin_bonos: str, padre):
        self.etiqueta = QLabel(titulo)
        self.aviso_sin_bonos = QLabel(aviso_sin_bonos)
        self.aviso_sin_bonos.setWordWrap(True)
        self.aviso_sin_bonos.setStyleSheet("color: #7A869A;")
        self.layout = QVBoxLayout()
        self.layout.setSpacing(6)  # los bonos como botones separados, no pegados en un bloque
        self.grupo = QButtonGroup(padre)
        self.grupo.setExclusive(True)
        self.grupo.idClicked.connect(self._recordar)
        self.bonos = []
        self._elegido_id = None
        self._habilitada = False

    def _recordar(self, bono_id: int):
        self._elegido_id = bono_id

    def cargar(self, bonos, habilitada: bool):
        """Vuelve a armar los botones con `bonos` (filas de un catálogo). Si el
        bono que estaba elegido sigue en la lista queda elegido -- la grilla se
        refresca sola cada 5 segundos y esto se llama cada vez: sin esto, el
        operador que tildó "3 horas" lo vería volver al primero justo antes de
        cobrar."""
        while self.layout.count():
            hijo = self.layout.takeAt(0)
            if hijo.widget():
                hijo.widget().deleteLater()
        for boton in self.grupo.buttons():
            self.grupo.removeButton(boton)

        self.bonos = list(bonos)
        ids = [bono["id"] for bono in self.bonos]
        elegido = self._elegido_id if self._elegido_id in ids else (ids[0] if ids else None)
        for bono in self.bonos:
            boton = QPushButton(f"{bono['nombre']} — {formato_pesos(bono['precio'])}")
            boton.setCheckable(True)
            boton.setChecked(bono["id"] == elegido)
            # Se crean después de _armar_interfaz, así que no los alcanzó
            # sin_boton_por_defecto: hay que hacerlo uno por uno.
            boton.setAutoDefault(False)
            boton.setDefault(False)
            self.grupo.addButton(boton, bono["id"])
            self.layout.addWidget(boton)
        self._elegido_id = elegido
        self.aviso_sin_bonos.setVisible(not self.bonos)
        self.habilitar(habilitada)

    def habilitar(self, habilitada: bool):
        """Habilita o deshabilita TODA la lista (título incluido, que se ve
        apagado): una lista deshabilitada no se puede tocar ni cobrar."""
        self._habilitada = habilitada
        self.etiqueta.setEnabled(habilitada)
        for boton in self.grupo.buttons():
            boton.setEnabled(habilitada)

    @property
    def habilitada(self) -> bool:
        return self._habilitada

    def bono_elegido(self):
        """La fila del bono tildado, o None si la lista está vacía."""
        bono_id = self.grupo.checkedId()
        return next((bono for bono in self.bonos if bono["id"] == bono_id), None)


class PanelDetalleEstacion(QFrame):
    """
    Panel lateral de "Control de PCs": todas las acciones sobre lo seleccionado
    en la grilla — vender/agregar un bono, abrir con Miembro, finalizar la
    sesión — viven acá en vez de un diálogo aparte por cada una, para que el
    Operador resuelva todo sin salir de esta pantalla.

    Lo seleccionado puede ser una PC o la PlayStation 5 (`item["dispositivo"]`),
    y los bonos se reparten así -- pedido explícito del dueño, para que nunca se
    aplique un bono al equipo equivocado:
    - Los bonos de PC arriba y los de la PlayStation 5 debajo, siempre a la vista.
    - Con la PlayStation 5 elegida, los de PC quedan deshabilitados; con una PC
      elegida, los de la PlayStation 5. Sin nada elegido, los dos.
    - "Iniciar Sesión"/"Agregar Bono" toma el bono de la lista que corresponde al
      equipo elegido, y solo de esa: no hay un camino que cruce las dos.
    La PlayStation 5 además exige el permiso operativo (ver
    playstation_repo.puede_operar): sin él, ve la consola pero no puede vender ni liberar.
    """

    def __init__(self, usuario, avisar_cambio, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self._avisar_cambio = avisar_cambio  # sin argumentos: le pide a PanelControlPcs que se refresque
        self.item = None
        self._equipo_mostrado = None  # (dispositivo, id) de lo último que se mostró, ver mostrar()
        self.setFixedWidth(260)
        self._armar_interfaz()
        self.mostrar(None)

    def _armar_interfaz(self):
        self.etiqueta_titulo = QLabel("Elegí una estación de la grilla")
        self.etiqueta_titulo.setWordWrap(True)
        self.etiqueta_titulo.setStyleSheet("font-weight: 600; font-size: 15px;")

        self.etiqueta_estado = QLabel("")
        self.etiqueta_estado.setWordWrap(True)

        self.lista_pc = _ListaDeBonos(
            "Bonos de PC:",
            "Todavía no hay bonos de PC: el Admin los crea desde Configuración ADMIN.",
            self,
        )
        self.lista_playstation = _ListaDeBonos(
            f"Bonos de {dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION]}:",
            "Todavía no hay bonos de PlayStation 5: el Admin los crea desde Configuración ADMIN.",
            self,
        )

        # Las dos listas van en un área con scroll: entre las dos pueden tener
        # más botones de los que entran en la altura de la ventana, y el método
        # de pago y los botones de acción tienen que quedar siempre a la vista.
        contenedor_bonos = QWidget()
        layout_bonos = QVBoxLayout(contenedor_bonos)
        layout_bonos.setContentsMargins(0, 0, 0, 0)
        for lista in (self.lista_pc, self.lista_playstation):
            layout_bonos.addWidget(lista.etiqueta)
            layout_bonos.addWidget(lista.aviso_sin_bonos)
            layout_bonos.addLayout(lista.layout)
        layout_bonos.addStretch()

        self.area_bonos = QScrollArea()
        self.area_bonos.setWidgetResizable(True)
        self.area_bonos.setFrameShape(QFrame.NoFrame)
        self.area_bonos.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.area_bonos.setMinimumHeight(120)
        self.area_bonos.setStyleSheet("QScrollArea { background: transparent; }")
        contenedor_bonos.setStyleSheet("QWidget#contenedorBonos { background: transparent; }")
        contenedor_bonos.setObjectName("contenedorBonos")
        self.area_bonos.setWidget(contenedor_bonos)

        self.combo_metodo = QComboBox()
        for metodo in (dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL, dominio.PAGO_MIXTO):
            self.combo_metodo.addItem(dominio.NOMBRE_METODO_PAGO[metodo], metodo)

        self.boton_iniciar = QPushButton("Iniciar Sesión")
        aplicar_clase(self.boton_iniciar, "primario")
        self.boton_iniciar.clicked.connect(self._confirmar_bono)

        self.boton_miembro = QPushButton("Abrir con Miembro...")
        self.boton_miembro.clicked.connect(self._abrir_con_miembro)

        self.boton_finalizar = QPushButton("Finalizar Sesión")
        aplicar_clase(self.boton_finalizar, "peligro")
        self.boton_finalizar.clicked.connect(self._finalizar_sesion)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.etiqueta_estado)
        layout.addWidget(self.area_bonos, 1)
        layout.addWidget(QLabel("Método de pago:"))
        layout.addWidget(self.combo_metodo)
        layout.addWidget(self.boton_iniciar)
        layout.addWidget(self.boton_miembro)
        layout.addWidget(self.boton_finalizar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @staticmethod
    def _es_playstation(item) -> bool:
        return item is not None and item["dispositivo"] == dominio.DISPOSITIVO_PLAYSTATION

    def mostrar(self, item):
        """`item` es un elemento de pcs_repo.estado_estaciones() (una PC), el de
        playstation_repo.estado() (la consola), o None si no hay nada
        seleccionado en la grilla."""
        self.item = item
        es_playstation = self._es_playstation(item)
        es_pc = item is not None and not es_playstation
        # La consola solo se opera con el permiso operativo (o siendo Admin).
        puede_operar_consola = es_playstation and playstation_repo.puede_operar(self.usuario)

        self.etiqueta_estado.setVisible(item is not None)
        self.lista_pc.cargar(pcs_repo.listar_bonos(), habilitada=es_pc)
        self.lista_playstation.cargar(playstation_repo.listar_bonos(), habilitada=puede_operar_consola)

        # Cuando la lista de bonos no entra entera en el panel, que se vea la del
        # equipo recién elegido. Solo al CAMBIAR de equipo: este método corre de
        # nuevo con cada refresco de la grilla (cada 5s) y no puede devolver el
        # scroll adonde estaba mientras alguien lo está moviendo a mano.
        equipo = None if item is None else (
            item["dispositivo"], None if es_playstation else item["estacion"]["id"]
        )
        if equipo is not None and equipo != self._equipo_mostrado:
            lista_activa = self.lista_playstation if es_playstation else self.lista_pc
            QTimer.singleShot(0, lambda: self._llevar_el_scroll_a(lista_activa))
        self._equipo_mostrado = equipo

        if item is None:
            self.etiqueta_titulo.setText("Elegí una estación de la grilla")
            for widget in (self.combo_metodo, self.boton_iniciar, self.boton_miembro, self.boton_finalizar):
                widget.setEnabled(False)
            return

        sesion = item["sesion"]
        if es_playstation:
            self.etiqueta_titulo.setText(item["nombre"])
            self.mostrar_estado_playstation(item, puede_operar_consola)
            lista, puede = self.lista_playstation, puede_operar_consola
        else:
            self.etiqueta_titulo.setText(item["estacion"]["nombre"])
            if sesion is None:
                self.etiqueta_estado.setText("🔒 Bloqueada — sin sesión activa.")
            else:
                quien = sesion["miembro_nombre"] or "Bono"
                texto = f"▶ Activa — {formato_tiempo(item['segundos_restantes'])} restantes ({quien})."
                if item["esperando_cliente"]:
                    texto += "\n⏳ El tiempo ya corre; la PC lo toma sola cuando el cliente la prenda."
                self.etiqueta_estado.setText(texto)
            lista, puede = self.lista_pc, True

        self.boton_iniciar.setText("Iniciar Sesión" if sesion is None else "Agregar Bono")
        self.boton_finalizar.setText(
            "Ya avisé: liberar la consola" if es_playstation and item["tiempo_agotado"] else "Finalizar Sesión"
        )
        self.combo_metodo.setEnabled(puede)
        self.boton_iniciar.setEnabled(puede and bool(lista.bonos))
        self.boton_finalizar.setEnabled(puede and sesion is not None)
        # Abrir con el saldo de un socio es cosa de las PCs: la consola se
        # vende solo con bonos.
        self.boton_miembro.setEnabled(es_pc)

    def _llevar_el_scroll_a(self, lista):
        """Sube o baja el área de bonos hasta el título de `lista`. Corre un
        instante después de armar las listas: recién ahí Qt calculó cuánto mide
        el contenido y cuánto se puede desplazar."""
        try:
            self.area_bonos.verticalScrollBar().setValue(lista.etiqueta.y())
        except RuntimeError:
            pass  # el panel se cerró antes de que corra: no hay nada que mover

    def mostrar_estado_playstation(self, item, puede_operar: bool = None):
        """Escribe en el panel cómo está la consola. Aparte de `mostrar` porque la
        grilla lo vuelve a llamar cada segundo mientras corre la cuenta regresiva
        (ver PanelControlPcs._actualizar_cuenta_regresiva), sin rearmar los botones."""
        if puede_operar is None:
            puede_operar = playstation_repo.puede_operar(self.usuario)
        sesion = item["sesion"]
        if sesion is None:
            texto = "🎮 Libre — sin sesión activa."
        elif item["tiempo_agotado"]:
            texto = "⏰ Se acabó el tiempo: avisales a los clientes y liberá la consola."
        else:
            texto = f"▶ Activa — {formato_tiempo(item['segundos_restantes'], con_segundos=True)} restantes."
        if not puede_operar:
            texto += "\n🔒 Sin permiso para operarla."
        self.etiqueta_estado.setText(texto)

    @manejar_errores
    def _confirmar_bono(self):
        # Todo se decide con el equipo elegido AHORA (`item`): de esa foto sale
        # la lista de bonos y a dónde se vende. Se toma antes de abrir el cobro
        # (que puede mostrar un diálogo mientras la grilla se sigue refrescando
        # sola), así lo que se cobra y a quién se lo aplica nunca se separan.
        item = self.item
        if item is None:
            return
        if self._es_playstation(item):
            lista, sin_bonos = self.lista_playstation, (
                "Todavía no hay ningún bono de PlayStation 5 — el Admin lo crea desde "
                "'Configuración ADMIN' -> 'Gestionar Bonos de PlayStation 5'."
            )
        else:
            lista, sin_bonos = self.lista_pc, (
                "Todavía no hay ningún bono de tiempo cargado — creá uno primero desde 'Gestionar Bonos'."
            )
        bono = lista.bono_elegido()
        if bono is None:
            mostrar_error(self, "Sin bonos", sin_bonos)
            return

        metodo = self.combo_metodo.currentData()
        pagos = resolver_pagos(self, metodo, bono["precio"])
        if pagos is None:
            return
        if self._es_playstation(item):
            playstation_repo.vender_bono(self.usuario["id"], bono["id"], pagos)
        else:
            pcs_repo.asignar_bono(item["estacion"]["id"], bono["id"], self.usuario["id"], pagos)
        self._avisar_cambio()

    def _abrir_con_miembro(self):
        if self.item is None or self._es_playstation(self.item):
            return
        dialogo = DialogoLoginMiembro(self.item["estacion"], self)
        if dialogo.exec():
            self._avisar_cambio()

    @manejar_errores
    def _finalizar_sesion(self):
        item = self.item
        if item is None or item["sesion"] is None:
            return
        segundos_restantes = item["segundos_restantes"]

        if self._es_playstation(item):
            if segundos_restantes:
                aviso = (
                    f"Todavía le quedan {formato_tiempo(segundos_restantes)} disponibles a la "
                    f"{item['nombre']}.\n\n¿Liberarla de todas formas? El tiempo no usado no se reintegra."
                )
            else:
                aviso = f"¿Ya les avisaste a los clientes? Se va a liberar la {item['nombre']}."
            if confirmar(self, "Confirmar", aviso):
                playstation_repo.finalizar_sesion(self.usuario["id"])
                self._avisar_cambio()
            return

        estacion_nombre = item["estacion"]["nombre"]
        # Caso típico: el cliente pidió un bono de 3hs y se va antes -- el
        # mostrador tiene que poder cerrarle la PC ya mismo aunque le
        # quede tiempo pago, por eso el aviso deja bien claro cuánto se
        # está por perder en vez de una advertencia genérica.
        if segundos_restantes:
            aviso = (
                f"Todavía le quedan {formato_tiempo(segundos_restantes)} disponibles a "
                f"'{estacion_nombre}'.\n\n¿Cerrarla de todas formas? El tiempo no usado "
                "no se reintegra."
            )
        else:
            aviso = (
                f"¿Finalizar la sesión de '{estacion_nombre}'? "
                "El tiempo que no se llegó a usar no se reintegra."
            )
        if confirmar(self, "Confirmar", aviso):
            pcs_repo.finalizar_sesion(item["sesion"]["id"])
            self._avisar_cambio()


class DialogoLoginMiembro(QDialog):
    """
    A diferencia de vender un bono (lo maneja el Operador, que elige el
    bono desde PanelDetalleEstacion), acá el Miembro se loguea SOLO con
    su usuario y contraseña — pensado para que lo tipee el socio mismo en
    el mostrador. No hay que elegir cuánto tiempo asignar: entrar con las
    credenciales correctas alcanza, se usa todo el saldo disponible en
    ese momento (ver miembros_repo.abrir_estacion_por_miembro).
    """

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Abrir PC con Miembro — {estacion['nombre']}")
        self.resize(340, 200)
        self._armar_interfaz()

    def _armar_interfaz(self):
        etiqueta = QLabel(f"Ingresá tu usuario y contraseña de socio para abrir '{self.estacion['nombre']}':")
        etiqueta.setWordWrap(True)

        self.campo_usuario = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)

        botones = fila_guardar_cancelar(self, self._confirmar, texto_guardar="Ingresar")

        layout = QVBoxLayout()
        layout.addWidget(etiqueta)
        layout.addWidget(QLabel("Usuario:"))
        layout.addWidget(self.campo_usuario)
        layout.addWidget(QLabel("Contraseña:"))
        layout.addWidget(self.campo_clave)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_usuario, self.campo_clave, accion_final=self._confirmar)
        sin_boton_por_defecto(self)
        self.campo_usuario.setFocus()

    @manejar_errores
    def _confirmar(self):
        usuario = self.campo_usuario.text().strip()
        clave = self.campo_clave.text()
        if not usuario or not clave:
            mostrar_error(self, "Faltan datos", "Ingresá tu usuario y tu contraseña.")
            return
        resultado = miembros_repo.abrir_estacion_por_miembro(self.estacion["id"], usuario, clave)
        mostrar_info(
            self, "PC activada",
            f"Hola {resultado['miembro']}, se activó '{self.estacion['nombre']}' con "
            f"{formato_tiempo(resultado['minutos_usados'] * 60)} de tu saldo."
        )
        self.accept()
