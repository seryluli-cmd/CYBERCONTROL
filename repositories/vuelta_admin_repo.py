"""
vuelta_admin_repo.py
=====================
La sesión del Administrador vuelve sola a la empleada (pedido del dueño,
2026-10-26): el dueño entra como Administrador con "🔄 Operador" para algo
rápido y muchas veces se olvida de volver a cambiar de usuario, y el programa
quedaba abierto como Administrador, con todo habilitado. A los
dominio.MINUTOS_ADMIN_VUELVE_SOLO la pantalla principal del mostrador vuelve a la
empleada que estaba antes (el reloj y el cartel están en ui/vuelta_del_admin.py);
acá se decide SI se puede volver a ella:

- tiene que seguir activa y no ser Admin;
- su caja tiene que seguir abierta a su nombre y en hora (la situación SU_CAJA
  de relevo_repo, la misma con que entra sin que le pregunten nada). Si en esos
  minutos su caja se cerró (cierre forzoso, o la cerró el dueño), la recibió otra
  o su turno ya venció, no se vuelve a ella: se va a la pantalla de ingreso, donde
  se entra contando lo que haga falta. Volver sola nunca se saltea un conteo.

La vuelta queda en `sesiones` como un ingreso de ella, igual que si hubiera
entrado con su clave: ese historial dice quién estuvo en el mostrador (lo usa,
por ejemplo, turnos_faltantes_repo._responsables_del_mes).
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import relevo_repo, usuarios_repo


def _se_puede_volver(conexion, usuario_id, ahora: datetime):
    """La fila de `usuario_id` si ahora se puede volver a ella, o None."""
    if usuario_id is None:
        return None
    usuario = conexion.execute("SELECT * FROM usuarios WHERE id = ? AND activo = 1", (usuario_id,)).fetchone()
    if usuario is None or dominio.es_admin(usuario):
        return None
    if relevo_repo._situacion(conexion, usuario, ahora)["situacion"] != relevo_repo.SITUACION_SU_CAJA:
        return None
    return usuario


def a_quien_volver(usuario_id, ahora: datetime = None):
    """Para el cartel de la cuenta regresiva: la empleada a la que se volvería
    ahora, o None (se iría a la pantalla de ingreso). No anota nada."""
    with conexion_db() as conexion:
        return _se_puede_volver(conexion, usuario_id, ahora or datetime.now())


def volver(usuario_id, ahora: datetime = None):
    """
    Vuelve a `usuario_id`: si todavía se puede, anota su ingreso y devuelve su
    fila; si no, None y no anota nada. Se vuelve a mirar acá, en la misma
    transacción que anota el ingreso, porque entre el cartel y la vuelta pasó
    un minuto (y pudo cerrarse su caja).
    """
    with conexion_db() as conexion:
        usuario = _se_puede_volver(conexion, usuario_id, ahora or datetime.now())
        if usuario is not None:
            usuarios_repo._registrar_sesion(conexion, usuario["id"])
        return usuario
