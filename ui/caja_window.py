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

Desde el 2026-10-26 las dos tienen el diseño de Configuración ADMIN (el dueño las vio
"muy vulgares" y pidió un diseño de alto nivel): cabecera oscura, las dos cifras que
importan en grande y la tabla de dónde vino la plata (ui/tarjeta_cierre.py). Muestran
los mismos datos que antes y los botones hacen lo mismo.
"""

from datetime import datetime

from PySide6.QtWidgets import QDialog, QVBoxLayout, QHBoxLayout, QLabel

from control_pcs.repositories import cuentas_pc_repo
from control_pcs.ui.cuenta_pc_dialogos import DialogoCobrarAntesDelCierre
from repositories import turnos_repo
from ui.control_cierres_window import ControlCierresWindow, DialogoDetalleCierre  # noqa: F401 (API de main_window y las pruebas)
from ui.envio_pwa_progreso import DialogoEnviandoCierre
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_VERDE, agregar_pastilla, cabecera_oscura, cifra_destacada, tecla,
)
from ui.tarjeta_cierre import TablaDeNegocios, TarjetaCierreDeTurno, detalle_de_la_cabecera
from ui.utils import formato_pesos, mostrar_info, confirmar, manejar_errores, sin_boton_por_defecto


class CajaWindow(QDialog):
    """Consulta de caja en vivo: cómo viene el turno actual."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Caja")
        self.resize(600, 590)
        self._armar_interfaz()
        self._refrescar()

    def se_puede_cerrar_sola(self) -> bool:
        """Es solo una consulta: el cierre forzoso de la caja la puede cerrar
        (ver MainWindow._hay_un_cobro_a_medias)."""
        return True

    def _armar_interfaz(self):
        self.cabecera = cabecera_oscura("💵", "Caja")
        # A qué hora se tomaron los números: la pantalla no se actualiza sola.
        self.pastilla_hora = agregar_pastilla(self.cabecera, "", TONO_GRIS)

        # Los mismos datos que el Cierre de Turno (pedido del dueño, 2026-10-20), con
        # CAJA ACTUAL en vez de A RETIRAR. Desde el 2026-10-26 la Caja Actual es solo el
        # efectivo cobrado, SIN el cambio (pedido del dueño: "que no esté sumado"; hasta
        # ese día decía "Incluye el cambio"): es lo mismo que A RETIRAR del cierre. Lo que
        # tiene que haber en el cajón contando el cambio sigue siendo
        # resumen["caja_actual"], que usa el relevo de una caja (relevo_repo).
        actual = cifra_destacada("CAJA ACTUAL (solo efectivo)", "Sin el cambio: lo cobrado en efectivo", TONO_VERDE)
        total = cifra_destacada("TOTAL (EFECTIVO + DIGITAL)", "Lo cobrado en el turno, sin el cambio", TONO_AZUL)
        self.valor_actual = actual.valor
        self.valor_total = total.valor
        cifras = QHBoxLayout()
        cifras.setSpacing(10)
        cifras.addWidget(actual, 1)
        cifras.addWidget(total, 1)

        # Con una caja abierta, el cambio con que arrancó (lo que se contó); sin caja,
        # el Cambio Fijo. Se muestra aparte: no entra en la Caja Actual.
        self.tabla = TablaDeNegocios("Caja inicial (Cambio Fijo)", "Con lo que arrancó la caja · no se suma")
        self.valor_fondo = self.tabla.valor_cambio
        self.valor_ventas = self.tabla.valor_efectivo
        self.valor_digital = self.tabla.valor_digital
        self.detalle_reservas = self.tabla.detalle_reservas

        botones = QHBoxLayout()
        botones.addWidget(tecla("🔄  ACTUALIZAR", self._refrescar))
        botones.addStretch()
        botones.addWidget(tecla("SALIR", self.close, "teclaRoja"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(self.cabecera)
        layout.addLayout(cifras)
        layout.addWidget(self.tabla)
        layout.addStretch()
        layout.addLayout(botones)
        sin_boton_por_defecto(self)

    def renglon(self, clave: str):
        """El renglón de un negocio de la tabla (las claves son las de tarjeta_cierre.NEGOCIOS)."""
        return self.tabla.renglon(clave)

    @manejar_errores
    def _refrescar(self):
        resumen = turnos_repo.resumen_turno_actual()
        self.cabecera.detalle.setText(detalle_de_la_cabecera(resumen))
        self.pastilla_hora.setText(f"ACTUALIZADA {datetime.now():%H:%M}")
        self.valor_actual.setText(formato_pesos(resumen["ventas_efectivo"]))
        self.valor_total.setText(formato_pesos(resumen["ventas_total"]))
        self.tabla.mostrar(resumen)


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
        self.resize(600, 660)
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
            "background: #FFF0FA; border: 2px solid #FF3EC8; border-radius: 10px; padding: 8px 10px; color: #1E2330;"
        )
        self.aviso_cuentas.setVisible(False)

        botones = QHBoxLayout()
        botones.addWidget(tecla("CANCELAR", self.close))
        botones.addStretch()
        botones.addWidget(tecla("CONFIRMAR CIERRE DE TURNO", self._cerrar_turno, "teclaAzul"))

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
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
        # Lo fiado en este turno se cobra en este turno (pedido del dueño, 2026-10-25):
        # si queda algo, se ofrece cobrarlo; si se cierra igual, queda en el cierre.
        if cuentas_pc_repo.fiado_del_turno_en_curso():
            pregunta = DialogoCobrarAntesDelCierre(self.usuario, DialogoCobrarAntesDelCierre.CIERRE, self)
            cerrar = pregunta.exec()
            self._refrescar_vista_previa()  # lo que se cobró recién ya suma en la tarjeta
            if not cerrar:
                return
            if pregunta.cerrar_igual:
                resultado = turnos_repo.cerrar_turno(self.usuario["id"])
                self._turno_cerrado(resultado)
                return
        if not confirmar(self, "Confirmar cierre",
                          "¿Confirmás el cierre de este turno? No se puede deshacer."):
            return
        self._turno_cerrado(turnos_repo.cerrar_turno(self.usuario["id"]))

    def _turno_cerrado(self, resultado):
        self.turno_cerrado = True
        if resultado.get("envio_a_la_app"):
            # La barra "ENVIANDO CIERRE DE TURNO" (pedido del dueño, 2026-10-26). El envío
            # lo hace el hilo de envio_pwa_repo; la barra solo mira cómo va.
            DialogoEnviandoCierre(resultado["id"], self).exec()
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
            + (f"Quedó en tu cierre {formato_pesos(resultado['fiado_sin_cobrar'])} fiado sin cobrar "
               "(Cuenta de la PC).\n\n" if resultado["fiado_sin_cobrar"] else "") +
            "Ahora volvés a la pantalla de ingreso: quien te releve tiene que entrar con su propio "
            "usuario. Si tu reemplazo no llegó, volvé a entrar con el tuyo y seguí vendiendo."
        )
        self.close()
