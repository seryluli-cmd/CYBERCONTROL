"""
pcs_window.py
==============
Control de PCs: `PanelControlPcs`, una lista de estaciones (una fila por
PC, con el color de fondo de toda la fila según su estado — numerada
automáticamente por Qt como una planilla) con su panel lateral para
operar la estación seleccionada — se embebe como pantalla principal en
ui/main_window.py, porque asignarle un bono a una PC (o dejar que un
Miembro se loguee solo) es una venta más del día a día, igual que
"Vender" del kiosko: cualquier usuario logueado puede operarla.

Si la lista aparece vacía no es un error: significa que todavía no se
cargó ninguna fila en `estaciones` (ver "Gestionar Estaciones" en
AdministrarKioskoWindow, ui/main_window.py) — sin estaciones no hay nada
que listar acá.

Los diálogos para ADMINISTRAR los catálogos de Estaciones y de Bonos de
Tiempo (`DialogoGestionEstaciones`/`DialogoGestionBonos`, mismo espíritu
que "Gestionar Rubros" en Artículos) también viven acá, pero se abren
desde `AdministrarKioskoWindow` (ui/main_window.py), no desde este panel
— esa es la parte reservada a encargados.
"""

import os
from datetime import datetime

from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (
    QDialog, QWidget, QVBoxLayout, QHBoxLayout, QFrame,
    QTableWidget, QTableWidgetItem, QPushButton, QButtonGroup, QLineEdit,
    QLabel, QComboBox, QTextEdit, QHeaderView, QInputDialog, QSpinBox,
    QDoubleSpinBox, QMenu,
)
from PySide6.QtCore import Qt, QTimer

import dominio
import database
from control_pcs.repositories import agentes_repo, comandos_pc_repo, miembros_repo, pcs_repo
from ui.dialogo_pago import resolver_pagos
from ui.utils import (
    formato_pesos, formato_tiempo, mostrar_error, mostrar_info, confirmar, manejar_errores,
    aplicar_clase, encadenar_enter,
)

# Cuántos segundos se espera, como máximo, la captura de pantalla que
# sube el agente después de un comando SCREENSHOT (ver DialogoCaptura) --
# tiene que ser más que INTERVALO_CONSULTA_MS del agente (5s) para darle
# margen a que la reciba en su próximo ciclo y la suba.
SEGUNDOS_ESPERA_CAPTURA = 20

# Cada cuántos milisegundos se recalcula el tiempo restante de las
# estaciones activas y se dan de baja solas las sesiones vencidas.
INTERVALO_REFRESCO_MS = 5000

# Por debajo de este tiempo restante, una fila en uso pasa a mostrarse en
# ámbar (⚠) en vez de amarillo, como aviso de que hay que renovarla pronto.
UMBRAL_POR_VENCER_SEGUNDOS = 5 * 60

# Colores de fondo de fila según estado (mismo criterio en toda la
# pantalla: verde disponible (prendida y enlazada, sin nadie usándola),
# amarillo en uso (con sesión activa, ámbar si está por vencer), rojo sin
# conexión (apagada, agente caído, o sin red hacia el mostrador -- ver
# pcs_repo.registrar_conexion/UMBRAL_ENLACE_SEGUNDOS).
COLOR_DISPONIBLE = QColor("#DCF3E1")
COLOR_EN_USO = QColor("#FDF1C7")
COLOR_POR_VENCER = QColor("#FCEBD2")
COLOR_DESCONECTADA = QColor("#F8D7D9")


def _texto_evento(evento) -> str:
    """
    Convierte un evento de pcs_repo.actividad_reciente() en una línea de
    texto para el panel de actividad. El repo devuelve datos crudos; el
    formato ("$ 6.700", "2h 05m") se arma acá porque es un tema de
    presentación, no de negocio.
    """
    hora = datetime.fromisoformat(evento["fecha"]).strftime("%H:%M")
    tipo = evento["tipo"]
    if tipo == "INICIO":
        return f"{hora} — {evento['estacion_nombre']}: sesión iniciada."
    if tipo == "FIN":
        return f"{hora} — {evento['estacion_nombre']}: sesión finalizada."
    if tipo == "BONO":
        return (f"{hora} — {evento['estacion_nombre']}: bono '{evento['bono_nombre']}' "
                f"cobrado ({formato_pesos(evento['precio'])}).")
    if tipo == "CARGA":
        return f"{hora} — {formato_pesos(evento['monto'])} cargados a {evento['miembro_nombre']}."
    if tipo == "CONSUMO":
        return (f"{hora} — {evento['miembro_nombre']} abrió {evento['estacion_nombre']} "
                f"con su saldo ({formato_tiempo(evento['minutos'] * 60)}).")
    if tipo == "REINTEGRO":
        return f"{hora} — {formato_tiempo(evento['minutos'] * 60)} reintegrados a {evento['miembro_nombre']}."
    return hora


class PanelControlPcs(QWidget):
    """
    Grilla de estaciones + panel de detalle + actividad reciente. Se
    instancia una sola vez por sesión, como `centralWidget` de
    `ui/main_window.py:MainWindow` — no es un diálogo que se abre y se
    cierra, por eso el timer de refresco lo para quien lo contiene
    (`detener_actualizacion`, llamado desde `MainWindow.closeEvent`) en
    vez de colgarse de una señal `finished` como antes (QWidget no la
    tiene, esa es cosa de QDialog).
    """

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self._estados = []
        self._estacion_id_seleccionada = None
        self._armar_interfaz()
        self._refrescar()

        self._timer = QTimer(self)
        self._timer.setInterval(INTERVALO_REFRESCO_MS)
        self._timer.timeout.connect(self._refrescar)
        self._timer.start()

    def detener_actualizacion(self):
        self._timer.stop()

    def _armar_interfaz(self):
        self.tabla = QTableWidget(0, 4)
        self.tabla.setHorizontalHeaderLabels(["Estación", "Estado", "Tiempo restante", "Quién"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        # Solo "Estación" se estira para ocupar el ancho libre; el resto
        # se ajusta a su contenido — si no, con una sola columna en
        # Stretch las otras tres quedan con el ancho mínimo por defecto y
        # el texto ("🔒 Bloqueada", "Tiempo restante") se corta con "...".
        encabezado = self.tabla.horizontalHeader()
        encabezado.setSectionResizeMode(0, QHeaderView.Stretch)
        for columna in (1, 2, 3):
            encabezado.setSectionResizeMode(columna, QHeaderView.ResizeToContents)
        self.tabla.itemSelectionChanged.connect(self._al_cambiar_seleccion)
        self.tabla.setContextMenuPolicy(Qt.CustomContextMenu)
        self.tabla.customContextMenuRequested.connect(self._mostrar_menu_contextual)

        self.panel_detalle = PanelDetalleEstacion(self.usuario, self._refrescar, self)

        fila_principal = QHBoxLayout()
        fila_principal.addWidget(self.tabla, 1)
        fila_principal.addWidget(self.panel_detalle)

        self.panel_actividad = PanelActividad()

        layout = QVBoxLayout()
        layout.addLayout(fila_principal, 1)
        layout.addWidget(QLabel("Actividad reciente:"))
        layout.addWidget(self.panel_actividad)
        self.setLayout(layout)

    @manejar_errores
    def _refrescar(self):
        estados = pcs_repo.estado_estaciones()
        # Cualquier sesión que ya llegó a 0 se da de baja acá mismo, sin
        # esperar a que alguien abra la pantalla de nuevo: es el "job de
        # vencimiento" de este módulo (mismo criterio que
        # turnos.turno_vencimiento, se resuelve por comparación de
        # fecha en cada refresco, no con un temporizador que dispare una
        # alarma en el medio).
        alguna_vencio = False
        for item in estados:
            if item["sesion"] is not None and item["segundos_restantes"] == 0:
                pcs_repo.finalizar_sesion(item["sesion"]["id"])
                alguna_vencio = True
        if alguna_vencio:
            estados = pcs_repo.estado_estaciones()

        self._estados = estados
        self._reconstruir_tabla()
        self.panel_actividad.actualizar()

    def _reconstruir_tabla(self):
        # blockSignals evita que cada fila insertada dispare
        # itemSelectionChanged antes de tiempo — solo nos interesa esa
        # señal en el selectRow() de más abajo, para reponer la selección
        # una vez que la tabla ya está completa.
        self.tabla.blockSignals(True)
        self.tabla.setRowCount(0)
        fila_a_seleccionar = -1
        for item in self._estados:
            estacion = item["estacion"]
            sesion = item["sesion"]
            segundos = item["segundos_restantes"]

            if sesion is not None:
                quien_texto = sesion["miembro_nombre"] or "Bono"
                restante_texto = formato_tiempo(segundos)
                if segundos <= UMBRAL_POR_VENCER_SEGUNDOS:
                    icono, texto_estado, color = "⚠", "Por vencer", COLOR_POR_VENCER
                else:
                    icono, texto_estado, color = "▶", "En uso", COLOR_EN_USO
            elif item["enlazada"]:
                icono, texto_estado, color = "✓", "Disponible", COLOR_DISPONIBLE
                restante_texto, quien_texto = "—", "—"
            else:
                icono, texto_estado, color = "🔌", "Sin conexión", COLOR_DESCONECTADA
                restante_texto, quien_texto = "—", "—"

            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            valores = (estacion["nombre"], f"{icono} {texto_estado}", restante_texto, quien_texto)
            for columna, valor in enumerate(valores):
                celda = QTableWidgetItem(valor)
                celda.setBackground(color)
                self.tabla.setItem(fila, columna, celda)

            if estacion["id"] == self._estacion_id_seleccionada:
                fila_a_seleccionar = fila

        self.tabla.blockSignals(False)
        if fila_a_seleccionar >= 0:
            self.tabla.selectRow(fila_a_seleccionar)  # dispara _al_cambiar_seleccion, que actualiza el panel
        else:
            self._estacion_id_seleccionada = None
            self.panel_detalle.mostrar(None)

    def _al_cambiar_seleccion(self):
        fila = self.tabla.currentRow()
        if 0 <= fila < len(self._estados):
            item = self._estados[fila]
            self._estacion_id_seleccionada = item["estacion"]["id"]
            self.panel_detalle.mostrar(item)
        else:
            self._estacion_id_seleccionada = None
            self.panel_detalle.mostrar(None)

    def _mostrar_menu_contextual(self, posicion):
        """
        Control remoto de la estación (clic derecho sobre una fila):
        cerrar la sesión ya (aunque tenga tiempo/saldo sin usar) y dejar
        la PC lista para el próximo cliente, reiniciar, apagar, mandar un
        mensaje o pedir una captura de pantalla. No pasa por el panel
        lateral porque son acciones sobre la PC física (o que necesitan
        efecto inmediato), no sobre la sesión de tiempo como elegir un
        bono. Reiniciar/Apagar/Mensaje/Captura viajan al agente de esa
        estación como un comando pendiente (ver comandos_pc_repo.py); no
        son instantáneas, tardan hasta el próximo ciclo de 5s del agente
        -- "Cerrar sesión" sí corta el tiempo ya mismo en la base (mismo
        mecanismo que "Finalizar Sesión" del panel lateral) y de paso
        encola el reinicio.
        """
        fila = self.tabla.rowAt(posicion.y())
        if fila < 0 or fila >= len(self._estados):
            return
        self.tabla.selectRow(fila)
        item = self._estados[fila]
        estacion = item["estacion"]
        sesion = item["sesion"]
        segundos_restantes = item["segundos_restantes"]

        menu = QMenu(self)
        accion_cerrar_sesion = menu.addAction("🔒 Cerrar sesión y reiniciar")
        accion_cerrar_sesion.setEnabled(sesion is not None)
        menu.addSeparator()
        accion_reiniciar = menu.addAction("🔄 Reiniciar PC")
        accion_apagar = menu.addAction("⏻ Apagar PC")
        menu.addSeparator()
        accion_mensaje = menu.addAction("💬 Enviar mensaje...")
        accion_captura = menu.addAction("📷 Sacar captura de pantalla")

        # menu.exec() abre un bucle de eventos anidado: mientras el menú
        # sigue abierto, el timer de refresco (cada 5s) puede disparar
        # igual y reconstruir toda la tabla de estaciones por debajo. Si
        # el mostrador tarda un poco en elegir una opción, eso llegó a
        # borrar el propio menú a mitad de camino y explotaba con
        # "libshiboken: Internal C++ object (QMenu) already deleted" justo
        # al leer qué se eligió. Se pausa el refresco mientras el menú
        # está abierto y se reanuda apenas se cierra (elija algo o no).
        self._timer.stop()
        try:
            elegida = menu.exec(self.tabla.viewport().mapToGlobal(posicion))
        finally:
            self._timer.start()

        if elegida == accion_cerrar_sesion:
            self._cerrar_sesion_y_reiniciar(estacion, sesion, segundos_restantes)
        elif elegida == accion_reiniciar:
            self._confirmar_y_encolar(
                estacion, comandos_pc_repo.TIPO_REINICIAR,
                f"¿Reiniciar '{estacion['nombre']}' ahora?\n"
                "Se pierde cualquier trabajo sin guardar en esa PC.",
            )
        elif elegida == accion_apagar:
            self._confirmar_y_encolar(
                estacion, comandos_pc_repo.TIPO_APAGAR,
                f"¿Apagar '{estacion['nombre']}' ahora?\n"
                "Se pierde cualquier trabajo sin guardar en esa PC.",
            )
        elif elegida == accion_mensaje:
            self._enviar_mensaje(estacion)
        elif elegida == accion_captura:
            DialogoCaptura(estacion, self).exec()

    @manejar_errores
    def _cerrar_sesion_y_reiniciar(self, estacion, sesion, segundos_restantes):
        """
        Caso típico: el cliente pidió un bono de 3hs y se va antes de
        tiempo -- el mostrador tiene que poder liberar la PC ya mismo,
        sin esperar a que se le acabe el tiempo pago, y dejarla lista
        para el que sigue. Corta la sesión en la base YA (mismo mecanismo
        que "Finalizar Sesión" del panel lateral, `pcs_repo.finalizar_sesion`
        -- un bono no reintegra el tiempo no usado, pero el saldo de un
        Miembro sí) y de paso encola un reinicio: sin reiniciar, la PC
        queda con la sesión de Windows del cliente anterior abierta y sus
        programas corriendo, no "lista para usar" para el próximo.
        """
        if sesion is None:
            return
        if segundos_restantes:
            aviso = (
                f"Todavía le quedan {formato_tiempo(segundos_restantes)} disponibles a "
                f"'{estacion['nombre']}'.\n\n¿Cerrar la sesión y reiniciar la PC de todas "
                "formas? El tiempo no usado no se reintegra."
            )
        else:
            aviso = (
                f"¿Cerrar la sesión de '{estacion['nombre']}' y reiniciar la PC?\n"
                "El tiempo que no se llegó a usar no se reintegra."
            )
        if not confirmar(self, "Confirmar", aviso):
            return
        pcs_repo.finalizar_sesion(sesion["id"])
        comandos_pc_repo.encolar_comando(estacion["id"], comandos_pc_repo.TIPO_REINICIAR)
        mostrar_info(
            self, "Listo",
            f"Sesión cerrada. '{estacion['nombre']}' se va a reiniciar en los próximos "
            "segundos y va a quedar lista para el próximo cliente.",
        )
        self._refrescar()

    @manejar_errores
    def _confirmar_y_encolar(self, estacion, tipo, texto_confirmacion):
        if not confirmar(self, "Confirmar", texto_confirmacion):
            return
        comandos_pc_repo.encolar_comando(estacion["id"], tipo)
        mostrar_info(
            self, "Enviado",
            f"Se le va a avisar a '{estacion['nombre']}' en los próximos segundos.",
        )

    @manejar_errores
    def _enviar_mensaje(self, estacion):
        texto, aceptado = QInputDialog.getMultiLineText(
            self, f"Mensaje para {estacion['nombre']}", "Texto del mensaje:"
        )
        texto = texto.strip()
        if not aceptado or not texto:
            return
        comandos_pc_repo.encolar_comando(estacion["id"], comandos_pc_repo.TIPO_MENSAJE, texto)
        mostrar_info(
            self, "Enviado",
            f"El mensaje le va a aparecer a '{estacion['nombre']}' en los próximos segundos.",
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
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

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
            self.etiqueta_estado.setText(
                f"▶ Activa — {formato_tiempo(item['segundos_restantes'])} restantes ({quien})."
            )
            self.boton_iniciar.setText("Agregar Bono")

        self.bonos = pcs_repo.listar_bonos()
        for indice, bono in enumerate(self.bonos):
            boton = QPushButton(f"{bono['nombre']} — {formato_pesos(bono['precio'])}")
            boton.setCheckable(True)
            boton.setChecked(indice == 0)
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


class PanelActividad(QTextEdit):
    """
    Log de los últimos movimientos (sesiones, bonos, saldo de socios) en
    la parte de abajo de la pantalla. De solo lectura: se repuebla entero
    en cada refresco con pcs_repo.actividad_reciente(), no acumula texto
    a mano (así nunca se desincroniza de lo que hay realmente en la base).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFixedHeight(130)

    def actualizar(self):
        eventos = pcs_repo.actividad_reciente()
        lineas = [_texto_evento(evento) for evento in reversed(eventos)]
        self.setPlainText("\n".join(lineas))
        barra = self.verticalScrollBar()
        barra.setValue(barra.maximum())


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
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)
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


class DialogoCaptura(QDialog):
    """
    Pide una captura de pantalla a una estación y la muestra apenas
    llega. No es instantáneo: el agente de esa PC recién la toma y la
    sube cuando le llega el comando en su próxima consulta de estado
    (hasta 5s, ver comandos_pc_repo.py) -- por eso este diálogo se queda
    revisando con un QTimer en vez de traer la imagen de una sola vez.
    """

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Captura de pantalla — {estacion['nombre']}")
        self.resize(520, 420)

        self.etiqueta_estado = QLabel("Esperando que la PC responda...")
        self.etiqueta_estado.setAlignment(Qt.AlignCenter)
        self.etiqueta_imagen = QLabel()
        self.etiqueta_imagen.setAlignment(Qt.AlignCenter)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        boton_cerrar.setAutoDefault(False)
        boton_cerrar.setDefault(False)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_estado)
        layout.addWidget(self.etiqueta_imagen, 1)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)

        self.comando_id = comandos_pc_repo.encolar_comando(estacion["id"], comandos_pc_repo.TIPO_SCREENSHOT)
        self._segundos_esperados = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._revisar)
        self._timer.start()

    def _revisar(self):
        self._segundos_esperados += 1
        fila = comandos_pc_repo.obtener_comando(self.comando_id)
        if fila is not None and fila["resultado"]:
            self._timer.stop()
            ruta_completa = os.path.join(database.DATA_DIR, fila["resultado"])
            pixmap = QPixmap(ruta_completa)
            if pixmap.isNull():
                self.etiqueta_estado.setText("Llegó una respuesta pero no se pudo leer la imagen.")
                return
            self.etiqueta_estado.setText(f"Captura de '{self.estacion['nombre']}':")
            self.etiqueta_imagen.setPixmap(
                pixmap.scaled(480, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation)
            )
            return
        if self._segundos_esperados >= SEGUNDOS_ESPERA_CAPTURA:
            self._timer.stop()
            self.etiqueta_estado.setText(
                "No llegó respuesta a tiempo — revisá que la PC esté prendida "
                "y conectada a la red, o probá de nuevo."
            )


class DialogoGestionEstaciones(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Estaciones")
        self.resize(360, 420)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.lista = QTableWidget(0, 1)
        self.lista.setHorizontalHeaderLabels(["Estación"])
        self.lista.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.lista.horizontalHeader().setVisible(False)
        self.lista.setSelectionBehavior(QTableWidget.SelectRows)
        self.lista.setSelectionMode(QTableWidget.SingleSelection)
        self.lista.setEditTriggers(QTableWidget.NoEditTriggers)
        self.lista.setAlternatingRowColors(True)

        self.campo_nuevo = QLineEdit()
        self.campo_nuevo.setPlaceholderText("Nombre de la estación nueva (ej. PC 5)...")
        boton_agregar = QPushButton("Agregar")
        aplicar_clase(boton_agregar, "primario")
        boton_agregar.clicked.connect(self._agregar)
        encadenar_enter(self.campo_nuevo, accion_final=self._agregar)

        fila_agregar = QHBoxLayout()
        fila_agregar.addWidget(self.campo_nuevo)
        fila_agregar.addWidget(boton_agregar)

        boton_renombrar = QPushButton("Renombrar seleccionada")
        boton_renombrar.clicked.connect(self._renombrar)
        boton_desactivar = QPushButton("Desactivar seleccionada")
        aplicar_clase(boton_desactivar, "peligro")
        boton_desactivar.clicked.connect(self._desactivar)

        fila_acciones = QHBoxLayout()
        fila_acciones.addWidget(boton_renombrar)
        fila_acciones.addWidget(boton_desactivar)

        boton_clave_agentes = QPushButton("Generar/renovar clave de agentes...")
        boton_clave_agentes.clicked.connect(self._generar_clave_agentes)

        boton_clave_admin = QPushButton("Cambiar contraseña de PC clientes...")
        boton_clave_admin.clicked.connect(self._cambiar_clave_admin_pcs)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Estaciones activas:"))
        layout.addWidget(self.lista)
        layout.addLayout(fila_agregar)
        layout.addLayout(fila_acciones)
        layout.addWidget(boton_clave_agentes)
        layout.addWidget(boton_clave_admin)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)
        self.campo_nuevo.setFocus()

    @manejar_errores
    def _cargar(self):
        self.estaciones = pcs_repo.listar_estaciones()
        self.lista.setRowCount(0)
        for estacion in self.estaciones:
            fila = self.lista.rowCount()
            self.lista.insertRow(fila)
            self.lista.setItem(fila, 0, QTableWidgetItem(estacion["nombre"]))

    def _seleccionada(self):
        fila = self.lista.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero una estación de la lista.")
            return None
        return self.estaciones[fila]

    @manejar_errores
    def _agregar(self):
        nombre = self.campo_nuevo.text().strip()
        if not nombre:
            mostrar_error(self, "Falta el nombre", "Escribí el nombre de la estación nueva.")
            return
        pcs_repo.crear_estacion(nombre)
        self.campo_nuevo.clear()
        self._cargar()
        self.campo_nuevo.setFocus()

    @manejar_errores
    def _renombrar(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        nuevo_nombre, aceptado = QInputDialog.getText(
            self, "Renombrar estación", "Nuevo nombre:", text=estacion["nombre"]
        )
        if not aceptado:
            return
        pcs_repo.renombrar_estacion(estacion["id"], nuevo_nombre)
        self._cargar()

    @manejar_errores
    def _desactivar(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar '{estacion['nombre']}'? Deja de listarse acá, pero su "
                     "historial de sesiones se conserva."):
            pcs_repo.desactivar_estacion(estacion["id"])
            self._cargar()

    @manejar_errores
    def _generar_clave_agentes(self):
        """
        Genera (o rota) la clave única que exige `servidor_red.py` en el
        header `Authorization` de cada agente (ver AGENTE PC KIOSKO,
        `red_kiosko._cabeceras_agente`). Al rotarla, la clave anterior
        deja de servir para CUALQUIER PC hasta que se la actualice ahí --
        por eso pide confirmación explícita si ya había una generada.
        """
        clave_actual = agentes_repo.obtener_clave_agentes()
        if clave_actual:
            aviso = (
                "Se va a generar una clave nueva para los agentes.\n\n"
                "Esto ROTA la clave de las estaciones que ya están conectadas: "
                "la anterior deja de servir para cualquier PC hasta que se "
                "actualice ahí con la nueva. ¿Continuar?"
            )
        else:
            aviso = "Se va a generar la clave que necesitan los agentes de bloqueo para conectarse a este servidor. ¿Continuar?"
        if not confirmar(self, "Generar/renovar clave de agentes", aviso):
            return
        clave_nueva = agentes_repo.generar_clave_agentes()
        QInputDialog.getText(
            self, "Clave de agentes generada",
            "Copiá esta clave (Ctrl+A, Ctrl+C) y pegala en el config.json\n"
            "o en el asistente de configuración de cada PC cliente:",
            text=clave_nueva,
        )

    @manejar_errores
    def _cambiar_clave_admin_pcs(self):
        """
        Contraseña que destraba el panel admin en la pantalla de bloqueo
        de cada PC cliente (ícono "A", ver agente_bloqueo.py). A
        diferencia de la clave de agentes, la elige el dueño (tiene que
        poder recordarla) y cada PC cliente la actualiza sola en su
        próximo `GET /estado` -- no hace falta ir PC por PC.
        """
        nueva, aceptado = QInputDialog.getText(
            self, "Cambiar contraseña de PC clientes",
            "Nueva contraseña de administrador:",
            QLineEdit.EchoMode.Password,
        )
        if not aceptado:
            return
        if len(nueva) < 4:
            mostrar_error(self, "Contraseña muy corta", "Usá al menos 4 caracteres.")
            return
        confirmacion, aceptado = QInputDialog.getText(
            self, "Cambiar contraseña de PC clientes",
            "Repetí la contraseña:",
            QLineEdit.EchoMode.Password,
        )
        if not aceptado:
            return
        if confirmacion != nueva:
            mostrar_error(self, "No coincide", "Las dos contraseñas no son iguales.")
            return
        agentes_repo.establecer_clave_admin_pcs(nueva)
        mostrar_info(
            self, "Listo",
            "Contraseña actualizada. Cada PC cliente la va a tomar sola "
            "la próxima vez que se conecte con el Servidor (hasta 5 "
            "segundos, si ya está prendida y conectada)."
        )


class DialogoGestionBonos(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Gestionar Bonos de Tiempo")
        self.resize(460, 440)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.tabla = QTableWidget(0, 3)
        self.tabla.setHorizontalHeaderLabels(["Nombre", "Tiempo", "Precio"])
        self.tabla.setSelectionBehavior(QTableWidget.SelectRows)
        self.tabla.setSelectionMode(QTableWidget.SingleSelection)
        self.tabla.setEditTriggers(QTableWidget.NoEditTriggers)
        self.tabla.setAlternatingRowColors(True)
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)

        boton_nuevo = QPushButton("Nuevo")
        aplicar_clase(boton_nuevo, "primario")
        boton_nuevo.clicked.connect(self._nuevo)
        boton_modificar = QPushButton("Modificar")
        boton_modificar.clicked.connect(self._modificar)
        boton_desactivar = QPushButton("Desactivar")
        aplicar_clase(boton_desactivar, "peligro")
        boton_desactivar.clicked.connect(self._desactivar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        barra_botones = QHBoxLayout()
        for boton in (boton_nuevo, boton_modificar, boton_desactivar, boton_cerrar):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _cargar(self):
        self.bonos = pcs_repo.listar_bonos()
        self.tabla.setRowCount(0)
        for bono in self.bonos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(bono["nombre"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(formato_tiempo(bono["minutos"] * 60)))
            self.tabla.setItem(fila, 2, QTableWidgetItem(formato_pesos(bono["precio"])))

    def _seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un bono de la lista.")
            return None
        return self.bonos[fila]

    def _nuevo(self):
        dialogo = DialogoBono(self)
        if dialogo.exec():
            self._cargar()

    def _modificar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        dialogo = DialogoBono(self, bono)
        if dialogo.exec():
            self._cargar()

    @manejar_errores
    def _desactivar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        if confirmar(self, "Confirmar",
                     f"¿Desactivar el bono '{bono['nombre']}'? Deja de poder venderse, pero "
                     "las sesiones que ya lo usaron conservan su historial."):
            pcs_repo.desactivar_bono(bono["id"])
            self._cargar()


class DialogoBono(QDialog):
    """Alta/edición de un bono de tiempo. El tiempo se carga en horas y
    minutos por separado (en pasos de 30 min) porque acá nunca se vende
    por minuto suelto — solo combos prearmados como "3 horas" o
    "1 hora y media"."""

    def __init__(self, parent, bono=None):
        super().__init__(parent)
        self.bono = bono
        self.setWindowTitle("Modificar Bono" if bono else "Nuevo Bono")
        self.resize(340, 260)
        self._armar_interfaz()
        if bono:
            self._cargar_datos(bono)

    def _armar_interfaz(self):
        self.campo_nombre = QLineEdit()
        self.campo_nombre.setPlaceholderText("Ej: 3 horas")

        self.spin_horas = QSpinBox()
        self.spin_horas.setRange(0, 99)
        self.spin_minutos = QSpinBox()
        self.spin_minutos.setRange(0, 30)
        self.spin_minutos.setSingleStep(30)
        fila_tiempo = QHBoxLayout()
        fila_tiempo.addWidget(self.spin_horas)
        fila_tiempo.addWidget(QLabel("hs"))
        fila_tiempo.addWidget(self.spin_minutos)
        fila_tiempo.addWidget(QLabel("min"))

        self.spin_precio = QDoubleSpinBox()
        self.spin_precio.setMaximum(99_999_999)
        self.spin_precio.setPrefix("$ ")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.campo_nombre)
        layout.addWidget(QLabel("Tiempo:"))
        layout.addLayout(fila_tiempo)
        layout.addWidget(QLabel("Precio:"))
        layout.addWidget(self.spin_precio)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addWidget(boton_guardar)
        botones.addWidget(boton_cancelar)
        layout.addLayout(botones)
        self.setLayout(layout)
        encadenar_enter(self.campo_nombre, self.spin_horas, self.spin_minutos, self.spin_precio,
                         accion_final=self._guardar)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _cargar_datos(self, bono):
        self.campo_nombre.setText(bono["nombre"])
        self.spin_horas.setValue(bono["minutos"] // 60)
        self.spin_minutos.setValue(bono["minutos"] % 60)
        self.spin_precio.setValue(bono["precio"])

    @manejar_errores
    def _guardar(self):
        nombre = self.campo_nombre.text().strip()
        minutos = self.spin_horas.value() * 60 + self.spin_minutos.value()
        precio = self.spin_precio.value()
        if self.bono:
            pcs_repo.modificar_bono(self.bono["id"], nombre, minutos, precio)
        else:
            pcs_repo.crear_bono(nombre, minutos, precio)
        self.accept()
