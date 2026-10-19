"""
cortes_pc_repo.py
=================
Por qué una PC con sesión dejó de dar noticias un rato y volvió sola (pedido del dueño,
2026-10-19: PCs en uso que titilaban "SIN CLIENTE" en Control de PCs y volvían al amarillo sin
que nadie supiera si era la red o el Cliente PC que se cerraba y la tarea volvía a abrir).

Mientras la PC está sin noticias no hay nada que saber: no llega nada. La causa se sabe cuando
VUELVE, con lo que cuenta su Cliente PC en esa consulta (CLIENTE PC/pulso.py, `leer_pulso`):

- `arranque` distinto del de antes del corte: el programa se cerró y se volvió a abrir
  (CLIENTE_REABIERTO); si además Windows lleva prendido menos que el corte, se reinició la PC
  entera (PC_REINICIADA).
- El mismo programa:
  - `sin_ok` mucho más chico que el corte: la PC sí tuvo respuestas en el medio pero el mostrador
    no las anotó (MOSTRADOR: ver los errores del programa).
  - `fallas` > 0: la PC preguntó y no le contestaron (RED: cable, switch, IP repetida, módem).
  - Ni una falla: no preguntó en todo ese rato (CLIENTE_TRABADO: el programa trabado o la PC
    suspendida).
- Un Cliente PC viejo no manda nada de esto: SIN_DATOS.

Límite, para no prometer de más: con el "inicio rápido" de Windows, apagar y prender la PC no
reinicia la cuenta de cuánto lleva prendida, así que eso se ve como CLIENTE_REABIERTO, no como
PC_REINICIADA. Un reinicio (el de siempre al terminar cada cliente) sí se ve como tal.

Solo se anota lo que en la grilla se vio como la alerta "SIN CLIENTE" (`estaba_en_alerta`): una PC
libre que se apaga, o la que espera a que el cliente la prenda, no es un corte. Tampoco la PC
cuyo Cliente PC cerró alguien desde el panel admin: eso ya lo anota accesos_admin_pc_repo
(CLIENTE_REANUDADO). Ni un corte que empezó antes de abrir este programa: con el mostrador
cerrado se quedan sin noticias todas las PCs a la vez, y no es cosa de ninguna.
"""

from datetime import datetime

import dominio
from database import conexion_db

# Cuánto más chico que el corte tiene que ser `sin_ok` para creerle a la PC que tuvo respuesta en
# el medio. En una PC normal los dos son casi iguales; la diferencia la hacen la demora de cada
# consulta y que la hora de la última conexión se guarda sin fracciones de segundo.
MARGEN_SIN_OK_SEGUNDOS = 10

_LARGO_MAXIMO_ARRANQUE = 40
# Un número más grande que esto no es un dato, es un pedido roto (son segundos o consultas).
_MAXIMO_NUMERO = 10 ** 9

# Desde cuándo está abierto este programa (se carga al arrancar, con el servidor de red).
_PROGRAMA_ABIERTO_DESDE = datetime.now()


def _entero(texto):
    try:
        valor = int(texto)
    except (TypeError, ValueError):
        return None
    return valor if 0 <= valor <= _MAXIMO_NUMERO else None


def leer_pulso(parametros: dict) -> dict:
    """
    Lo que mandó el Cliente PC en su GET /estado (ver CLIENTE PC/pulso.py), ya revisado:
    {"arranque", "fallas", "sin_ok", "encendida"}. Lo que falta o no se entiende queda en None:
    un Cliente PC viejo no manda nada de esto.
    """
    arranque = str(parametros.get("arranque") or "").strip()[:_LARGO_MAXIMO_ARRANQUE]
    return {
        "arranque": arranque or None,
        "fallas": _entero(parametros.get("fallas")),
        "sin_ok": _entero(parametros.get("sin_ok")),
        "encendida": _entero(parametros.get("encendida")),
    }


def causa_del_corte(segundos: int, pulso: dict, arranque_anterior) -> str:
    """
    La causa (una de dominio.CAUSAS_CORTE_PC) de un corte de `segundos` sin noticias, con el
    `pulso` (`leer_pulso`) de la consulta con que la PC volvió y el `arranque` que había mandado
    antes del corte (None si el Cliente PC de antes era viejo).
    """
    if pulso["arranque"] is None:
        return dominio.CORTE_SIN_DATOS
    if arranque_anterior is not None:
        reabierto = pulso["arranque"] != arranque_anterior
    else:
        # El de antes no dijo quién era: si este programa todavía no tuvo ni una respuesta,
        # no puede ser el que le habló al mostrador antes del corte.
        reabierto = pulso["sin_ok"] is None
    if reabierto:
        if pulso["encendida"] is not None and pulso["encendida"] < segundos:
            return dominio.CORTE_PC_REINICIADA
        return dominio.CORTE_CLIENTE_REABIERTO
    if pulso["sin_ok"] is not None and pulso["sin_ok"] < segundos - MARGEN_SIN_OK_SEGUNDOS:
        return dominio.CORTE_MOSTRADOR
    if pulso["fallas"]:
        return dominio.CORTE_RED
    return dominio.CORTE_CLIENTE_TRABADO


def estaba_en_alerta(item) -> bool:
    """¿La grilla mostraba esta PC en la alerta "SIN CLIENTE" que titila? `item` es el de
    pcs_repo.estado_de_estacion, leído ANTES de anotar la consulta que acaba de llegar. Fuera
    queda la PC cuyo Cliente PC se cerró desde el panel admin (ver el docstring del módulo)."""
    return (
        item["sesion"] is not None
        and not item["enlazada"]
        and not item["esperando_cliente"]
        and item["cliente_cerrado_admin_desde"] is None
        and item["ultima_conexion"] is not None
    )


def registrar_si_volvio_de_un_corte(item, pulso: dict, ahora: datetime = None,
                                    programa_abierto_desde: datetime = None):
    """
    Se llama en cada GET /estado (servidor_red.py) con el estado de la estación ANTES de anotar
    esa consulta. Si la PC estaba en la alerta "SIN CLIENTE", anota el corte (cuánto duró y por
    qué) y devuelve la causa; si no, devuelve None sin tocar la base, que es lo de siempre.
    `programa_abierto_desde` es para las pruebas.
    """
    if not estaba_en_alerta(item):
        return None
    ahora = ahora or datetime.now()
    if item["ultima_conexion"] < (programa_abierto_desde or _PROGRAMA_ABIERTO_DESDE):
        return None
    segundos = max(0, int((ahora - item["ultima_conexion"]).total_seconds()))
    causa = causa_del_corte(segundos, pulso, item["estacion"]["cliente_arranque"])
    with conexion_db() as conexion:
        conexion.execute(
            """
            INSERT INTO cortes_pc (estacion_id, sesion_id, fecha_hora, segundos, causa, fallas)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (item["estacion"]["id"], item["sesion"]["id"], ahora.isoformat(timespec="seconds"),
             segundos, causa, pulso["fallas"]),
        )
    return causa


def cortes_de_sesiones(conexion, sesion_ids) -> dict:
    """{sesion_id: [cortes de esa sesión, del más viejo al más nuevo]} para las sesiones
    pedidas (las que están en curso, ver pcs_repo.estado_estaciones)."""
    sesion_ids = list(sesion_ids)
    if not sesion_ids:
        return {}
    filas = conexion.execute(
        f"""
        SELECT * FROM cortes_pc WHERE sesion_id IN ({", ".join("?" for _ in sesion_ids)})
        ORDER BY fecha_hora, id
        """,
        sesion_ids,
    ).fetchall()
    cortes = {}
    for fila in filas:
        cortes.setdefault(fila["sesion_id"], []).append(fila)
    return cortes


def listar_recientes(limite: int):
    """Los últimos `limite` cortes, con el nombre de la PC, para el panel de actividad de
    Control de PCs (ver actividad_repo.actividad_reciente)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT cortes_pc.fecha_hora, cortes_pc.segundos, cortes_pc.causa, cortes_pc.fallas,
                   estaciones.nombre AS estacion_nombre
            FROM cortes_pc
            JOIN estaciones ON estaciones.id = cortes_pc.estacion_id
            ORDER BY cortes_pc.fecha_hora DESC, cortes_pc.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
