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
from control_pcs.ui.pcs_dibujos import COLOR_APAGAR  # noqa: E402
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

    def test_separar_en_libres_en_uso_y_apagadas(self):
        partes = pcs_libres_repo.separar(pcs_repo.estado_estaciones())
        nombres = [[item["estacion"]["nombre"] for item in parte] for parte in partes]
        self.assertEqual(nombres, [["PC1"], ["PC2"], ["PC3"]])


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
        self.assertEqual(botones.boton_reiniciar.text(), " REINICIAR")
        self.assertEqual(botones.boton_apagar.text(), " APAGAR")
        fondo_negro = panel.mosaico.parentWidget()
        self.assertEqual(fondo_negro.objectName(), "marcoMosaico")
        self.assertFalse(fondo_negro.isAncestorOf(botones))

    def test_el_copo_de_nieve_reiniciar_y_apagar_son_dibujos_no_emojis(self):
        # El 🧊 salía como un rectángulo en la PC del mostrador (2026-10-23). REINICIAR era el 🔄
        # azul, igual al de Operador: ahora son flechas rojas dibujadas (2026-10-24).
        botones = self.botones()
        for boton in (botones.boton_descongelar, botones.boton_reiniciar, botones.boton_apagar):
            self.assertFalse(boton.icon().isNull())
            imagen = boton.icon().pixmap(18, 18).toImage()
            pintados = sum(imagen.pixelColor(x, y).alpha() > 0 for x in range(18) for y in range(18))
            self.assertGreater(pintados, 20)

    def test_las_flechas_de_reiniciar_son_del_rojo_de_apagar(self):
        botones = self.botones()
        imagen = botones.boton_reiniciar.icon().pixmap(64, 64).toImage()
        colores = {imagen.pixelColor(x, y).name() for x in range(64) for y in range(64)
                   if imagen.pixelColor(x, y).alpha() == 255}
        self.assertEqual(colores, {COLOR_APAGAR.lower()})

    def test_descongelar_abre_la_ventana_de_shadow_defender(self):
        botones = self.botones()
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoCongelado") as ventana:
            botones.boton_descongelar.click()
        ventana.return_value.exec.assert_called_once()

    def test_descongelar_le_pasa_quien_esta_logueado(self):
        # Para que el Administrador vea ACTUALIZAR CLIENTES en esa ventana (2026-10-28).
        admin = {"rol": dominio.ROL_ADMIN}
        botones = BotonesParaLasLibres(pcs_repo.estado_estaciones, admin)
        self.addCleanup(botones.deleteLater)
        with mock.patch("control_pcs.ui.pcs_botones_libres.DialogoCongelado") as ventana:
            botones.boton_descongelar.click()
        self.assertIs(ventana.call_args.args[2], admin)

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
    """La ventana de REINICIAR: solo se marcan las prendidas y libres, que arrancan
    todas marcadas y se pueden desmarcar (pedido del dueño, 2026-10-22). Desde el
    2026-10-28 son fichas como las del mosaico, y las que están en uso se ven aparte
    sin poder marcarse (maqueta "B" que eligió el dueño)."""

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
        self.assertEqual([ficha.nombre for ficha in self.dialogo.fichas], ["PC1", "PC4"])
        self.assertEqual(self.dialogo.pastilla_marcadas.text(), "2 MARCADAS")
        self.assertEqual(self.dialogo.boton_mandar.accessibleName(), "Reiniciar las 2 marcadas")

    def test_las_que_estan_en_uso_se_ven_aparte_y_no_se_marcan(self):
        # Lo pidió el dueño: que se entienda que a las que están en uso no les pasa nada.
        (en_uso,) = self.dialogo.fichas_en_uso
        self.assertEqual(en_uso.nombre, "PC2")
        self.assertFalse(en_uso.isEnabled())
        self.assertFalse(en_uso.isCheckable())
        self.assertTrue(en_uso.detalle.text().startswith("QUEDAN "))
        self.assertNotIn("PC3", [ficha.nombre for ficha in self.dialogo.fichas + self.dialogo.fichas_en_uso])

    def test_el_aviso_dice_que_solo_se_tocan_las_prendidas_y_libres(self):
        texto = self.dialogo.aviso.text()
        self.assertIn("Solo se reinician las PCs PRENDIDAS y LIBRES", texto)
        self.assertIn("Las PCs en uso, con tiempo disponible, <b>no se reinician</b>", texto)

    def test_una_ficha_desmarcada_dice_que_no_se_toca(self):
        ficha = self.dialogo.fichas[1]
        self.assertEqual(ficha.detalle.text(), "SE REINICIA")
        ficha.click()
        self.assertFalse(ficha.isChecked())
        self.assertEqual(ficha.detalle.text(), "NO SE REINICIA")
        self.assertEqual(ficha.property("estado"), "desmarcada")
        self.assertEqual(self.dialogo.pastilla_marcadas.text(), "1 MARCADA")
        self.assertEqual(self.dialogo.boton_mandar.accessibleName(), "Reiniciar la marcada")

    def test_reinicia_las_marcadas(self):
        pregunta, aviso = self.reiniciar()

        self.assertIn("PC1, PC4", pregunta.call_args.args[2])
        self.assertIn("2 PC(s)", aviso.call_args.args[2])
        for estacion_id in (self.libre, self.otra_libre):
            self.assertEqual(self.pendiente(estacion_id), dominio.COMANDO_REINICIAR)

    def test_una_desmarcada_no_se_reinicia(self):
        self.dialogo.fichas[1].setChecked(False)
        self.reiniciar()
        self.assertEqual(self.pendiente(self.libre), dominio.COMANDO_REINICIAR)
        self.assertIsNone(self.pendiente(self.otra_libre))

    def test_desmarcar_todas_y_volver_a_marcar(self):
        self.dialogo._marcar(False)
        self.assertFalse(self.dialogo.boton_mandar.isEnabled())
        self.assertIn("al menos una", self.dialogo.boton_mandar.detalle.text())
        pregunta, _aviso = self.reiniciar()
        pregunta.assert_not_called()
        self.assertIsNone(self.pendiente(self.libre))

        self.dialogo._marcar(True)
        self.assertEqual(len(self.dialogo._marcadas()), 2)
        self.assertTrue(self.dialogo.boton_mandar.isEnabled())

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
        self.assertIn("Solo se apagan las PCs PRENDIDAS y LIBRES", self.dialogo.aviso.text())
        self.assertIn("no se apagan", self.dialogo.aviso.text())
        self.dialogo.fichas[1].setChecked(False)
        self.assertEqual(self.dialogo.fichas[1].detalle.text(), "NO SE APAGA")
        self.assertEqual(self.dialogo.boton_mandar.accessibleName(), "Apagar la marcada")

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


class TestFichasSinPcsEnUso(BaseConBaseTemporal):
    """Sin ninguna PC en uso ni apagada, la ventana no muestra esa parte."""

    def test_sin_en_uso_no_hay_fichas_aparte_ni_su_explicacion(self):
        pcs_repo.registrar_conexion(pcs_repo.crear_estacion("PC1"))
        dialogo = DialogoApagar(pcs_repo.estado_estaciones())
        self.addCleanup(dialogo.deleteLater)
        self.assertEqual(dialogo.fichas_en_uso, [])
        self.assertNotIn("se ven abajo", dialogo.aviso.text())

    def test_lo_que_queda_se_ve_sin_segundos(self):
        from control_pcs.ui.pcs_reiniciar_dialogo import _quedan
        self.assertEqual(_quedan(5100), "1h 25m")
        self.assertEqual(_quedan(2400), "40m")
        self.assertEqual(_quedan(912), "15m")
