# Historial de cambios y decisiones

Este archivo conserva íntegra la cronología que estaba en CLAUDE.md.
Las reglas vigentes están en CLAUDE.md y la referencia técnica actual en README.md.

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

**2026-10-08:** **Impresiones como renglón propio en Reportes.** Pedido del
dueño: IMPRESIONES es el producto Nº 1 del kiosko y quería verlo aparte en los
reportes. Sigue siendo un artículo de kiosko más (se vende por el mismo
mostrador, `origen` KIOSKO, descuenta stock); lo único que cambia es cómo se
muestra: las pestañas **Totales** y **Resumen del Día** ahora traen la columna
**Impresiones** entre "Kiosko" y "Alquiler de PCs", y **Kiosko** pasó a ser el
resto de lo vendido SIN las impresiones (las tres columnas suman el total, nada
se cuenta dos veces). Se lo reconoce por `dominio.CODIGO_ARTICULO_IMPRESIONES`
(`"1"`, el código del artículo en la base real); si ese artículo no existe, la
columna da $0. Cálculo: `reportes_repo.resumen_por_origen` (suma
`venta_detalle.subtotal` por período, resta de Kiosko) y
`turnos_repo._vendido_aparte_entre` (antes `_impresiones_entre`) / `resumen_del_dia` (misma ventana
`(desde, hasta]` de cada cierre, sin tocar `cierres_turno`: el cierre sigue
guardando UN solo importe de Kiosko). Ojo: **Caja, Cierre de Turno y Resumen de
Ventas NO cambiaron** -- ahí las impresiones siguen sumadas dentro de Kiosko, y
Efectivo/Digital tampoco cambian en ningún reporte (las impresiones también
entran por esos medios). El Ranking de Ventas ya las mostraba como una fila
más. 221 tests (4 nuevos en `TestResumenPorOrigen` y `TestResumenDelDia`).

**2026-10-08 (más tarde):** **botón "Trámites"** en la barra principal, entre
"Vender" y "Miembros". Pedido del dueño: servicios que los empleados le hacen
al cliente en el mostrador (sacar e imprimir una boleta de luz o gas, trámites
online, sacar turnos... cosas que mucha gente grande no sabe hacer sola) y se
cobran con un monto libre en $, con un catálogo que arma el Admin. **Se cobra el
servicio, NO la boleta** (esa plata no pasa por la caja): es ganancia pura, sin
stock ni costo. Lo ve cualquiera logueado (`ui/tramites_window.DialogoTramites`:
elegir trámite, tipear monto, medio de pago Efectivo/Digital/Mixto con el mismo
`resolver_pagos` de Cargar Saldo). El Admin agrega/edita/desactiva trámites
desde "Gestionar trámites" dentro del mismo diálogo o desde Configuración ADMIN
(`DialogoGestionTramites`). Tablas nuevas `tramites` y `tramites_venta`
(`CREATE TABLE IF NOT EXISTS`, sin migración). `tramites_repo.registrar_tramite`
arma la venta con `ventas_repo.registrar_venta_sin_detalle` (origen **KIOSKO**) y
la liga al trámite en la misma transacción; el nombre se guarda como foto, así
renombrar un trámite no cambia el historial. **Decisión a tener presente:** no
tiene origen propio, así que Caja y Cierre de Turno lo cuentan DENTRO de Kiosko (no
se tocó `cierres_turno`); en Reportes sale aparte, ver la entrada siguiente. Consulta
de Ventas muestra la fila "Trámite: <nombre>" en el detalle; anular funciona como en
cualquier venta. 235 tests (14 nuevos en `TestTramites`).

**2026-10-08 (más tarde todavía):** **los trámites salen aparte en Reportes**, igual
que las Impresiones (el dueño aclaró que son ganancia 100%: los hace un empleado, sin
costo). **Totales** y **Resumen del Día** traen la columna **Trámites** entre
"Impresiones" y "Alquiler de PCs" (`reportes_repo.resumen_por_origen` y
`turnos_repo.resumen_del_dia` devuelven `tramites`), y **Kiosko** pasa a ser el resto
SIN impresiones ni trámites: Kiosko + Impresiones + Trámites + PCs = Total. El
**Ranking de Ventas** ahora lista los trámites como quinta fuente (categoría
"Trámite", agrupados por el nombre que tenían al cobrarse; hasta acá faltaban porque
no tienen `venta_detalle`). Caja, Cierre de Turno, Resumen de Ventas y Por Turno NO
cambiaron: ahí siguen dentro de Kiosko. El helper que calcula lo que se muestra
aparte en el Resumen del Día es ahora `turnos_repo._vendido_aparte_entre`
(reemplaza a `_impresiones_entre`; `_LINEAS_APARTE` lista las columnas, así que una
tercera sale barata). **Bug corregido de paso (afectaba a Impresiones desde el mismo
día):** el cierre guarda una foto de lo cobrado, así que una venta anulada DESPUÉS
del cierre sigue sumada en su importe de Kiosko; como impresiones/trámites se
calculaban ignorando las anuladas, esos pesos pasaban a verse como "Kiosko". Ahora
para un turno ya cerrado se cuentan también las anuladas con `anulada_fecha`
posterior al cierre (`cierre_grabado=True`, comparando con `julianday` porque
`anulada_fecha` se graba con segundos y `fecha_cierre` con microsegundos). La ventana
de Reportes pasó de 1150 a 1300 px: con 12 columnas el Resumen del Día no entraba.
244 tests (9 nuevos).

**2026-10-08 (y más):** **la PlayStation 5.** Pedido del dueño: una única consola que
aparezca arriba de las PCs en la grilla de Control de PCs, con el nombre fijo
"PLAYSTATION 5" (no se edita, no se da de baja, no se configura como PC), y que se
venda por tiempo con bonos propios. Todo lo decidido y por qué está en "Trampas
conocidas" (la consola NO es una estación, su sesión NO se libera sola, los permisos
se hacen cumplir en el repo, un origen nuevo toca la caja, reconstruir `ventas`);
resumen de lo construido:
- **Datos:** tablas `bonos_playstation` (catálogo propio, el tercero junto a
  `bonos_tiempo` y `bonos_miembro`), `sesiones_playstation` (a lo sumo una `ACTIVA`,
  índice único) y `sesion_playstation_bonos`. Origen de venta nuevo
  `dominio.ORIGEN_PLAYSTATION`: `ventas.origen` cambió su CHECK, así que
  `_migrar_check_origen_en_ventas` reconstruye `ventas` en las bases viejas (una
  transacción, copia previa en `data/backups/antes_de_*.db`; probada contra una copia de
  la base real: mismas ventas, mismos totales, `foreign_key_check` y `integrity_check`
  limpios). `cierres_turno` ganó `playstation_efectivo`/`playstation_digital`.
- **Código:** `control_pcs/repositories/playstation_repo.py` (estado, venta de bonos,
  liberar, permisos, catálogo). La cuenta del tiempo se sacó de `pcs_repo` a
  `dominio.segundos_restantes`/`fin_al_sumar_minutos` y la usan las PCs y la consola
  (una sola cuenta). `pcs_repo.asignar_bono` ahora exige que la estación exista y esté
  activa. `PanelDetalleEstacion` tiene dos listas de bonos (PC arriba, PlayStation
  debajo) y habilita solo la del equipo elegido; recuerda el bono tildado entre
  refrescos de 5s (antes volvía al primero justo antes de cobrar).
- **Reportes y caja:** Caja, Cierre de Turno, Control de Cierres, Totales y Resumen del
  Día traen la consola como negocio aparte (Kiosko + Impresiones + Trámites + PCs +
  PlayStation = Total); el Ranking suma sus bonos como sexta fuente; Consulta de Ventas
  muestra el Origen de cada venta. La ventana de Reportes pasó a 1380 px (13 columnas;
  se achica si la pantalla es más angosta) y la de Control de Cierres a 1180.
- **Estilo global (`main.py`):** un botón tildado pero deshabilitado se ve tenue, y un
  botón rojo ("peligro") deshabilitado se ve apagado (antes parecía activo).
- **Archivos:** `control_pcs/ui/pcs_window.py` llegó a 599 líneas con esto (la regla 12
  pide partir cerca de 600), así que el log de "Actividad reciente" (`PanelActividad`
  y su `_texto_evento`) pasó a `control_pcs/ui/pcs_actividad.py`.
- **Permisos:** vender y liberar = ADMIN o `permiso_control_pcs`; administrar bonos =
  solo ADMIN (Configuración ADMIN → "Gestionar Bonos de PlayStation 5").
- **Fuera de alcance a propósito:** abrir la consola con el saldo de un socio, y que
  anular una venta de la consola corte su cuenta regresiva (se la libera aparte, como
  con un bono de PC).
328 tests (84 nuevos: `tests/test_playstation.py` y `tests/test_playstation_ui.py`).
