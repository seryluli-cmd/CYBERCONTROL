"""
servidor_red.py
=================
Servidor HTTP liviano embebido en Kiosko para que el agente de bloqueo
de cada PC cliente (carpeta hermana "AGENTE PC KIOSKO") pueda preguntar
el estado de su estación sin tocar la base de datos directamente. Corre
en un hilo de fondo desde que arranca el programa (ver main.py), sin
importar quién esté logueado ni qué pantalla esté abierta -- las PCs
clientes tienen que poder preguntar en cualquier momento.

Expone estos endpoints:
- GET /estado?estacion=<nombre> -- solo lectura, consultado cada pocos
  segundos por cada PC cliente para saber si debe mostrarse bloqueada.
  De paso, si el mostrador dejó un comando remoto pendiente para esa
  estación (reiniciar, apagar, mensaje, screenshot -- ver
  control_pcs/repositories/comandos_pc_repo.py y el menú contextual de
  Control de PCs), viaja en el mismo viaje de red como "comando" en vez
  de necesitar un endpoint aparte -- el agente ya está preguntando cada
  5s de todas formas. Cada pedido válido también deja constancia de
  "última conexión" y de la IP LAN de origen (`pcs_repo.registrar_conexion`,
  con `self.client_address` -- no un dato que mande el agente) -- es el
  latido que usa el dashboard de Control de PCs para saber si una
  estación sigue prendida y con red, no solo si tiene sesión, y la IP es
  la que rellena el botón "Traer IP" de Gestionar Estaciones.
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
- POST /comando_resultado -- el agente lo llama después de ejecutar un
  comando SCREENSHOT (para subir la imagen capturada) o CAMBIAR_RED (para
  avisar si pudo cambiar de módem o no -- a diferencia de reiniciar/apagar,
  esto sí puede fallar del lado de la PC y vale la pena que el mostrador
  se entere). Body JSON {"comando_id", "imagen_base64"} o
  {"comando_id", "texto"} según el tipo -- los demás comandos no tienen
  nada que devolver.

Todo pedido (GET y POST) exige la cabecera `Authorization: Bearer <clave>`
con la clave generada en Control de PCs -> Gestionar Estaciones ->
Generar/renovar clave de agentes (ver `control_pcs/repositories/agentes_repo.py`)
-- UNA sola clave compartida por todas las estaciones. Sin clave generada
todavía, o con una que no coincide, el servidor responde 403 sin tocar la
base: ver `_ManejadorEstado._autorizado`.

Puerto en PUERTO_SERVIDOR más abajo: un solo lugar para cambiarlo.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from control_pcs.repositories import agentes_repo, comandos_pc_repo, miembros_repo, pcs_repo

PUERTO_SERVIDOR = 8899

_servidor = None


def _estado_a_json(item):
    if item is None:
        # Estación desconocida (nombre mal escrito en el config.json del
        # cliente, o borrada de Kiosko): bloqueada, nunca se regala el
        # beneficio de la duda.
        return {"existe": False, "bloqueada": True, "segundos_restantes": None, "quien": None, "comando": None}
    sesion = item["sesion"]
    segundos = item["segundos_restantes"]
    bloqueada = sesion is None or (segundos is not None and segundos <= 0)
    quien = sesion["miembro_nombre"] if (sesion is not None and sesion["miembro_nombre"]) else None
    return {
        "existe": True,
        "bloqueada": bloqueada,
        "segundos_restantes": segundos,
        "quien": quien,
        # El agente lo guarda (ver red_kiosko.consultar_estado) para
        # mandarlo de vuelta en su próximo POST /logout -- ver
        # _manejar_logout sobre por qué hace falta.
        "sesion_id": sesion["id"] if sesion is not None else None,
        "comando": None,  # lo completa do_GET si hay uno pendiente para esta estación
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

    def _autorizado(self) -> bool:
        """
        Todo pedido de un agente viaja con `Authorization: Bearer <clave>`
        (ver `red_kiosko._cabeceras_agente` en AGENTE PC KIOSKO). Si en
        Kiosko todavía no se generó ninguna clave (Control de PCs ->
        Gestionar Estaciones -> Generar/renovar clave de agentes), no se
        regala el beneficio de la duda -- mismo criterio fail-safe que
        `_estado_a_json` con una estación desconocida.
        """
        clave_configurada = agentes_repo.obtener_clave_agentes()
        if not clave_configurada:
            return False
        return self.headers.get("Authorization") == "Bearer " + clave_configurada

    def do_GET(self):
        if not self._autorizado():
            self.send_response(403)
            self.end_headers()
            return

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

        cuerpo = _estado_a_json(item)
        if item is not None:
            try:
                # Que haya llegado hasta acá (autorizado, estación
                # conocida) ya prueba que el agente está prendido y con
                # red -- es la señal que usa el dashboard de Control de
                # PCs para distinguir "disponible" de "sin conexión". De
                # paso, self.client_address (IP real del socket, no un
                # dato que mande el agente) queda guardada como
                # estaciones.ultima_ip -- lo que lee el botón "Traer IP"
                # de Gestionar Estaciones.
                pcs_repo.registrar_conexion(item["estacion"]["id"], self.client_address[0])
            except Exception:
                pass  # no puede romper la consulta de bloqueo por esto
            try:
                comando = comandos_pc_repo.proximo_comando_pendiente(item["estacion"]["id"])
                if comando is not None:
                    comandos_pc_repo.marcar_entregado(comando["id"])
                    cuerpo["comando"] = {
                        "id": comando["id"], "tipo": comando["tipo"], "payload": comando["payload"],
                    }
            except Exception:
                pass  # un comando remoto que falla no puede romper la consulta de bloqueo, lo esencial

        try:
            # Viaja en TODO pedido de estado (exista o no la estación) para
            # que cada PC cliente la mantenga al día sola en un archivo
            # local propio, sin tener que ir PC por PC cuando se cambia --
            # ver agentes_repo y el panel admin ("A") de agente_bloqueo.py.
            cuerpo["clave_admin"] = agentes_repo.obtener_clave_admin_pcs()
        except Exception:
            pass

        self._responder_json(200, cuerpo)

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
        if not self._autorizado():
            self.send_response(403)
            self.end_headers()
            return

        ruta = urlparse(self.path)
        if ruta.path == "/login":
            self._manejar_login()
        elif ruta.path == "/logout":
            self._manejar_logout()
        elif ruta.path == "/comando_resultado":
            self._manejar_comando_resultado()
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
        """
        Cierra la sesión activa de una estación -- pero solo si sigue
        siendo la MISMA sesión para la que el agente pidió el cierre.

        `sesion_id` es opcional en el body (un agente viejo que todavía
        no lo manda sigue funcionando igual que antes, cerrando lo que
        esté activo) pero si viene, tiene que coincidir con la sesión
        activa actual de la estación. Sin este chequeo, un pedido de
        cierre que tarda en procesarse (demora de red, o el servidor
        ocupado con otra cosa) podía llegar DESPUÉS de que esa sesión ya
        se hubiera cerrado por otro lado (el mostrador la finalizó a
        mano) y de que se hubiera abierto una sesión NUEVA en la misma
        estación para otro cliente -- el código de acá solo miraba "qué
        sesión está activa ahora en esta estación" y la cerraba, sin
        importar si era la misma que el agente tenía en mente. Resultado:
        un pedido de cierre viejo de Juan terminaba cortándole la sesión
        recién pagada a María. Si `sesion_id` no coincide, la sesión que
        el agente quería cerrar ya no existe -- responde OK sin tocar
        nada, en vez de error (el objetivo del agente, "que esa sesión
        esté cerrada", ya se cumplió).
        """
        try:
            cuerpo = self._leer_cuerpo_json()
            nombre_estacion = str(cuerpo["estacion"])
            sesion_id_pedida = cuerpo.get("sesion_id")
        except Exception:
            self._responder_json(400, {"ok": False, "error": "Pedido inválido."})
            return

        item = self._resolver_estacion(nombre_estacion)
        if item is None:
            return  # _resolver_estacion ya respondió 404/500

        if item["sesion"] is None:
            self._responder_json(400, {"ok": False, "error": "No hay ninguna sesión activa en esta estación."})
            return

        if sesion_id_pedida is not None and sesion_id_pedida != item["sesion"]["id"]:
            self._responder_json(200, {"ok": True})
            return

        try:
            pcs_repo.finalizar_sesion(item["sesion"]["id"])
        except Exception:
            self._responder_json(500, {"ok": False, "error": "Error interno."})
            return

        self._responder_json(200, {"ok": True})

    def _manejar_comando_resultado(self):
        """
        El agente sube acá el resultado de un comando ya ejecutado: la
        captura de pantalla de un SCREENSHOT (`imagen_base64`, ver
        comandos_pc_repo.guardar_screenshot) o un texto corto "OK"/"ERROR:
        ..." de un CAMBIAR_RED (`texto`, directo a `comandos_pc.resultado`).
        No hace falta validar que la estación exista o que el comando siga
        "pendiente": si alguien tarda en mandarlo, guardarlo igual no
        rompe nada -- lo único que mira pcs_window.py es si a ESE
        comando_id ya le llegó un resultado.
        """
        try:
            cuerpo = self._leer_cuerpo_json()
            comando_id = int(cuerpo["comando_id"])
        except Exception:
            self._responder_json(400, {"ok": False, "error": "Pedido inválido."})
            return

        try:
            if "imagen_base64" in cuerpo:
                ruta_relativa = comandos_pc_repo.guardar_screenshot(comando_id, str(cuerpo["imagen_base64"]))
                comandos_pc_repo.marcar_resultado(comando_id, ruta_relativa)
            elif "texto" in cuerpo:
                comandos_pc_repo.marcar_resultado(comando_id, str(cuerpo["texto"])[:500])
            else:
                self._responder_json(400, {"ok": False, "error": "Pedido inválido."})
                return
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
