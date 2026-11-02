"""
historial_turno_window.py
==========================
HISTORIAL DEL TURNO (pedido del dueño, 2026-11-02): todo lo cobrado en el turno
abierto, venta por venta (bonos de PC, cargas de miembros, kiosko, impresiones,
trámites, PS5, PCSTREAM y reservas), con la maqueta A que eligió el dueño (en
PROPUESTA_HISTORIAL_DEL_TURNO): la cabecera oscura con la caja y los números del
turno, un buscador, pastillas para quedarse con un rubro, la lista y la ayuda
abajo. Los datos salen de repositories/historial_turno_repo.py.

El botón va debajo del mosaico de Control de PCs, a la derecha de CONTROL DE
STOCK (ahí lo pidió el dueño). Como ese, lo ven todos pero solo el Admin lo
abre: con otro operador se ve igual y no hace nada al apretarlo. El repo vuelve
a exigir Admin.

Las anuladas salen en rojo y no suman. Solo muestra: anular sigue siendo cosa de
Consulta de Ventas o de "Quitar un bono".
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QVBoxLayout

import dominio
from repositories import historial_turno_repo
from ui import imprimir
from ui.dibujos_tabla import DelegadoEtiqueta
from ui.piezas_ventana import (
    agregar_indicador, buscador, cabecera_oscura, fila_de_filtros, panel_de_tabla, pie_de_ventana,
    poner_indicador, tecla,
)
from ui.utils import aplicar_clase, crear_tabla, formato_pesos, manejar_errores, sin_boton_por_defecto

TITULO = "Historial del Turno"
COLUMNAS = ["Hora", "Rubro", "Qué se cobró", "Pago", "Total"]
COLUMNA_RUBRO = 1
COLUMNA_DETALLE = 2
COLUMNA_PAGO = 3
COLUMNA_TOTAL = 4

# La pastilla que deja solo las anuladas (las demás filtran por rubro).
FILTRO_ANULADAS = "anuladas"
FILTROS = [
    ("Bonos de PC", historial_turno_repo.RUBRO_BONO_PC),
    ("Miembros", historial_turno_repo.RUBRO_MIEMBRO),
    ("Kiosko", historial_turno_repo.RUBRO_KIOSKO),
    ("Impresiones", historial_turno_repo.RUBRO_IMPRESIONES),
    ("Trámites", historial_turno_repo.RUBRO_TRAMITE),
    ("PS5", historial_turno_repo.RUBRO_PS5),
    ("PCSTREAM", historial_turno_repo.RUBRO_PCSTREAM),
    ("Reservas", historial_turno_repo.RUBRO_RESERVA),
    ("Anuladas", FILTRO_ANULADAS),
]
# El color de la etiqueta de cada rubro (ui/dibujos_tabla.TONOS_DE_ETIQUETA).
TONOS = {
    historial_turno_repo.RUBRO_BONO_PC: "azul",
    historial_turno_repo.RUBRO_MIEMBRO: "violeta",
    historial_turno_repo.RUBRO_KIOSKO: "verde",
    historial_turno_repo.RUBRO_IMPRESIONES: "gris",
    historial_turno_repo.RUBRO_TRAMITE: "ámbar",
    historial_turno_repo.RUBRO_PS5: "celeste",
    historial_turno_repo.RUBRO_PCSTREAM: "naranja",
    historial_turno_repo.RUBRO_RESERVA: "rosa",
    historial_turno_repo.RUBRO_OTRO: "gris",
}
ROJO = QColor("#D93A45")
PIE = ("Todo lo cobrado en el turno abierto, el mismo que suma el Cierre de Turno  ·  Las anuladas se ven en "
       "rojo y no suman  ·  \"cobró ...\": lo cobró el Admin en la caja de quien agarró el turno")


class BotonHistorialTurno(QPushButton):
    """La tecla "📋 HISTORIAL DEL TURNO" de debajo del mosaico, con el mismo relieve
    que las de al lado."""

    def __init__(self, usuario, parent=None):
        super().__init__("📋  HISTORIAL DEL TURNO", parent)
        self.usuario = usuario
        aplicar_clase(self, "barra")
        if dominio.es_admin(usuario):
            self.clicked.connect(self._abrir)

    @manejar_errores
    def _abrir(self):
        VentanaHistorialTurno(self.usuario["id"], self.window()).exec()


def detalle_de_la_cabecera(historial) -> str:
    """"Caja Nº 42 de MATI · Turno Domingo T2 · abrió a las 18:02" (sin caja,
    solo el turno)."""
    if historial["caja_numero"] is None:
        return f"Turno {historial['turno_label']} · sin caja abierta"
    return (f"Caja Nº {historial['caja_numero']} de {historial['responsable']} · "
            f"Turno {historial['turno_label']} · abrió a las {historial['abrio_a_las']}")


def texto_de_lo_visible(ventas: list) -> str:
    """"5 ventas · $ 38.700": cuántas y cuánto suman las que se ven (sin las
    anuladas)."""
    validas = [venta for venta in ventas if not venta["anulada"]]
    cantidad = "1 venta" if len(validas) == 1 else f"{len(validas)} ventas"
    return f"{cantidad} · {formato_pesos(sum(venta['total'] for venta in validas))}"


class VentanaHistorialTurno(QDialog):
    """La lista de lo cobrado en el turno, con filtros y lista para imprimir."""

    def __init__(self, usuario_id: int, parent=None):
        super().__init__(parent)
        # Si no es Admin, el repo no deja y la ventana no llega a abrirse.
        self._historial = historial_turno_repo.historial_del_turno(usuario_id)
        self._filtro = None
        self.setWindowTitle(TITULO)
        self.resize(1100, 760)
        self._armar_interfaz()
        self._llenar()

    def _armar_interfaz(self):
        historial = self._historial
        cabecera = cabecera_oscura("📋", TITULO, detalle_de_la_cabecera(historial))
        self.etiqueta = cabecera.detalle
        poner_indicador(agregar_indicador(cabecera, "Ventas"), str(historial["cantidad"]))
        poner_indicador(agregar_indicador(cabecera, "Anuladas"), str(historial["anuladas"]),
                        alerta=historial["anuladas"] > 0)
        poner_indicador(agregar_indicador(cabecera, "Total"), formato_pesos(historial["total"]))

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

        self.filtros = fila_de_filtros(FILTROS, self._elegir_filtro, todos="Todo")
        # Cuántas y cuánto suman las que se ven: al tocar "Miembros", lo cargado en el turno.
        self.etiqueta_visible = QLabel()
        self.etiqueta_visible.setObjectName("pieDeVentana")
        fila_filtros = QHBoxLayout()
        fila_filtros.addWidget(self.filtros, 1)
        fila_filtros.addWidget(self.etiqueta_visible)

        self.tabla = crear_tabla(COLUMNAS, estirar=COLUMNA_DETALLE, por_filas=True)
        etiquetas = DelegadoEtiqueta(self.tabla)
        etiquetas.colores_fijos(TONOS)
        self.tabla.setItemDelegateForColumn(COLUMNA_RUBRO, etiquetas)
        self.tabla.setColumnWidth(0, 70)
        self.tabla.setColumnWidth(COLUMNA_RUBRO, 130)
        self.tabla.setColumnWidth(COLUMNA_PAGO, 140)
        self.tabla.setColumnWidth(COLUMNA_TOTAL, 110)
        self.tabla.horizontalHeaderItem(COLUMNA_TOTAL).setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(barra_botones)
        layout.addLayout(fila_filtros)
        layout.addWidget(panel_de_tabla(self.tabla), 1)
        layout.addWidget(pie_de_ventana(PIE))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _elegir_filtro(self, valor):
        self._filtro = valor
        self._llenar()

    def ventas_visibles(self) -> list:
        """Las ventas que dejan ver la pastilla elegida y lo escrito en el buscador."""
        ventas = self._historial["ventas"]
        if self._filtro == FILTRO_ANULADAS:
            ventas = [venta for venta in ventas if venta["anulada"]]
        elif self._filtro is not None:
            ventas = [venta for venta in ventas if self._filtro in venta["rubros"]]
        buscado = dominio.sin_acentos(self.buscador.text().strip())
        if buscado:
            ventas = [venta for venta in ventas if buscado in dominio.sin_acentos(
                " ".join((venta["hora"], venta["rubro"], venta["detalle"], venta["nota"])))]
        return ventas

    @staticmethod
    def _que_se_cobro(venta) -> str:
        return venta["detalle"] + (f"   ·   {venta['nota']}" if venta["nota"] else "")

    def _llenar(self):
        ventas = self.ventas_visibles()
        self.tabla.setRowCount(len(ventas))
        for fila, venta in enumerate(ventas):
            valores = (venta["hora"], venta["rubro"], self._que_se_cobro(venta),
                       "ANULADA" if venta["anulada"] else venta["pago"], formato_pesos(venta["total"]))
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                fuente = item.font()
                if columna == COLUMNA_TOTAL:
                    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                    # Tachado si se anuló; si no, en negrita.
                    fuente.setStrikeOut(venta["anulada"])
                    fuente.setBold(not venta["anulada"])
                    item.setFont(fuente)
                if venta["anulada"] and columna != COLUMNA_RUBRO:
                    item.setForeground(ROJO)
                self.tabla.setItem(fila, columna, item)
        # Lo último que se cobró a la vista: la lista va de la primera venta a la última.
        self.tabla.scrollToBottom()
        if self._historial["ventas"]:
            self.etiqueta_visible.setText(texto_de_lo_visible(ventas))
        else:
            self.etiqueta_visible.setText("Todavía no se cobró nada en este turno.")
        self.boton_imprimir.setEnabled(bool(ventas))

    def html_para_imprimir(self, impreso=None) -> str:
        ventas = self.ventas_visibles()
        filas = [((venta["hora"], venta["rubro"], self._que_se_cobro(venta),
                   "ANULADA" if venta["anulada"] else venta["pago"], formato_pesos(venta["total"])),
                  venta["anulada"]) for venta in ventas]
        validas = [venta for venta in ventas if not venta["anulada"]]
        pie = ("", "", f"{len(validas)} ventas (sin las anuladas)", "",
               formato_pesos(sum(venta["total"] for venta in validas)))
        nombre_del_filtro = next((texto for texto, valor in FILTROS if valor == self._filtro), None)
        subtitulo = detalle_de_la_cabecera(self._historial)
        if nombre_del_filtro:
            subtitulo += f" · solo {nombre_del_filtro}"
        if self.buscador.text().strip():
            subtitulo += f" · con \"{self.buscador.text().strip()}\""
        return imprimir.html_del_listado(TITULO, subtitulo, COLUMNAS, filas,
                                         a_la_derecha=(COLUMNA_TOTAL,), pie=pie, impreso=impreso)

    def _imprimir(self):
        imprimir.vista_previa(self, self.html_para_imprimir(), TITULO)
