"""
dominio.py
===========
Los valores fijos del negocio, escritos UNA sola vez.

Roles, estados de una venta, métodos de pago y turnos son textos que
viajan por todo el programa y se guardan tal cual en la base de datos.
Escritos a mano en cada pantalla, un error de tipeo no se nota: la
consulta no falla, simplemente devuelve cero filas — y alguien se entera
recién cuando falta plata en un cierre. Nombrándolos acá, un typo es un
error de Python que salta al instante.

Este módulo NO importa nada del programa a propósito: lo pueden usar
tanto `ui/` como `repositories/` como `database.py` sin romper la
dirección de las capas (ver CLAUDE.md, regla 1).

IMPORTANTE: los CHECK del esquema (`CHECK (rol IN (...))`, etc.) se arman
con las listas de acá (`ROLES`, `ESTADOS_VENTA`, `TURNOS`, `ORIGENES_VENTA`...,
ver `database._valores_sql`), así una base NUEVA nunca queda desfasada. Pero
SQLite no deja cambiar un CHECK ya grabado: si se agrega un valor, una base
que ya existe necesita además una migración que reconstruya esa tabla (como
`_migrar_check_tipo_en_comandos_pc`, que lo hace sola para los comandos).
"""

import re
from datetime import datetime, timedelta


# --------------------------------------------------------------------
# Roles de usuario
# --------------------------------------------------------------------
# ADMIN ve todo el sistema. EMPLEADA ve Ventas y Caja siempre, y el resto
# solo si el Admin le dio el permiso puntual (ver usuarios_repo.tiene_permiso).
ROL_ADMIN = "ADMIN"
ROL_EMPLEADA = "EMPLEADA"

ROLES = (ROL_ADMIN, ROL_EMPLEADA)


def es_admin(usuario) -> bool:
    """
    Único lugar donde se pregunta si un usuario es Administrador. Acepta
    la fila de la base (sqlite3.Row o dict). Usar esto en vez de comparar
    `usuario["rol"] == "ADMIN"` a mano en cada pantalla.
    """
    return usuario is not None and usuario["rol"] == ROL_ADMIN


# --------------------------------------------------------------------
# Estados de una venta
# --------------------------------------------------------------------
# Una venta nunca se borra: si hay que darla de baja, pasa a ANULADA y
# queda el rastro de quién, cuándo y por qué (ver CLAUDE.md, regla 7).
VENTA_CONFIRMADA = "CONFIRMADA"
VENTA_ANULADA = "ANULADA"

ESTADOS_VENTA = (VENTA_CONFIRMADA, VENTA_ANULADA)


# --------------------------------------------------------------------
# Métodos de pago
# --------------------------------------------------------------------
# DIGITAL agrupa Mercado Pago y transferencias: para el cierre de caja
# son lo mismo (plata que no está en el cajón), y separarlos obligaría a
# la empleada a elegir entre dos botones casi idénticos con la cola
# esperando.
PAGO_EFECTIVO = "EFECTIVO"
PAGO_DIGITAL = "DIGITAL"

METODOS_PAGO = (PAGO_EFECTIVO, PAGO_DIGITAL)

# Cómo se le muestra cada método a la usuaria.
NOMBRE_METODO_PAGO = {
    PAGO_EFECTIVO: "Efectivo",
    PAGO_DIGITAL: "Digital (Mercado Pago / Transferencia)",
}


def nombre_metodo(metodo: str) -> str:
    """Nombre corto y legible de un método de pago, para tablas y
    resúmenes donde no entra el texto largo del combo."""
    return "Efectivo" if metodo == PAGO_EFECTIVO else "Digital"


# --------------------------------------------------------------------
# Origen de una venta (Kiosko, Alquiler de PCs, PlayStation 5)
# --------------------------------------------------------------------
# Vender productos de kiosko, alquilar PCs (bonos + saldo de Miembros) y
# alquilar la PlayStation 5 son negocios distintos para el dueño, aunque
# comparten la misma caja: "ventas" y "cierres_turno" necesitan saber de
# cuál vino cada peso para que el cierre de turno pueda mostrar el desglose
# exacto (ver ventas_repo.registrar_venta_sin_detalle y
# turnos_ventas_repo._sumar_ventas_por_origen_y_metodo).
# ORIGEN_ALQUILER_PCS describe una categoría de reporte ("Kiosko vs.
# Alquiler de PCs", con las palabras del dueño) y a propósito no
# coincide con el nombre del módulo de código (control_pcs).
#
# Sumar un origen nuevo NO es solo agregarlo acá: también va en el CHECK de
# "ventas.origen" (database._migrar_check_origen_en_ventas lo reconstruye solo
# a partir de esta lista), en el desglose de Caja/Cierre de Turno
# (turnos_repo._PREFIJO_COLUMNAS_POR_ORIGEN y las columnas de "cierres_turno") y
# en los reportes. Un origen que quede afuera de eso hace desaparecer su plata
# de la caja sin avisar: hay un test que lo atrapa (TestCadaOrigenSumaEnLaCaja).
ORIGEN_KIOSKO = "KIOSKO"
ORIGEN_ALQUILER_PCS = "ALQUILER_PCS"
ORIGEN_PLAYSTATION = "PLAYSTATION"

ORIGENES_VENTA = (ORIGEN_KIOSKO, ORIGEN_ALQUILER_PCS, ORIGEN_PLAYSTATION)

NOMBRE_ORIGEN_VENTA = {
    ORIGEN_KIOSKO: "Kiosko",
    ORIGEN_ALQUILER_PCS: "Alquiler de PCs",
    ORIGEN_PLAYSTATION: "PlayStation 5",
}

# IMPRESIONES es un artículo más del kiosko (se vende por el mismo
# mostrador, con `origen` KIOSKO), pero es el producto Nº 1 y el dueño lo
# quiere ver como renglón propio en Reportes (Totales y Resumen del Día),
# separado del resto de lo que se vende en Kiosko. Se lo reconoce por el
# código del artículo, que es la clave primaria y no se puede cambiar una
# vez creado. Si este artículo no existe (o se creó con otro código), esas
# columnas simplemente muestran $0.
CODIGO_ARTICULO_IMPRESIONES = "1"


# --------------------------------------------------------------------
# Comandos remotos a una PC cliente
# --------------------------------------------------------------------
# Lo que el mostrador le puede pedir a una estación desde el menú contextual
# de Control de PCs. El CHECK de `comandos_pc.tipo` sale de TIPOS_COMANDO_PC y
# una base vieja se reconstruye sola al arrancar
# (database_migraciones._migrar_check_tipo_en_comandos_pc): alcanza con sumar
# el comando a la lista.
COMANDO_REINICIAR = "REINICIAR"
COMANDO_APAGAR = "APAGAR"
COMANDO_MENSAJE = "MENSAJE"
COMANDO_SCREENSHOT = "SCREENSHOT"
COMANDO_CAMBIAR_RED = "CAMBIAR_RED"
COMANDO_VOLUMEN = "VOLUMEN"
TIPOS_COMANDO_PC = (
    COMANDO_REINICIAR, COMANDO_APAGAR, COMANDO_MENSAJE,
    COMANDO_SCREENSHOT, COMANDO_CAMBIAR_RED, COMANDO_VOLUMEN,
)

# En qué está cada comando de la cola (`comandos_pc.estado`): PENDIENTE hasta
# que viaja en la respuesta de `GET /estado` de su PC, ENTREGADO después (ver
# comandos_pc_repo). Un typo acá dejaría a los comandos sin llegar nunca.
ESTADO_COMANDO_PENDIENTE = "PENDIENTE"
ESTADO_COMANDO_ENTREGADO = "ENTREGADO"
ESTADOS_COMANDO_PC = (ESTADO_COMANDO_PENDIENTE, ESTADO_COMANDO_ENTREGADO)


# --------------------------------------------------------------------
# Actualización del Cliente PC desde el Servidor
# --------------------------------------------------------------------
# Cómo va la actualización en cada PC, tal como la cuenta su Cliente PC en cada
# GET /estado (parámetro `act`, ver actualizacion_cliente_repo). Tienen que
# coincidir con las de CLIENTE PC/actualizador.py; cualquier otro valor se guarda
# como "nada pendiente". Vacío también es "nada pendiente".
ACTUALIZACION_BAJANDO = "bajando"
ACTUALIZACION_DESCARGADA = "descargada"
ACTUALIZACION_ERROR = "error"
ACTUALIZACION_FALLO = "fallo"
ESTADOS_ACTUALIZACION_CLIENTE = (
    ACTUALIZACION_BAJANDO, ACTUALIZACION_DESCARGADA, ACTUALIZACION_ERROR, ACTUALIZACION_FALLO,
)


# --------------------------------------------------------------------
# Accesos de admin en las PCs cliente
# --------------------------------------------------------------------
# Lo que el Cliente PC le avisa al servidor cuando alguien entra a su panel
# admin (la "A" chica de la pantalla de bloqueo) -- ver
# control_pcs/repositories/accesos_admin_pc_repo.py. Los tres primeros los
# manda el Cliente PC (son el "protocolo" de POST /evento_admin, tienen que
# coincidir con CLIENTE PC/red_kiosko.py); CLIENTE_REANUDADO no viaja por la
# red: lo anota el servidor solo, cuando una PC que había quedado sin
# Cliente PC vuelve a preguntar su estado.
EVENTO_ADMIN_ACCESO = "ACCESO"
EVENTO_ADMIN_CIERRE_CLIENTE = "CIERRE_CLIENTE"
EVENTO_ADMIN_RECONFIGURAR = "RECONFIGURAR"
EVENTO_ADMIN_CLIENTE_REANUDADO = "CLIENTE_REANUDADO"

EVENTOS_ADMIN_REPORTADOS_POR_CLIENTE = (
    EVENTO_ADMIN_ACCESO, EVENTO_ADMIN_CIERRE_CLIENTE, EVENTO_ADMIN_RECONFIGURAR,
)
EVENTOS_ADMIN_PC = EVENTOS_ADMIN_REPORTADOS_POR_CLIENTE + (EVENTO_ADMIN_CLIENTE_REANUDADO,)
# Los que dejan a la PC SIN Cliente PC corriendo, o sea sin bloqueo: la PC
# queda usable por cualquiera hasta que el Cliente PC vuelve a arrancar.
EVENTOS_ADMIN_QUE_DEJAN_PC_SIN_CLIENTE = (EVENTO_ADMIN_CIERRE_CLIENTE, EVENTO_ADMIN_RECONFIGURAR)

NOMBRE_EVENTO_ADMIN_PC = {
    EVENTO_ADMIN_ACCESO: "Entró al panel admin",
    EVENTO_ADMIN_CIERRE_CLIENTE: "Cerró el Cliente PC (la PC quedó SIN bloqueo)",
    EVENTO_ADMIN_RECONFIGURAR: "Abrió la reconfiguración (el Cliente PC se cerró)",
    EVENTO_ADMIN_CLIENTE_REANUDADO: "El Cliente PC volvió a arrancar",
}


def pagos_netos_de_vuelto(pagos: list, vuelto: float) -> list:
    """
    Descuenta el vuelto de los pagos en Efectivo antes de que se graben en
    venta_pagos: lo que queda en la caja de una venta es el total, nunca lo
    que la clienta puso arriba del mostrador. Sin esto, una venta de
    $1.000 pagada con un billete de $2.000 sumaba $2.000 a caja aunque se
    hayan devuelto $1.000 de vuelto -- inflaba Caja y Cierre de Turno en
    exactamente el vuelto de cada venta con cambio.

    No modifica `pagos`: devuelve una lista nueva, para que quien la llama
    (ui/dialogo_pago.DialogoPago) pueda seguir usando el vuelto calculado
    para avisarle a la empleada cuánto entregar, sin que se le mezcle con
    lo que se termina grabando.

    El recorte se hace de atrás para adelante (no importa cuál pago en
    Efectivo puntual se recorte, solo que la suma final quede igual al
    total); un pago que queda en $0 tras el recorte se descarta -- por
    ejemplo, uno que era exactamente el vuelto que se llevó puesto.
    """
    pagos = [dict(pago) for pago in pagos]
    restante = round(vuelto, 2)
    for pago in reversed(pagos):
        if restante <= 0:
            break
        if pago["metodo"] != PAGO_EFECTIVO:
            continue
        recorte = min(pago["monto"], restante)
        pago["monto"] = round(pago["monto"] - recorte, 2)
        restante = round(restante - recorte, 2)
    return [pago for pago in pagos if pago["monto"] > 0.001]


def lo_que_falta_para(total: float, monto: float) -> float:
    """En el cobro, lo que va en el OTRO medio cuando se escribe `monto` en uno
    (Efectivo <-> Digital): lo que falta para el total, nunca negativo."""
    return round(max(0.0, total - monto), 2)


def cuenta_del_cobro(total: float, efectivo: float, digital: float, paga_con: float = 0.0) -> dict:
    """
    La cuenta del cuadro de cobro (ui/dialogo_pago.py; pedido del dueño,
    2026-10-18: Efectivo y Digital siempre a la vista, el reparto se completa
    solo y el vuelto va aparte).

    - `digital`: lo que se cobra por medio digital (de 0 al total).
    - `efectivo`: lo escrito en Efectivo. Lo que no se cobra en digital es la
      parte en efectivo; si se escribió MÁS, es el billete con que pagan (como
      se hacía siempre: "escribí con cuánto pagan").
    - `paga_con`: el billete que da el cliente, escrito aparte (0 = no se
      escribió). Sirve para dar vuelto sin tocar lo digital: $1.500 = $1.000
      efectivo + $500 digital, y paga los $1.000 con uno de $2.000.

    Devuelve {"parte_efectivo", "digital", "entrega" (el efectivo que da el
    cliente), "vuelto", "falta" (efectivo que todavía no entregó; con algo
    acá no se puede cobrar) y "pagos"}. "pagos" ya es lo que queda en la caja
    (neto de vuelto, como pagos_netos_de_vuelto): una o dos filas de
    PAGO_EFECTIVO/PAGO_DIGITAL, listas para grabar.
    """
    total = round(total, 2)
    digital = round(min(max(digital, 0.0), total), 2)
    parte_efectivo = round(total - digital, 2)
    entrega = round(paga_con if paga_con > 0 else max(efectivo, 0.0), 2)
    if parte_efectivo <= 0:
        entrega = 0.0  # todo digital: no entrega billetes, así que no hay vuelto
    falta = round(max(0.0, parte_efectivo - entrega), 2)
    vuelto = round(entrega - parte_efectivo, 2) if not falta else 0.0
    pagos = []
    if parte_efectivo > 0.001:
        pagos.append({"metodo": PAGO_EFECTIVO, "monto": parte_efectivo})
    if digital > 0.001:
        pagos.append({"metodo": PAGO_DIGITAL, "monto": digital})
    return {
        "parte_efectivo": parte_efectivo, "digital": digital, "entrega": entrega,
        "vuelto": max(vuelto, 0.0), "falta": falta, "pagos": pagos,
    }


# --------------------------------------------------------------------
# Dispositivos que se alquilan por tiempo (PCs y PlayStation 5)
# --------------------------------------------------------------------
# El local alquila tiempo de dos tipos de equipo: las PCs (muchas, cada una
# una fila de "estaciones") y UNA PlayStation 5. Cada una tiene su catálogo
# de bonos y sus sesiones, y nunca se mezclan: un bono de PC no se le puede
# vender a la consola ni al revés. En la grilla de Control de PCs, cada fila
# trae su tipo en `item["dispositivo"]`.
DISPOSITIVO_PC = "PC"
DISPOSITIVO_PLAYSTATION = "PLAYSTATION"

# La consola es una sola y su nombre no se edita (a diferencia de una PC, que
# es una fila de "estaciones" que el Admin renombra o da de baja).
NOMBRE_PLAYSTATION = "PLAYSTATION 5"

# La PC de streaming SÍ es una PC (una fila de "estaciones", con su Cliente PC y
# su bloqueo), pero se cobra con su propio catálogo de bonos (ver
# pcstream_repo), no la pueden abrir los socios y no entra en "Intercambiar de
# máquina". Se la reconoce solo por el nombre (pedido del dueño, 2026-10-17):
# si el Admin la renombra a otra cosa, vuelve a ser una PC común.
NOMBRE_PCSTREAM = "PCSTREAM"


def es_pcstream(nombre_estacion: str) -> bool:
    """
    Único lugar donde se decide si una estación es la PC de streaming. Compara
    sin espacios, guiones ni mayúsculas: "PCSTREAM", "PC STREAM" y "Pc-Stream"
    son la misma PC (escrita a mano en "Gestionar Estaciones", un espacio de más
    no puede cambiarle los precios).
    """
    return re.sub(r"[\s_-]", "", nombre_estacion or "").upper() == NOMBRE_PCSTREAM

# Estado de una sesión de tiempo. Tienen que coincidir con el CHECK de
# "sesiones_playstation.estado" en database.py (las sesiones de PC todavía los
# escriben a mano, ver CLAUDE.md "Estado").
SESION_ACTIVA = "ACTIVA"
SESION_FINALIZADA = "FINALIZADA"

# Tipos del historial de saldo de socios. Los usa también el CHECK del esquema.
MOVIMIENTO_CARGA = "CARGA"
MOVIMIENTO_CONSUMO = "CONSUMO"
MOVIMIENTO_REINTEGRO = "REINTEGRO"
MOVIMIENTO_ANULACION = "ANULACION"
TIPOS_MOVIMIENTO_SALDO = (
    MOVIMIENTO_CARGA, MOVIMIENTO_CONSUMO, MOVIMIENTO_REINTEGRO, MOVIMIENTO_ANULACION,
)


def segundos_restantes(fin_previsto: datetime, ahora: datetime) -> int:
    """
    Único lugar donde se calcula cuánto le queda a una sesión de tiempo (PC
    o PlayStation 5): los segundos que faltan hasta `fin_previsto`, nunca
    negativos (0 = el tiempo se acabó). Es una cuenta contra el reloj de AHORA,
    no un contador guardado: por eso sigue siendo correcta aunque el programa
    se cierre y se vuelva a abrir.
    """
    return max(0, int((fin_previsto - ahora).total_seconds()))


def fin_al_sumar_minutos(fin_actual, minutos: int, ahora: datetime) -> datetime:
    """
    Único lugar donde se decide cuándo vence una sesión de tiempo al venderle
    `minutos` más (PC o PlayStation 5). `fin_actual` es el vencimiento que ya
    tenía, o None si todavía no hay sesión.

    Si la sesión sigue en curso, los minutos se suman a SU vencimiento (el
    cliente sigue jugando). Si no hay sesión, o ya venció y nadie la dio de
    baja todavía, se cuentan desde ahora: si no, se perderían los minutos
    entre que se agotó el tiempo anterior y que se vendió el siguiente.
    """
    base = ahora if fin_actual is None else max(fin_actual, ahora)
    return base + timedelta(minutes=minutos)


# --------------------------------------------------------------------
# Bonos de tiempo (reglas compartidas por los cuatro catálogos)
# --------------------------------------------------------------------
# Hay cuatro catálogos de bonos -- pcs_repo.bonos_tiempo (walk-ins),
# bonos_miembro_repo (exclusivo de socios), playstation_repo.bonos_playstation
# (exclusivo de la consola) y pcstream_repo.bonos_pcstream (exclusivo de la PC
# de streaming) -- deliberadamente separados (distinta tabla, distinto permiso
# para administrarlos), pero un bono es un bono: mismas tres reglas en los
# cuatro. Vive acá para no repetirla en cada repo (ver CLAUDE.md, regla 2).
def validar_datos_bono(nombre: str, minutos: int, precio: float):
    """Levanta ValueError (mensaje listo para mostrar) si el bono no es válido."""
    if not nombre.strip():
        raise ValueError("El nombre del bono no puede quedar vacío.")
    if minutos <= 0:
        raise ValueError("Los minutos del bono tienen que ser mayores a 0.")
    if precio <= 0:
        raise ValueError("El precio del bono tiene que ser mayor a 0.")


# --------------------------------------------------------------------
# Tarifa por hora de Socios (tramos por monto cargado)
# --------------------------------------------------------------------
# Hasta 2026-09-30 había una sola tarifa $/hora para convertir un monto
# libre en minutos (config_repo.obtener_tarifa_hora_miembro). El dueño
# pidió poder ofrecer tarifas distintas según cuánta plata carga el
# socio de una vez -- sin asumir que cargar más siempre sale más barato:
# cada tramo (a partir de qué monto mínimo rige, y a qué $/hora) lo
# define el dueño a mano, en cualquier orden de precios.
def validar_tramos_tarifa_hora_miembro(tramos: list):
    """Levanta ValueError (mensaje listo para mostrar) si la tabla de
    tramos está vacía o tiene un monto/tarifa inválido o un monto mínimo
    repetido."""
    if not tramos:
        raise ValueError("Tiene que haber al menos un tramo de tarifa.")
    montos_vistos = set()
    for tramo in tramos:
        if tramo["monto_minimo"] < 0:
            raise ValueError("El monto mínimo de un tramo no puede ser negativo.")
        if tramo["tarifa_hora"] <= 0:
            raise ValueError("La tarifa por hora de un tramo tiene que ser mayor a 0.")
        if tramo["monto_minimo"] in montos_vistos:
            raise ValueError("No puede haber dos tramos con el mismo monto mínimo.")
        montos_vistos.add(tramo["monto_minimo"])


def carga_minima_de_saldo(tramos: list) -> float:
    """
    Único lugar donde se decide cuánto es lo mínimo que puede cargar un
    socio con un monto libre: el monto_minimo del tramo más bajo (pedido del
    dueño, 2026-10-17: con un único tramo "desde $13.000 a $1.000/h" no se
    tiene que poder cargar $2.000). Un tramo "desde $0" deja cargar cualquier
    monto. Hasta ese día un monto menor se aceptaba igual con la tarifa del
    tramo más bajo. Lo hace cumplir miembros_repo.cargar_saldo_por_monto.
    """
    return min(tramo["monto_minimo"] for tramo in tramos)


def tarifa_hora_para_monto(tramos: list, monto: float) -> float:
    """
    Único lugar donde se decide qué tarifa $/hora le corresponde a un
    monto cargado, según la tabla de tramos (no hace falta que venga
    ordenada). Se usa el tramo con el monto_minimo más alto que no
    supere `monto`. Un monto menor que el tramo más bajo devuelve la
    tarifa de ese tramo (para la vista previa mientras se tipea), pero
    esa carga no se acepta: ver carga_minima_de_saldo.
    """
    tramos_ordenados = sorted(tramos, key=lambda tramo: tramo["monto_minimo"])
    tarifa = tramos_ordenados[0]["tarifa_hora"]
    for tramo in tramos_ordenados:
        if tramo["monto_minimo"] > monto:
            break
        tarifa = tramo["tarifa_hora"]
    return tarifa


# --------------------------------------------------------------------
# Turnos
# --------------------------------------------------------------------
# El local abre las 24 hs. De lunes a sábado son 3 turnos de 8 hs; los
# domingos son 2 de 12 hs y NO existe el turno TARDE (ver
# turnos.calcular_turno, que es donde se decide a qué turno pertenece
# una hora concreta, y turnos.turnos_del_dia para saber qué turnos
# existen en un día dado).
TURNO_MANANA = "MAÑANA"
TURNO_TARDE = "TARDE"
TURNO_NOCHE = "NOCHE"

TURNOS = (TURNO_MANANA, TURNO_TARDE, TURNO_NOCHE)
TURNOS_DOMINGO = (TURNO_MANANA, TURNO_NOCHE)
