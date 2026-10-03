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

IMPORTANTE: estos valores tienen que coincidir con los CHECK del esquema
en `database.py` (`CHECK (rol IN ('ADMIN', 'EMPLEADA'))`, etc.). Si
alguna vez se agrega un valor nuevo, va en los dos lados: acá y en una
migración que actualice el CHECK.
"""


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

# MIXTO nunca se guarda en venta_pagos (por eso no está en METODOS_PAGO
# ni en el CHECK del esquema): es una opción de pantalla para Control de
# PCs (bono, carga de saldo) que dispara el mismo DialogoPago que ya usa
# Ventas para repartir el cobro entre Efectivo y Digital, y termina
# grabando esas dos filas reales — igual que un pago combinado de
# kiosko. Así Caja y Cierre de Turno nunca ven un tercer balde "mixto"
# sin desglosar (ver control_pcs/ui/pcs_window.py y miembros_window.py).
PAGO_MIXTO = "MIXTO"

# Cómo se le muestra cada método a la usuaria.
NOMBRE_METODO_PAGO = {
    PAGO_EFECTIVO: "Efectivo",
    PAGO_DIGITAL: "Digital (Mercado Pago / Transferencia)",
    PAGO_MIXTO: "Mixto (Efectivo + Digital)",
}


def nombre_metodo(metodo: str) -> str:
    """Nombre corto y legible de un método de pago, para tablas y
    resúmenes donde no entra el texto largo del combo."""
    return "Efectivo" if metodo == PAGO_EFECTIVO else "Digital"


# --------------------------------------------------------------------
# Origen de una venta (Kiosko vs. Alquiler de PCs)
# --------------------------------------------------------------------
# Vender productos de kiosko y alquilar PCs (bonos + saldo de Miembros)
# son dos negocios distintos para el dueño, aunque comparten la misma
# caja: "ventas" y "cierres_turno" necesitan saber de cuál vino cada
# peso para que el cierre de turno pueda mostrar el desglose exacto (ver
# ventas_repo.registrar_venta_sin_detalle y turnos_repo._sumar_ventas_por_origen_y_metodo).
# ORIGEN_ALQUILER_PCS describe una categoría de reporte ("Kiosko vs.
# Alquiler de PCs", con las palabras del dueño) y a propósito no
# coincide con el nombre del módulo de código (control_pcs).
ORIGEN_KIOSKO = "KIOSKO"
ORIGEN_ALQUILER_PCS = "ALQUILER_PCS"

ORIGENES_VENTA = (ORIGEN_KIOSKO, ORIGEN_ALQUILER_PCS)

NOMBRE_ORIGEN_VENTA = {
    ORIGEN_KIOSKO: "Kiosko",
    ORIGEN_ALQUILER_PCS: "Alquiler de PCs",
}


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


# --------------------------------------------------------------------
# Bonos de tiempo (reglas compartidas por los dos catálogos)
# --------------------------------------------------------------------
# Hay dos catálogos de bonos -- pcs_repo.bonos_tiempo (walk-ins) y
# bonos_miembro_repo (exclusivo de socios) -- deliberadamente separados
# (distinta tabla, distinto permiso para administrarlos), pero un bono
# es un bono: mismas tres reglas en los dos. Vive acá para no repetirla
# en cada repo (ver CLAUDE.md, regla 2).
def validar_datos_bono(nombre: str, minutos: int, precio: float):
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


def tarifa_hora_para_monto(tramos: list, monto: float) -> float:
    """
    Único lugar donde se decide qué tarifa $/hora le corresponde a un
    monto cargado, según la tabla de tramos (no hace falta que venga
    ordenada). Se usa el tramo con el monto_minimo más alto que no
    supere `monto`; si `monto` es menor que el tramo más bajo, se usa
    igual la tarifa de ese tramo más bajo -- nunca se rechaza una carga
    chica por no entrar en ningún tramo (pedido explícito del dueño).
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
