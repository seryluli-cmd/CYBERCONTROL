"""
tests/correr_en_paralelo.py
===========================
Corre TODAS las pruebas repartiendo los archivos `test*.py` entre varios
procesos (8 a la vez si no se dice otra cosa). Es la forma rápida de cumplir
la regla 15 ("correr los tests antes de decir listo"): con la base plantilla
de `tests/base.py` tarda un par de minutos en vez de los 23 de antes
(revisión general del 2026-11-16, mejora 1).

    python tests/correr_en_paralelo.py                  # todas
    python tests/correr_en_paralelo.py -j 4             # 4 archivos a la vez
    python tests/correr_en_paralelo.py test_cajas test_kiosko   # solo esos

Cada archivo corre en su propio proceso con el mismo comando que usa
`python -m unittest discover tests` (`discover -s tests -p <archivo>`), así
que cada prueba ve lo mismo que en la corrida de siempre, que sigue andando
igual. Al final, si algo falló, muestra la salida completa de ese archivo, y
avisa si cambió algo en `data\\` del proyecto mientras corrían (no debería:
ver `tests/base.py`).

No es un archivo de pruebas (no empieza con "test"): discover no lo junta.
"""

import argparse
import fnmatch
import os
import re
import subprocess
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

CARPETA_PRUEBAS = os.path.dirname(os.path.abspath(__file__))
RAIZ = os.path.dirname(CARPETA_PRUEBAS)
CARPETA_DATOS = os.path.join(RAIZ, "data")
PATRON = "test*.py"  # el mismo de unittest discover
PROCESOS_POR_DEFECTO = 8
# Ningún archivo tarda ni un minuto: pasado esto se lo da por colgado.
SEGUNDOS_MAXIMOS_POR_ARCHIVO = 600


def _segundos(valor):
    return f"{valor:.1f}".replace(".", ",") + " s"


def _archivos(pedidos):
    todos = sorted(f for f in os.listdir(CARPETA_PRUEBAS) if fnmatch.fnmatch(f, PATRON))
    if pedidos:
        buscados = {p if p.endswith(".py") else p + ".py" for p in pedidos}
        faltan = buscados - set(todos)
        if faltan:
            sys.exit(f"No existen en tests/: {', '.join(sorted(faltan))}")
        todos = [f for f in todos if f in buscados]
    # Los más grandes primero: así el último que queda corriendo es uno corto.
    return sorted(todos, key=lambda f: os.path.getsize(os.path.join(CARPETA_PRUEBAS, f)), reverse=True)


def _foto_de_datos():
    """Nombre, tamaño y hora de cada archivo de data\\ del proyecto (si existe)."""
    foto = {}
    for carpeta, _, archivos in os.walk(CARPETA_DATOS):
        for nombre in archivos:
            ruta = os.path.join(carpeta, nombre)
            try:
                info = os.stat(ruta)
            except OSError:
                continue
            foto[os.path.relpath(ruta, RAIZ)] = (info.st_size, info.st_mtime_ns)
    return foto


def _leer_resultado(salida):
    """Lo que dice unittest al final: cuántas corrieron y cómo terminó."""
    corridas = re.search(r"^Ran (\d+) tests? in ", salida, re.M)
    final = re.search(r"^(OK|FAILED)(?: \((.*)\))?\s*$", salida, re.M)
    detalle = {}
    if final and final.group(2):
        for parte in final.group(2).split(","):
            clave, _, valor = parte.strip().partition("=")
            if valor.isdigit():
                detalle[clave] = int(valor)
    return (int(corridas.group(1)) if corridas else 0), (final.group(1) if final else None), detalle


def _correr(archivo):
    comando = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-p", archivo]
    entorno = dict(os.environ, PYTHONIOENCODING="utf-8")
    # En la corrida de siempre, el primer archivo que lo pone vale para todos.
    entorno.setdefault("QT_QPA_PLATFORM", "offscreen")
    inicio = time.perf_counter()
    try:
        proceso = subprocess.run(
            comando, cwd=RAIZ, env=entorno, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            encoding="utf-8", errors="replace", timeout=SEGUNDOS_MAXIMOS_POR_ARCHIVO,
        )
        salida, codigo = proceso.stdout, proceso.returncode
    except subprocess.TimeoutExpired as colgado:
        salida = (colgado.stdout or "") if isinstance(colgado.stdout, str) else ""
        salida += f"\n*** Se colgó: pasaron {SEGUNDOS_MAXIMOS_POR_ARCHIVO} s y se lo cortó. ***\n"
        codigo = None
    duracion = time.perf_counter() - inicio
    corridas, final, detalle = _leer_resultado(salida)
    bien = codigo == 0 and final == "OK"
    return {"archivo": archivo, "bien": bien, "corridas": corridas, "detalle": detalle,
            "segundos": duracion, "salida": salida, "codigo": codigo}


def main():
    try:
        sys.stdout.reconfigure(errors="replace")
    except AttributeError:
        pass
    parser = argparse.ArgumentParser(description="Corre las pruebas de tests/ en paralelo, un proceso por archivo.")
    parser.add_argument("archivos", nargs="*", help="solo estos archivos (con o sin .py)")
    parser.add_argument("-j", "--procesos", type=int, default=PROCESOS_POR_DEFECTO,
                        help=f"cuántos archivos a la vez (de fábrica {PROCESOS_POR_DEFECTO})")
    argumentos = parser.parse_args()

    archivos = _archivos(argumentos.archivos)
    procesos = max(1, min(argumentos.procesos, len(archivos)))
    print(f"Corriendo {len(archivos)} archivos de prueba, {procesos} a la vez...", flush=True)
    datos_antes = _foto_de_datos()
    inicio = time.perf_counter()
    resultados = []
    with ThreadPoolExecutor(max_workers=procesos) as pool:
        pendientes = [pool.submit(_correr, archivo) for archivo in archivos]
        for numero, terminado in enumerate(as_completed(pendientes), start=1):
            r = terminado.result()
            resultados.append(r)
            estado = "OK   " if r["bien"] else "FALLA"
            print(f"[{numero:>2}/{len(archivos)}] {estado} {r['archivo']:<40} "
                  f"{r['corridas']:>4} pruebas  {_segundos(r['segundos']):>8}", flush=True)
    total_segundos = time.perf_counter() - inicio

    fallados = [r for r in resultados if not r["bien"]]
    for r in sorted(fallados, key=lambda r: r["archivo"]):
        print("\n" + "=" * 78)
        print(f"FALLÓ {r['archivo']} (código de salida {r['codigo']}):")
        print("=" * 78)
        print(r["salida"].rstrip())

    corridas = sum(r["corridas"] for r in resultados)
    salteadas = sum(r["detalle"].get("skipped", 0) for r in resultados)
    fallas = sum(r["detalle"].get("failures", 0) for r in resultados)
    errores = sum(r["detalle"].get("errors", 0) for r in resultados)
    print("\n" + "-" * 78)
    lentos = sorted(resultados, key=lambda r: r["segundos"], reverse=True)[:5]
    print("Los más lentos: " + ", ".join(f"{r['archivo']} {_segundos(r['segundos'])}" for r in lentos))
    if fallados:
        print(f"FALLARON {len(fallados)} de {len(archivos)} archivos "
              f"({fallas} fallas, {errores} errores; {corridas} pruebas corridas, {salteadas} salteadas) "
              f"en {_segundos(total_segundos)}.")
    else:
        print(f"OK: {corridas} pruebas en {len(archivos)} archivos ({salteadas} salteadas) "
              f"en {_segundos(total_segundos)}, {procesos} a la vez.")

    datos_despues = _foto_de_datos()
    cambiados = sorted(n for n in set(datos_antes) | set(datos_despues) if datos_antes.get(n) != datos_despues.get(n))
    if cambiados:
        print("\nOJO: cambió algo en data\\ del proyecto mientras corrían las pruebas:")
        for nombre in cambiados[:20]:
            print("   ", nombre)
        print("Si el programa estaba abierto desde esta carpeta puede ser él; si no, alguna prueba "
              "escribió fuera de su carpeta temporal (ver tests/base.py).")
    return 1 if fallados else 0


if __name__ == "__main__":
    sys.exit(main())
