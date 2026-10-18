"""
servidor.py
============
Lo que atiende el CyberBIOS del MOSTRADOR cuando el Administrador trabaja
desde otra PC del local. Lo llama servidor_red.py (el mismo servidor y el
mismo puerto que usan las PCs del cyber) para todo pedido que empiece con
PREFIJO; las PCs del cyber no pasan por acá.

Rutas (todas POST, JSON):

/admin/hola      {"huella"}
    ¿Está el mostrador, está prendida la entrada y somos el mismo programa?
    -> {"ok", "activo", "misma_version"}. No pide clave: no muestra nada.
/admin/usuarios  {"huella"}
    Los nombres de los Administradores, para la lista de la pantalla de ingreso.
/admin/entrar    {"huella", "nombre", "clave"}
    -> {"ok": true, "token", "usuario"} o {"ok": false, "error"}. Después de
    MAX_INTENTOS claves mal seguidas desde una misma PC, esa PC no puede probar
    más por BLOQUEO_MINUTOS (5 por minuto como en el login de siempre sería
    poco: acá cualquiera de la red del local puede probar sin que lo vean).
    Cada PC prueba de a una clave por vez, y hay un tope para todas las PCs
    juntas (MAX_FALLIDOS_EN_TOTAL en VENTANA_TOTAL_MINUTOS).
/admin/llamar    {"token", "modulo", "funcion", "args", "kwargs"}
    Hace UNA función de la lista blanca con la base del mostrador y devuelve
    {"ok": true, "resultado"} o {"ok": false, "error": {"tipo", "mensaje"}}.
/admin/salir     {"token"}
    Cierra la sesión.

Seguridad, dicho sin exagerar (ver también admin_remoto_repo):
- Solo funciones de la lista blanca, y el "quién lo hizo" lo pone el mostrador
  (lista_blanca.ACTOR), no la otra PC.
- La sesión es un número al azar que vive solo en la memoria de este programa:
  se pierde al cerrarlo, vence tras SESION_VENCE_MINUTOS sin uso y solo vale
  desde la PC que entró (misma IP). En cada pedido se vuelve a mirar que la
  entrada siga prendida y que el usuario siga siendo un Admin activo.
- La clave viaja sin cifrar dentro de la red del local, igual que todo lo que
  hablan las PCs con el mostrador. Nada de esto queda abierto a internet.

No toca Qt (corre en los hilos del servidor de red) y nunca anota claves ni el
cuerpo de un pedido en el log de errores.
"""

import collections
import inspect
import json
import secrets
import threading
import time

from admin_remoto import codec, lista_blanca
from errores import registrar_error
from repositories import admin_remoto_repo

PREFIJO = "/admin/"

MAX_INTENTOS = 5
BLOQUEO_MINUTOS = 5
# Tope para TODAS las PCs juntas (cambiándose de IP se podría esquivar el de
# cada PC): con más claves mal que esto en la ventana, nadie prueba desde otra
# PC hasta que se vaya la más vieja. Alguien podría usarlo para no dejar entrar
# al dueño desde otra PC un rato; el mostrador sigue andando igual.
MAX_FALLIDOS_EN_TOTAL = 20
VENTANA_TOTAL_MINUTOS = 15
SESION_VENCE_MINUTOS = 180
# Un fondo de pantalla de las PCs (el pedido más grande) pesa a lo sumo ~1,5 MB.
TAMANO_MAXIMO_PEDIDO = 16 * 1024 * 1024

_MENSAJE_INTERNO = "Algo falló en el mostrador y quedó anotado en su data/errores.log."
_MENSAJE_OTRA_VERSION = (
    "El CyberBios.exe de esta PC no es el mismo que el del mostrador. Abrí el programa "
    "desde la carpeta compartida del mostrador (o copiá el mismo .exe en las dos)."
)
_MENSAJE_SESION_VENCIDA = "La sesión desde esta PC se cerró (o venció). Cerrá sesión y volvé a entrar."

_candado = threading.Lock()
_sesiones = {}   # token -> {"usuario_id", "ip", "ultimo_uso"}
_intentos = {}   # ip -> (claves mal seguidas, bloqueada_hasta)
_probando = set()  # IPs con una clave comprobándose en este momento
_fallidos_recientes = collections.deque()  # cuándo fue cada clave mal (todas las PCs)


def _ahora() -> float:
    return time.monotonic()


def atender(ruta: str, cuerpo: bytes, ip: str):
    """Atiende un pedido de la otra PC. Devuelve (código HTTP, diccionario de
    la respuesta). Nunca deja escapar una excepción (servidor_red responde lo
    que devuelve esto)."""
    try:
        pedido = json.loads(cuerpo.decode("utf-8")) if cuerpo else {}
        if not isinstance(pedido, dict):
            raise ValueError
    except ValueError:
        return 400, {"ok": False, "error": {"tipo": "Pedido", "mensaje": "Pedido inválido."}}

    manejadores = {
        "hola": _hola, "usuarios": _usuarios, "entrar": _entrar, "llamar": _llamar, "salir": _salir,
    }
    manejador = manejadores.get(ruta[len(PREFIJO):]) if ruta.startswith(PREFIJO) else None
    if manejador is None:
        return 404, {"ok": False, "error": {"tipo": "Pedido", "mensaje": "No existe."}}
    try:
        return manejador(pedido, ip)
    except Exception as error:
        registrar_error(error, f"Administración desde otra PC: {ruta}")
        return 500, {"ok": False, "error": {"tipo": "Interno", "mensaje": _MENSAJE_INTERNO}}


def _error(tipo: str, mensaje: str, status: int = 200):
    return status, {"ok": False, "error": {"tipo": tipo, "mensaje": mensaje}}


def _misma_version(pedido) -> bool:
    return pedido.get("huella") == lista_blanca.huella()


def _hola(pedido, ip):
    return 200, {"ok": True, "activo": admin_remoto_repo.esta_activo(), "misma_version": _misma_version(pedido)}


def _usuarios(pedido, ip):
    if not _misma_version(pedido):
        return _error("Version", _MENSAJE_OTRA_VERSION)
    if not admin_remoto_repo.esta_activo():
        return _error("Permiso", "La entrada desde otra PC está apagada en el mostrador.")
    return 200, {"ok": True, "nombres": admin_remoto_repo.administradores_para_entrar()}


def _entrar(pedido, ip):
    if not _misma_version(pedido):
        return _error("Version", _MENSAJE_OTRA_VERSION)
    nombre, clave = pedido.get("nombre"), pedido.get("clave")
    if not isinstance(nombre, str) or not isinstance(clave, str):
        return _error("Pedido", "Pedido inválido.", 400)

    with _candado:
        rechazo = _rechazo_antes_de_probar(ip)
        if rechazo is not None:
            return rechazo
        # Una sola prueba a la vez por PC: si no, muchas mandadas juntas pasaban
        # todas este control antes de que se anotara la primera clave mal.
        _probando.add(ip)

    try:
        usuario = admin_remoto_repo.entrar(nombre, clave, ip)
    except PermissionError as error:
        with _candado:
            _probando.discard(ip)
        return _error("Permiso", str(error))
    except Exception:
        with _candado:
            _probando.discard(ip)
        raise

    with _candado:
        _probando.discard(ip)
        if usuario is None:
            return _anotar_clave_mal(ip)
        if _intentos.get(ip, (0, 0.0))[1] <= _ahora():
            _intentos.pop(ip, None)
        _olvidar_sesiones_vencidas()
        token = secrets.token_urlsafe(32)
        _sesiones[token] = {"usuario_id": usuario["id"], "ip": ip, "ultimo_uso": _ahora()}
    return 200, {"ok": True, "token": token, "usuario": codec.a_json(usuario)}


def _minutos_hasta(momento: float) -> int:
    return int((momento - _ahora()) // 60) + 1


def _rechazo_antes_de_probar(ip):
    """Por qué no se deja probar una clave desde `ip` (la respuesta lista), o
    None si se puede. Con el candado ya tomado."""
    ahora = _ahora()
    while _fallidos_recientes and _fallidos_recientes[0] <= ahora - VENTANA_TOTAL_MINUTOS * 60:
        _fallidos_recientes.popleft()
    bloqueada_hasta = _intentos.get(ip, (0, 0.0))[1]
    if bloqueada_hasta > ahora:
        return _error(
            "Bloqueo",
            f"Demasiadas claves incorrectas seguidas desde esta PC. Esperá {_minutos_hasta(bloqueada_hasta)} "
            "minuto(s) y volvé a intentar.",
        )
    if len(_fallidos_recientes) >= MAX_FALLIDOS_EN_TOTAL:
        libre_desde = _fallidos_recientes[0] + VENTANA_TOTAL_MINUTOS * 60
        return _error(
            "Bloqueo",
            "Hubo demasiadas claves incorrectas desde las PCs del local: la entrada desde otra PC "
            f"queda frenada {_minutos_hasta(libre_desde)} minuto(s). En el mostrador se sigue entrando normal.",
        )
    if ip in _probando:
        return _error("Bloqueo", "Ya hay un intento de entrada en curso desde esta PC. Esperá un momento.")
    return None


def _anotar_clave_mal(ip):
    """Anota una clave mal desde `ip` y devuelve la respuesta. Un bloqueo ya
    puesto nunca se acorta ni se borra acá. Con el candado ya tomado."""
    ahora = _ahora()
    _fallidos_recientes.append(ahora)
    fallidos, bloqueada_hasta = _intentos.get(ip, (0, 0.0))
    if bloqueada_hasta > ahora:
        return _error("Bloqueo", f"Esta PC no puede probar más claves por {_minutos_hasta(bloqueada_hasta)} minuto(s).")
    fallidos += 1
    if fallidos >= MAX_INTENTOS:
        _intentos[ip] = (0, ahora + BLOQUEO_MINUTOS * 60)
        return _error(
            "Bloqueo",
            f"Demasiadas claves incorrectas seguidas: esta PC no puede probar más por {BLOQUEO_MINUTOS} minutos.",
        )
    _intentos[ip] = (fallidos, 0.0)
    return _error("Clave", "Nombre o clave incorrectos.")


def _olvidar_sesiones_vencidas():
    """Saca las sesiones que pasaron SESION_VENCE_MINUTOS sin uso (con el
    candado ya tomado)."""
    limite = _ahora() - SESION_VENCE_MINUTOS * 60
    for token in [token for token, sesion in _sesiones.items() if sesion["ultimo_uso"] < limite]:
        del _sesiones[token]


def _usuario_de_la_sesion(pedido, ip):
    """El id del Admin de esa sesión (y la renueva), o None si no vale: no
    existe, venció o se usa desde otra PC que la que entró."""
    token = pedido.get("token")
    if not isinstance(token, str):
        return None
    with _candado:
        _olvidar_sesiones_vencidas()
        sesion = _sesiones.get(token)
        if sesion is None or sesion["ip"] != ip:
            return None
        sesion["ultimo_uso"] = _ahora()
        return sesion["usuario_id"]


def _llamar(pedido, ip):
    usuario_id = _usuario_de_la_sesion(pedido, ip)
    if usuario_id is None:
        return _error("Sesion", _MENSAJE_SESION_VENCIDA)
    try:
        admin_remoto_repo.exigir_admin_habilitado(usuario_id)
    except PermissionError as error:
        _salir(pedido, ip)
        return _error("Sesion", f"{error} Cerrá sesión.")

    nombre_modulo, nombre_funcion = pedido.get("modulo"), pedido.get("funcion")
    if not (isinstance(nombre_modulo, str) and isinstance(nombre_funcion, str)
            and lista_blanca.permitida(nombre_modulo, nombre_funcion)):
        return _error("Permiso", "Eso no se puede hacer desde otra PC: hacelo en el mostrador.")

    try:
        args = codec.de_json(pedido.get("args") or [])
        kwargs = codec.de_json(pedido.get("kwargs") or {})
        if not isinstance(args, list) or not isinstance(kwargs, dict):
            raise ValueError
        funcion = lista_blanca.funcion(nombre_modulo, nombre_funcion)
        argumentos = inspect.signature(funcion).bind(*args, **kwargs)
    except (ValueError, TypeError):
        return _error("Pedido", "Pedido inválido.", 400)

    actor = lista_blanca.ACTOR.get((nombre_modulo, nombre_funcion))
    if actor is not None:
        argumentos.arguments[actor] = usuario_id

    try:
        resultado = funcion(*argumentos.args, **argumentos.kwargs)
    except (ValueError, PermissionError) as error:
        # Los rechazos "de negocio" (un precio mal puesto, un permiso) llegan a
        # la otra PC con su mensaje, como en el mostrador.
        return _error(type(error).__name__, str(error))
    return 200, {"ok": True, "resultado": codec.a_json(resultado)}


def _salir(pedido, ip):
    token = pedido.get("token")
    with _candado:
        sesion = _sesiones.get(token) if isinstance(token, str) else None
        if sesion is not None and sesion["ip"] == ip:
            del _sesiones[token]
    return 200, {"ok": True}


def _olvidar_todo():
    """Para las pruebas: sin sesiones ni bloqueos."""
    with _candado:
        _sesiones.clear()
        _intentos.clear()
        _probando.clear()
        _fallidos_recientes.clear()
