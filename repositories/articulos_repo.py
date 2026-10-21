"""
articulos_repo.py
==================
Funciones para leer y escribir artículos, marcas y rubros.

Importante: el alta y la edición de un artículo NO tocan su "stock". Esto
es a propósito: el stock se mueve con una Compra
(compras_repo.registrar_compra), con una Venta (ventas_repo.confirmar_venta /
anular_venta) o con ORDENAR Stock (ajustar_stock, abajo, que deja cada
corrección anotada en ajustes_stock), para que el historial de
"Movimientos" siempre sea confiable. El código tampoco se cambia al editar:
solo ORDENAR Stock lo corrige (cambiar_codigo, anotado en cambios_codigo).
"""

import sqlite3
from datetime import datetime
import dominio
from database import conexion_db, verificar_clave
from repositories import usuarios_repo

# La contraseña de ORDENAR Stock: la eligió el dueño (2026-10-20) y es fija.
# Acá está solo su hash con salt (database.hash_clave), nunca en claro: este
# repo es público. Para cambiarla, reemplazar este valor por el de
# database.hash_clave("la nueva").
CLAVE_ORDENAR_STOCK = (
    "34ba9a714dd183b754678099a9475e88$62dec9603a6d7096e44ce25ea3514cf37dd523679fc7835e919c428e2835fc9a"
)


# ---------------------------------------------------------------------
# Marcas y Rubros (catálogos auxiliares)
# ---------------------------------------------------------------------

def listar_marcas():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM marcas ORDER BY nombre").fetchall()


def _crear_o_buscar(tabla: str, nombre: str) -> int:
    """El id de `nombre` en un catálogo auxiliar (marcas o rubros), creándolo
    si todavía no existía. `tabla` la pone el código, nunca la usuaria."""
    nombre = nombre.strip()
    with conexion_db() as conexion:
        conexion.execute(f"INSERT OR IGNORE INTO {tabla} (nombre) VALUES (?)", (nombre,))
        fila = conexion.execute(f"SELECT id FROM {tabla} WHERE nombre = ?", (nombre,)).fetchone()
        return fila["id"]


def crear_marca(nombre: str) -> int:
    """Crea la marca y devuelve su id; si ya existía una con ese nombre,
    devuelve el id de la existente en vez de fallar (así se puede "agregar
    al vuelo" desde Artículos sin chequear antes)."""
    return _crear_o_buscar("marcas", nombre)


def listar_rubros():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM rubros ORDER BY nombre").fetchall()


def crear_rubro(nombre: str) -> int:
    """Igual que crear_marca: devuelve el id, sea nuevo o ya existente."""
    return _crear_o_buscar("rubros", nombre)


def renombrar_rubro(rubro_id: int, nuevo_nombre: str):
    nuevo_nombre = nuevo_nombre.strip()
    if not nuevo_nombre:
        raise ValueError("El nombre del rubro no puede quedar vacío.")
    try:
        with conexion_db() as conexion:
            conexion.execute(
                "UPDATE rubros SET nombre = ? WHERE id = ?", (nuevo_nombre, rubro_id)
            )
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe un rubro llamado '{nuevo_nombre}'.")


def borrar_rubro(rubro_id: int):
    """
    Borra un rubro del catálogo. Si algún artículo todavía lo tiene
    asignado, la base de datos rechaza el borrado (para no dejar
    artículos "huérfanos" de rubro sin darse cuenta); se convierte en un
    mensaje claro en vez del error crudo de SQLite.
    """
    try:
        with conexion_db() as conexion:
            conexion.execute("DELETE FROM rubros WHERE id = ?", (rubro_id,))
    except sqlite3.IntegrityError:
        raise ValueError(
            "No se puede borrar este rubro: todavía hay artículos que lo tienen "
            "asignado. Cambiales el rubro primero desde 'Modificar' en Artículos."
        )


# ---------------------------------------------------------------------
# Artículos
# ---------------------------------------------------------------------

# Esta consulta base se reutiliza en varios lugares: trae el artículo
# junto con el nombre de su marca y su rubro (no solo el id), para no
# tener que hacer una consulta aparte cada vez que se muestra en pantalla.
_SELECT_ARTICULOS = """
    SELECT
        a.codigo, a.descripcion, a.marca_id, a.rubro_id,
        a.precio_venta, a.precio_compra, a.stock, a.stock_minimo,
        a.fecha_creacion, a.fecha_modif,
        m.nombre AS marca, r.nombre AS rubro
    FROM articulos a
    LEFT JOIN marcas m ON m.id = a.marca_id
    LEFT JOIN rubros r ON r.id = a.rubro_id
"""


def listar_articulos(texto_busqueda: str = ""):
    """
    Devuelve todos los artículos, ordenados por descripción. Si se pasa
    `texto_busqueda`, filtra por código o descripción que lo contengan
    (para el buscador de la grilla).
    """
    with conexion_db() as conexion:
        if texto_busqueda:
            patron = f"%{texto_busqueda}%"
            return conexion.execute(
                _SELECT_ARTICULOS + " WHERE a.codigo LIKE ? OR a.descripcion LIKE ? ORDER BY a.descripcion",
                (patron, patron),
            ).fetchall()
        return conexion.execute(_SELECT_ARTICULOS + " ORDER BY a.descripcion").fetchall()


def buscar_por_codigo(codigo: str):
    """El artículo con ESE código exacto (lo que lee la pistola), o None."""
    with conexion_db() as conexion:
        return conexion.execute(_SELECT_ARTICULOS + " WHERE a.codigo = ?", (codigo,)).fetchone()


def buscar_por_descripcion(texto: str):
    """Artículos cuya descripción CONTIENE `texto` (búsqueda parcial)."""
    with conexion_db() as conexion:
        patron = f"%{texto}%"
        return conexion.execute(
            _SELECT_ARTICULOS + " WHERE a.descripcion LIKE ? ORDER BY a.descripcion", (patron,)
        ).fetchall()


def buscar_por_marca(texto: str):
    """Artículos cuya marca CONTIENE `texto` (búsqueda parcial)."""
    with conexion_db() as conexion:
        patron = f"%{texto}%"
        return conexion.execute(
            _SELECT_ARTICULOS + " WHERE m.nombre LIKE ? ORDER BY a.descripcion", (patron,)
        ).fetchall()


def _marca_para_guardar(conexion, marca_id, nombre_marca_nueva):
    """Resuelve una marca nueva dentro de la misma transacción del artículo."""
    if not nombre_marca_nueva:
        return marca_id
    nombre = nombre_marca_nueva.strip()
    if not nombre:
        return None
    conexion.execute("INSERT OR IGNORE INTO marcas (nombre) VALUES (?)", (nombre,))
    return conexion.execute("SELECT id FROM marcas WHERE nombre = ?", (nombre,)).fetchone()["id"]


def crear_articulo(codigo, descripcion, marca_id, rubro_id, precio_venta, precio_compra,
                   stock_minimo, *, nombre_marca_nueva=None):
    """
    Da de alta un artículo nuevo. El stock arranca en 0: para cargarle
    unidades hay que hacer una Compra (así queda un movimiento
    registrado desde el primer ingreso).
    """
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        marca_id = _marca_para_guardar(conexion, marca_id, nombre_marca_nueva)
        conexion.execute(
            """
            INSERT INTO articulos
                (codigo, descripcion, marca_id, rubro_id, precio_venta,
                 precio_compra, stock, stock_minimo, fecha_creacion, fecha_modif)
            VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?, ?)
            """,
            (codigo, descripcion, marca_id, rubro_id, round(precio_venta, 2),
             round(precio_compra, 2), stock_minimo, ahora, ahora),
        )


def modificar_articulo(codigo, descripcion, marca_id, rubro_id, precio_venta, precio_compra,
                      stock_minimo, *, nombre_marca_nueva=None):
    """
    Actualiza los datos generales de un artículo. A propósito NO recibe
    ni toca el campo "stock" — eso solo cambia vía Compras/Ventas.
    """
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        if conexion.execute("SELECT 1 FROM articulos WHERE codigo = ?", (codigo,)).fetchone() is None:
            raise ValueError("Ese artículo ya no existe. Actualizá la lista e intentá de nuevo.")
        marca_id = _marca_para_guardar(conexion, marca_id, nombre_marca_nueva)
        conexion.execute(
            """
            UPDATE articulos
            SET descripcion = ?, marca_id = ?, rubro_id = ?, precio_venta = ?,
                precio_compra = ?, stock_minimo = ?, fecha_modif = ?
            WHERE codigo = ?
            """,
            (descripcion, marca_id, rubro_id, round(precio_venta, 2),
             round(precio_compra, 2), stock_minimo, ahora, codigo),
        )


def borrar_articulo(codigo):
    """
    Borra un artículo. Si ya tiene compras, ventas o ajustes de stock
    registrados, la base de datos rechaza el borrado (para no perder el
    rastro de esos movimientos): en vez de dejar pasar el error de SQLite
    tal cual — que rompería la pantalla con una traza de Python — lo
    convertimos en un mensaje claro para que se le pueda mostrar a la usuaria.
    """
    try:
        with conexion_db() as conexion:
            conexion.execute("DELETE FROM articulos WHERE codigo = ?", (codigo,))
    except sqlite3.IntegrityError:
        raise ValueError(
            f"No se puede borrar el artículo {codigo}: ya tiene compras, ventas o ajustes "
            "de stock registrados. Si no se usa más, se puede dejar en stock 0 en vez de borrarlo."
        )


# ---------------------------------------------------------------------
# ORDENAR Stock (pedido del dueño, 2026-10-20)
# ---------------------------------------------------------------------
# Al empezar a usar el programa en el local hubo demasiados desarreglos de
# stock: un Admin, con la contraseña de ORDENAR Stock, escribe cuántos hay de
# verdad. Se controla acá y no solo en la pantalla (como en playstation_repo):
# se relee el usuario de la base en cada cambio, así un Admin dado de baja con
# la ventana abierta no sigue corrigiendo.

def comprobar_clave_para_ordenar_stock(usuario_id: int, clave: str):
    """PermissionError con el motivo si `usuario_id` no es un Admin activo o
    `clave` no es la de ORDENAR Stock. Es lo que pregunta el botón antes de
    abrir la pantalla; ajustar_stock lo vuelve a preguntar en cada cambio."""
    usuarios_repo.exigir_admin(usuario_id, "ordenar el stock")
    if not verificar_clave(clave or "", CLAVE_ORDENAR_STOCK):
        raise PermissionError("La contraseña de ORDENAR Stock no es correcta.")


def _stock_contado(valor) -> int:
    """El stock que se escribió (número o texto, como llega de la grilla), o
    ValueError si no es un entero de 0 para arriba. Acá no se acepta un
    negativo: es lo que hay contado en el estante (que el stock pueda quedar
    negativo es para no frenar una venta, ver database_esquema)."""
    texto = "" if valor is None or isinstance(valor, bool) else str(valor).strip()
    # isascii: "²" o "٣" también son "dígitos" para Python.
    if not (texto.isascii() and texto.isdigit()):
        escrito = f' (se escribió "{texto}")' if texto else ""
        raise ValueError(f"El stock tiene que ser un número entero, de 0 para arriba{escrito}.")
    return int(texto)


def ajustar_stock(usuario_id: int, codigo: str, stock_nuevo, clave: str) -> dict:
    """
    Deja el stock de `codigo` en `stock_nuevo` (lo contado) y lo anota en
    ajustes_stock con lo que había, quién y cuándo. No toca precios, costos,
    ventas ni la caja. Devuelve {"stock_anterior", "stock_nuevo"}; si ya
    tenía ese número no anota nada.

    "Lo que había" se lee de la base en la misma transacción, no de la
    pantalla: si se vendió algo mientras la grilla estaba abierta, el ajuste
    anotado es el real. PermissionError (ver comprobar_clave_para_ordenar_stock)
    o ValueError (número mal escrito, artículo que ya no existe).
    """
    comprobar_clave_para_ordenar_stock(usuario_id, clave)
    stock_nuevo = _stock_contado(stock_nuevo)
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        # Toma el permiso de escritura de entrada: una venta no puede cambiar el
        # stock entre la lectura de "lo que había" y la corrección.
        conexion.execute("BEGIN IMMEDIATE")
        fila = conexion.execute("SELECT stock FROM articulos WHERE codigo = ?", (codigo,)).fetchone()
        if fila is None:
            raise ValueError("Ese artículo ya no existe. Actualizá la lista e intentá de nuevo.")
        stock_anterior = fila["stock"]
        if stock_anterior != stock_nuevo:
            conexion.execute("UPDATE articulos SET stock = ? WHERE codigo = ?", (stock_nuevo, codigo))
            conexion.execute(
                """
                INSERT INTO ajustes_stock (articulo_codigo, fecha, usuario_id, stock_anterior, stock_nuevo)
                VALUES (?, ?, ?, ?, ?)
                """,
                (codigo, ahora, usuario_id, stock_anterior, stock_nuevo),
            )
    return {"stock_anterior": stock_anterior, "stock_nuevo": stock_nuevo}


# Las tablas que guardan el código de un artículo (todas con REFERENCES
# articulos(codigo)): cambiar_codigo las corrige todas juntas. Una tabla nueva
# que apunte a un artículo va acá; tests/test_ordenar_stock.py lo vigila.
_TABLAS_CON_CODIGO_DE_ARTICULO = ("venta_detalle", "compra_detalle", "ajustes_stock", "cambios_codigo")


def cambiar_codigo(usuario_id: int, codigo_actual: str, codigo_nuevo, clave: str) -> dict:
    """
    Corrige el código de un artículo (pedido del dueño, 2026-10-20: hubo
    códigos escritos a mano mal en vez de leídos con la pistola). Las ventas,
    compras y ajustes de stock de antes pasan al código nuevo en la misma
    transacción: es el mismo producto, su historial lo sigue. Queda anotado en
    cambios_codigo y en Movimientos. Devuelve {"codigo_anterior", "codigo_nuevo"};
    el mismo código no anota nada.

    PermissionError como ajustar_stock, o ValueError: código nuevo vacío, que ya
    es de otro artículo (dos artículos no pueden compartirlo: no se juntan solos),
    o el de Impresiones, que no se cambia ni se le da a otro (el botón Impresiones
    y los reportes lo buscan por ese número, dominio.CODIGO_ARTICULO_IMPRESIONES).
    """
    comprobar_clave_para_ordenar_stock(usuario_id, clave)
    nuevo = "" if codigo_nuevo is None else str(codigo_nuevo).strip()
    if not nuevo:
        raise ValueError("El código nuevo no puede quedar vacío.")
    impresiones = dominio.CODIGO_ARTICULO_IMPRESIONES
    if impresiones in (codigo_actual, nuevo) and codigo_actual != nuevo:
        raise ValueError(
            f"El código {impresiones} es el de Impresiones: el botón Impresiones y los reportes "
            "lo buscan por ese número, así que no se cambia ni se le pone a otro artículo."
        )
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        # Las tablas hijas apuntan al código: con las referencias revisadas recién al
        # guardar, se cambia el artículo y después cada tabla. Si faltara una, el
        # guardado falla y no queda nada a medias (conexion_db deshace todo).
        conexion.execute("PRAGMA defer_foreign_keys = ON")
        if conexion.execute("SELECT 1 FROM articulos WHERE codigo = ?", (codigo_actual,)).fetchone() is None:
            raise ValueError("Ese artículo ya no existe. Actualizá la lista e intentá de nuevo.")
        if nuevo == codigo_actual:
            return {"codigo_anterior": codigo_actual, "codigo_nuevo": nuevo}
        otro = conexion.execute("SELECT descripcion FROM articulos WHERE codigo = ?", (nuevo,)).fetchone()
        if otro is not None:
            raise ValueError(
                f'El código {nuevo} ya es de otro artículo: "{otro["descripcion"]}". '
                "Dos artículos no pueden tener el mismo código."
            )
        conexion.execute(
            "UPDATE articulos SET codigo = ?, fecha_modif = ? WHERE codigo = ?", (nuevo, ahora, codigo_actual)
        )
        for tabla in _TABLAS_CON_CODIGO_DE_ARTICULO:
            conexion.execute(
                f"UPDATE {tabla} SET articulo_codigo = ? WHERE articulo_codigo = ?", (nuevo, codigo_actual)
            )
        conexion.execute(
            """
            INSERT INTO cambios_codigo (articulo_codigo, fecha, usuario_id, codigo_anterior, codigo_nuevo)
            VALUES (?, ?, ?, ?, ?)
            """,
            (nuevo, ahora, usuario_id, codigo_actual, nuevo),
        )
    return {"codigo_anterior": codigo_actual, "codigo_nuevo": nuevo}


def obtener_movimientos(codigo: str, desde: str, hasta: str):
    """
    Arma el historial de "Movimientos" de un artículo: junta las líneas
    de Compras (suman stock), las líneas de Ventas confirmadas (restan
    stock), los ajustes de ORDENAR Stock (lo que sumó o restó cada uno) y
    los cambios de código (cantidad 0, con el código de antes y el nuevo)
    dentro de un rango de fechas, y las devuelve ordenadas por fecha. Las
    ventas anuladas no aparecen: ya repusieron su stock.
    """
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT fecha, 'compras' AS comprobante, compra_id AS numero, cantidad
            FROM compra_detalle
            JOIN compras ON compras.id = compra_detalle.compra_id
            WHERE articulo_codigo = ? AND date(fecha) BETWEEN date(?) AND date(?)

            UNION ALL

            SELECT ventas.fecha AS fecha, 'ventas' AS comprobante, ventas.id AS numero,
                   -venta_detalle.cantidad AS cantidad
            FROM venta_detalle
            JOIN ventas ON ventas.id = venta_detalle.venta_id
            WHERE venta_detalle.articulo_codigo = ?
              AND ventas.estado = ?
              AND date(ventas.fecha) BETWEEN date(?) AND date(?)

            UNION ALL

            SELECT fecha, 'ajuste de stock' AS comprobante, id AS numero,
                   stock_nuevo - stock_anterior AS cantidad
            FROM ajustes_stock
            WHERE articulo_codigo = ? AND date(fecha) BETWEEN date(?) AND date(?)

            UNION ALL

            SELECT fecha, 'cambio de código ' || codigo_anterior || ' → ' || codigo_nuevo AS comprobante,
                   id AS numero, 0 AS cantidad
            FROM cambios_codigo
            WHERE articulo_codigo = ? AND date(fecha) BETWEEN date(?) AND date(?)

            -- El número desempata lo que pasó en el mismo segundo (dos ajustes
            -- seguidos del mismo artículo): sin él, podían salir al revés.
            ORDER BY fecha, numero
            """,
            (codigo, desde, hasta, codigo, dominio.VENTA_CONFIRMADA, desde, hasta,
             codigo, desde, hasta, codigo, desde, hasta),
        ).fetchall()
