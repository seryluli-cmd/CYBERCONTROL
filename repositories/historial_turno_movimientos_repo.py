"""
historial_turno_movimientos_repo.py
====================================
Lo que pasó en un turno además de cobrar, para HISTORIAL DEL TURNO (pedido del
dueño, 2026-11-20: "debería mostrar absolutamente todos los movimientos de $ y
de habilitación y ventas"; eligió la maqueta A de
PROPUESTA_HISTORIAL_DEL_TURNO/2_TODOS_LOS_MOVIMIENTOS): las PCs, la PS5 y
PCSTREAM que se abrieron, los socios que entraron con su saldo, los pases de una
PC a otra, lo que vuelve al saldo de un socio, ORDENAR SALDOS, la apertura y los
relevos de la caja y lo anotado a la Cuenta de la PC. Cada cosa es un
"movimiento" (ver `movimiento`) de la ventana (desde, hasta] de un turno, la
misma que la de sus ventas. Lo junta con las ventas
historial_turno_repo.historial_del_turno; se separó de ahí para que ninguno de
los dos pase las 600 líneas (regla 12).

Solo lee, y nada de esto cambia la plata del turno: el TOTAL sigue siendo el de
las ventas, igual que el Cierre de Turno. Lo anotado a la Cuenta de la PC entra a
la caja recién cuando se cobra (una venta más).
"""

from datetime import datetime

import dominio

# Qué fue cada movimiento: el texto de la etiqueta de color de la columna "Qué
# fue". Las ventas que no abren ni suman tiempo van con su rubro
# (historial_turno_repo.RUBRO_*).
TIPO_PC_ABIERTA = "PC ABIERTA"
TIPO_PS5 = "PS5"
TIPO_PCSTREAM = "PCSTREAM"
TIPO_MAS_TIEMPO = "+ TIEMPO"
TIPO_MAS_TIEMPO_PS5 = "+ TIEMPO PS5"
TIPO_MAS_TIEMPO_PCSTREAM = "+ TIEMPO PCSTREAM"
TIPO_SOCIO_ENTRO = "SOCIO ENTRÓ"
TIPO_SALDO_A_LA_PC = "SALDO A LA PC"
TIPO_TRASLADO = "TRASLADO"
TIPO_CARGA_SOCIO = "CARGA SOCIO"
TIPO_SALDO_DEVUELTO = "SALDO DEVUELTO"
TIPO_SALDO_QUITADO = "SALDO QUITADO"
TIPO_SALDO_IMPORTADO = "SALDO IMPORTADO"
TIPO_ORDENAR_SALDOS = "ORDENAR SALDOS"
TIPO_CAJA = "CAJA"
TIPO_RELEVO = "RELEVO"
TIPO_A_CUENTA = "A CUENTA"
TIPO_CUENTA_COBRADA = "CUENTA COBRADA"
TIPO_CUENTA_PERDIDA = "CUENTA PERDIDA"
TIPO_DEVOLUCION = "DEVOLUCIÓN"
TIPO_CIERRE = "CIERRE"
# Los que cuentan en "PCs abiertas" de la cabecera: un equipo que se prendió.
TIPOS_QUE_ABREN = (TIPO_PC_ABIERTA, TIPO_PS5, TIPO_PCSTREAM, TIPO_SOCIO_ENTRO)

# Las pastillas de arriba de la lista. Un movimiento puede estar en más de una:
# un bono que abre una PC es venta Y habilitación.
GRUPO_VENTAS = "ventas"
GRUPO_HABILITACIONES = "habilitaciones"
GRUPO_SALDO = "saldo"
GRUPO_CAJA = "caja"

# Qué es la plata de la columna "Plata": entró a la caja, salió (la devolución
# de una seña), quedó anotada a la Cuenta de la PC (todavía no entró), la
# diferencia al contar el cajón (negativa: faltó) o una Cuenta dada por perdida.
PLATA_ENTRA = "entra"
PLATA_SALE = "sale"
PLATA_CUENTA = "cuenta"
PLATA_DIFERENCIA = "diferencia"
PLATA_PERDIDA = "perdida"

# El "Pago" de lo que no se cobró.
SIN_PAGO = "—"
PAGO_SALDO_DEL_SOCIO = "Saldo del socio"
PAGO_A_CUENTA = "A cuenta"

# De dónde salió el tiempo de una venta (bonos_de_las_ventas).
EQUIPO_PC = "PC"
EQUIPO_PCSTREAM = "PCSTREAM"
EQUIPO_PS5 = "PS5"
EQUIPO_SALDO = "SALDO"


def hora(fecha: str) -> str:
    return datetime.fromisoformat(fecha).strftime("%H:%M")


def momento(fecha: str) -> datetime:
    """La fecha como datetime, para ordenar: unas se graban con segundos y otras
    con microsegundos, y como texto "14:10:05" va antes que "14:10:04.5"."""
    return datetime.fromisoformat(fecha)


def movimiento(fecha: str, tipo: str, grupos: tuple, detalle: str, nota: str = "", pago: str = SIN_PAGO,
               tiempo: str = "", plata=None, clase_plata: str = None, anulada: bool = False) -> dict:
    """Un renglón del historial. Las ventas suman "venta_id", "rubro", "rubros" y la
    plata cobrada (historial_turno_repo._venta); el resto los trae vacíos."""
    return {
        "fecha": fecha, "hora": hora(fecha), "tipo": tipo, "grupos": tuple(grupos), "detalle": detalle,
        "nota": nota, "pago": pago, "tiempo": tiempo,
        "plata": round(plata, 2) if plata is not None else None, "clase_plata": clase_plata,
        "anulada": anulada, "venta_id": None, "rubro": None, "rubros": (),
    }


def _socio(fila) -> str:
    """El nombre del socio, o su usuario si no tiene nombre cargado."""
    return fila["socio"] or fila["socio_usuario"]


_SOCIO_SQL = "NULLIF(miembros.nombre, '') AS socio, miembros.usuario AS socio_usuario"


def _pc_en(cuando_sql: str) -> str:
    """SQL con el nombre de la PC donde estaba la sesión (`sesiones_pc`, ya en la
    consulta) en el momento `cuando_sql`. `sesiones_pc.estacion_id` es la PC de
    AHORA: si después la pasaron a otra (TRASLADO), lo anotado antes del pase fue
    en la PC de origen del primer pase posterior. Texto fijo del programa, nunca
    un dato de la usuaria."""
    return f"""COALESCE((
        SELECT origen.nombre FROM traslados_sesion AS pase
        JOIN estaciones AS origen ON origen.id = pase.estacion_origen_id
        WHERE pase.sesion_id = sesiones_pc.id AND julianday(pase.fecha) > julianday({cuando_sql})
        ORDER BY julianday(pase.fecha), pase.id LIMIT 1
    ), estaciones.nombre)"""


# ------------------------------------------------------------- lo que dicen las ventas
def bonos_de_las_ventas(conexion, desde: str, hasta: str) -> dict:
    """
    {venta_id: {"equipo", "minutos", "abrio"}} de las ventas de (desde, hasta] que
    dieron tiempo: un bono de PC, de PCSTREAM o de la PS5 ("abrio": fue el que
    prendió el equipo, el primero de su sesión, vendido en el mostrador) o una
    carga de saldo de un socio (EQUIPO_SALDO).

    Una sesión que abrió un socio con su saldo o una reserva NO la abrió una venta
    de este turno: esa la cuenta `habilitaciones`. Las ventas de una reserva y las
    de una Cuenta de la PC tienen su propio nombre (historial_turno_repo._que_fue).
    """
    rango = (desde, hasta)
    resultado = {}
    for tabla, equipo in (("sesion_bonos", EQUIPO_PC), ("sesion_pcstream_bonos", EQUIPO_PCSTREAM)):
        # El nombre de la tabla sale de esta tupla fija, nunca de un dato.
        for fila in conexion.execute(
            f"""
            SELECT bonos.venta_id, bonos.minutos,
                   bonos.id = (SELECT MIN(otro.id) FROM {tabla} AS otro WHERE otro.sesion_id = bonos.sesion_id)
                   AND sesiones_pc.miembro_id IS NULL
                   AND NOT EXISTS (SELECT 1 FROM reservas WHERE reservas.sesion_pc_id = bonos.sesion_id) AS abrio
            FROM {tabla} AS bonos
            JOIN ventas ON ventas.id = bonos.venta_id
            JOIN sesiones_pc ON sesiones_pc.id = bonos.sesion_id
            WHERE ventas.fecha > ? AND ventas.fecha <= ?
            """, rango,
        ):
            resultado[fila["venta_id"]] = {"equipo": equipo, "minutos": fila["minutos"], "abrio": bool(fila["abrio"])}
    for fila in conexion.execute(
        """
        SELECT bonos.venta_id, bonos.minutos,
               bonos.id = (SELECT MIN(otro.id) FROM sesion_playstation_bonos AS otro
                           WHERE otro.sesion_id = bonos.sesion_id)
               AND NOT EXISTS (SELECT 1 FROM reservas WHERE reservas.sesion_playstation_id = bonos.sesion_id) AS abrio
        FROM sesion_playstation_bonos AS bonos
        JOIN ventas ON ventas.id = bonos.venta_id
        WHERE ventas.fecha > ? AND ventas.fecha <= ?
        """, rango,
    ):
        resultado[fila["venta_id"]] = {"equipo": EQUIPO_PS5, "minutos": fila["minutos"], "abrio": bool(fila["abrio"])}
    for fila in conexion.execute(
        """
        SELECT movimientos_saldo_miembro.venta_id, SUM(movimientos_saldo_miembro.minutos) AS minutos
        FROM movimientos_saldo_miembro
        JOIN ventas ON ventas.id = movimientos_saldo_miembro.venta_id
        WHERE movimientos_saldo_miembro.tipo = ? AND ventas.fecha > ? AND ventas.fecha <= ?
        GROUP BY movimientos_saldo_miembro.venta_id
        """, (dominio.MOVIMIENTO_CARGA, *rango),
    ):
        resultado.setdefault(fila["venta_id"], {"equipo": EQUIPO_SALDO, "minutos": fila["minutos"], "abrio": False})
    return resultado


def ventas_de_cuentas(conexion, desde: str, hasta: str) -> dict:
    """{venta_id: la PC} de las ventas de (desde, hasta] con que se cobró una Cuenta
    de la PC (al cobrarla se graba una venta por lo de kiosko y otra por el tiempo)."""
    return {
        fila["venta_id"]: fila["pc"]
        for fila in conexion.execute(
            f"""
            SELECT DISTINCT cuenta_pc_items.venta_id, {_pc_en("ventas.fecha")} AS pc
            FROM cuenta_pc_items
            JOIN ventas ON ventas.id = cuenta_pc_items.venta_id
            JOIN cuentas_pc ON cuentas_pc.id = cuenta_pc_items.cuenta_id
            JOIN sesiones_pc ON sesiones_pc.id = cuentas_pc.sesion_id
            JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
            WHERE ventas.fecha > ? AND ventas.fecha <= ?
            """, (desde, hasta),
        )
    }


# ------------------------------------------------------------- habilitaciones
def _con_reserva(fila) -> str:
    return f" con la reserva Nº {fila['reserva']} de {fila['cliente']} ({fila['bono_nombre']})"


def habilitaciones(conexion, desde: str, hasta: str) -> list:
    """
    Lo que prendió un equipo o le pasó tiempo en (desde, hasta] SIN una venta que
    lo diga (esas ya están en la lista, ver bonos_de_las_ventas): la PC o la PS5
    que se abrió con una reserva ya pagada, el socio que entró con su saldo (o le
    pasó más saldo a su PC) y el pase de una PC a otra.

    Una sesión que abrió la venta de un bono no se repite acá, aunque esa venta
    sea de otro turno: `fecha_inicio` se graba sin los microsegundos, así que una
    PC abierta en el mismo segundo de un cierre puede caer del otro lado de la
    raya que su venta (que sí los tiene).
    """
    rango = (desde, hasta)
    movimientos = []
    for fila in conexion.execute(
        """
        SELECT sesiones_pc.fecha_inicio, sesiones_pc.miembro_id, estaciones.nombre AS pc,
               COALESCE(
                   (SELECT venta_id FROM sesion_bonos WHERE sesion_id = sesiones_pc.id ORDER BY id LIMIT 1),
                   (SELECT venta_id FROM sesion_pcstream_bonos WHERE sesion_id = sesiones_pc.id ORDER BY id LIMIT 1)
               ) AS venta_del_primer_bono,
               reservas.id AS reserva, reservas.cliente, reservas.bono_nombre
        FROM sesiones_pc
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        LEFT JOIN reservas ON reservas.sesion_pc_id = sesiones_pc.id
        WHERE sesiones_pc.fecha_inicio > ? AND sesiones_pc.fecha_inicio <= ?
        """, rango,
    ):
        # La de un socio la cuenta su CONSUMO, más abajo.
        if fila["miembro_id"] is not None:
            continue
        if fila["reserva"] is None and fila["venta_del_primer_bono"] is not None:
            continue
        tipo = TIPO_PCSTREAM if fila["pc"] == dominio.NOMBRE_PCSTREAM else TIPO_PC_ABIERTA
        detalle = f"{fila['pc']} se abrió" + (_con_reserva(fila) if fila["reserva"] is not None else "")
        nota = "pagada al reservar" if fila["reserva"] is not None else ""
        movimientos.append(movimiento(fila["fecha_inicio"], tipo, (GRUPO_HABILITACIONES,), detalle, nota))

    for fila in conexion.execute(
        """
        SELECT sesiones_playstation.fecha_inicio,
               (SELECT venta_id FROM sesion_playstation_bonos WHERE sesion_id = sesiones_playstation.id
                ORDER BY id LIMIT 1) AS venta_del_primer_bono,
               reservas.id AS reserva, reservas.cliente, reservas.bono_nombre
        FROM sesiones_playstation
        LEFT JOIN reservas ON reservas.sesion_playstation_id = sesiones_playstation.id
        WHERE sesiones_playstation.fecha_inicio > ? AND sesiones_playstation.fecha_inicio <= ?
        """, rango,
    ):
        if fila["reserva"] is None and fila["venta_del_primer_bono"] is not None:
            continue
        detalle = f"{dominio.NOMBRE_PLAYSTATION} se prendió" + (
            _con_reserva(fila) if fila["reserva"] is not None else "")
        nota = "pagada al reservar" if fila["reserva"] is not None else ""
        movimientos.append(movimiento(fila["fecha_inicio"], TIPO_PS5, (GRUPO_HABILITACIONES,), detalle, nota))

    # El primer CONSUMO de la sesión de un socio es él entrando; los que siguen,
    # saldo que le pasó a la PC donde ya estaba (una carga con la sesión abierta).
    for fila in conexion.execute(
        f"""
        SELECT movimientos_saldo_miembro.fecha, movimientos_saldo_miembro.minutos, {_SOCIO_SQL},
               {_pc_en("movimientos_saldo_miembro.fecha")} AS pc,
               movimientos_saldo_miembro.id = (
                   SELECT MIN(otro.id) FROM movimientos_saldo_miembro AS otro
                   WHERE otro.sesion_id = movimientos_saldo_miembro.sesion_id AND otro.tipo = ?
               ) AND sesiones_pc.miembro_id = movimientos_saldo_miembro.miembro_id AS entro
        FROM movimientos_saldo_miembro
        JOIN miembros ON miembros.id = movimientos_saldo_miembro.miembro_id
        LEFT JOIN sesiones_pc ON sesiones_pc.id = movimientos_saldo_miembro.sesion_id
        LEFT JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        WHERE movimientos_saldo_miembro.tipo = ?
          AND movimientos_saldo_miembro.fecha > ? AND movimientos_saldo_miembro.fecha <= ?
        """, (dominio.MOVIMIENTO_CONSUMO, dominio.MOVIMIENTO_CONSUMO, *rango),
    ):
        tiempo = dominio.texto_minutos(fila["minutos"])
        pc = fila["pc"] or "su PC"
        if fila["entro"]:
            movimientos.append(movimiento(
                fila["fecha"], TIPO_SOCIO_ENTRO, (GRUPO_HABILITACIONES, GRUPO_SALDO),
                f"{_socio(fila)} entró en {pc} con su saldo", pago=PAGO_SALDO_DEL_SOCIO, tiempo=f"usa {tiempo}"))
        else:
            movimientos.append(movimiento(
                fila["fecha"], TIPO_SALDO_A_LA_PC, (GRUPO_HABILITACIONES, GRUPO_SALDO),
                f"{_socio(fila)}: {tiempo} de su saldo pasaron a {pc}", pago=PAGO_SALDO_DEL_SOCIO,
                tiempo=f"+ {tiempo}"))

    for fila in conexion.execute(
        """
        SELECT traslados_sesion.fecha, origen.nombre AS de, destino.nombre AS a, usuarios.nombre AS quien
        FROM traslados_sesion
        JOIN estaciones AS origen ON origen.id = traslados_sesion.estacion_origen_id
        JOIN estaciones AS destino ON destino.id = traslados_sesion.estacion_destino_id
        JOIN usuarios ON usuarios.id = traslados_sesion.usuario_id
        WHERE traslados_sesion.fecha > ? AND traslados_sesion.fecha <= ?
        """, rango,
    ):
        movimientos.append(movimiento(
            fila["fecha"], TIPO_TRASLADO, (GRUPO_HABILITACIONES,),
            f"{fila['de']} pasó a {fila['a']}, con el tiempo que le quedaba", nota=f"lo hizo {fila['quien']}"))
    return movimientos


# ------------------------------------------------------------- saldo de los socios
def saldos(conexion, desde: str, hasta: str) -> list:
    """Lo que cambió el saldo de un socio en (desde, hasta] sin ser una carga
    (las cargas son ventas): lo que vuelve al saldo al irse, lo que se le sacó al
    anular una carga, un saldo importado y ORDENAR SALDOS."""
    rango = (desde, hasta)
    movimientos = []
    for fila in conexion.execute(
        f"""
        SELECT movimientos_saldo_miembro.fecha, movimientos_saldo_miembro.tipo, movimientos_saldo_miembro.minutos,
               {_SOCIO_SQL}, estaciones.nombre AS pc
        FROM movimientos_saldo_miembro
        JOIN miembros ON miembros.id = movimientos_saldo_miembro.miembro_id
        LEFT JOIN sesiones_pc ON sesiones_pc.id = movimientos_saldo_miembro.sesion_id
        LEFT JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        WHERE movimientos_saldo_miembro.tipo IN (?, ?, ?)
          AND movimientos_saldo_miembro.fecha > ? AND movimientos_saldo_miembro.fecha <= ?
        """, (dominio.MOVIMIENTO_REINTEGRO, dominio.MOVIMIENTO_ANULACION, dominio.MOVIMIENTO_IMPORTACION, *rango),
    ):
        tiempo = dominio.texto_minutos(fila["minutos"])
        socio = _socio(fila)
        if fila["tipo"] == dominio.MOVIMIENTO_REINTEGRO:
            de_donde = f" se fue de {fila['pc']}" if fila["pc"] else " se fue"
            movimientos.append(movimiento(
                fila["fecha"], TIPO_SALDO_DEVUELTO, (GRUPO_SALDO,),
                f"{socio}{de_donde}: lo que no usó vuelve a su saldo", tiempo=f"+ {tiempo} al saldo"))
        elif fila["tipo"] == dominio.MOVIMIENTO_ANULACION:
            de_donde = f"de {fila['pc']}" if fila["pc"] else "del saldo"
            movimientos.append(movimiento(
                fila["fecha"], TIPO_SALDO_QUITADO, (GRUPO_SALDO,),
                f"{socio}: se le sacaron {tiempo} {de_donde} (carga anulada)", tiempo=f"− {tiempo}"))
        else:
            movimientos.append(movimiento(
                fila["fecha"], TIPO_SALDO_IMPORTADO, (GRUPO_SALDO,), f"{socio}: saldo importado",
                tiempo=f"+ {tiempo} al saldo"))

    for fila in conexion.execute(
        f"""
        SELECT ajustes_saldo_miembro.fecha, ajustes_saldo_miembro.saldo_anterior, ajustes_saldo_miembro.saldo_nuevo,
               {_SOCIO_SQL}, usuarios.nombre AS quien,
               COALESCE(NULLIF(otro.nombre, ''), otro.usuario) AS otro
        FROM ajustes_saldo_miembro
        JOIN miembros ON miembros.id = ajustes_saldo_miembro.miembro_id
        JOIN usuarios ON usuarios.id = ajustes_saldo_miembro.usuario_id
        LEFT JOIN miembros AS otro ON otro.id = ajustes_saldo_miembro.otro_miembro_id
        WHERE ajustes_saldo_miembro.fecha > ? AND ajustes_saldo_miembro.fecha <= ?
        """, rango,
    ):
        cambio = fila["saldo_nuevo"] - fila["saldo_anterior"]
        detalle = (f"{fila['quien']} cambió el saldo de {_socio(fila)}: de "
                   f"{dominio.texto_minutos(fila['saldo_anterior'])} a {dominio.texto_minutos(fila['saldo_nuevo'])}")
        if fila["otro"]:
            detalle += f" (se lo pasó a {fila['otro']})" if cambio < 0 else f" (lo recibió de {fila['otro']})"
        signo = "+" if cambio >= 0 else "−"
        movimientos.append(movimiento(
            fila["fecha"], TIPO_ORDENAR_SALDOS, (GRUPO_SALDO,), detalle,
            tiempo=f"{signo} {dominio.texto_minutos(abs(cambio))} al saldo"))
    return movimientos


# ------------------------------------------------------------- caja y Cuenta de la PC
def _lo_contado(esperado: float, contado) -> str:
    if contado is None:
        return "sin contar"
    if abs(contado - esperado) < 0.005:
        return "contado justo"
    return f"contó {dominio.texto_pesos(contado)}"


def caja_y_cuenta(conexion, desde: str, hasta: str) -> list:
    """La caja que se abrió y la que pasó de mano en (desde, hasta], con lo que se
    contó, y lo que se anotó a la Cuenta de la PC o se dio por perdido. Lo que se
    cobró de una Cuenta es una venta (ventas_de_cuentas)."""
    rango = (desde, hasta)
    movimientos = []
    for fila in conexion.execute(
        """
        SELECT cajas.id, cajas.abierta_en, cajas.cambio_esperado, cajas.cambio_contado,
               responsables.nombre AS responsable, abrio.nombre AS abrio
        FROM cajas
        JOIN usuarios AS responsables ON responsables.id = cajas.responsable_id
        JOIN usuarios AS abrio ON abrio.id = cajas.abierta_por
        WHERE cajas.abierta_en > ? AND cajas.abierta_en <= ?
        """, rango,
    ):
        contado = fila["cambio_contado"]
        diferencia = None if contado is None else round(contado - fila["cambio_esperado"], 2)
        movimientos.append(movimiento(
            fila["abierta_en"], TIPO_CAJA, (GRUPO_CAJA,),
            f"{fila['responsable']} abrió la Caja Nº {fila['id']} · cambio "
            f"{dominio.texto_pesos(fila['cambio_esperado'])}, {_lo_contado(fila['cambio_esperado'], contado)}",
            nota="" if fila["abrio"] == fila["responsable"] else f"la abrió {fila['abrio']}",
            plata=diferencia if diferencia else None, clase_plata=PLATA_DIFERENCIA if diferencia else None))

    for fila in conexion.execute(
        """
        SELECT relevos_caja.fecha, relevos_caja.caja_id, relevos_caja.monto_esperado, relevos_caja.monto_contado,
               relevos_caja.diferencia, de.nombre AS de, a.nombre AS a
        FROM relevos_caja
        JOIN usuarios AS de ON de.id = relevos_caja.de_usuario_id
        JOIN usuarios AS a ON a.id = relevos_caja.a_usuario_id
        WHERE relevos_caja.fecha > ? AND relevos_caja.fecha <= ?
        """, rango,
    ):
        movimientos.append(movimiento(
            fila["fecha"], TIPO_RELEVO, (GRUPO_CAJA,),
            f"{fila['a']} recibió la Caja Nº {fila['caja_id']} de {fila['de']} · había que tener "
            f"{dominio.texto_pesos(fila['monto_esperado'])}, contó {dominio.texto_pesos(fila['monto_contado'])}",
            plata=fila["diferencia"], clase_plata=PLATA_DIFERENCIA))

    for fila in conexion.execute(
        f"""
        SELECT cuenta_pc_items.fecha, cuenta_pc_items.descripcion, cuenta_pc_items.cantidad,
               cuenta_pc_items.subtotal, cuenta_pc_items.minutos, cuenta_pc_items.quitado_fecha,
               cuenta_pc_items.quitado_motivo, quito.nombre AS quitado_por,
               {_pc_en("cuenta_pc_items.fecha")} AS pc
        FROM cuenta_pc_items
        JOIN cuentas_pc ON cuentas_pc.id = cuenta_pc_items.cuenta_id
        JOIN sesiones_pc ON sesiones_pc.id = cuentas_pc.sesion_id
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        LEFT JOIN usuarios AS quito ON quito.id = cuenta_pc_items.quitado_por
        WHERE cuenta_pc_items.fecha > ? AND cuenta_pc_items.fecha <= ?
        """, rango,
    ):
        quitado = fila["quitado_fecha"] is not None
        nota = ""
        if quitado:
            nota = f"quitado por {fila['quitado_por']} a las {hora(fila['quitado_fecha'])}"
            if fila["quitado_motivo"]:
                nota += f": {fila['quitado_motivo']}"
        grupos = (GRUPO_HABILITACIONES, GRUPO_CAJA) if fila["minutos"] else (GRUPO_CAJA,)
        movimientos.append(movimiento(
            fila["fecha"], TIPO_A_CUENTA, grupos,
            f"{fila['pc']}: {fila['cantidad']} x {fila['descripcion']} anotado a la Cuenta de la PC", nota=nota,
            pago=PAGO_A_CUENTA, tiempo=f"+ {dominio.texto_minutos(fila['minutos'])}" if fila["minutos"] else "",
            plata=fila["subtotal"], clase_plata=PLATA_CUENTA, anulada=quitado))

    for fila in conexion.execute(
        """
        SELECT cuentas_pc.fecha_cierre, cuentas_pc.motivo_perdida, estaciones.nombre AS pc, usuarios.nombre AS quien,
               COALESCE((SELECT SUM(subtotal) FROM cuenta_pc_items
                         WHERE cuenta_id = cuentas_pc.id AND quitado_fecha IS NULL), 0) AS total
        FROM cuentas_pc
        JOIN sesiones_pc ON sesiones_pc.id = cuentas_pc.sesion_id
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        LEFT JOIN usuarios ON usuarios.id = cuentas_pc.usuario_cierre_id
        WHERE cuentas_pc.estado = ? AND cuentas_pc.fecha_cierre > ? AND cuentas_pc.fecha_cierre <= ?
        """, (dominio.CUENTA_PERDIDA, *rango),
    ):
        detalle = f"{fila['pc']}: {fila['quien'] or 'un Administrador'} dio por perdida la Cuenta de la PC"
        if fila["motivo_perdida"]:
            detalle += f": {fila['motivo_perdida']}"
        movimientos.append(movimiento(
            fila["fecha_cierre"], TIPO_CUENTA_PERDIDA, (GRUPO_CAJA,), detalle,
            plata=fila["total"], clase_plata=PLATA_PERDIDA))
    return movimientos


def cierre(cierre_fila, caja, responsable: str) -> dict:
    """El último renglón de un turno ya cerrado: quién lo cerró, lo que había que
    retirar y, si el Admin ya contó el sobre en Control de Cierres, cuánto había."""
    detalle = (f"{responsable} cerró la Caja Nº {caja['id']}" if caja is not None
               else f"Cierre de Turno de {responsable}")
    detalle += f" · a retirar {dominio.texto_pesos(cierre_fila['monto_a_retirar'])}"
    notas = []
    if caja is not None and caja["cierre_forzoso"]:
        notas.append("se cerró sola al pasar la hora")
    diferencia = None
    if cierre_fila["monto_contado"] is not None:
        notas.append(f"el sobre tenía {dominio.texto_pesos(cierre_fila['monto_contado'])}")
        diferencia = cierre_fila["diferencia"]
    return movimiento(cierre_fila["fecha_cierre"], TIPO_CIERRE, (GRUPO_CAJA,), detalle, nota=" · ".join(notas),
                      plata=diferencia, clase_plata=PLATA_DIFERENCIA if diferencia is not None else None)
