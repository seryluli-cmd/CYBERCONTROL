"""
turnos_repo.py
===============
Lógica de Caja (consulta en vivo) y Cierre de Turno.

Idea central: en vez de calcular los turnos con horarios rígidos (lo cual
se complica porque el turno "NOCHE" cruza la medianoche, y porque a veces
una empleada llega unos minutos tarde), un turno "en curso" es
simplemente: *todo lo vendido desde el último cierre hasta ahora*.
Así, sin importar la hora exacta a la que alguien cierra, nunca se cuenta
una venta dos veces ni se pierde ninguna.
"""

from datetime import date, datetime, timedelta
from database import conexion_db, calcular_turno, etiqueta_turno, turno_vencimiento
from repositories.config_repo import obtener_fondo_cambio


def _obtener_ultimo_cierre(conexion):
    return conexion.execute(
        "SELECT * FROM cierres_turno ORDER BY id DESC LIMIT 1"
    ).fetchone()


def _sumar_ventas_por_metodo(conexion, desde: str, hasta: str):
    """
    Devuelve (total_efectivo, total_digital) vendidos entre `desde`
    (exclusivo) y `hasta` (inclusive), considerando solo ventas
    CONFIRMADAS (una venta anulada no debe contar en la caja).
    """
    filas = conexion.execute(
        """
        SELECT venta_pagos.metodo, SUM(venta_pagos.monto) AS total
        FROM venta_pagos
        JOIN ventas ON ventas.id = venta_pagos.venta_id
        WHERE ventas.estado = 'CONFIRMADA'
          AND ventas.fecha > ?
          AND ventas.fecha <= ?
        GROUP BY venta_pagos.metodo
        """,
        (desde, hasta),
    ).fetchall()
    totales = {"EFECTIVO": 0.0, "DIGITAL": 0.0}
    for fila in filas:
        totales[fila["metodo"]] = fila["total"] or 0.0
    return totales["EFECTIVO"], totales["DIGITAL"]


def resumen_turno_actual():
    """
    Para la pantalla "Caja": muestra cómo viene el turno en curso sin
    cerrarlo. Devuelve un diccionario con fondo de cambio, ventas en
    efectivo y digital acumuladas desde el último cierre, y cuánto
    debería haber ahora mismo en el cajón.
    """
    with conexion_db() as conexion:
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        desde = ultimo_cierre["fecha_cierre"] if ultimo_cierre else "0000-01-01T00:00:00"
        ahora = datetime.now().isoformat(timespec="seconds")
        ventas_efectivo, ventas_digital = _sumar_ventas_por_metodo(conexion, desde, ahora)

    fondo_cambio = obtener_fondo_cambio()

    ahora_dt = datetime.now()
    turno_actual = calcular_turno(ahora_dt)

    return {
        "turno_actual": turno_actual,
        "turno_actual_label": etiqueta_turno(ahora_dt.date(), turno_actual),
        "fondo_cambio": fondo_cambio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_digital": ventas_digital,
        "caja_actual": fondo_cambio + ventas_efectivo,
        "desde": desde,
        "hasta": ahora,
    }


def cerrar_turno(usuario_id: int):
    """
    Cierra el turno en curso: calcula lo mismo que `resumen_turno_actual`
    y lo deja grabado en `cierres_turno`, listo para que la empleada
    sepa cuánto retirar (dejando el fondo de cambio en el cajón para el
    próximo turno). Devuelve el resumen guardado.
    """
    fondo_cambio = obtener_fondo_cambio()

    with conexion_db() as conexion:
        ultimo_cierre = _obtener_ultimo_cierre(conexion)
        desde = ultimo_cierre["fecha_cierre"] if ultimo_cierre else "0000-01-01T00:00:00"
        ahora_dt = datetime.now()
        ahora = ahora_dt.isoformat(timespec="seconds")

        ventas_efectivo, ventas_digital = _sumar_ventas_por_metodo(conexion, desde, ahora)
        monto_a_retirar = ventas_efectivo

        # El turno que queda etiquetado en el cierre es el que empezó
        # justo después del cierre anterior — es decir, el turno que
        # efectivamente se está cerrando — y no el que esté vigente en
        # este preciso instante. Si no se hiciera así, una empleada que
        # cierra unos minutos tarde (ya entrada la hora del turno
        # siguiente) dejaría el cierre mal etiquetado con el turno
        # equivocado, aunque los montos en sí siempre fueron correctos.
        inicio_del_turno = datetime.fromisoformat(desde) if ultimo_cierre else ahora_dt
        turno = calcular_turno(inicio_del_turno)

        # "fecha" guarda el día en que ARRANCÓ el turno (el mismo criterio
        # que "turno", justo arriba) y no el día en que se lo cerró: para
        # un turno Noche cerrado ya pasada la medianoche, esos dos días son
        # distintos, y turnos_faltantes() necesita que coincida con el día
        # que arma turnos_del_mes_actual() para poder cruzarlos.
        fecha_turno = inicio_del_turno.date()

        cursor = conexion.execute(
            """
            INSERT INTO cierres_turno
                (fecha, turno, usuario_id, fecha_cierre, fondo_cambio,
                 ventas_efectivo, ventas_digital, monto_a_retirar)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                fecha_turno.isoformat(),
                turno,
                usuario_id,
                ahora,
                fondo_cambio,
                ventas_efectivo,
                ventas_digital,
                monto_a_retirar,
            ),
        )
        cierre_id = cursor.lastrowid

    return {
        "id": cierre_id,
        "turno": turno,
        "turno_label": etiqueta_turno(fecha_turno, turno),
        "fondo_cambio": fondo_cambio,
        "ventas_efectivo": ventas_efectivo,
        "ventas_digital": ventas_digital,
        "monto_a_retirar": monto_a_retirar,
    }


def listar_cierres(limite: int = 100):
    """Historial de cierres, para que el Admin controle turno por turno
    (y cargue el monto que contó en cada sobre)."""
    with conexion_db() as conexion:
        return conexion.execute(
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


def verificar_cierre(cierre_id: int, monto_contado: float, usuario_admin_id: int):
    """
    El Admin carga cuánta plata contó realmente en el sobre de un cierre
    puntual. Se calcula la diferencia contra lo esperado (monto_a_retirar)
    para detectar faltantes o sobrantes por empleada/turno.
    """
    with conexion_db() as conexion:
        cierre = conexion.execute(
            "SELECT * FROM cierres_turno WHERE id = ?", (cierre_id,)
        ).fetchone()
        if cierre is None:
            raise ValueError("El cierre no existe.")

        monto_contado = round(monto_contado, 2)
        diferencia = round(monto_contado - cierre["monto_a_retirar"], 2)
        ahora = datetime.now().isoformat(timespec="seconds")
        conexion.execute(
            """
            UPDATE cierres_turno
            SET monto_contado = ?, diferencia = ?, verificado_por = ?, fecha_verificacion = ?
            WHERE id = ?
            """,
            (monto_contado, diferencia, usuario_admin_id, ahora, cierre_id),
        )


def _vendedores_del_mes(conexion, inicio_mes):
    """
    Mapa (día, turno) -> nombres que registraron alguna venta CONFIRMADA
    en esa ventana, para el mes en curso. Sirve para, ante un turno
    faltante, saber quién vendió en ese horario y probablemente sea
    quien se olvidó de cerrarlo (no hay ningún horario asignado por
    empleada en el sistema — esto es una inferencia a partir de quién
    facturó, no una certeza).

    NOCHE cruza la medianoche: una venta de esas horas puede tener
    fecha del día en que arrancó el turno (22-23:59) o del día
    siguiente (00-05:59) — se le atribuye al día en que arrancó, mismo
    criterio que turno_vencimiento().
    """
    filas = conexion.execute(
        """
        SELECT ventas.fecha, ventas.turno, usuarios.nombre
        FROM ventas
        JOIN usuarios ON usuarios.id = ventas.usuario_id
        WHERE ventas.estado = 'CONFIRMADA' AND ventas.fecha >= ?
        """,
        (inicio_mes.isoformat(),),
    ).fetchall()

    vendedores = {}
    for fila in filas:
        momento = datetime.fromisoformat(fila["fecha"])
        turno = fila["turno"]
        dia_slot = momento.date()
        if turno == "NOCHE" and momento.hour < 12:
            dia_slot -= timedelta(days=1)
        vendedores.setdefault((dia_slot, turno), set()).add(fila["nombre"])
    return vendedores


def turnos_del_mes_actual():
    """
    Los turnos esperados del mes en curso, de día 1 a hoy — domingo
    tiene solo 2 (Mañana, Noche); el resto de los días tiene los 3 de
    siempre (ver database.calcular_turno). Todavía no dice cuáles ya
    tienen cierre cargado ni cuáles vencieron — eso lo hace
    turnos_faltantes().
    """
    hoy = datetime.now().date()
    dia = date(hoy.year, hoy.month, 1)
    slots = []
    while dia <= hoy:
        turnos_del_dia = ("MAÑANA", "NOCHE") if dia.weekday() == 6 else ("MAÑANA", "TARDE", "NOCHE")
        for turno in turnos_del_dia:
            slots.append({"fecha": dia, "turno": turno})
        dia += timedelta(days=1)
    return slots


def turnos_faltantes():
    """
    De los turnos esperados del mes en curso (turnos_del_mes_actual), los
    que YA vencieron (ventana nominal + 40 min de gracia, ver
    database.turno_vencimiento) y todavía no tienen un cierre cargado en
    cierres_turno. Se usa en "Control de Cierres de Turno" para que el
    Admin se entere de un turno sin cerrar antes de que se pierda en el
    historial, en vez de notarlo recién a fin de mes. Cada resultado
    incluye "usuarios": quién vendió durante esa ventana (ver
    _vendedores_del_mes), para saber a quién preguntarle.
    """
    ahora = datetime.now()
    hoy = ahora.date()
    inicio_mes = date(hoy.year, hoy.month, 1)

    with conexion_db() as conexion:
        filas_cierres = conexion.execute(
            "SELECT fecha, turno FROM cierres_turno WHERE fecha >= ?",
            (inicio_mes.isoformat(),),
        ).fetchall()
        vendedores = _vendedores_del_mes(conexion, inicio_mes)
    cerrados = {(fila["fecha"], fila["turno"]) for fila in filas_cierres}

    faltantes = []
    for slot in turnos_del_mes_actual():
        if (slot["fecha"].isoformat(), slot["turno"]) in cerrados:
            continue
        if turno_vencimiento(slot["fecha"], slot["turno"]) <= ahora:
            slot = dict(slot)
            slot["usuarios"] = sorted(vendedores.get((slot["fecha"], slot["turno"]), ()))
            faltantes.append(slot)
    return faltantes
