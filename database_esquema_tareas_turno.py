"""
database_esquema_tareas_turno.py
=================================
Las TAREAS DEL TURNO (pedido del dueño, 2026-11-03; reglas en
repositories/tareas_turno_repo.py): cosas para hacer a una hora, como "PRENDER
LAS LUCES DE AFUERA" a las 19:30. En archivo aparte, como las ofertas.
Las crea database_esquema.inicializar_base_de_datos con CREATE TABLE IF NOT
EXISTS: son tablas nuevas, no cambian ninguna que ya estuviera, así que una base
vieja las recibe vacías sin paso de migración (un CyberBios viejo las ignora).
"""

import dominio


def crear_tablas_tareas_turno(cursor, valores_sql):
    """Crea las tres tablas si todavía no existen. `valores_sql` es
    database._valores_sql (se recibe para no importar database desde acá, como en
    database_esquema_ofertas)."""

    # Una tarea cargada por el Admin.
    # - texto: lo que hay que hacer, con las mayúsculas como lo escribió
    #   (dominio.revisar_tarea).
    # - hora: "HH:MM" (dominio.hora_de_tarea). Antes de las 06:00 es la madrugada
    #   del día siguiente: la Noche del día del local (turnos.momento_de_la_tarea).
    # - repeticion: todos los días, algunos días de la semana (dias_semana, "0,2,4"
    #   con 0 = lunes) o un solo día (dia, "YYYY-MM-DD", el día del local en que se
    #   cargó). Cada columna está si y solo si su repetición la usa.
    # - creada / creada_por: cuándo y quién la cargó. Una vez que toca antes de
    #   `creada` no cuenta: la de las 18:00 cargada a las 19:00 avisa desde mañana.
    # - borrada / borrada_por: quién la sacó (nunca se borra la fila, regla 7).
    # Lo que tenía antes de cada MODIFICAR queda en tareas_turno_cambios.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS tareas_turno (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            texto        TEXT NOT NULL,
            hora         TEXT NOT NULL CHECK (hora GLOB '[0-2][0-9]:[0-5][0-9]'),
            repeticion   TEXT NOT NULL CHECK (repeticion IN ({valores_sql(dominio.REPETICIONES_TAREA)})),
            dias_semana  TEXT,
            dia          TEXT,
            estado       TEXT NOT NULL CHECK (estado IN ({valores_sql(dominio.ESTADOS_TAREA)})),
            creada       TEXT NOT NULL,
            creada_por   INTEGER NOT NULL REFERENCES usuarios(id),
            borrada      TEXT,
            borrada_por  INTEGER REFERENCES usuarios(id),
            CHECK ((repeticion = {valores_sql((dominio.TAREA_ALGUNOS_DIAS,))}) = (dias_semana IS NOT NULL)),
            CHECK ((repeticion = {valores_sql((dominio.TAREA_UN_SOLO_DIA,))}) = (dia IS NOT NULL)),
            CHECK ((estado = {valores_sql((dominio.TAREA_BORRADA,))}) = (borrada IS NOT NULL))
        )
    """)

    # Cada MODIFICAR deja acá cómo era la tarea ANTES del cambio, con quién y
    # cuándo la cambió. Con esto el historial de un día viejo muestra la tarea
    # como era ese día (otra hora, otro texto u otros días), y lo hecho o
    # pospuesto no se pierde: va por el número de la tarea, que no cambia.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tareas_turno_cambios (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            tarea_id     INTEGER NOT NULL REFERENCES tareas_turno(id),
            fecha        TEXT NOT NULL,
            usuario_id   INTEGER NOT NULL REFERENCES usuarios(id),
            texto        TEXT NOT NULL,
            hora         TEXT NOT NULL,
            repeticion   TEXT NOT NULL,
            dias_semana  TEXT,
            dia          TEXT
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_tareas_turno_cambios_tarea ON tareas_turno_cambios(tarea_id, fecha)"
    )

    # Lo que pasó con cada vez que una tarea tocó (la tarea y el DÍA DEL LOCAL):
    # HECHA (quién y a qué hora) o POSPUESTA (quién, cuándo y por cuántos
    # minutos: una fila por cada vez, así el historial dice cuántas veces y quiénes).
    # Los minutos van si y solo si es POSPUESTA, y solo los de las teclas del aviso.
    minutos = ", ".join(str(int(m)) for m in dominio.MINUTOS_PARA_POSPONER)
    pospuesta = valores_sql((dominio.ACCION_TAREA_POSPUESTA,))
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS tareas_turno_marcas (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            tarea_id    INTEGER NOT NULL REFERENCES tareas_turno(id),
            dia         TEXT NOT NULL,
            accion      TEXT NOT NULL CHECK (accion IN ({valores_sql(dominio.ACCIONES_TAREA)})),
            minutos     INTEGER CHECK (minutos IS NULL OR minutos IN ({minutos})),
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id),
            fecha       TEXT NOT NULL,
            CHECK ((accion = {pospuesta}) = (minutos IS NOT NULL))
        )
    """)
    # HECHA, una sola vez por tarea y día. Lo revisa el repo (marcar_hecha, dentro
    # de su BEGIN IMMEDIATE); esto es la última defensa ante un camino que se saltee
    # el repo. El valor va escrito porque el WHERE de un índice no acepta
    # parámetros, pero sale de dominio.
    cursor.execute(f"""
        CREATE UNIQUE INDEX IF NOT EXISTS idx_tareas_turno_una_hecha
        ON tareas_turno_marcas(tarea_id, dia)
        WHERE accion = {valores_sql((dominio.ACCION_TAREA_HECHA,))}
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_tareas_turno_marcas_dia ON tareas_turno_marcas(dia)")
