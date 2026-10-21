"""
reservas_window.py
====================
La ventana RESERVAS (botón de la barra, pedido del dueño 2026-10-20; es la
maqueta que aprobó): la lista de reservas con quién, cuándo, qué equipo, qué
bono, el precio, cuánto pagó, cuánto falta y cómo está, con los botones Nueva
reserva, Habilitar, Reprogramar, No vino y Devolver plata (solo el Admin).

Los formularios están en reservas_dialogos.py y las reglas en
control_pcs/repositories/reservas_repo.py. Se abre solo en el mostrador: cobra.
"""

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout,
)

import dominio
from control_pcs.repositories import reservas_repo
from control_pcs.ui.reservas_dialogos import (
    DialogoDevolver, DialogoHabilitarReserva, DialogoNuevaReserva, DialogoReprogramar, aviso_azul,
    texto_dia_y_hora,
)
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, formato_pesos, manejar_errores, mostrar_error, mostrar_info,
    sin_boton_por_defecto,
)

TITULOS = ("Nº", "Día y hora", "Cliente", "Celular", "Equipo", "Bono", "Precio", "Pagó", "Falta", "Estado")
COLUMNA_ESTADO = TITULOS.index("Estado")

# El color del estado en la lista, como en la maqueta: azul lo que espera,
# naranja lo que hay que reprogramar, verde lo que se usó, gris lo terminado.
COLOR_ESTADO = {
    dominio.RESERVA_PENDIENTE: "#1D48A0",
    dominio.RESERVA_A_REPROGRAMAR: "#C2620A",
    dominio.RESERVA_HABILITADA: "#1F8A43",
    dominio.RESERVA_NO_VINO: "#8A93A3",
    dominio.RESERVA_VENCIDA: "#8A93A3",
    dominio.RESERVA_DEVUELTA: "#8A93A3",
}

_MOSTRAR_TODAS = "Todas (las que esperan, arriba)"
_MOSTRAR_ABIERTAS = "Solo las que esperan al cliente"


def texto_estado(reserva: dict) -> str:
    """Cómo está una reserva, en palabras."""
    estado = reserva["estado"]
    if estado == dominio.RESERVA_PENDIENTE:
        return "Pendiente · pagada" if not reserva["falta"] else "Pendiente"
    if estado == dominio.RESERVA_HABILITADA:
        return f"Habilitada en {reserva['habilitada_en']}"
    if estado == dominio.RESERVA_NO_VINO:
        return "No vino · perdió la seña" if reserva["pagado"] > 0 else "No vino"
    if estado == dominio.RESERVA_A_REPROGRAMAR:
        return f"A reprogramar (no vino; vence el {datetime.fromisoformat(reserva['vence']):%d/%m})"
    if estado == dominio.RESERVA_VENCIDA:
        return "Vencida (no se reprogramó)"
    return "Devuelta"


class ReservasWindow(QDialog):
    """La lista de reservas y lo que se hace con cada una."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self.reservas = []
        self.setWindowTitle("Reservas")
        self.resize(1180, 560)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        titulo = QLabel("📅  Reservas")
        titulo.setStyleSheet("font-size: 18px; font-weight: bold;")

        botones = QHBoxLayout()
        for texto, accion, clase in (
            ("Nueva reserva", self._nueva, "primario"),
            ("Habilitar", self._habilitar, "primario"),
            ("Reprogramar", self._reprogramar, None),
            ("No vino", self._no_vino, "peligro"),
            ("Devolver plata (Admin)", self._devolver, "peligro"),
            ("Salir", self.close, None),
        ):
            boton = QPushButton(texto)
            if clase:
                aplicar_clase(boton, clase)
            boton.clicked.connect(accion)
            botones.addWidget(boton)
        botones.addStretch()

        self.combo_mostrar = QComboBox()
        self.combo_mostrar.addItems([_MOSTRAR_TODAS, _MOSTRAR_ABIERTAS])
        self.combo_mostrar.currentIndexChanged.connect(self._cargar)
        lupa = QLabel("🔍")
        lupa.setStyleSheet("font-size: 20px;")
        self.campo_buscar = QLineEdit()
        self.campo_buscar.setPlaceholderText("Buscar por cliente o celular...")
        self.campo_buscar.setMinimumWidth(300)
        self.campo_buscar.setClearButtonEnabled(True)
        self.campo_buscar.textChanged.connect(self._cargar)
        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Mostrar:"))
        filtros.addWidget(self.combo_mostrar)
        filtros.addSpacing(16)
        filtros.addWidget(lupa)
        filtros.addWidget(self.campo_buscar)
        filtros.addStretch()

        self.tabla = crear_tabla(TITULOS, estirar=COLUMNA_ESTADO, por_filas=True, una_sola=True)
        self.tabla.cellDoubleClicked.connect(lambda *_: self._habilitar())

        layout = QVBoxLayout()
        layout.addWidget(titulo)
        layout.addLayout(botones)
        layout.addLayout(filtros)
        layout.addWidget(self.tabla)
        layout.addWidget(aviso_azul(
            "Si no viene: si dejó seña, la pierde (No vino). Si pagó el 100%, queda \"A reprogramar\" para otro "
            "día, y ese día se le da cualquier PC disponible (vence a los "
            f"{dominio.DIAS_PARA_REPROGRAMAR_RESERVA} días). A los {dominio.MINUTOS_TOLERANCIA_RESERVA} minutos "
            "de la hora pasa sola. Devolver plata: solo el Admin; sale de la caja de quien la entrega."
        ))
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.campo_buscar.setFocus()

    @manejar_errores
    def _cargar(self, _=None, elegir: int = None):
        """Vuelve a leer la lista (con los estados al día) y deja elegida la
        reserva `elegir`, o la que estaba elegida."""
        if elegir is None:
            actual = self._elegida()
            elegir = actual["id"] if actual else None
        self.reservas = reservas_repo.listar_reservas(
            solo_abiertas=self.combo_mostrar.currentText() == _MOSTRAR_ABIERTAS,
            buscar=self.campo_buscar.text(),
        )
        self.tabla.setRowCount(0)
        for reserva in self.reservas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            sin_dia = reserva["estado"] == dominio.RESERVA_A_REPROGRAMAR
            textos = (
                str(reserva["id"]),
                "Sin día" if sin_dia else texto_dia_y_hora(reserva["fecha_reserva"]),
                reserva["cliente"], reserva["celular"], reserva["equipo_nombre"], reserva["bono_nombre"],
                formato_pesos(reserva["precio"]), formato_pesos(reserva["pagado"]),
                formato_pesos(reserva["falta"]) if reserva["falta"] else "—",
                texto_estado(reserva),
            )
            for columna, texto in enumerate(textos):
                self.tabla.setItem(fila, columna, QTableWidgetItem(texto))
            item_estado = self.tabla.item(fila, COLUMNA_ESTADO)
            item_estado.setForeground(QColor(COLOR_ESTADO[reserva["estado"]]))
            fuente = item_estado.font()
            fuente.setBold(True)
            item_estado.setFont(fuente)
            if reserva["id"] == elegir:
                self.tabla.selectRow(fila)
        self.tabla.resizeColumnsToContents()

    def _elegida(self):
        """La reserva elegida en la lista, o None."""
        fila = self.tabla.currentRow() if self.tabla.selectedItems() else -1
        if 0 <= fila < len(self.reservas):
            return self.reservas[fila]
        return None

    def _elegida_o_aviso(self, que_espera: bool = True):
        """La reserva elegida; si no hay ninguna, o (con `que_espera`) ya no
        espera al cliente, avisa y devuelve None."""
        reserva = self._elegida()
        if reserva is None:
            mostrar_error(self, "Nada elegido", "Elegí primero una reserva de la lista.")
            return None
        if que_espera and reserva["estado"] not in dominio.ESTADOS_RESERVA_ABIERTA:
            mostrar_error(self, "Esa reserva ya terminó",
                          f"La reserva Nº {reserva['id']} está: {texto_estado(reserva)}.")
            return None
        return reserva

    def _nueva(self):
        dialogo = DialogoNuevaReserva(self.usuario, self)
        if dialogo.exec():
            self._cargar(elegir=dialogo.reserva_id)

    @manejar_errores
    def _habilitar(self):
        reserva = self._elegida_o_aviso()
        if reserva is None:
            return
        if DialogoHabilitarReserva(self.usuario, reserva["id"], self).exec():
            self._cargar(elegir=reserva["id"])

    def _reprogramar(self):
        reserva = self._elegida_o_aviso()
        if reserva is None:
            return
        if DialogoReprogramar(self.usuario, reserva, self).exec():
            self._cargar(elegir=reserva["id"])

    @manejar_errores
    def _no_vino(self):
        reserva = self._elegida_o_aviso()
        if reserva is None:
            return
        if reserva["estado"] != dominio.RESERVA_PENDIENTE:
            mostrar_error(self, "Ya está marcada", "Esta reserva ya quedó A reprogramar: reprogramala.")
            return
        if reserva["falta"]:
            que_pasa = (f"Dejó {formato_pesos(reserva['pagado'])} de seña: la pierde y la reserva queda "
                        "terminada (No vino).")
        else:
            que_pasa = (f"Pagó todo: queda \"A reprogramar\" para darle otro día (vence a los "
                        f"{dominio.DIAS_PARA_REPROGRAMAR_RESERVA} días).")
        if not confirmar(self, "No vino",
                         f"¿{reserva['cliente']} no viene a la reserva Nº {reserva['id']}?\n\n{que_pasa}\n"
                         "No se mueve plata: ya está en la caja donde se cobró."):
            return
        reservas_repo.marcar_no_vino(reserva["id"], self.usuario["id"])
        self._cargar(elegir=reserva["id"])

    @manejar_errores
    def _devolver(self):
        if not self.es_admin:
            mostrar_error(self, "Solo el Administrador",
                          "Devolver la plata de una reserva lo hace solo el Administrador.")
            return
        reserva = self._elegida_o_aviso(que_espera=False)
        if reserva is None:
            return
        if reserva["estado"] in (dominio.RESERVA_HABILITADA, dominio.RESERVA_DEVUELTA) or reserva["pagado"] <= 0:
            mostrar_info(self, "Nada para devolver",
                         f"La reserva Nº {reserva['id']} no tiene plata para devolver ({texto_estado(reserva)}).")
            return
        if DialogoDevolver(self.usuario, reserva, self).exec():
            self._cargar(elegir=reserva["id"])
