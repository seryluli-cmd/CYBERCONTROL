"""
tests/test_cuenta_pc.py
=======================
La Cuenta de la PC (pedido del dueño, 2026-10-25): lo que pide un cliente que
está jugando (un pancho, más tiempo) se anota en la cuenta de su sesión, su PC
titila en fucsia y se cobra después, todo junto. Ver cuentas_pc_repo.
"""

import unittest
from datetime import datetime
from unittest import mock

import database
import dominio
from admin_remoto import lista_blanca
from control_pcs.repositories import (
    bonos_miembro_repo, cuentas_pc_repo, miembros_repo, pcs_repo, pcstream_repo, reintegros_repo,
)
from database import conexion_db
from repositories import articulos_repo, turnos_repo, usuarios_repo
from base import BaseConBaseTemporal

EFECTIVO, DIGITAL = dominio.PAGO_EFECTIVO, dominio.PAGO_DIGITAL


def _pagos(*filas):
    return [{"metodo": metodo, "monto": monto} for metodo, monto in filas]


class TestRepartirPagos(unittest.TestCase):
    def test_cada_venta_se_llena_con_el_efectivo_primero(self):
        repartidos = dominio.repartir_pagos(_pagos((DIGITAL, 1000), (EFECTIVO, 1300)), [1200, 1100])
        self.assertEqual(repartidos, [_pagos((EFECTIVO, 1200)), _pagos((EFECTIVO, 100), (DIGITAL, 1000))])

    def test_cada_medio_suma_lo_mismo_que_se_cobro(self):
        repartidos = dominio.repartir_pagos(_pagos((EFECTIVO, 700.5), (DIGITAL, 299.5)), [333.33, 333.33, 333.34])
        por_medio = {}
        for filas in repartidos:
            for fila in filas:
                por_medio[fila["metodo"]] = round(por_medio.get(fila["metodo"], 0) + fila["monto"], 2)
        self.assertEqual(por_medio, {EFECTIVO: 700.5, DIGITAL: 299.5})
        self.assertEqual([round(sum(f["monto"] for f in filas), 2) for filas in repartidos], [333.33, 333.33, 333.34])

    def test_lo_cobrado_tiene_que_coincidir(self):
        with self.assertRaises(ValueError):
            dominio.repartir_pagos(_pagos((EFECTIVO, 1000)), [1200])


class BaseCuenta(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.operador = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Jefe", "clave-jefe", dominio.ROL_ADMIN)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.bono_hora = pcs_repo.crear_bono("1 hora", 60, 1100)
        articulos_repo.crear_articulo("PANCHO", "Pancho", None, None, 1200.0, 500.0, 0)
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 900.0, 400.0, 0)

    def abrir(self, estacion_id):
        """Una sesión de bono pagado, como la del cliente que se sienta."""
        pcs_repo.asignar_bono(estacion_id, self.bono_hora, self.operador, _pagos((EFECTIVO, 1100)))
        return self.sesion_activa(estacion_id)["id"]

    def sesion_activa(self, estacion_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?", (estacion_id, dominio.SESION_ACTIVA)
            ).fetchone()

    def pancho(self, cantidad=1, precio=1200.0):
        return [{"codigo": "PANCHO", "descripcion": "Pancho", "cantidad": cantidad, "precio_unitario": precio}]

    def stock(self, codigo="PANCHO"):
        return articulos_repo.buscar_por_codigo(codigo)["stock"]

    def deuda(self, estacion_id):
        item = next(i for i in pcs_repo.estado_estaciones() if i["estacion"]["id"] == estacion_id)
        return item["deuda"]

    def minutos_que_le_quedan(self, estacion_id):
        fin = datetime.fromisoformat(self.sesion_activa(estacion_id)["fecha_fin_prevista"])
        return dominio.segundos_restantes(fin, datetime.now()) / 60

    def reglas(self, **cambios):
        reglas = {**cuentas_pc_repo.obtener_reglas(), **cambios}
        cuentas_pc_repo.guardar_reglas(self.admin, reglas["tope"], reglas["al_pasar_el_tope"],
                                       reglas["tiempo_a_cuenta"])


class TestAnotar(BaseCuenta):
    def test_arranca_con_el_tope_que_eligio_el_duenio(self):
        self.assertEqual(cuentas_pc_repo.obtener_reglas(), {
            "tope": 10000.0, "al_pasar_el_tope": dominio.TOPE_CUENTA_NO_DEJA, "tiempo_a_cuenta": True,
        })

    def test_un_pancho_baja_el_stock_y_la_pc_queda_debiendo(self):
        self.abrir(self.pc1)
        resultado = cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(2), self.operador, nombre="Pedro")

        self.assertEqual(resultado, {"estacion": "PC1", "nombre": "Pedro", "debe": 2400.0})
        self.assertEqual(self.stock(), -2)
        deuda = self.deuda(self.pc1)
        self.assertEqual(deuda["total"], 2400.0)
        self.assertEqual(deuda["de_la_sesion"]["nombre"], "Pedro")
        self.assertIsNone(self.deuda(self.pc2))
        # Todavía no entró plata: la caja no se entera hasta que se cobra.
        self.assertEqual(turnos_repo.resumen_turno_actual()["kiosko_efectivo"], 0)

    def test_lo_que_se_anota_despues_va_a_la_misma_cuenta(self):
        self.abrir(self.pc1)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, nombre="Pedro")
        resultado = cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, nombre="Otro")
        self.assertEqual((resultado["nombre"], resultado["debe"]), ("Pedro", 2400.0))
        self.assertEqual(len(cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)), 1)

    def test_sin_una_sesion_en_curso_no_se_anota(self):
        with self.assertRaisesRegex(ValueError, "no tiene una sesión en curso"):
            cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador)
        self.assertEqual(self.stock(), 0)

    def test_un_socio_va_con_su_nombre(self):
        socio = miembros_repo.crear_miembro("rodri", "clave123", "Rodrigo", "30111222", "1155554444")
        miembros_repo.cargar_saldo_por_bono(socio, bonos_miembro_repo.crear_bono("2 h", 120, 2000),
                                            _pagos((EFECTIVO, 2000)), self.operador)
        miembros_repo.abrir_estacion_por_miembro(self.pc1, "rodri", "clave123")
        resultado = cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, nombre="Pepe")
        self.assertEqual(resultado["nombre"], "Rodrigo")

    def test_un_bono_suma_el_tiempo_ya_y_queda_debiendo(self):
        self.abrir(self.pc1)
        cuentas_pc_repo.anotar_bono(self.pc1, self.bono_hora, self.operador, nombre="Pedro")
        self.assertAlmostEqual(self.minutos_que_le_quedan(self.pc1), 120, delta=1)
        self.assertEqual(self.deuda(self.pc1)["total"], 1100.0)
        renglon = cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]["renglones"][0]
        self.assertEqual((renglon["tipo"], renglon["descripcion"], renglon["anoto"]),
                         (dominio.ITEM_CUENTA_BONO, "Bono 1 hora", "Ana"))

    def test_si_el_admin_no_deja_anotar_tiempo(self):
        self.abrir(self.pc1)
        self.reglas(tiempo_a_cuenta=False)
        with self.assertRaisesRegex(ValueError, "no deja anotar tiempo"):
            cuentas_pc_repo.anotar_bono(self.pc1, self.bono_hora, self.operador)
        self.assertAlmostEqual(self.minutos_que_le_quedan(self.pc1), 60, delta=1)

    def test_pcstream_se_anota_con_sus_bonos(self):
        stream = pcs_repo.crear_estacion("PCSTREAM")
        bono_stream = pcstream_repo.crear_bono("Stream 1 h", 60, 3000)
        pcs_repo.asignar_bono(stream, bono_stream, self.operador, _pagos((EFECTIVO, 3000)))
        cuentas_pc_repo.anotar_bono(stream, bono_stream, self.operador)
        self.assertEqual(self.deuda(stream)["total"], 3000.0)
        cuenta_id = cuentas_pc_repo.cuentas_de_la_estacion(stream)[0]["id"]
        cuentas_pc_repo.cobrar([cuenta_id], self.operador, _pagos((EFECTIVO, 3000)))
        with conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM sesion_pcstream_bonos").fetchone()[0], 2)


class TestTope(BaseCuenta):
    def setUp(self):
        super().setUp()
        self.abrir(self.pc1)
        self.reglas(tope=3000)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(2), self.operador)  # debe 2400

    def test_no_deja_pasarse_y_no_anota_nada(self):
        with self.assertRaises(cuentas_pc_repo.TopeSuperado) as error:
            cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador)
        self.assertFalse(error.exception.con_clave)
        self.assertIn("Cobrale primero", str(error.exception))
        self.assertEqual((self.stock(), self.deuda(self.pc1)["total"]), (-2, 2400.0))

    def test_justo_el_tope_se_puede(self):
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(precio=600), self.operador)
        self.assertEqual(self.deuda(self.pc1)["total"], 3000.0)

    def test_con_la_regla_de_la_clave_pasa_con_la_de_un_admin(self):
        self.reglas(al_pasar_el_tope=dominio.TOPE_CUENTA_CON_CLAVE_ADMIN)
        with self.assertRaises(cuentas_pc_repo.TopeSuperado) as error:
            cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador)
        self.assertTrue(error.exception.con_clave)
        for autoriza in ({"nombre": "Jefe", "clave": "mal"}, {"nombre": "Ana", "clave": "1234"}):
            with self.subTest(autoriza=autoriza["nombre"]), self.assertRaises(cuentas_pc_repo.TopeSuperado):
                cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, autoriza=autoriza)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador,
                                         autoriza={"nombre": "jefe", "clave": "clave-jefe"})
        self.assertEqual(self.deuda(self.pc1)["total"], 3600.0)

    def test_con_el_tope_en_cero_no_se_anota_nada(self):
        self.reglas(tope=0, al_pasar_el_tope=dominio.TOPE_CUENTA_CON_CLAVE_ADMIN)
        self.abrir(self.pc2)
        with self.assertRaisesRegex(cuentas_pc_repo.TopeSuperado, "no deja anotar nada"):
            cuentas_pc_repo.anotar_articulos(self.pc2, self.pancho(), self.operador)

    def test_las_reglas_las_cambia_solo_un_admin(self):
        with self.assertRaises(PermissionError):
            cuentas_pc_repo.guardar_reglas(self.operador, 5000, dominio.TOPE_CUENTA_NO_DEJA, True)
        for tope, accion in ((-1, dominio.TOPE_CUENTA_NO_DEJA), ("mucho", dominio.TOPE_CUENTA_NO_DEJA),
                             (5000, "CUALQUIERA")):
            with self.subTest(tope=tope, accion=accion), self.assertRaises(ValueError):
                cuentas_pc_repo.guardar_reglas(self.admin, tope, accion, True)


class TestCobrar(BaseCuenta):
    def setUp(self):
        super().setUp()
        self.sesion = self.abrir(self.pc1)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, nombre="Pedro")
        cuentas_pc_repo.anotar_bono(self.pc1, self.bono_hora, self.operador)
        self.cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]

    def test_cobra_todo_junto_y_cada_cosa_entra_en_su_negocio(self):
        self.assertEqual(cuentas_pc_repo.total_de([self.cuenta["id"]]), 2300.0)
        antes = turnos_repo.resumen_turno_actual()

        ventas = cuentas_pc_repo.cobrar([self.cuenta["id"]], self.admin, _pagos((DIGITAL, 300), (EFECTIVO, 2000)))

        self.assertEqual(len(ventas), 2)
        self.assertIsNone(self.deuda(self.pc1))
        self.assertEqual(self.stock(), -1)  # bajó al anotarlo, no otra vez al cobrar
        despues = turnos_repo.resumen_turno_actual()
        self.assertEqual(despues["kiosko_efectivo"] - antes["kiosko_efectivo"], 1200)
        self.assertEqual(despues["pcs_efectivo"] - antes["pcs_efectivo"], 800)
        self.assertEqual(despues["pcs_digital"] - antes["pcs_digital"], 300)
        with conexion_db() as conexion:
            bono = conexion.execute(
                "SELECT * FROM sesion_bonos WHERE sesion_id = ? ORDER BY id DESC LIMIT 1", (self.sesion,)
            ).fetchone()
            detalle = conexion.execute("SELECT * FROM venta_detalle WHERE venta_id = ?", (ventas[0],)).fetchall()
            estado = conexion.execute("SELECT estado FROM cuentas_pc WHERE id = ?", (self.cuenta["id"],)).fetchone()
        self.assertEqual((bono["venta_id"], bono["minutos"], bono["precio"]), (ventas[1], 60, 1100))
        self.assertEqual([(d["articulo_codigo"], d["cantidad"], d["subtotal"]) for d in detalle], [("PANCHO", 1, 1200)])
        self.assertEqual(estado["estado"], dominio.CUENTA_COBRADA)

    def test_una_cuenta_cobrada_no_se_cobra_dos_veces(self):
        cuentas_pc_repo.cobrar([self.cuenta["id"]], self.operador, _pagos((EFECTIVO, 2300)))
        with self.assertRaisesRegex(ValueError, "ya se cerró"):
            cuentas_pc_repo.cobrar([self.cuenta["id"]], self.operador, _pagos((EFECTIVO, 2300)))

    def test_si_lo_cobrado_no_coincide_no_se_graba_nada(self):
        with self.assertRaises(ValueError):
            cuentas_pc_repo.cobrar([self.cuenta["id"]], self.operador, _pagos((EFECTIVO, 1000)))
        self.assertEqual(self.deuda(self.pc1)["total"], 2300.0)

    def test_en_movimientos_el_pancho_sale_una_sola_vez(self):
        hoy = datetime.now().date().isoformat()
        antes = articulos_repo.obtener_movimientos("PANCHO", hoy, hoy)
        self.assertEqual([(m["comprobante"], m["cantidad"]) for m in antes], [("cuenta de PC1 sin cobrar", -1)])
        cuentas_pc_repo.cobrar([self.cuenta["id"]], self.operador, _pagos((EFECTIVO, 2300)))
        despues = articulos_repo.obtener_movimientos("PANCHO", hoy, hoy)
        self.assertEqual([(m["comprobante"], m["cantidad"]) for m in despues], [("ventas", -1)])


class TestLaCuentaVaConElCliente(BaseCuenta):
    def test_si_se_cambia_de_pc_la_cuenta_se_va_con_el(self):
        self.abrir(self.pc1)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, nombre="Pedro")
        pcs_repo.trasladar_sesion(self.pc1, self.pc2, self.operador)
        self.assertIsNone(self.deuda(self.pc1))
        self.assertEqual(self.deuda(self.pc2)["de_la_sesion"]["nombre"], "Pedro")

    def test_si_se_va_debiendo_la_pc_sigue_debiendo_y_el_proximo_tiene_otra_cuenta(self):
        sesion = self.abrir(self.pc1)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(), self.operador, nombre="Pedro")
        pcs_repo.finalizar_sesion(sesion)

        deuda = self.deuda(self.pc1)
        self.assertEqual(deuda["total"], 1200.0)
        self.assertIsNone(deuda["de_la_sesion"])

        self.abrir(self.pc1)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(precio=900), self.operador, nombre="Juan")
        cuentas = cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)
        self.assertEqual([(c["nombre"], c["total"], c["es_de_la_sesion_actual"]) for c in cuentas],
                         [("Juan", 900.0, True), ("Pedro", 1200.0, False)])
        self.assertEqual(self.deuda(self.pc1)["total"], 2100.0)


class TestQuitarYPerder(BaseCuenta):
    def setUp(self):
        super().setUp()
        self.abrir(self.pc1)
        cuentas_pc_repo.anotar_articulos(self.pc1, self.pancho(2), self.operador, nombre="Pedro")
        cuentas_pc_repo.anotar_bono(self.pc1, self.bono_hora, self.operador)
        self.cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]
        self.renglon_pancho, self.renglon_bono = self.cuenta["renglones"]

    def test_quitar_es_solo_del_admin_y_con_motivo(self):
        with self.assertRaises(PermissionError):
            cuentas_pc_repo.quitar_renglon(self.renglon_pancho["id"], self.operador, "error")
        with self.assertRaises(ValueError):
            cuentas_pc_repo.quitar_renglon(self.renglon_pancho["id"], self.admin, "  ")

    def test_un_articulo_quitado_vuelve_al_stock(self):
        cuentas_pc_repo.quitar_renglon(self.renglon_pancho["id"], self.admin, "era de la PC 11")
        self.assertEqual(self.stock(), 0)
        self.assertEqual(self.deuda(self.pc1)["total"], 1100.0)
        with conexion_db() as conexion:
            fila = conexion.execute("SELECT * FROM cuenta_pc_items WHERE id = ?", (self.renglon_pancho["id"],)).fetchone()
        self.assertEqual((fila["quitado_por"], fila["quitado_motivo"]), (self.admin, "era de la PC 11"))

    def test_un_bono_quitado_le_saca_el_tiempo(self):
        cuentas_pc_repo.quitar_renglon(self.renglon_bono["id"], self.admin, "no lo pidió")
        self.assertAlmostEqual(self.minutos_que_le_quedan(self.pc1), 60, delta=1)
        self.assertEqual(self.deuda(self.pc1)["total"], 2400.0)

    def test_si_le_quitan_todo_no_debe_nada(self):
        for renglon in (self.renglon_pancho, self.renglon_bono):
            cuentas_pc_repo.quitar_renglon(renglon["id"], self.admin, "error")
        self.assertIsNone(self.deuda(self.pc1))
        self.assertEqual(cuentas_pc_repo.cuentas_de_la_estacion(self.pc1), [])

    def test_dar_por_perdida_es_del_admin_y_queda_anotada(self):
        with self.assertRaises(PermissionError):
            cuentas_pc_repo.dar_por_perdida(self.cuenta["id"], self.operador, "se fue")
        cuentas_pc_repo.dar_por_perdida(self.cuenta["id"], self.admin, "se fue sin pagar")
        self.assertIsNone(self.deuda(self.pc1))
        self.assertEqual(self.stock(), -2)  # se lo llevó
        hoy = datetime.now().date().isoformat()
        movimientos = articulos_repo.obtener_movimientos("PANCHO", hoy, hoy)
        self.assertEqual([(m["comprobante"], m["cantidad"]) for m in movimientos], [("cuenta perdida (PC1)", -2)])
        with conexion_db() as conexion:
            cuenta = conexion.execute("SELECT * FROM cuentas_pc WHERE id = ?", (self.cuenta["id"],)).fetchone()
        self.assertEqual((cuenta["estado"], cuenta["usuario_cierre_id"], cuenta["motivo_perdida"]),
                         (dominio.CUENTA_PERDIDA, self.admin, "se fue sin pagar"))

    def test_cambiar_el_codigo_de_un_articulo_lleva_lo_anotado(self):
        # Una contraseña de prueba: la de verdad nunca se escribe en el repo.
        with mock.patch.object(articulos_repo, "CLAVE_ORDENAR_STOCK", database.hash_clave("prueba")):
            articulos_repo.cambiar_codigo(self.admin, "PANCHO", "PANCHO2", "prueba")
        with conexion_db() as conexion:
            codigo = conexion.execute(
                "SELECT articulo_codigo FROM cuenta_pc_items WHERE id = ?", (self.renglon_pancho["id"],)
            ).fetchone()["articulo_codigo"]
        self.assertEqual(codigo, "PANCHO2")


class TestUnBonoAnotadoNoSeLeDevuelveAlSocio(BaseCuenta):
    def setUp(self):
        super().setUp()
        self.socio = miembros_repo.crear_miembro("rodri", "clave123", "Rodrigo", "30111222", "1155554444")
        miembros_repo.cargar_saldo_por_bono(self.socio, bonos_miembro_repo.crear_bono("1 h", 60, 1000),
                                            _pagos((EFECTIVO, 1000)), self.operador)
        self.sesion = miembros_repo.abrir_estacion_por_miembro(self.pc1, "rodri", "clave123")["sesion_id"]
        cuentas_pc_repo.anotar_bono(self.pc1, self.bono_hora, self.operador)

    def saldo(self):
        return miembros_repo.obtener_miembro(self.socio)["saldo_minutos"]

    def test_sin_cobrar_cuenta_como_bono(self):
        with conexion_db() as conexion:
            aportes = reintegros_repo.contribuciones_de_sesion(conexion, self.sesion)
        self.assertEqual([(a["tipo"], a["minutos"]) for a in aportes], [("SOCIO", 60), ("BONO", 60)])
        pcs_repo.finalizar_sesion(self.sesion)
        # Le quedaban ~2 h: la última es del bono (no se devuelve) y la primera, suya.
        self.assertEqual(self.saldo(), 30)

    def test_cobrado_sigue_en_su_lugar_aunque_se_cobre_despues_de_una_carga(self):
        cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc1)[0]
        # El socio carga más saldo (pasa a la sesión) y recién después se cobra el bono.
        miembros_repo.cargar_saldo_por_bono(self.socio, bonos_miembro_repo.crear_bono("30 m", 30, 500),
                                            _pagos((EFECTIVO, 500)), self.operador)
        cuentas_pc_repo.cobrar([cuenta["id"]], self.operador, _pagos((EFECTIVO, 1100)))
        with conexion_db() as conexion:
            aportes = reintegros_repo.contribuciones_de_sesion(conexion, self.sesion)
        self.assertEqual([(a["tipo"], a["minutos"]) for a in aportes], [("SOCIO", 60), ("BONO", 60), ("SOCIO", 30)])


class TestDesdeOtraPc(unittest.TestCase):
    def test_se_mira_pero_anotar_y_cobrar_son_del_mostrador(self):
        self.assertTrue(lista_blanca.permitida("cuentas_pc_repo", "cuentas_de_la_estacion"))
        for nombre in ("anotar_articulos", "anotar_bono", "cobrar", "quitar_renglon", "dar_por_perdida",
                       "cuentas_abiertas"):
            self.assertFalse(lista_blanca.permitida("cuentas_pc_repo", nombre), nombre)


if __name__ == "__main__":
    unittest.main()
