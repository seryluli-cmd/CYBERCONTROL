"""
tests/test_reservas_ui.py
===========================
Las pantallas de RESERVAS (control_pcs/ui/reservas_window.py y
reservas_dialogos.py) y el renglón "Reservas" de Caja y Cierre de Turno
(variante A, elegida por el dueño el 2026-10-20). Se prueban sin abrir ninguna
ventana (plataforma "offscreen"); la ventana de cobro se reemplaza por lo que
devolvería. La cuenta de la plata está en tests/test_reservas.py.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import date, datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QDate, Qt, QTime  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame, QPushButton  # noqa: E402

import dominio  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import pcs_repo, reservas_habilitar_repo, reservas_repo  # noqa: E402
from control_pcs.ui.reservas_dialogos import DialogoHabilitarReserva, DialogoNuevaReserva  # noqa: E402
from control_pcs.ui.reservas_window import COLOR_ESTADO, COLUMNA_ESTADO, ReservasWindow  # noqa: E402
from ui.caja_window import CajaWindow, CierreTurnoWindow  # noqa: E402
from ui.main_window import MainWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _manana_a_las(hora):
    return datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=hora)


class _ConUnaReserva(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.promo = pcs_repo.crear_bono("Promo 10 hs", 600, 10000.0)
        self.tres_horas = pcs_repo.crear_bono("3 horas", 180, 3000.0)

    def _usuario(self):
        return usuarios_repo.obtener_usuario(self.ana)

    def _reservar(self, monto=5000.0):
        return reservas_repo.crear_reserva(self.ana, "Juan Pérez", "", dominio.EQUIPO_RESERVA_PC, self.pc1,
                                           self.promo, _manana_a_las(10), monto, _efectivo(monto))

    def _abrir(self, ventana):
        self.addCleanup(ventana.deleteLater)
        return ventana


class TestRenglonReservas(_ConUnaReserva):
    def test_el_cierre_de_turno_las_muestra_aparte_de_alquiler_de_pcs(self):
        pcs_repo.asignar_bono(self.pc2, self.tres_horas, self.ana, _efectivo(3000.0))
        self._reservar(5000.0)

        tarjeta = self._abrir(CierreTurnoWindow(self._usuario())).tarjeta

        self.assertEqual(tarjeta.valor_pcs.text(), "$ 3.000 ef. + $ 0 dig.")
        self.assertEqual(tarjeta.valor_reservas.text(), "$ 5.000 ef. + $ 0 dig.")
        # Con espacio duro entre "$" y el número: el renglón es angosto.
        self.assertEqual(tarjeta.detalle_reservas.text(), "1 seña ($\u00a05.000)")
        # Separarlas es solo cómo se muestra: se retira todo.
        self.assertEqual(tarjeta.valor_retirar.text(), "$ 8.000")
        self.assertTrue(tarjeta.nota_reservas.isHidden())

    def test_nombra_la_que_se_habilito_sin_cobrar(self):
        reserva = self._reservar(10000.0)
        reservas_habilitar_repo.habilitar(reserva, self.ana, self.pc1, [])

        tarjeta = self._abrir(CierreTurnoWindow(self._usuario())).tarjeta

        self.assertFalse(tarjeta.nota_reservas.isHidden())
        self.assertIn(f"reserva Nº {reserva} (Juan Pérez) en PC1", tarjeta.nota_reservas.text())
        self.assertIn("Acá suma $ 0", tarjeta.nota_reservas.text())

    def test_caja_tiene_el_mismo_renglon(self):
        self._reservar(5000.0)

        caja = self._abrir(CajaWindow())

        self.assertEqual(caja.valor_reservas.text(), "$ 5.000 ef. + $ 0 dig.")
        self.assertEqual(caja.valor_pcs.text(), "$ 0 ef. + $ 0 dig.")

    def test_sin_reservas_el_renglon_chico_no_ocupa_lugar(self):
        tarjeta = self._abrir(CierreTurnoWindow(self._usuario())).tarjeta

        self.assertEqual(tarjeta.valor_reservas.text(), "$ 0 ef. + $ 0 dig.")
        self.assertTrue(tarjeta.detalle_reservas.isHidden())


class TestVentanaReservas(_ConUnaReserva):
    def test_lista_la_reserva_con_lo_que_falta(self):
        reserva = self._reservar(5000.0)

        ventana = self._abrir(ReservasWindow(self._usuario()))

        fila = [ventana.tabla.item(0, columna).text() for columna in range(ventana.tabla.columnCount())]
        self.assertEqual(fila[0], str(reserva))
        self.assertEqual(fila[2:], ["Juan Pérez", "", "PC1", "Promo 10 hs", "$ 10.000", "$ 5.000",
                                    "$ 5.000", "Pendiente"])

    def test_no_vino_pregunta_y_la_deja_terminada(self):
        reserva = self._reservar(5000.0)
        ventana = self._abrir(ReservasWindow(self._usuario()))
        ventana.tabla.selectRow(0)

        with mock.patch("control_pcs.ui.reservas_window.confirmar", return_value=True) as pregunta:
            ventana._no_vino()

        self.assertIn("la pierde", pregunta.call_args.args[2])
        self.assertEqual(reservas_repo.obtener_reserva(reserva)["estado"], dominio.RESERVA_NO_VINO)
        self.assertEqual(ventana.tabla.item(0, 9).text(), "No vino · perdió la seña")

    def test_una_empleada_no_devuelve_plata(self):
        self._reservar(5000.0)
        ventana = self._abrir(ReservasWindow(self._usuario()))
        ventana.tabla.selectRow(0)

        with mock.patch("control_pcs.ui.reservas_window.mostrar_error") as error, \
                mock.patch("control_pcs.ui.reservas_window.DialogoDevolver") as dialogo:
            ventana._devolver()

        self.assertIn("solo el Administrador", error.call_args.args[2])
        dialogo.assert_not_called()

    def test_la_cabecera_cuenta_las_que_esperan_y_las_que_hay_que_reprogramar(self):
        # Diseño del 2026-10-26 (maqueta "A"): pastillas en la cabecera oscura.
        self._reservar(5000.0)  # mañana: espera, pero no es de hoy
        pagada = reservas_repo.crear_reserva(self.ana, "Marta", "", dominio.EQUIPO_RESERVA_PC, self.pc2,
                                             self.tres_horas, _manana_a_las(10), 3000.0, _efectivo(3000.0))
        reservas_repo.marcar_no_vino(pagada, self.ana)  # pagó todo: queda A reprogramar

        ventana = self._abrir(ReservasWindow(self._usuario()))

        self.assertEqual(ventana.pastilla_hoy.text(), "HOY  0")
        self.assertEqual(ventana.pastilla_esperan.text(), "ESPERAN  1")
        self.assertEqual(ventana.pastilla_a_reprogramar.text(), "A REPROGRAMAR  1")
        self.assertFalse(ventana.pastilla_a_reprogramar.isHidden())

    def test_las_que_esperan_esconde_las_terminadas(self):
        self._reservar(5000.0)
        sena = reservas_repo.crear_reserva(self.ana, "Marta", "", dominio.EQUIPO_RESERVA_PC, self.pc2,
                                           self.tres_horas, _manana_a_las(10), 1000.0, _efectivo(1000.0))
        reservas_repo.marcar_no_vino(sena, self.ana)  # dejó seña: la pierde y termina
        ventana = self._abrir(ReservasWindow(self._usuario()))
        todas, las_que_esperan = ventana.findChild(QFrame, "pistaSegmentos").findChildren(QPushButton)
        self.assertEqual(ventana.tabla.rowCount(), 2)
        self.assertTrue(ventana.pastilla_a_reprogramar.isHidden())

        las_que_esperan.click()
        self.assertEqual([ventana.tabla.item(0, 2).text(), ventana.tabla.rowCount()], ["Juan Pérez", 1])

        todas.click()
        self.assertEqual(ventana.tabla.rowCount(), 2)

    def test_el_estado_lleva_su_color_y_el_texto_de_siempre(self):
        self._reservar(5000.0)

        ventana = self._abrir(ReservasWindow(self._usuario()))

        estado = ventana.tabla.item(0, COLUMNA_ESTADO)
        self.assertEqual(estado.text(), "Pendiente")
        self.assertEqual(estado.data(Qt.UserRole), COLOR_ESTADO[dominio.RESERVA_PENDIENTE])


class TestDialogos(_ConUnaReserva):
    def test_nueva_reserva_cobra_la_mitad_y_la_guarda(self):
        dialogo = self._abrir(DialogoNuevaReserva(self._usuario()))
        dialogo.campo_cliente.setText("Marta")
        manana = _manana_a_las(10)
        dialogo.campo_dia.setDate(QDate(manana.year, manana.month, manana.day))
        dialogo.campo_hora.setTime(QTime(10, 0))
        dialogo.combo_equipo.setCurrentIndex(dialogo.combo_equipo.findText("PC2"))
        dialogo.combo_bono.setCurrentIndex(1)  # Promo 10 hs (van por minutos)

        self.assertEqual(dialogo.boton_cobrar.text(), "Cobrar $ 5.000")
        with mock.patch("control_pcs.ui.reservas_dialogos.cobrar", return_value=_efectivo(5000.0)) as cobro, \
                mock.patch("control_pcs.ui.reservas_dialogos.mostrar_info"):
            dialogo.boton_cobrar.click()

        cobro.assert_called_once()
        self.assertEqual(cobro.call_args.args[1], 5000.0)
        datos = reservas_repo.obtener_reserva(dialogo.reserva_id)
        self.assertEqual((datos["cliente"], datos["equipo_nombre"], datos["pagado"], datos["fecha_reserva"]),
                         ("Marta", "PC2", 5000.0, manana.isoformat()))

    def test_si_la_reserva_no_se_puede_guardar_no_se_abre_el_cobro(self):
        self._reservar(5000.0)  # PC1, mañana de 10 a 20
        dialogo = self._abrir(DialogoNuevaReserva(self._usuario()))
        dialogo.campo_cliente.setText("Marta")
        manana = _manana_a_las(10)
        dialogo.campo_dia.setDate(QDate(manana.year, manana.month, manana.day))
        dialogo.campo_hora.setTime(QTime(12, 0))
        dialogo.combo_equipo.setCurrentIndex(dialogo.combo_equipo.findText("PC1"))

        with mock.patch("control_pcs.ui.reservas_dialogos.cobrar") as cobro, \
                mock.patch("ui.utils.mostrar_error") as error:
            dialogo.boton_cobrar.click()

        cobro.assert_not_called()
        self.assertIn("ya está reservado", error.call_args.args[2])

    def test_habilitar_con_sena_cobra_el_resto(self):
        reserva = self._reservar(5000.0)
        dialogo = self._abrir(DialogoHabilitarReserva(self._usuario(), reserva))

        self.assertEqual(dialogo.combo_lugar.currentText(), "PC1  (la reservada)  (sin conexión)")
        self.assertEqual(dialogo.boton_habilitar.text(), "Cobrar $ 5.000 y habilitar")
        with mock.patch("control_pcs.ui.reservas_dialogos.cobrar", return_value=_efectivo(5000.0)) as cobro, \
                mock.patch("control_pcs.ui.reservas_dialogos.mostrar_info"):
            dialogo.boton_habilitar.click()

        self.assertEqual(cobro.call_args.args[1], 5000.0)
        self.assertEqual(reservas_repo.obtener_reserva(reserva)["habilitada_en"], "PC1")

    def test_habilitar_una_ya_pagada_no_abre_el_cobro(self):
        reserva = self._reservar(10000.0)
        dialogo = self._abrir(DialogoHabilitarReserva(self._usuario(), reserva))

        self.assertEqual(dialogo.boton_habilitar.text(), "Habilitar PC1")
        with mock.patch("control_pcs.ui.reservas_dialogos.cobrar") as cobro, \
                mock.patch("control_pcs.ui.reservas_dialogos.mostrar_info"):
            dialogo.boton_habilitar.click()

        cobro.assert_not_called()
        self.assertEqual(reservas_repo.obtener_reserva(reserva)["estado"], dominio.RESERVA_HABILITADA)


class TestBotonDeLaBarra(_ConUnaReserva):
    def test_reservas_esta_en_la_barra_despues_de_miembros(self):
        ventana = MainWindow(self._usuario(), lambda: None)
        self.addCleanup(ventana.deleteLater)
        self.addCleanup(ventana.panel_pcs.detener_actualizacion)

        textos = [boton.text() for boton in ventana.findChild(QFrame, "encabezadoInicio").findChildren(QPushButton)]

        self.assertEqual(textos[textos.index("🧑  MIEMBROS") + 1], "📅  RESERVAS")
