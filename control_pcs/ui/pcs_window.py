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
    QDoubleSpinBox, QMenu, QSlider,
)
from PySide6.QtCore import Qt, QTimer

import dominio
import database
from control_pcs.repositories import (
    clientes_repo, comandos_pc_repo, config_red_repo, miembros_repo, pcs_repo,
)
from ui.dialogo_pago import resolver_pagos
from ui.utils import (
    formato_pesos, formato_tiempo, formato_transcurrido, mostrar_error, mostrar_info, confirmar, manejar_errores,
    aplicar_clase, encadenar_enter,
)

# Cuántos segundos se espera, como máximo, la captura de pantalla que
# sube el Cliente PC después de un comando SCREENSHOT (ver DialogoCaptura) --
# tiene que ser más que INTERVALO_CONSULTA_MS del Cliente PC (5s) para darle
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
# conexión (apagada, Cliente PC caído, o sin red hacia el mostrador -- ver
# pcs_repo.registrar_conexion/UMBRAL_ENLACE_SEGUNDOS).
COLOR_DISPONIBLE = QColor("#DCF3E1")
COLOR_EN_USO = QColor("#FDF1C7")
COLOR_POR_VENCER = QColor("#FCEBD2")
COLOR_DESCONECTADA = QColor("#F8D7D9")
# Sesión ya activada por el operador en una PC que el cliente todavía no
# prendió (ver pcs_repo.estado_estaciones, "esperando_cliente"): azul
# calmo, sin parpadeo -- es una espera normal, no una alerta.
COLOR_ESPERANDO_CLIENTE = QColor("#DCE7FD")
# PC sin Cliente PC porque alguien lo cerró desde su panel admin (ver
# accesos_admin_pc_repo): está usable por cualquiera, sin bloqueo ni cobro,
# hasta que el Cliente PC vuelva a arrancar. Lila a propósito, distinto del
# rojo de "Sin conexión" (apagada) para que se note cuál es cuál.
COLOR_CLIENTE_CERRADO_ADMIN = QColor("#E6D5F5")

# Alerta especial (pedido explícito del dueño, 2026-09-30): sesión activa
# (Bono o Miembro) en una estación que dejó de estar "enlazada" -- el
# Cliente PC de esa PC no reportó conexión en el último UMBRAL_ENLACE_SEGUNDOS
# a pesar de tener tiempo pago corriendo. A diferencia del rojo fijo de
# "Sin conexión" (esa es sin sesión, sin apuro: la PC está apagada o
# libre), acá SÍ hay plata/tiempo en juego sin que nadie lo esté viendo
# -- puede ser que un cliente haya encontrado la forma de cerrar el
# Cliente PC para seguir usando la PC sin que se le descuente. Parpadea entre
# estos dos colores para llamar la atención del operador (ver
# PanelControlPcs._alternar_parpadeo) en vez de quedar en el amarillo
# normal de "En uso", que pasaría desapercibido.
COLOR_ALERTA_SESION_SIN_CLIENTE = QColor("#F5A3A8")
COLOR_ALERTA_SESION_SIN_CLIENTE_APAGADA = QColor("#FFFFFF")

# Cada cuánto alterna el parpadeo de una fila en alerta -- rápido a
# propósito, tiene que notarse a simple vista sin mirar fijo la pantalla.
INTERVALO_PARPADEO_MS = 500


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
    if tipo == "TRASLADO":
        return f"{hora} — Sesión pasada de {evento['origen_nombre']} a {evento['destino_nombre']}."
    if tipo == "ADMIN_PC":
        texto = f"{hora} — {evento['estacion_nombre']}: {dominio.NOMBRE_EVENTO_ADMIN_PC[evento['evento_admin']]}"
        if evento["segundos_sin_cliente"] is not None:
            texto += f" (estuvo {formato_tiempo(evento['segundos_sin_cliente'])} sin bloqueo)"
        return texto + "."
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
        self._filas_en_alerta = []
        self._parpadeo_encendido = True
        self._armar_interfaz()
        self._refrescar()

        self._timer = QTimer(self)
        self._timer.setInterval(INTERVALO_REFRESCO_MS)
        self._timer.timeout.connect(self._refrescar)
        self._timer.start()

        # Timer aparte, mucho más rápido, solo para el parpadeo de
        # "sesión activa sin Cliente PC" (ver COLOR_ALERTA_SESION_SIN_CLIENTE) --
        # no puede compartir el timer de arriba, que reconstruye la tabla
        # entera cada 5s (perdería la selección y el parpadeo se vería a
        # los tumbos en vez de parejo).
        self._timer_parpadeo = QTimer(self)
        self._timer_parpadeo.setInterval(INTERVALO_PARPADEO_MS)
        self._timer_parpadeo.timeout.connect(self._alternar_parpadeo)
        self._timer_parpadeo.start()

    def detener_actualizacion(self):
        self._timer.stop()
        self._timer_parpadeo.stop()

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
        self._filas_en_alerta = []
        self._parpadeo_encendido = True
        for item in self._estados:
            estacion = item["estacion"]
            sesion = item["sesion"]
            segundos = item["segundos_restantes"]

            if sesion is not None and not item["enlazada"] and item["esperando_cliente"]:
                # El operador habilitó la PC antes de que el cliente la
                # prendiera -- el tiempo ya corre, pero no es una alerta.
                quien_texto = sesion["miembro_nombre"] or "Bono"
                restante_texto = formato_tiempo(segundos)
                icono, texto_estado, color = "⏳", "Esperando al cliente", COLOR_ESPERANDO_CLIENTE
            elif sesion is not None and not item["enlazada"]:
                # Hay tiempo pago corriendo pero el Cliente PC de esa PC dejó
                # de responder -- ver COLOR_ALERTA_SESION_SIN_CLIENTE. Esto
                # va ANTES que "por vencer"/"en uso": importa más avisar
                # que nadie está viendo esa PC que cuánto tiempo le queda.
                quien_texto = sesion["miembro_nombre"] or "Bono"
                restante_texto = formato_tiempo(segundos)
                texto_alerta = "SIN CLIENTE (revisar)"
                if item["cliente_cerrado_admin_desde"] is not None:
                    texto_alerta = f"SIN CLIENTE (cerrado por admin hace {formato_transcurrido(item['cliente_cerrado_admin_desde'])})"
                icono, texto_estado, color = "🚨", texto_alerta, COLOR_ALERTA_SESION_SIN_CLIENTE
            elif sesion is not None:
                quien_texto = sesion["miembro_nombre"] or "Bono"
                restante_texto = formato_tiempo(segundos)
                if segundos <= UMBRAL_POR_VENCER_SEGUNDOS:
                    icono, texto_estado, color = "⚠", "Por vencer", COLOR_POR_VENCER
                else:
                    icono, texto_estado, color = "▶", "En uso", COLOR_EN_USO
            elif item["enlazada"]:
                icono, texto_estado, color = "✓", "Disponible", COLOR_DISPONIBLE
                restante_texto, quien_texto = "—", "—"
            elif item["cliente_cerrado_admin_desde"] is not None:
                icono, color = "🔓", COLOR_CLIENTE_CERRADO_ADMIN
                texto_estado = f"Sin bloqueo (cerrado por admin hace {formato_transcurrido(item['cliente_cerrado_admin_desde'])})"
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

            if sesion is not None and not item["enlazada"] and not item["esperando_cliente"]:
                self._filas_en_alerta.append(fila)

            if estacion["id"] == self._estacion_id_seleccionada:
                fila_a_seleccionar = fila

        self.tabla.blockSignals(False)
        if fila_a_seleccionar >= 0:
            self.tabla.selectRow(fila_a_seleccionar)  # dispara _al_cambiar_seleccion, que actualiza el panel
        else:
            self._estacion_id_seleccionada = None
            self.panel_detalle.mostrar(None)

    def _alternar_parpadeo(self):
        """
        Alterna el fondo de las filas en `self._filas_en_alerta` entre
        rojo fuerte y blanco cada INTERVALO_PARPADEO_MS -- ver
        COLOR_ALERTA_SESION_SIN_CLIENTE. Corre en un timer aparte del
        refresco de 5s (`_reconstruir_tabla` ya deja los índices de fila
        actualizados cada vez que corre); si no hay ninguna fila en
        alerta no hace nada, así que dejarlo corriendo siempre no cuesta
        nada.
        """
        if not self._filas_en_alerta:
            return
        self._parpadeo_encendido = not self._parpadeo_encendido
        color = (
            COLOR_ALERTA_SESION_SIN_CLIENTE
            if self._parpadeo_encendido
            else COLOR_ALERTA_SESION_SIN_CLIENTE_APAGADA
        )
        for fila in self._filas_en_alerta:
            if fila >= self.tabla.rowCount():
                continue
            for columna in range(self.tabla.columnCount()):
                celda = self.tabla.item(fila, columna)
                if celda is not None:
                    celda.setBackground(color)

    @manejar_errores
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
        mensaje, pedir una captura de pantalla, cambiar a qué módem
        apunta su red o ajustar su volumen. No pasa por el panel lateral
        porque son acciones sobre la PC física (o que necesitan efecto
        inmediato), no sobre la sesión de tiempo como elegir un bono.
        Reiniciar/Apagar/Mensaje/Captura/Cambiar red/Volumen viajan al
        Cliente PC de esa estación como un comando pendiente (ver
        comandos_pc_repo.py); no son instantáneas, tardan hasta el
        próximo ciclo de 5s del Cliente PC -- "Cerrar sesión" sí corta el
        tiempo ya mismo en la base (mismo mecanismo que "Finalizar
        Sesión" del panel lateral) y de paso encola el reinicio.
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
        accion_trasladar = menu.addAction("🔀 Intercambiar de máquina...")
        accion_trasladar.setEnabled(sesion is not None)
        menu.addSeparator()
        accion_reiniciar = menu.addAction("🔄 Reiniciar PC")
        accion_apagar = menu.addAction("⏻ Apagar PC")
        menu.addSeparator()
        accion_mensaje = menu.addAction("💬 Enviar mensaje...")
        accion_captura = menu.addAction("📷 Sacar captura de pantalla")
        menu.addSeparator()
        accion_cambiar_red = menu.addAction("🌐 Cambiar red...")
        accion_volumen = menu.addAction("🔊 Ajustar volumen...")

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
        elif elegida == accion_trasladar:
            if DialogoTrasladarSesion(estacion, self._estados, self.usuario, self).exec():
                self._refrescar()
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
        elif elegida == accion_cambiar_red:
            DialogoCambiarRed(estacion, self).exec()
        elif elegida == accion_volumen:
            DialogoVolumen(estacion, self).exec()

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
    llega. No es instantáneo: el Cliente PC de esa PC recién la toma y la
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


class DialogoCambiarRed(QDialog):
    """
    Cambia la puerta de enlace y el DNS de la estación elegida a uno de
    los módems configurados (ver config_red_repo.py) -- nunca toca la IP
    fija de la PC ni su máscara. Pensado para el caso real del Cyber:
    varios módems en el mismo rango 192.168.1.x y las PCs con IP fija
    propia; si un cliente avisa "no tengo internet" porque se cayó UN
    módem, el mostrador la pasa al otro desde acá en vez de ir hasta la
    PC. A diferencia de Reiniciar/Apagar/Mensaje, este comando SÍ puede
    fallar del lado de la PC (adaptador no encontrado, PowerShell sin
    permisos) -- por eso se queda esperando el resultado con un QTimer,
    igual que DialogoCaptura, en vez de darlo por entregado y listo.
    """

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Cambiar red — {estacion['nombre']}")
        self.resize(360, 280)

        self.etiqueta_estado = QLabel("Elegí a qué módem pasar esta PC:")
        self.etiqueta_estado.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_estado)

        for gateway in config_red_repo.obtener_gateways():
            boton = QPushButton(f"{gateway['nombre']} ({gateway['ip']})")
            boton.clicked.connect(lambda _=False, ip=gateway["ip"]: self._enviar(ip))
            layout.addWidget(boton)

        boton_editar = QPushButton("Editar módems...")
        boton_editar.clicked.connect(self._editar_modems)
        layout.addWidget(boton_editar)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

        self.comando_id = None
        self._segundos_esperados = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._revisar)

    @manejar_errores
    def _enviar(self, ip_gateway):
        if not confirmar(
            self, "Confirmar",
            f"¿Cambiar la puerta de enlace y DNS de '{self.estacion['nombre']}' a {ip_gateway}?",
        ):
            return
        self.comando_id = comandos_pc_repo.encolar_comando(
            self.estacion["id"], comandos_pc_repo.TIPO_CAMBIAR_RED, ip_gateway
        )
        self._segundos_esperados = 0
        self.etiqueta_estado.setText("Esperando que la PC aplique el cambio...")
        self._timer.start()

    def _revisar(self):
        self._segundos_esperados += 1
        fila = comandos_pc_repo.obtener_comando(self.comando_id)
        if fila is not None and fila["resultado"]:
            self._timer.stop()
            if fila["resultado"] == "OK":
                self.etiqueta_estado.setText(
                    f"Listo, '{self.estacion['nombre']}' ya está usando esa puerta de enlace."
                )
            else:
                self.etiqueta_estado.setText(f"No se pudo cambiar: {fila['resultado']}")
            return
        if self._segundos_esperados >= SEGUNDOS_ESPERA_CAPTURA:
            self._timer.stop()
            self.etiqueta_estado.setText(
                "No llegó respuesta a tiempo — revisá que la PC esté prendida "
                "y conectada, o probá de nuevo."
            )

    def _editar_modems(self):
        DialogoEditarGateways(self).exec()
        self.close()  # la lista de botones de arriba quedaría desactualizada -- que lo vuelvan a abrir


class DialogoEditarGateways(QDialog):
    """Catálogo de módems conocidos (nombre + IP de su puerta de enlace),
    editable a mano por cualquier Operador -- no es un dato de plata ni
    de negocio, mismo nivel de confianza que Reiniciar/Apagar. Se guarda
    entero de una (ver config_red_repo.guardar_gateways), no fila por
    fila, porque es una lista chica pensada para editarse de vez en
    cuando, no un catálogo grande con altas/bajas frecuentes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar módems")
        self.resize(380, 320)

        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Nombre", "IP (puerta de enlace)"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for gateway in config_red_repo.obtener_gateways():
            self._agregar_fila(gateway["nombre"], gateway["ip"])

        boton_agregar = QPushButton("Agregar módem")
        boton_agregar.clicked.connect(lambda: self._agregar_fila("", ""))
        boton_quitar = QPushButton("Quitar seleccionado")
        aplicar_clase(boton_quitar, "peligro")
        boton_quitar.clicked.connect(self._quitar_seleccionado)
        fila_botones = QHBoxLayout()
        fila_botones.addWidget(boton_agregar)
        fila_botones.addWidget(boton_quitar)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Módems del local:"))
        layout.addWidget(self.tabla)
        layout.addLayout(fila_botones)
        layout.addWidget(boton_guardar)
        layout.addWidget(boton_cancelar)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    def _agregar_fila(self, nombre, ip):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
        self.tabla.setItem(fila, 1, QTableWidgetItem(ip))

    def _quitar_seleccionado(self):
        fila = self.tabla.currentRow()
        if fila >= 0:
            self.tabla.removeRow(fila)

    @manejar_errores
    def _guardar(self):
        gateways = []
        for fila in range(self.tabla.rowCount()):
            item_nombre = self.tabla.item(fila, 0)
            item_ip = self.tabla.item(fila, 1)
            nombre = item_nombre.text().strip() if item_nombre else ""
            ip = item_ip.text().strip() if item_ip else ""
            if not nombre and not ip:
                continue
            if not nombre or not ip:
                mostrar_error(self, "Fila incompleta", "Cada módem necesita nombre e IP.")
                return
            if not config_red_repo.es_ip_valida(ip):
                mostrar_error(self, "IP inválida", f"'{ip}' no es una IP válida (ej. 192.168.1.201).")
                return
            gateways.append({"nombre": nombre, "ip": ip})
        if not gateways:
            mostrar_error(self, "Nada para guardar", "Agregá al menos un módem con nombre e IP.")
            return
        config_red_repo.guardar_gateways(gateways)
        self.close()


class DialogoTrasladarSesion(QDialog):
    """
    Pasa la sesión activa de `estacion` a otra PC (clic derecho ->
    "Intercambiar de máquina..."): el cliente se sentó en la que había
    libre y quiere su favorita cuando se libera, o dos clientes quieren
    cambiarse de lugar. Libre = se mueve; ocupada = las dos sesiones se
    intercambian. La regla vive en `pcs_repo.trasladar_sesion`; acá solo se
    elige el destino y se explica qué va a pasar con cada PC antes de
    confirmar.
    """

    def __init__(self, estacion, estados, usuario, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.usuario = usuario
        self._ocupadas = {}
        self.setWindowTitle(f"Intercambiar de máquina — {estacion['nombre']}")
        self.resize(460, 230)

        self.combo_destino = QComboBox()
        for item in estados:
            otra = item["estacion"]
            if otra["id"] == estacion["id"]:
                continue
            sesion = item["sesion"]
            segundos = item["segundos_restantes"]
            ocupada = sesion is not None and bool(segundos)
            if ocupada:
                quien = sesion["miembro_nombre"] or "Bono"
                texto = f"{otra['nombre']} — ocupada ({quien}, {formato_tiempo(segundos)})"
            else:
                texto = f"{otra['nombre']} — libre"
            self._ocupadas[otra["id"]] = ocupada
            self.combo_destino.addItem(texto, otra["id"])

        self.etiqueta_efecto = QLabel()
        self.etiqueta_efecto.setWordWrap(True)
        self.combo_destino.currentIndexChanged.connect(lambda _indice: self._actualizar_efecto())

        self.boton_confirmar = QPushButton("Pasar sesión")
        aplicar_clase(self.boton_confirmar, "primario")
        self.boton_confirmar.clicked.connect(self._confirmar)
        self.boton_confirmar.setEnabled(self.combo_destino.count() > 0)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_cancelar)
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"¿A qué PC pasa la sesión de '{estacion['nombre']}'?"))
        layout.addWidget(self.combo_destino)
        layout.addWidget(self.etiqueta_efecto)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)
        self._actualizar_efecto()

    def _actualizar_efecto(self):
        destino_id = self.combo_destino.currentData()
        if destino_id is None:
            self.etiqueta_efecto.setText("No hay otras PCs activas para elegir.")
            return
        origen = self.estacion["nombre"]
        destino = self.combo_destino.currentText().split(" — ")[0]
        if self._ocupadas[destino_id]:
            self.etiqueta_efecto.setText(
                f"'{origen}' y '{destino}' intercambian sus sesiones: cada cliente se pasa a la "
                "PC del otro, cada uno con su propio tiempo restante. Ninguna de las dos se reinicia."
            )
        else:
            self.etiqueta_efecto.setText(
                f"'{origen}' pasa a '{destino}' con todo su tiempo restante, sin cobrar de nuevo. "
                f"'{origen}' se va a bloquear y reiniciar a los pocos segundos: avisale al cliente "
                "antes de confirmar."
            )

    @manejar_errores
    def _confirmar(self):
        destino_id = self.combo_destino.currentData()
        if destino_id is None:
            return
        pcs_repo.trasladar_sesion(self.estacion["id"], destino_id, self.usuario["id"])
        self.accept()


class DialogoVolumen(QDialog):
    """Ajusta el volumen maestro de la estación elegida (0-100%). A
    diferencia de Cambiar red, esto casi no puede fallar del lado de la
    PC (no necesita Administrador, es una propiedad de la sesión del
    usuario actual) -- por eso queda fire-and-forget, mismo criterio que
    Mensaje: se encola y listo, sin esperar confirmación de vuelta."""

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Ajustar volumen — {estacion['nombre']}")
        self.resize(320, 160)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.etiqueta_valor = QLabel("50%")
        self.etiqueta_valor.setAlignment(Qt.AlignCenter)
        self.slider.valueChanged.connect(lambda valor: self.etiqueta_valor.setText(f"{valor}%"))

        boton_aplicar = QPushButton("Aplicar")
        aplicar_clase(boton_aplicar, "primario")
        boton_aplicar.clicked.connect(self._aplicar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Volumen de '{estacion['nombre']}':"))
        layout.addWidget(self.slider)
        layout.addWidget(self.etiqueta_valor)
        layout.addWidget(boton_aplicar)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        for boton in self.findChildren(QPushButton):
            boton.setAutoDefault(False)
            boton.setDefault(False)

    @manejar_errores
    def _aplicar(self):
        nivel = self.slider.value()
        comandos_pc_repo.encolar_comando(
            self.estacion["id"], comandos_pc_repo.TIPO_VOLUMEN, str(nivel)
        )
        mostrar_info(
            self, "Enviado",
            f"El volumen de '{self.estacion['nombre']}' se va a ajustar a {nivel}% en los "
            "próximos segundos.",
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

        # IP de la estación seleccionada: la guarda sola servidor_red.py
        # (self.client_address de cada GET /estado, ver
        # pcs_repo.registrar_conexion) en cuanto el Cliente PC de esa PC hace
        # su primer pedido DESPUÉS de que la estación ya existe acá -- una
        # estación recién creada, o cuyo Cliente PC todavía no conectó, no
        # tiene nada que mostrar. "Traer IP" relee el dato fresco desde la
        # base por si el Cliente PC conectó recién, sin tener que cerrar y
        # volver a abrir todo el diálogo.
        self.campo_ip = QLineEdit()
        self.campo_ip.setReadOnly(True)
        self.campo_ip.setPlaceholderText("Todavía no se conoce")
        boton_traer_ip = QPushButton("Traer IP")
        boton_traer_ip.clicked.connect(self._traer_ip)

        fila_ip = QHBoxLayout()
        fila_ip.addWidget(QLabel("IP de la seleccionada:"))
        fila_ip.addWidget(self.campo_ip)
        fila_ip.addWidget(boton_traer_ip)

        self.lista.itemSelectionChanged.connect(self._al_cambiar_seleccion)

        boton_clave_clientes = QPushButton("Generar/renovar clave de Clientes PC...")
        boton_clave_clientes.clicked.connect(self._generar_clave_clientes)

        boton_clave_admin = QPushButton("Cambiar contraseña de PC clientes...")
        boton_clave_admin.clicked.connect(self._cambiar_clave_admin_pcs)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Estaciones activas:"))
        layout.addWidget(self.lista)
        layout.addLayout(fila_agregar)
        layout.addLayout(fila_acciones)
        layout.addLayout(fila_ip)
        layout.addWidget(boton_clave_clientes)
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

    def _al_cambiar_seleccion(self):
        """Al cambiar de fila, muestra la IP ya cargada en memoria (la que
        trajo el último `_cargar()`) sin ir a la base -- `_traer_ip` es la
        que relee fresco si hace falta."""
        fila = self.lista.currentRow()
        if fila < 0 or fila >= len(self.estaciones):
            self.campo_ip.clear()
            return
        self.campo_ip.setText(self.estaciones[fila]["ultima_ip"] or "")

    @manejar_errores
    def _traer_ip(self):
        estacion = self._seleccionada()
        if estacion is None:
            return
        fresca = pcs_repo.obtener_estacion(estacion["id"])
        ip = fresca["ultima_ip"] if fresca is not None else None
        if ip:
            self.campo_ip.setText(ip)
        else:
            self.campo_ip.clear()
            mostrar_error(
                self, "Todavía no hay IP",
                f"'{estacion['nombre']}' todavía no registró ninguna conexión con IP.\n\n"
                "Configurá el Cliente PC en esa PC con este mismo nombre de "
                "estación y esperá unos segundos: pregunta solo cada 5s, y "
                "recién ahí queda la IP guardada acá."
            )

    @manejar_errores
    def _generar_clave_clientes(self):
        """
        Genera (o rota) la clave única que exige `servidor_red.py` en el
        header `Authorization` de cada Cliente PC (ver CLIENTE PC,
        `red_kiosko._cabeceras_cliente`). Al rotarla, la clave anterior
        deja de servir para CUALQUIER PC hasta que se la actualice ahí --
        por eso pide confirmación explícita si ya había una generada.
        """
        clave_actual = clientes_repo.obtener_clave_clientes()
        if clave_actual:
            aviso = (
                "Se va a generar una clave nueva para los Clientes PC.\n\n"
                "Esto ROTA la clave de las estaciones que ya están conectadas: "
                "la anterior deja de servir para cualquier PC hasta que se "
                "actualice ahí con la nueva. ¿Continuar?"
            )
        else:
            aviso = "Se va a generar la clave que necesitan los Clientes PC para conectarse a este servidor. ¿Continuar?"
        if not confirmar(self, "Generar/renovar clave de Clientes PC", aviso):
            return
        clave_nueva = clientes_repo.generar_clave_clientes()
        QInputDialog.getText(
            self, "Clave de Clientes PC generada",
            "Copiá esta clave (Ctrl+A, Ctrl+C) y pegala en el config.json\n"
            "o en el asistente de configuración de cada PC cliente:",
            text=clave_nueva,
        )

    @manejar_errores
    def _cambiar_clave_admin_pcs(self):
        """
        Contraseña que destraba el panel admin en la pantalla de bloqueo
        de cada PC cliente (ícono "A", ver cliente_pc.py). A
        diferencia de la clave de Clientes PC, la elige el dueño (tiene que
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
        clientes_repo.establecer_clave_admin_pcs(nueva)
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
