"""
tests/test_congelado.py
=========================
Congelar y descongelar PCs con Shadow Defender desde el mostrador (pedido del
dueño, 2026-10-18; ver congelado_repo y comandos_pc_repo): a qué PCs se les
puede mandar, qué viaja, y que la clave de Shadow Defender nunca quede guardada
en la base. Lo que hace cada PC con su CmdTool se prueba en el Cliente PC
(CLIENTE PC/tests/test_shadow_defender.py).
"""

import json
import os
from datetime import datetime, timedelta
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import comandos_pc_repo, congelado_repo, pcs_repo  # noqa: E402
from control_pcs.ui.pcs_congelado_dialogo import COLUMNA_RESPUESTA, DialogoCongelado  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402
from test_control_pcs import _ConServidorRed  # noqa: E402

_app = QApplication.instance() or QApplication([])

CLAVE = "clave-de-shadow-defender"


def ocupar(estacion_id):
    """Le vende un bono de una hora a la PC (un cliente la está usando)."""
    usuario_id = usuarios_repo.crear_usuario(f"Operador {estacion_id}", "1234", "ADMIN")
    bono_id = pcs_repo.crear_bono(f"1 hora {estacion_id}", 60, 3000)
    pcs_repo.asignar_bono(estacion_id, bono_id, usuario_id, [{"metodo": "EFECTIVO", "monto": 3000}])


def fila(comando_id):
    return comandos_pc_repo.obtener_comando(comando_id)


def envejecer(comando_id, minutos):
    """Hace de cuenta que el comando se encoló hace `minutos`."""
    antes = (datetime.now() - timedelta(minutes=minutos)).isoformat(timespec="seconds")
    with conexion_db() as conexion:
        conexion.execute("UPDATE comandos_pc SET fecha_creacion = ? WHERE id = ?", (antes, comando_id))


class TestPedir(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc1 = pcs_repo.crear_estacion("PC1")
        self.pc2 = pcs_repo.crear_estacion("PC2")

    def test_manda_un_comando_por_pc_con_la_clave_y_los_discos(self):
        enviados = congelado_repo.pedir([self.pc1, self.pc2], congelado_repo.DESCONGELAR, CLAVE, "c")

        self.assertEqual(set(enviados), {self.pc1, self.pc2})
        for estacion_id, comando_id in enviados.items():
            comando = fila(comando_id)
            self.assertEqual((comando["estacion_id"], comando["tipo"]), (estacion_id, "DESCONGELAR"))
            self.assertEqual(json.loads(comando["payload"]), {"clave": CLAVE, "discos": "C"})

    def test_los_tipos_son_los_que_entiende_el_cliente_pc(self):
        # Tienen que coincidir con CLIENTE PC/shadow_defender.py.
        self.assertEqual(dominio.COMANDOS_CON_CLAVE, ("DESCONGELAR", "CONGELAR", "ESTADO_CONGELADO"))
        for tipo in dominio.COMANDOS_CON_CLAVE:
            self.assertIn(tipo, dominio.TIPOS_COMANDO_PC)

    def test_no_descongela_una_pc_con_un_cliente_ni_manda_nada(self):
        ocupar(self.pc2)

        with self.assertRaisesRegex(ValueError, "PC2"):
            congelado_repo.pedir([self.pc1, self.pc2], congelado_repo.DESCONGELAR, CLAVE)

        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1))

    def test_congelar_y_ver_estado_saltean_la_pc_con_un_cliente_y_hacen_las_demas(self):
        # Pedido del dueño (2026-10-19): la clave no viaja a una PC donde el
        # cliente es Administrador de Windows.
        ocupar(self.pc1)
        for tipo in (congelado_repo.CONGELAR, congelado_repo.ESTADO):
            with self.subTest(tipo=tipo):
                enviados = congelado_repo.pedir([self.pc1, self.pc2], tipo, CLAVE)

                self.assertEqual(set(enviados), {self.pc2})
                self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1))

    def test_si_todas_tienen_un_cliente_no_manda_nada_ni_se_queja(self):
        ocupar(self.pc1)
        ocupar(self.pc2)

        self.assertEqual(congelado_repo.pedir([self.pc1, self.pc2], congelado_repo.CONGELAR, CLAVE), {})
        for estacion_id in (self.pc1, self.pc2):
            self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(estacion_id))

    def test_sin_clave_sin_pcs_o_con_discos_raros_no_manda_nada(self):
        for estacion_ids, clave, discos in (
            ([self.pc1], "", "C"),
            ([], CLAVE, "C"),
            ([self.pc1], CLAVE, ""),
            ([self.pc1], CLAVE, "C:\\Windows"),
            ([self.pc1], CLAVE, "1"),
        ):
            with self.subTest(clave=clave, discos=discos, pcs=estacion_ids):
                with self.assertRaises(ValueError):
                    congelado_repo.pedir(estacion_ids, congelado_repo.CONGELAR, clave, discos)
        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1))

    def test_una_pc_dada_de_baja_no_se_manda(self):
        pcs_repo.desactivar_estacion(self.pc2)
        with self.assertRaises(ValueError):
            congelado_repo.pedir([self.pc1, self.pc2], congelado_repo.CONGELAR, CLAVE)

    def test_otro_tipo_de_comando_no(self):
        with self.assertRaises(ValueError):
            congelado_repo.pedir([self.pc1], dominio.COMANDO_REINICIAR, CLAVE)

    def test_discos(self):
        self.assertEqual(congelado_repo.normalizar_discos("c"), "C")
        self.assertEqual(congelado_repo.normalizar_discos(" C, d: c "), "CD")


class TestVentana(BaseConBaseTemporal):
    """La ventana avisa en su renglón la PC que se salteó por tener un cliente."""

    def test_congelar_con_todas_marcadas_avisa_la_salteada(self):
        pc1 = pcs_repo.crear_estacion("PC1")
        pc2 = pcs_repo.crear_estacion("PC2")
        ocupar(pc1)
        estados = pcs_repo.estado_estaciones()
        elegida = next(item["estacion"] for item in estados if item["estacion"]["id"] == pc1)
        dialogo = DialogoCongelado(elegida, estados)
        self.addCleanup(dialogo.deleteLater)

        def respuesta(estacion_id):
            fila, _item = dialogo._filas[estacion_id]
            return dialogo.tabla.item(fila, COLUMNA_RESPUESTA).text()

        # Se cierra dentro de la prueba (y no con addCleanup, que corre después de
        # borrar la base temporal): al cerrar, la ventana toca la base.
        try:
            dialogo._marcar(lambda _item: True)
            dialogo.campo_clave.setText(CLAVE)
            dialogo.boton_congelar.click()

            # Cada respuesta con su marca: ✖ no se pudo, ⏳ todavía no contestó.
            self.assertEqual(respuesta(pc1), f"✖  {congelado_repo.texto_salteada()}")
            self.assertEqual(respuesta(pc2), "⏳  Esperando que la PC conteste...")
            self.assertEqual(set(dialogo._esperando), {pc2})
            self.assertIn("1 salteada", dialogo.etiqueta_estado.text())
        finally:
            dialogo.close()


class TestVentanaNueva(BaseConBaseTemporal):
    """El diseño de la maqueta "A" (2026-10-28): los números de la cabecera y
    ACTUALIZAR CLIENTES, que solo ve el Administrador."""

    ADMIN = {"rol": dominio.ROL_ADMIN}
    OPERADOR = {"rol": dominio.ROL_EMPLEADA}

    def setUp(self):
        super().setUp()
        self.ocupada = pcs_repo.crear_estacion("PC1")
        self.libre = pcs_repo.crear_estacion("PC2")
        self.apagada = pcs_repo.crear_estacion("PC3")
        pcs_repo.registrar_conexion(self.libre)
        ocupar(self.ocupada)

    def abrir(self, usuario=None):
        """La ventana del botón DESCONGELAR. Cada prueba la cierra adentro (y no con
        addCleanup, que corre después de borrar la base temporal): al cerrar, toca la base."""
        dialogo = DialogoCongelado(None, pcs_repo.estado_estaciones(), usuario)
        self.addCleanup(dialogo.deleteLater)
        return dialogo

    def test_la_cabecera_cuenta_las_elegidas_y_como_estan(self):
        dialogo = self.abrir()
        try:
            self.assertEqual(dialogo.pastilla_elegidas.text(), "1 ELEGIDA")
            self.assertEqual(dialogo.pastilla_con_cliente.text(), "1 CON CLIENTE")
            self.assertEqual(dialogo.pastilla_sin_conexion.text(), "1 SIN CONEXIÓN")
            # Cambia sola al marcar y desmarcar.
            dialogo._marcar(lambda _item: True)
            self.assertEqual(dialogo.pastilla_elegidas.text(), "3 ELEGIDAS")
            dialogo._marcar(lambda _item: False)
            self.assertEqual(dialogo.pastilla_elegidas.text(), "0 ELEGIDAS")
        finally:
            dialogo.close()

    def test_si_todas_tienen_conexion_no_muestra_esa_pastilla(self):
        pcs_repo.registrar_conexion(self.apagada)
        dialogo = self.abrir()
        try:
            self.assertTrue(dialogo.pastilla_sin_conexion.isHidden())
            self.assertFalse(dialogo.pastilla_con_cliente.isHidden())
        finally:
            dialogo.close()

    def test_el_admin_ve_actualizar_clientes_y_abre_la_ventana_de_siempre(self):
        dialogo = self.abrir(self.ADMIN)
        try:
            self.assertEqual(dialogo.boton_actualizar.accessibleName(), "Actualizar clientes")
            with mock.patch("control_pcs.ui.pcs_congelado_dialogo.DialogoActualizarCliente") as ventana:
                dialogo.boton_actualizar.click()
            ventana.assert_called_once_with(dialogo)
            ventana.return_value.exec.assert_called_once()
        finally:
            dialogo.close()

    def test_un_operador_no_ve_actualizar_clientes(self):
        for usuario in (self.OPERADOR, None):
            dialogo = self.abrir(usuario)
            try:
                self.assertIsNone(dialogo.boton_actualizar)
            finally:
                dialogo.close()

    def test_desde_otra_pc_tampoco(self):
        # La versión nueva se firma con la clave que vive en el mostrador.
        with mock.patch("control_pcs.ui.pcs_congelado_dialogo.modo_remoto.es_copia_remota", return_value=True):
            dialogo = self.abrir(self.ADMIN)
        try:
            self.assertIsNone(dialogo.boton_actualizar)
        finally:
            dialogo.close()


class TestLaClaveNoQuedaGuardada(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.pc1 = pcs_repo.crear_estacion("PC1")

    def test_se_borra_apenas_viaja_a_la_pc(self):
        (comando_id,) = congelado_repo.pedir([self.pc1], congelado_repo.CONGELAR, CLAVE).values()

        entregado = comandos_pc_repo.proximo_comando_pendiente(self.pc1)
        comandos_pc_repo.marcar_entregado(entregado["id"])

        self.assertIn(CLAVE, entregado["payload"])       # lo que viaja la lleva...
        self.assertIsNone(fila(comando_id)["payload"])     # ...pero en la base ya no está

    def test_los_demas_comandos_conservan_su_payload(self):
        comando_id = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_MENSAJE, "Hola")
        comandos_pc_repo.marcar_entregado(comando_id)
        self.assertEqual(fila(comando_id)["payload"], "Hola")

    def test_si_la_pc_no_la_pide_a_tiempo_se_vence_y_no_le_llega(self):
        (comando_id,) = congelado_repo.pedir([self.pc1], congelado_repo.DESCONGELAR, CLAVE).values()
        envejecer(comando_id, comandos_pc_repo.MINUTOS_VIGENCIA_CON_CLAVE + 1)

        self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1))
        comando = fila(comando_id)
        self.assertIsNone(comando["payload"])
        self.assertEqual(comando["estado"], dominio.ESTADO_COMANDO_ENTREGADO)
        self.assertEqual(comando["resultado"], comandos_pc_repo.RESULTADO_VENCIDO)

    def test_uno_reciente_si_le_llega(self):
        (comando_id,) = congelado_repo.pedir([self.pc1], congelado_repo.DESCONGELAR, CLAVE).values()
        envejecer(comando_id, comandos_pc_repo.MINUTOS_VIGENCIA_CON_CLAVE - 1)
        self.assertEqual(comandos_pc_repo.proximo_comando_pendiente(self.pc1)["id"], comando_id)

    def test_un_mensaje_viejo_no_se_vence(self):
        comando_id = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_MENSAJE, "Hola")
        envejecer(comando_id, 60)
        self.assertEqual(comandos_pc_repo.proximo_comando_pendiente(self.pc1)["id"], comando_id)

    def test_reiniciar_o_apagar_que_la_pc_no_pidio_a_tiempo_no_le_llega_despues(self):
        # Mandado a una PC sin conexión: si le llegara al volver, la reiniciaría en medio de la
        # partida de otro cliente (revisión del 2026-10-21).
        for tipo in (comandos_pc_repo.TIPO_REINICIAR, comandos_pc_repo.TIPO_APAGAR):
            with self.subTest(tipo=tipo):
                comando_id = comandos_pc_repo.encolar_comando(self.pc1, tipo)
                envejecer(comando_id, comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO + 1)

                self.assertIsNone(comandos_pc_repo.proximo_comando_pendiente(self.pc1))
                comando = fila(comando_id)
                self.assertEqual(comando["estado"], dominio.ESTADO_COMANDO_ENTREGADO)
                self.assertEqual(comando["resultado"], comandos_pc_repo.RESULTADO_REINICIO_VENCIDO)

    def test_reiniciar_reciente_si_le_llega(self):
        comando_id = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_REINICIAR)
        envejecer(comando_id, comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO - 1)
        self.assertEqual(comandos_pc_repo.proximo_comando_pendiente(self.pc1)["id"], comando_id)

    def test_un_reiniciar_vencido_de_otra_pc_no_se_toca(self):
        pc2 = pcs_repo.crear_estacion("PC2")
        comando_id = comandos_pc_repo.encolar_comando(pc2, comandos_pc_repo.TIPO_REINICIAR)
        envejecer(comando_id, comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO + 1)
        comandos_pc_repo.proximo_comando_pendiente(self.pc1)
        self.assertEqual(fila(comando_id)["estado"], dominio.ESTADO_COMANDO_PENDIENTE)

    def test_al_cerrar_la_ventana_se_borra_de_los_que_no_viajaron(self):
        pc2 = pcs_repo.crear_estacion("PC2")
        enviados = congelado_repo.pedir([self.pc1, pc2], congelado_repo.CONGELAR, CLAVE)
        otro = congelado_repo.pedir([pc2], congelado_repo.ESTADO, CLAVE)[pc2]

        comandos_pc_repo.descartar_clave_de_pendientes([enviados[self.pc1], enviados[pc2]])

        for comando_id in enviados.values():
            self.assertIsNone(fila(comando_id)["payload"])
            self.assertEqual(fila(comando_id)["resultado"], comandos_pc_repo.RESULTADO_VENCIDO)
        self.assertIn(CLAVE, fila(otro)["payload"])   # el de otra tanda no se toca

    def test_descartar_no_pisa_una_respuesta_que_ya_llego(self):
        (comando_id,) = congelado_repo.pedir([self.pc1], congelado_repo.CONGELAR, CLAVE).values()
        comandos_pc_repo.marcar_entregado(comando_id)
        comandos_pc_repo.marcar_resultado(comando_id, "OK: Congelada (Modo Sombra): C.")

        comandos_pc_repo.descartar_clave_de_pendientes([comando_id])

        self.assertEqual(fila(comando_id)["resultado"], "OK: Congelada (Modo Sombra): C.")

    def test_al_arrancar_el_programa_se_borran_todos_los_que_quedaron(self):
        # Son de la vez anterior: el programa se cerró con la ventana abierta.
        (comando_id,) = congelado_repo.pedir([self.pc1], congelado_repo.CONGELAR, CLAVE).values()
        mensaje = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_MENSAJE, "Hola")

        comandos_pc_repo.descartar_clave_de_pendientes(todos=True)

        self.assertIsNone(fila(comando_id)["payload"])
        self.assertEqual(comandos_pc_repo.proximo_comando_pendiente(self.pc1)["id"], mensaje)

    def test_al_abrir_la_ventana_se_vencen_los_viejos_de_todas_las_pcs(self):
        pc2 = pcs_repo.crear_estacion("PC2")
        viejo = congelado_repo.pedir([pc2], congelado_repo.CONGELAR, CLAVE)[pc2]
        envejecer(viejo, comandos_pc_repo.MINUTOS_VIGENCIA_CON_CLAVE + 1)
        nuevo = congelado_repo.pedir([self.pc1], congelado_repo.CONGELAR, CLAVE)[self.pc1]

        comandos_pc_repo.descartar_clave_de_pendientes()

        self.assertIsNone(fila(viejo)["payload"])
        self.assertIn(CLAVE, fila(nuevo)["payload"])


class TestRespuestas(BaseConBaseTemporal):
    def test_interpretar(self):
        self.assertIsNone(congelado_repo.interpretar_respuesta(None))
        self.assertIsNone(congelado_repo.interpretar_respuesta(""))
        self.assertEqual(congelado_repo.interpretar_respuesta("OK: Congelada (Modo Sombra): C."),
                         (True, "Congelada (Modo Sombra): C."))
        self.assertEqual(congelado_repo.interpretar_respuesta("ERROR: La clave no es correcta."),
                         (False, "La clave no es correcta."))
        self.assertEqual(congelado_repo.interpretar_respuesta("otra cosa"), (False, "otra cosa"))

    def test_la_ventana_deja_de_esperar_antes_de_que_se_venza_la_clave(self):
        self.assertLess(congelado_repo.SEGUNDOS_ESPERA_RESPUESTA,
                        comandos_pc_repo.MINUTOS_VIGENCIA_CON_CLAVE * 60)

    def test_obtener_varios_comandos_de_una(self):
        pc1 = pcs_repo.crear_estacion("PC1")
        uno = comandos_pc_repo.encolar_comando(pc1, comandos_pc_repo.TIPO_REINICIAR)
        dos = comandos_pc_repo.encolar_comando(pc1, comandos_pc_repo.TIPO_APAGAR)

        self.assertEqual(set(comandos_pc_repo.obtener_comandos([uno, dos])), {uno, dos})
        self.assertEqual(comandos_pc_repo.obtener_comandos([]), {})


class TestCongelarPorLaRed(_ConServidorRed):
    """El viaje entero por el servidor de red, como lo ve el Cliente PC."""

    def test_la_pc_recibe_la_clave_una_vez_y_contesta(self):
        pc1 = pcs_repo.crear_estacion("PC1")
        (comando_id,) = congelado_repo.pedir([pc1], congelado_repo.DESCONGELAR, CLAVE).values()

        _, datos = self._get("/estado?estacion=PC1")
        self.assertEqual(datos["comando"]["tipo"], "DESCONGELAR")
        self.assertEqual(json.loads(datos["comando"]["payload"]), {"clave": CLAVE, "discos": "C"})
        self.assertIsNone(fila(comando_id)["payload"])
        self.assertIsNone(self._get("/estado?estacion=PC1")[1]["comando"])

        texto = "OK: Listo: C queda descongelado al reiniciar. La PC se reinicia ahora."
        self.assertEqual(self._post("/comando_resultado", {"comando_id": comando_id, "texto": texto})[0], 200)
        self.assertEqual(congelado_repo.interpretar_respuesta(fila(comando_id)["resultado"]),
                         (True, "Listo: C queda descongelado al reiniciar. La PC se reinicia ahora."))


class TestReiniciandoAlDescongelar(_ConServidorRed):
    """Un DESCONGELAR que contestó OK reinicia la PC: el mosaico la muestra REINICIANDO hasta que
    vuelve (pedido del dueño, 2026-10-28), aunque la ventana de Congelar ya esté cerrada."""

    OK = "OK: Listo: C queda descongelado al reiniciar. La PC se reinicia ahora."

    def setUp(self):
        super().setUp()
        self.pc1 = pcs_repo.crear_estacion("PC1")
        (self.comando_id,) = congelado_repo.pedir([self.pc1], congelado_repo.DESCONGELAR, CLAVE).values()
        # La PC lo pide (prendida hace una hora) y contesta.
        self.assertEqual(self._get("/estado?estacion=PC1&encendida=3600")[1]["comando"]["tipo"], "DESCONGELAR")

    def contestar(self, texto):
        self.assertEqual(self._post("/comando_resultado", {"comando_id": self.comando_id, "texto": texto})[0], 200)

    def reiniciando(self):
        item = next(item for item in pcs_repo.estado_estaciones() if item["estacion"]["id"] == self.pc1)
        return item["reiniciando"]

    def test_con_ok_dice_reiniciando(self):
        self.contestar(self.OK)

        self.assertEqual(self.reiniciando(), comandos_pc_repo.REINICIANDO_POR_DESCONGELAR)
        item = next(item for item in pcs_repo.estado_estaciones() if item["estacion"]["id"] == self.pc1)
        ficha = PanelControlPcs._ficha_de_pc(item)
        self.assertEqual(ficha.aviso, "REINICIANDO")
        self.assertIn("Reiniciando para descongelarse", ficha.estado)

    def test_con_error_no(self):
        self.contestar("ERROR: La clave no es correcta.")
        self.assertIsNone(self.reiniciando())

    def test_sin_respuesta_no(self):
        self.assertIsNone(self.reiniciando())
        # Ni cuando la ventana se cierra sin respuesta (se da por vencido).
        comandos_pc_repo.descartar_clave_de_pendientes(todos=True)
        self.assertIsNone(self.reiniciando())

    def test_aunque_se_cierre_la_ventana(self):
        self.contestar(self.OK)
        comandos_pc_repo.descartar_clave_de_pendientes([self.comando_id])
        self.assertEqual(self.reiniciando(), comandos_pc_repo.REINICIANDO_POR_DESCONGELAR)

    def test_mientras_no_volvio_sigue_diciendolo(self):
        self.contestar(self.OK)
        envejecer(self.comando_id, 1)
        # Todavía no se reinició: Windows sigue prendido desde antes.
        self._get("/estado?estacion=PC1&encendida=3600")
        self.assertEqual(self.reiniciando(), comandos_pc_repo.REINICIANDO_POR_DESCONGELAR)

    def test_cuando_vuelve_deja_de_decirlo(self):
        self.contestar(self.OK)
        envejecer(self.comando_id, 1)
        # Vuelve con Windows recién arrancado.
        self._get("/estado?estacion=PC1&encendida=20")
        self.assertIsNone(self.reiniciando())
        # Lo que contestó queda como estaba.
        self.assertEqual(fila(self.comando_id)["resultado"], self.OK)

    def test_si_no_vuelve_deja_de_decirlo_a_los_5_minutos(self):
        self.contestar(self.OK)
        envejecer(self.comando_id, comandos_pc_repo.MINUTOS_REINICIANDO + 1)
        self.assertIsNone(self.reiniciando())
