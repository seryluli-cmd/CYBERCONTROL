"""
pcs_reiniciar_dialogo.py
========================
Reiniciar o apagar varias PCs de una vez (botones REINICIAR y APAGAR de abajo
del mosaico de Control de PCs, pedidos del dueño 2026-10-22 y 2026-10-23).
Se pueden marcar solo las PCs prendidas y libres, y arrancan todas marcadas: se
desmarcan las que no se quieren tocar y se manda. Igual que la ventana de
DESCONGELAR, que arranca con las mismas marcadas.

Con el diseño que eligió el dueño el 2026-10-28 (maqueta "B", en
PROPUESTA_VENTANA_APAGAR): la cabecera oscura de ui/piezas_ventana.py, el aviso
de que solo se tocan las prendidas y libres, y las PCs como fichas sobre el
fondo negro, como en el mosaico: un clic marca o desmarca. Las que están en uso
se ven aparte, con el tiempo que les queda, y no se pueden marcar: así se ve
cuáles no se van a tocar y por qué.

Las dos ventanas son la misma: DialogoApagar solo cambia los textos, el
dibujito y qué se manda.

Cuáles son las prendidas y libres, y volver a mirarlas antes de mandar, es de
pcs_libres_repo: una PC donde se sentó un cliente mientras la ventana estaba
abierta no se toca.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QScrollArea, QVBoxLayout, QWidget,
)

from control_pcs.repositories import comandos_pc_repo, pcs_libres_repo
from control_pcs.ui.pcs_dibujos import icono_apagar, icono_reiniciar
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_NARANJA, TONO_ROJO, agregar_pastilla, cabecera_oscura, tarjeta_de_menu, tecla,
)
from ui.utils import confirmar, manejar_errores, mostrar_info, sin_boton_por_defecto

COLUMNAS_DE_FICHAS = 7
ANCHO_FICHA, ALTO_FICHA = 118, 58

# Cómo se ve cada ficha: la propiedad "estado" que lee la hoja de estilos.
MARCADA, DESMARCADA, EN_USO = "marcada", "desmarcada", "enUso"


def _repintar(widget):
    """Qt no vuelve a mirar la hoja de estilos cuando cambia una propiedad: se lo pide
    a la ficha y a sus etiquetas, que toman el color según el estado de la ficha."""
    for cada_uno in (widget, *widget.findChildren(QLabel)):
        cada_uno.style().unpolish(cada_uno)
        cada_uno.style().polish(cada_uno)


class FichaPc(QPushButton):
    """
    Una PC como una ficha del mosaico: el nombre, una línea de cómo está y el ✔ si
    está marcada. Una libre se marca o se desmarca con un clic y dice lo que le va a
    pasar (`textos`: marcada y desmarcada, "SE APAGA" / "NO SE APAGA"). Con `quedan`
    es una PC en uso: muestra el tiempo que le queda y no se puede marcar.
    """

    def __init__(self, item, textos=("", ""), quedan: str = None):
        super().__init__()
        self.setObjectName("fichaPc")
        self.estacion_id = item["estacion"]["id"]
        self.nombre = item["estacion"]["nombre"]
        self._textos = textos
        self.setAccessibleName(self.nombre)
        self.setFixedSize(ANCHO_FICHA, ALTO_FICHA)

        etiqueta_nombre = QLabel(self.nombre)
        etiqueta_nombre.setObjectName("nombreFicha")
        self.marca = QLabel("✔")
        self.marca.setObjectName("marcaFicha")
        self.detalle = QLabel()
        self.detalle.setObjectName("detalleFicha")
        for etiqueta in (etiqueta_nombre, self.marca, self.detalle):
            # Que el clic le llegue a la ficha aunque caiga sobre el texto.
            etiqueta.setAttribute(Qt.WA_TransparentForMouseEvents)
        fila = QHBoxLayout()
        fila.addWidget(etiqueta_nombre)
        fila.addStretch()
        fila.addWidget(self.marca)
        capa = QVBoxLayout(self)
        capa.setContentsMargins(10, 6, 8, 8)
        capa.setSpacing(1)
        capa.addLayout(fila)
        capa.addWidget(self.detalle)

        if quedan is None:
            self.setCheckable(True)
            self.toggled.connect(self._mostrar)
            self._mostrar(False)
        else:
            self.setEnabled(False)
            self.marca.hide()
            self.detalle.setText(f"QUEDAN {quedan}")
            self.setProperty("estado", EN_USO)

    def _mostrar(self, marcada: bool):
        self.marca.setVisible(marcada)
        self.detalle.setText(self._textos[0] if marcada else self._textos[1])
        self.setProperty("estado", MARCADA if marcada else DESMARCADA)
        _repintar(self)


def _quedan(segundos: int) -> str:
    """Lo que le queda a una PC en uso, sin los segundos ("1h 25m", "40m"): la
    ventana no se redibuja, y unos segundos quietos parecerían un reloj trabado."""
    horas, minutos = divmod(max(0, segundos) // 60, 60)
    return f"{horas}h {minutos:02d}m" if horas else f"{minutos}m"


def _grilla(fichas) -> QWidget:
    """Las fichas en filas de COLUMNAS_DE_FICHAS, pegadas a la izquierda."""
    grilla = QWidget()
    grilla.setObjectName("contenidoFichas")
    capa = QGridLayout(grilla)
    capa.setContentsMargins(0, 0, 0, 0)
    capa.setHorizontalSpacing(8)
    capa.setVerticalSpacing(8)
    for numero, ficha in enumerate(fichas):
        capa.addWidget(ficha, numero // COLUMNAS_DE_FICHAS, numero % COLUMNAS_DE_FICHAS)
    capa.setColumnStretch(COLUMNAS_DE_FICHAS, 1)
    return grilla


def _titulo_oscuro(texto: str, tono: str = "") -> QLabel:
    """El título chiquito de un grupo de fichas, sobre el fondo negro."""
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("tituloFichas")
    if tono:
        etiqueta.setProperty("tono", tono)
    return etiqueta


class DialogoReiniciar(QDialog):
    TITULO = "Reiniciar"
    INFINITIVO = "reiniciar"            # "Se van a reiniciar 2 PC(s)"
    PASADO = "reinició"                 # "No se reinició ninguna PC"
    PASADO_PLURAL = "reiniciaron"       # "No se reiniciaron porque..."
    PRESENTE = "reinicia"               # lo que dice cada ficha: "SE REINICIA"
    PRESENTE_PLURAL = "reinician"       # el aviso: "Solo se reinician las PCs..."
    AVISO = "Se pierde cualquier trabajo sin guardar en esas PCs."
    FUNCION_DEL_REPO = "reiniciar"      # pcs_libres_repo.reiniciar
    ICONO = staticmethod(icono_reiniciar)

    def __init__(self, estados, parent=None):
        """`estados`: lo último que leyó la pantalla de PCs (pcs_repo.estado_estaciones)."""
        super().__init__(parent)
        self.setWindowTitle(f"{self.TITULO} PCs prendidas y libres")
        self.resize(980, 720)
        libres, en_uso, apagadas = pcs_libres_repo.separar(estados)
        textos = (f"SE {self.PRESENTE.upper()}", f"NO SE {self.PRESENTE.upper()}")
        self.fichas = [FichaPc(item, textos) for item in libres]
        self.fichas_en_uso = [
            FichaPc(item, quedan=_quedan(item["segundos_restantes"])) for item in en_uso
        ]
        self._armar_interfaz(len(apagadas))
        for ficha in self.fichas:
            ficha.toggled.connect(self._contar)
        self._marcar(True)

    def _armar_interfaz(self, cuantas_apagadas: int):
        cabecera = cabecera_oscura(
            "", f"{self.TITULO} PCs", "Solo las prendidas y libres · las que están en uso no se tocan")
        cabecera.icono.setPixmap(self.ICONO().pixmap(30, 30))
        self.pastilla_marcadas = agregar_pastilla(cabecera, "", TONO_AZUL)
        pastilla_en_uso = agregar_pastilla(cabecera, f"{len(self.fichas_en_uso)} EN USO · NO SE TOCAN", TONO_NARANJA)
        pastilla_en_uso.setVisible(bool(self.fichas_en_uso))
        pastilla_apagadas = agregar_pastilla(cabecera, f"{cuantas_apagadas} APAGADAS", TONO_GRIS)
        pastilla_apagadas.setVisible(bool(cuantas_apagadas))

        # Lo que pidió el dueño que quede escrito (2026-10-28): a las que están en uso no les pasa nada.
        en_uso = f"Las PCs en uso, con tiempo disponible, <b>no se {self.PRESENTE_PLURAL}</b>"
        if self.fichas_en_uso:
            en_uso += ": se ven abajo, aparte, y no se pueden marcar"
        self.aviso = QLabel(f"<b>Solo se {self.PRESENTE_PLURAL} las PCs PRENDIDAS y LIBRES.</b><br>{en_uso}.")
        self.aviso.setObjectName("avisoSoloLibres")
        self.aviso.setWordWrap(True)

        # El fondo negro: arriba las libres, que se marcan; abajo las que están en uso.
        fila_titulo = QHBoxLayout()
        fila_titulo.addWidget(_titulo_oscuro(
            f"PRENDIDAS Y LIBRES · {len(self.fichas)}   —   un clic marca o desmarca"))
        fila_titulo.addStretch()
        fila_titulo.addWidget(tecla("MARCAR TODAS", lambda: self._marcar(True)))
        fila_titulo.addWidget(tecla("DESMARCAR", lambda: self._marcar(False)))
        contenido = QWidget()
        contenido.setObjectName("contenidoFichas")
        capa_contenido = QVBoxLayout(contenido)
        capa_contenido.setContentsMargins(0, 0, 0, 0)
        capa_contenido.setSpacing(10)
        capa_contenido.addWidget(_grilla(self.fichas))
        if self.fichas_en_uso:
            raya = QFrame()
            raya.setObjectName("rayaFichas")
            raya.setFixedHeight(1)
            capa_contenido.addSpacing(4)
            capa_contenido.addWidget(raya)
            capa_contenido.addWidget(_titulo_oscuro(
                f"EN USO · {len(self.fichas_en_uso)}   —   tienen tiempo disponible: no se tocan", "enUso"))
            capa_contenido.addWidget(_grilla(self.fichas_en_uso))
        capa_contenido.addStretch()
        # Con muchas PCs las fichas se corren: los botones de arriba quedan siempre a la vista.
        desplazable = QScrollArea()
        desplazable.setObjectName("scrollFichas")
        desplazable.setWidgetResizable(True)
        desplazable.setFrameShape(QFrame.NoFrame)
        desplazable.setWidget(contenido)
        marco = QFrame()
        marco.setObjectName("marcoFichas")
        capa_marco = QVBoxLayout(marco)
        capa_marco.setContentsMargins(16, 14, 16, 16)
        capa_marco.setSpacing(10)
        capa_marco.addLayout(fila_titulo)
        capa_marco.addWidget(desplazable, 1)

        # Abajo: la acción, en rojo como Descongelar y reiniciar, y Cerrar aparte.
        self.boton_mandar = tarjeta_de_menu("", "", "", self._mandar, alto=58, tono=TONO_ROJO)
        self.boton_mandar.icono.setPixmap(self.ICONO().pixmap(24, 24))
        self._titulo_mandar = self.boton_mandar.findChild(QLabel, "tituloTarjeta")
        fila_accion = QHBoxLayout()
        fila_accion.addWidget(self.boton_mandar, 1)
        fila_accion.addSpacing(8)
        fila_accion.addWidget(tecla("CERRAR", self.reject, "teclaRoja"), 0, Qt.AlignVCenter)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addWidget(self.aviso)
        layout.addWidget(marco, 1)
        layout.addLayout(fila_accion)
        sin_boton_por_defecto(self)

    def _contar(self):
        """La pastilla de las marcadas y la tecla roja, que dice cuántas se van a tocar.
        Sin ninguna marcada la tecla se apaga y dice por qué."""
        cuantas = len(self._marcadas())
        self.pastilla_marcadas.setText(f"{cuantas} MARCADA{'' if cuantas == 1 else 'S'}")
        if cuantas == 1:
            titulo = f"{self.TITULO} la marcada"
        elif cuantas:
            titulo = f"{self.TITULO} las {cuantas} marcadas"
        else:
            titulo = f"{self.TITULO} las marcadas"
        self._titulo_mandar.setText(titulo.upper())
        self.boton_mandar.setAccessibleName(titulo)
        self.boton_mandar.detalle.setText(
            "Se pierde lo que no se guardó en esas PCs" if cuantas else "Marcá al menos una PC")
        self.boton_mandar.setEnabled(bool(cuantas))

    def _marcar(self, marcada: bool):
        for ficha in self.fichas:
            ficha.setChecked(marcada)
        self._contar()

    def _marcadas(self) -> list:
        """(id, nombre) de las PCs marcadas."""
        return [(ficha.estacion_id, ficha.nombre) for ficha in self.fichas if ficha.isChecked()]

    @manejar_errores
    def _mandar(self):
        marcadas = self._marcadas()
        if not marcadas:
            return
        nombres = ", ".join(nombre for _id, nombre in marcadas)
        if not confirmar(
            self, self.TITULO,
            f"Se van a {self.INFINITIVO} {len(marcadas)} PC(s):\n{nombres}\n\n{self.AVISO} ¿Seguir?",
        ):
            return
        funcion = getattr(pcs_libres_repo, self.FUNCION_DEL_REPO)
        mandadas, salteadas = funcion([estacion_id for estacion_id, _nombre in marcadas])
        if mandadas:
            texto = (f"Se les va a avisar a {len(mandadas)} PC(s) en los próximos segundos.\n\n"
                     f"Si alguna no lo recibe en {comandos_pc_repo.MINUTOS_VIGENCIA_REINICIO} minutos "
                     "(apagada o sin conexión), se descarta: así no le llega más tarde a otro cliente.")
        else:
            texto = f"No se {self.PASADO} ninguna PC."
        if salteadas:
            texto += f"\n\nNo se {self.PASADO_PLURAL} porque ya no estaban libres: {', '.join(salteadas)}."
        mostrar_info(self, self.TITULO, texto)
        self.accept()


class DialogoApagar(DialogoReiniciar):
    TITULO = "Apagar"
    INFINITIVO = "apagar"
    PASADO = "apagó"
    PASADO_PLURAL = "apagaron"
    PRESENTE = "apaga"
    PRESENTE_PLURAL = "apagan"
    AVISO = ("Se pierde cualquier trabajo sin guardar en esas PCs, y para volver a "
             "prenderlas hay que ir hasta cada una.")
    FUNCION_DEL_REPO = "apagar"
    ICONO = staticmethod(icono_apagar)
