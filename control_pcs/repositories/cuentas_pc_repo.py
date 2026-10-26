"""
cuentas_pc_repo.py
====================
La "Cuenta de la PC" (pedido del dueño, 2026-10-25: "Pedro está en la PC 1,
pide algo, tiempo o un pancho, pero está jugando y no puede pagar en el
momento; que mis operadores puedan cargarle esa consumición y la PC quede
titilando hasta que realmente se le cobre").

- Se anota en la cuenta de la SESIÓN que está corriendo en esa PC (una cuenta
  por sesión, ver database_esquema "CUENTA DE LA PC"): si el cliente se cambia
  de máquina, la cuenta va con él; si se va debiendo, el próximo cliente de esa
  PC arranca una propia y la vieja sigue a la vista. Sin una sesión en curso no
  se anota nada: la cuenta es de quien está jugando (y una PC sin tiempo sigue
  bloqueada, como siempre).
- Un artículo baja el stock al anotarlo (ya se lo llevó); un bono suma el
  tiempo en ese momento. La plata entra recién al cobrar, en la caja de quien
  cobra: el kiosko como una venta de kiosko (sin volver a bajar el stock) y
  cada bono como una venta de Alquiler de PCs con su vínculo de siempre en
  sesion_bonos/sesion_pcstream_bonos, así Caja, Cierre de Turno y los Reportes
  lo cuentan igual que si se hubiera pagado en el momento.
- Cualquier operador anota y cobra (en el mostrador). Quitar un renglón anotado
  por error y dar una cuenta por perdida es solo del Admin, con el motivo:
  nada se borra.
- El tope (cuánto puede deber una PC) y si se puede anotar tiempo los fija el
  Admin en Configuración ADMIN > Reglas de Cuenta de PC (`obtener_reglas`).
"""

import json
from datetime import datetime, timedelta

import dominio
from database import conexion_db
from repositories import config_repo, turnos_repo, usuarios_repo, ventas_repo
from control_pcs.repositories import bonos_miembro_repo, deudas_pc_repo, miembros_repo, pcs_repo, pcstream_repo

_CLAVE_REGLAS = "reglas_cuenta_pc"


class TopeSuperado(ValueError):
    """Lo que se quiere anotar deja a la PC debiendo más que el tope. Con la regla
    "con la clave de un Admin" (`con_clave`), la pantalla puede pedirla y volver a
    intentar con `autoriza`; si no, el mensaje ya dice qué hacer."""

    def __init__(self, mensaje: str, con_clave: bool):
        super().__init__(mensaje)
        self.con_clave = con_clave


# ---------------------------------------------------------------------
# Reglas (Configuración ADMIN > Reglas de Cuenta de PC)
# ---------------------------------------------------------------------

def obtener_reglas() -> dict:
    """{"tope", "al_pasar_el_tope", "tiempo_a_cuenta"}. Guardadas como JSON en
    `configuracion`; mientras el Admin no las toque, las de arranque: tope de
    $10.000 (decisión del dueño), no deja pasarse y se puede anotar tiempo."""
    reglas = {
        "tope": dominio.TOPE_CUENTA_PC_INICIAL,
        "al_pasar_el_tope": dominio.TOPE_CUENTA_NO_DEJA,
        "tiempo_a_cuenta": True,
    }
    with conexion_db() as conexion:
        fila = conexion.execute("SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_REGLAS,)).fetchone()
    if fila:
        try:
            guardadas = json.loads(fila["valor"])
        except (ValueError, TypeError):
            guardadas = {}
        if isinstance(guardadas, dict):
            reglas.update({clave: guardadas[clave] for clave in reglas if clave in guardadas})
    return reglas


def guardar_reglas(usuario_id: int, tope, al_pasar_el_tope: str, tiempo_a_cuenta: bool):
    """Solo un Admin activo. El tope en 0 deja anotar nada."""
    usuarios_repo.exigir_admin(usuario_id, "cambiar las reglas de la Cuenta de la PC")
    try:
        tope = round(float(tope), 2)
    except (TypeError, ValueError):
        raise ValueError("El tope tiene que ser un número.")
    if tope < 0:
        raise ValueError("El tope no puede ser negativo.")
    if al_pasar_el_tope not in dominio.ACCIONES_TOPE_CUENTA_PC:
        raise ValueError("Elegí qué pasa si se pasa del tope.")
    valor = json.dumps({"tope": tope, "al_pasar_el_tope": al_pasar_el_tope, "tiempo_a_cuenta": bool(tiempo_a_cuenta)})
    with conexion_db() as conexion:
        conexion.execute("INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)", (_CLAVE_REGLAS, valor))


# ---------------------------------------------------------------------
# Anotar
# ---------------------------------------------------------------------

def anotar_articulos(estacion_id: int, lineas: list, usuario_id: int, nombre: str = None, autoriza: dict = None) -> dict:
    """
    Anota lo del carrito de Ventas en la cuenta de la sesión de esa PC.
    `lineas` como las de ventas_repo.confirmar_venta ({"codigo", "descripcion",
    "cantidad", "precio_unitario"}, el precio que tenía el carrito). Baja el
    stock ya (puede quedar negativo, como en una venta). `nombre`: a nombre de
    quién, si la cuenta es nueva (un socio va con el suyo). `autoriza`:
    {"nombre", "clave"} de un Admin, si la regla deja pasarse del tope con su
    clave. Devuelve {"estacion", "nombre", "debe"}: lo que debe ahora esa PC.
    """
    if not lineas:
        raise ValueError("Todavía no escaneaste ningún producto.")
    total = round(ventas_repo.total_carrito(lineas), 2)
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        estacion, sesion = _estacion_con_sesion(conexion, estacion_id, ahora)
        _revisar_tope(conexion, estacion, total, autoriza)
        cuenta_id = _cuenta_de_la_sesion(conexion, sesion, usuario_id, nombre, ahora)
        for linea in lineas:
            conexion.execute(
                """
                INSERT INTO cuenta_pc_items
                    (cuenta_id, tipo, fecha, usuario_id, descripcion, cantidad, precio_unitario, subtotal,
                     articulo_codigo)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (cuenta_id, dominio.ITEM_CUENTA_ARTICULO, ahora.isoformat(timespec="microseconds"), usuario_id,
                 linea["descripcion"], linea["cantidad"], round(linea["precio_unitario"], 2),
                 round(ventas_repo.subtotal_linea(linea), 2), linea["codigo"]),
            )
            # Baja ya: el pancho salió del estante aunque se cobre después. Al cobrar
            # no se vuelve a bajar (ventas_repo._grabar_venta_kiosko, descontar_stock).
            conexion.execute(
                "UPDATE articulos SET stock = stock - ? WHERE codigo = ?", (linea["cantidad"], linea["codigo"])
            )
        return _como_quedo(conexion, estacion, cuenta_id)


def anotar_bono(estacion_id: int, bono_id: int, usuario_id: int, nombre: str = None, autoriza: dict = None) -> dict:
    """
    Le suma a la sesión de esa PC el tiempo de un bono de su catálogo (el de
    PCSTREAM si es PCSTREAM, el común si no; ver pcs_repo.asignar_bono) y lo
    anota en la cuenta, sin cobrar. Solo extiende una sesión en curso: a una PC
    sin tiempo se le vende como siempre. Mismos `nombre`, `autoriza` y
    devolución que anotar_articulos.
    """
    if not obtener_reglas()["tiempo_a_cuenta"]:
        raise ValueError("El Admin no deja anotar tiempo a cuenta (Configuración ADMIN > Reglas de Cuenta de PC).")
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        estacion, sesion = _estacion_con_sesion(conexion, estacion_id, ahora)
        es_pcstream = dominio.es_pcstream(estacion["nombre"])
        bono = pcstream_repo.obtener_bono(bono_id) if es_pcstream else pcs_repo.obtener_bono(bono_id)
        if bono is None or not bono["activo"]:
            raise ValueError("Ese bono ya no está disponible.")
        _revisar_tope(conexion, estacion, round(bono["precio"], 2), autoriza)
        cuenta_id = _cuenta_de_la_sesion(conexion, sesion, usuario_id, nombre, ahora)
        # La sesión está en curso (_estacion_con_sesion), así que esto la estira.
        pcs_repo._abrir_o_extender_sesion(conexion, estacion_id, bono["minutos"], ahora)
        conexion.execute(
            f"""
            INSERT INTO cuenta_pc_items
                (cuenta_id, tipo, fecha, usuario_id, descripcion, cantidad, precio_unitario, subtotal,
                 {"bono_pcstream_id" if es_pcstream else "bono_tiempo_id"}, minutos)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?)
            """,
            (cuenta_id, dominio.ITEM_CUENTA_BONO, ahora.isoformat(timespec="microseconds"), usuario_id,
             f"Bono {bono['nombre']}", round(bono["precio"], 2), round(bono["precio"], 2), bono_id, bono["minutos"]),
        )
        return _como_quedo(conexion, estacion, cuenta_id)


def anotar_tiempo_socio(estacion_id: int, usuario_id: int, bono_id: int = None, monto: float = None,
                        autoriza: dict = None) -> dict:
    """
    El socio que está jugando pide más tiempo y lo paga después (pedido del
    dueño, 2026-10-25): un bono de socio (`bono_id`, bonos_miembro_repo) o un
    `monto` con la tarifa de socios (miembros_repo.minutos_por_monto, con la
    carga mínima de siempre), como en Cargar Saldo. Se le suma ya a su sesión,
    SIN tocar su saldo: mientras no lo paga es como un bono (si se va antes, no se
    le devuelve como saldo). Al cobrarlo queda como una carga suya que pasó a la
    sesión (ver _cobrar_tiempo_socio). Solo en una sesión abierta por un socio.
    """
    if not obtener_reglas()["tiempo_a_cuenta"]:
        raise ValueError("El Admin no deja anotar tiempo a cuenta (Configuración ADMIN > Reglas de Cuenta de PC).")
    if bono_id is not None:
        bono = bonos_miembro_repo.obtener_bono(bono_id)
        if bono is None or not bono["activo"]:
            raise ValueError("Ese bono ya no está disponible.")
        minutos, precio, descripcion = bono["minutos"], round(bono["precio"], 2), f"Socio: {bono['nombre']}"
    else:
        tramos = config_repo.obtener_tramos_tarifa_hora_miembro()
        monto = round(float(monto or 0), 2)
        miembros_repo.validar_monto_de_carga(tramos, monto)
        _tarifa, minutos = miembros_repo.minutos_por_monto(tramos, monto)
        if minutos <= 0:
            raise ValueError("Ese monto no alcanza ni para media hora a la tarifa de socios.")
        precio = monto
        descripcion = f"Socio: {minutos // 60} h {minutos % 60:02d} m por monto"
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        estacion, sesion = _estacion_con_sesion(conexion, estacion_id, ahora)
        if sesion["miembro_id"] is None:
            raise ValueError(f"'{estacion['nombre']}' no la abrió un socio: anotale un bono de PC.")
        _revisar_tope(conexion, estacion, precio, autoriza)
        cuenta_id = _cuenta_de_la_sesion(conexion, sesion, usuario_id, None, ahora)
        pcs_repo._abrir_o_extender_sesion(conexion, estacion_id, minutos, ahora)
        conexion.execute(
            """
            INSERT INTO cuenta_pc_items
                (cuenta_id, tipo, fecha, usuario_id, descripcion, cantidad, precio_unitario, subtotal,
                 bono_miembro_id, miembro_id, minutos)
            VALUES (?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?)
            """,
            (cuenta_id, dominio.ITEM_CUENTA_TIEMPO_SOCIO, ahora.isoformat(timespec="microseconds"), usuario_id,
             descripcion, precio, precio, bono_id, sesion["miembro_id"], minutos),
        )
        return _como_quedo(conexion, estacion, cuenta_id)


def _estacion_con_sesion(conexion, estacion_id: int, ahora: datetime):
    """La PC y su sesión en curso (con tiempo), o ValueError con qué hacer."""
    estacion = conexion.execute(
        "SELECT * FROM estaciones WHERE id = ? AND activa = 1", (estacion_id,)
    ).fetchone()
    if estacion is None:
        raise ValueError("Esa PC ya no está disponible. Actualizá la pantalla e intentá de nuevo.")
    sesion = conexion.execute(
        "SELECT * FROM sesiones_pc WHERE estacion_id = ? AND estado = ?", (estacion_id, dominio.SESION_ACTIVA)
    ).fetchone()
    if sesion is None or dominio.segundos_restantes(datetime.fromisoformat(sesion["fecha_fin_prevista"]), ahora) == 0:
        raise ValueError(
            f"'{estacion['nombre']}' no tiene una sesión en curso. La cuenta es del cliente que está "
            "jugando: a una PC sin tiempo se le vende un bono como siempre."
        )
    return estacion, sesion


def _revisar_tope(conexion, estacion, a_sumar: float, autoriza: dict):
    """Que con `a_sumar` la PC no deba más que el tope. Con la regla "con la clave
    de un Admin", `autoriza` = {"nombre", "clave"} de un Admin activo deja pasarse."""
    reglas = obtener_reglas()
    debe = deudas_pc_repo.por_estacion(conexion).get(estacion["id"], {"total": 0.0})["total"]
    if round(debe + a_sumar, 2) <= round(float(reglas["tope"]), 2):
        return
    con_clave = reglas["al_pasar_el_tope"] == dominio.TOPE_CUENTA_CON_CLAVE_ADMIN
    if con_clave and autoriza:
        admin = usuarios_repo._activo_por_nombre(conexion, autoriza.get("nombre") or "")
        if admin is None or not dominio.es_admin(admin) or not usuarios_repo._clave_correcta(
                conexion, admin, autoriza.get("clave") or ""):
            raise TopeSuperado("El usuario o la clave del Administrador no son correctos.", con_clave)
        return
    if float(reglas["tope"]) <= 0:
        raise TopeSuperado("El Admin no deja anotar nada a cuenta (el tope está en $ 0).", False)
    texto_debe = f"ya debe {dominio.texto_pesos(debe)} y " if debe > 0 else ""
    mensaje = (f"'{estacion['nombre']}' {texto_debe}con esto ({dominio.texto_pesos(a_sumar)}) pasaría el tope de "
               f"{dominio.texto_pesos(reglas['tope'])}.")
    mensaje += " Hace falta la clave de un Administrador." if con_clave else " Cobrale primero lo que debe."
    raise TopeSuperado(mensaje, con_clave)


def _cuenta_de_la_sesion(conexion, sesion, usuario_id: int, nombre: str, ahora: datetime) -> int:
    """La cuenta abierta de esa sesión, o una nueva. Un socio va con su nombre; si
    no, el que escribió el operador (puede quedar vacío)."""
    cuenta = conexion.execute(
        "SELECT id, estado FROM cuentas_pc WHERE sesion_id = ?", (sesion["id"],)
    ).fetchone()
    if cuenta is not None:
        if cuenta["estado"] != dominio.CUENTA_ABIERTA:
            raise ValueError("La cuenta de este cliente ya se cerró. Actualizá la pantalla e intentá de nuevo.")
        return cuenta["id"]
    socio = None
    if sesion["miembro_id"] is not None:
        socio = conexion.execute("SELECT nombre FROM miembros WHERE id = ?", (sesion["miembro_id"],)).fetchone()
    nombre_cuenta = socio["nombre"] if socio is not None else (nombre or "").strip()
    cursor = conexion.execute(
        """
        INSERT INTO cuentas_pc (sesion_id, nombre, estado, fecha_apertura, usuario_apertura_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (sesion["id"], nombre_cuenta[:40], dominio.CUENTA_ABIERTA, ahora.isoformat(timespec="seconds"), usuario_id),
    )
    return cursor.lastrowid


def _como_quedo(conexion, estacion, cuenta_id: int) -> dict:
    nombre = conexion.execute("SELECT nombre FROM cuentas_pc WHERE id = ?", (cuenta_id,)).fetchone()["nombre"]
    debe = deudas_pc_repo.por_estacion(conexion).get(estacion["id"], {"total": 0.0})["total"]
    return {"estacion": estacion["nombre"], "nombre": nombre, "debe": debe}


# ---------------------------------------------------------------------
# Mirar
# ---------------------------------------------------------------------

def cuentas_de_la_estacion(estacion_id: int) -> list:
    """
    Las cuentas que se deben en esa PC (la del cliente de ahora primero), cada
    una con {"id", "nombre", "es_de_la_sesion_actual", "fecha_apertura",
    "total", "renglones"}; cada renglón con {"id", "tipo", "fecha",
    "descripcion", "cantidad", "precio_unitario", "subtotal", "anoto"}. Los
    quitados no vienen (ni suman).
    """
    with conexion_db() as conexion:
        cuentas = _cuentas_abiertas(conexion, "sesiones_pc.estacion_id = ?", (estacion_id,))
        activa = conexion.execute(
            "SELECT id FROM sesiones_pc WHERE estacion_id = ? AND estado = ?", (estacion_id, dominio.SESION_ACTIVA)
        ).fetchone()
    for cuenta in cuentas:
        cuenta["es_de_la_sesion_actual"] = activa is not None and cuenta["sesion_id"] == activa["id"]
    cuentas.sort(key=lambda cuenta: (not cuenta["es_de_la_sesion_actual"], cuenta["id"]))
    return cuentas


def cuentas_abiertas() -> list:
    """Todas las cuentas que se deben, con la PC donde están ("estacion") y quién
    abrió cada una ("abrio"): para el aviso del Cierre de Turno."""
    with conexion_db() as conexion:
        return _cuentas_abiertas(conexion, "1 = 1", ())


def _cuentas_abiertas(conexion, condicion: str, parametros: tuple) -> list:
    filas = conexion.execute(
        f"""
        SELECT cuentas_pc.*, estaciones.nombre AS estacion, usuarios.nombre AS abrio
        FROM cuentas_pc
        JOIN sesiones_pc ON sesiones_pc.id = cuentas_pc.sesion_id
        JOIN estaciones ON estaciones.id = sesiones_pc.estacion_id
        JOIN usuarios ON usuarios.id = cuentas_pc.usuario_apertura_id
        WHERE cuentas_pc.estado = ? AND {condicion}
        ORDER BY cuentas_pc.id
        """,
        (dominio.CUENTA_ABIERTA, *parametros),
    ).fetchall()
    cuentas = []
    for fila in filas:
        renglones = [dict(renglon) for renglon in conexion.execute(
            """
            SELECT cuenta_pc_items.id, tipo, fecha, descripcion, cantidad, precio_unitario, subtotal,
                   usuarios.nombre AS anoto
            FROM cuenta_pc_items
            JOIN usuarios ON usuarios.id = cuenta_pc_items.usuario_id
            WHERE cuenta_id = ? AND quitado_fecha IS NULL
            ORDER BY cuenta_pc_items.id
            """,
            (fila["id"],),
        )]
        if not renglones:
            continue  # le quitaron todo: no se debe nada
        cuentas.append({
            "id": fila["id"], "sesion_id": fila["sesion_id"], "nombre": fila["nombre"],
            "estacion": fila["estacion"], "abrio": fila["abrio"], "fecha_apertura": fila["fecha_apertura"],
            "total": round(sum(renglon["subtotal"] for renglon in renglones), 2), "renglones": renglones,
        })
    return cuentas


def fiado_del_turno_en_curso() -> list:
    """Las cuentas con algo anotado en el turno abierto (desde el último cierre)
    que todavía no se cobró (deudas_pc_repo.fiado_del_turno): lo que el Cierre de
    Turno pregunta antes de cerrar."""
    ventana = turnos_repo.ventana_del_turno_en_curso()
    with conexion_db() as conexion:
        return deudas_pc_repo.fiado_del_turno(conexion, ventana["desde"])


def aviso_antes_del_cierre(ahora: datetime = None):
    """
    El cartel "Cobrá antes de cerrar el turno" (pedido del dueño, 2026-10-25):
    desde MINUTOS_AVISO_CUENTAS_ANTES_DEL_FIN antes del fin del turno abierto, si
    hay algo fiado en ese turno sin cobrar, {"fin", "turno_label", "cuentas"
    (fiado_del_turno_en_curso)}; si no, None. Sigue apareciendo pasado el fin,
    hasta que se cierre el turno.
    """
    ahora = ahora or datetime.now()
    ventana = turnos_repo.ventana_del_turno_en_curso()
    if ahora < ventana["fin"] - timedelta(minutes=dominio.MINUTOS_AVISO_CUENTAS_ANTES_DEL_FIN):
        return None
    with conexion_db() as conexion:
        cuentas = deudas_pc_repo.fiado_del_turno(conexion, ventana["desde"])
    if not cuentas:
        return None
    return {"fin": ventana["fin"], "turno_label": ventana["turno_label"], "cuentas": cuentas}


# ---------------------------------------------------------------------
# Cobrar, quitar un renglón, dar por perdida
# ---------------------------------------------------------------------

def total_de(cuenta_ids: list) -> float:
    """Cuánto suman esas cuentas (abiertas, sin los renglones quitados): lo que
    se cobra en la ventana de cobro."""
    with conexion_db() as conexion:
        return round(sum(_total_abierto(conexion, cuenta_id) for cuenta_id in cuenta_ids), 2)


def _total_abierto(conexion, cuenta_id: int) -> float:
    cuenta = conexion.execute("SELECT estado FROM cuentas_pc WHERE id = ?", (cuenta_id,)).fetchone()
    if cuenta is None or cuenta["estado"] != dominio.CUENTA_ABIERTA:
        raise ValueError("Esa cuenta ya se cerró. Actualizá la pantalla e intentá de nuevo.")
    fila = conexion.execute(
        "SELECT COALESCE(SUM(subtotal), 0) AS total FROM cuenta_pc_items WHERE cuenta_id = ? AND quitado_fecha IS NULL",
        (cuenta_id,),
    ).fetchone()
    return round(fila["total"], 2)


def cobrar(cuenta_ids: list, usuario_id: int, pagos: list) -> list:
    """
    Cobra esas cuentas con los `pagos` de la ventana de cobro
    (ui.dialogo_pago.cobrar, netos de vuelto). Por cada cuenta graba una venta
    de kiosko con sus artículos (sin bajar el stock: ya bajó al anotarlos) y una
    venta de Alquiler de PCs por cada bono, con su vínculo en sesion_bonos (o
    sesion_pcstream_bonos), y reparte los pagos entre esas ventas
    (dominio.repartir_pagos). Todo en una transacción: o se cobra todo o nada.
    Las cuentas quedan COBRADAS (la PC deja de titilar). Devuelve los números
    de venta.
    """
    if not cuenta_ids:
        raise ValueError("Elegí qué cuenta cobrar.")
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        ventas = []  # (monto, cómo grabarla): primero se suma todo, después se reparten los pagos
        for cuenta_id in cuenta_ids:
            _total_abierto(conexion, cuenta_id)  # que siga abierta
            renglones = conexion.execute(
                "SELECT * FROM cuenta_pc_items WHERE cuenta_id = ? AND quitado_fecha IS NULL ORDER BY id",
                (cuenta_id,),
            ).fetchall()
            articulos = [renglon for renglon in renglones if renglon["tipo"] == dominio.ITEM_CUENTA_ARTICULO]
            if articulos:
                ventas.append((round(sum(renglon["subtotal"] for renglon in articulos), 2), ("KIOSKO", articulos)))
            for renglon in renglones:
                if renglon["tipo"] in dominio.TIPOS_ITEM_CUENTA_CON_TIEMPO:
                    ventas.append((round(renglon["subtotal"], 2), (renglon["tipo"], renglon)))
        if not ventas:
            raise ValueError("Esa cuenta ya no debe nada.")
        repartidos = dominio.repartir_pagos(pagos, [monto for monto, _ in ventas])

        numeros = []
        for (monto, (tipo, que)), pagos_de_la_venta in zip(ventas, repartidos):
            if tipo == "KIOSKO":
                lineas = [{"codigo": r["articulo_codigo"], "descripcion": r["descripcion"],
                           "cantidad": r["cantidad"], "precio_unitario": r["precio_unitario"]} for r in que]
                venta_id = ventas_repo._grabar_venta_kiosko(
                    conexion, usuario_id, lineas, pagos_de_la_venta, descontar_stock=False
                )
                conexion.executemany(
                    "UPDATE cuenta_pc_items SET venta_id = ? WHERE id = ?", [(venta_id, r["id"]) for r in que]
                )
            elif tipo == dominio.ITEM_CUENTA_TIEMPO_SOCIO:
                venta_id = _cobrar_tiempo_socio(conexion, que, usuario_id, monto, pagos_de_la_venta, ahora)
            else:
                venta_id = _cobrar_bono(conexion, que, usuario_id, monto, pagos_de_la_venta, ahora)
            numeros.append(venta_id)

        conexion.executemany(
            "UPDATE cuentas_pc SET estado = ?, fecha_cierre = ?, usuario_cierre_id = ? WHERE id = ?",
            [(dominio.CUENTA_COBRADA, ahora.isoformat(timespec="seconds"), usuario_id, cuenta_id)
             for cuenta_id in cuenta_ids],
        )
        return numeros


def _cobrar_bono(conexion, renglon, usuario_id: int, monto: float, pagos: list, ahora: datetime) -> int:
    """La venta de Alquiler de PCs de un bono anotado y su vínculo con la sesión,
    como lo deja pcs_repo.asignar_bono: así lo cuentan los reportes de bonos, el
    Detalle del Día y PCSTREAM. El tiempo ya se había sumado al anotarlo."""
    sesion_id = conexion.execute(
        "SELECT sesion_id FROM cuentas_pc WHERE id = ?", (renglon["cuenta_id"],)
    ).fetchone()["sesion_id"]
    venta_id = ventas_repo.registrar_venta_sin_detalle(
        conexion, usuario_id, monto, pagos, dominio.ORIGEN_ALQUILER_PCS, ahora
    )
    if renglon["bono_pcstream_id"] is not None:
        tabla, bono_id, columna = "sesion_pcstream_bonos", renglon["bono_pcstream_id"], "sesion_pcstream_bono_id"
    else:
        tabla, bono_id, columna = "sesion_bonos", renglon["bono_tiempo_id"], "sesion_bono_id"
    cursor = conexion.execute(
        f"INSERT INTO {tabla} (sesion_id, bono_id, minutos, precio, venta_id) VALUES (?, ?, ?, ?, ?)",
        (sesion_id, bono_id, renglon["minutos"], round(monto, 2), venta_id),
    )
    conexion.execute(
        f"UPDATE cuenta_pc_items SET venta_id = ?, {columna} = ? WHERE id = ?",
        (venta_id, cursor.lastrowid, renglon["id"]),
    )
    return venta_id


def _cobrar_tiempo_socio(conexion, renglon, usuario_id: int, monto: float, pagos: list, ahora: datetime) -> int:
    """La venta de Alquiler de PCs del tiempo de socio anotado, y en su historial
    de saldo una CARGA (con esa venta, como en Cargar Saldo) y el CONSUMO que la
    pasó a la sesión, los dos con la hora en que se anotó: el saldo no cambia
    (el tiempo ya estaba en la PC), el Historial de Cargas y Socios y Bonos la
    cuentan como cualquier carga, y desde ahora se le devuelve si se va antes."""
    sesion_id = conexion.execute(
        "SELECT sesion_id FROM cuentas_pc WHERE id = ?", (renglon["cuenta_id"],)
    ).fetchone()["sesion_id"]
    venta_id = ventas_repo.registrar_venta_sin_detalle(
        conexion, usuario_id, monto, pagos, dominio.ORIGEN_ALQUILER_PCS, ahora
    )
    conexion.execute(
        """
        INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id, bono_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (renglon["miembro_id"], dominio.MOVIMIENTO_CARGA, renglon["minutos"],
         datetime.fromisoformat(renglon["fecha"]).isoformat(timespec="seconds"), venta_id, renglon["bono_miembro_id"]),
    )
    conexion.execute(
        """
        INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (renglon["miembro_id"], dominio.MOVIMIENTO_CONSUMO, renglon["minutos"], renglon["fecha"], sesion_id),
    )
    conexion.execute("UPDATE cuenta_pc_items SET venta_id = ? WHERE id = ?", (venta_id, renglon["id"]))
    return venta_id


def quitar_renglon(renglon_id: int, usuario_id: int, motivo: str):
    """
    Solo un Admin: saca de la cuenta un renglón anotado por error (no se borra:
    queda quién, cuándo y por qué). Un artículo vuelve al stock. Un bono (o
    tiempo de socio) le saca a la sesión el tiempo que le había sumado, si sigue
    en curso (sin dejarla por debajo de ahora: a lo sumo la deja en cero).
    """
    usuarios_repo.exigir_admin(usuario_id, "quitar algo de una cuenta")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Escribí por qué se quita.")
    ahora = datetime.now()
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        renglon = conexion.execute(
            """
            SELECT cuenta_pc_items.*, cuentas_pc.estado AS estado_cuenta, cuentas_pc.sesion_id
            FROM cuenta_pc_items JOIN cuentas_pc ON cuentas_pc.id = cuenta_pc_items.cuenta_id
            WHERE cuenta_pc_items.id = ?
            """,
            (renglon_id,),
        ).fetchone()
        if renglon is None or renglon["quitado_fecha"] is not None or renglon["estado_cuenta"] != dominio.CUENTA_ABIERTA:
            raise ValueError("Ese renglón ya no está en una cuenta abierta. Actualizá la pantalla.")
        if renglon["tipo"] == dominio.ITEM_CUENTA_ARTICULO:
            conexion.execute(
                "UPDATE articulos SET stock = stock + ? WHERE codigo = ?",
                (renglon["cantidad"], renglon["articulo_codigo"]),
            )
        else:
            sesion = conexion.execute(
                "SELECT * FROM sesiones_pc WHERE id = ? AND estado = ?", (renglon["sesion_id"], dominio.SESION_ACTIVA)
            ).fetchone()
            if sesion is not None:
                fin = datetime.fromisoformat(sesion["fecha_fin_prevista"])
                nuevo_fin = max(fin - timedelta(minutes=renglon["minutos"]), ahora)
                conexion.execute(
                    "UPDATE sesiones_pc SET fecha_fin_prevista = ? WHERE id = ?",
                    (nuevo_fin.isoformat(timespec="seconds"), sesion["id"]),
                )
        conexion.execute(
            "UPDATE cuenta_pc_items SET quitado_fecha = ?, quitado_por = ?, quitado_motivo = ? WHERE id = ?",
            (ahora.isoformat(timespec="seconds"), usuario_id, motivo, renglon_id),
        )


def dar_por_perdida(cuenta_id: int, usuario_id: int, motivo: str):
    """Solo un Admin: el cliente se fue sin pagar. La cuenta queda PERDIDA con el
    motivo (no se borra) y la PC deja de titilar; lo anotado no entra en la caja
    (nunca se cobró) y el stock queda como estaba (se lo llevó)."""
    usuarios_repo.exigir_admin(usuario_id, "dar una cuenta por perdida")
    motivo = (motivo or "").strip()
    if not motivo:
        raise ValueError("Escribí por qué se da por perdida.")
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        _total_abierto(conexion, cuenta_id)  # que siga abierta
        conexion.execute(
            """
            UPDATE cuentas_pc SET estado = ?, fecha_cierre = ?, usuario_cierre_id = ?, motivo_perdida = ?
            WHERE id = ?
            """,
            (dominio.CUENTA_PERDIDA, datetime.now().isoformat(timespec="seconds"), usuario_id, motivo, cuenta_id),
        )
