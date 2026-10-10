"""
pcs_actividad.py
==================
El panel de "Actividad reciente" de la parte de abajo de Control de PCs
(`PanelActividad`): el log de los últimos movimientos -- sesiones y bonos de las
PCs y de la PlayStation 5, saldo de socios, traslados, accesos de admin. Vive
aparte de la grilla (pcs_window.py) para que ese archivo no pase de largo.
"""

from datetime import datetime

from PySide6.QtWidgets import QTextEdit

import dominio
from control_pcs.repositories import pcs_repo
from ui.utils import formato_pesos, formato_tiempo


def _texto_evento(evento) -> str:
    """
    Convierte un evento de pcs_repo.actividad_reciente() en una línea de
    texto para el panel de actividad. El repo devuelve datos crudos; el
    formato ("$ 6.700", "2h 05m") se arma acá porque es un tema de
    presentación, no de negocio.
    """
    hora = datetime.fromisoformat(evento["fecha"]).strftime("%H:%M")
    tipo = evento["tipo"]
    if tipo == "INICIO":
        return f"{hora} — {evento['estacion_nombre']}: sesión iniciada."
    if tipo == "FIN":
        return f"{hora} — {evento['estacion_nombre']}: sesión finalizada."
    if tipo == "BONO":
        return (f"{hora} — {evento['estacion_nombre']}: bono '{evento['bono_nombre']}' "
                f"cobrado ({formato_pesos(evento['precio'])}).")
    if tipo == dominio.MOVIMIENTO_CARGA:
        return f"{hora} — {formato_pesos(evento['monto'])} cargados a {evento['miembro_nombre']}."
    if tipo == dominio.MOVIMIENTO_CONSUMO:
        return (f"{hora} — {evento['miembro_nombre']} abrió {evento['estacion_nombre']} "
                f"con su saldo ({formato_tiempo(evento['minutos'] * 60)}).")
    if tipo == dominio.MOVIMIENTO_REINTEGRO:
        return f"{hora} — {formato_tiempo(evento['minutos'] * 60)} reintegrados a {evento['miembro_nombre']}."
    if tipo == "TRASLADO":
        return f"{hora} — Sesión pasada de {evento['origen_nombre']} a {evento['destino_nombre']}."
    if tipo == "ADMIN_PC":
        texto = f"{hora} — {evento['estacion_nombre']}: {dominio.NOMBRE_EVENTO_ADMIN_PC[evento['evento_admin']]}"
        if evento["segundos_sin_cliente"] is not None:
            texto += f" (estuvo {formato_tiempo(evento['segundos_sin_cliente'])} sin bloqueo)"
        return texto + "."
    return hora


class PanelActividad(QTextEdit):
    """
    Log de los últimos movimientos (sesiones, bonos, saldo de socios) en
    la parte de abajo de la pantalla. De solo lectura: se repuebla entero
    en cada refresco con pcs_repo.actividad_reciente(), no acumula texto
    a mano (así nunca se desincroniza de lo que hay realmente en la base).
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setReadOnly(True)
        self.setFixedHeight(130)

    def actualizar(self):
        eventos = pcs_repo.actividad_reciente()
        lineas = [_texto_evento(evento) for evento in reversed(eventos)]
        self.setPlainText("\n".join(lineas))
        barra = self.verticalScrollBar()
        barra.setValue(barra.maximum())
