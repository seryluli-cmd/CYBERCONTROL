"""
envio_pwa_repo.py
==================
Mandar cada Cierre de Turno a la app de gastos del dueño -- la PWA "Gastos —
CyberBIOS" (cyberbios.netlify.app, repo CYBERBIOS WEB) -- para que quede asentado
allá como el cierre de caja de ese turno, a nombre de la responsable de la caja,
sin que nadie lo cargue a mano desde el celular (pedido del dueño, 2026-10-26;
la propuesta está en PROPUESTA_CIERRE_A_PWA_CYBERBIOS.md, en la carpeta de los
proyectos).

Cómo se habla con la app: igual que un celular. La PWA guarda sus datos en
Firestore (Firebase) y entra con un "login anónimo" usando la clave PÚBLICA que
está en su código (CLAVE_PUBLICA_FIREBASE, la misma de state.js); sus reglas
dejan leer y escribir a cualquiera que haya entrado así. Acá se hace lo mismo
con pedidos HTTPS comunes (urllib, sin librerías aparte): un login anónimo que se
conserva (su "refresh token" queda en `configuracion`, así el mostrador es
siempre el mismo usuario anónimo allá y no crea uno por envío) y un PATCH por
cierre a la colección `facturacion`. No se expone nada nuevo: esa clave ya es
pública y las reglas ya son esas. Si algún día se endurecen, estos envíos
empiezan a fallar con "permiso denegado" y habrá que pasar a una cuenta de
servicio de Firebase (una llave secreta fuera de este repo, como la de la firma
del Cliente PC).

Reglas:
- El cierre NUNCA espera a internet. `encolar` deja una fila en `envios_pwa` en
  la misma transacción que graba el cierre (turnos_repo.cerrar_turno: el que
  confirma la empleada, el que se hace en ausencia y el forzoso), solo si el
  envío está prendido en ese momento (Configuración ADMIN > Cierres a la app de
  gastos; viene apagado). Lo de antes de prenderlo no se manda: ya está cargado
  a mano allá.
- Un hilo propio (iniciar_envios_automaticos, lo arranca main.py en el mostrador)
  manda los pendientes cada SEGUNDOS_ENTRE_REVISIONES y reintenta los que
  fallaron, esperando `intentos` minutos entre pruebas (hasta
  MINUTOS_MAXIMOS_ENTRE_REINTENTOS): sin internet se mandan solos cuando vuelve.
  Sin internet no se prueban los demás pendientes hasta la próxima revisión.
- Un cierre se manda UNA vez aunque se reintente: el documento allá tiene un
  nombre fijo (documento_id) y el envío lo pisa entero; un corte a mitad de
  camino no deja dos. Una vez ENVIADO no se vuelve a mandar: si el dueño lo edita
  o lo borra allá, acá no se toca (la verdad de lo cobrado es este programa).
- Qué viaja (datos_del_cierre): lo mismo que carga una empleada a mano: el TOTAL
  (efectivo + digital, sin el Cambio Fijo), el efectivo, lo digital, el turno con
  el nombre de allá (turnos.turno_para_la_app_de_gastos), el día en que ARRANCÓ
  el turno (como allá) y `registradoPor` = el NOMBRE de la responsable de la caja
  (quien la tenía al cerrarse; sin caja, quien cerró), no de quien apretó el
  botón. Allá el usuario es solo ese texto: tiene que estar escrito igual que en
  la app (mayúsculas incluidas); si no, se ve sin color y no entra en sus
  estadísticas. No hacen falta contraseñas compartidas: el PIN de la app no
  participa. Van además campos que la app ignora y sirven para distinguirlo:
  origen, cierreId, caja, forzoso y cerradoPor.
- Desde otra PC (admin_remoto) no hay nada de esto: la cola y el hilo son del
  mostrador.
"""

import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, time as hora_del_dia, timedelta, timezone

import database
import dominio
from database import conexion_db
from errores import registrar_error
from repositories import cajas_repo, usuarios_repo
from turnos import etiqueta_turno, turno_para_la_app_de_gastos

# La app de gastos: su proyecto de Firebase y la clave PÚBLICA con que entra cada
# celular (CYBERBIOS WEB/state.js, DEFAULT_FIREBASE_CONFIG). No es un secreto: así
# funcionan las apps web de Firebase; lo que protege son las reglas de Firestore.
CLAVE_PUBLICA_FIREBASE = "AIzaSyCnTWkffUqTQDLg2pvy_SU79rX7uZ4rlqM"
PROYECTO_FIREBASE = "controlinterno-659c4"
NEGOCIO = "cyberbios"        # NEGOCIOS[0].id de la app: el campo `negocio` de cada cierre
COLECCION = "facturacion"    # donde la app guarda los cierres
ORIGEN = "cybercontrol"      # el campo `origen` que distingue los cierres que llegaron de acá
URL_FIRESTORE = (f"https://firestore.googleapis.com/v1/projects/{PROYECTO_FIREBASE}"
                 "/databases/(default)/documents")
URL_LOGIN = f"https://identitytoolkit.googleapis.com/v1/accounts:signUp?key={CLAVE_PUBLICA_FIREBASE}"
URL_RENOVAR = f"https://securetoken.googleapis.com/v1/token?key={CLAVE_PUBLICA_FIREBASE}"

SEGUNDOS_ENTRE_REVISIONES = 60
SEGUNDOS_DE_ESPERA = 20                 # lo que se espera cada pedido antes de darlo por caído
MINUTOS_MAXIMOS_ENTRE_REINTENTOS = 60
ENVIOS_POR_REVISION = 20                # alcanza de sobra: hay 2 o 3 cierres por día
ULTIMOS_EN_PANTALLA = 30
# La app guarda la fecha de un cierre como ese día a las 12:00 (facturado.js,
# saveCierre: `new Date(fechaStr + "T12:00:00")`). Se manda igual, para que se
# ordene y se agrupe con los cargados a mano.
HORA_DEL_CIERRE_EN_LA_APP = 12

_CLAVE_ACTIVADO = "envio_pwa_activado"
_CLAVE_RENOVACION = "envio_pwa_renovacion"
_SEGUNDOS_DE_MARGEN_DEL_TOKEN = 60

_candado = threading.Lock()   # un envío por vez: el hilo y los botones no se pisan
# Lo dispara cada cierre apenas queda grabado (avisar_que_hay_un_cierre): el hilo
# manda en ese momento, sin esperar a la próxima revisión.
_hay_novedades = threading.Event()
# El token con que se entra, en memoria (dura una hora; se renueva solo).
_sesion = {"token": None, "vence": 0.0}
# Lo último que pasó, para la pantalla (en memoria, como copias_repo._estado).
_estado = {"ultimo_error": None, "ultima_revision": None}


class FalloDeEnvio(ValueError):
    """No se pudo hablar con la app de gastos; el mensaje está pensado para el
    dueño. `frena` = no tiene sentido probar los demás pendientes ahora (sin
    internet)."""

    def __init__(self, mensaje: str, frena: bool = False):
        super().__init__(mensaje)
        self.frena = frena


# ---------------------------------------------------------------------------
# Prendido / apagado
# ---------------------------------------------------------------------------

def _activado(conexion) -> bool:
    fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_ACTIVADO,)).fetchone()
    return bool(fila) and fila["valor"] == "1"


def esta_activado() -> bool:
    with conexion_db() as conexion:
        return _activado(conexion)


def activar(usuario_id: int, prendido: bool):
    """Prende o apaga el envío. Solo Admin. Apagarlo no borra lo pendiente: se
    manda cuando se vuelva a prender."""
    usuarios_repo.exigir_admin(usuario_id, "prender o apagar el envío de los cierres a la app de gastos")
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_ACTIVADO, "1" if prendido else "0"),
        )


# ---------------------------------------------------------------------------
# La cola
# ---------------------------------------------------------------------------

def documento_id(cierre_id: int, fecha_turno) -> str:
    """El nombre del documento allá: fijo para cada cierre (un reintento lo pisa,
    no lo duplica). Lleva la fecha además del número por si algún día la base
    arranca de cero y los números se repiten."""
    return f"{ORIGEN}-{cierre_id}-{str(fecha_turno)[:10]}"


def encolar(conexion, cierre_id: int, ahora: datetime = None) -> bool:
    """Deja el cierre en la cola, en la transacción de quien llama
    (turnos_repo.cerrar_turno). Con el envío apagado no hace nada y devuelve
    False."""
    if not _activado(conexion):
        return False
    fila = conexion.execute("SELECT fecha FROM cierres_turno WHERE id = ?", (cierre_id,)).fetchone()
    conexion.execute(
        "INSERT OR IGNORE INTO envios_pwa (cierre_id, documento_id, estado, encolado_en) VALUES (?, ?, ?, ?)",
        (cierre_id, documento_id(cierre_id, fila["fecha"]), dominio.ENVIO_PENDIENTE,
         (ahora or datetime.now()).isoformat()),
    )
    return True


def datos_del_cierre(conexion, cierre_id: int) -> dict:
    """
    Lo que se asienta allá de un cierre, con las claves de la app (ver el
    comentario del módulo): importe, efectivo, digital, turno, registradoPor,
    fecha (date: el día en que arrancó el turno), creadoEn (datetime: la hora
    real del cierre), más origen, cierreId, caja (None sin caja), forzoso y
    cerradoPor.
    """
    cierre = conexion.execute(
        """
        SELECT cierres_turno.*, usuarios.nombre AS cerrado_por
        FROM cierres_turno JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
        WHERE cierres_turno.id = ?
        """,
        (cierre_id,),
    ).fetchone()
    if cierre is None:
        raise ValueError(f"No existe el cierre Nº {cierre_id}.")
    caja = cajas_repo._caja_del_cierre(conexion, cierre_id)
    efectivo = round(cierre["ventas_efectivo"], 2)
    digital = round(cierre["ventas_digital"], 2)
    return {
        "importe": round(efectivo + digital, 2),
        "efectivo": efectivo,
        "digital": digital,
        "turno": turno_para_la_app_de_gastos(cierre["fecha"], cierre["turno"]),
        # La responsable de la caja al cerrarse, no quien apretó el botón: si el
        # Admin cierra en ausencia de Gabriela, allá figura Gabriela.
        "registradoPor": caja["responsable"] if caja is not None else cierre["cerrado_por"],
        "fecha": date.fromisoformat(cierre["fecha"][:10]),
        "creadoEn": datetime.fromisoformat(cierre["fecha_cierre"]),
        "origen": ORIGEN,
        "cierreId": cierre_id,
        "caja": caja["id"] if caja is not None else None,
        "forzoso": bool(caja["cierre_forzoso"]) if caja is not None else False,
        "cerradoPor": cierre["cerrado_por"],
    }


def _momento_utc(momento: datetime) -> str:
    """Una fecha y hora de esta PC (hora local, sin zona) como la escribe
    Firestore: en UTC, formato RFC 3339."""
    en_utc = momento.astimezone(timezone.utc)
    return en_utc.strftime("%Y-%m-%dT%H:%M:%S.%fZ" if en_utc.microsecond else "%Y-%m-%dT%H:%M:%SZ")


def _numero(valor) -> dict:
    """Un monto como lo guarda la app desde el celular: entero si no tiene centavos."""
    return {"integerValue": str(int(valor))} if float(valor).is_integer() else {"doubleValue": float(valor)}


def a_campos_firestore(datos: dict) -> dict:
    """El cuerpo del PATCH: lo de `datos_del_cierre` con los tipos de Firestore."""
    campos = {
        "importe": _numero(datos["importe"]),
        "efectivo": _numero(datos["efectivo"]),
        "digital": _numero(datos["digital"]),
        "turno": {"stringValue": datos["turno"]},
        "registradoPor": {"stringValue": datos["registradoPor"]},
        "negocio": {"stringValue": NEGOCIO},
        "fecha": {"timestampValue": _momento_utc(
            datetime.combine(datos["fecha"], hora_del_dia(HORA_DEL_CIERRE_EN_LA_APP)))},
        "creadoEn": {"timestampValue": _momento_utc(datos["creadoEn"])},
        "origen": {"stringValue": datos["origen"]},
        "cierreId": {"integerValue": str(datos["cierreId"])},
        "forzoso": {"booleanValue": bool(datos["forzoso"])},
        "cerradoPor": {"stringValue": datos["cerradoPor"]},
    }
    if datos["caja"] is not None:
        campos["caja"] = {"integerValue": str(datos["caja"])}
    return {"fields": campos}


# ---------------------------------------------------------------------------
# Hablar con Google
# ---------------------------------------------------------------------------

def _transporte_http(metodo: str, url: str, datos, cabeceras: dict) -> tuple:
    """Un pedido HTTPS: (código, cuerpo como texto). Lo que no llega a contestar
    (sin internet, se cortó, tardó más de SEGUNDOS_DE_ESPERA) levanta OSError. Es
    lo que las pruebas reemplazan por una app de mentira."""
    pedido = urllib.request.Request(url, data=datos, headers=cabeceras, method=metodo)
    try:
        with urllib.request.urlopen(pedido, timeout=SEGUNDOS_DE_ESPERA) as respuesta:
            return respuesta.status, respuesta.read().decode("utf-8", "replace")
    except urllib.error.HTTPError as error:
        return error.code, error.read().decode("utf-8", "replace")


def _pedir(transporte, metodo: str, url: str, datos, token: str = None, formulario: bool = False) -> tuple:
    cabeceras = {"Content-Type": "application/x-www-form-urlencoded" if formulario else "application/json"}
    if token:
        cabeceras["Authorization"] = f"Bearer {token}"
    try:
        return transporte(metodo, url, datos, cabeceras)
    except OSError as error:
        motivo = getattr(error, "reason", None) or error
        raise FalloDeEnvio(f"Sin internet, o no se llega a Google desde esta PC ({motivo}).", frena=True) from None


def _json(texto: str) -> dict:
    try:
        datos = json.loads(texto)
    except ValueError:
        raise FalloDeEnvio("Google contestó algo que no se entiende (¿una red con portal de ingreso?).") from None
    return datos if isinstance(datos, dict) else {}


def _campo(datos: dict, nombre: str):
    try:
        return datos[nombre]
    except KeyError:
        raise FalloDeEnvio(f"Google contestó sin el dato '{nombre}' (¿una red con portal de ingreso?).") from None


def _mensaje_de_google(texto: str) -> str:
    try:
        return str(json.loads(texto)["error"]["message"])[:120]
    except (ValueError, TypeError, KeyError):
        return ""


def explicar_respuesta(codigo: int, texto: str = "") -> str:
    """Por qué la app de gastos no aceptó un pedido, en palabras para el dueño."""
    if codigo in (401, 403):
        return ("La app de gastos no dejó entrar (permiso denegado). Si se cambiaron las reglas de "
                "Firebase, hay que revisarlas.")
    if codigo == 404:
        return "La app de gastos no encontró dónde guardar el cierre (¿cambió el proyecto de Firebase?)."
    if codigo == 429:
        return "Google pidió esperar (demasiados pedidos seguidos). Se vuelve a probar más tarde."
    if codigo >= 500:
        return f"Google contestó con un error ({codigo}). Se vuelve a probar más tarde."
    detalle = _mensaje_de_google(texto)
    return f"La app de gastos rechazó el pedido ({codigo}{': ' + detalle if detalle else ''})."


def _leer_renovacion():
    with conexion_db() as conexion:
        fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_RENOVACION,)).fetchone()
    return fila["valor"] if fila and fila["valor"] else None


def _guardar_sesion(token: str, segundos: int, renovacion: str):
    _sesion["token"] = token
    _sesion["vence"] = time.monotonic() + segundos
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (_CLAVE_RENOVACION, renovacion)
        )


def _olvidar_sesion():
    _sesion["token"], _sesion["vence"] = None, 0.0


def _entrar(transporte) -> str:
    """
    El token para hablar con Firestore. El que está en memoria mientras no venza;
    si no, se renueva con el "refresh token" guardado (el mismo usuario anónimo
    de siempre) y, si no hay o Google no lo acepta (lo borraron allá), un login
    anónimo nuevo, que queda guardado para la próxima.
    """
    if _sesion["token"] and time.monotonic() < _sesion["vence"] - _SEGUNDOS_DE_MARGEN_DEL_TOKEN:
        return _sesion["token"]
    renovacion = _leer_renovacion()
    if renovacion:
        formulario = urllib.parse.urlencode({"grant_type": "refresh_token", "refresh_token": renovacion}).encode()
        codigo, texto = _pedir(transporte, "POST", URL_RENOVAR, formulario, formulario=True)
        if codigo == 200:
            datos = _json(texto)
            _guardar_sesion(_campo(datos, "id_token"), int(_campo(datos, "expires_in")), _campo(datos, "refresh_token"))
            return _sesion["token"]
    codigo, texto = _pedir(transporte, "POST", URL_LOGIN, json.dumps({"returnSecureToken": True}).encode())
    if codigo != 200:
        raise FalloDeEnvio("No se pudo entrar a la app de gastos: " + explicar_respuesta(codigo, texto))
    datos = _json(texto)
    _guardar_sesion(_campo(datos, "idToken"), int(_campo(datos, "expiresIn")), _campo(datos, "refreshToken"))
    return _sesion["token"]


# ---------------------------------------------------------------------------
# Mandar
# ---------------------------------------------------------------------------

def _mandar(fila: dict, transporte):
    """Manda un cierre de la cola. FalloDeEnvio si la app no lo aceptó."""
    with conexion_db() as conexion:
        datos = datos_del_cierre(conexion, fila["cierre_id"])
    cuerpo = json.dumps(a_campos_firestore(datos)).encode()
    url = f"{URL_FIRESTORE}/{COLECCION}/{fila['documento_id']}"
    for es_el_primer_intento in (True, False):
        codigo, texto = _pedir(transporte, "PATCH", url, cuerpo, token=_entrar(transporte))
        if codigo == 200:
            return
        if codigo in (401, 403) and es_el_primer_intento:
            _olvidar_sesion()  # el token venció o lo revocaron: entrar de nuevo y probar una vez más
            continue
        raise FalloDeEnvio(explicar_respuesta(codigo, texto))


def _filas_pendientes(conexion, ahora: datetime) -> list:
    return [dict(fila) for fila in conexion.execute(
        """
        SELECT * FROM envios_pwa
        WHERE estado IN (?, ?) AND (proximo_intento IS NULL OR proximo_intento <= ?)
        ORDER BY cierre_id
        LIMIT ?
        """,
        (dominio.ENVIO_PENDIENTE, dominio.ENVIO_ERROR, ahora.isoformat(), ENVIOS_POR_REVISION),
    ).fetchall()]


def _anotar_enviado(envio_id: int, ahora: datetime):
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE envios_pwa SET estado = ?, enviado_en = ?, ultimo_error = NULL, proximo_intento = NULL, "
            "intentos = intentos + 1 WHERE id = ?",
            (dominio.ENVIO_ENVIADO, ahora.isoformat(), envio_id),
        )


def _anotar_error(fila: dict, mensaje: str, ahora: datetime):
    intentos = fila["intentos"] + 1
    espera = timedelta(minutes=min(intentos, MINUTOS_MAXIMOS_ENTRE_REINTENTOS))
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE envios_pwa SET estado = ?, intentos = ?, ultimo_error = ?, proximo_intento = ? WHERE id = ?",
            (dominio.ENVIO_ERROR, intentos, mensaje, (ahora + espera).isoformat(), fila["id"]),
        )


def enviar_pendientes(ahora: datetime = None, transporte=None) -> dict:
    """
    Lo que hace el hilo en cada revisión (y "Reintentar ahora"): manda los
    cierres de la cola que toca mandar, de a uno, en el orden en que se
    cerraron. Devuelve {"enviados", "con_error"}. Nunca levanta un error: cada
    fallo queda en su fila (y en el log la primera vez que aparece ese mensaje).
    Con el envío apagado no manda nada: lo pendiente espera.
    """
    ahora = ahora or datetime.now()
    transporte = transporte or _transporte_http
    resultado = {"enviados": 0, "con_error": 0}
    with _candado:
        with conexion_db() as conexion:
            pendientes = _filas_pendientes(conexion, ahora) if _activado(conexion) else []
        for fila in pendientes:
            contexto = f"Envío del cierre Nº {fila['cierre_id']} a la app de gastos"
            try:
                _mandar(fila, transporte)
            except FalloDeEnvio as error:
                _anotar_error(fila, str(error), ahora)
                resultado["con_error"] += 1
                if _estado["ultimo_error"] != str(error):
                    registrar_error(error, contexto)
                _estado["ultimo_error"] = str(error)
                if error.frena:
                    break
            except Exception as error:  # algo inesperado (la base, un dato roto): no frena a los demás
                _anotar_error(fila, f"Error inesperado ({type(error).__name__}: {error}).", ahora)
                resultado["con_error"] += 1
                registrar_error(error, contexto)
            else:
                _anotar_enviado(fila["id"], ahora)
                resultado["enviados"] += 1
                _estado["ultimo_error"] = None
        _estado["ultima_revision"] = ahora
    return resultado


def reintentar_ahora(transporte=None) -> dict:
    """El botón "Reintentar ahora": los que fallaron se prueban ya, sin esperar
    su turno."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE envios_pwa SET proximo_intento = NULL WHERE estado = ?", (dominio.ENVIO_ERROR,))
    return enviar_pendientes(transporte=transporte)


def _nombres(campos: dict, lista: str) -> list:
    return [valor.get("stringValue", "") for valor in campos.get(lista, {}).get("arrayValue", {}).get("values", [])]


def probar_conexion(transporte=None) -> dict:
    """
    El botón "Probar la conexión": entra a la app de gastos y trae los nombres
    que conoce (config/socios: el dueño y los colaboradores), SIN escribir nada,
    y dice qué usuarios activos de acá no están allá escritos igual ("faltan"):
    a esos la app los mostraría sin color y fuera de sus estadísticas.
    FalloDeEnvio si no se pudo.
    """
    transporte = transporte or _transporte_http
    with _candado:
        token = _entrar(transporte)
        codigo, texto = _pedir(transporte, "GET", f"{URL_FIRESTORE}/config/socios", None, token=token)
    if codigo != 200:
        raise FalloDeEnvio(explicar_respuesta(codigo, texto))
    campos = _json(texto).get("fields", {})
    nombres = _nombres(campos, "socios") + _nombres(campos, "colaboradores")
    activos = [usuario["nombre"] for usuario in usuarios_repo.listar_usuarios()]
    return {"nombres_app": nombres, "faltan": [nombre for nombre in activos if nombre not in nombres]}


def estado_del_cierre(cierre_id: int):
    """Cómo va UN cierre en la cola ({"estado", "ultimo_error"}), o None si no está
    (el envío estaba apagado al cerrarlo). Lo mira la barra "ENVIANDO CIERRE DE
    TURNO" (ui/envio_pwa_progreso.py) mientras el hilo lo manda."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT estado, ultimo_error FROM envios_pwa WHERE cierre_id = ?", (cierre_id,)
        ).fetchone()
    return dict(fila) if fila else None


def estado() -> dict:
    """Para la pantalla: si está prendido, cuántos hay en cada estado, el último
    enviado, el último error y los últimos cierres de la cola con cómo les fue."""
    with conexion_db() as conexion:
        activado = _activado(conexion)
        cuentas = {fila["estado"]: fila["cantidad"] for fila in conexion.execute(
            "SELECT estado, COUNT(*) AS cantidad FROM envios_pwa GROUP BY estado"
        )}
        ultimo = conexion.execute("SELECT MAX(enviado_en) AS momento FROM envios_pwa").fetchone()["momento"]
        ultimos = [dict(fila) for fila in conexion.execute(
            """
            SELECT envios_pwa.*, cierres_turno.fecha, cierres_turno.turno,
                   cierres_turno.ventas_efectivo + cierres_turno.ventas_digital AS total,
                   COALESCE(responsables.nombre, quien_cerro.nombre) AS responsable
            FROM envios_pwa
            JOIN cierres_turno ON cierres_turno.id = envios_pwa.cierre_id
            JOIN usuarios AS quien_cerro ON quien_cerro.id = cierres_turno.usuario_id
            LEFT JOIN cajas ON cajas.cierre_id = cierres_turno.id
            LEFT JOIN usuarios AS responsables ON responsables.id = cajas.responsable_id
            ORDER BY envios_pwa.cierre_id DESC
            LIMIT ?
            """,
            (ULTIMOS_EN_PANTALLA,),
        )]
    for fila in ultimos:
        fila["turno_label"] = etiqueta_turno(fila["fecha"], fila["turno"])
    return {
        "activado": activado,
        "pendientes": cuentas.get(dominio.ENVIO_PENDIENTE, 0),
        "con_error": cuentas.get(dominio.ENVIO_ERROR, 0),
        "enviados": cuentas.get(dominio.ENVIO_ENVIADO, 0),
        "ultimo_enviado": ultimo,
        "ultimo_error": _estado["ultimo_error"],
        "ultima_revision": _estado["ultima_revision"],
        "ultimos": ultimos,
    }


# ---------------------------------------------------------------------------
# El hilo
# ---------------------------------------------------------------------------

def iniciar_envios_automaticos():
    """Arranca el hilo que manda los pendientes (solo el mostrador: main.py)."""
    threading.Thread(target=_revisar_siempre, name="envio-a-la-app-de-gastos", daemon=True).start()


def avisar_que_hay_un_cierre():
    """Lo llama turnos_repo.cerrar_turno DESPUÉS de grabar el cierre (fuera de su
    transacción): el hilo se despierta y lo manda en ese momento. Si el envío falla,
    sigue el reintento de siempre."""
    _hay_novedades.set()


def _revisar_siempre(detener: threading.Event = None):
    """El hilo: manda lo pendiente al arrancar, cada vez que un cierre lo despierta y,
    si no, cada SEGUNDOS_ENTRE_REVISIONES (los reintentos). `detener` es para las
    pruebas; en el mostrador corre hasta que se cierra el programa."""
    while detener is None or not detener.is_set():
        try:
            # Sin base todavía no hay nada que mandar (y leer la configuración la crearía vacía).
            if os.path.exists(database.DB_PATH):
                enviar_pendientes()
        except Exception as error:  # el hilo no se puede morir: sin él no se manda nada más
            registrar_error(error, "Envío de los cierres a la app de gastos")
        _hay_novedades.wait(SEGUNDOS_ENTRE_REVISIONES)
        _hay_novedades.clear()
