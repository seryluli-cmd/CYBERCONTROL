"""
pcs_filtro_dialogo.py
=======================
"Filtro de palabras de las PCs...": el Admin prende o apaga el filtro, edita la
lista de palabras y el mensaje que ve el cliente, y mira las últimas páginas que
cerró. Se abre desde Gestionar Estaciones (Configuración ADMIN, exclusiva de
ADMIN). Las reglas -qué es una palabra válida, los topes- son de
`filtro_palabras_repo`; cómo se busca en cada PC, de `CLIENTE PC/filtro_palabras.py`.
"""

from PySide6.QtWidgets import (
    QCheckBox, QDialog, QHBoxLayout, QLabel, QPlainTextEdit, QPushButton, QTableWidgetItem, QVBoxLayout,
)

from control_pcs.repositories import filtro_palabras_repo
from ui.utils import (
    aplicar_clase, confirmar, crear_tabla, formato_fecha_hora, manejar_errores, mostrar_info,
    sin_boton_por_defecto,
)

# Cuántos bloqueos se listan abajo (los más nuevos).
BLOQUEOS_A_MOSTRAR = 200


class DialogoFiltroPalabras(QDialog):
    """La lista, el mensaje y el interruptor del filtro, más los últimos bloqueos."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Filtro de palabras de las PCs")
        self.resize(780, 640)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.casilla_activo = QCheckBox("Filtro prendido")

        explicacion = QLabel(
            "Con una sesión en curso, cada PC mira el título de la ventana que el cliente tiene "
            "adelante (en el navegador, el título de la pestaña). Si aparece una de estas palabras, "
            "cierra esa pestaña, le muestra el mensaje y avisa acá y en Actividad reciente. Busca "
            "palabras enteras sin importar mayúsculas ni acentos: \"anal\" no salta con \"análisis\" "
            "ni con \"canal\". Solo ve el título: una página con un título inocente pasa igual."
        )
        explicacion.setWordWrap(True)

        self.campo_palabras = QPlainTextEdit()
        self.campo_palabras.setPlaceholderText("Una palabra o frase por renglón")
        self.campo_palabras.textChanged.connect(self._contar_palabras)
        self.cuenta_palabras = QLabel()

        columna_palabras = QVBoxLayout()
        columna_palabras.addWidget(QLabel("Palabras (una por renglón):"))
        columna_palabras.addWidget(self.campo_palabras)
        columna_palabras.addWidget(self.cuenta_palabras)

        self.campo_mensaje = QPlainTextEdit()
        self.campo_mensaje.setPlaceholderText("Vacío: cierra la página sin mostrar nada")
        nota_mensaje = QLabel(
            "Aparece en el medio de la pantalla del cliente cuando el filtro cierra una página. "
            "Las PCs prendidas toman los cambios solas en unos segundos."
        )
        nota_mensaje.setWordWrap(True)

        columna_mensaje = QVBoxLayout()
        columna_mensaje.addWidget(QLabel("Mensaje para el cliente:"))
        columna_mensaje.addWidget(self.campo_mensaje)
        columna_mensaje.addWidget(nota_mensaje)

        fila_edicion = QHBoxLayout()
        fila_edicion.addLayout(columna_palabras, 1)
        fila_edicion.addLayout(columna_mensaje, 1)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)

        self.tabla_bloqueos = crear_tabla(["Fecha", "PC", "Palabra", "Título de la página"], estirar=3, por_filas=True)
        boton_actualizar = QPushButton("Actualizar lista")
        boton_actualizar.clicked.connect(self._cargar_bloqueos)
        fila_titulo_bloqueos = QHBoxLayout()
        fila_titulo_bloqueos.addWidget(QLabel(f"Últimas páginas cerradas (hasta {BLOQUEOS_A_MOSTRAR}):"))
        fila_titulo_bloqueos.addStretch()
        fila_titulo_bloqueos.addWidget(boton_actualizar)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.reject)

        layout = QVBoxLayout()
        layout.addWidget(self.casilla_activo)
        layout.addWidget(explicacion)
        layout.addLayout(fila_edicion, 3)
        layout.addWidget(boton_guardar)
        layout.addLayout(fila_titulo_bloqueos)
        layout.addWidget(self.tabla_bloqueos, 2)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _lo_que_hay_en_pantalla(self):
        return (self.casilla_activo.isChecked(), self.campo_palabras.toPlainText(),
                self.campo_mensaje.toPlainText())

    @manejar_errores
    def _cargar(self):
        filtro = filtro_palabras_repo.obtener()
        self.casilla_activo.setChecked(filtro["activo"])
        self.campo_palabras.setPlainText("\n".join(filtro["palabras"]))
        self.campo_mensaje.setPlainText(filtro["mensaje"])
        self._guardado = self._lo_que_hay_en_pantalla()
        self._cargar_bloqueos()

    def _contar_palabras(self):
        cantidad = sum(1 for renglon in self.campo_palabras.toPlainText().splitlines() if renglon.strip())
        self.cuenta_palabras.setText(f"{cantidad} palabra{'' if cantidad == 1 else 's'}")

    @manejar_errores
    def _cargar_bloqueos(self):
        bloqueos = filtro_palabras_repo.listar_recientes(BLOQUEOS_A_MOSTRAR)
        self.tabla_bloqueos.setRowCount(0)
        for bloqueo in bloqueos:
            fila = self.tabla_bloqueos.rowCount()
            self.tabla_bloqueos.insertRow(fila)
            valores = (formato_fecha_hora(bloqueo["fecha_hora"]), bloqueo["estacion_nombre"],
                       bloqueo["palabra"], bloqueo["titulo"])
            for columna, valor in enumerate(valores):
                self.tabla_bloqueos.setItem(fila, columna, QTableWidgetItem(valor))
        for columna in (0, 1, 2):   # la fecha entera a la vista; el título se lleva lo que sobra
            self.tabla_bloqueos.resizeColumnToContents(columna)

    @manejar_errores
    def _guardar(self):
        activo, texto_palabras, mensaje = self._lo_que_hay_en_pantalla()
        filtro = filtro_palabras_repo.guardar(activo, texto_palabras, mensaje)
        # Se vuelve a mostrar lo que quedó guardado: en minúsculas, sin repetidas ni
        # renglones vacíos.
        self.campo_palabras.setPlainText("\n".join(filtro["palabras"]))
        self.campo_mensaje.setPlainText(filtro["mensaje"])
        self._guardado = self._lo_que_hay_en_pantalla()
        estado = "prendido" if filtro["activo"] else "APAGADO"
        mostrar_info(
            self, "Listo",
            f"Filtro guardado ({estado}, {len(filtro['palabras'])} palabras). Las PCs prendidas "
            "lo toman solas en unos segundos; las que arranquen después, al arrancar."
        )

    def reject(self):
        """Cerrar (o Esc) con cambios sin guardar pregunta antes, para no perderlos."""
        if self._lo_que_hay_en_pantalla() != self._guardado and not confirmar(
            self, "Cambios sin guardar", "Hay cambios sin guardar en el filtro. ¿Cerrar igual?"
        ):
            return
        super().reject()
