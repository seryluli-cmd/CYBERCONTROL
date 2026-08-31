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
from datetime import datetime, date, timedelta

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
    #   - ADMIN: acceso total, incluida la carga de stock (vía Compras),
    #     administración de usuarios, anulación de ventas, reportes, etc.
    #   - EMPLEADA: solo puede facturar (Ventas) y ver su propia caja.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT NOT NULL,
            clave_hash      TEXT NOT NULL,
            rol             TEXT NOT NULL CHECK (rol IN ('ADMIN', 'EMPLEADA')),
            activo          INTEGER NOT NULL DEFAULT 1,
            fecha_creacion  TEXT NOT NULL
        )
    """)

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

    conexion.commit()

    _cargar_datos_iniciales(conexion)

    conexion.close()


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
            VALUES (?, ?, 'ADMIN', 1, ?)
            """,
            ("Administrador", hash_clave("1234"), ahora),
        )
        conexion.commit()

    cursor.execute("SELECT COUNT(*) AS cantidad FROM configuracion WHERE clave = 'fondo_cambio'")
    if cursor.fetchone()["cantidad"] == 0:
        cursor.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('fondo_cambio', '50000')"
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


def calcular_turno(fecha_hora: datetime) -> str:
    """
    Devuelve a qué turno pertenece una fecha/hora determinada, según los
    horarios fijos del local (abierto las 24 hs):
        MAÑANA:  06:00 a 13:59
        TARDE:   14:00 a 21:59
        NOCHE:   22:00 a 05:59 (cruza la medianoche)
    Esto es independiente de qué usuario esté logueado, así que aunque
    una empleada llegue tarde, cada venta se clasifica sola por su hora
    real.

    EXCEPCIÓN: los domingos son distintos — solo hay 2 turnos de 12hs en
    vez de 3. "MAÑANA" pasa a durar 06:00-17:59 (absorbe lo que sería
    "TARDE", que no existe ese día) y "NOCHE" pasa a ser 18:00-05:59 del
    lunes. El sábado a la noche sigue siendo el turno normal 22-06
    (termina el domingo a la mañana), eso no cambia — por eso se mira el
    día de `fecha_hora` tal cual, sin correcciones.
    """
    domingo = fecha_hora.weekday() == 6  # Monday=0 ... Sunday=6
    hora = fecha_hora.hour
    fin_manana = 18 if domingo else 14
    if 6 <= hora < fin_manana:
        return "MAÑANA"
    elif not domingo and 14 <= hora < 22:
        return "TARDE"
    else:
        return "NOCHE"


def es_domingo(fecha) -> bool:
    """Acepta un date, un datetime, o un string 'YYYY-MM-DD' (o con hora
    al final, se ignora)."""
    if isinstance(fecha, datetime):
        fecha = fecha.date()
    elif isinstance(fecha, str):
        fecha = date.fromisoformat(fecha[:10])
    return fecha.weekday() == 6


def etiqueta_turno(fecha, turno: str) -> str:
    """
    Nombre legible de un turno según el día calendario al que
    pertenece: los domingos "MAÑANA"/"NOCHE" se muestran como "Domingo
    T1"/"Domingo T2" en vez de "Mañana"/"Noche", porque ese día no
    existe el turno Tarde — son 2 turnos de 12hs en vez de 3 (ver
    calcular_turno). `fecha` acepta lo mismo que es_domingo().
    """
    if es_domingo(fecha):
        if turno == "MAÑANA":
            return "Domingo T1"
        if turno == "NOCHE":
            return "Domingo T2"
    return turno.capitalize()


# Cuántos minutos de gracia se le dan a un turno vencido antes de
# considerarlo realmente "sin cerrar": quien cierra un turno tarda un
# rato en cargarlo, así que no tiene sentido avisar apenas termina su
# horario nominal — ver turno_vencimiento.
TURNO_GRACIA_MIN = 40


def turno_vencimiento(dia_base, turno: str) -> datetime:
    """
    Momento exacto en que el turno `turno` de un día calendario dado
    (`dia_base`, acepta lo mismo que es_domingo()) queda vencido: fin de
    su ventana nominal + TURNO_GRACIA_MIN de gracia. Se usa para saber
    si un turno del mes en curso que todavía no tiene cierre cargado ya
    "debería" estarlo, o si puede seguir en curso.

    NOCHE cruza la medianoche, por eso vence a la madrugada del día
    SIGUIENTE al que arrancó — esto no cambia los domingos: tanto la
    noche normal como "Domingo T2" terminan igual a las 06:00 del día
    siguiente, lo único que cambia es a qué hora arrancan.
    """
    if isinstance(dia_base, datetime):
        dia_base = dia_base.date()
    elif isinstance(dia_base, str):
        dia_base = date.fromisoformat(dia_base[:10])
    domingo = dia_base.weekday() == 6
    inicio_dia = datetime(dia_base.year, dia_base.month, dia_base.day)

    if turno == "MAÑANA":
        hora_fin = 18 if domingo else 14
        return inicio_dia.replace(hour=hora_fin, minute=TURNO_GRACIA_MIN)
    if turno == "TARDE":
        return inicio_dia.replace(hour=22, minute=TURNO_GRACIA_MIN)
    # NOCHE: vence a la madrugada del día siguiente.
    return (inicio_dia + timedelta(days=1)).replace(hour=6, minute=TURNO_GRACIA_MIN)
