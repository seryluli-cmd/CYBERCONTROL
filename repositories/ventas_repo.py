"""
ventas_repo.py
===============
Todo lo relacionado a registrar ventas (facturación) y, cuando hace
falta, anularlas.

Un detalle importante de diseño: el "carrito" de una venta en curso vive
solo en la memoria de la pantalla de Ventas (una lista de Python) — no se
guarda nada en la base de datos hasta que se confirma el pago. Por eso
una empleada puede borrar un renglón mal escaneado libremente mientras
está armando la venta: recién cuando se llama a `confirmar_venta(...)`
queda algo grabado, y a partir de ahí ya no se puede tocar (solo un
Admin puede anularla después con `anular_venta`).
"""

from datetime import datetime

import dominio
from database import conexion_db
from turnos import calcular_turno


def subtotal_linea(linea) -> float:
    """
    Cuánto se cobra por un renglón del carrito. Hoy es simplemente
    cantidad × precio, pero pasa por acá a propósito: es el único lugar
    donde se decide esa cuenta, así que el día que haya un descuento por
    cantidad o una promo 2x1, se cambia una sola función y la pantalla
    de Ventas, el total y lo que se graba en la base quedan coherentes
    solos.
    """
    return linea["cantidad"] * linea["precio_unitario"]


def total_carrito(lineas: list) -> float:
    """Total de una venta en curso, sumando el subtotal de cada renglón."""
    return sum(subtotal_linea(linea) for linea in lineas)


def confirmar_venta(usuario_id: int, lineas: list, pagos: list) -> int:
    """
    Graba una venta ya armada y cobrada.

    lineas: lista de diccionarios
        {"codigo", "descripcion", "cantidad", "precio_unitario"}
        El subtotal NO se recibe: se calcula acá con `subtotal_linea()`,
        para que la pantalla no pueda mandar una cuenta distinta a la que
        se graba en la base.
    pagos: lista de diccionarios
        {"metodo": dominio.PAGO_EFECTIVO | dominio.PAGO_DIGITAL, "monto": ...}
        (puede haber más de uno, para pagos combinados)

    Descuenta el stock de cada artículo vendido (puede quedar negativo,
    a propósito) y devuelve el número de factura generado. Cabecera,
    detalle, pagos y descuento de stock quedan todos en la misma
    transacción: si algo falla a mitad de camino, no queda una venta a
    medio grabar con el stock ya descontado.

    Los montos se redondean a 2 decimales antes de guardarse, para que
    pequeños errores de redondeo de punto flotante no se vayan
    acumulando venta tras venta a lo largo de los años.
    """
    ahora = datetime.now()
    ahora_iso = ahora.isoformat(timespec="seconds")
    turno = calcular_turno(ahora)
    total = round(total_carrito(lineas), 2)

    with conexion_db() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (ahora_iso, usuario_id, turno, total, dominio.VENTA_CONFIRMADA, dominio.ORIGEN_KIOSKO),
        )
        venta_id = cursor.lastrowid

        for linea in lineas:
            conexion.execute(
                """
                INSERT INTO venta_detalle
                    (venta_id, articulo_codigo, descripcion, cantidad, precio_unitario, subtotal)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (venta_id, linea["codigo"], linea["descripcion"], linea["cantidad"],
                 round(linea["precio_unitario"], 2), round(subtotal_linea(linea), 2)),
            )
            # Restamos el stock. Se permite que quede en negativo (ver
            # database.py / articulos_repo.py para la explicación completa).
            conexion.execute(
                "UPDATE articulos SET stock = stock - ? WHERE codigo = ?",
                (linea["cantidad"], linea["codigo"]),
            )

        for pago in pagos:
            conexion.execute(
                "INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (?, ?, ?)",
                (venta_id, pago["metodo"], round(pago["monto"], 2)),
            )

        return venta_id


def anular_venta(venta_id: int, usuario_admin_id: int, motivo: str):
    """
    Anula una venta ya confirmada (solo lo puede hacer un Admin, eso se
    valida en la pantalla, no acá). Repone el stock de cada artículo
    vendido y deja constancia de quién anuló, cuándo, y por qué — la
    venta NUNCA se borra de la base, solo cambia su estado a ANULADA,
    para no perder el rastro.
    """
    with conexion_db() as conexion:
        venta = conexion.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        if venta is None:
            raise ValueError("La venta no existe.")
        if venta["estado"] == dominio.VENTA_ANULADA:
            raise ValueError("Esa venta ya estaba anulada.")

        lineas = conexion.execute(
            "SELECT articulo_codigo, cantidad FROM venta_detalle WHERE venta_id = ?", (venta_id,)
        ).fetchall()
        for linea in lineas:
            conexion.execute(
                "UPDATE articulos SET stock = stock + ? WHERE codigo = ?",
                (linea["cantidad"], linea["articulo_codigo"]),
            )

        ahora = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """
            UPDATE ventas
            SET estado = ?, anulada_por = ?, anulada_fecha = ?, anulada_motivo = ?
            WHERE id = ?
            """,
            (dominio.VENTA_ANULADA, usuario_admin_id, ahora, motivo, venta_id),
        )


def buscar_venta(venta_id: int):
    """Trae una venta con su detalle y sus pagos, para mostrarla antes
    de anularla (o simplemente para consultarla)."""
    with conexion_db() as conexion:
        venta = conexion.execute("SELECT * FROM ventas WHERE id = ?", (venta_id,)).fetchone()
        if venta is None:
            return None, [], []
        detalle = conexion.execute(
            "SELECT * FROM venta_detalle WHERE venta_id = ?", (venta_id,)
        ).fetchall()
        pagos = conexion.execute(
            "SELECT * FROM venta_pagos WHERE venta_id = ?", (venta_id,)
        ).fetchall()
        return venta, detalle, pagos


def registrar_venta_sin_detalle(
    conexion, usuario_id: int, monto: float, metodo_pago: str, origen: str, ahora: datetime
) -> int:
    """
    Cabecera de venta compartida para lo que se cobra sin un artículo real
    de por medio -- un bono de PC o una carga de saldo de Miembro (ver
    control_pcs/repositories/pcs_repo.asignar_bono y
    control_pcs/repositories/miembros_repo._registrar_carga). No hay fila
    de venta_detalle porque esa tabla exige un articulo_codigo real.

    A diferencia de confirmar_venta(), recibe una conexión YA ABIERTA: el
    que llama a esta función ya está adentro de su propio `with
    conexion_db()` (por ejemplo, junto con el INSERT de sesion_bonos o el
    UPDATE del saldo del socio), y todo tiene que quedar en la misma
    transacción. Es el único lugar que arma una venta sin detalle -- antes
    cada llamador insertaba su propio "INSERT INTO ventas" casi idéntico.

    También recibe `ahora` en vez de llamar a su propio `datetime.now()`:
    el llamador ya calculó un `ahora` para el resto de la operación (la
    sesión de PC, el movimiento de saldo) y tiene que ser exactamente el
    mismo instante en los dos lados, no uno un poco después del otro.
    """
    ahora_iso = ahora.isoformat(timespec="seconds")
    turno = calcular_turno(ahora)

    cursor = conexion.execute(
        """
        INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ahora_iso, usuario_id, turno, round(monto, 2), dominio.VENTA_CONFIRMADA, origen),
    )
    venta_id = cursor.lastrowid
    conexion.execute(
        "INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (?, ?, ?)",
        (venta_id, metodo_pago, round(monto, 2)),
    )
    return venta_id


def listar_ventas_recientes(limite: int = 50):
    """Últimas ventas cargadas, para la pantalla de Consulta/Anulación."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT ventas.*, usuarios.nombre AS vendedor
            FROM ventas
            JOIN usuarios ON usuarios.id = ventas.usuario_id
            ORDER BY ventas.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
