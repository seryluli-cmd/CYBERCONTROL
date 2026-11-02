"""
tests/test_anular_carga.py
==========================
Rectificar una carga de saldo repetida por error (pedido del dueño, 2026-11-02:
la empleada le cargó dos bonos en vez de uno a un socio, que quedó con 10 h en
vez de 5 y la caja con $ 16.000 en vez de $ 8.000). El Admin anula la carga y se
corrigen las dos cosas juntas: la plata (la venta queda ANULADA) y el tiempo (se
le saca al socio). Ver miembros_repo.anular_carga, control_pcs/ui/anular_carga.py
y el botón "Anular carga" del Historial de Cargas. Las pantallas se prueban sin
abrir ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import bonos_miembro_repo, historial_cargas_repo, miembros_repo, pcs_repo, reintegros_repo  # noqa: E402
from control_pcs.ui import anular_carga  # noqa: E402
from control_pcs.ui.miembros_historial_cargas import COLUMNA_ESTADO, VentanaHistorialCargas  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo, ventas_repo  # noqa: E402
from turnos import dia_en_que_empezo_el_turno  # noqa: E402
from ui.consulta_ventas_window import ConsultaVentasWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3000}]
TRES_HORAS = 180


class BaseAnularCarga(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.ana = miembros_repo.crear_miembro("ana", "clave123", "Ana Pérez", "30111222", "1155554444")
        self.pc = pcs_repo.crear_estacion("PC 3")
        self.bono_3h = bonos_miembro_repo.crear_bono("3 horas", TRES_HORAS, 3000)
        self.hoy = dia_en_que_empezo_el_turno(datetime.now())

    def cargar_bono(self):
        return miembros_repo.cargar_saldo_por_bono(self.ana, self.bono_3h, EFECTIVO, self.toby)["venta_id"]

    def saldo(self):
        return miembros_repo.obtener_miembro(self.ana)["saldo_minutos"]

    def estado_de(self, venta_id):
        return ventas_repo.buscar_venta(venta_id)[0]["estado"]

    def anulaciones(self, venta_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT * FROM movimientos_saldo_miembro WHERE venta_id = ? AND tipo = 'ANULACION' ORDER BY id",
                (venta_id,),
            ).fetchall()

    def sesion(self, sesion_id):
        with conexion_db() as conexion:
            return conexion.execute("SELECT * FROM sesiones_pc WHERE id = ?", (sesion_id,)).fetchone()

    def fin_de(self, sesion_id):
        return datetime.fromisoformat(self.sesion(sesion_id)["fecha_fin_prevista"])

    def jugando_con_dos_bonos_de_mas(self):
        """Ana entra a la PC con un bono de 3 h y, ya jugando, la empleada le carga
        dos más por error. Devuelve (id de la sesión, id de la venta repetida)."""
        self.cargar_bono()
        sesion_id = miembros_repo.abrir_estacion_por_miembro(self.pc, "ana", "clave123")["sesion_id"]
        self.cargar_bono()
        repetida = self.cargar_bono()
        self.assertEqual(self.saldo(), 0)
        return sesion_id, repetida


class TestRectificarUnaCargaRepetida(BaseAnularCarga):
    def test_dos_bonos_por_error_se_rectifican_en_tiempo_y_en_plata(self):
        primera, repetida = self.cargar_bono(), self.cargar_bono()
        self.assertEqual(self.saldo(), 2 * TRES_HORAS)   # 6 h en vez de 3 h

        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces")

        self.assertEqual(self.saldo(), TRES_HORAS)
        self.assertEqual(hecho, {"minutos": TRES_HORAS, "sacados": TRES_HORAS, "del_saldo": TRES_HORAS,
                                 "de_la_pc": 0, "estacion": None, "sin_sacar": 0})
        # La plata: una sola venta sigue valiendo, la otra queda anulada con su motivo.
        self.assertEqual(self.estado_de(primera), dominio.VENTA_CONFIRMADA)
        anulada = ventas_repo.buscar_venta(repetida)[0]
        self.assertEqual(anulada["estado"], dominio.VENTA_ANULADA)
        self.assertEqual(anulada["anulada_por"], self.admin)
        self.assertEqual(anulada["anulada_motivo"], "se cargó dos veces")
        with conexion_db() as conexion:
            cobrado = conexion.execute(
                "SELECT SUM(total) FROM ventas WHERE estado = ?", (dominio.VENTA_CONFIRMADA,)
            ).fetchone()[0]
        self.assertEqual(cobrado, 3000)
        # Y el tiempo deja su rastro en el ledger, sin disimularse de consumo.
        filas = self.anulaciones(repetida)
        self.assertEqual([(f["minutos"], f["sesion_id"]) for f in filas], [(TRES_HORAS, None)])

    def test_la_carga_anulada_sale_marcada_en_el_historial_y_no_suma(self):
        self.cargar_bono()
        repetida = self.cargar_bono()
        miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces")

        cargas = historial_cargas_repo.listar_cargas(self.hoy, self.hoy)

        self.assertEqual([c["venta_id"] for c in cargas if c["anulada"]], [repetida])
        self.assertEqual(historial_cargas_repo.totales(cargas),
                         {"cantidad": 1, "minutos": TRES_HORAS, "monto": 3000.0, "anuladas": 1})

    def test_solo_un_admin_y_con_motivo(self):
        repetida = self.cargar_bono()
        with self.assertRaises(PermissionError):
            miembros_repo.anular_carga(repetida, self.toby, "x")
        with self.assertRaises(ValueError):
            miembros_repo.anular_carga(repetida, self.admin, "   ")
        # No se tocó nada.
        self.assertEqual(self.saldo(), TRES_HORAS)
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_CONFIRMADA)

    def test_una_carga_no_se_anula_dos_veces(self):
        repetida = self.cargar_bono()
        self.cargar_bono()
        miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces")
        with self.assertRaises(ValueError):
            miembros_repo.anular_carga(repetida, self.admin, "otra vez")
        self.assertEqual(self.saldo(), TRES_HORAS)

    def test_si_ya_uso_una_parte_se_saca_hasta_lo_que_tiene_y_se_dice(self):
        repetida = self.cargar_bono()
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 60 WHERE id = ?", (self.ana,))

        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces")

        self.assertEqual(self.saldo(), 0)
        self.assertEqual((hecho["sacados"], hecho["sin_sacar"]), (60, 120))
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)

    def test_resumen_de_carga(self):
        repetida = self.cargar_bono()
        resumen = miembros_repo.resumen_de_carga(repetida)
        self.assertEqual(resumen, {
            "venta_id": repetida, "socio": "ana", "minutos": TRES_HORAS, "monto": 3000.0, "anulada": False,
            "saldo_actual": TRES_HORAS, "estacion": None, "minutos_en_la_pc": 0,
        })
        miembros_repo.anular_carga(repetida, self.admin, "error")
        self.assertTrue(miembros_repo.resumen_de_carga(repetida)["anulada"])

    def test_resumen_de_una_venta_que_no_cargo_saldo(self):
        bono_pc = pcs_repo.crear_bono("1 hora", 60, 1500)
        venta_id = pcs_repo.asignar_bono(self.pc, bono_pc, self.toby, [{"metodo": "EFECTIVO", "monto": 1500}])
        self.assertIsNone(miembros_repo.resumen_de_carga(venta_id))
        self.assertIsNone(miembros_repo.resumen_de_carga(99999))


class TestElSocioEstaJugando(BaseAnularCarga):
    def test_el_resumen_dice_en_que_pc_juega_y_cuanto_le_queda(self):
        _sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        resumen = miembros_repo.resumen_de_carga(repetida)
        self.assertEqual(resumen["estacion"], "PC 3")
        self.assertAlmostEqual(resumen["minutos_en_la_pc"], 3 * TRES_HORAS, delta=1)
        self.assertEqual(resumen["saldo_actual"], 0)

    def test_sin_pedirlo_no_se_toca_la_pc(self):
        sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        fin = self.fin_de(sesion_id)

        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces")

        self.assertEqual((hecho["sacados"], hecho["sin_sacar"]), (0, TRES_HORAS))
        self.assertEqual(self.fin_de(sesion_id), fin)
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)

    def test_pidiendolo_se_le_saca_el_tiempo_a_la_pc_y_sigue_jugando(self):
        sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        fin = self.fin_de(sesion_id)

        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces", sacar_de_la_pc=True)

        self.assertEqual(hecho, {"minutos": TRES_HORAS, "sacados": TRES_HORAS, "del_saldo": 0,
                                 "de_la_pc": TRES_HORAS, "estacion": "PC 3", "sin_sacar": 0})
        self.assertEqual(fin - self.fin_de(sesion_id), timedelta(minutes=TRES_HORAS))
        self.assertEqual(self.sesion(sesion_id)["estado"], dominio.SESION_ACTIVA)
        self.assertEqual(self.saldo(), 0)
        # En el ledger queda atada a la venta y a la sesión de la que se sacó.
        filas = self.anulaciones(repetida)
        self.assertEqual([(f["minutos"], f["sesion_id"]) for f in filas], [(TRES_HORAS, sesion_id)])

    def test_despues_el_reintegro_al_irse_sigue_cuadrando(self):
        # Ana tenía 3 h pagadas + 3 h del bono que sí quería: al irse al toque, vuelven
        # ~6 h a su saldo (en bloques de 30), no 9 h.
        sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces", sacar_de_la_pc=True)

        pcs_repo.finalizar_sesion(sesion_id)

        self.assertEqual(self.saldo(), 2 * TRES_HORAS - 30)
        with conexion_db() as conexion:
            self.assertEqual(reintegros_repo.contribuciones_de_sesion(conexion, sesion_id)[0]["minutos"], TRES_HORAS)

    def test_no_se_le_saca_a_la_pc_mas_de_lo_que_le_queda(self):
        sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        # Ya jugó casi todo: le quedan 100 minutos.
        nuevo_fin = datetime.now() + timedelta(minutes=100)
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             (nuevo_fin.isoformat(timespec="seconds"), sesion_id))

        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces", sacar_de_la_pc=True)

        self.assertTrue(98 <= hecho["de_la_pc"] <= 100, hecho)
        self.assertEqual(hecho["sin_sacar"], TRES_HORAS - hecho["de_la_pc"])
        # La sesión no queda por debajo de ahora ni se cierra de golpe.
        self.assertGreaterEqual(self.fin_de(sesion_id), datetime.now().replace(microsecond=0))
        self.assertEqual(self.sesion(sesion_id)["estado"], dominio.SESION_ACTIVA)

    def test_con_saldo_y_pc_saca_primero_del_saldo(self):
        sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 50 WHERE id = ?", (self.ana,))

        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces", sacar_de_la_pc=True)

        self.assertEqual((hecho["del_saldo"], hecho["de_la_pc"], hecho["sin_sacar"]), (50, TRES_HORAS - 50, 0))
        self.assertEqual(self.saldo(), 0)
        self.assertEqual(len(self.anulaciones(repetida)), 2)

    def test_si_no_esta_jugando_pedirlo_no_cambia_nada(self):
        repetida = self.cargar_bono()
        self.cargar_bono()
        hecho = miembros_repo.anular_carga(repetida, self.admin, "se cargó dos veces", sacar_de_la_pc=True)
        self.assertEqual((hecho["del_saldo"], hecho["de_la_pc"], hecho["estacion"]), (TRES_HORAS, 0, None))


class TestElCartel(BaseAnularCarga):
    def resumen(self, **cambios):
        base = {"venta_id": 7, "socio": "ana", "minutos": TRES_HORAS, "monto": 3000.0, "anulada": False,
                "saldo_actual": 2 * TRES_HORAS, "estacion": None, "minutos_en_la_pc": 0}
        return {**base, **cambios}

    def test_con_saldo_de_sobra_dice_que_se_saca_del_saldo(self):
        texto, de_la_pc = anular_carga.texto_de_confirmacion(self.resumen())
        self.assertFalse(de_la_pc)
        self.assertIn("$ 3.000 salen de la caja", texto)
        self.assertIn("se le sacan 3 h del saldo (ahora tiene 6 h)", texto)

    def test_jugando_dice_de_que_pc_se_saca_y_que_sigue_jugando(self):
        texto, de_la_pc = anular_carga.texto_de_confirmacion(
            self.resumen(saldo_actual=0, estacion="PC 3", minutos_en_la_pc=500))
        self.assertTrue(de_la_pc)
        self.assertIn("está jugando en PC 3 (le quedan 8 h 20 min)", texto)
        self.assertIn("Se le sacan 3 h de PC 3: sigue jugando, pero con menos tiempo.", texto)
        self.assertNotIn("ya los usó", texto)

    def test_jugando_con_poco_tiempo_dice_lo_que_ya_uso(self):
        texto, de_la_pc = anular_carga.texto_de_confirmacion(
            self.resumen(saldo_actual=0, estacion="PC 3", minutos_en_la_pc=100))
        self.assertTrue(de_la_pc)
        self.assertIn("Se le sacan 1 h 40 min de PC 3", texto)
        self.assertIn("Los otros 1 h 20 min ya los usó", texto)

    def test_sin_tiempo_para_sacar_avisa_que_se_anula_solo_la_plata(self):
        texto, de_la_pc = anular_carga.texto_de_confirmacion(self.resumen(saldo_actual=0))
        self.assertFalse(de_la_pc)
        self.assertIn("se anula solo la plata", texto)

    def test_con_parte_del_saldo_se_saca_hasta_ahi(self):
        texto, _ = anular_carga.texto_de_confirmacion(self.resumen(saldo_actual=60))
        self.assertIn("tiene ahora 1 h de saldo y se le saca hasta ahí", texto)
        self.assertIn("Los otros 2 h ya los usó", texto)


class DialogosAfirmativos:
    """Contesta que sí a las preguntas del cartel, con un motivo escrito."""

    def __init__(self, motivo="se cargó dos veces"):
        self.motivo = motivo

    def __enter__(self):
        self._parches = [
            mock.patch("control_pcs.ui.anular_carga.confirmar", return_value=True),
            mock.patch("control_pcs.ui.anular_carga.QInputDialog.getText", return_value=(self.motivo, True)),
            mock.patch("control_pcs.ui.anular_carga.mostrar_info"),
            mock.patch("control_pcs.ui.anular_carga.mostrar_aviso"),
            mock.patch("control_pcs.ui.anular_carga.mostrar_error"),
        ]
        (self.confirmar, self.motivo_pedido, self.info, self.aviso, self.error) = [p.start() for p in self._parches]
        return self

    def __exit__(self, *args):
        for parche in self._parches:
            parche.stop()


class TestLaPantallaDeAnular(BaseAnularCarga):
    def historial(self, usuario_id):
        usuario = usuarios_repo.obtener_usuario(usuario_id) if usuario_id else None
        ventana = VentanaHistorialCargas(None, None, usuario)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def elegir(self, ventana, fila):
        ventana.tabla.setCurrentCell(fila, 0)
        ventana.tabla.selectRow(fila)

    def test_el_boton_es_solo_del_admin(self):
        self.cargar_bono()
        self.assertFalse(self.historial(self.admin).boton_anular.isHidden())
        self.assertTrue(self.historial(self.toby).boton_anular.isHidden())
        self.assertTrue(self.historial(None).boton_anular.isHidden())

    def test_el_boton_se_habilita_con_una_carga_vigente_elegida(self):
        self.cargar_bono()
        repetida = self.cargar_bono()
        ventana = self.historial(self.admin)
        self.assertFalse(ventana.boton_anular.isEnabled())   # nada elegido
        self.elegir(ventana, 0)
        self.assertTrue(ventana.boton_anular.isEnabled())
        with DialogosAfirmativos():
            ventana.boton_anular.click()
        # La anulada sigue en la lista, marcada, y ya no se puede anular otra vez.
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_ANULADA)
        self.assertIn("ANULADA", ventana.tabla.item(0, COLUMNA_ESTADO).text())
        self.assertFalse(ventana.boton_anular.isEnabled())
        self.elegir(ventana, 0)
        self.assertFalse(ventana.boton_anular.isEnabled())

    def test_anular_desde_el_historial_rectifica_el_tiempo_y_la_plata(self):
        self.cargar_bono()
        self.cargar_bono()
        ventana = self.historial(self.admin)
        self.elegir(ventana, 0)

        with DialogosAfirmativos() as dialogos:
            ventana.boton_anular.click()

        self.assertEqual(self.saldo(), TRES_HORAS)
        texto_final = dialogos.info.call_args.args[2]
        self.assertIn("Carga anulada", texto_final)
        self.assertIn("se le sacaron 3 h a ana", texto_final)
        self.assertIn("1 carga · 3h 00m · $ 3.000", ventana.etiqueta_totales.text())
        self.assertIn("sin contar 1 anulada", ventana.etiqueta_totales.text())

    def test_sin_motivo_no_se_anula(self):
        repetida = self.cargar_bono()
        ventana = self.historial(self.admin)
        self.elegir(ventana, 0)
        with DialogosAfirmativos(motivo="  ") as dialogos:
            ventana.boton_anular.click()
        dialogos.error.assert_called_once()
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_CONFIRMADA)
        self.assertEqual(self.saldo(), TRES_HORAS)

    def test_si_el_admin_dice_que_no_no_pasa_nada(self):
        repetida = self.cargar_bono()
        ventana = self.historial(self.admin)
        self.elegir(ventana, 0)
        with DialogosAfirmativos() as dialogos:
            dialogos.confirmar.return_value = False
            ventana.boton_anular.click()
        self.assertEqual(self.estado_de(repetida), dominio.VENTA_CONFIRMADA)
        dialogos.motivo_pedido.assert_not_called()

    def test_jugando_el_cartel_pide_sacar_de_la_pc_y_lo_cuenta(self):
        sesion_id, repetida = self.jugando_con_dos_bonos_de_mas()
        fin = self.fin_de(sesion_id)
        usuario = usuarios_repo.obtener_usuario(self.admin)

        with DialogosAfirmativos() as dialogos:
            self.assertTrue(anular_carga.anular_carga_con_cartel(None, usuario, repetida))

        self.assertIn("está jugando en PC 3", dialogos.confirmar.call_args.args[2])
        self.assertEqual(fin - self.fin_de(sesion_id), timedelta(minutes=TRES_HORAS))
        self.assertIn("de PC 3, donde sigue jugando", dialogos.info.call_args.args[2])

    def test_si_parte_del_tiempo_ya_se_uso_lo_dice_como_aviso(self):
        repetida = self.cargar_bono()
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = 60 WHERE id = ?", (self.ana,))
        usuario = usuarios_repo.obtener_usuario(self.admin)

        with DialogosAfirmativos() as dialogos:
            anular_carga.anular_carga_con_cartel(None, usuario, repetida)

        dialogos.aviso.assert_called_once()
        self.assertIn("ya los había usado", dialogos.aviso.call_args.args[2])
        dialogos.info.assert_not_called()


class TestConsultaDeVentas(BaseAnularCarga):
    def ventana(self):
        usuario = usuarios_repo.obtener_usuario(self.admin)
        ventana = ConsultaVentasWindow(usuario)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def elegir(self, ventana, venta_id):
        fila = next(i for i, venta in enumerate(ventana.ventas) if venta["id"] == venta_id)
        ventana.tabla.setCurrentCell(fila, 0)
        ventana.tabla.selectRow(fila)

    def test_una_venta_que_cargo_saldo_se_anula_con_el_cartel_de_las_cargas(self):
        repetida = self.cargar_bono()
        ventana = self.ventana()
        self.elegir(ventana, repetida)
        with mock.patch("ui.consulta_ventas_window.anular_carga_con_cartel", return_value=True) as cartel:
            ventana._anular()
        cartel.assert_called_once()
        self.assertEqual(cartel.call_args.args[2], repetida)

    def test_un_bono_de_pc_no_usa_el_cartel_de_las_cargas_sino_el_de_los_bonos(self):
        # Se anula con el cartel de los bonos, que también le saca el tiempo a la PC
        # (tests/test_anular_bono.py).
        bono_pc = pcs_repo.crear_bono("1 hora", 60, 1500)
        venta_id = pcs_repo.asignar_bono(self.pc, bono_pc, self.toby, [{"metodo": "EFECTIVO", "monto": 1500}])
        ventana = self.ventana()
        self.elegir(ventana, venta_id)
        with mock.patch("ui.consulta_ventas_window.anular_carga_con_cartel") as cartel_de_cargas, \
                mock.patch("ui.consulta_ventas_window.anular_bono_con_cartel", return_value=False) as cartel_de_bonos:
            ventana._anular()
        cartel_de_cargas.assert_not_called()
        cartel_de_bonos.assert_called_once()
        self.assertEqual(self.estado_de(venta_id), dominio.VENTA_CONFIRMADA)


if __name__ == "__main__":
    import unittest
    unittest.main()
