# Guía: Turnos, cajas y cierres

Parte de la guía de CYBERCONTROL. Lo que vale siempre (las 15 reglas y lo que no se
cambia sin que el dueño lo pida) está en [CLAUDE.md](../../CLAUDE.md); acá está lo de
esta área. Si cambiás algo de lo que dice esta guía, corregila en el mismo commit.

**Se cruza con:** [Ventas](VENTAS_Y_ARTICULOS.md) (cada origen de venta entra a la caja) y [Socios y reservas](SOCIOS_Y_RESERVAS.md) (el renglón Reservas de la caja).

## Puntos únicos de verdad (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `turnos.calcular_turno(fecha_hora)` | se decide a qué turno pertenece una hora |
| `turnos.es_domingo(fecha)` | se pregunta si un día es domingo (acepta date, datetime o string) |
| `turnos.turnos_del_dia(fecha)` | se decide qué turnos existen en un día (3, o 2 el domingo) |
| `turnos.etiqueta_turno(fecha, turno)` | se arma el nombre legible de un turno |
| `turnos.dia_en_que_empezo_el_turno(fecha_hora)` | se decide a qué día pertenece el turno de un momento (antes de las 06:00 es la Noche del día anterior): pasarle eso a `etiqueta_turno`, nunca el día calendario de una venta de madrugada |
| `turnos.limites_de_los_dias(desde, hasta)` · `turnos.sql_dia_del_local(columna)` | se filtra y se agrupa por día en un reporte de ventas: días de 06:00 a 06:00, con la Noche entera en el día en que empezó (pedido del dueño, 2026-10-17) |
| `turnos.dia_del_turno_que_arranca_tras_un_cierre(momento)` | se decide con qué DÍA queda anotado lo que sigue a un cierre (misma tolerancia que el turno): lo usa `turnos_repo._desde_y_turno_en_curso` |
| `ui.utils.hoy_del_local()` | se decide qué es "hoy" en los reportes de ventas (hasta las 06:00, el día anterior) |
| `turnos.turno_vencimiento(dia, turno)` | se decide si un turno ya debería estar cerrado: su fin + `MINUTOS_PARA_CIERRE_FORZOSO` (30 min, pedido del dueño 2026-10-20; desde el 2026-10-18 eran 15). Es también la hora del cierre forzoso de la caja. Los carteles que nombran esos minutos leen la constante |
| `turnos.fin_del_turno(dia, turno)` · `.inicio_del_aviso_de_cierre(dia, turno)` | se decide a qué hora termina un turno (Mañana 14, Tarde 22, Noche 06; domingo 18 y 06) y desde cuándo titila el botón Cierre de Turno (`MINUTOS_AVISO_ANTES_DEL_FIN`, 5 min antes) |
| `turnos.turno_que_arranca_tras_un_cierre(momento)` | se decide con qué turno queda anotado lo que sigue a un cierre (la hora del cierre + `TURNO_GRACIA_MIN`); la usa `turnos_repo._desde_y_turno_en_curso`, que es lo que ven Caja y Cierre de Turno y lo que graba `cerrar_turno`. Con la misma regla `relevo_repo.abrir_caja` decide el turno de una caja que se abre |
| `relevo_repo.situacion_al_entrar(usuario_id)` · `.abrir_caja` · `.recibir_caja` · `.cerrar_para_entrar` | se decide qué pasa con la caja cuando alguien entra (abrirla contando, recibirla contando todo el cajón, cerrar la de quien se fue, cerrar aparte las ventas sin caja; el Admin entra sin caja). La pantalla es `ui/ingreso_caja.py` |
| `relevo_repo.estado_de_la_caja()` · `.cierre_forzoso_si_corresponde()` | se decide si el botón Cierre de Turno titila y si toca el cierre forzoso (lo dispara `MainWindow._revisar_la_caja`, que espera si hay un cobro a medias) |
| `cajas_repo._quien_vende(conexion, usuario_id)` | se decide a nombre de quién y en qué caja queda una venta (lo que cobra el Admin va a nombre de la responsable de la caja abierta, con `ventas_caja.cargada_por`); lo usa `ventas_repo._insertar_cabecera_venta` |
| `cajas_repo.cambio_inicial(caja)` | se decide con cuánto cambio arrancó una caja (lo contado, o lo esperado si no se contó): es lo que queda en el cajón al cerrarla y lo que se espera en la siguiente |
| `control_cierres_repo.listar_cierres()` · `.detalle_cierre(id)` · `.verificar_cierre(...)` | se arma lo que muestra Control de Cierres (cada cierre con su caja, responsables, relevos, si se cerró sola o en ausencia; y en `detalle_cierre(id)["resumen"]` el cierre con las mismas claves que `resumen_turno_actual`, ver `_resumen_del_cierre`) y se carga lo contado del sobre (solo Admin, cada conteo en `verificaciones_cierre`). `turnos_repo` los reexporta con el mismo nombre |
| `turnos_repo._cerrado_pasado_su_vencimiento(dia, turno, cerrado_a)` | se decide si un turno se cerró "tarde" (pasado su vencimiento): lo usan el aviso y el "Cerrado el dd/mm" del Resumen del Día |
| `config_repo.obtener_fondo_cambio()` | se lee el fondo de cambio del turno |
| `turnos_repo._desglose_de_totales(...)` · `_PREFIJO_COLUMNAS_POR_ORIGEN` | se reparte lo cobrado de un turno por origen (kiosko/pcs/playstation × efectivo/digital) y se suma el efectivo del cajón sobre TODOS los `ORIGENES_VENTA` (el diccionario vive en `turnos_ventas_repo` desde el 2026-10-20 y `turnos_repo` lo importa con el mismo nombre) |
| `turnos_ventas_repo._vendido_aparte_entre(...)` (lo usa `turnos_repo`) | se calcula cuánto del Kiosko de un turno fue impresiones y trámites, para mostrarlos en columna propia en el Resumen del Día |
| `turnos_ventas_repo._aparte_por_metodo(...)` · `turnos_ventas_repo._separar_de_kiosko(...)` | se reparte lo de impresiones y trámites del turno en curso (o de un cierre ya hecho, con `cierre_grabado=True`) entre efectivo y digital (venta por venta, con sus pagos) y se arma Kiosko sin ellos para Caja, Cierre de Turno y el detalle de Control de Cierres (`resumen_turno_actual()["kiosko_solo_*"]`, `["impresiones_*"]`, `["tramites_*"]`). `turnos_repo` la importa con el mismo nombre |
| `turnos_ventas_repo._resumen_de_reservas(...)` | se separa lo cobrado por reservas de Alquiler de PCs y PlayStation 5 para el renglón "Reservas" de Caja, Cierre de Turno y el detalle de un cierre (`resumen["pcs_solo_*"]`, `["playstation_solo_*"]`, `["reservas_*"]`, `["reservas_por_tipo"]`, `["reservas_sin_cobro"]`) |
| `reportes_repo.resumen_por_operador(...)` · `.ventas_de_operador(...)` | se calcula cuánto vendió cada usuario y se listan sus ventas con fecha y hora (Reportes > Por Operador) |
| `turnos_repo._ventanas_del_dia(conexion, dia, ahora)` | se decide qué ventas son de qué turno de un día (los cierres anotados ese día y la ventana abierta si es de ese día): la usan las filas del Resumen del Día y su detalle |
| `detalle_dia_repo.detalle_del_dia(dia)` | se arma el detalle venta por venta de un día (hora, turno, operador, rubro y qué se vendió de kiosko, trámites, PCs con la PC al momento de vender, PCSTREAM, PlayStation 5 y socios), con los renglones de cada venta tal cual se cobraron (`lineas`, con el código), lo vendido por producto y por operador (Reportes > Resumen del Día, pedido del dueño 2026-10-18) |
| `envio_pwa_repo.encolar(conexion, cierre_id)` · `.enviar_pendientes(ahora, transporte)` · `.datos_del_cierre(conexion, cierre_id)` · `.mandar_cierre(usuario_id, cierre_id)` · `.activar(usuario_id, prendido)` · `.probar_conexion()` · `.estado()` · `turnos.turno_para_la_app_de_gastos(fecha, turno)` | se manda cada Cierre de Turno a la app de gastos del dueño (la PWA "Gastos — CyberBIOS"; pedido del dueño 2026-10-26): la cola `envios_pwa` se llena en la transacción de `turnos_repo.cerrar_turno` solo con el envío prendido (Configuración ADMIN > "Cierres a la app de gastos", `ui/envio_pwa_dialogo.py`, solo Admin y solo en el mostrador; viene apagado), un hilo la manda cada minuto con reintentos, y lo que viaja es lo que carga una empleada a mano (total, efectivo, digital, el turno con el nombre de allá, el día en que arrancó el turno y el NOMBRE de la responsable de la caja) más el desglose de la tarjeta del cierre (`detalle`, con `dominio.NEGOCIOS_DEL_CIERRE`: la misma lista de negocios que `ui/tarjeta_cierre.py`, para que la app muestre el cierre tal cual el programa). Se habla con Firestore como un celular: login anónimo con la clave pública de la PWA y REST con `urllib` |
| `vuelta_admin_repo.volver(usuario_id)` · `ui.vuelta_del_admin.VueltaDelAdmin` | se decide si la sesión del Administrador vuelve sola a la empleada (pedido del dueño 2026-10-26: entra para algo rápido y se olvidaba de volver a cambiar de usuario). A los `dominio.MINUTOS_ADMIN_VUELVE_SOLO` de entrar, en silencio (sin cartel ni aviso: el dueño pidió sacar el de la primera versión; no lo vuelvas a poner), vuelve a quien dejó el mostrador con "🔄 Operador" (`MainWindow.a_quien_volveria`, lo pasa `main.Aplicacion`) sin pedirle la clave, solo si su caja sigue abierta a su nombre y en hora (situación SU_CAJA); si no, a la pantalla de ingreso. Nunca corta un cobro ni un formulario abierto (espera, como el cierre forzoso). Solo en el mostrador |
| `historial_turno_repo.historial_del_turno(usuario_id)` | se arma el HISTORIAL DEL TURNO (pedido del dueño 2026-11-02, maqueta A; botón a la derecha de CONTROL DE STOCK, `ui/historial_turno_window.py`): todo lo cobrado en el turno abierto, venta por venta, con rubro (`RUBRO_*`; las impresiones son el artículo código 4 del kiosko; cada uno en la etiqueta del color de su rubro, `ui.dibujos_tabla.TONO_*`, el mismo que en Reportes), qué se cobró, pago y la nota de anulada o "cobró ..." del Admin. Son las ventas de `turnos_repo._ventana_en_curso` (las del Cierre de Turno: el total tiene que dar igual) con el detalle de `detalle_dia_repo._que_se_vendio_entre`. Lo abre cualquier operador habilitado (`usuarios_repo.usuario_habilitado`; pedido del dueño 2026-11-19, para revisar que no se equivocaron: antes era solo del Admin, como CONTROL DE STOCK); se mira también desde otra PC (está en `admin_remoto/lista_blanca.py`) |
| `horarios_repo.horarios_del_personal(usuario_id, desde, hasta)` · `horarios_repo.con_margen(minutos)` | se calcula a qué hora llegó y se fue cada empleada y si le debe tiempo al local o el local a ella (HORARIOS DEL PERSONAL, pedido del dueño 2026-11-19, maqueta B; `ui/horarios_personal_window.py`, Administrar Kiosko > Caja y personal, solo Admin, también desde otra PC). Sale de las cajas: llega al abrir o RECIBIR su caja y se va al cerrarla o ENTREGARLA; si la cerró el programa u otra persona, la salida es "sin dato" y no suma. Los tramos seguidos de una misma persona (cerró y abrió otra en menos de `MINUTOS_PARA_SEGUIR`) son UNA jornada: cubrir a la que llega tarde suma a favor, no es otro día. Se compara con los turnos de las cajas que tuvo al menos la mitad del turno (un doble turno, de punta a punta; nunca suma 8 horas). `MINUTOS_DE_MARGEN` (2) es "a horario". Con datos de caja es de suma cero: lo que gana la que llega temprano lo pierde la que cerró para dejarla abrir (avisado al dueño) |
| `ui.tarjeta_cierre.TarjetaCierreDeTurno` · `.TablaDeNegocios` | se dibuja el resumen de un Cierre de Turno (A RETIRAR y TOTAL en grande; en la tabla, cada negocio con su efectivo y digital en columnas, lo cobrado y el Cambio Fijo; diseño del 2026-10-26, con la cabecera de `ui.piezas_ventana`). La tabla es también la de Caja: la pantalla Cierre de Turno (turno en curso) y "Ver Detalle" de Control de Cierres (cualquier cierre ya hecho, también el forzoso; pedido del dueño 2026-10-20). Un cambio de diseño del Cierre de Turno se hace ahí y se ve en las dos |

Si necesitás uno de esos datos, **llamá a la función existente**.

## Trampas conocidas (no las rompas sin entenderlas)

- **El turno NOCHE cruza la medianoche** (22:00–05:59), así que vence a la
  madrugada del día *siguiente*. Cualquier consulta por rango de fechas
  que no contemple esto parte los turnos noche al medio. Por eso **el día del
  local va de 06:00 a 06:00** (`turnos.HORA_CAMBIO_DE_DIA`, pedido del dueño
  2026-10-17): el día 1 es Mañana, Tarde y la Noche ENTERA, aunque termine el
  día 2. Todo reporte de ventas filtra con `turnos.limites_de_los_dias` (nunca
  `date(?)`/`'+1 day'`), agrupa por día con `turnos.sql_dia_del_local` y toma su
  "hoy" de `ui.utils.hoy_del_local` (`armar_filtro_por_fechas(...,
  dias_del_local=True)`): a las 02:00, "Solo Hoy" es todavía el día anterior.
  Un cierre hecho pasada la medianoche (Noche cerrada dos veces, Tarde cerrada
  tarde) deja lo que sigue en la Noche del día ANTERIOR
  (`turnos.dia_del_turno_que_arranca_tras_un_cierre`). Los historiales que no
  son de ventas (accesos, logins, movimientos de un artículo) siguen por día
  calendario. Ver `tests/test_noche_del_dia.py` y `tests/test_reportes_fechas.py`.
  En las pruebas pasa lo mismo: el "hoy" de una prueba de reportes es
  `turnos.dia_en_que_empezo_el_turno(datetime.now())` o `hoy_del_local()`, nunca
  `date.today()` ni `QDate.currentDate()` (con esos, 11 pruebas fallaban de madrugada).
- **Los domingos tienen 2 turnos de 12hs, no 3.** `MAÑANA` dura hasta las
  18:00 y no existe `TARDE`. El sábado a la noche sigue siendo el turno
  normal 22–06. Nunca asumas tres turnos por día.
- **El envío de un cierre a la app de gastos nunca frena el cierre ni lo duplica**
  (pedido del dueño, 2026-10-26; `envio_pwa_repo`). El cierre se graba como
  siempre y en la MISMA transacción queda la fila de la cola (hay fila si y solo
  si hay cierre); mandarlo es tarea del hilo, nunca de `cerrar_turno` ni de una
  pantalla: ningún pedido de red va dentro de una transacción de la base.
  `cerrar_turno` solo lo despierta (`avisar_que_hay_un_cierre`, después del
  commit) para que salga en ese momento y no en la próxima revisión, y la barra
  "ENVIANDO CIERRE DE TURNO" (`ui/envio_pwa_progreso.py`, 3 s como mínimo) solo
  mira la cola (`estado_del_cierre`): tampoco manda nada. El
  documento allá tiene nombre fijo por cierre (`documento_id`, con el número y la
  fecha) y el PATCH lo pisa entero: un reintento tras un corte no deja dos. Un
  ENVIADO no se vuelve a mandar solo aunque allá lo editen o lo borren (la verdad
  de lo cobrado es este programa); a mano sí: Control de Cierres > "Mandar a la
  app de gastos" (`mandar_cierre`, solo Admin, en la lista blanca porque desde
  otra PC lo manda el mostrador) lo reencola desde cero al MISMO documento. Solo
  se encola con el envío prendido: prenderlo no manda los cierres viejos (ya
  están cargados a mano allá; el botón es para el que falte). `registradoPor` es la
  responsable de la caja, no quien apretó el botón, y tiene que ser el nombre
  EXACTO que usa la app (mayúsculas incluidas); las contraseñas de las dos apps no
  tienen nada que ver entre sí. La clave de Firebase que está acá es la PÚBLICA de
  la PWA (ya publicada en su código): no es un secreto y no hay que "esconderla";
  tampoco sumar una cuenta de servicio mientras las reglas de allá sigan dejando
  escribir al login anónimo. Las pruebas usan una app de mentira: ninguna sale a
  internet ni toca el Firestore real.
- **El turno de un cierre sale de la hora del cierre ANTERIOR, con 40 minutos
  de tolerancia.** `cerrar_turno` anota el cierre en el turno donde ARRANCÓ lo
  que cierra, no en el de la hora en que se aprieta el botón (cerrar la Mañana a
  las 14:05 sigue siendo "Mañana"). Pero la hora del cierre anterior se toma con
  `TURNO_GRACIA_MIN` de más (`turnos.turno_que_arranca_tras_un_cierre`): quien
  cierra a las 13:55 ya está cerrando la Mañana, y lo que sigue es de la Tarde.
  Sin esa tolerancia todos los cierres siguientes quedaban un turno corrido y el
  reporte marcaba "SIN CERRAR" turnos que sí se cerraron. No usarla para el
  primer cierre de todos (no hay cierre anterior). Cambiar esta regla toca lo que
  ven Caja, Cierre de Turno y Resumen del Día a la vez: todo sale de
  `turnos_repo._desde_y_turno_en_curso`. **Con una caja abierta, el turno y el día
  son los de la caja** (decididos al abrirla con la misma tolerancia,
  `turnos_repo._ventana_en_curso`): sin eso, una caja abierta a las 07:00 después de
  una noche sin uso quedaba anotada como la Noche anterior. `TURNO_GRACIA_MIN` (40)
  es SOLO esa tolerancia: lo que tarda en cerrarse sola una caja es
  `MINUTOS_PARA_CIERRE_FORZOSO` (30), no los mezcles.
- **Cajas con número (pedido del dueño, 2026-10-18; reglas en `relevo_repo`).** Una
  empleada no entra sin caja y nunca hay dos abiertas. La caja es de UNA persona por
  vez: si el reemplazo llega tarde, quien cubrió cierra a horario y vuelve a entrar
  con una caja nueva (sin contar); el que llega la RECIBE contando todo el cajón
  (`relevos_caja`) y lo vendido antes va en su sobre. Si el turno de la caja abierta
  ya terminó, quien llega la cierra "en ausencia" de la otra. El Admin (el dueño) no
  abre caja: lo que cobra va a nombre de la responsable (`cajas_repo._quien_vende`).
  La plata del cierre sigue saliendo de la ventana entre cierres; las ventas sin caja
  (de antes de las cajas, o del Admin sin nadie en el mostrador) se cierran aparte
  antes de abrir la próxima caja (`SITUACION_VENTAS_SIN_CAJA`): si se sumaran a la
  caja nueva, la empleada respondería por plata que no vendió (pasó en la base real
  el 18/10: $61.600 de la noche en la caja de la mañana). Lo que queda en el cajón al
  cerrar es el cambio con que arrancó la caja (`cajas_repo.cambio_inicial`), no el
  Cambio Fijo: así un faltante del cambio se ve una sola vez. `ventas_caja` es una
  tabla aparte (no columnas de `ventas`) para no tocar la reconstrucción de la tabla
  madre. El cierre forzoso espera a que no haya un cobro a medias (una pantalla modal
  abierta; Ventas con el carrito vacío y Caja se cierran solas con
  `se_puede_cerrar_sola`). El conteo es a ciegas (`ui/ingreso_caja.DialogoContarPlata`):
  no muestres lo esperado antes de que se escriba lo contado. Ver `tests/test_cajas.py`.
- **Un cierre hecho tras días sin cerrar NO aparece en las filas de hoy.** Cubre
  desde el cierre anterior, así que queda anotado en el turno viejo (días atrás) y
  el Resumen del Día de hoy sale en cero. No es un error ni plata perdida: el
  reporte lo avisa arriba de la tabla (`cierres_de_otro_dia`) con un botón para ir a
  verlo, y en ese día viejo el estado dice "Cerrado el dd/mm". Ver
  `TestResumenDelDia` y `tests/test_reportes_ui.py`.
- **Un cierre guarda una foto de lo cobrado.** En Resumen del Día, si una venta
  se anula después de cerrar, el desglose de Impresiones y Trámites debe seguir
  conciliando con ese cierre; ver `turnos_ventas_repo._vendido_aparte_entre`.
- **En Caja y Cierre de Turno, Kiosko se muestra SIN impresiones ni trámites,
  pero se GRABA entero** (lo eligió el dueño el 2026-10-19 entre dos opciones; hasta
  ese día eran renglones "incluidos en Kiosko"). Esa pantalla es el resumen que las
  empleadas le mandan al dueño. Lo que se guarda en `cierres_turno`
  (`kiosko_efectivo`/`kiosko_digital`), el efectivo a retirar y el TOTAL no
  cambiaron: separarlos es solo cómo se muestra. Las impresiones se cuentan por
  renglón de venta y no por medio de pago, así que se reparten venta por venta con
  los pagos de esa venta (`turnos_ventas_repo._aparte_por_metodo`): exacto si se
  cobraron solas (el botón Impresiones) o si el carrito se pagó en un solo medio, en
  proporción si iban con otras cosas y se pagó una parte en cada medio. Kiosko sale
  por resta, con los centavos redondeados una sola vez (`turnos_ventas_repo._separar_de_kiosko`),
  así Kiosko + Impresiones + Trámites da justo lo grabado. No guardes estos importes
  repartidos en el cierre como si fueran exactos. La tabla de Control de Cierres sigue
  mostrando Kiosko entero (lo grabado); su "Ver Detalle" muestra cada cierre con la
  tarjeta del Cierre de Turno (`ui/tarjeta_cierre.py`), con impresiones y trámites
  recalculados de las ventas de esa ventana contadas como estaban al cerrar (una venta
  anulada después sigue contando, igual que en el Resumen del Día:
  `turnos_ventas_repo._condicion_vigente`). Así un cierre forzoso, que no vio nadie, se
  ve igual que si lo hubiera cerrado la empleada (pedido del dueño, 2026-10-20).
- **En pantalla, el fondo de cambio se llama "Cambio Fijo" en TODOS lados**
  (Caja, Cierre de Turno, Control de Cierres, Usuarios; pedido del dueño,
  2026-10-10). Por dentro sigue siendo `fondo_cambio` (columnas, repos, claves):
  no se renombra, solo el texto que se ve.
- **El "Renglón por renglón" del Detalle del Día muestra cada renglón TAL CUAL se
  cobró** (pedido del dueño, 2026-10-18: "si se cobran 14 impresiones juntas, que diga
  14; si se hacen 4 por separado, que las ponga tal cual se cobraron, con su horario y
  su operador"; lo imprime como la planilla de su programa anterior). No lo agrupes
  por producto "para que sea más corto": para eso está "Lo vendido (cantidades)". En
  pantalla y en papel salen las mismas filas (`ui.reportes_detalle_dia._renglones`).
