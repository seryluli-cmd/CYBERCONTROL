"""
modo.py
========
¿Esta copia del programa es la del MOSTRADOR (la que tiene la base y atiende) o
una COPIA REMOTA (el Administrador administrando desde otra PC del local)?

Se decide solo, sin configurar nada: el dueño abre el CyberBios.exe desde la
carpeta compartida del mostrador (\\\\MOSTRADOR\\CyberBios\\CyberBios.exe, o una
unidad de red como Z:). Un programa abierto desde la red es una copia remota y
le habla al programa de la PC de donde vino el archivo. Esto además lo protege
de lo peor que podría pasar: que la copia de la otra PC abriera por la red el
mismo archivo de la base que está usando el mostrador.

Para probar (o con una copia del .exe en la otra PC), se puede decir a mano a
qué PC hablarle: CyberBios.exe --mostrador 192.168.0.10

No usa Qt ni la base: lo pregunta main.py antes de abrir nada, y las pantallas
(con es_copia_remota) para esconder lo que solo se hace en el mostrador.
"""

import ctypes
import os
import sys

OPCION_MOSTRADOR = "--mostrador"

# GetDriveTypeW: una unidad de red (Z: apuntando a \\MOSTRADOR\CyberBios).
_UNIDAD_DE_RED = 4

_mostrador_en_uso = None  # la PC del mostrador, si esta es una copia remota (ver activar)


def direccion_del_mostrador(argv=None, carpeta_del_programa=None):
    """
    A qué PC le habla esta copia, o None si esta ES la del mostrador.
    - `--mostrador X` en la línea de comandos manda sobre todo.
    - Si no, la PC de la carpeta compartida desde donde se abrió el programa.
    """
    argv = sys.argv if argv is None else argv
    if OPCION_MOSTRADOR in argv:
        posicion = argv.index(OPCION_MOSTRADOR)
        if posicion + 1 < len(argv) and argv[posicion + 1].strip():
            return argv[posicion + 1].strip()
    if carpeta_del_programa is None:
        import database
        carpeta_del_programa = database.BASE_DIR
    return pc_de_la_carpeta(carpeta_del_programa)


def pc_de_la_carpeta(carpeta: str):
    """La PC dueña de una carpeta compartida ("MOSTRADOR" para
    \\\\MOSTRADOR\\CyberBios o para una unidad de red Z: que apunta ahí), o None
    si la carpeta es de esta misma PC."""
    ruta = _ruta_de_red(carpeta)
    if ruta is None:
        return None
    ruta = ruta.replace("/", "\\")
    if ruta.upper().startswith("\\\\?\\UNC\\"):
        ruta = "\\\\" + ruta[len("\\\\?\\UNC\\"):]
    elif ruta.startswith("\\\\?\\") or ruta.startswith("\\\\.\\"):
        return None  # una ruta larga de un disco de esta PC, no de la red
    if not ruta.startswith("\\\\"):
        return None
    pc = ruta[2:].split("\\", 1)[0].strip()
    return pc or None


def _ruta_de_red(carpeta: str):
    """La carpeta como ruta de red (\\\\PC\\carpeta), o None si es de un disco
    de esta PC. Una unidad de red (Z:) se traduce a la carpeta compartida a la
    que apunta."""
    if carpeta.startswith("\\\\") or carpeta.startswith("//"):
        return carpeta
    unidad = os.path.splitdrive(carpeta)[0]
    if len(unidad) != 2 or unidad[1] != ":" or not sys.platform.startswith("win"):
        return None
    try:
        if ctypes.windll.kernel32.GetDriveTypeW(unidad + "\\") != _UNIDAD_DE_RED:
            return None
        buffer = ctypes.create_unicode_buffer(1024)
        largo = ctypes.c_ulong(len(buffer))
        if ctypes.windll.mpr.WNetGetConnectionW(unidad, buffer, ctypes.byref(largo)) != 0:
            return None
        return buffer.value
    except (AttributeError, OSError):
        return None


def activar(mostrador: str):
    """Deja anotado que esta es una copia remota que le habla a `mostrador`
    (lo llama admin_remoto.cliente al conectarse)."""
    global _mostrador_en_uso
    _mostrador_en_uso = mostrador


def desactivar():
    """Para las pruebas: vuelve a ser la copia del mostrador."""
    global _mostrador_en_uso
    _mostrador_en_uso = None


def es_copia_remota() -> bool:
    """True en la copia de la otra PC: las pantallas esconden lo que solo se
    hace en el mostrador (vender, cerrar turno, la grilla de PCs...)."""
    return _mostrador_en_uso is not None


def mostrador_en_uso():
    """La PC del mostrador a la que le habla esta copia remota (None en el mostrador)."""
    return _mostrador_en_uso
