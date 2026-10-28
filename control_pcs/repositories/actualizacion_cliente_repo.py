"""
actualizacion_cliente_repo.py
=============================
Actualizar el Cliente PC (PCcliente.exe, carpeta hermana "CLIENTE PC") de todas las PCs desde
acá, sin ir PC por PC (pedido del dueño, 2026-10-18). Se maneja desde Configuración ADMIN ->
Gestionar Estaciones -> "Actualizar el Cliente PC de las PCs..." (`pcs_actualizacion_dialogo`).

Cómo viaja una versión:
1. El Admin elige el PCcliente.exe nuevo y este repo lo FIRMA (`publicar`) con la clave privada
   que vive solo en esta PC, fuera de los repos (`ruta_clave_privada`; este repo es PÚBLICO: acá
   solo está la clave pública, que puede ser pública). Lo firmado es un "manifiesto": un texto
   JSON con la versión, el tamaño y la huella SHA-256 del exe.
2. El Admin marca a qué PCs va (`guardar_seleccion`; rehecho a pedido del dueño el 2026-10-19:
   antes eran unas "de prueba" y después todas, y no le resultaba claro). Una versión recién
   cargada no va a ninguna hasta que las marque.
3. En cada GET /estado, la PC recibe `cliente_version` (`version_para_estacion`). Si es más
   nueva que la suya, pide GET /cliente_pc (el manifiesto y la firma) y GET /cliente_pc/exe,
   aunque haya un cliente usándola, comprueba todo y la deja lista; su lanzador la pone en uso en
   el próximo reinicio y vuelve solo a la anterior si no arranca bien (ver CLIENTE PC/lanzador.py).
   Si recibe None (la desmarcaron), borra la que tenga copiada y sin poner.
4. Cada PC cuenta en cada consulta su versión, su carpeta y cómo va (`registrar_reporte`), y eso
   se ve en la pantalla, en palabras (`estado_de_las_pcs` y `situacion`).
5. Si una PC ya la copió, se reinició y sigue sin ponerla, la pantalla dice por qué (pedido del
   dueño, 2026-10-22: muchas decían «Actualizada con éxito» y al reiniciarlas seguían igual):
   `seguir_la_copia`, con los segundos que lleva prendida cada PC (`encendida`).

Dónde vive: `data/cliente_pc/PCcliente.exe` y `data/cliente_pc/version.json` (el manifiesto y su
firma), como el fondo de pantalla: fuera de la base y de git. Si se pierde `data/`, se vuelve a
cargar la versión. La versión es un número que sale de la fecha y hora en que se cargó
(AAAAMMDDhhmmss) y siempre crece: para volver a una versión vieja, se la carga de nuevo.

Ese número es el que comparan las PCs, pero el dueño ve otro (pedido del 2026-10-19): el
"número de versión" de cada PCcliente.exe, V1, V1.1 ... V1.9, V2 (CLIENTE PC/version_cliente.py).
Se lee del exe al cargarlo (`numero_de_version_del_exe`) y cada PC lo manda como `v` en cada
consulta (`registrar_reporte`). Un exe armado antes de la V1 no lo tiene.

Lo leen los hilos del servidor de red y lo escribe la pantalla, en el mismo programa: un candado
evita leer a medio cambiar y lo leído se guarda en memoria (con la fecha y el tamaño de los
archivos) para no abrir el disco en cada consulta de cada PC.

Versiones EN CARPETA (desde la V2 del Cliente PC, pedido del dueño 2026-10-28: la pantalla de
bloqueo tardaba 21-30 s en aparecer, casi todo desempaquetando el exe "todo en uno" en cada
arranque; ver CLIENTE PC/README.md, "Arranque sin desempaquetar"). El Admin carga un .zip con la
carpeta (PCcliente.exe y `_internal\\`, lo arma `CLIENTE PC/armar_paquete.py`) y se firma un
manifiesto que dice "PCcliente-carpeta" con la huella y el tamaño del .zip y la lista de los
archivos de adentro, con la huella y el tamaño de cada uno (`archivos`): la PC desempaqueta el .zip
una sola vez y comprueba cada archivo. Solo se le manda a las PCs que avisan que la saben poner
(`formato=2` en la consulta: Cliente PC V1.9 o más con el Lanzador 3); a las demás no les toca
ninguna y la pantalla dice que les falta la V1.9 (`FALTA_PUENTE`). Se guarda como
`data/cliente_pc/PCcliente.zip` en vez de `PCcliente.exe`.
"""

import base64
import hashlib
import io
import json
import os
import re
import struct
import threading
import time
import zipfile
from datetime import datetime, timedelta
from pathlib import Path

import database
import dominio
from database import conexion_db

# La mitad pública de la clave con que se firman las versiones. Tiene que ser la MISMA que
# `CLIENTE PC/actualizacion.py` (CLAVE_PUBLICA_FIRMA): es la que las PCs usan para comprobar.
CLAVE_PUBLICA_FIRMA = "r2y5vYxbu1ZZswyhSkn8hmBBe0KpaSjIr6VpZPG1WhE="

PROGRAMA = "PCcliente"
CARPETA = "cliente_pc"
NOMBRE_EXE = "PCcliente.exe"
NOMBRE_VERSION = "version.json"
TAMANO_MAXIMO_EXE = 150 * 1024 * 1024
# Una versión en carpeta (ver arriba). Los topes y las reglas de los nombres tienen que ser los
# MISMOS que comprueba cada PC (`CLIENTE PC/actualizacion.py`): si no, se firmaría una lista que las
# PCs rechazan.
PROGRAMA_EN_CARPETA = "PCcliente-carpeta"
NOMBRE_ZIP = "PCcliente.zip"
ARCHIVOS_MAXIMOS = 20_000
TAMANO_MAXIMO_CARPETA = 600 * 1024 * 1024
_NOMBRES_RESERVADOS = {"version.json", "arranco_bien", "pccliente.zip"}
_MARCA_ZIP = b"PK\x03\x04"
# Lo que manda una PC como `formato` cuando sabe poner una versión en carpeta (Cliente PC V1.9 o
# más, con el Lanzador 3).
FORMATO_EN_CARPETA = 2
# Lo que identifica un PCcliente.exe por dentro: PyInstaller deja, al final del archivo, la lista
# de lo que lleva adentro, y ahí está el nombre del programa principal (cliente_pc). Ataja el error
# de elegir otro exe (CyberBios.exe, Lanzador.exe): las PCs lo abrirían en lugar del Cliente PC.
_MARCA_DEL_CLIENTE = b"cliente_pc"
_FINAL_A_REVISAR = 512 * 1024
# El número de versión que PCcliente.spec graba en el exe (lo que Windows muestra en Propiedades ->
# Detalles): una estructura que empieza con el nombre "VS_VERSION_INFO" y, dos bytes después, una
# marca fija seguida de los números. Va en la parte de adelante del exe, antes de lo comprimido.
_NOMBRE_DATOS_DE_VERSION = "VS_VERSION_INFO\0".encode("utf-16-le")
_MARCA_DATOS_DE_VERSION = struct.pack("<I", 0xFEEF04BD)
_PRINCIPIO_A_REVISAR = 4 * 1024 * 1024
# Cómo se escribe un número de versión: "1", "1.1" ... "1.9", "2" (como CLIENTE PC/version_cliente.py).
_FORMATO_NUMERO_DE_VERSION = re.compile(r"[1-9]\d{0,3}(\.[1-9])?")

_CLAVE_ALCANCE = "actualizacion_cliente_alcance"
_TOPE_CARPETA = 260
_TOPE_DETALLE = 300

_candado = threading.Lock()
# Lo último leído del disco: de qué archivos salió (fechas y tamaños), el paquete y el exe.
_ultimo = {"clave": None, "paquete": None, "exe": None}
# Lo último que contó cada PC (estacion_id -> tupla), para escribir en la base solo si cambió:
# cada PC consulta cada 5 s.
_reportes = {}
# Lo mismo para el número de versión que manda cada PC (estacion_id -> "1.2" o None).
_numeros_de_version = {}
# Y para el seguimiento de la copia que espera el reinicio (estacion_id -> dict o None).
_seguimientos = {}
# Qué formato sabe poner cada PC, según su última consulta (estacion_id -> 1 o 2). Solo en memoria:
# cada PC lo vuelve a decir cada 5 s, y `version_para_estacion` se pregunta en la misma consulta.
_formatos = {}
# Cuánto más tarde tiene que haber arrancado Windows para contar como un reinicio: la hora de
# arranque sale de restarle a la hora del mostrador los segundos que la PC lleva prendida, y
# baila unos segundos de una consulta a otra.
MARGEN_REINICIO_SEGUNDOS = 120
_candado_reportes = threading.Lock()


def ruta_clave_privada() -> Path:
    """Dónde está la clave privada de firma: en la carpeta del usuario de Windows de esta PC, nunca
    en un repo ni en data/."""
    return Path.home() / "FirmaClientePC" / "clave_firma_cliente_pc.pem"


def _carpeta() -> str:
    return os.path.join(database.DATA_DIR, CARPETA)


def _ruta(nombre: str) -> str:
    return os.path.join(_carpeta(), nombre)


# --------------------------------------------------------------------
# Cargar y firmar una versión
# --------------------------------------------------------------------
def es_un_cliente_pc(datos: bytes) -> bool:
    """¿`datos` es un PCcliente.exe (armado con PCcliente.spec) y no otro programa?"""
    return datos[:2] == b"MZ" and _MARCA_DEL_CLIENTE in datos[-_FINAL_A_REVISAR:]


def numero_de_version_del_exe(datos: bytes):
    """El número de versión ("1.2" = V1.2) grabado en un PCcliente.exe, o None si no tiene (los
    armados antes de la V1)."""
    principio = datos[:_PRINCIPIO_A_REVISAR]
    nombre = principio.find(_NOMBRE_DATOS_DE_VERSION)
    if nombre < 0:
        return None
    despues = nombre + len(_NOMBRE_DATOS_DE_VERSION)
    marca = principio.find(_MARCA_DATOS_DE_VERSION, despues, despues + 8)
    if marca < 0 or len(principio) < marca + 12:
        return None
    _marca, _estructura, numeros = struct.unpack_from("<III", principio, marca)
    entero, decimo = numeros >> 16, numeros & 0xFFFF
    return numero_de_version_valido(str(entero) if decimo == 0 else f"{entero}.{decimo}")


def numero_de_version_valido(valor):
    """`valor` si es un número de versión bien escrito ("1", "1.2"), o None."""
    texto = str(valor or "").strip()
    return texto if _FORMATO_NUMERO_DE_VERSION.fullmatch(texto) else None


def nombre_de_version(numero) -> str:
    """"V1.2" para "1.2"; vacío si no hay número."""
    return f"V{numero}" if numero else ""


def es_mas_vieja(numero, otro) -> bool:
    """¿La versión `numero` es anterior a `otro`? ("1.9" es anterior a "2")."""
    def partes(texto):
        entero, _punto, decimo = texto.partition(".")
        return int(entero), int(decimo or 0)
    return partes(numero) < partes(otro)


def _cargar_clave_privada():
    ruta = ruta_clave_privada()
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    except ImportError:
        raise ValueError("A este programa le falta la biblioteca \"cryptography\" para firmar versiones.")
    try:
        privada = serialization.load_pem_private_key(ruta.read_bytes(), password=None)
    except FileNotFoundError:
        raise ValueError(
            f"No está la clave para firmar versiones en:\n{ruta}\n\n"
            "Copiala ahí desde el pendrive donde la guardaste.")
    except (ValueError, TypeError):
        raise ValueError(f"La clave para firmar versiones de\n{ruta}\nestá rota.")
    publica = privada.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw) \
        if isinstance(privada, Ed25519PrivateKey) else b""
    if base64.b64encode(publica).decode() != CLAVE_PUBLICA_FIRMA:
        raise ValueError(
            f"La clave de\n{ruta}\nno es la que conocen las PCs: no aceptarían lo que se firme con ella.")
    return privada


def _version_nueva(ahora: datetime, anterior) -> int:
    version = int(ahora.strftime("%Y%m%d%H%M%S"))
    return max(version, (anterior or 0) + 1)


def es_en_carpeta(datos: bytes) -> bool:
    """¿`datos` es el .zip de una versión en carpeta (y no un PCcliente.exe)?"""
    return datos[:4] == _MARCA_ZIP


def numero_de_version_del_paquete(datos: bytes):
    """`numero_de_version_del_exe` de lo que se va a cargar: el PCcliente.exe, o el que está adentro
    del .zip de una versión en carpeta. None si no tiene o el .zip no se puede leer."""
    if not es_en_carpeta(datos):
        return numero_de_version_del_exe(datos)
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as paquete:
            return numero_de_version_del_exe(paquete.read(NOMBRE_EXE))
    except (zipfile.BadZipFile, zipfile.LargeZipFile, KeyError, EOFError, RuntimeError, NotImplementedError):
        return None


def _ruta_valida(nombre: str) -> bool:
    """La misma regla que `CLIENTE PC/actualizacion.ruta_valida`: partes separadas por "/", sin
    "..", sin disco ni barra al principio, sin "\\" ni ":"."""
    if not nombre or "\\" in nombre or ":" in nombre or nombre.startswith("/"):
        return False
    return all(parte not in ("", ".", "..") and parte == parte.strip() for parte in nombre.split("/"))


def _lista_del_zip(datos: bytes) -> tuple:
    """(el PCcliente.exe de adentro, la lista {ruta: [huella, tamaño]}) del .zip de una versión en
    carpeta, con las mismas reglas que va a comprobar cada PC. Levanta ValueError, con un mensaje
    para mostrar, si el .zip no sirve."""
    rearmar = "volvé a armarlo con armar_paquete.py (CLIENTE PC\\dist\\PCcliente_V2.zip)"
    try:
        with zipfile.ZipFile(io.BytesIO(datos)) as paquete:
            entradas = [info for info in paquete.infolist() if not info.is_dir()]
            if not 0 < len(entradas) <= ARCHIVOS_MAXIMOS:
                raise ValueError(f"El .zip trae {len(entradas)} archivos: no parece el Cliente PC.")
            archivos, vistos, total = {}, set(), 0
            for info in entradas:
                nombre = info.filename
                if (not _ruta_valida(nombre) or nombre.lower() in vistos
                        or nombre.lower() in _NOMBRES_RESERVADOS):
                    raise ValueError(f"El .zip trae un archivo que no se puede usar ({nombre}): {rearmar}.")
                vistos.add(nombre.lower())
                huella, tamano = hashlib.sha256(), 0
                with paquete.open(info) as archivo:
                    for pedazo in iter(lambda: archivo.read(1024 * 1024), b""):
                        huella.update(pedazo)
                        tamano += len(pedazo)
                        total += len(pedazo)
                        if total > TAMANO_MAXIMO_CARPETA:
                            raise ValueError("Lo que trae el .zip pesa demasiado: no parece el Cliente PC.")
                archivos[nombre] = [huella.hexdigest(), tamano]
            # Un archivo y una carpeta con el mismo nombre ("a" y "a/b") no se pueden armar en la PC.
            carpetas = {nombre.lower().rsplit("/", 1)[0] for nombre in archivos if "/" in nombre}
            carpetas |= {"/".join(c.split("/")[:i]) for c in carpetas for i in range(1, c.count("/") + 1)}
            if carpetas & vistos:
                raise ValueError(f"El .zip trae un archivo y una carpeta con el mismo nombre: {rearmar}.")
            if NOMBRE_EXE not in archivos:
                raise ValueError(f"En el .zip no está {NOMBRE_EXE} (arriba de todo): {rearmar}.")
            return paquete.read(NOMBRE_EXE), archivos
    except (zipfile.BadZipFile, zipfile.LargeZipFile, EOFError, RuntimeError, NotImplementedError) as error:
        raise ValueError(f"El .zip está roto: {rearmar}.") from error


def publicar(datos_exe: bytes, ahora: datetime = None) -> dict:
    """Firma `datos_exe` (un PCcliente.exe, o el .zip de una versión en carpeta) y lo deja como la
    versión de las PCs. No va a ninguna hasta que el Admin las marque: se vacía la selección.
    Devuelve el manifiesto. Levanta ValueError, con un mensaje para mostrarle a la persona, si no es
    el Cliente PC o no se puede firmar."""
    en_carpeta = es_en_carpeta(datos_exe)
    if not en_carpeta and (not datos_exe or not datos_exe.startswith(b"MZ")):
        raise ValueError("El archivo elegido no es un programa (.exe) ni una versión en carpeta (.zip).")
    if len(datos_exe) > TAMANO_MAXIMO_EXE:
        raise ValueError(f"El archivo pesa {len(datos_exe) / 1024 / 1024:.0f} MB: no parece el PCcliente.exe.")
    exe, archivos = _lista_del_zip(datos_exe) if en_carpeta else (datos_exe, None)
    if not es_un_cliente_pc(exe):
        raise ValueError(
            "Ese .exe no es el Cliente PC (PCcliente.exe). Elegí el que está en "
            "CLIENTE PC\\dist\\PCcliente.exe." if not en_carpeta else
            "El PCcliente.exe de ese .zip no es el Cliente PC. Elegí el que deja armar_paquete.py en "
            "CLIENTE PC\\dist.")
    privada = _cargar_clave_privada()
    ahora = ahora or datetime.now()
    numero = numero_de_version_del_exe(exe)
    with _candado:
        anterior = _leer_del_disco()
        version = _version_nueva(ahora, anterior["paquete"]["version"] if anterior["paquete"] else None)
        datos_del_manifiesto = {
            "programa": PROGRAMA_EN_CARPETA if en_carpeta else PROGRAMA, "version": version,
            "sha256": hashlib.sha256(datos_exe).hexdigest(),
            "tamano": len(datos_exe), "creado": ahora.isoformat(timespec="seconds"),
        }
        if archivos is not None:
            datos_del_manifiesto["archivos"] = archivos
        if numero:   # las PCs no lo miran: es para mostrar
            datos_del_manifiesto["v"] = numero
        manifiesto = json.dumps(datos_del_manifiesto, sort_keys=True)
        firma = base64.b64encode(privada.sign(manifiesto.encode("utf-8"))).decode()
        os.makedirs(_carpeta(), exist_ok=True)
        # Primero el exe y después el manifiesto: una PC que pide justo en el medio recibe un exe
        # que no coincide con el manifiesto, lo descarta y vuelve a probar. El manifiesto dice cuál
        # de los dos archivos vale; el otro (de la versión anterior, si era del otro tipo) se borra.
        nombre, sobra = (NOMBRE_ZIP, NOMBRE_EXE) if en_carpeta else (NOMBRE_EXE, NOMBRE_ZIP)
        _escribir(_ruta(nombre), datos_exe)
        _escribir(_ruta(NOMBRE_VERSION), json.dumps({"manifiesto": manifiesto, "firma": firma}).encode("utf-8"))
        if os.path.exists(_ruta(sobra)):
            os.remove(_ruta(sobra))
        _ultimo.update(clave=None, paquete=None, exe=None)
    guardar_seleccion(())
    return json.loads(manifiesto)


def _escribir(ruta: str, datos: bytes):
    """Escribe en un archivo aparte y recién después lo pone en su lugar (un corte de luz no deja
    un archivo cortado), reintentando si un antivirus lo tiene trabado un instante."""
    temporal = ruta + ".nuevo"
    try:
        with open(temporal, "wb") as archivo:
            archivo.write(datos)
        for intento in range(5):
            try:
                os.replace(temporal, ruta)
                break
            except PermissionError:
                if intento == 4:
                    raise
                time.sleep(0.1)
    finally:
        if os.path.exists(temporal):
            os.remove(temporal)


# --------------------------------------------------------------------
# Leer la versión cargada (lo usa el servidor de red)
# --------------------------------------------------------------------
def _estado_del_archivo(nombre: str):
    try:
        estado = os.stat(_ruta(nombre))
    except FileNotFoundError:
        return None
    return estado.st_mtime_ns, estado.st_size


def _leer_del_disco() -> dict:
    """{"paquete": {...} o None, "exe": bytes o None} ("exe": el PCcliente.exe, o el .zip de una
    versión en carpeta). Se llama con el candado puesto. Un version.json roto, o sin el archivo que
    dice, cuenta como que no hay versión."""
    estados = tuple(_estado_del_archivo(n) for n in (NOMBRE_VERSION, NOMBRE_EXE, NOMBRE_ZIP))
    if estados[0] is None:
        _ultimo.update(clave=None, paquete=None, exe=None)
        return _ultimo
    if _ultimo["clave"] != estados:
        try:
            with open(_ruta(NOMBRE_VERSION), "rb") as archivo:
                guardado = json.loads(archivo.read().decode("utf-8"))
            contenido = json.loads(guardado["manifiesto"])
            en_carpeta = contenido.get("programa") == PROGRAMA_EN_CARPETA
            paquete = {"manifiesto": guardado["manifiesto"], "firma": guardado["firma"],
                       "version": int(contenido["version"]), "tamano": int(contenido["tamano"]),
                       "creado": contenido.get("creado", ""), "v": numero_de_version_valido(contenido.get("v")),
                       "en_carpeta": en_carpeta}
            with open(_ruta(NOMBRE_ZIP if en_carpeta else NOMBRE_EXE), "rb") as archivo:
                exe = archivo.read()
        except (OSError, ValueError, KeyError, TypeError):
            paquete, exe = None, None
        _ultimo.update(clave=estados, paquete=paquete, exe=exe)
    return _ultimo


def paquete():
    """La versión cargada: {"manifiesto", "firma", "version", "tamano", "creado", "v", "en_carpeta"},
    o None ("v": su número de versión, "1.2" = V1.2, o None si es un exe armado antes de la V1;
    "en_carpeta": si es una versión en carpeta, un .zip)."""
    with _candado:
        return _leer_del_disco()["paquete"]


def datos_exe():
    """Los bytes de la versión cargada (el PCcliente.exe, o el .zip de una versión en carpeta), o None."""
    with _candado:
        return _leer_del_disco()["exe"]


def version_publicada():
    encontrado = paquete()
    return encontrado["version"] if encontrado else None


# --------------------------------------------------------------------
# A qué PCs va
# --------------------------------------------------------------------
def obtener_seleccion() -> set:
    """Los ids de las estaciones marcadas para recibir la versión cargada. Sin nada guardado:
    ninguna. Lo que guardaba la pantalla vieja ("prueba" y "para_todas") cuenta como las de
    prueba marcadas."""
    with conexion_db() as conexion:
        fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_ALCANCE,)).fetchone()
    try:
        datos = json.loads(fila["valor"]) if fila else {}
        return {int(i) for i in datos.get("seleccionadas", datos.get("prueba")) or []}
    except (ValueError, TypeError, AttributeError):
        return set()


def guardar_seleccion(ids):
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_ALCANCE, json.dumps({"seleccionadas": sorted({int(i) for i in ids})})),
        )


def version_para_estacion(estacion_id: int):
    """La versión que le toca a esa PC (viaja en cada GET /estado como `cliente_version`), o None si
    no hay ninguna cargada, esa PC no está marcada o la versión es en carpeta y esa PC no avisó
    que la sabe poner (`formato` en su consulta, que `registrar_reporte` guarda justo antes)."""
    cargada = paquete()
    if cargada is None or estacion_id not in obtener_seleccion():
        return None
    if cargada["en_carpeta"]:
        with _candado_reportes:
            if _formatos.get(estacion_id, 1) < FORMATO_EN_CARPETA:
                return None
    return cargada["version"]


def sabe_poner_carpetas(estacion_id: int, numero_lanzador=None) -> bool:
    """¿Esa PC sabe poner una versión en carpeta? Lo que dijo en su última consulta; si no consultó
    desde que se abrió el programa, se adivina por su Lanzador.exe (el 3 o más), que queda en la base."""
    with _candado_reportes:
        if estacion_id in _formatos:
            return _formatos[estacion_id] >= FORMATO_EN_CARPETA
    return (numero_lanzador or 0) >= 3


# --------------------------------------------------------------------
# Lo que cuenta cada PC
# --------------------------------------------------------------------
def registrar_reporte(estacion_id: int, parametros: dict, ahora: datetime = None):
    """Guarda lo que contó la PC en su GET /estado (`parametros`: los de la consulta, ya de a uno):
    `version`, `carpeta`, `act`, `act_detalle` y `act_version` (la que está copiando o ya copió;
    un Cliente PC de antes del 2026-10-19 no la manda) y `lanzador`, el número de su Lanzador.exe
    (desde la V1.4). Un Cliente PC sin actualización automática no manda nada de eso y no se toca
    nada. Aparte, `v`: su número de versión (lo manda desde la V1, con lanzador o sin él; ver
    `_registrar_numero_de_version`), y `encendida`, los segundos que lleva prendida la PC, para
    seguir la copia a través de un reinicio (`_seguir_la_copia_de`). Solo escribe en la base si
    cambió algo. Y `formato`: 2 si sabe poner una versión en carpeta (desde la V1.9, con el Lanzador
    3); queda solo en memoria (`version_para_estacion`)."""
    _registrar_numero_de_version(estacion_id, parametros.get("v"))
    if "version" not in parametros:
        return
    with _candado_reportes:
        _formatos[estacion_id] = _numero(parametros.get("formato")) or 1
    version = _numero(parametros.get("version"))
    carpeta = str(parametros.get("carpeta") or "")[:_TOPE_CARPETA]
    estado = str(parametros.get("act") or "")
    if estado not in dominio.ESTADOS_ACTUALIZACION_CLIENTE:
        estado = ""
    detalle = str(parametros.get("act_detalle") or "")[:_TOPE_DETALLE] if estado else ""
    bajada = _numero(parametros.get("act_version")) if estado else None
    nuevo = (version, carpeta, estado, detalle, bajada, _numero(parametros.get("lanzador")))
    _seguir_la_copia_de(estacion_id, estado, bajada, version, _numero(parametros.get("encendida")), ahora)
    with _candado_reportes:
        if _reportes.get(estacion_id) == nuevo:
            return
    with conexion_db() as conexion:
        conexion.execute(
            """
            UPDATE estaciones SET version_cliente = ?, carpeta_cliente = ?, estado_actualizacion = ?,
                                  detalle_actualizacion = ?, version_bajada = ?, numero_lanzador = ?
            WHERE id = ?
            """,
            (*nuevo, estacion_id),
        )
    with _candado_reportes:
        _reportes[estacion_id] = nuevo


def seguir_la_copia(previo, estado: str, bajada, instalada, arranque):
    """El seguimiento de la copia que espera el reinicio en una PC, con lo que contó en esta
    consulta: `previo` (lo anterior, o None), su `estado`, la versión que copió (`bajada`), la
    que tiene puesta (`instalada`) y cuándo arrancó Windows (`arranque`, un datetime, o None si su
    Cliente PC no lo dice). Devuelve {"version", "arranque", "salio", "motivo"}, o None si no hay
    nada que seguir.

    La idea (pedido del dueño, 2026-10-22): una PC que copió la versión X la pone sola en el
    próximo reinicio. Si después de un reinicio (Windows arrancó más tarde que cuando se la vio
    copiada) sigue con X copiada y sin poner, hay dos causas, y se distinguen por lo que pasó en
    el medio:
    - se la vio sin X copiada (`salio`) y la volvió a copiar: el reinicio borró la copia, la
      carpeta no está excluida en Shadow Defender -> NO_SE_PUSO_SE_BORRO;
    - la copia siguió ahí todo el tiempo: nadie la puso, la PC arranca el Cliente PC sin pasar
      por Lanzador.exe (la tarea programada apunta a otro lado) -> NO_SE_PUSO_SIN_LANZADOR.
    El motivo queda hasta que la PC pone la versión o le toca otra."""
    if estado == dominio.ACTUALIZACION_DESCARGADA and bajada is not None:
        if not previo or previo.get("version") != bajada:
            return {"version": bajada, "arranque": _iso(arranque), "salio": False, "motivo": ""}
        antes = _fecha(previo.get("arranque"))
        if arranque is not None and antes is None:
            return {**previo, "arranque": _iso(arranque), "salio": False}
        if arranque is not None and arranque > antes + timedelta(seconds=MARGEN_REINICIO_SEGUNDOS):
            motivo = dominio.NO_SE_PUSO_SE_BORRO if previo.get("salio") else dominio.NO_SE_PUSO_SIN_LANZADOR
            return {**previo, "arranque": _iso(arranque), "salio": False, "motivo": motivo}
        # Sin reinicio de por medio (la desmarcaron y la volvieron a marcar): sigue como estaba.
        return {**previo, "salio": False}
    if not previo or (instalada is not None and instalada >= previo["version"]):
        return None     # nada copiado, o ya la puso
    if estado == dominio.ACTUALIZACION_FALLO:
        return None     # la puso y no arrancó: eso ya lo dice el estado
    return {**previo, "salio": True}


def _seguir_la_copia_de(estacion_id: int, estado: str, bajada, instalada, encendida, ahora):
    """`seguir_la_copia` para una PC, guardado en `estaciones.seguimiento_actualizacion` solo si
    cambió (casi nunca: al copiar, al reiniciar y al ponerla)."""
    arranque = (ahora or datetime.now()) - timedelta(seconds=encendida) if encendida is not None else None
    with _candado_reportes:
        conocido = estacion_id in _seguimientos
        previo = _seguimientos.get(estacion_id)
    if not conocido:
        with conexion_db() as conexion:
            fila = conexion.execute("SELECT seguimiento_actualizacion FROM estaciones WHERE id = ?",
                                    (estacion_id,)).fetchone()
        previo = _leer_seguimiento(fila["seguimiento_actualizacion"] if fila else None)
    nuevo = seguir_la_copia(previo, estado, bajada, instalada, arranque)
    if nuevo != previo:
        with conexion_db() as conexion:
            conexion.execute("UPDATE estaciones SET seguimiento_actualizacion = ? WHERE id = ?",
                             (json.dumps(nuevo) if nuevo else None, estacion_id))
    with _candado_reportes:
        _seguimientos[estacion_id] = nuevo


def _leer_seguimiento(texto):
    """El seguimiento guardado (JSON), o None si no hay o está roto."""
    try:
        datos = json.loads(texto) if texto else None
    except ValueError:
        return None
    return datos if isinstance(datos, dict) and isinstance(datos.get("version"), int) else None


def _iso(momento):
    return momento.isoformat(timespec="seconds") if momento is not None else None


def _fecha(texto):
    try:
        return datetime.fromisoformat(texto) if texto else None
    except (ValueError, TypeError):
        return None


def _registrar_numero_de_version(estacion_id: int, valor):
    """El número de versión que mandó la PC ("1.2" = V1.2), o NULL si no mandó ninguno (un Cliente
    PC armado antes de la V1: también si una PC volvió a uno así). Solo escribe si cambió."""
    numero = numero_de_version_valido(valor)
    with _candado_reportes:
        if estacion_id in _numeros_de_version and _numeros_de_version[estacion_id] == numero:
            return
    with conexion_db() as conexion:
        conexion.execute("UPDATE estaciones SET numero_version_cliente = ? WHERE id = ?", (numero, estacion_id))
    with _candado_reportes:
        _numeros_de_version[estacion_id] = numero


def _numero(valor):
    texto = str(valor or "").strip()
    return int(texto) if texto.isdigit() else None


def olvidar_reportes():
    """Que la próxima consulta de cada PC se vuelva a escribir (para los tests)."""
    with _candado_reportes:
        _reportes.clear()
        _numeros_de_version.clear()
        _seguimientos.clear()
        _formatos.clear()


def estado_de_las_pcs(ahora: datetime = None) -> list:
    """Una fila por estación activa, en el orden de siempre: lo que contó su Cliente PC, si está
    marcada, qué versión le toca, si se conectó hace poco y si tiene una sesión en curso. `v` es
    el número de versión que mandó la PC y `v_le_toca`, el de la versión que le toca; `lanzador`,
    el número de su Lanzador.exe; `no_se_puso`, por qué la copia que tiene no se puso al
    reiniciarla (uno de dominio.NO_SE_PUSO_*, o vacío; ver `seguir_la_copia`)."""
    from control_pcs.repositories import pcs_repo   # aquí: pcs_repo no depende de este repo
    seleccion = obtener_seleccion()
    cargada = paquete()
    publicada = cargada["version"] if cargada else None
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        ocupadas = {fila["estacion_id"] for fila in conexion.execute(
            "SELECT DISTINCT estacion_id FROM sesiones_pc WHERE estado = ?", (dominio.SESION_ACTIVA,))}
    filas = []
    for estacion in pcs_repo.listar_estaciones():
        seleccionada = estacion["id"] in seleccion
        seguimiento = _leer_seguimiento(estacion["seguimiento_actualizacion"]) or {}
        filas.append({
            "id": estacion["id"], "nombre": estacion["nombre"],
            "version": estacion["version_cliente"], "carpeta": estacion["carpeta_cliente"] or "",
            "estado": estacion["estado_actualizacion"] or "", "detalle": estacion["detalle_actualizacion"] or "",
            "version_bajada": estacion["version_bajada"],
            "v": estacion["numero_version_cliente"],
            "lanzador": estacion["numero_lanzador"],
            "no_se_puso": ((seguimiento.get("motivo") or "")
                           if seguimiento.get("version") == estacion["version_bajada"] else ""),
            "ultima_conexion": estacion["ultima_conexion"],
            "conectada": _conectada(estacion["ultima_conexion"], ahora, pcs_repo.UMBRAL_ENLACE_SEGUNDOS),
            "seleccionada": seleccionada,
            "le_toca": publicada if publicada is not None and seleccionada else None,
            "v_le_toca": cargada["v"] if cargada and seleccionada else None,
            "va_en_carpeta": bool(cargada and cargada["en_carpeta"]),
            "sabe_poner_carpetas": sabe_poner_carpetas(estacion["id"], estacion["numero_lanzador"]),
            "ocupada": estacion["id"] in ocupadas,
        })
    return filas


def _conectada(ultima_conexion, ahora: datetime, umbral: int) -> bool:
    """¿Consultó hace `umbral` segundos o menos? El mismo criterio que "SIN CLIENTE" en Control de PCs."""
    if not ultima_conexion:
        return False
    try:
        return (ahora - datetime.fromisoformat(ultima_conexion)).total_seconds() <= umbral
    except (ValueError, TypeError):
        return False


# Cómo está cada PC con la actualización, para la pantalla (`situacion`).
NUNCA_CONECTADA = "nunca_conectada"
INSTALACION_VIEJA = "instalacion_vieja"
NO_SELECCIONADA = "no_seleccionada"
FUNCIONANDO = "funcionando"          # ya arrancó con la versión que le toca
LISTA = "lista"                      # la copió y la comprobó: se pone en el próximo reinicio
FALLO = "fallo"                      # la puso, no arrancó bien y volvió sola a la anterior
APAGADA = "apagada"
COPIANDO = "copiando"
ERROR = "error"                      # no la pudo copiar: reintenta sola al minuto
ESPERANDO = "esperando"              # marcada, todavía no empezó (empieza en segundos)
SE_BORRA = "se_borra"                # la copió, pero el reinicio la borra (Shadow Defender)
SIN_LANZADOR = "sin_lanzador"        # la copió, pero al reiniciar nadie la pone (no arranca con Lanzador.exe)
FALTA_PUENTE = "falta_puente"        # la cargada es en carpeta y esa PC todavía no la sabe poner (le falta la V1.9)
# Las que ya no necesitan nada: cuentan como "listas" en el resumen.
SITUACIONES_LISTAS = (FUNCIONANDO, LISTA)


def situacion(pc: dict) -> str:
    """Cómo está una fila de `estado_de_las_pcs` con la versión cargada: una de las constantes de
    arriba. Lo que es verdad aunque la PC esté apagada (ya la copió, ya arrancó con ella, falló)
    va antes que "apagada"; lo que cuenta mientras pasa (copiando, error) solo vale si está
    conectada, porque es lo último que dijo."""
    if not pc["carpeta"]:
        return NUNCA_CONECTADA if not pc["ultima_conexion"] else INSTALACION_VIEJA
    if pc["le_toca"] is None:
        return NO_SELECCIONADA
    if pc["version"] == pc["le_toca"]:
        return FUNCIONANDO
    if pc.get("va_en_carpeta") and not pc.get("sabe_poner_carpetas"):
        return FALTA_PUENTE
    if pc["estado"] == dominio.ACTUALIZACION_FALLO:
        return FALLO
    if pc["estado"] == dominio.ACTUALIZACION_DESCARGADA and pc["version_bajada"] in (None, pc["le_toca"]):
        no_se_puso = pc.get("no_se_puso")
        if no_se_puso == dominio.NO_SE_PUSO_SE_BORRO:
            return SE_BORRA
        if no_se_puso == dominio.NO_SE_PUSO_SIN_LANZADOR:
            return SIN_LANZADOR
        return LISTA
    if not pc["conectada"]:
        return APAGADA
    if pc["estado"] == dominio.ACTUALIZACION_BAJANDO:
        return COPIANDO
    if pc["estado"] == dominio.ACTUALIZACION_ERROR:
        return ERROR
    return ESPERANDO


def texto_version(version) -> str:
    """"18/10/2026 19:30" para una versión (AAAAMMDDhhmmss); el número tal cual si no es una fecha."""
    try:
        return datetime.strptime(str(version), "%Y%m%d%H%M%S").strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(version) if version is not None else ""
