# Guía: PCs, bonos, PlayStation 5 y ofertas

Parte de la guía de CYBERCONTROL. Lo que vale siempre (las 15 reglas y lo que no se
cambia sin que el dueño lo pida) está en [CLAUDE.md](../../CLAUDE.md); acá está lo de
esta área. Si cambiás algo de lo que dice esta guía, corregila en el mismo commit.

**Se cruza con:** [Socios y reservas](SOCIOS_Y_RESERVAS.md) (saldo, reintegros y la PC reservada), [Cliente PC y red](CLIENTE_PC_Y_RED.md) (lo que ve y manda cada PC) y [Ventas](VENTAS_Y_ARTICULOS.md) (la ventana de cobro).

## Puntos únicos de verdad (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `pcs_repo.estado_estaciones()` | se calcula el tiempo restante y estado de cada PC |
| `pcs_repo._orden_natural(estacion)` | se ordenan las estaciones como lo haría una persona ("PC2" antes que "PC10"), con PCSTREAM antes que todas (en el mosaico queda al lado de la PlayStation 5); lo usan `listar_estaciones` y `estado_estaciones` |
| `dominio.es_pcstream(nombre)` | se decide si una estación es PCSTREAM, la PC de streaming (solo por el nombre, sin espacios/guiones/mayúsculas; pedido del dueño, 2026-10-17). `estado_estaciones` lo trae en `item["es_pcstream"]` para la pantalla |
| `pcstream_repo.uso_por_dia(desde, hasta)` | se calcula cuánto se usó PCSTREAM, en tiempo (vendido y de uso real) y en plata (Reportes > PCSTREAM) |
| `pcs_repo._cerrar_sesion(conexion, sesion, ahora, motivo, usuario_id)` · `pcs_repo.finalizar_sesion(sesion_id, motivo, usuario_id)` | se cierra una sesión de PC dentro de una transacción (reintegro del socio incluido; la hora de fin real nunca pasa de la prevista). La usan `finalizar_sesion` y `_abrir_o_extender_sesion`, que cierra una sesión que ya llegó a cero en vez de estirarla. Queda cómo se cerró (pedido del dueño 2026-11-09: dos PCs se cerraron con "Finalizar Sesión" estando sin conexión, perdieron su tiempo al volver la red y no quedaba quién lo hizo): `sesiones_pc.motivo_cierre` (uno de `dominio.MOTIVOS_CIERRE`: el botón Finalizar Sesión, Cerrar sesión y reiniciar, el socio desde su PC o el tiempo terminado), `cerrada_por` (el operador; NULL si la cerró el programa o el socio) y `segundos_quedaban_al_cerrar`. Todo camino nuevo que cierre una sesión pasa el suyo. Actividad reciente lo dice (`pcs_actividad.texto_del_cierre`); las sesiones de antes quedan en NULL y dicen "sesión finalizada". Ver `tests/test_quien_cierra_la_sesion.py` |
| `pcs_window.PanelControlPcs._ficha_de_pc(...)` · `._ficha_de_playstation(...)` | se decide con qué color, dibujito y aviso se ve cada equipo en el mosaico; `control_pcs/ui/pcs_mosaico.py` solo dibuja la `Ficha` que recibe |
| `pcs_repo.asignar_bono(...)` | se crea o extiende una sesión de PC con un bono del mostrador: el COMÚN (walk-in) o, si la PC es PCSTREAM, uno de SU catálogo (`pcstream_repo`) |
| `ofertas_repo.como_se_vende(conexion, equipo, bono, momento, bono_mostrado)` · `.momento_del_cobro(...)` · `.activas(momento)` · `.con_las_ofertas(equipo, bonos, ofertas)` · `.guardar_oferta(...)` · `.pausar_oferta` · `.reanudar_oferta` · `.terminar_oferta` | se decide con qué minutos y qué precio se vende un bono de PC, PCSTREAM o la PlayStation 5 cuando corre una OFERTA (pedido del dueño 2026-11-13: 2x1 = el doble de tiempo por la misma plata, 50% = la mitad de plata redondeada al peso; `con_oferta`). La usan dentro de su transacción `pcs_repo.asignar_bono`, `playstation_repo.vender_bono` y `cuentas_pc_repo.anotar_bono`, y lo vendido guarda `oferta_id` en `sesion_bonos`, `sesion_pcstream_bonos`, `sesion_playstation_bonos` y `cuenta_pc_items` con los minutos y el precio cobrados de verdad. Cada oferta va por cuadritos de la semana (día y turno: `franjas_de_la_semana`, la Noche cruza la medianoche y el domingo tiene T1 y T2), entre dos fechas y en los bonos elegidos; dos ofertas no pueden tocar el mismo bono en el mismo turno de hoy en adelante (`ChocaConOtraOferta`, las pausadas cuentan). Solo el Admin las arma, pausa y termina (también desde otra PC); nada se borra. La ventana es `control_pcs/ui/ofertas_window.py` (Configuración ADMIN > Ofertas, maqueta B "la semana en una grilla"); en el panel de la PC, `pcs_lista_de_bonos.py` (maqueta P1: la etiqueta en el botón y el cartel arriba). Las frases ("Así queda:", las próximas veces) también salen del repo. Ver `tests/test_ofertas.py` y `tests/test_ofertas_ui.py` |
| `dominio.segundos_restantes(fin, ahora)` · `dominio.fin_al_sumar_minutos(fin_actual, minutos, ahora)` | se calcula cuánto le queda a una sesión de tiempo y cuándo vence al sumarle un bono (PCs Y PlayStation 5: una sola cuenta) |
| `playstation_repo.estado()` · `.vender_bono(...)` · `.finalizar_sesion(...)` | se sabe cómo está la PlayStation 5, se le vende un bono (origen PLAYSTATION) y se la libera; ahí mismo se exige ser Admin para el catálogo (vender y liberar, cualquier operador) |
| `anular_bono_repo.resumen_de_bono(venta_id)` · `.bonos_de_la_sesion(estacion_id=None)` · `.anular_bono(venta_id, usuario_admin_id, motivo)` · `ui.anular_bono.anular_bono_con_cartel(parent, usuario, venta_id)` | se quita un bono de PC, de PCSTREAM o de la consola vendido de más (pedido del dueño 2026-11-02: dos bonos de 5 h a un cliente por error): la venta queda ANULADA y a la sesión se le acorta `fecha_fin_prevista` (lo que sumó el bono, topeado a lo que le queda, nunca antes de ahora; si la sesión ya se cerró, solo la plata), en una transacción. Botón "Quitar un bono" del panel de la PC (solo Admin, `@solo_en_el_mostrador`; elige entre los bonos de la sesión en curso) y Consulta de Ventas (cuando la venta vendió un bono; el de una reserva sigue por el camino viejo). Un bono anulado ya no cuenta en `reintegros_repo.contribuciones_de_sesion` ni en el feed de `actividad_repo`. Un bono anotado a la Cuenta de la PC y todavía sin cobrar se saca con `cuentas_pc_repo.quitar_renglon`. `resumen_de_bono`/`anular_bono` están en la `lista_blanca` (administrar desde otra PC); `bonos_de_la_sesion` no |
| `cuentas_pc_repo.anotar_articulos(...)` · `.anotar_bono(...)` · `.anotar_tiempo_socio(...)` · `.cobrar(cuenta_ids, usuario_id, pagos)` · `.quitar_renglon(...)` · `.dar_por_perdida(...)` · `.obtener_reglas()` · `.guardar_reglas(...)` · `.aviso_antes_del_cierre()` · `.fiado_del_turno_en_curso()` · `deudas_pc_repo.por_estacion(conexion)` · `.fiado_del_turno(...)` · `.anotar_fiado_en_el_cierre(...)` | se maneja la Cuenta de la PC (pedido del dueño 2026-10-25: el cliente que juega pide un pancho o más tiempo y paga después): se anota en la cuenta de SU SESIÓN (`cuentas_pc`, una por sesión: si se cambia de PC va con él; si se va debiendo, la PC sigue debiendo y el próximo cliente tiene la suya), el artículo baja el stock al anotarse y el bono suma el tiempo ya (solo a una sesión en curso); la PC titila con borde fucsia y "DEBE $ X" (`item["deuda"]` de `pcs_repo.estado_estaciones`, `pcs_mosaico.COLOR_DEBE`) hasta que se cobra con la ventana de cobro de siempre: una venta de kiosko SIN volver a bajar el stock (`ventas_repo._grabar_venta_kiosko(..., descontar_stock=False)`) y una de Alquiler de PCs por bono con su `sesion_bonos`/`sesion_pcstream_bonos`, con los pagos repartidos por `dominio.repartir_pagos`. Anotar y cobrar: cualquier operador, en el mostrador (VENDER "A cuenta de una PC...", el panel de la PC, `control_pcs/ui/cuenta_pc_dialogos.py`); quitar un renglón y dar por perdida: solo Admin, con motivo. El tope (arranca en $10.000), qué pasa al pasarlo (no deja, o con la clave de un Admin) y si se anota tiempo los fija el Admin en Configuración ADMIN > Reglas de Cuenta de PC (`control_pcs/ui/cuenta_pc_reglas_dialogo.py`). Movimientos muestra lo anotado sin cobrar o perdido. A un socio se le anota tiempo de socio (bono de socio o monto con su tarifa, `DialogoTiempoSocio`): se suma a su sesión SIN tocar su saldo y, mientras no lo paga, cuenta como bono para los reintegros; al cobrarlo queda como una carga suya que pasó a la sesión (CARGA con la venta + CONSUMO, los dos con la hora en que se anotó). Lo fiado en un turno se cobra en ese turno (pedido del dueño, mismo día): desde `dominio.MINUTOS_AVISO_CUENTAS_ANTES_DEL_FIN` (15) antes del fin del turno las PCs que lo deben titilan más rápido (`PanelControlPcs.marcar_cuentas_urgentes`) y sale `DialogoCobrarAntesDelCierre` con un "Cobrar" por PC y "Posponer 5 min" (`MainWindow._revisar_cuentas_antes_del_cierre`; no hay "Ya lo cobré" a propósito: apagarlo a mano dejaría plata fuera de la caja); al apretar Cierre de Turno pregunta otra vez, y si se cierra igual (o es el cierre forzoso) `turnos_repo.cerrar_turno` deja en `cierres_fiado_pc` lo anotado en ese turno sin cobrar, a nombre de quien cerró, y Control de Cierres lo muestra ("Fiado sin cobrar al cerrar"). No cambia lo que hay que retirar |
| `control_pcs.repositories.catalogo_bonos.CatalogoDeBonos(tabla)` | se hace el alta/edición/baja de un catálogo de bonos (`pcs_repo` para walk-ins, `bonos_miembro_repo` para socios, `playstation_repo` para la consola, `pcstream_repo` para la PC de streaming: cuatro tablas distintas, un solo código) |

Si necesitás uno de esos datos, **llamá a la función existente**.

## Trampas conocidas (no las rompas sin entenderlas)

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
- **Hay CUATRO catálogos de bonos, nunca la misma tabla** (los dos de abajo más
  `bonos_playstation`, ver la trampa de la PlayStation 5, y `bonos_pcstream`, ver
  la de PCSTREAM). `bonos_tiempo`
  (`pcs_repo`) es para cualquiera que entra al local sin ser socio
  (walk-in, `pcs_repo.asignar_bono`). `bonos_miembro` (`bonos_miembro_repo`)
  es exclusivo de Miembros, usado solo desde "Cargar Saldo" -> "Bono fijo"
  (`miembros_repo.cargar_saldo_por_bono`). El dueño pidió la separación
  explícitamente (2026-09-28) para poder ofrecerle a los socios combos
  propios sin tocar el catálogo del mostrador. Crear/editar/desactivar un
  bono, de cualquiera de los dos catálogos, es exclusivo de ADMIN desde
  "Configuración ADMIN" (`ui/configuracion_admin_window.ConfiguracionAdminWindow` —
  pedido explícito del dueño, 2026-09-28: editar el catálogo es tarea de
  super admin; *usar* un bono ya creado (cargarle saldo a un socio con
  "Bono fijo", o vender el de la PlayStation 5) abre para cualquier
  operador, pedido del dueño 2026-10-19). No fusionar estos catálogos
  "para simplificar":
  son dos negocios distintos con reglas de negocio propias, aunque ahora
  compartan el mismo nivel de permiso para editarlos.
- **La PlayStation 5 NO es una "estación" y no se debe volver una.** Es una
  sola consola, nombre fijo `dominio.NOMBRE_PLAYSTATION`, con sus propias tablas
  (`bonos_playstation`, `sesiones_playstation`, `sesion_playstation_bonos`) y su
  propio repo (`playstation_repo`), aunque se vea como el primer monitor del
  mosaico de Control de PCs. Una estación es una PC con Cliente PC (bloqueo,
  reinicio, apagado, IP, renombrar, baja): si la consola viviera en `estaciones`
  todo eso la alcanzaría, y a la consola no le corresponde nada. Por lo mismo,
  `playstation_repo` no tiene ningún `estacion_id` y `pcs_repo.asignar_bono` solo
  acepta una fila activa de `estaciones`: **un bono de PC no puede ir a la
  consola ni uno de la consola a una PC**, aunque dos ids coincidan (cada camino
  lee SOLO su catálogo; `PanelDetalleEstacion` además toma la lista de bonos del
  equipo elegido y deshabilita la otra). Cada equipo del mosaico trae su tipo en
  `item["dispositivo"]`.
- **PCSTREAM SÍ es una estación, con precios propios** (la PC de streaming, pedido
  del dueño 2026-10-17). Es una fila de `estaciones` con su Cliente PC y se bloquea
  como cualquier PC; se la reconoce SOLO por el nombre (`dominio.es_pcstream`: si
  el Admin la renombra, vuelve a ser una PC común). Lo propio: su catálogo
  `bonos_pcstream` (`pcstream_repo`, se edita desde Configuración ADMIN) y su tabla
  de vínculo `sesion_pcstream_bonos` — `sesion_bonos.bono_id` apunta a
  `bonos_tiempo`, así que un bono de PCSTREAM no puede ir ahí. `pcs_repo.asignar_bono`
  elige el catálogo por el nombre de la estación, así que a PCSTREAM no se le vende
  un bono común ni uno suyo a otra PC aunque los ids coincidan. Además: los socios
  no la pueden abrir (`miembros_repo.abrir_estacion_por_miembro` lo rechaza, también
  desde el Cliente PC), no entra en "Intercambiar de máquina" (`trasladar_sesion`
  lo rechaza: le daría a una PC el tiempo cobrado con la tarifa de la otra) y va al
  lado de la PlayStation 5 en el mosaico. Su plata entra como Alquiler de PCs (no
  hay origen de venta aparte, a propósito: sumar uno toca la caja); cuánto vendió y
  se usó se ve en Reportes > PCSTREAM (`pcstream_repo.uso_por_dia`), que reconoce
  sus sesiones por `sesion_pcstream_bonos` y no por el nombre actual.
- **La sesión de la PlayStation 5 NO se da de baja sola al llegar a cero.** A
  diferencia de una PC (que se bloquea y `PanelControlPcs._refrescar` la libera),
  acá el aviso es para una persona: queda `ACTIVA` con `tiempo_agotado`, su monitor
  titila en rojo (mismo parpadeo que "SIN CLIENTE") y sigue así —también si se
  cierra y reabre el programa, el vencimiento es una fecha absoluta— hasta que el
  operador la libera ("Ya avisé: liberar la consola") o le vende otro bono (que
  cuenta desde ahora, ver `dominio.fin_al_sumar_minutos`). La cuenta regresiva se
  redibuja cada segundo (`PanelControlPcs._actualizar_cuenta_regresiva`, un timer
  aparte del refresco de 5s). Si alguna vez se hace que esa sesión se libere sola,
  se pierde el aviso: no lo hagas sin que el dueño lo pida.
- **Permisos de la PlayStation 5: se hacen cumplir en el repo, no solo en la
  pantalla.** Vender un bono y liberarla: cualquier operador logueado; crear,
  modificar o dar de baja sus bonos: solo ADMIN (`playstation_repo` levanta
  `PermissionError`, que `ui.utils.manejar_errores` muestra como mensaje). Se
  vuelve a leer el usuario de la base en cada operación, así que un usuario
  desactivado corta el acceso en el acto. Hasta el 2026-10-19 vender/liberar
  pedía además el permiso `permiso_control_pcs` ("Operar PCs y Miembros") —
  la misma asimetría que tenía Miembros con el resto de la barra (las PCs
  ya estaban abiertas a cualquier logueado) — y se sacó el mismo día por el
  mismo motivo. El 2026-10-22 se sacó su casilla de Usuarios (pedido del
  dueño: "así no está por estar"): ya no daba nada, salvo hacer "encargada" a
  quien la tuviera, con un Admin Kiosko vacío. La columna
  `usuarios.permiso_control_pcs` sigue en la base con lo que tenía cada uno
  (regla 6), pero nadie la lee ni la escribe. Si el dueño quiere repartir
  quién opera qué, se vuelve a sumar a `usuarios_repo.PERMISOS_EMPLEADA` y se
  engancha en `playstation_repo.puede_operar` o en Miembros.
- **Una oferta vale a la hora en que se COBRA, y lo que se mostró es lo que se cobra**
  (ofertas 2x1 / 50%, pedido del dueño 2026-11-13; `ofertas_repo`). El panel de la PC
  arma los botones con las ofertas que corren en ese refresco y anota la hora
  (`PanelDetalleEstacion._momento_de_los_precios`); al cobrar, esa hora viaja como
  `momento_del_precio` y el repo calcula con ella (`momento_del_cobro`, hasta
  `MINUTOS_PARA_TERMINAR_DE_COBRAR` atrás): si la oferta termina a las 06:00 con la
  ventana de cobro abierta, se cobra lo que decía el botón. No calcules el precio en la
  pantalla ni lo mandes desde ahí: la pantalla muestra lo que dice el repo, y el repo lo
  vuelve a calcular dentro de la transacción. Junto con la hora viaja el bono como se vio
  (`bono_mostrado`): si el Admin pausó o cambió la oferta, puso una nueva o cambió el
  precio del bono mientras se cobraba, `como_se_vende` tira ValueError y no graba nada
  (revisión del 2026-11-13: si no, la venta quedaba con un total distinto de la plata
  cobrada). Terminarla no: queda fechada y vale lo que se mostró. Lo que NO lleva oferta, decidido con el
  dueño: los bonos de Socios (`guardar_oferta` los rechaza), la carga de saldo por monto
  y las reservas (su precio queda fijo al reservar; `reservas_*` no miran ofertas). Un
  bono anotado a la Cuenta de la PC con oferta la conserva aunque se cobre después
  (`cuentas_pc_repo._cobrar_bono` copia el `oferta_id` del renglón). Como lo vendido
  guarda los minutos y el precio de verdad, anular un bono, los reintegros y los reportes
  no saben nada de ofertas: si sumás algo que recalcula un bono desde su catálogo, mirá
  primero lo que quedó en la venta.
- **Lo que corre en cada refresco de la pantalla de PCs (cada 5 s) no puede leer
  todo el historial.** `pcs_repo.estado_estaciones` y el panel "Actividad reciente"
  (`actividad_repo.actividad_reciente`, con `playstation_repo.eventos_recientes`)
  piden "lo último" apoyados en los índices de `database_esquema` ("ÍNDICES"); los
  bonos se ordenan por número de venta, no por `ventas.fecha`, para no recorrer la
  historia. Sin eso, con un año de uso la pantalla se trababa ~0,4 s cada 5 s
  (revisión del 2026-10-17). Una consulta nueva en ese camino necesita su índice:
  `tests/test_velocidad_pantalla_pcs.py` mide que el trabajo no crezca con el
  historial.
- **Un traslado de PC conserva la sesión y su saldo.** `pcs_repo.trasladar_sesion`
  mueve o intercambia la misma sesión bajo `BEGIN IMMEDIATE`; el historial de
  qué PC ocupó está en `traslados_sesion`, no en el nombre actual de la estación.
- **Un bono anotado en la Cuenta de la PC es un bono para los reintegros de socios.**
  Mientras no se cobra no tiene fila en `sesion_bonos`, así que
  `reintegros_repo.contribuciones_de_sesion` lo saca de `cuenta_pc_items`; ya cobrado,
  su fila de `sesion_bonos` va con la hora en que se ANOTÓ (cuando se sumó el
  tiempo), no con la del cobro (`cuenta_pc_items.sesion_bono_id`). Sin eso, al
  cortar la sesión de un socio se le devolvía como saldo el tiempo del bono fiado, y
  la reconexión de una PC lo contaba mal. Un renglón de artículo guarda el código:
  está en `articulos_repo._TABLAS_CON_CODIGO_DE_ARTICULO`. La consola no tiene cuenta.
