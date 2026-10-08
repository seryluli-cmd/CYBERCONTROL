"""
caja_window.py
================
Pantallas relacionadas con la plata del día a día:

- CajaWindow: consulta rápida de "cómo viene la caja" en cualquier
  momento, sin cerrar nada.
- CierreTurnoWindow: el cierre real de turno. Calcula cuánto tiene que
  retirar la empleada (dejando el fondo de cambio fijo para el próximo
  turno) y lo deja guardado.

Y dos más, para controlar los cierres después (Admin, o una Empleada con
`permiso_control_cierres`):
- ControlCierresWindow: historial de cierres (uno por turno cerrado) con
  los totales de cada sobre, y para cargar lo que realmente se contó.
- DialogoDetalleCierre: el detalle de un cierre puntual -- venta por
  venta (ver turnos_repo.detalle_cierre), para entender cómo se llegó a
  esos totales sin tener que ir a buscarlas por separado en Consulta de
  Ventas.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem,
    QInputDialog, QWidget, QListWidget,
)
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

import dominio
from turnos import etiqueta_turno
from repositories import turnos_repo
from ui.detalle_venta import VentanaConDetalleDeVenta, crear_tabla_detalle_venta
from ui.utils import (
    formato_pesos, mostrar_info, confirmar, mostrar_error, manejar_errores, aplicar_clase,
    sin_boton_por_defecto, crear_tabla,
)


def _texto_desglose(efectivo: float, digital: float) -> str:
    """"$X ef. + $Y dig." -- una sola línea para mostrar el desglose de un
    origen (Kiosko, Alquiler de PCs o PlayStation 5) sin ocupar dos etiquetas
    por cada uno, ver CajaWindow/CierreTurnoWindow."""
    return f"{formato_pesos(efectivo)} ef. + {formato_pesos(digital)} dig."


def _etiqueta_dato(titulo, valor_texto):
    """Un dato de las pantallas de caja: título gris arriba y valor grande
    abajo. Devuelve (layout, etiqueta_del_valor) para poder actualizarla."""
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


class _PantallaDeCaja(QDialog):
    """Lo que comparten Caja y Cierre de Turno: un título centrado, los
    datos de a dos por fila, una nota en gris y los botones abajo."""

    def _armar_cuerpo(self, filas_de_datos, texto_nota, botones):
        """
        Arma la pantalla. El título queda en `self.titulo` para que la
        subclase lo complete al refrescar.

        - `filas_de_datos`: lista de pares de layouts hechos con `_etiqueta_dato`.
        - `botones`: el layout con los botones, ya armado.
        """
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.titulo.setAlignment(Qt.AlignCenter)

        nota = QLabel(texto_nota)
        nota.setWordWrap(True)
        nota.setStyleSheet("color: gray; font-style: italic;")

        layout = QVBoxLayout()
        layout.addWidget(self.titulo)
        for izquierda, derecha in filas_de_datos:
            fila = QHBoxLayout()
            fila.addLayout(izquierda)
            fila.addLayout(derecha)
            layout.addLayout(fila)
        layout.addWidget(nota)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)


class CajaWindow(_PantallaDeCaja):
    """Consulta de caja en vivo: cómo viene el turno actual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Caja")
        self.resize(460, 430)
        self._armar_interfaz()
        self._refrescar()

    def _armar_interfaz(self):
        layout_fondo, self.valor_fondo = _etiqueta_dato("CAJA INICIAL (fondo de cambio)", "")
        layout_actual, self.valor_actual = _etiqueta_dato("CAJA ACTUAL (solo efectivo)", "")
        layout_ventas, self.valor_ventas = _etiqueta_dato("VENTAS (efectivo)", "")
        layout_digital, self.valor_digital = _etiqueta_dato("VENTAS POR MEDIO DIGITAL", "")
        layout_kiosko, self.valor_kiosko = _etiqueta_dato(
            f"VENTAS — {dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO]}", ""
        )
        layout_pcs, self.valor_pcs = _etiqueta_dato(
            f"VENTAS — {dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS]}", ""
        )
        layout_playstation, self.valor_playstation = _etiqueta_dato(
            f"VENTAS — {dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION]}", ""
        )

        boton_refrescar = QPushButton("Actualizar")
        boton_refrescar.clicked.connect(self._refrescar)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        botones = QHBoxLayout()
        botones.addWidget(boton_refrescar)
        botones.addStretch()
        botones.addWidget(boton_salir)

        self._armar_cuerpo(
            [(layout_fondo, layout_actual), (layout_ventas, layout_digital),
             (layout_kiosko, layout_pcs), (layout_playstation, QVBoxLayout())],
            "La Caja Actual suma solo el EFECTIVO; no incluye lo cobrado por Digital.",
            botones,
        )

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
        self.valor_playstation.setText(
            _texto_desglose(resumen["playstation_efectivo"], resumen["playstation_digital"])
        )


class CierreTurnoWindow(_PantallaDeCaja):
    """Cierre real del turno: lo puede hacer cualquier usuario logueado
    (Admin o Empleada) para cerrar SU turno en curso."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        # En True apenas se confirma el cierre (ver _cerrar_turno) -- lo
        # consulta MainWindow._abrir_cierre_turno después de exec() para
        # saber si corresponde volver sola al Login (ver ese método).
        self.turno_cerrado = False
        self.setWindowTitle("Cierre de Turno")
        self.resize(460, 470)
        self._armar_interfaz()
        self._refrescar_vista_previa()

    def _armar_interfaz(self):
        layout_fondo, self.valor_fondo = _etiqueta_dato("Fondo de cambio", "")
        layout_efectivo, self.valor_efectivo = _etiqueta_dato("Ventas en Efectivo", "")
        layout_digital, self.valor_digital = _etiqueta_dato("Ventas Digital", "")
        layout_retirar, self.valor_retirar = _etiqueta_dato("A RETIRAR EN EFECTIVO", "")
        layout_kiosko, self.valor_kiosko = _etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO], ""
        )
        layout_pcs, self.valor_pcs = _etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS], ""
        )
        layout_playstation, self.valor_playstation = _etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION], ""
        )

        boton_cerrar_turno = QPushButton("Confirmar Cierre de Turno")
        aplicar_clase(boton_cerrar_turno, "primario")
        boton_cerrar_turno.clicked.connect(self._cerrar_turno)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.close)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(boton_cerrar_turno)

        self._armar_cuerpo(
            [(layout_fondo, layout_efectivo), (layout_digital, layout_retirar),
             (layout_kiosko, layout_pcs), (layout_playstation, QVBoxLayout())],
            "Retirá el efectivo indicado y guardalo en el sobre. Dejá el fondo de "
            "cambio en el cajón para que arranque el próximo turno.",
            botones,
        )

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
        self.valor_playstation.setText(
            _texto_desglose(resumen["playstation_efectivo"], resumen["playstation_digital"])
        )

    @manejar_errores
    def _cerrar_turno(self):
        if not confirmar(self, "Confirmar cierre",
                          "¿Confirmás el cierre de este turno? No se puede deshacer."):
            return
        resultado = turnos_repo.cerrar_turno(self.usuario["id"])
        self.turno_cerrado = True
        mostrar_info(
            self, "Turno cerrado",
            f"Turno {resultado['turno_label']} cerrado correctamente.\n\n"
            f"Retirá: {formato_pesos(resultado['monto_a_retirar'])}\n"
            f"(dejando {formato_pesos(resultado['fondo_cambio'])} de fondo para el próximo turno)\n\n"
            "Ahora volvés a la pantalla de ingreso: quien te releve tiene que "
            "entrar con su propio usuario."
        )
        self.close()


class ControlCierresWindow(QDialog):
    """Pantalla para revisar el historial de cierres de turno (Admin, o
    Empleada con `permiso_control_cierres`): cargar cuánto se contó
    realmente en cada sobre y ver qué turnos del mes en curso quedaron sin
    cerrar."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Control de Cierres de Turno")
        self.resize(1180, 520)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        # Aviso de turnos ya vencidos (ventana + turnos.TURNO_GRACIA_MIN) del
        # mes en curso que todavía no tienen cierre cargado — ver
        # turnos_repo.turnos_faltantes(). Es una QListWidget (no un QLabel)
        # con alto máximo y scroll propio: puede haber más de un centenar de
        # líneas (kiosko recién instalado, o meses sin revisar esta pantalla)
        # y no debe empujar la tabla ni los botones fuera de la ventana.
        # Seleccionar una fila no dispara ninguna acción (ver nota debajo):
        # un turno vencido no se puede cargar por separado, así que es un
        # aviso, no una lista para "completar". Arranca oculto y solo se
        # muestra si hay algo que avisar (ver _cargar_faltantes).
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

        self.tabla = crear_tabla(
            ["Fecha", "Turno", "Empleada", "Fondo", "Ventas Ef.", "Kiosko", "Alquiler PCs",
             "PlayStation 5", "A Retirar", "Contado", "Diferencia"],
            estirar=2, por_filas=True,
        )
        self.tabla.doubleClicked.connect(self._ver_detalle)

        boton_detalle = QPushButton("Ver Detalle del cierre seleccionado")
        boton_detalle.clicked.connect(self._ver_detalle)
        boton_verificar = QPushButton("Cargar monto contado en el cierre seleccionado")
        aplicar_clase(boton_verificar, "primario")
        boton_verificar.clicked.connect(self._verificar)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)

        botones = QHBoxLayout()
        botones.addWidget(boton_detalle)
        botones.addWidget(boton_verificar)
        botones.addStretch()
        botones.addWidget(boton_salir)

        layout = QVBoxLayout()
        layout.addWidget(self.panel_faltantes)
        layout.addWidget(self.tabla)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

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
            self.tabla.setItem(fila, 7, QTableWidgetItem(
                formato_pesos(cierre["playstation_efectivo"] + cierre["playstation_digital"])
            ))
            self.tabla.setItem(fila, 8, QTableWidgetItem(formato_pesos(cierre["monto_a_retirar"])))

            contado = cierre["monto_contado"]
            self.tabla.setItem(fila, 9, QTableWidgetItem(formato_pesos(contado) if contado is not None else "—"))

            diferencia = cierre["diferencia"]
            item_diferencia = QTableWidgetItem(formato_pesos(diferencia) if diferencia is not None else "—")
            if diferencia is not None and abs(diferencia) > 0.01:
                item_diferencia.setForeground(Qt.red)
            self.tabla.setItem(fila, 10, item_diferencia)

        self._cargar_faltantes()

    def _cargar_faltantes(self):
        """Turnos del mes en curso ya vencidos (con su gracia) que todavía
        no tienen cierre — ver turnos_repo.turnos_faltantes()."""
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
    def _ver_detalle(self, _=None):
        # El "_=None" no se usa: recibe el dato que manda `doubleClicked`
        # (la fila clickeada). Qt solo recorta los argumentos que una
        # función no acepta si ve su firma real; @manejar_errores la envuelve
        # en "*args, **kwargs", así que Qt le pasa todo. Sin este parámetro,
        # doble clic en una fila tiraba "takes 1 positional argument but 2
        # were given" en vez de abrir el detalle. (Mismo caso en
        # ArticulosWindow._cargar_grilla.)
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un cierre de la lista.")
            return
        cierre = self.cierres[fila]
        DialogoDetalleCierre(cierre, self).exec()

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


class DialogoDetalleCierre(VentanaConDetalleDeVenta):
    """
    Detalle de un cierre puntual: la lista de ventas que cayeron dentro
    de ese turno (ver turnos_repo.detalle_cierre), para que el Admin
    pueda ver venta por venta cómo se llegó al total del sobre en vez de
    confiar solo en los números agregados de la tabla de Control de
    Cierres. Mismo patrón maestro-detalle que ConsultaVentasWindow: al
    seleccionar una venta, abajo aparecen sus artículos -- una venta sin
    detalle real (bono de PC, bono de la PlayStation 5, carga de saldo de
    Miembro) simplemente deja esa tabla vacía, no hace falta un caso especial.
    """

    def __init__(self, cierre, parent=None):
        super().__init__(parent)
        self.cierre = cierre
        self.setWindowTitle(
            f"Detalle — Turno {etiqueta_turno(cierre['fecha'], cierre['turno'])} del {cierre['fecha']}"
        )
        self.resize(820, 560)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.encabezado = QLabel()
        self.encabezado.setWordWrap(True)
        self.encabezado.setStyleSheet("font-weight: 600;")

        self.tabla = crear_tabla(
            ["Hora", "Vendedor", "Origen", "Total", "Método", "Estado"],
            estirar=1, por_filas=True,
        )
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)

        self.tabla_detalle = crear_tabla_detalle_venta()

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addWidget(self.encabezado)
        layout.addWidget(QLabel("Ventas del turno:"))
        layout.addWidget(self.tabla)
        layout.addWidget(QLabel(
            "Artículos de la venta seleccionada (vacío si es bono de PC, de PlayStation o carga de saldo):"
        ))
        layout.addWidget(self.tabla_detalle)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        resultado = turnos_repo.detalle_cierre(self.cierre["id"])
        self.ventas = resultado["ventas"]

        # "desde" y "fecha_cierre" son ISO "YYYY-MM-DDTHH:MM:SS" -- solo
        # se muestra el rango horario acá, la fecha ya está en el título.
        desde_hora = resultado["desde"][11:16]
        hasta_hora = self.cierre["fecha_cierre"][11:16]
        self.encabezado.setText(
            f"Empleada: {self.cierre['empleada']}   ·   Rango: {desde_hora} → {hasta_hora}   ·   "
            f"A retirar: {formato_pesos(self.cierre['monto_a_retirar'])}"
        )

        self.tabla.setRowCount(0)
        for venta in self.ventas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(venta["fecha"][11:16]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(venta["vendedor"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(dominio.NOMBRE_ORIGEN_VENTA[venta["origen"]]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(venta["total"])))
            metodos = venta["metodos"].split(",") if venta["metodos"] else []
            texto_metodos = " + ".join(dominio.NOMBRE_METODO_PAGO[metodo] for metodo in metodos)
            self.tabla.setItem(fila, 4, QTableWidgetItem(texto_metodos))
            item_estado = QTableWidgetItem(venta["estado"])
            if venta["estado"] == dominio.VENTA_ANULADA:
                item_estado.setForeground(Qt.red)
            self.tabla.setItem(fila, 5, item_estado)
        self.tabla_detalle.setRowCount(0)

