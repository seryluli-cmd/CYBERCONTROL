"""
tarjeta_cierre.py
==================
El resumen de un Cierre de Turno tal como lo ve la empleada al cerrar: Cambio
Fijo, Efectivo y Digital, cada negocio con su "ef. + dig.", y TOTAL | A RETIRAR
EN EFECTIVO en la última línea (diseño aprobado por el dueño el 2026-10-20).

Lo dibujan dos pantallas con la MISMA tarjeta:
- CierreTurnoWindow (ui/caja_window.py): el turno en curso, antes de cerrarlo.
- DialogoDetalleCierre (ui/control_cierres_window.py): cualquier cierre ya
  hecho, común, forzoso o en ausencia (pedido del dueño, 2026-10-20: el cierre
  forzoso lo hace el programa solo y nadie veía este resumen; quiere verlo
  "como si fuera un cierre común").
Por eso vive acá y no en una de las dos: un cambio de diseño del Cierre de
Turno se ve también en Control de Cierres sin tocar nada más.

También están acá las piezas que comparte con la pantalla Caja (CajaWindow),
que tiene los mismos renglones pero otra última línea.
"""

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

import dominio
from ui.utils import formato_pesos

# La nota de abajo de la tarjeta en el Cierre de Turno de todos los días.
NOTA_AL_CERRAR = (
    "Retirá el efectivo indicado y guardalo en el sobre. Dejá el cambio "
    "fijo en el cajón para que arranque el próximo turno."
)


def texto_desglose(efectivo: float, digital: float) -> str:
    """"$X ef. + $Y dig." -- una sola línea para mostrar el desglose de un
    origen (Kiosko, Alquiler de PCs o PlayStation 5) sin ocupar dos etiquetas
    por cada uno."""
    return f"{formato_pesos(efectivo)} ef. + {formato_pesos(digital)} dig."


def mostrar_desglose_por_negocio(pantalla, resumen):
    """Los renglones de cada negocio, iguales en Caja y en Cierre de Turno:
    Kiosko (sin impresiones ni trámites), Impresiones, Trámites, Alquiler de
    PCs y PlayStation 5, cada uno con su efectivo y digital (ver
    turnos_repo.resumen_turno_actual)."""
    pantalla.valor_kiosko.setText(texto_desglose(resumen["kiosko_solo_efectivo"], resumen["kiosko_solo_digital"]))
    pantalla.valor_impresiones.setText(
        texto_desglose(resumen["impresiones_efectivo"], resumen["impresiones_digital"])
    )
    pantalla.valor_tramites.setText(texto_desglose(resumen["tramites_efectivo"], resumen["tramites_digital"]))
    pantalla.valor_pcs.setText(texto_desglose(resumen["pcs_efectivo"], resumen["pcs_digital"]))
    pantalla.valor_playstation.setText(
        texto_desglose(resumen["playstation_efectivo"], resumen["playstation_digital"])
    )


def titulo_de_la_caja(resumen) -> str:
    """"Caja Nº 12 de Lucía · " si el resumen es de una caja (ver
    turnos_repo.resumen_turno_actual); si no, nada."""
    if resumen["caja_numero"] is None:
        return ""
    return f"Caja Nº {resumen['caja_numero']} de {resumen['responsable']} · "


def etiqueta_dato(titulo, valor_texto, destacado=False, color_titulo=None, color_valor=None, negrita_titulo=False):
    """Un dato de las pantallas de caja: título gris arriba y valor grande
    abajo (en azul si `destacado`, como el TOTAL). `color_titulo`/
    `color_valor` pintan cada etiqueta aparte y `negrita_titulo` pone el
    título en negrita (ej. la Caja Actual: título negro y negrita, valor
    verde -- pedido del dueño). Devuelve (layout, etiqueta_del_valor) para
    poder actualizarla."""
    contenedor = QVBoxLayout()
    titulo_lbl = QLabel(titulo)
    valor_lbl = QLabel(valor_texto)
    fuente_valor = QFont()
    fuente_valor.setPointSize(14)
    fuente_valor.setBold(True)
    valor_lbl.setFont(fuente_valor)
    if negrita_titulo:
        fuente_titulo = QFont()
        fuente_titulo.setBold(True)
        titulo_lbl.setFont(fuente_titulo)
    titulo_lbl.setStyleSheet(f"color: {color_titulo or '#6B7585'};")
    if color_valor:
        valor_lbl.setStyleSheet(f"color: {color_valor};")
    elif destacado:
        valor_lbl.setStyleSheet("color: #2F6FED;")
    contenedor.addWidget(titulo_lbl)
    contenedor.addWidget(valor_lbl)
    return contenedor, valor_lbl


def armar_filas(layout, filas_de_datos):
    """Agrega a `layout` los datos de a dos por fila (pares de layouts hechos
    con `etiqueta_dato`): la grilla de Caja y de Cierre de Turno."""
    for izquierda, derecha in filas_de_datos:
        fila = QHBoxLayout()
        fila.addLayout(izquierda)
        fila.addLayout(derecha)
        layout.addLayout(fila)


class TarjetaCierreDeTurno(QWidget):
    """El resumen de un Cierre de Turno (ver el comentario del módulo): título
    centrado, los datos de a dos por fila y una nota abajo. No tiene botones:
    los pone cada pantalla."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._armar_interfaz()

    def _armar_interfaz(self):
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.titulo.setAlignment(Qt.AlignCenter)

        # "Cambio Fijo" es como lo llama el dueño en esta pantalla (es lo que las
        # empleadas le mandan como resumen del turno); por dentro sigue siendo el
        # "fondo de cambio" (`fondo_cambio`).
        layout_fondo, self.valor_fondo = etiqueta_dato("Cambio Fijo", "")
        layout_efectivo, self.valor_efectivo = etiqueta_dato("Efectivo", "")
        layout_digital, self.valor_digital = etiqueta_dato("Digital", "")
        # Efectivo + Digital de todo lo cobrado (Kiosko, Impresiones, Trámites,
        # PCs y PlayStation 5).
        # El título dice qué suma (efectivo + digital, sin el Cambio Fijo) y va en negrita
        # negra como "A RETIRAR EN EFECTIVO"; el monto sigue azul (pedido del dueño, 2026-10-20).
        layout_total, self.valor_total = etiqueta_dato(
            "TOTAL (EFECTIVO + DIGITAL)", "", destacado=True, color_titulo="#000000", negrita_titulo=True,
        )
        # Lo que la empleada guarda en el sobre: título negro en negrita y monto verde,
        # igual que la Caja Actual de la pantalla Caja (pedido del dueño, 2026-10-20).
        layout_retirar, self.valor_retirar = etiqueta_dato(
            "A RETIRAR EN EFECTIVO", "",
            color_titulo="#000000", negrita_titulo=True, color_valor="#2FB457",
        )
        layout_kiosko, self.valor_kiosko = etiqueta_dato(dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO], "")
        layout_pcs, self.valor_pcs = etiqueta_dato(dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS], "")
        layout_playstation, self.valor_playstation = etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION], ""
        )
        # La última línea (TOTAL y A RETIRAR) separada del resto: entre renglones hay ~10 px, se le
        # suman 10 (el doble, pedido del dueño 2026-10-20: quedaba muy encimada) y una línea de texto
        # más (~18 px, "un enter más abajo", mismo día).
        for ultima_linea in (layout_total, layout_retirar):
            ultima_linea.setContentsMargins(0, 28, 0, 0)
        # Kiosko, Impresiones y Trámites van separados, cada uno con su "ef. +
        # dig." (pedido del dueño, 2026-10-19: antes Impresiones y Trámites eran
        # renglones "incluidos en Kiosko"). Sumados dan lo que se graba como
        # Kiosko en el cierre.
        layout_impresiones, self.valor_impresiones = etiqueta_dato("Impresiones", "")
        layout_tramites, self.valor_tramites = etiqueta_dato("Trámites", "")

        self.nota = QLabel()
        self.nota.setWordWrap(True)
        self.poner_nota(NOTA_AL_CERRAR)

        layout = QVBoxLayout()
        layout.setContentsMargins(0, 0, 0, 0)
        layout.addWidget(self.titulo)
        # Efectivo y Digital en la misma línea, y el TOTAL con "A RETIRAR EN EFECTIVO" en la
        # última línea, después del desglose por negocio (pedido del dueño, 2026-10-20).
        armar_filas(layout, [
            (layout_fondo, QVBoxLayout()), (layout_efectivo, layout_digital),
            (layout_kiosko, layout_impresiones), (layout_tramites, layout_playstation),
            (layout_pcs, QVBoxLayout()),
            (layout_total, layout_retirar),
        ])
        layout.addWidget(self.nota)
        self.setLayout(layout)

    def mostrar(self, resumen):
        """Llena la tarjeta con un resumen con las claves de
        turnos_repo.resumen_turno_actual: el del turno en curso o el de un
        cierre ya hecho (control_cierres_repo.detalle_cierre()["resumen"])."""
        self.titulo.setText(f"Cierre de Turno — {titulo_de_la_caja(resumen)}{resumen['turno_actual_label']}")
        self.valor_fondo.setText(formato_pesos(resumen["cambio_inicial"]))
        self.valor_efectivo.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))
        self.valor_total.setText(formato_pesos(resumen["ventas_total"]))
        self.valor_retirar.setText(formato_pesos(resumen["ventas_efectivo"]))
        mostrar_desglose_por_negocio(self, resumen)

    def poner_nota(self, texto: str, alerta: bool = False):
        """La nota de abajo: gris en itálica, o en rojo si `alerta` (un cierre
        forzoso o en ausencia, con el mismo rojo que en la tabla de Control de
        Cierres)."""
        self.nota.setText(texto)
        if alerta:
            self.nota.setStyleSheet("color: red; font-weight: 600;")
        else:
            self.nota.setStyleSheet("color: gray; font-style: italic;")
