# Guía de trabajo para agentes — CYBERCONTROL

La referencia vigente del proyecto es [CLAUDE.md](CLAUDE.md). Leela antes de
modificar código: contiene las 15 reglas, los puntos únicos de verdad, las
trampas del negocio y lo que el dueño pidió no cambiar sin hablarlo.
[README.md](README.md) describe los módulos actuales y
[LEEME.txt](LEEME.txt) explica el uso para el mostrador.
La cronología anterior se conserva en [docs/HISTORIAL.md](docs/HISTORIAL.md).

Reglas esenciales:
- La UI no escribe SQL ni abre conexiones. Los repositorios contienen las
  reglas de negocio; `database.py` administra conexiones, claves y copias;
  `database_esquema.py` crea tablas e índices, y `database_migraciones.py`
  actualiza bases anteriores.
- Kiosko y Control de PCs mantienen sus dos árboles de carpetas separados.
- Los estados, tipos de movimiento y orígenes viven en dominio.py.
- Cada operación que mueve plata, saldo o stock se guarda en una transacción.
- No toques data/ ni la base real para desarrollar o probar. Los tests usan
  bases temporales.
- Verificá con python -m unittest discover tests y abrí Login y la ventana
  principal con una base temporal antes de declarar listo un cambio.
- La UI, los comentarios, los commits y las explicaciones al dueño van en
  español rioplatense.
