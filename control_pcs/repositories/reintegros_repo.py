"""
reintegros_repo.py
====================
Cuánto tiempo se le devuelve a cada socio cuando se corta una sesión de PC antes
de que se acabe (lo usa `pcs_repo.finalizar_sesion`, el único que cierra una
sesión de PC). Vive aparte porque pcs_repo.py pasó las ~600 líneas (CLAUDE.md,
regla 12); las dos funciones salieron de ahí sin cambios, salvo que ahora
también cuentan los bonos de PCSTREAM.

Un bono (común o de PCSTREAM) es un consumible: lo que no se usó no se devuelve.
El saldo de un socio es plata suya: lo que no se usó vuelve a su saldo, en
bloques de MINUTOS_POR_FRACCION.
"""

import dominio

# Mismo valor que miembros_repo.MINUTOS_POR_FRACCION (no se importa de
# ahí a propósito: miembros_repo importa pcs_repo, que importa este módulo, e
# importar en el otro sentido crearía un ciclo -- son dos constantes que hoy
# coinciden en valor pero describen granularidades de negocio distintas).
MINUTOS_POR_FRACCION = 30


def contribuciones_de_sesion(conexion, sesion_id: int):
    """
    Reconstruye, en orden cronológico, de dónde salió cada tramo de
    minutos que se le fue sumando a una sesión (bono del mostrador o
    saldo de un socio) -- no hace falta una tabla nueva para esto:
    sesion_bonos, sesion_pcstream_bonos y movimientos_saldo_miembro (tipo
    CONSUMO) ya guardan cada aporte por otras razones (facturación, ledger de
    saldo). El orden de aparición coincide con el orden en que se fueron
    sumando a la sesión porque pcs_repo.asignar_bono() y
    miembros_repo.abrir_estacion_por_miembro() usan el mismo `ahora` tanto para
    extender la sesión (pcs_repo._abrir_o_extender_sesion) como para grabar su
    propio registro -- ver reintegros_por_miembro, el único que usa esto. Un
    bono de PCSTREAM cuenta como cualquier bono: no reintegra.

    Un bono anotado en la Cuenta de la PC (cuentas_pc_repo) también es un bono:
    mientras no se cobra no tiene fila en sesion_bonos, así que sale de
    cuenta_pc_items; ya cobrado, su fila de sesion_bonos va con la hora en que
    se ANOTÓ (cuando se sumó el tiempo), no con la del cobro. Uno quitado por
    un Admin no cuenta (ya se le sacó el tiempo). El tiempo de socio anotado,
    mientras no se paga, cuenta como un bono (no se le devuelve como saldo algo
    que no pagó); cobrado, es un CONSUMO suyo con la hora en que se anotó.
    """
    return conexion.execute(
        """
        SELECT 'BONO' AS tipo, NULL AS miembro_id, sb.minutos AS minutos, COALESCE(ci.fecha, v.fecha) AS fecha
        FROM sesion_bonos sb
        JOIN ventas v ON v.id = sb.venta_id
        LEFT JOIN cuenta_pc_items ci ON ci.sesion_bono_id = sb.id
        WHERE sb.sesion_id = ?
        UNION ALL
        SELECT 'BONO' AS tipo, NULL AS miembro_id, spb.minutos AS minutos, COALESCE(ci.fecha, v.fecha) AS fecha
        FROM sesion_pcstream_bonos spb
        JOIN ventas v ON v.id = spb.venta_id
        LEFT JOIN cuenta_pc_items ci ON ci.sesion_pcstream_bono_id = spb.id
        WHERE spb.sesion_id = ?
        UNION ALL
        SELECT 'BONO' AS tipo, NULL AS miembro_id, ci.minutos AS minutos, ci.fecha AS fecha
        FROM cuenta_pc_items ci
        JOIN cuentas_pc c ON c.id = ci.cuenta_id
        WHERE c.sesion_id = ? AND ci.tipo IN (?, ?) AND ci.venta_id IS NULL AND ci.quitado_fecha IS NULL
        UNION ALL
        SELECT 'SOCIO' AS tipo, m.miembro_id AS miembro_id, m.minutos AS minutos, m.fecha AS fecha
        FROM movimientos_saldo_miembro m
        WHERE m.sesion_id = ? AND m.tipo = ?
        ORDER BY fecha
        """,
        (sesion_id, sesion_id, sesion_id, *dominio.TIPOS_ITEM_CUENTA_CON_TIEMPO, sesion_id, dominio.MOVIMIENTO_CONSUMO),
    ).fetchall()


def reintegros_por_miembro(conexion, sesion_id: int, minutos_restantes: int) -> dict:
    """
    De los minutos que le quedaban a una sesión al cortarla, calcula
    cuántos hay que devolverle a CADA socio que la financió -- nunca a un
    socio distinto del que puso ese tramo, y nunca a costa de un bono
    (ver pcs_repo.finalizar_sesion).

    No alcanza con mirar `sesiones_pc.miembro_id`: se graba solo al CREAR
    la sesión (ver pcs_repo._abrir_o_extender_sesion), y una sesión puede
    haberse extendido después con un bono del mostrador o con el saldo de OTRO
    socio. Por eso se reconstruye el aporte de cada uno.

    El tiempo restante es siempre el TRAMO MÁS NUEVO de la sesión (el
    reloj cuenta para atrás desde fecha_fin_prevista, y cada aporte nuevo
    -- bono o saldo -- estira ese final más lejos en el tiempo): por eso
    se recorren las contribuciones de atrás para adelante, "gastando"
    minutos_restantes contra cada una hasta agotarlo. El tramo de cada
    aporte de un socio que cae, total o parcialmente, dentro de esa cola
    se le suma a lo que hay que devolverle a ESE socio puntual --
    redondeado hacia abajo a bloques de 30 al final, cada socio por
    separado (mismo criterio que el resto del sistema). El tramo que cae
    en un aporte de tipo BONO simplemente se descarta: un bono no
    reintegra, se pierda o no dentro del tiempo restante.
    """
    contribuciones = contribuciones_de_sesion(conexion, sesion_id)
    restantes = minutos_restantes
    por_miembro = {}
    for fila in reversed(contribuciones):
        if restantes <= 0:
            break
        tramo = min(fila["minutos"], restantes)
        if fila["tipo"] == "SOCIO":
            por_miembro[fila["miembro_id"]] = por_miembro.get(fila["miembro_id"], 0) + tramo
        restantes -= tramo
    return {
        miembro_id: (minutos // MINUTOS_POR_FRACCION) * MINUTOS_POR_FRACCION
        for miembro_id, minutos in por_miembro.items()
        if minutos >= MINUTOS_POR_FRACCION
    }
