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
2. El Admin elige a qué PCs va: unas pocas "de prueba" o todas (`guardar_alcance`). Una versión
   recién cargada NUNCA va sola a todas: el alcance vuelve a "solo las de prueba".
3. En cada GET /estado, la PC recibe `cliente_version` (`version_para_estacion`). Si es más
   nueva que la suya, pide GET /cliente_pc (el manifiesto y la firma) y GET /cliente_pc/exe,
   comprueba todo y la deja lista; su lanzador la pone en uso en el próximo reinicio y vuelve
   solo a la anterior si no arranca bien (ver CLIENTE PC/lanzador.py).
4. Cada PC cuenta en cada consulta su versión, su carpeta y cómo va (`registrar_reporte`), y eso
   se ve en la pantalla (`estado_de_las_pcs`).

Dónde vive: `data/cliente_pc/PCcliente.exe` y `data/cliente_pc/version.json` (el manifiesto y su
firma), como el fondo de pantalla: fuera de la base y de git. Si se pierde `data/`, se vuelve a
cargar la versión. La versión es un número que sale de la fecha y hora en que se cargó
(AAAAMMDDhhmmss) y siempre crece: para volver a una versión vieja, se la carga de nuevo.

Lo leen los hilos del servidor de red y lo escribe la pantalla, en el mismo programa: un candado
evita leer a medio cambiar y lo leído se guarda en memoria (con la fecha y el tamaño de los
archivos) para no abrir el disco en cada consulta de cada PC.
"""

import base64
import hashlib
import json
import os
import threading
import time
from datetime import datetime
from pathlib import Path

import database
import dominio
from control_pcs.repositories import comandos_pc_repo
from database import conexion_db

# La mitad pública de la clave con que se firman las versiones. Tiene que ser la MISMA que
# `CLIENTE PC/actualizacion.py` (CLAVE_PUBLICA_FIRMA): es la que las PCs usan para comprobar.
CLAVE_PUBLICA_FIRMA = "r2y5vYxbu1ZZswyhSkn8hmBBe0KpaSjIr6VpZPG1WhE="

PROGRAMA = "PCcliente"
CARPETA = "cliente_pc"
NOMBRE_EXE = "PCcliente.exe"
NOMBRE_VERSION = "version.json"
TAMANO_MAXIMO_EXE = 150 * 1024 * 1024
# Lo que identifica un PCcliente.exe por dentro: PyInstaller deja, al final del archivo, la lista
# de lo que lleva adentro, y ahí está el nombre del programa principal (cliente_pc). Ataja el error
# de elegir otro exe (CyberBios.exe, Lanzador.exe): las PCs lo abrirían en lugar del Cliente PC.
_MARCA_DEL_CLIENTE = b"cliente_pc"
_FINAL_A_REVISAR = 512 * 1024

_CLAVE_ALCANCE = "actualizacion_cliente_alcance"
_TOPE_CARPETA = 260
_TOPE_DETALLE = 300

_candado = threading.Lock()
# Lo último leído del disco: de qué archivos salió (fechas y tamaños), el paquete y el exe.
_ultimo = {"clave": None, "paquete": None, "exe": None}
# Lo último que contó cada PC (estacion_id -> tupla), para escribir en la base solo si cambió:
# cada PC consulta cada 5 s.
_reportes = {}
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


def publicar(datos_exe: bytes, ahora: datetime = None) -> dict:
    """Firma `datos_exe` (un PCcliente.exe) y lo deja como la versión de las PCs. El alcance vuelve
    a "solo las de prueba". Devuelve el manifiesto. Levanta ValueError, con un mensaje para
    mostrarle a la persona, si no es un PCcliente.exe o no se puede firmar."""
    if not datos_exe or not datos_exe.startswith(b"MZ"):
        raise ValueError("El archivo elegido no es un programa (.exe).")
    if len(datos_exe) > TAMANO_MAXIMO_EXE:
        raise ValueError(f"El archivo pesa {len(datos_exe) / 1024 / 1024:.0f} MB: no parece el PCcliente.exe.")
    if not es_un_cliente_pc(datos_exe):
        raise ValueError(
            "Ese .exe no es el Cliente PC (PCcliente.exe). Elegí el que está en "
            "CLIENTE PC\\dist\\PCcliente.exe.")
    privada = _cargar_clave_privada()
    ahora = ahora or datetime.now()
    with _candado:
        anterior = _leer_del_disco()
        version = _version_nueva(ahora, anterior["paquete"]["version"] if anterior["paquete"] else None)
        manifiesto = json.dumps({
            "programa": PROGRAMA, "version": version, "sha256": hashlib.sha256(datos_exe).hexdigest(),
            "tamano": len(datos_exe), "creado": ahora.isoformat(timespec="seconds"),
        }, sort_keys=True)
        firma = base64.b64encode(privada.sign(manifiesto.encode("utf-8"))).decode()
        os.makedirs(_carpeta(), exist_ok=True)
        # Primero el exe y después el manifiesto: una PC que pide justo en el medio recibe un exe
        # que no coincide con el manifiesto, lo descarta y vuelve a probar.
        _escribir(_ruta(NOMBRE_EXE), datos_exe)
        _escribir(_ruta(NOMBRE_VERSION), json.dumps({"manifiesto": manifiesto, "firma": firma}).encode("utf-8"))
        _ultimo.update(clave=None, paquete=None, exe=None)
    alcance = obtener_alcance()
    guardar_alcance(False, alcance["prueba"])
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
def _leer_del_disco() -> dict:
    """{"paquete": {...} o None, "exe": bytes o None}. Se llama con el candado puesto. Un
    version.json roto cuenta como que no hay versión."""
    try:
        estados = tuple((os.stat(_ruta(n)).st_mtime_ns, os.stat(_ruta(n)).st_size) for n in (NOMBRE_VERSION, NOMBRE_EXE))
    except FileNotFoundError:
        _ultimo.update(clave=None, paquete=None, exe=None)
        return _ultimo
    if _ultimo["clave"] != estados:
        try:
            with open(_ruta(NOMBRE_VERSION), "rb") as archivo:
                guardado = json.loads(archivo.read().decode("utf-8"))
            contenido = json.loads(guardado["manifiesto"])
            paquete = {"manifiesto": guardado["manifiesto"], "firma": guardado["firma"],
                       "version": int(contenido["version"]), "tamano": int(contenido["tamano"]),
                       "creado": contenido.get("creado", "")}
            with open(_ruta(NOMBRE_EXE), "rb") as archivo:
                exe = archivo.read()
        except (OSError, ValueError, KeyError, TypeError):
            paquete, exe = None, None
        _ultimo.update(clave=estados, paquete=paquete, exe=exe)
    return _ultimo


def paquete():
    """La versión cargada: {"manifiesto", "firma", "version", "tamano", "creado"}, o None."""
    with _candado:
        return _leer_del_disco()["paquete"]


def datos_exe():
    """Los bytes del PCcliente.exe cargado, o None."""
    with _candado:
        return _leer_del_disco()["exe"]


def version_publicada():
    encontrado = paquete()
    return encontrado["version"] if encontrado else None


# --------------------------------------------------------------------
# A qué PCs va
# --------------------------------------------------------------------
def obtener_alcance() -> dict:
    """{"para_todas": bool, "prueba": set de ids de estación}. Sin nada guardado: ninguna."""
    with conexion_db() as conexion:
        fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_ALCANCE,)).fetchone()
    try:
        datos = json.loads(fila["valor"]) if fila else {}
        return {"para_todas": datos.get("para_todas") is True,
                "prueba": {int(i) for i in datos.get("prueba") or []}}
    except (ValueError, TypeError, AttributeError):
        return {"para_todas": False, "prueba": set()}


def guardar_alcance(para_todas: bool, ids_prueba):
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_ALCANCE, json.dumps({"para_todas": bool(para_todas), "prueba": sorted({int(i) for i in ids_prueba})})),
        )


def version_para_estacion(estacion_id: int):
    """La versión que le toca a esa PC (viaja en cada GET /estado como `cliente_version`), o None si
    no hay ninguna cargada o esa PC no está en el alcance."""
    version = version_publicada()
    if version is None:
        return None
    alcance = obtener_alcance()
    return version if alcance["para_todas"] or estacion_id in alcance["prueba"] else None


# --------------------------------------------------------------------
# Lo que cuenta cada PC
# --------------------------------------------------------------------
def registrar_reporte(estacion_id: int, parametros: dict):
    """Guarda lo que contó la PC en su GET /estado (`parametros`: los de la consulta, ya de a uno):
    `version`, `carpeta`, `act` y `act_detalle`. Un Cliente PC sin actualización automática no
    manda nada y no se toca nada. Solo escribe en la base si cambió algo."""
    if "version" not in parametros:
        return
    texto_version = str(parametros.get("version") or "").strip()
    version = int(texto_version) if texto_version.isdigit() else None
    carpeta = str(parametros.get("carpeta") or "")[:_TOPE_CARPETA]
    estado = str(parametros.get("act") or "")
    if estado not in dominio.ESTADOS_ACTUALIZACION_CLIENTE:
        estado = ""
    detalle = str(parametros.get("act_detalle") or "")[:_TOPE_DETALLE] if estado else ""
    nuevo = (version, carpeta, estado, detalle)
    with _candado_reportes:
        if _reportes.get(estacion_id) == nuevo:
            return
    with conexion_db() as conexion:
        conexion.execute(
            """
            UPDATE estaciones SET version_cliente = ?, carpeta_cliente = ?, estado_actualizacion = ?,
                                  detalle_actualizacion = ?
            WHERE id = ?
            """,
            (*nuevo, estacion_id),
        )
    with _candado_reportes:
        _reportes[estacion_id] = nuevo


def olvidar_reportes():
    """Que la próxima consulta de cada PC se vuelva a escribir (para los tests)."""
    with _candado_reportes:
        _reportes.clear()


def estado_de_las_pcs() -> list:
    """Una fila por estación activa, en el orden de siempre: lo que contó su Cliente PC, si está en
    la prueba, qué versión le toca y si tiene una sesión en curso."""
    from control_pcs.repositories import pcs_repo   # aquí: pcs_repo no depende de este repo
    alcance = obtener_alcance()
    publicada = version_publicada()
    with conexion_db() as conexion:
        ocupadas = {fila["estacion_id"] for fila in conexion.execute(
            "SELECT DISTINCT estacion_id FROM sesiones_pc WHERE estado = ?", (dominio.SESION_ACTIVA,))}
    filas = []
    for estacion in pcs_repo.listar_estaciones():
        en_prueba = estacion["id"] in alcance["prueba"]
        filas.append({
            "id": estacion["id"], "nombre": estacion["nombre"],
            "version": estacion["version_cliente"], "carpeta": estacion["carpeta_cliente"] or "",
            "estado": estacion["estado_actualizacion"] or "", "detalle": estacion["detalle_actualizacion"] or "",
            "ultima_conexion": estacion["ultima_conexion"], "en_prueba": en_prueba,
            "le_toca": publicada if publicada is not None and (alcance["para_todas"] or en_prueba) else None,
            "ocupada": estacion["id"] in ocupadas,
        })
    return filas


def reiniciar_las_libres_que_ya_la_bajaron() -> list:
    """Manda REINICIAR a cada PC sin sesión en curso que ya tiene la versión bajada (así la pone en
    uso ya, sin esperar al próximo cliente). Devuelve los nombres."""
    reiniciadas = []
    for pc in estado_de_las_pcs():
        if pc["estado"] == dominio.ACTUALIZACION_DESCARGADA and not pc["ocupada"]:
            comandos_pc_repo.encolar_comando(pc["id"], dominio.COMANDO_REINICIAR)
            reiniciadas.append(pc["nombre"])
    return reiniciadas


def texto_version(version) -> str:
    """"18/10/2026 19:30" para una versión (AAAAMMDDhhmmss); el número tal cual si no es una fecha."""
    try:
        return datetime.strptime(str(version), "%Y%m%d%H%M%S").strftime("%d/%m/%Y %H:%M")
    except (ValueError, TypeError):
        return str(version) if version is not None else ""
