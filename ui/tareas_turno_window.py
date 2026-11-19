"""
tareas_turno_window.py
=======================
TAREAS DEL TURNO (pedido del dueño, 2026-11-03, con la maqueta que vio ese día;
traída tal cual de FR Kiosko el 2026-11-19): el botón ⏰ TAREAS DEL TURNO de debajo
del mosaico, a la derecha de HISTORIAL DEL TURNO. Cosas
para hacer a una hora, como "PRENDER LAS LUCES DE AFUERA" a las 19:30. A la hora
sale el aviso de ui/aviso_tarea.py encima de todo; esta ventana es para verlas,
marcarlas y cargarlas. Las reglas, en repositories/tareas_turno_repo.py.

- Arriba, el turno y el día del local ("Tarde · lunes 03/11") y cuántas hay PARA
  HACER, ATRASADAS (en rojo si hay) y HECHAS.
- + NUEVA TAREA, MODIFICAR y BORRAR: solo el Administrador, con el borde punteado.
  A los demás les dicen "Acceso Restringido" al apretarlas; el repo lo vuelve a
  exigir al guardar.
- Pastillas: ESTE TURNO (arranca acá; con las atrasadas de un turno anterior de hoy,
  que siguen avisando), TODO EL DÍA y TODAS LAS TAREAS (lo cargado, con cuándo se
  repite: así el Admin modifica o borra una que hoy no toca).
- La grilla, en el orden del turno (la Noche va de 22 a 06: las 02:00 después de las
  23:00), con la tecla HECHA en cada renglón que falta (pregunta antes).
- HISTORIAL: los días que ya terminaron (ui/tareas_turno_dialogos.py).

Solo en el mostrador (MainWindow._abrir_tareas_turno): ninguna de sus funciones
está en admin_remoto/lista_blanca.py.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QTableWidgetItem, QVBoxLayout

import dominio
import turnos
from errores import registrar_error
from repositories import tareas_turno_repo
from ui.piezas_ventana import (
    agregar_indicador, cabecera_oscura, fila_de_filtros, solo_para_el_admin, panel_de_tabla, pie_de_ventana,
    poner_indicador, tecla, tecla_de_renglon,
)
from ui.tareas_turno_dialogos import (
    COLOR_APAGADO, COLOR_ATRASADA, COLOR_HECHA, COLOR_MAS_TARDE, COLOR_PRONTO, DialogoHistorialTareas, DialogoTarea,
    hora_de, texto_hecha,
)
from ui.utils import confirmar, crear_tabla, manejar_errores, mostrar_aviso, sin_boton_por_defecto

TITULO = "Tareas del Turno"
# Las pastillas: la primera de fila_de_filtros vale None.
FILTRO_ESTE_TURNO = None
FILTRO_TODO_EL_DIA = "TODO EL DÍA"
FILTRO_TODAS = "TODAS LAS TAREAS"
COLUMNAS = ["Hora", "Tarea", "Estado", ""]
COLUMNA_HORA = 0
COLUMNA_TAREA = 1
COLUMNA_ESTADO = 2
COLUMNA_HECHA = 3
# Con TODAS LAS TAREAS, la tercera columna dice cuándo se repite cada una.
TITULO_SE_REPITE = "Se repite"
TEXTO_HECHA = "✔  HECHA"
# Renglones altos con la tecla adentro.
ALTO_RENGLON = 58
ALTO_TECLA_RENGLON = 44
ANCHO_COLUMNA_HORA = 90
ANCHO_COLUMNA_ESTADO = 330
ANCHO_COLUMNA_HECHA = 160
# La lista se pone al día sola ("EN 18 MIN" pasa a "ATRASADA") mientras está
# abierta; lo que se contesta en el aviso, en el acto (RevisorDeTareas.contestaron,
# conectado en MainWindow._abrir_tareas_turno).
MILISEGUNDOS_ENTRE_REPASOS = 30_000


def _id_de(fila) -> int:
    """El número de la tarea de un renglón: una aparición del día trae `tarea_id`;
    una tarea cargada (TODAS LAS TAREAS), `id`."""
    return fila["tarea_id"] if "tarea_id" in fila else fila["id"]


def estado_en_texto(tarea, ahora: datetime) -> tuple:
    """(texto, color) de la columna Estado: "HECHA · Carla 19:42" en verde,
    "ATRASADA · 1 h 12 min" en rojo, "EN 18 MIN" en ámbar o "MÁS TARDE" en gris."""
    estado = tarea["estado"]
    if estado == dominio.TAREA_HECHA:
        return texto_hecha(tarea), COLOR_HECHA
    if estado == dominio.TAREA_ATRASADA:
        atraso = tarea["minutos_de_atraso"]
        texto = f"{dominio.TAREA_ATRASADA} · {dominio.texto_minutos(atraso)}" if atraso else "ES LA HORA"
        # Que se sepa por qué no está saltando el aviso.
        if tarea["pospuesta_hasta"] and tarea["pospuesta_hasta"] > ahora.isoformat(timespec="seconds"):
            texto += f" · pospuesta hasta las {hora_de(tarea['pospuesta_hasta'])}"
        return texto, COLOR_ATRASADA
    if estado == dominio.TAREA_PRONTO:
        return f"EN {dominio.texto_minutos(tarea['minutos_que_faltan']).upper()}", COLOR_PRONTO
    if estado == dominio.TAREA_NO_SE_HIZO:
        return dominio.TAREA_NO_SE_HIZO, COLOR_ATRASADA
    return dominio.TAREA_MAS_TARDE, COLOR_MAS_TARDE


class VentanaTareasTurno(QDialog):
    """Las tareas de hoy y las cargadas. `ahora` es el reloj (para las pruebas)."""

    def __init__(self, usuario, parent=None, ahora=datetime.now):
        super().__init__(parent)
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        self._ahora = ahora
        # Lo que muestra cada renglón, en orden: apariciones del día o tareas cargadas.
        self._filas = []
        self.setWindowTitle(TITULO)
        self.resize(1150, 700)
        self._armar_interfaz()
        self._cargar()
        self._timer = QTimer(self)
        self._timer.setInterval(MILISEGUNDOS_ENTRE_REPASOS)
        self._timer.timeout.connect(self._repasar)
        self._timer.start()

    def se_puede_cerrar_sola(self) -> bool:
        """Solo es una lista: el cierre forzoso de la caja la puede cerrar (lo que se
        marcó o se cargó ya está guardado)."""
        return True

    def _armar_interfaz(self):
        self.cabecera = cabecera_oscura("⏰", TITULO)
        self.indicador_para_hacer = agregar_indicador(self.cabecera, "Para hacer")
        self.indicador_atrasadas = agregar_indicador(self.cabecera, "Atrasadas")
        self.indicador_hechas = agregar_indicador(self.cabecera, "Hechas")

        self.boton_historial = tecla("📋  HISTORIAL", self._ver_historial)
        self.boton_historial.setToolTip("Los días anteriores: quién hizo cada tarea y a qué hora.")
        barra_botones = QHBoxLayout()
        barra_botones.setSpacing(8)
        # Las del Admin, solo para el Admin. Hasta el 2026-11-04 a los demás ni les
        # aparecían; ahora las ven igual y les dicen "Acceso Restringido" (pedido del dueño).
        self.boton_nueva = tecla("+  NUEVA TAREA", self._nueva, "teclaAzul")
        self.boton_modificar = tecla("✎  MODIFICAR", self._modificar)
        self.boton_borrar = tecla("BORRAR", self._borrar, "teclaRoja")
        for boton in (self.boton_nueva, self.boton_modificar, self.boton_borrar):
            solo_para_el_admin(boton, self.es_admin)
            barra_botones.addWidget(boton)
        barra_botones.addWidget(self.boton_historial)
        barra_botones.addStretch()
        barra_botones.addWidget(tecla("CERRAR", self.close, "teclaRoja"))

        self.filtros = fila_de_filtros([FILTRO_TODO_EL_DIA, FILTRO_TODAS], lambda _valor: self._cargar(),
                                       todos="ESTE TURNO")

        self.tabla = crear_tabla(COLUMNAS, estirar=COLUMNA_TAREA, por_filas=True, una_sola=True)
        for columna, ancho in ((COLUMNA_HORA, ANCHO_COLUMNA_HORA), (COLUMNA_ESTADO, ANCHO_COLUMNA_ESTADO),
                               (COLUMNA_HECHA, ANCHO_COLUMNA_HECHA)):
            self.tabla.setColumnWidth(columna, ancho)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(10)
        layout.addWidget(self.cabecera)
        layout.addLayout(barra_botones)
        layout.addWidget(self.filtros)
        layout.addWidget(panel_de_tabla(self.tabla, ALTO_RENGLON), 1)
        layout.addWidget(pie_de_ventana(
            "A la hora de cada tarea sale un aviso encima de todo, hasta que alguien pone TAREA HECHA  ·  "
            "HECHA en la lista también la marca (pregunta antes)"))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    # -----------------------------------------------------------------
    # La lista
    # -----------------------------------------------------------------

    @manejar_errores
    def _cargar(self, marcar_id=None):
        """Vuelve a leer todo. Con `marcar_id`, deja elegido el renglón de esa tarea."""
        self._leer_y_llenar(marcar_id)

    def _repasar(self):
        """Cada MILISEGUNDOS_ENTRE_REPASOS, con la ventana a la vista: la lista al día
        sin perder el renglón elegido. Sin cartel si falla (saldría cada 30 s): queda
        en el log y se vuelve a probar."""
        if not self.isVisible():
            return
        try:
            self._leer_y_llenar(self._id_elegido())
        except Exception as error:
            registrar_error(error, "Poner al día Tareas del Turno")

    def _leer_y_llenar(self, marcar_id):
        ahora = self._ahora()
        hoy = turnos.dia_en_que_empezo_el_turno(ahora)
        turno = turnos.calcular_turno(ahora)
        self.cabecera.detalle.setText(f"{turnos.etiqueta_turno(hoy, turno)} · {dominio.nombre_del_dia(hoy)}")
        del_dia = tareas_turno_repo.tareas_del_dia(None, ahora)
        filtro = self.filtros.elegido()
        if filtro == FILTRO_ESTE_TURNO:
            # Más las ATRASADAS de un turno anterior de hoy: siguen avisando y el
            # botón de la barra las cuenta, así que tienen que estar donde la que
            # entra las viene a buscar (y ATRASADAS dice lo mismo que el botón).
            del_dia = [tarea for tarea in del_dia
                       if tarea["turno"] == turno or tarea["estado"] == dominio.TAREA_ATRASADA]
        # Los números, de lo que se ve (con TODAS LAS TAREAS, de todo el día).
        numeros = dominio.numeros_de_las_tareas(del_dia)
        poner_indicador(self.indicador_para_hacer, str(numeros["para_hacer"]))
        poner_indicador(self.indicador_atrasadas, str(numeros["atrasadas"]), alerta=numeros["atrasadas"] > 0)
        poner_indicador(self.indicador_hechas, str(numeros["hechas"]))
        # Desde cero: un renglón que pasó a HECHA no puede quedarse con su tecla.
        self.tabla.setRowCount(0)
        if filtro == FILTRO_TODAS:
            self._filas = tareas_turno_repo.listar_tareas(ahora)
            self._llenar_con_las_cargadas()
        else:
            self._filas = del_dia
            self._llenar_con_las_del_dia(ahora)
        self.tabla.clearSelection()
        for fila, tarea in enumerate(self._filas):
            if _id_de(tarea) == marcar_id:
                self.tabla.selectRow(fila)
                return True
        # Sin celda actual: si no, la primera se dibuja con el recuadro del foco.
        self.tabla.setCurrentCell(-1, -1)
        return False

    def _llenar_con_las_del_dia(self, ahora):
        self.tabla.horizontalHeaderItem(COLUMNA_ESTADO).setText(COLUMNAS[COLUMNA_ESTADO])
        self.tabla.setRowCount(len(self._filas))
        for fila, tarea in enumerate(self._filas):
            hecha = tarea["estado"] == dominio.TAREA_HECHA
            celdas = [QTableWidgetItem(tarea["hora"]), QTableWidgetItem(tarea["texto"])]
            texto, color = estado_en_texto(tarea, ahora)
            estado = QTableWidgetItem(texto)
            estado.setForeground(QColor(color))
            fuente = estado.font()
            fuente.setBold(True)
            estado.setFont(fuente)
            for celda in celdas:
                fuente = celda.font()
                if hecha:
                    # Hecha: apagada y tachada, para que se lea lo que falta.
                    fuente.setStrikeOut(True)
                    celda.setForeground(QColor(COLOR_APAGADO))
                else:
                    fuente.setBold(True)
                celda.setFont(fuente)
            for columna, celda in enumerate(celdas + [estado]):
                self.tabla.setItem(fila, columna, celda)
            if not hecha:
                self.tabla.setCellWidget(fila, COLUMNA_HECHA, tecla_de_renglon(
                    TEXTO_HECHA, lambda _=False, t=tarea: self._marcar_hecha(t), "teclaVerde", ALTO_TECLA_RENGLON))

    def _llenar_con_las_cargadas(self):
        """TODAS LAS TAREAS: lo cargado, con cuándo se repite y sin la tecla HECHA."""
        self.tabla.horizontalHeaderItem(COLUMNA_ESTADO).setText(TITULO_SE_REPITE)
        self.tabla.setRowCount(len(self._filas))
        for fila, tarea in enumerate(self._filas):
            for columna, texto in enumerate((tarea["hora"], tarea["texto"], tarea["se_repite"])):
                self.tabla.setItem(fila, columna, QTableWidgetItem(texto))

    def _id_elegido(self):
        fila = self.tabla.currentRow()
        if fila < 0 or fila >= len(self._filas) or not self.tabla.selectionModel().hasSelection():
            return None
        return _id_de(self._filas[fila])

    def _elegida(self, para: str):
        """La tarea del renglón marcado, o None (con el aviso de que falta elegirla)."""
        if self._id_elegido() is None:
            mostrar_aviso(self, "Elegí una tarea", f"Marcá en la lista la tarea que querés {para}.")
            return None
        return self._filas[self.tabla.currentRow()]

    # -----------------------------------------------------------------
    # HECHA (cualquiera) y lo del Administrador
    # -----------------------------------------------------------------

    @manejar_errores
    def _marcar_hecha(self, tarea):
        if not confirmar(self, "Tarea hecha",
                         f"¿Ya está hecha?\n\n{tarea['texto']} ({tarea['hora']})\n\n"
                         "Queda anotada a tu nombre, con la hora, y deja de avisar por hoy."):
            return
        try:
            tareas_turno_repo.marcar_hecha(self.usuario["id"], tarea["tarea_id"], tarea["dia"], ahora=self._ahora())
        finally:
            # También si no se pudo (ya la había marcado otra): que se vea cómo quedó.
            self._leer_y_llenar(None)

    @manejar_errores
    def _nueva(self):
        dialogo = DialogoTarea(self.usuario, None, self, self._ahora)
        if dialogo.exec():
            self._mostrar_la_guardada(dialogo.tarea_id)

    def _mostrar_la_guardada(self, tarea_id):
        """La que se acaba de guardar, marcada. Si en este filtro no se ve (es de otro
        turno, o de un día que hoy no toca), pasa a TODAS LAS TAREAS: que se vea que
        quedó cargada."""
        if not self._leer_y_llenar(tarea_id) and self.filtros.elegido() != FILTRO_TODAS:
            next(p for p in self.filtros.pastillas if p.text() == FILTRO_TODAS).setChecked(True)
            self._leer_y_llenar(tarea_id)

    @manejar_errores
    def _modificar(self):
        elegida = self._elegida("modificar")
        if elegida is None:
            return
        # Con cómo está cargada (los días elegidos), no como se ve en un día.
        tarea = next((t for t in tareas_turno_repo.listar_tareas(self._ahora()) if t["id"] == _id_de(elegida)), None)
        if tarea is None:
            mostrar_aviso(self, "No se puede modificar",
                          f'"{elegida["texto"]}" ya no está cargada (la borraron, o era de un solo día que ya pasó).')
            return
        dialogo = DialogoTarea(self.usuario, tarea, self, self._ahora)
        if dialogo.exec():
            self._mostrar_la_guardada(dialogo.tarea_id)

    @manejar_errores
    def _borrar(self):
        tarea = self._elegida("borrar")
        if tarea is None:
            return
        if not confirmar(self, "Borrar tarea",
                         f"¿Borrar {tarea['texto']} ({tarea['hora']})?\n\n"
                         "Deja de avisar y sale de la lista. Lo que ya se hizo sigue en el historial."):
            return
        tareas_turno_repo.borrar_tarea(self.usuario["id"], _id_de(tarea), ahora=self._ahora())
        self._leer_y_llenar(None)

    @manejar_errores
    def _ver_historial(self):
        DialogoHistorialTareas(self, self._ahora).exec()
