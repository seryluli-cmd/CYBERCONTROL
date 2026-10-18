"""
reportes_resumen_dia.py
========================
Reportes > Resumen del Día: un día abierto por turno (quién cerró, cuánto se
vendió de cada rubro y si el sobre cuadró) y, abajo, el detalle de todo lo
vendido en el día o en el turno que se toque (ui/reportes_detalle_dia.py).

Se separó de ui/reportes_window.py el 2026-10-18, cuando el detalle lo dejaba
en 600 líneas (CLAUDE.md, regla 12); reportes_window la reexporta con el mismo
nombre.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QFrame, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidget,
    QTableWidgetItem, QHeaderView, QWidget, QSplitter,
)
from PySide6.QtCore import Qt, QDate
from PySide6.QtGui import QColor

from repositories import detalle_dia_repo, turnos_repo
from ui.reportes_detalle_dia import PanelDetalleDelDia
from ui.utils import (
    formato_pesos, manejar_errores, sin_boton_por_defecto, fecha_iso, crear_selector_de_fecha, hoy_del_local,
)


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
        self.fecha = crear_selector_de_fecha(hoy_del_local())
        self.fecha.dateChanged.connect(self._buscar)
        boton_anterior = QPushButton("◀ Día anterior")
        boton_anterior.clicked.connect(lambda: self._mover_dia(-1))
        boton_siguiente = QPushButton("Día siguiente ▶")
        boton_siguiente.clicked.connect(lambda: self._mover_dia(1))
        boton_hoy = QPushButton("Hoy")
        boton_hoy.clicked.connect(lambda: self.fecha.setDate(hoy_del_local()))

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
        # Tocar un turno muestra abajo solo su detalle (ver _al_elegir_fila).
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.itemSelectionChanged.connect(self._al_elegir_fila)
        self.tabla.setAlternatingRowColors(True)
        # Sin la numeración de filas (como en el resto de las tablas, ver ui.utils.crear_tabla):
        # acá además le quitaba lugar a la columna "Cerró".
        self.tabla.verticalHeader().setVisible(False)
        self.tabla.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.tabla.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

        nota = QLabel(
            "Cada turno cuenta lo que se vendió hasta que se lo cerró (la Noche incluye hasta las 06:00 "
            "del día siguiente). \"Sin contar\": el Admin todavía no cargó cuánto contó del sobre. "
            "Impresiones y Trámites se muestran aparte: no están sumados en Kiosko."
        )
        nota.setWordWrap(True)
        nota.setStyleSheet("color: #7A869A;")

        # Aviso (oculto salvo que haga falta) de los cierres hechos este día que
        # quedaron anotados en otro: ver _mostrar_aviso.
        self.aviso = QFrame()
        self.aviso.setObjectName("avisoInformativo")
        self.aviso_titulo = QLabel()
        self.aviso_titulo.setObjectName("avisoTitulo")
        self.aviso_titulo.setWordWrap(True)
        self.aviso_filas = QVBoxLayout()
        self.aviso_filas.setSpacing(4)
        aviso_explicacion = QLabel(
            "El cierre cuenta todo lo vendido desde el cierre anterior y se anota en el día en que "
            "ese período empezó: por eso esa plata no figura en las filas de este día."
        )
        aviso_explicacion.setWordWrap(True)
        aviso_layout = QVBoxLayout(self.aviso)
        aviso_layout.setContentsMargins(14, 10, 14, 10)
        aviso_layout.setSpacing(6)
        aviso_layout.addWidget(self.aviso_titulo)
        aviso_layout.addLayout(self.aviso_filas)
        aviso_layout.addWidget(aviso_explicacion)
        self.aviso.hide()

        arriba = QWidget()
        layout_arriba = QVBoxLayout(arriba)
        layout_arriba.setContentsMargins(0, 0, 0, 0)
        layout_arriba.addWidget(self.etiqueta_titulo)
        layout_arriba.addWidget(self.tabla)
        layout_arriba.addWidget(nota)

        # Abajo, el detalle de lo vendido (ver ui/reportes_detalle_dia.py). La
        # línea entre las dos partes se puede correr con el mouse.
        self.panel_detalle = PanelDetalleDelDia()
        self._detalle = None
        self._turno_de_cada_fila = []
        division = QSplitter(Qt.Vertical)
        division.addWidget(arriba)
        division.addWidget(self.panel_detalle)
        division.setStretchFactor(0, 2)
        division.setStretchFactor(1, 3)
        division.setChildrenCollapsible(False)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.aviso)
        layout.addWidget(division, 1)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _al_elegir_fila(self):
        """El detalle de abajo muestra el turno tocado (o todo el día con la
        fila TOTAL DEL DÍA, o si no hay ninguna elegida)."""
        if self._detalle is None:
            return
        filas = self.tabla.selectionModel().selectedRows()
        turno = None
        if filas and filas[0].row() < len(self._turno_de_cada_fila):
            turno = self._turno_de_cada_fila[filas[0].row()]
        self.panel_detalle.mostrar(self._detalle, turno)

    def _mover_dia(self, dias: int):
        self.fecha.setDate(self.fecha.date().addDays(dias))

    def _mostrar_aviso(self, cierres, dia: QDate):
        """
        Avisa los cierres que se hicieron en `dia` pero quedaron anotados en otro
        día (ver turnos_repo.resumen_del_dia, "cierres_de_otro_dia"), con un botón
        para ir a verlos. Sin eso, un cierre hecho hoy tras varios días sin cerrar
        parece perdido: las filas de hoy salen en cero y su plata está en el día
        viejo. Con la lista vacía el aviso se esconde.
        """
        while self.aviso_filas.count():
            fila = self.aviso_filas.takeAt(0).widget()
            if fila is not None:
                fila.deleteLater()

        if not cierres:
            self.aviso.hide()
            return

        cuando = "Hoy" if dia == hoy_del_local() else "Este día"
        if len(cierres) == 1:
            self.aviso_titulo.setText(f"{cuando} se cerró un turno que quedó anotado en otro día:")
        else:
            self.aviso_titulo.setText(f"{cuando} se cerraron {len(cierres)} turnos que quedaron anotados en otros días:")

        for cierre in cierres:
            dia_anotado = QDate.fromString(cierre["fecha"], "yyyy-MM-dd")
            fecha_texto = dia_anotado.toString("dd/MM/yyyy")
            hora = datetime.fromisoformat(cierre["cerrado_a"]).strftime("%H:%M")
            boton = QPushButton(f"Ver el {fecha_texto}")
            boton.clicked.connect(lambda _=False, destino=dia_anotado: self.fecha.setDate(destino))

            texto = f"•  {cierre['etiqueta']} del {fecha_texto} — cerró {cierre['responsable']} a las {hora}"
            fila = QWidget()
            fila_layout = QHBoxLayout(fila)
            fila_layout.setContentsMargins(0, 0, 0, 0)
            fila_layout.addWidget(QLabel(texto))
            fila_layout.addStretch()
            fila_layout.addWidget(boton)
            self.aviso_filas.addWidget(fila)
        self.aviso.show()

    def _agregar_fila(self, valores, negrita=False, color_estado=None, color_sobre=None):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        for columna, valor in enumerate(valores):
            item = QTableWidgetItem(valor)
            if columna == 2 and valor != "—":
                # "Cerró" es la columna que se estira: si aun así un nombre largo no entra,
                # el texto completo se ve al pasar el mouse.
                item.setToolTip(valor)
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
        # Qué turno es cada fila (None = TOTAL DEL DÍA), para el detalle de abajo.
        self._turno_de_cada_fila = [turno["turno"] for turno in resumen["turnos"]] + [None]
        for turno in resumen["turnos"]:
            if turno["responsables"]:
                cerro = ", ".join(turno["responsables"])
                if turno["cerrado_a"]:
                    cerro += f" · {datetime.fromisoformat(turno['cerrado_a']).strftime('%H:%M')}"
            else:
                cerro = "—"

            texto_estado = self._TEXTO_ESTADO[turno["estado"]]
            if turno["cerrado_otro_dia"]:
                # La hora de "Cerró" sola parecería de este mismo día: se aclara cuál fue.
                texto_estado += f" el {datetime.fromisoformat(turno['cerrado_a']).strftime('%d/%m')}"

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
                    texto_estado,
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

        self._mostrar_aviso(resumen["cierres_de_otro_dia"], dia)
        self._detalle = detalle_dia_repo.detalle_del_dia(fecha_iso(dia))
        self.panel_detalle.mostrar(self._detalle)
