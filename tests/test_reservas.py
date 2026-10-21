"""
tests/test_reservas.py
========================
RESERVAS (pedido del dueño, 2026-10-20; control_pcs/repositories/reservas_repo.py
y reservas_habilitar_repo.py). Lo que más importa es la plata, que se valida así
(PROPUESTA_RESERVAS.md, "Cómo se va a validar"):

- seña + resto = precio, y cada parte en la caja (el cierre) de quien la cobró;
- habilitar una reserva ya pagada no crea ninguna venta;
- "No vino" no mueve plata;
- la devolución baja lo que hay que retirar AHORA y no toca el cierre viejo;
- Limpiar base de datos borra las reservas.

Y las reglas del dueño: pierde la seña si no viene, "A reprogramar" si pagó
todo (vence a los 5 días), 20 minutos de tolerancia, el precio queda fijo,
"Cualquier PC" no aparta ninguna, PCSTREAM y la PlayStation 5 con sus bonos.

Se ejecutan con:

    python -m unittest discover tests
"""

import unittest
from datetime import date, datetime, timedelta

import dominio
from database import conexion_db
from repositories import articulos_repo, detalle_dia_repo, limpieza_repo, reportes_repo, turnos_repo, \
    usuarios_repo, ventas_repo
from control_pcs.repositories import (
    actividad_repo, pcs_repo, pcstream_repo, playstation_repo, reservas_habilitar_repo, reservas_repo,
)
from turnos import dia_en_que_empezo_el_turno
from base import BaseConBaseTemporal


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _manana_a_las(hora, minuto=0):
    """Mañana a esa hora: siempre en el futuro, corra la prueba cuando corra."""
    return datetime.combine(date.today() + timedelta(days=1), datetime.min.time()).replace(hour=hora, minute=minuto)


class _ConReservas(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.luis = usuarios_repo.crear_usuario("Luis", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        self.pcstream = pcs_repo.crear_estacion("PCSTREAM")
        self.promo = pcs_repo.crear_bono("Promo 10 hs", 600, 10000.0)
        self.tres_horas = pcs_repo.crear_bono("3 horas", 180, 3000.0)
        self.bono_stream = pcstream_repo.crear_bono("3 hs PCSTREAM", 180, 4500.0)
        self.bono_ps5 = playstation_repo.crear_bono(self.admin, "2 horas PS5", 120, 6000.0)

    def _reservar(self, monto=5000.0, equipo=dominio.EQUIPO_RESERVA_PC, estacion="pc1", bono=None,
                  cuando=None, por=None, cliente="Juan Pérez"):
        estacion_id = getattr(self, estacion) if estacion else None
        return reservas_repo.crear_reserva(
            por or self.ana, cliente, "11 5555-4444", equipo, estacion_id, bono or self.promo,
            cuando or _manana_a_las(10), monto, _efectivo(monto),
        )

    def _cerrar_turno(self, usuario):
        """Cierra el turno y lo corre un minuto atrás, con todo lo que cerró: en el
        local entre un cierre y lo que sigue pasan minutos, y el reloj de Windows
        avanza de a saltos, así que hechos uno atrás del otro el cierre y la
        habilitación quedaban con la MISMA hora y la habilitación caía adentro del
        cierre (medido: 1 de 2 corridas; mismo caso que en test_detalle_dia)."""
        cierre = turnos_repo.cerrar_turno(usuario)
        with conexion_db() as conexion:
            for tabla, columna in (("ventas", "fecha"), ("cierres_turno", "fecha_cierre")):
                for fila in conexion.execute(f"SELECT id, {columna} AS fecha FROM {tabla}").fetchall():
                    antes = datetime.fromisoformat(fila["fecha"]) - timedelta(minutes=1)
                    conexion.execute(f"UPDATE {tabla} SET {columna} = ? WHERE id = ?",
                                     (antes.isoformat(timespec="microseconds"), fila["id"]))
        return cierre

    def _cantidad_de_ventas(self):
        with conexion_db() as conexion:
            return conexion.execute("SELECT COUNT(*) AS n FROM ventas").fetchone()["n"]

    def _estado(self, reserva_id):
        return reservas_repo.obtener_reserva(reserva_id)["estado"]


class TestLaPlata(_ConReservas):
    def test_la_sena_queda_en_el_cierre_de_quien_reserva_y_el_resto_en_el_de_quien_habilita(self):
        reserva = self._reservar(5000.0, por=self.ana)
        cierre_ana = self._cerrar_turno(self.ana)

        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(5000.0))
        cierre_luis = turnos_repo.cerrar_turno(self.luis)

        # Cada uno cierra con la plata que recibió de verdad, y entre los dos, el precio.
        self.assertEqual(cierre_ana["monto_a_retirar"], 5000.0)
        self.assertEqual(cierre_luis["monto_a_retirar"], 5000.0)
        self.assertEqual(cierre_ana["pcs_efectivo"] + cierre_luis["pcs_efectivo"], 10000.0)
        self.assertEqual(self._estado(reserva), dominio.RESERVA_HABILITADA)

    def test_habilitar_una_reserva_ya_pagada_no_crea_ninguna_venta(self):
        reserva = self._reservar(10000.0)
        self._cerrar_turno(self.ana)
        antes = self._cantidad_de_ventas()

        resultado = reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, [])

        self.assertEqual(resultado, {"lugar": "PC1", "cobrado": 0.0})
        self.assertEqual(self._cantidad_de_ventas(), antes)
        resumen = turnos_repo.resumen_turno_actual()
        self.assertEqual(resumen["ventas_efectivo"], 0.0)
        # El Cierre de Turno la nombra, para que se entienda por qué se abrió una PC sin plata.
        self.assertEqual([r["numero"] for r in resumen["reservas_sin_cobro"]], [reserva])
        self.assertEqual(resumen["reservas_sin_cobro"][0]["lugar"], "PC1")
        self.assertEqual(resumen["reservas_sin_cobro"][0]["pagada_a"], "Ana")

    def test_habilitar_abre_la_pc_con_los_minutos_del_bono_reservado(self):
        reserva = self._reservar(10000.0)

        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, [])

        pc1 = next(e for e in pcs_repo.estado_estaciones() if e["estacion"]["id"] == self.pc1)
        self.assertGreater(pc1["segundos_restantes"], 599 * 60)
        with conexion_db() as conexion:
            vinculo = conexion.execute("SELECT * FROM sesion_bonos").fetchone()
        self.assertEqual((vinculo["bono_id"], vinculo["minutos"], vinculo["precio"]), (self.promo, 600, 10000.0))

    def test_el_bono_cuenta_una_sola_vez_en_el_ranking(self):
        reserva = self._reservar(5000.0)
        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(5000.0))

        hoy = dia_en_que_empezo_el_turno(datetime.now())
        ranking = reportes_repo.ranking_ventas(hoy.isoformat(), hoy.isoformat())
        promo = [fila for fila in ranking if fila["descripcion"] == "Promo 10 hs"]
        self.assertEqual([(fila["cantidad"], fila["importe"]) for fila in promo], [(1, 10000.0)])

    def test_actividad_reciente_dice_reserva_habilitada_y_no_bono_cobrado(self):
        # El bono de una reserva se anota con la venta del día que se reservó (que pudo
        # ser solo la seña): como "bono cobrado ($ 10.000)" confundiría al que mira la caja.
        reserva = self._reservar(5000.0)
        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(5000.0))
        ps5 = self._reservar(6000.0, equipo=dominio.EQUIPO_RESERVA_PLAYSTATION, estacion=None, bono=self.bono_ps5)
        reservas_habilitar_repo.habilitar(ps5, self.luis, None, [])

        eventos = actividad_repo.actividad_reciente()

        self.assertNotIn("BONO", [evento["tipo"] for evento in eventos])
        self.assertEqual(
            sorted((e["estacion_nombre"], e["numero"]) for e in eventos if e["tipo"] == "RESERVA"),
            sorted([("PC1", reserva), (dominio.NOMBRE_PLAYSTATION, ps5)]),
        )

    def test_el_precio_queda_fijo_aunque_despues_cambie_el_bono(self):
        reserva = self._reservar(5000.0)
        pcs_repo.modificar_bono(self.promo, "Promo 10 hs", 600, 12000.0)

        self.assertEqual(reservas_repo.obtener_reserva(reserva)["falta"], 5000.0)
        self.assertEqual(reservas_habilitar_repo.preparar_habilitacion(reserva, self.pc1), 5000.0)

    def test_si_los_pagos_no_cubren_el_resto_no_se_graba_nada(self):
        reserva = self._reservar(5000.0)
        antes = self._cantidad_de_ventas()

        with self.assertRaises(ValueError):
            reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(1000.0))

        self.assertEqual(self._cantidad_de_ventas(), antes)
        self.assertEqual(self._estado(reserva), dominio.RESERVA_PENDIENTE)

    def test_en_una_pc_ocupada_no_se_habilita_ni_se_cobra_el_resto(self):
        reserva = self._reservar(5000.0)
        pcs_repo.asignar_bono(self.pc1, self.tres_horas, self.luis, _efectivo(3000.0))
        antes = self._cantidad_de_ventas()

        with self.assertRaisesRegex(ValueError, "PC1 está en uso"):
            reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(5000.0))

        self.assertEqual(self._cantidad_de_ventas(), antes)
        self.assertEqual(self._estado(reserva), dominio.RESERVA_PENDIENTE)
        # La otra libre sí, y la ocupada no se ofrece.
        lugares = reservas_habilitar_repo.lugares_para_habilitar(reserva)
        self.assertEqual([lugar["nombre"] for lugar in lugares], ["PC2"])

    def test_anular_la_sena_deja_la_reserva_sin_pagar(self):
        reserva = self._reservar(5000.0)
        venta = reservas_repo.obtener_reserva(reserva)["pagos"][0]["venta_id"]

        ventas_repo.anular_venta(venta, self.admin, "se cobró mal")

        datos = reservas_repo.obtener_reserva(reserva)
        self.assertEqual((datos["pagado"], datos["falta"]), (0.0, 10000.0))

    def test_una_reserva_se_toma_con_algo_de_plata_y_nunca_mas_que_el_precio(self):
        for monto in (0.0, 10000.01):
            with self.subTest(monto=monto), self.assertRaises(ValueError):
                self._reservar(monto)
        self.assertEqual(self._cantidad_de_ventas(), 0)

    def test_no_se_reserva_una_hora_que_ya_paso(self):
        with self.assertRaisesRegex(ValueError, "ya pasó"):
            self._reservar(cuando=datetime.now() - timedelta(hours=1))


class TestNoVino(_ConReservas):
    def test_con_sena_pierde_la_sena_y_no_se_mueve_plata(self):
        reserva = self._reservar(5000.0)
        antes = self._cantidad_de_ventas()

        estado = reservas_repo.marcar_no_vino(reserva, self.luis)

        self.assertEqual(estado, dominio.RESERVA_NO_VINO)
        self.assertEqual(self._cantidad_de_ventas(), antes)
        self.assertEqual(turnos_repo.resumen_turno_actual()["ventas_efectivo"], 5000.0)

    def test_si_pago_todo_queda_a_reprogramar(self):
        reserva = self._reservar(10000.0)

        self.assertEqual(reservas_repo.marcar_no_vino(reserva, self.luis), dominio.RESERVA_A_REPROGRAMAR)

    def test_pasados_los_20_minutos_de_tolerancia_pasa_sola(self):
        hora = _manana_a_las(10)
        con_sena = self._reservar(5000.0, cuando=hora)
        pagada = self._reservar(3000.0, estacion="pc2", bono=self.tres_horas, cuando=hora)

        reservas_repo.actualizar_estados(hora + timedelta(minutes=19))
        self.assertEqual(self._estado(con_sena), dominio.RESERVA_PENDIENTE)

        reservas_repo.actualizar_estados(hora + timedelta(minutes=21))
        self.assertEqual(self._estado(con_sena), dominio.RESERVA_NO_VINO)
        self.assertEqual(self._estado(pagada), dominio.RESERVA_A_REPROGRAMAR)
        # Queda anotado que lo hizo el programa, a la hora en que venció.
        datos = reservas_repo.obtener_reserva(pagada)
        self.assertIsNone(datos["estado_por"])
        self.assertEqual(datos["estado_desde"][:19], (hora + timedelta(minutes=20)).isoformat())

    def test_a_reprogramar_vence_a_los_cinco_dias(self):
        hora = _manana_a_las(10)
        reserva = self._reservar(10000.0, cuando=hora)
        reservas_repo.actualizar_estados(hora + timedelta(minutes=21))

        reservas_repo.actualizar_estados(hora + timedelta(days=5, minutes=19))
        self.assertEqual(self._estado(reserva), dominio.RESERVA_A_REPROGRAMAR)
        reservas_repo.actualizar_estados(hora + timedelta(days=5, minutes=21))
        self.assertEqual(self._estado(reserva), dominio.RESERVA_VENCIDA)

    def test_reprogramada_vuelve_a_esperar_y_ya_no_tiene_pc_propia(self):
        reserva = self._reservar(10000.0)
        reservas_repo.marcar_no_vino(reserva, self.luis)

        reservas_repo.reprogramar(reserva, self.luis, _manana_a_las(15), self.pc2)

        datos = reservas_repo.obtener_reserva(reserva)
        self.assertEqual(datos["estado"], dominio.RESERVA_PENDIENTE)
        self.assertIsNone(datos["estacion_id"])
        self.assertEqual(datos["equipo_nombre"], dominio.NOMBRE_RESERVA_CUALQUIER_PC)
        self.assertEqual(datos["falta"], 0.0)

    def test_una_pendiente_puede_cambiar_de_pc_y_de_hora(self):
        reserva = self._reservar(5000.0)

        reservas_repo.reprogramar(reserva, self.luis, _manana_a_las(15), self.pc2)

        datos = reservas_repo.obtener_reserva(reserva)
        self.assertEqual((datos["equipo_nombre"], datos["fecha_reserva"]),
                         ("PC2", _manana_a_las(15).isoformat()))


class TestHorarios(_ConReservas):
    def test_la_misma_pc_no_se_reserva_dos_veces_a_la_vez(self):
        self._reservar(cuando=_manana_a_las(10))  # la promo de 10 hs: hasta las 20:00

        with self.assertRaisesRegex(ValueError, "ya está reservado"):
            self._reservar(cuando=_manana_a_las(15))
        # Otra PC, o "cualquier PC", sí.
        self._reservar(cuando=_manana_a_las(15), estacion="pc2")
        self._reservar(cuando=_manana_a_las(15), estacion=None)
        # La misma PC después de las 20:00, también.
        self._reservar(cuando=_manana_a_las(20), bono=self.tres_horas, monto=1500.0)

    def test_el_boton_cuenta_las_que_esperan_hoy(self):
        hora = _manana_a_las(10)
        self._reservar(cuando=hora)

        self.assertEqual(reservas_repo.reservas_de_hoy(hora - timedelta(hours=2)), 1)
        self.assertEqual(reservas_repo.reservas_de_hoy(hora + timedelta(minutes=25)), 0)
        self.assertEqual(reservas_repo.reservas_de_hoy(hora - timedelta(days=1)), 0)

    def test_la_lista_pone_primero_las_que_esperan_y_busca_sin_acentos(self):
        terminada = self._reservar(cliente="Pedro Ruiz", cuando=_manana_a_las(9))
        reservas_repo.marcar_no_vino(terminada, self.luis)
        tarde = self._reservar(cliente="Marta Gómez", estacion="pc2", cuando=_manana_a_las(18))
        temprano = self._reservar(cliente="Juan Pérez", cuando=_manana_a_las(10))

        self.assertEqual([r["id"] for r in reservas_repo.listar_reservas()], [temprano, tarde, terminada])
        self.assertEqual([r["id"] for r in reservas_repo.listar_reservas(solo_abiertas=True)], [temprano, tarde])
        self.assertEqual([r["id"] for r in reservas_repo.listar_reservas(buscar="gomez")], [tarde])
        self.assertEqual(len(reservas_repo.listar_reservas(buscar="5555 4444")), 3)


class TestDevolucion(_ConReservas):
    def test_solo_el_admin_devuelve(self):
        reserva = self._reservar(5000.0)

        with self.assertRaises(PermissionError):
            reservas_repo.devolver(reserva, self.ana, dominio.PAGO_EFECTIVO, "se cortó la luz")
        self.assertEqual(self._estado(reserva), dominio.RESERVA_PENDIENTE)

    def test_sale_de_la_caja_de_ahora_y_no_toca_el_cierre_viejo(self):
        reserva = self._reservar(5000.0)
        cierre_viejo = self._cerrar_turno(self.ana)

        devuelto = reservas_repo.devolver(reserva, self.admin, dominio.PAGO_EFECTIVO, "se cortó la luz")

        self.assertEqual(devuelto, 5000.0)
        resumen = turnos_repo.resumen_turno_actual()
        self.assertEqual(resumen["ventas_efectivo"], -5000.0)
        self.assertEqual(resumen["reservas_efectivo"], -5000.0)
        self.assertEqual(resumen["reservas_por_tipo"],
                         [{"clase": dominio.PAGO_RESERVA_DEVOLUCION, "cantidad": 1, "monto": -5000.0}])
        guardado = next(c for c in turnos_repo.listar_cierres() if c["id"] == cierre_viejo["id"])
        self.assertEqual(guardado["monto_a_retirar"], 5000.0)
        datos = reservas_repo.obtener_reserva(reserva)
        self.assertEqual((datos["estado"], datos["pagado"], datos["motivo_devolucion"]),
                         (dominio.RESERVA_DEVUELTA, 0.0, "se cortó la luz"))

    def test_una_reserva_ya_usada_no_se_devuelve(self):
        reserva = self._reservar(10000.0)
        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, [])

        with self.assertRaises(ValueError):
            reservas_repo.devolver(reserva, self.admin, dominio.PAGO_EFECTIVO, "x")


class TestEquipos(_ConReservas):
    def test_pcstream_se_reserva_con_sus_bonos_y_se_habilita_solo_ahi(self):
        reserva = self._reservar(4500.0, equipo=dominio.EQUIPO_RESERVA_PCSTREAM, estacion=None,
                                 bono=self.bono_stream)

        with self.assertRaisesRegex(ValueError, "solo ahí"):
            reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, [])
        self.assertEqual([lugar["nombre"] for lugar in reservas_habilitar_repo.lugares_para_habilitar(reserva)],
                         ["PCSTREAM"])
        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pcstream, [])

        hoy = dia_en_que_empezo_el_turno(datetime.now()).isoformat()
        self.assertEqual(pcstream_repo.uso_por_dia(hoy, hoy)["total"]["bonos"], 1)

    def test_una_reserva_de_pc_comun_no_va_a_pcstream(self):
        reserva = self._reservar(5000.0)

        with self.assertRaisesRegex(ValueError, "propios precios"):
            reservas_habilitar_repo.habilitar(reserva, self.luis, self.pcstream, _efectivo(5000.0))

    def test_pcstream_no_se_elige_como_pc_comun(self):
        with self.assertRaisesRegex(ValueError, "sus propios bonos"):
            self._reservar(estacion="pcstream")
        nombres = [opcion["nombre"] for opcion in reservas_repo.equipos_para_reservar()]
        self.assertEqual(nombres, [dominio.NOMBRE_RESERVA_CUALQUIER_PC, "PC1", "PC2", "PCSTREAM",
                                   dominio.NOMBRE_PLAYSTATION])

    def test_la_playstation_se_reserva_y_se_habilita_como_playstation(self):
        reserva = self._reservar(3000.0, equipo=dominio.EQUIPO_RESERVA_PLAYSTATION, estacion=None,
                                 bono=self.bono_ps5)
        resumen = turnos_repo.resumen_turno_actual()
        self.assertEqual((resumen["playstation_efectivo"], resumen["playstation_solo_efectivo"]), (3000.0, 0.0))

        reservas_habilitar_repo.habilitar(reserva, self.luis, None, _efectivo(3000.0))

        consola = playstation_repo.estado()
        self.assertGreater(consola["segundos_restantes"], 119 * 60)
        self.assertEqual(reservas_repo.obtener_reserva(reserva)["habilitada_en"], dominio.NOMBRE_PLAYSTATION)

    def test_la_playstation_en_uso_no_se_habilita(self):
        reserva = self._reservar(6000.0, equipo=dominio.EQUIPO_RESERVA_PLAYSTATION, estacion=None,
                                 bono=self.bono_ps5)
        playstation_repo.vender_bono(self.luis, self.bono_ps5, _efectivo(6000.0))

        self.assertEqual(reservas_habilitar_repo.lugares_para_habilitar(reserva), [])
        with self.assertRaisesRegex(ValueError, "en uso"):
            reservas_habilitar_repo.habilitar(reserva, self.luis, None, [])

    def test_cualquier_pc_se_habilita_en_una_libre(self):
        reserva = self._reservar(3000.0, estacion=None, bono=self.tres_horas)
        pcs_repo.asignar_bono(self.pc1, self.tres_horas, self.luis, _efectivo(3000.0))

        lugares = reservas_habilitar_repo.lugares_para_habilitar(reserva)
        self.assertEqual([lugar["nombre"] for lugar in lugares], ["PC2"])
        self.assertEqual(reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc2, [])["lugar"], "PC2")


class TestCajaYCierre(_ConReservas):
    def test_las_reservas_van_en_su_renglon_y_se_retira_lo_mismo(self):
        pcs_repo.asignar_bono(self.pc2, self.tres_horas, self.luis, _efectivo(3000.0))
        self._reservar(5000.0)

        resumen = turnos_repo.resumen_turno_actual()

        self.assertEqual(resumen["pcs_efectivo"], 8000.0)
        self.assertEqual(resumen["pcs_solo_efectivo"], 3000.0)
        self.assertEqual((resumen["reservas_efectivo"], resumen["reservas_digital"], resumen["reservas"]),
                         (5000.0, 0.0, 5000.0))
        self.assertEqual(resumen["reservas_por_tipo"], [{"clase": dominio.CLASE_PAGO_RESERVA_SENA, "cantidad": 1, "monto": 5000.0}])
        self.assertEqual(turnos_repo.cerrar_turno(self.luis)["monto_a_retirar"], 8000.0)

    def test_el_detalle_de_un_cierre_hecho_las_muestra_igual(self):
        self._reservar(10000.0)
        cierre = turnos_repo.cerrar_turno(self.ana)

        resumen = turnos_repo.detalle_cierre(cierre["id"])["resumen"]

        self.assertEqual((resumen["pcs_solo_efectivo"], resumen["reservas_efectivo"]), (0.0, 10000.0))
        self.assertEqual(resumen["reservas_por_tipo"], [{"clase": dominio.CLASE_PAGO_RESERVA_TOTAL, "cantidad": 1, "monto": 10000.0}])

    def test_el_detalle_del_dia_dice_que_fue_cada_pago(self):
        reserva = self._reservar(5000.0)
        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(5000.0))

        detalle = detalle_dia_repo.detalle_del_dia(dia_en_que_empezo_el_turno(datetime.now()))

        textos = [venta["detalle"] for venta in detalle["ventas"]]
        self.assertTrue(textos[0].startswith(f"Seña reserva Nº {reserva} · Juan Pérez · Promo 10 hs · PC1"), textos)
        self.assertEqual(textos[1], f"Resto reserva Nº {reserva} · Juan Pérez · Promo 10 hs · habilitada en PC1")
        self.assertEqual({v["rubro"] for v in detalle["ventas"]}, {reportes_repo.CATEGORIA_RESERVA})
        # Lo vendido: un bono, por el precio entero.
        self.assertEqual([(p["producto"], p["cantidad"], p["importe"]) for p in detalle["por_producto"]],
                         [("Promo 10 hs", 1, 10000.0)])


class TestLimpiarBase(_ConReservas):
    def test_limpiar_la_base_borra_las_reservas(self):
        reserva = self._reservar(5000.0)
        reservas_habilitar_repo.habilitar(reserva, self.luis, self.pc1, _efectivo(5000.0))

        limpieza_repo.limpiar_base(self.admin)

        with conexion_db() as conexion:
            for tabla in ("reservas", "reservas_pagos"):
                self.assertEqual(conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"], 0, tabla)


if __name__ == "__main__":
    unittest.main()
