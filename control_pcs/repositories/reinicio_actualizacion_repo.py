"""
reinicio_actualizacion_repo.py
==============================
Una PC libre que terminó de copiar el Cliente PC nuevo se reinicia sola para ponerlo (pedido del
dueño, 2026-10-28). Hasta ahora la versión copiada se ponía recién en el próximo reinicio de
siempre, el de cada cliente que termina: una PC que la copiaba libre se quedaba con la vieja hasta
que alguien la usara.

Se le manda Reiniciar (`reiniciar_si_corresponde`, en cada GET /estado de esa PC, antes de buscarle
un comando: sale en esa misma respuesta) cuando:
- su Cliente PC dice que ya copió y comprobó la versión que le toca (`act` DESCARGADA con la
  versión de `actualizacion_cliente_repo.version_para_estacion`) y todavía no la tiene puesta. Da
  igual si es un PCcliente.exe o el .zip de una versión en carpeta: la PC lo cuenta igual;
- está libre (`congelado_repo.esta_ocupada`). Con un cliente jugando no se toca: la pone sola en el
  reinicio de siempre, cuando ese cliente termina;
- no está en mantenimiento ("Hacer mantenimiento (15 min)" o el de la "A"): alguien trabaja en la
  PC. Se reinicia cuando termina;
- y no se le mandó ya uno por esa misma versión. Una sola vez por versión: si el reinicio no la
  pone (Shadow Defender borra la copia, o la PC no arranca con Lanzador.exe), la PC la vuelve a
  copiar y se reiniciaría para siempre. Eso ya lo dice "Actualizar el Cliente PC"
  (`actualizacion_cliente_repo.seguir_la_copia`).

Desde que se manda hasta que la PC vuelve, el mosaico la muestra REINICIANDO
(`comandos_pc_repo.reiniciando`). El Reiniciar lleva la versión en el payload
(`comandos_pc_repo.payload_reinicio_por_actualizacion`) y el Cliente PC no lo lee: no hace falta un
Cliente PC nuevo.

Lo que se mira de la PC es lo que contó en su consulta ANTERIOR (`item["estacion"]`, leído antes de
guardar la de ahora): reinicia unos segundos más tarde, y nada más.
"""

import dominio
from control_pcs.repositories import (
    actualizacion_cliente_repo, comandos_pc_repo, congelado_repo, mantenimiento_pc_repo,
)


def reiniciar_si_corresponde(item):
    """Le manda Reiniciar a la PC de `item` (pcs_repo.estado_de_estacion, de antes de esta consulta)
    si ya copió la versión que le toca y está libre (ver el docstring del módulo). Devuelve el id
    del comando, o None si no corresponde."""
    estacion = item["estacion"]
    if estacion["estado_actualizacion"] != dominio.ACTUALIZACION_DESCARGADA:
        return None
    le_toca = actualizacion_cliente_repo.version_para_estacion(estacion["id"])
    if le_toca is None or estacion["version_bajada"] != le_toca or estacion["version_cliente"] == le_toca:
        return None
    # Está preguntando ahora mismo: está enlazada aunque `item` diga otra cosa.
    if congelado_repo.esta_ocupada(item) or mantenimiento_pc_repo.minutos_vigentes(estacion, True):
        return None
    payload = comandos_pc_repo.payload_reinicio_por_actualizacion(le_toca)
    if comandos_pc_repo.existe_comando(estacion["id"], comandos_pc_repo.TIPO_REINICIAR, payload):
        return None
    return comandos_pc_repo.encolar_comando(estacion["id"], comandos_pc_repo.TIPO_REINICIAR, payload)
