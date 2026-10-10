"""
servidor_red.py
=================
Servidor HTTP liviano embebido en Kiosko para que el Cliente PC (carpeta
hermana "CLIENTE PC") instalado en cada PC del salón pueda preguntar
el estado de su estación sin tocar la base de datos directamente. Corre
en un hilo de fondo desde que arranca el programa (ver main.py), sin
importar quién esté logueado ni qué pantalla esté abierta -- las PCs
clientes tienen que poder preguntar en cualquier momento.

Autenticación: todo pedido (GET y POST) exige la cabecera
`Authorization: Bearer <clave>` con la clave generada en Control de PCs ->
Gestionar Estaciones -> Generar/renovar clave de Clientes PC (ver
`control_pcs/repositories/clientes_repo.py`). Es UNA sola clave compartida
por todas las estaciones. Sin clave generada todavía, o con una que no
coincide, responde 403 sin tocar la base (ver `_ManejadorEstado._autorizado`).

Endpoints
---------
GET /estado?estacion=<nombre>
    Solo lectura; cada PC cliente lo consulta cada pocos segundos para saber
    si debe mostrarse bloqueada. En el mismo viaje de red:
    - Si el mostrador dejó un comando remoto pendiente para esa estación
      (ver control_pcs/repositories/comandos_pc_repo.py y el menú
      contextual de Control de PCs), viaja como "comando" -- no hace falta
      un endpoint aparte, el Cliente PC ya está preguntando de todas formas.
    - Cada pedido válido deja constancia de "última conexión" y de la IP LAN
      de origen (`pcs_repo.registrar_conexion`; la IP sale de
      `self.client_address`, no de un dato que mande el Cliente PC). Es el
      latido con que el dashboard de Control de PCs sabe si una estación
      sigue prendida y con red, no solo si tiene sesión; la IP rellena el
      botón "Traer IP" de Gestionar Estaciones.

POST /login           {"estacion", "usuario", "clave"}
    Un Miembro se loguea directo desde su PC cliente con TODO su saldo
    (mismo mecanismo que miembros_repo.abrir_estacion_por_miembro, el de la
    pantalla Miembros).

POST /logout          {"estacion", "sesion_id" (opcional)}
    Corta YA la sesión activa de esa estación (mismo mecanismo que
    "Finalizar antes de tiempo", ver pcs_repo.finalizar_sesion) para que
    quien usa la PC cierre su propia sesión sin pasar por el mostrador. No
    pide usuario/clave: alcanza con estar físicamente en esa PC, mismo
    criterio de confianza que el resto del sistema.

POST /evento_admin    {"estacion", "tipo", "segundos_atras"}
    El Cliente PC avisa que alguien entró a su panel admin, cerró el
    Cliente PC o abrió la reconfiguración (ver
    control_pcs/repositories/accesos_admin_pc_repo.py: es lo que le permite
    al dueño enterarse de una PC que quedó sin bloqueo). `segundos_atras`
    es para los avisos que no se pudieron mandar en el momento (servidor
    apagado) y se mandan al volver la conexión.

POST /comando_resultado   {"comando_id", "imagen_base64"} o {"comando_id", "texto"}
    El Cliente PC lo llama después de ejecutar un comando que tiene algo
    para devolver: SCREENSHOT (sube la imagen) o CAMBIAR_RED (avisa si pudo
    cambiar de módem; a diferencia de reiniciar/apagar, esto sí puede
    fallar del lado de la PC y el mostrador tiene que enterarse). Los demás
    comandos no devuelven nada.

El puerto está en PUERTO_SERVIDOR más abajo: un solo lugar para cambiarlo.
"""

import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

import dominio
from errores import registrar_error
from control_pcs.repositories import (
    accesos_admin_pc_repo, clientes_repo, comandos_pc_repo, miembros_repo, pcs_repo,
)

PUERTO_SERVIDOR = 8899

_servidor = None  # el servidor en marcha, o None si no arrancó (ver iniciar_servidor)

# Mensajes de error que se repiten en varios endpoints.
_PEDIDO_INVALIDO = "Pedido inválido."
_ERROR_INTERNO = "Error interno."


def _estado_a_json(item):
    """
    Arma la respuesta de GET /estado a partir de lo que devuelve
    pcs_repo.estado_de_estacion (None = estación desconocida).
    """
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
        # El Cliente PC lo guarda (ver red_kiosko.consultar_estado) para
        # mandarlo de vuelta en su próximo POST /logout -- ver
        # _manejar_logout sobre por qué hace falta.
        "sesion_id": sesion["id"] if sesion is not None else None,
        "comando": None,  # lo completa do_GET si hay uno pendiente para esta estación
    }


class _ManejadorEstado(BaseHTTPRequestHandler):
    """Atiende un pedido de un Cliente PC: do_GET resuelve /estado y do_POST
    reparte el resto de los endpoints (ver el docstring del módulo)."""

    def log_message(self, formato, *args):
        pass  # sin esto, cada consulta imprime una línea de acceso en la consola -- no aporta nada acá

    def _responder_json(self, status: int, cuerpo_dict: dict):
        cuerpo = json.dumps(cuerpo_dict).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(cuerpo)))
        self.end_headers()
        self.wfile.write(cuerpo)

    def _responder_vacio(self, status: int):
        """Responde solo con el código de estado, sin cuerpo: así se rechaza
        un pedido sin autorización y los errores de GET /estado."""
        self.send_response(status)
        self.end_headers()

    def _responder_error(self, status: int, mensaje: str):
        """Responde con {"ok": False, "error": mensaje}: el formato de error
        de los POST (el Cliente PC muestra ese mensaje tal cual)."""
        self._responder_json(status, {"ok": False, "error": mensaje})

    def _autorizado(self) -> bool:
        """
        Todo pedido de un Cliente PC viaja con `Authorization: Bearer <clave>`
        (ver `red_kiosko._cabeceras_cliente` en CLIENTE PC). Si en
        Kiosko todavía no se generó ninguna clave (Control de PCs ->
        Gestionar Estaciones -> Generar/renovar clave de Clientes PC), no se
        regala el beneficio de la duda -- mismo criterio fail-safe que
        `_estado_a_json` con una estación desconocida.
        """
        clave_configurada = clientes_repo.obtener_clave_clientes()
        if not clave_configurada:
            return False
        return self.headers.get("Authorization") == "Bearer " + clave_configurada

    def do_GET(self):
        try:
            autorizado = self._autorizado()
        except Exception as error:
            registrar_error(error, "Servidor de red: autorización GET")
            self._responder_vacio(500)
            return
        if not autorizado:
            self._responder_vacio(403)
            return

        ruta = urlparse(self.path)
        if ruta.path != "/estado":
            self._responder_vacio(404)
            return

        nombre_estacion = (parse_qs(ruta.query).get("estacion") or [""])[0]
        if not nombre_estacion:
            self._responder_vacio(400)
            return

        try:
            item = pcs_repo.estado_de_estacion(nombre_estacion)
        except Exception as error:
            # Un problema leyendo la base no puede tirar abajo el hilo
            # del servidor -- se responde 500 y sigue escuchando.
            registrar_error(error, "Servidor de red: leer estado de PC")
            self._responder_vacio(500)
            return

        cuerpo = _estado_a_json(item)
        if item is not None:
            try:
                # Que haya llegado hasta acá (autorizado, estación
                # conocida) ya prueba que el Cliente PC está prendido y con
                # red -- es la señal que usa el dashboard de Control de
                # PCs para distinguir "disponible" de "sin conexión". De
                # paso, self.client_address (IP real del socket, no un
                # dato que mande el Cliente PC) queda guardada como
                # estaciones.ultima_ip -- lo que lee el botón "Traer IP"
                # de Gestionar Estaciones.
                pcs_repo.registrar_conexion(item["estacion"]["id"], self.client_address[0])
            except Exception as error:
                registrar_error(error, "Servidor de red: registrar conexión de PC")
            if item["estacion"]["cliente_cerrado_desde"] is not None:
                # Esta PC había quedado sin Cliente PC (alguien lo cerró
                # desde el panel admin) y acaba de volver: se anota cuánto
                # estuvo así. Solo se mira cuando hay marca, así que un
                # pedido normal no cuesta nada de más.
                try:
                    accesos_admin_pc_repo.registrar_regreso_del_cliente(item["estacion"]["id"])
                except Exception as error:
                    registrar_error(error, "Servidor de red: registrar regreso del Cliente PC")
            try:
                comando = comandos_pc_repo.proximo_comando_pendiente(item["estacion"]["id"])
                if comando is not None:
                    comandos_pc_repo.marcar_entregado(comando["id"])
                    cuerpo["comando"] = {
                        "id": comando["id"], "tipo": comando["tipo"], "payload": comando["payload"],
                    }
            except Exception as error:
                registrar_error(error, "Servidor de red: consultar comando remoto")

        try:
            # Viaja en TODO pedido de estado (exista o no la estación) para
            # que cada PC cliente la mantenga al día sola en un archivo
            # local propio, sin tener que ir PC por PC cuando se cambia --
            # ver clientes_repo y el panel admin ("A") de cliente_pc.py.
            cuerpo["clave_admin"] = clientes_repo.obtener_clave_admin_pcs()
        except Exception as error:
            registrar_error(error, "Servidor de red: leer clave admin de PCs")

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
        except Exception as error:
            registrar_error(error, "Servidor de red: resolver estación")
            self._responder_error(500, _ERROR_INTERNO)
            return None
        if item is None:
            # Mismo criterio fail-safe que _estado_a_json: un nombre de
            # estación que no existe en Kiosko nunca deja pasar nada.
            self._responder_error(404, "Estación desconocida.")
            return None
        return item

    def do_POST(self):
        try:
            autorizado = self._autorizado()
        except Exception as error:
            registrar_error(error, "Servidor de red: autorización POST")
            self._responder_error(500, _ERROR_INTERNO)
            return
        if not autorizado:
            self._responder_vacio(403)
            return

        ruta = urlparse(self.path)
        if ruta.path == "/login":
            self._manejar_login()
        elif ruta.path == "/logout":
            self._manejar_logout()
        elif ruta.path == "/evento_admin":
            self._manejar_evento_admin()
        elif ruta.path == "/comando_resultado":
            self._manejar_comando_resultado()
        else:
            self._responder_error(404, "No existe.")

    def _manejar_login(self):
        try:
            cuerpo = self._leer_cuerpo_json()
            nombre_estacion = str(cuerpo["estacion"])
            usuario = str(cuerpo["usuario"])
            clave = str(cuerpo["clave"])
        except Exception:
            self._responder_error(400, _PEDIDO_INVALIDO)
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
            self._responder_error(400, str(error))
            return
        except Exception as error:
            registrar_error(error, "Servidor de red: login de socio")
            self._responder_error(500, _ERROR_INTERNO)
            return

        self._responder_json(200, {"ok": True, **resumen})

    def _manejar_logout(self):
        """
        Cierra la sesión activa de una estación -- pero solo si sigue
        siendo la MISMA sesión para la que el Cliente PC pidió el cierre.

        `sesion_id` es opcional en el body (un Cliente PC viejo que no lo
        manda sigue cerrando lo que esté activo), pero si viene tiene que
        coincidir con la sesión activa actual. Sin este chequeo, un pedido
        de cierre demorado (red lenta, servidor ocupado) podía llegar
        DESPUÉS de que esa sesión ya se cerró por otro lado (el mostrador
        la finalizó a mano) y de que se abrió una sesión NUEVA en la misma
        estación: el pedido viejo de Juan terminaba cortándole la sesión
        recién pagada a María. Si no coincide, la sesión que el Cliente PC
        quería cerrar ya no existe: se responde OK sin tocar nada (su
        objetivo, "que esa sesión esté cerrada", ya se cumplió).
        """
        try:
            cuerpo = self._leer_cuerpo_json()
            nombre_estacion = str(cuerpo["estacion"])
            sesion_id_pedida = cuerpo.get("sesion_id")
        except Exception:
            self._responder_error(400, _PEDIDO_INVALIDO)
            return

        item = self._resolver_estacion(nombre_estacion)
        if item is None:
            return  # _resolver_estacion ya respondió 404/500

        if item["sesion"] is None:
            self._responder_error(400, "No hay ninguna sesión activa en esta estación.")
            return

        if sesion_id_pedida is not None and sesion_id_pedida != item["sesion"]["id"]:
            self._responder_json(200, {"ok": True})
            return

        try:
            pcs_repo.finalizar_sesion(item["sesion"]["id"])
        except Exception as error:
            registrar_error(error, "Servidor de red: logout de socio")
            self._responder_error(500, _ERROR_INTERNO)
            return

        self._responder_json(200, {"ok": True})

    def _manejar_evento_admin(self):
        """
        Anota un aviso del panel admin de un Cliente PC (ver
        accesos_admin_pc_repo). Como /logout, no pide usuario ni clave
        propia: alcanza con la clave de Clientes PC que ya exige do_POST.
        """
        try:
            cuerpo = self._leer_cuerpo_json()
            nombre_estacion = str(cuerpo["estacion"])
            tipo = str(cuerpo["tipo"])
            segundos_atras = float(cuerpo.get("segundos_atras") or 0)
        except Exception:
            self._responder_error(400, _PEDIDO_INVALIDO)
            return
        if tipo not in dominio.EVENTOS_ADMIN_REPORTADOS_POR_CLIENTE:
            self._responder_error(400, "Tipo de evento inválido.")
            return

        item = self._resolver_estacion(nombre_estacion)
        if item is None:
            return  # _resolver_estacion ya respondió 404/500

        try:
            accesos_admin_pc_repo.registrar_evento(item["estacion"]["id"], tipo, segundos_atras)
        except ValueError:
            self._responder_error(400, _PEDIDO_INVALIDO)
            return
        except Exception as error:
            registrar_error(error, "Servidor de red: evento admin de PC")
            self._responder_error(500, _ERROR_INTERNO)
            return

        self._responder_json(200, {"ok": True})

    def _manejar_comando_resultado(self):
        """
        El Cliente PC sube acá el resultado de un comando ya ejecutado: la
        captura de pantalla de un SCREENSHOT (`imagen_base64`, ver
        comandos_pc_repo.guardar_screenshot) o un texto corto "OK"/"ERROR:
        ..." de un CAMBIAR_RED (`texto`, directo a `comandos_pc.resultado`).
        No hace falta validar que la estación exista o que el comando siga
        "pendiente": si alguien tarda en mandarlo, guardarlo igual no
        rompe nada -- lo único que mira pcs_comandos_dialogos.py es si a ESE
        comando_id ya le llegó un resultado.
        """
        try:
            cuerpo = self._leer_cuerpo_json()
            comando_id = int(cuerpo["comando_id"])
        except Exception:
            self._responder_error(400, _PEDIDO_INVALIDO)
            return

        try:
            if "imagen_base64" in cuerpo:
                ruta_relativa = comandos_pc_repo.guardar_screenshot(comando_id, str(cuerpo["imagen_base64"]))
                comandos_pc_repo.marcar_resultado(comando_id, ruta_relativa)
            elif "texto" in cuerpo:
                comandos_pc_repo.marcar_resultado(comando_id, str(cuerpo["texto"])[:500])
            else:
                self._responder_error(400, _PEDIDO_INVALIDO)
                return
        except Exception as error:
            registrar_error(error, "Servidor de red: resultado de comando")
            self._responder_error(500, _ERROR_INTERNO)
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
    except OSError as error:
        registrar_error(error, "Servidor de red: abrir puerto")
        return None
    hilo = threading.Thread(target=_servidor.serve_forever, daemon=True)
    hilo.start()
    return _servidor
