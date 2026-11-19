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

from PySide6.QtWidgets import QWidget, QVBoxLayout, QHBoxLayout, QTableWidgetItem, QHeaderView
from PySide6.QtCore import Qt, QDate

import dominio
from control_pcs.repositories import pcstream_repo
from ui.piezas_ventana import TONO_CELESTE, TONO_GRIS, cifra_destacada, pie_de_ventana
from ui.reportes_piezas import como_plata, panel_de_reporte, tarjeta_de_filtros, titulos_en_mayuscula
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, formato_tiempo, hoy_del_local, manejar_errores,
    sin_boton_por_defecto, crear_tabla, rango_de_fechas,
)

# Columnas que van alineadas a la derecha (números, tiempos y plata).
_COLUMNAS_A_LA_DERECHA = (1, 2, 3, 4, 5)
_COLUMNA_RECAUDADO = 5


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
        hoy = hoy_del_local()
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, QDate(hoy.year(), hoy.month(), 1), solo_hoy=True, dias_del_local=True
        )

        # Los totales en las cifras grandes de Resumen de Ventas (2026-11-19): la plata
        # en el celeste de PCSTREAM (ui/dibujos_tabla.TONO_PCSTREAM), lo demás en gris.
        recaudado = cifra_destacada("RECAUDADO", "Ya sumado en Alquiler de PCs", TONO_CELESTE)
        vendido = cifra_destacada("TIEMPO VENDIDO", "Lo que suman los bonos", TONO_GRIS)
        uso = cifra_destacada("TIEMPO DE USO", "Lo que estuvo habilitada", TONO_GRIS)
        bonos = cifra_destacada("BONOS VENDIDOS", "En estas fechas", TONO_GRIS)
        self.etiqueta_recaudado = recaudado.valor
        self.etiqueta_vendido = vendido.valor
        self.etiqueta_uso = uso.valor
        self.etiqueta_bonos = bonos.valor
        totales = QHBoxLayout()
        totales.setSpacing(12)
        for cifra in (recaudado, vendido, uso, bonos):
            totales.addWidget(cifra, 1)

        self.tabla = crear_tabla(
            ["Día", "Sesiones", "Bonos vendidos", "Tiempo vendido", "Tiempo de uso", "Recaudado"],
            estirar=0,
        )
        titulos_en_mayuscula(self.tabla, a_la_derecha=_COLUMNAS_A_LA_DERECHA)
        # Los números al ancho de su título: con el ancho fijo de siempre,
        # "Bonos vendidos" y "Tiempo vendido" salían cortados.
        for columna in _COLUMNAS_A_LA_DERECHA:
            self.tabla.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)

        nota = pie_de_ventana(
            f"Lo recaudado por {dominio.NOMBRE_PCSTREAM} ya está sumado en \"Alquiler de PCs\" "
            "(Caja, Cierre de Turno y Totales). Tiempo de uso: lo que estuvo habilitada de verdad; "
            "es menos que lo vendido si se cortó una sesión antes de tiempo. Cada sesión cuenta "
            "en el día en que empezó."
        )

        # Como las demás secciones de Reportes: los filtros en su tarjeta y la grilla
        # en su panel blanco.
        layout = QVBoxLayout()
        layout.setContentsMargins(0, 12, 0, 0)
        layout.setSpacing(12)
        layout.addWidget(tarjeta_de_filtros(filtros))
        layout.addLayout(totales)
        layout.addWidget(panel_de_reporte(self.tabla), 1)
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
            if columna == _COLUMNA_RECAUDADO:
                como_plata(item)
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
