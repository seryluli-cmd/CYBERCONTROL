"""
main_window.py
================
Ventana principal: aparece después del login y muestra de entrada la
grilla de "Control de PCs" (`control_pcs/ui/pcs_window.py:PanelControlPcs`) — es lo
que se usa todo el día en el mostrador, así que es la pantalla misma, no
una opción más de un menú. Desde la barra de arriba se llega a Vender
(kiosko), a "Trámites" (servicios con monto libre, ej. sacar una boleta de
luz), a "Miembros" (alta/carga de saldo de socios) y, para
"encargados", a "Administrar Kiosko" (el resto de las pantallas de
gestión) y, solo para Admin, a "Configuración ADMIN". Qué se ve depende
del rol y los permisos:

- Cualquiera logueado: operar la grilla de PCs (asignar un bono ya
  creado, abrir con Miembro, finalizar sesión — es una venta más, como
  Vender), Vender, cobrar un Trámite, Caja, Cierre de Turno, y Cambiar mi
  Clave. La PlayStation 5, que está en esa misma grilla, la ve cualquiera pero
  solo la opera (vender sus bonos, liberarla) quien tenga `permiso_control_pcs`
  (o sea Admin).
- Con `permiso_control_pcs` (o Admin): además ve "Miembros" (alta,
  modificar datos, cargar saldo, desactivar — usa la tarifa y los bonos
  ya definidos, no los edita).
- "Encargado" (ADMIN, o EMPLEADA con al menos uno de los permisos de
  usuarios_repo.PERMISOS_EMPLEADA): además ve "Administrar Kiosko", que
  agrupa Artículos/Compras/Consulta de Ventas/Reportes/Control de
  Cierres, y Usuarios si es Admin (eso no se puede delegar con permisos).
- Solo ADMIN, sin excepción: "Configuración ADMIN" — Gestionar
  Estaciones (agregar/quitar/renombrar PC), Gestionar Bonos (catálogo de
  walk-ins), Gestionar Bonos de PlayStation 5, Gestionar Bonos de PCSTREAM (la
  PC de streaming), Tarifa por Hora de Socios,
  Gestionar Bonos de Socios, Gestionar Trámites, Accesos de Admin (registro
  de logins de administradores) y Limpiar base de datos (borra la plata y el
  historial de ventas para volver a probar; ver limpieza_repo).
  Pedido explícito del dueño: editar estos catálogos es tarea de super
  admin; usarlos (asignar un bono, cobrar con la tarifa ya fijada) sigue
  delegable con `permiso_control_pcs`.

Cada módulo se abre como un diálogo modal (QDialog.exec) encima de esta
ventana.

La caja (pedido del dueño, 2026-10-18; reglas en repositories/relevo_repo.py):
al lado del nombre se ve la caja abierta. Desde 5 minutos antes del fin del
turno el botón Cierre de Turno titila en rojo, y a los 15 minutos del fin el
programa cierra la caja solo (cierre forzoso, ver _revisar_la_caja).

Desde otra PC del local (la copia para administrar, ver admin_remoto/): solo
Administrar Kiosko, Configuración ADMIN, Caja (para mirar) y Clave. Vender,
cobrar, cerrar el turno y la grilla de PCs siguen en el mostrador, y el cierre
forzoso de la caja también lo hace el mostrador (si lo hicieran las dos, la
misma caja se intentaría cerrar dos veces).
"""

from PySide6.QtWidgets import (
    QApplication, QMainWindow, QDialog, QWidget, QVBoxLayout, QHBoxLayout, QPushButton, QLabel, QFrame,
)
from PySide6.QtCore import Qt, QTimer

import dominio
from admin_remoto import modo as modo_remoto
from errores import registrar_error
from repositories import relevo_repo, usuarios_repo
from ui.accesos_admin_window import AccesosAdminWindow
from ui.admin_remoto_dialogo import DialogoEntrarDesdeOtraPC
from ui.articulos_window import ArticulosWindow
from ui.compras_window import ComprasWindow
from ui.ventas_window import VentasWindow
from ui.consulta_ventas_window import ConsultaVentasWindow
from ui.limpieza_dialogo import DialogoLimpiarBase
from ui.caja_window import CajaWindow, CierreTurnoWindow, ControlCierresWindow
from ui.reportes_window import ReportesWindow
from ui.tramites_window import DialogoTramites, DialogoGestionTramites
from ui.usuarios_window import UsuariosWindow, DialogoCambiarClave
from control_pcs.ui.pcs_window import PanelControlPcs
from control_pcs.ui.pcs_gestion_dialogos import (
    DialogoGestionEstaciones, DialogoGestionBonos, DialogoGestionBonosPlaystation,
    DialogoGestionBonosPcstream,
)
from control_pcs.ui.miembros_window import MiembrosWindow, DialogoTramosTarifaMiembro, DialogoGestionBonosMiembro
from ui.ingreso_caja import mensaje_del_sobre
from ui.utils import aplicar_clase, mostrar_info, sin_boton_por_defecto

# Cada cuánto se mira cómo está la caja (si tiene que titilar el botón, o si ya
# toca el cierre forzoso). Es una consulta chica, con su índice.
INTERVALO_REVISION_CAJA_MS = 10_000
# Cada cuánto cambia de color el botón Cierre de Turno mientras titila.
INTERVALO_PARPADEO_MS = 600


class MainWindow(QMainWindow):
    """Barra de botones (según rol y permisos) y, debajo, la grilla de PCs."""

    def __init__(self, usuario, al_cerrar_sesion):
        """
        `usuario` es la fila del usuario logueado (con su rol).
        `al_cerrar_sesion` es una función que se llama al elegir
        "Cerrar sesión", para volver a la pantalla de login.
        """
        super().__init__()
        self.usuario = usuario
        self.es_admin = dominio.es_admin(usuario)
        # "Encargado" no es un rol propio en la base — es un Admin, o una
        # Empleada con al menos uno de los permisos de administración de
        # usuarios_repo.PERMISOS_EMPLEADA. Decide si se ve el botón
        # "Administrar Kiosko".
        self._es_encargado = self.es_admin or any(
            usuarios_repo.tiene_permiso(usuario, clave_permiso)
            for clave_permiso, _ in usuarios_repo.PERMISOS_EMPLEADA
        )
        self._al_cerrar_sesion = al_cerrar_sesion
        self._remota = modo_remoto.es_copia_remota()
        self._titilar = False
        self._encendido = False
        self._armar_interfaz()
        if self._remota:
            self._mostrar_la_caja_del_mostrador()
        else:
            self._actualizar_estado_de_la_caja()

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

        # Tarjeta blanca "#encabezadoInicio" (estilo en la hoja de estilos
        # global de main.py), armada como barra horizontal.
        barra = QFrame()
        barra.setObjectName("encabezadoInicio")
        layout_barra = QHBoxLayout()
        layout_barra.setContentsMargins(20, 12, 20, 12)
        layout_barra.setSpacing(10)

        # Pedido del dueño (2026-10-16): el nombre de quien está en el mostrador
        # como "Operador: TOBY", sin saludo y sin la palabra "EMPLEADA" (el rol
        # por dentro sigue siendo EMPLEADA). El Admin se sigue distinguiendo.
        cargo = "Administrador" if self.es_admin else "Operador"
        titulo = QLabel(f"{cargo}: {self.usuario['nombre']}")
        titulo.setStyleSheet("font-size: 15px; font-weight: 700; color: #1B2233;")
        layout_barra.addWidget(titulo)
        # La caja abierta: "Caja Nº 12 · Mañana" (ver _actualizar_estado_de_la_caja).
        self.etiqueta_caja = QLabel()
        self.etiqueta_caja.setStyleSheet("font-size: 13px; color: #4A5568;")
        layout_barra.addWidget(self.etiqueta_caja)
        layout_barra.addStretch()

        if not self._remota:
            self._agregar_boton_barra(layout_barra, "🛒  Vender", self._abrir_ventas, clase="primario")
            self._agregar_boton_barra(layout_barra, "📄  Trámites", self._abrir_tramites)
            if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, "permiso_control_pcs"):
                self._agregar_boton_barra(layout_barra, "🧑‍🤝‍🧑  Miembros", self._abrir_miembros)
        if self._es_encargado:
            self._agregar_boton_barra(layout_barra, "🛠️  Administrar Kiosko", self._abrir_administrar_kiosko)
        if self.es_admin:
            self._agregar_boton_barra(layout_barra, "⚙️  Configuración ADMIN", self._abrir_configuracion_admin)
        self._agregar_boton_barra(layout_barra, "💵  Caja", self._abrir_caja)
        self.boton_cierre_turno = None
        if not self._remota:
            self.boton_cierre_turno = self._agregar_boton_barra(
                layout_barra, "🧾  Cierre de Turno", self._abrir_cierre_turno
            )
        self._agregar_boton_barra(layout_barra, "🔑  Clave", self._abrir_cambiar_clave)
        self._agregar_boton_barra(layout_barra, "Cerrar sesión", self._cerrar_sesion, clase="peligro")
        barra.setLayout(layout_barra)

        # Desde otra PC no va la grilla de PCs (eso se atiende en el mostrador):
        # un cartel que dice dónde se está trabajando.
        self.panel_pcs = None if self._remota else PanelControlPcs(self.usuario, self)

        contenedor = QWidget()
        layout = QVBoxLayout()
        layout.setContentsMargins(12, 12, 12, 12)
        layout.setSpacing(12)
        layout.addWidget(barra)
        layout.addWidget(self.panel_pcs if self.panel_pcs is not None else _cartel_de_otra_pc(), 1)
        contenedor.setLayout(layout)
        self.setCentralWidget(contenedor)

    def _agregar_boton_barra(self, layout, texto, funcion, clase=None):
        """Botón de la barra superior: alto fijo, ancho según el texto
        (van en fila, así que no hace falta que midan todos igual)."""
        boton = QPushButton(texto)
        boton.setFixedHeight(38)
        # Los que no son ni "primario" ni "peligro" van sin borde (clase "barra",
        # ver la hoja de estilos de main.py).
        aplicar_clase(boton, clase or "barra")
        boton.clicked.connect(funcion)
        layout.addWidget(boton)
        return boton

    def closeEvent(self, evento):
        # QMainWindow no tiene la señal `finished` de los QDialog, así que
        # el refresco automático de la grilla de PCs se frena acá, al cerrar.
        if self.panel_pcs is not None:
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
            self.etiqueta_caja.setText("·  Sin caja abierta" if self.es_admin else "")
        elif self.es_admin or estado["responsable_id"] != self.usuario["id"]:
            self.etiqueta_caja.setText(
                f"·  Caja Nº {estado['caja_numero']} de {estado['responsable']} · {estado['turno_label']}"
            )
        else:
            self.etiqueta_caja.setText(f"·  Caja Nº {estado['caja_numero']} · {estado['turno_label']}")
        self._titilar = bool(estado and estado["titilar"])
        return estado

    def _mostrar_la_caja_del_mostrador(self):
        """Desde otra PC: el número de caja que ve el mostrador, o que no hay
        conexión (sin carteles: se vuelve a probar en la próxima revisión)."""
        try:
            self._actualizar_estado_de_la_caja()
        except (ValueError, PermissionError):  # sin red, o se cerró la sesión en el mostrador
            self.etiqueta_caja.setText("·  Sin conexión con el mostrador")

    def _parpadear(self):
        """Titila en rojo (alterna con su color de siempre) mientras toca
        cerrar; si no, se queda con su color de siempre. El rojo es la clase
        "alerta" de la hoja de estilos (main.py)."""
        if self.boton_cierre_turno is None:  # desde otra PC no hay Cierre de Turno
            return
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
        titileo, y si pasaron los 15 minutos de gracia hace el cierre forzoso
        (pedido del dueño: "el programa aprieta solo Cierre de Turno"). Después,
        quien atiende vuelve a la pantalla de ingreso como con un cierre normal;
        el Admin se queda donde estaba (no estaba atendiendo esa caja).

        Desde otra PC solo se actualiza el número de caja: el cierre forzoso lo
        hace el mostrador.
        """
        if self._remota:
            self._mostrar_la_caja_del_mostrador()
            return
        try:
            estado = self._actualizar_estado_de_la_caja()
            if estado is None or not estado["vencida"] or self._hay_un_cobro_a_medias():
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
                f"({resultado['turno_label']}) se cerró sola: pasaron 15 minutos del fin del turno.\n\n"
                f"{resultado['responsable']} tiene que armar el sobre. {mensaje_del_sobre(resultado)}",
            )
            return
        mostrar_info(
            self, "Cierre forzoso",
            f"Tu caja Nº {resultado['caja_numero']} ({resultado['turno_label']}) se cerró sola: pasaron "
            "15 minutos del fin del turno.\n\n"
            f"{mensaje_del_sobre(resultado)}\n\n"
            "Ahora volvés a la pantalla de ingreso. Si tu reemplazo no llegó, volvé a entrar con tu "
            "usuario y seguí vendiendo: no hace falta contar el Cambio Fijo.",
        )
        self._cerrar_sesion()

    # -----------------------------------------------------------------
    # Abrir cada módulo (diálogos modales)
    # -----------------------------------------------------------------

    def _abrir_ventas(self):
        VentasWindow(self.usuario, self).exec()

    def _abrir_tramites(self):
        DialogoTramites(self.usuario, self).exec()

    def _abrir_caja(self):
        CajaWindow(self).exec()

    def _abrir_cierre_turno(self):
        dialogo = CierreTurnoWindow(self.usuario, self)
        dialogo.exec()
        # Cerrar un turno implica que ya llegó el relevo -- en vez de
        # dejar la sesión de quien cerró abierta, se vuelve sola al Login
        # (mismo camino que el botón "Cerrar sesión") para que la próxima
        # persona entre con su propio usuario. Si se canceló el diálogo
        # sin confirmar el cierre (turno_cerrado sigue en False), no pasa
        # nada -- sigue todo como estaba.
        if dialogo.turno_cerrado:
            self._cerrar_sesion()

    def _abrir_cambiar_clave(self):
        DialogoCambiarClave(self.usuario, self).exec()

    def _abrir_administrar_kiosko(self):
        AdministrarKioskoWindow(self.usuario, self.es_admin, self).exec()

    def _abrir_miembros(self):
        MiembrosWindow(self.usuario, self).exec()

    def _abrir_configuracion_admin(self):
        ConfiguracionAdminWindow(self.usuario, self).exec()

    def _cerrar_sesion(self):
        self.close()
        self._al_cerrar_sesion()


def _cartel_de_otra_pc() -> QLabel:
    """Lo que se ve en lugar de la grilla de PCs en la copia para administrar
    desde otra PC."""
    cartel = QLabel(
        f"Estás administrando desde otra PC, con los datos del mostrador ({modo_remoto.mostrador_en_uso()}).\n\n"
        "Lo que guardes acá queda guardado en el mostrador al instante. Vender, cobrar, cerrar el turno "
        "y atender las PCs se hace en el mostrador: la operadora sigue trabajando normal."
    )
    cartel.setAlignment(Qt.AlignCenter)
    cartel.setWordWrap(True)
    cartel.setStyleSheet("font-size: 15px; color: #4A5568; padding: 40px;")
    return cartel


class _VentanaDeBotones(QDialog):
    """
    Diálogo angosto con un título y una columna de botones grandes, todos
    del mismo tamaño para que la pantalla quede prolija, y un "Cerrar" al
    final. Es la base de "Administrar Kiosko" y de "Configuración ADMIN":
    cada una dice qué botones tiene (`_armar_botones`) y qué hace cada uno.
    """

    ANCHO_BOTON = 320
    ALTO_BOTON = 48

    def __init__(self, titulo: str, alto: int, parent=None):
        super().__init__(parent)
        self._titulo = titulo
        self.setWindowTitle(titulo)
        self.resize(360, alto)

    def _armar_botones(self, botones: list):
        """`botones`: lista de (texto, función) o (texto, función, clase), en el
        orden en que se ven. La clase ("peligro", "primario") le da el color."""
        layout = QVBoxLayout()
        layout.setContentsMargins(24, 24, 24, 24)

        titulo = QLabel(self._titulo)
        titulo.setAlignment(Qt.AlignCenter)
        titulo.setStyleSheet("font-size: 17px; font-weight: 700; color: #1B2233;")
        layout.addWidget(titulo)
        layout.addSpacing(16)

        for texto, funcion, *clase in botones:
            self._agregar_boton(layout, texto, funcion, *clase)

        layout.addStretch()
        self._agregar_boton(layout, "Cerrar", self.close, clase="peligro")
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_boton(self, layout, texto, funcion, clase=None):
        boton = QPushButton(texto.upper())
        boton.setFixedSize(self.ANCHO_BOTON, self.ALTO_BOTON)
        if clase:
            aplicar_clase(boton, clase)
        boton.clicked.connect(funcion)
        layout.addWidget(boton, alignment=Qt.AlignHCenter)
        return boton


class AdministrarKioskoWindow(_VentanaDeBotones):
    """
    Agrupa las pantallas de gestión del kiosko detrás de un único acceso
    ("Administrar Kiosko"), visible solo para encargados (ver
    MainWindow._es_encargado). Un Admin las ve todas; una Empleada solo las
    que tenga habilitadas en usuarios_repo.PERMISOS_EMPLEADA.
    """

    def __init__(self, usuario, es_admin, parent=None):
        super().__init__("Administrar Kiosko", 540, parent)
        self.usuario = usuario
        self.es_admin = es_admin
        self._armar_interfaz()

    def _armar_interfaz(self):
        # (permiso que la habilita, texto, qué abre). "Usuarios" no está
        # acá: es solo del Admin, no se delega con ningún permiso.
        pantallas = [
            ("permiso_articulos", "📦  Artículos", self._abrir_articulos),
            ("permiso_compras", "🚚  Compras", self._abrir_compras),
            ("permiso_consulta_ventas",
             "🔍  Consulta de Ventas / Anular" if self.es_admin else "🔍  Consulta de Ventas",
             self._abrir_consulta_ventas),
            ("permiso_reportes", "📊  Reportes", self._abrir_reportes),
            ("permiso_control_cierres", "🗂️  Control de Cierres de Turno", self._abrir_control_cierres),
        ]
        botones = [
            (texto, funcion) for permiso, texto, funcion in pantallas
            if self.es_admin or usuarios_repo.tiene_permiso(self.usuario, permiso)
        ]
        if self.es_admin:
            botones.append(("👤  Usuarios", self._abrir_usuarios))
        self._armar_botones(botones)

    def _abrir_articulos(self):
        ArticulosWindow(self).exec()

    def _abrir_compras(self):
        ComprasWindow(self.usuario, self).exec()

    def _abrir_consulta_ventas(self):
        ConsultaVentasWindow(self.usuario, self).exec()

    def _abrir_reportes(self):
        ReportesWindow(self).exec()

    def _abrir_control_cierres(self):
        ControlCierresWindow(self.usuario, self).exec()

    def _abrir_usuarios(self):
        UsuariosWindow(self.usuario, self).exec()


class ConfiguracionAdminWindow(_VentanaDeBotones):
    """
    Agrupa las pantallas de EDICIÓN de catálogos -- Estaciones, Bonos de
    Tiempo (walk-in), Bonos de PlayStation 5, Bonos de PCSTREAM, Tarifa por Hora
    de Socios, Bonos de Socios y Trámites -- más "Accesos de Admin" (quién entró con una cuenta
    de administrador, ver ui/accesos_admin_window.py) y, en el mostrador, "Entrar desde
    otra PC" (ui/admin_remoto_dialogo.py) y "Limpiar base de datos". Exclusiva de ADMIN, sin
    excepción: no hay permiso delegable para esto (ver
    MainWindow._armar_interfaz). Recibe el `usuario` porque el catálogo de la
    PlayStation 5 vuelve a exigir en el repo que quien lo edita sea Admin.

    *Usar* esos catálogos (asignarle un bono ya creado a una PC o a la
    PlayStation 5, cargar saldo con la tarifa ya fijada) sigue abierto a
    cualquier operador con permiso_control_pcs desde la grilla de PCs y
    "Miembros". Separación pedida explícitamente por el dueño: editar el
    catálogo es tarea de super admin, usarlo no.
    """

    def __init__(self, usuario, parent=None):
        super().__init__("Configuración ADMIN", 740, parent)
        self.usuario = usuario
        botones = [
            ("🖥️  Gestionar Estaciones", self._abrir_estaciones),
            ("🎟️  Gestionar Bonos", self._abrir_bonos),
            ("🎮  Gestionar Bonos de PlayStation 5", self._abrir_bonos_playstation),
            (f"🎥  Gestionar Bonos de {dominio.NOMBRE_PCSTREAM}", self._abrir_bonos_pcstream),
            ("💲  Tarifa por Hora de Socios", self._configurar_tarifa),
            ("🎁  Gestionar Bonos de Socios", self._abrir_bonos_miembro),
            ("📄  Gestionar Trámites", self._abrir_tramites),
            ("🔐  Accesos de Admin", self._abrir_accesos_admin),
        ]
        # Desde otra PC no se prende ni apaga la entrada desde otra PC (se apagaría
        # a sí misma) ni se limpia la base: las dos cosas, solo en el mostrador.
        if not modo_remoto.es_copia_remota():
            botones += [
                ("🌐  Entrar desde otra PC", self._abrir_entrar_desde_otra_pc),
                # Para la etapa de pruebas (pedido del dueño, 2026-10-17): borra la
                # plata y el historial de ventas, deja los catálogos. Ver limpieza_repo.
                ("🧹  Limpiar base de datos", self._limpiar_base, "peligro"),
            ]
        self._armar_botones(botones)

    def _abrir_estaciones(self):
        DialogoGestionEstaciones(self).exec()

    def _abrir_bonos(self):
        DialogoGestionBonos(self).exec()

    def _abrir_bonos_playstation(self):
        DialogoGestionBonosPlaystation(self.usuario, self).exec()

    def _abrir_bonos_pcstream(self):
        DialogoGestionBonosPcstream(self).exec()

    def _configurar_tarifa(self):
        DialogoTramosTarifaMiembro(self).exec()

    def _abrir_bonos_miembro(self):
        DialogoGestionBonosMiembro(self).exec()

    def _abrir_tramites(self):
        DialogoGestionTramites(self).exec()

    def _abrir_accesos_admin(self):
        AccesosAdminWindow(self).exec()

    def _abrir_entrar_desde_otra_pc(self):
        DialogoEntrarDesdeOtraPC(self.usuario, self).exec()

    def _limpiar_base(self):
        DialogoLimpiarBase(self.usuario, self).exec()
