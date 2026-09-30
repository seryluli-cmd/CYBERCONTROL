# Sistema de Kiosko — CyberBIOS

Aplicación de escritorio (Windows) en **Python + PySide6 (Qt)**, con **SQLite**
local, para manejar la caja de un kiosko: ventas con lectura de código de
barras, control de stock por compras, cierre de turno con fondo de cambio
fijo, y reportes. La usan el Admin (dueño) y las empleadas desde la PC del
mostrador.

Para la guía de uso pensada para quien opera el kiosko (no técnica), ver
[LEEME.txt](LEEME.txt). Este README es la referencia técnica: para cualquier
tarea de código, leer esto primero en vez de explorar archivo por archivo —
ahorra mucho contexto. Recién si hace falta el detalle exacto de una
función, ir a buscarla puntualmente (está indexada acá por nombre y archivo).

## Stack

- **Python 3.10+**, sin build ni empaquetado en desarrollo (se corre
  directo con `python main.py`).
- **PySide6** (Qt) para toda la UI — ventanas/diálogos, sin HTML/web.
- **SQLite** (`sqlite3` de la librería estándar) como única base de datos,
  un solo archivo `data/kiosko.db`. Todo acceso pasa por el context manager
  `conexion_db()` en `database.py` (commit al salir bien, rollback si hay
  excepción, siempre cierra) y con `PRAGMA foreign_keys = ON`.
- **PyInstaller** (`Kiosko.spec`) para armar el `.exe` final — empaqueta
  `main.py` + `assets/`; la carpeta `data/` (con la base) **no** se
  empaqueta, queda al lado del `.exe` real (`database.py` detecta
  `sys.frozen` para ubicarla ahí en vez de dentro del temp de extracción).
- Sin frameworks de testing externos — `tests/test_kiosko.py` usa
  `unittest` de la librería estándar (`python -m unittest discover tests`).

## Arquitectura: repositorio + ventana

El código separa **acceso a datos** (`repositories/`, funciones puras que
reciben/devuelven dicts o tuplas, sin nada de Qt) de **UI** (`ui/`, una
clase `QDialog`/`QMainWindow` por pantalla, que llama a las funciones del
repo correspondiente). `main.py` es el único punto de entrada.

## Archivos

| Archivo | Contenido |
|---|---|
| [main.py](main.py) | Entry point. Clase `Aplicacion` alterna `LoginWindow` ↔ `MainWindow` (para poder "cerrar sesión" sin cerrar el programa). Define la hoja de estilos Qt global (botones `primario`/`peligro` vía `setProperty("clase", ...)`). `sys.excepthook` propio: cualquier excepción no capturada se loguea en `data/errores.log` y muestra un cartel, en vez de cerrar la app en silencio. |
| [database.py](database.py) | Esquema completo (`CREATE TABLE`), `hash_clave`/`verificar_clave`, seed inicial, backups automáticos/manuales, `calcular_turno()`. Ver modelo de datos abajo. |
| [repositories/](repositories/) | Capa de datos, un archivo por entidad: `articulos_repo.py`, `compras_repo.py`, `config_repo.py`, `reportes_repo.py`, `turnos_repo.py`, `usuarios_repo.py`, `ventas_repo.py`. |
| [ui/](ui/) | Una ventana/diálogo por pantalla — ver detalle abajo. `ui/utils.py` tiene los helpers compartidos (formato de pesos, decorador de manejo de errores, encadenar Enter entre campos). |
| [tests/test_kiosko.py](tests/test_kiosko.py) | Tests de la capa de repositorios/lógica de negocio sobre una base SQLite temporal (no toca `data/kiosko.db`). Sin tests de UI. |
| [Kiosko.spec](Kiosko.spec) | Config de PyInstaller para generar el `.exe`. |
| [assets/](assets/) | Ícono de la app (`icono.ico`/`.png`). |
| [data/backups/](data/backups/) | Copias diarias automáticas de la base (últimos 30 días) + copias manuales. |

## Modelo de datos (SQLite, `database.py`)

- **`usuarios`** — `id` PK, `nombre`, `clave_hash` (`salt$sha256hex`; hashes
  legacy sin salt se siguen aceptando y se migran solos al formato nuevo en
  el próximo login exitoso, ver `usuarios_repo.autenticar` /
  `database.verificar_clave`), `rol` (`ADMIN` | `EMPLEADA`), `activo`
  (soft-delete, nunca se borra un usuario de verdad para no romper el
  historial de ventas/compras/cierres), `fecha_creacion`.
- **`sesiones`** — `id` PK, `usuario_id`, `fecha_hora`. Una fila por cada
  login exitoso (la inserta `usuarios_repo.autenticar()`, junto con la
  migración de hash legacy). No hay horario asignado por empleada en el
  sistema, así que esto (junto con las ventas) es la única pista para
  saber quién podría ser responsable de un turno sin cerrar — ver
  `turnos_repo._responsables_del_mes` más abajo.
- **`marcas`** / **`rubros`** — catálogos simples `id` + `nombre` (único).
  Las marcas se crean al vuelo escribiendo un nombre nuevo en el combo del
  artículo; los **rubros son un catálogo cerrado**, se gestionan aparte
  (ver `DialogoGestionRubros` más abajo) — así se evita terminar con
  "Bebidas" y "BEBIDAS" como dos rubros distintos.
- **`articulos`** — PK es `codigo` (el código de barras o uno corto
  cargado a mano), `descripcion`, `marca_id`/`rubro_id` (FKs nullable),
  `precio_venta`, `precio_compra`, `stock` (**puede quedar negativo a
  propósito** si se vende antes de cargar la compra — nunca bloquea una
  venta), `stock_minimo` (solo para el aviso visual de stock bajo, no
  bloquea nada), `fecha_creacion`, `fecha_modif`.
- **`compras`** (cabecera: `fecha`, `usuario_id`) + **`compra_detalle`**
  (`compra_id`, `articulo_codigo`, `cantidad`, `costo_unitario`,
  `stock_antes`, `stock_despues`) — es la **única vía para que el stock
  suba** (`compras_repo.registrar_compra`, transacción única que también
  actualiza `articulos.stock`/`precio_compra`).
- **`ventas`** (cabecera: `fecha`, `usuario_id`, `turno` — se calcula solo
  con `calcular_turno(fecha_hora)`, no depende de quién esté logueado;
  `total`, `estado` `CONFIRMADA`|`ANULADA` — **una venta nunca se borra**,
  anular solo cambia el estado y guarda `anulada_por`/`anulada_fecha`/
  `anulada_motivo`) + **`venta_detalle`** (`descripcion` es una foto del
  nombre al momento de vender, no un join en vivo) + **`venta_pagos`**
  (una venta puede tener varias filas — pago mixto Efectivo + Digital).
- **`cierres_turno`** — `fecha`/`turno` del cierre, `usuario_id` (quién
  cerró), `fecha_cierre` (momento exacto — es el límite "desde" del
  próximo turno), `fondo_cambio`/`ventas_efectivo`/`ventas_digital`/
  `monto_a_retirar`, más `monto_contado`/`diferencia`/`verificado_por`/
  `fecha_verificacion` (nullable, los completa el Admin después desde
  Control de Cierres).
- **`configuracion`** — tabla genérica clave/valor. Hoy solo dos claves:
  `fondo_cambio` (monto del fondo fijo, arranca en `50000`, editable solo
  por Admin desde Usuarios) y `rubros_iniciales_cargados` (flag interno,
  no se muestra en la UI, evita que los 4 rubros semilla —`BEBIDAS`,
  `KIOSKO`, `ARTÍCULOS DE LIMPIEZA`, `INSUMOS DE PAPELERÍA`— reaparezcan
  si el Admin borra alguno a propósito).
- **`calcular_turno(fecha_hora)`** (database.py) — Mañana 06-14, Tarde
  14-22, Noche 22-06 (cruza medianoche). Se usa al registrar una venta.
  ⚠️ **Excepción: los domingos son distintos** — ese día solo hay 2
  turnos de 12hs en vez de 3 (no existe Tarde): Mañana pasa a durar
  06-18 y Noche pasa a ser 18-06 del lunes. El sábado a la noche sigue
  siendo el turno normal 22-06 (mismo criterio que la PWA web hermana,
  ver `esDiaDomingo`/`turnoActual` en el README de ese repo). Para
  mostrar el nombre según el día (`database.etiqueta_turno(fecha,
  turno)`) los domingos se muestran como **"Domingo T1"**/**"Domingo
  T2"** en vez de "Mañana"/"Noche"; el resto de los días, con el nombre
  normal.
  ⚠️ Para el **cierre de turno**, tanto la etiqueta (`turno`) como la
  **`fecha`** guardada usan el momento en que **empezó** el turno (el
  `fecha_cierre` del cierre anterior), no el momento del clic de cerrar
  — así cerrar tarde (incluso ya pasada la medianoche, para un turno
  Noche) no cambia a qué turno/día queda atribuido el cierre (ver
  `turnos_repo.cerrar_turno`, cubierto por `TestEtiquetaDeTurnoEnElCierre`
  y `TestFechaDelCierreEsElDiaQueArrancoElTurno` en los tests).
- **`database.turno_vencimiento(dia, turno)`** — momento en que un turno
  de un día dado queda vencido: fin de su ventana nominal +
  `TURNO_GRACIA_MIN` (40 min) de gracia, para darle tiempo a quien cierra
  el turno anterior antes de avisar. **`turnos_repo.turnos_del_mes_actual()`**
  arma la grilla de turnos esperados del mes en curso (día 1 a hoy,
  domingo con 2, el resto con 3) y **`turnos_repo.turnos_faltantes()`**
  la cruza contra `cierres_turno` para devolver los que ya vencieron y
  todavía no se cerraron, agregándole a cada uno `"usuarios"`: quién
  vendió algo o **inició sesión** en esa ventana, según
  `turnos_repo._responsables_del_mes` (combina `ventas` y la tabla
  `sesiones` — sirve incluso para un turno sin ninguna venta, por
  ejemplo alguien logueado que todavía no facturó nada; no hay horarios
  asignados por empleada en el sistema, así que sigue siendo una pista
  de a quién preguntarle, no una certeza). Control de Cierres de Turno
  muestra esa lista como una `QListWidget` seleccionable (no un texto
  plano) dentro de un panel rojo arriba de la tabla — cada línea trae el
  turno, la fecha y quién estuvo activo (ver
  `ControlCierresWindow._cargar_faltantes` en `ui/caja_window.py`);
  seleccionar una fila no dispara ninguna acción, porque en este sistema
  un turno vencido no se puede cerrar por separado (ver nota en la
  propia pantalla). Igual que en la PWA web
  (`turnosDelMesActual`/`turnoVencimiento`/`renderFacturado`), solo se
  reconstruye para el mes en curso, no retroactivamente.

**Seed inicial** (`database.py`, corre en cada arranque pero es
idempotente): si `usuarios` está vacía, crea **"Administrador" (Usuario
Nº 1) / clave 1234** con rol ADMIN (login muestra un aviso para cambiarla
mientras siga siendo la default). Si no existe la clave `fondo_cambio`, la crea en `50000`. Si
no corrió antes, siembra los 4 rubros default.

**Backups**: `hacer_backup_automatico()` copia `data/kiosko.db` →
`data/backups/kiosko_YYYY-MM-DD.db` una vez por día (al primer arranque
del día), conserva los últimos 30 archivos. Copia manual a cualquier
carpeta desde Usuarios → "Copia de Seguridad" (`database.copiar_backup_a`).

## Pantallas (`ui/`)

Todo se abre como diálogo modal desde `main_window.py` (no hay tabs/vistas
embebidas) — `MainWindow` arma el menú según el rol del usuario logueado.

**Para cualquier usuario (Admin o Empleada):**
- **Ventas** (`ventas_window.py`, `VentasWindow` + `DialogoPago`) —
  pantalla principal. Escaneo por código de barras (Enter en el campo
  código dispara `_escanear()`; Enter con el campo vacío y carrito no
  vacío pasa directo a cobrar). Atajos F5/F6/F7 abren el buscador
  (`buscar_articulo.py`, `DialogoBuscarArticulo`) por código/descripción/
  marca. Botón `*` "Cant." fija la cantidad para el próximo escaneo.
  Doble clic en la columna Cantidad la deja editar a cualquiera; doble
  clic en $ Unit. **solo si es Admin** (`self.es_admin`). Avisa (no
  bloquea) si el stock proyectado queda por debajo de `stock_minimo`.
  `DialogoPago` combina Efectivo + Digital: Digital nunca puede superar lo
  que falta pagar (no da "vuelto" en digital); Efectivo sí puede pasarse y
  ahí se calcula `vuelto`. Confirmar llama a `ventas_repo.confirmar_venta`.
- **Caja** (`caja_window.py`, `CajaWindow`) — solo lectura, resumen del
  turno en curso vía `turnos_repo.resumen_turno_actual()` (fondo, caja
  actual = fondo + efectivo, ventas efectivo/digital). La caja actual
  excluye a propósito lo cobrado en digital.
- **Cierre de Turno** (`caja_window.py`, `CierreTurnoWindow`) — cualquiera
  cierra su propio turno. Muestra preview y, al confirmar, llama a
  `turnos_repo.cerrar_turno(usuario['id'])`: `monto_a_retirar` = lo
  vendido en efectivo (el fondo de cambio se queda en la caja para el
  turno siguiente).

**Solo Admin** (bloque separado en `main_window.py`, gateado por
`usuario['rol'] == 'ADMIN'`):
- **Artículos** (`articulos_window.py`, `ArticulosWindow`) — grilla con
  búsqueda en vivo, resalta en rojo filas con `stock < stock_minimo`.
  `DialogoArticulo` para alta/edición (código no editable una vez creado;
  marca se puede tipear y crea al vuelo; **rubro es un combo cerrado**,
  incluye "(Sin rubro)", se elige por `rubro_id` con `findData`; el campo
  stock es solo lectura — "el stock se carga desde Compras"). Botón
  **Gestionar Rubros** abre `DialogoGestionRubros` (único lugar donde se
  crean/renombran/borran rubros, vía `articulos_repo.crear_rubro` /
  `renombrar_rubro` / `borrar_rubro` — este último rechaza el borrado con
  `ValueError` si todavía hay artículos usando ese rubro). `DialogoMovimientos`
  muestra historial de un artículo (`articulos_repo.obtener_movimientos`,
  compras en positivo, ventas confirmadas en negativo/rojo).
- **Compras** (`compras_window.py`, `ComprasWindow`) — carga de mercadería
  por escaneo (mismos F5/F6/F7 que Ventas). Al escanear pide cantidad y
  costo (precargado con el `precio_compra` actual) por `QInputDialog`.
  Confirmar llama a `compras_repo.registrar_compra` con todo el lote junto.
- **Consulta de Ventas** (`consulta_ventas_window.py`,
  `ConsultaVentasWindow`) — últimas 100 ventas
  (`ventas_repo.listar_ventas_recientes`), resalta ANULADA. Botón "Anular
  venta" (solo si `self.es_admin`) pide motivo obligatorio y llama a
  `ventas_repo.anular_venta`, que **repone el stock** de cada línea y
  marca `estado='ANULADA'` con auditoría (quién/cuándo/por qué).
- **Reportes** (`reportes_window.py`, `ReportesWindow`) — 4 tabs, todas
  con filtro Desde/Hasta y atajo "Solo Hoy": **Resumen de Ventas**
  (`reportes_repo.resumen_ventas`: total + desglose efectivo/digital),
  **Por Turno** (`reportes_repo.resumen_por_turno`: mismo desglose pero
  separado por Mañana/Tarde/Noche, siempre las 3 aunque alguna quede en
  $0), **Kiosko vs. PCs** (`reportes_repo.resumen_por_origen`: cuánto se
  facturó de Kiosko contra Alquiler de PCs — ver `dominio.ORIGENES_VENTA`
  —, con un combo para agrupar por Turno/Día/Semana o el total del rango
  completo; agrega una fila TOTAL al pie cuando hay más de un período
  listado) y **Ranking de Ventas** (`reportes_repo.ranking_ventas`, por
  cantidad o por monto).
- **Control de Cierres de Turno** (`caja_window.py`,
  `ControlCierresWindow`) — lista `turnos_repo.listar_cierres()` (columna
  Turno con la etiqueta de `etiqueta_turno`, incluye "Domingo T1"/"T2"),
  resalta en rojo si `|diferencia| > 0.01`. "Cargar monto contado" abre
  `QInputDialog` y llama a `turnos_repo.verificar_cierre`. Arriba de la
  tabla, un aviso rojo (oculto si no hay nada que avisar) lista los
  turnos del mes en curso ya vencidos sin cerrar, vía
  `turnos_repo.turnos_faltantes()`.
- **Usuarios** (`usuarios_window.py`, `UsuariosWindow`) — alta/edición de
  usuarios (clave vacía al editar = no se cambia; no deja crear/renombrar
  a un nombre que ya use otro usuario activo, ver `_nombre_en_uso`),
  "Borrar" (`usuarios_repo.borrar_usuario` — borrado real si nunca vendió/
  compró/cerró un turno, y libera su "Usuario Nº" para el próximo que se
  cree vía `_proximo_numero_disponible`; si tiene historial, ofrece
  desactivarlo en su lugar con `desactivar_usuario`, soft-delete que no
  libera el número), check "Mostrar inactivos" (para poder encontrar y
  borrar del todo a alguien ya desactivado), "Configurar Fondo de Cambio"
  (`config_repo`), "Copia de Seguridad" (`database.copiar_backup_a`).
  También `DialogoCambiarClave` (accesible para cualquier rol desde el
  menú principal, no desde esta pantalla) — cambia la clave propia
  pidiendo la actual como confirmación (`usuarios_repo.cambiar_clave`).

## Identidad y permisos

Login por **nombre + clave** (`login_window.py`, vía
`usuarios_repo.autenticar_por_nombre`) — ignora mayúsculas/minúsculas y
espacios de más al comparar. ⚠️ La comparación se hace en **Python**
(`str.lower()`), no con el `LOWER()` de SQLite: SQLite solo pliega
mayúsculas ASCII por defecto, así que con nombres acentuados
("MATÍAS" vs "Matías") el `LOWER()` de la base los deja distintos. Como
el nombre no es la clave primaria, `crear_usuario`/`modificar_usuario`
rechazan (`ValueError`) que dos usuarios **activos** compartan nombre
(ignorando mayúsculas/espacios, mismo criterio) — un usuario inactivo no
cuenta, así que su nombre se puede reusar. `autenticar(usuario_id, clave)`
por "Usuario Nº" sigue existiendo como función interna (la usan
`cambiar_clave` y los tests), pero la pantalla de Login ya no la llama.
Protección contra fuerza bruta en memoria (se resetea al reiniciar el
programa): 5 intentos fallidos → bloqueo de 60s para ese nombre
(`MAX_INTENTOS` / `BLOQUEO_SEGUNDOS`). No hay sesión persistida ni token
más allá de la fila en `sesiones` (solo para el aviso de turnos
faltantes) — el dict `usuario` (con su `rol`) simplemente se pasa por
parámetro a cada ventana que se abre.

`rol` es `ADMIN` o `EMPLEADA`. Las pantallas de administración ni siquiera
aparecen en el menú para una Empleada (no es solo un botón deshabilitado).
Dentro de alguna pantalla ya Admin-only hay chequeos extra de `es_admin`
(defensa en profundidad, ej. el botón Anular en Consulta de Ventas).

⚠️ No hay cifrado de la base ni protección contra acceso directo al
archivo `data/kiosko.db` con otra herramienta — la seguridad es a nivel de
la app (login), no del archivo.

## Manejo de errores y logging

Casi todas las acciones de UI que tocan datos están envueltas con el
decorador `@manejar_errores` (`ui/utils.py`): si la función levanta
`ValueError`, se asume un mensaje ya pensado para el usuario y se muestra
tal cual ("No se pudo completar"); cualquier otra excepción se loguea
completa (traceback) en `data/errores.log` vía `registrar_error()` y se
muestra un cartel genérico con el nombre de la excepción, para que el
programa nunca se cierre en silencio. Además `main.py` instala un
`sys.excepthook` global como red de seguridad final para lo que se escape
de ese decorador (por ejemplo, al construir una ventana).

## Cómo probarlo en local

```bash
pip install -r requirements.txt
python main.py
```

Primer arranque: se crea `data/kiosko.db` solo, con usuario `1` / clave
`1234` (rol ADMIN).

## Tests

```bash
python -m unittest discover tests
```

Corren contra una base SQLite temporal (nunca tocan `data/kiosko.db`).
Cubren: límites de `calcular_turno`, hash/verificación de clave (formato
nuevo y legacy, migración en login), venta/anulación con movimiento de
stock y redondeo a 2 decimales, borrado de artículo protegido si tiene
movimientos, y la etiqueta de turno correcta al cerrar tarde.

## Empaquetado (.exe)

`Kiosko.spec` (PyInstaller): empaqueta `main.py` + `assets/` como app sin
consola (`console=False`), ícono `assets/icono.ico`. La carpeta `data/`
(base + backups) **no** se empaqueta — queda al lado del `.exe` instalado,
así los datos sobreviven a reinstalar/actualizar el programa.

## Estado del repo

Es un repositorio git local, sin remoto configurado todavía (no hay
deploy/CI — se distribuye como `.exe` armado a mano con PyInstaller). Ver
[LEEME.txt](LEEME.txt) para el estado funcional (qué cubre esta primera
versión y qué quedó afuera a propósito).
