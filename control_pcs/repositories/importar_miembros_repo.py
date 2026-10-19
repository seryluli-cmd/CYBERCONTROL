"""
importar_miembros_repo.py
===========================
Trae los socios del programa de cyber anterior desde una planilla de Excel
(pedido del dueño, 2026-10-19: exportó los miembros de su programa viejo a una
planilla y no quería volver a cargarlos uno por uno). De cada renglón se toman
el usuario, el nombre, la contraseña y el tiempo que le quedaba; el DNI y los
teléfonos los completa cada socio la primera vez que entra desde su PC, igual
que en cualquier alta rápida (ver miembros_repo).

Reglas:
- La planilla tiene que tener, en un mismo renglón, los títulos "Usuario" y
  "Contraseña" (o "Clave"); "Nombre" y "Tiempo" son opcionales. Lo que está
  arriba de los títulos (título, notas) no se mira, y tampoco un renglón sin
  contraseña, nombre ni tiempo (el "Saldo total" del final).
- Un usuario que ya existe en el programa (activo o no) se saltea: no se le
  cambia la clave ni se le vuelve a sumar el tiempo. Así, importar dos veces la
  misma planilla no duplica nada.
- El tiempo se guarda en minutos enteros, sin redondear para arriba (lo que
  sobra son segundos). Un tiempo que no se entiende ("Por confirmar") deja al
  socio con 0 y se avisa, para cargarlo a mano.
- El tiempo traído queda en el historial de saldo como IMPORTACION, sin venta:
  esa plata se cobró en el programa anterior y no puede aparecer en la caja ni
  en los reportes.
- Todo en una transacción: entran todos los socios nuevos o ninguno.
- Solo un Administrador: le da tiempo a cuentas sin cobrar nada.

La planilla se lee con la biblioteca estándar (un .xlsx es un .zip con XML
adentro): el .exe no lleva openpyxl y no hace falta sumarlo por esto.
"""

import re
import unicodedata
import zipfile
import xml.etree.ElementTree as ET
from datetime import datetime

import dominio
from database import conexion_db
from repositories import usuarios_repo
from control_pcs.repositories import miembros_repo

_NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
_SEGUNDOS_POR_DIA = 24 * 60 * 60


def minutos_del_tiempo(valor):
    """
    Los minutos enteros de un tiempo de la planilla, o None si no es un tiempo.
    Excel guarda un tiempo como fracción de día (0,5 = 12 horas); también se
    acepta escrito como "h:mm" o "h:mm:ss". Los segundos que sobran se
    descartan: nunca se redondea para arriba. Una celda vacía es 0.
    """
    if valor is None or (isinstance(valor, str) and not valor.strip()):
        return 0
    if isinstance(valor, float):
        if valor < 0:
            return None
        # A segundos enteros primero: un 1:18:00 justo llega como 0,0541666...
        # y pasado directo a minutos puede dar 77,99999 → 77.
        segundos = round(valor * _SEGUNDOS_POR_DIA)
    else:
        partes = re.fullmatch(r"\s*(\d+):(\d{1,2})(?::(\d{1,2}))?\s*", str(valor))
        if partes is None:
            return None
        horas, minutos, segundos_sueltos = (int(parte or 0) for parte in partes.groups())
        segundos = horas * 3600 + minutos * 60 + segundos_sueltos
    return segundos // 60


def revisar_planilla(ruta: str) -> dict:
    """Lo que haría importar la planilla de `ruta`, sin tocar nada (para
    mostrarlo antes de confirmar). Mismo formato que importar_planilla.
    Levanta ValueError si el archivo no se puede leer o no tiene los títulos."""
    renglones = _socios_de_la_planilla(ruta)
    with conexion_db() as conexion:
        return _resumen(_planificar(conexion, renglones))


def importar_planilla(ruta: str, usuario_id: int) -> dict:
    """
    Da de alta los socios nuevos de la planilla con su tiempo, todo en una
    transacción, y devuelve el resumen de lo que hizo:
    {"nuevos": [{"fila", "usuario", "nombre", "minutos"}], "minutos_en_total",
     "sin_tiempo": [(usuario, lo que decía la planilla)],
     "con_poco_saldo": [usuario], "ya_existen": [usuario],
     "con_problemas": [(fila, usuario, motivo)]}.
    Vuelve a leer la planilla y la base en vez de confiar en lo que se revisó
    antes: entre una cosa y la otra pudo cambiar cualquiera de las dos.
    """
    usuarios_repo.exigir_admin(usuario_id, "importar socios")
    renglones = _socios_de_la_planilla(ruta)
    ahora = datetime.now().isoformat(timespec="seconds")
    with conexion_db() as conexion:
        conexion.execute("BEGIN IMMEDIATE")
        plan = _planificar(conexion, renglones)
        for socio in plan["nuevos"]:
            miembro_id = miembros_repo._insertar_miembro(conexion, socio["datos"], socio["clave"], ahora)
            if socio["minutos"]:
                conexion.execute(
                    "UPDATE miembros SET saldo_minutos = ? WHERE id = ?", (socio["minutos"], miembro_id)
                )
                conexion.execute(
                    """
                    INSERT INTO movimientos_saldo_miembro (miembro_id, tipo, minutos, fecha)
                    VALUES (?, ?, ?, ?)
                    """,
                    (miembro_id, dominio.MOVIMIENTO_IMPORTACION, socio["minutos"], ahora),
                )
        return _resumen(plan)


def _planificar(conexion, renglones: list) -> dict:
    """Decide qué pasa con cada renglón de la planilla: socio nuevo (con sus
    datos ya validados, su clave y sus minutos), usuario que ya existe, o
    renglón que no se puede importar y por qué."""
    existentes = {fila["usuario"] for fila in conexion.execute("SELECT usuario FROM miembros")}
    plan = {"nuevos": [], "ya_existen": [], "con_problemas": []}
    fila_de_cada_usuario = {}
    for renglon in renglones:
        usuario = _texto(renglon.get("usuario")).strip()
        nombre = _texto(renglon.get("nombre")).strip()
        clave = _texto(renglon.get("clave"))
        tiempo = renglon.get("tiempo")
        if not clave and not nombre and tiempo is None:
            continue
        fila = renglon["fila"]
        if not usuario:
            plan["con_problemas"].append((fila, "", "falta el usuario"))
            continue
        if usuario in fila_de_cada_usuario:
            plan["con_problemas"].append(
                (fila, usuario, f"está repetido en la planilla (ya está en la fila {fila_de_cada_usuario[usuario]})")
            )
            continue
        fila_de_cada_usuario[usuario] = fila
        if usuario in existentes:
            plan["ya_existen"].append(usuario)
            continue
        if not clave:
            plan["con_problemas"].append((fila, usuario, "falta la contraseña"))
            continue
        minutos = minutos_del_tiempo(tiempo)
        plan["nuevos"].append({
            "fila": fila,
            "usuario": usuario,
            "datos": miembros_repo._datos_de_miembro(usuario, nombre, "", ""),
            "clave": clave,
            "minutos": minutos or 0,
            "tiempo_sin_entender": None if minutos is not None else _texto(tiempo),
        })
    return plan


def _resumen(plan: dict) -> dict:
    """El plan sin las claves ni los datos internos, para la pantalla."""
    nuevos = plan["nuevos"]
    return {
        "nuevos": [
            {"fila": socio["fila"], "usuario": socio["usuario"], "nombre": socio["datos"]["nombre"],
             "minutos": socio["minutos"]}
            for socio in nuevos
        ],
        "minutos_en_total": sum(socio["minutos"] for socio in nuevos),
        "sin_tiempo": [(socio["usuario"], socio["tiempo_sin_entender"])
                       for socio in nuevos if socio["tiempo_sin_entender"] is not None],
        # Con menos de un bloque no se puede abrir una PC (ver
        # miembros_repo.abrir_estacion_por_miembro): el tiempo no se pierde,
        # se le suma a lo próximo que cargue.
        "con_poco_saldo": [socio["usuario"] for socio in nuevos
                           if socio["tiempo_sin_entender"] is None
                           and socio["minutos"] < miembros_repo.MINUTOS_POR_FRACCION],
        "ya_existen": list(plan["ya_existen"]),
        "con_problemas": list(plan["con_problemas"]),
    }


def _texto(valor) -> str:
    """Una celda como texto. Una clave o un usuario de puros números que Excel
    guardó como número ("123456") vuelve sin el ".0"."""
    if valor is None:
        return ""
    if isinstance(valor, float):
        return str(int(valor)) if valor.is_integer() else str(valor)
    return str(valor)


# ---------------------------------------------------------------------------
# Lectura del .xlsx
# ---------------------------------------------------------------------------

def _que_dato_es(titulo):
    """Qué dato trae una columna según su título, o None si no interesa.
    "usuario" se mira primero: "Nombre de usuario" es el usuario, no el nombre."""
    if not isinstance(titulo, str):
        return None
    titulo = _sin_acentos(titulo).strip().lower()
    if "usuario" in titulo:
        return "usuario"
    if titulo.startswith(("contrasena", "clave", "password")):
        return "clave"
    if titulo.startswith("nombre"):
        return "nombre"
    if titulo.startswith("tiempo"):
        return "tiempo"
    return None


def _sin_acentos(texto: str) -> str:
    return "".join(letra for letra in unicodedata.normalize("NFD", texto) if unicodedata.category(letra) != "Mn")


def _socios_de_la_planilla(ruta: str) -> list:
    """Los renglones que siguen a los títulos, en la primera hoja que los
    tenga: [{"fila", "usuario", "clave", y si hay esas columnas "nombre" y
    "tiempo"}], con lo que trae cada celda tal cual."""
    for hoja in _leer_hojas(ruta):
        for posicion, (_numero, renglon) in enumerate(hoja):
            columnas = {}
            for columna, titulo in sorted(renglon.items()):
                dato = _que_dato_es(titulo)
                if dato and dato not in columnas.values():
                    columnas[columna] = dato
            if {"usuario", "clave"} <= set(columnas.values()):
                return [
                    {"fila": numero, **{dato: celdas.get(columna) for columna, dato in columnas.items()}}
                    for numero, celdas in hoja[posicion + 1:]
                ]
    raise ValueError('La planilla no tiene los títulos "Usuario" y "Contraseña" en un mismo renglón.')


def _leer_hojas(ruta: str) -> list:
    """Cada hoja del libro como una lista de (número de fila, {número de
    columna: valor}). Un texto llega como str y un número como float."""
    try:
        with zipfile.ZipFile(ruta) as libro:
            nombres = libro.namelist()
            textos = _textos_compartidos(libro) if "xl/sharedStrings.xml" in nombres else []
            hojas = sorted(
                (nombre for nombre in nombres if re.fullmatch(r"xl/worksheets/sheet\d+\.xml", nombre)),
                key=lambda nombre: int(re.search(r"\d+", nombre).group()),
            )
            return [_renglones(ET.fromstring(libro.read(hoja)), textos) for hoja in hojas]
    except (OSError, zipfile.BadZipFile, ET.ParseError, KeyError, IndexError, ValueError):
        raise ValueError(
            "No se pudo leer la planilla. Tiene que ser un archivo de Excel (.xlsx); si es un .xls "
            "viejo, abrilo con Excel y guardalo como .xlsx."
        )


def _textos_compartidos(libro) -> list:
    """Excel guarda cada texto una sola vez en sharedStrings.xml y la celda
    dice qué número de texto es."""
    raiz = ET.fromstring(libro.read("xl/sharedStrings.xml"))
    return ["".join(t.text or "" for t in si.iter(_NS + "t")) for si in raiz.findall(_NS + "si")]


def _renglones(hoja, textos: list) -> list:
    renglones = []
    for fila in hoja.iter(_NS + "row"):
        numero = int(fila.get("r") or len(renglones) + 1)
        celdas = {}
        columna = 0
        for celda in fila.findall(_NS + "c"):
            columna = _numero_de_columna(celda.get("r")) or columna + 1
            valor = _valor_de_celda(celda, textos)
            if valor is not None:
                celdas[columna] = valor
        renglones.append((numero, celdas))
    return renglones


def _numero_de_columna(referencia):
    """"C12" → 3. None si la celda no dice dónde está (Excel siempre lo dice;
    otros programas que guardan .xlsx a veces no)."""
    letras = re.match(r"[A-Z]+", referencia or "")
    if letras is None:
        return None
    numero = 0
    for letra in letras.group():
        numero = numero * 26 + ord(letra) - ord("A") + 1
    return numero


def _valor_de_celda(celda, textos: list):
    tipo = celda.get("t", "n")
    if tipo == "inlineStr":
        return "".join(t.text or "" for t in celda.iter(_NS + "t"))
    valor = celda.find(_NS + "v")
    if valor is None or valor.text is None:
        return None
    if tipo == "s":
        return textos[int(valor.text)]
    if tipo == "n":
        return float(valor.text)
    if tipo == "e":  # #N/A, #DIV/0!...
        return None
    return valor.text  # "str" (lo que dio una fórmula) o "b"
