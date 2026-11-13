"""
ofertas_piezas.py
=================
Las piezas de la ventana de Ofertas (ofertas_window.py, la maqueta B "la semana en una
grilla" que eligió el dueño el 2026-11-13 entre las de PROPUESTA_OFERTAS): la ficha de
cada oferta de arriba, el cuadrito de un día y un turno, la tarjeta de 2x1 / 50%, el
renglón de un bono con lo que queda con la oferta y el aviso de cuando dos ofertas
chocan. Y la etiqueta 2x1 / 50% (`insignia`), que va también en los botones de bonos
del panel de la PC (pcs_lista_de_bonos.py).

Solo arman widgets con su objectName y sus propiedades: los colores están en
ui/hoja_de_estilos.py ("Ofertas"). El naranja es el 2x1 y el violeta el 50%.
"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QDialog, QHBoxLayout, QLabel, QPushButton, QVBoxLayout, QWidget

import dominio
from control_pcs.repositories import ofertas_repo
from control_pcs.ui.dibujos_de_ventana import CasillaDibujada, pixmap_de
from ui.piezas_ventana import (
    TONO_AMARILLO, TONO_AZUL, TONO_GRIS, TONO_VERDE, cabecera_oscura, panel_blanco, pastilla_clara, tecla,
)
from ui.utils import formato_pesos, sin_boton_por_defecto

# El color de cada tipo de oferta: [tono="naranja"] y [tono="violeta"] en la hoja de estilos.
TONO_DEL_TIPO = {dominio.OFERTA_2X1: "naranja", dominio.OFERTA_MITAD: "violeta"}
TONO_DEL_ESTADO = {
    dominio.OFERTA_ACTIVA: TONO_VERDE, dominio.OFERTA_PROGRAMADA: TONO_AZUL,
    dominio.OFERTA_PAUSADA: TONO_AMARILLO, dominio.OFERTA_TERMINADA: TONO_GRIS,
}
QUE_ES_CADA_TIPO = {
    dominio.OFERTA_2X1: ("Pagan 1, juegan el doble", "mismo precio, el doble de tiempo"),
    dominio.OFERTA_MITAD: ("Mitad de precio", "mismo tiempo, la mitad de plata"),
}
DIAS_CORTOS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")


def repintar(widget, **propiedades):
    """Cambia propiedades de `widget` y hace que Qt vuelva a mirar la hoja de estilos."""
    for nombre, valor in propiedades.items():
        widget.setProperty(nombre, valor)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def vaciar(capa):
    """Saca todo lo que tiene un layout. Se esconde además de borrarse: deleteLater
    recién borra al volver al bucle de Qt, y hasta ahí se vería encimado con lo nuevo."""
    while capa.count():
        hijo = capa.takeAt(0)
        if hijo.widget() is not None:
            hijo.widget().hide()
            hijo.widget().deleteLater()


def _etiqueta(texto: str, nombre: str, ajustar: bool = False) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName(nombre)
    etiqueta.setWordWrap(ajustar)
    # Texto tal cual: un nombre de oferta con "<" no se toma como HTML.
    etiqueta.setTextFormat(Qt.PlainText)
    # Las etiquetas de adentro de un botón no se quedan con el clic.
    etiqueta.setAttribute(Qt.WA_TransparentForMouseEvents)
    return etiqueta


def insignia(tipo: str, chica: bool = False, apagada: bool = False) -> QLabel:
    """La etiqueta "2x1" o "50%" con el color de la oferta (gris si `apagada`)."""
    etiqueta = _etiqueta(tipo, "insigniaOferta")
    etiqueta.setAlignment(Qt.AlignCenter)
    etiqueta.setProperty("tono", TONO_DEL_TIPO[tipo])
    etiqueta.setProperty("chica", "true" if chica else "false")
    etiqueta.setProperty("apagada", "true" if apagada else "false")
    return etiqueta


def texto_de_la_franja(dia: int, turno: str) -> str:
    """Lo que dice un cuadrito prendido: "vie 22 → sáb 06" para la Noche (cruza la
    medianoche), "dom 18 → lun 06" para el T2 del domingo y "06 a 14" para los demás."""
    inicio, fin = ofertas_repo.horario_de_la_franja(dia, turno)
    if turno == dominio.TURNO_NOCHE:
        return f"{DIAS_CORTOS[dia].lower()} {inicio} → {DIAS_CORTOS[(dia + 1) % 7].lower()} {fin}"
    return f"{inicio} a {fin}"


def resumen_corto(oferta: dict) -> str:
    """La línea de debajo del nombre en la ficha: "Vie y Sáb · Noche · hasta el 30/11"."""
    franjas = [franja for franja in ofertas_repo.franjas_de_la_semana() if franja in oferta["franjas"]]
    dias = sorted({dia for dia, _ in franjas})
    texto_dias = "Lun a Vie" if dias == [0, 1, 2, 3, 4] else ofertas_repo.y_lista(DIAS_CORTOS[dia] for dia in dias)
    turnos_vistos = []
    for dia, turno in franjas:
        nombre = ("T1" if turno == dominio.TURNO_MANANA else "T2") if dia == ofertas_repo.DOMINGO \
            else turno.capitalize()
        if nombre not in turnos_vistos:
            turnos_vistos.append(nombre)
    if oferta.get("estado") == dominio.OFERTA_TERMINADA:
        fin = oferta["terminada_fecha"].date() if oferta["terminada_fecha"] else oferta["hasta"]
        hasta = f"terminó el {fin:%d/%m}"
    else:
        hasta = f"hasta el {oferta['hasta']:%d/%m}"
    return " · ".join(parte for parte in (texto_dias, ofertas_repo.y_lista(turnos_vistos), hasta) if parte)


class FichaDeOferta(QPushButton):
    """Una oferta de la fila de arriba: la etiqueta 2x1/50%, el nombre, cuándo corre y
    su estado. Se elige con un clic (la elegida, con el borde azul)."""

    def __init__(self, oferta: dict, al_elegir):
        super().__init__()
        self.oferta = oferta
        self.setObjectName("fichaOferta")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(oferta["nombre"])
        self.setFixedHeight(54)
        terminada = oferta["estado"] == dominio.OFERTA_TERMINADA
        # El estado al lado del nombre (y no en su propia columna): así entran tres
        # fichas en la fila.
        estado = pastilla_clara(oferta["estado"].replace(" AHORA", ""), TONO_DEL_ESTADO[oferta["estado"]], chica=True)
        estado.setAttribute(Qt.WA_TransparentForMouseEvents)
        arriba = QHBoxLayout()
        arriba.setSpacing(6)
        arriba.addWidget(_etiqueta(oferta["nombre"], "nombreFicha"))
        arriba.addWidget(estado)
        arriba.addStretch()
        textos = QVBoxLayout()
        textos.setSpacing(1)
        textos.addLayout(arriba)
        textos.addWidget(_etiqueta(resumen_corto(oferta), "resumenFicha"))
        capa = QHBoxLayout(self)
        capa.setContentsMargins(10, 6, 12, 6)
        capa.setSpacing(9)
        capa.addWidget(insignia(oferta["tipo"], apagada=terminada))
        capa.addLayout(textos, 1)
        # El botón no mide su contenido: que entre todo el texto.
        self.setMinimumWidth(max(230, capa.sizeHint().width()))
        self.clicked.connect(lambda: al_elegir(self.oferta))


class CuadritoDeLaSemana(QPushButton):
    """Un día y un turno de la grilla. Prendido, del color de la oferta, con "2x1" en
    grande y su horario; abajo, en chiquito, las OTRAS ofertas que usan ese cuadrito.
    El domingo dice además cuál de sus dos turnos es (T1 o T2)."""

    def __init__(self, dia: int, turno: str, al_tocar):
        super().__init__()
        self.dia, self.turno = dia, turno
        self.setObjectName("cuadritoSemana")
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setMinimumHeight(84)
        self.setAccessibleName(f"{ofertas_repo.DIAS[dia]} {ofertas_repo.nombre_de_la_franja(dia, turno)}")
        capa = QVBoxLayout(self)
        capa.setContentsMargins(5, 5, 5, 5)
        capa.setSpacing(3)
        self.rotulo = None
        if dia == ofertas_repo.DOMINGO:
            inicio, fin = ofertas_repo.horario_de_la_franja(dia, turno)
            self.rotulo = _etiqueta(f"{'T1' if turno == dominio.TURNO_MANANA else 'T2'} · {inicio} a {fin}",
                                    "rotuloCuadrito")
            self.rotulo.setAlignment(Qt.AlignCenter)
            capa.addWidget(self.rotulo)
        capa.addStretch()
        self.tipo = _etiqueta("", "tipoCuadrito")
        self.horario = _etiqueta(texto_de_la_franja(dia, turno), "horarioCuadrito")
        self.horario.setWordWrap(True)  # "vie 22 → sáb 06" no entra en un cuadrito angosto
        for etiqueta in (self.tipo, self.horario):
            etiqueta.setAlignment(Qt.AlignCenter)
            capa.addWidget(etiqueta)
        self.capa_otras = QVBoxLayout()
        self.capa_otras.setSpacing(2)
        capa.addLayout(self.capa_otras)
        capa.addStretch()
        self.clicked.connect(lambda: al_tocar(self.dia, self.turno))

    def pintar(self, prendido: bool, tipo: str, otras: list):
        """`otras`: las demás ofertas que usan este cuadrito (sin terminar)."""
        self.setChecked(prendido)
        repintar(self, tono=TONO_DEL_TIPO[tipo])
        self.tipo.setText(tipo)
        self.tipo.setVisible(prendido)
        self.horario.setVisible(prendido)
        if self.rotulo is not None:
            repintar(self.rotulo, prendido="true" if prendido else "false")
        vaciar(self.capa_otras)
        for otra in otras:
            pausada = otra["estado"] == dominio.OFERTA_PAUSADA
            chip = _etiqueta(f"{otra['tipo']} {otra['nombre']}" + (" (pausada)" if pausada else ""),
                             "otraOfertaCuadrito", ajustar=True)
            chip.setAlignment(Qt.AlignCenter)
            chip.setProperty("tono", "gris" if pausada else TONO_DEL_TIPO[otra["tipo"]])
            self.capa_otras.addWidget(chip)


class TarjetaDeTipo(QPushButton):
    """2x1 o 50%, en grande, con qué quiere decir. La elegida, con el borde y el fondo
    del color de la oferta."""

    def __init__(self, tipo: str, al_elegir):
        super().__init__()
        self.tipo = tipo
        self.setObjectName("tarjetaTipo")
        self.setProperty("tono", TONO_DEL_TIPO[tipo])
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setAccessibleName(tipo)
        self.setFixedHeight(56)
        titulo, detalle = QUE_ES_CADA_TIPO[tipo]
        self.grande = _etiqueta(tipo, "grandeTipo")
        self.grande.setFixedWidth(64)
        self.titulo = _etiqueta(titulo, "tituloTipo")
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(self.titulo)
        textos.addWidget(_etiqueta(detalle, "detalleTipo"))
        capa = QHBoxLayout(self)
        capa.setContentsMargins(14, 6, 14, 6)
        capa.setSpacing(12)
        capa.addWidget(self.grande)
        capa.addLayout(textos, 1)
        self.clicked.connect(lambda: al_elegir(self.tipo))

    def pintar(self, elegida: bool):
        self.setChecked(elegida)
        for etiqueta in (self.grande, self.titulo):
            repintar(etiqueta, prendido="true" if elegida else "false", tono=TONO_DEL_TIPO[self.tipo])


class RenglonDeBono(QWidget):
    """Un bono para tildar: su nombre, cómo se vende siempre y, si está tildado, cómo
    queda con la oferta ("3 h · $ 6.700  →  6 h · $ 6.700"). Un bono dado de baja
    aparece solo si la oferta lo tiene, para poder sacarlo."""

    def __init__(self, equipo: str, bono, al_cambiar):
        super().__init__()
        self.equipo, self.bono = equipo, bono
        self.setObjectName("renglonBonoOferta")
        self.casilla = CasillaDibujada(False)
        self.casilla.setAccessibleName(bono["nombre"])
        self.casilla.toggled.connect(lambda marcada: al_cambiar(self.equipo, self.bono["id"], marcada))
        self.nombre = QLabel(bono["nombre"] + ("" if bono["activo"] else "  (dado de baja)"))
        self.nombre.setObjectName("nombreBonoOferta")
        self.antes = QLabel(f"{dominio.texto_minutos(bono['minutos'])} · {formato_pesos(bono['precio'])}"
                            if bono["activo"] else "ya no está a la venta")
        self.antes.setObjectName("antesBonoOferta")
        self.despues = QLabel()
        self.despues.setObjectName("despuesBonoOferta")
        capa = QHBoxLayout(self)
        capa.setContentsMargins(0, 2, 0, 2)
        capa.setSpacing(9)
        capa.addWidget(self.casilla)
        capa.addWidget(self.nombre, 1)
        capa.addWidget(self.antes)
        capa.addWidget(self.despues)

    def mousePressEvent(self, evento):
        # Un clic en el nombre tilda igual que en la casilla.
        if self.casilla.isEnabled():
            self.casilla.toggle()
        super().mousePressEvent(evento)

    def pintar(self, marcado: bool, tipo: str, editable: bool):
        self.casilla.blockSignals(True)
        self.casilla.setChecked(marcado)
        self.casilla.blockSignals(False)
        self.casilla.setEnabled(editable)
        repintar(self.nombre, marcado="true" if marcado else "false")
        con_oferta = marcado and bool(self.bono["activo"])
        self.despues.setVisible(con_oferta)
        if con_oferta:
            minutos, precio = ofertas_repo.con_oferta(tipo, self.bono["minutos"], self.bono["precio"])
            self.despues.setText(f"→  {dominio.texto_minutos(minutos)} · {formato_pesos(precio)}")
            repintar(self.despues, tono=TONO_DEL_TIPO[tipo])


def avisar_choque(padre, mensaje: str):
    """El aviso de cuando lo que se quiere guardar toca un bono y un turno que ya tiene
    otra oferta (ofertas_repo.ChocaConOtraOferta): arriba, en rojo, qué oferta lo tiene;
    abajo, qué hacer (maqueta X de PROPUESTA_OFERTAS)."""
    choque, que_hacer = (mensaje.split("\n\n", 1) + [""])[:2]
    dialogo = QDialog(padre)
    dialogo.setWindowTitle("No se puede guardar")
    dialogo.resize(620, 300)
    cabecera = cabecera_oscura("", "No se puede guardar",
                               "Dos ofertas no pueden tocar el mismo bono en el mismo turno")
    cabecera.icono.setPixmap(pixmap_de("prohibido", 28, "#FF9AA2", 2))
    rojo = QLabel(choque)
    rojo.setObjectName("avisoChoqueOferta")
    rojo.setTextFormat(Qt.PlainText)  # trae los nombres de las ofertas tal cual
    rojo.setWordWrap(True)
    panel, capa_panel = panel_blanco()
    explicacion = QLabel(que_hacer)
    explicacion.setObjectName("textoOferta")
    explicacion.setTextFormat(Qt.PlainText)
    explicacion.setWordWrap(True)
    capa_panel.addWidget(explicacion)
    capa = QVBoxLayout(dialogo)
    capa.setContentsMargins(16, 16, 16, 14)
    capa.setSpacing(12)
    capa.addWidget(cabecera)
    capa.addWidget(rojo)
    capa.addWidget(panel)
    capa.addStretch()
    fila = QHBoxLayout()
    fila.addStretch()
    fila.addWidget(tecla("ENTENDIDO", dialogo.accept, "teclaAzul"))
    capa.addLayout(fila)
    sin_boton_por_defecto(dialogo)
    dialogo.exec()
