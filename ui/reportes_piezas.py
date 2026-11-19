"""
reportes_piezas.py
==================
Lo que comparten las pestañas de Reportes con el diseño que eligió el dueño el
2026-11-19: la opción C ("todos los títulos de arriba en MAYÚSCULA y hacelo
profesional y bello") con un color por rubro ("todo lo que sea BONO de un color,
lo que sea Kiosko de otro... bono de PC y bono de PlayStation diferentes
colores"). Acá están los filtros en una tarjeta blanca, los títulos de las
columnas en mayúscula, la plata en negrita a la derecha con los ceros en gris, y
el nombre corto y el color de cada rubro (los colores son los de
ui/dibujos_tabla.py, los mismos en todo el programa).

Vive aparte de reportes_window.py porque lo usan también reportes_resumen_dia,
reportes_detalle_dia, reportes_operador, reportes_pcstream y
reportes_socios_bonos, que reportes_window importa: desde ahí sería un import
circular.
"""

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor
from PySide6.QtWidgets import QFrame, QHeaderView, QLabel, QPushButton, QTableWidgetItem

from repositories import reportes_repo
from ui.dibujos_tabla import (
    TONO_IMPRESIONES, TONO_KIOSKO, TONO_PCS, TONO_PCSTREAM, TONO_PLAYSTATION, TONO_RESERVAS, TONO_SOCIOS,
    TONO_TRAMITES, DelegadoEtiqueta, tonos_de_los_origenes,
)
from ui.piezas_ventana import panel_de_tabla
from ui.utils import formato_pesos

# Los renglones de las grillas de Reportes, un poco más altos que en el resto del
# programa (36): con los títulos en mayúscula y la plata en negrita se veían apretados.
ALTO_DE_RENGLON = 38

# Un "$ 0" va en gris claro y sin negrita: que salte a la vista lo que sí se vendió.
CERO_PESOS = formato_pesos(0)
COLOR_CERO = QColor("#A3ACBA")

# Cada categoría de reportes_repo con el nombre corto de su etiqueta y su color. El
# nombre completo se ve al pasar el mouse: "Carga de saldo de Socio (tarifa por
# hora)" no entraba en una etiqueta. Los dos de socios van del mismo color: son el
# mismo rubro ("lo que sea de una misma categoría, que mantengan color").
RUBROS = {
    reportes_repo.CATEGORIA_BONO_PC: ("Bono de PC", TONO_PCS),
    reportes_repo.CATEGORIA_BONO_PLAYSTATION: ("Bono de PlayStation 5", TONO_PLAYSTATION),
    reportes_repo.CATEGORIA_BONO_PCSTREAM: (reportes_repo.CATEGORIA_BONO_PCSTREAM, TONO_PCSTREAM),
    reportes_repo.CATEGORIA_KIOSKO: ("Kiosko", TONO_KIOSKO),
    reportes_repo.CATEGORIA_IMPRESIONES: ("Impresiones", TONO_IMPRESIONES),
    reportes_repo.CATEGORIA_TRAMITE: ("Trámite", TONO_TRAMITES),
    reportes_repo.CATEGORIA_CARGA_TARIFA_SOCIO: ("Carga de Socio", TONO_SOCIOS),
    reportes_repo.CATEGORIA_BONO_SOCIO: ("Bono de Socio", TONO_SOCIOS),
    reportes_repo.CATEGORIA_RESERVA: ("Reserva", TONO_RESERVAS),
}

# Las columnas de plata de cada rubro en TOTALES y en el Resumen del Día (las
# claves de reportes_repo.resumen_por_origen y turnos_repo.resumen_del_dia), con
# el color de la barra de su título. "pcs" (Alquiler de PCs) va en el azul de los
# bonos de PC aunque junta todo lo de las PCs: el pie de TOTALES lo aclara.
TONO_DE_LA_COLUMNA = {
    "kiosko": TONO_KIOSKO,
    "impresiones": TONO_IMPRESIONES,
    "tramites": TONO_TRAMITES,
    "pcs": TONO_PCS,
    "playstation": TONO_PLAYSTATION,
}


def panel_de_reporte(tabla) -> QFrame:
    """
    La grilla de una sección de Reportes en su panel blanco (panel_de_tabla) con
    renglones de ALTO_DE_RENGLON y los títulos de las columnas de Reportes (más
    aire y más espacio entre letras: la hoja de estilos los busca por la marca
    "deReporte" de la tabla).

    La marca va en la tabla y no se busca "adentro de la ventana de Reportes": cada
    sección se arma y se llena (y algunas fijan el alto o el ancho de las columnas
    según los títulos) ANTES de entrar a la ventana, y con la regla de la ventana
    los títulos se medían más chicos de lo que se dibujaban: salían mordidos y el
    TOTAL DEL DÍA, cortado (revisión del 2026-11-19). Se pone antes de armar el
    panel, porque la hoja se vuelve a leer cuando la tabla entra al panel.
    """
    tabla.setProperty("deReporte", True)
    return panel_de_tabla(tabla, ALTO_DE_RENGLON)


def tarjeta_de_filtros(filtros) -> QFrame:
    """
    La fila de filtros de una pestaña (fechas, Buscar...) adentro de una tarjeta
    blanca, con sus rótulos y botones en mayúscula (Qt no tiene text-transform).
    Los rótulos sueltos ("Desde:") pasan a llamarse "rotuloFiltro", para la hoja
    de estilos; los que ya tienen nombre (el día elegido del Resumen del Día)
    quedan como están. Se hace acá y no en ui.utils.armar_filtro_por_fechas
    porque esa fila la usan también pantallas que no son de Reportes.
    """
    tarjeta = QFrame()
    tarjeta.setObjectName("tarjetaFiltrosReporte")
    filtros.setContentsMargins(14, 10, 14, 10)
    tarjeta.setLayout(filtros)
    for numero in range(filtros.count()):
        widget = filtros.itemAt(numero).widget()
        if isinstance(widget, QLabel) and not widget.objectName():
            widget.setObjectName("rotuloFiltro")
            widget.setText(widget.text().upper())
        elif isinstance(widget, QPushButton):
            widget.setText(widget.text().upper())
    return tarjeta


def titulos_en_mayuscula(tabla, a_la_derecha=()):
    """
    Los títulos de las columnas de `tabla` en mayúscula y los de `a_la_derecha`
    (las de plata y números) alineados como sus celdas. Cambia solo lo que se ve:
    las listas de títulos de cada pestaña (las que se imprimen) quedan como están.
    """
    for columna in range(tabla.columnCount()):
        item = tabla.horizontalHeaderItem(columna)
        if item is None:
            continue
        item.setText(item.text().upper())
        if columna in a_la_derecha:
            item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)


def como_plata(item: QTableWidgetItem) -> QTableWidgetItem:
    """Una celda de plata como se ve en Reportes: a la derecha y en negrita; un
    "$ 0", en gris claro y sin negrita (salvo que ya tenga color, como una venta
    anulada en rojo: ese color manda)."""
    item.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
    fuente = item.font()
    if item.text() == CERO_PESOS:
        fuente.setBold(False)
        if item.data(Qt.ForegroundRole) is None:
            item.setForeground(COLOR_CERO)
    else:
        fuente.setBold(True)
    item.setFont(fuente)
    return item


def celda_de_plata(monto: float) -> QTableWidgetItem:
    """La celda de un monto (formato_pesos), con como_plata."""
    return como_plata(QTableWidgetItem(formato_pesos(monto)))


def etiqueta_de_rubros(tabla) -> DelegadoEtiqueta:
    """Lo que dibuja una columna Categoría o Rubro: cada rubro en su etiqueta de
    color, por su nombre corto (las celdas se llenan con celda_de_rubro). Una venta
    sin nada anotado de qué fue sale con el nombre de su origen ("Alquiler de PCs",
    ver detalle_dia_repo._sin_articulo): también con el color de su rubro."""
    delegado = DelegadoEtiqueta(tabla, grande=True)
    delegado.colores_fijos({**tonos_de_los_origenes(), **{corto: tono for corto, tono in RUBROS.values()}})
    return delegado


def etiqueta_de_origenes(tabla) -> DelegadoEtiqueta:
    """Lo que dibuja una columna Origen (Kiosko, Alquiler de PCs, PlayStation 5),
    con el color de su rubro."""
    delegado = DelegadoEtiqueta(tabla, grande=True)
    delegado.colores_fijos(tonos_de_los_origenes())
    return delegado


def nombre_corto(categoria: str) -> str:
    """El nombre de la etiqueta de una categoría de reportes_repo ("Carga de
    Socio"); una que no está en RUBROS queda como viene (y su etiqueta, en gris)."""
    return RUBROS.get(categoria, (categoria, None))[0]


def celda_de_rubro(categoria: str) -> QTableWidgetItem:
    """La celda de una categoría de reportes_repo: su nombre corto, y el completo
    al pasar el mouse."""
    item = QTableWidgetItem(nombre_corto(categoria))
    item.setToolTip(categoria)
    return item


def ancho_para_los_rubros(tabla, columna: int, delegado: DelegadoEtiqueta):
    """Fija `columna` al ancho de la etiqueta más larga de TODOS los rubros, aunque
    lo que se buscó no la tenga: así la columna no cambia de ancho con las fechas.
    Llamarla con la tabla ya llena si después se ajustan las columnas al contenido."""
    tabla.ensurePolished()
    ancho = max(delegado.ancho_para(corto, tabla.font()) for corto, _tono in RUBROS.values())
    cabecera = tabla.horizontalHeader()
    cabecera.setSectionResizeMode(columna, QHeaderView.Fixed)
    tabla.setColumnWidth(columna, max(ancho, cabecera.sectionSizeHint(columna)))
