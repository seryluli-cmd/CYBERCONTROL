"""
tests/test_tareas_turno_pantalla.py
====================================
La ventana de TAREAS DEL TURNO (pedido del dueño, 2026-11-03, traída de FR Kiosko el
2026-11-19): el botón ⏰ TAREAS de la barra (ui/tareas_turno_window.py) y lo que abre (ui/tareas_turno_dialogos.py: el
formulario de la tarea y el historial). El aviso que sale encima de todo, en
tests/test_tareas_turno_aviso.py; las reglas de adentro, en tests/test_tareas_turno.py
y tests/test_tareas_turno_cuentas.py.

El reloj se inyecta: las pruebas dicen qué hora es, así nada depende de la hora en
que se corren.

Se ejecutan con:

    python -m unittest discover tests
"""

import unittest
from datetime import datetime
from unittest import mock

from base_tareas_turno_pantalla import (
    BASURA, CIGARRILLOS, DIARIOS, HELADERA, LUCES, PERSIANA, _ConTareas,
)

from PySide6.QtCore import Qt
from PySide6.QtTest import QTest
from PySide6.QtWidgets import QDialog, QPushButton

import dominio
from repositories import tareas_turno_repo
from ui.tareas_turno_dialogos import DialogoHistorialTareas, DialogoTarea, texto_de_lo_pospuesto
from ui.tareas_turno_window import (
    COLUMNA_ESTADO, COLUMNA_HECHA, COLUMNA_HORA, COLUMNA_TAREA, FILTRO_TODAS, FILTRO_TODO_EL_DIA, TEXTO_HECHA,
    TITULO_SE_REPITE, VentanaTareasTurno,
)


class _ConLaVentana(_ConTareas):
    def setUp(self):
        super().setUp()
        # Martes 19:42, en la Tarde.
        self.reloj = [datetime(2026, 11, 3, 19, 42)]
        self.heladera_id = self._cargar(HELADERA, "09:00")
        self.luces_id = self._cargar(LUCES, "19:30")
        self.basura_id = self._cargar(BASURA, "20:00")
        self.persiana_id = self._cargar(PERSIANA, "21:50")
        self.cigarrillos_id = self._cargar(CIGARRILLOS, "02:00")
        # Solo los lunes: hoy no toca.
        self.diarios_id = self._cargar(DIARIOS, "12:00", dominio.TAREA_ALGUNOS_DIAS, [0])
        tareas_turno_repo.marcar_hecha(self.carla_id, self.heladera_id, "2026-11-03", ahora=datetime(2026, 11, 3, 9, 5))

    def _ventana(self, usuario=None):
        ventana = VentanaTareasTurno(usuario or self.carla, None, ahora=lambda: self.reloj[0])
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.close)
        return ventana

    @staticmethod
    def _columna(ventana, columna):
        return [ventana.tabla.item(fila, columna).text() for fila in range(ventana.tabla.rowCount())]

    @staticmethod
    def _numeros(ventana):
        return tuple(indicador.valor.text() for indicador in
                     (ventana.indicador_para_hacer, ventana.indicador_atrasadas, ventana.indicador_hechas))

    @staticmethod
    def _elegir(ventana, filtro):
        next(p for p in ventana.filtros.pastillas if p.text() == filtro).click()

    def _fila_de(self, ventana, texto):
        return self._columna(ventana, COLUMNA_TAREA).index(texto)


class TestLaLista(_ConLaVentana):
    def test_arranca_en_este_turno_con_su_estado_en_palabras(self):
        ventana = self._ventana()
        self.assertTrue(ventana.se_puede_cerrar_sola())
        self.assertEqual(ventana.cabecera.detalle.text(), "Tarde · martes 03/11")
        self.assertEqual(self._columna(ventana, COLUMNA_HORA), ["19:30", "20:00", "21:50"])
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO), ["ATRASADA · 12 min", "EN 18 MIN", "MÁS TARDE"])
        self.assertEqual(self._numeros(ventana), ("2", "1", "0"))
        self.assertTrue(ventana.indicador_atrasadas.property("alerta"))
        # Cada renglón que falta, con su tecla HECHA.
        for fila in range(3):
            self.assertEqual(ventana.tabla.cellWidget(fila, COLUMNA_HECHA).boton.text(), TEXTO_HECHA)

    def test_todo_el_dia_va_en_el_orden_del_turno_con_las_hechas_tachadas(self):
        ventana = self._ventana()
        self._elegir(ventana, FILTRO_TODO_EL_DIA)
        # La de las 02:00 es de la Noche del día: va al final.
        self.assertEqual(self._columna(ventana, COLUMNA_TAREA), [HELADERA, LUCES, BASURA, PERSIANA, CIGARRILLOS])
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "HECHA · Carla 09:05")
        self.assertTrue(ventana.tabla.item(0, COLUMNA_TAREA).font().strikeOut())
        self.assertFalse(ventana.tabla.item(1, COLUMNA_TAREA).font().strikeOut())
        self.assertIsNone(ventana.tabla.cellWidget(0, COLUMNA_HECHA))
        self.assertEqual(self._numeros(ventana), ("3", "1", "1"))

    def test_todas_las_tareas_muestra_cuando_se_repite_cada_una(self):
        ventana = self._ventana()
        self._elegir(ventana, FILTRO_TODAS)
        self.assertEqual(ventana.tabla.horizontalHeaderItem(COLUMNA_ESTADO).text(), TITULO_SE_REPITE)
        self.assertEqual(self._columna(ventana, COLUMNA_TAREA),
                         [HELADERA, DIARIOS, LUCES, BASURA, PERSIANA, CIGARRILLOS])
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[1], "Lun")
        self.assertTrue(all(ventana.tabla.cellWidget(fila, COLUMNA_HECHA) is None
                            for fila in range(ventana.tabla.rowCount())))
        # De vuelta a ESTE TURNO, el título de la columna vuelve a ser Estado.
        self._elegir(ventana, "ESTE TURNO")
        self.assertEqual(ventana.tabla.horizontalHeaderItem(COLUMNA_ESTADO).text(), "Estado")

    def test_es_la_hora_y_la_pospuesta_dicen_por_que_no_salta_el_aviso(self):
        tareas_turno_repo.posponer(self.carla_id, self.luces_id, "2026-11-03", 10, ahora=datetime(2026, 11, 3, 19, 37))
        ventana = self._ventana()
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "ATRASADA · 12 min · pospuesta hasta las 19:47")
        self.reloj[0] = datetime(2026, 11, 3, 20, 0, 30)
        ventana._cargar()
        # La posposición ya venció (el aviso vuelve a salir): no lo dice más.
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "ATRASADA · 30 min")
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[1], "ES LA HORA")

    def test_este_turno_trae_las_atrasadas_de_un_turno_anterior(self):
        # Una de la Mañana que nadie hizo sigue avisando en la Tarde, y el botón de la
        # barra la cuenta: tiene que estar donde la de la Tarde la viene a buscar.
        self._cargar("REPONER LA HELADERA", "13:30")
        self.reloj[0] = datetime(2026, 11, 3, 14, 10)
        ventana = self._ventana()
        self.assertEqual(ventana.cabecera.detalle.text(), "Tarde · martes 03/11")
        self.assertEqual(self._columna(ventana, COLUMNA_TAREA), ["REPONER LA HELADERA", LUCES, BASURA, PERSIANA])
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "ATRASADA · 40 min")
        self.assertEqual(self._numeros(ventana), ("3", "1", "0"))
        # La HECHA de la Mañana no: esa ya no hay que hacerla.
        self.assertNotIn(HELADERA, self._columna(ventana, COLUMNA_TAREA))
        self.assertEqual(ventana.indicador_atrasadas.valor.text(),
                         str(tareas_turno_repo.cuantas_atrasadas(self.reloj[0])))

    def test_se_pone_al_dia_sola_solo_con_la_ventana_a_la_vista(self):
        ventana = self._ventana()
        self.reloj[0] = datetime(2026, 11, 3, 20, 5)
        ventana._repasar()
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[1], "EN 18 MIN")
        ventana.show()
        ventana.tabla.selectRow(2)
        ventana._repasar()
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[1], "ATRASADA · 5 min")
        # Sin perder el renglón elegido.
        self.assertEqual(ventana._id_elegido(), self.persiana_id)


class TestHechaDesdeLaLista(_ConLaVentana):
    def test_hecha_pregunta_y_queda_a_nombre_de_quien_la_marco(self):
        ventana = self._ventana()
        ventana.tabla.cellWidget(0, COLUMNA_HECHA).boton.click()

        self.pregunta.assert_called_once()
        self.assertIn(LUCES, self.pregunta.call_args.args[2])
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "HECHA · Carla 19:42")
        self.assertIsNone(ventana.tabla.cellWidget(0, COLUMNA_HECHA))
        self.assertEqual(self._numeros(ventana), ("2", "0", "1"))
        self.assertFalse(ventana.indicador_atrasadas.property("alerta"))
        self.assertEqual(self._de_hoy(self.reloj[0])[LUCES]["hecha_por"], "Carla")

    def test_si_dice_que_no_no_la_marca(self):
        self.pregunta.return_value = False
        ventana = self._ventana()
        ventana.tabla.cellWidget(0, COLUMNA_HECHA).boton.click()
        self.assertEqual(self._de_hoy(self.reloj[0])[LUCES]["estado"], dominio.TAREA_ATRASADA)
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "ATRASADA · 12 min")

    def test_si_ya_la_habian_marcado_sale_el_cartel_y_la_lista_se_pone_al_dia(self):
        # La lista quedó vieja: alguien la marcó por otro lado. El repo la rechaza y,
        # aunque no se pudo, el renglón pasa a como quedó (sin la tecla).
        ventana = self._ventana()
        tareas_turno_repo.marcar_hecha(self.admin_id, self.luces_id, "2026-11-03", ahora=self.reloj[0])
        with mock.patch("ui.utils.mostrar_error") as cartel:
            ventana.tabla.cellWidget(0, COLUMNA_HECHA).boton.click()
        cartel.assert_called_once()
        self.assertIn("la marcó Sergio", cartel.call_args.args[2])
        self.assertEqual(self._columna(ventana, COLUMNA_ESTADO)[0], "HECHA · Sergio 19:42")
        self.assertIsNone(ventana.tabla.cellWidget(0, COLUMNA_HECHA))


class TestLoDelAdministrador(_ConLaVentana):
    def _guardar_con(self, texto=None, hora=None, repeticion=None, dias=None, revisar=None):
        """DialogoTarea.exec de mentira: escribe lo pedido y aprieta GUARDAR (o, con
        `revisar`, primero le pasa el diálogo para mirar cómo arrancó)."""
        def exec_(dialogo):
            if revisar is not None:
                revisar(dialogo)
            if texto is not None:
                dialogo.campo_tarea.setText(texto)
            if hora is not None:
                dialogo.campo_hora.setText(hora)
            if repeticion is not None:
                dialogo._pastillas_repeticion[repeticion].setChecked(True)
            for numero, pastilla in enumerate(dialogo._pastillas_dias):
                if dias is not None:
                    pastilla.setChecked(numero in dias)
            dialogo._guardar()
            return dialogo.result()
        return mock.patch.object(DialogoTarea, "exec", exec_)

    def _textos_de_las_teclas(self, ventana) -> set:
        return {boton.text() for boton in ventana.findChildren(QPushButton) if not boton.isHidden()}

    def test_a_una_empleada_las_teclas_del_admin_le_dicen_acceso_restringido(self):
        # Hasta el 2026-11-04 ni las veía; ahora las ve igual (pedido del dueño).
        ventana = self._ventana(self.carla)
        textos = self._textos_de_las_teclas(ventana)
        for boton in (ventana.boton_nueva, ventana.boton_modificar, ventana.boton_borrar):
            self.assertIn(boton.text(), textos)
            self.assertTrue(boton.property("restringido"))
        antes = tareas_turno_repo.listar_tareas(self.reloj[0])
        with mock.patch("ui.piezas_ventana.avisar_acceso_restringido") as aviso:
            ventana.boton_nueva.click()
        aviso.assert_called_once()
        self.assertEqual(tareas_turno_repo.listar_tareas(self.reloj[0]), antes)
        # HISTORIAL y CERRAR son para todos.
        self.assertIn("📋  HISTORIAL", textos)
        self.assertIn("CERRAR", textos)
        self.assertFalse(ventana.boton_historial.property("soloAdmin"))

    def test_el_admin_ve_sus_teclas_con_el_borde_punteado(self):
        ventana = self._ventana(self.admin)
        textos = self._textos_de_las_teclas(ventana)
        for boton in (ventana.boton_nueva, ventana.boton_modificar, ventana.boton_borrar):
            self.assertIn(boton.text(), textos)
            self.assertTrue(boton.property("soloAdmin"))

    def test_nueva_tarea_queda_elegida_y_si_no_es_de_este_turno_pasa_a_todas(self):
        ventana = self._ventana(self.admin)
        with self._guardar_con("REPONER LA HELADERA", "2015"):
            ventana.boton_nueva.click()
        self.assertEqual(ventana.filtros.elegido(), None)
        fila = self._fila_de(ventana, "REPONER LA HELADERA")
        self.assertEqual(ventana.tabla.item(fila, COLUMNA_HORA).text(), "20:15")
        self.assertEqual(ventana.tabla.currentRow(), fila)

        # Una de la Mañana no se ve en la Tarde: pasa a TODAS LAS TAREAS, marcada.
        with self._guardar_con("ABRIR LA PERSIANA", "7:05"):
            ventana.boton_nueva.click()
        self.assertEqual(ventana.filtros.elegido(), FILTRO_TODAS)
        self.assertEqual(ventana.tabla.currentRow(), self._fila_de(ventana, "ABRIR LA PERSIANA"))
        self.assertEqual(ventana._id_elegido(), tareas_turno_repo.listar_tareas(self.reloj[0])[0]["id"])

    def test_modificar_arranca_con_la_tarea_como_esta_cargada(self):
        ventana = self._ventana(self.admin)
        self._elegir(ventana, FILTRO_TODAS)
        ventana.tabla.selectRow(self._fila_de(ventana, DIARIOS))
        vio = {}

        def mirar(dialogo):
            vio.update(texto=dialogo.campo_tarea.text(), hora=dialogo.campo_hora.text(),
                       repeticion=dialogo.repeticion_elegida(), dias=dialogo.dias_elegidos(),
                       con_dias=not dialogo.fila_dias.isHidden())

        with self._guardar_con(hora="12:30", dias=[0, 4], revisar=mirar):
            ventana.boton_modificar.click()
        self.assertEqual(vio, {"texto": DIARIOS, "hora": "12:00", "repeticion": dominio.TAREA_ALGUNOS_DIAS,
                               "dias": [0], "con_dias": True})
        cargada = next(t for t in tareas_turno_repo.listar_tareas(self.reloj[0]) if t["id"] == self.diarios_id)
        self.assertEqual((cargada["hora"], cargada["dias_semana"]), ("12:30", (0, 4)))
        self.assertEqual(ventana._id_elegido(), self.diarios_id)
        self.assertEqual(ventana.tabla.item(ventana.tabla.currentRow(), COLUMNA_ESTADO).text(), "Lun · Vie")

    def test_modificar_desde_la_lista_del_dia_y_cancelar_no_cambia_nada(self):
        ventana = self._ventana(self.admin)
        ventana.tabla.selectRow(0)
        with mock.patch.object(DialogoTarea, "exec", return_value=QDialog.Rejected):
            ventana.boton_modificar.click()
        with self._guardar_con(hora="19:45"):
            ventana.boton_modificar.click()
        self.assertEqual(self._columna(ventana, COLUMNA_HORA)[0], "19:45")
        self.assertEqual(ventana._id_elegido(), self.luces_id)

    def test_modificar_y_borrar_sin_elegir_una_avisan(self):
        ventana = self._ventana(self.admin)
        with mock.patch("ui.tareas_turno_window.DialogoTarea") as dialogo:
            ventana.boton_modificar.click()
            ventana.boton_borrar.click()
        dialogo.assert_not_called()
        self.assertEqual([llamada.args[1] for llamada in self.avisos.call_args_list], ["Elegí una tarea"] * 2)
        self.pregunta.assert_not_called()

    def test_borrar_pregunta_y_la_saca_de_la_lista(self):
        ventana = self._ventana(self.admin)
        ventana.tabla.selectRow(self._fila_de(ventana, BASURA))
        self.pregunta.return_value = False
        ventana.boton_borrar.click()
        self.assertIn(BASURA, self._columna(ventana, COLUMNA_TAREA))

        self.pregunta.return_value = True
        ventana.boton_borrar.click()
        self.assertEqual(self.pregunta.call_count, 2)
        self.assertIn(BASURA, self.pregunta.call_args.args[2])
        self.assertEqual(self._columna(ventana, COLUMNA_TAREA), [LUCES, PERSIANA])
        self.assertNotIn(self.basura_id, [t["id"] for t in tareas_turno_repo.listar_tareas(self.reloj[0])])


class TestElDialogoDeLaTarea(_ConTareas):
    def _dialogo(self, ahora=datetime(2026, 11, 3, 19, 42)):
        dialogo = DialogoTarea(self.admin, None, None, lambda: ahora)
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_el_turno_sale_solo_de_la_hora(self):
        dialogo = self._dialogo()
        for hora, turno in (("1930", "Tarde  ·  a las 19:30"), ("7.05", "Mañana  ·  a las 07:05"),
                            ("02:00", "Noche  ·  a las 02:00"), ("abc", "—"), ("", "—")):
            dialogo.campo_hora.setText(hora)
            self.assertEqual(dialogo.etiqueta_turno.text(), turno, hora)

    def test_los_dias_se_ven_solo_con_elegir_dias_y_solo_hoy_dice_que_dia_es(self):
        dialogo = self._dialogo()
        self.assertEqual(dialogo.repeticion_elegida(), dominio.TAREA_TODOS_LOS_DIAS)
        self.assertTrue(dialogo.fila_dias.isHidden())
        self.assertEqual(len(dialogo._pastillas_dias), 7)

        dialogo._pastillas_repeticion[dominio.TAREA_ALGUNOS_DIAS].setChecked(True)
        self.assertFalse(dialogo.fila_dias.isHidden())
        dialogo._pastillas_repeticion[dominio.TAREA_UN_SOLO_DIA].setChecked(True)
        self.assertTrue(dialogo.fila_dias.isHidden())
        self.assertEqual(dialogo.aclaracion.text(), "Solo hoy, martes 03/11.")

        # A la madrugada, el día del local todavía es el que empezó ayer.
        madrugada = self._dialogo(datetime(2026, 11, 4, 2, 0))
        madrugada._pastillas_repeticion[dominio.TAREA_UN_SOLO_DIA].setChecked(True)
        self.assertIn("Solo hoy, martes 03/11", madrugada.aclaracion.text())
        self.assertIn("06:00", madrugada.aclaracion.text())

    def test_enter_en_la_hora_guarda_los_dias_elegidos(self):
        dialogo = self._dialogo()
        dialogo.show()
        self.addCleanup(dialogo.close)
        dialogo.campo_tarea.setText(DIARIOS)
        dialogo._pastillas_repeticion[dominio.TAREA_ALGUNOS_DIAS].setChecked(True)
        dialogo._pastillas_dias[0].setChecked(True)
        dialogo._pastillas_dias[4].setChecked(True)
        dialogo.campo_hora.setFocus()
        QTest.keyClicks(dialogo.campo_hora, "2100")
        QTest.keyClick(dialogo.campo_hora, Qt.Key_Return)

        self.assertEqual(dialogo.result(), QDialog.Accepted)
        cargada = tareas_turno_repo.listar_tareas(datetime(2026, 11, 3, 19, 42))[0]
        self.assertEqual(cargada["id"], dialogo.tarea_id)
        self.assertEqual((cargada["texto"], cargada["hora"], cargada["repeticion"], cargada["dias_semana"]),
                         (DIARIOS, "21:00", dominio.TAREA_ALGUNOS_DIAS, (0, 4)))

    def test_lo_que_rechaza_el_repo_sale_en_su_cartel_y_no_cierra(self):
        dialogo = self._dialogo()
        dialogo.campo_tarea.setText(LUCES)
        dialogo.campo_hora.setText("25:00")
        with mock.patch("ui.utils.mostrar_error") as cartel:
            dialogo._guardar()
        cartel.assert_called_once()
        self.assertNotEqual(dialogo.result(), QDialog.Accepted)
        self.assertIsNone(dialogo.tarea_id)
        self.assertEqual(tareas_turno_repo.listar_tareas(datetime(2026, 11, 3, 19, 42)), [])


class TestElHistorial(_ConTareas):
    def test_los_dias_anteriores_con_quien_la_hizo_y_quien_la_pospuso(self):
        luces_id = self._cargar(LUCES, "19:30", ahora=datetime(2026, 11, 1, 8, 0))
        tareas_turno_repo.posponer(self.carla_id, luces_id, "2026-11-02", 5, ahora=datetime(2026, 11, 2, 19, 31))
        tareas_turno_repo.marcar_hecha(self.carla_id, luces_id, "2026-11-02", ahora=datetime(2026, 11, 2, 19, 40))
        ahora = datetime(2026, 11, 3, 19, 42)
        ventana = VentanaTareasTurno(self.carla, None, ahora=lambda: ahora)
        self.addCleanup(ventana.deleteLater)
        abiertos = []

        def exec_(dialogo):
            abiertos.append(dialogo)
            return QDialog.Rejected

        with mock.patch.object(DialogoHistorialTareas, "exec", exec_):
            ventana.boton_historial.click()
        historial = abiertos[0]
        self.addCleanup(historial.deleteLater)
        self.assertTrue(historial.se_puede_cerrar_sola())
        # Hasta ayer: el día de hoy todavía no terminó.
        self.assertEqual(historial.fecha_hasta.date().toString("yyyy-MM-dd"), "2026-11-02")
        self.assertEqual(historial.fecha_desde.date().toString("yyyy-MM-dd"), "2026-10-27")
        filas = [[historial.tabla.item(fila, columna).text() for columna in range(5)]
                 for fila in range(historial.tabla.rowCount())]
        self.assertEqual(filas, [
            ["lunes 02/11", "19:30", LUCES, "HECHA · Carla 19:40", "1 vez (Carla, 19:31)"],
            ["domingo 01/11", "19:30", LUCES, dominio.TAREA_NO_SE_HIZO, "—"],
        ])
        self.assertIn("(5 min)", historial.tabla.item(0, 4).toolTip())
        self.assertEqual((historial.indicador_hechas.valor.text(), historial.indicador_no_se_hicieron.valor.text()),
                         ("1", "1"))
        self.assertTrue(historial.indicador_no_se_hicieron.property("alerta"))

    def test_dice_si_despues_la_borraron(self):
        # Hecha el lunes y borrada esa misma noche (antes de las 06:00 del martes).
        luces_id = self._cargar(LUCES, "19:30", ahora=datetime(2026, 11, 2, 8, 0))
        tareas_turno_repo.marcar_hecha(self.carla_id, luces_id, "2026-11-02", ahora=datetime(2026, 11, 2, 19, 40))
        tareas_turno_repo.borrar_tarea(self.admin_id, luces_id, ahora=datetime(2026, 11, 2, 20, 0))
        historial = DialogoHistorialTareas(None, lambda: datetime(2026, 11, 3, 19, 42))
        self.addCleanup(historial.deleteLater)
        self.assertEqual(historial.tabla.rowCount(), 1)
        self.assertEqual(historial.tabla.item(0, 2).text(), f"{LUCES}  (después la borraron)")
        self.assertEqual(historial.tabla.item(0, 3).text(), "HECHA · Carla 19:40")

    def test_con_mas_de_tres_posposiciones_nombra_las_ultimas(self):
        posposiciones = [{"nombre": nombre, "fecha": f"2026-11-03T{hora}:00"}
                         for nombre, hora in (("Carla", "19:30"), ("Gaby", "19:35"), ("Carla", "19:40"),
                                              ("Gaby", "19:50"))]
        self.assertEqual(texto_de_lo_pospuesto(posposiciones), "4 veces (… Gaby, 19:35 · Carla, 19:40 · Gaby, 19:50)")
        self.assertEqual(texto_de_lo_pospuesto(posposiciones[:3]), "3 veces (Carla, 19:30 · Gaby, 19:35 · Carla, 19:40)")
        self.assertEqual(texto_de_lo_pospuesto(posposiciones[:1]), "1 vez (Carla, 19:30)")
        self.assertEqual(texto_de_lo_pospuesto([]), "")


if __name__ == "__main__":
    unittest.main()
