# Historial de cambios y decisiones

Este archivo conserva íntegra la cronología que estaba en CLAUDE.md.
Las reglas vigentes están en CLAUDE.md, las funciones y trampas de cada área en
`docs/guia/` y la referencia técnica actual en README.md.

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

**2026-10-14:** **la clave de los Clientes PC pasó a ser fija.** Pedido del dueño: que la
clave de conexión de las PCs (no la contraseña de admin, la otra) quede para siempre, sin
tener que pegarla en cada PC ni poder perderla o renovarla por error; aceptó expresamente
que quede dentro del `.exe`. Antes se generaba al azar ("Generar/renovar clave de Clientes
PC..."), se guardaba en la base y había que copiarla al asistente de cada PC; renovarla
dejaba sin conexión a todas las demás, y una vez generada no se podía volver a ver.
- **Servidor:** este repo es PÚBLICO, así que la clave no se escribe acá: `clientes_repo`
  guarda solo su huella SHA-256 (`HUELLA_CLAVE_CLIENTES`) y `es_clave_de_clientes()` la
  compara en tiempo constante; `servidor_red._autorizado` usa eso. Se sacaron
  `generar_clave_clientes`/`obtener_clave_clientes` y el botón de Gestionar Estaciones;
  la fila `clave_clientes` que quede en una base anterior ya no se usa (no se tocó la base).
  La contraseña de ADMIN de los Clientes PC no cambió.
- **Cliente PC:** la clave vive en `CLIENTE PC/configuracion.py` (repo privado) y el
  asistente ya no la pide. Compatible en las dos direcciones: un `.exe` anterior con su
  config.json y un servidor nuevo (o al revés) siguen conectando, porque es la MISMA clave
  que ya estaba en uso (se comprobó que coincidían la del `config.json.ejemplo`, la del
  `config.json` de la PC de prueba y la de la base, y que su huella es la guardada acá).
- **Para cambiarla alguna vez** (decisión de fondo): clave nueva en CLIENTE PC, huella nueva
  en `clientes_repo.py` y el `.exe` reinstalado en TODAS las PCs. Un test vigila que nadie
  vuelva a agregar el botón de renovar sin hablarlo con el dueño.
362 tests (3 que probaban generar/renovar se reemplazaron por 3 de la huella y 2 nuevos
del servidor: clave sin "Bearer" y clave correcta).

**2026-10-15:** **fondo de pantalla para la pantalla de bloqueo de las PCs.** Pedido del dueño:
que las PCs, al arrancar, le pidan a CYBERCONTROL el wallpaper de bloqueo (y preguntó si eso
haría el arranque mucho más lento: no, si se pide en segundo plano; ver el README de CLIENTE PC,
sección "Fondo de la pantalla de bloqueo", con lo medido).
- **Dónde se elige:** Configuración ADMIN -> Gestionar Estaciones -> "Fondo de pantalla de las
  PCs..." (`control_pcs/ui/pcs_fondo_dialogo.py`). `preparar_jpeg` (Qt) abre cualquier imagen,
  respeta la orientación de las fotos de celular, la achica a 1920x1080 sin deformarla, rellena
  las transparencias con el azul del bloqueo y la guarda como JPEG (bajando la calidad si hace
  falta para entrar en 2 MB). Las reglas y el archivo son de `control_pcs/repositories/fondo_repo.py`.
- **Dónde vive:** UN archivo, `data/fondo_bloqueo.jpg` (fuera de git y de las copias de
  seguridad de la base). Su versión es la huella SHA-256 (16 caracteres) de su contenido: no hay
  un dato aparte que pueda quedar desparejo.
- **Servidor:** `GET /fondo` (el JPEG con su versión en `X-Fondo-Version`; 404 si no hay) y
  `fondo_version` en cada `GET /estado`, para que una PC prendida hace días se entere de un
  cambio sin bajar la imagen. Compatible en las dos direcciones: un Cliente PC viejo ignora el
  campo nuevo, y uno nuevo contra un servidor viejo recibe 404 y se queda con el azul.
- **Es un adorno:** si algo falla acá (disco, archivo roto), `/estado` sigue contestando sin ese
  dato y `/fondo` da 404 o 500; un archivo que no empieza como JPEG cuenta como "no hay fondo".
403 tests (41 nuevos en `tests/test_fondo_pantalla.py`: el repositorio, el servidor real, la
preparación de la imagen y la pantalla).

**2026-10-17:** **filtro de palabras de las PCs ("protección antiporno").** Pedido del dueño, con
una captura del "Filtrador de palabras" del programa de cyber que usaba antes, y la pregunta de si
consumiría muchos recursos en las PCs (16 GB, Ryzen 5 3500, Windows 10): no, se midió una revisión
completa en 6-10 microsegundos, menos de una milésima de un núcleo cada 0,7 s.
- **Dónde se configura:** Configuración ADMIN -> Gestionar Estaciones -> "Filtro de palabras de las
  PCs..." (`control_pcs/ui/pcs_filtro_dialogo.py`): prendido/apagado, la lista y el mensaje, más las
  últimas páginas cerradas. Viene prendido con la lista del programa viejo, sin "DP".
- **Dónde vive:** la lista, como JSON en `configuracion` (`filtro_palabras_repo`); cada página
  cerrada, en la tabla nueva `bloqueos_filtro_pc` (con índice por fecha: la lee "Actividad
  reciente" en cada refresco).
- **Servidor:** `filtro_version` en cada `GET /estado`, `GET /filtro` con la lista y
  `POST /filtro_bloqueo` para los avisos. Compatible en las dos direcciones: un Cliente PC viejo
  ignora el campo nuevo y uno nuevo contra un servidor viejo no recibe versión y no filtra nada.
- **En cada PC** (`CLIENTE PC/filtro_palabras.py`): con una sesión en curso mira el título de la
  ventana de adelante; con una palabra de la lista (entera, sin mayúsculas ni acentos) cierra la
  pestaña con Ctrl+W, muestra el mensaje y avisa; si la página sigue ahí 2 s después, cierra la
  ventana. Como mucho un aviso cada 30 s por PC.
529 tests al juntarse con la revisión del mismo día (26 nuevos en `tests/test_filtro_palabras.py`:
el repositorio, el servidor real, la actividad y la pantalla).

**2026-10-17:** **alta de socios con usuario y clave; el DNI lo completa el socio en su primer
ingreso.** Pedido del dueño: tenía muchísimas cuentas de su programa de cyber anterior para volver
a crear, y el alta pedía usuario, clave, nombre, DNI y teléfono.
- **Alta:** en Miembros alcanzan usuario y contraseña; nombre, DNI, celular (el "teléfono" de
  antes), WhatsApp (columna nueva `miembros.whatsapp`) y email son opcionales. Un nombre vacío se
  guarda como el usuario. La lista muestra DNI, Celular y WhatsApp, y "Falta DNI" en rojo.
- **Primer ingreso:** el Cliente PC nuevo manda `pide_datos` en `POST /login`; a un socio sin DNI
  válido el servidor le contesta `faltan_datos` sin abrir nada, y la PC le pide DNI (obligatorio),
  celular y WhatsApp (opcionales). Se guardan en la misma transacción que abre la PC: con un dato
  mal o un DNI que ya es de otra cuenta activa ("pasá por el mostrador"), no se guarda nada ni se
  gasta saldo. Es una sola vez.
- **Compatible:** un Cliente PC viejo no manda `pide_datos` y el socio entra como siempre (se le
  pide la próxima vez en una PC actualizada); uno nuevo contra un servidor viejo también entra.
- El DNI se guarda solo con números (7 u 8 cifras) y los teléfonos con sus números (8 a 15, con el
  "+" de adelante si lo tenía), también cuando los carga el mostrador.
556 tests (24 nuevos en `tests/test_primer_ingreso_socio.py`: alta, primer ingreso, migración y
servidor real).

**2026-10-19:** **botón Impresiones y Kiosko sin impresiones en Caja y Cierre de Turno.** Pedido del
dueño: "entre Vender y Trámites quiero el botón Impresiones, es el artículo número 4".
- **Código 4:** en la base con la que trabaja, IMPRESIONES es el artículo código 4, pero
  `dominio.CODIGO_ARTICULO_IMPRESIONES` seguía en "1" (el de la base anterior): las impresiones salían
  en $0 en Reportes, Resumen del Día y Cierre de Turno. Pasó a "4"; los días ya trabajados con esta
  base se recalculan solos (se busca el código en cada consulta).
- **Botón "Impresiones"** en la barra, entre Vender y Trámites (`ui/impresiones_window.py`,
  `repositories/impresiones_repo.py`): cantidad, ventana de cobro de siempre y venta de kiosko común
  del artículo. `confirmar_venta` se partió en `_grabar_venta_kiosko` para leer el precio en la misma
  transacción. No aparece desde otra PC.
- **Caja y Cierre de Turno:** Kiosko, Impresiones y Trámites en renglones separados, cada uno con su
  efectivo y digital (el dueño eligió esta opción entre dos). Lo grabado en el cierre, el efectivo a
  retirar y el TOTAL no cambian.
800 tests (21 nuevos en `tests/test_impresiones.py`).

**2026-10-19:** **panel del costado de Control de PCs en gris medio.** Pedido del dueño: cambiar el
color de "todo ese sector del costado"; eligió la B (gris medio) entre cinco maquetas (gris claro, gris
medio, grafito, azul noche como la barra, todo oscuro).
- `PanelDetalleEstacion` se llama `panelDetalle` (y su área de bonos `areaBonos`); los colores viven en
  la hoja de estilos de `main.py`: fondo #5E636B, letras claras, bonos claros, el elegido y Cobrar en
  azul, Finalizar con borde rojo. El aviso "Todavía no hay bonos" dejó su color fijo por `avisoSinBonos`.
- Las reglas van con `>` (solo hijos directos): el cobro, el login del socio y los avisos tienen al panel
  como padre y con un selector común heredaban las letras claras.
802 tests (1 nuevo en `tests/test_estilo_ui.py`, que falla si se saca el `>`).

**2026-10-19:** **la barra de arriba con todos los botones para todos, y Config ADMIN para el
Operador.** Pedido del dueño: "que para todos los usuarios aparezcan todos los botones... los que no
tienen acceso, que no haga nada; si no, queda muy vacío". Después: "cuando el usuario es Operador,
CONFIG ADMIN solo muestre disponible Gestionar Estaciones, las demás en gris".
- `MainWindow._agregar_boton_barra(..., habilitado=...)`: Miembros y Admin Kiosko se ven siempre; sin
  permiso no se conectan (se ven iguales, no grises). Config ADMIN abre para todos.
- `ConfiguracionAdminWindow`: un no Admin solo puede usar Gestionar Estaciones (`_armar_botones(...,
  habilitados=...)`); el resto queda en gris.
- Adentro de Gestionar Estaciones (pedido del dueño, mismo día: "de las 4 cosas, solo Actualización de
  cliente PC bloqueado", y enseguida "también cambiar la contraseña de las PC clientes"): el Operador
  ve en gris esos dos botones; estaciones, IP, fondo y filtro los usa. `DialogoGestionEstaciones` recibe el
  `usuario`. Bloqueo solo de pantalla: los repos no exigen Admin.
813 tests (11 nuevos en `tests/test_barra_para_todos.py`).

## Hasta el 2026-11-18 (venía de "Estado actual" de CLAUDE.md)

La suite actual se ejecuta con `python tests/correr_en_paralelo.py` (o `python -m unittest discover tests`) y tiene
1899 pruebas al 2026-11-18 (lo que se hablan el mostrador y las PCs, de la revisión general: una prueba de contrato con los 11 datos de GET /estado que lee el Cliente PC, que con la carpeta CLIENTE PC al lado usa su código de verdad; una consulta sin novedades que toma el permiso de escritura de la base una sola vez, así las 40 PCs no hacen esperar a las ventas; y la respuesta que no le llega a una PC anotada en errores.log, con el comando que iba; las copias de seguridad revisadas de la revisión general: cada copia pasa quick_check antes de guardarse, una dañada no se guarda ni borra las de antes y la barra de arriba avisa en rojo, y los pasos para volver a una copia quedan en un .txt al lado de las copias; los candados de plata de la revisión general: el bono que espera su turno, una sola sesión activa por PC, el precio de lista salvo el Admin, anular_venta sin cargas ni bonos y los pagos que suman justo el total en todas las ventas; las ofertas 2x1 y 50% en los bonos de las PCs, PCSTREAM y la PlayStation 5, nunca en los de socios ni en la carga por monto ni en las reservas: Configuración ADMIN > Ofertas, solo el Admin, con la ventana B que eligió el dueño, la semana en una grilla día por turno con la Noche que cruza medianoche y el domingo en T1/T2, los bonos con su antes y después, las próximas veces con su día y su hora, pausar, terminar y usar de nuevo, y el aviso si dos ofertas chocan en un mismo bono y turno; en el panel de la PC, la maqueta P1: la etiqueta 2x1 / 50% en el botón del bono con lo que se cobra y el cartel naranja o violeta arriba de las listas; se cobra lo que se mostró aunque la oferta termine con la ventana de cobro abierta y, si el Admin la pausó o la cambió mientras tanto, no se graba nada y se avisa que hay que volver a cobrar; un bono anotado a la Cuenta de la PC conserva la oferta aunque se cobre después; cada bono vendido dice con qué oferta; Venta de Mercadería con un solo campo que no pide elegir: sin letras es código de barras, con letras busca por nombre o marca, cada palabra en cualquier orden, sin los botones F5/F6/F7; el aviso antes de cerrar la sesión de una PC que no responde, con lo que pierde el cliente y, si se cortaron varias a la vez, que seguramente es la red del mostrador; cómo se cerró cada sesión de PC: con qué botón, quién y cuánto le quedaba, y Actividad reciente lo dice; un socio entra a una sola PC a la vez, sin multilogin; el tiempo de los socios que juegan, claro: Miembros muestra el SALDO TOTAL, lo guardado más lo que le queda en la PC, de dónde sale cada parte y un cartel celeste con hasta cuándo juega y si una reserva de otro corta la PC; el cuadro de la PC dice "Hasta 22:00 · Eros" desde que entra; y el cartel de la carga dice también lo que quedó guardado; ORDENAR SALDOS en Miembros, que ve solo el Admin y pide la contraseña de ORDENAR Stock: sumar, restar o pasar tiempo de un socio a otro sin crear ventas ni tocar la caja, cada corrección anotada con quién y cuándo, y también desde otra PC, donde el botón Miembros lo ofrece y lo graba el mostrador a nombre del que entró; la PC que abre el Cliente PC sin el Lanzador, que en Actualizar el Cliente PC ya no queda "Esperando" para siempre: va a "Con problema" y dice que hay que reinstalarla con preparar_pc.bat; las listas con la maqueta B del kiosko: cabecera oscura con indicadores, teclas en mayúscula con lo que es solo del Admin punteado, buscador, filtros en pastillas y la grilla en su panel, en Artículos, Compras, Control de Stock, ORDENAR Stock, Consulta de Ventas con el Origen en etiqueta, Control de Cierres con los turnos del domingo en sus colores, Reportes con PCSTREAM y Socios y Bonos, Usuarios, Accesos de Admin, Copias, Impresiones y Entrar desde otra PC; Modificar artículo con la maqueta B del kiosko: la cabecera con el artículo y su stock, los datos a la izquierda y la tarjeta oscura con el precio de venta en grande y la calculadora costo + ganancia % = venta, que arranca en 80%; la pantalla de ingreso con el diseño Portal que eligió el dueño, la maqueta "D": anillos de neón que giran alrededor del ícono, estrellas, los campos y ENTRAR en una fila y la hora abajo, animada solo mientras se ve y con los avisos que se abren encima en sus colores de siempre; Miembros con la ficha del socio: la lista a la izquierda y, a la derecha, todo lo del socio elegido con los botones que actúan sobre él; Actualizar el Cliente PC como tablero por etapas, con una tarjeta por PC que cambia de columna a medida que avanza, y las que están al día chiquitas; los fondos de las PCs con la maqueta B: la pantalla de bloqueo y el wallpaper de Windows lado a lado, cada uno con su vista previa en un monitor dibujado, Elegir imagen y Quitar, y la misma imagen en los dos con un botón; el wallpaper lo pone el Cliente PC V2.1 con la PC libre y de nuevo en cada arranque; el mosaico dice REINICIANDO también cuando la PC se reinicia por un DESCONGELAR que contestó OK, hasta que vuelve o 5 minutos; las ventanas de REINICIAR y APAGAR con el diseño B: las PCs libres como fichas del mosaico que se marcan con un clic, las que están en uso aparte con lo que les queda y sin poder marcarse, y el aviso de que solo se tocan las prendidas y libres; la ventana de Congelar / descongelar PCs con el diseño A: lista a la izquierda, tarjetas a la derecha y ACTUALIZAR CLIENTES solo para el Admin, con el copo dibujado; la PC libre que terminó de copiar el Cliente PC nuevo se reinicia sola para ponerlo y su monitor dice REINICIANDO hasta que vuelve, una sola vez por versión, nunca con un cliente ni en mantenimiento; las versiones del Cliente PC en carpeta: el .zip firmado con la lista de sus archivos, que solo les llega a las PCs que lo saben poner; quién abrió la caja y a qué hora, que viaja con el cierre a la app de gastos; la impresora de la vista previa que Python borraba y cerraba el programa sin cartel al imprimir; el Administrador que vuelve solo y en silencio a la empleada a los 10 minutos, solo si su caja sigue abierta a su nombre; los cierres que se asientan solos en la app de gastos del dueño: cola en la transacción del cierre, hilo que manda en el momento y reintenta, un documento por cierre, a nombre de la responsable de la caja, el forzoso marcado, la barra "ENVIANDO CIERRE DE TURNO" de 3 segundos como mínimo al confirmar, y la pantalla de Configuración ADMIN con prender/apagar, Probar la conexión y Reintentar ahora; las reservas de socios: un socio con 5 hs de saldo o más reserva una PC sin seña, y al que no llega se le carga saldo ahí mismo, el mínimo lo cambia solo el Admin en Miembros > "$ Para Reserva", al entrar con su usuario la reserva queda habilitada sola y si no viene no pierde nada; Administrar Kiosko con el mismo diseño, y lo que una encargada no tiene habilitado en gris con candado; Caja y Cierre de Turno con el mismo diseño: las dos cifras que importan en grande y la tabla de dónde vino la plata, negocio por negocio, con el efectivo y lo digital en columnas; Configuración ADMIN, Gestionar Estaciones y Reservas con el diseño que eligió el dueño, la maqueta "A": cabecera oscura con la estela celeste del cometa y pastillas con números, tarjetas de menú agrupadas con candado en lo que es solo del Admin, lo peligroso en rojo y aparte, y el estado de cada reserva como pastilla de color; piezas en `ui/piezas_ventana.py`; la plata en miles y sin centavos en todo el programa, "$ 1.500", también en los campos donde se escribe; la ventana de Venta de Mercadería con el diseño que eligió el dueño, la maqueta "B": el total oscuro y COBRAR siempre grandes a la derecha, teclas con la tecla dibujada aparte y el código y el precio por unidad debajo de cada producto, colores en `ui/hoja_de_estilos.py` y dibujos en `ui/ventas_dibujos.py`; F5 Código lista por código de menor a mayor, como números; la Cuenta de la PC: el cliente que juega pide un pancho, más tiempo o tiempo de socio, se anota en la cuenta de su sesión, su PC titila con borde fucsia y se cobra después, con tope que fija el Admin en Reglas de Cuenta de PC; 15 minutos antes del fin del turno titila más rápido y sale el cartel para cobrar, y lo que quedó sin cobrar va al cierre como fiado; desde otra PC la pantalla principal se ve igual que en el mostrador, con la grilla de PCs en vivo, y lo que vende, cobra o atiende una PC avisa que se hace en el mostrador; el servidor de red lee el cuerpo de un POST que rechaza, así la PC no se queda sin la respuesta por un "reset" de Windows: una prueba fallaba al azar; el 🔄 de Operador un 25% más grande, como ícono, y las flechas rojas dibujadas de REINICIAR; una sesión con bono ya no se cierra desde la PC: POST /logout la rechaza, solo los socios; Bajar a Excel en el Historial de Cargas y en Socios y Bonos; Reportes > PCs: Socios y Bonos; "No viene hace" en Miembros; el Historial de Cargas de Miembros; CONTROL DE STOCK, a la derecha de APAGAR, que lo abre solo el Admin; el botón "Cerrar sesión" ahora dice "Camb Operador" y va pegado a la derecha de Clave; Gestionar Marcas, solo para el Admin; el cometa del borde del fondo negro; "Programas y estado" y el mantenimiento a distancia del clic derecho de una PC; el botón APAGAR debajo del mosaico y el copo de nieve dibujado de DESCONGELAR; la carga de saldo de un socio que está usando una PC pasa a su sesión; los botones DESCONGELAR y REINICIAR debajo del mosaico, para cualquier operador y con su ventana para desmarcar PCs; el termómetro con la temperatura de cada PC; sin las 14 de Limpiar base de datos, que se sacó; la casilla "Operar PCs y Miembros" que se sacó de Usuarios; por qué una PC no puso la actualización del Cliente PC al reiniciarse, la barra en mayúscula y negrita; la revisión de limpieza del 21/10 sacó las 4 de `dominio.pagos_netos_de_vuelto`, que el cobro ya no usaba; la PC que no se enteró de que terminó su sesión titila como la PlayStation 5, y una PC que se reinicia sigue con su sesión y su tiempo; el reinicio del seguro de fin de sesión del Cliente PC; Reiniciar/Apagar que vencen a los 2 minutos y el motivo de cada reinicio que pide el Cliente PC; las reservas, parte 2: la PC reservada en el mosaico y en la pantalla de bloqueo, el aviso al vender y el socio que se corta a la hora; las reservas, parte 1: la plata; cambiar el código de un artículo desde ORDENAR Stock, el número que se escribe en una celda de tabla, como el stock de ORDENAR Stock, las preguntas de cerrar una sesión sin hablar de reintegros, el tiempo de las PCs al volver de un corte y con nadie logueado, la lista de Miembros alta, por usuario y con lupa, el detalle de cada cierre con la tarjeta del Cierre de Turno, también el forzoso, ORDENAR Stock, las copias de seguridad automáticas en varias carpetas, el aviso de mantenimiento de las PCs, la actualización del Cliente PC rehecha con casillas, con los cortes de las PCs, Miembros y la PlayStation 5 abiertos a cualquier operador, las cajas con número, administrar desde otra PC, el detalle del día con su renglón por renglón para imprimir, el cobro nuevo en todas las pantallas, congelar/descongelar PCs con Shadow Defender, la barra oscura de arriba, el botón Impresiones con Kiosko sin impresiones en Caja y Cierre de Turno, el panel gris del costado y la barra con todos los botones para todos).

## Desde el 2026-11-18

Lo nuevo se anota acá abajo, con fecha, lo más nuevo al final.

- **2026-11-18 — `CLAUDE.md` a dieta** (revisión general, mejora 5). Pasó de 149 KB a 18 KB:
  quedan la arquitectura, las 15 reglas, lo que no se cambia sin el dueño, el Cliente PC y
  cómo trabajar. Las funciones que son el único lugar de algo y las trampas se mudaron, tal
  cual, a `docs/guia/`, una guía por área, y `CLAUDE.md` dice cuál leer según lo que se va a
  tocar. `tests/test_guia_del_proyecto.py` revisa que cada función de las tablas (300
  nombres) exista en el código y que `CLAUDE.md` no pase de 25 KB. 1905 pruebas.
- **2026-11-19 — HISTORIAL DEL TURNO para los operadores** (pedido del dueño: "quiero que el
  historial de turno lo puedan ver los operadores, para verificar que no cometieron errores").
  El botón de debajo del mosaico ya no es solo del Admin: cualquier operador habilitado ve todo
  lo cobrado en el turno abierto, con las anuladas y quién las anuló. No muestra nada nuevo: el
  botón Caja ya les daba lo cobrado, y el conteo del Cierre de Turno sigue a ciegas. La lista
  blanca de la otra PC no cambia (misma firma).
- **2026-11-19 — REPORTES con el diseño C y un color por rubro** (pedido del dueño: "mejorá la
  estética de REPORTES. Todos los títulos de arriba en MAYÚSCULA y hacelo profesional y bello";
  de tres maquetas eligió la C y pidió "bono de PC y bono de PlayStation diferentes colores, lo
  que sea de una misma categoría que mantengan color"; de tres formas eligió la 1, la etiqueta).
  Un menú a la izquierda en vez de pestañas, el nombre de la sección grande con su para qué,
  los filtros en una tarjeta blanca, todos los títulos en mayúscula, la plata en negrita a la
  derecha con los "$ 0" en gris, renglones más altos y las cifras de PCSTREAM como las de
  Resumen de Ventas. Un solo mapa de colores para todo el programa (`ui/dibujos_tabla.TONO_*`):
  el Ranking muestra la categoría en una etiqueta de color con nombre corto y las impresiones
  aparte de Kiosko; TOTALES y el Resumen del Día llevan una barra del color de cada rubro bajo
  su título; el Detalle del Día y Por Operador, el rubro y el origen en etiqueta. Se alinearon
  al mismo mapa el Historial del Turno (PS5 de celeste a rosa, PCSTREAM de naranja a celeste,
  reservas de rosa a naranja), el Origen de Consulta de Ventas y Control de Cierres (Kiosko
  verde, Alquiler de PCs azul, PS5 rosa) y Socios y Bonos (socios violeta, bonos azul). Dos
  revisiones independientes dejaron además: las impresiones también aparte en el Detalle del Día
  (Venta por venta y Lo vendido; una regla sola, `reportes_repo.categoria_de_la_venta`, que usa
  también el Historial del Turno sin cambiar lo que muestra), ANULADA de rosa a rojo
  (`TONO_ALERTA`: el rosa pasó a ser de la PS5 y una venta de la PS5 anulada llevaba dos
  etiquetas rosas), los títulos de las grillas buscados por la marca `deReporte` y no "adentro de
  la ventana" (se medían antes de entrar: salían mordidos y el TOTAL DEL DÍA, cortado) y la
  grilla de turnos sumando la barra de abajo en pantallas angostas. Sin .exe. 1935
  pruebas.
- **2026-11-19 — HORARIOS DEL PERSONAL** (pedido del dueño: "que sume los minutos que abre la
  caja tarde o temprano cada usuario... quiero saber cuántos días llegó temprano, cuántos días
  llegó tarde y si me debe tiempo o le debo tiempo"; de tres maquetas, `PROPUESTA_HORARIOS`,
  eligió la B: "me encanta la B"). Tarjeta nueva en Administrar Kiosko > Caja y personal, solo
  del Admin (no en Reportes: ahí entran empleadas con permiso). Una tarjeta por empleada con
  los días que llegó temprano, tarde y que se fue antes, y el saldo grande en verde o rojo;
  abajo el detalle día por día con "qué pasó" (recibió la caja de, cubrió hasta que llegó, la
  cerró el programa). Todo sale de `cajas`, `relevos_caja` y `cierres_turno`
  (`repositories/horarios_repo.py`), sin tablas nuevas ni migración: lee, no graba. Probado
  sobre una copia de la base del local (18/10–03/11): las cajas las cierra casi siempre su
  responsable; las que cerró el Admin quedan "sin dato". Se suma a la lista blanca de
  administrar desde otra PC (cambia la firma: las dos copias necesitan el .exe nuevo). Sin
  .exe. 1955 pruebas.
- **2026-11-19 — TAREAS DEL TURNO, traídas de FR Kiosko** (pedido del dueño: "de fr kiosko
  quiero que portes el gestor de tareas a cybercontrol"). Tal cual allá: el Admin carga cosas
  para hacer a una hora (todos los días, algunos días o solo hoy) y a esa hora sale un aviso
  encima de todo, con POSPONER 5/10 MIN y TAREA HECHA, hasta que alguien la marca. Lo único
  distinto: en vez del sexto acceso del inicio (acá no hay inicio, está el mosaico) es el botón
  ⏰ TAREAS de la barra, después de Reservas, que titila en rojo y dice cuántas hay atrasadas; y
  las tareas NO viajan con el cierre a la app de gastos (la de CyberBIOS no las muestra). Con
  ellas llegaron `piezas_ventana.restringir`/`solo_para_el_admin` ("Acceso Restringido") y
  `tecla_de_renglon`, usadas solo por esta pantalla. Tres tablas nuevas, sin migración. Solo en
  el mostrador: no cambia la lista blanca. Sin .exe.
- **2026-11-19 — TAREAS DEL TURNO baja al lado de HISTORIAL DEL TURNO** (pedido del dueño, al
  verla en la barra: "quiero que lo muevas ... y se llame TAREAS DEL TURNO"). El botón deja la
  barra de arriba (que vuelve a medir lo de antes) y va debajo del mosaico, a la derecha de
  HISTORIAL DEL TURNO, con ese nombre; sigue titilando en rojo con las atrasadas ("TAREAS DEL
  TURNO · 2"). Lo arma `MainWindow` y lo suma `PanelControlPcs.agregar_boton_abajo`. Sin .exe.
- **2026-11-20 — Permiso para cargar TAREAS DEL TURNO** (pedido del dueño: "quiero que una
  usuaria Gabriela sí pueda crear tareas ... y por si quiero que otros operadores también";
  eligió que pueda cargar, cambiar y borrar). Una casilla nueva en Usuarios > Permisos extra:
  "Tareas del Turno (cargar, cambiar y borrar tareas)". Con ella, + NUEVA TAREA, MODIFICAR y
  BORRAR andan igual que para el Admin; sin ella, siguen diciendo "Acceso Restringido". Marcar
  HECHA y posponer sigue siendo de cualquiera. El repo lo relee de la base en cada cambio
  (`usuarios_repo.exigir_permiso`), y la ventana al abrirse (`tareas_turno_repo.puede_cargar`):
  dárselo o sacárselo vale sin que salga y vuelva a entrar. No abre Administrar Kiosko
  (`usuarios_repo.es_encargado` mira solo `PERMISOS_DE_ADMINISTRAR_KIOSKO`). El historial ya
  anotaba quién cargó, cambió o borró cada tarea. Columna nueva `usuarios.permiso_tareas_turno`
  con migración (arranca en 0 para todos). `piezas_ventana.solo_para_el_admin` pasa a
  `solo_con_permiso`. La huella de la otra PC ahora incluye las casillas de permisos: las dos
  copias necesitan el mismo .exe. Sin .exe.
- **2026-11-20 — HISTORIAL DEL TURNO con todos los movimientos y los turnos anteriores**
  (pedidos del dueño: "absolutamente todos los movimientos de $ y de habilitación y ventas";
  "que se guarden todos los historiales de todos los días de todos los turnos, y poder elegir el
  día, el turno, pero que al ingresar por defecto solo muestre el turno actual"; eligió la maqueta A
  de `PROPUESTA_HISTORIAL_DEL_TURNO/2_TODOS_LOS_MOVIMIENTOS` y el selector de
  `3_ELEGIR_DIA_Y_TURNO`, con "el operador solo puede ver su turno actual, el admin puede navegar
  entre todos los días y turnos"). Además de las ventas, el Historial junta lo que no es una venta
  (`repositories/historial_turno_movimientos_repo.py`, nuevo): la PC que se abrió con una reserva,
  el socio que entra con su saldo, el pase de PC, lo que vuelve al saldo, ORDENAR SALDOS, la caja
  que se abre o pasa de mano, la Cuenta de la PC; cada venta que dio tiempo dice si prendió el
  equipo o le sumó. Columnas nuevas (Qué fue, Tiempo, Plata) y pastillas por tipo. El Admin elige
  día y turno con la barra nueva (`ui/historial_turno_barra.py`); un turno cerrado es solo para
  mirar, termina con su CIERRE y su TOTAL da igual que su cierre (lo anulado después sigue
  sumando, como en Control de Cierres). El operador ve solo el turno actual, y el repo se lo exige
  (`exigir_admin`). Dos colores nuevos: fucsia para la Cuenta de la PC y pizarra para la caja.
  Al sacar las fotos se vieron y arreglaron dos cosas: las pastillas del día anterior quedaban en
  la barra (trampa nueva en `docs/guia/PANTALLA.md`) y lo anotado antes de pasar una PC a otra
  decía la PC nueva (`_pc_en`, trampa en `docs/guia/TURNOS_Y_CAJA.md`). Las pruebas se partieron
  en `tests/test_historial_turno.py` y `tests/test_historial_turno_anteriores.py`. Cambia la lista
  blanca (`turnos_del_dia`): las dos copias necesitan el mismo .exe. Sin .exe.
- **2026-11-20 — El socio cambia su contraseña desde su PC** (pedido del dueño: "quiero que el cliente
  pueda cambiar su contraseña desde su PC, me lo pidieron"; eligió la maqueta B, el botón en la franja,
  y un mínimo de 4 caracteres). `POST /cambiar_clave` nuevo en `servidor_red.py`: el socio es el de la
  sesión abierta en esa PC (no viaja el usuario) y, si la PC manda una `sesion_id` que ya no es la de
  ahora, no se cambia nada. La regla, en `miembros_repo.cambiar_clave_desde_la_pc` (la actual tiene que
  ser la correcta; la nueva, de al menos `LARGO_MINIMO_CLAVE_SOCIO` caracteres y distinta). Del lado del
  Cliente PC, "Cambiar contraseña" abajo de "Cerrar sesión" y "Minimizar" en la franja agrandada, solo
  con un socio; un Cliente PC viejo no lo tiene y sigue igual. Pruebas en
  `tests/test_cambiar_clave_socio.py` y el contrato con el Cliente PC de verdad en
  `tests/test_contrato_cliente_pc.py`. Sin .exe; la lista blanca no cambia.
