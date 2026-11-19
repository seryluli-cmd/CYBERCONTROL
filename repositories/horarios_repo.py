"""
horarios_repo.py
=================
HORARIOS DEL PERSONAL (pedido del dueño, 2026-11-19; eligió la maqueta B de
PROPUESTA_HORARIOS: una tarjeta por empleada y abajo su detalle día por día).
Por cada empleada, cuántos días llegó temprano, cuántos llegó tarde, cuántos se
fue antes y el saldo: si le debe tiempo al local o el local a ella. Su ejemplo:
Antonella abre la caja de la Tarde a las 13:55 (5 minutos antes); si la cierra a
las 21:55 (5 antes), cumplió justo su turno y el día queda en cero. Lo muestra
ui/horarios_personal_window.py, solo al Administrador.

El programa no ve la puerta: lo único que sabe de cuándo llega y se va alguien
es su caja (relevo_repo). Por eso:
- Llega cuando abre su caja, o cuando RECIBE la de quien la estaba cubriendo
  (relevos_caja).
- Se va cuando cierra su caja, o cuando la ENTREGA a quien llega (otro relevo).
- Si la caja la cerró el programa (cierre forzoso) o la cerró otra persona (en
  su ausencia, o el Admin), no se sabe a qué hora se fue: esa salida queda "sin
  dato" y no suma ni resta. Lo que llegó temprano o tarde ese día sí cuenta.
- Una JORNADA es un tramo seguido de una misma persona: si cierra su caja y en
  menos de MINUTOS_PARA_SEGUIR abre otra (cubre a la que no llegó, o hace doble
  turno), sigue siendo el mismo día de trabajo. Pasó en la base del local: el de
  la Noche cerró a las 06:15 y abrió la caja de la Mañana a las 06:16 hasta que
  llegó el reemplazo a las 06:32; se fue 06:32, no 06:15.
- Contra qué horario se compara: los turnos de las cajas que tuvo al menos la
  mitad del turno (la "suya"). La que cubre a otra un rato no cumple con eso, así
  que lo que se queda cuenta a su favor; la que llega antes y recibe la caja del
  turno anterior, tampoco. Un doble turno (las dos mitades enteras) se compara
  con la entrada del primero y la salida del segundo, y se avisa: no suma 8 horas.
- Con datos de caja, lo que gana la que llega temprano lo pierde la que se va:
  para que una abra, la otra tuvo que cerrar antes (se le avisó al dueño).

Solo mira: no graba nada, ni toca la plata ni los cierres.
"""

from collections import Counter
from datetime import date, datetime, timedelta

import dominio
from database import conexion_db
from repositories import cajas_repo, usuarios_repo
from turnos import etiqueta_turno, fin_del_turno, inicio_del_turno

# Hasta estos minutos antes o después cuenta como "a horario": llegar a las 14:01
# no es llegar tarde (pedido del dueño, 2026-11-19; se puede cambiar acá).
MINUTOS_DE_MARGEN = 2

# Entre cerrar una caja y abrir la siguiente la misma persona: hasta acá, sigue
# siendo la misma jornada (en la base del local fueron de 1 a 6 minutos).
MINUTOS_PARA_SEGUIR = 30

# Cómo terminó el tramo de alguien con una caja.
_LA_ENTREGO = "entrego"        # se la pasó a quien llegó (relevo)
_LA_CERRO_ELLA = "cerro"       # hizo su Cierre de Turno
_SE_CERRO_SOLA = "forzoso"     # la cerró el programa
_LA_CERRO_OTRA = "otra"        # la cerró otra persona (en su ausencia, o el Admin)
_SIGUE_ABIERTA = "abierta"     # está trabajando ahora


def _momento(texto) -> datetime:
    """La hora de la base, sin los segundos: la pantalla muestra "06:17" y los
    minutos tienen que dar con eso (con los segundos, 06:17:40 contaba 18 tarde)."""
    return datetime.fromisoformat(str(texto)).replace(second=0, microsecond=0)


def _como_fecha(valor) -> date:
    """Acepta un date, un datetime o "YYYY-MM-DD" (como hablan las pantallas)."""
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor
    return date.fromisoformat(str(valor)[:10])


def _minutos(diferencia: timedelta) -> int:
    return round(diferencia.total_seconds() / 60)


def con_margen(minutos: int) -> int:
    """Los minutos de una punta del día, con el margen ya aplicado: dentro de
    MINUTOS_DE_MARGEN (antes o después) es cero, "a horario"."""
    return 0 if abs(minutos) <= MINUTOS_DE_MARGEN else minutos


def _tramos(conexion, desde: date, hasta: date) -> list:
    """Cada rato que una persona tuvo una caja, en orden: desde que la abrió o
    la recibió hasta que la entregó, la cerró o se cerró. Toma un día de más a
    cada lado: una jornada puede empezar en la Noche del día anterior."""
    cajas = conexion.execute(
        """
        SELECT cajas.id, cajas.fecha, cajas.turno, cajas.abierta_por, cajas.abierta_en,
               cajas.cierre_forzoso, cierres_turno.fecha_cierre, cierres_turno.usuario_id AS cerrada_por
        FROM cajas
        LEFT JOIN cierres_turno ON cierres_turno.id = cajas.cierre_id
        WHERE cajas.fecha BETWEEN ? AND ?
        ORDER BY cajas.abierta_en, cajas.id
        """,
        ((desde - timedelta(days=1)).isoformat(), (hasta + timedelta(days=1)).isoformat()),
    ).fetchall()
    tramos = []
    for caja in cajas:
        fecha = _como_fecha(caja["fecha"])
        quien, desde_cuando, recibio_de = caja["abierta_por"], _momento(caja["abierta_en"]), None
        for relevo in cajas_repo._relevos_de(conexion, caja["id"]):
            cuando = _momento(relevo["fecha"])
            tramos.append({
                "usuario_id": quien, "fecha": fecha, "turno": caja["turno"], "desde": desde_cuando,
                "hasta": cuando, "termino": _LA_ENTREGO, "otra": relevo["a_usuario_id"], "recibio_de": recibio_de,
            })
            quien, desde_cuando, recibio_de = relevo["a_usuario_id"], cuando, relevo["de_usuario_id"]
        if caja["fecha_cierre"] is None:
            termino, hasta_cuando = _SIGUE_ABIERTA, None
        elif caja["cierre_forzoso"]:
            termino, hasta_cuando = _SE_CERRO_SOLA, _momento(caja["fecha_cierre"])
        elif caja["cerrada_por"] == quien:
            termino, hasta_cuando = _LA_CERRO_ELLA, _momento(caja["fecha_cierre"])
        else:
            termino, hasta_cuando = _LA_CERRO_OTRA, _momento(caja["fecha_cierre"])
        tramos.append({
            "usuario_id": quien, "fecha": fecha, "turno": caja["turno"], "desde": desde_cuando,
            "hasta": hasta_cuando, "termino": termino, "otra": caja["cerrada_por"], "recibio_de": recibio_de,
        })
    tramos.sort(key=lambda tramo: tramo["desde"])
    return tramos


def _jornadas(tramos: list) -> list:
    """Junta los tramos seguidos de una misma persona (ver MINUTOS_PARA_SEGUIR):
    cada jornada es la lista de sus tramos, en orden."""
    jornadas, ultima_de = [], {}
    for tramo in tramos:
        anterior = ultima_de.get(tramo["usuario_id"])
        sigue = (
            anterior is not None
            and tramo["recibio_de"] is None
            and anterior[-1]["hasta"] is not None
            and timedelta(0) <= tramo["desde"] - anterior[-1]["hasta"] <= timedelta(minutes=MINUTOS_PARA_SEGUIR)
        )
        if sigue:
            anterior.append(tramo)
        else:
            nueva = [tramo]
            jornadas.append(nueva)
            ultima_de[tramo["usuario_id"]] = nueva
    return jornadas


def _turnos_propios(jornada: list, ahora: datetime) -> list:
    """Los turnos (fecha, turno) que la jornada cubrió como suyos, en orden: los de
    las cajas que tuvo al menos la mitad del turno. No cuenta la caja que abrió
    después de la suya y entregó a quien llegó tarde: eso es cubrir, y lo que se
    quedó va a su favor. Si ninguno llega a la mitad, el que tuvo más tiempo (el
primer tramo siempre cuenta, así que nunca queda vacío)."""
    minutos = {}
    for numero, tramo in enumerate(jornada):
        if numero > 0 and tramo["termino"] == _LA_ENTREGO:
            continue
        clave = (tramo["fecha"], tramo["turno"])
        minutos[clave] = minutos.get(clave, 0) + _minutos((tramo["hasta"] or ahora) - tramo["desde"])
    propios = [
        clave for clave, tenidos in minutos.items()
        if tenidos * 2 >= _minutos(fin_del_turno(*clave) - inicio_del_turno(*clave))
    ]
    return sorted(propios or [max(minutos, key=minutos.get)], key=lambda clave: inicio_del_turno(*clave))


def _dia_de_trabajo(jornada: list, nombres: dict, ahora: datetime) -> dict:
    """Un renglón del detalle: a qué hora llegó y se fue, contra qué horario y
    cuántos minutos de más (+) o de menos (−) en cada punta."""
    propios = _turnos_propios(jornada, ahora)
    inicio = inicio_del_turno(*propios[0])
    fin = fin_del_turno(*propios[-1])
    primero, ultimo = jornada[0], jornada[-1]
    llegada = primero["desde"]
    salida = ultimo["hasta"] if ultimo["termino"] in (_LA_ENTREGO, _LA_CERRO_ELLA) else None
    en_curso = ultimo["termino"] == _SIGUE_ABIERTA

    que_paso = []
    if primero["recibio_de"] is not None:
        que_paso.append(f"Recibió la caja de {nombres.get(primero['recibio_de'], '?')}")
    if len(propios) > 1:
        que_paso.append("Turno doble: " + " y ".join(etiqueta_turno(*clave) for clave in propios))
    if ultimo["termino"] == _LA_ENTREGO:
        quien = nombres.get(ultimo["otra"], "?")
        cubrio = len(jornada) > 1 and (ultimo["fecha"], ultimo["turno"]) not in propios
        que_paso.append(f"Cubrió hasta que llegó {quien}" if cubrio else f"Le entregó la caja a {quien}")
    elif ultimo["termino"] == _SE_CERRO_SOLA:
        que_paso.append("La caja la cerró el programa: no se sabe a qué hora se fue")
    elif ultimo["termino"] == _LA_CERRO_OTRA:
        que_paso.append(f"La caja la cerró {nombres.get(ultimo['otra'], '?')}: no se sabe a qué hora se fue")
    elif en_curso:
        que_paso.append("Está trabajando ahora")

    al_llegar = con_margen(_minutos(inicio - llegada))
    al_irse = None if salida is None else con_margen(_minutos(salida - fin))
    return {
        "dia": propios[0][0],
        "turno": propios[0][1],
        "turno_label": " y ".join(etiqueta_turno(*clave) for clave in propios),
        "inicio": inicio,
        "fin": fin,
        "llegada": llegada,
        "salida": salida,
        "en_curso": en_curso,
        "al_llegar": al_llegar,
        "al_irse": al_irse,
        "del_dia": al_llegar + (al_irse or 0),
        "que_paso": " · ".join(que_paso),
    }


def _resumen_de(nombre: str, dias: list) -> dict:
    habitual = Counter(etiqueta_turno(dia["dia"], dia["turno"]) for dia in dias).most_common(1)[0][0]
    return {
        "nombre": nombre,
        "turno_habitual": habitual,
        "dias": len(dias),
        "llego_temprano": sum(1 for dia in dias if dia["al_llegar"] > 0),
        "llego_tarde": sum(1 for dia in dias if dia["al_llegar"] < 0),
        "se_fue_antes": sum(1 for dia in dias if dia["al_irse"] is not None and dia["al_irse"] < 0),
        "sin_dato": sum(1 for dia in dias if dia["salida"] is None and not dia["en_curso"]),
        "saldo": sum(dia["del_dia"] for dia in dias),
        "detalle": dias,
    }


def horarios_del_personal(usuario_id: int, desde, hasta, ahora: datetime = None) -> dict:
    """
    Los horarios de cada empleada entre `desde` y `hasta` (días del local, como
    "YYYY-MM-DD" o date). Solo el Administrador (PermissionError si no).

    Devuelve {"margen": MINUTOS_DE_MARGEN, "empleadas": [...]}, una por cada
    empleada que trabajó en el período, por nombre. Cada una trae "nombre",
    "usuario_id", "turno_habitual", "dias", "llego_temprano", "llego_tarde",
    "se_fue_antes", "sin_dato" y "saldo" (minutos: positivo = el local le debe
    tiempo a ella; negativo = ella le debe al local), y "detalle", un renglón por
    día con "dia", "turno_label", "inicio"/"fin" (su horario), "llegada"/"salida"
    (None = sin dato o todavía trabajando, ver "en_curso"), "al_llegar"/"al_irse"
    (minutos a su favor: + llegó antes o se quedó, − llegó tarde o se fue antes;
    al_irse None si no se sabe), "del_dia" y "que_paso".
    """
    usuarios_repo.exigir_admin(usuario_id, "ver los horarios del personal")
    desde, hasta = _como_fecha(desde), _como_fecha(hasta)
    ahora = ahora or datetime.now()
    with conexion_db() as conexion:
        tramos = _tramos(conexion, desde, hasta)
        usuarios = {
            fila["id"]: fila
            for fila in conexion.execute("SELECT id, nombre, rol FROM usuarios").fetchall()
        }
    nombres = {usuario_id_: fila["nombre"] for usuario_id_, fila in usuarios.items()}

    dias_de = {}
    for jornada in _jornadas(tramos):
        quien = jornada[0]["usuario_id"]
        if usuarios[quien]["rol"] == dominio.ROL_ADMIN:
            continue
        dia = _dia_de_trabajo(jornada, nombres, ahora)
        if desde <= dia["dia"] <= hasta:
            dias_de.setdefault(quien, []).append(dia)

    empleadas = [
        {"usuario_id": quien, **_resumen_de(nombres[quien], dias)}
        for quien, dias in dias_de.items()
    ]
    empleadas.sort(key=lambda empleada: dominio.sin_acentos(empleada["nombre"]))
    return {"margen": MINUTOS_DE_MARGEN, "empleadas": empleadas}
