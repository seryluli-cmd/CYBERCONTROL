"""
temperatura_pc_repo.py
=======================
La temperatura del procesador y de la placa de video de cada PC (pedido del dueño, 2026-10-22:
un termómetro al costado de cada monitor del mosaico, y "CALIENTE" titilando cuando se pasa).

La mide cada Cliente PC (`CLIENTE PC/temperatura.py`, con LibreHardwareMonitor) y la manda en
cada `GET /estado` como `temp_cpu` y `temp_gpu`, en grados enteros. Para el procesador la PC
necesita el driver PawnIO y correr como Administrador: sin eso solo llega la placa de video, y un
Cliente PC viejo no manda nada. Qué es "caliente" lo decide `dominio.nivel_de_temperatura`.

Es un dato para mirar, nada más: nunca puede tocar el bloqueo (`servidor_red` lo graba en su
propio try) y no se guarda historia, solo lo último en `estaciones.temp_cpu`/`temp_gpu`. Se graba
solo si cambió, para no sumar una escritura por PC cada 5 s. Lo que se guardó vale mientras la PC
siga enlazada: de una PC apagada o sin Cliente PC no se muestra una temperatura vieja.
"""

from database import conexion_db

# Lo que se acepta como temperatura: un sensor que se lee mal da 0 o 255.
_MINIMA, _MAXIMA = 1, 149


def _grados(valor):
    try:
        grados = int(str(valor).strip())
    except (TypeError, ValueError):
        return None
    return grados if _MINIMA <= grados <= _MAXIMA else None


def leer_temperatura(parametros: dict) -> dict:
    """Lo que mandó el Cliente PC en su GET /estado, ya revisado: {"cpu", "gpu"}, cada uno None
    si no vino o no se entiende."""
    return {"cpu": _grados(parametros.get("temp_cpu")), "gpu": _grados(parametros.get("temp_gpu"))}


def registrar(estacion_id: int, temperatura: dict) -> bool:
    """Guarda la última temperatura de esa estación, solo si cambió (también si dejó de llegar).
    Devuelve si la guardó."""
    with conexion_db() as conexion:
        return conexion.execute(
            """
            UPDATE estaciones SET temp_cpu = ?, temp_gpu = ?
            WHERE id = ? AND (temp_cpu IS NOT ? OR temp_gpu IS NOT ?)
            """,
            (temperatura["cpu"], temperatura["gpu"], estacion_id, temperatura["cpu"], temperatura["gpu"]),
        ).rowcount > 0


def vigente(estacion, enlazada: bool) -> dict:
    """La temperatura que se muestra de una estación ({"cpu", "gpu"}): None en los dos si no está
    enlazada (lo guardado es de cuando todavía preguntaba) o si su Cliente PC nunca la mandó."""
    claves = estacion.keys()
    if not enlazada or "temp_cpu" not in claves:
        return {"cpu": None, "gpu": None}
    return {"cpu": estacion["temp_cpu"], "gpu": estacion["temp_gpu"]}
