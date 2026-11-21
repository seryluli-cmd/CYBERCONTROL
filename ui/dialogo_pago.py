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
pagan con otro billete se puede escribir ahí mismo con cuánto pagan. Un Enter
cobra siempre, también con una parte en cada medio y con vuelto (pedido del
dueño, esa misma noche: "el Enter debería ser para agilizar"); el vuelto se ve
titilando mientras se escribe el billete. La cuenta (reparto, vuelto, lo que
queda en la caja) es dominio.cuenta_del_cobro; esta pantalla solo la muestra.

El aspecto es el diseño A que eligió el dueño el 2026-11-21 entre tres maquetas
("que sea mucho más profesional y bella"): la cabecera oscura de Caja y Cierre
de Turno con el total a la derecha; en un panel blanco, cada medio con su
dibujito en un cuadradito de color (verde el efectivo, azul lo digital, ámbar el
billete) y los importes grandes; abajo, lo que se cobra y el vuelto como cifras
grandes (ui.piezas_ventana.cifra_destacada), y las teclas con relieve. Cambió
solo cómo se ve: los campos, los atajos y las cuentas son los de antes. Los
colores van en ui/hoja_de_estilos.py, por objectName.

Está separado de ventas_window.py a propósito: una arma el carrito y esta
cobra, así se puede tocar la forma de cobrar sin riesgo de romper el
escaneo, y al revés (ver CLAUDE.md, regla 12). Todo lo demás que se cobra
lo reutiliza vía `cobrar` (más abajo): los bonos de Control de PCs, la carga
de saldo de un socio y los trámites.
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QGridLayout, QLabel, QDoubleSpinBox,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence

import dominio
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_ROJO, TONO_VERDE, cabecera_oscura, cifra_destacada, linea_divisoria,
    panel_blanco, pastilla_clara, pie_de_ventana, tecla, titulo_de_seccion,
)
from ui.utils import CampoPesos, formato_pesos, encadenar_enter, sin_boton_por_defecto

# Lo que muestra "Paga con" vacío (en cero).
_TEXTO_PAGA_JUSTO = "paga justo"

# El cuadradito del billete que da el cliente ("Paga con"): solo existe en esta ventana.
_TONO_AMBAR = "ambar"


class _CampoPlata(CampoPesos):
    """Un importe en pesos ("$ 1.500", ver ui.utils.CampoPesos) que, al entrar con
    el mouse o con Tab, queda seleccionado: lo que se escribe reemplaza al número
    que había. Grande y a la derecha, como se escribe la plata (diseño A)."""

    def __init__(self, maximo: float):
        super().__init__(maximo)
        self.setButtonSymbols(QDoubleSpinBox.NoButtons)
        self.setObjectName("campoCobro")
        self.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.setMinimumWidth(170)

    def focusInEvent(self, evento):
        super().focusInEvent(evento)
        QTimer.singleShot(0, self.selectAll)


def _insignia(icono: str, tono: str) -> QLabel:
    """El dibujito de un medio de pago en un cuadradito de color."""
    etiqueta = QLabel(icono)
    etiqueta.setObjectName("insigniaCobro")
    etiqueta.setProperty("tono", tono)
    etiqueta.setAlignment(Qt.AlignCenter)
    etiqueta.setFixedSize(42, 42)
    return etiqueta


def _nombre_del_medio(nombre: str, ayuda: str) -> QVBoxLayout:
    """El nombre del medio en mayúscula y, debajo, una línea gris de qué es."""
    capa = QVBoxLayout()
    capa.setSpacing(0)
    capa.addStretch()
    etiqueta_nombre = QLabel(nombre)
    etiqueta_nombre.setObjectName("nombreMedioCobro")
    etiqueta_ayuda = QLabel(ayuda)
    etiqueta_ayuda.setObjectName("ayudaMedioCobro")
    capa.addWidget(etiqueta_nombre)
    capa.addWidget(etiqueta_ayuda)
    capa.addStretch()
    return capa


def _repintar(*widgets):
    """Que Qt vuelva a mirar la hoja de estilos después de cambiar una propiedad (el
    tono de una cifra, el titileo del vuelto)."""
    for widget in widgets:
        widget.style().unpolish(widget)
        widget.style().polish(widget)


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
        self.setMinimumWidth(620)
        self._armar_interfaz()
        self._refrescar()
        # Si se cierra el cuadro con el vuelto titilando, se apaga el timer.
        self.finished.connect(lambda _resultado: self._parpadeo_timer.stop())

    def _armar_interfaz(self):
        # La cabecera oscura, con el total a la derecha (en grande y en blanco).
        cabecera = cabecera_oscura("💵", "Cobrar venta", "Enter cobra  ·  Esc cancela")
        capa_total = QVBoxLayout()
        capa_total.setSpacing(0)
        titulo_total = QLabel("TOTAL A COBRAR")
        titulo_total.setObjectName("tituloTotalCobro")
        titulo_total.setAlignment(Qt.AlignRight)
        self.etiqueta_total = QLabel(formato_pesos(self.total))
        self.etiqueta_total.setObjectName("totalCobro")
        self.etiqueta_total.setAlignment(Qt.AlignRight)
        capa_total.addWidget(titulo_total)
        capa_total.addWidget(self.etiqueta_total)
        cabecera.fila.addLayout(capa_total)

        self.campo_efectivo = _CampoPlata(99_999_999)
        self.campo_digital = _CampoPlata(self.total)
        self.campo_paga_con = _CampoPlata(99_999_999)
        # En cero, "Paga con" no dice "$ 0,00" (parecería que paga cero): dice que paga justo.
        self.campo_paga_con.setSpecialValueText(_TEXTO_PAGA_JUSTO)

        # El "&" deja los atajos de siempre: Alt+E y Alt+D.
        self.boton_todo_efectivo = tecla("TODO &EFECTIVO", self._todo_efectivo)
        self.boton_todo_digital = tecla("TODO &DIGITAL", self._todo_digital)
        for boton in (self.boton_todo_efectivo, self.boton_todo_digital):
            boton.setMinimumWidth(150)

        # Los tres importes en un panel blanco: dibujito, nombre, campo y tecla.
        panel, capa_panel = panel_blanco()
        capa_panel.addWidget(titulo_de_seccion("Cómo paga"))
        grilla = QGridLayout()
        grilla.setHorizontalSpacing(12)
        grilla.setVerticalSpacing(10)
        renglones = (
            (0, "💵", TONO_VERDE, "EFECTIVO", "billetes y monedas", self.campo_efectivo,
             self.boton_todo_efectivo),
            (1, "💳", TONO_AZUL, "DIGITAL", "transferencia, QR o tarjeta", self.campo_digital,
             self.boton_todo_digital),
            (3, "💰", _TONO_AMBAR, "PAGA CON", "el billete que da", self.campo_paga_con,
             pastilla_clara("OPCIONAL", TONO_GRIS, chica=True)),
        )
        for fila, icono, tono, nombre, ayuda, campo, al_costado in renglones:
            grilla.addWidget(_insignia(icono, tono), fila, 0)
            grilla.addLayout(_nombre_del_medio(nombre, ayuda), fila, 1)
            grilla.addWidget(campo, fila, 2)
            grilla.addWidget(al_costado, fila, 3, Qt.AlignLeft | Qt.AlignVCenter)
        # La raya separa lo que se cobra (Efectivo y Digital) del billete, que es opcional.
        grilla.addWidget(linea_divisoria(), 2, 0, 1, 4)
        grilla.setColumnStretch(2, 1)
        capa_panel.addLayout(grilla)

        # Al escribir en un medio, el otro se completa solo (ver _al_escribir_en).
        self.campo_efectivo.valueChanged.connect(lambda _valor: self._al_escribir_en(self.campo_efectivo))
        self.campo_digital.valueChanged.connect(lambda _valor: self._al_escribir_en(self.campo_digital))
        self.campo_paga_con.valueChanged.connect(lambda _valor: self._refrescar())
        # Enter en cualquiera de los tres cobra. Va por encadenar_enter (y no
        # por returnPressed) porque así un Enter que quedó apretado de la
        # pantalla anterior no cobra solo.
        for campo in (self.campo_efectivo, self.campo_digital, self.campo_paga_con):
            encadenar_enter(campo, accion_final=self._enter_en_un_importe)

        # Abajo, en grande: lo que se cobra (verde; en rojo si no alcanza) y el vuelto.
        self.cifra_cobro = cifra_destacada("SE COBRA", "", TONO_VERDE)
        # El vuelto se destaca a propósito: rojo y titilando, para que a la empleada
        # no se le pase entregarlo. El titileo alterna el COLOR del número (visible <->
        # transparente) cada medio segundo, en vez de mostrarlo y ocultarlo: con
        # setVisible(), Qt le saca su lugar en el layout y los botones de abajo
        # saltarían cada medio segundo. Sin vuelto queda en gris, con "$ 0".
        self.cifra_vuelto = cifra_destacada("VUELTO", "", TONO_GRIS)
        self.etiqueta_vuelto = self.cifra_vuelto.valor
        self._parpadeo_timer = QTimer(self)
        self._parpadeo_timer.setInterval(500)
        self._parpadeo_timer.timeout.connect(self._alternar_parpadeo_vuelto)
        self._parpadeo_visible = True
        cifras = QHBoxLayout()
        cifras.setSpacing(12)
        cifras.addWidget(self.cifra_cobro, 1)
        cifras.addWidget(self.cifra_vuelto, 1)

        ayuda = pie_de_ventana(
            "💡  Pagan justo: Enter y listo. Una parte en cada medio: escribí una y la otra se "
            "completa sola. Con un billete más grande: escribilo en Efectivo o en «Paga con» y "
            "sale el vuelto."
        )

        boton_cancelar = tecla("CANCELAR  (Esc)", self.reject)
        boton_cancelar.setObjectName("cancelarCobro")
        self.boton_confirmar = tecla("✓  CONFIRMAR COBRO  (Enter)", self._confirmar, "teclaVerde")
        self.boton_confirmar.setObjectName("confirmarCobro")

        # Confirmar no es el botón "default" (ver sin_boton_por_defecto), así que
        # Enter con el foco EN Confirmar (llegando con Tab) no lo activaría solo:
        # se le agrega un atajo que responde únicamente con el foco puesto ahí.
        # Sin repetición: un Enter que queda apretado no confirma solo.
        for tecla_enter in (Qt.Key_Return, Qt.Key_Enter):
            atajo = QShortcut(QKeySequence(tecla_enter), self.boton_confirmar)
            atajo.setContext(Qt.WidgetShortcut)
            atajo.setAutoRepeat(False)
            atajo.activated.connect(self.boton_confirmar.click)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(panel)
        layout.addLayout(cifras)
        layout.addWidget(ayuda)
        layout.addStretch()
        layout.addLayout(botones)
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

    @staticmethod
    def _mostrar_cifra(cifra, tono: str, titulo: str, valor: str, aclaracion: str, apagada: bool = False):
        """Pone los textos y el color de una de las dos cifras de abajo. El color
        depende del recuadro, así que se repintan él y sus tres etiquetas."""
        cifra.setProperty("tono", tono)
        cifra.setProperty("apagada", "true" if apagada else "false")
        cifra.titulo.setText(titulo)
        cifra.valor.setText(valor)
        cifra.aclaracion.setText(aclaracion)
        _repintar(cifra, cifra.titulo, cifra.valor, cifra.aclaracion)

    @staticmethod
    def _como_se_cobra(cuenta: dict) -> str:
        """La línea de abajo de SE COBRA: en qué medio va la plata."""
        efectivo, digital = cuenta["parte_efectivo"], cuenta["digital"]
        if efectivo > 0 and digital > 0:
            return f"{formato_pesos(efectivo)} efectivo + {formato_pesos(digital)} digital  ✓"
        if efectivo > 0:
            return "todo en efectivo  ✓"
        if digital > 0:
            return "todo digital  ✓"
        return "cobro completo  ✓"

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
            self._mostrar_cifra(self.cifra_cobro, TONO_ROJO, "FALTA", formato_pesos(cuenta["falta"]),
                                "con lo que paga no alcanza")
            self.boton_confirmar.setEnabled(False)
        else:
            self._mostrar_cifra(self.cifra_cobro, TONO_VERDE, "SE COBRA", formato_pesos(self.total),
                                self._como_se_cobra(cuenta))
            self.boton_confirmar.setEnabled(True)

        if self.vuelto > 0:
            self._mostrar_cifra(self.cifra_vuelto, TONO_ROJO, "VUELTO", formato_pesos(self.vuelto),
                                "entregáselo al cliente")
            if not self._parpadeo_timer.isActive():
                self._parpadeo_timer.start()
        else:
            self._detener_parpadeo_vuelto()
            self._mostrar_cifra(self.cifra_vuelto, TONO_GRIS, "VUELTO", formato_pesos(0), "no hay vuelto",
                                apagada=True)

    def _enter_en_un_importe(self):
        """
        Enter en Efectivo, Digital o "Paga con": cobra, pague justo, con una
        parte en cada medio o con vuelto. Hasta el 2026-10-18 con vuelto frenaba
        en Confirmar y hacía falta otro Enter; el dueño pidió que no: el vuelto
        ya se ve al escribir el billete y, en Ventas, sale también en el cartel
        de la venta cobrada. Si con lo que paga no alcanza, no hace nada (lo
        dice en rojo).
        """
        if self.boton_confirmar.isEnabled():
            self._confirmar()

    def _pintar_parpadeo(self):
        valor = self.cifra_vuelto.valor
        valor.setProperty("parpadeo", "prendido" if self._parpadeo_visible else "apagado")
        _repintar(valor)

    def _alternar_parpadeo_vuelto(self):
        """Alterna el número del vuelto entre visible y transparente (el
        titileo); el recuadro queda siempre en su lugar, así nada se corre."""
        self._parpadeo_visible = not self._parpadeo_visible
        self._pintar_parpadeo()

    def _detener_parpadeo_vuelto(self):
        """Apaga el titileo y deja el número a la vista."""
        self._parpadeo_timer.stop()
        self._parpadeo_visible = True
        self._pintar_parpadeo()

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
    no debe seguir). Así se cobra todo lo que no es una venta de kiosko,
    igual que una venta de kiosko: un bono en Control de PCs -- PC, PCSTREAM
    y PlayStation 5 --, la carga de saldo de un socio y un trámite (pedido
    del dueño, 2026-10-18: antes se elegía el medio en un combo de cada
    pantalla, y esta ventana solo se abría con "Mixto").
    """
    dialogo = DialogoPago(parent, monto)
    if not dialogo.exec():
        return None
    return dialogo.pagos
