"""
anular_carga.py
===============
El cartel para ANULAR UNA CARGA DE SALDO de un socio (pedido del dueño,
2026-11-02: la empleada le cargó dos bonos en vez de uno, el socio quedó con 10 h
en vez de 5 y la caja con $ 16.000 en vez de $ 8.000, y el Admin tiene que poder
rectificar las dos cosas). Lo usan el Historial de Cargas (botón "Anular carga",
solo para el Admin) y Consulta de Ventas (cuando la venta elegida cargó saldo):
las dos hacen lo mismo con miembros_repo.anular_carga, que anula la venta y saca
el tiempo en una sola transacción.

Antes de anular se le muestra al Admin qué va a pasar con la plata y con el
tiempo; si el socio está jugando, que el tiempo se le saca de la PC (sigue
jugando, con menos). Después se le cuenta qué se hizo de verdad (si parte del
tiempo ya lo había usado).
"""

from PySide6.QtWidgets import QInputDialog

import dominio
from control_pcs.repositories import miembros_repo
from ui.utils import confirmar, formato_pesos, manejar_errores, mostrar_aviso, mostrar_error, mostrar_info

TITULO = "Anular carga"


def texto_de_confirmacion(resumen) -> tuple:
    """(texto del cartel, si el tiempo también hay que sacarlo de la PC que el
    socio está usando), a partir de miembros_repo.resumen_de_carga. Si con el
    saldo alcanza para sacar todo el tiempo, se le saca de ahí. Si no, lo que
    falta se le saca de la PC en la que está jugando, y lo que ya no está
    (porque lo usó) se dice."""
    minutos, saldo = resumen["minutos"], resumen["saldo_actual"]
    socio, plata = resumen["socio"], formato_pesos(resumen["monto"])
    texto = (
        "¿Anular esta carga?\n\n"
        f"Socio: {socio}\n"
        f"Carga: {dominio.texto_minutos(minutos)} por {plata} (venta Nº {resumen['venta_id']})\n\n"
        "Se hacen dos cosas juntas:\n"
        f"• La plata: la venta queda ANULADA y esos {plata} salen de la caja y de los reportes. "
        "No se borra: queda quién la anuló, cuándo y por qué.\n"
    )
    en_la_pc = min(minutos - saldo, resumen["minutos_en_la_pc"]) if resumen["estacion"] else 0
    if saldo >= minutos:
        texto += (f"• El tiempo: se le sacan {dominio.texto_minutos(minutos)} del saldo "
                  f"(ahora tiene {dominio.texto_minutos(saldo)}).")
    elif en_la_pc > 0:
        partes = [f"{dominio.texto_minutos(en_la_pc)} de {resumen['estacion']}"]
        if saldo > 0:
            partes.insert(0, f"{dominio.texto_minutos(saldo)} del saldo")
        texto += (
            f"• El tiempo: {socio} está jugando en {resumen['estacion']} (le quedan "
            f"{dominio.texto_minutos(resumen['minutos_en_la_pc'])}). Se le sacan {' y '.join(partes)}: "
            "sigue jugando, pero con menos tiempo."
        )
        resto = minutos - saldo - en_la_pc
        if resto > 0:
            texto += f" Los otros {dominio.texto_minutos(resto)} ya los usó y no se pueden recuperar."
    elif saldo > 0:
        texto += (f"• El tiempo: {socio} tiene ahora {dominio.texto_minutos(saldo)} de saldo y se le saca "
                  f"hasta ahí. Los otros {dominio.texto_minutos(minutos - saldo)} ya los usó y no se pueden recuperar.")
    else:
        texto += (f"• El tiempo: {socio} no tiene saldo ahora, ya usó ese tiempo. No queda nada para sacarle: "
                  "se anula solo la plata.")
    return texto, en_la_pc > 0


def texto_del_resultado(resumen, hecho) -> str:
    """Lo que se hizo de verdad, con lo que devolvió miembros_repo.anular_carga."""
    socio = resumen["socio"]
    texto = (
        "Carga anulada.\n\n"
        f"• Plata: {formato_pesos(resumen['monto'])} fuera de la caja y de los reportes (un cierre de turno "
        "que ya se hizo conserva lo que sumó al cerrar).\n"
    )
    if not hecho["sacados"]:
        texto += f"• Tiempo: no se le sacó nada a {socio}."
    else:
        texto += f"• Tiempo: se le sacaron {dominio.texto_minutos(hecho['sacados'])} a {socio}"
        if hecho["de_la_pc"] and hecho["del_saldo"]:
            texto += (f" ({dominio.texto_minutos(hecho['del_saldo'])} del saldo y "
                      f"{dominio.texto_minutos(hecho['de_la_pc'])} de {hecho['estacion']})")
        elif hecho["de_la_pc"]:
            texto += f", de {hecho['estacion']}, donde sigue jugando"
        texto += "."
    if hecho["sin_sacar"]:
        texto += (f"\n\nOjo: {dominio.texto_minutos(hecho['sin_sacar'])} ya los había usado y no se pudieron "
                  "sacar.")
    return texto


@manejar_errores
def anular_carga_con_cartel(parent, usuario, venta_id: int) -> bool:
    """Anula la carga de saldo de la venta `venta_id` como `usuario` (Admin) y
    cuenta qué pasó. True si se anuló; False si no (cancelaron o no se pudo)."""
    resumen = miembros_repo.resumen_de_carga(venta_id)
    if resumen is None:
        mostrar_error(parent, TITULO, "Esa venta no cargó saldo a ningún socio.")
        return False
    if resumen["anulada"]:
        mostrar_error(parent, "Ya anulada", "Esa carga ya estaba anulada.")
        return False

    texto, sacar_de_la_pc = texto_de_confirmacion(resumen)
    if not confirmar(parent, TITULO, texto):
        return False
    motivo, aceptado = QInputDialog.getText(
        parent, "Motivo de la anulación", "Contá brevemente por qué se anula esta carga:"
    )
    if not aceptado or not motivo.strip():
        mostrar_error(parent, "Falta el motivo", "Tenés que indicar un motivo para anular la carga.")
        return False

    hecho = miembros_repo.anular_carga(venta_id, usuario["id"], motivo.strip(), sacar_de_la_pc=sacar_de_la_pc)
    mensaje = texto_del_resultado(resumen, hecho)
    (mostrar_aviso if hecho["sin_sacar"] else mostrar_info)(parent, TITULO, mensaje)
    return True
