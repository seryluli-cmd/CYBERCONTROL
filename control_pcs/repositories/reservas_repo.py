"""
reservas_repo.py
==================
RESERVAS (pedido del dueño, 2026-10-20): un cliente reserva una PC, PCSTREAM o
la PlayStation 5 para más tarde u otro día (por ejemplo, la promo de 10 hs) y
paga en el momento una seña o todo. Cuando vuelve puede ser otro turno, con
otro operador.

Lo que resuelve es un problema de plata. Hasta acá, para habilitarle la PC al
que volvía había que "Cobrar" el bono como una venta nueva, y al operador que lo
habilitaba le faltaba en el Cierre de Turno una plata que nunca recibió. Ahora:

- Lo que se paga al reservar es una venta (Alquiler de PCs o PlayStation 5) en
  la caja de quien toma la reserva, y el resto, una venta en la caja de quien la
  habilita. Habilitar una reserva ya pagada NO crea ninguna venta: abre la sesión
  con el bono reservado (reservas_habilitar_repo.py, que se separó de este
  archivo por tamaño). Cada venta queda unida a su
  reserva en `reservas_pagos`, como un trámite en `tramites_venta`: Caja y Cierre
  de Turno la cuentan solas y la muestran en su renglón "Reservas"
  (turnos_ventas_repo._reservas_por_metodo). No hace falta otro origen de venta.
- El precio queda fijo el día que se reserva (se guarda en la reserva): lo que
  falta es ese precio menos lo pagado, aunque después cambie el bono.
- Si el cliente no viene (solo, a la hora + MINUTOS_TOLERANCIA_RESERVA, o antes
  con "No vino"): si dejó seña, la pierde ("No vino"); si pagó todo, queda "A
  reprogramar" para darle otro día, ya con cualquier PC disponible, y vence a los
  DIAS_PARA_REPROGRAMAR_RESERVA. Nada de eso mueve plata: ya está en la caja
  donde entró.
- Devolver la plata (corte de luz, PC rota, el local cancela): solo el Admin.
  Es una venta en negativo en la caja de AHORA (sale del cajón de quien la
  entrega); el cierre del turno en que entró no se toca.

Las decisiones son del dueño (PROPUESTA_RESERVAS.md, en la carpeta de los
proyectos). La parte 2 (la PC marcada RESERVADA en el mosaico, el aviso al
venderle un bono que se pase de la hora, el socio que se corta a la hora y el
cartel en la pantalla de bloqueo) está en reservas_horario_repo.py.

Cobrar es del mostrador: nada de esto está en lo que se puede pedir desde otra
PC (admin_remoto/lista_blanca.py) y la ventana no se abre allá.
"""

import unicodedata
from datetime import datetime, timedelta

import dominio
from database import conexion_db
from repositories import usuarios_repo, ventas_repo
from turnos import dia_en_que_empezo_el_turno, limites_de_los_dias
from control_pcs.repositories import pcs_repo, pcstream_repo, playstation_repo

# Cuántas reservas ya terminadas (habilitadas, no vino, vencidas, devueltas)
# muestra la ventana debajo de las que esperan: las más nuevas.
LIMITE_TERMINADAS = 200


def _catalogo(equipo: str):
    """El repo con el catálogo de bonos de ese equipo: cada uno cobra con el suyo
    y nunca se mezclan (CLAUDE.md, "Hay CUATRO catálogos de bonos")."""
    if equipo == dominio.EQUIPO_RESERVA_PCSTREAM:
        return pcstream_repo
    if equipo == dominio.EQUIPO_RESERVA_PLAYSTATION:
        return playstation_repo
    return pcs_repo


def _origen(equipo: str) -> str:
    """Como qué negocio entra la plata: PCSTREAM es una PC (Alquiler de PCs)."""
    if equipo == dominio.EQUIPO_RESERVA_PLAYSTATION:
        return dominio.ORIGEN_PLAYSTATION
    return dominio.ORIGEN_ALQUILER_PCS


def _iso(momento: datetime) -> str:
    return momento.isoformat(timespec="microseconds")


# ---------------------------------------------------------------------
# Qué se puede reservar
# ---------------------------------------------------------------------

def equipos_para_reservar() -> list:
    """
    Lo que se puede elegir como equipo de una reserva nueva, en el orden en que
    se muestra: "Cualquier PC disponible", cada PC común activa (en orden
    natural), PCSTREAM si existe y la PlayStation 5. Cada uno es {"equipo",
    "estacion_id", "nombre"}; estacion_id es None en "cualquier PC" y en PCSTREAM
    y la consola, que son una sola.
    """
    opciones = [{"equipo": dominio.EQUIPO_RESERVA_PC, "estacion_id": None,
                 "nombre": dominio.NOMBRE_RESERVA_CUALQUIER_PC}]
    hay_pcstream = False
    for estacion in pcs_repo.listar_estaciones():
        if dominio.es_pcstream(estacion["nombre"]):
            hay_pcstream = True
            continue
        opciones.append({"equipo": dominio.EQUIPO_RESERVA_PC, "estacion_id": estacion["id"],
                         "nombre": estacion["nombre"]})
    if hay_pcstream:
        opciones.append({"equipo": dominio.EQUIPO_RESERVA_PCSTREAM, "estacion_id": None,
                         "nombre": dominio.NOMBRE_PCSTREAM})
    opciones.append({"equipo": dominio.EQUIPO_RESERVA_PLAYSTATION, "estacion_id": None,
                     "nombre": dominio.NOMBRE_PLAYSTATION})
    return opciones


def bonos_para(equipo: str) -> list:
    """Los bonos activos del catálogo de ese equipo, para elegir el de la reserva."""
    return _catalogo(equipo).listar_bonos()


def _validar_equipo(conexion, equipo: str, estacion_id):
    """Levanta ValueError si el equipo no se puede reservar: una PC puntual tiene
    que estar activa y no ser PCSTREAM (tiene sus precios), y para reservar
    PCSTREAM tiene que existir."""
    if equipo not in dominio.EQUIPOS_RESERVA:
        raise ValueError("Elegí qué equipo se reserva.")
    if equipo == dominio.EQUIPO_RESERVA_PC and estacion_id is not None:
        estacion = conexion.execute(
            "SELECT nombre FROM estaciones WHERE id = ? AND activa = 1", (estacion_id,)
        ).fetchone()
        if estacion is None:
            raise ValueError("Esa PC ya no está disponible. Actualizá la pantalla e intentá de nuevo.")
        if dominio.es_pcstream(estacion["nombre"]):
            raise ValueError(f"{dominio.NOMBRE_PCSTREAM} se reserva con sus propios bonos: elegila de la lista.")
    if equipo == dominio.EQUIPO_RESERVA_PCSTREAM and _estacion_pcstream(conexion) is None:
        raise ValueError(f"No hay ninguna PC llamada {dominio.NOMBRE_PCSTREAM}.")


def _estacion_pcstream(conexion):
    """La estación activa que es PCSTREAM (se la reconoce por el nombre), o None."""
    for estacion in conexion.execute("SELECT * FROM estaciones WHERE activa = 1"):
        if dominio.es_pcstream(estacion["nombre"]):
            return estacion
    return None


def _validar_horario(conexion, equipo: str, estacion_id, inicio: datetime, minutos: int, ahora: datetime,
                     excluir_id: int = None):
    """
    Levanta ValueError si la hora ya pasó, o si ese mismo equipo (la PC puntual,
    PCSTREAM o la consola) ya tiene otra reserva pendiente que se pisa con esta:
    de su hora a su hora + los minutos del bono. "Cualquier PC disponible" no
    aparta ninguna PC (decisión del dueño), así que no choca con nada.
    """
    if inicio <= ahora:
        raise ValueError("Esa hora ya pasó: elegí un día y una hora que todavía no llegaron.")
    if equipo == dominio.EQUIPO_RESERVA_PC and estacion_id is None:
        return
    fin = inicio + timedelta(minutes=minutos)
    otras = conexion.execute(
        """
        SELECT reservas.id, reservas.cliente, reservas.fecha_reserva, reservas.minutos
        FROM reservas
        WHERE reservas.estado = ? AND reservas.equipo = ? AND reservas.id IS NOT ?
          AND (reservas.estacion_id = ? OR (? IS NULL AND reservas.estacion_id IS NULL))
        """,
        (dominio.RESERVA_PENDIENTE, equipo, excluir_id, estacion_id, estacion_id),
    ).fetchall()
    for otra in otras:
        otra_inicio = datetime.fromisoformat(otra["fecha_reserva"])
        otra_fin = otra_inicio + timedelta(minutes=otra["minutos"])
        if inicio < otra_fin and otra_inicio < fin:
            raise ValueError(
                f"Ese equipo ya está reservado de {otra_inicio:%d/%m %H:%M} a {otra_fin:%H:%M} "
                f"(reserva Nº {otra['id']}, {otra['cliente']}). Elegí otro horario u otro equipo."
            )


def _validar_reserva_nueva(conexion, equipo: str, estacion_id, bono_id: int, inicio: datetime, monto: float,
                           ahora: datetime):
    """Todo lo que controla crear_reserva antes de grabar. Devuelve el bono."""
    _validar_equipo(conexion, equipo, estacion_id)
    bono = _catalogo(equipo).obtener_bono(bono_id) if bono_id is not None else None
    if bono is None or not bono["activo"]:
        raise ValueError("Ese bono ya no está disponible.")
    monto = round(monto, 2)
    if monto <= 0:
        raise ValueError("Lo que paga ahora tiene que ser más que cero: la reserva se toma con una seña o con todo.")
    if monto > round(bono["precio"], 2):
        raise ValueError("Lo que paga ahora no puede ser más que el precio del bono.")
    _validar_horario(conexion, equipo, estacion_id, inicio, bono["minutos"], ahora)
    return bono


def revisar_reserva(equipo: str, estacion_id, bono_id: int, inicio: datetime, monto: float):
    """
    Lo mismo que controla crear_reserva, sin grabar nada (ValueError con el
    motivo): la pantalla lo pregunta ANTES de abrir el cobro, así nunca se cobra
    una reserva que después no se puede guardar. crear_reserva lo vuelve a
    controlar.
    """
    with conexion_db() as conexion:
        _validar_reserva_nueva(conexion, equipo, estacion_id, bono_id, inicio, monto, datetime.now())


def crear_reserva(usuario_id: int, cliente: str, celular: str, equipo: str, estacion_id, bono_id: int,
                  inicio: datetime, monto: float, pagos: list) -> int:
    """
    Toma una reserva y cobra lo que paga ahora (`monto`: una seña o todo, más de
    cero y hasta el precio del bono). `pagos` son los de la ventana de cobro
    (ui.dialogo_pago.cobrar) y tienen que cubrir `monto`. Devuelve el número de
    la reserva.

    `equipo` es dominio.EQUIPO_RESERVA_*; `estacion_id`, la PC pedida (None =
    cualquier PC disponible; siempre None para PCSTREAM y la consola). `inicio` es
    el día y la hora a la que viene (los segundos se descartan).

    La reserva, la venta y su vínculo se graban juntos (regla 8): la venta entra
    en la caja abierta, a nombre de quien cobra (cajas_repo._quien_vende), como
    cualquier otra.
    """
    cliente = (cliente or "").strip()
    if not cliente:
        raise ValueError("Escribí el nombre del cliente.")
    monto = round(monto, 2)
    if sum(pago["monto"] for pago in pagos) < monto - 0.01:
        raise ValueError("Los pagos no cubren lo que paga ahora.")
    if equipo != dominio.EQUIPO_RESERVA_PC:
        estacion_id = None
    inicio = inicio.replace(second=0, microsecond=0)
    usuarios_repo.usuario_habilitado(usuario_id)

    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        bono = _validar_reserva_nueva(conexion, equipo, estacion_id, bono_id, inicio, monto, ahora)
        reserva_id = conexion.execute(
            """
            INSERT INTO reservas (fecha_creacion, usuario_id, cliente, celular, equipo, estacion_id, bono_id,
                                  bono_nombre, minutos, precio, fecha_reserva, estado, estado_desde, estado_por)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (_iso(ahora), usuario_id, cliente, (celular or "").strip(), equipo, estacion_id, bono["id"],
             bono["nombre"], bono["minutos"], round(bono["precio"], 2), inicio.isoformat(timespec="seconds"),
             dominio.RESERVA_PENDIENTE, _iso(ahora), usuario_id),
        ).lastrowid
        _cobrar(conexion, reserva_id, dominio.PAGO_RESERVA_ANTICIPO, usuario_id, monto, pagos, equipo, ahora)
    return reserva_id


def _cobrar(conexion, reserva_id: int, tipo: str, usuario_id: int, monto: float, pagos: list, equipo: str,
            ahora: datetime) -> int:
    """Una venta de la reserva (sin detalle, ver ventas_repo.registrar_venta_sin_detalle)
    y su vínculo, en la transacción de quien llama. Devuelve el id de la venta."""
    venta_id = ventas_repo.registrar_venta_sin_detalle(conexion, usuario_id, monto, pagos, _origen(equipo), ahora)
    conexion.execute(
        "INSERT INTO reservas_pagos (reserva_id, venta_id, tipo) VALUES (?, ?, ?)", (reserva_id, venta_id, tipo)
    )
    return venta_id


# ---------------------------------------------------------------------
# La lista
# ---------------------------------------------------------------------

def _pagado(conexion, reserva_id: int) -> float:
    """Lo que la reserva tiene pagado hoy: sus ventas confirmadas (una anulada
    desde Consulta de Ventas deja de contar; una devolución resta)."""
    return round(conexion.execute(
        """
        SELECT COALESCE(SUM(ventas.total), 0) AS pagado
        FROM reservas_pagos JOIN ventas ON ventas.id = reservas_pagos.venta_id
        WHERE reservas_pagos.reserva_id = ? AND ventas.estado = ?
        """,
        (reserva_id, dominio.VENTA_CONFIRMADA),
    ).fetchone()["pagado"], 2)


def _estado_si_no_viene(conexion, reserva) -> str:
    """Con seña la pierde (No vino); si pagó todo, A reprogramar (decisión del dueño)."""
    if _pagado(conexion, reserva["id"]) >= round(reserva["precio"], 2) - 0.009:
        return dominio.RESERVA_A_REPROGRAMAR
    return dominio.RESERVA_NO_VINO


def _pasar_las_vencidas(conexion, ahora: datetime):
    """
    Las reservas que cambian solas de estado: una pendiente cuyo cliente no
    llegó a la hora + MINUTOS_TOLERANCIA_RESERVA pasa a No vino o A reprogramar,
    y una A reprogramar que nadie reprogramó en DIAS_PARA_REPROGRAMAR_RESERVA,
    a Vencida. Queda anotado desde cuándo (la hora en que venció, no la de ahora)
    y que lo hizo el programa (estado_por en NULL). No mueve plata.

    No hay un reloj que lo haga: se hace al mirar la lista. Cada UPDATE vuelve a
    pedir el estado de antes, por si justo la habilitaron.
    """
    tolerancia = timedelta(minutes=dominio.MINUTOS_TOLERANCIA_RESERVA)
    vencidas = conexion.execute(
        "SELECT * FROM reservas WHERE estado = ? AND fecha_reserva < ?",
        (dominio.RESERVA_PENDIENTE, (ahora - tolerancia).isoformat(timespec="seconds")),
    ).fetchall()
    for reserva in vencidas:
        desde = datetime.fromisoformat(reserva["fecha_reserva"]) + tolerancia
        conexion.execute(
            "UPDATE reservas SET estado = ?, estado_desde = ?, estado_por = NULL WHERE id = ? AND estado = ?",
            (_estado_si_no_viene(conexion, reserva), _iso(desde), reserva["id"], dominio.RESERVA_PENDIENTE),
        )

    plazo = timedelta(days=dominio.DIAS_PARA_REPROGRAMAR_RESERVA)
    for reserva in conexion.execute(
        "SELECT id, estado_desde FROM reservas WHERE estado = ? AND estado_desde < ?",
        (dominio.RESERVA_A_REPROGRAMAR, _iso(ahora - plazo)),
    ).fetchall():
        conexion.execute(
            "UPDATE reservas SET estado = ?, estado_desde = ?, estado_por = NULL WHERE id = ? AND estado = ?",
            (dominio.RESERVA_VENCIDA, _iso(datetime.fromisoformat(reserva["estado_desde"]) + plazo),
             reserva["id"], dominio.RESERVA_A_REPROGRAMAR),
        )


def actualizar_estados(ahora: datetime = None):
    """Pasa de estado las reservas que vencieron (ver _pasar_las_vencidas). La
    llama listar_reservas; `ahora` es para las pruebas."""
    with conexion_db() as conexion:
        _pasar_las_vencidas(conexion, ahora or datetime.now())


_SELECT_RESERVAS = """
    SELECT reservas.*, estaciones.nombre AS estacion_nombre, habilitada.nombre AS habilitada_nombre,
           COALESCE((SELECT SUM(ventas.total) FROM reservas_pagos
                     JOIN ventas ON ventas.id = reservas_pagos.venta_id
                     WHERE reservas_pagos.reserva_id = reservas.id AND ventas.estado = ?), 0) AS pagado
    FROM reservas
    LEFT JOIN estaciones ON estaciones.id = reservas.estacion_id
    LEFT JOIN estaciones AS habilitada ON habilitada.id = reservas.estacion_habilitada_id
"""


def _armar(fila) -> dict:
    """Una fila de reservas lista para la pantalla: sus columnas más "equipo_nombre"
    (la PC pedida, "Cualquier PC disponible", PCSTREAM o la consola),
    "habilitada_en", "pagado", "falta" y, si está A reprogramar, "vence"."""
    reserva = dict(fila)
    reserva["equipo_nombre"] = dominio.nombre_equipo_reservado(reserva["equipo"], reserva["estacion_nombre"])
    reserva["habilitada_en"] = (
        dominio.NOMBRE_PLAYSTATION if reserva["sesion_playstation_id"] is not None else reserva["habilitada_nombre"]
    )
    reserva["pagado"] = round(reserva["pagado"], 2)
    reserva["falta"] = max(0.0, round(reserva["precio"] - reserva["pagado"], 2))
    reserva["vence"] = None
    if reserva["estado"] == dominio.RESERVA_A_REPROGRAMAR:
        reserva["vence"] = (
            datetime.fromisoformat(reserva["estado_desde"]) + timedelta(days=dominio.DIAS_PARA_REPROGRAMAR_RESERVA)
        ).isoformat(timespec="seconds")
    return reserva


def _sin_acentos(texto: str) -> str:
    """Para buscar sin mayúsculas ni acentos ("perez" encuentra "Pérez")."""
    return "".join(
        letra for letra in unicodedata.normalize("NFD", (texto or "").lower()) if not unicodedata.combining(letra)
    )


def _coincide(reserva: dict, buscar: str) -> bool:
    """Si la reserva es de un cliente o un celular que se parece a `buscar`: el
    nombre sin mayúsculas ni acentos, o los números del celular sin espacios ni
    guiones."""
    buscado = _sin_acentos(buscar).strip()
    if not buscado:
        return True
    if buscado in _sin_acentos(reserva["cliente"]):
        return True
    digitos = "".join(c for c in buscado if c.isdigit())
    return bool(digitos) and digitos in "".join(c for c in reserva["celular"] if c.isdigit())


def listar_reservas(solo_abiertas: bool = False, buscar: str = "", ahora: datetime = None) -> list:
    """
    Las reservas para la ventana RESERVAS, ya con su estado al día (ver
    _pasar_las_vencidas): primero las que esperan al cliente (Pendiente y A
    reprogramar), de la más próxima a la más lejana; después, salvo con
    `solo_abiertas`, las terminadas, de la más nueva a la más vieja (las últimas
    LIMITE_TERMINADAS). `buscar` filtra por cliente o celular. Cada una, con la
    forma de _armar.
    """
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        _pasar_las_vencidas(conexion, ahora)
        abiertas = conexion.execute(
            _SELECT_RESERVAS + " WHERE reservas.estado IN (?, ?) ORDER BY reservas.fecha_reserva, reservas.id",
            (dominio.VENTA_CONFIRMADA, *dominio.ESTADOS_RESERVA_ABIERTA),
        ).fetchall()
        terminadas = [] if solo_abiertas else conexion.execute(
            _SELECT_RESERVAS + " WHERE reservas.estado NOT IN (?, ?) ORDER BY reservas.id DESC LIMIT ?",
            (dominio.VENTA_CONFIRMADA, *dominio.ESTADOS_RESERVA_ABIERTA, LIMITE_TERMINADAS),
        ).fetchall()
    return [reserva for reserva in map(_armar, [*abiertas, *terminadas]) if _coincide(reserva, buscar)]


def obtener_reserva(reserva_id: int) -> dict:
    """
    Una reserva (con la forma de _armar) más "pagos": cada venta suya, de la
    primera a la última, como {"tipo", "venta_id", "fecha", "monto", "anulada",
    "operador", "caja_numero"} -- quién la cobró y en qué caja quedó, para decir
    al habilitarla dónde está esa plata. ValueError si no existe.
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            _SELECT_RESERVAS + " WHERE reservas.id = ?", (dominio.VENTA_CONFIRMADA, reserva_id)
        ).fetchone()
        if fila is None:
            raise ValueError("Esa reserva no existe.")
        pagos = conexion.execute(
            """
            SELECT reservas_pagos.tipo, ventas.id AS venta_id, ventas.fecha, ventas.total AS monto,
                   ventas.estado, usuarios.nombre AS operador, ventas_caja.caja_id AS caja_numero
            FROM reservas_pagos
            JOIN ventas ON ventas.id = reservas_pagos.venta_id
            JOIN usuarios ON usuarios.id = ventas.usuario_id
            LEFT JOIN ventas_caja ON ventas_caja.venta_id = ventas.id
            WHERE reservas_pagos.reserva_id = ?
            ORDER BY ventas.id
            """,
            (reserva_id,),
        ).fetchall()
    reserva = _armar(fila)
    reserva["pagos"] = [
        {"tipo": pago["tipo"], "venta_id": pago["venta_id"], "fecha": pago["fecha"], "monto": pago["monto"],
         "anulada": pago["estado"] == dominio.VENTA_ANULADA, "operador": pago["operador"],
         "caja_numero": pago["caja_numero"]}
        for pago in pagos
    ]
    return reserva


def reservas_de_hoy(ahora: datetime = None) -> int:
    """Cuántas reservas esperan hoy (el día del local, de 06:00 a 06:00) y todavía
    no pasaron su tolerancia: el número del botón Reservas de la barra. Solo lee."""
    ahora = ahora or datetime.now()
    hoy = dia_en_que_empezo_el_turno(ahora)
    desde, hasta = limites_de_los_dias(hoy, hoy)
    todavia = (ahora - timedelta(minutes=dominio.MINUTOS_TOLERANCIA_RESERVA)).isoformat(timespec="seconds")
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT COUNT(*) AS n FROM reservas
            WHERE estado = ? AND fecha_reserva >= ? AND fecha_reserva < ? AND fecha_reserva >= ?
            """,
            (dominio.RESERVA_PENDIENTE, desde, hasta, todavia),
        ).fetchone()["n"]


# ---------------------------------------------------------------------
# Una reserva puntual (habilitarla está en reservas_habilitar_repo.py)
# ---------------------------------------------------------------------

def _reserva_o_error(conexion, reserva_id: int):
    reserva = conexion.execute("SELECT * FROM reservas WHERE id = ?", (reserva_id,)).fetchone()
    if reserva is None:
        raise ValueError("Esa reserva no existe.")
    return reserva


def _reserva_abierta(conexion, reserva_id: int):
    """La reserva, si todavía espera al cliente (Pendiente o A reprogramar);
    si no, ValueError: otra persona la habilitó o la cambió mientras tanto."""
    reserva = _reserva_o_error(conexion, reserva_id)
    if reserva["estado"] not in dominio.ESTADOS_RESERVA_ABIERTA:
        raise ValueError("Esta reserva ya no está esperando al cliente. Actualizá la lista.")
    return reserva


# ---------------------------------------------------------------------
# No vino, reprogramar, devolver
# ---------------------------------------------------------------------

def marcar_no_vino(reserva_id: int, usuario_id: int) -> str:
    """
    El cliente avisó que no viene, o no llegó y no hace falta esperar a que pase
    sola: con seña queda No vino (la pierde), si pagó todo, A reprogramar. No
    mueve plata. Solo para una Pendiente. Devuelve el estado en que quedó.
    """
    usuarios_repo.usuario_habilitado(usuario_id)
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        reserva = _reserva_o_error(conexion, reserva_id)
        if reserva["estado"] != dominio.RESERVA_PENDIENTE:
            raise ValueError("Solo una reserva Pendiente se puede marcar como que no vino.")
        estado = _estado_si_no_viene(conexion, reserva)
        conexion.execute(
            "UPDATE reservas SET estado = ?, estado_desde = ?, estado_por = ? WHERE id = ?",
            (estado, _iso(datetime.now()), usuario_id, reserva_id),
        )
    return estado


def reprogramar(reserva_id: int, usuario_id: int, inicio: datetime, estacion_id=None):
    """
    Otro día u otra hora para una reserva que espera (Pendiente, o A reprogramar:
    vuelve a Pendiente). Una de PC que quedó A reprogramar ya no elige PC
    (decisión del dueño): vuelve como "cualquier PC disponible" aunque venga
    `estacion_id`. Una Pendiente de PC puede cambiar de PC. PCSTREAM y la consola
    son una sola y siguen siendo las mismas. No mueve plata: el precio y lo
    pagado no cambian.
    """
    usuarios_repo.usuario_habilitado(usuario_id)
    inicio = inicio.replace(second=0, microsecond=0)
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        reserva = _reserva_abierta(conexion, reserva_id)
        if reserva["equipo"] != dominio.EQUIPO_RESERVA_PC or reserva["estado"] == dominio.RESERVA_A_REPROGRAMAR:
            estacion_id = None
        _validar_equipo(conexion, reserva["equipo"], estacion_id)
        _validar_horario(conexion, reserva["equipo"], estacion_id, inicio, reserva["minutos"], ahora,
                         excluir_id=reserva_id)
        conexion.execute(
            """
            UPDATE reservas SET fecha_reserva = ?, estacion_id = ?, estado = ?, estado_desde = ?, estado_por = ?
            WHERE id = ?
            """,
            (inicio.isoformat(timespec="seconds"), estacion_id, dominio.RESERVA_PENDIENTE, _iso(ahora),
             usuario_id, reserva_id),
        )


def devolver(reserva_id: int, usuario_id: int, metodo: str, motivo: str) -> float:
    """
    Le devuelve al cliente TODO lo que tiene pagado una reserva que no se usó
    (corte de luz, PC rota, el local cancela: si dejó seña y no vino, la pierde,
    así que esto es para excepciones). Solo un Administrador (PermissionError si
    no), con un motivo.

    La devolución es una venta en negativo, del negocio de la reserva, en la caja
    abierta AHORA (a nombre de la responsable, como todo lo que cobra el Admin:
    cajas_repo._quien_vende): sale del cajón de quien entrega la plata y su sobre
    la descuenta. El cierre del turno en que había entrado no se toca. `metodo`
    dice si se devuelve en efectivo (del cajón) o por transferencia (digital).
    Devuelve lo devuelto.
    """
    usuarios_repo.exigir_admin(usuario_id, "devolver la plata de una reserva")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Escribí por qué se devuelve la plata.")
    if metodo not in dominio.METODOS_PAGO:
        raise ValueError("Elegí cómo se devuelve: en efectivo o digital.")
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        reserva = _reserva_o_error(conexion, reserva_id)
        if reserva["estado"] in (dominio.RESERVA_HABILITADA, dominio.RESERVA_DEVUELTA):
            raise ValueError("Esa reserva ya se usó o ya se devolvió: no hay plata para devolver.")
        pagado = _pagado(conexion, reserva_id)
        if pagado <= 0:
            raise ValueError("Esa reserva no tiene plata cobrada para devolver.")
        _cobrar(conexion, reserva_id, dominio.PAGO_RESERVA_DEVOLUCION, usuario_id, -pagado,
                [{"metodo": metodo, "monto": -pagado}], reserva["equipo"], ahora)
        conexion.execute(
            """
            UPDATE reservas SET estado = ?, estado_desde = ?, estado_por = ?, motivo_devolucion = ?
            WHERE id = ?
            """,
            (dominio.RESERVA_DEVUELTA, _iso(ahora), usuario_id, motivo, reserva_id),
        )
    return pagado
