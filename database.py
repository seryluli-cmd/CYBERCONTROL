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

import hashlib
import os
import re
import secrets
import sys
from contextlib import contextmanager
from datetime import datetime

import dominio
from motor_sql import PUEDE_CIFRAR, sqlite3

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


# --------------------------------------------------------------------
# Cifrado de la base
# --------------------------------------------------------------------
# Pedido del dueño (2026-10-19): que quien consiga el archivo kiosko.db -- de esta
# PC, de una copia de seguridad en otra PC o en un pendrive -- no pueda abrirlo
# con ningún programa. La base va cifrada con SQLCipher y el programa le pone la
# clave solo, sin pedírsela a nadie.
#
# La clave son 256 bits al azar (64 caracteres hexadecimales) y vive en el archivo
# `clave_base.py`, que NO está en git (este repo es PÚBLICO) y que la receta de
# armado del .exe copia a la carpeta de armado: PyInstaller la mete adentro del
# CyberBios.exe. Sin ese archivo (una PC de desarrollo, las pruebas) CLAVE_HEX es
# None y todo sigue con la base común, como antes.
#
# Es clave CRUDA (x'...') y no una frase a propósito: con una frase SQLCipher hace
# 256.000 vueltas de PBKDF2 en CADA conexión (medido: ~100 ms) y este programa abre
# una por consulta, además de las PCs que preguntan cada 5 segundos. La cruda no
# tiene ese costo (medido: 0,4 ms). Una clave de 256 bits al azar no necesita
# estirarse. Lo vigila TestComoAndaCifrada.test_abrir_una_conexion_sigue_siendo_rapido.
#
# Qué protege y qué no: protege el ARCHIVO (copiarlo, abrirlo con otro programa,
# ver los datos de los socios). No protege contra alguien que tenga el .exe y sepa
# desarmarlo: la clave está adentro. Es el mismo trato que se aceptó con la clave
# de los Clientes PC (ver CLAUDE.md). Si se pierde clave_base.py Y todos los .exe
# armados con ella, la base y sus copias no se pueden abrir nunca más: el dueño
# guarda una copia de la clave aparte.
try:
    from clave_base import CLAVE_HEX
except ImportError:
    CLAVE_HEX = None

_ENCABEZADO_BASE_COMUN = b"SQLite format 3\x00"
_CLAVE_BIEN_ARMADA = re.compile(r"[0-9a-fA-F]{64}")


class ErrorDeCifrado(Exception):
    """La base no se puede abrir por la clave o el cifrado. El mensaje está escrito
    para que lo lea el dueño (main.py lo muestra en un cartel al arrancar)."""


def cifrado_activo() -> bool:
    return CLAVE_HEX is not None


def _clave_validada() -> str:
    # PRAGMA key y ATTACH ... KEY no aceptan parámetros: la clave se pega en el
    # texto. Por eso se la exige de 64 hexadecimales y nada más (si no, un
    # clave_base.py roto podría meter cualquier cosa en el SQL).
    if not _CLAVE_BIEN_ARMADA.fullmatch(CLAVE_HEX or ""):
        raise ErrorDeCifrado(
            "La clave de la base de datos (clave_base.py) está mal armada: tiene que ser "
            "un texto de 64 letras y números (0-9, a-f)."
        )
    if not PUEDE_CIFRAR:
        # El sqlite3 común IGNORA en silencio "PRAGMA key": seguiría andando, pero con la
        # base sin cifrar y sin que nadie se entere. Mejor frenar.
        raise ErrorDeCifrado(
            "Este programa tiene una clave para cifrar la base de datos pero le falta el módulo "
            "que sabe cifrar (sqlcipher3). Hay que armarlo de nuevo con ese módulo instalado."
        )
    return CLAVE_HEX


def abrir_archivo(ruta: str, solo_lectura: bool = False) -> sqlite3.Connection:
    """
    Abre un archivo de base de datos del programa (la base en uso, una copia de
    seguridad) con la clave, si la hay. Es el único lugar que sabe poner la clave:
    todo lo que abra un archivo .db tiene que pasar por acá, nunca por
    `sqlite3.connect` a mano (en una base cifrada no leería nada).
    """
    conexion = sqlite3.connect(ruta)
    if cifrado_activo():
        conexion.execute(f"PRAGMA key = \"x'{_clave_validada()}'\"")
    if solo_lectura:
        conexion.execute("PRAGMA query_only = ON")
    return conexion


def _es_base_comun(ruta: str) -> bool:
    """Un archivo de SQLite sin cifrar empieza siempre con este texto; uno cifrado
    parece ruido desde el primer byte."""
    with open(ruta, "rb") as archivo:
        return archivo.read(len(_ENCABEZADO_BASE_COMUN)) == _ENCABEZADO_BASE_COMUN


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
    conexion = abrir_archivo(DB_PATH)
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

    Con la base cifrada la copia sale cifrada con la misma clave (los dos lados se
    abren con `abrir_archivo`): una copia en el pendrive o en otra PC no se lee
    sin el programa.
    """
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    origen = abrir_archivo(DB_PATH)
    try:
        con_destino = abrir_archivo(destino)
        try:
            origen.backup(con_destino)
        finally:
            con_destino.close()
    finally:
        origen.close()


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


def _valores_sql(valores) -> str:
    """Una lista de dominio.py (ROLES, ESTADOS_VENTA, TURNOS...) como va dentro
    de un CHECK (columna IN (...)): "'ADMIN', 'EMPLEADA'". Así los valores
    admitidos se escriben una sola vez, en dominio.py, y el esquema de una base
    nueva nunca queda desfasado (los valores son nombres fijos nuestros, sin
    comillas adentro)."""
    return ", ".join(f"'{valor}'" for valor in valores)


def _origenes_venta_sql() -> str:
    """Los orígenes de venta (dominio.ORIGENES_VENTA) como van dentro de un
    CHECK (origen IN (...))."""
    return _valores_sql(dominio.ORIGENES_VENTA)


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
            turno             TEXT NOT NULL CHECK (turno IN ({_valores_sql(dominio.TURNOS)})),
            total              REAL NOT NULL,
            estado            TEXT NOT NULL DEFAULT '{dominio.VENTA_CONFIRMADA}' CHECK (estado IN ({_valores_sql(dominio.ESTADOS_VENTA)})),
            anulada_por        INTEGER REFERENCES usuarios(id),
            anulada_fecha      TEXT,
            anulada_motivo     TEXT,
            origen             TEXT NOT NULL DEFAULT '{dominio.ORIGEN_KIOSKO}' CHECK (origen IN ({_origenes_venta_sql()}))
        )
    """


def _sql_tabla_de_bonos(tabla: str) -> str:
    """
    El CREATE TABLE de un catálogo de bonos de tiempo. Hay cuatro con el mismo
    esquema -- "bonos_tiempo" (walk-ins), "bonos_miembro" (exclusivo de
    socios), "bonos_playstation" (exclusivo de la consola) y "bonos_pcstream"
    (exclusivo de la PC de streaming) -- a propósito en tablas separadas: ver
    CLAUDE.md, "Hay CUATRO catálogos de bonos".
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
    """Cifra la base si hace falta, crea el esquema y actualiza bases anteriores sin
    reemplazar sus datos."""
    from database_esquema import inicializar_base_de_datos as crear_esquema
    preparar_cifrado()
    return crear_esquema()


# --------------------------------------------------------------------
# Cifrar la base común que ya tiene el dueño
# --------------------------------------------------------------------

def _quitar(ruta: str):
    try:
        os.remove(ruta)
    except FileNotFoundError:
        pass


def _copiar_comun(origen: str, destino: str):
    """Copia de seguridad de la base COMÚN (Online Backup API, igual que
    `_backup_consistente` pero sin clave en ninguno de los dos lados)."""
    os.makedirs(os.path.dirname(destino) or ".", exist_ok=True)
    de = sqlite3.connect(origen)
    try:
        a = sqlite3.connect(destino)
        try:
            de.backup(a)
        finally:
            a.close()
    finally:
        de.close()


def _exportar_cifrada(destino: str):
    """Escribe en `destino` una copia CIFRADA de la base común (DB_PATH): tablas, índices,
    disparadores, datos y los números automáticos (sqlite_sequence). La base común no se
    toca (se abre sin clave y se la lee nada más)."""
    clave = _clave_validada()
    comun = sqlite3.connect(DB_PATH)
    try:
        comun.execute(f"ATTACH DATABASE ? AS cifrada KEY \"x'{clave}'\"", (destino,))
        comun.execute("SELECT sqlcipher_export('cifrada')")
        comun.execute("DETACH DATABASE cifrada")
    finally:
        comun.close()


def _resumen_para_comparar(conexion) -> tuple:
    """Lo que tiene que ser igual antes y después de cifrar: cuántas filas tiene cada
    tabla, los números automáticos y el esquema completo."""
    tablas = [fila[0] for fila in conexion.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name NOT LIKE 'sqlite_%' ORDER BY name"
    )]
    filas = {tabla: conexion.execute(f'SELECT COUNT(*) FROM "{tabla}"').fetchone()[0] for tabla in tablas}
    hay_numeros = conexion.execute("SELECT 1 FROM sqlite_master WHERE name = 'sqlite_sequence'").fetchone()
    numeros = sorted(tuple(fila) for fila in conexion.execute("SELECT name, seq FROM sqlite_sequence")) \
        if hay_numeros else []
    esquema = sorted((fila[0], fila[1], fila[2] or "") for fila in
                     conexion.execute("SELECT type, name, sql FROM sqlite_master"))
    return filas, numeros, esquema


def _comprobar_que_quedo_igual(ruta_comun: str, ruta_cifrada: str):
    """Antes de reemplazar la base, se abre la cifrada con la clave y se compara con la
    común: mismas tablas con las mismas cantidades de filas, mismo esquema, mismos
    números automáticos y la base sana por dentro. Si algo no coincide la común no se
    toca. (Las pruebas comparan además el contenido fila por fila.)"""
    comun = sqlite3.connect(ruta_comun)
    cifrada = abrir_archivo(ruta_cifrada)
    try:
        try:
            integridad = cifrada.execute("PRAGMA integrity_check").fetchone()[0]
            resumen_cifrada = _resumen_para_comparar(cifrada)
        except sqlite3.DatabaseError as error:
            raise ErrorDeCifrado(f"La copia cifrada no se pudo leer con la clave ({error}).") from error
        if integridad != "ok":
            raise ErrorDeCifrado(f"La copia cifrada quedó dañada ({integridad}).")
        filas_comun, numeros_comun, esquema_comun = _resumen_para_comparar(comun)
        filas_cifrada, numeros_cifrada, esquema_cifrada = resumen_cifrada
        for tabla, cantidad in filas_comun.items():
            if filas_cifrada.get(tabla) != cantidad:
                raise ErrorDeCifrado(
                    f"La tabla {tabla} tiene {cantidad} filas y en la copia cifrada {filas_cifrada.get(tabla)}."
                )
        if set(filas_cifrada) != set(filas_comun):
            raise ErrorDeCifrado("La copia cifrada tiene otras tablas que la base original.")
        if numeros_comun != numeros_cifrada:
            raise ErrorDeCifrado("Los números automáticos de la copia cifrada no coinciden.")
        if esquema_comun != esquema_cifrada:
            raise ErrorDeCifrado("El esquema de la copia cifrada no coincide con el original.")
    finally:
        comun.close()
        cifrada.close()


def _cifrar_en_el_lugar():
    """
    Cifra la base común que ya está en DB_PATH, con todos sus datos. Pasos, cada uno
    pensado para que la base común nunca se pierda:
      1. una copia COMÚN en data/backups/antes_de_cifrar_*.db (sin copia no se cifra);
      2. se escribe la versión cifrada en un archivo aparte (kiosko.db.cifrando);
      3. se la abre con la clave y se la compara con la original;
      4. recién ahí reemplaza a kiosko.db (un solo movimiento de archivo).
    Si algo falla antes del paso 4, kiosko.db queda como estaba y se borran los restos.
    La copia del paso 1 es la única copia legible que queda: el dueño la borra cuando
    ya vio que todo anda (ver CLAUDE.md).
    """
    ahora = datetime.now().strftime("%Y%m%d_%H%M%S")
    copia = os.path.join(DATA_DIR, "backups", f"antes_de_cifrar_{ahora}.db")
    temporal = DB_PATH + ".cifrando"
    _quitar(temporal)  # un resto de un intento anterior que se cortó
    try:
        _copiar_comun(DB_PATH, copia)
        _exportar_cifrada(temporal)
        _comprobar_que_quedo_igual(DB_PATH, temporal)
        os.replace(temporal, DB_PATH)
    except BaseException:
        _quitar(temporal)
        _quitar(copia)  # la base no cambió: esa copia no hace falta
        raise


def preparar_cifrado():
    """
    Se llama en cada arranque, antes de crear o migrar el esquema.
      - Sin clave y base común (o sin base): nada que hacer.
      - Con clave y base común: la cifra (`_cifrar_en_el_lugar`).
      - Con clave y base ya cifrada: comprueba que la clave sirve.
      - Base cifrada sin clave, o con otra clave: ErrorDeCifrado, con un mensaje
        para el dueño. Nunca se intenta "arreglarla" ni se crea una base nueva al lado:
        sería perder de vista las ventas.
    Una base que no existe o está vacía no hace falta tocarla: se crea ya cifrada.
    """
    if not os.path.exists(DB_PATH) or os.path.getsize(DB_PATH) == 0:
        return
    es_comun = _es_base_comun(DB_PATH)
    if not cifrado_activo():
        if not es_comun:
            raise ErrorDeCifrado(
                "La base de datos está cifrada y esta copia del programa no trae la clave para "
                "abrirla (se armó sin ella). No se tocó nada: usá el CyberBios.exe de siempre."
            )
        return
    _clave_validada()
    if es_comun:
        try:
            _cifrar_en_el_lugar()
        except (OSError, sqlite3.Error) as error:  # disco lleno, archivo trabado por un antivirus...
            raise ErrorDeCifrado(
                f"No se pudo cifrar la base de datos ({error}). La base quedó como estaba y se puede "
                "seguir usando con el programa de antes."
            ) from error
        return
    conexion = abrir_archivo(DB_PATH)
    try:
        conexion.execute("SELECT COUNT(*) FROM sqlite_master").fetchone()
    except sqlite3.DatabaseError as error:
        if "not a database" not in str(error).lower():
            raise
        raise ErrorDeCifrado(
            "La base de datos no se puede abrir con la clave de este programa: está cifrada con "
            "otra clave (o el archivo se dañó). No se tocó nada. Usá el CyberBios.exe de siempre."
        ) from error
    finally:
        conexion.close()


def _respaldar_antes_de_migrar(motivo: str):
    """
    Copia de seguridad de la base ANTES de una migración que reconstruye una
    tabla con plata adentro (ver _migrar_check_origen_en_ventas). La carpeta
    sale de DATA_DIR al momento de llamar (no al importar el módulo), así los
    tests, que apuntan DATA_DIR a una carpeta temporal, nunca escriben en los
    backups reales.

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


# API histórica: los tests y los docs nombran estas funciones como database.X, y
# database_esquema las toma de acá.
#
# ESTE BLOQUE TIENE QUE QUEDAR AL FINAL DEL ARCHIVO. database_migraciones hace
# `from database import _sql_tabla_ventas, ...` al cargarse: si este import
# subiera al principio (como se ordenan normalmente), database_migraciones se
# cargaría antes de que existan esas funciones y el programa no arrancaría
# (ImportError; se comprobó en la revisión del 2026-10-17). Tampoco se puede
# sacar: _migrar_check_tipo_en_movimientos_saldo_miembro lee
# `database._TIPOS_MOVIMIENTO_SALDO` a propósito, para que las pruebas puedan
# reemplazarlo acá.
from database_migraciones import (
    _agregar_columna_si_falta,
    _migrar_columnas_permisos,
    _migrar_columna_ultima_conexion_estaciones,
    _migrar_columna_ultima_ip_estaciones,
    _migrar_columna_ip_asentada_estaciones,
    _migrar_columna_cliente_cerrado_desde_estaciones,
    _migrar_columnas_actualizacion_estaciones,
    _migrar_columna_cliente_arranque_estaciones,
    _migrar_columna_miembro_en_sesiones,
    _migrar_columna_whatsapp_en_miembros,
    _migrar_columna_desde_ip_en_sesiones,
    _sql_tabla_movimientos_saldo_miembro,
    _reconstruir_tabla,
    _admite_todos_los_tipos,
    _migrar_referencia_bono_en_movimientos_saldo_miembro,
    _migrar_check_tipo_en_movimientos_saldo_miembro,
    _sql_tabla_comandos_pc,
    _migrar_check_tipo_en_comandos_pc,
    _sql_tabla_eventos_admin_pc,
    _migrar_check_tipo_en_eventos_admin_pc,
    _migrar_borrar_clave_vieja_de_clientes_pc,
    _migrar_columna_origen_en_ventas,
    _migrar_columnas_origen_en_cierres,
    _migrar_check_origen_en_ventas,
    _COLUMNAS_MOVIMIENTOS_SALDO,
    _TIPOS_MOVIMIENTO_SALDO_ORIGINALES,
    _TIPOS_MOVIMIENTO_SALDO,
    _TIPOS_COMANDO_PC_ORIGINALES,
    _TIPOS_EVENTO_ADMIN_PC_ORIGINALES,
)
