"""
pcs_lista_de_bonos.py
=====================
Las listas de bonos del panel de la PC (`ListaDeBonos`, salió de pcs_detalle.py el
2026-11-13 al sumarle las ofertas) y lo que muestran las ofertas que corren, con la
maqueta P1 que eligió el dueño (PROPUESTA_OFERTAS): el bono con oferta lleva la
etiqueta 2x1 / 50% adentro, a la izquierda, con el tiempo y el precio que se van a
cobrar (`boton_de_bono`), y arriba de las listas un cartel naranja (o violeta, el 50%)
dice qué oferta corre y hasta qué hora (`cartel_de_ofertas`). Los colores, en
ui/hoja_de_estilos.py ("Ofertas").
"""

import html
from datetime import time, timedelta

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QButtonGroup, QHBoxLayout, QLabel, QPushButton, QVBoxLayout

import dominio
import turnos
from control_pcs.ui.ofertas_piezas import TONO_DEL_TIPO, insignia, repintar
from ui.utils import formato_pesos

# Cómo se dice en el cartel de qué equipo son los bonos ("en 2 bonos de PC").
_DE_QUE_EQUIPO = {
    dominio.EQUIPO_RESERVA_PC: "de PC",
    dominio.EQUIPO_RESERVA_PCSTREAM: f"de {dominio.NOMBRE_PCSTREAM}",
    dominio.EQUIPO_RESERVA_PLAYSTATION: "de la PlayStation 5",
}


def boton_de_bono(bono) -> QPushButton:
    """El botón de un bono de la lista. Sin oferta, "1 Hora — $ 5.000" como siempre.
    Con oferta (`bono["oferta"]`, de ofertas_repo.con_las_ofertas), lo que se cobra
    con ella ("Promo 3hs — 6 h · $ 6.700"), la etiqueta 2x1 / 50% a la izquierda y el
    borde del color de la oferta; el precio de siempre, en el cartelito del mouse."""
    oferta = bono.get("oferta") if hasattr(bono, "get") else None
    if oferta is None:
        return QPushButton(f"{bono['nombre']} — {formato_pesos(bono['precio'])}")
    boton = QPushButton(f"{bono['nombre']} — {dominio.texto_minutos(bono['minutos'])} · "
                        f"{formato_pesos(bono['precio'])}")
    boton.setProperty("oferta", TONO_DEL_TIPO[oferta["tipo"]])
    boton.setToolTip(f"{oferta['tipo']} «{oferta['nombre']}». Sin la oferta: "
                     f"{dominio.texto_minutos(bono['minutos_sin_oferta'])} por "
                     f"{formato_pesos(bono['precio_sin_oferta'])}.")
    capa = QHBoxLayout(boton)
    capa.setContentsMargins(5, 0, 0, 0)
    capa.addWidget(insignia(oferta["tipo"], chica=True), 0, Qt.AlignVCenter)
    capa.addStretch()
    return boton


def _hasta(fin, ahora) -> str:
    """" HASTA LAS 22:00" si termina hoy, o mañana a la hora del cambio de día (la
    Noche: "HASTA LAS 06:00", como se dice en el local); " HASTA MAÑANA A LAS 14:00"
    si termina mañana más tarde (si no, a las 15:00 se leería como que ya terminó);
    si no, con la fecha."""
    if fin is None:
        return ""
    manana = ahora.date() + timedelta(days=1)
    if fin.date() == ahora.date() or (fin.date() == manana and fin.time() <= time(turnos.HORA_CAMBIO_DE_DIA)):
        return f" HASTA LAS {fin:%H:%M}"
    if fin.date() == manana:
        return f" HASTA MAÑANA A LAS {fin:%H:%M}"
    return f" HASTA EL {fin:%d/%m} A LAS {fin:%H:%M}"


def cartel_de_ofertas(ofertas: list, equipo, ahora, a_la_venta=None):
    """
    El cartel de arriba de los bonos: (texto, tipo de la primera oferta) con las
    ofertas que corren (las de ofertas_repo.activas) en los bonos de `equipo` (o en
    todos, con None: no hay nada elegido), o None si no hay ninguna. "2x1 HASTA LAS
    06:00 / «Noche de finde» en 2 bonos de PC", una oferta debajo de la otra.
    Con `a_la_venta` ({(equipo, bono_id)} de los botones de las listas) cuenta solo
    esos: un bono dado de baja después de armar la oferta no tiene botón, y el
    cartel no puede prometer una oferta que no se cobra.
    """
    renglones, primera = [], None
    for oferta in sorted(ofertas, key=lambda oferta: oferta["id"]):
        cuantos = sum(1 for de_que, bono_id in oferta["bonos"]
                      if (equipo is None or de_que == equipo)
                      and (a_la_venta is None or (de_que, bono_id) in a_la_venta))
        if not cuantos:
            continue
        primera = primera or oferta["tipo"]
        bonos = f"{cuantos} bono{'' if cuantos == 1 else 's'}"
        if equipo is not None:
            bonos += f" {_DE_QUE_EQUIPO[equipo]}"
        renglones.append(f"<b>{oferta['tipo']}{_hasta(oferta.get('hasta_el_fin'), ahora)}</b><br>"
                         f"«{html.escape(oferta['nombre'])}» en {bonos}")
    if not renglones:
        return None
    return "<br>".join(renglones), primera


def poner_cartel_de_ofertas(etiqueta, ofertas: list, equipo, ahora, a_la_venta):
    """Pone el cartel de `cartel_de_ofertas` en `etiqueta` (el #cartelOferta del
    panel), naranja el 2x1 y violeta el 50%, o la esconde si no corre ninguna."""
    cartel = cartel_de_ofertas(ofertas, equipo, ahora, a_la_venta)
    etiqueta.setVisible(cartel is not None)
    if cartel is not None:
        etiqueta.setText(cartel[0])
        repintar(etiqueta, tono=TONO_DEL_TIPO[cartel[1]])


class ListaDeBonos:
    """
    Una lista de bonos como botones (uno elegido a la vez) con su título. El
    panel tiene TRES, separadas y una debajo de la otra: la de los bonos de PC,
    la de la PlayStation 5 y la de PCSTREAM (catálogos distintos, ver
    playstation_repo y pcstream_repo). Nunca comparten botones ni grupo, así que
    lo que está tildado en una no puede terminar usándose para otra.
    """

    def __init__(self, titulo: str, aviso_sin_bonos: str, padre):
        self.etiqueta = QLabel(titulo)
        self.aviso_sin_bonos = QLabel(aviso_sin_bonos)
        self.aviso_sin_bonos.setWordWrap(True)
        self.aviso_sin_bonos.setObjectName("avisoSinBonos")  # color en ui/hoja_de_estilos.py
        self.layout = QVBoxLayout()
        self.layout.setSpacing(6)  # los bonos como botones separados, no pegados en un bloque
        self.grupo = QButtonGroup(padre)
        self.grupo.setExclusive(True)
        self.grupo.idClicked.connect(self._recordar)
        self.bonos = []
        self._elegido_id = None
        self._habilitada = False

    def _recordar(self, bono_id: int):
        self._elegido_id = bono_id

    def cargar(self, bonos, habilitada: bool):
        """Vuelve a armar los botones con `bonos` (filas de un catálogo, o lo que
        devuelve ofertas_repo.con_las_ofertas: con el precio y los minutos de la oferta
        que corre). Si el bono que estaba elegido sigue en la lista queda elegido -- la
        grilla se refresca sola cada 5 segundos y esto se llama cada vez: sin esto, el
        operador que tildó "3 horas" lo vería volver al primero justo antes de
        cobrar."""
        while self.layout.count():
            hijo = self.layout.takeAt(0)
            if hijo.widget():
                hijo.widget().hide()  # deleteLater lo borra después: que no se vea encimado
                hijo.widget().deleteLater()
        for boton in self.grupo.buttons():
            self.grupo.removeButton(boton)

        self.bonos = list(bonos)
        ids = [bono["id"] for bono in self.bonos]
        elegido = self._elegido_id if self._elegido_id in ids else (ids[0] if ids else None)
        for bono in self.bonos:
            boton = boton_de_bono(bono)
            boton.setCheckable(True)
            boton.setChecked(bono["id"] == elegido)
            # Se crean después de _armar_interfaz, así que no los alcanzó
            # sin_boton_por_defecto: hay que hacerlo uno por uno.
            boton.setAutoDefault(False)
            boton.setDefault(False)
            self.grupo.addButton(boton, bono["id"])
            self.layout.addWidget(boton)
        self._elegido_id = elegido
        self.aviso_sin_bonos.setVisible(not self.bonos)
        self.habilitar(habilitada)

    def habilitar(self, habilitada: bool):
        """Habilita o deshabilita TODA la lista (título incluido, que se ve
        apagado): una lista deshabilitada no se puede tocar ni cobrar."""
        self._habilitada = habilitada
        self.etiqueta.setEnabled(habilitada)
        for boton in self.grupo.buttons():
            boton.setEnabled(habilitada)

    @property
    def habilitada(self) -> bool:
        return self._habilitada

    def bono_elegido(self):
        """La fila del bono tildado, o None si la lista está vacía."""
        bono_id = self.grupo.checkedId()
        return next((bono for bono in self.bonos if bono["id"] == bono_id), None)
