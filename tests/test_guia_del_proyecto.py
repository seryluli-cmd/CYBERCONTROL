"""La guía del proyecto (CLAUDE.md y docs/guia/) sigue diciendo la verdad.

Revisión general del 2026-11-16, mejora 5: CLAUDE.md pesaba 149 KB y se cargaba entero en
cada sesión. Quedó lo que vale siempre (la arquitectura, las 15 reglas, lo que no se cambia
sin el dueño); las funciones que son el único lugar de algo ("puntos únicos de verdad") y
las trampas se mudaron, tal cual, a docs/guia/, una guía por área.

Estas pruebas cuidan que eso no se desarme:
- cada función que citan las tablas de puntos únicos existe en el código: si alguien la
  renombra o la borra sin corregir la tabla, la guía manda a buscar algo que no está;
- CLAUDE.md no vuelve a engordar (lo nuevo va a la guía de su área);
- cada guía que nombra CLAUDE.md existe, y cada guía de docs/guia/ está nombrada ahí.

No importan nada del programa: leen los .py con ast, así no abren Qt ni la base.
"""

import ast
import os
import re
import unittest
from functools import lru_cache
from pathlib import Path

RAIZ = Path(__file__).resolve().parents[1]
GUIA = RAIZ / "docs" / "guia"
CLAUDE_MD = RAIZ / "CLAUDE.md"
# Quedó en ~18 KB; el margen es para crecer un poco, no para volver a mudar todo acá.
TOPE_CLAUDE_MD = 25_000
CARPETAS_QUE_NO_SON_EL_PROGRAMA = {"tests", "build", "dist", "data", "venv", "__pycache__"}


@lru_cache(maxsize=None)
def _modulos_del_programa():
    """Los .py del programa, por ruta con puntos ("ui.utils") y por nombre suelto ("pcs_repo")."""
    por_ruta, por_nombre = {}, {}
    for carpeta, subcarpetas, archivos in os.walk(RAIZ):
        subcarpetas[:] = [s for s in subcarpetas
                          if s not in CARPETAS_QUE_NO_SON_EL_PROGRAMA and not s.startswith(".")]
        for archivo in archivos:
            if not archivo.endswith(".py"):
                continue
            ruta = Path(carpeta) / archivo
            partes = ruta.relative_to(RAIZ).with_suffix("").parts
            if partes[-1] == "__init__":
                partes = partes[:-1]
            if not partes:
                continue
            por_ruta[".".join(partes)] = ruta
            por_nombre.setdefault(partes[-1], []).append(ruta)
    return por_ruta, por_nombre


@lru_cache(maxsize=None)
def _arbol(ruta):
    return ast.parse(ruta.read_text(encoding="utf-8"))


def _definidos(cuerpo):
    """Lo que define un bloque: funciones, clases, asignaciones e imports (lo reexportado)."""
    nombres = {}
    for nodo in cuerpo:
        if isinstance(nodo, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            nombres[nodo.name] = nodo
        elif isinstance(nodo, (ast.Assign, ast.AnnAssign)):
            destinos = nodo.targets if isinstance(nodo, ast.Assign) else [nodo.target]
            for destino in destinos:
                for parte in ast.walk(destino):
                    if isinstance(parte, ast.Name):
                        nombres[parte.id] = nodo
        elif isinstance(nodo, (ast.Import, ast.ImportFrom)):
            for alias in nodo.names:
                nombres[(alias.asname or alias.name).split(".")[0]] = nodo
        elif isinstance(nodo, (ast.If, ast.Try)):
            bloques = [nodo.body, nodo.orelse] + [getattr(nodo, "finalbody", [])]
            bloques += [manejador.body for manejador in getattr(nodo, "handlers", [])]
            for bloque in bloques:
                for nombre, definicion in _definidos(bloque).items():
                    nombres.setdefault(nombre, definicion)
    return nombres


def _existe_adentro(cuerpo, resto):
    if not resto:
        return True
    definicion = _definidos(cuerpo).get(resto[0])
    if definicion is None:
        return False
    if len(resto) == 1:
        return True
    if isinstance(definicion, ast.ClassDef):
        return _existe_adentro(definicion.body, resto[1:])
    # Un nombre importado de otro módulo: no se sigue la cadena (alcanza con que esté).
    return isinstance(definicion, (ast.Import, ast.ImportFrom))


def existe_en_el_codigo(referencia):
    """True si `referencia` ("ui.utils.formato_pesos", "pcs_repo.asignar_bono",
    "control_pcs/ui/pcs_cometa.CometaEnElBorde", "servidor_red._ManejadorEstado._responder_json")
    está definida en el programa."""
    por_ruta, por_nombre = _modulos_del_programa()
    partes = referencia.replace("/", ".").split(".")
    for corte in range(len(partes), 0, -1):
        modulo = ".".join(partes[:corte])
        if modulo in por_ruta:
            rutas = [por_ruta[modulo]]
        elif corte == 1:
            rutas = por_nombre.get(modulo, [])
        else:
            # "ui.anular_bono" dentro de control_pcs: la ruta citada es el final de la real.
            rutas = [ruta for real, ruta in por_ruta.items() if real.endswith("." + modulo)]
        if rutas:
            return any(_existe_adentro(_arbol(ruta).body, partes[corte:]) for ruta in rutas)
    return False


def referencias_de_la_fila(fila):
    """Los nombres que cita la primera columna de una fila de puntos únicos, completos.

    `.abrir_caja` al lado de `relevo_repo.situacion_al_entrar(...)` es `relevo_repo.abrir_caja`;
    un nombre suelto (`DB_PATH` al lado de `database.DATA_DIR`) se busca primero en el mismo
    lugar que el anterior y, si no, como módulo o nombre propio (`turnos_repo`).
    Devuelve una lista de alternativas por nombre: alcanza con que una exista."""
    primera_columna = fila.split("|")[1]
    anterior = None
    citas = []
    for crudo in re.findall(r"`([^`]+)`", primera_columna):
        nombre = crudo.split("(")[0].strip()
        if not re.fullmatch(r"[\w./]+", nombre):
            continue
        padre = anterior.rsplit(".", 1)[0] if anterior and "." in anterior else None
        if nombre.startswith("."):
            alternativas = [padre + nombre] if padre else [nombre.lstrip(".")]
        elif "." not in nombre.replace("/", ".") and padre:
            alternativas = [f"{padre}.{nombre}", nombre]
        else:
            alternativas = [nombre]
        citas.append(alternativas)
        anterior = alternativas[0]
    return citas


def filas_de_puntos_unicos(texto):
    """Las filas de la tabla "Puntos únicos de verdad" de una guía."""
    filas, adentro = [], False
    for renglon in texto.splitlines():
        if renglon.startswith("## "):
            adentro = renglon.startswith("## Puntos únicos")
        elif adentro and renglon.startswith("| `"):
            filas.append(renglon)
    return filas


def _guias():
    return sorted(GUIA.glob("*.md"))


class TestGuiaDelProyecto(unittest.TestCase):

    def test_cada_funcion_de_las_tablas_existe_en_el_codigo(self):
        faltan, revisadas = [], 0
        for guia in _guias():
            for fila in filas_de_puntos_unicos(guia.read_text(encoding="utf-8")):
                for alternativas in referencias_de_la_fila(fila):
                    revisadas += 1
                    if not any(existe_en_el_codigo(nombre) for nombre in alternativas):
                        faltan.append(f"{guia.name}: {alternativas[0]}")
        self.assertGreater(revisadas, 250, "No se encontraron las tablas de puntos únicos en docs/guia/")
        self.assertEqual(
            faltan, [],
            "Estas funciones de la tabla de puntos únicos ya no existen en el código. Si se "
            "renombraron o se mudaron, corregí la fila en la guía en el mismo commit:\n  "
            + "\n  ".join(faltan))

    def test_la_revision_detecta_un_nombre_que_no_existe(self):
        fila = ("| `turnos.calcular_turno(fecha_hora)` · `.no_existe_esta_funcion` · "
                "`pcs_repo.tampoco_esta` | algo |")
        citas = referencias_de_la_fila(fila)
        self.assertEqual([c[0] for c in citas], [
            "turnos.calcular_turno", "turnos.no_existe_esta_funcion", "pcs_repo.tampoco_esta"])
        self.assertEqual([any(existe_en_el_codigo(n) for n in c) for c in citas],
                         [True, False, False])

    def test_la_revision_entiende_clases_rutas_y_nombres_sueltos(self):
        for nombre in ("servidor_red._ManejadorEstado._responder_json",
                       "control_pcs/ui/pcs_cometa.CometaEnElBorde",
                       "ui.utils.formato_pesos", "database.DB_PATH", "turnos_repo",
                       "ui.anular_bono.anular_bono_con_cartel"):
            with self.subTest(nombre=nombre):
                self.assertTrue(existe_en_el_codigo(nombre))
        self.assertFalse(existe_en_el_codigo("servidor_red._ManejadorEstado.no_existe"))

    def test_claude_md_no_vuelve_a_engordar(self):
        tamano = len(CLAUDE_MD.read_bytes())
        self.assertLessEqual(
            tamano, TOPE_CLAUDE_MD,
            f"CLAUDE.md pesa {tamano} bytes (tope {TOPE_CLAUDE_MD}) y se carga entero en cada "
            "sesión. Una función o una trampa nueva va a la guía de su área en docs/guia/; lo "
            "que se terminó, con fecha, a docs/HISTORIAL.md.")

    def test_cada_guia_esta_nombrada_en_claude_md_y_existe(self):
        nombradas = set(re.findall(r"docs/guia/([A-Z_]+\.md)", CLAUDE_MD.read_text(encoding="utf-8")))
        existentes = {guia.name for guia in _guias()}
        self.assertEqual(nombradas - existentes, set(), "CLAUDE.md nombra guías que no existen")
        self.assertEqual(existentes - nombradas, set(),
                         "Hay guías en docs/guia/ que CLAUDE.md no nombra: nadie las va a leer")

    def test_cada_guia_tiene_sus_dos_partes(self):
        for guia in _guias():
            texto = guia.read_text(encoding="utf-8")
            with self.subTest(guia=guia.name):
                self.assertIn("## Puntos únicos de verdad", texto)
                self.assertIn("## Trampas conocidas", texto)
                self.assertIn("](../../CLAUDE.md)", texto)


if __name__ == "__main__":
    unittest.main()
