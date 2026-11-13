"""
tests/test_ofertas_ui.py
========================
Las ofertas 2x1 y 50% en pantalla (plataforma "offscreen" de Qt, sin abrir ventanas):
el panel de la PC con la maqueta P1 (la etiqueta en el botón, lo que se cobra con la
oferta y el cartel de arriba) y que el cobro lleve la hora de los precios que se
mostraron; la ventana de Ofertas con la maqueta B (armar una tocando la semana y los
bonos, el aviso cuando choca con otra, terminarla y usarla de nuevo, avisar antes de
cerrar con cambios sin guardar) y su tarjeta en Configuración ADMIN, solo del
Administrador. Las cuentas y las reglas están en tests/test_ofertas.py.

Las ofertas de estas pruebas corren TODA la semana: así están andando a cualquier hora
en que se corran las pruebas.
"""

import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel, QPushButton  # noqa: E402

import dominio  # noqa: E402
import turnos  # noqa: E402
from control_pcs.repositories import ofertas_repo, pcs_repo, playstation_repo  # noqa: E402
from control_pcs.ui.ofertas_window import OfertasWindow  # noqa: E402
from control_pcs.ui.pcs_detalle import PanelDetalleEstacion  # noqa: E402
from control_pcs.ui.pcs_lista_de_bonos import cartel_de_ofertas  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from ui.configuracion_admin_window import ConfiguracionAdminWindow  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

PC = dominio.EQUIPO_RESERVA_PC
VIE, SAB = 4, 5
NOCHE = dominio.TURNO_NOCHE


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


class _ConOfertas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.estacion = pcs_repo.crear_estacion("PC 1")
        self.una_hora = pcs_repo.crear_bono("1 Hora", 60, 5000.0)
        self.promo3 = pcs_repo.crear_bono("Promo 3hs", 180, 6700.0)
        self.ps5 = playstation_repo.crear_bono(self.admin, "1 Hora PS5", 60, 4000.0)
        self.hoy = turnos.dia_en_que_empezo_el_turno(datetime.now())
        # Un cartel abierto de verdad dejaría la prueba esperando: se anotan.
        self.errores = []
        for donde in ("ui.utils.mostrar_error", "control_pcs.ui.ofertas_window.mostrar_info"):
            parche = mock.patch(donde, side_effect=lambda *a, **k: self.errores.append(a[1:]))
            parche.start()
            self.addCleanup(parche.stop)

    def toda_la_semana(self, tipo=dominio.OFERTA_2X1, bonos=None, nombre="Toda la semana"):
        return ofertas_repo.guardar_oferta(
            self.admin, None, nombre, tipo, self.hoy, self.hoy + timedelta(days=6),
            ofertas_repo.franjas_de_la_semana(), bonos if bonos is not None else [(PC, self.promo3)],
        )

    def usuario(self, usuario_id):
        return usuarios_repo.obtener_usuario(usuario_id)


class TestElPanelDeLaPc(_ConOfertas):
    def panel(self):
        panel = PanelDetalleEstacion(self.usuario(self.toby), lambda: None)
        self.addCleanup(panel.deleteLater)
        panel.mostrar(next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == self.estacion))
        return panel

    def test_el_bono_con_oferta_lleva_la_etiqueta_y_lo_que_se_cobra_y_arriba_el_cartel(self):
        self.toda_la_semana()
        panel = self.panel()

        con_oferta = panel.lista_pc.grupo.button(self.promo3)
        self.assertEqual(con_oferta.property("oferta"), "naranja")
        self.assertEqual(con_oferta.text(), "Promo 3hs — 6 h · $ 6.700")
        self.assertEqual(con_oferta.findChild(QLabel, "insigniaOferta").text(), "2x1")
        sin_oferta = panel.lista_pc.grupo.button(self.una_hora)
        self.assertIsNone(sin_oferta.property("oferta"))
        self.assertEqual(sin_oferta.text(), "1 Hora — $ 5.000")
        self.assertFalse(panel.cartel_oferta.isHidden())
        self.assertIn("2x1 HASTA", panel.cartel_oferta.text())
        self.assertIn("«Toda la semana» en 1 bono de PC", panel.cartel_oferta.text())
        self.assertEqual(panel.cartel_oferta.property("tono"), "naranja")

    def test_el_50_va_en_violeta_y_a_mitad_de_precio(self):
        self.toda_la_semana(tipo=dominio.OFERTA_MITAD)
        panel = self.panel()

        boton = panel.lista_pc.grupo.button(self.promo3)
        self.assertEqual((boton.property("oferta"), boton.text()), ("violeta", "Promo 3hs — 3 h · $ 3.350"))
        self.assertEqual(panel.cartel_oferta.property("tono"), "violeta")

    def test_sin_oferta_en_los_bonos_del_equipo_elegido_no_hay_cartel(self):
        self.toda_la_semana()
        panel = self.panel()
        panel.mostrar(playstation_repo.estado())
        self.assertTrue(panel.cartel_oferta.isHidden())

    def test_una_oferta_pausada_no_se_ve(self):
        oferta_id = self.toda_la_semana()
        ofertas_repo.pausar_oferta(self.admin, oferta_id)
        panel = self.panel()
        self.assertEqual(panel.lista_pc.grupo.button(self.promo3).text(), "Promo 3hs — $ 6.700")
        self.assertTrue(panel.cartel_oferta.isHidden())

    def test_el_cartel_no_cuenta_un_bono_dado_de_baja(self):
        # Revisión del 13/11: el cartel prometía la oferta en un bono que ya no tiene botón.
        self.toda_la_semana(bonos=[(PC, self.promo3), (PC, self.una_hora)])
        pcs_repo.desactivar_bono(self.una_hora)
        self.assertIn("en 1 bono de PC", self.panel().cartel_oferta.text())
        pcs_repo.desactivar_bono(self.promo3)
        self.assertTrue(self.panel().cartel_oferta.isHidden())

    def test_el_cartel_dice_hasta_cuando_sin_que_parezca_terminada(self):
        oferta = {"id": 1, "nombre": "Finde", "tipo": dominio.OFERTA_2X1, "bonos": [(PC, 1)]}
        viernes = datetime(2026, 11, 13)
        casos = [
            (viernes.replace(hour=15), viernes.replace(hour=22), "2x1 HASTA LAS 22:00"),
            # La Noche: "hasta las 06:00", como se dice en el local.
            (viernes.replace(hour=23), viernes.replace(hour=6) + timedelta(days=1), "2x1 HASTA LAS 06:00"),
            # Mañana más tarde que ahora: a las 15:00, "HASTA LAS 14:00" parecería terminada.
            (viernes.replace(hour=15), viernes.replace(hour=14) + timedelta(days=1), "2x1 HASTA MAÑANA A LAS 14:00"),
            (viernes.replace(hour=23), viernes.replace(hour=6) + timedelta(days=3), "2x1 HASTA EL 16/11 A LAS 06:00"),
        ]
        for ahora, fin, texto in casos:
            with self.subTest(texto):
                cartel, _ = cartel_de_ofertas([dict(oferta, hasta_el_fin=fin)], PC, ahora)
                self.assertIn(f"<b>{texto}</b>", cartel)

    def test_cobrar_con_la_oferta_cobra_lo_que_se_mostro_y_da_el_doble_de_tiempo(self):
        oferta_id = self.toda_la_semana()
        panel = self.panel()
        panel.lista_pc.grupo.button(self.promo3).click()

        with mock.patch("control_pcs.ui.pcs_detalle.cobrar", side_effect=lambda ventana, monto: _efectivo(monto)) \
                as cobrar, mock.patch.object(pcs_repo, "asignar_bono", wraps=pcs_repo.asignar_bono) as asignar:
            panel._cobrar_bono()

        cobrar.assert_called_once_with(panel, 6700.0)
        # Viaja la hora en que se leyeron los precios del panel: si la oferta termina con
        # el cobro abierto, se cobra lo que se mostró.
        self.assertEqual(asignar.call_args.kwargs["momento_del_precio"], panel._momento_de_los_precios)
        # Y el bono como se vio: si la oferta cambió mientras se cobraba, no se graba nada.
        mostrado = asignar.call_args.kwargs["bono_mostrado"]
        self.assertEqual((mostrado["precio"], mostrado["minutos"], mostrado["oferta"]["id"]), (6700.0, 360, oferta_id))
        with conexion_db() as conexion:
            vinculo = conexion.execute("SELECT minutos, oferta_id FROM sesion_bonos").fetchone()
        self.assertEqual((vinculo["minutos"], vinculo["oferta_id"]), (360, oferta_id))
        self.assertEqual(self.errores, [])


class TestLaVentanaDeOfertas(_ConOfertas):
    def ventana(self, usuario_id=None):
        ventana = OfertasWindow(self.usuario(usuario_id or self.admin))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def renglon(self, ventana, bono_id):
        return next(r for r in ventana.renglones if (r.equipo, r.bono["id"]) == (PC, bono_id))

    def armar_viernes_y_sabado_noche(self, ventana, nombre="Noche de finde"):
        ventana.boton_nueva.click()
        QTest.keyClicks(ventana.campo_nombre, nombre)
        ventana.cuadritos[(VIE, NOCHE)].click()
        ventana.cuadritos[(SAB, NOCHE)].click()
        self.renglon(ventana, self.promo3).casilla.click()

    def test_sin_ofertas_arranca_con_una_nueva(self):
        ventana = self.ventana()
        self.assertIsNone(ventana._borrador["id"])
        self.assertEqual(ventana.pastilla_estado.text(), "NUEVA")
        self.assertTrue(ventana.boton_terminar.isHidden())

    def test_se_arma_tocando_la_semana_y_los_bonos_y_se_guarda(self):
        ventana = self.ventana()
        self.armar_viernes_y_sabado_noche(ventana)

        self.assertTrue(ventana.cuadritos[(VIE, NOCHE)].isChecked())
        self.assertIn("2x1 en Promo 3hs de las PCs, los viernes y sábados en el turno Noche (22 a 06)",
                      ventana.asi_queda.text())
        self.assertEqual(self.renglon(ventana, self.promo3).despues.text(), "→  6 h · $ 6.700")
        ventana.boton_guardar.click()

        [oferta] = ofertas_repo.listar_ofertas()
        self.assertEqual((oferta["nombre"], oferta["tipo"]), ("Noche de finde", dominio.OFERTA_2X1))
        self.assertEqual(oferta["franjas"], [(VIE, NOCHE), (SAB, NOCHE)])
        self.assertEqual(oferta["bonos"], [(PC, self.promo3)])
        self.assertEqual([ficha.oferta["id"] for ficha in ventana.fichas], [oferta["id"]])
        self.assertTrue(ventana.fichas[0].isChecked())
        self.assertFalse(ventana._hay_cambios())

    def test_con_una_sola_vez_por_delante_se_ve_bien(self):
        # Revisión del 13/11: con un solo renglón Qt no lo tomaba como HTML y se veía "&nbsp;".
        ahora = datetime.now()
        ofertas_repo.guardar_oferta(self.admin, None, "Solo hoy", dominio.OFERTA_2X1, self.hoy, self.hoy,
                                    [ofertas_repo.franja_de(ahora)], [(PC, self.promo3)])
        ventana = self.ventana()
        self.assertEqual(ventana._borrador["nombre"], "Solo hoy")
        self.assertEqual(ventana.etiqueta_veces.textFormat(), Qt.RichText)
        self.assertEqual(ventana.etiqueta_veces.text().count("●"), 1)

    def test_el_50_cambia_como_queda_cada_bono(self):
        ventana = self.ventana()
        self.armar_viernes_y_sabado_noche(ventana)
        next(t for t in ventana.tarjetas_tipo if t.tipo == dominio.OFERTA_MITAD).click()
        self.assertEqual(self.renglon(ventana, self.promo3).despues.text(), "→  3 h · $ 3.350")
        self.assertEqual(ventana.cuadritos[(VIE, NOCHE)].property("tono"), "violeta")

    def test_si_choca_con_otra_avisa_y_no_guarda(self):
        self.toda_la_semana()
        ventana = self.ventana()
        self.armar_viernes_y_sabado_noche(ventana)

        with mock.patch("control_pcs.ui.ofertas_window.avisar_choque") as avisar:
            ventana.boton_guardar.click()

        avisar.assert_called_once()
        self.assertIn("«Toda la semana» ya pone 2x1 en Promo 3hs de las PCs", avisar.call_args.args[1])
        self.assertEqual(len(ofertas_repo.listar_ofertas()), 1)

    def test_terminarla_la_pasa_a_terminadas_y_se_puede_usar_de_nuevo(self):
        oferta_id = self.toda_la_semana()
        ventana = self.ventana()
        self.assertEqual(ventana._borrador["id"], oferta_id)

        with mock.patch("control_pcs.ui.ofertas_window.confirmar", return_value=True):
            ventana.boton_terminar.click()

        self.assertEqual(ofertas_repo.listar_ofertas()[0]["estado"], dominio.OFERTA_TERMINADA)
        self.assertEqual(ventana.fichas, [])
        self.assertEqual(ventana.boton_terminadas.text(), "VER TERMINADAS (1)")
        ventana.boton_terminadas.click()
        ventana.fichas[0].click()
        self.assertFalse(ventana.boton_usar_de_nuevo.isHidden())
        self.assertTrue(ventana.boton_guardar.isHidden())
        ventana.boton_usar_de_nuevo.click()
        self.assertIsNone(ventana._borrador["id"])
        self.assertEqual(ventana._borrador["nombre"], "Toda la semana")
        self.assertEqual(ventana._borrador["desde"], self.hoy)

    def test_pausar_y_reanudar(self):
        oferta_id = self.toda_la_semana()
        ventana = self.ventana()
        with mock.patch("control_pcs.ui.ofertas_window.confirmar", return_value=True):
            ventana.boton_pausar.click()
            self.assertEqual(ofertas_repo.listar_ofertas()[0]["estado"], dominio.OFERTA_PAUSADA)
            self.assertEqual(ventana.boton_pausar.text(), "REANUDAR")
            self.assertIn("PAUSADA", ventana.etiqueta_veces.text())
            ventana.boton_pausar.click()
        self.assertEqual(ofertas_repo.listar_ofertas()[0]["estado"], dominio.OFERTA_ACTIVA)
        self.assertEqual(ventana._borrador["id"], oferta_id)

    def test_una_empleada_no_la_puede_guardar(self):
        ventana = self.ventana(self.toby)
        self.armar_viernes_y_sabado_noche(ventana)
        ventana.boton_guardar.click()
        self.assertEqual(ofertas_repo.listar_ofertas(), [])
        self.assertEqual(len(self.errores), 1)

    def test_al_cerrar_con_cambios_sin_guardar_pregunta(self):
        ventana = self.ventana()
        with mock.patch("control_pcs.ui.ofertas_window.confirmar", return_value=False) as pregunta:
            ventana.reject()
            pregunta.assert_not_called()  # sin cambios, cierra sin preguntar
            QTest.keyClicks(ventana.campo_nombre, "Algo")
            ventana.reject()
            pregunta.assert_called_once()
            # Elegir otra oferta o una nueva también pregunta.
            ventana.boton_nueva.click()
            self.assertEqual(pregunta.call_count, 2)
            self.assertEqual(ventana._borrador["nombre"], "Algo")


class TestConfiguracionAdmin(_ConOfertas):
    def tarjeta(self, usuario_id):
        ventana = ConfiguracionAdminWindow(self.usuario(usuario_id))
        self.addCleanup(ventana.deleteLater)
        return next(b for b in ventana.findChildren(QPushButton) if b.accessibleName() == "Ofertas")

    def test_la_tarjeta_de_ofertas_es_solo_del_administrador(self):
        self.assertTrue(self.tarjeta(self.admin).isEnabled())
        self.assertFalse(self.tarjeta(self.toby).isEnabled())
