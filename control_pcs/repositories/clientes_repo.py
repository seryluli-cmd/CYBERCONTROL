"""
clientes_repo.py
================
Las dos claves compartidas por todas las PC clientes (carpeta hermana
"CLIENTE PC"):

- La clave de CONEXIÓN: la que usa el software cliente para autenticarse
  contra `servidor_red.py` (ver `red_kiosko._cabeceras_cliente`). Es FIJA y
  permanente (pedido del dueño, 2026-10-14): ya no se genera, no se renueva
  y no se guarda en la base. Este repositorio es público, así que acá no está
  la clave sino su huella SHA-256 (`HUELLA_CLAVE_CLIENTES`): alcanza para
  reconocerla y no sirve para conectarse. La clave en sí vive en
  `CLIENTE PC/configuracion.py` (repo privado). `es_clave_de_clientes()` es
  el único lugar que la compara.
- 'clave_admin_pcs' (tabla `configuracion`, mismo patrón que `config_repo.py`):
  la contraseña de administrador que destraba el panel admin en la pantalla
  de bloqueo de cada PC cliente (ver el ícono "A" en `cliente_pc.py`). A
  diferencia de la anterior, la ELIGE el dueño (no se genera al azar, tiene
  que poder recordarla) con `establecer_clave_admin_pcs()`. Cada PC cliente
  la guarda en un archivo local propio y la mantiene al día sola
  preguntándosela al Servidor en cada `GET /estado` (viaja adentro de esa
  respuesta, mismo criterio que los comandos remotos) -- así cambiarla
  implica un solo clic acá, no ir PC por PC.
"""

import hashlib
import hmac

from database import conexion_db

# SHA-256 (hexadecimal) de la clave de conexión de los Clientes PC. Alcanza una
# huella simple, sin sal ni función lenta, porque la clave NO es una contraseña
# elegida por una persona sino un valor al azar de 256 bits (43 caracteres, de
# los que generaba `secrets.token_urlsafe(32)`): no hay diccionario que probar
# ni forma de volver de la huella a la clave. Publicarla no regala nada (la
# clave nunca estuvo en este repo). Para cambiar la clave, que es una decisión
# de fondo del dueño: poner la nueva en
# `CLIENTE PC/configuracion.py`, recalcular esta huella con `huella_de_clave()`
# y reinstalar el .exe en TODAS las PCs (la vieja deja de servir en el acto).
HUELLA_CLAVE_CLIENTES = "844ae2955fa6791a1ac4b836aca99b27247d72702b8dbea2e8829735fd01cfd8"


def huella_de_clave(clave: str) -> str:
    """La huella SHA-256 (hexadecimal) de `clave`."""
    return hashlib.sha256(clave.encode("utf-8")).hexdigest()


def es_clave_de_clientes(clave_recibida: str) -> bool:
    """¿Es `clave_recibida` la clave de conexión de los Clientes PC? Compara
    huellas (no la clave) y en tiempo constante, así una clave equivocada no
    deja pistas de cuánto se parecía a la verdadera."""
    return hmac.compare_digest(huella_de_clave(clave_recibida), HUELLA_CLAVE_CLIENTES)


def obtener_clave_admin_pcs() -> str:
    """Cadena vacía si todavía no se puso ninguna contraseña admin (estado
    inicial): con eso, el panel admin de cualquier PC cliente rechaza
    cualquier intento -- nunca hay una contraseña por defecto dando vueltas."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = 'clave_admin_pcs'"
        ).fetchone()
        return fila["valor"] if fila else ""


def establecer_clave_admin_pcs(nueva_clave: str):
    """Guarda la contraseña que el dueño eligió a mano (se valida en la
    pantalla). Se propaga sola a cada PC cliente en su próximo `GET /estado`
    -- no hace falta ir PC por PC."""
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('clave_admin_pcs', ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (nueva_clave,),
        )
