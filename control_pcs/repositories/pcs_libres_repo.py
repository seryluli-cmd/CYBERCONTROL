"""
pcs_libres_repo.py
==================
Las PCs "prendidas y libres": con su Cliente PC conectado y sin ningún cliente
usándolas. Son a las que van los botones DESCONGELAR, REINICIAR y APAGAR de
abajo del mosaico de Control de PCs (pedido del dueño, 2026-10-22; APAGAR el
2026-10-23): lo que se hace con todas a la vez nunca le puede caer a alguien
que está jugando.

Una PC apagada o sin conexión no cuenta: no pediría el comando, y un Reiniciar
o un Apagar que no pidió a tiempo se descarta solo
(comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO).
"""

from control_pcs.repositories import comandos_pc_repo, congelado_repo, pcs_repo


def esta_prendida_y_libre(item) -> bool:
    """¿La PC tiene su Cliente PC conectado y nadie usándola? (un item de
    pcs_repo.estado_estaciones)"""
    return bool(item["enlazada"]) and not congelado_repo.esta_ocupada(item)


def prendidas_y_libres(estados) -> list:
    """Las de `estados` (pcs_repo.estado_estaciones) que están prendidas y libres."""
    return [item for item in estados if esta_prendida_y_libre(item)]


def reiniciar(estacion_ids) -> tuple:
    """Le manda Reiniciar a las PCs de `estacion_ids` que siguen prendidas y
    libres (ver `_mandar`). Devuelve (reiniciadas, salteadas)."""
    return _mandar(estacion_ids, comandos_pc_repo.TIPO_REINICIAR)


def apagar(estacion_ids) -> tuple:
    """Le manda Apagar a las PCs de `estacion_ids` que siguen prendidas y
    libres (ver `_mandar`). Devuelve (apagadas, salteadas)."""
    return _mandar(estacion_ids, comandos_pc_repo.TIPO_APAGAR)


def _mandar(estacion_ids, tipo: str) -> tuple:
    """
    Le manda el comando `tipo` a cada PC de `estacion_ids` que SIGUE prendida y
    libre: se vuelve a mirar acá porque la lista que vio el mostrador al
    preguntar puede tener unos segundos, y en ese rato pudo sentarse un cliente.
    Devuelve (mandadas, salteadas): los nombres de las PCs a las que se les
    mandó y de las que ya no estaban libres o prendidas. Una PC dada de baja en
    el medio no aparece en ninguna de las dos.
    """
    por_id = {item["estacion"]["id"]: item for item in pcs_repo.estado_estaciones()}
    mandadas, salteadas = [], []
    for estacion_id in dict.fromkeys(estacion_ids):
        item = por_id.get(estacion_id)
        if item is None:
            continue
        if esta_prendida_y_libre(item):
            comandos_pc_repo.encolar_comando(estacion_id, tipo)
            mandadas.append(item["estacion"]["nombre"])
        else:
            salteadas.append(item["estacion"]["nombre"])
    return mandadas, salteadas
