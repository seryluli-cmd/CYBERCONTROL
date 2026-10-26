"""
ui/vuelta_del_admin.py
======================
La sesión del Administrador vuelve sola (pedido del dueño, 2026-10-26: entra
como Administrador con "🔄 Operador" para algo rápido y muchas veces se olvida
de volver a cambiar de usuario). Lo arranca la pantalla principal (MainWindow)
solo con el Administrador y solo en el mostrador; desde otra PC no.

- A los dominio.MINUTOS_ADMIN_VUELVE_SOLO de entrar, aunque esté usando el
  programa, vuelve en silencio: sin cartel ni aviso (lo pidió así el dueño el
  mismo día; la primera versión avisaba un minuto antes con "SEGUIR COMO ADMIN").
  Para seguir, se vuelve a entrar como Administrador y los minutos arrancan de nuevo.
- Nunca corta en medio de algo: con una ventana abierta encima (un cobro, un
  artículo a medio editar) espera a que se cierre, como el cierre forzoso
  (MainWindow._hay_un_cobro_a_medias: Ventas con el carrito vacío y Caja se
  cierran solas).
- A quién vuelve lo decide repositories/vuelta_admin_repo.py: a la empleada que
  estaba antes si su caja sigue abierta a su nombre; si no, a la pantalla de
  ingreso.
"""

import time

from PySide6.QtCore import QObject, QTimer

import dominio
from errores import registrar_error
from repositories import vuelta_admin_repo

MILISEGUNDOS_ENTRE_REVISIONES = 1000


class VueltaDelAdmin(QObject):
    """
    El reloj del Administrador en el mostrador. `volver_a_id` es quien dejó el
    mostrador con "🔄 Operador" antes de que él entrara (o None). Al vencer llama
    a `al_volver(fila)`: la fila de la empleada, con su ingreso ya anotado, o None
    (a la pantalla de ingreso). `hay_un_cobro_a_medias` es el de la pantalla
    principal: cierra lo que se puede cerrar solo y dice si hay que esperar.
    `reloj` es para las pruebas (segundos, como time.monotonic).
    """

    def __init__(self, ventana, volver_a_id, al_volver, hay_un_cobro_a_medias, reloj=time.monotonic):
        super().__init__(ventana)
        self._volver_a_id = volver_a_id
        self._al_volver = al_volver
        self._hay_un_cobro_a_medias = hay_un_cobro_a_medias
        self._reloj = reloj
        self._vence = reloj() + dominio.MINUTOS_ADMIN_VUELVE_SOLO * 60
        # Vuelve una sola vez: una revisión que ya estaba en la cola al frenar el
        # timer no puede anotar otro ingreso ni abrir otra ventana.
        self._volvio = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._revisar)
        self._timer.start(MILISEGUNDOS_ENTRE_REVISIONES)

    def detener(self):
        self._timer.stop()

    def _revisar(self):
        if self._volvio or self._reloj() < self._vence or self._hay_un_cobro_a_medias():
            return  # ya volvió, todavía no, o hay algo abierto (si se cerró solo, vuelve en la próxima revisión)
        self._volvio = True
        self._timer.stop()
        try:
            usuario = vuelta_admin_repo.volver(self._volver_a_id)
        except Exception as error:  # un fallo de la base no puede dejar abierto el Administrador
            registrar_error(error, "Volver sola a la empleada")
            usuario = None
        self._al_volver(usuario)
