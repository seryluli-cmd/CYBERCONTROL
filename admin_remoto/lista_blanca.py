"""
lista_blanca.py
================
Las ÚNICAS funciones de los repos que se pueden pedir desde otra PC. Cualquier
otra cosa que llegue al mostrador se rechaza, aunque venga con la clave del
Administrador: nada de "cualquier cosa por la red".

Son las que usan las pantallas de administración (pedido del dueño,
2026-10-18: "hago las modificaciones que quiera hacer, o miro reportes"):
Administrar Kiosko entero (Artículos, Compras, Consulta de Ventas con anular,
Reportes, Control de Cierres con la carga del sobre, Usuarios), Configuración
ADMIN (estaciones, los cuatro catálogos de bonos, tarifa de socios, trámites,
accesos de admin, fondo y filtro de palabras de las PCs) y Caja para mirar.

Lo que NO está, a propósito, y sigue solo en el mostrador: vender y cobrar
(Ventas, Trámites, bonos de PCs, carga de saldo), abrir/cerrar cajas y turnos,
la grilla de PCs y Actualizar el Cliente PC.

`ACTOR` dice, para cada función que recibe "quién lo hace", cuál es ese
parámetro: el mostrador lo completa SIEMPRE con el Administrador que entró, sin
importar lo que mande la otra PC (una anulación queda a nombre de quien la hizo).
No confundir con un parámetro que nombra a OTRO usuario (ventas_de_operador,
modificar_usuario): esos viajan tal cual.

Si una pantalla de administración empieza a usar una función nueva de un repo,
hay que sumarla acá: tests/test_admin_remoto.py revisa las pantallas y avisa.
"""

import functools
import hashlib
import inspect

from repositories import (
    articulos_repo, compras_repo, config_repo, detalle_dia_repo, relevo_repo, reportes_repo, tramites_repo,
    turnos_repo, usuarios_repo, ventas_repo,
)
from control_pcs.repositories import (
    accesos_admin_pc_repo, bonos_miembro_repo, clientes_repo, filtro_palabras_repo, fondo_repo, miembros_repo,
    pcs_repo, pcstream_repo, playstation_repo, socios_bonos_repo,
)

# Sube si cambia CÓMO se hablan las dos copias (no la lista): las dos tienen que
# hablar igual. Entra en la huella.
VERSION_DEL_PROTOCOLO = 1

_MODULOS = {
    "articulos_repo": articulos_repo,
    "compras_repo": compras_repo,
    "config_repo": config_repo,
    "detalle_dia_repo": detalle_dia_repo,
    "relevo_repo": relevo_repo,
    "reportes_repo": reportes_repo,
    "tramites_repo": tramites_repo,
    "turnos_repo": turnos_repo,
    "usuarios_repo": usuarios_repo,
    "ventas_repo": ventas_repo,
    "accesos_admin_pc_repo": accesos_admin_pc_repo,
    "bonos_miembro_repo": bonos_miembro_repo,
    "clientes_repo": clientes_repo,
    "filtro_palabras_repo": filtro_palabras_repo,
    "fondo_repo": fondo_repo,
    "miembros_repo": miembros_repo,
    "pcs_repo": pcs_repo,
    "pcstream_repo": pcstream_repo,
    "playstation_repo": playstation_repo,
    "socios_bonos_repo": socios_bonos_repo,
}

_CATALOGO_DE_BONOS = ("listar_bonos", "crear_bono", "modificar_bono", "desactivar_bono")

FUNCIONES = {
    # Administrar Kiosko > Artículos (y la búsqueda F5/F6/F7 de Compras), con
    # ORDENAR Stock
    "articulos_repo": (
        "listar_articulos", "buscar_por_codigo", "buscar_por_descripcion", "buscar_por_marca",
        "crear_articulo", "modificar_articulo", "borrar_articulo", "obtener_movimientos",
        "listar_marcas", "listar_rubros", "crear_rubro", "renombrar_rubro", "borrar_rubro",
        "listar_marcas_con_cantidad", "buscar_marca_por_nombre",
        "crear_marca", "renombrar_marca", "juntar_marcas", "borrar_marca",
        "comprobar_clave_para_ordenar_stock", "ajustar_stock", "cambiar_codigo",
    ),
    # Compras
    "compras_repo": ("proximo_numero_compra", "registrar_compra"),
    # Consulta de Ventas / Anular (y el detalle de una venta)
    "ventas_repo": ("listar_ventas_recientes", "buscar_venta", "anular_venta"),
    "miembros_repo": ("anular_carga",),
    "tramites_repo": ("tramite_de_venta", "listar_tramites", "crear_tramite", "modificar_tramite", "desactivar_tramite"),
    # Reportes
    "reportes_repo": (
        "resumen_ventas", "ranking_ventas", "resumen_por_origen", "resumen_por_turno",
        "resumen_por_operador", "ventas_de_operador",
    ),
    # Reportes > Resumen del Día (con el detalle venta por venta), Control de
    # Cierres y Caja (solo mirar)
    "detalle_dia_repo": ("detalle_del_dia",),
    "turnos_repo": (
        "resumen_del_dia", "listar_cierres", "detalle_cierre", "turnos_faltantes", "verificar_cierre",
        "resumen_turno_actual",
    ),
    # El número de caja de la barra de arriba
    "relevo_repo": ("estado_de_la_caja",),
    # Usuarios (y "Clave": cambiar la propia)
    "usuarios_repo": (
        "listar_usuarios", "obtener_usuario", "crear_usuario", "modificar_usuario", "desactivar_usuario",
        "borrar_usuario", "cambiar_clave", "listar_logins",
    ),
    "config_repo": (
        "obtener_fondo_cambio", "actualizar_fondo_cambio",
        "obtener_tramos_tarifa_hora_miembro", "guardar_tramos_tarifa_hora_miembro",
    ),
    # Configuración ADMIN > Gestionar Estaciones (con fondo y filtro de las PCs)
    "pcs_repo": (
        "listar_estaciones", "ips_asentadas_repetidas", "crear_estacion", "renombrar_estacion",
        "desactivar_estacion", "borrar_ip_asentada", "estado_estaciones",
    ) + _CATALOGO_DE_BONOS,
    "clientes_repo": ("establecer_clave_admin_pcs",),
    "fondo_repo": ("obtener", "guardar_jpeg", "quitar"),
    "filtro_palabras_repo": ("obtener", "guardar", "listar_recientes"),
    "accesos_admin_pc_repo": ("listar_eventos",),
    # Los catálogos de bonos (y Reportes > PCSTREAM)
    "pcstream_repo": ("uso_por_dia",) + _CATALOGO_DE_BONOS,
    # Reportes > PCs: Socios y Bonos
    "socios_bonos_repo": ("comparar",),
    "playstation_repo": _CATALOGO_DE_BONOS,
    "bonos_miembro_repo": _CATALOGO_DE_BONOS,
}

# (repo, función) -> el parámetro que dice quién lo hace (ver el comentario del módulo).
ACTOR = {
    ("articulos_repo", "comprobar_clave_para_ordenar_stock"): "usuario_id",
    ("articulos_repo", "ajustar_stock"): "usuario_id",
    ("articulos_repo", "cambiar_codigo"): "usuario_id",
    ("articulos_repo", "crear_marca"): "usuario_id",
    ("articulos_repo", "renombrar_marca"): "usuario_id",
    ("articulos_repo", "juntar_marcas"): "usuario_id",
    ("articulos_repo", "borrar_marca"): "usuario_id",
    ("compras_repo", "registrar_compra"): "usuario_id",
    ("ventas_repo", "anular_venta"): "usuario_admin_id",
    ("miembros_repo", "anular_carga"): "usuario_admin_id",
    ("turnos_repo", "verificar_cierre"): "usuario_admin_id",
    # Cambiar la clave PROPIA (a otra persona se la cambia modificar_usuario).
    ("usuarios_repo", "cambiar_clave"): "usuario_id",
    ("playstation_repo", "crear_bono"): "usuario_id",
    ("playstation_repo", "modificar_bono"): "usuario_id",
    ("playstation_repo", "desactivar_bono"): "usuario_id",
}


def modulo(nombre: str):
    """El módulo de un repo de la lista, por su nombre corto ("articulos_repo")."""
    return _MODULOS[nombre]


def nombres_de_modulos():
    return list(_MODULOS)


def permitida(nombre_modulo: str, nombre_funcion: str) -> bool:
    return nombre_funcion in FUNCIONES.get(nombre_modulo, ())


def funcion(nombre_modulo: str, nombre_funcion: str):
    """La función real del repo (solo si está en la lista; si no, KeyError)."""
    if not permitida(nombre_modulo, nombre_funcion):
        raise KeyError(f"{nombre_modulo}.{nombre_funcion}")
    return getattr(_MODULOS[nombre_modulo], nombre_funcion)


def huella(obtener_funcion=None) -> str:
    """
    Una huella de lo que las dos copias tienen que tener igual: la lista, qué
    parámetros recibe cada función y quién es el actor. Si el .exe del mostrador
    y el de la otra PC no son el mismo, las huellas no coinciden y no se entra
    (una función que cambió de parámetros recibiría datos corridos).

    `obtener_funcion` es para la copia remota, que ya reemplazó los repos por
    sus representantes: le pasa las funciones originales que guardó. Sin él,
    la cuenta se hace una sola vez (el mostrador la usa en cada ingreso).
    """
    if obtener_funcion is None:
        return _huella_de_los_repos()
    return _calcular_huella(obtener_funcion)


@functools.lru_cache(maxsize=1)
def _huella_de_los_repos() -> str:
    return _calcular_huella(funcion)


def _calcular_huella(obtener_funcion) -> str:
    renglones = [f"protocolo {VERSION_DEL_PROTOCOLO}"]
    for nombre_modulo in sorted(FUNCIONES):
        for nombre_funcion in sorted(FUNCIONES[nombre_modulo]):
            firma = inspect.signature(obtener_funcion(nombre_modulo, nombre_funcion))
            actor = ACTOR.get((nombre_modulo, nombre_funcion), "")
            renglones.append(f"{nombre_modulo}.{nombre_funcion}{firma} actor={actor}")
    return hashlib.sha256("\n".join(renglones).encode("utf-8")).hexdigest()
