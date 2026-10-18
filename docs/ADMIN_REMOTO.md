# Administrar CyberBIOS desde otra PC (propuesta)

Borrador del 18/10/2026 para que lo revises (si querés, con ChatGPT). Todavía
no está programado: primero necesito tus respuestas a las 3 preguntas del final.

## Lo que pediste

Hoy, para cargar mercadería o cambiar precios, usás la misma PC del mostrador
(por UltraVNC) y le trabás la pantalla a la empleada. Querés lo mismo que en el
otro local: **una PC atiende y en otra administrás vos**, a la vez y sin
molestarse.

La PC para administrar sería el servidor de archivos (el que no tiene monitor),
al que entrás desde tu casa por UltraVNC.

## Cómo funcionaría

- En el servidor va **una copia del mismo CyberBios.exe**, con un archivito al
  lado que dice "esta copia es para administrar, y el mostrador está en la IP
  tal". Te lo dejo armado; vos solo ponés la IP del mostrador.
- Esa copia **no tiene base de datos propia**. Cada vez que abrís una pantalla o
  apretás Guardar, le pide el dato al CyberBIOS del mostrador por la red del
  local (por el mismo camino que ya usan las 40 PCs). El que guarda siempre es
  el mostrador, en su base de siempre. **Las ventas y la plata siguen en un
  solo lugar.**
- Entrás con tu usuario Administrador y tu clave de siempre. Ves las pantallas
  de administración (las que elijas en la pregunta 1), iguales a las de ahora.
- La empleada sigue vendiendo en el mostrador como si nada: no se le abre
  ninguna ventana ni se le traba la pantalla.

### Por qué así y no "compartiendo la carpeta de la base"

Lo más fácil parecería abrir la misma base desde las dos PCs por una carpeta
compartida. No conviene: esta base (SQLite) no está hecha para que dos PCs la
escriban por la red, y si dos guardan justo a la vez **se puede dañar el archivo
con todas las ventas**. Con lo que propongo, el único que toca la base es el
mostrador, como hoy.

## Lo que la copia del servidor NO hace

- No vende ni cobra, no abre ni cierra cajas, no hace cierres de turno (no hay
  cajón ahí).
- No atiende a las PCs del cyber (eso lo sigue haciendo solo el mostrador).
- No hace la copia de seguridad automática diaria del mostrador ni el cierre
  forzoso de la caja: eso sigue en el mostrador.
- Lo que hace no puede saltearse las reglas: es el mismo programa del mostrador
  el que guarda, con los mismos controles (precios, stock, permisos).

## Qué pasa si...

- **El mostrador está apagado o con CyberBIOS cerrado:** la copia del servidor
  avisa "no encuentro el programa del mostrador" y no deja hacer nada. Todo lo
  que ya guardaste quedó guardado; lo que estabas tocando y no guardaste, no.
- **Cambiás un precio mientras ella tiene ese artículo ya escaneado en el
  carrito:** ese cliente paga el precio viejo (como hoy si lo cambiás entre dos
  ventas); el próximo escaneo ya trae el precio nuevo.
- **Cargás una compra mientras ella vende ese mismo artículo:** el stock queda
  bien (cada operación se guarda entera, una detrás de la otra).
- **Actualizás el CyberBios.exe del mostrador y no el del servidor:** la copia
  del servidor avisa que son versiones distintas y no deja entrar hasta que
  copies el mismo .exe en las dos.
- **Sacás un reporte muy grande:** la venta del mostrador puede esperar un
  instante mientras se arma (hoy pasa lo mismo si lo sacás en el mostrador).
  Lo voy a medir con una base de prueba de un año antes de darlo por bueno.

## Seguridad (dicho sin exagerar)

- Para entrar hace falta el usuario **Administrador** y su clave. Una empleada,
  aunque tenga permisos de encargada, no entra desde otra PC.
- 5 claves mal seguidas bloquean un minuto, como en el login de siempre.
- Solo se puede hacer lo de la lista de pantallas que elijas: nada de "cualquier
  cosa por la red".
- Viene **apagado**: no cambia nada hasta que lo prendas desde Configuración
  ADMIN en el mostrador.
- Límite honesto: dentro de la red del local la clave viaja sin cifrar (igual que
  hoy lo que hablan las PCs con el mostrador). Alguien que logre espiar la red
  del local podría verla. Por eso recomiendo además la pregunta 2.
- Nada de esto queda abierto a internet: desde tu casa seguís entrando al
  servidor por UltraVNC, y es el servidor el que habla con el mostrador dentro
  del local.

## Las 3 cosas que necesito que decidas

**1. ¿Qué pantallas querés desde el servidor?**
- (a) **Recomendado para arrancar:** todo "Administrar Kiosko": Artículos (y
  precios), Compras, Consulta de Ventas, Reportes, Control de Cierres y
  Usuarios. Más "Caja" para mirar cómo va la caja abierta (solo mirar).
- (b) Lo de (a) y además "Configuración ADMIN" (bonos, tarifa de socios,
  trámites, estaciones, filtro de palabras, fondo de las PCs). Se puede, lleva
  más trabajo; lo haría en una segunda tanda.
- Dentro de Consulta de Ventas: **¿querés poder ANULAR ventas desde el
  servidor?** (yo diría que sí: es lo mismo que hacés hoy por UltraVNC).
- "Limpiar base de datos" y "Actualizar el Cliente PC de las PCs" los dejaría
  solo en el mostrador.

**2. ¿Desde qué PC se puede entrar?**
- (a) **Recomendado:** solo desde el servidor. En el mostrador se anota la IP
  del servidor y cualquier otra PC (por ejemplo, la de un cliente del cyber que
  sepa tu clave) queda afuera aunque tenga la clave. Para esto el servidor
  tiene que tener **IP fija** (como las PCs del cyber).
- (b) Desde cualquier PC de la red del local, con la clave de Administrador.

**3. Copia de seguridad en el servidor**
- Hoy, "Copia de Seguridad" (en Usuarios) guarda la base en una carpeta de la PC
  donde estás. Desde el servidor, guardaría una copia de la base del mostrador
  en el servidor. ¿Querés además que **la copia del servidor guarde sola una
  copia por día** de la base del mostrador? Así, si se rompe el disco del
  mostrador, la base está también en otra PC.

## Cómo lo voy a probar

- Pruebas automáticas nuevas: que sin clave o con la de una empleada no se
  entre, que desde otra IP no se entre (si elegís 2a), que una función fuera de
  la lista sea rechazada, que cambiar un precio, cargar una compra y sacar un
  reporte desde la otra copia quede igual que hecho en el mostrador, y que la
  copia del servidor nunca cree una base propia.
- Prueba con dos copias abiertas a la vez (una de mostrador vendiendo, otra de
  administración cambiando precios y cargando una compra), con una base de
  prueba, nunca con la real.
- La suite completa de pruebas del programa tiene que seguir pasando.

---

## Anexo técnico (para revisar con ChatGPT)

- La copia remota reemplaza, al arrancar, cada módulo de `repositories/` (y los de
  `control_pcs/repositories/` que use) por un "representante" que manda la
  llamada por HTTP al mostrador: `POST /admin/llamar` en el puerto 8899, el mismo
  `ThreadingHTTPServer` de los Clientes PC, en un módulo propio (el servidor de
  hoy ya pasa las 600 líneas). La pantalla no se entera: sigue llamando a
  `articulos_repo.modificar_articulo(...)`.
- En la copia remota, `database.conexion_db` queda bloqueada a propósito: si
  alguna pantalla quisiera tocar una base local, falla con un mensaje claro en vez
  de crear una base vacía.
- Lista blanca explícita (módulo + función) del lado del mostrador. Las filas de
  SQLite viajan como JSON y del otro lado se rearman con un objeto que se lee
  igual que `sqlite3.Row` (por nombre y por posición). Los errores pensados para
  el usuario (`ValueError`, `PermissionError`) viajan con su mensaje y se
  muestran igual que hoy.
- Login: `POST /admin/login` con usuario y clave; el mostrador verifica que sea
  ADMIN activo y devuelve un token al azar que vive solo en memoria (se pierde al
  cerrar el programa del mostrador y vence por inactividad). Cada llamada
  re-verifica que el usuario siga activo y siendo Admin. El hash de la clave no
  viaja nunca a la otra PC.
- El "usuario" que mandan las pantallas a los repos (quién cargó la compra, quién
  anuló) lo pone el mostrador a partir del token, no se confía en lo que manda la
  copia remota.
- Versión: las dos copias calculan una huella de la lista blanca y de las firmas
  de esas funciones; si no coinciden, no se entra.
- La copia remota no arranca `servidor_red.iniciar_servidor`, ni
  `hacer_backup_automatico`, ni el temporizador del cierre forzoso.
- El servidor del mostrador no toca Qt (corre en los hilos del servidor, con
  conexiones SQLite propias, como hoy los pedidos de las PCs).
