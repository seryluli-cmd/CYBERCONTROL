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
    # Microsegundos, no segundos: turnos_repo compara "ventas.fecha" contra
    # "cierres_turno.fecha_cierre" con un corte estricto (> / <=) para
    # decidir a qué turno pertenece cada venta. Con precisión de un solo
    # segundo, una venta y un cierre que cayeran en el mismo segundo (una
    # venta hecha justo al abrir el turno siguiente, por ejemplo) podían
    # empatar en el string de fecha y la venta quedaba afuera de los DOS
    # turnos -- ni en el que se estaba cerrando (llegó después del corte)
    # ni en el siguiente (el ">" estricto la excluía por el empate). Ver
    # turnos_repo.cerrar_turno, que graba fecha_cierre con la misma
    # precisión por la misma razón.
    ahora_iso = ahora.isoformat(timespec="microseconds")
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


def _anular_venta(conexion, venta_id: int, usuario_admin_id: int, motivo: str):
    """
    Núcleo de anular_venta que opera sobre una conexión YA ABIERTA -- lo
    necesita control_pcs.repositories.miembros_repo.anular_carga para que
    anular una venta que había cargado saldo de un socio, y revertir esa
    carga (ver ahí), queden en la MISMA transacción: o se anulan y
    revierten juntas, o no se anula nada.
    """
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


def anular_venta(venta_id: int, usuario_admin_id: int, motivo: str):
    """
    Anula una venta ya confirmada (solo lo puede hacer un Admin, eso se
    valida en la pantalla, no acá). Repone el stock de cada artículo
    vendido y deja constancia de quién anuló, cuándo, y por qué — la
    venta NUNCA se borra de la base, solo cambia su estado a ANULADA,
    para no perder el rastro.

    Si la venta había cargado saldo a un socio (control_pcs, "Cargar
    Saldo"), usar control_pcs.repositories.miembros_repo.anular_carga en
    su lugar -- esta función solo sabe de ventas/stock, y anular una
    carga sin revertir el saldo le dejaría al socio minutos que ya nadie
    cobró (ver ese repo).
    """
    with conexion_db() as conexion:
        _anular_venta(conexion, venta_id, usuario_admin_id, motivo)


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
    conexion, usuario_id: int, monto: float, pagos: list, origen: str, ahora: datetime
) -> int:
    """
    Cabecera de venta compartida para lo que se cobra sin un artículo real
    de por medio -- un bono de PC o una carga de saldo de Miembro (ver
    control_pcs/repositories/pcs_repo.asignar_bono y
    control_pcs/repositories/miembros_repo._registrar_carga). No hay fila
    de venta_detalle porque esa tabla exige un articulo_codigo real.

    `monto` es el total real de la operación (precio del bono, o el monto
    cargado de saldo) y es lo que se graba en `ventas.total`, tal cual,
    sin importar lo que haya circulado en `pagos` -- mismo criterio que
    confirmar_venta(), donde el total sale del carrito y no de la suma de
    los pagos (un pago en Efectivo puede superar el total si hay vuelto
    de por medio). `pagos` es una lista de {"metodo", "monto"} -- puede
    traer más de una fila para un cobro Mixto (Efectivo + Digital), ver
    ui/dialogo_pago.DialogoPago, reutilizado tal cual para este caso.

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
    # Microsegundos, no segundos: ver el mismo comentario en
    # confirmar_venta -- acá aplica igual, esto también graba "ventas.fecha".
    ahora_iso = ahora.isoformat(timespec="microseconds")
    turno = calcular_turno(ahora)

    cursor = conexion.execute(
        """
        INSERT INTO ventas (fecha, usuario_id, turno, total, estado, origen)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (ahora_iso, usuario_id, turno, round(monto, 2), dominio.VENTA_CONFIRMADA, origen),
    )
    venta_id = cursor.lastrowid
    for pago in pagos:
        conexion.execute(
            "INSERT INTO venta_pagos (venta_id, metodo, monto) VALUES (?, ?, ?)",
            (venta_id, pago["metodo"], round(pago["monto"], 2)),
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
