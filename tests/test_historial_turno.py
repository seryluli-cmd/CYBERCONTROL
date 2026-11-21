"""
tests/test_historial_turno.py
=============================
HISTORIAL DEL TURNO (botón de debajo del mosaico, a la derecha de CONTROL DE
STOCK; pedido del dueño, 2026-11-02, maqueta A): todo lo que pasó en el turno,
en orden de hora. Las ventas son las mismas que suma el Cierre de Turno. Lo abre
cualquier operador, para revisar que no se equivocó al cobrar (2026-11-19).

Desde el 2026-11-20 muestra TODOS los movimientos, no solo las ventas (las PCs que
se abrieron, los socios, la caja y la Cuenta de la PC), y el Admin elige el día y
el turno con una barra; el operador ve solo el turno actual. Ver
repositories/historial_turno_repo.py, repositories/historial_turno_movimientos_repo.py,
ui/historial_turno_window.py y ui/historial_turno_barra.py. Las pantallas se
prueban sin abrir ninguna ventana (plataforma "offscreen" de Qt). Los turnos
anteriores y la barra del Admin, en tests/test_historial_turno_anteriores.py.
"""

import os
from datetime import datetime
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint, Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from admin_remoto import lista_blanca  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    ajustes_saldo_repo, anular_bono_repo, bonos_miembro_repo, cuentas_pc_repo, miembros_repo, pcs_repo,
    pcstream_repo, playstation_repo,
)
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import (  # noqa: E402
    articulos_repo, historial_turno_repo as repo, impresiones_repo, relevo_repo, tramites_repo, turnos_repo,
    usuarios_repo, ventas_repo,
)
from ui.historial_turno_window import (  # noqa: E402
    COLUMNA_PAGO, COLUMNA_PLATA, COLUMNA_TIEMPO, COLUMNA_TIPO, FILTRO_ANULADAS, BotonHistorialTurno,
    VentanaHistorialTurno,
)
from base import BaseConBaseTemporal, esperar_que_avance_el_reloj  # noqa: E402

_app = QApplication.instance() or QApplication([])

CLAVE_ORDENAR = "clave-de-prueba"


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _digital(monto):
    return [{"metodo": dominio.PAGO_DIGITAL, "monto": monto}]


def esperar_al_segundo_siguiente():
    """Lo que vuelve al saldo del socio, ORDENAR SALDOS y la hora en que se anuló
    una venta se graban sin fracciones de segundo, y el cierre con ellas: algo
    hecho en el MISMO segundo del cierre queda "antes" del cierre y cae en el turno
    cerrado. En el mostrador nunca pasa (entre un cierre y lo que sigue siempre
    pasa una persona); en una prueba, todo pasa en el mismo segundo."""
    antes = datetime.now().replace(microsecond=0)
    while datetime.now().replace(microsecond=0) <= antes:
        pass


class BaseHistorial(BaseConBaseTemporal):
    """Un turno de Lucía con de todo: lo de antes del último cierre no es de este turno."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        self.lucia_id = usuarios_repo.crear_usuario("LUCIA", "4321", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 0)
        articulos_repo.crear_articulo("PANCHO", "Pancho", None, None, 1200.0, 500.0, 0)
        articulos_repo.crear_articulo(dominio.CODIGO_ARTICULO_IMPRESIONES, "Impresión B/N", None, None,
                                      200.0, 0.0, 0)
        self.pc = pcs_repo.crear_estacion("PC12X")
        self.pc14 = pcs_repo.crear_estacion("PC14X")
        self.pc15 = pcs_repo.crear_estacion("PC15X")
        self.pcstream = pcs_repo.crear_estacion(dominio.NOMBRE_PCSTREAM)
        self.bono_pc = pcs_repo.crear_bono("Promo 5hs", 300, 8000.0)
        self.bono_stream = pcstream_repo.crear_bono("1 hora", 60, 2000.0)
        self.bono_ps5 = playstation_repo.crear_bono(self.admin_id, "Promo 2hs", 120, 6000.0)
        self.bono_socio = bonos_miembro_repo.crear_bono("Promo 10hs", 600, 9700.0)
        self.tramite = tramites_repo.crear_tramite("Turno ANSES")
        self.socio = miembros_repo.crear_miembro("ulises", "1111", nombre="Ulises")
        self.ana = miembros_repo.crear_miembro("ana", "clave123", "Ana Pérez", "30111222", "1155554444")

    def vender_coca(self, usuario_id, cantidad=1, pagos=None):
        return ventas_repo.confirmar_venta(
            usuario_id, [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": cantidad,
                          "precio_unitario": 1000.0}],
            pagos or _efectivo(1000.0 * cantidad),
        )

    def turno_con_de_todo(self):
        """Un turno cerrado de antes (no tiene que salir) y el de Lucía, abierto."""
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)
        self.v_de_antes = self.vender_coca(self.lucia_id, 5)
        self.cierre_de_antes = turnos_repo.cerrar_turno(self.lucia_id)["id"]
        # Lo que sigue va después del cierre, como en el mostrador: sin esto, en
        # Windows una venta podía quedar con la MISMA hora del cierre y no entrar
        # al turno nuevo (fallaba 1 de cada 10 corridas, revisión del 2026-11-16).
        esperar_que_avance_el_reloj()
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)

        self.v_kiosko = self.vender_coca(self.lucia_id, 2)
        self.v_pc = pcs_repo.asignar_bono(self.pc, self.bono_pc, self.lucia_id, _efectivo(8000.0))
        self.v_stream = pcs_repo.asignar_bono(self.pcstream, self.bono_stream, self.lucia_id, _digital(2000.0))
        self.v_ps5 = playstation_repo.vender_bono(self.lucia_id, 1, self.bono_ps5, _efectivo(6000.0))
        self.v_socio = miembros_repo.cargar_saldo_por_bono(
            self.socio, self.bono_socio, _digital(9700.0), self.lucia_id)["venta_id"]
        self.v_carga = miembros_repo.cargar_saldo_por_monto(
            self.socio, 3000.0, _efectivo(3000.0), self.lucia_id)["venta_id"]
        self.v_tramite = tramites_repo.registrar_tramite(self.lucia_id, self.tramite, 1500.0, _efectivo(1500.0))
        self.v_impresiones = impresiones_repo.cobrar_impresiones(self.lucia_id, 14, 200.0, _efectivo(2800.0))
        self.v_mixta = ventas_repo.confirmar_venta(
            self.lucia_id,
            [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": 1, "precio_unitario": 1000.0},
             {"codigo": dominio.CODIGO_ARTICULO_IMPRESIONES, "descripcion": "Impresión B/N", "cantidad": 2,
              "precio_unitario": 200.0}],
            [{"metodo": dominio.PAGO_EFECTIVO, "monto": 700.0}, {"metodo": dominio.PAGO_DIGITAL, "monto": 700.0}],
        )
        self.v_repetida = pcs_repo.asignar_bono(self.pc, self.bono_pc, self.lucia_id, _efectivo(8000.0))
        anular_bono_repo.anular_bono(self.v_repetida, self.admin_id, "cargado 2 veces")
        # El Admin cobra con la caja de Lucía abierta: queda a nombre de ella.
        self.v_admin = self.vender_coca(self.admin_id, 1)

    def historial(self, cierre_id=None):
        return repo.historial_del_turno(self.admin_id, cierre_id)

    def venta(self, historial, venta_id):
        return next(v for v in historial["ventas"] if v["id"] == venta_id)

    def de_tipo(self, historial, tipo):
        return [m for m in historial["movimientos"] if m["tipo"] == tipo]


class TestQueSeCobro(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()

    def test_cada_venta_con_su_rubro_y_lo_que_se_cobro(self):
        historial = self.historial()
        esperado = {
            self.v_kiosko: (repo.RUBRO_KIOSKO, "2 x Coca 500"),
            self.v_pc: (repo.RUBRO_BONO_PC, "PC12X · Promo 5hs (5 h)"),
            self.v_stream: (repo.RUBRO_PCSTREAM, f"{dominio.NOMBRE_PCSTREAM} · 1 hora (1 h)"),
            self.v_ps5: (repo.RUBRO_PS5, f"{dominio.nombre_consola(1)} · Promo 2hs (2 h)"),
            self.v_socio: (repo.RUBRO_MIEMBRO, "Socio Ulises · Promo 10hs (10 h)"),
            self.v_tramite: (repo.RUBRO_TRAMITE, "Trámite: Turno ANSES"),
            self.v_impresiones: (repo.RUBRO_IMPRESIONES, "14 x Impresión B/N"),
        }
        for venta_id, (rubro, detalle) in esperado.items():
            venta = self.venta(historial, venta_id)
            self.assertEqual((venta["rubro"], venta["detalle"]), (rubro, detalle))
        carga = self.venta(historial, self.v_carga)
        self.assertEqual(carga["rubro"], repo.RUBRO_MIEMBRO)
        self.assertTrue(carga["detalle"].startswith("Socio Ulises · carga de saldo ("), carga["detalle"])

    def test_impresiones_con_otra_cosa_es_kiosko_pero_sale_al_filtrar_impresiones(self):
        mixta = self.venta(self.historial(), self.v_mixta)
        self.assertEqual(mixta["rubro"], repo.RUBRO_KIOSKO)
        self.assertEqual(set(mixta["rubros"]), {repo.RUBRO_KIOSKO, repo.RUBRO_IMPRESIONES})

    def test_lo_de_antes_del_ultimo_cierre_no_es_de_este_turno(self):
        ids = [venta["id"] for venta in self.historial()["ventas"]]
        self.assertNotIn(self.v_de_antes, ids)
        self.assertEqual(ids, sorted(ids))   # de la primera a la última

    def test_hora_y_forma_de_pago(self):
        historial = self.historial()
        self.assertEqual(self.venta(historial, self.v_pc)["pago"], repo.PAGO_EFECTIVO)
        self.assertEqual(self.venta(historial, self.v_stream)["pago"], repo.PAGO_DIGITAL)
        self.assertEqual(self.venta(historial, self.v_mixta)["pago"], repo.PAGO_LOS_DOS)
        venta = self.venta(historial, self.v_pc)
        self.assertEqual(venta["hora"], datetime.fromisoformat(venta["fecha"]).strftime("%H:%M"))

    def test_la_anulada_dice_quien_cuando_y_por_que_y_no_suma(self):
        historial = self.historial()
        repetida = self.venta(historial, self.v_repetida)
        self.assertTrue(repetida["anulada"])
        self.assertRegex(repetida["nota"], r"^anulada por Duenio a las \d\d:\d\d: cargado 2 veces$")
        self.assertEqual(historial["anuladas"], 1)
        self.assertEqual(historial["cantidad"], len(historial["ventas"]) - 1)

    def test_lo_que_cobro_el_admin_queda_en_la_caja_de_ella_y_lo_dice(self):
        venta = self.venta(self.historial(), self.v_admin)
        self.assertEqual(venta["operador"], "LUCIA")
        self.assertEqual(venta["nota"], "cobró Duenio")

    def test_el_total_es_el_mismo_que_el_del_cierre_de_turno(self):
        historial = self.historial()
        cierre = turnos_repo.resumen_turno_actual()
        self.assertEqual(historial["total"], cierre["ventas_total"])
        self.assertEqual(historial["efectivo"], cierre["ventas_efectivo"])
        self.assertEqual(historial["digital"], cierre["ventas_digital"])
        self.assertEqual(historial["total"], 2000 + 8000 + 2000 + 6000 + 9700 + 3000 + 1500 + 2800 + 1400 + 1000)

    def test_la_caja_de_quien_agarro_el_turno(self):
        historial = self.historial()
        caja = relevo_repo.estado_de_la_caja()
        self.assertEqual(historial["caja_numero"], caja["caja_numero"])
        self.assertEqual(historial["responsable"], "LUCIA")
        self.assertRegex(historial["abrio_a_las"], r"^\d\d:\d\d$")
        self.assertEqual(historial["turno_label"], caja["turno_label"])


class TestQueFueCadaVenta(BaseHistorial):
    """Pedido del dueño (2026-11-20): también las habilitaciones. Una venta que dio
    tiempo dice si prendió el equipo o le sumó, y cuánto."""

    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()

    def test_el_bono_que_prende_el_equipo_y_el_que_le_suma(self):
        historial = self.historial()
        abrio = self.venta(historial, self.v_pc)
        self.assertEqual((abrio["tipo"], abrio["tiempo"]), (repo.TIPO_PC_ABIERTA, "+ 5 h"))
        self.assertEqual(set(abrio["grupos"]), {repo.GRUPO_VENTAS, repo.GRUPO_HABILITACIONES})
        self.assertEqual(self.venta(historial, self.v_stream)["tipo"], repo.TIPO_PCSTREAM)
        self.assertEqual(self.venta(historial, self.v_ps5)["tipo"], repo.TIPO_PS5)
        # La repetida fue a la PC que ya estaba abierta: le sumó tiempo (y se anuló).
        repetida = self.venta(historial, self.v_repetida)
        self.assertEqual(repetida["tipo"], repo.TIPO_MAS_TIEMPO)
        self.assertEqual(historial["pcs_abiertas"], 3)

    def test_la_carga_de_un_socio_va_a_su_saldo(self):
        historial = self.historial()
        carga = self.venta(historial, self.v_socio)
        self.assertEqual((carga["tipo"], carga["tiempo"]), (repo.TIPO_CARGA_SOCIO, "+ 10 h al saldo"))
        self.assertEqual(set(carga["grupos"]), {repo.GRUPO_VENTAS, repo.GRUPO_SALDO})

    def test_lo_que_no_da_tiempo_va_con_su_rubro(self):
        historial = self.historial()
        self.assertEqual(self.venta(historial, self.v_kiosko)["tipo"], repo.RUBRO_KIOSKO)
        self.assertEqual(self.venta(historial, self.v_tramite)["tipo"], repo.RUBRO_TRAMITE)
        self.assertEqual(self.venta(historial, self.v_kiosko)["grupos"], (repo.GRUPO_VENTAS,))
        venta = self.venta(historial, self.v_kiosko)
        self.assertEqual((venta["plata"], venta["clase_plata"]), (2000.0, repo.PLATA_ENTRA))

    def test_la_apertura_de_la_caja_esta_en_la_lista(self):
        historial = self.historial()
        [caja] = self.de_tipo(historial, repo.TIPO_CAJA)
        self.assertEqual(caja["detalle"], f"LUCIA abrió la Caja Nº {historial['caja_numero']} · cambio $ 20.000, "
                                          "contado justo")
        self.assertIsNone(caja["plata"])
        self.assertEqual(caja["grupos"], (repo.GRUPO_CAJA,))
        # Va primero: se abrió antes de vender.
        self.assertEqual(historial["movimientos"][0]["tipo"], repo.TIPO_CAJA)

    def test_todo_en_orden_de_hora(self):
        movimientos = self.historial()["movimientos"]
        momentos = [datetime.fromisoformat(m["fecha"]) for m in movimientos]
        self.assertEqual(momentos, sorted(momentos))
        self.assertEqual(len(movimientos), len(self.historial()["ventas"]) + 1)


class TestTodosLosMovimientos(BaseHistorial):
    """Lo que no es una venta: el socio con su saldo, el pase de PC, la Cuenta de la
    PC, ORDENAR SALDOS, el relevo."""

    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()
        parche = mock.patch.object(ajustes_saldo_repo, "CLAVE_ORDENAR_SALDOS", database.hash_clave(CLAVE_ORDENAR))
        parche.start()
        self.addCleanup(parche.stop)

    def test_el_socio_que_entra_con_su_saldo_y_lo_que_le_vuelve_al_irse(self):
        miembros_repo.cargar_saldo_por_bono(self.ana, self.bono_socio, _efectivo(9700.0), self.lucia_id)
        sesion = miembros_repo.abrir_estacion_por_miembro(self.pc14, "ana", "clave123")["sesion_id"]
        esperar_al_segundo_siguiente()
        pcs_repo.finalizar_sesion(sesion, dominio.CIERRE_FINALIZAR, self.lucia_id)
        historial = self.historial()
        [entro] = self.de_tipo(historial, repo.TIPO_SOCIO_ENTRO)
        self.assertEqual(entro["detalle"], "Ana Pérez entró en PC14X con su saldo")
        self.assertEqual((entro["pago"], entro["tiempo"]), (repo.PAGO_SALDO_DEL_SOCIO, "usa 10 h"))
        self.assertIsNone(entro["plata"])
        self.assertEqual(set(entro["grupos"]), {repo.GRUPO_HABILITACIONES, repo.GRUPO_SALDO})
        [devuelto] = self.de_tipo(historial, repo.TIPO_SALDO_DEVUELTO)
        self.assertEqual(devuelto["detalle"], "Ana Pérez se fue de PC14X: lo que no usó vuelve a su saldo")
        self.assertRegex(devuelto["tiempo"], r"^\+ .+ al saldo$")
        self.assertEqual(historial["pcs_abiertas"], 4)

    def test_el_pase_de_una_pc_a_otra(self):
        pcs_repo.trasladar_sesion(self.pc, self.pc15, self.lucia_id)
        [pase] = self.de_tipo(self.historial(), repo.TIPO_TRASLADO)
        self.assertEqual(pase["detalle"], "PC12X pasó a PC15X, con el tiempo que le quedaba")
        self.assertEqual(pase["nota"], "lo hizo LUCIA")
        self.assertEqual(pase["grupos"], (repo.GRUPO_HABILITACIONES,))

    def test_lo_anotado_a_la_cuenta_y_cuando_se_cobra(self):
        pancho = [{"codigo": "PANCHO", "descripcion": "Pancho", "cantidad": 1, "precio_unitario": 1200.0}]
        cuentas_pc_repo.anotar_articulos(self.pc, pancho, self.lucia_id, nombre="Pedro")
        total_antes = self.historial()["total"]
        [anotado] = self.de_tipo(self.historial(), repo.TIPO_A_CUENTA)
        self.assertEqual(anotado["detalle"], "PC12X: 1 x Pancho anotado a la Cuenta de la PC")
        self.assertEqual((anotado["plata"], anotado["clase_plata"]), (1200.0, repo.PLATA_CUENTA))
        self.assertEqual(anotado["pago"], repo.PAGO_A_CUENTA)

        cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc)[0]["id"]
        [venta_id] = cuentas_pc_repo.cobrar([cuenta], self.lucia_id, _efectivo(1200.0))
        historial = self.historial()
        cobrada = self.venta(historial, venta_id)
        self.assertEqual(cobrada["tipo"], repo.TIPO_CUENTA_COBRADA)
        self.assertEqual(cobrada["nota"], "de la Cuenta de PC12X")
        self.assertEqual(set(cobrada["grupos"]), {repo.GRUPO_VENTAS, repo.GRUPO_CAJA})
        # Lo anotado no sumaba: entra a la caja al cobrarse.
        self.assertEqual(historial["total"], total_antes + 1200.0)

    def test_lo_anotado_antes_de_pasarlo_de_pc_dice_la_pc_de_ese_momento(self):
        pancho = [{"codigo": "PANCHO", "descripcion": "Pancho", "cantidad": 1, "precio_unitario": 1200.0}]
        cuentas_pc_repo.anotar_articulos(self.pc, pancho, self.lucia_id, nombre="Pedro")
        esperar_que_avance_el_reloj()
        pcs_repo.trasladar_sesion(self.pc, self.pc15, self.lucia_id)
        esperar_que_avance_el_reloj()
        cuenta = cuentas_pc_repo.cuentas_de_la_estacion(self.pc15)[0]["id"]
        [venta_id] = cuentas_pc_repo.cobrar([cuenta], self.lucia_id, _efectivo(1200.0))
        historial = self.historial()
        [anotado] = self.de_tipo(historial, repo.TIPO_A_CUENTA)
        self.assertEqual(anotado["detalle"], "PC12X: 1 x Pancho anotado a la Cuenta de la PC")
        self.assertEqual(self.venta(historial, venta_id)["nota"], "de la Cuenta de PC15X")

    def test_un_renglon_quitado_de_la_cuenta_sale_tachado(self):
        pancho = [{"codigo": "PANCHO", "descripcion": "Pancho", "cantidad": 1, "precio_unitario": 1200.0}]
        cuentas_pc_repo.anotar_articulos(self.pc, pancho, self.lucia_id, nombre="Pedro")
        renglon = cuentas_pc_repo.cuentas_de_la_estacion(self.pc)[0]["renglones"][0]["id"]
        cuentas_pc_repo.quitar_renglon(renglon, self.admin_id, "se equivocó de PC")
        historial = self.historial()
        [anotado] = self.de_tipo(historial, repo.TIPO_A_CUENTA)
        self.assertTrue(anotado["anulada"])
        self.assertRegex(anotado["nota"], r"^quitado por Duenio a las \d\d:\d\d: se equivocó de PC$")
        self.assertEqual(historial["anuladas"], 2)

    def test_ordenar_saldos(self):
        esperar_al_segundo_siguiente()
        ajustes_saldo_repo.sumar(self.admin_id, self.ana, 90, CLAVE_ORDENAR)
        [ajuste] = self.de_tipo(self.historial(), repo.TIPO_ORDENAR_SALDOS)
        self.assertEqual(ajuste["detalle"], "Duenio cambió el saldo de Ana Pérez: de 0 min a 1 h 30 min")
        self.assertEqual(ajuste["tiempo"], "+ 1 h 30 min al saldo")
        self.assertEqual(ajuste["grupos"], (repo.GRUPO_SALDO,))

    def test_el_relevo_con_lo_que_falto(self):
        caja = relevo_repo.estado_de_la_caja()["caja_numero"]
        marta = usuarios_repo.crear_usuario("MARTA", "5555", dominio.ROL_EMPLEADA)
        with conexion_db() as conexion:
            conexion.execute(
                "INSERT INTO relevos_caja (caja_id, fecha, de_usuario_id, a_usuario_id, monto_esperado, "
                "monto_contado, diferencia) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (caja, datetime.now().isoformat(timespec="microseconds"), self.lucia_id, marta,
                 38600.0, 38500.0, -100.0))
        [relevo] = self.de_tipo(self.historial(), repo.TIPO_RELEVO)
        self.assertEqual(relevo["detalle"], f"MARTA recibió la Caja Nº {caja} de LUCIA · había que tener "
                                            "$ 38.600, contó $ 38.500")
        self.assertEqual((relevo["plata"], relevo["clase_plata"]), (-100.0, repo.PLATA_DIFERENCIA))


class TestQuienLoVe(BaseHistorial):
    def test_la_empleada_ve_lo_mismo_que_el_admin(self):
        # Pedido del dueño (2026-11-19): que los operadores revisen que no se equivocaron.
        self.turno_con_de_todo()
        de_ella = repo.historial_del_turno(self.lucia_id)
        del_admin = self.historial()
        # Lo único distinto: el Admin puede mirar otros turnos (2026-11-20).
        self.assertFalse(de_ella.pop("puede_mirar_otros"))
        self.assertTrue(del_admin.pop("puede_mirar_otros"))
        self.assertEqual(de_ella, del_admin)
        self.assertEqual(de_ella["responsable"], "LUCIA")
        # Ve también las anuladas, con quién y por qué: así se entera de lo que le corrigieron.
        self.assertRegex(self.venta(de_ella, self.v_repetida)["nota"],
                         r"^anulada por Duenio a las \d\d:\d\d: cargado 2 veces$")

    def test_un_operador_dado_de_baja_no_lo_ve(self):
        otro = usuarios_repo.crear_usuario("MARTA", "5555", dominio.ROL_EMPLEADA)
        usuarios_repo.desactivar_usuario(otro)
        with self.assertRaisesRegex(PermissionError, "ya no está habilitado"):
            repo.historial_del_turno(otro)

    def test_se_puede_mirar_desde_otra_pc_a_nombre_del_que_entro(self):
        for funcion in ("historial_del_turno", "turnos_del_dia"):
            with self.subTest(funcion=funcion):
                self.assertTrue(lista_blanca.permitida("historial_turno_repo", funcion))
                self.assertEqual(lista_blanca.ACTOR[("historial_turno_repo", funcion)], "usuario_id")

    def test_sin_caja_abierta_es_lo_vendido_desde_el_ultimo_cierre(self):
        venta = self.vender_coca(self.lucia_id)
        historial = self.historial()
        self.assertIsNone(historial["caja_numero"])
        self.assertEqual([v["id"] for v in historial["ventas"]], [venta])


class TestVentana(BaseHistorial):
    def setUp(self):
        super().setUp()
        self.turno_con_de_todo()

    def ventana(self, usuario_id=None):
        ventana = VentanaHistorialTurno(usuario_id or self.admin_id)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def filas(self, ventana, columna):
        return [ventana.tabla.item(fila, columna).text() for fila in range(ventana.tabla.rowCount())]

    def elegir(self, ventana, texto, filtros=None):
        filtros = filtros or ventana.filtros
        next(p for p in filtros.pastillas if p.text() == texto.upper()).click()

    def test_muestra_todo_el_turno_con_la_caja_arriba(self):
        ventana = self.ventana()
        historial = self.historial()
        self.assertEqual(ventana.tabla.rowCount(), len(historial["movimientos"]))
        self.assertIn(f"Caja Nº {historial['caja_numero']} de LUCIA · Turno ", ventana.etiqueta.text())
        anulada = [m["venta_id"] for m in historial["movimientos"]].index(self.v_repetida)
        self.assertEqual(ventana.tabla.item(anulada, COLUMNA_PAGO).text(), "ANULADA")
        self.assertTrue(ventana.tabla.item(anulada, COLUMNA_PLATA).font().strikeOut())
        self.assertEqual(ventana.tabla.item(0, COLUMNA_PLATA).textAlignment(), Qt.AlignRight | Qt.AlignVCenter)
        self.assertEqual(ventana.indicador_pcs.valor.text(), "3")
        self.assertFalse(ventana.aviso.isVisibleTo(ventana))
        self.assertFalse(ventana.pastilla_cerrado.isVisibleTo(ventana))

    def test_columnas_que_fue_tiempo_y_plata(self):
        ventana = self.ventana()
        movimientos = self.historial()["movimientos"]
        fila = [m["venta_id"] for m in movimientos].index(self.v_pc)
        self.assertEqual(ventana.tabla.item(fila, COLUMNA_TIPO).text(), repo.TIPO_PC_ABIERTA)
        self.assertEqual(ventana.tabla.item(fila, COLUMNA_TIEMPO).text(), "+ 5 h")
        self.assertEqual(ventana.tabla.item(fila, COLUMNA_PLATA).text(), "$ 8.000")
        caja = 0   # la apertura de la caja: no movió plata
        self.assertEqual(ventana.tabla.item(caja, COLUMNA_PLATA).text(), "—")

    def test_las_pastillas_por_tipo(self):
        ventana = self.ventana()
        self.elegir(ventana, "Habilitaciones")
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [
            repo.TIPO_PC_ABIERTA, repo.TIPO_PCSTREAM, repo.TIPO_PS5, repo.TIPO_MAS_TIEMPO])
        self.elegir(ventana, "Saldo de socios")
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [repo.TIPO_CARGA_SOCIO] * 2)
        self.elegir(ventana, "Caja y Cuenta")
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [repo.TIPO_CAJA])
        self.elegir(ventana, "Anuladas")
        self.assertEqual(ventana._grupo, FILTRO_ANULADAS)
        self.assertEqual(self.filas(ventana, COLUMNA_PAGO), ["ANULADA"])
        self.elegir(ventana, "Todo")
        self.assertEqual(ventana.tabla.rowCount(), len(self.historial()["movimientos"]))

    def test_al_tocar_ventas_aparecen_los_rubros(self):
        ventana = self.ventana()
        self.assertFalse(ventana.filtros_rubros.isVisibleTo(ventana))
        self.elegir(ventana, "Ventas")
        self.assertTrue(ventana.filtros_rubros.isVisibleTo(ventana))
        self.assertEqual(ventana.tabla.rowCount(), len(self.historial()["ventas"]))
        self.elegir(ventana, "Miembros", ventana.filtros_rubros)
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [repo.TIPO_CARGA_SOCIO] * 2)
        self.assertEqual(ventana.etiqueta_visible.text(), "2 movimientos · 2 ventas · $ 12.700")
        self.elegir(ventana, "Bonos de PC", ventana.filtros_rubros)
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [repo.TIPO_PC_ABIERTA, repo.TIPO_MAS_TIEMPO])
        # La repetida se ve (en rojo) pero no suma.
        self.assertEqual(ventana.etiqueta_visible.text(), "2 movimientos · 1 venta · $ 8.000")
        self.elegir(ventana, "Impresiones", ventana.filtros_rubros)
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [repo.RUBRO_IMPRESIONES, repo.RUBRO_KIOSKO])
        # Otra pastilla de arriba: los rubros se van y dejan de filtrar.
        self.elegir(ventana, "Habilitaciones")
        self.assertFalse(ventana.filtros_rubros.isVisibleTo(ventana))
        self.assertIsNone(ventana._rubro)

    def test_el_buscador_no_mira_mayusculas_ni_acentos(self):
        ventana = self.ventana()
        ventana.buscador.setText("ulises")
        self.assertEqual(ventana.tabla.rowCount(), 2)
        ventana.buscador.setText("TRAMITE")
        self.assertEqual(self.filas(ventana, COLUMNA_TIPO), [repo.RUBRO_TRAMITE])

    def test_imprime_lo_que_se_ve(self):
        ventana = self.ventana()
        self.elegir(ventana, "Ventas")
        self.elegir(ventana, "Miembros", ventana.filtros_rubros)
        html = ventana.html_para_imprimir(datetime(2026, 11, 2, 2, 30))
        self.assertIn("Historial del Turno", html)
        self.assertIn("Impreso el 02/11/2026 02:30", html)
        self.assertIn("solo Ventas de Miembros", html)
        self.assertIn("Socio Ulises", html)
        self.assertNotIn("Coca 500", html)
        self.assertIn("$ 12.700", html)
        with mock.patch("ui.historial_turno_window.imprimir.vista_previa") as vista_previa:
            ventana.boton_imprimir.click()
        vista_previa.assert_called_once()
        self.assertEqual(vista_previa.call_args.args[2], "Historial del Turno")

    def test_el_operador_no_tiene_la_barra(self):
        # "El operador solo puede ver su turno actual" (pedido del dueño, 2026-11-20).
        self.assertIsNone(self.ventana(self.lucia_id).barra)
        del_admin = self.ventana()
        self.assertTrue(del_admin.barra.isVisibleTo(del_admin))


class TestTurnoVacio(BaseHistorial):
    def ventana(self):
        ventana = VentanaHistorialTurno(self.admin_id)
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_sin_nada_desde_el_ultimo_cierre_lo_dice_en_vez_de_la_lista_en_blanco(self):
        ventana = self.ventana()
        self.assertEqual(ventana.paginas.currentIndex(), 1)
        self.assertEqual(ventana.titulo_vacio.text(), "No hubo movimientos desde el último Cierre de Turno")
        self.assertIn("Todavía no hubo ningún Cierre de Turno.", ventana.detalle_vacio.text())
        self.assertFalse(ventana.boton_imprimir.isEnabled())

    def test_dice_cuando_fue_el_ultimo_cierre(self):
        self.vender_coca(self.lucia_id)
        turnos_repo.cerrar_turno(self.lucia_id)
        esperar_que_avance_el_reloj()
        ventana = self.ventana()
        self.assertEqual(ventana.paginas.currentIndex(), 1)
        self.assertRegex(ventana.detalle_vacio.text(), r"^El último cierre fue el \w+ \d\d/\d\d a las \d\d:\d\d\.")

    def test_con_la_caja_recien_abierta_se_ve_la_apertura(self):
        relevo_repo.abrir_caja(self.lucia_id, cambio_contado=20000.0)
        ventana = self.ventana()
        self.assertEqual(ventana.paginas.currentIndex(), 0)
        self.assertEqual(ventana.tabla.rowCount(), 1)
        self.assertEqual(ventana.etiqueta_visible.text(), "1 movimiento · 0 ventas · $ 0")


class TestBoton(BaseHistorial):
    def boton(self, usuario_id):
        boton = BotonHistorialTurno(usuarios_repo.obtener_usuario(usuario_id))
        self.addCleanup(boton.deleteLater)
        return boton

    def test_lo_ven_todos_igual(self):
        for usuario_id in (self.admin_id, self.lucia_id):
            boton = self.boton(usuario_id)
            self.assertEqual(boton.text(), "📋  HISTORIAL DEL TURNO")
            self.assertEqual(boton.property("clase"), "barra")
            self.assertTrue(boton.isEnabled())

    def test_lo_abren_todos_cada_uno_a_su_nombre(self):
        with mock.patch("ui.historial_turno_window.VentanaHistorialTurno") as ventana:
            self.boton(self.lucia_id).click()
            self.boton(self.admin_id).click()
        self.assertEqual([llamada.args[0] for llamada in ventana.call_args_list], [self.lucia_id, self.admin_id])

    def test_la_empleada_lo_abre_de_verdad(self):
        self.turno_con_de_todo()
        ventana = VentanaHistorialTurno(self.lucia_id)
        self.addCleanup(ventana.deleteLater)
        self.assertEqual(ventana.tabla.rowCount(), len(self.historial()["movimientos"]))
        self.assertIn("Caja Nº", ventana.etiqueta.text())

    def test_va_pegado_a_la_derecha_de_control_de_stock(self):
        panel = PanelControlPcs(usuarios_repo.obtener_usuario(self.lucia_id))
        panel.detener_actualizacion()
        self.addCleanup(panel.deleteLater)
        panel.setAttribute(Qt.WA_DontShowOnScreen)
        panel.resize(1600, 900)
        panel.show()
        self.addCleanup(panel.hide)
        _app.processEvents()

        stock = panel.boton_control_stock
        historial = panel.boton_historial_turno
        borde_de_stock = stock.mapTo(panel, QPoint(stock.width(), 0))
        inicio_de_historial = historial.mapTo(panel, QPoint(0, 0))
        self.assertTrue(0 <= inicio_de_historial.x() - borde_de_stock.x() < 20,
                        (borde_de_stock.x(), inicio_de_historial.x()))
        self.assertLessEqual(abs((inicio_de_historial.y() + historial.height() / 2)
                                 - (borde_de_stock.y() + stock.height() / 2)), 3)
