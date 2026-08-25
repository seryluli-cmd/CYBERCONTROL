"""
articulos_repo.py
==================
Funciones para leer y escribir artículos, marcas y rubros.

Importante: ninguna función de este archivo modifica el "stock" de un
artículo directamente (salvo la función interna que usa compras_repo y
ventas_repo). Esto es a propósito: el stock solo se mueve a través de una
Compra o de una Venta, nunca editando el artículo a mano, para que el
historial de "Movimientos" siempre sea confiable.
"""

import sqlite3
from datetime import datetime
from database import conexion_db


# ---------------------------------------------------------------------
# Marcas y Rubros (catálogos auxiliares)
# ---------------------------------------------------------------------

def listar_marcas():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM marcas ORDER BY nombre").fetchall()


def crear_marca(nombre: str) -> int:
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR IGNORE INTO marcas (nombre) VALUES (?)", (nombre.strip(),)
        )
        fila = conexion.execute(
            "SELECT id FROM marcas WHERE nombre = ?", (nombre.strip(),)
        ).fetchone()
        return fila["id"]


def listar_rubros():
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM rubros ORDER BY nombre").fetchall()


def crear_rubro(nombre: str) -> int:
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR IGNORE INTO rubros (nombre) VALUES (?)", (nombre.strip(),)
        )
        fila = conexion.execute(
            "SELECT id FROM rubros WHERE nombre = ?", (nombre.strip(),)
        ).fetchone()
        return fila["id"]


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
    Devuelve todos los artículos, ordenados por descripción (igual que en
    el sistema actual). Si se pasa `texto_busqueda`, filtra por código o
    descripción que lo contengan (para el buscador de la grilla).
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
    with conexion_db() as conexion:
        return conexion.execute(_SELECT_ARTICULOS + " WHERE a.codigo = ?", (codigo,)).fetchone()


def buscar_por_descripcion(texto: str):
    with conexion_db() as conexion:
        patron = f"%{texto}%"
        return conexion.execute(
            _SELECT_ARTICULOS + " WHERE a.descripcion LIKE ? ORDER BY a.descripcion", (patron,)
        ).fetchall()


def buscar_por_marca(texto: str):
    with conexion_db() as conexion:
        patron = f"%{texto}%"
        return conexion.execute(
            _SELECT_ARTICULOS + " WHERE m.nombre LIKE ? ORDER BY a.descripcion", (patron,)
        ).fetchall()


def crear_articulo(codigo, descripcion, marca_id, rubro_id, precio_venta, precio_compra, stock_minimo):
    """
    Da de alta un artículo nuevo. El stock arranca en 0: para cargarle
    unidades hay que hacer una Compra (así queda un movimiento
    registrado desde el primer ingreso).
    """
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
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


def modificar_articulo(codigo, descripcion, marca_id, rubro_id, precio_venta, precio_compra, stock_minimo):
    """
    Actualiza los datos generales de un artículo. A propósito NO recibe
    ni toca el campo "stock" — eso solo cambia vía Compras/Ventas.
    """
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
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
    Borra un artículo. Si ya tiene compras o ventas registradas, la
    base de datos rechaza el borrado (para no perder el rastro de esos
    movimientos): en vez de dejar pasar el error de SQLite tal cual —
    que rompería la pantalla con una traza de Python — lo convertimos
    en un mensaje claro para que se le pueda mostrar a la usuaria.
    """
    try:
        with conexion_db() as conexion:
            conexion.execute("DELETE FROM articulos WHERE codigo = ?", (codigo,))
    except sqlite3.IntegrityError:
        raise ValueError(
            f"No se puede borrar el artículo {codigo}: ya tiene compras o ventas "
            "registradas. Si no se usa más, se puede dejar en stock 0 en vez de borrarlo."
        )


def obtener_movimientos(codigo: str, desde: str, hasta: str):
    """
    Arma el historial de "Movimientos" de un artículo: junta las líneas
    de Compras (suman stock) y las líneas de Ventas confirmadas (restan
    stock) dentro de un rango de fechas, y las devuelve ordenadas por
    fecha — igual que la pantalla "Movimientos" del sistema actual.
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
              AND ventas.estado = 'CONFIRMADA'
              AND date(ventas.fecha) BETWEEN date(?) AND date(?)

            ORDER BY fecha
            """,
            (codigo, desde, hasta, codigo, desde, hasta),
        ).fetchall()
