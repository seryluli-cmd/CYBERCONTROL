"""
main_window.py
================
Ventana principal: aparece después del login y muestra de entrada la
grilla de "Control de PCs" (`control_pcs/ui/pcs_window.py:PanelControlPcs`) — es lo
que se usa todo el día en el mostrador, así que es la pantalla misma, no
una opción más de un menú. Desde la barra de arriba se llega a Vender
(kiosko), a "Impresiones" (cobro rápido del artículo de impresiones, sin
entrar a Vender), a "Trámites" (servicios con monto libre, ej. sacar una boleta de
luz), a "Miembros" (alta/carga de saldo de socios) y, para
"encargados", a "Administrar Kiosko" (el resto de las pantallas de
gestión) y a "Configuración ADMIN". Todos ven todos los
botones (pedido del dueño, 2026-10-19); qué abre cada uno depende del rol y
los permisos (los que no le tocan a alguien no hacen nada al apretarlos):

- Cualquiera logueado: operar la grilla de PCs (asignar un bono ya
  creado, abrir con Miembro, finalizar sesión — es una venta más, como
  Vender), Vender, cobrar Impresiones o un Trámite, "Miembros" (alta,
  modificar datos, cargar saldo, desactivar — usa la tarifa y los bonos ya
  definidos, no los edita; pedido del dueño, 2026-10-19: antes pedía
  `permiso_control_pcs`, cualquier operador tiene que poder cargarle saldo a
  un socio), "Reservas" (tomar una reserva cobrando la seña, habilitarla,
  reprogramarla; devolver la plata es solo del Admin, ver
  control_pcs/repositories/reservas_repo.py), Caja, Cierre de Turno, y Cambiar
  mi Clave. La PlayStation 5, que
  está en esa misma grilla, también la opera cualquiera (vender sus bonos,
  liberarla; pedido del dueño, 2026-10-19). La casilla de ese permiso
  ("Operar PCs y Miembros") se sacó de Usuarios el 2026-10-22: ya no daba
  nada (ver usuarios_repo.PERMISOS_EMPLEADA).
- "Encargado" (ADMIN, o EMPLEADA con al menos uno de los permisos de
  usuarios_repo.PERMISOS_EMPLEADA): además abre "Administrar Kiosko", que
  agrupa Artículos/Compras/Consulta de Ventas/Reportes/Control de
  Cierres, y Usuarios si es Admin (eso no se puede delegar con permisos);
  lo que no le toca lo ve en gris, con candado (ui/administrar_kiosko_window.py).
- "Configuración ADMIN": la abre cualquiera, pero un Operador solo usa
  Gestionar Estaciones (agregar/quitar/renombrar PC; pedido del dueño,
  2026-10-19) y ve el resto en gris. Lo demás es solo de ADMIN, sin
  excepción: Gestionar Bonos (catálogo de
  walk-ins), Gestionar Bonos de PlayStation 5, Gestionar Bonos de PCSTREAM (la
  PC de streaming), Tarifa por Hora de Socios,
  Gestionar Bonos de Socios, Gestionar Trámites, Accesos de Admin (registro
  de logins de administradores).
  Pedido explícito del dueño: editar estos catálogos es tarea de super
  admin; usarlos (asignar un bono, cobrar con la tarifa ya fijada) lo puede
  hacer cualquier operador.

Cada módulo se abre como un diálogo modal (QDialog.exec) encima de esta
ventana.

La caja (pedido del dueño, 2026-10-18; reglas en repositories/relevo_repo.py):
al lado del nombre se ve la caja abierta. Desde 5 minutos antes del fin del
turno el botón Cierre de Turno titila en rojo, y a los 30 minutos del fin
(turnos.MINUTOS_PARA_CIERRE_FORZOSO) el programa cierra la caja solo (cierre
forzoso, ver _revisar_la_caja).

Desde otra PC del local (la copia para administrar, ver admin_remoto/) se ve
igual que en el mostrador, con la grilla de PCs en vivo (pedido del dueño,
2026-10-24: "quiero que se vea tal cual"). Se usan Administrar Kiosko,
Configuración ADMIN, Caja (para mirar) y Clave; Vender, cobrar, cerrar el turno
y atender las PCs están, pero al apretarlos avisan que se hace en el mostrador
(`ui.utils.solo_en_el_mostrador`). El cierre forzoso de la caja lo hace solo el
mostrador (si lo hicieran las dos, la misma caja se intentaría cerrar dos veces).
"""

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
)
from PySide6.QtCore import QTimer

import time

import dominio
from admin_remoto import modo as modo_remoto
from errores import registrar_error
from repositories import impresiones_repo, relevo_repo, usuarios_repo
from turnos import MINUTOS_PARA_CIERRE_FORZOSO
from ui.administrar_kiosko_window import AdministrarKioskoWindow
from ui.configuracion_admin_window import ConfiguracionAdminWindow
from ui.impresiones_window import DialogoImpresiones
from ui.ventas_window import VentasWindow
from ui.caja_window import CajaWindow, CierreTurnoWindow
from ui.tramites_window import DialogoTramites
from ui.usuarios_window import DialogoCambiarClave
from control_pcs.ui.pcs_window import PanelControlPcs
from control_pcs.ui.cuenta_pc_dialogos import DialogoCobrarAntesDelCierre
from control_pcs.repositories import cuentas_pc_repo
from control_pcs.ui.miembros_window import MiembrosWindow
from control_pcs.ui.reservas_window import ReservasWindow
from control_pcs.repositories import reservas_repo
from ui.ingreso_caja import mensaje_del_sobre
from ui.utils import (
    aplicar_clase, icono_de_emoji, mostrar_error, mostrar_info, solo_en_el_mostrador,
)

# Cada cuánto se mira cómo está la caja (si tiene que titilar el botón, o si ya
# toca el cierre forzoso). Es una consulta chica, con su índice.
INTERVALO_REVISION_CAJA_MS = 10_000
# Cada cuánto cambia de color el botón Cierre de Turno mientras titila.
INTERVALO_PARPADEO_MS = 600
# El dibujito del botón Operador (lo eligió el dueño entre cinco, 2026-10-24) y cuánto más grande
# va que los de los otros botones de la barra.
DIBUJITO_OPERADOR = "🔄"
AGRANDAR_DIBUJITO_OPERADOR = 1.25


class MainWindow(QMainWindow):
    """Barra de botones (los mismos para todos; qué abren, según rol y
    permisos) y, debajo, la grilla de PCs."""

    def __init__(self, usuario, al_cerrar_sesion):
        """
        `usuario` es la fila del usuario logueado (con su rol).
        `al_cerrar_sesion` es una función que se llama al elegir
        "🔄 Operador", para volver a la pantalla de login.
        """
        super().__init__()
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        # "Encargado" no es un rol propio en la base — es un Admin, o una
        # Empleada con al menos uno de los permisos de administración de
        # usuarios_repo.PERMISOS_EMPLEADA. Decide si el botón "Administrar
        # Kiosko" abre algo (se ve siempre).
        self._es_encargado = self.es_admin or any(
            usuarios_repo.tiene_permiso(usuario, clave_permiso)
            for clave_permiso, _ in usuarios_repo.PERMISOS_EMPLEADA
        )
        self._al_cerrar_sesion = al_cerrar_sesion
        self._remota = modo_remoto.es_copia_remota()
        self._titilar = False
        self._encendido = False
        # Hasta cuándo no vuelve a salir el cartel de lo fiado en el turno (Posponer 5 min).
        self._cuentas_pospuestas_hasta = 0.0
        self._armar_interfaz()
        if self._remota:
            self._mostrar_la_caja_del_mostrador()
        else:
            self._actualizar_estado_de_la_caja()
        self._actualizar_boton_reservas()

        self._timer_caja = QTimer(self)
        self._timer_caja.setInterval(INTERVALO_REVISION_CAJA_MS)
        self._timer_caja.timeout.connect(self._revisar_la_caja)
        self._timer_caja.start()
        self._timer_parpadeo = QTimer(self)
        self._timer_parpadeo.setInterval(INTERVALO_PARPADEO_MS)
        self._timer_parpadeo.timeout.connect(self._parpadear)
        self._timer_parpadeo.start()

    def _armar_interfaz(self):
        if self._remota:
            self.setWindowTitle(
                f"CyberBIOS - {self.usuario['nombre']} - desde otra PC (mostrador: {modo_remoto.mostrador_en_uso()})"
            )
        else:
            self.setWindowTitle(f"CyberBIOS - {self.usuario['nombre']} ({self.usuario['rol']})")
        self.resize(980, 680)

        # Barra oscura "#encabezadoInicio" (estilo en la hoja de estilos
        # global de main.py), en dos renglones (pedido del dueño, 2026-10-18: en
        # la pantalla del mostrador, de 1366 de ancho, todo en una sola fila no
        # entraba y se cortaban los textos): arriba quién está y la caja, abajo
        # los botones, empezando por Vender desde la izquierda.
        barra = QFrame()
        barra.setObjectName("encabezadoInicio")
        layout_barra = QVBoxLayout()
        layout_barra.setContentsMargins(16, 10, 16, 10)
        layout_barra.setSpacing(8)

        # Pedido del dueño (2026-10-16): el nombre de quien está en el mostrador
        # como "Operador: TOBY", sin saludo y sin la palabra "EMPLEADA" (el rol
        # por dentro sigue siendo EMPLEADA). El Admin se sigue distinguiendo.
        cargo = "Administrador" if self.es_admin else "Operador"
        # Letra clara sobre la barra oscura: "#nombreEncabezado" y "#cajaEncabezado"
        # en ui/hoja_de_estilos.py.
        titulo = QLabel(f"{cargo}: {self.usuario['nombre']}")
        titulo.setObjectName("nombreEncabezado")
        # La caja abierta, al lado del nombre: "Caja Nº 12 · Mañana" (ver
        # _actualizar_estado_de_la_caja).
        self.etiqueta_caja = QLabel()
        self.etiqueta_caja.setObjectName("cajaEncabezado")
        self.etiqueta_caja.hide()
        renglon_nombre = QHBoxLayout()
        renglon_nombre.setSpacing(10)
        renglon_nombre.addWidget(titulo)
        renglon_nombre.addWidget(self.etiqueta_caja)
        renglon_nombre.addStretch()
        layout_barra.addLayout(renglon_nombre)

        botones = QHBoxLayout()
        botones.setSpacing(6)
        layout_barra.addLayout(botones)
        self._armar_botones_de_la_barra(botones)
        barra.setLayout(layout_barra)

        # Desde otra PC también: la misma grilla, en vivo, con los datos del
        # mostrador (pedido del dueño, 2026-10-24; hasta ese día iba un cartel).
        self.panel_pcs = PanelControlPcs(self.usuario, self)

        contenedor = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(barra)
        layout.addWidget(self.panel_pcs, 1)
        contenedor.setLayout(layout)
        self.setCentralWidget(contenedor)

    def _armar_botones_de_la_barra(self, layout_barra):
        """El renglón de botones, de izquierda a derecha empezando por Vender y
        terminando en "🔄 Operador", pegado a la derecha de Clave (pedido del
        dueño, 2026-10-23; hasta ese día iba solo en la punta derecha y, con la
        pantalla de 1920 del mostrador, quedaba lejos de todo). Se llamaba
        "Cerrar sesión": el dueño pidió que diga lo que hace de verdad, volver
        al ingreso para que entre otro operador. Primero fue "Camb Operador"; el
        2026-10-24 pasó a las flechas en círculo + "Operador" (el dueño eligió
        🔄 entre cinco dibujitos).

        Desde otra PC van los mismos botones (pedido del dueño, 2026-10-24): los
        que venden, cobran o cierran el turno avisan que eso se hace en el
        mostrador (ver los `_abrir_...` con `solo_en_el_mostrador`)."""
        self._agregar_boton_barra(layout_barra, "🛒  Vender", self._abrir_ventas, clase="primario")
        # Cobro rápido de impresiones, sin entrar a Vender (pedido del dueño, 2026-10-19).
        self._agregar_boton_barra(layout_barra, "🖨️  Impresiones", self._abrir_impresiones)
        self._agregar_boton_barra(layout_barra, "📄  Trámites", self._abrir_tramites)
        # Una sola carita (2026-10-18): el emoji de "dos personas" de antes,
        # en el Windows del mostrador, se veía como tres caras sueltas.
        # Abre para cualquier operador logueado (pedido del dueño, 2026-10-19):
        # antes pedía permiso_control_pcs o Admin, pero cargarle saldo a un socio
        # es una venta más y cualquiera tiene que poder hacerlo.
        self._agregar_boton_barra(layout_barra, "🧑  Miembros", self._abrir_miembros)
        # Reservas de PCs, PCSTREAM y PlayStation 5 (pedido del dueño, 2026-10-20): cobra,
        # así que se abre solo en el mostrador. Dice cuántas esperan hoy (ver _actualizar_boton_reservas).
        self.boton_reservas = self._agregar_boton_barra(layout_barra, "", self._abrir_reservas)
        # Nombres cortos en la barra (pedido del dueño, 2026-10-18); las ventanas
        # que abren siguen con su nombre entero.
        self._agregar_boton_barra(
            layout_barra, "🛠️  Admin Kiosko", self._abrir_administrar_kiosko, habilitado=self._es_encargado
        )
        # Abre para todos: un Operador solo usa Gestionar Estaciones (ver ConfiguracionAdminWindow).
        self._agregar_boton_barra(layout_barra, "⚙️  Config ADMIN", self._abrir_configuracion_admin)
        self._agregar_boton_barra(layout_barra, "💵  Caja", self._abrir_caja)
        self.boton_cierre_turno = self._agregar_boton_barra(layout_barra, "🧾  Cierre de Turno", self._abrir_cierre_turno)
        self._agregar_boton_barra(layout_barra, "🔑  Clave", self._abrir_cambiar_clave)
        # Tres espacios entre el dibujito y el texto: uno más que en los otros botones (pedido del dueño).
        boton_operador = self._agregar_boton_barra(layout_barra, "   Operador", self._cerrar_sesion, clase="peligro")
        # Su dibujito va un 25% más grande que los de los otros botones (pedido del dueño,
        # 2026-10-24): uno dentro del texto mide lo que la letra, así que este va como ícono.
        boton_operador.ensurePolished()
        icono, tamano = icono_de_emoji(DIBUJITO_OPERADOR, boton_operador.fontInfo().pixelSize() * AGRANDAR_DIBUJITO_OPERADOR)
        boton_operador.setIcon(icono)
        boton_operador.setIconSize(tamano)
        layout_barra.addStretch()

    def _agregar_boton_barra(self, layout, texto, funcion, clase=None, habilitado=True):
        """Botón de la barra superior: alto fijo, ancho según el texto
        (van en fila, así que no hace falta que midan todos igual).

        Todos ven todos los botones (pedido del dueño, 2026-10-19: con solo los
        suyos la barra de una empleada quedaba muy vacía). Uno sin `habilitado`
        se ve igual que los demás pero no hace nada al apretarlo: no se lo
        apaga con setEnabled(False) porque se vería gris, distinto del resto.

        El texto va en mayúscula (y en negrita, por ui/hoja_de_estilos.py),
        pedido del dueño 2026-10-22; acá y no en la hoja porque Qt no tiene
        text-transform."""
        boton = QPushButton(texto.upper())
        boton.setFixedHeight(38)
        # Los que no son ni "primario" ni "peligro" son teclas oscuras con relieve
        # (clase "barra", ver ui/hoja_de_estilos.py).
        aplicar_clase(boton, clase or "barra")
        if habilitado:
            boton.clicked.connect(funcion)
        layout.addWidget(boton)
        return boton

    def closeEvent(self, evento):
        # QMainWindow no tiene la señal `finished` de los QDialog, así que
        # el refresco automático de la grilla de PCs se frena acá, al cerrar.
        self.panel_pcs.detener_actualizacion()
        self._timer_caja.stop()
        self._timer_parpadeo.stop()
        super().closeEvent(evento)

    # -----------------------------------------------------------------
    # La caja: número arriba, botón que titila y cierre forzoso
    # -----------------------------------------------------------------

    def _actualizar_estado_de_la_caja(self):
        """Lee cómo está la caja, la muestra al lado del nombre y decide si el
        botón Cierre de Turno titila. Devuelve el estado (ver
        relevo_repo.estado_de_la_caja) o None si no hay caja abierta."""
        estado = relevo_repo.estado_de_la_caja()
        if estado is None:
            self._mostrar_texto_de_la_caja("·  Sin caja abierta" if self.es_admin else "")
        elif self.es_admin or estado["responsable_id"] != self.usuario["id"]:
            self._mostrar_texto_de_la_caja(
                f"·  Caja Nº {estado['caja_numero']} de {estado['responsable']} · {estado['turno_label']}"
            )
        else:
            self._mostrar_texto_de_la_caja(f"·  Caja Nº {estado['caja_numero']} · {estado['turno_label']}")
        self._titilar = bool(estado and estado["titilar"])
        return estado

    def _mostrar_texto_de_la_caja(self, texto: str):
        """La caja, al lado del nombre (escondida si no hay nada que decir)."""
        self.etiqueta_caja.setText(texto)
        self.etiqueta_caja.setVisible(bool(texto))

    def _mostrar_la_caja_del_mostrador(self):
        """Desde otra PC: el número de caja que ve el mostrador, o que no hay
        conexión (sin carteles: se vuelve a probar en la próxima revisión)."""
        try:
            self._actualizar_estado_de_la_caja()
        except (ValueError, PermissionError):  # sin red, o se cerró la sesión en el mostrador
            self._mostrar_texto_de_la_caja("·  Sin conexión con el mostrador")

    def _parpadear(self):
        """Titila en rojo (alterna con su color de siempre) mientras toca
        cerrar; si no, se queda con su color de siempre. El rojo es la clase
        "alerta" de la hoja de estilos (ui/hoja_de_estilos.py). Desde otra PC
        titila igual, con la caja del mostrador."""
        self._encendido = self._titilar and not self._encendido
        clase = "alerta" if self._encendido else "barra"
        if self.boton_cierre_turno.property("clase") != clase:
            aplicar_clase(self.boton_cierre_turno, clase)

    def _hay_un_cobro_a_medias(self) -> bool:
        """
        Si hay una pantalla abierta encima que no se puede cerrar sin perder
        algo (un carrito con artículos, el cobro, un formulario): el cierre
        forzoso espera a que termine, como esperaría una persona para apretar
        el botón. Una pantalla que avisa que se puede cerrar sola (Ventas con el
        carrito vacío, Caja) se cierra y se sigue en la próxima revisión.
        """
        encima = QApplication.activeModalWidget()
        if encima is None:
            return False
        se_puede_cerrar_sola = getattr(encima, "se_puede_cerrar_sola", None)
        if se_puede_cerrar_sola is not None and se_puede_cerrar_sola():
            encima.reject()
        return True

    def _revisar_la_caja(self):
        """
        Cada INTERVALO_REVISION_CAJA_MS: actualiza el número de caja y el
        titileo, y si pasaron los minutos de gracia hace el cierre forzoso
        (pedido del dueño: "el programa aprieta solo Cierre de Turno"). Después,
        quien atiende vuelve a la pantalla de ingreso como con un cierre normal;
        el Admin se queda donde estaba (no estaba atendiendo esa caja).

        Desde otra PC solo se actualizan el número de caja (y el titileo) y las
        reservas de hoy: el cierre forzoso lo hace el mostrador.
        """
        self._actualizar_boton_reservas()
        if self._remota:
            self._mostrar_la_caja_del_mostrador()
            return
        try:
            estado = self._actualizar_estado_de_la_caja()
            if estado is None or not estado["vencida"]:
                self._revisar_cuentas_antes_del_cierre()
                return
            if self._hay_un_cobro_a_medias():
                return
            resultado = relevo_repo.cierre_forzoso_si_corresponde()
        except Exception as error:  # un fallo de la base no puede tirar abajo el mostrador
            registrar_error(error, "Revisar la caja (cierre forzoso)")
            return
        if resultado is None:
            return
        self._actualizar_estado_de_la_caja()
        if self.es_admin:
            mostrar_info(
                self, "Cierre forzoso",
                f"La caja Nº {resultado['caja_numero']} de {resultado['responsable']} "
                f"({resultado['turno_label']}) se cerró sola: pasaron {MINUTOS_PARA_CIERRE_FORZOSO} minutos del fin del turno.\n\n"
                f"{resultado['responsable']} tiene que armar el sobre. {mensaje_del_sobre(resultado)}",
            )
            return
        mostrar_info(
            self, "Cierre forzoso",
            f"Tu caja Nº {resultado['caja_numero']} ({resultado['turno_label']}) se cerró sola: pasaron "
            f"{MINUTOS_PARA_CIERRE_FORZOSO} minutos del fin del turno.\n\n"
            f"{mensaje_del_sobre(resultado)}\n\n"
            "Ahora volvés a la pantalla de ingreso. Si tu reemplazo no llegó, volvé a entrar con tu "
            "usuario y seguí vendiendo: no hace falta contar el Cambio Fijo.",
        )
        self._cerrar_sesion()

    def _revisar_cuentas_antes_del_cierre(self):
        """
        Lo fiado en el turno se cobra en el turno (pedido del dueño, 2026-10-25):
        desde 15 minutos antes del fin, las PCs que lo deben titilan más rápido y
        sale el cartel con un "Cobrar" por PC. "Posponer" lo deja 5 minutos sin
        salir. No sale encima de otra ventana (un cobro a medias): espera a la
        próxima revisión. Solo en el mostrador (lo llama _revisar_la_caja).
        """
        aviso = cuentas_pc_repo.aviso_antes_del_cierre()
        self.panel_pcs.marcar_cuentas_urgentes(
            {cuenta["estacion_id"] for cuenta in aviso["cuentas"]} if aviso else set()
        )
        if aviso is None or time.monotonic() < self._cuentas_pospuestas_hasta \
                or QApplication.activeModalWidget() is not None:
            return
        cartel = DialogoCobrarAntesDelCierre(self.usuario, DialogoCobrarAntesDelCierre.AVISO, self)
        if not cartel.exec():  # Posponer (o cerró la ventana)
            self._cuentas_pospuestas_hasta = time.monotonic() + dominio.MINUTOS_POSPONER_AVISO_CUENTAS * 60
        self.panel_pcs._refrescar()

    # -----------------------------------------------------------------
    # Abrir cada módulo (diálogos modales)
    # -----------------------------------------------------------------

    @solo_en_el_mostrador
    def _abrir_ventas(self):
        VentasWindow(self.usuario, self).exec()

    @solo_en_el_mostrador
    def _abrir_impresiones(self):
        articulo = impresiones_repo.articulo_impresiones()
        if articulo is None:
            mostrar_error(self, "Falta el artículo", impresiones_repo.mensaje_sin_articulo())
            return
        DialogoImpresiones(self.usuario, articulo, self).exec()

    @solo_en_el_mostrador
    def _abrir_tramites(self):
        DialogoTramites(self.usuario, self).exec()

    def _abrir_caja(self):
        CajaWindow(self).exec()

    @solo_en_el_mostrador
    def _abrir_cierre_turno(self):
        dialogo = CierreTurnoWindow(self.usuario, self)
        dialogo.exec()
        # Cerrar un turno implica que ya llegó el relevo -- en vez de
        # dejar la sesión de quien cerró abierta, se vuelve sola al Login
        # (mismo camino que el botón "🔄 Operador") para que la próxima
        # persona entre con su propio usuario. Si se canceló el diálogo
        # sin confirmar el cierre (turno_cerrado sigue en False), no pasa
        # nada -- sigue todo como estaba.
        if dialogo.turno_cerrado:
            self._cerrar_sesion()

    def _abrir_cambiar_clave(self):
        DialogoCambiarClave(self.usuario, self).exec()

    def _abrir_administrar_kiosko(self):
        AdministrarKioskoWindow(self.usuario, self.es_admin, self).exec()

    @solo_en_el_mostrador
    def _abrir_miembros(self):
        MiembrosWindow(self.usuario, self).exec()

    @solo_en_el_mostrador
    def _abrir_reservas(self):
        ReservasWindow(self.usuario, self).exec()
        self._actualizar_boton_reservas()

    def _actualizar_boton_reservas(self):
        """"Reservas · 3 hoy" con las que esperan hoy (reservas_repo.reservas_de_hoy),
        o solo "Reservas" si no hay. Se mira al abrir, en cada revisión de la caja y al
        cerrar la ventana de Reservas. Un fallo de la base no puede tirar el mostrador."""
        try:
            hoy = reservas_repo.reservas_de_hoy()
        except Exception as error:
            if self._remota and isinstance(error, (ValueError, PermissionError)):
                return  # sin red con el mostrador: queda lo último (la barra ya dice "Sin conexión")
            registrar_error(error, "Contar las reservas de hoy")
            hoy = 0
        self.boton_reservas.setText((f"📅  Reservas · {hoy} hoy" if hoy else "📅  Reservas").upper())

    def _abrir_configuracion_admin(self):
        ConfiguracionAdminWindow(self.usuario, self).exec()

    def _cerrar_sesion(self):
        self.close()
        self._al_cerrar_sesion()

