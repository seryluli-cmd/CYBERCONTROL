"""
tests/test_reservas_socios.py
===============================
RESERVAS DE SOCIOS (pedido del dueño, 2026-10-26;
control_pcs/repositories/reservas_socios_repo.py). Lo que eligió el dueño:

- reserva sin seña solo un socio con 5 hs o más de saldo; el número lo cambia
  solo el Admin, en Miembros > "$ Para Reserva";
- al reservar no se cobra ni se le descuenta nada;
- cuando llega, entra con su usuario y su clave y usa su saldo: su propia
  reserva no lo corta y queda habilitada sola;
- si no viene, queda "No vino" y no pierde nada;
- el mínimo cuenta al reservar (si ese día tiene menos, entra igual).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import turnos_ventas_repo, usuarios_repo  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    miembros_repo, pcs_repo, reservas_habilitar_repo, reservas_horario_repo, reservas_repo, reservas_socios_repo,
)
from control_pcs.ui.miembros_window import MiembrosWindow  # noqa: E402
from control_pcs.ui.reservas_socio_dialogo import DialogoReservaDeSocio, DialogoSaldoParaReserva  # noqa: E402
from control_pcs.ui.reservas_window import TITULOS, ReservasWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _en(minutos):
    """Dentro de tantos minutos, sin segundos (así se guarda una reserva)."""
    return (datetime.now() + timedelta(minutes=minutos)).replace(second=0, microsecond=0)


class _ConSocios(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.pcstream = pcs_repo.crear_estacion("PCSTREAM")
        self.juan = miembros_repo.crear_miembro("juan", "clave123", "Juan Pérez", "30111222", "1155554444")
        self.luis = miembros_repo.crear_miembro("luis", "clave123", "Luis", "30111333")
        self._poner_saldo(self.juan, 450)
        self._poner_saldo(self.luis, 120)

    def _poner_saldo(self, miembro_id, minutos):
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, miembro_id))

    def _saldo(self, miembro_id):
        return miembros_repo.obtener_miembro(miembro_id)["saldo_minutos"]

    def _reservar(self, cuando, miembro=None, estacion="pc1", horas=2):
        estacion_id = getattr(self, estacion) if estacion else None
        return reservas_socios_repo.crear_reserva_de_socio(
            self.ana, miembro or self.juan, estacion_id, cuando, horas * 60)

    def _fila(self, reserva_id):
        with conexion_db() as conexion:
            return conexion.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()

    def _cantidad(self, tabla):
        with conexion_db() as conexion:
            return conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]

    def _abrir(self, ventana):
        self.addCleanup(ventana.deleteLater)
        return ventana


class TestSaldoParaReservar(_ConSocios):
    def test_arranca_en_cinco_horas(self):
        self.assertEqual(reservas_socios_repo.horas_para_reservar(), 5)

    def test_el_admin_lo_cambia(self):
        reservas_socios_repo.guardar_horas_para_reservar(self.admin, 3)

        self.assertEqual(reservas_socios_repo.horas_para_reservar(), 3)

    def test_una_empleada_no_lo_cambia(self):
        with self.assertRaises(PermissionError):
            reservas_socios_repo.guardar_horas_para_reservar(self.ana, 3)

        self.assertEqual(reservas_socios_repo.horas_para_reservar(), 5)

    def test_de_una_a_99_horas(self):
        for horas in (0, 100):
            with self.assertRaises(ValueError):
                reservas_socios_repo.guardar_horas_para_reservar(self.admin, horas)

    def test_las_horas_se_nombran_como_las_dice_el_duenio(self):
        texto = reservas_socios_repo.texto_de_horas
        self.assertEqual((texto(300), texto(60), texto(210), texto(40)), ("5 hs", "1 h", "3 hs 30 min", "40 min"))


class TestTomarLaReserva(_ConSocios):
    def test_no_cobra_nada_ni_le_toca_el_saldo(self):
        reserva = self._fila(self._reservar(_en(180)))

        self.assertEqual((reserva["miembro_id"], reserva["cliente"], reserva["celular"]),
                         (self.juan, "Juan Pérez", "1155554444"))
        self.assertEqual((reserva["bono_id"], reserva["precio"], reserva["minutos"]),
                         (reservas_socios_repo.BONO_DE_SOCIO, 0, 120))
        self.assertEqual(reserva["estado"], dominio.RESERVA_PENDIENTE)
        self.assertEqual((self._cantidad("ventas"), self._cantidad("reservas_pagos")), (0, 0))
        self.assertEqual(self._saldo(self.juan), 450)

    def test_sin_cinco_horas_de_saldo_no_reserva_y_dice_cuanto_le_falta(self):
        self._poner_saldo(self.juan, 270)

        with self.assertRaisesRegex(ValueError, "tiene 4 hs 30 min.*necesita 5 hs.*le faltan 30 min"):
            self._reservar(_en(180))

        self.assertEqual(self._cantidad("reservas"), 0)

    def test_con_justo_cinco_horas_reserva(self):
        self._poner_saldo(self.juan, 300)

        self.assertTrue(self._reservar(_en(180)))

    def test_si_el_admin_baja_el_minimo_reserva_con_menos(self):
        reservas_socios_repo.guardar_horas_para_reservar(self.admin, 2)

        self.assertTrue(self._reservar(_en(180), miembro=self.luis, horas=1))

    def test_no_reserva_mas_horas_que_las_que_tiene(self):
        with self.assertRaisesRegex(ValueError, "no puede reservar 8 hs"):
            self._reservar(_en(180), horas=8)

    def test_solo_horas_enteras_y_hasta_el_tope(self):
        for minutos in (90, (dominio.HORAS_MAXIMAS_RESERVA_SOCIO + 1) * 60):
            self._poner_saldo(self.juan, 2000)
            with self.assertRaises(ValueError):
                reservas_socios_repo.crear_reserva_de_socio(self.ana, self.juan, self.pc1, _en(180), minutos)

    def test_pcstream_no_se_reserva_con_saldo_de_socio(self):
        with self.assertRaisesRegex(ValueError, "PCSTREAM"):
            self._reservar(_en(180), estacion="pcstream")

    def test_no_se_pisa_con_otra_reserva_de_la_misma_pc(self):
        self._reservar(_en(180))
        self._poner_saldo(self.luis, 600)

        with self.assertRaisesRegex(ValueError, "ya está reservado"):
            self._reservar(_en(240), miembro=self.luis)

    def test_un_socio_dado_de_baja_no_reserva(self):
        miembros_repo.desactivar_miembro(self.juan)

        with self.assertRaisesRegex(ValueError, "activo"):
            self._reservar(_en(180))

    def test_la_lista_de_socios_dice_quien_llega(self):
        socios = {socio["usuario"]: socio["alcanza"] for socio in reservas_socios_repo.socios_para_reservar()}

        self.assertEqual(socios, {"juan": True, "luis": False})
        self.assertEqual([socio["usuario"] for socio in reservas_socios_repo.socios_para_reservar("PEREZ")],
                         ["juan"])


class TestSiNoViene(_ConSocios):
    def test_pasada_la_tolerancia_queda_no_vino(self):
        reserva = self._reservar(_en(60))
        with conexion_db() as conexion:
            conexion.execute("UPDATE reservas SET fecha_reserva = ? WHERE id = ?",
                             (_en(-25).isoformat(timespec="seconds"), reserva))

        reservas_repo.actualizar_estados()

        # Con precio 0 no puede quedar "A reprogramar" como si hubiera pagado todo.
        self.assertEqual(self._fila(reserva)["estado"], dominio.RESERVA_NO_VINO)

    def test_no_vino_a_mano_tampoco_lo_deja_a_reprogramar(self):
        reserva = self._reservar(_en(60))

        self.assertEqual(reservas_repo.marcar_no_vino(reserva, self.ana), dominio.RESERVA_NO_VINO)

    def test_no_hay_plata_para_devolver(self):
        reserva = self._reservar(_en(60))

        with self.assertRaisesRegex(ValueError, "plata"):
            reservas_repo.devolver(reserva, self.admin, dominio.PAGO_EFECTIVO, "Se cortó la luz")


class TestCuandoLlega(_ConSocios):
    def _sesion(self, estacion_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?", (estacion_id, dominio.SESION_ACTIVA)
            ).fetchone()

    def test_su_propia_reserva_no_lo_corta_y_queda_habilitada(self):
        reserva = self._reservar(_en(60))

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertEqual((resumen["minutos_usados"], resumen["hasta_la_reserva"]), (450, None))
        fila = self._fila(reserva)
        self.assertEqual((fila["estado"], fila["estacion_habilitada_id"], fila["sesion_pc_id"], fila["estado_por"]),
                         (dominio.RESERVA_HABILITADA, self.pc1, self._sesion(self.pc1)["id"], None))
        # Ya no aparta la PC: no queda nada pendiente.
        with conexion_db() as conexion:
            self.assertEqual(reservas_horario_repo.pendientes(conexion, datetime.now()), [])

    def test_llega_tarde_dentro_de_la_tolerancia(self):
        reserva = self._reservar(_en(60))
        with conexion_db() as conexion:
            conexion.execute("UPDATE reservas SET fecha_reserva = ? WHERE id = ?",
                             (_en(-10).isoformat(timespec="seconds"), reserva))

        miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertEqual(self._fila(reserva)["estado"], dominio.RESERVA_HABILITADA)

    def test_si_entra_en_otra_pc_la_reserva_queda_usada_ahi(self):
        reserva = self._reservar(_en(60))

        miembros_repo.abrir_estacion_por_miembro(self.pc2, "juan", "clave123")

        self.assertEqual(self._fila(reserva)["estacion_habilitada_id"], self.pc2)

    def test_si_su_saldo_no_llega_a_la_hora_la_reserva_sigue_esperando(self):
        reserva = self._reservar(_en(240))
        self._poner_saldo(self.juan, 60)

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc2, "juan", "clave123")

        self.assertEqual(resumen["minutos_usados"], 60)
        self.assertEqual(self._fila(reserva)["estado"], dominio.RESERVA_PENDIENTE)

    def test_si_ese_dia_tiene_menos_del_minimo_entra_igual(self):
        reserva = self._reservar(_en(60))
        self._poner_saldo(self.juan, 90)

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        self.assertEqual(resumen["minutos_usados"], 90)
        self.assertEqual(self._fila(reserva)["estado"], dominio.RESERVA_HABILITADA)

    def test_la_reserva_de_un_socio_corta_a_otro_socio(self):
        self._reservar(_en(60))

        resumen = miembros_repo.abrir_estacion_por_miembro(self.pc1, "luis", "clave123")

        self.assertLessEqual(resumen["minutos_usados"], 60)
        self.assertIsNotNone(resumen["hasta_la_reserva"])

    def test_una_carga_que_llega_a_la_hora_tambien_la_habilita(self):
        reserva = self._reservar(_en(120))
        self._poner_saldo(self.juan, 60)
        miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")
        self.assertEqual(self._fila(reserva)["estado"], dominio.RESERVA_PENDIENTE)

        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = saldo_minutos + 180 WHERE id = ?", (self.juan,))
            sumado = miembros_repo._sumar_carga_a_la_sesion(conexion, self.juan, 180, datetime.now())

        self.assertEqual(sumado["minutos"], 180)
        self.assertEqual(self._fila(reserva)["estado"], dominio.RESERVA_HABILITADA)

    def test_desde_el_mostrador_no_se_habilita(self):
        reserva = self._reservar(_en(60))

        with self.assertRaisesRegex(ValueError, "usuario y su clave"):
            reservas_habilitar_repo.preparar_habilitacion(reserva, self.pc1)
        with self.assertRaisesRegex(ValueError, "usuario y su clave"):
            reservas_habilitar_repo.habilitar(reserva, self.ana, self.pc1, [])
        self.assertIsNone(self._sesion(self.pc1))

    def test_el_cierre_no_la_nombra_entre_las_habilitadas_sin_cobrar(self):
        self._reservar(_en(60))
        desde = datetime.now() - timedelta(minutes=1)

        miembros_repo.abrir_estacion_por_miembro(self.pc1, "juan", "clave123")

        with conexion_db() as conexion:
            self.assertEqual(turnos_ventas_repo._reservas_habilitadas_sin_cobro(
                conexion, desde.isoformat(), (datetime.now() + timedelta(minutes=1)).isoformat()), [])


class TestPantallas(_ConSocios):
    def _usuario(self, usuario_id=None):
        return usuarios_repo.obtener_usuario(usuario_id or self.ana)

    def _fila_de(self, ventana, reserva_id):
        fila = next(i for i, reserva in enumerate(ventana.reservas) if reserva["id"] == reserva_id)
        return {titulo: ventana.tabla.item(fila, columna).text() for columna, titulo in enumerate(TITULOS)}

    def test_la_lista_la_muestra_como_de_socio_y_sin_plata(self):
        reserva = self._reservar(_en(180))

        textos = self._fila_de(self._abrir(ReservasWindow(self._usuario())), reserva)

        self.assertEqual(textos["Cliente"], "Juan Pérez (socio)")
        self.assertEqual(textos["Bono"], "Saldo de socio · 2 hs")
        self.assertEqual((textos["Precio"], textos["Pagó"], textos["Falta"]), ("—", "—", "—"))
        self.assertEqual(textos["Estado"], "Pendiente · socio")

    def test_la_ventana_tiene_el_boton_de_reserva_de_socio(self):
        ventana = self._abrir(ReservasWindow(self._usuario()))

        self.assertIn("👤  RESERVA DE SOCIO", [boton.text() for boton in ventana.findChildren(QPushButton)])

    def test_habilitar_una_de_socio_explica_que_entre_con_su_usuario(self):
        reserva = self._reservar(_en(180))
        ventana = self._abrir(ReservasWindow(self._usuario()))
        ventana._cargar(elegir=reserva)

        with mock.patch("control_pcs.ui.reservas_window.mostrar_info") as aviso, \
                mock.patch("control_pcs.ui.reservas_window.DialogoHabilitarReserva") as dialogo:
            ventana._habilitar()

        dialogo.assert_not_called()
        self.assertIn("usuario y su clave", aviso.call_args.args[2])

    def test_el_formulario_muestra_en_gris_al_que_no_llega_y_reserva_sin_cobrar(self):
        dialogo = self._abrir(DialogoReservaDeSocio(self._usuario()))
        items = [dialogo.lista_socios.item(i) for i in range(dialogo.lista_socios.count())]

        self.assertTrue(items[0].text().startswith("juan"))
        self.assertTrue(items[0].flags() & Qt.ItemIsEnabled)
        self.assertIn("le faltan 3 hs", items[1].text())
        self.assertFalse(items[1].flags() & Qt.ItemIsEnabled)
        # Queda elegido el primero que puede, y no reserva más horas que su saldo.
        self.assertEqual(dialogo._socio()["id"], self.juan)
        self.assertEqual(dialogo.campo_horas.maximum(), 7)

        dialogo.combo_equipo.setCurrentIndex(dialogo.combo_equipo.findData(self.pc2))
        dialogo.campo_horas.setValue(3)
        with mock.patch("control_pcs.ui.reservas_socio_dialogo.mostrar_info"):
            dialogo._reservar()

        fila = self._fila(dialogo.reserva_id)
        self.assertEqual((fila["miembro_id"], fila["estacion_id"], fila["minutos"]), (self.juan, self.pc2, 180))
        self.assertEqual(self._cantidad("ventas"), 0)

    def test_la_lupa_filtra_y_sin_socio_no_reserva(self):
        dialogo = self._abrir(DialogoReservaDeSocio(self._usuario()))
        dialogo.campo_buscar.setText("luis")

        self.assertIsNone(dialogo._socio())
        with mock.patch("control_pcs.ui.reservas_socio_dialogo.mostrar_error") as error:
            dialogo._reservar()

        error.assert_called_once()
        self.assertEqual(self._cantidad("reservas"), 0)

    def test_el_formulario_solo_ofrece_pcs_comunes(self):
        dialogo = self._abrir(DialogoReservaDeSocio(self._usuario()))
        equipos = [dialogo.combo_equipo.itemText(i) for i in range(dialogo.combo_equipo.count())]

        self.assertEqual(equipos, [dominio.NOMBRE_RESERVA_CUALQUIER_PC, "PC1", "PC2"])

    def test_en_miembros_el_admin_cambia_el_saldo_para_reservar(self):
        ventana = self._abrir(MiembrosWindow(self._usuario(self.admin)))
        self.assertTrue(ventana.boton_saldo_para_reserva.isEnabled())

        dialogo = self._abrir(DialogoSaldoParaReserva(self._usuario(self.admin)))
        self.assertEqual(dialogo.campo_horas.value(), 5)
        dialogo.campo_horas.setValue(8)
        dialogo._guardar()

        self.assertEqual(reservas_socios_repo.horas_para_reservar(), 8)

    def test_en_miembros_una_empleada_lo_ve_en_gris_con_candado(self):
        ventana = self._abrir(MiembrosWindow(self._usuario()))

        self.assertFalse(ventana.boton_saldo_para_reserva.isEnabled())
        self.assertIn("🔒", ventana.boton_saldo_para_reserva.text())
