"""
pcs_actualizacion_dialogo.py
============================
"Actualizar el Cliente PC de las PCs...": el Admin carga un PCcliente.exe nuevo, marca a qué PCs
va y ve, en palabras, cómo va cada una. Rehecha a pedido del dueño el 2026-10-19 (eligió la
maqueta "A": una tabla con casillas): antes había PCs "de prueba" y "Mandarla a TODAS", y no le
resultaba claro qué hacer ni cómo quedaba cada PC. Se refresca sola cada pocos segundos, así el
"Actualizada con éxito" aparece sin tocar nada. Se abre desde Gestionar Estaciones. Las reglas
-firmar, qué versión le toca a cada PC, cómo está cada una- son de `actualizacion_cliente_repo`.

Las versiones se muestran con su número (V1, V1.1...: pedido del dueño, 2026-10-19), el que trae
cada PCcliente.exe desde la V1. Uno armado antes no tiene: se lo muestra por la fecha en que se
cargó.

Desde el 2026-10-22 (pedido del dueño) se dice además el número del Lanzador.exe de cada PC
(desde la V1.4 el Cliente PC se lo cambia solo) y, si una PC ya copió la versión, se reinició y
sigue sin ponerla, por qué y qué hacer en esa PC (`repo.seguir_la_copia`).

Desde el 2026-10-29 la tabla es un tablero por etapas (diseño "D", que eligió el dueño entre seis):
una columna por cómo va la actualización (Copiando, Falta reiniciar, Al día, Con problema, Sin
conexión y, si hay alguna, Sin marcar) y una tarjeta por PC con su casilla. Qué le pasa a cada PC lo
decide `repo.situacion`; acá solo se la pone en su columna. Las que están al día van chiquitas, solo
con la casilla y el nombre, para que entren muchas. Los colores están en ui/hoja_de_estilos.py.
"""

import re

from PySide6.QtCore import Qt, QTimer
from PySide6.QtWidgets import (
    QDialog, QFileDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QScrollArea, QVBoxLayout, QWidget,
)

from control_pcs.repositories import actualizacion_cliente_repo as repo
from control_pcs.ui.dibujos_de_ventana import CasillaDibujada, pixmap_de, poner_icono
from errores import registrar_error
from ui.piezas_ventana import TONO_AMARILLO, TONO_AZUL, TONO_GRIS, TONO_ROJO, TONO_VERDE, pastilla_clara, tecla
from ui.utils import confirmar, manejar_errores, mostrar_info, sin_boton_por_defecto

# Desde la V2 del Cliente PC (2026-10-28) la versión puede ser un .zip: el Cliente PC armado en
# carpeta, para que las PCs no lo desempaqueten en cada arranque (ver actualizacion_cliente_repo).
FILTRO_EXE = "El Cliente PC (PCcliente.exe o PCcliente_V2.zip) (*.exe *.zip)"
# Cada cuánto se vuelve a leer cómo está cada PC (las PCs cuentan cada 5 s).
REFRESCO_MS = 3000

# El tablero (diseño "D" que eligió el dueño el 2026-10-29): cada PC es una tarjeta que cambia de
# columna a medida que avanza la actualización. (clave, título, color, situaciones que caen ahí.)
# "Sin marcar" solo se ve si hay alguna PC en esa situación: casi siempre están todas marcadas.
COLUMNAS_DEL_TABLERO = (
    ("sin_marcar", "Sin marcar", "gris", (repo.NO_SELECCIONADA,)),
    ("copiando", "Copiando", "azul", (repo.ESPERANDO, repo.COPIANDO)),
    ("falta_reiniciar", "Falta reiniciar", "turquesa", (repo.LISTA,)),
    ("al_dia", "Al día", "verde", (repo.FUNCIONANDO,)),
    ("con_problema", "Con problema", "rojo",
     (repo.ERROR, repo.FALLO, repo.SE_BORRA, repo.SIN_LANZADOR, repo.FALTA_PUENTE)),
    ("sin_conexion", "Sin conexión", "gris", (repo.APAGADA, repo.NUNCA_CONECTADA, repo.INSTALACION_VIEJA)),
)
# Cuánto ancho se lleva cada columna (la de las que están al día, con sus casillas en fila, más).
ANCHO_DE_LAS_COLUMNAS = {"sin_marcar": 3, "copiando": 3, "falta_reiniciar": 3, "al_dia": 6, "con_problema": 4,
                         "sin_conexion": 3}
CASILLAS_POR_FILA = 3
# El tono de cada tarjeta (el borde y el color de lo que dice): ver ui/hoja_de_estilos.py.
TONO_DE_LA_SITUACION = {
    repo.FUNCIONANDO: TONO_VERDE, repo.LISTA: TONO_VERDE, repo.COPIANDO: TONO_AZUL, repo.ESPERANDO: TONO_AMARILLO,
    repo.ERROR: TONO_ROJO, repo.FALLO: TONO_ROJO, repo.SE_BORRA: TONO_ROJO, repo.SIN_LANZADOR: TONO_ROJO,
    repo.FALTA_PUENTE: TONO_AMARILLO, repo.APAGADA: TONO_GRIS, repo.NO_SELECCIONADA: TONO_GRIS,
    repo.NUNCA_CONECTADA: TONO_GRIS, repo.INSTALACION_VIEJA: TONO_GRIS,
}
PASOS = ("Marcás la PC", "Copia la versión sola", "Se reinicia para ponerla", "Queda al día")
ANCHO_DE_LA_VENTANA = 1320
ALTO_DE_LA_VENTANA = 860
# Para el resumen de arriba: por qué le falta a cada una.
_POR_QUE_FALTA = {
    repo.APAGADA: "apagada", repo.COPIANDO: "copiando", repo.ERROR: "error", repo.FALLO: "falló",
    repo.ESPERANDO: "esperando", repo.NUNCA_CONECTADA: "nunca se conectó",
    repo.INSTALACION_VIEJA: "instalación vieja",
    repo.SE_BORRA: "se borra al reiniciar", repo.SIN_LANZADOR: "no arranca con el Lanzador",
    repo.FALTA_PUENTE: "le falta la V1.9",
}

# Un número de versión (AAAAMMDDhhmmss) dentro de un texto que manda la PC.
_NUMERO_DE_VERSION = re.compile(r"\b20\d{12}\b")


def _con_fechas(texto: str, pc: dict) -> str:
    """El texto que manda la PC, con cada número de versión como fecha ("18/10/2026 19:30"), o
    como "V1.2" si es la que le toca y tiene número."""
    def reemplazo(encontrado):
        if pc.get("v_le_toca") and str(pc.get("le_toca")) == encontrado.group():
            return repo.nombre_de_version(pc["v_le_toca"])
        return repo.texto_version(encontrado.group())
    return _NUMERO_DE_VERSION.sub(reemplazo, texto)


def texto_de_la_version(pc: dict) -> str:
    """La columna "Versión en uso": el número que manda la PC (V1, V1.1...). Una que se conectó
    y no manda ninguno tiene un Cliente PC armado antes de la V1."""
    if pc.get("v"):
        return repo.nombre_de_version(pc["v"])
    return "anterior a la V1" if pc.get("ultima_conexion") or pc.get("carpeta") else ""


def texto_del_lanzador(pc: dict) -> str:
    """La columna "Lanzador": el número del Lanzador.exe que manda la PC (desde la V1.4). Una con
    lanzador que no lo manda tiene un Cliente PC anterior a la V1.4: "—"."""
    if pc.get("lanzador"):
        return str(pc["lanzador"])
    return "—" if pc.get("carpeta") else ""


def texto_de_la_version_cargada(paquete: dict) -> str:
    """"V1.2 (cargada el 19/10/2026 09:23)"; sin número, la fecha y que es de antes de la V1."""
    cuando = repo.texto_version(paquete["version"])
    if paquete.get("v"):
        return f"{repo.nombre_de_version(paquete['v'])} (cargada el {cuando})"
    return f"{cuando} (sin número: armada antes de la V1)"


def texto_del_estado(pc: dict) -> str:
    """Cómo va la actualización de una PC, en palabras, para la tabla."""
    situacion = repo.situacion(pc)
    detalle = _con_fechas(pc["detalle"], pc)
    funcionando = (f"Funcionando con la {repo.nombre_de_version(pc['v_le_toca'])}" if pc.get("v_le_toca")
                   else "Funcionando con la versión nueva")
    return {
        repo.NUNCA_CONECTADA: "Nunca se conectó a este CYBERCONTROL (¿apagada o con otro nombre?)",
        repo.INSTALACION_VIEJA: "Instalación vieja: hay que reinstalarla con el pendrive (preparar_pc.bat)",
        repo.NO_SELECCIONADA: "No seleccionada",
        repo.FUNCIONANDO: funcionando,
        repo.LISTA: "Actualizada con éxito · se aplica al reiniciarse (sola, si está libre)",
        repo.SE_BORRA: ("No se puso: el reinicio borró la copia (la volvió a copiar). Excluí la carpeta del "
                        "Cliente PC en Shadow Defender y reiniciala"),
        repo.SIN_LANZADOR: ("No se puso al reiniciar: la PC no arranca con Lanzador.exe. Con Shadow Defender "
                            "desactivado, abrí «Lanzador.exe --configurar» como Administrador"),
        repo.FALTA_PUENTE: ("Le falta la V1.9: esta versión va en carpeta y su Lanzador todavía no la sabe "
                            "poner. Primero tiene que tener la V1.9 (Lanzador 3)"),
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


class TarjetaPc(QFrame):
    """Una PC en el tablero: su casilla, su nombre y cómo va. La "compacta" es la de las que ya
    están al día (solo la casilla y el nombre, para que entren muchas); las demás llevan además su
    versión, su lanzador y lo que pasa. Un clic en cualquier parte de la tarjeta tilda o destilda
    su casilla. Los textos están siempre (aunque la compacta no los muestre): salen de las mismas
    funciones de abajo que usaba la tabla de antes."""

    def __init__(self, pc: dict, marcada: bool, compacta: bool):
        super().__init__()
        self.pc_id = pc["id"]
        self.situacion = repo.situacion(pc)
        tono = TONO_DE_LA_SITUACION[self.situacion]
        self.setObjectName("chipPc" if compacta else "tarjetaPc")
        self.setProperty("tono", tono)
        self.setCursor(Qt.PointingHandCursor)
        self.casilla = CasillaDibujada(marcada, 14 if compacta else 16)
        self.nombre = QLabel(pc["nombre"])
        self.nombre.setObjectName("nombrePc")
        texto_del_estado_de_la_pc = texto_del_estado(pc)
        self.estado = QLabel(texto_del_estado_de_la_pc)
        self.estado.setObjectName("estadoPc")
        self.estado.setProperty("tono", tono)
        self.estado.setWordWrap(True)
        version = texto_de_la_version(pc)
        self.version = pastilla_clara(version, TONO_GRIS, chica=True)
        lanzador = texto_del_lanzador(pc)
        self.lanzador = pastilla_clara(f"Lanz. {lanzador}" if lanzador else "", TONO_GRIS, chica=True)
        if lanzador == "—":
            self.lanzador.setToolTip("Su Cliente PC es anterior a la V1.4 y no lo dice")
        lineas = [pc["nombre"], texto_del_estado_de_la_pc]
        if version or lanzador:
            lineas.append(f"Versión en uso: {version or '—'} · Lanzador: {lanzador or '—'}")
        if pc["carpeta"]:
            lineas.append(f"Instalado en: {pc['carpeta']}")
        self.setToolTip("\n".join(lineas))

        if compacta:
            capa = QHBoxLayout(self)
            capa.setContentsMargins(7, 0, 6, 0)
            capa.setSpacing(6)
            capa.addWidget(self.casilla)
            capa.addWidget(self.nombre)
            capa.addStretch()
            self.setFixedHeight(32)
            for sobrante in (self.estado, self.version, self.lanzador):
                sobrante.setParent(self)
                sobrante.hide()
            return
        capa = QVBoxLayout(self)
        capa.setContentsMargins(12, 10, 12, 10)
        capa.setSpacing(4)
        arriba = QHBoxLayout()
        arriba.setSpacing(8)
        arriba.addWidget(self.casilla)
        arriba.addWidget(self.nombre)
        arriba.addStretch()
        capa.addLayout(arriba)
        pastillas = QHBoxLayout()
        pastillas.setSpacing(6)
        hay_pastillas = False
        for pastilla in (self.version, self.lanzador):
            if pastilla.text():
                pastillas.addWidget(pastilla)
                hay_pastillas = True
            else:
                pastilla.setParent(self)
                pastilla.hide()
        pastillas.addStretch()
        if hay_pastillas:
            capa.addLayout(pastillas)
        capa.addWidget(self.estado)

    def mousePressEvent(self, evento):
        if evento.button() == Qt.LeftButton:
            self.casilla.toggle()


class DialogoActualizarCliente(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowTitle("Actualizar el Cliente PC de las PCs")
        # Ancha para que entren las columnas del tablero con los avisos de qué hacer en una PC que
        # no puso la versión (2026-10-22), sin pasar del tamaño de la pantalla.
        ancho, alto = ANCHO_DE_LA_VENTANA, ALTO_DE_LA_VENTANA
        if self.screen() is not None:
            disponible = self.screen().availableGeometry()
            ancho, alto = min(ancho, disponible.width() - 20), min(alto, disponible.height() - 60)
        self.resize(ancho, alto)
        self.pcs = []
        self.tarjetas = {}      # id de la PC -> su TarjetaPc
        self._marcas = {}       # id de la PC -> si está tildada (también lo que no se guardó)
        self._firma = None      # cómo se veía el tablero la última vez, para no rehacerlo si no cambió
        self._armar_interfaz()
        self._cargar()
        self._timer = QTimer(self)
        self._timer.setInterval(REFRESCO_MS)
        self._timer.timeout.connect(self._refrescar_solo)
        self._timer.start()

    def _armar_interfaz(self):
        # Título, la versión cargada y el botón para cargar otra.
        titulos = QVBoxLayout()
        titulos.setSpacing(0)
        titulo = QLabel("Actualizar el Cliente PC")
        titulo.setObjectName("tituloVentana")
        subtitulo = QLabel("Cada PC avanza de izquierda a derecha hasta quedar al día")
        subtitulo.setObjectName("subtituloVentana")
        titulos.addWidget(titulo)
        titulos.addWidget(subtitulo)
        self.caption_version = QLabel("VERSIÓN CARGADA")
        self.caption_version.setObjectName("captionChip")
        self.etiqueta_version = QLabel()
        self.etiqueta_version.setObjectName("valorChip")
        chip = QFrame()
        chip.setObjectName("chipVersion")
        capa_chip = QHBoxLayout(chip)
        capa_chip.setContentsMargins(14, 7, 14, 7)
        capa_chip.setSpacing(10)
        capa_chip.addWidget(self.caption_version)
        capa_chip.addWidget(self.etiqueta_version)
        boton_cargar = tecla("Cargar versión nueva...", self._cargar_version)
        poner_icono(boton_cargar, "subir")
        fila_titulo = QHBoxLayout()
        fila_titulo.setSpacing(12)
        fila_titulo.addLayout(titulos)
        fila_titulo.addStretch()
        fila_titulo.addWidget(chip)
        fila_titulo.addWidget(boton_cargar)

        # El camino de una actualización, en una línea.
        cinta = QFrame()
        cinta.setObjectName("cintaDePasos")
        capa_cinta = QHBoxLayout(cinta)
        capa_cinta.setContentsMargins(18, 10, 18, 10)
        capa_cinta.setSpacing(10)
        for numero, texto in enumerate(PASOS, start=1):
            etiqueta_numero = QLabel(str(numero))
            etiqueta_numero.setObjectName("numeroDePaso")
            etiqueta_texto = QLabel(texto)
            etiqueta_texto.setObjectName("textoDePaso")
            capa_cinta.addWidget(etiqueta_numero)
            capa_cinta.addWidget(etiqueta_texto)
            if numero < len(PASOS):
                flecha = QLabel()
                flecha.setPixmap(pixmap_de("flecha", 18, "#A7B0C0"))
                capa_cinta.addWidget(flecha)
        capa_cinta.addStretch()
        nota = QLabel("Si no arranca bien, vuelve sola a la anterior")
        nota.setObjectName("notaDePasos")
        capa_cinta.addWidget(nota)

        self.etiqueta_resumen = QLabel()
        self.etiqueta_resumen.setObjectName("resumenActualizacion")
        self.etiqueta_resumen.setWordWrap(True)

        # El tablero: una columna por etapa, con una tarjeta por PC.
        self.area = QScrollArea()
        self.area.setObjectName("areaTablero")
        self.area.setWidgetResizable(True)
        self.area.setFrameShape(QFrame.NoFrame)
        self.area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tablero = QWidget()
        self.capa_columnas = QHBoxLayout(tablero)
        self.capa_columnas.setContentsMargins(0, 0, 0, 0)
        self.capa_columnas.setSpacing(12)
        self.area.setWidget(tablero)

        boton_todas = tecla("Marcar todas", lambda: self._marcar_todas(True))
        boton_ninguna = tecla("Desmarcar todas", lambda: self._marcar_todas(False))
        self.boton_actualizar = tecla("Actualizar las seleccionadas", self._actualizar_seleccionadas, "teclaAzul")
        poner_icono(self.boton_actualizar, "subir", 16, "#FFFFFF")
        self.boton_actualizar.setStyleSheet("padding: 10px 26px; font-size: 14px;")
        boton_cerrar = tecla("Cerrar", self.reject, "teclaRoja")
        self.etiqueta_marcadas = QLabel()
        self.etiqueta_marcadas.setObjectName("notaDePasos")
        fila_abajo = QHBoxLayout()
        fila_abajo.setSpacing(10)
        fila_abajo.addWidget(self.etiqueta_marcadas)
        fila_abajo.addStretch()
        fila_abajo.addWidget(boton_todas)
        fila_abajo.addWidget(boton_ninguna)
        fila_abajo.addWidget(self.boton_actualizar)
        fila_abajo.addWidget(boton_cerrar)

        layout = QVBoxLayout()
        layout.setContentsMargins(24, 20, 24, 18)
        layout.setSpacing(14)
        layout.addLayout(fila_titulo)
        layout.addWidget(cinta)
        layout.addWidget(self.etiqueta_resumen)
        layout.addWidget(self.area, 1)
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
            self.etiqueta_version.setText(f"{texto_de_la_version_cargada(paquete)} · {megas} MB")
        self.caption_version.setVisible(paquete is not None)
        self._hay_version = paquete is not None
        self._mostrar(conservar_casillas=False)
        self._guardado = self._ids_marcados()

    def _refrescar_solo(self):
        """Lo que dispara el timer: sin carteles si algo falla (se volvería a mostrar cada 3 s); queda
        en el log de errores y el tablero sigue con lo último que leyó."""
        try:
            self._mostrar(conservar_casillas=True)
        except RuntimeError as error:
            if "already deleted" not in str(error):    # la ventana se está cerrando
                registrar_error(error, "Actualizar el Cliente PC: refrescar el tablero")
        except Exception as error:
            registrar_error(error, "Actualizar el Cliente PC: refrescar el tablero")

    def _mostrar(self, conservar_casillas: bool):
        """Vuelve a leer cómo está cada PC. Con `conservar_casillas`, lo que el Admin tildó y no
        guardó queda como está. El tablero solo se rehace si algo cambió (una PC pasó de etapa, un
        texto es otro): si no, no se mueve nada mientras se mira o se tilda."""
        pcs = repo.estado_de_las_pcs()
        if conservar_casillas:
            self._marcas = {pc["id"]: self._marcas.get(pc["id"], False) for pc in pcs}
        else:
            self._marcas = {pc["id"]: bool(pc["seleccionada"]) for pc in pcs}
            self._firma = None
        self.pcs = pcs
        firma = tuple((pc["id"], pc["nombre"], repo.situacion(pc), texto_del_estado(pc), texto_de_la_version(pc),
                       texto_del_lanzador(pc), pc["carpeta"]) for pc in pcs)
        if firma != self._firma:
            self._firma = firma
            self._armar_el_tablero()
        self.etiqueta_resumen.setText(texto_del_resumen(pcs, self._hay_version))
        self._contar_las_marcadas()

    def _armar_el_tablero(self):
        while self.capa_columnas.count():
            columna = self.capa_columnas.takeAt(0).widget()
            if columna is not None:
                # Sin padre ya no se ve (si no, quedaría encima de la nueva hasta que Qt la borre).
                columna.setParent(None)
                columna.deleteLater()
        self.tarjetas = {}
        for clave, titulo, tono, situaciones in COLUMNAS_DEL_TABLERO:
            propias = [pc for pc in self.pcs if repo.situacion(pc) in situaciones]
            if clave == "sin_marcar" and not propias:
                continue
            tarjetas = []
            for pc in propias:
                tarjeta = TarjetaPc(pc, self._marcas.get(pc["id"], False), compacta=clave == "al_dia")
                tarjeta.casilla.toggled.connect(lambda marcada, pc_id=pc["id"]: self._al_tildar(pc_id, marcada))
                self.tarjetas[pc["id"]] = tarjeta
                tarjetas.append(tarjeta)
            self.capa_columnas.addWidget(self._columna(titulo, tono, tarjetas, en_grilla=clave == "al_dia"),
                                         ANCHO_DE_LAS_COLUMNAS[clave])

    @staticmethod
    def _columna(titulo: str, tono: str, tarjetas: list, en_grilla: bool) -> QFrame:
        marco = QFrame()
        marco.setObjectName("columnaTablero")
        capa = QVBoxLayout(marco)
        capa.setContentsMargins(12, 12, 12, 12)
        capa.setSpacing(10)
        punto = QLabel()
        punto.setObjectName("puntoColumna")
        punto.setProperty("tono", tono)
        punto.setFixedSize(10, 10)
        etiqueta_titulo = QLabel(titulo)
        etiqueta_titulo.setObjectName("tituloColumna")
        cuenta = QLabel(str(len(tarjetas)))
        cuenta.setObjectName("cuentaColumna")
        cuenta.setProperty("tono", tono)
        cuenta.setAlignment(Qt.AlignCenter)
        cabecera = QHBoxLayout()
        cabecera.setSpacing(8)
        cabecera.addWidget(punto)
        cabecera.addWidget(etiqueta_titulo)
        cabecera.addStretch()
        cabecera.addWidget(cuenta)
        capa.addLayout(cabecera)
        if en_grilla:
            grilla = QGridLayout()
            grilla.setSpacing(8)
            for lugar, tarjeta in enumerate(tarjetas):
                grilla.addWidget(tarjeta, lugar // CASILLAS_POR_FILA, lugar % CASILLAS_POR_FILA)
            for columna in range(CASILLAS_POR_FILA):
                grilla.setColumnStretch(columna, 1)
            capa.addLayout(grilla)
        else:
            for tarjeta in tarjetas:
                capa.addWidget(tarjeta)
        capa.addStretch()
        return marco

    def _al_tildar(self, pc_id: int, marcada: bool):
        self._marcas[pc_id] = marcada
        self._contar_las_marcadas()

    def _contar_las_marcadas(self):
        cuantas = len(self._ids_marcados())
        self.etiqueta_marcadas.setText(f"{cuantas} PC{'s' if cuantas != 1 else ''} "
                                       f"marcada{'s' if cuantas != 1 else ''}")

    def _ids_marcados(self) -> set:
        return {pc["id"] for pc in self.pcs if self._marcas.get(pc["id"])}

    # -- acciones ----------------------------------------------------------------
    def _marcar_todas(self, marcar: bool):
        for tarjeta in self.tarjetas.values():
            tarjeta.casilla.setChecked(marcar)

    @manejar_errores
    def _cargar_version(self):
        ruta, _filtro = QFileDialog.getOpenFileName(self, "Elegir el Cliente PC nuevo", "", FILTRO_EXE)
        if not ruta:
            return
        with open(ruta, "rb") as archivo:
            datos = archivo.read()
        if not confirmar(self, "Cargar versión nueva", self._pregunta_para_cargar(datos)):
            return
        manifiesto = repo.publicar(datos)
        self._cargar()
        cual = (repo.nombre_de_version(manifiesto["v"]) if manifiesto.get("v")
                else f"Versión {repo.texto_version(manifiesto['version'])}")
        mostrar_info(self, "Versión cargada",
                     f"{cual} cargada y firmada.\n\nAhora marcá las PCs y tocá «Actualizar las seleccionadas».")

    @staticmethod
    def _pregunta_para_cargar(datos: bytes) -> str:
        """Qué versión es la que se va a cargar y, si es más vieja que la cargada, que lo sepa. Si es
        una versión en carpeta (un .zip), que solo les llega a las PCs que ya tienen la V1.9."""
        numero = repo.numero_de_version_del_paquete(datos)
        en_carpeta = repo.es_en_carpeta(datos)
        cual = "esta versión en carpeta (.zip)" if en_carpeta else "este PCcliente.exe"
        if not numero:
            pregunta = (f"¿Cargar {cual} como la versión nueva de las PCs?\n\n"
                        "No tiene número de versión: es uno armado antes de la V1.")
        else:
            nuevo = repo.nombre_de_version(numero)
            pregunta = f"¿Cargar {cual} ({nuevo}) como la versión nueva de las PCs?"
            cargada = repo.paquete()
            if cargada and cargada["v"] and repo.es_mas_vieja(numero, cargada["v"]):
                actual = repo.nombre_de_version(cargada["v"])
                pregunta += (f"\n\nOjo: la {nuevo} es más vieja que la {actual} que está cargada ahora. "
                             f"Las PCs que marques y ya tengan la {actual} van a volver a la {nuevo}.")
        if en_carpeta:
            pregunta += ("\n\nVa en carpeta: solo la pueden poner las PCs que ya tienen la V1.9 (Lanzador 3). "
                         "Cargala cuando todas digan «3» en la columna Lanzador: la que esté cargada ahora deja "
                         "de llegarles a las que todavía no la tienen.")
        return pregunta + "\n\nNo va a ninguna PC hasta que las marques y toques «Actualizar las seleccionadas»."

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
                         "unos segundos y acá vas a ver «Actualizada con éxito». Las libres se reinician "
                         "solas para ponerla; las que tienen un cliente, cuando ese cliente termina.")
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
