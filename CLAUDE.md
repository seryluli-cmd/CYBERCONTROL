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
| Origen de una venta | `ORIGEN_KIOSKO`, `ORIGEN_ALQUILER_PCS`, `ORIGEN_PLAYSTATION`, `ORIGENES_VENTA` |
| Equipo que se alquila por tiempo / estado de su sesión | `DISPOSITIVO_PC`, `DISPOSITIVO_PLAYSTATION`, `NOMBRE_PLAYSTATION`, `SESION_ACTIVA`, `SESION_FINALIZADA` |

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
Ya se hizo con `ventas_window.py` (carrito y diálogo de pago) y con
`turnos.py` (calendario separado de la base), `turnos_faltantes_repo.py`
(turnos vencidos sin cierre) y `actividad_repo.py` (feed de PCs).
`database.py` sigue pendiente: esquema, migraciones, copias y claves.
Conservá las funciones públicas al partirlos para no tocar otras pantallas.

**13. Comentar el porqué, no el qué.**
Es la mejor costumbre que tiene este código y hay que sostenerla. Los
comentarios explican decisiones no obvias y trampas (por qué el turno
noche cruza la medianoche, por qué el `.exe` guarda la base al lado del
ejecutable). Un comentario que repite lo que dice la línea de abajo
sobra; uno que explica por qué esa línea es así vale oro.

### Cómo se verifica

**14. Regla de negocio nueva, test nuevo.**
`tests/` cubre turnos, stock, cierres, PCs, Miembros, PlayStation y totales.
Todo lo que se calcule con plata, fechas o
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
| `dominio.segundos_restantes(fin, ahora)` · `dominio.fin_al_sumar_minutos(fin_actual, minutos, ahora)` | se calcula cuánto le queda a una sesión de tiempo y cuándo vence al sumarle un bono (PCs Y PlayStation 5: una sola cuenta) |
| `playstation_repo.estado()` · `.vender_bono(...)` · `.finalizar_sesion(...)` | se sabe cómo está la PlayStation 5, se le vende un bono (origen PLAYSTATION) y se la libera; ahí mismo se exige el permiso (`puede_operar`) o ser Admin (catálogo) |
| `turnos_repo._desglose_de_totales(...)` · `_PREFIJO_COLUMNAS_POR_ORIGEN` | se reparte lo cobrado de un turno por origen (kiosko/pcs/playstation × efectivo/digital) y se suma el efectivo del cajón sobre TODOS los `ORIGENES_VENTA` |
| `bonos_miembro_repo.listar_bonos()` / `.obtener_bono(id)` | catálogo de bonos EXCLUSIVO de socios (no confundir con `pcs_repo`) |
| `miembros_repo.abrir_estacion_por_miembro(...)` | un socio abre una PC con su propio saldo |
| `ventas_repo.registrar_venta_sin_detalle(...)` | se arma una venta sin artículo real de por medio (bono de PC, carga de saldo) |
| `dominio.CODIGO_ARTICULO_IMPRESIONES` | se decide qué artículo de kiosko es "Impresiones" (el producto Nº 1), para mostrarlo como renglón propio en Reportes |
| `turnos_repo._vendido_aparte_entre(...)` | se calcula cuánto del Kiosko de un turno fue impresiones y trámites, para mostrarlos en columna propia en el Resumen del Día |
| `tramites_repo.registrar_tramite(...)` | se cobra un trámite de mostrador (monto libre): venta KIOSKO sin detalle + vínculo en `tramites_venta` |
| `ui.utils.formato_pesos(monto)` | un número se convierte en `"$ 1.234,50"` |
| `errores.registrar_error(excepcion, contexto)` | la UI y el servidor guardan fallos inesperados en `data/errores.log` sin depender de Qt |
| `ui.utils.manejar_errores` | se atrapa un error de una acción de pantalla |
| `ui.utils.encadenar_enter(...)` | se arma el salto de campo en campo con Enter |
| `ui.utils.aplicar_clase(widget, clase)` | un botón se marca como primario/peligro |
| `ui.utils.sin_boton_por_defecto(ventana)` | se evita que Enter en un campo active el primer botón de un diálogo (llamarla al final de `_armar_interfaz`) |
| `ui.utils.crear_tabla(titulos, ...)` | se arma una tabla de solo lectura (filas alternadas, columna que se estira, selección por filas) |
| `ui.utils.crear_selector_de_fecha(...)` | se crea un campo de fecha con calendario (sin sábado/domingo en rojo; usarlo siempre, nunca un `QDateEdit` a mano) |
| `ui.utils.armar_filtro_por_fechas(...)` · `rango_de_fechas(...)` · `fecha_iso(...)` | se arma la fila Desde/Hasta con "Buscar" y se leen sus fechas como `"YYYY-MM-DD"` (el formato con que hablan los repos) |
| `ui.utils.fila_guardar_cancelar(dialogo, ...)` | se arma la fila Guardar/Cancelar de un formulario |
| `ui.utils.fila_agregar_quitar(tabla, ...)` | se arman los botones Agregar/Quitar de una tabla que se edita a mano |
| `ui.buscar_articulo.armar_botones_de_busqueda(ventana, ...)` | se arman los botones F5/F6/F7 y sus atajos (Ventas y Compras) |
| `ui.detalle_venta.VentanaConDetalleDeVenta` | lista de ventas + artículos de la elegida (Consulta de Ventas y Detalle de un cierre) |
| `control_pcs.repositories.catalogo_bonos.CatalogoDeBonos(tabla)` | se hace el alta/edición/baja de un catálogo de bonos (`pcs_repo` para walk-ins, `bonos_miembro_repo` para socios, `playstation_repo` para la consola: tres tablas distintas, un solo código) |
| `database._reconstruir_tabla(...)` · `_admite_todos_los_tipos(lista)` | se reconstruye una tabla para cambiar un CHECK/REFERENCES, y se decide si un CHECK de tipos ya está al día |
| `database._sql_tabla_ventas(...)` · `_migrar_check_origen_en_ventas(...)` | se escribe el CREATE de `ventas` (el CHECK de `origen` sale de `dominio.ORIGENES_VENTA`) y se reconstruye una base vieja SIN romper las tablas que la referencian (ver "Trampas conocidas") |

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
  (`dominio.ORIGENES_VENTA`) — sin eso, el desglose Kiosko/Alquiler de
  PCs/PlayStation 5 de Caja y Cierre de Turno queda mal. El dueño pidió este desglose
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
- **Hay TRES catálogos de bonos, nunca la misma tabla** (los dos de abajo más
  `bonos_playstation`, ver la trampa de la PlayStation 5). `bonos_tiempo`
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
- **La PlayStation 5 NO es una "estación" y no se debe volver una.** Es una
  sola consola, nombre fijo `dominio.NOMBRE_PLAYSTATION`, con sus propias tablas
  (`bonos_playstation`, `sesiones_playstation`, `sesion_playstation_bonos`) y su
  propio repo (`playstation_repo`), aunque se vea como la primera fila de la
  grilla de Control de PCs. Una estación es una PC con Cliente PC (bloqueo,
  reinicio, apagado, IP, renombrar, baja): si la consola viviera en `estaciones`
  todo eso la alcanzaría, y a la consola no le corresponde nada. Por lo mismo,
  `playstation_repo` no tiene ningún `estacion_id` y `pcs_repo.asignar_bono` solo
  acepta una fila activa de `estaciones`: **un bono de PC no puede ir a la
  consola ni uno de la consola a una PC**, aunque dos ids coincidan (cada camino
  lee SOLO su catálogo; `PanelDetalleEstacion` además toma la lista de bonos del
  equipo elegido y deshabilita la otra). Cada fila de la grilla trae su tipo en
  `item["dispositivo"]`.
- **La sesión de la PlayStation 5 NO se da de baja sola al llegar a cero.** A
  diferencia de una PC (que se bloquea y `PanelControlPcs._refrescar` la libera),
  acá el aviso es para una persona: queda `ACTIVA` con `tiempo_agotado`, su fila
  titila en rojo (mismo parpadeo que "SIN CLIENTE") y sigue así —también si se
  cierra y reabre el programa, el vencimiento es una fecha absoluta— hasta que el
  operador la libera ("Ya avisé: liberar la consola") o le vende otro bono (que
  cuenta desde ahora, ver `dominio.fin_al_sumar_minutos`). La cuenta regresiva se
  redibuja cada segundo (`PanelControlPcs._actualizar_cuenta_regresiva`, un timer
  aparte del refresco de 5s). Si alguna vez se hace que esa sesión se libere sola,
  se pierde el aviso: no lo hagas sin que el dueño lo pida.
- **Permisos de la PlayStation 5: se hacen cumplir en el repo, no solo en la
  pantalla.** Vender un bono y liberarla: ADMIN o `permiso_control_pcs`
  ("Operar PCs y Miembros"); crear/modificar/dar de baja sus bonos: solo ADMIN
  (`playstation_repo` levanta `PermissionError`, que `ui.utils.manejar_errores`
  muestra como mensaje). Se vuelve a leer el usuario de la base en cada operación,
  así que un permiso quitado o un usuario desactivado corta el acceso en el acto.
  Ojo con la asimetría, es pedido del dueño: las **PCs** siguen abiertas a
  cualquier usuario logueado (no piden permiso), la consola no.
- **Sumar un origen de venta nuevo toca la caja, no solo `dominio.py`.** Si un
  origen no figura en `turnos_repo._PREFIJO_COLUMNAS_POR_ORIGEN` (y en las
  columnas de `cierres_turno`), su plata desaparece del efectivo esperado en el
  cajón sin ningún error visible — el dueño usa este desglose para auditar
  faltantes. El test `TestCadaOrigenSumaEnLaCaja` lo atrapa. `ventas.origen` tiene
  un CHECK: agregar un origen exige que `database._migrar_check_origen_en_ventas`
  reconstruya la tabla (corre sola al arrancar, dejando una copia en
  `data/backups/antes_de_*.db`).
- **Reconstruir `ventas` no se hace con `_reconstruir_tabla`.** Esa función
  renombra la tabla vieja primero, y SQLite (desde 3.26) re-apunta a la renombrada
  todas las claves foráneas de las tablas hijas (`venta_detalle`, `venta_pagos`,
  `sesion_bonos`, `tramites_venta`, `movimientos_saldo_miembro`,
  `sesion_playstation_bonos`): al borrarla, quedarían apuntando a una tabla que ya
  no existe. Para una tabla MADRE el orden es otro: crear `<tabla>_nueva`, copiar,
  borrar la vieja y recién ahí renombrar, con las claves foráneas apagadas y todo
  en UNA transacción — ver `_migrar_check_origen_en_ventas` y
  `TestMigracionOrigenEnVentas`.
- **Un trámite es un servicio que se cobra, no el pago de una boleta.** Lo que
  se tipea en "Trámites" es lo que el local cobra por hacerle el trámite al
  cliente (imprimir la boleta de luz, un trámite online, sacar un turno...);
  la boleta en sí nunca pasa por la caja, así que no se la modela como una
  entrada y salida de plata de terceros. No tiene stock ni costo: es ganancia
  pura (la hace un empleado). Ver `tramites_repo`.
- **El servidor de red no debe tocar Qt.** Usa conexiones SQLite propias desde
  sus hilos y registra fallos inesperados con `errores.registrar_error`, sin
  incluir claves ni el cuerpo de los pedidos en el contexto del log.
- **El refresco de PCs distingue esperar de perder el Cliente PC.** Si la
  estación aún no se conectó desde que arrancó el bono, muestra "Esperando al
  cliente"; si se desconecta después de estar enlazada, avisa "SIN CLIENTE".
  `pcs_repo._estado_para_estacion` decide esto para la grilla y para el Cliente PC.
- **Un traslado de PC conserva la sesión y su saldo.** `pcs_repo.trasladar_sesion`
  mueve o intercambia la misma sesión bajo `BEGIN IMMEDIATE`; el historial de
  qué PC ocupó está en `traslados_sesion`, no en el nombre actual de la estación.
- **Un cierre guarda una foto de lo cobrado.** En Resumen del Día, si una venta
  se anula después de cerrar, el desglose de Impresiones y Trámites debe seguir
  conciliando con ese cierre; ver `turnos_repo._vendido_aparte_entre`.
- **El recolector cíclico está desactivado a propósito** en `main.py`: evita que
  un hilo del servidor destruya un `QTimer` de Qt. Antes de reactivarlo, revisar
  la propiedad de los objetos de UI y sus ciclos de referencias.

---

## Qué no cambiar sin que el dueño lo pida explícitamente

- **El modelo de cobro de Control de PCs (y de la PlayStation 5).** Siempre
  bonos de tiempo fijos prearmados (ej. "3 horas" = 180 min / $X, en
  fracciones de 30 min). Nunca hora libre ni minuto suelto, y una PC sin
  bono/saldo activo queda bloqueada — no "abierta y se cobra después". Esto no es un detalle
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

## Estado actual

El programa integra kiosko, Control de PCs, Miembros, Trámites y PlayStation 5.
Las decisiones de negocio y las trampas vigentes están arriba; el detalle
cronológico anterior se conserva en [docs/HISTORIAL.md](docs/HISTORIAL.md).
La suite actual se ejecuta con `python -m unittest discover tests` y tiene
332 pruebas al 2026-10-10.
