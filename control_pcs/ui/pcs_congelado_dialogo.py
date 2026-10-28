"""
pcs_congelado_dialogo.py
==========================
Congelar y descongelar PCs con Shadow Defender (clic derecho en una PC de
Control de PCs -> "Congelar / descongelar...", solo Admin; pedido del dueño,
2026-10-18). Se eligen las PCs (arranca marcada la del clic; desde el botón
DESCONGELAR de abajo del mosaico, todas las prendidas y libres), se escribe la
clave de Shadow Defender y se manda: ver cómo están, descongelar (reinicia) o
congelar (en el acto). Cada PC contesta en su renglón; las que tienen un
cliente se saltean y lo dicen ahí.

Con el diseño de la maqueta "A" que eligió el dueño el 2026-10-28 (las piezas de
ui/piezas_ventana.py): la lista a la izquierda y las acciones como tarjetas a la
derecha. Al Administrador le suma ACTUALIZAR CLIENTES, que solo abre la ventana
de Actualizar el Cliente PC: como la exclusión de carpeta de Shadow Defender no
siempre anda, el dueño descongela todas, actualiza y vuelve a congelar desde acá.

Las reglas viven en congelado_repo; acá solo se elige y se muestra. La clave
vive solo en el campo de esta ventana: no se guarda, y al cerrar se borra de
los comandos que todavía no viajaron (comandos_pc_repo.descartar_clave_de_pendientes).
"""

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QFont
from PySide6.QtWidgets import (
    QDialog, QFrame, QHBoxLayout, QLabel, QLineEdit, QTableWidgetItem, QVBoxLayout,
)

import dominio
from admin_remoto import modo as modo_remoto
from control_pcs.repositories import comandos_pc_repo, congelado_repo, pcs_libres_repo
from control_pcs.ui.pcs_actualizacion_dialogo import DialogoActualizarCliente
from control_pcs.ui.pcs_dibujos import COLOR_HIELO_FUERTE, icono_copo_de_nieve
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_NARANJA, TONO_ROJO, TONO_VERDE, agregar_pastilla, cabecera_oscura,
    linea_divisoria, panel_blanco, tarjeta_de_menu, tecla, titulo_de_seccion,
)
from ui.utils import (
    confirmar, crear_tabla, encadenar_enter, manejar_errores, sin_boton_por_defecto,
)

COLUMNA_PC, COLUMNA_AHORA, COLUMNA_RESPUESTA = range(3)
COLOR_BIEN = QColor("#1b7f3a")
COLOR_MAL = QColor("#b3261e")
COLOR_ESPERANDO = QColor("#1D48A0")

# Cómo está cada PC al abrir la ventana, con su color en la columna "Ahora".
LIBRE, CON_CLIENTE, SIN_CONEXION = "Libre", "Con cliente", "Sin conexión"
COLOR_AHORA = {LIBRE: COLOR_BIEN, CON_CLIENTE: QColor("#B85C00"), SIN_CONEXION: QColor("#8A93A3")}


def _texto_respuesta(texto: str, bien) -> str:
    """La respuesta con su marca adelante: ✔ salió bien, ✖ no, ⏳ todavía no contestó."""
    marca = "⏳" if bien is None else ("✔" if bien else "✖")
    return f"{marca}  {texto}"


def _con_numero(cantidad: int, singular: str, plural: str) -> str:
    return f"{cantidad} {singular if cantidad == 1 else plural}"


class DialogoCongelado(QDialog):
    def __init__(self, estacion_elegida, estados, usuario=None, parent=None):
        """`estacion_elegida` es la PC del clic derecho, que arranca marcada; con
        None (botón DESCONGELAR) arrancan marcadas todas las prendidas y libres.
        `usuario` es quien está logueado: si es el Administrador ve ACTUALIZAR CLIENTES."""
        super().__init__(parent)
        self.setWindowTitle("Congelar / descongelar PCs (Shadow Defender)")
        self.resize(1060, 760)
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

        self._armar_interfaz(dominio.es_admin(usuario))
        for item in estados:
            if estacion_elegida is None:
                marcada = pcs_libres_repo.esta_prendida_y_libre(item)
            else:
                marcada = item["estacion"]["id"] == estacion_elegida["id"]
            self._agregar_pc(item, marcada=marcada)
        self._contar()
        # Recién ahora: mientras se llenaba, cada renglón nuevo la dispararía.
        self.tabla.itemChanged.connect(self._al_cambiar_celda)

    def _armar_interfaz(self, es_admin: bool):
        cabecera = cabecera_oscura(
            "", "Congelar / descongelar PCs", "Shadow Defender · las PCs con un cliente se saltean solas")
        # El copo dibujado de DESCONGELAR: el cubito 🧊 sale como un rectángulo en el mostrador.
        cabecera.icono.setPixmap(icono_copo_de_nieve().pixmap(30, 30))
        self.pastilla_elegidas = agregar_pastilla(cabecera, "", TONO_AZUL)
        self.pastilla_con_cliente = agregar_pastilla(cabecera, "", TONO_NARANJA)
        self.pastilla_sin_conexion = agregar_pastilla(cabecera, "", TONO_GRIS)

        # Izquierda: las PCs, con los botones para marcarlas arriba.
        self.tabla = crear_tabla(["PC", "Ahora", "Respuesta"], estirar=COLUMNA_RESPUESTA)
        self.tabla.setObjectName("tablaCongelado")
        self.tabla.setShowGrid(False)
        self.tabla.verticalHeader().setDefaultSectionSize(34)
        self.tabla.setColumnWidth(COLUMNA_PC, 130)
        self.tabla.setColumnWidth(COLUMNA_AHORA, 130)
        fila_marcar = QHBoxLayout()
        fila_marcar.addWidget(titulo_de_seccion("PCs del local"))
        fila_marcar.addStretch()
        fila_marcar.addWidget(tecla("MARCAR LAS LIBRES", self._marcar_libres))
        fila_marcar.addWidget(tecla("DESMARCAR", lambda: self._marcar(lambda _item: False)))
        panel_lista, capa_lista = panel_blanco()
        capa_lista.addLayout(fila_marcar)
        capa_lista.addWidget(self.tabla, 1)

        # Derecha, arriba: la clave.
        self.campo_clave = QLineEdit()
        self.campo_clave.setObjectName("campoClaveShadow")
        self.campo_clave.setEchoMode(QLineEdit.Password)
        self.campo_discos = QLineEdit(congelado_repo.DISCOS_DE_SIEMPRE)
        self.campo_discos.setFixedWidth(56)
        fila_clave = QHBoxLayout()
        fila_clave.addWidget(self.campo_clave, 1)
        fila_clave.addSpacing(6)
        fila_clave.addWidget(QLabel("Discos"))
        fila_clave.addWidget(self.campo_discos)
        ayuda_clave = QLabel("No se guarda: se borra al cerrar esta ventana.")
        ayuda_clave.setObjectName("ayudaChica")
        panel_clave, capa_clave = panel_blanco()
        capa_clave.addWidget(titulo_de_seccion("Clave de Shadow Defender"))
        capa_clave.addLayout(fila_clave)
        capa_clave.addWidget(ayuda_clave)

        # Derecha, abajo: qué hacer con las marcadas. Descongelar, en rojo: reinicia PCs.
        self.boton_estado = tarjeta_de_menu(
            "🔍", "Ver cómo están", "Pregunta si están congeladas, sin cambiar nada",
            lambda: self._mandar(congelado_repo.ESTADO), alto=54)
        self.boton_descongelar = tarjeta_de_menu(
            "💧", "Descongelar y reiniciar", "Vuelven descongeladas: lo que se instale queda",
            lambda: self._mandar(congelado_repo.DESCONGELAR), alto=54, tono=TONO_ROJO)
        self.boton_congelar = tarjeta_de_menu(
            "", "Congelar ahora", "En el acto, sin reiniciar",
            lambda: self._mandar(congelado_repo.CONGELAR), alto=54)
        self.boton_congelar.icono.setPixmap(icono_copo_de_nieve(COLOR_HIELO_FUERTE).pixmap(24, 24))
        panel_acciones, capa_acciones = panel_blanco()
        capa_acciones.setSpacing(8)
        capa_acciones.addWidget(titulo_de_seccion("Con las PCs marcadas"))
        capa_acciones.addWidget(self.boton_estado)
        capa_acciones.addWidget(self.boton_descongelar)
        capa_acciones.addWidget(self.boton_congelar)
        # Solo el Admin (pedido del dueño, 2026-10-28), y solo en el mostrador: la
        # versión nueva se firma con la clave que vive ahí (como en Gestionar Estaciones).
        self.boton_actualizar = None
        if es_admin and not modo_remoto.es_copia_remota():
            self.boton_actualizar = tarjeta_de_menu(
                "⬆️", "Actualizar clientes", "Abre Actualizar el Cliente PC, sin cerrar esta ventana",
                self._abrir_actualizacion, alto=54, tono=TONO_VERDE)
            capa_acciones.addSpacing(4)
            capa_acciones.addWidget(linea_divisoria())
            capa_acciones.addSpacing(2)
            capa_acciones.addWidget(titulo_de_seccion("Solo el Administrador"))
            capa_acciones.addWidget(self.boton_actualizar)

        derecha = QVBoxLayout()
        derecha.setSpacing(12)
        derecha.addWidget(panel_clave)
        derecha.addWidget(panel_acciones)
        derecha.addStretch()
        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        cuerpo.addWidget(panel_lista, 14)
        cuerpo.addLayout(derecha, 9)

        # Abajo: qué está pasando, y Cerrar.
        self.etiqueta_estado = QLabel("Marcá las PCs, escribí la clave y elegí qué hacer.")
        self.etiqueta_estado.setWordWrap(True)
        barra_estado = QFrame()
        barra_estado.setObjectName("pieAyuda")
        capa_estado = QHBoxLayout(barra_estado)
        capa_estado.setContentsMargins(12, 8, 12, 8)
        capa_estado.addWidget(self.etiqueta_estado, 1)
        pie = QHBoxLayout()
        pie.addWidget(barra_estado, 1)
        pie.addSpacing(8)
        pie.addWidget(tecla("CERRAR", self.close, "teclaRoja"))

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(cuerpo, 1)
        layout.addLayout(pie)
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
        negrita = QFont(celda_pc.font())
        negrita.setBold(True)
        celda_pc.setFont(negrita)
        ahora = self._como_esta(item)
        celda_ahora = QTableWidgetItem(f"●  {ahora}")
        celda_ahora.setForeground(COLOR_AHORA[ahora])
        self.tabla.setItem(fila, COLUMNA_PC, celda_pc)
        self.tabla.setItem(fila, COLUMNA_AHORA, celda_ahora)
        self.tabla.setItem(fila, COLUMNA_RESPUESTA, QTableWidgetItem(""))
        self._filas[estacion["id"]] = (fila, item)

    @staticmethod
    def _como_esta(item) -> str:
        if congelado_repo.esta_ocupada(item):
            return CON_CLIENTE
        return LIBRE if item["enlazada"] else SIN_CONEXION

    def _contar(self):
        """Los números de la cabecera: las marcadas, y las que tienen un cliente o no
        tienen conexión (estas dos, solo si hay alguna)."""
        elegidas = len(self._elegidas())
        self.pastilla_elegidas.setText(_con_numero(elegidas, "ELEGIDA", "ELEGIDAS"))
        como_estan = [self._como_esta(item) for _fila, item in self._filas.values()]
        for pastilla, estado, texto in (
            (self.pastilla_con_cliente, CON_CLIENTE, "CON CLIENTE"),
            (self.pastilla_sin_conexion, SIN_CONEXION, "SIN CONEXIÓN"),
        ):
            cantidad = como_estan.count(estado)
            pastilla.setText(f"{cantidad} {texto}")
            pastilla.setVisible(bool(cantidad))

    def _al_cambiar_celda(self, celda):
        if celda.column() == COLUMNA_PC:
            self._contar()

    def _marcar(self, condicion):
        for fila, item in self._filas.values():
            self.tabla.item(fila, COLUMNA_PC).setCheckState(Qt.Checked if condicion(item) else Qt.Unchecked)

    def _marcar_libres(self):
        self._marcar(pcs_libres_repo.esta_prendida_y_libre)

    def _elegidas(self) -> list:
        return [
            estacion_id for estacion_id, (fila, _item) in self._filas.items()
            if self.tabla.item(fila, COLUMNA_PC).checkState() == Qt.Checked
        ]

    def _poner_respuesta(self, estacion_id, texto: str, bien=None):
        fila, _item = self._filas[estacion_id]
        celda = QTableWidgetItem(_texto_respuesta(texto, bien))
        celda.setToolTip(texto)
        celda.setForeground(COLOR_ESPERANDO if bien is None else (COLOR_BIEN if bien else COLOR_MAL))
        self.tabla.setItem(fila, COLUMNA_RESPUESTA, celda)

    @manejar_errores
    def _abrir_actualizacion(self):
        """La ventana de siempre de Actualizar el Cliente PC (ver pcs_actualizacion_dialogo),
        encima de esta: al cerrarla se sigue acá, para volver a congelar."""
        DialogoActualizarCliente(self).exec()

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
