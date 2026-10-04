"""
accesos_admin_pc_repo.py
===========================
Registro de lo que pasa en el panel admin de cada Cliente PC (la "A"
chica de la pantalla de bloqueo, ver CLIENTE PC/cliente_pc.py).

Por qué existe: quien sabe la contraseña admin puede cerrar el Cliente PC
y dejar esa PC SIN bloqueo -- queda usable por cualquiera, gratis, hasta
que el Cliente PC vuelva a arrancar. Es lo que hace un empleado de
mantenimiento a propósito para trabajar en una PC, pero también es la
forma de dejarla abierta horas para jugar. El dueño quería enterarse
cuándo pasa y cuánto dura, así que el Cliente PC avisa tres cosas
(`POST /evento_admin`, ver servidor_red.py): entró al panel, cerró el
Cliente PC, o abrió la reconfiguración. La contraseña admin es una sola
para todos, así que esto dice QUÉ PC y CUÁNDO, no QUIÉN.

El cuarto evento, CLIENTE_REANUDADO, lo anota el servidor solo: la
primera vez que una PC que había quedado sin Cliente PC vuelve a preguntar
su estado (`registrar_regreso_del_cliente`). Con eso se sabe cuánto estuvo
la PC sin bloqueo -- ojo, hasta que el Cliente PC volvió: si la apagaron
en el medio, ese tiempo incluye el que estuvo apagada, el servidor no tiene
forma de distinguirlo.
"""

from datetime import datetime, timedelta

import dominio
from database import conexion_db

# Un Cliente PC que no pudo avisar en el momento (servidor apagado) lo
# anota localmente y lo manda cuando vuelve la conexión, diciendo "esto
# pasó hace X segundos" (no manda su hora: el reloj de cada PC puede estar
# corrido). Más de esto no se le cree: sería un archivo roto, no un aviso.
MAXIMO_SEGUNDOS_ATRAS = 30 * 24 * 3600


def registrar_evento(estacion_id: int, tipo: str, segundos_atras: float = 0):
    """
    Anota un evento que el Cliente PC de `estacion_id` reportó. `tipo` tiene
    que ser uno de dominio.EVENTOS_ADMIN_REPORTADOS_POR_CLIENTE (el
    CLIENTE_REANUDADO lo pone el servidor, no se acepta desde afuera).
    `segundos_atras` es hace cuánto pasó realmente, para los avisos que
    quedaron demorados.

    Si el evento deja la PC sin Cliente PC (cerrarlo, o reconfigurar, que
    también lo cierra), además marca `estaciones.cliente_cerrado_desde`:
    es lo que usa la grilla de Control de PCs para mostrar esa PC como
    "sin bloqueo" y cuánto lleva así.
    """
    if tipo not in dominio.EVENTOS_ADMIN_REPORTADOS_POR_CLIENTE:
        raise ValueError(f"Tipo de evento admin inválido: {tipo!r}.")
    segundos_atras = min(max(float(segundos_atras or 0), 0.0), MAXIMO_SEGUNDOS_ATRAS)
    fecha = (datetime.now() - timedelta(seconds=segundos_atras)).isoformat(timespec="seconds")

    with conexion_db() as conexion:
        conexion.execute(
            "INSERT INTO eventos_admin_pc (estacion_id, fecha_hora, tipo) VALUES (?, ?, ?)",
            (estacion_id, fecha, tipo),
        )
        if tipo in dominio.EVENTOS_ADMIN_QUE_DEJAN_PC_SIN_CLIENTE:
            # El "<" evita que un aviso viejo, que llegó tarde, pise a uno
            # más nuevo que ya se registró.
            conexion.execute(
                """
                UPDATE estaciones SET cliente_cerrado_desde = ?
                WHERE id = ? AND (cliente_cerrado_desde IS NULL OR cliente_cerrado_desde < ?)
                """,
                (fecha, estacion_id, fecha),
            )


def registrar_regreso_del_cliente(estacion_id: int) -> bool:
    """
    La PC volvió a preguntar su estado: si estaba marcada como sin Cliente
    PC, anota CLIENTE_REANUDADO con cuánto estuvo así y limpia la marca.
    Devuelve True si anotó algo. Se llama desde servidor_red.py en cada
    GET /estado solo cuando la estación tiene la marca, así que en el uso
    normal no cuesta nada.

    El UPDATE condicionado al valor leído hace de "compare and set": si dos
    pedidos llegaran a la vez, solo uno ve la marca y anota el evento.
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT cliente_cerrado_desde FROM estaciones WHERE id = ?", (estacion_id,)
        ).fetchone()
        if fila is None or fila["cliente_cerrado_desde"] is None:
            return False
        desde = fila["cliente_cerrado_desde"]
        ahora = datetime.now()
        segundos = max(0, int((ahora - datetime.fromisoformat(desde)).total_seconds()))

        cursor = conexion.execute(
            "UPDATE estaciones SET cliente_cerrado_desde = NULL WHERE id = ? AND cliente_cerrado_desde = ?",
            (estacion_id, desde),
        )
        if cursor.rowcount != 1:
            return False
        conexion.execute(
            """
            INSERT INTO eventos_admin_pc (estacion_id, fecha_hora, tipo, segundos_sin_cliente)
            VALUES (?, ?, ?, ?)
            """,
            (estacion_id, ahora.isoformat(timespec="seconds"), dominio.EVENTO_ADMIN_CLIENTE_REANUDADO, segundos),
        )
        return True


def limpiar_marca_sin_cliente(estacion_id: int):
    """
    Saca la marca "sin Cliente PC desde..." de una estación SIN anotar
    ningún evento ni dejar advertencias: la PC deja de mostrarse como "sin
    bloqueo (cerrado por admin)" y, cuando vuelva a prenderse, tampoco se
    anota un CLIENTE_REANUDADO (registrar_regreso_del_cliente no encuentra
    marca). Se usa cuando el Operador apaga la PC desde CYBERCONTROL
    (ver comandos_pc_repo.encolar_comando): apagarla es el final normal de
    ese episodio, no algo para avisar. El historial de lo que pasó antes
    (ACCESO, CIERRE_CLIENTE) queda como estaba.
    """
    with conexion_db() as conexion:
        conexion.execute("UPDATE estaciones SET cliente_cerrado_desde = NULL WHERE id = ?", (estacion_id,))


def listar_eventos(desde: str, hasta: str):
    """Los eventos entre dos fechas (incluidas ambas puntas, "YYYY-MM-DD"),
    del más nuevo al más viejo, con el nombre de la PC."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT eventos_admin_pc.fecha_hora, eventos_admin_pc.tipo,
                   eventos_admin_pc.segundos_sin_cliente, estaciones.nombre AS estacion_nombre
            FROM eventos_admin_pc
            JOIN estaciones ON estaciones.id = eventos_admin_pc.estacion_id
            WHERE date(eventos_admin_pc.fecha_hora) BETWEEN date(?) AND date(?)
            ORDER BY eventos_admin_pc.fecha_hora DESC, eventos_admin_pc.id DESC
            """,
            (desde, hasta),
        ).fetchall()


def listar_recientes(limite: int):
    """Los últimos `limite` eventos, para el panel de actividad de Control
    de PCs (ver pcs_repo.actividad_reciente)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT eventos_admin_pc.fecha_hora, eventos_admin_pc.tipo,
                   eventos_admin_pc.segundos_sin_cliente, estaciones.nombre AS estacion_nombre
            FROM eventos_admin_pc
            JOIN estaciones ON estaciones.id = eventos_admin_pc.estacion_id
            ORDER BY eventos_admin_pc.fecha_hora DESC, eventos_admin_pc.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
