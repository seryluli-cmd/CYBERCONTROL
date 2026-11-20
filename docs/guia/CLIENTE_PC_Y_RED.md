# Guía: Cliente PC, servidor de red y otra PC del local

Parte de la guía de CYBERCONTROL. Lo que vale siempre (las 15 reglas y lo que no se
cambia sin que el dueño lo pida) está en [CLAUDE.md](../../CLAUDE.md); acá está lo de
esta área. Si cambiás algo de lo que dice esta guía, corregila en el mismo commit.

**Se cruza con:** [PCs y bonos](PCS_Y_BONOS.md) (las sesiones que ve la PC) y [Base](BASE_Y_PRUEBAS.md) (conexiones y espera de la base).

## Puntos únicos de verdad (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `clientes_repo.es_clave_de_clientes(clave)` | se decide si un pedido de red viene de un Cliente PC (clave fija, comparada por su huella SHA-256; la usa `servidor_red._autorizado`) |
| `fondo_repo.obtener(cual)` · `.version_actual(cual)` · `.guardar_jpeg(datos, cual)` · `.quitar(cual)` | se leen y se cambian los dos fondos de las PCs (`cual`: `fondo_repo.BLOQUEO`, el de la pantalla de bloqueo, el de siempre si no se dice; `fondo_repo.ESCRITORIO`, el wallpaper de Windows, pedido del dueño 2026-10-28): un archivo cada uno, `data/fondo_bloqueo.jpg` y `data/fondo_escritorio.jpg`, con su versión (la huella del contenido) que viaja en `GET /estado` como `fondo_version` y `escritorio_version`. `cual` llega también desde otra PC: se valida contra `NOMBRES_DE_ARCHIVO`, nunca arma una ruta con un texto suelto. La pantalla (`pcs_fondo_dialogo.preparar_jpeg`, ventana "Fondos de las PCs" con la maqueta B) lo achica con Qt; el repo valida que sea un JPEG y que no pase del tope. El wallpaper lo pone el Cliente PC desde la V2.1 (`CLIENTE PC/fondo_escritorio.py`): solo con la PC libre y de nuevo en cada arranque (Shadow Defender lo borra al reiniciar) |
| `filtro_palabras_repo.obtener()` · `.guardar(...)` · `.registrar_bloqueo(...)` | se lee y se cambia el filtro de palabras de las PCs ("protección antiporno", pedido del dueño 2026-10-17: prendido, lista y mensaje, como JSON en `configuracion`; su versión viaja en `GET /estado` como `filtro_version`) y se anota cada página que cerró una PC (`bloqueos_filtro_pc`). Buscar las palabras en los títulos es tarea de cada Cliente PC (`CLIENTE PC/filtro_palabras.py`), no de este repo |
| `actualizacion_cliente_repo.publicar(datos)` · `.version_para_estacion(id)` · `.registrar_reporte(id, parametros)` · `.estado_de_las_pcs()` · `.situacion(pc)` | se carga y FIRMA una versión del Cliente PC (`data/cliente_pc/`), se decide qué versión le toca a cada PC (las que marcó el Admin, `guardar_seleccion`; viaja en `GET /estado` como `cliente_version`), se guarda lo que cuenta cada PC (versión, carpeta, cómo va, qué versión copió) y se decide cómo está cada una para "Actualizar el Cliente PC de las PCs..." (copiando, actualizada con éxito, funcionando, apagada, error...; pedido del dueño 2026-10-18, rehecho el 2026-10-19 con la maqueta "A" que eligió). Las versiones se muestran con su número V1, V1.1... (`numero_de_version_del_exe`, y el `v` que manda cada PC). Desde el 2026-10-22 (pedido del dueño: muchas decían «Actualizada con éxito» y al reiniciarlas seguían igual) también se decide, con `seguir_la_copia`, si una PC que copió la versión se reinició sin ponerla y por qué: el reinicio borró la copia (carpeta sin excluir en Shadow Defender) o la PC no arrancó con Lanzador.exe; se sabe por la hora en que arrancó Windows (`encendida`) y queda en `estaciones.seguimiento_actualizacion`. Y se ve el número del Lanzador.exe de cada PC (`lanzador`, lo manda desde la V1.4). Una PC que manda su número (`v`) pero no el reporte tiene su Cliente PC abierto sin Lanzador.exe y no se puede actualizar: se borra lo que había contado antes y va a "Con problema" diciendo que hay que reinstalarla con preparar_pc.bat (`ARRANCA_SIN_LANZADOR`, 2026-11-01: la PC1 de la casa del dueño quedaba "Esperando" para siempre con el Lanzador de otra época) |
| `reinicio_actualizacion_repo.reiniciar_si_corresponde(item)` · `comandos_pc_repo.reiniciando(conexion, ahora)` · `.payload_reinicio_por_actualizacion(version)` | se decide si una PC se reinicia sola para poner el Cliente PC nuevo (pedido del dueño 2026-10-28): en cada GET /estado, si ya copió y comprobó la versión que le toca (exe o .zip, da igual), está libre (`congelado_repo.esta_ocupada`) y no está en mantenimiento, se le manda Reiniciar en esa misma respuesta, UNA sola vez por versión (si el reinicio no la pone, la PC la vuelve a copiar: sin ese tope se reiniciaría para siempre). Con un cliente jugando la pone el reinicio de siempre al terminar. Ese Reiniciar lleva `ACTUALIZAR:<versión>` en el payload (el Cliente PC no lo lee): el mosaico dice REINICIANDO hasta que la PC vuelve con Windows recién arrancado (`encendida`, `comandos_pc_repo._dar_por_reiniciadas`) o `MINUTOS_REINICIANDO`; y si la PC se reinició sola antes de pedirlo, al volver no se le da (se reiniciaría dos veces). Un Reiniciar del botón o del clic derecho no cambia. También dice REINICIANDO ("Reiniciando para descongelarse") la PC cuyo DESCONGELAR contestó OK, hasta que vuelve o 5 minutos (pedido del dueño 2026-10-28; con ERROR o sin respuesta no): al volver, `_dar_por_reiniciadas` le anota `PAYLOAD_VOLVIO_REINICIADA` en el payload, que se había vaciado al entregarle la clave; `reiniciando` devuelve {estacion_id: por qué} (`REINICIANDO_POR_ACTUALIZACION` / `_POR_DESCONGELAR`) y el texto de la ficha sale de `pcs_window.TEXTOS_REINICIANDO` |
| `cortes_pc_repo.leer_pulso(parametros)` · `.causa_del_corte(...)` · `.registrar_si_volvio_de_un_corte(item, pulso)` | se decide POR QUÉ una PC en uso titiló "SIN CLIENTE" y volvió sola (pedido del dueño, 2026-10-19): red, Cliente PC reabierto, PC reiniciada, Cliente PC trabado, mostrador que no anotó, o sin datos (Cliente PC viejo). Se sabe cuando la PC vuelve, con el pulso que manda en cada `GET /estado` (`CLIENTE PC/pulso.py`); se anota en `cortes_pc` y se ve en Actividad reciente, en el panel de la PC y en el cartelito de su monitor (`control_pcs/ui/pcs_cortes.py`) |
| `congelado_repo.pedir(estacion_ids, tipo, clave, discos)` · `.esta_ocupada(item)` · `.interpretar_respuesta(texto)` | se manda congelar, descongelar o ver cómo está Shadow Defender en las PCs (pedido del dueño, 2026-10-18; clic derecho en una PC, solo Admin): con la clave de Shadow Defender, que no se guarda; nunca a una PC con cliente (descongelar no manda nada si se eligió alguna; congelar y ver cómo está la saltean y la ventana lo avisa en su renglón, `.texto_salteada()`). Lo hace cada Cliente PC con CmdTool.exe (`CLIENTE PC/shadow_defender.py`) |
| `programas_pc_repo.pedir_info(id)` · `.leer_info(texto)` · `.cerrar_programa(...)` · `.abrir_programa(...)` · `mantenimiento_pc_repo.ordenar(id, orden, usuario)` · `.minutos_vigentes(estacion, enlazada)` | se ve y se maneja una PC desde el clic derecho, para cualquier operador (pedido del dueño 2026-10-22, maqueta aprobada; ventanas en `control_pcs/ui/pcs_programas_dialogo.py`): "📋 Programas y estado..." (disco, memoria, procesador, prendida hace; programas abiertos con NO RESPONDE para cerrarlos a la fuerza; íconos del escritorio para abrir uno) y "🛠️ Hacer mantenimiento (15 min)" / "Terminar mantenimiento (quedan N min)" (el de la "A", solo con la PC libre; quién lo mandó queda en `mantenimientos_remotos_pc` y Actividad reciente lo muestra si la PC contestó OK). Comandos INFO_PC, CERRAR_PROGRAMA, ABRIR_PROGRAMA y MANTENIMIENTO: los entiende el Cliente PC desde la `dominio.VERSION_CLIENTE_PROGRAMAS` (V1.6; a una PC que avisó una más vieja no se le manda nada) y vencen a los 2 min como Reiniciar. La PC solo cierra algo de su lista de ese momento y solo abre un ícono de su escritorio (`CLIENTE PC/programas_pc.py`). El JSON de INFO_PC es el único texto largo de la cola (`comandos_pc_repo.guardar_texto`, `TOPE_TEXTO_INFO`) y pedir otro vacía los viejos de esa PC. Los minutos de mantenimiento llegan como `mant` en GET /estado (`estaciones.mant_min`) |
| `pcs_libres_repo.esta_prendida_y_libre(item)` · `.prendidas_y_libres(estados)` · `.separar(estados)` · `.reiniciar(estacion_ids)` · `.apagar(estacion_ids)` | se decide qué PCs están prendidas (Cliente PC conectado) y libres (sin cliente): a esas van los botones DESCONGELAR (abre la ventana de Shadow Defender con ellas marcadas; el Administrador ve ahí ACTUALIZAR CLIENTES, que solo abre la ventana de Actualizar el Cliente PC: el dueño descongela todas, actualiza y vuelve a congelar, porque la exclusión de carpeta de Shadow Defender no siempre anda, 2026-10-28), REINICIAR y APAGAR (abren `control_pcs/ui/pcs_reiniciar_dialogo.py`, `DialogoReiniciar` / `DialogoApagar`: solo se marcan ellas y arrancan todas marcadas; desde el 2026-10-28, con la maqueta "B" que eligió el dueño, son fichas como las del mosaico y las que están en uso se ven aparte con lo que les queda, sin poder marcarse, debajo del aviso "Solo se apagan las PCs PRENDIDAS y LIBRES" que pidió; `separar` las reparte en libres, en uso y apagadas) de debajo del mosaico, afuera del fondo negro (`control_pcs/ui/pcs_botones_libres.py`, pedido del dueño 2026-10-22, APAGAR 2026-10-23: en las ventanas se desmarcan las que no se quieren tocar). Son para cualquier operador (el mantenimiento lo suelen hacer ellos); "Congelar / descongelar..." del clic derecho sigue siendo solo del Admin. `reiniciar`/`apagar` vuelven a mirar antes de mandar: una PC donde se sentó un cliente después de la pregunta no se toca. El copo de nieve de DESCONGELAR y el símbolo de APAGAR se dibujan con QPainter (`control_pcs/ui/pcs_dibujos.py`: `icono_copo_de_nieve`, `icono_apagar`, `icono_reiniciar`; el copo también va en la ventana de Congelar / descongelar): los emojis 🧊 y ⏻ salen como rectángulo en el Windows del mostrador |
| `admin_remoto_repo.esta_activo()` · `.activar(...)` · `.entrar(nombre, clave, ip)` · `.exigir_admin_habilitado(id)` | se decide quién administra desde otra PC del local: viene apagado, solo un ADMIN activo, cada ingreso en `sesiones.desde_ip` (pedido del dueño, 2026-10-18) |
| `admin_remoto.lista_blanca.FUNCIONES` · `.ACTOR` · `.huella()` | qué funciones de los repos se pueden pedir desde otra PC, qué parámetro es "quién lo hizo" (lo completa el mostrador) y la huella que tienen que compartir las dos copias del .exe (desde el 2026-11-20 incluye las casillas de permisos de Usuarios: viajan como {columna: sí/no} y la que falta se guarda apagada, así que una copia sin la casilla le sacaría el permiso a quien guarde) |
| `admin_remoto.modo.direccion_del_mostrador()` · `.es_copia_remota()` | se decide si esta copia es la del mostrador o una abierta por la red (y a qué PC le habla), y las pantallas esconden lo que solo se hace en el mostrador |
| `ui.utils.solo_en_el_mostrador` · `.avisar_que_es_en_el_mostrador(padre)` | se decide qué hace desde otra PC un botón de la pantalla principal que vende, cobra o atiende una PC: está igual que en el mostrador y avisa "Esto se hace en el mostrador" (pedido del dueño, 2026-10-24). En el mostrador no cambia nada |
| `pcs_repo.estado_de_estacion(nombre, ip)` | se decide qué estación es una PC que se conecta: por el nombre que manda su Cliente PC y, si ninguna activa se llama así, por la IP asentada en su primer enlace (`registrar_conexion`); con una IP asentada en dos estaciones activas no adivina. La usan TODOS los endpoints de `servidor_red.py` |
| `reconexion_repo.leer_tiempo_de_la_pc(parametros)` · `.tomar_el_menor(estacion_id, tiempo_pc)` | se decide qué tiempo vale cuando una PC vuelve de un corte (pedido del dueño, 2026-10-20): gana el MENOR entre lo que cuenta la PC y lo del mostrador, contando lo que se cargó durante el corte, y el mostrador lo guarda (`ajustes_reconexion_pc`, "Actividad reciente"). Nunca sube el tiempo. Lo llama `servidor_red` en `GET /estado` antes de armar la respuesta; del lado de la PC es `CLIENTE PC/reconexion.py`. Explicación para el dueño: `docs/TIEMPO_DE_LAS_PCS.md` |
| `avisos_fin_pc_repo.fin_sin_aviso(...)` · `.marcar_enterada(...)` · `.marcar_revisada(...)` | se decide si una PC se enteró de que terminó su sesión (pedido del dueño, 2026-10-21: en la PC 30 se terminó el tiempo con el Cliente PC cerrado y siguieron jugando). Toda sesión que se cierra queda `AVISO_FIN_PENDIENTE` (`pcs_repo._cerrar_sesion`) hasta que la PC vuelve a preguntar (`pcs_repo.registrar_conexion`); sin noticias pasado `UMBRAL_ENLACE_SEGUNDOS`, el monitor titila "TIEMPO AGOTADO" como la PlayStation 5 hasta que la PC vuelve (el corte se anota con su causa, `cortes_pc_repo`) o el operador aprieta "Ya revisé la PC" (queda quién y cuándo, y se ve en Actividad reciente). Las sesiones de antes quedan en NULL y no titilan |
| `pcs_sin_respuesta_repo.aviso_antes_de_cerrar(estacion_id)` · `.no_responde(item)` · `control_pcs.ui.pcs_aviso_sin_respuesta.cerrar_igual(padre, aviso)` | se avisa antes de cerrar la sesión de una PC que no responde (pedido del dueño 2026-11-09, maqueta B de `PROPUESTA_AVISO_PC_SIN_RESPUESTA`: el 02/11 se cortó la red del mostrador y a cuatro PCs se les cerró la sesión; al volver la red se reiniciaron y perdieron su tiempo). "Finalizar Sesión" (`pcs_detalle`) y "Cerrar sesión y reiniciar" (`pcs_window`) abren, en vez de la pregunta de siempre, una ventana con la cabecera cyber: hace cuánto no responde, que sin red la PC sigue contando sola, lo que pierde el cliente si se la cierra y, si dejaron de responder dos o más PCs en uso con menos de `SEGUNDOS_MISMO_CORTE` (60) de diferencia, un cartel rojo de que seguramente es la red del mostrador. NO CERRAR es la tecla de entrada; CERRAR IGUAL cierra (la PC que el cliente apagó al irse). "No responde" es lo mismo que el mosaico muestra SIN CLIENTE: no cuenta "Esperando al cliente" ni el Cliente PC cerrado desde su panel admin. Avisa, no impide. Ver `tests/test_aviso_pc_sin_respuesta.py` |
| `servidor_red._ManejadorEstado._responder_json(status, cuerpo)` · `._responder_vacio(status)` | se le contesta a un Cliente PC o a la otra PC del local; si la otra punta ya cortó, se anota en `errores.log` qué PC no recibió la respuesta y qué comando iba (`_anotar_respuesta_que_no_llego`). No escribas en `self.wfile` a mano para un JSON. Revisión general del 2026-11-16, mejora 4c |

Si necesitás uno de esos datos, **llamá a la función existente**.

## Trampas conocidas (no las rompas sin entenderlas)

- **El fondo de la pantalla de bloqueo de las PCs es un adorno que nunca puede frenar el
  bloqueo.** Vive en UN archivo, `data/fondo_bloqueo.jpg` (`fondo_repo`): `data/` está fuera
  de git y de las copias de seguridad de la base, así que si se pierde se vuelve a elegir la
  imagen. Su versión es la huella de su contenido y viaja en cada `GET /estado`
  (`fondo_version`; cadena vacía = no hay) y en la cabecera `X-Fondo-Version` de `GET /fondo`;
  las dos salen del mismo `fondo_repo.obtener()` que los bytes, para que nunca queden
  desparejas. Cada Cliente PC lo baja en un hilo aparte (`CLIENTE PC/fondo_pantalla.py`): si
  acá algo falla (disco, imagen rota), `/estado` sigue contestando sin ese dato y `/fondo`
  da 404 o 500, y la PC se queda con el gris liso. No lo muevas a la base ni lo metas en el
  camino que decide si una PC está bloqueada. Un archivo que no empieza como JPEG cuenta
  como "no hay fondo". Abrir y achicar imágenes es de la pantalla (Qt): el repo no usa Qt.
  Lo mismo vale para el wallpaper de Windows (`fondo_repo.ESCRITORIO`, `data/fondo_escritorio.jpg`,
  `escritorio_version` y `GET /escritorio` con `X-Escritorio-Version`, en su propio try): una
  falla deja a cada PC con el wallpaper que tenga. El Cliente PC lo pone solo con la PC libre,
  para no cambiarle el escritorio a alguien que está jugando: no lo cambies a "en el acto".
- **El filtro de palabras tampoco puede tocar el bloqueo.** Viaja por el mismo camino que el
  fondo (`filtro_version` en cada `GET /estado`, cada uno en su propio try/except; `GET /filtro`
  con la lista). La lista es chica a propósito (tope de 1000 palabras): cada PC la recibe
  entera cuando cambia y la revisa cada 0,7 s. Las PCs buscan PALABRAS ENTERAS sin mayúsculas
  ni acentos ("anal" no salta con "análisis"); por eso el repo rechaza palabras de una letra.
  Si se cambia cómo se guarda la lista, la versión tiene que seguir saliendo del mismo
  `obtener()` que la lista: si no, las PCs la piden en cada consulta o no se enteran del cambio.
- **Una versión del Cliente PC solo la acepta una PC si está firmada con la clave del dueño.**
  `actualizacion_cliente_repo.publicar` la firma (Ed25519) con la clave privada que vive en la
  carpeta `FirmaClientePC` del usuario de Windows de la PC del mostrador (`ruta_clave_privada`),
  FUERA de los repos: este repo es
  público y solo tiene la clave PÚBLICA (`CLAVE_PUBLICA_FIRMA`, la misma que `CLIENTE PC/actualizacion.py`;
  un test lo vigila). Nunca la escribas en el repo, en `data/` ni en un test (los tests generan una de
  prueba). Si se pierde, no se pueden mandar más versiones hasta reinstalar el lanzador PC por PC. La
  firma es lo que protege: el servidor de red no tiene forma de hacer pasar otro exe por bueno. Además:
  `publicar` rechaza un .exe que no sea el Cliente PC (busca `cliente_pc` en la lista de PyInstaller del
  final del archivo: CyberBios.exe elegido por error se abriría en las PCs en vez del bloqueo), una versión
  recién cargada no va a ninguna PC hasta que el Admin las marque (se vacía la selección; desde el
  2026-10-19 no hay PCs "de prueba": el dueño prueba en la PC de su casa), y la versión es la
  fecha y hora de carga y siempre crece. Las PCs la copian aunque tengan un cliente y una PC
  desmarcada descarta la que copió y no puso (recibe `cliente_version` en None): lo que dice la
  pantalla es lo que pasa en el reinicio. "Actualizada con éxito" exige que la versión que la PC
  copió (`version_bajada`) sea la que le toca: si no, una copia vieja parecería la nueva. El reporte de cada PC (`registrar_reporte`) se escribe solo si
  cambió: llega en cada `GET /estado` de cada PC, cada 5 s. Poner la versión en uso, vigilarla y volver
  atrás es tarea del lanzador de cada PC (`CLIENTE PC/lanzador.py`), no de acá.
  El número que ve el dueño (V1, V1.1 ... V1.9, V2; pedido del 2026-10-19) es OTRO: viene grabado en
  el exe (Propiedades -> Detalles; `numero_de_version_del_exe` lo lee) y va en el manifiesto como
  `v`; cada PC manda el suyo como `v` en cada `GET /estado`
  (`estaciones.numero_version_cliente`). Las PCs comparan la fecha: cargar una V más vieja la
  manda igual (la pantalla avisa antes). Salvo a una PC instalada a mano (`preparar_pc.bat` borra su
  `version.json`, así que no sabe su fecha): desde el Cliente PC V2.3 esa mira el `v` del manifiesto y
  no baja uno anterior al suyo; lo cuenta como error con el motivo y en la pantalla queda en "Con
  problema" hasta que se cargue otra (2026-11-02: la PC11 con la V2.1 a mano iba a bajar la V1.9).
  El número se sube en `CLIENTE PC/version_cliente.py`.
  Desde la V2 del Cliente PC (pedido del dueño 2026-10-28: la pantalla de bloqueo tardaba 21-30 s,
  casi todo desempaquetando el exe "todo en uno") la versión puede ser un **.zip con la carpeta**
  (`PCcliente_V2.zip`, de `CLIENTE PC/armar_paquete.py`): `publicar` firma un manifiesto
  "PCcliente-carpeta" con la huella del .zip y la LISTA de los archivos de adentro (huella y tamaño
  de cada uno), y se guarda como `data/cliente_pc/PCcliente.zip`. Las reglas de esa lista (nombres,
  topes) tienen que ser las mismas que comprueba la PC (`CLIENTE PC/actualizacion.py`): una prueba
  firma un .zip acá y lo desempaqueta con el código de allá. Solo le llega a una PC que manda
  `formato=2` (Cliente PC V1.9 o más con el Lanzador 3, que es el que la sabe poner): a las demás
  `version_para_estacion` les da None y la pantalla dice "Le falta la V1.9" (`FALTA_PUENTE`). Por
  eso el paso es en dos cargas: la V1.9 (un exe, como siempre) a todas, y la V2 recién cuando todas
  muestran Lanzador 3 (se guarda una sola versión cargada).
- **La clave de Shadow Defender nunca queda guardada** (congelar/descongelar PCs, pedido del dueño,
  2026-10-18). Shadow Defender no tiene consola de red: cada PC corre su CmdTool.exe, que sin la clave
  no hace nada, así que la clave viaja en el `payload` de DESCONGELAR/CONGELAR/ESTADO_CONGELADO
  (`dominio.COMANDOS_CON_CLAVE`). La escribe el dueño en la ventana cada vez; `comandos_pc_repo` la borra
  del payload apenas viaja (`marcar_entregado`), si la PC no la pide en `MINUTOS_VIGENCIA_CON_CLAVE`
  (en cada `GET /estado` de esa PC, con el índice por estación), al cerrar la ventana y al arrancar el
  servidor de red. No la guardes en `configuracion` "para no tipearla": cualquiera con
  `data/kiosko.db` la leería, y las cuentas de Windows de las PCs son de Administrador (tampoco va
  guardada allá). Descongelar reinicia la PC: `congelado_repo.pedir` no lo manda a una PC con cliente
  (y el Cliente PC lo vuelve a revisar). Congelar y ver cómo está tampoco (pedido del dueño,
  2026-10-19): la clave viajaría a una PC donde el cliente es Administrador y podría leerla en la línea
  de comandos de CmdTool; se saltean esas PCs y se hacen las demás. Para que CmdTool arranque, la
  tarea del Cliente PC corre elevada (`HighestAvailable`, ver
  `CLIENTE PC/win32_utils.configurar_inicio_automatico`).
- **El servidor de red no debe tocar Qt.** Usa conexiones SQLite propias desde
  sus hilos y registra fallos inesperados con `errores.registrar_error`, sin
  incluir claves ni el cuerpo de los pedidos en el contexto del log.
- **El refresco de PCs distingue esperar de perder el Cliente PC.** Si la
  estación aún no se conectó desde que arrancó el bono, muestra "Esperando al
  cliente"; si se desconecta después de estar enlazada, avisa "SIN CLIENTE".
  `pcs_repo._estado_para_estacion` decide esto para la grilla y para el Cliente PC.
  "Desconectada" es más de `UMBRAL_ENLACE_SEGUNDOS` (30 s desde el 2026-10-19;
  antes 15, y 2 o 3 consultas perdidas hacían titilar una PC sana). El corte se
  anota recién cuando la PC vuelve (`cortes_pc_repo`), con el estado de ANTES de
  esa consulta: `registrar_conexion` y el corte usan el mismo `item`, así que el
  orden entre los dos no importa. Un corte que empezó antes de abrir el programa
  no se anota: con el mostrador cerrado se quedan sin noticias todas las PCs.
  Con la sesión ya terminada también hay alerta si la PC no se enteró
  (`avisos_fin_pc_repo`, 2026-10-21): hasta ese día el refresco cerraba la sesión
  y el monitor pasaba al rojo fijo de "Sin conexión", el de una PC apagada, aunque
  siguieran jugando. No hagas que esa alerta se apague sola: la apaga la PC al
  volver o el operador con "Ya revisé la PC". Una orden de reiniciar no lo
  reemplaza: viaja por la misma consulta que la PC no está haciendo. Lo que sí
  reinicia una PC con el Cliente PC cerrado es su seguro de fin de sesión (V1.3,
  `CLIENTE PC/seguro_fin.py`): una tarea de Windows a la hora de fin + 2 minutos.
  Al volver la PC lo cuenta (`dominio.REINICIO_SEGURO_FIN`) y Actividad reciente
  dice que el Cliente PC no estaba andando.
- **GET /estado (40 PCs, cada 5 s) no toma el permiso de escritura si no hay nada que
  cambiar, y no se le cambian los nombres** (revisión general del 2026-11-16, mejora 4).
  Un UPDATE que no cambia ninguna fila igual toma el permiso de escritura de la base, y
  una venta en ese instante espera. Por eso la temperatura y el mantenimiento se comparan
  con la fila que la consulta ya leyó (`temperatura_pc_repo.registrar_si_cambio`,
  `mantenimiento_pc_repo.registrar_si_cambio`) y la cola de comandos mira con un SELECT
  antes de vencer nada (`comandos_pc_repo._cambiar_si_hay`): una consulta sin novedades
  escribe UNA vez, la "última conexión". Algo nuevo que se grabe en cada consulta va igual:
  solo si cambió (lo mide `tests/test_contrato_cliente_pc.py`). Los nombres de la respuesta
  los lee el Cliente PC, que está en otro repo: la misma prueba revisa los 11
  (`CAMPOS_QUE_LEE_EL_CLIENTE_PC`) y, con la carpeta `CLIENTE PC` al lado, los lee con su
  `red_kiosko.py` de verdad y saca de su código cuáles lee. Una respuesta que no llega (la
  PC se cansó de esperar sus 3 s) queda en `errores.log`, con el comando que iba si había
  uno (`servidor_red._anotar_respuesta_que_no_llego`): ese comando quedó ENTREGADO sin
  llegar y hay que volver a mandarlo. Que la PC confirme los comandos y que los avisos no
  se dupliquen (4d y 4e) necesita una versión nueva del Cliente PC: no está hecho.
- **Una PC se reconoce por su nombre y, si no, por su IP asentada** (pedido del
  dueño, 2026-10-17). `estaciones.ip_asentada` es la IP del PRIMER enlace y no se
  pisa sola (`ultima_ip` sí, en cada conexión); solo se borra a mano desde
  Gestionar Estaciones y se vuelve a asentar en la próxima conexión por nombre. La IP
  sale del socket (`self.client_address`), nunca de un dato que mande el Cliente PC,
  y se mira DESPUÉS de la clave de Clientes PC. El nombre siempre gana; una IP
  asentada en dos estaciones activas no reconoce a ninguna (no adivinar: daría el
  tiempo de una PC a otra). Las PCs del local tienen IP fija; si alguna pasara a
  DHCP, la IP asentada podría quedar en otra máquina. Ver `tests/test_ip_asentada.py`.
- **El tiempo de las PCs no depende de que haya alguien logueado ni de que el
  mostrador esté prendido** (ver `docs/TIEMPO_DE_LAS_PCS.md`, pedido del dueño
  2026-10-20). El servidor de red arranca con el programa, no con el login: cerrar
  sesión no toca a las PCs. El mostrador guarda la HORA de fin de cada sesión, así
  que su cuenta no se frena con el programa cerrado; cada Cliente PC cuenta solo
  durante un corte. Al volver gana el menor (`reconexion_repo`): no lo cambies a
  "gana el mostrador" ni a "gana la PC" sin que el dueño lo pida, y nunca dejes que
  lo que manda la PC SUBA el tiempo (cualquiera puede tocar una PC). Lo que se cargó
  durante el corte se le suma a la cuenta de la PC antes de comparar: si no, un bono
  vendido con la PC desconectada se perdería. Con nadie logueado nadie cierra las
  sesiones vencidas (lo hace `PanelControlPcs._refrescar`): por eso
  `_abrir_o_extender_sesion` no estira una sesión que ya llegó a cero y
  `_cerrar_sesion` anota como fin real la hora en que llegó a cero.
- **Administrar desde otra PC: la base la toca SOLO el mostrador** (pedido del
  dueño, 2026-10-18; ver `admin_remoto/` y `docs/ADMIN_REMOTO.md`). El
  `CyberBios.exe` abierto desde la carpeta compartida del mostrador es una copia
  remota (`admin_remoto/modo.py`): no abre ninguna base (`conexion_db` queda
  cerrada a propósito) y cada función de la lista blanca viaja al mostrador por
  `POST /admin/...` del servidor de red. Nunca hagas que una copia abra
  `data/kiosko.db` por la red: SQLite por una carpeta compartida puede dañar el
  archivo con todas las ventas. Consecuencias: (1) una pantalla **nunca** importa
  una función suelta de un repo (`from repositories.x import f`): la copia remota
  reemplaza las funciones en su módulo y una suelta seguiría yendo a la base; (2)
  si una pantalla que se abre desde otra PC empieza a usar otra función de un
  repo, va a `admin_remoto/lista_blanca.py` (con su `ACTOR` si recibe quién lo
  hace) — `tests/test_admin_remoto.py` lo vigila; (3) lo que solo se hace en el
  mostrador (vender, cobrar, cajas y turnos, atender las PCs, Miembros salvo
  ORDENAR SALDOS, Actualizar el Cliente PC, Copias de Seguridad) NO entra en la
  lista: desde el 2026-11-01 el botón Miembros de la otra PC le ofrece al Admin
  ORDENAR SALDOS (`MainWindow._ordenar_saldos_desde_otra_pc`), que no mueve plata. La
  pantalla principal se ve igual que en el mostrador, con la grilla de PCs en
  vivo (pedido del dueño, 2026-10-24: "quiero que se vea tal cual"): ahí esos
  botones están y avisan con `ui.utils.solo_en_el_mostrador` (un test revisa que
  todo lo que esa pantalla le pide a un repo esté en la lista, no vaya a la base
  o avise); en las demás pantallas se esconden con `modo.es_copia_remota()`. Sin
  respuesta del mostrador, la grilla deja lo último con un aviso rojo y prueba
  cada 30 s (cada intento sin respuesta traba la ventana hasta 2 s,
  `cliente.ESPERA_CONECTAR_SEGUNDOS`); (4) el cierre forzoso de la caja y dar
  de baja las sesiones vencidas lo hace solo el mostrador; (5) una consulta de reporte lenta frena las
  ventas del mostrador mientras dura (sin WAL, SQLite no deja grabar mientras otro
  lee): cada conexión de `get_connection` espera hasta 30 s
  (`database.ESPERA_BASE_OCUPADA_SEGUNDOS`, 2026-10-28; con la espera de fábrica de
  5 s la venta FALLABA con "database is locked"), así que la venta espera y se
  graba, pero el mostrador queda trabado mientras tanto. Todo lo que se lee desde
  otra PC tiene que andar rápido con un año de ventas
  (medido el 2026-10-18: todo < 0,2 s con 110.000 ventas, después de sumar
  `idx_venta_pagos_venta`; sin ese índice Por Operador tardaba 6 minutos). No
  pases la base a WAL sin hablarlo: deja archivos -wal/-shm y cambia cómo se
  recupera una copia; (6) si la red se corta DESPUÉS de mandar un pedido (se
  perdió la respuesta o pasó la espera), el mostrador pudo haberlo grabado:
  `admin_remoto/cliente.py` lo distingue (`SinRespuesta`, una `SinConexion`) y
  avisa que se fije antes de repetirlo. No lo juntes con el "No encuentro el
  CyberBIOS del mostrador", que es solo para cuando el pedido no llegó (repetir a
  ciegas una compra la carga dos veces y suma el stock doble; lo vigila
  `TestSeCortaEsperandoLaRespuesta`). El saludo y el ingreso no graban nada: ahí
  un corte da un aviso neutro.
