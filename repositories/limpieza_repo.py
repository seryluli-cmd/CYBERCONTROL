"""
limpieza_repo.py
==================
"LIMPIAR BASE DE DATOS" (Configuración ADMIN): borra TODO lo que es plata e
historial de ventas y deja todo lo que es catálogo. Pedido del dueño
(2026-10-17) para la etapa de pruebas: simula ventas, mira cómo quedan Caja,
Cierre de Turno y Reportes, y quiere volver a empezar de cero sin perder lo que
ya cargó. No es para usar con el local funcionando de verdad.

Es la ÚNICA excepción a "nada se borra, se marca" (CLAUDE.md, regla 7), y por
eso tiene sus propios resguardos:
- Solo un Admin, controlado acá (se relee el usuario de la base, como en
  playstation_repo), no solo escondiendo el botón.
- Antes de borrar se hace una copia completa de la base en data/backups/
  ("antes_de_limpiar_base_..."; el prefijo "antes_de_" hace que la rotación de
  backups diarios no la toque). Si la copia no se puede hacer, NO se borra nada.
- Todo se borra en UNA transacción: o queda limpia, o queda como estaba.

Qué se borra (_TABLAS_A_VACIAR): ventas con su detalle y sus pagos, cobros de
trámites, cierres de turno, sesiones de las PCs y de la PlayStation 5 con sus
bonos vendidos y sus traslados, y el historial de saldo de los socios. Además
cada socio queda con saldo 0 (su saldo se cargó con ventas que se borran) y a
cada artículo se le devuelve el stock que se llevaron las ventas confirmadas
(como si esas ventas no hubieran pasado; las anuladas ya lo habían devuelto).

Qué queda: usuarios, artículos (con marcas y rubros), compras, los cuatro
catálogos de bonos, estaciones, socios (sus datos, no el saldo), trámites (el
catálogo), configuración (fondo de cambio, tarifa de socios, filtro de
palabras...), y los historiales que no son plata: inicios de sesión, accesos de
admin de las PCs, comandos enviados a las PCs y páginas que cerró el filtro de
palabras.
"""

import os
from datetime import datetime

import database
import dominio
from database import conexion_db
from repositories import usuarios_repo

# En este orden: primero las tablas que apuntan a otras (las claves foráneas
# están prendidas, y SQLite no deja borrar una venta que todavía tiene pagos).
_TABLAS_A_VACIAR = (
    "venta_pagos",
    "venta_detalle",
    "tramites_venta",
    "sesion_bonos",
    "sesion_pcstream_bonos",
    "sesion_playstation_bonos",
    "movimientos_saldo_miembro",
    "traslados_sesion",
    "sesiones_pc",
    "sesiones_playstation",
    "cierres_turno",
    "ventas",
)


def _exigir_admin(usuario_id: int):
    usuario = usuarios_repo.obtener_usuario(usuario_id)
    if usuario is None or not usuario["activo"] or not dominio.es_admin(usuario):
        raise PermissionError("Solo un Administrador puede limpiar la base de datos.")


def contar_lo_que_se_borraria() -> dict:
    """{tabla: cantidad de filas} de lo que borraría limpiar_base(), para que la
    pantalla muestre cuánto hay antes de confirmar. Solo lee."""
    with conexion_db() as conexion:
        return {
            tabla: conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]
            for tabla in _TABLAS_A_VACIAR
        }


def limpiar_base(usuario_id: int) -> dict:
    """
    Borra la plata y el historial de ventas (ver el comentario del módulo) y
    devuelve {"copia": ruta de la copia de seguridad, "ventas": cuántas ventas
    se borraron, "cierres": cuántos cierres, "sesiones": cuántas sesiones de PC
    y de la consola, "socios_en_cero": a cuántos socios se les puso el saldo en 0}.

    PermissionError si `usuario_id` no es un Admin activo; OSError o
    sqlite3.Error si no se pudo hacer la copia (y entonces no se borró nada).
    Las sesiones en curso también se borran: las PCs que estaban habilitadas
    vuelven a bloquearse y la PlayStation 5 queda libre.
    """
    _exigir_admin(usuario_id)

    # La copia va ANTES de la transacción y sin atrapar errores: si falla, se
    # corta acá y no se borra nada.
    copia = os.path.join(
        database.DATA_DIR, "backups",
        f"antes_de_limpiar_base_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db",
    )
    database._backup_consistente(copia)

    with conexion_db() as conexion:
        # Toma el permiso de escritura de entrada: el servidor de red (logins de
        # socios desde las PCs) no puede meter una sesión nueva a mitad de la limpieza.
        conexion.execute("BEGIN IMMEDIATE")
        cantidades = {
            tabla: conexion.execute(f"SELECT COUNT(*) AS n FROM {tabla}").fetchone()["n"]
            for tabla in _TABLAS_A_VACIAR
        }

        # El stock que se llevaron las ventas confirmadas vuelve a su artículo.
        conexion.execute(
            """
            UPDATE articulos
            SET stock = stock + (
                SELECT SUM(venta_detalle.cantidad)
                FROM venta_detalle
                JOIN ventas ON ventas.id = venta_detalle.venta_id
                WHERE ventas.estado = ? AND venta_detalle.articulo_codigo = articulos.codigo
            )
            WHERE codigo IN (
                SELECT venta_detalle.articulo_codigo
                FROM venta_detalle
                JOIN ventas ON ventas.id = venta_detalle.venta_id
                WHERE ventas.estado = ?
            )
            """,
            (dominio.VENTA_CONFIRMADA, dominio.VENTA_CONFIRMADA),
        )
        socios_en_cero = conexion.execute(
            "UPDATE miembros SET saldo_minutos = 0 WHERE saldo_minutos <> 0"
        ).rowcount

        for tabla in _TABLAS_A_VACIAR:
            conexion.execute(f"DELETE FROM {tabla}")
        # Que los números vuelvan a empezar desde 1 (la primera venta de prueba
        # nueva es la Nº 1, no la 348).
        conexion.execute(
            f"DELETE FROM sqlite_sequence WHERE name IN ({', '.join('?' for _ in _TABLAS_A_VACIAR)})",
            _TABLAS_A_VACIAR,
        )

    return {
        "copia": copia,
        "ventas": cantidades["ventas"],
        "cierres": cantidades["cierres_turno"],
        "sesiones": cantidades["sesiones_pc"] + cantidades["sesiones_playstation"],
        "socios_en_cero": socios_en_cero,
    }
