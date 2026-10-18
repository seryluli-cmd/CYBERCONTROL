"""
pcs_actualizacion_dialogo.py
============================
"Actualizar el Cliente PC de las PCs...": el Admin carga un PCcliente.exe nuevo, elige a qué PCs
va (primero unas de prueba, después todas) y ve qué versión tiene cada PC y cómo va. Se abre
desde Gestionar Estaciones (Configuración ADMIN, exclusiva de ADMIN). Las reglas -firmar, qué
versión le toca a cada PC, qué PCs se pueden reiniciar- son de `actualizacion_cliente_repo`.
"""

import re

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox, QDialog, QFileDialog, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QVBoxLayout,
)

import dominio
from control_pcs.repositories import actualizacion_cliente_repo
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, formato_fecha_hora, manejar_errores, mostrar_info, sin_boton_por_defecto,
)

FILTRO_EXE = "El Cliente PC (PCcliente.exe) (*.exe)"
COLUMNAS = ["Prueba", "PC", "Versión instalada", "Estado", "Carpeta", "Última conexión"]


# Un número de versión (AAAAMMDDhhmmss) dentro de un texto que manda la PC.
_NUMERO_DE_VERSION = re.compile(r"\b20\d{12}\b")


def _con_fechas(texto: str) -> str:
    """El texto que manda la PC, con cada número de versión como fecha ("18/10/2026 19:30")."""
    return _NUMERO_DE_VERSION.sub(lambda m: actualizacion_cliente_repo.texto_version(m.group()), texto)


def texto_de_la_version(pc: dict) -> str:
    if pc["version"] is None:
        return "a mano (sin versión)" if pc["carpeta"] else ""
    return actualizacion_cliente_repo.texto_version(pc["version"])


def texto_del_estado(pc: dict) -> str:
    """Cómo va la actualización de una PC, para la tabla."""
    if pc["estado"] == dominio.ACTUALIZACION_BAJANDO:
        return "Bajándola..."
    if pc["estado"] == dominio.ACTUALIZACION_DESCARGADA:
        return "Bajada: se pone en el próximo reinicio"
    if pc["estado"] == dominio.ACTUALIZACION_ERROR:
        return f"No la pudo bajar: {_con_fechas(pc['detalle'])}"
    if pc["estado"] == dominio.ACTUALIZACION_FALLO:
        return f"FALLÓ: {_con_fechas(pc['detalle'])}"
    if not pc["carpeta"]:
        return "Sin actualización automática (instalación vieja)"
    if pc["le_toca"] is None:
        return ""
    if pc["version"] == pc["le_toca"]:
        return "Al día"
    return "Pendiente"


class DialogoActualizarCliente(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actualizar el Cliente PC de las PCs")
        self.resize(920, 620)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.etiqueta_version = QLabel()
        self.etiqueta_version.setStyleSheet("font-weight: bold;")
        boton_cargar = QPushButton("Cargar versión nueva...")
        aplicar_clase(boton_cargar, "primario")
        boton_cargar.clicked.connect(self._cargar_version)
        fila_version = QHBoxLayout()
        fila_version.addWidget(self.etiqueta_version, 1)
        fila_version.addWidget(boton_cargar)

        explicacion = QLabel(
            "Cada PC baja sola la versión que le toca, con la pantalla bloqueada, y la pone en uso en el "
            "próximo reinicio (el de después de cada cliente): nunca en medio de una sesión. Si no "
            "arranca bien, vuelve sola a la anterior. Una versión recién cargada va SOLO a las PCs "
            "marcadas como prueba: cuando veas que anda bien en ellas, marcá \"Mandarla a todas\"."
        )
        explicacion.setWordWrap(True)

        self.tabla = crear_tabla(COLUMNAS, estirar=3, por_filas=True)
        self.casilla_todas = QCheckBox("Mandarla a TODAS las PCs")

        boton_guardar = QPushButton("Guardar a qué PCs va")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_actualizar = QPushButton("Actualizar lista")
        boton_actualizar.clicked.connect(self._cargar_tabla)
        boton_reiniciar = QPushButton("Reiniciar las PCs libres que ya la bajaron")
        boton_reiniciar.clicked.connect(self._reiniciar_libres)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)

        fila_alcance = QHBoxLayout()
        fila_alcance.addWidget(self.casilla_todas)
        fila_alcance.addStretch()
        fila_alcance.addWidget(boton_guardar)

        fila_abajo = QHBoxLayout()
        fila_abajo.addWidget(boton_actualizar)
        fila_abajo.addWidget(boton_reiniciar)
        fila_abajo.addStretch()
        fila_abajo.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.addLayout(fila_version)
        layout.addWidget(explicacion)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_alcance)
        layout.addLayout(fila_abajo)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    # -- mostrar -----------------------------------------------------------------
    @manejar_errores
    def _cargar(self):
        paquete = actualizacion_cliente_repo.paquete()
        if paquete is None:
            self.etiqueta_version.setText("Todavía no cargaste ninguna versión.")
        else:
            megas = f"{paquete['tamano'] / 1024 / 1024:.1f}".replace(".", ",")
            self.etiqueta_version.setText(
                f"Versión cargada: {actualizacion_cliente_repo.texto_version(paquete['version'])} ({megas} MB)")
        self.casilla_todas.setChecked(actualizacion_cliente_repo.obtener_alcance()["para_todas"])
        self._cargar_tabla()
        self._guardado = self._lo_que_hay_en_pantalla()

    @manejar_errores
    def _cargar_tabla(self):
        """Recarga la tabla sin perder las casillas de prueba que el Admin ya tildó y no guardó."""
        tildadas = self._ids_de_prueba() if self.tabla.rowCount() else None
        self.pcs = actualizacion_cliente_repo.estado_de_las_pcs()
        self.tabla.setRowCount(0)
        for pc in self.pcs:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            casilla = QTableWidgetItem()
            casilla.setFlags(Qt.ItemFlag.ItemIsUserCheckable | Qt.ItemFlag.ItemIsEnabled)
            marcada = pc["id"] in tildadas if tildadas is not None else pc["en_prueba"]
            casilla.setCheckState(Qt.CheckState.Checked if marcada else Qt.CheckState.Unchecked)
            self.tabla.setItem(fila, 0, casilla)
            valores = (pc["nombre"], texto_de_la_version(pc), texto_del_estado(pc),
                       pc["carpeta"], formato_fecha_hora(pc["ultima_conexion"]) if pc["ultima_conexion"] else "")
            for columna, valor in enumerate(valores, start=1):
                item = QTableWidgetItem(valor)
                item.setToolTip(valor)   # el estado y la carpeta pueden no entrar enteros
                if columna == 3 and pc["estado"] == dominio.ACTUALIZACION_FALLO:
                    item.setForeground(Qt.GlobalColor.red)
                self.tabla.setItem(fila, columna, item)
        for columna in (0, 1, 2, 5):
            self.tabla.resizeColumnToContents(columna)

    def _ids_de_prueba(self) -> set:
        return {pc["id"] for fila, pc in enumerate(self.pcs)
                if self.tabla.item(fila, 0).checkState() == Qt.CheckState.Checked}

    def _lo_que_hay_en_pantalla(self):
        return (self.casilla_todas.isChecked(), self._ids_de_prueba())

    # -- acciones ----------------------------------------------------------------
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
            "Va primero SOLO a las PCs marcadas como prueba (y deja de ir a todas, si estaba así)."
        ):
            return
        manifiesto = actualizacion_cliente_repo.publicar(datos)
        self._cargar()
        de_prueba = len(actualizacion_cliente_repo.obtener_alcance()["prueba"])
        aviso = (f"Va a las {de_prueba} PC{'s' if de_prueba != 1 else ''} de prueba: la bajan solas y la ponen "
                 "en el próximo reinicio." if de_prueba
                 else "Todavía no va a ninguna PC: marcá una o dos como prueba y tocá \"Guardar a qué PCs va\".")
        mostrar_info(self, "Versión cargada",
                     f"Versión {actualizacion_cliente_repo.texto_version(manifiesto['version'])} cargada y firmada.\n\n{aviso}")

    @manejar_errores
    def _guardar(self):
        para_todas, ids = self._lo_que_hay_en_pantalla()
        if para_todas and not self._guardado[0] and not confirmar(
            self, "Mandarla a todas",
            "¿Mandar la versión cargada a TODAS las PCs? Cada una la pone en su próximo reinicio."
        ):
            return
        actualizacion_cliente_repo.guardar_alcance(para_todas, ids)
        self._guardado = self._lo_que_hay_en_pantalla()
        self._cargar_tabla()
        destino = "todas las PCs" if para_todas else f"{len(ids)} PC{'s' if len(ids) != 1 else ''} de prueba"
        mostrar_info(self, "Listo", f"Guardado: la versión cargada va a {destino}.")

    @manejar_errores
    def _reiniciar_libres(self):
        if not confirmar(
            self, "Reiniciar",
            "¿Reiniciar ahora las PCs SIN cliente que ya bajaron la versión? Así la ponen en uso "
            "sin esperar al próximo cliente. Las que tienen una sesión en curso no se tocan."
        ):
            return
        reiniciadas = actualizacion_cliente_repo.reiniciar_las_libres_que_ya_la_bajaron()
        mostrar_info(self, "Reiniciar",
                     f"Se mandó reiniciar: {', '.join(reiniciadas)}." if reiniciadas
                     else "No hay PCs libres con la versión ya bajada.")
        self._cargar_tabla()

    def reject(self):
        """Cerrar con cambios sin guardar en a qué PCs va pregunta antes, para no perderlos."""
        if self._lo_que_hay_en_pantalla() != self._guardado and not confirmar(
            self, "Cambios sin guardar", "No guardaste a qué PCs va la versión. ¿Cerrar igual?"
        ):
            return
        super().reject()
