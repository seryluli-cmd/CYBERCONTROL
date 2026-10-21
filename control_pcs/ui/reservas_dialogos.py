"""
reservas_dialogos.py
======================
Los formularios de la ventana RESERVAS (control_pcs/ui/reservas_window.py),
como en las maquetas que aprobó el dueño el 2026-10-20:

- DialogoNuevaReserva: cliente, celular, día y hora, equipo, bono y cuánto paga
  ahora (50%, 100% u otro monto). Se cobra con la ventana de cobro de siempre.
- DialogoHabilitarReserva: el cliente llegó. Dice cuánto pagó, cuándo y en qué
  caja quedó esa plata, cobra lo que falta (si falta algo) y abre el equipo.
- DialogoReprogramar: otro día u otra hora.
- DialogoDevolver: solo el Admin, con un motivo.

Las reglas (qué se puede, cuánto falta, a qué caja va la plata) viven en
control_pcs/repositories/reservas_repo.py: acá solo se pregunta y se muestra.
"""

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, QTime
from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QDoubleSpinBox, QFormLayout, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QRadioButton, QTimeEdit, QVBoxLayout,
)

import dominio
from repositories import relevo_repo
from control_pcs.repositories import reservas_habilitar_repo, reservas_repo
from ui.dialogo_pago import cobrar
from ui.tarjeta_cierre import etiqueta_dato
from ui.utils import (
    aplicar_clase, confirmar, crear_selector_de_fecha, encadenar_enter, formato_pesos, manejar_errores,
    mostrar_error, mostrar_info, sin_boton_por_defecto,
)

_DIAS = ("lun", "mar", "mié", "jue", "vie", "sáb", "dom")


def texto_dia_y_hora(fecha_iso: str) -> str:
    """"mar 21/10 10:00": el día de la semana ayuda a no equivocarse de día."""
    momento = datetime.fromisoformat(fecha_iso)
    return f"{_DIAS[momento.weekday()]} {momento:%d/%m %H:%M}"


def aviso_azul(cuerpo: str, titulo: str = None) -> QFrame:
    """El recuadro azul suave de los avisos (#avisoInformativo en la hoja de estilos)."""
    marco = QFrame()
    marco.setObjectName("avisoInformativo")
    capa = QVBoxLayout(marco)
    capa.setContentsMargins(12, 10, 12, 10)
    if titulo:
        etiqueta_titulo = QLabel(titulo)
        etiqueta_titulo.setObjectName("avisoTitulo")
        etiqueta_titulo.setWordWrap(True)
        capa.addWidget(etiqueta_titulo)
    etiqueta = QLabel(cuerpo)
    etiqueta.setWordWrap(True)
    capa.addWidget(etiqueta)
    marco.cuerpo = etiqueta
    return marco


def _gris_chico(texto: str = "") -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setWordWrap(True)
    etiqueta.setStyleSheet("color: #6B7585; font-size: 11px;")
    return etiqueta


def _encabezado(texto: str) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setStyleSheet("font-size: 16px; font-weight: bold;")
    return etiqueta


def _campo_hora(hora: QTime) -> QTimeEdit:
    campo = QTimeEdit(hora)
    campo.setDisplayFormat("HH:mm")
    return campo


def _proxima_hora_en_punto() -> datetime:
    return (datetime.now() + timedelta(hours=1)).replace(minute=0, second=0, microsecond=0)


def _momento(fecha: QDate, hora: QTime) -> datetime:
    """El día de un selector de fecha y la hora de un QTimeEdit, juntos."""
    return datetime(fecha.year(), fecha.month(), fecha.day(), hora.hour(), hora.minute())


# ---------------------------------------------------------------------
# Nueva reserva
# ---------------------------------------------------------------------

class DialogoNuevaReserva(QDialog):
    """Tomar una reserva y cobrar la seña (o todo). Al aceptar queda
    `self.reserva_id`, el número de la reserva nueva."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.reserva_id = None
        self.setWindowTitle("Nueva reserva")
        self.resize(600, 420)
        self._armar_interfaz()
        self._cargar_bonos()

    def _armar_interfaz(self):
        self.campo_cliente = QLineEdit()
        self.campo_cliente.setPlaceholderText("Nombre de quien reserva")
        self.campo_celular = QLineEdit()
        self.campo_celular.setPlaceholderText("(opcional, para avisarle)")

        inicio = _proxima_hora_en_punto()
        self.campo_dia = crear_selector_de_fecha(QDate(inicio.year, inicio.month, inicio.day))
        self.campo_hora = _campo_hora(QTime(inicio.hour, 0))
        fila_dia = QHBoxLayout()
        fila_dia.addWidget(self.campo_dia)
        fila_dia.addWidget(QLabel("Hora:"))
        fila_dia.addWidget(self.campo_hora)
        fila_dia.addStretch()

        self.combo_equipo = QComboBox()
        for opcion in reservas_repo.equipos_para_reservar():
            self.combo_equipo.addItem(opcion["nombre"], opcion)
        self.combo_equipo.currentIndexChanged.connect(self._cargar_bonos)

        self.combo_bono = QComboBox()
        self.combo_bono.currentIndexChanged.connect(self._actualizar_monto)

        # Cuánto paga ahora: la mitad, todo, u otro monto (más de cero y hasta el precio).
        self.opcion_mitad = QRadioButton("50%")
        self.opcion_todo = QRadioButton("100%")
        self.opcion_otro = QRadioButton("Otro monto:")
        self.opcion_mitad.setChecked(True)
        self._grupo_paga = QButtonGroup(self)
        fila_paga = QHBoxLayout()
        for opcion in (self.opcion_mitad, self.opcion_todo, self.opcion_otro):
            self._grupo_paga.addButton(opcion)
            opcion.toggled.connect(self._actualizar_monto)
            fila_paga.addWidget(opcion)
        self.spin_otro = QDoubleSpinBox()
        self.spin_otro.setPrefix("$ ")
        self.spin_otro.setMaximum(99_999_999)
        self.spin_otro.valueChanged.connect(self._actualizar_monto)
        fila_paga.addWidget(self.spin_otro)
        fila_paga.addStretch()

        formulario = QFormLayout()
        formulario.addRow("Cliente:", self.campo_cliente)
        formulario.addRow("Celular:", self.campo_celular)
        formulario.addRow("Día:", fila_dia)
        formulario.addRow("Equipo:", self.combo_equipo)
        formulario.addRow("", _gris_chico(
            "Con \"Cualquier PC disponible\" no se aparta ninguna PC: cuando llega se le da la que esté libre."
        ))
        formulario.addRow("Bono:", self.combo_bono)
        formulario.addRow("Paga ahora:", fila_paga)

        self.aviso = aviso_azul("")
        self.etiqueta_sin_bonos = QLabel()
        self.etiqueta_sin_bonos.setWordWrap(True)
        self.etiqueta_sin_bonos.setStyleSheet("color: #A6323C;")
        self.etiqueta_sin_bonos.hide()

        self.boton_cobrar = QPushButton()
        aplicar_clase(self.boton_cobrar, "primario")
        self.boton_cobrar.clicked.connect(self._cobrar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.boton_cobrar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addLayout(formulario)
        layout.addWidget(self.etiqueta_sin_bonos)
        layout.addWidget(self.aviso)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_cliente, self.campo_celular, self.campo_dia, self.campo_hora,
                        self.combo_equipo, self.combo_bono, accion_final=self._cobrar)
        sin_boton_por_defecto(self)
        self.campo_cliente.setFocus()

    def _equipo(self) -> dict:
        return self.combo_equipo.currentData()

    def _bono(self):
        return self.combo_bono.currentData()

    def _cargar_bonos(self, _=None):
        """Los bonos del catálogo del equipo elegido (cada equipo cobra con el suyo)."""
        self.combo_bono.blockSignals(True)
        self.combo_bono.clear()
        for bono in reservas_repo.bonos_para(self._equipo()["equipo"]):
            self.combo_bono.addItem(f"{bono['nombre']} — {formato_pesos(bono['precio'])}", bono)
        self.combo_bono.blockSignals(False)
        vacio = self.combo_bono.count() == 0
        self.etiqueta_sin_bonos.setText(
            f"Todavía no hay bonos para {self._equipo()['nombre']}: el Admin los crea en Configuración ADMIN."
            if vacio else ""
        )
        self.etiqueta_sin_bonos.setVisible(vacio)
        self._actualizar_monto()

    def _monto(self) -> float:
        """Lo que paga ahora, según la opción elegida."""
        bono = self._bono()
        if bono is None:
            return 0.0
        if self.opcion_todo.isChecked():
            return round(bono["precio"], 2)
        if self.opcion_otro.isChecked():
            return round(self.spin_otro.value(), 2)
        return round(bono["precio"] / 2, 2)

    def _actualizar_monto(self, _=None):
        """Los importes de las opciones, el botón Cobrar y el aviso de abajo
        (qué pasa si no viene) siguen al bono y a la opción elegida."""
        bono = self._bono()
        precio = bono["precio"] if bono else 0.0
        self.opcion_mitad.setText(f"50%  ({formato_pesos(round(precio / 2, 2))})")
        self.opcion_todo.setText(f"100%  ({formato_pesos(precio)})")
        self.spin_otro.setEnabled(self.opcion_otro.isChecked())
        monto = self._monto()
        self.boton_cobrar.setText(f"Cobrar {formato_pesos(monto)}")
        self.boton_cobrar.setEnabled(bono is not None)
        if bono is None:
            self.aviso.cuerpo.setText("Elegí un equipo que tenga bonos.")
        elif monto >= round(precio, 2):
            self.aviso.cuerpo.setText(
                f"El precio queda fijo en {formato_pesos(precio)} aunque después cambie el bono. "
                "Paga todo: si no viene, queda \"A reprogramar\" para darle otro día (con cualquier PC "
                f"disponible), y vence a los {dominio.DIAS_PARA_REPROGRAMAR_RESERVA} días."
            )
        else:
            self.aviso.cuerpo.setText(
                f"El precio queda fijo en {formato_pesos(precio)} aunque después cambie el bono. "
                f"Cuando llegue se cobra lo que falta. Si no viene (o llega más de "
                f"{dominio.MINUTOS_TOLERANCIA_RESERVA} minutos tarde), pierde la seña."
            )

    @manejar_errores
    def _cobrar(self):
        cliente = self.campo_cliente.text().strip()
        if not cliente:
            mostrar_error(self, "Falta el cliente", "Escribí el nombre de quien reserva.")
            self.campo_cliente.setFocus()
            return
        bono = self._bono()
        if bono is None:
            mostrar_error(self, "Sin bono", "Elegí un equipo que tenga bonos.")
            return
        equipo = self._equipo()
        inicio = _momento(self.campo_dia.date(), self.campo_hora.time())
        monto = self._monto()
        # Antes de cobrar: que no se cobre una reserva que después no se puede guardar.
        reservas_repo.revisar_reserva(equipo["equipo"], equipo["estacion_id"], bono["id"], inicio, monto)
        pagos = cobrar(self, monto)
        if pagos is None:
            return
        self.reserva_id = reservas_repo.crear_reserva(
            self.usuario["id"], cliente, self.campo_celular.text(), equipo["equipo"], equipo["estacion_id"],
            bono["id"], inicio, monto, pagos,
        )
        mostrar_info(
            self, "Reserva tomada",
            f"Reserva Nº {self.reserva_id}: {cliente}, {equipo['nombre']}, {texto_dia_y_hora(inicio.isoformat())}.\n"
            f"{bono['nombre']} · cobraste {formato_pesos(monto)}"
            + ("." if monto >= bono["precio"] else f", falta {formato_pesos(bono['precio'] - monto)}."),
        )
        self.accept()


# ---------------------------------------------------------------------
# Habilitar (el cliente llegó)
# ---------------------------------------------------------------------

_NOMBRE_DEL_PAGO = {
    dominio.PAGO_RESERVA_RESTO: "el resto",
    dominio.PAGO_RESERVA_DEVOLUCION: "una devolución",
}


def texto_de_lo_pagado(reserva: dict) -> str:
    """Cuánto pagó, cuándo, a quién y en qué caja quedó: "Dejó una seña de $
    5.000,00 el lun 20/10 16:10 (Ana, Caja Nº 31)." Sirve para que quien
    habilita sepa que esa plata NO está en su caja."""
    renglones = []
    for pago in reserva["pagos"]:
        if pago["anulada"]:
            continue
        cuando = texto_dia_y_hora(pago["fecha"])
        donde = pago["operador"] + (f", Caja Nº {pago['caja_numero']}" if pago["caja_numero"] else "")
        if pago["tipo"] == dominio.PAGO_RESERVA_ANTICIPO:
            if pago["monto"] >= reserva["precio"] - 0.005:
                que = f"Pagó todo ({formato_pesos(pago['monto'])})"
            else:
                que = f"Dejó una seña de {formato_pesos(pago['monto'])}"
        else:
            que = f"Pagó {_NOMBRE_DEL_PAGO[pago['tipo']]}: {formato_pesos(pago['monto'])}"
        renglones.append(f"{que} el {cuando} ({donde}).")
    if not renglones:
        return "No tiene nada pagado (se anuló lo que había pagado): se cobra todo ahora."
    return " ".join(renglones) + " Esa plata ya quedó en la caja donde se cobró."


class DialogoHabilitarReserva(QDialog):
    """El cliente llegó: cobrar lo que falta (si falta algo) y abrirle el equipo."""

    def __init__(self, usuario, reserva_id: int, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.reserva = reservas_repo.obtener_reserva(reserva_id)
        self.lugares = reservas_habilitar_repo.lugares_para_habilitar(reserva_id)
        self.setWindowTitle(f"Habilitar reserva Nº {reserva_id}")
        self.resize(480, 330)
        self._armar_interfaz()

    def _armar_interfaz(self):
        reserva = self.reserva
        falta = reserva["falta"]
        aviso = aviso_azul(
            texto_de_lo_pagado(reserva),
            f"{reserva['cliente']} · {reserva['bono_nombre']} · {formato_pesos(reserva['precio'])}",
        )
        if falta:
            caja_dato, _ = etiqueta_dato("FALTA COBRAR (entra en tu caja)", formato_pesos(falta),
                                         color_titulo="#000000", negrita_titulo=True, color_valor="#2FB457")
        else:
            caja_dato, _ = etiqueta_dato("NO SE COBRA NADA EN ESTE TURNO", formato_pesos(0),
                                         color_titulo="#000000", negrita_titulo=True, color_valor="#2F6FED")

        self.combo_lugar = QComboBox()
        self.combo_lugar.setMinimumWidth(220)
        for lugar in self.lugares:
            texto = lugar["nombre"]
            if lugar["es_la_reservada"] and reserva["equipo"] == dominio.EQUIPO_RESERVA_PC:
                texto += "  (la reservada)"
            if not lugar["enlazada"]:
                texto += "  (sin conexión)"
            if lugar["reservada_para"]:
                texto += f"  (reservada para {lugar['reservada_para']})"
            self.combo_lugar.addItem(texto, lugar)
        self.combo_lugar.currentIndexChanged.connect(self._actualizar_boton)
        fila_lugar = QHBoxLayout()
        fila_lugar.addWidget(QLabel("Se habilita en:"))
        fila_lugar.addWidget(self.combo_lugar)
        fila_lugar.addStretch()

        if not self.lugares:
            ayuda = "No hay ningún equipo libre para esta reserva: liberá uno y volvé a abrir esta ventana."
        elif reserva["equipo"] != dominio.EQUIPO_RESERVA_PC:
            ayuda = ""
        elif reserva["estado"] == dominio.RESERVA_A_REPROGRAMAR:
            ayuda = "Quedó A reprogramar: ya no tiene PC propia, se le da cualquiera de las libres."
        elif reserva["estacion_id"] is None:
            ayuda = "Reserva sin PC fija: se elige cualquiera de las libres."
        elif not any(lugar["es_la_reservada"] for lugar in self.lugares):
            ayuda = f"{reserva['equipo_nombre']} está ocupada: elegí otra libre."
        else:
            ayuda = f"Si {reserva['equipo_nombre']} está rota o no anda, se puede elegir otra libre."
        etiqueta_ayuda = _gris_chico(ayuda)
        etiqueta_ayuda.setVisible(bool(ayuda))

        self.boton_habilitar = QPushButton()
        aplicar_clase(self.boton_habilitar, "primario")
        self.boton_habilitar.clicked.connect(self._habilitar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.boton_habilitar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(_encabezado(f"Habilitar reserva Nº {reserva['id']}"))
        layout.addWidget(aviso)
        layout.addLayout(caja_dato)
        layout.addLayout(fila_lugar)
        layout.addWidget(etiqueta_ayuda)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self._actualizar_boton()

    def _actualizar_boton(self, _=None):
        lugar = self.combo_lugar.currentData()
        self.boton_habilitar.setEnabled(lugar is not None)
        if self.reserva["falta"]:
            self.boton_habilitar.setText(f"Cobrar {formato_pesos(self.reserva['falta'])} y habilitar")
        else:
            self.boton_habilitar.setText(f"Habilitar {lugar['nombre']}" if lugar else "Habilitar")

    @manejar_errores
    def _habilitar(self):
        lugar = self.combo_lugar.currentData()
        if lugar is None:
            return
        # Antes de cobrar el resto: que el equipo siga libre y la reserva esperando.
        falta = reservas_habilitar_repo.preparar_habilitacion(self.reserva["id"], lugar["estacion_id"])
        pagos = []
        if falta:
            pagos = cobrar(self, falta)
            if pagos is None:
                return
        resultado = reservas_habilitar_repo.habilitar(
            self.reserva["id"], self.usuario["id"], lugar["estacion_id"], pagos
        )
        cobro = (f"Cobraste {formato_pesos(resultado['cobrado'])}." if resultado["cobrado"]
                 else "No se cobró nada: ya estaba pagada.")
        mostrar_info(self, "Reserva habilitada",
                     f"Reserva Nº {self.reserva['id']} ({self.reserva['cliente']}) habilitada en "
                     f"{resultado['lugar']} con {self.reserva['bono_nombre']}. {cobro}")
        self.accept()


# ---------------------------------------------------------------------
# Reprogramar
# ---------------------------------------------------------------------

class DialogoReprogramar(QDialog):
    """Otro día u otra hora para una reserva que espera al cliente."""

    def __init__(self, usuario, reserva: dict, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.reserva = reserva
        self.setWindowTitle(f"Reprogramar reserva Nº {reserva['id']}")
        self.resize(460, 280)
        self._armar_interfaz()

    def _armar_interfaz(self):
        reserva = self.reserva
        inicio = _proxima_hora_en_punto()
        if reserva["estado"] == dominio.RESERVA_PENDIENTE:
            inicio = datetime.fromisoformat(reserva["fecha_reserva"])
        self.campo_dia = crear_selector_de_fecha(QDate(inicio.year, inicio.month, inicio.day))
        self.campo_hora = _campo_hora(QTime(inicio.hour, inicio.minute))
        fila_dia = QHBoxLayout()
        fila_dia.addWidget(self.campo_dia)
        fila_dia.addWidget(QLabel("Hora:"))
        fila_dia.addWidget(self.campo_hora)
        fila_dia.addStretch()

        # Una de PC pendiente puede cambiar de PC; una A reprogramar ya no elige
        # (se le da cualquiera), y PCSTREAM y la consola son una sola.
        self.combo_equipo = QComboBox()
        elige_pc = reserva["equipo"] == dominio.EQUIPO_RESERVA_PC and reserva["estado"] == dominio.RESERVA_PENDIENTE
        if elige_pc:
            for opcion in reservas_repo.equipos_para_reservar():
                if opcion["equipo"] == dominio.EQUIPO_RESERVA_PC:
                    self.combo_equipo.addItem(opcion["nombre"], opcion["estacion_id"])
            self.combo_equipo.setCurrentIndex(max(0, self.combo_equipo.findData(reserva["estacion_id"])))
        else:
            nombre = dominio.nombre_equipo_reservado(reserva["equipo"])
            self.combo_equipo.addItem(nombre, None)
            self.combo_equipo.setEnabled(False)

        formulario = QFormLayout()
        formulario.addRow("Día:", fila_dia)
        formulario.addRow("Equipo:", self.combo_equipo)
        if reserva["equipo"] == dominio.EQUIPO_RESERVA_PC and not elige_pc:
            formulario.addRow("", _gris_chico("Quedó A reprogramar: ya no elige PC, ese día se le da cualquiera."))

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(_encabezado(f"Reprogramar reserva Nº {reserva['id']}"))
        layout.addWidget(aviso_azul(
            f"{reserva['bono_nombre']} · pagó {formato_pesos(reserva['pagado'])} de "
            f"{formato_pesos(reserva['precio'])}. Lo pagado y el precio no cambian.",
            reserva["cliente"],
        ))
        layout.addLayout(formulario)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_dia, self.campo_hora, accion_final=self._guardar)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _guardar(self):
        inicio = _momento(self.campo_dia.date(), self.campo_hora.time())
        reservas_repo.reprogramar(self.reserva["id"], self.usuario["id"], inicio, self.combo_equipo.currentData())
        self.accept()


# ---------------------------------------------------------------------
# Devolver la plata (solo el Admin)
# ---------------------------------------------------------------------

class DialogoDevolver(QDialog):
    """Devolverle al cliente lo que pagó de una reserva que no se usó. Solo el
    Admin (el repo lo vuelve a exigir), con un motivo."""

    def __init__(self, usuario, reserva: dict, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.reserva = reserva
        self.setWindowTitle(f"Devolver la plata de la reserva Nº {reserva['id']}")
        self.resize(480, 300)
        self._armar_interfaz()

    def _armar_interfaz(self):
        reserva = self.reserva
        caja = relevo_repo.estado_de_la_caja()
        if caja is None:
            de_donde = "No hay ninguna caja abierta: queda como una venta sin caja, que se cierra aparte."
        else:
            de_donde = (f"Sale de la Caja Nº {caja['caja_numero']} de {caja['responsable']}: se descuenta de "
                        "lo que va en su sobre. El cierre del turno en que se cobró no cambia.")

        self.opcion_efectivo = QRadioButton("En efectivo (sale del cajón)")
        self.opcion_digital = QRadioButton("Digital (transferencia)")
        self.opcion_efectivo.setChecked(True)
        grupo = QButtonGroup(self)
        grupo.addButton(self.opcion_efectivo)
        grupo.addButton(self.opcion_digital)
        self.campo_motivo = QLineEdit()
        self.campo_motivo.setPlaceholderText("Ej: se cortó la luz, la PC no anda")

        formulario = QFormLayout()
        formulario.addRow("Cómo:", self.opcion_efectivo)
        formulario.addRow("", self.opcion_digital)
        formulario.addRow("Motivo:", self.campo_motivo)

        boton_devolver = QPushButton(f"Devolver {formato_pesos(reserva['pagado'])}")
        aplicar_clase(boton_devolver, "peligro")
        boton_devolver.clicked.connect(self._devolver)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_devolver)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(_encabezado(f"Devolver la plata de la reserva Nº {reserva['id']}"))
        layout.addWidget(aviso_azul(
            f"Se le devuelven {formato_pesos(reserva['pagado'])} ({reserva['bono_nombre']}). {de_donde}",
            reserva["cliente"],
        ))
        layout.addLayout(formulario)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.campo_motivo.setFocus()

    @manejar_errores
    def _devolver(self):
        motivo = self.campo_motivo.text().strip()
        if not motivo:
            mostrar_error(self, "Falta el motivo", "Escribí por qué se devuelve la plata.")
            self.campo_motivo.setFocus()
            return
        metodo = dominio.PAGO_EFECTIVO if self.opcion_efectivo.isChecked() else dominio.PAGO_DIGITAL
        if not confirmar(self, "Devolver la plata",
                         f"¿Le devolvés {formato_pesos(self.reserva['pagado'])} a {self.reserva['cliente']}? "
                         "La reserva queda Devuelta y no se puede deshacer desde acá."):
            return
        devuelto = reservas_repo.devolver(self.reserva["id"], self.usuario["id"], metodo, motivo)
        mostrar_info(self, "Plata devuelta",
                     f"Reserva Nº {self.reserva['id']}: se devolvieron {formato_pesos(devuelto)}.")
        self.accept()
