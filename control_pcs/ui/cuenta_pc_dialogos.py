"""
cuenta_pc_dialogos.py
=======================
Las ventanas de la Cuenta de la PC (pedido del dueño, 2026-10-25; reglas en
control_pcs/repositories/cuentas_pc_repo.py):

- `anotar_en_la_cuenta`: lo que hacen VENDER ("A cuenta de una PC...") y el
  panel de la PC ("Agregar bono a cuenta") para anotar: pide a nombre de quién
  si la cuenta es nueva y, si se pasa del tope y la regla lo deja, la clave de
  un Admin (`DialogoClaveAdmin`).
- `DialogoElegirPc`: a qué PC se anota lo del carrito de VENDER (solo las que
  tienen un cliente jugando).
- `DialogoTiempoSocio`: cuánto tiempo de socio se le anota a un socio que está
  jugando (un bono de socio o un monto con la tarifa de socios, como en Cargar
  Saldo).
- `DialogoCuentaPc`: lo que debe una PC, renglón por renglón, para cobrarlo con
  la ventana de cobro de siempre; el Admin además quita un renglón anotado por
  error o da la cuenta por perdida. Desde otra PC se mira igual, y lo que cobra
  o cambia algo avisa que se hace en el mostrador.
- `DialogoCobrarAntesDelCierre`: lo fiado en el turno que todavía se debe, con un
  "Cobrar" por PC. Sale solo 15 minutos antes del fin del turno ("Posponer 5 min")
  y al apretar Cierre de Turno ("Cerrar igual": queda en el cierre como fiado sin
  cobrar). Pedido del dueño, 2026-10-25: "que lo que dio el operador de X turno
  quede en su turno".
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QCheckBox, QDialog, QDoubleSpinBox, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget,
    QListWidgetItem, QPushButton, QRadioButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

import dominio
from control_pcs.repositories import bonos_miembro_repo, cuentas_pc_repo, miembros_repo, pcs_repo
from repositories import config_repo
from ui import dialogo_pago
from ui.utils import (
    aplicar_clase, crear_tabla, encadenar_enter, fila_guardar_cancelar, formato_pesos, formato_tiempo, manejar_errores,
    mostrar_error, mostrar_info, sin_boton_por_defecto, solo_en_el_mostrador,
)


def _nombre_para_la_cuenta(parent, item):
    """A nombre de quién va una cuenta nueva: "" si no hace falta preguntar (ya
    tiene cuenta, o es un socio y va con su nombre), lo que escribió el operador
    (puede quedar vacío), o None si canceló."""
    deuda = item.get("deuda")
    if (deuda is not None and deuda.get("de_la_sesion") is not None) or item["sesion"]["miembro_nombre"]:
        return ""
    nombre, ok = QInputDialog.getText(
        parent, "¿A nombre de quién?",
        f"¿A nombre de quién anotás en '{item['estacion']['nombre']}'?\n"
        "(Opcional: sirve para no confundirlo si se va y se sienta otro.)",
    )
    return nombre.strip() if ok else None


def anotar_en_la_cuenta(parent, item, anotar):
    """
    Anota en la cuenta de la PC `item` (un elemento de pcs_repo.estado_estaciones)
    con `anotar(nombre=..., autoriza=...)` (cuentas_pc_repo.anotar_articulos o
    anotar_bono, con lo demás ya puesto). Si se pasa del tope y la regla deja
    pasarse con la clave de un Admin, la pide y vuelve a intentar. Devuelve lo que
    devuelve el repo, o None si no se anotó (ya se avisó por qué).
    """
    nombre = _nombre_para_la_cuenta(parent, item)
    if nombre is None:
        return None
    autoriza = None
    while True:
        try:
            return anotar(nombre=nombre, autoriza=autoriza)
        except cuentas_pc_repo.TopeSuperado as error:
            if not error.con_clave:
                mostrar_error(parent, "Pasa el tope", str(error))
                return None
            dialogo = DialogoClaveAdmin(str(error), parent)
            if not dialogo.exec():
                return None
            autoriza = dialogo.autoriza


class DialogoClaveAdmin(QDialog):
    """Un Admin autoriza que una PC deba más que el tope (si la regla lo deja)."""

    def __init__(self, motivo: str, parent=None):
        super().__init__(parent)
        self.autoriza = None
        self.setWindowTitle("Clave de un Administrador")
        self.resize(360, 220)
        etiqueta = QLabel(motivo)
        etiqueta.setWordWrap(True)
        self.campo_nombre = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)
        layout = QVBoxLayout()
        layout.addWidget(etiqueta)
        layout.addWidget(QLabel("Administrador:"))
        layout.addWidget(self.campo_nombre)
        layout.addWidget(QLabel("Clave:"))
        layout.addWidget(self.campo_clave)
        layout.addLayout(fila_guardar_cancelar(self, self._confirmar, texto_guardar="Autorizar"))
        self.setLayout(layout)
        encadenar_enter(self.campo_nombre, self.campo_clave, accion_final=self._confirmar)
        sin_boton_por_defecto(self)
        self.campo_nombre.setFocus()

    def _confirmar(self):
        if not self.campo_nombre.text().strip() or not self.campo_clave.text():
            mostrar_error(self, "Faltan datos", "Escribí el nombre y la clave del Administrador.")
            return
        self.autoriza = {"nombre": self.campo_nombre.text().strip(), "clave": self.campo_clave.text()}
        self.accept()


class DialogoTiempoSocio(QDialog):
    """Cuánto tiempo de socio se anota: un bono de socio o un monto (con la tarifa
    por hora de socios y la carga mínima de siempre). Deja `bono_id` o `monto`."""

    def __init__(self, item, parent=None):
        super().__init__(parent)
        self.bono_id, self.monto = None, None
        self.setWindowTitle("Tiempo de socio a cuenta")
        self.resize(380, 360)
        self._bonos = bonos_miembro_repo.listar_bonos()
        self._tramos = config_repo.obtener_tramos_tarifa_hora_miembro()

        etiqueta = QLabel(f"¿Cuánto tiempo le anotás a {item['sesion']['miembro_nombre']} en "
                          f"'{item['estacion']['nombre']}'? Se le suma ya y se cobra después.")
        etiqueta.setWordWrap(True)
        self._grupo = QButtonGroup(self)
        layout = QVBoxLayout()
        layout.addWidget(etiqueta)
        self._opciones = []
        for bono in self._bonos:
            opcion = QRadioButton(f"{bono['nombre']} — {formato_pesos(bono['precio'])}")
            self._grupo.addButton(opcion)
            self._opciones.append((opcion, bono))
            layout.addWidget(opcion)
        self.opcion_monto = QRadioButton("Otro monto:")
        self._grupo.addButton(self.opcion_monto)
        self.campo_monto = QDoubleSpinBox()
        self.campo_monto.setMaximum(99_999_999)
        self.campo_monto.setDecimals(0)
        self.campo_monto.setGroupSeparatorShown(True)
        self.campo_monto.setPrefix("$ ")
        self.campo_monto.valueChanged.connect(self._mostrar_minutos)
        self.campo_monto.valueChanged.connect(lambda _: self.opcion_monto.setChecked(True))
        self.etiqueta_minutos = QLabel("")
        fila_monto = QHBoxLayout()
        fila_monto.addWidget(self.opcion_monto)
        fila_monto.addWidget(self.campo_monto, 1)
        layout.addLayout(fila_monto)
        layout.addWidget(self.etiqueta_minutos)
        layout.addStretch()
        layout.addLayout(fila_guardar_cancelar(self, self._confirmar, texto_guardar="Anotar"))
        self.setLayout(layout)
        (self._opciones[0][0] if self._opciones else self.opcion_monto).setChecked(True)
        encadenar_enter(self.campo_monto, accion_final=self._confirmar)
        sin_boton_por_defecto(self)

    def _mostrar_minutos(self):
        monto = self.campo_monto.value()
        if monto <= 0:
            self.etiqueta_minutos.setText("")
            return
        _tarifa, minutos = miembros_repo.minutos_por_monto(self._tramos, monto)
        self.etiqueta_minutos.setText(f"Son {formato_tiempo(minutos * 60)} con la tarifa de socios.")

    def _confirmar(self):
        for opcion, bono in self._opciones:
            if opcion.isChecked():
                self.bono_id = bono["id"]
                self.accept()
                return
        if self.campo_monto.value() <= 0:
            mostrar_error(self, "Falta el monto", "Elegí un bono de socio o escribí un monto.")
            return
        self.monto = self.campo_monto.value()
        self.accept()


class DialogoElegirPc(QDialog):
    """A qué PC se anota lo del carrito de VENDER: las que tienen un cliente
    jugando, con quién es, cuánto le queda y cuánto debe ya."""

    def __init__(self, total: float, parent=None):
        super().__init__(parent)
        self.item = None
        self.setWindowTitle("A cuenta de una PC")
        self.resize(380, 440)
        self._items = [item for item in pcs_repo.estado_estaciones()
                       if item["sesion"] is not None and item["segundos_restantes"]]

        etiqueta = QLabel(f"¿En la cuenta de qué PC anotás {formato_pesos(total)}?")
        etiqueta.setWordWrap(True)
        self.lista = QListWidget()
        for item in self._items:
            texto = (f"{item['estacion']['nombre']} — {item['sesion']['miembro_nombre'] or 'Bono'} — "
                     f"le quedan {formato_tiempo(item['segundos_restantes'])}")
            if item["deuda"] is not None:
                texto += f" — ya debe {formato_pesos(item['deuda']['total'])}"
            self.lista.addItem(QListWidgetItem(texto))
        self.lista.itemDoubleClicked.connect(lambda _: self._confirmar())
        aviso = QLabel("Ninguna PC tiene un cliente jugando." if not self._items else "")
        aviso.setVisible(not self._items)

        layout = QVBoxLayout()
        layout.addWidget(etiqueta)
        layout.addWidget(self.lista, 1)
        layout.addWidget(aviso)
        layout.addLayout(fila_guardar_cancelar(self, self._confirmar, texto_guardar="Anotar"))
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        if self._items:
            self.lista.setCurrentRow(0)
        self.lista.setFocus()

    def _confirmar(self):
        fila = self.lista.currentRow()
        if not 0 <= fila < len(self._items):
            mostrar_error(self, "Elegí una PC", "Elegí en qué PC anotarlo.")
            return
        self.item = self._items[fila]
        self.accept()


class DialogoCuentaPc(QDialog):
    """
    Lo que debe una PC: cada cuenta (normalmente una, la del cliente de ahora;
    otra si el anterior se fue debiendo) con una casilla para elegir qué se
    cobra, y sus renglones con la hora y quién los anotó. "Cobrar" abre la
    ventana de cobro de siempre. El Admin ve además "Quitar renglón" y "Dar por
    perdida". Se cierra sola cuando ya no se debe nada.
    """

    def __init__(self, usuario, estacion, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.estacion = estacion
        self.es_admin = dominio.es_admin(usuario)
        self.cobro_hecho = False
        self.cuentas, self.casillas, self._renglones = [], [], []
        self.setWindowTitle(f"Cuenta de {estacion['nombre']}")
        self.resize(620, 460)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.layout_casillas = QVBoxLayout()
        self.tabla = crear_tabla(["Cliente", "Qué", "Cant.", "Importe", "Hora", "Anotó"], estirar=1, por_filas=True,
                                 una_sola=True)
        self.etiqueta_total = QLabel()
        self.etiqueta_total.setStyleSheet("font-size: 16px; font-weight: 700;")

        self.boton_cobrar = QPushButton("Cobrar")
        aplicar_clase(self.boton_cobrar, "cuenta")
        self.boton_cobrar.clicked.connect(self._cobrar)
        self.boton_quitar = QPushButton("Quitar renglón...")
        self.boton_quitar.clicked.connect(self._quitar_renglon)
        self.boton_perdida = QPushButton("Dar por perdida...")
        aplicar_clase(self.boton_perdida, "peligro")
        self.boton_perdida.clicked.connect(self._dar_por_perdida)
        for boton in (self.boton_quitar, self.boton_perdida):
            boton.setVisible(self.es_admin)  # solo el Admin (el repo lo vuelve a exigir)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)

        botones = QHBoxLayout()
        botones.addWidget(self.boton_quitar)
        botones.addWidget(self.boton_perdida)
        botones.addStretch()
        botones.addWidget(boton_cerrar)
        botones.addWidget(self.boton_cobrar)

        layout = QVBoxLayout()
        layout.addWidget(self.titulo)
        layout.addLayout(self.layout_casillas)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(self.etiqueta_total, alignment=Qt.AlignRight)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        self.cuentas = cuentas_pc_repo.cuentas_de_la_estacion(self.estacion["id"])
        while self.layout_casillas.count():
            casilla = self.layout_casillas.takeAt(0).widget()
            if casilla is not None:
                casilla.deleteLater()
        self.casillas = []
        for cuenta in self.cuentas:
            quien = cuenta["nombre"] or "Sin nombre"
            de_cuando = "cliente de ahora" if cuenta["es_de_la_sesion_actual"] else "se fue debiendo"
            casilla = QCheckBox(f"{quien} ({de_cuando}): {formato_pesos(cuenta['total'])}")
            casilla.setChecked(True)
            casilla.toggled.connect(self._mostrar_total)
            # Con una sola cuenta no hay nada que elegir.
            casilla.setVisible(len(self.cuentas) > 1)
            self.layout_casillas.addWidget(casilla)
            self.casillas.append(casilla)

        renglones = [(cuenta, renglon) for cuenta in self.cuentas for renglon in cuenta["renglones"]]
        self.tabla.setRowCount(len(renglones))
        for fila, (cuenta, renglon) in enumerate(renglones):
            valores = [cuenta["nombre"] or "—", renglon["descripcion"], str(renglon["cantidad"]),
                       formato_pesos(renglon["subtotal"]), renglon["fecha"][11:16], renglon["anoto"]]
            for columna, valor in enumerate(valores):
                celda = QTableWidgetItem(valor)
                if columna in (2, 3):
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(fila, columna, celda)
        self._renglones = renglones
        self.titulo.setText(f"Lo que debe {self.estacion['nombre']}" if self.cuentas
                            else f"{self.estacion['nombre']} no debe nada.")
        self._mostrar_total()

    def _elegidas(self):
        return [cuenta for cuenta, casilla in zip(self.cuentas, self.casillas) if casilla.isChecked()]

    def _mostrar_total(self):
        total = round(sum(cuenta["total"] for cuenta in self._elegidas()), 2)
        self.etiqueta_total.setText(f"A cobrar: {formato_pesos(total)}")
        self.boton_cobrar.setText(f"Cobrar {formato_pesos(total)}")
        self.boton_cobrar.setEnabled(total > 0)
        self.boton_perdida.setEnabled(bool(self.cuentas))
        self.boton_quitar.setEnabled(bool(self._renglones))

    def _cuenta_y_renglon_elegidos(self):
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self._renglones):
            return self._renglones[fila]
        if len(self.cuentas) == 1:
            return self.cuentas[0], None
        return None, None

    def _despues_de_cambiar(self):
        self._cargar()
        if not self.cuentas:
            self.accept()

    @solo_en_el_mostrador
    @manejar_errores
    def _cobrar(self):
        ids = [cuenta["id"] for cuenta in self._elegidas()]
        if not ids:
            mostrar_error(self, "Elegí qué cobrar", "Marcá qué cuenta cobrar.")
            return
        # El total lo vuelve a sumar el repo: lo que se cobra es lo que se debe AHORA.
        total = cuentas_pc_repo.total_de(ids)
        pagos = dialogo_pago.cobrar(self, total)
        if pagos is None:
            return
        cuentas_pc_repo.cobrar(ids, self.usuario["id"], pagos)
        self.cobro_hecho = True
        mostrar_info(self, "Cuenta cobrada", f"Se cobraron {formato_pesos(total)} de {self.estacion['nombre']}.")
        self._despues_de_cambiar()

    @solo_en_el_mostrador
    @manejar_errores
    def _quitar_renglon(self):
        cuenta, renglon = self._cuenta_y_renglon_elegidos()
        if renglon is None:
            mostrar_error(self, "Elegí un renglón", "Marcá en la lista lo que querés quitar.")
            return
        extra = ("Vuelve al stock." if renglon["tipo"] == dominio.ITEM_CUENTA_ARTICULO
                 else "Si la PC sigue en uso, se le saca ese tiempo.")
        motivo, ok = QInputDialog.getText(
            self, "Quitar renglón",
            f"Quitar '{renglon['descripcion']}' ({formato_pesos(renglon['subtotal'])}) de la cuenta. {extra}\n"
            "¿Por qué? (queda anotado):",
        )
        if not ok:
            return
        cuentas_pc_repo.quitar_renglon(renglon["id"], self.usuario["id"], motivo)
        self._despues_de_cambiar()

    @solo_en_el_mostrador
    @manejar_errores
    def _dar_por_perdida(self):
        cuenta, _ = self._cuenta_y_renglon_elegidos()
        if cuenta is None:
            mostrar_error(self, "Elegí una cuenta", "Marcá en la lista un renglón de la cuenta que se da por perdida.")
            return
        quien = cuenta["nombre"] or "sin nombre"
        motivo, ok = QInputDialog.getText(
            self, "Dar por perdida",
            f"La cuenta de {quien} ({formato_pesos(cuenta['total'])}) deja de cobrarse y la PC deja de titilar. "
            "No entra plata en la caja.\n¿Por qué? (queda anotado):",
        )
        if not ok:
            return
        cuentas_pc_repo.dar_por_perdida(cuenta["id"], self.usuario["id"], motivo)
        self._despues_de_cambiar()


class DialogoCobrarAntesDelCierre(QDialog):
    """
    Lo fiado en el turno abierto que todavía se debe (cuentas_pc_repo), una fila
    por PC con su "Cobrar" (abre DialogoCuentaPc: la ventana de cobro de siempre,
    así la plata entra en la caja de este turno). Se cierra sola cuando ya no
    queda nada. No hay un "Ya lo cobré": una cuenta se apaga sola al cobrarla con
    el programa, y apagarla a mano dejaría plata fuera de la caja.

    - AVISO (15 minutos antes del fin del turno, MainWindow): "Posponer 5 min".
    - CIERRE (al apretar Cierre de Turno): "Cerrar igual" (accept con
      `cerrar_igual`: queda en el cierre como fiado sin cobrar) o "Cancelar".
    """

    AVISO = "AVISO"
    CIERRE = "CIERRE"

    def __init__(self, usuario, modo: str, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.modo = modo
        self.cerrar_igual = False
        self.cuentas = []
        self.setWindowTitle("Cobrá antes de cerrar el turno" if modo == self.AVISO else "Quedó sin cobrar")
        self.resize(460, 280)
        self._armar_interfaz()
        self._cargar()

    def se_puede_cerrar_sola(self) -> bool:
        """El cierre forzoso no espera por este cartel (ver MainWindow._hay_un_cobro_a_medias)."""
        return True

    def _armar_interfaz(self):
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 15px; font-weight: 600;")
        self.texto = QLabel()
        self.texto.setWordWrap(True)
        self.filas = QWidget()
        botones = QHBoxLayout()
        botones.addStretch()
        if self.modo == self.AVISO:
            boton_posponer = QPushButton(f"Posponer {dominio.MINUTOS_POSPONER_AVISO_CUENTAS} min")
            boton_posponer.clicked.connect(self.reject)
            botones.addWidget(boton_posponer)
        else:
            boton_cancelar = QPushButton("Cancelar")
            boton_cancelar.clicked.connect(self.reject)
            boton_cerrar_igual = QPushButton("Cerrar igual")
            aplicar_clase(boton_cerrar_igual, "peligro")
            boton_cerrar_igual.clicked.connect(self._cerrar_igual)
            botones.addWidget(boton_cancelar)
            botones.addWidget(boton_cerrar_igual)
        self._layout = QVBoxLayout()
        self._layout.addWidget(self.titulo)
        self._layout.addWidget(self.texto)
        self._layout.addWidget(self.filas)
        self._layout.addStretch()
        self._layout.addLayout(botones)
        self.setLayout(self._layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        if self.modo == self.AVISO:
            aviso = cuentas_pc_repo.aviso_antes_del_cierre()
            self.cuentas = aviso["cuentas"] if aviso else []
            self.titulo.setText("Cobrá antes de cerrar el turno")
            if aviso:
                self.texto.setText(f"Tu turno ({aviso['turno_label']}) cierra a las {aviso['fin']:%H:%M}. "
                                   "Estas PCs deben lo que se anotó en tu turno:")
        else:
            self.cuentas = cuentas_pc_repo.fiado_del_turno_en_curso()
            self.titulo.setText("Quedó sin cobrar")
            self.texto.setText("Estas PCs deben lo que se anotó en tu turno. Si cerrás igual, queda en tu cierre "
                               "como fiado sin cobrar, a tu nombre:")
        if not self.cuentas and self.isVisible():
            self.accept()  # ya no queda nada que cobrar
            return
        nuevas = QWidget()
        layout_filas = QVBoxLayout(nuevas)
        layout_filas.setContentsMargins(0, 4, 0, 4)
        for cuenta in self.cuentas:
            fila = QHBoxLayout()
            nombre_pc = QLabel(cuenta["estacion"])
            nombre_pc.setStyleSheet("font-weight: 600;")
            nombre_pc.setMinimumWidth(70)
            fila.addWidget(nombre_pc)
            fila.addWidget(QLabel(cuenta["nombre"] or "—"), 1)
            fila.addWidget(QLabel(formato_pesos(cuenta["debe"])))
            boton = QPushButton("Cobrar")
            aplicar_clase(boton, "cuenta")
            boton.clicked.connect(lambda _=False, c=cuenta: self._cobrar(c))
            fila.addWidget(boton)
            layout_filas.addLayout(fila)
        self._layout.replaceWidget(self.filas, nuevas)
        self.filas.deleteLater()
        self.filas = nuevas

    def _cobrar(self, cuenta):
        DialogoCuentaPc(self.usuario, {"id": cuenta["estacion_id"], "nombre": cuenta["estacion"]}, self).exec()
        self._cargar()

    def _cerrar_igual(self):
        self.cerrar_igual = True
        self.accept()
