"""
reservas_habilitar_repo.py
============================
Habilitar una reserva (control_pcs/repositories/reservas_repo.py): el cliente
llegó, se cobra lo que falta y se le abre el equipo con el bono que reservó.
Se separó de reservas_repo.py porque ese archivo pasaba las 600 líneas (regla 12
de CLAUDE.md); las reglas son las mismas, ver el comentario de ese módulo.

Lo importante: lo que falta entra en la caja de quien habilita, y si ya estaba
todo pagado NO se crea ninguna venta (esa plata está en la caja donde se cobró
al reservar). Por eso el bono se anota en la sesión con la venta con que se
pagó la reserva, sin cobrarlo de nuevo.
"""

from datetime import datetime, timedelta

import dominio
from database import conexion_db
from repositories import usuarios_repo
from control_pcs.repositories import pcs_repo, playstation_repo, reservas_horario_repo, reservas_repo


def lugares_para_habilitar(reserva_id: int) -> list:
    """
    Dónde se puede habilitar ahora una reserva: los equipos LIBRES de su tipo,
    como {"estacion_id", "nombre", "es_la_reservada", "enlazada"} (enlazada: el
    Cliente PC de esa PC está respondiendo). Para una de PC común, cualquier PC
    común libre, con la reservada primero; una "A reprogramar" ya no tiene PC
    propia (decisión del dueño). Para PCSTREAM, PCSTREAM; para la consola, la
    consola (estacion_id None). Lista vacía si no hay ninguno libre.

    "reservada_para" ("Marta hoy 11:00", o None): esa PC tiene otra reserva antes
    de que termine el bono de esta, así que quedaría ocupada cuando llegue ese
    cliente (parte 2 de las reservas). Esas van al final; la pantalla lo avisa.
    """
    with conexion_db() as conexion:
        reserva = reservas_repo._reserva_abierta(conexion, reserva_id)
    if reserva["equipo"] == dominio.EQUIPO_RESERVA_PLAYSTATION:
        consola = playstation_repo.estado()
        libre = consola["sesion"] is None or consola["tiempo_agotado"]
        return [{"estacion_id": None, "nombre": dominio.NOMBRE_PLAYSTATION, "es_la_reservada": True,
                 "enlazada": True, "reservada_para": None}] if libre else []

    propia = reserva["estacion_id"] if reserva["estado"] == dominio.RESERVA_PENDIENTE else None
    es_de_pcstream = reserva["equipo"] == dominio.EQUIPO_RESERVA_PCSTREAM
    ahora = datetime.now()
    hasta = ahora + timedelta(minutes=reserva["minutos"])
    lugares = []
    for item in pcs_repo.estado_estaciones():
        estacion = item["estacion"]
        if dominio.es_pcstream(estacion["nombre"]) != es_de_pcstream:
            continue
        if item["sesion"] is not None and item["segundos_restantes"]:
            continue
        otra = item["reserva"]
        reservada_para = None
        if otra is not None and otra["id"] != reserva_id and otra["inicio"] < hasta:
            reservada_para = f"{otra['cliente']} {reservas_horario_repo.texto_de_la_hora(otra['inicio'], ahora)}"
        lugares.append({"estacion_id": estacion["id"], "nombre": estacion["nombre"],
                        "es_la_reservada": es_de_pcstream or estacion["id"] == propia,
                        "enlazada": item["enlazada"], "reservada_para": reservada_para})
    lugares.sort(key=lambda lugar: (not lugar["es_la_reservada"], lugar["reservada_para"] is not None))
    return lugares


def _revisar_pc(conexion, reserva, estacion_id, ahora: datetime):
    """La PC donde se va a habilitar la reserva, o ValueError: tiene que estar
    activa, libre (no se le suma el tiempo de la reserva al cliente que ya está
    sentado; una sesión que llegó a cero cuenta como libre) y ser del tipo de la
    reserva (un bono de PCSTREAM solo en PCSTREAM, uno común en cualquier otra)."""
    if estacion_id is None:
        raise ValueError("Elegí en qué PC se habilita.")
    estacion = conexion.execute(
        "SELECT * FROM estaciones WHERE id = ? AND activa = 1", (estacion_id,)
    ).fetchone()
    if estacion is None:
        raise ValueError("Esa PC ya no está disponible. Actualizá la pantalla e intentá de nuevo.")
    es_de_pcstream = reserva["equipo"] == dominio.EQUIPO_RESERVA_PCSTREAM
    if dominio.es_pcstream(estacion["nombre"]) != es_de_pcstream:
        if es_de_pcstream:
            raise ValueError(f"Es una reserva de {dominio.NOMBRE_PCSTREAM}: se habilita solo ahí.")
        raise ValueError(
            f"{dominio.NOMBRE_PCSTREAM} tiene sus propios precios: una reserva de PC común no se habilita ahí."
        )
    sesion = conexion.execute(
        "SELECT fecha_fin_prevista FROM sesiones_pc WHERE estacion_id = ? AND estado = ?",
        (estacion_id, dominio.SESION_ACTIVA),
    ).fetchone()
    if sesion is not None and dominio.segundos_restantes(datetime.fromisoformat(sesion["fecha_fin_prevista"]), ahora):
        raise ValueError(f"{estacion['nombre']} está en uso. Elegí otra PC libre.")
    return estacion


def _abrir_en_una_pc(conexion, reserva, estacion_id: int, venta_id: int, ahora: datetime) -> tuple:
    """
    Habilita la reserva en una PC (la de la consola es
    playstation_repo._abrir_sesion_de_reserva): una sesión nueva con los minutos
    del bono reservado, sin cobrar nada acá. El bono queda en la tabla de vínculo
    de siempre (sesion_bonos, o sesion_pcstream_bonos si es de PCSTREAM) con
    `venta_id`, la venta con que se pagó la reserva: así los reportes de bonos,
    Reportes > PCSTREAM y el reintegro de los socios (reintegros_repo) la ven como
    cualquier bono, contado una sola vez, el día que se vendió. Devuelve
    (sesion_id, nombre de la PC).
    """
    estacion = _revisar_pc(conexion, reserva, estacion_id, ahora)
    sesion_id = pcs_repo._abrir_o_extender_sesion(conexion, estacion_id, reserva["minutos"], ahora)
    tabla_vinculo = (
        "sesion_pcstream_bonos" if reserva["equipo"] == dominio.EQUIPO_RESERVA_PCSTREAM else "sesion_bonos"
    )
    conexion.execute(
        f"INSERT INTO {tabla_vinculo} (sesion_id, bono_id, minutos, precio, venta_id) VALUES (?, ?, ?, ?, ?)",
        (sesion_id, reserva["bono_id"], reserva["minutos"], reserva["precio"], venta_id),
    )
    return sesion_id, estacion["nombre"]


def _falta(conexion, reserva) -> float:
    return max(0.0, round(reserva["precio"] - reservas_repo._pagado(conexion, reserva["id"]), 2))


def preparar_habilitacion(reserva_id: int, estacion_id) -> float:
    """
    Lo que controla habilitar ANTES de cobrar el resto, sin grabar nada (la
    reserva sigue esperando y el lugar elegido sirve; ValueError si no), para no
    cobrar algo que después no se puede habilitar. Devuelve lo que falta cobrar.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        reserva = reservas_repo._reserva_abierta(conexion, reserva_id)
        if reserva["equipo"] != dominio.EQUIPO_RESERVA_PLAYSTATION:
            _revisar_pc(conexion, reserva, estacion_id, ahora)
        return _falta(conexion, reserva)


def habilitar(reserva_id: int, usuario_id: int, estacion_id, pagos: list) -> dict:
    """
    El cliente llegó: se cobra lo que falta (si falta algo) y se le abre el
    equipo con el bono reservado. `estacion_id` es la PC donde se sienta (None
    para la consola); `pagos`, los de la ventana de cobro del resto (vacío si ya
    estaba todo pagado).

    Lo que falta entra en la caja de quien habilita. Si ya estaba todo pagado NO
    se crea ninguna venta: esa plata está en la caja donde se cobró al reservar.
    Todo en una transacción: si el equipo no está libre, no se cobra nada.
    Devuelve {"lugar": dónde quedó habilitada, "cobrado": lo que se cobró}.
    """
    usuarios_repo.usuario_habilitado(usuario_id)
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        reserva = reservas_repo._reserva_abierta(conexion, reserva_id)
        falta = _falta(conexion, reserva)
        if falta:
            if sum(pago["monto"] for pago in pagos) < falta - 0.01:
                raise ValueError("Los pagos no cubren lo que falta de la reserva.")
            reservas_repo._cobrar(conexion, reserva_id, dominio.PAGO_RESERVA_RESTO, usuario_id, falta, pagos,
                                  reserva["equipo"], ahora)

        # La venta con que se "vendió" el bono: el primer pago que sigue en pie.
        venta_del_bono = conexion.execute(
            """
            SELECT ventas.id FROM reservas_pagos JOIN ventas ON ventas.id = reservas_pagos.venta_id
            WHERE reservas_pagos.reserva_id = ? AND reservas_pagos.tipo IN (?, ?) AND ventas.estado = ?
            ORDER BY ventas.id LIMIT 1
            """,
            (reserva_id, dominio.PAGO_RESERVA_ANTICIPO, dominio.PAGO_RESERVA_RESTO, dominio.VENTA_CONFIRMADA),
        ).fetchone()["id"]

        sesion_pc_id = sesion_playstation_id = None
        if reserva["equipo"] == dominio.EQUIPO_RESERVA_PLAYSTATION:
            estacion_id = None
            sesion_playstation_id = playstation_repo._abrir_sesion_de_reserva(
                conexion, reserva["bono_id"], reserva["minutos"], reserva["precio"], venta_del_bono, ahora
            )
            lugar = dominio.NOMBRE_PLAYSTATION
        else:
            sesion_pc_id, lugar = _abrir_en_una_pc(conexion, reserva, estacion_id, venta_del_bono, ahora)

        conexion.execute(
            """
            UPDATE reservas SET estado = ?, estado_desde = ?, estado_por = ?, estacion_habilitada_id = ?,
                                sesion_pc_id = ?, sesion_playstation_id = ?
            WHERE id = ?
            """,
            (dominio.RESERVA_HABILITADA, reservas_repo._iso(ahora), usuario_id, estacion_id, sesion_pc_id,
             sesion_playstation_id, reserva_id),
        )
    return {"lugar": lugar, "cobrado": falta}
