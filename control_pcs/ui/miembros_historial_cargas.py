"""
miembros_historial_cargas.py
============================
HISTORIAL DE CARGAS (pedido del dueño, 2026-10-24): las cargas de saldo a los
socios, de la más nueva a la más vieja, con a qué socio, cuánto tiempo, cuánta
plata y cómo se pagó, el bono (o "Monto libre"), quién la cargó y la fecha y
hora. Se abre con el botón "Historial de Cargas" de la ventana de Miembros, al
lado de "Cargar Saldo", y lo puede usar cualquier operador (como Miembros).

Con un socio marcado en la lista de Miembros abre con las cargas de ese socio
(del último año); sin ninguno, con las de todos desde el 1 del mes. Filtros:
Desde/Hasta con "Solo Hoy" (días del local, de 06:00 a 06:00) y un buscador
por socio que filtra mientras se escribe. Abajo, los totales sin las
anuladas, "Bajar a Excel" (ui/excel.py) e Imprimir (vista previa de
ui/imprimir.py).

"Anular carga" (pedido del dueño, 2026-11-02, solo si quien la abrió es Admin): con
una carga elegida, la anula y le saca el tiempo al socio, en una sola vez (la
empleada cargó dos bonos en vez de uno). Lo hace anular_carga.py.

Qué entra y qué no lo decide historial_cargas_repo; acá solo se muestra.
"""

from datetime import datetime

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout

import dominio
from control_pcs.repositories import historial_cargas_repo
from control_pcs.ui.anular_carga import anular_carga_con_cartel
from ui import excel, imprimir
from ui.utils import (
    aplicar_clase, armar_filtro_por_fechas, crear_tabla, formato_fecha_hora, formato_pesos, formato_tiempo,
    hoy_del_local, manejar_errores, rango_de_fechas, sin_boton_por_defecto,
)

TITULO = "Historial de Cargas"
COLUMNAS = ["Fecha y hora", "Socio", "Tiempo", "Plata", "Pago", "Bono", "Operador", "Estado"]
COLUMNA_SOCIO = 1
COLUMNA_ESTADO = 7
_A_LA_DERECHA = (2, 3)
_COLOR_ANULADA = QColor("#C62828")


def _estado(carga) -> str:
    if not carga["anulada"]:
        return ""
    texto = f"ANULADA por {carga['anulada_por']}" if carga["anulada_por"] else "ANULADA"
    if carga["anulada_fecha"]:
        texto += f" el {formato_fecha_hora(carga['anulada_fecha'])}"
    if carga["anulada_motivo"]:
        texto += f": {carga['anulada_motivo']}"
    return texto


def _valores(carga) -> list:
    """Lo que va en cada columna, igual en pantalla y en la hoja impresa."""
    return [
        formato_fecha_hora(carga["fecha"]),
        carga["socio"],
        formato_tiempo(carga["minutos"] * 60),
        formato_pesos(carga["monto"]),
        carga["medio"],
        carga["bono"] or "Monto libre",
        carga["operador"],
        _estado(carga),
    ]


def _texto_totales(suma) -> str:
    cargas = "1 carga" if suma["cantidad"] == 1 else f"{suma['cantidad']} cargas"
    texto = f"{cargas} · {formato_tiempo(suma['minutos'] * 60)} · {formato_pesos(suma['monto'])}"
    if suma["anuladas"]:
        anuladas = "1 anulada" if suma["anuladas"] == 1 else f"{suma['anuladas']} anuladas"
        texto += f"  (sin contar {anuladas})"
    return texto


class VentanaHistorialCargas(QDialog):
    def __init__(self, parent=None, miembro=None, usuario=None):
        """`miembro`: el socio marcado en Miembros (o None, para ver todos).
        `usuario`: quien abrió la ventana; si es Admin, puede anular cargas."""
        super().__init__(parent)
        self._cargas = []
        self._usuario = usuario
        # Con un socio marcado se filtra por SU id: buscando el texto, "ana"
        # traería también a "mariana". Si se cambia el buscador, pasa a buscar
        # por el texto.
        self._miembro = miembro
        self.setWindowTitle(TITULO)
        self.resize(1150, 680)
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.campo_socio = QLineEdit()
        self.campo_socio.setPlaceholderText("Usuario o nombre del socio...")
        self.campo_socio.setClearButtonEnabled(True)
        self.campo_socio.setMinimumWidth(220)
        hoy = hoy_del_local()
        if self._miembro is not None:
            self.campo_socio.setText(self._miembro["usuario"])
            desde_inicial = hoy.addYears(-1)
        else:
            desde_inicial = QDate(hoy.year(), hoy.month(), 1)
        self.campo_socio.textChanged.connect(self._al_cambiar_el_buscador)
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, desde_inicial, extras=[("Socio:", self.campo_socio)],
            solo_hoy=True, dias_del_local=True,
        )

        self.tabla = crear_tabla(COLUMNAS, estirar=COLUMNA_ESTADO, por_filas=True)

        self.etiqueta_totales = QLabel()
        self.etiqueta_totales.setStyleSheet("font-weight: bold; font-size: 13px;")
        self.boton_imprimir = QPushButton("🖨️  Imprimir")
        self.boton_imprimir.setToolTip("Abre la vista previa para imprimir lo que se ve (o guardarlo en PDF).")
        aplicar_clase(self.boton_imprimir, "primario")
        self.boton_imprimir.clicked.connect(self._imprimir)
        # Bajar a Excel (pedido del dueño, 2026-10-24): lo mismo que se ve, con
        # números que Excel suma (ver ui/excel.py).
        self.boton_excel = QPushButton("📊  Bajar a Excel")
        self.boton_excel.clicked.connect(self._bajar_a_excel)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        # Anular una carga (por ejemplo, un bono cargado dos veces) es del Admin: a
        # los demás ni se les muestra (el repo lo vuelve a exigir).
        self.boton_anular = QPushButton("Anular carga")
        self.boton_anular.setToolTip(
            "Anula la carga elegida: saca la plata de la caja y el tiempo del socio, las dos cosas juntas."
        )
        aplicar_clase(self.boton_anular, "peligro")
        self.boton_anular.clicked.connect(self._anular_carga)
        self.boton_anular.setVisible(self._usuario is not None and dominio.es_admin(self._usuario))
        self.boton_anular.setEnabled(False)
        self.tabla.itemSelectionChanged.connect(self._al_elegir_una_carga)
        fila_abajo = QHBoxLayout()
        fila_abajo.addWidget(self.etiqueta_totales, 1)
        fila_abajo.addWidget(self.boton_anular)
        fila_abajo.addWidget(self.boton_excel)
        fila_abajo.addWidget(self.boton_imprimir)
        fila_abajo.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addLayout(filtros)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_abajo)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _al_cambiar_el_buscador(self, texto):
        if self._miembro is not None and texto != self._miembro["usuario"]:
            self._miembro = None
        self._buscar()

    def _carga_elegida(self):
        """La carga de la fila elegida, o None si no hay ninguna."""
        fila = self.tabla.currentRow()
        if fila < 0 or fila >= len(self._cargas) or not self.tabla.selectionModel().hasSelection():
            return None
        return self._cargas[fila]

    def _al_elegir_una_carga(self):
        carga = self._carga_elegida()
        self.boton_anular.setEnabled(carga is not None and not carga["anulada"] and carga["venta_id"] is not None)

    @manejar_errores
    def _anular_carga(self):
        carga = self._carga_elegida()
        if carga is None:
            return
        if anular_carga_con_cartel(self, self._usuario, carga["venta_id"]):
            self._buscar()

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        miembro_id = self._miembro["id"] if self._miembro is not None else None
        self._cargas = historial_cargas_repo.listar_cargas(desde, hasta, self.campo_socio.text(), miembro_id)
        self.tabla.setRowCount(len(self._cargas))
        for fila, carga in enumerate(self._cargas):
            for columna, valor in enumerate(_valores(carga)):
                celda = QTableWidgetItem(valor)
                if columna in _A_LA_DERECHA:
                    celda.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                if carga["anulada"]:
                    celda.setForeground(_COLOR_ANULADA)
                self.tabla.setItem(fila, columna, celda)
        for columna in range(len(COLUMNAS)):
            if columna != COLUMNA_ESTADO:
                self.tabla.resizeColumnToContents(columna)
        self.etiqueta_totales.setText(_texto_totales(historial_cargas_repo.totales(self._cargas)))
        self.boton_imprimir.setEnabled(bool(self._cargas))
        self.boton_excel.setEnabled(bool(self._cargas))
        # La fila elegida puede seguir elegida con otros datos (la que se acaba de anular).
        self._al_elegir_una_carga()

    def _subtitulo(self) -> str:
        desde, hasta = (fecha.date().toString("dd/MM/yyyy") for fecha in (self.fecha_desde, self.fecha_hasta))
        texto = f"Del {desde} al {hasta}" if desde != hasta else f"Del {desde}"
        socio = self.campo_socio.text().strip()
        if socio:
            texto += f" · socio: {socio}"
        return f"{texto} · {_texto_totales(historial_cargas_repo.totales(self._cargas))}"

    def html_para_imprimir(self, impreso=None) -> str:
        filas = [(_valores(carga), carga["anulada"]) for carga in self._cargas]
        return imprimir.html_del_listado(TITULO, self._subtitulo(), COLUMNAS, filas,
                                         a_la_derecha=_A_LA_DERECHA, impreso=impreso)

    def _imprimir(self):
        if self._cargas:
            imprimir.vista_previa(self, self.html_para_imprimir(), TITULO)

    def datos_para_excel(self):
        """(columnas, filas, totales) para excel.guardar_xlsx: los mismos renglones
        que la tabla, con la fecha, el tiempo y la plata como números."""
        columnas = list(zip(COLUMNAS, (excel.FECHA_HORA, excel.TEXTO, excel.HORAS, excel.PESOS,
                                        excel.TEXTO, excel.TEXTO, excel.TEXTO, excel.TEXTO)))
        filas = [
            [datetime.fromisoformat(carga["fecha"]), carga["socio"], carga["minutos"], carga["monto"],
             carga["medio"], carga["bono"] or "Monto libre", carga["operador"], _estado(carga)]
            for carga in self._cargas
        ]
        suma = historial_cargas_repo.totales(self._cargas)
        cargas = "1 carga" if suma["cantidad"] == 1 else f"{suma['cantidad']} cargas"
        totales = ["TOTAL", cargas, suma["minutos"], suma["monto"], None, None, None,
                   "sin las anuladas" if suma["anuladas"] else None]
        return columnas, filas, totales

    @manejar_errores
    def _bajar_a_excel(self):
        if not self._cargas:
            return
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        excel.bajar_a_excel(self, excel.nombre_de_archivo(TITULO, desde, hasta), TITULO, *self.datos_para_excel())
