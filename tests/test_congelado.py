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
from datetime import datetime, timedelta

import dominio
from control_pcs.repositories import comandos_pc_repo, congelado_repo, pcs_repo
from database import conexion_db
from repositories import usuarios_repo
from base import BaseConBaseTemporal
from test_control_pcs import _ConServidorRed

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

    def test_congelar_y_ver_estado_si_con_un_cliente(self):
        ocupar(self.pc1)
        for tipo in (congelado_repo.CONGELAR, congelado_repo.ESTADO):
            self.assertIn(self.pc1, congelado_repo.pedir([self.pc1], tipo, CLAVE))

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

    def test_un_comando_viejo_sin_clave_no_se_vence(self):
        comando_id = comandos_pc_repo.encolar_comando(self.pc1, comandos_pc_repo.TIPO_REINICIAR)
        envejecer(comando_id, 60)
        self.assertEqual(comandos_pc_repo.proximo_comando_pendiente(self.pc1)["id"], comando_id)

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
