"""
tests/test_ordenar_saldos.py
============================
ORDENAR SALDOS (botón de Miembros que solo ve el Admin; pedido del dueño,
2026-11-01: una empleada le cargó horas a un socio que no era). Un Admin con la
contraseña corrige el saldo de un socio (sumar, restar o pasar a otro) sin crear
ventas ni tocar la caja, y cada corrección queda anotada con quién y cuándo.

La contraseña real no se escribe acá (el repo es público): cada prueba usa una
de prueba. Las pantallas se prueban sin abrir ninguna ventana (plataforma
"offscreen" de Qt).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from control_pcs.repositories import ajustes_saldo_repo, bonos_miembro_repo, miembros_repo, pcs_repo  # noqa: E402
from control_pcs.ui.miembros_window import MiembrosWindow  # noqa: E402
from control_pcs.ui.ordenar_saldos_window import OrdenarSaldosWindow, texto_del_cambio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import articulos_repo, usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

CLAVE = "clave-de-prueba"
# La del programa, leída antes de que una prueba la cambie por la de prueba.
CLAVE_REAL = ajustes_saldo_repo.CLAVE_ORDENAR_SALDOS
TRES_HORAS = 180


class BaseOrdenarSaldos(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        parche = mock.patch.object(ajustes_saldo_repo, "CLAVE_ORDENAR_SALDOS", database.hash_clave(CLAVE))
        parche.start()
        self.addCleanup(parche.stop)
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.empleada = usuarios_repo.crear_usuario("Lucia", "1234", dominio.ROL_EMPLEADA)
        # El caso del dueño: a "juan" le cargaron las 3 horas que eran de "pedro".
        self.juan = miembros_repo.crear_miembro("juan", "clave123")
        self.pedro = miembros_repo.crear_miembro("pedro", "clave123")
        self.bono = bonos_miembro_repo.crear_bono("3 horas", TRES_HORAS, 3000)
        miembros_repo.cargar_saldo_por_bono(
            self.juan, self.bono, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3000}], self.empleada)

    def saldo(self, socio):
        return miembros_repo.obtener_miembro(socio)["saldo_minutos"]

    def ajustes(self):
        with conexion_db() as conexion:
            return conexion.execute("SELECT * FROM ajustes_saldo_miembro ORDER BY id").fetchall()

    def foto_de_la_plata(self):
        """Todo lo que mira la caja (y el ledger de saldo): una corrección no lo cambia."""
        with conexion_db() as conexion:
            return {tabla: conexion.execute(f"SELECT * FROM {tabla} ORDER BY 1").fetchall()
                    for tabla in ("ventas", "venta_pagos", "ventas_caja", "movimientos_saldo_miembro")}


class TestSumarYRestar(BaseOrdenarSaldos):
    def test_restar_saca_del_saldo_y_lo_deja_anotado(self):
        resultado = ajustes_saldo_repo.restar(self.admin, self.juan, TRES_HORAS, CLAVE)

        self.assertEqual(resultado, {"saldo_anterior": TRES_HORAS, "saldo_nuevo": 0})
        self.assertEqual(self.saldo(self.juan), 0)
        [ajuste] = self.ajustes()
        self.assertEqual((ajuste["miembro_id"], ajuste["usuario_id"], ajuste["saldo_anterior"], ajuste["saldo_nuevo"],
                          ajuste["otro_miembro_id"]), (self.juan, self.admin, TRES_HORAS, 0, None))

    def test_sumar_agrega_al_saldo(self):
        resultado = ajustes_saldo_repo.sumar(self.admin, self.pedro, 90, CLAVE)

        self.assertEqual(resultado, {"saldo_anterior": 0, "saldo_nuevo": 90, "sumado_a_la_sesion": None})
        self.assertEqual(self.saldo(self.pedro), 90)

    def test_no_crea_ventas_ni_toca_la_caja_ni_el_ledger(self):
        antes = self.foto_de_la_plata()
        ajustes_saldo_repo.restar(self.admin, self.juan, 60, CLAVE)
        ajustes_saldo_repo.sumar(self.admin, self.pedro, 60, CLAVE)
        ajustes_saldo_repo.pasar(self.admin, self.juan, self.pedro, 30, CLAVE)
        self.assertEqual(self.foto_de_la_plata(), antes)

    def test_no_deja_un_saldo_en_negativo(self):
        with self.assertRaises(ValueError) as error:
            ajustes_saldo_repo.restar(self.admin, self.juan, TRES_HORAS + 30, CLAVE)
        self.assertIn("3 h de saldo", str(error.exception))
        self.assertEqual((self.saldo(self.juan), self.ajustes()), (TRES_HORAS, []))

    def test_el_tiempo_tiene_que_ser_mas_de_cero(self):
        for minutos in (0, -30, 1.5, "60", None, True):
            with self.subTest(minutos=minutos):
                with self.assertRaises(ValueError):
                    ajustes_saldo_repo.sumar(self.admin, self.pedro, minutos, CLAVE)
        self.assertEqual(self.ajustes(), [])

    def test_un_socio_que_no_existe(self):
        with self.assertRaises(ValueError):
            ajustes_saldo_repo.sumar(self.admin, 9999, 30, CLAVE)


class TestPasarAOtroSocio(BaseOrdenarSaldos):
    def test_pasa_las_horas_de_la_cuenta_equivocada_a_la_correcta(self):
        resultado = ajustes_saldo_repo.pasar(self.admin, self.juan, self.pedro, TRES_HORAS, CLAVE)

        self.assertEqual(resultado["desde"], {"saldo_anterior": TRES_HORAS, "saldo_nuevo": 0})
        self.assertEqual(resultado["hacia"], {"saldo_anterior": 0, "saldo_nuevo": TRES_HORAS,
                                              "sumado_a_la_sesion": None})
        self.assertEqual((self.saldo(self.juan), self.saldo(self.pedro)), (0, TRES_HORAS))
        sacado, sumado = self.ajustes()
        self.assertEqual((sacado["miembro_id"], sacado["otro_miembro_id"]), (self.juan, self.pedro))
        self.assertEqual((sumado["miembro_id"], sumado["otro_miembro_id"]), (self.pedro, self.juan))
        self.assertEqual(sacado["fecha"], sumado["fecha"])

    def test_si_no_le_alcanza_no_pasa_nada_a_ninguno(self):
        with self.assertRaises(ValueError):
            ajustes_saldo_repo.pasar(self.admin, self.juan, self.pedro, TRES_HORAS + 30, CLAVE)
        self.assertEqual((self.saldo(self.juan), self.saldo(self.pedro), self.ajustes()), (TRES_HORAS, 0, []))

    def test_no_se_pasa_al_mismo_socio(self):
        with self.assertRaises(ValueError):
            ajustes_saldo_repo.pasar(self.admin, self.juan, self.juan, 30, CLAVE)
        self.assertEqual(self.ajustes(), [])

    def test_la_lista_de_correcciones_dice_de_quien_vino_y_a_quien_fue(self):
        ajustes_saldo_repo.pasar(self.admin, self.juan, self.pedro, TRES_HORAS, CLAVE)
        ajustes_saldo_repo.restar(self.admin, self.pedro, 30, CLAVE)

        ultimos = ajustes_saldo_repo.listar_ajustes()

        self.assertEqual([(a["socio"], a["minutos"], a["otro_socio"], a["operador"]) for a in ultimos], [
            ("pedro", -30, None, "Duenio"),
            ("pedro", TRES_HORAS, "juan", "Duenio"),
            ("juan", -TRES_HORAS, "pedro", "Duenio"),
        ])
        self.assertEqual([texto_del_cambio(a) for a in ultimos],
                         ["-30m 00s", "+3h 00m, pasado de juan", "-3h 00m, pasado a pedro"])


class TestSocioJugando(BaseOrdenarSaldos):
    """Lo que se le suma a un socio que está usando una PC pasa a esa sesión, como una carga."""

    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")
        miembros_repo.cargar_saldo_por_bono(
            self.pedro, bonos_miembro_repo.crear_bono("Media hora", 30, 500),
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 500}], self.empleada)
        self.sesion_id = miembros_repo.abrir_estacion_por_miembro(self.pc, "pedro", "clave123")["sesion_id"]

    def minutos_que_le_quedan(self):
        with conexion_db() as conexion:
            fin = conexion.execute("SELECT fecha_fin_prevista FROM sesiones_pc WHERE id = ?",
                                   (self.sesion_id,)).fetchone()["fecha_fin_prevista"]
        return dominio.segundos_restantes(datetime.fromisoformat(fin), datetime.now()) / 60

    def test_lo_que_se_le_pasa_corre_en_su_pc(self):
        resultado = ajustes_saldo_repo.pasar(self.admin, self.juan, self.pedro, TRES_HORAS, CLAVE)

        self.assertEqual(resultado["hacia"]["sumado_a_la_sesion"], {"estacion": "PC07", "minutos": TRES_HORAS, "guardado": 0,
                                                                    "hasta_la_reserva": None})
        self.assertEqual(self.saldo(self.pedro), 0)
        self.assertAlmostEqual(self.minutos_que_le_quedan(), 30 + TRES_HORAS, delta=1)

    def test_lo_que_ya_corre_en_la_pc_no_se_resta(self):
        with self.assertRaises(ValueError) as error:
            ajustes_saldo_repo.restar(self.admin, self.pedro, 30, CLAVE)
        self.assertIn("cerrale la sesión", str(error.exception))


class TestQuienPuede(BaseOrdenarSaldos):
    def test_una_empleada_no_puede_aunque_sepa_la_contrasena(self):
        for hacer in (lambda: ajustes_saldo_repo.sumar(self.empleada, self.pedro, 30, CLAVE),
                      lambda: ajustes_saldo_repo.restar(self.empleada, self.juan, 30, CLAVE),
                      lambda: ajustes_saldo_repo.pasar(self.empleada, self.juan, self.pedro, 30, CLAVE),
                      lambda: ajustes_saldo_repo.comprobar_clave_para_ordenar_saldos(self.empleada, CLAVE)):
            with self.assertRaises(PermissionError):
                hacer()
        self.assertEqual(self.ajustes(), [])

    def test_con_otra_contrasena_no_se_puede(self):
        for clave in ("mala", "", None):
            with self.subTest(clave=clave):
                with self.assertRaises(PermissionError):
                    ajustes_saldo_repo.restar(self.admin, self.juan, 30, clave)
        self.assertEqual(self.saldo(self.juan), TRES_HORAS)

    def test_un_admin_dado_de_baja_con_la_ventana_abierta_no_sigue(self):
        otro_admin = usuarios_repo.crear_usuario("Otro", "1234", dominio.ROL_ADMIN)
        ajustes_saldo_repo.comprobar_clave_para_ordenar_saldos(otro_admin, CLAVE)
        usuarios_repo.desactivar_usuario(otro_admin)
        with self.assertRaises(PermissionError):
            ajustes_saldo_repo.restar(otro_admin, self.juan, 30, CLAVE)

    def test_la_contrasena_real_es_la_de_ordenar_stock(self):
        # Pedido del dueño: "como la del botón ORDENAR Stock" (la de antes del parche de prueba).
        self.assertEqual(CLAVE_REAL, articulos_repo.CLAVE_ORDENAR_STOCK)


class BasePantallas(BaseOrdenarSaldos):
    def abrir(self, ventana):
        self.addCleanup(ventana.deleteLater)
        ventana.show()
        _app.processEvents()
        return ventana

    def ventana_de_saldos(self):
        return self.abrir(OrdenarSaldosWindow(None, self.admin, CLAVE))

    @staticmethod
    def elegir(ventana, usuario):
        ventana.lista.setCurrentRow(next(i for i, s in enumerate(ventana.socios) if s["usuario"] == usuario))


class TestBotonEnMiembros(BasePantallas):
    def test_solo_lo_ve_un_admin(self):
        for usuario, lo_ve in ((self.admin, True), (self.empleada, False)):
            with self.subTest(usuario=usuario):
                ventana = self.abrir(MiembrosWindow(usuarios_repo.obtener_usuario(usuario)))
                self.assertEqual(ventana.boton_ordenar_saldos.isVisible(), lo_ve)
                self.assertTrue(ventana.boton_ordenar_saldos.text().endswith("ORDENAR SALDOS"))

    def apretar_con(self, respuesta):
        ventana = self.abrir(MiembrosWindow(usuarios_repo.obtener_usuario(self.admin)))
        with mock.patch("control_pcs.ui.ordenar_saldos_window.QInputDialog.getText", return_value=respuesta), \
                mock.patch("control_pcs.ui.ordenar_saldos_window.OrdenarSaldosWindow") as pantalla, \
                mock.patch("ui.utils.mostrar_error") as error:
            ventana.boton_ordenar_saldos.click()
        return pantalla, error

    def test_con_la_contrasena_abre_la_ventana(self):
        pantalla, error = self.apretar_con((CLAVE, True))
        pantalla.assert_called_once()
        self.assertEqual(pantalla.call_args.args[1:], (self.admin, CLAVE))
        error.assert_not_called()

    def test_con_otra_contrasena_no_abre_y_avisa(self):
        pantalla, error = self.apretar_con(("mala", True))
        pantalla.assert_not_called()
        error.assert_called_once()

    def test_si_cancela_no_pasa_nada(self):
        pantalla, error = self.apretar_con(("", False))
        pantalla.assert_not_called()
        error.assert_not_called()


class TestVentana(BasePantallas):
    def escribir(self, ventana, horas, minutos=0):
        ventana.campo_horas.setValue(horas)
        ventana.campo_minutos.setValue(minutos)

    def test_muestra_el_saldo_del_elegido(self):
        ventana = self.ventana_de_saldos()
        self.elegir(ventana, "juan")
        self.assertEqual((ventana.etiqueta_usuario.text(), ventana.cifra_saldo.valor.text()), ("juan", "3h 00m"))
        self.assertFalse(ventana.aviso_jugando.isVisible())

    def test_restar_pregunta_antes_y_guarda(self):
        ventana = self.ventana_de_saldos()
        self.elegir(ventana, "juan")
        self.escribir(ventana, 1, 30)
        with mock.patch("control_pcs.ui.ordenar_saldos_window.confirmar", return_value=False):
            ventana.boton_restar.click()
        self.assertEqual(self.saldo(self.juan), TRES_HORAS)

        with mock.patch("control_pcs.ui.ordenar_saldos_window.confirmar", return_value=True) as pregunta:
            ventana.boton_restar.click()
        self.assertIn("1h 30m", pregunta.call_args.args[2])
        self.assertEqual(self.saldo(self.juan), 90)
        self.assertEqual(ventana.cifra_saldo.valor.text(), "1h 30m")
        self.assertEqual(ventana.tabla.rowCount(), 1)
        self.assertEqual(ventana.tabla.item(0, 2).text(), "-1h 30m")
        # Los campos quedan en cero para la próxima.
        self.assertEqual((ventana.campo_horas.value(), ventana.campo_minutos.value()), (0, 0))

    def test_sin_tiempo_escrito_avisa_y_no_pregunta(self):
        ventana = self.ventana_de_saldos()
        with mock.patch("control_pcs.ui.ordenar_saldos_window.confirmar") as pregunta, \
                mock.patch("control_pcs.ui.ordenar_saldos_window.mostrar_error") as error:
            ventana.boton_sumar.click()
        pregunta.assert_not_called()
        error.assert_called_once()

    def test_pasar_a_otro_socio(self):
        ventana = self.ventana_de_saldos()
        self.elegir(ventana, "juan")
        self.escribir(ventana, 3)
        elegido = miembros_repo.obtener_miembro(self.pedro)

        def elegir_a_pedro(dialogo):
            # La lista de a quién pasarle no tiene a juan.
            self.assertEqual([s["usuario"] for s in dialogo.socios], ["pedro"])
            dialogo.elegido = elegido
            return True

        with mock.patch("control_pcs.ui.ordenar_saldos_window.DialogoElegirSocio.exec", elegir_a_pedro), \
                mock.patch("control_pcs.ui.ordenar_saldos_window.confirmar", return_value=True):
            ventana.boton_pasar.click()
        self.assertEqual((self.saldo(self.juan), self.saldo(self.pedro)), (0, TRES_HORAS))
        self.assertTrue(ventana.etiqueta_estado.text().startswith("Pasado: 3h 00m de juan"))

    def test_un_error_del_repo_se_muestra_y_no_cambia_nada(self):
        ventana = self.ventana_de_saldos()
        self.elegir(ventana, "pedro")
        self.escribir(ventana, 1)
        with mock.patch("control_pcs.ui.ordenar_saldos_window.confirmar", return_value=True), \
                mock.patch("ui.utils.mostrar_error") as error:
            ventana.boton_restar.click()
        error.assert_called_once()
        self.assertEqual(self.ajustes(), [])
