"""
ui/envio_pwa_dialogo.py
=======================
La pantalla "Cierres a la app de gastos" (Configuración ADMIN; solo Admin y solo
en el mostrador): prender o apagar que cada Cierre de Turno se asiente solo en la
app de gastos del dueño (la PWA "Gastos — CyberBIOS"), ver cómo van los envíos,
probar la conexión (y qué usuarios de acá no están escritos igual allá) y
reintentar ya los que fallaron. Las reglas viven en repositories/envio_pwa_repo.py.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QTableWidgetItem, QVBoxLayout

import dominio
from repositories import envio_pwa_repo
from ui.piezas_ventana import (
    TONO_GRIS, TONO_VERDE, agregar_pastilla, cabecera_oscura, panel_blanco, tecla, titulo_de_seccion,
)
from ui.utils import (
    crear_tabla, formato_fecha_hora, formato_pesos, manejar_errores, mostrar_columna_entera, mostrar_info,
    sin_boton_por_defecto,
)

_ESTILO_ERROR = "color: #C62828; font-weight: 600;"
_COLOR_ERROR = QColor("#C62828")
_TEXTO_ESTADO = {
    dominio.ENVIO_PENDIENTE: "Pendiente",
    dominio.ENVIO_ENVIADO: "Enviado",
    dominio.ENVIO_ERROR: "Con error",
}


def _dia(fecha_iso: str) -> str:
    """"2026-10-25" -> "25/10/2026"."""
    return "/".join(reversed(fecha_iso[:10].split("-")))


class _Esperando:
    """Reloj de arena mientras se habla con la app: un pedido puede tardar unos segundos."""

    def __enter__(self):
        QApplication.setOverrideCursor(Qt.WaitCursor)

    def __exit__(self, *_):
        QApplication.restoreOverrideCursor()


class DialogoEnvioPwa(QDialog):
    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.estado = None
        self.setWindowTitle("Cierres a la app de gastos")
        self.resize(780, 620)
        self._armar_interfaz()
        self._actualizar()

    def _armar_interfaz(self):
        self.cabecera = cabecera_oscura(
            "📲", "Cierres a la app de gastos", "Cada Cierre de Turno se asienta solo en Gastos — CyberBIOS"
        )
        self.pastilla = agregar_pastilla(self.cabecera, "APAGADO", TONO_GRIS)

        panel, capa = panel_blanco()
        explicacion = QLabel(
            "Con esto prendido, cada <b>Cierre de Turno</b> (el que confirma la empleada, el que se hace en "
            "ausencia y el forzoso) se manda solo a la app de gastos como el cierre de caja de ese turno, a "
            "nombre de la <b>responsable de la caja</b>. Si no hay internet queda pendiente y se manda solo "
            "cuando vuelve: el cierre de acá nunca espera.<br>"
            "El nombre de cada usuario tiene que estar escrito <b>igual</b> en las dos apps (mayúsculas "
            "incluidas); las contraseñas no hace falta que coincidan."
        )
        explicacion.setWordWrap(True)
        capa.addWidget(explicacion)

        fila_interruptor = QHBoxLayout()
        self.etiqueta_interruptor = QLabel()
        self.tecla_interruptor = tecla("PRENDER", self._prender_o_apagar, "teclaAzul")
        fila_interruptor.addWidget(self.etiqueta_interruptor, 1)
        fila_interruptor.addWidget(self.tecla_interruptor)
        capa.addLayout(fila_interruptor)

        self.etiqueta_estado = QLabel()
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_error = QLabel()
        self.etiqueta_error.setStyleSheet(_ESTILO_ERROR)
        self.etiqueta_error.setWordWrap(True)
        capa.addWidget(self.etiqueta_estado)
        capa.addWidget(self.etiqueta_error)

        capa.addWidget(titulo_de_seccion("Últimos cierres"))
        self.tabla = crear_tabla(["Turno", "Responsable", "Total", "Estado", "Detalle"], estirar=4,
                                 por_filas=True, una_sola=True)
        capa.addWidget(self.tabla, 1)

        pie = QHBoxLayout()
        pie.addWidget(tecla("PROBAR LA CONEXIÓN", self._probar_conexion))
        pie.addWidget(tecla("REINTENTAR AHORA", self._reintentar, "teclaAzul"))
        pie.addStretch()
        pie.addWidget(tecla("CERRAR", self.close, "teclaRoja"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.cabecera)
        layout.addWidget(panel, 1)
        layout.addLayout(pie)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _actualizar(self):
        estado = envio_pwa_repo.estado()
        self.estado = estado
        prendido = estado["activado"]
        self.pastilla.setText("PRENDIDO" if prendido else "APAGADO")
        self.pastilla.setProperty("tono", TONO_VERDE if prendido else TONO_GRIS)
        # Qt no vuelve a pintar sola una propiedad de estilo que cambió.
        self.pastilla.style().unpolish(self.pastilla)
        self.pastilla.style().polish(self.pastilla)
        self.etiqueta_interruptor.setText(
            "<b>Prendido:</b> cada cierre nuevo se manda solo." if prendido
            else "<b>Apagado:</b> no se manda nada (lo que quedó pendiente espera)."
        )
        self.tecla_interruptor.setText("APAGAR" if prendido else "PRENDER")
        ultimo = formato_fecha_hora(estado["ultimo_enviado"]) if estado["ultimo_enviado"] else "todavía ninguno"
        self.etiqueta_estado.setText(
            f"Último cierre mandado: <b>{ultimo}</b> · Pendientes: <b>{estado['pendientes']}</b> · "
            f"Con error: <b>{estado['con_error']}</b> · Enviados: <b>{estado['enviados']}</b>"
        )
        self.etiqueta_error.setText(estado["ultimo_error"] or "")
        self.etiqueta_error.setVisible(bool(estado["ultimo_error"]))

        self.tabla.setRowCount(0)
        for fila in estado["ultimos"]:
            numero = self.tabla.rowCount()
            self.tabla.insertRow(numero)
            if fila["estado"] == dominio.ENVIO_ENVIADO:
                detalle = f"Mandado el {formato_fecha_hora(fila['enviado_en'])}"
            else:
                detalle = fila["ultimo_error"] or ""
            textos = [
                f"{fila['turno_label']} {_dia(fila['fecha'])}", fila["responsable"], formato_pesos(fila["total"]),
                _TEXTO_ESTADO.get(fila["estado"], fila["estado"]), detalle,
            ]
            for columna, texto in enumerate(textos):
                item = QTableWidgetItem(texto)
                item.setToolTip(texto)  # el porqué de un error entero, aunque en la celda no entre
                if fila["estado"] == dominio.ENVIO_ERROR:
                    item.setForeground(_COLOR_ERROR)
                self.tabla.setItem(numero, columna, item)
        mostrar_columna_entera(self.tabla, 0)  # "Tarde 26/10/2026" entero, sin "..."

    @manejar_errores
    def _prender_o_apagar(self):
        prendido = not self.estado["activado"]
        envio_pwa_repo.activar(self.usuario["id"], prendido)
        self._actualizar()
        if prendido:
            mostrar_info(
                self, "Cierres a la app de gastos",
                "Listo: desde ahora cada Cierre de Turno se manda solo a la app de gastos.\n"
                "Los cierres de antes de este momento no se mandan.",
            )

    @manejar_errores
    def _probar_conexion(self):
        with _Esperando():
            resultado = envio_pwa_repo.probar_conexion()
        nombres = ", ".join(resultado["nombres_app"]) or "(ninguno)"
        if resultado["faltan"]:
            mostrar_info(
                self, "Conexión OK, pero faltan nombres",
                f"Se pudo entrar a la app de gastos. Allá están: {nombres}.\n\n"
                f"Estos usuarios de acá NO están escritos igual allá: {', '.join(resultado['faltan'])}.\n"
                "Sus cierres se verían sin color y fuera de las estadísticas: escribilos igual en las dos apps.",
            )
        else:
            mostrar_info(
                self, "Conexión OK",
                f"Se pudo entrar a la app de gastos. Allá están: {nombres}.\n"
                "Todos los usuarios de acá están escritos igual.",
            )

    @manejar_errores
    def _reintentar(self):
        if not self.estado["activado"]:
            mostrar_info(self, "Reintentar ahora", "El envío está apagado: prendelo para mandar lo pendiente.")
            return
        with _Esperando():
            resultado = envio_pwa_repo.reintentar_ahora()
        self._actualizar()
        mostrar_info(
            self, "Reintentar ahora",
            f"Enviados: {resultado['enviados']} · Con error: {resultado['con_error']}.",
        )
