"""
pcs_actualizacion_dialogo.py
============================
"Actualizar el Cliente PC de las PCs...": el Admin carga un PCcliente.exe nuevo, marca a qué PCs
va y ve, en palabras, cómo va cada una. Rehecha a pedido del dueño el 2026-10-19 (eligió la
maqueta "A": una tabla con casillas): antes había PCs "de prueba" y "Mandarla a TODAS", y no le
resultaba claro qué hacer ni cómo quedaba cada PC. Se refresca sola cada pocos segundos, así el
"Actualizada con éxito" aparece sin tocar nada. Se abre desde Gestionar Estaciones. Las reglas
-firmar, qué versión le toca a cada PC, cómo está cada una- son de `actualizacion_cliente_repo`.
"""

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QVBoxLayout,
)

from control_pcs.repositories import actualizacion_cliente_repo as repo
from errores import registrar_error
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, manejar_errores, mostrar_info, sin_boton_por_defecto,
)

FILTRO_EXE = "El Cliente PC (PCcliente.exe) (*.exe)"
COLUMNAS = ["", "PC", "Estado", "Versión en uso"]
COLUMNA_CASILLA, COLUMNA_PC, COLUMNA_ESTADO, COLUMNA_VERSION = range(4)
# Cada cuánto se vuelve a leer cómo está cada PC (las PCs cuentan cada 5 s).
REFRESCO_MS = 3000

# Colores de la columna Estado: (fondo, letra). Sin fondo, solo la letra en gris.
_VERDE = (QColor("#DCF3E1"), QColor("#1B5E20"))
_AZUL = (QColor("#DCE8FB"), QColor("#0D47A1"))
_ROJO = (QColor("#FBE3E1"), QColor("#B3261E"))
_AMARILLO = (QColor("#FFF3CD"), QColor("#7A5300"))
_GRIS = (None, QColor("#5F6B7A"))
COLORES = {
    repo.FUNCIONANDO: _VERDE, repo.LISTA: _VERDE, repo.COPIANDO: _AZUL,
    repo.ERROR: _ROJO, repo.FALLO: _ROJO, repo.ESPERANDO: _AMARILLO,
    repo.APAGADA: _GRIS, repo.NO_SELECCIONADA: _GRIS, repo.NUNCA_CONECTADA: _GRIS,
    repo.INSTALACION_VIEJA: _GRIS,
}
# Para el resumen de arriba: por qué le falta a cada una.
_POR_QUE_FALTA = {
    repo.APAGADA: "apagada", repo.COPIANDO: "copiando", repo.ERROR: "error", repo.FALLO: "falló",
    repo.ESPERANDO: "esperando", repo.NUNCA_CONECTADA: "nunca se conectó",
    repo.INSTALACION_VIEJA: "instalación vieja",
}

# Un número de versión (AAAAMMDDhhmmss) dentro de un texto que manda la PC.
_NUMERO_DE_VERSION = re.compile(r"\b20\d{12}\b")


def _con_fechas(texto: str) -> str:
    """El texto que manda la PC, con cada número de versión como fecha ("18/10/2026 19:30")."""
    return _NUMERO_DE_VERSION.sub(lambda m: repo.texto_version(m.group()), texto)


def texto_de_la_version(pc: dict) -> str:
    if pc["version"] is None:
        return "a mano (sin versión)" if pc["carpeta"] else ""
    return repo.texto_version(pc["version"])


def texto_del_estado(pc: dict) -> str:
    """Cómo va la actualización de una PC, en palabras, para la tabla."""
    situacion = repo.situacion(pc)
    detalle = _con_fechas(pc["detalle"])
    return {
        repo.NUNCA_CONECTADA: "Nunca se conectó a este CYBERCONTROL (¿apagada o con otro nombre?)",
        repo.INSTALACION_VIEJA: "Instalación vieja: hay que reinstalarla con el pendrive (preparar_pc.bat)",
        repo.NO_SELECCIONADA: "No seleccionada",
        repo.FUNCIONANDO: "Funcionando con la versión nueva",
        repo.LISTA: "Actualizada con éxito · se aplica en el próximo reinicio",
        repo.FALLO: f"Falló al arrancar: {detalle}",   # el detalle ya dice "volvió a la anterior"
        repo.APAGADA: "Apagada / sin conexión · se actualiza sola al prenderla",
        repo.COPIANDO: "Copiando…",
        repo.ERROR: f"Error: {detalle.rstrip('.')} · reintenta sola",
        repo.ESPERANDO: "Esperando",
    }[situacion]


def texto_del_resumen(pcs: list, hay_version: bool) -> str:
    """La línea de arriba de la tabla: cuántas de las marcadas ya están listas y qué les falta a
    las demás."""
    if not hay_version:
        return "Primero cargá la versión nueva con «Cargar versión nueva…»."
    marcadas = [pc for pc in pcs if pc["le_toca"] is not None]
    if not marcadas:
        return "Marcá las PCs que querés actualizar y tocá «Actualizar las seleccionadas»."
    faltan = [(pc["nombre"], repo.situacion(pc)) for pc in marcadas]
    faltan = [(nombre, situacion) for nombre, situacion in faltan if situacion not in repo.SITUACIONES_LISTAS]
    if not faltan:
        cuantas = len(marcadas)
        return (f"✔ Las {cuantas} PCs seleccionadas están actualizadas." if cuantas != 1
                else "✔ La PC seleccionada está actualizada.")
    listas = len(marcadas) - len(faltan)
    detalle = ", ".join(f"{nombre} ({_POR_QUE_FALTA[situacion]})" for nombre, situacion in faltan)
    return f"{listas} de {len(marcadas)} listas · faltan: {detalle}"


class DialogoActualizarCliente(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actualizar el Cliente PC de las PCs")
        self.resize(860, 600)
        self.pcs = []
        self._armar_interfaz()
        self._cargar()
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESCO_MS)
        self._timer.timeout.connect(self._refrescar_solo)
        self._timer.start()

    def _armar_interfaz(self):
        self.etiqueta_version = QLabel()
        self.etiqueta_version.setStyleSheet("font-weight: bold;")
        boton_cargar = QPushButton("Cargar versión nueva...")
        boton_cargar.clicked.connect(self._cargar_version)
        fila_version = QHBoxLayout()
        fila_version.addWidget(self.etiqueta_version, 1)
        fila_version.addWidget(boton_cargar)

        explicacion = QLabel(
            "Marcá las PCs y tocá «Actualizar las seleccionadas». Cada una copia la versión sola en "
            "unos segundos, aunque tenga un cliente, y acá te avisa «Actualizada con éxito». Se pone "
            "en uso en su próximo reinicio; si no arranca bien, vuelve sola a la anterior."
        )
        explicacion.setWordWrap(True)

        self.etiqueta_resumen = QLabel()
        self.etiqueta_resumen.setWordWrap(True)
        self.etiqueta_resumen.setStyleSheet("font-weight: bold;")

        self.tabla = crear_tabla(COLUMNAS, estirar=COLUMNA_ESTADO, por_filas=True)

        boton_todas = QPushButton("Marcar todas")
        boton_todas.clicked.connect(lambda: self._marcar_todas(True))
        boton_ninguna = QPushButton("Desmarcar todas")
        boton_ninguna.clicked.connect(lambda: self._marcar_todas(False))
        self.boton_actualizar = QPushButton("Actualizar las seleccionadas")
        aplicar_clase(self.boton_actualizar, "primario")
        self.boton_actualizar.clicked.connect(self._actualizar_seleccionadas)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)

        fila_abajo = QHBoxLayout()
        fila_abajo.addWidget(boton_todas)
        fila_abajo.addWidget(boton_ninguna)
        fila_abajo.addStretch()
        fila_abajo.addWidget(self.boton_actualizar)
        fila_abajo.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addLayout(fila_version)
        layout.addWidget(explicacion)
        layout.addWidget(self.etiqueta_resumen)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_abajo)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    # -- mostrar -----------------------------------------------------------------
    @manejar_errores
    def _cargar(self):
        """Todo de nuevo, con las casillas como están guardadas."""
        paquete = repo.paquete()
        if paquete is None:
            self.etiqueta_version.setText("Todavía no cargaste ninguna versión.")
        else:
            megas = f"{paquete['tamano'] / 1024 / 1024:.1f}".replace(".", ",")
            self.etiqueta_version.setText(
                f"Versión cargada: {repo.texto_version(paquete['version'])} ({megas} MB)")
        self._hay_version = paquete is not None
        self._mostrar(conservar_casillas=False)
        self._guardado = self._ids_marcados()

    def _refrescar_solo(self):
        """Lo que dispara el timer: sin carteles si algo falla (se volvería a mostrar cada 3 s); queda
        en el log de errores y la tabla sigue con lo último que leyó."""
        try:
            self._mostrar(conservar_casillas=True)
        except RuntimeError as error:
            if "already deleted" not in str(error):    # la ventana se está cerrando
                registrar_error(error, "Actualizar el Cliente PC: refrescar la tabla")
        except Exception as error:
            registrar_error(error, "Actualizar el Cliente PC: refrescar la tabla")

    def _mostrar(self, conservar_casillas: bool):
        """Vuelve a leer cómo está cada PC. Con `conservar_casillas`, lo que el Admin tildó y no
        guardó queda como está. Si son las mismas PCs, cambia los textos en su lugar (así no se
        mueve la tabla ni se pierde la fila elegida mientras se refresca)."""
        tildadas = self._ids_marcados() if conservar_casillas else None
        pcs = repo.estado_de_las_pcs()
        mismas = [pc["id"] for pc in pcs] == [pc["id"] for pc in self.pcs]
        self.pcs = pcs
        if not mismas:
            self.tabla.setRowCount(0)
        for fila, pc in enumerate(pcs):
            if not mismas:
                self.tabla.insertRow(fila)
                casilla = QTableWidgetItem()
                casilla.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
                self.tabla.setItem(fila, COLUMNA_CASILLA, casilla)
                for columna in (COLUMNA_PC, COLUMNA_ESTADO, COLUMNA_VERSION):
                    self.tabla.setItem(fila, columna, QTableWidgetItem())
            if tildadas is None or not mismas:
                marcada = pc["id"] in tildadas if tildadas is not None else pc["seleccionada"]
                self.tabla.item(fila, COLUMNA_CASILLA).setCheckState(
                    Qt.CheckState.Checked if marcada else Qt.CheckState.Unchecked)
            self._llenar_fila(fila, pc)
        if not mismas:
            for columna in (COLUMNA_CASILLA, COLUMNA_PC, COLUMNA_VERSION):
                self.tabla.resizeColumnToContents(columna)
        self.etiqueta_resumen.setText(texto_del_resumen(pcs, self._hay_version))

    def _llenar_fila(self, fila: int, pc: dict):
        nombre = self.tabla.item(fila, COLUMNA_PC)
        nombre.setText(pc["nombre"])
        nombre.setToolTip(f"Instalado en: {pc['carpeta']}" if pc["carpeta"] else "")
        estado = self.tabla.item(fila, COLUMNA_ESTADO)
        texto = texto_del_estado(pc)
        estado.setText(texto)
        estado.setToolTip(texto)    # un error largo puede no entrar entero
        fondo, letra = COLORES[repo.situacion(pc)]
        estado.setData(Qt.ItemDataRole.BackgroundRole, fondo)
        estado.setForeground(letra)
        self.tabla.item(fila, COLUMNA_VERSION).setText(texto_de_la_version(pc))

    def _ids_marcados(self) -> set:
        return {pc["id"] for fila, pc in enumerate(self.pcs)
                if self.tabla.item(fila, COLUMNA_CASILLA).checkState() == Qt.CheckState.Checked}

    # -- acciones ----------------------------------------------------------------
    def _marcar_todas(self, marcar: bool):
        estado = Qt.CheckState.Checked if marcar else Qt.CheckState.Unchecked
        for fila in range(self.tabla.rowCount()):
            self.tabla.item(fila, COLUMNA_CASILLA).setCheckState(estado)

    @manejar_errores
    def _cargar_version(self):
        ruta, _filtro = QFileDialog.getOpenFileName(self, "Elegir el PCcliente.exe nuevo", "", FILTRO_EXE)
        if not ruta:
            return
        with open(ruta, "rb") as archivo:
            datos = archivo.read()
        if not confirmar(
            self, "Cargar versión nueva",
            "¿Cargar este PCcliente.exe como la versión nueva de las PCs?\n\n"
            "No va a ninguna PC hasta que las marques y toques «Actualizar las seleccionadas»."
        ):
            return
        manifiesto = repo.publicar(datos)
        self._cargar()
        mostrar_info(self, "Versión cargada",
                     f"Versión {repo.texto_version(manifiesto['version'])} cargada y firmada.\n\n"
                     "Ahora marcá las PCs y tocá «Actualizar las seleccionadas».")

    @manejar_errores
    def _actualizar_seleccionadas(self):
        if not self._hay_version:
            mostrar_info(self, "Actualizar", "Primero cargá la versión nueva con «Cargar versión nueva…».")
            return
        ids = self._ids_marcados()
        if not ids and not self._guardado:
            mostrar_info(self, "Actualizar", "No marcaste ninguna PC.")
            return
        # Desmarcar una que ya la copió hace que la descarte: avisarlo antes.
        descartan = [pc["nombre"] for pc in self.pcs
                     if pc["id"] in self._guardado and pc["id"] not in ids and repo.situacion(pc) == repo.LISTA]
        if descartan and not confirmar(
            self, "Desmarcar",
            f"{', '.join(descartan)} ya {'la copiaron' if len(descartan) > 1 else 'la copió'} y todavía no "
            f"reinici{'aron' if len(descartan) > 1 else 'ó'}: si {'las' if len(descartan) > 1 else 'la'} "
            "desmarcás, la descarta y sigue con la que tiene. ¿Seguir?"
        ):
            return
        repo.guardar_seleccion(ids)
        self._guardado = set(ids)
        self._mostrar(conservar_casillas=True)
        if ids:
            mostrar_info(self, "Actualizar",
                         f"Listo: va a {len(ids)} PC{'s' if len(ids) != 1 else ''}. Cada una la copia sola en "
                         "unos segundos y acá vas a ver «Actualizada con éxito». Se pone en uso en su "
                         "próximo reinicio.")
        else:
            mostrar_info(self, "Actualizar", "Listo: la versión no va a ninguna PC.")

    def reject(self):
        """Cerrar con casillas cambiadas y sin tocar «Actualizar las seleccionadas» pregunta antes,
        para no perderlas."""
        if self._ids_marcados() != self._guardado and not confirmar(
            self, "Cambios sin guardar",
            "Cambiaste las casillas pero no tocaste «Actualizar las seleccionadas». ¿Cerrar igual?"
        ):
            return
        self._timer.stop()
        super().reject()
