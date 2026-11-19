"""
tareas_turno_repo.py
=====================
TAREAS DEL TURNO (pedido del dueño, 2026-11-03): cosas para hacer a una hora,
como "PRENDER LAS LUCES DE AFUERA" a las 19:30. A la hora sale un aviso encima de
todo, con POSPONER 5 MIN, POSPONER 10 MIN y TAREA HECHA, que vuelve hasta que
alguien la hace. Acá están las reglas; el aviso y la pantalla solo preguntan.

Reglas:

- Cargar, modificar y borrar una tarea: solo un Administrador (exigir_admin).
  Marcarla HECHA y posponerla: cualquier operador que siga habilitado
  (usuario_habilitado).
- Cada vez que una tarea toca es una "aparición": la tarea en un DÍA DEL LOCAL
  (de 06:00 a 06:00, turnos.HORA_CAMBIO_DE_DIA). TODOS LOS DÍAS toca todos;
  ALGUNOS DÍAS, los días de la semana que eligió el Admin; UN SOLO DÍA ("SOLO
  HOY"), el día en que se cargó. El día es el del local: la de las 02:00 "los
  lunes" es de la Noche del lunes y pasa el martes a las 02:00
  (turnos.momento_de_la_tarea).
- Una aparición cuya hora es anterior al minuto en que se cargó la tarea no cuenta:
  ni avisa ni queda atrasada (la de las 18:00 "todos los días" cargada a las 19:00
  avisa desde mañana). Por eso un SOLO HOY con una hora que ya pasó no se carga.
  Con MODIFICAR pasa lo mismo, desde el minuto del cambio, si con cómo era antes
  ese día no le tocaba (la de las 18:00 de los lunes, pasada a TODOS LOS DÍAS el
  martes a las 21:00, avisa desde el miércoles); si ya le tocaba, sigue contando
  (corregirle el texto a una atrasada no la calla). Ver _cuenta.
- Desde su hora, mientras nadie la haga, está ATRASADA y avisa
  (tareas_para_avisar), salvo que esté pospuesta: cada POSPONER deja una fila con
  quién, cuándo y los minutos, y no vuelve a avisar hasta esa hora más los minutos.
  Después, otra vez, hasta que alguien ponga HECHA (una sola vez por aparición: lo
  cuida además un índice único).
- Avisa solo lo del día del local en curso: lo que no se hizo en un día que ya
  terminó queda en el historial como NO SE HIZO y no vuelve a avisar. Marcar o
  posponer se acepta también para el día anterior, porque el aviso de las 05:50 se
  puede contestar a las 06:01; pero lo pospuesto más allá de las 06:00 ya no vuelve,
  y el aviso lo dice antes (minutos_que_no_vuelven).
- Nada se borra (regla 7). BORRAR la deja BORRADA: deja de avisar y de verse, y lo
  que ya pasó (lo hecho, lo pospuesto, lo que no se hizo) sigue en el historial.
  MODIFICAR deja en tareas_turno_cambios cómo era antes: lo hecho y lo pospuesto
  siguen con la tarea (van por su número, que no cambia) y el historial de un día
  viejo la muestra como era cuando le tocó (ver _version_del_dia).

Es solo del mostrador: nada de acá entra en admin_remoto/lista_blanca.py.
"""

import math
from datetime import date, datetime, timedelta

import dominio
import turnos
from database import conexion_db
from repositories import usuarios_repo

# Lo que define cuándo y qué es una tarea: lo que cambia MODIFICAR y lo que guarda
# tareas_turno_cambios de antes de cada cambio.
_CAMPOS_DE_LA_TAREA = ("texto", "hora", "repeticion", "dias_semana", "dia")

_PARA_CARGAR = "cargar, modificar o borrar las tareas del turno"


def _como_momento(ahora) -> datetime:
    """`ahora` (datetime, texto ISO o None = el reloj) al segundo, como se graba."""
    if ahora is None:
        ahora = datetime.now()
    elif isinstance(ahora, str):
        ahora = datetime.fromisoformat(ahora)
    return ahora.replace(microsecond=0)


def _como_dia(dia) -> date:
    """El día del local de una aparición: un date o "YYYY-MM-DD". Un datetime no:
    a las 02:00 su fecha es la del día siguiente al del local, y daría otra
    aparición sin que nadie se entere."""
    if isinstance(dia, datetime):
        raise TypeError("Pasá el día del local (un date o 'YYYY-MM-DD'), no un momento.")
    return dia if isinstance(dia, date) else date.fromisoformat(str(dia)[:10])


def _texto(momento: datetime) -> str:
    return momento.isoformat(timespec="seconds")


def _hoy(ahora: datetime) -> date:
    return turnos.dia_en_que_empezo_el_turno(ahora)


def _al_minuto(momento: str) -> datetime:
    """Desde cuándo cuenta lo que toca con una versión de la tarea: el minuto en que
    se cargó o se cambió. Al minuto y no al segundo: la de las 19:00 cargada a las
    19:00:40 es para ahora mismo."""
    return datetime.fromisoformat(momento).replace(second=0)


# ---------------------------------------------------------------------
# Qué tareas tocan un día y cómo están
# ---------------------------------------------------------------------

def _leer_todo(conexion, desde: date, hasta: date):
    """Las tareas (todas, también las borradas), sus cambios (de cada tarea, del más
    nuevo al más viejo) y lo anotado de los días `desde` a `hasta` (por tarea y día,
    en el orden en que pasó)."""
    tareas = conexion.execute(
        "SELECT t.*, u.nombre AS creada_por_nombre FROM tareas_turno AS t "
        "JOIN usuarios AS u ON u.id = t.creada_por ORDER BY t.id"
    ).fetchall()
    cambios = {}
    for cambio in conexion.execute("SELECT * FROM tareas_turno_cambios ORDER BY fecha DESC, id DESC"):
        cambios.setdefault(cambio["tarea_id"], []).append(cambio)
    marcas = {}
    for marca in conexion.execute(
        "SELECT m.*, u.nombre FROM tareas_turno_marcas AS m JOIN usuarios AS u ON u.id = m.usuario_id "
        "WHERE m.dia >= ? AND m.dia <= ? ORDER BY m.fecha, m.id",
        (desde.isoformat(), hasta.isoformat()),
    ):
        marcas.setdefault((marca["tarea_id"], marca["dia"]), []).append(marca)
    return tareas, cambios, marcas


def _versiones(tarea, cambios) -> list:
    """
    Cada versión de la tarea, de la primera a la de ahora: dicts con `campos` (los
    de _CAMPOS_DE_LA_TAREA), `desde` (la carga o el cambio que la dejó así, ISO) y
    `hasta` (el cambio siguiente o el borrado; None si sigue). `cambios` es lo de
    tareas_turno_cambios de esa tarea, del más nuevo al más viejo: cada fila guardó
    cómo era antes de cambiarla, o sea, la versión que terminó en su fecha.
    """
    versiones = []
    desde = tarea["creada"]
    for cambio in reversed(cambios):
        versiones.append({"campos": {campo: cambio[campo] for campo in _CAMPOS_DE_LA_TAREA},
                          "desde": desde, "hasta": cambio["fecha"]})
        desde = cambio["fecha"]
    versiones.append({"campos": {campo: tarea[campo] for campo in _CAMPOS_DE_LA_TAREA},
                      "desde": desde, "hasta": tarea["borrada"]})
    return versiones


def _vigente_en(versiones, momento: str):
    """El número de la versión que regía en `momento` (ISO): la última que empezó
    hasta entonces (None si todavía no la habían cargado)."""
    vigente = None
    for numero, version in enumerate(versiones):
        if version["desde"] > momento:
            break
        vigente = numero
    return vigente


def _le_toca(campos: dict, dia: date) -> bool:
    """Si una tarea (sus campos, como en _CAMPOS_DE_LA_TAREA) toca el día del local `dia`."""
    if campos["repeticion"] == dominio.TAREA_ALGUNOS_DIAS:
        return dia.weekday() in dominio.dias_de_la_tarea(campos["dias_semana"])
    if campos["repeticion"] == dominio.TAREA_UN_SOLO_DIA:
        return campos["dia"] == dia.isoformat()
    return True


def _cuenta(versiones, numero: int, dia: date) -> bool:
    """
    Si con la versión `numero` la tarea tiene una aparición que cuenta el día `dia`:
    le toca, y su hora no es anterior a cuando empezó esa versión (la carga o el
    cambio, al minuto). Si es anterior, cuenta solo si con la versión de antes ese
    día también contaba. Así MODIFICAR hace lo mismo que cargarla de nuevo para lo
    que hoy no tocaba (la de las 18:00 de los lunes, pasada a TODOS LOS DÍAS el
    martes a las 21:00, no salta el martes ni queda como NO SE HIZO), pero corregir
    el texto o la hora de una que hoy ya tocaba la deja como estaba (sigue atrasada).
    """
    for version in reversed(versiones[:numero + 1]):
        campos = version["campos"]
        if not _le_toca(campos, dia):
            return False
        if turnos.momento_de_la_tarea(dia, campos["hora"]) >= _al_minuto(version["desde"]):
            return True
    return False


def _llego_su_hora(versiones, numero: int, dia: date) -> bool:
    """Si con la versión `numero` el día `dia` contaba y su hora llegó mientras esa
    versión regía (antes del cambio siguiente o del borrado): esa vez pasó."""
    hasta = versiones[numero]["hasta"]
    momento = turnos.momento_de_la_tarea(dia, versiones[numero]["campos"]["hora"])
    return _cuenta(versiones, numero, dia) and (hasta is None or momento < datetime.fromisoformat(hasta))


def _version_del_dia(versiones, dia: date, lo_anotado, borrada: bool, corte: str, termino: bool):
    """
    Con qué versión de la tarea se ve su aparición del día `dia` (el número), o None
    si ese día no tiene. `corte` es hasta cuándo se mira (ISO) y `termino`, si el
    día ya terminó.

    - El día en curso se ve como está la tarea ahora: borrarla o cambiarla para que
      hoy no toque la saca de la grilla y del aviso, salvo que ya esté HECHA (eso
      pasó y se sigue viendo, también borrada).
    - Un día que ya terminó se ve como pasó, no como quedó la tarea al terminar el
      día: borrarla o cambiarle los días a las 21:00 no puede hacer desaparecer del
      historial lo que se pospuso a las 19:30 ni el NO SE HIZO (lo que se le dijo al
      dueño: cada POSPONER se ve en el HISTORIAL). Una HECHA, con la tarea como era
      cuando la marcaron (la de las 23:00 hecha a las 23:05 y pasada a las 02:00 a
      las 23:30 sigue diciendo 23:00); si no, con la última versión con la que su hora
      llegó mientras regía; y si nada de eso, pero alguien la pospuso, con la de la
      última marca.
    """
    hecha = next((marca for marca in lo_anotado if marca["accion"] == dominio.ACCION_TAREA_HECHA), None)
    if not termino:
        actual = _vigente_en(versiones, corte)
        if hecha is not None or (not borrada and _cuenta(versiones, actual, dia)):
            return actual
        return None
    if hecha is not None:
        return _vigente_en(versiones, hecha["fecha"])
    for numero in reversed(range(len(versiones))):
        # Una versión de después de que terminó el día no es la que le tocó ese día.
        if versiones[numero]["desde"] <= corte and _llego_su_hora(versiones, numero, dia):
            return numero
    if lo_anotado:
        return _vigente_en(versiones, lo_anotado[-1]["fecha"])
    return None


def _pospuestas(lo_anotado) -> list:
    return [
        {"usuario_id": marca["usuario_id"], "nombre": marca["nombre"], "fecha": marca["fecha"],
         "minutos": marca["minutos"],
         "hasta": _texto(datetime.fromisoformat(marca["fecha"]) + timedelta(minutes=marca["minutos"]))}
        for marca in lo_anotado if marca["accion"] == dominio.ACCION_TAREA_POSPUESTA
    ]


def _aparicion(tarea, como_era: dict, dia: date, lo_anotado, borrada: bool, ahora: datetime) -> dict:
    """Una aparición como la usan la grilla, el aviso y el historial, con la tarea
    como era (`como_era`, sus campos) en la versión que le toca ese día."""
    momento = turnos.momento_de_la_tarea(dia, como_era["hora"])
    hecha = next((m for m in lo_anotado if m["accion"] == dominio.ACCION_TAREA_HECHA), None)
    pospuestas = _pospuestas(lo_anotado)
    estado = dominio.estado_de_la_tarea(hecha is not None, dia < _hoy(ahora), momento, ahora)
    segundos = (ahora - momento).total_seconds()
    return {
        "tarea_id": tarea["id"],
        "texto": como_era["texto"],
        "hora": como_era["hora"],
        "dia": dia.isoformat(),
        "momento": _texto(momento),
        "turno": turnos.calcular_turno(momento),
        "repeticion": como_era["repeticion"],
        "se_repite": dominio.texto_se_repite(como_era["repeticion"], como_era["dias_semana"], como_era["dia"]),
        "estado": estado,
        # ATRASADA · 1 h 12 min / EN 18 MIN: los minutos que faltan, redondeados
        # para arriba, así nunca dice "EN 0 MIN" antes de la hora.
        "minutos_de_atraso": int(segundos // 60) if estado == dominio.TAREA_ATRASADA else 0,
        "minutos_que_faltan": (math.ceil(-segundos / 60)
                               if estado in (dominio.TAREA_PRONTO, dominio.TAREA_MAS_TARDE) else 0),
        "hecha_por": hecha["nombre"] if hecha else None,
        "hecha_por_id": hecha["usuario_id"] if hecha else None,
        "hecha_en": hecha["fecha"] if hecha else None,
        # La última hora hasta la que la pospusieron (puede haber pasado ya).
        "pospuesta_hasta": max((p["hasta"] for p in pospuestas), default=None),
        "veces_pospuesta": len(pospuestas),
        "posposiciones": pospuestas,
        "borrada": borrada,
    }


def _apariciones_del_dia(tareas, cambios, marcas, dia: date, ahora: datetime) -> list:
    """Cada aparición del día del local `dia`, en el orden del turno (por su
    momento: las 02:00 después de las 23:00)."""
    fin_del_dia = datetime.fromisoformat(turnos.limites_de_los_dias(dia, dia)[1])
    # Hasta cuándo se mira: un día que ya terminó, hasta su último segundo; el de
    # hoy, hasta ahora.
    corte = _texto(min(ahora, fin_del_dia - timedelta(seconds=1)))
    termino = dia < _hoy(ahora)
    apariciones = []
    for tarea in tareas:
        if tarea["creada"] > corte:
            continue  # todavía no la habían cargado
        versiones = _versiones(tarea, cambios.get(tarea["id"], ()))
        lo_anotado = marcas.get((tarea["id"], dia.isoformat()), [])
        borrada = tarea["estado"] == dominio.TAREA_BORRADA and tarea["borrada"] <= corte
        numero = _version_del_dia(versiones, dia, lo_anotado, borrada, corte, termino)
        if numero is not None:
            apariciones.append(_aparicion(tarea, versiones[numero]["campos"], dia, lo_anotado, borrada, ahora))
    apariciones.sort(key=lambda a: (a["momento"], dominio.sin_acentos(a["texto"]), a["tarea_id"]))
    return apariciones


def tareas_del_dia(dia=None, ahora=None) -> list:
    """
    Cada aparición del día del local `dia` (date o "YYYY-MM-DD"; None = hoy, el día
    del local de `ahora`), en el orden del turno. Cada una es un dict con:
    `tarea_id`, `texto`, `hora` ("HH:MM"), `dia`, `momento` (cuándo toca, ISO),
    `turno`, `repeticion` y `se_repite`; `estado` (dominio.ESTADOS_TAREA_DEL_DIA),
    `minutos_de_atraso` (si está ATRASADA) y `minutos_que_faltan` (PRONTO o MÁS
    TARDE); `hecha_por` (nombre), `hecha_por_id` y `hecha_en` (ISO) si está HECHA;
    `pospuesta_hasta` (ISO de la última, aunque ya haya pasado, o None),
    `veces_pospuesta` y `posposiciones` (cada una con `usuario_id`, `nombre`,
    `fecha`, `minutos` y `hasta`, en el orden en que pasaron); y `borrada` (hoy solo
    una HECHA puede venir borrada: se sigue viendo lo que se hizo; en un día que ya
    terminó, también lo que pasó ese día antes de que la borraran).
    """
    ahora = _como_momento(ahora)
    dia = _hoy(ahora) if dia is None else _como_dia(dia)
    with conexion_db() as conexion:
        tareas, cambios, marcas = _leer_todo(conexion, dia, dia)
    return _apariciones_del_dia(tareas, cambios, marcas, dia, ahora)


def tareas_para_avisar(ahora=None) -> list:
    """Las que tienen que saltar ya en el aviso, en orden (si tocan dos a la vez
    salen de a una): las de hoy ATRASADAS que no están pospuestas, o cuya última
    posposición ya venció. Mismos dicts que tareas_del_dia."""
    ahora = _como_momento(ahora)
    ahora_texto = _texto(ahora)
    return [
        tarea for tarea in tareas_del_dia(None, ahora)
        if tarea["estado"] == dominio.TAREA_ATRASADA
        and (tarea["pospuesta_hasta"] is None or tarea["pospuesta_hasta"] <= ahora_texto)
    ]


def minutos_que_no_vuelven(dia, ahora=None, margen_segundos: int = 0) -> tuple:
    """
    De dominio.MINUTOS_PARA_POSPONER, los que llevan la aparición del día del local
    `dia` hasta el fin de ese día (las 06:00 del siguiente) o más allá: pospuesta
    así ya no vuelve a avisar, porque los avisos son solo del día en curso, y queda
    NO SE HIZO. El aviso lo dice antes de que la pospongan (la de las 05:50
    pospuesta 10 minutos a las 05:55 se perdía sin que nadie se enterara).
    `margen_segundos` es lo que puede tardar la revisión siguiente: pospuesta hasta
    las 05:59:55 y revisada a las 06:00:05, tampoco vuelve.
    """
    ahora = _como_momento(ahora)
    dia = _como_dia(dia)
    fin_del_dia = datetime.fromisoformat(turnos.limites_de_los_dias(dia, dia)[1])
    return tuple(minutos for minutos in dominio.MINUTOS_PARA_POSPONER
                 if ahora + timedelta(minutes=minutos, seconds=margen_segundos) >= fin_del_dia)


def cuantas_atrasadas(ahora=None) -> int:
    """Cuántas tareas de hoy ya llegaron a su hora y nadie hizo, también las
    pospuestas: el número del botón TAREAS de la barra, que titila mientras haya."""
    return sum(tarea["estado"] == dominio.TAREA_ATRASADA for tarea in tareas_del_dia(None, ahora))


def listar_historial(desde, hasta, ahora=None) -> list:
    """
    Los días anteriores de `desde` a `hasta` (incluidos; el de hoy no, que todavía
    no terminó): cada aparición con su `estado` HECHA (quién y cuándo) o NO SE HIZO,
    y lo pospuesto (cuántas veces y quiénes), con la tarea como era ese día. El día
    más nuevo primero y, dentro de cada día, en el orden del turno. Mismos dicts que
    tareas_del_dia.
    """
    ahora = _como_momento(ahora)
    desde, hasta = _como_dia(desde), min(_como_dia(hasta), _hoy(ahora) - timedelta(days=1))
    with conexion_db() as conexion:
        tareas, cambios, marcas = _leer_todo(conexion, desde, hasta)
    if not tareas:
        return []
    # Antes de la primera tarea no hay nada: un "Desde" muy viejo no recorre años vacíos.
    desde = max(desde, min(turnos.dia_en_que_empezo_el_turno(datetime.fromisoformat(t["creada"])) for t in tareas))
    historial = []
    dia = hasta
    while dia >= desde:
        historial.extend(_apariciones_del_dia(tareas, cambios, marcas, dia, ahora))
        dia -= timedelta(days=1)
    return historial


def listar_tareas(ahora=None) -> list:
    """
    Las tareas cargadas (TODAS LAS TAREAS, para modificar o borrar una que hoy no
    toca), en el orden del turno (de las 06:00 a las 05:59). Cada una con `id`,
    `texto`, `hora`, `turno`, `repeticion`, `dias_semana` (números, 0 = lunes),
    `dia` (la de un solo día), `se_repite`, `creada` y `creada_por` (nombre). Sin
    las borradas ni las de un solo día que ya pasó: esas están en el historial.
    """
    ahora = _como_momento(ahora)
    hoy = _hoy(ahora)
    with conexion_db() as conexion:
        filas = conexion.execute(
            "SELECT t.*, u.nombre AS creada_por_nombre FROM tareas_turno AS t "
            "JOIN usuarios AS u ON u.id = t.creada_por WHERE t.estado = ?",
            (dominio.TAREA_ACTIVA,),
        ).fetchall()
    tareas = [
        {"id": fila["id"], "texto": fila["texto"], "hora": fila["hora"],
         "turno": turnos.calcular_turno(turnos.momento_de_la_tarea(hoy, fila["hora"])),
         "repeticion": fila["repeticion"], "dias_semana": dominio.dias_de_la_tarea(fila["dias_semana"]),
         "dia": fila["dia"],
         "se_repite": dominio.texto_se_repite(fila["repeticion"], fila["dias_semana"], fila["dia"]),
         "creada": fila["creada"], "creada_por": fila["creada_por_nombre"]}
        for fila in filas
        if not (fila["repeticion"] == dominio.TAREA_UN_SOLO_DIA and fila["dia"] < hoy.isoformat())
    ]
    tareas.sort(key=lambda t: (turnos.momento_de_la_tarea(hoy, t["hora"]), dominio.sin_acentos(t["texto"]), t["id"]))
    return tareas


# ---------------------------------------------------------------------
# Cargar, modificar y borrar: solo el Administrador
# ---------------------------------------------------------------------

def _revisar(texto, hora, repeticion, dias_semana, hoy: date) -> dict:
    """Los campos de una tarea como se guardan, en el orden del diálogo (TAREA,
    HORA, SE REPITE), o ValueError con lo que está mal."""
    texto = dominio.revisar_tarea(texto)
    hora = dominio.hora_de_tarea(hora)
    repeticion, dias = dominio.revisar_repeticion(repeticion, dias_semana)
    return {"texto": texto, "hora": hora, "repeticion": repeticion, "dias_semana": dias,
            "dia": hoy.isoformat() if repeticion == dominio.TAREA_UN_SOLO_DIA else None}


def _exigir_que_no_haya_pasado(campos: dict, ahora: datetime):
    """ValueError si es de SOLO HOY y su hora de hoy ya pasó: nunca avisaría."""
    momento = turnos.momento_de_la_tarea(campos["dia"], campos["hora"])
    if momento >= ahora.replace(second=0):
        return
    aclaracion = (" (hasta las 06:00 sigue siendo el día que empezó ayer)"
                  if ahora.hour < turnos.HORA_CAMBIO_DE_DIA else "")
    raise ValueError(
        f"Las {campos['hora']} de hoy ya pasaron{aclaracion}: una tarea de SOLO HOY tiene que ser "
        "para más tarde. Si es para todos los días o para otros días, elegilo en SE REPITE."
    )


def _leer_tarea(conexion, tarea_id: int):
    tarea = conexion.execute("SELECT * FROM tareas_turno WHERE id = ?", (tarea_id,)).fetchone()
    if tarea is None:
        raise ValueError("Esa tarea no existe: cerrá y volvé a abrir Tareas del Turno.")
    return tarea


def _leer_activa(conexion, tarea_id: int, para: str):
    """La tarea, o ValueError si ya no está (el Admin pudo borrarla mientras el
    aviso o la pantalla seguían abiertos)."""
    tarea = _leer_tarea(conexion, tarea_id)
    if tarea["estado"] != dominio.TAREA_ACTIVA:
        raise ValueError(f'"{tarea["texto"]}" ya no está: la borró el Administrador. No se puede {para}.')
    return tarea


def crear_tarea(usuario_id: int, texto, hora, repeticion, dias_semana=None, ahora=None) -> int:
    """
    Carga una tarea nueva y devuelve su número. `hora` como la escriban ("1930",
    "19:30"...); `repeticion` es una de dominio.REPETICIONES_TAREA y `dias_semana`
    los días de ELEGIR DÍAS (0 = lunes). SOLO HOY es el día del local en curso.
    ValueError si algo está mal escrito o si es de SOLO HOY y su hora ya pasó.
    """
    usuarios_repo.exigir_admin(usuario_id, _PARA_CARGAR)
    ahora = _como_momento(ahora)
    campos = _revisar(texto, hora, repeticion, dias_semana, _hoy(ahora))
    if campos["repeticion"] == dominio.TAREA_UN_SOLO_DIA:
        _exigir_que_no_haya_pasado(campos, ahora)
    with conexion_db() as conexion:
        return conexion.execute(
            "INSERT INTO tareas_turno (texto, hora, repeticion, dias_semana, dia, estado, creada, creada_por) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (campos["texto"], campos["hora"], campos["repeticion"], campos["dias_semana"], campos["dia"],
             dominio.TAREA_ACTIVA, _texto(ahora), usuario_id),
        ).lastrowid


def _anotar_cambio(conexion, tarea_id: int, antes: dict, usuario_id: int, ahora: datetime):
    conexion.execute(
        "INSERT INTO tareas_turno_cambios (tarea_id, fecha, usuario_id, texto, hora, repeticion, dias_semana, dia) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (tarea_id, _texto(ahora), usuario_id, *(antes[campo] for campo in _CAMPOS_DE_LA_TAREA)),
    )


def modificar_tarea(usuario_id: int, tarea_id: int, texto, hora, repeticion, dias_semana=None, ahora=None):
    """
    Cambia el texto, la hora o la repetición de una tarea (lo mismo que se escribe
    al cargarla). Lo hecho y pospuesto de hoy no se pierde, y cómo era antes queda
    en tareas_turno_cambios con quién y cuándo. SOLO HOY la deja para el día del
    local en curso; con una hora que ya pasó solo se acepta si hoy ya le tocaba
    (corregir una de hoy), porque si no nunca avisaría.
    """
    usuarios_repo.exigir_admin(usuario_id, _PARA_CARGAR)
    ahora = _como_momento(ahora)
    hoy = _hoy(ahora)
    nuevos = _revisar(texto, hora, repeticion, dias_semana, hoy)
    with conexion_db() as conexion:
        # Lo que se lee (cómo era antes, que queda anotado) y lo que se graba, en la
        # misma transacción (regla 8): con el permiso de escritura tomado antes de
        # mirar, otra conexión que la cambie a la vez no deja anotado un "antes" viejo.
        conexion.execute("BEGIN IMMEDIATE")
        tarea = _leer_activa(conexion, tarea_id, "modificarla")
        antes = {campo: tarea[campo] for campo in _CAMPOS_DE_LA_TAREA}
        if nuevos == antes:
            return  # no cambió nada: no se anota un cambio vacío
        cambios = conexion.execute(
            "SELECT * FROM tareas_turno_cambios WHERE tarea_id = ? ORDER BY fecha DESC, id DESC", (tarea["id"],)
        ).fetchall()
        versiones = _versiones(tarea, cambios)
        # Con la hora pasada, SOLO HOY cuenta solo si hoy ya le tocaba (_cuenta).
        if nuevos["repeticion"] == dominio.TAREA_UN_SOLO_DIA and not _cuenta(versiones, len(versiones) - 1, hoy):
            _exigir_que_no_haya_pasado(nuevos, ahora)
        conexion.execute(
            "UPDATE tareas_turno SET texto = ?, hora = ?, repeticion = ?, dias_semana = ?, dia = ? WHERE id = ?",
            (*(nuevos[campo] for campo in _CAMPOS_DE_LA_TAREA), tarea["id"]),
        )
        _anotar_cambio(conexion, tarea["id"], antes, usuario_id, ahora)


def borrar_tarea(usuario_id: int, tarea_id: int, ahora=None):
    """La saca de la lista: deja de avisar y de verse. La fila queda BORRADA con
    quién y cuándo (regla 7), y lo que ya se hizo sigue en el historial."""
    usuarios_repo.exigir_admin(usuario_id, _PARA_CARGAR)
    ahora = _como_momento(ahora)
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        tarea = _leer_tarea(conexion, tarea_id)
        if tarea["estado"] == dominio.TAREA_BORRADA:
            raise ValueError(f'"{tarea["texto"]}" ya estaba borrada.')
        conexion.execute(
            "UPDATE tareas_turno SET estado = ?, borrada = ?, borrada_por = ? WHERE id = ?",
            (dominio.TAREA_BORRADA, _texto(ahora), usuario_id, tarea["id"]),
        )


# ---------------------------------------------------------------------
# HECHA y POSPONER: cualquier operador habilitado
# ---------------------------------------------------------------------

def _la_aparicion(conexion, tarea_id: int, dia: date, ahora: datetime, para: str) -> dict:
    """La aparición de la tarea ese día, como la da tareas_del_dia, o ValueError si
    la tarea ya no está, el día no se puede contestar o ese día no le toca."""
    tarea = _leer_activa(conexion, tarea_id, para)
    hoy = _hoy(ahora)
    if dia > hoy:
        raise ValueError(f'"{tarea["texto"]}" es de un día que todavía no empezó: no se puede {para}.')
    # Ayer sí: el aviso de las 05:50 se puede contestar pasadas las 06:00.
    if dia < hoy - timedelta(days=1):
        raise ValueError(f'"{tarea["texto"]}" es de un día que ya terminó: no se puede {para}.')
    _, cambios, marcas = _leer_todo(conexion, dia, dia)
    for aparicion in _apariciones_del_dia([tarea], cambios, marcas, dia, ahora):
        return aparicion
    raise ValueError(f'"{tarea["texto"]}" no toca ese día: no se puede {para}.')


def _exigir_que_no_este_hecha(aparicion: dict):
    if aparicion["estado"] == dominio.TAREA_HECHA:
        hecha_en = datetime.fromisoformat(aparicion["hecha_en"])
        raise ValueError(
            f'"{aparicion["texto"]}" ya está hecha: la marcó {aparicion["hecha_por"]} a las {hecha_en:%H:%M}.'
        )


def _anotar_marca(conexion, tarea_id: int, dia: date, accion: str, minutos, usuario_id: int, ahora: datetime):
    conexion.execute(
        "INSERT INTO tareas_turno_marcas (tarea_id, dia, accion, minutos, usuario_id, fecha) VALUES (?, ?, ?, ?, ?, ?)",
        (tarea_id, dia.isoformat(), accion, minutos, usuario_id, _texto(ahora)),
    )


def marcar_hecha(usuario_id: int, tarea_id: int, dia, ahora=None):
    """TAREA HECHA (del aviso o de la grilla): queda con quién y a qué hora, y deja
    de avisar. Una sola vez por día (ValueError si ya estaba). Se puede marcar antes
    de su hora: quien ya prendió las luces no tiene por qué esperar el aviso."""
    usuarios_repo.usuario_habilitado(usuario_id)
    ahora = _como_momento(ahora)
    dia = _como_dia(dia)
    with conexion_db() as conexion:
        # Lo que se mira (si ya está hecha) y lo que se graba, en la misma
        # transacción (regla 8), con el permiso de escritura tomado antes de mirar.
        # Hoy todo esto lo escribe solo el hilo de Qt del mostrador (el aviso es modal
        # y Tareas del Turno no está en la lista blanca), así que "a la vez" no pasa;
        # pero si algún día otra conexión las escribe, la segunda espera, ve la
        # primera y avisa quién fue, en vez de chocar con el índice único.
        conexion.execute("BEGIN IMMEDIATE")
        aparicion = _la_aparicion(conexion, tarea_id, dia, ahora, "marcarla como hecha")
        _exigir_que_no_este_hecha(aparicion)
        _anotar_marca(conexion, aparicion["tarea_id"], dia, dominio.ACCION_TAREA_HECHA, None, usuario_id, ahora)


def posponer(usuario_id: int, tarea_id: int, dia, minutos: int, ahora=None) -> str:
    """POSPONER 5 MIN / 10 MIN: queda una fila con quién, cuándo y los minutos, y la
    tarea no vuelve a avisar hasta entonces. Devuelve hasta cuándo (ISO). Solo los
    minutos de dominio.MINUTOS_PARA_POSPONER, y no a una que ya está hecha."""
    usuarios_repo.usuario_habilitado(usuario_id)
    if isinstance(minutos, bool) or minutos not in dominio.MINUTOS_PARA_POSPONER:
        raise ValueError(
            "Se pospone " + " o ".join(str(m) for m in dominio.MINUTOS_PARA_POSPONER) + " minutos."
        )
    minutos = int(minutos)
    ahora = _como_momento(ahora)
    dia = _como_dia(dia)
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        aparicion = _la_aparicion(conexion, tarea_id, dia, ahora, "posponerla")
        _exigir_que_no_este_hecha(aparicion)
        _anotar_marca(conexion, aparicion["tarea_id"], dia, dominio.ACCION_TAREA_POSPUESTA, minutos, usuario_id,
                      ahora)
    return _texto(ahora + timedelta(minutes=minutos))
