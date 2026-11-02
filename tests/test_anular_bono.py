"""
tests/test_anular_bono.py
=========================
Quitar un bono vendido de más (pedido del dueño, 2026-11-02: le cargó dos bonos de 5 h a
un cliente por error y el Administrador tiene que poder dejarlo bien). Se anula la
venta (la plata sale de la caja y de los reportes) y se le saca a la sesión el tiempo
que sumó, las dos cosas juntas. Ver control_pcs/repositories/anular_bono_repo.py,
control_pcs/ui/anular_bono.py, el botón "Quitar un bono" del panel de la PC y Consulta
de Ventas. Las pantallas se prueban sin abrir ninguna ventana (plataforma "offscreen").
"""

import contextlib
import os
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from admin_remoto import lista_blanca  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    actividad_repo, anular_bono_repo, bonos_miembro_repo, miembros_repo, pcs_repo, pcstream_repo,
    playstation_repo, reintegros_repo, reservas_habilitar_repo, reservas_repo,
)
from control_pcs.ui import anular_bono  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo, ventas_repo  # noqa: E402
from ui.consulta_ventas_window import ConsultaVentasWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

CINCO_HORAS = 300


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


@contextlib.contextmanager
def dialogos(motivo="se cargó dos veces", confirma=True):
    """Los cuadros del cartel, contestados: lo que el Admin elige y escribe. Devuelve los
    mocks para ver qué se mostró. En la lista elige siempre el primero (el más nuevo)."""
    qinputdialog = mock.Mock()
    qinputdialog.getItem.side_effect = lambda padre, titulo, etiqueta, items, *resto: (items[0], True)
    qinputdialog.getText.return_value = (motivo, True)
    nombres = {"confirmar": mock.Mock(return_value=confirma), "mostrar_info": mock.Mock(),
               "mostrar_aviso": mock.Mock(), "mostrar_error": mock.Mock(), "QInputDialog": qinputdialog}
    with contextlib.ExitStack() as pila:
        for nombre, falso in nombres.items():
            pila.enter_context(mock.patch(f"control_pcs.ui.anular_bono.{nombre}", falso))
        yield SimpleNamespace(confirmar=nombres["confirmar"], info=nombres["mostrar_info"],
                              aviso=nombres["mostrar_aviso"], error=nombres["mostrar_error"],
                              dialogo=qinputdialog)


class BaseAnularBono(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.pc = pcs_repo.crear_estacion("PC 3")
        self.bono_5h = pcs_repo.crear_bono("5 horas", CINCO_HORAS, 8000)

    def vender(self, estacion=None, bono=None):
        """Le vende un bono (por defecto el de 5 h) a una PC, pagado justo en efectivo."""
        bono = bono or self.bono_5h
        return pcs_repo.asignar_bono(estacion or self.pc, bono, self.toby,
                                     _efectivo(pcs_repo.obtener_bono(bono)["precio"]))

    def estado_de(self, venta_id):
        return ventas_repo.buscar_venta(venta_id)[0]["estado"]

    def sesion_de(self, venta_id, vinculo="sesion_bonos"):
        with conexion_db() as conexion:
            return conexion.execute(
                f"SELECT sesion_id FROM {vinculo} WHERE venta_id = ?", (venta_id,)
            ).fetchone()["sesion_id"]

    def fin_de(self, sesion_id, tabla="sesiones_pc"):
        with conexion_db() as conexion:
            fila = conexion.execute(f"SELECT fecha_fin_prevista FROM {tabla} WHERE id = ?", (sesion_id,)).fetchone()
        return datetime.fromisoformat(fila["fecha_fin_prevista"])

    def poner_fin(self, sesion_id, fin):
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             (fin.isoformat(timespec="seconds"), sesion_id))

    def cobrado(self):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT COALESCE(SUM(total), 0) FROM ventas WHERE estado = ?", (dominio.VENTA_CONFIRMADA,)
            ).fetchone()[0]


class TestRectificarUnBonoRepetido(BaseAnularBono):
    def test_dos_bonos_de_5_horas_por_error_se_rectifican_en_tiempo_y_en_plata(self):
        primera, repetida = self.vender(), self.vender()
        sesion = self.sesion_de(repetida)
        self.assertEqual(self.sesion_de(primera), sesion)
        fin_con_los_dos = self.fin_de(sesion)
        self.assertGreater(fin_con_los_dos - datetime.now(), timedelta(minutes=599))   # 10 h en vez de 5 h
        self.assertEqual(self.cobrado(), 16000)                                         # $ 16.000 en vez de $ 8.000

        hecho = anular_bono_repo.anular_bono(repetida, self.admin, "se cargó dos veces")

        self.assertEqual(hecho, {"minutos": CINCO_HORAS, "sacados": CINCO_HORAS, "sin_sacar": 0, "estacion": "PC 3"})
        # El tiempo: le quedan 5 h, y la sesión sigue en curso.
        self.assertEqual(fin_con_los_dos - self.fin_de(sesion), timedelta(minutes=CINCO_HORAS))
        # La plata: una sola venta sigue valiendo, la otra queda anulada con quién, cuándo y por qué.
        self.assertEqual(self.cobrado(), 8000)
        self.assertEqual(self.estado_de(primera), dominio.VENTA_CONFIRMADA)
        anulada = ventas_repo.buscar_venta(repetida)[0]
        self.assertEqual(anulada["estado"], dominio.VENTA_ANULADA)
        self.assertEqual(anulada["anulada_por"], self.admin)
        self.assertEqual(anulada["anulada_motivo"], "se cargó dos veces")

    def test_da_igual_cual_de_los_dos_se_anule(self):
        primera, repetida = self.vender(), self.vender()
        sesion = self.sesion_de(primera)
        fin = self.fin_de(sesion)

        anular_bono_repo.anular_bono(primera, self.admin, "se cargó dos veces")

        self.assertEqual(fin - self.fin_de(sesion), timedelta(minutes=CINCO_HORAS))
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_CONFIRMADA)

    def test_solo_un_admin_y_con_motivo_y_sin_ellos_no_cambia_nada(self):
        primera, repetida = self.vender(), self.vender()
        sesion = self.sesion_de(repetida)
        fin = self.fin_de(sesion)

        with self.assertRaises(PermissionError):
            anular_bono_repo.anular_bono(repetida, self.toby, "x")
        with self.assertRaises(ValueError):
            anular_bono_repo.anular_bono(repetida, self.admin, "   ")

        self.assertEqual(self.estado_de(repetida), dominio.VENTA_CONFIRMADA)
        self.assertEqual(self.fin_de(sesion), fin)

    def test_no_se_anula_dos_veces_ni_se_le_saca_el_tiempo_otra_vez(self):
        primera, repetida = self.vender(), self.vender()
        anular_bono_repo.anular_bono(repetida, self.admin, "se cargó dos veces")
        fin = self.fin_de(self.sesion_de(primera))

        with self.assertRaises(ValueError):
            anular_bono_repo.anular_bono(repetida, self.admin, "otra vez")

        self.assertEqual(self.fin_de(self.sesion_de(primera)), fin)

    def test_si_el_cliente_ya_uso_parte_solo_se_saca_lo_que_le_queda(self):
        venta = self.vender()
        sesion = self.sesion_de(venta)
        self.poner_fin(sesion, datetime.now() + timedelta(minutes=125, seconds=30))
        fin = self.fin_de(sesion)

        hecho = anular_bono_repo.anular_bono(venta, self.admin, "no lo quiso")

        self.assertEqual((hecho["sacados"], hecho["sin_sacar"]), (125, CINCO_HORAS - 125))
        self.assertEqual(fin - self.fin_de(sesion), timedelta(minutes=125))
        self.assertGreater(self.fin_de(sesion), datetime.now())   # nunca antes de ahora
        self.assertEqual(self.estado_de(venta), dominio.VENTA_ANULADA)

    def test_si_la_sesion_ya_se_cerro_se_anula_solo_la_plata(self):
        venta = self.vender()
        sesion = self.sesion_de(venta)
        pcs_repo.finalizar_sesion(sesion)

        hecho = anular_bono_repo.anular_bono(venta, self.admin, "se cobró de más")

        self.assertEqual(hecho, {"minutos": CINCO_HORAS, "sacados": 0, "sin_sacar": CINCO_HORAS, "estacion": "PC 3"})
        self.assertEqual(self.estado_de(venta), dominio.VENTA_ANULADA)
        self.assertEqual(self.cobrado(), 0)

    def test_una_venta_que_no_es_un_bono_no_se_anula_por_aca(self):
        with conexion_db() as conexion:
            venta_id = ventas_repo.registrar_venta_sin_detalle(
                conexion, self.toby, 500, _efectivo(500), dominio.ORIGEN_ALQUILER_PCS, datetime.now()
            )

        self.assertIsNone(anular_bono_repo.resumen_de_bono(venta_id))
        with self.assertRaises(ValueError):
            anular_bono_repo.anular_bono(venta_id, self.admin, "x")
        self.assertEqual(self.estado_de(venta_id), dominio.VENTA_CONFIRMADA)

    def test_el_resumen_dice_lo_que_hay_antes_de_anular(self):
        self.vender()
        repetida = self.vender()

        resumen = anular_bono_repo.resumen_de_bono(repetida)

        self.assertEqual({clave: resumen[clave] for clave in
                          ("venta_id", "bono", "minutos", "monto", "anulada", "estacion", "de_reserva")},
                         {"venta_id": repetida, "bono": "5 horas", "minutos": CINCO_HORAS, "monto": 8000.0,
                          "anulada": False, "estacion": "PC 3", "de_reserva": False})
        self.assertGreaterEqual(resumen["minutos_en_la_pc"], 2 * CINCO_HORAS - 1)

    def test_los_bonos_de_la_sesion_son_los_que_siguen_valiendo_el_mas_nuevo_primero(self):
        primera, segunda, tercera = self.vender(), self.vender(), self.vender()
        anular_bono_repo.anular_bono(segunda, self.admin, "x")

        bonos = anular_bono_repo.bonos_de_la_sesion(self.pc)

        self.assertEqual([b["venta_id"] for b in bonos], [tercera, primera])
        self.assertEqual({b["monto"] for b in bonos}, {8000.0})
        self.assertEqual(anular_bono_repo.bonos_de_la_sesion(pcs_repo.crear_estacion("PC 4")), [])


class TestLoQueQuedaDespues(BaseAnularBono):
    def test_la_actividad_reciente_no_muestra_el_bono_anulado(self):
        self.vender()
        repetida = self.vender()
        bonos = lambda: [e for e in actividad_repo.actividad_reciente() if e["tipo"] == "BONO"]
        self.assertEqual(len(bonos()), 2)

        anular_bono_repo.anular_bono(repetida, self.admin, "se cargó dos veces")

        self.assertEqual(len(bonos()), 1)

    def test_el_reintegro_del_socio_no_se_come_el_tiempo_del_bono_anulado(self):
        """Un socio entra a una PC y, mientras juega, le suman dos bonos de más: al anular uno, lo
        que se le devuelve al socio si se va antes sigue saliendo de SU tramo."""
        ana = miembros_repo.crear_miembro("ana", "clave123", "Ana Pérez", "30111222", "1155554444")
        bono_socio = bonos_miembro_repo.crear_bono("3 horas", 180, 3000)
        miembros_repo.cargar_saldo_por_bono(ana, bono_socio, _efectivo(3000), self.toby)
        sesion = miembros_repo.abrir_estacion_por_miembro(self.pc, "ana", "clave123")["sesion_id"]
        una_hora = pcs_repo.crear_bono("1 hora", 60, 1500)
        self.vender(bono=una_hora)
        repetida = self.vender(bono=una_hora)

        anular_bono_repo.anular_bono(repetida, self.admin, "se cargó dos veces")

        with conexion_db() as conexion:
            # Quedan 3 h de Ana + 1 h de bono: si se corta con 4 h por delante, la última hora es del
            # bono (no reintegra) y las 3 h de Ana vuelven enteras.
            self.assertEqual(reintegros_repo.reintegros_por_miembro(conexion, sesion, 240), {ana: 180})


class TestOtrosBonos(BaseAnularBono):
    def test_el_bono_de_pcstream_se_quita_igual(self):
        stream = pcs_repo.crear_estacion("PCSTREAM")
        bono = pcstream_repo.crear_bono("3 hs PCSTREAM", 180, 4500)
        pagos = _efectivo(4500)
        primera = pcs_repo.asignar_bono(stream, bono, self.toby, pagos)
        repetida = pcs_repo.asignar_bono(stream, bono, self.toby, pagos)
        sesion = self.sesion_de(repetida, "sesion_pcstream_bonos")
        fin = self.fin_de(sesion)

        hecho = anular_bono_repo.anular_bono(repetida, self.admin, "se cargó dos veces")

        self.assertEqual((hecho["sacados"], hecho["estacion"]), (180, "PCSTREAM"))
        self.assertEqual(fin - self.fin_de(sesion), timedelta(minutes=180))
        self.assertEqual(self.estado_de(primera), dominio.VENTA_CONFIRMADA)
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)

    def test_el_bono_de_la_playstation_se_quita_igual(self):
        bono = playstation_repo.crear_bono(self.admin, "2 horas PS5", 120, 6000)
        playstation_repo.vender_bono(self.toby, bono, _efectivo(6000))
        repetida = playstation_repo.vender_bono(self.toby, bono, _efectivo(6000))
        sesion = self.sesion_de(repetida, "sesion_playstation_bonos")
        fin = self.fin_de(sesion, "sesiones_playstation")

        self.assertEqual([b["venta_id"] for b in anular_bono_repo.bonos_de_la_sesion(None)][0], repetida)
        hecho = anular_bono_repo.anular_bono(repetida, self.admin, "se cargó dos veces")

        self.assertEqual((hecho["sacados"], hecho["estacion"]), (120, dominio.NOMBRE_PLAYSTATION))
        self.assertEqual(fin - self.fin_de(sesion, "sesiones_playstation"), timedelta(minutes=120))
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)

    def test_el_bono_de_una_reserva_no_se_anula_por_aca(self):
        manana = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=10)
        reserva = reservas_repo.crear_reserva(self.toby, "Juan Pérez", "11 5555-4444", dominio.EQUIPO_RESERVA_PC,
                                              self.pc, self.bono_5h, manana, 8000.0, _efectivo(8000.0))
        reservas_habilitar_repo.habilitar(reserva, self.toby, self.pc, [])
        with conexion_db() as conexion:
            venta_id = conexion.execute("SELECT venta_id FROM sesion_bonos").fetchone()["venta_id"]

        self.assertTrue(anular_bono_repo.resumen_de_bono(venta_id)["de_reserva"])
        self.assertEqual(anular_bono_repo.bonos_de_la_sesion(self.pc), [])
        with self.assertRaises(ValueError):
            anular_bono_repo.anular_bono(venta_id, self.admin, "x")
        self.assertEqual(self.estado_de(venta_id), dominio.VENTA_CONFIRMADA)


class TestElCartel(BaseAnularBono):
    RESUMEN = {"venta_id": 7, "bono": "5 horas", "minutos": CINCO_HORAS, "monto": 8000.0, "anulada": False,
               "estacion": "PC 3", "minutos_en_la_pc": 540, "de_reserva": False}

    def test_con_tiempo_de_sobra_dice_cuanto_le_queda_y_que_sigue_jugando(self):
        texto = anular_bono.texto_de_confirmacion(self.RESUMEN)
        self.assertIn("5 horas (5 h) por $ 8.000 en PC 3 (venta Nº 7)", texto)
        self.assertIn("esos $ 8.000 salen de la caja", texto)
        self.assertIn("a PC 3 le quedan 9 h. Se le sacan 5 h y sigue con 4 h.", texto)

    def test_si_ya_uso_parte_dice_cuanto_no_se_puede_recuperar(self):
        texto = anular_bono.texto_de_confirmacion(dict(self.RESUMEN, minutos_en_la_pc=120))
        self.assertIn("Se le sacan 2 h: se queda sin tiempo.", texto)
        self.assertIn("Los otros 3 h ya los usó y no se pueden recuperar.", texto)

    def test_sin_sesion_se_anula_solo_la_plata(self):
        texto = anular_bono.texto_de_confirmacion(dict(self.RESUMEN, minutos_en_la_pc=0))
        self.assertIn("no tiene una sesión en curso", texto)
        self.assertIn("se anula solo la plata", texto)

    def test_el_resultado_cuenta_lo_que_se_hizo_y_avisa_lo_que_no(self):
        hecho = {"minutos": CINCO_HORAS, "sacados": 120, "sin_sacar": 180, "estacion": "PC 3"}
        texto = anular_bono.texto_del_resultado(self.RESUMEN, hecho)
        self.assertIn("se le sacaron 2 h a PC 3", texto)
        self.assertIn("Ojo: 3 h ya los había usado", texto)

    def test_sin_bonos_para_elegir_avisa_y_manda_a_consulta_de_ventas(self):
        with dialogos() as cuadros:
            self.assertIsNone(anular_bono.elegir_bono_a_quitar(None, "PC 3", []))
        self.assertIn("Consulta de Ventas", cuadros.aviso.call_args.args[2])

    def test_el_cartel_pide_confirmar_y_motivo_y_cuenta_el_resultado(self):
        self.vender()
        repetida = self.vender()
        usuario = usuarios_repo.obtener_usuario(self.admin)

        with dialogos() as cuadros:
            self.assertTrue(anular_bono.anular_bono_con_cartel(None, usuario, repetida))

        self.assertIn("a PC 3 le quedan", cuadros.confirmar.call_args.args[2])
        self.assertIn("Bono quitado", cuadros.info.call_args.args[2])
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)

    def test_sin_motivo_o_sin_confirmar_no_se_anula(self):
        repetida = self.vender()
        usuario = usuarios_repo.obtener_usuario(self.admin)
        with dialogos(motivo="  ") as cuadros:
            self.assertFalse(anular_bono.anular_bono_con_cartel(None, usuario, repetida))
        cuadros.error.assert_called_once()
        with dialogos(confirma=False) as cuadros:
            self.assertFalse(anular_bono.anular_bono_con_cartel(None, usuario, repetida))
        cuadros.dialogo.getText.assert_not_called()
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_CONFIRMADA)


class TestElPanelDeLaPc(BaseAnularBono):
    def panel(self, usuario_id):
        panel = PanelDetalleEstacion(usuarios_repo.obtener_usuario(usuario_id), lambda: None)
        self.addCleanup(panel.deleteLater)
        return panel

    def item(self):
        return next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.pc)

    def test_el_boton_es_solo_del_administrador(self):
        self.assertFalse(self.panel(self.admin).boton_quitar_bono.isHidden())
        self.assertTrue(self.panel(self.toby).boton_quitar_bono.isHidden())

    def test_solo_se_puede_apretar_con_una_sesion_en_curso(self):
        panel = self.panel(self.admin)
        panel.mostrar(None)
        self.assertFalse(panel.boton_quitar_bono.isEnabled())
        panel.mostrar(self.item())
        self.assertFalse(panel.boton_quitar_bono.isEnabled())
        self.vender()
        panel.mostrar(self.item())
        self.assertTrue(panel.boton_quitar_bono.isEnabled())

    def test_quitar_el_repetido_desde_el_panel_deja_la_pc_con_un_solo_bono(self):
        primera, repetida = self.vender(), self.vender()
        sesion = self.sesion_de(repetida)
        fin = self.fin_de(sesion)
        panel = self.panel(self.admin)
        panel.mostrar(self.item())

        with dialogos() as cuadros:
            panel.boton_quitar_bono.click()

        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)
        self.assertEqual(self.estado_de(primera), dominio.VENTA_CONFIRMADA)
        self.assertEqual(fin - self.fin_de(sesion), timedelta(minutes=CINCO_HORAS))
        self.assertIn("Bono quitado", cuadros.info.call_args.args[2])


class TestConsultaDeVentas(BaseAnularBono):
    def ventana(self):
        ventana = ConsultaVentasWindow(usuarios_repo.obtener_usuario(self.admin))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def elegir(self, ventana, venta_id):
        fila = next(i for i, venta in enumerate(ventana.ventas) if venta["id"] == venta_id)
        ventana.tabla.setCurrentCell(fila, 0)
        ventana.tabla.selectRow(fila)

    def test_la_venta_de_un_bono_se_anula_con_el_cartel_de_los_bonos(self):
        self.vender()
        repetida = self.vender()
        ventana = self.ventana()
        self.elegir(ventana, repetida)
        with mock.patch("ui.consulta_ventas_window.anular_bono_con_cartel", return_value=True) as cartel:
            ventana._anular()
        cartel.assert_called_once()
        self.assertEqual(cartel.call_args.args[2], repetida)

    def test_anular_desde_consulta_de_ventas_tambien_le_saca_el_tiempo(self):
        self.vender()
        repetida = self.vender()
        sesion = self.sesion_de(repetida)
        fin = self.fin_de(sesion)
        ventana = self.ventana()
        self.elegir(ventana, repetida)

        with dialogos():
            ventana._anular()

        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)
        self.assertEqual(fin - self.fin_de(sesion), timedelta(minutes=CINCO_HORAS))

    def test_la_venta_de_una_reserva_sigue_con_su_camino_de_siempre(self):
        manana = datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=10)
        reserva = reservas_repo.crear_reserva(self.toby, "Juan Pérez", "11 5555-4444", dominio.EQUIPO_RESERVA_PC,
                                              self.pc, self.bono_5h, manana, 8000.0, _efectivo(8000.0))
        reservas_habilitar_repo.habilitar(reserva, self.toby, self.pc, [])
        with conexion_db() as conexion:
            venta_id = conexion.execute("SELECT venta_id FROM sesion_bonos").fetchone()["venta_id"]
        ventana = self.ventana()
        self.elegir(ventana, venta_id)
        with mock.patch("ui.consulta_ventas_window.anular_bono_con_cartel") as cartel, \
                mock.patch("ui.consulta_ventas_window.confirmar", return_value=False) as confirmar:
            ventana._anular()
        cartel.assert_not_called()
        confirmar.assert_called_once()


class TestAdministrarDesdeOtraPc(BaseAnularBono):
    def test_anular_y_resumir_se_pueden_pedir_desde_otra_pc_y_anular_va_a_nombre_del_admin(self):
        self.assertTrue(lista_blanca.permitida("anular_bono_repo", "anular_bono"))
        self.assertTrue(lista_blanca.permitida("anular_bono_repo", "resumen_de_bono"))
        self.assertEqual(lista_blanca.ACTOR[("anular_bono_repo", "anular_bono")], "usuario_admin_id")

    def test_el_panel_de_la_pc_sigue_siendo_del_mostrador(self):
        self.assertFalse(lista_blanca.permitida("anular_bono_repo", "bonos_de_la_sesion"))


if __name__ == "__main__":
    import unittest
    unittest.main()
