"""
servidor_red.py
=================
Servidor HTTP liviano embebido en Kiosko para que el agente de bloqueo
de cada PC cliente (carpeta hermana "AGENTE PC KIOSKO") pueda preguntar
el estado de su estación sin tocar la base de datos directamente. Corre
en un hilo de fondo desde que arranca el programa (ver main.py), sin
importar quién esté logueado ni qué pantalla esté abierta -- las PCs
clientes tienen que poder preguntar en cualquier momento.

Expone tres endpoints:
- GET /estado?estacion=<nombre> -- solo lectura, consultado cada pocos
  segundos por cada PC cliente para saber si debe mostrarse bloqueada.
- POST /login -- un Miembro se loguea directo desde su PC cliente con
  TODO su saldo (mismo mecanismo que miembros_repo.abrir_estacion_por_miembro,
  el que ya usa la pantalla de Miembros del lado de Kiosko). Body JSON
  {"estacion", "usuario", "clave"}.
- POST /logout -- corta YA la sesión activa de esa estación (mismo
  mecanismo que "Finalizar antes de tiempo" en Gestionar PCs, ver
  pcs_repo.finalizar_sesion) para que el que está usando la PC pueda
  cerrar su propia sesión sin pasar por el mostrador. Body JSON
  {"estacion"} -- no pide usuario/clave: alcanza con estar físicamente
  en esa PC, mismo criterio de confianza que ya usa el resto del sistema.

Puerto en PUERTO_SERVIDOR más abajo: un solo lugar para cambiarlo.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from control_pcs.repositories import miembros_repo, pcs_repo

PUERTO_SERVIDOR = 8899

_servidor = None


def _estado_a_json(item):
    if item is None:
        # Estación desconocida (nombre mal escrito en el config.json del
        # cliente, o borrada de Kiosko): bloqueada, nunca se regala el
        # beneficio de la duda.
        return {"existe": False, "bloqueada": True, "segundos_restantes": None, "quien": None}
    sesion = item["sesion"]
    segundos = item["segundos_restantes"]
    bloqueada = sesion is None or (segundos is not None and segundos <= 0)
    quien = sesion["miembro_nombre"] if (sesion is not None and sesion["miembro_nombre"]) else None
    return {
        "existe": True,
        "bloqueada": bloqueada,
        "segundos_restantes": segundos,
        "quien": quien,
    }


class _ManejadorEstado(BaseHTTPRequestHandler):
    def log_message(self, formato, *args):
        pass  # sin esto, cada consulta imprime una línea de acceso en la consola -- no aporta nada acá

    def _responder_json(self, status: int, cuerpo_dict: dict):
        cuerpo = json.dumps(cuerpo_dict).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def do_GET(self):
        ruta = urlparse(self.path)
        if ruta.path != "/estado":
            self.send_response(404)
            self.end_headers()
            return

        nombre_estacion = (parse_qs(ruta.query).get("estacion") or [""])[0]
        if not nombre_estacion:
            self.send_response(400)
            self.end_headers()
            return

        try:
            item = pcs_repo.estado_de_estacion(nombre_estacion)
        except Exception:
            # Un problema leyendo la base no puede tirar abajo el hilo
            # del servidor -- se responde 500 y sigue escuchando.
            self.send_response(500)
            self.end_headers()
            return

        self._responder_json(200, _estado_a_json(item))

    def _leer_cuerpo_json(self) -> dict:
        largo = int(self.headers.get("Content-Length", 0))
        return json.loads(self.rfile.read(largo).decode("utf-8"))

    def _resolver_estacion(self, nombre_estacion: str):
        """
        Busca la estación por nombre y ya manda la respuesta 404/500 ella
        misma si no la encuentra -- así `_manejar_login`/`_manejar_logout`
        solo siguen de largo cuando esto devuelve un item real, sin
        repetir el mismo chequeo en los dos.
        """
        try:
            item = pcs_repo.estado_de_estacion(nombre_estacion)
        except Exception:
            self._responder_json(500, {"ok": False, "error": "Error interno."})
            return None
        if item is None:
            # Mismo criterio fail-safe que _estado_a_json: un nombre de
            # estación que no existe en Kiosko nunca deja pasar nada.
            self._responder_json(404, {"ok": False, "error": "Estación desconocida."})
            return None
        return item

    def do_POST(self):
        ruta = urlparse(self.path)
        if ruta.path == "/login":
            self._manejar_login()
        elif ruta.path == "/logout":
            self._manejar_logout()
        else:
            self._responder_json(404, {"ok": False, "error": "No existe."})

    def _manejar_login(self):
        try:
            cuerpo = self._leer_cuerpo_json()
            nombre_estacion = str(cuerpo["estacion"])
            usuario = str(cuerpo["usuario"])
            clave = str(cuerpo["clave"])
        except Exception:
            self._responder_json(400, {"ok": False, "error": "Pedido inválido."})
            return

        item = self._resolver_estacion(nombre_estacion)
        if item is None:
            return  # _resolver_estacion ya respondió 404/500

        try:
            resumen = miembros_repo.abrir_estacion_por_miembro(
                item["estacion"]["id"], usuario, clave
            )
        except ValueError as error:
            # Credenciales incorrectas o saldo insuficiente -- el mensaje
            # ya viene pensado para mostrarle al Miembro tal cual.
            self._responder_json(400, {"ok": False, "error": str(error)})
            return
        except Exception:
            self._responder_json(500, {"ok": False, "error": "Error interno."})
            return

        self._responder_json(200, {"ok": True, **resumen})

    def _manejar_logout(self):
        try:
            cuerpo = self._leer_cuerpo_json()
            nombre_estacion = str(cuerpo["estacion"])
        except Exception:
            self._responder_json(400, {"ok": False, "error": "Pedido inválido."})
            return

        item = self._resolver_estacion(nombre_estacion)
        if item is None:
            return  # _resolver_estacion ya respondió 404/500

        if item["sesion"] is None:
            self._responder_json(400, {"ok": False, "error": "No hay ninguna sesión activa en esta estación."})
            return

        try:
            pcs_repo.finalizar_sesion(item["sesion"]["id"])
        except Exception:
            self._responder_json(500, {"ok": False, "error": "Error interno."})
            return

        self._responder_json(200, {"ok": True})


def iniciar_servidor():
    """
    Arranca el servidor en un hilo de fondo (`daemon=True`, para que no
    impida cerrar el programa). Se llama una sola vez desde main.py. Si
    el puerto ya está en uso (ej. dos copias de Kiosko abiertas a la
    vez), devuelve None en vez de reventar el arranque de todo el
    programa -- Kiosko tiene que poder seguir funcionando en el
    mostrador aunque esta parte falle.
    """
    global _servidor
    try:
        _servidor = ThreadingHTTPServer(("0.0.0.0", PUERTO_SERVIDOR), _ManejadorEstado)
    except OSError:
        return None
    hilo = threading.Thread(target=_servidor.serve_forever, daemon=True)
    hilo.start()
    return _servidor
