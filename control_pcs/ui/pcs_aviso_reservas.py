"""
pcs_aviso_reservas.py
======================
El aviso de arriba del mosaico de Control de PCs con las reservas de
"Cualquier PC disponible" (parte 2 de las reservas, pedido del dueño
2026-10-20, maqueta 7 de PROPUESTA_RESERVAS): esas no apartan ninguna PC, así
que en vez de pintar una se avisa quién viene, a qué hora y cuántas PCs hay
libres para dársela. Se esconde si no hay ninguna a la vista (2 h antes).
Qué reservas y cuántas PCs libres lo decide reservas_horario_repo.
"""

from datetime import datetime

from PySide6.QtWidgets import QLabel

from control_pcs.repositories import reservas_horario_repo


class AvisoDeReservasSinPcFija(QLabel):
    """Recuadro claro con letra azul (estilo "#avisoReservasMosaico" en main.py)."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("avisoReservasMosaico")
        self.setWordWrap(True)
        self.setVisible(False)

    def actualizar(self, reservas, estados):
        """`reservas`: reservas_horario_repo.reservas_para_la_grilla(); `estados`:
        pcs_repo.estado_estaciones(), para contar las PCs libres."""
        sin_pc = reservas_horario_repo.sin_pc_fija(reservas)
        self.setVisible(bool(sin_pc))
        if not sin_pc:
            return
        ahora = datetime.now()
        quienes = ", ".join(
            f"{reserva['cliente']} · {reservas_horario_repo.texto_de_la_hora(reserva['inicio'], ahora)}"
            for reserva in sin_pc
        )
        titulo = "Reserva sin PC fija" if len(sin_pc) == 1 else "Reservas sin PC fija"
        self.setText(
            f"📅 {titulo}: {quienes} · cualquier PC disponible"
            f"      (libres ahora: {reservas_horario_repo.pcs_libres(estados)})"
        )
