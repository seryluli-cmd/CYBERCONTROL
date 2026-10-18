"""
admin_remoto
=============
Administrar CyberBIOS desde otra PC del local mientras el mostrador sigue
atendiendo (pedido del dueño, 2026-10-18: entra desde su casa por UltraVNC a
una PC libre del local, abre el programa por la red y administra sin molestar
a la operadora).

Cómo funciona, en una línea: la copia que se abre en la otra PC no tiene base
propia; cada vez que una pantalla llama a un repo, la llamada viaja al
CyberBIOS del mostrador (el mismo servidor de red de las PCs, puerto 8899,
rutas /admin/...), que la hace con SU base y devuelve el resultado. La base
sigue siendo un solo archivo que toca un solo programa.

- `modo`: decide si esta copia es la del mostrador o una "copia remota" (el
  .exe abierto desde la carpeta compartida del mostrador).
- `codec`: cómo viajan los datos (filas, fechas, imágenes) por JSON.
- `lista_blanca`: las únicas funciones que se pueden pedir desde otra PC.
- `servidor`: lo que atiende el mostrador (entrada con clave, sesiones, llamadas).
- `cliente`: lo que hace la copia remota (conectarse y reemplazar los repos
  por "representantes" que mandan la llamada al mostrador).

La regla de quién puede entrar (solo un Administrador, y solo si el dueño lo
prendió en el mostrador) vive en repositories/admin_remoto_repo.py.

Por qué NO se abre la base por la carpeta compartida: SQLite no está hecho para
que dos PCs escriban el mismo archivo por la red; si las dos guardan a la vez,
se puede dañar el archivo con todas las ventas.
"""
