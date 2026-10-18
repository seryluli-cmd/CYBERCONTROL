"""
database_esquema_cajas.py
==========================
Las tablas de las cajas con número (pedido del dueño, 2026-10-18). Viven en un
archivo aparte porque database_esquema.py ya pasaba las 600 líneas (CLAUDE.md,
regla 12); las crea database_esquema.inicializar_base_de_datos.

Una caja es lo que tiene a cargo UNA persona por vez: se abre contando el cambio
del cajón, puede pasar de mano en un relevo (quien llega cuenta todo el cajón) y
se cierra con el Cierre de Turno de siempre (cierres_turno). Todo se agrega con
CREATE TABLE IF NOT EXISTS: una base vieja recibe las tablas vacías y sus
ventas y cierres anteriores quedan tal cual, sin caja (ver relevo_repo).

Lo que se vende NO se le suma a la caja por estas tablas: la plata de un cierre
sigue saliendo de la ventana entre cierres (turnos_repo). `ventas_caja` es el
número de caja de cada venta y, si la cobró el Admin, quién apretó el botón.
"""

import dominio


def crear_tablas_de_cajas(cursor, valores_sql):
    """Crea las tablas e índices de las cajas si todavía no existen.
    `valores_sql` es database._valores_sql (se recibe para no importar database
    desde acá: database_esquema ya lo tiene a mano)."""

    # Una fila por caja; su id ES el número de caja que se ve en pantalla.
    # - fecha/turno: el turno al que pertenece, decidido al ABRIRLA con la
    #   tolerancia de turnos.turno_que_arranca_tras_un_cierre. Es lo que va a
    #   quedar anotado en su cierre.
    # - cambio_esperado: lo que tendría que haber en el cajón al abrir (lo que
    #   dejó la caja anterior, o el Cambio Fijo).
    # - cambio_contado: lo que contó quien la abrió. NULL = no contó, porque
    #   la abrió la misma persona que acaba de cerrar la anterior (su reemplazo
    #   no llegó): arranca con lo que ella misma dejó.
    # - responsable_id: quién la tiene AHORA. Cambia con un relevo.
    # - cierre_id: NULL mientras está abierta. Solo puede haber una abierta.
    # - cierre_forzoso: 1 si la cerró el programa solo, a los 15 minutos del
    #   fin del turno (turnos.MINUTOS_PARA_CIERRE_FORZOSO).
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS cajas (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha            TEXT NOT NULL,
            turno            TEXT NOT NULL CHECK (turno IN ({valores_sql(dominio.TURNOS)})),
            abierta_por      INTEGER NOT NULL REFERENCES usuarios(id),
            abierta_en       TEXT NOT NULL,
            cambio_esperado  REAL NOT NULL,
            cambio_contado   REAL,
            responsable_id   INTEGER NOT NULL REFERENCES usuarios(id),
            cierre_id        INTEGER REFERENCES cierres_turno(id),
            cierre_forzoso   INTEGER NOT NULL DEFAULT 0
        )
    """)

    # Cada vez que una caja pasa de mano sin cerrarse (el reemplazo llegó tarde
    # y recibe la caja de quien la cubrió): quien la recibe cuenta TODO el cajón
    # y queda lo que tendría que haber, lo que contó y la diferencia.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS relevos_caja (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            caja_id         INTEGER NOT NULL REFERENCES cajas(id),
            fecha           TEXT NOT NULL,
            de_usuario_id   INTEGER NOT NULL REFERENCES usuarios(id),
            a_usuario_id    INTEGER NOT NULL REFERENCES usuarios(id),
            monto_esperado  REAL NOT NULL,
            monto_contado   REAL NOT NULL,
            diferencia      REAL NOT NULL
        )
    """)

    # En qué caja quedó cada venta. Tabla aparte (y no una columna de "ventas")
    # a propósito: "ventas" es la tabla madre de la plata y reconstruirla tiene
    # su propia receta (database_migraciones._migrar_check_origen_en_ventas);
    # una columna nueva ahí obligaba a tocar esa migración y sus pruebas.
    # cargada_por: quién apretó cobrar cuando no fue la responsable (el Admin
    # que vende con la caja de la empleada abierta: la venta queda a nombre de
    # ella, pedido del dueño 2026-10-18). NULL = la cobró la misma responsable.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ventas_caja (
            venta_id     INTEGER PRIMARY KEY REFERENCES ventas(id),
            caja_id      INTEGER NOT NULL REFERENCES cajas(id),
            cargada_por  INTEGER REFERENCES usuarios(id)
        )
    """)

    # Cada vez que el dueño carga lo que contó en el sobre de un cierre. El
    # último conteo sigue también en cierres_turno (monto_contado, diferencia),
    # que es lo que leen las pantallas; acá quedan todos, para que corregir un
    # conteo no borre el anterior.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS verificaciones_cierre (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            cierre_id       INTEGER NOT NULL REFERENCES cierres_turno(id),
            monto_contado   REAL NOT NULL,
            diferencia      REAL NOT NULL,
            verificado_por  INTEGER NOT NULL REFERENCES usuarios(id),
            fecha           TEXT NOT NULL
        )
    """)

    # Buscar la caja abierta pasa en cada venta y cada 10 s en la pantalla
    # principal: tiene que ser un atajo, no recorrer todas las cajas.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cajas_cierre ON cajas(cierre_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_relevos_caja ON relevos_caja(caja_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ventas_caja_caja ON ventas_caja(caja_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_verificaciones_cierre ON verificaciones_cierre(cierre_id)")
