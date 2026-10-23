"""
tests/test_pcs_libres.py
========================
Los botones DESCONGELAR, REINICIAR y APAGAR de abajo del mosaico de Control de
PCs (pedido del dueño, 2026-10-22; APAGAR el 2026-10-23): van a todas las PCs
prendidas y libres de una vez (pcs_libres_repo) y nunca a una con un cliente.
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
from control_pcs.ui.pcs_reiniciar_dialogo import DialogoApagar, DialogoReiniciar  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402
from test_congelado import ocupar  # noqa: E402

_app = QApplication.instance() or QApplication([])



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


class TestApagar(_TresPcs):
    def test_manda_apagar_solo_a_la_prendida_y_libre(self):
        apagadas, salteadas = pcs_libres_repo.apagar(self.todas)

        self.assertEqual(apagadas, ["PC1"])
        self.assertEqual(salteadas, ["PC2", "PC3"])
        self.assertEqual(self.pendiente(self.libre), dominio.COMANDO_APAGAR)
        self.assertIsNone(self.pendiente(self.ocupada))

    def test_vuelve_a_mirar_por_si_se_sento_un_cliente_despues_de_preguntar(self):
        ocupar(self.libre)
        self.assertEqual(pcs_libres_repo.apagar([self.libre]), ([], ["PC1"]))
        self.assertIsNone(self.pendiente(self.libre))


class TestBotones(_TresPcs):
    def botones(self):
        botones = BotonesParaLasLibres(pcs_repo.estado_estaciones)
        self.addCleanup(botones.deleteLater)
        return botones

    def test_un_operador_ve_los_tres_afuera_del_fondo_negro(self):
        # Pedido del dueño (2026-10-22): el mantenimiento lo suelen hacer los
        # operadores; y los botones van debajo del fondo negro, no adentro.
        operador = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        panel = PanelControlPcs(usuarios_repo.obtener_usuario(operador))
        panel.detener_actualizacion()
        self.addCleanup(panel.deleteLater)

        botones = panel.botones_libres
        fila = botones.layout()
        self.assertEqual([fila.itemAt(i).widget() for i in range(3)],
                         [botones.boton_descongelar, botones.boton_reiniciar, botones.boton_apagar])
        self.assertEqual(botones.boton_descongelar.text(), " DESCONGELAR")
        self.assertEqual(botones.boton_reiniciar.text(), "🔄  REINICIAR")
        self.assertEqual(botones.boton_apagar.text(), " APAGAR")
        fondo_negro = panel.mosaico.parentWidget()
        self.assertEqual(fondo_negro.objectName(), "marcoMosaico")
        self.assertFalse(fondo_negro.isAncestorOf(botones))

    def test_el_copo_de_nieve_y_el_de_apagar_son_dibujos_no_emojis(self):
        # El 🧊 salía como un rectángulo en la PC del mostrador (2026-10-23).
        botones = self.botones()
        for boton in (botones.boton_descongelar, botones.boton_apagar):
            self.assertFalse(boton.icon().isNull())
            imagen = boton.icon().pixmap(18, 18).toImage()
            pintados = sum(imagen.pixelColor(x, y).alpha() > 0 for x in range(18) for y in range(18))
            self.assertGreater(pintados, 20)

    def test_descongelar_abre_la_ventana_de_shadow_defender(self):
        botones = self.botones()
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoCongelado") as ventana:
            botones.boton_descongelar.click()
        ventana.return_value.exec.assert_called_once()

    def test_reiniciar_abre_la_ventana_para_elegir(self):
        botones = self.botones()
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoReiniciar") as ventana:
            botones.boton_reiniciar.click()
        ventana.return_value.exec.assert_called_once()

    def test_apagar_abre_la_ventana_para_elegir(self):
        botones = self.botones()
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoApagar") as ventana:
            botones.boton_apagar.click()
        ventana.return_value.exec.assert_called_once()

    def test_sin_pcs_libres_avisa_y_no_abre_la_ventana(self):
        ocupar(self.libre)
        botones = self.botones()
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoReiniciar") as ventana, \
                mock.patch("control_pcs.ui.pcs_botones_libres.mostrar_info") as aviso:
            ventana.TITULO, ventana.INFINITIVO = DialogoReiniciar.TITULO, DialogoReiniciar.INFINITIVO
            botones.boton_reiniciar.click()
        ventana.assert_not_called()
        self.assertIn("ninguna PC prendida y libre para reiniciar", aviso.call_args.args[2])

    def test_sin_pcs_libres_apagar_avisa_y_no_abre_la_ventana(self):
        ocupar(self.libre)
        botones = self.botones()
        with mock.patch("control_pcs.ui.pcs_botones_libres.mostrar_info") as aviso:
            botones.boton_apagar.click()
        self.assertEqual(aviso.call_args.args[1], "Apagar")
        self.assertIn("ninguna PC prendida y libre para apagar", aviso.call_args.args[2])

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
            self.dialogo.boton_mandar.click()
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


class TestVentanaApagar(_TresPcs):
    """La ventana de APAGAR es la misma que la de REINICIAR, pero manda Apagar
    (pedido del dueño, 2026-10-23)."""

    def setUp(self):
        super().setUp()
        self.otra_libre = pcs_repo.crear_estacion("PC4")
        pcs_repo.registrar_conexion(self.otra_libre)
        self.dialogo = DialogoApagar(pcs_repo.estado_estaciones())
        self.addCleanup(self.dialogo.deleteLater)

    def apagar(self):
        with mock.patch("control_pcs.ui.pcs_reiniciar_dialogo.confirmar", return_value=True) as pregunta, \
                mock.patch("control_pcs.ui.pcs_reiniciar_dialogo.mostrar_info") as aviso:
            self.dialogo.boton_mandar.click()
        return pregunta, aviso

    def test_apaga_las_marcadas_y_no_las_desmarcadas(self):
        self.assertEqual(self.dialogo.windowTitle(), "Apagar PCs prendidas y libres")
        self.assertEqual(self.dialogo.boton_mandar.text(), "Apagar las marcadas")
        self.dialogo.tabla.item(1, 0).setCheckState(Qt.Unchecked)

        pregunta, aviso = self.apagar()

        self.assertIn("Se van a apagar 1 PC(s):\nPC1", pregunta.call_args.args[2])
        self.assertIn("volver a prenderlas", pregunta.call_args.args[2])
        self.assertIn("1 PC(s)", aviso.call_args.args[2])
        self.assertEqual(self.pendiente(self.libre), dominio.COMANDO_APAGAR)
        self.assertIsNone(self.pendiente(self.otra_libre))

    def test_si_se_sento_un_cliente_lo_dice_con_apagar(self):
        ocupar(self.libre)
        ocupar(self.otra_libre)
        _pregunta, aviso = self.apagar()
        self.assertIn("No se apagó ninguna PC.", aviso.call_args.args[2])
        self.assertIn("No se apagaron porque ya no estaban libres: PC1, PC4.", aviso.call_args.args[2])
