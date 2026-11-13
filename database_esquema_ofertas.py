"""
database_esquema_ofertas.py
============================
Las ofertas 2x1 y 50% en los bonos (pedido del dueño, 2026-11-13; reglas en
control_pcs/repositories/ofertas_repo.py). En su propio archivo porque
database_esquema.py ya pasó las 600 líneas (CLAUDE.md, regla 12); la crea
database_esquema.inicializar_base_de_datos con CREATE TABLE IF NOT EXISTS: una
base vieja la recibe vacía, y lo que ya se vendió queda sin oferta.
"""

import dominio


def crear_tabla_ofertas(cursor, valores_sql):
    """Crea la tabla si todavía no existe. `valores_sql` es database._valores_sql
    (se recibe para no importar database desde acá, como en
    database_esquema_cajas)."""

    # Una fila por oferta. Nada se borra (regla 7): una oferta que ya no se
    # quiere se TERMINA (terminada_*) y queda en la lista.
    # - desde / hasta: días del local ("YYYY-MM-DD", de 06:00 a 06:00): la Noche
    #   del día `hasta` entra entera, aunque termine a la madrugada siguiente.
    # - franjas: JSON con los cuadritos de la semana, [[día, turno], ...]: día 0
    #   (lunes) a 6 (domingo) y el turno como en dominio.TURNOS. El domingo
    #   MAÑANA es "Domingo T1" y NOCHE es "Domingo T2" (turnos.calcular_turno).
    # - bonos: JSON con los bonos que toca, [[equipo, bono_id], ...]: el equipo
    #   (uno de dominio.EQUIPOS_CON_OFERTA) dice de qué catálogo es el bono, porque
    #   los ids de los tres catálogos se repiten.
    # - pausada: 1 mientras el Admin la tiene en pausa.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS ofertas (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre            TEXT NOT NULL,
            tipo              TEXT NOT NULL CHECK (tipo IN ({valores_sql(dominio.TIPOS_OFERTA)})),
            desde             TEXT NOT NULL,
            hasta             TEXT NOT NULL,
            franjas           TEXT NOT NULL,
            bonos             TEXT NOT NULL,
            pausada           INTEGER NOT NULL DEFAULT 0,
            creada_fecha      TEXT NOT NULL,
            creada_por        INTEGER NOT NULL REFERENCES usuarios(id),
            modificada_fecha  TEXT,
            modificada_por    INTEGER REFERENCES usuarios(id),
            terminada_fecha   TEXT,
            terminada_por     INTEGER REFERENCES usuarios(id)
        )
    """)
