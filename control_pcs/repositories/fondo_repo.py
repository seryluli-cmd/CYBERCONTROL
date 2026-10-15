"""
fondo_repo.py
=============
El fondo de la pantalla de bloqueo de las PC clientes (carpeta hermana
"CLIENTE PC"). Lo elige el Admin en Configuración ADMIN -> Gestionar Estaciones
-> "Fondo de pantalla de las PCs..." y cada Cliente PC lo pide al arrancar
(`GET /fondo`, ver `servidor_red.py`).

Dónde vive: UN solo archivo JPEG, `data/fondo_bloqueo.jpg`. No va en la base
(es una imagen, no un dato) ni en git (`data/` está en el `.gitignore` y este
repo es público). Por lo mismo no entra en las copias de seguridad de la base:
si alguna vez se pierde la carpeta `data/`, se vuelve a elegir la imagen.

La versión: es la huella SHA-256 (los primeros 16 caracteres) del contenido, así
sale sola del propio archivo y no hay un dato aparte que pueda quedar desparejo.
Viaja en cada `GET /estado` (`fondo_version`): una PC que lleva días prendida se
entera de que el fondo cambió sin tener que bajar la imagen para compararla.

Quién achica la imagen: la pantalla (`pcs_fondo_dialogo.py`), porque solo Qt sabe
abrir un PNG o JPG cualquiera. Acá se fijan las reglas (tamaño máximo, calidad,
peso máximo) y se valida lo que llega, sin Qt, como en el resto de los
repositorios.

Lo leen los hilos del servidor de red y lo escribe la pantalla, todo en el mismo
programa: un candado evita leer un archivo a medio cambiar, y lo último leído se
guarda en memoria (con el archivo del que salió) para no volver a abrir el disco
ni recalcular la huella en cada pedido: `/estado` lo pregunta cada 5 s por cada
PC. Si el archivo cambia por fuera del programa, se nota solo (cambia su fecha o
su tamaño). Igual que `comandos_pc_repo.guardar_screenshot`, `database.DATA_DIR`
se lee al momento de usarse: los tests lo apuntan a una carpeta temporal.
"""

import hashlib
import os
import threading
import time

import database

NOMBRE_ARCHIVO = "fondo_bloqueo.jpg"

# Lo que la pantalla le hace a la imagen antes de guardarla (ver
# `pcs_fondo_dialogo.preparar_jpeg`): entra en este rectángulo sin deformarse y
# se guarda como JPEG con esta calidad. Una foto de 4K sin achicar pesaría varios
# MB por PC en cada arranque, y las 40 PCs prenden juntas después de un corte de
# luz. La PC cliente la ajusta a su propia pantalla, recortando lo que sobre.
ANCHO_MAXIMO = 1920
ALTO_MAXIMO = 1080
CALIDAD_JPEG = 85

# Techo del archivo ya guardado. Una imagen de 1920x1080 a calidad 85 pesa
# unos 300-800 KB; esto solo ataja lo que se saliera de lo normal.
TAMANO_MAXIMO_BYTES = 2 * 1024 * 1024

_FIRMA_JPEG = b"\xff\xd8\xff"

_candado = threading.Lock()
# Lo último leído del disco: de qué archivo salió (ruta, fecha, tamaño), su contenido
# y su versión. `clave` en None = no se leyó nada o no hay fondo.
_ultimo = {"clave": None, "datos": None, "version": ""}


def ruta_del_fondo() -> str:
    return os.path.join(database.DATA_DIR, NOMBRE_ARCHIVO)


def _huella(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()[:16]


def _olvidar():
    _ultimo.update(clave=None, datos=None, version="")


def _leer_del_disco():
    """`(datos, versión)` del fondo guardado, o None si no hay. Se llama con el
    candado puesto. Un archivo que no empieza como un JPEG (vacío, cortado por un
    apagón al copiarlo, cualquier otra cosa) cuenta como que no hay fondo: las PCs
    se quedan con el azul liso en vez de intentar dibujar basura."""
    ruta = ruta_del_fondo()
    try:
        estado = os.stat(ruta)
    except FileNotFoundError:
        _olvidar()
        return None
    clave = (ruta, estado.st_mtime_ns, estado.st_size)
    if _ultimo["clave"] != clave:
        with open(ruta, "rb") as archivo:
            datos = archivo.read()
        if not datos.startswith(_FIRMA_JPEG):
            _olvidar()
            return None
        _ultimo.update(clave=clave, datos=datos, version=_huella(datos))
    return _ultimo["datos"], _ultimo["version"]


def obtener():
    """`(bytes_del_jpeg, versión)` del fondo actual, o None si no hay ninguno."""
    with _candado:
        return _leer_del_disco()


def version_actual() -> str:
    """La versión del fondo actual, o cadena vacía si no hay. Es lo que viaja en
    cada `GET /estado`: barato, no abre el archivo si no cambió."""
    with _candado:
        encontrado = _leer_del_disco()
    return encontrado[1] if encontrado else ""


def guardar_jpeg(datos: bytes) -> str:
    """Deja `datos` (un JPEG ya achicado por la pantalla) como el fondo de todas las
    PCs y devuelve su versión. Lo escribe en un archivo aparte y recién entonces lo
    pone en su lugar, así un corte de luz a mitad de camino no deja un fondo
    cortado. Levanta ValueError (con un mensaje para mostrarle a la persona) si lo
    que llega no es un JPEG o pesa más del tope."""
    if not datos.startswith(_FIRMA_JPEG):
        raise ValueError("La imagen no está en formato JPEG.")
    if len(datos) > TAMANO_MAXIMO_BYTES:
        raise ValueError(
            f"La imagen pesa {len(datos) / 1024 / 1024:.1f} MB y el máximo es "
            f"{TAMANO_MAXIMO_BYTES // (1024 * 1024)} MB."
        )
    with _candado:
        os.makedirs(database.DATA_DIR, exist_ok=True)
        ruta = ruta_del_fondo()
        temporal = ruta + ".nuevo"
        try:
            with open(temporal, "wb") as archivo:
                archivo.write(datos)
            _poner_en_su_lugar(temporal, ruta)
        finally:
            if os.path.exists(temporal):
                os.remove(temporal)
        _olvidar()
        return _leer_del_disco()[1]


def _poner_en_su_lugar(temporal: str, destino: str, intentos: int = 5):
    """`os.replace` con reintentos: en Windows, un antivirus que justo está
    revisando el archivo viejo lo deja trabado un instante y el reemplazo falla
    con PermissionError."""
    for intento in range(intentos):
        try:
            os.replace(temporal, destino)
            return
        except PermissionError:
            if intento == intentos - 1:
                raise
            time.sleep(0.1)


def quitar() -> bool:
    """Saca el fondo: las PCs vuelven al azul liso de siempre. True si había uno."""
    with _candado:
        try:
            os.remove(ruta_del_fondo())
            habia = True
        except FileNotFoundError:
            habia = False
        _olvidar()
        return habia
