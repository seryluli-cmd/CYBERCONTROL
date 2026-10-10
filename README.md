# Sistema de Kiosko — CyberBIOS

Aplicación de escritorio (Windows) en **Python + PySide6 (Qt)**, con **SQLite**
local, para manejar el kiosko, las PCs del cyber, socios con saldo prepago,
trámites de mostrador y una PlayStation 5. Incluye ventas, stock, caja,
cierres de turno y reportes. La usan el Admin y las empleadas desde la PC
del mostrador.

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
- Tests con `unittest` de la librería estándar
  (`python -m unittest discover tests`).

## Arquitectura: repositorio + ventana

El código separa **acceso a datos** (repositorios, sin Qt) de **UI**
(ventanas y paneles, sin SQL). El kiosko usa `repositories/` y `ui/`;
Control de PCs, Miembros y PlayStation usan sus propios subdirectorios en
`control_pcs/`. Comparten `database.py`, `dominio.py` y `turnos.py`.
`main.py` es el único punto de entrada. Ver las reglas en `CLAUDE.md`.

## Archivos

| Archivo | Contenido |
|---|---|
| [main.py](main.py) | Entry point. Clase `Aplicacion` alterna `LoginWindow` ↔ `MainWindow` (para poder "cerrar sesión" sin cerrar el programa). Define la hoja de estilos Qt global (botones `primario`/`peligro` vía `setProperty("clase", ...)`). `sys.excepthook` propio: cualquier excepción no capturada se loguea en `data/errores.log` y muestra un cartel, en vez de cerrar la app en silencio. |
| [database.py](database.py) · [database_esquema.py](database_esquema.py) · [database_migraciones.py](database_migraciones.py) | Conexiones, claves y copias; creación de tablas e índices; migraciones de bases existentes. Ver modelo de datos abajo. |
| [turnos.py](turnos.py) · [dominio.py](dominio.py) | Calendario del local y constantes/reglas puras de negocio. |
| [repositories/](repositories/) | Capa de datos, un archivo por tema: artículos, compras, configuración, reportes, turnos y turnos faltantes, trámites, usuarios y ventas. |
| [ui/](ui/) | Una ventana/diálogo por pantalla — ver detalle abajo. `ui/utils.py` tiene los helpers compartidos (formato de pesos, decorador de manejo de errores, encadenar Enter entre campos). |
| [control_pcs/](control_pcs/) | UI y repositorios de PCs, Miembros y PlayStation 5; el feed de actividad está en `control_pcs/repositories/actividad_repo.py`. |
| [servidor_red.py](servidor_red.py) · [errores.py](errores.py) | API del Cliente PC y registro de fallos compartido con la UI. |
| [tests/](tests/) | Tests de repositorios, migraciones, servidor y UI sobre bases SQLite temporales (no tocan `data/kiosko.db`). |
| [tests/test_playstation.py](tests/test_playstation.py) · [tests/test_playstation_ui.py](tests/test_playstation_ui.py) | La PlayStation 5: permisos, catálogos separados, ventas, vencimiento del tiempo, caja/reportes y la migración de `ventas`; y su grilla/panel (con Qt "offscreen", sin abrir ventanas). |
| [Kiosko.spec](Kiosko.spec) | Config de PyInstaller para generar el `.exe`. |
| [assets/](assets/) | Ícono de la app (`icono.ico`/`.png`). |
| [data/backups/](data/backups/) | Copias diarias automáticas de la base (últimos 30 días) + copias manuales. |

## Modelo de datos (SQLite, `database_esquema.py`)

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
- **`tramites`** (`id`, `nombre`, `activo` — baja lógica) + **`tramites_venta`**
  (`venta_id` único, `tramite_id`, `descripcion` = foto del nombre al cobrar)
  — servicios que los empleados hacen en el mostrador (sacar e imprimir una
  boleta de luz o gas, trámites online, turnos...) con monto libre. Se
  cobra el servicio, nunca la boleta en sí: no hay stock ni costo, es
  ganancia pura. El catálogo lo arma el Admin; cobrar uno es una venta
  común (origen KIOSKO, sin `venta_detalle`) más una fila en
  `tramites_venta` que dice cuál fue. Ver `tramites_repo.registrar_tramite`.
- **`bonos_playstation`** + **`sesiones_playstation`** +
  **`sesion_playstation_bonos`** — la **PlayStation 5** del local (una sola
  consola, nombre fijo "PLAYSTATION 5"), que se alquila por tiempo como una
  PC pero con su propio catálogo de bonos (tabla aparte de `bonos_tiempo` y
  `bonos_miembro`), sus sesiones (el vencimiento es una fecha absoluta, así
  que el tiempo sigue bien aunque se cierre el programa; a lo sumo una
  sesión `ACTIVA`, lo garantiza un índice único) y el vínculo con la venta
  que cobró cada bono. **No es una fila de `estaciones`** a propósito: una
  estación es una PC con Cliente PC y ninguna de sus acciones (renombrar,
  dar de baja, reiniciar, bono de PC) puede alcanzar a la consola. Sus ventas
  llevan `ventas.origen = 'PLAYSTATION'` (`dominio.ORIGEN_PLAYSTATION`), así
  Caja, Cierre de Turno y Reportes la muestran aparte de Kiosko y de Alquiler
  de PCs. Ver `control_pcs/repositories/playstation_repo.py`.
- **`cierres_turno`** — `fecha`/`turno` del cierre, `usuario_id` (quién
  cerró), `fecha_cierre` (momento exacto — es el límite "desde" del
  próximo turno), `fondo_cambio`/`ventas_efectivo`/`ventas_digital`/
  `monto_a_retirar`, más `monto_contado`/`diferencia`/`verificado_por`/
  `fecha_verificacion` (nullable, los completa el Admin después desde
  Control de Cierres) y el desglose por origen (`kiosko_*`, `pcs_*`,
  `playstation_*`, cada uno en efectivo y digital).
- **`configuracion`** — tabla genérica clave/valor. Incluye el fondo de
  cambio, el indicador de rubros iniciales, tarifas y claves de Clientes PC.
  Las claves exactas están centralizadas en los repositorios que las usan.
- **`calcular_turno(fecha_hora)`** (`turnos.py`) — Mañana 06-14, Tarde
  14-22, Noche 22-06 (cruza medianoche). Se usa al registrar una venta.
  ⚠️ **Excepción: los domingos son distintos** — ese día solo hay 2
  turnos de 12hs en vez de 3 (no existe Tarde): Mañana pasa a durar
  06-18 y Noche pasa a ser 18-06 del lunes. El sábado a la noche sigue
  siendo el turno normal 22-06 (mismo criterio que la PWA web hermana,
  ver `esDiaDomingo`/`turnoActual` en el README de ese repo). Para
  mostrar el nombre según el día (`turnos.etiqueta_turno(fecha,
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
- **`turnos.turno_vencimiento(dia, turno)`** — momento en que un turno
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

## Pantallas (`ui/` y `control_pcs/ui/`)

`MainWindow` muestra la grilla de PCs y la PlayStation 5 como panel principal;
el resto se abre en diálogos. Arma los accesos según rol y permisos.

**Para cualquier usuario (Admin o Empleada):**
- **Ventas** (`ventas_window.py`, `VentasWindow` + `DialogoPago`) —
  pantalla de facturación. Escaneo por código de barras (Enter en el campo
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
- **Trámites** (`tramites_window.py`, `DialogoTramites`) — botón de la
  barra entre "Vender" y "Miembros". Se elige un trámite del catálogo, se
  tipea el monto (libre, en $) y el medio de pago (Efectivo / Digital /
  Mixto, mismo `resolver_pagos` que Cargar Saldo) y se cobra con
  `tramites_repo.registrar_tramite`. En Caja y Cierre de Turno cuenta como
  **Kiosko** (no tiene origen propio); en Reportes sale en columna aparte
  (Totales y Resumen del Día) y en el Ranking de Ventas. El Admin ve además
  "Gestionar trámites" (`DialogoGestionTramites`: Nuevo / Modificar /
  Desactivar), que también está en Configuración ADMIN. En Consulta de
  Ventas el trámite se ve como una fila "Trámite: <nombre>".
- **PlayStation 5** (`control_pcs/ui/pcs_window.py` + `pcs_detalle.py`) — es
  la primera fila de la grilla de Control de PCs, arriba de las PCs, con el
  nombre fijo "PLAYSTATION 5" (no se edita, no se da de baja, no tiene menú de
  PC). Al elegirla, el panel lateral habilita **solo** sus bonos (que van
  debajo de los de PC, que quedan deshabilitados); al elegir una PC pasa lo
  inverso, y un bono nunca puede cobrarse al equipo equivocado
  (`PanelDetalleEstacion` toma la lista del equipo elegido, y los repos
  validan cada uno su catálogo). Muestra una cuenta regresiva que se redibuja
  cada segundo; al llegar a cero la fila **titila en rojo** hasta que el
  operador avise a los clientes y la libere ("Ya avisé: liberar la consola")
  o venda otro bono — no se da de baja sola como una PC. Vender un bono y
  liberarla pide ser Admin o tener `permiso_control_pcs` ("Operar PCs y
  Miembros"); crear/modificar/dar de baja sus bonos es solo del Admin, desde
  Configuración ADMIN → "Gestionar Bonos de PlayStation 5". Ver
  `playstation_repo.vender_bono`.
- **Caja** (`caja_window.py`, `CajaWindow`) — solo lectura, resumen del
  turno en curso vía `turnos_repo.resumen_turno_actual()` (fondo, caja
  actual = fondo + efectivo, ventas efectivo/digital, y el desglose Kiosko /
  Alquiler de PCs / PlayStation 5). La caja actual
  excluye a propósito lo cobrado en digital.
- **Cierre de Turno** (`caja_window.py`, `CierreTurnoWindow`) — cualquiera
  cierra su propio turno. Muestra preview y, al confirmar, llama a
  `turnos_repo.cerrar_turno(usuario['id'])`: `monto_a_retirar` = lo
  vendido en efectivo (el fondo de cambio se queda en la caja para el
  turno siguiente).

**Administrar Kiosko:** Artículos, Compras, Consulta de Ventas, Reportes y
Control de Cierres pueden delegarse por permiso individual a una empleada.
Usuarios y las configuraciones de catálogos son exclusivos del Admin.
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
- **Reportes** (`reportes_window.py`, `ReportesWindow`) — 5 tabs. Cuatro
  con filtro Desde/Hasta y atajo "Solo Hoy": **Resumen de Ventas**
  (`reportes_repo.resumen_ventas`: total + desglose efectivo/digital),
  **Por Turno** (`reportes_repo.resumen_por_turno`: mismo desglose pero
  separado por Mañana/Tarde/Noche, siempre las 3 aunque alguna quede en
  $0), **Totales** (`reportes_repo.resumen_por_origen`: cuánto se
  facturó de Kiosko, de Impresiones, de Trámites, de Alquiler de PCs y de
  PlayStation 5 — ver
  `dominio.ORIGENES_VENTA`, `dominio.CODIGO_ARTICULO_IMPRESIONES` y
  `tramites_repo`; las impresiones (el producto Nº 1) y los trámites (ganancia
  pura) salen en columna aparte y NO están sumados en Kiosko —, con un
  combo para agrupar por Turno/Día/Semana o el total del rango completo;
  agrega una fila TOTAL al pie cuando hay más de un período listado) y
  **Ranking de Ventas** (`reportes_repo.ranking_ventas`: TODO lo que se
  vendió junto —artículos de kiosko, bonos de PC, bonos de socios, cargas
  de saldo por tarifa, trámites y bonos de PlayStation 5—, con columna Categoría para distinguir
  de dónde vino cada fila, por cantidad o por monto). La quinta,
  **Resumen del Día** (`turnos_repo.resumen_del_dia`), muestra UN día
  abierto por turno (Mañana/Tarde/Noche, o Domingo T1/T2) con estado
  (Cerrado / En curso / SIN CERRAR / Pendiente), quién cerró y a qué hora,
  cantidad de ventas, Kiosko / Impresiones / Trámites / Alquiler de PCs /
  PlayStation 5 (mismo criterio que Totales), Efectivo/Digital, Total
  y la diferencia del sobre si el Admin ya lo contó; tiene botones de día
  anterior/siguiente y una fila TOTAL DEL DÍA. La plata de cada turno es
  la de su cierre (no la que daría mirar el reloj).
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

`rol` es `ADMIN` o `EMPLEADA`. Una empleada puede recibir permisos para
Artículos, Compras, Consulta de Ventas (sin anular), Reportes, Control de
Cierres y operación de PCs/Miembros; la lista única está en
`usuarios_repo.PERMISOS_EMPLEADA`. Usuarios, Configuración ADMIN y Anular
Venta permanecen exclusivos del Admin. La grilla de PCs es visible para todo
usuario logueado; operar la PlayStation pide Admin o `permiso_control_pcs`.

⚠️ No hay cifrado de la base ni protección contra acceso directo al
archivo `data/kiosko.db` con otra herramienta — la seguridad es a nivel de
la app (login), no del archivo.

## Manejo de errores y logging

Casi todas las acciones de UI que tocan datos están envueltas con el
decorador `@manejar_errores` (`ui/utils.py`): si la función levanta
`ValueError`, se asume un mensaje ya pensado para el usuario y se muestra
tal cual ("No se pudo completar"); cualquier otra excepción se loguea
completa (traceback) en `data/errores.log` vía `errores.registrar_error()` y se
muestra un cartel genérico con el nombre de la excepción, para que el
programa nunca se cierre en silencio. Además `main.py` instala un
`sys.excepthook` global como red de seguridad final para lo que se escape
de ese decorador (por ejemplo, al construir una ventana). El servidor de red
usa el mismo registro sin importar Qt ni guardar claves en el contexto.

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
332 tests al 2026-10-10. Cubren turnos, caja, stock, ventas y anulaciones,
PCs, Miembros, PlayStation 5, Trámites, servidor de red, migraciones y algunas
interacciones de UI. Incluyen límites de fechas, redondeo y apertura de la
interfaz con Qt fuera de pantalla.

## Empaquetado (.exe)

Instalá PyInstaller para armar el ejecutable (`pip install pyinstaller`) y
ejecutá `pyinstaller Kiosko.spec`. El archivo está versionado: empaqueta
`main.py` + `assets/` como app sin
consola (`console=False`), ícono `assets/icono.ico`. La carpeta `data/`
(base + backups) **no** se empaqueta — queda al lado del `.exe` instalado,
así los datos sobreviven a reinstalar/actualizar el programa.

## Estado del repo

El remoto `origin` es `https://github.com/seryluli-cmd/CYBERCONTROL`.
No hay CI configurada; el `.exe` se arma con PyInstaller. Ver
[LEEME.txt](LEEME.txt) para la guía de uso y [docs/HISTORIAL.md](docs/HISTORIAL.md)
para el historial de decisiones.
