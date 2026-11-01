"""
ajustes_saldo_repo.py
=====================
ORDENAR SALDOS (botón de Miembros que solo ve el Admin; pedido del dueño,
2026-11-01): corregir a mano el saldo de tiempo de un socio. El caso que lo
trajo: una empleada le cargó horas a un socio que no era (se equivocó de
cuenta). La plata entró bien a la caja; lo que quedó mal es en qué cuenta está
el tiempo. Anular la carga desde Consulta de Ventas no sirve para eso: saca la
plata de la caja, y volver a cargársela al socio correcto la cobraría otra vez.
Acá se mueve SOLO el tiempo: ni ventas, ni pagos, ni la caja.

Tres formas: sumar, restar y pasar de un socio a otro (las dos puntas en la
misma transacción). Cada una queda en `ajustes_saldo_miembro` con el saldo de
antes y el de después, quién y cuándo; en un pase, cada punta con el otro
socio. Como ORDENAR Stock, lo hace solo un Admin activo con la contraseña, y se
vuelve a pedir en cada cambio (no solo al abrir la ventana).

Lo que se le suma a un socio que está usando una PC pasa a esa sesión, igual que
una carga (miembros_repo._sumar_carga_a_la_sesion): si no, la PC seguiría
contando hasta cero. Restar, en cambio, sale solo del saldo: el tiempo que ya
corre en una PC no se toca desde acá (para eso se le cierra la sesión, y lo que
no usó vuelve al saldo).
"""

from datetime import datetime

import dominio
from database import conexion_db, verificar_clave
from repositories import articulos_repo, usuarios_repo
from control_pcs.repositories import miembros_repo

# La contraseña de ORDENAR SALDOS: la misma que la de ORDENAR Stock (pedido del
# dueño, 2026-11-01: "como la del botón ORDENAR Stock"). Va en su propia
# constante para poder cambiar una sin la otra: para cambiarla, poner acá el
# valor de database.hash_clave("la nueva"), nunca la clave en claro (este repo
# es público).
CLAVE_ORDENAR_SALDOS = articulos_repo.CLAVE_ORDENAR_STOCK


def comprobar_clave_para_ordenar_saldos(usuario_id: int, clave: str):
    """PermissionError con el motivo si `usuario_id` no es un Admin activo o
    `clave` no es la de ORDENAR SALDOS. Es lo que pregunta el botón antes de
    abrir la ventana; sumar, restar y pasar lo vuelven a preguntar."""
    usuarios_repo.exigir_admin(usuario_id, "ordenar los saldos de los socios")
    if not verificar_clave(clave or "", CLAVE_ORDENAR_SALDOS):
        raise PermissionError("La contraseña de ORDENAR SALDOS no es correcta.")


def _minutos_a_mover(minutos) -> int:
    """Los minutos que se suman, restan o pasan: un entero de 1 para arriba."""
    if isinstance(minutos, bool) or not isinstance(minutos, int) or minutos <= 0:
        raise ValueError("Escribí cuánto tiempo (horas y minutos): tiene que ser más de cero.")
    return minutos


def _socio(conexion, miembro_id: int):
    """El socio tal como está AHORA en la base (dentro de la transacción: el
    saldo de la pantalla puede ser viejo si mientras tanto entró a una PC)."""
    fila = conexion.execute(
        "SELECT id, usuario, nombre, saldo_minutos FROM miembros WHERE id = ?", (miembro_id,)
    ).fetchone()
    if fila is None:
        raise ValueError("Ese socio ya no existe. Cerrá ORDENAR SALDOS y volvé a abrirlo.")
    return fila


def _anotar(conexion, socio, saldo_nuevo: int, usuario_id: int, fecha: str, otro_miembro_id: int = None) -> dict:
    """Deja el saldo del socio en `saldo_nuevo` y lo anota con el de antes."""
    conexion.execute("UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (saldo_nuevo, socio["id"]))
    conexion.execute(
        """
        INSERT INTO ajustes_saldo_miembro
            (miembro_id, fecha, usuario_id, saldo_anterior, saldo_nuevo, otro_miembro_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (socio["id"], fecha, usuario_id, socio["saldo_minutos"], saldo_nuevo, otro_miembro_id),
    )
    return {"saldo_anterior": socio["saldo_minutos"], "saldo_nuevo": saldo_nuevo}


def _sumarle(conexion, socio, minutos: int, usuario_id: int, ahora: datetime, otro_miembro_id: int = None) -> dict:
    resultado = _anotar(conexion, socio, socio["saldo_minutos"] + minutos, usuario_id,
                        ahora.isoformat(timespec="seconds"), otro_miembro_id)
    # Lo de `sumado_a_la_sesion` (None o {"estacion", "minutos"}) es para avisarlo en
    # pantalla, como Cargar Saldo.
    resultado["sumado_a_la_sesion"] = miembros_repo._sumar_carga_a_la_sesion(conexion, socio["id"], minutos, ahora)
    return resultado


def _restarle(conexion, socio, minutos: int, usuario_id: int, ahora: datetime, otro_miembro_id: int = None) -> dict:
    # Nunca negativo: lo que le falta ya está corriendo en una PC o lo usó.
    if minutos > socio["saldo_minutos"]:
        raise ValueError(
            f"{socio['usuario']} tiene {dominio.texto_minutos(socio['saldo_minutos'])} de saldo: no se le "
            f"pueden sacar {dominio.texto_minutos(minutos)}. Si está usando una PC, lo que ya corre en la PC "
            "no se saca desde acá: cerrale la sesión (lo que no usó vuelve a su saldo) y probá de nuevo."
        )
    return _anotar(conexion, socio, socio["saldo_minutos"] - minutos, usuario_id,
                   ahora.isoformat(timespec="seconds"), otro_miembro_id)


def sumar(usuario_id: int, miembro_id: int, minutos, clave: str) -> dict:
    """Le suma `minutos` al saldo del socio, sin venta ni cobro. Devuelve
    {"saldo_anterior", "saldo_nuevo", "sumado_a_la_sesion"}. PermissionError
    (ver comprobar_clave_para_ordenar_saldos) o ValueError."""
    comprobar_clave_para_ordenar_saldos(usuario_id, clave)
    minutos = _minutos_a_mover(minutos)
    with conexion_db() as conexion:
        # El permiso de escritura de entrada: el socio no puede entrar a una PC (y
        # gastar el saldo) entre que se lee su saldo y se corrige.
        conexion.execute("BEGIN IMMEDIATE")
        return _sumarle(conexion, _socio(conexion, miembro_id), minutos, usuario_id, datetime.now())


def restar(usuario_id: int, miembro_id: int, minutos, clave: str) -> dict:
    """Le saca `minutos` del saldo al socio, sin tocar ventas ni la caja.
    Devuelve {"saldo_anterior", "saldo_nuevo"}. ValueError si tiene menos
    saldo que eso (no se deja en negativo)."""
    comprobar_clave_para_ordenar_saldos(usuario_id, clave)
    minutos = _minutos_a_mover(minutos)
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        return _restarle(conexion, _socio(conexion, miembro_id), minutos, usuario_id, datetime.now())


def pasar(usuario_id: int, desde_id: int, hacia_id: int, minutos, clave: str) -> dict:
    """
    Pasa `minutos` del saldo de un socio al de otro: el caso de la carga hecha a
    la cuenta equivocada. Las dos puntas en la misma transacción (o ninguna) y
    con la misma hora; cada una anotada con el otro socio. Devuelve
    {"desde": lo de restar, "hacia": lo de sumar}.
    """
    comprobar_clave_para_ordenar_saldos(usuario_id, clave)
    minutos = _minutos_a_mover(minutos)
    if desde_id == hacia_id:
        raise ValueError("Elegí otro socio: no se puede pasar el saldo al mismo.")
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        desde, hacia = _socio(conexion, desde_id), _socio(conexion, hacia_id)
        restado = _restarle(conexion, desde, minutos, usuario_id, ahora, otro_miembro_id=hacia_id)
        sumado = _sumarle(conexion, hacia, minutos, usuario_id, ahora, otro_miembro_id=desde_id)
        return {"desde": restado, "hacia": sumado}


def listar_ajustes(limite: int = 200):
    """Los últimos ajustes de saldo, el más nuevo primero: fecha, el socio
    (`socio`), saldo de antes y de después, cuánto se le sumó (`minutos`, en
    negativo lo que se le sacó), quién lo hizo (`operador`) y, en un pase, el
    otro socio (`otro_socio`, None si fue un ajuste suelto)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT a.id, a.fecha, a.miembro_id, a.saldo_anterior, a.saldo_nuevo,
                   a.saldo_nuevo - a.saldo_anterior AS minutos,
                   m.usuario AS socio, o.usuario AS otro_socio, u.nombre AS operador
            FROM ajustes_saldo_miembro a
            JOIN miembros m ON m.id = a.miembro_id
            LEFT JOIN miembros o ON o.id = a.otro_miembro_id
            JOIN usuarios u ON u.id = a.usuario_id
            ORDER BY a.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
