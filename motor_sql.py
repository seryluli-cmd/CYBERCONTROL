"""
motor_sql.py
============
Qué módulo de SQLite usa el programa. Es el ÚNICO lugar donde se elige.

Si está instalado `sqlcipher3` (siempre, en el CyberBios.exe), se usa ese: es
SQLite con el cifrado adentro, igual en todo lo demás (mismas consultas, mismas
filas, mismas excepciones con los mismos nombres). Si no está (una PC de
desarrollo que no lo instaló), se usa el `sqlite3` común, que no sabe cifrar y
solo sirve mientras no haya clave (ver database.py, "Cifrado de la base").

Los demás archivos hacen `from motor_sql import sqlite3` en vez de `import
sqlite3`. No es un capricho: `sqlcipher3` trae sus propias clases de error, y un
`except sqlite3.IntegrityError` escrito contra el módulo común NO atraparía el
error de una base abierta con `sqlcipher3` (son clases distintas, aunque se
llamen igual): la venta quedaría sin validar y el programa mostraría el cartel
de "error inesperado". Con este alias, todo el programa habla con el mismo módulo.
"""

try:
    from sqlcipher3 import dbapi2 as sqlite3
    PUEDE_CIFRAR = True
except ImportError:  # una PC sin sqlcipher3: sigue andando, pero sin poder cifrar
    import sqlite3
    PUEDE_CIFRAR = False

__all__ = ["sqlite3", "PUEDE_CIFRAR"]
