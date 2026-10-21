"""
control_cierres_repo.py
========================
Lo que el dueño mira DESPUÉS de un cierre (pantalla Control de Cierres de
Turno): el historial de cierres con su caja, el detalle venta por venta de cada
uno y la carga de lo que contó en el sobre.

Se separó de turnos_repo.py el 2026-10-18, cuando las cajas con número le
sumaron datos a cada cierre y ese archivo pasaba las 600 líneas (CLAUDE.md,
regla 12). turnos_repo reexporta las funciones públicas con el mismo nombre,
así las pantallas y las pruebas no cambian.

La ventana de un cierre es (cierre anterior, este cierre]: las ventas con
`fecha > desde AND fecha <= fecha_cierre`, comparadas como texto ISO con
microsegundos (ver turnos_repo).
"""

from datetime import datetime

from database import conexion_db
from repositories import cajas_repo, usuarios_repo
from repositories.turnos_ventas_repo import _aparte_por_metodo, _resumen_de_reservas, _separar_de_kiosko
from turnos import etiqueta_turno, fin_del_turno


# Desde cuándo cuenta la ventana del primer turno de la historia (todavía no
# hay un cierre anterior).
_PRINCIPIO_DE_LOS_TIEMPOS = "0000-01-01T00:00:00"


def _desde_del_cierre(conexion, cierre_id: int) -> str:
    """
    Desde cuándo cuenta lo vendido en el cierre `cierre_id`: la
    `fecha_cierre` del cierre anterior (por id), o el principio de los
    tiempos si es el primero que existe. Mismo criterio de ventana que
    usa cerrar_turno() para el turno en curso.
    """
    anterior = conexion.execute(
        "SELECT fecha_cierre FROM cierres_turno WHERE id < ? ORDER BY id DESC LIMIT 1",
        (cierre_id,),
    ).fetchone()
    return anterior["fecha_cierre"] if anterior else _PRINCIPIO_DE_LOS_TIEMPOS


def _cierre_o_error(conexion, cierre_id: int):
    """La fila del cierre `cierre_id`; ValueError si ese cierre no existe."""
    cierre = conexion.execute(
        "SELECT * FROM cierres_turno WHERE id = ?", (cierre_id,)
    ).fetchone()
    if cierre is None:
        raise ValueError("El cierre no existe.")
    return cierre


def _minutos_despues_del_fin(cierre) -> int:
    """Cuántos minutos después del fin de su turno se hizo un cierre (negativo
    si se cerró antes). Es lo que muestra si se cerró a horario."""
    diferencia = datetime.fromisoformat(cierre["fecha_cierre"]) - fin_del_turno(cierre["fecha"], cierre["turno"])
    return int(diferencia.total_seconds() // 60)


def _datos_de_la_caja(conexion, cierre) -> dict:
    """
    Lo que se sabe de la caja de un cierre, listo para mostrar:
    - "caja_numero": el número de caja, o None si es un cierre sin caja (de
      antes de las cajas, o de ventas que quedaron sin caja).
    - "responsable": quién tenía la caja al cerrarla (sin caja, quien cerró).
    - "responsables": todos los que la tuvieron, en orden (quien la abrió y
      quienes la recibieron en un relevo).
    - "cerrada_en_ausencia": la cerró otra persona (la que llegó, o el Admin)
      porque la responsable se fue sin cerrar.
    - "cierre_forzoso": la cerró el programa solo.
    - "abierta_en", "cambio_esperado", "cambio_contado" y "relevos": la
      apertura y los relevos de la caja (vacío si no hay caja).
    - "cambio_inicial": con cuánto cambio arrancó (cajas_repo.cambio_inicial);
      sin caja, el Cambio Fijo que tenía el cierre. Es el "Cambio Fijo" que
      muestra la pantalla Cierre de Turno.
    - "minutos_despues_del_fin": ver _minutos_despues_del_fin.
    """
    caja = cajas_repo._caja_del_cierre(conexion, cierre["id"])
    datos = {"minutos_despues_del_fin": _minutos_despues_del_fin(cierre)}
    if caja is None:
        quien_cerro = conexion.execute(
            "SELECT nombre FROM usuarios WHERE id = ?", (cierre["usuario_id"],)
        ).fetchone()["nombre"]
        datos.update({
            "caja_numero": None, "responsable": quien_cerro, "responsables": [quien_cerro],
            "cerrada_en_ausencia": False, "cierre_forzoso": False,
            "abierta_en": None, "cambio_esperado": None, "cambio_contado": None, "relevos": [],
            "cambio_inicial": cierre["fondo_cambio"],
        })
        return datos

    relevos = [dict(relevo) for relevo in cajas_repo._relevos_de(conexion, caja["id"])]
    responsables = [caja["abierta_por_nombre"]]
    for relevo in relevos:
        if relevo["a_nombre"] != responsables[-1]:
            responsables.append(relevo["a_nombre"])
    datos.update({
        "caja_numero": caja["id"],
        "responsable": caja["responsable"],
        "responsables": responsables,
        "cerrada_en_ausencia": cierre["usuario_id"] != caja["responsable_id"],
        "cierre_forzoso": bool(caja["cierre_forzoso"]),
        "abierta_en": caja["abierta_en"],
        "cambio_esperado": caja["cambio_esperado"],
        "cambio_contado": caja["cambio_contado"],
        "relevos": relevos,
        "cambio_inicial": cajas_repo.cambio_inicial(caja),
    })
    return datos


def _resumen_del_cierre(conexion, cierre, desde: str, caja: dict) -> dict:
    """
    Un cierre ya hecho con las mismas claves que turnos_repo.resumen_turno_actual:
    lo que mostraba la pantalla Cierre de Turno al cerrarlo, para verlo igual
    desde Control de Cierres, sea un cierre común, forzoso o en ausencia (pedido
    del dueño, 2026-10-20: el forzoso lo hace el programa solo y nadie veía ese
    resumen). `caja` es lo de _datos_de_la_caja.

    Casi todo sale tal cual de lo guardado en el cierre (efectivo, digital y cada
    negocio): son los mismos números con que se cerró. Lo único que se recalcula
    es cuánto de Kiosko fue impresiones y trámites, y cuánto de Alquiler de PCs y
    PlayStation 5 fueron reservas (no se guarda aparte), con las ventas de su
    ventana contadas como estaban al cerrar (ver
    turnos_ventas_repo._condicion_vigente).
    """
    guardado = dict(cierre)
    por_metodo = _aparte_por_metodo(conexion, desde, cierre["fecha_cierre"], cierre_grabado=True)
    return {
        **guardado,
        **_separar_de_kiosko(guardado, por_metodo),
        **_resumen_de_reservas(conexion, guardado, desde, cierre["fecha_cierre"], cierre_grabado=True),
        "turno_actual": cierre["turno"],
        "turno_actual_label": etiqueta_turno(cierre["fecha"], cierre["turno"]),
        "ventas_total": round(cierre["ventas_efectivo"] + cierre["ventas_digital"], 2),
        "cambio_inicial": caja["cambio_inicial"],
        "caja_numero": caja["caja_numero"],
        "responsable": caja["responsable"],
        "desde": desde,
        "hasta": cierre["fecha_cierre"],
    }


def listar_cierres(limite: int = 100) -> list:
    """Historial de cierres, del más nuevo al más viejo, para que el Admin
    controle turno por turno (y cargue el monto que contó en cada sobre). Cada
    cierre trae sus columnas, "empleada" (quien lo cerró), "verificado_por_nombre"
    y los datos de su caja (ver _datos_de_la_caja)."""
    with conexion_db() as conexion:
        cierres = conexion.execute(
            """
            SELECT cierres_turno.*, usuarios.nombre AS empleada,
                   verificadores.nombre AS verificado_por_nombre
            FROM cierres_turno
            JOIN usuarios ON usuarios.id = cierres_turno.usuario_id
            LEFT JOIN usuarios AS verificadores ON verificadores.id = cierres_turno.verificado_por
            ORDER BY cierres_turno.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
        return [{**dict(cierre), **_datos_de_la_caja(conexion, cierre)} for cierre in cierres]


def detalle_cierre(cierre_id: int):
    """
    Las ventas que componen un cierre puntual -- las que cayeron entre el
    cierre anterior y este (mismo criterio de rango que cerrar_turno() /
    resumen_turno_actual(): "desde" es el fecha_cierre del cierre previo
    por id, o el principio de los tiempos si es el primer cierre que
    existe). Es lo que le permite al Admin, desde "Control de Cierres de
    Turno", ver venta por venta cómo se llegó al total de un sobre en vez
    de confiar solo en el número agregado.

    Incluye ventas ANULADAS que hayan caído en la ventana (no se
    filtran): no suman al total ya grabado en el cierre (ese total se
    calculó en su momento solo con CONFIRMADAS, ver
    _sumar_ventas_por_origen_y_metodo), pero conviene poder verlas acá
    para entender un cierre que no cuadra. La pantalla las remarca aparte
    (mismo criterio que Consulta de Ventas), nunca se ocultan.

    Cada venta trae "cargada_por_nombre" si la cobró otra persona (el Admin)
    a nombre de la responsable. Además devuelve "caja" (ver _datos_de_la_caja),
    "verificaciones" (todos los conteos del sobre, del primero al último) y
    "resumen": el cierre como lo mostraba la pantalla Cierre de Turno (ver
    _resumen_del_cierre).
    """
    with conexion_db() as conexion:
        cierre = _cierre_o_error(conexion, cierre_id)
        desde = _desde_del_cierre(conexion, cierre_id)

        ventas = conexion.execute(
            """
            SELECT ventas.*, usuarios.nombre AS vendedor,
                   cargadores.nombre AS cargada_por_nombre,
                   GROUP_CONCAT(DISTINCT venta_pagos.metodo) AS metodos
            FROM ventas
            JOIN usuarios ON usuarios.id = ventas.usuario_id
            LEFT JOIN ventas_caja ON ventas_caja.venta_id = ventas.id
            LEFT JOIN usuarios AS cargadores ON cargadores.id = ventas_caja.cargada_por
            LEFT JOIN venta_pagos ON venta_pagos.venta_id = ventas.id
            WHERE ventas.fecha > ? AND ventas.fecha <= ?
            GROUP BY ventas.id
            ORDER BY ventas.fecha
            """,
            (desde, cierre["fecha_cierre"]),
        ).fetchall()

        caja = _datos_de_la_caja(conexion, cierre)
        verificaciones = conexion.execute(
            """
            SELECT verificaciones_cierre.*, usuarios.nombre AS verificado_por_nombre
            FROM verificaciones_cierre
            JOIN usuarios ON usuarios.id = verificaciones_cierre.verificado_por
            WHERE verificaciones_cierre.cierre_id = ?
            ORDER BY verificaciones_cierre.id
            """,
            (cierre_id,),
        ).fetchall()
        resumen = _resumen_del_cierre(conexion, cierre, desde, caja)

    return {
        "cierre": cierre, "desde": desde, "ventas": ventas, "caja": caja, "verificaciones": verificaciones,
        "resumen": resumen,
    }


def verificar_cierre(cierre_id: int, monto_contado: float, usuario_admin_id: int):
    """
    El dueño carga cuánta plata contó realmente en el sobre de un cierre
    puntual. Se calcula la diferencia contra lo esperado (monto_a_retirar)
    para detectar faltantes o sobrantes por empleada/turno.

    Solo un Administrador (pedido del dueño, 2026-10-18: las empleadas guardan
    el sobre en la caja fuerte y lo cuenta él): PermissionError si no. Cada
    conteo queda guardado en verificaciones_cierre; el cierre muestra el último.
    """
    usuarios_repo.exigir_admin(usuario_admin_id, "cargar lo contado en el sobre")
    with conexion_db() as conexion:
        cierre = _cierre_o_error(conexion, cierre_id)

        monto_contado = round(monto_contado, 2)
        diferencia = round(monto_contado - cierre["monto_a_retirar"], 2)
        ahora = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """
            INSERT INTO verificaciones_cierre (cierre_id, monto_contado, diferencia, verificado_por, fecha)
            VALUES (?, ?, ?, ?, ?)
            """,
            (cierre_id, monto_contado, diferencia, usuario_admin_id, ahora),
        )
        conexion.execute(
            """
            UPDATE cierres_turno
            SET monto_contado = ?, diferencia = ?, verificado_por = ?, fecha_verificacion = ?
            WHERE id = ?
            """,
            (monto_contado, diferencia, usuario_admin_id, ahora, cierre_id),
        )
