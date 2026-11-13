"""
ofertas_repo.py
================
Las OFERTAS de los bonos (pedido del dueño, 2026-11-13: "quiero poder activar
precios especiales, 2x1 o 50%... elegir qué día, qué turno y cuándo termina...
tal vez solo en ciertos bonos"). La ventana es control_pcs/ui/ofertas_window.py
(la maqueta B, "la semana en una grilla"); en el panel de la PC se ven con la
maqueta P1 (cartel arriba de los bonos y la etiqueta en el botón). Las dos las
eligió el dueño entre las de PROPUESTA_OFERTAS.

Reglas (decididas con el dueño):
- 2x1: el precio de siempre y el doble de tiempo. 50%: el tiempo de siempre y
  la mitad de la plata, redondeada al peso (`con_oferta`).
- Vale la hora en que se COBRA el bono (`momento_del_cobro`). La Noche del
  viernes va del viernes 22:00 al sábado 06:00, y el domingo tiene sus dos
  turnos, T1 y T2 (los cuadritos de la semana: `franjas_de_la_semana`).
- Solo los bonos fijos de las PCs, de PCSTREAM y de la PlayStation 5
  (dominio.EQUIPOS_CON_OFERTA). Nunca los de Socios ni la carga de saldo por
  monto, y las reservas siempre sin oferta: su precio queda fijo al reservar.
- Un bono anotado a la Cuenta de la PC durante la oferta la conserva aunque se
  cobre después: el tiempo de más ya se le dio al anotarlo.
- Dos ofertas no pueden tocar el mismo bono en el mismo turno del mismo día
  (`ChocaConOtraOferta`): cada bono tiene una sola oferta a la vez, así nunca
  hay dudas de qué precio va.
- Solo el Administrador las arma, pausa y termina: se exige acá, no solo en la
  pantalla. Nada se borra: una oferta terminada queda en la lista.
- Lo vendido guarda con qué oferta se vendió (`oferta_id` en sesion_bonos,
  sesion_pcstream_bonos, sesion_playstation_bonos y cuenta_pc_items), con los
  minutos y el precio que se cobraron de verdad: anular un bono, los reintegros
  y los reportes siguen andando sin saber nada de ofertas.

Quién la aplica al vender: pcs_repo.asignar_bono (PCs y PCSTREAM),
playstation_repo.vender_bono y cuentas_pc_repo.anotar_bono, los tres con
`como_se_vende` dentro de su transacción.
"""

import json
import math
from datetime import date, datetime, timedelta

import dominio
import turnos
from database import conexion_db
from repositories import usuarios_repo

# Cuánto puede quedar abierta la ventana de cobro y seguir valiendo el precio que
# se mostró al abrirla (ver momento_del_cobro).
MINUTOS_PARA_TERMINAR_DE_COBRAR = 30

LARGO_MAXIMO_DEL_NOMBRE = 40

# Una oferta dura como mucho un año: alcanza de sobra y pone un tope a las cuentas
# que recorren sus días.
DIAS_MAXIMOS = 366

# El catálogo de cada equipo (ver CLAUDE.md, "Hay CUATRO catálogos de bonos"). Acá
# se lee la tabla directo, sin importar pcs_repo ni playstation_repo: los dos
# importan este módulo para vender.
_TABLA_DEL_CATALOGO = {
    dominio.EQUIPO_RESERVA_PC: "bonos_tiempo",
    dominio.EQUIPO_RESERVA_PCSTREAM: "bonos_pcstream",
    dominio.EQUIPO_RESERVA_PLAYSTATION: "bonos_playstation",
}

# Cómo se nombra cada catálogo en una frase ("Promo 3hs de las PCs").
DE_CADA_EQUIPO = {
    dominio.EQUIPO_RESERVA_PC: "de las PCs",
    dominio.EQUIPO_RESERVA_PCSTREAM: f"de {dominio.NOMBRE_PCSTREAM}",
    dominio.EQUIPO_RESERVA_PLAYSTATION: "de la PlayStation 5",
}

DIAS = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábado", "domingo")
DIAS_EN_PLURAL = ("lunes", "martes", "miércoles", "jueves", "viernes", "sábados", "domingos")
DOMINGO = 6

# Un lunes cualquiera: para preguntarle a turnos.py por "el turno X del día de la
# semana N" sin una fecha concreta.
_UN_LUNES = date(2024, 1, 1)


class ChocaConOtraOferta(ValueError):
    """Lo que se quiere guardar toca un bono y un turno que ya tiene otra oferta.
    `otra` es el nombre de esa otra oferta; el mensaje ya dice qué hacer."""

    def __init__(self, mensaje: str, otra: str):
        super().__init__(mensaje)
        self.otra = otra


# ---------------------------------------------------------------------
# La semana: cada cuadrito es un día y un turno
# ---------------------------------------------------------------------

def _un_dia(dia_semana: int) -> date:
    return _UN_LUNES + timedelta(days=dia_semana)


def franjas_de_la_semana() -> list:
    """Todos los cuadritos de la grilla, en orden: (día de la semana, turno), con
    el día de 0 (lunes) a 6 (domingo). El domingo trae solo sus dos turnos
    (turnos.turnos_del_dia): MAÑANA es "Domingo T1" y NOCHE es "Domingo T2"."""
    return [(dia, turno) for dia in range(7) for turno in turnos.turnos_del_dia(_un_dia(dia))]


def franja_de(momento: datetime) -> tuple:
    """El cuadrito al que pertenece `momento`. A la madrugada es la Noche del día
    anterior: el sábado a las 03:00 es la Noche del VIERNES, y el lunes a las 03:00
    es "Domingo T2"."""
    return turnos.dia_en_que_empezo_el_turno(momento).weekday(), turnos.calcular_turno(momento)


def horario_de_la_franja(dia_semana: int, turno: str) -> tuple:
    """(inicio, fin) de un cuadrito como texto de horas ("22", "06")."""
    dia = _un_dia(dia_semana)
    return (f"{turnos.inicio_del_turno(dia, turno):%H}", f"{turnos.fin_del_turno(dia, turno):%H}")


def nombre_de_la_franja(dia_semana: int, turno: str) -> str:
    """El turno como se ve en la grilla y en las frases: "Noche (22 a 06)", o
    "T2 (18 a 06)" el domingo."""
    inicio, fin = horario_de_la_franja(dia_semana, turno)
    if dia_semana == DOMINGO:
        nombre = "T1" if turno == dominio.TURNO_MANANA else "T2"
    else:
        nombre = turno.capitalize()
    return f"{nombre} ({inicio} a {fin})"


# ---------------------------------------------------------------------
# Las cuentas (sin base: las usan también las pantallas)
# ---------------------------------------------------------------------

def con_oferta(tipo: str, minutos: int, precio: float) -> tuple:
    """(minutos, precio) de un bono con la oferta `tipo`: 2x1 da el doble de
    tiempo por la misma plata; 50% el mismo tiempo por la mitad, redondeada al peso
    (para arriba en los 50 centavos: el local no cobra centavos)."""
    if tipo == dominio.OFERTA_2X1:
        return minutos * 2, round(precio, 2)
    if tipo == dominio.OFERTA_MITAD:
        return minutos, float(math.floor(precio / 2 + 0.5))
    raise ValueError("Elegí si la oferta es 2x1 o 50%.")


def aplica_en(oferta: dict, momento: datetime) -> bool:
    """Si la oferta corre en `momento`: no está pausada ni terminada, el día del
    local cae entre sus fechas y el cuadrito de ese momento está marcado."""
    if oferta["pausada"]:
        return False
    if oferta["terminada_fecha"] is not None and momento >= oferta["terminada_fecha"]:
        return False
    if not oferta["desde"] <= turnos.dia_en_que_empezo_el_turno(momento) <= oferta["hasta"]:
        return False
    return franja_de(momento) in oferta["franjas"]


def proximas_veces(oferta: dict, ahora: datetime, cuantas: int = 5) -> list:
    """
    Las próximas veces que corre la oferta, la que está corriendo incluida, como
    (inicio, fin). Turnos marcados seguidos son una sola vez: la Tarde y la Noche
    del sábado van de las 14:00 a las 06:00. Una pausada o terminada no corre.
    """
    if oferta["pausada"] or oferta["terminada_fecha"] is not None:
        return []
    veces = []
    dia = max(oferta["desde"], turnos.dia_en_que_empezo_el_turno(ahora))
    tope = min(oferta["hasta"], dia + timedelta(days=DIAS_MAXIMOS))
    # Se junta una de más: la última pedida podría seguir al día siguiente.
    while dia <= tope and len(veces) <= cuantas:
        for turno in turnos.turnos_del_dia(dia):
            if (dia.weekday(), turno) not in oferta["franjas"]:
                continue
            inicio, fin = turnos.inicio_del_turno(dia, turno), turnos.fin_del_turno(dia, turno)
            if fin <= ahora:
                continue
            if veces and veces[-1][1] == inicio:
                veces[-1] = (veces[-1][0], fin)
            else:
                veces.append((inicio, fin))
        dia += timedelta(days=1)
    return veces[:cuantas]


def hasta_cuando(oferta: dict, momento: datetime):
    """Hasta qué hora corre la oferta que está corriendo en `momento` (el fin de
    este tramo de turnos seguidos), o None si no corre."""
    if not aplica_en(oferta, momento):
        return None
    veces = proximas_veces(oferta, momento, 1)
    return veces[0][1] if veces else None


def estado(oferta: dict, ahora: datetime) -> str:
    """Cómo está la oferta en `ahora` (uno de dominio.ESTADOS_OFERTA). TERMINADA
    también cuando ya no le queda ninguna vez por delante."""
    if oferta["terminada_fecha"] is not None:
        return dominio.OFERTA_TERMINADA
    if oferta["pausada"]:
        if turnos.dia_en_que_empezo_el_turno(ahora) > oferta["hasta"]:
            return dominio.OFERTA_TERMINADA
        return dominio.OFERTA_PAUSADA
    veces = proximas_veces(oferta, ahora, 1)
    if not veces:
        return dominio.OFERTA_TERMINADA
    return dominio.OFERTA_ACTIVA if veces[0][0] <= ahora else dominio.OFERTA_PROGRAMADA


def con_las_ofertas(equipo: str, bonos, ofertas: list) -> list:
    """
    Los `bonos` de un catálogo (filas, o lo que ya devolvió esta función) como se
    cobran con las `ofertas` que corren (las de `activas`). Cada uno, un dict con
    lo de su fila más "minutos" y "precio" con la oferta puesta,
    "minutos_sin_oferta", "precio_sin_oferta" y "oferta" (None, o un dict con su
    "id", "nombre", "tipo" y "hasta_el_fin"). Si dos ofertas tocaran el mismo bono
    (no se deja guardar así), gana la más vieja.
    """
    ordenadas = sorted(ofertas, key=lambda oferta: oferta["id"])
    resultado = []
    for fila in bonos:
        bono = dict(fila)
        minutos = bono.get("minutos_sin_oferta", bono["minutos"])
        precio = bono.get("precio_sin_oferta", bono["precio"])
        oferta = next((o for o in ordenadas if (equipo, bono["id"]) in o["bonos"]), None)
        bono["minutos_sin_oferta"], bono["precio_sin_oferta"] = minutos, precio
        if oferta is None:
            bono["minutos"], bono["precio"], bono["oferta"] = minutos, precio, None
        else:
            bono["minutos"], bono["precio"] = con_oferta(oferta["tipo"], minutos, precio)
            bono["oferta"] = {"id": oferta["id"], "nombre": oferta["nombre"], "tipo": oferta["tipo"],
                              "hasta_el_fin": oferta.get("hasta_el_fin")}
        resultado.append(bono)
    return resultado


# ---------------------------------------------------------------------
# Las frases (sin base: las usan también las pantallas)
# ---------------------------------------------------------------------

def y_lista(cosas) -> str:
    """"a", "a y b", "a, b y c"."""
    cosas = list(cosas)
    if len(cosas) <= 1:
        return "".join(cosas)
    return ", ".join(cosas[:-1]) + " y " + cosas[-1]


def _turnos_en_frase(dia_semana: int, turnos_del_grupo) -> str:
    if dia_semana != DOMINGO and len(turnos_del_grupo) == len(dominio.TURNOS):
        return "todo el día"
    nombres = [nombre_de_la_franja(dia_semana, turno) for turno in turnos_del_grupo]
    return ("en el turno " if len(nombres) == 1 else "en los turnos ") + y_lista(nombres)


def frase_de_cuando(oferta: dict) -> str:
    """Los días y turnos en castellano: "los viernes y sábados en el turno Noche (22
    a 06)", "de lunes a viernes en el turno Tarde (14 a 22) y los domingos en el
    turno T1 (06 a 18)". Una oferta de un solo día: "el sábado 31/10 en ..."."""
    por_dia = {}
    for dia, turno in franjas_de_la_semana():
        if (dia, turno) in oferta["franjas"]:
            por_dia.setdefault(dia, []).append(turno)
    if oferta["desde"] == oferta["hasta"]:
        dia = oferta["desde"].weekday()
        if dia not in por_dia:
            return ""
        return f"el {DIAS[dia]} {oferta['desde']:%d/%m} " + _turnos_en_frase(dia, por_dia[dia])
    grupos = {}  # mismos turnos -> los días que los tienen (el domingo siempre aparte)
    for dia, turnos_del_dia in por_dia.items():
        clave = ("domingo", tuple(turnos_del_dia)) if dia == DOMINGO else tuple(turnos_del_dia)
        grupos.setdefault(clave, []).append(dia)
    partes = []
    for dias in grupos.values():
        if dias == [0, 1, 2, 3, 4]:
            texto_dias = "de lunes a viernes"
        elif dias == [0, 1, 2, 3, 4, 5]:
            texto_dias = "de lunes a sábado"
        else:
            texto_dias = "los " + y_lista(DIAS_EN_PLURAL[dia] for dia in dias)
        partes.append(f"{texto_dias} {_turnos_en_frase(dias[0], por_dia[dias[0]])}")
    return y_lista(partes)


def frase_de_los_bonos(oferta: dict, nombres: dict) -> str:
    """"Promo 3hs y Promo 5hs de las PCs y Promo 2hs de la PlayStation 5".
    `nombres`: {(equipo, bono_id): nombre}."""
    por_equipo = {}
    for equipo, bono_id in oferta["bonos"]:
        por_equipo.setdefault(equipo, []).append(nombres.get((equipo, bono_id), "un bono dado de baja"))
    return y_lista(f"{y_lista(lista)} {DE_CADA_EQUIPO[equipo]}"
                   for equipo, lista in sorted(por_equipo.items(), key=lambda par: dominio.EQUIPOS_CON_OFERTA.index(par[0])))


def frase(oferta: dict, nombres: dict) -> str:
    """La oferta entera en castellano, para "Así queda:": "2x1 en Promo 3hs de las
    PCs, los viernes y sábados en el turno Noche (22 a 06), del 13/11 al 30/11."."""
    partes = [f"{oferta['tipo']} en {frase_de_los_bonos(oferta, nombres)}", frase_de_cuando(oferta)]
    if oferta["desde"] != oferta["hasta"]:
        partes.append(f"del {oferta['desde']:%d/%m} al {oferta['hasta']:%d/%m}")
    return ", ".join(parte for parte in partes if parte) + "."


def frase_de_la_vez(inicio: datetime, fin: datetime, ahora: datetime, ultima: bool = False) -> str:
    """Una de las `proximas_veces`, para la ventana: "Hoy, viernes 13/11, de 22:00 a
    06:00 — andando ahora". La que dura más de un día (turnos seguidos de varios
    días): "Del sábado 14/11 a las 14:00 al lunes 16/11 a las 06:00", o "Desde hoy,
    sábado 14/11 a las 14:00, hasta el lunes..." si empieza hoy. Con `ultima`,
    termina en "— la última"."""
    dia = inicio.date()
    cuando = f"{DIAS[dia.weekday()]} {dia:%d/%m}"
    es_hoy = dia == turnos.dia_en_que_empezo_el_turno(ahora)
    hasta = f"{DIAS[fin.weekday()]} {fin:%d/%m} a las {fin:%H:%M}"
    # Menos de un día: "de 22:00 a 06:00". Un día entero o más dice hasta qué día
    # (si no, "de 06:00 a 06:00" parecería que no dura nada).
    if fin - inicio < timedelta(hours=24):
        texto = f"{'hoy, ' if es_hoy else ''}{cuando}, de {inicio:%H:%M} a {fin:%H:%M}"
    elif es_hoy:
        texto = f"desde hoy, {cuando} a las {inicio:%H:%M}, hasta el {hasta}"
    else:
        texto = f"del {cuando} a las {inicio:%H:%M} al {hasta}"
    if inicio <= ahora:
        texto += " — andando ahora"
    elif ultima:
        texto += " — la última"
    return texto[0].upper() + texto[1:]


# ---------------------------------------------------------------------
# Leer
# ---------------------------------------------------------------------

def _como_oferta(fila) -> dict:
    oferta = dict(fila)
    oferta["franjas"] = [tuple(franja) for franja in json.loads(fila["franjas"])]
    oferta["bonos"] = [tuple(bono) for bono in json.loads(fila["bonos"])]
    oferta["desde"] = date.fromisoformat(fila["desde"])
    oferta["hasta"] = date.fromisoformat(fila["hasta"])
    oferta["pausada"] = bool(fila["pausada"])
    if fila["terminada_fecha"]:
        oferta["terminada_fecha"] = datetime.fromisoformat(fila["terminada_fecha"])
    return oferta


def _vigentes(conexion, momento: datetime) -> list:
    """Las ofertas que pueden correr en `momento`: sin terminar (o terminadas
    después) y con `hasta` en ese día del local o más adelante."""
    filas = conexion.execute(
        """
        SELECT * FROM ofertas
        WHERE (terminada_fecha IS NULL OR terminada_fecha > ?) AND hasta >= ?
        ORDER BY id
        """,
        (momento.isoformat(timespec="seconds"), turnos.dia_en_que_empezo_el_turno(momento).isoformat()),
    ).fetchall()
    return [_como_oferta(fila) for fila in filas]


def listar_ofertas() -> list:
    """Todas las ofertas, las terminadas también, cada una con su "estado" de este
    momento (dominio.ESTADOS_OFERTA). Las más nuevas primero."""
    ahora = datetime.now()
    with conexion_db() as conexion:
        ofertas = [_como_oferta(fila) for fila in conexion.execute("SELECT * FROM ofertas ORDER BY id DESC")]
    for oferta in ofertas:
        oferta["estado"] = estado(oferta, ahora)
    return ofertas


def activas(momento: datetime = None) -> list:
    """Las ofertas que corren en `momento` (ahora, si no se dice), cada una con
    "hasta_el_fin" (cuándo termina este tramo). La pide el panel de la PC en cada
    refresco, para la etiqueta de los bonos y el cartel de arriba."""
    momento = momento or datetime.now()
    with conexion_db() as conexion:
        ofertas = _vigentes(conexion, momento)
    resultado = []
    for oferta in ofertas:
        if aplica_en(oferta, momento):
            oferta["hasta_el_fin"] = hasta_cuando(oferta, momento)
            resultado.append(oferta)
    return resultado


# ---------------------------------------------------------------------
# Vender con la oferta (la usan pcs_repo, playstation_repo y cuentas_pc_repo)
# ---------------------------------------------------------------------

def momento_del_cobro(momento_del_precio, ahora: datetime) -> datetime:
    """
    La hora que vale para la oferta de un cobro: la que la pantalla usó para
    mostrar el precio al apretar Cobrar (`momento_del_precio`). Así, si la oferta
    termina con la ventana de cobro abierta (a las 06:00 en punto), se cobra lo que
    se mostró. Sin `momento_del_precio`, ahora. Más de
    MINUTOS_PARA_TERMINAR_DE_COBRAR atrás (o adelantado) no se acepta.
    """
    if momento_del_precio is None:
        return ahora
    if (momento_del_precio > ahora + timedelta(minutes=1)
            or ahora - momento_del_precio > timedelta(minutes=MINUTOS_PARA_TERMINAR_DE_COBRAR)):
        raise ValueError("La ventana de cobro quedó abierta mucho tiempo y el precio del bono puede haber "
                         "cambiado. Volvé a cobrarlo.")
    return momento_del_precio


def como_se_vende(conexion, equipo: str, bono, momento: datetime, bono_mostrado=None) -> dict:
    """
    El bono `bono` (fila de su catálogo) cobrado en `momento`, dentro de la
    transacción de quien vende: {"minutos", "precio", "oferta_id", "tipo"} (los dos
    últimos en None sin oferta).

    `bono_mostrado` es el bono como lo vio el operador al apretar Cobrar (el de
    con_las_ofertas, con lo que se le cobró al cliente). Si no da lo mismo, ValueError
    y no se graba nada: pasa si con la ventana de cobro abierta el Administrador
    pausó la oferta, la cambió, puso una nueva o cambió el precio del bono (terminarla
    no: queda fechada y vale lo que se mostró, ver momento_del_cobro). Sin esto la
    venta quedaría con un total distinto de la plata cobrada.
    """
    ofertas = [oferta for oferta in _vigentes(conexion, momento) if aplica_en(oferta, momento)]
    vendido = con_las_ofertas(equipo, [bono], ofertas)[0]
    oferta = vendido["oferta"]
    resultado = {"minutos": vendido["minutos"], "precio": round(vendido["precio"], 2),
                 "oferta_id": None if oferta is None else oferta["id"],
                 "tipo": None if oferta is None else oferta["tipo"]}
    if bono_mostrado is not None:
        oferta_mostrada = bono_mostrado.get("oferta")
        mostrado = (int(bono_mostrado["minutos"]), round(float(bono_mostrado["precio"]), 2),
                    None if oferta_mostrada is None else oferta_mostrada["id"])
        if mostrado != (resultado["minutos"], resultado["precio"], resultado["oferta_id"]):
            raise ValueError(
                f"El precio de «{bono['nombre']}» cambió mientras se cobraba (el Administrador pausó o cambió "
                "una oferta, puso una nueva o cambió el precio del bono), así que no se registró nada. Mirá "
                "cómo quedó el bono en la lista y volvé a cobrarlo."
            )
    return resultado


# ---------------------------------------------------------------------
# Armar, pausar y terminar (solo el Administrador)
# ---------------------------------------------------------------------

def _como_fecha(valor, cual: str) -> date:
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    try:
        return date.fromisoformat(str(valor)[:10])
    except ValueError:
        raise ValueError(f"La fecha {cual} no es válida.") from None


def _franjas_validas(franjas) -> list:
    validas = franjas_de_la_semana()
    elegidas = []
    for franja in franjas or ():
        franja = (int(franja[0]), str(franja[1]))
        if franja not in validas:
            raise ValueError("Uno de los cuadritos de la semana no es un turno del local.")
        if franja not in elegidas:
            elegidas.append(franja)
    if not elegidas:
        raise ValueError("Marcá en la semana al menos un día y un turno.")
    return sorted(elegidas, key=validas.index)


def _bonos_validos(conexion, bonos) -> tuple:
    """(lista de (equipo, bono_id) sin repetir, {(equipo, bono_id): nombre})."""
    elegidos, nombres = [], {}
    for equipo, bono_id in bonos or ():
        if equipo not in dominio.EQUIPOS_CON_OFERTA:
            # Los bonos de Socios nunca llevan oferta (decisión del dueño, 2026-11-13).
            raise ValueError("Las ofertas van solo en los bonos de las PCs, de PCSTREAM y de la PlayStation 5.")
        fila = conexion.execute(
            f"SELECT nombre, activo FROM {_TABLA_DEL_CATALOGO[equipo]} WHERE id = ?", (int(bono_id),)
        ).fetchone()
        if fila is None or not fila["activo"]:
            nombre = f"«{fila['nombre']}» " if fila is not None else ""
            raise ValueError(f"El bono {nombre}{DE_CADA_EQUIPO[equipo]} ya no está a la venta: sacalo de la oferta.")
        if (equipo, int(bono_id)) not in elegidos:
            elegidos.append((equipo, int(bono_id)))
            nombres[(equipo, int(bono_id))] = fila["nombre"]
    if not elegidos:
        raise ValueError("Elegí al menos un bono.")
    return elegidos, nombres


def _primer_choque(una: dict, otra: dict, ahora: datetime):
    """El primer (día de la semana, turno, (equipo, bono_id)) en que las dos
    ofertas tocarían el mismo bono, o None. Mira solo lo que comparten de ahora en
    adelante (desde el día del local, ver turnos.dia_en_que_empezo_el_turno, y sin los
    turnos de hoy que ya terminaron): lo que compartieron y ya pasó no le hace nada a
    nadie."""
    bonos = sorted(set(una["bonos"]) & set(otra["bonos"]))
    franjas = set(una["franjas"]) & set(otra["franjas"])
    if not bonos or not franjas:
        return None
    desde = max(una["desde"], otra["desde"], turnos.dia_en_que_empezo_el_turno(ahora))
    hasta = min(una["hasta"], otra["hasta"])
    dia = desde
    while dia <= hasta and dia < desde + timedelta(days=7):  # una semana ya tiene todos los días
        for turno in turnos.turnos_del_dia(dia):
            if (dia.weekday(), turno) in franjas and turnos.fin_del_turno(dia, turno) > ahora:
                return dia.weekday(), turno, bonos[0]
        dia += timedelta(days=1)
    return None


def _revisar_choques(conexion, oferta: dict, nombres: dict, ahora: datetime):
    """ChocaConOtraOferta si alguna oferta que no terminó (pausadas incluidas: se
    pueden reanudar) toca un bono de `oferta` en el mismo turno del mismo día."""
    filas = conexion.execute("SELECT * FROM ofertas WHERE terminada_fecha IS NULL ORDER BY id").fetchall()
    for otra in (_como_oferta(fila) for fila in filas):
        if otra["id"] == oferta.get("id") or estado(otra, ahora) == dominio.OFERTA_TERMINADA:
            continue
        choque = _primer_choque(oferta, otra, ahora)
        if choque is None:
            continue
        dia, turno, (equipo, bono_id) = choque
        bono = nombres.get((equipo, bono_id), "ese bono")
        raise ChocaConOtraOferta(
            f"«{otra['nombre']}» ya pone {otra['tipo']} en {bono} {DE_CADA_EQUIPO[equipo]} los "
            f"{DIAS_EN_PLURAL[dia]} en el turno {nombre_de_la_franja(dia, turno)}.\n\n"
            f"Para guardar «{oferta['nombre']}», sacale ese bono o ese turno, o terminá antes "
            f"«{otra['nombre']}». Así nunca hay dudas de qué precio va: cada bono tiene una sola "
            "oferta a la vez.",
            otra["nombre"],
        )


def _oferta(conexion, oferta_id: int) -> dict:
    fila = conexion.execute("SELECT * FROM ofertas WHERE id = ?", (oferta_id,)).fetchone()
    if fila is None:
        raise ValueError("Esa oferta ya no existe.")
    return _como_oferta(fila)


def guardar_oferta(usuario_id: int, oferta_id, nombre: str, tipo: str, desde, hasta, franjas, bonos) -> int:
    """
    Crea una oferta (`oferta_id` None) o cambia una que no terminó, y devuelve su
    id. `franjas`: [(día de la semana, turno)...]; `bonos`: [(equipo, bono_id)...].
    Solo el Administrador (PermissionError). ValueError con el mensaje listo para
    mostrar si algo no vale, y ChocaConOtraOferta si toca un bono y un turno que
    ya tiene otra. Una oferta pausada sigue pausada al cambiarla.
    """
    usuarios_repo.exigir_admin(usuario_id, "armar ofertas")
    nombre = (nombre or "").strip()
    if not nombre:
        raise ValueError("Ponele un nombre a la oferta (por ejemplo, «Noche de finde»).")
    if len(nombre) > LARGO_MAXIMO_DEL_NOMBRE:
        raise ValueError(f"El nombre es muy largo: hasta {LARGO_MAXIMO_DEL_NOMBRE} letras.")
    if tipo not in dominio.TIPOS_OFERTA:
        raise ValueError("Elegí si la oferta es 2x1 o 50%.")
    desde, hasta = _como_fecha(desde, "DESDE"), _como_fecha(hasta, "HASTA")
    if hasta < desde:
        raise ValueError("La fecha HASTA es anterior a DESDE.")
    if (hasta - desde).days >= DIAS_MAXIMOS:
        raise ValueError("Una oferta dura como mucho un año: acortá las fechas.")
    franjas = _franjas_validas(franjas)

    ahora = datetime.now()
    if hasta < turnos.dia_en_que_empezo_el_turno(ahora):
        raise ValueError("La fecha HASTA ya pasó.")
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        bonos, nombres = _bonos_validos(conexion, bonos)
        pausada = False
        if oferta_id is not None:
            anterior = _oferta(conexion, oferta_id)
            if estado(anterior, ahora) == dominio.OFERTA_TERMINADA:
                raise ValueError("Esa oferta ya terminó y no se cambia: para volver a ponerla, usala de nuevo.")
            pausada = anterior["pausada"]
        nueva = {"id": oferta_id, "nombre": nombre, "tipo": tipo, "desde": desde, "hasta": hasta,
                 "franjas": franjas, "bonos": bonos, "pausada": False, "terminada_fecha": None}
        if not proximas_veces(nueva, ahora, 1):
            raise ValueError("Entre esas fechas no queda por delante ningún día con los turnos marcados.")
        _revisar_choques(conexion, nueva, nombres, ahora)

        datos = (nombre, tipo, desde.isoformat(), hasta.isoformat(),
                 json.dumps([list(franja) for franja in franjas]), json.dumps([list(bono) for bono in bonos]))
        momento = ahora.isoformat(timespec="seconds")
        if oferta_id is None:
            return conexion.execute(
                """
                INSERT INTO ofertas (nombre, tipo, desde, hasta, franjas, bonos, pausada, creada_fecha, creada_por)
                VALUES (?, ?, ?, ?, ?, ?, 0, ?, ?)
                """,
                (*datos, momento, usuario_id),
            ).lastrowid
        conexion.execute(
            """
            UPDATE ofertas SET nombre = ?, tipo = ?, desde = ?, hasta = ?, franjas = ?, bonos = ?, pausada = ?,
                               modificada_fecha = ?, modificada_por = ?
            WHERE id = ?
            """,
            (*datos, int(pausada), momento, usuario_id, oferta_id),
        )
        return oferta_id


def _cambiar_estado(usuario_id: int, oferta_id: int, para: str, cambio: str, valores: tuple):
    usuarios_repo.exigir_admin(usuario_id, f"{para} una oferta")
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        if estado(_oferta(conexion, oferta_id), ahora) == dominio.OFERTA_TERMINADA:
            raise ValueError("Esa oferta ya terminó.")
        conexion.execute(f"UPDATE ofertas SET {cambio} WHERE id = ?", (*valores, oferta_id))


def pausar_oferta(usuario_id: int, oferta_id: int):
    """La deja de aplicar hasta que se la reanude (solo el Administrador)."""
    momento = datetime.now().isoformat(timespec="seconds")
    _cambiar_estado(usuario_id, oferta_id, "pausar", "pausada = 1, modificada_fecha = ?, modificada_por = ?",
                    (momento, usuario_id))


def reanudar_oferta(usuario_id: int, oferta_id: int):
    """La vuelve a aplicar en sus días y turnos (solo el Administrador). No hace
    falta revisar choques: mientras estuvo pausada nadie pudo poner otra encima."""
    momento = datetime.now().isoformat(timespec="seconds")
    _cambiar_estado(usuario_id, oferta_id, "reanudar", "pausada = 0, modificada_fecha = ?, modificada_por = ?",
                    (momento, usuario_id))


def terminar_oferta(usuario_id: int, oferta_id: int):
    """La termina ya, aunque le queden días (solo el Administrador). No se borra:
    queda en la lista como TERMINADA, con quién y cuándo."""
    momento = datetime.now().isoformat(timespec="seconds")
    _cambiar_estado(usuario_id, oferta_id, "terminar", "terminada_fecha = ?, terminada_por = ?",
                    (momento, usuario_id))
