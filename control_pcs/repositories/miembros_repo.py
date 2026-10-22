"""
miembros_repo.py
==================
Socios del Cyber con cuenta propia y saldo prepago de tiempo (en
minutos). Se cargan de dos formas — pagando un monto en pesos que se
convierte a minutos según la tarifa que corresponda a ese monto (ver
config_repo.obtener_tramos_tarifa_hora_miembro), o comprando uno de los bonos
del catálogo EXCLUSIVO de socios (bonos_miembro_repo.listar_bonos, no el
de walk-ins de pcs_repo — ver ese módulo para la diferencia) — y se
gastan abriendo una estación con el usuario/clave del socio, sin que el
mostrador decida cuánto tiempo asignarle: un Miembro se loguea solo y
usa TODO lo que tenga disponible en ese momento (ver
abrir_estacion_por_miembro).

Diferencia clave con un bono: un bono se cobra y se consume en el
momento, sin reintegro. El saldo de un socio es una cuenta que persiste
entre visitas — si corta antes de gastarlo todo, lo que no usó se le
devuelve (ver pcs_repo.finalizar_sesion). Por eso cada movimiento de
saldo (carga, consumo, reintegro) queda en el ledger
`movimientos_saldo_miembro`: esto maneja plata real de terceros, así que
tiene que poder auditarse.

Alta rápida y datos en el primer ingreso (pedido del dueño, 2026-10-17: tenía
muchísimas cuentas de su programa anterior para volver a crear). Para dar de
alta un socio alcanzan usuario y contraseña; el DNI (obligatorio), el celular y
el WhatsApp (opcionales) los carga el propio socio la primera vez que entra
desde un Cliente PC, antes de que se le abra la PC (ver
abrir_estacion_por_miembro). Una vez guardado un DNI válido no se le vuelve a
pedir (`tiene_dni`). Un DNI no puede estar en dos cuentas activas.
"""

import re
import sqlite3
from contextlib import contextmanager
from datetime import datetime
import dominio
from database import conexion_db, hash_clave, verificar_clave
from repositories import config_repo, ventas_repo
from control_pcs.repositories import pcs_repo, bonos_miembro_repo, reservas_horario_repo

# El saldo se carga, se devuelve y se pide como mínimo en bloques de 30 minutos.
# Se gasta entero, salvo en una PC reservada: ahí se gasta justo hasta la hora de
# la reserva, así que puede quedar un saldo que no es múltiplo de 30 (decisión del
# dueño: "lo que no usó le queda en el saldo"). Mismo valor que
# reintegros_repo.MINUTOS_POR_FRACCION (ver ahí por qué no se importa).
MINUTOS_POR_FRACCION = 30


class FaltanDatosDelSocio(Exception):
    """
    La levanta abrir_estacion_por_miembro cuando el Cliente PC sabe pedir los
    datos del primer ingreso y el socio todavía no tiene DNI: no se abrió nada
    ni se gastó saldo. El servidor de red se la contesta al Cliente PC como
    "faltan_datos", y el Cliente PC le muestra al socio el cuadro para
    completarlos. No es un ValueError a propósito: no es un error del socio.
    """


# Lo que se acepta escrito entre los números de un DNI o de un teléfono, y se
# saca antes de guardarlo: "30.111.222", "11 5555-4444", "(011) 5555 4444".
_SEPARADORES = re.compile(r"[\s.\-()]")


def normalizar_dni(texto: str) -> str:
    """
    El DNI tal cual se guarda: solo los números, sin puntos ni espacios ("" si
    vino vacío). Levanta ValueError (mensaje listo para mostrarle al socio o al
    operador) si no son 7 u 8 cifras.
    """
    dni = _SEPARADORES.sub("", texto or "")
    if dni and not re.fullmatch(r"\d{7,8}", dni):
        raise ValueError("El DNI tiene que ser solo números, de 7 u 8 cifras.")
    return dni


def tiene_dni(miembro) -> bool:
    """
    ¿Este socio ya tiene un DNI válido cargado? Si no, el Cliente PC se lo pide
    al entrar (ver abrir_estacion_por_miembro) y Miembros lo marca "Falta DNI".
    Mira que el DNI sea válido y no solo que haya algo escrito: un socio cargado
    antes de que se validara (cuando el DNI era obligatorio en el alta) pudo
    quedar con un relleno cualquiera, y a ese también hay que pedírselo.
    """
    try:
        return bool(normalizar_dni(miembro["dni"]))
    except ValueError:
        return False


def normalizar_telefono(texto: str, que: str) -> str:
    """
    Un celular o WhatsApp tal cual se guarda: los números, con el "+" de
    adelante si lo tenía ("" si vino vacío; los dos son opcionales). Levanta
    ValueError si no son de 8 a 15 cifras. `que` es cómo se lo nombra en el
    mensaje ("El celular", "El WhatsApp").
    """
    telefono = _SEPARADORES.sub("", texto or "")
    if telefono and not re.fullmatch(r"\+?\d{8,15}", telefono):
        raise ValueError(f"{que} tiene que ser un número de teléfono (solo números, con la característica).")
    return telefono


def _exigir_dni_libre(conexion, dni: str, miembro_id: int = None, mensaje: str = None):
    """
    Levanta ValueError si `dni` ya está en OTRA cuenta activa: un DNI, una
    cuenta (pedido del dueño). Las cuentas desactivadas no cuentan: no se pueden
    usar, y si la persona vuelve con una cuenta nueva no hay que trabarla. Se
    compara sin puntos ni espacios, por los DNI cargados antes de que se
    guardaran así.
    """
    if not dni:
        return
    otra = conexion.execute(
        """
        SELECT usuario FROM miembros
        WHERE activo = 1 AND id IS NOT ?
          AND REPLACE(REPLACE(REPLACE(dni, '.', ''), ' ', ''), '-', '') = ?
        """,
        (miembro_id, dni),
    ).fetchone()
    if otra is not None:
        raise ValueError(mensaje or f"Ese DNI ya está cargado en el socio '{otra['usuario']}'.")


def _datos_de_miembro(usuario: str, nombre: str, dni: str, telefono: str, email: str = None,
                      whatsapp: str = "") -> dict:
    """Valida los datos de un socio y los devuelve como se guardan. Solo el
    usuario es obligatorio: un nombre vacío queda igual al usuario (así se lo
    ve en la lista y en las PCs), el DNI y los teléfonos se guardan solo con
    los números, y un email vacío queda en None. Los usan crear_miembro y
    modificar_miembro."""
    usuario = (usuario or "").strip()
    if not usuario:
        raise ValueError("El usuario no puede quedar vacío.")
    return {
        "usuario": usuario,
        "nombre": (nombre or "").strip() or usuario,
        "dni": normalizar_dni(dni),
        "telefono": normalizar_telefono(telefono, "El celular"),
        "whatsapp": normalizar_telefono(whatsapp, "El WhatsApp"),
        "email": (email or "").strip() or None,
    }


@contextmanager
def _usuario_de_socio_unico(usuario: str):
    """`miembros.usuario` es UNIQUE (es el login del socio): si ya existe, la
    base tira IntegrityError y acá se convierte en un mensaje para mostrar."""
    try:
        yield
    except sqlite3.IntegrityError:
        raise ValueError(f"Ya existe un socio con el usuario '{usuario}'.")


def crear_miembro(usuario: str, clave: str, nombre: str = "", dni: str = "", telefono: str = "",
                  email: str = None, whatsapp: str = "") -> int:
    """Da de alta un socio (arranca con saldo 0) y devuelve su id. Alcanzan
    usuario y clave: lo demás es opcional (ver _datos_de_miembro) y, si falta el
    DNI, el socio lo completa al entrar por primera vez desde una PC. Levanta
    ValueError si falta el usuario o la clave, si un dato está mal escrito, si
    ya existe otro socio con ese usuario o si el DNI ya es de otra cuenta."""
    datos = _datos_de_miembro(usuario, nombre, dni, telefono, email, whatsapp)
    if not clave:
        raise ValueError("El socio necesita una contraseña para poder loguearse solo.")
    ahora = datetime.now().isoformat(timespec="seconds")
    with _usuario_de_socio_unico(datos["usuario"]):
        with conexion_db() as conexion:
            _exigir_dni_libre(conexion, datos["dni"])
            cursor = conexion.execute(
                """
                INSERT INTO miembros (usuario, clave_hash, nombre, dni, telefono, whatsapp, email, fecha_creacion)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (datos["usuario"], hash_clave(clave), datos["nombre"], datos["dni"],
                 datos["telefono"], datos["whatsapp"], datos["email"], ahora),
            )
            return cursor.lastrowid


def modificar_miembro(miembro_id: int, usuario: str, nombre: str, dni: str, telefono: str,
                       email: str = None, clave: str = None, whatsapp: str = ""):
    """Actualiza los datos de un socio (mismas reglas que crear_miembro). Si
    `clave` viene vacía se conserva la anterior. No toca el saldo: eso solo se
    mueve con cargas, consumos y reintegros (ver el ledger
    movimientos_saldo_miembro)."""
    datos = _datos_de_miembro(usuario, nombre, dni, telefono, email, whatsapp)
    if clave:
        datos["clave_hash"] = hash_clave(clave)
    asignaciones = ", ".join(f"{columna} = ?" for columna in datos)
    with _usuario_de_socio_unico(datos["usuario"]):
        with conexion_db() as conexion:
            _exigir_dni_libre(conexion, datos["dni"], miembro_id)
            conexion.execute(
                f"UPDATE miembros SET {asignaciones} WHERE id = ?", (*datos.values(), miembro_id)
            )


def desactivar_miembro(miembro_id: int):
    """No se borra (queda el ledger de movimientos y el historial de
    sesiones), solo deja de poder loguearse."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE miembros SET activo = 0 WHERE id = ?", (miembro_id,))


def listar_miembros(incluir_inactivos: bool = False, texto_busqueda: str = ""):
    """Los socios en orden alfabético por usuario, sin importar mayúsculas
    (pedido del dueño, 2026-10-20: antes iban por nombre); por defecto solo
    los activos. Con `texto_busqueda`, solo los que lo tienen en el usuario
    (la lupa de Miembros, mismo día), sin importar mayúsculas."""
    condiciones, parametros = [], []
    if not incluir_inactivos:
        condiciones.append("activo = 1")
    texto = texto_busqueda.strip().lower()
    if texto:
        # instr y no LIKE: un "_" o un "%" del usuario se busca tal cual.
        condiciones.append("instr(lower(usuario), ?) > 0")
        parametros.append(texto)
    donde = f" WHERE {' AND '.join(condiciones)}" if condiciones else ""
    with conexion_db() as conexion:
        return conexion.execute(
            f"SELECT * FROM miembros{donde} ORDER BY usuario COLLATE NOCASE", parametros
        ).fetchall()


def obtener_miembro(miembro_id: int):
    """La fila de un socio (activo o no), o None si no existe."""
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM miembros WHERE id = ?", (miembro_id,)).fetchone()


def _buscar_miembro_autenticado(conexion, usuario: str, clave: str):
    """
    Núcleo compartido de autenticar_miembro y abrir_estacion_por_miembro:
    busca al socio por usuario/clave usando una conexión YA ABIERTA. Existe
    aparte de autenticar_miembro (que abre la suya propia) para que
    abrir_estacion_por_miembro pueda autenticar DENTRO de su propia
    transacción con lock -- ver el porqué en su docstring.
    """
    fila = conexion.execute(
        "SELECT * FROM miembros WHERE usuario = ? AND activo = 1", (usuario.strip(),)
    ).fetchone()
    if fila is None or not verificar_clave(clave, fila["clave_hash"]):
        return None
    return fila


def autenticar_miembro(usuario: str, clave: str):
    """
    Devuelve la fila del socio si el usuario/clave coinciden y está
    activo, o None si no. Mismo mecanismo que
    usuarios_repo._validar_credenciales_y_registrar_sesion, sin la parte
    de migrar hash legacy (acá no hay socios viejos que migrar) ni de
    registrar sesión (eso es para turnos de empleadas, no aplica a un
    socio abriendo una PC).
    """
    with conexion_db() as conexion:
        return _buscar_miembro_autenticado(conexion, usuario, clave)


def _sesion_en_curso_del_socio(conexion, miembro_id: int, ahora: datetime):
    """La sesión de PC que el socio está usando ahora (abierta con su saldo y
    con tiempo por delante), con el nombre de la PC en `estacion_nombre`; None
    si no está usando ninguna. Si figura en más de una, también None: no se
    adivina a cuál sumarle el tiempo."""
    filas = conexion.execute(
        """
        SELECT s.*, e.nombre AS estacion_nombre
        FROM sesiones_pc s JOIN estaciones e ON e.id = s.estacion_id
        WHERE s.miembro_id = ? AND s.estado = ?
        """,
        (miembro_id, dominio.SESION_ACTIVA),
    ).fetchall()
    en_curso = [
        fila for fila in filas
        if dominio.segundos_restantes(datetime.fromisoformat(fila["fecha_fin_prevista"]), ahora) > 0
    ]
    return en_curso[0] if len(en_curso) == 1 else None


def _sumar_carga_a_la_sesion(conexion, miembro_id: int, minutos: int, ahora: datetime):
    """
    Si el socio está usando una PC, le pasa los minutos recién cargados a esa
    sesión (pedido del dueño, 2026-10-22: un socio con 20 minutos por delante
    cargó 13 h y la PC siguió contando hasta cero, porque al entrar la sesión
    se lleva el saldo de ESE momento y la carga quedaba en el saldo; tuvo que
    cerrar sesión y volver a entrar, y perdió los minutos sueltos). Es lo mismo
    que hace abrir_estacion_por_miembro al entrar, con el mismo movimiento
    CONSUMO: los reintegros (reintegros_repo) y la reconexión de una PC
    (reconexion_repo) lo cuentan igual que un ingreso.

    Si la PC tiene una reserva por delante, solo hasta su hora y lo demás queda
    en el saldo (reservas_horario_repo.minutos_para_el_socio); si hasta la
    reserva quedaría muy poco, todo queda en el saldo. Devuelve
    {"estacion": nombre de la PC, "minutos": los que se sumaron}, o None si no
    se sumó nada.
    """
    sesion = _sesion_en_curso_del_socio(conexion, miembro_id, ahora)
    if sesion is None:
        return None
    try:
        minutos_a_usar, _corte = reservas_horario_repo.minutos_para_el_socio(
            conexion, sesion["estacion_id"], minutos, ahora
        )
    except ValueError:
        return None
    pcs_repo._abrir_o_extender_sesion(conexion, sesion["estacion_id"], minutos_a_usar, ahora, miembro_id=miembro_id)
    conexion.execute(
        "UPDATE miembros SET saldo_minutos = saldo_minutos - ? WHERE id = ?", (minutos_a_usar, miembro_id)
    )
    # Con microsegundos, por el mismo motivo que en abrir_estacion_por_miembro.
    conexion.execute(
        """
        INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id)
        VALUES (?, ?, ?, ?, ?)
        """,
        (miembro_id, dominio.MOVIMIENTO_CONSUMO, minutos_a_usar, ahora.isoformat(timespec="microseconds"),
         sesion["id"]),
    )
    return {"estacion": sesion["estacion_nombre"], "minutos": minutos_a_usar}


def _registrar_carga(conexion, miembro_id: int, minutos: int, precio: float, pagos: list,
                      usuario_operador_id: int, bono_id: int = None) -> dict:
    """Núcleo común de cargar_saldo_por_monto/cargar_saldo_por_bono: la
    venta se registra vía ventas_repo.registrar_venta_sin_detalle (mismo
    mecanismo que pcs_repo.asignar_bono, por la misma razón: no hay un
    artículo real de por medio), se suma el saldo, y queda el movimiento
    CARGA en el ledger. A diferencia de abrir_estacion_por_miembro
    (autoservicio puro), cargar saldo siempre lo hace el Operador porque
    implica cobrar plata — por eso necesita `usuario_operador_id`, igual
    que cualquier otra venta del sistema. Si el socio está usando una PC, lo
    cargado pasa a esa sesión (_sumar_carga_a_la_sesion).

    Devuelve {"venta_id", "sumado_a_la_sesion"} (lo segundo, lo que devuelve
    _sumar_carga_a_la_sesion).

    `pagos`: lista de {"metodo", "monto"} — ver
    ventas_repo.registrar_venta_sin_detalle."""
    # El lock de escritura de entrada, como abrir_estacion_por_miembro: la sesión
    # que se estira no puede cambiar entre que se la lee y se la estira.
    conexion.execute("BEGIN IMMEDIATE")
    ahora = datetime.now()
    ahora_iso = ahora.isoformat(timespec="seconds")

    venta_id = ventas_repo.registrar_venta_sin_detalle(
        conexion, usuario_operador_id, precio, pagos, dominio.ORIGEN_ALQUILER_PCS, ahora
    )
    conexion.execute(
        "UPDATE miembros SET saldo_minutos = saldo_minutos + ? WHERE id = ?",
        (minutos, miembro_id),
    )
    conexion.execute(
        """
        INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id, bono_id)
        VALUES (?, ?, ?, ?, ?, ?)
        """,
        (miembro_id, dominio.MOVIMIENTO_CARGA, minutos, ahora_iso, venta_id, bono_id),
    )
    return {"venta_id": venta_id,
            "sumado_a_la_sesion": _sumar_carga_a_la_sesion(conexion, miembro_id, minutos, ahora)}


def minutos_por_monto(tramos: list, monto: float):
    """
    (tarifa_hora, minutos) que corresponden a cargar `monto` en pesos: la
    tarifa $/hora del tramo que le toca a ESE monto (ver
    dominio.tarifa_hora_para_monto -- tabla de tramos por monto mínimo, no
    una tarifa única) y los minutos que alcanzan a esa tarifa, redondeados
    siempre hacia ABAJO al bloque de MINUTOS_POR_FRACCION más cercano:
    nunca se regala tiempo de más por un redondeo, y el saldo solo se gasta
    en esos mismos bloques (ver abrir_estacion_por_miembro).

    Es la única cuenta de esta conversión: la usa cargar_saldo_por_monto al
    cobrar y la pantalla de Cargar Saldo para mostrar la vista previa.
    `tramos` viene de config_repo.obtener_tramos_tarifa_hora_miembro.
    """
    tarifa_hora = dominio.tarifa_hora_para_monto(tramos, monto)
    minutos = int((monto / tarifa_hora * 60) // MINUTOS_POR_FRACCION) * MINUTOS_POR_FRACCION
    return tarifa_hora, minutos


def validar_monto_de_carga(tramos: list, monto: float):
    """
    Levanta ValueError (mensaje listo para mostrar) si `monto` no se puede
    cargar: cero, o menos que la carga mínima (dominio.carga_minima_de_saldo).
    La usa cargar_saldo_por_monto y también la pantalla de Cargar Saldo ANTES
    de pedir el medio de pago, para no preguntar cómo paga algo que después
    se va a rechazar.
    """
    if monto <= 0:
        raise ValueError("El monto tiene que ser mayor a 0.")
    minima = dominio.carga_minima_de_saldo(tramos)
    if monto < minima:
        raise ValueError(
            f"La carga mínima es de ${minima:,.0f}.".replace(",", ".")
            + " Se configura en Configuración ADMIN > Tarifa por Hora para Socios."
        )


def cargar_saldo_por_monto(miembro_id: int, monto: float, pagos: list, usuario_operador_id: int) -> dict:
    """
    Convierte un pago en pesos a minutos de saldo (ver minutos_por_monto) y
    se los suma al socio. Levanta ValueError si el monto es cero, no llega
    a la carga mínima (ver validar_monto_de_carga) o no alcanza ni para un
    bloque. Devuelve lo mismo que _registrar_carga.
    """
    tramos = config_repo.obtener_tramos_tarifa_hora_miembro()
    validar_monto_de_carga(tramos, monto)
    tarifa_hora, minutos = minutos_por_monto(tramos, monto)
    if minutos <= 0:
        raise ValueError(
            f"Ese monto no alcanza para {MINUTOS_POR_FRACCION} minutos a la tarifa actual "
            f"(${tarifa_hora:.0f}/hora)."
        )
    with conexion_db() as conexion:
        return _registrar_carga(conexion, miembro_id, minutos, monto, pagos, usuario_operador_id)


def cargar_saldo_por_bono(miembro_id: int, bono_id: int, pagos: list, usuario_operador_id: int) -> dict:
    """Agrega al saldo del socio un bono del catálogo EXCLUSIVO de socios
    (bonos_miembro_repo, no pcs_repo.listar_bonos -- ese es para
    walk-ins) — ya viene en minutos múltiplos de 30 por construcción del
    catálogo. Devuelve lo mismo que _registrar_carga."""
    bono = bonos_miembro_repo.obtener_bono(bono_id)
    if bono is None or not bono["activo"]:
        raise ValueError("Ese bono ya no está disponible.")
    with conexion_db() as conexion:
        return _registrar_carga(conexion, miembro_id, bono["minutos"], bono["precio"], pagos,
                                 usuario_operador_id, bono_id=bono_id)


def anular_carga(venta_id: int, usuario_admin_id: int, motivo: str):
    """
    Anula, desde Consulta de Ventas, una venta que había cargado saldo a
    un socio (ver _registrar_carga) -- y revierte esa carga del saldo
    actual, todo en la MISMA transacción que la anulación en sí (ver
    ventas_repo._anular_venta). Anular solo la venta (ventas_repo.anular_venta)
    le sacaría la plata del cierre/caja a una carga, pero le dejaría los
    minutos intactos al socio, como si el negocio le hubiera regalado ese
    tiempo; por eso Consulta de Ventas usa esta función para las ventas de
    origen ALQUILER_PCS.

    La reversión queda topeada a lo que el socio TENGA en este momento:
    si ya gastó parte o todo el saldo cargado (abriendo una PC, ver
    abrir_estacion_por_miembro) antes de que alguien anule la carga, no
    se le puede sacar más de lo que le queda -- ahí ya es plata/tiempo
    que se usó de verdad, revertir no puede dejarlo en saldo negativo. El
    movimiento que se deja en el ledger es 'ANULACION', nunca un CONSUMO
    ni un REINTEGRO disimulados: son conceptos distintos y mezclarlos
    rompería la trazabilidad que este ledger existe para dar.

    Sirve para CUALQUIER venta, no solo una carga: si la venta no tiene
    ninguna CARGA asociada (un bono de PC walk-in, por ejemplo), se
    comporta exactamente igual que ventas_repo.anular_venta.
    """
    with conexion_db() as conexion:
        ventas_repo._anular_venta(conexion, venta_id, usuario_admin_id, motivo)

        ahora_iso = datetime.now().isoformat(timespec="seconds")
        cargas = conexion.execute(
            "SELECT * FROM movimientos_saldo_miembro WHERE venta_id = ? AND tipo = ?",
            (venta_id, dominio.MOVIMIENTO_CARGA),
        ).fetchall()
        for carga in cargas:
            saldo_actual = conexion.execute(
                "SELECT saldo_minutos FROM miembros WHERE id = ?", (carga["miembro_id"],)
            ).fetchone()["saldo_minutos"]
            a_revertir = min(carga["minutos"], saldo_actual)
            if a_revertir <= 0:
                continue
            conexion.execute(
                "UPDATE miembros SET saldo_minutos = saldo_minutos - ? WHERE id = ?",
                (a_revertir, carga["miembro_id"]),
            )
            conexion.execute(
                """
                INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, venta_id)
                VALUES (?, 'ANULACION', ?, ?, ?)
                """,
                (carga["miembro_id"], a_revertir, ahora_iso, venta_id),
            )


def _guardar_datos_del_primer_ingreso(conexion, miembro, datos_socio: dict):
    """
    Guarda en la cuenta lo que el socio escribió en el cuadro del primer
    ingreso de su PC: el DNI (obligatorio, y que no sea de otra cuenta activa),
    el celular y el WhatsApp (opcionales: si los deja vacíos, se conserva lo que
    hubiera cargado el mostrador). Levanta ValueError con un mensaje para el
    socio; como corre dentro de la transacción de abrir_estacion_por_miembro, un
    error no deja nada guardado.
    """
    dni = normalizar_dni(str(datos_socio.get("dni") or ""))
    if not dni:
        raise ValueError("El DNI es obligatorio.")
    _exigir_dni_libre(
        conexion, dni, miembro["id"],
        mensaje="Ese DNI ya está registrado en otra cuenta. Pasá por el mostrador.",
    )
    celular = normalizar_telefono(str(datos_socio.get("celular") or ""), "El celular")
    whatsapp = normalizar_telefono(str(datos_socio.get("whatsapp") or ""), "El WhatsApp")
    conexion.execute(
        "UPDATE miembros SET dni = ?, telefono = ?, whatsapp = ? WHERE id = ?",
        (dni, celular or miembro["telefono"], whatsapp or miembro["whatsapp"], miembro["id"]),
    )


def abrir_estacion_por_miembro(estacion_id: int, usuario: str, clave: str,
                               pedir_datos: bool = False, datos_socio: dict = None) -> dict:
    """
    El socio se loguea solo (usuario/clave) para abrir una estación con
    TODO su saldo disponible — no es el mostrador quien elige cuánto
    tiempo asignarle, es autoservicio puro. Levanta ValueError si las
    credenciales no coinciden o si no le queda al menos un bloque de 30
    minutos. Devuelve un resumen simple para mostrar en pantalla.

    Datos del primer ingreso: `pedir_datos=True` lo manda el Cliente PC que
    sabe pedírselos al socio. Si el socio todavía no tiene DNI (`tiene_dni`),
    sin `datos_socio` levanta FaltanDatosDelSocio sin abrir nada (el Cliente PC
    le muestra el cuadro), y con `datos_socio` ({"dni", "celular", "whatsapp"})
    los guarda y abre la PC en la MISMA transacción: si el DNI está mal o es de
    otra cuenta, no queda nada guardado ni se gasta saldo. Se pregunta DESPUÉS
    de la clave y del saldo, para no hacerle escribir el DNI a alguien que igual
    no va a poder entrar. Sin `pedir_datos` (un Cliente PC viejo, o "Abrir PC con
    Miembro" del mostrador) entra como siempre: no se traba nadie mientras haya
    PCs sin actualizar, y se le pide la próxima vez en una PC actualizada. A un
    socio que ya tiene DNI no se le pide ni se le cambia nada.

    Autentica y consume el saldo DENTRO de una sola transacción con
    "BEGIN IMMEDIATE" (toma el lock de escritura de entrada, antes de
    leer nada). El servidor de red atiende cada pedido en su propio hilo
    (ver servidor_red.ThreadingHTTPServer): sin el lock, dos POST /login
    simultáneos del MISMO socio (doble clic, reintento de red) se
    autenticaban leyendo el mismo saldo_minutos y lo gastaban los dos --
    un socio con 60 minutos terminaba con 120 asignados entre dos
    sesiones. Con el lock, el segundo pedido espera al primero, lee el
    saldo ya en 0 y se rechaza en vez de duplicarle el tiempo.

    PCSTREAM (la PC de streaming) no se abre con saldo de socio: tiene sus
    propios precios y se cobra solo con sus bonos (pedido del dueño,
    2026-10-17). Se rechaza antes de pedir la clave, con un mensaje que el
    Cliente PC le muestra tal cual al socio.

    Una PC con una reserva por delante (pedido del dueño, 2026-10-20): el socio
    entra solo hasta la hora de la reserva y se le descuenta solo ese tiempo; lo
    demás le queda en el saldo (reservas_horario_repo.minutos_para_el_socio, que
    lo rechaza si quedaría muy poco). "hasta_la_reserva" en lo que devuelve es esa
    hora ("10:00"), o None si usó todo su saldo.
    """
    ahora = datetime.now()
    # Microsegundos, no segundos: esta "fecha" es la que
    # reintegros_repo.contribuciones_de_sesion usa para ordenar cronológicamente
    # los aportes de una sesión (bonos y consumos de saldo mezclados) y
    # saber, al cortarla antes de tiempo, a quién devolverle el tramo sin
    # usar (ver reintegros_repo.reintegros_por_miembro). El aporte de un bono se
    # graba con microsegundos (ventas.fecha); si este consumo quedara
    # truncado a segundos, "10:00:00" ordenaría ANTES que "10:00:00.900000"
    # aunque haya pasado después, y el tramo del socio se atribuiría al
    # bono, que nunca reintegra. Mismo motivo que ventas_repo.confirmar_venta.
    ahora_iso = ahora.isoformat(timespec="microseconds")

    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")

        estacion = conexion.execute(
            "SELECT nombre FROM estaciones WHERE id = ?", (estacion_id,)
        ).fetchone()
        if estacion is not None and dominio.es_pcstream(estacion["nombre"]):
            raise ValueError(
                f"{estacion['nombre']} no se puede usar con saldo de socio: "
                "se paga con sus propios bonos en el mostrador."
            )

        miembro = _buscar_miembro_autenticado(conexion, usuario, clave)
        if miembro is None:
            raise ValueError("Usuario o contraseña incorrectos.")
        if miembro["saldo_minutos"] < MINUTOS_POR_FRACCION:
            raise ValueError(
                f"{miembro['nombre']} no tiene saldo suficiente (le quedan "
                f"{miembro['saldo_minutos']} minutos, hace falta al menos {MINUTOS_POR_FRACCION})."
            )
        # Antes de los datos del primer ingreso: que no escriba el DNI si la PC está reservada.
        minutos_a_usar, corte = reservas_horario_repo.minutos_para_el_socio(
            conexion, estacion_id, miembro["saldo_minutos"], ahora
        )
        if pedir_datos and not tiene_dni(miembro):
            if datos_socio is None:
                raise FaltanDatosDelSocio("Es tu primer ingreso: completá tus datos para entrar.")
            _guardar_datos_del_primer_ingreso(conexion, miembro, datos_socio)

        sesion_id = pcs_repo._abrir_o_extender_sesion(
            conexion, estacion_id, minutos_a_usar, ahora, miembro_id=miembro["id"]
        )
        conexion.execute(
            "UPDATE miembros SET saldo_minutos = saldo_minutos - ? WHERE id = ?", (minutos_a_usar, miembro["id"])
        )
        conexion.execute(
            """
            INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha, sesion_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (miembro["id"], dominio.MOVIMIENTO_CONSUMO, minutos_a_usar, ahora_iso, sesion_id),
        )

    return {"miembro": miembro["nombre"], "minutos_usados": minutos_a_usar, "sesion_id": sesion_id,
            "hasta_la_reserva": f"{corte:%H:%M}" if corte is not None else None}
