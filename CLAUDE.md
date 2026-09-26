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
| Método de pago | `PAGO_EFECTIVO`, `PAGO_DIGITAL`, `METODOS_PAGO` |
| Turno | `TURNO_MANANA`, `TURNO_TARDE`, `TURNO_NOCHE`, `TURNOS` |

Un typo en uno de esos strings **no falla ruidosamente**: la consulta
devuelve cero filas y nadie se entera hasta que falta plata en un cierre.
Nombrándolos, un typo es un error de Python que salta al instante.

Esto vale también dentro del SQL: el estado va como parámetro
(`WHERE estado = ?` con `dominio.VENTA_CONFIRMADA`), no como literal
pegado en la consulta. La excepción son los `CHECK (... IN (...))` del
esquema en `database.py`: ahí el literal *es* la definición. Si algún día
se agrega un valor nuevo, va en los dos lados — `dominio.py` y una
migración que actualice el CHECK.

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
| `pcs_repo.asignar_bono(...)` | se crea o extiende una sesión de PC con un bono |
| `miembros_repo.abrir_estacion_por_miembro(...)` | un socio abre una PC con su propio saldo |
| `ui.utils.formato_pesos(monto)` | un número se convierte en `"$ 1.234,50"` |
| `ui.utils.manejar_errores` | se atrapa un error de una acción de pantalla |
| `ui.utils.encadenar_enter(...)` | se arma el salto de campo en campo con Enter |
| `ui.utils.aplicar_clase(widget, clase)` | un botón se marca como primario/peligro |

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
por tiempo: estaciones, bonos, sesiones — `repositories/pcs_repo.py` +
`ui/pcs_window.py`) y **Miembros** (socios con saldo prepago de tiempo —
`repositories/miembros_repo.py` + `ui/miembros_window.py`), y se
reorganizó `ui/main_window.py`: la grilla de PCs es la pantalla
principal, con "Gestionar PCs" como botón propio de la barra superior.
Ese código todavía no adoptó las constantes de `dominio.py` para sus
propios strings fijos (`'ACTIVA'`/`'FINALIZADA'`,
`'CARGA'`/`'CONSUMO'`/`'REINTEGRO'`) — candidato a alinear la próxima vez
que se toquen esos archivos, no urge un pase aparte solo para eso.

Próximo candidato a mirar cuando toque crecer: `ui/articulos_window.py`
(524 líneas).
