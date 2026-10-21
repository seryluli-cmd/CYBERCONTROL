"""
limpieza_dialogo.py
=====================
La pantalla de "LIMPIAR BASE DE DATOS" (Configuración ADMIN, pedido del dueño
para la etapa de pruebas): dice qué se borra y qué queda, cuánto hay hoy de
cada cosa, y solo deja seguir si se escribe la palabra LIMPIAR -- un clic
apurado no puede borrar nada. La regla (qué se borra, la copia de seguridad,
que sea solo para Admin) vive en repositories/limpieza_repo.py.
"""

import os

from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout

from repositories import limpieza_repo
from ui.utils import aplicar_clase, manejar_errores, mostrar_info, sin_boton_por_defecto

# Lo que hay que escribir para habilitar el botón.
PALABRA_DE_CONFIRMACION = "LIMPIAR"


class DialogoLimpiarBase(QDialog):
    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Limpiar base de datos")
        self.resize(520, 480)
        self._armar_interfaz()

    def _armar_interfaz(self):
        cantidades = limpieza_repo.contar_lo_que_se_borraria()

        titulo = QLabel("⚠  LIMPIAR BASE DE DATOS")
        titulo.setStyleSheet("font-size: 17px; font-weight: 700; color: #C62828;")

        se_borra = QLabel(
            "<b>Se borra</b> (no se puede deshacer desde el programa):<ul>"
            f"<li>Todas las ventas: {cantidades['ventas']} (kiosko, bonos de PC, PCSTREAM, "
            "PlayStation 5, cargas de saldo y trámites), con sus pagos.</li>"
            f"<li>Todos los cierres de turno: {cantidades['cierres_turno']}.</li>"
            f"<li>Las sesiones de las PCs ({cantidades['sesiones_pc']}) y de la PlayStation 5 "
            f"({cantidades['sesiones_playstation']}), también las que estén en curso: "
            "esas PCs se vuelven a bloquear.</li>"
            "<li>El saldo de los socios (quedan en 0) y su historial de saldo.</li>"
            f"<li>Las reservas: {cantidades['reservas']}.</li>"
            "</ul>Con eso Caja, Cierre de Turno y todos los Reportes quedan en cero. A los "
            "artículos se les devuelve el stock que se llevaron esas ventas."
        )
        se_borra.setWordWrap(True)

        queda = QLabel(
            "<b>Queda todo lo cargado:</b> usuarios, artículos, compras, bonos (PC, PCSTREAM, "
            "PlayStation 5 y socios), estaciones, socios, trámites y la configuración."
        )
        queda.setWordWrap(True)

        copia = QLabel(
            "Antes de borrar se guarda una copia completa de la base en la carpeta "
            "data\\backups. Si la copia no se puede hacer, no se borra nada."
        )
        copia.setWordWrap(True)
        copia.setStyleSheet("color: #7A869A;")

        self.campo_confirmacion = QLineEdit()
        self.campo_confirmacion.setPlaceholderText(PALABRA_DE_CONFIRMACION)
        self.campo_confirmacion.textChanged.connect(self._actualizar_boton)

        self.boton_limpiar = QPushButton("Limpiar base de datos")
        aplicar_clase(self.boton_limpiar, "peligro")
        self.boton_limpiar.setEnabled(False)
        self.boton_limpiar.clicked.connect(self._limpiar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_cancelar)
        botones.addWidget(self.boton_limpiar)

        layout = QVBoxLayout()
        layout.addWidget(titulo)
        layout.addWidget(se_borra)
        layout.addWidget(queda)
        layout.addWidget(copia)
        layout.addWidget(QLabel(f"Para confirmar, escribí {PALABRA_DE_CONFIRMACION}:"))
        layout.addWidget(self.campo_confirmacion)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self.campo_confirmacion.setFocus()

    def _actualizar_boton(self, texto: str):
        self.boton_limpiar.setEnabled(texto.strip().upper() == PALABRA_DE_CONFIRMACION)

    @manejar_errores
    def _limpiar(self):
        if not self.boton_limpiar.isEnabled():
            return
        resultado = limpieza_repo.limpiar_base(self.usuario["id"])
        mostrar_info(
            self, "Base de datos limpia",
            f"Listo. Se borraron {resultado['ventas']} venta(s), {resultado['cierres']} cierre(s) "
            f"de turno y {resultado['sesiones']} sesión(es); {resultado['socios_en_cero']} socio(s) "
            "quedaron con saldo 0.\n\n"
            f"Copia de seguridad: {os.path.basename(resultado['copia'])} (en data\\backups).",
        )
        self.accept()
