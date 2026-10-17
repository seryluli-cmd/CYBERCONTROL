"""
tests/test_velocidad_pantalla_pcs.py
=====================================
La pantalla de PCs se refresca cada 5 segundos. Lo que pide en cada refresco
(las sesiones en curso y el panel "Actividad reciente", con la PlayStation 5)
no puede volverse más lento a medida que se acumula historial: en la revisión
del 2026-10-17 (docs/AUDITORIA_2026-10-17.md), con un año simulado de 40 PCs,
la pantalla se trababa ~0,4 s cada 5 s porque la base leía toda la historia.

Se mide el TRABAJO de la base y no el tiempo (que depende de la PC y de qué
más esté corriendo): SQLite avisa cada tantas instrucciones que ejecuta y se
cuentan esos avisos. Con los índices de database_esquema ("ÍNDICES"), pedir
lo último cuesta lo mismo con 400 que con 2.000 sesiones viejas; sin ellos,
crece con el historial.

Se ejecutan con:

    python -m unittest discover tests
"""

from datetime import datetime, timedelta
from unittest import mock

import database
import dominio
from base import BaseConBaseTemporal
from control_pcs.repositories import actividad_repo, miembros_repo, pcs_repo, pcstream_repo, playstation_repo
from repositories import usuarios_repo

# Cada cuántas instrucciones de SQLite se cuenta un aviso.
_INSTRUCCIONES_POR_AVISO = 100


class TestLaPantallaDePcsNoSeVuelveLentaConElHistorial(BaseConBaseTemporal):
    def setUp(self):
        super().setUp()
        self.admin = usuarios_repo.crear_usuario("Admin", "1234", dominio.ROL_ADMIN)
        self.estaciones = [pcs_repo.crear_estacion(f"PC{n}") for n in range(1, 6)]
        self.estaciones.append(pcs_repo.crear_estacion("PCSTREAM"))
        self.bono = pcs_repo.crear_bono("1 hora", 60, 1500)
        self.bono_stream = pcstream_repo.crear_bono("Stream 1 hora", 60, 2500)
        self.bono_consola = playstation_repo.crear_bono(self.admin, "1 hora", 60, 3000)
        self.socio = miembros_repo.crear_miembro("juan", "x", "Juan", "30111222", "1155550000")
        # Todo el historial simulado queda antes de hoy, cada cosa en su propio
        # minuto (sin empates de fecha, así el orden es uno solo).
        self._momento = datetime.now() - timedelta(days=400)

    def _abrir_una_pc_ahora(self):
        """Una PC en uso ahora mismo. Va DESPUÉS del historial, como en la
        realidad: lo de hoy se vende después que lo de ayer."""
        pcs_repo.registrar_conexion(self.estaciones[0])
        pcs_repo.asignar_bono(self.estaciones[0], self.bono, self.admin, [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500}])

    def _siguiente_momento(self):
        self._momento += timedelta(minutes=7)
        return self._momento

    def _sumar_historial(self, sesiones):
        """`sesiones` sesiones ya terminadas, cada una con su bono vendido (una de
        cada cinco en PCSTREAM), más movimientos de socio, traslados, accesos de
        admin, bloqueos del filtro de palabras y sesiones de la PlayStation 5: lo
        que se va acumulando día a día."""
        with database.conexion_db() as conexion:
            for n in range(sesiones):
                inicio = self._siguiente_momento()
                fin = inicio + timedelta(minutes=61)
                es_stream = n % 5 == 0
                estacion = self.estaciones[-1] if es_stream else self.estaciones[n % 5]
                venta = conexion.execute(
                    "INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen) VALUES (?, ?, ?, ?, ?, ?)",
                    (inicio.isoformat(timespec="seconds"), self.admin, dominio.TURNO_TARDE, 1500,
                     dominio.VENTA_CONFIRMADA, dominio.ORIGEN_ALQUILER_PCS),
                ).lastrowid
                sesion = conexion.execute(
                    "INSERT INTO sesiones_pc (estacion_id, fecha_inicio, fecha_fin_prevista, estado, fecha_fin_real) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (estacion, inicio.isoformat(timespec="seconds"), fin.isoformat(timespec="seconds"),
                     dominio.SESION_FINALIZADA, fin.isoformat(timespec="seconds")),
                ).lastrowid
                conexion.execute(
                    f"INSERT INTO {'sesion_pcstream_bonos' if es_stream else 'sesion_bonos'} "
                    "(sesion_id, bono_id, minutos, precio, venta_id) VALUES (?, ?, 60, 1500, ?)",
                    (sesion, self.bono_stream if es_stream else self.bono, venta),
                )
                if n % 4 == 0:
                    conexion.execute(
                        "INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id) "
                        "VALUES (?, ?, 60, ?, ?)",
                        (self.socio, dominio.MOVIMIENTO_CONSUMO, (inicio + timedelta(seconds=2)).isoformat(timespec="seconds"), sesion),
                    )
                if n % 10 == 0:
                    conexion.execute(
                        "INSERT INTO traslados_sesion (sesion_id, estacion_origen_id, estacion_destino_id, fecha, usuario_id) "
                        "VALUES (?, ?, ?, ?, ?)",
                        (sesion, self.estaciones[0], self.estaciones[1],
                         (inicio + timedelta(seconds=3)).isoformat(timespec="seconds"), self.admin),
                    )
                if n % 2 == 0:
                    conexion.execute(
                        "INSERT INTO eventos_admin_pc (estacion_id, fecha_hora, tipo) VALUES (?, ?, ?)",
                        (estacion, (inicio + timedelta(seconds=4)).isoformat(timespec="seconds"),
                         dominio.EVENTO_ADMIN_ACCESO),
                    )
                if n % 2 == 1:
                    conexion.execute(
                        "INSERT INTO bloqueos_filtro_pc (estacion_id, fecha_hora, palabra, titulo) VALUES (?, ?, ?, ?)",
                        (estacion, (inicio + timedelta(seconds=5)).isoformat(timespec="seconds"), "palabra", "Una página"),
                    )
                if n % 3 == 0:
                    inicio_consola = inicio + timedelta(seconds=30)
                    fin_consola = inicio_consola + timedelta(minutes=61)
                    venta_consola = conexion.execute(
                        "INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen) VALUES (?, ?, ?, ?, ?, ?)",
                        (inicio_consola.isoformat(timespec="seconds"), self.admin, dominio.TURNO_TARDE, 3000,
                         dominio.VENTA_CONFIRMADA, dominio.ORIGEN_PLAYSTATION),
                    ).lastrowid
                    sesion_consola = conexion.execute(
                        "INSERT INTO sesiones_playstation (fecha_inicio, fecha_fin_prevista, estado, fecha_fin_real) "
                        "VALUES (?, ?, ?, ?)",
                        (inicio_consola.isoformat(timespec="seconds"), fin_consola.isoformat(timespec="seconds"),
                         dominio.SESION_FINALIZADA, fin_consola.isoformat(timespec="seconds")),
                    ).lastrowid
                    conexion.execute(
                        "INSERT INTO sesion_playstation_bonos (sesion_id, bono_id, minutos, precio, venta_id) "
                        "VALUES (?, ?, 60, 3000, ?)",
                        (sesion_consola, self.bono_consola, venta_consola),
                    )

    @staticmethod
    def _trabajo(consulta):
        """Cuántos avisos de "llevo _INSTRUCCIONES_POR_AVISO instrucciones" da
        SQLite mientras corre `consulta()`."""
        avisos = [0]
        conectar_de_verdad = database.get_connection

        def conectar_contando():
            conexion = conectar_de_verdad()

            def contar():
                avisos[0] += 1
                return 0  # 0 = seguir

            conexion.set_progress_handler(contar, _INSTRUCCIONES_POR_AVISO)
            return conexion

        with mock.patch.object(database, "get_connection", conectar_contando):
            consulta()
        return avisos[0]

    _LO_QUE_PIDE_CADA_REFRESCO = (
        ("sesiones en curso", pcs_repo.estado_estaciones),
        ("panel de actividad", actividad_repo.actividad_reciente),
        ("actividad de la PlayStation 5", playstation_repo.eventos_recientes),
    )

    def test_con_cinco_veces_mas_historial_cada_refresco_trabaja_lo_mismo(self):
        self._sumar_historial(400)
        self._abrir_una_pc_ahora()
        con_poco = {nombre: self._trabajo(consulta) for nombre, consulta in self._LO_QUE_PIDE_CADA_REFRESCO}

        self._sumar_historial(1600)

        for nombre, consulta in self._LO_QUE_PIDE_CADA_REFRESCO:
            with self.subTest(nombre):
                # Un margen chico por si cambia algún detalle del plan de SQLite;
                # leyendo todo el historial, el trabajo se multiplicaría por ~5.
                self.assertLessEqual(self._trabajo(consulta), con_poco[nombre] * 1.25 + 10)

    def test_pedir_lo_ultimo_da_lo_mismo_que_pedir_todo_y_cortar(self):
        # Pocos eventos (los últimos) tienen que ser exactamente los primeros de la
        # lista completa: los bonos se ordenan por número de venta para no recorrer
        # la historia, y eso tiene que dar el mismo orden que la fecha.
        self._sumar_historial(60)
        self._abrir_una_pc_ahora()

        todos = actividad_repo.actividad_reciente(limite=100_000)
        for limite in (1, 5, 12, 30):
            with self.subTest(limite=limite):
                self.assertEqual(actividad_repo.actividad_reciente(limite=limite), todos[:limite])
        tipos_al_principio = {evento["tipo"] for evento in todos[:30]}
        self.assertIn("BONO", tipos_al_principio)


if __name__ == "__main__":
    import unittest
    unittest.main()
