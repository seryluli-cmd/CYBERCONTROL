"""
usuarios_repo.py
=================
"Repositorio" de usuarios: todas las funciones que leen o escriben en la
tabla `usuarios`. El resto del programa (pantallas, lógica de login) usa
estas funciones en vez de escribir SQL directamente, así si algún día
cambia cómo se guardan los usuarios, solo hay que tocar este archivo.
"""

from datetime import datetime
from database import conexion_db, hash_clave, verificar_clave


def autenticar(usuario_id: int, clave: str):
    """
    Intenta loguear a un usuario. Devuelve la fila del usuario si el
    número de usuario y la clave coinciden (y el usuario está activo),
    o None si no coincide algo.

    Si la clave guardada todavía está en el formato viejo (sin salt, de
    antes de este cambio), y el login es correcto, se migra sola al
    formato nuevo en el momento — así todos los usuarios van quedando
    con el hash más seguro a medida que usan el sistema, sin que nadie
    tenga que reconfigurar nada a mano.

    Cada login exitoso también queda registrado en `sesiones` — es la
    pista que usa Control de Cierres de Turno para saber quién podría
    ser responsable de un turno sin cerrar, incluso si no vendió nada
    en esa ventana (ver turnos_repo._responsables_del_mes).
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT * FROM usuarios WHERE id = ? AND activo = 1", (usuario_id,)
        ).fetchone()

        if fila is None:
            return None
        if not verificar_clave(clave, fila["clave_hash"]):
            return None

        if "$" not in fila["clave_hash"]:
            conexion.execute(
                "UPDATE usuarios SET clave_hash = ? WHERE id = ?",
                (hash_clave(clave), fila["id"]),
            )

        conexion.execute(
            "INSERT INTO sesiones (usuario_id, fecha_hora) VALUES (?, ?)",
            (fila["id"], datetime.now().isoformat(timespec="seconds")),
        )

        return fila


def listar_usuarios(incluir_inactivos: bool = False):
    """Devuelve todos los usuarios, para la pantalla de Administración."""
    with conexion_db() as conexion:
        if incluir_inactivos:
            return conexion.execute("SELECT * FROM usuarios ORDER BY nombre").fetchall()
        return conexion.execute(
            "SELECT * FROM usuarios WHERE activo = 1 ORDER BY nombre"
        ).fetchall()


def obtener_usuario(usuario_id: int):
    with conexion_db() as conexion:
        return conexion.execute(
            "SELECT * FROM usuarios WHERE id = ?", (usuario_id,)
        ).fetchone()


def crear_usuario(nombre: str, clave: str, rol: str):
    """Crea un nuevo usuario (Admin o Empleada) y devuelve su id."""
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO usuarios (nombre, clave_hash, rol, activo, fecha_creacion)
            VALUES (?, ?, ?, 1, ?)
            """,
            (nombre, hash_clave(clave), rol, ahora),
        )
        return cursor.lastrowid


def modificar_usuario(usuario_id: int, nombre: str, rol: str, clave: str = None):
    """
    Actualiza nombre y rol de un usuario. Si se pasa una clave nueva
    (no vacía), también la actualiza; si no, deja la clave como estaba.
    """
    with conexion_db() as conexion:
        if clave:
            conexion.execute(
                "UPDATE usuarios SET nombre = ?, rol = ?, clave_hash = ? WHERE id = ?",
                (nombre, rol, hash_clave(clave), usuario_id),
            )
        else:
            conexion.execute(
                "UPDATE usuarios SET nombre = ?, rol = ? WHERE id = ?",
                (nombre, rol, usuario_id),
            )


def desactivar_usuario(usuario_id: int):
    """
    No borramos usuarios físicamente (para no perder el historial de
    ventas/compras/cierres que hicieron): los marcamos como inactivos,
    y así dejan de poder loguearse pero su historial queda intacto.
    """
    with conexion_db() as conexion:
        conexion.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (usuario_id,))
