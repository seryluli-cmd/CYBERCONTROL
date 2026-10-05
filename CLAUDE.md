# Guía de trabajo para Claude — Sistema de Kiosko

## Por qué existe este archivo

El programa hoy es chico (~5.700 líneas) pero va a crecer. El pedido del
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
explícitamente" y "Estado" más abajo para el detalle.

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
| Rol | `ROL_ADMIN`, `ROL_EMPLEADA` — y `dominio.es_admin(usuario)` |
| Estado de venta | `VENTA_CONFIRMADA`, `VENTA_ANULADA` |
| Método de pago | `PAGO_EFECTIVO`, `PAGO_DIGITAL`, `METODOS_PAGO` — y `PAGO_MIXTO`, que NUNCA se guarda (ver más abajo) |
| Turno | `TURNO_MANANA`, `TURNO_TARDE`, `TURNO_NOCHE`, `TURNOS` |
| Origen de una venta | `ORIGEN_KIOSKO`, `ORIGEN_ALQUILER_PCS`, `ORIGENES_VENTA` |

Un typo en uno de esos strings **no falla ruidosamente**: la consulta
devuelve cero filas y nadie se entera hasta que falta plata en un cierre.
Nombrándolos, un typo es un error de Python que salta al instante.

Esto vale también dentro del SQL: el estado va como parámetro
(`WHERE estado = ?` con `dominio.VENTA_CONFIRMADA`), no como literal
pegado en la consulta. La excepción son los `CHECK (... IN (...))` del
esquema en `database.py`: ahí el literal *es* la definición. Si algún día
se agrega un valor nuevo, va en los dos lados — `dominio.py` y una
migración que actualice el CHECK. (Para `comandos_pc.tipo` y
`movimientos_saldo_miembro.tipo` ya está resuelto: el CHECK sale de la lista
única — `dominio.TIPOS_COMANDO_PC`, `database._TIPOS_MOVIMIENTO_SALDO` — y la
migración reconstruye la tabla sola si falta algún tipo; alcanza con sumar
el valor a la lista.)

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
Ya se hizo dos veces y quedó el patrón: `ventas_window.py` (589) se
partió en la pantalla del carrito + `ui/dialogo_pago.py` (el cobro), y
`database.py` (544) soltó todo el calendario del local a `turnos.py`.
Hoy el más grande es `ui/articulos_window.py` (524) — mirarlo antes de
agregarle cosas. Corte natural ahí: la lista/ABM de artículos por un
lado, los diálogos de alta-edición y movimientos por otro.

**13. Comentar el porqué, no el qué.**
Es la mejor costumbre que tiene este código y hay que sostenerla. Los
comentarios explican decisiones no obvias y trampas (por qué el turno
noche cruza la medianoche, por qué el `.exe` guarda la base al lado del
ejecutable). Un comentario que repite lo que dice la línea de abajo
sobra; uno que explica por qué esa línea es así vale oro.

### Cómo se verifica

**14. Regla de negocio nueva, test nuevo.**
`tests/test_kiosko.py` cubre la lógica de turnos, stock, cierres, PCs,
Miembros y totales de venta. Todo lo que se calcule con plata, fechas o
turnos entra ahí antes de darse por terminado. La UI se prueba a mano;
la lógica, no.

**15. Antes de decir "listo": correr los tests y abrir el programa.**

```
python -m unittest discover tests
python main.py
```

Que los tests pasen no alcanza si la pantalla no abre. Que la pantalla
abra no alcanza si los tests no pasan.

---

## Puntos únicos de verdad ya establecidos (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `turnos.calcular_turno(fecha_hora)` | se decide a qué turno pertenece una hora |
| `turnos.es_domingo(fecha)` | se pregunta si un día es domingo (acepta date, datetime o string) |
| `turnos.turnos_del_dia(fecha)` | se decide qué turnos existen en un día (3, o 2 el domingo) |
| `turnos.etiqueta_turno(fecha, turno)` | se arma el nombre legible de un turno |
| `turnos.turno_vencimiento(dia, turno)` | se decide si un turno ya debería estar cerrado |
| `dominio.es_admin(usuario)` | se pregunta si alguien es Administrador |
| `dominio.nombre_metodo(metodo)` | se arma el nombre corto de un método de pago |
| `ventas_repo.subtotal_linea(linea)` | se calcula lo que se cobra por un renglón |
| `ventas_repo.total_carrito(lineas)` | se suma el total de una venta en curso |
| `database.conexion_db()` | se abre una transacción contra la base |
| `database.DATA_DIR` / `DB_PATH` | se resuelve dónde viven los datos (código vs `.exe`) |
| `database.hash_clave()` / `verificar_clave()` | se maneja una contraseña |
| `usuarios_repo.tiene_permiso(usuario, clave)` | se decide si alguien puede entrar a algo |
| `config_repo.obtener_fondo_cambio()` | se lee el fondo de cambio del turno |
| `pcs_repo.estado_estaciones()` | se calcula el tiempo restante y estado de cada PC |
| `pcs_repo.asignar_bono(...)` | se crea o extiende una sesión de PC con un bono COMÚN (walk-in) |
| `bonos_miembro_repo.listar_bonos()` / `.obtener_bono(id)` | catálogo de bonos EXCLUSIVO de socios (no confundir con `pcs_repo`) |
| `miembros_repo.abrir_estacion_por_miembro(...)` | un socio abre una PC con su propio saldo |
| `ventas_repo.registrar_venta_sin_detalle(...)` | se arma una venta sin artículo real de por medio (bono de PC, carga de saldo) |
| `ui.utils.formato_pesos(monto)` | un número se convierte en `"$ 1.234,50"` |
| `ui.utils.manejar_errores` | se atrapa un error de una acción de pantalla |
| `ui.utils.encadenar_enter(...)` | se arma el salto de campo en campo con Enter |
| `ui.utils.aplicar_clase(widget, clase)` | un botón se marca como primario/peligro |
| `ui.utils.sin_boton_por_defecto(ventana)` | se evita que Enter en un campo active el primer botón de un diálogo (llamarla al final de `_armar_interfaz`) |
| `ui.utils.crear_tabla(titulos, ...)` | se arma una tabla de solo lectura (filas alternadas, columna que se estira, selección por filas) |
| `ui.utils.armar_filtro_por_fechas(...)` · `rango_de_fechas(...)` · `fecha_iso(...)` | se arma la fila Desde/Hasta con "Buscar" y se leen sus fechas como `"YYYY-MM-DD"` (el formato con que hablan los repos) |
| `ui.utils.fila_guardar_cancelar(dialogo, ...)` | se arma la fila Guardar/Cancelar de un formulario |
| `ui.utils.fila_agregar_quitar(tabla, ...)` | se arman los botones Agregar/Quitar de una tabla que se edita a mano |
| `ui.buscar_articulo.armar_botones_de_busqueda(ventana, ...)` | se arman los botones F5/F6/F7 y sus atajos (Ventas y Compras) |
| `ui.detalle_venta.VentanaConDetalleDeVenta` | lista de ventas + artículos de la elegida (Consulta de Ventas y Detalle de un cierre) |
| `control_pcs.repositories.catalogo_bonos.CatalogoDeBonos(tabla)` | se hace el alta/edición/baja de un catálogo de bonos (`pcs_repo` para walk-ins, `bonos_miembro_repo` para socios: dos tablas distintas, un solo código) |
| `database._reconstruir_tabla(...)` · `_admite_todos_los_tipos(lista)` | se reconstruye una tabla para cambiar un CHECK/REFERENCES, y se decide si un CHECK de tipos ya está al día |

Si necesitás uno de esos datos, **llamá a la función existente**.

---

## Trampas conocidas (no las rompas sin entenderlas)

- **El turno NOCHE cruza la medianoche** (22:00–05:59), así que vence a la
  madrugada del día *siguiente*. Cualquier consulta por rango de fechas
  que no contemple esto parte los turnos noche al medio.
- **Los domingos tienen 2 turnos de 12hs, no 3.** `MAÑANA` dura hasta las
  18:00 y no existe `TARDE`. El sábado a la noche sigue siendo el turno
  normal 22–06. Nunca asumas tres turnos por día.
- **El `.exe` empaquetado resuelve las rutas distinto.** Con PyInstaller
  `__file__` apunta a una carpeta temporal que se borra en cada arranque;
  por eso `BASE_DIR` usa `sys.executable` si está `frozen`. Si guardás un
  archivo nuevo, hacelo bajo `DATA_DIR`, nunca al lado de un `.py`.
- **El stock puede quedar negativo a propósito.** No agregues una
  validación que lo impida: prefieren vender y corregir después antes que
  frenar la cola en el mostrador.
- **El carrito de una venta vive solo en memoria** hasta que se cobra. No
  lo persistas "por las dudas": es lo que permite borrar un renglón mal
  escaneado sin dejar basura en la base.
- **El login es por nombre y exige nombres únicos entre usuarios activos.**
  Dos "Matías" activos romperían el login.
- **Las claves están hasheadas con salt, pero esto no es un sistema
  seguro.** Cualquiera con acceso al archivo `data/kiosko.db` lee y
  modifica todo. No le prometas al usuario que esto protege datos.
- **Un bono de tiempo nunca reintegra minutos no usados; el saldo de un
  Miembro sí.** Cortar antes de tiempo una sesión de bono no devuelve
  nada (es un consumible de una sola vez); cortar antes de tiempo una
  sesión abierta con saldo de socio devuelve lo no usado (redondeado
  hacia abajo a bloques de 30 min) a `miembros.saldo_minutos`. Ver
  `pcs_repo.finalizar_sesion`.
- **Los bonos los asigna el Operador; los Miembros se loguean solos.**
  No es el mismo flujo: asignar un bono es una decisión del mostrador
  (`pcs_repo.asignar_bono`), abrir con saldo de socio es autoservicio de
  autenticación pura (`miembros_repo.abrir_estacion_por_miembro`), sin
  que el Operador decida cuánto tiempo darle.
- **Toda venta sin artículo real de por medio pasa por
  `ventas_repo.registrar_venta_sin_detalle`, nunca un `INSERT INTO ventas`
  a mano.** Es lo único que le pone el `origen` correcto
  (`dominio.ORIGENES_VENTA`) — sin eso, el desglose Kiosko/Alquiler de PCs
  de Caja y Cierre de Turno queda mal. El dueño pidió este desglose
  explícitamente para poder auditar la caja (sospecha de faltantes), así
  que un error acá no es solo un bug visual.
- **`dominio.PAGO_MIXTO` no es un método de pago real: nunca llega a
  `venta_pagos`.** Es una opción del combo en Control de PCs (bono, carga
  de saldo) que abre `ui.dialogo_pago.DialogoPago` para repartir el monto
  entre Efectivo y Digital — termina grabando una o dos filas reales de
  `PAGO_EFECTIVO`/`PAGO_DIGITAL`, igual que un pago combinado de una venta
  de kiosko. Por eso no está en `METODOS_PAGO` ni en el `CHECK` de
  `venta_pagos.metodo`: agregarlo ahí rompería el desglose Efectivo/Digital
  de Caja y Cierre de Turno, que no sabría de dónde sacar el
  Efectivo/Digital de un pago "mixto" sin desglosar. Ver
  `ui.dialogo_pago.resolver_pagos`, que usan `PanelDetalleEstacion`
  (pcs_detalle.py) y `DialogoCargarSaldo` (miembros_window.py).
- **`ventas_repo.registrar_venta_sin_detalle` recibe `pagos` (lista), no
  un único método.** El `monto`/total de la venta se pasa aparte y se
  graba tal cual en `ventas.total` — nunca se lo deduce sumando `pagos`,
  porque un pago en Efectivo puede superar el total si hay vuelto de por
  medio (mismo criterio que `confirmar_venta`, que calcula el total desde
  el carrito y no desde los pagos).
- **Hay DOS catálogos de bonos, nunca la misma tabla.** `bonos_tiempo`
  (`pcs_repo`) es para cualquiera que entra al local sin ser socio
  (walk-in, `pcs_repo.asignar_bono`). `bonos_miembro` (`bonos_miembro_repo`)
  es exclusivo de Miembros, usado solo desde "Cargar Saldo" -> "Bono fijo"
  (`miembros_repo.cargar_saldo_por_bono`). El dueño pidió la separación
  explícitamente (2026-09-28) para poder ofrecerle a los socios combos
  propios sin tocar el catálogo del mostrador. Crear/editar/desactivar un
  bono, de cualquiera de los dos catálogos, es exclusivo de ADMIN desde
  "Configuración ADMIN" (`ui/main_window.ConfiguracionAdminWindow` —
  pedido explícito del dueño, 2026-09-28: editar el catálogo es tarea de
  super admin; *usar* un bono ya creado sigue delegable con
  `permiso_control_pcs`). No fusionar estos catálogos "para simplificar":
  son dos negocios distintos con reglas de negocio propias, aunque ahora
  compartan el mismo nivel de permiso para editarlos.

---

## Qué no cambiar sin que el dueño lo pida explícitamente

- **El modelo de cobro de Control de PCs.** Siempre bonos de tiempo fijos
  prearmados (ej. "3 horas" = 180 min / $X, en fracciones de 30 min).
  Nunca hora libre ni minuto suelto, y una PC sin bono/saldo activo queda
  bloqueada — no "abierta y se cobra después". Esto no es un detalle
  técnico, es una decisión de negocio del dueño del Cyber.
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

---

## Cliente PC (estado actual)

El bloqueo de las PCs funciona con el proyecto separado `CLIENTE PC/`,
ubicado en la carpeta hermana. Se comunica con el servidor de este repo
(`servidor_red.py`) para consultar el estado de cada estación, permitir
el login de Miembros y cerrar sesiones. `explorer.exe` sigue siendo el
shell de Windows; el cliente usa pantalla de bloqueo, hook de teclado y
una tarea programada para volver a arrancar si se cierra. El reemplazo
del shell no forma parte del diseño actual. El README de `CLIENTE PC/`
contiene las instrucciones vigentes de instalación y recuperación.

## Roadmap (a futuro, fuera de alcance hoy)

Estos puntos todavía no están construidos:

- **Reportes específicos de PCs** (ej. "horas vendidas por día"). Se
  puede sumar reutilizando `sesion_bonos`, no hace falta tocar el
  esquema.
- **Separar "Cargar Saldo" de Miembros de la gestión completa de
  socios.** Hoy vive dentro de "Miembros" (botón propio de la barra
  superior, permiso `permiso_control_pcs`), aunque cargar saldo es una
  venta como cualquier otra. Editar la tarifa y el catálogo de Bonos de
  Socios ya quedó exclusivo de ADMIN desde "Configuración ADMIN"
  (2026-09-28) — lo que falta, si en algún momento se quiere, es un
  permiso aparte para que un empleado común pueda cobrarle saldo a un
  socio sin tener acceso a dar de alta/baja Miembros — decisión
  consciente de no hacerlo hasta que el dueño lo pida.

---

## Cómo trabajar en este repo

- **Idioma: español (rioplatense).** UI, comentarios, mensajes de commit y
  respuestas al usuario. El usuario no es programador: explicá los
  cambios en términos del kiosko, no de la implementación.
- **Stack:** Python 3.10+, PySide6, SQLite. Sin ORM, sin frameworks.
- **Git:** rama por cambio, después mergear a `master`.
- **Empaquetado:** `pyinstaller Kiosko.spec` genera `dist/Kiosko.exe`.
  Ojo: `dist/data/` es la base de datos *real* de la copia empaquetada.

---

## Estado

Los cinco pendientes que estas reglas dejaron a la vista la primera vez
ya están hechos (rama `ordenar-para-escalar`): subtotal en un solo lugar,
precio con `formato_pesos()`, constantes en `dominio.py`, los dos
archivos grandes partidos, y `*.log` en el `.gitignore`.

Desde entonces se sumó el módulo de **Control de PCs** (alquiler de PCs
por tiempo: estaciones, bonos, sesiones) y **Miembros** (socios con saldo
prepago de tiempo), y se reorganizó `ui/main_window.py`: la grilla de PCs
es la pantalla principal, con "Gestionar PCs" como botón propio de la
barra superior. Ese código todavía no adoptó las constantes de
`dominio.py` para sus propios strings fijos (`'ACTIVA'`/`'FINALIZADA'`,
`'CARGA'`/`'CONSUMO'`/`'REINTEGRO'`) — candidato a alinear la próxima vez
que se toquen esos archivos, no urge un pase aparte solo para eso.

El 2026-09-26 ese módulo se movió de `repositories/pcs_repo.py` +
`ui/pcs_window.py` (y equivalentes de Miembros) a su propio paquete
**`control_pcs/`** (`control_pcs/repositories/`, `control_pcs/ui/`),
separado del resto de la app (ver "Qué no cambiar..." arriba) — mismo
programa, mismo login, misma base de datos, pero código físicamente
aparte. El mismo día se agregó `ventas.origen` (`dominio.ORIGENES_VENTA`)
para poder desglosar, en Caja y Cierre de Turno, cuánto se vendió de
kiosko contra cuánto de alquiler de PCs — pedido explícito del dueño para
poder auditar la caja.

`control_pcs/ui/pcs_window.py` (1.475 líneas) se partió en cuatro archivos
dentro de `control_pcs/ui/` (2026-10-05): `pcs_window.py` (grilla, menú
contextual, actividad), `pcs_detalle.py` (panel lateral + login de socio),
`pcs_comandos_dialogos.py` (captura, red, intercambiar, volumen) y
`pcs_gestion_dialogos.py` (Estaciones y Bonos, Configuración ADMIN).
Próximo candidato a mirar cuando toque crecer: `ui/articulos_window.py`
(~520 líneas).

**2026-09-28:** se sumó método de pago **Mixto** (`dominio.PAGO_MIXTO`,
nunca persistido, ver "Trampas conocidas") a los combos de Control de
PCs, y el catálogo **`bonos_miembro`** (exclusivo de socios,
`bonos_miembro_repo`, separado de `bonos_tiempo` — ver "Trampas
conocidas"), gestionable solo por ADMIN desde "Configuración ADMIN" ->
"Gestionar Bonos de Socios". También se corrigió un crash del menú
contextual de "Control de PCs" (clic derecho sobre una estación) que
saltaba si el refresco automático de 5s disparaba con el menú todavía
abierto (`PanelControlPcs._mostrar_menu_contextual`, ahora pausa el
timer mientras el menú está abierto).

**2026-09-28 (más tarde):** reorganización de menú pedida explícitamente
por el dueño, separando "editar el catálogo" (Admin) de "usar el
catálogo" (cualquier operador con `permiso_control_pcs`):
- **"Miembros"** (antes "Gestionar Miembros", colgado de "Gestionar
  PCs"): ahora botón propio de la barra superior, entre "Vender" y
  "Administrar Kiosko". Solo conserva lo operativo — alta de socio,
  modificar datos, cargar saldo, desactivar.
- **"Configuración ADMIN"** (`ui/main_window.ConfiguracionAdminWindow`):
  botón nuevo, exclusivo de ADMIN sin excepción (no hay permiso
  delegable). Agrupa las cuatro pantallas de edición de catálogo que
  antes eran delegables o estaban repartidas: Gestionar Estaciones
  (agregar/quitar/renombrar PC, antes con `permiso_control_pcs`),
  Gestionar Bonos de walk-ins (antes con `permiso_control_pcs`), Tarifa
  por Hora de Socios y Gestionar Bonos de Socios (estas dos ya eran
  Admin-only, solo cambió de dónde se accede).
- **El botón "Gestionar PCs" desapareció** — lo que tenía (Estaciones,
  Bonos, Miembros) se repartió entre "Configuración ADMIN" y "Miembros".
- La etiqueta del permiso `permiso_control_pcs` en Usuarios se actualizó
  a "Operar PCs y Miembros (asignar bonos, abrir con socio, cargar
  saldo)" para reflejar que ya no habilita editar Estaciones ni Bonos.

**2026-09-29:** se corrigieron seis bugs de plata/datos reportados por el
dueño, todos con test nuevo (94 -> 109 tests):
- **Vuelto contado como ingreso.** Una venta de $1.000 pagada con un
  billete de $2.000 sumaba $2.000 a caja aunque se hayan devuelto $1.000
  de vuelto. `ui/dialogo_pago.DialogoPago._confirmar` ahora descuenta el
  vuelto de los pagos en Efectivo antes de devolverlos (ver
  `dominio.pagos_netos_de_vuelto`, la única función que decide esto).
- **Migración frágil de `movimientos_saldo_miembro`.** Podía romper con
  "FOREIGN KEY constraint failed" si un `bono_id` heredado no existía en
  `bonos_miembro`, y un corte de luz a mitad de camino podía dejar el
  historial real atrapado, invisible, en una tabla "_viejo" para
  siempre. Ver `database._migrar_referencia_bono_en_movimientos_saldo_miembro`.
- **Reintegro al socio equivocado.** Una sesión de PC creada por un socio
  y extendida después con un bono del mostrador (o al revés) le
  reintegraba a un solo `miembro_id` (el grabado al crear la sesión)
  TODO el tiempo restante, aunque parte viniera de un bono (que nunca
  reintegra) o de otro socio. `pcs_repo.finalizar_sesion` ahora
  reconstruye de qué fuente salió cada tramo (`_reintegros_por_miembro`)
  y reintegra solo lo que le corresponde a cada uno.
- **Saldo duplicado por carrera.** Dos pedidos `/login` simultáneos del
  mismo socio (`ThreadingHTTPServer`, doble clic o reintento de red)
  podían autenticarse leyendo el mismo saldo y gastarlo los dos.
  `miembros_repo.abrir_estacion_por_miembro` ahora autentica y consume
  DENTRO de una transacción con `BEGIN IMMEDIATE`, que serializa los
  pedidos concurrentes.
- **Cierre en el mismo segundo.** `ventas.fecha` y
  `cierres_turno.fecha_cierre` se grababan con precisión de un segundo;
  una venta y un cierre que empataran en el mismo segundo quedaban
  afuera de los DOS turnos (el `>` estricto entre ventanas los excluía a
  los dos). Ahora se graban con microsegundos.
- **Anulación que no revierte el beneficio.** Anular desde Consulta de
  Ventas una venta que había cargado saldo a un socio le sacaba la plata
  del cierre/caja pero le dejaba los minutos intactos. Nueva función
  `miembros_repo.anular_carga` (usada por `ui/consulta_ventas_window`
  cuando `origen == ALQUILER_PCS`) revierte la carga del saldo actual
  (topeada a lo que le quede) y deja un movimiento `ANULACION` propio en
  el ledger — tipo nuevo, migración de CHECK incluida (ver
  `database._migrar_check_tipo_en_movimientos_saldo_miembro`).

**2026-09-29 (más tarde):** dos comandos remotos nuevos en el menú
contextual de Control de PCs, mismo mecanismo que
Reiniciar/Apagar/Mensaje/Captura (`comandos_pc_repo.py`,
`TIPO_CAMBIAR_RED`/`TIPO_VOLUMEN`):
- **"Cambiar red..."**: el Cyber tiene varios módems en paralelo (ej.
  192.168.1.201/.202), cada uno con su propia puerta de enlace en el
  mismo rango; si uno se cae, esto le cambia a una estación la puerta de
  enlace y el DNS al otro módem sin ir hasta la PC (las PCs cliente
  tienen IP fija propia, confirmado con el dueño). Catálogo de módems
  nuevo, `control_pcs/repositories/config_red_repo.py` (JSON en la
  tabla `configuracion` existente, sin migración), editable desde el
  mismo diálogo. A diferencia de Reiniciar/Apagar, sí puede fallar del
  lado de la PC (necesita permisos de Administrador ahí — confirmado que
  las cuentas cliente los tienen), así que el Cliente PC sube el resultado
  de vuelta por `POST /comando_resultado` con un `texto` corto
  ("OK"/"ERROR: ...") en vez del `imagen_base64` que ya usaba
  SCREENSHOT — `servidor_red.py:_manejar_comando_resultado` ahora acepta
  cualquiera de los dos.
- **"Ajustar volumen..."**: slider 0-100% que le manda a una estación su
  nivel exacto de volumen maestro (el Cliente PC usa pycaw,
  ver README de CLIENTE PC) — fire-and-forget como Mensaje, no
  necesita Administrador así que no hace falta reportar resultado.

114 tests (109 -> 114, 5 nuevos en `TestConfigRedRepo`). Detalle técnico
completo del lado cliente (PowerShell usado, por qué no `netsh`,
dependencias nuevas) en el README de `CLIENTE PC`, sección
"Cambiar red... y Ajustar volumen...".

**2026-09-29 (más tarde todavía):** nueva pestaña **"Kiosko vs. PCs"** en
Reportes (pedido explícito del dueño: quería ver cuánto se facturó de
Kiosko contra Alquiler de PCs, por turno/día/semana/rango de fechas).
`reportes_repo.resumen_por_origen(desde, hasta, agrupar_por)` es la
única función que decide esto -- agrupa por `"turno"` (siempre las 3,
mismo criterio que `resumen_por_turno`), `"dia"`, `"semana"` (lunes a
domingo, vía el modismo `date(fecha, 'weekday 0', '-6 days')` de SQLite
para hallar el lunes de la semana) o `"rango"` (un solo total, default).
Usa `ventas.total` agrupado por `ventas.origen`, no `venta_pagos`: acá
no importa el método de pago. La pestaña agrega una fila TOTAL en negrita
al pie cuando el agrupamiento deja más de un período listado. 119 tests
(114 -> 119, 5 nuevos en `TestResumenPorOrigen`).

**2026-09-29 (más tarde todavía, otra vez):** encontrado y arreglado el
origen real de una familia de crashes que venía apareciendo hacía días en
`data/errores.log` sin poder explicarse ("Internal C++ object (QTimer) /
(PanelActividad) / (PanelControlPcs) already deleted") y que el dueño
reportó como "entro al programa y se cierra solo" estando en la grilla de
PCs, sin ninguna acción puntual de por medio. Causa: `PanelControlPcs`
conecta su timer de refresco a un método propio
(`self._timer.timeout.connect(self._refrescar)`,
`control_pcs/ui/pcs_window.py`), lo que arma un ciclo de referencias
Python que solo el recolector *cíclico* rompe -- y ese recolector puede
dispararse desde CUALQUIER hilo que esté asignando memoria en ese
momento, no necesariamente el hilo dueño del QObject. `servidor_red.py`
corre un hilo de fondo real (`threading.Thread`, no `QThread`) todo el
tiempo que Kiosko está abierto: si ese hilo disparaba la recolección
justo cuando le tocaba destruir un QTimer de la interfaz, Qt tiraba
`QObject::killTimer: Timers cannot be stopped from another thread` y
dejaba el objeto C++ roto, listo para explotar como "already deleted" en
cualquier pantalla que lo tocara después. Arreglo: `gc.disable()` en
`main.py:main()`, antes de crear la `QApplication` -- los `QObject` ya se
liberan solos por relación padre/hijo de Qt (`QTimer(self)`) y el resto
del programa se apoya en refcounting normal, no en ciclos, así que
desactivar el recolector cíclico no pierde nada que importe en un
programa que se reinicia a diario.

**2026-09-30:** dos pedidos del dueño sobre Control de PCs, confirmados
tras una prueba real (abrir un bono, apagar la PC cliente, verificar que
el tiempo restante siguió bajando solo del lado del Servidor -- el
mecanismo ya era correcto):
- **Alerta "SIN CLIENTE"**: una estación con sesión activa (Bono o
  Miembro) que deja de estar "enlazada" ahora parpadea en rojo en vez de
  quedar en el amarillo normal de "En uso" -- aviso al operador de que
  hay tiempo pago corriendo sin que el Cliente PC de esa PC esté reportando
  conexión (posible cliente que encontró la forma de cerrarlo). Ver
  `COLOR_ALERTA_SESION_SIN_CLIENTE` / `_alternar_parpadeo` en
  `control_pcs/ui/pcs_window.py` -- timer aparte de 500ms, no toca
  `pcs_repo` ni el esquema.
- **Sincronización al reconectar, siempre el menor**: pedido de
  seguridad extra del lado del cliente (`CLIENTE PC`, no en este
  repo) -- ante cualquier diferencia entre el conteo local del Cliente PC y
  el `segundos_restantes` que manda este Servidor, el Cliente PC ahora usa
  siempre el menor de los dos, para no regalar tiempo de sesión por un
  desfasaje de reloj entre PCs. No requirió ningún cambio acá (el
  Servidor ya mandaba el dato correcto); ver el README de
  `CLIENTE PC` para el detalle.

**2026-10-02:** pedido del dueño: cuando llegan muchos clientes juntos, el
operador va habilitando las PCs una por una y cada cliente la usa apenas
la prende, sin ninguna confirmación extra. El tiempo ya corría desde el
momento de activar el bono (vencimiento absoluto en `fecha_fin_prevista`,
independiente de si la PC está prendida) y el Cliente PC, al arrancar,
toma solo el estado del servidor -- eso no hizo falta tocarlo. Lo que
faltaba: una PC habilitada pero todavía apagada parpadeaba en rojo como
"SIN CLIENTE (revisar)" (alerta de posible fraude), llenando la pantalla
de falsas alarmas. `pcs_repo.estado_estaciones` ahora trae
`esperando_cliente` (sesión activa, PC no enlazada, y que no estaba
enlazada al arrancar la sesión ni se conectó desde entonces) y la grilla
la muestra como "⏳ Esperando al cliente" en azul calmo, sin parpadeo. La
alerta roja queda solo para una PC que SÍ estuvo enlazada durante la
sesión (o justo antes) y dejó de responder. 152 tests.

**2026-10-02 (más tarde):** nueva opción **"🔀 Intercambiar de máquina..."**
en el menú contextual (clic derecho) de una PC con sesión activa. Pedido
del dueño: el cliente se sienta en la PC que hay libre, pero quiere su
favorita (ej. la 15) y se pasa horas después cuando se libera; o dos
clientes quieren cambiarse de lugar. `pcs_repo.trasladar_sesion` es la
única función que decide esto: la MISMA fila de `sesiones_pc` cambia de
`estacion_id` (vencimiento, bonos, saldo de socio y reintegro intactos, no
se cobra nada). Destino libre = se mueve (la PC de origen queda sin
sesión y su Cliente PC la bloquea y reinicia sola, como al acabarse el
tiempo); destino ocupado = las dos sesiones se intercambian (ninguna se
reinicia); un destino con sesión ya vencida cuenta como libre. Corre con
`BEGIN IMMEDIATE`. Tabla nueva `traslados_sesion` (historial, una fila por
sesión movida) y evento "Sesión pasada de PC X a PC Y" en el panel de
actividad. Ojo: el INICIO/BONO de esa sesión en el panel de actividad se
muestra con la PC ACTUAL (sale de `sesiones_pc.estacion_id`); el recorrido
real está en `traslados_sesion`. 158 tests.

**2026-10-03:** nueva pestaña **"Resumen del Día"** en Reportes (pedido del
dueño: ver UN día abierto por turno, con su resumen). La única función que
lo decide es `turnos_repo.resumen_del_dia(dia)`: para cada turno esperado
ese día (`turnos_del_dia`, 3 o 2 el domingo) devuelve estado CERRADO /
EN_CURSO / SIN_CERRAR / PENDIENTE, quién cerró, ventas (y anuladas aparte),
Kiosko vs. PCs, Efectivo/Digital, total y la diferencia del sobre si el
Admin ya lo contó. Un turno es del día en que ARRANCÓ (la Noche incluye
hasta las 06:00 del siguiente) y su plata es la de su CIERRE
(`cierres_turno`), no la del reloj -- si el mismo turno se cerró dos
veces se suman los dos cierres. 165 tests (7 nuevos en `TestResumenDelDia`).

**2026-10-03 (más tarde):** nuevo botón **"🔐 Accesos de Admin"** en
Configuración ADMIN (`ui/accesos_admin_window.py`). Pedido del dueño: que
quede registrado cuándo se loguea un Admin. La tabla `sesiones` ya
guardaba cada login de TODOS los usuarios; lo que faltaba era verla.
`usuarios_repo.listar_logins(desde, hasta, solo_admin=True)` filtra por
rol ADMIN (el rol de HOY, no el de cuando se logueó) y la pantalla trae un
combo para ver también a las empleadas. Solo registra logins exitosos: un
intento con clave mala no deja rastro. 169 tests.

**2026-10-03 (más tarde todavía):** **registro de accesos admin en las PCs
cliente**. Pedido del dueño: los empleados de mantenimiento entran al panel
admin de una PC (la "A" chica de la pantalla de bloqueo), cierran el Cliente
PC y la dejan abierta horas para jugar -- quería enterarse cuándo pasa y
cuánto dura. El Cliente PC avisa tres cosas (`POST /evento_admin`, ver
`servidor_red._manejar_evento_admin`): `ACCESO` (entró al panel con la
contraseña correcta), `CIERRE_CLIENTE` y `RECONFIGURAR`. El cuarto,
`CLIENTE_REANUDADO`, lo anota el servidor solo la primera vez que esa PC
vuelve a preguntar su estado (con cuánto estuvo sin bloqueo). Todo vive en
`control_pcs/repositories/accesos_admin_pc_repo.py`, tabla nueva
`eventos_admin_pc` y columna `estaciones.cliente_cerrado_desde` (la marca
"esta PC está sin Cliente PC desde...", migración
`_migrar_columna_cliente_cerrado_desde_estaciones`); los nombres de los
eventos son `dominio.EVENTO_ADMIN_*`. Se ve en tres lugares: la grilla de
Control de PCs (lila "Sin bloqueo (cerrado por admin hace 2h 05m)", y si hay
una sesión corriendo parpadea como "SIN CLIENTE"; `estado_estaciones` trae
`cliente_cerrado_admin_desde` y con eso `esperando_cliente` queda en False,
porque un Cliente PC cerrado por un admin no va a volver solo), el panel de
"Actividad reciente" (tipo `ADMIN_PC`) y la pestaña **"Admin en PCs cliente"**
de Configuración ADMIN -> Accesos de Admin
(`control_pcs/ui/accesos_admin_pc_tab.py`). Si el servidor está apagado
cuando el admin entra (justo cuando suele hacer falta el panel), el Cliente
PC guarda el aviso en `eventos_admin_pendientes.json` y lo manda solo al
volver la conexión, diciendo "esto pasó hace X segundos" (no manda su hora:
el reloj de cada PC puede estar corrido). Límites a no olvidar: la
contraseña admin es una sola, así que el registro dice QUÉ PC y CUÁNDO, no
QUIÉN; y "sin bloqueo" corre hasta que el Cliente PC volvió, así que si
apagaron la PC en el medio incluye ese tiempo. Solo deja constancia, no
impide nada. 188 tests (19 nuevos: `TestAccesosAdminPc` y
`TestServidorRedEventoAdmin`; `TestServidorRedLogout` ahora hereda de la
base común `_ConServidorRed`).

**2026-10-04:** **apagar una PC desde CYBERCONTROL cierra el episodio "sin
bloqueo"**. Pedido del dueño: si el Operador apaga la PC, deja de
interpretarse como "admin corriendo" y no tiene que dar ninguna
advertencia. `comandos_pc_repo.encolar_comando` (único lugar donde se
encola un comando) llama a `accesos_admin_pc_repo.limpiar_marca_sin_cliente`
cuando el tipo es `TIPO_APAGAR`: borra `estaciones.cliente_cerrado_desde`
sin anotar ningún evento, así la grilla vuelve a mostrar "Sin conexión" y,
cuando la PC se prenda de nuevo, no se anota `CLIENTE_REANUDADO`. Reiniciar
NO lo hace (la PC vuelve con el Cliente PC y ahí sí se anota cuánto estuvo
sin bloqueo). Ojo: el comando lo ejecuta el Cliente PC de esa PC, así que si
tiene el Cliente PC cerrado el comando queda pendiente y la PC no se apaga;
y como además se limpia la marca, esa PC pasa a verse igual que una apagada.
190 tests.

**2026-10-05 (más tarde):** limpieza de código repetido en todo el proyecto,
sin cambios de comportamiento (verificada contra la versión anterior: tests,
un escenario de datos de 149 pasos, el árbol completo de widgets de las 54
pantallas y 82 secciones de interacción). Lo que antes estaba copiado ahora
vive en un solo lugar -- ver la tabla de "Puntos únicos de verdad": ayudantes
de pantalla en `ui/utils.py`, `ui/detalle_venta.py`,
`ui/buscar_articulo.armar_botones_de_busqueda`,
`control_pcs/ui/bonos_dialogos.py` (alta/edición y lista de bonos de los dos
catálogos) y `control_pcs/repositories/catalogo_bonos.py` (`CatalogoDeBonos`;
los dos catálogos siguen siendo tablas separadas). Las migraciones de
`database.py` salen de `_reconstruir_tabla` / `_sql_tabla_*`. Bug encontrado
y arreglado en el camino: "Cambiar red..." y "Ajustar volumen..." no podían
ni encolarse (el CHECK de `comandos_pc.tipo` no admitía esos tipos); migración
`_migrar_check_tipo_en_comandos_pc`, con tests. El proyecto hermano
`CLIENTE PC` recibió la misma limpieza. 213 tests.
