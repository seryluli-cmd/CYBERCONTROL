"""
tests/test_playstation_ui.py
==============================
La PlayStation 5 en pantalla (se prueba sin abrir ninguna ventana, plataforma
"offscreen" de Qt): que el panel lateral habilite SOLO la lista de bonos del
equipo elegido (nunca se puede aplicar un bono al equivocado), que la consola
sea la primera fila de la grilla con su nombre fijo, que la cuenta regresiva
corra y que al llegar a cero la fila titile en rojo. La lógica de fondo (permisos,
ventas, tiempo) está en tests/test_playstation.py.

Se ejecutan con:

    python -m unittest discover tests
"""

import contextlib
import os
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from repositories import usuarios_repo, ventas_repo  # noqa: E402
from control_pcs.repositories import pcs_repo, playstation_repo  # noqa: E402
from control_pcs.ui import pcs_window  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


@contextlib.contextmanager
def _reloj_de_la_pantalla(momento):
    """Dentro del bloque, todo lo que mira la hora (la consola, las PCs y la
    grilla) cree que ahora es `momento`."""
    parches = [
        mock.patch("control_pcs.repositories.playstation_repo.datetime"),
        mock.patch("control_pcs.repositories.pcs_repo.datetime"),
        mock.patch("control_pcs.ui.pcs_window.datetime"),
    ]
    with contextlib.ExitStack() as pila:
        for parche in parches:
            datetime_mock = pila.enter_context(parche)
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
        yield


class _ConPantalla(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.operadora_id = usuarios_repo.crear_usuario(
            "Operadora", "1234", dominio.ROL_EMPLEADA, {playstation_repo.PERMISO_OPERAR: True}
        )
        self.empleada_id = usuarios_repo.crear_usuario("Empleada", "1234", dominio.ROL_EMPLEADA)
        self.estacion_id = pcs_repo.crear_estacion("PC 1")
        self.bono_pc_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        self.bono_pc_2_id = pcs_repo.crear_bono("5 horas", 300, 12000)
        self.bono_ps_id = playstation_repo.crear_bono(self.admin_id, "1 hora PS5", 60, 3000)
        self.bono_ps_2_id = playstation_repo.crear_bono(self.admin_id, "2 horas PS5", 120, 5000)

        # Un cartel de error o de confirmación abierto de verdad dejaría la prueba
        # colgada esperando que alguien lo cierre: se registran en vez de mostrarse.
        self.errores = []
        patch_error = mock.patch("ui.utils.mostrar_error", side_effect=lambda *a, **k: self.errores.append(a[2]))
        patch_error.start()
        self.addCleanup(patch_error.stop)

    def _usuario(self, usuario_id):
        return usuarios_repo.obtener_usuario(usuario_id)

    def _panel(self, usuario_id):
        panel = PanelDetalleEstacion(self._usuario(usuario_id), lambda: None)
        self.addCleanup(panel.deleteLater)
        return panel

    def _grilla(self, usuario_id=None):
        grilla = PanelControlPcs(self._usuario(usuario_id or self.operadora_id))
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def _item_pc(self):
        return next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.estacion_id)

    @staticmethod
    def _habilitados(lista):
        return [boton.isEnabled() for boton in lista.grupo.buttons()]


class TestPanelDeBonosPorEquipo(_ConPantalla):
    """Mientras esté elegida la consola los bonos de PC están deshabilitados, y al
    revés: nunca se puede aplicar un bono al dispositivo equivocado."""

    def test_sin_nada_elegido_no_se_puede_tocar_ningun_bono(self):
        panel = self._panel(self.operadora_id)

        panel.mostrar(None)

        self.assertEqual(len(panel.lista_pc.grupo.buttons()), 2)
        self.assertEqual(len(panel.lista_playstation.grupo.buttons()), 2)
        self.assertFalse(any(self._habilitados(panel.lista_pc)))
        self.assertFalse(any(self._habilitados(panel.lista_playstation)))
        self.assertFalse(panel.boton_iniciar.isEnabled())

    def test_con_una_pc_elegida_solo_se_pueden_tocar_los_bonos_de_pc(self):
        panel = self._panel(self.operadora_id)

        panel.mostrar(self._item_pc())

        self.assertTrue(all(self._habilitados(panel.lista_pc)))
        self.assertFalse(any(self._habilitados(panel.lista_playstation)))
        self.assertTrue(panel.boton_iniciar.isEnabled())
        self.assertTrue(panel.boton_miembro.isEnabled())

    def test_con_la_consola_elegida_solo_se_pueden_tocar_los_bonos_de_la_consola(self):
        panel = self._panel(self.operadora_id)

        panel.mostrar(playstation_repo.estado())

        self.assertFalse(any(self._habilitados(panel.lista_pc)))
        self.assertTrue(all(self._habilitados(panel.lista_playstation)))
        self.assertTrue(panel.boton_iniciar.isEnabled())
        # Abrir con el saldo de un socio es solo de las PCs.
        self.assertFalse(panel.boton_miembro.isEnabled())
        self.assertEqual(panel.etiqueta_titulo.text(), "PLAYSTATION 5")

    def test_los_bonos_de_la_consola_van_debajo_de_los_de_pc(self):
        panel = self._panel(self.operadora_id)
        panel.show()
        self.addCleanup(panel.hide)
        _app.processEvents()

        y_pc = panel.lista_pc.etiqueta.mapTo(panel, panel.lista_pc.etiqueta.rect().topLeft()).y()
        y_consola = panel.lista_playstation.etiqueta.mapTo(
            panel, panel.lista_playstation.etiqueta.rect().topLeft()
        ).y()

        self.assertLess(y_pc, y_consola)
        self.assertEqual(panel.lista_pc.etiqueta.text(), "Bonos de PC:")
        self.assertEqual(panel.lista_playstation.etiqueta.text(), "Bonos de PlayStation 5:")

    def test_sin_el_permiso_operativo_la_consola_se_ve_pero_no_se_opera(self):
        panel = self._panel(self.empleada_id)

        panel.mostrar(playstation_repo.estado())

        self.assertFalse(any(self._habilitados(panel.lista_playstation)))
        self.assertFalse(any(self._habilitados(panel.lista_pc)))
        self.assertFalse(panel.boton_iniciar.isEnabled())
        self.assertFalse(panel.boton_finalizar.isEnabled())
        self.assertIn("Sin permiso", panel.etiqueta_estado.text())

    def test_el_admin_opera_la_consola(self):
        panel = self._panel(self.admin_id)

        panel.mostrar(playstation_repo.estado())

        self.assertTrue(all(self._habilitados(panel.lista_playstation)))
        self.assertTrue(panel.boton_iniciar.isEnabled())

    def test_aunque_se_fuerce_el_boton_sin_permiso_el_repo_lo_frena(self):
        panel = self._panel(self.empleada_id)
        panel.mostrar(playstation_repo.estado())

        with mock.patch("control_pcs.ui.pcs_detalle.resolver_pagos", return_value=_efectivo(3000.0)):
            panel._confirmar_bono()  # lo que haría el clic si el botón no estuviera apagado

        self.assertEqual(ventas_repo.listar_ventas_recientes(), [])
        self.assertEqual(len(self.errores), 1)
        self.assertIn("permiso", self.errores[0])


class TestCobrarDesdeElPanel(_ConPantalla):
    def _cobrar(self, panel):
        with mock.patch("control_pcs.ui.pcs_detalle.resolver_pagos") as resolver:
            resolver.side_effect = lambda ventana, metodo, monto: _efectivo(monto)
            panel._confirmar_bono()

    def test_con_la_consola_elegida_se_cobra_el_bono_de_la_consola(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(playstation_repo.estado())

        self._cobrar(panel)

        venta = ventas_repo.listar_ventas_recientes()[0]
        self.assertEqual((venta["origen"], venta["total"]), (dominio.ORIGEN_PLAYSTATION, 3000.0))
        self.assertIsNotNone(playstation_repo.estado()["sesion"])
        self.assertIsNone(self._item_pc()["sesion"])  # ninguna PC recibió nada
        self.assertEqual(self.errores, [])

    def test_con_una_pc_elegida_se_cobra_el_bono_de_pc(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(self._item_pc())

        self._cobrar(panel)

        venta = ventas_repo.listar_ventas_recientes()[0]
        self.assertEqual((venta["origen"], venta["total"]), (dominio.ORIGEN_ALQUILER_PCS, 9000.0))
        self.assertIsNotNone(self._item_pc()["sesion"])
        self.assertIsNone(playstation_repo.estado()["sesion"])  # la consola no recibió nada

    def test_se_cobra_el_bono_tildado_en_la_lista_del_equipo_elegido(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(playstation_repo.estado())
        panel.lista_playstation.grupo.button(self.bono_ps_2_id).click()  # "2 horas PS5", $5.000

        self._cobrar(panel)

        self.assertEqual(ventas_repo.listar_ventas_recientes()[0]["total"], 5000.0)

    def test_el_bono_tildado_se_conserva_cuando_la_grilla_se_refresca(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(self._item_pc())
        panel.lista_pc.grupo.button(self.bono_pc_2_id).click()

        panel.mostrar(self._item_pc())  # la grilla se refresca sola cada 5 segundos

        self.assertEqual(panel.lista_pc.bono_elegido()["id"], self.bono_pc_2_id)

    def test_si_el_bono_elegido_ya_no_existe_se_vuelve_al_primero(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(self._item_pc())
        panel.lista_pc.grupo.button(self.bono_pc_2_id).click()
        pcs_repo.desactivar_bono(self.bono_pc_2_id)

        panel.mostrar(self._item_pc())

        self.assertEqual(panel.lista_pc.bono_elegido()["id"], self.bono_pc_id)

    def test_cada_lista_recuerda_su_propio_bono(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(self._item_pc())
        panel.lista_pc.grupo.button(self.bono_pc_2_id).click()
        panel.mostrar(playstation_repo.estado())
        panel.lista_playstation.grupo.button(self.bono_ps_2_id).click()

        panel.mostrar(self._item_pc())

        self.assertEqual(panel.lista_pc.bono_elegido()["id"], self.bono_pc_2_id)
        self.assertEqual(panel.lista_playstation.bono_elegido()["id"], self.bono_ps_2_id)

    def test_liberar_la_consola_desde_el_panel(self):
        panel = self._panel(self.operadora_id)
        panel.mostrar(playstation_repo.estado())
        self._cobrar(panel)
        panel.mostrar(playstation_repo.estado())
        self.assertTrue(panel.boton_finalizar.isEnabled())

        with mock.patch("control_pcs.ui.pcs_detalle.confirmar", return_value=True):
            panel._finalizar_sesion()

        self.assertIsNone(playstation_repo.estado()["sesion"])

    def test_cuando_se_acaba_el_tiempo_el_panel_pide_avisar_y_liberar(self):
        panel = self._panel(self.operadora_id)
        with _reloj_de_la_pantalla(datetime(2026, 1, 5, 10, 0, 0)):
            playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))
        with _reloj_de_la_pantalla(datetime(2026, 1, 5, 11, 30, 0)):  # media hora después de vencer
            panel.mostrar(playstation_repo.estado())

        self.assertIn("Se acabó el tiempo", panel.etiqueta_estado.text())
        self.assertIn("liberar", panel.boton_finalizar.text())


class TestGrillaConLaPlaystation(_ConPantalla):
    def _vencida(self):
        """Una sesión de la consola que se acabó hace mucho (ya pasó en el reloj real)."""
        with _reloj_de_la_pantalla(datetime(2026, 1, 5, 10, 0, 0)):
            playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))

    def _nombres(self, grilla):
        return [grilla.tabla.item(fila, 0).text() for fila in range(grilla.tabla.rowCount())]

    def test_la_consola_es_la_primera_fila_con_su_nombre_fijo_y_las_pcs_van_despues(self):
        pcs_repo.crear_estacion("PC 2")

        grilla = self._grilla()

        self.assertEqual(self._nombres(grilla), ["PLAYSTATION 5", "PC 1", "PC 2"])
        self.assertEqual(grilla.tabla.item(0, 1).text(), "✓ Disponible")

    def test_elegir_la_consola_o_una_pc_cambia_el_panel(self):
        grilla = self._grilla()

        grilla.tabla.selectRow(0)
        self.assertEqual(grilla.panel_detalle.etiqueta_titulo.text(), "PLAYSTATION 5")
        self.assertTrue(all(self._habilitados(grilla.panel_detalle.lista_playstation)))

        grilla.tabla.selectRow(1)
        self.assertEqual(grilla.panel_detalle.etiqueta_titulo.text(), "PC 1")
        self.assertTrue(all(self._habilitados(grilla.panel_detalle.lista_pc)))
        self.assertFalse(any(self._habilitados(grilla.panel_detalle.lista_playstation)))

    def test_la_seleccion_se_mantiene_cuando_la_grilla_se_refresca(self):
        grilla = self._grilla()
        grilla.tabla.selectRow(0)

        grilla._refrescar()

        self.assertEqual(grilla.tabla.currentRow(), 0)
        self.assertEqual(grilla.panel_detalle.etiqueta_titulo.text(), "PLAYSTATION 5")

    def test_la_consola_en_uso_muestra_la_cuenta_regresiva(self):
        ahora = datetime.now().replace(microsecond=0)
        with _reloj_de_la_pantalla(ahora):
            playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))

        grilla = self._grilla()

        self.assertEqual(grilla.tabla.item(0, 1).text(), "▶ En uso")
        # Recién vendida (con el reloj real): 1 hora justa, o apenas menos.
        self.assertRegex(grilla.tabla.item(0, pcs_window.COLUMNA_TIEMPO_RESTANTE).text(), r"^(59m \d\ds|1h 00m 00s)$")
        self.assertEqual(grilla._filas_en_alerta, [])

    def test_la_cuenta_regresiva_se_redibuja_cada_segundo_sin_reconstruir_la_grilla(self):
        ahora = datetime.now().replace(microsecond=0)
        with _reloj_de_la_pantalla(ahora):
            playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))
        grilla = self._grilla()
        celda = grilla.tabla.item(0, pcs_window.COLUMNA_TIEMPO_RESTANTE)

        with _reloj_de_la_pantalla(ahora + timedelta(minutes=30, seconds=15)):
            grilla._actualizar_cuenta_regresiva()
        self.assertEqual(celda.text(), "29m 45s")
        with _reloj_de_la_pantalla(ahora + timedelta(minutes=30, seconds=16)):
            grilla._actualizar_cuenta_regresiva()
        self.assertEqual(celda.text(), "29m 44s")

        # Es la MISMA celda: no se reconstruyó la tabla ni se perdió la selección.
        self.assertIs(grilla.tabla.item(0, pcs_window.COLUMNA_TIEMPO_RESTANTE), celda)

    def test_al_llegar_a_cero_la_fila_empieza_a_titilar_en_rojo(self):
        ahora = datetime.now().replace(microsecond=0)
        with _reloj_de_la_pantalla(ahora):
            playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))
        grilla = self._grilla()
        self.assertEqual(grilla._filas_en_alerta, [])

        with _reloj_de_la_pantalla(ahora + timedelta(minutes=60)):
            grilla._actualizar_cuenta_regresiva()  # el segundo en que llega a cero

        self.assertEqual(grilla._filas_en_alerta, [0])
        self.assertIn("TIEMPO AGOTADO", grilla.tabla.item(0, 1).text())
        self.assertEqual(grilla.tabla.item(0, pcs_window.COLUMNA_TIEMPO_RESTANTE).text(), "0m 00s")
        rojo = pcs_window.COLOR_ALERTA_SESION_SIN_CLIENTE
        blanco = pcs_window.COLOR_ALERTA_SESION_SIN_CLIENTE_APAGADA
        colores = []
        for _ in range(4):
            colores.append(grilla.tabla.item(0, 0).background().color())
            grilla._alternar_parpadeo()
        # Titila: alterna entre el rojo y el blanco, y sigue haciéndolo.
        self.assertEqual({c.name() for c in colores}, {rojo.name(), blanco.name()})
        self.assertNotEqual(colores[0], colores[1])
        self.assertEqual(colores[0], colores[2])

    def test_el_aviso_sigue_cuando_se_cierra_y_se_vuelve_a_abrir_el_programa(self):
        self._vencida()

        grilla = self._grilla()  # el programa "arranca de nuevo" con la sesión ya vencida

        self.assertEqual(grilla._filas_en_alerta, [0])
        self.assertIn("TIEMPO AGOTADO", grilla.tabla.item(0, 1).text())

    def test_una_pc_vencida_se_libera_sola_pero_la_consola_no(self):
        # La PC también se acabó, pero se da de baja en el refresco; la consola
        # queda avisando hasta que el operador la libere.
        self._vencida()
        with mock.patch("control_pcs.repositories.pcs_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = datetime(2026, 1, 5, 10, 0, 0)
            datetime_mock.fromisoformat = datetime.fromisoformat
            pcs_repo.asignar_bono(self.estacion_id, self.bono_pc_id, self.operadora_id, _efectivo(9000.0))

        grilla = self._grilla()

        self.assertIsNone(self._item_pc()["sesion"])               # la PC se liberó sola
        self.assertIsNotNone(playstation_repo.estado()["sesion"])  # la consola no
        self.assertIn(0, grilla._filas_en_alerta)

    def test_liberar_o_vender_otro_bono_apaga_el_aviso(self):
        self._vencida()
        grilla = self._grilla()
        self.assertEqual(grilla._filas_en_alerta, [0])

        playstation_repo.finalizar_sesion(self.operadora_id)
        grilla._refrescar()

        self.assertEqual(grilla._filas_en_alerta, [])
        self.assertEqual(grilla.tabla.item(0, 1).text(), "✓ Disponible")

        # Y vendiendo otro bono con el tiempo agotado (sin liberar) también se apaga.
        self._vencida()
        grilla._refrescar()
        self.assertEqual(grilla._filas_en_alerta, [0])
        playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))
        grilla._refrescar()
        self.assertEqual(grilla._filas_en_alerta, [])

    def test_los_timers_se_frenan_al_cerrar(self):
        grilla = self._grilla()
        self.assertTrue(grilla._timer_cuenta_regresiva.isActive())

        grilla.detener_actualizacion()

        self.assertFalse(grilla._timer_cuenta_regresiva.isActive())
        self.assertFalse(grilla._timer.isActive())
        self.assertFalse(grilla._timer_parpadeo.isActive())


class TestPantallasDeLaPlata(_ConPantalla):
    """Caja, Cierre de Turno, Consulta de Ventas y Reportes muestran la consola
    como un negocio más (si no, el dueño no la vería al auditar la caja)."""

    def setUp(self):
        super().setUp()
        playstation_repo.vender_bono(self.operadora_id, self.bono_ps_id, _efectivo(3000.0))

    def _abrir(self, ventana):
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_caja_y_cierre_de_turno_muestran_lo_cobrado_por_la_consola(self):
        from ui.caja_window import CajaWindow, CierreTurnoWindow

        caja = self._abrir(CajaWindow())
        cierre = self._abrir(CierreTurnoWindow(self._usuario(self.operadora_id)))

        self.assertIn("$ 3.000,00 ef.", caja.valor_playstation.text())
        self.assertIn("$ 3.000,00 ef.", cierre.valor_playstation.text())
        # Y lo suma al efectivo del cajón, que es lo que se retira.
        self.assertEqual(caja.valor_ventas.text(), "$ 3.000,00")
        self.assertEqual(cierre.valor_retirar.text(), "$ 3.000,00")

    def test_control_de_cierres_trae_una_columna_para_la_consola(self):
        from repositories import turnos_repo
        from ui.caja_window import ControlCierresWindow

        turnos_repo.cerrar_turno(self.operadora_id)
        ventana = self._abrir(ControlCierresWindow(self._usuario(self.admin_id)))

        titulos = [ventana.tabla.horizontalHeaderItem(c).text() for c in range(ventana.tabla.columnCount())]
        columna = titulos.index("PlayStation 5")
        self.assertEqual(ventana.tabla.item(0, columna).text(), "$ 3.000,00")

    def test_consulta_de_ventas_distingue_el_origen_de_cada_venta(self):
        from ui.consulta_ventas_window import ConsultaVentasWindow

        pcs_repo.asignar_bono(self.estacion_id, self.bono_pc_id, self.operadora_id, _efectivo(9000.0))
        ventana = self._abrir(ConsultaVentasWindow(self._usuario(self.admin_id)))

        columna = [ventana.tabla.horizontalHeaderItem(c).text() for c in range(ventana.tabla.columnCount())].index("Origen")
        origenes = [ventana.tabla.item(fila, columna).text() for fila in range(ventana.tabla.rowCount())]
        self.assertEqual(sorted(origenes), ["Alquiler de PCs", "PlayStation 5"])

    def test_los_reportes_traen_la_columna_de_la_consola(self):
        from ui.reportes_window import PestañaKioskoVsPCs, PestañaResumenDelDia

        totales = self._abrir(PestañaKioskoVsPCs())
        dia = self._abrir(PestañaResumenDelDia())

        titulos = [totales.tabla.horizontalHeaderItem(c).text() for c in range(totales.tabla.columnCount())]
        self.assertEqual(titulos, ["Período", "Kiosko", "Impresiones", "Trámites", "Alquiler de PCs",
                                   "PlayStation 5", "Total"])
        self.assertEqual(totales.tabla.item(0, titulos.index("PlayStation 5")).text(), "$ 3.000,00")
        self.assertIn("PlayStation 5", dia._COLUMNAS)
        # Cada fila del Resumen del Día tiene un valor por cada columna.
        self.assertEqual(dia.tabla.columnCount(), len(dia._COLUMNAS))
        self.assertTrue(all(dia.tabla.item(0, c) is not None for c in range(dia.tabla.columnCount())))


class TestPantallasDeAdmin(_ConPantalla):
    def test_la_pantalla_de_bonos_de_la_consola_la_maneja_el_admin_y_no_la_operadora(self):
        from control_pcs.ui.pcs_gestion_dialogos import DialogoGestionBonosPlaystation

        dialogo_admin = DialogoGestionBonosPlaystation(self._usuario(self.admin_id))
        self.addCleanup(dialogo_admin.deleteLater)
        self.assertEqual(dialogo_admin.tabla.rowCount(), 2)
        dialogo_admin.repo.crear_bono("30 minutos", 30, 1800)
        self.assertEqual(len(playstation_repo.listar_bonos()), 3)

        dialogo_operadora = DialogoGestionBonosPlaystation(self._usuario(self.operadora_id))
        self.addCleanup(dialogo_operadora.deleteLater)
        with self.assertRaises(PermissionError):
            dialogo_operadora.repo.crear_bono("45 minutos", 45, 2000)
        self.assertEqual(len(playstation_repo.listar_bonos()), 3)

    def test_los_formularios_de_bonos_de_pc_y_de_socios_siguen_con_su_repo(self):
        from control_pcs.ui.pcs_gestion_dialogos import DialogoGestionBonos
        from control_pcs.ui.miembros_window import DialogoGestionBonosMiembro

        dialogo_pc = DialogoGestionBonos()
        dialogo_socios = DialogoGestionBonosMiembro()
        for dialogo in (dialogo_pc, dialogo_socios):
            self.addCleanup(dialogo.deleteLater)

        self.assertIs(dialogo_pc.repo, pcs_repo)
        self.assertEqual(dialogo_pc.tabla.rowCount(), 2)
        self.assertEqual(dialogo_socios.tabla.rowCount(), 0)
        formulario = dialogo_pc.CLASE_FORMULARIO(dialogo_pc, repo=dialogo_pc.repo)
        self.addCleanup(formulario.deleteLater)
        self.assertIs(formulario.repo, pcs_repo)


if __name__ == "__main__":
    unittest.main()
