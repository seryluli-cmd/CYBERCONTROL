"""
tests/test_cambiar_clave_socio.py
==================================
El socio cambia su contraseña desde la franja de su PC (pedido del dueño,
2026-11-20: "me lo pidieron"; eligió el botón en la franja, la pantalla B):
`miembros_repo.cambiar_clave_desde_la_pc` y `POST /cambiar_clave` de
servidor_red.py. El socio es el de la sesión abierta en esa PC: el usuario no
viaja. Pide la actual y una nueva de al menos 4 caracteres.

    python -m unittest discover -s tests -p test_cambiar_clave_socio.py
"""

import database
from repositories import usuarios_repo
from control_pcs.repositories import miembros_repo, pcs_repo
from base import BaseConBaseTemporal
from test_control_pcs import _ConServidorRed


def _socio_con_saldo(usuario="juan", clave="clave123", minutos=60, dni="30111222"):
    miembro_id = miembros_repo.crear_miembro(usuario, clave, usuario.capitalize(), dni, "1155554444")
    with database.conexion_db() as conexion:
        conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, miembro_id))
    return miembro_id


class TestCambiarClaveDesdeLaPc(BaseConBaseTemporal):
    """La regla, en miembros_repo."""

    def setUp(self):
        super().setUp()
        self.juan = _socio_con_saldo()

    def _entra_con(self, clave):
        return miembros_repo.autenticar_miembro("juan", clave) is not None

    def test_cambia_la_clave_y_la_vieja_deja_de_servir(self):
        miembros_repo.cambiar_clave_desde_la_pc(self.juan, "clave123", "nueva1")

        self.assertTrue(self._entra_con("nueva1"))
        self.assertFalse(self._entra_con("clave123"))

    def test_con_la_actual_equivocada_no_cambia_nada(self):
        with self.assertRaisesRegex(ValueError, "La contraseña actual no es correcta."):
            miembros_repo.cambiar_clave_desde_la_pc(self.juan, "otra", "nueva1")

        self.assertTrue(self._entra_con("clave123"))
        self.assertFalse(self._entra_con("nueva1"))

    def test_la_nueva_tiene_que_tener_al_menos_4_caracteres(self):
        self.assertEqual(miembros_repo.LARGO_MINIMO_CLAVE_SOCIO, 4)   # decisión del dueño
        for corta in ("", "abc", "    ", " ab "):
            with self.assertRaisesRegex(ValueError, "al menos 4 caracteres"):
                miembros_repo.cambiar_clave_desde_la_pc(self.juan, "clave123", corta)
        self.assertTrue(self._entra_con("clave123"))

        miembros_repo.cambiar_clave_desde_la_pc(self.juan, "clave123", "abcd")
        self.assertTrue(self._entra_con("abcd"))

    def test_la_nueva_igual_a_la_actual_se_avisa(self):
        with self.assertRaisesRegex(ValueError, "igual a la actual"):
            miembros_repo.cambiar_clave_desde_la_pc(self.juan, "clave123", "clave123")

    def test_un_socio_desactivado_no_la_cambia(self):
        miembros_repo.desactivar_miembro(self.juan)

        with self.assertRaisesRegex(ValueError, "no está activa"):
            miembros_repo.cambiar_clave_desde_la_pc(self.juan, "clave123", "nueva1")

    def test_solo_cambia_la_del_socio_que_se_pide(self):
        ana = _socio_con_saldo("ana", "clave123", dni="30999888")
        with database.conexion_db() as conexion:
            antes = conexion.execute("SELECT clave_hash FROM miembros WHERE id = ?", (ana,)).fetchone()[0]

        miembros_repo.cambiar_clave_desde_la_pc(self.juan, "clave123", "nueva1")

        with database.conexion_db() as conexion:
            despues = conexion.execute("SELECT clave_hash FROM miembros WHERE id = ?", (ana,)).fetchone()[0]
        self.assertEqual(antes, despues)


class TestServidorRedCambiarClave(_ConServidorRed):
    """POST /cambiar_clave: el socio es el que está jugando en esa PC."""

    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        self.pc8 = pcs_repo.crear_estacion("PC 8")
        self.juan = _socio_con_saldo()

    def _entrar(self):
        status, datos = self._post("/login", {"estacion": "PC 8", "usuario": "juan", "clave": "clave123"})
        self.assertEqual(status, 200, datos)
        return datos["sesion_id"]

    def _cambiar(self, **cuerpo):
        return self._post("/cambiar_clave", {"estacion": "PC 8", **cuerpo})

    def _entra_con(self, clave):
        return miembros_repo.autenticar_miembro("juan", clave) is not None

    def test_el_socio_que_juega_cambia_su_clave(self):
        sesion_id = self._entrar()

        status, datos = self._cambiar(sesion_id=sesion_id, clave_actual="clave123", clave_nueva="nueva1")

        self.assertEqual((status, datos), (200, {"ok": True}))
        self.assertTrue(self._entra_con("nueva1"))
        self.assertFalse(self._entra_con("clave123"))
        # Cambiar la contraseña no toca la sesión.
        self.assertEqual(pcs_repo.estado_estaciones()[0]["sesion"]["id"], sesion_id)

    def test_sin_sesion_id_cambia_la_del_socio_de_la_sesion_abierta(self):
        self._entrar()

        status, datos = self._cambiar(clave_actual="clave123", clave_nueva="nueva1")

        self.assertEqual((status, datos), (200, {"ok": True}))
        self.assertTrue(self._entra_con("nueva1"))

    def test_los_errores_del_socio_vuelven_con_el_motivo(self):
        sesion_id = self._entrar()

        for actual, nueva, motivo in (
            ("otra", "nueva1", "La contraseña actual no es correcta."),
            ("clave123", "abc", "La contraseña nueva tiene que tener al menos 4 caracteres."),
            ("clave123", "clave123", "La contraseña nueva es igual a la actual."),
        ):
            status, datos = self._cambiar(sesion_id=sesion_id, clave_actual=actual, clave_nueva=nueva)
            self.assertEqual((status, datos), (400, {"ok": False, "error": motivo}))
        self.assertTrue(self._entra_con("clave123"))

    def test_con_la_sesion_de_otro_no_se_cambia_nada(self):
        # Juan se fue y en la misma PC entró Ana: un pedido que todavía dice la sesión de Juan
        # no le cambia la contraseña a nadie.
        sesion_juan = self._entrar()
        pcs_repo.finalizar_sesion(sesion_juan)
        _socio_con_saldo("ana", "clave123", dni="30999888")
        status, _datos = self._post("/login", {"estacion": "PC 8", "usuario": "ana", "clave": "clave123"})
        self.assertEqual(status, 200)

        status, datos = self._cambiar(sesion_id=sesion_juan, clave_actual="clave123", clave_nueva="nueva1")

        self.assertEqual((status, datos),
                         (400, {"ok": False, "error": "Tu sesión ya terminó: no se cambió la contraseña."}))
        self.assertTrue(self._entra_con("clave123"))
        self.assertIsNotNone(miembros_repo.autenticar_miembro("ana", "clave123"))

    def test_sin_sesion_o_con_bono_no_hay_contrasena_que_cambiar(self):
        status, datos = self._cambiar(clave_actual="clave123", clave_nueva="nueva1")
        self.assertEqual((status, datos),
                         (400, {"ok": False, "error": "Tu sesión ya terminó: no se cambió la contraseña."}))

        bono = pcs_repo.crear_bono("1 hora", 60, 3000)
        pcs_repo.asignar_bono(self.pc8, bono, self.admin, [{"metodo": "EFECTIVO", "monto": 3000}])
        status, datos = self._cambiar(clave_actual="clave123", clave_nueva="nueva1")
        self.assertEqual((status, datos), (400, {"ok": False, "error": "Solo los socios tienen contraseña."}))
        self.assertTrue(self._entra_con("clave123"))

    def test_pedido_incompleto_o_estacion_desconocida(self):
        self.assertEqual(self._post("/cambiar_clave", {}), (400, {"ok": False, "error": "Pedido inválido."}))
        self.assertEqual(self._post("/cambiar_clave", {"estacion": "PC 8", "clave_actual": "x"}),
                         (400, {"ok": False, "error": "Pedido inválido."}))
        self.assertEqual(
            self._post("/cambiar_clave", {"estacion": "PC 99", "clave_actual": "a", "clave_nueva": "bbbb"}),
            (404, {"ok": False, "error": "Estación desconocida."}),
        )
