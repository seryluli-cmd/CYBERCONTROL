"""
anular_bono_repo.py
===================
Quitar un bono vendido DE MÁS en una PC o en la consola (pedido del dueño,
2026-11-02: le cargó dos bonos de 5 h a un cliente por error). El Administrador lo
anula y se corrigen las dos cosas juntas: la plata (la venta queda ANULADA, sale de
la caja y de los reportes) y el tiempo (se le saca a la sesión que lo recibió).

Es el hermano de miembros_repo.anular_carga, que hace lo mismo con el saldo de un
socio. Anular solo la venta (ventas_repo.anular_venta) le sacaba la plata a la
caja pero le dejaba el tiempo al cliente, como regalado; y finalizar la sesión lo
dejaba sin el bono que SÍ pagó. Por eso Consulta de Ventas y el botón "Quitar un
bono" del panel de la PC pasan por acá.

Un bono es de uno de tres catálogos, cada uno con su tabla de vínculo con la sesión
(ver database_esquema): el común de las PCs (sesion_bonos), el de PCSTREAM
(sesion_pcstream_bonos) y el de la PlayStation 5 (sesion_playstation_bonos). Los de
las PCs y PCSTREAM extienden una fila de sesiones_pc; los de la consola, una de
sesiones_playstation: las dos tienen `fecha_fin_prevista`, que es lo que se acorta.
"""

from datetime import datetime, timedelta

import dominio
from database import conexion_db
from repositories import ventas_repo

# (vínculo con la sesión, catálogo de bonos, tabla de sesiones)
_BONOS = (
    ("sesion_bonos", "bonos_tiempo", "sesiones_pc"),
    ("sesion_pcstream_bonos", "bonos_pcstream", "sesiones_pc"),
    ("sesion_playstation_bonos", "bonos_playstation", "sesiones_playstation"),
)


def _consulta(vinculo: str, catalogo: str, sesiones: str, donde: str):
    """(SQL, parámetros que van antes del `?` de `donde`) para traer un bono con su venta,
    su sesión y el nombre de la PC (o de la consola)."""
    es_consola = sesiones == "sesiones_playstation"
    sql = f"""
        SELECT sb.venta_id, sb.sesion_id, sb.minutos, b.nombre AS bono,
               v.total AS monto, v.estado AS estado_venta, v.fecha AS fecha_venta,
               s.estado AS estado_sesion, s.fecha_fin_prevista,
               {"?" if es_consola else "e.nombre"} AS estacion,
               EXISTS (SELECT 1 FROM reservas_pagos rp WHERE rp.venta_id = sb.venta_id) AS de_reserva
        FROM {vinculo} sb
        JOIN ventas v ON v.id = sb.venta_id
        JOIN {catalogo} b ON b.id = sb.bono_id
        JOIN {sesiones} s ON s.id = sb.sesion_id
        {"" if es_consola else "JOIN estaciones e ON e.id = s.estacion_id"}
        WHERE {donde}
    """
    return sql, ((dominio.NOMBRE_PLAYSTATION,) if es_consola else ())


def _buscar(conexion, venta_id: int):
    """El bono que vendió esa venta, con `sesiones` (la tabla donde está su sesión);
    None si la venta no vendió ningún bono."""
    for vinculo, catalogo, sesiones in _BONOS:
        sql, antes = _consulta(vinculo, catalogo, sesiones, "sb.venta_id = ?")
        fila = conexion.execute(sql, (*antes, venta_id)).fetchone()
        if fila is not None:
            return dict(fila, sesiones=sesiones)
    return None


def _minutos_que_le_quedan(fila, ahora: datetime) -> int:
    """Los minutos enteros que le quedan a la sesión del bono (0 si ya se cerró o se acabó)."""
    if fila["estado_sesion"] != dominio.SESION_ACTIVA:
        return 0
    fin = datetime.fromisoformat(fila["fecha_fin_prevista"])
    return dominio.segundos_restantes(fin, ahora) // 60


def resumen_de_bono(venta_id: int):
    """
    Lo que hay que saber ANTES de quitar el bono que vendió esa venta, para armar el
    cartel de confirmación. None si la venta no vendió un bono de PC ni de la
    consola (un artículo, una carga de saldo...). Solo lee. Devuelve:

    - bono (el nombre), minutos, monto y `anulada` si la venta ya lo estaba;
    - estacion: la PC (o la consola) donde está su sesión;
    - minutos_en_la_pc: lo que le queda a esa sesión AHORA, o 0 si ya se cerró o se
      acabó (entonces solo se puede anular la plata);
    - de_reserva: el bono salió de una reserva (se anota con la venta de la seña):
      esas no se anulan desde acá.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        fila = _buscar(conexion, venta_id)
    if fila is None:
        return None
    return {
        "venta_id": venta_id,
        "bono": fila["bono"],
        "minutos": fila["minutos"],
        "monto": fila["monto"],
        "anulada": fila["estado_venta"] == dominio.VENTA_ANULADA,
        "estacion": fila["estacion"],
        "minutos_en_la_pc": _minutos_que_le_quedan(fila, ahora),
        "de_reserva": bool(fila["de_reserva"]),
    }


def bonos_de_la_sesion(estacion_id: int = None) -> list:
    """
    Los bonos que vendió la sesión EN CURSO de una PC (o de la consola, con
    `estacion_id=None`) y que siguen valiendo -- los que el Administrador puede
    quitar desde el panel de la PC --, el más nuevo primero. Cada uno:
    {"venta_id", "bono", "minutos", "monto", "fecha"}. Sin los de una reserva. Vacía
    si no tiene sesión.
    """
    bonos = []
    with conexion_db() as conexion:
        for vinculo, catalogo, sesiones in _BONOS:
            if (sesiones == "sesiones_playstation") != (estacion_id is None):
                continue
            sql, antes = _consulta(vinculo, catalogo, sesiones, "s.estado = ? AND v.estado = ?")
            parametros = [*antes, dominio.SESION_ACTIVA, dominio.VENTA_CONFIRMADA]
            if estacion_id is not None:
                sql += " AND s.estacion_id = ?"
                parametros.append(estacion_id)
            for fila in conexion.execute(sql, parametros):
                if not fila["de_reserva"]:
                    bonos.append({"venta_id": fila["venta_id"], "bono": fila["bono"], "minutos": fila["minutos"],
                                  "monto": fila["monto"], "fecha": fila["fecha_venta"]})
    return sorted(bonos, key=lambda bono: bono["venta_id"], reverse=True)


def anular_bono(venta_id: int, usuario_admin_id: int, motivo: str):
    """
    Anula la venta de un bono de PC o de la consola y le saca a su sesión el tiempo
    que le había sumado, en la MISMA transacción: o se hacen las dos cosas o ninguna.
    Solo un Administrador activo y con motivo (ventas_repo.exigir_admin_y_motivo_para_anular).
    La venta no se borra: queda quién la anuló, cuándo y por qué.

    El tiempo se saca del FINAL de la sesión, que es donde cae el último bono sumado
    (da igual cuál de los dos repetidos se anule), sin cortarla ni dejarla por debajo
    de ahora -- como cuentas_pc_repo.quitar_renglon: el cliente sigue jugando con lo
    que le toca. Si ya usó parte del tiempo, solo se saca lo que le queda, y se
    dice. Si la sesión ya se cerró (finalizaron la PC, o se acabó), solo se anula la
    plata. Un bono de una reserva no se anula acá (ValueError).

    Un bono que se anotó en la Cuenta de la PC y todavía no se cobró se saca de la
    cuenta (cuentas_pc_repo.quitar_renglon); a este camino llega recién cuando se cobró.

    Devuelve {"minutos": los del bono, "sacados": los que se le sacaron a la sesión,
    "sin_sacar": los que ya no estaban, "estacion": la PC o la consola}.
    """
    motivo = ventas_repo.exigir_admin_y_motivo_para_anular(usuario_admin_id, motivo)
    with conexion_db() as conexion:
        # El lock de escritura de entrada: el cliente no puede cerrar la PC entre que se
        # lee su sesión y se la acorta.
        conexion.execute("BEGIN IMMEDIATE")
        fila = _buscar(conexion, venta_id)
        if fila is None:
            raise ValueError("Esa venta no vendió ningún bono de PC ni de la consola.")
        if fila["de_reserva"]:
            raise ValueError("Ese bono salió de una reserva: se deshace desde Reservas, no desde acá.")
        ventas_repo._anular_venta(conexion, venta_id, usuario_admin_id, motivo)

        ahora = datetime.now()
        sacados = min(fila["minutos"], _minutos_que_le_quedan(fila, ahora))
        if sacados > 0:
            fin = datetime.fromisoformat(fila["fecha_fin_prevista"])
            conexion.execute(
                f"UPDATE {fila['sesiones']} SET fecha_fin_prevista = ? WHERE id = ?",
                ((fin - timedelta(minutes=sacados)).isoformat(timespec="seconds"), fila["sesion_id"]),
            )
    return {"minutos": fila["minutos"], "sacados": sacados, "sin_sacar": fila["minutos"] - sacados,
            "estacion": fila["estacion"]}
