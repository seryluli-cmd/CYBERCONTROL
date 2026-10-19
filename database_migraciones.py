"""Migraciones idempotentes de bases SQLite existentes."""

import sqlite3

import dominio
import database
from database import (
    _sql_tabla_ventas, _origenes_venta_sql, _valores_sql,
    _respaldar_antes_de_migrar,
)


# --------------------------------------------------------------------
# Migraciones
# --------------------------------------------------------------------
# Cada _migrar_* es idempotente (segura de correr en cada arranque) y se llama
# desde inicializar_base_de_datos() justo después del CREATE TABLE que le
# corresponde. Hacen falta porque CREATE TABLE IF NOT EXISTS no toca una tabla
# que ya existe: una base creada antes de un cambio de esquema se quedaría con
# el esquema viejo (ver CLAUDE.md, regla 6).

def _agregar_columna_si_falta(conexion: sqlite3.Connection, tabla: str, columna: str, definicion: str) -> bool:
    """
    ALTER TABLE ... ADD COLUMN, solo si la tabla todavía no tiene esa columna.
    Devuelve True si la agregó, para las migraciones que además tienen que
    rellenar algo esa primera vez (ver _migrar_columna_origen_en_ventas).
    No hace commit: lo hace cada migración al terminar.
    """
    columnas_actuales = {fila["name"] for fila in conexion.execute(f"PRAGMA table_info({tabla})")}
    if columna in columnas_actuales:
        return False
    conexion.execute(f"ALTER TABLE {tabla} ADD COLUMN {columna} {definicion}")
    return True


def _migrar_columnas_permisos(conexion: sqlite3.Connection):
    """
    Agrega a "usuarios" las columnas "permiso_*" que falten (ver
    usuarios_repo.PERMISOS_EMPLEADA), para una base creada antes de que
    existiera cada permiso. Al sumar un permiso nuevo hay que agregarlo en
    este listado Y en el CREATE TABLE.
    """
    for columna in (
        "permiso_articulos", "permiso_compras", "permiso_consulta_ventas",
        "permiso_reportes", "permiso_control_cierres", "permiso_control_pcs",
    ):
        _agregar_columna_si_falta(conexion, "usuarios", columna, "INTEGER NOT NULL DEFAULT 0")
    conexion.commit()


def _migrar_columna_ultima_conexion_estaciones(conexion: sqlite3.Connection):
    """
    Para una base creada antes de que el Cliente PC reportara su propio
    "estoy vivo" (ver servidor_red.py): agrega estaciones.ultima_conexion.
    """
    _agregar_columna_si_falta(conexion, "estaciones", "ultima_conexion", "TEXT")
    conexion.commit()


def _migrar_columna_ultima_ip_estaciones(conexion: sqlite3.Connection):
    """
    Agrega estaciones.ultima_ip: la IP LAN desde la que llegó el último
    GET /estado de esa estación (servidor_red.py la saca de
    self.client_address, no la manda el Cliente PC). Es lo que usa el botón
    "Traer IP" de Gestionar Estaciones -- solo tiene valor una vez que la
    estación ya existe en esta tabla Y el Cliente PC de esa PC hizo al menos
    un pedido después de creada (una estación recién tipeada y todavía no
    guardada no tiene fila que actualizar).
    """
    _agregar_columna_si_falta(conexion, "estaciones", "ultima_ip", "TEXT")
    conexion.commit()


def _migrar_columna_ip_asentada_estaciones(conexion: sqlite3.Connection):
    """
    Agrega estaciones.ip_asentada: la IP desde la que esa PC se enlazó POR
    PRIMERA VEZ (pedido del dueño, 2026-10-17). A diferencia de ultima_ip no se
    pisa en cada conexión: queda fija hasta que el Admin la borra en Gestionar
    Estaciones. Sirve para reconocer a la PC por su IP cuando el nombre que
    manda su Cliente PC no coincide con ninguna estación (ver
    pcs_repo.estado_de_estacion). Arranca vacía: cada PC la asienta sola en su
    próxima consulta.
    """
    _agregar_columna_si_falta(conexion, "estaciones", "ip_asentada", "TEXT")
    conexion.commit()


def _migrar_columna_cliente_cerrado_desde_estaciones(conexion: sqlite3.Connection):
    """
    Agrega estaciones.cliente_cerrado_desde: desde cuándo la PC está sin
    Cliente PC porque alguien lo cerró desde su panel admin (NULL = no).
    Lo pone accesos_admin_pc_repo.registrar_evento y lo limpia
    registrar_regreso_del_cliente cuando la PC vuelve a conectarse. Vive en
    `estaciones` (y no se deduce del historial de eventos) para que
    pcs_repo.estado_estaciones, que ya lee esa fila, lo tenga sin una
    consulta más.
    """
    _agregar_columna_si_falta(conexion, "estaciones", "cliente_cerrado_desde", "TEXT")
    conexion.commit()


def _migrar_columnas_actualizacion_estaciones(conexion: sqlite3.Connection):
    """
    Agrega a `estaciones` lo que cuenta el Cliente PC de su actualización desde el
    Servidor (pedido del dueño, 2026-10-18; ver actualizacion_cliente_repo):
    `version_cliente` (la versión instalada; NULL = un Cliente PC sin actualización
    automática), `carpeta_cliente` (dónde está instalado), `estado_actualizacion`
    (uno de dominio.ESTADOS_ACTUALIZACION_CLIENTE, o vacío) y `detalle_actualizacion`
    (el texto que manda la PC). Arrancan vacías: cada PC las completa en su próxima
    consulta.
    """
    _agregar_columna_si_falta(conexion, "estaciones", "version_cliente", "INTEGER")
    _agregar_columna_si_falta(conexion, "estaciones", "carpeta_cliente", "TEXT")
    _agregar_columna_si_falta(conexion, "estaciones", "estado_actualizacion", "TEXT")
    _agregar_columna_si_falta(conexion, "estaciones", "detalle_actualizacion", "TEXT")
    conexion.commit()


def _migrar_columna_cliente_arranque_estaciones(conexion: sqlite3.Connection):
    """
    Agrega estaciones.cliente_arranque (pedido del dueño, 2026-10-19): el
    `arranque` que mandó el Cliente PC de esa estación en su última consulta, o
    sea qué programa abierto era (ver CLIENTE PC/pulso.py). Si el que llega
    después de un corte es otro, el Cliente PC se cerró y se volvió a abrir
    (ver cortes_pc_repo). Arranca vacía: cada PC la completa en su próxima
    consulta; un Cliente PC viejo no la manda y queda vacía.
    """
    _agregar_columna_si_falta(conexion, "estaciones", "cliente_arranque", "TEXT")
    conexion.commit()


def _migrar_columna_miembro_en_sesiones(conexion: sqlite3.Connection):
    """
    Para una base creada antes de que existiera "Miembros": agrega
    sesiones_pc.miembro_id (NULL = sesión de bono/walk-in, como siempre
    fue; con valor = sesión abierta con el saldo de ese socio).
    """
    _agregar_columna_si_falta(conexion, "sesiones_pc", "miembro_id", "INTEGER REFERENCES miembros(id)")
    conexion.commit()


def _migrar_columna_whatsapp_en_miembros(conexion: sqlite3.Connection):
    """
    Agrega miembros.whatsapp (pedido del dueño, 2026-10-17: el socio lo carga,
    opcional, la primera vez que entra desde una PC; ver
    miembros_repo.abrir_estacion_por_miembro). Cadena vacía = no lo dio, igual
    que dni/telefono: esas columnas ya eran NOT NULL y cambiarlas obligaría a
    reconstruir `miembros`, que es tabla madre (ver "Trampas conocidas" en
    CLAUDE.md), así que "sin dato" es '' en las tres.
    """
    _agregar_columna_si_falta(conexion, "miembros", "whatsapp", "TEXT NOT NULL DEFAULT ''")
    conexion.commit()


def _migrar_columna_desde_ip_en_sesiones(conexion: sqlite3.Connection):
    """
    Agrega sesiones.desde_ip (2026-10-18): la IP de la otra PC cuando el
    Administrador entra desde otra PC del local (ver admin_remoto_repo); NULL =
    entró en el mostrador, como todos los ingresos de antes. Se ve en Accesos de
    Admin y deja afuera esos ingresos de la pista de quién estaba en el mostrador
    (turnos_faltantes_repo._responsables_del_mes).
    """
    _agregar_columna_si_falta(conexion, "sesiones", "desde_ip", "TEXT")
    conexion.commit()


# --- Reconstruir una tabla (cambiar un CHECK o un REFERENCES) ---

# Columnas de movimientos_saldo_miembro, para copiarlas al reconstruir la tabla.
_COLUMNAS_MOVIMIENTOS_SALDO = (
    "id", "miembro_id", "tipo", "minutos", "fecha", "venta_id", "bono_id", "sesion_id",
)

# Tipos de movimiento del ledger de saldo de socios (el CHECK de "tipo"). Los
# "originales" son los del primer esquema; ANULACION se sumó después.
_TIPOS_MOVIMIENTO_SALDO_ORIGINALES = ("CARGA", "CONSUMO", "REINTEGRO")
_TIPOS_MOVIMIENTO_SALDO = dominio.TIPOS_MOVIMIENTO_SALDO


def _sql_tabla_movimientos_saldo_miembro(tipos: tuple, referencia_bono: str, si_no_existe: bool = False) -> str:
    """
    El CREATE TABLE de movimientos_saldo_miembro, escrito una sola vez. Lo
    usa inicializar_base_de_datos() con el esquema actual y las dos
    migraciones de abajo, que reconstruyen la tabla de una base vieja
    (SQLite no deja cambiar un CHECK ni un REFERENCES ya grabados). Lo único
    que cambió con el tiempo es qué `tipos` admite el CHECK y a qué catálogo
    apunta `referencia_bono`: "bonos_miembro(id)" hoy, "bonos_tiempo(id)" en
    las bases anteriores a que existiera bonos_miembro.
    """
    tipos_sql = _valores_sql(tipos)
    existe = "IF NOT EXISTS " if si_no_existe else ""
    return f"""
        CREATE TABLE {existe}movimientos_saldo_miembro (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
            tipo        TEXT NOT NULL CHECK (tipo IN ({tipos_sql})),
            minutos     INTEGER NOT NULL,
            fecha       TEXT NOT NULL,
            venta_id    INTEGER REFERENCES ventas(id),
            bono_id     INTEGER REFERENCES {referencia_bono},
            sesion_id   INTEGER REFERENCES sesiones_pc(id)
        )
    """


def _reconstruir_tabla(conexion: sqlite3.Connection, tabla: str, columnas: tuple, ya_esta_al_dia, sql_tabla_nueva):
    """
    Esqueleto común de las migraciones que reconstruyen una tabla: renombrar
    la vieja, crear la nueva con el esquema correcto, copiar las filas tal
    cual (`columnas`) y borrar la vieja. Es la única forma que soporta
    SQLite de cambiar un CHECK o un REFERENCES ya grabados. Mira la
    definición guardada en sqlite_master para saber si hace falta, así que
    es segura de correr en cada arranque y no hace nada en una base nueva.

    - `ya_esta_al_dia(sql_actual)`: True si esa definición ya tiene el cambio.
    - `sql_tabla_nueva(sql_actual)`: el CREATE TABLE de la tabla reconstruida
      (recibe la definición vieja por si tiene que conservar algo de ella).

    Reconstruir una tabla borra los índices que tenía: hay que recrearlos
    después (con CREATE INDEX IF NOT EXISTS, más adelante en
    inicializar_base_de_datos).

    Dos casos borde, para que la migración nunca deje datos históricos
    afuera:

    1. **Corte a mitad de camino.** Si el programa se cierra (por ejemplo,
       un corte de luz) entre el RENAME y el final de la copia, el
       próximo arranque ve la tabla recreada pero VACÍA -- la recrea el
       CREATE TABLE IF NOT EXISTS de inicializar_base_de_datos(), que corre
       antes que las migraciones -- con el historial real atrapado en
       "<tabla>_viejo". Por eso no alcanza con preguntar "¿ya está al día?":
       también se chequea si quedó una "_viejo" pendiente, y se la termina
       de absorber.
    2. **Referencias heredadas que ya no existen.** Con foreign_keys en ON,
       copiar una fila cuyo REFERENCES ya no apunta a nada vigente (por
       ejemplo un bono_id de movimientos_saldo_miembro que no está en
       bonos_miembro) rompía la migración entera a mitad de la copia. Por
       eso el chequeo de FK se apaga SOLO durante esta copia de datos
       históricos (nunca en el uso normal): conservar la fila aunque ya no
       apunte a nada vigente es mejor que perderla.
    """
    tabla_vieja = f"{tabla}_viejo"
    tabla_vieja_pendiente = conexion.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name = ?", (tabla_vieja,)
    ).fetchone() is not None

    definicion = conexion.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (tabla,)
    ).fetchone()
    if definicion is None:
        return  # base nueva: la tabla ni existe todavía, nada que migrar

    sql_actual = definicion["sql"]
    al_dia = ya_esta_al_dia(sql_actual)
    if al_dia and not tabla_vieja_pendiente:
        return  # ya se migró en un arranque anterior, sin cortes de por medio

    if not al_dia:
        conexion.execute(f"ALTER TABLE {tabla} RENAME TO {tabla_vieja}")
        conexion.execute(sql_tabla_nueva(sql_actual))

    # A este punto "<tabla>_viejo" existe siempre -- recién renombrada
    # arriba, o ya estaba de un corte anterior (ver punto 1). Se copia con FK
    # apagado (punto 2) y con INSERT OR IGNORE: si el corte anterior pasó
    # DESPUÉS de copiar pero ANTES de borrar la vieja, algunas filas ya están
    # de las dos veces y no hace falta duplicarlas ni romper por choque de
    # "id".
    #
    # "PRAGMA foreign_keys" es un no-op silencioso si queda una transacción
    # pendiente (por ejemplo, si quien llamó a esta función venía de hacer
    # un INSERT propio sin comitear todavía, como en un test) -- por eso se
    # comitea antes de tocarlo, para no apagar el chequeo "en el papel" y
    # que la FK siga rompiendo igual.
    lista_columnas = ", ".join(columnas)
    conexion.commit()
    conexion.execute("PRAGMA foreign_keys = OFF")
    try:
        conexion.execute(
            f"INSERT OR IGNORE INTO {tabla} ({lista_columnas}) SELECT {lista_columnas} FROM {tabla_vieja}"
        )
        conexion.execute(f"DROP TABLE {tabla_vieja}")
        conexion.commit()
    finally:
        conexion.execute("PRAGMA foreign_keys = ON")


def _admite_todos_los_tipos(tipos: tuple):
    """
    La función `ya_esta_al_dia` de las migraciones que agregan valores al
    CHECK (tipo IN (...)) de una tabla: True si la definición guardada ya
    admite TODOS los `tipos`. Mirar solo el último que se sumó dejaba sin
    migrar a las bases ya existentes el día que se agrega uno nuevo.
    """
    return lambda sql: all(f"'{tipo}'" in sql for tipo in tipos)


def _migrar_referencia_bono_en_movimientos_saldo_miembro(conexion: sqlite3.Connection):
    """
    Para una base creada antes de que existiera "bonos_miembro": hace que
    movimientos_saldo_miembro.bono_id apunte a ese catálogo y no al viejo
    (bonos_tiempo, el de walk-ins). La referencia queda grabada en el
    propio esquema de la tabla, y SQLite no deja cambiar un REFERENCES con
    ALTER TABLE. Sin esta migración, cargar un bono de socios cuyo id no
    existiera también en bonos_tiempo rompía con "FOREIGN KEY constraint
    failed" (pasa recién cuando las dos secuencias de ids se separan).

    Reconstruye la tabla (ver _reconstruir_tabla, que explica los dos casos
    borde).
    """
    _reconstruir_tabla(
        conexion, "movimientos_saldo_miembro", _COLUMNAS_MOVIMIENTOS_SALDO,
        ya_esta_al_dia=lambda sql: "bonos_miembro(id)" in sql,
        sql_tabla_nueva=lambda sql: _sql_tabla_movimientos_saldo_miembro(
            _TIPOS_MOVIMIENTO_SALDO_ORIGINALES, "bonos_miembro(id)"
        ),
    )


def _migrar_check_tipo_en_movimientos_saldo_miembro(conexion: sqlite3.Connection):
    """
    Agrega 'ANULACION' a los tipos válidos de movimientos_saldo_miembro.tipo
    (el CHECK (tipo IN (...)) del esquema). Lo necesita
    miembros_repo.anular_carga para revertir del saldo de un socio una
    CARGA cuya venta se anuló desde Consulta de Ventas, dejando un
    movimiento propio en el ledger en vez de disimularlo como un CONSUMO o
    un REINTEGRO que no fueron.

    SQLite no deja tocar un CHECK ya grabado con ALTER TABLE, así que
    reconstruye la tabla (ver _reconstruir_tabla). Corre
    siempre DESPUÉS de _migrar_referencia_bono_en_movimientos_saldo_miembro,
    así que el REFERENCES de bono_id puede llegar ya corregido o no: esta
    migración lo conserva tal cual y solo agrega el valor nuevo al CHECK.

    Mira TODOS los tipos de _TIPOS_MOVIMIENTO_SALDO (no solo el último que se
    sumó): si algún día se agrega otro, alcanza con sumarlo ahí y el próximo
    arranque reconstruye la tabla.
    """
    _reconstruir_tabla(
        conexion, "movimientos_saldo_miembro", _COLUMNAS_MOVIMIENTOS_SALDO,
        ya_esta_al_dia=_admite_todos_los_tipos(database._TIPOS_MOVIMIENTO_SALDO),
        sql_tabla_nueva=lambda sql: _sql_tabla_movimientos_saldo_miembro(
            database._TIPOS_MOVIMIENTO_SALDO,
            "bonos_miembro(id)" if "bonos_miembro(id)" in sql else "bonos_tiempo(id)",
        ),
    )


# Tipos de comando que admitía el CHECK de comandos_pc.tipo antes de que se
# sumaran CAMBIAR_RED y VOLUMEN (ver dominio.TIPOS_COMANDO_PC).
_TIPOS_COMANDO_PC_ORIGINALES = ("REINICIAR", "APAGAR", "MENSAJE", "SCREENSHOT")


def _sql_tabla_comandos_pc(tipos: tuple, si_no_existe: bool = False) -> str:
    """
    El CREATE TABLE de comandos_pc, escrito una sola vez. Lo usa
    inicializar_base_de_datos() con todos los dominio.TIPOS_COMANDO_PC y la
    migración de abajo para reconstruir la tabla. Lo único que cambió con el
    tiempo es qué `tipos` admite el CHECK (los tests usan los originales para
    simular una base vieja).
    """
    tipos_sql = _valores_sql(tipos)
    existe = "IF NOT EXISTS " if si_no_existe else ""
    return f"""
        CREATE TABLE {existe}comandos_pc (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id     INTEGER NOT NULL REFERENCES estaciones(id),
            tipo            TEXT NOT NULL CHECK (tipo IN ({tipos_sql})),
            payload         TEXT,
            fecha_creacion  TEXT NOT NULL,
            estado          TEXT NOT NULL DEFAULT '{dominio.ESTADO_COMANDO_PENDIENTE}' CHECK (estado IN ({_valores_sql(dominio.ESTADOS_COMANDO_PC)})),
            resultado       TEXT
        )
    """


def _migrar_check_tipo_en_comandos_pc(conexion: sqlite3.Connection):
    """
    Agrega CAMBIAR_RED y VOLUMEN a los tipos válidos de comandos_pc.tipo (el
    CHECK (tipo IN (...)) del esquema). Sin esto, "Cambiar red..." y "Ajustar
    volumen..." del menú de Control de PCs no podían ni encolar el comando:
    el INSERT fallaba con "CHECK constraint failed" en cualquier base.

    SQLite no deja tocar un CHECK ya grabado con ALTER TABLE, así que
    reconstruye la tabla (ver _reconstruir_tabla). Los comandos ya encolados
    y sus resultados se conservan.

    Mira TODOS los tipos de dominio.TIPOS_COMANDO_PC (no solo el último que
    se sumó): si algún día se agrega otro comando, alcanza con sumarlo ahí y
    el próximo arranque reconstruye la tabla; no hace falta otra migración.
    """
    _reconstruir_tabla(
        conexion, "comandos_pc",
        ("id", "estacion_id", "tipo", "payload", "fecha_creacion", "estado", "resultado"),
        ya_esta_al_dia=_admite_todos_los_tipos(dominio.TIPOS_COMANDO_PC),
        sql_tabla_nueva=lambda sql: _sql_tabla_comandos_pc(dominio.TIPOS_COMANDO_PC),
    )


# --- el resto de las migraciones ---

def _migrar_borrar_clave_vieja_de_clientes_pc(conexion: sqlite3.Connection):
    """
    Hasta el 2026-10-14 la clave con la que los Clientes PC se identifican ante
    `servidor_red.py` se generaba desde el programa y se guardaba en
    `configuracion` ('clave_clientes'; antes de que el proyecto hermano se
    llamara CLIENTE PC, 'clave_agentes'). Desde entonces es FIJA: vive solo en
    CLIENTE PC y acá se compara su huella (`clientes_repo.es_clave_de_clientes`),
    así que nada lee más esa fila. El dueño pidió borrarla (revisión del
    2026-10-17): una copia de una clave guardada donde nadie la usa no suma
    nada. Las copias de seguridad viejas la conservan, pero tampoco se leen.
    Segura de correr en cada arranque: si no está, no hace nada.
    """
    conexion.execute(
        "DELETE FROM configuracion WHERE clave IN ('clave_clientes', 'clave_agentes')"
    )
    conexion.commit()


def _migrar_columna_origen_en_ventas(conexion: sqlite3.Connection):
    """
    Para una base creada antes de que "ventas" distinguiera de dónde vino
    cada venta: agrega "origen" (ver dominio.ORIGENES_VENTA) y, la
    primera vez, reclasifica a ALQUILER_PCS las ventas viejas que en
    realidad fueron un bono de PC o una carga de saldo de Miembro --
    quedaron con el valor por defecto KIOSKO al agregar la columna, y sin
    este backfill el desglose de Caja/Cierre de Turno mentiría sobre el
    historial ya cargado.

    El backfill corre SOLO si la columna se acaba de agregar: así se hace
    una sola vez, no en cada arranque del programa -- con años de ventas
    cargadas, repetir este JOIN en cada inicio saldría caro para nada.
    """
    se_agrego = _agregar_columna_si_falta(
        conexion, "ventas", "origen",
        f"TEXT NOT NULL DEFAULT 'KIOSKO' CHECK (origen IN ({_origenes_venta_sql()}))",
    )
    if se_agrego:
        conexion.execute("""
            UPDATE ventas SET origen = 'ALQUILER_PCS'
            WHERE id IN (SELECT venta_id FROM sesion_bonos WHERE venta_id IS NOT NULL)
               OR id IN (SELECT venta_id FROM movimientos_saldo_miembro WHERE venta_id IS NOT NULL)
        """)
    conexion.commit()


def _migrar_columnas_origen_en_cierres(conexion: sqlite3.Connection):
    """
    Para una base creada antes del desglose por origen en el cierre de turno:
    agrega las columnas nuevas de cierres_turno en 0 (Kiosko y Alquiler de PCs
    primero; PlayStation 5 después) -- los cierres viejos ya cerrados no se
    pueden reconstruir con el desglose (no queda registro de qué parte de esas
    ventas ya era de PCs), así que quedan en 0 en vez de inventar un número.
    Para PlayStation 5 es exacto: antes de la consola no se vendió nada de eso.
    """
    for columna in (
        "kiosko_efectivo", "kiosko_digital", "pcs_efectivo", "pcs_digital",
        "playstation_efectivo", "playstation_digital",
    ):
        _agregar_columna_si_falta(conexion, "cierres_turno", columna, "REAL NOT NULL DEFAULT 0")
    conexion.commit()


def _migrar_check_origen_en_ventas(conexion: sqlite3.Connection):
    """
    Agrega 'PLAYSTATION' a los orígenes válidos de ventas.origen (el CHECK
    (origen IN (...)) del esquema). Sin esto, la primera venta de un bono de
    la PlayStation 5 fallaba con "CHECK constraint failed" en cualquier base
    ya existente.

    SQLite no deja tocar un CHECK ya grabado con ALTER TABLE, así que hay que
    reconstruir "ventas" -- pero a diferencia de las otras migraciones de este
    estilo (ver _reconstruir_tabla), esta es la tabla MADRE de la plata: la
    referencian venta_detalle, venta_pagos, sesion_bonos, tramites_venta,
    movimientos_saldo_miembro y sesion_playstation_bonos. Por eso no sirve
    renombrar la vieja primero (SQLite re-apuntaría esas referencias a
    "ventas_viejo", que después se borra): se arma "ventas_nueva" al lado, se
    copia, se borra la vieja y recién ahí se la renombra a "ventas". Es el
    procedimiento que documenta SQLite para esto, con las claves foráneas
    apagadas solo mientras dura y todo dentro de UNA transacción: si algo
    falla (o se corta la luz) a mitad de camino, no pasó nada -- la tabla vieja
    queda tal cual.

    Antes de tocar nada deja una copia de la base en data/backups/ (el nombre
    empieza con "antes_de_", así la rotación de los backups diarios no la
    borra nunca): es plata real. Mira TODOS los dominio.ORIGENES_VENTA (no solo
    el último que se sumó): si algún día se agrega otro origen, alcanza con
    sumarlo ahí y el próximo arranque reconstruye la tabla; no hace falta otra
    migración. En una base nueva, o ya al día, no hace nada.
    """
    definicion = conexion.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = 'ventas'"
    ).fetchone()
    if definicion is None or _admite_todos_los_tipos(dominio.ORIGENES_VENTA)(definicion["sql"]):
        return

    conexion.commit()
    _respaldar_antes_de_migrar("agregar_playstation_a_ventas")

    lista_columnas = ", ".join(database._COLUMNAS_VENTAS)
    # "PRAGMA foreign_keys" es un no-op dentro de una transacción: se apaga acá,
    # con todo lo anterior ya comiteado.
    conexion.execute("PRAGMA foreign_keys = OFF")
    try:
        conexion.execute("BEGIN")
        conexion.execute("DROP TABLE IF EXISTS ventas_nueva")
        conexion.execute(_sql_tabla_ventas("ventas_nueva"))
        conexion.execute(
            f"INSERT INTO ventas_nueva ({lista_columnas}) SELECT {lista_columnas} FROM ventas"
        )
        # AUTOINCREMENT no reutiliza ids: la tabla nueva tiene que seguir
        # numerando donde la vieja (no solo desde su mayor id, por si la última
        # fila alguna vez se hubiera borrado).
        conexion.execute(
            """
            UPDATE sqlite_sequence
            SET seq = MAX(seq, COALESCE((SELECT seq FROM sqlite_sequence WHERE name = 'ventas'), 0))
            WHERE name = 'ventas_nueva'
            """
        )
        conexion.execute("DROP TABLE ventas")
        conexion.execute("ALTER TABLE ventas_nueva RENAME TO ventas")
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.execute("PRAGMA foreign_keys = ON")
