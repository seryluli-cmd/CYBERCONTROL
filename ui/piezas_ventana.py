"""
ui/piezas_ventana.py
====================
Las piezas del diseño "clara con cabecera cyber" que eligió el dueño el 2026-10-26
(maqueta A, en PROPUESTA_VENTANAS_ADMIN) para Configuración ADMIN, Gestionar
Estaciones y Reservas, y después Administrar Kiosko, Caja y Cierre de Turno: la cabecera oscura como la barra de arriba del mostrador, con
una estela celeste como la del cometa del mosaico y pastillas con números; paneles
blancos con títulos de sección; tarjetas de menú (un botón con dibujito, título y una
línea de para qué es); cifras destacadas (un monto grande en un recuadro verde o azul) y
teclas con relieve.

Las listas (Artículos y las demás pantallas con una grilla) usan además la maqueta
B que eligió el dueño para el kiosko el 2026-10-30 y pidió también acá el
2026-10-31: indicadores con números grandes en la cabecera, un buscador grande,
filtros en pastillas, la grilla en un panel con renglones altos y una línea de
ayuda abajo (indicadores, buscador, fila_de_filtros, panel_de_tabla,
pie_de_ventana; lo que se dibuja adentro de las celdas, en ui/dibujos_tabla.py).

Solo arman widgets con su objectName o su "clase": los colores están en
ui/hoja_de_estilos.py. Ninguna regla de esas va por tipo de widget, así que las
ventanas que se abren desde estas (avisos, confirmaciones) no heredan nada.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QButtonGroup, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidget, QVBoxLayout, QWidget,
)

from ui.utils import aplicar_clase

# Colores de las pastillas de la cabecera (QLabel#pastillaCabecera[tono=...]) y de las
# cifras destacadas (QFrame#cifraDestacada[tono=...], solo azul y verde).
TONO_AZUL = "azul"
TONO_VERDE = "verde"
TONO_CELESTE = "celeste"
TONO_NARANJA = "naranja"
TONO_AMARILLO = "amarillo"
TONO_ROJO = "rojo"
TONO_GRIS = "gris"

TEXTO_SOLO_ADMIN = "Solo el Administrador"


def cabecera_oscura(icono: str, titulo: str, detalle: str = "") -> QFrame:
    """La cabecera oscura de la ventana: dibujito, título y una línea de detalle a la
    izquierda; a la derecha, las pastillas que se le agreguen con `agregar_pastilla`.
    `cabecera.titulo` y `cabecera.detalle` son sus etiquetas, por si cambian, y `cabecera.icono` la
    del dibujito (para ponerle uno dibujado: hay emojis que el mostrador no trae)."""
    cabecera = QFrame()
    cabecera.setObjectName("cabeceraOscura")
    capa = QVBoxLayout(cabecera)
    capa.setContentsMargins(18, 14, 18, 0)
    capa.setSpacing(12)

    etiqueta_icono = QLabel(icono)
    etiqueta_icono.setObjectName("iconoCabecera")
    cabecera.icono = etiqueta_icono
    etiqueta_titulo = QLabel(titulo)
    etiqueta_titulo.setObjectName("tituloCabecera")
    cabecera.titulo = etiqueta_titulo
    cabecera.detalle = QLabel(detalle)
    cabecera.detalle.setObjectName("detalleCabecera")
    textos = QVBoxLayout()
    textos.setSpacing(0)
    textos.addWidget(etiqueta_titulo)
    textos.addWidget(cabecera.detalle)

    cabecera.fila = QHBoxLayout()
    cabecera.fila.setSpacing(10)
    cabecera.fila.addWidget(etiqueta_icono)
    cabecera.fila.addSpacing(2)
    cabecera.fila.addLayout(textos)
    cabecera.fila.addStretch()
    capa.addLayout(cabecera.fila)

    # La estela: una línea que se aclara hacia la derecha, como la cola del cometa.
    estela = QFrame()
    estela.setObjectName("estelaCabecera")
    estela.setFixedHeight(2)
    capa.addWidget(estela)
    return cabecera


def agregar_pastilla(cabecera: QFrame, texto: str, tono: str) -> QLabel:
    """Una pastilla con un número a la derecha de la cabecera ("31 ESTACIONES")."""
    pastilla = QLabel(texto)
    pastilla.setObjectName("pastillaCabecera")
    pastilla.setProperty("tono", tono)
    # Centrada: si no, la etiqueta se estira al alto del título.
    cabecera.fila.addWidget(pastilla, 0, Qt.AlignVCenter)
    return pastilla


def panel_blanco() -> tuple:
    """Un panel blanco con bordes redondeados: (el panel, su layout vertical)."""
    panel = QFrame()
    panel.setObjectName("panelBlanco")
    capa = QVBoxLayout(panel)
    capa.setContentsMargins(16, 14, 16, 16)
    capa.setSpacing(10)
    return panel, capa


def cifra_destacada(titulo: str, aclaracion: str, tono: str) -> QFrame:
    """Un recuadro de color con un monto grande: el título chiquito arriba, la cifra y
    una línea que aclara qué suma ("Sin el cambio: lo cobrado en efectivo"). Es lo primero
    que se lee en Caja y en Cierre de Turno. `cifra.valor` es la etiqueta del monto."""
    cifra = QFrame()
    cifra.setObjectName("cifraDestacada")
    cifra.setProperty("tono", tono)
    capa = QVBoxLayout(cifra)
    capa.setContentsMargins(16, 12, 16, 12)
    capa.setSpacing(0)
    etiqueta_titulo = QLabel(titulo)
    etiqueta_titulo.setObjectName("tituloCifra")
    cifra.valor = QLabel()
    cifra.valor.setObjectName("valorCifra")
    cifra.aclaracion = QLabel(aclaracion)
    cifra.aclaracion.setObjectName("aclaracionCifra")
    capa.addWidget(etiqueta_titulo)
    capa.addWidget(cifra.valor)
    capa.addWidget(cifra.aclaracion)
    return cifra


def pastilla_clara(texto: str, tono: str, chica: bool = False) -> QLabel:
    """Una etiqueta de color suave ("ACTIVO", "V2", "FALTA DNI"), para usar sobre fondo
    claro (las de `agregar_pastilla` son para la cabecera oscura). `tono`: TONO_VERDE,
    TONO_AZUL, TONO_ROJO, TONO_NARANJA, TONO_AMARILLO o TONO_GRIS; `chica` la achica."""
    pastilla = QLabel(texto)
    pastilla.setObjectName("pastillaClara")
    pastilla.setProperty("tono", tono)
    pastilla.setProperty("chica", "true" if chica else "false")
    pastilla.setAlignment(Qt.AlignCenter)
    return pastilla


def titulo_de_seccion(texto: str) -> QLabel:
    """El título chiquito, en mayúscula y gris, de un grupo ("BONOS")."""
    etiqueta = QLabel(texto.upper())
    etiqueta.setObjectName("tituloDeSeccion")
    return etiqueta


def tarjeta_de_menu(icono: str, titulo: str, detalle: str, al_apretar, alto: int = 62,
                    tono: str = "") -> QPushButton:
    """
    Un botón grande con el dibujito a la izquierda, el título en mayúscula y negrita
    y debajo una línea de para qué es. El texto lo dibujan etiquetas de adentro, así
    que `text()` queda vacío: el título está en `accessibleName()` (lo usan las
    pruebas y los lectores de pantalla). `tono`: TONO_ROJO (lo peligroso, el título en
    rojo) o TONO_VERDE (fondo verdecito); sin tono, blanca.
    """
    boton = QPushButton()
    aplicar_clase(boton, "tarjetaMenu")
    if tono:
        boton.setProperty("tono", tono)
    boton.setAccessibleName(titulo)
    boton.setFixedHeight(alto)
    boton.clicked.connect(al_apretar)

    boton.icono = QLabel(icono)
    boton.icono.setObjectName("iconoTarjeta")
    boton.icono.setFixedWidth(30)
    boton.icono.setAlignment(Qt.AlignCenter)
    etiqueta_titulo = QLabel(titulo.upper())
    etiqueta_titulo.setObjectName("tituloTarjeta")
    boton.detalle = QLabel(detalle)
    boton.detalle.setObjectName("detalleTarjeta")
    for etiqueta in (boton.icono, etiqueta_titulo, boton.detalle):
        # Que el clic le llegue al botón aunque caiga sobre el texto.
        etiqueta.setAttribute(Qt.WA_TransparentForMouseEvents)

    textos = QVBoxLayout()
    textos.setSpacing(0)
    textos.addStretch()
    textos.addWidget(etiqueta_titulo)
    textos.addWidget(boton.detalle)
    textos.addStretch()
    capa = QHBoxLayout(boton)
    capa.setContentsMargins(14, 6, 12, 8)
    capa.setSpacing(12)
    capa.addWidget(boton.icono)
    capa.addLayout(textos, 1)
    return boton


def bloquear_tarjeta(tarjeta: QPushButton, motivo: str = TEXTO_SOLO_ADMIN):
    """Una tarjeta que quien la mira no puede usar: en gris y con candado, y en vez de
    para qué es, el `motivo`, para que se entienda por qué no se puede apretar."""
    tarjeta.setEnabled(False)
    tarjeta.icono.setText("🔒")
    tarjeta.detalle.setText(motivo)


def tecla(texto: str, al_apretar=None, clase: str = "teclaBlanca") -> QPushButton:
    """Un botón con relieve: "teclaBlanca", "teclaAzul" (la acción principal),
    "teclaVerde" o "teclaRoja" (lo peligroso y Cerrar)."""
    boton = QPushButton(texto)
    aplicar_clase(boton, clase)
    if al_apretar is not None:
        boton.clicked.connect(al_apretar)
    return boton


def linea_divisoria(vertical: bool = False) -> QFrame:
    """Una rayita gris para separar grupos de botones."""
    linea = QFrame()
    linea.setObjectName("lineaDivisoria")
    if vertical:
        linea.setFixedSize(1, 30)
    else:
        linea.setFixedHeight(1)
    return linea


def _repintar(widget):
    """Que Qt vuelva a mirar la hoja de estilos después de cambiar una propiedad."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def agregar_indicador(cabecera: QFrame, titulo: str) -> QFrame:
    """Un recuadro a la derecha de la cabecera con un número grande y, debajo, su
    título chiquito en mayúscula ("73 / ARTÍCULOS"). El número se pone con
    `poner_indicador`."""
    indicador = QFrame()
    indicador.setObjectName("indicadorCabecera")
    capa = QVBoxLayout(indicador)
    capa.setContentsMargins(14, 7, 18, 7)
    capa.setSpacing(0)
    indicador.valor = QLabel("—")
    indicador.valor.setObjectName("valorIndicador")
    etiqueta_titulo = QLabel(titulo.upper())
    etiqueta_titulo.setObjectName("tituloIndicador")
    capa.addWidget(indicador.valor)
    capa.addWidget(etiqueta_titulo)
    cabecera.fila.addWidget(indicador, 0, Qt.AlignVCenter)
    return indicador


def poner_indicador(indicador: QFrame, texto: str, alerta: bool = False):
    """El número de un indicador; con `alerta`, en rojo (lo que pide atención, como
    los artículos que quedaron bajo el mínimo)."""
    indicador.valor.setText(texto)
    for widget in (indicador, indicador.valor):
        widget.setProperty("alerta", alerta)
        _repintar(widget)


def buscador(texto: str) -> QLineEdit:
    """El campo grande para buscar en una lista, con la lupa adelante."""
    campo = QLineEdit()
    campo.setObjectName("buscador")
    campo.setPlaceholderText(f"🔍  {texto}")
    campo.setClearButtonEnabled(True)
    return campo


def fila_de_filtros(opciones, al_elegir, todos: str = "Todos") -> QWidget:
    """
    Una fila de pastillas para filtrar una lista: la primera (`todos`) muestra todo y
    cada una de `opciones` ((texto, valor), o solo el texto, que es también el valor)
    se queda con lo suyo. Se elige una sola a la vez; al cambiar se llama a
    `al_elegir(valor)`, con None para `todos`. `fila.elegido()` dice cuál está.
    """
    fila = QWidget()
    capa = QHBoxLayout(fila)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setSpacing(6)
    grupo = QButtonGroup(fila)
    grupo.setExclusive(True)
    valores = {}
    for texto, valor in [(todos, None)] + [o if isinstance(o, tuple) else (o, o) for o in opciones]:
        pastilla = QPushButton(texto.upper())
        aplicar_clase(pastilla, "filtro")
        pastilla.setCheckable(True)
        pastilla.setCursor(Qt.PointingHandCursor)
        grupo.addButton(pastilla)
        valores[pastilla] = valor
        capa.addWidget(pastilla)
    grupo.buttons()[0].setChecked(True)
    grupo.buttonClicked.connect(lambda pastilla: al_elegir(valores[pastilla]))
    capa.addStretch()
    fila.pastillas = grupo.buttons()
    fila.elegido = lambda: valores[grupo.checkedButton()]
    return fila


def panel_de_tabla(tabla: QTableWidget, alto_de_renglon: int = 36) -> QFrame:
    """La grilla de una lista dentro de un panel blanco redondeado, sin las rayas de
    la cuadrícula y con renglones más altos (los títulos de las columnas, en
    mayúscula y con la raya azul abajo, los pone la hoja de estilos)."""
    panel = QFrame()
    panel.setObjectName("panelTabla")
    capa = QVBoxLayout(panel)
    capa.setContentsMargins(1, 1, 1, 1)
    tabla.setShowGrid(False)
    tabla.verticalHeader().setDefaultSectionSize(alto_de_renglon)
    tabla.horizontalHeader().setHighlightSections(False)
    capa.addWidget(tabla)
    return panel


def pie_de_ventana(texto: str) -> QLabel:
    """La línea de ayuda gris de abajo de una lista ("Doble clic para modificar")."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("pieDeVentana")
    etiqueta.setWordWrap(True)
    return etiqueta


def marcar_solo_admin(boton: QPushButton):
    """Un botón que solo ve el Administrador: con el borde punteado, para que se
    sepa que una empleada no lo tiene."""
    boton.setProperty("soloAdmin", True)
    boton.setToolTip(TEXTO_SOLO_ADMIN)
    _repintar(boton)
