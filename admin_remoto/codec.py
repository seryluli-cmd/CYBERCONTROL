"""
codec.py
=========
Cómo viajan por la red los datos de una llamada (lo que le pasa la pantalla al
repo, y lo que el repo le devuelve) entre la copia remota y el mostrador.

JSON solo sabe de textos, números, listas y diccionarios con claves de texto.
Los repos devuelven más cosas: filas de SQLite (que se leen por nombre Y por
posición), tuplas (`buscar_venta` devuelve tres cosas), conjuntos, fechas,
diccionarios con claves que no son texto e imágenes (el fondo de las PCs). Cada
una viaja como un diccionario de UNA sola clave que empieza con "__" (por
ejemplo {"__t": [...]} es una tupla) y del otro lado se rearma igual.

Del otro lado nunca se arma nada que no sea uno de esos tipos: un pedido no
puede hacer que el mostrador cree un objeto cualquiera ni corra código.

Una fila llega como `FilaRemota`, que se lee igual que `sqlite3.Row`
(fila["nombre"], fila[0], dict(fila), for valor in fila). Las columnas de
`COLUMNAS_QUE_NO_VIAJAN` (los hashes de las claves) salen vacías: a la otra PC
no le hacen falta y no tienen por qué andar por la red.
"""

import base64
from motor_sql import sqlite3
from datetime import date, datetime

# Columnas que nunca salen del mostrador, aunque una función devuelva la fila
# entera (listar_usuarios trae todo). Llegan como texto vacío.
COLUMNAS_QUE_NO_VIAJAN = frozenset({"clave_hash"})

_TUPLA, _CONJUNTO, _DICCIONARIO, _FILA = "__t", "__s", "__d", "__r"
_FECHA_HORA, _FECHA, _BYTES = "__dt", "__da", "__b"
_ETIQUETAS = frozenset({_TUPLA, _CONJUNTO, _DICCIONARIO, _FILA, _FECHA_HORA, _FECHA, _BYTES})


class FilaRemota:
    """
    Una fila de la base que llegó por la red. Se usa igual que `sqlite3.Row`:
    por nombre de columna (sin distinguir mayúsculas, como SQLite), por
    posición, con `keys()`, con `dict(fila)` y recorriéndola (da los valores,
    no los nombres, igual que sqlite3.Row).
    """

    __slots__ = ("_columnas", "_valores", "_indice")

    def __init__(self, columnas, valores):
        self._columnas = tuple(columnas)
        self._valores = tuple(valores)
        if len(self._columnas) != len(self._valores):
            raise ValueError("Fila mal armada.")
        self._indice = {}
        for posicion, columna in enumerate(self._columnas):
            self._indice.setdefault(columna, posicion)
            self._indice.setdefault(columna.lower(), posicion)

    def keys(self):
        return list(self._columnas)

    def __getitem__(self, clave):
        if isinstance(clave, str):
            posicion = self._indice.get(clave)
            if posicion is None:
                posicion = self._indice.get(clave.lower())
            if posicion is None:
                raise IndexError(f"No existe la columna {clave!r}")
            return self._valores[posicion]
        return self._valores[clave]

    def __iter__(self):
        return iter(self._valores)

    def __len__(self):
        return len(self._valores)

    def __eq__(self, otra):
        if isinstance(otra, FilaRemota):
            return self._columnas == otra._columnas and self._valores == otra._valores
        return NotImplemented

    def __hash__(self):
        return hash((self._columnas, self._valores))

    def __repr__(self):
        return f"FilaRemota({dict(zip(self._columnas, self._valores))!r})"


def a_json(valor):
    """`valor` convertido en algo que json.dumps acepta (ver el comentario del
    módulo). TypeError si trae un tipo que no sabe mandar: mejor un error
    claro que un dato que llega cambiado."""
    if valor is None or isinstance(valor, (bool, int, float, str)):
        return valor
    if isinstance(valor, list):
        return [a_json(item) for item in valor]
    if isinstance(valor, tuple):
        return {_TUPLA: [a_json(item) for item in valor]}
    if isinstance(valor, (set, frozenset)):
        return {_CONJUNTO: [a_json(item) for item in valor]}
    if isinstance(valor, (sqlite3.Row, FilaRemota)):
        columnas = list(valor.keys())
        valores = ["" if columna in COLUMNAS_QUE_NO_VIAJAN else a_json(valor[columna]) for columna in columnas]
        return {_FILA: [columnas, valores]}
    if isinstance(valor, dict):
        if all(isinstance(clave, str) for clave in valor) and not (len(valor) == 1 and next(iter(valor)) in _ETIQUETAS):
            return {clave: a_json(item) for clave, item in valor.items()}
        return {_DICCIONARIO: [[a_json(clave), a_json(item)] for clave, item in valor.items()]}
    # datetime antes que date: un datetime también es un date.
    if isinstance(valor, datetime):
        return {_FECHA_HORA: valor.isoformat()}
    if isinstance(valor, date):
        return {_FECHA: valor.isoformat()}
    if isinstance(valor, (bytes, bytearray)):
        return {_BYTES: base64.b64encode(bytes(valor)).decode("ascii")}
    raise TypeError(f"No se puede mandar por la red un dato de tipo {type(valor).__name__}.")


def de_json(valor):
    """Lo contrario de a_json: rearma tuplas, filas, fechas, etc."""
    if isinstance(valor, list):
        return [de_json(item) for item in valor]
    if not isinstance(valor, dict):
        return valor
    if len(valor) == 1:
        etiqueta, contenido = next(iter(valor.items()))
        if etiqueta == _TUPLA:
            return tuple(de_json(item) for item in contenido)
        if etiqueta == _CONJUNTO:
            return {de_json(item) for item in contenido}
        if etiqueta == _DICCIONARIO:
            return {_clave_hashable(de_json(clave)): de_json(item) for clave, item in contenido}
        if etiqueta == _FILA:
            columnas, valores = contenido
            return FilaRemota([str(columna) for columna in columnas], [de_json(item) for item in valores])
        if etiqueta == _FECHA_HORA:
            return datetime.fromisoformat(contenido)
        if etiqueta == _FECHA:
            return date.fromisoformat(contenido)
        if etiqueta == _BYTES:
            return base64.b64decode(contenido)
    return {clave: de_json(item) for clave, item in valor.items()}


def _clave_hashable(clave):
    """Una lista no puede ser clave de un diccionario: si llegara una (un dato
    mal armado), se corta con un error claro en vez de un TypeError suelto."""
    if isinstance(clave, list):
        raise ValueError("Pedido inválido.")
    return clave
