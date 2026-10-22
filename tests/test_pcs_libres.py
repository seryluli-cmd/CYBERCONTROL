"""
tests/test_pcs_libres.py
========================
Los botones DESCONGELAR y REINICIAR de abajo del mosaico de Control de PCs
(pedido del dueño, 2026-10-22): van a todas las PCs prendidas y libres de una
vez (pcs_libres_repo) y nunca a una con un cliente.
"""

import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import comandos_pc_repo, pcs_libres_repo, pcs_repo  # noqa: E402
from control_pcs.ui.pcs_botones_libres import BotonesParaLasLibres  # noqa: E402
from control_pcs.ui.pcs_congelado_dialogo import COLUMNA_PC, DialogoCongelado  # noqa: E402
from control_pcs.ui.pcs_reiniciar_dialogo import DialogoReiniciar  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402
from test_congelado import ocupar  # noqa: E402

_app = QApplication.instance() or QApplication([])

ADMIN = {"id": 1, "nombre": "Admin", "rol": dominio.ROL_ADMIN}
EMPLEADA = {"id": 2, "nombre": "TOBY", "rol": dominio.ROL_EMPLEADA}


class _TresPcs(BaseConBaseTemporal):
    """PC1 prendida y libre, PC2 prendida con un cliente, PC3 apagada."""

    def setUp(self):
        super().setUp()
        self.libre = pcs_repo.crear_estacion("PC1")
        self.ocupada = pcs_repo.crear_estacion("PC2")
        self.apagada = pcs_repo.crear_estacion("PC3")
        pcs_repo.registrar_conexion(self.libre)
        pcs_repo.registrar_conexion(self.ocupada)
        ocupar(self.ocupada)
        self.todas = [self.libre, self.ocupada, self.apagada]

    def pendiente(self, estacion_id):
        comando = comandos_pc_repo.proximo_comando_pendiente(estacion_id)
        return comando["tipo"] if comando is not None else None


class TestCualesSonLibres(_TresPcs):
    def test_solo_la_prendida_sin_cliente(self):
        libres = pcs_libres_repo.prendidas_y_libres(pcs_repo.estado_estaciones())
        self.assertEqual([item["estacion"]["nombre"] for item in libres], ["PC1"])


class TestReiniciar(_TresPcs):
    def test_manda_reiniciar_solo_a_la_prendida_y_libre(self):
        reiniciadas, salteadas = pcs_libres_repo.reiniciar(self.todas)

        self.assertEqual(reiniciadas, ["PC1"])
        self.assertEqual(salteadas, ["PC2", "PC3"])
        self.assertEqual(self.pendiente(self.libre), dominio.COMANDO_REINICIAR)
        self.assertIsNone(self.pendiente(self.ocupada))
        self.assertIsNone(self.pendiente(self.apagada))

    def test_vuelve_a_mirar_por_si_se_sento_un_cliente_despues_de_preguntar(self):
        vistas = [item["estacion"]["id"] for item in pcs_libres_repo.prendidas_y_libres(pcs_repo.estado_estaciones())]
        ocupar(self.libre)

        self.assertEqual(pcs_libres_repo.reiniciar(vistas), ([], ["PC1"]))
        self.assertIsNone(self.pendiente(self.libre))

    def test_una_pc_dada_de_baja_en_el_medio_no_se_reinicia(self):
        pcs_repo.desactivar_estacion(self.libre)
        self.assertEqual(pcs_libres_repo.reiniciar([self.libre]), ([], []))
        self.assertIsNone(self.pendiente(self.libre))


class TestBotones(_TresPcs):
    def botones(self, usuario):
        botones = BotonesParaLasLibres(usuario, pcs_repo.estado_estaciones)
        self.addCleanup(botones.deleteLater)
        return botones

    def test_descongelar_solo_lo_ve_el_admin_y_reiniciar_cualquiera(self):
        self.assertIsNotNone(self.botones(ADMIN).boton_descongelar)
        empleada = self.botones(EMPLEADA)
        self.assertIsNone(empleada.boton_descongelar)
        self.assertEqual(empleada.boton_reiniciar.text(), "🔄  REINICIAR")

    def test_reiniciar_abre_la_ventana_para_elegir(self):
        botones = self.botones(EMPLEADA)
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoReiniciar") as ventana:
            botones.boton_reiniciar.click()
        ventana.return_value.exec.assert_called_once()

    def test_sin_pcs_libres_avisa_y_no_abre_la_ventana(self):
        ocupar(self.libre)
        botones = self.botones(EMPLEADA)
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoReiniciar") as ventana, \
                mock.patch("control_pcs.ui.pcs_botones_libres.mostrar_info") as aviso:
            botones.boton_reiniciar.click()
        ventana.assert_not_called()
        self.assertIn("ninguna PC prendida y libre", aviso.call_args.args[2])

    def test_la_ventana_de_descongelar_arranca_con_las_libres_marcadas(self):
        dialogo = DialogoCongelado(None, pcs_repo.estado_estaciones())
        self.addCleanup(dialogo.deleteLater)
        # Se cierra dentro de la prueba: al cerrar, la ventana toca la base temporal.
        try:
            marcadas = {
                estacion_id for estacion_id, (fila, _item) in dialogo._filas.items()
                if dialogo.tabla.item(fila, COLUMNA_PC).checkState() == Qt.Checked
            }
            self.assertEqual(marcadas, {self.libre})
        finally:
            dialogo.close()


class TestVentanaReiniciar(_TresPcs):
    """La ventana de REINICIAR: solo las prendidas y libres, todas marcadas, y se
    pueden desmarcar (pedido del dueño, 2026-10-22)."""

    def setUp(self):
        super().setUp()
        self.otra_libre = pcs_repo.crear_estacion("PC4")
        pcs_repo.registrar_conexion(self.otra_libre)
        self.dialogo = DialogoReiniciar(pcs_repo.estado_estaciones())
        self.addCleanup(self.dialogo.deleteLater)

    def reiniciar(self, confirma=True):
        with mock.patch("control_pcs.ui.pcs_reiniciar_dialogo.confirmar", return_value=confirma) as pregunta, \
                mock.patch("control_pcs.ui.pcs_reiniciar_dialogo.mostrar_info") as aviso:
            self.dialogo.boton_reiniciar.click()
        return pregunta, aviso

    def test_aparecen_solo_las_prendidas_y_libres_todas_marcadas(self):
        self.assertEqual(self.dialogo._marcadas(), [(self.libre, "PC1"), (self.otra_libre, "PC4")])
        self.assertEqual(self.dialogo.tabla.rowCount(), 2)

    def test_reinicia_las_marcadas(self):
        pregunta, aviso = self.reiniciar()

        self.assertIn("PC1, PC4", pregunta.call_args.args[2])
        self.assertIn("2 PC(s)", aviso.call_args.args[2])
        for estacion_id in (self.libre, self.otra_libre):
            self.assertEqual(self.pendiente(estacion_id), dominio.COMANDO_REINICIAR)

    def test_una_desmarcada_no_se_reinicia(self):
        self.dialogo.tabla.item(1, 0).setCheckState(Qt.Unchecked)
        self.reiniciar()
        self.assertEqual(self.pendiente(self.libre), dominio.COMANDO_REINICIAR)
        self.assertIsNone(self.pendiente(self.otra_libre))

    def test_desmarcar_todas_y_volver_a_marcar(self):
        self.dialogo._marcar(Qt.Unchecked)
        pregunta, _aviso = self.reiniciar()
        pregunta.assert_not_called()
        self.assertIn("al menos una", self.dialogo.etiqueta_estado.text())
        self.assertIsNone(self.pendiente(self.libre))

        self.dialogo._marcar(Qt.Checked)
        self.assertEqual(len(self.dialogo._marcadas()), 2)

    def test_si_dice_que_no_no_reinicia_nada(self):
        self.reiniciar(confirma=False)
        self.assertIsNone(self.pendiente(self.libre))
        self.assertIsNone(self.pendiente(self.otra_libre))
