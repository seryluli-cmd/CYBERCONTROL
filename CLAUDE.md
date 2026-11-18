# Guía de trabajo para Claude — Sistema de Kiosko

## Por qué existe este archivo

El programa sigue creciendo y conviene mantenerlo ordenado. El pedido del
dueño es explícito: **ordenarlo ahora, mientras es barato**, para que
sumar un módulo nuevo el año que viene no obligue a tocar media docena
de archivos ni rompa algo que ya funcionaba.

La buena noticia es que la base ya está bien puesta: hay tres capas
separadas de verdad y `ui/` no tiene una sola línea de SQL. Las reglas de
abajo no son un plan de refactor: son **el contrato para que eso siga
siendo cierto** cuando el programa tenga el triple de tamaño.

---

## La arquitectura en una línea

```
main.py  →  ui/  →  repositories/  →  database.py  →  data/kiosko.db
           (qué       (reglas de       (esquema y
            se ve)     negocio)         conexión)

        dominio.py  ·  turnos.py     ← los usa cualquier capa
     (nombres fijos)  (calendario)      (no importan nada del programa)
```

**La flecha va en un solo sentido y nunca al revés.** Un repo jamás
importa nada de `ui/`. `database.py` no sabe que existen las pantallas.

`dominio.py` y `turnos.py` están fuera de la fila a propósito: son
funciones y constantes puras, sin base de datos ni Qt, así que las puede
usar cualquier capa sin ensuciar la dirección de las flechas.

**Dos negocios, un solo programa.** Desde el 2026-09-26, Control de
PCs/Miembros/Bonos/Historiales vive en su propio paquete `control_pcs/`
(con su propio `ui/` y `repositories/` adentro), separado del `ui/` y
`repositories/` de arriba que quedan solo para el negocio de kiosko —
son dos negocios distintos para el dueño, aunque comparten programa,
login y base de datos. Ver "Qué no cambiar sin que el dueño lo pida
explícitamente" más abajo.

---

## Antes de tocar código: leé la guía del área

Este archivo tiene solo lo que vale siempre. Las funciones que ya resuelven
algo ("puntos únicos de verdad") y las trampas conocidas están en
`docs/guia/`, un archivo por área. **Antes de cambiar algo, leé entera la guía
de su área** (si el cambio toca dos áreas, las dos): ahí está lo que ya se
resolvió y lo que se rompe si no lo sabés.

| Si vas a tocar... | Leé |
|---|---|
| turnos, cajas, Cierre de Turno, Control de Cierres, Resumen y Detalle del Día, Historial del Turno, reportes por operador, el envío de cierres a la app de gastos | [docs/guia/TURNOS_Y_CAJA.md](docs/guia/TURNOS_Y_CAJA.md) |
| Venta de Mercadería, la ventana de cobro, cómo se muestra o se escribe la plata, artículos, stock, marcas, Impresiones, Trámites, anular ventas, un origen de venta nuevo | [docs/guia/VENTAS_Y_ARTICULOS.md](docs/guia/VENTAS_Y_ARTICULOS.md) |
| sesiones de PC, bonos del mostrador, PlayStation 5, PCSTREAM, ofertas, Cuenta de la PC, el mosaico de PCs | [docs/guia/PCS_Y_BONOS.md](docs/guia/PCS_Y_BONOS.md) |
| socios (Miembros), su saldo, cargas, reintegros, ORDENAR SALDOS, reservas | [docs/guia/SOCIOS_Y_RESERVAS.md](docs/guia/SOCIOS_Y_RESERVAS.md) |
| el Cliente PC, `servidor_red.py`, GET /estado, comandos a las PCs, fondos, filtro de palabras, Actualizar el Cliente PC, congelar, REINICIAR/APAGAR, cortes, administrar desde otra PC | [docs/guia/CLIENTE_PC_Y_RED.md](docs/guia/CLIENTE_PC_Y_RED.md) |
| la base (esquema, migraciones, conexiones), usuarios y permisos, claves, copias de seguridad, `errores.log`, el `.exe`, las pruebas | [docs/guia/BASE_Y_PRUEBAS.md](docs/guia/BASE_Y_PRUEBAS.md) |
| cualquier pantalla: las piezas de `ui/utils.py` y `ui/piezas_ventana.py`, la hoja de estilos, dibujos, Excel, imprimir, la barra de arriba, Qt | [docs/guia/PANTALLA.md](docs/guia/PANTALLA.md) |

- **¿Ya hay una función para esto?** Buscala antes de escribirla:
  `grep -n "palabra" docs/guia/*.md` recorre las tablas de todas las áreas.
- **Un comentario del código dice "ver CLAUDE.md, «título»" y acá no está:**
  esa trampa se mudó a `docs/guia/` con el mismo título; buscala con grep.
  Las reglas por número ("regla 7") siguen acá.
- **Lo que aprendas va a la guía de su área, no a este archivo:** una función
  que pasa a ser el único lugar de algo, una fila en la tabla de su guía; una
  trampa nueva, en sus trampas; lo que se terminó, con fecha, en
  [docs/HISTORIAL.md](docs/HISTORIAL.md). `tests/test_guia_del_proyecto.py`
  revisa que cada función de las tablas exista en el código y que este
  archivo no pase de 25 KB.

---

## Las 15 reglas

### Cómo se reparte el código

**1. Tres capas, flecha en un solo sentido.**
`ui/` dibuja y pregunta. `repositories/` decide. `database.py` guarda.
Una pantalla **nunca** importa `sqlite3`, ni escribe SQL, ni abre
`conexion_db()`. Hoy esto se cumple al 100% (verificado: cero SQL en
`ui/`) — es lo más valioso que tiene el proyecto, no lo rompas por
apuro. Si necesitás un dato que ningún repo te da, la respuesta es
**agregar la función al repo**, no meter un SELECT en la pantalla.

**2. Un dato, un solo lugar que lo calcula.**
Si vas a repetir una cuenta que ya existe en otro lado, extraela a una
función compartida *primero* y usala en los dos lugares. Nunca copiar y
pegar lógica.
> Caso resuelto que dejó el patrón: `cantidad * precio_unitario` estaba
> escrito tres veces en `ui/ventas_window.py`. Hoy vive solo en
> `ventas_repo.subtotal_linea()`, y `confirmar_venta()` la usa en vez de
> confiar en el subtotal que le manda la pantalla. El día que haya un
> descuento por cantidad o un 2x1, se cambia una función y listo.

**3. La regla de negocio vive en el repo, no en la pantalla.**
La pantalla junta lo que la usuaria escribió, se lo pasa al repo y
muestra el resultado. Validar, calcular y decidir es tarea del repo.
Si en un `.py` de `ui/` aparece una cuenta de plata o un "si pasa esto
entonces aquello" del negocio, está en el lugar equivocado.

**4. Cambio local, efecto local.**
Tocar una pantalla no puede obligar a tocar otras tres. Si te pasa eso,
falta una abstracción: hacela antes de seguir.

**5. Nada de strings mágicos sueltos.**
Los valores fijos del negocio están todos en **`dominio.py`** y se usan
desde ahí, nunca escritos a mano:

| Concepto | Constantes |
|---|---|
| Rol | `ROL_ADMIN`, `ROL_EMPLEADA`, `ROLES` — y `dominio.es_admin(usuario)` |
| Estado de venta | `VENTA_CONFIRMADA`, `VENTA_ANULADA`, `ESTADOS_VENTA` |
| Método de pago | `PAGO_EFECTIVO`, `PAGO_DIGITAL`, `METODOS_PAGO` (no hay "mixto": ver [la guía de ventas](docs/guia/VENTAS_Y_ARTICULOS.md)) |
| Turno | `TURNO_MANANA`, `TURNO_TARDE`, `TURNO_NOCHE`, `TURNOS` |
| Origen de una venta | `ORIGEN_KIOSKO`, `ORIGEN_ALQUILER_PCS`, `ORIGEN_PLAYSTATION`, `ORIGENES_VENTA` |
| Equipo que se alquila por tiempo / estado de su sesión | `DISPOSITIVO_PC`, `DISPOSITIVO_PLAYSTATION`, `NOMBRE_PLAYSTATION`, `NOMBRE_PCSTREAM`, `SESION_ACTIVA`, `SESION_FINALIZADA` |
| Comando a una PC / su estado en la cola | `TIPOS_COMANDO_PC` (los de Shadow Defender, en `COMANDOS_CON_CLAVE`; el payload de `COMANDO_MANTENIMIENTO`, en `ORDENES_MANTENIMIENTO`), `ESTADO_COMANDO_PENDIENTE`, `ESTADO_COMANDO_ENTREGADO` |
| Aviso de admin de una PC | `EVENTOS_ADMIN_PC` (los que manda el Cliente PC + `CLIENTE_REANUDADO`) |

Un typo en uno de esos strings **no falla ruidosamente**: la consulta
devuelve cero filas y nadie se entera hasta que falta plata en un cierre.
Nombrándolos, un typo es un error de Python que salta al instante.

Esto vale también dentro del SQL: el estado va como parámetro
(`WHERE estado = ?` con `dominio.VENTA_CONFIRMADA`), no como literal
pegado en la consulta. Y los `CHECK (... IN (...))` del esquema también salen
de las listas de `dominio.py` (`ROLES`, `ESTADOS_VENTA`, `TURNOS`,
`ORIGENES_VENTA`, `EVENTOS_ADMIN_PC`, `ESTADOS_COMANDO_PC`...) con
`database._valores_sql` (revisión del 2026-10-17): una base NUEVA nunca queda
desfasada. Pero SQLite no deja cambiar un CHECK ya grabado: si se agrega un
valor, las bases que ya existen necesitan una migración que reconstruya la
tabla. Para `comandos_pc.tipo`, `movimientos_saldo_miembro.tipo`,
`eventos_admin_pc.tipo` (desde el 2026-10-19, por el aviso `MANTENIMIENTO`) y
`ventas.origen` esa migración ya existe y se dispara sola si falta algún valor
(alcanza con sumarlo a la lista); para los demás, hay que escribirla.

### Cómo se tratan los datos

**6. El esquema se cambia con migración, nunca a mano.**
En la PC del kiosko hay una base con datos reales. Toda columna o tabla
nueva se agrega con una función de migración que sea segura de correr
dos veces, siguiendo el patrón de `_migrar_columnas_permisos()`. Nunca
"borrá el .db y volvé a empezar".

**7. Nada se borra: se marca.**
Una venta anulada cambia de estado y guarda quién, cuándo y por qué —
nunca desaparece de la tabla. Un usuario que se va se desactiva. Esto es
lo que permite auditar un faltante tres meses después.
> Sin excepciones: "Limpiar base de datos" (borraba la plata y el historial
> de ventas, pedido el 2026-10-17 para la etapa de pruebas) se sacó el
> 2026-10-22 a pedido del dueño ("ya es peligroso": el local trabaja con plata
> real). No vuelvas a sumar un borrado así sin que el dueño lo pida. En
> `data/backups/` pueden quedar copias `antes_de_limpiar_base_*`: no se borran.

**8. Una operación de negocio = una transacción.**
Cabecera, detalle, pagos y descuento de stock se graban juntos o no se
graba nada (ver `confirmar_venta`). Nunca dejar la puerta abierta a una
venta a medio grabar con el stock ya descontado.

**9. La plata se redondea al guardar y se formatea al mostrar.**
`round(..., 2)` en el repo, justo antes del INSERT. `formato_pesos()` en
la pantalla, justo antes de mostrar. Nunca al revés, y nunca un
`f"{monto:.2f}"` suelto en una pantalla.
> Caso resuelto: `ui/buscar_articulo.py` mostraba el precio con
> `f"{...:.2f}"` y era la única tabla del programa donde la plata se veía
> distinta. Hoy usa `formato_pesos()` como todas las demás.

**10. Los permisos se preguntan, no se deducen.**
Siempre `usuarios_repo.tiene_permiso(usuario, "permiso_x")`, nunca
comparando el rol a mano. Un permiso nuevo se agrega en el repo y las
pantallas no se enteran.

### Cómo se crece

**11. Un archivo por pantalla, un repo por tema.**
Módulo nuevo = pantalla nueva en `ui/` + su repo en `repositories/`. No
se cuelga de uno existente "porque es parecido".

**12. Cuando un archivo pasa las ~600 líneas, se parte.**
Ya se hizo con `ventas_window.py` (carrito y diálogo de pago) y con
`turnos.py` (calendario separado de la base), `turnos_faltantes_repo.py`
(turnos vencidos sin cierre), `turnos_ventas_repo.py` (qué se vendió en la
ventana de un turno), `control_cierres_repo.py` (Control de Cierres, con su
pantalla `ui/control_cierres_window.py`), `ui/reportes_resumen_dia.py` (el Resumen
del Día salió de `reportes_window.py`), `actividad_repo.py` (feed de PCs) y
`database.py` (esquema en `database_esquema.py`, migraciones en
`database_migraciones.py`, conexiones/copias/claves en `database.py`) y `main.py`
(la hoja de estilos en `ui/hoja_de_estilos.py`, 2026-10-22) y `ui/main_window.py`
(Configuración ADMIN en `ui/configuracion_admin_window.py` y Administrar Kiosko en
`ui/administrar_kiosko_window.py`, 2026-10-26) y `ui/articulos_window.py` (el alta y
modificación de un artículo en `ui/dialogo_articulo.py`, 2026-10-31) y
`control_pcs/ui/pcs_detalle.py` (las listas de bonos con las ofertas en
`pcs_lista_de_bonos.py` y el login del socio en `pcs_login_miembro.py`, 2026-11-13).
Conservá las funciones públicas al partirlos para no tocar otras pantallas.

**13. Comentar el porqué, no el qué.**
Es la mejor costumbre que tiene este código y hay que sostenerla. Los
comentarios explican decisiones no obvias y trampas (por qué el turno
noche cruza la medianoche, por qué el `.exe` guarda la base al lado del
ejecutable). Un comentario que repite lo que dice la línea de abajo
sobra; uno que explica por qué esa línea es así vale oro.

### Cómo se verifica

**14. Regla de negocio nueva, test nuevo.**
`tests/` cubre turnos, stock, cierres, cajas con número, administrar desde otra PC, PCs, PCSTREAM, Miembros, PlayStation, las ofertas 2x1 y 50%, totales y copias de seguridad, que siempre quede un Administrador activo, que los pagos de una venta de kiosko sumen el total y que anular sea solo del Admin y con motivo.
Todo lo que se calcule con plata, fechas o
turnos entra ahí antes de darse por terminado. La UI se prueba a mano;
la lógica, no.

**15. Antes de decir "listo": correr los tests y abrir el programa.**

```
python tests/correr_en_paralelo.py
python main.py
```

`correr_en_paralelo.py` corre todos los archivos de `tests/`, 8 a la vez, en
un par de minutos; `python -m unittest discover tests` sigue andando igual, en
un solo proceso y más lento. Que los tests pasen no alcanza si la pantalla no abre. Que la pantalla
abra no alcanza si los tests no pasan.

---

## Qué no cambiar sin que el dueño lo pida explícitamente

- **El modelo de cobro de Control de PCs (y de la PlayStation 5).** Siempre
  bonos de tiempo fijos prearmados (ej. "3 horas" = 180 min / $X, en
  fracciones de 30 min). Nunca hora libre ni minuto suelto, y una PC sin
  bono/saldo activo queda bloqueada — no "abierta y se cobra después". Esto no es un detalle
  técnico, es una decisión de negocio del dueño del Cyber. La única excepción la pidió él
  (2026-10-25, Cuenta de la PC): a un cliente que YA está jugando se le puede anotar un bono
  fijo para cobrarlo después, con tope; una PC sin sesión sigue bloqueada y no se abre a cuenta.
- **La estructura de carpetas.** Hoy hay DOS árboles a propósito: `ui/` +
  `repositories/` (kiosko) y `control_pcs/ui/` + `control_pcs/repositories/`
  (PCs/Miembros/Bonos/Historiales) — el dueño pidió esta separación
  explícitamente el 2026-09-26 ("son dos cosas completamente diferentes a
  lo que es vender productos de kiosko"), no es desprolijidad para
  "limpiar" fusionándolos de nuevo. Cualquier reorganización más allá de
  esta sigue siendo una decisión de fondo que se charla antes, no algo que
  se infiere de "quedaría más prolijo".
- **`data/`, a mano.** Ahí vive la base real del negocio (está en
  `.gitignore` a propósito, no llega a git). No asumas que su contenido es
  descartable ni lo edites por fuera de una migración.
- **La clave de conexión de los Clientes PC es fija y permanente** (pedido del
  dueño, 2026-10-14; aceptó expresamente el riesgo de que quede dentro del
  `.exe`). No hay pantalla para generarla ni renovarla y no se guarda en la
  base: este repo es PÚBLICO, así que el programa solo conoce su huella SHA-256
  (`clientes_repo.HUELLA_CLAVE_CLIENTES`); la clave en sí vive en
  `CLIENTE PC/configuracion.py` (repo privado). Nunca escribir la clave en este
  repo (ni en un test, ni en un doc). Una huella SHA-256 simple alcanza porque la
  clave es un valor al azar de 256 bits, no una contraseña elegida (una revisión
  automática lo marcó el 2026-10-14 y se evaluó: no hace falta sal ni KDF, ni
  "rotar porque la huella está publicada"). No volver a proponer rotación ni un botón
  "Generar/renovar": cambiarla dejaría sin conexión a las ~40 PCs hasta
  reinstalarles el `.exe`; un test lo vigila. Es una cosa distinta de la
  contraseña de ADMIN de los Clientes PC, que sí se cambia desde "Gestionar
  Estaciones".

---

## Cliente PC (estado actual)

El bloqueo de las PCs funciona con el proyecto separado `CLIENTE PC/`,
ubicado en la carpeta hermana. Se comunica con el servidor de este repo
(`servidor_red.py`) para consultar el estado de cada estación, permitir
el login de Miembros y cerrar sesiones. `explorer.exe` sigue siendo el
shell de Windows; el cliente usa pantalla de bloqueo, hook de teclado y
una tarea programada para volver a arrancar si se cierra. El reemplazo
del shell no forma parte del diseño actual. Desde el 2026-10-19 el panel admin
de cada PC (la "A") ya no cierra el Cliente PC: "Hacer mantenimiento (15 min)"
deja la PC libre con el programa abierto y avisa `MANTENIMIENTO`, que se ve en
Actividad reciente pero NO marca la PC como sin cliente (sigue preguntando su
estado). `CIERRE_CLIENTE` solo llega de PCs sin actualizar. Todo pedido del cliente lleva la
clave fija de los Clientes PC (ver "Qué no cambiar sin que el dueño lo pida
explícitamente"). El README de `CLIENTE PC/` contiene las instrucciones
vigentes de instalación y recuperación. Lo que se hablan por GET /estado lo vigila
`tests/test_contrato_cliente_pc.py` (ver la trampa de GET /estado en `docs/guia/CLIENTE_PC_Y_RED.md`): conviene correrla con
la carpeta `CLIENTE PC` al lado, porque así usa el código de verdad del Cliente PC.

## Roadmap (a futuro, fuera de alcance hoy)

Estos puntos todavía no están construidos:

- **Reportes específicos de PCs** (ej. "horas vendidas por día"). Se
  puede sumar reutilizando `sesion_bonos`, no hace falta tocar el
  esquema.

---

## Cómo trabajar en este repo

- **Idioma: español (rioplatense).** UI, comentarios, mensajes de commit y
  respuestas al usuario. El usuario no es programador: explicá los
  cambios en términos del kiosko, no de la implementación.
- **Stack:** Python 3.10+, PySide6, SQLite. Sin ORM, sin frameworks.
- **Git:** rama por cambio, después mergear a `master`.
- **Empaquetado:** `pyinstaller Kiosko.spec` genera `dist/CyberBios.exe` (el
  nombre con que lo usa el dueño; la receta conserva su nombre de archivo).
  Ojo: `dist/data/` es la base de datos *real* de la copia empaquetada.
- **Lo que aprendas** va a la guía de su área en `docs/guia/` y lo que
  termines, a `docs/HISTORIAL.md` (ver "Antes de tocar código").

---

## Estado actual

El programa integra kiosko (con el botón Impresiones), Control de PCs (con PCSTREAM), Miembros, Trámites, PlayStation 5 y Reservas (la plata, el cuidado de la hora y las de socios, sin seña).
Las pruebas se corren con `python tests/correr_en_paralelo.py` (o `python -m unittest discover tests`).
Lo que se fue haciendo, con fecha, está en [docs/HISTORIAL.md](docs/HISTORIAL.md): lo que
termines se anota ahí, no acá.
