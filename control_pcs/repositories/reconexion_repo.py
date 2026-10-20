"""
reconexion_repo.py
====================
Al volver la conexión entre el mostrador y una PC, gana el tiempo MENOR (pedido
del dueño, 2026-10-20; la PC ya lo hacía desde el 2026-09-30, pero solo por un
instante y sin avisarle al mostrador). La explicación para el dueño está en
docs/TIEMPO_DE_LAS_PCS.md.

Mientras una PC no puede hablar con el mostrador (mostrador apagado o cerrado,
cable, red), su Cliente PC sigue descontando el tiempo solo. El mostrador
también: guarda la hora en que termina cada sesión
(`sesiones_pc.fecha_fin_prevista`), no "cuánto le queda", así que su cuenta no
se frena aunque esté apagado. Normalmente los dos dan igual. Pueden dar
distinto si la hora de la PC del mostrador cambió en el medio: ahí el
mostrador le daría tiempo de más al cliente.

Por eso, después de un corte, la PC cuenta en cada consulta lo que le queda
según su cuenta (`leer_tiempo_de_la_pc`: parámetros `sesion`, `resto` y `desde`
de GET /estado, ver CLIENTE PC/red_kiosko.py) y, con la primera que llega,
`tomar_el_menor` decide:

- Solo se compara la MISMA sesión que la PC venía contando: si en el medio se
  cerró, se pasó a otra PC o se abrió otra, no hay nada que comparar.
- Lo que se le cargó a esa sesión DURANTE el corte (un bono vendido en el
  mostrador, el saldo de un socio) la PC no lo sabía: se le suma a su cuenta
  antes de comparar. Así se compara el tiempo USADO y nunca se le borra al
  cliente lo que pagó.
- Si la cuenta de la PC es menor por más de `TOLERANCIA_SEGUNDOS`, el mostrador
  corre el fin de la sesión para que le quede eso, y lo anota en
  `ajustes_reconexion_pc` (se ve en "Actividad reciente"). Unos segundos de
  diferencia son del redondeo de cada consulta y no se tocan.
- Nunca SUBE el tiempo: la PC solo puede bajarlo. Tocar la PC no regala nada.

Una PC que se reinició porque se le terminó el tiempo durante el corte manda
`resto=0` al volver (lo dejó anotado antes de reiniciarse): entra por el mismo
camino y, si el mostrador creía que todavía le quedaba, la sesión termina ahí.
"""

from datetime import datetime, timedelta

import dominio
from database import conexion_db
from control_pcs.repositories.reintegros_repo import contribuciones_de_sesion

# Diferencias de hasta esto son del redondeo de cada consulta (la PC cuenta desde
# la última respuesta, el mostrador redondea a segundos): no se tocan.
TOLERANCIA_SEGUNDOS = 30
# Un bono vendido justo antes de la última respuesta que le llegó a la PC puede
# estar o no en su cuenta: se lo toma como cargado durante el corte. La duda
# favorece al cliente (su cuenta parece más larga y se le baja menos), nunca al revés.
MARGEN_SEGUNDOS = 15


def _entero_no_negativo(valor):
    try:
        numero = int(valor)
    except (TypeError, ValueError):
        return None
    return numero if numero >= 0 else None


def leer_tiempo_de_la_pc(parametros: dict):
    """
    Lo que manda el Cliente PC en su GET /estado después de un corte, ya revisado:
    {"sesion_id", "segundos" (lo que le queda según su cuenta), "desde" (hace
    cuántos segundos le contestó el mostrador por última vez)}. None si no lo
    mandó (sin corte, o un Cliente PC viejo) o si falta o no se entiende algo.
    """
    sesion_id = _entero_no_negativo(parametros.get("sesion"))
    segundos = _entero_no_negativo(parametros.get("resto"))
    desde = _entero_no_negativo(parametros.get("desde"))
    if sesion_id is None or segundos is None or desde is None:
        return None
    return {"sesion_id": sesion_id, "segundos": segundos, "desde": desde}


def tomar_el_menor(estacion_id: int, tiempo_pc: dict, ahora: datetime = None):
    """
    Si la PC volvió de un corte con menos tiempo que el mostrador (ver el
    comentario del módulo), baja el del mostrador a lo que dice la PC y lo anota.
    `tiempo_pc` es lo de `leer_tiempo_de_la_pc`. Devuelve lo que se anotó
    ({"segundos_mostrador", "segundos_pc", "minutos_cargados", "fin_antes",
    "fin_despues"}) o None si no tocó nada.

    Con "BEGIN IMMEDIATE": un bono que se vende en el mismo instante espera, y
    se suma al fin ya corregido.
    """
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        sesion = conexion.execute(
            "SELECT * FROM sesiones_pc WHERE id = ? AND estacion_id = ? AND estado = ?",
            (tiempo_pc["sesion_id"], estacion_id, dominio.SESION_ACTIVA),
        ).fetchone()
        if sesion is None:
            return None
        fin_antes = datetime.fromisoformat(sesion["fecha_fin_prevista"])
        segundos_mostrador = dominio.segundos_restantes(fin_antes, ahora)

        ultima_respuesta = ahora - timedelta(seconds=tiempo_pc["desde"] + MARGEN_SEGUNDOS)
        minutos_cargados = sum(
            aporte["minutos"] for aporte in contribuciones_de_sesion(conexion, sesion["id"])
            if datetime.fromisoformat(aporte["fecha"]) >= ultima_respuesta
        )
        segundos_pc = tiempo_pc["segundos"] + minutos_cargados * 60
        if segundos_mostrador - segundos_pc <= TOLERANCIA_SEGUNDOS:
            return None

        fin_despues = ahora + timedelta(seconds=segundos_pc)
        ajuste = {
            "segundos_mostrador": segundos_mostrador,
            "segundos_pc": segundos_pc,
            "minutos_cargados": minutos_cargados,
            "fin_antes": sesion["fecha_fin_prevista"],
            "fin_despues": fin_despues.isoformat(timespec="seconds"),
        }
        conexion.execute(
            "UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
            (ajuste["fin_despues"], sesion["id"]),
        )
        conexion.execute(
            """
            INSERT INTO ajustes_reconexion_pc
                (estacion_id, sesion_id, fecha_hora, segundos_mostrador, segundos_pc,
                 minutos_cargados, fin_antes, fin_despues)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (estacion_id, sesion["id"], ahora.isoformat(timespec="seconds"), segundos_mostrador,
             segundos_pc, minutos_cargados, ajuste["fin_antes"], ajuste["fin_despues"]),
        )
    return ajuste


def listar_recientes(limite: int):
    """Los últimos `limite` ajustes, con el nombre de la PC, para "Actividad
    reciente" de Control de PCs (ver actividad_repo.actividad_reciente)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT a.fecha_hora, a.segundos_mostrador, a.segundos_pc, e.nombre AS estacion_nombre
            FROM ajustes_reconexion_pc a
            JOIN estaciones e ON e.id = a.estacion_id
            ORDER BY a.fecha_hora DESC, a.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
