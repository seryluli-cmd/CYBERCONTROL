"""
bonos_dialogos.py
===================
Las dos pantallas con las que se administra un catálogo de bonos de tiempo:
la lista con Nuevo / Modificar / Desactivar (`DialogoGestionBonosBase`) y el
formulario de alta y edición de un bono (`DialogoBonoBase`).

Hay TRES catálogos con esta misma mecánica, deliberadamente separados (ver
control_pcs/repositories/catalogo_bonos.py): el de walk-ins
(`DialogoGestionBonos` / `DialogoBono` en pcs_gestion_dialogos.py), el
exclusivo de socios (`DialogoGestionBonosMiembro` / `DialogoBonoMiembro` en
miembros_window.py) y el de la PlayStation 5 (`DialogoGestionBonosPlaystation`
/ `DialogoBonoPlaystation`, otra vez en pcs_gestion_dialogos.py). Cada uno es
una subclase corta que solo dice qué repo usa y cómo se llama en pantalla;
todo lo demás se escribe una vez acá.
"""

from PySide6.QtWidgets import (
    QDialog, QDoubleSpinBox, QHBoxLayout, QLabel, QLineEdit, QPushButton, QSpinBox,
    QTableWidgetItem, QVBoxLayout,
)

from ui.utils import (
    aplicar_clase, confirmar, encadenar_enter, fila_guardar_cancelar, formato_pesos,
    formato_tiempo, manejar_errores, mostrar_error, sin_boton_por_defecto, crear_tabla,
)


class DialogoBonoBase(QDialog):
    """
    Alta/edición de un bono de tiempo. El tiempo se carga en horas y
    minutos por separado (en pasos de 30 min) porque acá nunca se vende
    por minuto suelto — solo combos prearmados como "3 horas" o
    "1 hora y media".

    Cada subclase define: `repo` (el módulo con crear_bono/modificar_bono:
    pcs_repo o bonos_miembro_repo) y los textos TITULO_NUEVO,
    TITULO_EDICION y EJEMPLO_NOMBRE. Si el catálogo exige saber QUIÉN lo
    edita (el de la PlayStation 5, ver playstation_repo.AdministradorDeBonos),
    el `repo` se pasa al abrir el formulario en vez de ser fijo de la clase.
    """

    repo = None
    TITULO_NUEVO = "Nuevo Bono"
    TITULO_EDICION = "Modificar Bono"
    EJEMPLO_NOMBRE = "Ej: 3 horas"

    def __init__(self, parent, bono=None, repo=None):
        super().__init__(parent)
        if repo is not None:
            self.repo = repo
        self.bono = bono
        self.setWindowTitle(self.TITULO_EDICION if bono else self.TITULO_NUEVO)
        self.resize(340, 260)
        self._armar_interfaz()
        if bono:
            self._cargar_datos(bono)

    def _armar_interfaz(self):
        self.campo_nombre = QLineEdit()
        self.campo_nombre.setPlaceholderText(self.EJEMPLO_NOMBRE)

        self.spin_horas = QSpinBox()
        self.spin_horas.setRange(0, 99)
        self.spin_minutos = QSpinBox()
        self.spin_minutos.setRange(0, 30)
        self.spin_minutos.setSingleStep(30)
        fila_tiempo = QHBoxLayout()
        fila_tiempo.addWidget(self.spin_horas)
        fila_tiempo.addWidget(QLabel("hs"))
        fila_tiempo.addWidget(self.spin_minutos)
        fila_tiempo.addWidget(QLabel("min"))

        self.spin_precio = QDoubleSpinBox()
        self.spin_precio.setMaximum(99_999_999)
        self.spin_precio.setPrefix("$ ")

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Nombre:"))
        layout.addWidget(self.campo_nombre)
        layout.addWidget(QLabel("Tiempo:"))
        layout.addLayout(fila_tiempo)
        layout.addWidget(QLabel("Precio:"))
        layout.addWidget(self.spin_precio)
        layout.addLayout(fila_guardar_cancelar(self, self._guardar))
        self.setLayout(layout)
        encadenar_enter(self.campo_nombre, self.spin_horas, self.spin_minutos, self.spin_precio,
                         accion_final=self._guardar)
        sin_boton_por_defecto(self)

    def _cargar_datos(self, bono):
        self.campo_nombre.setText(bono["nombre"])
        self.spin_horas.setValue(bono["minutos"] // 60)
        self.spin_minutos.setValue(bono["minutos"] % 60)
        self.spin_precio.setValue(bono["precio"])

    @manejar_errores
    def _guardar(self):
        nombre = self.campo_nombre.text().strip()
        minutos = self.spin_horas.value() * 60 + self.spin_minutos.value()
        precio = self.spin_precio.value()
        if self.bono:
            self.repo.modificar_bono(self.bono["id"], nombre, minutos, precio)
        else:
            self.repo.crear_bono(nombre, minutos, precio)
        self.accept()


class DialogoGestionBonosBase(QDialog):
    """
    Lista de los bonos de un catálogo, con Nuevo / Modificar / Desactivar.

    Cada subclase define: `repo` (pcs_repo o bonos_miembro_repo),
    `CLASE_FORMULARIO` (el DialogoBonoBase de alta/edición que le toca),
    TITULO y CONFIRMAR_DESACTIVAR (el texto de la pregunta, con `{nombre}`).
    Igual que el formulario, acepta un `repo` al abrirse (el de la PlayStation 5
    va atado al usuario) y se lo pasa a los formularios que abre.
    """

    repo = None
    CLASE_FORMULARIO = None
    TITULO = "Gestionar Bonos"
    CONFIRMAR_DESACTIVAR = "¿Desactivar el bono '{nombre}'?"

    def __init__(self, parent=None, repo=None):
        super().__init__(parent)
        if repo is not None:
            self.repo = repo
        self.setWindowTitle(self.TITULO)
        self.resize(460, 440)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        self.tabla = crear_tabla(["Nombre", "Tiempo", "Precio"], estirar=0, por_filas=True, una_sola=True)

        boton_nuevo = QPushButton("Nuevo")
        aplicar_clase(boton_nuevo, "primario")
        boton_nuevo.clicked.connect(self._nuevo)
        boton_modificar = QPushButton("Modificar")
        boton_modificar.clicked.connect(self._modificar)
        boton_desactivar = QPushButton("Desactivar")
        aplicar_clase(boton_desactivar, "peligro")
        boton_desactivar.clicked.connect(self._desactivar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        barra_botones = QHBoxLayout()
        for boton in (boton_nuevo, boton_modificar, boton_desactivar, boton_cerrar):
            barra_botones.addWidget(boton)
        barra_botones.addStretch()

        layout = QVBoxLayout()
        layout.addLayout(barra_botones)
        layout.addWidget(self.tabla)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        self.bonos = self.repo.listar_bonos()
        self.tabla.setRowCount(0)
        for bono in self.bonos:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(bono["nombre"]))
            self.tabla.setItem(fila, 1, QTableWidgetItem(formato_tiempo(bono["minutos"] * 60)))
            self.tabla.setItem(fila, 2, QTableWidgetItem(formato_pesos(bono["precio"])))

    def _seleccionado(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un bono de la lista.")
            return None
        return self.bonos[fila]

    def _nuevo(self):
        dialogo = self.CLASE_FORMULARIO(self, repo=self.repo)
        if dialogo.exec():
            self._cargar()

    def _modificar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        dialogo = self.CLASE_FORMULARIO(self, bono, repo=self.repo)
        if dialogo.exec():
            self._cargar()

    @manejar_errores
    def _desactivar(self):
        bono = self._seleccionado()
        if bono is None:
            return
        if confirmar(self, "Confirmar", self.CONFIRMAR_DESACTIVAR.format(nombre=bono["nombre"])):
            self.repo.desactivar_bono(bono["id"])
            self._cargar()
