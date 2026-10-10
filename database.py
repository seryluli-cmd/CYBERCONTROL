"""
database.py
============
Punto de entrada de SQLite para el resto del sistema:
- Dónde se guarda el archivo de la base de datos.
- Cómo se conecta el resto del programa a ella.
- El esquema completo vive en database_esquema.py.
- Las migraciones (`_migrar_*`) viven en database_migraciones.py.
- Los datos mínimos de la primera vez: un Administrador, el fondo de
  cambio, la tarifa de socios y los rubros de fábrica.

Usamos SQLite porque es un archivo único en el disco (no hace falta instalar
ningún "servidor" de base de datos aparte), y funciona perfecto sin
internet, que es un requisito clave de este sistema.

Todo cambio de esquema va como migración idempotente (segura de correr en
cada arranque), nunca borrando la base: ver CLAUDE.md, regla 6.
"""

import sqlite3
import hashlib
import os
import secrets
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
    lo que pase: un error en el medio nunca deja una conexión abierta sin
    guardar ni deshacer nada.
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


def _backup_consistente(destino: str):
    """
    Copia la base de datos a `destino` usando la Online Backup API de
    SQLite (`sqlite3.Connection.backup`), no una copia de archivo cruda
    (`shutil.copy`). El programa sigue corriendo mientras se hace un
    backup -- el servidor de red (servidor_red.py) sigue atendiendo
    pedidos de las PCs cliente en su propio hilo, y cualquier pantalla
    puede estar a mitad de una operación de varias tablas (ver
    ventas_repo.confirmar_venta: cabecera, detalle, pagos y stock se
    graban juntos, todo o nada). Copiar el archivo .db a mano justo en
    ese instante puede capturarlo a mitad de esa escritura -- sin el
    archivo de journal al lado que le permitiría a SQLite deshacerla
    sola, así que la copia queda con esa operación a medio grabar, y al
    abrirla más tarde parece una base válida en vez de avisar que algo
    quedó incompleto. `Connection.backup()` usa el mecanismo oficial de
    SQLite para este caso: toma una foto consistente de un instante
    puntual aunque haya otra conexión escribiendo al mismo tiempo,
    reintentando sola si choca con una escritura en curso -- nunca deja
    un archivo a medio grabar.
    """
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    origen = sqlite3.connect(DB_PATH)
    try:
        con_destino = sqlite3.connect(destino)
        try:
            origen.backup(con_destino)
        finally:
            con_destino.close()
    finally:
        origen.close()


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

    _backup_consistente(destino)

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
    _backup_consistente(destino)
    return destino


# Columnas de "ventas", para copiarlas al reconstruir la tabla.
_COLUMNAS_VENTAS = (
    "id", "fecha", "usuario_id", "turno", "total", "estado", "anulada_por",
    "anulada_fecha", "anulada_motivo", "origen",
)


def _origenes_venta_sql() -> str:
    """Los orígenes de venta (dominio.ORIGENES_VENTA) como van dentro de un
    CHECK (origen IN (...)): una sola fuente, así el esquema nunca queda
    desfasado de dominio.py."""
    return ", ".join(f"'{origen}'" for origen in dominio.ORIGENES_VENTA)


def _sql_tabla_ventas(nombre: str = "ventas", si_no_existe: bool = False) -> str:
    """
    El CREATE TABLE de "ventas", escrito una sola vez. Lo usa
    inicializar_base_de_datos() para una base nueva y
    _migrar_check_origen_en_ventas() para reconstruir la tabla de una base
    vieja (SQLite no deja cambiar un CHECK ya grabado). `nombre` es el de la
    tabla a crear: la migración arma "ventas_nueva" aparte y recién al final
    la renombra, porque otras cinco tablas apuntan a "ventas".
    """
    existe = "IF NOT EXISTS " if si_no_existe else ""
    return f"""
        CREATE TABLE {existe}{nombre} (
            id                INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha             TEXT NOT NULL,
            usuario_id        INTEGER NOT NULL REFERENCES usuarios(id),
            turno             TEXT NOT NULL CHECK (turno IN ('MAÑANA', 'TARDE', 'NOCHE')),
            total              REAL NOT NULL,
            estado            TEXT NOT NULL DEFAULT 'CONFIRMADA' CHECK (estado IN ('CONFIRMADA', 'ANULADA')),
            anulada_por        INTEGER REFERENCES usuarios(id),
            anulada_fecha      TEXT,
            anulada_motivo     TEXT,
            origen             TEXT NOT NULL DEFAULT 'KIOSKO' CHECK (origen IN ({_origenes_venta_sql()}))
        )
    """


def _sql_tabla_de_bonos(tabla: str) -> str:
    """
    El CREATE TABLE de un catálogo de bonos de tiempo. Hay tres con el mismo
    esquema -- "bonos_tiempo" (walk-ins), "bonos_miembro" (exclusivo de
    socios) y "bonos_playstation" (exclusivo de la consola) -- a propósito en
    tablas separadas: ver CLAUDE.md, "Hay TRES catálogos de bonos".
    """
    return f"""
        CREATE TABLE IF NOT EXISTS {tabla} (
            id      INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre  TEXT NOT NULL,
            minutos INTEGER NOT NULL,
            precio  REAL NOT NULL,
            activo  INTEGER NOT NULL DEFAULT 1
        )
    """


def inicializar_base_de_datos():
    """Crea el esquema y actualiza bases anteriores sin reemplazar sus datos."""
    from database_esquema import inicializar_base_de_datos as crear_esquema
    return crear_esquema()


def _respaldar_antes_de_migrar(motivo: str):
    """
    Copia de seguridad de la base ANTES de una migración que reconstruye una
    tabla con plata adentro (ver _migrar_check_origen_en_ventas). A propósito
    NO usa BACKUPS_DIR (se resuelve al importar el módulo): la carpeta sale de
    DATA_DIR al momento de llamar, así los tests, que apuntan DATA_DIR a una
    carpeta temporal, nunca escriben en los backups reales.

    Es un extra, no un requisito: la migración es una sola transacción y se
    deshace sola si falla, así que si no se puede escribir la copia (disco
    lleno, sin permisos) se sigue igual en vez de dejar el programa sin arrancar.
    """
    destino = os.path.join(
        DATA_DIR, "backups", f"antes_de_{motivo}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    )
    try:
        _backup_consistente(destino)
    except (OSError, sqlite3.Error):
        pass


# --------------------------------------------------------------------
# Datos de la primera vez
# --------------------------------------------------------------------

def _insertar_configuracion_si_falta(cursor: sqlite3.Cursor, clave: str, valor: str) -> bool:
    """
    Guarda `clave` en `configuracion` solo si todavía no existe, para no
    pisar lo que el Admin ya cambió. Devuelve True si la insertó. No hace
    commit.
    """
    cursor.execute("SELECT COUNT(*) AS cantidad FROM configuracion WHERE clave = ?", (clave,))
    if cursor.fetchone()["cantidad"] != 0:
        return False
    cursor.execute("INSERT INTO configuracion (clave, valor) VALUES (?, ?)", (clave, valor))
    return True


def _cargar_datos_iniciales(conexion: sqlite3.Connection):
    """
    Carga un usuario Administrador y los valores por defecto del fondo de
    cambio, la tarifa de socios y los rubros de fábrica la primera vez que
    se usa el sistema (lo que ya esté cargado no se toca, para no pisar
    datos reales).
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

    for clave, valor in (("fondo_cambio", "50000"), ("tarifa_hora_miembro", "1000")):
        _insertar_configuracion_si_falta(cursor, clave, valor)
        conexion.commit()

    # Rubros de fábrica: se cargan UNA sola vez (se deja constancia en
    # "configuracion" de que ya se hizo). Si se gatillara en cada
    # arranque en vez de una sola vez, un rubro que el Admin borra a
    # propósito desde "Gestionar Rubros" volvería a aparecer solo.
    if _insertar_configuracion_si_falta(cursor, "rubros_iniciales_cargados", "1"):
        for nombre in ("BEBIDAS", "KIOSKO", "ARTÍCULOS DE LIMPIEZA", "INSUMOS DE PAPELERÍA"):
            cursor.execute("INSERT OR IGNORE INTO rubros (nombre) VALUES (?)", (nombre,))
        conexion.commit()


# API histórica: los tests y módulos existentes importan estas funciones desde database.
from database_migraciones import (
    _agregar_columna_si_falta,
    _migrar_columnas_permisos,
    _migrar_columna_ultima_conexion_estaciones,
    _migrar_columna_ultima_ip_estaciones,
    _migrar_columna_cliente_cerrado_desde_estaciones,
    _migrar_columna_miembro_en_sesiones,
    _sql_tabla_movimientos_saldo_miembro,
    _reconstruir_tabla,
    _admite_todos_los_tipos,
    _migrar_referencia_bono_en_movimientos_saldo_miembro,
    _migrar_check_tipo_en_movimientos_saldo_miembro,
    _sql_tabla_comandos_pc,
    _migrar_check_tipo_en_comandos_pc,
    _migrar_clave_clientes_pc,
    _migrar_columna_origen_en_ventas,
    _migrar_columnas_origen_en_cierres,
    _migrar_check_origen_en_ventas,
    _COLUMNAS_MOVIMIENTOS_SALDO,
    _TIPOS_MOVIMIENTO_SALDO_ORIGINALES,
    _TIPOS_MOVIMIENTO_SALDO,
    _TIPOS_COMANDO_PC_ORIGINALES,
)
