"""
caja_window.py
================
Dos pantallas relacionadas con la plata del día a día:

- CajaWindow: consulta rápida de "cómo viene la caja" en cualquier
  momento, sin cerrar nada (equivalente a la pantalla "Caja" del
  sistema actual).
- CierreTurnoWindow: el cierre real de turno. Calcula cuánto tiene que
  retirar la empleada (dejando el fondo de cambio fijo para el próximo
  turno) y lo deja guardado.

Y una tercera, solo para Admin, para controlar los cierres después
(cargar lo que realmente se contó en cada sobre).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QInputDialog
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

from repositories import turnos_repo
from ui.utils import formato_pesos, mostrar_info, confirmar, mostrar_error, manejar_errores, aplicar_clase


def _etiqueta_dato(titulo, valor_texto):
    contenedor = QVBoxLayout()
    titulo_lbl = QLabel(titulo)
    titulo_lbl.setStyleSheet("color: gray;")
    valor_lbl = QLabel(valor_texto)
    fuente = QFont()
    fuente.setPointSize(14)
    fuente.setBold(True)
    valor_lbl.setFont(fuente)
    contenedor.addWidget(titulo_lbl)
    contenedor.addWidget(valor_lbl)
    return contenedor, valor_lbl


class CajaWindow(QDialog):
    """Consulta de caja en vivo: cómo viene el turno actual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Caja")
        self.resize(420, 300)
        self._armar_interfaz()
        self._refrescar()

    def _armar_interfaz(self):
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.titulo.setAlignment(Qt.AlignCenter)

        fila1 = QHBoxLayout()
        layout_fondo, self.valor_fondo = _etiqueta_dato("CAJA INICIAL (fondo de cambio)", "")
        layout_actual, self.valor_actual = _etiqueta_dato("CAJA ACTUAL (solo efectivo)", "")
        fila1.addLayout(layout_fondo)
        fila1.addLayout(layout_actual)

        fila2 = QHBoxLayout()
        layout_ventas, self.valor_ventas = _etiqueta_dato("VENTAS (efectivo)", "")
        layout_digital, self.valor_digital = _etiqueta_dato("VENTAS POR MEDIO DIGITAL", "")
        fila2.addLayout(layout_ventas)
        fila2.addLayout(layout_digital)

        nota = QLabel("La Caja Actual suma solo el EFECTIVO; no incluye lo cobrado por Digital.")
        nota.setWordWrap(True)
        nota.setStyleSheet("color: gray; font-style: italic;")

        boton_refrescar = QPushButton("Actualizar")
        boton_refrescar.clicked.connect(self._refrescar)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        botones = QHBoxLayout()
        botones.addWidget(boton_refrescar)
        botones.addStretch()
        botones.addWidget(boton_salir)

        layout = QVBoxLayout()
        layout.addWidget(self.titulo)
        layout.addLayout(fila1)
        layout.addLayout(fila2)
        layout.addWidget(nota)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _refrescar(self):
        resumen = turnos_repo.resumen_turno_actual()
        self.titulo.setText(f"CAJA — Turno {resumen['turno_actual']}")
        self.valor_fondo.setText(formato_pesos(resumen["fondo_cambio"]))
        self.valor_actual.setText(formato_pesos(resumen["caja_actual"]))
        self.valor_ventas.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))


class CierreTurnoWindow(QDialog):
    """Cierre real del turno: lo puede hacer cualquier usuario logueado
    (Admin o Empleada) para cerrar SU turno en curso."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Cierre de Turno")
        self.resize(420, 340)
        self._armar_interfaz()
        self._refrescar_vista_previa()

    def _armar_interfaz(self):
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.titulo.setAlignment(Qt.AlignCenter)

        fila1 = QHBoxLayout()
        layout_fondo, self.valor_fondo = _etiqueta_dato("Fondo de cambio", "")
        layout_efectivo, self.valor_efectivo = _etiqueta_dato("Ventas en Efectivo", "")
        fila1.addLayout(layout_fondo)
        fila1.addLayout(layout_efectivo)

        fila2 = QHBoxLayout()
        layout_digital, self.valor_digital = _etiqueta_dato("Ventas Digital", "")
        layout_retirar, self.valor_retirar = _etiqueta_dato("A RETIRAR EN EFECTIVO", "")
        fila2.addLayout(layout_digital)
        fila2.addLayout(layout_retirar)

        nota = QLabel(
            "Retirá el efectivo indicado y guardalo en el sobre. Dejá el fondo de "
            "cambio en el cajón para que arranque el próximo turno."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: gray; font-style: italic;")

        boton_cerrar_turno = QPushButton("Confirmar Cierre de Turno")
        aplicar_clase(boton_cerrar_turno, "primario")
        boton_cerrar_turno.clicked.connect(self._cerrar_turno)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.close)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(boton_cerrar_turno)

        layout = QVBoxLayout()
        layout.addWidget(self.titulo)
        layout.addLayout(fila1)
        layout.addLayout(fila2)
        layout.addWidget(nota)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _refrescar_vista_previa(self):
        resumen = turnos_repo.resumen_turno_actual()
        self.titulo.setText(f"Cierre de Turno {resumen['turno_actual']}")
        self.valor_fondo.setText(formato_pesos(resumen["fondo_cambio"]))
        self.valor_efectivo.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))
        self.valor_retirar.setText(formato_pesos(resumen["ventas_efectivo"]))

    @manejar_errores
    def _cerrar_turno(self):
        if not confirmar(self, "Confirmar cierre",
                          "¿Confirmás el cierre de este turno? No se puede deshacer."):
            return
        resultado = turnos_repo.cerrar_turno(self.usuario["id"])
        mostrar_info(
            self, "Turno cerrado",
            f"Turno cerrado correctamente.\n\n"
            f"Retirá: {formato_pesos(resultado['monto_a_retirar'])}\n"
            f"(dejando {formato_pesos(resultado['fondo_cambio'])} de fondo para el próximo turno)"
        )
        self.close()


class ControlCierresWindow(QDialog):
    """Pantalla de Admin para revisar el historial de cierres de turno y
    cargar cuánto se contó realmente en cada sobre."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Control de Cierres de Turno")
        self.resize(900, 450)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.tabla = QTableWidget(0, 8)
        self.tabla.setHorizontalHeaderLabels(
            ["Fecha", "Turno", "Empleada", "Fondo", "Ventas Ef.", "A Retirar", "Contado", "Diferencia"]
        )
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        boton_verificar = QPushButton("Cargar monto contado en el cierre seleccionado")
        aplicar_clase(boton_verificar, "primario")
        boton_verificar.clicked.connect(self._verificar)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)

        botones = QHBoxLayout()
        botones.addWidget(boton_verificar)
        botones.addStretch()
        botones.addWidget(boton_salir)

        layout = QVBoxLayout()
        layout.addWidget(self.tabla)
        layout.addLayout(botones)
        self.setLayout(layout)
        # Evita que Qt elija automaticamente el primer boton como "default":
        # sin esto, apretar Enter en cualquier campo de texto (por ejemplo el
        # codigo de barras) tambien activaba el primer boton de la pantalla,
        # como si se hubiera hecho clic en el (por eso se abria la busqueda F5
        # solo con escanear y apretar Enter).
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _cargar(self):
        self.cierres = turnos_repo.listar_cierres()
        self.tabla.setRowCount(0)
        for cierre in self.cierres:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(cierre["fecha"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(cierre["turno"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(cierre["empleada"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(cierre["fondo_cambio"])))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(cierre["ventas_efectivo"])))
            self.tabla.setItem(fila, 5, QTableWidgetItem(formato_pesos(cierre["monto_a_retirar"])))

            contado = cierre["monto_contado"]
            self.tabla.setItem(fila, 6, QTableWidgetItem(formato_pesos(contado) if contado is not None else "—"))

            diferencia = cierre["diferencia"]
            item_diferencia = QTableWidgetItem(formato_pesos(diferencia) if diferencia is not None else "—")
            if diferencia is not None and abs(diferencia) > 0.01:
                item_diferencia.setForeground(Qt.red)
            self.tabla.setItem(fila, 7, item_diferencia)

    @manejar_errores
    def _verificar(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un cierre de la lista.")
            return
        cierre = self.cierres[fila]

        monto, aceptado = QInputDialog.getDouble(
            self, "Monto contado",
            f"Turno {cierre['turno']} del {cierre['fecha']} — {cierre['empleada']}\n"
            f"Se esperaba retirar: {formato_pesos(cierre['monto_a_retirar'])}\n\n"
            "¿Cuánto contaste realmente en el sobre?",
            cierre["monto_a_retirar"], 0, 99_999_999, 2
        )
        if not aceptado:
            return

        turnos_repo.verificar_cierre(cierre["id"], monto, self.usuario["id"])
        self._cargar()
