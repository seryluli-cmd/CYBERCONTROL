"""
pcs_reiniciar_dialogo.py
========================
Reiniciar varias PCs de una vez (botón REINICIAR de abajo del mosaico de
Control de PCs, pedido del dueño 2026-10-22). Aparecen solo las PCs prendidas
y libres, todas marcadas: se desmarcan las que no se quieren reiniciar y se
manda. Igual que la ventana de DESCONGELAR, que arranca con las mismas
marcadas.

Cuáles son las prendidas y libres, y volver a mirarlas antes de mandar, es de
pcs_libres_repo: una PC donde se sentó un cliente mientras la ventana estaba
abierta no se reinicia.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QVBoxLayout

from control_pcs.repositories import comandos_pc_repo, pcs_libres_repo
from ui.utils import aplicar_clase, confirmar, crear_tabla, manejar_errores, mostrar_info, sin_boton_por_defecto


class DialogoReiniciar(QDialog):
    def __init__(self, estados, parent=None):
        """`estados`: lo último que leyó la pantalla de PCs (pcs_repo.estado_estaciones)."""
        super().__init__(parent)
        self.setWindowTitle("Reiniciar PCs prendidas y libres")
        self.resize(420, 560)

        explicacion = QLabel(
            "Están marcadas todas las PCs prendidas y libres. Desmarcá las que no quieras "
            "reiniciar. Las que tienen un cliente o están apagadas no aparecen."
        )
        explicacion.setWordWrap(True)

        self.tabla = crear_tabla(["PC"], estirar=0)
        for item in pcs_libres_repo.prendidas_y_libres(estados):
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            celda = QTableWidgetItem(item["estacion"]["nombre"])
            celda.setFlags(celda.flags() | Qt.ItemIsUserCheckable)
            celda.setCheckState(Qt.Checked)
            celda.setData(Qt.UserRole, item["estacion"]["id"])
            self.tabla.setItem(fila, 0, celda)

        boton_todas = QPushButton("Marcar todas")
        boton_todas.clicked.connect(lambda: self._marcar(Qt.Checked))
        boton_ninguna = QPushButton("Desmarcar todas")
        boton_ninguna.clicked.connect(lambda: self._marcar(Qt.Unchecked))
        fila_marcar = QHBoxLayout()
        fila_marcar.addWidget(boton_todas)
        fila_marcar.addWidget(boton_ninguna)
        fila_marcar.addStretch()

        self.boton_reiniciar = QPushButton("Reiniciar las marcadas")
        aplicar_clase(self.boton_reiniciar, "peligro")
        self.boton_reiniciar.clicked.connect(self._reiniciar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)
        fila_acciones = QHBoxLayout()
        fila_acciones.addWidget(self.boton_reiniciar)
        fila_acciones.addStretch()
        fila_acciones.addWidget(boton_cerrar)

        self.etiqueta_estado = QLabel("")
        self.etiqueta_estado.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(explicacion)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_marcar)
        layout.addLayout(fila_acciones)
        layout.addWidget(self.etiqueta_estado)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _marcar(self, estado):
        for fila in range(self.tabla.rowCount()):
            self.tabla.item(fila, 0).setCheckState(estado)

    def _marcadas(self) -> list:
        """(id, nombre) de las PCs marcadas."""
        celdas = (self.tabla.item(fila, 0) for fila in range(self.tabla.rowCount()))
        return [(celda.data(Qt.UserRole), celda.text()) for celda in celdas if celda.checkState() == Qt.Checked]

    @manejar_errores
    def _reiniciar(self):
        marcadas = self._marcadas()
        if not marcadas:
            self.etiqueta_estado.setText("Marcá al menos una PC.")
            return
        nombres = ", ".join(nombre for _id, nombre in marcadas)
        if not confirmar(
            self, "Reiniciar",
            f"Se van a reiniciar {len(marcadas)} PC(s):\n{nombres}\n\n"
            "Se pierde cualquier trabajo sin guardar en esas PCs. ¿Seguir?",
        ):
            return
        reiniciadas, salteadas = pcs_libres_repo.reiniciar([estacion_id for estacion_id, _nombre in marcadas])
        if reiniciadas:
            texto = (f"Se les va a avisar a {len(reiniciadas)} PC(s) en los próximos segundos.\n\n"
                     f"Si alguna no lo recibe en {comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO} minutos "
                     "(apagada o sin conexión), se descarta: así no le llega más tarde a otro cliente.")
        else:
            texto = "No se reinició ninguna PC."
        if salteadas:
            texto += f"\n\nNo se reiniciaron porque ya no estaban libres: {', '.join(salteadas)}."
        mostrar_info(self, "Reiniciar", texto)
        self.accept()
