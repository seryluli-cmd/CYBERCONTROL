"""
caja_window.py
================
Pantallas relacionadas con la plata del día a día:

- CajaWindow: consulta rápida de "cómo viene la caja" en cualquier
  momento, sin cerrar nada.
- CierreTurnoWindow: el cierre real de turno. Calcula cuánto tiene que
  retirar la empleada (dejando el cambio fijo -el "fondo de cambio"- para
  el próximo turno) y lo deja guardado. Su resumen es la tarjeta de
  ui/tarjeta_cierre.py, la misma que muestra Control de Cierres para cada
  cierre ya hecho.

Las dos pantallas para controlar los cierres después (ControlCierresWindow y
DialogoDetalleCierre) viven en ui/control_cierres_window.py desde el
2026-10-18 y se reexportan acá con el mismo nombre.

Desde el 2026-10-18 cada cierre es el de una caja con número (ver
repositories/relevo_repo.py): las pantallas muestran el número y quién la tenía.
"""

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton
from PySide6.QtCore import Qt

import dominio
from control_pcs.repositories import cuentas_pc_repo
from repositories import turnos_repo
from ui.control_cierres_window import ControlCierresWindow, DialogoDetalleCierre  # noqa: F401 (API de main_window y las pruebas)
from ui.tarjeta_cierre import (
    TarjetaCierreDeTurno, armar_filas, armar_renglon_de_reservas, etiqueta_dato, mostrar_desglose_por_negocio,
    titulo_de_la_caja,
)
from ui.utils import (
    formato_pesos, mostrar_info, confirmar, manejar_errores, aplicar_clase, sin_boton_por_defecto,
)


class _PantallaDeCaja(QDialog):
    """La pantalla Caja: un título centrado, los datos de a dos por fila (con la
    misma grilla que el Cierre de Turno, ver ui/tarjeta_cierre.py), una nota en
    gris y los botones abajo."""

    def _armar_cuerpo(self, filas_de_datos, texto_nota, botones):
        """
        Arma la pantalla. El título queda en `self.titulo` para que la
        subclase lo complete al refrescar.

        - `filas_de_datos`: lista de pares de layouts hechos con `etiqueta_dato`.
        - `botones`: el layout con los botones, ya armado.
        """
        self.titulo = QLabel()
        self.titulo.setStyleSheet("font-size: 16px; font-weight: bold;")
        self.titulo.setAlignment(Qt.AlignCenter)

        nota = QLabel(texto_nota)
        nota.setWordWrap(True)
        nota.setStyleSheet("color: gray; font-style: italic;")
        self.nota = nota

        layout = QVBoxLayout()
        layout.addWidget(self.titulo)
        armar_filas(layout, filas_de_datos)
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
        self.resize(460, 450)
        self._armar_interfaz()
        self._refrescar()

    def se_puede_cerrar_sola(self) -> bool:
        """Es solo una consulta: el cierre forzoso de la caja la puede cerrar
        (ver MainWindow._hay_un_cobro_a_medias)."""
        return True

    def _armar_interfaz(self):
        # Parecida al Cierre de Turno (pedido del dueño, 2026-10-20: eligió la opción 1 entre
        # tres maquetas): mismos renglones y orden, y al final TOTAL | CAJA ACTUAL. Se sacó el
        # cartel azul de "Suma Total": el TOTAL ya está en la última línea.
        layout_fondo, self.valor_fondo = etiqueta_dato("CAJA INICIAL (Cambio Fijo)", "")
        layout_actual, self.valor_actual = etiqueta_dato(
            "CAJA ACTUAL (solo efectivo)", "",
            color_titulo="#000000", negrita_titulo=True, color_valor="#2FB457",
        )
        # Debajo del monto, para que no se confunda con el TOTAL (la Caja Actual SÍ suma el
        # Cambio, el TOTAL no): mismo gris itálico que la nota del Cierre de Turno.
        aclaracion = QLabel("Incluye el cambio")
        aclaracion.setStyleSheet("color: gray; font-style: italic;")
        layout_actual.addWidget(aclaracion)
        layout_ventas, self.valor_ventas = etiqueta_dato("Efectivo", "")
        layout_digital, self.valor_digital = etiqueta_dato("Digital", "")
        layout_total, self.valor_total = etiqueta_dato(
            "TOTAL (EFECTIVO + DIGITAL)", "", destacado=True, color_titulo="#000000", negrita_titulo=True,
        )
        layout_kiosko, self.valor_kiosko = etiqueta_dato(dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_KIOSKO], "")
        layout_impresiones, self.valor_impresiones = etiqueta_dato("Impresiones", "")
        layout_tramites, self.valor_tramites = etiqueta_dato("Trámites", "")
        layout_pcs, self.valor_pcs = etiqueta_dato(dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_ALQUILER_PCS], "")
        layout_playstation, self.valor_playstation = etiqueta_dato(
            dominio.NOMBRE_ORIGEN_VENTA[dominio.ORIGEN_PLAYSTATION], ""
        )
        # Las reservas, en su renglón, como en el Cierre de Turno (ver ui/tarjeta_cierre.py).
        layout_reservas, self.valor_reservas, self.detalle_reservas = armar_renglon_de_reservas()
        layout_pcs.addStretch()
        # La última línea con más aire arriba, igual que en el Cierre de Turno (ver ui/tarjeta_cierre.py).
        for ultima_linea in (layout_total, layout_actual):
            ultima_linea.setContentsMargins(0, 28, 0, 0)
        # El lado de la Caja Actual tiene un renglón más ("Incluye el cambio"): sin esto el TOTAL se
        # estira y su monto queda más abajo que el de al lado.
        layout_total.addStretch()

        boton_refrescar = QPushButton("Actualizar")
        boton_refrescar.clicked.connect(self._refrescar)
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)
        botones = QHBoxLayout()
        botones.addWidget(boton_refrescar)
        botones.addStretch()
        botones.addWidget(boton_salir)

        self._armar_cuerpo(
            [(layout_fondo, QVBoxLayout()), (layout_ventas, layout_digital),
             (layout_kiosko, layout_impresiones), (layout_tramites, layout_playstation),
             (layout_pcs, layout_reservas),
             (layout_total, layout_actual)],
            "",  # esta pantalla no lleva nota abajo
            botones,
        )
        self.nota.hide()

    @manejar_errores
    def _refrescar(self):
        resumen = turnos_repo.resumen_turno_actual()
        self.titulo.setText(f"CAJA — {titulo_de_la_caja(resumen)}Turno {resumen['turno_actual_label']}")
        # Con una caja abierta, el cambio con que arrancó (lo que se contó); sin
        # caja, el Cambio Fijo. La Caja Actual sale de ahí.
        self.valor_fondo.setText(formato_pesos(resumen["cambio_inicial"]))
        self.valor_actual.setText(formato_pesos(resumen["caja_actual"]))
        self.valor_ventas.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_digital.setText(formato_pesos(resumen["ventas_digital"]))
        self.valor_total.setText(formato_pesos(resumen["ventas_total"]))
        mostrar_desglose_por_negocio(self, resumen)


class CierreTurnoWindow(QDialog):
    """Cierre real del turno: lo puede hacer cualquier usuario logueado
    (Admin o Empleada) para cerrar SU turno en curso. El resumen es la
    TarjetaCierreDeTurno (ui/tarjeta_cierre.py), la misma con que Control de
    Cierres muestra después cada cierre ya hecho."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        # En True apenas se confirma el cierre (ver _cerrar_turno) -- lo
        # consulta MainWindow._abrir_cierre_turno después de exec() para
        # saber si corresponde volver sola al Login (ver ese método).
        self.turno_cerrado = False
        self.setWindowTitle("Cierre de Turno")
        self.resize(460, 490)
        self._armar_interfaz()
        self._refrescar_vista_previa()

    def _armar_interfaz(self):
        self.tarjeta = TarjetaCierreDeTurno()
        # Lo que quedó sin cobrar en las Cuentas de las PCs (pedido del dueño,
        # 2026-10-25): no entra en este cierre (nunca se cobró) y no lo frena, pero
        # quien cierra y quien entra tienen que saberlo.
        self.aviso_cuentas = QLabel("")
        self.aviso_cuentas.setWordWrap(True)
        self.aviso_cuentas.setStyleSheet(
            "background: #FFF0FA; border: 2px solid #FF3EC8; border-radius: 8px; padding: 6px 8px; color: #1E2330;"
        )
        self.aviso_cuentas.setVisible(False)

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
        layout.addWidget(self.tarjeta)
        layout.addWidget(self.aviso_cuentas)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _refrescar_vista_previa(self):
        self.tarjeta.mostrar(turnos_repo.resumen_turno_actual())
        cuentas = cuentas_pc_repo.cuentas_abiertas()
        self.aviso_cuentas.setVisible(bool(cuentas))
        if cuentas:
            renglones = [
                f"{cuenta['estacion']}: {formato_pesos(cuenta['total'])}"
                + (f" ({cuenta['nombre']})" if cuenta["nombre"] else "") + f", anotó {cuenta['abrio']}"
                for cuenta in cuentas
            ]
            self.aviso_cuentas.setText(
                "💳 Quedan cuentas de PCs sin cobrar (no entran en este cierre):\n" + "\n".join(renglones)
            )
            # Con el aviso, la ventana crece lo que haga falta: si no, aprieta la tarjeta y
            # los importes de abajo se cortan.
            self.resize(self.width(), max(self.height(), self.sizeHint().height()))

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
