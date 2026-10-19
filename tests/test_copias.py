"""
tests/test_copias.py
======================
Las copias de seguridad automáticas (repositories/copias_repo.py y
ui/copias_dialogo.py, pedido del dueño 2026-10-19): una después de cada Cierre
de Turno y cada 8 horas con el programa abierto, en data/backups y en las otras
carpetas (otro disco, otra PC de la red con usuario y clave); cuántas quedan; que
una copia a medias nunca parezca buena; que con una carpeta que no está la copia
llegue sola cuando vuelve; que la clave de una carpeta de red no se guarde; y que
solo se borren las copias automáticas.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import shutil
import socket
import sqlite3
import subprocess
import tempfile
import unittest
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
from repositories import copias_repo, turnos_repo, usuarios_repo  # noqa: E402
from ui.copias_dialogo import DialogoAgregarCarpeta, DialogoCopiasDeSeguridad  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

_CARPETA_DE_RED = "\\\\192.168.1.111\\backups"
_CLAVE_DE_PRUEBA = "clave-de-prueba-que-no-se-guarda"


def _copias(carpeta):
    return sorted(n for n in os.listdir(carpeta) if copias_repo.momento_de_la_copia(n))


def _windows_acepta(*_args, **_kwargs):
    return subprocess.CompletedProcess(args=[], returncode=0)


class TestReglas(unittest.TestCase):
    def test_el_nombre_dice_cuando_se_hizo(self):
        self.assertEqual(
            copias_repo.momento_de_la_copia("kiosko_2026-10-19_140530.db"), datetime(2026, 10, 19, 14, 5, 30)
        )
        # las de antes de este cambio, una por día
        self.assertEqual(copias_repo.momento_de_la_copia("kiosko_2026-10-08.db"), datetime(2026, 10, 8))
        self.assertEqual(
            copias_repo.nombre_de_copia(datetime(2026, 10, 19, 14, 5, 30)), "kiosko_2026-10-19_140530.db"
        )

    def test_lo_que_no_es_una_copia_automatica_no_se_toca(self):
        for nombre in ("kiosko_backup_20261019_140530.db", "antes_de_limpiar_base_20261019_140530.db",
                       "kiosko.db", "kiosko_2026-10-19_140530.db.parcial", "notas.txt", "kiosko_2026-13-45.db"):
            self.assertIsNone(copias_repo.momento_de_la_copia(nombre), nombre)

    def test_cuando_toca_una_copia(self):
        copia = datetime(2026, 10, 19, 6, 1)
        self.assertTrue(copias_repo.toca_copia(None, None, copia))
        self.assertFalse(copias_repo.toca_copia(copia, None, copia + timedelta(hours=7, minutes=59)))
        self.assertTrue(copias_repo.toca_copia(copia, None, copia + timedelta(hours=8)))
        # un Cierre de Turno después de la última copia: enseguida
        self.assertTrue(copias_repo.toca_copia(copia, copia + timedelta(minutes=5), copia + timedelta(minutes=6)))
        # el cierre que ya quedó en la copia no vuelve a disparar
        self.assertFalse(copias_repo.toca_copia(copia, copia - timedelta(minutes=1), copia + timedelta(hours=1)))

    def test_quedan_todas_las_de_3_dias_y_una_por_dia_hasta_30(self):
        inicio = datetime(2026, 1, 1)
        nombres = [
            copias_repo.nombre_de_copia(inicio + timedelta(days=dia, hours=hora))
            for dia in range(40) for hora in (6, 14, 22)
        ] + ["antes_de_migrar_20260101_000000.db", "kiosko_backup_20260101_000000.db"]
        a_borrar = set(copias_repo.nombres_a_borrar(nombres))
        quedan = [n for n in nombres if n not in a_borrar and copias_repo.momento_de_la_copia(n)]

        self.assertEqual(len(quedan), 3 * 3 + 27)
        ultimos_3 = {(inicio + timedelta(days=d)).date() for d in (37, 38, 39)}
        for nombre in quedan:
            momento = copias_repo.momento_de_la_copia(nombre)
            if momento.date() not in ultimos_3:
                self.assertEqual(momento.hour, 22, nombre)  # la última de ese día
        self.assertNotIn("antes_de_migrar_20260101_000000.db", a_borrar)
        self.assertNotIn("kiosko_backup_20260101_000000.db", a_borrar)

    def test_se_cuentan_dias_con_copias_y_no_dias_del_calendario(self):
        # Un mes con el programa cerrado no borra las copias de antes: siguen
        # siendo de los últimos días CON copias.
        viejas = [copias_repo.nombre_de_copia(datetime(2026, 1, d, 22)) for d in range(1, 6)]
        nueva = copias_repo.nombre_de_copia(datetime(2026, 6, 1, 6))
        self.assertEqual(copias_repo.nombres_a_borrar(viejas + [nueva]), [])

    def test_carpetas_de_red(self):
        self.assertTrue(copias_repo.es_carpeta_de_red(_CARPETA_DE_RED))
        self.assertFalse(copias_repo.es_carpeta_de_red("D:\\BACKUPS"))
        self.assertEqual(copias_repo.servidor_de(_CARPETA_DE_RED), "192.168.1.111")

    @unittest.skipUnless(os.name == "nt", "los códigos de error son los de Windows")
    def test_los_errores_de_windows_en_palabras(self):
        def error(codigo):
            return copias_repo.explicar_error(OSError(None, "x", None, codigo), _CARPETA_DE_RED)
        self.assertIn("¿está prendida esa PC", error(53))
        self.assertIn("El usuario o la clave", error(1326))
        self.assertIn("ya está conectada a 192.168.1.111 con otro usuario", error(1219))
        self.assertIn("No hay más lugar", error(112))
        self.assertIn("No se encuentra la carpeta", copias_repo.explicar_error(FileNotFoundError(2, "x"), "D:\\X"))


class _ConCopias(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        copias_repo._estado.update(error_local=None, reintentar_desde=None, extra={})
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.empleada_id = usuarios_repo.crear_usuario("Empleada", "1234", dominio.ROL_EMPLEADA)
        self._otras = tempfile.TemporaryDirectory()
        # como D:\BACKUPS y la carpeta compartida de otra PC
        self.disco = os.path.join(self._otras.name, "D", "BACKUPS")
        self.otra_pc = os.path.join(self._otras.name, "otra_pc", "backups")
        os.makedirs(self.disco)
        os.makedirs(self.otra_pc)

    def tearDown(self):
        copias_repo._estado.update(error_local=None, reintentar_desde=None, extra={})
        self._otras.cleanup()
        super().tearDown()

    def _agregar_las_dos(self):
        copias_repo.agregar_carpeta_extra(self.admin_id, self.otra_pc)
        copias_repo.agregar_carpeta_extra(self.admin_id, self.disco)


class TestCopiasAutomaticas(_ConCopias):
    def test_la_primera_revision_hace_una_copia_que_se_abre_bien(self):
        ruta = copias_repo.copia_automatica_si_corresponde()
        self.assertTrue(os.path.exists(ruta))
        self.assertEqual(os.path.dirname(ruta), os.path.join(database.DATA_DIR, "backups"))
        conexion = sqlite3.connect(ruta)
        try:
            self.assertGreaterEqual(conexion.execute("SELECT COUNT(*) FROM usuarios").fetchone()[0], 2)
        finally:
            conexion.close()
        self.assertEqual([n for n in os.listdir(os.path.dirname(ruta)) if n.endswith(".parcial")], [])

    def test_sin_cierre_espera_8_horas(self):
        antes = datetime.now() - timedelta(hours=20)
        self.assertIsNotNone(copias_repo.copia_automatica_si_corresponde(antes))
        self.assertIsNone(copias_repo.copia_automatica_si_corresponde(antes + timedelta(hours=7)))
        self.assertIsNotNone(copias_repo.copia_automatica_si_corresponde(antes + timedelta(hours=8)))
        self.assertEqual(len(_copias(copias_repo.carpeta_local())), 2)

    def test_un_cierre_de_turno_dispara_una_copia(self):
        antes = datetime.now() - timedelta(hours=1)
        copias_repo.copia_automatica_si_corresponde(antes)
        self.assertIsNone(copias_repo.copia_automatica_si_corresponde(antes + timedelta(minutes=30)))

        turnos_repo.cerrar_turno(self.empleada_id)
        ruta = copias_repo.copia_automatica_si_corresponde(datetime.now() + timedelta(seconds=1))
        self.assertIsNotNone(ruta)
        conexion = sqlite3.connect(ruta)
        try:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM cierres_turno").fetchone()[0], 1)
        finally:
            conexion.close()
        # y el mismo cierre no dispara otra
        self.assertIsNone(copias_repo.copia_automatica_si_corresponde(datetime.now() + timedelta(minutes=2)))

    def test_cada_copia_va_tambien_a_las_otras_carpetas(self):
        self._agregar_las_dos()
        ruta = copias_repo.copia_automatica_si_corresponde()
        for carpeta in (self.otra_pc, self.disco):
            self.assertEqual(_copias(carpeta), [os.path.basename(ruta)])
            self.assertEqual(os.path.getsize(os.path.join(carpeta, os.path.basename(ruta))), os.path.getsize(ruta))
        estado = copias_repo.estado()
        self.assertEqual([c["carpeta"] for c in estado["extra"]], [self.otra_pc, self.disco])
        for carpeta in estado["extra"]:
            self.assertEqual(carpeta["ultima"], estado["ultima_local"])
            self.assertIsNone(carpeta["error"])

    def test_con_la_otra_pc_apagada_la_copia_llega_cuando_vuelve(self):
        self._agregar_las_dos()
        shutil.rmtree(os.path.dirname(self.otra_pc))  # la otra PC apagada: no está la carpeta
        ruta = copias_repo.copia_automatica_si_corresponde()
        self.assertTrue(os.path.exists(ruta))  # en esta PC sí
        self.assertEqual(_copias(self.disco), [os.path.basename(ruta)])  # y en el disco también
        otra_pc, disco = copias_repo.estado()["extra"]
        self.assertIn("No se encuentra la carpeta", otra_pc["error"])
        self.assertIsNone(disco["error"])
        self.assertFalse(os.path.exists(self.otra_pc))  # no la inventa

        os.makedirs(self.otra_pc)  # volvió la otra PC
        self.assertIsNone(copias_repo.copia_automatica_si_corresponde(datetime.now() + timedelta(minutes=1)))
        self.assertEqual(_copias(self.otra_pc), [os.path.basename(ruta)])
        self.assertIsNone(copias_repo.estado()["extra"][0]["error"])

    def test_el_mismo_error_va_una_sola_vez_al_log(self):
        copias_repo.agregar_carpeta_extra(self.admin_id, self.otra_pc)
        shutil.rmtree(self.otra_pc)
        ahora = datetime.now()
        for minuto in range(4):
            copias_repo.copia_automatica_si_corresponde(ahora + timedelta(minutes=minuto))
        with open(os.path.join(database.DATA_DIR, "errores.log"), encoding="utf-8") as log:
            self.assertEqual(log.read().count("Copia de seguridad en otra carpeta"), 1)

    def test_una_copia_que_falla_no_deja_un_archivo_a_medias(self):
        copias_repo.agregar_carpeta_extra(self.admin_id, self.disco)

        def falla_a_mitad(destino):
            with open(destino, "wb") as archivo:
                archivo.write(b"SQLite format 3\x00 a medias")
            raise OSError("disco lleno")

        ahora = datetime.now()
        with mock.patch("database._backup_consistente", side_effect=falla_a_mitad) as copia:
            self.assertIsNone(copias_repo.copia_automatica_si_corresponde(ahora))
            self.assertEqual(os.listdir(copias_repo.carpeta_local()), [])
            self.assertEqual(os.listdir(self.disco), [])  # nada a medias se lleva a otra carpeta
            self.assertIn("disco lleno", copias_repo.estado()["error_local"])
            # no reintenta cada minuto
            copias_repo.copia_automatica_si_corresponde(ahora + timedelta(minutes=1))
            self.assertEqual(copia.call_count, 1)
            copias_repo.copia_automatica_si_corresponde(ahora + timedelta(minutes=11))
            self.assertEqual(copia.call_count, 2)
        self.assertIsNotNone(copias_repo.copia_automatica_si_corresponde(ahora + timedelta(minutes=22)))
        self.assertIsNone(copias_repo.estado()["error_local"])

    def test_solo_se_borran_copias_automaticas(self):
        copias_repo.agregar_carpeta_extra(self.admin_id, self.disco)
        inicio = datetime(2026, 1, 1, 22)
        viejas = [copias_repo.nombre_de_copia(inicio + timedelta(days=d)) for d in range(40)]
        otras = ["antes_de_limpiar_base_20260101_000000.db", "kiosko_backup_20260101_000000.db", "notas.txt"]
        os.makedirs(copias_repo.carpeta_local())
        for carpeta in (copias_repo.carpeta_local(), self.disco):
            for nombre in viejas + otras:
                open(os.path.join(carpeta, nombre), "wb").close()

        copias_repo.hacer_copia_ahora()
        for carpeta in (copias_repo.carpeta_local(), self.disco):
            quedan = os.listdir(carpeta)
            for nombre in otras:
                self.assertIn(nombre, quedan)
            self.assertEqual(len(_copias(carpeta)), copias_repo.DIAS_CON_UNA_COPIA)

    def test_hacer_una_copia_ahora(self):
        resultado = copias_repo.hacer_copia_ahora()
        self.assertTrue(os.path.exists(resultado["local"]))
        self.assertEqual(resultado["extra"], [])
        self._agregar_las_dos()
        resultado = copias_repo.hacer_copia_ahora()
        self.assertEqual([r["error"] for r in resultado["extra"]], [None, None])
        for r in resultado["extra"]:
            self.assertTrue(os.path.exists(r["destino"]))

    def test_sin_base_no_hay_nada_que_copiar(self):
        os.remove(database.DB_PATH)
        self.assertIsNone(copias_repo.copia_automatica_si_corresponde())
        self.assertFalse(os.path.exists(database.DB_PATH))  # no la crea vacía


class TestOtrasCarpetas(_ConCopias):
    def test_solo_el_admin_las_agrega_o_las_quita(self):
        with self.assertRaises(PermissionError):
            copias_repo.agregar_carpeta_extra(self.empleada_id, self.disco)
        copias_repo.agregar_carpeta_extra(self.admin_id, self.disco)
        with self.assertRaises(PermissionError):
            copias_repo.quitar_carpeta_extra(self.empleada_id, self.disco)
        self.assertEqual(copias_repo.carpetas_extra(), [os.path.normpath(self.disco)])
        copias_repo.quitar_carpeta_extra(self.admin_id, os.path.normpath(self.disco))
        self.assertEqual(copias_repo.carpetas_extra(), [])

    def test_en_un_disco_de_esta_pc_la_crea_si_falta(self):
        nueva = os.path.join(self._otras.name, "E", "BACKUPS")
        copias_repo.agregar_carpeta_extra(self.admin_id, nueva)
        self.assertTrue(os.path.isdir(nueva))
        self.assertEqual(copias_repo.carpetas_extra(), [os.path.normpath(nueva)])

    @unittest.skipUnless(os.name == "nt", "letras de disco de Windows")
    def test_un_disco_que_no_esta_no_se_inventa(self):
        sin_disco = next(f"{letra}:\\" for letra in "ZYXWVUTSRQPONMLKJIHG" if not os.path.exists(f"{letra}:\\"))
        with self.assertRaises(ValueError) as error:
            copias_repo.agregar_carpeta_extra(self.admin_id, sin_disco + "BACKUPS")
        self.assertIn("No se encuentra el disco", str(error.exception))
        self.assertEqual(copias_repo.carpetas_extra(), [])

    def test_tiene_que_ser_completa_no_repetirse_y_no_ser_la_del_programa(self):
        for mal in ("BACKUPS", "", "   "):
            with self.assertRaises(ValueError):
                copias_repo.agregar_carpeta_extra(self.admin_id, mal)
        os.makedirs(copias_repo.carpeta_local())
        with self.assertRaises(ValueError):
            copias_repo.agregar_carpeta_extra(self.admin_id, copias_repo.carpeta_local())
        copias_repo.agregar_carpeta_extra(self.admin_id, self.disco + "\\")
        with self.assertRaises(ValueError):
            copias_repo.agregar_carpeta_extra(self.admin_id, self.disco.upper())
        self.assertEqual(copias_repo.carpetas_extra(), [os.path.normpath(self.disco)])
        self.assertEqual(os.listdir(self.disco), [])  # la prueba de escritura no deja nada

    def test_la_carpeta_de_red_le_da_el_usuario_y_la_clave_a_windows_y_no_los_guarda(self):
        with mock.patch("repositories.copias_repo.subprocess.run", side_effect=_windows_acepta) as cmdkey, \
                mock.patch("repositories.copias_repo._probar_que_se_puede_guardar"):
            copias_repo.agregar_carpeta_extra(self.admin_id, _CARPETA_DE_RED + "\\", "usuario_de_prueba", _CLAVE_DE_PRUEBA)
        argumentos = cmdkey.call_args[0][0]
        self.assertEqual(argumentos[:3], ["cmdkey", "/add:192.168.1.111", "/user:usuario_de_prueba"])
        self.assertEqual(argumentos[3], f"/pass:{_CLAVE_DE_PRUEBA}")
        self.assertEqual(copias_repo.carpetas_extra(), [_CARPETA_DE_RED])
        with database.conexion_db() as conexion:
            todo = " ".join(str(f["valor"]) for f in conexion.execute("SELECT valor FROM configuracion"))
        self.assertNotIn(_CLAVE_DE_PRUEBA, todo)

    def test_sin_usuario_no_toca_las_claves_de_windows(self):
        with mock.patch("repositories.copias_repo.subprocess.run", side_effect=_windows_acepta) as cmdkey, \
                mock.patch("repositories.copias_repo._probar_que_se_puede_guardar"):
            copias_repo.agregar_carpeta_extra(self.admin_id, _CARPETA_DE_RED)
        cmdkey.assert_not_called()

    def test_si_windows_no_acepta_la_clave_no_se_agrega(self):
        rechazo = subprocess.CompletedProcess(args=[], returncode=1)
        with mock.patch("repositories.copias_repo.subprocess.run", return_value=rechazo):
            with self.assertRaises(ValueError) as error:
                copias_repo.agregar_carpeta_extra(self.admin_id, _CARPETA_DE_RED, "usuario_de_prueba", _CLAVE_DE_PRUEBA)
        self.assertNotIn(_CLAVE_DE_PRUEBA, str(error.exception))
        self.assertEqual(copias_repo.carpetas_extra(), [])

    def test_si_la_otra_pc_no_contesta_no_espera_a_windows(self):
        with mock.patch("repositories.copias_repo._probar_que_se_puede_guardar"):
            copias_repo.agregar_carpeta_extra(self.admin_id, _CARPETA_DE_RED)
        with mock.patch("repositories.copias_repo.socket.create_connection", side_effect=TimeoutError("timed out")), \
                mock.patch("repositories.copias_repo.os.path.exists", wraps=os.path.exists) as existe:
            copias_repo.copia_automatica_si_corresponde()
        self.assertIn("No se llega a", copias_repo.estado()["extra"][0]["error"])
        # ni se asomó a la carpeta: con la PC apagada eso tarda ~50 s
        self.assertFalse(any(_CARPETA_DE_RED in str(llamada) for llamada in existe.call_args_list))

    def test_preguntar_si_la_otra_pc_contesta(self):
        servidor = socket.create_server(("127.0.0.1", 0))
        puerto = servidor.getsockname()[1]
        try:
            with mock.patch.object(copias_repo, "PUERTO_CARPETAS_COMPARTIDAS", puerto):
                copias_repo._que_conteste("\\\\127.0.0.1\\backups")  # contesta: no pasa nada
        finally:
            servidor.close()
        with mock.patch.object(copias_repo, "PUERTO_CARPETAS_COMPARTIDAS", puerto):
            with self.assertRaises(copias_repo.NoContesta):
                copias_repo._que_conteste("\\\\127.0.0.1\\backups")
        copias_repo._que_conteste(self.disco)  # una carpeta de esta PC no se pregunta

    def test_a_la_carpeta_de_red_le_falta_la_carpeta_compartida(self):
        with self.assertRaises(ValueError):
            copias_repo.agregar_carpeta_extra(self.admin_id, "\\\\192.168.1.111")


class TestPantallaDeCopias(_ConCopias):
    def _dialogo(self):
        return DialogoCopiasDeSeguridad(usuarios_repo.obtener_usuario(self.admin_id))

    def test_sin_copias_ni_carpetas(self):
        dialogo = self._dialogo()
        self.assertIn("todavía ninguna", dialogo.etiqueta_local.text())
        self.assertEqual(dialogo.tabla.rowCount(), 0)
        self.assertFalse(dialogo.boton_quitar.isEnabled())

    def test_agregar_una_carpeta_hace_una_copia_enseguida(self):
        dialogo = self._dialogo()
        agregar = DialogoAgregarCarpeta(usuarios_repo.obtener_usuario(self.admin_id), dialogo)
        agregar.campo_carpeta.setText(self.disco)
        agregar._guardar()
        self.assertEqual(agregar.result(), DialogoAgregarCarpeta.Accepted)
        with mock.patch("ui.copias_dialogo.DialogoAgregarCarpeta.exec", return_value=True), \
                mock.patch("ui.copias_dialogo.mostrar_info") as aviso:
            dialogo._agregar_carpeta()
        self.assertIn("en esta PC y en las 1 carpeta(s)", aviso.call_args[0][2])
        self.assertEqual(len(_copias(self.disco)), 1)
        self.assertEqual(dialogo.tabla.item(0, 0).text(), os.path.normpath(self.disco))
        self.assertEqual(dialogo.tabla.item(0, 2).text(), "Bien")
        self.assertIn("1 copia(s)", dialogo.etiqueta_local.text())
        self.assertTrue(dialogo.boton_quitar.isEnabled())

    def test_una_carpeta_que_no_esta_se_ve_en_rojo_y_avisa(self):
        self._agregar_las_dos()
        shutil.rmtree(self.otra_pc)
        dialogo = self._dialogo()
        with mock.patch("ui.copias_dialogo.mostrar_error") as aviso:
            dialogo._copiar_ahora()
        self.assertIn("no en todas las carpetas", aviso.call_args[0][1])
        self.assertIn("y en 1 carpeta(s) más", aviso.call_args[0][2])
        self.assertEqual(dialogo.tabla.item(0, 2).text(), "No anda (ver abajo)")
        self.assertIn("No se encuentra la carpeta", dialogo.errores_extra.text())  # el porqué, entero
        self.assertFalse(dialogo.errores_extra.isHidden())
        self.assertEqual(dialogo.tabla.item(1, 2).text(), "Bien")

    def test_quitar_sin_elegir_una_carpeta_avisa(self):
        self._agregar_las_dos()
        dialogo = self._dialogo()
        with mock.patch("ui.copias_dialogo.mostrar_error") as aviso, \
                mock.patch("ui.copias_dialogo.confirmar") as pregunta:
            dialogo._quitar_carpeta()
        self.assertIn("Elegí primero una carpeta", aviso.call_args[0][2])
        pregunta.assert_not_called()
        self.assertEqual(len(copias_repo.carpetas_extra()), 2)

    def test_quitar_una_carpeta(self):
        self._agregar_las_dos()
        dialogo = self._dialogo()
        dialogo.tabla.selectRow(1)
        with mock.patch("ui.copias_dialogo.confirmar", return_value=True):
            dialogo._quitar_carpeta()
        self.assertEqual(copias_repo.carpetas_extra(), [os.path.normpath(self.otra_pc)])
        self.assertEqual(dialogo.tabla.rowCount(), 1)


if __name__ == "__main__":
    unittest.main()
