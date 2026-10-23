"""
mantenimiento_pc_repo.py
=========================
El mantenimiento de 15 minutos de una PC (el "Hacer mantenimiento" de la "A" del Cliente PC: la
PC queda libre, con el Administrador de tareas habilitado, y se bloquea sola) visto desde el
mostrador (pedido del dueño, 2026-10-22):

- Si una PC está en mantenimiento y cuánto le queda: lo manda cada Cliente PC V1.6 como `mant`
  en su GET /estado (los minutos que le quedan, redondeados para arriba). Se guarda lo último en
  `estaciones.mant_min`, solo si cambió (como temperatura_pc_repo), y vale mientras la PC siga
  enlazada.
- Empezarlo o terminarlo a distancia, desde el clic derecho de la PC, para cualquier operador:
  el comando MANTENIMIENTO con "INICIAR" o "TERMINAR". Empezar es solo con la PC libre (lo
  revisa también el Cliente PC, que contesta error si tiene un cliente).
- Quién lo mandó queda en `mantenimientos_remotos_pc`, y Actividad reciente lo muestra con su
  nombre cuando la PC contestó que lo hizo ("OK: ..."). El de la "A" se sigue viendo como antes
  (EVENTO_ADMIN_MANTENIMIENTO, lo avisa la PC); el de acá, la PC no lo avisa.
"""

from datetime import datetime

import dominio
from database import conexion_db
from control_pcs.repositories import comandos_pc_repo

# Lo que se acepta de una PC: el mantenimiento dura 15 minutos (CLIENTE PC/mantenimiento.py).
_MAXIMO_MINUTOS = 60


def leer_minutos(parametros: dict):
    """Los minutos que mandó la PC en su GET /estado (`mant`), o None si no está en
    mantenimiento (no lo mandó, o mandó algo que no se entiende)."""
    texto = str(parametros.get("mant") or "").strip()
    if not texto.isdigit():
        return None
    minutos = int(texto)
    return minutos if 1 <= minutos <= _MAXIMO_MINUTOS else None


def registrar(estacion_id: int, minutos) -> bool:
    """Guarda los minutos de mantenimiento de esa estación (None = no está), solo si cambiaron.
    Devuelve si los guardó."""
    with conexion_db() as conexion:
        return conexion.execute(
            "UPDATE estaciones SET mant_min = ? WHERE id = ? AND mant_min IS NOT ?",
            (minutos, estacion_id, minutos),
        ).rowcount > 0


def minutos_vigentes(estacion, enlazada: bool):
    """Cuánto le queda al mantenimiento de esa estación, o None si no está en mantenimiento, no
    está enlazada (lo guardado es de cuando todavía preguntaba) o su Cliente PC no lo manda."""
    if not enlazada or "mant_min" not in estacion.keys():
        return None
    return estacion["mant_min"]


def ordenar(estacion_id: int, orden: str, usuario) -> int:
    """Le manda a la PC empezar (MANTENIMIENTO_INICIAR) o terminar (MANTENIMIENTO_TERMINAR) el
    mantenimiento y anota quién (`usuario`, la fila del operador). Devuelve el id del comando,
    para esperar lo que contesta la PC."""
    if orden not in dominio.ORDENES_MANTENIMIENTO:
        raise ValueError(f"Orden de mantenimiento desconocida: {orden}")
    comando_id = comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_MANTENIMIENTO, orden)
    with conexion_db() as conexion:
        conexion.execute(
            """
            INSERT INTO mantenimientos_remotos_pc (comando_id, estacion_id, usuario_id, orden, fecha_hora)
            VALUES (?, ?, ?, ?, ?)
            """,
            (comando_id, estacion_id, usuario["id"] if usuario is not None else None, orden,
             datetime.now().isoformat(timespec="seconds")),
        )
    return comando_id


def listar_recientes(limite: int):
    """Los últimos `limite` mantenimientos mandados desde el mostrador que la PC hizo (contestó
    "OK: ..."), para "Actividad reciente" (actividad_repo): la PC, quién, qué y cuándo."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT m.fecha_hora, m.orden, e.nombre AS estacion_nombre, u.nombre AS usuario_nombre
            FROM mantenimientos_remotos_pc m
            JOIN comandos_pc c ON c.id = m.comando_id
            JOIN estaciones e ON e.id = m.estacion_id
            LEFT JOIN usuarios u ON u.id = m.usuario_id
            WHERE c.resultado LIKE 'OK:%'
            ORDER BY m.fecha_hora DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
