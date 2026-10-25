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
- `DialogoCuentaPc`: lo que debe una PC, renglón por renglón, para cobrarlo con
  la ventana de cobro de siempre; el Admin además quita un renglón anotado por
  error o da la cuenta por perdida. Desde otra PC se mira igual, y lo que cobra
  o cambia algo avisa que se hace en el mostrador.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QPushButton,
    QTableWidgetItem, QVBoxLayout,
)

import dominio
from control_pcs.repositories import cuentas_pc_repo, pcs_repo
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
