"""
tests/test_candados_de_plata.py
===============================
Las reglas de plata las hace cumplir el repo, no solo la pantalla (revisión
general del 2026-11-16, mejora 2; CLAUDE.md, regla 3):

- 2a. Vender un bono (de PC o de la consola) toma el candado de la base al
  empezar: si en ese mismo instante otro hilo cierra la sesión o le corrige el
  tiempo, la venta espera y se suma a lo que quedó, nunca a una sesión cerrada.
- 2b. La base no deja dos sesiones ACTIVAS en una misma PC.
- 2c. Cambiar el precio de un artículo al vender (o al anotarlo en la Cuenta de
  la PC) es solo del Administrador.
- 2d. `anular_venta` no anula una carga de saldo ni un bono: esos tienen su
  propio camino, que también saca el tiempo.
- 2e. Todas las ventas sin detalle revisan que los pagos sumen justo el total.

"El otro hilo" de las carreras es una conexión que toma el candado y cambia la
sesión antes de que arranque la venta, y lo suelta un rato después: así la
carrera sale siempre igual, sin depender de la suerte.
"""

import os
import sqlite3
import threading
import time
from datetime import datetime, timedelta

import database
import dominio
from control_pcs.repositories import (
    anular_bono_repo, bonos_miembro_repo, cuentas_pc_repo, miembros_repo, pcs_repo, playstation_repo,
)
from database import conexion_db
from repositories import articulos_repo, tramites_repo, usuarios_repo, ventas_repo
from base import BaseConBaseTemporal

UNA_HORA = 60
# Lo que el otro hilo tiene el candado después de que arrancó la venta: con el
# código de antes, la venta ya leyó la sesión vieja y espera para escribir.
SEGUNDOS_CON_EL_CANDADO = 0.3


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _fecha(texto):
    return datetime.fromisoformat(texto)


class BaseCandados(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.pc = pcs_repo.crear_estacion("PC 7")
        self.bono_hora = pcs_repo.crear_bono("1 hora", UNA_HORA, 1500)

    def vender_bono(self, estacion=None):
        return pcs_repo.asignar_bono(estacion or self.pc, self.bono_hora, self.toby, _efectivo(1500))

    def mientras_otro_tiene_el_candado(self, cambiar, operacion):
        """Corre `operacion` en un hilo mientras otra conexión tiene el candado de
        la base y ya hizo `cambiar(conexion)` sin confirmarlo; lo confirma un rato
        después. Devuelve lo que devolvió `operacion` (o levanta su error)."""
        otro = database.get_connection()
        otro.isolation_level = None
        otro.execute("BEGIN IMMEDIATE")
        try:
            cambiar(otro)
            resultado = {}

            def correr():
                try:
                    resultado["valor"] = operacion()
                except Exception as error:  # noqa: BLE001 - se vuelve a levantar abajo
                    resultado["error"] = error

            hilo = threading.Thread(target=correr)
            hilo.start()
            time.sleep(SEGUNDOS_CON_EL_CANDADO)
            otro.execute("COMMIT")
        finally:
            otro.close()
        hilo.join(15)
        self.assertFalse(hilo.is_alive(), "la operación quedó colgada")
        if "error" in resultado:
            raise resultado["error"]
        return resultado["valor"]

    def sesiones_de(self, estacion_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT * FROM sesiones_pc WHERE estacion_id = ? ORDER BY id", (estacion_id,)
            ).fetchall()

    def activas_de(self, estacion_id):
        return [s for s in self.sesiones_de(estacion_id) if s["estado"] == dominio.SESION_ACTIVA]

    def sesion_del_bono(self, venta_id, vinculo="sesion_bonos", sesiones="sesiones_pc"):
        with conexion_db() as conexion:
            return conexion.execute(
                f"SELECT s.* FROM {vinculo} sb JOIN {sesiones} s ON s.id = sb.sesion_id WHERE sb.venta_id = ?",
                (venta_id,),
            ).fetchone()

    def insertar_activa(self, conexion, estacion_id, minutos=30):
        """Una sesión ACTIVA escrita a mano, como la que abre un socio al entrar."""
        ahora = datetime.now()
        conexion.execute(
            "INSERT INTO sesiones_pc (estacion_id, fecha_inicio, fecha_fin_prevista, estado) VALUES (?, ?, ?, ?)",
            (estacion_id, ahora.isoformat(timespec="seconds"),
             (ahora + timedelta(minutes=minutos)).isoformat(timespec="seconds"), dominio.SESION_ACTIVA),
        )

    def cuantas(self, tabla):
        with conexion_db() as conexion:
            return conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]


# ---------------------------------------------------------------------
# 2a. Vender un bono espera su turno
# ---------------------------------------------------------------------

class TestElBonoEsperaSuTurno(BaseCandados):
    def test_si_el_socio_cierra_en_ese_instante_el_bono_abre_una_sesion_nueva(self):
        # Antes: el bono se sumaba a la sesión que el otro hilo acababa de cerrar. La
        # plata entraba a la caja y la PC quedaba bloqueada.
        self.vender_bono()
        (vieja,) = self.activas_de(self.pc)

        def cerrar(conexion):
            conexion.execute(
                "UPDATE sesiones_pc SET estado = ?, fecha_fin_real = ? WHERE id = ?",
                (dominio.SESION_FINALIZADA, datetime.now().isoformat(timespec="seconds"), vieja["id"]),
            )

        venta = self.mientras_otro_tiene_el_candado(cerrar, self.vender_bono)

        sesion = self.sesion_del_bono(venta)
        self.assertEqual(sesion["estado"], dominio.SESION_ACTIVA)
        self.assertNotEqual(sesion["id"], vieja["id"])
        self.assertEqual(len(self.activas_de(self.pc)), 1)
        cerrada = self.sesiones_de(self.pc)[0]
        self.assertEqual(cerrada["fecha_fin_prevista"], vieja["fecha_fin_prevista"], "a la cerrada no se le suma nada")

    def test_si_le_corrigen_el_tiempo_en_ese_instante_el_bono_se_suma_al_fin_corregido(self):
        # "Gana el menor" de una PC que vuelve de un corte (reconexion_repo.tomar_el_menor).
        # Antes: el bono se sumaba al fin viejo y la corrección se perdía.
        self.vender_bono()
        (sesion,) = self.activas_de(self.pc)
        corregido = (datetime.now() + timedelta(minutes=10)).replace(microsecond=0)

        def corregir(conexion):
            conexion.execute(
                "UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                (corregido.isoformat(timespec="seconds"), sesion["id"]),
            )

        self.mientras_otro_tiene_el_candado(corregir, self.vender_bono)

        (despues,) = self.activas_de(self.pc)
        self.assertEqual(_fecha(despues["fecha_fin_prevista"]), corregido + timedelta(minutes=UNA_HORA))

    def test_la_consola_tambien_espera_si_la_liberan_en_ese_instante(self):
        bono_ps5 = playstation_repo.crear_bono(self.admin, "1 hora PS5", UNA_HORA, 2000)
        playstation_repo.vender_bono(self.toby, bono_ps5, _efectivo(2000))
        vieja = playstation_repo.estado()["sesion"]

        def liberar(conexion):
            conexion.execute(
                "UPDATE sesiones_playstation SET estado = ?, fecha_fin_real = ? WHERE id = ?",
                (dominio.SESION_FINALIZADA, datetime.now().isoformat(timespec="seconds"), vieja["id"]),
            )

        venta = self.mientras_otro_tiene_el_candado(
            liberar, lambda: playstation_repo.vender_bono(self.toby, bono_ps5, _efectivo(2000))
        )

        sesion = self.sesion_del_bono(venta, "sesion_playstation_bonos", "sesiones_playstation")
        self.assertEqual(sesion["estado"], dominio.SESION_ACTIVA)
        self.assertNotEqual(sesion["id"], vieja["id"])


# ---------------------------------------------------------------------
# 2b. Una sola sesión ACTIVA por PC
# ---------------------------------------------------------------------

class TestUnaSolaSesionActivaPorPc(BaseCandados):
    def test_la_base_no_deja_abrir_una_segunda_sesion_activa_en_la_misma_pc(self):
        self.vender_bono()
        with self.assertRaises(sqlite3.IntegrityError):
            with conexion_db() as conexion:
                self.insertar_activa(conexion, self.pc)
        self.assertEqual(len(self.activas_de(self.pc)), 1)

    def test_otras_pcs_y_las_sesiones_cerradas_no_cuentan(self):
        otra = pcs_repo.crear_estacion("PC 8")
        self.vender_bono()
        self.vender_bono(otra)
        (sesion,) = self.activas_de(self.pc)
        pcs_repo.finalizar_sesion(sesion["id"], dominio.CIERRE_FINALIZAR, self.toby)
        self.vender_bono()
        self.assertEqual(len(self.activas_de(self.pc)), 1)
        self.assertEqual(len(self.activas_de(otra)), 1)

    def test_si_un_socio_entra_mientras_se_vende_un_bono_queda_una_sola_sesion(self):
        # Antes: 8 de 300 intentos forzados terminaban con DOS sesiones activas en la PC.
        venta = self.mientras_otro_tiene_el_candado(
            lambda conexion: self.insertar_activa(conexion, self.pc), self.vender_bono
        )

        (sesion,) = self.activas_de(self.pc)
        self.assertEqual(self.sesion_del_bono(venta)["id"], sesion["id"])


class TestElIndiceEnUnaBaseVieja(BaseCandados):
    """La base del local se creó sin el índice: se agrega al arrancar. Si justo
    tuviera una PC con dos sesiones activas, no se puede crear: el programa
    arranca igual, lo anota en errores.log y lo vuelve a intentar en el próximo
    arranque (para entonces una de las dos ya se cerró sola)."""

    def setUp(self):
        super().setUp()
        with conexion_db() as conexion:
            conexion.execute(f"DROP INDEX {database.INDICE_UNA_SESION_ACTIVA_POR_PC}")

    def _indice_creado(self):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT COUNT(*) FROM sqlite_master WHERE type = 'index' AND name = ?",
                (database.INDICE_UNA_SESION_ACTIVA_POR_PC,),
            ).fetchone()[0] == 1

    def _log(self):
        ruta = os.path.join(database.DATA_DIR, "errores.log")
        if not os.path.exists(ruta):
            return ""
        with open(ruta, encoding="utf-8") as archivo:
            return archivo.read()

    def test_sin_duplicadas_se_crea_al_arrancar(self):
        self.vender_bono()
        database.inicializar_base_de_datos()
        self.assertTrue(self._indice_creado())
        self.assertEqual(self._log(), "")

    def test_con_dos_activas_en_una_pc_arranca_igual_avisa_y_lo_crea_cuando_se_cierran(self):
        self.vender_bono()
        with conexion_db() as conexion:
            self.insertar_activa(conexion, self.pc)

        database.inicializar_base_de_datos()

        self.assertFalse(self._indice_creado())
        self.assertIn("PC 7", self._log())
        self.assertEqual(len(self.activas_de(self.pc)), 2, "no se toca ninguna sesión")

        for sesion in self.activas_de(self.pc):
            pcs_repo.finalizar_sesion(sesion["id"], dominio.CIERRE_FINALIZAR, self.toby)
        database.inicializar_base_de_datos()
        self.assertTrue(self._indice_creado())


# ---------------------------------------------------------------------
# 2c. El precio de lista, salvo que venda un Administrador
# ---------------------------------------------------------------------

class TestElPrecioDeLista(BaseCandados):
    def setUp(self):
        super().setUp()
        articulos_repo.crear_articulo("ALF", "Alfajor", None, None, 1500.0, 700.0, 0)

    def alfajor(self, precio=1500.0, cantidad=1):
        return [{"codigo": "ALF", "descripcion": "Alfajor", "cantidad": cantidad, "precio_unitario": precio}]

    def test_una_empleada_no_puede_vender_a_otro_precio(self):
        # Antes: una EMPLEADA grababa un alfajor de $ 1.500 a $ 1 llamando al repo.
        with self.assertRaisesRegex(PermissionError, "solo del Administrador"):
            ventas_repo.confirmar_venta(self.toby, self.alfajor(1.0), _efectivo(1.0))
        self.assertEqual(self.cuantas("ventas"), 0)
        self.assertEqual(articulos_repo.buscar_por_codigo("ALF")["stock"], 0)

    def test_al_precio_de_lista_vende_cualquiera(self):
        venta = ventas_repo.confirmar_venta(self.toby, self.alfajor(cantidad=2), _efectivo(3000.0))
        self.assertEqual(ventas_repo.buscar_venta(venta)[0]["total"], 3000.0)

    def test_el_administrador_si_puede_cambiarlo(self):
        venta = ventas_repo.confirmar_venta(self.admin, self.alfajor(1200.0), _efectivo(1200.0))
        _, detalle, _ = ventas_repo.buscar_venta(venta)
        self.assertEqual(detalle[0]["precio_unitario"], 1200.0)

    def test_si_el_precio_cambio_mientras_estaba_en_el_carrito_avisa_cual_es_el_nuevo(self):
        carrito = self.alfajor()
        with conexion_db() as conexion:
            conexion.execute("UPDATE articulos SET precio_venta = 1600 WHERE codigo = 'ALF'")
        with self.assertRaisesRegex(PermissionError, r"\$ 1\.600"):
            ventas_repo.confirmar_venta(self.toby, carrito, _efectivo(1500.0))

    def test_tampoco_se_puede_anotar_en_la_cuenta_de_la_pc_a_otro_precio(self):
        self.vender_bono()
        with self.assertRaisesRegex(PermissionError, "solo del Administrador"):
            cuentas_pc_repo.anotar_articulos(self.pc, self.alfajor(1.0), self.toby, nombre="Pedro")
        self.assertEqual(self.cuantas("cuenta_pc_items"), 0)
        resultado = cuentas_pc_repo.anotar_articulos(self.pc, self.alfajor(), self.toby, nombre="Pedro")
        self.assertEqual(resultado["debe"], 1500.0)


# ---------------------------------------------------------------------
# 2d. anular_venta no anula cargas ni bonos
# ---------------------------------------------------------------------

class TestAnularVentaNoEsParaCargasNiBonos(BaseCandados):
    def estado_de(self, venta_id):
        return ventas_repo.buscar_venta(venta_id)[0]["estado"]

    def test_una_carga_de_saldo_no_se_anula_como_venta_comun(self):
        # Antes: la venta quedaba ANULADA y el socio conservaba sus minutos.
        socio = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222")
        bono_socio = bonos_miembro_repo.crear_bono("5 horas", 300, 5000)
        venta = miembros_repo.cargar_saldo_por_bono(socio, bono_socio, _efectivo(5000), self.toby)["venta_id"]

        with self.assertRaisesRegex(ValueError, "Anular carga"):
            ventas_repo.anular_venta(venta, self.admin, "se cargó dos veces")

        self.assertEqual(self.estado_de(venta), dominio.VENTA_CONFIRMADA)
        self.assertEqual(miembros_repo.obtener_miembro(socio)["saldo_minutos"], 300)

    def test_un_bono_no_se_anula_como_venta_comun(self):
        venta = self.vender_bono()
        (sesion,) = self.activas_de(self.pc)

        with self.assertRaisesRegex(ValueError, "Quitar bono"):
            ventas_repo.anular_venta(venta, self.admin, "se vendió de más")
        # El mismo hueco en el camino de las cargas: un bono no es una carga.
        with self.assertRaisesRegex(ValueError, "Quitar bono"):
            miembros_repo.anular_carga(venta, self.admin, "se vendió de más")

        self.assertEqual(self.estado_de(venta), dominio.VENTA_CONFIRMADA)
        self.assertEqual(self.activas_de(self.pc)[0]["fecha_fin_prevista"], sesion["fecha_fin_prevista"])
        # Su camino sigue andando: anula la plata y saca el tiempo.
        anular_bono_repo.anular_bono(venta, self.admin, "se vendió de más")
        self.assertEqual(self.estado_de(venta), dominio.VENTA_ANULADA)

    def test_una_venta_del_kiosko_se_sigue_anulando(self):
        articulos_repo.crear_articulo("ALF", "Alfajor", None, None, 1500.0, 700.0, 0)
        venta = ventas_repo.confirmar_venta(
            self.toby, [{"codigo": "ALF", "descripcion": "Alfajor", "cantidad": 1, "precio_unitario": 1500.0}],
            _efectivo(1500.0),
        )
        ventas_repo.anular_venta(venta, self.admin, "se equivocó de artículo")
        self.assertEqual(self.estado_de(venta), dominio.VENTA_ANULADA)


# ---------------------------------------------------------------------
# 2e. Los pagos suman justo el total, en todas las ventas sin detalle
# ---------------------------------------------------------------------

class TestLosPagosSumanElTotal(BaseCandados):
    def test_un_tramite_pagado_de_mas_no_se_graba(self):
        # Antes: un trámite de $ 1.000 con $ 5.000 en efectivo se grababa, y la Caja
        # esperaba $ 4.000 que no estaban en el cajón.
        tramite = tramites_repo.crear_tramite("Fotocopia DNI")
        with self.assertRaisesRegex(ValueError, "no coincide con el total"):
            tramites_repo.registrar_tramite(self.toby, tramite, 1000.0, _efectivo(5000.0))
        self.assertEqual(self.cuantas("ventas"), 0)

    def test_un_bono_de_pc_pagado_de_mas_o_de_menos_no_se_graba(self):
        for pagado in (5000.0, 1000.0):
            with self.subTest(pagado=pagado):
                with self.assertRaisesRegex(ValueError, "no coincide con el total"):
                    pcs_repo.asignar_bono(self.pc, self.bono_hora, self.toby, _efectivo(pagado))
        self.assertEqual(self.cuantas("ventas"), 0)
        self.assertEqual(self.sesiones_de(self.pc), [])

    def test_un_bono_de_la_consola_pagado_de_mas_no_se_graba(self):
        bono_ps5 = playstation_repo.crear_bono(self.admin, "1 hora PS5", UNA_HORA, 2000)
        with self.assertRaisesRegex(ValueError, "no coincide con el total"):
            playstation_repo.vender_bono(self.toby, bono_ps5, _efectivo(9000.0))
        self.assertIsNone(playstation_repo.estado()["sesion"])

    def test_una_carga_de_saldo_pagada_de_mas_no_se_graba(self):
        socio = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222")
        bono_socio = bonos_miembro_repo.crear_bono("5 horas", 300, 5000)
        with self.assertRaisesRegex(ValueError, "no coincide con el total"):
            miembros_repo.cargar_saldo_por_bono(socio, bono_socio, _efectivo(6000), self.toby)
        self.assertEqual(miembros_repo.obtener_miembro(socio)["saldo_minutos"], 0)

    def test_un_pago_negativo_no_se_graba_aunque_la_suma_de(self):
        pagos = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3500.0},
                 {"metodo": dominio.PAGO_DIGITAL, "monto": -2000.0}]
        with self.assertRaisesRegex(ValueError, "no puede ser negativo"):
            pcs_repo.asignar_bono(self.pc, self.bono_hora, self.toby, pagos)

    def test_una_devolucion_va_en_negativo_y_no_admite_un_pago_positivo(self):
        # La de una reserva (reservas_repo.devolver): total y pago en negativo.
        with conexion_db() as conexion:
            venta = ventas_repo.registrar_venta_sin_detalle(
                conexion, self.admin, -1500.0, _efectivo(-1500.0), dominio.ORIGEN_ALQUILER_PCS, datetime.now())
        self.assertEqual(ventas_repo.buscar_venta(venta)[0]["total"], -1500.0)
        with self.assertRaisesRegex(ValueError, "ningún pago puede ser positivo"):
            with conexion_db() as conexion:
                ventas_repo.registrar_venta_sin_detalle(
                    conexion, self.admin, -1500.0,
                    [{"metodo": dominio.PAGO_EFECTIVO, "monto": -3000.0},
                     {"metodo": dominio.PAGO_DIGITAL, "monto": 1500.0}],
                    dominio.ORIGEN_ALQUILER_PCS, datetime.now())

    def test_pagado_justo_en_dos_medios_se_graba(self):
        pagos = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0},
                 {"metodo": dominio.PAGO_DIGITAL, "monto": 500.0}]
        venta = pcs_repo.asignar_bono(self.pc, self.bono_hora, self.toby, pagos)
        self.assertEqual(ventas_repo.buscar_venta(venta)[0]["total"], 1500.0)
