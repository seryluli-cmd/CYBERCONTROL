"""
tareas_turno_dialogos.py
=========================
TAREAS DEL TURNO (pedido del dueño, 2026-11-03): lo que abre la ventana de
ui/tareas_turno_window.py, aparte para que ningún archivo pase las ~600 líneas.

- DialogoTarea: + NUEVA TAREA y MODIFICAR (solo el Administrador). TAREA, HORA (como
  la escriban: "1930", "19:30", "19.30", "7:05"), el TURNO que sale de esa hora y SE
  REPITE: TODOS LOS DÍAS, ELEGIR DÍAS (lunes a domingo, en pastillas) o SOLO HOY.
- DialogoHistorialTareas: los días que ya terminaron, con quién hizo cada tarea y a
  qué hora (o NO SE HIZO) y cuántas veces la pospusieron y quiénes.
- Los textos que repiten la grilla, el historial y el aviso de ui/aviso_tarea.py
  (la hora de algo, el turno, lo pospuesto, HECHA · quién y a qué hora).

Las reglas están en repositories/tareas_turno_repo.py; acá solo se junta lo que
escriben y se muestra lo que el repo devuelve.
"""

from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QButtonGroup, QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout, QWidget,
)

import dominio
import turnos
from repositories import tareas_turno_repo
from ui.piezas_ventana import (
    agregar_indicador, cabecera_oscura, panel_blanco, panel_de_tabla, pie_de_ventana, poner_indicador, tecla,
    titulo_de_seccion,
)
from ui.utils import (
    aplicar_clase, armar_filtro_por_fechas, crear_tabla, encadenar_enter, fila_guardar_cancelar, manejar_errores,
    rango_de_fechas, sin_boton_por_defecto,
)

# Los colores de cada estado, en la grilla y en el historial.
COLOR_HECHA = "#1F7A45"
COLOR_ATRASADA = "#C62828"
COLOR_PRONTO = "#B7791F"
COLOR_MAS_TARDE = "#7A8699"
# Lo ya hecho, apagado (y tachado) para que se lea lo que falta.
COLOR_APAGADO = "#9AA3B2"
# Cuántas veces se nombra quién la pospuso: con más, se ven las últimas (el aviso las
# muestra en una línea, y con un mostrador que la pospuso toda la tarde no entraría).
POSPUESTAS_A_LA_VISTA = 3
# Con cuántos días para atrás arranca el historial.
DIAS_DEL_HISTORIAL = 7


def hora_de(momento: str) -> str:
    """"19:42" de un momento ISO como los que devuelve el repo."""
    return datetime.fromisoformat(momento).strftime("%H:%M")


def nombre_del_turno(tarea) -> str:
    """El turno de una aparición como se lee: "Tarde"."""
    return turnos.etiqueta_turno(tarea["dia"], tarea["turno"])


def texto_hecha(tarea) -> str:
    """"HECHA · Carla 19:42": quién la marcó y a qué hora."""
    return f"HECHA · {tarea['hecha_por']} {hora_de(tarea['hecha_en'])}"


def texto_de_lo_pospuesto(posposiciones) -> str:
    """"1 vez (Carla, 19:30)" o "4 veces (… Gaby, 19:35 · Carla, 19:40 · Gaby,
    19:50)"; "" si nadie la pospuso. Lo usan el aviso y el historial."""
    if not posposiciones:
        return ""
    veces = len(posposiciones)
    cuantas = "1 vez" if veces == 1 else f"{veces} veces"
    ultimas = " · ".join(f"{p['nombre']}, {hora_de(p['fecha'])}" for p in posposiciones[-POSPUESTAS_A_LA_VISTA:])
    return f"{cuantas} ({'… ' if veces > POSPUESTAS_A_LA_VISTA else ''}{ultimas})"


def _como_qdate(dia) -> QDate:
    return QDate(dia.year, dia.month, dia.day)


class DialogoTarea(QDialog):
    """
    + NUEVA TAREA (`tarea` None) o MODIFICAR (`tarea`, uno de los dicts de
    tareas_turno_repo.listar_tareas). Solo lo abre el Administrador, y el repo lo
    vuelve a exigir al guardar. `ahora` es el reloj (para las pruebas). Al guardar
    queda en `tarea_id` el número de la tarea.

    No tiene se_puede_cerrar_sola: es un formulario a medio escribir, y el cierre
    forzoso de la caja espera a que se cierre (como con cualquier formulario).
    """

    def __init__(self, usuario, tarea=None, parent=None, ahora=datetime.now):
        super().__init__(parent)
        self.usuario = usuario
        self._tarea = tarea
        self._ahora = ahora
        self.tarea_id = None
        self.setWindowTitle("Modificar tarea" if tarea else "Nueva tarea")
        self.setMinimumWidth(620)
        self._armar_interfaz()
        if tarea is not None:
            self._poner(tarea)
        self._cambio_la_repeticion()
        self._mostrar_turno()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura(
            "⏰", "Modificar tarea" if self._tarea else "Nueva tarea",
            "A la hora sale un aviso encima de todo, hasta que alguien pone TAREA HECHA")

        panel, capa = panel_blanco()
        capa.addWidget(titulo_de_seccion("Tarea"))
        self.campo_tarea = QLineEdit()
        self.campo_tarea.setMaxLength(dominio.LARGO_MAXIMO_TAREA)
        self.campo_tarea.setPlaceholderText("Ej.: PRENDER LAS LUCES DE AFUERA")
        self.campo_tarea.setMinimumHeight(38)
        capa.addWidget(self.campo_tarea)

        self.campo_hora = QLineEdit()
        self.campo_hora.setPlaceholderText("19:30")
        self.campo_hora.setMaxLength(8)
        self.campo_hora.setFixedWidth(130)
        self.campo_hora.setMinimumHeight(38)
        self.campo_hora.textChanged.connect(self._mostrar_turno)
        # El turno sale solo de la hora (no se elige): así no puede quedar una tarea
        # de las 19:30 anotada en la Mañana.
        self.etiqueta_turno = QLabel("—")
        self.etiqueta_turno.setObjectName("turnoDeLaTarea")
        columna_hora = QVBoxLayout()
        columna_hora.addWidget(titulo_de_seccion("Hora"))
        columna_hora.addWidget(self.campo_hora)
        columna_turno = QVBoxLayout()
        columna_turno.addWidget(titulo_de_seccion("Turno"))
        columna_turno.addWidget(self.etiqueta_turno)
        fila_hora = QHBoxLayout()
        fila_hora.addLayout(columna_hora)
        fila_hora.addSpacing(28)
        fila_hora.addLayout(columna_turno, 1)
        capa.addLayout(fila_hora)

        capa.addWidget(titulo_de_seccion("Se repite"))
        self._pastillas_repeticion = {}
        grupo = QButtonGroup(self)
        grupo.setExclusive(True)
        fila_repeticion = QHBoxLayout()
        fila_repeticion.setSpacing(6)
        for repeticion in dominio.REPETICIONES_TAREA:
            pastilla = self._pastilla(dominio.NOMBRE_REPETICION_TAREA[repeticion])
            grupo.addButton(pastilla)
            self._pastillas_repeticion[repeticion] = pastilla
            fila_repeticion.addWidget(pastilla)
        fila_repeticion.addStretch()
        capa.addLayout(fila_repeticion)
        self._pastillas_repeticion[dominio.TAREA_TODOS_LOS_DIAS].setChecked(True)

        # Los días de ELEGIR DÍAS (lunes a domingo); se ven solo con esa opción.
        self.fila_dias = QWidget()
        capa_dias = QHBoxLayout(self.fila_dias)
        capa_dias.setContentsMargins(0, 0, 0, 0)
        capa_dias.setSpacing(6)
        self._pastillas_dias = []
        for nombre in dominio.DIAS_DE_LA_SEMANA:
            pastilla = self._pastilla(nombre.upper())
            self._pastillas_dias.append(pastilla)
            capa_dias.addWidget(pastilla)
        capa_dias.addStretch()
        capa.addWidget(self.fila_dias)
        # Qué día es SOLO HOY (a la madrugada, el día del local es el de ayer).
        self.aclaracion = QLabel()
        self.aclaracion.setObjectName("pieDeVentana")
        self.aclaracion.setWordWrap(True)
        capa.addWidget(self.aclaracion)
        # Recién ahora: con la fila de los días y la aclaración ya armadas.
        for pastilla in self._pastillas_repeticion.values():
            pastilla.toggled.connect(self._cambio_la_repeticion)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(panel)
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        # Enter en TAREA pasa a HORA, y en HORA guarda.
        encadenar_enter(self.campo_tarea, self.campo_hora, accion_final=self._guardar)
        sin_boton_por_defecto(self)
        self.campo_tarea.setFocus()

    @staticmethod
    def _pastilla(texto: str) -> QPushButton:
        pastilla = QPushButton(texto)
        aplicar_clase(pastilla, "filtro")
        pastilla.setCheckable(True)
        pastilla.setCursor(Qt.PointingHandCursor)
        return pastilla

    def _poner(self, tarea):
        """MODIFICAR: el formulario con la tarea como está."""
        self.campo_tarea.setText(tarea["texto"])
        self.campo_hora.setText(tarea["hora"])
        self._pastillas_repeticion[tarea["repeticion"]].setChecked(True)
        for numero, pastilla in enumerate(self._pastillas_dias):
            pastilla.setChecked(numero in tarea["dias_semana"])

    def repeticion_elegida(self) -> str:
        return next(r for r, pastilla in self._pastillas_repeticion.items() if pastilla.isChecked())

    def dias_elegidos(self) -> list:
        return [numero for numero, pastilla in enumerate(self._pastillas_dias) if pastilla.isChecked()]

    def _hoy(self):
        return turnos.dia_en_que_empezo_el_turno(self._ahora())

    def _cambio_la_repeticion(self, *_):
        repeticion = self.repeticion_elegida()
        self.fila_dias.setVisible(repeticion == dominio.TAREA_ALGUNOS_DIAS)
        if repeticion == dominio.TAREA_UN_SOLO_DIA:
            madrugada = self._ahora().hour < turnos.HORA_CAMBIO_DE_DIA
            self.aclaracion.setText(
                f"Solo hoy, {dominio.nombre_del_dia(self._hoy())}"
                + (" (hasta las 06:00 sigue siendo el día que empezó ayer)." if madrugada else "."))
        elif repeticion == dominio.TAREA_ALGUNOS_DIAS:
            self.aclaracion.setText("Tocá los días. Una tarea de antes de las 06:00 es de la Noche de ese día.")
        else:
            self.aclaracion.setText("")
        self.aclaracion.setVisible(bool(self.aclaracion.text()))

    def _mostrar_turno(self, *_):
        """El turno que le toca a la hora escrita, con la hora como va a quedar
        ("1930" → 19:30), o "—" mientras no se entienda."""
        try:
            hora = dominio.hora_de_tarea(self.campo_hora.text())
        except ValueError:
            self.etiqueta_turno.setText("—")
            return
        hoy = self._hoy()
        turno = turnos.calcular_turno(turnos.momento_de_la_tarea(hoy, hora))
        self.etiqueta_turno.setText(f"{turnos.etiqueta_turno(hoy, turno)}  ·  a las {hora}")

    @manejar_errores
    def _guardar(self):
        argumentos = (self.campo_tarea.text(), self.campo_hora.text(), self.repeticion_elegida(), self.dias_elegidos())
        if self._tarea is None:
            self.tarea_id = tareas_turno_repo.crear_tarea(self.usuario["id"], *argumentos, ahora=self._ahora())
        else:
            tareas_turno_repo.modificar_tarea(self.usuario["id"], self._tarea["id"], *argumentos, ahora=self._ahora())
            self.tarea_id = self._tarea["id"]
        self.accept()


class DialogoHistorialTareas(QDialog):
    """Los días que ya terminaron (el de hoy está en la ventana de Tareas del Turno):
    cada tarea con su día y su hora, HECHA por quién y a qué hora o NO SE HIZO, y
    cuántas veces la pospusieron y quiénes. El día más nuevo primero."""

    COLUMNAS = ["Día", "Hora", "Tarea", "Qué pasó", "La pospusieron"]

    def __init__(self, parent=None, ahora=datetime.now):
        super().__init__(parent)
        self._ahora = ahora
        self.setWindowTitle("Tareas del Turno · Historial")
        self.resize(1100, 620)
        cabecera = cabecera_oscura("📋", "Historial", "Los días que ya terminaron: quién hizo cada tarea y a qué hora")
        self.indicador_hechas = agregar_indicador(cabecera, "Hechas")
        self.indicador_no_se_hicieron = agregar_indicador(cabecera, "No se hicieron")

        hoy = turnos.dia_en_que_empezo_el_turno(ahora())
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self.buscar, desde_inicial=_como_qdate(hoy - timedelta(days=DIAS_DEL_HISTORIAL)), dias_del_local=True)
        # Hasta ayer: el día de hoy todavía no terminó y no está acá.
        self.fecha_hasta.setDate(_como_qdate(hoy - timedelta(days=1)))

        self.tabla = crear_tabla(self.COLUMNAS, estirar=2, por_filas=True, una_sola=True)
        for columna, ancho in ((0, 130), (1, 70), (3, 210), (4, 300)):
            self.tabla.setColumnWidth(columna, ancho)

        barra = QHBoxLayout()
        barra.addStretch()
        barra.addWidget(tecla("CERRAR", self.close, "teclaRoja"))
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(filtros)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        layout.addWidget(pie_de_ventana(
            "El día del local va de 06:00 a 06:00: una tarea de las 02:00 está en el día en que empezó la Noche  ·  "
            "El día de hoy aparece acá cuando termina"))
        layout.addLayout(barra)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.buscar()

    def se_puede_cerrar_sola(self) -> bool:
        """Solo es una lista: el cierre forzoso la cierra y sigue con la de abajo."""
        return True

    @manejar_errores
    def buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        filas = tareas_turno_repo.listar_historial(desde, hasta, ahora=self._ahora())
        hechas = sum(tarea["estado"] == dominio.TAREA_HECHA for tarea in filas)
        poner_indicador(self.indicador_hechas, str(hechas))
        poner_indicador(self.indicador_no_se_hicieron, str(len(filas) - hechas), alerta=len(filas) > hechas)
        self.tabla.setRowCount(len(filas))
        for fila, tarea in enumerate(filas):
            hecha = tarea["estado"] == dominio.TAREA_HECHA
            texto = tarea["texto"] + ("  (después la borraron)" if tarea["borrada"] else "")
            que_paso = QTableWidgetItem(texto_hecha(tarea) if hecha else dominio.TAREA_NO_SE_HIZO)
            que_paso.setForeground(QColor(COLOR_HECHA if hecha else COLOR_ATRASADA))
            fuente = que_paso.font()
            fuente.setBold(True)
            que_paso.setFont(fuente)
            pospuesta = QTableWidgetItem(texto_de_lo_pospuesto(tarea["posposiciones"]) or "—")
            # Entera en el cartelito: en la celda se ven las últimas.
            pospuesta.setToolTip("\n".join(f"{p['nombre']}, {hora_de(p['fecha'])} ({p['minutos']} min)"
                                           for p in tarea["posposiciones"]))
            celdas = (QTableWidgetItem(dominio.nombre_del_dia(tarea["dia"])), QTableWidgetItem(tarea["hora"]),
                      QTableWidgetItem(texto), que_paso, pospuesta)
            for columna, celda in enumerate(celdas):
                self.tabla.setItem(fila, columna, celda)
        # Sin celda actual: si no, la primera se dibuja con el recuadro del foco.
        self.tabla.setCurrentCell(-1, -1)
