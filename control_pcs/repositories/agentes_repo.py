"""
agentes_repo.py
================
Acceso a las dos claves compartidas por todas las PC clientes (carpeta
hermana "AGENTE PC KIOSKO"), ambas guardadas en la tabla `configuracion`
-- mismo patrón que `config_repo.py`:

- 'clave_agentes': la que usa el software cliente para autenticarse
  contra `servidor_red.py` (ver `red_kiosko._cabeceras_agente`). La
  genera `generar_clave_agentes()`, al azar, y rota TODAS las PC clientes
  de una.
- 'clave_admin_pcs': la contraseña de administrador que destraba el panel
  admin en la pantalla de bloqueo de cada PC cliente (ver el ícono "A" en
  `agente_bloqueo.py`). A diferencia de la anterior, la ELIGE el dueño
  (no se genera al azar, tiene que poder recordarla) con
  `establecer_clave_admin_pcs()`. Cada PC cliente la guarda en un
  archivo local propio y la mantiene al día sola preguntándosela al
  Servidor en cada `GET /estado` (viaja adentro de esa respuesta, mismo
  criterio que los comandos remotos) -- así cambiarla implica un solo
  clic acá, no ir PC por PC.
"""

import secrets

from database import conexion_db


def obtener_clave_agentes() -> str:
    """Cadena vacía si todavía no se generó ninguna clave (estado inicial,
    antes de usar "Generar/renovar clave de agentes" por primera vez)."""
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = 'clave_agentes'"
        ).fetchone()
        return fila["valor"] if fila else ""


def generar_clave_agentes() -> str:
    """
    Genera una clave nueva al azar (43 caracteres, por encima del mínimo
    de 32 que exige el asistente de configuración del agente) y la
    guarda, reemplazando la anterior si había una. Rota TODOS los
    agentes de una: la clave vieja deja de servir para cualquier PC
    apenas se llama esto -- coherente con que es una sola clave
    compartida, no una por estación.
    """
    clave_nueva = secrets.token_urlsafe(32)
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT INTO configuracion (clave, valor) VALUES ('clave_agentes', ?) "
            "ON CONFLICT(clave) DO UPDATE SET valor = excluded.valor",
            (clave_nueva,),
        )
    return clave_nueva


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
