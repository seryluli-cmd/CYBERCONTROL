"""
tests/test_tareas_turno_cambios.py
===================================
TAREAS DEL TURNO (pedido del dueño, 2026-11-03): BORRAR y MODIFICAR una tarea (solo
el Administrador), y lo que se lee y se graba en la misma transacción.

- Borrar la deja BORRADA: deja de avisar y de verse, y lo que ya pasó sigue en el
  historial.
- Modificar no pierde lo de hoy, anota cómo era antes y, para lo que hoy no le
  tocaba, cuenta desde el minuto del cambio (como cargarla de nuevo).
- Un día que ya terminó se ve en el historial como pasó, no como quedó la tarea.

Las demás reglas, en tests/test_tareas_turno.py. Se ejecutan con:

    python -m unittest discover tests -p "test_tareas_turno*.py"
"""

import sqlite3
import threading
import time as reloj
import unittest
from datetime import timedelta
from unittest import mock

import database
import dominio
from database import conexion_db
from repositories import tareas_turno_repo as repo
from base_tareas_turno import ALGUNOS, LUCES, LUNES, MARTES, MIERCOLES, SOLO_HOY, TODOS, _ConTareas, _el


class TestBorrar(_ConTareas):
    def test_deja_de_avisar_y_de_verse_pero_la_fila_queda(self):
        tarea_id = self._crear(a_las=_el(LUNES, "08:00"))
        repo.borrar_tarea(self.admin_id, tarea_id, ahora=_el(MARTES, "12:00"))

        fila = self._fila("tareas_turno", tarea_id)
        self.assertEqual((fila["estado"], fila["borrada"], fila["borrada_por"]),
                         (dominio.TAREA_BORRADA, "2026-11-03T12:00:00", self.admin_id))
        self.assertEqual(self._avisos(_el(MARTES, "19:30")), [])
        self.assertEqual(repo.tareas_del_dia(MARTES, _el(MARTES, "19:30")), [])
        self.assertEqual(repo.listar_tareas(_el(MARTES, "19:30")), [])
        # El lunes, cuando todavía estaba, sigue en el historial.
        self.assertEqual([t["dia"] for t in repo.listar_historial(LUNES, MIERCOLES, ahora=_el(MIERCOLES, "10:00"))],
                         ["2026-11-02"])

        with self.assertRaisesRegex(ValueError, "ya estaba borrada"):
            repo.borrar_tarea(self.admin_id, tarea_id, ahora=_el(MARTES, "12:01"))
        for hacer in (lambda: repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "19:30")),
                      lambda: repo.posponer(self.lucia_id, tarea_id, MARTES, 5, ahora=_el(MARTES, "19:30")),
                      lambda: repo.modificar_tarea(self.admin_id, tarea_id, LUCES, "20:00", TODOS,
                                                   ahora=_el(MARTES, "19:30"))):
            with self.assertRaisesRegex(ValueError, "ya no está: la borró el Administrador"):
                hacer()

    def test_lo_que_ya_se_hizo_hoy_sigue_a_la_vista(self):
        tarea_id = self._crear()
        repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "19:31"))
        repo.borrar_tarea(self.admin_id, tarea_id, ahora=_el(MARTES, "19:40"))
        tarea, = repo.tareas_del_dia(MARTES, _el(MARTES, "19:41"))
        self.assertEqual((tarea["estado"], tarea["hecha_por"], tarea["borrada"]), (dominio.TAREA_HECHA, "Lucia", True))
        # Antes de borrarla, la misma tarea no venía como borrada.
        self.assertFalse(repo.tareas_del_dia(MARTES, _el(MARTES, "19:35"))[0]["borrada"])

    def test_borrada_a_la_noche_el_historial_no_pierde_lo_que_paso_ese_dia(self):
        # El martes Lucia la pospuso dos veces y nadie la hizo; a las 21:00 el Admin la
        # borra. Sale de la grilla de hoy, pero el martes sigue en el historial: NO SE
        # HIZO, con las dos posposiciones (cada POSPONER se ve en el HISTORIAL).
        tarea_id = self._crear(a_las=_el(LUNES, "08:00"))
        repo.posponer(self.lucia_id, tarea_id, MARTES, 10, ahora=_el(MARTES, "19:30"))
        repo.posponer(self.lucia_id, tarea_id, MARTES, 10, ahora=_el(MARTES, "19:40"))
        repo.borrar_tarea(self.admin_id, tarea_id, ahora=_el(MARTES, "21:00"))
        self.assertEqual(repo.tareas_del_dia(MARTES, _el(MARTES, "21:00")), [])
        self.assertEqual(self._avisos(_el(MARTES, "21:00")), [])

        historial = repo.listar_historial(LUNES, MARTES, ahora=_el(MIERCOLES, "10:00"))
        self.assertEqual([(t["dia"], t["estado"], t["veces_pospuesta"], t["borrada"]) for t in historial], [
            ("2026-11-03", dominio.TAREA_NO_SE_HIZO, 2, True),
            ("2026-11-02", dominio.TAREA_NO_SE_HIZO, 0, False),
        ])
        self.assertEqual([p["nombre"] for p in historial[0]["posposiciones"]], ["Lucia", "Lucia"])

    def test_una_que_no_existe(self):
        with self.assertRaisesRegex(ValueError, "no existe"):
            repo.borrar_tarea(self.admin_id, 999)


class TestModificar(_ConTareas):
    def test_no_pierde_lo_hecho_ni_lo_pospuesto_de_hoy(self):
        luces = self._crear()
        basura = self._crear("SACAR LA BASURA", "19:00")
        repo.marcar_hecha(self.gaby_id, basura, MARTES, ahora=_el(MARTES, "19:05"))
        repo.posponer(self.lucia_id, luces, MARTES, 10, ahora=_el(MARTES, "19:31"))

        ahora = _el(MARTES, "19:35")
        repo.modificar_tarea(self.admin_id, basura, "SACAR LA BASURA AL CONTENEDOR", "19:15", TODOS, ahora=ahora)
        repo.modificar_tarea(self.admin_id, luces, "PRENDER LAS LUCES", "19:20", TODOS, ahora=ahora)

        hecha, pospuesta = repo.tareas_del_dia(MARTES, ahora)
        self.assertEqual((hecha["texto"], hecha["estado"], hecha["hecha_por"]),
                         ("SACAR LA BASURA AL CONTENEDOR", dominio.TAREA_HECHA, "Gaby"))
        self.assertEqual((pospuesta["texto"], pospuesta["veces_pospuesta"], pospuesta["pospuesta_hasta"]),
                         ("PRENDER LAS LUCES", 1, "2026-11-03T19:41:00"))
        self.assertEqual(self._avisos(ahora), [])
        self.assertEqual(self._avisos(_el(MARTES, "19:41")), ["PRENDER LAS LUCES"])

    def test_anota_como_era_y_el_historial_la_muestra_como_era_ese_dia(self):
        tarea_id = self._crear("PRENDER LUCES", "19:30", a_las=_el(LUNES, "08:00"))
        repo.modificar_tarea(self.admin_id, tarea_id, LUCES, "20:00", ALGUNOS, [MARTES.weekday()],
                             ahora=_el(MARTES, "10:00"))

        with conexion_db() as conexion:
            cambio, = conexion.execute("SELECT * FROM tareas_turno_cambios").fetchall()
        self.assertEqual(
            (cambio["tarea_id"], cambio["fecha"], cambio["usuario_id"], cambio["texto"], cambio["hora"],
             cambio["repeticion"], cambio["dias_semana"], cambio["dia"]),
            (tarea_id, "2026-11-03T10:00:00", self.admin_id, "PRENDER LUCES", "19:30", TODOS, None, None),
        )
        historial = repo.listar_historial(LUNES, MARTES, ahora=_el(MIERCOLES, "21:00"))
        self.assertEqual([(t["dia"], t["texto"], t["hora"], t["se_repite"]) for t in historial], [
            ("2026-11-03", LUCES, "20:00", "Mar"),
            ("2026-11-02", "PRENDER LUCES", "19:30", "Todos los días"),
        ])
        # Hoy (miércoles) ya no le toca.
        self.assertEqual(self._avisos(_el(MIERCOLES, "21:00")), [])

    def test_sin_cambios_no_anota_nada(self):
        tarea_id = self._crear()
        repo.modificar_tarea(self.admin_id, tarea_id, f"  {LUCES} ", "1930", TODOS, [2], ahora=_el(MARTES, "10:00"))
        with conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM tareas_turno_cambios").fetchone()[0], 0)

    def test_valida_igual_que_al_cargar(self):
        tarea_id = self._crear()
        ahora = _el(MARTES, "10:00")
        with self.assertRaisesRegex(ValueError, "Escribí qué hay que hacer"):
            repo.modificar_tarea(self.admin_id, tarea_id, "  ", "19:30", TODOS, ahora=ahora)
        with self.assertRaisesRegex(ValueError, "No entiendo la hora"):
            repo.modificar_tarea(self.admin_id, tarea_id, LUCES, "25:00", TODOS, ahora=ahora)
        with self.assertRaisesRegex(ValueError, "no existe"):
            repo.modificar_tarea(self.admin_id, 999, LUCES, "19:30", TODOS, ahora=ahora)
        self.assertEqual(repo.listar_tareas(ahora)[0]["hora"], "19:30")

    def test_a_solo_hoy_con_la_hora_pasada_solo_si_hoy_ya_le_tocaba(self):
        jueves = self._crear("LIMPIAR LA HELADERA", "10:00", ALGUNOS, [3], a_las=_el(LUNES, "08:00"))
        todos = self._crear("ABRIR LA PERSIANA", "07:00", a_las=_el(LUNES, "08:00"))
        ahora = _el(MARTES, "12:00")
        # Hoy no le tocaba: SOLO HOY a las 10:00 nunca avisaría.
        with self.assertRaisesRegex(ValueError, "Las 10:00 de hoy ya pasaron"):
            repo.modificar_tarea(self.admin_id, jueves, "LIMPIAR LA HELADERA", "10:00", SOLO_HOY, ahora=ahora)
        # Hoy sí le tocaba (y no se hizo): queda de hoy, atrasada.
        repo.modificar_tarea(self.admin_id, todos, "ABRIR LA PERSIANA", "07:00", SOLO_HOY, ahora=ahora)
        self.assertEqual(self._fila("tareas_turno", todos)["dia"], "2026-11-03")
        self.assertEqual(self._avisos(ahora), ["ABRIR LA PERSIANA"])
        self.assertEqual(self._avisos(_el(MIERCOLES, "08:00")), [])

    def test_pasarla_a_todos_los_dias_con_su_hora_pasada_cuenta_desde_manana(self):
        # Como cargarla: la de las 18:00 de los lunes y miércoles, pasada a TODOS LOS
        # DÍAS el martes a las 21:00, no salta el martes ni queda como NO SE HIZO.
        tarea_id = self._crear("SACAR LA BASURA", "18:00", ALGUNOS, [0, 2], a_las=_el(LUNES, "08:00"))
        ahora = _el(MARTES, "21:00")
        repo.modificar_tarea(self.admin_id, tarea_id, "SACAR LA BASURA", "18:00", TODOS, ahora=ahora)

        self.assertEqual(repo.tareas_del_dia(MARTES, ahora), [])
        self.assertEqual(self._avisos(ahora), [])
        self.assertEqual(repo.cuantas_atrasadas(ahora), 0)
        self.assertEqual(self._avisos(_el(MIERCOLES, "18:00")), ["SACAR LA BASURA"])
        self.assertEqual(self._avisos(_el(MIERCOLES + timedelta(days=1), "18:00")), ["SACAR LA BASURA"])
        historial = repo.listar_historial(LUNES, MIERCOLES, ahora=_el(MIERCOLES + timedelta(days=1), "10:00"))
        self.assertEqual([(t["dia"], t["estado"]) for t in historial], [
            ("2026-11-04", dominio.TAREA_NO_SE_HIZO),
            ("2026-11-02", dominio.TAREA_NO_SE_HIZO),
        ])

    def test_corregir_una_atrasada_de_hoy_la_deja_atrasada(self):
        # Hoy ya le tocaba: corregirle el texto (o la hora) no la calla.
        luces = self._crear()
        persiana = self._crear("BAJAR LA PERSIANA", "22:00")
        ahora = _el(MARTES, "21:00")
        repo.modificar_tarea(self.admin_id, luces, "PRENDER LAS LUCES", "19:30", TODOS, ahora=ahora)
        repo.modificar_tarea(self.admin_id, persiana, "BAJAR LA PERSIANA", "20:00", TODOS, ahora=ahora)

        self.assertEqual([(t["texto"], t["estado"], t["minutos_de_atraso"]) for t in repo.tareas_del_dia(MARTES, ahora)],
                         [("PRENDER LAS LUCES", dominio.TAREA_ATRASADA, 90),
                          ("BAJAR LA PERSIANA", dominio.TAREA_ATRASADA, 60)])
        self.assertEqual(self._avisos(ahora), ["PRENDER LAS LUCES", "BAJAR LA PERSIANA"])

    def test_cambiarle_los_dias_a_la_noche_no_borra_del_historial_lo_de_ese_dia(self):
        # Pospuesta dos veces el martes, y a las 21:00 pasa a lunes y miércoles: sale de
        # la grilla del martes, pero el martes sigue en el historial como pasó.
        tarea_id = self._crear(a_las=_el(LUNES, "08:00"))
        repo.posponer(self.lucia_id, tarea_id, MARTES, 10, ahora=_el(MARTES, "19:30"))
        repo.posponer(self.lucia_id, tarea_id, MARTES, 10, ahora=_el(MARTES, "19:40"))
        repo.modificar_tarea(self.admin_id, tarea_id, LUCES, "19:30", ALGUNOS, [0, 2], ahora=_el(MARTES, "21:00"))
        self.assertEqual(repo.tareas_del_dia(MARTES, _el(MARTES, "21:00")), [])

        del_martes, = repo.listar_historial(MARTES, MARTES, ahora=_el(MIERCOLES, "10:00"))
        self.assertEqual(
            (del_martes["hora"], del_martes["estado"], del_martes["veces_pospuesta"], del_martes["borrada"],
             del_martes["se_repite"]),
            ("19:30", dominio.TAREA_NO_SE_HIZO, 2, False, "Todos los días"))

    def test_la_hecha_queda_en_el_historial_con_la_hora_que_tenia_cuando_la_hicieron(self):
        # La de las 23:00, hecha a las 23:05 y pasada a las 02:00 a las 23:30: el martes
        # se hizo la de las 23:00 (no la de las 02:00, que recién toca de madrugada).
        tarea_id = self._crear("CERRAR LA PERSIANA", "23:00", a_las=_el(LUNES, "08:00"))
        repo.marcar_hecha(self.gaby_id, tarea_id, MARTES, ahora=_el(MARTES, "23:05"))
        repo.modificar_tarea(self.admin_id, tarea_id, "CERRAR LA PERSIANA", "02:00", TODOS, ahora=_el(MARTES, "23:30"))
        # Hoy sigue HECHA (no vuelve a avisar a las 02:00).
        self.assertEqual(self._avisos(_el(MIERCOLES, "02:30")), [])

        del_martes, = repo.listar_historial(MARTES, MARTES, ahora=_el(MIERCOLES, "10:00"))
        self.assertEqual((del_martes["hora"], del_martes["estado"], del_martes["hecha_en"]),
                         ("23:00", dominio.TAREA_HECHA, "2026-11-03T23:05:00"))

    def test_si_falla_a_mitad_de_camino_no_cambia_nada(self):
        tarea_id = self._crear()
        original = repo._anotar_cambio

        def anota_y_falla(*argumentos):
            original(*argumentos)  # el cambio y la tarea ya escritos, como la base ocupada al final
            raise sqlite3.OperationalError("database is locked")

        with mock.patch.object(repo, "_anotar_cambio", side_effect=anota_y_falla):
            with self.assertRaises(sqlite3.OperationalError):
                repo.modificar_tarea(self.admin_id, tarea_id, "OTRA COSA", "20:00", TODOS, ahora=_el(MARTES, "10:00"))
        fila = self._fila("tareas_turno", tarea_id)
        self.assertEqual((fila["texto"], fila["hora"]), (LUCES, "19:30"))
        with conexion_db() as conexion:
            self.assertEqual(conexion.execute("SELECT COUNT(*) FROM tareas_turno_cambios").fetchone()[0], 0)


class TestOtraConexionALaVez(_ConTareas):
    """Hoy todo lo escribe el hilo de Qt del mostrador, pero lo que se lee y lo que se
    graba van en la misma transacción (regla 8, BEGIN IMMEDIATE): si algún día otra
    conexión escribe estas tablas, la segunda espera a la primera y ve lo que hizo."""

    def _mientras_otra_escribe(self, escribir, hacer) -> dict:
        """`escribir(otra)` en otra conexión con el permiso de escritura tomado y,
        mientras, `hacer()` en un hilo, que tiene que esperar a que la otra termine.
        Devuelve {"valor": ...} o {"error": ...}."""
        otra = sqlite3.connect(database.DB_PATH, isolation_level=None)
        resultado = {}

        def en_el_hilo():
            try:
                resultado["valor"] = hacer()
            except Exception as error:
                resultado["error"] = error

        try:
            otra.execute("BEGIN IMMEDIATE")
            escribir(otra)
            hilo = threading.Thread(target=en_el_hilo)
            hilo.start()
            reloj.sleep(0.5)  # el hilo queda esperando el permiso de escritura
            otra.execute("COMMIT")
            hilo.join(10)
        finally:
            otra.close()
        return resultado

    def test_marcar_hecha_ve_la_que_se_grabo_mientras_esperaba(self):
        tarea_id = self._crear()
        resultado = self._mientras_otra_escribe(
            lambda otra: otra.execute(
                "INSERT INTO tareas_turno_marcas (tarea_id, dia, accion, usuario_id, fecha) VALUES (?, ?, ?, ?, ?)",
                (tarea_id, "2026-11-03", dominio.ACCION_TAREA_HECHA, self.gaby_id, "2026-11-03T19:30:00")),
            lambda: repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "19:31")))
        # Sin el BEGIN IMMEDIATE no la veía y chocaba con el índice único (IntegrityError).
        self.assertIsInstance(resultado.get("error"), ValueError)
        self.assertIn("la marcó Gaby a las 19:30", str(resultado["error"]))
        self.assertEqual(len(self._marcas()), 1)

    def test_modificar_anota_como_era_despues_de_lo_que_grabo_la_otra(self):
        tarea_id = self._crear()
        resultado = self._mientras_otra_escribe(
            lambda otra: otra.execute("UPDATE tareas_turno SET texto = ? WHERE id = ?", ("PRENDER LAS LUCES", tarea_id)),
            lambda: repo.modificar_tarea(self.admin_id, tarea_id, "PRENDER LAS LUCES", "20:00", TODOS,
                                         ahora=_el(MARTES, "10:00")))
        self.assertNotIn("error", resultado)
        # Sin el BEGIN IMMEDIATE quedaba anotado un "antes" que ya no era.
        with conexion_db() as conexion:
            cambio, = conexion.execute("SELECT texto, hora FROM tareas_turno_cambios").fetchall()
        self.assertEqual(tuple(cambio), ("PRENDER LAS LUCES", "19:30"))


if __name__ == "__main__":
    unittest.main()
