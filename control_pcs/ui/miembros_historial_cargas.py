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
anuladas, y el botón Imprimir (vista previa de ui/imprimir.py).

Qué entra y qué no lo decide historial_cargas_repo; acá solo se muestra.
"""

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout

from control_pcs.repositories import historial_cargas_repo
from ui import imprimir
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
    def __init__(self, parent=None, miembro=None):
        """`miembro`: el socio marcado en Miembros (o None, para ver todos)."""
        super().__init__(parent)
        self._cargas = []
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
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        fila_abajo = QHBoxLayout()
        fila_abajo.addWidget(self.etiqueta_totales, 1)
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
