"""
anular_bono.py
==============
El cartel para QUITAR UN BONO vendido de más a una PC o a la consola (pedido del dueño,
2026-11-02: le cargó dos bonos de 5 h a un cliente por error, y el Administrador tiene
que poder dejarlo bien, en el tiempo y en la plata). Lo usan el botón "Quitar un bono"
del panel de la PC (solo el Administrador) y Consulta de Ventas (cuando la venta
elegida vendió un bono): las dos hacen lo mismo con anular_bono_repo.anular_bono, que
anula la venta y le saca el tiempo a la sesión en una sola transacción.

Antes de anular se le muestra al Administrador qué va a pasar con la plata y con el
tiempo; después se le cuenta qué se hizo de verdad (si el cliente ya había usado parte
del tiempo, o la sesión ya se cerró).
"""

from datetime import datetime

from PySide6.QtWidgets import QInputDialog

import dominio
from control_pcs.repositories import anular_bono_repo
from ui.utils import confirmar, formato_pesos, manejar_errores, mostrar_aviso, mostrar_error, mostrar_info

TITULO = "Quitar bono"


def texto_de_confirmacion(resumen) -> str:
    """El cartel de antes de anular, a partir de anular_bono_repo.resumen_de_bono."""
    minutos, en_la_pc = resumen["minutos"], resumen["minutos_en_la_pc"]
    estacion, plata = resumen["estacion"], formato_pesos(resumen["monto"])
    texto = (
        "¿Quitar este bono?\n\n"
        f"{resumen['bono']} ({dominio.texto_minutos(minutos)}) por {plata} en {estacion} "
        f"(venta Nº {resumen['venta_id']})\n\n"
        "Se hacen dos cosas juntas:\n"
        f"• La plata: la venta queda ANULADA y esos {plata} salen de la caja y de los reportes. "
        "No se borra: queda quién la anuló, cuándo y por qué.\n"
    )
    if en_la_pc <= 0:
        texto += (f"• El tiempo: {estacion} no tiene una sesión en curso (ya se cerró o se acabó). "
                  "No queda nada para sacar: se anula solo la plata.")
        return texto
    sacar = min(minutos, en_la_pc)
    quedan = en_la_pc - sacar
    texto += (f"• El tiempo: a {estacion} le quedan {dominio.texto_minutos(en_la_pc)}. "
              f"Se le sacan {dominio.texto_minutos(sacar)}")
    texto += (": se queda sin tiempo." if quedan <= 0
              else f" y sigue con {dominio.texto_minutos(quedan)}.")
    if minutos > sacar:
        texto += f" Los otros {dominio.texto_minutos(minutos - sacar)} ya los usó y no se pueden recuperar."
    return texto


def texto_del_resultado(resumen, hecho) -> str:
    """Lo que se hizo de verdad, con lo que devolvió anular_bono_repo.anular_bono."""
    estacion = hecho["estacion"]
    texto = (
        "Bono quitado.\n\n"
        f"• Plata: {formato_pesos(resumen['monto'])} fuera de la caja y de los reportes (un cierre de turno "
        "que ya se hizo conserva lo que sumó al cerrar).\n"
    )
    if hecho["sacados"]:
        texto += f"• Tiempo: se le sacaron {dominio.texto_minutos(hecho['sacados'])} a {estacion}."
    else:
        texto += f"• Tiempo: no se le sacó nada a {estacion}."
    if hecho["sin_sacar"]:
        texto += (f"\n\nOjo: {dominio.texto_minutos(hecho['sin_sacar'])} ya los había usado (o la sesión ya "
                  "terminó) y no se pudieron sacar.")
    return texto


def _renglon(bono) -> str:
    """Cómo se ve un bono en la lista para elegir: la hora, qué bono, y el número de venta
    (que además lo distingue de otro igual vendido en el mismo minuto)."""
    hora = datetime.fromisoformat(bono["fecha"])
    return (f"{hora:%d/%m %H:%M} · {bono['bono']} ({dominio.texto_minutos(bono['minutos'])}) · "
            f"{formato_pesos(bono['monto'])} · venta Nº {bono['venta_id']}")


def elegir_bono_a_quitar(parent, equipo: str, bonos: list):
    """Pregunta cuál de los bonos de la sesión de `equipo` hay que quitar. El número de venta del
    elegido, o None si no hay ninguno o canceló. `bonos` viene de anular_bono_repo.bonos_de_la_sesion."""
    if not bonos:
        mostrar_aviso(parent, TITULO, f"{equipo} no tiene bonos en su sesión actual.\n\nSi el bono se vendió en una "
                                      "sesión que ya terminó, anulá la venta desde Consulta de Ventas.")
        return None
    renglones = {_renglon(bono): bono["venta_id"] for bono in bonos}
    elegido, aceptado = QInputDialog.getItem(
        parent, TITULO, f"Bonos de la sesión de {equipo} (el más nuevo primero).\n¿Cuál se quita?",
        list(renglones), 0, False,
    )
    return renglones[elegido] if aceptado and elegido in renglones else None


@manejar_errores
def anular_bono_con_cartel(parent, usuario, venta_id: int) -> bool:
    """Quita el bono que vendió la venta `venta_id` como `usuario` (Administrador) y cuenta
    qué pasó. True si se anuló; False si no (cancelaron o no se pudo)."""
    resumen = anular_bono_repo.resumen_de_bono(venta_id)
    if resumen is None:
        mostrar_error(parent, TITULO, "Esa venta no vendió ningún bono de PC ni de la consola.")
        return False
    if resumen["anulada"]:
        mostrar_error(parent, "Ya anulada", "Esa venta ya estaba anulada.")
        return False
    if resumen["de_reserva"]:
        mostrar_error(parent, TITULO, "Ese bono salió de una reserva: se deshace desde Reservas, no desde acá.")
        return False

    if not confirmar(parent, TITULO, texto_de_confirmacion(resumen)):
        return False
    motivo, aceptado = QInputDialog.getText(
        parent, "Motivo de la anulación", "Contá brevemente por qué se quita este bono:"
    )
    if not aceptado or not motivo.strip():
        mostrar_error(parent, "Falta el motivo", "Tenés que indicar un motivo para quitar el bono.")
        return False

    hecho = anular_bono_repo.anular_bono(venta_id, usuario["id"], motivo.strip())
    (mostrar_aviso if hecho["sin_sacar"] else mostrar_info)(parent, TITULO, texto_del_resultado(resumen, hecho))
    return True
