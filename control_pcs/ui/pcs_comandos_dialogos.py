"""
pcs_comandos_dialogos.py
==========================
Diálogos del menú contextual (clic derecho) de la grilla de Control de PCs:
captura de pantalla, cambiar de módem (+ editar el catálogo de módems),
intercambiar la sesión con otra PC y ajustar el volumen. Los abre
`PanelControlPcs` (pcs_window.py). Salvo "Intercambiar", que cambia la base
directo (`pcs_repo.trasladar_sesion`), todos mandan un comando a la PC cliente
(ver comandos_pc_repo.py).
"""

import os

from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import (
    QComboBox, QDialog, QHBoxLayout, QHeaderView, QLabel, QPushButton, QSlider,
    QTableWidget, QTableWidgetItem, QVBoxLayout,
)
from PySide6.QtCore import Qt, QTimer

import database
from control_pcs.repositories import comandos_pc_repo, config_red_repo, pcs_repo
from ui.utils import (
    aplicar_clase, confirmar, formato_tiempo, manejar_errores, mostrar_error, mostrar_info,
    sin_boton_por_defecto,
)

# Cuántos segundos se espera, como máximo, la captura de pantalla que
# sube el Cliente PC después de un comando SCREENSHOT (ver DialogoCaptura) --
# tiene que ser más que INTERVALO_CONSULTA_MS del Cliente PC (5s) para darle
# margen a que la reciba en su próximo ciclo y la suba.
SEGUNDOS_ESPERA_CAPTURA = 20


class _DialogoQueEsperaResultado(QDialog):
    """
    Base de los diálogos que le mandan un comando a una PC y se quedan
    esperando lo que devuelve (ver comandos_pc_repo.py): una captura de
    pantalla, o si pudo cambiar de módem. No es instantáneo -- el Cliente PC
    recién recibe el comando en su próxima consulta de estado (hasta 5s) --
    así que, con un QTimer, revisa cada segundo si ya llegó el resultado y,
    pasados SEGUNDOS_ESPERA_CAPTURA sin respuesta, avisa.

    La subclase manda el comando y llama a `_esperar_resultado(comando_id)`;
    define qué hacer cuando llega (`_mostrar_resultado`) y el texto de
    MENSAJE_SIN_RESPUESTA. Necesita una `self.etiqueta_estado`.
    """

    MENSAJE_SIN_RESPUESTA = (
        "No llegó respuesta a tiempo — revisá que la PC esté prendida "
        "y conectada, o probá de nuevo."
    )

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.comando_id = None
        self._segundos_esperados = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._revisar)

    def _esperar_resultado(self, comando_id: int):
        """Empieza a esperar el resultado del comando ya encolado."""
        self.comando_id = comando_id
        self._segundos_esperados = 0
        self._timer.start()

    def _mostrar_resultado(self, resultado: str):
        """Qué mostrar cuando llega el resultado (lo define cada subclase)."""
        raise NotImplementedError

    def _revisar(self):
        self._segundos_esperados += 1
        fila = comandos_pc_repo.obtener_comando(self.comando_id)
        if fila is not None and fila["resultado"]:
            self._timer.stop()
            self._mostrar_resultado(fila["resultado"])
            return
        if self._segundos_esperados >= SEGUNDOS_ESPERA_CAPTURA:
            self._timer.stop()
            self.etiqueta_estado.setText(self.MENSAJE_SIN_RESPUESTA)


class DialogoCaptura(_DialogoQueEsperaResultado):
    """
    Pide una captura de pantalla a una estación y la muestra apenas
    llega. El Cliente PC de esa PC recién la toma y la sube cuando le llega
    el comando, por eso se espera el resultado (ver la clase base) en vez de
    traer la imagen de una sola vez.
    """

    MENSAJE_SIN_RESPUESTA = (
        "No llegó respuesta a tiempo — revisá que la PC esté prendida "
        "y conectada a la red, o probá de nuevo."
    )

    def __init__(self, estacion, parent=None):
        super().__init__(estacion, parent)
        self.setWindowTitle(f"Captura de pantalla — {estacion['nombre']}")
        self.resize(520, 420)

        self.etiqueta_estado = QLabel("Esperando que la PC responda...")
        self.etiqueta_estado.setAlignment(Qt.AlignCenter)
        self.etiqueta_imagen = QLabel()
        self.etiqueta_imagen.setAlignment(Qt.AlignCenter)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_estado)
        layout.addWidget(self.etiqueta_imagen, 1)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

        self._esperar_resultado(
            comandos_pc_repo.encolar_comando(estacion["id"], comandos_pc_repo.TIPO_SCREENSHOT)
        )

    def _mostrar_resultado(self, resultado: str):
        """`resultado` es la ruta (dentro de data/) de la imagen que subió el
        Cliente PC."""
        pixmap = QPixmap(os.path.join(database.DATA_DIR, resultado))
        if pixmap.isNull():
            self.etiqueta_estado.setText("Llegó una respuesta pero no se pudo leer la imagen.")
            return
        self.etiqueta_estado.setText(f"Captura de '{self.estacion['nombre']}':")
        self.etiqueta_imagen.setPixmap(
            pixmap.scaled(480, 340, Qt.KeepAspectRatio, Qt.SmoothTransformation)
        )


class DialogoCambiarRed(_DialogoQueEsperaResultado):
    """
    Cambia la puerta de enlace y el DNS de la estación elegida a uno de
    los módems configurados (ver config_red_repo.py) -- nunca toca la IP
    fija de la PC ni su máscara. Pensado para el caso real del Cyber:
    varios módems en el mismo rango 192.168.1.x y las PCs con IP fija
    propia; si un cliente avisa "no tengo internet" porque se cayó UN
    módem, el mostrador la pasa al otro desde acá en vez de ir hasta la
    PC. A diferencia de Reiniciar/Apagar/Mensaje, este comando SÍ puede
    fallar del lado de la PC (adaptador no encontrado, PowerShell sin
    permisos) -- por eso se queda esperando el resultado (ver la clase
    base) en vez de darlo por entregado y listo.
    """

    def __init__(self, estacion, parent=None):
        super().__init__(estacion, parent)
        self.setWindowTitle(f"Cambiar red — {estacion['nombre']}")
        self.resize(360, 280)

        self.etiqueta_estado = QLabel("Elegí a qué módem pasar esta PC:")
        self.etiqueta_estado.setWordWrap(True)

        layout = QVBoxLayout()
        layout.addWidget(self.etiqueta_estado)

        for gateway in config_red_repo.obtener_gateways():
            boton = QPushButton(f"{gateway['nombre']} ({gateway['ip']})")
            boton.clicked.connect(lambda _=False, ip=gateway["ip"]: self._enviar(ip))
            layout.addWidget(boton)

        boton_editar = QPushButton("Editar módems...")
        boton_editar.clicked.connect(self._editar_modems)
        layout.addWidget(boton_editar)

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _enviar(self, ip_gateway):
        if not confirmar(
            self, "Confirmar",
            f"¿Cambiar la puerta de enlace y DNS de '{self.estacion['nombre']}' a {ip_gateway}?",
        ):
            return
        self._esperar_resultado(comandos_pc_repo.encolar_comando(
            self.estacion["id"], comandos_pc_repo.TIPO_CAMBIAR_RED, ip_gateway
        ))
        self.etiqueta_estado.setText("Esperando que la PC aplique el cambio...")

    def _mostrar_resultado(self, resultado: str):
        """`resultado` es "OK" o "ERROR: ..." (ver win32_utils.cambiar_gateway_y_dns
        del lado del Cliente PC)."""
        if resultado == "OK":
            self.etiqueta_estado.setText(
                f"Listo, '{self.estacion['nombre']}' ya está usando esa puerta de enlace."
            )
        else:
            self.etiqueta_estado.setText(f"No se pudo cambiar: {resultado}")

    def _editar_modems(self):
        DialogoEditarGateways(self).exec()
        self.close()  # la lista de botones de arriba quedaría desactualizada -- que lo vuelvan a abrir


class DialogoEditarGateways(QDialog):
    """Catálogo de módems conocidos (nombre + IP de su puerta de enlace),
    editable a mano por cualquier Operador -- no es un dato de plata ni
    de negocio, mismo nivel de confianza que Reiniciar/Apagar. Se guarda
    entero de una (ver config_red_repo.guardar_gateways), no fila por
    fila, porque es una lista chica pensada para editarse de vez en
    cuando, no un catálogo grande con altas/bajas frecuentes."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Editar módems")
        self.resize(380, 320)

        self.tabla = QTableWidget(0, 2)
        self.tabla.setHorizontalHeaderLabels(["Nombre", "IP (puerta de enlace)"])
        self.tabla.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        self.tabla.horizontalHeader().setSectionResizeMode(1, QHeaderView.Stretch)
        for gateway in config_red_repo.obtener_gateways():
            self._agregar_fila(gateway["nombre"], gateway["ip"])

        boton_agregar = QPushButton("Agregar módem")
        boton_agregar.clicked.connect(lambda: self._agregar_fila("", ""))
        boton_quitar = QPushButton("Quitar seleccionado")
        aplicar_clase(boton_quitar, "peligro")
        boton_quitar.clicked.connect(self._quitar_seleccionado)
        fila_botones = QHBoxLayout()
        fila_botones.addWidget(boton_agregar)
        fila_botones.addWidget(boton_quitar)

        boton_guardar = QPushButton("Guardar")
        aplicar_clase(boton_guardar, "primario")
        boton_guardar.clicked.connect(self._guardar)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("Módems del local:"))
        layout.addWidget(self.tabla)
        layout.addLayout(fila_botones)
        layout.addWidget(boton_guardar)
        layout.addWidget(boton_cancelar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    def _agregar_fila(self, nombre, ip):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        self.tabla.setItem(fila, 0, QTableWidgetItem(nombre))
        self.tabla.setItem(fila, 1, QTableWidgetItem(ip))

    def _quitar_seleccionado(self):
        fila = self.tabla.currentRow()
        if fila >= 0:
            self.tabla.removeRow(fila)

    @manejar_errores
    def _guardar(self):
        gateways = []
        for fila in range(self.tabla.rowCount()):
            item_nombre = self.tabla.item(fila, 0)
            item_ip = self.tabla.item(fila, 1)
            nombre = item_nombre.text().strip() if item_nombre else ""
            ip = item_ip.text().strip() if item_ip else ""
            if not nombre and not ip:
                continue
            if not nombre or not ip:
                mostrar_error(self, "Fila incompleta", "Cada módem necesita nombre e IP.")
                return
            if not config_red_repo.es_ip_valida(ip):
                mostrar_error(self, "IP inválida", f"'{ip}' no es una IP válida (ej. 192.168.1.201).")
                return
            gateways.append({"nombre": nombre, "ip": ip})
        if not gateways:
            mostrar_error(self, "Nada para guardar", "Agregá al menos un módem con nombre e IP.")
            return
        config_red_repo.guardar_gateways(gateways)
        self.close()


class DialogoTrasladarSesion(QDialog):
    """
    Pasa la sesión activa de `estacion` a otra PC (clic derecho ->
    "Intercambiar de máquina..."): el cliente se sentó en la que había
    libre y quiere su favorita cuando se libera, o dos clientes quieren
    cambiarse de lugar. Libre = se mueve; ocupada = las dos sesiones se
    intercambian. La regla vive en `pcs_repo.trasladar_sesion`; acá solo se
    elige el destino y se explica qué va a pasar con cada PC antes de
    confirmar.
    """

    def __init__(self, estacion, estados, usuario, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.usuario = usuario
        self._ocupadas = {}
        self.setWindowTitle(f"Intercambiar de máquina — {estacion['nombre']}")
        self.resize(460, 230)

        self.combo_destino = QComboBox()
        for item in estados:
            otra = item["estacion"]
            if otra["id"] == estacion["id"]:
                continue
            sesion = item["sesion"]
            segundos = item["segundos_restantes"]
            ocupada = sesion is not None and bool(segundos)
            if ocupada:
                quien = sesion["miembro_nombre"] or "Bono"
                texto = f"{otra['nombre']} — ocupada ({quien}, {formato_tiempo(segundos)})"
            else:
                texto = f"{otra['nombre']} — libre"
            self._ocupadas[otra["id"]] = ocupada
            self.combo_destino.addItem(texto, otra["id"])

        self.etiqueta_efecto = QLabel()
        self.etiqueta_efecto.setWordWrap(True)
        self.combo_destino.currentIndexChanged.connect(lambda _indice: self._actualizar_efecto())

        self.boton_confirmar = QPushButton("Pasar sesión")
        aplicar_clase(self.boton_confirmar, "primario")
        self.boton_confirmar.clicked.connect(self._confirmar)
        self.boton_confirmar.setEnabled(self.combo_destino.count() > 0)
        boton_cancelar = QPushButton("Cancelar")
        boton_cancelar.clicked.connect(self.reject)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_cancelar)
        botones.addWidget(self.boton_confirmar)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"¿A qué PC pasa la sesión de '{estacion['nombre']}'?"))
        layout.addWidget(self.combo_destino)
        layout.addWidget(self.etiqueta_efecto)
        layout.addStretch()
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)
        self._actualizar_efecto()

    def _actualizar_efecto(self):
        destino_id = self.combo_destino.currentData()
        if destino_id is None:
            self.etiqueta_efecto.setText("No hay otras PCs activas para elegir.")
            return
        origen = self.estacion["nombre"]
        destino = self.combo_destino.currentText().split(" — ")[0]
        if self._ocupadas[destino_id]:
            self.etiqueta_efecto.setText(
                f"'{origen}' y '{destino}' intercambian sus sesiones: cada cliente se pasa a la "
                "PC del otro, cada uno con su propio tiempo restante. Ninguna de las dos se reinicia."
            )
        else:
            self.etiqueta_efecto.setText(
                f"'{origen}' pasa a '{destino}' con todo su tiempo restante, sin cobrar de nuevo. "
                f"'{origen}' se va a bloquear y reiniciar a los pocos segundos: avisale al cliente "
                "antes de confirmar."
            )

    @manejar_errores
    def _confirmar(self):
        destino_id = self.combo_destino.currentData()
        if destino_id is None:
            return
        pcs_repo.trasladar_sesion(self.estacion["id"], destino_id, self.usuario["id"])
        self.accept()


class DialogoVolumen(QDialog):
    """Ajusta el volumen maestro de la estación elegida (0-100%). A
    diferencia de Cambiar red, esto casi no puede fallar del lado de la
    PC (no necesita Administrador, es una propiedad de la sesión del
    usuario actual) -- por eso queda fire-and-forget, mismo criterio que
    Mensaje: se encola y listo, sin esperar confirmación de vuelta."""

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Ajustar volumen — {estacion['nombre']}")
        self.resize(320, 160)

        self.slider = QSlider(Qt.Horizontal)
        self.slider.setRange(0, 100)
        self.slider.setValue(50)
        self.etiqueta_valor = QLabel("50%")
        self.etiqueta_valor.setAlignment(Qt.AlignCenter)
        self.slider.valueChanged.connect(lambda valor: self.etiqueta_valor.setText(f"{valor}%"))

        boton_aplicar = QPushButton("Aplicar")
        aplicar_clase(boton_aplicar, "primario")
        boton_aplicar.clicked.connect(self._aplicar)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)

        layout = QVBoxLayout()
        layout.addWidget(QLabel(f"Volumen de '{estacion['nombre']}':"))
        layout.addWidget(self.slider)
        layout.addWidget(self.etiqueta_valor)
        layout.addWidget(boton_aplicar)
        layout.addWidget(boton_cerrar)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _aplicar(self):
        nivel = self.slider.value()
        comandos_pc_repo.encolar_comando(
            self.estacion["id"], comandos_pc_repo.TIPO_VOLUMEN, str(nivel)
        )
        mostrar_info(
            self, "Enviado",
            f"El volumen de '{self.estacion['nombre']}' se va a ajustar a {nivel}% en los "
            "próximos segundos.",
        )
