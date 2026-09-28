"""
bonos_miembro_repo.py
=======================
Catálogo de bonos de tiempo EXCLUSIVO para Miembros (socios con saldo
prepago) -- separado a propósito de pcs_repo.bonos_tiempo, que es el
catálogo de bonos COMUNES para cualquier persona que entra al local sin
ser socia. Antes "Cargar Saldo" -> "Bono fijo" reusaba el catálogo de
walk-ins; el dueño pidió separarlos porque a los socios les puede convenir
ofrecerles combos propios (ver control_pcs/ui/miembros_window.py).

Mismo esquema y mismas reglas que bonos_tiempo (nombre/minutos/precio,
"activo" para dar de baja sin romper el historial de cargas que ya lo
usaron) -- la única diferencia real es la tabla, y que crear/editar acá
está restringido a ADMIN (ver MiembrosWindow), a diferencia de
pcs_repo.crear_bono/modificar_bono/desactivar_bono, que cualquiera con
'permiso_control_pcs' puede usar. Esa restricción se aplica en la UI
(qué botón se muestra), no acá: este repo no sabe nada de permisos, igual
que el resto de repositories/ (ver CLAUDE.md, regla 1).
"""

import dominio
from database import conexion_db


def listar_bonos(solo_activos: bool = True):
    with conexion_db() as conexion:
        if solo_activos:
            return conexion.execute(
                "SELECT * FROM bonos_miembro WHERE activo = 1 ORDER BY minutos"
            ).fetchall()
        return conexion.execute("SELECT * FROM bonos_miembro ORDER BY minutos").fetchall()


def obtener_bono(bono_id: int):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM bonos_miembro WHERE id = ?", (bono_id,)).fetchone()


def crear_bono(nombre: str, minutos: int, precio: float) -> int:
    dominio.validar_datos_bono(nombre, minutos, precio)
    with conexion_db() as conexion:
        cursor = conexion.execute(
            "INSERT INTO bonos_miembro (nombre, minutos, precio) VALUES (?, ?, ?)",
            (nombre.strip(), minutos, round(precio, 2)),
        )
        return cursor.lastrowid


def modificar_bono(bono_id: int, nombre: str, minutos: int, precio: float):
    dominio.validar_datos_bono(nombre, minutos, precio)
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE bonos_miembro SET nombre = ?, minutos = ?, precio = ? WHERE id = ?",
            (nombre.strip(), minutos, round(precio, 2), bono_id),
        )


def desactivar_bono(bono_id: int):
    """No se borra (un bono ya cargado por algún socio queda referenciado
    desde movimientos_saldo_miembro), solo deja de ofrecerse para cargas
    nuevas."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE bonos_miembro SET activo = 0 WHERE id = ?", (bono_id,))
