"""
reservas_socio_dialogo.py
===========================
Las reservas de socios (pedido del dueño, 2026-10-26; las reglas están en
control_pcs/repositories/reservas_socios_repo.py):

- DialogoReservaDeSocio: el botón "RESERVA DE SOCIO" de la ventana Reservas.
  Se elige el socio de la lista de Miembros (los que no llegan al saldo para
  reservar se ven en gris, con lo que les falta), el día, la PC y cuántas horas.
  No se cobra nada: su saldo es la garantía. Al que no llega se le carga saldo
  ahí mismo (pedido del dueño, 2026-10-26: "si tiene 2 hs, que pueda hacer la
  carga, por ejemplo $ 13.000 por 13 hs, para poder reservar"), con la ventana de
  Cargar Saldo de Miembros; esa carga queda en el saldo aunque esté jugando.
- DialogoSaldoParaReserva: el botón "$ Para Reserva" de Miembros, solo para el
  Admin: cuántas horas de saldo necesita un socio para reservar.

Están aparte de reservas_dialogos.py porque ese archivo ya va por las 580 líneas
(regla 12 de CLAUDE.md).
"""

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QComboBox, QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSpinBox,
    QVBoxLayout,
)

import dominio
from control_pcs.repositories import reservas_repo, reservas_socios_repo
from control_pcs.ui.reservas_dialogos import (
    _campo_hora, _encabezado, _gris_chico, _momento, _proxima_hora_en_punto, aviso_azul, texto_dia_y_hora,
)
from ui.piezas_ventana import tecla
from ui.utils import (
    crear_selector_de_fecha, encadenar_enter, fila_guardar_cancelar, icono_de_emoji, manejar_errores, mostrar_error,
    mostrar_info, sin_boton_por_defecto,
)


# El socio que no llega al saldo para reservar (el gris de lo apagado de Reservas).
COLOR_NO_LLEGA = "#9AA2AF"


def _campo_horas(minimo: int, maximo: int, valor: int) -> QSpinBox:
    """Un número de horas que se escribe ("5 hs"), sin flechitas: con esta hoja de
    estilos salían como una rayita (igual que en Miembros)."""
    campo = QSpinBox()
    campo.setRange(minimo, maximo)
    campo.setValue(valor)
    campo.setSuffix(" hs")
    campo.setButtonSymbols(QSpinBox.NoButtons)
    campo.setFixedWidth(90)
    return campo


class DialogoReservaDeSocio(QDialog):
    """Tomar la reserva de un socio, sin cobrar. Al aceptar queda
    `self.reserva_id`, el número de la reserva nueva."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.reserva_id = None
        self.setWindowTitle("Reserva de socio")
        self.resize(640, 700)
        self._armar_interfaz()
        self._cargar_socios()

    def _armar_interfaz(self):
        self.horas_minimas = reservas_socios_repo.horas_para_reservar()

        self.campo_buscar = QLineEdit()
        self.campo_buscar.setPlaceholderText("Buscar socio por usuario o nombre...")
        self.campo_buscar.addAction(icono_de_emoji("🔍", 14)[0], QLineEdit.LeadingPosition)
        self.campo_buscar.setClearButtonEnabled(True)
        self.campo_buscar.textChanged.connect(self._cargar_socios)
        self.lista_socios = QListWidget()
        self.lista_socios.setObjectName("listaSociosReserva")
        self.lista_socios.setMinimumHeight(180)
        self.lista_socios.currentItemChanged.connect(self._al_elegir_socio)

        # Debajo de la lista: si el elegido no llega, cuánto le falta; y para
        # cualquiera, cargarle saldo sin salir de acá.
        self.aviso_carga = QLabel()
        self.aviso_carga.setObjectName("avisoCargaSocio")
        self.aviso_carga.setWordWrap(True)
        self.boton_cargar = tecla("💰  CARGAR SALDO", self._cargar_saldo, "teclaVerde")
        fila_carga = QHBoxLayout()
        fila_carga.addWidget(self.aviso_carga, 1)
        fila_carga.addWidget(self.boton_cargar)

        inicio = _proxima_hora_en_punto()
        self.campo_dia = crear_selector_de_fecha(QDate(inicio.year, inicio.month, inicio.day))
        self.campo_hora = _campo_hora(QTime(inicio.hour, 0))
        fila_dia = QHBoxLayout()
        fila_dia.addWidget(self.campo_dia)
        fila_dia.addWidget(QLabel("Hora:"))
        fila_dia.addWidget(self.campo_hora)
        fila_dia.addStretch()

        # Solo PCs comunes: PCSTREAM y la PlayStation 5 no se usan con saldo de socio.
        self.combo_equipo = QComboBox()
        for opcion in reservas_repo.equipos_para_reservar():
            if opcion["equipo"] == dominio.EQUIPO_RESERVA_PC:
                self.combo_equipo.addItem(opcion["nombre"], opcion["estacion_id"])

        self.campo_horas = _campo_horas(1, dominio.HORAS_MAXIMAS_RESERVA_SOCIO, 2)

        formulario = QFormLayout()
        formulario.addRow("Día:", fila_dia)
        formulario.addRow("PC:", self.combo_equipo)
        formulario.addRow("", _gris_chico(
            "Con \"Cualquier PC disponible\" no se aparta ninguna PC. PCSTREAM y la PlayStation 5 no se "
            "usan con saldo de socio: esas se reservan con seña."
        ))
        formulario.addRow("Tiempo:", self.campo_horas)

        self.aviso = aviso_azul(
            "No paga nada ahora: su saldo es la garantía. Cuando llega, entra a la PC con su usuario y su clave "
            "y usa su saldo como siempre (la reserva queda habilitada sola). Si no viene (o llega más de "
            f"{dominio.MINUTOS_TOLERANCIA_RESERVA} minutos tarde), queda \"No vino\" y no pierde nada.",
        )

        layout = QVBoxLayout()
        layout.addWidget(_encabezado("Reserva de socio"))
        layout.addWidget(_gris_chico(
            f"Reservan los socios que tienen {reservas_socios_repo.texto_de_horas(self.horas_minimas * 60)} "
            "o más de saldo. Los que no llegan se ven en gris: elegilo y cargale saldo acá mismo."
        ))
        layout.addWidget(self.campo_buscar)
        layout.addWidget(self.lista_socios, 1)
        layout.addLayout(fila_carga)
        layout.addLayout(formulario)
        layout.addWidget(self.aviso)
        layout.addLayout(fila_guardar_cancelar(self, self._reservar, "Reservar"))
        self.setLayout(layout)
        encadenar_enter(self.campo_buscar, self.campo_dia, self.campo_hora, self.combo_equipo, self.campo_horas,
                        accion_final=self._reservar)
        sin_boton_por_defecto(self)
        self.campo_buscar.setFocus()

    @manejar_errores
    def _cargar_socios(self, _=None, elegir: int = None):
        """La lista con lo que se escribió en la lupa. Queda elegido el socio
        `elegir` (el que se acaba de cargar) o, si no, el primero que puede
        reservar, así se busca y se sigue con Enter."""
        self.lista_socios.clear()
        primero = None
        for socio in reservas_socios_repo.socios_para_reservar(self.campo_buscar.text()):
            saldo = reservas_socios_repo.texto_de_horas(socio["saldo_minutos"])
            texto = f"{socio['usuario']}  —  {socio['nombre']}  ·  saldo {saldo}"
            item = QListWidgetItem()
            item.setData(Qt.UserRole, socio)
            if not socio["alcanza"]:
                texto += f"  ·  le faltan {self._texto_falta(socio)}"
                # En gris (se elige igual, para cargarle saldo).
                item.setForeground(QColor(COLOR_NO_LLEGA))
            if socio["id"] == elegir or (elegir is None and primero is None and socio["alcanza"]):
                primero = item
            item.setText(texto)
            self.lista_socios.addItem(item)
        if primero is not None:
            self.lista_socios.setCurrentItem(primero)
        self._al_elegir_socio()

    def _texto_falta(self, socio) -> str:
        return reservas_socios_repo.texto_de_horas(self.horas_minimas * 60 - socio["saldo_minutos"])

    def _socio(self):
        item = self.lista_socios.currentItem()
        return item.data(Qt.UserRole) if item is not None else None

    def _al_elegir_socio(self, *_):
        """No puede reservar más horas que las que tiene de saldo; si no llega al
        mínimo, se dice cuánto le falta (y Cargar Saldo queda a mano)."""
        socio = self._socio()
        maximo = dominio.HORAS_MAXIMAS_RESERVA_SOCIO
        if socio is not None:
            maximo = max(1, min(maximo, socio["saldo_minutos"] // 60))
        self.campo_horas.setMaximum(maximo)
        self.boton_cargar.setEnabled(socio is not None)
        if socio is None:
            self.aviso_carga.setText("Elegí un socio de la lista.")
        elif socio["alcanza"]:
            self.aviso_carga.setText(
                f"{socio['nombre']} tiene {reservas_socios_repo.texto_de_horas(socio['saldo_minutos'])} "
                "de saldo: puede reservar.")
        else:
            self.aviso_carga.setText(
                f"{socio['nombre']} tiene {reservas_socios_repo.texto_de_horas(socio['saldo_minutos'])} "
                f"de saldo: le faltan {self._texto_falta(socio)} para reservar. Cargale saldo y seguí.")
        self.aviso_carga.setProperty("alerta", socio is not None and not socio["alcanza"])
        self.aviso_carga.style().unpolish(self.aviso_carga)
        self.aviso_carga.style().polish(self.aviso_carga)

    @manejar_errores
    def _cargar_saldo(self):
        """La ventana de Cargar Saldo de Miembros, para el socio elegido. Lo
        cargado queda en su saldo aunque esté usando una PC: es para la reserva."""
        socio = self._socio()
        if socio is None:
            return
        # Acá y no arriba: miembros_window importa este archivo (por $ Para Reserva).
        from control_pcs.ui.miembros_window import DialogoCargarSaldo
        if DialogoCargarSaldo(self.usuario, socio, self, a_la_sesion=False).exec():
            self._cargar_socios(elegir=socio["id"])
            self.campo_dia.setFocus()

    @manejar_errores
    def _reservar(self):
        socio = self._socio()
        if socio is None:
            mostrar_error(self, "Falta el socio", "Elegí de la lista el socio que reserva.")
            self.campo_buscar.setFocus()
            return
        inicio = _momento(self.campo_dia.date(), self.campo_hora.time())
        minutos = self.campo_horas.value() * 60
        self.reserva_id = reservas_socios_repo.crear_reserva_de_socio(
            self.usuario["id"], socio["id"], self.combo_equipo.currentData(), inicio, minutos,
        )
        mostrar_info(
            self, "Reserva tomada",
            f"Reserva Nº {self.reserva_id}: {socio['nombre']} (socio), {self.combo_equipo.currentText()}, "
            f"{texto_dia_y_hora(inicio.isoformat())}, {reservas_socios_repo.texto_de_horas(minutos)}.\n"
            "No se cobró nada: cuando llega, entra con su usuario y su clave y usa su saldo.",
        )
        self.accept()


class DialogoSaldoParaReserva(QDialog):
    """"$ Para Reserva" (Miembros, solo el Admin): las horas de saldo que necesita
    un socio para reservar sin seña. El repo vuelve a exigir Admin."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("$ Para Reserva")
        self.resize(440, 220)

        self.campo_horas = _campo_horas(1, dominio.HORAS_MAXIMAS_SALDO_PARA_RESERVAR,
                                        reservas_socios_repo.horas_para_reservar())
        formulario = QFormLayout()
        formulario.addRow("Saldo mínimo:", self.campo_horas)

        layout = QVBoxLayout()
        layout.addWidget(_encabezado("$ Para Reserva"))
        layout.addWidget(_gris_chico(
            "Las horas de saldo que tiene que tener un socio para reservar una PC sin seña. Cuenta al tomar la "
            "reserva: si el día que viene tiene menos, entra igual con lo que tenga."
        ))
        layout.addLayout(formulario)
        layout.addStretch()
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        encadenar_enter(self.campo_horas, accion_final=self._guardar)
        sin_boton_por_defecto(self)
        self.campo_horas.setFocus()
        self.campo_horas.selectAll()

    @manejar_errores
    def _guardar(self):
        reservas_socios_repo.guardar_horas_para_reservar(self.usuario["id"], self.campo_horas.value())
        self.accept()
