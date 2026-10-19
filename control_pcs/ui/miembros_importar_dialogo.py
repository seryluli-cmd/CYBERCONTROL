"""
miembros_importar_dialogo.py
==============================
"Importar de Excel": trae de una sola vez los socios del programa de cyber
anterior, con su usuario, nombre, contraseña y el tiempo que les quedaba
(pedido del dueño, 2026-10-19). Se abre desde Miembros y solo lo ve el
Administrador. La pantalla elige el archivo, muestra lo que va a pasar y pide
confirmación; qué se importa y cómo lo decide importar_miembros_repo.
"""

import os

from PySide6.QtWidgets import QDialog, QFileDialog, QLabel, QPlainTextEdit, QVBoxLayout

from control_pcs.repositories import importar_miembros_repo
from ui.utils import (
    fila_guardar_cancelar, formato_tiempo, manejar_errores, mostrar_aviso, mostrar_info, sin_boton_por_defecto,
)

FILTRO_EXCEL = "Planillas de Excel (*.xlsx);;Todos los archivos (*)"


def elegir_planilla(parent) -> str:
    """La ruta de la planilla elegida, o "" si se canceló."""
    ruta, _filtro = QFileDialog.getOpenFileName(parent, "Elegir la planilla de socios", "", FILTRO_EXCEL)
    return ruta


def texto_del_resumen(resumen: dict) -> str:
    """El resumen de importar_miembros_repo como texto para leer de corrido."""
    partes = []
    if resumen["nuevos"]:
        partes.append("Socios nuevos (usuario — nombre — tiempo):")
        partes += [f"  {socio['usuario']} — {socio['nombre']} — {_tiempo(socio['minutos'])}"
                   for socio in resumen["nuevos"]]
    if resumen["sin_tiempo"]:
        partes.append("\nNo se entiende el tiempo, entran con 0 (cargalo a mano si corresponde):")
        partes += [f"  {usuario} — la planilla dice \"{texto}\"" for usuario, texto in resumen["sin_tiempo"]]
    if resumen["con_poco_saldo"]:
        partes.append("\nCon menos de 30 minutos: para entrar a una PC tienen que cargar saldo "
                      "(lo que tienen se les suma):")
        partes.append("  " + ", ".join(resumen["con_poco_saldo"]))
    if resumen["ya_existen"]:
        partes.append("\nYa existen en el programa, no se tocan:")
        partes.append("  " + ", ".join(resumen["ya_existen"]))
    if resumen["con_problemas"]:
        partes.append("\nNo se pueden importar:")
        partes += [f"  Fila {fila}: {usuario or '(sin usuario)'} — {motivo}"
                   for fila, usuario, motivo in resumen["con_problemas"]]
    return "\n".join(partes)


def _tiempo(minutos: int) -> str:
    return formato_tiempo(minutos * 60)


class DialogoImportarMiembros(QDialog):
    """Muestra lo que va a hacer la importación y la hace si se confirma."""

    def __init__(self, usuario_operador, ruta: str, resumen: dict, parent=None):
        super().__init__(parent)
        self.usuario_operador = usuario_operador
        self.ruta = ruta
        self.resultado = None
        self.setWindowTitle("Importar socios del programa anterior")
        self.resize(640, 520)

        cantidad = len(resumen["nuevos"])
        encabezado = QLabel(
            f"Planilla: {os.path.basename(ruta)}\n\n"
            f"Se van a crear {cantidad} socios con {_tiempo(resumen['minutos_en_total'])} de tiempo en total. "
            "Entran con su usuario y contraseña de siempre; el DNI se lo pide su PC la primera vez."
        )
        encabezado.setWordWrap(True)
        detalle = QPlainTextEdit(texto_del_resumen(resumen))
        detalle.setReadOnly(True)

        layout = QVBoxLayout()
        layout.addWidget(encabezado)
        layout.addWidget(detalle)
        layout.addLayout(fila_guardar_cancelar(self, self._importar, f"Importar {cantidad} socios"))
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _importar(self):
        self.resultado = importar_miembros_repo.importar_planilla(self.ruta, self.usuario_operador["id"])
        self.accept()


def importar_de_excel(parent, usuario_operador) -> bool:
    """Todo el recorrido desde el botón: elegir la planilla, ver qué va a pasar
    y confirmar. True si se creó algún socio (para refrescar la lista).
    Los errores de lectura los muestra quien llama (manejar_errores)."""
    ruta = elegir_planilla(parent)
    if not ruta:
        return False
    resumen = importar_miembros_repo.revisar_planilla(ruta)
    if not resumen["nuevos"]:
        mostrar_aviso(parent, "Nada para importar",
                      "La planilla no tiene socios nuevos.\n\n" + texto_del_resumen(resumen))
        return False
    dialogo = DialogoImportarMiembros(usuario_operador, ruta, resumen, parent)
    if not dialogo.exec():
        return False
    resultado = dialogo.resultado
    mensaje = (f"Listo: se crearon {len(resultado['nuevos'])} socios con "
               f"{_tiempo(resultado['minutos_en_total'])} de tiempo en total.")
    if resultado["ya_existen"] or resultado["con_problemas"]:
        mensaje += "\n\n" + texto_del_resumen({**resultado, "nuevos": [], "sin_tiempo": [], "con_poco_saldo": []})
    mostrar_info(parent, "Socios importados", mensaje)
    return bool(resultado["nuevos"])
