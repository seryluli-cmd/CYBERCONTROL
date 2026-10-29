"""
tests/test_ficha_del_socio.py
=============================
La ventana de Miembros con la "ficha del socio" (maqueta B que eligió el dueño el 2026-10-29): la
lista de socios a la izquierda y, a la derecha, la ficha del elegido con su saldo, su última carga,
su última visita, sus datos y los botones que actúan sobre él. Las pantallas se prueban sin abrir
ninguna ventana (plataforma "offscreen" de Qt).
"""

import os
from datetime import date
from unittest import mock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QLabel  # noqa: E402

import dominio  # noqa: E402
from control_pcs.repositories import bonos_miembro_repo, miembros_repo  # noqa: E402
from control_pcs.ui.miembros_ficha import ROL_DATOS, DelegadoDeSocios, texto_de_la_fecha  # noqa: E402
from control_pcs.ui.miembros_window import MiembrosWindow  # noqa: E402
from repositories import config_repo, usuarios_repo  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])

EFECTIVO = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 3000}]


class BaseFicha(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.toby = usuarios_repo.crear_usuario("TOBY", "1234", dominio.ROL_EMPLEADA)
        self.admin = usuarios_repo.crear_usuario("Duenio", "1234", dominio.ROL_ADMIN)
        # ana: con DNI y datos; beto: sin DNI ni nada; cris: con DNI y sin saldo.
        self.ana = miembros_repo.crear_miembro("ana", "clave123", "Ana Pérez", "30111222", "1155554444",
                                               whatsapp="1155550000")
        self.beto = miembros_repo.crear_miembro("beto", "clave123", "", "", "")
        self.cris = miembros_repo.crear_miembro("cris", "clave123", "Cristina", "30111333", "")
        self.bono = bonos_miembro_repo.crear_bono("3 horas", 180, 3000)
        config_repo.guardar_tramos_tarifa_hora_miembro([{"monto_minimo": 0, "tarifa_hora": 1000}])

    def ventana(self, usuario=None):
        ventana = MiembrosWindow(usuarios_repo.obtener_usuario(usuario or self.toby))
        self.addCleanup(ventana.deleteLater)
        return ventana

    def cargar(self, miembro, pagos=EFECTIVO, operador=None):
        return miembros_repo.cargar_saldo_por_bono(miembro, self.bono, pagos, operador or self.toby)["venta_id"]

    def elegir(self, ventana, usuario):
        ventana.lista.setCurrentRow(next(i for i, m in enumerate(ventana.miembros) if m["usuario"] == usuario))

    @staticmethod
    def textos(ventana):
        """Lo que se lee en la ficha."""
        ficha = ventana.ficha
        return {
            "nombre": ficha.etiqueta_nombre.text(), "usuario": ficha.etiqueta_usuario.text(),
            "saldo": ficha.valor_saldo.text(), "carga": ficha.valor_carga.text(),
            "carga_detalle": ficha.aclaracion_carga.text(), "visita": ficha.valor_visita.text(),
            **{clave: etiqueta.text() for clave, etiqueta in ficha.datos.items()},
            "pastillas": [ficha.fila_pastillas.itemAt(i).widget().text() for i in range(ficha.fila_pastillas.count())
                          if ficha.fila_pastillas.itemAt(i).widget() is not None],
        }


class TestLaCabecera(BaseFicha):
    def test_las_cifras_son_de_todos_los_socios_activos_se_filtre_lo_que_se_filtre(self):
        self.cargar(self.ana)
        ventana = self.ventana()
        self.assertEqual(ventana.pastilla_socios.text(), "3 SOCIOS")
        self.assertEqual(ventana.pastilla_con_saldo.text(), "1 CON SALDO")
        self.assertEqual(ventana.pastilla_sin_dni.text(), "1 SIN DNI")
        # Los tres nunca entraron a una PC; a ana se le cargó saldo hoy: no viene hace 0 días.
        self.assertEqual(ventana.pastilla_sin_venir.text(),
                         f"2 NO VIENEN HACE +{dominio.DIAS_SIN_VENIR_AVISO} DÍAS")

        ventana.campo_buscar.setText("ana")
        self.assertEqual(ventana.lista.count(), 1)
        self.assertEqual(ventana.pastilla_socios.text(), "3 SOCIOS")

    def test_un_inactivo_no_cuenta(self):
        miembros_repo.desactivar_miembro(self.cris)
        self.assertEqual(self.ventana().pastilla_socios.text(), "2 SOCIOS")


class TestLaFicha(BaseFicha):
    def test_muestra_los_datos_del_socio_elegido(self):
        self.cargar(self.ana)
        ventana = self.ventana()
        self.elegir(ventana, "ana")

        textos = self.textos(ventana)
        self.assertEqual(textos["nombre"], "Ana Pérez")
        self.assertEqual(textos["usuario"], "Usuario: ana")
        self.assertEqual(textos["saldo"], "3h 00m")
        self.assertEqual(textos["dni"], "30111222")
        self.assertEqual(textos["celular"], "1155554444")
        self.assertEqual(textos["whatsapp"], "1155550000")
        self.assertEqual(textos["email"], "(sin cargar)")
        self.assertEqual(textos["pastillas"], ["ACTIVO", "CON SALDO"])

    def test_lo_que_falta_se_ve_y_un_socio_sin_nombre_sale_con_su_usuario(self):
        ventana = self.ventana()
        self.elegir(ventana, "beto")

        textos = self.textos(ventana)
        self.assertEqual(textos["nombre"], "beto")
        self.assertEqual(textos["dni"], "Falta DNI")
        self.assertEqual(ventana.ficha.datos["dni"].property("falta"), "true")
        self.assertEqual(textos["celular"], "(sin cargar)")
        self.assertEqual(textos["saldo"], "0m 00s")
        self.assertEqual(textos["pastillas"], ["ACTIVO", "SIN SALDO", "FALTA DNI"])

    def test_la_ultima_carga_y_las_ultimas_cargas(self):
        self.cargar(self.ana, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1000},
                               {"metodo": dominio.PAGO_DIGITAL, "monto": 2000}])
        self.cargar(self.ana)
        ventana = self.ventana()
        self.elegir(ventana, "ana")

        textos = self.textos(ventana)
        self.assertTrue(textos["carga"].startswith("Hoy "), textos["carga"])
        self.assertEqual(textos["carga_detalle"], "$ 3.000 · Efectivo · TOBY")
        tabla = ventana.ficha.tabla_cargas
        self.assertEqual(tabla.rowCount(), 2)
        self.assertEqual([tabla.item(0, c).text() for c in (1, 2, 3, 4)], ["3h 00m", "$ 3.000", "Efectivo", "TOBY"])
        self.assertEqual(tabla.item(1, 3).text(), "Efectivo y digital")
        self.assertFalse(ventana.ficha.sin_cargas.isVisibleTo(ventana.ficha))

    def test_sin_cargas_lo_dice_y_no_muestra_la_tabla(self):
        self.cargar(self.ana)
        ventana = self.ventana()
        self.elegir(ventana, "cris")

        self.assertEqual(self.textos(ventana)["carga"], "Sin cargas")
        self.assertTrue(ventana.ficha.tabla_cargas.isHidden())
        self.assertFalse(ventana.ficha.sin_cargas.isHidden())

    def test_solo_muestra_las_ultimas_cuatro(self):
        for _ in range(6):
            self.cargar(self.ana)
        ventana = self.ventana()
        self.elegir(ventana, "ana")
        self.assertEqual(ventana.ficha.tabla_cargas.rowCount(), 4)

    def test_una_carga_anulada_se_ve_tachada_y_no_cuenta_como_la_ultima(self):
        self.cargar(self.ana, [{"metodo": dominio.PAGO_DIGITAL, "monto": 3000}])
        anulada = self.cargar(self.ana)
        miembros_repo.anular_carga(anulada, self.admin, "se cargó mal")
        ventana = self.ventana()
        self.elegir(ventana, "ana")

        # La última carga es la que quedó (digital); la anulada sale tachada en la tabla.
        self.assertEqual(self.textos(ventana)["carga_detalle"], "$ 3.000 · Digital · TOBY")
        tabla = ventana.ficha.tabla_cargas
        self.assertEqual(tabla.rowCount(), 2)
        self.assertTrue(tabla.item(0, 2).font().strikeOut())
        self.assertFalse(tabla.item(1, 2).font().strikeOut())

    def test_cambia_con_el_socio_elegido_y_sigue_siendolo_despues_de_recargar(self):
        ventana = self.ventana()
        self.elegir(ventana, "cris")
        self.assertEqual(self.textos(ventana)["nombre"], "Cristina")

        self.cargar(self.cris)
        ventana._cargar_grilla()

        self.assertEqual(ventana._seleccionado()["usuario"], "cris")
        self.assertEqual(self.textos(ventana)["saldo"], "3h 00m")

    def test_sin_socios_la_ficha_queda_vacia(self):
        ventana = self.ventana()
        ventana.campo_buscar.setText("zzz")

        self.assertEqual(ventana.lista.count(), 0)
        self.assertEqual(ventana.ficha._paginas.currentIndex(), 0)
        self.assertIsNone(ventana._elegido())

    def test_un_inactivo_se_ve_inactivo(self):
        miembros_repo.desactivar_miembro(self.cris)
        ventana = self.ventana()
        self.assertNotIn("cris", [m["usuario"] for m in ventana.miembros])

        ventana.check_inactivos.setChecked(True)
        self.elegir(ventana, "cris")
        self.assertEqual(self.textos(ventana)["pastillas"][0], "INACTIVO")


class TestLosFiltros(BaseFicha):
    def usuarios(self, ventana):
        return [m["usuario"] for m in ventana.miembros]

    def test_con_saldo_y_sin_dni(self):
        self.cargar(self.ana)
        ventana = self.ventana()
        self.assertEqual(self.usuarios(ventana), ["ana", "beto", "cris"])

        ventana.segmentos.elegir("con_saldo")
        self.assertEqual(self.usuarios(ventana), ["ana"])
        ventana.segmentos.elegir("sin_dni")
        self.assertEqual(self.usuarios(ventana), ["beto"])
        ventana.segmentos.elegir("todos")
        self.assertEqual(self.usuarios(ventana), ["ana", "beto", "cris"])

    def test_el_filtro_se_combina_con_el_buscador(self):
        ventana = self.ventana()
        ventana.segmentos.elegir("sin_dni")
        ventana.campo_buscar.setText("cris")
        self.assertEqual(self.usuarios(ventana), [])
        ventana.campo_buscar.setText("bet")
        self.assertEqual(self.usuarios(ventana), ["beto"])


class TestLosBotones(BaseFicha):
    def test_cargar_saldo_abre_el_dialogo_del_elegido_y_despues_se_actualiza(self):
        ventana = self.ventana()
        self.elegir(ventana, "ana")
        with mock.patch("control_pcs.ui.miembros_window.DialogoCargarSaldo") as dialogo:
            dialogo.return_value.exec.return_value = 1
            self.cargar(self.ana)                     # lo que haría el diálogo al aceptar
            ventana.ficha.boton_cargar_saldo.click()

        self.assertEqual(dialogo.call_args.args[1]["usuario"], "ana")
        self.assertEqual(self.textos(ventana)["saldo"], "3h 00m")

    def test_modificar_abre_el_formulario_del_elegido(self):
        ventana = self.ventana()
        self.elegir(ventana, "beto")
        with mock.patch("control_pcs.ui.miembros_window.DialogoMiembro") as dialogo:
            dialogo.return_value.exec.return_value = 0
            ventana.ficha.boton_modificar.click()
        self.assertEqual(dialogo.call_args.args[1]["usuario"], "beto")

    def test_nuevo_abre_el_formulario_vacio(self):
        ventana = self.ventana()
        with mock.patch("control_pcs.ui.miembros_window.DialogoMiembro") as dialogo:
            dialogo.return_value.exec.return_value = 0
            ventana.boton_nuevo.click()
        self.assertEqual(len(dialogo.call_args.args), 1)

    def test_desactivar_pregunta_y_saca_al_socio_de_la_lista(self):
        ventana = self.ventana()
        self.elegir(ventana, "beto")
        with mock.patch("control_pcs.ui.miembros_window.confirmar", return_value=False):
            ventana.ficha.boton_desactivar.click()
        self.assertIn("beto", [m["usuario"] for m in ventana.miembros])

        with mock.patch("control_pcs.ui.miembros_window.confirmar", return_value=True):
            ventana.ficha.boton_desactivar.click()
        self.assertNotIn("beto", [m["usuario"] for m in ventana.miembros])
        self.assertEqual(ventana.pastilla_socios.text(), "2 SOCIOS")

    def test_doble_clic_en_un_socio_lo_modifica(self):
        ventana = self.ventana()
        self.elegir(ventana, "cris")
        with mock.patch("control_pcs.ui.miembros_window.DialogoMiembro") as dialogo:
            dialogo.return_value.exec.return_value = 0
            ventana.lista.itemDoubleClicked.emit(ventana.lista.item(ventana.lista.currentRow()))
        self.assertEqual(dialogo.call_args.args[1]["usuario"], "cris")


class TestLoQueSeDibuja(BaseFicha):
    def test_la_lista_pinta_al_elegido_con_su_rayita_azul(self):
        ventana = self.ventana()
        ventana.setAttribute(Qt.WA_DontShowOnScreen)
        ventana.show()
        self.addCleanup(ventana.hide)
        _app.processEvents()

        imagen = ventana.lista.viewport().grab().toImage()
        # El primer socio está elegido: la rayita de 3 px del costado, en el medio del renglón.
        self.assertEqual(imagen.pixelColor(1, DelegadoDeSocios.ALTO // 2).name(), "#2f6fed")
        # Y el segundo no la tiene.
        self.assertNotEqual(imagen.pixelColor(1, DelegadoDeSocios.ALTO + DelegadoDeSocios.ALTO // 2).name(), "#2f6fed")

    def test_cada_renglon_trae_su_socio_y_hace_cuanto_no_viene(self):
        ventana = self.ventana()
        datos = ventana.lista.item(0).data(ROL_DATOS)
        self.assertEqual(datos["miembro"]["usuario"], "ana")
        self.assertIsNone(datos["dias"])           # nunca vino

    def test_la_ficha_tiene_el_texto_de_la_pastilla_y_ninguna_etiqueta_queda_en_blanco(self):
        ventana = self.ventana()
        self.elegir(ventana, "ana")
        vacias = [e.objectName() for e in ventana.ficha.findChildren(QLabel)
                  if e.objectName() in ("fichaNombre", "fichaValorBloque", "fichaValorDato") and not e.text()]
        self.assertEqual(vacias, [])


class TestLosTextos(BaseFicha):
    def test_la_fecha_de_la_ultima_carga(self):
        hoy = date(2026, 10, 29)
        self.assertEqual(texto_de_la_fecha("2026-10-29T18:42:05", hoy), "Hoy 18:42")
        self.assertEqual(texto_de_la_fecha("2026-10-28 20:10:00", hoy), "Ayer 20:10")
        self.assertEqual(texto_de_la_fecha("2026-10-26T09:05:00", hoy), "26/10 09:05")


if __name__ == "__main__":
    import unittest
    unittest.main()
