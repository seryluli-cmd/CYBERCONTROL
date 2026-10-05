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
"Configuración ADMIN", ui/main_window.py) — sin estaciones no hay nada
que listar acá.

Este archivo tiene la grilla, su menú contextual (clic derecho), el
refresco automático y el log de actividad. El resto del módulo vive al lado:
- `pcs_detalle.py`: el panel lateral (vender un bono, abrir con Miembro,
  finalizar) y el login de socio.
- `pcs_comandos_dialogos.py`: los diálogos del menú contextual (captura,
  cambiar red, intercambiar de máquina, volumen).
- `pcs_gestion_dialogos.py`: administrar el catálogo de Estaciones y de
  Bonos de Tiempo (solo se abren desde Configuración ADMIN, no desde acá).
"""

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QTableWidget, QTableWidgetItem, QLabel,
    QTextEdit, QHeaderView, QInputDialog, QMenu,
)
from PySide6.QtCore import Qt, QTimer

import dominio
from control_pcs.repositories import comandos_pc_repo, pcs_repo
from control_pcs.ui.pcs_comandos_dialogos import (
    DialogoCambiarRed, DialogoCaptura, DialogoTrasladarSesion, DialogoVolumen,
)
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion
from ui.utils import (
    formato_pesos, formato_tiempo, formato_transcurrido, mostrar_info,
    confirmar, manejar_errores,
)

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

# Alerta especial (pedido explícito del dueño): sesión activa (Bono o
# Miembro) en una estación que dejó de estar "enlazada" -- el Cliente PC de
# esa PC no reportó conexión en el último UMBRAL_ENLACE_SEGUNDOS a pesar de
# tener tiempo pago corriendo. A diferencia del rojo fijo de "Sin conexión"
# (sin sesión, sin apuro: la PC está apagada o libre), acá SÍ hay
# plata/tiempo en juego sin que nadie lo esté viendo -- puede ser que un
# cliente haya encontrado la forma de cerrar el Cliente PC para seguir
# usando la PC sin que se le descuente. Parpadea entre estos dos colores
# para llamar la atención del operador (ver
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
    (`detener_actualizacion`, llamado desde `MainWindow.closeEvent`):
    QWidget no tiene la señal `finished` de QDialog.
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
        """Frena los dos timers (refresco y parpadeo); lo llama MainWindow
        al cerrarse para que no sigan corriendo contra widgets destruidos."""
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
