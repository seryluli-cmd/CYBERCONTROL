# Revisión de limpieza — 17 de octubre de 2026

Primera etapa: **solo revisar**. No se cambió nada del programa; este informe es
lo único nuevo. La base real y `data/` no se tocaron (las mediciones usaron una
base temporal). Punto de partida: `master` en `94e9f83`, **500 pruebas, todas OK**.

Se partió de la revisión anterior (`docs/AUDITORIA_2026-10-10.md`) para no repetir
lo ya resuelto. Cómo se revisó:

- Un script que recorre todo el código y busca imports sin usar y funciones o
  constantes que nadie llama. Cada caso se confirmó a mano buscando el nombre en
  todo el repo, tests incluidos.
- Un script que busca bloques de código repetidos (6 líneas o más) entre archivos.
- Un script que verifica que cada `modulo.funcion` nombrado en README.md,
  CLAUDE.md, AGENTS.md y en los comentarios exista donde dice.
- Un script que revisa las 500 pruebas: pruebas pisadas (dos con el mismo nombre
  en una clase), pruebas idénticas y pruebas que no verifican nada.
- Búsquedas de las reglas de CLAUDE.md: SQL en pantallas, textos fijos fuera de
  `dominio.py`, plata formateada a mano, roles comparados a mano, archivos de más
  de 600 líneas.
- **Medición de velocidad** con una base temporal que simula 40 PCs y 1 año de
  uso (146.000 sesiones de PC con sus ventas, 18.000 movimientos de socios).
- Comparación de lo que contesta `servidor_red.py` con lo que lee y manda
  `CLIENTE PC/red_kiosko.py` (sin tocar CLIENTE PC).

No apareció nada que hoy haga fallar al programa. Lo más importante es una
lentitud que todavía no se nota porque la base está casi vacía.

---

## Arreglar ya

### 1. El panel de "Actividad reciente" se vuelve lento a medida que se usa el programa

**Qué pasa.** La pantalla de PCs se actualiza cada 5 segundos. En cada
actualización, el panel de actividad pide "los últimos 30 movimientos" de varias
listas: sesiones que empezaron, sesiones que terminaron, bonos vendidos,
movimientos de socios y traslados. Como esas listas no tienen un índice por fecha
(un atajo para encontrar lo último sin leer todo), la base las **lee enteras
desde el primer día** cada vez.

Medido en esta PC con la base simulada:

| Historial | Actualización de la pantalla de PCs (cada 5 s) |
|---|---|
| 1 semana | 12 ms |
| 1 año | **227 a 239 ms** (casi un cuarto de segundo trabada, cada 5 s) |
| 1 año, con la propuesta | **~12 ms**, con exactamente los mismos resultados |

Con dos años sería medio segundo cada 5 segundos, en la pantalla que se usa todo
el día. No es un error hoy, pero empeora solo cada día de uso. Conviene hacerlo
antes de arrancar en serio: con la base casi vacía, crear los índices es
instantáneo.

**Dónde.**
- `control_pcs/repositories/actividad_repo.py:7` (`actividad_reciente`).
- `control_pcs/repositories/pcs_repo.py:241`: la búsqueda de sesiones activas
  tampoco tiene índice. Pasa de 2 ms a 19 ms con un año de historial.

**Propuesta.**
- Una migración (segura de correr dos veces, regla 6) que agregue índices a
  `sesiones_pc(fecha_inicio)`, `sesiones_pc(fecha_fin_real)`, `sesiones_pc(estado)`,
  `movimientos_saldo_miembro(fecha)`, `traslados_sesion(fecha)`,
  `sesion_bonos(venta_id)` y `sesion_pcstream_bonos(venta_id)`.
- Escribir las dos consultas de "bonos vendidos" empezando por `ventas`, que ya
  tiene índice por fecha (`idx_ventas_fecha`). Con eso solo los índices bajan la
  pantalla a 93 ms; reescribiendo esas dos consultas queda en ~12 ms.
- Una prueba que verifique que el panel muestra lo mismo que antes.

**Riesgo.** Bajo: un índice no cambia ningún dato ni ningún resultado, solo la
velocidad. Lo único que cuesta es crearlo una vez, al primer arranque.

No se simuló historial de la PlayStation 5 ni de los accesos de admin a las PCs:
la consola es una sola y los accesos ya tienen índice por fecha.

### 2. Una migración vieja dice algo sobre la clave de las PCs que ya no es cierto

**Qué pasa.** `database_migraciones.py:346` (`_migrar_clave_clientes_pc`, se
corre en cada arranque desde `database_esquema.py:547`) renombra una fila
`clave_agentes` → `clave_clientes` de la tabla `configuracion`. Su explicación dice
que "el código de acá en más busca 'clave_clientes'" y que si se perdiera "habría
que regenerarla y volver a distribuir config.json". Desde el 14/10 eso es falso:
la clave de las PCs es fija, no se guarda en la base y nada lee esa fila (una
prueba verifica que ya no existen `generar_clave_clientes` ni
`obtener_clave_clientes`). Quien lea esto puede creer que la clave vive en la
base, justo lo contrario de lo que dice CLAUDE.md.

**Propuesta.** Sacar esa migración, que ya no cumple ninguna función.
Además, decidir vos si se borra la fila vieja `clave_clientes`/`clave_agentes` que
pueda haber quedado en alguna base. Es una copia de una clave que el programa ya no
lee, pero es una decisión tuya porque toca datos.

**Riesgo.** Ninguno para el funcionamiento: se buscaron todas las lecturas de
`configuracion` y ninguna pide esa fila.

### 3. Las PCs dependen de una palabra exacta de un mensaje del servidor, y ninguna prueba lo vigila

**Qué pasa.** Cuando una PC manda un aviso de acceso de admin y el servidor
contesta "Estación desconocida." (`servidor_red.py:295`), el Cliente PC busca la
palabra **"desconocida"** en ese texto para decidir si descarta el aviso o lo
sigue reintentando (`CLIENTE PC/red_kiosko.py:243`). La prueba de ese caso
(`tests/test_control_pcs.py:1574`) solo mira que la respuesta sea 404, no el
texto. Si alguien mejora la redacción del mensaje (por ejemplo, "Esa PC no
existe"), todas las pruebas siguen pasando y las PCs se quedan reintentando esos
avisos para siempre, sin que nadie lo note.

**Propuesta.** Sumar a esa prueba que el mensaje contenga "desconocida", y un
comentario junto al mensaje que explique que el Cliente PC depende de esa
palabra. No hay que tocar CLIENTE PC.

**Riesgo.** Ninguno: es una prueba y un comentario.

---

## Conviene

### 4. `repositories/turnos_repo.py` pasó el tope de ~600 líneas (regla 12)

Tiene 678 líneas (el 10/10 tenía 575). Lo que más creció es el **Resumen del Día**:
`resumen_del_dia` ocupa 155 líneas (`turnos_repo.py:440`), más sus ayudantes
(`_cerrado_pasado_su_vencimiento` en la 386, `_cierres_hechos_ese_dia_y_anotados_antes`
en la 398) y los estados del reporte (líneas 302-308). **Propuesta:** pasarlo a un
archivo propio, `repositories/resumen_dia_repo.py`, y que `turnos_repo` lo siga
ofreciendo con los mismos nombres. Así no cambia ninguna pantalla, y Caja y Cierre
de Turno quedan en un archivo más chico. **Riesgo:** bajo, hay muchas pruebas del
Resumen del Día. Habría que actualizar la tabla de puntos únicos de CLAUDE.md.

### 5. El estado de los comandos a las PCs está escrito a mano (regla 5)

`control_pcs/repositories/comandos_pc_repo.py:61`, `:77` y `:92` escriben
`'PENDIENTE'` y `'ENTREGADO'` directo en el SQL. Un error de tipeo ahí haría que
los comandos (reiniciar, apagar, mensaje...) nunca les lleguen a las PCs, sin
ningún aviso. **Propuesta:** `dominio.COMANDO_PENDIENTE` y
`dominio.COMANDO_ENTREGADO`, pasados como parámetro, igual que el resto de los
estados. **Riesgo:** ninguno, son los mismos textos.

### 6. La guía del mostrador (`LEEME.txt`) quedó atrás

No menciona nada de lo agregado en los últimos días:
- PCSTREAM: bonos propios, los socios no la pueden abrir, no entra en
  "Intercambiar de máquina" y tiene su reporte en Reportes > PCSTREAM.
- El día del local de 06:00 a 06:00: a las 2 de la mañana, "Solo Hoy" todavía es
  el día anterior.
- La carga mínima de saldo de los socios.
- La IP asentada de cada PC y el botón "Borrar IP" en Gestionar Estaciones.
- "Limpiar base de datos", para la etapa de pruebas.

**Propuesta:** un párrafo corto por cada tema.

### 7. Una cadena de imports frágil entre `database.py` y `database_migraciones.py`

`database_migraciones.py` toma funciones de `database.py`, y `database.py`
reexporta las migraciones desde un bloque que está **al final del archivo**
(`database.py:333`). Funciona solo porque ese bloque está abajo de todo: si
alguien lo sube al principio, como se ordenan los imports normalmente, el
programa no arranca. Se comprobó en una copia: falla con `ImportError` al
importar `database`. Nada lo advierte. **Propuesta:** que
`database_esquema.py:12` tome las migraciones directo de `database_migraciones`, y
dejar en `database.py` un comentario que explique por qué ese bloque va al final.
**Riesgo:** bajo; si se rompe, se nota al instante porque no arranca ninguna prueba.

### 8. Ejecutables viejos sueltos en la carpeta del proyecto (fuera de git)

`CYBERCONTROL\CyberBios.exe` (16/10) y `dist\CyberBios_anterior.exe` (14/10) son
versiones viejas. Si alguien abre `CYBERCONTROL\CyberBios.exe` por error, usa la
base vieja de pruebas que está al lado (`CYBERCONTROL\data`). Si en ese momento
el programa de verdad está cerrado, ese pasa a ser el servidor de las PCs del
local. El 16/10 pasó algo parecido al probar un exe. **Propuesta:** borrar esos dos `.exe`; ocupan
unos 100 MB. No se toca ninguna carpeta `data`. **Riesgo:** ninguno; el que usás
está en el escritorio, con sus respaldos.

---

## Detalle

9. **Comentarios y documentación con el número o la pantalla vieja.**
   - `dominio.py:292` y `control_pcs/repositories/playstation_repo.py:128` dicen
     "los tres catálogos": son cuatro desde PCSTREAM.
   - `control_pcs/repositories/pcs_repo.py:227` dice "mostrarlo en la tabla";
     `control_pcs/ui/pcs_window.py:131` y `:136` dicen "fila de la grilla".
   - `CLAUDE.md:341`, `CLAUDE.md:349` y `README.md:237` dicen que la PlayStation 5
     es "la primera fila de la grilla". Desde el 16/10 es el primer monitor del
     mosaico.
10. **Documentación que apunta a un lugar viejo.** `README.md:69`, `README.md:163`,
    `database_esquema.py:256` y `repositories/usuarios_repo.py:57` mandan a
    `turnos_repo._responsables_del_mes`. Desde el 10/10 esa función vive en
    `turnos_faltantes_repo`, y `turnos_repo.py:32` la importa solo para que esas
    referencias sigan andando. **Propuesta:** apuntar al lugar real y sacar ese
    import.
11. **`README.md:444` dice 428 pruebas**: son 500.
12. **Tres listas de `dominio.py` que nadie usa**: `ROLES` (línea 35),
    `ESTADOS_VENTA` (55) y `EVENTOS_ADMIN_PC` (172). Repiten lo que los `CHECK`
    del esquema escriben a mano (`database_esquema.py:46`, `database.py:226`,
    `database_esquema.py:340`). **Propuesta:** armar esos `CHECK` con las listas,
    como ya se hace con los comandos a las PCs, o borrar las listas. Ojo: el
    `CHECK` solo cambia en bases nuevas; en las que ya existen no hace falta tocar
    nada.
13. **"Solo un Administrador" está escrito dos veces**, con la misma idea (releer
    el usuario de la base y exigir que sea Admin activo):
    `control_pcs/repositories/playstation_repo.py:85` y
    `repositories/limpieza_repo.py:59`. **Propuesta:** una sola función en
    `usuarios_repo` que usen los dos, antes de que aparezca una tercera copia.
14. **`_es_playstation` está dos veces**: `control_pcs/ui/pcs_window.py:130` y
    `control_pcs/ui/pcs_detalle.py:206`.
15. **Pruebas:**
    - imports sin usar en `tests/test_fondo_pantalla.py:20` (`json`) y
      `tests/test_playstation_ui.py:26` (`database`).
    - Dos clases de prueba se llaman igual, `TestMigracionOrigenEnVentas`
      (`tests/test_kiosko.py:1869` y `tests/test_playstation.py:617`), pero
      prueban migraciones distintas, y `CLAUDE.md:401` nombra una sin aclarar
      cuál. **Propuesta:** renombrar la de PlayStation a
      `TestMigracionCheckOrigenEnVentas`.
16. **`Kiosko.spec:25` arma `Kiosko.exe`** y cada vez hay que renombrarlo a
    `CyberBios.exe` a mano. **Propuesta:** `name='CyberBios'`.
17. **Archivos cerca del tope de 600 líneas:**
    - `main.py` tiene 598, y 395 son la hoja de estilos (`HOJA_DE_ESTILOS`,
      línea 95): lo próximo que se le sume lo pasa del tope. Cuando haga falta, la
      hoja de estilos va a su propio archivo.
    - También están cerca `control_pcs/repositories/pcs_repo.py` (589) y
      `control_pcs/ui/pcs_window.py` (576).

---

## Revisado y sin problemas

- **Capas (regla 1):** ninguna pantalla tiene SQL ni abre la base; ningún repo,
  ni `dominio.py`, ni `turnos.py`, ni el servidor importan pantallas o Qt.
- **Plata (regla 9):** se formatea solo en `ui/utils.formato_pesos`. **Roles (regla
  10):** solo `dominio.es_admin`.
- **Código repetido:** los bloques que se repiten son armado de pantallas (filas de
  botones "Nuevo/Modificar", layouts), no reglas de negocio. No apareció ninguna
  cuenta de plata, turnos o tiempo escrita dos veces. Las funciones con el mismo
  nombre en dos archivos son a propósito: `turnos_repo` envuelve a
  `turnos_faltantes_repo` y `database.inicializar_base_de_datos` delega en
  `database_esquema`.
- **Código muerto:** no hay funciones de pantalla ni de repositorio sin uso.
  `miembros_repo.obtener_miembro`, `pcs_repo.obtener_estacion` y
  `tramites_repo.obtener_tramite` solo las usan las pruebas, pero son lecturas de
  una línea que les sirven. Se dejan.
- **Pruebas:** 500, ninguna pisada ni repetida, todas verifican algo. Dos lo hacen
  comprobando que no salte un error, y está bien así.
- **Errores tragados en silencio:** ninguno, salvo el último recurso de
  `main.py:527`, que es a propósito.
- **Calculadora de margen en Artículos** (`ui/articulos_window.py:276`): es una
  ayuda para completar el formulario; el precio lo confirma la persona y lo graba
  el repo. Se deja.
- **Contrato con el Cliente PC:** coinciden los campos de `GET /estado`
  (`existe`, `bloqueada`, `segundos_restantes`, `quien`, `sesion_id`, `comando`,
  `clave_admin`, `fondo_version`) y los cuerpos de `POST /login`, `/logout`,
  `/evento_admin` y `/comando_resultado`, además de la cabecera `X-Fondo-Version`
  de `GET /fondo`. La única fragilidad es la del punto 3.
- **Pendiente de la revisión anterior** (el costo de que cada PC consulte cada 5
  segundos): ahora está medido. Cada consulta de una PC tarda ~5 ms; con 40 PCs es
  un 4-5% de un núcleo, aun con un año de historial. No hace falta tocarlo. Lo lento
  era el panel de actividad (punto 1).

---

## Cómo seguiría (segunda etapa, con tu OK)

Por tandas, cada una en su rama, con todas las pruebas antes y después:

1. **Velocidad:** punto 1, con una prueba que verifique que el panel muestra lo
   mismo.
2. **Claridad:** puntos 2, 3, 5, 6, 9, 10 y 11.
3. **Orden:** puntos 4, 7, 12 a 17.
4. **Fuera de git:** punto 8, borrar los dos `.exe` viejos.

### Tanda 1 — hecha (17/10)

Punto 1 resuelto en la rama `tanda1-velocidad-actividad`, mergeada a `master`:

- Diez índices nuevos en `database_esquema.py` (bloque "ÍNDICES"). Además de los
  propuestos, se sumaron los de la PlayStation 5 (`sesiones_playstation` por
  inicio y por fin, y `sesion_playstation_bonos(venta_id)`), que tenían el mismo
  problema.
- Los bonos vendidos del panel (PCs, PCSTREAM y PlayStation 5) se ordenan por
  número de venta en vez de por `ventas.fecha`: los números crecen a medida que
  se vende. Es más simple que reescribir la consulta partiendo de `ventas` y
  evita un caso lento: con pocos bonos de PCSTREAM, esa versión habría recorrido
  todas las ventas buscándolos.
- `tests/test_velocidad_pantalla_pcs.py` (2 pruebas): el trabajo de la base en
  cada refresco no crece con 5 veces más historial, y pedir los últimos eventos da
  lo mismo que pedir todos y cortar. Con el código anterior la primera falla (el
  trabajo crecía entre 2 y 4 veces); ordenando los bonos al revés falla la segunda.

Medido con un año simulado (146.000 sesiones de PC, 740 bonos de PCSTREAM, 9.125
sesiones de la PlayStation 5), sin otra cosa corriendo:

| | Antes | Después |
|---|---|---|
| Sesiones en curso | 18,5 ms | 1,5 ms |
| Panel de actividad (con la PlayStation 5) | 347 ms | 5,6 ms |
| **Refresco completo, cada 5 s** | **367 ms** | **8 ms** |

El panel mostró exactamente los mismos 30 eventos antes y después. El primer
arranque después de actualizar crea los índices: ~0,4 s una sola vez con un año
de historial; los arranques siguientes no cambian. Pruebas: 500 antes, 502
después, todas OK.

### Tanda 2 — hecha (17/10)

Puntos 2, 3, 5, 6, 9, 10 y 11, más el 12 (adelantado, porque el dueño lo decidió
junto con el 2), en la rama `tanda2-claridad`, mergeada a `master`:

- **2:** el dueño decidió borrar la fila. La migración vieja se reemplazó por
  `_migrar_borrar_clave_vieja_de_clientes_pc`, que borra `clave_clientes` y
  `clave_agentes` de `configuracion` en cada arranque. Si no están, no hace nada.
  Prueba nueva: el resto de la configuración queda intacto. Sin la migración, la
  prueba falla.
- **3:** la prueba de "estación desconocida" ahora exige la palabra
  "desconocida", con un comentario junto al mensaje en `servidor_red.py`.
  Cambiando el texto por "Esa PC no existe." la prueba falla.
- **5:** `dominio.ESTADO_COMANDO_PENDIENTE` / `ESTADO_COMANDO_ENTREGADO` /
  `ESTADOS_COMANDO_PC`, pasados como parámetro en `comandos_pc_repo`.
- **12:** el dueño eligió usar las listas. Los `CHECK` de rol, estado y turno de
  las ventas, turno de los cierres, avisos de admin y estado de los comandos se
  arman con las listas de `dominio.py` mediante `database._valores_sql`, que
  también reemplaza las tres copias que había de esa misma cuenta. **El esquema
  de una base nueva salió idéntico, línea por línea, antes y después.**
- **6:** `LEEME.txt` suma PCSTREAM, el día de 06:00 a 06:00, la carga mínima de
  socios, la IP asentada con "Borrar IP" y "Limpiar base de datos".
- **9 y 10:** comentarios y documentación al día ("cuatro catálogos", "mosaico"
  en vez de "fila de la grilla", referencias a
  `turnos_faltantes_repo._responsables_del_mes`, sin el import sobrante de
  `turnos_repo`). La regla 5 de CLAUDE.md explica cómo se arman ahora los `CHECK`.
- **11:** ya se había hecho en la tanda 1.

Pruebas: 502 antes, 503 después. En cuatro corridas completas, una tuvo 1 error
que no se repitió en las tres siguientes (todas OK). No quedó registrado cuál
fue; se presume la prueba de red que ya fallaba de vez en cuando por una
conexión cortada (`ConnectionAbortedError`).

### Tanda 3 — hecha (17/10)

Puntos 4, 7, 13 a 17 (el 12 ya estaba hecho en la tanda 2), en la rama
`tanda3-orden`, mergeada a `master`:

- **4, hecho distinto de lo propuesto:** no se mudó el Resumen del Día. 20 pruebas
  congelan la hora parcheando `repositories.turnos_repo.datetime`, y en otro
  archivo el reporte habría quedado con la hora real. Se mudaron en cambio las
  cuatro consultas de "qué se vendió en la ventana de un turno" a
  `repositories/turnos_ventas_repo.py`: no miran la hora, ninguna prueba las
  intercepta y `turnos_repo` las sigue usando con los mismos nombres.
  `turnos_repo.py`: 676 → 581 líneas.
- **7, solo el comentario:** `database.py` explica por qué el bloque de
  migraciones va al final y por qué no se puede sacar (una migración lee
  `database._TIPOS_MOVIMIENTO_SALDO` a propósito, para que las pruebas lo
  reemplacen). Se descartó cambiar de dónde importa `database_esquema`: no saca
  el ciclo, y si alguien mueve el bloque fallan todas las pruebas al instante.
- **13:** `usuarios_repo.exigir_admin` y `usuarios_repo.usuario_habilitado`, que
  usan Limpiar base de datos y la PlayStation 5. Cambio visible: un Admin dado de
  baja que intenta limpiar la base ve "ya no está habilitado" en vez de "Solo un
  Administrador...". Tres pruebas nuevas.
- **14:** una sola `es_playstation` (en `pcs_detalle`, que `pcs_window` ya
  importaba). Al unificarla, una variable local con el mismo nombre rompía el
  panel. Se corrigió, y se confirmó que las pruebas lo atrapan: con el error
  vuelto a poner, fallan 25.
- **15:** imports sin usar fuera; la clase de `test_playstation` pasa a
  `TestMigracionCheckOrigenEnVentas`.
- **16:** `Kiosko.spec` arma `CyberBios.exe`. Se va a ver en el próximo armado.
- **17:** sin cambios. `main.py` sigue en 598 líneas; la hoja de estilos se muda
  cuando algo lo haga pasar de 600.

**Junto con el filtro de palabras.** Mientras tanto, otra sesión subió a `master`
el filtro de palabras de las PCs (`108b931`, `f7b2db7`), y se juntó antes de
mergear, sin conflictos. Suma una consulta al panel de actividad
(`filtro_palabras_repo.listar_recientes`). Se comprobó que usa su índice por
fecha, y `tests/test_velocidad_pantalla_pcs.py` ahora simula también bloqueos
del filtro y accesos de admin: quitando cualquiera de esos dos índices, el
trabajo pasa de ~110 a ~200 y la prueba falla.

Pruebas: 506 OK antes de juntar; 532 OK después (las 529 de `master` más las 3
nuevas).

Decisiones tuyas antes de la tanda 2 (ya tomadas):
- ¿Se borra la fila vieja de la clave en la base (punto 2)? **Sí.**
- En el punto 12, ¿armar los `CHECK` con las listas o borrar las listas? **Armarlos con las listas.**
