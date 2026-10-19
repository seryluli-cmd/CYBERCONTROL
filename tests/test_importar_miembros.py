"""
tests/test_importar_miembros.py
=================================
Importar los socios del programa de cyber anterior desde una planilla de Excel
(pedido del dueño, 2026-10-19): usuario, nombre, contraseña y el tiempo que les
quedaba. Ver control_pcs/repositories/importar_miembros_repo.py.

Las planillas se arman acá mismo como .xlsx de verdad (un .zip con XML), igual
que las guarda Excel: textos en sharedStrings.xml y el tiempo como fracción de día.
"""

import os
import tempfile
import unittest
import zipfile
from xml.sax.saxutils import escape

import database
import dominio
from repositories import usuarios_repo
from control_pcs.repositories import actividad_repo, importar_miembros_repo, miembros_repo
from base import BaseConBaseTemporal

TITULOS = ["Usuario", "Nombre", "Contraseña", "Tiempo equivalente", "Saldo (ARS)"]


def _hora(horas=0, minutos=0, segundos=0) -> float:
    """Un tiempo como lo guarda Excel: fracción de día."""
    return (horas * 3600 + minutos * 60 + segundos) / 86400


def _columna(indice: int) -> str:
    return "ABCDEFGHIJ"[indice]


def armar_xlsx(ruta: str, renglones: list, numeros_como_texto: bool = True):
    """Guarda en `ruta` un .xlsx con una hoja y `renglones` (listas de celdas:
    str, float/int o None). Los textos van a sharedStrings.xml, como hace Excel."""
    textos = []
    filas_xml = []
    for numero, renglon in enumerate(renglones, start=1):
        celdas = []
        for indice, valor in enumerate(renglon):
            referencia = f"{_columna(indice)}{numero}"
            if valor is None:
                continue
            if isinstance(valor, str):
                textos.append(valor)
                celdas.append(f'<c r="{referencia}" t="s"><v>{len(textos) - 1}</v></c>')
            else:
                celdas.append(f'<c r="{referencia}"><v>{valor!r}</v></c>')
        filas_xml.append(f'<row r="{numero}">{"".join(celdas)}</row>')
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    hoja = f'<?xml version="1.0" encoding="UTF-8"?><worksheet {ns}><sheetData>{"".join(filas_xml)}</sheetData></worksheet>'
    compartidos = "".join(f"<si><t>{escape(texto)}</t></si>" for texto in textos)
    sst = f'<?xml version="1.0" encoding="UTF-8"?><sst {ns}>{compartidos}</sst>'
    with zipfile.ZipFile(ruta, "w") as libro:
        libro.writestr("[Content_Types].xml", "<Types/>")
        libro.writestr("xl/workbook.xml", f"<workbook {ns}/>")
        libro.writestr("xl/sharedStrings.xml", sst)
        libro.writestr("xl/worksheets/sheet1.xml", hoja)


class _ConPlanilla(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Jefe", "1234", dominio.ROL_ADMIN)
        self.empleada_id = usuarios_repo.crear_usuario("Ana", "1234", dominio.ROL_EMPLEADA)
        self.ruta = os.path.join(self._tmp_dir.name, "miembros.xlsx")

    def planilla(self, *socios, arriba=None, abajo=None):
        """Planilla parecida a la del dueño: título y notas arriba, los
        títulos de las columnas, los socios y el "Saldo total" al final."""
        renglones = arriba if arriba is not None else [[], ["Miembros del ciber"], ["Fuente: USDB.DAT"], []]
        renglones = renglones + [TITULOS] + [list(socio) for socio in socios]
        renglones += abajo if abajo is not None else [["Saldo total", None, None, None, 319079.99]]
        armar_xlsx(self.ruta, renglones)
        return self.ruta

    def importar(self):
        return importar_miembros_repo.importar_planilla(self.ruta, self.admin_id)

    def socio(self, usuario):
        return next(m for m in miembros_repo.listar_miembros(incluir_inactivos=True) if m["usuario"] == usuario)

    def movimientos(self):
        with database.conexion_db() as conexion:
            return conexion.execute("SELECT * FROM movimientos_saldo_miembro ORDER BY id").fetchall()


class TestImportarSocios(_ConPlanilla):
    def test_crea_cada_socio_con_su_clave_su_nombre_y_su_tiempo(self):
        self.planilla(
            ["alvaro", "Alvaro Torres", "secreta1", _hora(1, 17, 57), 1299.27],
            ["cris", "Cristian Ibarra", "otra", _hora(8, 59, 59), 8999.91],
        )

        resultado = self.importar()

        self.assertEqual([s["usuario"] for s in resultado["nuevos"]], ["alvaro", "cris"])
        alvaro = self.socio("alvaro")
        self.assertEqual(alvaro["nombre"], "Alvaro Torres")
        # 1:17:57 son 77 minutos: los segundos se descartan, nunca para arriba.
        self.assertEqual(alvaro["saldo_minutos"], 77)
        self.assertEqual(self.socio("cris")["saldo_minutos"], 539)
        self.assertEqual(resultado["minutos_en_total"], 77 + 539)
        self.assertIsNotNone(miembros_repo.autenticar_miembro("alvaro", "secreta1"))
        self.assertIsNone(miembros_repo.autenticar_miembro("alvaro", "otra"))
        # El DNI se lo pide su PC la primera vez, como a cualquier alta rápida.
        self.assertFalse(miembros_repo.tiene_dni(alvaro))

    def test_el_tiempo_queda_en_el_historial_sin_venta_ni_plata_en_la_caja(self):
        self.planilla(["alvaro", "Alvaro Torres", "secreta1", _hora(2), 2000])

        self.importar()

        (movimiento,) = self.movimientos()
        self.assertEqual(movimiento["tipo"], dominio.MOVIMIENTO_IMPORTACION)
        self.assertEqual(movimiento["minutos"], 120)
        self.assertIsNone(movimiento["venta_id"])
        with database.conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) AS n FROM ventas").fetchone()["n"], 0)

    def test_la_importacion_no_llena_el_panel_de_actividad(self):
        self.planilla(["alvaro", "Alvaro Torres", "secreta1", _hora(2), 2000])

        self.importar()

        self.assertEqual(actividad_repo.actividad_reciente(), [])

    def test_con_el_tiempo_importado_el_socio_abre_una_pc(self):
        from control_pcs.repositories import pcs_repo
        estacion_id = pcs_repo.crear_estacion("PC1")
        self.planilla(["alvaro", "Alvaro Torres", "secreta1", _hora(1, 17, 57), 1299.27])
        self.importar()

        resumen = miembros_repo.abrir_estacion_por_miembro(estacion_id, "alvaro", "secreta1")

        self.assertEqual(resumen["minutos_usados"], 77)

    def test_importar_dos_veces_no_duplica_ni_suma_el_tiempo_de_nuevo(self):
        self.planilla(["alvaro", "Alvaro Torres", "secreta1", _hora(2), 2000])
        self.importar()

        segunda = self.importar()

        self.assertEqual(segunda["nuevos"], [])
        self.assertEqual(segunda["ya_existen"], ["alvaro"])
        self.assertEqual(self.socio("alvaro")["saldo_minutos"], 120)
        self.assertEqual(len(self.movimientos()), 1)

    def test_un_socio_que_ya_existe_conserva_su_clave_y_su_saldo(self):
        miembros_repo.crear_miembro("alvaro", "la-de-ahora")
        self.planilla(
            ["alvaro", "Alvaro Torres", "la-vieja", _hora(5), 5000],
            ["cris", "Cristian", "otra", _hora(1), 1000],
        )

        resultado = self.importar()

        self.assertEqual(resultado["ya_existen"], ["alvaro"])
        self.assertEqual([s["usuario"] for s in resultado["nuevos"]], ["cris"])
        self.assertIsNotNone(miembros_repo.autenticar_miembro("alvaro", "la-de-ahora"))
        self.assertEqual(self.socio("alvaro")["saldo_minutos"], 0)

    def test_un_tiempo_que_no_se_entiende_entra_en_cero_y_se_avisa(self):
        self.planilla(["sergio", "JEFE PEREZ", "clave1", "Por confirmar", 13000])

        resultado = self.importar()

        self.assertEqual(resultado["sin_tiempo"], [("sergio", "Por confirmar")])
        self.assertEqual(self.socio("sergio")["saldo_minutos"], 0)
        self.assertEqual(self.movimientos(), [])
        # No va también entre los de poco saldo: ya se avisa aparte.
        self.assertEqual(resultado["con_poco_saldo"], [])

    def test_avisa_quienes_quedan_con_menos_de_30_minutos(self):
        self.planilla(
            ["agus555", "Agustin", "triple5", _hora(0, 0, 58), 16.29],
            ["karma", "Jere", "abcd", _hora(0, 26, 59), 449.81],
            ["cris", "Cristian", "otra", _hora(0, 30), 500],
        )

        resultado = self.importar()

        self.assertEqual(resultado["con_poco_saldo"], ["agus555", "karma"])
        self.assertEqual(self.socio("agus555")["saldo_minutos"], 0)
        self.assertEqual(self.socio("karma")["saldo_minutos"], 26)

    def test_sin_nombre_se_lo_ve_con_el_usuario(self):
        self.planilla(["toxin", None, "abcd", _hora(1), 1000])

        self.importar()

        self.assertEqual(self.socio("toxin")["nombre"], "toxin")

    def test_una_clave_de_puros_numeros_guardada_como_numero_sirve_igual(self):
        self.planilla(["andresff", "Andres", 123456, _hora(1), 1000])

        self.importar()

        self.assertIsNotNone(miembros_repo.autenticar_miembro("andresff", "123456"))

    def test_renglones_que_no_se_pueden_importar_se_avisan_y_no_frenan_a_los_demas(self):
        self.planilla(
            ["alvaro", "Alvaro", "secreta1", _hora(1), 1000],
            ["sinclave", "Sin Clave", None, _hora(1), 1000],
            [None, "Sin Usuario", "abcd", _hora(1), 1000],
            ["alvaro", "Alvaro otra vez", "xyz", _hora(3), 3000],
        )

        resultado = self.importar()

        self.assertEqual([s["usuario"] for s in resultado["nuevos"]], ["alvaro"])
        self.assertEqual(resultado["con_problemas"], [
            (7, "sinclave", "falta la contraseña"),
            (8, "", "falta el usuario"),
            (9, "alvaro", "está repetido en la planilla (ya está en la fila 6)"),
        ])
        self.assertEqual(self.socio("alvaro")["saldo_minutos"], 60)

    def test_el_saldo_total_del_final_y_las_notas_de_arriba_no_son_socios(self):
        self.planilla(["alvaro", "Alvaro", "secreta1", _hora(1), 1000])

        resultado = self.importar()

        self.assertEqual(resultado["con_problemas"], [])
        self.assertEqual(len(miembros_repo.listar_miembros()), 1)

    def test_revisar_no_toca_nada(self):
        self.planilla(["alvaro", "Alvaro", "secreta1", _hora(1), 1000])

        resumen = importar_miembros_repo.revisar_planilla(self.ruta)

        self.assertEqual([s["usuario"] for s in resumen["nuevos"]], ["alvaro"])
        self.assertEqual(miembros_repo.listar_miembros(), [])
        # El resumen va a la pantalla: nunca lleva las claves.
        self.assertNotIn("secreta1", repr(resumen))

    def test_solo_un_administrador_importa(self):
        self.planilla(["alvaro", "Alvaro", "secreta1", _hora(1), 1000])

        with self.assertRaises(PermissionError):
            importar_miembros_repo.importar_planilla(self.ruta, self.empleada_id)
        self.assertEqual(miembros_repo.listar_miembros(), [])

    def test_si_algo_falla_en_el_medio_no_queda_ningun_socio_a_medias(self):
        self.planilla(
            ["alvaro", "Alvaro", "secreta1", _hora(1), 1000],
            ["cris", "Cristian", "otra", _hora(2), 2000],
        )
        original = miembros_repo._insertar_miembro
        llamadas = []

        def falla_en_el_segundo(*args, **kwargs):
            llamadas.append(1)
            if len(llamadas) == 2:
                raise RuntimeError("se cortó la luz")
            return original(*args, **kwargs)

        miembros_repo._insertar_miembro = falla_en_el_segundo
        try:
            with self.assertRaises(RuntimeError):
                self.importar()
        finally:
            miembros_repo._insertar_miembro = original

        self.assertEqual(miembros_repo.listar_miembros(), [])
        self.assertEqual(self.movimientos(), [])


class TestLeerLaPlanilla(_ConPlanilla):
    def test_los_titulos_pueden_estar_en_otro_orden_y_con_otro_nombre(self):
        armar_xlsx(self.ruta, [
            ["Tiempo", "Clave", "Nombre de usuario", "Nombre"],
            [_hora(2), "secreta1", "alvaro", "Alvaro Torres"],
        ])

        resumen = importar_miembros_repo.revisar_planilla(self.ruta)

        self.assertEqual(resumen["nuevos"], [{"fila": 2, "usuario": "alvaro", "nombre": "Alvaro Torres", "minutos": 120}])

    def test_sin_los_titulos_avisa_que_falta(self):
        armar_xlsx(self.ruta, [["Nombre", "Tiempo"], ["Alvaro", _hora(1)]])

        with self.assertRaisesRegex(ValueError, "Usuario"):
            importar_miembros_repo.revisar_planilla(self.ruta)

    def test_un_archivo_que_no_es_un_xlsx_se_avisa_con_un_mensaje_claro(self):
        with open(self.ruta, "w", encoding="utf-8") as archivo:
            archivo.write("usuario;clave\nalvaro;1234\n")

        with self.assertRaisesRegex(ValueError, "Excel"):
            importar_miembros_repo.revisar_planilla(self.ruta)

    def test_tiempos_escritos_como_texto(self):
        casos = {"1:17:57": 77, "2:05": 125, " 0:00:59 ": 0, "": 0, None: 0,
                 "Por confirmar": None, "-1": None}
        for valor, minutos in casos.items():
            with self.subTest(valor=valor):
                self.assertEqual(importar_miembros_repo.minutos_del_tiempo(valor), minutos)

    def test_tiempos_como_los_guarda_excel(self):
        self.assertEqual(importar_miembros_repo.minutos_del_tiempo(_hora(1, 18)), 78)
        self.assertEqual(importar_miembros_repo.minutos_del_tiempo(_hora(81, 12, 58)), 81 * 60 + 12)
        self.assertEqual(importar_miembros_repo.minutos_del_tiempo(-0.5), None)


class TestBaseVieja(unittest.TestCase):
    def test_una_base_de_antes_acepta_el_movimiento_de_importacion(self):
        """El CHECK de movimientos_saldo_miembro.tipo de una base que ya existía no
        tenía IMPORTACION: la migración que lo reconstruye corre sola al arrancar."""
        with tempfile.TemporaryDirectory() as carpeta:
            data_dir, db_path = database.DATA_DIR, database.DB_PATH
            database.DATA_DIR = carpeta
            database.DB_PATH = os.path.join(carpeta, "vieja.db")
            try:
                database.inicializar_base_de_datos()
                with database.conexion_db() as conexion:
                    sql = conexion.execute(
                        "SELECT sql FROM sqlite_master WHERE name = 'movimientos_saldo_miembro'"
                    ).fetchone()["sql"]
                    conexion.execute("PRAGMA foreign_keys = OFF")
                    conexion.execute("DROP TABLE movimientos_saldo_miembro")
                    conexion.execute(sql.replace(", 'IMPORTACION'", ""))
                with database.conexion_db() as conexion:
                    sql_viejo = conexion.execute(
                        "SELECT sql FROM sqlite_master WHERE name = 'movimientos_saldo_miembro'"
                    ).fetchone()["sql"]
                self.assertNotIn("IMPORTACION", sql_viejo)

                database.inicializar_base_de_datos()

                miembro_id = miembros_repo.crear_miembro("alvaro", "secreta1")
                with database.conexion_db() as conexion:
                    conexion.execute(
                        "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha) VALUES (?, ?, ?, ?)",
                        (miembro_id, dominio.MOVIMIENTO_IMPORTACION, 60, "2026-10-19T10:00:00"),
                    )
            finally:
                database.DATA_DIR, database.DB_PATH = data_dir, db_path


if __name__ == "__main__":
    unittest.main()
