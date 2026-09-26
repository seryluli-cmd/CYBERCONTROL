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
