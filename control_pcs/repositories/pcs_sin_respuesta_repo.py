"""
pcs_sin_respuesta_repo.py
===========================
El aviso antes de cerrar la sesión de una PC que no responde (pedido del dueño,
2026-11-09, eligió la maqueta B de PROPUESTA_AVISO_PC_SIN_RESPUESTA).

El 02/11 se cortó la red del mostrador, cuatro PCs en uso titilaron "SIN CLIENTE"
y se les cerró la sesión con "Finalizar Sesión". Sin red, cada PC sigue contando
sola y al volver sigue con su tiempo (ver docs/TIEMPO_DE_LAS_PCS.md): lo que les
sacó el tiempo fue el cierre. Cuando volvió la red, el mostrador les contestó "sin
sesión" y se reiniciaron. Por eso "Finalizar Sesión" y "Cerrar sesión y reiniciar"
avisan antes, con lo que pierde el cliente y, si se cortaron varias a la vez, que
seguramente es la red del mostrador. No impiden cerrar: una PC que el cliente apagó
al irse también se ve "SIN CLIENTE", y esa sí hay que cerrarla.

La pantalla es control_pcs/ui/pcs_aviso_sin_respuesta.py.
"""

from datetime import datetime

from control_pcs.repositories import pcs_repo

# Dos PCs que dejaron de responder con menos de esto de diferencia se cortaron "a la
# vez": un corte de la red del mostrador las deja sin noticias en la misma consulta
# (cada PC pregunta cada 5 s); dos clientes que apagan su PC al irse, casi nunca.
SEGUNDOS_MISMO_CORTE = 60


def no_responde(item) -> bool:
    """La PC tiene una sesión en curso y su Cliente PC dejó de preguntar: la que el
    mosaico muestra "SIN CLIENTE" (pcs_window._ficha_de_pc). No cuenta la que todavía
    no se prendió desde que se le vendió el bono ("Esperando al cliente": cerrarla no
    le saca nada a nadie) ni la que tiene el Cliente PC cerrado desde su panel admin
    (está en mantenimiento, sin bloqueo, y ya se ve como tal)."""
    return (item.get("sesion") is not None
            and not item["enlazada"]
            and not item["esperando_cliente"]
            and item["cliente_cerrado_admin_desde"] is None)


def aviso_antes_de_cerrar(estacion_id: int, ahora: datetime = None):
    """
    Qué decir antes de cerrar la sesión de esa PC, o None si la PC responde (se
    pregunta lo de siempre).

    {"estacion_nombre", "segundos_sin_noticias", "segundos_restantes",
    "cortadas_a_la_vez"}: hace cuánto no pregunta, lo que el cliente pierde si se la
    cierra y cuántas PCs en uso dejaron de responder a la vez que ella, contándola
    (si son dos o más, seguramente es la red del mostrador).
    """
    ahora = ahora or datetime.now()
    estados = pcs_repo.estado_estaciones()
    item = next((i for i in estados if i["estacion"]["id"] == estacion_id), None)
    if item is None or not no_responde(item):
        return None
    ultima = item["ultima_conexion"]
    cortadas = 1
    if ultima is not None:
        cortadas = sum(
            1 for otro in estados
            if no_responde(otro) and otro["ultima_conexion"] is not None
            and abs((otro["ultima_conexion"] - ultima).total_seconds()) <= SEGUNDOS_MISMO_CORTE
        )
    return {
        "estacion_nombre": item["estacion"]["nombre"],
        "segundos_sin_noticias": None if ultima is None else max(0, int((ahora - ultima).total_seconds())),
        "segundos_restantes": item["segundos_restantes"],
        "cortadas_a_la_vez": cortadas,
    }
