"""
reservas_window.py
====================
La ventana RESERVAS (botón de la barra, pedido del dueño 2026-10-20; es la
maqueta que aprobó): la lista de reservas con quién, cuándo, qué equipo, qué
bono, el precio, cuánto pagó, cuánto falta y cómo está, con los botones Nueva
reserva, Habilitar, Reprogramar, No vino y Devolver plata (solo el Admin).
Desde el 2026-10-26, con el diseño que eligió el dueño (maqueta "A" de
PROPUESTA_VENTANAS_ADMIN): cabecera oscura con cuántas hay hoy, cuántas esperan y
cuántas hay que reprogramar, No vino y Devolver plata en rojo y aparte, y el
estado de cada reserva como una pastilla de color.

Los formularios están en reservas_dialogos.py y las reglas en
control_pcs/repositories/reservas_repo.py. Se abre solo en el mostrador: cobra.
"RESERVA DE SOCIO" (2026-10-26) abre reservas_socio_dialogo.py: un socio con
saldo reserva sin seña; en la lista se ve "(socio)" y no tiene plata.
"""

from datetime import datetime

from PySide6.QtCore import QRectF, Qt
from PySide6.QtGui import QColor, QFont, QPainter
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QStyle, QStyledItemDelegate,
    QStyleOptionViewItem, QTableWidgetItem, QVBoxLayout,
)

import dominio
from turnos import dia_en_que_empezo_el_turno
from control_pcs.repositories import reservas_repo
from control_pcs.repositories import reservas_socios_repo
from control_pcs.ui.reservas_dialogos import (
    DialogoDevolver, DialogoHabilitarReserva, DialogoNuevaReserva, DialogoReprogramar, texto_dia_y_hora,
)
from control_pcs.ui.reservas_socio_dialogo import DialogoReservaDeSocio
from ui.piezas_ventana import (
    TONO_AZUL, TONO_CELESTE, TONO_NARANJA, agregar_pastilla, cabecera_oscura, linea_divisoria, tecla,
)
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, formato_pesos, icono_de_emoji, manejar_errores, mostrar_error,
    mostrar_info, sin_boton_por_defecto,
)

TITULOS = ("Nº", "Día y hora", "Cliente", "Celular", "Equipo", "Bono", "Precio", "Pagó", "Falta", "Estado")
COLUMNA_ESTADO = TITULOS.index("Estado")

# El color del estado en la lista, como en la maqueta: azul lo que espera,
# naranja lo que hay que reprogramar, verde lo que se usó, gris lo terminado.
COLOR_ESTADO = {
    dominio.RESERVA_PENDIENTE: "#1D5FD8",
    dominio.RESERVA_A_REPROGRAMAR: "#C2620A",
    dominio.RESERVA_HABILITADA: "#1F8A43",
    dominio.RESERVA_NO_VINO: "#8A93A3",
    dominio.RESERVA_VENCIDA: "#8A93A3",
    dominio.RESERVA_DEVUELTA: "#8A93A3",
}

# Las letras de una reserva terminada (no vino, vencida, devuelta), del Nº y de lo que
# falta pagar de una que espera.
COLOR_APAGADO = "#9AA2AF"
COLOR_FALTA = "#C2620A"

_DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")


def _texto_del_minimo() -> str:
    """El saldo que necesita un socio para reservar ("5 hs"), para la ayuda de abajo."""
    return reservas_socios_repo.texto_de_horas(reservas_socios_repo.horas_para_reservar() * 60)


def texto_estado(reserva: dict) -> str:
    """Cómo está una reserva, en palabras."""
    estado = reserva["estado"]
    if estado == dominio.RESERVA_PENDIENTE and reserva["es_de_socio"]:
        return "Pendiente · socio"
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


class _DelegadoEstado(QStyledItemDelegate):
    """La columna Estado: el texto dentro de una pastilla de su color (el de
    COLOR_ESTADO, guardado en la celda con Qt.UserRole), con un puntito adelante.
    El texto de la celda no cambia: esto es solo cómo se ve."""

    def paint(self, pintor, opcion, indice):
        opcion = QStyleOptionViewItem(opcion)
        self.initStyleOption(opcion, indice)
        texto = opcion.text
        opcion.text = ""
        # El fondo de la fila (elegida o alternada), sin el texto.
        opcion.widget.style().drawControl(QStyle.CE_ItemViewItem, opcion, pintor, opcion.widget)
        color = QColor(indice.data(Qt.UserRole) or COLOR_APAGADO)
        letra = QFont(opcion.font)
        letra.setBold(True)
        letra.setPixelSize(12)
        pintor.save()
        pintor.setRenderHint(QPainter.Antialiasing)
        pintor.setFont(letra)
        alto = 24
        pastilla = QRectF(opcion.rect.x() + 6, opcion.rect.center().y() - alto / 2 + 1,
                          pintor.fontMetrics().horizontalAdvance(texto) + 30, alto)
        fondo = QColor(color)
        fondo.setAlpha(30)
        pintor.setPen(Qt.NoPen)
        pintor.setBrush(fondo)
        pintor.drawRoundedRect(pastilla, alto / 2, alto / 2)
        pintor.setBrush(color)
        pintor.drawEllipse(QRectF(pastilla.x() + 10, pastilla.center().y() - 3, 6, 6))
        pintor.setPen(color)
        pintor.drawText(pastilla.adjusted(22, 0, 0, 0), Qt.AlignVCenter | Qt.AlignLeft, texto)
        pintor.restore()


class ReservasWindow(QDialog):
    """La lista de reservas y lo que se hace con cada una."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self.reservas = []
        self.setWindowTitle("Reservas")
        self.resize(1180, 640)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        # El día del local (de 06:00 a 06:00), el mismo con que cuenta la pastilla HOY.
        hoy = dia_en_que_empezo_el_turno(datetime.now())
        cabecera = cabecera_oscura(
            "📅", "Reservas", f"Hoy es {_DIAS[hoy.weekday()]} {hoy:%d/%m} · las que esperan van arriba")
        self.pastilla_hoy = agregar_pastilla(cabecera, "", TONO_AZUL)
        self.pastilla_esperan = agregar_pastilla(cabecera, "", TONO_CELESTE)
        self.pastilla_a_reprogramar = agregar_pastilla(cabecera, "", TONO_NARANJA)

        # Lo de todos los días primero; No vino y Devolver plata, en rojo y aparte.
        botones = QHBoxLayout()
        botones.setSpacing(8)
        botones.addWidget(tecla("＋  NUEVA RESERVA", self._nueva, "teclaAzul"))
        botones.addWidget(tecla("👤  RESERVA DE SOCIO", self._nueva_de_socio, "teclaAzul"))
        botones.addWidget(tecla("▶  HABILITAR", self._habilitar, "teclaVerde"))
        botones.addWidget(tecla("🗓️  REPROGRAMAR", self._reprogramar))
        botones.addSpacing(6)
        botones.addWidget(linea_divisoria(vertical=True))
        botones.addSpacing(6)
        botones.addWidget(tecla("NO VINO", self._no_vino, "teclaRoja"))
        # Lo aprieta cualquiera (avisa que es del Admin), con candado si no es Admin.
        botones.addWidget(tecla("DEVOLVER PLATA" if self.es_admin else "DEVOLVER PLATA  🔒", self._devolver,
                                "teclaRoja"))
        botones.addStretch()

        # "Todas" o "Las que esperan": dos botones en una pista, uno siempre elegido.
        pista = QFrame()
        pista.setObjectName("pistaSegmentos")
        capa_pista = QHBoxLayout(pista)
        capa_pista.setContentsMargins(3, 3, 3, 3)
        capa_pista.setSpacing(2)
        self._grupo_mostrar = QButtonGroup(self)
        for texto in ("TODAS", "LAS QUE ESPERAN"):
            segmento = QPushButton(texto)
            aplicar_clase(segmento, "segmento")
            segmento.setCheckable(True)
            self._grupo_mostrar.addButton(segmento)
            capa_pista.addWidget(segmento)
        self._grupo_mostrar.buttons()[0].setChecked(True)
        self.boton_solo_las_que_esperan = self._grupo_mostrar.buttons()[1]
        self._grupo_mostrar.buttonClicked.connect(lambda _boton: self._cargar())
        botones.addWidget(pista)

        self.campo_buscar = QLineEdit()
        self.campo_buscar.setPlaceholderText("Buscar por cliente o celular...")
        self.campo_buscar.addAction(icono_de_emoji("🔍", 14)[0], QLineEdit.LeadingPosition)
        self.campo_buscar.setMinimumWidth(220)
        self.campo_buscar.setClearButtonEnabled(True)
        self.campo_buscar.textChanged.connect(self._cargar)
        botones.addWidget(self.campo_buscar)

        self.tabla = crear_tabla(TITULOS, estirar=COLUMNA_ESTADO, por_filas=True, una_sola=True)
        self.tabla.setObjectName("tablaReservas")
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setDefaultSectionSize(38)
        self.tabla.setItemDelegateForColumn(COLUMNA_ESTADO, _DelegadoEstado(self.tabla))
        self.tabla.cellDoubleClicked.connect(lambda *_: self._habilitar())

        pie_ayuda = QFrame()
        pie_ayuda.setObjectName("pieAyuda")
        capa_ayuda = QHBoxLayout(pie_ayuda)
        capa_ayuda.setContentsMargins(14, 9, 14, 9)
        ayuda = QLabel(
            "ⓘ&nbsp; <b>No vino con seña:</b> la pierde. &nbsp;·&nbsp; <b>Pagó el 100%:</b> queda A reprogramar "
            f"(vence a los {dominio.DIAS_PARA_REPROGRAMAR_RESERVA} días) y ese día va a cualquier PC disponible. "
            f"&nbsp;·&nbsp; A los {dominio.MINUTOS_TOLERANCIA_RESERVA} minutos de la hora pasa sola. "
            "&nbsp;·&nbsp; <b>Devolver plata:</b> solo el Admin; sale de la caja de quien la entrega. "
            f"&nbsp;·&nbsp; <b>Socio</b> (con {_texto_del_minimo()} o más de saldo): no paga nada; entra con su "
            "usuario y usa su saldo."
        )
        ayuda.setWordWrap(True)
        capa_ayuda.addWidget(ayuda)
        pie = QHBoxLayout()
        pie.setSpacing(12)
        pie.addWidget(pie_ayuda, 1)
        pie.addWidget(tecla("SALIR", self.close))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(botones)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(pie)
        sin_boton_por_defecto(self)
        self.campo_buscar.setFocus()

    @manejar_errores
    def _cargar(self, _=None, elegir: int = None):
        """Vuelve a leer la lista (con los estados al día) y las pastillas de la
        cabecera, y deja elegida la reserva `elegir`, o la que estaba elegida."""
        if elegir is None:
            actual = self._elegida()
            elegir = actual["id"] if actual else None
        self.reservas = reservas_repo.listar_reservas(
            solo_abiertas=self.boton_solo_las_que_esperan.isChecked(),
            buscar=self.campo_buscar.text(),
        )
        self.tabla.setRowCount(0)
        for reserva in self.reservas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            sin_dia = reserva["estado"] == dominio.RESERVA_A_REPROGRAMAR
            if reserva["es_de_socio"]:
                # Sin plata: el precio y lo pagado no dicen nada.
                cliente = f"{reserva['cliente']} (socio)"
                bono = f"{reserva['bono_nombre']} · {reservas_socios_repo.texto_de_horas(reserva['minutos'])}"
                precio = pago = "—"
            else:
                cliente, bono = reserva["cliente"], reserva["bono_nombre"]
                precio, pago = formato_pesos(reserva["precio"]), formato_pesos(reserva["pagado"])
            textos = (
                str(reserva["id"]),
                "Sin día" if sin_dia else texto_dia_y_hora(reserva["fecha_reserva"]),
                cliente, reserva["celular"], reserva["equipo_nombre"], bono, precio, pago,
                formato_pesos(reserva["falta"]) if reserva["falta"] else "—",
                texto_estado(reserva),
            )
            for columna, texto in enumerate(textos):
                self.tabla.setItem(fila, columna, QTableWidgetItem(texto))
            self._pintar_fila(fila, reserva)
            if reserva["id"] == elegir:
                self.tabla.selectRow(fila)
        self.tabla.resizeColumnsToContents()
        # Un poco de aire entre columnas: la tabla no tiene rayas que las separen.
        for columna in range(COLUMNA_ESTADO):
            self.tabla.setColumnWidth(columna, self.tabla.columnWidth(columna) + 14)
        self._contar()

    def _pintar_fila(self, fila: int, reserva: dict):
        """Las que esperan, con el día y el cliente en negrita y lo que falta en
        naranja; las terminadas (no vino, vencida, devuelta), en gris; el estado,
        en la pastilla de su color."""
        espera = reserva["estado"] in dominio.ESTADOS_RESERVA_ABIERTA
        terminada = not espera and reserva["estado"] != dominio.RESERVA_HABILITADA
        for columna in range(self.tabla.columnCount()):
            item = self.tabla.item(fila, columna)
            if terminada or columna == 0:
                item.setForeground(QColor(COLOR_APAGADO))
            negrita = espera and (columna in (1, 2) or (columna == TITULOS.index("Falta") and reserva["falta"]))
            if negrita:
                letra = item.font()
                letra.setBold(True)
                item.setFont(letra)
        if espera and reserva["falta"]:
            self.tabla.item(fila, TITULOS.index("Falta")).setForeground(QColor(COLOR_FALTA))
        self.tabla.item(fila, COLUMNA_ESTADO).setData(Qt.UserRole, COLOR_ESTADO[reserva["estado"]])

    def _contar(self):
        """Las pastillas de la cabecera: las de hoy (como el botón de la barra), las
        que esperan y las que hay que reprogramar, sin el filtro ni la búsqueda."""
        abiertas = reservas_repo.listar_reservas(solo_abiertas=True)
        esperan = sum(1 for reserva in abiertas if reserva["estado"] == dominio.RESERVA_PENDIENTE)
        a_reprogramar = len(abiertas) - esperan
        self.pastilla_hoy.setText(f"HOY  {reservas_repo.reservas_de_hoy()}")
        self.pastilla_esperan.setText(f"ESPERAN  {esperan}")
        self.pastilla_a_reprogramar.setText(f"A REPROGRAMAR  {a_reprogramar}")
        self.pastilla_a_reprogramar.setVisible(bool(a_reprogramar))

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

    def _nueva_de_socio(self):
        dialogo = DialogoReservaDeSocio(self.usuario, self)
        if dialogo.exec():
            self._cargar(elegir=dialogo.reserva_id)

    @manejar_errores
    def _habilitar(self):
        reserva = self._elegida_o_aviso()
        if reserva is None:
            return
        if reserva["es_de_socio"]:
            # Abrirle la PC desde acá la dejaría sin pasar por su saldo.
            mostrar_info(self, "Reserva de socio",
                         f"{reserva['cliente']} es socio: que entre a la PC con su usuario y su clave (o abrila "
                         "con \"Abrir PC con Miembro\"). La reserva queda habilitada sola cuando entra.")
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
        if reserva["es_de_socio"]:
            que_pasa = "Es socio: no pagó nada, así que no pierde nada."
        elif reserva["falta"]:
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
