"""
tests/test_primer_ingreso_socio.py
====================================
Alta rápida de socios y datos del primer ingreso (pedido del dueño,
2026-10-17): para crear un socio alcanzan usuario y contraseña, y el DNI
(obligatorio), el celular y el WhatsApp (opcionales) los completa el socio la
primera vez que entra desde su PC. Ver miembros_repo.abrir_estacion_por_miembro
y POST /login en servidor_red.py.
"""

import unittest

import database
from repositories import usuarios_repo
from control_pcs.repositories import miembros_repo, pcs_repo
from base import BaseConBaseTemporal
from test_control_pcs import _ConServidorRed

DATOS_BUENOS = {"dni": "30.111.222", "celular": "11 5555-4444", "whatsapp": "+54 9 11 5555 4444"}


def _socio(miembro_id):
    return miembros_repo.obtener_miembro(miembro_id)


def _darle_saldo(miembro_id, minutos=120):
    with database.conexion_db() as conexion:
        conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (minutos, miembro_id))


def _sesiones():
    with database.conexion_db() as conexion:
        return conexion.execute("SELECT * FROM sesiones_pc").fetchall()


class TestAltaRapida(BaseConBaseTemporal):
    def test_alcanza_con_usuario_y_clave(self):
        miembro_id = miembros_repo.crear_miembro("juancho", "clave123")

        socio = _socio(miembro_id)
        # Sin nombre, se lo ve con el usuario (en la lista y en las PCs).
        self.assertEqual(socio["nombre"], "juancho")
        self.assertEqual((socio["dni"], socio["telefono"], socio["whatsapp"], socio["email"]),
                         ("", "", "", None))
        self.assertFalse(miembros_repo.tiene_dni(socio))
        self.assertIsNotNone(miembros_repo.autenticar_miembro("juancho", "clave123"))

    def test_sin_usuario_o_sin_clave_no_se_crea(self):
        with self.assertRaises(ValueError):
            miembros_repo.crear_miembro("  ", "clave123")
        with self.assertRaises(ValueError):
            miembros_repo.crear_miembro("juancho", "")

    def test_si_se_cargan_los_datos_se_guardan_solo_con_los_numeros(self):
        miembro_id = miembros_repo.crear_miembro(
            "juan", "clave123", "Juan Pérez", "30.111.222", "(011) 5555-4444", whatsapp="+54 9 11 5555 4444",
        )

        socio = _socio(miembro_id)
        self.assertEqual((socio["dni"], socio["telefono"], socio["whatsapp"]),
                         ("30111222", "01155554444", "+5491155554444"))
        self.assertTrue(miembros_repo.tiene_dni(socio))

    def test_un_dni_o_un_telefono_mal_escrito_no_se_guarda(self):
        for dni in ("123", "123456789", "30111abc"):
            with self.subTest(dni=dni), self.assertRaises(ValueError):
                miembros_repo.crear_miembro("juan", "clave123", dni=dni)
        with self.assertRaises(ValueError):
            miembros_repo.crear_miembro("juan", "clave123", telefono="1234")
        with self.assertRaises(ValueError):
            miembros_repo.crear_miembro("juan", "clave123", whatsapp="no tengo")
        self.assertEqual(miembros_repo.listar_miembros(), [])

    def test_un_dni_no_puede_estar_en_dos_cuentas_activas(self):
        miembros_repo.crear_miembro("juan", "clave123", dni="30111222")

        with self.assertRaises(ValueError) as error:
            miembros_repo.crear_miembro("juan2", "clave123", dni="30.111.222")
        self.assertIn("juan", str(error.exception))

    def test_el_dni_de_una_cuenta_desactivada_se_puede_volver_a_usar(self):
        viejo_id = miembros_repo.crear_miembro("juan", "clave123", dni="30111222")
        miembros_repo.desactivar_miembro(viejo_id)

        miembros_repo.crear_miembro("juan_nuevo", "clave123", dni="30111222")

    def test_modificar_conserva_su_propio_dni_pero_no_toma_el_de_otro(self):
        juan_id = miembros_repo.crear_miembro("juan", "clave123", dni="30111222")
        ana_id = miembros_repo.crear_miembro("ana", "clave123", dni="30333444")

        miembros_repo.modificar_miembro(juan_id, "juan", "Juan Pérez", "30111222", "1155554444",
                                        whatsapp="1155554444")
        self.assertEqual(_socio(juan_id)["whatsapp"], "1155554444")
        with self.assertRaises(ValueError):
            miembros_repo.modificar_miembro(ana_id, "ana", "", "30111222", "")
        self.assertEqual(_socio(ana_id)["dni"], "30333444")

    def test_tiene_dni_solo_con_un_dni_valido(self):
        # Un socio cargado cuando el DNI era obligatorio pudo quedar con un relleno.
        for dni, esperado in (("", False), ("-", False), ("0", False), ("30111222", True),
                              ("30.111.222", True), ("1234567", True)):
            with self.subTest(dni=dni):
                self.assertEqual(miembros_repo.tiene_dni({"dni": dni}), esperado)


class TestDatosDelPrimerIngreso(BaseConBaseTemporal):
    """miembros_repo.abrir_estacion_por_miembro con pedir_datos (el Cliente PC nuevo)."""

    def setUp(self):
        super().setUp()
        self.estacion_id = pcs_repo.crear_estacion("PC 1")
        self.miembro_id = miembros_repo.crear_miembro("juancho", "clave123")
        _darle_saldo(self.miembro_id)

    def _entrar(self, datos=None, pedir_datos=True):
        return miembros_repo.abrir_estacion_por_miembro(
            self.estacion_id, "juancho", "clave123", pedir_datos=pedir_datos, datos_socio=datos,
        )

    def _no_paso_nada(self):
        socio = _socio(self.miembro_id)
        self.assertEqual(socio["saldo_minutos"], 120)
        self.assertEqual(socio["dni"], "")
        self.assertEqual(_sesiones(), [])

    def test_sin_dni_pide_los_datos_sin_abrir_la_pc_ni_gastar_saldo(self):
        with self.assertRaises(miembros_repo.FaltanDatosDelSocio):
            self._entrar()
        self._no_paso_nada()

    def test_con_los_datos_los_guarda_y_abre_la_pc_con_todo_el_saldo(self):
        resumen = self._entrar(DATOS_BUENOS)

        socio = _socio(self.miembro_id)
        self.assertEqual((socio["dni"], socio["telefono"], socio["whatsapp"]),
                         ("30111222", "1155554444", "+5491155554444"))
        self.assertEqual(socio["saldo_minutos"], 0)
        self.assertEqual(resumen["minutos_usados"], 120)
        self.assertEqual(len(_sesiones()), 1)

    def test_es_una_sola_vez(self):
        self._entrar(DATOS_BUENOS)
        pcs_repo.finalizar_sesion(_sesiones()[0]["id"])
        _darle_saldo(self.miembro_id)

        # La segunda vez entra directo, y lo que mande no pisa lo que ya tenía.
        self._entrar({"dni": "40999888", "celular": "", "whatsapp": ""})
        self.assertEqual(_socio(self.miembro_id)["dni"], "30111222")

    def test_celular_y_whatsapp_son_opcionales_y_no_borran_lo_del_mostrador(self):
        with database.conexion_db() as conexion:
            conexion.execute("UPDATE miembros SET telefono = '1166667777' WHERE id = ?", (self.miembro_id,))

        self._entrar({"dni": "30111222", "celular": "", "whatsapp": ""})

        socio = _socio(self.miembro_id)
        self.assertEqual((socio["dni"], socio["telefono"], socio["whatsapp"]), ("30111222", "1166667777", ""))

    def test_sin_dni_o_con_un_dni_mal_escrito_no_guarda_nada_ni_abre(self):
        for dni in ("", "   ", "12.34", "treinta"):
            with self.subTest(dni=dni):
                with self.assertRaises(ValueError):
                    self._entrar({"dni": dni, "celular": "1155554444", "whatsapp": ""})
                self._no_paso_nada()
                self.assertEqual(_socio(self.miembro_id)["telefono"], "")

    def test_un_telefono_mal_escrito_tampoco_deja_nada_a_medias(self):
        with self.assertRaises(ValueError):
            self._entrar({"dni": "30111222", "celular": "12", "whatsapp": ""})
        self._no_paso_nada()

    def test_un_dni_de_otra_cuenta_lo_manda_al_mostrador(self):
        miembros_repo.crear_miembro("juan_viejo", "clave123", dni="30111222")

        with self.assertRaises(ValueError) as error:
            self._entrar(DATOS_BUENOS)
        self.assertIn("mostrador", str(error.exception))
        self._no_paso_nada()

    def test_sin_saldo_avisa_eso_antes_de_pedirle_los_datos(self):
        _darle_saldo(self.miembro_id, 0)

        with self.assertRaises(ValueError) as error:
            self._entrar()
        self.assertIn("saldo", str(error.exception))

    def test_con_la_clave_mal_no_pide_nada(self):
        with self.assertRaises(ValueError):
            miembros_repo.abrir_estacion_por_miembro(self.estacion_id, "juancho", "otra", pedir_datos=True)

    def test_un_cliente_pc_viejo_entra_como_siempre_y_se_le_pide_la_proxima(self):
        self._entrar(pedir_datos=False)

        self.assertEqual(len(_sesiones()), 1)
        self.assertFalse(miembros_repo.tiene_dni(_socio(self.miembro_id)))

    def test_un_socio_con_dni_entra_directo(self):
        miembros_repo.modificar_miembro(self.miembro_id, "juancho", "", "30111222", "")

        self._entrar()

        self.assertEqual(len(_sesiones()), 1)


class TestMigracionWhatsapp(BaseConBaseTemporal):
    def test_una_base_vieja_suma_la_columna_sin_tocar_a_los_socios(self):
        miembro_id = miembros_repo.crear_miembro("juan", "clave123", "Juan", "30111222", "1155554444")
        with database.conexion_db() as conexion:
            conexion.execute("ALTER TABLE miembros DROP COLUMN whatsapp")

        database.inicializar_base_de_datos()

        socio = _socio(miembro_id)
        self.assertEqual((socio["nombre"], socio["dni"], socio["telefono"], socio["whatsapp"]),
                         ("Juan", "30111222", "1155554444", ""))
        database.inicializar_base_de_datos()   # segura de correr dos veces


class TestServidorRedPrimerIngreso(_ConServidorRed):
    """POST /login con los datos del primer ingreso (ver _ConServidorRed)."""

    def setUp(self):
        super().setUp()
        usuarios_repo.crear_usuario("Test", "1234", "ADMIN")
        pcs_repo.crear_estacion("PC 8")
        self.miembro_id = miembros_repo.crear_miembro("juancho", "clave123")
        _darle_saldo(self.miembro_id)

    def _login(self, **extra):
        return self._post("/login", {"estacion": "PC 8", "usuario": "juancho", "clave": "clave123", **extra})

    def test_avisa_que_faltan_los_datos_y_despues_entra_con_ellos(self):
        status, datos = self._login(pide_datos=True)
        self.assertEqual(status, 200)
        self.assertFalse(datos["ok"])
        self.assertTrue(datos["faltan_datos"])
        self.assertTrue(datos["error"])
        self.assertEqual(_sesiones(), [])

        status, datos = self._login(pide_datos=True, datos_socio=DATOS_BUENOS)
        self.assertEqual(status, 200)
        self.assertTrue(datos["ok"])
        self.assertEqual(datos["sesion_id"], _sesiones()[0]["id"])
        self.assertEqual(_socio(self.miembro_id)["dni"], "30111222")

    def test_un_dni_mal_escrito_vuelve_con_el_motivo(self):
        status, datos = self._login(pide_datos=True, datos_socio={"dni": "12", "celular": "", "whatsapp": ""})

        self.assertEqual(status, 400)
        self.assertFalse(datos["ok"])
        self.assertNotIn("faltan_datos", datos)
        self.assertIn("DNI", datos["error"])

    def test_un_cliente_pc_viejo_no_manda_pide_datos_y_entra(self):
        status, datos = self._login()

        self.assertEqual(status, 200)
        self.assertTrue(datos["ok"])

    def test_datos_socio_que_no_son_un_objeto_es_un_pedido_invalido(self):
        status, datos = self._login(pide_datos=True, datos_socio="30111222")

        self.assertEqual(status, 400)
        self.assertEqual(_sesiones(), [])


if __name__ == "__main__":
    unittest.main()
