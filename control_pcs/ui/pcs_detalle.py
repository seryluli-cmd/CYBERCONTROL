"""
pcs_detalle.py
===============
Panel lateral de "Control de PCs" (`PanelDetalleEstacion`): todas las
acciones sobre la estación seleccionada en la grilla de pcs_window.py —
vender/agregar un bono, abrir con Miembro, finalizar la sesión — y el
diálogo con el que un socio se loguea solo (`DialogoLoginMiembro`).
"""

from PySide6.QtWidgets import (
    QButtonGroup, QComboBox, QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit,
    QPushButton, QVBoxLayout,
)

import dominio
from control_pcs.repositories import miembros_repo, pcs_repo
from ui.dialogo_pago import resolver_pagos
from ui.utils import (
    aplicar_clase, confirmar, encadenar_enter, formato_pesos, formato_tiempo,
    manejar_errores, mostrar_error, mostrar_info, sin_boton_por_defecto,
)

class PanelDetalleEstacion(QFrame):
    """
    Panel lateral de "Control de PCs": todas las acciones sobre la
    estación seleccionada en la grilla — vender/agregar un bono, abrir
    con Miembro, finalizar la sesión — viven acá en vez de un diálogo
    aparte por cada una, para que el Operador resuelva todo sin salir de
    esta pantalla.
    """

    def __init__(self, usuario, avisar_cambio, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self._avisar_cambio = avisar_cambio  # sin argumentos: le pide a PanelControlPcs que se refresque
        self.item = None
        self.bonos = []
        self.setFixedWidth(260)
        self._armar_interfaz()
        self.mostrar(None)

    def _armar_interfaz(self):
        self.etiqueta_titulo = QLabel("Elegí una estación de la grilla")
        self.etiqueta_titulo.setWordWrap(True)
        self.etiqueta_titulo.setStyleSheet("font-weight: 600; font-size: 15px;")

        self.etiqueta_estado = QLabel("")
        self.etiqueta_estado.setWordWrap(True)

        self.grupo_bonos = QButtonGroup(self)
        self.grupo_bonos.setExclusive(True)
        self.layout_bonos = QVBoxLayout()

        self.combo_metodo = QComboBox()
        for metodo in (dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL, dominio.PAGO_MIXTO):
            self.combo_metodo.addItem(dominio.NOMBRE_METODO_PAGO[metodo], metodo)

        self.boton_iniciar = QPushButton("Iniciar Sesión")
        aplicar_clase(self.boton_iniciar, "primario")
        self.boton_iniciar.clicked.connect(self._confirmar_bono)

        self.boton_miembro = QPushButton("Abrir con Miembro...")
        self.boton_miembro.clicked.connect(self._abrir_con_miembro)

        self.boton_finalizar = QPushButton("Finalizar Sesión")
        aplicar_clase(self.boton_finalizar, "peligro")
        self.boton_finalizar.clicked.connect(self._finalizar_sesion)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(self.etiqueta_estado)
        layout.addWidget(QLabel("Bono:"))
        layout.addLayout(self.layout_bonos)
        layout.addWidget(QLabel("Método de pago:"))
        layout.addWidget(self.combo_metodo)
        layout.addWidget(self.boton_iniciar)
        layout.addWidget(self.boton_miembro)
        layout.addWidget(self.boton_finalizar)
        layout.addStretch()
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def mostrar(self, item):
        """`item` es un elemento de pcs_repo.estado_estaciones(), o None
        si no hay ninguna estación seleccionada en la grilla."""
        self.item = item
        hay_estacion = item is not None
        self.etiqueta_estado.setVisible(hay_estacion)
        for widget in (self.combo_metodo, self.boton_iniciar, self.boton_miembro, self.boton_finalizar):
            widget.setEnabled(hay_estacion)

        while self.layout_bonos.count():
            hijo = self.layout_bonos.takeAt(0)
            if hijo.widget():
                hijo.widget().deleteLater()
        for boton in self.grupo_bonos.buttons():
            self.grupo_bonos.removeButton(boton)

        if not hay_estacion:
            self.etiqueta_titulo.setText("Elegí una estación de la grilla")
            self.bonos = []
            return

        estacion = item["estacion"]
        sesion = item["sesion"]
        self.etiqueta_titulo.setText(estacion["nombre"])
        if sesion is None:
            self.etiqueta_estado.setText("🔒 Bloqueada — sin sesión activa.")
            self.boton_iniciar.setText("Iniciar Sesión")
            self.boton_finalizar.setEnabled(False)
        else:
            quien = sesion["miembro_nombre"] or "Bono"
            texto = f"▶ Activa — {formato_tiempo(item['segundos_restantes'])} restantes ({quien})."
            if item["esperando_cliente"]:
                texto += "\n⏳ El tiempo ya corre; la PC lo toma sola cuando el cliente la prenda."
            self.etiqueta_estado.setText(texto)
            self.boton_iniciar.setText("Agregar Bono")

        self.bonos = pcs_repo.listar_bonos()
        for indice, bono in enumerate(self.bonos):
            boton = QPushButton(f"{bono['nombre']} — {formato_pesos(bono['precio'])}")
            boton.setCheckable(True)
            boton.setChecked(indice == 0)
            # Se crean después de _armar_interfaz, así que no los alcanzó
            # sin_boton_por_defecto: hay que hacerlo uno por uno.
            boton.setAutoDefault(False)
            boton.setDefault(False)
            self.grupo_bonos.addButton(boton, bono["id"])
            self.layout_bonos.addWidget(boton)
        self.boton_iniciar.setEnabled(bool(self.bonos))

    @manejar_errores
    def _confirmar_bono(self):
        if self.item is None:
            return
        if not self.bonos:
            mostrar_error(self, "Sin bonos", "Todavía no hay ningún bono de tiempo cargado — "
                                              "creá uno primero desde 'Gestionar Bonos'.")
            return
        bono_id = self.grupo_bonos.checkedId()
        bono = next(b for b in self.bonos if b["id"] == bono_id)
        metodo = self.combo_metodo.currentData()
        pagos = resolver_pagos(self, metodo, bono["precio"])
        if pagos is None:
            return
        pcs_repo.asignar_bono(self.item["estacion"]["id"], bono_id, self.usuario["id"], pagos)
        self._avisar_cambio()

    def _abrir_con_miembro(self):
        if self.item is None:
            return
        dialogo = DialogoLoginMiembro(self.item["estacion"], self)
        if dialogo.exec():
            self._avisar_cambio()

    @manejar_errores
    def _finalizar_sesion(self):
        if self.item is None or self.item["sesion"] is None:
            return
        estacion_nombre = self.item["estacion"]["nombre"]
        segundos_restantes = self.item["segundos_restantes"]
        # Caso típico: el cliente pidió un bono de 3hs y se va antes -- el
        # mostrador tiene que poder cerrarle la PC ya mismo aunque le
        # quede tiempo pago, por eso el aviso deja bien claro cuánto se
        # está por perder en vez de una advertencia genérica.
        if segundos_restantes:
            aviso = (
                f"Todavía le quedan {formato_tiempo(segundos_restantes)} disponibles a "
                f"'{estacion_nombre}'.\n\n¿Cerrarla de todas formas? El tiempo no usado "
                "no se reintegra."
            )
        else:
            aviso = (
                f"¿Finalizar la sesión de '{estacion_nombre}'? "
                "El tiempo que no se llegó a usar no se reintegra."
            )
        if confirmar(self, "Confirmar", aviso):
            pcs_repo.finalizar_sesion(self.item["sesion"]["id"])
            self._avisar_cambio()


class DialogoLoginMiembro(QDialog):
    """
    A diferencia de vender un bono (lo maneja el Operador, que elige el
    bono desde PanelDetalleEstacion), acá el Miembro se loguea SOLO con
    su usuario y contraseña — pensado para que lo tipee el socio mismo en
    el mostrador. No hay que elegir cuánto tiempo asignar: entrar con las
    credenciales correctas alcanza, se usa todo el saldo disponible en
    ese momento (ver miembros_repo.abrir_estacion_por_miembro).
    """

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Abrir PC con Miembro — {estacion['nombre']}")
        self.resize(340, 200)
        self._armar_interfaz()

    def _armar_interfaz(self):
        etiqueta = QLabel(f"Ingresá tu usuario y contraseña de socio para abrir '{self.estacion['nombre']}':")
        etiqueta.setWordWrap(True)

        self.campo_usuario = QLineEdit()
        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)

        boton_ingresar = QPushButton("Ingresar")
        aplicar_clase(boton_ingresar, "primario")
        boton_ingresar.clicked.connect(self._confirmar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_ingresar)
        botones.addWidget(boton_cancelar)

        layout = QVBoxLayout()
        layout.addWidget(etiqueta)
        layout.addWidget(QLabel("Usuario:"))
        layout.addWidget(self.campo_usuario)
        layout.addWidget(QLabel("Contraseña:"))
        layout.addWidget(self.campo_clave)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_usuario, self.campo_clave, accion_final=self._confirmar)
        sin_boton_por_defecto(self)
        self.campo_usuario.setFocus()

    @manejar_errores
    def _confirmar(self):
        usuario = self.campo_usuario.text().strip()
        clave = self.campo_clave.text()
        if not usuario or not clave:
            mostrar_error(self, "Faltan datos", "Ingresá tu usuario y tu contraseña.")
            return
        resultado = miembros_repo.abrir_estacion_por_miembro(self.estacion["id"], usuario, clave)
        mostrar_info(
            self, "PC activada",
            f"Hola {resultado['miembro']}, se activó '{self.estacion['nombre']}' con "
            f"{formato_tiempo(resultado['minutos_usados'] * 60)} de tu saldo."
        )
        self.accept()
