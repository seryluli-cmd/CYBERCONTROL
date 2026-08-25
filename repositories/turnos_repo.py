"""
turnos_repo.py
===============
Lógica de Caja (consulta en vivo) y Cierre de Turno.

Idea central: en vez de calcular los turnos con horarios rígidos (lo cual
se complica porque el turno "NOCHE" cruza la medianoche, y porque a veces
una empleada llega unos minutos tarde), un turno "en curso" es
simplemente: *todo lo vendido desde el último cierre hasta ahora*.
Así, sin importar la hora exacta a la que alguien cierra, nunca se cuenta
una venta dos veces ni se pierde ninguna.
"""

from datetime import datetime
from database import conexion_db, calcular_turno
from repositories.config_repo import obtener_fondo_cambio


def _obtener_ultimo_cierre(conexion):
    return conexion.execute(
        "SELECT * FROM cierres_turno ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _sumar_ventas_por_metodo(conexion, desde: str, hasta: str):
    """
    Devuelve (total_efectivo, total_digital) vendidos entre `desde`
    (exclusivo) y `hasta` (inclusive), considerando solo ventas
    CONFIRMADAS (una venta anulada no debe contar en la caja).
    """
    filas = conexion.execute(
        """
        SELECT venta_pagos.metodo, SUM(venta_pagos.monto) AS total
        FROM venta_pagos
        JOIN ventas ON ventas.id = venta_pagos.venta_id
        WHERE ventas.estado = 'CONFIRMADA'
          AND ventas.fecha > ?
          AND ventas.fecha <= ?
        GROUP BY venta_pagos.metodo
        """,
        (desde, hasta),
    ).fetchall()
    totales = {"EFECTIVO": 0.0, "DIGITAL": 0.0}
    for fila in filas:
        totales[fila["metodo"]] = fila["total"] or 0.0
    return totales["EFECTIVO"], totales["DIGITAL"]


def resumen_turno_actual():
    """
    Para la pantalla "Caja": muestra cómo viene el turno en curso sin
    cerrarlo. Devuelve un diccionario con fondo de cambio, ventas en
    efectivo y digital acumuladas desde el último cierre, y cuánto
    debería haber ahora mismo en el cajón.
    """
    with conexion_db() as conexion:
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        desde = ultimo_cierre["fecha_cierre"] if ultimo_cierre else "0000-01-01T00:00:00"
        ahora = datetime.now().isoformat(timespec="seconds")
        ventas_efectivo, ventas_digital = _sumar_ventas_por_metodo(conexion, desde, ahora)

    fondo_cambio = obtener_fondo_cambio()

    return {
        "turno_actual": calcular_turno(datetime.now()),
        "fondo_cambio": fondo_cambio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_digital": ventas_digital,
        "caja_actual": fondo_cambio + ventas_efectivo,
        "desde": desde,
        "hasta": ahora,
    }


def cerrar_turno(usuario_id: int):
    """
    Cierra el turno en curso: calcula lo mismo que `resumen_turno_actual`
    y lo deja grabado en `cierres_turno`, listo para que la empleada
    sepa cuánto retirar (dejando el fondo de cambio en el cajón para el
    próximo turno). Devuelve el resumen guardado.
    """
    fondo_cambio = obtener_fondo_cambio()

    with conexion_db() as conexion:
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        desde = ultimo_cierre["fecha_cierre"] if ultimo_cierre else "0000-01-01T00:00:00"
        ahora_dt = datetime.now()
        ahora = ahora_dt.isoformat(timespec="seconds")

        ventas_efectivo, ventas_digital = _sumar_ventas_por_metodo(conexion, desde, ahora)
        monto_a_retirar = ventas_efectivo

        # El turno que queda etiquetado en el cierre es el que empezó
        # justo después del cierre anterior — es decir, el turno que
        # efectivamente se está cerrando — y no el que esté vigente en
        # este preciso instante. Si no se hiciera así, una empleada que
        # cierra unos minutos tarde (ya entrada la hora del turno
        # siguiente) dejaría el cierre mal etiquetado con el turno
        # equivocado, aunque los montos en sí siempre fueron correctos.
        inicio_del_turno = datetime.fromisoformat(desde) if ultimo_cierre else ahora_dt
        turno = calcular_turno(inicio_del_turno)

        cursor = conexion.execute(
            """
            INSERT INTO cierres_turno
                (fecha, turno, usuario_id, fecha_cierre, fondo_cambio,
                 ventas_efectivo, ventas_digital, monto_a_retirar)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                ahora_dt.date().isoformat(),
                turno,
                usuario_id,
                ahora,
                fondo_cambio,
                ventas_efectivo,
                ventas_digital,
                monto_a_retirar,
            ),
        )
        cierre_id = cursor.lastrowid

    return {
        "id": cierre_id,
        "fondo_cambio": fondo_cambio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_digital": ventas_digital,
        "monto_a_retirar": monto_a_retirar,
    }


def listar_cierres(limite: int = 100):
    """Historial de cierres, para que el Admin controle turno por turno
    (y cargue el monto que contó en cada sobre)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT cierres_turno.*, usuarios.nombre AS empleada,
                   verificadores.nombre AS verificado_por_nombre
            FROM cierres_turno
            JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
            LEFT JOIN usuarios AS verificadores ON verificadores.id = cierres_turno.verificado_por
            ORDER BY cierres_turno.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()


def verificar_cierre(cierre_id: int, monto_contado: float, usuario_admin_id: int):
    """
    El Admin carga cuánta plata contó realmente en el sobre de un cierre
    puntual. Se calcula la diferencia contra lo esperado (monto_a_retirar)
    para detectar faltantes o sobrantes por empleada/turno.
    """
    with conexion_db() as conexion:
        cierre = conexion.execute(
            "SELECT * FROM cierres_turno WHERE id = ?", (cierre_id,)
        ).fetchone()
        if cierre is None:
            raise ValueError("El cierre no existe.")

        monto_contado = round(monto_contado, 2)
        diferencia = round(monto_contado - cierre["monto_a_retirar"], 2)
        ahora = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """
            UPDATE cierres_turno
            SET monto_contado = ?, diferencia = ?, verificado_por = ?, fecha_verificacion = ?
            WHERE id = ?
            """,
            (monto_contado, diferencia, usuario_admin_id, ahora, cierre_id),
        )
