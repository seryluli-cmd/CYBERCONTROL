"""
tests/test_pcs_cometa.py
========================
El cometa que da vueltas por el borde del fondo negro del mosaico de Control de
PCs (pedido del dueño, 2026-10-23): va pegado al borde, como las agujas del
reloj, no tapa los clics y no gasta nada cuando la pantalla no se ve.
"""

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QFrame  # noqa: E402

import dominio  # noqa: E402
from control_pcs.ui import pcs_cometa  # noqa: E402
from control_pcs.ui.pcs_cometa import CometaEnElBorde  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


class TestCometa(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.marco = QFrame()
        self.marco.resize(900, 500)
        # A la vista (sin abrir ventanas): Qt no avisa los cambios de tamaño de lo que no se ve.
        self.marco.setAttribute(Qt.WA_DontShowOnScreen)
        self.marco.show()
        self.addCleanup(self.marco.deleteLater)
        self.cometa = CometaEnElBorde(self.marco)
        self.cometa.detener()   # las pruebas lo mueven a mano

    def test_cubre_el_fondo_negro_y_lo_sigue_si_cambia_de_tamano(self):
        self.assertEqual(self.cometa.geometry(), self.marco.rect())
        self.marco.resize(1200, 640)
        self.assertEqual(self.cometa.geometry(), self.marco.rect())

    def test_deja_pasar_los_clics(self):
        self.assertTrue(self.cometa.testAttribute(Qt.WA_TransparentForMouseEvents))

    def test_va_pegado_al_borde(self):
        adentro = QRectF(self.marco.rect())
        for paso in range(20):
            self.cometa.avance = paso / 20
            for punto in self.cometa.puntos():
                self.assertTrue(adentro.contains(punto))
                al_borde = min(punto.x(), punto.y(), adentro.width() - punto.x(), adentro.height() - punto.y())
                # En las esquinas redondeadas entra un poco más: hasta 0,3 del radio.
                self.assertLessEqual(al_borde, pcs_cometa.DISTANCIA_AL_BORDE + 0.3 * pcs_cometa.RADIO_ESQUINAS + 0.5)

    def test_da_la_vuelta_como_las_agujas_del_reloj(self):
        cabezas = []
        for paso in range(100):
            self.cometa.avance = paso / 100
            cabezas.append(self.cometa.puntos()[0])
        # Con la y para abajo (la pantalla), una vuelta como las agujas del reloj da área positiva.
        area = sum(a.x() * b.y() - b.x() * a.y() for a, b in zip(cabezas, cabezas[1:] + cabezas[:1]))
        self.assertGreater(area, 0)

    def test_la_cola_queda_atras_de_la_cabeza(self):
        self.cometa.avance = 0.3
        cabeza, segundo = self.cometa.puntos()[:2]
        self.cometa.avance = 0.3 + pcs_cometa.LARGO_COLA / pcs_cometa.TRAMOS_COLA
        # Un rato después, donde estaba la cabeza pasa la cola.
        despues = self.cometa.puntos()[1]
        self.assertAlmostEqual(despues.x(), cabeza.x(), places=3)
        self.assertAlmostEqual(despues.y(), cabeza.y(), places=3)
        self.assertNotEqual(segundo, cabeza)

    def test_avanza_y_vuelve_a_pintar_solo_un_pedacito(self):
        self.cometa._avanzar()
        self.assertGreater(self.cometa.avance, 0)
        zona = self.cometa._zona_pintada
        self.assertLess(zona.width() * zona.height(), self.marco.width() * self.marco.height() / 4)
        _app.processEvents()   # se pinta sin errores

    def test_si_no_se_ve_no_hace_nada(self):
        self.marco.hide()
        self.cometa._avanzar()
        self.assertEqual(self.cometa.avance, 0)


class TestEnLaPantallaDePcs(BaseConBaseTemporal):
    def test_esta_sobre_el_fondo_negro_y_se_frena_al_cerrar(self):
        operador = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        panel = PanelControlPcs(usuarios_repo.obtener_usuario(operador))
        self.addCleanup(panel.deleteLater)

        self.assertEqual(panel.cometa.parentWidget().objectName(), "marcoMosaico")
        self.assertTrue(panel.cometa._timer.isActive())
        panel.detener_actualizacion()
        self.assertFalse(panel.cometa._timer.isActive())
