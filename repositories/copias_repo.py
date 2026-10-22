"""
copias_repo.py
================
Las copias de seguridad automáticas de la base (pedido del dueño, 2026-10-19:
"para no perder todo").

Cuándo: después de cada Cierre de Turno (el que aprieta la empleada, el que se
hace en ausencia al entrar el otro operador y el forzoso: todos pasan por
turnos_repo.cerrar_turno y dejan su `fecha_cierre`) y, si no hubo ninguno, cada
HORAS_ENTRE_COPIAS. Se hacen EN CALIENTE, con el programa abierto: el mostrador
queda abierto días seguidos, y hasta el 2026-10-19 la única copia automática se
hacía al abrir el programa, así que podían pasar días sin ninguna.

Quién: un hilo propio (iniciar_copias_automaticas, lo arranca main.py en el
mostrador) que revisa cada SEGUNDOS_ENTRE_REVISIONES. No depende de que haya
alguien logueado ni de Qt, y nunca frena una venta: la copia usa la Online Backup
API de SQLite (database._backup_consistente).

Dónde: en data/backups y, además, en las OTRAS CARPETAS que elija el Admin. El
dueño eligió dos: una carpeta compartida de otra PC del local (con usuario y clave)
y otro disco de la misma PC. Cada copia nueva se copia de data/backups a cada una.
Si una no está (la otra PC apagada, el disco desconectado), la copia llega sola
apenas vuelve: en cada revisión se mira que la última esté en todas.

El usuario y la clave de una carpeta de red NO se guardan en el programa: se le
pasan a Windows (Administrador de credenciales, con `cmdkey`, lo mismo que
"Recordar mis credenciales") y desde ahí Windows entra solo. En la base quedarían
a la vista de cualquiera que copie el archivo, y este repo es público.

Cuántas: las de los últimos DIAS_CON_TODAS_LAS_COPIAS días con copias, todas; más
atrás, la última de cada día hasta DIAS_CON_UNA_COPIA días con copias (ver
nombres_a_borrar). Se cuentan días CON copias y no días del calendario: si el
reloj de la PC salta o el programa pasa un mes cerrado, no se borra todo de golpe.
Solo se tocan los archivos con el nombre de una copia automática
(kiosko_AAAA-MM-DD_HHMMSS.db, o kiosko_AAAA-MM-DD.db de antes de este cambio): las
copias "antes_de_..." de las migraciones (y las de Limpiar base, que existió hasta el
2026-10-22) y las que se guardan a mano no se borran nunca.
"""

import json
import os
import re
import shutil
import socket
import subprocess
import threading
import time
from datetime import datetime, timedelta

import database
from database import conexion_db
from errores import registrar_error
from repositories import usuarios_repo

HORAS_ENTRE_COPIAS = 8
SEGUNDOS_ENTRE_REVISIONES = 60
# Si la copia de esta PC falla (disco lleno), no se reintenta cada minuto: se
# espera esto.
MINUTOS_ANTES_DE_REINTENTAR = 10
DIAS_CON_TODAS_LAS_COPIAS = 3
DIAS_CON_UNA_COPIA = 30
MAXIMO_CARPETAS_EXTRA = 5

# Antes de entrar a una carpeta de otra PC se pregunta si esa PC contesta (el
# puerto de las carpetas compartidas de Windows): con la PC apagada, Windows
# tarda ~50 s en darse por vencido (medido el 2026-10-19 en el local), y el hilo
# de las copias o la pantalla quedarían esperando todo ese tiempo.
PUERTO_CARPETAS_COMPARTIDAS = 445
SEGUNDOS_PARA_CONTESTAR = 3

_CLAVE_CARPETAS_EXTRA = "carpetas_copias_extra"
_PATRON_COPIA = re.compile(r"^kiosko_(\d{4}-\d{2}-\d{2})(?:_(\d{6}))?\.db$")
_SUFIJO_A_MEDIAS = ".parcial"

# Lo que dice Windows cuando no se puede entrar a una carpeta (winerror), en
# palabras para el dueño.
_SIN_RED = {53, 64, 67, 121, 1231, 1232}
_USUARIO_O_CLAVE = {86, 1326, 1907, 1909}
_OTRO_USUARIO_YA_CONECTADO = 1219
_SIN_LUGAR = {39, 112}

# Una copia por vez: el hilo y el botón "Hacer copia de seguridad ahora" no pueden pisarse.
_candado = threading.Lock()
# Lo último que pasó, para la pantalla. Vive en memoria: al reabrir el programa
# se vuelve a probar enseguida. "extra" es {carpeta: {"ultima", "error"}}: la
# pantalla lo lee de acá y no de la carpeta, porque mirar una carpeta de red con
# la otra PC apagada tarda varios segundos y congelaría la ventana.
_estado = {"error_local": None, "reintentar_desde": None, "extra": {}}


# ---------------------------------------------------------------------------
# Las reglas (sin disco ni base: las prueba tests/test_copias.py)
# ---------------------------------------------------------------------------

def momento_de_la_copia(nombre: str):
    """El momento en que se hizo una copia automática, sacado de su nombre, o
    None si el archivo no es una copia automática (no se toca)."""
    coincidencia = _PATRON_COPIA.match(nombre)
    if coincidencia is None:
        return None
    dia, hora = coincidencia.groups()
    try:
        return datetime.strptime(f"{dia} {hora or '000000'}", "%Y-%m-%d %H%M%S")
    except ValueError:
        return None


def nombre_de_copia(momento: datetime) -> str:
    return f"kiosko_{momento.strftime('%Y-%m-%d_%H%M%S')}.db"


def toca_copia(ultima_copia, ultimo_cierre, ahora: datetime) -> bool:
    """Si hay que hacer una copia: no hay ninguna, hubo un Cierre de Turno
    después de la última o pasaron HORAS_ENTRE_COPIAS desde la última."""
    if ultima_copia is None:
        return True
    if ultimo_cierre is not None and ultimo_cierre > ultima_copia:
        return True
    return ahora - ultima_copia >= timedelta(hours=HORAS_ENTRE_COPIAS)


def nombres_a_borrar(nombres) -> list:
    """De los archivos de una carpeta, las copias automáticas que sobran (ver el
    comentario del módulo). Los demás archivos no aparecen nunca."""
    copias = sorted(
        (momento, nombre) for nombre in nombres
        if (momento := momento_de_la_copia(nombre)) is not None
    )
    dias = sorted({momento.date() for momento, _ in copias}, reverse=True)
    dias_con_todas = set(dias[:DIAS_CON_TODAS_LAS_COPIAS])
    dias_con_una = set(dias[:DIAS_CON_UNA_COPIA])
    ultima_del_dia = {momento.date(): nombre for momento, nombre in copias}
    return [
        nombre for momento, nombre in copias
        if momento.date() not in dias_con_todas
        and not (momento.date() in dias_con_una and ultima_del_dia[momento.date()] == nombre)
    ]


def es_carpeta_de_red(carpeta: str) -> bool:
    """Una carpeta compartida de otra PC (\\\\192.168.1.111\\backups)."""
    return carpeta.startswith("\\\\")


def servidor_de(carpeta: str) -> str:
    """La PC de una carpeta de red: "192.168.1.111" en \\\\192.168.1.111\\backups."""
    return carpeta.lstrip("\\").split("\\")[0]


class NoContesta(OSError):
    """La PC de una carpeta de red no contestó (apagada o sin red)."""


def explicar_error(error: OSError, carpeta: str) -> str:
    """Por qué no se pudo entrar o guardar en una carpeta, en palabras."""
    codigo = getattr(error, "winerror", None)
    if isinstance(error, NoContesta) or codigo in _SIN_RED:
        return f"No se llega a {carpeta}: ¿está prendida esa PC y conectada a la red?"
    if codigo in _USUARIO_O_CLAVE:
        return (f"El usuario o la clave de {carpeta} no son correctos. Quitá la carpeta y volvé "
                "a agregarla con el usuario y la clave.")
    if codigo == _OTRO_USUARIO_YA_CONECTADO:
        return (f"Esta PC ya está conectada a {servidor_de(carpeta)} con otro usuario. Reiniciá "
                "esta PC y volvé a probar.")
    if codigo in _SIN_LUGAR:
        return f"No hay más lugar en {carpeta}."
    if isinstance(error, FileNotFoundError):
        return f"No se encuentra la carpeta {carpeta}."
    if isinstance(error, PermissionError):
        return f"No hay permiso para guardar en {carpeta}."
    return f"No se pudo guardar en {carpeta} ({error.strerror or error})."


# ---------------------------------------------------------------------------
# Dónde se guardan
# ---------------------------------------------------------------------------

def carpeta_local() -> str:
    """data/backups. Se resuelve en cada llamada (no al importar) para respetar
    la base temporal de los tests."""
    return os.path.join(database.DATA_DIR, "backups")


def carpetas_extra() -> list:
    """Las otras carpetas donde va cada copia, en el orden en que se agregaron."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_CARPETAS_EXTRA,)
        ).fetchone()
    try:
        carpetas = json.loads(fila["valor"]) if fila else []
    except (ValueError, TypeError):
        return []
    return [c for c in carpetas if isinstance(c, str) and c] if isinstance(carpetas, list) else []


def _guardar_carpetas_extra(carpetas: list):
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_CARPETAS_EXTRA, json.dumps(carpetas)),
        )


def _misma_carpeta(una: str, otra: str) -> bool:
    return os.path.normcase(una) == os.path.normcase(otra)


def agregar_carpeta_extra(usuario_id: int, carpeta: str, usuario_red: str = "", clave_red: str = "") -> str:
    """
    Suma una carpeta donde va cada copia. Solo Admin. Si es de otra PC y vienen
    usuario y clave, se los pasa a Windows (no se guardan acá). Antes de sumarla
    prueba guardar un archivo ahí. ValueError (con el mensaje para la pantalla)
    si no se puede. Una carpeta de un disco de esta PC se crea si el disco está
    (el dueño escribe D:\\BACKUPS y listo); una de otra PC tiene que estar
    compartida allá. Después, las copias nunca crean una carpeta que falta: con el
    disco cambiado o desconectado quedarían donde no van. Devuelve la carpeta
    como quedó.
    """
    usuarios_repo.exigir_admin(usuario_id, "elegir dónde se guardan las copias de seguridad")
    carpeta = (carpeta or "").strip().rstrip("\\/")
    if not carpeta:
        raise ValueError("Escribí la carpeta (por ejemplo D:\\BACKUPS o \\\\192.168.1.111\\backups).")
    if re.fullmatch(r"[A-Za-z]:", carpeta):
        carpeta += "\\"  # "D:" solo es "la carpeta en uso de D:", no la raíz del disco
    carpeta = carpeta if es_carpeta_de_red(carpeta) else os.path.normpath(carpeta)
    if es_carpeta_de_red(carpeta) and len([p for p in carpeta.split("\\") if p]) < 2:
        raise ValueError("A una carpeta de otra PC le falta el nombre de la carpeta compartida "
                         "(por ejemplo \\\\192.168.1.111\\backups).")
    datos = os.path.normcase(os.path.abspath(database.DATA_DIR))
    if not es_carpeta_de_red(carpeta):
        if not os.path.isabs(carpeta):
            raise ValueError("Escribí la carpeta completa, con la letra del disco (por ejemplo D:\\BACKUPS).")
        elegida = os.path.normcase(os.path.abspath(carpeta))
        if elegida == datos or elegida.startswith(datos + os.sep):
            raise ValueError("Esa es la carpeta del programa: las copias ya quedan ahí. Elegí otro "
                             "disco u otra PC.")
    actuales = carpetas_extra()
    if any(_misma_carpeta(carpeta, otra) for otra in actuales):
        raise ValueError("Esa carpeta ya está en la lista.")
    if len(actuales) >= MAXIMO_CARPETAS_EXTRA:
        raise ValueError(f"Ya hay {MAXIMO_CARPETAS_EXTRA} carpetas: quitá una antes de agregar otra.")
    if es_carpeta_de_red(carpeta) and usuario_red.strip():
        _darle_a_windows_usuario_y_clave(servidor_de(carpeta), usuario_red.strip(), clave_red)
    if not es_carpeta_de_red(carpeta) and not os.path.isdir(carpeta):
        disco = os.path.splitdrive(carpeta)[0] + os.sep
        if not os.path.isdir(disco):
            raise ValueError(f"No se encuentra el disco {disco} en esta PC.")
        try:
            os.makedirs(carpeta)
        except OSError as error:
            raise ValueError(explicar_error(error, carpeta)) from None
    _probar_que_se_puede_guardar(carpeta)
    _guardar_carpetas_extra(actuales + [carpeta])
    _estado["extra"].pop(carpeta, None)
    return carpeta


def quitar_carpeta_extra(usuario_id: int, carpeta: str):
    """Deja de copiar a esa carpeta (lo que ya está ahí no se toca). Solo Admin."""
    usuarios_repo.exigir_admin(usuario_id, "cambiar dónde se guardan las copias de seguridad")
    _guardar_carpetas_extra([c for c in carpetas_extra() if not _misma_carpeta(c, carpeta)])
    _estado["extra"].pop(carpeta, None)


def _darle_a_windows_usuario_y_clave(servidor: str, usuario: str, clave: str):
    """
    Guarda el usuario y la clave de las carpetas de `servidor` en el
    Administrador de credenciales de Windows (del usuario que tiene abierto el
    programa), como "Recordar mis credenciales": Windows los usa solo cada vez
    que se entra a esa PC, también después de reiniciar. La clave no pasa por la
    base ni por el log (ni siquiera en un error: `from None`).
    """
    try:
        resultado = subprocess.run(
            ["cmdkey", f"/add:{servidor}", f"/user:{usuario}", f"/pass:{clave}"],
            capture_output=True, timeout=20,
            # sin esto, el .exe (sin consola) haría aparecer una ventana negra
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
        )
    except (OSError, subprocess.SubprocessError):
        raise ValueError("No se pudo cargar el usuario y la clave en Windows.") from None
    if resultado.returncode != 0:
        raise ValueError(f"Windows no aceptó el usuario y la clave para {servidor}.")


def _que_conteste(carpeta: str):
    """Si `carpeta` es de otra PC, NoContesta si esa PC no contesta en
    SEGUNDOS_PARA_CONTESTAR (ver PUERTO_CARPETAS_COMPARTIDAS)."""
    if not es_carpeta_de_red(carpeta):
        return
    try:
        socket.create_connection(
            (servidor_de(carpeta), PUERTO_CARPETAS_COMPARTIDAS), timeout=SEGUNDOS_PARA_CONTESTAR
        ).close()
    except OSError as error:
        raise NoContesta(str(error)) from None


def _probar_que_se_puede_guardar(carpeta: str):
    prueba = os.path.join(carpeta, f"prueba_cyberbios{_SUFIJO_A_MEDIAS}")
    try:
        _que_conteste(carpeta)
        os.listdir(carpeta)  # da la razón verdadera (sin red, usuario o clave mal...)
        with open(prueba, "wb") as archivo:
            archivo.write(b"prueba")
        os.remove(prueba)
    except OSError as error:
        raise ValueError(explicar_error(error, carpeta)) from None


def _copias_en(carpeta: str, ahora: datetime = None) -> list:
    """[(momento, ruta)] de las copias automáticas de una carpeta, de la más
    vieja a la más nueva. Con `ahora`, sin las que dicen ser del futuro (el
    reloj de la PC se atrasó): si no, ninguna copia nueva sería "la última" y no
    se volvería a copiar hasta que el reloj las alcance."""
    try:
        nombres = os.listdir(carpeta)
    except OSError:
        return []
    copias = []
    for nombre in nombres:
        momento = momento_de_la_copia(nombre)
        if momento is not None and (ahora is None or momento <= ahora + timedelta(minutes=1)):
            copias.append((momento, os.path.join(carpeta, nombre)))
    return sorted(copias)


def _ultimo_cierre():
    with conexion_db() as conexion:
        fila = conexion.execute("SELECT MAX(fecha_cierre) AS fecha FROM cierres_turno").fetchone()
    try:
        return datetime.fromisoformat(fila["fecha"]) if fila["fecha"] else None
    except ValueError:
        return None


def _borrar_si_existe(ruta: str):
    try:
        os.remove(ruta)
    except OSError:
        pass


def _borrar_las_que_sobran(carpeta: str):
    for nombre in nombres_a_borrar(os.listdir(carpeta)):
        _borrar_si_existe(os.path.join(carpeta, nombre))  # si una no se puede borrar, la próxima vez


# ---------------------------------------------------------------------------
# Hacer las copias
# ---------------------------------------------------------------------------

def _copiar_en_esta_pc(ahora: datetime) -> str:
    """Una copia nueva en data/backups. Se graba con otro nombre y se renombra
    al final: si algo falla a mitad de camino, no queda un .db a medias que
    parezca la última copia (y que se lleve a las otras carpetas)."""
    carpeta = carpeta_local()
    os.makedirs(carpeta, exist_ok=True)
    destino = os.path.join(carpeta, nombre_de_copia(ahora))
    a_medias = destino + _SUFIJO_A_MEDIAS
    _borrar_si_existe(a_medias)
    try:
        database._backup_consistente(a_medias)
        os.replace(a_medias, destino)
    except BaseException:
        _borrar_si_existe(a_medias)
        raise
    _borrar_las_que_sobran(carpeta)
    return destino


def _llevar_a(carpeta: str, origen: str) -> str:
    """Deja `origen` en `carpeta` (si ya está, nada). OSError si no se puede."""
    _que_conteste(carpeta)
    destino = os.path.join(carpeta, os.path.basename(origen))
    if os.path.exists(destino):
        return destino
    os.listdir(carpeta)  # da la razón verdadera si no está (y nunca la crea)
    a_medias = destino + _SUFIJO_A_MEDIAS
    try:
        shutil.copyfile(origen, a_medias)
        os.replace(a_medias, destino)
    except BaseException:
        _borrar_si_existe(a_medias)
        raise
    _borrar_las_que_sobran(carpeta)
    return destino


def _llevar_a_las_otras_carpetas(ahora: datetime) -> list:
    """
    Deja la última copia de esta PC en cada una de las otras carpetas.
    Devuelve [{"carpeta", "destino" (o None), "error" (o None)}]. Se llama en
    cada revisión: si una carpeta no estaba, la copia llega cuando vuelve.
    """
    copias = _copias_en(carpeta_local(), ahora)
    if not copias:
        return []
    momento, origen = copias[-1]
    resultados = []
    for carpeta in carpetas_extra():
        anterior = _estado["extra"].get(carpeta, {})
        try:
            destino = _llevar_a(carpeta, origen)
        except OSError as error:
            mensaje = explicar_error(error, carpeta)
            # Al log va solo la primera vez que aparece cada error: con la otra PC
            # apagada toda una noche, serían cientos de renglones iguales.
            if anterior.get("error") != mensaje:
                registrar_error(error, f"Copia de seguridad en otra carpeta: {carpeta}")
            _estado["extra"][carpeta] = {"ultima": anterior.get("ultima"), "error": mensaje}
            resultados.append({"carpeta": carpeta, "destino": None, "error": mensaje})
            continue
        _estado["extra"][carpeta] = {"ultima": momento, "error": None}
        resultados.append({"carpeta": carpeta, "destino": destino, "error": None})
    return resultados


def copia_automatica_si_corresponde(ahora: datetime = None):
    """
    Lo que hace el hilo en cada revisión: la copia si toca (ver toca_copia) y
    llevar la última a las otras carpetas. Devuelve la ruta de la copia nueva o
    None. Nunca levanta un error: lo anota en el log y en la pantalla de copias.
    """
    ahora = ahora or datetime.now()
    if not os.path.exists(database.DB_PATH):
        return None  # todavía no hay base (y leer la configuración la crearía vacía)
    with _candado:
        nueva = None
        reintentar_desde = _estado["reintentar_desde"]
        try:
            if reintentar_desde is None or ahora >= reintentar_desde:
                ultimas = _copias_en(carpeta_local(), ahora)
                if toca_copia(ultimas[-1][0] if ultimas else None, _ultimo_cierre(), ahora):
                    nueva = _copiar_en_esta_pc(ahora)
                    _estado["error_local"] = None
                    _estado["reintentar_desde"] = None
        except Exception as error:
            _estado["reintentar_desde"] = ahora + timedelta(minutes=MINUTOS_ANTES_DE_REINTENTAR)
            mensaje = f"No se pudo hacer la copia en esta PC ({error})."
            if _estado["error_local"] != mensaje:
                registrar_error(error, "Copia de seguridad automática")
            _estado["error_local"] = mensaje
        try:
            _llevar_a_las_otras_carpetas(ahora)
        except Exception as error:  # la base no contestó al leer las carpetas: la próxima vez
            registrar_error(error, "Copia de seguridad en otras carpetas")
        return nueva


def hacer_copia_ahora() -> dict:
    """
    El botón "Hacer copia de seguridad ahora": copia en esta PC y en las otras carpetas.
    {"local": ruta, "extra": lo de _llevar_a_las_otras_carpetas}. Si la copia de
    esta PC falla, levanta el error (la pantalla lo muestra).
    """
    with _candado:
        ahora = datetime.now()
        local = _copiar_en_esta_pc(ahora)
        _estado["error_local"] = None
        _estado["reintentar_desde"] = None
        extra = _llevar_a_las_otras_carpetas(ahora)
    return {"local": local, "extra": extra}


def guardar_copia_en(carpeta: str) -> str:
    """Una copia suelta donde se elija (un pendrive), que no se borra nunca sola."""
    return database.copiar_backup_a(carpeta)


def estado() -> dict:
    """Para la pantalla de copias: la última en esta PC y cómo anduvo cada una
    de las otras carpetas (sin mirar las carpetas: ver `_estado`)."""
    local = _copias_en(carpeta_local())
    return {
        "carpeta_local": carpeta_local(),
        "ultima_local": local[-1][0] if local else None,
        "cantidad_local": len(local),
        "error_local": _estado["error_local"],
        "extra": [
            {
                "carpeta": carpeta,
                "revisada": carpeta in _estado["extra"],
                "ultima": _estado["extra"].get(carpeta, {}).get("ultima"),
                "error": _estado["extra"].get(carpeta, {}).get("error"),
            }
            for carpeta in carpetas_extra()
        ],
    }


def iniciar_copias_automaticas():
    """Arranca el hilo de las copias (solo el mostrador: main.py). La primera
    revisión es enseguida, como la copia que antes se hacía al abrir."""
    threading.Thread(target=_revisar_siempre, name="copias-de-seguridad", daemon=True).start()


def _revisar_siempre():
    while True:
        try:
            copia_automatica_si_corresponde()
        except Exception as error:  # el hilo no se puede morir: sin él no hay más copias
            registrar_error(error, "Copias de seguridad automáticas")
        time.sleep(SEGUNDOS_ENTRE_REVISIONES)
