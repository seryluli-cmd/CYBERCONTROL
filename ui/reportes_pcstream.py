"""
reportes_pcstream.py
======================
Pestaña "PCSTREAM" de Reportes (pedido del dueño, 2026-10-17): cuánto se usa la
PC de streaming, en tiempo y en plata, entre dos fechas -- arriba los totales y
abajo día por día. Las cuentas son de pcstream_repo.uso_por_dia; acá solo se
muestran. Vive aparte de reportes_window.py, igual que "Por Operador", porque
ese archivo ya está cerca del tope de ~600 líneas (CLAUDE.md, regla 12).

La plata de PCSTREAM entra a la caja como "Alquiler de PCs" (es una PC): esta
pestaña muestra qué parte de eso fue PCSTREAM, no es plata aparte.
"""

from datetime import date

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QLabel, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt, QDate

import dominio
from control_pcs.repositories import pcstream_repo
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, formato_tiempo, manejar_errores,
    sin_boton_por_defecto, crear_tabla, rango_de_fechas,
)

# Columnas que van alineadas a la derecha (números, tiempos y plata).
_COLUMNAS_A_LA_DERECHA = (1, 2, 3, 4, 5)


def _tiempo(segundos: int) -> str:
    """Un tiempo para la tabla: "—" si es cero (un "0m 00s" se lee como un dato)."""
    return formato_tiempo(segundos) if segundos else "—"


class PestañaPcstream(QWidget):
    """Totales de PCSTREAM en un rango de fechas y el detalle por día."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        hoy = QDate.currentDate()
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, QDate(hoy.year(), hoy.month(), 1), solo_hoy=True
        )

        self.etiqueta_recaudado = QLabel()
        self.etiqueta_vendido = QLabel()
        self.etiqueta_uso = QLabel()
        self.etiqueta_bonos = QLabel()
        totales = QHBoxLayout()
        for titulo, etiqueta in (
            ("RECAUDADO", self.etiqueta_recaudado),
            ("TIEMPO VENDIDO", self.etiqueta_vendido),
            ("TIEMPO DE USO", self.etiqueta_uso),
            ("BONOS VENDIDOS", self.etiqueta_bonos),
        ):
            columna = QVBoxLayout()
            rotulo = QLabel(titulo, alignment=Qt.AlignCenter)
            rotulo.setStyleSheet("color: #6B7585; font-size: 12px; font-weight: 600;")
            etiqueta.setAlignment(Qt.AlignCenter)
            etiqueta.setStyleSheet("color: #2F6FED; font-size: 22px; font-weight: 700;")
            columna.addWidget(rotulo)
            columna.addWidget(etiqueta)
            totales.addLayout(columna)

        self.tabla = crear_tabla(
            ["Día", "Sesiones", "Bonos vendidos", "Tiempo vendido", "Tiempo de uso", "Recaudado"],
            estirar=0,
        )
        # Los números al ancho de su título: con el ancho fijo de siempre,
        # "Bonos vendidos" y "Tiempo vendido" salían cortados.
        for columna in _COLUMNAS_A_LA_DERECHA:
            self.tabla.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)

        nota = QLabel(
            f"Lo recaudado por {dominio.NOMBRE_PCSTREAM} ya está sumado en \"Alquiler de PCs\" "
            "(Caja, Cierre de Turno y Totales). Tiempo de uso: lo que estuvo habilitada de verdad; "
            "es menos que lo vendido si se cortó una sesión antes de tiempo. Cada sesión cuenta "
            "en el día en que empezó."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(12)
        layout.addLayout(totales)
        layout.addSpacing(12)
        layout.addWidget(self.tabla)
        layout.addWidget(nota)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_fila(self, etiqueta: str, datos: dict, negrita: bool = False):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        valores = [
            etiqueta,
            str(datos["sesiones"]),
            str(datos["bonos"]),
            _tiempo(datos["minutos_vendidos"] * 60),
            _tiempo(datos["segundos_de_uso"]),
            formato_pesos(datos["recaudado"]),
        ]
        for columna, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            if columna in _COLUMNAS_A_LA_DERECHA:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if negrita:
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
            self.tabla.setItem(fila, columna, item)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        uso = pcstream_repo.uso_por_dia(desde, hasta)
        total = uso["total"]

        self.etiqueta_recaudado.setText(formato_pesos(total["recaudado"]))
        self.etiqueta_vendido.setText(_tiempo(total["minutos_vendidos"] * 60))
        self.etiqueta_uso.setText(_tiempo(total["segundos_de_uso"]))
        self.etiqueta_bonos.setText(str(total["bonos"]))

        self.tabla.setRowCount(0)
        for dia in uso["dias"]:
            self._agregar_fila(date.fromisoformat(dia["dia"]).strftime("%d/%m/%Y"), dia)
        if len(uso["dias"]) > 1:
            self._agregar_fila("TOTAL", total, negrita=True)
