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
