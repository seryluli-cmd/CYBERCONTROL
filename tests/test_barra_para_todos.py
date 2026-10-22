"""
tests/test_barra_para_todos.py
================================
La barra de arriba de la ventana principal muestra los mismos botones a todos
(pedido del dueño, 2026-10-19: con solo los suyos, la barra de una empleada quedaba
muy vacía). Los que no le tocan a alguien se ven igual que los demás pero no abren
nada al apretarlos. Configuración ADMIN la abre cualquiera, pero un Operador solo
puede usar Gestionar Estaciones: el resto se ve en gris (mismo día). Adentro, todo
menos la contraseña de las PCs clientes y Actualizar el Cliente PC. Miembros abre
para cualquier operador logueado (pedido del dueño, 2026-10-19: antes pedía
permiso_control_pcs o Admin). Se prueba sin abrir ninguna ventana (plataforma
"offscreen").

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QFrame, QPushButton  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from ui.main_window import ConfiguracionAdminWindow, MainWindow  # noqa: E402
from control_pcs.ui.pcs_gestion_dialogos import DialogoGestionEstaciones  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Botón de la barra -> la ventana que abre (el nombre en ui.main_window).
# Miembros no está acá: abre para cualquiera, como Vender (ver
# test_miembros_abre_para_cualquier_empleada).
_CON_PERMISO = {
    "🛠️  ADMIN KIOSKO": "AdministrarKioskoWindow",
}


class _ConUsuarios(BaseConBaseTemporal):
    def _usuario(self, nombre, rol, permisos=None):
        return usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario(nombre, "1234", rol, permisos))


class TestBarraParaTodos(_ConUsuarios):
    def _ventana(self, nombre, rol, permisos=None):
        ventana = MainWindow(self._usuario(nombre, rol, permisos), lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)
        return ventana

    def _botones(self, ventana):
        barra = ventana.findChild(QFrame, "encabezadoInicio")
        return {boton.text(): boton for boton in barra.findChildren(QPushButton)}

    def _que_abre(self, ventana):
        """Aprieta cada botón con permiso y devuelve cuáles abrieron su ventana."""
        botones = self._botones(ventana)
        abiertos = set()
        for texto, ventana_que_abre in _CON_PERMISO.items():
            with mock.patch(f"ui.main_window.{ventana_que_abre}") as clase:
                botones[texto].click()
            if clase.called:
                abiertos.add(texto)
        return abiertos

    def test_una_empleada_ve_los_mismos_botones_que_el_admin(self):
        admin = self._ventana("Admin", dominio.ROL_ADMIN)
        empleada = self._ventana("TOBY", dominio.ROL_EMPLEADA)

        self.assertEqual(list(self._botones(empleada)), list(self._botones(admin)))

    def test_los_que_no_le_tocan_se_ven_igual_pero_no_abren_nada(self):
        empleada = self._ventana("TOBY", dominio.ROL_EMPLEADA)
        botones = self._botones(empleada)

        for texto in _CON_PERMISO:
            # Ni gris ni de otro color: la misma tecla que el resto de la barra.
            self.assertTrue(botones[texto].isEnabled(), texto)
            self.assertEqual(botones[texto].property("clase"), "barra", texto)
        self.assertEqual(self._que_abre(empleada), set())

    def test_el_admin_abre_todo(self):
        admin = self._ventana("Admin", dominio.ROL_ADMIN)

        self.assertEqual(self._que_abre(admin), set(_CON_PERMISO))

    def test_cada_empleada_abre_solo_lo_que_tiene_habilitado(self):
        encargada = self._ventana("Encargada", dominio.ROL_EMPLEADA, {"permiso_reportes": True})

        self.assertEqual(self._que_abre(encargada), {"🛠️  ADMIN KIOSKO"})

    def test_la_casilla_vieja_de_pcs_ya_no_la_hace_encargada(self):
        """Pedido del dueño, 2026-10-22: se sacó "Operar PCs y Miembros" de
        Usuarios. Quien la tenía tildada (la columna sigue en la base, con su
        valor) ya no abre Admin Kiosko, que se le abría vacío."""
        usuario_id = usuarios_repo.crear_usuario("PCs", "1234", dominio.ROL_EMPLEADA)
        with conexion_db() as conexion:
            conexion.execute("UPDATE usuarios SET permiso_control_pcs = 1 WHERE id = ?", (usuario_id,))
        ventana = MainWindow(usuarios_repo.obtener_usuario(usuario_id), lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        self.assertEqual(self._que_abre(ventana), set())
        # Y modificarla en Usuarios no le pisa lo que tenía guardado.
        usuarios_repo.modificar_usuario(usuario_id, "PCs", dominio.ROL_EMPLEADA, permisos={})
        self.assertEqual(usuarios_repo.obtener_usuario(usuario_id)["permiso_control_pcs"], 1)

    def test_miembros_abre_para_cualquier_empleada(self):
        """Pedido del dueño, 2026-10-19: antes pedía permiso_control_pcs o Admin,
        pero cargarle saldo a un socio es una venta más y cualquiera tiene que
        poder hacerlo."""
        empleada = self._ventana("TOBY", dominio.ROL_EMPLEADA)
        botones = self._botones(empleada)

        with mock.patch("ui.main_window.MiembrosWindow") as clase:
            botones["🧑  MIEMBROS"].click()

        clase.assert_called_once()

    def test_config_admin_abre_para_todos(self):
        for ventana in (self._ventana("Admin", dominio.ROL_ADMIN), self._ventana("TOBY", dominio.ROL_EMPLEADA)):
            with mock.patch("ui.main_window.ConfiguracionAdminWindow") as clase:
                self._botones(ventana)["⚙️  CONFIG ADMIN"].click()
            clase.assert_called_once()


class TestConfiguracionAdminParaUnOperador(_ConUsuarios):
    def _habilitados(self, usuario):
        """Botón -> si se puede apretar (sin el Cerrar del final)."""
        ventana = ConfiguracionAdminWindow(usuario)
        self.addCleanup(ventana.deleteLater)
        return {b.text(): b.isEnabled() for b in ventana.findChildren(QPushButton) if b.text() != "CERRAR"}

    def test_un_operador_solo_puede_usar_gestionar_estaciones(self):
        habilitados = self._habilitados(self._usuario("TOBY", dominio.ROL_EMPLEADA))

        self.assertEqual([texto for texto, si in habilitados.items() if si], ["🖥️  GESTIONAR ESTACIONES"])
        self.assertGreater(len(habilitados), 1)  # el resto sigue a la vista, en gris

    def test_ni_con_todos_los_permisos_usa_lo_demas(self):
        # Los catálogos son de super admin: ningún permiso de empleada los habilita.
        todos = {clave: True for clave, _ in usuarios_repo.PERMISOS_EMPLEADA}
        habilitados = self._habilitados(self._usuario("TOBY", dominio.ROL_EMPLEADA, todos))

        self.assertEqual([texto for texto, si in habilitados.items() if si], ["🖥️  GESTIONAR ESTACIONES"])

    def test_el_admin_usa_todo(self):
        habilitados = self._habilitados(self._usuario("Admin", dominio.ROL_ADMIN))

        self.assertTrue(all(habilitados.values()), habilitados)

    def test_un_operador_abre_gestionar_estaciones(self):
        ventana = ConfiguracionAdminWindow(self._usuario("TOBY", dominio.ROL_EMPLEADA))
        self.addCleanup(ventana.deleteLater)
        boton = next(b for b in ventana.findChildren(QPushButton) if b.text() == "🖥️  GESTIONAR ESTACIONES")

        with mock.patch("ui.main_window.DialogoGestionEstaciones") as dialogo:
            boton.click()

        dialogo.assert_called_once()


class TestGestionarEstacionesParaUnOperador(_ConUsuarios):
    """Adentro de Gestionar Estaciones el Operador usa todo menos la contraseña de
    las PCs clientes y Actualizar el Cliente PC, que ve en gris (pedido del dueño,
    2026-10-19: el fondo y el filtro sí los puede usar)."""

    def _habilitados(self, usuario):
        ventana = DialogoGestionEstaciones(usuario)
        self.addCleanup(ventana.deleteLater)
        return {b.text(): b.isEnabled() for b in ventana.findChildren(QPushButton)}

    def test_un_operador_ve_en_gris_la_contrasena_y_actualizar_el_cliente_pc(self):
        habilitados = self._habilitados(self._usuario("TOBY", dominio.ROL_EMPLEADA))

        self.assertEqual(sorted(texto for texto, si in habilitados.items() if not si),
                         ["Actualizar el Cliente PC de las PCs...", "Cambiar contraseña de PC clientes..."])
        for texto in ("Agregar", "Renombrar seleccionada", "Fondo de pantalla de las PCs...",
                      "Filtro de palabras de las PCs..."):
            self.assertTrue(habilitados[texto], texto)

    def test_el_admin_usa_todo(self):
        habilitados = self._habilitados(self._usuario("Admin", dominio.ROL_ADMIN))

        self.assertTrue(all(habilitados.values()), habilitados)
