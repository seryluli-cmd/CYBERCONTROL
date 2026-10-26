"""
reservas_socios_repo.py
=========================
RESERVAS DE SOCIOS (pedido del dueño, 2026-10-26): un socio de Miembros reserva
una PC sin pagar nada. Su saldo es la garantía, en vez de la seña, así que solo
reserva un socio con por lo menos `horas_para_reservar()` de saldo (arranca en
dominio.HORAS_SALDO_PARA_RESERVAR, 5 hs; lo cambia solo el Admin, en Miembros >
"$ Para Reserva"). Las demás reglas de las reservas son las de reservas_repo.py.

Lo que eligió el dueño:
- Al reservar no se cobra ni se descuenta nada. No hay venta, así que Caja y
  Cierre de Turno no se enteran (no es plata).
- Cuando llega, entra con su usuario y su clave en la PC (o con "Abrir PC con
  Miembro" del mostrador) y gasta su saldo como siempre: la reserva queda
  habilitada sola al entrar (`marcar_llegada`, la llama
  miembros_repo.abrir_estacion_por_miembro). No se habilita desde la ventana
  Reservas: eso abriría la PC sin pasar por su saldo.
- Su propia reserva no lo corta (reservas_horario_repo.minutos_para_el_socio);
  la de otro, sí, como siempre.
- Si no viene, pasa a "No vino" y no pierde nada (no pagó nada).
- El mínimo cuenta al reservar: si ese día tiene menos saldo, entra igual con lo
  que tenga.

Solo PCs comunes: PCSTREAM y la PlayStation 5 no se usan con saldo de socio.
Una reserva de socio no tiene bono: se guarda con bono_id BONO_DE_SOCIO, precio 0
y los minutos que se reservan (para que no se pise con otra reserva).
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import usuarios_repo
from control_pcs.repositories import reservas_horario_repo, reservas_repo

# reservas.bono_id es NOT NULL y no lleva REFERENCES (sale de uno de tres
# catálogos): una reserva de socio, que no tiene bono, guarda 0.
BONO_DE_SOCIO = 0
NOMBRE_BONO_DE_SOCIO = "Saldo de socio"

_CLAVE_HORAS = "reserva_socio_horas_minimas"


def texto_de_horas(minutos: int) -> str:
    """"5 hs", "1 h", "3 hs 30 min" o "40 min": cómo se nombra un saldo o un tiempo
    en los avisos de las reservas de socios."""
    horas, resto = divmod(max(0, int(minutos)), 60)
    if not horas:
        return f"{resto} min"
    texto = f"{horas} h" if horas == 1 else f"{horas} hs"
    return f"{texto} {resto} min" if resto else texto


# ---------------------------------------------------------------------
# El mínimo de saldo ("$ Para Reserva")
# ---------------------------------------------------------------------

def horas_para_reservar() -> int:
    """Las horas de saldo que tiene que tener un socio para reservar: las que guardó
    el Admin, o dominio.HORAS_SALDO_PARA_RESERVAR si nunca las cambió."""
    with conexion_db() as conexion:
        return _horas_para_reservar(conexion)


def _horas_para_reservar(conexion) -> int:
    fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_HORAS,)).fetchone()
    try:
        return int(fila["valor"]) if fila is not None else dominio.HORAS_SALDO_PARA_RESERVAR
    except ValueError:
        return dominio.HORAS_SALDO_PARA_RESERVAR


def guardar_horas_para_reservar(usuario_id: int, horas: int):
    """Cambia el mínimo de saldo para reservar. Solo un Administrador
    (PermissionError si no), de 1 a dominio.HORAS_MAXIMAS_SALDO_PARA_RESERVAR."""
    usuarios_repo.exigir_admin(usuario_id, "cambiar el saldo para reservar")
    if not isinstance(horas, int) or not 1 <= horas <= dominio.HORAS_MAXIMAS_SALDO_PARA_RESERVAR:
        raise ValueError(f"Elegí de 1 a {dominio.HORAS_MAXIMAS_SALDO_PARA_RESERVAR} horas.")
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (_CLAVE_HORAS, str(horas))
        )


# ---------------------------------------------------------------------
# Tomar la reserva
# ---------------------------------------------------------------------

def socios_para_reservar(buscar: str = "") -> list:
    """
    Los socios activos para elegir en la reserva, por usuario (como la lista de
    Miembros), cada uno como {"id", "usuario", "nombre", "saldo_minutos",
    "alcanza"}: "alcanza" es si tiene el saldo para reservar. `buscar` filtra
    por usuario o nombre, sin mayúsculas ni acentos.
    """
    buscado = dominio.sin_acentos(buscar).strip()
    with conexion_db() as conexion:
        minimo = _horas_para_reservar(conexion) * 60
        filas = conexion.execute(
            "SELECT id, usuario, nombre, saldo_minutos FROM miembros WHERE activo = 1 "
            "ORDER BY usuario COLLATE NOCASE"
        ).fetchall()
    socios = []
    for fila in filas:
        if buscado and buscado not in dominio.sin_acentos(f"{fila['usuario']} {fila['nombre']}"):
            continue
        socios.append({"id": fila["id"], "usuario": fila["usuario"], "nombre": fila["nombre"],
                       "saldo_minutos": fila["saldo_minutos"], "alcanza": fila["saldo_minutos"] >= minimo})
    return socios


def _validar(conexion, miembro_id: int, estacion_id, inicio: datetime, minutos: int, ahora: datetime):
    """Todo lo que controla crear_reserva_de_socio antes de grabar. Devuelve el socio."""
    miembro = conexion.execute(
        "SELECT * FROM miembros WHERE id = ? AND activo = 1", (miembro_id,)
    ).fetchone()
    if miembro is None:
        raise ValueError("Ese socio ya no está activo. Elegí otro.")
    minimo = _horas_para_reservar(conexion) * 60
    if miembro["saldo_minutos"] < minimo:
        raise ValueError(
            f"{miembro['nombre']} tiene {texto_de_horas(miembro['saldo_minutos'])} de saldo y para reservar "
            f"necesita {texto_de_horas(minimo)} o más (le faltan "
            f"{texto_de_horas(minimo - miembro['saldo_minutos'])}). Cargale saldo, o tomá una reserva común "
            "con seña."
        )
    if minutos <= 0 or minutos % 60 or minutos > dominio.HORAS_MAXIMAS_RESERVA_SOCIO * 60:
        raise ValueError(f"Elegí de 1 a {dominio.HORAS_MAXIMAS_RESERVA_SOCIO} horas.")
    if minutos > miembro["saldo_minutos"]:
        raise ValueError(
            f"{miembro['nombre']} tiene {texto_de_horas(miembro['saldo_minutos'])} de saldo: no puede reservar "
            f"{texto_de_horas(minutos)}."
        )
    reservas_repo._validar_equipo(conexion, dominio.EQUIPO_RESERVA_PC, estacion_id)
    reservas_repo._validar_horario(conexion, dominio.EQUIPO_RESERVA_PC, estacion_id, inicio, minutos, ahora)
    return miembro


def crear_reserva_de_socio(usuario_id: int, miembro_id: int, estacion_id, inicio: datetime, minutos: int) -> int:
    """
    Toma la reserva de un socio para una PC común (`estacion_id`; None =
    cualquier PC disponible) a la hora `inicio` (los segundos se descartan), por
    `minutos` (horas enteras, nunca más que su saldo). No cobra nada ni le toca
    el saldo. Devuelve el número de la reserva.
    """
    usuarios_repo.usuario_habilitado(usuario_id)
    inicio = inicio.replace(second=0, microsecond=0)
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        miembro = _validar(conexion, miembro_id, estacion_id, inicio, minutos, ahora)
        return conexion.execute(
            """
            INSERT INTO reservas (fecha_creacion, usuario_id, cliente, celular, equipo, estacion_id, bono_id,
                                  bono_nombre, minutos, precio, fecha_reserva, estado, estado_desde, estado_por,
                                  miembro_id)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 0, ?, ?, ?, ?, ?)
            """,
            (reservas_repo._iso(ahora), usuario_id, miembro["nombre"], miembro["telefono"],
             dominio.EQUIPO_RESERVA_PC, estacion_id, BONO_DE_SOCIO, NOMBRE_BONO_DE_SOCIO, minutos,
             inicio.isoformat(timespec="seconds"), dominio.RESERVA_PENDIENTE, reservas_repo._iso(ahora),
             usuario_id, miembro_id),
        ).lastrowid


# ---------------------------------------------------------------------
# El socio llegó
# ---------------------------------------------------------------------

def marcar_llegada(conexion, miembro_id: int, estacion_id: int, sesion_id: int, ahora: datetime) -> list:
    """
    El socio acaba de entrar a una PC con su saldo (dentro de la transacción de
    miembros_repo.abrir_estacion_por_miembro): sus reservas Pendientes cuya hora
    cae dentro de la sesión (llega antes de hora con saldo hasta pasada la hora, o
    tarde dentro de la tolerancia) quedan Habilitadas en esa PC, aunque sea otra
    que la reservada (como al habilitar desde el mostrador, se le da la que está
    libre). Así la PC reservada deja de estar apartada. Quedan anotadas por el
    programa (estado_por en NULL). Devuelve los números de esas reservas.
    """
    sesion = conexion.execute("SELECT fecha_fin_prevista FROM sesiones_pc WHERE id = ?", (sesion_id,)).fetchone()
    if sesion is None:
        return []
    fin = datetime.fromisoformat(sesion["fecha_fin_prevista"])
    numeros = [
        reserva["id"] for reserva in reservas_horario_repo.pendientes(conexion, ahora)
        if reserva["miembro_id"] == miembro_id and reserva["equipo"] == dominio.EQUIPO_RESERVA_PC
        and reserva["inicio"] < fin
    ]
    for numero in numeros:
        conexion.execute(
            """
            UPDATE reservas SET estado = ?, estado_desde = ?, estado_por = NULL, estacion_habilitada_id = ?,
                                sesion_pc_id = ?
            WHERE id = ? AND estado = ?
            """,
            (dominio.RESERVA_HABILITADA, reservas_repo._iso(ahora), estacion_id, sesion_id, numero,
             dominio.RESERVA_PENDIENTE),
        )
    return numeros
