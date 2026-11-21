"""
historial_turno_window.py
==========================
HISTORIAL DEL TURNO (pedido del dueño, 2026-11-02, maqueta A de
PROPUESTA_HISTORIAL_DEL_TURNO): la cabecera oscura con la caja y los números del
turno, un buscador, pastillas para filtrar, la lista y la ayuda abajo. Los datos
salen de repositories/historial_turno_repo.py.

Desde el 2026-11-20 muestra TODO lo que pasó en el turno, no solo las ventas
(pedido del dueño: "absolutamente todos los movimientos de $ y de habilitación y
ventas"; maqueta A de PROPUESTA_HISTORIAL_DEL_TURNO/2_TODOS_LOS_MOVIMIENTOS): las
columnas "Qué fue", "Tiempo" y "Plata", pastillas por tipo (al tocar VENTAS
aparecen los rubros) y, cuando no pasó nada, un cartel en vez de la lista en
blanco. Y el Administrador elige el día y el turno con la barra de
ui/historial_turno_barra.py (maqueta de PROPUESTA_HISTORIAL_DEL_TURNO/
3_ELEGIR_DIA_Y_TURNO); al abrir se ve siempre el turno actual, y el operador ve
solo ese.

El botón va debajo del mosaico de Control de PCs, a la derecha de CONTROL DE
STOCK (ahí lo pidió el dueño). Lo abre cualquier operador, para revisar que no se
equivocó al cobrar (pedido del dueño, 2026-11-19; antes, solo el Admin).

Lo anulado sale en rojo y no suma. Solo muestra: anular sigue siendo cosa de
Consulta de Ventas o de "Quitar un bono".

Desde el 2026-11-21 el texto de "Qué pasó" va del mismo color que la etiqueta de
"Qué fue" de su renglón (pedido del dueño: "para que sea más fácil de leer").
"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QPushButton, QStackedWidget, QTableWidgetItem, QVBoxLayout,
)

import dominio
from repositories import historial_turno_repo as repo
from ui import imprimir
from ui.dibujos_tabla import (
    TONO_CAJA, TONO_CUENTA_PC, TONO_IMPRESIONES, TONO_KIOSKO, TONO_PCS, TONO_PCSTREAM, TONO_PLAYSTATION,
    TONO_RESERVAS, TONO_SOCIOS, TONO_TRAMITES, DelegadoEtiqueta,
)
from ui.historial_turno_barra import AvisoTurnoCerrado, BarraDeTurnos
from ui.piezas_ventana import (
    agregar_indicador, agregar_pastilla, buscador, cabecera_oscura, fila_de_filtros, panel_de_tabla,
    pie_de_ventana, poner_indicador, tecla,
)
from ui.utils import aplicar_clase, crear_tabla, formato_pesos, manejar_errores, sin_boton_por_defecto

TITULO = "Historial del Turno"
COLUMNAS = ["Hora", "Qué fue", "Qué pasó", "Pago", "Tiempo", "Plata"]
COLUMNA_HORA = 0
COLUMNA_TIPO = 1
COLUMNA_DETALLE = 2
COLUMNA_PAGO = 3
COLUMNA_TIEMPO = 4
COLUMNA_PLATA = 5

# Las pastillas de arriba: una por tipo de movimiento, y la de lo anulado.
FILTRO_ANULADAS = "anuladas"
GRUPOS = [
    ("Ventas", repo.GRUPO_VENTAS),
    ("Habilitaciones", repo.GRUPO_HABILITACIONES),
    ("Saldo de socios", repo.GRUPO_SALDO),
    ("Caja y Cuenta", repo.GRUPO_CAJA),
    ("Anuladas", FILTRO_ANULADAS),
]
# La fila que aparece al tocar VENTAS, para quedarse con un rubro.
RUBROS = [
    ("Bonos de PC", repo.RUBRO_BONO_PC),
    ("Miembros", repo.RUBRO_MIEMBRO),
    ("Kiosko", repo.RUBRO_KIOSKO),
    ("Impresiones", repo.RUBRO_IMPRESIONES),
    ("Trámites", repo.RUBRO_TRAMITE),
    ("PS5", repo.RUBRO_PS5),
    ("PCSTREAM", repo.RUBRO_PCSTREAM),
    ("Reservas", repo.RUBRO_RESERVA),
]
# El color de la etiqueta de "Qué fue": el de su rubro, el mismo en todo el
# programa (Reportes también, ver ui/dibujos_tabla.TONO_PCS...). Lo de las PCs
# en azul, la PS5 en rosa, PCSTREAM en celeste, los socios en violeta, la Cuenta
# de la PC en fucsia y la caja en pizarra.
TONOS = {
    repo.RUBRO_BONO_PC: TONO_PCS,
    repo.RUBRO_MIEMBRO: TONO_SOCIOS,
    repo.RUBRO_KIOSKO: TONO_KIOSKO,
    repo.RUBRO_IMPRESIONES: TONO_IMPRESIONES,
    repo.RUBRO_TRAMITE: TONO_TRAMITES,
    repo.RUBRO_PS5: TONO_PLAYSTATION,
    repo.RUBRO_PCSTREAM: TONO_PCSTREAM,
    repo.RUBRO_RESERVA: TONO_RESERVAS,
    repo.RUBRO_OTRO: "gris",
    repo.TIPO_PC_ABIERTA: TONO_PCS,
    repo.TIPO_MAS_TIEMPO: TONO_PCS,
    repo.TIPO_TRASLADO: TONO_PCS,
    repo.TIPO_PS5: TONO_PLAYSTATION,
    repo.TIPO_MAS_TIEMPO_PS5: TONO_PLAYSTATION,
    repo.TIPO_PCSTREAM: TONO_PCSTREAM,
    repo.TIPO_MAS_TIEMPO_PCSTREAM: TONO_PCSTREAM,
    repo.TIPO_SOCIO_ENTRO: TONO_SOCIOS,
    repo.TIPO_SALDO_A_LA_PC: TONO_SOCIOS,
    repo.TIPO_CARGA_SOCIO: TONO_SOCIOS,
    repo.TIPO_SALDO_DEVUELTO: TONO_SOCIOS,
    repo.TIPO_SALDO_QUITADO: TONO_SOCIOS,
    repo.TIPO_SALDO_IMPORTADO: TONO_SOCIOS,
    repo.TIPO_ORDENAR_SALDOS: TONO_SOCIOS,
    repo.TIPO_CAJA: TONO_CAJA,
    repo.TIPO_RELEVO: TONO_CAJA,
    repo.TIPO_CIERRE: TONO_CAJA,
    repo.TIPO_A_CUENTA: TONO_CUENTA_PC,
    repo.TIPO_CUENTA_COBRADA: TONO_CUENTA_PC,
    repo.TIPO_CUENTA_PERDIDA: TONO_CUENTA_PC,
    repo.TIPO_DEVOLUCION: TONO_RESERVAS,
}
ROJO = QColor("#D93A45")
FUCSIA = QColor("#C21C97")
NARANJA = QColor("#B4471A")
GRIS = QColor("#9AA3B2")
PIE = ("Todo lo que pasó en el turno, en orden de hora  ·  TOTAL suma solo las ventas, igual que el Cierre de "
       "Turno  ·  En rojo, lo anulado  ·  En fucsia, lo anotado a la Cuenta de la PC (entra a la caja cuando se "
       "cobra)  ·  \"cobró ...\": lo cobró el Admin en la caja de quien agarró el turno")
PIE_ADMIN = "Al abrir se ve el turno actual  ·  ◀ ▶ pasan de a un turno; la fecha abre el calendario  ·  " + PIE


class BotonHistorialTurno(QPushButton):
    """La tecla "📋 HISTORIAL DEL TURNO" de debajo del mosaico, con el mismo relieve
    que las de al lado."""

    def __init__(self, usuario, parent=None):
        super().__init__("📋  HISTORIAL DEL TURNO", parent)
        self.usuario = usuario
        aplicar_clase(self, "barra")
        self.clicked.connect(self._abrir)

    @manejar_errores
    def _abrir(self):
        VentanaHistorialTurno(self.usuario["id"], self.window()).exec()


def detalle_de_la_cabecera(historial) -> str:
    """"Caja Nº 42 de MATI · Turno Domingo T2 · abrió a las 18:02" (sin caja,
    solo el turno). De un turno cerrado, con su día y a qué hora cerró."""
    turno = f"Turno {historial['turno_label']}"
    if historial["es_el_actual"]:
        if historial["caja_numero"] is None:
            return f"{turno} · sin caja abierta"
        return f"Caja Nº {historial['caja_numero']} de {historial['responsable']} · {turno} · " \
               f"abrió a las {historial['abrio_a_las']}"
    turno += f" del {dominio.nombre_del_dia(historial['dia'])}"
    if historial["caja_numero"] is None:
        return f"Cierre de {historial['responsable']} · {turno} · cerró a las {historial['cerro_a_las']}"
    return (f"Caja Nº {historial['caja_numero']} de {historial['responsable']} · {turno} · "
            f"abrió {historial['abrio_a_las']}, cerró {historial['cerro_a_las']}")


def texto_de_lo_visible(movimientos: list) -> str:
    """"26 movimientos · 15 ventas · $ 78.100": cuántos se ven y cuánto suman las
    ventas que se ven (sin las anuladas)."""
    ventas = [m for m in movimientos if m["venta_id"] is not None and not m["anulada"]]
    cuantos = "1 movimiento" if len(movimientos) == 1 else f"{len(movimientos)} movimientos"
    cuantas = "1 venta" if len(ventas) == 1 else f"{len(ventas)} ventas"
    return f"{cuantos} · {cuantas} · {formato_pesos(sum(venta['total'] for venta in ventas))}"


def texto_de_la_plata(movimiento) -> tuple:
    """(texto, color, negrita) de la columna Plata: lo que entró a la caja en
    negrita; lo que salió, la diferencia al contar y lo perdido en naranja; lo
    anotado a la Cuenta de la PC en fucsia; "—" si no movió plata."""
    plata, clase = movimiento["plata"], movimiento["clase_plata"]
    if plata is None:
        return "—", GRIS, False
    if clase == repo.PLATA_SALE:
        return f"− {formato_pesos(plata)}", NARANJA, True
    if clase == repo.PLATA_CUENTA:
        return f"a cuenta {formato_pesos(plata)}", FUCSIA, False
    if clase == repo.PLATA_PERDIDA:
        return f"perdida {formato_pesos(plata)}", NARANJA, True
    if clase == repo.PLATA_DIFERENCIA:
        if abs(plata) < 0.005:
            return "justo", GRIS, False
        return (f"falta {formato_pesos(-plata)}" if plata < 0 else f"sobra {formato_pesos(plata)}"), NARANJA, True
    return formato_pesos(plata), None, True


def _que_paso(movimiento) -> str:
    return movimiento["detalle"] + (f"   ·   {movimiento['nota']}" if movimiento["nota"] else "")


def _pago(movimiento) -> str:
    return "ANULADA" if movimiento["anulada"] and movimiento["venta_id"] is not None else movimiento["pago"]


class VentanaHistorialTurno(QDialog):
    """Lo que pasó en el turno, con filtros y lista para imprimir. Abre en el
    turno actual; el Admin elige otro con la barra de arriba."""

    def __init__(self, usuario_id: int, parent=None):
        super().__init__(parent)
        self.usuario_id = usuario_id
        # Si el usuario ya no está habilitado, el repo no deja y la ventana no llega a abrirse.
        self._historial = repo.historial_del_turno(usuario_id)
        self._grupo = None
        self._rubro = None
        self.setWindowTitle(TITULO)
        self.resize(1180, 800)
        self._armar_interfaz()
        self._mostrar_turno()

    def _armar_interfaz(self):
        cabecera = cabecera_oscura("📋", TITULO, "")
        self.etiqueta = cabecera.detalle
        self.pastilla_cerrado = agregar_pastilla(cabecera, "TURNO CERRADO", "gris")
        self.indicador_ventas = agregar_indicador(cabecera, "Ventas")
        self.indicador_pcs = agregar_indicador(cabecera, "PCs abiertas")
        self.indicador_anuladas = agregar_indicador(cabecera, "Anuladas")
        self.indicador_total = agregar_indicador(cabecera, "Total")

        # La barra para elegir día y turno, solo para quien puede mirar otros (el Admin).
        self.barra = None
        if self._historial["puede_mirar_otros"]:
            self.barra = BarraDeTurnos(self.usuario_id)
            self.barra.eligieron.connect(self._ir_a)
            self.barra.anterior.connect(lambda: self._ir_a(self._historial["anterior"]))
            self.barra.siguiente.connect(lambda: self._ir_a(self._historial["siguiente"]))
        self.aviso = AvisoTurnoCerrado(lambda: self._ir_a(None))

        self.buscador = buscador("Buscar en el turno: PC, socio, artículo...")
        self.buscador.setMinimumWidth(380)
        self.buscador.textChanged.connect(lambda _texto: self._llenar())
        self.boton_imprimir = tecla("🖨  IMPRIMIR", self._imprimir, "teclaAzul")
        self.boton_imprimir.setToolTip("Abre la vista previa para imprimir la lista tal cual se ve (o guardarla en PDF).")
        barra_botones = QHBoxLayout()
        barra_botones.setSpacing(8)
        barra_botones.addWidget(self.buscador)
        barra_botones.addStretch()
        barra_botones.addWidget(self.boton_imprimir)
        barra_botones.addWidget(tecla("CERRAR", self.close))

        self.filtros = fila_de_filtros(GRUPOS, self._elegir_grupo, todos="Todo")
        # Cuántos se ven y cuánto suman las ventas que se ven: al tocar "Miembros", lo cargado en el turno.
        self.etiqueta_visible = QLabel()
        self.etiqueta_visible.setObjectName("pieDeVentana")
        fila_filtros = QHBoxLayout()
        fila_filtros.addWidget(self.filtros, 1)
        fila_filtros.addWidget(self.etiqueta_visible)
        self.filtros_rubros = fila_de_filtros(RUBROS, self._elegir_rubro, todos="Todos los rubros")
        self.filtros_rubros.hide()

        self.tabla = crear_tabla(COLUMNAS, estirar=COLUMNA_DETALLE, por_filas=True)
        self.etiquetas = DelegadoEtiqueta(self.tabla)
        self.etiquetas.colores_fijos(TONOS)
        self.tabla.setItemDelegateForColumn(COLUMNA_TIPO, self.etiquetas)
        for columna, ancho in ((COLUMNA_HORA, 62), (COLUMNA_TIPO, 160), (COLUMNA_PAGO, 130),
                               (COLUMNA_TIEMPO, 150), (COLUMNA_PLATA, 135)):
            self.tabla.setColumnWidth(columna, ancho)
        self.tabla.horizontalHeaderItem(COLUMNA_PLATA).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.paginas = QStackedWidget()
        self.paginas.addWidget(panel_de_tabla(self.tabla, alto_de_renglon=34))
        self.paginas.addWidget(self._armar_vacio())

        self.pie = pie_de_ventana(PIE_ADMIN if self.barra is not None else PIE)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        if self.barra is not None:
            layout.addWidget(self.barra)
        layout.addWidget(self.aviso)
        layout.addLayout(barra_botones)
        layout.addLayout(fila_filtros)
        layout.addWidget(self.filtros_rubros)
        layout.addWidget(self.paginas, 1)
        layout.addWidget(self.pie)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _armar_vacio(self) -> QFrame:
        """El cartel de cuando no pasó nada, en vez de la lista en blanco."""
        panel = QFrame()
        panel.setObjectName("historialVacio")
        capa = QVBoxLayout(panel)
        capa.addStretch()
        icono = QLabel("📋")
        icono.setStyleSheet("font-size: 34pt;")
        self.titulo_vacio = QLabel()
        self.titulo_vacio.setObjectName("tituloHistorialVacio")
        self.detalle_vacio = QLabel()
        self.detalle_vacio.setObjectName("detalleHistorialVacio")
        for etiqueta in (icono, self.titulo_vacio, self.detalle_vacio):
            etiqueta.setAlignment(Qt.AlignCenter)
            capa.addWidget(etiqueta)
        capa.addStretch()
        return panel

    @manejar_errores
    def _ir_a(self, cierre_id):
        """Muestra el turno de `cierre_id` (None: el actual). Lo pide el repo de
        nuevo: si se le sacó el Admin a quien la tiene abierta, ya no deja."""
        self._historial = repo.historial_del_turno(self.usuario_id, cierre_id)
        self._mostrar_turno()

    def _mostrar_turno(self):
        historial = self._historial
        self.etiqueta.setText(detalle_de_la_cabecera(historial))
        self.pastilla_cerrado.setVisible(not historial["es_el_actual"])
        poner_indicador(self.indicador_ventas, str(historial["cantidad"]))
        poner_indicador(self.indicador_pcs, str(historial["pcs_abiertas"]))
        poner_indicador(self.indicador_anuladas, str(historial["anuladas"]), alerta=historial["anuladas"] > 0)
        poner_indicador(self.indicador_total, formato_pesos(historial["total"]))
        self.aviso.setVisible(not historial["es_el_actual"])
        if self.barra is not None:
            self.barra.mostrar(historial["dia"], historial["cierre_id"], historial["anterior"] is not None,
                               not historial["es_el_actual"])
        if historial["movimientos"]:
            self.paginas.setCurrentIndex(0)
        else:
            self._poner_cartel_vacio()
            self.paginas.setCurrentIndex(1)
        self._llenar()

    def _poner_cartel_vacio(self):
        historial = self._historial
        if not historial["es_el_actual"]:
            self.titulo_vacio.setText("En este turno no hubo movimientos")
            self.detalle_vacio.setText("")
            return
        self.titulo_vacio.setText("No hubo movimientos desde el último Cierre de Turno")
        if historial["desde"] is None:
            ultimo = "Todavía no hubo ningún Cierre de Turno."
        else:
            cuando = datetime.fromisoformat(historial["desde"])
            ultimo = f"El último cierre fue el {dominio.nombre_del_dia(cuando.date())} a las {cuando:%H:%M}."
        self.detalle_vacio.setText(f"{ultimo}\nCuando alguien abra una caja, venda algo o habilite una PC, "
                                   "aparece acá.")

    def _elegir_grupo(self, valor):
        self._grupo = valor
        # Los rubros son de las ventas: con otra pastilla, se van y dejan de filtrar.
        self.filtros_rubros.setVisible(valor == repo.GRUPO_VENTAS)
        if valor != repo.GRUPO_VENTAS:
            self.filtros_rubros.pastillas[0].setChecked(True)
            self._rubro = None
        self._llenar()

    def _elegir_rubro(self, valor):
        self._rubro = valor
        self._llenar()

    def movimientos_visibles(self) -> list:
        """Los movimientos que dejan ver las pastillas elegidas y lo escrito en el buscador."""
        movimientos = self._historial["movimientos"]
        if self._grupo == FILTRO_ANULADAS:
            movimientos = [m for m in movimientos if m["anulada"]]
        elif self._grupo is not None:
            movimientos = [m for m in movimientos if self._grupo in m["grupos"]]
        if self._grupo == repo.GRUPO_VENTAS and self._rubro is not None:
            movimientos = [m for m in movimientos if self._rubro in m["rubros"]]
        buscado = dominio.sin_acentos(self.buscador.text().strip())
        if buscado:
            movimientos = [m for m in movimientos if buscado in dominio.sin_acentos(
                " ".join((m["hora"], m["tipo"], m["detalle"], m["nota"])))]
        return movimientos

    def _llenar(self):
        movimientos = self.movimientos_visibles()
        self.tabla.setRowCount(len(movimientos))
        for fila, movimiento in enumerate(movimientos):
            anulada = movimiento["anulada"]
            rojo = ROJO if anulada else None
            pago = _pago(movimiento)
            texto_plata, color_plata, negrita = texto_de_la_plata(movimiento)
            if anulada:
                color_plata, negrita = ROJO, False
            # "Qué pasó" con la letra de su etiqueta de "Qué fue" (pedido del dueño,
            # 2026-11-21: "para que sea más fácil de leer"); lo anulado sigue en rojo.
            color_de_lo_que_paso = rojo or QColor(self.etiquetas.colores_de(movimiento["tipo"])[0])
            celdas = (
                (movimiento["hora"], rojo, False, False),
                (movimiento["tipo"], None, False, False),
                (_que_paso(movimiento), color_de_lo_que_paso, False, False),
                (pago, rojo or (FUCSIA if pago == repo.PAGO_A_CUENTA
                                else (GRIS if pago == repo.SIN_PAGO else None)), False, False),
                (movimiento["tiempo"] or "—", rojo or (None if movimiento["tiempo"] else GRIS), False, anulada),
                (texto_plata, color_plata, negrita, anulada),
            )
            for columna, (texto, color, en_negrita, tachado) in enumerate(celdas):
                item = QTableWidgetItem(texto)
                fuente = item.font()
                fuente.setBold(en_negrita)
                fuente.setStrikeOut(tachado)
                item.setFont(fuente)
                if color is not None:
                    item.setForeground(color)
                if columna == COLUMNA_PLATA:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.tabla.setItem(fila, columna, item)
        # En el turno actual, lo último a la vista: la lista va del primer movimiento al último.
        if self._historial["es_el_actual"]:
            self.tabla.scrollToBottom()
        else:
            self.tabla.scrollToTop()
        self.etiqueta_visible.setText(texto_de_lo_visible(movimientos) if self._historial["movimientos"] else "")
        self.boton_imprimir.setEnabled(bool(movimientos))

    def html_para_imprimir(self, impreso=None) -> str:
        movimientos = self.movimientos_visibles()
        filas = [((m["hora"], m["tipo"], _que_paso(m), _pago(m), m["tiempo"] or "—", texto_de_la_plata(m)[0]),
                  m["anulada"]) for m in movimientos]
        ventas = [m for m in movimientos if m["venta_id"] is not None and not m["anulada"]]
        pie = ("", "", f"{len(ventas)} ventas (sin las anuladas)", "", "",
               formato_pesos(sum(venta["total"] for venta in ventas)))
        subtitulo = detalle_de_la_cabecera(self._historial)
        nombre_del_grupo = next((texto for texto, valor in GRUPOS if valor == self._grupo), None)
        if nombre_del_grupo:
            subtitulo += f" · solo {nombre_del_grupo}"
        nombre_del_rubro = next((texto for texto, valor in RUBROS if valor == self._rubro), None)
        if self._grupo == repo.GRUPO_VENTAS and nombre_del_rubro:
            subtitulo += f" de {nombre_del_rubro}"
        if self.buscador.text().strip():
            subtitulo += f" · con \"{self.buscador.text().strip()}\""
        return imprimir.html_del_listado(TITULO, subtitulo, COLUMNAS, filas,
                                         a_la_derecha=(COLUMNA_PLATA,), pie=pie, impreso=impreso)

    def _imprimir(self):
        imprimir.vista_previa(self, self.html_para_imprimir(), TITULO)
