"""Feed de actividad de PCs y PlayStation para el panel del mostrador."""

import dominio
from database import conexion_db
from control_pcs.repositories import (
    accesos_admin_pc_repo, avisos_fin_pc_repo, cortes_pc_repo, filtro_palabras_repo, playstation_repo,
    reconexion_repo, reinicios_pc_repo,
)


def actividad_reciente(limite: int = 30):
    """
    Feed de eventos recientes para el panel de actividad de "Control de
    PCs". No existe una tabla de log aparte: esto relee
    sesiones_pc/sesion_bonos/sesion_pcstream_bonos/movimientos_saldo_miembro, que ya guardan
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

        # Los bonos comunes y los de PCSTREAM viven en tablas distintas (ver
        # pcstream_repo), pero en el panel son el mismo evento: "se vendió un bono".
        # Menos el de una reserva: se anota con la venta del día que se reservó (que
        # pudo ser solo una seña), y sale abajo como "reserva habilitada".
        # Los últimos bonos son los de número de venta más alto (se numeran a
        # medida que se venden): ordenar por `venta_id`, con su índice, lee solo
        # esos. Ordenar por `ventas.fecha` obligaba a recorrer y ordenar todos los
        # bonos de la historia en cada refresco (ver database_esquema, ÍNDICES).
        for tabla_vinculo, tabla_bonos in (("sesion_bonos", "bonos_tiempo"),
                                           ("sesion_pcstream_bonos", "bonos_pcstream")):
            for fila in conexion.execute(f"""
                SELECT v.fecha AS fecha, e.nombre AS estacion_nombre,
                       b.nombre AS bono_nombre, sb.precio AS precio
                FROM {tabla_vinculo} sb
                JOIN ventas v ON v.id = sb.venta_id
                JOIN {tabla_bonos} b ON b.id = sb.bono_id
                JOIN sesiones_pc s ON s.id = sb.sesion_id
                JOIN estaciones e ON e.id = s.estacion_id
                WHERE NOT EXISTS (SELECT 1 FROM reservas_pagos rp WHERE rp.venta_id = sb.venta_id)
                ORDER BY sb.venta_id DESC LIMIT ?
            """, (limite,)).fetchall():
                eventos.append({"fecha": fila["fecha"], "tipo": "BONO",
                                 "estacion_nombre": fila["estacion_nombre"],
                                 "bono_nombre": fila["bono_nombre"], "precio": fila["precio"]})

        # Sin el tiempo traído del programa anterior (ver
        # dominio.MOVIMIENTO_IMPORTACION): no pasó en ninguna PC, y los 45
        # socios importados de una vez tapaban todo lo demás del panel.
        for fila in conexion.execute("""
            SELECT m.fecha AS fecha, m.tipo AS tipo, m.minutos AS minutos,
                   mi.nombre AS miembro_nombre, e.nombre AS estacion_nombre, v.total AS monto
            FROM movimientos_saldo_miembro m
            JOIN miembros mi ON mi.id = m.miembro_id
            LEFT JOIN sesiones_pc s ON s.id = m.sesion_id
            LEFT JOIN estaciones e ON e.id = s.estacion_id
            LEFT JOIN ventas v ON v.id = m.venta_id
            WHERE m.tipo <> ?
            ORDER BY m.fecha DESC LIMIT ?
        """, (dominio.MOVIMIENTO_IMPORTACION, limite)).fetchall():
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

        for fila in filtro_palabras_repo.listar_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "FILTRO",
                             "estacion_nombre": fila["estacion_nombre"],
                             "palabra": fila["palabra"], "titulo": fila["titulo"]})

        # PCs en uso que titilaron "SIN CLIENTE" y volvieron solas, con la causa.
        for fila in cortes_pc_repo.listar_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "CORTE",
                             "estacion_nombre": fila["estacion_nombre"],
                             "segundos": fila["segundos"], "causa": fila["causa"],
                             "fallas": fila["fallas"], "reinicio_pedido": fila["reinicio_pedido"],
                             "reinicio_por_seguro": fila["reinicio_por_seguro"],
                             "despues_del_fin": fila["despues_del_fin"]})

        # PCs que no se enteraron de que terminó su sesión y que un operador dio por
        # revisadas (avisos_fin_pc_repo): quién apagó la alerta.
        for fila in avisos_fin_pc_repo.listar_revisadas_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "FIN_REVISADO",
                             "estacion_nombre": fila["estacion_nombre"], "fin": fila["fecha_fin_real"],
                             "usuario_nombre": fila["usuario_nombre"]})

        # Las PCs que reinició (o apagó) su propio Cliente PC, con el motivo (ver
        # reinicios_pc_repo). Sin el de todos los días: el del final de cada sesión.
        for fila in reinicios_pc_repo.listar_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "REINICIO",
                             "estacion_nombre": fila["estacion_nombre"], "motivo": fila["motivo"],
                             "segundos_quedaban": fila["segundos_quedaban"]})

        # PCs que volvieron de un corte con menos tiempo que el del mostrador: se tomó
        # el de la PC (ver reconexion_repo).
        for fila in reconexion_repo.listar_recientes(limite):
            eventos.append({"fecha": fila["fecha_hora"], "tipo": "AJUSTE_TIEMPO",
                             "estacion_nombre": fila["estacion_nombre"],
                             "segundos_mostrador": fila["segundos_mostrador"],
                             "segundos_pc": fila["segundos_pc"]})

        # Las reservas que se habilitaron (reservas_repo), en la PC donde se usaron o
        # en la consola. Con su índice (estado, estado_desde): lee solo las últimas.
        for fila in conexion.execute("""
            SELECT r.estado_desde AS fecha, r.id AS numero, r.cliente AS cliente, r.bono_nombre AS bono_nombre,
                   CASE WHEN r.sesion_playstation_id IS NOT NULL THEN ? ELSE e.nombre END AS estacion_nombre
            FROM reservas r
            LEFT JOIN estaciones e ON e.id = r.estacion_habilitada_id
            WHERE r.estado = ?
            ORDER BY r.estado_desde DESC LIMIT ?
        """, (dominio.NOMBRE_PLAYSTATION, dominio.RESERVA_HABILITADA, limite)).fetchall():
            eventos.append({"fecha": fila["fecha"], "tipo": "RESERVA", "estacion_nombre": fila["estacion_nombre"],
                            "numero": fila["numero"], "cliente": fila["cliente"],
                            "bono_nombre": fila["bono_nombre"]})

    # La PlayStation 5 comparte el panel con las PCs: sus sesiones y bonos
    # llegan con la misma forma (ver playstation_repo.eventos_recientes).
    eventos.extend(playstation_repo.eventos_recientes(limite))

    eventos.sort(key=lambda evento: evento["fecha"], reverse=True)
    return eventos[:limite]
