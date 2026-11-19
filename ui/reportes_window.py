"""
reportes_window.py
=====================
Reportes, una sección por cada pregunta que se le hace a las ventas:

- Resumen de Ventas: cuánta plata se trabajó en un rango de fechas.
- Resumen del Día: un día abierto por turno, con quién cerró y si el sobre
  cuadró; Kiosko, Impresiones, Trámites, Alquiler de PCs y PlayStation 5 van en
  columnas aparte. Abajo, el detalle de todo lo vendido (venta por venta, por
  producto y por operador) del día o del turno que se toque (en su propio
  archivo, ui/reportes_detalle_dia.py).
- Por Turno: el total de un rango repartido entre Mañana/Tarde/Noche.
- Totales: Kiosko / Impresiones / Trámites / Alquiler de PCs / PlayStation 5,
  por turno, día, semana o rango.
- Ranking de Ventas: qué se vendió más -- artículos de kiosko, impresiones, bonos
  de PC, bonos de socios, cargas de saldo por tarifa, trámites y bonos de la
  PlayStation 5, todo junto, con una columna Categoría para distinguir de qué
  rubro vino cada fila (ver reportes_repo.ranking_ventas).
- Por Operador: quién vendió cuánto y, de cada uno, sus ventas con fecha y
  hora (en su propio archivo, ui/reportes_operador.py).
- PCSTREAM: cuánto se usa la PC de streaming, en tiempo y en plata, día por día
  (en su propio archivo, ui/reportes_pcstream.py).
- PCs: Socios y Bonos: lo que dejaron las PCs, separado en cargas a socios y
  bonos del mostrador, y comparado (ui/reportes_socios_bonos.py).

Con el diseño C que eligió el dueño el 2026-11-19: un menú a la izquierda en vez
de pestañas, el nombre de la sección grande arriba, los títulos en mayúscula y un
color por rubro (las piezas, en ui/reportes_piezas.py).

Las usa el Admin o una Empleada con `permiso_reportes`.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QListWidget,
    QTableWidgetItem, QHeaderView, QComboBox, QTabWidget, QWidget,
)

import dominio
from repositories import reportes_repo
from ui.dibujos_tabla import DelegadoEtiqueta, poner_cabecera_con_colores
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_VERDE, agregar_pastilla, cabecera_oscura, cifra_destacada, pie_de_ventana,
    titulo_de_seccion,
)
# Resumen del Día vive en su propio archivo; se importa también desde acá
# (ui.reportes_window.PestañaResumenDelDia), como antes de partirlo.
from ui.reportes_resumen_dia import PestañaResumenDelDia
from ui.reportes_operador import PestañaPorOperador
from ui.reportes_pcstream import PestañaPcstream
from ui.reportes_piezas import (
    TONO_DE_LA_COLUMNA, ancho_para_los_rubros, celda_de_plata, celda_de_rubro, etiqueta_de_rubros, panel_de_reporte,
    tarjeta_de_filtros, titulos_en_mayuscula,
)
from ui.reportes_socios_bonos import PestañaSociosYBonos
from ui.utils import (
    armar_filtro_por_fechas, formato_pesos, manejar_errores, sin_boton_por_defecto,
    crear_tabla, rango_de_fechas, hoy_del_local,
    mostrar_columna_entera,
)

# Margen de arriba del contenido de cada sección: lo separa del subtítulo gris.
MARGENES_DE_PESTAÑA = (0, 12, 0, 0)

# El menú de la izquierda: lo justo para "🖥️ PCS: SOCIOS Y BONOS" sin cortar.
ANCHO_DEL_MENU = 250


class ReportesWindow(QDialog):
    """
    El menú de las secciones a la izquierda y, a la derecha, el nombre de la
    elegida en grande, para qué sirve y su contenido (cada sección es un QWidget
    independiente que busca y se muestra solo, ver las clases de abajo).

    Por dentro sigue siendo un QTabWidget (`self.pestañas`) con la barra de
    pestañas escondida: el menú solo elige cuál se ve. Así cada sección conserva
    su nombre de pestaña (lo buscan las pruebas) y quien elija una pestaña por
    código mueve también el menú.

    La cabecera no lleva números: cada sección tiene su propio rango de fechas y
    un número arriba no diría de cuál es.
    """

    def __init__(self, parent=None):
        super().__init__(parent)
        # Para la hoja de estilos: los títulos y la letra de Reportes (ui/hoja_de_estilos.py).
        self.setObjectName("ventanaReportes")
        self.setWindowTitle("Reportes")
        # Ancho: el menú más el Resumen del Día, que tiene 13 columnas (con menos, la de
        # "Cerró", el nombre de quien cerró cada turno, corta el nombre). El mostrador
        # tiene 1920; nunca más que la pantalla, para que la ventana no se salga de ella.
        # Alto: el Resumen del Día lleva abajo el detalle de las ventas.
        ancho, alto = 1840, 900
        if self.screen() is not None:
            ancho = min(ancho, self.screen().availableGeometry().width() - 20)
            alto = min(alto, self.screen().availableGeometry().height() - 40)
        self.resize(ancho, alto)

        cabecera = cabecera_oscura(
            "📊", "REPORTES", "Lo vendido por día, por turno, por negocio, por artículo y por operador")
        agregar_pastilla(cabecera, "DÍAS DE 06:00 A 06:00", TONO_GRIS)

        self.menu = QListWidget()
        self.menu.setObjectName("menuReportes")
        self.menu.setFixedWidth(ANCHO_DEL_MENU)
        # Sin el recuadro de las pestañas: cada sección ya pone sus grillas en un panel
        # blanco, y con los dos bordes juntos se veía un cuadro adentro de otro.
        self.pestañas = QTabWidget()
        self.pestañas.setDocumentMode(True)
        for clase, icono, titulo, _para_que in SECCIONES:
            self.pestañas.addTab(clase(), titulo)
            self.menu.addItem(f"{icono}   {titulo.upper()}")
        self.pestañas.tabBar().hide()

        self.titulo = QLabel()
        self.titulo.setObjectName("tituloReporte")
        self.para_que = QLabel()
        self.para_que.setObjectName("subtituloReporte")

        self.menu.currentRowChanged.connect(self.pestañas.setCurrentIndex)
        self.pestañas.currentChanged.connect(self._al_cambiar_de_seccion)

        derecha = QVBoxLayout()
        derecha.setSpacing(2)
        derecha.addWidget(self.titulo)
        derecha.addWidget(self.para_que)
        derecha.addWidget(self.pestañas, 1)
        medio = QHBoxLayout()
        medio.setSpacing(16)
        medio.addWidget(self.menu)
        medio.addLayout(derecha, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(16, 16, 16, 12)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(medio, 1)
        # Cómo se cuenta un día en TODAS las secciones (pedido del dueño): sin
        # esto, ver la madrugada del 2 sumada en el día 1 parecería un error.
        layout.addWidget(pie_de_ventana(
            "Cada día va de las 06:00 a las 06:00 del día siguiente: el turno Noche "
            "(22 a 06) cuenta entero en el día en que empezó."
        ))
        self.setLayout(layout)
        self._al_cambiar_de_seccion(self.pestañas.currentIndex())
        sin_boton_por_defecto(self)

    def _al_cambiar_de_seccion(self, indice: int):
        """El menú, el título y el para qué de la sección que quedó a la vista."""
        if indice < 0:
            return
        self.menu.setCurrentRow(indice)
        _clase, _icono, titulo, para_que = SECCIONES[indice]
        self.titulo.setText(titulo.upper())
        self.para_que.setText(para_que)


class PestañaResumen(QWidget):
    """Total vendido, cantidad de ventas y desglose Efectivo/Digital de un
    rango de fechas, en las cifras grandes de Caja (piezas_ventana.cifra_destacada)."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True, dias_del_local=True)

        total = cifra_destacada("TOTAL VENDIDO", "", TONO_AZUL)
        efectivo = cifra_destacada("EFECTIVO", "Lo cobrado en efectivo", TONO_VERDE)
        digital = cifra_destacada("DIGITAL", "Lo cobrado por medios digitales", TONO_AZUL)
        self.etiqueta_total = total.valor
        self.etiqueta_cantidad = total.aclaracion
        self.etiqueta_efectivo = efectivo.valor
        self.etiqueta_digital = digital.valor
        cifras = QHBoxLayout()
        cifras.setSpacing(12)
        for cifra in (total, efectivo, digital):
            cifras.addWidget(cifra, 1)

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addWidget(tarjeta_de_filtros(filtros))
        layout.addLayout(cifras)
        layout.addStretch()
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        resumen = reportes_repo.resumen_ventas(desde, hasta)
        self.etiqueta_total.setText(formato_pesos(resumen["total"]))
        self.etiqueta_cantidad.setText(f"{resumen['cantidad_ventas']} venta(s)")
        self.etiqueta_efectivo.setText(formato_pesos(resumen["efectivo"]))
        self.etiqueta_digital.setText(formato_pesos(resumen["digital"]))


# Las columnas de "Por Turno". La última, sin título, es la que se estira: estirada
# la del turno, la etiqueta quedaba sola a la izquierda y los números lejos, del
# otro lado; estirada "Digital", con la plata a la derecha, quedaba lejos ese número.
_COLUMNAS_POR_TURNO = ["Turno", "Total vendido", "Ventas", "Efectivo", "Digital", ""]
_ANCHOS_POR_TURNO = (170, 190, 120, 190, 190)
# Cada columna de plata con su clave en reportes_repo.resumen_por_turno.
_PLATA_POR_TURNO = {1: "total", 3: "efectivo", 4: "digital"}
_COLUMNA_CANTIDAD_POR_TURNO = 2


class PestañaPorTurno(QWidget):
    """Desglosa el total vendido en un rango de fechas por turno
    (Mañana/Tarde/Noche), para responder "¿cuánto trabajó la Tarde esta
    semana?" sin tener que sumar a mano los cierres cargados."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(self._buscar, solo_hoy=True, dias_del_local=True)

        self.tabla = crear_tabla(_COLUMNAS_POR_TURNO, estirar=len(_COLUMNAS_POR_TURNO) - 1)
        titulos_en_mayuscula(self.tabla, a_la_derecha=(*_PLATA_POR_TURNO, _COLUMNA_CANTIDAD_POR_TURNO))
        for columna, ancho in enumerate(_ANCHOS_POR_TURNO):
            self.tabla.setColumnWidth(columna, ancho)
        # El turno en una etiqueta de color, siempre el mismo para cada uno (como el
        # rubro en Artículos); la celda sigue teniendo su texto.
        etiqueta_turno = DelegadoEtiqueta(self.tabla, grande=True)
        etiqueta_turno.colores_en_orden([turno.capitalize() for turno in dominio.TURNOS])
        self.tabla.setItemDelegateForColumn(0, etiqueta_turno)

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addWidget(tarjeta_de_filtros(filtros))
        layout.addWidget(panel_de_reporte(self.tabla), 1)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        filas = reportes_repo.resumen_por_turno(desde, hasta)

        self.tabla.setRowCount(0)
        for fila_datos in filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(fila_datos["turno"].capitalize()))
            cantidad = QTableWidgetItem(str(fila_datos["cantidad_ventas"]))
            cantidad.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
            self.tabla.setItem(fila, _COLUMNA_CANTIDAD_POR_TURNO, cantidad)
            for columna, clave in _PLATA_POR_TURNO.items():
                self.tabla.setItem(fila, columna, celda_de_plata(fila_datos[clave]))


# Las columnas de plata de la pestaña "Totales", en el orden en que se ven: son
# las claves de cada fila de reportes_repo.resumen_por_origen.
_COLUMNAS_DE_TOTALES = ("kiosko", "impresiones", "tramites", "pcs", "playstation", "total")


class PestañaKioskoVsPCs(QWidget):
    """Desglosa lo facturado en Kiosko, Impresiones, Trámites, Alquiler de PCs y
    PlayStation 5 (ver dominio.NOMBRE_ORIGEN_VENTA) en un rango de fechas,
    agrupado a elección por turno, día, semana o el total del rango completo.
    Cada rubro con una barra de su color abajo del título (el mismo color que en
    el Ranking y en el Historial del Turno)."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_agrupar = QComboBox()
        self.combo_agrupar.addItem("Total del rango", "rango")
        self.combo_agrupar.addItem("Por Turno", "turno")
        self.combo_agrupar.addItem("Por Día", "dia")
        self.combo_agrupar.addItem("Por Semana", "semana")
        self.combo_agrupar.currentIndexChanged.connect(self._buscar)

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, extras=[("Agrupar:", self.combo_agrupar)], solo_hoy=True, dias_del_local=True
        )

        self.tabla = crear_tabla(
            ["Período", "Kiosko", "Impresiones", "Trámites", "Alquiler de PCs", "PlayStation 5", "Total"],
            estirar=0,
        )
        plata = range(1, len(_COLUMNAS_DE_TOTALES) + 1)
        titulos_en_mayuscula(self.tabla, a_la_derecha=plata)
        for columna in plata:
            self.tabla.horizontalHeader().setSectionResizeMode(columna, QHeaderView.ResizeToContents)
        poner_cabecera_con_colores(self.tabla, {
            columna: TONO_DE_LA_COLUMNA[clave]
            for columna, clave in enumerate(_COLUMNAS_DE_TOTALES, start=1) if clave in TONO_DE_LA_COLUMNA
        })

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addWidget(tarjeta_de_filtros(filtros))
        layout.addWidget(panel_de_reporte(self.tabla), 1)
        # Alquiler de PCs va en el azul de los bonos de PC, pero junta más que eso.
        layout.addWidget(pie_de_ventana(
            "Impresiones y Trámites se muestran aparte: no están sumados en Kiosko. Alquiler de PCs junta "
            f"todo lo cobrado por las PCs: bonos, socios, {dominio.NOMBRE_PCSTREAM}, reservas y cuentas."
        ))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_fila(self, datos: dict, negrita: bool = False):
        """Una fila de la tabla; `datos` es una fila de
        reportes_repo.resumen_por_origen (o una armada igual, ver el TOTAL
        de _buscar)."""
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        periodo = QTableWidgetItem(datos["etiqueta"])
        if negrita:
            fuente = periodo.font()
            fuente.setBold(True)
            periodo.setFont(fuente)
        self.tabla.setItem(fila, 0, periodo)
        # La plata va siempre en negrita (y un "$ 0", en gris): ver como_plata.
        for columna, clave in enumerate(_COLUMNAS_DE_TOTALES, start=1):
            self.tabla.setItem(fila, columna, celda_de_plata(datos[clave]))

    @manejar_errores
    def _buscar(self, _=None):
        # El "_=None" no se usa: absorbe el índice que manda
        # `currentIndexChanged` (ver ControlCierresWindow._ver_detalle en
        # caja_window.py).
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        agrupar_por = self.combo_agrupar.currentData()
        filas = reportes_repo.resumen_por_origen(desde, hasta, agrupar_por)

        self.tabla.setRowCount(0)
        for fila_datos in filas:
            self._agregar_fila(fila_datos)

        # Fila TOTAL al pie cuando hay más de un período listado -- con
        # "Total del rango" ya sobraría, es la única fila que hay.
        if agrupar_por != "rango" and len(filas) > 1:
            sumas = {
                clave: sum(fila[clave] for fila in filas)
                for clave in _COLUMNAS_DE_TOTALES
            }
            self._agregar_fila({"etiqueta": "TOTAL", **sumas}, negrita=True)


# Las columnas del Ranking.
_COLUMNA_CATEGORIA = 1
_COLUMNA_CODIGO = 2
_COLUMNA_IMPORTE = 4


class PestañaRanking(QWidget):
    """Ranking de TODO lo vendido (kiosko, impresiones, bonos de PC, de socios y
    de la PlayStation 5, cargas de saldo y trámites) en un rango de fechas,
    ordenable por cantidad o por monto. La categoría va en una etiqueta del color
    de su rubro (reportes_piezas.RUBROS): bono de PC y bono de PlayStation 5, de
    colores distintos; las impresiones, aparte de Kiosko, como en Totales."""

    def __init__(self):
        super().__init__()
        self._armar_interfaz()
        self._buscar()

    def _armar_interfaz(self):
        self.combo_orden = QComboBox()
        self.combo_orden.addItem("Por Cantidad vendida", "cantidad")
        self.combo_orden.addItem("Por Monto ($)", "monto")

        self.fecha_desde, self.fecha_hasta, filtros = armar_filtro_por_fechas(
            self._buscar, hoy_del_local().addMonths(-1),
            extras=[("Ordenar:", self.combo_orden)], dias_del_local=True,
        )

        self.etiqueta_titulo = titulo_de_seccion("")

        self.tabla = crear_tabla(["Cantidad", "Categoría", "Código", "Descripción", "Importe"], estirar=3)
        titulos_en_mayuscula(self.tabla, a_la_derecha=(_COLUMNA_IMPORTE,))
        self.tabla.horizontalHeader().setSectionResizeMode(_COLUMNA_IMPORTE, QHeaderView.ResizeToContents)
        self.etiqueta_categoria = etiqueta_de_rubros(self.tabla)
        self.tabla.setItemDelegateForColumn(_COLUMNA_CATEGORIA, self.etiqueta_categoria)
        panel = panel_de_reporte(self.tabla)
        # La categoría entera y siempre del mismo ancho: el de la etiqueta más larga
        # de todas ("BONO DE PLAYSTATION 5"), aunque lo buscado no la tenga. Ya con la
        # tabla en su panel, para que el título se mida con la letra de Reportes.
        ancho_para_los_rubros(self.tabla, _COLUMNA_CATEGORIA, self.etiqueta_categoria)

        layout = QVBoxLayout()
        layout.setContentsMargins(*MARGENES_DE_PESTAÑA)
        layout.setSpacing(12)
        layout.addWidget(tarjeta_de_filtros(filtros))
        layout.addWidget(self.etiqueta_titulo)
        layout.addWidget(panel, 1)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _buscar(self):
        desde, hasta = rango_de_fechas(self.fecha_desde, self.fecha_hasta)
        orden = self.combo_orden.currentData()

        # En mayúscula, como todo título de sección (titulo_de_seccion lo pone solo al armarlo).
        self.etiqueta_titulo.setText(
            f"Ranking de Ventas del {self.fecha_desde.date().toString('dd/MM/yyyy')} "
            f"al {self.fecha_hasta.date().toString('dd/MM/yyyy')}".upper()
        )

        filas = reportes_repo.ranking_ventas(desde, hasta, orden)
        self.tabla.setRowCount(0)
        for fila_datos in filas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            categoria = reportes_repo.categoria_a_la_vista(fila_datos["categoria"], fila_datos["codigo"])
            self.tabla.setItem(fila, 0, QTableWidgetItem(str(fila_datos["cantidad"])))
            self.tabla.setItem(fila, _COLUMNA_CATEGORIA, celda_de_rubro(categoria))
            self.tabla.setItem(fila, _COLUMNA_CODIGO, QTableWidgetItem(fila_datos["codigo"]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(fila_datos["descripcion"]))
            self.tabla.setItem(fila, _COLUMNA_IMPORTE, celda_de_plata(fila_datos["importe"]))
        mostrar_columna_entera(self.tabla, _COLUMNA_CODIGO)


# Las secciones de Reportes, en el orden del menú de la izquierda: (sección,
# dibujito, título, para qué sirve). El título es también el nombre de su pestaña.
# Son emojis que el Windows del mostrador trae (el 🧊, por ejemplo, no: ver
# control_pcs/ui/pcs_dibujos.py).
SECCIONES = (
    (PestañaResumen, "📈", "Resumen de Ventas", "Cuánta plata se trabajó en un rango de fechas"),
    (PestañaResumenDelDia, "📅", "Resumen del Día", "Un día abierto por turno: quién cerró y si el sobre cuadró"),
    (PestañaPorTurno, "🕒", "Por Turno", "El total repartido entre Mañana, Tarde y Noche"),
    (PestañaKioskoVsPCs, "💰", "Totales", "Kiosko, Impresiones, Trámites, Alquiler de PCs y PlayStation 5"),
    (PestañaRanking, "🏆", "Ranking de Ventas", "Qué se vendió más, por cantidad o por monto"),
    (PestañaPorOperador, "👤", "Por Operador", "Quién vendió cuánto, venta por venta"),
    (PestañaPcstream, "🎥", dominio.NOMBRE_PCSTREAM, "La PC de streaming, en tiempo y en plata"),
    (PestañaSociosYBonos, "🖥️", "PCs: Socios y Bonos",
     "Lo que dejaron las PCs: cargas a socios y bonos del mostrador"),
)
