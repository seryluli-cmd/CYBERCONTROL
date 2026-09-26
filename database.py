"""
database.py
============
Todo lo relacionado a la base de datos SQLite del sistema vive acá:
- Dónde se guarda el archivo de la base de datos.
- Cómo se conecta el resto del programa a ella.
- El esquema completo (todas las tablas), con comentarios explicando
  para qué sirve cada una y cómo se relacionan entre sí.
- Datos de ejemplo para poder probar el sistema apenas se instala.

Usamos SQLite porque es un archivo único en el disco (no hace falta instalar
ningún "servidor" de base de datos aparte), y funciona perfecto sin
internet, que es un requisito clave de este sistema.
"""

import sqlite3
import hashlib
import os
import secrets
import shutil
import sys
from contextlib import contextmanager
from datetime import datetime, date

import dominio

# Carpeta donde vive el archivo de la base de datos. Se guarda al lado del
# programa, dentro de una carpeta "data" para no mezclar el archivo .db
# con el código fuente. Cuando el programa corre como .exe empaquetado
# (PyInstaller), __file__ apunta a una carpeta temporal que se borra en
# cada arranque — si se usara esa carpeta para guardar la base de datos,
# el sistema "perdería la memoria" cada vez que se abre. Por eso, si está
# empaquetado, se usa la carpeta donde vive el .exe real en su lugar.
BASE_DIR = os.path.dirname(sys.executable) if getattr(sys, "frozen", False) \
    else os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.join(BASE_DIR, "data")
DB_PATH = os.path.join(DATA_DIR, "kiosko.db")
BACKUPS_DIR = os.path.join(DATA_DIR, "backups")
MAX_BACKUPS_AUTOMATICOS = 30


def hash_clave(texto_plano: str, salt: str = None) -> str:
    """
    Convierte una clave (contraseña) en un "hash" con salt — una versión
    codificada que no se puede revertir a la clave original, y que
    además usa un valor al azar (salt) distinto para cada usuario para
    que dos personas con la misma clave no terminen con el mismo hash
    guardado. El resultado se guarda como "salt$hash".

    Si no se pasa `salt`, se genera uno nuevo al azar (para altas de
    usuario o cambios de clave). Al verificar un login se le pasa el
    salt ya guardado, para recalcular el mismo hash y compararlo.
    """
    if salt is None:
        salt = secrets.token_hex(16)
    hash_hex = hashlib.sha256((salt + texto_plano).encode("utf-8")).hexdigest()
    return f"{salt}${hash_hex}"


def verificar_clave(texto_plano: str, hash_guardado: str) -> bool:
    """
    Compara una clave ingresada contra el hash guardado en la base.
    Soporta tanto el formato nuevo ("salt$hash") como el formato viejo
    (sha256 sin salt, como quedaron guardadas las claves antes de este
    cambio) para no invalidar usuarios ya creados. La migración de un
    hash viejo al formato nuevo se hace sola la próxima vez que esa
    persona haga login correctamente (ver usuarios_repo.autenticar).
    """
    if "$" in hash_guardado:
        salt, _ = hash_guardado.split("$", 1)
        return hash_clave(texto_plano, salt) == hash_guardado
    return hashlib.sha256(texto_plano.encode("utf-8")).hexdigest() == hash_guardado


def get_connection() -> sqlite3.Connection:
    """
    Abre (o crea si no existe) la conexión a la base de datos.
    `row_factory = sqlite3.Row` permite acceder a las columnas de un
    resultado por nombre (fila["descripcion"]) en vez de solo por
    posición (fila[1]), lo cual hace el código mucho más legible.
    """
    os.makedirs(DATA_DIR, exist_ok=True)
    conexion = sqlite3.connect(DB_PATH)
    conexion.row_factory = sqlite3.Row
    # Activamos el chequeo de claves foráneas: SQLite lo trae desactivado
    # por defecto, y sin esto no se respetarían las relaciones entre tablas.
    conexion.execute("PRAGMA foreign_keys = ON")
    return conexion


@contextmanager
def conexion_db():
    """
    Forma recomendada de usar la base desde los repositorios:

        with conexion_db() as conexion:
            conexion.execute(...)

    Si todo sale bien, hace commit solo al final. Si algo tira una
    excepción en el medio (por ejemplo, una violación de clave foránea
    al intentar borrar un artículo con historial), hace rollback en vez
    de dejar cambios a medio guardar, y siempre cierra la conexión pase
    lo que pase — antes cada función abría y cerraba la conexión a mano,
    y un error en el medio podía dejarla abierta sin guardar ni
    deshacer nada.
    """
    conexion = get_connection()
    try:
        yield conexion
        conexion.commit()
    except Exception:
        conexion.rollback()
        raise
    finally:
        conexion.close()


def hacer_backup_automatico():
    """
    Guarda una copia de la base de datos en data/backups/ una vez por
    día (la primera vez que se abre el programa ese día). Antes la
    única forma de tener una copia era que alguien se acordara de
    copiar el archivo a mano; esto pasa a hacerse solo, sin pedir nada.
    Se conservan como máximo los últimos MAX_BACKUPS_AUTOMATICOS
    archivos — los más viejos se van borrando solos para no llenar el
    disco con años de copias diarias.
    """
    if not os.path.exists(DB_PATH):
        return  # primera vez que se usa el sistema, todavía no hay nada que respaldar

    os.makedirs(BACKUPS_DIR, exist_ok=True)
    destino = os.path.join(BACKUPS_DIR, f"kiosko_{date.today().isoformat()}.db")
    if os.path.exists(destino):
        return  # ya se hizo el backup de hoy

    shutil.copy2(DB_PATH, destino)

    backups_existentes = sorted(
        f for f in os.listdir(BACKUPS_DIR) if f.startswith("kiosko_") and f.endswith(".db")
    )
    for viejo in backups_existentes[:-MAX_BACKUPS_AUTOMATICOS]:
        try:
            os.remove(os.path.join(BACKUPS_DIR, viejo))
        except OSError:
            pass  # si no se puede borrar uno viejo, no es motivo para frenar el arranque


def copiar_backup_a(carpeta_destino: str) -> str:
    """
    Copia la base de datos actual a la carpeta que elija la usuaria
    (por ejemplo, un pendrive), con fecha y hora en el nombre para no
    pisar copias anteriores. Devuelve la ruta final del archivo
    copiado, para poder mostrarla en un cartel de confirmación.
    """
    ahora = datetime.now().strftime("%Y%m%d_%H%M%S")
    destino = os.path.join(carpeta_destino, f"kiosko_backup_{ahora}.db")
    shutil.copy2(DB_PATH, destino)
    return destino


def inicializar_base_de_datos():
    """
    Crea todas las tablas si todavía no existen (no borra nada si ya
    existen, así que es seguro llamar a esta función cada vez que arranca
    el programa). También carga datos de ejemplo la primera vez.
    """
    conexion = get_connection()
    cursor = conexion.cursor()

    # -------------------------------------------------------------------
    # USUARIOS
    # -------------------------------------------------------------------
    # Cada empleada y el/los administradores tienen su propio usuario.
    # "rol" solo puede ser ADMIN o EMPLEADA (dos niveles, como se definió).
    #   - ADMIN: acceso total siempre, incluida la administración de
    #     usuarios y la anulación de ventas — esto no se puede delegar
    #     con los permisos de abajo, son exclusivos del rol ADMIN.
    #   - EMPLEADA: por defecto solo factura (Ventas) y ve su propia
    #     caja. Un Admin puede sumarle permisos puntuales con los
    #     "permiso_*" de abajo (ver PERMISOS_EMPLEADA en
    #     usuarios_repo.py) para que también pueda entrar a Artículos,
    #     Compras, Consulta de Ventas (sin poder anular), Reportes o
    #     Control de Cierres, sin tener que hacerla Admin del todo.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre                   TEXT NOT NULL,
            clave_hash               TEXT NOT NULL,
            rol                      TEXT NOT NULL CHECK (rol IN ('ADMIN', 'EMPLEADA')),
            activo                   INTEGER NOT NULL DEFAULT 1,
            fecha_creacion           TEXT NOT NULL,
            permiso_articulos        INTEGER NOT NULL DEFAULT 0,
            permiso_compras          INTEGER NOT NULL DEFAULT 0,
            permiso_consulta_ventas  INTEGER NOT NULL DEFAULT 0,
            permiso_reportes         INTEGER NOT NULL DEFAULT 0,
            permiso_control_cierres  INTEGER NOT NULL DEFAULT 0,
            permiso_control_pcs      INTEGER NOT NULL DEFAULT 0
        )
    """)
    _migrar_columnas_permisos(conexion)

    # -------------------------------------------------------------------
    # MARCAS y RUBROS
    # -------------------------------------------------------------------
    # Tablas simples de "catálogo" para que Marca y Rubro se puedan elegir
    # de una lista (y agregar nuevas al vuelo) en vez de escribirlas a mano
    # cada vez, evitando que "COCA" y "Coca" queden como cosas distintas.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS marcas (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rubros (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE
        )
    """)

    # -------------------------------------------------------------------
    # ARTICULOS
    # -------------------------------------------------------------------
    # El "codigo" es el código de barras (o un código corto para productos
    # sin barras, como "PANCHO DOBLE"). Es el identificador natural del
    # producto porque es lo que lee la pistola lectora.
    #
    # "stock" puede quedar en negativo a propósito: cuando se vende un
    # producto que todavía no se cargó como compra, el stock baja de 0
    # para abajo, y cuando después se carga la compra correspondiente,
    # el número se corrige solo. Nunca se bloquea una venta por falta de
    # stock, solo se avisa si queda por debajo de "stock_minimo".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articulos (
            codigo          TEXT PRIMARY KEY,
            descripcion     TEXT NOT NULL,
            marca_id        INTEGER REFERENCES marcas(id),
            rubro_id        INTEGER REFERENCES rubros(id),
            precio_venta    REAL NOT NULL DEFAULT 0,
            precio_compra   REAL NOT NULL DEFAULT 0,
            stock           INTEGER NOT NULL DEFAULT 0,
            stock_minimo    INTEGER NOT NULL DEFAULT 0,
            fecha_creacion  TEXT NOT NULL,
            fecha_modif     TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # COMPRAS (ingreso de mercadería)
    # -------------------------------------------------------------------
    # Es la ÚNICA forma de modificar el stock de un artículo (aparte de las
    # ventas). Cada compra tiene una cabecera (fecha, quién la cargó) y
    # varias líneas de detalle, una por artículo ingresado.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha       TEXT NOT NULL,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compra_detalle (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id        INTEGER NOT NULL REFERENCES compras(id),
            articulo_codigo  TEXT NOT NULL REFERENCES articulos(codigo),
            cantidad         INTEGER NOT NULL,
            costo_unitario   REAL NOT NULL,
            stock_antes      INTEGER NOT NULL,
            stock_despues    INTEGER NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # VENTAS (facturación)
    # -------------------------------------------------------------------
    # "turno" se calcula automáticamente según la hora de la venta
    # (MAÑANA 06-14, TARDE 14-22, NOCHE 22-06), sin importar qué usuario
    # esté logueado — así el reporte "ventas por turno" es siempre exacto,
    # incluso si una empleada llega tarde a su horario.
    #
    # "estado" es CONFIRMADA o ANULADA. Nunca se borra una venta: si el
    # Admin necesita corregir un error después de cobrada, se anula (queda
    # el rastro de quién, cuándo y por qué) y el stock se repone solo.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ventas (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha             TEXT NOT NULL,
            usuario_id        INTEGER NOT NULL REFERENCES usuarios(id),
            turno             TEXT NOT NULL CHECK (turno IN ('MAÑANA', 'TARDE', 'NOCHE')),
            total              REAL NOT NULL,
            estado            TEXT NOT NULL DEFAULT 'CONFIRMADA' CHECK (estado IN ('CONFIRMADA', 'ANULADA')),
            anulada_por        INTEGER REFERENCES usuarios(id),
            anulada_fecha      TEXT,
            anulada_motivo     TEXT
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS venta_detalle (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id         INTEGER NOT NULL REFERENCES ventas(id),
            articulo_codigo  TEXT NOT NULL REFERENCES articulos(codigo),
            descripcion      TEXT NOT NULL,
            cantidad         INTEGER NOT NULL,
            precio_unitario  REAL NOT NULL,
            subtotal         REAL NOT NULL
        )
    """)
    # Una venta puede pagarse combinando más de un medio de pago (por
    # ejemplo: una parte en efectivo y el resto por Mercado Pago), por eso
    # los pagos son una tabla aparte y no un campo único en "ventas".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS venta_pagos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id  INTEGER NOT NULL REFERENCES ventas(id),
            metodo    TEXT NOT NULL CHECK (metodo IN ('EFECTIVO', 'DIGITAL')),
            monto     REAL NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # CIERRES DE TURNO
    # -------------------------------------------------------------------
    # Un registro por cada vez que una empleada cierra su turno. Guarda
    # cuánto efectivo "debería" haber (fondo de cambio + ventas en
    # efectivo de ese turno) para que la empleada se lleve la diferencia.
    # Más tarde, el Admin puede cargar "monto_contado" (lo que realmente
    # había en el sobre) para llevar un control por empleada y por turno.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cierres_turno (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha               TEXT NOT NULL,
            turno               TEXT NOT NULL CHECK (turno IN ('MAÑANA', 'TARDE', 'NOCHE')),
            usuario_id          INTEGER NOT NULL REFERENCES usuarios(id),
            fecha_cierre        TEXT NOT NULL,
            fondo_cambio        REAL NOT NULL,
            ventas_efectivo     REAL NOT NULL,
            ventas_digital      REAL NOT NULL,
            monto_a_retirar     REAL NOT NULL,
            monto_contado       REAL,
            diferencia          REAL,
            verificado_por      INTEGER REFERENCES usuarios(id),
            fecha_verificacion  TEXT
        )
    """)

    # -------------------------------------------------------------------
    # SESIONES (inicios de sesión)
    # -------------------------------------------------------------------
    # Una fila por cada login exitoso. El sistema no tiene un horario
    # asignado por empleada, así que esto sirve como pista de quién
    # estaba usando el sistema en un momento dado — en particular, para
    # saber quién podría ser responsable de un turno que quedó sin
    # cerrar aunque no haya vendido nada en esa ventana (ver
    # turnos_repo._responsables_del_mes).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id),
            fecha_hora  TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # ESTACIONES y BONOS DE TIEMPO (Control de PCs)
    # -------------------------------------------------------------------
    # "estaciones" es el catálogo de PCs físicas del local (ej. "PC 1"...
    # "PC 10"), igual de simple que marcas/rubros. "bonos_tiempo" es el
    # catálogo de combos vendibles ("3 horas" -> 180 min / $X) que arma
    # el Admin: acá NUNCA se cobra por minuto suelto ni por hora libre,
    # solo por estos bonos prearmados. "activo" en ambas tablas permite
    # dar de baja una sin romper el historial de sesiones que ya la usaron
    # (mismo criterio que articulos.stock: nunca se borra, se desactiva).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estaciones (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL UNIQUE,
            activa  INTEGER NOT NULL DEFAULT 1
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bonos_tiempo (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL,
            minutos INTEGER NOT NULL,
            precio  REAL NOT NULL,
            activo  INTEGER NOT NULL DEFAULT 1
        )
    """)

    # Una fila por uso continuo de una estación. Al vender un bono a una
    # estación sin sesión activa se crea una fila nueva; al vender un
    # bono adicional a una que YA está activa (el cliente sigue jugando)
    # se extiende "fecha_fin_prevista" de esta misma fila en vez de crear
    # otra — así "agregar tiempo" es sumar otro bono a la sesión abierta,
    # sin necesitar un concepto aparte de "extender por minutos sueltos".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_pc (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id         INTEGER NOT NULL REFERENCES estaciones(id),
            fecha_inicio        TEXT NOT NULL,
            fecha_fin_prevista  TEXT NOT NULL,
            estado              TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA', 'FINALIZADA')),
            fecha_fin_real      TEXT
        )
    """)
    # Detalle de qué bono(s) se cargaron a cada sesión, con el venta_id de
    # la venta que generó ese cobro (se factura igual que cualquier venta
    # de kiosko, ver pcs_repo.asignar_bono) — trazabilidad completa entre
    # "se vendió este bono a esta PC" y "esto es lo que se facturó".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesion_bonos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id  INTEGER NOT NULL REFERENCES sesiones_pc(id),
            bono_id    INTEGER NOT NULL REFERENCES bonos_tiempo(id),
            minutos    INTEGER NOT NULL,
            precio     REAL NOT NULL,
            venta_id   INTEGER REFERENCES ventas(id)
        )
    """)

    # -------------------------------------------------------------------
    # MIEMBROS (socios con saldo prepago de tiempo)
    # -------------------------------------------------------------------
    # A diferencia de un bono (lo habilita el mostrador, se paga y se usa
    # en el momento, sin reintegro), un Miembro tiene una cuenta propia:
    # se loguea solo con "usuario"/clave para abrir una PC con SU saldo
    # (ver pcs_repo._abrir_o_extender_sesion / miembros_repo.abrir_estacion_por_miembro).
    # "usuario" acá SÍ es UNIQUE de verdad (a diferencia de usuarios.nombre,
    # que solo se valida en Python) porque es un campo de login real, no
    # un nombre para mostrar. "email" es el único dato realmente opcional.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS miembros (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario         TEXT NOT NULL UNIQUE,
            clave_hash      TEXT NOT NULL,
            nombre          TEXT NOT NULL,
            dni             TEXT NOT NULL,
            telefono        TEXT NOT NULL,
            email           TEXT,
            saldo_minutos   INTEGER NOT NULL DEFAULT 0,
            activo          INTEGER NOT NULL DEFAULT 1,
            fecha_creacion  TEXT NOT NULL
        )
    """)
    # Ledger de auditoría de todo movimiento de saldo: CARGA (siempre con
    # venta_id, porque implica cobrar plata real — y bono_id si se cargó
    # comprando un bono en vez de un monto libre), CONSUMO (sesion_id,
    # al abrir una PC con saldo) y REINTEGRO (sesion_id, cuando se corta
    # antes de tiempo y se devuelve lo no usado). Como esto maneja plata
    # de terceros, poder reconstruir "por qué le queda tal saldo a este
    # socio" no es opcional.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS movimientos_saldo_miembro (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            miembro_id  INTEGER NOT NULL REFERENCES miembros(id),
            tipo        TEXT NOT NULL CHECK (tipo IN ('CARGA', 'CONSUMO', 'REINTEGRO')),
            minutos     INTEGER NOT NULL,
            fecha       TEXT NOT NULL,
            venta_id    INTEGER REFERENCES ventas(id),
            bono_id     INTEGER REFERENCES bonos_tiempo(id),
            sesion_id   INTEGER REFERENCES sesiones_pc(id)
        )
    """)
    _migrar_columna_miembro_en_sesiones(conexion)

    # -------------------------------------------------------------------
    # CONFIGURACION
    # -------------------------------------------------------------------
    # Tabla simple de "clave -> valor" para parámetros generales del
    # sistema. Hoy solo se usa para el fondo de cambio, pero permite
    # agregar más configuraciones a futuro sin tener que cambiar el
    # esquema de la base de datos.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion (
            clave  TEXT PRIMARY KEY,
            valor  TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # INDICES
    # -------------------------------------------------------------------
    # Estos índices son la razón por la que los reportes van a ser rápidos
    # incluso con años de historial: le dicen a SQLite que arme un "atajo"
    # para buscar por fecha o por artículo, en vez de tener que recorrer
    # toda la tabla fila por fila cada vez que pedís un reporte.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ventas_turno ON ventas(turno, fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_venta_detalle_venta ON venta_detalle(venta_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_venta_detalle_articulo ON venta_detalle(articulo_codigo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_detalle_articulo ON compra_detalle(articulo_codigo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_detalle_compra ON compra_detalle(compra_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_fecha ON sesiones(fecha_hora)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_pc_estacion ON sesiones_pc(estacion_id, estado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_saldo_miembro ON movimientos_saldo_miembro(miembro_id)")

    conexion.commit()

    _cargar_datos_iniciales(conexion)

    conexion.close()


def _migrar_columnas_permisos(conexion: sqlite3.Connection):
    """
    Para una base creada antes de que existieran los permisos por
    empleada (Artículos/Compras/Consulta de Ventas/Reportes/Control de
    Cierres): agrega las columnas "permiso_*" que falten con
    ALTER TABLE, en vez de perder la base ya existente. Hace falta este
    paso aparte porque CREATE TABLE IF NOT EXISTS no toca una tabla que
    ya existe, aunque le falten columnas nuevas del esquema de arriba.
    """
    columnas_actuales = {fila["name"] for fila in conexion.execute("PRAGMA table_info(usuarios)")}
    for columna in (
        "permiso_articulos", "permiso_compras", "permiso_consulta_ventas",
        "permiso_reportes", "permiso_control_cierres", "permiso_control_pcs",
    ):
        if columna not in columnas_actuales:
            conexion.execute(f"ALTER TABLE usuarios ADD COLUMN {columna} INTEGER NOT NULL DEFAULT 0")
    conexion.commit()


def _migrar_columna_miembro_en_sesiones(conexion: sqlite3.Connection):
    """
    Para una base creada antes de que existiera "Miembros": agrega
    sesiones_pc.miembro_id (NULL = sesión de bono/walk-in, como siempre
    fue; con valor = sesión abierta con el saldo de ese socio). Mismo
    motivo que _migrar_columnas_permisos: ALTER TABLE porque
    CREATE TABLE IF NOT EXISTS no toca una tabla que ya existe.
    """
    columnas_actuales = {fila["name"] for fila in conexion.execute("PRAGMA table_info(sesiones_pc)")}
    if "miembro_id" not in columnas_actuales:
        conexion.execute("ALTER TABLE sesiones_pc ADD COLUMN miembro_id INTEGER REFERENCES miembros(id)")
    conexion.commit()


def _cargar_datos_iniciales(conexion: sqlite3.Connection):
    """
    Carga un usuario Administrador y el valor por defecto del fondo de
    cambio la primera vez que se usa el sistema (si ya hay usuarios
    cargados, no hace nada, para no pisar datos reales).
    """
    cursor = conexion.cursor()

    cursor.execute("SELECT COUNT(*) AS cantidad FROM usuarios")
    if cursor.fetchone()["cantidad"] == 0:
        ahora = datetime.now().isoformat(timespec="seconds")
        cursor.execute(
            """
            INSERT INTO usuarios (nombre, clave_hash, rol, activo, fecha_creacion)
            VALUES (?, ?, ?, 1, ?)
            """,
            ("Administrador", hash_clave("1234"), dominio.ROL_ADMIN, ahora),
        )
        conexion.commit()

    cursor.execute("SELECT COUNT(*) AS cantidad FROM configuracion WHERE clave = 'fondo_cambio'")
    if cursor.fetchone()["cantidad"] == 0:
        cursor.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('fondo_cambio', '50000')"
        )
        conexion.commit()

    cursor.execute("SELECT COUNT(*) AS cantidad FROM configuracion WHERE clave = 'tarifa_hora_miembro'")
    if cursor.fetchone()["cantidad"] == 0:
        cursor.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('tarifa_hora_miembro', '1000')"
        )
        conexion.commit()

    # Rubros de fábrica: se cargan UNA sola vez (se deja constancia en
    # "configuracion" de que ya se hizo). Si se gatillara en cada
    # arranque en vez de una sola vez, un rubro que el Admin borra a
    # propósito desde "Gestionar Rubros" volvería a aparecer solo.
    cursor.execute("SELECT COUNT(*) AS cantidad FROM configuracion WHERE clave = 'rubros_iniciales_cargados'")
    if cursor.fetchone()["cantidad"] == 0:
        for nombre in ("BEBIDAS", "KIOSKO", "ARTÍCULOS DE LIMPIEZA", "INSUMOS DE PAPELERÍA"):
            cursor.execute("INSERT OR IGNORE INTO rubros (nombre) VALUES (?)", (nombre,))
        cursor.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('rubros_iniciales_cargados', '1')"
        )
        conexion.commit()
