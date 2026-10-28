"""
tests/test_envio_pwa.py
=========================
El envío de cada Cierre de Turno a la app de gastos del dueño (la PWA "Gastos —
CyberBIOS"; repositories/envio_pwa_repo.py y ui/envio_pwa_dialogo.py, pedido del
dueño 2026-10-26): qué viaja y a nombre de quién (la responsable de la caja, el
forzoso marcado, el turno con el nombre de allá), que el cierre quede en la cola
solo con el envío prendido y en la misma transacción, que un cierre se mande una
sola vez aunque se reintente, cómo se espera sin internet, el login anónimo que
se conserva, "Probar la conexión" con los nombres que faltan, y la pantalla.

Google se reemplaza por una app de mentira (_AppDeGastosDePrueba): ninguna
prueba sale a internet ni toca el Firestore real.

Se ejecutan con:

    python -m unittest discover tests
"""

import json
import os
import threading
import time
import unittest
from datetime import date, datetime, timedelta, timezone
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import dominio  # noqa: E402
import turnos  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import (  # noqa: E402
    articulos_repo, compras_repo, envio_pwa_repo, relevo_repo, turnos_repo, usuarios_repo, ventas_repo,
)
from ui.caja_window import CierreTurnoWindow  # noqa: E402
from ui.configuracion_admin_window import ConfiguracionAdminWindow  # noqa: E402
from ui.control_cierres_window import ControlCierresWindow  # noqa: E402
from ui.envio_pwa_dialogo import DialogoEnvioPwa  # noqa: E402
from ui.envio_pwa_progreso import (  # noqa: E402
    ENVIADO, ERROR, PENDIENTE, SEGUNDOS_MAXIMOS, TOPE_SIN_CONFIRMAR, DialogoEnviandoCierre,
)
from ui.utils import formato_pesos  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

LUNES = date(2026, 1, 5)
MARTES = date(2026, 1, 6)
DOMINGO = date(2026, 1, 4)
TARJETA = "Cierres a la app de gastos"


def _a_las(hora, minuto=0, dia=LUNES):
    return datetime(dia.year, dia.month, dia.day, hora, minuto)


def _utc(texto):
    """Un timestamp como lo escribe Firestore, de vuelta a la hora de esta PC."""
    formato = "%Y-%m-%dT%H:%M:%S.%fZ" if "." in texto else "%Y-%m-%dT%H:%M:%SZ"
    return datetime.strptime(texto, formato).replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


class _AppDeGastosDePrueba:
    """Hace de Google: contesta el login anónimo, la renovación del token, el GET
    de config/socios y el PATCH de cada cierre, y anota todo lo que le piden."""

    def __init__(self):
        self.pedidos = []            # (metodo, url, cuerpo como texto, cabeceras)
        self.caida = False           # sin internet: ningún pedido llega
        self.rechazar_patch = []     # códigos con que contestar los próximos PATCH (se consumen)
        self.rechazar_get = None     # código con que contestar los GET
        self.renovacion_valida = True
        self.logins = 0
        self.socios = {"socios": ["Sergio"], "colaboradores": ["TOBY", "MATI"]}

    def __call__(self, metodo, url, datos, cabeceras):
        if self.caida:
            raise OSError("getaddrinfo failed")
        self.pedidos.append((metodo, url, datos.decode() if datos else None, cabeceras))
        if url == envio_pwa_repo.URL_LOGIN:
            self.logins += 1
            return 200, json.dumps({"idToken": f"token-{self.logins}", "refreshToken": f"renovacion-{self.logins}",
                                    "expiresIn": "3600", "localId": "anonimo"})
        if url == envio_pwa_repo.URL_RENOVAR:
            if not self.renovacion_valida:
                return 400, json.dumps({"error": {"message": "TOKEN_EXPIRED"}})
            return 200, json.dumps({"id_token": "token-renovado", "refresh_token": "renovacion-nueva",
                                    "expires_in": "3600"})
        if metodo == "GET" and url.endswith("/config/socios"):
            if self.rechazar_get:
                return self.rechazar_get, json.dumps({"error": {"message": "rechazado"}})
            return 200, json.dumps({"fields": {
                lista: {"arrayValue": {"values": [{"stringValue": nombre} for nombre in nombres]}}
                for lista, nombres in self.socios.items()
            }})
        if metodo == "PATCH":
            if self.rechazar_patch:
                codigo = self.rechazar_patch.pop(0)
                return codigo, json.dumps({"error": {"code": codigo, "message": "rechazado", "status": "X"}})
            return 200, json.dumps({"name": url.split("/documents/")[1]})
        return 404, "{}"

    def patches(self):
        return [pedido for pedido in self.pedidos if pedido[0] == "PATCH"]


class _BaseDeEnvios(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        envio_pwa_repo._olvidar_sesion()
        envio_pwa_repo._estado.update(ultimo_error=None, ultima_revision=None)
        envio_pwa_repo._hay_novedades.clear()
        self.admin_id = usuarios_repo.crear_usuario("Dueño", "1234", dominio.ROL_ADMIN)
        self.toby_id = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.gabriela_id = usuarios_repo.crear_usuario("Gabriela", "1234", dominio.ROL_EMPLEADA)
        articulos_repo.crear_articulo("COD1", "Turrón", None, None, 500.0, 300.0, 0)
        compras_repo.registrar_compra(self.admin_id, [{"codigo": "COD1", "cantidad": 100, "costo_unitario": 300.0}])
        self.app = _AppDeGastosDePrueba()

    def _vender(self, usuario_id, momento, monto=500.0, metodo=dominio.PAGO_EFECTIVO):
        with mock.patch("repositories.ventas_repo.datetime") as datetime_mock:
            datetime_mock.now.return_value = momento
            return ventas_repo.confirmar_venta(
                usuario_id,
                [{"codigo": "COD1", "descripcion": "Turrón", "cantidad": 1, "precio_unitario": monto}],
                [{"metodo": metodo, "monto": monto}],
            )

    def _turno_de_toby(self, dia=LUNES):
        """La caja de TOBY abierta a las 05:55, con $1.000 en efectivo y $600 digital."""
        relevo_repo.abrir_caja(self.toby_id, 50000.0, _a_las(5, 55, dia))
        self._vender(self.toby_id, _a_las(9, dia=dia), 1000.0)
        self._vender(self.toby_id, _a_las(10, dia=dia), 600.0, dominio.PAGO_DIGITAL)

    def _otro_turno_de_toby(self, desde, venta, cierre):
        """TOBY reabre su caja (sin contar) después de su propio cierre y vuelve a cerrar."""
        relevo_repo.abrir_caja(self.toby_id, None, desde)
        self._vender(self.toby_id, venta, 300.0)
        return turnos_repo.cerrar_turno(self.toby_id, ahora_dt=cierre)

    def _datos(self, cierre_id):
        with conexion_db() as conexion:
            return envio_pwa_repo.datos_del_cierre(conexion, cierre_id)

    def _fila(self, cierre_id):
        with conexion_db() as conexion:
            fila = conexion.execute("SELECT * FROM envios_pwa WHERE cierre_id = ?", (cierre_id,)).fetchone()
        return dict(fila) if fila else None

    def _configuracion(self, clave):
        with conexion_db() as conexion:
            fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (clave,)).fetchone()
        return fila["valor"] if fila else None


class TestElTurnoConElNombreDeAlla(unittest.TestCase):
    def test_de_lunes_a_sabado_son_los_tres_de_siempre(self):
        for turno, alla in ((dominio.TURNO_MANANA, "mañana"), (dominio.TURNO_TARDE, "tarde"),
                            (dominio.TURNO_NOCHE, "noche")):
            self.assertEqual(turnos.turno_para_la_app_de_gastos(LUNES, turno), alla)
            self.assertEqual(turnos.turno_para_la_app_de_gastos("2026-01-10", turno), alla)  # sábado

    def test_el_domingo_son_t1_y_t2(self):
        self.assertEqual(turnos.turno_para_la_app_de_gastos(DOMINGO, dominio.TURNO_MANANA), "t1")
        self.assertEqual(turnos.turno_para_la_app_de_gastos("2026-01-04", dominio.TURNO_NOCHE), "t2")


class TestLoQueViaja(_BaseDeEnvios):
    def test_el_cierre_de_la_empleada_va_a_su_nombre_con_el_total_y_el_reparto(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        datos = self._datos(cierre["id"])

        esperado = {
            "importe": 1600.0, "efectivo": 1000.0, "digital": 600.0, "turno": "mañana", "registradoPor": "TOBY",
            "fecha": LUNES, "creadoEn": _a_las(14, 0), "origen": "cybercontrol", "cierreId": cierre["id"],
            "caja": cierre["caja_numero"], "forzoso": False, "enAusencia": False, "cerradoPor": "TOBY",
        }
        self.assertEqual({clave: datos[clave] for clave in esperado}, esperado)

    def test_viaja_el_desglose_por_negocio_como_en_la_tarjeta(self):
        from ui.tarjeta_cierre import NEGOCIOS
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        detalle = self._datos(cierre["id"])["detalle"]

        self.assertEqual((detalle["cambioFijo"], detalle["aRetirar"]), (50000.0, 1000.0))
        self.assertEqual([(n["clave"], n["nombre"]) for n in detalle["negocios"]],
                         [(clave, nombre) for clave, _dibujito, nombre in NEGOCIOS])
        por_clave = {n["clave"]: (n["efectivo"], n["digital"]) for n in detalle["negocios"]}
        self.assertEqual(por_clave["kiosko_solo"], (1000.0, 600.0))
        self.assertEqual({clave: montos for clave, montos in por_clave.items() if clave != "kiosko_solo"},
                         {clave: (0.0, 0.0) for clave in por_clave if clave != "kiosko_solo"})
        self.assertEqual(detalle["reservasPorTipo"], [])
        self.assertEqual(datetime.fromisoformat(detalle["hasta"]), _a_las(14, 0))

    def test_el_desglose_viaja_como_mapa_de_firestore(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        campos = envio_pwa_repo.a_campos_firestore(self._datos(cierre["id"]))["fields"]

        detalle = campos["detalle"]["mapValue"]["fields"]
        self.assertEqual(detalle["cambioFijo"], {"integerValue": "50000"})
        kiosko = detalle["negocios"]["arrayValue"]["values"][0]["mapValue"]["fields"]
        self.assertEqual((kiosko["nombre"], kiosko["efectivo"], kiosko["digital"]),
                         ({"stringValue": "Kiosko"}, {"integerValue": "1000"}, {"integerValue": "600"}))
        self.assertEqual(detalle["reservasPorTipo"], {"arrayValue": {"values": []}})
        self.assertEqual(campos["enAusencia"], {"booleanValue": False})
        # json.dumps lo tiene que poder escribir entero (es lo que viaja).
        json.dumps(campos)

    def test_si_el_admin_cierra_en_ausencia_alla_figura_la_responsable(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.admin_id, ahora_dt=_a_las(14, 5))

        datos = self._datos(cierre["id"])

        self.assertEqual((datos["registradoPor"], datos["cerradoPor"], datos["forzoso"], datos["enAusencia"]),
                         ("TOBY", "Dueño", False, True))

    def test_el_cierre_forzoso_va_marcado_y_a_nombre_de_la_responsable(self):
        self._turno_de_toby()
        cierre = relevo_repo.cierre_forzoso_si_corresponde(_a_las(14, 31))

        datos = self._datos(cierre["id"])

        self.assertEqual((datos["registradoPor"], datos["forzoso"], datos["importe"]), ("TOBY", True, 1600.0))

    def test_sin_caja_va_a_nombre_de_quien_cerro(self):
        self._vender(self.admin_id, _a_las(9), 700.0)
        cierre = turnos_repo.cerrar_turno(self.admin_id, ahora_dt=_a_las(14, 0))

        datos = self._datos(cierre["id"])

        self.assertEqual((datos["registradoPor"], datos["caja"], datos["importe"]), ("Dueño", None, 700.0))

    def test_viaja_quien_abrio_la_caja_y_a_que_hora(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        datos = self._datos(cierre["id"])
        campos = envio_pwa_repo.a_campos_firestore(datos)["fields"]

        self.assertEqual((datos["abiertaPor"], datos["abiertaEn"]), ("TOBY", _a_las(5, 55)))
        self.assertEqual(campos["abiertaPor"], {"stringValue": "TOBY"})
        self.assertEqual(_utc(campos["abiertaEn"]["timestampValue"]), _a_las(5, 55))

    def test_en_ausencia_viaja_quien_abrio_no_quien_cerro(self):
        self._turno_de_toby()
        relevo_repo.cierre_forzoso_si_corresponde(_a_las(14, 31))
        relevo_repo.abrir_caja(self.gabriela_id, 50000.0, _a_las(14, 40))
        cierre = relevo_repo.cerrar_para_entrar(self.toby_id, relevo_repo.SITUACION_CERRAR_LA_DE_OTRA, _a_las(22, 10))

        datos = self._datos(cierre["id"])

        self.assertEqual((datos["abiertaPor"], datos["abiertaEn"], datos["cerradoPor"]),
                         ("Gabriela", _a_las(14, 40), "TOBY"))

    def test_sin_caja_no_viaja_quien_la_abrio(self):
        self._vender(self.admin_id, _a_las(9), 700.0)
        cierre = turnos_repo.cerrar_turno(self.admin_id, ahora_dt=_a_las(14, 0))

        datos = self._datos(cierre["id"])
        campos = envio_pwa_repo.a_campos_firestore(datos)["fields"]

        self.assertEqual((datos["abiertaPor"], datos["abiertaEn"]), (None, None))
        self.assertNotIn("abiertaPor", campos)
        self.assertNotIn("abiertaEn", campos)

    def test_el_domingo_va_como_t1(self):
        self._turno_de_toby(DOMINGO)
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(18, 0, DOMINGO))

        self.assertEqual((self._datos(cierre["id"])["turno"], cierre["turno_label"]), ("t1", "Domingo T1"))

    def test_los_campos_llevan_los_tipos_de_firestore(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        campos = envio_pwa_repo.a_campos_firestore(self._datos(cierre["id"]))["fields"]

        self.assertEqual(campos["importe"], {"integerValue": "1600"})
        self.assertEqual(campos["efectivo"], {"integerValue": "1000"})
        self.assertEqual(campos["negocio"], {"stringValue": "cyberbios"})
        self.assertEqual(campos["turno"], {"stringValue": "mañana"})
        self.assertEqual(campos["registradoPor"], {"stringValue": "TOBY"})
        self.assertEqual(campos["origen"], {"stringValue": "cybercontrol"})
        self.assertEqual(campos["forzoso"], {"booleanValue": False})
        self.assertEqual(campos["caja"], {"integerValue": str(cierre["caja_numero"])})
        self.assertEqual(campos["cierreId"], {"integerValue": str(cierre["id"])})
        # La fecha es ese día a las 12:00 de esta PC (como la guarda la app desde el
        # celular) y creadoEn la hora real del cierre, las dos escritas en UTC.
        self.assertEqual(_utc(campos["fecha"]["timestampValue"]), _a_las(12, 0))
        self.assertEqual(_utc(campos["creadoEn"]["timestampValue"]), _a_las(14, 0))

    def test_sin_caja_no_viaja_el_numero_de_caja(self):
        self._vender(self.admin_id, _a_las(9), 700.0)
        cierre = turnos_repo.cerrar_turno(self.admin_id, ahora_dt=_a_las(14, 0))

        self.assertNotIn("caja", envio_pwa_repo.a_campos_firestore(self._datos(cierre["id"]))["fields"])

    def test_un_monto_con_centavos_va_como_decimal(self):
        self.assertEqual(envio_pwa_repo._numero(1234.5), {"doubleValue": 1234.5})
        self.assertEqual(envio_pwa_repo._numero(1500.0), {"integerValue": "1500"})
        self.assertEqual(envio_pwa_repo._numero(0), {"integerValue": "0"})


class TestLaCola(_BaseDeEnvios):
    def test_apagado_el_cierre_no_queda_en_la_cola(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        self.assertFalse(envio_pwa_repo.esta_activado())
        self.assertIsNone(self._fila(cierre["id"]))

    def test_prendido_el_cierre_queda_pendiente_con_su_documento_fijo(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        fila = self._fila(cierre["id"])

        self.assertEqual((fila["estado"], fila["intentos"], fila["documento_id"]),
                         (dominio.ENVIO_PENDIENTE, 0, f"cybercontrol-{cierre['id']}-2026-01-05"))

    def test_el_forzoso_y_el_de_en_ausencia_tambien_quedan_en_la_cola(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        forzoso = relevo_repo.cierre_forzoso_si_corresponde(_a_las(14, 31))
        relevo_repo.abrir_caja(self.gabriela_id, 50000.0, _a_las(14, 40))
        en_ausencia = relevo_repo.cerrar_para_entrar(self.toby_id, relevo_repo.SITUACION_CERRAR_LA_DE_OTRA,
                                                      _a_las(22, 10))

        self.assertEqual(self._fila(forzoso["id"])["estado"], dominio.ENVIO_PENDIENTE)
        self.assertEqual(self._fila(en_ausencia["id"])["estado"], dominio.ENVIO_PENDIENTE)
        self.assertEqual(self._datos(en_ausencia["id"])["registradoPor"], "Gabriela")

    def test_solo_el_admin_lo_prende(self):
        with self.assertRaises(PermissionError):
            envio_pwa_repo.activar(self.toby_id, True)
        self.assertFalse(envio_pwa_repo.esta_activado())

    def test_el_cierre_despierta_al_hilo_solo_si_esta_prendido(self):
        self._turno_de_toby()
        turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.assertFalse(envio_pwa_repo._hay_novedades.is_set())

        envio_pwa_repo.activar(self.admin_id, True)
        self._otro_turno_de_toby(_a_las(14, 1), _a_las(15), _a_las(22, 0))
        self.assertTrue(envio_pwa_repo._hay_novedades.is_set())

    def test_al_cerrar_la_caja_se_manda_en_ese_momento_sin_esperar_la_revision(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        detener = threading.Event()
        # El hilo de verdad, con la app de mentira y una revisión lejísimos: si el
        # cierre llega a la app, fue porque lo despertó el cierre.
        with mock.patch.object(envio_pwa_repo, "_transporte_http", self.app), \
                mock.patch.object(envio_pwa_repo, "SEGUNDOS_ENTRE_REVISIONES", 600):
            hilo = threading.Thread(target=envio_pwa_repo._revisar_siempre, args=(detener,), daemon=True)
            hilo.start()
            try:
                cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
                limite = time.monotonic() + 5
                while time.monotonic() < limite and self._fila(cierre["id"])["estado"] != dominio.ENVIO_ENVIADO:
                    time.sleep(0.05)
            finally:
                detener.set()
                envio_pwa_repo._hay_novedades.set()
                hilo.join(timeout=5)
        self.assertFalse(hilo.is_alive())
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertEqual(len(self.app.patches()), 1)

    def test_lo_de_antes_de_prenderlo_no_se_manda(self):
        self._turno_de_toby()
        anterior = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        envio_pwa_repo.activar(self.admin_id, True)
        nuevo = self._otro_turno_de_toby(_a_las(14, 1), _a_las(15), _a_las(22, 0))

        envio_pwa_repo.enviar_pendientes(_a_las(22, 1), transporte=self.app)

        self.assertIsNone(self._fila(anterior["id"]))
        self.assertEqual(self._fila(nuevo["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertEqual(len(self.app.patches()), 1)

    def test_se_manda_una_vez_con_el_token_y_al_documento_fijo(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        ahora = _a_las(14, 1)

        resultado = envio_pwa_repo.enviar_pendientes(ahora, transporte=self.app)
        de_nuevo = envio_pwa_repo.enviar_pendientes(ahora + timedelta(minutes=5), transporte=self.app)

        self.assertEqual((resultado, de_nuevo), ({"enviados": 1, "con_error": 0}, {"enviados": 0, "con_error": 0}))
        self.assertEqual(len(self.app.patches()), 1)
        _, url, cuerpo, cabeceras = self.app.patches()[0]
        self.assertEqual(url, f"{envio_pwa_repo.URL_FIRESTORE}/facturacion/cybercontrol-{cierre['id']}-2026-01-05")
        self.assertEqual(cabeceras["Authorization"], "Bearer token-1")
        self.assertEqual(json.loads(cuerpo)["fields"]["registradoPor"], {"stringValue": "TOBY"})
        fila = self._fila(cierre["id"])
        self.assertEqual((fila["estado"], fila["enviado_en"], fila["intentos"], fila["ultimo_error"]),
                         (dominio.ENVIO_ENVIADO, ahora.isoformat(), 1, None))
        self.assertEqual(envio_pwa_repo.estado()["ultimo_enviado"], ahora.isoformat())

    def test_el_login_anonimo_se_hace_una_vez_y_se_conserva(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self._otro_turno_de_toby(_a_las(14, 1), _a_las(15), _a_las(22, 0))

        envio_pwa_repo.enviar_pendientes(_a_las(22, 1), transporte=self.app)

        self.assertEqual((self.app.logins, len(self.app.patches())), (1, 2))
        self.assertEqual(self._configuracion("envio_pwa_renovacion"), "renovacion-1")

        # Se reabre el programa (el token en memoria se pierde): se renueva con lo
        # guardado, sin crear otro usuario anónimo allá.
        envio_pwa_repo._olvidar_sesion()
        self._otro_turno_de_toby(_a_las(22, 1), _a_las(23), _a_las(6, 0, MARTES))
        envio_pwa_repo.enviar_pendientes(_a_las(6, 1, MARTES), transporte=self.app)

        self.assertEqual((self.app.logins, len(self.app.patches())), (1, 3))
        self.assertEqual(self.app.patches()[-1][3]["Authorization"], "Bearer token-renovado")
        self.assertEqual(self._configuracion("envio_pwa_renovacion"), "renovacion-nueva")

    def test_si_google_no_acepta_la_renovacion_entra_de_nuevo(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        envio_pwa_repo._guardar_sesion("viejo", 0, "renovacion-borrada")
        self.app.renovacion_valida = False

        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)

        self.assertEqual(self.app.logins, 1)
        self.assertEqual(self.app.patches()[-1][3]["Authorization"], "Bearer token-1")

    def test_con_el_token_vencido_entra_de_nuevo_y_lo_manda_igual(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.app.rechazar_patch = [401]

        resultado = envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)

        self.assertEqual(resultado, {"enviados": 1, "con_error": 0})
        self.assertEqual([pedido[3]["Authorization"] for pedido in self.app.patches()],
                         ["Bearer token-1", "Bearer token-renovado"])
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)

    def test_sin_internet_queda_con_error_y_se_vuelve_a_probar_solo(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.app.caida = True
        ahora = _a_las(14, 1)

        resultado = envio_pwa_repo.enviar_pendientes(ahora, transporte=self.app)

        fila = self._fila(cierre["id"])
        self.assertEqual(resultado, {"enviados": 0, "con_error": 1})
        self.assertEqual((fila["estado"], fila["intentos"], fila["proximo_intento"]),
                         (dominio.ENVIO_ERROR, 1, (ahora + timedelta(minutes=1)).isoformat()))
        self.assertIn("Sin internet", fila["ultimo_error"])
        self.assertIn("Sin internet", envio_pwa_repo.estado()["ultimo_error"])

        # Antes de que le toque no se prueba; después sí, y ya volvió la conexión.
        self.assertEqual(
            envio_pwa_repo.enviar_pendientes(ahora + timedelta(seconds=30), transporte=self.app),
            {"enviados": 0, "con_error": 0},
        )
        self.app.caida = False
        self.assertEqual(
            envio_pwa_repo.enviar_pendientes(ahora + timedelta(minutes=1), transporte=self.app)["enviados"], 1
        )
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertIsNone(envio_pwa_repo.estado()["ultimo_error"])

    def test_sin_internet_no_se_prueban_los_demas_hasta_la_proxima_revision(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        primero = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        segundo = self._otro_turno_de_toby(_a_las(14, 1), _a_las(15), _a_las(22, 0))
        self.app.caida = True

        envio_pwa_repo.enviar_pendientes(_a_las(22, 1), transporte=self.app)

        self.assertEqual(self._fila(primero["id"])["estado"], dominio.ENVIO_ERROR)
        self.assertEqual((self._fila(segundo["id"])["estado"], self._fila(segundo["id"])["intentos"]),
                         (dominio.ENVIO_PENDIENTE, 0))

    def test_la_espera_crece_con_cada_fallo_hasta_una_hora(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        ahora = _a_las(14, 1)
        self.app.rechazar_patch = [500, 500, 500]

        envio_pwa_repo.enviar_pendientes(ahora, transporte=self.app)
        envio_pwa_repo.enviar_pendientes(ahora + timedelta(minutes=1), transporte=self.app)

        fila = self._fila(cierre["id"])
        self.assertEqual((fila["intentos"], fila["proximo_intento"]), (2, (ahora + timedelta(minutes=3)).isoformat()))
        self.assertIn("Google contestó con un error (500)", fila["ultimo_error"])
        with conexion_db() as conexion:
            conexion.execute("UPDATE envios_pwa SET intentos = 200, proximo_intento = NULL")
        envio_pwa_repo.enviar_pendientes(ahora + timedelta(minutes=10), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["proximo_intento"], (ahora + timedelta(minutes=70)).isoformat())

    def test_permiso_denegado_queda_explicado(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.app.rechazar_patch = [403, 403]

        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)

        fila = self._fila(cierre["id"])
        self.assertEqual(fila["estado"], dominio.ENVIO_ERROR)
        self.assertIn("permiso denegado", fila["ultimo_error"])
        self.assertEqual(len(self.app.patches()), 2)  # entró de nuevo y probó una vez más

    def test_apagado_lo_pendiente_espera_y_al_prender_se_manda(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        envio_pwa_repo.activar(self.admin_id, False)

        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        self.assertEqual((self._fila(cierre["id"])["estado"], self.app.pedidos), (dominio.ENVIO_PENDIENTE, []))

        envio_pwa_repo.activar(self.admin_id, True)
        envio_pwa_repo.enviar_pendientes(_a_las(14, 2), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)

    def test_reintentar_ahora_no_espera_el_turno_del_que_fallo_ni_repite_los_enviados(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.app.rechazar_patch = [500]
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ERROR)

        resultado = envio_pwa_repo.reintentar_ahora(transporte=self.app)

        self.assertEqual((resultado["enviados"], self._fila(cierre["id"])["estado"]), (1, dominio.ENVIO_ENVIADO))
        self.assertEqual(envio_pwa_repo.reintentar_ahora(transporte=self.app), {"enviados": 0, "con_error": 0})
        self.assertEqual(len(self.app.patches()), 2)

    def test_un_error_inesperado_en_un_cierre_no_frena_a_los_demas(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        roto = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        sano = self._otro_turno_de_toby(_a_las(14, 1), _a_las(15), _a_las(22, 0))
        original = envio_pwa_repo.datos_del_cierre

        def datos_o_un_dato_roto(conexion, cierre_id):
            if cierre_id == roto["id"]:
                raise RuntimeError("dato roto")
            return original(conexion, cierre_id)

        with mock.patch.object(envio_pwa_repo, "datos_del_cierre", datos_o_un_dato_roto):
            resultado = envio_pwa_repo.enviar_pendientes(_a_las(22, 1), transporte=self.app)

        self.assertEqual(resultado, {"enviados": 1, "con_error": 1})
        self.assertEqual(self._fila(sano["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertIn("Error inesperado", self._fila(roto["id"])["ultimo_error"])


class TestProbarLaConexion(_BaseDeEnvios):
    def test_entra_trae_los_nombres_y_dice_cuales_faltan_sin_escribir_nada(self):
        resultado = envio_pwa_repo.probar_conexion(transporte=self.app)

        self.assertEqual(resultado["nombres_app"], ["Sergio", "TOBY", "MATI"])
        # "Administrador" es el usuario que siembra la base; TOBY está escrito igual allá.
        self.assertEqual(resultado["faltan"], ["Administrador", "Dueño", "Gabriela"])
        self.assertEqual([metodo for metodo, *_ in self.app.pedidos], ["POST", "GET"])

    def test_sin_internet_avisa(self):
        self.app.caida = True
        with self.assertRaises(ValueError) as contexto:
            envio_pwa_repo.probar_conexion(transporte=self.app)
        self.assertIn("Sin internet", str(contexto.exception))

    def test_permiso_denegado_avisa(self):
        self.app.rechazar_get = 403
        with self.assertRaises(ValueError) as contexto:
            envio_pwa_repo.probar_conexion(transporte=self.app)
        self.assertIn("permiso denegado", str(contexto.exception))

    def test_una_respuesta_que_no_es_de_google_avisa(self):
        # Una red con portal de ingreso contesta HTML con código 200.
        with self.assertRaises(ValueError) as contexto:
            envio_pwa_repo._json("<html>portal</html>")
        self.assertIn("no se entiende", str(contexto.exception))


class TestEstado(_BaseDeEnvios):
    def test_cuenta_y_lista_los_ultimos_con_turno_responsable_y_total(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        turnos_repo.cerrar_turno(self.admin_id, ahora_dt=_a_las(14, 5))  # en ausencia

        estado = envio_pwa_repo.estado()

        self.assertEqual((estado["activado"], estado["pendientes"], estado["enviados"], estado["con_error"]),
                         (True, 1, 0, 0))
        ultimo = estado["ultimos"][0]
        self.assertEqual(
            (ultimo["turno_label"], ultimo["fecha"], ultimo["responsable"], ultimo["total"], ultimo["estado"]),
            ("Mañana", "2026-01-05", "TOBY", 1600.0, dominio.ENVIO_PENDIENTE),
        )


class TestPantalla(_BaseDeEnvios):
    def _usuario(self, usuario_id):
        return dict(usuarios_repo.obtener_usuario(usuario_id))

    def _tecla(self, ventana, texto):
        return next(boton for boton in ventana.findChildren(QPushButton) if boton.text() == texto)

    def _tarjeta(self, ventana):
        return [boton for boton in ventana.findChildren(QPushButton) if boton.accessibleName() == TARJETA]

    def test_prende_y_apaga_desde_la_pantalla(self):
        ventana = DialogoEnvioPwa(self._usuario(self.admin_id))
        self.addCleanup(ventana.deleteLater)
        self.assertEqual(ventana.pastilla.text(), "APAGADO")

        with mock.patch("ui.envio_pwa_dialogo.mostrar_info") as aviso:
            self._tecla(ventana, "PRENDER").click()

        aviso.assert_called_once()
        self.assertTrue(envio_pwa_repo.esta_activado())
        self.assertEqual((ventana.pastilla.text(), ventana.tecla_interruptor.text()), ("PRENDIDO", "APAGAR"))
        self._tecla(ventana, "APAGAR").click()
        self.assertFalse(envio_pwa_repo.esta_activado())
        self.assertEqual(ventana.pastilla.text(), "APAGADO")

    def test_un_operador_no_puede_prenderlo(self):
        ventana = DialogoEnvioPwa(self._usuario(self.toby_id))
        self.addCleanup(ventana.deleteLater)

        with mock.patch("ui.utils.mostrar_error") as error:
            self._tecla(ventana, "PRENDER").click()

        error.assert_called_once()
        self.assertFalse(envio_pwa_repo.esta_activado())

    def test_muestra_los_envios_y_el_error(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.app.caida = True
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)

        ventana = DialogoEnvioPwa(self._usuario(self.admin_id))
        self.addCleanup(ventana.deleteLater)

        self.assertEqual(ventana.tabla.rowCount(), 1)
        self.assertEqual([ventana.tabla.item(0, columna).text() for columna in range(4)],
                         ["Mañana 05/01/2026", "TOBY", formato_pesos(1600.0), "Con error"])
        self.assertIn("Sin internet", ventana.tabla.item(0, 4).text())
        self.assertIn("Sin internet", ventana.etiqueta_error.text())

    def test_probar_la_conexion_dice_que_nombres_faltan(self):
        ventana = DialogoEnvioPwa(self._usuario(self.admin_id))
        self.addCleanup(ventana.deleteLater)

        with mock.patch.object(envio_pwa_repo, "_transporte_http", self.app), \
                mock.patch("ui.envio_pwa_dialogo.mostrar_info") as aviso:
            self._tecla(ventana, "PROBAR LA CONEXIÓN").click()

        titulo, mensaje = aviso.call_args[0][1], aviso.call_args[0][2]
        self.assertEqual(titulo, "Conexión OK, pero faltan nombres")
        self.assertIn("Gabriela", mensaje)
        self.assertEqual(self.app.patches(), [])

    def test_reintentar_ahora_manda_lo_que_fallo(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.app.rechazar_patch = [500]
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        ventana = DialogoEnvioPwa(self._usuario(self.admin_id))
        self.addCleanup(ventana.deleteLater)

        with mock.patch.object(envio_pwa_repo, "_transporte_http", self.app), \
                mock.patch("ui.envio_pwa_dialogo.mostrar_info") as aviso:
            self._tecla(ventana, "REINTENTAR AHORA").click()

        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertEqual(ventana.tabla.item(0, 3).text(), "Enviado")
        self.assertIn("Enviados: 1", aviso.call_args[0][2])

    def test_la_tarjeta_esta_en_configuracion_admin_solo_en_el_mostrador(self):
        admin = self._usuario(self.admin_id)
        ventana = ConfiguracionAdminWindow(admin)
        self.addCleanup(ventana.deleteLater)
        tarjeta = self._tarjeta(ventana)[0]
        self.assertTrue(tarjeta.isEnabled())
        with mock.patch("ui.configuracion_admin_window.DialogoEnvioPwa") as dialogo:
            tarjeta.click()
        dialogo.assert_called_once()

        operador = ConfiguracionAdminWindow(self._usuario(self.toby_id))
        self.addCleanup(operador.deleteLater)
        self.assertFalse(self._tarjeta(operador)[0].isEnabled())

        with mock.patch("ui.configuracion_admin_window.modo_remoto.es_copia_remota", return_value=True):
            remota = ConfiguracionAdminWindow(admin)
        self.addCleanup(remota.deleteLater)
        self.assertEqual(self._tarjeta(remota), [])


class TestBarraDeEnvio(_BaseDeEnvios):
    """La barra "ENVIANDO CIERRE DE TURNO" (pedido del dueño, 2026-10-26): dura 3 s
    como mínimo, se llena del todo recién cuando la app confirmó, y si no se pudo
    lo dice y aclara que se manda solo después."""

    def _cierre_en_cola(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        return turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

    def _barra(self, cierre_id):
        """La barra con un reloj de mentira que arranca en 0: (barra, momento); se
        avanza escribiendo momento[0] y llamando a barra._tic()."""
        momento = [0.0]
        barra = DialogoEnviandoCierre(cierre_id, reloj=lambda: momento[0])
        self.addCleanup(barra.deleteLater)
        barra._timer.stop()  # en la prueba el tiempo se maneja a mano
        return barra, momento

    def test_dura_3_segundos_aunque_el_envio_sea_instantaneo(self):
        cierre = self._cierre_en_cola()
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)  # ya enviado
        barra, momento = self._barra(cierre["id"])

        for momento[0] in (0.5, 1.5, 2.9):
            barra._tic()
            self.assertEqual(barra.titulo.text(), "ENVIANDO CIERRE DE TURNO")
            self.assertLess(barra.barra.value(), TOPE_SIN_CONFIRMAR)
            self.assertIsNone(barra.terminado)
            self.assertFalse(barra.tecla_continuar.isVisibleTo(barra))
        momento[0] = 3.0
        barra._tic()

        self.assertEqual((barra.barra.value(), barra.terminado), (100, ENVIADO))
        self.assertIn("CIERRE ENVIADO", barra.titulo.text())
        self.assertTrue(barra.tecla_continuar.isVisibleTo(barra))
        self.assertTrue(barra._cerrarse.isActive())  # se va sola enseguida

    def test_si_la_app_tarda_la_barra_espera_sin_llenarse(self):
        cierre = self._cierre_en_cola()  # queda PENDIENTE: nadie lo manda todavía
        barra, momento = self._barra(cierre["id"])

        momento[0] = 3.5
        barra._tic()
        self.assertEqual((barra.barra.value(), barra.terminado), (TOPE_SIN_CONFIRMAR, None))

        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        momento[0] = 5.0
        barra._tic()
        self.assertEqual(barra.terminado, ENVIADO)

    def test_sin_internet_lo_dice_en_rojo_y_aclara_que_se_manda_solo(self):
        cierre = self._cierre_en_cola()
        self.app.caida = True
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        barra, momento = self._barra(cierre["id"])

        momento[0] = 3.0
        barra._tic()

        self.assertEqual((barra.terminado, barra.barra.value()), (ERROR, TOPE_SIN_CONFIRMAR))
        self.assertEqual(barra.titulo.property("estado"), ERROR)
        self.assertIn("Sin internet", barra.detalle.text())
        self.assertIn("Se vuelve a intentar solo", barra.detalle.text())
        self.assertTrue(barra.tecla_continuar.isVisibleTo(barra))
        self.assertFalse(barra._cerrarse.isActive())  # que se lea: no se va sola

    def test_pasado_el_maximo_deja_de_esperar(self):
        cierre = self._cierre_en_cola()
        barra, momento = self._barra(cierre["id"])

        momento[0] = SEGUNDOS_MAXIMOS + 1
        barra._tic()

        self.assertEqual(barra.terminado, PENDIENTE)
        self.assertIn("se manda solo", barra.detalle.text().lower())

    def test_el_cierre_de_turno_no_abre_la_barra_con_el_envio_apagado(self):
        self._turno_de_toby()
        ventana = CierreTurnoWindow(dict(usuarios_repo.obtener_usuario(self.toby_id)))
        self.addCleanup(ventana.deleteLater)

        with mock.patch("ui.caja_window.confirmar", return_value=True), \
                mock.patch("ui.caja_window.mostrar_info"), \
                mock.patch("ui.caja_window.DialogoEnviandoCierre") as barra:
            ventana._cerrar_turno()

        barra.assert_not_called()
        self.assertTrue(ventana.turno_cerrado)

    def test_el_cierre_de_turno_abre_la_barra_con_el_envio_prendido(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        ventana = CierreTurnoWindow(dict(usuarios_repo.obtener_usuario(self.toby_id)))
        self.addCleanup(ventana.deleteLater)

        with mock.patch("ui.caja_window.confirmar", return_value=True), \
                mock.patch("ui.caja_window.mostrar_info") as aviso, \
                mock.patch("ui.caja_window.DialogoEnviandoCierre") as barra:
            ventana._cerrar_turno()

        barra.assert_called_once()
        barra.return_value.exec.assert_called_once()
        aviso.assert_called_once()  # el aviso de "Turno cerrado" sigue después de la barra
        with conexion_db() as conexion:
            cierre_id = conexion.execute("SELECT MAX(id) AS id FROM cierres_turno").fetchone()["id"]
        self.assertEqual(barra.call_args.args[0], cierre_id)


class TestMandarCierreAMano(_BaseDeEnvios):
    """El botón "Mandar a la app de gastos" de Control de Cierres (pedido del dueño,
    2026-10-26): un cierre hecho con el envío apagado, o borrado por error allá, se
    manda a pedido; al mismo documento, así no se duplica."""

    def _url(self, cierre):
        return f"{envio_pwa_repo.URL_FIRESTORE}/facturacion/cybercontrol-{cierre['id']}-2026-01-05"

    def test_un_cierre_hecho_con_el_envio_apagado_se_manda_a_pedido(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.assertIsNone(self._fila(cierre["id"]))
        envio_pwa_repo.activar(self.admin_id, True)

        resultado = envio_pwa_repo.mandar_cierre(self.admin_id, cierre["id"])

        self.assertEqual(resultado["activado"], True)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_PENDIENTE)
        self.assertTrue(envio_pwa_repo._hay_novedades.is_set())  # el hilo lo manda ya
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertEqual([pedido[1] for pedido in self.app.patches()], [self._url(cierre)])

    def test_uno_ya_enviado_se_vuelve_a_mandar_al_mismo_documento(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)

        envio_pwa_repo.mandar_cierre(self.admin_id, cierre["id"])

        fila = self._fila(cierre["id"])
        self.assertEqual((fila["estado"], fila["intentos"], fila["enviado_en"], fila["ultimo_error"]),
                         (dominio.ENVIO_PENDIENTE, 0, None, None))
        envio_pwa_repo.enviar_pendientes(_a_las(14, 2), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)
        self.assertEqual([pedido[1] for pedido in self.app.patches()], [self._url(cierre)] * 2)

    def test_con_el_envio_apagado_queda_en_la_cola_hasta_prenderlo(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        resultado = envio_pwa_repo.mandar_cierre(self.admin_id, cierre["id"])

        self.assertEqual(resultado["activado"], False)
        self.assertFalse(envio_pwa_repo._hay_novedades.is_set())
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_PENDIENTE)
        envio_pwa_repo.enviar_pendientes(_a_las(14, 1), transporte=self.app)
        self.assertEqual(self.app.patches(), [])
        envio_pwa_repo.activar(self.admin_id, True)
        envio_pwa_repo.enviar_pendientes(_a_las(14, 2), transporte=self.app)
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_ENVIADO)

    def test_solo_el_admin_y_solo_un_cierre_que_existe(self):
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))

        with self.assertRaises(PermissionError):
            envio_pwa_repo.mandar_cierre(self.toby_id, cierre["id"])
        with self.assertRaises(ValueError):
            envio_pwa_repo.mandar_cierre(self.admin_id, 9999)
        self.assertIsNone(self._fila(cierre["id"]))

    def _control_de_cierres(self, usuario_id):
        ventana = ControlCierresWindow(dict(usuarios_repo.obtener_usuario(usuario_id)))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def test_el_boton_lo_ve_solo_el_admin_y_en_el_mostrador_abre_la_barra(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        self.assertFalse(self._control_de_cierres(self.toby_id).boton_mandar.isVisibleTo(
            self._control_de_cierres(self.toby_id)))
        ventana = self._control_de_cierres(self.admin_id)
        self.assertTrue(ventana.boton_mandar.isVisibleTo(ventana))
        ventana.tabla.selectRow(0)

        with mock.patch("ui.control_cierres_window.confirmar", return_value=True), \
                mock.patch("ui.control_cierres_window.DialogoEnviandoCierre") as barra:
            ventana.boton_mandar.click()

        barra.assert_called_once()
        self.assertEqual(barra.call_args.args[0], cierre["id"])
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_PENDIENTE)

    def test_desde_otra_pc_avisa_que_lo_manda_el_mostrador_y_no_abre_la_barra(self):
        envio_pwa_repo.activar(self.admin_id, True)
        self._turno_de_toby()
        cierre = turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        ventana = self._control_de_cierres(self.admin_id)
        ventana.tabla.selectRow(0)

        with mock.patch("ui.control_cierres_window.confirmar", return_value=True), \
                mock.patch("ui.control_cierres_window.modo_remoto.es_copia_remota", return_value=True), \
                mock.patch("ui.control_cierres_window.mostrar_info") as aviso, \
                mock.patch("ui.control_cierres_window.DialogoEnviandoCierre") as barra:
            ventana.boton_mandar.click()

        barra.assert_not_called()
        self.assertIn("mostrador", aviso.call_args.args[2])
        self.assertEqual(self._fila(cierre["id"])["estado"], dominio.ENVIO_PENDIENTE)

    def test_sin_elegir_un_cierre_avisa(self):
        self._turno_de_toby()
        turnos_repo.cerrar_turno(self.toby_id, ahora_dt=_a_las(14, 0))
        ventana = self._control_de_cierres(self.admin_id)
        ventana.tabla.clearSelection()
        ventana.tabla.setCurrentCell(-1, -1)

        with mock.patch("ui.control_cierres_window.mostrar_error") as error, \
                mock.patch("ui.control_cierres_window.DialogoEnviandoCierre") as barra:
            ventana.boton_mandar.click()

        error.assert_called_once()
        barra.assert_not_called()


if __name__ == "__main__":
    unittest.main()
