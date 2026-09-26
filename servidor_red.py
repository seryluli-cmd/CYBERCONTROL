"""
servidor_red.py
=================
Servidor HTTP liviano embebido en Kiosko para que el agente de bloqueo
de cada PC cliente (carpeta hermana "AGENTE PC KIOSKO") pueda preguntar
el estado de su estación sin tocar la base de datos directamente. Corre
en un hilo de fondo desde que arranca el programa (ver main.py), sin
importar quién esté logueado ni qué pantalla esté abierta -- las PCs
clientes tienen que poder preguntar en cualquier momento.

Solo lectura por ahora: expone GET /estado?estacion=<nombre>. Todavía no
hay ningún endpoint que escriba en la base (que un Miembro se loguee
directo desde su PC cliente es un paso aparte, a propósito separado de
este primero -- ver CLAUDE.md, sección Roadmap).

Puerto en PUERTO_SERVIDOR más abajo: un solo lugar para cambiarlo.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from repositories import pcs_repo

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
            cuerpo = json.dumps(_estado_a_json(item)).encode("utf-8")
        except Exception:
            # Un problema leyendo la base no puede tirar abajo el hilo
            # del servidor -- se responde 500 y sigue escuchando.
            self.send_response(500)
            self.end_headers()
            return

        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)


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
