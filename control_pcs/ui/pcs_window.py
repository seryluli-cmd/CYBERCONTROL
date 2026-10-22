"""
pcs_window.py
==============
Control de PCs: `PanelControlPcs`, un mosaico de monitores (uno por PC, con
la pantalla pintada del color de su estado, ver `pcs_mosaico.py`) con su
panel lateral para operar la estación seleccionada — se embebe como pantalla
principal en
ui/main_window.py, porque asignarle un bono a una PC (o dejar que un
Miembro se loguee solo) es una venta más del día a día, igual que
"Vender" del kiosko: cualquier usuario logueado puede operarla.

Si la lista aparece vacía no es un error: significa que todavía no se
cargó ninguna fila en `estaciones` (ver "Gestionar Estaciones" en
"Configuración ADMIN", ui/main_window.py) — sin estaciones no hay nada
que listar acá.

Primera en el mosaico, antes de las PCs, está la PlayStation 5 (ver
`playstation_repo`): una sola consola con nombre fijo, que se vende por tiempo
con bonos propios. Mientras corre muestra su cuenta regresiva (se redibuja cada
segundo) y al llegar a cero su monitor titila en rojo hasta que el operador avise
a los clientes y la libere -- a diferencia de una PC, no se da de baja sola.
Justo después va PCSTREAM, la PC de streaming (pedido del dueño): una PC más,
con bloqueo, pero con sus propios bonos (ver pcstream_repo). El orden lo decide
pcs_repo._orden_natural, que la pone antes que las demás PCs.

Este archivo decide qué estado, color y dibujito le toca a cada equipo, el
menú contextual (clic derecho) y el refresco automático. El resto del módulo
vive al lado:
- `pcs_mosaico.py`: el dibujo del mosaico de monitores (solo dibuja).
- `pcs_actividad.py`: el log de "Actividad reciente" de la parte de abajo.
- `pcs_aviso_reservas.py`: el aviso de arriba del mosaico con las reservas de
  "Cualquier PC disponible". Las de una PC puntual, PCSTREAM o la consola se ven
  en su monitor: celeste si está libre (ver COLOR_RESERVADA).
- `pcs_detalle.py`: el panel lateral (vender un bono, abrir con Miembro,
  finalizar) y el login de socio.
- `pcs_comandos_dialogos.py`: los diálogos del menú contextual (captura,
  cambiar red, intercambiar de máquina, volumen).
- `pcs_congelado_dialogo.py`: congelar y descongelar PCs con Shadow Defender
  (también del menú contextual, solo para el Admin).
- `pcs_gestion_dialogos.py`: administrar el catálogo de Estaciones y de
  Bonos de Tiempo (solo se abren desde Configuración ADMIN, no desde acá).
"""

from datetime import datetime

from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QWidget, QVBoxLayout, QHBoxLayout, QLabel, QFrame, QInputDialog, QMenu,
)
from PySide6.QtCore import Qt, QTimer

import dominio
from control_pcs.repositories import comandos_pc_repo, pcs_repo, playstation_repo, reservas_horario_repo
from control_pcs.ui.pcs_comandos_dialogos import (
    DialogoCambiarRed, DialogoCaptura, DialogoTrasladarSesion, DialogoVolumen,
)
from control_pcs.ui.pcs_congelado_dialogo import DialogoCongelado
from control_pcs.ui.pcs_actividad import PanelActividad
from control_pcs.ui.pcs_aviso_reservas import AvisoDeReservasSinPcFija
from control_pcs.ui.pcs_cortes import resumen_de_cortes
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion, es_playstation, texto_de_la_reserva
from control_pcs.ui.pcs_mosaico import (
    MosaicoDeEquipos, LeyendaDeColores, Ficha,
    DIBUJO_NINGUNO, DIBUJO_RELOJ, DIBUJO_SOCIO, DIBUJO_ALERTA, DIBUJO_CANDADO_ABIERTO,
)
from ui.utils import (
    formato_tiempo, formato_transcurrido, mostrar_info, confirmar, manejar_errores,
)

# Cada cuántos milisegundos se recalcula el tiempo restante de las
# estaciones activas y se dan de baja solas las sesiones vencidas.
INTERVALO_REFRESCO_MS = 5000

# Por debajo de este tiempo restante, una PC en uso pasa a mostrarse en
# naranja (⚠) en vez de amarillo, como aviso de que hay que renovarla pronto.
UMBRAL_POR_VENCER_SEGUNDOS = 5 * 60

# Color de la pantalla de cada monitor según su estado (mismo criterio en
# toda la pantalla: verde disponible (prendida y enlazada, sin nadie
# usándola), amarillo en uso (con sesión activa, naranja si está por vencer),
# rojo sin conexión (apagada, Cliente PC caído, o sin red hacia el mostrador
# -- ver pcs_repo.registrar_conexion/UMBRAL_ENLACE_SEGUNDOS). Son los mismos
# colores de siempre, más vivos que cuando pintaban filas de una tabla: sobre
# la pantalla de un monitor dibujado, los pastel se veían lavados.
COLOR_DISPONIBLE = QColor("#2FB457")
COLOR_EN_USO = QColor("#E9B820")
COLOR_POR_VENCER = QColor("#F08A24")
COLOR_DESCONECTADA = QColor("#D93A40")
# Sesión ya activada por el operador en una PC que el cliente todavía no
# prendió (ver pcs_repo.estado_estaciones, "esperando_cliente"): azul
# calmo, sin parpadeo -- es una espera normal, no una alerta.
COLOR_ESPERANDO_CLIENTE = QColor("#3B7DF0")
# PC sin Cliente PC porque alguien lo cerró desde su panel admin (ver
# accesos_admin_pc_repo): está usable por cualquiera, sin bloqueo ni cobro,
# hasta que el Cliente PC vuelva a arrancar. Lila a propósito, distinto del
# rojo de "Sin conexión" (apagada) para que se note cuál es cuál.
COLOR_CLIENTE_CERRADO_ADMIN = QColor("#9B6BD6")
# Equipo libre que ya está apartado para una reserva (2 h antes de la hora, ver
# reservas_horario_repo): celeste, la variante A que eligió el dueño. Uno en uso
# conserva su color y avisa "Res. 10:00" debajo del nombre.
COLOR_RESERVADA = QColor("#22C3E6")


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
COLOR_ALERTA_SESION_SIN_CLIENTE = QColor("#FF3B47")
COLOR_ALERTA_SESION_SIN_CLIENTE_APAGADA = QColor("#FFFFFF")

# Qué quiere decir cada color, en la leyenda de arriba del mosaico.
LEYENDA = [
    (COLOR_DISPONIBLE, "Disponible"),
    (COLOR_EN_USO, "En uso"),
    (COLOR_POR_VENCER, "Por vencer"),
    (COLOR_ESPERANDO_CLIENTE, "Esperando al cliente"),
    (COLOR_RESERVADA, "Reservada"),
    (COLOR_DESCONECTADA, "Sin conexión"),
    (COLOR_CLIENTE_CERRADO_ADMIN, "Sin bloqueo"),
    (COLOR_ALERTA_SESION_SIN_CLIENTE, "Alerta (titila)"),
]

# Cada cuánto alterna el parpadeo de un equipo en alerta -- rápido a
# propósito, tiene que notarse a simple vista sin mirar fijo la pantalla.
INTERVALO_PARPADEO_MS = 500

# Cada cuánto se redibuja la cuenta regresiva de la PlayStation 5.
INTERVALO_CUENTA_REGRESIVA_MS = 1000

# Cómo se identifica un equipo del mosaico: ("PC", id de la estación) o
# ("PLAYSTATION", None) -- la consola es una sola, no tiene id. Es lo que
# permite volver a seleccionar la misma fila cuando la grilla se reconstruye.
_CLAVE_PLAYSTATION = (dominio.DISPOSITIVO_PLAYSTATION, None)


def _clave_de_item(item):
    """La identidad de un equipo del mosaico (ver _CLAVE_PLAYSTATION)."""
    if es_playstation(item):
        return _CLAVE_PLAYSTATION
    return (dominio.DISPOSITIVO_PC, item["estacion"]["id"])


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
        self._estados = []              # solo las PCs (pcs_repo.estado_estaciones)
        self._item_playstation = None   # la consola (playstation_repo.estado)
        self._items_en_grilla = []      # lo que hay en cada fila: la consola y después las PCs
        self._seleccion = None          # clave de la fila elegida (ver _clave_de_item)
        self._filas_en_alerta = []
        self._filas_calientes = []      # las PCs con el procesador caliente: "CALIENTE" titila
        self._parpadeo_encendido = True
        self._armar_interfaz()
        self._refrescar()

        self._timer = QTimer(self)
        self._timer.setInterval(INTERVALO_REFRESCO_MS)
        self._timer.timeout.connect(self._refrescar)
        self._timer.start()

        # Timer aparte, mucho más rápido, solo para el parpadeo de
        # "sesión activa sin Cliente PC" (ver COLOR_ALERTA_SESION_SIN_CLIENTE) --
        # no puede compartir el timer de arriba, que rearma el mosaico
        # entero cada 5s (el parpadeo se vería a los tumbos en vez de parejo).
        self._timer_parpadeo = QTimer(self)
        self._timer_parpadeo.setInterval(INTERVALO_PARPADEO_MS)
        self._timer_parpadeo.timeout.connect(self._alternar_parpadeo)
        self._timer_parpadeo.start()

        # Otro más, de un segundo, para la cuenta regresiva de la PlayStation 5
        # (ver _actualizar_cuenta_regresiva): por la misma razón que el de
        # arriba, no puede colgarse del refresco de 5s.
        self._timer_cuenta_regresiva = QTimer(self)
        self._timer_cuenta_regresiva.setInterval(INTERVALO_CUENTA_REGRESIVA_MS)
        self._timer_cuenta_regresiva.timeout.connect(self._actualizar_cuenta_regresiva)
        self._timer_cuenta_regresiva.start()

    def detener_actualizacion(self):
        """Frena los timers (refresco, parpadeo y cuenta regresiva); lo llama
        MainWindow al cerrarse para que no sigan corriendo contra widgets
        destruidos."""
        self._timer.stop()
        self._timer_parpadeo.stop()
        self._timer_cuenta_regresiva.stop()

    def _armar_interfaz(self):
        self.mosaico = MosaicoDeEquipos()
        self.mosaico.itemSelectionChanged.connect(self._al_cambiar_seleccion)
        self.mosaico.setContextMenuPolicy(Qt.CustomContextMenu)
        self.mosaico.customContextMenuRequested.connect(self._mostrar_menu_contextual)

        # El mosaico va sobre un fondo oscuro (estilo "#marcoMosaico" en la hoja
        # de estilos de main.py): los colores de las pantallas resaltan mucho más
        # que sobre el gris claro del resto del programa.
        marco = QFrame()
        marco.setObjectName("marcoMosaico")
        layout_marco = QVBoxLayout()
        layout_marco.setContentsMargins(12, 12, 12, 8)
        layout_marco.setSpacing(8)
        layout_marco.addWidget(LeyendaDeColores(LEYENDA))
        # Las reservas de "Cualquier PC disponible": no apartan ninguna PC, así que
        # se avisan acá arriba (decisión del dueño). Escondido si no hay ninguna.
        self.aviso_reservas = AvisoDeReservasSinPcFija()
        layout_marco.addWidget(self.aviso_reservas)
        layout_marco.addWidget(self.mosaico, 1)
        marco.setLayout(layout_marco)

        self.panel_detalle = PanelDetalleEstacion(self.usuario, self._refrescar, self)

        fila_principal = QHBoxLayout()
        fila_principal.addWidget(marco, 1)
        fila_principal.addWidget(self.panel_detalle)

        self.panel_actividad = PanelActividad()

        layout = QVBoxLayout()
        layout.addLayout(fila_principal, 1)
        titulo_actividad = QLabel("Actividad reciente")
        titulo_actividad.setObjectName("tituloSeccion")
        layout.addWidget(titulo_actividad)
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
        # La PlayStation 5 NO entra en el "job de vencimiento" de arriba: al
        # llegar a cero no se libera sola, queda avisando en rojo hasta que el
        # operador la libera (ver playstation_repo).
        self._item_playstation = playstation_repo.estado()
        self.aviso_reservas.actualizar(reservas_horario_repo.reservas_para_la_grilla(), estados)
        self._redibujar_mosaico()
        self.panel_actividad.actualizar()

    @staticmethod
    def _ficha_de_pc(item):
        """Cómo se dibuja una PC en el mosaico (estado, tiempo, quién, color,
        dibujito y si titila), a partir de un elemento de
        pcs_repo.estado_estaciones()."""
        estacion = item["estacion"]
        sesion = item["sesion"]
        segundos = item["segundos_restantes"]
        en_alerta = False
        aviso = ""

        if sesion is not None:
            quien_texto = sesion["miembro_nombre"] or "Bono"
            restante_texto = formato_tiempo(segundos)
            # El socio se ve con su dibujito; un bono, con el reloj y las monedas.
            dibujo = DIBUJO_SOCIO if sesion["miembro_nombre"] else DIBUJO_RELOJ
        else:
            quien_texto, restante_texto, dibujo = "—", "—", DIBUJO_NINGUNO

        if sesion is not None and not item["enlazada"] and item["esperando_cliente"]:
            # El operador habilitó la PC antes de que el cliente la
            # prendiera -- el tiempo ya corre, pero no es una alerta.
            icono, texto_estado, color = "⏳", "Esperando al cliente", COLOR_ESPERANDO_CLIENTE
            aviso = "Esperando"  # corto: el casillero es angosto (el texto completo va en el cartelito)
        elif sesion is not None and not item["enlazada"]:
            # Hay tiempo pago corriendo pero el Cliente PC de esa PC dejó
            # de responder -- ver COLOR_ALERTA_SESION_SIN_CLIENTE. Esto
            # va ANTES que "por vencer"/"en uso": importa más avisar
            # que nadie está viendo esa PC que cuánto tiempo le queda.
            texto_alerta = "SIN CLIENTE (revisar)"
            if item["cliente_cerrado_admin_desde"] is not None:
                texto_alerta = f"SIN CLIENTE (cerrado por admin hace {formato_transcurrido(item['cliente_cerrado_admin_desde'])})"
            elif item["ultima_conexion"] is not None:
                # Por qué, recién se sabe cuando vuelve (ver cortes_pc_repo).
                texto_alerta = f"SIN CLIENTE hace {formato_transcurrido(item['ultima_conexion'])} (revisar)"
            icono, texto_estado, color = "🚨", texto_alerta, COLOR_ALERTA_SESION_SIN_CLIENTE
            en_alerta, dibujo, aviso = True, DIBUJO_ALERTA, "SIN CLIENTE"
        elif sesion is not None:
            if segundos <= UMBRAL_POR_VENCER_SEGUNDOS:
                icono, texto_estado, color = "⚠", "Por vencer", COLOR_POR_VENCER
                aviso = "Por vencer"
            else:
                icono, texto_estado, color = "▶", "En uso", COLOR_EN_USO
        elif item.get("fin_sin_aviso") is not None:
            # Se terminó su sesión y la PC no se enteró: su Cliente PC no responde y
            # pueden seguir usándola sin tiempo (ver avisos_fin_pc_repo). Titila como la
            # PlayStation 5 con el tiempo agotado, hasta que vuelva o alguien la revise.
            fin = item["fin_sin_aviso"]
            que_paso = "Se terminó el tiempo" if fin["por_tiempo"] else "Se cerró la sesión"
            icono, color, quien_texto = "⏰", COLOR_ALERTA_SESION_SIN_CLIENTE, fin["quien"]
            texto_estado = (f"{que_paso} a las {fin['fin']:%H:%M} y la PC no se enteró "
                            "(su Cliente PC no responde): revisar la PC")
            en_alerta, dibujo = True, DIBUJO_ALERTA
            aviso = "TIEMPO AGOTADO" if fin["por_tiempo"] else "NO SE BLOQUEÓ"
        elif item["enlazada"]:
            icono, texto_estado, color = "✓", "Disponible", COLOR_DISPONIBLE
        elif item["cliente_cerrado_admin_desde"] is not None:
            icono, color = "🔓", COLOR_CLIENTE_CERRADO_ADMIN
            texto_estado = f"Sin bloqueo (cerrado por admin hace {formato_transcurrido(item['cliente_cerrado_admin_desde'])})"
            dibujo, aviso = DIBUJO_CANDADO_ABIERTO, "Sin bloqueo"
        else:
            icono, texto_estado, color = "🔌", "Sin conexión", COLOR_DESCONECTADA

        reserva = item.get("reserva")
        if reserva is not None and reserva["marcada"]:
            hora = f"{reserva['inicio']:%H:%M}"
            if sesion is None and item["cliente_cerrado_admin_desde"] is None and not en_alerta:
                # Libre y apartada: celeste, para que nadie se la dé a otro cliente.
                # Apagada también: lo que importa es que está reservada.
                icono, color = "📅", COLOR_RESERVADA
                texto_estado = f"Reservada para {reserva['cliente']}"
                if not item["enlazada"]:
                    texto_estado += " (la PC está apagada o sin conexión)"
                aviso = f"{reserva['cliente']} {hora}"
            elif not aviso:
                aviso = f"Res. {hora}"  # en uso: más urgente que el nombre del socio

        if not aviso and dibujo == DIBUJO_SOCIO:
            aviso = quien_texto  # el nombre del socio, si no hay nada más urgente que avisar

        estado = f"{icono} {texto_estado}"
        temperatura = item.get("temperatura") or {"cpu": None, "gpu": None}
        nivel_temperatura = dominio.nivel_de_temperatura(temperatura["cpu"])
        if temperatura["cpu"] is not None or temperatura["gpu"] is not None:
            partes = [f"Procesador {temperatura['cpu']}°" if temperatura["cpu"] is not None else None,
                      f"Placa de video {temperatura['gpu']}°" if temperatura["gpu"] is not None else None]
            estado += "\n🌡 " + " · ".join(parte for parte in partes if parte)
            if nivel_temperatura == dominio.TEMPERATURA_CALIENTE_NIVEL:
                estado += "\n🔥 CALIENTE: revisar ventiladores y polvo"
        if texto_de_la_reserva(item):
            estado += f"\n{texto_de_la_reserva(item)}"
        if item["cortes"]:
            # Solo en el cartelito: el monitor dibujado no cambia (el detalle, en el panel).
            estado += f"\n⚠ {resumen_de_cortes(item['cortes'])}"

        return Ficha(
            clave=_clave_de_item(item),
            nombre=estacion["nombre"],
            estado=estado,
            restante=restante_texto,
            quien=quien_texto,
            color=color,
            en_alerta=en_alerta,
            dibujo=dibujo,
            con_bono=sesion is not None and not sesion["miembro_nombre"],
            aviso=aviso,
            con_termometro=True,
            temperatura=temperatura["cpu"],
            nivel_temperatura=nivel_temperatura,
        )

    @staticmethod
    def _ficha_de_playstation(item):
        """Lo mismo que _ficha_de_pc, para la PlayStation 5 (un elemento de
        playstation_repo.estado()). No hay Cliente PC que reporte conexión: la
        consola está libre, en uso, por vencer, o con el tiempo agotado -- y ESE
        caso es una alerta: titila en rojo hasta que el operador avise a los
        clientes y la libere (o venda otro bono)."""
        comun = {"clave": _CLAVE_PLAYSTATION, "nombre": item["nombre"], "es_consola": True}
        reserva = item.get("reserva") if item.get("reserva") is not None and item["reserva"]["marcada"] else None
        if item["sesion"] is None:
            if reserva is not None:
                return Ficha(
                    estado=f"📅 Reservada para {reserva['cliente']}\n{texto_de_la_reserva(item)}",
                    restante="—", quien="—", color=COLOR_RESERVADA,
                    aviso=f"{reserva['cliente']} {reserva['inicio']:%H:%M}", **comun,
                )
            return Ficha(estado="✓ Disponible", restante="—", quien="—", color=COLOR_DISPONIBLE, **comun)
        restante_texto = formato_tiempo(item["segundos_restantes"], con_segundos=True)
        en_sesion = {"restante": restante_texto, "quien": "Bono", "con_bono": True, **comun}
        if reserva is not None and not item["tiempo_agotado"] \
                and item["segundos_restantes"] > UMBRAL_POR_VENCER_SEGUNDOS:
            return Ficha(
                estado=f"▶ En uso\n{texto_de_la_reserva(item)}", color=COLOR_EN_USO, dibujo=DIBUJO_RELOJ,
                aviso=f"Res. {reserva['inicio']:%H:%M}", **en_sesion,
            )
        if item["tiempo_agotado"]:
            return Ficha(
                estado="⏰ TIEMPO AGOTADO — avisar", color=COLOR_ALERTA_SESION_SIN_CLIENTE,
                en_alerta=True, dibujo=DIBUJO_ALERTA, aviso="TIEMPO AGOTADO", **en_sesion,
            )
        if item["segundos_restantes"] <= UMBRAL_POR_VENCER_SEGUNDOS:
            return Ficha(
                estado="⚠ Por vencer", color=COLOR_POR_VENCER, dibujo=DIBUJO_RELOJ,
                aviso="Por vencer", **en_sesion,
            )
        return Ficha(estado="▶ En uso", color=COLOR_EN_USO, dibujo=DIBUJO_RELOJ, **en_sesion)

    def _redibujar_mosaico(self):
        # La PlayStation 5 va primero, antes de las PCs.
        self._items_en_grilla = (
            [self._item_playstation] if self._item_playstation is not None else []
        ) + list(self._estados)
        fichas = [
            self._ficha_de_playstation(item) if es_playstation(item) else self._ficha_de_pc(item)
            for item in self._items_en_grilla
        ]
        self._filas_en_alerta = [fila for fila, ficha in enumerate(fichas) if ficha.en_alerta]
        self._filas_calientes = [fila for fila, ficha in enumerate(fichas) if ficha.caliente]
        self._parpadeo_encendido = True

        claves = [ficha.clave for ficha in fichas]
        fila_a_seleccionar = claves.index(self._seleccion) if self._seleccion in claves else -1

        # blockSignals: actualizar los casilleros no tiene que disparar
        # itemSelectionChanged a cada rato; el panel lateral se actualiza una
        # sola vez abajo, con los datos frescos del equipo elegido.
        self.mosaico.blockSignals(True)
        self.mosaico.mostrar(fichas)
        self.mosaico.elegir(fila_a_seleccionar)
        self.mosaico.blockSignals(False)

        if fila_a_seleccionar >= 0:
            self.panel_detalle.mostrar(self._items_en_grilla[fila_a_seleccionar])
        else:
            self._seleccion = None
            self.panel_detalle.mostrar(None)

    def _actualizar_cuenta_regresiva(self):
        """
        Redibuja, cada segundo, el tiempo restante de la PlayStation 5 (el
        mosaico entero se refresca solo cada 5s, y una cuenta regresiva que
        salta de a 5 no se ve como tal). Solo cambia el tiempo de su casillero
        -- nunca rearma el mosaico --, y calcula contra el reloj de AHORA con
        el vencimiento guardado, así que no deriva ni depende de cuántas veces
        corrió. Cuando llega a cero pide un refresco completo: ahí pasa a
        "TIEMPO AGOTADO" y arranca a titilar en rojo (ver _ficha_de_playstation).
        """
        item = self._item_playstation
        if item is None or item["sesion"] is None or item["tiempo_agotado"]:
            return
        fin_previsto = datetime.fromisoformat(item["sesion"]["fecha_fin_prevista"])
        segundos = dominio.segundos_restantes(fin_previsto, datetime.now())
        if segundos == 0:
            self._refrescar()
            return
        # La consola es siempre el primer casillero (ver _redibujar_mosaico).
        if self.mosaico.count() > 0:
            self.mosaico.cambiar_restante(0, formato_tiempo(segundos, con_segundos=True))
        if self._seleccion == _CLAVE_PLAYSTATION:
            self.panel_detalle.mostrar_estado_playstation({**item, "segundos_restantes": segundos})

    def _alternar_parpadeo(self):
        """
        Alterna la pantalla de los equipos en `self._filas_en_alerta` entre
        rojo fuerte y blanco cada INTERVALO_PARPADEO_MS -- ver
        COLOR_ALERTA_SESION_SIN_CLIENTE --, y prende y apaga el "CALIENTE" de
        los de `self._filas_calientes`. Corre en un timer aparte del
        refresco de 5s (`_redibujar_mosaico` ya deja los índices
        actualizados cada vez que corre); si no hay ningún equipo en
        alerta ni caliente no hace nada, así que dejarlo corriendo siempre
        no cuesta nada.
        """
        if not self._filas_en_alerta and not self._filas_calientes:
            return
        self._parpadeo_encendido = not self._parpadeo_encendido
        color = (
            COLOR_ALERTA_SESION_SIN_CLIENTE
            if self._parpadeo_encendido
            else COLOR_ALERTA_SESION_SIN_CLIENTE_APAGADA
        )
        for fila in self._filas_en_alerta:
            if fila < self.mosaico.count():
                self.mosaico.pintar(fila, color)
        for fila in self._filas_calientes:
            if fila < self.mosaico.count():
                self.mosaico.titilar_calor(fila, self._parpadeo_encendido)

    @manejar_errores
    def _al_cambiar_seleccion(self):
        fila = self.mosaico.fila_elegida()
        if 0 <= fila < len(self._items_en_grilla):
            item = self._items_en_grilla[fila]
            self._seleccion = _clave_de_item(item)
            self.panel_detalle.mostrar(item)
        else:
            self._seleccion = None
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
        fila = self.mosaico.fila_en(posicion)
        if fila < 0 or fila >= len(self._items_en_grilla):
            return
        self.mosaico.elegir(fila)
        item = self._items_en_grilla[fila]
        if es_playstation(item):
            # La consola no se controla a distancia: no tiene Cliente PC, así
            # que nada de este menú (cerrar y reiniciar, apagar, mensaje,
            # captura, red, volumen) tiene sentido. Se opera desde el panel.
            return
        estacion = item["estacion"]
        sesion = item["sesion"]
        segundos_restantes = item["segundos_restantes"]

        menu = QMenu(self)
        accion_cerrar_sesion = menu.addAction("🔒 Cerrar sesión y reiniciar")
        accion_cerrar_sesion.setEnabled(sesion is not None)
        accion_trasladar = menu.addAction("🔀 Intercambiar de máquina...")
        # PCSTREAM tiene sus propios precios: no entra en un traslado (ver
        # pcs_repo.trasladar_sesion, que también lo rechaza).
        accion_trasladar.setEnabled(sesion is not None and not item["es_pcstream"])
        menu.addSeparator()
        accion_reiniciar = menu.addAction("🔄 Reiniciar PC")
        accion_apagar = menu.addAction("⏻ Apagar PC")
        menu.addSeparator()
        accion_mensaje = menu.addAction("💬 Enviar mensaje...")
        accion_captura = menu.addAction("📷 Sacar captura de pantalla")
        menu.addSeparator()
        accion_cambiar_red = menu.addAction("🌐 Cambiar red...")
        accion_volumen = menu.addAction("🔊 Ajustar volumen...")
        # Shadow Defender: solo el Admin lo ve. Igual pide su clave, que las
        # empleadas no tienen; así no les aparece algo que no pueden usar.
        accion_congelar = None
        if dominio.es_admin(self.usuario):
            menu.addSeparator()
            accion_congelar = menu.addAction("🧊 Congelar / descongelar...")

        # menu.exec() abre un bucle de eventos anidado: mientras el menú
        # sigue abierto, el timer de refresco (cada 5s) puede disparar
        # igual y rearmar todo el mosaico de estaciones por debajo. Si
        # el mostrador tarda un poco en elegir una opción, eso llegó a
        # borrar el propio menú a mitad de camino y explotaba con
        # "libshiboken: Internal C++ object (QMenu) already deleted" justo
        # al leer qué se eligió. Se pausa el refresco mientras el menú
        # está abierto y se reanuda apenas se cierra (elija algo o no).
        self._timer.stop()
        self._timer_cuenta_regresiva.stop()
        try:
            elegida = menu.exec(self.mosaico.viewport().mapToGlobal(posicion))
        finally:
            self._timer.start()
            self._timer_cuenta_regresiva.start()

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
        elif accion_congelar is not None and elegida == accion_congelar:
            DialogoCongelado(estacion, self._estados, self).exec()

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
                "formas?"
            )
        else:
            aviso = f"¿Cerrar la sesión de '{estacion['nombre']}' y reiniciar la PC?"
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
            f"Se le va a avisar a '{estacion['nombre']}' en los próximos segundos.\n\n"
            f"Si no lo recibe en {comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO} minutos (apagada o sin "
            "conexión), se descarta: así no le llega más tarde a otro cliente.",
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
