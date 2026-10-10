"""Feed de actividad de PCs y PlayStation para el panel del mostrador."""

from database import conexion_db
from control_pcs.repositories import accesos_admin_pc_repo, playstation_repo


def actividad_reciente(limite: int = 30):
    """
    Feed de eventos recientes para el panel de actividad de "Control de
    PCs". No existe una tabla de log aparte: esto relee
    sesiones_pc/sesion_bonos/movimientos_saldo_miembro, que ya guardan
    todo esto por otras razones (facturación, auditoría de saldo de
    socios) — acá solo se junta todo, se ordena por fecha y se corta a
    `limite`. Devuelve datos crudos; el texto para mostrar se arma en la
    UI (ver control_pcs/ui/pcs_actividad.py:_texto_evento), no acá. Incluye los
    movimientos de la PlayStation 5.
    """
    eventos = []
    with conexion_db() as conexion:
        for fila in conexion.execute("""
            SELECT s.fecha_inicio AS fecha, e.nombre AS estacion_nombre
            FROM sesiones_pc s JOIN estaciones e ON e.id = s.estacion_id
            ORDER BY s.fecha_inicio DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "INICIO",
                             "estacion_nombre": fila["estacion_nombre"]})

        for fila in conexion.execute("""
            SELECT s.fecha_fin_real AS fecha, e.nombre AS estacion_nombre
            FROM sesiones_pc s JOIN estaciones e ON e.id = s.estacion_id
            WHERE s.fecha_fin_real IS NOT NULL
            ORDER BY s.fecha_fin_real DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "FIN",
                             "estacion_nombre": fila["estacion_nombre"]})

        for fila in conexion.execute("""
            SELECT v.fecha AS fecha, e.nombre AS estacion_nombre,
                   b.nombre AS bono_nombre, sb.precio AS precio
            FROM sesion_bonos sb
            JOIN ventas v ON v.id = sb.venta_id
            JOIN bonos_tiempo b ON b.id = sb.bono_id
            JOIN sesiones_pc s ON s.id = sb.sesion_id
            JOIN estaciones e ON e.id = s.estacion_id
            ORDER BY v.fecha DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "BONO",
                             "estacion_nombre": fila["estacion_nombre"],
                             "bono_nombre": fila["bono_nombre"], "precio": fila["precio"]})

        for fila in conexion.execute("""
            SELECT m.fecha AS fecha, m.tipo AS tipo, m.minutos AS minutos,
                   mi.nombre AS miembro_nombre, e.nombre AS estacion_nombre, v.total AS monto
            FROM movimientos_saldo_miembro m
            JOIN miembros mi ON mi.id = m.miembro_id
            LEFT JOIN sesiones_pc s ON s.id = m.sesion_id
            LEFT JOIN estaciones e ON e.id = s.estacion_id
            LEFT JOIN ventas v ON v.id = m.venta_id
            ORDER BY m.fecha DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": fila["tipo"],
                             "miembro_nombre": fila["miembro_nombre"],
                             "estacion_nombre": fila["estacion_nombre"],
                             "minutos": fila["minutos"], "monto": fila["monto"]})

        # Los eventos de arriba toman el nombre de la estación de
        # sesiones_pc.estacion_id, que es la ACTUAL: si una sesión se pasó
        # de PC (ver trasladar_sesion), su INICIO/BONO se muestran en la PC
        # nueva. Estos eventos TRASLADO dejan a la vista el recorrido.
        for fila in conexion.execute("""
            SELECT t.fecha AS fecha, eo.nombre AS origen_nombre, ed.nombre AS destino_nombre
            FROM traslados_sesion t
            JOIN estaciones eo ON eo.id = t.estacion_origen_id
            JOIN estaciones ed ON ed.id = t.estacion_destino_id
            ORDER BY t.fecha DESC LIMIT ?
        """, (limite,)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "TRASLADO",
                             "origen_nombre": fila["origen_nombre"],
                             "destino_nombre": fila["destino_nombre"]})

        for fila in accesos_admin_pc_repo.listar_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "ADMIN_PC",
                             "evento_admin": fila["tipo"],
                             "estacion_nombre": fila["estacion_nombre"],
                             "segundos_sin_cliente": fila["segundos_sin_cliente"]})

    # La PlayStation 5 comparte el panel con las PCs: sus sesiones y bonos
    # llegan con la misma forma (ver playstation_repo.eventos_recientes).
    eventos.extend(playstation_repo.eventos_recientes(limite))

    eventos.sort(key=lambda evento: evento["fecha"], reverse=True)
    return eventos[:limite]
