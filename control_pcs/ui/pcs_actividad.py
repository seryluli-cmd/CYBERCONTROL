"""
pcs_actividad.py
==================
El panel de "Actividad reciente" de la parte de abajo de Control de PCs
(`PanelActividad`): el log de los últimos movimientos -- sesiones y bonos de las
PCs y de la PlayStation 5, saldo de socios, traslados, accesos de admin, páginas
que cerró el filtro de palabras y PCs que titilaron "SIN CLIENTE" y volvieron
(con la causa, ver pcs_cortes.py). Vive
aparte de la grilla (pcs_window.py) para que ese archivo no pase de largo.
"""

from datetime import datetime

from PySide6.QtWidgets import QTextEdit

import dominio
from control_pcs.repositories import pcs_repo, reinicios_pc_repo
from control_pcs.ui.pcs_cortes import detalle_del_corte
from ui.utils import formato_pesos, formato_tiempo


def texto_del_reinicio(evento) -> str:
    """"el Cliente PC la reinició por la orden Reiniciar del mostrador" (ver
    reinicios_pc_repo): `evento` trae "motivo" y "segundos_quedaban"."""
    motivo = evento["motivo"]
    if motivo == dominio.REINICIO_ORDEN_REINICIAR:
        return "el Cliente PC la reinició por la orden Reiniciar del mostrador"
    if motivo == dominio.REINICIO_ORDEN_APAGAR:
        return "el Cliente PC la apagó por la orden Apagar del mostrador"
    if motivo == dominio.REINICIO_DESCONGELAR:
        return "el Cliente PC la reinició para descongelarla (Shadow Defender)"
    if motivo == dominio.REINICIO_TIEMPO_SIN_CONEXION:
        return "el Cliente PC la reinició: se le terminó el tiempo estando sin conexión con el mostrador"
    quedaban = evento["segundos_quedaban"]
    if quedaban is not None and quedaban > reinicios_pc_repo.SEGUNDOS_DE_FIN_NORMAL:
        return (f"el Cliente PC la reinició porque el mostrador dio la sesión por terminada cuando, según "
                f"la PC, le quedaban {formato_tiempo(quedaban)} (se cerró, se finalizó o se pasó a otra PC)")
    return "el Cliente PC la reinició porque se terminó el tiempo de la sesión"


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
    if tipo == "RESERVA":
        return (f"{hora} — {evento['estacion_nombre']}: reserva Nº {evento['numero']} de {evento['cliente']} "
                f"habilitada ({evento['bono_nombre']}).")
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
    if tipo == "FILTRO":
        return (f"{hora} — {evento['estacion_nombre']}: el filtro cerró una página con "
                f"\"{evento['palabra']}\" ({titulo_corto(evento['titulo'])}).")
    if tipo == "CORTE":
        texto = (f"{hora} — {evento['estacion_nombre']}: "
                 f"{detalle_del_corte(evento['causa'], evento['segundos'], evento['fallas'])}")
        if evento.get("reinicio_pedido") is True:
            texto += " (la reinició el Cliente PC)"
        elif evento.get("reinicio_pedido") is False:
            texto += (" SIN que la reiniciara el Cliente PC: corte de luz, cuelgue o pantalla azul, "
                      "Windows Update o alguien con el botón")
        return texto + "."
    if tipo == "REINICIO":
        return f"{hora} — {evento['estacion_nombre']}: {texto_del_reinicio(evento)}."
    if tipo == "AJUSTE_TIEMPO":
        return (f"{hora} — {evento['estacion_nombre']}: volvió la conexión y se tomó el tiempo de la PC, "
                f"que era menor: le quedaban {formato_tiempo(evento['segundos_pc'])} "
                f"(el mostrador decía {formato_tiempo(evento['segundos_mostrador'])}).")
    return hora


def titulo_corto(titulo: str, largo: int = 60) -> str:
    """El título de la página que cerró el filtro, cortado para que entre en un
    renglón (el completo se ve en la pantalla del filtro)."""
    return titulo if len(titulo) <= largo else titulo[:largo - 1] + "…"


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
