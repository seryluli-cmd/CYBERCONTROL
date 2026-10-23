"""
tests/test_programas_pc.py
===========================
"Programas y estado" y el mantenimiento a distancia del clic derecho de una PC (pedido del dueño,
2026-10-22). Del lado de la PC es CLIENTE PC/programas_pc.py (Cliente PC V1.6).

- `programas_pc_repo` y `mantenimiento_pc_repo`, y los comandos nuevos en la cola.
- `servidor_red.py`: los minutos de mantenimiento en GET /estado y el JSON largo de INFO_PC.
- La ventana y el clic derecho (Qt "offscreen", sin abrir ventanas).

Se ejecutan con:

    python -m unittest discover tests
"""

import json
import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import QPoint  # noqa: E402
from PySide6.QtWidgets import QApplication, QMenu  # noqa: E402

import dominio  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from test_congelado import envejecer, ocupar  # noqa: E402
from control_pcs.repositories import (  # noqa: E402
    actividad_repo, comandos_pc_repo, mantenimiento_pc_repo, pcs_repo, programas_pc_repo,
)
from control_pcs.ui import pcs_programas_dialogo, pcs_window  # noqa: E402
from control_pcs.ui.pcs_actividad import _texto_evento  # noqa: E402
from control_pcs.ui.pcs_programas_dialogo import DialogoMantenimiento, DialogoProgramas  # noqa: E402

_app = QApplication.instance() or QApplication([])

GB = 1024 ** 3

INFO = {
    "estado": {
        "discos": [{"unidad": "C:", "libre": 38 * GB, "total": 465 * GB},
                   {"unidad": "D:", "libre": 120 * GB, "total": 931 * GB}],
        "memoria": {"usada": int(9.1 * GB), "total": 16 * GB},
        "cpu": 23, "prendida": 3 * 3600 + 12 * 60, "temp_cpu": 61, "temp_gpu": None, "version": "1.6",
    },
    "programas": [
        {"pid": 50, "exe": "steam.exe", "titulo": "Steam", "no_responde": False},
        {"pid": 40, "exe": "FortniteClient-Win64-Shipping.exe", "titulo": "Fortnite", "no_responde": True},
    ],
    "iconos": ["Discord", "Fortnite", "Steam"],
}


def poner_version(estacion_id, numero):
    with conexion_db() as conexion:
        conexion.execute("UPDATE estaciones SET numero_version_cliente = ? WHERE id = ?", (numero, estacion_id))


def enlazar(estacion_id, mant_min=None):
    """La PC preguntó hace un momento (y, si se da, está en mantenimiento)."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE estaciones SET ultima_conexion = ?, mant_min = ? WHERE id = ?",
                         (datetime.now().isoformat(timespec="seconds"), mant_min, estacion_id))


def contestar(comando_id, texto):
    """Lo que hace el servidor de red cuando la PC sube su respuesta."""
    comandos_pc_repo.marcar_entregado(comando_id)
    comandos_pc_repo.guardar_texto(comando_id, texto)


def comandos(estacion_id):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM comandos_pc WHERE estacion_id = ? ORDER BY id",
                                (estacion_id,)).fetchall()


class TestLaCola(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")

    def test_los_cuatro_comandos_nuevos_entran_en_la_base(self):
        for tipo in (dominio.COMANDO_INFO_PC, dominio.COMANDO_CERRAR_PROGRAMA, dominio.COMANDO_ABRIR_PROGRAMA,
                     dominio.COMANDO_MANTENIMIENTO):
            comandos_pc_repo.encolar_comando(self.pc, tipo, "x")
        self.assertEqual(len(comandos(self.pc)), 4)

    def test_vencen_como_reiniciar_para_no_llegarle_horas_despues_a_otro_cliente(self):
        cerrar = programas_pc_repo.cerrar_programa(self.pc, INFO["programas"][1])
        mantenimiento = mantenimiento_pc_repo.ordenar(self.pc, dominio.MANTENIMIENTO_INICIAR, None)
        for comando_id in (cerrar, mantenimiento):
            envejecer(comando_id, comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO + 1)

        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc))
        for comando_id in (cerrar, mantenimiento):
            self.assertEqual(comandos_pc_repo.obtener_comando(comando_id)["resultado"],
                             comandos_pc_repo.RESULTADO_REINICIO_VENCIDO)

    def test_la_respuesta_de_info_pc_se_guarda_entera_y_las_demas_cortas(self):
        info = programas_pc_repo.pedir_info(self.pc)
        abrir = programas_pc_repo.abrir_programa(self.pc, "Steam")
        largo = "x" * 30000

        contestar(info, largo)
        contestar(abrir, largo)

        self.assertEqual(len(comandos_pc_repo.obtener_comando(info)["resultado"]), 30000)
        self.assertEqual(len(comandos_pc_repo.obtener_comando(abrir)["resultado"]), comandos_pc_repo.TOPE_TEXTO)


class TestProgramasRepo(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")

    def test_solo_se_le_pide_a_un_cliente_pc_de_la_v16_en_adelante(self):
        for numero, falta in ((None, True), ("1", True), ("1.5", True), ("1.6", False), ("1.7", False),
                              ("2", False)):
            poner_version(self.pc, numero)
            self.assertEqual(programas_pc_repo.le_falta_la_version(pcs_repo.obtener_estacion(self.pc)), falta,
                             numero)

    def test_lee_lo_que_contesta_la_pc(self):
        self.assertEqual(programas_pc_repo.leer_info(json.dumps(INFO)), INFO)

    def test_lo_que_no_se_entiende_queda_afuera(self):
        raro = {"estado": {"discos": [{"unidad": "C:"}, "x"], "memoria": {"usada": "mucha"}, "cpu": 2.5,
                           "prendida": -3, "temp_cpu": True},
                "programas": [{"pid": "40"}, {"pid": 41}, 7], "iconos": ["Steam", 3, ""]}

        info = programas_pc_repo.leer_info(json.dumps(raro))

        self.assertEqual(info["estado"]["discos"], [])
        self.assertIsNone(info["estado"]["memoria"])
        self.assertEqual([info["estado"][c] for c in ("cpu", "prendida", "temp_cpu")], [None, None, None])
        self.assertEqual(info["programas"], [{"pid": 41, "exe": "", "titulo": "", "no_responde": False}])
        self.assertEqual(info["iconos"], ["Steam"])

    def test_un_error_de_la_pc_o_algo_que_no_es_json_levanta_el_motivo(self):
        with self.assertRaisesRegex(ValueError, "se rompió"):
            programas_pc_repo.leer_info("ERROR: se rompió")
        for texto in ("no es json", "[1, 2]", ""):
            with self.assertRaisesRegex(ValueError, "no se entiende"):
                programas_pc_repo.leer_info(texto)

    def test_cerrar_manda_el_pid_y_el_exe_y_abrir_el_nombre_del_icono(self):
        cerrar = programas_pc_repo.cerrar_programa(self.pc, INFO["programas"][1])
        abrir = programas_pc_repo.abrir_programa(self.pc, "Steam")

        fila_cerrar, fila_abrir = comandos_pc_repo.obtener_comando(cerrar), comandos_pc_repo.obtener_comando(abrir)
        self.assertEqual((fila_cerrar["tipo"], json.loads(fila_cerrar["payload"])),
                         (dominio.COMANDO_CERRAR_PROGRAMA, {"pid": 40, "exe": "FortniteClient-Win64-Shipping.exe"}))
        self.assertEqual((fila_abrir["tipo"], fila_abrir["payload"]), (dominio.COMANDO_ABRIR_PROGRAMA, "Steam"))

    def test_pedir_otra_vez_vacia_las_respuestas_viejas_de_esa_pc(self):
        # Así la base no crece cada vez que se abre la ventana.
        otra_pc = pcs_repo.crear_estacion("PC08")
        vieja, de_otra = programas_pc_repo.pedir_info(self.pc), programas_pc_repo.pedir_info(otra_pc)
        contestar(vieja, json.dumps(INFO))
        contestar(de_otra, json.dumps(INFO))
        cerrar = programas_pc_repo.cerrar_programa(self.pc, INFO["programas"][0])
        contestar(cerrar, "OK: Se cerró Steam.")

        nueva = programas_pc_repo.pedir_info(self.pc)

        self.assertIsNone(comandos_pc_repo.obtener_comando(vieja)["resultado"])
        self.assertIsNotNone(comandos_pc_repo.obtener_comando(de_otra)["resultado"])
        self.assertEqual(comandos_pc_repo.obtener_comando(cerrar)["resultado"], "OK: Se cerró Steam.")
        self.assertEqual(comandos_pc_repo.obtener_comando(nueva)["estado"], dominio.ESTADO_COMANDO_PENDIENTE)

    def test_leer_respuesta(self):
        self.assertEqual(programas_pc_repo.leer_respuesta("OK: Se cerró Steam."), (True, "Se cerró Steam."))
        self.assertEqual(programas_pc_repo.leer_respuesta("ERROR: Acceso denegado"), (False, "Acceso denegado"))
        self.assertFalse(programas_pc_repo.leer_respuesta("cualquier cosa")[0])


class TestMantenimientoRepo(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")
        self.operador = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA))

    def test_lee_los_minutos_que_manda_la_pc(self):
        self.assertEqual(mantenimiento_pc_repo.leer_minutos({"mant": "12"}), 12)
        for parametros in ({}, {"mant": ""}, {"mant": "0"}, {"mant": "-3"}, {"mant": "abc"}, {"mant": "500"}):
            self.assertIsNone(mantenimiento_pc_repo.leer_minutos(parametros), parametros)

    def test_guarda_solo_si_cambio_y_vale_solo_con_la_pc_enlazada(self):
        self.assertTrue(mantenimiento_pc_repo.registrar(self.pc, 12))
        self.assertFalse(mantenimiento_pc_repo.registrar(self.pc, 12))
        estacion = pcs_repo.obtener_estacion(self.pc)
        self.assertEqual(mantenimiento_pc_repo.minutos_vigentes(estacion, True), 12)
        self.assertIsNone(mantenimiento_pc_repo.minutos_vigentes(estacion, False))
        self.assertTrue(mantenimiento_pc_repo.registrar(self.pc, None))
        self.assertIsNone(mantenimiento_pc_repo.minutos_vigentes(pcs_repo.obtener_estacion(self.pc), True))

    def test_ordenar_manda_el_comando_y_anota_quien(self):
        comando_id = mantenimiento_pc_repo.ordenar(self.pc, dominio.MANTENIMIENTO_INICIAR, self.operador)

        fila = comandos_pc_repo.obtener_comando(comando_id)
        self.assertEqual((fila["tipo"], fila["payload"]), (dominio.COMANDO_MANTENIMIENTO, "INICIAR"))
        with self.assertRaises(ValueError):
            mantenimiento_pc_repo.ordenar(self.pc, "OTRA", self.operador)

    def test_actividad_reciente_lo_muestra_con_el_operador_solo_si_la_pc_lo_hizo(self):
        empezar = mantenimiento_pc_repo.ordenar(self.pc, dominio.MANTENIMIENTO_INICIAR, self.operador)
        rechazado = mantenimiento_pc_repo.ordenar(self.pc, dominio.MANTENIMIENTO_INICIAR, self.operador)
        terminar = mantenimiento_pc_repo.ordenar(self.pc, dominio.MANTENIMIENTO_TERMINAR, self.operador)
        mantenimiento_pc_repo.ordenar(self.pc, dominio.MANTENIMIENTO_TERMINAR, self.operador)   # sin respuesta
        contestar(empezar, "OK: La PC queda libre 15 minutos y después se bloquea sola.")
        contestar(rechazado, "ERROR: La PC tiene un cliente usándola.")
        contestar(terminar, "OK: Se terminó el mantenimiento: la PC quedó bloqueada.")

        eventos = [e for e in actividad_repo.actividad_reciente() if e["tipo"] == "MANTENIMIENTO_REMOTO"]

        self.assertEqual(sorted(e["orden"] for e in eventos), ["INICIAR", "TERMINAR"])
        textos = sorted(_texto_evento(e).split(" — ", 1)[1] for e in eventos)
        self.assertEqual(textos, [
            "PC07: TOBY la puso en mantenimiento desde el mostrador (15 min sin bloqueo, después se bloquea sola).",
            "PC07: TOBY terminó el mantenimiento desde el mostrador.",
        ])


class TestServidor(test_control_pcs._ConServidorRed):
    def test_guarda_los_minutos_de_mantenimiento_y_los_borra_cuando_deja_de_mandarlos(self):
        estacion = pcs_repo.crear_estacion("PC11X")

        status, datos = self._get("/estado?estacion=PC11X&mant=12")
        self.assertEqual((status, datos["bloqueada"]), (200, True))
        self.assertEqual(pcs_repo.obtener_estacion(estacion)["mant_min"], 12)

        self._get("/estado?estacion=PC11X")
        self.assertIsNone(pcs_repo.obtener_estacion(estacion)["mant_min"])

    def test_la_respuesta_larga_de_info_pc_llega_entera(self):
        estacion = pcs_repo.crear_estacion("PC11X")
        comando_id = programas_pc_repo.pedir_info(estacion)
        texto = json.dumps(dict(INFO, iconos=[f"Juego {n}" for n in range(150)]))

        status, _datos = self._post("/comando_resultado", {"comando_id": comando_id, "texto": texto})

        self.assertEqual(status, 200)
        self.assertEqual(programas_pc_repo.leer_info(comandos_pc_repo.obtener_comando(comando_id)["resultado"])
                         ["iconos"][-1], "Juego 149")


class TestVentana(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")
        poner_version(self.pc, "1.6")

    def ventana(self):
        dialogo = DialogoProgramas(pcs_repo.obtener_estacion(self.pc))
        self.addCleanup(dialogo.deleteLater)
        self.addCleanup(dialogo._timer.stop)
        return dialogo

    def ultimo(self):
        return comandos(self.pc)[-1]

    def test_al_abrir_le_pide_los_datos_a_la_pc_y_los_muestra_al_llegar(self):
        dialogo = self.ventana()
        pedido = self.ultimo()
        self.assertEqual(pedido["tipo"], dominio.COMANDO_INFO_PC)
        self.assertEqual(dialogo.etiqueta_estado.text(), "Pidiendo los datos a la PC...")
        self.assertFalse(dialogo.boton_cerrar_programa.isEnabled())

        contestar(pedido["id"], json.dumps(INFO))
        dialogo._cada_segundo()

        self.assertEqual(dialogo.recuadro_disco.etiqueta_valor.text(), "38 GB libres")
        self.assertEqual(dialogo.recuadro_disco.etiqueta_detalle.text(), "de 465 GB · D: 120 GB libres")
        self.assertEqual(dialogo.recuadro_memoria.etiqueta_valor.text(), "9,1 GB en uso")
        self.assertEqual(dialogo.recuadro_procesador.etiqueta_valor.text(), "23 %")
        self.assertEqual(dialogo.recuadro_procesador.etiqueta_detalle.text(), "61 °C")
        self.assertEqual(dialogo.recuadro_prendida.etiqueta_valor.text(), "3h 12m")
        self.assertEqual(dialogo.recuadro_prendida.etiqueta_detalle.text(), "Cliente PC V1.6")
        # El que no responde, primero y en rojo.
        tabla = dialogo.tabla_programas
        self.assertEqual([tabla.item(f, 0).text() for f in range(tabla.rowCount())], ["Fortnite", "Steam"])
        self.assertEqual([tabla.item(f, 1).text() for f in range(tabla.rowCount())], ["⚠️ NO RESPONDE", "Funciona"])
        self.assertEqual(tabla.item(0, 1).foreground().color().name().upper(), pcs_programas_dialogo.COLOR_ALERTA)
        self.assertEqual([dialogo.tabla_iconos.item(f, 0).text() for f in range(3)], ["Discord", "Fortnite", "Steam"])
        self.assertTrue(dialogo.boton_cerrar_programa.isEnabled())
        self.assertTrue(dialogo.etiqueta_estado.text().startswith("Datos de hace "))

    def mostrar_info(self, dialogo):
        contestar(self.ultimo()["id"], json.dumps(INFO))
        dialogo._cada_segundo()

    def test_cerrar_el_elegido_pregunta_lo_manda_y_vuelve_a_pedir_la_lista(self):
        dialogo = self.ventana()
        self.mostrar_info(dialogo)
        dialogo.tabla_programas.selectRow(0)

        with mock.patch.object(pcs_programas_dialogo, "confirmar", return_value=True) as pregunta:
            dialogo._cerrar_elegido()

        self.assertIn("«Fortnite»", pregunta.call_args.args[2])
        cerrar = self.ultimo()
        self.assertEqual((cerrar["tipo"], json.loads(cerrar["payload"])["pid"]), (dominio.COMANDO_CERRAR_PROGRAMA, 40))
        self.assertEqual(dialogo.etiqueta_estado.text(), "Cerrando «Fortnite»...")

        contestar(cerrar["id"], "OK: Se cerró Fortnite.")
        dialogo._cada_segundo()

        self.assertEqual(self.ultimo()["tipo"], dominio.COMANDO_INFO_PC)
        self.assertEqual(dialogo.etiqueta_estado.text(), "Se cerró Fortnite. Actualizando la lista...")
        self.mostrar_info(dialogo)
        self.assertTrue(dialogo.etiqueta_estado.text().startswith("Se cerró Fortnite. Datos de hace "))

    def test_si_no_confirma_no_manda_nada(self):
        dialogo = self.ventana()
        self.mostrar_info(dialogo)
        dialogo.tabla_programas.selectRow(0)
        with mock.patch.object(pcs_programas_dialogo, "confirmar", return_value=False):
            dialogo._cerrar_elegido()
        self.assertEqual(self.ultimo()["tipo"], dominio.COMANDO_INFO_PC)

    def test_abrir_el_icono_elegido(self):
        dialogo = self.ventana()
        self.mostrar_info(dialogo)
        dialogo.tabla_iconos.selectRow(2)

        dialogo._abrir_elegido()

        abrir = self.ultimo()
        self.assertEqual((abrir["tipo"], abrir["payload"]), (dominio.COMANDO_ABRIR_PROGRAMA, "Steam"))
        contestar(abrir["id"], "ERROR: El ícono ya no está en el escritorio.")
        dialogo._cada_segundo()
        self.assertEqual(dialogo.etiqueta_estado.text(),
                         "No se pudo: El ícono ya no está en el escritorio. Actualizando la lista...")

    def test_sin_elegir_nada_lo_pide(self):
        dialogo = self.ventana()
        self.mostrar_info(dialogo)
        dialogo._abrir_elegido()
        self.assertEqual(dialogo.etiqueta_estado.text().split(" Datos")[0],
                         "Elegí un ícono de la lista de la derecha.")
        self.assertEqual(self.ultimo()["tipo"], dominio.COMANDO_INFO_PC)

    def test_si_la_pc_no_contesta_lo_avisa(self):
        dialogo = self.ventana()
        for _ in range(pcs_programas_dialogo.SEGUNDOS_ESPERA_CAPTURA):
            dialogo._cada_segundo()
        self.assertEqual(dialogo.etiqueta_estado.text(), pcs_programas_dialogo.MENSAJE_SIN_RESPUESTA)
        self.assertTrue(dialogo.boton_actualizar.isEnabled())

    def test_a_una_pc_con_un_cliente_pc_viejo_no_le_manda_nada(self):
        poner_version(self.pc, "1.5")
        dialogo = self.ventana()
        self.assertEqual(comandos(self.pc), [])
        self.assertIn("tiene el Cliente PC V1.5: esto necesita la V1.6", dialogo.etiqueta_estado.text())
        self.assertFalse(dialogo.boton_actualizar.isEnabled())


class TestMantenimientoVentana(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")
        poner_version(self.pc, "1.6")
        self.operador = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA))

    def test_manda_la_orden_y_muestra_lo_que_contesta_la_pc(self):
        dialogo = DialogoMantenimiento(pcs_repo.obtener_estacion(self.pc), dominio.MANTENIMIENTO_INICIAR, self.operador)
        self.addCleanup(dialogo.deleteLater)
        (orden,) = comandos(self.pc)
        self.assertEqual(orden["payload"], "INICIAR")

        contestar(orden["id"], "OK: La PC queda libre 15 minutos y después se bloquea sola.")
        dialogo._revisar()

        self.assertEqual(dialogo.etiqueta_estado.text(),
                         "Listo: La PC queda libre 15 minutos y después se bloquea sola.")

    def test_con_un_cliente_pc_viejo_no_manda_nada(self):
        poner_version(self.pc, "1.5")
        dialogo = DialogoMantenimiento(pcs_repo.obtener_estacion(self.pc), dominio.MANTENIMIENTO_INICIAR, self.operador)
        self.addCleanup(dialogo.deleteLater)
        self.assertEqual(comandos(self.pc), [])
        self.assertIn("necesita la V1.6", dialogo.etiqueta_estado.text())


class TestClicDerecho(BaseConBaseTemporal):
    """Las entradas nuevas del menú de la PC, para cualquier operador."""

    def setUp(self):
        super().setUp()
        self.pc = pcs_repo.crear_estacion("PC07")
        poner_version(self.pc, "1.6")
        self.operador = usuarios_repo.obtener_usuario(usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA))

    def menu(self, elegir=None):
        """Abre el clic derecho de PC07 y elige la entrada que empieza con `elegir`. Devuelve
        {texto: habilitada} de lo que mostró."""
        grilla = pcs_window.PanelControlPcs(self.operador)
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        fila, = [f for f in range(grilla.mosaico.count()) if grilla.mosaico.ficha(f).nombre == "PC07"]
        visto = {}

        class MenuFalso(QMenu):
            """El menú de verdad, pero en vez de abrirse elige `elegir` (el exec de Qt no se
            puede reemplazar en la clase: hay que heredarla)."""

            def exec(self, *_args):
                acciones = [accion for accion in self.actions() if accion.text()]
                visto.update({accion.text(): accion.isEnabled() for accion in acciones})
                return next((a for a in acciones if elegir and a.text().startswith(elegir)), None)

        with mock.patch.object(pcs_window, "QMenu", MenuFalso), \
                mock.patch.object(grilla.mosaico, "fila_en", lambda _posicion: fila):
            grilla._mostrar_menu_contextual(QPoint(0, 0))
        return visto

    def test_programas_y_estado_para_cualquier_operador(self):
        with mock.patch.object(pcs_window, "DialogoProgramas") as ventana:
            visto = self.menu("📋")
        self.assertTrue(visto["📋 Programas y estado..."])
        self.assertEqual(ventana.call_args.args[0]["id"], self.pc)
        ventana.return_value.exec.assert_called_once()

    def test_hacer_mantenimiento_pregunta_y_manda_iniciar_con_el_operador(self):
        enlazar(self.pc)
        with mock.patch.object(pcs_window, "DialogoMantenimiento") as ventana, \
                mock.patch.object(pcs_window, "confirmar", return_value=True):
            visto = self.menu("🛠️")
        self.assertTrue(visto["🛠️ Hacer mantenimiento (15 min)"])
        estacion, orden, usuario = ventana.call_args.args[:3]
        self.assertEqual((estacion["id"], orden, usuario["nombre"]), (self.pc, "INICIAR", "TOBY"))

    def test_con_un_cliente_usando_la_pc_no_se_puede_hacer_mantenimiento(self):
        enlazar(self.pc)
        ocupar(self.pc)
        self.assertFalse(self.menu()["🛠️ Hacer mantenimiento (15 min)"])

    def test_en_mantenimiento_se_ofrece_terminarlo(self):
        enlazar(self.pc, mant_min=12)
        with mock.patch.object(pcs_window, "DialogoMantenimiento") as ventana, \
                mock.patch.object(pcs_window, "confirmar", return_value=True):
            visto = self.menu("🛠️")
        self.assertIn("🛠️ Terminar mantenimiento (quedan 12 min)", visto)
        self.assertEqual(ventana.call_args.args[1], "TERMINAR")

    def test_si_no_confirma_no_manda_nada(self):
        enlazar(self.pc)
        with mock.patch.object(pcs_window, "DialogoMantenimiento") as ventana, \
                mock.patch.object(pcs_window, "confirmar", return_value=False):
            self.menu("🛠️")
        ventana.assert_not_called()

    def test_de_una_pc_apagada_no_se_cree_un_mantenimiento_viejo(self):
        enlazar(self.pc, mant_min=12)
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                             ((datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds"), self.pc))
        self.assertIn("🛠️ Hacer mantenimiento (15 min)", self.menu())
