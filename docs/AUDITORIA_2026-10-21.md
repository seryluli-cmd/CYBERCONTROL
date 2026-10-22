# Revisión de limpieza — 21 de octubre de 2026

Alcance: los 72 commits desde la revisión anterior (`5cf2c1e`, 17/10) y un repaso
del resto. **Fase 1: solo informe, sin tocar código.**

Cómo se buscó: ruff 0.17 (imports y variables sin usar), vulture 2.16 (funciones sin
uso), grep de cada candidato (código, pruebas, lista blanca de admin remoto, CLAUDE.md,
README, LEEME), `git log -p --all` para el historial y una medición con una base
temporal de un año simulado (146.000 sesiones, 40 PCs; nunca `data/`).

Línea de base: **1064 pruebas, todas OK** (10 min 50 s).

> **Al aplicarlo (22/10):** el informe se hizo sobre `b9af98e`. Antes de tocar nada
> se volvió a verificar sobre `9239e28`, con 4 commits más (los reinicios de las PCs y
> "TIEMPO AGOTADO"; la suite pasó a 1107 pruebas). Ruff da lo mismo. Vulture suma
> `reinicios_pc_repo.fue_pedido`, que va a B. Dos puntos de A cambiaron al revisarlos
> de nuevo: el 4 (lo usaban 3 pruebas) y el 5 (se queda). Ver cada fila.

**En una línea:** el código está limpio. Lo que sobra son restos chicos de tres
cambios (el cobro nuevo del 18/10, el `permiso_control_pcs` vaciado el 19/10 y las
marcas que se graban con el artículo). Nunca hubo binarios, bases ni claves en git.
No hay ninguna optimización que valga la pena: está todo medido abajo.

---

## A. Seguro de borrar o corregir (riesgo bajo)

### Código sin uso

| # | Dónde | Qué es | Por qué sobra | Cómo se confirmó |
|---|---|---|---|---|
| 1 | `dominio.py:79` | `nombre_metodo()` | Nadie la llama desde `a59c404` (18/10): era para la tabla de pagos del cobro viejo. CLAUDE.md:212 la sigue nombrando como "punto único". | vulture; grep: 0 usos en código y pruebas |
| 2 | `dominio.py:263` + `tests/test_kiosko.py:123` | `pagos_netos_de_vuelto()` y `TestPagosNetosDeVuelto` (4 pruebas) | El cobro dejó de usarla en `a59c404`. Hoy descuenta el vuelto `dominio.cuenta_del_cobro`, que tiene sus propias pruebas ("en la caja queda el total", `test_dialogo_pago.py:54`). La docstring de la prueba dice que la usa `DialogoPago`, y ya no es así. `dominio.py:318` la nombra en un comentario. | grep: solo la usan esas 4 pruebas |
| 3 | `repositories/articulos_repo.py:49` | `crear_marca()` | 0 usos: desde `f0b2587` las marcas se graban junto con el artículo. No está en la lista blanca. La docstring de `crear_rubro` (`:62`) dice "Igual que crear_marca". | vulture; grep |
| 4 | `control_pcs/repositories/playstation_repo.py:56-59` | `PERMISO_OPERAR = "permiso_control_pcs"` y su comentario | Nadie lo importa desde `03ee5b6` (19/10). El comentario lo justifica porque lo usa `usuarios_repo`, pero `usuarios_repo` escribe el texto aparte y no lo importa. **Corrección al aplicar:** 3 pruebas (`test_playstation.py:63, 142`, `test_playstation_ui.py:63`) lo usaban para marcarle el permiso a una empleada; pasan a escribir `"permiso_control_pcs"`, como ya hacían `test_barra_para_todos` y `test_detalle_dia`. | vulture; grep (el primer grep no miró `tests/`) |
| ~~5~~ | `control_pcs/repositories/comandos_pc_repo.py:60-62` | `TIPO_DESCONGELAR`, `TIPO_CONGELAR`, `TIPO_ESTADO_CONGELADO` | **Corrección al aplicar: se queda (pasa a B).** `test_control_pcs.py:1014` recorre con `vars()` todos los `TIPO_*` del repo y los compara con `dominio.TIPOS_COMANDO_PC`. Sin estos 3, esa prueba falla y se pierde el control de que el repo y el CHECK de la base tengan los mismos tipos. Vulture no ve el `vars()`. | grep de `vars(`/`getattr(` antes de borrar |
| 6 | pruebas | imports y variables sin usar: `test_admin_remoto.py:32` (`timedelta`), `test_reservas.py:28` (`articulos_repo`), `test_control_pcs.py:461, 671, 1446, 1447`, `test_kiosko.py:1077` | Sobran. En las variables solo se borra el nombre: la llamada queda porque crea datos para la prueba. | ruff F401/F841 |
| 7 | `control_pcs/repositories/pcs_repo.py:42` | import de `actividad_reciente` | **No sobra**: lo usan `pcs_actividad.py` y 7 pruebas como `pcs_repo.actividad_reciente`. Ruff lo marca igual. Propuesta: aclararlo con `# noqa: F401`, como ya hace `turnos_repo.py:39`. | grep |

### Comentarios y documentación que quedaron atrás

| # | Dónde | Qué dice | Qué es hoy |
|---|---|---|---|
| 8 | `LEEME.txt:42` (guía del mostrador) | "a los **15** minutos del fin del turno [...] la cierra solo" | **30** minutos desde `93e9858` (20/10): ese commit cambió el número en el programa y en README, pero no en LEEME. |
| 9 | `LEEME.txt:132-133` | "Operar la PlayStation y entrar a Miembros requiere el permiso «Operar PCs y Miembros»" | Cualquier operador desde el 19/10 (`13b8d9d`, `03ee5b6`). |
| 10 | `ui/main_window.py:25-28`, `:42-44`, `:565-567`; `control_pcs/repositories/bonos_miembro_repo.py:16`; `database_esquema.py:644-645` | Que `permiso_control_pcs` hace falta para la PlayStation 5 o para usar un bono | Ya no gobierna nada de eso (lo dicen bien CLAUDE.md y README:641). |
| 11 | `control_pcs/repositories/reservas_repo.py:311` | "`actualizar_estados` [...] La llama listar_reservas" | `listar_reservas` llama a `_pasar_las_vencidas` directo. `actualizar_estados` solo la usan las pruebas. |
| 12 | `CLAUDE.md:261` | `ui/pcs_aviso_reservas.py` | `control_pcs/ui/pcs_aviso_reservas.py` |
| 13 | `CLAUDE.md:212` | fila de `dominio.nombre_metodo` | Se va junto con el punto 1. Al final se actualiza el conteo de pruebas (`CLAUDE.md:880`). Al aplicar se sumó la fila de `playstation_repo` en CLAUDE.md, que todavía decía "se exige el permiso (`puede_operar`)": es el mismo tema del punto 10. |

---

## B. Dudoso: se deja, con el motivo

| Dónde | Qué es | Por qué se deja |
|---|---|---|
| `miembros_repo.autenticar_miembro` (`:247`), `lista_blanca.nombres_de_modulos` (`:145`), `reservas_repo.actualizar_estados` (`:310`) | Solo los usan las pruebas | El mismo criterio que la revisión del 17/10 aplicó con `obtener_miembro`, `obtener_estacion` y `obtener_tramite`: son envoltorios de 2 o 3 líneas que les sirven a las pruebas. |
| `reinicios_pc_repo.fue_pedido` (`:105`) | Solo la usa una prueba | Nueva, del 21/10 (después del informe): `cortes_pc_repo` pasó a usar `motivo_del_corte`, que dice además si fue el seguro de fin de sesión. Mismo criterio que la fila de arriba. |
| `comandos_pc_repo.TIPO_DESCONGELAR`, `TIPO_CONGELAR`, `TIPO_ESTADO_CONGELADO` | Atajos que no usa el código | Los usa una prueba con `vars()` (ver el punto 5 de A). |
| `actualizacion_cliente_repo.olvidar_reportes`, `admin_remoto.servidor._olvidar_todo`, `admin_remoto.cliente.desinstalar` | Ganchos para las pruebas | Están documentados así a propósito. |
| `database.py:321-349` (bloque de reexportes) | Ruff marca 29 "sin uso" | Son falsos: `database_esquema.py:12` los importa desde `database` y las pruebas los parchean. Cinco no los usa nadie de afuera (`_agregar_columna_si_falta`, `_reconstruir_tabla`, `_admite_todos_los_tipos`, `_COLUMNAS_MOVIMIENTOS_SALDO`, `_TIPOS_MOVIMIENTO_SALDO_ORIGINALES`), pero CLAUDE.md:289 documenta `database._reconstruir_tabla` y el bloque es frágil (ver el comentario de la revisión del 17/10). Ganar 5 líneas no vale el riesgo. |
| `dominio.EVENTO_ADMIN_CIERRE_CLIENTE` | El aviso del botón viejo "Cerrar software cliente" | Lo siguen mandando los Clientes PC sin actualizar: es protocolo y no se toca. |
| `dominio.MOVIMIENTO_IMPORTACION` y su filtro en `actividad_repo` | Lo que quedó de la importación de socios | Hay filas reales en la base del local (CLAUDE.md:384). |
| Avisos de vulture sobre las listas de `dominio.py` (`ROLES`, `ESTADOS_VENTA`, `ESTADOS_RESERVA`...) y sobre `do_GET`, `do_POST`, `log_message`, `paint` y `eventFilter` | — | Son falsos: las listas se usan dentro de los f-strings del esquema, y los métodos los llaman Qt y `http.server` por su nombre. |

**Restos que pediste revisar:**
- **Base cifrada (`dc97187`):** no quedó nada. `git diff f62f086 dc97187` sale vacío. No hay `sqlcipher`, `motor_sql.py` ni `clave_base.py`, y `requirements.txt` volvió a PySide6 + cryptography (esta última es para firmar el Cliente PC, no para la base).
- **Importación de socios (`51657a5`):** se borraron sus 3 archivos y no quedó código. Lo que queda es a propósito (fila anterior).
- **`permiso_control_pcs`:** los comentarios viejos están en los puntos 9 y 10. Lo que sigue haciendo la casilla se explica en E.1.
- **Limpiar base:** sigue como estaba. Ver E.2.

---

## C. Commits

- **Archivos que no deberían estar:** ninguno, en todo el historial (`git log --all
  --name-only`). Nunca entró un `.db`, `.exe`, `.log`, `build/`, `dist/`, `data/` ni
  `__pycache__`. El `.gitignore` cubre todo eso. El repo pesa 1,2 MB y ningún archivo
  pasa de 150 KB.
- **Claves:**
  - No hay claves privadas.
  - La clave fija de los Clientes PC **nunca** estuvo en este repo: se comparó contra
    `CLIENTE PC/configuracion.py` sin imprimirla.
  - La contraseña de ORDENAR Stock está solo como hash con sal, desde su primer commit.
  - No hay usuario ni clave de la carpeta de red de las copias: las pruebas usan
    `usuario_de_prueba`.
  - Lo demás son valores de prueba ("clave-de-prueba") y la clave **pública** de firma,
    que es pública a propósito.
- **Commits con cambios ajenos:** se revisó la lista de archivos de los 64 commits
  (sin contar merges). Coinciden con su título, salvo el ya conocido `b06fa23`, que
  `8c31f33` corrigió.
- **Ruido sin daño:** 10 commits seguidos de ajustes de diseño en `ui/caja_window.py`
  (`00491c0` a `fb3d0e0`). No se reescribe nada.
- **Rama remota `origin/mosaico-pcs`:** ya está entera en `master` (0 commits
  propios). Ver E.3.

---

## D. Optimización (medido)

Base temporal con un año simulado: 146.000 sesiones de 40 PCs, 9.000 de la
PlayStation 5 y 67 MB. 20 PCs en uso.

| Qué | Cada cuánto | Mediana | Conexiones a la base |
|---|---|---|---|
| Refresco de la pantalla de PCs (estado, consola, reservas, actividad) | 5 s | **11,9 ms** | 9 |
| Revisión de la caja (`estado_de_la_caja`) | 10 s | 1,0 ms | 1 |
| Consulta de una PC (`GET /estado`) | 5 s por PC | **14,4 ms** | 6,4 |
| 40 PCs consultando en el mismo instante | — | 1,16 s para atender a las 40 | 240 |

El historial no hace más lento nada: con 3.000 sesiones daba lo mismo. Los índices
del 17/10 siguen funcionando.

**Desglose de `GET /estado`:**
- 5,5 ms: `registrar_conexion`, la escritura de "última conexión". Es casi todo esperar
  al disco.
- 1,7 ms: el cartel de la reserva (nuevo, del 21/10).
- ~1 ms cada una: el estado, el próximo comando, la clave admin y el filtro.

**Comparación con la versión del 17/10, mismo instrumento y misma PC:** 9-11 ms
entonces y 13-16 ms hoy, unos 4 ms más por consulta. Es lo que sumaron la reconexión,
los cortes, la versión del cliente y la reserva. Los "~5 ms" anotados el 17/10 se
midieron de otra forma y no se comparan.

**Conclusión: no se cambia nada.** Con 40 PCs son unas 8 consultas por segundo, que
ocupan ~11% del tiempo y en su mayoría esperando al disco. La pantalla del mostrador
tarda 12 ms cada 5 s. Nadie lo nota. Se evaluó:
- **Juntar las lecturas de `GET /estado` en una sola conexión:** ahorraría ~4-5 ms por
  consulta, pero obliga a cambiar la firma de 8 funciones de repos. No se ve. Se
  descarta.
- **Modo WAL de SQLite:** la escritura bajaría a menos de 1 ms. Pero deja dos archivos
  más al lado de `kiosko.db` (`-wal`, `-shm`), y copiar `kiosko.db` solo, como se hace
  a mano al mover el programa, perdería lo último grabado. Para una base con plata, el
  riesgo pesa más que 5 ms que nadie ve. Se descarta.
- **La ráfaga de 40 PCs a la vez** solo pasaría si arrancan todas en el mismo segundo,
  y aun así se atienden en ~1 s, con consultas cada 5 s. No hace falta tocarla.

---

## E. Decisiones tuyas

1. **La casilla "Operar PCs y Miembros (asignar bonos, abrir con socio, cargar
   saldo)" de Usuarios ya no da ninguna de esas cosas.** Desde el 19/10 todo eso lo
   hace cualquier operador. Lo único que hace hoy es habilitar el botón "Admin
   Kiosko" a esa empleada, que lo abre y ve todos los botones en gris si no tiene
   otro permiso (`ui/main_window.py:119` y `:527`). Opciones: (a) dejarla, (b)
   cambiarle el texto, (c) sacarla de la lista (la columna de la base queda). Cambia
   lo que se ve, así que no entra en esta limpieza sin tu OK.
2. **"Limpiar base de datos" sigue en Configuración ADMIN.** El programa ya trabaja
   con plata real: cajas desde el 18/10 y socios desde el 19/10. Un clic de Admin
   borra todo el historial de ventas (con copia previa). **Recomiendo sacarlo ya.**
   Es un cambio visible: va aparte, si decís que sí.
3. **Rama `origin/mosaico-pcs` en GitHub:** ya está en `master`. ¿La borro?
4. **(Opcional) `main.py` tiene 825 líneas** y pasó el tope de 600 (regla 12). La
   revisión del 17/10 dejó dicho que la hoja de estilos (~400 líneas) se muda a su
   propio archivo cuando pase el tope. No cambia nada visible. Es orden, no código
   muerto: va como tanda aparte si querés.

---

## Cómo se aplicó (22/10, con el OK del dueño)

Tres tandas, cada una con la suite completa, revisando `git diff --stat`, con un
commit y push a `master`:

| Tanda | Commit | Qué | Pruebas |
|---|---|---|---|
| 1. Pruebas | `ae2d97e` | Punto 6, el `noqa` del punto 7 y este informe | 1107 OK |
| 2. Código muerto | `b86e826` | Puntos 1 a 4 (con `dominio.py:318` y `articulos_repo.py:62`). El 5 se quedó | 1103 OK |
| 3. Textos | (este commit) | Puntos 8 a 13, y la fila de `playstation_repo` en CLAUDE.md | 1103 OK sobre `b86e826`. Entra encima de `167c9b0` (otra sesión, +14 pruebas): 1117 |
| 4. Optimización | — | Ninguna (ver D) | — |

En total, 90 líneas menos en neto (125 borradas y 35 escritas, sin contar este
informe; 41 de las borradas son las 4 pruebas), sin ningún cambio en lo que se ve ni
en cómo funciona el programa. No se armó el .exe.

Mientras se aplicaba, otras sesiones trabajaban en la misma carpeta (la barra en
negrita y mayúscula; por qué una actualización del Cliente PC no se puso). Sus cambios
sin commitear quedaron fuera de estos commits: las tandas 2 y 3 se probaron y se
commitearon desde el índice de git (HEAD + solo estos cambios), en una copia aparte.
