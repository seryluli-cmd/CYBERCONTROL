"""Creación de tablas e índices en el orden requerido por las migraciones."""

import dominio


def inicializar_base_de_datos():
    """
    Crea todas las tablas si todavía no existen (no borra nada si ya
    existen, así que es seguro llamar a esta función cada vez que arranca
    el programa). También carga datos de ejemplo la primera vez.
    """
    from database import (
        get_connection, _sql_tabla_ventas, _sql_tabla_de_bonos,
        _sql_tabla_comandos_pc, _sql_tabla_eventos_admin_pc, _sql_tabla_movimientos_saldo_miembro,
        _TIPOS_MOVIMIENTO_SALDO,
        _migrar_columnas_permisos, _migrar_columnas_origen_en_cierres,
        _migrar_columna_ultima_conexion_estaciones, _migrar_columna_ultima_ip_estaciones,
        _migrar_columna_ip_asentada_estaciones,
        _migrar_columna_cliente_cerrado_desde_estaciones, _migrar_columnas_actualizacion_estaciones,
        _migrar_columna_cliente_arranque_estaciones,
        _migrar_check_tipo_en_comandos_pc, _migrar_check_tipo_en_eventos_admin_pc,
        _migrar_columna_miembro_en_sesiones, _migrar_columna_whatsapp_en_miembros,
        _migrar_columna_desde_ip_en_sesiones,
        _migrar_referencia_bono_en_movimientos_saldo_miembro,
        _migrar_check_tipo_en_movimientos_saldo_miembro, _migrar_columna_origen_en_ventas,
        _migrar_check_origen_en_ventas, _migrar_borrar_clave_vieja_de_clientes_pc, _cargar_datos_iniciales,
        _valores_sql,
    )
    conexion = get_connection()
    cursor = conexion.cursor()

    # -------------------------------------------------------------------
    # USUARIOS
    # -------------------------------------------------------------------
    # Cada empleada y el/los administradores tienen su propio usuario.
    # "rol" solo puede ser ADMIN o EMPLEADA (dos niveles, como se definió).
    #   - ADMIN: acceso total siempre, incluida la administración de
    #     usuarios y la anulación de ventas — esto no se puede delegar
    #     con los permisos de abajo, son exclusivos del rol ADMIN.
    #   - EMPLEADA: por defecto solo factura (Ventas) y ve su propia
    #     caja. Un Admin puede sumarle permisos puntuales con los
    #     "permiso_*" de abajo (ver PERMISOS_EMPLEADA en
    #     usuarios_repo.py) para que también pueda entrar a Artículos,
    #     Compras, Consulta de Ventas (sin poder anular), Reportes o
    #     Control de Cierres, sin tener que hacerla Admin del todo.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS usuarios (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre                   TEXT NOT NULL,
            clave_hash               TEXT NOT NULL,
            rol                      TEXT NOT NULL CHECK (rol IN ({_valores_sql(dominio.ROLES)})),
            activo                   INTEGER NOT NULL DEFAULT 1,
            fecha_creacion           TEXT NOT NULL,
            permiso_articulos        INTEGER NOT NULL DEFAULT 0,
            permiso_compras          INTEGER NOT NULL DEFAULT 0,
            permiso_consulta_ventas  INTEGER NOT NULL DEFAULT 0,
            permiso_reportes         INTEGER NOT NULL DEFAULT 0,
            permiso_control_cierres  INTEGER NOT NULL DEFAULT 0,
            permiso_control_pcs      INTEGER NOT NULL DEFAULT 0
        )
    """)
    _migrar_columnas_permisos(conexion)

    # -------------------------------------------------------------------
    # MARCAS y RUBROS
    # -------------------------------------------------------------------
    # Tablas simples de "catálogo" para que Marca y Rubro se puedan elegir
    # de una lista (y agregar nuevas al vuelo) en vez de escribirlas a mano
    # cada vez, evitando que "COCA" y "Coca" queden como cosas distintas.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS marcas (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS rubros (
            id     INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre TEXT NOT NULL UNIQUE
        )
    """)

    # -------------------------------------------------------------------
    # ARTICULOS
    # -------------------------------------------------------------------
    # El "codigo" es el código de barras (o un código corto para productos
    # sin barras, como "PANCHO DOBLE"). Es el identificador natural del
    # producto porque es lo que lee la pistola lectora.
    #
    # "stock" puede quedar en negativo a propósito: cuando se vende un
    # producto que todavía no se cargó como compra, el stock baja de 0
    # para abajo, y cuando después se carga la compra correspondiente,
    # el número se corrige solo. Nunca se bloquea una venta por falta de
    # stock, solo se avisa si queda por debajo de "stock_minimo".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articulos (
            codigo          TEXT PRIMARY KEY,
            descripcion     TEXT NOT NULL,
            marca_id        INTEGER REFERENCES marcas(id),
            rubro_id        INTEGER REFERENCES rubros(id),
            precio_venta    REAL NOT NULL DEFAULT 0,
            precio_compra   REAL NOT NULL DEFAULT 0,
            stock           INTEGER NOT NULL DEFAULT 0,
            stock_minimo    INTEGER NOT NULL DEFAULT 0,
            fecha_creacion  TEXT NOT NULL,
            fecha_modif     TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # COMPRAS (ingreso de mercadería)
    # -------------------------------------------------------------------
    # Es la forma de cargar stock a un artículo (aparte de las ventas, que lo
    # bajan, y de ORDENAR Stock, que lo corrige: ver ajustes_stock). Cada
    # compra tiene una cabecera (fecha, quién la cargó) y varias líneas de
    # detalle, una por artículo ingresado.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compras (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha       TEXT NOT NULL,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id)
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS compra_detalle (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            compra_id        INTEGER NOT NULL REFERENCES compras(id),
            articulo_codigo  TEXT NOT NULL REFERENCES articulos(codigo),
            cantidad         INTEGER NOT NULL,
            costo_unitario   REAL NOT NULL,
            stock_antes      INTEGER NOT NULL,
            stock_despues    INTEGER NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # AJUSTES DE STOCK ("ORDENAR Stock", pedido del dueño 2026-10-20)
    # -------------------------------------------------------------------
    # Cada vez que un Admin corrige a mano el stock de un artículo (lo que hay
    # contado en el estante): cuánto decía el programa, cuánto quedó, quién y
    # cuándo. Sin plata: no es una compra ni una venta. Es lo que muestra
    # Movimientos como "ajuste de stock" (articulos_repo.ajustar_stock).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ajustes_stock (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            articulo_codigo  TEXT NOT NULL REFERENCES articulos(codigo),
            fecha            TEXT NOT NULL,
            usuario_id       INTEGER NOT NULL REFERENCES usuarios(id),
            stock_anterior   INTEGER NOT NULL,
            stock_nuevo      INTEGER NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # CAMBIOS DE CÓDIGO (también "ORDENAR Stock", pedido del dueño 2026-10-20)
    # -------------------------------------------------------------------
    # Códigos que se cargaron mal a mano (en vez de con la pistola) y un Admin
    # corrigió: el de antes, el nuevo, quién y cuándo. `articulo_codigo` es el
    # código ACTUAL del artículo: en cada cambio se corrige junto con las ventas,
    # compras y ajustes (articulos_repo.cambiar_codigo), así Movimientos muestra
    # todos los cambios de un artículo aunque se haya corregido dos veces.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cambios_codigo (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            articulo_codigo  TEXT NOT NULL REFERENCES articulos(codigo),
            fecha            TEXT NOT NULL,
            usuario_id       INTEGER NOT NULL REFERENCES usuarios(id),
            codigo_anterior  TEXT NOT NULL,
            codigo_nuevo     TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # VENTAS (facturación)
    # -------------------------------------------------------------------
    # "turno" se calcula automáticamente según la hora de la venta (ver
    # turnos.calcular_turno: 3 turnos de 8 hs, 2 de 12 hs los domingos),
    # sin importar qué usuario esté logueado — así el reporte "ventas por
    # turno" es siempre exacto, incluso si una empleada llega tarde a su
    # horario.
    #
    # "estado" es CONFIRMADA o ANULADA. Nunca se borra una venta: si el
    # Admin necesita corregir un error después de cobrada, se anula (queda
    # el rastro de quién, cuándo y por qué) y el stock se repone solo.
    #
    # "origen" separa cuánto se vendió de productos de kiosko (KIOSKO), cuánto
    # entró por alquiler de PCs -- bonos y cargas de saldo de Miembros
    # (ALQUILER_PCS) -- y cuánto por la PlayStation 5 (PLAYSTATION), para que
    # Caja/Cierre de Turno puedan mostrar el desglose exacto entre los tres
    # negocios (ver dominio.ORIGENES_VENTA, ventas_repo.registrar_venta_sin_detalle,
    # _migrar_columna_origen_en_ventas para el backfill de bases viejas y
    # _migrar_check_origen_en_ventas para las que no admiten PLAYSTATION).
    # (El SQL de esta tabla está en database._sql_tabla_ventas: la migración
    # del CHECK de "origen" la reconstruye con el mismo molde.)
    cursor.execute(_sql_tabla_ventas(si_no_existe=True))
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS venta_detalle (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id         INTEGER NOT NULL REFERENCES ventas(id),
            articulo_codigo  TEXT NOT NULL REFERENCES articulos(codigo),
            descripcion      TEXT NOT NULL,
            cantidad         INTEGER NOT NULL,
            precio_unitario  REAL NOT NULL,
            subtotal         REAL NOT NULL
        )
    """)
    # Una venta puede pagarse combinando más de un medio de pago (por
    # ejemplo: una parte en efectivo y el resto por Mercado Pago), por eso
    # los pagos son una tabla aparte y no un campo único en "ventas".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS venta_pagos (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id  INTEGER NOT NULL REFERENCES ventas(id),
            metodo    TEXT NOT NULL CHECK (metodo IN ('EFECTIVO', 'DIGITAL')),
            monto     REAL NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # TRÁMITES (servicios que los empleados hacen en el mostrador -- sacar e
    # imprimir una boleta de luz o gas, un trámite online, un turno -- y se
    # cobran con el monto que se tipee en el momento: se cobra el servicio,
    # nunca la boleta en sí)
    # -------------------------------------------------------------------
    # "tramites" es el catálogo que arma el Admin (activo = 0 es la baja:
    # nada se borra, las ventas ya hechas lo siguen referenciando).
    # "tramites_venta" une cada venta de un trámite con el trámite que se
    # cobró -- la venta en sí es una fila común de "ventas" (origen KIOSKO,
    # sin venta_detalle, ver tramites_repo.registrar_tramite), así que la
    # caja y el cierre de turno la cuentan solos. "descripcion" es una foto
    # del nombre al momento de cobrar (igual que venta_detalle.descripcion):
    # si el Admin renombra el trámite después, el historial no cambia.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tramites (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre          TEXT NOT NULL,
            activo          INTEGER NOT NULL DEFAULT 1,
            fecha_creacion  TEXT NOT NULL
        )
    """)
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS tramites_venta (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            venta_id     INTEGER NOT NULL UNIQUE REFERENCES ventas(id),
            tramite_id   INTEGER NOT NULL REFERENCES tramites(id),
            descripcion  TEXT NOT NULL
        )
    """)

    # -------------------------------------------------------------------
    # CIERRES DE TURNO
    # -------------------------------------------------------------------
    # Un registro por cada vez que una empleada cierra su turno. Guarda
    # cuánto efectivo "debería" haber (fondo de cambio + ventas en
    # efectivo de ese turno) para que la empleada se lleve la diferencia.
    # Más tarde, el Admin puede cargar "monto_contado" (lo que realmente
    # había en el sobre) para llevar un control por empleada y por turno.
    #
    # "kiosko_*"/"pcs_*"/"playstation_*" repiten el mismo desglose que
    # "ventas_efectivo"/"ventas_digital" pero separado por origen (ver
    # dominio.ORIGENES_VENTA): el dueño necesita poder controlar, turno por
    # turno, cuánto entró por productos de kiosko, cuánto por alquiler de PCs y
    # cuánto por la PlayStation 5, no solo el total mezclado. Quedan guardados
    # en el cierre (no solo calculados al vuelo) para que el historial sea
    # auditable después, no solo "ahora".
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS cierres_turno (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha               TEXT NOT NULL,
            turno               TEXT NOT NULL CHECK (turno IN ({_valores_sql(dominio.TURNOS)})),
            usuario_id          INTEGER NOT NULL REFERENCES usuarios(id),
            fecha_cierre        TEXT NOT NULL,
            fondo_cambio        REAL NOT NULL,
            ventas_efectivo     REAL NOT NULL,
            ventas_digital      REAL NOT NULL,
            monto_a_retirar     REAL NOT NULL,
            monto_contado       REAL,
            diferencia          REAL,
            verificado_por      INTEGER REFERENCES usuarios(id),
            fecha_verificacion  TEXT,
            kiosko_efectivo     REAL NOT NULL DEFAULT 0,
            kiosko_digital      REAL NOT NULL DEFAULT 0,
            pcs_efectivo        REAL NOT NULL DEFAULT 0,
            pcs_digital         REAL NOT NULL DEFAULT 0,
            playstation_efectivo REAL NOT NULL DEFAULT 0,
            playstation_digital  REAL NOT NULL DEFAULT 0
        )
    """)
    _migrar_columnas_origen_en_cierres(conexion)

    # -------------------------------------------------------------------
    # SESIONES (inicios de sesión)
    # -------------------------------------------------------------------
    # Una fila por cada login exitoso. El sistema no tiene un horario
    # asignado por empleada, así que esto sirve como pista de quién
    # estaba usando el sistema en un momento dado — en particular, para
    # saber quién podría ser responsable de un turno que quedó sin
    # cerrar aunque no haya vendido nada en esa ventana (ver
    # turnos_faltantes_repo._responsables_del_mes).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id),
            fecha_hora  TEXT NOT NULL
        )
    """)
    # desde_ip: el ingreso del Administrador desde otra PC del local.
    _migrar_columna_desde_ip_en_sesiones(conexion)

    # -------------------------------------------------------------------
    # ESTACIONES y BONOS DE TIEMPO (Control de PCs)
    # -------------------------------------------------------------------
    # "estaciones" es el catálogo de PCs físicas del local (ej. "PC 1"...
    # "PC 10"), igual de simple que marcas/rubros. "bonos_tiempo" es el
    # catálogo de combos vendibles ("3 horas" -> 180 min / $X) que arma
    # el Admin: acá NUNCA se cobra por minuto suelto ni por hora libre,
    # solo por estos bonos prearmados. "activo" en ambas tablas permite
    # dar de baja una sin romper el historial de sesiones que ya la usaron
    # (mismo criterio que articulos.stock: nunca se borra, se desactiva).
    # "ultima_conexion" la actualiza servidor_red.py en cada GET /estado
    # que recibe de esa estación (el Cliente PC pregunta cada 5s mientras está
    # prendido y con red) -- es lo que usa pcs_repo.estado_estaciones()
    # para decidir si una estación está "enlazada" sin sesión de por medio.
    # "ultima_ip" es la IP de esa última consulta; "ip_asentada", la de la
    # PRIMERA, que no se pisa sola: con ella se reconoce a una PC cuyo nombre no
    # coincide con ninguna estación (pcs_repo.estado_de_estacion).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS estaciones (
            id               INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre           TEXT NOT NULL UNIQUE,
            activa           INTEGER NOT NULL DEFAULT 1,
            ultima_conexion  TEXT
        )
    """)
    _migrar_columna_ultima_conexion_estaciones(conexion)
    _migrar_columna_ultima_ip_estaciones(conexion)
    _migrar_columna_ip_asentada_estaciones(conexion)
    _migrar_columna_cliente_cerrado_desde_estaciones(conexion)
    _migrar_columnas_actualizacion_estaciones(conexion)
    _migrar_columna_cliente_arranque_estaciones(conexion)
    cursor.execute(_sql_tabla_de_bonos("bonos_tiempo"))

    # Una fila por uso continuo de una estación. Al vender un bono a una
    # estación sin sesión activa se crea una fila nueva; al vender un
    # bono adicional a una que YA está activa (el cliente sigue jugando)
    # se extiende "fecha_fin_prevista" de esta misma fila en vez de crear
    # otra — así "agregar tiempo" es sumar otro bono a la sesión abierta,
    # sin necesitar un concepto aparte de "extender por minutos sueltos".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_pc (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id         INTEGER NOT NULL REFERENCES estaciones(id),
            fecha_inicio        TEXT NOT NULL,
            fecha_fin_prevista  TEXT NOT NULL,
            estado              TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA', 'FINALIZADA')),
            fecha_fin_real      TEXT
        )
    """)
    # Historial de cada vez que una sesión cambió de PC (ver
    # pcs_repo.trasladar_sesion): el cliente quería su PC favorita y el
    # operador le pasó la sesión sin perder tiempo ni cobrar de nuevo. La
    # sesión es la MISMA fila de sesiones_pc con otro estacion_id, así que
    # sin esta tabla no quedaría rastro de en qué PC estuvo antes (nada se
    # borra, se registra: regla 7 de CLAUDE.md). Un intercambio entre dos
    # PCs ocupadas graba dos filas, una por cada sesión.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS traslados_sesion (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id            INTEGER NOT NULL REFERENCES sesiones_pc(id),
            estacion_origen_id   INTEGER NOT NULL REFERENCES estaciones(id),
            estacion_destino_id  INTEGER NOT NULL REFERENCES estaciones(id),
            fecha                TEXT NOT NULL,
            usuario_id           INTEGER NOT NULL REFERENCES usuarios(id)
        )
    """)
    # Registro de los accesos al panel admin de cada Cliente PC (ver
    # control_pcs/repositories/accesos_admin_pc_repo.py): quién sabe la
    # contraseña puede cerrar el Cliente PC y dejar la PC sin bloqueo, y el
    # dueño quería enterarse cuándo pasa y cuánto dura. Nada se borra
    # (regla 7 de CLAUDE.md). "segundos_sin_cliente" solo se llena en
    # CLIENTE_REANUDADO: cuánto estuvo la PC sin Cliente PC.
    # (El SQL está en database_migraciones._sql_tabla_eventos_admin_pc: la migración
    # de abajo la reconstruye cuando se suma un tipo, como MANTENIMIENTO el 2026-10-19.)
    cursor.execute(_sql_tabla_eventos_admin_pc(dominio.EVENTOS_ADMIN_PC, si_no_existe=True))
    # Antes del índice: reconstruir la tabla borra los que tenía.
    _migrar_check_tipo_en_eventos_admin_pc(conexion)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_eventos_admin_pc_fecha ON eventos_admin_pc(fecha_hora)")
    # Cada vez que una PC con sesión dejó de dar noticias (la alerta "SIN
    # CLIENTE" que titila) y volvió sola: cuándo volvió, cuánto estuvo sin
    # noticias y por qué (ver control_pcs/repositories/cortes_pc_repo.py).
    # "fallas" es cuántas consultas le fallaron a la PC en el medio, según ella
    # (NULL = no lo dijo: Cliente PC viejo). Nada se borra (regla 7). Índice por
    # fecha para "Actividad reciente"; por sesión, para la cuenta de cortes de
    # la sesión en curso que muestra el panel de cada PC.
    cursor.execute(f"""
        CREATE TABLE IF NOT EXISTS cortes_pc (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id          INTEGER NOT NULL REFERENCES estaciones(id),
            sesion_id            INTEGER REFERENCES sesiones_pc(id),
            fecha_hora           TEXT NOT NULL,
            segundos             INTEGER NOT NULL,
            causa                TEXT NOT NULL CHECK (causa IN ({_valores_sql(dominio.CAUSAS_CORTE_PC)})),
            fallas               INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cortes_pc_fecha ON cortes_pc(fecha_hora)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cortes_pc_sesion ON cortes_pc(sesion_id)")
    # Cada vez que una PC volvió de un corte con MENOS tiempo que el que tenía
    # anotado el mostrador y el mostrador bajó el suyo (ver
    # control_pcs/repositories/reconexion_repo.py, pedido del dueño 2026-10-20:
    # "se toma el menor"). Cuánto decía cada uno y cómo quedó el fin de la
    # sesión, para poder explicar después por qué un cliente tuvo menos tiempo.
    # Nada se borra (regla 7). Índice por fecha para "Actividad reciente".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS ajustes_reconexion_pc (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id          INTEGER NOT NULL REFERENCES estaciones(id),
            sesion_id            INTEGER NOT NULL REFERENCES sesiones_pc(id),
            fecha_hora           TEXT NOT NULL,
            segundos_mostrador   INTEGER NOT NULL,
            segundos_pc          INTEGER NOT NULL,
            minutos_cargados     INTEGER NOT NULL,
            fin_antes            TEXT NOT NULL,
            fin_despues          TEXT NOT NULL
        )
    """)
    cursor.execute(
        "CREATE INDEX IF NOT EXISTS idx_ajustes_reconexion_pc_fecha ON ajustes_reconexion_pc(fecha_hora)"
    )
    # Cada página que cerró el filtro de palabras de una PC cliente (ver
    # control_pcs/repositories/filtro_palabras_repo.py): qué palabra encontró y en
    # qué título. Nada se borra (regla 7). El índice por fecha es porque
    # "Actividad reciente" pide los últimos en cada refresco de 5 s.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS bloqueos_filtro_pc (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id          INTEGER NOT NULL REFERENCES estaciones(id),
            fecha_hora           TEXT NOT NULL,
            palabra              TEXT NOT NULL,
            titulo               TEXT NOT NULL
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_bloqueos_filtro_pc_fecha ON bloqueos_filtro_pc(fecha_hora)")
    # Detalle de qué bono(s) se cargaron a cada sesión, con el venta_id de
    # la venta que generó ese cobro (se factura igual que cualquier venta
    # de kiosko, ver pcs_repo.asignar_bono) — trazabilidad completa entre
    # "se vendió este bono a esta PC" y "esto es lo que se facturó".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesion_bonos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id  INTEGER NOT NULL REFERENCES sesiones_pc(id),
            bono_id    INTEGER NOT NULL REFERENCES bonos_tiempo(id),
            minutos    INTEGER NOT NULL,
            precio     REAL NOT NULL,
            venta_id   INTEGER REFERENCES ventas(id)
        )
    """)

    # -------------------------------------------------------------------
    # PCSTREAM (la PC de streaming: una estación más, con precios propios)
    # -------------------------------------------------------------------
    # A diferencia de la PlayStation 5, PCSTREAM SÍ es una fila de "estaciones"
    # (tiene Cliente PC y se bloquea como cualquier PC) y sus sesiones son de
    # "sesiones_pc". Lo único propio es el catálogo de bonos: "bonos_pcstream",
    # otra tabla con el mismo esquema, para que un bono común nunca se le pueda
    # vender a PCSTREAM ni uno de PCSTREAM a otra PC (ver pcstream_repo y
    # pcs_repo.asignar_bono). Por eso el vínculo bono-sesión también es otra
    # tabla: sesion_bonos.bono_id apunta a bonos_tiempo, y con las claves
    # foráneas prendidas un bono de PCSTREAM no puede ir ahí.
    cursor.execute(_sql_tabla_de_bonos("bonos_pcstream"))
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesion_pcstream_bonos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id  INTEGER NOT NULL REFERENCES sesiones_pc(id),
            bono_id    INTEGER NOT NULL REFERENCES bonos_pcstream(id),
            minutos    INTEGER NOT NULL,
            precio     REAL NOT NULL,
            venta_id   INTEGER NOT NULL REFERENCES ventas(id)
        )
    """)

    # -------------------------------------------------------------------
    # PLAYSTATION 5 (una única consola, se alquila por tiempo como una PC)
    # -------------------------------------------------------------------
    # La consola NO es una fila de "estaciones": una estación es una PC con su
    # Cliente PC (bloqueo, comandos remotos, IP, "Gestionar Estaciones"), y nada
    # de eso existe en una consola. Por eso tiene sus propias tablas, y ningún
    # camino pensado para PCs (renombrar, dar de baja, reiniciar, pasarle un
    # bono de PC) puede alcanzarla por error. Ver playstation_repo.py.
    #
    # "bonos_playstation" es su catálogo de bonos, aparte del de las PCs
    # (bonos_tiempo, bonos_pcstream) y del de socios (bonos_miembro): mismo
    # esquema, tablas distintas, para que un bono de una nunca se pueda vender
    # en la otra.
    cursor.execute(_sql_tabla_de_bonos("bonos_playstation"))
    # Misma idea que "sesiones_pc"/"sesion_bonos": una sesión por cada uso
    # continuo de la consola, que se extiende (fecha_fin_prevista) si se vende
    # otro bono mientras sigue en curso. El vencimiento es una fecha ABSOLUTA,
    # no un contador: cerrar y reabrir el programa no cambia cuánto queda. Al
    # llegar a cero la sesión NO se da de baja sola (a diferencia de una PC, que
    # se bloquea): queda ACTIVA con el tiempo agotado, avisando en rojo, hasta
    # que el operador la libera o vende otro bono (ver playstation_repo).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones_playstation (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha_inicio        TEXT NOT NULL,
            fecha_fin_prevista  TEXT NOT NULL,
            estado              TEXT NOT NULL DEFAULT 'ACTIVA' CHECK (estado IN ('ACTIVA', 'FINALIZADA')),
            fecha_fin_real      TEXT
        )
    """)
    # Una sola consola, así que a lo sumo UNA sesión ACTIVA a la vez: el índice
    # parcial lo garantiza desde la base, aunque algún día un error de código (o
    # dos pedidos juntos) intentara abrir una segunda.
    cursor.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS idx_sesion_playstation_activa "
        "ON sesiones_playstation(estado) WHERE estado = 'ACTIVA'"
    )
    # Qué bono(s) se vendieron en cada sesión, con el venta_id de la venta que
    # los cobró (origen PLAYSTATION, ver dominio.ORIGEN_PLAYSTATION): la
    # trazabilidad entre "se vendió este bono" y "esto es lo que se facturó".
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesion_playstation_bonos (
            id         INTEGER PRIMARY KEY AUTOINCREMENT,
            sesion_id  INTEGER NOT NULL REFERENCES sesiones_playstation(id),
            bono_id    INTEGER NOT NULL REFERENCES bonos_playstation(id),
            minutos    INTEGER NOT NULL,
            precio     REAL NOT NULL,
            venta_id   INTEGER NOT NULL REFERENCES ventas(id)
        )
    """)

    # -------------------------------------------------------------------
    # COMANDOS_PC (control remoto de una estación desde el mostrador)
    # -------------------------------------------------------------------
    # El mostrador no tiene ninguna conexión directa hacia la PC cliente
    # (evita el lío de firewall/puertos entrantes que ya se vio con el
    # servidor de Kiosko) -- en cambio, deja un comando "pendiente" acá, y
    # el Cliente PC de esa estación lo recoge solo en su próxima consulta de
    # `GET /estado` (cada 5s, ver servidor_red.py y la carpeta hermana
    # "CLIENTE PC"). "resultado" solo se usa para SCREENSHOT: guarda
    # la ruta relativa (dentro de data/) del archivo que subió el Cliente PC
    # después de entregado -- para REINICIAR/APAGAR/MENSAJE queda en NULL,
    # no hay nada que el Cliente PC tenga que devolver.
    # (El SQL de esta tabla está en database_migraciones._sql_tabla_comandos_pc: una
    # migración la reconstruye en su versión anterior. "tipo" admite todos los
    # dominio.TIPOS_COMANDO_PC.)
    cursor.execute(_sql_tabla_comandos_pc(dominio.TIPOS_COMANDO_PC, si_no_existe=True))
    # Tiene que ir ANTES de crear el índice de abajo: reconstruir la tabla
    # borra los índices que tenía, y así se recrea sobre la tabla nueva.
    _migrar_check_tipo_en_comandos_pc(conexion)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_comandos_pc_estacion ON comandos_pc(estacion_id, estado)")

    # -------------------------------------------------------------------
    # MIEMBROS (socios con saldo prepago de tiempo)
    # -------------------------------------------------------------------
    # A diferencia de un bono (lo habilita el mostrador, se paga y se usa
    # en el momento, sin reintegro), un Miembro tiene una cuenta propia:
    # se loguea solo con "usuario"/clave para abrir una PC con SU saldo
    # (ver pcs_repo._abrir_o_extender_sesion / miembros_repo.abrir_estacion_por_miembro).
    # "usuario" acá SÍ es UNIQUE de verdad (a diferencia de usuarios.nombre,
    # que solo se valida en Python) porque es un campo de login real, no
    # un nombre para mostrar. Desde el 2026-10-17 el alta pide solo usuario y
    # clave: dni, telefono (el "Celular" de la pantalla) y whatsapp quedan en ''
    # hasta que el socio los completa en su primer ingreso desde una PC (ver
    # miembros_repo.abrir_estacion_por_miembro), y un nombre vacío se guarda
    # como el usuario.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS miembros (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario         TEXT NOT NULL UNIQUE,
            clave_hash      TEXT NOT NULL,
            nombre          TEXT NOT NULL,
            dni             TEXT NOT NULL,
            telefono        TEXT NOT NULL,
            email           TEXT,
            saldo_minutos   INTEGER NOT NULL DEFAULT 0,
            activo          INTEGER NOT NULL DEFAULT 1,
            fecha_creacion  TEXT NOT NULL,
            whatsapp        TEXT NOT NULL DEFAULT ''
        )
    """)
    _migrar_columna_whatsapp_en_miembros(conexion)
    # Catálogo de bonos EXCLUSIVO para Miembros -- mismo esquema que
    # bonos_tiempo (nombre/minutos/precio/activo) pero a propósito una
    # tabla aparte, nunca la misma fila: bonos_tiempo es lo que se le
    # vende a cualquiera que entra al local (walk-in, ver
    # pcs_repo.asignar_bono), bonos_miembro es lo que un socio puede
    # cargarse a su saldo desde "Cargar Saldo" -> "Bono fijo" (ver
    # miembros_repo.cargar_saldo_por_bono) -- el dueño pidió poder
    # ofrecerle a los socios combos propios, distintos de los del
    # mostrador. Crear/editar/dar de baja un bono de ESTE catálogo, igual
    # que uno de bonos_tiempo, es exclusivo de ADMIN (ver
    # ui/main_window.ConfiguracionAdminWindow) -- cualquiera con
    # 'permiso_control_pcs' puede usar un bono ya creado, no editarlo.
    cursor.execute(_sql_tabla_de_bonos("bonos_miembro"))
    # Ledger de auditoría de todo movimiento de saldo: CARGA (siempre con
    # venta_id, porque implica cobrar plata real — y bono_id si se cargó
    # comprando un bono en vez de un monto libre, SIEMPRE del catálogo
    # bonos_miembro, nunca de bonos_tiempo), CONSUMO (sesion_id, al abrir
    # una PC con saldo), REINTEGRO (sesion_id, cuando se corta antes de
    # tiempo y se devuelve lo no usado) y ANULACION (venta_id, cuando un
    # Admin anula desde Consulta de Ventas la venta que había originado
    # una CARGA -- ver ventas_repo.anular_venta / miembros_repo.anular_carga).
    # Como esto maneja plata de terceros, poder reconstruir "por qué le
    # queda tal saldo a este socio" no es opcional.
    # (El SQL de esta tabla está en _sql_tabla_movimientos_saldo_miembro, más
    # abajo: las migraciones de esta misma tabla la reconstruyen en sus
    # versiones anteriores, y así todas parten del mismo molde.)
    cursor.execute(_sql_tabla_movimientos_saldo_miembro(
        _TIPOS_MOVIMIENTO_SALDO, "bonos_miembro(id)", si_no_existe=True
    ))
    _migrar_columna_miembro_en_sesiones(conexion)

    # Una base que ya tenía "movimientos_saldo_miembro" de antes de que
    # existiera "bonos_miembro" sigue con bono_id apuntando a bonos_tiempo
    # (el CREATE TABLE de arriba no toca una tabla existente). Necesita su
    # propia migración -- reconstruir la tabla, no un ALTER TABLE -- porque
    # SQLite no deja cambiar el REFERENCES de una columna ya creada.
    _migrar_referencia_bono_en_movimientos_saldo_miembro(conexion)

    # Mismo motivo, pero para el CHECK de "tipo": una base creada antes de
    # que existiera el tipo ANULACION sigue con el CHECK viejo.
    _migrar_check_tipo_en_movimientos_saldo_miembro(conexion)

    # Esta migración necesita leer "sesion_bonos" y "movimientos_saldo_miembro"
    # para el backfill (ver database_migraciones._migrar_columna_origen_en_ventas),
    # así que va acá -- recién
    # ahora existen esas dos tablas -- y NO junto al CREATE TABLE de
    # "ventas", más arriba en este archivo.
    _migrar_columna_origen_en_ventas(conexion)
    # Va justo después: la columna ya existe, pero su CHECK puede no admitir
    # todavía el origen PLAYSTATION (una base anterior a la consola). Tiene que
    # correr ANTES de crear los índices de más abajo, porque reconstruir
    # "ventas" borra los suyos.
    _migrar_check_origen_en_ventas(conexion)

    # -------------------------------------------------------------------
    # CONFIGURACION
    # -------------------------------------------------------------------
    # Tabla simple de "clave -> valor" para parámetros generales del
    # sistema. Hoy solo se usa para el fondo de cambio, pero permite
    # agregar más configuraciones a futuro sin tener que cambiar el
    # esquema de la base de datos.
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS configuracion (
            clave  TEXT PRIMARY KEY,
            valor  TEXT NOT NULL
        )
    """)
    _migrar_borrar_clave_vieja_de_clientes_pc(conexion)

    # -------------------------------------------------------------------
    # CAJAS (con número, apertura, relevos y conteos del sobre)
    # -------------------------------------------------------------------
    # En su propio archivo: ver database_esquema_cajas.py.
    from database_esquema_cajas import crear_tablas_de_cajas
    crear_tablas_de_cajas(cursor, _valores_sql)

    # -------------------------------------------------------------------
    # INDICES
    # -------------------------------------------------------------------
    # Estos índices son la razón por la que los reportes van a ser rápidos
    # incluso con años de historial: le dicen a SQLite que arme un "atajo"
    # para buscar por fecha o por artículo, en vez de tener que recorrer
    # toda la tabla fila por fila cada vez que pedís un reporte.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ventas_fecha ON ventas(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ventas_turno ON ventas(turno, fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_venta_detalle_venta ON venta_detalle(venta_id)")
    # Los pagos de cada venta (2026-10-18). Sin este, "Reportes > Por Operador"
    # con un año de ventas tardaba 6 minutos (por cada venta recorría todos los
    # pagos de la historia); mirado desde otra PC (admin_remoto/), eso además
    # frenaba las ventas del mostrador mientras duraba.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_venta_pagos_venta ON venta_pagos(venta_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_venta_detalle_articulo ON venta_detalle(articulo_codigo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_detalle_articulo ON compra_detalle(articulo_codigo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_detalle_compra ON compra_detalle(compra_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_ajustes_stock_articulo ON ajustes_stock(articulo_codigo, fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_cambios_codigo_articulo ON cambios_codigo(articulo_codigo, fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_fecha ON sesiones(fecha_hora)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_pc_estacion ON sesiones_pc(estacion_id, estado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_saldo_miembro ON movimientos_saldo_miembro(miembro_id)")

    # La pantalla de PCs se refresca cada 5 segundos y en cada refresco pide
    # las sesiones en curso y "lo último que pasó" para el panel de
    # actividad (pcs_repo.estado_estaciones, actividad_repo.actividad_reciente).
    # Sin estos índices la base leía TODO el historial cada vez: medido con
    # un año simulado de 40 PCs, la pantalla se trababa ~0,4 s cada 5 s, y
    # cada día de uso lo empeoraba (revisión del 2026-10-17, ver
    # docs/AUDITORIA_2026-10-17.md). Con ellos lee solo lo que muestra
    # (~8 ms con ese mismo año). Crearlos es instantáneo con la base vacía y
    # tarda ~0,4 s, una sola vez, con un año de historial. Lo vigila
    # tests/test_velocidad_pantalla_pcs.py.
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_pc_estado ON sesiones_pc(estado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_pc_inicio ON sesiones_pc(fecha_inicio)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_pc_fin_real ON sesiones_pc(fecha_fin_real)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesion_bonos_venta ON sesion_bonos(venta_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesion_pcstream_bonos_venta ON sesion_pcstream_bonos(venta_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_saldo_miembro_fecha ON movimientos_saldo_miembro(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_traslados_sesion_fecha ON traslados_sesion(fecha)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_playstation_inicio ON sesiones_playstation(fecha_inicio)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_playstation_fin_real ON sesiones_playstation(fecha_fin_real)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesion_playstation_bonos_venta ON sesion_playstation_bonos(venta_id)")

    conexion.commit()

    _cargar_datos_iniciales(conexion)

    conexion.close()
