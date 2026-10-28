"""
fondo_repo.py
=============
Los fondos de las PC clientes (carpeta hermana "CLIENTE PC"), dos imágenes que
elige el Admin en Configuración ADMIN -> Gestionar Estaciones -> "Fondos de
pantalla" y que cada Cliente PC pide solo:

- BLOQUEO: el fondo de la pantalla de bloqueo, detrás del nombre de la PC y del
  recuadro de ingreso (`GET /fondo`, ver `servidor_red.py`).
- ESCRITORIO: el wallpaper de Windows que ve el cliente mientras juega (pedido del
  dueño, 2026-10-28; `GET /escritorio`). Lo pone cada Cliente PC (desde la V2.1,
  `CLIENTE PC/fondo_escritorio.py`), con la PC libre y de nuevo en cada arranque:
  Shadow Defender lo borra al reiniciar.

Todas las funciones reciben `cual` (BLOQUEO si no se dice): las dos imágenes siguen
las mismas reglas y solo cambia el archivo. Viene también desde otra PC (admin
remoto), así que se valida contra la lista: nunca arma una ruta con un texto suelto.

Dónde vive: UN archivo JPEG por fondo, `data/fondo_bloqueo.jpg` y
`data/fondo_escritorio.jpg`. No va en la base
(es una imagen, no un dato) ni en git (`data/` está en el `.gitignore` y este
repo es público). Por lo mismo no entra en las copias de seguridad de la base:
si alguna vez se pierde la carpeta `data/`, se vuelve a elegir la imagen.

La versión: es la huella SHA-256 (los primeros 16 caracteres) del contenido, así
sale sola del propio archivo y no hay un dato aparte que pueda quedar desparejo.
Viaja en cada `GET /estado` (`fondo_version` y `escritorio_version`): una PC que
lleva días prendida se entera de que un fondo cambió sin tener que bajar la imagen
para compararla.

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

BLOQUEO = "bloqueo"
ESCRITORIO = "escritorio"
NOMBRES_DE_ARCHIVO = {BLOQUEO: "fondo_bloqueo.jpg", ESCRITORIO: "fondo_escritorio.jpg"}
FONDOS = tuple(NOMBRES_DE_ARCHIVO)

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
# Lo último leído del disco de cada fondo: de qué archivo salió (ruta, fecha, tamaño),
# su contenido y su versión. `clave` en None = no se leyó nada o no hay fondo.
_ultimo = {cual: {"clave": None, "datos": None, "version": ""} for cual in FONDOS}


def _nombre_de_archivo(cual: str) -> str:
    try:
        return NOMBRES_DE_ARCHIVO[cual]
    except (KeyError, TypeError):
        raise ValueError(f"No hay ningún fondo llamado {cual!r}.") from None


def ruta_del_fondo(cual: str = BLOQUEO) -> str:
    return os.path.join(database.DATA_DIR, _nombre_de_archivo(cual))


def _huella(datos: bytes) -> str:
    return hashlib.sha256(datos).hexdigest()[:16]


def _olvidar(cual: str = None):
    """Se olvida lo leído de ese fondo (de los dos, sin `cual`)."""
    for cada_uno in (FONDOS if cual is None else (cual,)):
        _ultimo[cada_uno].update(clave=None, datos=None, version="")


def _leer_del_disco(cual: str):
    """`(datos, versión)` de ese fondo guardado, o None si no hay. Se llama con el
    candado puesto. Un archivo que no empieza como un JPEG (vacío, cortado por un
    apagón al copiarlo, cualquier otra cosa) cuenta como que no hay fondo: las PCs
    se quedan con el gris liso (o con su wallpaper) en vez de intentar dibujar basura."""
    ruta = ruta_del_fondo(cual)
    ultimo = _ultimo[cual]
    try:
        estado = os.stat(ruta)
    except FileNotFoundError:
        _olvidar(cual)
        return None
    clave = (ruta, estado.st_mtime_ns, estado.st_size)
    if ultimo["clave"] != clave:
        with open(ruta, "rb") as archivo:
            datos = archivo.read()
        if not datos.startswith(_FIRMA_JPEG):
            _olvidar(cual)
            return None
        ultimo.update(clave=clave, datos=datos, version=_huella(datos))
    return ultimo["datos"], ultimo["version"]


def obtener(cual: str = BLOQUEO):
    """`(bytes_del_jpeg, versión)` de ese fondo, o None si no hay ninguno."""
    _nombre_de_archivo(cual)
    with _candado:
        return _leer_del_disco(cual)


def version_actual(cual: str = BLOQUEO) -> str:
    """La versión de ese fondo, o cadena vacía si no hay. Es lo que viaja en cada
    `GET /estado`: barato, no abre el archivo si no cambió."""
    _nombre_de_archivo(cual)
    with _candado:
        encontrado = _leer_del_disco(cual)
    return encontrado[1] if encontrado else ""


def guardar_jpeg(datos: bytes, cual: str = BLOQUEO) -> str:
    """Deja `datos` (un JPEG ya achicado por la pantalla) como ese fondo de todas las
    PCs y devuelve su versión. Lo escribe en un archivo aparte y recién entonces lo
    pone en su lugar, así un corte de luz a mitad de camino no deja un fondo
    cortado. Levanta ValueError (con un mensaje para mostrarle a la persona) si lo
    que llega no es un JPEG o pesa más del tope."""
    _nombre_de_archivo(cual)
    if not datos.startswith(_FIRMA_JPEG):
        raise ValueError("La imagen no está en formato JPEG.")
    if len(datos) > TAMANO_MAXIMO_BYTES:
        raise ValueError(
            f"La imagen pesa {len(datos) / 1024 / 1024:.1f} MB y el máximo es "
            f"{TAMANO_MAXIMO_BYTES // (1024 * 1024)} MB."
        )
    with _candado:
        os.makedirs(database.DATA_DIR, exist_ok=True)
        ruta = ruta_del_fondo(cual)
        temporal = ruta + ".nuevo"
        try:
            with open(temporal, "wb") as archivo:
                archivo.write(datos)
            _poner_en_su_lugar(temporal, ruta)
        finally:
            if os.path.exists(temporal):
                os.remove(temporal)
        _olvidar(cual)
        return _leer_del_disco(cual)[1]


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


def quitar(cual: str = BLOQUEO) -> bool:
    """Saca ese fondo. True si había uno. Sin el de bloqueo, las PCs vuelven al gris liso
    de siempre; sin el del escritorio, dejan de tocar el wallpaper de Windows (el que
    pusieron queda hasta que la PC se reinicia congelada)."""
    _nombre_de_archivo(cual)
    with _candado:
        try:
            os.remove(ruta_del_fondo(cual))
            habia = True
        except FileNotFoundError:
            habia = False
        _olvidar(cual)
        return habia
