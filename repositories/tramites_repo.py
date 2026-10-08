"""
tramites_repo.py
==================
Trámites: servicios que se cobran en el mostrador sin un artículo de por
medio, ej. "Sacar boleta de luz". El Admin arma el catálogo (nombre
solamente) y al cobrar se tipea el monto que corresponda en ese momento: no
hay precio fijo.

Cobrar un trámite es una venta más: una fila común de `ventas` (origen
KIOSKO, sin `venta_detalle`, se arma con ventas_repo.registrar_venta_sin_detalle)
más una fila en `tramites_venta` que dice QUÉ trámite fue. Por eso Caja,
Cierre de Turno y los reportes la cuentan sin tocar nada, y anularla desde
Consulta de Ventas funciona igual que con cualquier otra venta.
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import ventas_repo


def _exigir_nombre_libre(conexion, nombre: str, excluir_id: int = None):
    """Levanta ValueError (mensaje listo para mostrar) si el nombre está
    vacío o ya lo usa otro trámite ACTIVO (ignorando mayúsculas/espacios; la
    comparación va en Python porque el LOWER() de SQLite no pliega bien las
    mayúsculas con acento, ver usuarios_repo._nombre_en_uso). Uno dado de
    baja no cuenta: se puede volver a crear con el mismo nombre."""
    if not nombre.strip():
        raise ValueError("El nombre del trámite no puede quedar vacío.")
    objetivo = nombre.strip().lower()
    for fila in conexion.execute("SELECT id, nombre FROM tramites WHERE activo = 1"):
        if excluir_id is not None and fila["id"] == excluir_id:
            continue
        if fila["nombre"].strip().lower() == objetivo:
            raise ValueError(f"Ya existe un trámite llamado '{fila['nombre']}'.")


def listar_tramites():
    """Los trámites activos, ordenados por nombre (sin distinguir
    mayúsculas), listos para elegir en el mostrador."""
    with conexion_db() as conexion:
        filas = conexion.execute("SELECT * FROM tramites WHERE activo = 1").fetchall()
    return sorted(filas, key=lambda fila: fila["nombre"].lower())


def obtener_tramite(tramite_id: int):
    """La fila de un trámite (activo o no), o None si no existe."""
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM tramites WHERE id = ?", (tramite_id,)).fetchone()


def crear_tramite(nombre: str) -> int:
    """Da de alta un trámite y devuelve su id."""
    with conexion_db() as conexion:
        _exigir_nombre_libre(conexion, nombre)
        cursor = conexion.execute(
            "INSERT INTO tramites (nombre, fecha_creacion) VALUES (?, ?)",
            (nombre.strip(), datetime.now().isoformat(timespec="seconds")),
        )
        return cursor.lastrowid


def modificar_tramite(tramite_id: int, nombre: str):
    """Cambia el nombre de un trámite. Las ventas ya cobradas conservan el
    nombre que tenía en ese momento (ver tramites_venta.descripcion)."""
    with conexion_db() as conexion:
        _exigir_nombre_libre(conexion, nombre, excluir_id=tramite_id)
        conexion.execute("UPDATE tramites SET nombre = ? WHERE id = ?", (nombre.strip(), tramite_id))


def desactivar_tramite(tramite_id: int):
    """Da de baja un trámite: no se borra (las ventas que ya lo cobraron lo
    siguen referenciando), solo deja de ofrecerse en el mostrador."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE tramites SET activo = 0 WHERE id = ?", (tramite_id,))


def registrar_tramite(usuario_id: int, tramite_id: int, monto: float, pagos: list) -> int:
    """
    Cobra un trámite por `monto` (libre, lo tipea quien atiende) y devuelve
    el id de la venta generada. `pagos` es una lista de {"metodo", "monto"},
    ver ui.dialogo_pago.resolver_pagos.

    Venta, pagos y vínculo con el trámite se graban en la misma transacción:
    o queda todo o no queda nada (CLAUDE.md, regla 8). El `monto` se graba
    tal cual en `ventas.total` (mismo criterio que
    ventas_repo.registrar_venta_sin_detalle); los pagos tienen que cubrirlo.
    """
    monto = round(monto, 2)
    if monto <= 0:
        raise ValueError("Ingresá un monto mayor a cero.")
    if sum(pago["monto"] for pago in pagos) < monto - 0.01:
        raise ValueError("Los pagos no cubren el monto del trámite.")

    with conexion_db() as conexion:
        tramite = conexion.execute(
            "SELECT * FROM tramites WHERE id = ? AND activo = 1", (tramite_id,)
        ).fetchone()
        if tramite is None:
            raise ValueError("Ese trámite ya no está disponible.")

        venta_id = ventas_repo.registrar_venta_sin_detalle(
            conexion, usuario_id, monto, pagos, dominio.ORIGEN_KIOSKO, datetime.now()
        )
        conexion.execute(
            "INSERT INTO tramites_venta (venta_id, tramite_id, descripcion) VALUES (?, ?, ?)",
            (venta_id, tramite_id, tramite["nombre"]),
        )
        return venta_id


def tramite_de_venta(venta_id: int):
    """El nombre del trámite que se cobró en esa venta, o None si la venta no
    fue un trámite (para mostrar de qué se trató en Consulta de Ventas)."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT descripcion FROM tramites_venta WHERE venta_id = ?", (venta_id,)
        ).fetchone()
    return fila["descripcion"] if fila else None
