"""
tests/cifrado_de_prueba.py
===========================
Para correr TODA la suite con la base cifrada (la forma en que anda el
CyberBios.exe del dueño) en vez de con la base común:

    set CYBERCONTROL_PRUEBAS_CIFRADAS=1
    python -m unittest discover tests

Sin esa variable las pruebas siguen con la base común, como siempre. La clave de
abajo NO es un secreto: solo existe para las pruebas (la verdadera no está en el
repo, ver CLAUDE.md, "La base de datos va cifrada").

No se llama test_*.py para que unittest no lo tome como una prueba.
"""

import os

import database

CLAVE_DE_PRUEBA = "5f" * 32


def activar_si_corresponde():
    if os.environ.get("CYBERCONTROL_PRUEBAS_CIFRADAS") == "1":
        database.CLAVE_HEX = CLAVE_DE_PRUEBA
