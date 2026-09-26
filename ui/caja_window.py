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
    QTableWidgetItem, QHeaderView, QInputDialog, QWidget, QListWidget
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

import dominio
from turnos import etiqueta_turno
from repositories import turnos_repo
from ui.utils import formato_pesos, mostrar_info, confirmar, mostrar_error, manejar_errores, aplicar_clase


def _texto_desglose(efectivo: float, digital: float) -> str:
    """"$X ef. + $Y dig." -- una sola línea para mostrar el desglose de un
    origen (Kiosko o Alquiler de PCs) sin ocupar dos etiquetas por cada
    uno, ver CajaWindow/CierreTurnoWindow."""
    return f"{formato_pesos(efectivo)} ef. + {formato_pesos(digital)} dig."


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
        self.resize(460, 360)
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

        fila3 = QHBoxLayout()
        layout_kiosko, self.valor_kiosko = _etiqueta_dato(
            f"VENTAS — {dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO]}", ""
        )
        layout_pcs, self.valor_pcs = _etiqueta_dato(
            f"VENTAS — {dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS]}", ""
        )
        fila3.addLayout(layout_kiosko)
        fila3.addLayout(layout_pcs)

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
        layout.addLayout(fila3)
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
        self.titulo.setText(f"CAJA — Turno {resumen['turno_actual_label']}")
        self.valor_fondo.setText(formato_pesos(resumen["fondo_cambio"]))
        self.valor_actual.setText(formato_pesos(resumen["caja_actual"]))
        self.valor_ventas.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))
        self.valor_kiosko.setText(_texto_desglose(resumen["kiosko_efectivo"], resumen["kiosko_digital"]))
        self.valor_pcs.setText(_texto_desglose(resumen["pcs_efectivo"], resumen["pcs_digital"]))


class CierreTurnoWindow(QDialog):
    """Cierre real del turno: lo puede hacer cualquier usuario logueado
    (Admin o Empleada) para cerrar SU turno en curso."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Cierre de Turno")
        self.resize(460, 400)
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

        fila3 = QHBoxLayout()
        layout_kiosko, self.valor_kiosko = _etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO], ""
        )
        layout_pcs, self.valor_pcs = _etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS], ""
        )
        fila3.addLayout(layout_kiosko)
        fila3.addLayout(layout_pcs)

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
        layout.addLayout(fila3)
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
        self.titulo.setText(f"Cierre de Turno {resumen['turno_actual_label']}")
        self.valor_fondo.setText(formato_pesos(resumen["fondo_cambio"]))
        self.valor_efectivo.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))
        self.valor_retirar.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_kiosko.setText(_texto_desglose(resumen["kiosko_efectivo"], resumen["kiosko_digital"]))
        self.valor_pcs.setText(_texto_desglose(resumen["pcs_efectivo"], resumen["pcs_digital"]))

    @manejar_errores
    def _cerrar_turno(self):
        if not confirmar(self, "Confirmar cierre",
                          "¿Confirmás el cierre de este turno? No se puede deshacer."):
            return
        resultado = turnos_repo.cerrar_turno(self.usuario["id"])
        mostrar_info(
            self, "Turno cerrado",
            f"Turno {resultado['turno_label']} cerrado correctamente.\n\n"
            f"Retirá: {formato_pesos(resultado['monto_a_retirar'])}\n"
            f"(dejando {formato_pesos(resultado['fondo_cambio'])} de fondo para el próximo turno)"
        )
        self.close()


class ControlCierresWindow(QDialog):
    """Pantalla de Admin para revisar el historial de cierres de turno,
    cargar cuánto se contó realmente en cada sobre, y ver qué turnos del
    mes en curso quedaron sin cerrar."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Control de Cierres de Turno")
        self.resize(1050, 520)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        # Aviso de turnos ya vencidos (ventana + 40 min de gracia) del mes
        # en curso que todavía no tienen cierre cargado — ver
        # turnos_repo.turnos_faltantes(). Es una QListWidget (no un QLabel
        # de texto plano) para que cada línea se pueda seleccionar con el
        # mouse como cualquier otra lista de la app, con su propio alto
        # máximo y scroll interno — puede haber muchas líneas (un kiosko
        # recién instalado, o varios meses sin revisar esta pantalla,
        # fácilmente pasa el centenar) y no debe empujar la tabla ni los
        # botones fuera de la ventana. Seleccionar una fila no dispara
        # ninguna acción (ver nota debajo): en este sistema un turno
        # vencido no se puede cargar por separado, así que es un aviso
        # para que el Admin lo note, no una lista para "completar".
        # Arranca oculto: solo se muestra si hay algo que avisar (ver
        # _cargar_faltantes).
        self.panel_faltantes = QWidget()
        panel_layout = QVBoxLayout(self.panel_faltantes)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)

        self.titulo_faltantes = QLabel()
        self.titulo_faltantes.setStyleSheet("color: #A6323C; font-weight: 600;")

        self.lista_faltantes = QListWidget()
        self.lista_faltantes.setMaximumHeight(140)
        self.lista_faltantes.setStyleSheet(
            "QListWidget { background-color: #FBEAEA; border: 1px solid #D9838A; "
            "border-radius: 6px; color: #A6323C; } "
            "QListWidget::item { padding: 3px 6px; } "
            "QListWidget::item:selected { background-color: #F3D3D3; color: #A6323C; }"
        )

        nota_faltantes = QLabel(
            "Un turno vencido no se carga por separado: al confirmar \"Cierre de "
            "Turno\" ahora, todo lo vendido desde el último cierre se agrupa junto, "
            "sin importar cuántos turnos nominales pasaron en el medio. El nombre al "
            "final de cada línea es quién vendió algo o inició sesión en ese horario "
            "(no hay horarios asignados por empleada, así que es una pista de a quién "
            "preguntarle, no una certeza)."
        )
        nota_faltantes.setWordWrap(True)
        nota_faltantes.setStyleSheet("color: #A6323C; font-style: italic; font-size: 11px;")

        panel_layout.addWidget(self.titulo_faltantes)
        panel_layout.addWidget(self.lista_faltantes)
        panel_layout.addWidget(nota_faltantes)
        self.panel_faltantes.hide()

        self.tabla = QTableWidget(0, 10)
        self.tabla.setHorizontalHeaderLabels(
            ["Fecha", "Turno", "Empleada", "Fondo", "Ventas Ef.", "Kiosko", "Alquiler PCs",
             "A Retirar", "Contado", "Diferencia"]
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
        layout.addWidget(self.panel_faltantes)
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
            self.tabla.setItem(fila, 1, QTableWidgetItem(etiqueta_turno(cierre["fecha"], cierre["turno"])))
            self.tabla.setItem(fila, 2, QTableWidgetItem(cierre["empleada"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(cierre["fondo_cambio"])))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(cierre["ventas_efectivo"])))
            self.tabla.setItem(fila, 5, QTableWidgetItem(
                formato_pesos(cierre["kiosko_efectivo"] + cierre["kiosko_digital"])
            ))
            self.tabla.setItem(fila, 6, QTableWidgetItem(
                formato_pesos(cierre["pcs_efectivo"] + cierre["pcs_digital"])
            ))
            self.tabla.setItem(fila, 7, QTableWidgetItem(formato_pesos(cierre["monto_a_retirar"])))

            contado = cierre["monto_contado"]
            self.tabla.setItem(fila, 8, QTableWidgetItem(formato_pesos(contado) if contado is not None else "—"))

            diferencia = cierre["diferencia"]
            item_diferencia = QTableWidgetItem(formato_pesos(diferencia) if diferencia is not None else "—")
            if diferencia is not None and abs(diferencia) > 0.01:
                item_diferencia.setForeground(Qt.red)
            self.tabla.setItem(fila, 9, item_diferencia)

        self._cargar_faltantes()

    def _cargar_faltantes(self):
        """Turnos del mes en curso ya vencidos (+ 40 min de gracia) que
        todavía no tienen cierre — ver turnos_repo.turnos_faltantes()."""
        faltantes = turnos_repo.turnos_faltantes()
        if not faltantes:
            self.panel_faltantes.hide()
            return
        faltantes_ordenados = sorted(faltantes, key=lambda s: (s["fecha"], s["turno"]), reverse=True)
        self.titulo_faltantes.setText(f"⚠️ TURNOS SIN CERRAR ESTE MES ({len(faltantes)}):")
        self.lista_faltantes.clear()
        for slot in faltantes_ordenados:
            # "usuarios": quién vendió algo o inició sesión en esa
            # ventana (no hay horarios asignados en el sistema, así que
            # es una inferencia, no una certeza — ver
            # turnos_repo._responsables_del_mes).
            quien = ", ".join(slot["usuarios"]) if slot["usuarios"] else "sin actividad registrada"
            texto = f"{etiqueta_turno(slot['fecha'], slot['turno'])} — {slot['fecha'].strftime('%d/%m')} — {quien}"
            self.lista_faltantes.addItem(texto)
        self.panel_faltantes.show()

    @manejar_errores
    def _verificar(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un cierre de la lista.")
            return
        cierre = self.cierres[fila]

        monto, aceptado = QInputDialog.getDouble(
            self, "Monto contado",
            f"Turno {etiqueta_turno(cierre['fecha'], cierre['turno'])} del {cierre['fecha']} — {cierre['empleada']}\n"
            f"Se esperaba retirar: {formato_pesos(cierre['monto_a_retirar'])}\n\n"
            "¿Cuánto contaste realmente en el sobre?",
            cierre["monto_a_retirar"], 0, 99_999_999, 2
        )
        if not aceptado:
            return

        turnos_repo.verificar_cierre(cierre["id"], monto, self.usuario["id"])
        self._cargar()
