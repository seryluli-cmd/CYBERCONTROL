"""
filtro_palabras_repo.py
=========================
El filtro de palabras de las PCs cliente (pedido del dueño, 2026-10-17: una
"protección antiporno" como la del programa de cyber que usaba antes).

Cómo funciona, de punta a punta:
- El Admin carga acá la lista de palabras, si el filtro está prendido y el
  mensaje que ve el cliente (Configuración ADMIN -> Gestionar Estaciones ->
  "Filtro de palabras de las PCs...", ver control_pcs/ui/pcs_filtro_dialogo.py).
- Cada Cliente PC se la pide al Servidor (`GET /filtro`) y la vuelve a pedir solo
  cuando cambia `filtro_version`, que viaja en cada `GET /estado` (mismo camino que
  el fondo de pantalla). Con una sesión en curso, mira el título de la ventana que
  el cliente tiene adelante; si aparece una palabra de la lista, cierra esa
  pestaña, muestra el mensaje y avisa (`POST /filtro_bloqueo`). Buscar las
  palabras (palabra entera, sin mayúsculas ni acentos) es tarea del Cliente PC
  (`CLIENTE PC/filtro_palabras.py`): acá solo se guarda la lista.
- Cada aviso queda en `bloqueos_filtro_pc` (nada se borra, regla 7) y se ve en
  "Actividad reciente" de Control de PCs y en la misma pantalla del filtro.

La configuración es una lista chica que el Admin edita de vez en cuando, así que
vive como JSON en la tabla genérica `configuracion` (mismo patrón que
`config_repo.obtener_tramos_tarifa_hora_miembro`), no en una tabla propia.
"""

import hashlib
import json
from datetime import datetime, timedelta

from database import conexion_db
from control_pcs.repositories.accesos_admin_pc_repo import MAXIMO_SEGUNDOS_ATRAS

_CLAVE_CONFIGURACION = "filtro_palabras"

# Topes de lo que se guarda: la lista viaja entera a las ~40 PCs cada vez que
# cambia y cada PC la revisa varias veces por segundo, así que no puede crecer
# sin límite. Mil palabras ya es mucho más de lo que se usa en la práctica.
MAXIMO_PALABRAS = 1000
MINIMO_LARGO_PALABRA = 2   # una sola letra ("x") cerraría cualquier página que la nombre suelta
MAXIMO_LARGO_PALABRA = 60
MAXIMO_LARGO_MENSAJE = 500
# Lo que se guarda de cada aviso que manda una PC.
MAXIMO_LARGO_TITULO = 300

# Lo que trae el filtro antes de que el Admin lo toque: la lista que el dueño
# usaba en su programa anterior (sin "DP", que es demasiado común: aparece en
# títulos de monitores y cables) y prendido, porque fue lo que pidió.
PALABRAS_POR_DEFECTO = (
    "desnudo", "desnuda", "porno", "hentai", "sex", "sexo", "anal", "xxx", "erome", "xvideos",
    "pornhub", "folla", "penetra", "xnxx", "seks", "youx",
    "xvideos.es", "pornhub.com", "xnxx.com", "youx.xxx",
)
MENSAJE_POR_DEFECTO = "Esta página no está permitida en el local.\nSe le avisó al mostrador."


def _version(activo: bool, palabras: list, mensaje: str) -> str:
    """La huella de lo que reciben las PCs: cambia si cambia cualquiera de las
    tres cosas, así cada PC sabe que tiene que volver a pedir la lista."""
    contenido = json.dumps({"activo": activo, "palabras": palabras, "mensaje": mensaje},
                           ensure_ascii=False, sort_keys=True)
    return hashlib.sha256(contenido.encode("utf-8")).hexdigest()[:16]


def _armar(activo: bool, palabras: list, mensaje: str) -> dict:
    return {"activo": activo, "palabras": palabras, "mensaje": mensaje,
            "version": _version(activo, palabras, mensaje)}


def obtener() -> dict:
    """
    Lo que tienen que usar las PCs: {"activo", "palabras", "mensaje", "version"}.
    Si el Admin nunca lo guardó, la lista por defecto. Un valor guardado que no se
    puede leer (base tocada a mano) cuenta como que nunca se guardó: mejor el
    filtro por defecto que ninguno.
    """
    with conexion_db() as conexion:
        fila = conexion.execute(
            "SELECT valor FROM configuracion WHERE clave = ?", (_CLAVE_CONFIGURACION,)
        ).fetchone()
    if fila is not None:
        try:
            datos = json.loads(fila["valor"])
            palabras = [str(palabra) for palabra in datos["palabras"]]
            return _armar(bool(datos["activo"]), palabras, str(datos["mensaje"]))
        except (ValueError, TypeError, KeyError):
            pass
    return _armar(True, list(PALABRAS_POR_DEFECTO), MENSAJE_POR_DEFECTO)


def version_actual() -> str:
    """La versión que viaja en cada `GET /estado` (ver servidor_red.py)."""
    return obtener()["version"]


def limpiar_palabras(texto: str) -> list:
    """
    Una palabra o frase por renglón, tal cual las escribe el Admin, pasadas a la
    forma en que se guardan: sin espacios de más, en minúsculas y sin repetidas
    (respetando el orden). Los renglones vacíos se saltean. Levanta ValueError con
    un mensaje para mostrar si alguna no sirve.
    """
    palabras = []
    for renglon in str(texto or "").splitlines():
        palabra = " ".join(renglon.split()).lower()
        if not palabra or palabra in palabras:
            continue
        if len(palabra) < MINIMO_LARGO_PALABRA:
            raise ValueError(
                f"\"{palabra}\" es demasiado corta: cada palabra tiene que tener al menos "
                f"{MINIMO_LARGO_PALABRA} letras (una sola cerraría casi cualquier página)."
            )
        if len(palabra) > MAXIMO_LARGO_PALABRA:
            raise ValueError(f"\"{palabra[:30]}...\" es demasiado larga (máximo {MAXIMO_LARGO_PALABRA} letras).")
        if not any(caracter.isalnum() for caracter in palabra):
            raise ValueError(f"\"{palabra}\" no tiene ninguna letra ni número.")
        palabras.append(palabra)
    if len(palabras) > MAXIMO_PALABRAS:
        raise ValueError(f"Son {len(palabras)} palabras: el máximo es {MAXIMO_PALABRAS}.")
    return palabras


def guardar(activo: bool, texto_palabras: str, mensaje: str) -> dict:
    """
    Guarda el filtro (`texto_palabras`: una palabra o frase por renglón, ver
    `limpiar_palabras`) y devuelve cómo quedó, con su versión nueva. Las PCs
    prendidas lo toman solas en su próxima consulta de estado. Un mensaje vacío
    es válido: el filtro cierra la pestaña sin mostrar nada.
    """
    palabras = limpiar_palabras(texto_palabras)
    mensaje = str(mensaje or "").strip()
    if len(mensaje) > MAXIMO_LARGO_MENSAJE:
        raise ValueError(f"El mensaje es demasiado largo (máximo {MAXIMO_LARGO_MENSAJE} letras).")
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT OR REPLACE INTO configuracion (clave, valor) VALUES (?, ?)",
            (_CLAVE_CONFIGURACION, json.dumps(
                {"activo": bool(activo), "palabras": palabras, "mensaje": mensaje}, ensure_ascii=False,
            )),
        )
    return obtener()


def registrar_bloqueo(estacion_id: int, palabra: str, titulo: str, segundos_atras: float = 0):
    """
    Anota que el Cliente PC de `estacion_id` cerró una página porque su título
    tenía `palabra`. `segundos_atras` es hace cuánto pasó (la PC junta los avisos
    mientras el Servidor no contesta y los manda después; no manda su hora porque
    el reloj de cada PC puede estar corrido, mismo criterio que
    `accesos_admin_pc_repo.registrar_evento`).
    """
    palabra = " ".join(str(palabra or "").split())[:MAXIMO_LARGO_PALABRA]
    if not palabra:
        raise ValueError("Falta la palabra que encontró el filtro.")
    titulo = " ".join(str(titulo or "").split())[:MAXIMO_LARGO_TITULO]
    segundos_atras = min(max(float(segundos_atras or 0), 0.0), MAXIMO_SEGUNDOS_ATRAS)
    fecha = (datetime.now() - timedelta(seconds=segundos_atras)).isoformat(timespec="seconds")
    with conexion_db() as conexion:
        conexion.execute(
            "INSERT INTO bloqueos_filtro_pc (estacion_id, fecha_hora, palabra, titulo) VALUES (?, ?, ?, ?)",
            (estacion_id, fecha, palabra, titulo),
        )


def listar_recientes(limite: int):
    """Los últimos `limite` bloqueos, del más nuevo al más viejo, con el nombre
    de la PC: para la pantalla del filtro y para "Actividad reciente" (ver
    actividad_repo; corre en cada refresco, por eso se apoya en el índice por fecha)."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            SELECT bloqueos_filtro_pc.fecha_hora, bloqueos_filtro_pc.palabra, bloqueos_filtro_pc.titulo,
                   estaciones.nombre AS estacion_nombre
            FROM bloqueos_filtro_pc
            JOIN estaciones ON estaciones.id = bloqueos_filtro_pc.estacion_id
            ORDER BY bloqueos_filtro_pc.fecha_hora DESC, bloqueos_filtro_pc.id DESC
            LIMIT ?
            """,
            (limite,),
        ).fetchall()
