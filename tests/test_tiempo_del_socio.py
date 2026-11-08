"""
tests/test_tiempo_del_socio.py
================================
"Que se vea claro" (pedido del dueño, 2026-11-07). Eros entró a la PC15X con unas 43 h de
saldo, la PC estaba reservada por otro a las 22:00 y el programa le pasó a la PC solo el tiempo
hasta esa hora: la PC decía 6h 33m y la ficha de Miembros 32h 18m, y nada explicaba por qué.
La regla del corte no cambia; lo que se prueba acá es que se vea:

- la reserva que corta la sesión de un socio se reconoce (reservas_horario_repo.reserva_que_corta)
  y viaja en el estado de la PC (pcs_repo.estado_estaciones, "hasta_la_reserva");
- lo que tiene cada socio en las PCs donde juega y su total (tiempo_del_socio_repo);
- la lista y la ficha de Miembros muestran el total, de dónde sale y el cartel celeste;
- el cuadro de la PC en el mosaico dice "Hasta 22:00" desde que el socio entra.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    bonos_miembro_repo, miembros_repo, pcs_repo, reservas_horario_repo, reservas_repo, tiempo_del_socio_repo,
)
from control_pcs.ui import miembros_ficha  # noqa: E402
from control_pcs.ui.miembros_ficha import ROL_DATOS  # noqa: E402
from control_pcs.ui.miembros_window import MiembrosWindow  # noqa: E402
from control_pcs.ui.pcs_detalle import texto_de_la_reserva  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Lo de Eros: 32h 18m que quedan guardadas + 11h 21m hasta la reserva.
SALDO_DE_EROS = 32 * 60 + 18 + 11 * 60 + 21
HASTA_LA_RESERVA = 11 * 60 + 21


def _en(minutos):
    """Dentro de tantos minutos, sin segundos (así se guarda una reserva)."""
    return (datetime.now() + timedelta(minutes=minutos)).replace(second=0, microsecond=0)


class _ConUnSocioYUnaReserva(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.ana = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Sergio", "1234", dominio.ROL_ADMIN)
        self.pc15 = pcs_repo.crear_estacion("PC15X")
        self.pc16 = pcs_repo.crear_estacion("PC16X")
        self.promo = pcs_repo.crear_bono("Promo 2 hs", 120, 2000.0)
        self.eros = miembros_repo.crear_miembro("Eritos", "clave123", "Eros", "44285997", "1155554444")

    def _poner_saldo(self, minutos, socio=None):
        with conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, socio or self.eros))

    def _reservar(self, inicio, estacion=None, cliente="Juan Pérez"):
        return reservas_repo.crear_reserva(
            self.ana, cliente, "11 5555-4444", dominio.EQUIPO_RESERVA_PC, estacion or self.pc15, self.promo,
            inicio, 1000.0, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000.0}],
        )

    def _entra(self, estacion=None, usuario="Eritos"):
        return miembros_repo.abrir_estacion_por_miembro(estacion or self.pc15, usuario, "clave123")

    def _estado(self, nombre):
        return next(item for item in pcs_repo.estado_estaciones() if item["estacion"]["nombre"] == nombre)

    def _miembro(self, socio=None):
        return miembros_repo.obtener_miembro(socio or self.eros)


class TestLaReservaQueCorta(_ConUnSocioYUnaReserva):
    def test_el_socio_que_entra_a_una_pc_reservada_lleva_la_reserva_en_el_estado_de_la_pc(self):
        self._poner_saldo(SALDO_DE_EROS)
        inicio = _en(HASTA_LA_RESERVA)
        self._reservar(inicio)

        self._entra()
        corte = self._estado("PC15X")["hasta_la_reserva"]

        self.assertEqual((corte["cliente"], corte["inicio"]), ("Juan Pérez", inicio))

    def test_si_le_alcanza_antes_de_la_reserva_no_hay_corte(self):
        self._poner_saldo(60)
        self._reservar(_en(180))

        self._entra()

        self.assertIsNone(self._estado("PC15X")["hasta_la_reserva"])
        # La próxima reserva se sigue viendo como siempre.
        self.assertIsNotNone(self._estado("PC15X")["reserva"])

    def test_un_bono_que_termina_a_la_hora_de_la_reserva_no_es_un_corte(self):
        # Solo se corta a los socios: a un bono se lo avisa al venderlo y decide el operador.
        self._reservar(_en(120))
        pcs_repo.asignar_bono(self.pc15, self.promo, self.ana, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 2000.0}])

        self.assertIsNone(self._estado("PC15X")["hasta_la_reserva"])

    def test_la_reserva_de_otra_pc_no_corta(self):
        self._poner_saldo(300)
        self._reservar(_en(60), estacion=self.pc16)

        self._entra()

        self.assertIsNone(self._estado("PC15X")["hasta_la_reserva"])

    def test_se_reconoce_aunque_la_sesion_termine_hasta_un_minuto_antes_de_la_hora(self):
        # La sesión se guarda en minutos enteros y sin la fracción de segundo: termina entre la
        # hora de la reserva y un minuto antes, nunca después.
        inicio = datetime(2026, 11, 6, 22, 0)
        estacion = pcs_repo.obtener_estacion(self.pc15)
        reservas = [{"equipo": dominio.EQUIPO_RESERVA_PC, "estacion_id": self.pc15, "inicio": inicio,
                     "cliente": "Juan", "miembro_id": None}]
        for fin, corta in (("2026-11-06T22:00:00", True), ("2026-11-06T21:59:00", True),
                           ("2026-11-06T21:58:59", False), ("2026-11-06T22:00:01", False)):
            sesion = {"miembro_id": self.eros, "fecha_fin_prevista": fin}
            self.assertEqual(reservas_horario_repo.reserva_que_corta(reservas, estacion, sesion) is not None, corta, fin)

    def test_su_propia_reserva_no_lo_corta(self):
        estacion = pcs_repo.obtener_estacion(self.pc15)
        inicio = datetime(2026, 11, 6, 22, 0)
        reservas = [{"equipo": dominio.EQUIPO_RESERVA_PC, "estacion_id": self.pc15, "inicio": inicio,
                     "cliente": "Eros", "miembro_id": self.eros}]
        sesion = {"miembro_id": self.eros, "fecha_fin_prevista": "2026-11-06T22:00:00"}

        self.assertIsNone(reservas_horario_repo.reserva_que_corta(reservas, estacion, sesion))

    def test_la_carga_de_saldo_mientras_juega_tambien_se_reconoce(self):
        # Le cargan 13 h jugando en una PC reservada más tarde: pasa solo hasta la reserva.
        self._poner_saldo(60)
        inicio = _en(5 * 60)
        self._reservar(inicio)
        self._entra()
        trece_horas = bonos_miembro_repo.crear_bono("13 horas", 13 * 60, 13000)

        miembros_repo.cargar_saldo_por_bono(self.eros, trece_horas, [{"metodo": "EFECTIVO", "monto": 13000}], self.ana)

        self.assertEqual(self._estado("PC15X")["hasta_la_reserva"]["inicio"], inicio)
        self.assertGreater(self._miembro()["saldo_minutos"], 0)


class TestTiempoDelSocio(_ConUnSocioYUnaReserva):
    def test_el_caso_de_eros_lo_guardado_mas_lo_de_la_pc_da_todo_su_saldo(self):
        self._poner_saldo(SALDO_DE_EROS)
        self._reservar(_en(HASTA_LA_RESERVA))

        self._entra()
        jugando = tiempo_del_socio_repo.socios_jugando()[self.eros]
        miembro = self._miembro()

        self.assertEqual([pc["estacion"] for pc in jugando["pcs"]], ["PC15X"])
        self.assertEqual(jugando["pcs"][0]["hasta_la_reserva"]["cliente"], "Juan Pérez")
        # Lo de la PC es lo mismo que marca el mosaico.
        self.assertAlmostEqual(jugando["pcs"][0]["segundos"], self._estado("PC15X")["segundos_restantes"], delta=2)
        self.assertAlmostEqual(miembro["saldo_minutos"], 32 * 60 + 18, delta=1)
        self.assertAlmostEqual(tiempo_del_socio_repo.segundos_totales(miembro, jugando), SALDO_DE_EROS * 60, delta=62)

    def test_el_que_no_juega_no_esta_y_su_total_es_su_saldo(self):
        self._poner_saldo(300)

        self.assertEqual(tiempo_del_socio_repo.socios_jugando(), {})
        self.assertEqual(tiempo_del_socio_repo.segundos_totales(self._miembro()), 300 * 60)

    def test_sin_reserva_se_lleva_todo_a_la_pc_y_el_total_no_cambia(self):
        self._poner_saldo(300)

        self._entra()
        jugando = tiempo_del_socio_repo.socios_jugando()[self.eros]

        self.assertIsNone(jugando["pcs"][0]["hasta_la_reserva"])
        self.assertEqual(self._miembro()["saldo_minutos"], 0)
        self.assertAlmostEqual(tiempo_del_socio_repo.segundos_totales(self._miembro(), jugando), 300 * 60, delta=2)

    def test_si_quedo_en_dos_pcs_de_antes_del_cambio_se_ven_las_dos(self):
        # Desde el 07/11 un socio entra a una sola PC (TestUnaSolaPcALaVez); antes podía
        # entrar a otra con lo que le quedó guardado, y la ficha lo tiene que seguir mostrando.
        self._poner_saldo(SALDO_DE_EROS)
        self._reservar(_en(HASTA_LA_RESERVA))
        self._entra()

        with conexion_db() as conexion:
            pcs_repo._abrir_o_extender_sesion(conexion, self.pc16, 12 * 60, datetime.now(), miembro_id=self.eros)
        jugando = tiempo_del_socio_repo.socios_jugando()[self.eros]

        # De la que termina antes a la que termina después.
        self.assertEqual([pc["estacion"] for pc in jugando["pcs"]], ["PC15X", "PC16X"])
        self.assertEqual(jugando["segundos_en_pcs"], sum(pc["segundos"] for pc in jugando["pcs"]))

    def test_una_sesion_que_ya_llego_a_cero_no_cuenta(self):
        self._poner_saldo(300)
        sesion_id = self._entra()["sesion_id"]
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"), sesion_id))

        self.assertEqual(tiempo_del_socio_repo.socios_jugando(), {})


class TestUnaSolaPcALaVez(_ConUnSocioYUnaReserva):
    """Pedido del dueño, 2026-11-07: "no quiero que haya multilogin". Un socio entra a una
    sola PC a la vez (miembros_repo._no_esta_jugando_en_otra_pc)."""

    def _pcs_con_sesion(self):
        with conexion_db() as conexion:
            return sorted(fila["estacion_id"] for fila in conexion.execute(
                "SELECT estacion_id FROM sesiones_pc WHERE estado = ?", (dominio.SESION_ACTIVA,)))

    def test_con_saldo_guardado_por_una_reserva_no_entra_en_otra_pc(self):
        # Lo de Eros: le quedaron 32 h guardadas y con eso podía abrir otra PC.
        self._poner_saldo(SALDO_DE_EROS)
        self._reservar(_en(HASTA_LA_RESERVA))
        self._entra()
        guardado = self._miembro()["saldo_minutos"]

        with self.assertRaises(ValueError) as error:
            self._entra(self.pc16)

        self.assertEqual(
            str(error.exception),
            "Eros ya está jugando en la PC15X: un socio entra a una sola PC a la vez. Para usar esta PC, "
            "primero cerrá la sesión en la PC15X o pedí en el mostrador que te cambien de PC.",
        )
        self.assertEqual(self._miembro()["saldo_minutos"], guardado)
        self.assertEqual(self._pcs_con_sesion(), [self.pc15])

    def test_con_todo_el_saldo_en_la_pc_le_dice_donde_juega_y_no_que_le_falta_saldo(self):
        self._poner_saldo(300)
        self._entra()

        with self.assertRaisesRegex(ValueError, "ya está jugando en la PC15X"):
            self._entra(self.pc16)

    def test_en_la_misma_pc_entra_y_le_suma_a_su_sesion(self):
        self._poner_saldo(60)
        sesion_id = self._entra()["sesion_id"]
        self._poner_saldo(60)

        self.assertEqual(self._entra()["sesion_id"], sesion_id)
        self.assertEqual(self._pcs_con_sesion(), [self.pc15])

    def test_despues_de_cerrar_la_sesion_entra_en_otra_pc(self):
        self._poner_saldo(300)
        pcs_repo.finalizar_sesion(self._entra()["sesion_id"])

        self._entra(self.pc16)

        self.assertEqual(self._pcs_con_sesion(), [self.pc16])

    def test_una_sesion_que_llego_a_cero_y_todavia_no_se_cerro_no_lo_traba(self):
        self._poner_saldo(300)
        sesion_id = self._entra()["sesion_id"]
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=1)).isoformat(timespec="seconds"), sesion_id))
        self._poner_saldo(60)

        self.assertEqual(self._entra(self.pc16)["minutos_usados"], 60)

    def test_con_la_clave_mal_no_dice_donde_esta_jugando(self):
        self._poner_saldo(300)
        self._entra()

        with self.assertRaisesRegex(ValueError, "^Usuario o contraseña incorrectos.$"):
            miembros_repo.abrir_estacion_por_miembro(self.pc16, "Eritos", "otra")

    def test_otro_socio_entra_en_otra_pc_como_siempre(self):
        luis = miembros_repo.crear_miembro("luis", "clave123", "Luis")
        self._poner_saldo(300)
        self._poner_saldo(300, luis)
        self._entra()

        self._entra(self.pc16, usuario="luis")

        self.assertEqual(self._pcs_con_sesion(), sorted([self.pc15, self.pc16]))

    def test_si_el_mostrador_lo_cambia_de_pc_sigue_jugando_en_la_nueva(self):
        self._poner_saldo(300)
        self._entra()

        pcs_repo.trasladar_sesion(self.pc15, self.pc16, self.ana)

        self.assertEqual(self._pcs_con_sesion(), [self.pc16])
        with self.assertRaisesRegex(ValueError, "ya está jugando en la PC16X"):
            self._entra(self.pc15)


class TestLosTextos(unittest.TestCase):
    """Los textos de la ficha, sin base: lo que le dice al operador."""

    AHORA = datetime(2026, 11, 6, 15, 26)

    def _jugando(self, *pcs):
        return {"pcs": list(pcs), "segundos_en_pcs": sum(pc["segundos"] for pc in pcs)}

    def _pc(self, nombre, minutos, corte=None):
        return {"estacion": nombre, "segundos": minutos * 60,
                "hasta_la_reserva": {"inicio": corte, "cliente": "Juan Pérez"} if corte else None}

    def test_con_una_reserva_dice_hasta_cuando_y_por_que(self):
        jugando = self._jugando(self._pc("PC15X", 6 * 60 + 33, datetime(2026, 11, 6, 22, 0)))

        texto = miembros_ficha.texto_de_lo_que_juega(jugando, 32 * 60 + 18, self.AHORA)

        self.assertIn("Está jugando en la PC15X: le quedan 6h 33m en la PC, hasta hoy 22:00, "
                      "porque la PC15X está reservada para Juan Pérez.", texto)
        self.assertIn("Lo guardado (32h 18m) no se descuenta mientras juega", texto)
        self.assertIn("puede seguir en otra PC", texto)
        self.assertEqual(miembros_ficha.texto_de_las_partes(jugando, 32 * 60 + 18),
                         "32h 18m guardado + 6h 33m en la PC15X")

    def test_sin_reserva_ni_guardado_dice_solo_lo_de_la_pc(self):
        jugando = self._jugando(self._pc("PC07X", 90))

        self.assertEqual(miembros_ficha.texto_de_lo_que_juega(jugando, 0, self.AHORA),
                         "Está jugando en la PC07X: le quedan 1h 30m en la PC.")
        self.assertEqual(miembros_ficha.texto_de_las_partes(jugando, 0), "todo en la PC07X")

    def test_el_cartel_de_la_carga_dice_lo_que_quedo_guardado_y_por_que(self):
        # Lo de Oscar: le cargaron 13 h y el cartel decía solo "8h 40m".
        sumado = {"estacion": "PC13X", "minutos": 8 * 60 + 40, "guardado": 4 * 60 + 20,
                  "hasta_la_reserva": datetime(2026, 11, 7, 14, 0)}

        texto = miembros_ficha.texto_de_lo_sumado(sumado, datetime(2026, 11, 7, 6, 42))

        self.assertIn("Se le sumaron 8h 40m a su sesión en PC13X", texto)
        self.assertIn("Las otras 4h 20m le quedaron guardadas en su cuenta: la PC13X está reservada hoy 14:00", texto)

    def test_si_paso_todo_a_la_pc_el_cartel_es_el_de_siempre(self):
        sumado = {"estacion": "PC07", "minutos": 13 * 60, "guardado": 0, "hasta_la_reserva": None}

        self.assertEqual(miembros_ficha.texto_de_lo_sumado(sumado),
                         "Se le sumaron 13h 00m a su sesión en PC07: le aparecen en la PC en unos segundos.")
        # Un mostrador sin actualizar no manda lo guardado: sale igual.
        self.assertNotIn("guardadas", miembros_ficha.texto_de_lo_sumado({"estacion": "PC07", "minutos": 60}))

    def test_en_dos_pcs_las_nombra_a_las_dos(self):
        jugando = self._jugando(self._pc("PC15X", 60, datetime(2026, 11, 6, 22, 0)), self._pc("PC16X", 120))

        texto = miembros_ficha.texto_de_lo_que_juega(jugando, 0, self.AHORA)

        self.assertIn("Está jugando en 2 PCs a la vez: PC15X (1h 00m, hasta hoy 22:00 por una reserva) y "
                      "PC16X (2h 00m).", texto)
        self.assertEqual(miembros_ficha.texto_de_la_lista_jugando(jugando), "Jugando · 2 PCs")


class TestLaPantallaDeMiembros(_ConUnSocioYUnaReserva):
    def _ventana(self):
        ventana = MiembrosWindow(usuarios_repo.obtener_usuario(self.ana))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def _renglon(self, ventana, usuario):
        for fila in range(ventana.lista.count()):
            datos = ventana.lista.item(fila).data(ROL_DATOS)
            if datos["miembro"]["usuario"] == usuario:
                return fila, datos
        self.fail(f"No está {usuario} en la lista")

    def test_la_ficha_de_eros_muestra_el_total_de_donde_sale_y_el_cartel(self):
        self._poner_saldo(SALDO_DE_EROS)
        self._reservar(_en(HASTA_LA_RESERVA))
        self._entra()

        ventana = self._ventana()
        fila, datos = self._renglon(ventana, "Eritos")
        ventana.lista.setCurrentRow(fila)
        ficha = ventana.ficha

        self.assertEqual(datos["jugando"]["pcs"][0]["estacion"], "PC15X")
        self.assertAlmostEqual(datos["segundos"], SALDO_DE_EROS * 60, delta=62)
        self.assertEqual(ficha.titulo_saldo.text(), "SALDO TOTAL")
        self.assertTrue(ficha.aclaracion_saldo.text().startswith("32h 1"))
        self.assertIn("guardado + 11h", ficha.aclaracion_saldo.text())
        self.assertFalse(ficha.cartel_jugando.isHidden())
        self.assertIn("reservada para Juan Pérez", ficha.texto_jugando.text())

    def test_el_que_no_juega_se_ve_como_siempre(self):
        self._poner_saldo(300)

        ventana = self._ventana()
        fila, datos = self._renglon(ventana, "Eritos")
        ventana.lista.setCurrentRow(fila)

        self.assertIsNone(datos["jugando"])
        self.assertEqual(datos["segundos"], 300 * 60)
        self.assertEqual(ventana.ficha.titulo_saldo.text(), "SALDO")
        self.assertEqual(ventana.ficha.valor_saldo.text(), "5h 00m")
        self.assertTrue(ventana.ficha.cartel_jugando.isHidden())

    def test_cargar_saldo_dice_el_saldo_con_lo_de_la_pc(self):
        from control_pcs.ui.miembros_window import DialogoCargarSaldo

        self._poner_saldo(300)
        self._entra()
        jugando = tiempo_del_socio_repo.socios_jugando()[self.eros]

        dialogo = DialogoCargarSaldo(usuarios_repo.obtener_usuario(self.ana), self._miembro(), jugando=jugando)
        self.addCleanup(dialogo.deleteLater)
        sin_jugando = DialogoCargarSaldo(usuarios_repo.obtener_usuario(self.ana), self._miembro())
        self.addCleanup(sin_jugando.deleteLater)

        def textos(ventana):
            from PySide6.QtWidgets import QLabel
            return [etiqueta.text() for etiqueta in ventana.findChildren(QLabel)]

        self.assertTrue(any(texto.startswith("Saldo actual: 4h 5") and "todo en la PC15X" in texto
                            for texto in textos(dialogo)), textos(dialogo))
        self.assertIn("Saldo actual: 0m 00s", textos(sin_jugando))

    def test_el_que_se_llevo_todo_a_la_pc_cuenta_como_con_saldo(self):
        # Antes figuraba "SIN SALDO" mientras jugaba con todo su saldo en la PC.
        self._poner_saldo(300)
        self._entra()

        ventana = self._ventana()
        ventana.segmentos.elegir("con_saldo")

        self._renglon(ventana, "Eritos")
        self.assertIn("1 CON SALDO", ventana.pastilla_con_saldo.text())

    def test_el_refresco_rearma_la_lista_si_alguien_dejo_de_jugar(self):
        self._poner_saldo(300)
        sesion_id = self._entra()["sesion_id"]
        ventana = self._ventana()
        ventana.show()
        self.addCleanup(ventana.hide)

        pcs_repo.finalizar_sesion(sesion_id)  # sale antes: se le devuelve lo que quedaba
        ventana._refrescar_lo_que_juegan()

        _, datos = self._renglon(ventana, "Eritos")
        self.assertIsNone(datos["jugando"])
        self.assertEqual(datos["segundos"], self._miembro()["saldo_minutos"] * 60)


class TestElMosaico(_ConUnSocioYUnaReserva):
    def _ficha(self, nombre):
        grilla = PanelControlPcs(usuarios_repo.obtener_usuario(self.admin))
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        for fila in range(grilla.mosaico.count()):
            if grilla.mosaico.ficha(fila).nombre == nombre:
                return grilla.mosaico.ficha(fila)
        self.fail(f"No está {nombre} en el mosaico")

    def test_la_pc_dice_hasta_que_hora_desde_que_el_socio_entra(self):
        self._poner_saldo(SALDO_DE_EROS)
        inicio = _en(HASTA_LA_RESERVA)
        self._reservar(inicio)
        pcs_repo.registrar_conexion(self.pc15)
        self._entra()

        ficha = self._ficha("PC15X")

        # Faltan más de 2 h para la reserva: antes no decía nada hasta las 20:00.
        self.assertEqual(ficha.aviso, f"Hasta {inicio:%H:%M} · Eros")
        self.assertIn("la PC está reservada para Juan Pérez", ficha.estado)
        self.assertIn("le quedó guardado", texto_de_la_reserva(self._estado("PC15X")))

    def test_sin_corte_el_socio_se_ve_con_su_nombre_como_siempre(self):
        self._poner_saldo(300)
        pcs_repo.registrar_conexion(self.pc15)
        self._entra()

        self.assertEqual(self._ficha("PC15X").aviso, "Eros")
