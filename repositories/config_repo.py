"""
config_repo.py
================
Acceso a la tabla `configuracion` (valores generales del sistema, tipo
"clave -> valor"). Por ahora solo se usa para el fondo de cambio fijo,
pero está pensada para poder sumar más configuraciones sin tener que
cambiar el esquema de la base de datos.
"""

import json

import dominio
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
    """Tarifa $/hora vieja, de un solo valor -- ya no la usa ninguna
    pantalla (ver obtener_tramos_tarifa_hora_miembro), pero queda como
    lectura de la clave heredada 'tarifa_hora_miembro' para poder migrar
    una base que la tenga configurada al primer tramo de la tabla nueva,
    sin cambiarle el precio a nadie de un día para el otro."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = 'tarifa_hora_miembro'"
        ).fetchone()
        return float(fila["valor"]) if fila else 1000.0


_CLAVE_TRAMOS_TARIFA_MIEMBRO = "tramos_tarifa_hora_miembro"


def obtener_tramos_tarifa_hora_miembro() -> list:
    """
    Tabla de tramos (monto_minimo -> tarifa_hora) para convertir una
    carga de saldo libre en minutos -- ver
    miembros_repo.cargar_saldo_por_monto y dominio.tarifa_hora_para_monto,
    que es quien decide qué tramo corresponde a un monto dado. Se guarda
    como JSON en la tabla genérica `configuracion` (mismo patrón que
    config_red_repo.obtener_gateways): es una lista chica que el Admin
    edita de vez en cuando, no hace falta una tabla nueva.

    Si todavía no se guardó ninguna tabla de tramos (base vieja, de antes
    de 2026-09-30), se arma una de un solo tramo desde monto_minimo 0 con
    el valor de la tarifa única heredada (obtener_tarifa_hora_miembro) --
    así una base ya en uso sigue cobrando exactamente igual hasta que el
    Admin decida agregar más tramos.
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_TRAMOS_TARIFA_MIEMBRO,)
        ).fetchone()
    if fila:
        try:
            tramos = json.loads(fila["valor"])
            if isinstance(tramos, list) and tramos:
                return tramos
        except (ValueError, TypeError):
            pass
    return [{"monto_minimo": 0.0, "tarifa_hora": obtener_tarifa_hora_miembro()}]


def guardar_tramos_tarifa_hora_miembro(tramos: list):
    """Solo el Admin puede llamar a esto (ya se valida en la pantalla, pero
    se repite acá para que este repo nunca dependa de que el llamador se
    acuerde de validar antes -- mismo criterio que el resto de las reglas
    de negocio, que viven en el repo y no en la pantalla)."""
    dominio.validar_tramos_tarifa_hora_miembro(tramos)
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_TRAMOS_TARIFA_MIEMBRO, json.dumps(tramos)),
        )
