"""
reservas_horario_repo.py
=========================
RESERVAS, parte 2: "que el programa cuide la hora" (pedido del dueño,
2026-10-20; las decisiones están en PROPUESTA_RESERVAS.md, en la carpeta de los
proyectos). La parte 1, la plata, está en reservas_repo.py.

- Desde MINUTOS_EQUIPO_RESERVADO_ANTES antes de la hora, una PC puntual,
  PCSTREAM o la PlayStation 5 se ve RESERVADA: celeste en el mosaico si está
  libre (pcs_window), y en la pantalla de bloqueo de la PC un cartel
  "RESERVADA para Juan · hoy 10:00" (lo manda servidor_red en GET /estado con
  cartel_para_la_pc; lo dibuja CLIENTE PC/cartel_reserva.py desde la V1.2).
  Sigue así hasta la hora + MINUTOS_TOLERANCIA_RESERVA, cuando la reserva pasa
  sola a No vino o A reprogramar.
- Mientras tanto se le puede vender un bono a otro cliente. Si el bono termina
  después de la hora de la reserva, la pantalla avisa antes de cobrar
  (aviso_al_vender). Es un aviso, no un freno: decide el operador.
- Un socio entra a una PC reservada solo hasta la hora de la reserva
  (minutos_para_el_socio, lo usa miembros_repo.abrir_estacion_por_miembro): se
  le descuenta solo ese tiempo y lo demás le queda en el saldo. Su propia
  reserva (las de socios, reservas_socios_repo) no lo corta.
- Las de "Cualquier PC disponible" no apartan ninguna PC (decisión del dueño):
  se ven en un aviso arriba del mosaico (sin_pc_fija), con cuántas PCs libres
  hay (pcs_libres).

Está aparte de reservas_repo para que pcs_repo, playstation_repo y
miembros_repo lo puedan usar sin un import circular (reservas_repo importa a
pcs_repo). No escribe nada: las reservas vencidas cambian de estado al listar
(reservas_repo._pasar_las_vencidas), y acá alcanza con no mirar las que ya
pasaron su tolerancia, aunque sigan anotadas como Pendientes.

Corre en cada refresco de la pantalla de PCs (cada 5 s) y en cada GET /estado
de cada PC: lee solo las Pendientes que todavía no vencieron, con el índice
idx_reservas_estado (CLAUDE.md, "Lo que corre en cada refresco...").
"""

from datetime import datetime, timedelta

import dominio
from database import conexion_db


def _iso_sin_segundos(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def pendientes(conexion, ahora: datetime) -> list:
    """
    Las reservas Pendientes cuyo cliente todavía puede llegar (su hora +
    MINUTOS_TOLERANCIA_RESERVA no pasó), de la más próxima a la más lejana. Cada
    una como {"id", "cliente", "equipo", "estacion_id", "inicio" (datetime),
    "minutos", "marcada", "miembro_id"}; "marcada" es si el equipo ya se ve
    RESERVADO (faltan MINUTOS_EQUIPO_RESERVADO_ANTES o menos) y "miembro_id", el
    socio de una reserva de socio (None en una común).
    """
    desde = ahora - timedelta(minutes=dominio.MINUTOS_TOLERANCIA_RESERVA)
    filas = conexion.execute(
        """
        SELECT id, cliente, equipo, estacion_id, fecha_reserva, minutos, miembro_id FROM reservas
        WHERE estado = ? AND fecha_reserva >= ?
        ORDER BY fecha_reserva, id
        """,
        (dominio.RESERVA_PENDIENTE, _iso_sin_segundos(desde)),
    ).fetchall()
    antes = timedelta(minutes=dominio.MINUTOS_EQUIPO_RESERVADO_ANTES)
    reservas = []
    for fila in filas:
        inicio = datetime.fromisoformat(fila["fecha_reserva"])
        reservas.append({
            "id": fila["id"], "cliente": fila["cliente"], "equipo": fila["equipo"],
            "estacion_id": fila["estacion_id"], "inicio": inicio, "minutos": fila["minutos"],
            "marcada": inicio - antes <= ahora, "miembro_id": fila["miembro_id"],
        })
    return reservas


def es_del_equipo(reserva: dict, estacion=None) -> bool:
    """Si `reserva` aparta ese equipo: `estacion` es una fila de `estaciones`, o
    None para la PlayStation 5. PCSTREAM se reconoce por el nombre (como en todo
    el programa) y una de "Cualquier PC disponible" no aparta ninguna PC."""
    if estacion is None:
        return reserva["equipo"] == dominio.EQUIPO_RESERVA_PLAYSTATION
    if dominio.es_pcstream(estacion["nombre"]):
        return reserva["equipo"] == dominio.EQUIPO_RESERVA_PCSTREAM
    return reserva["equipo"] == dominio.EQUIPO_RESERVA_PC and reserva["estacion_id"] == estacion["id"]


def proxima(reservas: list, estacion=None):
    """La primera de `reservas` (las de `pendientes`) que aparta ese equipo, o None."""
    return next((reserva for reserva in reservas if es_del_equipo(reserva, estacion)), None)


def texto_de_la_hora(inicio: datetime, ahora: datetime) -> str:
    """"hoy 10:00", "mañana 00:30" o "23/10 10:00": cómo se nombra la hora de una
    reserva en los avisos."""
    dias = (inicio.date() - ahora.date()).days
    if dias == 0:
        dia = "hoy"
    elif dias == 1:
        dia = "mañana"
    else:
        dia = f"{inicio:%d/%m}"
    return f"{dia} {inicio:%H:%M}"


# ---------------------------------------------------------------------
# Lo que se ve: mosaico y pantalla de bloqueo
# ---------------------------------------------------------------------

def reservas_para_la_grilla(ahora: datetime = None) -> list:
    """Las de `pendientes`, para que la pantalla de PCs las reparta entre sus
    equipos (pcs_repo.estado_estaciones, playstation_repo.estado)."""
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        return pendientes(conexion, ahora)


def sin_pc_fija(reservas: list) -> list:
    """Las de "Cualquier PC disponible" que ya se tienen que ver (marcadas), para
    el aviso de arriba del mosaico: no apartan ninguna PC."""
    return [
        reserva for reserva in reservas
        if reserva["marcada"] and reserva["equipo"] == dominio.EQUIPO_RESERVA_PC and reserva["estacion_id"] is None
    ]


def pcs_libres(estados: list) -> int:
    """Cuántas PCs comunes se le pueden dar ahora a quien reservó "cualquier PC":
    sin sesión, con el Cliente PC respondiendo y sin una reserva propia a la
    vista. `estados` es pcs_repo.estado_estaciones()."""
    return sum(
        1 for item in estados
        if item["sesion"] is None and item["enlazada"] and not item["es_pcstream"]
        and not (item["reserva"] is not None and item["reserva"]["marcada"])
    )


def cartel_para_la_pc(estacion, ahora: datetime = None):
    """
    Lo que viaja en GET /estado para el cartel de la pantalla de bloqueo:
    {"cliente", "inicio" (ISO, sin segundos)} si esa PC (una fila de
    `estaciones`) ya se ve RESERVADA, o None. La hora viaja entera y no como
    texto: "hoy" o "mañana" lo decide la PC con su reloj.
    """
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        reserva = proxima(pendientes(conexion, ahora), estacion)
    if reserva is None or not reserva["marcada"]:
        return None
    return {"cliente": reserva["cliente"], "inicio": _iso_sin_segundos(reserva["inicio"])}


# ---------------------------------------------------------------------
# Lo que se cuida: vender un bono, entrar con saldo de socio
# ---------------------------------------------------------------------

def aviso_al_vender(estacion_id, minutos: int, ahora: datetime = None):
    """
    Si venderle a ese equipo un bono de `minutos` lo deja usándose después de la
    hora de una reserva suya, el texto del aviso para el operador; si no, None.
    `estacion_id` es la PC (también PCSTREAM), o None para la PlayStation 5. El
    vencimiento se calcula como al cobrar (dominio.fin_al_sumar_minutos, sobre la
    sesión en curso si hay una). No frena nada: lo decide el operador.
    """
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        if estacion_id is None:
            estacion, nombre = None, f"La {dominio.NOMBRE_PLAYSTATION}"
            sesion = conexion.execute(
                "SELECT fecha_fin_prevista FROM sesiones_playstation WHERE estado = ?", (dominio.SESION_ACTIVA,)
            ).fetchone()
        else:
            estacion = conexion.execute("SELECT * FROM estaciones WHERE id = ?", (estacion_id,)).fetchone()
            if estacion is None:
                return None
            nombre = estacion["nombre"]
            sesion = conexion.execute(
                "SELECT fecha_fin_prevista FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
                (estacion_id, dominio.SESION_ACTIVA),
            ).fetchone()
        reservas = pendientes(conexion, ahora)

    fin_actual = datetime.fromisoformat(sesion["fecha_fin_prevista"]) if sesion is not None else None
    fin = dominio.fin_al_sumar_minutos(fin_actual, minutos, ahora)
    reserva = next(
        (reserva for reserva in reservas if es_del_equipo(reserva, estacion) and reserva["inicio"] < fin), None
    )
    if reserva is None:
        return None
    return (
        f"{nombre} está reservada para {reserva['cliente']} {texto_de_la_hora(reserva['inicio'], ahora)}, "
        f"y con este bono se usaría hasta las {fin:%H:%M}.\n\n"
        "Si el cliente de la reserva llega a horario, va a encontrar el equipo ocupado.\n\n¿Cobrar igual?"
    )


def minutos_para_el_socio(conexion, estacion_id: int, saldo_minutos: int, ahora: datetime,
                          miembro_id: int = None) -> tuple:
    """
    Cuántos minutos de su saldo usa un socio que entra a esa PC: todo el saldo,
    salvo que la PC tenga una reserva antes de que se le termine; entonces solo
    hasta la hora de la reserva (decisión del dueño), y lo demás le queda en el
    saldo. Si ya hay una sesión en curso, cuenta desde su vencimiento, igual que
    al sumarle el tiempo. Devuelve (minutos, hora de la reserva o None).

    Levanta ValueError (con un mensaje para el socio) si hasta la reserva le
    quedarían menos de MINUTOS_MINIMOS_SOCIO_ANTES_DE_RESERVA. Corre dentro de la
    transacción de abrir_estacion_por_miembro.

    Una reserva del mismo socio (`miembro_id`, ver reservas_socios_repo) no lo
    corta: es su turno. La de otro que venga después, sí.
    """
    estacion = conexion.execute("SELECT * FROM estaciones WHERE id = ?", (estacion_id,)).fetchone()
    if estacion is None:
        return saldo_minutos, None
    ajenas = [reserva for reserva in pendientes(conexion, ahora)
              if miembro_id is None or reserva["miembro_id"] != miembro_id]
    reserva = proxima(ajenas, estacion)
    if reserva is None:
        return saldo_minutos, None

    sesion = conexion.execute(
        "SELECT fecha_fin_prevista FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
        (estacion_id, dominio.SESION_ACTIVA),
    ).fetchone()
    desde = ahora if sesion is None else max(datetime.fromisoformat(sesion["fecha_fin_prevista"]), ahora)
    disponibles = int((reserva["inicio"] - desde).total_seconds() // 60)
    if disponibles >= saldo_minutos:
        return saldo_minutos, None
    if disponibles < dominio.MINUTOS_MINIMOS_SOCIO_ANTES_DE_RESERVA:
        raise ValueError(
            f"Esta PC está reservada {texto_de_la_hora(reserva['inicio'], ahora)}. "
            "Usá otra PC o pedí ayuda en el mostrador."
        )
    return disponibles, reserva["inicio"]
