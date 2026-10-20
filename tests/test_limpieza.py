"""
tests/test_limpieza.py
========================
"LIMPIAR BASE DE DATOS" (repositories/limpieza_repo.py y ui/limpieza_dialogo.py),
el botón para la etapa de pruebas: borra la plata y el historial de ventas y deja
todo lo cargado. Se prueba qué se borra, qué queda, que el stock y el saldo de
los socios queden coherentes, que haya copia de seguridad antes (y que sin copia
no se borre nada), y que solo lo pueda hacer un Admin.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from repositories import (  # noqa: E402
    articulos_repo, compras_repo, limpieza_repo, reportes_repo, tramites_repo, turnos_repo,
    usuarios_repo, ventas_repo,
)
from control_pcs.repositories import (  # noqa: E402
    bonos_miembro_repo, miembros_repo, pcs_repo, pcstream_repo, playstation_repo,
)
from ui.limpieza_dialogo import DialogoLimpiarBase  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

_CATALOGOS = (
    "usuarios", "articulos", "compras", "compra_detalle", "bonos_tiempo", "bonos_pcstream",
    "bonos_playstation", "bonos_miembro", "estaciones", "miembros", "tramites", "configuracion",
)


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


def _contar(tabla, ruta=None):
    if ruta is None:
        with database.conexion_db() as conexion:
            return conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    conexion = database.abrir_archivo(ruta)
    try:
        return conexion.execute(f"SELECT COUNT(*) FROM {tabla}").fetchone()[0]
    finally:
        conexion.close()


class _ConUnDiaDePruebas(BaseConBaseTemporal):
    """Un día de pruebas con un poco de todo: ventas de kiosko (una anulada),
    bonos de PC, de PCSTREAM y de la PlayStation 5, un trámite, un socio con
    saldo cargado que abrió una PC, y un cierre de turno."""

    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.empleada_id = usuarios_repo.crear_usuario("Empleada", "1234", dominio.ROL_EMPLEADA)

        articulos_repo.crear_articulo("COCA", "Coca 500", None, None, 1000.0, 500.0, 0)
        compras_repo.registrar_compra(self.admin_id, [{"codigo": "COCA", "cantidad": 50, "costo_unitario": 500.0}])
        coca = [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": 2, "precio_unitario": 1000.0}]
        ventas_repo.confirmar_venta(self.empleada_id, coca, _efectivo(2000.0))
        anulada = ventas_repo.confirmar_venta(self.empleada_id, [{**coca[0], "cantidad": 3}], _efectivo(3000.0))
        ventas_repo.anular_venta(anulada, self.admin_id, "prueba")

        self.pc_id = pcs_repo.crear_estacion("PC 1")
        self.pc2_id = pcs_repo.crear_estacion("PC 2")
        self.pcstream_id = pcs_repo.crear_estacion("PCSTREAM")
        bono_pc = pcs_repo.crear_bono("1 hora", 60, 2000)
        bono_stream = pcstream_repo.crear_bono("1 hora stream", 60, 4000)
        bono_ps = playstation_repo.crear_bono(self.admin_id, "1 hora PS5", 60, 3000)
        pcs_repo.asignar_bono(self.pc_id, bono_pc, self.empleada_id, _efectivo(2000))
        pcs_repo.asignar_bono(self.pcstream_id, bono_stream, self.empleada_id, _efectivo(4000))
        playstation_repo.vender_bono(self.admin_id, bono_ps, _efectivo(3000))

        tramite_id = tramites_repo.crear_tramite("Boleta de luz")
        tramites_repo.registrar_tramite(self.empleada_id, tramite_id, 500.0, _efectivo(500.0))

        self.miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        bono_socio = bonos_miembro_repo.crear_bono("5 horas socio", 300, 6000)
        miembros_repo.cargar_saldo_por_bono(self.miembro_id, bono_socio, _efectivo(6000), self.empleada_id)
        miembros_repo.abrir_estacion_por_miembro(self.pc2_id, "juan", "clave123")
        with database.conexion_db() as conexion:  # que le quede saldo después de abrir la PC
            conexion.execute("UPDATE miembros SET saldo_minutos = 120 WHERE id = ?", (self.miembro_id,))

        turnos_repo.cerrar_turno(self.empleada_id)
        self.catalogos_antes = {tabla: _contar(tabla) for tabla in _CATALOGOS}


class TestLimpiarBase(_ConUnDiaDePruebas):
    def test_borra_toda_la_plata_y_el_historial_de_ventas(self):
        self.assertGreater(_contar("ventas"), 0)

        resultado = limpieza_repo.limpiar_base(self.admin_id)

        for tabla in limpieza_repo._TABLAS_A_VACIAR:
            self.assertEqual(_contar(tabla), 0, tabla)
        self.assertEqual((resultado["ventas"], resultado["cierres"], resultado["sesiones"]), (7, 1, 4))
        self.assertEqual(reportes_repo.resumen_ventas("2000-01-01", "2100-01-01")["total"], 0)
        self.assertEqual(turnos_repo.resumen_turno_actual()["ventas_total"], 0)

    def test_deja_todo_lo_cargado(self):
        limpieza_repo.limpiar_base(self.admin_id)

        self.assertEqual({tabla: _contar(tabla) for tabla in _CATALOGOS}, self.catalogos_antes)

    def test_devuelve_el_stock_de_las_ventas_confirmadas(self):
        # Compra de 50, venta de 2 (la de 3 se anuló y ya había vuelto): quedaban 48.
        self.assertEqual(articulos_repo.buscar_por_codigo("COCA")["stock"], 48)

        limpieza_repo.limpiar_base(self.admin_id)

        self.assertEqual(articulos_repo.buscar_por_codigo("COCA")["stock"], 50)

    def test_el_socio_queda_con_saldo_cero(self):
        resultado = limpieza_repo.limpiar_base(self.admin_id)

        socio = miembros_repo.obtener_miembro(self.miembro_id)
        self.assertEqual(socio["saldo_minutos"], 0)
        self.assertEqual(socio["nombre"], "Juan")
        self.assertEqual(resultado["socios_en_cero"], 1)

    def test_las_pcs_y_la_consola_quedan_libres(self):
        limpieza_repo.limpiar_base(self.admin_id)

        self.assertTrue(all(item["sesion"] is None for item in pcs_repo.estado_estaciones()))
        self.assertIsNone(playstation_repo.estado()["sesion"])

    def test_las_ventas_nuevas_vuelven_a_empezar_desde_la_1(self):
        limpieza_repo.limpiar_base(self.admin_id)

        venta_id = ventas_repo.confirmar_venta(
            self.empleada_id,
            [{"codigo": "COCA", "descripcion": "Coca 500", "cantidad": 1, "precio_unitario": 1000.0}],
            _efectivo(1000.0),
        )

        self.assertEqual(venta_id, 1)

    def test_antes_de_borrar_guarda_una_copia_con_todo(self):
        ventas_antes = _contar("ventas")

        resultado = limpieza_repo.limpiar_base(self.admin_id)

        self.assertTrue(os.path.basename(resultado["copia"]).startswith("antes_de_limpiar_base_"))
        self.assertEqual(os.path.dirname(resultado["copia"]), os.path.join(database.DATA_DIR, "backups"))
        self.assertEqual(_contar("ventas", resultado["copia"]), ventas_antes)

    def test_si_no_se_puede_hacer_la_copia_no_se_borra_nada(self):
        ventas_antes = _contar("ventas")

        with mock.patch("database._backup_consistente", side_effect=OSError("disco lleno")):
            with self.assertRaises(OSError):
                limpieza_repo.limpiar_base(self.admin_id)

        self.assertEqual(_contar("ventas"), ventas_antes)

    def test_solo_un_admin_puede_limpiar(self):
        ventas_antes = _contar("ventas")

        with self.assertRaises(PermissionError):
            limpieza_repo.limpiar_base(self.empleada_id)

        self.assertEqual(_contar("ventas"), ventas_antes)
        self.assertFalse(os.path.exists(os.path.join(database.DATA_DIR, "backups")))


class TestPantallaDeLimpieza(_ConUnDiaDePruebas):
    def _dialogo(self):
        dialogo = DialogoLimpiarBase(usuarios_repo.obtener_usuario(self.admin_id))
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_el_boton_solo_se_habilita_escribiendo_limpiar(self):
        dialogo = self._dialogo()

        self.assertFalse(dialogo.boton_limpiar.isEnabled())
        dialogo.campo_confirmacion.setText("limpia")
        self.assertFalse(dialogo.boton_limpiar.isEnabled())
        dialogo.campo_confirmacion.setText("limpiar")
        self.assertTrue(dialogo.boton_limpiar.isEnabled())

    def test_confirmado_limpia_y_avisa_donde_quedo_la_copia(self):
        dialogo = self._dialogo()
        dialogo.campo_confirmacion.setText("LIMPIAR")

        with mock.patch("ui.limpieza_dialogo.mostrar_info") as mostrar_info:
            dialogo.boton_limpiar.click()

        self.assertEqual(_contar("ventas"), 0)
        self.assertIn("antes_de_limpiar_base_", mostrar_info.call_args[0][2])

    def test_sin_escribir_limpiar_no_borra_nada(self):
        dialogo = self._dialogo()
        ventas_antes = _contar("ventas")

        dialogo._limpiar()  # lo que haría un clic si el botón no estuviera apagado

        self.assertEqual(_contar("ventas"), ventas_antes)
