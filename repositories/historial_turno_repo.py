"""
historial_turno_repo.py
========================
HISTORIAL DEL TURNO (pedido del dueño, 2026-11-02: "al lado de CONTROL DE
STOCK, quiero que aparezca todo el historial del operador que agarró el
turno"; eligió la maqueta A, en PROPUESTA_HISTORIAL_DEL_TURNO): todo lo que pasó
en un turno, en orden de hora. Lo muestra ui/historial_turno_window.py.

Hasta el 2026-11-20 eran solo las ventas. Ese día el dueño pidió "absolutamente
todos los movimientos de $ y de habilitación y ventas" (maqueta A de
PROPUESTA_HISTORIAL_DEL_TURNO/2_TODOS_LOS_MOVIMIENTOS): ahora suma las PCs que se
abrieron, los socios, la caja y la Cuenta de la PC
(historial_turno_movimientos_repo). Y "que se guarden todos los historiales de
todos los días de todos los turnos, y poder elegir el día y el turno; al entrar,
el turno actual" (maqueta de PROPUESTA_HISTORIAL_DEL_TURNO/3_ELEGIR_DIA_Y_TURNO):
un turno ya cerrado se arma igual, de la ventana de su cierre. No se guarda nada
nuevo: todo eso ya estaba en la base.

Las ventas son las mismas que suma el Cierre de Turno (turnos_repo._ventana_en_curso:
desde el último cierre hasta ahora; la de un cierre ya hecho, del cierre anterior
a ese), así el TOTAL de acá da lo mismo que el del cierre. Con una caja abierta,
son las de esa caja: la de quien agarró el turno, aunque cobre el Admin (quedan a
nombre de ella, ver cajas_repo._quien_vende). Qué se vendió en cada una sale de
detalle_dia_repo, el mismo detalle de Reportes > Resumen del Día.

El turno actual lo abre cualquier operador habilitado (pedido del dueño,
2026-11-19: "quiero que el historial de turno lo puedan ver los operadores, para
verificar que no cometieron errores"). Los turnos anteriores, solo el Admin
(2026-11-20: "el operador solo puede ver su turno actual, el admin puede navegar
entre todos los días y turnos"). Solo mira: anular sigue siendo del Admin, en
Consulta de Ventas.
"""

from datetime import date, datetime

import dominio
from database import conexion_db
from repositories import cajas_repo, detalle_dia_repo, reportes_repo, turnos_repo, usuarios_repo
from repositories import historial_turno_movimientos_repo as movimientos_repo
from repositories.control_cierres_repo import _PRINCIPIO_DE_LOS_TIEMPOS, _cierre_o_error, _desde_del_cierre
from repositories.historial_turno_movimientos_repo import (  # noqa: F401 (las usa la pantalla)
    GRUPO_CAJA, GRUPO_HABILITACIONES, GRUPO_SALDO, GRUPO_VENTAS, PAGO_A_CUENTA, PAGO_SALDO_DEL_SOCIO, PLATA_CUENTA,
    PLATA_DIFERENCIA, PLATA_ENTRA, PLATA_PERDIDA, PLATA_SALE, SIN_PAGO, TIPOS_QUE_ABREN, TIPO_A_CUENTA, TIPO_CAJA,
    TIPO_CARGA_SOCIO, TIPO_CIERRE, TIPO_CUENTA_COBRADA, TIPO_CUENTA_PERDIDA, TIPO_DEVOLUCION, TIPO_MAS_TIEMPO,
    TIPO_MAS_TIEMPO_PCSTREAM, TIPO_MAS_TIEMPO_PS5, TIPO_ORDENAR_SALDOS, TIPO_PCSTREAM, TIPO_PC_ABIERTA, TIPO_PS5,
    TIPO_RELEVO, TIPO_SALDO_A_LA_PC, TIPO_SALDO_DEVUELTO, TIPO_SALDO_IMPORTADO, TIPO_SALDO_QUITADO,
    TIPO_SOCIO_ENTRO, TIPO_TRASLADO,
)
from turnos import etiqueta_turno

# El rubro de cada venta, como se lee en los filtros de los rubros (la fila que
# aparece al tocar VENTAS).
RUBRO_BONO_PC = "BONO PC"
RUBRO_MIEMBRO = "MIEMBRO"
RUBRO_KIOSKO = "KIOSKO"
RUBRO_IMPRESIONES = "IMPRESIONES"
RUBRO_TRAMITE = "TRÁMITE"
RUBRO_PS5 = "PS5"
RUBRO_PCSTREAM = "PCSTREAM"
RUBRO_RESERVA = "RESERVA"
# Una venta sin nada anotado de qué fue (no debería haber: ver detalle_dia_repo).
RUBRO_OTRO = "OTRO"

_RUBRO_DE_CATEGORIA = {
    reportes_repo.CATEGORIA_KIOSKO: RUBRO_KIOSKO,
    reportes_repo.CATEGORIA_IMPRESIONES: RUBRO_IMPRESIONES,
    reportes_repo.CATEGORIA_BONO_PC: RUBRO_BONO_PC,
    reportes_repo.CATEGORIA_BONO_SOCIO: RUBRO_MIEMBRO,
    reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO: RUBRO_MIEMBRO,
    reportes_repo.CATEGORIA_TRAMITE: RUBRO_TRAMITE,
    reportes_repo.CATEGORIA_BONO_PLAYSTATION: RUBRO_PS5,
    reportes_repo.CATEGORIA_BONO_PCSTREAM: RUBRO_PCSTREAM,
    reportes_repo.CATEGORIA_RESERVA: RUBRO_RESERVA,
}

PAGO_EFECTIVO = "Efectivo"
PAGO_DIGITAL = "Digital"
PAGO_LOS_DOS = "Efectivo y digital"

# Qué fue una venta que dio tiempo: si prendió el equipo, el equipo; si no, "+ TIEMPO".
_ABRIO = {
    movimientos_repo.EQUIPO_PC: TIPO_PC_ABIERTA,
    movimientos_repo.EQUIPO_PCSTREAM: TIPO_PCSTREAM,
    movimientos_repo.EQUIPO_PS5: TIPO_PS5,
}
_SUMO_TIEMPO = {
    movimientos_repo.EQUIPO_PC: TIPO_MAS_TIEMPO,
    movimientos_repo.EQUIPO_PCSTREAM: TIPO_MAS_TIEMPO_PCSTREAM,
    movimientos_repo.EQUIPO_PS5: TIPO_MAS_TIEMPO_PS5,
}
# Si no se sabe de qué bono fue (no debería pasar), lo que dice su rubro.
_TIPO_DEL_RUBRO = {
    RUBRO_BONO_PC: TIPO_MAS_TIEMPO,
    RUBRO_PCSTREAM: TIPO_MAS_TIEMPO_PCSTREAM,
    RUBRO_PS5: TIPO_MAS_TIEMPO_PS5,
    RUBRO_MIEMBRO: TIPO_CARGA_SOCIO,
}

_hora = movimientos_repo.hora


def _rubros(categoria: str, lineas: list) -> tuple:
    """(el rubro de la venta, todos los rubros por los que se la encuentra al
    filtrar). Las impresiones son un artículo del kiosko (el código 4): una
    venta de solo impresiones ya viene como CATEGORIA_IMPRESIONES
    (reportes_repo.categoria_de_la_venta, la misma regla del Detalle del Día y el
    Ranking); una con impresiones y otra cosa es KIOSKO, pero sale también al
    filtrar por impresiones."""
    rubro = _RUBRO_DE_CATEGORIA.get(categoria, RUBRO_OTRO)
    if rubro == RUBRO_KIOSKO and any(linea["codigo"] == dominio.CODIGO_ARTICULO_IMPRESIONES for linea in lineas):
        return RUBRO_KIOSKO, (RUBRO_KIOSKO, RUBRO_IMPRESIONES)
    return rubro, (rubro,)


def _pago(efectivo: float, digital: float) -> str:
    if efectivo > 0 and digital > 0:
        return PAGO_LOS_DOS
    return PAGO_DIGITAL if digital > 0 else PAGO_EFECTIVO


def _anulada_despues_del_cierre(fila, hasta_del_cierre) -> bool:
    """Si la venta se anuló DESPUÉS de cerrado su turno: el cierre es una foto de
    lo cobrado al cerrar, así que ahí sigue sumando (como en el Resumen del Día,
    turnos_ventas_repo._condicion_vigente)."""
    return (hasta_del_cierre is not None and fila["estado"] == dominio.VENTA_ANULADA
            and fila["anulada_fecha"] is not None
            and movimientos_repo.momento(fila["anulada_fecha"]) > movimientos_repo.momento(hasta_del_cierre))


def _nota(fila, despues_del_cierre: bool) -> str:
    """Lo que se aclara después de qué se cobró: quién la anuló, cuándo y por
    qué, y si la cobró el Admin en la caja de la empleada."""
    partes = []
    if fila["estado"] == dominio.VENTA_ANULADA:
        anulada = "anulada después del cierre" if despues_del_cierre else "anulada"
        if fila["anulada_por"]:
            anulada += f" por {fila['anulada_por']}"
        if fila["anulada_fecha"]:
            cuando = datetime.fromisoformat(fila["anulada_fecha"])
            anulada += f" el {cuando:%d/%m} a las {cuando:%H:%M}" if despues_del_cierre else f" a las {cuando:%H:%M}"
        if fila["anulada_motivo"]:
            anulada += f": {fila['anulada_motivo']}"
        partes.append(anulada)
    if fila["cargada_por"]:
        partes.append(f"cobró {fila['cargada_por']}")
    return " · ".join(partes)


def _que_fue(rubro: str, total: float, bono, pc_de_la_cuenta) -> tuple:
    """(tipo, grupos, tiempo) de una venta: la etiqueta de "Qué fue", en qué
    pastillas sale y el tiempo que dio."""
    ventas = movimientos_repo.GRUPO_VENTAS
    if pc_de_la_cuenta is not None:
        return TIPO_CUENTA_COBRADA, (ventas, GRUPO_CAJA), ""
    if rubro == RUBRO_RESERVA:
        # La devolución de una seña es una venta en negativo (reservas_repo.devolver).
        return (TIPO_DEVOLUCION, (ventas, GRUPO_CAJA), "") if total < 0 else (RUBRO_RESERVA, (ventas,), "")
    if bono is not None:
        tiempo = dominio.texto_minutos(bono["minutos"])
        if bono["equipo"] == movimientos_repo.EQUIPO_SALDO:
            return TIPO_CARGA_SOCIO, (ventas, GRUPO_SALDO), f"+ {tiempo} al saldo"
        tipo = (_ABRIO if bono["abrio"] else _SUMO_TIEMPO)[bono["equipo"]]
        return tipo, (ventas, GRUPO_HABILITACIONES), f"+ {tiempo}"
    return _TIPO_DEL_RUBRO.get(rubro, rubro), (ventas,), ""


def _venta(fila, vendido, bonos: dict, cuentas: dict, hasta_del_cierre) -> dict:
    origen = dominio.NOMBRE_ORIGEN_VENTA.get(fila["origen"], fila["origen"])
    categoria, detalle, _renglones, lineas = vendido.get(
        fila["id"], detalle_dia_repo._sin_articulo(origen, "(sin detalle)", "(sin detalle)", fila["total"])
    )
    rubro, rubros = _rubros(categoria, lineas)
    despues = _anulada_despues_del_cierre(fila, hasta_del_cierre)
    anulada = fila["estado"] == dominio.VENTA_ANULADA and not despues
    tipo, grupos, tiempo = _que_fue(rubro, fila["total"], bonos.get(fila["id"]), cuentas.get(fila["id"]))
    nota = _nota(fila, despues)
    if fila["id"] in cuentas:
        nota = " · ".join(parte for parte in (f"de la Cuenta de {cuentas[fila['id']]}", nota) if parte)
    total = round(fila["total"], 2)
    venta = movimientos_repo.movimiento(
        fila["fecha"], tipo, grupos, detalle, nota=nota, pago=_pago(fila["efectivo"], fila["digital"]),
        tiempo=tiempo, plata=abs(total), clase_plata=PLATA_SALE if total < 0 else PLATA_ENTRA, anulada=anulada,
    )
    venta.update({
        "id": fila["id"],
        "venta_id": fila["id"],
        "rubro": rubro,
        "rubros": rubros,
        "efectivo": round(fila["efectivo"], 2),
        "digital": round(fila["digital"], 2),
        "total": total,
        "operador": fila["operador"],
        "cargada_por": fila["cargada_por"],
    })
    return venta


def _movimientos_entre(conexion, desde: str, hasta: str, hasta_del_cierre=None) -> list:
    """Todo lo que pasó en (desde, hasta], en orden de hora: las ventas y lo
    demás (historial_turno_movimientos_repo). `hasta_del_cierre`: la fecha del
    cierre, si es un turno ya cerrado (ver _anulada_despues_del_cierre)."""
    vendido = detalle_dia_repo._que_se_vendio_entre(conexion, desde, hasta)
    bonos = movimientos_repo.bonos_de_las_ventas(conexion, desde, hasta)
    cuentas = movimientos_repo.ventas_de_cuentas(conexion, desde, hasta)
    ventas = [_venta(fila, vendido, bonos, cuentas, hasta_del_cierre)
              for fila in detalle_dia_repo._ventas_entre(conexion, desde, hasta)]
    otros = (movimientos_repo.habilitaciones(conexion, desde, hasta)
             + movimientos_repo.saldos(conexion, desde, hasta)
             + movimientos_repo.caja_y_cuenta(conexion, desde, hasta))
    # sorted es estable: a la misma hora, las ventas primero.
    return sorted(ventas + otros, key=lambda m: movimientos_repo.momento(m["fecha"]))


def _caja_del_cierre(conexion, cierre_id: int):
    return conexion.execute(
        """
        SELECT cajas.*, usuarios.nombre AS responsable
        FROM cajas JOIN usuarios ON usuarios.id = cajas.responsable_id
        WHERE cajas.cierre_id = ?
        """, (cierre_id,),
    ).fetchone()


def _vecinos(conexion, cierre_id) -> tuple:
    """(el cierre del turno anterior, el del siguiente) por número de cierre: los
    turnos van uno detrás del otro, cada uno desde el cierre del anterior. None
    en "siguiente" es el turno que está abierto ahora; en "anterior", que no hay."""
    if cierre_id is None:
        anterior = conexion.execute("SELECT MAX(id) AS id FROM cierres_turno").fetchone()["id"]
        return anterior, None
    anterior = conexion.execute("SELECT MAX(id) AS id FROM cierres_turno WHERE id < ?", (cierre_id,)).fetchone()["id"]
    siguiente = conexion.execute("SELECT MIN(id) AS id FROM cierres_turno WHERE id > ?", (cierre_id,)).fetchone()["id"]
    return anterior, siguiente


def _desde_visible(desde: str):
    """La fecha desde la que cuenta el turno, o None si es el primero de todos
    (el "principio de los tiempos" no se muestra)."""
    return None if desde == _PRINCIPIO_DE_LOS_TIEMPOS else desde


def historial_del_turno(usuario_id: int, cierre_id: int = None) -> dict:
    """
    Todo lo que pasó en un turno, en orden de hora. Sin `cierre_id`, el turno
    abierto (desde el último cierre hasta ahora): lo ve cualquier operador
    habilitado. Con `cierre_id`, el turno que se cerró con ese cierre: solo el
    Administrador (PermissionError si no; ValueError si ese cierre no existe).

    {"cierre_id", "es_el_actual", "puede_mirar_otros" (el Admin: la pantalla le
    pone la barra para elegir día y turno), "dia" (date del local),
    "turno_label", "caja_numero", "responsable", "abrio_a_las" ("18:02"; None
    los tres sin caja), "cerro_a_las" (None en el actual), "se_cerro_sola",
    "desde" (la fecha del cierre anterior, None si es el primero), "anterior" y
    "siguiente" (números de cierre para ◀ ▶; ver _vecinos), "movimientos",
    "ventas" (solo las ventas), "cantidad", "anuladas", "pcs_abiertas",
    "efectivo", "digital", "total"}.

    Cada movimiento: {"fecha", "hora", "tipo" (TIPO_* o el rubro), "grupos"
    (GRUPO_*: en qué pastillas sale), "detalle", "nota", "pago", "tiempo",
    "plata" y "clase_plata" (PLATA_*; None si no movió plata), "anulada",
    "venta_id", "rubro" y "rubros" (solo las ventas)}; las ventas traen además
    "id", "efectivo", "digital", "total", "operador" y "cargada_por". Las
    anuladas vienen en la lista, pero los números no las cuentan. En un turno
    cerrado, una venta anulada DESPUÉS del cierre sigue contando (el cierre es
    una foto de lo cobrado al cerrar) y lo dice en la nota.
    Un usuario dado de baja que quedó con la sesión abierta no lo ve (PermissionError).
    """
    if cierre_id is None:
        usuario = usuarios_repo.usuario_habilitado(usuario_id)
    else:
        usuario = usuarios_repo.exigir_admin(usuario_id, "mirar los turnos anteriores")
    with conexion_db() as conexion:
        if cierre_id is None:
            ventana = turnos_repo._ventana_en_curso(conexion)
            desde, hasta, dia, turno = ventana["desde"], ventana["hasta"], ventana["dia"], ventana["turno"]
            caja, responsable = ventana["caja"], ventana["caja"]["responsable"] if ventana["caja"] else None
            movimientos = _movimientos_entre(conexion, desde, hasta)
        else:
            cierre = _cierre_o_error(conexion, cierre_id)
            desde, hasta = _desde_del_cierre(conexion, cierre_id), cierre["fecha_cierre"]
            dia, turno = date.fromisoformat(cierre["fecha"]), cierre["turno"]
            caja = _caja_del_cierre(conexion, cierre_id)
            # Un cierre sin caja (de antes de las cajas): quien lo cerró.
            responsable = caja["responsable"] if caja is not None else conexion.execute(
                "SELECT nombre FROM usuarios WHERE id = ?", (cierre["usuario_id"],)).fetchone()["nombre"]
            movimientos = _movimientos_entre(conexion, desde, hasta, hasta_del_cierre=hasta)
            movimientos.append(movimientos_repo.cierre(cierre, caja, responsable))
        anterior, siguiente = _vecinos(conexion, cierre_id)
    ventas = [m for m in movimientos if m["venta_id"] is not None]
    validas = [venta for venta in ventas if not venta["anulada"]]
    return {
        "cierre_id": cierre_id,
        "es_el_actual": cierre_id is None,
        "puede_mirar_otros": dominio.es_admin(usuario),
        "dia": dia,
        "turno_label": etiqueta_turno(dia, turno),
        "caja_numero": caja["id"] if caja is not None else None,
        "responsable": responsable,
        "abrio_a_las": _hora(caja["abierta_en"]) if caja is not None else None,
        "cerro_a_las": None if cierre_id is None else _hora(hasta),
        "se_cerro_sola": bool(caja is not None and cierre_id is not None and caja["cierre_forzoso"]),
        "desde": _desde_visible(desde),
        "anterior": anterior,
        "siguiente": siguiente,
        "movimientos": movimientos,
        "ventas": ventas,
        "cantidad": len(validas),
        "anuladas": sum(1 for m in movimientos if m["anulada"]),
        "pcs_abiertas": sum(1 for m in movimientos if m["tipo"] in TIPOS_QUE_ABREN and not m["anulada"]),
        **{campo: round(sum(venta[campo] for venta in validas), 2) for campo in ("efectivo", "digital", "total")},
    }


def turnos_del_dia(usuario_id: int, dia) -> dict:
    """
    Los turnos de `dia` (un día del local, date o "YYYY-MM-DD") para elegir en la
    barra del Historial del Turno: solo el Administrador (PermissionError si no).

    {"turnos": [...], "primer_dia" (el día del primer Cierre de Turno de la base:
    antes no hay nada que mirar; None si todavía no hubo ninguno)}. Cada turno es
    {"cierre_id" (None: el que está abierto ahora), "turno_label", "desde" y
    "hasta" ("22:01"; "desde" None si es el primero de todos, "hasta" None si
    sigue abierto), "responsable" (quién tenía la caja; None si nadie)}. Son los
    mismos turnos del Resumen del Día (turnos_repo._ventanas_del_dia).
    """
    usuarios_repo.exigir_admin(usuario_id, "mirar los turnos anteriores")
    dia = dia if isinstance(dia, date) else date.fromisoformat(dia)
    with conexion_db() as conexion:
        ventanas = turnos_repo._ventanas_del_dia(conexion, dia, datetime.now())
        caja_abierta = cajas_repo._caja_abierta(conexion)
        primero = conexion.execute("SELECT MIN(fecha) AS dia FROM cierres_turno").fetchone()["dia"]
    turnos = []
    for ventana in ventanas:
        cierre = ventana["cierre"]
        if cierre is not None:
            responsable = cierre["empleada"]
        else:
            responsable = caja_abierta["responsable"] if caja_abierta is not None else None
        desde = _desde_visible(ventana["desde"])
        turnos.append({
            "cierre_id": cierre["id"] if cierre is not None else None,
            "turno_label": etiqueta_turno(dia, ventana["turno"]),
            "desde": _hora(desde) if desde else None,
            "hasta": _hora(ventana["hasta"]) if cierre is not None else None,
            "responsable": responsable,
        })
    return {"turnos": turnos, "primer_dia": date.fromisoformat(primero) if primero else None}
