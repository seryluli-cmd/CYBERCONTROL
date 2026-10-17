"""
tests/test_ip_asentada.py
===========================
La IP asentada de cada estación (pedido del dueño, 2026-10-17): la primera vez
que una PC se enlaza, su IP queda asentada y no se pisa sola; el servidor
reconoce a cada PC primero por el nombre que manda su Cliente PC y, si ninguna
estación se llama así, por esa IP. Sin tocar el Cliente PC.

- `pcs_repo`: cuándo se asienta, la prioridad del nombre, la IP repetida (no
  adivina), las estaciones desactivadas y "Borrar IP".
- `servidor_red.py`: con el servidor real, como los demás tests de la capa HTTP
  (el pedido llega desde 127.0.0.1).
- La pantalla Gestionar Estaciones (Qt "offscreen", sin abrir ventanas).

Se ejecutan con:

    python -m unittest discover tests
"""

import os
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from control_pcs.repositories import pcs_repo  # noqa: E402
from control_pcs.ui import pcs_gestion_dialogos  # noqa: E402

_app = QApplication.instance() or QApplication([])

IP_PC1 = "192.168.1.11"
IP_PC2 = "192.168.1.12"


def _ips(estacion_id):
    estacion = pcs_repo.obtener_estacion(estacion_id)
    return estacion["ip_asentada"], estacion["ultima_ip"]


def _reconocida(nombre, ip):
    """El nombre de la estación con la que el servidor reconoce ese pedido, o None."""
    item = pcs_repo.estado_de_estacion(nombre, ip)
    return item["estacion"]["nombre"] if item is not None else None


class TestAsentarLaIp(BaseConBaseTemporal):
    def test_el_primer_enlace_asienta_la_ip_y_los_siguientes_no_la_pisan(self):
        pc1 = pcs_repo.crear_estacion("PC1")
        self.assertEqual(_ips(pc1), (None, None))

        pcs_repo.registrar_conexion(pc1, IP_PC1)
        self.assertEqual(_ips(pc1), (IP_PC1, IP_PC1))

        pcs_repo.registrar_conexion(pc1, "192.168.1.99")
        self.assertEqual(_ips(pc1), (IP_PC1, "192.168.1.99"))

    def test_una_conexion_sin_ip_no_asienta_nada(self):
        pc1 = pcs_repo.crear_estacion("PC1")
        pcs_repo.registrar_conexion(pc1)
        self.assertEqual(_ips(pc1), (None, None))

    def test_borrar_la_ip_asentada_deja_que_se_asiente_la_nueva(self):
        pc1 = pcs_repo.crear_estacion("PC1")
        pcs_repo.registrar_conexion(pc1, IP_PC1)

        pcs_repo.borrar_ip_asentada(pc1)
        self.assertEqual(_ips(pc1), (None, IP_PC1))
        self.assertIsNone(_reconocida("OTRO NOMBRE", IP_PC1))

        pcs_repo.registrar_conexion(pc1, "192.168.1.20")
        self.assertEqual(_ips(pc1), ("192.168.1.20", "192.168.1.20"))

    def test_la_migracion_se_puede_correr_dos_veces(self):
        database.inicializar_base_de_datos()
        conexion = database.get_connection()
        try:
            database._migrar_columna_ip_asentada_estaciones(conexion)
            columnas = [fila[1] for fila in conexion.execute("PRAGMA table_info(estaciones)")]
        finally:
            conexion.close()
        self.assertEqual(columnas.count("ip_asentada"), 1)


class TestReconocerLaPc(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        pcs_repo.registrar_conexion(self.pc1, IP_PC1)
        pcs_repo.registrar_conexion(self.pc2, IP_PC2)

    def test_el_nombre_va_antes_que_la_ip(self):
        # Llega desde la IP asentada de PC1, pero diciendo que es PC2: es PC2.
        self.assertEqual(_reconocida("PC2", IP_PC1), "PC2")

    def test_un_nombre_desconocido_se_reconoce_por_la_ip_asentada(self):
        self.assertEqual(_reconocida("PC 1 mal tipeado", IP_PC1), "PC1")

    def test_renombrar_la_estacion_no_deja_a_la_pc_sin_conexion(self):
        # El caso real: se renombra acá y el Cliente PC sigue mandando el nombre viejo.
        pcs_repo.renombrar_estacion(self.pc1, "PC01")
        self.assertEqual(_reconocida("PC1", IP_PC1), "PC01")

    def test_sin_ip_o_con_una_ip_desconocida_no_se_reconoce(self):
        self.assertIsNone(_reconocida("PC9", None))
        self.assertIsNone(_reconocida("PC9", "192.168.1.50"))

    def test_una_ip_asentada_en_dos_estaciones_no_reconoce_a_ninguna(self):
        pc3 = pcs_repo.crear_estacion("PC3")
        pcs_repo.registrar_conexion(pc3, IP_PC1)

        self.assertEqual(pcs_repo.ips_asentadas_repetidas(), {IP_PC1})
        self.assertIsNone(_reconocida("PC9", IP_PC1))
        # Por nombre siguen andando las dos.
        self.assertEqual(_reconocida("PC1", IP_PC1), "PC1")
        self.assertEqual(_reconocida("PC3", IP_PC1), "PC3")

    def test_una_estacion_desactivada_no_cuenta(self):
        pcs_repo.desactivar_estacion(self.pc1)
        self.assertIsNone(_reconocida("PC9", IP_PC1))

        # Tampoco cuenta como repetida: la IP es de la única activa que la tiene.
        pc3 = pcs_repo.crear_estacion("PC3")
        pcs_repo.registrar_conexion(pc3, IP_PC1)
        self.assertEqual(pcs_repo.ips_asentadas_repetidas(), set())
        self.assertEqual(_reconocida("PC9", IP_PC1), "PC3")


class TestServidorRedIpAsentada(test_control_pcs._ConServidorRed):
    """El pedido de prueba llega desde 127.0.0.1: esa es la IP que se asienta."""

    def test_el_primer_get_estado_asienta_la_ip_del_pedido(self):
        pc1 = pcs_repo.crear_estacion("PC 1")
        status, _ = self._get("/estado?estacion=PC+1")

        self.assertEqual(status, 200)
        self.assertEqual(_ips(pc1), ("127.0.0.1", "127.0.0.1"))

    def test_get_estado_con_otro_nombre_reconoce_a_la_pc_por_su_ip(self):
        pc1 = pcs_repo.crear_estacion("PC 1")
        self._get("/estado?estacion=PC+1")
        pcs_repo.renombrar_estacion(pc1, "PC 01")

        status, datos = self._get("/estado?estacion=PC+1")

        self.assertEqual(status, 200)
        self.assertTrue(datos["existe"])

    def test_los_post_usan_la_misma_regla(self):
        pcs_repo.crear_estacion("PC 1")
        self._get("/estado?estacion=PC+1")

        # Con un nombre que no existe ya no da "Estación desconocida": encontró
        # la PC por su IP y contesta lo que corresponde a ella.
        self.assertEqual(
            self._post("/logout", {"estacion": "PC VIEJA"}),
            (400, {"ok": False, "error": "No hay ninguna sesión activa en esta estación."}),
        )

    def test_sin_ip_asentada_un_nombre_desconocido_sigue_bloqueado(self):
        pcs_repo.crear_estacion("PC 1")  # todavía no se conectó nunca

        status, datos = self._get("/estado?estacion=PC+VIEJA")

        self.assertEqual(status, 200)
        self.assertFalse(datos["existe"])
        self.assertTrue(datos["bloqueada"])


class TestPantallaGestionEstaciones(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")
        pcs_repo.crear_estacion("PC3")  # todavía no se conectó
        pcs_repo.registrar_conexion(self.pc1, IP_PC1)
        pcs_repo.registrar_conexion(self.pc2, IP_PC2)

    def _dialogo(self):
        dialogo = pcs_gestion_dialogos.DialogoGestionEstaciones()
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def _fila(self, dialogo, nombre):
        for fila in range(dialogo.lista.rowCount()):
            if dialogo.lista.item(fila, 0).text() == nombre:
                return fila
        raise AssertionError(nombre)

    def test_la_lista_muestra_la_ip_asentada_de_cada_estacion(self):
        dialogo = self._dialogo()
        self.assertEqual(
            [(dialogo.lista.item(f, 0).text(), dialogo.lista.item(f, 1).text())
             for f in range(dialogo.lista.rowCount())],
            [("PC1", IP_PC1), ("PC2", IP_PC2), ("PC3", "")],
        )

        dialogo.lista.setCurrentCell(self._fila(dialogo, "PC1"), 0)
        self.assertEqual(dialogo.campo_ip.text(), IP_PC1)
        self.assertTrue(dialogo.aviso_ip.isHidden())

    def test_una_ip_repetida_sale_en_rojo_y_con_aviso(self):
        pc3 = pcs_repo.estado_de_estacion("PC3")["estacion"]["id"]
        pcs_repo.registrar_conexion(pc3, IP_PC1)
        dialogo = self._dialogo()

        self.assertEqual(dialogo.lista.item(self._fila(dialogo, "PC1"), 1).foreground().color(), Qt.red)
        dialogo.lista.setCurrentCell(self._fila(dialogo, "PC3"), 0)
        self.assertFalse(dialogo.aviso_ip.isHidden())
        self.assertIn("también está asentada en PC1", dialogo.aviso_ip.text())

    def test_avisa_si_la_pc_se_conecta_desde_otra_ip(self):
        pcs_repo.registrar_conexion(self.pc1, "192.168.1.99")
        dialogo = self._dialogo()

        dialogo.lista.setCurrentCell(self._fila(dialogo, "PC1"), 0)
        self.assertIn("192.168.1.99", dialogo.aviso_ip.text())

    def test_borrar_ip_la_olvida_y_actualiza_la_lista(self):
        dialogo = self._dialogo()
        dialogo.lista.setCurrentCell(self._fila(dialogo, "PC1"), 0)

        with mock.patch.object(pcs_gestion_dialogos, "confirmar", return_value=True):
            dialogo._borrar_ip()

        self.assertEqual(_ips(self.pc1), (None, IP_PC1))
        self.assertEqual(dialogo.lista.item(self._fila(dialogo, "PC1"), 1).text(), "")
        self.assertEqual(dialogo.campo_ip.text(), "")
