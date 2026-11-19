"""
tests/test_tareas_turno_aviso.py
=================================
El aviso de TAREAS DEL TURNO (pedido del dueño, 2026-11-03; ui/aviso_tarea.py): sale
encima de todo a la hora de una tarea, lo arranca la ventana principal del mostrador
y vuelve hasta que alguien pone TAREA HECHA. La ventana del botón ⏰ TAREAS, en
tests/test_tareas_turno_pantalla.py; las reglas de adentro, en tests/test_tareas_turno.py.

El reloj se inyecta: las pruebas dicen qué hora es y cuándo se revisa (los timers de
verdad del aviso quedan parados), así nada depende de la hora en que se corren.

Se ejecutan con:

    python -m unittest discover tests
"""

import unittest
from datetime import datetime
from unittest import mock

from base_tareas_turno_pantalla import BASURA, CIGARRILLOS, LUCES, _ConTareas

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QApplication, QDialog

import dominio
from repositories import usuarios_repo
from ui.aviso_tarea import (
    INTERVALO_REVISION_TAREAS_MS, MILISEGUNDOS_PRIMERA_REVISION, MILISEGUNDOS_SIN_RESPONDER,
    SEGUNDOS_SIN_AVISAR_TRAS_CORRERSE, AvisoDeTarea, RevisorDeTareas,
)
from ui.main_window import MainWindow
from ui.tareas_turno_dialogos import DialogoTarea
from ui.tareas_turno_window import COLUMNA_ESTADO, COLUMNA_HECHA, VentanaTareasTurno


class _ConElMostrador(_ConTareas):
    def setUp(self):
        super().setUp()
        self.reloj = [datetime(2026, 11, 3, 19, 30, 10)]

    def _mostrador(self, al_cerrar_sesion=lambda: None, usuario=None):
        ventana = MainWindow(usuario or self.carla, al_cerrar_sesion)
        revisor = ventana._tareas
        # Los relojes de verdad, parados: la prueba revisa cuando quiere y con su hora.
        revisor._timer.stop()
        revisor._timer_primera.stop()
        revisor._ahora = lambda: self.reloj[0]
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.close)
        ventana.show()
        return ventana

    def _a_las(self, ventana, hora, minuto, segundo=0):
        """Son las hora:minuto:segundo del martes y toca la revisión: el aviso que
        quedó a la vista (o None)."""
        self.reloj[0] = datetime(2026, 11, 3, hora, minuto, segundo)
        ventana._tareas.revisar()
        return ventana._tareas.aviso

    def _la_de_las_luces(self):
        return self._de_hoy(self.reloj[0])[LUCES]


class TestElAviso(_ConElMostrador):
    def test_sale_encima_de_todo_sin_ventana_madre_y_sin_la_cruz(self):
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        self.assertIsNone(self._a_las(ventana, 19, 29, 50))

        aviso = self._a_las(ventana, 19, 30, 10)
        self.assertIsInstance(aviso, AvisoDeTarea)
        self.assertTrue(aviso.isVisible())
        self.assertIsNone(aviso.parent())
        banderas = aviso.windowFlags()
        self.assertEqual(banderas & Qt.WindowStaysOnTopHint, Qt.WindowStaysOnTopHint)
        self.assertNotEqual(banderas & Qt.WindowCloseButtonHint, Qt.WindowCloseButtonHint)
        self.assertEqual(aviso.windowModality(), Qt.ApplicationModal)
        self.assertIs(QApplication.activeModalWidget(), aviso)
        self.assertEqual(aviso.etiqueta_hora.text(), "ES LA HORA · 19:30")
        self.assertEqual(aviso.etiqueta_texto.text(), LUCES)
        # Con una sola, sin el "1 de 1"; y nadie la pospuso todavía.
        self.assertEqual(aviso.etiqueta_turno.text(), "Turno Tarde")
        self.assertTrue(aviso.etiqueta_pospuesta.isHidden())
        self.assertEqual([boton.text() for boton in aviso.teclas],
                         ["POSPONER 5 MIN", "POSPONER 10 MIN", "✔  TAREA HECHA"])

        # Alt+F4 llega a closeEvent: tampoco lo cierra.
        aviso.close()
        self.assertTrue(aviso.isVisible())
        self.assertIs(ventana._tareas.aviso, aviso)

    def test_ninguna_tecla_lo_cierra_ni_aprieta_un_boton(self):
        # La pistola de códigos escribe dígitos + Enter: si justo están vendiendo, no
        # puede marcarla hecha sin querer.
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)
        aviso._prender_teclas()

        for tecla in (Qt.Key_Escape, Qt.Key_Return, Qt.Key_Enter, Qt.Key_Space, Qt.Key_7):
            QTest.keyClick(aviso, tecla)
            for boton in aviso.teclas:
                QTest.keyClick(boton, tecla)
        QTest.keyClicks(aviso, "7790001234567")
        QTest.keyClick(aviso, Qt.Key_Return)

        self.assertTrue(aviso.isVisible())
        self.assertIs(ventana._tareas.aviso, aviso)
        self.assertTrue(all(boton.focusPolicy() == Qt.NoFocus for boton in aviso.teclas))
        tarea = self._la_de_las_luces()
        self.assertEqual((tarea["estado"], tarea["veces_pospuesta"]), (dominio.TAREA_ATRASADA, 0))

    def test_los_botones_no_responden_el_primer_segundo(self):
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)

        self.assertEqual(MILISEGUNDOS_SIN_RESPONDER, 1000)
        self.assertTrue(aviso._timer_teclas.isActive())
        self.assertEqual(aviso._timer_teclas.interval(), MILISEGUNDOS_SIN_RESPONDER)
        self.assertFalse(any(boton.isEnabled() for boton in aviso.teclas))
        # Un toque que ya iba a otra cosa no lo aprieta.
        aviso.boton_hecha.click()
        aviso.botones_posponer[5].click()
        self.assertIs(ventana._tareas.aviso, aviso)
        tarea = self._la_de_las_luces()
        self.assertEqual((tarea["estado"], tarea["veces_pospuesta"]), (dominio.TAREA_ATRASADA, 0))

        QTest.qWait(MILISEGUNDOS_SIN_RESPONDER + 150)
        self.assertTrue(all(boton.isEnabled() for boton in aviso.teclas))

    def test_posponer_5_y_10_vuelve_a_salir_pasado_ese_rato(self):
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)
        aviso._prender_teclas()
        aviso.botones_posponer[5].click()
        self.assertFalse(aviso.isVisible())
        self.assertIsNone(ventana._tareas.aviso)

        # Pospuesta a las 19:30:10 por 5: hasta las 19:35:10 no sale.
        self.assertIsNone(self._a_las(ventana, 19, 35, 0))
        aviso = self._a_las(ventana, 19, 35, 15)
        self.assertIsNotNone(aviso)
        self.assertEqual(aviso.etiqueta_pospuesta.text(), "Ya la pospusieron 1 vez (Carla, 19:30)")
        self.assertFalse(aviso.etiqueta_pospuesta.isHidden())

        aviso._prender_teclas()
        aviso.botones_posponer[10].click()
        self.assertIsNone(self._a_las(ventana, 19, 45, 0))
        self.assertIsNotNone(self._a_las(ventana, 19, 45, 20))
        tarea = self._la_de_las_luces()
        self.assertEqual([(p["nombre"], p["minutos"]) for p in tarea["posposiciones"]], [("Carla", 5), ("Carla", 10)])
        # Pospuesta sigue atrasada: el botón de la barra la cuenta.
        self.assertEqual(ventana.boton_tareas.text(), "⏰  TAREAS · 1")

    def test_tarea_hecha_no_vuelve_a_salir(self):
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)
        aviso._prender_teclas()
        aviso.boton_hecha.click()

        self.assertFalse(aviso.isVisible())
        self.assertIsNone(ventana._tareas.aviso)
        for hora, minuto in ((19, 45), (21, 59), (23, 30)):
            self.assertIsNone(self._a_las(ventana, hora, minuto))
        tarea = self._la_de_las_luces()
        self.assertEqual((tarea["estado"], tarea["hecha_por"]), (dominio.TAREA_HECHA, "Carla"))
        self.assertEqual(ventana.boton_tareas.text(), "⏰  TAREAS")
        self.assertEqual(ventana._tareas_atrasadas, 0)

    def test_si_tocan_dos_a_la_vez_salen_de_a_una(self):
        self._cargar(BASURA, "19:30")
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        primera = self._a_las(ventana, 19, 30, 10)
        self.assertEqual((primera.etiqueta_texto.text(), primera.etiqueta_turno.text()),
                         (LUCES, "Turno Tarde · 1 de 2"))
        primera._prender_teclas()
        primera.boton_hecha.click()

        segunda = ventana._tareas.aviso
        self.assertIsNot(segunda, primera)
        self.assertEqual((segunda.etiqueta_texto.text(), segunda.etiqueta_turno.text()),
                         (BASURA, "Turno Tarde · 2 de 2"))
        # Arranca con los botones apagados: el segundo toque de un doble clic en HECHA
        # caería en esta.
        self.assertFalse(segunda.boton_hecha.isEnabled())
        segunda._prender_teclas()
        segunda.botones_posponer[5].click()
        self.assertIsNone(ventana._tareas.aviso)
        hoy = self._de_hoy(self.reloj[0])
        self.assertEqual((hoy[LUCES]["estado"], hoy[BASURA]["veces_pospuesta"]), (dominio.TAREA_HECHA, 1))

    def test_la_que_llega_con_un_aviso_abierto_se_suma_a_la_tanda(self):
        self._cargar(LUCES, "19:30")
        self._cargar(BASURA, "19:32")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)
        self.assertEqual(aviso.etiqueta_turno.text(), "Turno Tarde")

        self.assertIs(self._a_las(ventana, 19, 32, 5), aviso)
        self.assertEqual(aviso.etiqueta_turno.text(), "Turno Tarde · 1 de 2")
        aviso._prender_teclas()
        aviso.boton_hecha.click()
        self.assertEqual(ventana._tareas.aviso.etiqueta_texto.text(), BASURA)

    def test_el_cierre_forzoso_lo_corre_sin_contar_como_posponer(self):
        # MainWindow._hay_un_cobro_a_medias es lo que miran el cierre forzoso de la caja
        # y la vuelta sola del Admin antes de hacer lo suyo.
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)
        self.assertTrue(aviso.se_puede_cerrar_sola())

        self.assertTrue(ventana._hay_un_cobro_a_medias())
        self.assertFalse(aviso.isVisible())
        self.assertIsNone(ventana._tareas.aviso)
        self.assertIsNone(QApplication.activeModalWidget())
        tarea = self._la_de_las_luces()
        self.assertEqual((tarea["estado"], tarea["veces_pospuesta"]), (dominio.TAREA_ATRASADA, 0))

        # En la revisión siguiente de la caja (10 s) ya no hay nada encima: el cierre pasa.
        self.assertFalse(ventana._hay_un_cobro_a_medias())
        self.assertEqual(SEGUNDOS_SIN_AVISAR_TRAS_CORRERSE, 60)
        self.assertIsNone(self._a_las(ventana, 19, 30, 40))
        self.assertIsNone(self._a_las(ventana, 19, 31, 9))
        # Mientras tanto sigue contando como atrasada.
        self.assertEqual(ventana.boton_tareas.text(), "⏰  TAREAS · 1")
        self.assertIsNotNone(self._a_las(ventana, 19, 31, 11))

    def test_al_cerrar_la_sesion_el_aviso_se_va_sin_grabar_nada(self):
        self._cargar(LUCES, "19:30")
        salidas = []
        ventana = self._mostrador(lambda: salidas.append(True))
        aviso = self._a_las(ventana, 19, 30, 10)

        ventana._cerrar_sesion()
        self.assertEqual(salidas, [True])
        self.assertFalse(aviso.isVisible())
        self.assertIsNone(ventana._tareas.aviso)
        self.assertIsNone(QApplication.activeModalWidget())
        self.assertFalse(ventana._tareas._timer.isActive())
        # Sin nadie adentro no vuelve a salir.
        self.assertIsNone(self._a_las(ventana, 19, 45))
        tarea = self._la_de_las_luces()
        self.assertEqual((tarea["estado"], tarea["veces_pospuesta"]), (dominio.TAREA_ATRASADA, 0))

    def test_con_la_ventana_principal_cerrada_no_avisa(self):
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        ventana.hide()
        self.assertIsNone(self._a_las(ventana, 19, 30, 10))

    def test_en_la_copia_abierta_desde_otra_pc_no_hay_aviso(self):
        # El aviso es del mostrador: desde otra PC no hay nadie atendiendo.
        with mock.patch("ui.main_window.modo_remoto.es_copia_remota", return_value=True), \
                mock.patch("ui.main_window.modo_remoto.mostrador_en_uso", return_value="MOSTRADOR"):
            ventana = MainWindow(self.admin, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.close)
        self.assertIsNone(ventana._tareas)
        self.assertEqual(ventana.findChildren(RevisorDeTareas), [])
        self.assertEqual(ventana.boton_tareas.text(), "⏰  TAREAS")

    def test_el_boton_de_la_barra_dice_cuantas_hay_atrasadas_y_titila_en_rojo(self):
        self._cargar(LUCES, "19:30")
        self._cargar(BASURA, "19:30")
        ventana = self._mostrador()
        boton = ventana.boton_tareas

        self.assertIsNone(self._a_las(ventana, 19, 0))
        self.assertEqual(boton.text(), "⏰  TAREAS")
        ventana._parpadear()
        self.assertEqual(boton.property("clase"), "barra")

        aviso = self._a_las(ventana, 19, 30, 10)
        self.assertEqual(boton.text(), "⏰  TAREAS · 2")
        ventana._parpadear()
        self.assertEqual(boton.property("clase"), "alerta")
        ventana._parpadear()
        self.assertEqual(boton.property("clase"), "barra")

        # Hechas las dos, vuelve a ser un botón más de la barra y deja de titilar.
        for _ in range(2):
            aviso._prender_teclas()
            aviso.boton_hecha.click()
            aviso = ventana._tareas.aviso
        self.assertEqual(boton.text(), "⏰  TAREAS")
        for _ in range(3):
            ventana._parpadear()
            self.assertEqual(boton.property("clase"), "barra")

    def test_se_pone_adelante_y_hace_titilar_la_barra_de_tareas(self):
        # Con el programa minimizado o WhatsApp Web adelante: que tome el teclado y, si
        # Windows no lo deja, que titile en la barra de tareas.
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        with mock.patch.object(QApplication, "alert") as titila, \
                mock.patch.object(AvisoDeTarea, "raise_") as adelante, \
                mock.patch.object(AvisoDeTarea, "activateWindow") as con_el_teclado:
            aviso = self._a_las(ventana, 19, 30, 10)
        titila.assert_called_once_with(aviso)
        adelante.assert_called_once_with()
        con_el_teclado.assert_called_once_with()

    def test_la_primera_revision_es_a_los_dos_segundos_de_entrar(self):
        # Una que ya está atrasada no espera la primera vuelta de 15 s.
        self._cargar(LUCES, "19:30")
        ventana = MainWindow(self.carla, lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.close)
        revisor = ventana._tareas
        primera = revisor._timer_primera
        self.assertTrue(primera.isActive())
        self.assertTrue(primera.isSingleShot())
        self.assertEqual(primera.interval(), MILISEGUNDOS_PRIMERA_REVISION)
        self.assertEqual(revisor._timer.interval(), INTERVALO_REVISION_TAREAS_MS)
        revisor._timer.stop()
        primera.stop()
        revisor._ahora = lambda: self.reloj[0]
        ventana.show()

        primera.timeout.emit()
        self.assertIsInstance(revisor.aviso, AvisoDeTarea)

    def test_al_cerrar_tareas_del_turno_el_boton_se_pone_al_dia(self):
        ventana = self._mostrador()
        with mock.patch("ui.main_window.VentanaTareasTurno") as abierta, \
                mock.patch.object(ventana._tareas, "contar") as contar:
            ventana.boton_tareas.click()
        abierta.return_value.exec.assert_called_once_with()
        contar.assert_called_once_with()

    def test_lo_que_se_contesta_en_el_aviso_se_ve_ya_en_tareas_del_turno_abierta(self):
        # Carla tiene abierta la ventana y encima sale el aviso: lo que contesta se ve
        # en la lista en el acto, no recién en su repaso de los 30 s (con la tecla HECHA
        # todavía en el renglón, que la rechazaba con un cartel).
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        vio = {}

        def exec_(tareas):
            tareas.show()
            vio["antes"] = tareas.tabla.item(0, COLUMNA_ESTADO).text()
            aviso = self._a_las(ventana, 19, 30, 10)
            QTest.qWait(MILISEGUNDOS_SIN_RESPONDER + 150)
            aviso.boton_hecha.click()
            vio["despues"] = tareas.tabla.item(0, COLUMNA_ESTADO).text()
            vio["tecla"] = tareas.tabla.cellWidget(0, COLUMNA_HECHA)
            tareas.close()
            return QDialog.Rejected

        with mock.patch("ui.main_window.VentanaTareasTurno",
                        side_effect=lambda usuario, padre: VentanaTareasTurno(usuario, padre,
                                                                              ahora=lambda: self.reloj[0])), \
                mock.patch.object(VentanaTareasTurno, "exec", exec_):
            ventana.boton_tareas.click()
        self.assertEqual(vio, {"antes": "ES LA HORA", "despues": "HECHA · Carla 19:30", "tecla": None})
        # Ya cerrada, la ventana no queda colgada de los avisos.
        self.assertEqual(ventana._tareas.receivers("2contestaron()"), 0)

    def test_si_el_repo_rechaza_la_respuesta_sale_su_cartel_y_vuelve_en_la_revision_siguiente(self):
        # A Carla la dieron de baja con la sesión abierta: TAREA HECHA no se graba. Sale
        # un solo cartel, el aviso se va y vuelve en la revisión siguiente; no en el acto
        # como "2 de 2", "3 de 3"... con un cartel por vuelta.
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        aviso = self._a_las(ventana, 19, 30, 10)
        usuarios_repo.desactivar_usuario(self.carla_id)
        aviso._prender_teclas()
        with mock.patch("ui.utils.mostrar_error") as cartel:
            aviso.boton_hecha.click()
        cartel.assert_called_once()
        self.assertIsNone(ventana._tareas.aviso)
        self.assertEqual(self._la_de_las_luces()["estado"], dominio.TAREA_ATRASADA)

        otra_vez = self._a_las(ventana, 19, 30, 25)
        self.assertIsNotNone(otra_vez)
        self.assertEqual(otra_vez.etiqueta_turno.text(), "Turno Tarde")


class TestElAvisoConOtraVentanaAbajo(_ConElMostrador):
    """El cierre forzoso de la caja y la vuelta sola del Admin corren el aviso para
    pasar, pero no si abajo queda una ventana que igual los hace esperar."""

    def test_con_un_formulario_abajo_no_se_corre_y_se_puede_contestar(self):
        # El Admin, pasados sus 10 minutos, sigue cargando una tarea: la vuelta espera
        # igual. Si corriera el aviso (lo mira cada 1 s, lo mismo que tarda en responder)
        # no se podría contestar nunca, y cada minuto le sacaría el teclado al formulario.
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador(usuario=self.admin)
        vuelta = ventana._vuelta
        vuelta._vence = vuelta._reloj() - 1
        formulario = DialogoTarea(self.admin, None, ventana, lambda: self.reloj[0])
        formulario.setWindowModality(Qt.ApplicationModal)  # como con exec()
        formulario.show()
        self.addCleanup(formulario.close)
        aviso = self._a_las(ventana, 19, 30, 10)
        self.assertFalse(aviso.se_puede_cerrar_sola())

        for _ in range(3):
            vuelta._revisar()
        # El reloj de verdad de la vuelta también corre mientras tanto.
        QTest.qWait(MILISEGUNDOS_SIN_RESPONDER + 150)
        self.assertTrue(aviso.isVisible())
        self.assertIs(ventana._tareas.aviso, aviso)
        self.assertTrue(aviso.boton_hecha.isEnabled())
        aviso.boton_hecha.click()

        self.assertEqual(self._la_de_las_luces()["hecha_por"], "Sergio")
        # El formulario sigue abierto: la vuelta sigue esperando.
        self.assertTrue(formulario.isVisible())
        self.assertFalse(vuelta._volvio)

    def test_con_una_lista_que_se_cierra_sola_abajo_se_corre_y_el_cierre_pasa(self):
        # Tareas del Turno es solo una lista: se cierra sola, así que el aviso se corre,
        # en la revisión siguiente se cierra la lista y en la otra el cierre pasa.
        self._cargar(LUCES, "19:30")
        ventana = self._mostrador()
        lista = VentanaTareasTurno(self.carla, ventana, ahora=lambda: self.reloj[0])
        lista.setWindowModality(Qt.ApplicationModal)  # como con exec()
        lista.show()
        self.addCleanup(lista.close)
        aviso = self._a_las(ventana, 19, 30, 10)
        self.assertTrue(aviso.se_puede_cerrar_sola())

        self.assertTrue(ventana._hay_un_cobro_a_medias())
        self.assertIsNone(ventana._tareas.aviso)
        self.assertFalse(aviso.isVisible())
        self.assertTrue(ventana._hay_un_cobro_a_medias())
        self.assertFalse(lista.isVisible())
        self.assertFalse(ventana._hay_un_cobro_a_medias())
        self.assertEqual(self._la_de_las_luces()["veces_pospuesta"], 0)


class TestElAvisoCercaDeLasSeis(_ConElMostrador):
    """Los avisos son solo del día del local en curso: pospuesta más allá de las 06:00,
    ya no vuelve. El aviso lo dice antes de que la pospongan."""

    def _a_las_del_miercoles(self, ventana, hora, minuto, segundo=0):
        self.reloj[0] = datetime(2026, 11, 4, hora, minuto, segundo)
        ventana._tareas.revisar()
        return ventana._tareas.aviso

    def test_avisa_que_pospuesta_ya_no_vuelve(self):
        # La de las 05:50 es de la Noche del martes y pasa el miércoles a las 05:50.
        self._cargar(CIGARRILLOS, "05:50")
        ventana = self._mostrador()
        aviso = self._a_las_del_miercoles(ventana, 5, 55)
        self.assertEqual(aviso.etiqueta_texto.text(), CIGARRILLOS)
        self.assertFalse(aviso.etiqueta_fin_del_dia.isHidden())
        self.assertEqual(aviso.etiqueta_fin_del_dia.text(),
                         "A las 06:00 termina el día: si la posponés, no vuelve a avisar y queda NO SE HIZO.")

    def test_a_las_cinco_y_cincuenta_solo_la_de_diez_minutos_no_vuelve(self):
        self._cargar(CIGARRILLOS, "05:45")
        ventana = self._mostrador()
        aviso = self._a_las_del_miercoles(ventana, 5, 50, 10)
        self.assertEqual(aviso.etiqueta_fin_del_dia.text(),
                         "A las 06:00 termina el día: si la posponés 10 MIN, no vuelve a avisar y queda NO SE HIZO.")

    def test_lejos_de_las_seis_no_dice_nada_y_se_pone_al_dia_mientras_sigue_abierto(self):
        self._cargar(CIGARRILLOS, "05:30")
        ventana = self._mostrador()
        aviso = self._a_las_del_miercoles(ventana, 5, 30, 10)
        self.assertTrue(aviso.etiqueta_fin_del_dia.isHidden())
        # Nadie lo contesta: a las 05:56 ya lo dice.
        self.assertIs(self._a_las_del_miercoles(ventana, 5, 56), aviso)
        self.assertFalse(aviso.etiqueta_fin_del_dia.isHidden())


if __name__ == "__main__":
    unittest.main()
