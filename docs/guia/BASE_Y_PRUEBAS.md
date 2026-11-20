# Guía: Base de datos, usuarios, copias, .exe y pruebas

Parte de la guía de CYBERCONTROL. Lo que vale siempre (las 15 reglas y lo que no se
cambia sin que el dueño lo pida) está en [CLAUDE.md](../../CLAUDE.md); acá está lo de
esta área. Si cambiás algo de lo que dice esta guía, corregila en el mismo commit.

**Se cruza con:** todas: cualquier cambio que grabe algo pasa por acá. Para los orígenes de venta, [Ventas](VENTAS_Y_ARTICULOS.md).

## Puntos únicos de verdad (usalos, no los repitas)

| Función | Es el único lugar donde... |
|---|---|
| `dominio.es_admin(usuario)` | se pregunta si alguien es Administrador |
| `database.conexion_db()` | se abre una transacción contra la base. Todo lo que graba la abre así (con `get_connection`, que espera `ESPERA_BASE_OCUPADA_SEGUNDOS`, 30 s, si otra conexión la tiene ocupada; con la espera de fábrica de 5 s la venta fallaba con "database is locked") |
| `database.DATA_DIR` / `DB_PATH` | se resuelve dónde viven los datos (código vs `.exe`) |
| `database.hash_clave()` / `verificar_clave()` | se maneja una contraseña |
| `usuarios_repo.tiene_permiso(usuario, clave)` · `.es_encargado(usuario)` · `.PERMISOS_EMPLEADA` | se decide si alguien puede entrar a algo. Las casillas de Usuarios salen de `PERMISOS_EMPLEADA`: las de `PERMISOS_DE_ADMINISTRAR_KIOSKO` (con alguna, `es_encargado`: abre Administrar Kiosko) y `PERMISO_TAREAS_TURNO` (cargar, cambiar y borrar Tareas del Turno, 2026-11-20; no abre Administrar Kiosko). Un permiso nuevo es una fila ahí, su columna en el CREATE TABLE y en `database._migrar_columnas_permisos`; entra solo en la huella de la otra PC (`admin_remoto.lista_blanca.huella`), así que las dos copias necesitan el mismo .exe |
| `usuarios_repo.exigir_admin(usuario_id, para)` · `.exigir_permiso(usuario_id, clave, para)` · `.tiene_permiso_hoy(usuario_id, clave)` · `.usuario_habilitado(usuario_id)` | un repo exige que quien opera siga activo (y sea Admin, o tenga el permiso: Tareas del Turno usa `exigir_permiso`), releyéndolo de la base (un permiso sacado con la sesión abierta ya no sirve): un usuario dado de baja con la sesión abierta no puede seguir. Lo usan, entre otros, la PlayStation 5, ORDENAR Stock, ORDENAR SALDOS, la devolución de una reserva y anular una venta o una carga (`ventas_repo.exigir_admin_y_motivo_para_anular`, que además exige un motivo escrito) |
| `usuarios_repo._exigir_que_quede_otro_admin(conexion, usuario_id, que_se_quiere)` | se decide que siempre quede al menos un Administrador activo: `modificar_usuario` (al pasarlo a Empleada), `desactivar_usuario` y `borrar_usuario` lo llaman con el permiso de escritura ya tomado (`BEGIN IMMEDIATE`: dos Admins que se bajan a la vez, uno desde otra PC, no dejan cero) y rechazan con ValueError tocar al único. Sin Admin nadie vuelve a entrar a Usuarios, anular ventas ni usar ORDENAR Stock sin tocar la base a mano. Crear y Modificar también rechazan un nombre vacío, y Crear una clave vacía. No cambia quién puede hacer qué; "no te podés borrar a vos mismo" sigue en `ui/usuarios_window.py`. Ver `TestSiempreQuedaUnAdministrador` |
| `copias_repo.copia_automatica_si_corresponde()` · `.toca_copia(...)` · `.nombres_a_borrar(...)` · `.agregar_carpeta_extra(...)` | se decide cuándo se hace una copia de seguridad (después de cada Cierre de Turno y cada `HORAS_ENTRE_COPIAS`, con el programa abierto; lo corre el hilo de `iniciar_copias_automaticas`), cuántas quedan y en qué otras carpetas se guarda (otro disco, carpeta compartida de otra PC); pedido del dueño, 2026-10-19. La pantalla es `ui/copias_dialogo.py` (Usuarios > "Copias de Seguridad") |
| `database.revisar_copia(ruta)` · `copias_repo.aviso_de_copia_danada()` · `copias_repo.PASOS_PARA_VOLVER_A_UNA_COPIA` | se decide si una copia de la base está sana (`PRAGMA quick_check`; la usan la copia automática, "Hacer copia ahora" y la del pendrive), se lee si la última salió dañada (el cartel rojo de la barra de arriba) y se escriben los pasos para volver a una copia (el .txt al lado de las copias, la tecla de la pantalla de copias y LEEME.txt). Revisión general del 2026-11-16, mejora 3 |
| `errores.registrar_error(excepcion, contexto)` | la UI y el servidor guardan fallos inesperados en `data/errores.log` sin depender de Qt |
| `database._reconstruir_tabla(...)` · `_admite_todos_los_tipos(lista)` | se reconstruye una tabla para cambiar un CHECK/REFERENCES, y se decide si un CHECK de tipos ya está al día |
| `database._sql_tabla_ventas(...)` · `_migrar_check_origen_en_ventas(...)` | se escribe el CREATE de `ventas` (el CHECK de `origen` sale de `dominio.ORIGENES_VENTA`) y se reconstruye una base vieja SIN romper las tablas que la referencian (ver "Trampas conocidas") |

Si necesitás uno de esos datos, **llamá a la función existente**.

## Trampas conocidas (no las rompas sin entenderlas)

- **El `.exe` empaquetado resuelve las rutas distinto.** Con PyInstaller
  `__file__` apunta a una carpeta temporal que se borra en cada arranque;
  por eso `BASE_DIR` usa `sys.executable` si está `frozen`. Si guardás un
  archivo nuevo, hacelo bajo `DATA_DIR`, nunca al lado de un `.py`.
- **El login es por nombre y exige nombres únicos entre usuarios activos.**
  Dos "Matías" activos romperían el login.
- **Las claves están hasheadas con salt, pero esto no es un sistema
  seguro.** Cualquiera con acceso al archivo `data/kiosko.db` lee y
  modifica todo. No le prometas al usuario que esto protege datos.
- **Reconstruir `ventas` no se hace con `_reconstruir_tabla`.** Esa función
  renombra la tabla vieja primero, y SQLite (desde 3.26) re-apunta a la renombrada
  todas las claves foráneas de las tablas hijas (`venta_detalle`, `venta_pagos`,
  `sesion_bonos`, `tramites_venta`, `movimientos_saldo_miembro`,
  `sesion_playstation_bonos`, `ventas_caja`): al borrarla, quedarían apuntando a una
  tabla que ya no existe. Para una tabla MADRE el orden es otro: crear `<tabla>_nueva`, copiar,
  borrar la vieja y recién ahí renombrar, con las claves foráneas apagadas y todo
  en UNA transacción — ver `_migrar_check_origen_en_ventas` y
  `TestMigracionCheckOrigenEnVentas` (en tests/test_playstation.py).
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
  crea la de un disco de esta PC); (7) cada copia se revisa con
  `database.revisar_copia` (`PRAGMA quick_check`, 0,3 s con 80 MB) ANTES de
  renombrarla (revisión general del 2026-11-16, mejora 3): la Online Backup API copia
  una página dañada tal cual y sin error, así que una copia dañada (`CopiaDanada`) no
  se guarda, no viaja ni borra las de antes, y la barra de arriba avisa en rojo
  (`MainWindow._mostrar_aviso_de_las_copias`) hasta que una sale bien. El detalle de
  SQLite va solo al log: con el mismo daño no da siempre el mismo texto; (8) los pasos
  para volver a una copia (`PASOS_PARA_VOLVER_A_UNA_COPIA`) quedan en
  `COMO_VOLVER_A_UNA_COPIA.txt` al lado de las copias de cada carpeta (LEEME.txt no
  viaja con el .exe) y LEEME.txt los repite tal cual (una prueba lo vigila). El paso
  que importa: mover `kiosko.db` Y `kiosko.db-journal` antes de poner la copia (medido:
  con el journal de un corte de luz al lado, la copia queda "malformed"). La pantalla lee lo que pasó de `_estado`, en
  memoria, y no mira las carpetas: una de red apagada la congelaría.
- **Las pruebas nunca tocan `data\` del proyecto ni crean la base en cada prueba**
  (revisión general del 2026-11-16). `tests/base.py` apunta `database.DATA_DIR` a
  una carpeta temporal apenas se importa y, al terminar cada prueba, cierra
  (`close()`) las `MainWindow` que sigan abiertas: con `deleteLater` solo, el reloj
  de la caja seguía andando y podía grabar un cierre forzoso en la base que
  hubiera en `data\`. La base de cada prueba es la copia de una plantilla armada una vez por
  proceso con el mismo `inicializar_base_de_datos()`: una prueba de migración arma
  su tabla vieja encima, como siempre. Una prueba que cierra un turno y enseguida
  vende llama a `base.esperar_que_avance_el_reloj()`: en Windows `datetime.now()`
  avanza a saltos de hasta 16 ms y la venta quedaba con la misma hora del cierre.
