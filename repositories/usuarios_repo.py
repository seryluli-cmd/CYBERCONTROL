"""
usuarios_repo.py
=================
"Repositorio" de usuarios: todas las funciones que leen o escriben en la
tabla `usuarios`. El resto del programa (pantallas, lógica de login) usa
estas funciones en vez de escribir SQL directamente, así si algún día
cambia cómo se guardan los usuarios, solo hay que tocar este archivo.
"""

import sqlite3
from datetime import datetime
import dominio
from database import conexion_db, hash_clave, verificar_clave

# (columna en `usuarios`, etiqueta para mostrar en la UI) de cada
# permiso que un Admin puede sumarle a una empleada además de lo que ya
# puede hacer por defecto (Ventas / operar la grilla de PCs / Caja /
# Cierre de Turno / Cambiar mi Clave — asignarle un bono a una PC es una
# venta más, no un privilegio). Un ADMIN los tiene todos siempre — ver
# tiene_permiso() — y no se le pueden sacar desde acá. "Usuarios"
# (crear/borrar gente, resetear claves) y "Anular Venta" quedan
# exclusivos de ADMIN a propósito, no están en esta lista. Todos estos
# permisos son lo que separa a un "encargado" de un empleado común en
# ui/main_window.py: quien tenga al menos uno ve "Administrar Kiosko".
PERMISOS_EMPLEADA = [
    ("permiso_articulos", "Artículos (crear/editar productos y precios)"),
    ("permiso_compras", "Compras (cargar mercadería / stock)"),
    ("permiso_consulta_ventas", "Consulta de Ventas (sin poder anular)"),
    ("permiso_reportes", "Reportes"),
    ("permiso_control_cierres", "Control de Cierres de Turno"),
    ("permiso_control_pcs", "Operar PCs y Miembros (asignar bonos, abrir con socio, cargar saldo)"),
]


def tiene_permiso(usuario, clave_permiso: str) -> bool:
    """
    True si `usuario` (una fila de la tabla usuarios, por ejemplo la
    que devuelve el login) puede usar la pantalla asociada a
    `clave_permiso` (una de las claves de PERMISOS_EMPLEADA). Un ADMIN
    siempre puede, pase lo que pase en sus columnas permiso_*.
    """
    if dominio.es_admin(usuario):
        return True
    return bool(usuario[clave_permiso])


def _validar_credenciales_y_registrar_sesion(conexion, fila, clave: str):
    """
    Núcleo común de autenticar()/autenticar_por_nombre(): valida la
    clave contra el hash guardado (migrando el formato legacy si hace
    falta) y, si es correcta, registra la sesión exitosa en `sesiones`
    — es la pista que usa Control de Cierres de Turno para saber quién
    podría ser responsable de un turno sin cerrar, incluso si no
    vendió nada en esa ventana (ver turnos_repo._responsables_del_mes).
    Devuelve la fila del usuario si todo coincide, o None si no.
    """
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


def autenticar(usuario_id: int, clave: str):
    """
    Intenta loguear a un usuario por su "Usuario Nº" y clave. Devuelve
    la fila del usuario si coinciden (y está activo), o None si no.
    Ver autenticar_por_nombre() para el login por nombre que usa la
    pantalla de ingreso actual — este queda como forma alternativa,
    hoy solo la usan los tests (TestMigracionHashEnLogin).
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT * FROM usuarios WHERE id = ? AND activo = 1", (usuario_id,)
        ).fetchone()
        return _validar_credenciales_y_registrar_sesion(conexion, fila, clave)


def autenticar_por_nombre(nombre: str, clave: str):
    """
    Igual que autenticar(), pero buscando por nombre en vez de por
    "Usuario Nº" — es lo que usa la pantalla de Login. La búsqueda
    ignora mayúsculas/minúsculas y espacios de más, para que no
    dependa de que se tipee exactamente igual a como se cargó.

    La comparación se hace en Python (con str.lower()) y no con el
    LOWER() de SQLite a propósito: SQLite solo pliega mayúsculas ASCII
    por defecto, así que "MATÍAS" y "Matías" le quedarían distintos
    (la Í no se convierte a í) — con nombres reales, que casi siempre
    llevan acentos, eso rompía el login con la variante equivocada.

    Como el nombre no es la clave primaria, en teoría podría haber más
    de un usuario activo con el mismo nombre y quedar ambiguo — por
    eso crear_usuario/modificar_usuario rechazan nombres repetidos
    entre usuarios activos (ver _nombre_en_uso), así que en la
    práctica esto no debería pasar.
    """
    objetivo = nombre.strip().lower()
    with conexion_db() as conexion:
        fila = next(
            (f for f in conexion.execute("SELECT * FROM usuarios WHERE activo = 1")
             if f["nombre"].strip().lower() == objetivo),
            None,
        )
        return _validar_credenciales_y_registrar_sesion(conexion, fila, clave)


def cambiar_clave(usuario_id: int, clave_actual: str, clave_nueva: str):
    """
    Cualquier usuario logueado (Admin o Empleada) puede cambiar su
    propia clave desde acá, pidiendo la clave actual como confirmación
    — a diferencia de modificar_usuario(), que es para que el Admin le
    resetee la clave a otra persona sin necesidad de saber la vieja.
    Levanta ValueError con un mensaje pensado para mostrar tal cual si
    la clave actual ingresada no coincide.
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT * FROM usuarios WHERE id = ? AND activo = 1", (usuario_id,)
        ).fetchone()
        if fila is None or not verificar_clave(clave_actual, fila["clave_hash"]):
            raise ValueError("La clave actual no es correcta.")

        conexion.execute(
            "UPDATE usuarios SET clave_hash = ? WHERE id = ?",
            (hash_clave(clave_nueva), usuario_id),
        )


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


def _proximo_numero_disponible(conexion) -> int:
    """
    Menor "Usuario Nº" que todavía no está ocupado — a propósito NO es
    simplemente MAX(id)+1, para que borrar un usuario sin historial
    (ver borrar_usuario) libere su número para el próximo que se cree,
    en vez de ir siempre para arriba y dejar huecos para siempre.
    """
    ocupados = {fila["id"] for fila in conexion.execute("SELECT id FROM usuarios")}
    candidato = 1
    while candidato in ocupados:
        candidato += 1
    return candidato


def _nombre_en_uso(conexion, nombre: str, excluir_id: int = None) -> bool:
    """
    Si ya hay otro usuario ACTIVO con este nombre (ignorando
    mayúsculas/espacios) — el login es por nombre (ver
    autenticar_por_nombre), así que dos usuarios activos no pueden
    compartir uno sin quedar ambiguo. Un usuario inactivo con el mismo
    nombre no cuenta: no puede loguearse, así que no genera ambigüedad.

    Comparación en Python (no con LOWER() de SQLite): mismo motivo que
    en autenticar_por_nombre, SQLite no pliega bien mayúsculas con
    acentos.
    """
    objetivo = nombre.strip().lower()
    for fila in conexion.execute("SELECT id, nombre FROM usuarios WHERE activo = 1"):
        if excluir_id is not None and fila["id"] == excluir_id:
            continue
        if fila["nombre"].strip().lower() == objetivo:
            return True
    return False


def crear_usuario(nombre: str, clave: str, rol: str, permisos: dict = None):
    """
    Crea un nuevo usuario (Admin o Empleada) y devuelve su id (el
    menor "Usuario Nº" disponible, ver _proximo_numero_disponible).
    Levanta ValueError si ya hay otro usuario activo con ese nombre.

    `permisos` es un dict {columna: bool} con algunas (o todas, o
    ninguna) de las claves de PERMISOS_EMPLEADA — las que no se pasen
    quedan en False. Para un usuario ADMIN da igual lo que se mande acá
    (ya tiene todo, ver tiene_permiso()), pero igual se guarda tal cual
    para no perderlo si algún día lo bajan a EMPLEADA.
    """
    permisos = permisos or {}
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        if _nombre_en_uso(conexion, nombre):
            raise ValueError(
                f"Ya hay un usuario activo llamado '{nombre.strip()}'. Como se ingresa "
                "por nombre, no puede haber dos iguales — probá con otro (por ejemplo, "
                "agregando el apellido)."
            )
        nuevo_id = _proximo_numero_disponible(conexion)
        columnas_permiso = [clave_col for clave_col, _ in PERMISOS_EMPLEADA]
        valores_permiso = [1 if permisos.get(c) else 0 for c in columnas_permiso]
        conexion.execute(
            f"""
            INSERT INTO usuarios
                (id, nombre, clave_hash, rol, activo, fecha_creacion, {", ".join(columnas_permiso)})
            VALUES (?, ?, ?, ?, 1, ?, {", ".join("?" for _ in columnas_permiso)})
            """,
            (nuevo_id, nombre, hash_clave(clave), rol, ahora, *valores_permiso),
        )
        return nuevo_id


def modificar_usuario(usuario_id: int, nombre: str, rol: str, clave: str = None, permisos: dict = None):
    """
    Actualiza nombre, rol y permisos de un usuario. Si se pasa una
    clave nueva (no vacía), también la actualiza; si no, deja la clave
    como estaba. Levanta ValueError si el nombre nuevo ya lo usa otro
    usuario activo (ver _nombre_en_uso). `permisos` funciona igual que
    en crear_usuario (las claves de PERMISOS_EMPLEADA que no se pasen
    quedan en False, no como estaban antes).
    """
    permisos = permisos or {}
    with conexion_db() as conexion:
        if _nombre_en_uso(conexion, nombre, excluir_id=usuario_id):
            raise ValueError(
                f"Ya hay un usuario activo llamado '{nombre.strip()}'. Como se ingresa "
                "por nombre, no puede haber dos iguales — probá con otro (por ejemplo, "
                "agregando el apellido)."
            )
        columnas_permiso = [clave_col for clave_col, _ in PERMISOS_EMPLEADA]
        valores_permiso = [1 if permisos.get(c) else 0 for c in columnas_permiso]
        set_permisos = ", ".join(f"{c} = ?" for c in columnas_permiso)
        if clave:
            conexion.execute(
                f"UPDATE usuarios SET nombre = ?, rol = ?, clave_hash = ?, {set_permisos} WHERE id = ?",
                (nombre, rol, hash_clave(clave), *valores_permiso, usuario_id),
            )
        else:
            conexion.execute(
                f"UPDATE usuarios SET nombre = ?, rol = ?, {set_permisos} WHERE id = ?",
                (nombre, rol, *valores_permiso, usuario_id),
            )


def desactivar_usuario(usuario_id: int):
    """
    Soft-delete: marca al usuario como inactivo en vez de borrarlo, para
    no perder el historial de ventas/compras/cierres que hizo. Deja de
    poder loguearse, pero su "Usuario Nº" queda reservado para siempre
    (no lo libera para reusar, a diferencia de borrar_usuario) — lo usa
    la UI como respaldo cuando borrar_usuario() rechaza el borrado por
    tener historial.
    """
    with conexion_db() as conexion:
        conexion.execute("UPDATE usuarios SET activo = 0 WHERE id = ?", (usuario_id,))


def borrar_usuario(usuario_id: int):
    """
    Borra un usuario de verdad (a diferencia de desactivar_usuario, que
    solo lo desactiva). Libera su "Usuario Nº" para que
    _proximo_numero_disponible se lo asigne al próximo usuario que se
    cree, así los números se mantienen correlativos con el tiempo.

    Solo se puede borrar si el usuario nunca vendió, compró, ni cerró
    un turno: si tiene historial, la clave foránea de esas tablas
    rechaza el borrado (SQLite lo avisa como IntegrityError) y acá se
    traduce en un ValueError con un mensaje pensado para mostrar tal
    cual, sugiriendo desactivar_usuario() en su lugar.
    """
    try:
        with conexion_db() as conexion:
            conexion.execute("DELETE FROM usuarios WHERE id = ?", (usuario_id,))
    except sqlite3.IntegrityError:
        raise ValueError(
            "Este usuario ya tiene ventas, compras o cierres de turno registrados: "
            "no se puede borrar sin perder ese historial. Se puede desactivar en su "
            "lugar (deja de poder loguearse, pero conserva su historial)."
        )
