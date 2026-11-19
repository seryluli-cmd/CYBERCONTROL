"""
ui/aviso_tarea.py
=================
El aviso de TAREAS DEL TURNO (pedido del dueño, 2026-11-03, con la maqueta que vio
ese día): cuando llega la hora de una tarea ("PRENDER LAS LUCES DE AFUERA" a las
19:30) sale un aviso ENCIMA DE TODAS LAS VENTANAS, también de Vender, de otro
programa (WhatsApp Web) o con el programa minimizado, con POSPONER 5 MIN, POSPONER 10
MIN y TAREA HECHA. Pospuesta, vuelve a salir a los 5 o 10 minutos, una y otra vez,
hasta que alguien pone TAREA HECHA. Las reglas (qué toca y cuándo, quién puede) están
en repositories/tareas_turno_repo.py.

Lo que se le dijo al dueño que pasa, y por qué:

- No se cierra con la cruz ni con Esc: hay que elegir una de las tres. Enter (y
  cualquier tecla) no aprieta nada: la pistola de códigos escribe dígitos + Enter, y
  si justo están vendiendo no puede marcarla hecha sin querer.
- Los botones responden recién MILISEGUNDOS_SIN_RESPONDER después de que sale (un
  toque que ya iba a otra cosa no lo aprieta; tampoco el segundo toque de un doble
  clic en TAREA HECHA, que caería en el aviso de la tarea siguiente).
- Si tocan dos a la vez, salen de a una ("1 de 2").
- Solo en el mostrador y solo con alguien adentro: lo arranca MainWindow (no la copia
  abierta desde otra PC) y al cerrar la sesión el aviso se cierra.
- Si llega el cierre forzoso de la caja o la vuelta sola del Admin, el aviso se corre
  para dejarlos pasar (MainWindow._hay_un_cobro_a_medias lo cierra con reject, como
  a cualquier ventana que se puede cerrar sola). Eso no cuenta como posponer, y no
  vuelve a salir hasta SEGUNDOS_SIN_AVISAR_TRAS_CORRERSE después: si saliera en la
  revisión siguiente, el cierre forzoso (que mira cada 10 s) nunca pasaría. No se
  corre si abajo queda otra ventana que no se cierra sola (Compras, un formulario):
  ellos igual tienen que esperar (ver se_puede_cerrar_sola).
- Cerca de las 06:00 avisa que, si la posponen, ya no vuelve: los avisos son solo
  del día del local en curso (tareas_turno_repo.minutos_que_no_vuelven).

El aviso va sin ventana madre, como el cartel de ui/espera_del_mostrador.py: la de
adelante puede estar por cerrarse, y un aviso hijo se cerraría con ella. Es modal
para todo el programa pero se muestra con show(), no con exec(): así sale y se
contesta aunque Vender esté abierta con su propio exec().
"""

from datetime import datetime, timedelta

from PySide6.QtCore import QEvent, QObject, Qt, QTimer, Signal
from PySide6.QtWidgets import QApplication, QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import dominio
import turnos
from errores import registrar_error
from repositories import tareas_turno_repo
from ui.tareas_turno_dialogos import nombre_del_turno, texto_de_lo_pospuesto
from ui.utils import manejar_errores, sin_boton_por_defecto

# Cada cuánto se mira si llegó la hora de alguna tarea (y cuántas hay atrasadas, el
# número del botón TAREAS de la barra). Un aviso que sale hasta 15 s tarde no le cambia nada a nadie.
INTERVALO_REVISION_TAREAS_MS = 15_000
# La primera revisión, un rato después de entrar: con la ventana principal ya en la
# pantalla (el aviso que sale antes que ella queda raro).
MILISEGUNDOS_PRIMERA_REVISION = 2_000
MILISEGUNDOS_SIN_RESPONDER = 1_000
SEGUNDOS_SIN_AVISAR_TRAS_CORRERSE = 60

# Con barra de título (se puede correr de lugar) pero sin la cruz, y siempre adelante.
BANDERAS_DEL_AVISO = Qt.Dialog | Qt.CustomizeWindowHint | Qt.WindowTitleHint | Qt.WindowStaysOnTopHint
TEXTO_HECHA = "✔  TAREA HECHA"


def _clave(tarea) -> tuple:
    """Una aparición: la tarea en un día del local."""
    return tarea["tarea_id"], tarea["dia"]


class AvisoDeTarea(QDialog):
    """
    El aviso de UNA tarea (`tarea`, uno de los dicts de
    tareas_turno_repo.tareas_para_avisar). POSPONER y TAREA HECHA graban a nombre de
    `usuario_id`, con la hora de `ahora()`, y avisan con `contestada`; si el
    programa lo corre (reject: el cierre forzoso o la vuelta del Admin), avisa con
    `corrida`. Lo maneja RevisorDeTareas.
    """

    contestada = Signal()
    corrida = Signal()

    def __init__(self, tarea, usuario_id: int, ahora, numero: int = 1, de_cuantas: int = 1):
        super().__init__(None, BANDERAS_DEL_AVISO)
        self.tarea = tarea
        self._usuario_id = usuario_id
        self._ahora = ahora
        # Contestado o corrido: una sola vez (un segundo toque, o el reject del cierre
        # forzoso justo después de un toque, no hacen nada).
        self._contestado = False
        self.setObjectName("avisoTarea")
        self.setWindowTitle("CyberBIOS - Tarea del turno")
        self.setWindowModality(Qt.ApplicationModal)
        self._armar_interfaz()
        self.poner_numero(numero, de_cuantas)
        self._timer_teclas = QTimer(self)
        self._timer_teclas.setSingleShot(True)
        self._timer_teclas.setInterval(MILISEGUNDOS_SIN_RESPONDER)
        self._timer_teclas.timeout.connect(self._prender_teclas)

    def _armar_interfaz(self):
        cabecera = QFrame()
        cabecera.setObjectName("cabeceraAviso")
        circulo = QLabel("⏰")
        circulo.setObjectName("circuloAviso")
        circulo.setFixedSize(64, 64)
        circulo.setAlignment(Qt.AlignCenter)
        self.etiqueta_hora = QLabel(f"ES LA HORA · {self.tarea['hora']}")
        self.etiqueta_hora.setObjectName("horaAviso")
        self.etiqueta_texto = QLabel(self.tarea["texto"])
        self.etiqueta_texto.setObjectName("textoAviso")
        # Lo escribió una persona: "<" o "&" se ven tal cual, no como formato.
        self.etiqueta_texto.setTextFormat(Qt.PlainText)
        self.etiqueta_texto.setWordWrap(True)
        self.etiqueta_turno = QLabel()
        self.etiqueta_turno.setObjectName("turnoAviso")
        textos = QVBoxLayout()
        textos.setSpacing(4)
        for etiqueta in (self.etiqueta_hora, self.etiqueta_texto, self.etiqueta_turno):
            textos.addWidget(etiqueta)
        fila = QHBoxLayout(cabecera)
        fila.setContentsMargins(18, 16, 18, 16)
        fila.setSpacing(16)
        fila.addWidget(circulo, 0, Qt.AlignTop)
        fila.addLayout(textos, 1)

        self.etiqueta_pospuesta = QLabel()
        self.etiqueta_pospuesta.setObjectName("pospuestaAviso")
        lo_pospuesto = texto_de_lo_pospuesto(self.tarea["posposiciones"])
        self.etiqueta_pospuesta.setText(f"Ya la pospusieron {lo_pospuesto}" if lo_pospuesto else "")
        self.etiqueta_pospuesta.setVisible(bool(lo_pospuesto))
        # Cerca de las 06:00: que se sepa que pospuesta ya no vuelve (poner_al_dia).
        self.etiqueta_fin_del_dia = QLabel()
        self.etiqueta_fin_del_dia.setObjectName("finDelDiaAviso")
        self.etiqueta_fin_del_dia.setWordWrap(True)

        self.botones_posponer = {}
        fila_posponer = QHBoxLayout()
        fila_posponer.setSpacing(10)
        for minutos in dominio.MINUTOS_PARA_POSPONER:
            boton = QPushButton(f"POSPONER {minutos} MIN")
            boton.setObjectName("teclaPosponer")
            boton.clicked.connect(lambda _=False, m=minutos: self._contestar(self._posponer, m))
            self.botones_posponer[minutos] = boton
            fila_posponer.addWidget(boton)
        self.boton_hecha = QPushButton(TEXTO_HECHA)
        self.boton_hecha.setObjectName("teclaTareaHecha")
        self.boton_hecha.clicked.connect(lambda _=False: self._contestar(self._hecha))
        self.teclas = (*self.botones_posponer.values(), self.boton_hecha)
        for boton in self.teclas:
            # Sin foco y sin teclado: ninguna tecla las aprieta, solo el clic.
            boton.setFocusPolicy(Qt.NoFocus)
            boton.installEventFilter(self)
            boton.setEnabled(False)

        layout = QVBoxLayout()
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(self.etiqueta_pospuesta)
        layout.addWidget(self.etiqueta_fin_del_dia)
        layout.addLayout(fila_posponer)
        layout.addWidget(self.boton_hecha)
        self.setLayout(layout)
        self.setMinimumWidth(600)
        sin_boton_por_defecto(self)
        self.poner_al_dia()

    def poner_al_dia(self):
        """La línea del fin del día, con la hora de ahora: al salir y en cada revisión
        mientras sigue abierto (si sale a las 05:40 y lo contestan a las 05:56, tiene
        que decirlo). Si los minutos de POSPONER llegan a las 06:00, ya no vuelve:
        la revisión siguiente puede tardar INTERVALO_REVISION_TAREAS_MS."""
        no_vuelven = tareas_turno_repo.minutos_que_no_vuelven(
            self.tarea["dia"], self._ahora(), margen_segundos=INTERVALO_REVISION_TAREAS_MS // 1000)
        if not no_vuelven:
            self.etiqueta_fin_del_dia.setText("")
        else:
            cuales = ("" if len(no_vuelven) == len(dominio.MINUTOS_PARA_POSPONER)
                      else " " + " o ".join(str(minutos) for minutos in no_vuelven) + " MIN")
            self.etiqueta_fin_del_dia.setText(
                f"A las {turnos.HORA_CAMBIO_DE_DIA:02d}:00 termina el día: si la posponés{cuales}, "
                f"no vuelve a avisar y queda {dominio.TAREA_NO_SE_HIZO}.")
        self.etiqueta_fin_del_dia.setVisible(bool(no_vuelven))

    def poner_numero(self, numero: int, de_cuantas: int):
        """"Turno Tarde · 1 de 2" (con una sola, sin el "1 de 1")."""
        cuantas = f" · {numero} de {de_cuantas}" if de_cuantas > 1 else ""
        self.etiqueta_turno.setText(f"Turno {nombre_del_turno(self.tarea)}{cuantas}")

    def mostrar(self):
        """Adelante de todo: también sobre otro programa o con el programa minimizado
        (WindowStaysOnTopHint), y la barra de tareas titila si Windows no le deja
        tomar el teclado."""
        self.show()
        self.raise_()
        self.activateWindow()
        QApplication.alert(self)

    def showEvent(self, evento):
        super().showEvent(evento)
        # El segundo sin responder cuenta desde que sale (no al volver de minimizado).
        if not evento.spontaneous():
            for boton in self.teclas:
                boton.setEnabled(False)
            self._timer_teclas.start()

    def _prender_teclas(self):
        for boton in self.teclas:
            boton.setEnabled(True)

    def se_puede_cerrar_sola(self) -> bool:
        """
        El cierre forzoso de la caja y la vuelta del Admin lo pueden correr (ver
        reject): vuelve a salir después, y no cuenta como posponer.

        Salvo que abajo haya otra ventana modal a la vista que no se cierra sola
        (Compras, Administrar Kiosko, el formulario de una tarea, Vender con
        artículos): con esa abierta ellos igual tienen que esperar, así que correrlo
        no destraba nada. Y la vuelta del Admin mira cada 1 s, lo mismo que tarda el
        aviso en responder: lo corría cada vez que salía, antes de que se lo pudiera
        contestar, y cada minuto le sacaba el teclado a la ventana de abajo.
        """
        for ventana in QApplication.topLevelWidgets():
            if ventana is self or not ventana.isVisible() or not ventana.isModal():
                continue
            se_cierra_sola = getattr(ventana, "se_puede_cerrar_sola", None)
            if se_cierra_sola is None or not se_cierra_sola():
                return False
        return True

    def keyPressEvent(self, evento):
        """Ninguna tecla hace nada: ni Esc lo cierra ni Enter aprieta un botón."""
        evento.accept()

    def eventFilter(self, objeto, evento):
        if objeto in self.teclas and evento.type() in (QEvent.KeyPress, QEvent.KeyRelease):
            return True  # la barra espaciadora tampoco aprieta un botón
        return super().eventFilter(objeto, evento)

    def closeEvent(self, evento):
        """La cruz no está, pero Alt+F4 llega acá: tampoco lo cierra."""
        evento.ignore()

    def reject(self):
        """Solo lo llama el programa (Esc y la cruz no): MainWindow._hay_un_cobro_a_medias,
        para que pase el cierre forzoso o la vuelta del Admin. No graba nada."""
        if self._contestado:
            return
        self._contestado = True
        super().reject()
        self.corrida.emit()

    def cerrar_sin_contestar(self):
        """Se cerró la sesión: el aviso se va sin grabar nada y sin contar como corrido
        (el reject de QDialog, no el de acá)."""
        self._contestado = True
        QDialog.reject(self)

    def _contestar(self, accion, *argumentos):
        if self._contestado:
            return
        self._contestado = True
        # Si el repo la rechaza (ya la marcó otra, la borró el Admin) sale su cartel,
        # y el aviso se va igual: lo que quede pendiente vuelve en la próxima revisión.
        accion(*argumentos)
        self.accept()
        self.contestada.emit()

    @manejar_errores
    def _posponer(self, minutos: int):
        tareas_turno_repo.posponer(self._usuario_id, self.tarea["tarea_id"], self.tarea["dia"], minutos,
                                   ahora=self._ahora())

    @manejar_errores
    def _hecha(self):
        tareas_turno_repo.marcar_hecha(self._usuario_id, self.tarea["tarea_id"], self.tarea["dia"], ahora=self._ahora())


class RevisorDeTareas(QObject):
    """
    El reloj de las tareas de la ventana principal (`ventana`, la MainWindow del
    mostrador). Cada INTERVALO_REVISION_TAREAS_MS cuenta las atrasadas (le pasa el
    número a `al_contar`, para el botón que titila) y saca el aviso de las que
    llegaron a su hora, de a una. `ahora` es el reloj (para las pruebas). La ventana
    lo para con `detener()` al cerrarse. `contestaron` sale cada vez que contestan un
    aviso (HECHA o POSPONER): la ventana de Tareas del Turno, si está abierta, se pone
    al día ya y no recién en su repaso de los 30 s.
    """

    contestaron = Signal()

    def __init__(self, ventana, usuario, al_contar, ahora=datetime.now):
        super().__init__(ventana)
        self._ventana = ventana
        self._usuario = usuario
        self._al_contar = al_contar
        self._ahora = ahora
        self.aviso = None
        # Las que salen de a una: la tanda y cuál se está mostrando.
        self._tanda = []
        self._en_la_tanda = 0
        # Hasta cuándo no sale después de que lo corrió el cierre forzoso.
        self._corrido_hasta = None
        # Los avisos ya cerrados, hasta la próxima revisión: soltarlos dentro de su
        # propio clic borraría el botón que se está apretando.
        self._cerrados = []
        self._detenido = False
        self._timer = QTimer(self)
        self._timer.setInterval(INTERVALO_REVISION_TAREAS_MS)
        self._timer.timeout.connect(self.revisar)
        self._timer.start()
        self._timer_primera = QTimer(self)
        self._timer_primera.setSingleShot(True)
        self._timer_primera.setInterval(MILISEGUNDOS_PRIMERA_REVISION)
        self._timer_primera.timeout.connect(self.revisar)
        self._timer_primera.start()
        self.contar()

    def _que_hora_es(self) -> datetime:
        return self._ahora()

    def detener(self):
        """Se cerró la sesión: no avisa más y el aviso abierto se va."""
        self._detenido = True
        self._timer.stop()
        self._timer_primera.stop()
        if self.aviso is not None:
            self.aviso.cerrar_sin_contestar()
            self._soltar()
        self._tanda = []

    def contar(self):
        """El número del botón de la barra: cuántas de hoy llegaron a su hora sin hacerse."""
        try:
            cuantas = tareas_turno_repo.cuantas_atrasadas(self._ahora())
        except Exception as error:  # un fallo de la base no puede tirar abajo el mostrador
            registrar_error(error, "Contar las tareas del turno atrasadas")
            return
        self._al_contar(cuantas)

    def revisar(self):
        """Cada INTERVALO_REVISION_TAREAS_MS. Solo con la ventana principal abierta
        (minimizada también cuenta: para Qt sigue a la vista); una cerrada, o que
        nunca se mostró, no avisa."""
        if self._detenido or not self._ventana.isVisible():
            return
        self._cerrados.clear()
        self.contar()
        if self.aviso is not None:
            self.aviso.poner_al_dia()
        try:
            pendientes = tareas_turno_repo.tareas_para_avisar(self._ahora())
        except Exception as error:  # un fallo de la base no puede tirar abajo el mostrador
            registrar_error(error, "Revisar los avisos de las tareas del turno")
            return
        if self.aviso is not None:
            self._sumar_a_la_tanda(pendientes)
            return
        if self._corrido_hasta is not None and self._ahora() < self._corrido_hasta:
            return
        self._corrido_hasta = None
        if pendientes:
            self._tanda, self._en_la_tanda = pendientes, 0
            self._mostrar()

    def _sumar_a_la_tanda(self, pendientes):
        """Con un aviso abierto llegó la hora de otra: va al final ("1 de 3")."""
        en_la_tanda = {_clave(tarea) for tarea in self._tanda}
        nuevas = [tarea for tarea in pendientes if _clave(tarea) not in en_la_tanda]
        if nuevas:
            self._tanda.extend(nuevas)
            self.aviso.poner_numero(self._en_la_tanda + 1, len(self._tanda))

    def _mostrar(self):
        self.aviso = AvisoDeTarea(self._tanda[self._en_la_tanda], self._usuario["id"], self._que_hora_es,
                                  self._en_la_tanda + 1, len(self._tanda))
        self.aviso.contestada.connect(self._pasar_a_la_siguiente)
        self.aviso.corrida.connect(self._se_corrio)
        self.aviso.mostrar()

    def _soltar(self):
        self.aviso.deleteLater()
        self._cerrados.append(self.aviso)
        self.aviso = None

    def _pasar_a_la_siguiente(self):
        """Contestaron una: sale la siguiente de la tanda que todavía falte (con lo que
        tiene ahora: si la pospusieron, ya dice cuántas veces), o se termina."""
        self._soltar()
        self.contar()
        self.contestaron.emit()
        try:
            pendientes = tareas_turno_repo.tareas_para_avisar(self._ahora())
        except Exception as error:  # un fallo de la base no puede tirar abajo el mostrador
            registrar_error(error, "Pasar al aviso de la tarea siguiente")
            pendientes = []
        # Las que ya salieron en esta tanda no vuelven en la misma (una que no se pudo
        # grabar sale de nuevo en la próxima revisión).
        ya_salieron = {_clave(tarea) for tarea in self._tanda[:self._en_la_tanda + 1]}
        resto = [tarea for tarea in pendientes if _clave(tarea) not in ya_salieron]
        if self._detenido or not resto:
            self._tanda = []
            return
        self._tanda = self._tanda[:self._en_la_tanda + 1] + resto
        self._en_la_tanda += 1
        self._mostrar()

    def _se_corrio(self):
        """Lo corrió el cierre forzoso o la vuelta del Admin: nada se grabó, y vuelve
        a salir pasados SEGUNDOS_SIN_AVISAR_TRAS_CORRERSE (la tanda arranca de nuevo)."""
        self._soltar()
        self._tanda = []
        self._corrido_hasta = self._ahora() + timedelta(seconds=SEGUNDOS_SIN_AVISAR_TRAS_CORRERSE)
