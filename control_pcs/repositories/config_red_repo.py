"""
config_red_repo.py
=====================
Catálogo de módems/conexiones a internet del local -- el Cyber tiene
varias en paralelo (ej. dos módems en el mismo rango 192.168.1.x, cada
uno con su propia puerta de enlace: .201 y .202) y a veces se cae uno
solo. Se guarda como JSON en la tabla genérica `configuracion` (clave
"red_gateways", mismo patrón que `config_repo.py` para fondo de cambio y
tarifa de socios) en vez de una tabla nueva -- no hace falta migración
para una lista tan chica que el dueño edita a mano de vez en cuando.

Lo usa el menú "Cambiar red..." de Control de PCs
(`control_pcs/ui/pcs_window.py`) para mandarle a un Cliente PC a qué IP
cambiar su puerta de enlace y DNS (`comandos_pc_repo.TIPO_CAMBIAR_RED`,
ejecutado del lado de la PC cliente por `win32_utils.cambiar_gateway_y_dns`
en el proyecto hermano "CLIENTE PC").
"""

import json
import re

from database import conexion_db

_CLAVE = "red_gateways"
_DEFECTO = [
    {"nombre": "Módem 1", "ip": "192.168.1.201"},
    {"nombre": "Módem 2", "ip": "192.168.1.202"},
]

_PATRON_IPV4 = re.compile(r"^(\d{1,3})\.(\d{1,3})\.(\d{1,3})\.(\d{1,3})$")


def es_ip_valida(ip: str) -> bool:
    """True si `ip` es una IPv4 con cuatro números de 0 a 255 (sin chequear
    que sea alcanzable)."""
    coincidencia = _PATRON_IPV4.match((ip or "").strip())
    if not coincidencia:
        return False
    return all(0 <= int(octeto) <= 255 for octeto in coincidencia.groups())


def obtener_gateways() -> list:
    """Lista de módems conocidos, o los dos de ejemplo del dueño (.201/.202)
    si todavía no se guardó ninguno o la fila quedó corrupta."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE,)
        ).fetchone()
    if not fila:
        return list(_DEFECTO)
    try:
        datos = json.loads(fila["valor"])
        if isinstance(datos, list) and datos:
            return datos
    except (ValueError, TypeError):
        pass
    return list(_DEFECTO)


def guardar_gateways(lista: list):
    """Solo el Operador que edita el catálogo desde `DialogoEditarGateways`
    llama a esto -- ya viene validado (nombre e IP no vacíos, IP con
    formato válido)."""
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE, json.dumps(lista)),
        )
