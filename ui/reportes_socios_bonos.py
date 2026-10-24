"""
reportes_socios_bonos.py
==========================
Pestaña "PCs: Socios y Bonos" de Reportes (pedido del dueño, 2026-10-24): lo
que dejaron las PCs, separado en cargas de saldo a socios y bonos vendidos en
el mostrador, y comparado: arriba una tarjeta para cada uno (plata, qué parte
del total, cuántos, tiempo vendido y cuánto deja cada hora) con una barra que
los pone lado a lado, y abajo la tabla por período. Las cuentas son de
socios_bonos_repo.comparar; acá solo se muestran. Vive aparte de
reportes_window.py, como "PCSTREAM" y "Por Operador" (CLAUDE.md, regla 12).
"""

from PySide6.QtCore import QDate, QRectF, Qt
from PySide6.QtGui import QColor, QPainter
from PySide6.QtWidgets import (
    QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel, QTableWidgetItem, QVBoxLayout, QWidget,
)

from control_pcs.repositories import socios_bonos_repo
from ui.utils import (
    armar_filtro_por_fechas, crear_tabla, formato_pesos, formato_tiempo, hoy_del_local, manejar_errores,
    rango_de_fechas, sin_boton_por_defecto,
)

COLOR_SOCIOS = "#2F6FED"
COLOR_BONOS = "#1E9E6A"
COLUMNAS = ["Período", "Socios", "Cargas", "Bonos", "Bonos vendidos", "Total PCs", "% Socios", "% Bonos"]
_A_LA_DERECHA = (1, 2, 3, 4, 5, 6, 7)


def _porcentaje(valor: float) -> str:
    return f"{valor:.1f} %".replace(".", ",")


def _detalle(parte: dict, que: str) -> str:
    """ "40 cargas · 120h 00m · $ 1.000,00 por hora" """
    cantidad = parte["cantidad"]
    texto = f"{cantidad} {que if cantidad != 1 else que[:-1]}"
    if parte["minutos"]:
        texto += f" · {formato_tiempo(parte['minutos'] * 60)}"
    if parte["por_hora"] is not None:
        texto += f" · {formato_pesos(parte['por_hora'])} por hora"
    return texto


def texto_de_la_diferencia(total: dict) -> str:
    """La frase de abajo de la barra: quién dejó más y por cuánto."""
    socios, bonos = total["socios"]["plata"], total["bonos"]["plata"]
    if not total["total"]:
        return "No hubo ventas de PCs en estas fechas."
    if socios == bonos:
        return f"Total PCs: {formato_pesos(total['total'])}. Socios y bonos dejaron lo mismo."
    mas, menos = ("los socios", "los bonos") if socios > bonos else ("los bonos", "los socios")
    return (f"Total PCs: {formato_pesos(total['total'])}. {mas.capitalize()} dejaron "
            f"{formato_pesos(abs(socios - bonos))} más que {menos}.")


class TarjetaParte(QFrame):
    """Una de las dos tarjetas de arriba (socios o bonos)."""

    def __init__(self, titulo: str, color: str, que: str):
        super().__init__()
        self._que = que
        self.setStyleSheet(
            f"TarjetaParte {{ background: #FFFFFF; border: 1px solid #DDE3EC; border-left: 5px solid {color};"
            " border-radius: 8px; }"
        )
        rotulo = QLabel(titulo)
        rotulo.setStyleSheet("color: #6B7585; font-size: 12px; font-weight: 600; border: none;")
        self.etiqueta_plata = QLabel()
        self.etiqueta_plata.setStyleSheet(f"color: {color}; font-size: 24px; font-weight: 700; border: none;")
        self.etiqueta_porcentaje = QLabel()
        self.etiqueta_porcentaje.setStyleSheet(f"color: {color}; font-size: 16px; font-weight: 600; border: none;")
        self.etiqueta_detalle = QLabel()
        self.etiqueta_detalle.setStyleSheet("color: #3D4656; border: none;")
        fila_plata = QHBoxLayout()
        fila_plata.addWidget(self.etiqueta_plata)
        fila_plata.addStretch()
        fila_plata.addWidget(self.etiqueta_porcentaje)
        layout = QVBoxLayout()
        layout.setContentsMargins(16, 10, 16, 10)
        layout.addWidget(rotulo)
        layout.addLayout(fila_plata)
        layout.addWidget(self.etiqueta_detalle)
        self.setLayout(layout)

    def mostrar(self, parte: dict):
        self.etiqueta_plata.setText(formato_pesos(parte["plata"]))
        self.etiqueta_porcentaje.setText(_porcentaje(parte["porcentaje"]))
        self.etiqueta_detalle.setText(_detalle(parte, self._que))


class BarraComparacion(QWidget):
    """Una barra partida en dos: socios a la izquierda y bonos a la derecha, cada
    uno del largo de su parte de la plata."""

    def __init__(self):
        super().__init__()
        self.socios = 0.0
        self.bonos = 0.0
        self.setMinimumHeight(30)

    def mostrar(self, socios: float, bonos: float):
        self.socios, self.bonos = socios, bonos
        self.update()

    def paintEvent(self, _evento):
        pincel = QPainter(self)
        pincel.setRenderHint(QPainter.Antialiasing)
        caja = QRectF(self.rect()).adjusted(0.5, 0.5, -0.5, -0.5)
        pincel.setPen(Qt.NoPen)
        pincel.setBrush(QColor("#E6EAF0"))
        pincel.drawRoundedRect(caja, 6, 6)
        total = self.socios + self.bonos
        if total <= 0:
            return
        corte = caja.left() + caja.width() * self.socios / total
        for desde, hasta, color, porcentaje in (
            (caja.left(), corte, COLOR_SOCIOS, self.socios * 100 / total),
            (corte, caja.right(), COLOR_BONOS, self.bonos * 100 / total),
        ):
            if hasta - desde < 1:
                continue
            pedazo = QRectF(desde, caja.top(), hasta - desde, caja.height())
            pincel.save()
            pincel.setClipRect(pedazo)
            pincel.setBrush(QColor(color))
            pincel.drawRoundedRect(caja, 6, 6)
            pincel.restore()
            if pedazo.width() > 50:
                pincel.setPen(QColor("#FFFFFF"))
                pincel.drawText(pedazo, Qt.AlignCenter, _porcentaje(porcentaje))
                pincel.setPen(Qt.NoPen)


class PestañaSociosYBonos(QWidget):
    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_agrupar = QComboBox()
        self.combo_agrupar.addItem("Total del rango", "rango")
        self.combo_agrupar.addItem("Por Día", "dia")
        self.combo_agrupar.addItem("Por Semana", "semana")
        self.combo_agrupar.addItem("Por Turno", "turno")
        self.combo_agrupar.currentIndexChanged.connect(self._buscar)
        hoy = hoy_del_local()
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, QDate(hoy.year(), hoy.month(), 1), extras=[("Agrupar:", self.combo_agrupar)],
            solo_hoy=True, dias_del_local=True,
        )

        self.tarjeta_socios = TarjetaParte("CARGAS A SOCIOS", COLOR_SOCIOS, "cargas")
        self.tarjeta_bonos = TarjetaParte("BONOS EN EL MOSTRADOR", COLOR_BONOS, "bonos")
        tarjetas = QHBoxLayout()
        tarjetas.addWidget(self.tarjeta_socios)
        tarjetas.addWidget(self.tarjeta_bonos)
        self.barra = BarraComparacion()
        self.etiqueta_diferencia = QLabel()
        self.etiqueta_diferencia.setStyleSheet("font-weight: 600;")

        self.tabla = crear_tabla(COLUMNAS, estirar=0)
        for columna in _A_LA_DERECHA:
            self.tabla.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)

        nota = QLabel(
            "Bonos: los de walk-ins, los de PCSTREAM y lo cobrado por reservas de PCs. Socios + Bonos = "
            "\"Alquiler de PCs\" de Caja y Totales. El tiempo de los bonos es el de los que se pusieron en una "
            "PC: una reserva que no vino suma plata pero no tiempo."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(8)
        layout.addLayout(tarjetas)
        layout.addWidget(self.barra)
        layout.addWidget(self.etiqueta_diferencia)
        layout.addSpacing(6)
        layout.addWidget(self.tabla, 1)
        layout.addWidget(nota)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_fila(self, fila_datos: dict, negrita: bool = False):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        socios, bonos = fila_datos["socios"], fila_datos["bonos"]
        valores = [
            fila_datos["etiqueta"], formato_pesos(socios["plata"]), str(socios["cantidad"]),
            formato_pesos(bonos["plata"]), str(bonos["cantidad"]), formato_pesos(fila_datos["total"]),
            _porcentaje(socios["porcentaje"]), _porcentaje(bonos["porcentaje"]),
        ]
        for columna, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            if columna in _A_LA_DERECHA:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if negrita:
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
            self.tabla.setItem(fila, columna, item)

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" absorbe el índice que manda `currentIndexChanged`.
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        agrupar_por = self.combo_agrupar.currentData()
        resultado = socios_bonos_repo.comparar(desde, hasta, agrupar_por)
        total = resultado["total"]

        self.tarjeta_socios.mostrar(total["socios"])
        self.tarjeta_bonos.mostrar(total["bonos"])
        self.barra.mostrar(max(total["socios"]["plata"], 0), max(total["bonos"]["plata"], 0))
        self.etiqueta_diferencia.setText(texto_de_la_diferencia(total))

        self.tabla.setRowCount(0)
        for fila_datos in resultado["filas"]:
            self._agregar_fila(fila_datos)
        if agrupar_por != "rango" and len(resultado["filas"]) > 1:
            self._agregar_fila(total, negrita=True)
