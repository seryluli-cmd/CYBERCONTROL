# Administrar CyberBIOS desde otra PC del local

**Programado el 18/10/2026** (antes era la propuesta de este mismo archivo).
Si lo querés revisar con ChatGPT, este archivo se puede adjuntar tal cual.

## Lo que pediste

> "Desde la PC de mi casa entro con UltraVNC a otra PC que no está en uso, y con
> esa PC accedo al programa por red, me logueo como admin y de ahí hago las
> modificaciones que quiera hacer, o miro reportes, controlo, etc. Esto sin
> interrumpir a la operadora que está trabajando en ese momento, tal vez
> habilitando PCs y esas cosas."

## Cómo quedó

- **Una sola vez, en el mostrador:**
  1. Configuración ADMIN > **Entrar desde otra PC**: tildar "Permitir que el
     Administrador entre desde otra PC" y Guardar. Viene **apagado**.
  2. Compartir en la red la carpeta donde está CyberBios.exe (con contraseña).
     La pantalla del paso 1 dice el nombre y la IP del mostrador.
- **Cada vez, en la PC libre:** abrir CyberBios.exe **desde la carpeta
  compartida** (por ejemplo `\\MOSTRADOR\CyberBios\CyberBios.exe`) y entrar con
  el usuario Administrador y su clave.
- El programa se da cuenta solo de que lo abriste por la red. Esa copia **no
  abre ninguna base**: cada vez que una pantalla necesita un dato o guarda algo,
  se lo pide al CyberBIOS del mostrador por la red del local (el mismo camino
  que ya usan las PCs del cyber, puerto 8899). El único que toca la base es el
  mostrador, como siempre.
- En la otra PC la ventana principal muestra un cartel ("Estás administrando
  desde otra PC...") en lugar de la grilla de PCs, y arriba el número de la caja
  abierta en el mostrador.
- La operadora no ve nada ni se le traba la pantalla.

### Qué se puede hacer desde la otra PC

- **Administrar Kiosko completo:** Artículos (y precios), Compras, Consulta de
  Ventas **con anular**, Reportes, Control de Cierres (con la carga de lo contado
  en el sobre) y Usuarios.
- **Configuración ADMIN:** estaciones, los cuatro catálogos de bonos, tarifa de
  socios, trámites, Accesos de Admin, fondo y filtro de palabras de las PCs.
- **Caja** (solo mirar) y **Clave** (cambiar la propia).

### Qué sigue solo en el mostrador

Vender, cobrar (bonos, trámites, carga de saldo), Cierre de Turno y las cajas,
la grilla de PCs, Miembros, Actualizar el Cliente PC (se
firma con la clave que vive en la PC del mostrador), Copia de Seguridad y prender
o apagar la entrada desde otra PC. El cierre forzoso de la caja también lo hace
solo el mostrador.

## Las decisiones que salieron de tu respuesta

1. **Pantallas:** "hago las modificaciones que quiera hacer" → todo lo de
   administración (Administrar Kiosko + Configuración ADMIN), con anular ventas.
2. **Desde qué PC:** "otra PC que no está en uso" (no siempre la misma) → desde
   **cualquier PC del local**, con la clave del Administrador. No se ata a una IP
   fija.
3. **Copia diaria de la base en la otra PC:** no se hizo. Con una PC que cambia
   y no queda prendida, no tiene sentido; la copia diaria la sigue haciendo el
   mostrador en su propia PC.

## Por qué así y no "abriendo la base por la carpeta compartida"

La base (SQLite) no está hecha para que dos PCs la escriban por la red: si las
dos guardan justo a la vez, **se puede dañar el archivo con todas las ventas**.
Por eso, aunque abras el .exe desde la carpeta compartida, el programa nunca
abre la base de esa carpeta: le habla al programa del mostrador.

## Seguridad (dicho sin exagerar)

- Solo entra un usuario **Administrador** activo, con su clave. Una empleada no
  entra, ni siquiera con permisos de encargada.
- Viene **apagado**. Apagarlo en el mostrador corta en el acto a quien estaba
  adentro desde otra PC.
- **5 claves mal seguidas desde una PC** dejan a esa PC sin poder probar por 5
  minutos (las demás PCs no se afectan), y cada PC prueba de a una clave por
  vez. Además hay un tope para todas las PCs juntas: con 20 claves mal en 15
  minutos, nadie puede entrar desde otra PC hasta que pase ese rato (en el
  mostrador se sigue entrando normal). Alguien podría usar eso para no dejarte
  entrar desde otra PC un rato; nunca para entrar.
- La sesión vale solo desde la PC que entró, vence a las 3 horas sin uso y se
  pierde si se cierra el programa del mostrador. Ojo: con la ventana abierta en
  la otra PC cuenta como "en uso" (mira la caja cada 10 segundos). **Al
  terminar, cerrá sesión o cerrá el programa**, sobre todo si es una PC del
  cyber: si no, el próximo cliente de esa PC la encontraría abierta.
- Solo se pueden pedir las funciones de una **lista cerrada**; cualquier otra se
  rechaza aunque venga con la clave del Administrador.
- **Quién hizo cada cosa** (quién anuló, quién cargó la compra o el sobre) lo
  anota el mostrador con el Administrador que entró, no con lo que mande la otra
  PC.
- Cada ingreso queda en **Accesos de Admin**, con la IP de la PC desde donde se
  entró.
- El hash de las claves nunca sale del mostrador.
- **Límite honesto:** dentro de la red del local la clave viaja sin cifrar
  (igual que hoy lo que hablan las PCs con el mostrador). Alguien que logre
  espiar la red del local podría verla. Como se puede entrar desde cualquier PC
  del local (incluidas las del cyber), **la clave del Administrador tiene que ser
  buena** (no 1234, ni el nombre, ni una fecha). Nada de esto queda abierto a
  internet: desde tu casa seguís entrando por UltraVNC.

## Qué pasa si...

- **El mostrador está apagado o con CyberBIOS cerrado:** la otra PC avisa "No
  encuentro el CyberBIOS del mostrador". Lo que ya guardaste quedó guardado.
- **Se corta la red con la sesión abierta:** cada acción avisa que no encuentra
  el mostrador; cuando vuelve la red, sigue andando (si pasaron más de 3 horas,
  hay que cerrar sesión y volver a entrar).
- **Se reinicia el programa del mostrador:** la sesión de la otra PC se pierde;
  la próxima acción avisa "La sesión desde esta PC se cerró": cerrás sesión y
  volvés a entrar.
- **Cambiás un precio mientras ella tiene ese artículo en el carrito:** ese
  cliente paga el precio viejo; el próximo escaneo trae el nuevo (igual que hoy).
- **Cargás una compra mientras ella vende ese artículo:** el stock queda bien
  (cada operación se guarda entera, una detrás de la otra).
- **El .exe del mostrador y el de la otra PC no son el mismo:** no deja entrar
  y avisa. Abriéndolo siempre desde la carpeta compartida, son el mismo.
- **Sacás un reporte de un año:** lo medí con una base de prueba de un año
  (110.000 ventas): todos los reportes tardan menos de 0,2 segundos, así que la
  venta del mostrador ni lo nota. Al medir apareció un problema que **ya
  existía**: Reportes > Por Operador tardaba **6 minutos** con un año de ventas
  (también en el mostrador). Se arregló con un índice y ahora tarda 0,2 s.
- **Windows pregunta si querés ejecutar el archivo** al abrirlo desde la red:
  decile que sí.

## Cómo se probó

- 55 pruebas automáticas nuevas (`tests/test_admin_remoto.py`): sin clave o con
  la de una empleada no se entra; con la entrada apagada tampoco; una función
  fuera de la lista se rechaza; la sesión no sirve desde otra PC; las 5 claves
  mal (también mandadas todas juntas, o desde varias PCs); quién anula es quien entró; el hash no viaja; y una **copia remota de
  verdad** contra un **mostrador de prueba en otro proceso** (con una base de
  prueba, nunca la real): abre todas las pantallas de administración sin
  errores, cambia un precio, carga una compra, anula una venta, carga un sobre,
  cambia el fondo de las PCs, y todo queda en la base del mostrador; esa copia
  nunca crea una base propia.
- Una prueba revisa las pantallas que se abren desde otra PC: si alguna empieza
  a usar una función que no está en la lista, falla y dice cuál.
- La suite completa del programa sigue pasando (723 pruebas).

## Para probarlo en el local

1. Armar el .exe nuevo y ponerlo en el mostrador (con un Cierre de Turno justo
   antes, como siempre que se cambia el programa).
2. En el mostrador: Configuración ADMIN > Entrar desde otra PC > prender.
3. Compartir la carpeta del CyberBios.exe.
4. Desde una PC libre: abrir el .exe desde la carpeta compartida, entrar como
   Administrador, cambiar el precio de un artículo de prueba y fijarse en el
   mostrador que cambió. Mirar Accesos de Admin: tiene que figurar "Otra PC
   (IP)".

---

## Anexo técnico (para revisar con ChatGPT)

- `admin_remoto/modo.py`: copia remota si `database.BASE_DIR` es una ruta
  `\\PC\carpeta` (o `\\?\UNC\...`) o una unidad de red (`GetDriveTypeW` =
  `DRIVE_REMOTE` → `WNetGetConnectionW`); la PC es la de la ruta. Para probar:
  `--mostrador <ip>`.
- `admin_remoto/cliente.py`: `instalar()` cierra la base local (reemplaza
  `conexion_db`/`get_connection` en `database` y en todo módulo que se trajo su
  referencia), manda `DATA_DIR` (solo el log de errores) a `%LOCALAPPDATA%` y
  reemplaza en su módulo cada función de la lista blanca por un representante
  que hace `POST /admin/llamar`. `listar_usuarios`/`autenticar_por_nombre`
  antes de entrar van por `/admin/usuarios` y `/admin/entrar`. Errores:
  `ValueError`/`PermissionError` del mostrador llegan con su mensaje; sin red,
  `SinConexion` (un `ValueError`).
- `admin_remoto/servidor.py` (lo llama `servidor_red.do_POST` para `/admin/`,
  antes del control de la clave de los Clientes PC): token
  `secrets.token_urlsafe(32)` en memoria, atado a la IP del socket, vence a los
  180 min sin uso; bloqueo por IP tras 5 claves mal (5 min), una prueba de clave
  a la vez por IP, un bloqueo nunca se acorta, y tope global de 20 claves mal en
  15 min (revisión de seguridad del 2026-10-18); en cada llamada,
  `admin_remoto_repo.exigir_admin_habilitado`; `inspect.signature(...).bind` de
  los argumentos y el `ACTOR` se pisa con el usuario del token; tope de 16 MB
  por pedido; nunca loguea claves ni cuerpos.
- `admin_remoto/codec.py`: JSON con etiquetas de una clave (`__t` tupla, `__s`
  conjunto, `__d` diccionario con claves no-texto, `__r` fila, `__dt`/`__da`
  fechas, `__b` bytes en base64). Del otro lado solo se arman esos tipos.
  `FilaRemota` se comporta como `sqlite3.Row`. `clave_hash` sale vacío.
- `admin_remoto/lista_blanca.py`: `FUNCIONES` (módulo → nombres), `ACTOR`
  ((módulo, función) → parámetro) y `huella()` (sha256 de la lista, las firmas y
  los actores + versión del protocolo; se compara en `/admin/hola`, `usuarios` y
  `entrar`).
- Esquema: `sesiones.desde_ip` (migración idempotente) e índice
  `idx_venta_pagos_venta`.
- Concurrencia: el servidor corre en hilos con conexiones propias (como los
  pedidos de las PCs); SQLite sin WAL, así que una lectura larga frena una
  escritura del mostrador hasta 5 s (timeout por defecto) — por eso se midieron
  los reportes con un año de datos.
