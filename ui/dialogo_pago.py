"""
dialogo_pago.py
=================
El cuadro de cobro que se abre al final de una venta. Desde el 2026-10-18
(idea del dueño): Efectivo y Digital están siempre a la vista y suman el
total. Al escribir en uno, el otro se completa solo con lo que falta. Hay
botones "Todo efectivo" y "Todo digital", y un campo aparte, "Paga con", para
el billete que da el cliente, que calcula el vuelto sin tocar la parte digital.
Antes había que ir agregando pagos a una lista.

Lo de siempre se mantiene (pedido del dueño, 2026-10-18): arranca con el total
escrito en Efectivo y seleccionado, así que si pagan justo un Enter cobra; si
pagan con otro billete se puede escribir ahí mismo con cuánto pagan. Con
vuelto, Enter frena una vez en Confirmar: la empleada tiene que ver el vuelto
(que titila) antes de cobrar. La cuenta (reparto, vuelto, lo que queda en la
caja) es dominio.cuenta_del_cobro; esta pantalla solo la muestra.

Está separado de ventas_window.py a propósito: una arma el carrito y esta
cobra, así se puede tocar la forma de cobrar sin riesgo de romper el
escaneo, y al revés (ver CLAUDE.md, regla 12). También lo reutilizan el
cobro de un bono en Control de PCs, vía `cobrar`, y el Mixto de Cargar
Saldo y Trámites, vía `resolver_pagos` (más abajo).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QPushButton, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence

import dominio
from ui.utils import formato_pesos, aplicar_clase, encadenar_enter, sin_boton_por_defecto

# Lo que muestra "Paga con" vacío (en cero).
_TEXTO_PAGA_JUSTO = "paga justo"


class _CampoPlata(QDoubleSpinBox):
    """Un importe en pesos que, al entrar con el mouse o con Tab, queda
    seleccionado: lo que se escribe reemplaza al número que había."""

    def __init__(self, maximo: float):
        super().__init__()
        self.setPrefix("$ ")
        self.setDecimals(2)
        self.setMaximum(maximo)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setMinimumWidth(150)

    def focusInEvent(self, evento):
        super().focusInEvent(evento)
        QTimer.singleShot(0, self.selectAll)


class DialogoPago(QDialog):
    """
    Cuadro de cobro de `total`. Al aceptar quedan `self.pagos` (lo que queda en
    la caja, neto de vuelto, listo para grabar: una o dos filas de
    Efectivo/Digital) y `self.vuelto` (lo que hay que entregarle al cliente).
    """

    def __init__(self, parent, total: float):
        super().__init__(parent)
        self.total = round(total, 2)
        self.pagos = []
        self.vuelto = 0.0
        self._acomodando = False  # mientras el programa completa un campo, no "escribe" la usuaria
        self.setWindowTitle("Cobrar Venta")
        self.resize(460, 380)
        self._armar_interfaz()
        self._refrescar()
        # Si se cierra el cuadro con el vuelto titilando, se apaga el timer.
        self.finished.connect(lambda _resultado: self._parpadeo_timer.stop())

    def _armar_interfaz(self):
        # Por hoja de estilos y no con QFont: la hoja global (main.py) le gana a
        # un QFont y el total salía con la letra chica de siempre.
        self.etiqueta_total = QLabel(f"Total: {formato_pesos(self.total)}")
        self.etiqueta_total.setStyleSheet("font-size: 22px; font-weight: 700; color: #1B2233;")

        self.campo_efectivo = _CampoPlata(99_999_999)
        self.campo_digital = _CampoPlata(self.total)
        self.campo_paga_con = _CampoPlata(99_999_999)
        # En cero, "Paga con" no dice "$ 0,00" (parecería que paga cero): dice que paga justo.
        self.campo_paga_con.setSpecialValueText(_TEXTO_PAGA_JUSTO)

        self.boton_todo_efectivo = QPushButton("Todo &efectivo")
        self.boton_todo_efectivo.clicked.connect(self._todo_efectivo)
        self.boton_todo_digital = QPushButton("Todo &digital")
        self.boton_todo_digital.clicked.connect(self._todo_digital)

        grilla = QGridLayout()
        grilla.setHorizontalSpacing(10)
        grilla.setVerticalSpacing(8)
        grilla.addWidget(QLabel("Efectivo:"), 0, 0)
        grilla.addWidget(self.campo_efectivo, 0, 1)
        grilla.addWidget(self.boton_todo_efectivo, 0, 2)
        grilla.addWidget(QLabel("Digital:"), 1, 0)
        grilla.addWidget(self.campo_digital, 1, 1)
        grilla.addWidget(self.boton_todo_digital, 1, 2)
        grilla.addWidget(QLabel("Paga con:"), 2, 0)
        grilla.addWidget(self.campo_paga_con, 2, 1)
        nota_paga_con = QLabel("el billete que da (opcional)")
        nota_paga_con.setStyleSheet("color: gray; font-size: 11px;")
        grilla.addWidget(nota_paga_con, 2, 2)
        grilla.setColumnStretch(1, 1)

        # Al escribir en un medio, el otro se completa solo (ver _al_escribir_en).
        self.campo_efectivo.valueChanged.connect(lambda _valor: self._al_escribir_en(self.campo_efectivo))
        self.campo_digital.valueChanged.connect(lambda _valor: self._al_escribir_en(self.campo_digital))
        self.campo_paga_con.valueChanged.connect(lambda _valor: self._refrescar())
        # Enter en cualquiera de los tres cobra (o frena en Confirmar si hay
        # vuelto). Va por encadenar_enter (y no por returnPressed) porque así un
        # Enter que quedó apretado de la pantalla anterior no cobra solo.
        for campo in (self.campo_efectivo, self.campo_digital, self.campo_paga_con):
            encadenar_enter(campo, accion_final=self._enter_en_un_importe)

        etiqueta_ayuda = QLabel(
            "Si pagan justo, Enter y listo. Si pagan una parte en cada medio, escribí una parte: "
            "la otra se completa sola. Si pagan con un billete más grande, escribilo en Efectivo "
            "o en \"Paga con\" y te muestra el vuelto."
        )
        etiqueta_ayuda.setWordWrap(True)
        etiqueta_ayuda.setStyleSheet("color: gray; font-style: italic; font-size: 11px;")

        self.etiqueta_falta = QLabel()

        # El vuelto se destaca a propósito: rojo, negrita y titilando, para que a
        # la empleada no se le pase entregarlo. El titileo alterna el COLOR del
        # texto (visible <-> transparente) cada medio segundo, en vez de mostrar y
        # ocultar la etiqueta: con setVisible(), Qt le saca su lugar en el layout y
        # los botones de abajo saltarían cada medio segundo.
        self.etiqueta_vuelto = QLabel()
        self.etiqueta_vuelto.setAlignment(Qt.AlignCenter)
        self._estilo_vuelto_prendido = "color: #A6323C; font-weight: bold; font-size: 16px;"
        self._estilo_vuelto_apagado = "color: rgba(0, 0, 0, 0); font-weight: bold; font-size: 16px;"
        self.etiqueta_vuelto.setStyleSheet(self._estilo_vuelto_prendido)
        self._parpadeo_timer = QTimer(self)
        self._parpadeo_timer.setInterval(500)
        self._parpadeo_timer.timeout.connect(self._alternar_parpadeo_vuelto)
        self._parpadeo_visible = True

        self.boton_confirmar = QPushButton("Confirmar")
        aplicar_clase(self.boton_confirmar, "primario")
        self.boton_confirmar.clicked.connect(self._confirmar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)

        # Confirmar no es el botón "default" (ver sin_boton_por_defecto), así que
        # Enter con el foco EN Confirmar no lo activaría solo: se le agrega un
        # atajo que responde únicamente con el foco puesto ahí. Sin repetición: un
        # Enter que queda apretado no confirma solo.
        for tecla in (Qt.Key_Return, Qt.Key_Enter):
            atajo = QShortcut(QKeySequence(tecla), self.boton_confirmar)
            atajo.setContext(Qt.WidgetShortcut)
            atajo.setAutoRepeat(False)
            atajo.activated.connect(self.boton_confirmar.click)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_total)
        layout.addSpacing(6)
        layout.addLayout(grilla)
        layout.addWidget(etiqueta_ayuda)
        layout.addStretch()
        layout.addWidget(self.etiqueta_falta)
        layout.addWidget(self.etiqueta_vuelto)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        # Arranca con todo en efectivo (lo más común: pagan justo).
        self._poner(efectivo=self.total, digital=0.0)
        self.campo_efectivo.setFocus()

    def showEvent(self, evento):
        super().showEvent(evento)
        # Al mostrarse, Qt le pone el foco al campo y le acomoda el cursor: recién
        # después se puede dejar el total seleccionado, para que lo que se
        # escriba lo reemplace.
        QTimer.singleShot(0, self.campo_efectivo.selectAll)

    # -----------------------------------------------------------------
    # El reparto
    # -----------------------------------------------------------------

    def _poner(self, efectivo=None, digital=None, paga_con=None):
        """Escribe importes desde el programa (sin que cuente como que la
        usuaria escribió, ver _al_escribir_en)."""
        self._acomodando = True
        try:
            if efectivo is not None:
                self.campo_efectivo.setValue(efectivo)
            if digital is not None:
                self.campo_digital.setValue(digital)
            if paga_con is not None:
                self.campo_paga_con.setValue(paga_con)
        finally:
            self._acomodando = False
        self._refrescar()

    def _al_escribir_en(self, campo):
        """La usuaria escribió en Efectivo o en Digital: el otro medio se
        completa con lo que falta para el total (el último que se escribe
        manda en el reparto)."""
        if self._acomodando:
            return
        if campo is self.campo_efectivo:
            self._poner(digital=dominio.lo_que_falta_para(self.total, self.campo_efectivo.value()))
        else:
            self._poner(efectivo=dominio.lo_que_falta_para(self.total, self.campo_digital.value()))

    def _todo_efectivo(self):
        self._poner(efectivo=self.total, digital=0.0)
        self.campo_efectivo.setFocus()
        self.campo_efectivo.selectAll()

    def _todo_digital(self):
        self._poner(efectivo=0.0, digital=self.total, paga_con=0.0)
        self.campo_digital.setFocus()
        self.campo_digital.selectAll()

    def _cuenta(self) -> dict:
        return dominio.cuenta_del_cobro(
            self.total, self.campo_efectivo.value(), self.campo_digital.value(), self.campo_paga_con.value(),
        )

    # -----------------------------------------------------------------
    # Lo que se ve y cobrar
    # -----------------------------------------------------------------

    def _refrescar(self):
        cuenta = self._cuenta()
        self.vuelto = cuenta["vuelto"]
        # "Paga con" solo tiene sentido si hay una parte en efectivo; si todo va
        # a digital, se vacía (no queda un billete viejo escrito, apagado).
        hay_efectivo = cuenta["parte_efectivo"] > 0
        self.campo_paga_con.setEnabled(hay_efectivo)
        if not hay_efectivo and self.campo_paga_con.value():
            self.campo_paga_con.blockSignals(True)
            self.campo_paga_con.setValue(0.0)
            self.campo_paga_con.blockSignals(False)

        if cuenta["falta"] > 0:
            self.etiqueta_falta.setText(
                f"Con lo que paga no alcanza: faltan {formato_pesos(cuenta['falta'])} en efectivo."
            )
            self.etiqueta_falta.setStyleSheet("color: #A6323C; font-weight: bold;")
            self.boton_confirmar.setEnabled(False)
        else:
            partes = []
            if cuenta["parte_efectivo"] > 0:
                partes.append(f"{formato_pesos(cuenta['parte_efectivo'])} en efectivo")
            if cuenta["digital"] > 0:
                partes.append(f"{formato_pesos(cuenta['digital'])} digital")
            self.etiqueta_falta.setText("Se cobra: " + " + ".join(partes) + "  ✓" if partes else "Cobro completo ✓")
            self.etiqueta_falta.setStyleSheet("color: #1E8E5A; font-weight: bold;")
            self.boton_confirmar.setEnabled(True)

        if self.vuelto > 0:
            self.etiqueta_vuelto.setText(f"VUELTO: {formato_pesos(self.vuelto)}")
            if not self._parpadeo_timer.isActive():
                self._parpadeo_timer.start()
        else:
            self._detener_parpadeo_vuelto()

    def _enter_en_un_importe(self):
        """
        Enter en Efectivo, Digital o "Paga con". Pagó justo (lo más común, y
        también con una parte en cada medio, que ya se ve en los dos campos):
        este mismo Enter cobra. Con vuelto, el foco pasa a Confirmar y hace
        falta un Enter más: la empleada tiene que ver el vuelto que titila antes
        de cobrar. Si con lo que paga no alcanza, no hace nada (lo dice en rojo).
        """
        if not self.boton_confirmar.isEnabled():
            return
        if self.vuelto > 0:
            self.boton_confirmar.setFocus()
        else:
            self._confirmar()

    def _alternar_parpadeo_vuelto(self):
        """Alterna el color del vuelto entre visible y transparente (el
        titileo); la etiqueta queda siempre visible, así nada se corre."""
        self._parpadeo_visible = not self._parpadeo_visible
        estilo = self._estilo_vuelto_prendido if self._parpadeo_visible else self._estilo_vuelto_apagado
        self.etiqueta_vuelto.setStyleSheet(estilo)

    def _detener_parpadeo_vuelto(self):
        """Apaga el titileo y deja la etiqueta vacía (sin ocultarla)."""
        self._parpadeo_timer.stop()
        self._parpadeo_visible = True
        self.etiqueta_vuelto.setStyleSheet(self._estilo_vuelto_prendido)
        self.etiqueta_vuelto.setText("")

    def _confirmar(self):
        cuenta = self._cuenta()
        if cuenta["falta"] > 0:
            return
        # Lo que se graba es la plata que queda en la caja (neta de vuelto); el
        # vuelto queda aparte, para avisarle a la empleada cuánto entregar (ver
        # ventas_window._ir_a_cobrar).
        self.pagos = cuenta["pagos"]
        self.vuelto = cuenta["vuelto"]
        self.accept()


def cobrar(parent, monto):
    """
    Abre este cuadro de cobro por `monto` y devuelve los pagos (netos de
    vuelto, listos para mandarle al repo), o None si se canceló (el llamador
    no debe seguir). Así se cobra un bono en Control de PCs -- PC, PCSTREAM
    y PlayStation 5 --, igual que una venta de kiosko (pedido del dueño,
    2026-10-18: antes se elegía el medio en un combo del panel). También lo
    usa el Mixto de `resolver_pagos`.
    """
    dialogo = DialogoPago(parent, monto)
    if not dialogo.exec():
        return None
    return dialogo.pagos


def resolver_pagos(parent, metodo, monto):
    """
    Único lugar donde se resuelve "qué método eligió la usuaria" a una
    lista de pagos lista para mandarle al repo. Si el medio elegido es
    Mixto, abre este mismo DialogoPago para repartir el monto entre
    Efectivo y Digital -- no existe un tercer método "MIXTO" en la base,
    siempre termina siendo una o dos filas reales de Efectivo/Digital.
    Devuelve None si se canceló ese cuadro (el llamador no debe seguir).

    Compartido entre control_pcs/ui/miembros_window.py (cargar saldo de un
    socio) y ui/tramites_window.py (cobrar un trámite), para no repetir
    esta lógica (CLAUDE.md, regla 2). `monto <= 0` no abre el
    cuadro (no tiene sentido cobrar un total en cero): el llamador que
    permite un monto libre en $ (Cargar Saldo) ya valida eso aparte antes
    de llegar a grabar nada.
    """
    if metodo == dominio.PAGO_MIXTO and monto > 0:
        return cobrar(parent, monto)
    return [{"metodo": metodo, "monto": monto}]
