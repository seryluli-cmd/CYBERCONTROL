"""
database_esquema_envios.py
===========================
La cola de los Cierres de Turno que se mandan a la app de gastos del dueño (la
PWA "Gastos — CyberBIOS"; pedido del dueño, 2026-10-26; reglas en
repositories/envio_pwa_repo.py). En su propio archivo porque
database_esquema.py ya pasó las 600 líneas (CLAUDE.md, regla 12); la crea
database_esquema.inicializar_base_de_datos con CREATE TABLE IF NOT EXISTS: una
base vieja la recibe vacía y ninguno de sus cierres anteriores se manda solo.
"""

import dominio


def crear_tabla_envios_pwa(cursor, valores_sql):
    """Crea la cola si todavía no existe. `valores_sql` es database._valores_sql
    (se recibe para no importar database desde acá, como en
    database_esquema_cajas)."""

    # Una fila por cierre que hay que mandar. Se encola en la MISMA transacción
    # que graba el cierre (turnos_repo.cerrar_turno), y solo si el envío estaba
    # prendido en ese momento.
    # - documento_id: el nombre del documento allá, fijo desde que se encola: un
    #   reintento pisa el mismo documento en vez de crear otro.
    # - estado / intentos / proximo_intento / ultimo_error: cómo va. Un envío que
    #   falló espera `intentos` minutos (hasta 60) antes de volver a probar.
    # - enviado_en: cuándo lo aceptó la app. Un ENVIADO no se vuelve a mandar.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS envios_pwa (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            cierre_id        INTEGER NOT NULL UNIQUE REFERENCES cierres_turno(id),
            documento_id     TEXT NOT NULL,
            estado           TEXT NOT NULL CHECK (estado IN ({valores_sql(dominio.ESTADOS_ENVIO_PWA)})),
            intentos         INTEGER NOT NULL DEFAULT 0,
            proximo_intento  TEXT,
            ultimo_error     TEXT,
            encolado_en      TEXT NOT NULL,
            enviado_en       TEXT
        )
    """)
    # El hilo busca los que faltan cada minuto: que no recorra los ya enviados.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_envios_pwa_estado ON envios_pwa(estado)")
