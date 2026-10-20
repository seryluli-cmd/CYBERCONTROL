"""
tests/test_lista_miembros.py
==============================
La lista de Administración de Miembros (pedido del dueño, 2026-10-20): en
orden alfabético por usuario, en una ventana alta para ver muchos socios sin
bajar, y con una lupa para buscar por usuario. Plataforma "offscreen" de Qt: no se abre ninguna ventana.

Se ejecutan con:

    python -m unittest discover tests
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402

from control_pcs.repositories import miembros_repo  # noqa: E402
from control_pcs.ui.miembros_window import ALTO_DE_LA_VENTANA, MiembrosWindow  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Cargados desordenados, con nombres en otro orden y mayúsculas mezcladas.
SOCIOS = [("zenex", "Cris"), ("MissGloom", "Gaby"), ("agus555", "Zulema"), ("Toxin", "Agustin")]
EN_ORDEN = ["agus555", "MissGloom", "Toxin", "zenex"]


class TestOrdenPorUsuario(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        for usuario, nombre in SOCIOS:
            miembros_repo.crear_miembro(usuario, "clave123", nombre)

    def test_van_por_usuario_sin_importar_mayusculas(self):
        self.assertEqual([m["usuario"] for m in miembros_repo.listar_miembros()], EN_ORDEN)

    def test_con_los_inactivos_tambien(self):
        miembro = next(m for m in miembros_repo.listar_miembros() if m["usuario"] == "Toxin")
        miembros_repo.desactivar_miembro(miembro["id"])

        self.assertEqual([m["usuario"] for m in miembros_repo.listar_miembros()],
                         ["agus555", "MissGloom", "zenex"])
        self.assertEqual([m["usuario"] for m in miembros_repo.listar_miembros(incluir_inactivos=True)],
                         EN_ORDEN)

    def test_la_ventana_los_muestra_en_ese_orden(self):
        operador = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA))
        ventana = MiembrosWindow(operador)

        self.assertEqual([ventana.tabla.item(fila, 0).text() for fila in range(ventana.tabla.rowCount())],
                         EN_ORDEN)
        # Elegir un renglón elige a ese socio (la lista de atrás va en el mismo orden).
        ventana.tabla.selectRow(1)
        self.assertEqual(ventana._seleccionado()["usuario"], "MissGloom")


class TestLupa(BaseConBaseTemporal):
    """Buscar por usuario (pedido del dueño, 2026-10-20)."""

    def setUp(self):
        super().setUp()
        for usuario, nombre in SOCIOS + [("cris_77", "Ana"), ("elcris", "Bruno"), ("crisxx", "Cristina")]:
            miembros_repo.crear_miembro(usuario, "clave123", nombre)

    def _usuarios(self, **filtro):
        return [m["usuario"] for m in miembros_repo.listar_miembros(**filtro)]

    def test_busca_en_el_usuario_sin_importar_mayusculas(self):
        self.assertEqual(self._usuarios(texto_busqueda="CRIS"), ["cris_77", "crisxx", "elcris"])
        self.assertEqual(self._usuarios(texto_busqueda="  gloom "), ["MissGloom"])

    def test_no_busca_en_el_nombre(self):
        # "Cris" es el nombre de zenex y "Cristina" el de crisxx: zenex no sale.
        self.assertNotIn("zenex", self._usuarios(texto_busqueda="cris"))

    def test_un_guion_bajo_se_busca_tal_cual(self):
        self.assertEqual(self._usuarios(texto_busqueda="s_7"), ["cris_77"])

    def test_sin_texto_estan_todos_y_respeta_los_inactivos(self):
        self.assertEqual(len(self._usuarios(texto_busqueda="")), 7)
        miembro = next(m for m in miembros_repo.listar_miembros() if m["usuario"] == "elcris")
        miembros_repo.desactivar_miembro(miembro["id"])
        self.assertEqual(self._usuarios(texto_busqueda="cris"), ["cris_77", "crisxx"])
        self.assertEqual(self._usuarios(texto_busqueda="cris", incluir_inactivos=True),
                         ["cris_77", "crisxx", "elcris"])

    def test_la_ventana_filtra_mientras_se_escribe(self):
        operador = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA))
        ventana = MiembrosWindow(operador)

        ventana.campo_buscar.setText("cris")
        self.assertEqual([ventana.tabla.item(fila, 0).text() for fila in range(ventana.tabla.rowCount())],
                         ["cris_77", "crisxx", "elcris"])
        # Lo elegido en la lista filtrada es ese socio, no el de esa fila sin filtrar.
        ventana.tabla.selectRow(2)
        self.assertEqual(ventana._seleccionado()["usuario"], "elcris")

        ventana.campo_buscar.clear()
        self.assertEqual(ventana.tabla.rowCount(), 7)


class TestVentanaAlta(BaseConBaseTemporal):
    def test_es_alta_pero_entra_en_la_pantalla(self):
        operador = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA))
        ventana = MiembrosWindow(operador)

        disponible = ventana.screen().availableGeometry().height()
        self.assertEqual(ventana.height(), min(ALTO_DE_LA_VENTANA, disponible - 80))
        self.assertEqual(ventana.width(), 860)
