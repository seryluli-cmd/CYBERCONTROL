"""
pcstream_repo.py
==================
PCSTREAM, la PC de streaming del local (pedido del dueño, 2026-10-17): una PC
como cualquier otra -- es una fila de "estaciones", tiene Cliente PC, se
bloquea cuando se le acaba el tiempo y sus sesiones son de "sesiones_pc" --
pero se cobra con SUS precios. Se la reconoce solo por el nombre
(`dominio.es_pcstream`): si el Admin la renombra, vuelve a ser una PC común.

Lo que tiene de distinto, y dónde se hace cumplir:
- Catálogo de bonos propio (tabla bonos_pcstream, acá abajo). Venderle un bono
  sigue siendo `pcs_repo.asignar_bono`, que mira el nombre de la estación y
  busca el bono SOLO en el catálogo que le corresponde: a PCSTREAM no se le
  puede vender un bono común, ni un bono de PCSTREAM a otra PC.
- Los socios no la pueden abrir con su saldo (`miembros_repo.abrir_estacion_por_miembro`).
- No entra en "Intercambiar de máquina" (`pcs_repo.trasladar_sesion`): pasarle
  la sesión de una PC común le daría el tiempo barato a la PC cara, o al revés.
- En el mosaico va al lado de la PlayStation 5 (`pcs_repo._orden_natural`).

La plata que cobra entra a la caja como "Alquiler de PCs" (es una PC): no hay
un origen de venta aparte. Lo que se vendió y se usó de PCSTREAM se ve en
Reportes > PCSTREAM (`uso_por_dia`).

Crear/editar/dar de baja sus bonos es exclusivo de ADMIN desde "Configuración
ADMIN", igual que el catálogo de las demás PCs: se aplica en la pantalla, como
en pcs_repo y bonos_miembro_repo.
"""

from datetime import datetime

import dominio
from database import conexion_db
from control_pcs.repositories.catalogo_bonos import CatalogoDeBonos

# Mismo mecanismo que los otros tres catálogos, otra tabla. Un bono dado de baja
# no se borra: queda referenciado desde sesion_pcstream_bonos.
_catalogo_bonos = CatalogoDeBonos("bonos_pcstream")
listar_bonos = _catalogo_bonos.listar
obtener_bono = _catalogo_bonos.obtener
crear_bono = _catalogo_bonos.crear
modificar_bono = _catalogo_bonos.modificar
desactivar_bono = _catalogo_bonos.desactivar


def _dia_vacio(dia: str) -> dict:
    return {"dia": dia, "sesiones": 0, "bonos": 0, "minutos_vendidos": 0,
            "segundos_de_uso": 0, "recaudado": 0.0}


def uso_por_dia(desde: str, hasta: str) -> dict:
    """
    Cuánto se usó PCSTREAM entre dos fechas ("YYYY-MM-DD", incluidas las dos
    puntas), día por día. Cada día trae:

    - "bonos", "minutos_vendidos" y "recaudado": los bonos que se le vendieron,
      cuánto tiempo sumaban y cuánta plata entró. Solo ventas confirmadas (una
      anulada no cuenta, mismo criterio que el resto de Reportes).
    - "sesiones" y "segundos_de_uso": cuántas veces se la usó y cuánto tiempo
      estuvo habilitada de verdad. Puede ser menos que lo vendido si alguien
      cortó antes ("Finalizar Sesión"): el tiempo pago que no se usó no se
      reintegra, pero acá se ve. Cada sesión cuenta entera en el día en que
      arrancó, aunque termine pasada la medianoche.

    Las sesiones de PCSTREAM se reconocen por tener un bono de PCSTREAM
    (sesion_pcstream_bonos), no por el nombre actual de la estación: renombrarla
    después no borra su historial de este reporte.

    Devuelve {"dias": [...] (solo los días con algo, en orden), "total": {...}}
    -- el total con las mismas claves, sin "dia".
    """
    ahora = datetime.now()
    with conexion_db() as conexion:
        ventas = conexion.execute(
            """
            SELECT date(ventas.fecha) AS dia, COUNT(*) AS bonos,
                   SUM(spb.minutos) AS minutos, SUM(spb.precio) AS recaudado
            FROM sesion_pcstream_bonos spb
            JOIN ventas ON ventas.id = spb.venta_id
            WHERE ventas.estado = ? AND ventas.fecha >= date(?) AND ventas.fecha < date(?, '+1 day')
            GROUP BY dia
            """,
            (dominio.VENTA_CONFIRMADA, desde, hasta),
        ).fetchall()
        sesiones = conexion.execute(
            """
            SELECT fecha_inicio, fecha_fin_prevista, fecha_fin_real FROM sesiones_pc
            WHERE id IN (SELECT sesion_id FROM sesion_pcstream_bonos)
              AND fecha_inicio >= date(?) AND fecha_inicio < date(?, '+1 day')
            """,
            (desde, hasta),
        ).fetchall()

    dias = {}
    for fila in ventas:
        dia = dias.setdefault(fila["dia"], _dia_vacio(fila["dia"]))
        dia["bonos"] = fila["bonos"]
        dia["minutos_vendidos"] = fila["minutos"] or 0
        dia["recaudado"] = round(fila["recaudado"] or 0.0, 2)

    for sesion in sesiones:
        inicio = datetime.fromisoformat(sesion["fecha_inicio"])
        fin_previsto = datetime.fromisoformat(sesion["fecha_fin_prevista"])
        # Una sesión en curso cuenta hasta ahora; una cerrada, hasta que se
        # cerró -- y nunca más allá de su vencimiento: si el programa estaba
        # cerrado cuando se le acabó el tiempo, se la da de baja recién al
        # abrirlo, pero la PC ya se había bloqueado sola a la hora.
        fin = ahora if sesion["fecha_fin_real"] is None else datetime.fromisoformat(sesion["fecha_fin_real"])
        segundos = max(0, int((min(fin, fin_previsto) - inicio).total_seconds()))
        dia = dias.setdefault(inicio.date().isoformat(), _dia_vacio(inicio.date().isoformat()))
        dia["sesiones"] += 1
        dia["segundos_de_uso"] += segundos

    lista = [dias[clave] for clave in sorted(dias)]
    total = {
        clave: sum(dia[clave] for dia in lista)
        for clave in ("sesiones", "bonos", "minutos_vendidos", "segundos_de_uso", "recaudado")
    }
    total["recaudado"] = round(total["recaudado"], 2)
    return {"dias": lista, "total": total}
