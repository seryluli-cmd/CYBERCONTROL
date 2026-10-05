"""
catalogo_bonos.py
===================
La mecánica de un catálogo de bonos de tiempo prearmados ("3 horas" ->
180 min / $X): listar, buscar, crear, modificar y dar de baja.

Hay DOS catálogos con este mismo esquema, deliberadamente separados (tabla,
quién los usa y cómo se cobran): `bonos_tiempo`, para cualquiera que entra al
local sin ser socio (`pcs_repo`), y `bonos_miembro`, exclusivo de socios
(`bonos_miembro_repo`). Ver CLAUDE.md, "Hay DOS catálogos de bonos": no se
fusionan. Lo único que se comparte acá es el código; cada repo instancia
`CatalogoDeBonos` con SU tabla y expone las funciones públicas de siempre
(`listar_bonos`, `obtener_bono`, ...), así que ninguna pantalla se entera.
"""

import dominio
from database import conexion_db


class CatalogoDeBonos:
    """Un catálogo de bonos sobre una tabla con (id, nombre, minutos, precio, activo)."""

    def __init__(self, tabla: str):
        # Nombre fijo que pone cada repo (nunca un dato de la usuaria), por
        # eso es seguro armarlo dentro del SQL.
        self._tabla = tabla

    def listar(self, solo_activos: bool = True):
        """Los bonos ordenados por duración; por defecto solo los activos."""
        with conexion_db() as conexion:
            if solo_activos:
                return conexion.execute(
                    f"SELECT * FROM {self._tabla} WHERE activo = 1 ORDER BY minutos"
                ).fetchall()
            return conexion.execute(f"SELECT * FROM {self._tabla} ORDER BY minutos").fetchall()

    def obtener(self, bono_id: int):
        """La fila de un bono (activo o no), o None si no existe."""
        with conexion_db() as conexion:
            return conexion.execute(
                f"SELECT * FROM {self._tabla} WHERE id = ?", (bono_id,)
            ).fetchone()

    def crear(self, nombre: str, minutos: int, precio: float) -> int:
        """Da de alta un bono y devuelve su id. Levanta ValueError (mensaje
        listo para mostrar) si el nombre, los minutos o el precio no valen
        -- ver dominio.validar_datos_bono."""
        dominio.validar_datos_bono(nombre, minutos, precio)
        with conexion_db() as conexion:
            cursor = conexion.execute(
                f"INSERT INTO {self._tabla} (nombre, minutos, precio) VALUES (?, ?, ?)",
                (nombre.strip(), minutos, round(precio, 2)),
            )
            return cursor.lastrowid

    def modificar(self, bono_id: int, nombre: str, minutos: int, precio: float):
        """Cambia nombre, minutos y precio de un bono (mismas validaciones
        que `crear`)."""
        dominio.validar_datos_bono(nombre, minutos, precio)
        with conexion_db() as conexion:
            conexion.execute(
                f"UPDATE {self._tabla} SET nombre = ?, minutos = ?, precio = ? WHERE id = ?",
                (nombre.strip(), minutos, round(precio, 2), bono_id),
            )

    def desactivar(self, bono_id: int):
        """Da de baja un bono: no se borra (las ventas o cargas que ya lo
        usaron lo siguen referenciando), solo deja de ofrecerse."""
        with conexion_db() as conexion:
            conexion.execute(f"UPDATE {self._tabla} SET activo = 0 WHERE id = ?", (bono_id,))
