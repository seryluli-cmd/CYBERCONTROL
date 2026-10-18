"""
dialogo_pago.py
=================
El cuadro de cobro que se abre al final de una venta: permite ir
agregando pagos parciales (una parte en Efectivo, el resto en Digital)
hasta cubrir el total, calcula el vuelto y recién ahí habilita
Confirmar. El monto arranca escrito con el total (pedido del dueño,
2026-10-18: casi siempre pagan justo), así que el cobro común es un Enter.

Está separado de ventas_window.py a propósito: una arma el carrito y esta
cobra, así se puede tocar la forma de cobrar sin riesgo de romper el
escaneo, y al revés (ver CLAUDE.md, regla 12). También lo reutilizan el
cobro de un bono en Control de PCs, vía `cobrar`, y el Mixto de Cargar
Saldo y Trámites, vía `resolver_pagos` (más abajo).
"""

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QComboBox, QDoubleSpinBox,
    QTableWidgetItem,
)
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QShortcut, QKeySequence, QFont

import dominio
from ui.utils import (
    formato_pesos, mostrar_error, mostrar_aviso, aplicar_clase, encadenar_enter,
    sin_boton_por_defecto, crear_tabla,
)


class DialogoPago(QDialog):
    """
    Cuadro de cobro. Se pueden ir agregando pagos parciales — por
    ejemplo, una parte en Efectivo y el resto en Digital (Mercado Pago /
    transferencia) — hasta cubrir el total. El botón Confirmar recién se
    habilita cuando ya está cubierto.

    Al aceptar quedan `self.pagos` (ya netos de vuelto, listos para
    grabar) y `self.vuelto` (lo que hay que entregarle a la clienta).
    """

    def __init__(self, parent, total: float):
        super().__init__(parent)
        self.total = total
        self.pagos = []  # lista de {"metodo": PAGO_EFECTIVO|PAGO_DIGITAL, "monto": ...}
        self.vuelto = 0.0
        self.setWindowTitle("Cobrar Venta")
        self.resize(420, 420)
        self._armar_interfaz()
        self._refrescar()
        # Por las dudas se cierre el cuadro (Cancelar o Confirmar) con el
        # vuelto titilando, apagamos el timer para que no siga corriendo
        # de fondo sin sentido.
        self.finished.connect(lambda _resultado: self._parpadeo_timer.stop())

    def _armar_interfaz(self):
        fuente_total = QFont()
        fuente_total.setPointSize(18)
        fuente_total.setBold(True)

        self.etiqueta_total = QLabel()
        self.etiqueta_total.setFont(fuente_total)

        self.combo_metodo = QComboBox()
        for metodo in dominio.METODOS_PAGO:
            self.combo_metodo.addItem(dominio.NOMBRE_METODO_PAGO[metodo], metodo)

        self.spin_monto = QDoubleSpinBox()
        self.spin_monto.setMaximum(99_999_999)
        self.spin_monto.setPrefix("$ ")
        # Apretar Enter en el monto no solo agrega ese pago: si sobra
        # algo para llegar al total, lo completa solo con el OTRO medio
        # de pago (ver _agregar_pago_y_completar). Es el caso más común
        # en el mostrador: "una parte en efectivo, el resto digital", o
        # al revés — así se resuelve en un solo Enter, sin calculadora.
        # Va por encadenar_enter (y no por returnPressed) porque así un
        # Enter que quedó apretado de la pantalla anterior no cobra solo.
        encadenar_enter(self.spin_monto, accion_final=self._agregar_pago_y_completar)
        # Enter en "Medio de pago" vuelve al monto con el número seleccionado
        # (Qt lo deselecciona al salir del campo), listo para pisarlo.
        encadenar_enter(self.combo_metodo, accion_final=self._volver_al_monto)

        boton_agregar = QPushButton("Agregar pago")
        boton_agregar.setToolTip("Agrega únicamente el monto tipeado, con el medio elegido.")
        boton_agregar.clicked.connect(self._agregar_pago)

        fila_agregar = QHBoxLayout()
        fila_agregar.addWidget(self.combo_metodo)
        fila_agregar.addWidget(self.spin_monto)
        fila_agregar.addWidget(boton_agregar)

        etiqueta_ayuda = QLabel(
            "El monto ya viene con el total: si pagan justo, apretá Enter y listo. "
            "Si pagan con otro billete, escribí con cuánto pagan. Si pagan una parte "
            "en cada medio, escribí una parte y apretá Enter: el resto se completa solo "
            "con el otro medio."
        )
        etiqueta_ayuda.setWordWrap(True)
        etiqueta_ayuda.setStyleSheet("color: gray; font-style: italic; font-size: 11px;")

        self.tabla_pagos = crear_tabla(["Medio de pago", "Monto"], estirar=0)

        boton_quitar_pago = QPushButton("Quitar pago seleccionado")
        boton_quitar_pago.clicked.connect(self._quitar_pago)

        self.etiqueta_falta = QLabel()

        # El vuelto se destaca a propósito: rojo, negrita y titilando,
        # para que a la empleada no se le pase entregarlo (es plata que
        # tiene que devolver, y en el ajetreo del mostrador es fácil
        # olvidarlo). El titileo se logra con un QTimer que alterna el
        # COLOR del texto (visible <-> transparente) cada medio segundo,
        # en vez de mostrar/ocultar la etiqueta: si se usara setVisible(),
        # Qt le saca el espacio reservado en el layout cuando está oculta,
        # y todo lo de abajo (los botones) se corre de lugar cada medio
        # segundo. Manteniendo la etiqueta siempre visible, con solo el
        # color titilando, el espacio ocupado nunca cambia y nada se mueve.
        self.etiqueta_vuelto = QLabel()
        self.etiqueta_vuelto.setAlignment(Qt.AlignCenter)
        self._estilo_vuelto_prendido = "color: #A6323C; font-weight: bold; font-size: 16px;"
        self._estilo_vuelto_apagado = "color: rgba(0, 0, 0, 0); font-weight: bold; font-size: 16px;"
        self.etiqueta_vuelto.setStyleSheet(self._estilo_vuelto_prendido)
        self._parpadeo_timer = QTimer(self)
        self._parpadeo_timer.setInterval(500)  # medio segundo prendido, medio apagado
        self._parpadeo_timer.timeout.connect(self._alternar_parpadeo_vuelto)
        self._parpadeo_visible = True

        self.boton_confirmar = QPushButton("Confirmar")
        aplicar_clase(self.boton_confirmar, "primario")
        self.boton_confirmar.clicked.connect(self._confirmar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)

        # Con Confirmar sin ser el botón "default" (ver el bucle de más
        # abajo, necesario para que Enter en el código de barras no
        # dispare botones ajenos), apretar Enter estando el foco EN el
        # botón Confirmar no lo activa solo. Se agrega un atajo de
        # teclado con contexto WidgetShortcut: solo responde a Enter
        # cuando el foco está puesto justo en ese botón, así que no
        # reintroduce el problema de "Enter en cualquier lado dispara el
        # botón". Se cubren Key_Return (Enter del teclado) y Key_Enter
        # (Enter del teclado numérico).
        # Sin repetición: un Enter que queda apretado no confirma solo.
        self._atajo_confirmar_return = QShortcut(QKeySequence(Qt.Key_Return), self.boton_confirmar)
        self._atajo_confirmar_return.setContext(Qt.WidgetShortcut)
        self._atajo_confirmar_return.setAutoRepeat(False)
        self._atajo_confirmar_return.activated.connect(self.boton_confirmar.click)
        self._atajo_confirmar_enter = QShortcut(QKeySequence(Qt.Key_Enter), self.boton_confirmar)
        self._atajo_confirmar_enter.setContext(Qt.WidgetShortcut)
        self._atajo_confirmar_enter.setAutoRepeat(False)
        self._atajo_confirmar_enter.activated.connect(self.boton_confirmar.click)

        botones = QHBoxLayout()
        botones.addWidget(boton_cancelar)
        botones.addStretch()
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_total)
        layout.addLayout(fila_agregar)
        layout.addWidget(etiqueta_ayuda)
        layout.addWidget(self.tabla_pagos)
        layout.addWidget(boton_quitar_pago)
        layout.addWidget(self.etiqueta_falta)
        layout.addWidget(self.etiqueta_vuelto)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        self._proponer_lo_que_falta()
        self.spin_monto.setFocus()

    def showEvent(self, evento):
        super().showEvent(evento)
        # Al mostrarse, Qt le pone el foco al monto y le acomoda el cursor:
        # recién después se puede dejar el número seleccionado, para que lo
        # que se escriba lo reemplace.
        QTimer.singleShot(0, self.spin_monto.lineEdit().selectAll)

    def _volver_al_monto(self):
        self.spin_monto.setFocus()
        self.spin_monto.lineEdit().selectAll()

    def _falta_cubrir(self) -> float:
        return round(self.total - sum(p["monto"] for p in self.pagos), 2)

    def _proponer_lo_que_falta(self):
        """
        Deja escrito en el monto lo que falta cubrir (al abrir, el total), y
        seleccionado: casi siempre pagan justo, en efectivo o por
        transferencia (pedido del dueño, 2026-10-18), así que alcanza con
        Enter. Si pagan con otro billete, lo que se escribe reemplaza al
        número propuesto sin tener que borrarlo. Con todo cubierto queda en
        cero, que es lo que hace que un Enter de más no agregue nada.
        """
        self.spin_monto.setValue(max(0.0, self._falta_cubrir()))
        self.spin_monto.lineEdit().selectAll()

    def _validar_y_agregar(self, metodo, monto):
        """
        Valida y agrega UN pago a self.pagos. Devuelve True si se pudo
        agregar (y ya queda cargado); False si no era válido (y ya se
        le mostró el error a la usuaria). Lo comparten _agregar_pago
        (botón) y _agregar_pago_y_completar (Enter).
        """
        if monto <= 0:
            mostrar_error(self, "Monto inválido", "Ingresá un monto mayor a cero.")
            return False

        # Un pago Digital no puede superar lo que todavía falta cubrir
        # (a diferencia del Efectivo, que sí puede pasarse: ahí se
        # calcula el vuelto).
        if metodo == dominio.PAGO_DIGITAL:
            cubierto_digital = sum(p["monto"] for p in self.pagos if p["metodo"] == dominio.PAGO_DIGITAL)
            falta_sin_efectivo = self.total - cubierto_digital
            if monto > falta_sin_efectivo + 0.01:
                mostrar_aviso(self, "Monto demasiado alto",
                              "El pago Digital no puede superar lo que falta cubrir del total.")
                return False

        self.pagos.append({"metodo": metodo, "monto": monto})
        return True

    def _agregar_pago(self):
        """Botón "Agregar pago": suma únicamente el monto tipeado, tal
        cual, sin tocar nada más."""
        monto = self.spin_monto.value()
        metodo = self.combo_metodo.currentData()
        if self._validar_y_agregar(metodo, monto):
            self._refrescar()
            self._proponer_lo_que_falta()

    def _agregar_pago_y_completar(self):
        """
        Se dispara al apretar Enter en el campo de monto. Agrega el pago
        tipeado y, si con eso todavía no se cubre el total de la venta,
        completa automáticamente lo que falta con el OTRO medio de pago
        (Efectivo <-> Digital). Cubre el caso más frecuente en el
        mostrador: "una parte en efectivo, el resto en digital" (o al
        revés) en un solo paso, sin tener que calcular el resto a mano.
        """
        monto = self.spin_monto.value()
        if monto <= 0:
            # Un Enter con el campo en $0 no hace nada (por ejemplo, el
            # que queda pendiente justo después de agregar un pago, que
            # deja el campo en cero listo para el siguiente). No tiene
            # sentido molestar con un cartel de error acá.
            return
        metodo = self.combo_metodo.currentData()

        falta_antes = self.total - sum(p["monto"] for p in self.pagos)

        if not self._validar_y_agregar(metodo, monto):
            return

        resto = falta_antes - monto
        completado_con_el_otro_medio = resto > 0.01
        if completado_con_el_otro_medio:
            otro_metodo = dominio.PAGO_DIGITAL if metodo == dominio.PAGO_EFECTIVO else dominio.PAGO_EFECTIVO
            # El resto siempre es, como mucho, lo que faltaba cubrir, así
            # que nunca puede superar el tope de Digital: no hace falta
            # volver a validar acá.
            self.pagos.append({"metodo": otro_metodo, "monto": round(resto, 2)})

        self._refrescar()
        self._proponer_lo_que_falta()

        if not self.boton_confirmar.isEnabled():
            return
        # Pagó justo (lo más común): no hay vuelto que entregar ni un
        # reparto entre medios que revisar, así que este mismo Enter cobra.
        # Con vuelto o con el resto puesto en el otro medio, el foco pasa a
        # Confirmar y hace falta un Enter más: la empleada tiene que ver el
        # vuelto que titila, o el reparto, antes de cobrar.
        if self.vuelto <= 0 and not completado_con_el_otro_medio:
            self._confirmar()
        else:
            self.boton_confirmar.setFocus()

    def _quitar_pago(self):
        fila = self.tabla_pagos.currentRow()
        if fila >= 0:
            del self.pagos[fila]
            self._refrescar()
            self._proponer_lo_que_falta()

    def _alternar_parpadeo_vuelto(self):
        """Cada vez que dispara el timer, alterna el color del texto del
        vuelto entre visible y transparente — eso es lo que se ve como
        un titileo. La etiqueta en sí queda SIEMPRE visible (nunca se usa
        setVisible), para que su espacio en el layout no cambie y nada
        se corra de lugar en la pantalla."""
        self._parpadeo_visible = not self._parpadeo_visible
        estilo = self._estilo_vuelto_prendido if self._parpadeo_visible else self._estilo_vuelto_apagado
        self.etiqueta_vuelto.setStyleSheet(estilo)

    def _refrescar(self):
        self.etiqueta_total.setText(f"Total: {formato_pesos(self.total)}")

        self.tabla_pagos.setRowCount(0)
        for pago in self.pagos:
            fila = self.tabla_pagos.rowCount()
            self.tabla_pagos.insertRow(fila)
            nombre_metodo = dominio.nombre_metodo(pago["metodo"])
            self.tabla_pagos.setItem(fila, 0, QTableWidgetItem(nombre_metodo))
            self.tabla_pagos.setItem(fila, 1, QTableWidgetItem(formato_pesos(pago["monto"])))

        total_efectivo = sum(p["monto"] for p in self.pagos if p["metodo"] == dominio.PAGO_EFECTIVO)
        total_digital = sum(p["monto"] for p in self.pagos if p["metodo"] == dominio.PAGO_DIGITAL)
        falta = self.total - total_digital - total_efectivo

        if falta > 0.01:
            self.etiqueta_falta.setText(f"Falta cobrar: {formato_pesos(falta)}")
            self.etiqueta_falta.setStyleSheet("color: #A6323C; font-weight: bold;")
            self.vuelto = 0.0
            self._detener_parpadeo_vuelto()
            self.boton_confirmar.setEnabled(False)
        else:
            self.vuelto = max(0.0, total_efectivo - (self.total - total_digital))
            self.etiqueta_falta.setText("Cobro completo ✓")
            self.etiqueta_falta.setStyleSheet("color: #1E8E5A; font-weight: bold;")
            if self.vuelto > 0:
                self.etiqueta_vuelto.setText(f"VUELTO: {formato_pesos(self.vuelto)}")
                if not self._parpadeo_timer.isActive():
                    self._parpadeo_timer.start()
            else:
                self._detener_parpadeo_vuelto()
            self.boton_confirmar.setEnabled(True)

    def _detener_parpadeo_vuelto(self):
        """Apaga el titileo y deja la etiqueta vacía, con el color
        "prendido" de base, lista para la próxima vez que haga falta
        mostrar un vuelto. La etiqueta nunca se oculta (setVisible), así
        que esto no afecta el espacio que ocupa en el layout."""
        self._parpadeo_timer.stop()
        self._parpadeo_visible = True
        self.etiqueta_vuelto.setStyleSheet(self._estilo_vuelto_prendido)
        self.etiqueta_vuelto.setText("")

    def _confirmar(self):
        # self.pagos tiene que quedar neto del vuelto ANTES de devolverlo
        # (ver dominio.pagos_netos_de_vuelto): lo que graba venta_pagos es
        # la plata que efectivamente queda en la caja, no lo que la
        # clienta puso arriba del mostrador. self.vuelto NO se toca: sigue
        # siendo lo que se le avisa a la empleada que tiene que entregar
        # (ver ventas_window._ir_a_cobrar).
        if self.vuelto > 0:
            self.pagos = dominio.pagos_netos_de_vuelto(self.pagos, self.vuelto)
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
