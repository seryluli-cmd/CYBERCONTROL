"""
ui/vuelta_del_admin.py
======================
La sesión del Administrador vuelve sola (pedido del dueño, 2026-10-26: entra
como Administrador con "🔄 Operador" para algo rápido y muchas veces se olvida
de volver a cambiar de usuario). Lo arranca la pantalla principal (MainWindow)
solo con el Administrador y solo en el mostrador; desde otra PC no.

- Los minutos (dominio.MINUTOS_ADMIN_VUELVE_SOLO) cuentan desde que entró,
  aunque esté usando el programa.
- dominio.SEGUNDOS_AVISO_VUELTA_ADMIN antes sale el cartel con la cuenta
  regresiva y "SEGUIR COMO ADMIN (10 MIN MÁS)". Si no se toca nada, o se lo
  cierra, vuelve.
- Nunca corta en medio de algo: con una ventana abierta encima (un cobro, un
  artículo a medio editar) el cartel espera a que se cierre, y recién ahí corre
  su minuto. Las que se cierran solas para el cierre forzoso (Ventas con el
  carrito vacío, Caja; ver MainWindow._hay_un_cobro_a_medias) no lo frenan: el
  cartel sale encima y, si vuelve, se cierran igual que ahí.
- A quién vuelve lo decide repositories/vuelta_admin_repo.py: a la empleada que
  estaba antes si su caja sigue abierta a su nombre; si no, a la pantalla de
  ingreso.
"""

import math
import time

from PySide6.QtCore import QObject, Qt, QTimer
from PySide6.QtWidgets import QApplication, QDialog, QHBoxLayout, QLabel, QVBoxLayout

import dominio
from errores import registrar_error
from repositories import vuelta_admin_repo
from ui.piezas_ventana import tecla
from ui.utils import sin_boton_por_defecto

MILISEGUNDOS_ENTRE_REVISIONES = 1000


def _hay_algo_a_medias() -> bool:
    """Si hay una ventana abierta encima que no se puede cerrar sola (ver
    MainWindow._hay_un_cobro_a_medias): ahí el cartel espera."""
    encima = QApplication.activeModalWidget()
    if encima is None:
        return False
    se_puede_cerrar_sola = getattr(encima, "se_puede_cerrar_sola", None)
    return not (se_puede_cerrar_sola is not None and se_puede_cerrar_sola())


class CartelVueltaDelAdmin(QDialog):
    """La cuenta regresiva. Termina aceptado solo con "SEGUIR COMO ADMIN"; a cero,
    con la cruz o con Esc termina rechazado (= vuelve). `destino` es el nombre de
    la empleada a la que vuelve, o None (vuelve la pantalla de ingreso). `reloj` es
    para las pruebas (segundos, como time.monotonic)."""

    def __init__(self, destino, parent=None, reloj=time.monotonic):
        super().__init__(parent)
        self._reloj = reloj
        self._desde = reloj()
        self._destino = destino
        self.setWindowTitle("Administrador")
        self.setModal(True)
        self._armar_interfaz()
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tic)
        self._timer.start(250)
        self._tic()

    def _armar_interfaz(self):
        self.titulo = QLabel()
        self.titulo.setObjectName("tituloVueltaAdmin")
        self.titulo.setAlignment(Qt.AlignCenter)
        self.titulo.setWordWrap(True)
        detalle = QLabel(
            f"Para que no quede abierto el Administrador, el programa vuelve solo a los "
            f"{dominio.MINUTOS_ADMIN_VUELVE_SOLO} minutos de entrar."
        )
        detalle.setObjectName("detalleVueltaAdmin")
        detalle.setAlignment(Qt.AlignCenter)
        detalle.setWordWrap(True)
        self.tecla_seguir = tecla(
            f"SEGUIR COMO ADMIN ({dominio.MINUTOS_ADMIN_VUELVE_SOLO} MIN MÁS)", self.accept, "teclaAzul"
        )

        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(self.tecla_seguir)
        botones.addStretch()

        layout = QVBoxLayout(self)
        layout.setContentsMargins(24, 22, 24, 18)
        layout.setSpacing(12)
        layout.addWidget(self.titulo)
        layout.addWidget(detalle)
        layout.addLayout(botones)
        self.resize(520, 200)
        # Un Enter suelto no tiene que dejar abierto el Administrador.
        sin_boton_por_defecto(self)

    def segundos_que_quedan(self) -> int:
        return max(0, math.ceil(dominio.SEGUNDOS_AVISO_VUELTA_ADMIN - (self._reloj() - self._desde)))

    def _tic(self):
        quedan = self.segundos_que_quedan()
        a_quien = f"VUELVE {self._destino}" if self._destino else "VUELVE LA PANTALLA DE INGRESO"
        self.titulo.setText(f"EN {quedan} SEGUNDOS {a_quien}")
        if quedan == 0:
            self._timer.stop()
            self.reject()


class VueltaDelAdmin(QObject):
    """
    El reloj del Administrador en el mostrador. `volver_a_id` es quien dejó el
    mostrador con "🔄 Operador" antes de que él entrara (o None). Al vencer llama
    a `al_volver(fila)`: la fila de la empleada, con su ingreso ya anotado, o None
    (a la pantalla de ingreso). `hay_un_cobro_a_medias` es el de la pantalla
    principal: cierra lo que se puede cerrar solo y dice si hay que esperar.
    """

    def __init__(self, ventana, volver_a_id, al_volver, hay_un_cobro_a_medias, reloj=time.monotonic):
        super().__init__(ventana)
        self._ventana = ventana
        self._volver_a_id = volver_a_id
        self._al_volver = al_volver
        self._hay_un_cobro_a_medias = hay_un_cobro_a_medias
        self._reloj = reloj
        self._vence = reloj() + dominio.MINUTOS_ADMIN_VUELVE_SOLO * 60
        # Ya pasó el cartel sin "seguir": vuelve apenas no quede nada abierto.
        self._decidido = False
        # El cartel está abierto: el timer sigue andando adentro de su exec().
        self._preguntando = False
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._revisar)
        self._timer.start(MILISEGUNDOS_ENTRE_REVISIONES)

    def detener(self):
        self._timer.stop()

    def _revisar(self):
        if self._preguntando:
            return
        if not self._decidido:
            if self._reloj() < self._vence - dominio.SEGUNDOS_AVISO_VUELTA_ADMIN or _hay_algo_a_medias():
                return
            self._preguntando = True
            try:
                seguir = self._preguntar()
            finally:
                self._preguntando = False
            if seguir:
                self._vence = self._reloj() + dominio.MINUTOS_ADMIN_VUELVE_SOLO * 60
                return
            self._decidido = True
        if self._hay_un_cobro_a_medias():
            return  # se cerró Ventas vacía o Caja (o se abrió algo): se vuelve en la próxima revisión
        self._timer.stop()
        try:
            usuario = vuelta_admin_repo.volver(self._volver_a_id)
        except Exception as error:  # un fallo de la base no puede dejar abierto el Administrador
            registrar_error(error, "Volver sola a la empleada")
            usuario = None
        self._al_volver(usuario)

    def _preguntar(self) -> bool:
        """El cartel con la cuenta regresiva: True si el Administrador sigue."""
        try:
            destino = vuelta_admin_repo.a_quien_volver(self._volver_a_id)
        except Exception as error:
            registrar_error(error, "A quién vuelve el Administrador")
            destino = None
        cartel = CartelVueltaDelAdmin(destino["nombre"] if destino else None, self._ventana, self._reloj)
        return cartel.exec() == QDialog.Accepted
