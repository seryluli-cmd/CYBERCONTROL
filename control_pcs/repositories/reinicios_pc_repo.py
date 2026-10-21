"""
reinicios_pc_repo.py
====================
Por qué el Cliente PC de una PC la reinició o la apagó (revisión del 2026-10-21:
a un chico se le reinició la PC jugando y no había forma de saber si había sido
el Cliente PC, Windows, un corte de luz o el hardware).

Antes de cada `shutdown`, el Cliente PC anota el motivo en un archivo de su
carpeta (la que no restaura Shadow Defender) y lo manda en su próxima consulta
de GET /estado, antes o después del reinicio (CLIENTE PC/motivo_reinicio.py):
parámetros `reinicio` (uno de dominio.MOTIVOS_REINICIO_PC), `reinicio_marca`,
`reinicio_hace` (segundos: el reloj de cada PC puede estar corrido, así que no
viaja la hora) y `reinicio_quedaban` (lo que le quedaba a la sesión según la PC).

Con eso se ve en "Actividad reciente":
- Cada reinicio que pidió el Cliente PC, menos el de todos los días (el del final
  de cada sesión, que no dice nada nuevo).
- Si un corte "la PC se reinició" lo pidió el Cliente PC o no (`fue_pedido`). Si
  no, fue otra cosa: corte de luz, cuelgue o pantalla azul, Windows Update o
  alguien con el botón. Eso ya no es del programa: se mira en el Visor de eventos
  de esa PC.

Los Cliente PC anteriores a PRIMERA_VERSION_QUE_AVISA no cuentan nada: de esas PCs
no se sabe.
"""

from datetime import datetime, timedelta

import dominio
from database import conexion_db
from control_pcs.repositories.actualizacion_cliente_repo import es_mas_vieja, numero_de_version_valido

# La primera versión del Cliente PC que avisa por qué reinició la PC.
PRIMERA_VERSION_QUE_AVISA = "1.3"
# Un aviso que tarda más que esto en llegar (PC apagada días) no se anota: ya no ayuda a nadie.
MAXIMO_SEGUNDOS_ATRAS = 7 * 24 * 3600
# Una sesión que el mostrador dio por terminada con esto o menos por delante (según la PC) terminó
# por tiempo: es el reinicio de todos los días. Lo que sobra es redondeo y la demora de la consulta.
SEGUNDOS_DE_FIN_NORMAL = 60
# Cuánto antes de que la PC dejara de dar noticias puede haber pedido el reinicio: Windows tarda
# unos segundos en cerrar todo y la PC sigue consultando mientras tanto.
MARGEN_SEGUNDOS = 120


def _entero_no_negativo(valor):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero >= 0 else None


def leer_reinicio(parametros: dict):
    """Lo que mandó el Cliente PC en su GET /estado, ya revisado: {"motivo", "marca", "hace",
    "quedaban"}. None si no mandó nada (lo de siempre, o un Cliente PC viejo) o si algo no se
    entiende."""
    motivo = parametros.get("reinicio")
    if motivo not in dominio.MOTIVOS_REINICIO_PC:
        return None
    marca = _entero_no_negativo(parametros.get("reinicio_marca"))
    hace = _entero_no_negativo(parametros.get("reinicio_hace"))
    if marca is None or hace is None or hace > MAXIMO_SEGUNDOS_ATRAS:
        return None
    return {"motivo": motivo, "marca": marca, "hace": hace,
            "quedaban": _entero_no_negativo(parametros.get("reinicio_quedaban"))}


def registrar(estacion_id: int, reinicio: dict, ahora: datetime = None):
    """Anota el reinicio (`leer_reinicio`). Si el mismo aviso llega dos veces (la respuesta no le
    llegó a la PC y lo volvió a mandar), queda uno solo."""
    ahora = ahora or datetime.now()
    cuando = ahora - timedelta(seconds=reinicio["hace"])
    with conexion_db() as conexion:
        conexion.execute(
            """
            INSERT OR IGNORE INTO reinicios_pc (estacion_id, fecha_hora, motivo, segundos_quedaban, marca)
            VALUES (?, ?, ?, ?, ?)
            """,
            (estacion_id, cuando.isoformat(timespec="seconds"), reinicio["motivo"], reinicio["quedaban"],
             reinicio["marca"]),
        )


def motivo_del_corte(conexion, estacion_id: int, fecha_corte: str, segundos_corte: int, version_cliente):
    """¿Por qué se reinició la PC de un corte (cortes_pc: volvió en `fecha_corte` después de
    `segundos_corte` sin noticias)? El motivo que contó la PC (uno de dominio.MOTIVOS_REINICIO_PC,
    el más nuevo si hay varios), False si no contó ninguno (no lo pidió el Cliente PC ni su
    seguro de fin de sesión) o None si su Cliente PC es anterior a PRIMERA_VERSION_QUE_AVISA:
    no se sabe."""
    version = numero_de_version_valido(version_cliente)
    if version is None or es_mas_vieja(version, PRIMERA_VERSION_QUE_AVISA):
        return None
    volvio = datetime.fromisoformat(fecha_corte)
    desde = volvio - timedelta(seconds=segundos_corte + MARGEN_SEGUNDOS)
    fila = conexion.execute(
        """
        SELECT motivo FROM reinicios_pc WHERE estacion_id = ? AND fecha_hora BETWEEN ? AND ?
        ORDER BY fecha_hora DESC, id DESC LIMIT 1
        """,
        (estacion_id, desde.isoformat(timespec="seconds"), volvio.isoformat(timespec="seconds")),
    ).fetchone()
    return fila["motivo"] if fila is not None else False


def fue_pedido(conexion, estacion_id: int, fecha_corte: str, segundos_corte: int, version_cliente):
    """¿El reinicio de un corte lo pidió el Cliente PC de esa PC (o su seguro de fin de sesión)?
    None si no se sabe (ver motivo_del_corte)."""
    motivo = motivo_del_corte(conexion, estacion_id, fecha_corte, segundos_corte, version_cliente)
    return None if motivo is None else motivo is not False


def listar_recientes(limite: int):
    """Los últimos `limite` reinicios, con el nombre de la PC, para "Actividad reciente" (ver
    actividad_repo.actividad_reciente). Sin el de todos los días: una sesión que terminó por
    tiempo (SEGUNDOS_DE_FIN_NORMAL)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT r.fecha_hora, r.motivo, r.segundos_quedaban, e.nombre AS estacion_nombre
            FROM reinicios_pc r
            JOIN estaciones e ON e.id = r.estacion_id
            WHERE NOT (r.motivo = ? AND COALESCE(r.segundos_quedaban, 0) <= ?)
            ORDER BY r.fecha_hora DESC, r.id DESC
            LIMIT ?
            """,
            (dominio.REINICIO_SESION_TERMINADA, SEGUNDOS_DE_FIN_NORMAL, limite),
        ).fetchall()
