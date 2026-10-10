"""
reportes_window.py
=====================
Reportes, una pestaña por cada pregunta que se le hace a las ventas:

- Resumen de Ventas: cuánta plata se trabajó en un rango de fechas.
- Resumen del Día: un día abierto por turno, con quién cerró y si el sobre
  cuadró; Kiosko, Impresiones, Trámites, Alquiler de PCs y PlayStation 5 van en
  columnas aparte.
- Por Turno: el total de un rango repartido entre Mañana/Tarde/Noche.
- Totales: Kiosko / Impresiones / Trámites / Alquiler de PCs / PlayStation 5,
  por turno, día, semana o rango.
- Ranking de Ventas: qué se vendió más -- artículos de kiosko, bonos de PC,
  bonos de socios, cargas de saldo por tarifa, trámites y bonos de la
  PlayStation 5, todo junto, con una columna Categoría para distinguir de qué
  rubro vino cada fila (ver reportes_repo.ranking_ventas).

Las usa el Admin o una Empleada con `permiso_reportes`.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QWidget,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor, QFont

from repositories import reportes_repo, turnos_repo
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, manejar_errores, sin_boton_por_defecto,
    crear_tabla, rango_de_fechas, fecha_iso, crear_selector_de_fecha,
)


class ReportesWindow(QDialog):
    """Contenedor de las pestañas de reportes (cada una es un QWidget
    independiente que busca y se muestra sola, ver las clases de abajo)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Reportes")
        # El Resumen del Día tiene 13 columnas: con menos ancho la de "Cerró" (el
        # nombre de quien cerró cada turno) queda tan angosta que corta el nombre.
        # No más ancho que la pantalla, para que la ventana no se salga de ella.
        ancho = 1380
        if self.screen() is not None:
            ancho = min(ancho, self.screen().availableGeometry().width() - 20)
        self.resize(ancho, 560)

        pestañas = QTabWidget()
        pestañas.addTab(PestañaResumen(), "Resumen de Ventas")
        pestañas.addTab(PestañaResumenDelDia(), "Resumen del Día")
        pestañas.addTab(PestañaPorTurno(), "Por Turno")
        pestañas.addTab(PestañaKioskoVsPCs(), "Totales")
        pestañas.addTab(PestañaRanking(), "Ranking de Ventas")

        layout = QVBoxLayout()
        layout.addWidget(pestañas)
        self.setLayout(layout)
        sin_boton_por_defecto(self)


class PestañaResumen(QWidget):
    """Total vendido, cantidad de ventas y desglose Efectivo/Digital de un
    rango de fechas."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True)

        fuente_grande = QFont()
        fuente_grande.setPointSize(20)
        fuente_grande.setBold(True)

        self.etiqueta_total = QLabel()
        self.etiqueta_total.setFont(fuente_grande)
        self.etiqueta_total.setStyleSheet("color: #2F6FED;")
        self.etiqueta_total.setAlignment(Qt.AlignCenter)

        self.etiqueta_cantidad = QLabel()
        self.etiqueta_cantidad.setAlignment(Qt.AlignCenter)

        self.etiqueta_efectivo = QLabel()
        self.etiqueta_digital = QLabel()
        detalle_pagos = QHBoxLayout()
        detalle_pagos.addStretch()
        detalle_pagos.addWidget(self.etiqueta_efectivo)
        detalle_pagos.addSpacing(30)
        detalle_pagos.addWidget(self.etiqueta_digital)
        detalle_pagos.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(20)
        titulo_total = QLabel("TOTAL VENDIDO", alignment=Qt.AlignCenter)
        titulo_total.setStyleSheet("color: #6B7585; font-size: 12px; font-weight: 600;")
        layout.addWidget(titulo_total)
        layout.addWidget(self.etiqueta_total)
        layout.addWidget(self.etiqueta_cantidad)
        layout.addSpacing(10)
        layout.addLayout(detalle_pagos)
        layout.addStretch()
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        resumen = reportes_repo.resumen_ventas(desde, hasta)
        self.etiqueta_total.setText(formato_pesos(resumen["total"]))
        self.etiqueta_cantidad.setText(f"{resumen['cantidad_ventas']} venta(s)")
        self.etiqueta_efectivo.setText(f"Efectivo: {formato_pesos(resumen['efectivo'])}")
        self.etiqueta_digital.setText(f"Digital: {formato_pesos(resumen['digital'])}")


class PestañaResumenDelDia(QWidget):
    """El reporte de UN día abierto por turno (Mañana/Tarde/Noche, o
    Domingo T1/T2): qué se vendió en cada uno, quién lo cerró y si el
    sobre cuadró. A diferencia de "Por Turno" (que suma un rango entero),
    acá cada fila es un turno real con su cierre -- ver
    turnos_repo.resumen_del_dia."""

    _DIAS = ("Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo")
    _TEXTO_ESTADO = {
        turnos_repo.ESTADO_CERRADO: "Cerrado",
        turnos_repo.ESTADO_EN_CURSO: "En curso",
        turnos_repo.ESTADO_SIN_CERRAR: "⚠ SIN CERRAR",
        turnos_repo.ESTADO_PENDIENTE: "Pendiente",
    }
    _COLOR_ESTADO = {
        turnos_repo.ESTADO_EN_CURSO: "#2F6FED",
        turnos_repo.ESTADO_SIN_CERRAR: "#C62828",
        turnos_repo.ESTADO_PENDIENTE: "#7A869A",
    }
    _COLUMNAS = ["Turno", "Estado", "Cerró", "Ventas", "Kiosko", "Impresiones", "Trámites",
                 "Alquiler de PCs", "PlayStation 5", "Efectivo", "Digital", "Total",
                 "Sobre (contado - esperado)"]

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha = crear_selector_de_fecha()
        self.fecha.dateChanged.connect(self._buscar)
        boton_anterior = QPushButton("◀ Día anterior")
        boton_anterior.clicked.connect(lambda: self._mover_dia(-1))
        boton_siguiente = QPushButton("Día siguiente ▶")
        boton_siguiente.clicked.connect(lambda: self._mover_dia(1))
        boton_hoy = QPushButton("Hoy")
        boton_hoy.clicked.connect(lambda: self.fecha.setDate(QDate.currentDate()))

        filtros = QHBoxLayout()
        filtros.addWidget(QLabel("Día:"))
        filtros.addWidget(self.fecha)
        filtros.addWidget(boton_anterior)
        filtros.addWidget(boton_siguiente)
        filtros.addWidget(boton_hoy)
        filtros.addStretch()

        self.etiqueta_titulo = QLabel()
        self.etiqueta_titulo.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.etiqueta_titulo.setAlignment(Qt.AlignCenter)

        self.tabla = QTableWidget(0, len(self._COLUMNAS))
        self.tabla.setHorizontalHeaderLabels(self._COLUMNAS)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        nota = QLabel(
            "Cada turno cuenta lo que se vendió hasta que se lo cerró (la Noche incluye hasta las 06:00 "
            "del día siguiente). \"Sin contar\": el Admin todavía no cargó cuánto contó del sobre. "
            "Impresiones y Trámites se muestran aparte: no están sumados en Kiosko."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.tabla)
        layout.addWidget(nota)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _mover_dia(self, dias: int):
        self.fecha.setDate(self.fecha.date().addDays(dias))

    def _agregar_fila(self, valores, negrita=False, color_estado=None, color_sobre=None):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        for columna, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            if columna >= 3:
                item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            if negrita or (columna == 1 and color_estado):
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
            if columna == 1 and color_estado:
                item.setForeground(QColor(color_estado))
            if columna == len(valores) - 1 and color_sobre:
                item.setForeground(QColor(color_sobre))
            self.tabla.setItem(fila, columna, item)

    @staticmethod
    def _texto_ventas(cantidad: int, anuladas: int) -> str:
        if anuladas:
            return f"{cantidad} ({anuladas} anulada{'s' if anuladas > 1 else ''})"
        return str(cantidad)

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" no se usa: absorbe la fecha que manda `dateChanged` (ver
        # ControlCierresWindow._ver_detalle en caja_window.py).
        dia = self.fecha.date()
        resumen = turnos_repo.resumen_del_dia(fecha_iso(dia))
        self.etiqueta_titulo.setText(f"{self._DIAS[dia.dayOfWeek() - 1]} {dia.toString('dd/MM/yyyy')}")

        self.tabla.setRowCount(0)
        for turno in resumen["turnos"]:
            if turno["responsables"]:
                cerro = ", ".join(turno["responsables"])
                if turno["cerrado_a"]:
                    cerro += f" · {datetime.fromisoformat(turno['cerrado_a']).strftime('%H:%M')}"
            else:
                cerro = "—"

            tiene_plata = turno["estado"] in (turnos_repo.ESTADO_CERRADO, turnos_repo.ESTADO_EN_CURSO)
            if turno["verificado"]:
                sobre = formato_pesos(turno["diferencia"])
                color_sobre = "#C62828" if turno["diferencia"] < 0 else None
            elif turno["estado"] == turnos_repo.ESTADO_CERRADO:
                sobre, color_sobre = "Sin contar", "#7A869A"
            else:
                sobre, color_sobre = "—", None

            self._agregar_fila(
                [
                    turno["etiqueta"],
                    self._TEXTO_ESTADO[turno["estado"]],
                    cerro,
                    self._texto_ventas(turno["cantidad_ventas"], turno["cantidad_anuladas"]) if tiene_plata else "—",
                    formato_pesos(turno["kiosko"]) if tiene_plata else "—",
                    formato_pesos(turno["impresiones"]) if tiene_plata else "—",
                    formato_pesos(turno["tramites"]) if tiene_plata else "—",
                    formato_pesos(turno["pcs"]) if tiene_plata else "—",
                    formato_pesos(turno["playstation"]) if tiene_plata else "—",
                    formato_pesos(turno["efectivo"]) if tiene_plata else "—",
                    formato_pesos(turno["digital"]) if tiene_plata else "—",
                    formato_pesos(turno["total"]) if tiene_plata else "—",
                    sobre,
                ],
                color_estado=self._COLOR_ESTADO.get(turno["estado"]),
                color_sobre=color_sobre,
            )

        total = resumen["total"]
        self._agregar_fila(
            [
                "TOTAL DEL DÍA", "", "",
                self._texto_ventas(total["cantidad_ventas"], total["cantidad_anuladas"]),
                formato_pesos(total["kiosko"]), formato_pesos(total["impresiones"]),
                formato_pesos(total["tramites"]), formato_pesos(total["pcs"]),
                formato_pesos(total["playstation"]),
                formato_pesos(total["efectivo"]), formato_pesos(total["digital"]),
                formato_pesos(total["total"]), "",
            ],
            negrita=True,
        )


class PestañaPorTurno(QWidget):
    """Desglosa el total vendido en un rango de fechas por turno
    (Mañana/Tarde/Noche), para responder "¿cuánto trabajó la Tarde esta
    semana?" sin tener que sumar a mano los cierres cargados."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True)

        self.tabla = crear_tabla(["Turno", "Total vendido", "Ventas", "Efectivo", "Digital"], estirar=0)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(10)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        filas = reportes_repo.resumen_por_turno(desde, hasta)

        self.tabla.setRowCount(0)
        for fila_datos in filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(fila_datos["turno"].capitalize()))
            self.tabla.setItem(fila, 1, QTableWidgetItem(formato_pesos(fila_datos["total"])))
            self.tabla.setItem(fila, 2, QTableWidgetItem(str(fila_datos["cantidad_ventas"])))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(fila_datos["efectivo"])))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(fila_datos["digital"])))


# Las columnas de plata de la pestaña "Totales", en el orden en que se ven: son
# las claves de cada fila de reportes_repo.resumen_por_origen.
_COLUMNAS_DE_TOTALES = ("kiosko", "impresiones", "tramites", "pcs", "playstation", "total")


class PestañaKioskoVsPCs(QWidget):
    """Desglosa lo facturado en Kiosko, Impresiones, Trámites, Alquiler de PCs y
    PlayStation 5 (ver dominio.NOMBRE_ORIGEN_VENTA) en un rango de fechas,
    agrupado a elección por turno, día, semana o el total del rango completo."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_agrupar = QComboBox()
        self.combo_agrupar.addItem("Total del rango", "rango")
        self.combo_agrupar.addItem("Por Turno", "turno")
        self.combo_agrupar.addItem("Por Día", "dia")
        self.combo_agrupar.addItem("Por Semana", "semana")
        self.combo_agrupar.currentIndexChanged.connect(self._buscar)

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, extras=[("Agrupar:", self.combo_agrupar)], solo_hoy=True
        )

        self.tabla = crear_tabla(
            ["Período", "Kiosko", "Impresiones", "Trámites", "Alquiler de PCs", "PlayStation 5", "Total"],
            estirar=0,
        )

        nota = QLabel("Impresiones y Trámites se muestran aparte: no están sumados en Kiosko.")
        nota.setStyleSheet("color: #7A869A;")

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addSpacing(10)
        layout.addWidget(self.tabla)
        layout.addWidget(nota)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_fila(self, datos: dict, negrita: bool = False):
        """Una fila de la tabla; `datos` es una fila de
        reportes_repo.resumen_por_origen (o una armada igual, ver el TOTAL
        de _buscar)."""
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        for columna, valor in enumerate([
            datos["etiqueta"],
            *(formato_pesos(datos[clave]) for clave in _COLUMNAS_DE_TOTALES),
        ]):
            item = QTableWidgetItem(valor)
            if negrita:
                fuente = item.font()
                fuente.setBold(True)
                item.setFont(fuente)
            self.tabla.setItem(fila, columna, item)

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" no se usa: absorbe el índice que manda
        # `currentIndexChanged` (ver ControlCierresWindow._ver_detalle en
        # caja_window.py).
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        agrupar_por = self.combo_agrupar.currentData()
        filas = reportes_repo.resumen_por_origen(desde, hasta, agrupar_por)

        self.tabla.setRowCount(0)
        for fila_datos in filas:
            self._agregar_fila(fila_datos)

        # Fila TOTAL al pie cuando hay más de un período listado -- con
        # "Total del rango" ya sobraría, es la única fila que hay.
        if agrupar_por != "rango" and len(filas) > 1:
            sumas = {
                clave: sum(fila[clave] for fila in filas)
                for clave in _COLUMNAS_DE_TOTALES
            }
            self._agregar_fila({"etiqueta": "TOTAL", **sumas}, negrita=True)


class PestañaRanking(QWidget):
    """Ranking de TODO lo vendido (kiosko, bonos de PC, de socios y de la
    PlayStation 5, cargas de saldo y trámites) en un rango de fechas, ordenable
    por cantidad o por monto."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_orden = QComboBox()
        self.combo_orden.addItem("Por Cantidad vendida", "cantidad")
        self.combo_orden.addItem("Por Monto ($)", "monto")

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, QDate.currentDate().addMonths(-1),
            extras=[("Ordenar:", self.combo_orden)], estirar=False,
        )

        self.etiqueta_titulo = QLabel()
        self.etiqueta_titulo.setStyleSheet("font-weight: bold; font-size: 14px;")
        self.etiqueta_titulo.setAlignment(Qt.AlignCenter)

        self.tabla = crear_tabla(["Cantidad", "Categoría", "Código", "Descripción", "Importe"], estirar=3)
        # La categoría se muestra entera: con el ancho fijo de siempre, "Bono de
        # PlayStation 5" y "Bono de Socio" se cortaban igual ("Bono de ...") y no
        # se podían distinguir.
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.ResizeToContents)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        orden = self.combo_orden.currentData()

        self.etiqueta_titulo.setText(
            f"Ranking de Ventas del {self.fecha_desde.date().toString('dd/MM/yyyy')} "
            f"al {self.fecha_hasta.date().toString('dd/MM/yyyy')}"
        )

        filas = reportes_repo.ranking_ventas(desde, hasta, orden)
        self.tabla.setRowCount(0)
        for fila_datos in filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(fila_datos["cantidad"])))
            self.tabla.setItem(fila, 1, QTableWidgetItem(fila_datos["categoria"]))
            self.tabla.setItem(fila, 2, QTableWidgetItem(fila_datos["codigo"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(fila_datos["descripcion"]))
            self.tabla.setItem(fila, 4, QTableWidgetItem(formato_pesos(fila_datos["importe"])))
