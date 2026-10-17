"""
tests/test_pcstream.py
========================
PCSTREAM, la PC de streaming (control_pcs/repositories/pcstream_repo.py): una PC
más, con su Cliente PC y su bloqueo, pero con su propio catálogo de bonos. Se
prueba que se la reconozca por el nombre, que se le cobren SUS bonos (y nunca
los comunes, ni los suyos a otra PC), que los socios no la puedan abrir, que no
entre en "Intercambiar de máquina", que vaya al lado de la PlayStation 5 en el
mosaico y que Reportes muestre cuánto se usó, en tiempo y en plata. La pantalla
se prueba sin abrir ninguna ventana (plataforma "offscreen" de Qt).

Se ejecutan con:

    python -m unittest discover tests
"""

import contextlib
import os
import unittest
from datetime import date, datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from repositories import reportes_repo, usuarios_repo, ventas_repo  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    actividad_repo, miembros_repo, pcs_repo, pcstream_repo, playstation_repo,
)
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_gestion_dialogos import DialogoGestionBonosPcstream  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from ui.reportes_pcstream import PestañaPcstream  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


@contextlib.contextmanager
def _reloj(momento):
    """Dentro del bloque, las PCs (y el reporte de PCSTREAM) creen que ahora es `momento`."""
    parches = [
        mock.patch("control_pcs.repositories.pcs_repo.datetime"),
        mock.patch("control_pcs.repositories.pcstream_repo.datetime"),
        mock.patch("control_pcs.repositories.miembros_repo.datetime"),
    ]
    with contextlib.ExitStack() as pila:
        for parche in parches:
            datetime_mock = pila.enter_context(parche)
            datetime_mock.now.return_value = momento
            datetime_mock.fromisoformat = datetime.fromisoformat
        yield


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _contar(tabla):
    with database.conexion_db() as conexion:
        return conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]


class _ConPcstream(BaseConBaseTemporal):
    """Una PC común ("PC 1") y PCSTREAM, cada una con su catálogo: el bono común
    y el primero de PCSTREAM tienen el MISMO id (1) a propósito, para probar que
    cada PC lee solo su catálogo."""

    def setUp(self):
        super().setUp()
        self.usuario_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.pc_id = pcs_repo.crear_estacion("PC 1")
        self.pcstream_id = pcs_repo.crear_estacion("PCSTREAM")
        self.bono_pc_id = pcs_repo.crear_bono("3 horas", 180, 9000)
        self.bono_stream_id = pcstream_repo.crear_bono("2 horas stream", 120, 15000)
        self.bono_stream_corto_id = pcstream_repo.crear_bono("1 hora stream", 60, 8000)
        self.assertEqual(self.bono_pc_id, self.bono_stream_id)

    def _vender(self, estacion_id, bono_id, momento, monto=None):
        with _reloj(momento):
            return pcs_repo.asignar_bono(estacion_id, bono_id, self.usuario_id, _efectivo(monto or 99999))

    def _finalizar(self, estacion_id, momento):
        with _reloj(momento):
            sesion = pcs_repo.estado_de_estacion(
                pcs_repo.obtener_estacion(estacion_id)["nombre"]
            )["sesion"]
            pcs_repo.finalizar_sesion(sesion["id"])

    def _item(self, estacion_id):
        return next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == estacion_id)


class TestReconocerPcstream(unittest.TestCase):
    def test_se_reconoce_por_el_nombre_sin_importar_espacios_guiones_ni_mayusculas(self):
        for nombre in ("PCSTREAM", "PC STREAM", "pc-stream", " PcStream ", "PC_STREAM"):
            self.assertTrue(dominio.es_pcstream(nombre), nombre)

    def test_otro_nombre_es_una_pc_comun(self):
        for nombre in ("PC 1", "PCSTREAM2", "STREAM", "", None):
            self.assertFalse(dominio.es_pcstream(nombre), nombre)


class TestVenderAPcstream(_ConPcstream):
    def test_a_pcstream_se_le_cobra_su_bono_aunque_el_id_coincida_con_uno_comun(self):
        venta_id = self._vender(self.pcstream_id, self.bono_stream_id, datetime(2026, 1, 5, 10, 0))

        venta = ventas_repo.listar_ventas_recientes()[0]
        self.assertEqual(venta["id"], venta_id)
        self.assertEqual(venta["total"], 15000.0)
        self.assertEqual(venta["origen"], dominio.ORIGEN_ALQUILER_PCS)
        self.assertEqual((_contar("sesion_pcstream_bonos"), _contar("sesion_bonos")), (1, 0))

    def test_a_una_pc_comun_se_le_cobra_el_bono_comun(self):
        self._vender(self.pc_id, self.bono_pc_id, datetime(2026, 1, 5, 10, 0))

        self.assertEqual(ventas_repo.listar_ventas_recientes()[0]["total"], 9000.0)
        self.assertEqual((_contar("sesion_pcstream_bonos"), _contar("sesion_bonos")), (0, 1))

    def test_un_bono_que_solo_existe_en_pcstream_no_se_le_vende_a_otra_pc(self):
        with self.assertRaisesRegex(ValueError, "ya no está disponible"):
            self._vender(self.pc_id, self.bono_stream_corto_id, datetime(2026, 1, 5, 10, 0))

        self.assertEqual((_contar("ventas"), _contar("sesiones_pc")), (0, 0))

    def test_un_bono_de_pcstream_dado_de_baja_no_se_vende(self):
        pcstream_repo.desactivar_bono(self.bono_stream_corto_id)

        with self.assertRaisesRegex(ValueError, "ya no está disponible"):
            self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 5, 10, 0))

    def test_pcstream_se_bloquea_y_desbloquea_como_cualquier_pc(self):
        # El Cliente PC de PCSTREAM pregunta su estado igual que el de las demás.
        with _reloj(datetime(2026, 1, 5, 10, 0)):
            self.assertIsNone(pcs_repo.estado_de_estacion("PCSTREAM")["sesion"])
        self._vender(self.pcstream_id, self.bono_stream_id, datetime(2026, 1, 5, 10, 0))
        with _reloj(datetime(2026, 1, 5, 11, 0)):
            item = pcs_repo.estado_de_estacion("PCSTREAM")
        self.assertIsNotNone(item["sesion"])
        self.assertEqual(item["segundos_restantes"], 3600)
        self.assertTrue(item["es_pcstream"])

    def test_agregar_otro_bono_de_pcstream_extiende_la_misma_sesion(self):
        self._vender(self.pcstream_id, self.bono_stream_id, datetime(2026, 1, 5, 10, 0))
        self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 5, 10, 30))

        with _reloj(datetime(2026, 1, 5, 10, 30)):
            item = pcs_repo.estado_de_estacion("PCSTREAM")
        self.assertEqual(item["segundos_restantes"], (90 + 60) * 60)
        self.assertEqual(_contar("sesiones_pc"), 1)


class TestPcstreamSinSociosNiTraslados(_ConPcstream):
    def _socio_con_saldo(self, minutos):
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, miembro_id))
        return miembro_id

    def test_un_socio_no_puede_abrir_pcstream_con_su_saldo(self):
        miembro_id = self._socio_con_saldo(120)

        with _reloj(datetime(2026, 1, 5, 10, 0)), self.assertRaisesRegex(ValueError, "saldo de socio"):
            miembros_repo.abrir_estacion_por_miembro(self.pcstream_id, "juan", "clave123")

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 120)
        self.assertEqual(_contar("sesiones_pc"), 0)

    def test_un_socio_si_puede_abrir_una_pc_comun(self):
        self._socio_con_saldo(120)

        with _reloj(datetime(2026, 1, 5, 10, 0)):
            miembros_repo.abrir_estacion_por_miembro(self.pc_id, "juan", "clave123")

        self.assertEqual(_contar("sesiones_pc"), 1)

    def test_no_se_le_puede_pasar_a_pcstream_la_sesion_de_otra_pc(self):
        self._vender(self.pc_id, self.bono_pc_id, datetime(2026, 1, 5, 10, 0))

        with _reloj(datetime(2026, 1, 5, 10, 5)), self.assertRaisesRegex(ValueError, "PCSTREAM"):
            pcs_repo.trasladar_sesion(self.pc_id, self.pcstream_id, self.usuario_id)

        self.assertIsNotNone(self._item(self.pc_id)["sesion"])
        self.assertIsNone(self._item(self.pcstream_id)["sesion"])
        self.assertEqual(_contar("traslados_sesion"), 0)

    def test_no_se_puede_pasar_la_sesion_de_pcstream_a_otra_pc(self):
        self._vender(self.pcstream_id, self.bono_stream_id, datetime(2026, 1, 5, 10, 0))

        with _reloj(datetime(2026, 1, 5, 10, 5)), self.assertRaisesRegex(ValueError, "PCSTREAM"):
            pcs_repo.trasladar_sesion(self.pcstream_id, self.pc_id, self.usuario_id)

        self.assertIsNotNone(self._item(self.pcstream_id)["sesion"])
        self.assertEqual(_contar("traslados_sesion"), 0)

    def test_un_bono_de_pcstream_no_se_le_reintegra_a_un_socio(self):
        # Caso borde: el socio abrió "PC 1" con su saldo, el Admin la renombró a
        # PCSTREAM y se le vendió un bono de PCSTREAM encima. Al cortar, lo que
        # queda sin usar es primero el tramo del bono (el último que se sumó), que
        # no reintegra: al socio solo le vuelve lo que es suyo.
        miembro_id = self._socio_con_saldo(60)
        with _reloj(datetime(2026, 1, 5, 10, 0)):
            miembros_repo.abrir_estacion_por_miembro(self.pc_id, "juan", "clave123")
        pcs_repo.desactivar_estacion(self.pcstream_id)
        pcs_repo.renombrar_estacion(self.pcstream_id, "PCSTREAM vieja")
        pcs_repo.renombrar_estacion(self.pc_id, "PCSTREAM")
        self._vender(self.pc_id, self.bono_stream_corto_id, datetime(2026, 1, 5, 10, 0, 1))

        # Vence a las 12:00 (11:00 del saldo + 1 hora del bono). A las 10:30 quedan
        # 90 minutos: 60 del bono (se pierden) y 30 del socio. Sin contar el bono de
        # PCSTREAM, al socio le volvían 60.
        self._finalizar(self.pc_id, datetime(2026, 1, 5, 10, 30, 0))

        self.assertEqual(miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"], 30)


class TestOrdenDePcstream(_ConPcstream):
    def test_pcstream_va_antes_que_las_demas_pcs(self):
        pcs_repo.crear_estacion("PC 10")
        pcs_repo.crear_estacion("PC 2")

        nombres = [e["nombre"] for e in pcs_repo.listar_estaciones()]

        self.assertEqual(nombres, ["PCSTREAM", "PC 1", "PC 2", "PC 10"])
        self.assertEqual([i["estacion"]["nombre"] for i in pcs_repo.estado_estaciones()], nombres)


class TestUsoDePcstream(_ConPcstream):
    """Reportes > PCSTREAM: cuánto se usó, en tiempo y en plata, día por día."""

    def setUp(self):
        super().setUp()
        dia1, dia2 = date(2026, 1, 5), date(2026, 1, 6)
        # Día 1, a la mañana: 2 horas ($15.000), pero se corta a la hora y media.
        self._vender(self.pcstream_id, self.bono_stream_id, datetime(2026, 1, 5, 10, 0))
        self._finalizar(self.pcstream_id, datetime(2026, 1, 5, 11, 30))
        # Día 1, a la tarde: 1 hora + otra hora ($8.000 + $8.000); se da de baja
        # unos segundos después de vencer (el refresco de la grilla): cuenta 2 horas justas.
        self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 5, 14, 0))
        self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 5, 14, 30))
        self._finalizar(self.pcstream_id, datetime(2026, 1, 5, 16, 0, 5))
        # Una PC común ese mismo día: no tiene que aparecer.
        self._vender(self.pc_id, self.bono_pc_id, datetime(2026, 1, 5, 15, 0))
        # Día 2: 1 hora que todavía está en curso, y cuya venta se anuló.
        venta_anulada = self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 6, 9, 0))
        ventas_repo.anular_venta(venta_anulada, self.usuario_id, "cobrada dos veces")
        self.dia1, self.dia2 = dia1.isoformat(), dia2.isoformat()

    def _uso(self, desde, hasta, ahora=datetime(2026, 1, 6, 9, 20)):
        with _reloj(ahora):
            return pcstream_repo.uso_por_dia(desde, hasta)

    def test_dia_por_dia_en_tiempo_y_en_plata(self):
        uso = self._uso(self.dia1, self.dia2)

        dia1, dia2 = uso["dias"]
        self.assertEqual(dia1, {
            "dia": self.dia1, "sesiones": 2, "bonos": 3, "minutos_vendidos": 240,
            "segundos_de_uso": (90 + 120) * 60, "recaudado": 31000.0,
        })
        # La venta anulada no suma plata ni bonos, pero la PC sí se usó.
        self.assertEqual(dia2, {
            "dia": self.dia2, "sesiones": 1, "bonos": 0, "minutos_vendidos": 0,
            "segundos_de_uso": 20 * 60, "recaudado": 0.0,
        })
        self.assertEqual(uso["total"], {
            "sesiones": 3, "bonos": 3, "minutos_vendidos": 240,
            "segundos_de_uso": (90 + 120 + 20) * 60, "recaudado": 31000.0,
        })

    def test_solo_cuenta_las_fechas_pedidas(self):
        uso = self._uso(self.dia2, self.dia2)

        self.assertEqual([dia["dia"] for dia in uso["dias"]], [self.dia2])
        self.assertEqual(uso["total"]["recaudado"], 0.0)

    def test_sin_uso_devuelve_todo_en_cero(self):
        uso = self._uso("2026-02-01", "2026-02-28")

        self.assertEqual(uso["dias"], [])
        self.assertEqual(uso["total"], {
            "sesiones": 0, "bonos": 0, "minutos_vendidos": 0, "segundos_de_uso": 0, "recaudado": 0.0,
        })

    def test_lo_de_la_madrugada_suma_en_el_dia_en_que_empezo_la_noche(self):
        # Día del local: de 06:00 a 06:00. Una sesión de las 23:00 del 7 que se
        # extiende a la 01:00 del 8 es toda de la Noche del 7. (Antes se cierra la
        # sesión que dejó abierta el setUp, para que esta sea una sesión nueva.)
        self._finalizar(self.pcstream_id, datetime(2026, 1, 6, 10, 0))
        self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 7, 23, 0))
        self._vender(self.pcstream_id, self.bono_stream_corto_id, datetime(2026, 1, 8, 1, 0))

        uso_7 = self._uso("2026-01-07", "2026-01-07", ahora=datetime(2026, 1, 8, 2, 0))
        uso_8 = self._uso("2026-01-08", "2026-01-08", ahora=datetime(2026, 1, 8, 2, 0))

        self.assertEqual((uso_7["total"]["bonos"], uso_7["total"]["sesiones"]), (2, 1))
        self.assertEqual(uso_7["total"]["recaudado"], 16000.0)
        self.assertEqual(uso_8["dias"], [])

    def test_renombrarla_despues_no_le_borra_el_historial(self):
        pcs_repo.renombrar_estacion(self.pcstream_id, "PC STREAM VIEJA")

        self.assertEqual(self._uso(self.dia1, self.dia2)["total"]["recaudado"], 31000.0)

    def test_sus_bonos_salen_en_el_ranking_de_ventas(self):
        filas = reportes_repo.ranking_ventas(self.dia1, self.dia2)

        stream = [f for f in filas if f["categoria"] == reportes_repo.CATEGORIA_BONO_PCSTREAM]
        self.assertEqual(
            sorted((f["descripcion"], f["cantidad"], f["importe"]) for f in stream),
            [("1 hora stream", 2, 16000.0), ("2 horas stream", 1, 15000.0)],
        )

    def test_sus_bonos_salen_en_la_actividad_reciente(self):
        bonos = [e for e in actividad_repo.actividad_reciente() if e["tipo"] == "BONO"]

        self.assertIn(("PCSTREAM", "2 horas stream"), {(e["estacion_nombre"], e["bono_nombre"]) for e in bonos})
        self.assertIn(("PC 1", "3 horas"), {(e["estacion_nombre"], e["bono_nombre"]) for e in bonos})

    def test_la_pestana_de_reportes_muestra_los_totales(self):
        with _reloj(datetime(2026, 1, 6, 9, 20)):
            pestaña = PestañaPcstream()
            self.addCleanup(pestaña.deleteLater)
            pestaña.fecha_desde.setDate(date(2026, 1, 5))
            pestaña.fecha_hasta.setDate(date(2026, 1, 6))
            pestaña._buscar()

        self.assertEqual(pestaña.etiqueta_bonos.text(), "3")
        self.assertEqual(pestaña.etiqueta_vendido.text(), "4h 00m")
        self.assertEqual(pestaña.etiqueta_uso.text(), "3h 50m")
        self.assertEqual(pestaña.tabla.rowCount(), 3)  # dos días + TOTAL
        self.assertEqual(pestaña.tabla.item(2, 0).text(), "TOTAL")
        self.assertEqual(pestaña.tabla.item(0, 0).text(), "05/01/2026")


class TestPcstreamEnPantalla(_ConPcstream):
    def setUp(self):
        super().setUp()
        self.usuario = usuarios_repo.obtener_usuario(self.usuario_id)
        self.bono_ps_id = playstation_repo.crear_bono(self.usuario_id, "1 hora PS5", 60, 3000)

    def _panel(self):
        panel = PanelDetalleEstacion(self.usuario, lambda: None)
        self.addCleanup(panel.deleteLater)
        return panel

    @staticmethod
    def _habilitados(lista):
        return [boton.isEnabled() for boton in lista.grupo.buttons()]

    def test_con_pcstream_elegida_solo_se_pueden_tocar_sus_bonos(self):
        panel = self._panel()

        panel.mostrar(self._item(self.pcstream_id))

        self.assertEqual(len(panel.lista_pcstream.grupo.buttons()), 2)
        self.assertTrue(all(self._habilitados(panel.lista_pcstream)))
        self.assertFalse(any(self._habilitados(panel.lista_pc)))
        self.assertFalse(any(self._habilitados(panel.lista_playstation)))
        self.assertTrue(panel.boton_iniciar.isEnabled())
        self.assertFalse(panel.boton_miembro.isEnabled())  # los socios no la usan
        self.assertEqual(panel.etiqueta_titulo.text(), "PCSTREAM")

    def test_con_una_pc_comun_elegida_los_de_pcstream_quedan_apagados(self):
        panel = self._panel()

        panel.mostrar(self._item(self.pc_id))

        self.assertTrue(all(self._habilitados(panel.lista_pc)))
        self.assertFalse(any(self._habilitados(panel.lista_pcstream)))
        self.assertTrue(panel.boton_miembro.isEnabled())

    def test_desde_el_panel_se_cobra_el_bono_tildado_de_pcstream(self):
        panel = self._panel()
        panel.mostrar(self._item(self.pcstream_id))
        panel.lista_pcstream.grupo.button(self.bono_stream_corto_id).click()  # "1 hora stream", $8.000

        with mock.patch("control_pcs.ui.pcs_detalle.resolver_pagos") as resolver:
            resolver.side_effect = lambda ventana, metodo, monto: _efectivo(monto)
            panel._confirmar_bono()

        venta = ventas_repo.listar_ventas_recientes()[0]
        self.assertEqual((venta["origen"], venta["total"]), (dominio.ORIGEN_ALQUILER_PCS, 8000.0))
        self.assertIsNotNone(self._item(self.pcstream_id)["sesion"])
        self.assertIsNone(self._item(self.pc_id)["sesion"])

    def test_en_el_mosaico_va_al_lado_de_la_playstation(self):
        pcs_repo.crear_estacion("PC 2")
        grilla = PanelControlPcs(self.usuario)
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)

        nombres = [grilla.mosaico.ficha(fila).nombre for fila in range(grilla.mosaico.count())]

        self.assertEqual(nombres, ["PLAYSTATION 5", "PCSTREAM", "PC 1", "PC 2"])

    def test_el_admin_administra_sus_bonos_desde_su_propia_pantalla(self):
        dialogo = DialogoGestionBonosPcstream()
        self.addCleanup(dialogo.deleteLater)

        self.assertEqual(dialogo.windowTitle(), "Gestionar Bonos de PCSTREAM")
        self.assertEqual(
            [dialogo.tabla.item(fila, 0).text() for fila in range(dialogo.tabla.rowCount())],
            ["1 hora stream", "2 horas stream"],
        )


if __name__ == "__main__":
    unittest.main()
