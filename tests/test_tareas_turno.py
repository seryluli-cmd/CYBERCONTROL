"""
tests/test_tareas_turno.py
===========================
TAREAS DEL TURNO (pedido del dueño, 2026-11-03): cosas para hacer a una hora
("PRENDER LAS LUCES DE AFUERA" a las 19:30).

- Las carga, modifica y borra solo un Administrador; HECHA y POSPONER, cualquier
  operador habilitado.
- Se repiten todos los días, algunos días de la semana o solo hoy, siempre por el
  día del local (de 06:00 a 06:00): la de las 02:00 es de la Noche del día.
- A su hora avisa; POSPONER 5 o 10 la calla esos minutos y después vuelve, hasta
  que alguien pone HECHA (una sola vez por día).
- Cargada después de su hora, hoy no cuenta; lo de días anteriores no avisa y
  queda en el historial como NO SE HIZO.
- Borrar y modificar, en tests/test_tareas_turno_cambios.py.

Acá van las reglas de adentro, con la base (repositories/tareas_turno_repo.py);
las cuentas puras de dominio.py y turnos.momento_de_la_tarea, en
tests/test_tareas_turno_cuentas.py. Se ejecutan con:

    python -m unittest discover tests -p "test_tareas_turno*.py"
"""

import sqlite3
import unittest
from datetime import date, timedelta

import database
import dominio
from database import conexion_db
from repositories import tareas_turno_repo as repo
from repositories import usuarios_repo
from base_tareas_turno import (
    ALGUNOS, LUCES, LUNES, MARTES, MIERCOLES, SOLO_HOY, TODOS, _ConTareas, _el,
)


class TestQuienPuede(_ConTareas):
    def test_la_empleada_no_carga_ni_modifica_ni_borra(self):
        tarea_id = self._crear()
        ahora = _el(MARTES, "09:00")
        with self.assertRaisesRegex(PermissionError, "Solo un Administrador"):
            repo.crear_tarea(self.lucia_id, "BARRER LA VEREDA", "10:00", TODOS, ahora=ahora)
        with self.assertRaisesRegex(PermissionError, "Solo un Administrador"):
            repo.modificar_tarea(self.lucia_id, tarea_id, "OTRA COSA", "20:00", TODOS, ahora=ahora)
        with self.assertRaisesRegex(PermissionError, "Solo un Administrador"):
            repo.borrar_tarea(self.gaby_id, tarea_id, ahora=ahora)

        tarea, = repo.listar_tareas(ahora)
        self.assertEqual((tarea["texto"], tarea["hora"]), (LUCES, "19:30"))

    def test_un_admin_dado_de_baja_no_sigue_cargando(self):
        otro_admin = usuarios_repo.crear_usuario("Dueño", "1234", dominio.ROL_ADMIN)
        usuarios_repo.desactivar_usuario(otro_admin)
        with self.assertRaisesRegex(PermissionError, "ya no está habilitado"):
            repo.crear_tarea(otro_admin, LUCES, "19:30", TODOS, ahora=_el(MARTES, "09:00"))
        self.assertEqual(repo.listar_tareas(_el(MARTES, "09:00")), [])

    def test_cualquier_operador_la_marca_hecha_o_la_pospone(self):
        luces = self._crear()
        basura = self._crear("SACAR LA BASURA", "19:00")
        ahora = _el(MARTES, "19:31")
        repo.posponer(self.lucia_id, luces, MARTES, 5, ahora=ahora)
        repo.marcar_hecha(self.gaby_id, basura, MARTES, ahora=ahora)
        self.assertEqual(self._del_dia(MARTES, ahora), [
            ("SACAR LA BASURA", dominio.TAREA_HECHA), (LUCES, dominio.TAREA_ATRASADA),
        ])

    def test_uno_dado_de_baja_o_que_no_existe_no_marca_ni_pospone(self):
        tarea_id = self._crear()
        usuarios_repo.desactivar_usuario(self.gaby_id)
        ahora = _el(MARTES, "19:31")
        for quien in (self.gaby_id, 999, None):
            with self.subTest(quien=quien):
                with self.assertRaisesRegex(PermissionError, "ya no está habilitado"):
                    repo.marcar_hecha(quien, tarea_id, MARTES, ahora=ahora)
                with self.assertRaisesRegex(PermissionError, "ya no está habilitado"):
                    repo.posponer(quien, tarea_id, MARTES, 5, ahora=ahora)
        self.assertEqual(self._marcas(), [])
        self.assertEqual(self._avisos(ahora), [LUCES])


class TestCadaRepeticion(_ConTareas):
    def test_todos_los_dias_toca_cada_dia(self):
        self._crear()
        for dias in range(8):
            dia = MARTES + timedelta(days=dias)
            with self.subTest(dia=dia):
                self.assertEqual(self._avisos(_el(dia, "19:30")), [LUCES])

    def test_elegir_dias_toca_solo_los_dias_elegidos(self):
        # Lunes, miércoles y viernes; elegidos desordenados y uno repetido.
        tarea_id = self._crear("LIMPIAR LA HELADERA", "10:00", ALGUNOS, [4, 0, 2, 0], a_las=_el(LUNES, "08:00"))
        for dias in range(7):
            dia = LUNES + timedelta(days=dias)
            with self.subTest(dia=dia):
                toca = dia.weekday() in (0, 2, 4)
                self.assertEqual(self._avisos(_el(dia, "10:00")), ["LIMPIAR LA HELADERA"] if toca else [])
        tarea, = repo.listar_tareas(_el(LUNES, "09:00"))
        self.assertEqual((tarea["repeticion"], tarea["dias_semana"], tarea["se_repite"]),
                         (ALGUNOS, (0, 2, 4), "Lun · Mié · Vie"))
        self.assertEqual(self._fila("tareas_turno", tarea_id)["dias_semana"], "0,2,4")

    def test_elegir_dias_sin_ningun_dia_no_se_carga(self):
        for dias in (None, [], [7], [-1], [True], ["lunes"]):
            with self.subTest(dias=dias):
                with self.assertRaises(ValueError):
                    self._crear(repeticion=ALGUNOS, dias=dias)
        self.assertEqual(repo.listar_tareas(_el(MARTES, "09:00")), [])

    def test_con_los_siete_dias_es_todos_los_dias(self):
        self._crear(repeticion=ALGUNOS, dias=range(7))
        tarea, = repo.listar_tareas(_el(MARTES, "09:00"))
        self.assertEqual((tarea["repeticion"], tarea["dias_semana"], tarea["se_repite"]), (TODOS, (), "Todos los días"))

    def test_solo_hoy_toca_solo_el_dia_en_que_se_cargo(self):
        tarea_id = self._crear("PAGAR LA LUZ", "11:00", SOLO_HOY, dias=[3])  # los días no cuentan acá
        fila = self._fila("tareas_turno", tarea_id)
        self.assertEqual((fila["dia"], fila["dias_semana"]), ("2026-11-03", None))
        self.assertEqual(self._avisos(_el(MARTES, "11:00")), ["PAGAR LA LUZ"])
        self.assertEqual(self._avisos(_el(MIERCOLES, "11:00")), [])
        self.assertEqual(repo.tareas_del_dia(MIERCOLES, _el(MIERCOLES, "11:00")), [])
        tarea, = repo.listar_tareas(_el(MARTES, "12:00"))
        self.assertEqual(tarea["se_repite"], "Solo el martes 03/11")
        # Al otro día ya no está en TODAS LAS TAREAS: quedó en el historial.
        self.assertEqual(repo.listar_tareas(_el(MIERCOLES, "08:00")), [])

    def test_solo_hoy_con_una_hora_que_ya_paso_no_se_carga(self):
        with self.assertRaisesRegex(ValueError, "Las 07:00 de hoy ya pasaron"):
            self._crear(hora="07:00", repeticion=SOLO_HOY)
        # La misma hora en que se carga sí (es para ahora), y la de la madrugada
        # es de la Noche de hoy: todavía no pasó.
        self._crear("ABRIR LA PERSIANA", "08:00", SOLO_HOY, a_las=_el(MARTES, "08:00:40"))
        self._crear("CONTAR LAS GASEOSAS", "02:00", SOLO_HOY, a_las=_el(MARTES, "20:00"))
        self.assertEqual([t["texto"] for t in repo.listar_tareas(_el(MARTES, "20:00"))],
                         ["ABRIR LA PERSIANA", "CONTAR LAS GASEOSAS"])

    def test_una_repeticion_que_no_existe_no_se_carga(self):
        with self.assertRaisesRegex(ValueError, "Elegí cuándo se repite"):
            self._crear(repeticion="CADA TANTO")


class TestLaNoche(_ConTareas):
    def test_la_de_las_dos_es_de_la_noche_del_dia_y_pasa_al_dia_siguiente(self):
        lunes = _el(LUNES, "08:00")
        self._crear("CERRAR LA PERSIANA", "23:00", a_las=lunes)
        self._crear("SACAR LA BASURA", "02:00", a_las=lunes)
        abrir = self._crear("ABRIR LA PERSIANA", "06:00", a_las=lunes)
        repo.marcar_hecha(self.lucia_id, abrir, MARTES, ahora=_el(MARTES, "06:05"))

        del_martes = repo.tareas_del_dia(MARTES, _el(MARTES, "20:00"))
        self.assertEqual([(t["texto"], t["momento"], t["turno"]) for t in del_martes], [
            ("ABRIR LA PERSIANA", "2026-11-03T06:00:00", dominio.TURNO_MANANA),
            ("CERRAR LA PERSIANA", "2026-11-03T23:00:00", dominio.TURNO_NOCHE),
            ("SACAR LA BASURA", "2026-11-04T02:00:00", dominio.TURNO_NOCHE),
        ])
        # El miércoles a la 01:00 es todavía la Noche del martes.
        self.assertEqual(self._avisos(_el(MIERCOLES, "01:00")), ["CERRAR LA PERSIANA"])
        self.assertEqual(self._avisos(_el(MIERCOLES, "02:00")), ["CERRAR LA PERSIANA", "SACAR LA BASURA"])
        self.assertEqual(self._avisos(_el(MIERCOLES, "05:59")), ["CERRAR LA PERSIANA", "SACAR LA BASURA"])
        # A las 06:00 empieza el miércoles: lo de la Noche del martes ya no avisa.
        self.assertEqual(self._avisos(_el(MIERCOLES, "06:00")), ["ABRIR LA PERSIANA"])

    def test_elegir_dias_mira_el_dia_del_local_y_no_el_del_calendario(self):
        # "Los martes a las 02:00" es la Noche del martes: pasa el miércoles de
        # madrugada, y la madrugada del martes (Noche del lunes) no toca.
        self._crear("SACAR LA BASURA", "02:00", ALGUNOS, [MARTES.weekday()], a_las=_el(LUNES, "08:00"))
        self.assertEqual(self._avisos(_el(MARTES, "02:30")), [])
        self.assertEqual(self._avisos(_el(MIERCOLES, "02:30")), ["SACAR LA BASURA"])

    def test_hecha_de_madrugada_queda_en_el_dia_de_la_noche(self):
        tarea_id = self._crear("SACAR LA BASURA", "02:00")
        repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MIERCOLES, "02:10"))
        self.assertEqual(self._marcas(), [
            (tarea_id, "2026-11-03", dominio.ACCION_TAREA_HECHA, None, self.lucia_id, "2026-11-04T02:10:00"),
        ])
        self.assertEqual(self._avisos(_el(MIERCOLES, "03:00")), [])

    def test_solo_hoy_de_madrugada_es_del_dia_que_empezo_ayer(self):
        # A la 01:00 del miércoles el día del local es el martes.
        tarea_id = self._crear("CONTAR LAS GASEOSAS", "03:00", SOLO_HOY, a_las=_el(MIERCOLES, "01:00"))
        self.assertEqual(self._fila("tareas_turno", tarea_id)["dia"], "2026-11-03")
        self.assertEqual(self._avisos(_el(MIERCOLES, "03:00")), ["CONTAR LAS GASEOSAS"])
        # Las 10:00 de ese día ya pasaron, y el cartel explica por qué.
        with self.assertRaisesRegex(ValueError, "hasta las 06:00 sigue siendo el día que empezó ayer"):
            self._crear("PAGAR LA LUZ", "10:00", SOLO_HOY, a_las=_el(MIERCOLES, "01:00"))


class TestEstados(_ConTareas):
    def test_mas_tarde_pronto_y_atrasada_con_sus_minutos(self):
        self._crear()
        casos = (
            ("18:00:00", dominio.TAREA_MAS_TARDE, 0, 90),
            ("19:00:00", dominio.TAREA_MAS_TARDE, 0, 30),
            ("19:00:01", dominio.TAREA_PRONTO, 0, 30),
            ("19:12:30", dominio.TAREA_PRONTO, 0, 18),  # 17 min y medio: "EN 18 MIN"
            ("19:29:59", dominio.TAREA_PRONTO, 0, 1),
            ("19:30:00", dominio.TAREA_ATRASADA, 0, 0),
            ("20:42:59", dominio.TAREA_ATRASADA, 72, 0),
        )
        for hora, estado, atraso, faltan in casos:
            with self.subTest(hora=hora):
                tarea, = repo.tareas_del_dia(MARTES, _el(MARTES, hora))
                self.assertEqual((tarea["estado"], tarea["minutos_de_atraso"], tarea["minutos_que_faltan"]),
                                 (estado, atraso, faltan))
        self.assertEqual(dominio.texto_minutos(72), "1 h 12 min")

    def test_sin_dia_es_el_de_hoy_del_local(self):
        self._crear("SACAR LA BASURA", "02:00")
        hoy, = repo.tareas_del_dia(None, _el(MIERCOLES, "01:00"))
        self.assertEqual(hoy["dia"], "2026-11-03")

    def test_el_dia_va_como_dia_y_no_como_momento(self):
        with self.assertRaises(TypeError):
            repo.tareas_del_dia(_el(MIERCOLES, "02:00"), _el(MIERCOLES, "02:00"))

    def test_los_numeros_de_la_cabecera(self):
        luces = self._crear()
        self._crear("SACAR LA BASURA", "19:00")
        self._crear("CERRAR LA PERSIANA", "23:00")
        self._crear("BARRER LA VEREDA", "12:00")
        repo.marcar_hecha(self.lucia_id, luces, MARTES, ahora=_el(MARTES, "19:10"))
        tareas = repo.tareas_del_dia(MARTES, _el(MARTES, "19:45"))
        self.assertEqual(dominio.numeros_de_las_tareas(tareas), {"para_hacer": 1, "atrasadas": 2, "hechas": 1})
        self.assertEqual(repo.cuantas_atrasadas(_el(MARTES, "19:45")), 2)


class TestElAviso(_ConTareas):
    def test_salta_a_su_hora_y_no_antes(self):
        self._crear()
        self.assertEqual(self._avisos(_el(MARTES, "19:29:59")), [])
        self.assertEqual(self._avisos(_el(MARTES, "19:30")), [LUCES])
        self.assertEqual(self._avisos(_el(MARTES, "23:00")), [LUCES])

    def test_si_tocan_dos_a_la_vez_salen_de_a_una_en_orden(self):
        self._crear("SACAR LA BASURA", "19:30")
        self._crear(LUCES, "19:30")
        self._crear("REGAR LAS PLANTAS", "19:00")
        self.assertEqual(self._avisos(_el(MARTES, "19:45")), ["REGAR LAS PLANTAS", LUCES, "SACAR LA BASURA"])

    def test_posponer_la_calla_esos_minutos_y_despues_vuelve_hasta_que_la_hacen(self):
        tarea_id = self._crear()

        hasta = repo.posponer(self.lucia_id, tarea_id, MARTES, 5, ahora=_el(MARTES, "19:30:10"))
        self.assertEqual(hasta, "2026-11-03T19:35:10")
        self.assertEqual(self._avisos(_el(MARTES, "19:35:09")), [])
        self.assertEqual(self._avisos(_el(MARTES, "19:35:10")), [LUCES])

        repo.posponer(self.gaby_id, tarea_id, MARTES, 10, ahora=_el(MARTES, "19:36"))
        self.assertEqual(self._avisos(_el(MARTES, "19:45:59")), [])
        self.assertEqual(self._avisos(_el(MARTES, "19:46")), [LUCES])
        # Pospuesta sigue atrasada: el botón de la barra la cuenta.
        self.assertEqual(repo.cuantas_atrasadas(_el(MARTES, "19:40")), 1)

        tarea, = repo.tareas_del_dia(MARTES, _el(MARTES, "19:50"))
        self.assertEqual((tarea["veces_pospuesta"], tarea["pospuesta_hasta"]), (2, "2026-11-03T19:46:00"))
        self.assertEqual([(p["nombre"], p["fecha"], p["minutos"]) for p in tarea["posposiciones"]], [
            ("Lucia", "2026-11-03T19:30:10", 5),
            ("Gaby", "2026-11-03T19:36:00", 10),
        ])

        repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "19:50"))
        for hora in ("19:51", "22:00", "05:00"):
            with self.subTest(hora=hora):
                dia = MIERCOLES if hora < "06:00" else MARTES
                self.assertEqual(self._avisos(_el(dia, hora)), [])
        self.assertEqual(repo.cuantas_atrasadas(_el(MARTES, "19:51")), 0)

    def test_se_pospone_solo_cinco_o_diez_minutos(self):
        tarea_id = self._crear()
        self.assertEqual(dominio.MINUTOS_PARA_POSPONER, (5, 10))
        for minutos in (7, 0, 15, -5, True, "5", None):
            with self.subTest(minutos=minutos):
                with self.assertRaisesRegex(ValueError, "Se pospone 5 o 10 minutos"):
                    repo.posponer(self.lucia_id, tarea_id, MARTES, minutos, ahora=_el(MARTES, "19:31"))
        self.assertEqual(self._marcas(), [])

    def test_hecha_antes_de_su_hora_no_avisa(self):
        tarea_id = self._crear()
        repo.marcar_hecha(self.gaby_id, tarea_id, MARTES, ahora=_el(MARTES, "19:20"))
        self.assertEqual(self._avisos(_el(MARTES, "19:30")), [])
        tarea, = repo.tareas_del_dia(MARTES, _el(MARTES, "19:30"))
        self.assertEqual((tarea["estado"], tarea["hecha_por"], tarea["hecha_en"]),
                         (dominio.TAREA_HECHA, "Gaby", "2026-11-03T19:20:00"))


class TestHecha(_ConTareas):
    def test_queda_con_quien_y_a_que_hora(self):
        tarea_id = self._crear()
        repo.marcar_hecha(self.gaby_id, tarea_id, "2026-11-03", ahora=_el(MARTES, "19:32:15"))
        tarea, = repo.tareas_del_dia(MARTES, _el(MARTES, "20:00"))
        self.assertEqual((tarea["estado"], tarea["hecha_por"], tarea["hecha_por_id"], tarea["hecha_en"]),
                         (dominio.TAREA_HECHA, "Gaby", self.gaby_id, "2026-11-03T19:32:15"))

    def test_una_sola_vez_por_dia(self):
        tarea_id = self._crear()
        repo.marcar_hecha(self.gaby_id, tarea_id, MARTES, ahora=_el(MARTES, "19:32"))
        with self.assertRaisesRegex(ValueError, "ya está hecha: la marcó Gaby a las 19:32"):
            repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "19:33"))
        with self.assertRaisesRegex(ValueError, "ya está hecha"):
            repo.posponer(self.lucia_id, tarea_id, MARTES, 5, ahora=_el(MARTES, "19:33"))
        self.assertEqual(len(self._marcas()), 1)
        # Y la base tampoco deja dos.
        with self.assertRaises(sqlite3.IntegrityError):
            with conexion_db() as conexion:
                conexion.execute(
                    "INSERT INTO tareas_turno_marcas (tarea_id, dia, accion, usuario_id, fecha) VALUES (?, ?, ?, ?, ?)",
                    (tarea_id, "2026-11-03", dominio.ACCION_TAREA_HECHA, self.lucia_id, "2026-11-03T19:40:00"),
                )

    def test_al_otro_dia_vuelve_a_tocar(self):
        tarea_id = self._crear()
        repo.marcar_hecha(self.gaby_id, tarea_id, MARTES, ahora=_el(MARTES, "19:32"))
        self.assertEqual(self._avisos(_el(MIERCOLES, "19:30")), [LUCES])
        repo.marcar_hecha(self.gaby_id, tarea_id, MIERCOLES, ahora=_el(MIERCOLES, "19:31"))
        self.assertEqual(len(self._marcas()), 2)

    def test_solo_el_dia_de_hoy_o_el_de_ayer(self):
        tarea_id = self._crear(a_las=_el(LUNES, "08:00"))
        ahora = _el(MIERCOLES, "06:01")
        with self.assertRaisesRegex(ValueError, "todavía no empezó"):
            repo.marcar_hecha(self.lucia_id, tarea_id, MIERCOLES + timedelta(days=1), ahora=ahora)
        with self.assertRaisesRegex(ValueError, "ya terminó"):
            repo.marcar_hecha(self.lucia_id, tarea_id, LUNES, ahora=ahora)
        with self.assertRaisesRegex(ValueError, "ya terminó"):
            repo.posponer(self.lucia_id, tarea_id, LUNES, 5, ahora=ahora)
        # El aviso de la Noche se puede contestar pasadas las 06:00.
        repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=ahora)
        del_martes, = repo.listar_historial(MARTES, MARTES, ahora=ahora)
        self.assertEqual((del_martes["estado"], del_martes["hecha_en"]), (dominio.TAREA_HECHA, "2026-11-04T06:01:00"))

    def test_un_dia_que_no_le_toca_no_se_marca(self):
        tarea_id = self._crear("LIMPIAR LA HELADERA", "10:00", ALGUNOS, [MIERCOLES.weekday()])
        with self.assertRaisesRegex(ValueError, "no toca ese día"):
            repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "10:00"))
        with self.assertRaisesRegex(ValueError, "no existe"):
            repo.marcar_hecha(self.lucia_id, 999, MARTES, ahora=_el(MARTES, "10:00"))
        self.assertEqual(self._marcas(), [])


class TestCargadaDespuesDeSuHora(_ConTareas):
    def test_la_de_las_18_cargada_a_las_19_avisa_desde_manana(self):
        tarea_id = self._crear("BAJAR EL TOLDO", "18:00", a_las=_el(MARTES, "19:00"))
        self.assertEqual(self._avisos(_el(MARTES, "19:01")), [])
        self.assertEqual(repo.tareas_del_dia(MARTES, _el(MARTES, "19:01")), [])
        self.assertEqual(repo.cuantas_atrasadas(_el(MARTES, "19:01")), 0)
        with self.assertRaisesRegex(ValueError, "no toca ese día"):
            repo.marcar_hecha(self.lucia_id, tarea_id, MARTES, ahora=_el(MARTES, "19:01"))
        self.assertEqual(self._avisos(_el(MIERCOLES, "18:00")), ["BAJAR EL TOLDO"])
        # Ni el martes queda en el historial como que no se hizo.
        self.assertEqual(repo.listar_historial(MARTES, MARTES, ahora=_el(MIERCOLES, "18:00")), [])

    def test_cargada_dentro_del_mismo_minuto_es_para_ahora(self):
        self._crear("BAJAR EL TOLDO", "19:00", a_las=_el(MARTES, "19:00:40"))
        self.assertEqual(self._avisos(_el(MARTES, "19:00:41")), ["BAJAR EL TOLDO"])

    def test_la_de_la_madrugada_cargada_a_la_noche_es_de_esa_noche(self):
        self._crear("SACAR LA BASURA", "02:00", a_las=_el(MARTES, "23:00"))
        self.assertEqual(self._avisos(_el(MIERCOLES, "02:00")), ["SACAR LA BASURA"])


class TestDiasAnteriores(_ConTareas):
    def test_lo_de_ayer_no_avisa_hoy_y_queda_como_no_se_hizo(self):
        self._crear(a_las=_el(LUNES, "08:00"))
        self.assertEqual(self._avisos(_el(MARTES, "08:00")), [])
        tarea, = repo.tareas_del_dia(LUNES, _el(MARTES, "08:00"))
        self.assertEqual(tarea["estado"], dominio.TAREA_NO_SE_HIZO)

    def test_el_historial_dice_quien_la_hizo_o_que_no_se_hizo_y_quienes_la_pospusieron(self):
        luces = self._crear(a_las=_el(LUNES, "08:00"))
        self._crear("SACAR LA BASURA", "02:00", a_las=_el(LUNES, "08:00"))
        # Lunes: las luces, pospuestas por Lucia y hechas por Gaby; la basura, no.
        repo.posponer(self.lucia_id, luces, LUNES, 5, ahora=_el(LUNES, "19:30"))
        repo.marcar_hecha(self.gaby_id, luces, LUNES, ahora=_el(LUNES, "19:37"))
        # Martes: nada.
        ahora = _el(MIERCOLES, "10:00")

        historial = repo.listar_historial(LUNES, MIERCOLES, ahora=ahora)

        self.assertEqual([(t["dia"], t["hora"], t["texto"], t["estado"], t["hecha_por"]) for t in historial], [
            ("2026-11-03", "19:30", LUCES, dominio.TAREA_NO_SE_HIZO, None),
            ("2026-11-03", "02:00", "SACAR LA BASURA", dominio.TAREA_NO_SE_HIZO, None),
            ("2026-11-02", "19:30", LUCES, dominio.TAREA_HECHA, "Gaby"),
            ("2026-11-02", "02:00", "SACAR LA BASURA", dominio.TAREA_NO_SE_HIZO, None),
        ])
        hecha = historial[2]
        self.assertEqual((hecha["hecha_en"], hecha["veces_pospuesta"]), ("2026-11-02T19:37:00", 1))
        self.assertEqual([p["nombre"] for p in hecha["posposiciones"]], ["Lucia"])

    def test_pospuesta_mas_alla_de_las_seis_ya_no_vuelve_y_queda_no_se_hizo(self):
        # La de las 05:50 es de la Noche del martes. Pospuesta 10 minutos a las 05:55,
        # su "hasta" (06:05) ya es del miércoles: no vuelve a avisar (los avisos son
        # solo del día en curso). El aviso lo dice antes (minutos_que_no_vuelven).
        tarea_id = self._crear("CONTAR CIGARRILLOS", "05:50")
        self.assertEqual(self._avisos(_el(MIERCOLES, "05:50")), ["CONTAR CIGARRILLOS"])
        hasta = repo.posponer(self.lucia_id, tarea_id, MARTES, 10, ahora=_el(MIERCOLES, "05:55"))
        self.assertEqual(hasta, "2026-11-04T06:05:00")

        self.assertEqual(self._avisos(_el(MIERCOLES, "06:05")), [])
        self.assertEqual(repo.cuantas_atrasadas(_el(MIERCOLES, "06:05")), 0)
        del_martes, = repo.listar_historial(MARTES, MARTES, ahora=_el(MIERCOLES, "06:05"))
        self.assertEqual((del_martes["estado"], del_martes["veces_pospuesta"]), (dominio.TAREA_NO_SE_HIZO, 1))

    def test_cuales_minutos_de_posponer_ya_no_vuelven(self):
        casos = (
            ("05:40:00", 0, ()),
            ("05:50:00", 0, (10,)),       # 06:00 en punto ya es el miércoles
            ("05:49:50", 15, (10,)),      # 05:59:50, y la revisión siguiente puede ser 06:00:05
            ("05:49:50", 0, ()),
            ("05:55:00", 0, (5, 10)),
            ("06:01:00", 0, (5, 10)),     # el aviso de la Noche contestado ya en el miércoles
        )
        for hora, margen, no_vuelven in casos:
            with self.subTest(hora=hora, margen=margen):
                self.assertEqual(repo.minutos_que_no_vuelven(MARTES, _el(MIERCOLES, hora), margen), no_vuelven)
        self.assertEqual(repo.minutos_que_no_vuelven("2026-11-03", _el(MARTES, "19:30")), ())

    def test_el_historial_no_trae_el_dia_de_hoy_ni_dias_vacios(self):
        self._crear(a_las=_el(LUNES, "08:00"))
        ahora = _el(MARTES, "20:00")
        self.assertEqual([t["dia"] for t in repo.listar_historial(LUNES - timedelta(days=400), MARTES, ahora=ahora)],
                         ["2026-11-02"])
        self.assertEqual(repo.listar_historial(MARTES, LUNES, ahora=ahora), [])
        self.assertEqual(repo.listar_historial(date(2026, 10, 1), date(2026, 10, 31), ahora=ahora), [])


class TestListarTareas(_ConTareas):
    def test_en_el_orden_del_turno_con_su_se_repite(self):
        self._crear("SACAR LA BASURA", "02:00")
        self._crear("ABRIR LA PERSIANA", "06:00")
        self._crear("CONTAR EL CAMBIO", "05:59")
        self._crear("PAGAR LA LUZ", "23:00", SOLO_HOY)
        self._crear(LUCES, "19:30", ALGUNOS, [0, 4])
        borrada = self._crear("REGAR", "10:00")
        repo.borrar_tarea(self.admin_id, borrada, ahora=_el(MARTES, "09:00"))

        tareas = repo.listar_tareas(_el(MARTES, "09:00"))

        self.assertEqual([(t["hora"], t["texto"], t["turno"], t["se_repite"]) for t in tareas], [
            ("06:00", "ABRIR LA PERSIANA", dominio.TURNO_MANANA, "Todos los días"),
            ("19:30", LUCES, dominio.TURNO_TARDE, "Lun · Vie"),
            ("23:00", "PAGAR LA LUZ", dominio.TURNO_NOCHE, "Solo el martes 03/11"),
            ("02:00", "SACAR LA BASURA", dominio.TURNO_NOCHE, "Todos los días"),
            ("05:59", "CONTAR EL CAMBIO", dominio.TURNO_NOCHE, "Todos los días"),
        ])
        self.assertEqual((tareas[0]["creada"], tareas[0]["creada_por"]), ("2026-11-03T08:00:00", "Sergio"))

    def test_el_texto_queda_como_lo_escribieron(self):
        tarea_id = self._crear("  prender   las Luces​  ")
        self.assertEqual(self._fila("tareas_turno", tarea_id)["texto"], "prender las Luces")


class TestLaBase(_ConTareas):
    def _insertar_tarea(self, conexion, **cambios):
        valores = {"texto": LUCES, "hora": "19:30", "repeticion": TODOS, "dias_semana": None, "dia": None,
                   "estado": dominio.TAREA_ACTIVA, "creada": "2026-11-03T08:00:00", "creada_por": self.admin_id,
                   "borrada": None}
        valores.update(cambios)
        columnas = ", ".join(valores)
        return conexion.execute(
            f"INSERT INTO tareas_turno ({columnas}) VALUES ({', '.join('?' for _ in valores)})", tuple(valores.values())
        ).lastrowid

    def test_los_valores_tienen_que_ser_los_de_dominio(self):
        malos = (
            {"repeticion": "TODOS LOS DIAS"},
            {"estado": "BORRADO"},
            {"hora": "7:30"},
            {"repeticion": ALGUNOS},                    # sin días
            {"dias_semana": "0,2"},                     # días con todos los días
            {"repeticion": SOLO_HOY},                   # sin el día
            {"estado": dominio.TAREA_BORRADA},          # borrada sin cuándo
        )
        for cambios in malos:
            with self.subTest(cambios=cambios):
                with self.assertRaises(sqlite3.IntegrityError):
                    with conexion_db() as conexion:
                        self._insertar_tarea(conexion, **cambios)

    def test_las_marcas_tambien(self):
        with conexion_db() as conexion:
            tarea_id = self._insertar_tarea(conexion)
        malas = (
            ("HECHO", None),
            (dominio.ACCION_TAREA_POSPUESTA, 7),
            (dominio.ACCION_TAREA_POSPUESTA, None),
            (dominio.ACCION_TAREA_HECHA, 5),
        )
        for accion, minutos in malas:
            with self.subTest(accion=accion, minutos=minutos):
                with self.assertRaises(sqlite3.IntegrityError):
                    with conexion_db() as conexion:
                        conexion.execute(
                            "INSERT INTO tareas_turno_marcas (tarea_id, dia, accion, minutos, usuario_id, fecha) "
                            "VALUES (?, ?, ?, ?, ?, ?)",
                            (tarea_id, "2026-11-03", accion, minutos, self.lucia_id, "2026-11-03T19:30:00"),
                        )

    def test_una_base_vieja_sin_las_tablas_las_recibe_al_inicializar(self):
        # Como la base del local antes del 2026-11-19: con datos, sin las tres tablas.
        with conexion_db() as conexion:
            for tabla in ("tareas_turno_marcas", "tareas_turno_cambios", "tareas_turno"):
                conexion.execute(f"DROP TABLE {tabla}")

        database.inicializar_base_de_datos()

        with conexion_db() as conexion:
            nombres = {fila["name"] for fila in conexion.execute("SELECT name FROM sqlite_master")}
        self.assertTrue({"tareas_turno", "tareas_turno_cambios", "tareas_turno_marcas",
                         "idx_tareas_turno_una_hecha", "idx_tareas_turno_marcas_dia",
                         "idx_tareas_turno_cambios_tarea"} <= nombres)
        self.assertEqual(usuarios_repo.obtener_usuario(self.lucia_id)["nombre"], "Lucia")
        self.assertIsInstance(self._crear(), int)


if __name__ == "__main__":
    unittest.main()
