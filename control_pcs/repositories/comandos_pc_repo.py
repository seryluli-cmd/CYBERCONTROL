"""
comandos_pc_repo.py
=====================
Control remoto de una estación desde el mostrador: reiniciar, apagar,
mandar un mensaje, pedir una captura de pantalla, cambiar la puerta de
enlace/DNS de red o ajustar el volumen. Como el mostrador no tiene
conexión directa hacia la PC cliente, esto solo deja un comando
"pendiente" en la base -- el Cliente PC de esa estación (carpeta hermana
"CLIENTE PC") lo recoge solo en su próxima consulta de
`GET /estado`, cada 5 segundos (ver servidor_red.py).

Por eso una acción acá no es instantánea: el Operador puede ver el
resultado tardar hasta esos 5 segundos (más lo que tarde la PC en
ejecutar la acción). Para REINICIAR/APAGAR/MENSAJE/VOLUMEN no hace falta
ningún resultado de vuelta -- entregado es entregado. Para SCREENSHOT y
CAMBIAR_RED sí: el Cliente PC sube un resultado aparte con
`POST /comando_resultado` -- la imagen para SCREENSHOT
(`guardar_screenshot` la deja en disco, no en la fila de la base, para no
inflar el .db con binarios, devolviendo la ruta relativa) o un texto
corto "OK"/"ERROR: ..." para CAMBIAR_RED (directo en `comandos_pc.resultado`,
ver `marcar_resultado`) -- a diferencia de reiniciar/apagar, cambiar de
módem sí puede fallar del lado de la PC (adaptador no encontrado, sin
permisos) y vale la pena que el mostrador se entere sin tener que ir
hasta ahí a revisar.
"""

import base64
import os
from datetime import datetime

import database
from database import conexion_db

TIPO_REINICIAR = "REINICIAR"
TIPO_APAGAR = "APAGAR"
TIPO_MENSAJE = "MENSAJE"
TIPO_SCREENSHOT = "SCREENSHOT"
TIPO_CAMBIAR_RED = "CAMBIAR_RED"
TIPO_VOLUMEN = "VOLUMEN"


def encolar_comando(estacion_id: int, tipo: str, payload: str = None) -> int:
    """Deja un comando pendiente para que el Cliente PC de esa estación lo
    recoja en su próxima consulta de estado. Devuelve el id del comando
    (lo necesita, por ejemplo, DialogoCaptura para saber cuál resultado
    esperar)."""
    with conexion_db() as conexion:
        cursor = conexion.execute(
            """
            INSERT INTO comandos_pc (estacion_id, tipo, payload, fecha_creacion, estado)
            VALUES (?, ?, ?, ?, 'PENDIENTE')
            """,
            (estacion_id, tipo, payload, datetime.now().isoformat(timespec="seconds")),
        )
        return cursor.lastrowid


def proximo_comando_pendiente(estacion_id: int):
    """El comando pendiente más viejo para esta estación, o None. Lo
    llama servidor_red.py en cada `GET /estado` de esa estación."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT * FROM comandos_pc WHERE estacion_id = ? AND estado = 'PENDIENTE'
            ORDER BY fecha_creacion LIMIT 1
            """,
            (estacion_id,),
        ).fetchone()


def marcar_entregado(comando_id: int):
    """Se llama apenas el comando se incluye en una respuesta de
    `GET /estado` -- no se espera una confirmación aparte del Cliente PC
    (mismo criterio de simpleza que el resto de este protocolo: si la
    respuesta no llega a destino por un problema de red, el Operador
    simplemente vuelve a mandar la acción, no hay nada crítico en juego
    como para justificar un mecanismo de reintento más elaborado)."""
    with conexion_db() as conexion:
        conexion.execute("UPDATE comandos_pc SET estado = 'ENTREGADO' WHERE id = ?", (comando_id,))


def obtener_comando(comando_id: int):
    with conexion_db() as conexion:
        return conexion.execute("SELECT * FROM comandos_pc WHERE id = ?", (comando_id,)).fetchone()


def guardar_screenshot(comando_id: int, imagen_base64: str) -> str:
    """Decodifica la imagen que subió el Cliente PC (ver
    servidor_red.py:_manejar_comando_resultado) y la guarda en
    data/screenshots/. Devuelve la ruta RELATIVA a DATA_DIR, que es lo
    que se guarda en `comandos_pc.resultado` -- así la UI (pcs_window.py)
    la puede abrir armando `os.path.join(database.DATA_DIR, resultado)`
    sin que el nombre de la carpeta quede pisado si se migra la base a
    otra PC.

    Ojo: `database.DATA_DIR` se lee acá adentro (no en una constante de
    módulo) a propósito -- los tests apuntan `database.DATA_DIR` a una
    carpeta temporal antes de cada uno (ver tests/base.py), y una
    constante calculada una sola vez al importar este archivo se habría
    quedado con la carpeta real de siempre, ignorando ese aislamiento."""
    carpeta_screenshots = os.path.join(database.DATA_DIR, "screenshots")
    os.makedirs(carpeta_screenshots, exist_ok=True)
    nombre_archivo = f"comando_{comando_id}.png"
    ruta_completa = os.path.join(carpeta_screenshots, nombre_archivo)
    with open(ruta_completa, "wb") as archivo:
        archivo.write(base64.b64decode(imagen_base64))
    return os.path.join("screenshots", nombre_archivo)


def marcar_resultado(comando_id: int, ruta_relativa):
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE comandos_pc SET resultado = ? WHERE id = ?", (ruta_relativa, comando_id)
        )
