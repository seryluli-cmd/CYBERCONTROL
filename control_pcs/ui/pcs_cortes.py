"""
pcs_cortes.py
=============
Los textos de los cortes de las PCs: una PC en uso que titiló "SIN CLIENTE" y volvió sola, con la
causa que anotó el servidor al volver (ver control_pcs/repositories/cortes_pc_repo.py). Se usan en
la línea de "Actividad reciente" (pcs_actividad.py), en el panel de la PC elegida (pcs_detalle.py)
y en el cartelito de su monitor (pcs_window.py).
"""

from collections import Counter
from datetime import datetime

import dominio
from ui.utils import formato_tiempo, formato_transcurrido


def detalle_del_corte(causa: str, segundos: int, fallas) -> str:
    """"estuvo 0m 40s sin noticias: se cortó la comunicación con el mostrador (red), 5 consultas
    sin respuesta". `fallas` solo se dice cuando la causa es la red: es lo que la prueba."""
    texto = dominio.NOMBRE_CAUSA_CORTE_PC[causa]
    if causa == dominio.CORTE_RED and fallas:
        texto += f", {fallas} consulta{'s' if fallas != 1 else ''} sin respuesta"
    return f"estuvo {formato_tiempo(segundos)} sin noticias: {texto}"


def resumen_de_cortes(cortes) -> str:
    """"3 cortes en esta sesión (red ×2, PC reiniciada)", los más repetidos primero."""
    partes = [
        dominio.NOMBRE_CORTO_CAUSA_CORTE_PC[causa] + (f" ×{veces}" if veces > 1 else "")
        for causa, veces in Counter(corte["causa"] for corte in cortes).most_common()
    ]
    cantidad = len(cortes)
    return f"{cantidad} corte{'s' if cantidad != 1 else ''} en esta sesión ({', '.join(partes)})"


def texto_para_el_panel(cortes) -> str:
    """Los cortes de la sesión en curso, para el panel de la PC elegida: cuántos y el último."""
    ultimo = cortes[-1]
    hace = formato_transcurrido(datetime.fromisoformat(ultimo["fecha_hora"]))
    return (f"⚠ {resumen_de_cortes(cortes)}. El último fue hace {hace} y "
            f"{detalle_del_corte(ultimo['causa'], ultimo['segundos'], ultimo['fallas'])}.")
