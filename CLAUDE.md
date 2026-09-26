# Kiosko — reglas del proyecto

Este sistema administra un negocio real: un Cyber. No es un proyecto de
prueba. Prioridad siempre en este orden: **1) no romper datos ni plata
real, 2) prolijidad, 3) escalabilidad, 4) velocidad de entrega.** Si un
cambio rápido pone en riesgo el punto 1 o 2, no se hace rápido.

## Qué es Kiosko

App de escritorio Windows (Python + PySide6 + SQLite, sin servidor,
sin internet) que factura:
- **Kiosko**: venta de productos de almacén/kiosko (stock, compras, caja).
- **Control de PCs**: alquiler de PCs del local por tiempo. Se cobra
  vendiendo **bonos de tiempo** prearmados (ej. "3 horas" = 180 min /
  $X, en fracciones de 30 min) — nunca por hora libre ni minuto suelto.
  Una PC sin bono activo asignado queda bloqueada. Ver
  `repositories/pcs_repo.py`.
- A futuro (todavía no existe): un agente instalado en cada PC cliente
  que bloquea la pantalla según el estado que reporta este programa.
  Va a necesitar sumar networking, algo que hoy el proyecto no tiene
  (`requirements.txt` solo declara `PySide6`).

Para el detalle completo de tablas y pantallas, leer `README.md` antes
de tocar algo grande — es más largo y más específico que esto.

## Arquitectura en capas (no negociable)

```
ui/            → pantallas (PySide6). Nunca ejecuta SQL directo.
repositories/  → toda la lógica de negocio y el SQL. Un archivo por
                 dominio (articulos_repo.py, ventas_repo.py, pcs_repo.py...).
database.py    → esquema, conexión, utilidades de fecha/turno compartidas.
```

- Los catálogos auxiliares de una entidad viven en el mismo archivo que
  la entidad principal (ej. `marcas`/`rubros` dentro de
  `articulos_repo.py`, `estaciones`/`bonos_tiempo` dentro de
  `pcs_repo.py`) — no se crea un archivo de repo por cada tabla chica.
- Toda función de repo que escribe usa `with conexion_db() as conexion:`
  (`database.py`) para que el commit/rollback sea atómico. Nunca abrir
  una conexión a mano.
- Toda query con datos del usuario va parametrizada (`?`, nunca
  f-string armando SQL con un valor externo). Esto no se negocia.

## Reglas de prolijidad

- **Nunca borrar algo con historial real de plata/stock/tiempo**
  (ventas, compras, sesiones de PC). Se marca `ANULADA`/`activo=0`/
  `desactivada`, nunca `DELETE`. Ver cómo lo hacen `ventas_repo.anular_venta`,
  `articulos_repo.desactivar_*` y `pcs_repo.desactivar_bono` como
  referencia.
- **Migraciones de esquema siempre aditivas.** `CREATE TABLE IF NOT
  EXISTS` para tablas nuevas, `ALTER TABLE ADD COLUMN` en una función
  `_migrar_*` para columnas nuevas en tablas viejas (ver
  `database._migrar_columnas_permisos`). Nunca un cambio que rompa una
  base ya instalada en el local real.
- **Comentarios explican el POR QUÉ, nunca el QUÉ.** El nombre de la
  función/variable ya dice qué hace. Un comentario solo se justifica
  para una decisión no obvia (ver casi cualquier función de
  `database.py` como ejemplo del estilo esperado).
- **Toda acción de UI que toca la base va envuelta en
  `@manejar_errores`** (`ui/utils.py`): un `ValueError` se muestra tal
  cual a la usuaria, cualquier otro error se loguea en
  `data/errores.log` sin romper la pantalla.
- **Nombres de función/tabla/columna en español**, consistentes con lo
  que ya existe. No mezclar idiomas dentro del mismo dominio.

## Reglas de escalabilidad

La app va a seguir creciendo (más módulos de negocio, más pantallas).
Para que eso no se vuelva un problema:

- **Si un patrón de UI se repite en 3 o más pantallas, se extrae** a
  algo compartido (por ahora no existe ese lugar común — la primera vez
  que haga falta, se crea `ui/widgets.py` o similar, no se sigue
  copiando y pegando). Ejemplo de algo que ya está repetido y es
  candidato: el bloque `for boton in self.findChildren(QPushButton):
  boton.setAutoDefault(False)` que aparece en cada `QDialog`.
- **Si un archivo de `ui/` pasa ~500-600 líneas**, evaluar partirlo en
  sub-widgets dentro del mismo módulo (no en archivos sueltos sin
  relación) antes de seguir agregándole cosas.
- **No reorganizar la estructura de carpetas (`ui/`, `repositories/`)
  sin proponerlo primero.** Es una decisión de fondo que el dueño del
  proyecto quiere charlar antes de que se ejecute — no asumir que
  "más prolijo" es motivo suficiente para migrar todo el árbol de
  archivos sin avisar.

## Testing

- `python -m unittest discover tests` corre toda la suite, siempre
  contra una base SQLite temporal (`tests/test_kiosko.py:BaseConBaseTemporal`),
  nunca contra `data/kiosko.db`.
- **Toda regla de negocio que toque plata, stock o tiempo necesita al
  menos un test.** Para simular una fecha/hora específica, mockear el
  `datetime` del módulo del repo (`mock.patch("repositories.X.datetime")`,
  con `datetime_mock.fromisoformat = datetime.fromisoformat` para no
  perder esa función real) — ver ejemplos en `TestPcsRepo` o
  `TestResumenPorTurno`.

## Qué NO hacer sin preguntar antes

- No reorganizar carpetas/estructura del proyecto.
- No cambiar el modelo de cobro (bonos de tiempo fijos — nunca hora
  libre ni minuto suelto) sin que el dueño lo pida explícitamente.
- No tocar `data/` a mano ni asumir que su contenido es descartable: ahí
  vive la base real del negocio (está en `.gitignore` a propósito, no
  llega a git).
- No lanzar un refactor grande "de paso" mientras se hace un cambio
  chico. Un pedido puntual se resuelve puntual.
