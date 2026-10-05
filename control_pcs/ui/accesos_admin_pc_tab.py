"""
accesos_admin_pc_tab.py
=========================
Pestaña "Admin en PCs cliente" de ui/accesos_admin_window.py: cada vez que
alguien entró al panel admin de un Cliente PC, cerró el Cliente PC (dejando
la PC sin bloqueo) o lo volvió a arrancar, y cuánto estuvo la PC sin
bloqueo. Ver control_pcs/repositories/accesos_admin_pc_repo.py.

Vive en control_pcs/ui (y no junto a la ventana) porque es del negocio de
las PCs, aunque la ventana que la contiene es la de Configuración ADMIN.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QDateEdit, QTableWidget, QTableWidgetItem,
    QHeaderView, QWidget,
)
from PySide6.QtCore import QDate
from PySide6.QtGui import QColor

import dominio
from control_pcs.repositories import accesos_admin_pc_repo, pcs_repo
from ui.utils import formato_tiempo, formato_transcurrido, manejar_errores, encadenar_enter

# Mismo lila que usa la grilla de Control de PCs para "sin bloqueo".
COLOR_SIN_BLOQUEO = QColor("#E6D5F5")
COLOR_VOLVIO = QColor("#DCF3E1")


class PestañaAccesosAdminPc(QWidget):
    """Qué PCs están sin bloqueo ahora mismo (arriba) y el historial de
    eventos del panel admin entre dos fechas (tabla)."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde = QDateEdit(QDate.currentDate().addDays(-7))
        self.fecha_desde.setCalendarPopup(True)
        self.fecha_hasta = QDateEdit(QDate.currentDate())
        self.fecha_hasta.setCalendarPopup(True)
        boton_buscar = QPushButton("Buscar")
        boton_buscar.clicked.connect(self._buscar)
        encadenar_enter(self.fecha_desde, self.fecha_hasta, accion_final=self._buscar)

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Desde:"))
        filtros.addWidget(self.fecha_desde)
        filtros.addWidget(QLabel("Hasta:"))
        filtros.addWidget(self.fecha_hasta)
        filtros.addWidget(boton_buscar)
        filtros.addStretch()

        self.etiqueta_ahora = QLabel()
        self.etiqueta_ahora.setWordWrap(True)
        self.etiqueta_ahora.setStyleSheet("font-weight: bold;")

        self.tabla = QTableWidget(0, 5)
        self.tabla.setHorizontalHeaderLabels(["Fecha", "Hora", "PC", "Qué pasó", "Estuvo sin bloqueo"])
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)

        nota = QLabel(
            "La contraseña admin es una sola para todos: acá se ve QUÉ PC y CUÁNDO, no quién. "
            "\"Estuvo sin bloqueo\" corre hasta que el Cliente PC volvió a conectarse; si apagaron "
            "la PC en el medio, incluye el tiempo que estuvo apagada."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_ahora)
        layout.addWidget(self.tabla)
        layout.addWidget(nota)
        self.setLayout(layout)

    @manejar_errores
    def _buscar(self, _=None):
        desde = self.fecha_desde.date().toString("yyyy-MM-dd")
        hasta = self.fecha_hasta.date().toString("yyyy-MM-dd")

        sin_bloqueo = [i for i in pcs_repo.estado_estaciones() if i["cliente_cerrado_admin_desde"] is not None]
        if sin_bloqueo:
            partes = [
                f"{i['estacion']['nombre']} (hace {formato_transcurrido(i['cliente_cerrado_admin_desde'])})"
                for i in sin_bloqueo
            ]
            self.etiqueta_ahora.setText("🔓 Sin bloqueo ahora: " + ", ".join(partes))
        else:
            self.etiqueta_ahora.setText("Ninguna PC está sin bloqueo por un cierre desde el panel admin.")

        self.tabla.setRowCount(0)
        for evento in accesos_admin_pc_repo.listar_eventos(desde, hasta):
            momento = datetime.fromisoformat(evento["fecha_hora"])
            duracion = (
                formato_tiempo(evento["segundos_sin_cliente"])
                if evento["segundos_sin_cliente"] is not None else ""
            )
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            for columna, valor in enumerate([
                momento.strftime("%d/%m/%Y"), momento.strftime("%H:%M:%S"), evento["estacion_nombre"],
                dominio.NOMBRE_EVENTO_ADMIN_PC[evento["tipo"]], duracion,
            ]):
                celda = QTableWidgetItem(valor)
                if evento["tipo"] in dominio.EVENTOS_ADMIN_QUE_DEJAN_PC_SIN_CLIENTE:
                    celda.setBackground(COLOR_SIN_BLOQUEO)
                elif evento["tipo"] == dominio.EVENTO_ADMIN_CLIENTE_REANUDADO:
                    celda.setBackground(COLOR_VOLVIO)
                self.tabla.setItem(fila, columna, celda)
