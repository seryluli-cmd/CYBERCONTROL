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
        _sql_tabla_comandos_pc, _sql_tabla_movimientos_saldo_miembro,
        _TIPOS_MOVIMIENTO_SALDO,
        _migrar_columnas_permisos, _migrar_columnas_origen_en_cierres,
        _migrar_columna_ultima_conexion_estaciones, _migrar_columna_ultima_ip_estaciones,
        _migrar_columna_cliente_cerrado_desde_estaciones, _migrar_check_tipo_en_comandos_pc,
        _migrar_columna_miembro_en_sesiones, _migrar_referencia_bono_en_movimientos_saldo_miembro,
        _migrar_check_tipo_en_movimientos_saldo_miembro, _migrar_columna_origen_en_ventas,
        _migrar_check_origen_en_ventas, _migrar_clave_clientes_pc, _cargar_datos_iniciales,
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS usuarios (
            id                       INTEGER PRIMARY KEY AUTOINCREMENT,
            nombre                   TEXT NOT NULL,
            clave_hash               TEXT NOT NULL,
            rol                      TEXT NOT NULL CHECK (rol IN ('ADMIN', 'EMPLEADA')),
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
    # Es la ÚNICA forma de modificar el stock de un artículo (aparte de las
    # ventas). Cada compra tiene una cabecera (fecha, quién la cargó) y
    # varias líneas de detalle, una por artículo ingresado.
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS cierres_turno (
            id                  INTEGER PRIMARY KEY AUTOINCREMENT,
            fecha               TEXT NOT NULL,
            turno               TEXT NOT NULL CHECK (turno IN ('MAÑANA', 'TARDE', 'NOCHE')),
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
    # turnos_repo._responsables_del_mes).
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS sesiones (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            usuario_id  INTEGER NOT NULL REFERENCES usuarios(id),
            fecha_hora  TEXT NOT NULL
        )
    """)

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
    _migrar_columna_cliente_cerrado_desde_estaciones(conexion)
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
    cursor.execute("""
        CREATE TABLE IF NOT EXISTS eventos_admin_pc (
            id                   INTEGER PRIMARY KEY AUTOINCREMENT,
            estacion_id          INTEGER NOT NULL REFERENCES estaciones(id),
            fecha_hora           TEXT NOT NULL,
            tipo                 TEXT NOT NULL CHECK (tipo IN
                                     ('ACCESO', 'CIERRE_CLIENTE', 'RECONFIGURAR', 'CLIENTE_REANUDADO')),
            segundos_sin_cliente INTEGER
        )
    """)
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_eventos_admin_pc_fecha ON eventos_admin_pc(fecha_hora)")
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
    # PLAYSTATION 5 (una única consola, se alquila por tiempo como una PC)
    # -------------------------------------------------------------------
    # La consola NO es una fila de "estaciones": una estación es una PC con su
    # Cliente PC (bloqueo, comandos remotos, IP, "Gestionar Estaciones"), y nada
    # de eso existe en una consola. Por eso tiene sus propias tablas, y ningún
    # camino pensado para PCs (renombrar, dar de baja, reiniciar, pasarle un
    # bono de PC) puede alcanzarla por error. Ver playstation_repo.py.
    #
    # "bonos_playstation" es su catálogo de bonos, aparte del de las PCs
    # (bonos_tiempo) y del de socios (bonos_miembro): mismo esquema, tablas
    # distintas, para que un bono de una nunca se pueda vender en la otra.
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
    # un nombre para mostrar. "email" es el único dato realmente opcional.
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
            fecha_creacion  TEXT NOT NULL
        )
    """)
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
    _migrar_clave_clientes_pc(conexion)

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
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_venta_detalle_articulo ON venta_detalle(articulo_codigo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_detalle_articulo ON compra_detalle(articulo_codigo)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_compra_detalle_compra ON compra_detalle(compra_id)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_fecha ON sesiones(fecha_hora)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_sesiones_pc_estacion ON sesiones_pc(estacion_id, estado)")
    cursor.execute("CREATE INDEX IF NOT EXISTS idx_movimientos_saldo_miembro ON movimientos_saldo_miembro(miembro_id)")

    conexion.commit()

    _cargar_datos_iniciales(conexion)

    conexion.close()
