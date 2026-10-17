"""
tests/test_mosaico_pcs_ui.py
==============================
El mosaico de monitores de Control de PCs (control_pcs/ui/pcs_mosaico.py, armado
por pcs_window.PanelControlPcs): que las PCs salgan en orden natural (PC2 antes
que PC10), que cada estado lleve su color y su dibujito, que el refresco de cada
5 segundos no rearme los casilleros (así no parpadea todo ni se pierde la
selección), que una sesión sin Cliente PC titile y que vayan 8 equipos por fila.
Con Qt "offscreen", sin abrir ventanas.

Se ejecutan con:

    python -m unittest discover tests
"""

import os
import unittest
from datetime import datetime, timedelta

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtGui import QColor  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

import dominio  # noqa: E402
from database import conexion_db  # noqa: E402
from repositories import usuarios_repo  # noqa: E402
from control_pcs.repositories import pcs_repo, miembros_repo  # noqa: E402
from control_pcs.ui import pcs_window, pcs_mosaico  # noqa: E402
from control_pcs.ui.pcs_window import PanelControlPcs  # noqa: E402
from base import BaseConBaseTemporal  # noqa: E402

_app = QApplication.instance() or QApplication([])


def _efectivo(monto):
    return [{"metodo": dominio.PAGO_EFECTIVO, "monto": monto}]


class TestOrdenNaturalDeLasEstaciones(BaseConBaseTemporal):
    def test_pc2_va_antes_que_pc10(self):
        for nombre in ("PC10", "PC2", "pc1", "PC11", "Caja"):
            pcs_repo.crear_estacion(nombre)

        esperado = ["Caja", "pc1", "PC2", "PC10", "PC11"]
        self.assertEqual([e["nombre"] for e in pcs_repo.listar_estaciones()], esperado)
        self.assertEqual([i["estacion"]["nombre"] for i in pcs_repo.estado_estaciones()], esperado)


class TestMosaicoDePcs(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin_id = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.bono_id = pcs_repo.crear_bono("1 hora", 60, 1500)

    def _grilla(self):
        usuario = usuarios_repo.obtener_usuario(self.admin_id)
        grilla = PanelControlPcs(usuario)
        self.addCleanup(grilla.deleteLater)
        self.addCleanup(grilla.detener_actualizacion)
        return grilla

    def _ficha(self, grilla, nombre):
        for fila in range(grilla.mosaico.count()):
            ficha = grilla.mosaico.ficha(fila)
            if ficha.nombre == nombre:
                return fila, ficha
        self.fail(f"No está {nombre} en el mosaico")

    def _id_sesion(self, estacion_id):
        with conexion_db() as conexion:
            return conexion.execute(
                "SELECT id FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
                (estacion_id, dominio.SESION_ACTIVA),
            ).fetchone()["id"]

    def test_cada_estado_lleva_su_color_y_su_dibujo(self):
        libre = pcs_repo.crear_estacion("PC1")
        en_uso = pcs_repo.crear_estacion("PC2")
        pcs_repo.crear_estacion("PC3")  # nunca se conectó
        pcs_repo.registrar_conexion(libre)
        pcs_repo.registrar_conexion(en_uso)
        pcs_repo.asignar_bono(en_uso, self.bono_id, self.admin_id, _efectivo(1500))

        grilla = self._grilla()

        _, ficha = self._ficha(grilla, "PC1")
        self.assertEqual(ficha.color, pcs_window.COLOR_DISPONIBLE)
        self.assertEqual(ficha.dibujo, pcs_mosaico.DIBUJO_NINGUNO)
        _, ficha = self._ficha(grilla, "PC2")
        self.assertEqual(ficha.color, pcs_window.COLOR_EN_USO)
        self.assertEqual(ficha.dibujo, pcs_mosaico.DIBUJO_RELOJ)
        self.assertTrue(ficha.con_bono)
        self.assertNotEqual(ficha.restante, "—")
        _, ficha = self._ficha(grilla, "PC3")
        self.assertEqual(ficha.color, pcs_window.COLOR_DESCONECTADA)
        self.assertEqual(ficha.restante, "—")

    def test_la_pc_de_un_socio_muestra_su_nombre_y_no_las_monedas(self):
        estacion = pcs_repo.crear_estacion("PC1")
        pcs_repo.registrar_conexion(estacion)
        pcs_repo.asignar_bono(estacion, self.bono_id, self.admin_id, _efectivo(1500))
        socio = miembros_repo.crear_miembro("juanp", "x", "Juan Pérez", "30111222", "1155550000")
        with conexion_db() as conexion:
            conexion.execute("UPDATE sesiones_pc SET miembro_id = ? WHERE id = ?", (socio, self._id_sesion(estacion)))

        _, ficha = self._ficha(self._grilla(), "PC1")

        self.assertEqual(ficha.dibujo, pcs_mosaico.DIBUJO_SOCIO)
        self.assertEqual(ficha.aviso, "Juan Pérez")
        self.assertFalse(ficha.con_bono)

    def test_una_sesion_sin_cliente_pc_titila(self):
        estacion = pcs_repo.crear_estacion("PC1")
        pcs_repo.registrar_conexion(estacion)
        pcs_repo.asignar_bono(estacion, self.bono_id, self.admin_id, _efectivo(1500))
        # Estuvo enlazada durante la sesión y dejó de responder hace 2 minutos.
        with conexion_db() as conexion:
            conexion.execute(
                "UPDATE sesiones_pc SET fecha_inicio = ? WHERE id = ?",
                ((datetime.now() - timedelta(minutes=10)).isoformat(timespec="seconds"), self._id_sesion(estacion)),
            )
            conexion.execute(
                "UPDATE estaciones SET ultima_conexion = ? WHERE id = ?",
                ((datetime.now() - timedelta(minutes=2)).isoformat(timespec="seconds"), estacion),
            )

        grilla = self._grilla()
        fila, ficha = self._ficha(grilla, "PC1")

        self.assertTrue(ficha.en_alerta)
        self.assertEqual(ficha.dibujo, pcs_mosaico.DIBUJO_ALERTA)
        self.assertIn(fila, grilla._filas_en_alerta)
        colores = []
        for _ in range(3):
            colores.append(grilla.mosaico.color(fila).name())
            grilla._alternar_parpadeo()
        self.assertEqual(colores[0], pcs_window.COLOR_ALERTA_SESION_SIN_CLIENTE.name())
        self.assertEqual(colores[1], pcs_window.COLOR_ALERTA_SESION_SIN_CLIENTE_APAGADA.name())
        self.assertEqual(colores[0], colores[2])

    def test_el_refresco_no_rearma_los_casilleros_ni_pierde_la_seleccion(self):
        for nombre in ("PC1", "PC2"):
            pcs_repo.registrar_conexion(pcs_repo.crear_estacion(nombre))
        grilla = self._grilla()
        fila, _ = self._ficha(grilla, "PC2")
        grilla.mosaico.elegir(fila)
        casilleros = [grilla.mosaico.item(f) for f in range(grilla.mosaico.count())]

        grilla._refrescar()

        self.assertEqual([grilla.mosaico.item(f) for f in range(grilla.mosaico.count())], casilleros)
        self.assertEqual(grilla.mosaico.fila_elegida(), fila)
        self.assertEqual(grilla.panel_detalle.etiqueta_titulo.text(), "PC2")

    def test_una_pc_nueva_aparece_en_su_lugar_y_la_seleccion_la_sigue(self):
        pcs_repo.registrar_conexion(pcs_repo.crear_estacion("PC2"))
        grilla = self._grilla()
        grilla.mosaico.elegir(self._ficha(grilla, "PC2")[0])

        pcs_repo.crear_estacion("PC1")
        grilla._refrescar()

        nombres = [grilla.mosaico.ficha(f).nombre for f in range(grilla.mosaico.count())]
        self.assertEqual(nombres[-2:], ["PC1", "PC2"])
        self.assertEqual(grilla.mosaico.ficha(grilla.mosaico.fila_elegida()).nombre, "PC2")

    def test_el_mosaico_se_dibuja_sin_errores(self):
        estacion = pcs_repo.crear_estacion("PC1")
        pcs_repo.registrar_conexion(estacion)
        pcs_repo.asignar_bono(estacion, self.bono_id, self.admin_id, _efectivo(1500))
        grilla = self._grilla()
        grilla.resize(900, 600)
        grilla.mosaico.elegir(0)

        imagen = grilla.grab()

        self.assertFalse(imagen.isNull())


class TestOchoEquiposPorFila(unittest.TestCase):
    """Pedido del dueño (2026-10-17): 8 equipos por fila, no "los que entren"."""

    def _mosaico(self, cantidad, ancho, alto):
        mosaico = pcs_mosaico.MosaicoDeEquipos()
        self.addCleanup(mosaico.deleteLater)
        mosaico.mostrar([
            pcs_mosaico.Ficha(clave=(n,), nombre=f"PC{n}", estado="", restante="—", quien="—", color=QColor("red"))
            for n in range(cantidad)
        ])
        mosaico.resize(ancho, alto)
        mosaico.show()
        _app.processEvents()
        return mosaico

    @staticmethod
    def _equipos_por_fila(mosaico):
        por_altura = {}
        for fila in range(mosaico.count()):
            altura = mosaico.visualItemRect(mosaico.item(fila)).y()
            por_altura[altura] = por_altura.get(altura, 0) + 1
        return [por_altura[altura] for altura in sorted(por_altura)]

    def test_van_8_por_fila_en_cualquier_ancho_en_que_entran(self):
        # Varios anchos seguidos: con algunos, repartir sin restar la barra de
        # desplazamiento o el último píxel dejaba 7 en vez de 8.
        for ancho in (900, 1300, 1301, 1303, 1307, 1600, 1901, 1907):
            with self.subTest(ancho=ancho):
                self.assertEqual(self._equipos_por_fila(self._mosaico(21, ancho, 500)), [8, 8, 5])

    def test_tambien_con_la_barra_de_desplazamiento_a_la_vista(self):
        mosaico = self._mosaico(40, 1300, 300)

        self.assertTrue(mosaico.verticalScrollBar().isVisible())
        self.assertEqual(self._equipos_por_fila(mosaico), [8, 8, 8, 8, 8])

    def test_si_no_entran_8_enteros_no_se_achican_los_casilleros(self):
        mosaico = self._mosaico(21, 600, 500)

        self.assertLess(self._equipos_por_fila(mosaico)[0], 8)
        self.assertEqual(mosaico.gridSize().width(), pcs_mosaico.ANCHO_CASILLERO)


if __name__ == "__main__":
    unittest.main()
