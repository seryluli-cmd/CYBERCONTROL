"""
ui/configuracion_admin_window.py
================================
La ventana "Configuración ADMIN" (botón ⚙️ CONFIG ADMIN de la barra). Estaba en
ui/main_window.py y se mudó acá el 2026-10-26, cuando el dueño eligió su diseño
nuevo (maqueta "A": cabecera oscura y tarjetas en tres grupos, con una línea de para
qué es cada una; las piezas están en ui/piezas_ventana.py). Los botones hacen lo
mismo que antes.
"""

from PySide6.QtWidgets import QDialog, QGridLayout, QHBoxLayout, QVBoxLayout

import dominio
from admin_remoto import modo as modo_remoto
from control_pcs.ui.cuenta_pc_reglas_dialogo import DialogoReglasCuentaPc
from control_pcs.ui.miembros_window import DialogoGestionBonosMiembro, DialogoTramosTarifaMiembro
from control_pcs.ui.pcs_gestion_dialogos import (
    DialogoGestionBonos, DialogoGestionBonosPcstream, DialogoGestionBonosPlaystation, DialogoGestionEstaciones,
)
from ui.accesos_admin_window import AccesosAdminWindow
from ui.admin_remoto_dialogo import DialogoEntrarDesdeOtraPC
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, agregar_pastilla, bloquear_tarjeta, cabecera_oscura, tarjeta_de_menu, tecla,
    titulo_de_seccion,
)
from ui.tramites_window import DialogoGestionTramites
from ui.utils import sin_boton_por_defecto


class ConfiguracionAdminWindow(QDialog):
    """
    Agrupa las pantallas de EDICIÓN de catálogos -- Estaciones, Bonos de
    Tiempo (walk-in), Bonos de PlayStation 5, Bonos de PCSTREAM, Tarifa por Hora
    de Socios, las Reglas de Cuenta de PC (el tope de lo que puede deber una PC,
    2026-10-25), Bonos de Socios y Trámites -- más "Accesos de Admin" (quién entró con una cuenta
    de administrador, ver ui/accesos_admin_window.py) y, en el mostrador, "Entrar desde
    otra PC" (ui/admin_remoto_dialogo.py). La abre
    cualquiera, pero un Operador solo puede usar Gestionar Estaciones (pedido del
    dueño, 2026-10-19); el resto se ve en gris, con candado, y es de ADMIN, sin
    excepción: no hay permiso delegable para esto. Recibe el `usuario` para eso y
    porque el catálogo de la PlayStation 5 vuelve a exigir en el repo que quien lo
    edita sea Admin.

    *Usar* esos catálogos (asignarle un bono ya creado a una PC o a la
    PlayStation 5, cargar saldo con la tarifa ya fijada) sigue abierto a
    cualquier operador desde la grilla de PCs y "Miembros". Separación
    pedida explícitamente por el dueño: editar el
    catálogo es tarea de super admin, usarlo no.
    """

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Configuración ADMIN")
        self.resize(660, 640)
        self._armar_interfaz()

    def _armar_interfaz(self):
        es_admin = dominio.es_admin(self.usuario)
        cabecera = cabecera_oscura(
            "⚙️", "Configuración ADMIN",
            f"{self.usuario['nombre']} · "
            + ("Administrador" if es_admin else "Operador: usa solo Gestionar Estaciones"),
        )
        agregar_pastilla(cabecera, "ADMIN" if es_admin else "OPERADOR", TONO_AZUL if es_admin else TONO_GRIS)

        pcs_del_local = [
            ("🖥️", "Gestionar Estaciones", "Alta, IP, fondo, filtro y Cliente PC", self._abrir_estaciones),
            ("💳", "Reglas de Cuenta de PC", "Cuánto puede deber una PC", self._abrir_reglas_cuenta_pc),
        ]
        # Desde otra PC no se prende ni apaga la entrada desde otra PC: se apagaría
        # a sí misma. Solo en el mostrador.
        if not modo_remoto.es_copia_remota():
            pcs_del_local.append(("🌐", "Entrar desde otra PC", "Manejar el programa desde otra compu del local",
                                  self._abrir_entrar_desde_otra_pc))
        grupos = [
            ("Las PCs del local", pcs_del_local),
            ("Bonos", [
                ("🎟️", "Bonos de las PCs", "Los que se venden en el mostrador", self._abrir_bonos),
                ("🎮", "Bonos de PlayStation 5", "Los de la consola", self._abrir_bonos_playstation),
                ("🎥", f"Bonos de {dominio.NOMBRE_PCSTREAM}", "Los de la PC de streaming",
                 self._abrir_bonos_pcstream),
                ("🎁", "Bonos de Socios", "Exclusivos de los socios", self._abrir_bonos_miembro),
            ]),
            ("Socios, trámites y accesos", [
                ("💲", "Tarifa por hora de Socios", "Lo que se descuenta del saldo", self._configurar_tarifa),
                ("📄", "Trámites", "Los trámites que se cobran", self._abrir_tramites),
                ("🔐", "Accesos de Admin", "Quién entró con una cuenta de administrador", self._abrir_accesos_admin),
            ]),
        ]

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(10)
        layout.addWidget(cabecera)
        for titulo, tarjetas in grupos:
            layout.addSpacing(4)
            layout.addWidget(titulo_de_seccion(titulo))
            grilla = QGridLayout()
            grilla.setSpacing(10)
            for numero, (icono, nombre, detalle, funcion) in enumerate(tarjetas):
                tarjeta = tarjeta_de_menu(icono, nombre, detalle, funcion)
                # Un Operador entra pero solo usa Gestionar Estaciones; lo demás lo ve
                # en gris y con candado (pedido del dueño, 2026-10-19).
                if not es_admin and funcion != self._abrir_estaciones:
                    bloquear_tarjeta(tarjeta)
                # La última de un grupo impar ocupa las dos columnas: sin huecos.
                ancho = 2 if numero == len(tarjetas) - 1 and numero % 2 == 0 else 1
                grilla.addWidget(tarjeta, numero // 2, numero % 2, 1, ancho)
            grilla.setColumnStretch(0, 1)
            grilla.setColumnStretch(1, 1)
            layout.addLayout(grilla)
        layout.addStretch()

        pie = QHBoxLayout()
        pie.addStretch()
        pie.addWidget(tecla("CERRAR", self.close, "teclaRoja"))
        layout.addLayout(pie)
        sin_boton_por_defecto(self)

    def _abrir_estaciones(self):
        DialogoGestionEstaciones(self.usuario, self).exec()

    def _abrir_bonos(self):
        DialogoGestionBonos(self).exec()

    def _abrir_bonos_playstation(self):
        DialogoGestionBonosPlaystation(self.usuario, self).exec()

    def _abrir_bonos_pcstream(self):
        DialogoGestionBonosPcstream(self).exec()

    def _configurar_tarifa(self):
        DialogoTramosTarifaMiembro(self).exec()

    def _abrir_reglas_cuenta_pc(self):
        DialogoReglasCuentaPc(self.usuario, self).exec()

    def _abrir_bonos_miembro(self):
        DialogoGestionBonosMiembro(self).exec()

    def _abrir_tramites(self):
        DialogoGestionTramites(self).exec()

    def _abrir_accesos_admin(self):
        AccesosAdminWindow(self).exec()

    def _abrir_entrar_desde_otra_pc(self):
        DialogoEntrarDesdeOtraPC(self.usuario, self).exec()
