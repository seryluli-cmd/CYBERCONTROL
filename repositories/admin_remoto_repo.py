"""
admin_remoto_repo.py
=====================
Las reglas de "entrar desde otra PC del local" (pedido del dueño, 2026-10-18:
desde su casa entra por UltraVNC a una PC libre del local, abre el programa por
la red y administra sin molestar a la operadora del mostrador). Cómo viaja cada
pedido está en el paquete admin_remoto/; acá solo se decide quién entra:

- Viene APAGADO. Lo prende el Administrador desde Configuración ADMIN, en el
  mostrador. Apagarlo corta también a quien ya estaba adentro (el servidor lo
  vuelve a preguntar en cada pedido).
- Solo entra un usuario ADMIN activo, con su clave. Una empleada no entra desde
  otra PC aunque tenga permisos de encargada: lo pidió así el dueño ("el
  Administrador lo voy a usar yo") y es lo que deja chica la puerta.
- Cada ingreso queda en `sesiones` con la IP de la otra PC (`desde_ip`): se ve en
  Accesos de Admin.
"""

import dominio
from database import conexion_db
from repositories import usuarios_repo

_CLAVE_ACTIVO = "admin_remoto_activo"


def esta_activo() -> bool:
    """Si se puede entrar desde otra PC (lo decide el Admin en el mostrador)."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_ACTIVO,)
        ).fetchone()
    return fila is not None and fila["valor"] == "1"


def activar(usuario_id: int, activo: bool):
    """Prende o apaga la entrada desde otra PC. Solo un Administrador
    (PermissionError si no, releyéndolo de la base)."""
    usuarios_repo.exigir_admin(usuario_id, "prender o apagar la entrada desde otra PC")
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_ACTIVO, "1" if activo else "0"),
        )


def administradores_para_entrar() -> list:
    """Los nombres de los Administradores activos, en orden alfabético: es la
    lista que ve la pantalla de ingreso de la otra PC (las empleadas no
    aparecen: no pueden entrar desde ahí)."""
    with conexion_db() as conexion:
        filas = conexion.execute(
            "SELECT nombre FROM usuarios WHERE activo = 1 AND rol = ?", (dominio.ROL_ADMIN,)
        ).fetchall()
    return sorted((fila["nombre"] for fila in filas), key=str.lower)


def entrar(nombre: str, clave: str, desde_ip: str):
    """
    El ingreso de un Administrador desde otra PC: la fila del usuario si el
    nombre es el de un ADMIN activo y la clave es la suya (y queda anotado en
    `sesiones` con `desde_ip`), o None si no. Para una empleada también da
    None, igual que una clave mal puesta: desde otra PC no se distingue "no
    existe" de "no es Admin" (no hay por qué confirmarle a nadie que acertó la
    clave de una empleada).

    PermissionError si la entrada desde otra PC está apagada.
    """
    if not esta_activo():
        raise PermissionError(
            "La entrada desde otra PC está apagada. Prendela desde el mostrador, "
            "en Configuración ADMIN > Entrar desde otra PC."
        )
    with conexion_db() as conexion:
        fila = usuarios_repo._activo_por_nombre(conexion, nombre)
        if fila is None or not dominio.es_admin(fila):
            return None
        if not usuarios_repo._clave_correcta(conexion, fila, clave):
            return None
        usuarios_repo._registrar_sesion(conexion, fila["id"], desde_ip=desde_ip)
        return fila


def exigir_admin_habilitado(usuario_id: int):
    """Lo que el servidor vuelve a preguntar en cada pedido de la otra PC: que
    la entrada siga prendida y que el usuario siga siendo un Administrador
    activo. PermissionError con el motivo, si no."""
    if not esta_activo():
        raise PermissionError("La entrada desde otra PC se apagó en el mostrador.")
    return usuarios_repo.exigir_admin(usuario_id, "administrar desde otra PC")
