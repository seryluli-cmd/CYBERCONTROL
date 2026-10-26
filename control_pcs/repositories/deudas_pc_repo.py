"""
deudas_pc_repo.py
===================
Cuánto debe cada PC por su Cuenta de la PC (ver cuentas_pc_repo): lo que
`pcs_repo.estado_estaciones` le pone a cada PC en `item["deuda"]` para que el
mosaico la haga titilar en fucsia y el panel muestre el botón de cobrar.

Vive aparte de cuentas_pc_repo porque esa usa pcs_repo (para sumarle el tiempo
de un bono a la sesión) y pcs_repo usa esto: así no se importan entre ellos.
Corre en cada refresco de la pantalla de PCs (cada 5 s): solo mira las cuentas
ABIERTAS, que son pocas (índice idx_cuentas_pc_estado).

También lo fiado en la ventana de un turno (`fiado_del_turno`): lo que tiene que
cobrarse antes de cerrarlo y, si no, queda en el cierre (`anotar_fiado_en_el_cierre`,
lo llama turnos_repo.cerrar_turno en su transacción; pedido del dueño 2026-10-25).
"""

import dominio


def por_estacion(conexion) -> dict:
    """
    {estacion_id: {"total", "cuentas": [{"id", "sesion_id", "nombre", "total"}]}}
    con lo que se debe en cada PC: las cuentas abiertas de las sesiones que
    están (o terminaron) en ella. Un renglón quitado no cuenta, y una cuenta a
    la que le quitaron todo no aparece (no se debe nada).
    """
    filas = conexion.execute(
        """
        SELECT cuentas_pc.id, cuentas_pc.sesion_id, cuentas_pc.nombre, sesiones_pc.estacion_id,
               SUM(cuenta_pc_items.subtotal) AS total
        FROM cuentas_pc
        JOIN sesiones_pc ON sesiones_pc.id = cuentas_pc.sesion_id
        JOIN cuenta_pc_items ON cuenta_pc_items.cuenta_id = cuentas_pc.id
                            AND cuenta_pc_items.quitado_fecha IS NULL
        WHERE cuentas_pc.estado = ?
        GROUP BY cuentas_pc.id
        HAVING total > 0
        ORDER BY cuentas_pc.id
        """,
        (dominio.CUENTA_ABIERTA,),
    ).fetchall()
    deudas = {}
    for fila in filas:
        deuda = deudas.setdefault(fila["estacion_id"], {"total": 0.0, "cuentas": []})
        deuda["cuentas"].append({
            "id": fila["id"], "sesion_id": fila["sesion_id"], "nombre": fila["nombre"],
            "total": round(fila["total"], 2),
        })
        deuda["total"] = round(deuda["total"] + fila["total"], 2)
    return deudas


def fiado_del_turno(conexion, desde: str, hasta: str = None) -> list:
    """
    Las cuentas abiertas con algo anotado en la ventana del turno (desde, hasta]
    (la de turnos_repo: desde el último cierre) que todavía no se cobró. Cada una
    con {"cuenta_id", "estacion_id", "estacion", "nombre", "monto_del_turno" (lo
    anotado en ese turno), "debe" (toda la cuenta: lo que se cobra)}.
    """
    filas = conexion.execute(
        """
        SELECT cuentas_pc.id AS cuenta_id, sesiones_pc.estacion_id, estaciones.nombre AS estacion,
               cuentas_pc.nombre,
               SUM(CASE WHEN cuenta_pc_items.fecha > ? AND (? IS NULL OR cuenta_pc_items.fecha <= ?)
                        THEN cuenta_pc_items.subtotal ELSE 0 END) AS monto_del_turno,
               SUM(cuenta_pc_items.subtotal) AS debe
        FROM cuentas_pc
        JOIN sesiones_pc ON sesiones_pc.id = cuentas_pc.sesion_id
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        JOIN cuenta_pc_items ON cuenta_pc_items.cuenta_id = cuentas_pc.id
                            AND cuenta_pc_items.quitado_fecha IS NULL
        WHERE cuentas_pc.estado = ?
        GROUP BY cuentas_pc.id
        HAVING monto_del_turno > 0
        ORDER BY cuentas_pc.id
        """,
        (desde, hasta, hasta, dominio.CUENTA_ABIERTA),
    ).fetchall()
    return [{**dict(fila), "monto_del_turno": round(fila["monto_del_turno"], 2), "debe": round(fila["debe"], 2)}
            for fila in filas]


def anotar_fiado_en_el_cierre(conexion, cierre_id: int, desde: str, hasta: str) -> float:
    """La foto de lo fiado en ese turno que quedó sin cobrar, unida al cierre
    (cierres_fiado_pc). Devuelve cuánto suma."""
    fiado = fiado_del_turno(conexion, desde, hasta)
    conexion.executemany(
        "INSERT INTO cierres_fiado_pc (cierre_id, cuenta_id, estacion, nombre, monto) VALUES (?, ?, ?, ?, ?)",
        [(cierre_id, cuenta["cuenta_id"], cuenta["estacion"], cuenta["nombre"], cuenta["monto_del_turno"])
         for cuenta in fiado],
    )
    return round(sum(cuenta["monto_del_turno"] for cuenta in fiado), 2)


def fiado_del_cierre(conexion, cierre_id: int) -> list:
    """Lo fiado sin cobrar que quedó anotado en un cierre: [{"estacion", "nombre", "monto"}]."""
    return [dict(fila) for fila in conexion.execute(
        "SELECT estacion, nombre, monto FROM cierres_fiado_pc WHERE cierre_id = ? ORDER BY id", (cierre_id,)
    )]
