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

Solo arman widgets con su objectName o su "clase": los colores están en
ui/hoja_de_estilos.py. Ninguna regla de esas va por tipo de widget, así que las
ventanas que se abren desde estas (avisos, confirmaciones) no heredan nada.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QFrame, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

from ui.utils import aplicar_clase

# Colores de las pastillas de la cabecera (QLabel#pastillaCabecera[tono=...]) y de las
# cifras destacadas (QFrame#cifraDestacada[tono=...], solo azul y verde).
TONO_AZUL = "azul"
TONO_VERDE = "verde"
TONO_CELESTE = "celeste"
TONO_NARANJA = "naranja"
TONO_ROJO = "rojo"
TONO_GRIS = "gris"

TEXTO_SOLO_ADMIN = "Solo el Administrador"


def cabecera_oscura(icono: str, titulo: str, detalle: str = "") -> QFrame:
    """La cabecera oscura de la ventana: dibujito, título y una línea de detalle a la
    izquierda; a la derecha, las pastillas que se le agreguen con `agregar_pastilla`.
    `cabecera.detalle` es la etiqueta del detalle, por si cambia, y `cabecera.icono` la
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
