"""
playstation_repo.py
=====================
La PlayStation 5 del local: UNA sola consola, con el nombre fijo
"PLAYSTATION 5" (dominio.NOMBRE_PLAYSTATION), que se alquila por tiempo con
bonos propios -- el mismo modelo de cobro que las PCs (bonos prearmados con
tiempo y monto fijos, nunca minuto suelto), pero con su catálogo, sus sesiones
y su origen de venta aparte.

Por qué no es "una estación más" de `pcs_repo`: una estación es una PC con su
Cliente PC (bloqueo, reinicio, apagado, IP, renombrar, dar de baja desde
"Gestionar Estaciones"). Nada de eso existe en una consola, y si estuviera en
la misma tabla, cada camino pensado para PCs podría alcanzarla por error. Acá
no hay `estacion_id` en ninguna función: lo que se vende en este módulo SOLO
puede ir a la consola, y lo que `pcs_repo` vende SOLO puede ir a una PC.

Lo que SÍ se reutiliza de las PCs, en vez de copiarlo (regla 2 de CLAUDE.md):
la mecánica del catálogo (`CatalogoDeBonos`, otra tabla), las reglas de un bono
(`dominio.validar_datos_bono`), la cuenta del tiempo (`dominio.segundos_restantes`
y `dominio.fin_al_sumar_minutos`, las mismas que usa `pcs_repo`), la venta
(`ventas_repo.registrar_venta_sin_detalle`, con origen PLAYSTATION) y, en la
pantalla, el cobro (`ui.dialogo_pago.resolver_pagos`).

Quién puede qué (se pregunta con `usuarios_repo.tiene_permiso`, nunca
comparando el rol a mano):
- Crear, modificar y dar de baja los bonos: solo ADMIN (como los demás
  catálogos, ver ui/main_window.ConfiguracionAdminWindow).
- Vender un bono y liberar la consola: ADMIN o quien tenga el permiso
  operativo `permiso_control_pcs` ("Operar PCs y Miembros"), que no deja
  administrar nada.
Estas reglas se hacen cumplir ACÁ y no solo en la pantalla: una pantalla que
se olvide de esconder un botón no puede darle a nadie un poder que no tiene.
Se lee el usuario de la base en cada operación (no se confía en la fila que
quedó guardada al loguearse), así que un permiso quitado o un usuario
desactivado corta el acceso en el acto.

La sesión de la consola NO se da de baja sola al llegar a cero -- a diferencia de
una PC, que se bloquea y se libera -- porque acá el aviso es para una persona:
queda ACTIVA con `tiempo_agotado`, la grilla la hace titilar en rojo y sigue así
hasta que el operador avisa a los clientes y la libera (`finalizar_sesion`) o le
vende otro bono. Como el vencimiento es una fecha absoluta (no un contador),
todo esto se mantiene igual aunque el programa se cierre y se vuelva a abrir.
"""

from datetime import datetime

import dominio
from database import conexion_db
from repositories import usuarios_repo, ventas_repo
from control_pcs.repositories.catalogo_bonos import CatalogoDeBonos

# El permiso operativo que habilita vender bonos y liberar la consola (es el de
# usuarios_repo.PERMISOS_EMPLEADA etiquetado "Operar PCs y Miembros").
PERMISO_OPERAR = "permiso_control_pcs"


# ---------------------------------------------------------------------
# Permisos
# ---------------------------------------------------------------------

def puede_operar(usuario) -> bool:
    """True si `usuario` (la fila de la tabla usuarios, p. ej. la del login)
    puede vender bonos de la PlayStation 5 y liberarla. La pantalla lo usa para
    decidir qué habilitar; las operaciones de abajo lo vuelven a exigir."""
    return usuarios_repo.tiene_permiso(usuario, PERMISO_OPERAR)


def _usuario_habilitado(usuario_id: int):
    """La fila ACTUAL del usuario, o PermissionError si ya no existe o fue
    desactivado (no puede seguir operando con una sesión que quedó abierta)."""
    usuario = usuarios_repo.obtener_usuario(usuario_id)
    if usuario is None or not usuario["activo"]:
        raise PermissionError("Ese usuario ya no está habilitado para operar.")
    return usuario


def _exigir_operador(usuario_id: int):
    if not puede_operar(_usuario_habilitado(usuario_id)):
        raise PermissionError(
            "No tenés permiso para operar la PlayStation 5. "
            "Pedile al Admin el permiso \"Operar PCs y Miembros\"."
        )


def _exigir_admin(usuario_id: int):
    if not dominio.es_admin(_usuario_habilitado(usuario_id)):
        raise PermissionError("Solo un Administrador puede administrar los bonos de la PlayStation 5.")


# ---------------------------------------------------------------------
# Bonos de la PlayStation 5 (catálogo propio, tabla bonos_playstation)
# ---------------------------------------------------------------------

# Mismo mecanismo que bonos_tiempo (PCs) y bonos_miembro (socios), otra tabla.
# Un bono dado de baja no se borra: queda referenciado desde las ventas que ya
# lo usaron (sesion_playstation_bonos). Listarlos y consultarlos lo puede hacer
# cualquiera (la grilla los ofrece); crearlos, cambiarlos o darlos de baja, solo ADMIN.
_catalogo_bonos = CatalogoDeBonos("bonos_playstation")
listar_bonos = _catalogo_bonos.listar
obtener_bono = _catalogo_bonos.obtener


def crear_bono(usuario_id: int, nombre: str, minutos: int, precio: float) -> int:
    """Da de alta un bono de la PlayStation 5 y devuelve su id. Solo ADMIN
    (PermissionError si no); ValueError si el bono no es válido."""
    _exigir_admin(usuario_id)
    return _catalogo_bonos.crear(nombre, minutos, precio)


def modificar_bono(usuario_id: int, bono_id: int, nombre: str, minutos: int, precio: float):
    """Cambia nombre, minutos y precio de un bono. Solo ADMIN."""
    _exigir_admin(usuario_id)
    _catalogo_bonos.modificar(bono_id, nombre, minutos, precio)


def desactivar_bono(usuario_id: int, bono_id: int):
    """Da de baja un bono (deja de ofrecerse; las ventas que ya lo usaron no
    cambian). Solo ADMIN."""
    _exigir_admin(usuario_id)
    _catalogo_bonos.desactivar(bono_id)


class AdministradorDeBonos:
    """
    El catálogo de bonos de la consola ya atado a quién lo administra.

    Las pantallas de alta/edición de bonos (control_pcs/ui/bonos_dialogos.py) se
    escribieron una vez para los tres catálogos y esperan un "repo" con
    `listar_bonos`, `crear_bono`, `modificar_bono` y `desactivar_bono` SIN
    usuario. Acá el usuario es parte de la regla (solo ADMIN), así que este
    objeto tiene esa misma forma pero lleva el `usuario_id` por dentro y se lo
    pasa a cada operación, que lo vuelve a controlar.
    """

    def __init__(self, usuario_id: int):
        self._usuario_id = usuario_id

    def listar_bonos(self, solo_activos: bool = True):
        return listar_bonos(solo_activos)

    def crear_bono(self, nombre: str, minutos: int, precio: float) -> int:
        return crear_bono(self._usuario_id, nombre, minutos, precio)

    def modificar_bono(self, bono_id: int, nombre: str, minutos: int, precio: float):
        modificar_bono(self._usuario_id, bono_id, nombre, minutos, precio)

    def desactivar_bono(self, bono_id: int):
        desactivar_bono(self._usuario_id, bono_id)


# ---------------------------------------------------------------------
# La consola: estado, venta de bonos, liberar
# ---------------------------------------------------------------------

def _sesion_activa(conexion):
    """La sesión en curso de la consola, o None. A lo sumo hay una (lo
    garantiza el índice único idx_sesion_playstation_activa)."""
    return conexion.execute(
        "SELECT * FROM sesiones_playstation WHERE estado = ?", (dominio.SESION_ACTIVA,)
    ).fetchone()


def estado() -> dict:
    """
    Cómo está la consola ahora, para la grilla de Control de PCs. Tiene la
    misma forma que cada elemento de `pcs_repo.estado_estaciones()` en lo que
    importa -- "sesion" y "segundos_restantes" -- más:

    - "dispositivo": dominio.DISPOSITIVO_PLAYSTATION (la grilla distingue por
      esto una fila de una PC).
    - "nombre": el nombre fijo, dominio.NOMBRE_PLAYSTATION.
    - "tiempo_agotado": True si hay una sesión cuyo tiempo llegó a cero y nadie
      la liberó todavía -- es lo que dispara el parpadeo rojo.

    El tiempo restante se calcula al vuelo contra el reloj de ahora (ver
    dominio.segundos_restantes), no se guarda ningún contador.
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        sesion = _sesion_activa(conexion)

    segundos = None
    if sesion is not None:
        segundos = dominio.segundos_restantes(datetime.fromisoformat(sesion["fecha_fin_prevista"]), ahora)

    return {
        "dispositivo": dominio.DISPOSITIVO_PLAYSTATION,
        "nombre": dominio.NOMBRE_PLAYSTATION,
        "sesion": sesion,
        "segundos_restantes": segundos,
        "tiempo_agotado": sesion is not None and segundos == 0,
    }


def vender_bono(usuario_id: int, bono_id: int, pagos: list) -> int:
    """
    Vende un bono de la PlayStation 5 y devuelve el id de la venta. Si la
    consola no tiene sesión, arranca una; si ya tiene una en curso (los clientes
    siguen jugando) le suma los minutos; si el tiempo ya se había agotado y
    nadie la liberó, los minutos nuevos cuentan desde ahora y el aviso rojo se
    apaga solo (ver dominio.fin_al_sumar_minutos).

    `bono_id` se busca SOLO en el catálogo de la consola: el id de un bono de
    PC no sirve acá (si por casualidad coincidiera con uno de la consola, la
    pantalla nunca lo manda: lo toma de la lista de bonos de la consola).
    `pagos` es una lista de {"metodo", "monto"} -- ver
    ui.dialogo_pago.resolver_pagos -- y tiene que cubrir el precio.

    Requiere ADMIN o `permiso_control_pcs` (PermissionError si no). Venta,
    sesión y vínculo con el bono se graban en la misma transacción (regla 8 de
    CLAUDE.md); la venta se registra con origen PLAYSTATION, así Caja, Cierre de
    Turno y Reportes la muestran aparte de Kiosko y de Alquiler de PCs.
    """
    _exigir_operador(usuario_id)
    bono = obtener_bono(bono_id)
    if bono is None or not bono["activo"]:
        raise ValueError("Ese bono de la PlayStation 5 ya no está disponible.")
    if sum(pago["monto"] for pago in pagos) < bono["precio"] - 0.01:
        raise ValueError("Los pagos no cubren el precio del bono.")

    ahora = datetime.now()
    with conexion_db() as conexion:
        sesion = _sesion_activa(conexion)
        if sesion is None:
            fin_previsto = dominio.fin_al_sumar_minutos(None, bono["minutos"], ahora)
            sesion_id = conexion.execute(
                """
                INSERT INTO sesiones_playstation (fecha_inicio, fecha_fin_prevista, estado)
                VALUES (?, ?, ?)
                """,
                (ahora.isoformat(timespec="seconds"), fin_previsto.isoformat(timespec="seconds"),
                 dominio.SESION_ACTIVA),
            ).lastrowid
        else:
            sesion_id = sesion["id"]
            fin_previsto = dominio.fin_al_sumar_minutos(
                datetime.fromisoformat(sesion["fecha_fin_prevista"]), bono["minutos"], ahora
            )
            conexion.execute(
                "UPDATE sesiones_playstation SET fecha_fin_prevista = ? WHERE id = ?",
                (fin_previsto.isoformat(timespec="seconds"), sesion_id),
            )

        venta_id = ventas_repo.registrar_venta_sin_detalle(
            conexion, usuario_id, bono["precio"], pagos, dominio.ORIGEN_PLAYSTATION, ahora
        )
        conexion.execute(
            """
            INSERT INTO sesion_playstation_bonos (sesion_id, bono_id, minutos, precio, venta_id)
            VALUES (?, ?, ?, ?, ?)
            """,
            (sesion_id, bono_id, bono["minutos"], round(bono["precio"], 2), venta_id),
        )
        return venta_id


def finalizar_sesion(usuario_id: int):
    """
    Libera la consola: da de baja la sesión en curso, tenga o no tiempo sin
    usar. Es lo que hace el operador al avisar a los clientes que se acabó el
    tiempo (apaga el parpadeo rojo) y lo que usa para cortar antes de tiempo.
    Como un bono de PC, lo que no se usó NO se reintegra: es un consumible.
    No hace nada si no hay sesión (apretar dos veces no rompe nada).

    Requiere ADMIN o `permiso_control_pcs`, igual que vender.
    """
    _exigir_operador(usuario_id)
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE sesiones_playstation SET estado = ?, fecha_fin_real = ? WHERE estado = ?",
            (dominio.SESION_FINALIZADA, datetime.now().isoformat(timespec="seconds"), dominio.SESION_ACTIVA),
        )


def eventos_recientes(limite: int = 30) -> list:
    """
    Los últimos movimientos de la consola (sesión iniciada, bono cobrado,
    sesión liberada), con la misma forma que los de `pcs_repo.actividad_reciente`
    para que el panel "Actividad reciente" los mezcle con los de las PCs (es
    `actividad_reciente` quien los junta y ordena). Datos crudos: el texto se
    arma en la pantalla.
    """
    nombre = dominio.NOMBRE_PLAYSTATION
    eventos = []
    with conexion_db() as conexion:
        for fila in conexion.execute(
            "SELECT fecha_inicio AS fecha FROM sesiones_playstation ORDER BY fecha_inicio DESC LIMIT ?",
            (limite,),
        ):
            eventos.append({"fecha": fila["fecha"], "tipo": "INICIO", "estacion_nombre": nombre})

        for fila in conexion.execute(
            """
            SELECT fecha_fin_real AS fecha FROM sesiones_playstation
            WHERE fecha_fin_real IS NOT NULL ORDER BY fecha_fin_real DESC LIMIT ?
            """,
            (limite,),
        ):
            eventos.append({"fecha": fila["fecha"], "tipo": "FIN", "estacion_nombre": nombre})

        for fila in conexion.execute(
            """
            SELECT v.fecha AS fecha, b.nombre AS bono_nombre, spb.precio AS precio
            FROM sesion_playstation_bonos spb
            JOIN ventas v ON v.id = spb.venta_id
            JOIN bonos_playstation b ON b.id = spb.bono_id
            ORDER BY v.fecha DESC LIMIT ?
            """,
            (limite,),
        ):
            eventos.append({"fecha": fila["fecha"], "tipo": "BONO", "estacion_nombre": nombre,
                            "bono_nombre": fila["bono_nombre"], "precio": fila["precio"]})
    return eventos
