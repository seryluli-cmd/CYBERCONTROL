"""
tests/test_fondo_pantalla.py
==============================
Los fondos de las PCs cliente (el de la pantalla de bloqueo y el wallpaper de
Windows), de punta a punta:

- `fondo_repo`: dónde se guarda, la versión, lo que rechaza, que nunca deja un
  fondo cortado y que los dos fondos no se pisan.
- `servidor_red.py`: `GET /fondo`, `GET /escritorio` y las versiones que viajan en
  `GET /estado` (con el servidor real, como los demás tests de la capa HTTP).
- `pcs_fondo_dialogo.preparar_jpeg`: lo que se le hace a la imagen que elige el
  Admin antes de guardarla (con Qt "offscreen", sin abrir ventanas).
- La ventana "Fondos de las PCs" (maqueta B) y su tarjeta en Gestionar Estaciones.

Se ejecutan con:

    python -m unittest discover tests
"""

import http.client
import os
import tempfile
import unittest
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor, QImage  # noqa: E402
from PySide6.QtWidgets import QApplication, QPushButton  # noqa: E402

import database  # noqa: E402
import dominio  # noqa: E402
import servidor_red  # noqa: E402
import test_control_pcs  # noqa: E402  (solo para reusar el servidor real de _ConServidorRed)
from base import BaseConBaseTemporal  # noqa: E402
from control_pcs.repositories import fondo_repo, pcs_repo  # noqa: E402
from control_pcs.ui import pcs_fondo_dialogo, pcs_gestion_dialogos  # noqa: E402

_app = QApplication.instance() or QApplication([])

# Un JPEG "de mentira": al repositorio solo le importa que empiece como uno.
FIRMA_JPEG = bytes([0xFF, 0xD8, 0xFF, 0xE0])
FIN_JPEG = bytes([0xFF, 0xD9])


def jpeg_falso(relleno=b"contenido de prueba", veces=50):
    return FIRMA_JPEG + relleno * veces + FIN_JPEG


class _ConFondoLimpio(BaseConBaseTemporal):
    """Cada test arranca sin fondo y sin nada recordado de otro test."""

    def setUp(self):
        super().setUp()
        fondo_repo._olvidar()
        self.addCleanup(fondo_repo._olvidar)


class TestFondoRepo(_ConFondoLimpio):
    def test_sin_fondo_todavia_no_hay_nada(self):
        self.assertIsNone(fondo_repo.obtener())
        self.assertEqual(fondo_repo.version_actual(), "")
        self.assertFalse(fondo_repo.quitar())

    def test_guardar_deja_el_jpeg_en_data_y_devuelve_su_version(self):
        datos = jpeg_falso()

        version = fondo_repo.guardar_jpeg(datos)

        self.assertRegex(version, r"^[0-9a-f]{16}$")
        self.assertEqual(fondo_repo.obtener(), (datos, version))
        self.assertEqual(fondo_repo.version_actual(), version)
        ruta = os.path.join(database.DATA_DIR, "fondo_bloqueo.jpg")
        with open(ruta, "rb") as archivo:
            self.assertEqual(archivo.read(), datos)

    def test_no_queda_ningun_archivo_temporal(self):
        fondo_repo.guardar_jpeg(jpeg_falso())

        self.assertNotIn("fondo_bloqueo.jpg.nuevo", os.listdir(database.DATA_DIR))

    def test_la_version_sale_del_contenido(self):
        uno = fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        mismo_otra_vez = fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        otro = fondo_repo.guardar_jpeg(jpeg_falso(b"otro"))

        self.assertEqual(uno, mismo_otra_vez)
        self.assertNotEqual(uno, otro)

    def test_guardar_otro_reemplaza_al_anterior(self):
        fondo_repo.guardar_jpeg(jpeg_falso(b"viejo"))
        nuevo = jpeg_falso(b"nuevo")

        version = fondo_repo.guardar_jpeg(nuevo)

        self.assertEqual(fondo_repo.obtener(), (nuevo, version))

    def test_quitar_borra_el_archivo_y_las_pcs_vuelven_al_gris_liso(self):
        fondo_repo.guardar_jpeg(jpeg_falso())

        self.assertTrue(fondo_repo.quitar())

        self.assertIsNone(fondo_repo.obtener())
        self.assertEqual(fondo_repo.version_actual(), "")
        self.assertFalse(os.path.exists(os.path.join(database.DATA_DIR, "fondo_bloqueo.jpg")))

    def test_rechaza_lo_que_no_es_un_jpeg_y_no_toca_el_fondo_que_ya_habia(self):
        buena = jpeg_falso()
        version = fondo_repo.guardar_jpeg(buena)

        for mala in (b"", b"texto cualquiera", bytes([0x89]) + b"PNG\r\n" + b"x" * 100):
            with self.assertRaises(ValueError):
                fondo_repo.guardar_jpeg(mala)

        self.assertEqual(fondo_repo.obtener(), (buena, version))

    def test_rechaza_lo_que_pesa_mas_del_tope_y_dice_cuanto_es_el_maximo(self):
        demasiado = FIRMA_JPEG + b"x" * fondo_repo.TAMANO_MAXIMO_BYTES

        with self.assertRaises(ValueError) as contexto:
            fondo_repo.guardar_jpeg(demasiado)

        self.assertIn("máximo es 2 MB", str(contexto.exception))
        self.assertIsNone(fondo_repo.obtener())

    def test_justo_en_el_tope_se_acepta(self):
        justo = FIRMA_JPEG + b"x" * (fondo_repo.TAMANO_MAXIMO_BYTES - len(FIRMA_JPEG))

        fondo_repo.guardar_jpeg(justo)

        self.assertEqual(len(fondo_repo.obtener()[0]), fondo_repo.TAMANO_MAXIMO_BYTES)

    def test_lo_que_se_lee_se_recuerda_y_no_se_vuelve_a_abrir_el_archivo(self):
        fondo_repo.guardar_jpeg(jpeg_falso())

        primero, _ = fondo_repo.obtener()
        segundo, _ = fondo_repo.obtener()

        self.assertIs(primero, segundo)

    def test_si_el_archivo_cambia_por_fuera_del_programa_se_nota(self):
        fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        reemplazo = jpeg_falso(b"cambiado a mano, con otro largo", veces=7)
        with open(fondo_repo.ruta_del_fondo(), "wb") as archivo:
            archivo.write(reemplazo)

        datos, version = fondo_repo.obtener()

        self.assertEqual(datos, reemplazo)
        self.assertEqual(version, fondo_repo.version_actual())

    def test_si_borran_el_archivo_por_fuera_deja_de_haber_fondo(self):
        fondo_repo.guardar_jpeg(jpeg_falso())
        os.remove(fondo_repo.ruta_del_fondo())

        self.assertIsNone(fondo_repo.obtener())
        self.assertEqual(fondo_repo.version_actual(), "")

    def test_un_archivo_que_no_es_un_jpeg_cuenta_como_que_no_hay_fondo(self):
        # Vacío, cortado por un apagón al copiarlo, un texto: las PCs se quedan con el
        # gris liso en vez de intentar dibujar basura.
        for contenido in (b"", b"no soy una imagen"):
            with open(fondo_repo.ruta_del_fondo(), "wb") as archivo:
                archivo.write(contenido)

            self.assertIsNone(fondo_repo.obtener(), contenido)
            self.assertEqual(fondo_repo.version_actual(), "", contenido)

    def test_si_el_antivirus_traba_el_reemplazo_reintenta_y_lo_logra(self):
        fallos = [PermissionError("archivo en uso"), PermissionError("archivo en uso")]
        original = os.replace

        def reemplazo_con_fallos(origen, destino):
            if fallos:
                raise fallos.pop(0)
            original(origen, destino)

        with mock.patch.object(fondo_repo.os, "replace", reemplazo_con_fallos), \
                mock.patch.object(fondo_repo.time, "sleep"):
            version = fondo_repo.guardar_jpeg(jpeg_falso())

        self.assertEqual(fondo_repo.version_actual(), version)

    def test_si_el_reemplazo_nunca_se_logra_avisa_y_no_deja_basura(self):
        with mock.patch.object(fondo_repo.os, "replace", side_effect=PermissionError("en uso")), \
                mock.patch.object(fondo_repo.time, "sleep"):
            with self.assertRaises(PermissionError):
                fondo_repo.guardar_jpeg(jpeg_falso())

        self.assertNotIn("fondo_bloqueo.jpg.nuevo", os.listdir(database.DATA_DIR))
        self.assertIsNone(fondo_repo.obtener())


class TestFondoDelEscritorio(_ConFondoLimpio):
    """El wallpaper de Windows: las mismas reglas que el de bloqueo, en su propio archivo."""

    def test_se_guarda_aparte_y_no_toca_el_de_bloqueo(self):
        version = fondo_repo.guardar_jpeg(jpeg_falso(b"escritorio"), fondo_repo.ESCRITORIO)

        self.assertIsNone(fondo_repo.obtener())
        self.assertEqual(fondo_repo.version_actual(), "")
        self.assertEqual(fondo_repo.obtener(fondo_repo.ESCRITORIO), (jpeg_falso(b"escritorio"), version))
        self.assertEqual(fondo_repo.version_actual(fondo_repo.ESCRITORIO), version)
        self.assertEqual(os.path.basename(fondo_repo.ruta_del_fondo(fondo_repo.ESCRITORIO)), "fondo_escritorio.jpg")
        self.assertTrue(os.path.exists(fondo_repo.ruta_del_fondo(fondo_repo.ESCRITORIO)))

    def test_cada_uno_recuerda_lo_suyo(self):
        bloqueo = fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        escritorio = fondo_repo.guardar_jpeg(jpeg_falso(b"dos"), fondo_repo.ESCRITORIO)

        self.assertNotEqual(bloqueo, escritorio)
        self.assertEqual(fondo_repo.version_actual(fondo_repo.BLOQUEO), bloqueo)
        self.assertEqual(fondo_repo.version_actual(fondo_repo.ESCRITORIO), escritorio)

    def test_la_misma_imagen_en_los_dos_da_la_misma_version(self):
        self.assertEqual(fondo_repo.guardar_jpeg(jpeg_falso()),
                         fondo_repo.guardar_jpeg(jpeg_falso(), fondo_repo.ESCRITORIO))

    def test_quitar_uno_deja_el_otro(self):
        fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        fondo_repo.guardar_jpeg(jpeg_falso(b"dos"), fondo_repo.ESCRITORIO)

        self.assertTrue(fondo_repo.quitar(fondo_repo.ESCRITORIO))

        self.assertIsNone(fondo_repo.obtener(fondo_repo.ESCRITORIO))
        self.assertIsNotNone(fondo_repo.obtener(fondo_repo.BLOQUEO))
        self.assertFalse(fondo_repo.quitar(fondo_repo.ESCRITORIO))

    def test_rechaza_lo_que_no_es_un_jpeg_igual_que_el_de_bloqueo(self):
        with self.assertRaises(ValueError):
            fondo_repo.guardar_jpeg(b"no soy un jpeg", fondo_repo.ESCRITORIO)
        self.assertIsNone(fondo_repo.obtener(fondo_repo.ESCRITORIO))

    def test_un_fondo_que_no_existe_se_rechaza_y_no_arma_ninguna_ruta(self):
        # Llega también desde otra PC (admin remoto): nunca un texto suelto como nombre de archivo.
        for cual in ("..\\kiosko.db", "otro", None):
            with self.assertRaises(ValueError):
                fondo_repo.obtener(cual)
            with self.assertRaises(ValueError):
                fondo_repo.guardar_jpeg(jpeg_falso(), cual)
            with self.assertRaises(ValueError):
                fondo_repo.quitar(cual)
        self.assertFalse(any(nombre.endswith((".jpg", ".nuevo")) for nombre in os.listdir(database.DATA_DIR)))


class TestServidorRedFondo(test_control_pcs._ConServidorRed):
    """GET /fondo y `fondo_version` de GET /estado, con el servidor real."""

    def setUp(self):
        super().setUp()
        fondo_repo._olvidar()
        self.addCleanup(fondo_repo._olvidar)

    def _get_crudo(self, ruta, con_clave=True, cabecera_version="X-Fondo-Version"):
        """(status, versión de la cabecera, tipo, cuerpo en bytes) sin interpretar nada."""
        conexion = http.client.HTTPConnection("127.0.0.1", self._puerto, timeout=5)
        try:
            cabeceras = {"Authorization": "Bearer " + self._clave} if con_clave else {}
            conexion.request("GET", ruta, headers=cabeceras)
            respuesta = conexion.getresponse()
            return (respuesta.status, respuesta.getheader(cabecera_version),
                    respuesta.getheader("Content-Type"), respuesta.read())
        finally:
            conexion.close()

    def _get_escritorio(self, con_clave=True):
        return self._get_crudo("/escritorio", con_clave, cabecera_version="X-Escritorio-Version")

    def test_escritorio_sin_imagen_responde_404_sin_cuerpo(self):
        fondo_repo.guardar_jpeg(jpeg_falso())  # el de bloqueo no cuenta

        status, version, _tipo, cuerpo = self._get_escritorio()

        self.assertEqual((status, version, cuerpo), (404, None, b""))

    def test_escritorio_manda_su_jpeg_con_su_version_y_no_el_de_bloqueo(self):
        fondo_repo.guardar_jpeg(jpeg_falso(b"bloqueo"))
        datos = jpeg_falso(b"escritorio")
        version = fondo_repo.guardar_jpeg(datos, fondo_repo.ESCRITORIO)

        status, version_recibida, tipo, cuerpo = self._get_escritorio()

        self.assertEqual((status, tipo), (200, "image/jpeg"))
        self.assertEqual((version_recibida, cuerpo), (version, datos))
        self.assertEqual(self._get_crudo("/fondo")[3], jpeg_falso(b"bloqueo"))

    def test_escritorio_sin_la_clave_de_los_clientes_responde_403(self):
        fondo_repo.guardar_jpeg(jpeg_falso(), fondo_repo.ESCRITORIO)

        status, version, _tipo, cuerpo = self._get_escritorio(con_clave=False)

        self.assertEqual((status, version, cuerpo), (403, None, b""))

    def test_estado_trae_la_version_del_escritorio_aparte_de_la_del_fondo(self):
        pcs_repo.crear_estacion("PC 1")
        _, datos = self._get("/estado?estacion=PC+1")
        self.assertEqual((datos["fondo_version"], datos["escritorio_version"]), ("", ""))

        version = fondo_repo.guardar_jpeg(jpeg_falso(b"escritorio"), fondo_repo.ESCRITORIO)
        _, datos = self._get("/estado?estacion=PC+1")
        self.assertEqual((datos["fondo_version"], datos["escritorio_version"]), ("", version))
        self.assertEqual(self._get_escritorio()[1], version)

        fondo_repo.quitar(fondo_repo.ESCRITORIO)
        _, datos = self._get("/estado?estacion=PC+1")
        self.assertEqual(datos["escritorio_version"], "")

    def test_si_falla_la_version_del_escritorio_el_estado_sigue_con_la_del_fondo(self):
        pcs_repo.crear_estacion("PC 1")
        version_fondo = fondo_repo.guardar_jpeg(jpeg_falso())
        original = fondo_repo.version_actual

        def falla_el_escritorio(cual=fondo_repo.BLOQUEO):
            if cual == fondo_repo.ESCRITORIO:
                raise OSError("disco roto")
            return original(cual)

        with mock.patch.object(fondo_repo, "version_actual", side_effect=falla_el_escritorio), \
                mock.patch.object(servidor_red, "registrar_error"):
            status, datos = self._get("/estado?estacion=PC+1")

        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertEqual(datos["fondo_version"], version_fondo)
        self.assertNotIn("escritorio_version", datos)

    def test_sin_fondo_responde_404_sin_cuerpo(self):
        status, version, _tipo, cuerpo = self._get_crudo("/fondo")

        self.assertEqual((status, version, cuerpo), (404, None, b""))

    def test_con_fondo_manda_el_jpeg_tal_cual_con_su_version(self):
        datos = jpeg_falso()
        version = fondo_repo.guardar_jpeg(datos)

        status, version_recibida, tipo, cuerpo = self._get_crudo("/fondo")

        self.assertEqual(status, 200)
        self.assertEqual(tipo, "image/jpeg")
        self.assertEqual(version_recibida, version)
        self.assertEqual(cuerpo, datos)

    def test_sin_la_clave_de_los_clientes_responde_403_y_no_regala_la_imagen(self):
        fondo_repo.guardar_jpeg(jpeg_falso())

        status, version, _tipo, cuerpo = self._get_crudo("/fondo", con_clave=False)

        self.assertEqual((status, version, cuerpo), (403, None, b""))

    def test_estado_trae_la_version_vacia_si_no_hay_fondo(self):
        pcs_repo.crear_estacion("PC 1")

        status, datos = self._get("/estado?estacion=PC+1")

        self.assertEqual(status, 200)
        self.assertEqual(datos["fondo_version"], "")

    def test_estado_trae_la_version_del_fondo_y_cambia_cuando_cambia_el_fondo(self):
        pcs_repo.crear_estacion("PC 1")
        primera = fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        _, datos = self._get("/estado?estacion=PC+1")
        self.assertEqual(datos["fondo_version"], primera)

        segunda = fondo_repo.guardar_jpeg(jpeg_falso(b"dos"))
        _, datos = self._get("/estado?estacion=PC+1")
        self.assertEqual(datos["fondo_version"], segunda)
        self.assertNotEqual(primera, segunda)

        fondo_repo.quitar()
        _, datos = self._get("/estado?estacion=PC+1")
        self.assertEqual(datos["fondo_version"], "")

    def test_estado_de_una_estacion_desconocida_tambien_trae_la_version(self):
        version = fondo_repo.guardar_jpeg(jpeg_falso())

        _, datos = self._get("/estado?estacion=PC+99")

        self.assertFalse(datos["existe"])
        self.assertEqual(datos["fondo_version"], version)

    def test_la_version_de_estado_es_la_misma_que_trae_la_imagen(self):
        pcs_repo.crear_estacion("PC 1")
        fondo_repo.guardar_jpeg(jpeg_falso())

        _, estado = self._get("/estado?estacion=PC+1")
        _, version_de_la_imagen, _, _ = self._get_crudo("/fondo")

        self.assertEqual(estado["fondo_version"], version_de_la_imagen)

    def test_si_leer_el_fondo_falla_responde_500_y_el_servidor_sigue_andando(self):
        with mock.patch.object(fondo_repo, "obtener", side_effect=OSError("disco roto")), \
                mock.patch.object(servidor_red, "registrar_error"):
            status, _version, _tipo, cuerpo = self._get_crudo("/fondo")

        self.assertEqual((status, cuerpo), (500, b""))
        self.assertEqual(self._get_crudo("/fondo")[0], 404)

    def test_si_falla_la_version_el_estado_sigue_contestando_sin_ese_dato(self):
        # Una falla del fondo (cosmético) no puede dejar sin respuesta al bloqueo de las PCs.
        pcs_repo.crear_estacion("PC 1")

        with mock.patch.object(fondo_repo, "version_actual", side_effect=OSError("disco roto")), \
                mock.patch.object(servidor_red, "registrar_error"):
            status, datos = self._get("/estado?estacion=PC+1")

        self.assertEqual(status, 200)
        self.assertTrue(datos["bloqueada"])
        self.assertNotIn("fondo_version", datos)


def _guardar_imagen(carpeta, nombre, ancho, alto, color="#336699", formato=QImage.Format.Format_RGB32):
    """Una imagen lisa de ese tamaño, guardada en `carpeta`; devuelve su ruta."""
    imagen = QImage(ancho, alto, formato)
    imagen.fill(QColor(color))
    ruta = os.path.join(carpeta, nombre)
    assert imagen.save(ruta), ruta
    return ruta


class TestPrepararJpeg(unittest.TestCase):
    """Lo que se le hace a la imagen que elige el Admin antes de guardarla."""

    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.carpeta = self._tmp.name

    def _abrir(self, datos):
        imagen = QImage.fromData(datos)
        self.assertFalse(imagen.isNull(), "lo que devolvió preparar_jpeg no se puede abrir como imagen")
        return imagen

    def test_una_imagen_grande_se_achica_sin_deformarse(self):
        ruta = _guardar_imagen(self.carpeta, "grande.png", 4000, 3000)

        datos = pcs_fondo_dialogo.preparar_jpeg(ruta)

        self.assertTrue(datos.startswith(FIRMA_JPEG[:3]))
        imagen = self._abrir(datos)
        # 4:3 entra en 1920x1080 por el alto: 1440x1080.
        self.assertEqual((imagen.width(), imagen.height()), (1440, 1080))

    def test_una_apaisada_16_9_de_4k_queda_en_1920_por_1080(self):
        ruta = _guardar_imagen(self.carpeta, "4k.png", 3840, 2160)

        imagen = self._abrir(pcs_fondo_dialogo.preparar_jpeg(ruta))

        self.assertEqual((imagen.width(), imagen.height()), (1920, 1080))

    def test_una_imagen_chica_no_se_agranda(self):
        ruta = _guardar_imagen(self.carpeta, "chica.png", 800, 450)

        imagen = self._abrir(pcs_fondo_dialogo.preparar_jpeg(ruta))

        self.assertEqual((imagen.width(), imagen.height()), (800, 450))

    def test_el_resultado_siempre_es_un_jpeg_que_entra_en_el_peso_maximo(self):
        ruta = _guardar_imagen(self.carpeta, "lisa.png", 1920, 1080)

        datos = pcs_fondo_dialogo.preparar_jpeg(ruta)

        self.assertTrue(datos.startswith(FIRMA_JPEG[:3]))
        self.assertLessEqual(len(datos), fondo_repo.TAMANO_MAXIMO_BYTES)

    def test_una_foto_muy_ruidosa_baja_la_calidad_hasta_entrar_en_el_peso_maximo(self):
        # Ruido puro: es lo que más pesa. (`crudo` tiene que seguir vivo mientras se usa la
        # imagen: QImage no copia los bytes con los que se la arma.)
        crudo = os.urandom(1920 * 1080 * 4)
        imagen = QImage(crudo, 1920, 1080, QImage.Format.Format_RGB32)
        ruta = os.path.join(self.carpeta, "ruido.png")
        assert imagen.save(ruta)
        calidades = pcs_fondo_dialogo.CALIDADES_A_PROBAR
        pesos = [len(pcs_fondo_dialogo._a_jpeg(imagen, calidad)) for calidad in calidades]
        self.assertEqual(pesos, sorted(pesos, reverse=True), "a menor calidad tiene que pesar menos")
        # Un tope que la primera y la segunda calidad se pasan, y la tercera cumple.
        tope = pesos[2] + 1
        self.assertGreater(pesos[1], tope)

        with mock.patch.object(fondo_repo, "TAMANO_MAXIMO_BYTES", tope):
            datos = pcs_fondo_dialogo.preparar_jpeg(ruta)

        self.assertEqual(len(datos), pesos[2])
        self.assertEqual(self._abrir(datos).width(), 1920)

    def test_si_ni_con_la_peor_calidad_entra_avisa_en_vez_de_guardar_algo_enorme(self):
        ruta = _guardar_imagen(self.carpeta, "lisa.png", 400, 300)

        with mock.patch.object(fondo_repo, "TAMANO_MAXIMO_BYTES", 10):
            with self.assertRaises(ValueError) as contexto:
                pcs_fondo_dialogo.preparar_jpeg(ruta)

        self.assertIn("pesa demasiado", str(contexto.exception))

    def test_lo_transparente_sale_del_gris_de_bloqueo_y_no_negro(self):
        ruta = _guardar_imagen(
            self.carpeta, "transparente.png", 200, 100, color="#00000000",
            formato=QImage.Format.Format_ARGB32,
        )

        imagen = self._abrir(pcs_fondo_dialogo.preparar_jpeg(ruta))

        # Es JPEG (con pérdida): se compara con tolerancia.
        pixel = imagen.pixelColor(100, 50)
        esperado = QColor(pcs_fondo_dialogo.COLOR_BLOQUEO)
        for canal in ("red", "green", "blue"):
            self.assertAlmostEqual(getattr(pixel, canal)(), getattr(esperado, canal)(), delta=8, msg=canal)

    def test_un_archivo_que_no_es_una_imagen_avisa_con_un_mensaje_claro(self):
        ruta = os.path.join(self.carpeta, "texto.png")
        with open(ruta, "w") as archivo:
            archivo.write("esto no es una imagen")

        with self.assertRaises(ValueError) as contexto:
            pcs_fondo_dialogo.preparar_jpeg(ruta)

        self.assertIn("No se pudo abrir esa imagen", str(contexto.exception))

    def test_un_archivo_que_no_existe_avisa_igual(self):
        with self.assertRaises(ValueError):
            pcs_fondo_dialogo.preparar_jpeg(os.path.join(self.carpeta, "no_existe.jpg"))


class _ConDialogo(_ConFondoLimpio):
    """El diálogo con los cuadros de mensaje reemplazados: uno abierto de verdad
    dejaría el test colgado esperando que alguien lo cierre."""

    def setUp(self):
        super().setUp()
        self.errores = []
        self.respuesta_confirmar = True
        self.preguntas = []
        self.ruta_elegida = ""
        parches = [
            mock.patch("ui.utils.mostrar_error", side_effect=lambda *a, **k: self.errores.append(a[2])),
            mock.patch.object(pcs_fondo_dialogo, "confirmar", side_effect=self._confirmar),
            mock.patch.object(
                pcs_fondo_dialogo.QFileDialog, "getOpenFileName",
                side_effect=lambda *a, **k: (self.ruta_elegida, ""),
            ),
        ]
        for parche in parches:
            parche.start()
            self.addCleanup(parche.stop)
        self.carpeta_imagenes = tempfile.TemporaryDirectory()
        self.addCleanup(self.carpeta_imagenes.cleanup)

    def _confirmar(self, _padre, _titulo, texto):
        self.preguntas.append(texto)
        return self.respuesta_confirmar

    def _dialogo(self):
        dialogo = pcs_fondo_dialogo.DialogoFondoPantalla()
        self.addCleanup(dialogo.deleteLater)
        return dialogo


BLOQUEO, ESCRITORIO = fondo_repo.BLOQUEO, fondo_repo.ESCRITORIO


class TestDialogoFondoPantalla(_ConDialogo):
    def test_sin_fondos_lo_dice_en_los_dos_y_no_se_puede_quitar_nada(self):
        dialogo = self._dialogo()

        self.assertIn("gris liso de siempre", dialogo.detalles[BLOQUEO].text())
        self.assertIn("wallpaper que tiene Windows", dialogo.detalles[ESCRITORIO].text())
        for cual in (BLOQUEO, ESCRITORIO):
            self.assertFalse(dialogo.botones_quitar[cual].isEnabled())
            self.assertFalse(dialogo.vistas[cual].pixmap().isNull())  # el monitor, con el liso
            self.assertEqual(dialogo.pastillas[cual].property("tono"), "gris")
        self.assertEqual(dialogo.pastillas[BLOQUEO].text(), "BLOQUEO: SIN IMAGEN")
        self.assertEqual(dialogo.pastillas[ESCRITORIO].text(), "ESCRITORIO: SIN IMAGEN")

    def test_con_un_fondo_guardado_muestra_sus_datos_solo_en_su_lado(self):
        ruta = _guardar_imagen(self.carpeta_imagenes.name, "fondo.png", 1920, 1080)
        fondo_repo.guardar_jpeg(pcs_fondo_dialogo.preparar_jpeg(ruta), ESCRITORIO)

        dialogo = self._dialogo()

        self.assertIn("1920 × 1080", dialogo.detalles[ESCRITORIO].text())
        self.assertTrue(dialogo.botones_quitar[ESCRITORIO].isEnabled())
        self.assertEqual(dialogo.pastillas[ESCRITORIO].text(), "ESCRITORIO ✔")
        self.assertEqual(dialogo.pastillas[ESCRITORIO].property("tono"), "verde")
        self.assertFalse(dialogo.botones_quitar[BLOQUEO].isEnabled())
        self.assertIn("gris liso de siempre", dialogo.detalles[BLOQUEO].text())

    def test_elegir_el_wallpaper_lo_achica_lo_guarda_y_no_toca_el_de_bloqueo(self):
        fondo_repo.guardar_jpeg(jpeg_falso())
        antes = fondo_repo.obtener(BLOQUEO)
        self.ruta_elegida = _guardar_imagen(self.carpeta_imagenes.name, "foto.png", 4000, 2250)
        dialogo = self._dialogo()

        dialogo._elegir(ESCRITORIO)

        datos, version = fondo_repo.obtener(ESCRITORIO)
        imagen = QImage.fromData(datos)
        self.assertEqual((imagen.width(), imagen.height()), (1920, 1080))
        self.assertEqual(fondo_repo.version_actual(ESCRITORIO), version)
        self.assertEqual(fondo_repo.obtener(BLOQUEO), antes)
        self.assertTrue(dialogo.botones_quitar[ESCRITORIO].isEnabled())
        self.assertIn("Wallpaper guardado", dialogo.etiqueta_estado.text())
        self.assertIn("V2.1", dialogo.etiqueta_estado.text())
        self.assertEqual(self.errores, [])

    def test_elegir_el_de_bloqueo_no_toca_el_wallpaper(self):
        self.ruta_elegida = _guardar_imagen(self.carpeta_imagenes.name, "foto.png", 800, 450)
        dialogo = self._dialogo()

        dialogo._elegir(BLOQUEO)

        self.assertIsNotNone(fondo_repo.obtener(BLOQUEO))
        self.assertIsNone(fondo_repo.obtener(ESCRITORIO))
        self.assertIn("Fondo de bloqueo guardado", dialogo.etiqueta_estado.text())

    def test_los_botones_de_cada_lado_eligen_su_fondo(self):
        self.ruta_elegida = _guardar_imagen(self.carpeta_imagenes.name, "foto.png", 800, 450)
        dialogo = self._dialogo()
        elegir = [b for b in dialogo.findChildren(QPushButton) if "ELEGIR IMAGEN" in b.text()]
        self.assertEqual(len(elegir), 2)

        elegir[1].click()  # el de la derecha: el escritorio

        self.assertIsNone(fondo_repo.obtener(BLOQUEO))
        self.assertIsNotNone(fondo_repo.obtener(ESCRITORIO))
        self.assertEqual(self.errores, [])

    def test_usar_la_misma_imagen_la_pone_en_los_dos(self):
        self.ruta_elegida = _guardar_imagen(self.carpeta_imagenes.name, "foto.png", 1280, 720)
        dialogo = self._dialogo()

        dialogo.boton_la_misma.click()

        self.assertEqual(fondo_repo.obtener(BLOQUEO), fondo_repo.obtener(ESCRITORIO))
        self.assertIsNotNone(fondo_repo.obtener(BLOQUEO))
        for cual in (BLOQUEO, ESCRITORIO):
            self.assertTrue(dialogo.botones_quitar[cual].isEnabled())
            self.assertEqual(dialogo.pastillas[cual].property("tono"), "verde")
        self.assertIn("La misma imagen", dialogo.etiqueta_estado.text())
        self.assertEqual(self.errores, [])

    def test_si_se_cancela_el_selector_no_cambia_nada(self):
        fondo_repo.guardar_jpeg(jpeg_falso())
        antes = fondo_repo.obtener()
        self.ruta_elegida = ""
        dialogo = self._dialogo()
        texto_antes = dialogo.etiqueta_estado.text()

        dialogo._elegir(BLOQUEO)
        dialogo._usar_la_misma()

        self.assertEqual(fondo_repo.obtener(), antes)
        self.assertIsNone(fondo_repo.obtener(ESCRITORIO))
        self.assertEqual((dialogo.etiqueta_estado.text(), self.errores), (texto_antes, []))

    def test_elegir_algo_que_no_es_una_imagen_muestra_el_motivo_y_no_toca_nada(self):
        mala = os.path.join(self.carpeta_imagenes.name, "mala.png")
        with open(mala, "w") as archivo:
            archivo.write("no soy una imagen")
        self.ruta_elegida = mala
        dialogo = self._dialogo()

        dialogo._elegir(ESCRITORIO)
        dialogo._usar_la_misma()

        self.assertIsNone(fondo_repo.obtener(BLOQUEO))
        self.assertIsNone(fondo_repo.obtener(ESCRITORIO))
        self.assertEqual(len(self.errores), 2)
        self.assertIn("No se pudo abrir esa imagen", self.errores[0])

    def test_quitar_pide_confirmacion_y_si_se_dice_que_no_no_pasa_nada(self):
        fondo_repo.guardar_jpeg(jpeg_falso(), ESCRITORIO)
        self.respuesta_confirmar = False
        dialogo = self._dialogo()

        dialogo._quitar(ESCRITORIO)

        self.assertIsNotNone(fondo_repo.obtener(ESCRITORIO))
        self.assertEqual(len(self.preguntas), 1)
        self.assertIn("wallpaper", self.preguntas[0])

    def test_quitar_el_wallpaper_deja_el_de_bloqueo(self):
        fondo_repo.guardar_jpeg(jpeg_falso(b"uno"))
        fondo_repo.guardar_jpeg(jpeg_falso(b"dos"), ESCRITORIO)
        dialogo = self._dialogo()

        dialogo._quitar(ESCRITORIO)

        self.assertIsNone(fondo_repo.obtener(ESCRITORIO))
        self.assertIsNotNone(fondo_repo.obtener(BLOQUEO))
        self.assertFalse(dialogo.botones_quitar[ESCRITORIO].isEnabled())
        self.assertTrue(dialogo.botones_quitar[BLOQUEO].isEnabled())
        self.assertEqual(dialogo.pastillas[ESCRITORIO].text(), "ESCRITORIO: SIN IMAGEN")
        self.assertIn("Wallpaper quitado", dialogo.etiqueta_estado.text())

    def test_quitar_el_de_bloqueo_vuelve_al_gris_liso(self):
        fondo_repo.guardar_jpeg(jpeg_falso())
        dialogo = self._dialogo()

        dialogo._quitar(BLOQUEO)

        self.assertIsNone(fondo_repo.obtener())
        self.assertIn("gris liso de siempre", dialogo.detalles[BLOQUEO].text())
        self.assertIn("gris liso de siempre", self.preguntas[0])


class TestVistaEnMonitor(unittest.TestCase):
    def test_dibuja_el_monitor_con_y_sin_imagen_en_los_dos(self):
        from control_pcs.ui import pcs_fondo_vista
        carpeta = tempfile.TemporaryDirectory()
        self.addCleanup(carpeta.cleanup)
        datos = pcs_fondo_dialogo.preparar_jpeg(_guardar_imagen(carpeta.name, "f.png", 640, 480, "#00AA00"))
        medida = (pcs_fondo_vista.ANCHO_PANTALLA + 2 * pcs_fondo_vista.MARCO,
                  pcs_fondo_vista.ALTO_PANTALLA + 2 * pcs_fondo_vista.MARCO + pcs_fondo_vista.PIE)
        for cual in (BLOQUEO, ESCRITORIO):
            for con_imagen in (datos, None):
                vista = pcs_fondo_vista.vista_en_monitor(con_imagen, cual)
                self.assertEqual((vista.width(), vista.height()), medida)
        # Sin imagen, el bloqueo es el gris liso de siempre; con imagen, la imagen (aunque sea 4:3,
        # llena la pantalla del monitor: se recorta, no quedan franjas).
        centro_izquierda = (pcs_fondo_vista.MARCO + 5, pcs_fondo_vista.MARCO + pcs_fondo_vista.ALTO_PANTALLA // 2)
        sin = pcs_fondo_vista.vista_en_monitor(None, BLOQUEO).toImage().pixelColor(*centro_izquierda)
        con = pcs_fondo_vista.vista_en_monitor(datos, BLOQUEO).toImage().pixelColor(*centro_izquierda)
        self.assertEqual(sin.name(), pcs_fondo_vista.COLOR_BLOQUEO.lower())
        self.assertGreater(con.green(), 150)
        self.assertLess(con.red(), 60)


class TestBotonEnGestionarEstaciones(_ConDialogo):
    def test_gestionar_estaciones_tiene_la_tarjeta_y_abre_la_ventana_de_los_fondos(self):
        gestion = pcs_gestion_dialogos.DialogoGestionEstaciones({"rol": dominio.ROL_ADMIN})
        self.addCleanup(gestion.deleteLater)
        botones = [b for b in gestion.findChildren(QPushButton) if b.accessibleName() == "Fondos de pantalla"]
        self.assertEqual(len(botones), 1)

        with mock.patch.object(pcs_gestion_dialogos.DialogoFondoPantalla, "exec") as abrir:
            botones[0].click()

        abrir.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
