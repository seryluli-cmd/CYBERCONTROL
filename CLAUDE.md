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
| Método de pago | `PAGO_EFECTIVO`, `PAGO_DIGITAL`, `METODOS_PAGO` — y `PAGO_MIXTO`, que NUNCA se guarda (ver más abajo) |
| Turno | `TURNO_MANANA`, `TURNO_TARDE`, `TURNO_NOCHE`, `TURNOS` |
| Origen de una venta | `ORIGEN_KIOSKO`, `ORIGEN_ALQUILER_PCS`, `ORIGEN_PLAYSTATION`, `ORIGENES_VENTA` |
| Equipo que se alquila por tiempo / estado de su sesión | `DISPOSITIVO_PC`, `DISPOSITIVO_PLAYSTATION`, `NOMBRE_PLAYSTATION`, `NOMBRE_PCSTREAM`, `SESION_ACTIVA`, `SESION_FINALIZADA` |
| Comando a una PC / su estado en la cola | `TIPOS_COMANDO_PC`, `ESTADO_COMANDO_PENDIENTE`, `ESTADO_COMANDO_ENTREGADO` |
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
tabla. Para `comandos_pc.tipo`, `movimientos_saldo_miembro.tipo` y
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
> Única excepción: "Limpiar base de datos" (Configuración ADMIN,
> `limpieza_repo.limpiar_base`), pedida por el dueño el 2026-10-17 para la
> etapa de pruebas. Borra la plata y el historial de ventas y deja los
> catálogos; solo Admin, con copia completa en `data/backups/antes_de_limpiar_base_*`
> antes de borrar (sin copia no borra) y todo en una transacción. No sumes
> otros borrados "porque ya hay uno": si el dueño deja de necesitarlo, se saca.

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
pantalla `ui/control_cierres_window.py`), `actividad_repo.py` (feed de PCs) y
`database.py` (esquema en `database_esquema.py`, migraciones en
`database_migraciones.py`, conexiones/copias/claves en `database.py`).
Conservá las funciones públicas al partirlos para no tocar otras pantallas.

**13. Comentar el porqué, no el qué.**
Es la mejor costumbre que tiene este código y hay que sostenerla. Los
comentarios explican decisiones no obvias y trampas (por qué el turno
noche cruza la medianoche, por qué el `.exe` guarda la base al lado del
ejecutable). Un comentario que repite lo que dice la línea de abajo
sobra; uno que explica por qué esa línea es así vale oro.

### Cómo se verifica

**14. Regla de negocio nueva, test nuevo.**
`tests/` cubre turnos, stock, cierres, cajas con número, administrar desde otra PC, PCs, PCSTREAM, Miembros, PlayStation y totales.
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
| `turnos.turno_vencimiento(dia, turno)` | se decide si un turno ya debería estar cerrado: su fin + `MINUTOS_PARA_CIERRE_FORZOSO` (15 min, pedido del dueño 2026-10-18). Es también la hora del cierre forzoso de la caja |
| `turnos.fin_del_turno(dia, turno)` · `.inicio_del_aviso_de_cierre(dia, turno)` | se decide a qué hora termina un turno (Mañana 14, Tarde 22, Noche 06; domingo 18 y 06) y desde cuándo titila el botón Cierre de Turno (`MINUTOS_AVISO_ANTES_DEL_FIN`, 5 min antes) |
| `turnos.turno_que_arranca_tras_un_cierre(momento)` | se decide con qué turno queda anotado lo que sigue a un cierre (la hora del cierre + `TURNO_GRACIA_MIN`); la usa `turnos_repo._desde_y_turno_en_curso`, que es lo que ven Caja y Cierre de Turno y lo que graba `cerrar_turno`. Con la misma regla `relevo_repo.abrir_caja` decide el turno de una caja que se abre |
| `relevo_repo.situacion_al_entrar(usuario_id)` · `.abrir_caja` · `.recibir_caja` · `.cerrar_para_entrar` | se decide qué pasa con la caja cuando alguien entra (abrirla contando, recibirla contando todo el cajón, cerrar la de quien se fue, cerrar aparte las ventas sin caja; el Admin entra sin caja). La pantalla es `ui/ingreso_caja.py` |
| `relevo_repo.estado_de_la_caja()` · `.cierre_forzoso_si_corresponde()` | se decide si el botón Cierre de Turno titila y si toca el cierre forzoso (lo dispara `MainWindow._revisar_la_caja`, que espera si hay un cobro a medias) |
| `cajas_repo._quien_vende(conexion, usuario_id)` | se decide a nombre de quién y en qué caja queda una venta (lo que cobra el Admin va a nombre de la responsable de la caja abierta, con `ventas_caja.cargada_por`); lo usa `ventas_repo._insertar_cabecera_venta` |
| `cajas_repo.cambio_inicial(caja)` | se decide con cuánto cambio arrancó una caja (lo contado, o lo esperado si no se contó): es lo que queda en el cajón al cerrarla y lo que se espera en la siguiente |
| `control_cierres_repo.listar_cierres()` · `.detalle_cierre(id)` · `.verificar_cierre(...)` | se arma lo que muestra Control de Cierres (cada cierre con su caja, responsables, relevos, si se cerró sola o en ausencia) y se carga lo contado del sobre (solo Admin, cada conteo en `verificaciones_cierre`). `turnos_repo` los reexporta con el mismo nombre |
| `turnos_repo._cerrado_pasado_su_vencimiento(dia, turno, cerrado_a)` | se decide si un turno se cerró "tarde" (pasado su vencimiento): lo usan el aviso y el "Cerrado el dd/mm" del Resumen del Día |
| `dominio.es_admin(usuario)` | se pregunta si alguien es Administrador |
| `dominio.nombre_metodo(metodo)` | se arma el nombre corto de un método de pago |
| `ventas_repo.subtotal_linea(linea)` | se calcula lo que se cobra por un renglón |
| `ventas_repo.total_carrito(lineas)` | se suma el total de una venta en curso |
| `database.conexion_db()` | se abre una transacción contra la base |
| `database.DATA_DIR` / `DB_PATH` | se resuelve dónde viven los datos (código vs `.exe`) |
| `database.hash_clave()` / `verificar_clave()` | se maneja una contraseña |
| `usuarios_repo.tiene_permiso(usuario, clave)` | se decide si alguien puede entrar a algo |
| `usuarios_repo.exigir_admin(usuario_id, para)` · `.usuario_habilitado(usuario_id)` | un repo exige que quien opera siga activo (y sea Admin), releyéndolo de la base: un usuario dado de baja con la sesión abierta no puede seguir. Lo usan Limpiar base de datos y la PlayStation 5 |
| `clientes_repo.es_clave_de_clientes(clave)` | se decide si un pedido de red viene de un Cliente PC (clave fija, comparada por su huella SHA-256; la usa `servidor_red._autorizado`) |
| `fondo_repo.obtener()` · `.version_actual()` · `.guardar_jpeg(datos)` · `.quitar()` | se lee y se cambia el fondo de la pantalla de bloqueo de las PCs: un solo archivo `data/fondo_bloqueo.jpg`, con su versión (la huella del contenido) que viaja en `GET /estado` como `fondo_version`. La pantalla (`pcs_fondo_dialogo.preparar_jpeg`) lo achica con Qt; el repo valida que sea un JPEG y que no pase del tope |
| `filtro_palabras_repo.obtener()` · `.guardar(...)` · `.registrar_bloqueo(...)` | se lee y se cambia el filtro de palabras de las PCs ("protección antiporno", pedido del dueño 2026-10-17: prendido, lista y mensaje, como JSON en `configuracion`; su versión viaja en `GET /estado` como `filtro_version`) y se anota cada página que cerró una PC (`bloqueos_filtro_pc`). Buscar las palabras en los títulos es tarea de cada Cliente PC (`CLIENTE PC/filtro_palabras.py`), no de este repo |
| `actualizacion_cliente_repo.publicar(datos)` · `.version_para_estacion(id)` · `.registrar_reporte(id, parametros)` · `.estado_de_las_pcs()` | se carga y FIRMA una versión del Cliente PC (`data/cliente_pc/`), se decide qué versión le toca a cada PC (las de prueba o todas; viaja en `GET /estado` como `cliente_version`), se guarda lo que cuenta cada PC (versión, carpeta, cómo va) y se arma lo que muestra "Actualizar el Cliente PC de las PCs..." (pedido del dueño, 2026-10-18) |
| `admin_remoto_repo.esta_activo()` · `.activar(...)` · `.entrar(nombre, clave, ip)` · `.exigir_admin_habilitado(id)` | se decide quién administra desde otra PC del local: viene apagado, solo un ADMIN activo, cada ingreso en `sesiones.desde_ip` (pedido del dueño, 2026-10-18) |
| `admin_remoto.lista_blanca.FUNCIONES` · `.ACTOR` · `.huella()` | qué funciones de los repos se pueden pedir desde otra PC, qué parámetro es "quién lo hizo" (lo completa el mostrador) y la huella que tienen que compartir las dos copias del .exe |
| `admin_remoto.modo.direccion_del_mostrador()` · `.es_copia_remota()` | se decide si esta copia es la del mostrador o una abierta por la red (y a qué PC le habla), y las pantallas esconden lo que solo se hace en el mostrador |
| `config_repo.obtener_fondo_cambio()` | se lee el fondo de cambio del turno |
| `pcs_repo.estado_estaciones()` | se calcula el tiempo restante y estado de cada PC |
| `pcs_repo.estado_de_estacion(nombre, ip)` | se decide qué estación es una PC que se conecta: por el nombre que manda su Cliente PC y, si ninguna activa se llama así, por la IP asentada en su primer enlace (`registrar_conexion`); con una IP asentada en dos estaciones activas no adivina. La usan TODOS los endpoints de `servidor_red.py` |
| `pcs_repo._orden_natural(estacion)` | se ordenan las estaciones como lo haría una persona ("PC2" antes que "PC10"), con PCSTREAM antes que todas (en el mosaico queda al lado de la PlayStation 5); lo usan `listar_estaciones` y `estado_estaciones` |
| `dominio.es_pcstream(nombre)` | se decide si una estación es PCSTREAM, la PC de streaming (solo por el nombre, sin espacios/guiones/mayúsculas; pedido del dueño, 2026-10-17). `estado_estaciones` lo trae en `item["es_pcstream"]` para la pantalla |
| `pcstream_repo.uso_por_dia(desde, hasta)` | se calcula cuánto se usó PCSTREAM, en tiempo (vendido y de uso real) y en plata (Reportes > PCSTREAM) |
| `reintegros_repo.reintegros_por_miembro(...)` | se decide cuánto se le devuelve a cada socio al cortar una sesión de PC (lo usa `pcs_repo.finalizar_sesion`) |
| `pcs_window.PanelControlPcs._ficha_de_pc(...)` · `._ficha_de_playstation(...)` | se decide con qué color, dibujito y aviso se ve cada equipo en el mosaico; `control_pcs/ui/pcs_mosaico.py` solo dibuja la `Ficha` que recibe |
| `pcs_repo.asignar_bono(...)` | se crea o extiende una sesión de PC con un bono del mostrador: el COMÚN (walk-in) o, si la PC es PCSTREAM, uno de SU catálogo (`pcstream_repo`) |
| `dominio.segundos_restantes(fin, ahora)` · `dominio.fin_al_sumar_minutos(fin_actual, minutos, ahora)` | se calcula cuánto le queda a una sesión de tiempo y cuándo vence al sumarle un bono (PCs Y PlayStation 5: una sola cuenta) |
| `playstation_repo.estado()` · `.vender_bono(...)` · `.finalizar_sesion(...)` | se sabe cómo está la PlayStation 5, se le vende un bono (origen PLAYSTATION) y se la libera; ahí mismo se exige el permiso (`puede_operar`) o ser Admin (catálogo) |
| `turnos_repo._desglose_de_totales(...)` · `_PREFIJO_COLUMNAS_POR_ORIGEN` | se reparte lo cobrado de un turno por origen (kiosko/pcs/playstation × efectivo/digital) y se suma el efectivo del cajón sobre TODOS los `ORIGENES_VENTA` |
| `bonos_miembro_repo.listar_bonos()` / `.obtener_bono(id)` | catálogo de bonos EXCLUSIVO de socios (no confundir con `pcs_repo`) |
| `miembros_repo.abrir_estacion_por_miembro(...)` | un socio abre una PC con su propio saldo (y, con `pedir_datos`, completa sus datos del primer ingreso) |
| `miembros_repo.normalizar_dni(...)` · `.tiene_dni(miembro)` · `.normalizar_telefono(...)` | se valida y se guarda el DNI (solo números, 7 u 8 cifras), el celular y el WhatsApp de un socio, y se decide si a un socio le falta el DNI (el Cliente PC se lo pide; Miembros lo marca "Falta DNI") |
| `dominio.carga_minima_de_saldo(tramos)` · `miembros_repo.validar_monto_de_carga(...)` | se decide cuánto es lo mínimo que un socio puede cargar con un monto libre (el monto del tramo más bajo de la Tarifa por Hora para Socios; pedido del dueño, 2026-10-17) y se rechaza una carga menor: la pantalla la valida antes de pedir el medio de pago, el repo de nuevo al cobrar |
| `ui.dialogo_pago.cobrar(parent, monto)` | se cobra un monto fijo con la ventana de cobro de Ventas (medio de pago, reparto y vuelto): el bono de PC, PCSTREAM o PlayStation 5 del botón "Cobrar" de Control de PCs, y el Mixto de `resolver_pagos`. Devuelve los pagos netos de vuelto, o None si se canceló |
| `ventas_repo.registrar_venta_sin_detalle(...)` | se arma una venta sin artículo real de por medio (bono de PC, carga de saldo) |
| `dominio.CODIGO_ARTICULO_IMPRESIONES` | se decide qué artículo de kiosko es "Impresiones" (el producto Nº 1), para mostrarlo como renglón propio en Reportes |
| `turnos_ventas_repo._vendido_aparte_entre(...)` (lo usa `turnos_repo`) | se calcula cuánto del Kiosko de un turno fue impresiones y trámites, para mostrarlos en columna propia en el Resumen del Día (y las impresiones, como renglón informativo, en Cierre de Turno vía `resumen_turno_actual()["impresiones"]`) |
| `tramites_repo.registrar_tramite(...)` | se cobra un trámite de mostrador (monto libre): venta KIOSKO sin detalle + vínculo en `tramites_venta` |
| `main.aplicar_estilo(app)` | se fija el aspecto de TODO el programa: estilo Fusion, esquema de color CLARO y la hoja de estilos (`HOJA_DE_ESTILOS`) |
| `ui.utils.formato_pesos(monto)` | un número se convierte en `"$ 1.234,50"` |
| `ui.utils.formato_fecha_hora(fecha)` | una fecha con hora de la base se convierte en `"16/10/2026 22:13"` |
| `reportes_repo.resumen_por_operador(...)` · `.ventas_de_operador(...)` | se calcula cuánto vendió cada usuario y se listan sus ventas con fecha y hora (Reportes > Por Operador) |
| `limpieza_repo.limpiar_base(usuario_id)` | se borra la plata y el historial de ventas para volver a probar (qué tablas, en `_TABLAS_A_VACIAR`; devuelve el stock de las ventas confirmadas y deja a los socios con saldo 0). Una tabla nueva que guarde plata o ventas tiene que sumarse ahí |
| `errores.registrar_error(excepcion, contexto)` | la UI y el servidor guardan fallos inesperados en `data/errores.log` sin depender de Qt |
| `ui.utils.manejar_errores` | se atrapa un error de una acción de pantalla |
| `ui.utils.encadenar_enter(...)` | se arma el salto de campo en campo con Enter, como Tab, y la acción del último campo (pedido del dueño, 2026-10-18: todo formulario lo usa). Descarta el Enter repetido de una tecla que quedó apretada |
| `ui.utils.aplicar_clase(widget, clase)` | un botón se marca como primario/peligro |
| `ui.utils.sin_boton_por_defecto(ventana)` | se evita que Enter en un campo active el primer botón de un diálogo (llamarla al final de `_armar_interfaz`) |
| `ui.utils.crear_tabla(titulos, ...)` | se arma una tabla de solo lectura (filas alternadas, columna que se estira, selección por filas) |
| `ui.utils.mostrar_columna_entera(tabla, columna)` | se ensancha una columna para que su texto no se corte con "..." (la de códigos de barras, en las seis tablas que la muestran: llamarla después de llenar la tabla). Con 100 px un EAN-13 se veía "77981133010…" y parecía guardado con dos dígitos menos (2026-10-18) |
| `ui.buscar_articulo.avisar_codigo_no_encontrado(ventana, codigo)` | se avisa en Ventas y Compras que lo escaneado no es ningún artículo, con cuántos dígitos llegaron (para comparar con el código cargado) |
| `ui.utils.crear_selector_de_fecha(...)` | se crea un campo de fecha con calendario (sin sábado/domingo en rojo; usarlo siempre, nunca un `QDateEdit` a mano) |
| `ui.utils.armar_filtro_por_fechas(...)` · `rango_de_fechas(...)` · `fecha_iso(...)` | se arma la fila Desde/Hasta con "Buscar" y se leen sus fechas como `"YYYY-MM-DD"` (el formato con que hablan los repos) |
| `ui.utils.fila_guardar_cancelar(dialogo, ...)` | se arma la fila Guardar/Cancelar de un formulario |
| `ui.utils.fila_agregar_quitar(tabla, ...)` | se arman los botones Agregar/Quitar de una tabla que se edita a mano |
| `ui.buscar_articulo.armar_botones_de_busqueda(ventana, ...)` | se arman los botones F5/F6/F7 y sus atajos (Ventas y Compras) |
| `ui.detalle_venta.VentanaConDetalleDeVenta` | lista de ventas + artículos de la elegida (Consulta de Ventas y Detalle de un cierre) |
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
- **El stock puede quedar negativo a propósito.** No agregues una
  validación que lo impida: prefieren vender y corregir después antes que
  frenar la cola en el mostrador.
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
- **Toda venta sin artículo real de por medio pasa por
  `ventas_repo.registrar_venta_sin_detalle`, nunca un `INSERT INTO ventas`
  a mano.** Es lo único que le pone el `origen` correcto
  (`dominio.ORIGENES_VENTA`) — sin eso, el desglose Kiosko/Alquiler de
  PCs/PlayStation 5 de Caja y Cierre de Turno queda mal. El dueño pidió este desglose
  explícitamente para poder auditar la caja (sospecha de faltantes), así
  que un error acá no es solo un bug visual.
- **`dominio.PAGO_MIXTO` no es un método de pago real: nunca llega a
  `venta_pagos`.** Es una opción del combo de Cargar Saldo de un socio y de
  Trámites, que abre `ui.dialogo_pago.DialogoPago` para repartir el monto
  entre Efectivo y Digital — termina grabando una o dos filas reales de
  `PAGO_EFECTIVO`/`PAGO_DIGITAL`, igual que un pago combinado de una venta
  de kiosko. Por eso no está en `METODOS_PAGO` ni en el `CHECK` de
  `venta_pagos.metodo`: agregarlo ahí rompería el desglose Efectivo/Digital
  de Caja y Cierre de Turno, que no sabría de dónde sacar el
  Efectivo/Digital de un pago "mixto" sin desglosar. Ver
  `ui.dialogo_pago.resolver_pagos`, que usan `DialogoCargarSaldo`
  (miembros_window.py) y `DialogoTramites` (tramites_window.py). Los bonos de
  Control de PCs ya no tienen combo: el botón "Cobrar" del panel abre directo
  `DialogoPago` (`ui.dialogo_pago.cobrar`, pedido del dueño 2026-10-18).
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
  "Configuración ADMIN" (`ui/main_window.ConfiguracionAdminWindow` —
  pedido explícito del dueño, 2026-09-28: editar el catálogo es tarea de
  super admin; *usar* un bono ya creado sigue delegable con
  `permiso_control_pcs`). No fusionar estos catálogos "para simplificar":
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
  pantalla.** Vender un bono y liberarla: ADMIN o `permiso_control_pcs`
  ("Operar PCs y Miembros"); crear/modificar/dar de baja sus bonos: solo ADMIN
  (`playstation_repo` levanta `PermissionError`, que `ui.utils.manejar_errores`
  muestra como mensaje). Se vuelve a leer el usuario de la base en cada operación,
  así que un permiso quitado o un usuario desactivado corta el acceso en el acto.
  Ojo con la asimetría, es pedido del dueño: las **PCs** siguen abiertas a
  cualquier usuario logueado (no piden permiso), la consola no.
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
  recién cargada vuelve el alcance a "solo las de prueba" (nunca va sola a todas), y la versión es la
  fecha y hora de carga y siempre crece. El reporte de cada PC (`registrar_reporte`) se escribe solo si
  cambió: llega en cada `GET /estado` de cada PC, cada 5 s. Poner la versión en uso, vigilarla y volver
  atrás es tarea del lanzador de cada PC (`CLIENTE PC/lanzador.py`), no de acá.
- **El servidor de red no debe tocar Qt.** Usa conexiones SQLite propias desde
  sus hilos y registra fallos inesperados con `errores.registrar_error`, sin
  incluir claves ni el cuerpo de los pedidos en el contexto del log.
- **El refresco de PCs distingue esperar de perder el Cliente PC.** Si la
  estación aún no se conectó desde que arrancó el bono, muestra "Esperando al
  cliente"; si se desconecta después de estar enlazada, avisa "SIN CLIENTE".
  `pcs_repo._estado_para_estacion` decide esto para la grilla y para el Cliente PC.
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
  pisa sola (`ultima_ip` sí, en cada conexión); solo la borra el Admin desde
  Gestionar Estaciones y se vuelve a asentar en la próxima conexión por nombre. La IP
  sale del socket (`self.client_address`), nunca de un dato que mande el Cliente PC,
  y se mira DESPUÉS de la clave de Clientes PC. El nombre siempre gana; una IP
  asentada en dos estaciones activas no reconoce a ninguna (no adivinar: daría el
  tiempo de una PC a otra). Las PCs del local tienen IP fija; si alguna pasara a
  DHCP, la IP asentada podría quedar en otra máquina. Ver `tests/test_ip_asentada.py`.
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
  `MINUTOS_PARA_CIERRE_FORZOSO` (15), no los mezcles.
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
  mostrador (vender, cobrar, cajas y turnos, la grilla de PCs, Miembros, Limpiar
  base, Actualizar el Cliente PC, Copia de Seguridad) se esconde con
  `modo.es_copia_remota()` y NO entra en la lista; (4) el cierre forzoso de la
  caja lo hace solo el mostrador; (5) una consulta de reporte lenta frena las
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
- **En Cierre de Turno, Impresiones es un renglón informativo: no se le resta a
  Kiosko.** Esa pantalla es el resumen que las empleadas le mandan al dueño.
  Kiosko lleva su desglose efectivo/digital (lo que se guarda en el cierre y con
  lo que cierra el cajón), pero las impresiones se cuentan por renglón de venta y
  no por medio de pago: restarlas obligaría a repartirlas entre efectivo y
  digital con una cuenta aproximada. Por eso el título dice "incluidas en
  Kiosko" (el Resumen del Día y Reportes sí las muestran aparte, ahí Kiosko es un
  solo importe). Si el dueño pide Kiosko sin impresiones, primero hay que decidir
  cómo repartirlas por medio de pago. Los trámites van igual: renglón informativo
  "incluidos en Kiosko" (`resumen["tramites"]`), ya están en el TOTAL, no se
  suman dos veces.
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
  `ui.dialogo_pago.DialogoPago` el monto propone lo que falta cubrir, seleccionado (lo que se
  escribe lo reemplaza). Enter con un pago que cubre justo confirma solo; con vuelto, o con el
  resto puesto en el otro medio, se frena en Confirmar: la empleada tiene que ver el vuelto o el
  reparto antes de cobrar. No saques esa frenada "para ahorrar un Enter". Los bonos de PCs,
  PCSTREAM y PlayStation 5 (botón "Cobrar" del panel, siempre) y el Mixto de socios y trámites
  usan el mismo cuadro y arrancan igual (elegido por el dueño).
  Ventas: escanear, Enter con el código vacío (abre el cobro) y Enter. Un Enter que queda
  apretado no cobra: `encadenar_enter` descarta la repetición del teclado y los atajos de
  Confirmar no se repiten (`tests/test_dialogo_pago.py`, `tests/test_enter_como_tab.py`).
  Excepciones a propósito: el texto de varias líneas del filtro de palabras (Enter es un
  renglón nuevo) y "Limpiar base de datos" (Enter nunca borra).
- **El recolector cíclico está desactivado a propósito** en `main.py`: evita que
  un hilo del servidor destruya un `QTimer` de Qt. Antes de reactivarlo, revisar
  la propiedad de los objetos de UI y sus ciclos de referencias.

---

## Qué no cambiar sin que el dueño lo pida explícitamente

- **El modelo de cobro de Control de PCs (y de la PlayStation 5).** Siempre
  bonos de tiempo fijos prearmados (ej. "3 horas" = 180 min / $X, en
  fracciones de 30 min). Nunca hora libre ni minuto suelto, y una PC sin
  bono/saldo activo queda bloqueada — no "abierta y se cobra después". Esto no es un detalle
  técnico, es una decisión de negocio del dueño del Cyber.
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
del shell no forma parte del diseño actual. Todo pedido del cliente lleva la
clave fija de los Clientes PC (ver "Qué no cambiar sin que el dueño lo pida
explícitamente"). El README de `CLIENTE PC/` contiene las instrucciones
vigentes de instalación y recuperación.

## Roadmap (a futuro, fuera de alcance hoy)

Estos puntos todavía no están construidos:

- **Reportes específicos de PCs** (ej. "horas vendidas por día"). Se
  puede sumar reutilizando `sesion_bonos`, no hace falta tocar el
  esquema.
- **Separar "Cargar Saldo" de Miembros de la gestión completa de
  socios.** Hoy vive dentro de "Miembros" (botón propio de la barra
  superior, permiso `permiso_control_pcs`), aunque cargar saldo es una
  venta como cualquier otra. Editar la tarifa y el catálogo de Bonos de
  Socios ya quedó exclusivo de ADMIN desde "Configuración ADMIN"
  (2026-09-28) — lo que falta, si en algún momento se quiere, es un
  permiso aparte para que un empleado común pueda cobrarle saldo a un
  socio sin tener acceso a dar de alta/baja Miembros — decisión
  consciente de no hacerlo hasta que el dueño lo pida.

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

El programa integra kiosko, Control de PCs (con PCSTREAM), Miembros, Trámites y PlayStation 5.
Las decisiones de negocio y las trampas vigentes están arriba; el detalle
cronológico anterior se conserva en [docs/HISTORIAL.md](docs/HISTORIAL.md).
La suite actual se ejecuta con `python -m unittest discover tests` y tiene
723 pruebas al 2026-10-18 (con las cajas con número y administrar desde otra PC).
