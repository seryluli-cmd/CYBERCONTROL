"""Los fallos de red se registran en el directorio de datos vigente."""

from pathlib import Path

from base import BaseConBaseTemporal
import database
from errores import registrar_error


class TestRegistroDeErrores(BaseConBaseTemporal):
    def test_registra_contexto_sin_perder_la_traza(self):
        try:
            raise RuntimeError("falló la consulta")
        except RuntimeError as error:
            registrar_error(error, "Servidor de red: leer estado de PC")

        contenido = (Path(database.DATA_DIR) / "errores.log").read_text(encoding="utf-8")
        self.assertIn("Servidor de red: leer estado de PC", contenido)
        self.assertIn("RuntimeError: falló la consulta", contenido)
