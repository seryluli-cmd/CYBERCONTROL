"""La consulta de un Cliente PC usa la misma cuenta que la grilla."""

from unittest import mock

from base import BaseConBaseTemporal
from control_pcs.repositories import pcs_repo


class TestEstadoIndividual(BaseConBaseTemporal):
    def test_estado_individual_sin_recorrer_toda_la_grilla(self):
        pcs_repo.crear_estacion("PC 1")
        pcs_repo.crear_estacion("PC 2")
        esperado = next(
            item for item in pcs_repo.estado_estaciones()
            if item["estacion"]["nombre"] == "PC 1"
        )

        with mock.patch.object(pcs_repo, "estado_estaciones", side_effect=AssertionError("barrido")):
            actual = pcs_repo.estado_de_estacion("PC 1")

        self.assertEqual(actual["estacion"]["id"], esperado["estacion"]["id"])
        self.assertEqual(actual["sesion"], esperado["sesion"])
        self.assertEqual(actual["enlazada"], esperado["enlazada"])
        self.assertIsNone(pcs_repo.estado_de_estacion("Desconocida"))
