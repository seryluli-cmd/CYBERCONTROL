"""Una marca creada al guardar un artículo debe compartir su transacción."""

import sqlite3

from base import BaseConBaseTemporal
from database import conexion_db
from repositories import articulos_repo


class TestMarcaYArticulo(BaseConBaseTemporal):
    def test_codigo_repetido_no_deja_una_marca_nueva(self):
        articulos_repo.crear_articulo("A1", "Primero", None, None, 10, 5, 0)

        with self.assertRaises(sqlite3.IntegrityError):
            articulos_repo.crear_articulo(
                "A1", "Duplicado", None, None, 10, 5, 0,
                nombre_marca_nueva="Marca que no debe quedar",
            )

        with conexion_db() as conexion:
            marcas = conexion.execute("SELECT nombre FROM marcas").fetchall()
        self.assertEqual(marcas, [])
