# Guía: Socios (Miembros) y reservas

Parte de la guía de CYBERCONTROL. Lo que vale siempre (las 15 reglas y lo que no se
cambia sin que el dueño lo pida) está en [CLAUDE.md](../../CLAUDE.md); acá está lo de
esta área. Si cambiás algo de lo que dice esta guía, corregila en el mismo commit.

**Se cruza con:** [PCs y bonos](PCS_Y_BONOS.md) (la sesión en la que juega el socio), [Ventas](VENTAS_Y_ARTICULOS.md) (las cargas son ventas) y [Turnos y caja](TURNOS_Y_CAJA.md) (la plata de las reservas en la caja).

## Puntos únicos de verdad (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `socios_bonos_repo.comparar(desde, hasta, agrupar_por)` | se separa lo que dejaron las PCs en cargas de saldo a socios y bonos del mostrador, y se los compara (Reportes > "PCs: Socios y Bonos", pedido del dueño 2026-10-24, `ui/reportes_socios_bonos.py`): plata, cuántos, tiempo vendido, qué parte del total y cuánto deja cada hora. Bonos = walk-ins, PCSTREAM y reservas de PCs; su plata sale por resta (Alquiler de PCs − cargas), así las dos partes suman justo "Alquiler de PCs" de Caja y Totales. Agrupa con `reportes_repo._COLUMNA_AGRUPACION` (rango, día, semana, turno). Está en `admin_remoto/lista_blanca.py` (Reportes se abre desde otra PC) |
| `reintegros_repo.reintegros_por_miembro(...)` | se decide cuánto se le devuelve a cada socio al cortar una sesión de PC (lo usa `pcs_repo.finalizar_sesion`) |
| `bonos_miembro_repo.listar_bonos()` / `.obtener_bono(id)` | catálogo de bonos EXCLUSIVO de socios (no confundir con `pcs_repo`) |
| `miembros_repo.abrir_estacion_por_miembro(...)` | un socio abre una PC con su propio saldo (y, con `pedir_datos`, completa sus datos del primer ingreso). Una sola PC a la vez (pedido del dueño 2026-11-07, "no quiero que haya multilogin"): si ya juega en OTRA PC con tiempo por delante, `_no_esta_jugando_en_otra_pc` lo rechaza antes de mirar el saldo, con un mensaje que el Cliente PC muestra tal cual; en la misma PC le suma a su sesión como siempre. Para cambiarlo de PC está "Intercambiar de máquina..." (`pcs_repo.trasladar_sesion`) |
| `miembros_repo.cambiar_clave_desde_la_pc(miembro_id, clave_actual, clave_nueva)` | el socio cambia su contraseña él mismo, desde la franja de su PC mientras juega (pedido del dueño 2026-11-20, maqueta B: botón "Cambiar contraseña" del Cliente PC V2.6 o más; `POST /cambiar_clave` de `servidor_red.py`). El socio es el de la sesión abierta en esa PC, nunca un usuario que mande la PC. Exige la actual y una nueva de al menos `LARGO_MINIMO_CLAVE_SOCIO` (4) caracteres; el alta y "Modificar" de Miembros no tienen ese mínimo (el mostrador sigue poniendo la que quiera y es quien la blanquea si el socio se la olvida) |
| `miembros_repo._sumar_carga_a_la_sesion(...)` | se decide qué pasa con lo que se le carga a un socio que está usando una PC: pasa a esa sesión, con un CONSUMO como al entrar (hasta la hora de una reserva, si la hay; lo demás queda en el saldo). Pedido del dueño 2026-10-22: la sesión se lleva el saldo al entrar, y una carga quedaba en el saldo mientras la PC contaba hasta cero. `cargar_saldo_por_monto/_por_bono` devuelven `{"venta_id", "sumado_a_la_sesion"}` y Cargar Saldo lo avisa. Ojo: anular esa carga no le saca el tiempo a la PC por sí sola (`anular_carga` solo revierte lo que hay en el saldo); con `sacar_de_la_pc=True` (lo pide el cartel de `control_pcs/ui/anular_carga.py` cuando `resumen_de_carga` dice que el socio está jugando) lo que falta se le acorta a su sesión, sin cortarla ni dejarla antes de ahora, como `cuentas_pc_repo.quitar_renglon` |
| `miembros_repo.resumen_de_carga(venta_id)` · `.anular_carga(venta_id, usuario_admin_id, motivo, sacar_de_la_pc=False)` · `ui.anular_carga.anular_carga_con_cartel(parent, usuario, venta_id)` | se rectifica una carga de saldo hecha de más o por error (pedido del dueño 2026-11-02: dos bonos en vez de uno), en tiempo Y en plata a la vez: la venta queda ANULADA (la plata sale de la caja y de los reportes; un cierre ya hecho conserva lo que sumó) y el tiempo sale del saldo del socio (y de su PC si está jugando), todo en una transacción, con un ANULACION en el ledger. Botón "Anular carga" del Historial de Cargas (solo Admin) y Consulta de Ventas (cuando la venta cargó saldo): el mismo cartel, que dice antes qué va a pasar y después qué se hizo. Para ESTO no uses ORDENAR SALDOS (no toca la caja); ORDENAR SALDOS es para una carga que entró bien a la caja pero en la cuenta equivocada |
| `historial_cargas_repo.listar_cargas(desde, hasta, buscar, miembro_id)` · `.totales(cargas)` | se arma el Historial de Cargas de saldo de los socios (pedido del dueño 2026-10-24; botón "Historial de Cargas" de Miembros, al lado de Cargar Saldo, para cualquier operador; pantalla `control_pcs/ui/miembros_historial_cargas.py`): solo los movimientos CARGA (no consumos, reintegros ni IMPORTACION; sí las que pasaron directo a la PC del socio), con el socio, minutos, plata, medio de pago, bono o monto libre, el operador que apretó el botón (`ventas_caja.cargada_por` si cobró el Admin con la caja de una empleada) y fecha y hora. Días del local de 06:00 a 06:00. Las anuladas salen en rojo con quién y por qué, y no suman en los totales. Desde el 2026-10-29 (la ficha del socio) hay dos botones: "Historial de este socio" en la ficha del socio elegido, y "Historial de Cargas" abajo, el de todos. Con un socio elegido en Miembros abre filtrado por su id (buscar el texto "ana" trae también a "mariana") |
| `ultima_visita_repo.ultimas_visitas()` · `.dias_sin_venir(visita)` · `.no_viene_hace_mas_de(dias, limite)` | se decide hace cuántos días no viene un socio (lista de Miembros, "Última visita" de su ficha y las cifras de la cabecera, pedido del dueño 2026-10-24, para saber a quién escribirle): lo último entre su última sesión de PC con su usuario (cuando se fue, o ahora si sigue jugando) y su última carga sin anular, en días del local. No hay registro aparte de visitas: un socio que paga un bono en el mostrador sin entrar con su usuario no cuenta. En naranja pasados `dominio.DIAS_SIN_VENIR_AVISO` (15), filtro "No vienen hace más de N días" (entran también los que nunca vinieron) y orden "Más tiempo sin venir" / "Menos tiempo sin venir" (`MiembrosWindow.combo_orden`). Índice `idx_sesiones_pc_miembro` |
| `control_pcs.ui.miembros_ficha.FichaDelSocio` · `.DelegadoDeSocios` · `.Segmentos` | se dibuja la ventana de Miembros con la "ficha del socio" (maqueta B, que eligió el dueño el 2026-10-29 entre tres): a la izquierda la lista (buscador, filtros Todos / Con saldo / No vienen +N días / Sin DNI, "Mostrar inactivos" y el orden) con cada socio dibujado por `DelegadoDeSocios` (círculo con iniciales, saldo y hace cuánto vino), y a la derecha la ficha del elegido: saldo, última carga, última visita, datos de contacto, "Cargar Saldo" / "Historial de este socio" / "Modificar datos" / "Desactivar" (actúan sobre ese socio, sin marcar fila antes) y sus últimas cuatro cargas. Abajo, "$ Para Reserva", el Historial de Cargas de todos y Salir. La ficha solo dibuja: `MiembrosWindow` le pasa el socio, hace cuánto no viene, su visita y sus cargas (`historial_cargas_repo.listar_cargas`, último año). Las cifras de la cabecera son de todos los socios activos, se filtre lo que se filtre. Tras recargar sigue elegido el mismo socio |
| `miembros_repo.normalizar_dni(...)` · `.tiene_dni(miembro)` · `.normalizar_telefono(...)` | se valida y se guarda el DNI (solo números, 7 u 8 cifras), el celular y el WhatsApp de un socio, y se decide si a un socio le falta el DNI (el Cliente PC se lo pide; Miembros lo marca "Falta DNI") |
| `dominio.carga_minima_de_saldo(tramos)` · `miembros_repo.validar_monto_de_carga(...)` | se decide cuánto es lo mínimo que un socio puede cargar con un monto libre (el monto del tramo más bajo de la Tarifa por Hora para Socios; pedido del dueño, 2026-10-17) y se rechaza una carga menor: la pantalla la valida antes de abrir la ventana de cobro, el repo de nuevo al cobrar |
| `reservas_repo.crear_reserva(...)` · `reservas_habilitar_repo.habilitar(...)` · `reservas_repo.marcar_no_vino` · `.reprogramar` · `.devolver` | se toma una reserva cobrando la seña o todo, se la habilita (cobrando solo lo que falta), se la da por no venida, se la reprograma y se devuelve su plata (solo Admin). Pedido del dueño 2026-10-20; ver "Trampas conocidas". Las dos pantallas preguntan antes de cobrar (`revisar_reserva`, `preparar_habilitacion`) para no cobrar algo que después no se puede grabar |
| `reservas_repo._pasar_las_vencidas(conexion, ahora)` | se decide cuándo una reserva pasa sola a No vino / A reprogramar (su hora + `MINUTOS_TOLERANCIA_RESERVA`, 1 hora desde el 2026-11-21; los avisos la nombran con `dominio.texto_tolerancia_reserva()`, nunca "N minutos" a mano) y a Vencida (`DIAS_PARA_REPROGRAMAR_RESERVA`). No hay reloj: corre al listar (`listar_reservas`, `actualizar_estados`) |
| `reservas_socios_repo.crear_reserva_de_socio(...)` · `.horas_para_reservar()` · `.guardar_horas_para_reservar(...)` · `.marcar_llegada(...)` | se toma la reserva de un socio (pedido del dueño 2026-10-26, botón "RESERVA DE SOCIO" de Reservas, `control_pcs/ui/reservas_socio_dialogo.py`): sin seña ni venta, solo con `horas_para_reservar()` de saldo o más (arranca en `dominio.HORAS_SALDO_PARA_RESERVAR`, 5; lo cambia solo el Admin en Miembros > "$ Para Reserva") y nunca más horas que su saldo; solo PCs comunes. Al que no llega se le carga saldo desde ahí ("CARGAR SALDO", `DialogoCargarSaldo(..., a_la_sesion=False)` → `cargar_saldo_por_*(..., a_la_sesion=False)`): esa carga queda en el saldo aunque esté usando una PC, no pasa a su sesión. Se guarda con `miembro_id`, `bono_id` 0 y precio 0. Al entrar con su saldo (`abrir_estacion_por_miembro` o una carga que pasa a su sesión) `marcar_llegada` la deja Habilitada si la sesión llega a su hora; su propia reserva no lo corta (`minutos_para_el_socio(..., miembro_id)`). No se habilita desde el mostrador (`reservas_habilitar_repo` lo rechaza) y si no viene queda No vino (`_estado_si_no_viene`: con precio 0 parecería "pagó todo") |
| `dominio.nombre_equipo_reservado(equipo, nombre_pc, consola)` · `dominio.lugar_habilitado(consola_habilitada, nombre_pc)` | se nombra el equipo de una reserva (la PC, "Cualquier PC disponible", PCSTREAM, PS5-1 o PS5-2) y dónde se habilitó |
| `reservas_horario_repo.pendientes(conexion, ahora)` · `.proxima(reservas, estacion=None, consola=None)` · `.es_del_equipo(reserva, estacion=None, consola=None)` | se decide qué reserva aparta qué equipo y desde cuándo se ve RESERVADO (`MINUTOS_EQUIPO_RESERVADO_ANTES`, 2 h, hasta la hora + la tolerancia). Lo usan `pcs_repo.estado_estaciones` y `playstation_repo.estados` (`item["reserva"]`, la de cada consola), y de ahí el mosaico (`pcs_window._ficha_de_pc`, celeste `COLOR_RESERVADA`), el panel y `lugares_para_habilitar` |
| `reservas_horario_repo.reserva_que_corta(reservas, estacion, sesion)` · `tiempo_del_socio_repo.socios_jugando()` · `.segundos_totales(miembro, jugando)` | se reconoce que una reserva de OTRO corta la sesión de un socio (la sesión termina justo a su hora, entre un minuto antes y la hora: no queda anotado aparte) y cuánto tiene un socio contando lo que le queda en las PCs donde juega (pedido del dueño, 2026-11-07: Eros en la PC15X, la PC decía 6h 33m y la ficha 32h 18m, eran las dos partes de su saldo y la PC se cortaba a las 22:00 por una reserva). El mosaico dice "Hasta 22:00 · Eros" desde que entra (`item["hasta_la_reserva"]`, de `pcs_repo.estado_estaciones`; `pcs_detalle.texto_de_la_reserva` lo explica), y Miembros muestra el SALDO TOTAL (guardado + PC) en la lista y la ficha, de dónde sale cada parte y un cartel celeste (`miembros_ficha.texto_de_lo_que_juega`), releído cada 30 s; "Saldo actual" de Cargar Saldo también. El cartel de después de cargar o sumar (Cargar Saldo y ORDENAR SALDOS, `miembros_ficha.texto_de_lo_sumado`) dice lo que pasó a la PC y lo que quedó guardado por una reserva (`_sumar_carga_a_la_sesion` devuelve `guardado` y `hasta_la_reserva`; a Oscar le cargaron 13 h y decía solo "8h 40m"). ORDENAR SALDOS y Reserva de socio (la regla de las 5 h) siguen mirando solo lo guardado. Ver `tests/test_tiempo_del_socio.py` |
| `reservas_horario_repo.aviso_al_vender(estacion_id, minutos, ahora=None, consola=None)` · `.minutos_para_el_socio(...)` · `.cartel_para_la_pc(estacion)` · `.sin_pc_fija(...)` · `.pcs_libres(...)` | se avisa antes de cobrar un bono que deja el equipo ocupado a la hora de su reserva (no frena), se decide cuánto saldo usa un socio en una PC reservada (hasta la hora; lo demás le queda), qué cartel viaja a la pantalla de bloqueo (`reserva` en GET /estado) y qué va en el aviso de "Cualquier PC disponible" de arriba del mosaico (`control_pcs/ui/pcs_aviso_reservas.py`) |
| `ajustes_saldo_repo.sumar(...)` · `.restar(...)` · `.pasar(usuario_id, desde_id, hacia_id, minutos, clave)` · `.comprobar_clave_para_ordenar_saldos(...)` · `.listar_ajustes()` | se corrige a mano el saldo de tiempo de un socio (ORDENAR SALDOS, botón de abajo de Miembros que solo ve el Admin; pedido del dueño 2026-11-01: una empleada le cargó horas a un socio que no era): sumar, restar o pasar de un socio a otro (las dos puntas en una transacción; también desde otra PC, donde el botón Miembros se lo ofrece al Admin y lo graba el mostrador: está en `admin_remoto/lista_blanca.py`). Se abre con `ordenar_saldos_window.abrir_ordenar_saldos` (pide la contraseña). Solo Admin activo con la contraseña de `CLAVE_ORDENAR_SALDOS` (hoy la misma de ORDENAR Stock, en su propia constante para poder cambiar una sola), nunca un saldo negativo, y cada punta queda en `ajustes_saldo_miembro` (antes, después, quién, cuándo y el otro socio de un pase). Sin ventas: la caja no se entera. Lo que se suma a un socio que está jugando pasa a su sesión (`miembros_repo._sumar_carga_a_la_sesion`, como una carga); lo que ya corre en una PC no se resta. Pantalla `control_pcs/ui/ordenar_saldos_window.py`; los avisos dicen el tiempo con `dominio.texto_minutos` ("3 h", "1 h 30 min") |

Si necesitás uno de esos datos, **llamá a la función existente**.

## Trampas conocidas (no las rompas sin entenderlas)

- **El saldo de un socio se corrige a mano SOLO con ORDENAR SALDOS** (botón de
  Miembros, pedido del dueño 2026-11-01: una empleada le cargó horas a la cuenta
  equivocada; la plata estaba bien en la caja, el tiempo en otro socio). Mismo
  esquema que ORDENAR Stock: lo ve solo el Admin, pide la contraseña (en el repo,
  solo su hash: `ajustes_saldo_repo.CLAVE_ORDENAR_SALDOS`) y el repo la vuelve a
  exigir en cada corrección. No lo cambies por "anular la carga y volver a
  cargarla": eso saca y vuelve a meter plata en la caja (y en otro turno, en otra
  caja). Las correcciones van en `ajustes_saldo_miembro` y NO en el ledger
  `movimientos_saldo_miembro` (no tienen venta ni sesión, y ahí no hay "quién"):
  por qué le queda tal saldo a un socio sale de las dos tablas. Por lo mismo no
  cuentan como visita (`ultima_visita_repo`) ni salen en el Historial de Cargas,
  y los reintegros no las ven (salvo el CONSUMO de lo que pasó a una sesión, que
  es el de siempre).
- **Un socio se da de alta solo con usuario y clave; el DNI lo completa él en su
  primer ingreso** (pedido del dueño, 2026-10-17: tenía muchísimas cuentas de su
  programa anterior para volver a crear). El Cliente PC nuevo manda `pide_datos` en
  `POST /login`; si el socio no tiene un DNI válido (`miembros_repo.tiene_dni`), el
  servidor contesta `faltan_datos` sin abrir nada y el Cliente PC le pide DNI
  (obligatorio), celular y WhatsApp (opcionales), que llegan en un segundo login y
  se guardan en la MISMA transacción que abre la PC: con un dato mal o un DNI que ya
  es de otra cuenta activa, no queda nada guardado ni se gasta saldo. Se pregunta
  después de la clave y del saldo. Sin `pide_datos` (Cliente PC viejo, "Abrir PC con
  Miembro" del mostrador) entra como siempre: no sumes esa exigencia ahí sin que el
  dueño lo pida, trabaría a los socios en las PCs sin actualizar. "Sin dato" es `''`
  en `dni`/`telefono`/`whatsapp` (son NOT NULL y `miembros` es tabla madre: no
  reconstruirla por esto) y un nombre vacío se guarda como el usuario, así
  `miembro_nombre` nunca queda vacío (las pantallas de PCs lo usan para distinguir
  una sesión de socio de una de bono). En pantalla, `telefono` se llama "Celular".
- **La base del local tiene movimientos de saldo `IMPORTACION`** (2026-10-19): el
  dueño trajo sus 45 socios del programa anterior con una importación desde Excel
  que usó una sola vez y después pidió sacar del programa. Quedaron esas filas (sin
  venta) en `movimientos_saldo_miembro`. `dominio.MOVIMIENTO_IMPORTACION` sigue en
  `TIPOS_MOVIMIENTO_SALDO` a propósito: si una migración reconstruye la tabla sin
  ese tipo en el CHECK, el `INSERT OR IGNORE` de `_reconstruir_tabla` las descarta
  sin aviso. El panel de actividad no las muestra (`actividad_repo`). No vuelvas a
  proponer la importación salvo que el dueño la pida.
- **Una reserva no es un origen de venta: su plata son ventas comunes** (Alquiler
  de PCs o PlayStation 5) unidas a la reserva en `reservas_pagos`, como un trámite
  (pedido del dueño, 2026-10-20). El problema que resuelve: el operador que
  habilitaba al cliente que volvía tenía que "Cobrar" el bono de nuevo y en su
  cierre faltaba plata que nunca recibió. Por eso: lo que se paga al reservar
  queda en la caja de quien lo cobra, el resto en la de quien habilita, y
  **habilitar una reserva ya pagada NO crea ninguna venta** (ni una de $0). El
  bono se anota en la sesión (`sesion_bonos`, `sesion_pcstream_bonos` o
  `sesion_playstation_bonos`) con la venta del primer pago, así los reportes de
  bonos y el reintegro de socios lo cuentan una vez; en "Actividad reciente" ese
  bono no sale como "cobrado" sino como "reserva habilitada". El precio queda fijo
  al reservar (foto en la reserva). La devolución (solo Admin) es una venta en
  NEGATIVO en la caja de ahora: el cierre del turno en que entró no se toca. Si no
  viene: con seña la pierde (No vino), si pagó todo queda A reprogramar (vence a
  los 5 días); ninguna de las dos mueve plata. Una reserva se habilita solo en un
  equipo LIBRE (sumarle el tiempo a una sesión en curso se lo daría a otro
  cliente). Una de PlayStation es de UNA consola (`reservas.consola`, NULL en las de
  PC; dos PS5 desde el 2026-11-21, lo eligió el dueño): choca solo con las de su
  consola, reprogramarla no se la cambia y, como con una PC, si la suya está ocupada
  se habilita en la otra libre (`lugares_para_habilitar` la ofrece,
  `habilitar(..., consola=)`), y "Habilitada en" dice en cuál. El renglón "Reservas" aparte es solo de Caja y Cierre de Turno (lo
  eligió el dueño, variante A): el Resumen del Día y los Reportes las siguen
  contando dentro de Alquiler de PCs y PlayStation 5. Cobra: la ventana se abre
  solo en el mostrador y nada de esto está en `admin_remoto/lista_blanca.py`.
  La parte 2 ("que el programa cuide la hora", 2026-10-21, `reservas_horario_repo`):
  una PC puntual, PCSTREAM o la consola se ve RESERVADA 2 h antes (celeste si está
  libre; en uso conserva su color y dice "Res. 10:00"), venderle a otro cliente un
  bono que se pasa de la hora AVISA pero no frena (lo decidió el dueño: "avisa"), un
  socio entra solo hasta la hora y lo demás le queda en el saldo (con menos de
  `MINUTOS_MINIMOS_SOCIO_ANTES_DE_RESERVA` no entra), "Cualquier PC disponible" no
  aparta ninguna (aviso arriba del mosaico) y la pantalla de bloqueo muestra el cartel
  (Cliente PC V1.2; uno viejo no lo mira). Nada de eso escribe en la base: las vencidas
  cambian de estado al listar, y acá se ignoran las que pasaron su tolerancia. El cartel
  viaja en GET /estado en su propio try: nunca puede tocar el bloqueo. Ver
  `PROPUESTA_RESERVAS\PROPUESTA_RESERVAS.md` en la carpeta de los proyectos.
  Ojo con lo que eso deja ver (2026-11-07): el socio cortado por una reserva juega con
  una PARTE de su saldo y el resto queda guardado, así que la PC y `saldo_minutos`
  muestran números distintos y los dos son ciertos. Miembros muestra el total y el
  mosaico la hora del corte (`reservas_horario_repo.reserva_que_corta`). Con lo que le
  quedaba guardado, ese socio podía entrar a OTRA PC a la vez; desde el 2026-11-07 no
  (`miembros_repo._no_esta_jugando_en_otra_pc`, el dueño no quiere multilogin). La ficha
  sigue sabiendo mostrar "Jugando en 2 PCs" por si quedó alguno de antes.
