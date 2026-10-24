"""
cliente.py
===========
Lo que hace la COPIA REMOTA (el programa abierto en otra PC del local para
administrar, ver modo.py): hablarle al CyberBIOS del mostrador y hacer que las
pantallas, sin enterarse, le pidan todo a él.

`instalar(conexion)` reemplaza cada función de la lista blanca, en su módulo de
repositories/ o control_pcs/repositories/, por un "representante" que manda la
llamada al mostrador y devuelve lo que contesta. Las pantallas siguen llamando a
`articulos_repo.modificar_articulo(...)` como siempre: por eso ninguna pantalla
puede importar una función de un repo suelta (`from repositories.x import f`),
siempre el módulo.

Además deja la base de esta PC CERRADA a propósito: si una pantalla quisiera
algo que no está en la lista, falla con un mensaje claro en vez de abrir (o
crear vacía) una base propia. Y el log de errores de esta copia va a una carpeta
de esta PC, no a la carpeta compartida del mostrador.

Errores: un rechazo "de negocio" del mostrador (ValueError, PermissionError)
llega como la misma excepción con el mismo mensaje, así las pantallas lo
muestran igual que en el mostrador. Sin red, o con el mostrador cerrado, es
SinConexion (un ValueError: las pantallas lo muestran como un aviso, no como un
error del programa).
"""

import http.client
import json
import os
import sys
import tempfile
import urllib.error
import urllib.request

import database
from admin_remoto import codec, lista_blanca, modo
from servidor_red import PUERTO_SERVIDOR as PUERTO
# Un reporte de un año puede tardar unos segundos en armarse en el mostrador.
ESPERA_LLAMADA_SEGUNDOS = 60
ESPERA_HOLA_SEGUNDOS = 6
# Cuánto se espera para CONECTAR con el mostrador (en la red del local tarda
# milisegundos). Con el programa del mostrador cerrado, Windows no rechaza: no
# contesta nada, y cada pedido esperaba la espera entera. Con la grilla de PCs,
# que pide cada 5 segundos, la ventana quedaba trabada.
ESPERA_CONECTAR_SEGUNDOS = 2


class _ConexionHttp(http.client.HTTPConnection):
    """Conecta con ESPERA_CONECTAR_SEGUNDOS; la respuesta se espera con la espera
    del pedido."""

    def connect(self):
        espera = self.timeout
        self.timeout = ESPERA_CONECTAR_SEGUNDOS
        try:
            super().connect()
        finally:
            self.timeout = espera
        self.sock.settimeout(espera)


class _ManejadorHttp(urllib.request.HTTPHandler):
    def http_open(self, pedido):
        return self.do_open(_ConexionHttp, pedido)


# Sin proxy: el mostrador está en la red del local, y un proxy puesto en Windows
# (Opciones de Internet) se llevaría el pedido afuera.
_abrir = urllib.request.build_opener(urllib.request.ProxyHandler({}), _ManejadorHttp).open


class SinConexion(ValueError):
    """No se pudo hablar con el CyberBIOS del mostrador."""


class _ErrorDelMostrador(Exception):
    """El mostrador contestó que no (con un tipo y un mensaje para mostrar)."""

    def __init__(self, tipo: str, mensaje: str):
        super().__init__(mensaje)
        self.tipo = tipo
        self.mensaje = mensaje


class ConexionConElMostrador:
    """La charla con el CyberBIOS de una PC del local (su nombre o su IP)."""

    def __init__(self, mostrador: str, puerto: int = PUERTO, huella: str = None):
        self.mostrador = mostrador
        self._base = f"http://{mostrador}:{puerto}/admin/"
        # La huella se calcula ANTES de reemplazar los repos (después, las
        # funciones de la lista serían los representantes).
        self._huella = huella or lista_blanca.huella()
        self._token = None

    # --- el ida y vuelta ---------------------------------------------------

    def _pedir(self, ruta: str, cuerpo: dict, espera: float) -> dict:
        datos = json.dumps(cuerpo).encode("utf-8")
        pedido = urllib.request.Request(
            self._base + ruta, data=datos, method="POST", headers={"Content-Type": "application/json"},
        )
        try:
            with _abrir(pedido, timeout=espera) as respuesta:
                contenido = respuesta.read()
        except urllib.error.HTTPError as error:
            # 400/404/500 vienen igual con su explicación en JSON.
            contenido = error.read()
        except (urllib.error.URLError, OSError) as error:
            raise SinConexion(
                f"No encuentro el CyberBIOS del mostrador ({self.mostrador}). Fijate que esa PC esté "
                "prendida, con el programa abierto, y que esta PC tenga red."
            ) from error
        try:
            respuesta = json.loads(contenido.decode("utf-8"))
        except ValueError as error:
            raise SinConexion(f"El mostrador ({self.mostrador}) contestó algo que no se entiende.") from error
        if not respuesta.get("ok"):
            error = respuesta.get("error") or {}
            raise _ErrorDelMostrador(error.get("tipo", ""), error.get("mensaje", "El mostrador dijo que no."))
        return respuesta

    # --- antes de entrar ---------------------------------------------------

    def hola(self) -> dict:
        """{"activo", "misma_version"} del mostrador (SinConexion si no está)."""
        return self._pedir("hola", {"huella": self._huella}, ESPERA_HOLA_SEGUNDOS)

    def nombres_para_entrar(self) -> list:
        """Los Administradores del mostrador, para la lista de la pantalla de
        ingreso."""
        try:
            return self._pedir("usuarios", {"huella": self._huella}, ESPERA_HOLA_SEGUNDOS)["nombres"]
        except _ErrorDelMostrador as error:
            raise PermissionError(error.mensaje) from None

    def entrar(self, nombre: str, clave: str):
        """La fila del Administrador si la clave es correcta (y queda la sesión
        abierta), o None si no. PermissionError con el motivo si el mostrador
        no deja entrar (apagado, demasiados intentos, otra versión)."""
        try:
            respuesta = self._pedir(
                "entrar", {"huella": self._huella, "nombre": nombre, "clave": clave}, ESPERA_HOLA_SEGUNDOS,
            )
        except _ErrorDelMostrador as error:
            if error.tipo == "Clave":
                return None
            raise PermissionError(error.mensaje) from None
        self._token = respuesta["token"]
        return codec.de_json(respuesta["usuario"])

    def salir(self):
        """Cierra la sesión en el mostrador (si no hay red, igual se olvida acá:
        vence sola)."""
        token, self._token = self._token, None
        if token is None:
            return
        try:
            self._pedir("salir", {"token": token}, ESPERA_HOLA_SEGUNDOS)
        except (SinConexion, _ErrorDelMostrador):
            pass

    @property
    def adentro(self) -> bool:
        return self._token is not None

    # --- con la sesión abierta ---------------------------------------------

    def llamar(self, nombre_modulo: str, nombre_funcion: str, args, kwargs):
        """Hace `nombre_modulo.nombre_funcion(*args, **kwargs)` en el mostrador."""
        if self._token is None:
            raise PermissionError("Primero hay que entrar con el usuario Administrador.")
        try:
            respuesta = self._pedir("llamar", {
                "token": self._token, "modulo": nombre_modulo, "funcion": nombre_funcion,
                "args": codec.a_json(list(args)), "kwargs": codec.a_json(dict(kwargs)),
            }, ESPERA_LLAMADA_SEGUNDOS)
        except _ErrorDelMostrador as error:
            # Un permiso o una sesión vencida es un "no se puede"; lo demás (un
            # dato mal puesto, una falla del mostrador) se muestra como aviso.
            if error.tipo in ("PermissionError", "Permiso", "Sesion"):
                raise PermissionError(error.mensaje) from None
            raise ValueError(error.mensaje) from None
        return codec.de_json(respuesta["resultado"])


# --------------------------------------------------------------------
# Hacer que las pantallas le pidan todo al mostrador
# --------------------------------------------------------------------

def _carpeta_local() -> str:
    """Dónde guarda sus cosas (solo el log de errores) la copia remota: una
    carpeta de ESTA PC, nunca la compartida del mostrador."""
    base = os.environ.get("LOCALAPPDATA") or tempfile.gettempdir()
    return os.path.join(base, "CyberBIOS", "administracion_remota")


def _base_cerrada(*_args, **_kwargs):
    raise PermissionError(
        "Eso no se puede hacer desde otra PC: hacelo en el mostrador. "
        "(Esta copia no tiene base de datos propia.)"
    )


def _representante(conexion, nombre_modulo: str, nombre_funcion: str, original):
    def llamar_al_mostrador(*args, **kwargs):
        return conexion.llamar(nombre_modulo, nombre_funcion, args, kwargs)
    llamar_al_mostrador.__name__ = nombre_funcion
    llamar_al_mostrador.__qualname__ = f"{nombre_modulo}.{nombre_funcion}"
    llamar_al_mostrador.__doc__ = getattr(original, "__doc__", None)
    llamar_al_mostrador.original = original
    return llamar_al_mostrador


# listar_usuarios y autenticar_por_nombre ANTES de entrar: la pantalla de
# ingreso los usa sin sesión abierta. En la copia remota ofrece solo a los
# Administradores y entra por el mostrador, que es quien mira la clave.
def _listar_usuarios_para_entrar(conexion, original_remoto):
    def listar_usuarios(*args, **kwargs):
        if conexion.adentro:
            return original_remoto(*args, **kwargs)
        return [codec.FilaRemota(["nombre"], [nombre]) for nombre in conexion.nombres_para_entrar()]
    listar_usuarios.original = original_remoto.original
    return listar_usuarios


def _entrar_por_el_mostrador(conexion, original):
    def autenticar_por_nombre(nombre, clave):
        return conexion.entrar(nombre, clave)
    autenticar_por_nombre.original = original
    return autenticar_por_nombre


_deshacer = []  # (objeto, atributo, valor de antes), para las pruebas


def instalar(conexion: ConexionConElMostrador):
    """
    Convierte ESTE programa en una copia remota que le pide todo a `conexion`.
    No tiene vuelta atrás dentro del programa (para las pruebas, desinstalar()).
    """
    carpeta = _carpeta_local()
    _cambiar(database, "DATA_DIR", carpeta)
    _cambiar(database, "DB_PATH", os.path.join(carpeta, "sin_base_en_esta_pc.db"))

    # La base de esta PC, cerrada: en database y en cada módulo que ya se haya
    # traído su propia referencia con `from database import conexion_db`.
    originales_db = {nombre: getattr(database, nombre) for nombre in ("conexion_db", "get_connection")}
    for modulo_cargado in list(sys.modules.values()):
        for nombre, original in originales_db.items():
            if getattr(modulo_cargado, nombre, None) is original:
                _cambiar(modulo_cargado, nombre, _base_cerrada)

    for nombre_modulo, nombres in lista_blanca.FUNCIONES.items():
        modulo_repo = lista_blanca.modulo(nombre_modulo)
        for nombre_funcion in nombres:
            original = getattr(modulo_repo, nombre_funcion)
            _cambiar(modulo_repo, nombre_funcion, _representante(conexion, nombre_modulo, nombre_funcion, original))

    usuarios_repo = lista_blanca.modulo("usuarios_repo")
    _cambiar(usuarios_repo, "listar_usuarios", _listar_usuarios_para_entrar(conexion, usuarios_repo.listar_usuarios))
    _cambiar(usuarios_repo, "autenticar_por_nombre",
             _entrar_por_el_mostrador(conexion, usuarios_repo.autenticar_por_nombre))
    modo.activar(conexion.mostrador)


def _cambiar(objeto, atributo, valor):
    _deshacer.append((objeto, atributo, getattr(objeto, atributo)))
    setattr(objeto, atributo, valor)


def desinstalar():
    """Para las pruebas: deja todo como estaba antes de instalar()."""
    while _deshacer:
        objeto, atributo, valor = _deshacer.pop()
        setattr(objeto, atributo, valor)
    modo.desactivar()


def conectar(mostrador: str, puerto: int = PUERTO, huella: str = None) -> ConexionConElMostrador:
    """
    Se presenta al mostrador y, si todo está bien, devuelve la conexión lista
    para instalar(). Si no, una excepción con el mensaje para mostrar:
    SinConexion (no está), PermissionError (entrada apagada u otra versión).
    `huella` es para las pruebas (la de "otro programa"); si no, la de este.
    """
    conexion = ConexionConElMostrador(mostrador, puerto, huella)
    respuesta = conexion.hola()
    if not respuesta.get("misma_version"):
        raise PermissionError(
            f"El CyberBios.exe de esta PC no es el mismo que el del mostrador ({mostrador}).\n\n"
            "Abrí el programa desde la carpeta compartida del mostrador, o copiá en esta PC "
            "el mismo .exe que usa el mostrador."
        )
    if not respuesta.get("activo"):
        raise PermissionError(
            f"El mostrador ({mostrador}) tiene apagada la entrada desde otra PC.\n\n"
            "Prendela en el mostrador: Configuración ADMIN > Entrar desde otra PC."
        )
    return conexion
