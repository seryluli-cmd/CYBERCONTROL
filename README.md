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
| [main.py](main.py) | Entry point. Clase `Aplicacion` alterna `LoginWindow` ↔ `MainWindow` (para poder "cerrar sesión" sin cerrar el programa). Define la hoja de estilos Qt global (botones `primario`/`peligro`/`barra` vía `setProperty("clase", ...)`) y `aplicar_estilo(app)`, que además fija el esquema de color CLARO (con Windows en modo oscuro, los cuadros sin estilo salían negros). `sys.excepthook` propio: cualquier excepción no capturada se loguea en `data/errores.log` y muestra un cartel, en vez de cerrar la app en silencio. |
| [database.py](database.py) · [database_esquema.py](database_esquema.py) · [database_esquema_cajas.py](database_esquema_cajas.py) · [database_migraciones.py](database_migraciones.py) | Conexiones, claves y copias; creación de tablas e índices (las de las cajas con número, en su propio archivo); migraciones de bases existentes. Ver modelo de datos abajo. |
| [turnos.py](turnos.py) · [dominio.py](dominio.py) | Calendario del local y constantes/reglas puras de negocio. |
| [repositories/](repositories/) | Capa de datos, un archivo por tema: artículos, compras, configuración, reportes, turnos (con turnos faltantes y lo vendido en la ventana de un turno, `turnos_ventas_repo.py`), cajas con número (`cajas_repo.py` los datos, `relevo_repo.py` las reglas al entrar y el cierre forzoso, `control_cierres_repo.py` lo que se controla después), trámites, usuarios y ventas. |
| [ui/](ui/) | Una ventana/diálogo por pantalla — ver detalle abajo (`ui/ingreso_caja.py`: lo que pasa con la caja entre el login y la ventana principal). `ui/utils.py` tiene los helpers compartidos (formato de pesos, decorador de manejo de errores, encadenar Enter entre campos). |
| [control_pcs/](control_pcs/) | UI y repositorios de PCs, Miembros y PlayStation 5; el mosaico de monitores de la pantalla principal se dibuja en `control_pcs/ui/pcs_mosaico.py` (solo dibuja: qué estado/color le toca a cada equipo lo decide `pcs_window.py`); el feed de actividad está en `control_pcs/repositories/actividad_repo.py` y el fondo de la pantalla de bloqueo de las PCs en `control_pcs/repositories/fondo_repo.py` + `control_pcs/ui/pcs_fondo_dialogo.py`, y el filtro de palabras en `control_pcs/repositories/filtro_palabras_repo.py` + `control_pcs/ui/pcs_filtro_dialogo.py`. |
| [admin_remoto/](admin_remoto/) · [repositories/admin_remoto_repo.py](repositories/admin_remoto_repo.py) · [ui/admin_remoto_dialogo.py](ui/admin_remoto_dialogo.py) | Administrar desde otra PC del local (ver la sección propia más abajo). |
| [servidor_red.py](servidor_red.py) · [errores.py](errores.py) | API del Cliente PC (todo pedido exige la clave fija de los Clientes PC, ver `clientes_repo.py`; incluye `GET /fondo`, el fondo de la pantalla de bloqueo, y `GET /filtro` + `POST /filtro_bloqueo`, el filtro de palabras) y registro de fallos compartido con la UI. |
| [tests/](tests/) | Tests de repositorios, migraciones, servidor y UI sobre bases SQLite temporales (no tocan `data/kiosko.db`). |
| [tests/test_playstation.py](tests/test_playstation.py) · [tests/test_playstation_ui.py](tests/test_playstation_ui.py) | La PlayStation 5: permisos, catálogos separados, ventas, vencimiento del tiempo, caja/reportes y la migración de `ventas`; y su grilla/panel (con Qt "offscreen", sin abrir ventanas). |
| [Kiosko.spec](Kiosko.spec) | Config de PyInstaller para generar el `.exe`. |
| [assets/](assets/) | Ícono de la app (`icono.ico`/`.png`). |
| [data/backups/](data/backups/) | Copias automáticas de la base (después de cada Cierre de Turno y cada 8 horas; todas las de 3 días y una por día hasta 30) + las de antes de una migración (y las de Limpiar base, que existió hasta el 2026-10-22). |

## Modelo de datos (SQLite, `database_esquema.py`)

- **`usuarios`** — `id` PK, `nombre`, `clave_hash` (`salt$sha256hex`; hashes
  legacy sin salt se siguen aceptando y se migran solos al formato nuevo en
  el próximo login exitoso, ver `usuarios_repo.autenticar` /
  `database.verificar_clave`), `rol` (`ADMIN` | `EMPLEADA`), `activo`
  (soft-delete, nunca se borra un usuario de verdad para no romper el
  historial de ventas/compras/cierres), `fecha_creacion`.
- **`sesiones`** — `id` PK, `usuario_id`, `fecha_hora`, `desde_ip` (NULL = en
  el mostrador; la IP de la otra PC si el Administrador entró desde otra PC
  del local, ver "Administrar desde otra PC"). Una fila por cada
  login exitoso (la inserta `usuarios_repo._registrar_sesion`, junto con la
  migración de hash legacy). No hay horario asignado por empleada en el
  sistema, así que esto (junto con las ventas) es la única pista para
  saber quién podría ser responsable de un turno sin cerrar — ver
  `turnos_faltantes_repo._responsables_del_mes` más abajo (los ingresos desde
  otra PC no cuentan).
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
  (una venta puede tener varias filas — pago mixto Efectivo + Digital; índice
  `idx_venta_pagos_venta`: sin él, Reportes > Por Operador con un año de ventas
  tardaba 6 minutos).
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
- **`reservas`** + **`reservas_pagos`** — las **reservas** de una PC (una
  puntual o "cualquier PC disponible"), PCSTREAM o la PlayStation 5 (pedido del
  dueño, 2026-10-20). La reserva guarda quién y cuándo viene, el equipo y una
  foto del bono (nombre, minutos y precio: el precio queda fijo), su estado
  (`dominio.ESTADOS_RESERVA`: Pendiente, Habilitada, No vino, A reprogramar,
  Vencida, Devuelta) y, al habilitarla, dónde y con qué sesión se usó. Cada
  pago es una venta común (Alquiler de PCs o PlayStation 5) unida a su reserva
  en `reservas_pagos` con su tipo (`ANTICIPO` al reservar, `RESTO` al habilitar,
  `DEVOLUCION`, una venta en negativo): la plata queda en la caja de quien la
  cobra y no hace falta otro origen de venta. Ver
  `control_pcs/repositories/reservas_repo.py`.
- **`cierres_turno`** — `fecha`/`turno` del cierre, `usuario_id` (quién
  cerró), `fecha_cierre` (momento exacto — es el límite "desde" del
  próximo turno), `fondo_cambio`/`ventas_efectivo`/`ventas_digital`/
  `monto_a_retirar`, más `monto_contado`/`diferencia`/`verificado_por`/
  `fecha_verificacion` (nullable, los completa el Admin después desde
  Control de Cierres) y el desglose por origen (`kiosko_*`, `pcs_*`,
  `playstation_*`, cada uno en efectivo y digital).
- **Cajas con número** (`database_esquema_cajas.py`, pedido del dueño
  2026-10-18; reglas en `repositories/relevo_repo.py`). **`cajas`**: una fila
  por caja (su `id` es el número que se ve), con `fecha`/`turno` decididos al
  ABRIRLA (con la tolerancia de `turnos.turno_que_arranca_tras_un_cierre`),
  `abierta_por`/`abierta_en`, `cambio_esperado` (lo que dejó la caja anterior, o
  el Cambio Fijo) y `cambio_contado` (NULL = no contó: la abrió la misma persona
  que acababa de cerrar la anterior), `responsable_id` (cambia en un relevo),
  `cierre_id` (NULL = abierta; nunca hay dos abiertas) y `cierre_forzoso`.
  **`relevos_caja`**: cada vez que la caja pasa de mano sin cerrarse (quien llega
  cuenta TODO el cajón: lo esperado, lo contado y la diferencia).
  **`ventas_caja`**: en qué caja quedó cada venta y `cargada_por` (el Admin que la
  cobró a nombre de la responsable) — tabla aparte y no columnas de `ventas` para
  no tocar la reconstrucción de la tabla madre. **`verificaciones_cierre`**: cada
  conteo del sobre (el último sigue también en `cierres_turno`). La plata de un
  cierre sigue saliendo de la ventana entre cierres; la caja aporta el turno, el
  responsable y lo que se contó.
- **`configuracion`** — tabla genérica clave/valor. Incluye el fondo de
  cambio, el indicador de rubros iniciales, tarifas y la contraseña de admin de
  los Clientes PC. Las claves exactas están centralizadas en los repositorios
  que las usan. La clave de CONEXIÓN de los Clientes PC ya no se guarda acá: es
  fija y el programa conserva solo su huella (`clientes_repo.py`); la fila
  `clave_clientes` (o `clave_agentes`) que haya quedado en una base anterior se
  borra sola al arrancar (`_migrar_borrar_clave_vieja_de_clientes_pc`, pedido del
  dueño 2026-10-17).
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
  ⚠️ Ese "momento en que empezó" se toma con una **tolerancia de
  `TURNO_GRACIA_MIN` (40 min)**, `turnos.turno_que_arranca_tras_un_cierre`:
  un cierre hecho hasta 40 minutos ANTES del cambio de turno (el que se va a
  las 13:55) cuenta como el cierre del turno que termina, y lo que sigue ya es
  del turno nuevo. Sin eso, cerrar un par de minutos antes de las 14, las 22
  o las 06 corría de turno a todos los cierres siguientes (la Tarde quedaba
  como "Mañana") y el reporte mostraba "SIN CERRAR" un turno que sí se cerró
  (`TestCierreHechoUnPocoAntesDelCambioDeTurno`). El primer cierre de todos
  no tiene cierre anterior: usa la hora en que se hace.
  ⚠️ **Con una caja abierta, el turno y el día del cierre son los de la caja**
  (decididos al abrirla, ver "Cajas con número"): quien abre a las 07:00 después
  de una noche sin uso abre la Mañana, aunque el cierre anterior haya sido a las
  22:05 (`TestCerrarCaja` en `tests/test_cajas.py`).
- **`turnos.turno_vencimiento(dia, turno)`** — momento en que un turno
  de un día dado queda vencido: su fin (`turnos.fin_del_turno`) +
  `MINUTOS_PARA_CIERRE_FORZOSO` (30 min, pedido del dueño 2026-10-20; del
  2026-10-18 a ese día eran 15, y antes 40). A esa hora la caja se cierra sola (cierre forzoso) y el turno pasa a
  contar como sin cerrar. El botón Cierre de Turno titila desde
  `turnos.inicio_del_aviso_de_cierre` (5 min antes del fin). **`turnos_repo.turnos_del_mes_actual()`**
  arma la grilla de turnos esperados del mes en curso (día 1 a hoy,
  domingo con 2, el resto con 3) y **`turnos_repo.turnos_faltantes()`**
  la cruza contra `cierres_turno` para devolver los que ya vencieron y
  todavía no se cerraron, agregándole a cada uno `"usuarios"`: quién
  vendió algo o **inició sesión** en esa ventana, según
  `turnos_faltantes_repo._responsables_del_mes` (combina `ventas` y la tabla
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

**Backups** (`repositories/copias_repo.py`, desde el 2026-10-19): un hilo que
arranca `main.py` en el mostrador revisa cada minuto y copia `data/kiosko.db` →
`data/backups/kiosko_AAAA-MM-DD_HHMMSS.db` en caliente (Online Backup API de
SQLite) después de cada Cierre de Turno (manual, en ausencia o forzoso: se mira
`MAX(cierres_turno.fecha_cierre)`) y, si no hubo ninguno, cada 8 horas. Cada copia
va además a las "otras carpetas" que elige el Admin (otro disco, una carpeta
compartida de otra PC; usuario y clave de red se le pasan a Windows con `cmdkey`,
no se guardan); si una no está, la copia llega cuando vuelve. Quedan todas las de
los últimos 3 días con copias y una por día hasta 30. Pantalla: Usuarios →
"Copias de Seguridad" (`ui/copias_dialogo.py`), con "Hacer copia de seguridad ahora" y una
copia suelta a un pendrive (`database.copiar_backup_a`).

## Pantallas (`ui/` y `control_pcs/ui/`)

`MainWindow` muestra la grilla de PCs y la PlayStation 5 como panel principal;
el resto se abre en diálogos. Arma los accesos según rol y permisos.

La "grilla" es un **mosaico de monitores** sobre fondo oscuro (desde el
2026-10-16, pedido del dueño con el aspecto de los programas de cyber):
`pcs_mosaico.MosaicoDeEquipos` (un `QListWidget` en modo íconos, así la
selección, el teclado y el acomodo según el ancho los resuelve Qt) con un
delegado que pinta con QPainter cada monitor: la pantalla con el color del
estado (`COLOR_*` de `pcs_window.py`, con su leyenda arriba), un dibujito
(reloj = sesión con bono, personitas = socio, triángulo = alerta, candado
abierto = sin bloqueo), monedas si corre con bono, joystick en la consola, y
abajo el tiempo, el nombre y un aviso corto. `PanelControlPcs` arma una
`pcs_mosaico.Ficha` por equipo (`_ficha_de_pc` / `_ficha_de_playstation`); el
refresco de 5s actualiza los casilleros en su lugar si siguen siendo los mismos
equipos (no parpadea ni pierde la selección). Las estaciones salen en **orden
natural** (PC2 antes que PC10, `pcs_repo._orden_natural`). Van **8 equipos por
fila** (`pcs_mosaico.EQUIPOS_POR_FILA`, pedido del dueño 2026-10-17), repartidos
a lo ancho: `MosaicoDeEquipos._repartir_columnas` ensancha cada columna al
cambiar el tamaño, descontando la barra de desplazamiento (Qt la reserva aunque
no se vea). Si la ventana es tan angosta que no entran 8 casilleros enteros,
pasa antes a la fila de abajo en vez de achicarlos.

El panel lateral (`pcs_detalle.PanelDetalleEstacion`) vende el bono tildado con
el botón **Cobrar** ("Cobrar y Agregar Bono" si el equipo ya tiene una sesión
en curso): abre la misma ventana de cobro que Ventas (`dialogo_pago.cobrar` →
`DialogoPago`), donde se elige el medio, se reparte y se ve el vuelto; si pagan
justo, un Enter cobra. Pedido del dueño, 2026-10-18: antes el panel tenía un
combo "Método de pago" e "Iniciar Sesión".

**Ingreso con caja** (`ui/ingreso_caja.py`, entre el login y la ventana
principal; reglas en `relevo_repo.situacion_al_entrar`; pedido del dueño
2026-10-18). Una empleada no entra sin caja: si no hay ninguna abierta, abre una
contando el Cambio Fijo (si la abre la misma persona que acaba de cerrar la
anterior, no cuenta); si la caja abierta es de otra y su turno sigue, la
**recibe** contando todo el cajón (el reemplazo que llegó tarde: lo vendido por
quien cubrió va en su sobre); si el turno de esa caja ya terminó (desde 5 minutos
antes del fin), la **cierra en ausencia** de la otra y después abre la suya; si
quedaron ventas sin caja, las cierra aparte primero. El conteo es **a ciegas**
(`DialogoContarPlata`: primero se escribe lo contado, después se ve cuánto tenía
que haber). El Admin entra directo, sin caja: lo que cobra queda a nombre de la
responsable de la caja abierta, con `ventas_caja.cargada_por` (pedido del dueño:
"que lo asiente como la empleada que estaba antes de que yo entrara").

**En la ventana principal**, al lado del nombre se ve la caja ("Caja Nº 12 ·
Mañana"). Cada 10 s `MainWindow._revisar_la_caja` mira `relevo_repo.estado_de_la_caja`:
desde 5 minutos antes del fin del turno el botón **Cierre de Turno titila en
rojo** (clase `alerta` de la hoja de estilos) y a los 30 minutos del fin hace el
**cierre forzoso** (`relevo_repo.cierre_forzoso_si_corresponde`) y vuelve al
ingreso (el Admin se queda). Si hay un cobro a medias (una pantalla abierta
encima), espera; Ventas con el carrito vacío y Caja se cierran solas
(`se_puede_cerrar_sola`).

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
- **Impresiones** (`impresiones_window.py`, `DialogoImpresiones`) — botón de
  la barra entre "Vender" y "Trámites" (pedido del dueño, 2026-10-19): cobro
  rápido del artículo de impresiones (`dominio.CODIGO_ARTICULO_IMPRESIONES`,
  el código 4) sin entrar a Vender. Se escribe la cantidad (arranca en 1),
  Enter abre la ventana de cobro de siempre (`DialogoPago`) y otro Enter
  cobra. Se graba con `impresiones_repo.cobrar_impresiones` como una venta de
  kiosko común del artículo (descuenta stock, entra en la caja abierta, sale en
  el Detalle del Día); si alguien cambió el precio mientras se cobraba, no
  graba nada. Si el artículo no está cargado con ese código, avisa y no abre.
- **Trámites** (`tramites_window.py`, `DialogoTramites`) — botón de la
  barra entre "Impresiones" y "Miembros". Se elige un trámite del catálogo, se
  tipea el monto (libre, en $) y "Cobrar" abre la misma ventana de cobro
  que Ventas (`dialogo_pago.cobrar`, igual que Cargar Saldo de un socio y
  los bonos de Control de PCs; antes había un combo "Medio de pago") y se
  graba con
  `tramites_repo.registrar_tramite`. No tiene origen propio (se graba como
  **Kiosko**), pero en Caja y Cierre de Turno va en su renglón; en Reportes sale en columna aparte
  (Totales y Resumen del Día) y en el Ranking de Ventas. El Admin ve además
  "Gestionar trámites" (`DialogoGestionTramites`: Nuevo / Modificar /
  Desactivar), que también está en Configuración ADMIN. En Consulta de
  Ventas el trámite se ve como una fila "Trámite: <nombre>".
- **PlayStation 5** (`control_pcs/ui/pcs_window.py` + `pcs_detalle.py`) — es
  el primer monitor del mosaico de Control de PCs, antes de las PCs, con el
  nombre fijo "PLAYSTATION 5" (no se edita, no se da de baja, no tiene menú de
  PC). Al elegirla, el panel lateral habilita **solo** sus bonos (que van
  debajo de los de PC, que quedan deshabilitados); al elegir una PC pasa lo
  inverso, y un bono nunca puede cobrarse al equipo equivocado
  (`PanelDetalleEstacion` toma la lista del equipo elegido, y los repos
  validan cada uno su catálogo). Muestra una cuenta regresiva que se redibuja
  cada segundo; al llegar a cero su monitor **titila en rojo** hasta que el
  operador avise a los clientes y la libere ("Ya avisé: liberar la consola")
  o venda otro bono — no se da de baja sola como una PC. Vender un bono y
  liberarla lo puede hacer cualquier operador logueado; crear/modificar/dar
  de baja sus bonos es solo del Admin, desde Configuración ADMIN →
  "Gestionar Bonos de PlayStation 5". Ver `playstation_repo.vender_bono`.
- **Reservas** (`control_pcs/ui/reservas_window.py` + `reservas_dialogos.py`;
  botón "📅 Reservas · N hoy" de la barra, solo en el mostrador) — pedido del
  dueño, 2026-10-20 (parte 1: la plata). Un cliente reserva un equipo para otro
  momento y paga una seña o todo; cuando vuelve puede ser otro turno. Nueva
  reserva cobra lo que paga ahora con la ventana de cobro de siempre (queda en la
  caja de quien la toma); Habilitar dice cuánto pagó, cuándo y a quién, cobra lo
  que falta (queda en la caja de quien habilita) y abre el equipo con el bono
  reservado. **Habilitar una reserva ya pagada no crea ninguna venta.** Si no
  viene (sola, a la hora + 20 minutos, o con "No vino"): con seña la pierde; si
  pagó todo queda "A reprogramar" (otro día, con cualquier PC disponible) y vence
  a los 5 días. Ninguna de las dos cosas mueve plata. Devolver plata es solo del
  Admin: una venta en negativo en la caja de ahora (el cierre viejo no se toca).
  Reglas en `control_pcs/repositories/reservas_repo.py` y
  `reservas_habilitar_repo.py`.
  Parte 2 (2026-10-21, `reservas_horario_repo.py`): 2 horas antes de la hora, la
  PC, PCSTREAM o la consola reservada se ve celeste en el mosaico ("Reservada" en
  la leyenda, con el cliente y la hora; si está en uso conserva su color y dice
  "Res. 10:00"), y la pantalla de bloqueo de la PC muestra "RESERVADA para Juan ·
  hoy 10:00" (Cliente PC V1.2). Venderle a otro cliente un bono que se pasa de la
  hora avisa antes de cobrar; un socio entra solo hasta la hora y lo demás le
  queda en el saldo. Las de "Cualquier PC disponible" van en un aviso arriba del
  mosaico, con cuántas PCs libres hay.
- **Caja** (`caja_window.py`, `CajaWindow`) — solo lectura, resumen del
  turno en curso vía `turnos_repo.resumen_turno_actual()` (número de caja y
  responsable, caja inicial = el cambio con que arrancó la caja, caja actual =
  caja inicial + efectivo, ventas efectivo/digital, y el desglose Kiosko /
  Impresiones / Trámites / Alquiler de PCs / PlayStation 5 / Reservas, cada uno
  con su efectivo y digital). La caja actual
  excluye a propósito lo cobrado en digital.
- **Cierre de Turno** (`caja_window.py`, `CierreTurnoWindow`) — cualquiera
  cierra su propio turno. Muestra preview y, al confirmar, llama a
  `turnos_repo.cerrar_turno(usuario['id'])`: `monto_a_retirar` = lo
  vendido en efectivo (el cambio con que arrancó la caja se queda en el cajón
  para el turno siguiente; `cambio_que_queda`). Si quien cierra no es la
  responsable de la caja (el Admin), queda anotado como cerrada en su ausencia. Esta pantalla es el resumen que las empleadas le
  mandan al dueño; se dibuja con `ui/tarjeta_cierre.py` (`TarjetaCierreDeTurno`),
  la misma tarjeta con que "Ver Detalle" de Control de Cierres muestra después
  cada cierre ya hecho, también el forzoso. En pantalla el fondo de cambio se llama **"Cambio Fijo"**
  en todos lados (pedido del dueño; por dentro sigue siendo `fondo_cambio`).
  Muestra Efectivo, Digital y **TOTAL** (`resumen["ventas_total"]`: todo lo
  cobrado, sin sumar aparte impresiones ni trámites). **Kiosko, Impresiones
  y Trámites van en renglones separados**, cada uno con su efectivo y digital
  (pedido del dueño, 2026-10-19; antes Impresiones y Trámites eran renglones
  "incluidos en Kiosko"): `resumen["kiosko_solo_*"]`, `["impresiones_*"]` y
  `["tramites_*"]`. Los tres suman lo que se graba como Kiosko en el cierre
  (`kiosko_efectivo`/`kiosko_digital`, que no cambian); el reparto entre
  efectivo y digital se hace venta por venta con sus pagos
  (`turnos_ventas_repo._aparte_por_metodo`): exacto si las impresiones se
  cobraron solas, en proporción si iban en un carrito pagado en los dos medios.
  Lo mismo con las **Reservas** (variante A, elegida por el dueño el
  2026-10-20): un renglón propio al lado de Alquiler de PCs, sacado de Alquiler
  de PCs y de PlayStation 5 (`resumen["pcs_solo_*"]`, `["playstation_solo_*"]`,
  `["reservas_*"]`), con un renglón chico abajo ("1 seña · 1 resto") y, al pie,
  las reservas que se habilitaron ya pagadas de otro turno (no suman acá). Lo
  que se graba en el cierre no cambia.

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
  compras en positivo, ventas confirmadas en negativo/rojo, y los "ajuste de
  stock" con lo que sumaron o restaron). La grilla (columnas, rojo bajo el
  mínimo) vive en `ui/articulos_tabla.py`, compartida con ORDENAR Stock.
- **ORDENAR Stock** (`ordenar_stock_window.py`, `OrdenarStockWindow`; pedido
  del dueño 2026-10-20) — botón de Artículos que solo ve el Admin y que pide
  una contraseña fija (en el código está solo su hash con salt,
  `articulos_repo.CLAVE_ORDENAR_STOCK`; este repo es público). Abre la misma
  grilla con la columna Stock para escribir (fondo amarillo): Enter guarda y
  pasa al de abajo; con la pistola, escanear en el buscador y, si queda un solo
  artículo, el Enter abre su stock. Cada cambio pasa por
  `articulos_repo.ajustar_stock(usuario_id, codigo, stock_nuevo, clave)`, que
  vuelve a exigir Admin activo y contraseña, toma el stock "antes" de la base
  (no de la pantalla), acepta solo enteros de 0 para arriba y anota cada cambio
  en `ajustes_stock`. No toca precios, costos ni la caja. También corrige el
  CÓDIGO de un artículo cargado mal a mano (amarillo también; doble clic, escanear
  o escribir, Enter y confirmar): `articulos_repo.cambiar_codigo` lleva sus
  ventas, compras y ajustes al código nuevo y lo anota en `cambios_codigo` y en
  Movimientos. Es el único lugar donde se cambia un código.
- **Compras** (`compras_window.py`, `ComprasWindow`) — carga de mercadería
  por escaneo (mismos F5/F6/F7 que Ventas). Al escanear pide cantidad y
  costo (precargado con el `precio_compra` actual) por `QInputDialog`.
  Confirmar llama a `compras_repo.registrar_compra` con todo el lote junto.
- **Consulta de Ventas** (`consulta_ventas_window.py`,
  `ConsultaVentasWindow`) — últimas 100 ventas
  (`ventas_repo.listar_ventas_recientes`), con la fecha como "16/10/2026 22:13"
  (`ui.utils.formato_fecha_hora`), resalta ANULADA. Botón "Anular
  venta" (solo si `self.es_admin`) pide motivo obligatorio y llama a
  `ventas_repo.anular_venta`, que **repone el stock** de cada línea y
  marca `estado='ANULADA'` con auditoría (quién/cuándo/por qué).
- **Reportes** (`reportes_window.py`, `ReportesWindow`) — 6 tabs. Cuatro
  con filtro Desde/Hasta y atajo "Solo Hoy": **Resumen de Ventas**
  (`reportes_repo.resumen_ventas`: total + desglose efectivo/digital),
  **Por Turno** (`reportes_repo.resumen_por_turno`: mismo desglose pero
  separado por Mañana/Tarde/Noche, siempre las 3 aunque alguna quede en
  $0), **Totales** (`reportes_repo.resumen_por_origen`: cuánto se
  facturó de Kiosko, de Impresiones, de Trámites, de Alquiler de PCs y de
  PlayStation 5 — ver
  `dominio.ORIGENES_VENTA`, `dominio.CODIGO_ARTICULO_IMPRESIONES` y
  `tramites_repo`; las impresiones (el artículo código 4, el que más se vende) y los trámites (ganancia
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
  la de su cierre (no la que daría mirar el reloj). Como un cierre se anota
  donde EMPEZÓ lo que cierra, un cierre hecho tras días sin cerrar cae en el
  turno viejo y las filas de hoy salen en cero: por eso arriba de la tabla
  aparece un aviso azul ("Hoy se cerró un turno que quedó anotado en otro
  día", con botón "Ver el dd/mm/aaaa"), que sale de
  `resumen_del_dia()["cierres_de_otro_dia"]`, y en el día donde quedó anotado
  el estado dice "Cerrado el dd/mm" (`"cerrado_otro_dia"`). La Noche que se
  cierra a la madrugada (lo normal) no dispara nada
  (`turnos_repo._cerrado_pasado_su_vencimiento`). Abajo de los turnos (pedido del
  dueño 2026-10-18; `ui/reportes_resumen_dia.py` + `ui/reportes_detalle_dia.py`,
  datos de `detalle_dia_repo.detalle_del_dia`) va el **detalle de todo lo vendido**
  del día, o del turno que se toque: **renglón por renglón** (cada cosa tal cual
  se cobró: hora, turno, operador, Nº de venta, código, descripción, cantidad y
  total, con la fila TOTAL; 14 impresiones juntas son un renglón de 14, 4 cobradas
  por separado son 4 renglones; el botón **Imprimir** abre la vista previa de ese
  listado en hojas A4, `ui/imprimir.py`, y desde ahí se imprime o se guarda en PDF
  con "Microsoft Print to PDF"), venta por venta (Nº, hora, turno, operador
  —"(cargó X)" si la cobró el Admin—, rubro, qué se vendió con cantidades: "2 x
  Coca 500", "PC1 · 3 horas (3 h)" con la PC donde estaba al venderlo aunque
  después se la cambiara de máquina, PCSTREAM, PlayStation 5, socios y trámites —,
  efectivo, digital, total y si se anuló), lo vendido por producto y por operador.
  Qué venta es de qué turno sale de `turnos_repo._ventanas_del_dia`, la misma
  función que arma las filas, así el detalle de un turno suma lo mismo que su fila
  (salvo una venta anulada después de cerrar, que el cierre sí cuenta: se marca).
  La sexta, **Por Operador**
  (`ui/reportes_operador.py`, archivo aparte por la regla 12; pedido del dueño
  2026-10-17), con Desde/Hasta y "Solo Hoy": arriba
  `reportes_repo.resumen_por_operador` (por usuario: ventas confirmadas,
  anuladas, efectivo, digital y total, de mayor a menor) y abajo, del operador
  elegido, `reportes_repo.ventas_de_operador` (cada venta con fecha y hora,
  turno, origen, concepto —"2 x Coca 500" o "Trámite: ..."—, efectivo, digital,
  total y estado; las anuladas en rojo, sin sumar). No hizo falta tocar la base:
  `ventas.fecha` (con la hora) y `ventas.usuario_id` se graban desde siempre. La
  venta queda a nombre de quien tenía la SESIÓN abierta, salvo lo que cobra el
  Admin con la caja de una empleada abierta: queda a nombre de ella
  (`cajas_repo._quien_vende`). El turno se rotula con
  `turnos.dia_en_que_empezo_el_turno` (una venta del lunes a la 01:00 es
  "Domingo T2", no "Noche").
- **Control de Cierres de Turno** (`control_cierres_window.py`,
  `ControlCierresWindow`; se reexporta desde `caja_window.py`) — lista
  `turnos_repo.listar_cierres()` (que vive en `control_cierres_repo.py`):
  columna Turno con la etiqueta de `etiqueta_turno` (incluye "Domingo T1"/"T2"),
  Caja ("Nº 12" o "sin caja"), Responsable (quien la abrió → quien la recibió),
  Apertura ("05:55 · contó $ 50.000,00 (coincide)") y Cierre ("A horario 14:00",
  "Forzoso 14:30" o "Gaby, en ausencia de Lucía", estos dos en rojo); resalta en
  rojo si `|diferencia| > 0.01`. "Cargar monto contado" (visible solo para el
  Admin; el repo también lo exige) abre `QInputDialog` y llama a
  `turnos_repo.verificar_cierre`, que guarda cada conteo en
  `verificaciones_cierre`. El detalle de un cierre muestra, a la izquierda, el
  cierre tal como lo mostraba la pantalla Cierre de Turno (la misma tarjeta,
  `ui/tarjeta_cierre.py`, con `detalle_cierre()["resumen"]`; también el cierre
  forzoso, que no vio nadie) y abajo cómo se cerró (en rojo si fue forzoso o en
  ausencia); a la derecha, la caja, los relevos, los conteos del sobre y la lista
  de ventas con, en cada una, quién la cargó si fue el Admin. Arriba de la
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
  borrar del todo a alguien ya desactivado), "Configurar Cambio Fijo"
  (`config_repo`), "Copias de Seguridad" (`ui/copias_dialogo.py`, ver Backups).
  También `DialogoCambiarClave` (accesible para cualquier rol desde el
  menú principal, no desde esta pantalla) — cambia la clave propia
  pidiendo la actual como confirmación (`usuarios_repo.cambiar_clave`).
- **Fondo de pantalla de las PCs** (`control_pcs/ui/pcs_fondo_dialogo.py`,
  `DialogoFondoPantalla`; botón "Fondo de pantalla de las PCs..." de Gestionar
  Estaciones, en Configuración ADMIN) — la imagen que se ve detrás del cartel de la
  pantalla de bloqueo de cada PC cliente. "Elegir imagen..." abre un JPG, PNG, BMP,
  WEBP o GIF; `preparar_jpeg` respeta la orientación de las fotos de celular, la achica
  a 1920x1080 sin deformarla (una más chica no se agranda: la PC la ajusta a su
  pantalla), rellena las transparencias con el azul del bloqueo y la pasa a JPEG,
  bajando la calidad si hace falta para entrar en 2 MB. `fondo_repo.guardar_jpeg` la
  deja en `data/fondo_bloqueo.jpg` (fuera de git y de las copias de seguridad de la
  base). "Quitar fondo" vuelve al azul liso. Cada Cliente PC lo pide al arrancar
  (`GET /fondo`, ver `servidor_red.py`) y las que están prendidas se enteran solas,
  porque `GET /estado` trae `fondo_version` (la huella del contenido).
- **Filtro de palabras de las PCs** (`control_pcs/ui/pcs_filtro_dialogo.py`,
  `DialogoFiltroPalabras`; botón "Filtro de palabras de las PCs..." de Gestionar
  Estaciones; pedido del dueño, 2026-10-17: "protección antiporno") — prender/apagar,
  la lista (una palabra o frase por renglón) y el mensaje que ve el cliente, más las
  últimas páginas cerradas. Con una sesión en curso, cada Cliente PC mira el título de
  la ventana de adelante y, si tiene una palabra de la lista (entera, sin mayúsculas
  ni acentos), cierra la pestaña, muestra el mensaje y avisa (`POST /filtro_bloqueo`):
  queda en `bloqueos_filtro_pc` y en "Actividad reciente". La lista vive en
  `configuracion` (`filtro_palabras_repo`); viene prendida con la que el dueño usaba en
  su programa anterior. Llega a las PCs como el fondo: `filtro_version` en cada
  `GET /estado` y `GET /filtro` si cambió. Cómo busca y lo medido (menos de una
  milésima de un núcleo): README de CLIENTE PC, "Filtro de palabras".
- **IP asentada de cada estación** (Gestionar Estaciones, columna "IP asentada";
  pedido del dueño, 2026-10-17) — la primera vez que el Cliente PC de una PC se
  conecta, `pcs_repo.registrar_conexion` asienta la IP real del pedido
  (`estaciones.ip_asentada`) y después no la pisa (`ultima_ip` sí cambia en cada
  conexión). `pcs_repo.estado_de_estacion` reconoce a cada PC por el nombre que manda
  y, si ninguna estación activa se llama así (se renombró acá, o se tipeó distinto
  allá), por esa IP; si la IP está asentada en dos estaciones activas no adivina y la
  pantalla lo marca en rojo con un aviso. "Traer IP" relee la base; "Borrar IP" la
  olvida para que se asiente la nueva. No hizo falta tocar el Cliente PC.

## El tiempo de las PCs cuando el mostrador no está

Explicación para el dueño, con ejemplos: [docs/TIEMPO_DE_LAS_PCS.md](docs/TIEMPO_DE_LAS_PCS.md).

- **Cerrar sesión no toca a las PCs:** el servidor de red arranca con el programa
  (`main.main`) y sigue contestando sin nadie logueado.
- **Una sesión que ya llegó a cero no se estira** (`pcs_repo._abrir_o_extender_sesion`):
  se cierra y se abre otra. Sin nadie logueado no hay pantalla que cierre las
  sesiones vencidas, y un socio que entraba a esa PC quedaba pegado a la del cliente
  anterior. Una sesión cerrada tarde queda con la hora en que llegó a cero
  (`pcs_repo._cerrar_sesion`).
- **Al volver de un corte gana el tiempo menor y el mostrador lo guarda**
  (`control_pcs/repositories/reconexion_repo.py`, pedido del dueño 2026-10-20). El
  Cliente PC manda en `GET /estado` cuánto le queda según su cuenta (`sesion`,
  `resto`, `desde`); el mostrador le suma lo que se cargó durante el corte, y si
  igual es menos, corre el fin de la sesión y lo anota en `ajustes_reconexion_pc`
  ("Actividad reciente"). Nunca sube el tiempo; diferencias de hasta 30 s no se tocan.

## Administrar desde otra PC (`admin_remoto/`)

Pedido del dueño (2026-10-18): desde su casa entra por UltraVNC a una PC libre
del local y administra desde ahí mientras el mostrador sigue atendiendo. Diseño
y decisiones en [docs/ADMIN_REMOTO.md](docs/ADMIN_REMOTO.md).

- **Cómo se abre:** el mismo `CyberBios.exe`, abierto desde la carpeta
  compartida del mostrador. `admin_remoto/modo.py` lo reconoce (ruta
  `\\PC\carpeta` o unidad de red) y esa copia NO abre ninguna base: le habla al
  CyberBIOS de esa PC. Para probar: `python main.py --mostrador <ip>`.
- **Cómo viaja:** `POST /admin/...` en el mismo servidor de red de las PCs (puerto
  8899; esas rutas no usan la clave de los Clientes PC sino la del
  Administrador). `admin_remoto/cliente.instalar` reemplaza en su módulo cada
  función de `admin_remoto/lista_blanca.py` por un representante que manda la
  llamada; las pantallas no se enteran. Por eso **ninguna pantalla importa una
  función suelta de un repo** (un test lo vigila). Los datos van con
  `admin_remoto/codec.py` (filas, tuplas, fechas, bytes; `clave_hash` nunca viaja).
- **Quién entra** (`repositories/admin_remoto_repo.py`): viene apagado
  (Configuración ADMIN > Entrar desde otra PC, solo en el mostrador); solo un
  ADMIN activo; cada ingreso queda en `sesiones.desde_ip`. El servidor
  (`admin_remoto/servidor.py`) da una sesión al azar atada a la IP, que vence a
  las 3 h sin uso; 5 claves mal desde una PC la frenan 5 minutos (de a una prueba por PC, y
  un tope de 20 claves mal en 15 minutos para todas juntas); en cada pedido
  vuelve a mirar que la entrada siga prendida y el usuario siga siendo Admin; y
  el "quién lo hizo" (`lista_blanca.ACTOR`) lo pone el mostrador.
- **Qué no se puede desde otra PC:** vender, cobrar, abrir/cerrar cajas y
  turnos, la grilla de PCs, Miembros, Actualizar el
  Cliente PC y las Copias de Seguridad (las pantallas lo esconden con
  `modo.es_copia_remota()`, y la lista blanca lo rechaza igual). El cierre
  forzoso de la caja lo hace solo el mostrador.
- **Las dos copias tienen que ser el mismo .exe:** `lista_blanca.huella()`
  (funciones, parámetros y actores) se compara al entrar.

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
`usuarios_repo.PERMISOS_EMPLEADA` (ese último permiso ya no gobierna nada
funcional desde el 2026-10-19: Miembros y la PlayStation 5 abren para
cualquier operador logueado, igual que la grilla de PCs). Usuarios,
Configuración ADMIN y Anular Venta permanecen exclusivos del Admin.

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
753 tests al 2026-10-18. Cubren turnos, caja y cajas con número
(`tests/test_cajas.py`, `tests/test_cajas_ui.py`), el detalle del día (`tests/test_detalle_dia.py`), administrar desde otra PC
(`tests/test_admin_remoto.py`, con un mostrador de prueba en otro proceso:
`tests/mostrador_de_prueba.py`), stock, ventas y anulaciones,
PCs, Miembros, PlayStation 5, Trámites, reservas (`tests/test_reservas.py`,
`tests/test_reservas_ui.py`), servidor de red (con el fondo de pantalla
y el filtro de palabras de las PCs), migraciones y algunas interacciones de UI. Incluyen límites de fechas, redondeo y apertura de la
interfaz con Qt fuera de pantalla.

## Empaquetado (.exe)

Instalá PyInstaller para armar el ejecutable (`pip install pyinstaller`) y
ejecutá `pyinstaller Kiosko.spec`: genera `dist/CyberBios.exe`. El archivo está versionado: empaqueta
`main.py` + `assets/` como app sin
consola (`console=False`), ícono `assets/icono.ico`. La carpeta `data/`
(base + backups) **no** se empaqueta — queda al lado del `.exe` instalado,
así los datos sobreviven a reinstalar/actualizar el programa.

## Estado del repo

El remoto `origin` es `https://github.com/seryluli-cmd/CYBERCONTROL`.
No hay CI configurada; el `.exe` se arma con PyInstaller. Ver
[LEEME.txt](LEEME.txt) para la guía de uso y [docs/HISTORIAL.md](docs/HISTORIAL.md)
para el historial de decisiones.
