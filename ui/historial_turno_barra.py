"""
historial_turno_barra.py
=========================
En HISTORIAL DEL TURNO, la barra del Administrador para elegir el día y el turno
(pedido del dueño, 2026-11-20: "poder revisar, elegir el día, el turno; pero que
al ingresar por defecto solo muestre el turno actual"; "el operador solo puede ver
su turno actual, el admin puede navegar entre todos los días y turnos"; maqueta de
PROPUESTA_HISTORIAL_DEL_TURNO/3_ELEGIR_DIA_Y_TURNO):

- ◀ ▶ pasan de a un turno (al terminar los de un día, siguen con los del de al lado);
- la fecha abre el calendario, para saltar a cualquier día;
- las pastillas son los turnos de ese día, con su horario y quién tenía la caja.

Y la franja amarilla que avisa que lo que se ve es un turno ya cerrado, con la
tecla para volver al actual. La ventana (ui/historial_turno_window.py) pone la
barra solo si el repo dice que quien entró puede mirar otros turnos; el repo lo
vuelve a exigir igual (historial_turno_repo.turnos_del_dia y historial_del_turno).
"""

from datetime import date

from PySide6.QtCore import QDate, QLocale, Signal
from PySide6.QtWidgets import QButtonGroup, QFrame, QHBoxLayout, QLabel, QPushButton

from repositories import historial_turno_repo
from ui.piezas_ventana import tecla
from ui.utils import aplicar_clase, crear_selector_de_fecha, hoy_del_local, manejar_errores

_CASTELLANO = QLocale(QLocale.Spanish, QLocale.Argentina)


def texto_de_la_pastilla(turno: dict) -> str:
    """"NOCHE · 22:01 a 06:04 · MATI", o "● TARDE · EN CURSO desde las 14:01 ·
    ANTONELLA" el que está abierto."""
    nombre = turno["turno_label"].upper()
    if turno["hasta"] is None:
        partes = [f"●  {nombre}", f"EN CURSO desde las {turno['desde']}" if turno["desde"] else "EN CURSO"]
    else:
        partes = [nombre, f"{turno['desde']} a {turno['hasta']}" if turno["desde"] else f"hasta las {turno['hasta']}"]
    if turno["responsable"]:
        partes.append(turno["responsable"])
    return "  ·  ".join(partes)


class BarraDeTurnos(QFrame):
    """◀, la fecha, ▶ y los turnos del día. Avisa con `eligieron(cierre_id)`
    (None: el turno abierto) y con `anterior`/`siguiente`; qué turno se muestra lo
    decide la ventana, que después llama a `mostrar`."""

    eligieron = Signal(object)
    anterior = Signal()
    siguiente = Signal()

    def __init__(self, usuario_id: int, parent=None):
        super().__init__(parent)
        self.usuario_id = usuario_id
        self.setObjectName("barraDeTurnos")
        self._cierre_id = None
        capa = QHBoxLayout(self)
        capa.setContentsMargins(12, 10, 12, 10)
        capa.setSpacing(8)

        self.boton_anterior = tecla("◀", lambda: self.anterior.emit())
        self.boton_anterior.setObjectName("flechaDeTurno")
        self.boton_anterior.setFixedWidth(46)
        self.boton_anterior.setToolTip("El turno anterior")
        self.campo_dia = crear_selector_de_fecha(hoy_del_local())
        self.campo_dia.setLocale(_CASTELLANO)
        self.campo_dia.calendarWidget().setLocale(_CASTELLANO)
        self.campo_dia.setDisplayFormat("dddd dd/MM/yyyy")
        self.campo_dia.setMinimumWidth(185)
        self.campo_dia.setToolTip("Elegí el día: se ven sus turnos al lado")
        self.campo_dia.dateChanged.connect(self._cambio_el_dia)
        self.boton_siguiente = tecla("▶", lambda: self.siguiente.emit())
        self.boton_siguiente.setObjectName("flechaDeTurno")
        self.boton_siguiente.setFixedWidth(46)
        self.boton_siguiente.setToolTip("El turno siguiente")
        titulo = QLabel("TURNOS DEL DÍA")
        titulo.setObjectName("tituloBarraTurnos")
        self.etiqueta_sin_turnos = QLabel("Ese día no hubo turnos.")
        self.etiqueta_sin_turnos.setObjectName("sinTurnos")
        self.etiqueta_sin_turnos.hide()

        capa.addWidget(self.boton_anterior)
        capa.addWidget(self.campo_dia)
        capa.addWidget(self.boton_siguiente)
        capa.addSpacing(10)
        capa.addWidget(titulo)
        self._capa_pastillas = QHBoxLayout()
        self._capa_pastillas.setSpacing(8)
        capa.addLayout(self._capa_pastillas)
        capa.addWidget(self.etiqueta_sin_turnos)
        capa.addStretch()
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self.pastillas = []
        self.turnos = []

    def mostrar(self, dia: date, cierre_id, hay_anterior: bool, hay_siguiente: bool):
        """Pone la barra en el turno que muestra la ventana, sin volver a avisar."""
        self._cierre_id = cierre_id
        self.campo_dia.blockSignals(True)
        self.campo_dia.setDate(QDate(dia.year, dia.month, dia.day))
        self.campo_dia.blockSignals(False)
        self._cargar_turnos(dia)
        self.boton_anterior.setEnabled(hay_anterior)
        self.boton_siguiente.setEnabled(hay_siguiente)

    def _cargar_turnos(self, dia: date) -> list:
        datos = historial_turno_repo.turnos_del_dia(self.usuario_id, dia)
        self.campo_dia.blockSignals(True)
        if datos["primer_dia"] is not None:
            primero = datos["primer_dia"]
            self.campo_dia.setMinimumDate(QDate(primero.year, primero.month, primero.day))
        self.campo_dia.setMaximumDate(hoy_del_local())
        self.campo_dia.blockSignals(False)
        for pastilla in self.pastillas:
            self._grupo.removeButton(pastilla)
            # Sacarla ya de la barra: deleteLater solo la borra cuando vuelve el
            # bucle de eventos, y hasta entonces seguía dibujada (y marcada) al
            # lado de los turnos del día nuevo.
            pastilla.setParent(None)
            pastilla.deleteLater()
        self.pastillas = []
        self.turnos = datos["turnos"]
        for turno in self.turnos:
            pastilla = QPushButton(texto_de_la_pastilla(turno))
            aplicar_clase(pastilla, "filtro")
            pastilla.setCheckable(True)
            pastilla.setChecked(turno["cierre_id"] == self._cierre_id)
            pastilla.clicked.connect(lambda _marcada, cierre_id=turno["cierre_id"]: self.eligieron.emit(cierre_id))
            self._grupo.addButton(pastilla)
            self._capa_pastillas.addWidget(pastilla)
            self.pastillas.append(pastilla)
        self.etiqueta_sin_turnos.setVisible(not self.turnos)
        return self.turnos

    @manejar_errores
    def _cambio_el_dia(self, fecha: QDate):
        """Elegido otro día en el calendario: se ve su primer turno."""
        turnos = self._cargar_turnos(fecha.toPython())
        if turnos:
            self.eligieron.emit(turnos[0]["cierre_id"])


class AvisoTurnoCerrado(QFrame):
    """La franja amarilla de un turno ya cerrado: es solo para mirar."""

    def __init__(self, al_volver, parent=None):
        super().__init__(parent)
        self.setObjectName("avisoTurnoCerrado")
        capa = QHBoxLayout(self)
        capa.setContentsMargins(14, 8, 10, 8)
        self.texto = QLabel("👁   <b>Turno cerrado: solo para mirar.</b>  Desde acá no se anula ni se cambia nada."
                            "  ·  El TOTAL es el mismo de su Cierre de Turno.")
        self.texto.setWordWrap(True)
        capa.addWidget(self.texto, 1)
        self.boton_volver = tecla("⟲  VOLVER AL TURNO ACTUAL", al_volver, "teclaVerde")
        capa.addWidget(self.boton_volver)
