"""
excel.py
==========
Bajar un listado a Excel (pedido del dueño, 2026-10-24: el Historial de Cargas
de Miembros y Reportes > PCs: Socios y Bonos). Arma un .xlsx de verdad, con
la fila de títulos en negrita y fija, filtros en los títulos, y números,
pesos, fechas y tiempos que Excel suma y ordena (no textos).

Sin librerías aparte: un .xlsx es un .zip con unos pocos XML adentro, y para
una sola hoja alcanza con escribirlos a mano. Así el programa no suma otra
dependencia ni crece el .exe. Excel guarda los formatos siempre en inglés
("#,##0") y los muestra con la coma y el punto de la PC. Los montos van sin
centavos, como en el programa (pedido del dueño 2026-10-26); la celda guarda el
número exacto. Probado abriéndolo
con Excel 16 (2026-10-24): sin carteles de "reparar", con filtros y la fila
de títulos fija.

guardar_xlsx no usa Qt (se prueba solo); bajar_a_excel es lo que llaman las
pantallas: pregunta dónde guardarlo y ofrece abrirlo.
"""

import os
import re
import zipfile
from datetime import datetime
from xml.sax.saxutils import escape

from PySide6.QtCore import QStandardPaths, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import QFileDialog

from ui.utils import confirmar, mostrar_error

# Formatos de columna que entiende guardar_xlsx.
TEXTO = "texto"
ENTERO = "entero"
PESOS = "pesos"
FECHA_HORA = "fecha_hora"
HORAS = "horas"            # minutos, que Excel muestra como "3:30" y suma bien
PORCENTAJE = "porcentaje"  # de 0 a 100, como lo dan los repos

# Número de estilo (posición en cellXfs de _ESTILOS) de cada formato; con
# negrita, el de al lado (+1).
_ESTILO = {TEXTO: 1, ENTERO: 3, PESOS: 5, FECHA_HORA: 7, HORAS: 9, PORCENTAJE: 11}
_ESTILO_TITULO = 13
_ANCHO = {TEXTO: 18, ENTERO: 10, PESOS: 15, FECHA_HORA: 17, HORAS: 10, PORCENTAJE: 10}

_ESTILOS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
<numFmts count="4">
<numFmt numFmtId="164" formatCode="&quot;$&quot; #,##0"/>
<numFmt numFmtId="165" formatCode="dd/mm/yyyy hh:mm"/>
<numFmt numFmtId="166" formatCode="[h]:mm"/>
<numFmt numFmtId="167" formatCode="0.0%"/>
</numFmts>
<fonts count="2"><font><sz val="11"/><name val="Calibri"/></font><font><b/><sz val="11"/><name val="Calibri"/></font></fonts>
<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill>
<fill><patternFill patternType="solid"><fgColor rgb="FFDDE3EC"/><bgColor indexed="64"/></patternFill></fill></fills>
<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>
<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
<cellXfs count="14">
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
<xf numFmtId="0" fontId="1" fillId="0" borderId="0" xfId="0" applyFont="1"/>
<xf numFmtId="1" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="1" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="164" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="164" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="165" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="165" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="166" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="166" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="167" fontId="0" fillId="0" borderId="0" xfId="0" applyNumberFormat="1"/>
<xf numFmtId="167" fontId="1" fillId="0" borderId="0" xfId="0" applyNumberFormat="1" applyFont="1"/>
<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFont="1" applyFill="1"/>
</cellXfs>
<cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>"""

_TIPOS = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
<Default Extension="xml" ContentType="application/xml"/>
<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
<Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>"""

_RELACIONES = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>"""

_RELACIONES_LIBRO = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
<Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
<Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>"""

_FECHA_CERO = datetime(1899, 12, 30)


def _columna(numero: int) -> str:
    """0 -> "A", 25 -> "Z", 26 -> "AA"."""
    letras = ""
    numero += 1
    while numero:
        numero, resto = divmod(numero - 1, 26)
        letras = chr(65 + resto) + letras
    return letras


def _nombre_de_hoja(nombre: str) -> str:
    """Excel no acepta estos caracteres ni más de 31 letras en el nombre de una hoja."""
    for prohibido in '[]:*?/\\':
        nombre = nombre.replace(prohibido, "-")
    return nombre[:31] or "Hoja1"


def _celda(referencia: str, valor, formato: str, negrita: bool) -> str:
    if valor is None or valor == "":
        return ""
    negrita = 1 if negrita else 0
    if formato == FECHA_HORA and isinstance(valor, datetime):
        valor = (valor - _FECHA_CERO).total_seconds() / 86400
    elif formato == HORAS and isinstance(valor, (int, float)):
        valor = valor / 1440
    elif formato == PORCENTAJE and isinstance(valor, (int, float)):
        valor = valor / 100
    if isinstance(valor, bool) or not isinstance(valor, (int, float)):
        # Un texto (el "TOTAL" en una columna de fechas, por ejemplo) va con el
        # estilo de texto, cualquiera sea su columna.
        texto = escape(str(valor))
        return (f'<c r="{referencia}" s="{_ESTILO[TEXTO] + negrita}" t="inlineStr">'
                f'<is><t xml:space="preserve">{texto}</t></is></c>')
    return f'<c r="{referencia}" s="{_ESTILO[formato] + negrita}"><v>{valor!r}</v></c>'


def _ancho(numero: int, titulo: str, formato: str, filas, totales) -> int:
    """El ancho de una columna: el de su formato, o lo que pida su título (con
    lugar para la flechita del filtro) o su texto más largo, hasta 60."""
    textos = [fila[numero] for fila in list(filas) + ([totales] if totales else [])
              if numero < len(fila) and isinstance(fila[numero], str)]
    return min(max(_ANCHO[formato], len(titulo) + 4, *(len(texto) + 2 for texto in textos)), 60)


def _hoja(columnas, filas, totales) -> str:
    formatos = [formato for _, formato in columnas]
    ultima = _columna(len(columnas) - 1)
    renglones = ['<row r="1">' + "".join(
        f'<c r="{_columna(i)}1" s="{_ESTILO_TITULO}" t="inlineStr"><is><t>{escape(titulo)}</t></is></c>'
        for i, (titulo, _) in enumerate(columnas)
    ) + "</row>"]
    numero = 1
    for fila in filas:
        numero += 1
        renglones.append(f'<row r="{numero}">' + "".join(
            _celda(f"{_columna(i)}{numero}", valor, formatos[i], False) for i, valor in enumerate(fila)
        ) + "</row>")
    hasta_los_datos = numero
    if totales is not None:
        numero += 2  # un renglón vacío antes, para que el filtro no lo agarre
        renglones.append(f'<row r="{numero}">' + "".join(
            _celda(f"{_columna(i)}{numero}", valor, formatos[i], True) for i, valor in enumerate(totales)
        ) + "</row>")
    anchos = "".join(
        f'<col min="{i + 1}" max="{i + 1}" width="{_ancho(i, titulo, formato, filas, totales)}" customWidth="1"/>'
        for i, (titulo, formato) in enumerate(columnas)
    )
    return (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
        '<sheetViews><sheetView workbookViewId="0">'
        '<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>'
        '</sheetView></sheetViews>'
        f'<cols>{anchos}</cols>'
        f'<sheetData>{"".join(renglones)}</sheetData>'
        f'<autoFilter ref="A1:{ultima}{hasta_los_datos}"/>'
        '</worksheet>'
    )


def guardar_xlsx(ruta: str, nombre_hoja: str, columnas, filas, totales=None):
    """
    Graba en `ruta` un .xlsx de una hoja.

    - `columnas`: lista de (título, formato), con formato TEXTO, ENTERO,
      PESOS, FECHA_HORA (un datetime), HORAS (minutos) o PORCENTAJE (0 a 100).
    - `filas`: listas de valores en el orden de las columnas (None = vacía).
    - `totales`: una fila más, en negrita, separada por un renglón vacío.
    """
    libro = (
        '<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
        '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
        'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
        f'<sheets><sheet name="{escape(_nombre_de_hoja(nombre_hoja), {chr(34): "&quot;"})}" sheetId="1" r:id="rId1"/></sheets>'
        '</workbook>'
    )
    with zipfile.ZipFile(ruta, "w", zipfile.ZIP_DEFLATED) as archivo:
        archivo.writestr("[Content_Types].xml", _TIPOS)
        archivo.writestr("_rels/.rels", _RELACIONES)
        archivo.writestr("xl/workbook.xml", libro)
        archivo.writestr("xl/_rels/workbook.xml.rels", _RELACIONES_LIBRO)
        archivo.writestr("xl/styles.xml", _ESTILOS)
        archivo.writestr("xl/worksheets/sheet1.xml", _hoja(columnas, filas, totales))


def nombre_de_archivo(titulo: str, desde: str, hasta: str) -> str:
    """ "Historial de Cargas del 01-10-2026 al 24-10-2026.xlsx" (fechas "YYYY-MM-DD")."""
    def dia(fecha):
        return datetime.strptime(fecha, "%Y-%m-%d").strftime("%d-%m-%Y")
    rango = f"del {dia(desde)}" if desde == hasta else f"del {dia(desde)} al {dia(hasta)}"
    return re.sub(r'[<>:"/\|?*]', "-", f"{titulo} {rango}.xlsx")


def bajar_a_excel(parent, nombre_sugerido: str, nombre_hoja: str, columnas, filas, totales=None) -> str:
    """Pregunta dónde guardar (arranca en el Escritorio), graba el .xlsx con
    guardar_xlsx y ofrece abrirlo. Devuelve la ruta, o "" si se canceló o no
    se pudo grabar."""
    escritorio = QStandardPaths.writableLocation(QStandardPaths.DesktopLocation)
    ruta, _ = QFileDialog.getSaveFileName(
        parent, "Bajar a Excel", os.path.join(escritorio, nombre_sugerido), "Excel (*.xlsx)"
    )
    if not ruta:
        return ""
    if not ruta.lower().endswith(".xlsx"):
        ruta += ".xlsx"
    try:
        guardar_xlsx(ruta, nombre_hoja, columnas, filas, totales)
    except OSError as error:
        # Lo más común: el mismo archivo está abierto en Excel, que no deja pisarlo.
        mostrar_error(parent, "No se pudo guardar",
                      f"No se pudo grabar {os.path.basename(ruta)}.\nSi está abierto en Excel, cerralo y "
                      f"probá de nuevo.\n\n({error.strerror or error})")
        return ""
    if confirmar(parent, "Bajar a Excel", f"Listo, se guardó en:\n{ruta}\n\n¿Abrirlo ahora?"):
        QDesktopServices.openUrl(QUrl.fromLocalFile(ruta))
    return ruta
