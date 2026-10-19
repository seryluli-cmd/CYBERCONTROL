"""
pcs_congelado_dialogo.py
==========================
Congelar y descongelar PCs con Shadow Defender (clic derecho en una PC de
Control de PCs -> "Congelar / descongelar...", solo Admin; pedido del dueño,
2026-10-18). Se eligen las PCs (arranca marcada la del clic), se escribe la
clave de Shadow Defender y se manda: ver cómo están, descongelar (reinicia) o
congelar (en el acto). Cada PC contesta en su renglón; las que tienen un
cliente se saltean y lo dicen ahí.

Las reglas viven en congelado_repo; acá solo se elige y se muestra. La clave
vive solo en el campo de esta ventana: no se guarda, y al cerrar se borra de
los comandos que todavía no viajaron (comandos_pc_repo.descartar_clave_de_pendientes).
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFormLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QTableWidgetItem, QVBoxLayout,
)

from control_pcs.repositories import comandos_pc_repo, congelado_repo
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, encadenar_enter, manejar_errores, sin_boton_por_defecto,
)

COLUMNA_PC, COLUMNA_AHORA, COLUMNA_RESPUESTA = range(3)
COLOR_BIEN = QColor("#1b7f3a")
COLOR_MAL = QColor("#b3261e")


class DialogoCongelado(QDialog):
    def __init__(self, estacion_elegida, estados, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Congelar / descongelar PCs (Shadow Defender)")
        self.resize(720, 560)
        # {estacion_id: comando_id} de lo que se mandó y todavía no contestó.
        self._esperando = {}
        self._segundos_esperados = 0
        self._filas = {}
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._revisar_respuestas)

        # Por si el programa se cerró con algún pedido en la cola: que no le
        # quede la clave a una PC que la pida más tarde.
        comandos_pc_repo.descartar_clave_de_pendientes()

        explicacion = QLabel(
            "Descongelar reinicia la PC: vuelve a arrancar descongelada y, desde ahí, lo que se "
            "instale queda guardado. Congelar es en el acto. A las PCs con un cliente no se les "
            "manda nada: no se pueden descongelar, y Congelar y Ver cómo están las saltean. "
            "La clave de Shadow Defender no se guarda."
        )
        explicacion.setWordWrap(True)

        self.tabla = crear_tabla(["PC", "Ahora", "Respuesta"], estirar=COLUMNA_RESPUESTA)
        for item in estados:
            self._agregar_pc(item, marcada=item["estacion"]["id"] == estacion_elegida["id"])
        self.tabla.resizeColumnToContents(COLUMNA_PC)
        self.tabla.resizeColumnToContents(COLUMNA_AHORA)

        boton_libres = QPushButton("Marcar todas las libres")
        boton_libres.clicked.connect(self._marcar_libres)
        boton_ninguna = QPushButton("Desmarcar todas")
        boton_ninguna.clicked.connect(lambda: self._marcar(lambda _item: False))
        fila_marcar = QHBoxLayout()
        fila_marcar.addWidget(boton_libres)
        fila_marcar.addWidget(boton_ninguna)
        fila_marcar.addStretch()

        self.campo_clave = QLineEdit()
        self.campo_clave.setEchoMode(QLineEdit.Password)
        self.campo_discos = QLineEdit(congelado_repo.DISCOS_DE_SIEMPRE)
        self.campo_discos.setMaximumWidth(80)
        formulario = QFormLayout()
        formulario.addRow("Clave de Shadow Defender:", self.campo_clave)
        formulario.addRow("Discos:", self.campo_discos)

        self.boton_estado = QPushButton("Ver cómo están")
        self.boton_estado.clicked.connect(lambda: self._mandar(congelado_repo.ESTADO))
        self.boton_descongelar = QPushButton("Descongelar y reiniciar")
        aplicar_clase(self.boton_descongelar, "peligro")
        self.boton_descongelar.clicked.connect(lambda: self._mandar(congelado_repo.DESCONGELAR))
        self.boton_congelar = QPushButton("Congelar ahora")
        aplicar_clase(self.boton_congelar, "primario")
        self.boton_congelar.clicked.connect(lambda: self._mandar(congelado_repo.CONGELAR))
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        fila_acciones = QHBoxLayout()
        fila_acciones.addWidget(self.boton_estado)
        fila_acciones.addWidget(self.boton_descongelar)
        fila_acciones.addWidget(self.boton_congelar)
        fila_acciones.addStretch()
        fila_acciones.addWidget(boton_cerrar)

        self.etiqueta_estado = QLabel("")
        self.etiqueta_estado.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(explicacion)
        layout.addWidget(self.tabla, 1)
        layout.addLayout(fila_marcar)
        layout.addLayout(formulario)
        layout.addLayout(fila_acciones)
        layout.addWidget(self.etiqueta_estado)
        self.setLayout(layout)
        # Enter en la clave pasa a Discos; Enter en Discos solo mira cómo están
        # (nunca descongela: eso reinicia PCs y va con su botón y su confirmación).
        encadenar_enter(self.campo_clave, self.campo_discos, accion_final=self.boton_estado.click)
        sin_boton_por_defecto(self)
        self.campo_clave.setFocus()

    # -- la lista de PCs --------------------------------------------------------
    def _agregar_pc(self, item, marcada: bool):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        estacion = item["estacion"]
        celda_pc = QTableWidgetItem(estacion["nombre"])
        celda_pc.setFlags(celda_pc.flags() | Qt.ItemIsUserCheckable)
        celda_pc.setCheckState(Qt.Checked if marcada else Qt.Unchecked)
        celda_pc.setData(Qt.UserRole, estacion["id"])
        if congelado_repo.esta_ocupada(item):
            ahora = "Con cliente"
        elif item["enlazada"]:
            ahora = "Libre"
        else:
            ahora = "Sin conexión"
        self.tabla.setItem(fila, COLUMNA_PC, celda_pc)
        self.tabla.setItem(fila, COLUMNA_AHORA, QTableWidgetItem(ahora))
        self.tabla.setItem(fila, COLUMNA_RESPUESTA, QTableWidgetItem(""))
        self._filas[estacion["id"]] = (fila, item)

    def _marcar(self, condicion):
        for fila, item in self._filas.values():
            self.tabla.item(fila, COLUMNA_PC).setCheckState(Qt.Checked if condicion(item) else Qt.Unchecked)

    def _marcar_libres(self):
        self._marcar(lambda item: item["enlazada"] and not congelado_repo.esta_ocupada(item))

    def _elegidas(self) -> list:
        return [
            estacion_id for estacion_id, (fila, _item) in self._filas.items()
            if self.tabla.item(fila, COLUMNA_PC).checkState() == Qt.Checked
        ]

    def _poner_respuesta(self, estacion_id, texto: str, bien=None):
        fila, _item = self._filas[estacion_id]
        celda = QTableWidgetItem(texto)
        celda.setToolTip(texto)
        if bien is not None:
            celda.setForeground(COLOR_BIEN if bien else COLOR_MAL)
        self.tabla.setItem(fila, COLUMNA_RESPUESTA, celda)

    # -- mandar y esperar ---------------------------------------------------------
    @manejar_errores
    def _mandar(self, tipo: str):
        if self._esperando:
            self.etiqueta_estado.setText("Todavía hay PCs sin contestar: esperá un momento.")
            return
        elegidas = self._elegidas()
        if tipo == congelado_repo.DESCONGELAR and elegidas:
            nombres = ", ".join(self._filas[estacion_id][1]["estacion"]["nombre"] for estacion_id in elegidas)
            if not confirmar(
                self, "Descongelar",
                f"Se van a descongelar y REINICIAR: {nombres}.\n\n"
                "Hasta que las vuelvas a congelar, todo lo que se haga en ellas queda guardado. ¿Seguir?",
            ):
                return
        enviados = congelado_repo.pedir(elegidas, tipo, self.campo_clave.text(), self.campo_discos.text())
        # Las elegidas que no están en `enviados` tenían un cliente (pedir las saltea).
        salteadas = [estacion_id for estacion_id in elegidas if estacion_id not in enviados]
        for estacion_id in enviados:
            self._poner_respuesta(estacion_id, "Esperando que la PC conteste...")
        for estacion_id in salteadas:
            self._poner_respuesta(estacion_id, congelado_repo.texto_salteada(), False)
        if not enviados:
            self.etiqueta_estado.setText("No se mandó nada: todas las PCs elegidas tienen un cliente.")
            return
        aviso = f" {len(salteadas)} salteada(s) por tener un cliente." if salteadas else ""
        self._esperando = dict(enviados)
        self._segundos_esperados = 0
        self.etiqueta_estado.setText(
            f"Mandado a {len(enviados)} PC(s). Cada una contesta en su renglón.{aviso}"
        )
        self._timer.start()

    @manejar_errores
    def _revisar_respuestas(self):
        self._segundos_esperados += 1
        filas = comandos_pc_repo.obtener_comandos(self._esperando.values())
        for estacion_id, comando_id in list(self._esperando.items()):
            fila = filas.get(comando_id)
            respuesta = congelado_repo.interpretar_respuesta(fila["resultado"] if fila is not None else None)
            if respuesta is not None:
                bien, texto = respuesta
                self._poner_respuesta(estacion_id, texto, bien)
                del self._esperando[estacion_id]
        if self._esperando and self._segundos_esperados >= congelado_repo.SEGUNDOS_ESPERA_RESPUESTA:
            comandos_pc_repo.descartar_clave_de_pendientes(self._esperando.values())
            for estacion_id in self._esperando:
                self._poner_respuesta(estacion_id, congelado_repo.texto_sin_respuesta(), False)
            self._esperando = {}
        if not self._esperando:
            self._timer.stop()
            self.etiqueta_estado.setText("Listo.")

    def done(self, resultado):
        """Al cerrar (con Cerrar, la X o Escape, todos pasan por acá): la clave no
        queda en ningún comando que todavía no viajó."""
        self._timer.stop()
        try:
            comandos_pc_repo.descartar_clave_de_pendientes(self._esperando.values())
        finally:
            self._esperando = {}
            self.campo_clave.clear()
            super().done(resultado)
