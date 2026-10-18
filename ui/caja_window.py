"""
caja_window.py
================
Pantallas relacionadas con la plata del día a día:

- CajaWindow: consulta rápida de "cómo viene la caja" en cualquier
  momento, sin cerrar nada.
- CierreTurnoWindow: el cierre real de turno. Calcula cuánto tiene que
  retirar la empleada (dejando el cambio fijo -el "fondo de cambio"- para
  el próximo turno) y lo deja guardado.

Las dos pantallas para controlar los cierres después (ControlCierresWindow y
DialogoDetalleCierre) viven en ui/control_cierres_window.py desde el
2026-10-18 y se reexportan acá con el mismo nombre.

Desde el 2026-10-18 cada cierre es el de una caja con número (ver
repositories/relevo_repo.py): las pantallas muestran el número y quién la tenía.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt
from PySide6.QtGui import QFont

import dominio
from repositories import turnos_repo
from ui.control_cierres_window import ControlCierresWindow, DialogoDetalleCierre  # noqa: F401 (API de main_window y las pruebas)
from ui.utils import (
    formato_pesos, mostrar_info, confirmar, manejar_errores, aplicar_clase, sin_boton_por_defecto,
)


def _texto_desglose(efectivo: float, digital: float) -> str:
    """"$X ef. + $Y dig." -- una sola línea para mostrar el desglose de un
    origen (Kiosko, Alquiler de PCs o PlayStation 5) sin ocupar dos etiquetas
    por cada uno, ver CajaWindow/CierreTurnoWindow."""
    return f"{formato_pesos(efectivo)} ef. + {formato_pesos(digital)} dig."


def _titulo_de_la_caja(resumen) -> str:
    """"Caja Nº 12 de Lucía · " si hay una caja abierta (ver
    turnos_repo.resumen_turno_actual); si no, nada."""
    if resumen["caja_numero"] is None:
        return ""
    return f"Caja Nº {resumen['caja_numero']} de {resumen['responsable']} · "


def _etiqueta_dato(titulo, valor_texto, destacado=False):
    """Un dato de las pantallas de caja: título gris arriba y valor grande
    abajo (en azul si `destacado`, como el TOTAL). Devuelve (layout,
    etiqueta_del_valor) para poder actualizarla."""
    contenedor = QVBoxLayout()
    titulo_lbl = QLabel(titulo)
    titulo_lbl.setStyleSheet("color: #6B7585;")
    valor_lbl = QLabel(valor_texto)
    fuente = QFont()
    fuente.setPointSize(14)
    fuente.setBold(True)
    valor_lbl.setFont(fuente)
    if destacado:
        valor_lbl.setStyleSheet("color: #2F6FED;")
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

    def se_puede_cerrar_sola(self) -> bool:
        """Es solo una consulta: el cierre forzoso de la caja la puede cerrar
        (ver MainWindow._hay_un_cobro_a_medias)."""
        return True

    def _armar_interfaz(self):
        layout_fondo, self.valor_fondo = _etiqueta_dato("CAJA INICIAL (Cambio Fijo)", "")
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
        self.titulo.setText(f"CAJA — {_titulo_de_la_caja(resumen)}Turno {resumen['turno_actual_label']}")
        # Con una caja abierta, el cambio con que arrancó (lo que se contó); sin
        # caja, el Cambio Fijo. La Caja Actual sale de ahí.
        self.valor_fondo.setText(formato_pesos(resumen["cambio_inicial"]))
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
        # "Cambio Fijo" es como lo llama el dueño en esta pantalla (es lo que las
        # empleadas le mandan como resumen del turno); por dentro sigue siendo el
        # "fondo de cambio" (`fondo_cambio`).
        layout_fondo, self.valor_fondo = _etiqueta_dato("Cambio Fijo", "")
        layout_efectivo, self.valor_efectivo = _etiqueta_dato("Efectivo", "")
        layout_digital, self.valor_digital = _etiqueta_dato("Digital", "")
        # Efectivo + Digital de Kiosko, PCs y PlayStation 5; las impresiones no se
        # suman aparte porque ya están dentro de Kiosko.
        layout_total, self.valor_total = _etiqueta_dato("TOTAL", "", destacado=True)
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
        # Las impresiones no son un origen aparte: ya están sumadas dentro de
        # Kiosko (y de su "ef. + dig."), por eso el título lo aclara -- así nadie
        # las cuenta dos veces al sumar los renglones a mano.
        layout_impresiones, self.valor_impresiones = _etiqueta_dato("Impresiones (incluidas en Kiosko)", "")
        # Igual con los trámites: se cobran como una venta de Kiosko, ya están en el TOTAL.
        layout_tramites, self.valor_tramites = _etiqueta_dato("Trámites (incluidos en Kiosko)", "")

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
            [(layout_fondo, layout_retirar), (layout_efectivo, layout_digital),
             (layout_total, QVBoxLayout()),
             (layout_kiosko, layout_pcs), (layout_playstation, layout_impresiones),
             (layout_tramites, QVBoxLayout())],
            "Retirá el efectivo indicado y guardalo en el sobre. Dejá el cambio "
            "fijo en el cajón para que arranque el próximo turno.",
            botones,
        )

    @manejar_errores
    def _refrescar_vista_previa(self):
        resumen = turnos_repo.resumen_turno_actual()
        self.titulo.setText(f"Cierre de Turno — {_titulo_de_la_caja(resumen)}{resumen['turno_actual_label']}")
        self.valor_fondo.setText(formato_pesos(resumen["cambio_inicial"]))
        self.valor_efectivo.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))
        self.valor_total.setText(formato_pesos(resumen["ventas_total"]))
        self.valor_retirar.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_kiosko.setText(_texto_desglose(resumen["kiosko_efectivo"], resumen["kiosko_digital"]))
        self.valor_pcs.setText(_texto_desglose(resumen["pcs_efectivo"], resumen["pcs_digital"]))
        self.valor_playstation.setText(
            _texto_desglose(resumen["playstation_efectivo"], resumen["playstation_digital"])
        )
        self.valor_impresiones.setText(formato_pesos(resumen["impresiones"]))
        self.valor_tramites.setText(formato_pesos(resumen["tramites"]))

    @manejar_errores
    def _cerrar_turno(self):
        if not confirmar(self, "Confirmar cierre",
                          "¿Confirmás el cierre de este turno? No se puede deshacer."):
            return
        resultado = turnos_repo.cerrar_turno(self.usuario["id"])
        self.turno_cerrado = True
        caja = f"Caja Nº {resultado['caja_numero']} · " if resultado["caja_numero"] is not None else ""
        ausencia = ""
        if resultado["responsable"] is not None and resultado["responsable"] != self.usuario["nombre"]:
            ausencia = f"Queda anotado que la cerraste vos, en ausencia de {resultado['responsable']}.\n\n"
        mostrar_info(
            self, "Turno cerrado",
            f"{caja}Turno {resultado['turno_label']} cerrado correctamente.\n\n"
            f"{ausencia}"
            f"Retirá: {formato_pesos(resultado['monto_a_retirar'])} para el sobre y guardalo en la caja fuerte.\n"
            f"(dejando {formato_pesos(resultado['cambio_que_queda'])} de cambio fijo para el próximo turno)\n\n"
            "Ahora volvés a la pantalla de ingreso: quien te releve tiene que entrar con su propio "
            "usuario. Si tu reemplazo no llegó, volvé a entrar con el tuyo y seguí vendiendo."
        )
        self.close()
