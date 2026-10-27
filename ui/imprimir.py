"""
imprimir.py
=============
Imprimir un listado, con vista previa (pedido del dueño, 2026-10-18: el detalle
de lo vendido como la planilla impresa de su programa anterior, pero renglón por
renglón con hora, turno y operador).

El listado se arma como HTML en un QTextDocument: Qt lo corta en hojas A4 solo,
repite los títulos de las columnas arriba de cada hoja y numera las hojas. La
vista previa tiene el botón de imprimir; con la impresora "Microsoft Print to
PDF" de Windows queda guardado como PDF.
"""

from datetime import datetime
from html import escape

from PySide6.QtCore import QMarginsF
from PySide6.QtGui import QFont, QPageLayout, QPageSize, QTextDocument
from PySide6.QtPrintSupport import QPrinter, QPrintPreviewDialog

_COLOR_ANULADA = "#C62828"
_FONDO_TITULOS = "#DDE3EC"
_FONDO_RENGLON_PAR = "#F3F5F8"


def html_del_listado(titulo, subtitulo, columnas, filas, a_la_derecha=(), pie=None, impreso=None) -> str:
    """
    El listado en HTML, listo para imprimir.

    - `filas`: lista de (valores, anulada); las anuladas salen en rojo.
    - `a_la_derecha`: números de las columnas que van alineadas a la derecha
      (cantidades y plata).
    - `pie`: los valores de la fila de totales, en negrita (o None).
    - `impreso`: la fecha y hora que se ve arriba a la derecha (la de ahora si
      no se pasa).
    """
    impreso = impreso or datetime.now()

    def celda(etiqueta, columna, valor, atributos=""):
        alineacion = "right" if columna in a_la_derecha else "left"
        return f'<{etiqueta} align="{alineacion}"{atributos}>{escape(str(valor))}</{etiqueta}>'

    partes = [
        '<table width="100%" cellspacing="0" cellpadding="0"><tr>',
        f'<td><span style="font-size: 14pt; font-weight: bold;">{escape(titulo)}</span><br>{escape(subtitulo)}</td>',
        f'<td align="right" valign="top">Impreso el {impreso.strftime("%d/%m/%Y %H:%M")}</td>',
        "</tr></table><br>",
        '<table width="100%" cellspacing="0" cellpadding="3">',
        f'<thead><tr bgcolor="{_FONDO_TITULOS}">',
        *(celda("th", columna, nombre) for columna, nombre in enumerate(columnas)),
        "</tr></thead>",
    ]
    for numero, (valores, anulada) in enumerate(filas):
        fondo = f' bgcolor="{_FONDO_RENGLON_PAR}"' if numero % 2 else ""
        color = f' style="color: {_COLOR_ANULADA};"' if anulada else ""
        partes.append(f"<tr{fondo}>")
        partes += [celda("td", columna, valor, color) for columna, valor in enumerate(valores)]
        partes.append("</tr>")
    if pie is not None:
        partes.append(f'<tr bgcolor="{_FONDO_TITULOS}">')
        partes += [celda("td", columna, valor, ' style="font-weight: bold;"') for columna, valor in enumerate(pie)]
        partes.append("</tr>")
    partes.append("</table>")
    return "".join(partes)


def _documento(html) -> QTextDocument:
    documento = QTextDocument()
    documento.setDefaultFont(QFont("Segoe UI", 8))
    documento.setHtml(html)
    return documento


def _impresora(nombre) -> QPrinter:
    """Hoja A4 parada, con márgenes de 12 mm."""
    impresora = QPrinter(QPrinter.HighResolution)
    impresora.setPageLayout(QPageLayout(
        QPageSize(QPageSize.A4), QPageLayout.Portrait, QMarginsF(12, 12, 12, 12), QPageLayout.Millimeter,
    ))
    impresora.setDocName(nombre)
    return impresora


def vista_previa(parent, html, nombre):
    """Abre la vista previa de impresión de `html` (de html_del_listado). Desde
    ahí se imprime; `nombre` es el título de la ventana y del trabajo de
    impresión (y el nombre que propone el PDF)."""
    documento = _documento(html)
    # La impresora tiene que quedar en una variable hasta que se cierra la vista
    # previa: el diálogo la usa pero no la guarda, y pasada sin variable Python la
    # borraba al toque. La vista previa leía memoria liberada y el programa se
    # cerraba sin ningún cartel (Control de Stock > Imprimir, 2026-10-26).
    impresora = _impresora(nombre)
    dialogo = QPrintPreviewDialog(impresora, parent)
    dialogo.setWindowTitle(f"Vista previa · {nombre}")
    dialogo.paintRequested.connect(documento.print_)
    dialogo.resize(1000, 860)
    dialogo.exec()
