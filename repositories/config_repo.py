"""
config_repo.py
================
Acceso a la tabla `configuracion` (valores generales del sistema, tipo
"clave -> valor"). Por ahora solo se usa para el fondo de cambio fijo,
pero está pensada para poder sumar más configuraciones sin tener que
cambiar el esquema de la base de datos.
"""

from database import conexion_db


def obtener_fondo_cambio() -> float:
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = 'fondo_cambio'"
        ).fetchone()
        return float(fila["valor"]) if fila else 0.0


def actualizar_fondo_cambio(nuevo_valor: float):
    """Solo el Admin puede llamar a esto (se valida en la pantalla)."""
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE configuracion SET valor = ? WHERE clave = 'fondo_cambio'",
            (str(round(nuevo_valor, 2)),),
        )


def obtener_tarifa_hora_miembro() -> float:
    """Cuántos pesos vale una hora de saldo para un Miembro (ver
    miembros_repo.cargar_saldo_por_monto). Modificable por el Admin."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = 'tarifa_hora_miembro'"
        ).fetchone()
        return float(fila["valor"]) if fila else 1000.0


def actualizar_tarifa_hora_miembro(nuevo_valor: float):
    """Solo el Admin puede llamar a esto (se valida en la pantalla)."""
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE configuracion SET valor = ? WHERE clave = 'tarifa_hora_miembro'",
            (str(round(nuevo_valor, 2)),),
        )
