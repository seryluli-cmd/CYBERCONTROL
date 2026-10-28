# Guía de trabajo para Claude — Sistema de Kiosko

## Por qué existe este archivo

El programa sigue creciendo y conviene mantenerlo ordenado. El pedido del
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

**Dos negocios, un solo programa.** Desde el 2026-09-26, Control de
PCs/Miembros/Bonos/Historiales vive en su propio paquete `control_pcs/`
(con su propio `ui/` y `repositories/` adentro), separado del `ui/` y
`repositories/` de arriba que quedan solo para el negocio de kiosko —
son dos negocios distintos para el dueño, aunque comparten programa,
login y base de datos. Ver "Qué no cambiar sin que el dueño lo pida
explícitamente" y "Estado" más abajo para el detalle.

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
| Rol | `ROL_ADMIN`, `ROL_EMPLEADA`, `ROLES` — y `dominio.es_admin(usuario)` |
| Estado de venta | `VENTA_CONFIRMADA`, `VENTA_ANULADA`, `ESTADOS_VENTA` |
| Método de pago | `PAGO_EFECTIVO`, `PAGO_DIGITAL`, `METODOS_PAGO` (no hay "mixto": ver más abajo) |
| Turno | `TURNO_MANANA`, `TURNO_TARDE`, `TURNO_NOCHE`, `TURNOS` |
| Origen de una venta | `ORIGEN_KIOSKO`, `ORIGEN_ALQUILER_PCS`, `ORIGEN_PLAYSTATION`, `ORIGENES_VENTA` |
| Equipo que se alquila por tiempo / estado de su sesión | `DISPOSITIVO_PC`, `DISPOSITIVO_PLAYSTATION`, `NOMBRE_PLAYSTATION`, `NOMBRE_PCSTREAM`, `SESION_ACTIVA`, `SESION_FINALIZADA` |
| Comando a una PC / su estado en la cola | `TIPOS_COMANDO_PC` (los de Shadow Defender, en `COMANDOS_CON_CLAVE`; el payload de `COMANDO_MANTENIMIENTO`, en `ORDENES_MANTENIMIENTO`), `ESTADO_COMANDO_PENDIENTE`, `ESTADO_COMANDO_ENTREGADO` |
| Aviso de admin de una PC | `EVENTOS_ADMIN_PC` (los que manda el Cliente PC + `CLIENTE_REANUDADO`) |

Un typo en uno de esos strings **no falla ruidosamente**: la consulta
devuelve cero filas y nadie se entera hasta que falta plata en un cierre.
Nombrándolos, un typo es un error de Python que salta al instante.

Esto vale también dentro del SQL: el estado va como parámetro
(`WHERE estado = ?` con `dominio.VENTA_CONFIRMADA`), no como literal
pegado en la consulta. Y los `CHECK (... IN (...))` del esquema también salen
de las listas de `dominio.py` (`ROLES`, `ESTADOS_VENTA`, `TURNOS`,
`ORIGENES_VENTA`, `EVENTOS_ADMIN_PC`, `ESTADOS_COMANDO_PC`...) con
`database._valores_sql` (revisión del 2026-10-17): una base NUEVA nunca queda
desfasada. Pero SQLite no deja cambiar un CHECK ya grabado: si se agrega un
valor, las bases que ya existen necesitan una migración que reconstruya la
tabla. Para `comandos_pc.tipo`, `movimientos_saldo_miembro.tipo`,
`eventos_admin_pc.tipo` (desde el 2026-10-19, por el aviso `MANTENIMIENTO`) y
`ventas.origen` esa migración ya existe y se dispara sola si falta algún valor
(alcanza con sumarlo a la lista); para los demás, hay que escribirla.

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
> Sin excepciones: "Limpiar base de datos" (borraba la plata y el historial
> de ventas, pedido el 2026-10-17 para la etapa de pruebas) se sacó el
> 2026-10-22 a pedido del dueño ("ya es peligroso": el local trabaja con plata
> real). No vuelvas a sumar un borrado así sin que el dueño lo pida. En
> `data/backups/` pueden quedar copias `antes_de_limpiar_base_*`: no se borran.

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
Ya se hizo con `ventas_window.py` (carrito y diálogo de pago) y con
`turnos.py` (calendario separado de la base), `turnos_faltantes_repo.py`
(turnos vencidos sin cierre), `turnos_ventas_repo.py` (qué se vendió en la
ventana de un turno), `control_cierres_repo.py` (Control de Cierres, con su
pantalla `ui/control_cierres_window.py`), `ui/reportes_resumen_dia.py` (el Resumen
del Día salió de `reportes_window.py`), `actividad_repo.py` (feed de PCs) y
`database.py` (esquema en `database_esquema.py`, migraciones en
`database_migraciones.py`, conexiones/copias/claves en `database.py`) y `main.py`
(la hoja de estilos en `ui/hoja_de_estilos.py`, 2026-10-22) y `ui/main_window.py`
(Configuración ADMIN en `ui/configuracion_admin_window.py` y Administrar Kiosko en
`ui/administrar_kiosko_window.py`, 2026-10-26).
Conservá las funciones públicas al partirlos para no tocar otras pantallas.

**13. Comentar el porqué, no el qué.**
Es la mejor costumbre que tiene este código y hay que sostenerla. Los
comentarios explican decisiones no obvias y trampas (por qué el turno
noche cruza la medianoche, por qué el `.exe` guarda la base al lado del
ejecutable). Un comentario que repite lo que dice la línea de abajo
sobra; uno que explica por qué esa línea es así vale oro.

### Cómo se verifica

**14. Regla de negocio nueva, test nuevo.**
`tests/` cubre turnos, stock, cierres, cajas con número, administrar desde otra PC, PCs, PCSTREAM, Miembros, PlayStation, totales y copias de seguridad.
Todo lo que se calcule con plata, fechas o
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
| `dominio.es_admin(usuario)` | se pregunta si alguien es Administrador |
| `ventas_repo.subtotal_linea(linea)` | se calcula lo que se cobra por un renglón |
| `ventas_repo.total_carrito(lineas)` | se suma el total de una venta en curso |
| `database.conexion_db()` | se abre una transacción contra la base |
| `database.DATA_DIR` / `DB_PATH` | se resuelve dónde viven los datos (código vs `.exe`) |
| `database.hash_clave()` / `verificar_clave()` | se maneja una contraseña |
| `usuarios_repo.tiene_permiso(usuario, clave)` | se decide si alguien puede entrar a algo |
| `usuarios_repo.exigir_admin(usuario_id, para)` · `.usuario_habilitado(usuario_id)` | un repo exige que quien opera siga activo (y sea Admin), releyéndolo de la base: un usuario dado de baja con la sesión abierta no puede seguir. Lo usan, entre otros, la PlayStation 5, ORDENAR Stock y la devolución de una reserva |
| `clientes_repo.es_clave_de_clientes(clave)` | se decide si un pedido de red viene de un Cliente PC (clave fija, comparada por su huella SHA-256; la usa `servidor_red._autorizado`) |
| `fondo_repo.obtener()` · `.version_actual()` · `.guardar_jpeg(datos)` · `.quitar()` | se lee y se cambia el fondo de la pantalla de bloqueo de las PCs: un solo archivo `data/fondo_bloqueo.jpg`, con su versión (la huella del contenido) que viaja en `GET /estado` como `fondo_version`. La pantalla (`pcs_fondo_dialogo.preparar_jpeg`) lo achica con Qt; el repo valida que sea un JPEG y que no pase del tope |
| `filtro_palabras_repo.obtener()` · `.guardar(...)` · `.registrar_bloqueo(...)` | se lee y se cambia el filtro de palabras de las PCs ("protección antiporno", pedido del dueño 2026-10-17: prendido, lista y mensaje, como JSON en `configuracion`; su versión viaja en `GET /estado` como `filtro_version`) y se anota cada página que cerró una PC (`bloqueos_filtro_pc`). Buscar las palabras en los títulos es tarea de cada Cliente PC (`CLIENTE PC/filtro_palabras.py`), no de este repo |
| `actualizacion_cliente_repo.publicar(datos)` · `.version_para_estacion(id)` · `.registrar_reporte(id, parametros)` · `.estado_de_las_pcs()` · `.situacion(pc)` | se carga y FIRMA una versión del Cliente PC (`data/cliente_pc/`), se decide qué versión le toca a cada PC (las que marcó el Admin, `guardar_seleccion`; viaja en `GET /estado` como `cliente_version`), se guarda lo que cuenta cada PC (versión, carpeta, cómo va, qué versión copió) y se decide cómo está cada una para "Actualizar el Cliente PC de las PCs..." (copiando, actualizada con éxito, funcionando, apagada, error...; pedido del dueño 2026-10-18, rehecho el 2026-10-19 con la maqueta "A" que eligió). Las versiones se muestran con su número V1, V1.1... (`numero_de_version_del_exe`, y el `v` que manda cada PC). Desde el 2026-10-22 (pedido del dueño: muchas decían «Actualizada con éxito» y al reiniciarlas seguían igual) también se decide, con `seguir_la_copia`, si una PC que copió la versión se reinició sin ponerla y por qué: el reinicio borró la copia (carpeta sin excluir en Shadow Defender) o la PC no arrancó con Lanzador.exe; se sabe por la hora en que arrancó Windows (`encendida`) y queda en `estaciones.seguimiento_actualizacion`. Y se ve el número del Lanzador.exe de cada PC (`lanzador`, lo manda desde la V1.4) |
| `reinicio_actualizacion_repo.reiniciar_si_corresponde(item)` · `comandos_pc_repo.reiniciando(conexion, ahora)` · `.payload_reinicio_por_actualizacion(version)` | se decide si una PC se reinicia sola para poner el Cliente PC nuevo (pedido del dueño 2026-10-28): en cada GET /estado, si ya copió y comprobó la versión que le toca (exe o .zip, da igual), está libre (`congelado_repo.esta_ocupada`) y no está en mantenimiento, se le manda Reiniciar en esa misma respuesta, UNA sola vez por versión (si el reinicio no la pone, la PC la vuelve a copiar: sin ese tope se reiniciaría para siempre). Con un cliente jugando la pone el reinicio de siempre al terminar. Ese Reiniciar lleva `ACTUALIZAR:<versión>` en el payload (el Cliente PC no lo lee): el mosaico dice REINICIANDO hasta que la PC vuelve con Windows recién arrancado (`encendida`, `comandos_pc_repo._dar_por_reiniciadas`) o `MINUTOS_REINICIANDO`; y si la PC se reinició sola antes de pedirlo, al volver no se le da (se reiniciaría dos veces). Un Reiniciar del botón o del clic derecho no cambia |
| `cortes_pc_repo.leer_pulso(parametros)` · `.causa_del_corte(...)` · `.registrar_si_volvio_de_un_corte(item, pulso)` | se decide POR QUÉ una PC en uso titiló "SIN CLIENTE" y volvió sola (pedido del dueño, 2026-10-19): red, Cliente PC reabierto, PC reiniciada, Cliente PC trabado, mostrador que no anotó, o sin datos (Cliente PC viejo). Se sabe cuando la PC vuelve, con el pulso que manda en cada `GET /estado` (`CLIENTE PC/pulso.py`); se anota en `cortes_pc` y se ve en Actividad reciente, en el panel de la PC y en el cartelito de su monitor (`control_pcs/ui/pcs_cortes.py`) |
| `congelado_repo.pedir(estacion_ids, tipo, clave, discos)` · `.esta_ocupada(item)` · `.interpretar_respuesta(texto)` | se manda congelar, descongelar o ver cómo está Shadow Defender en las PCs (pedido del dueño, 2026-10-18; clic derecho en una PC, solo Admin): con la clave de Shadow Defender, que no se guarda; nunca a una PC con cliente (descongelar no manda nada si se eligió alguna; congelar y ver cómo está la saltean y la ventana lo avisa en su renglón, `.texto_salteada()`). Lo hace cada Cliente PC con CmdTool.exe (`CLIENTE PC/shadow_defender.py`) |
| `programas_pc_repo.pedir_info(id)` · `.leer_info(texto)` · `.cerrar_programa(...)` · `.abrir_programa(...)` · `mantenimiento_pc_repo.ordenar(id, orden, usuario)` · `.minutos_vigentes(estacion, enlazada)` | se ve y se maneja una PC desde el clic derecho, para cualquier operador (pedido del dueño 2026-10-22, maqueta aprobada; ventanas en `control_pcs/ui/pcs_programas_dialogo.py`): "📋 Programas y estado..." (disco, memoria, procesador, prendida hace; programas abiertos con NO RESPONDE para cerrarlos a la fuerza; íconos del escritorio para abrir uno) y "🛠️ Hacer mantenimiento (15 min)" / "Terminar mantenimiento (quedan N min)" (el de la "A", solo con la PC libre; quién lo mandó queda en `mantenimientos_remotos_pc` y Actividad reciente lo muestra si la PC contestó OK). Comandos INFO_PC, CERRAR_PROGRAMA, ABRIR_PROGRAMA y MANTENIMIENTO: los entiende el Cliente PC desde la `dominio.VERSION_CLIENTE_PROGRAMAS` (V1.6; a una PC que avisó una más vieja no se le manda nada) y vencen a los 2 min como Reiniciar. La PC solo cierra algo de su lista de ese momento y solo abre un ícono de su escritorio (`CLIENTE PC/programas_pc.py`). El JSON de INFO_PC es el único texto largo de la cola (`comandos_pc_repo.guardar_texto`, `TOPE_TEXTO_INFO`) y pedir otro vacía los viejos de esa PC. Los minutos de mantenimiento llegan como `mant` en GET /estado (`estaciones.mant_min`) |
| `pcs_libres_repo.esta_prendida_y_libre(item)` · `.prendidas_y_libres(estados)` · `.separar(estados)` · `.reiniciar(estacion_ids)` · `.apagar(estacion_ids)` | se decide qué PCs están prendidas (Cliente PC conectado) y libres (sin cliente): a esas van los botones DESCONGELAR (abre la ventana de Shadow Defender con ellas marcadas; el Administrador ve ahí ACTUALIZAR CLIENTES, que solo abre la ventana de Actualizar el Cliente PC: el dueño descongela todas, actualiza y vuelve a congelar, porque la exclusión de carpeta de Shadow Defender no siempre anda, 2026-10-28), REINICIAR y APAGAR (abren `control_pcs/ui/pcs_reiniciar_dialogo.py`, `DialogoReiniciar` / `DialogoApagar`: solo se marcan ellas y arrancan todas marcadas; desde el 2026-10-28, con la maqueta "B" que eligió el dueño, son fichas como las del mosaico y las que están en uso se ven aparte con lo que les queda, sin poder marcarse, debajo del aviso "Solo se apagan las PCs PRENDIDAS y LIBRES" que pidió; `separar` las reparte en libres, en uso y apagadas) de debajo del mosaico, afuera del fondo negro (`control_pcs/ui/pcs_botones_libres.py`, pedido del dueño 2026-10-22, APAGAR 2026-10-23: en las ventanas se desmarcan las que no se quieren tocar). Son para cualquier operador (el mantenimiento lo suelen hacer ellos); "Congelar / descongelar..." del clic derecho sigue siendo solo del Admin. `reiniciar`/`apagar` vuelven a mirar antes de mandar: una PC donde se sentó un cliente después de la pregunta no se toca. El copo de nieve de DESCONGELAR y el símbolo de APAGAR se dibujan con QPainter (`control_pcs/ui/pcs_dibujos.py`: `icono_copo_de_nieve`, `icono_apagar`, `icono_reiniciar`; el copo también va en la ventana de Congelar / descongelar): los emojis 🧊 y ⏻ salen como rectángulo en el Windows del mostrador |
| `control_pcs/ui/pcs_cometa.CometaEnElBorde` | el cometa celeste que da vueltas por el borde del fondo negro del mosaico (pedido del dueño 2026-10-23; solo adorno). Widget transparente encima de `#marcoMosaico` que deja pasar los clics; cada cuadro (unos 30 por segundo) repinta solo la zona del cometa, no hace nada si la pantalla no se ve y se frena en `PanelControlPcs.detener_actualizacion`. La cola son capas continuas encimadas: en tramos sueltos se notaban los cortes |
| `admin_remoto_repo.esta_activo()` · `.activar(...)` · `.entrar(nombre, clave, ip)` · `.exigir_admin_habilitado(id)` | se decide quién administra desde otra PC del local: viene apagado, solo un ADMIN activo, cada ingreso en `sesiones.desde_ip` (pedido del dueño, 2026-10-18) |
| `admin_remoto.lista_blanca.FUNCIONES` · `.ACTOR` · `.huella()` | qué funciones de los repos se pueden pedir desde otra PC, qué parámetro es "quién lo hizo" (lo completa el mostrador) y la huella que tienen que compartir las dos copias del .exe |
| `admin_remoto.modo.direccion_del_mostrador()` · `.es_copia_remota()` | se decide si esta copia es la del mostrador o una abierta por la red (y a qué PC le habla), y las pantallas esconden lo que solo se hace en el mostrador |
| `ui.utils.solo_en_el_mostrador` · `.avisar_que_es_en_el_mostrador(padre)` | se decide qué hace desde otra PC un botón de la pantalla principal que vende, cobra o atiende una PC: está igual que en el mostrador y avisa "Esto se hace en el mostrador" (pedido del dueño, 2026-10-24). En el mostrador no cambia nada |
| `config_repo.obtener_fondo_cambio()` | se lee el fondo de cambio del turno |
| `pcs_repo.estado_estaciones()` | se calcula el tiempo restante y estado de cada PC |
| `pcs_repo.estado_de_estacion(nombre, ip)` | se decide qué estación es una PC que se conecta: por el nombre que manda su Cliente PC y, si ninguna activa se llama así, por la IP asentada en su primer enlace (`registrar_conexion`); con una IP asentada en dos estaciones activas no adivina. La usan TODOS los endpoints de `servidor_red.py` |
| `pcs_repo._orden_natural(estacion)` | se ordenan las estaciones como lo haría una persona ("PC2" antes que "PC10"), con PCSTREAM antes que todas (en el mosaico queda al lado de la PlayStation 5); lo usan `listar_estaciones` y `estado_estaciones` |
| `dominio.es_pcstream(nombre)` | se decide si una estación es PCSTREAM, la PC de streaming (solo por el nombre, sin espacios/guiones/mayúsculas; pedido del dueño, 2026-10-17). `estado_estaciones` lo trae en `item["es_pcstream"]` para la pantalla |
| `socios_bonos_repo.comparar(desde, hasta, agrupar_por)` | se separa lo que dejaron las PCs en cargas de saldo a socios y bonos del mostrador, y se los compara (Reportes > "PCs: Socios y Bonos", pedido del dueño 2026-10-24, `ui/reportes_socios_bonos.py`): plata, cuántos, tiempo vendido, qué parte del total y cuánto deja cada hora. Bonos = walk-ins, PCSTREAM y reservas de PCs; su plata sale por resta (Alquiler de PCs − cargas), así las dos partes suman justo "Alquiler de PCs" de Caja y Totales. Agrupa con `reportes_repo._COLUMNA_AGRUPACION` (rango, día, semana, turno). Está en `admin_remoto/lista_blanca.py` (Reportes se abre desde otra PC) |
| `pcstream_repo.uso_por_dia(desde, hasta)` | se calcula cuánto se usó PCSTREAM, en tiempo (vendido y de uso real) y en plata (Reportes > PCSTREAM) |
| `reintegros_repo.reintegros_por_miembro(...)` | se decide cuánto se le devuelve a cada socio al cortar una sesión de PC (lo usa `pcs_repo.finalizar_sesion`) |
| `reconexion_repo.leer_tiempo_de_la_pc(parametros)` · `.tomar_el_menor(estacion_id, tiempo_pc)` | se decide qué tiempo vale cuando una PC vuelve de un corte (pedido del dueño, 2026-10-20): gana el MENOR entre lo que cuenta la PC y lo del mostrador, contando lo que se cargó durante el corte, y el mostrador lo guarda (`ajustes_reconexion_pc`, "Actividad reciente"). Nunca sube el tiempo. Lo llama `servidor_red` en `GET /estado` antes de armar la respuesta; del lado de la PC es `CLIENTE PC/reconexion.py`. Explicación para el dueño: `docs/TIEMPO_DE_LAS_PCS.md` |
| `avisos_fin_pc_repo.fin_sin_aviso(...)` · `.marcar_enterada(...)` · `.marcar_revisada(...)` | se decide si una PC se enteró de que terminó su sesión (pedido del dueño, 2026-10-21: en la PC 30 se terminó el tiempo con el Cliente PC cerrado y siguieron jugando). Toda sesión que se cierra queda `AVISO_FIN_PENDIENTE` (`pcs_repo._cerrar_sesion`) hasta que la PC vuelve a preguntar (`pcs_repo.registrar_conexion`); sin noticias pasado `UMBRAL_ENLACE_SEGUNDOS`, el monitor titila "TIEMPO AGOTADO" como la PlayStation 5 hasta que la PC vuelve (el corte se anota con su causa, `cortes_pc_repo`) o el operador aprieta "Ya revisé la PC" (queda quién y cuándo, y se ve en Actividad reciente). Las sesiones de antes quedan en NULL y no titilan |
| `pcs_repo._cerrar_sesion(conexion, sesion, ahora)` | se cierra una sesión de PC dentro de una transacción (reintegro del socio incluido; la hora de fin real nunca pasa de la prevista). La usan `finalizar_sesion` y `_abrir_o_extender_sesion`, que cierra una sesión que ya llegó a cero en vez de estirarla |
| `pcs_window.PanelControlPcs._ficha_de_pc(...)` · `._ficha_de_playstation(...)` | se decide con qué color, dibujito y aviso se ve cada equipo en el mosaico; `control_pcs/ui/pcs_mosaico.py` solo dibuja la `Ficha` que recibe |
| `pcs_repo.asignar_bono(...)` | se crea o extiende una sesión de PC con un bono del mostrador: el COMÚN (walk-in) o, si la PC es PCSTREAM, uno de SU catálogo (`pcstream_repo`) |
| `dominio.segundos_restantes(fin, ahora)` · `dominio.fin_al_sumar_minutos(fin_actual, minutos, ahora)` | se calcula cuánto le queda a una sesión de tiempo y cuándo vence al sumarle un bono (PCs Y PlayStation 5: una sola cuenta) |
| `playstation_repo.estado()` · `.vender_bono(...)` · `.finalizar_sesion(...)` | se sabe cómo está la PlayStation 5, se le vende un bono (origen PLAYSTATION) y se la libera; ahí mismo se exige ser Admin para el catálogo (vender y liberar, cualquier operador) |
| `turnos_repo._desglose_de_totales(...)` · `_PREFIJO_COLUMNAS_POR_ORIGEN` | se reparte lo cobrado de un turno por origen (kiosko/pcs/playstation × efectivo/digital) y se suma el efectivo del cajón sobre TODOS los `ORIGENES_VENTA` (el diccionario vive en `turnos_ventas_repo` desde el 2026-10-20 y `turnos_repo` lo importa con el mismo nombre) |
| `bonos_miembro_repo.listar_bonos()` / `.obtener_bono(id)` | catálogo de bonos EXCLUSIVO de socios (no confundir con `pcs_repo`) |
| `miembros_repo.abrir_estacion_por_miembro(...)` | un socio abre una PC con su propio saldo (y, con `pedir_datos`, completa sus datos del primer ingreso) |
| `miembros_repo._sumar_carga_a_la_sesion(...)` | se decide qué pasa con lo que se le carga a un socio que está usando una PC: pasa a esa sesión, con un CONSUMO como al entrar (hasta la hora de una reserva, si la hay; lo demás queda en el saldo). Pedido del dueño 2026-10-22: la sesión se lleva el saldo al entrar, y una carga quedaba en el saldo mientras la PC contaba hasta cero. `cargar_saldo_por_monto/_por_bono` devuelven `{"venta_id", "sumado_a_la_sesion"}` y Cargar Saldo lo avisa. Ojo: anular esa carga no le saca el tiempo a la PC (`anular_carga` solo revierte lo que hay en el saldo, igual que si el socio ya hubiera entrado) |
| `historial_cargas_repo.listar_cargas(desde, hasta, buscar, miembro_id)` · `.totales(cargas)` | se arma el Historial de Cargas de saldo de los socios (pedido del dueño 2026-10-24; botón "Historial de Cargas" de Miembros, al lado de Cargar Saldo, para cualquier operador; pantalla `control_pcs/ui/miembros_historial_cargas.py`): solo los movimientos CARGA (no consumos, reintegros ni IMPORTACION; sí las que pasaron directo a la PC del socio), con el socio, minutos, plata, medio de pago, bono o monto libre, el operador que apretó el botón (`ventas_caja.cargada_por` si cobró el Admin con la caja de una empleada) y fecha y hora. Días del local de 06:00 a 06:00. Las anuladas salen en rojo con quién y por qué, y no suman en los totales. Con un socio marcado en Miembros abre filtrado por su id (buscar el texto "ana" trae también a "mariana") |
| `ultima_visita_repo.ultimas_visitas()` · `.dias_sin_venir(visita)` · `.no_viene_hace_mas_de(dias, limite)` | se decide hace cuántos días no viene un socio (columna "No viene hace" de Miembros, pedido del dueño 2026-10-24, para saber a quién escribirle): lo último entre su última sesión de PC con su usuario (cuando se fue, o ahora si sigue jugando) y su última carga sin anular, en días del local. No hay registro aparte de visitas: un socio que paga un bono en el mostrador sin entrar con su usuario no cuenta. En naranja pasados `dominio.DIAS_SIN_VENIR_AVISO` (15), filtro "No vienen hace más de N días" (entran también los que nunca vinieron) y orden con un clic en el título (`MiembrosWindow._ordenar_por_columna`; la flecha va en el texto del título porque el indicador de Qt ordenaría solo). Índice `idx_sesiones_pc_miembro` |
| `miembros_repo.normalizar_dni(...)` · `.tiene_dni(miembro)` · `.normalizar_telefono(...)` | se valida y se guarda el DNI (solo números, 7 u 8 cifras), el celular y el WhatsApp de un socio, y se decide si a un socio le falta el DNI (el Cliente PC se lo pide; Miembros lo marca "Falta DNI") |
| `dominio.carga_minima_de_saldo(tramos)` · `miembros_repo.validar_monto_de_carga(...)` | se decide cuánto es lo mínimo que un socio puede cargar con un monto libre (el monto del tramo más bajo de la Tarifa por Hora para Socios; pedido del dueño, 2026-10-17) y se rechaza una carga menor: la pantalla la valida antes de abrir la ventana de cobro, el repo de nuevo al cobrar |
| `cuentas_pc_repo.anotar_articulos(...)` · `.anotar_bono(...)` · `.anotar_tiempo_socio(...)` · `.cobrar(cuenta_ids, usuario_id, pagos)` · `.quitar_renglon(...)` · `.dar_por_perdida(...)` · `.obtener_reglas()` · `.guardar_reglas(...)` · `.aviso_antes_del_cierre()` · `.fiado_del_turno_en_curso()` · `deudas_pc_repo.por_estacion(conexion)` · `.fiado_del_turno(...)` · `.anotar_fiado_en_el_cierre(...)` | se maneja la Cuenta de la PC (pedido del dueño 2026-10-25: el cliente que juega pide un pancho o más tiempo y paga después): se anota en la cuenta de SU SESIÓN (`cuentas_pc`, una por sesión: si se cambia de PC va con él; si se va debiendo, la PC sigue debiendo y el próximo cliente tiene la suya), el artículo baja el stock al anotarse y el bono suma el tiempo ya (solo a una sesión en curso); la PC titila con borde fucsia y "DEBE $ X" (`item["deuda"]` de `pcs_repo.estado_estaciones`, `pcs_mosaico.COLOR_DEBE`) hasta que se cobra con la ventana de cobro de siempre: una venta de kiosko SIN volver a bajar el stock (`ventas_repo._grabar_venta_kiosko(..., descontar_stock=False)`) y una de Alquiler de PCs por bono con su `sesion_bonos`/`sesion_pcstream_bonos`, con los pagos repartidos por `dominio.repartir_pagos`. Anotar y cobrar: cualquier operador, en el mostrador (VENDER "A cuenta de una PC...", el panel de la PC, `control_pcs/ui/cuenta_pc_dialogos.py`); quitar un renglón y dar por perdida: solo Admin, con motivo. El tope (arranca en $10.000), qué pasa al pasarlo (no deja, o con la clave de un Admin) y si se anota tiempo los fija el Admin en Configuración ADMIN > Reglas de Cuenta de PC (`control_pcs/ui/cuenta_pc_reglas_dialogo.py`). Movimientos muestra lo anotado sin cobrar o perdido. A un socio se le anota tiempo de socio (bono de socio o monto con su tarifa, `DialogoTiempoSocio`): se suma a su sesión SIN tocar su saldo y, mientras no lo paga, cuenta como bono para los reintegros; al cobrarlo queda como una carga suya que pasó a la sesión (CARGA con la venta + CONSUMO, los dos con la hora en que se anotó). Lo fiado en un turno se cobra en ese turno (pedido del dueño, mismo día): desde `dominio.MINUTOS_AVISO_CUENTAS_ANTES_DEL_FIN` (15) antes del fin del turno las PCs que lo deben titilan más rápido (`PanelControlPcs.marcar_cuentas_urgentes`) y sale `DialogoCobrarAntesDelCierre` con un "Cobrar" por PC y "Posponer 5 min" (`MainWindow._revisar_cuentas_antes_del_cierre`; no hay "Ya lo cobré" a propósito: apagarlo a mano dejaría plata fuera de la caja); al apretar Cierre de Turno pregunta otra vez, y si se cierra igual (o es el cierre forzoso) `turnos_repo.cerrar_turno` deja en `cierres_fiado_pc` lo anotado en ese turno sin cobrar, a nombre de quien cerró, y Control de Cierres lo muestra ("Fiado sin cobrar al cerrar"). No cambia lo que hay que retirar |
| `dominio.cuenta_del_cobro(total, efectivo, digital, paga_con)` · `.lo_que_falta_para(total, monto)` | se calcula el cobro: la parte en efectivo y la digital, el billete que da el cliente, el vuelto, lo que falta y los pagos que quedan en la caja (netos de vuelto); y lo que completa el otro medio al escribir en uno |
| `ui.dialogo_pago.cobrar(parent, monto)` | se cobra todo lo que no es una venta de kiosko con la ventana de cobro de Ventas (medio de pago, reparto y vuelto): el bono de PC, PCSTREAM o PlayStation 5 del botón "Cobrar" de Control de PCs, la carga de saldo de un socio y un trámite. Devuelve los pagos netos de vuelto, o None si se canceló |
| `ventas_repo.registrar_venta_sin_detalle(...)` | se arma una venta sin artículo real de por medio (bono de PC, carga de saldo) |
| `dominio.CODIGO_ARTICULO_IMPRESIONES` | se decide qué artículo de kiosko es "Impresiones" (el código "4" en la base del dueño; hasta el 2026-10-19 el programa buscaba el "1", el de la base anterior, y las impresiones salían en $0), para mostrarlo como renglón propio en Reportes, Caja y Cierre de Turno |
| `impresiones_repo.cobrar_impresiones(...)` · `.articulo_impresiones()` | se cobran impresiones desde el botón de la barra (pedido del dueño, 2026-10-19): venta de kiosko común del artículo, con el precio leído en la misma transacción (`ventas_repo._grabar_venta_kiosko`, el núcleo de `confirmar_venta`) |
| `turnos_ventas_repo._vendido_aparte_entre(...)` (lo usa `turnos_repo`) | se calcula cuánto del Kiosko de un turno fue impresiones y trámites, para mostrarlos en columna propia en el Resumen del Día |
| `turnos_ventas_repo._aparte_por_metodo(...)` · `turnos_ventas_repo._separar_de_kiosko(...)` | se reparte lo de impresiones y trámites del turno en curso (o de un cierre ya hecho, con `cierre_grabado=True`) entre efectivo y digital (venta por venta, con sus pagos) y se arma Kiosko sin ellos para Caja, Cierre de Turno y el detalle de Control de Cierres (`resumen_turno_actual()["kiosko_solo_*"]`, `["impresiones_*"]`, `["tramites_*"]`). `turnos_repo` la importa con el mismo nombre |
| `tramites_repo.registrar_tramite(...)` | se cobra un trámite de mostrador (monto libre): venta KIOSKO sin detalle + vínculo en `tramites_venta` |
| `reservas_repo.crear_reserva(...)` · `reservas_habilitar_repo.habilitar(...)` · `reservas_repo.marcar_no_vino` · `.reprogramar` · `.devolver` | se toma una reserva cobrando la seña o todo, se la habilita (cobrando solo lo que falta), se la da por no venida, se la reprograma y se devuelve su plata (solo Admin). Pedido del dueño 2026-10-20; ver "Trampas conocidas". Las dos pantallas preguntan antes de cobrar (`revisar_reserva`, `preparar_habilitacion`) para no cobrar algo que después no se puede grabar |
| `reservas_repo._pasar_las_vencidas(conexion, ahora)` | se decide cuándo una reserva pasa sola a No vino / A reprogramar (su hora + `MINUTOS_TOLERANCIA_RESERVA`) y a Vencida (`DIAS_PARA_REPROGRAMAR_RESERVA`). No hay reloj: corre al listar (`listar_reservas`, `actualizar_estados`) |
| `turnos_ventas_repo._resumen_de_reservas(...)` | se separa lo cobrado por reservas de Alquiler de PCs y PlayStation 5 para el renglón "Reservas" de Caja, Cierre de Turno y el detalle de un cierre (`resumen["pcs_solo_*"]`, `["playstation_solo_*"]`, `["reservas_*"]`, `["reservas_por_tipo"]`, `["reservas_sin_cobro"]`) |
| `reservas_socios_repo.crear_reserva_de_socio(...)` · `.horas_para_reservar()` · `.guardar_horas_para_reservar(...)` · `.marcar_llegada(...)` | se toma la reserva de un socio (pedido del dueño 2026-10-26, botón "RESERVA DE SOCIO" de Reservas, `control_pcs/ui/reservas_socio_dialogo.py`): sin seña ni venta, solo con `horas_para_reservar()` de saldo o más (arranca en `dominio.HORAS_SALDO_PARA_RESERVAR`, 5; lo cambia solo el Admin en Miembros > "$ Para Reserva") y nunca más horas que su saldo; solo PCs comunes. Al que no llega se le carga saldo desde ahí ("CARGAR SALDO", `DialogoCargarSaldo(..., a_la_sesion=False)` → `cargar_saldo_por_*(..., a_la_sesion=False)`): esa carga queda en el saldo aunque esté usando una PC, no pasa a su sesión. Se guarda con `miembro_id`, `bono_id` 0 y precio 0. Al entrar con su saldo (`abrir_estacion_por_miembro` o una carga que pasa a su sesión) `marcar_llegada` la deja Habilitada si la sesión llega a su hora; su propia reserva no lo corta (`minutos_para_el_socio(..., miembro_id)`). No se habilita desde el mostrador (`reservas_habilitar_repo` lo rechaza) y si no viene queda No vino (`_estado_si_no_viene`: con precio 0 parecería "pagó todo") |
| `dominio.nombre_equipo_reservado(equipo, nombre_pc)` | se nombra el equipo de una reserva (la PC, "Cualquier PC disponible", PCSTREAM o la PlayStation 5) |
| `reservas_horario_repo.pendientes(conexion, ahora)` · `.proxima(reservas, estacion)` | se decide qué reserva aparta qué equipo y desde cuándo se ve RESERVADO (`MINUTOS_EQUIPO_RESERVADO_ANTES`, 2 h, hasta la hora + la tolerancia). Lo usan `pcs_repo.estado_estaciones` y `playstation_repo.estado` (`item["reserva"]`), y de ahí el mosaico (`pcs_window._ficha_de_pc`, celeste `COLOR_RESERVADA`), el panel y `lugares_para_habilitar` |
| `reservas_horario_repo.aviso_al_vender(estacion_id, minutos)` · `.minutos_para_el_socio(...)` · `.cartel_para_la_pc(estacion)` · `.sin_pc_fija(...)` · `.pcs_libres(...)` | se avisa antes de cobrar un bono que deja el equipo ocupado a la hora de su reserva (no frena), se decide cuánto saldo usa un socio en una PC reservada (hasta la hora; lo demás le queda), qué cartel viaja a la pantalla de bloqueo (`reserva` en GET /estado) y qué va en el aviso de "Cualquier PC disponible" de arriba del mosaico (`control_pcs/ui/pcs_aviso_reservas.py`) |
| `main.aplicar_estilo(app)` | se fija el aspecto de TODO el programa: estilo Fusion, esquema de color CLARO y la hoja de estilos (`HOJA_DE_ESTILOS`, en `ui/hoja_de_estilos.py`) |
| `dominio.texto_pesos(monto)` · `ui.utils.formato_pesos(monto)` | un monto se convierte en texto: `"$ 1.500"`, `"$ 30.000"`, con el punto de los miles y SIN centavos (pedido del dueño 2026-10-26: todos los precios son en miles y `"$ 1.500,00"` o `"1500,00"` se leían mal); con centavos solo si los tiene de verdad (`"$ 1.234,50"`, un reparto en proporción), para que una suma de la caja no parezca no cerrar. Los repos lo usan en sus mensajes; la pantalla, con `formato_pesos` |
| `ui.utils.CampoPesos` · `ui.utils.pedir_pesos(parent, titulo, texto, valor)` | se escribe un monto: el campo se ve `"$ 1.500"` igual que `formato_pesos`, acepta escribirlo con o sin el punto (la coma es de los centavos) y `pedir_pesos` es el `getDouble` con ese campo. Ninguna pantalla arma un `QDoubleSpinBox()` ni un `getDouble` suelto para plata (`tests/test_formato_pesos.py` lo vigila). Excel muestra los montos con `"$" #,##0` (el número de la celda sigue exacto) |
| `ui.utils.formato_fecha_hora(fecha)` | una fecha con hora de la base se convierte en `"16/10/2026 22:13"` |
| `reportes_repo.resumen_por_operador(...)` · `.ventas_de_operador(...)` | se calcula cuánto vendió cada usuario y se listan sus ventas con fecha y hora (Reportes > Por Operador) |
| `turnos_repo._ventanas_del_dia(conexion, dia, ahora)` | se decide qué ventas son de qué turno de un día (los cierres anotados ese día y la ventana abierta si es de ese día): la usan las filas del Resumen del Día y su detalle |
| `detalle_dia_repo.detalle_del_dia(dia)` | se arma el detalle venta por venta de un día (hora, turno, operador, rubro y qué se vendió de kiosko, trámites, PCs con la PC al momento de vender, PCSTREAM, PlayStation 5 y socios), con los renglones de cada venta tal cual se cobraron (`lineas`, con el código), lo vendido por producto y por operador (Reportes > Resumen del Día, pedido del dueño 2026-10-18) |
| `ui.excel.guardar_xlsx(ruta, hoja, columnas, filas, totales)` · `.bajar_a_excel(parent, ...)` | se baja un listado a Excel (pedido del dueño 2026-10-24: Historial de Cargas y Reportes > PCs: Socios y Bonos, botón "📊 Bajar a Excel"). Un .xlsx de verdad escrito a mano con zipfile, SIN librerías aparte (no hay openpyxl en el .exe): fechas, tiempos ([h]:mm), pesos y porcentajes como números que Excel suma, títulos en negrita y fijos, filtros, fila TOTAL en negrita. Probado abriéndolo con Excel 16. `bajar_a_excel` pregunta dónde (arranca en el Escritorio), avisa si el archivo está abierto en Excel y ofrece abrirlo. Cada pantalla arma sus `datos_para_excel()` |
| `ui.imprimir.html_del_listado(...)` · `.vista_previa(parent, html, nombre)` | se imprime un listado: HTML en hojas A4 con los títulos de las columnas repetidos en cada hoja y vista previa (desde ahí se imprime o se guarda en PDF). Lo usa el "Renglón por renglón" del Detalle del Día |
| `copias_repo.copia_automatica_si_corresponde()` · `.toca_copia(...)` · `.nombres_a_borrar(...)` · `.agregar_carpeta_extra(...)` | se decide cuándo se hace una copia de seguridad (después de cada Cierre de Turno y cada `HORAS_ENTRE_COPIAS`, con el programa abierto; lo corre el hilo de `iniciar_copias_automaticas`), cuántas quedan y en qué otras carpetas se guarda (otro disco, carpeta compartida de otra PC); pedido del dueño, 2026-10-19. La pantalla es `ui/copias_dialogo.py` (Usuarios > "Copias de Seguridad") |
| `envio_pwa_repo.encolar(conexion, cierre_id)` · `.enviar_pendientes(ahora, transporte)` · `.datos_del_cierre(conexion, cierre_id)` · `.mandar_cierre(usuario_id, cierre_id)` · `.activar(usuario_id, prendido)` · `.probar_conexion()` · `.estado()` · `turnos.turno_para_la_app_de_gastos(fecha, turno)` | se manda cada Cierre de Turno a la app de gastos del dueño (la PWA "Gastos — CyberBIOS"; pedido del dueño 2026-10-26): la cola `envios_pwa` se llena en la transacción de `turnos_repo.cerrar_turno` solo con el envío prendido (Configuración ADMIN > "Cierres a la app de gastos", `ui/envio_pwa_dialogo.py`, solo Admin y solo en el mostrador; viene apagado), un hilo la manda cada minuto con reintentos, y lo que viaja es lo que carga una empleada a mano (total, efectivo, digital, el turno con el nombre de allá, el día en que arrancó el turno y el NOMBRE de la responsable de la caja) más el desglose de la tarjeta del cierre (`detalle`, con `dominio.NEGOCIOS_DEL_CIERRE`: la misma lista de negocios que `ui/tarjeta_cierre.py`, para que la app muestre el cierre tal cual el programa). Se habla con Firestore como un celular: login anónimo con la clave pública de la PWA y REST con `urllib` |
| `vuelta_admin_repo.volver(usuario_id)` · `ui.vuelta_del_admin.VueltaDelAdmin` | se decide si la sesión del Administrador vuelve sola a la empleada (pedido del dueño 2026-10-26: entra para algo rápido y se olvidaba de volver a cambiar de usuario). A los `dominio.MINUTOS_ADMIN_VUELVE_SOLO` de entrar, en silencio (sin cartel ni aviso: el dueño pidió sacar el de la primera versión; no lo vuelvas a poner), vuelve a quien dejó el mostrador con "🔄 Operador" (`MainWindow.a_quien_volveria`, lo pasa `main.Aplicacion`) sin pedirle la clave, solo si su caja sigue abierta a su nombre y en hora (situación SU_CAJA); si no, a la pantalla de ingreso. Nunca corta un cobro ni un formulario abierto (espera, como el cierre forzoso). Solo en el mostrador |
| `errores.registrar_error(excepcion, contexto)` | la UI y el servidor guardan fallos inesperados en `data/errores.log` sin depender de Qt |
| `ui.utils.manejar_errores` | se atrapa un error de una acción de pantalla |
| `ui.utils.encadenar_enter(...)` | se arma el salto de campo en campo con Enter, como Tab, y la acción del último campo (pedido del dueño, 2026-10-18: todo formulario lo usa). Descarta el Enter repetido de una tecla que quedó apretada. Ojo: en un QSpinBox/QDoubleSpinBox/QDateEdit/QComboBox editable el Enter del teclado le llega al campo de AFUERA, no a su `lineEdit()`; una prueba que le manda el Enter al `lineEdit()` pasa aunque en el mostrador no ande (pasó hasta el 2026-10-18: ningún importe respondía al Enter). Ver `TestDondeLlegaElEnter` |
| `ui.utils.aplicar_clase(widget, clase)` | un botón se marca como primario/peligro |
| `ui.piezas_ventana.cabecera_oscura(...)` · `.agregar_pastilla(...)` · `.panel_blanco()` · `.titulo_de_seccion(...)` · `.tarjeta_de_menu(...)` · `.bloquear_tarjeta(...)` · `.tecla(...)` | se arma una ventana con el diseño "clara con cabecera cyber" que eligió el dueño el 2026-10-26 (maqueta A de `PROPUESTA_VENTANAS_ADMIN`; hoy Configuración ADMIN, Administrar Kiosko, Gestionar Estaciones, Reservas, Caja, Cierre de Turno, Congelar / descongelar PCs y Reiniciar / Apagar PCs; `.cifra_destacada(...)` es el monto grande verde o azul de Caja y Cierre de Turno): cabecera oscura como la barra, con la estela celeste del cometa y pastillas con números; paneles blancos; tarjetas de menú (dibujito, título y para qué es; la que solo usa el Admin, con candado y "Solo el Administrador"; con `tono=TONO_ROJO` lo peligroso, con `TONO_VERDE` en verdecito); teclas con relieve (`teclaAzul` lo principal, `teclaRoja` lo peligroso y Cerrar, aparte). Los colores van en `ui/hoja_de_estilos.py`, siempre por objectName o "clase" (y `>` para las etiquetas de un panel): los avisos que se abren encima son hijos de la ventana y no heredan nada (`test_estilo_ui`). El texto de una tarjeta lo dibujan etiquetas de adentro: su título está en `accessibleName()`, y por ahí la buscan las pruebas |
| `ui.utils.sin_boton_por_defecto(ventana)` | se evita que Enter en un campo active el primer botón de un diálogo (llamarla al final de `_armar_interfaz`) |
| `ui.utils.crear_tabla(titulos, ...)` | se arma una tabla de solo lectura (filas alternadas, columna que se estira, selección por filas) |
| `ui.utils.mostrar_columna_entera(tabla, columna)` | se ensancha una columna para que su texto no se corte con "..." (la de códigos de barras, en las tablas que la muestran en una columna: llamarla después de llenar la tabla; en el carrito de Ventas el código va chiquito debajo del producto, `ui.ventas_dibujos.DelegadoProducto`). Con 100 px un EAN-13 se veía "77981133010…" y parecía guardado con dos dígitos menos (2026-10-18) |
| `articulos_repo.ajustar_stock(usuario_id, codigo, stock_nuevo, clave)` · `.comprobar_clave_para_ordenar_stock(...)` | se corrige el stock de un artículo a mano (ORDENAR Stock, pedido del dueño 2026-10-20): solo Admin activo con la contraseña de `CLAVE_ORDENAR_STOCK`, entero de 0 para arriba, anotado en `ajustes_stock` y visible en Movimientos. Es la única forma de mover el stock aparte de Compras y Ventas |
| `articulos_repo.cambiar_codigo(usuario_id, codigo_actual, codigo_nuevo, clave)` · `._TABLAS_CON_CODIGO_DE_ARTICULO` | se corrige el código de un artículo (ORDENAR Stock, doble clic en el código; pedido del dueño 2026-10-20): mismo permiso y contraseña que el stock; las ventas, compras y ajustes de antes pasan al código nuevo en la misma transacción, anotado en `cambios_codigo` y en Movimientos ("cambio de código A → B"). Es el único lugar donde se cambia un código (ver "Trampas conocidas") |
| `articulos_repo.crear_marca` · `.renombrar_marca` · `.juntar_marcas` · `.borrar_marca` (usuario_id primero) | se corrige el catálogo de marcas: SOLO el Admin (pedido del dueño 2026-10-23; `exigir_admin(..., "editar las marcas")`, y el botón "Gestionar Marcas" de Artículos solo lo ve el Admin, `ui/articulos_window.DialogoGestionMarcas`). Renombrar con el nombre de otra marca pregunta si juntarlas (pasa los artículos y borra la vieja); borrar una con artículos se rechaza. Una marca nueva al cargar un artículo (`_marca_para_guardar`) sigue libre para quien entra a Artículos |
| `articulos_repo.listar_para_control_de_stock(usuario_id)` | se arma la lista de CONTROL DE STOCK (pedido del dueño 2026-10-24; botón de debajo del mosaico, a la derecha de APAGAR, `ui/control_stock_window.py`): los artículos con stock de 1 para arriba, de la A a la Z, para imprimirla y contar el estante (la hoja trae una columna "Contado" vacía). El botón lo ven todos y solo el Admin lo abre (con otro operador no hace nada, como Admin Kiosko); el repo vuelve a exigir Admin. Solo muestra: corregir es de ORDENAR Stock |
| `dominio.sin_acentos(texto)` | se compara u ordena un texto sin mayúsculas ni acentos, como lo haría una persona (la búsqueda de Reservas, el orden de CONTROL DE STOCK): en el orden de la computadora "Álamo" queda después de la "z" |
| `dominio.orden_de_codigo(codigo)` | se ordenan códigos de artículo de menor a mayor como números (1, 2, 10 y no 1, 10, 2; los que tienen letras al final): F5 Código, pedido del dueño 2026-10-25 |
| `ui.articulos_tabla.llenar_tabla_de_articulos(...)` · `.poner_stock(...)` | se arma la grilla de artículos (columnas y stock en rojo bajo el mínimo): la usan Artículos y ORDENAR Stock |
| `ui.buscar_articulo.avisar_codigo_no_encontrado(ventana, codigo)` | se avisa en Ventas y Compras que lo escaneado no es ningún artículo, con cuántos dígitos llegaron (para comparar con el código cargado) |
| `ui.utils.crear_selector_de_fecha(...)` | se crea un campo de fecha con calendario (sin sábado/domingo en rojo; usarlo siempre, nunca un `QDateEdit` a mano) |
| `ui.utils.armar_filtro_por_fechas(...)` · `rango_de_fechas(...)` · `fecha_iso(...)` | se arma la fila Desde/Hasta con "Buscar" y se leen sus fechas como `"YYYY-MM-DD"` (el formato con que hablan los repos) |
| `ui.utils.fila_guardar_cancelar(dialogo, ...)` | se arma la fila Guardar/Cancelar de un formulario |
| `ui.utils.fila_agregar_quitar(tabla, ...)` | se arman los botones Agregar/Quitar de una tabla que se edita a mano |
| `ui.buscar_articulo.armar_botones_de_busqueda(ventana, ...)` | se arman los botones F5/F6/F7 y sus atajos (Ventas y Compras) |
| `ui.detalle_venta.VentanaConDetalleDeVenta` | lista de ventas + artículos de la elegida (Consulta de Ventas y Detalle de un cierre) |
| `ui.tarjeta_cierre.TarjetaCierreDeTurno` · `.TablaDeNegocios` | se dibuja el resumen de un Cierre de Turno (A RETIRAR y TOTAL en grande; en la tabla, cada negocio con su efectivo y digital en columnas, lo cobrado y el Cambio Fijo; diseño del 2026-10-26, con la cabecera de `ui.piezas_ventana`). La tabla es también la de Caja: la pantalla Cierre de Turno (turno en curso) y "Ver Detalle" de Control de Cierres (cualquier cierre ya hecho, también el forzoso; pedido del dueño 2026-10-20). Un cambio de diseño del Cierre de Turno se hace ahí y se ve en las dos |
| `control_pcs.repositories.catalogo_bonos.CatalogoDeBonos(tabla)` | se hace el alta/edición/baja de un catálogo de bonos (`pcs_repo` para walk-ins, `bonos_miembro_repo` para socios, `playstation_repo` para la consola, `pcstream_repo` para la PC de streaming: cuatro tablas distintas, un solo código) |
| `database._reconstruir_tabla(...)` · `_admite_todos_los_tipos(lista)` | se reconstruye una tabla para cambiar un CHECK/REFERENCES, y se decide si un CHECK de tipos ya está al día |
| `database._sql_tabla_ventas(...)` · `_migrar_check_origen_en_ventas(...)` | se escribe el CREATE de `ventas` (el CHECK de `origen` sale de `dominio.ORIGENES_VENTA`) y se reconstruye una base vieja SIN romper las tablas que la referencian (ver "Trampas conocidas") |

Si necesitás uno de esos datos, **llamá a la función existente**.

---

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
- **El `.exe` empaquetado resuelve las rutas distinto.** Con PyInstaller
  `__file__` apunta a una carpeta temporal que se borra en cada arranque;
  por eso `BASE_DIR` usa `sys.executable` si está `frozen`. Si guardás un
  archivo nuevo, hacelo bajo `DATA_DIR`, nunca al lado de un `.py`.
- **Un objeto de Qt que se pasa a otro sin que lo adopte tiene que quedar en una
  variable.** `QPrintPreviewDialog(QPrinter(...), parent)` usa la impresora
  pero no la guarda: pasada sin variable, Python la borraba apenas se armaba el
  diálogo, la vista previa leía memoria liberada y el programa se cerraba **sin
  ningún cartel** (ni `manejar_errores` ni `sys.excepthook` lo ven: es una caída
  de Qt, no de Python). Le pasó al dueño en el local con Control de Stock >
  Imprimir (2026-10-26); valía para los tres listados (`ui/imprimir.vista_previa`).
  Ver `test_la_impresora_sigue_viva_mientras_esta_abierta_la_vista_previa`.
  Los QObject con `parent` no tienen este problema (los retiene el padre).
- **El stock puede quedar negativo a propósito.** No agregues una
  validación que lo impida: prefieren vender y corregir después antes que
  frenar la cola en el mostrador.
- **El stock se corrige a mano SOLO con ORDENAR Stock** (botón de Artículos,
  pedido del dueño 2026-10-20: al arrancar en el local hubo demasiados
  desarreglos). Lo ve solo el Admin y pide una contraseña fija que eligió el
  dueño; en el código está solo su hash con salt (`articulos_repo.CLAVE_ORDENAR_STOCK`,
  el repo es público: nunca la escribas en claro, tampoco en un test). El repo
  vuelve a exigir Admin activo y contraseña en cada cambio, y cada cambio queda
  en `ajustes_stock` (antes, después, quién, cuándo) y en Movimientos como
  "ajuste de stock": no lo saques "para simplificar", es lo que deja auditar un
  faltante de mercadería. Solo cambia `articulos.stock`: ni precios, ni costos,
  ni ventas, ni la caja. Ahí sí se rechaza un número negativo (es lo que hay
  contado en el estante); lo de arriba vale para vender. El alta/edición de un
  artículo sigue sin tocar el stock.
- **El código de un artículo se cambia SOLO en ORDENAR Stock** (mismo día: había
  códigos escritos a mano mal en vez de leídos con la pistola). Se abre con doble
  clic en el código (un clic sigue yendo al stock, así no se cambia uno sin
  querer), pregunta antes de guardar y pasa por `articulos_repo.cambiar_codigo`
  (mismo permiso y contraseña que el stock). El código es la clave de `articulos`
  y lo guardan `venta_detalle`, `compra_detalle`, `ajustes_stock` y
  `cambios_codigo`: se corrigen todas en la misma transacción con
  `PRAGMA defer_foreign_keys` (si faltara una, el guardado falla y no queda nada a
  medias). Una tabla nueva que guarde el código de un artículo va en
  `articulos_repo._TABLAS_CON_CODIGO_DE_ARTICULO` (`tests/test_ordenar_stock.py`
  lo vigila). No deja usar el código de otro artículo (no se juntan dos
  artículos) ni tocar el de Impresiones (`dominio.CODIGO_ARTICULO_IMPRESIONES`).
  En Artículos > Modificar el código sigue sin poder cambiarse.
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
- **Toda venta sin artículo real de por medio pasa por
  `ventas_repo.registrar_venta_sin_detalle`, nunca un `INSERT INTO ventas`
  a mano.** Es lo único que le pone el `origen` correcto
  (`dominio.ORIGENES_VENTA`) — sin eso, el desglose Kiosko/Alquiler de
  PCs/PlayStation 5 de Caja y Cierre de Turno queda mal. El dueño pidió este desglose
  explícitamente para poder auditar la caja (sospecha de faltantes), así
  que un error acá no es solo un bug visual.
- **Todo se cobra con la misma ventana de cobro, nunca con un combo "Medio de
  pago"** (pedido del dueño, 2026-10-18: "a todo"). Ventas abre
  `ui.dialogo_pago.DialogoPago`; los bonos de Control de PCs (PC, PCSTREAM,
  PlayStation 5), Cargar Saldo de un socio y Trámites la abren con
  `ui.dialogo_pago.cobrar`. Así las empleadas aprenden un solo cobro y siempre
  ven el vuelto. Una pantalla nueva que cobre tiene que usar `cobrar`. Un pago
  repartido entre los dos medios se graba como dos filas reales de
  `PAGO_EFECTIVO`/`PAGO_DIGITAL`: no existe un método "mixto" (hasta ese día había
  un `PAGO_MIXTO` de pantalla). No lo sumes a `METODOS_PAGO` ni al `CHECK` de
  `venta_pagos.metodo`: Caja y Cierre de Turno no sabrían cuánto de un pago
  "mixto" quedó en el cajón.
- **`ventas_repo.registrar_venta_sin_detalle` recibe `pagos` (lista), no
  un único método.** El `monto`/total de la venta se pasa aparte y se
  graba tal cual en `ventas.total` — nunca se lo deduce sumando `pagos`,
  porque un pago en Efectivo puede superar el total si hay vuelto de por
  medio (mismo criterio que `confirmar_venta`, que calcula el total desde
  el carrito y no desde los pagos).
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
- **Sumar un origen de venta nuevo toca la caja, no solo `dominio.py`.** Si un
  origen no figura en `turnos_repo._PREFIJO_COLUMNAS_POR_ORIGEN` (y en las
  columnas de `cierres_turno`), su plata desaparece del efectivo esperado en el
  cajón sin ningún error visible — el dueño usa este desglose para auditar
  faltantes. El test `TestCadaOrigenSumaEnLaCaja` lo atrapa. `ventas.origen` tiene
  un CHECK: agregar un origen exige que `database._migrar_check_origen_en_ventas`
  reconstruya la tabla (corre sola al arrancar, dejando una copia en
  `data/backups/antes_de_*.db`).
- **Reconstruir `ventas` no se hace con `_reconstruir_tabla`.** Esa función
  renombra la tabla vieja primero, y SQLite (desde 3.26) re-apunta a la renombrada
  todas las claves foráneas de las tablas hijas (`venta_detalle`, `venta_pagos`,
  `sesion_bonos`, `tramites_venta`, `movimientos_saldo_miembro`,
  `sesion_playstation_bonos`, `ventas_caja`): al borrarla, quedarían apuntando a una
  tabla que ya no existe. Para una tabla MADRE el orden es otro: crear `<tabla>_nueva`, copiar,
  borrar la vieja y recién ahí renombrar, con las claves foráneas apagadas y todo
  en UNA transacción — ver `_migrar_check_origen_en_ventas` y
  `TestMigracionCheckOrigenEnVentas` (en tests/test_playstation.py).
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
  cliente). El renglón "Reservas" aparte es solo de Caja y Cierre de Turno (lo
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
- **Un trámite es un servicio que se cobra, no el pago de una boleta.** Lo que
  se tipea en "Trámites" es lo que el local cobra por hacerle el trámite al
  cliente (imprimir la boleta de luz, un trámite online, sacar un turno...);
  la boleta en sí nunca pasa por la caja, así que no se la modela como una
  entrada y salida de plata de terceros. No tiene stock ni costo: es ganancia
  pura (la hace un empleado). Ver `tramites_repo`.
- **El fondo de la pantalla de bloqueo de las PCs es un adorno que nunca puede frenar el
  bloqueo.** Vive en UN archivo, `data/fondo_bloqueo.jpg` (`fondo_repo`): `data/` está fuera
  de git y de las copias de seguridad de la base, así que si se pierde se vuelve a elegir la
  imagen. Su versión es la huella de su contenido y viaja en cada `GET /estado`
  (`fondo_version`; cadena vacía = no hay) y en la cabecera `X-Fondo-Version` de `GET /fondo`;
  las dos salen del mismo `fondo_repo.obtener()` que los bytes, para que nunca queden
  desparejas. Cada Cliente PC lo baja en un hilo aparte (`CLIENTE PC/fondo_pantalla.py`): si
  acá algo falla (disco, imagen rota), `/estado` sigue contestando sin ese dato y `/fondo`
  da 404 o 500, y la PC se queda con el azul liso. No lo muevas a la base ni lo metas en el
  camino que decide si una PC está bloqueada. Un archivo que no empieza como JPEG cuenta
  como "no hay fondo". Abrir y achicar imágenes es de la pantalla (Qt): el repo no usa Qt.
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
  `v`, solo para mostrar; cada PC manda el suyo como `v` en cada `GET /estado`
  (`estaciones.numero_version_cliente`). Las PCs comparan solo la fecha: cargar una V más vieja la
  manda igual (la pantalla avisa antes). El número se sube en `CLIENTE PC/version_cliente.py`.
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
- **Las copias de seguridad se hacen en caliente, desde un hilo propio, y nunca
  pueden frenar el mostrador** (pedido del dueño, 2026-10-19: el programa queda
  abierto días seguidos y hasta ese día la única copia automática se hacía al
  abrirlo). `copias_repo` copia a `data/backups` después de cada Cierre de Turno
  (todos pasan por `turnos_repo.cerrar_turno`: se compara `MAX(fecha_cierre)` con
  la última copia) y cada 8 horas, y lleva la última a cada "otra carpeta" en cada
  revisión. Reglas que no hay que romper: (1) una copia se graba como `.parcial` y
  se renombra al final, para que una a medias nunca parezca la última ni viaje a
  otra carpeta; (2) solo se borran archivos con nombre de copia automática
  (`kiosko_AAAA-MM-DD[_HHMMSS].db`): nunca los `antes_de_*` ni las manuales; (3) las
  copias cuentan días CON copias, no días del calendario (un reloj que salta no
  borra todo); (4) una carpeta de otra PC se pregunta primero con
  `_que_conteste` (3 s al puerto 445): con esa PC apagada Windows tarda ~50 s
  (medido) y el hilo o la pantalla quedaban esperando; (5) el usuario y la clave de
  una carpeta de red se le pasan a Windows con `cmdkey` y NO se guardan en la base
  ni en un log (este repo es público: nunca escribas la clave real en un test o un
  doc); (6) las copias nunca crean una carpeta que falta (solo "Agregar carpeta"
  crea la de un disco de esta PC). La pantalla lee lo que pasó de `_estado`, en
  memoria, y no mira las carpetas: una de red apagada la congelaría.
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
- **Lo que corre en cada refresco de la pantalla de PCs (cada 5 s) no puede leer
  todo el historial.** `pcs_repo.estado_estaciones` y el panel "Actividad reciente"
  (`actividad_repo.actividad_reciente`, con `playstation_repo.eventos_recientes`)
  piden "lo último" apoyados en los índices de `database_esquema` ("ÍNDICES"); los
  bonos se ordenan por número de venta, no por `ventas.fecha`, para no recorrer la
  historia. Sin eso, con un año de uso la pantalla se trababa ~0,4 s cada 5 s
  (revisión del 2026-10-17). Una consulta nueva en ese camino necesita su índice:
  `tests/test_velocidad_pantalla_pcs.py` mide que el trabajo no crezca con el
  historial.
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
- **Un traslado de PC conserva la sesión y su saldo.** `pcs_repo.trasladar_sesion`
  mueve o intercambia la misma sesión bajo `BEGIN IMMEDIATE`; el historial de
  qué PC ocupó está en `traslados_sesion`, no en el nombre actual de la estación.
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
  mostrador (vender, cobrar, cajas y turnos, atender las PCs, Miembros,
  Actualizar el Cliente PC, Copias de Seguridad) NO entra en la lista. La
  pantalla principal se ve igual que en el mostrador, con la grilla de PCs en
  vivo (pedido del dueño, 2026-10-24: "quiero que se vea tal cual"): ahí esos
  botones están y avisan con `ui.utils.solo_en_el_mostrador` (un test revisa que
  todo lo que esa pantalla le pide a un repo esté en la lista, no vaya a la base
  o avise); en las demás pantallas se esconden con `modo.es_copia_remota()`. Sin
  respuesta del mostrador, la grilla deja lo último con un aviso rojo y prueba
  cada 30 s (cada intento sin respuesta traba la ventana hasta 2 s,
  `cliente.ESPERA_CONECTAR_SEGUNDOS`); (4) el cierre forzoso de la caja y dar
  de baja las sesiones vencidas lo hace solo el mostrador; (5) una consulta de reporte lenta frena las
  ventas del mostrador mientras dura (SQLite no deja grabar mientras otro lee):
  todo lo que se lee desde otra PC tiene que andar rápido con un año de ventas
  (medido el 2026-10-18: todo < 0,2 s con 110.000 ventas, después de sumar
  `idx_venta_pagos_venta`; sin ese índice Por Operador tardaba 6 minutos).
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
- **El esquema de color se fija en CLARO a propósito (`main.aplicar_estilo`).**
  Fusion toma los colores de Windows: con el modo oscuro puesto, los widgets que
  la hoja de estilos no pinta (el log de "Actividad reciente", la numeración de
  filas) salían negros y con la letra oscura de la hoja encima, ilegibles. Si se
  agrega un widget nuevo que se vea oscuro, hay que pintarlo en `HOJA_DE_ESTILOS`
  (no sacar el esquema claro). Para ver cómo queda una pantalla sin abrirla se puede
  dibujar con `widget.grab()` usando la plataforma real de Windows (la "offscreen" de
  los tests usa otras tipografías y no aplica el esquema de color).
- **El cobro arranca con el total escrito y, si pagan justo, un Enter cobra** (pedido del
  dueño, 2026-10-18: casi siempre pagan justo, en efectivo o por transferencia). En
  `ui.dialogo_pago.DialogoPago` Efectivo y Digital están siempre a la vista y suman el total
  (idea del dueño, 2026-10-18): arranca con el total en Efectivo, seleccionado (lo que se
  escribe lo reemplaza); al escribir en uno, el otro se completa con lo que falta; "Todo
  efectivo"/"Todo digital"; y "Paga con" (opcional) es el billete que da el cliente, para dar
  vuelto sin tocar lo digital. Escribir el billete en Efectivo también da vuelto (la costumbre
  de siempre). La cuenta es `dominio.cuenta_del_cobro`. Un Enter cobra SIEMPRE: pago justo,
  una parte en cada medio o con vuelto (pedido del dueño, 2026-10-18 a la noche: "el Enter
  debería ser para agilizar"; hasta ese momento con vuelto frenaba en Confirmar, y se sacó a
  pedido suyo). El vuelto se ve titilando mientras se escribe el billete y en Ventas sale
  además en el cartel de la venta cobrada. No vuelvas a poner la frenada sin que el dueño lo
  pida. Los bonos de PCs,
  PCSTREAM y PlayStation 5 (botón "Cobrar" del panel), Cargar Saldo de un socio y Trámites
  (Enter en el monto o en el bono) usan el mismo cuadro y arrancan igual (elegido por el dueño).
  Ventas: escanear, Enter con el código vacío (abre el cobro) y Enter. Un Enter que queda
  apretado no cobra: `encadenar_enter` descarta la repetición del teclado y los atajos de
  Confirmar no se repiten (`tests/test_dialogo_pago.py`, `tests/test_enter_como_tab.py`).
  Excepción a propósito: el texto de varias líneas del filtro de palabras (Enter es un
  renglón nuevo).
- **El "Renglón por renglón" del Detalle del Día muestra cada renglón TAL CUAL se
  cobró** (pedido del dueño, 2026-10-18: "si se cobran 14 impresiones juntas, que diga
  14; si se hacen 4 por separado, que las ponga tal cual se cobraron, con su horario y
  su operador"; lo imprime como la planilla de su programa anterior). No lo agrupes
  por producto "para que sea más corto": para eso está "Lo vendido (cantidades)". En
  pantalla y en papel salen las mismas filas (`ui.reportes_detalle_dia._renglones`).
- **Un bono anotado en la Cuenta de la PC es un bono para los reintegros de socios.**
  Mientras no se cobra no tiene fila en `sesion_bonos`, así que
  `reintegros_repo.contribuciones_de_sesion` lo saca de `cuenta_pc_items`; ya cobrado,
  su fila de `sesion_bonos` va con la hora en que se ANOTÓ (cuando se sumó el
  tiempo), no con la del cobro (`cuenta_pc_items.sesion_bono_id`). Sin eso, al
  cortar la sesión de un socio se le devolvía como saldo el tiempo del bono fiado, y
  la reconexión de una PC lo contaba mal. Un renglón de artículo guarda el código:
  está en `articulos_repo._TABLAS_CON_CODIGO_DE_ARTICULO`. La consola no tiene cuenta.
- **El recolector cíclico está desactivado a propósito** en `main.py`: evita que
  un hilo del servidor destruya un `QTimer` de Qt. Antes de reactivarlo, revisar
  la propiedad de los objetos de UI y sus ciclos de referencias.

---

## Qué no cambiar sin que el dueño lo pida explícitamente

- **El modelo de cobro de Control de PCs (y de la PlayStation 5).** Siempre
  bonos de tiempo fijos prearmados (ej. "3 horas" = 180 min / $X, en
  fracciones de 30 min). Nunca hora libre ni minuto suelto, y una PC sin
  bono/saldo activo queda bloqueada — no "abierta y se cobra después". Esto no es un detalle
  técnico, es una decisión de negocio del dueño del Cyber. La única excepción la pidió él
  (2026-10-25, Cuenta de la PC): a un cliente que YA está jugando se le puede anotar un bono
  fijo para cobrarlo después, con tope; una PC sin sesión sigue bloqueada y no se abre a cuenta.
- **La estructura de carpetas.** Hoy hay DOS árboles a propósito: `ui/` +
  `repositories/` (kiosko) y `control_pcs/ui/` + `control_pcs/repositories/`
  (PCs/Miembros/Bonos/Historiales) — el dueño pidió esta separación
  explícitamente el 2026-09-26 ("son dos cosas completamente diferentes a
  lo que es vender productos de kiosko"), no es desprolijidad para
  "limpiar" fusionándolos de nuevo. Cualquier reorganización más allá de
  esta sigue siendo una decisión de fondo que se charla antes, no algo que
  se infiere de "quedaría más prolijo".
- **`data/`, a mano.** Ahí vive la base real del negocio (está en
  `.gitignore` a propósito, no llega a git). No asumas que su contenido es
  descartable ni lo edites por fuera de una migración.
- **La clave de conexión de los Clientes PC es fija y permanente** (pedido del
  dueño, 2026-10-14; aceptó expresamente el riesgo de que quede dentro del
  `.exe`). No hay pantalla para generarla ni renovarla y no se guarda en la
  base: este repo es PÚBLICO, así que el programa solo conoce su huella SHA-256
  (`clientes_repo.HUELLA_CLAVE_CLIENTES`); la clave en sí vive en
  `CLIENTE PC/configuracion.py` (repo privado). Nunca escribir la clave en este
  repo (ni en un test, ni en un doc). Una huella SHA-256 simple alcanza porque la
  clave es un valor al azar de 256 bits, no una contraseña elegida (una revisión
  automática lo marcó el 2026-10-14 y se evaluó: no hace falta sal ni KDF, ni
  "rotar porque la huella está publicada"). No volver a proponer rotación ni un botón
  "Generar/renovar": cambiarla dejaría sin conexión a las ~40 PCs hasta
  reinstalarles el `.exe`; un test lo vigila. Es una cosa distinta de la
  contraseña de ADMIN de los Clientes PC, que sí se cambia desde "Gestionar
  Estaciones".

---

## Cliente PC (estado actual)

El bloqueo de las PCs funciona con el proyecto separado `CLIENTE PC/`,
ubicado en la carpeta hermana. Se comunica con el servidor de este repo
(`servidor_red.py`) para consultar el estado de cada estación, permitir
el login de Miembros y cerrar sesiones. `explorer.exe` sigue siendo el
shell de Windows; el cliente usa pantalla de bloqueo, hook de teclado y
una tarea programada para volver a arrancar si se cierra. El reemplazo
del shell no forma parte del diseño actual. Desde el 2026-10-19 el panel admin
de cada PC (la "A") ya no cierra el Cliente PC: "Hacer mantenimiento (15 min)"
deja la PC libre con el programa abierto y avisa `MANTENIMIENTO`, que se ve en
Actividad reciente pero NO marca la PC como sin cliente (sigue preguntando su
estado). `CIERRE_CLIENTE` solo llega de PCs sin actualizar. Todo pedido del cliente lleva la
clave fija de los Clientes PC (ver "Qué no cambiar sin que el dueño lo pida
explícitamente"). El README de `CLIENTE PC/` contiene las instrucciones
vigentes de instalación y recuperación.

## Roadmap (a futuro, fuera de alcance hoy)

Estos puntos todavía no están construidos:

- **Reportes específicos de PCs** (ej. "horas vendidas por día"). Se
  puede sumar reutilizando `sesion_bonos`, no hace falta tocar el
  esquema.

---

## Cómo trabajar en este repo

- **Idioma: español (rioplatense).** UI, comentarios, mensajes de commit y
  respuestas al usuario. El usuario no es programador: explicá los
  cambios en términos del kiosko, no de la implementación.
- **Stack:** Python 3.10+, PySide6, SQLite. Sin ORM, sin frameworks.
- **Git:** rama por cambio, después mergear a `master`.
- **Empaquetado:** `pyinstaller Kiosko.spec` genera `dist/CyberBios.exe` (el
  nombre con que lo usa el dueño; la receta conserva su nombre de archivo).
  Ojo: `dist/data/` es la base de datos *real* de la copia empaquetada.

---

## Estado actual

El programa integra kiosko (con el botón Impresiones), Control de PCs (con PCSTREAM), Miembros, Trámites, PlayStation 5 y Reservas (la plata, el cuidado de la hora y las de socios, sin seña).
Las decisiones de negocio y las trampas vigentes están arriba; el detalle
cronológico anterior se conserva en [docs/HISTORIAL.md](docs/HISTORIAL.md).
La suite actual se ejecuta con `python -m unittest discover tests` y tiene
1500 pruebas al 2026-10-28 (las ventanas de REINICIAR y APAGAR con el diseño B: las PCs libres como fichas del mosaico que se marcan con un clic, las que están en uso aparte con lo que les queda y sin poder marcarse, y el aviso de que solo se tocan las prendidas y libres; la ventana de Congelar / descongelar PCs con el diseño A: lista a la izquierda, tarjetas a la derecha y ACTUALIZAR CLIENTES solo para el Admin, con el copo dibujado; la PC libre que terminó de copiar el Cliente PC nuevo se reinicia sola para ponerlo y su monitor dice REINICIANDO hasta que vuelve, una sola vez por versión, nunca con un cliente ni en mantenimiento; las versiones del Cliente PC en carpeta: el .zip firmado con la lista de sus archivos, que solo les llega a las PCs que lo saben poner; quién abrió la caja y a qué hora, que viaja con el cierre a la app de gastos; la impresora de la vista previa que Python borraba y cerraba el programa sin cartel al imprimir; el Administrador que vuelve solo y en silencio a la empleada a los 10 minutos, solo si su caja sigue abierta a su nombre; los cierres que se asientan solos en la app de gastos del dueño: cola en la transacción del cierre, hilo que manda en el momento y reintenta, un documento por cierre, a nombre de la responsable de la caja, el forzoso marcado, la barra "ENVIANDO CIERRE DE TURNO" de 3 segundos como mínimo al confirmar, y la pantalla de Configuración ADMIN con prender/apagar, Probar la conexión y Reintentar ahora; las reservas de socios: un socio con 5 hs de saldo o más reserva una PC sin seña, y al que no llega se le carga saldo ahí mismo, el mínimo lo cambia solo el Admin en Miembros > "$ Para Reserva", al entrar con su usuario la reserva queda habilitada sola y si no viene no pierde nada; Administrar Kiosko con el mismo diseño, y lo que una encargada no tiene habilitado en gris con candado; Caja y Cierre de Turno con el mismo diseño: las dos cifras que importan en grande y la tabla de dónde vino la plata, negocio por negocio, con el efectivo y lo digital en columnas; Configuración ADMIN, Gestionar Estaciones y Reservas con el diseño que eligió el dueño, la maqueta "A": cabecera oscura con la estela celeste del cometa y pastillas con números, tarjetas de menú agrupadas con candado en lo que es solo del Admin, lo peligroso en rojo y aparte, y el estado de cada reserva como pastilla de color; piezas en `ui/piezas_ventana.py`; la plata en miles y sin centavos en todo el programa, "$ 1.500", también en los campos donde se escribe; la ventana de Venta de Mercadería con el diseño que eligió el dueño, la maqueta "B": el total oscuro y COBRAR siempre grandes a la derecha, teclas con la tecla dibujada aparte y el código y el precio por unidad debajo de cada producto, colores en `ui/hoja_de_estilos.py` y dibujos en `ui/ventas_dibujos.py`; F5 Código lista por código de menor a mayor, como números; la Cuenta de la PC: el cliente que juega pide un pancho, más tiempo o tiempo de socio, se anota en la cuenta de su sesión, su PC titila con borde fucsia y se cobra después, con tope que fija el Admin en Reglas de Cuenta de PC; 15 minutos antes del fin del turno titila más rápido y sale el cartel para cobrar, y lo que quedó sin cobrar va al cierre como fiado; desde otra PC la pantalla principal se ve igual que en el mostrador, con la grilla de PCs en vivo, y lo que vende, cobra o atiende una PC avisa que se hace en el mostrador; el servidor de red lee el cuerpo de un POST que rechaza, así la PC no se queda sin la respuesta por un "reset" de Windows: una prueba fallaba al azar; el 🔄 de Operador un 25% más grande, como ícono, y las flechas rojas dibujadas de REINICIAR; una sesión con bono ya no se cierra desde la PC: POST /logout la rechaza, solo los socios; Bajar a Excel en el Historial de Cargas y en Socios y Bonos; Reportes > PCs: Socios y Bonos; "No viene hace" en Miembros; el Historial de Cargas de Miembros; CONTROL DE STOCK, a la derecha de APAGAR, que lo abre solo el Admin; el botón "Cerrar sesión" ahora dice "Camb Operador" y va pegado a la derecha de Clave; Gestionar Marcas, solo para el Admin; el cometa del borde del fondo negro; "Programas y estado" y el mantenimiento a distancia del clic derecho de una PC; el botón APAGAR debajo del mosaico y el copo de nieve dibujado de DESCONGELAR; la carga de saldo de un socio que está usando una PC pasa a su sesión; los botones DESCONGELAR y REINICIAR debajo del mosaico, para cualquier operador y con su ventana para desmarcar PCs; el termómetro con la temperatura de cada PC; sin las 14 de Limpiar base de datos, que se sacó; la casilla "Operar PCs y Miembros" que se sacó de Usuarios; por qué una PC no puso la actualización del Cliente PC al reiniciarse, la barra en mayúscula y negrita; la revisión de limpieza del 21/10 sacó las 4 de `dominio.pagos_netos_de_vuelto`, que el cobro ya no usaba; la PC que no se enteró de que terminó su sesión titila como la PlayStation 5, y una PC que se reinicia sigue con su sesión y su tiempo; el reinicio del seguro de fin de sesión del Cliente PC; Reiniciar/Apagar que vencen a los 2 minutos y el motivo de cada reinicio que pide el Cliente PC; las reservas, parte 2: la PC reservada en el mosaico y en la pantalla de bloqueo, el aviso al vender y el socio que se corta a la hora; las reservas, parte 1: la plata; cambiar el código de un artículo desde ORDENAR Stock, el número que se escribe en una celda de tabla, como el stock de ORDENAR Stock, las preguntas de cerrar una sesión sin hablar de reintegros, el tiempo de las PCs al volver de un corte y con nadie logueado, la lista de Miembros alta, por usuario y con lupa, el detalle de cada cierre con la tarjeta del Cierre de Turno, también el forzoso, ORDENAR Stock, las copias de seguridad automáticas en varias carpetas, el aviso de mantenimiento de las PCs, la actualización del Cliente PC rehecha con casillas, con los cortes de las PCs, Miembros y la PlayStation 5 abiertos a cualquier operador, las cajas con número, administrar desde otra PC, el detalle del día con su renglón por renglón para imprimir, el cobro nuevo en todas las pantallas, congelar/descongelar PCs con Shadow Defender, la barra oscura de arriba, el botón Impresiones con Kiosko sin impresiones en Caja y Cierre de Turno, el panel gris del costado y la barra con todos los botones para todos).

La barra de arriba de la ventana principal es oscura, estilo cyber, con teclas en relieve (pedido del dueño 2026-10-19, eligió esta entre cuatro maquetas). Los colores viven en la hoja de estilos (`ui/hoja_de_estilos.py`: `#encabezadoInicio`, clases `barra` y `alerta`, y Vender/Operador dentro de la barra; "🔄 Operador" se llamaba "Cerrar sesión", renombrado a pedido del dueño 2026-10-23 a "Camb Operador" (pidió también que vaya pegado a la derecha de Clave y no solo en la punta) y el 2026-10-24 a las flechas en círculo + "Operador", que eligió entre cinco dibujitos). Cuidado al tocar `alerta`: tiene que llevar los mismos bordes, relleno y letra que `barra`, porque si no Cierre de Turno cambia de tamaño cada vez que titila (lo cuida `test_estilo_ui`). Desde el 2026-10-22 (pedido del dueño) todos los botones de la barra van en negrita (700, en la hoja de estilos) y en mayúscula (la pone `MainWindow._agregar_boton_barra`, y Reservas al cambiar su texto: Qt no tiene `text-transform`); así la ventana pide unos 1490 px de ancho (el mostrador tiene 1920).

La barra muestra los mismos botones a todos (pedido del dueño 2026-10-19: con solo los suyos la de una empleada quedaba muy vacía). El que alguien no tiene habilitado (Admin Kiosko) se ve igual pero no hace nada al apretarlo: no se apaga con `setEnabled(False)` porque se vería gris. Miembros abre para cualquier operador logueado (mismo día: antes pedía `permiso_control_pcs` o Admin, pero cargarle saldo a un socio tiene que poder hacerlo cualquiera). Config ADMIN la abre cualquiera, pero un Operador solo usa Gestionar Estaciones y ve el resto en gris (`ConfiguracionAdminWindow`, mismo día). Adentro, el Operador usa todo (estaciones, IP, fondo, filtro de palabras) menos "Cambiar contraseña de PC clientes" y "Actualizar el Cliente PC", que ve en gris (`DialogoGestionEstaciones` recibe el `usuario`; lo decidió el dueño el mismo día). Ese bloqueo es solo de pantalla: `clientes_repo` y `actualizacion_cliente_repo` no exigen Admin. Lo cuida `tests/test_barra_para_todos.py`.

El panel del costado de Control de PCs (`#panelDetalle`, los bonos y Cobrar) es gris medio (pedido del dueño 2026-10-19, eligió esta entre cinco maquetas). Sus reglas en `ui/hoja_de_estilos.py` van con `>` (solo hijos directos del panel y de `#contenedorBonos`) a propósito: el cobro, el login del socio y los avisos se abren con el panel como padre, y con un selector común quedarían con letras claras sobre su fondo claro (lo cuida `test_estilo_ui`).
