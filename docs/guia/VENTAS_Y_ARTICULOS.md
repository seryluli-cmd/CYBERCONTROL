# Guía: Ventas, cobro, plata y artículos

Parte de la guía de CYBERCONTROL. Lo que vale siempre (las 15 reglas y lo que no se
cambia sin que el dueño lo pida) está en [CLAUDE.md](../../CLAUDE.md); acá está lo de
esta área. Si cambiás algo de lo que dice esta guía, corregila en el mismo commit.

**Se cruza con:** [Turnos y caja](TURNOS_Y_CAJA.md) (un origen de venta nuevo toca la caja), [PCs y bonos](PCS_Y_BONOS.md) (los bonos también se cobran) y [Base](BASE_Y_PRUEBAS.md) (el CHECK de `ventas.origen`).

## Puntos únicos de verdad (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `ventas_repo.subtotal_linea(linea)` | se calcula lo que se cobra por un renglón |
| `ventas_repo.total_carrito(lineas)` | se suma el total de una venta en curso |
| `ventas_repo._grabar_venta_kiosko(...)` | se graba una venta de kiosko sobre una conexión abierta (`confirmar_venta`, `impresiones_repo.cobrar_impresiones` y el kiosko de `cuentas_pc_repo.cobrar`): el único INSERT en `venta_detalle`, el único descuento de stock por una venta y donde se revisa (`_revisar_que_los_pagos_sumen_el_total`) que los pagos (netos de vuelto, ninguno negativo) sumen el total, con un centavo de tolerancia (`DIFERENCIA_MAXIMA_DE_PAGOS`); si no, no graba nada. `registrar_venta_sin_detalle` (bonos, cargas, PlayStation, trámites, reservas, Cuenta de la PC) hace la misma revisión desde la revisión general del 2026-11-16. Ver `TestLosPagosSumanElTotal` de `test_kiosko` y de `test_candados_de_plata` |
| `dominio.cuenta_del_cobro(total, efectivo, digital, paga_con)` · `.lo_que_falta_para(total, monto)` | se calcula el cobro: la parte en efectivo y la digital, el billete que da el cliente, el vuelto, lo que falta y los pagos que quedan en la caja (netos de vuelto); y lo que completa el otro medio al escribir en uno |
| `ui.dialogo_pago.cobrar(parent, monto)` | se cobra todo lo que no es una venta de kiosko con la ventana de cobro de Ventas (medio de pago, reparto y vuelto): el bono de PC, PCSTREAM o PlayStation 5 del botón "Cobrar" de Control de PCs, la carga de saldo de un socio y un trámite. Devuelve los pagos netos de vuelto, o None si se canceló |
| `ventas_repo.registrar_venta_sin_detalle(...)` | se arma una venta sin artículo real de por medio (bono de PC, carga de saldo); los pagos tienen que sumar justo el total (la devolución de una reserva va en negativo, con sus pagos en negativo) |
| `ventas_repo._exigir_precio_de_lista(conexion, usuario_id, lineas)` | se decide si un renglón puede ir a otro precio que el de la lista: solo si vende un Administrador activo; si no, PermissionError con el precio de lista. La llaman `confirmar_venta` y `cuentas_pc_repo.anotar_articulos` (revisión general del 2026-11-16). Ver `TestElPrecioDeLista` |
| `ventas_repo._exigir_que_no_sea_carga_ni_bono(conexion, venta_id, tambien_cargas=True)` | se decide qué venta NO se anula como venta común: una carga de saldo va por `miembros_repo.anular_carga` y un bono que no salió de una reserva por `anular_bono_repo.anular_bono`, que también sacan el tiempo. La llaman `anular_venta` y, sin las cargas, `anular_carga` (la misma elección que Consulta de Ventas). Ver `TestAnularVentaNoEsParaCargasNiBonos` |
| `dominio.CODIGO_ARTICULO_IMPRESIONES` | se decide qué artículo de kiosko es "Impresiones" (el código "4" en la base del dueño; hasta el 2026-10-19 el programa buscaba el "1", el de la base anterior, y las impresiones salían en $0), para mostrarlo como renglón propio en Reportes, Caja y Cierre de Turno; en el Ranking de Ventas, desde el 2026-11-19, con su propia categoría (`reportes_repo.categoria_a_la_vista`; ranking_ventas la sigue dando como Kiosko) |
| `impresiones_repo.cobrar_impresiones(...)` · `.articulo_impresiones()` | se cobran impresiones desde el botón de la barra (pedido del dueño, 2026-10-19): venta de kiosko común del artículo, con el precio leído en la misma transacción (`ventas_repo._grabar_venta_kiosko`, el núcleo de `confirmar_venta`) |
| `tramites_repo.registrar_tramite(...)` | se cobra un trámite de mostrador (monto libre): venta KIOSKO sin detalle + vínculo en `tramites_venta` |
| `dominio.texto_pesos(monto)` · `ui.utils.formato_pesos(monto)` | un monto se convierte en texto: `"$ 1.500"`, `"$ 30.000"`, con el punto de los miles y SIN centavos (pedido del dueño 2026-10-26: todos los precios son en miles y `"$ 1.500,00"` o `"1500,00"` se leían mal); con centavos solo si los tiene de verdad (`"$ 1.234,50"`, un reparto en proporción), para que una suma de la caja no parezca no cerrar. Los repos lo usan en sus mensajes; la pantalla, con `formato_pesos` |
| `ui.utils.CampoPesos` · `ui.utils.pedir_pesos(parent, titulo, texto, valor)` | se escribe un monto: el campo se ve `"$ 1.500"` igual que `formato_pesos`, acepta escribirlo con o sin el punto (la coma es de los centavos) y `pedir_pesos` es el `getDouble` con ese campo. Ninguna pantalla arma un `QDoubleSpinBox()` ni un `getDouble` suelto para plata (`tests/test_formato_pesos.py` lo vigila). Excel muestra los montos con `"$" #,##0` (el número de la celda sigue exacto) |
| `dominio.precio_con_margen(costo, porcentaje)` · `.costo_sin_margen(precio_venta, porcentaje)` · `.porcentaje_de_ganancia(costo, precio_venta)` · `.ganancia_por_unidad(costo, precio_venta)` · `.MARGEN_POR_DEFECTO` · `.bajo_el_minimo(stock, minimo)` · `.texto_cantidad(n)` | se hacen las cuentas de Modificar artículo (`ui/dialogo_articulo.py`, la maqueta B que eligió el dueño el 2026-10-31 para el kiosko y pidió también acá: la tarjeta oscura con el precio de venta grande y la calculadora COSTO, GANANCIA %, VENTA, cada uno con su "＝ Calcular" que lo saca de los otros dos). El margen va como `round(costo * (1 + %/100), 2)` y su vuelta (escrito como `costo + costo * %/100` da a veces otro centavo); el % que se le gana sale con dos decimales para que vuelva a dar la misma venta ($ 20 y $ 200 dan 900%); debajo del precio grande va solo lo que se gana por unidad en pesos (el % sobre la venta confundía al dueño y se sacó). El % arranca en 80. El stock actual va arriba con el punto de los miles, en rojo bajo el mínimo. Los campos de números no tienen las flechitas de subir y bajar. Son puras a propósito: Artículos se abre desde otra PC |
| `articulos_repo.ajustar_stock(usuario_id, codigo, stock_nuevo, clave)` · `.comprobar_clave_para_ordenar_stock(...)` | se corrige el stock de un artículo a mano (ORDENAR Stock, pedido del dueño 2026-10-20): solo Admin activo con la contraseña de `CLAVE_ORDENAR_STOCK`, entero de 0 para arriba, anotado en `ajustes_stock` y visible en Movimientos. Es la única forma de mover el stock aparte de Compras y Ventas |
| `articulos_repo.cambiar_codigo(usuario_id, codigo_actual, codigo_nuevo, clave)` · `._TABLAS_CON_CODIGO_DE_ARTICULO` | se corrige el código de un artículo (ORDENAR Stock, doble clic en el código; pedido del dueño 2026-10-20): mismo permiso y contraseña que el stock; las ventas, compras y ajustes de antes pasan al código nuevo en la misma transacción, anotado en `cambios_codigo` y en Movimientos ("cambio de código A → B"). Es el único lugar donde se cambia un código (ver "Trampas conocidas") |
| `articulos_repo.crear_marca` · `.renombrar_marca` · `.juntar_marcas` · `.borrar_marca` (usuario_id primero) | se corrige el catálogo de marcas: SOLO el Admin (pedido del dueño 2026-10-23; `exigir_admin(..., "editar las marcas")`, y el botón "Gestionar Marcas" de Artículos solo lo ve el Admin, `ui/articulos_window.DialogoGestionMarcas`). Renombrar con el nombre de otra marca pregunta si juntarlas (pasa los artículos y borra la vieja); borrar una con artículos se rechaza. Una marca nueva al cargar un artículo (`_marca_para_guardar`) sigue libre para quien entra a Artículos |
| `articulos_repo.listar_para_control_de_stock(usuario_id)` | se arma la lista de CONTROL DE STOCK (pedido del dueño 2026-10-24; botón de debajo del mosaico, a la derecha de APAGAR, `ui/control_stock_window.py`): los artículos con stock de 1 para arriba, de la A a la Z, para imprimirla y contar el estante (la hoja trae una columna "Contado" vacía). El botón lo ven todos y solo el Admin lo abre (con otro operador no hace nada, como Admin Kiosko); el repo vuelve a exigir Admin. Solo muestra: corregir es de ORDENAR Stock |
| `dominio.orden_de_codigo(codigo)` | se ordenan códigos de artículo de menor a mayor como números (1, 2, 10 y no 1, 10, 2; los que tienen letras al final): F5 Código, pedido del dueño 2026-10-25 |
| `ui.articulos_tabla.llenar_tabla_de_articulos(...)` · `.poner_stock(...)` | se arma la grilla de artículos (columnas y stock en rojo bajo el mínimo): la usan Artículos y ORDENAR Stock |
| `ui.buscar_articulo.avisar_codigo_no_encontrado(ventana, codigo)` | se avisa en Ventas y Compras que lo escaneado no es ningún artículo, con cuántos dígitos llegaron (para comparar con el código cargado) |
| `ui.buscar_articulo.armar_botones_de_busqueda(ventana, ...)` | se arman los botones F5/F6/F7 y sus atajos (Compras) |
| `ui.venta_buscador.BuscadorDeLaVenta` · `articulos_repo.buscar_para_vender` | Ventas busca en SU MISMO campo y el operador no elige nada (pedido del dueño, 2026-11-09): sin letras es un código de barras; con alguna letra, nombre O marca, cada palabra en cualquier orden, con LIMIT 100. Lo encontrado sale en una lista que flota debajo del campo (flechas, Enter o clic; arranca marcado el primero); sin nada en la lista, Enter busca el código exacto. Esc borra lo escrito. Ver `tests/test_venta_buscar_en_el_campo.py` |
| `ui.detalle_venta.VentanaConDetalleDeVenta` | lista de ventas + artículos de la elegida (Consulta de Ventas y Detalle de un cierre) |

Si necesitás uno de esos datos, **llamá a la función existente**.

## Trampas conocidas (no las rompas sin entenderlas)

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
  graba tal cual en `ventas.total`, y los pagos tienen que sumarlo justo: llegan
  netos de vuelto (`ui.dialogo_pago.cobrar`, `dominio.repartir_pagos`). Antes cada
  repo lo revisaba por su cuenta y aceptaba pagos de más: un trámite de $ 1.000
  con $ 5.000 dejaba a la Caja esperando $ 4.000 que no estaban (revisión general
  del 2026-11-16). Una prueba que paga "lo que sea" ya no anda: pagá el precio.
- **Sumar un origen de venta nuevo toca la caja, no solo `dominio.py`.** Si un
  origen no figura en `turnos_repo._PREFIJO_COLUMNAS_POR_ORIGEN` (y en las
  columnas de `cierres_turno`), su plata desaparece del efectivo esperado en el
  cajón sin ningún error visible — el dueño usa este desglose para auditar
  faltantes. El test `TestCadaOrigenSumaEnLaCaja` lo atrapa. `ventas.origen` tiene
  un CHECK: agregar un origen exige que `database._migrar_check_origen_en_ventas`
  reconstruya la tabla (corre sola al arrancar, dejando una copia en
  `data/backups/antes_de_*.db`).
- **Un trámite es un servicio que se cobra, no el pago de una boleta.** Lo que
  se tipea en "Trámites" es lo que el local cobra por hacerle el trámite al
  cliente (imprimir la boleta de luz, un trámite online, sacar un turno...);
  la boleta en sí nunca pasa por la caja, así que no se la modela como una
  entrada y salida de plata de terceros. No tiene stock ni costo: es ganancia
  pura (la hace un empleado). Ver `tramites_repo`.
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
- **Los candados de la plata los pone el repo, no la pantalla** (revisión general
  del 2026-11-16, mejora 2; regla 3):
  - `pcs_repo.asignar_bono` y `playstation_repo.vender_bono` toman `BEGIN IMMEDIATE`
    al empezar, como las otras operaciones que tocan una sesión, y el UPDATE de la
    sesión lleva `AND estado = ?`. Sin eso, si el socio cerraba desde su PC o la PC
    volvía de un corte en ese instante, el bono se cobraba sobre una sesión cerrada
    o pisaba la corrección de "gana el menor".
  - La base no deja dos sesiones ACTIVAS en una PC: índice único parcial
    `database.INDICE_UNA_SESION_ACTIVA_POR_PC`. Si al arrancar alguna PC ya tiene dos,
    no se crea, se anota en `errores.log` y se reintenta en el próximo arranque
    (`database_migraciones._crear_indice_una_sesion_activa_por_pc`). Por el índice, el
    intercambio de `trasladar_sesion` pasa la sesión del destino a FINALIZADA mientras
    mueve las dos y la vuelve a ACTIVA: SQLite revisa el índice fila por fila.
  - Un precio distinto al de la lista, solo si vende un Admin
    (`ventas_repo._exigir_precio_de_lista`). Las pruebas que arman ventas con
    cualquier monto llaman antes a `base.poner_precio_de_lista`.
  - `anular_venta` no anula cargas ni bonos, y `anular_carga` no anula bonos
    (`ventas_repo._exigir_que_no_sea_carga_ni_bono`).
