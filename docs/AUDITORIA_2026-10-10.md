# Auditoría de orden y robustez — 10 de octubre de 2026

Rama: `auditoria-orden-2026-10-10`. La base real y `data/` no se tocaron.
Antes de los cambios pasaban 328 tests. Después pasan 332 y abren Login y
ventana principal con Qt `offscreen` y una SQLite temporal. Las correcciones
se guardaron por tema en commits separados.

## Prioridad alta

| Hallazgo | Impacto en el kiosko | Resolución |
|---|---|---|
| Alta de artículo y marca nueva en dos pasos (`ui/articulos_window.py:283`, `repositories/articulos_repo.py:155`) | Si el código del artículo ya existía, la marca nueva podía quedar guardada sola. | La marca se crea dentro de la misma transacción que el artículo; un error deshace ambas cosas. Cubierto por `tests/test_articulos_atomicidad.py`. |
| Errores de la API de PCs descartados (`servidor_red.py:155` y otros manejadores) | Una PC podía dejar de comunicarse sin dejar una causa para diagnosticar en el mostrador. | El servidor registra fallos inesperados con contexto en `data/errores.log` mediante `errores.py:13`; conserva la respuesta de error prevista por el protocolo. |
| `Kiosko.spec` ignorado por `*.spec` (`.gitignore:6-7`) | Un checkout limpio podía carecer de la receta usada para armar el ejecutable. | Excepción explícita en `.gitignore` y archivo versionado. |

## Prioridad media

| Hallazgo | Impacto en el kiosko | Resolución |
|---|---|---|
| `database.py` tenía 1299 líneas (`database.py:253`) | Mezclaba conexiones, copias, claves, creación de tablas y migraciones; cada cambio era difícil de revisar. | Esquema en `database_esquema.py`, migraciones en `database_migraciones.py`, API y rutas configurables en `database.py`. Quedaron en 541, 459 y 355 líneas. Los tests de migración e idempotencia pasan. |
| `turnos_repo.py` y `pcs_repo.py` superaban las ~600 líneas (`repositories/turnos_repo.py:570`, `control_pcs/repositories/pcs_repo.py:37`) | Los temas nuevos seguían acumulándose en módulos que mezclaban responsabilidades. | Turnos vencidos en `repositories/turnos_faltantes_repo.py` y feed en `control_pcs/repositories/actividad_repo.py`, con API anterior conservada. Ahora tienen 575 y 580 líneas. |
| La consulta de una PC recorría todas las estaciones (`control_pcs/repositories/pcs_repo.py:249`) | Cada consulta del cliente hacía trabajo proporcional a toda la grilla. | Consulta directa de la estación pedida y cálculo compartido del estado. Cubierto por `tests/test_estado_pc.py`. |
| Reportes filtraban `date(ventas.fecha)` (`repositories/reportes_repo.py:44`) | Ese filtro impedía aprovechar `idx_ventas_fecha` al pedir un período; el costo crecía con el historial. | Rangos de fechas sobre la columna original. Se comprobó el plan de consulta con `EXPLAIN QUERY PLAN` y se añadieron pruebas de límites de fecha. |
| Literales de estado y saldo fuera de `dominio.py` (inventario abajo) | Un typo podía dejar una consulta sin filas o un movimiento mal clasificado, sin error visible. | Uso de constantes y parámetros SQL; los `CHECK` del esquema siguen definiendo los valores admitidos. |
| `CLAUDE.md` mezclaba reglas vigentes con cronología y tenía cifras viejas (`CLAUDE.md:142`, `CLAUDE.md:436`) | La guía podía inducir a buscar módulos o permisos que ya habían cambiado. | Reglas y estado actual compactados; historial íntegro en `docs/HISTORIAL.md`; README y LEEME actualizados. `AGENTS.md` quedó como guía corta que apunta a la fuente vigente. |

### Inventario de literales originales

Se verificaron **18 ocurrencias de código productivo** para los cinco valores
de la pista, fuera de `dominio.py` y `database.py` (en `master`, antes de esta
rama). Las líneas de tests que reproducen esquemas viejos son datos de prueba
y se conservaron.

| Archivo en `master` | Líneas | Valor y uso |
|---|---|---|
| `control_pcs/repositories/miembros_repo.py` | 184, 271, 347 | `CARGA` y `CONSUMO` al registrar o buscar saldo |
| `control_pcs/repositories/pcs_repo.py` | 200, 288, 297, 406, 413, 418, 469, 547, 553, 572 | `ACTIVA`, `FINALIZADA`, `CONSUMO`, `REINTEGRO` en sesiones y reintegros |
| `repositories/reportes_repo.py` | 314, 328 | `CARGA` en sumas para reportes |
| `control_pcs/ui/pcs_actividad.py` | 35, 37, 40 | `CARGA`, `CONSUMO`, `REINTEGRO` para mostrar el feed |

Una mención adicional de `CARGA` en `repositories/reportes_repo.py:263` es
un comentario de dominio y se dejó como texto explicativo.

## Prioridad baja y seguimiento

- `kiosko_launch.log` y `kiosko_launch_err.log` eran archivos locales vacíos,
  ignorados por Git. Se eliminaron; el registro útil de fallos está en
  `data/errores.log`.
- Cerca del umbral de 600 líneas están `control_pcs/ui/pcs_window.py` (546),
  `ui/caja_window.py` (495), `ui/articulos_window.py` (468) y
  `ui/reportes_window.py` (457). Conviene separarlos cuando aparezca un tema
  nuevo, manteniendo un archivo por pantalla o panel.
- No aparecieron SQL en `ui/` o `control_pcs/ui/`, importaciones de UI desde
  repositorios, comparaciones de permisos por rol en esas pantallas ni formatos
  de dinero dispersos: el formato visible está en `ui/utils.py:91`.
- No se confirmó código muerto con evidencia suficiente para eliminarlo.

## Pendiente de medición

El sondeo de PCs escribe la última conexión en cada pedido
(`servidor_red.py:192`, `control_pcs/repositories/pcs_repo.py:117`) y la grilla
se refresca cada 5 segundos (`control_pcs/ui/pcs_window.py:56`). Una reducción
de escrituras o de consultas del feed exige medir carga y conservar la
precisión del indicador «en línea». No se cambió ese contrato sin datos de
uso. Tampoco se cambió el modelo de bonos, los dos árboles de carpetas ni
ninguna decisión de negocio.

La receta `Kiosko.spec` quedó versionada, pero no se generó ni probó un
ejecutable en esta pasada; esa validación queda para el próximo empaquetado.

## Verificación

`python -m unittest discover tests`: **332 tests, OK**.

Login y ventana principal: **abren y cierran correctamente** con
`QT_QPA_PLATFORM=offscreen` y base temporal. No se inició el programa sobre
`data/kiosko.db`.
