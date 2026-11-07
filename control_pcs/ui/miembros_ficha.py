"""
miembros_ficha.py
=================
Las piezas de la ventana de Administración de Miembros con el diseño "ficha del socio" que
eligió el dueño el 2026-10-29 (maqueta B, entre tres): a la izquierda la lista de socios, con
su círculo de iniciales, su saldo y hace cuánto vino (`DelegadoDeSocios`), y a la derecha la
ficha del que está elegido (`FichaDelSocio`): saldo, última carga, última visita, datos de
contacto, los botones que actúan sobre ESE socio y sus últimas cargas. Arriba de la lista, los
filtros en una pista de botones (`Segmentos`).

Con el socio jugando (pedido del dueño, 2026-11-07: la PC decía 6h 33m y la ficha 32h 18m), el
saldo de la lista y de la ficha es el TOTAL: lo guardado más lo que le queda en la PC. La ficha
dice de dónde sale cada parte y, en un cartel celeste, hasta cuándo juega en la PC y si una
reserva la corta (tiempo_del_socio_repo).

Acá solo se dibuja: de dónde salen los datos (socios, visitas, cargas) lo decide
`miembros_window.MiembrosWindow`, que le pasa a la ficha lo que tiene que mostrar. Los colores
de la ficha están en ui/hoja_de_estilos.py, por objectName.
"""

from datetime import date, datetime
from functools import lru_cache

from PySide6.QtCore import QPointF, QRect, QRectF, QSize, Qt, Signal
from PySide6.QtGui import QColor, QFont, QFontMetrics, QPainter
from PySide6.QtWidgets import (
    QAbstractItemView, QButtonGroup, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton,
    QStackedLayout, QStyle, QStyledItemDelegate, QTableWidgetItem, QVBoxLayout, QWidget,
)

import dominio
from control_pcs.repositories import miembros_repo, reservas_horario_repo, tiempo_del_socio_repo
from control_pcs.ui.dibujos_de_ventana import pixmap_de_avatar, poner_icono
from ui.piezas_ventana import (
    TONO_AZUL, TONO_CELESTE, TONO_GRIS, TONO_ROJO, TONO_VERDE, pastilla_clara, tecla, titulo_de_seccion,
)
from ui.utils import aplicar_clase, crear_tabla, formato_fecha_hora, formato_pesos, formato_tiempo

# El dato de cada renglón de la lista: {"miembro": socio, "dias": hace cuántos días no viene}, y
# en Miembros también "jugando" (lo de tiempo_del_socio_repo.socios_jugando para él, o None) y
# "segundos" (su tiempo total). ORDENAR SALDOS no los manda: ahí se ve solo lo guardado.
ROL_DATOS = Qt.UserRole + 1
# "Hace N días" en naranja pasados dominio.DIAS_SIN_VENIR_AVISO días.
COLOR_NO_VIENE = QColor("#D35400")
# "Jugando · PC15X" en la lista: el celeste del cartel de la ficha.
COLOR_JUGANDO = QColor("#1185B5")
CARGAS_EN_LA_FICHA = 4


def texto_no_viene(dias) -> str:
    """Lo que dice "Última visita" (de ultima_visita_repo.dias_sin_venir)."""
    if dias is None:
        return "Nunca vino"
    if dias == 0:
        return "Hoy"
    if dias == 1:
        return "Ayer"
    if dias < 60:
        return f"{dias} días"
    return f"{dias // 30} meses"


def texto_de_la_lista(dias) -> str:
    """Lo chiquito de abajo del saldo en la lista: "Vino hoy", "Hace 9 días", "Nunca vino"."""
    if dias is None:
        return "Nunca vino"
    if dias <= 1:
        return "Vino " + texto_no_viene(dias).lower()
    return "Hace " + texto_no_viene(dias)


def detalle_de_la_visita(visita) -> str:
    """Lo que se ve al pasar el mouse por un socio de la lista: cuándo y qué hizo."""
    if visita is None:
        return "Nunca entró a una PC con su usuario ni se le cargó saldo."
    partes = []
    if visita["pc"] is not None:
        desde = visita["pc_desde"].strftime("%d/%m %H:%M")
        partes.append(f"Está usando la {visita['pc']} desde el {desde}" if visita["jugando"]
                      else f"Entró a la {visita['pc']} el {desde}")
    if visita["carga"] is not None:
        partes.append(f"Última carga {visita['carga'].strftime('%d/%m %H:%M')}")
    return " · ".join(partes)


def texto_de_la_ultima_pc(visita) -> str:
    """Lo de abajo de "Última visita": en qué PC estuvo y desde cuándo."""
    if visita is None or visita["pc"] is None:
        return "Nunca entró a una PC con su usuario"
    desde = visita["pc_desde"].strftime("%d/%m %H:%M")
    return f"Está usando la {visita['pc']} desde el {desde}" if visita["jugando"] else \
        f"Entró a la {visita['pc']} el {desde}"


def texto_de_la_fecha(fecha, hoy: date = None) -> str:
    """"Hoy 18:42", "Ayer 20:10" o "26/10 20:10" para una fecha con hora de la base."""
    momento = datetime.fromisoformat(str(fecha))
    dia = (hoy or date.today()) - momento.date()
    if dia.days == 0:
        return f"Hoy {momento:%H:%M}"
    if dia.days == 1:
        return f"Ayer {momento:%H:%M}"
    return f"{momento:%d/%m} {momento:%H:%M}"


def texto_de_la_lista_jugando(jugando) -> str:
    """Lo chiquito de abajo del saldo en la lista con el socio jugando: "Jugando · PC15X"."""
    pcs = jugando["pcs"]
    return f"Jugando · {pcs[0]['estacion']}" if len(pcs) == 1 else f"Jugando · {len(pcs)} PCs"


def _en_las_pcs(jugando) -> str:
    """"en la PC15X" o "en 2 PCs"."""
    pcs = jugando["pcs"]
    return f"en la {pcs[0]['estacion']}" if len(pcs) == 1 else f"en {len(pcs)} PCs"


def texto_de_las_partes(jugando, minutos_guardados: int) -> str:
    """Lo de abajo del SALDO TOTAL con el socio jugando: de dónde sale cada parte
    ("32h 18m guardado + 6h 33m en la PC15X")."""
    en_pcs = f"{formato_tiempo(jugando['segundos_en_pcs'])} {_en_las_pcs(jugando)}"
    if minutos_guardados <= 0:
        return f"todo {_en_las_pcs(jugando)}"
    return f"{formato_tiempo(minutos_guardados * 60)} guardado + {en_pcs}"


def _hasta_la_reserva(pc, ahora: datetime) -> str:
    reserva = pc["hasta_la_reserva"]
    return f"hasta {reservas_horario_repo.texto_de_la_hora(reserva['inicio'], ahora)}"


def texto_de_lo_que_juega(jugando, minutos_guardados: int, ahora: datetime = None) -> str:
    """
    El cartel celeste de la ficha con el socio jugando: cuánto le queda en la PC, hasta qué
    hora si la PC está reservada para otro (la PC no le da más que eso: lo demás queda
    guardado) y que lo guardado no se descuenta mientras juega. Es la explicación de por qué
    la PC y la ficha muestran números distintos.
    """
    ahora = ahora or datetime.now()
    pcs = jugando["pcs"]
    if len(pcs) == 1:
        pc = pcs[0]
        texto = f"Está jugando en la {pc['estacion']}: le quedan {formato_tiempo(pc['segundos'])} en la PC"
        if pc["hasta_la_reserva"] is not None:
            texto += (f", {_hasta_la_reserva(pc, ahora)}, porque la {pc['estacion']} está reservada para "
                      f"{pc['hasta_la_reserva']['cliente']}")
        texto += "."
    else:
        partes = [
            f"{pc['estacion']} ({formato_tiempo(pc['segundos'])}"
            + (f", {_hasta_la_reserva(pc, ahora)} por una reserva" if pc["hasta_la_reserva"] is not None else "")
            + ")"
            for pc in pcs
        ]
        texto = f"Está jugando en {len(pcs)} PCs a la vez: {', '.join(partes[:-1])} y {partes[-1]}."
    if minutos_guardados > 0:
        texto += (f"\nLo guardado ({formato_tiempo(minutos_guardados * 60)}) no se descuenta mientras juega: "
                  "sigue en su cuenta.")
        if any(pc["hasta_la_reserva"] is not None for pc in pcs):
            texto += " Cuando la PC se bloquee por la reserva, puede seguir en otra PC."
    return texto


def texto_de_lo_sumado(sumado, ahora: datetime = None) -> str:
    """
    El cartel de después de cargarle (o sumarle, en ORDENAR SALDOS) tiempo a un socio que
    está jugando: cuánto pasó a su PC y, si una reserva no dejó pasar todo, cuánto le quedó
    guardado y por qué. `sumado` es lo de miembros_repo._sumar_carga_a_la_sesion. Antes decía
    solo lo que pasó a la PC: a Oscar le cargaron 13 h y el cartel dijo "8h 40m".
    """
    texto = (f"Se le sumaron {formato_tiempo(sumado['minutos'] * 60)} a su sesión en {sumado['estacion']}: "
             "le aparecen en la PC en unos segundos.")
    # Con .get: una copia abierta desde otra PC puede hablar con un mostrador sin actualizar.
    guardado, hora = sumado.get("guardado") or 0, sumado.get("hasta_la_reserva")
    if guardado > 0:
        motivo = ""
        if hora is not None:
            cuando = reservas_horario_repo.texto_de_la_hora(hora, ahora or datetime.now())
            motivo = f": la {sumado['estacion']} está reservada {cuando} y la PC le da tiempo solo hasta esa hora"
        texto += (f"\n\nLas otras {formato_tiempo(guardado * 60)} le quedaron guardadas en su cuenta{motivo}. "
                  "Las puede usar en otra PC o la próxima vez.")
    return texto


def color_del_saldo(minutos: int) -> str:
    """Apagado en cero, ámbar con menos de una hora y normal si no."""
    if minutos <= 0:
        return "#A7ADB8"
    if minutos < 60:
        return "#B26A00"
    return "#1B2233"


@lru_cache(maxsize=512)
def _avatar(usuario: str, lado: int):
    return pixmap_de_avatar(usuario, lado)


# ---------------------------------------------------------------- la lista de socios
class DelegadoDeSocios(QStyledItemDelegate):
    """Dibuja cada socio de la lista: el círculo con sus iniciales, el usuario y el nombre a
    la izquierda, el saldo y hace cuánto vino a la derecha. El socio elegido va con fondo
    celeste y una rayita azul al costado. Lee el socio de `ROL_DATOS`."""

    ALTO = 56
    _LADO_AVATAR = 36
    _ANCHO_DERECHA = 96

    def sizeHint(self, _opcion, _indice):
        return QSize(0, self.ALTO)

    def paint(self, pintor, opcion, indice):
        datos = indice.data(ROL_DATOS)
        if not datos:
            return super().paint(pintor, opcion, indice)
        miembro, dias = datos["miembro"], datos["dias"]
        jugando = datos.get("jugando")
        segundos = datos.get("segundos", miembro["saldo_minutos"] * 60)
        zona = opcion.rect
        pintor.save()
        pintor.setRenderHint(QPainter.Antialiasing)
        if opcion.state & QStyle.State_Selected:
            pintor.fillRect(zona, QColor("#EAF1FE"))
            pintor.fillRect(QRect(zona.left(), zona.top(), 3, zona.height()), QColor("#2F6FED"))
        elif opcion.state & QStyle.State_MouseOver:
            pintor.fillRect(zona, QColor("#F6F8FC"))
        pintor.setPen(QColor("#EEF1F6"))
        pintor.drawLine(zona.left(), zona.bottom(), zona.right(), zona.bottom())

        x = zona.left() + 14
        pintor.drawPixmap(QPointF(x, zona.top() + (zona.height() - self._LADO_AVATAR) / 2),
                          _avatar(miembro["usuario"], self._LADO_AVATAR))
        izquierda = x + self._LADO_AVATAR + 10
        derecha = zona.right() - 14
        ancho_izquierda = int(derecha - self._ANCHO_DERECHA - izquierda)
        activo = bool(miembro["activo"])

        letra = QFont(opcion.font)
        letra.setPixelSize(14)
        letra.setBold(True)
        pintor.setFont(letra)
        pintor.setPen(QColor("#1B2233" if activo else "#8A94A6"))
        pintor.drawText(QRectF(izquierda, zona.top() + 9, ancho_izquierda, 20), Qt.AlignLeft | Qt.AlignVCenter,
                        QFontMetrics(letra).elidedText(miembro["usuario"], Qt.ElideRight, ancho_izquierda))

        letra.setPixelSize(12)
        letra.setBold(False)
        pintor.setFont(letra)
        pintor.setPen(QColor("#6B7585"))
        pintor.drawText(QRectF(izquierda, zona.top() + 29, ancho_izquierda, 18), Qt.AlignLeft | Qt.AlignVCenter,
                        QFontMetrics(letra).elidedText(miembro["nombre"] or "", Qt.ElideRight, ancho_izquierda))

        columna = QRectF(derecha - self._ANCHO_DERECHA, 0, self._ANCHO_DERECHA, 0)
        letra.setPixelSize(14)
        letra.setBold(True)
        pintor.setFont(letra)
        pintor.setPen(QColor(color_del_saldo(segundos // 60) if activo else "#A7ADB8"))
        pintor.drawText(QRectF(columna.left(), zona.top() + 9, columna.width(), 20), Qt.AlignRight | Qt.AlignVCenter,
                        formato_tiempo(segundos))

        letra.setPixelSize(11)
        letra.setBold(False)
        pintor.setFont(letra)
        if not activo:
            texto, color = "Inactivo", QColor("#8A94A6")
        elif jugando:
            texto, color = texto_de_la_lista_jugando(jugando), COLOR_JUGANDO
        else:
            texto = texto_de_la_lista(dias)
            color = COLOR_NO_VIENE if (dias is not None and dias > dominio.DIAS_SIN_VENIR_AVISO) else QColor("#8A94A6")
        pintor.setPen(color)
        pintor.drawText(QRectF(columna.left(), zona.top() + 29, columna.width(), 18), Qt.AlignRight | Qt.AlignVCenter,
                        texto)
        pintor.restore()


class Segmentos(QFrame):
    """Los filtros de arriba de la lista: botones en una pista gris, el elegido oscuro (el
    mismo diseño que "Todas / Las que esperan" de Reservas). `opciones`: [(clave, texto)]."""

    cambio = Signal(str)

    def __init__(self, opciones, parent=None):
        super().__init__(parent)
        self.setObjectName("pistaSegmentos")
        capa = QHBoxLayout(self)
        capa.setContentsMargins(3, 3, 3, 3)
        capa.setSpacing(2)
        self._grupo = QButtonGroup(self)
        self._grupo.setExclusive(True)
        self._botones = {}
        for clave, texto in opciones:
            boton = QPushButton(texto)
            aplicar_clase(boton, "segmento")
            boton.setCheckable(True)
            boton.setFocusPolicy(Qt.NoFocus)
            boton.clicked.connect(lambda _=False, c=clave: self.cambio.emit(c))
            self._grupo.addButton(boton)
            capa.addWidget(boton, 1)
            self._botones[clave] = boton
        next(iter(self._botones.values())).setChecked(True)

    def elegido(self) -> str:
        return next(clave for clave, boton in self._botones.items() if boton.isChecked())

    def elegir(self, clave: str):
        self._botones[clave].click()

    def poner_texto(self, clave: str, texto: str):
        self._botones[clave].setText(texto)


# ---------------------------------------------------------------- la ficha del socio
def _poner(etiqueta: QLabel, texto: str, **propiedades):
    """Cambia el texto de una etiqueta y sus propiedades de estilo (vacio, falta)."""
    etiqueta.setText(texto)
    for nombre, valor in propiedades.items():
        etiqueta.setProperty(nombre, "true" if valor else "false")
    etiqueta.style().unpolish(etiqueta)
    etiqueta.style().polish(etiqueta)


class _TextoQueSeParte(QLabel):
    """Un texto que se parte en renglones y nunca queda cortado: Qt le da el alto que pide
    para su ancho de ANTES (el cartel aparece al elegir un socio y la ficha ya estaba
    armada), y el último renglón no se veía. Acá se pide de nuevo cada vez que cambia el
    ancho o el texto."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWordWrap(True)

    def poner_texto(self, texto: str):
        self.setText(texto)
        self._ajustar_alto()

    def resizeEvent(self, evento):
        super().resizeEvent(evento)
        self._ajustar_alto()

    def _ajustar_alto(self):
        alto = self.heightForWidth(self.width())
        if alto > 0 and alto != self.minimumHeight():
            self.setMinimumHeight(alto)


def _bloque(titulo: str, destacado: bool = False):
    """Un recuadro con un título chico, un valor grande y una línea que lo aclara:
    (el recuadro, la etiqueta del título, la del valor, la de la aclaración)."""
    marco = QFrame()
    marco.setObjectName("fichaBloque")
    marco.setProperty("destacado", "true" if destacado else "false")
    capa = QVBoxLayout(marco)
    capa.setContentsMargins(16, 12, 16, 12)
    capa.setSpacing(0)
    etiqueta_titulo = QLabel(titulo)
    etiqueta_titulo.setObjectName("fichaTituloBloque")
    valor = QLabel()
    valor.setObjectName("fichaValorBloque")
    valor.setProperty("destacado", "true" if destacado else "false")
    aclaracion = QLabel()
    aclaracion.setObjectName("fichaSubBloque")
    capa.addWidget(etiqueta_titulo)
    capa.addWidget(valor)
    capa.addWidget(aclaracion)
    return marco, etiqueta_titulo, valor, aclaracion


class FichaDelSocio(QFrame):
    """El panel de la derecha: todo lo de un socio y los botones que actúan sobre él. Se llena
    con `mostrar(...)`; sin socios, con `vaciar()`, dice que no hay nada para mostrar."""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setObjectName("panelBlanco")
        self._paginas = QStackedLayout(self)
        self._paginas.setContentsMargins(0, 0, 0, 0)

        vacia = QLabel("No hay socios para mostrar.")
        vacia.setObjectName("fichaVacia")
        vacia.setAlignment(Qt.AlignCenter)
        self._paginas.addWidget(vacia)

        pagina = QWidget()
        capa = QVBoxLayout(pagina)
        capa.setContentsMargins(24, 22, 24, 20)
        capa.setSpacing(14)

        # Arriba: quién es.
        arriba = QHBoxLayout()
        arriba.setSpacing(16)
        self.avatar = QLabel()
        self.avatar.setFixedSize(68, 68)
        arriba.addWidget(self.avatar, 0, Qt.AlignTop)
        quien = QVBoxLayout()
        quien.setSpacing(2)
        self.etiqueta_nombre = QLabel()
        self.etiqueta_nombre.setObjectName("fichaNombre")
        self.etiqueta_usuario = QLabel()
        self.etiqueta_usuario.setObjectName("fichaUsuario")
        self.fila_pastillas = QHBoxLayout()
        self.fila_pastillas.setSpacing(6)
        quien.addWidget(self.etiqueta_nombre)
        quien.addWidget(self.etiqueta_usuario)
        quien.addSpacing(4)
        quien.addLayout(self.fila_pastillas)
        arriba.addLayout(quien, 1)
        self.boton_modificar = tecla("Modificar datos")
        poner_icono(self.boton_modificar, "lapiz")
        arriba.addWidget(self.boton_modificar, 0, Qt.AlignTop)
        capa.addLayout(arriba)

        # Saldo, última carga y última visita.
        tres = QHBoxLayout()
        tres.setSpacing(12)
        bloque_saldo, self.titulo_saldo, self.valor_saldo, self.aclaracion_saldo = _bloque("SALDO", destacado=True)
        bloque_carga, _, self.valor_carga, self.aclaracion_carga = _bloque("ÚLTIMA CARGA")
        bloque_visita, _, self.valor_visita, self.aclaracion_visita = _bloque("ÚLTIMA VISITA")
        tres.addWidget(bloque_saldo, 5)
        tres.addWidget(bloque_carga, 4)
        tres.addWidget(bloque_visita, 4)
        capa.addLayout(tres)

        # Con el socio jugando: hasta cuándo en la PC y por qué lo guardado no baja. El texto
        # va adentro de un marco con márgenes de layout, no con "padding" en la hoja de
        # estilos: Qt no cuenta ese padding al calcular el alto de un texto que se parte en
        # renglones.
        self.cartel_jugando = QFrame()
        self.cartel_jugando.setObjectName("fichaJugando")
        capa_cartel = QVBoxLayout(self.cartel_jugando)
        capa_cartel.setContentsMargins(16, 10, 14, 10)
        self.texto_jugando = _TextoQueSeParte()
        self.texto_jugando.setObjectName("fichaJugandoTexto")
        capa_cartel.addWidget(self.texto_jugando)
        self.cartel_jugando.setVisible(False)
        capa.addWidget(self.cartel_jugando)

        # Datos de contacto.
        capa.addWidget(titulo_de_seccion("Datos de contacto"))
        datos = QGridLayout()
        datos.setHorizontalSpacing(30)
        datos.setVerticalSpacing(8)
        self.datos = {}
        for lugar, (clave, titulo) in enumerate((("dni", "DNI"), ("celular", "Celular"),
                                                 ("whatsapp", "WhatsApp"), ("email", "Email"))):
            etiqueta_dato = QLabel(titulo)
            etiqueta_dato.setObjectName("fichaEtiquetaDato")
            valor = QLabel()
            valor.setObjectName("fichaValorDato")
            self.datos[clave] = valor
            columna = QVBoxLayout()
            columna.setSpacing(0)
            columna.addWidget(etiqueta_dato)
            columna.addWidget(valor)
            datos.addLayout(columna, lugar // 2, lugar % 2)
        capa.addLayout(datos)

        # Lo que se puede hacer con este socio.
        acciones = QHBoxLayout()
        acciones.setSpacing(10)
        self.boton_cargar_saldo = tecla("Cargar Saldo", clase="teclaAzul")
        poner_icono(self.boton_cargar_saldo, "moneda", 18, "#FFFFFF")
        self.boton_cargar_saldo.setStyleSheet("padding: 11px 26px; font-size: 14px;")
        self.boton_historial = tecla("Historial de este socio")
        poner_icono(self.boton_historial, "reloj")
        self.boton_desactivar = tecla("Desactivar", clase="teclaRoja")
        poner_icono(self.boton_desactivar, "prohibido", 16, "#A6323C")
        acciones.addWidget(self.boton_cargar_saldo)
        acciones.addWidget(self.boton_historial)
        acciones.addStretch()
        acciones.addWidget(self.boton_desactivar)
        capa.addLayout(acciones)

        # Sus últimas cargas.
        linea = QFrame()
        linea.setFixedHeight(1)
        linea.setStyleSheet("background-color: #E4E7EC; border: none;")
        capa.addWidget(linea)
        capa.addWidget(titulo_de_seccion("Últimas cargas de este socio"))
        self.tabla_cargas = crear_tabla(["Fecha y hora", "Tiempo", "Plata", "Pago", "Operador"], estirar=0)
        self.tabla_cargas.setSelectionMode(QAbstractItemView.NoSelection)
        self.tabla_cargas.setShowGrid(False)
        self.tabla_cargas.setFocusPolicy(Qt.NoFocus)
        self.tabla_cargas.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        self.tabla_cargas.verticalHeader().setDefaultSectionSize(34)
        for columna, ancho in ((1, 90), (2, 100), (3, 150), (4, 110)):
            self.tabla_cargas.setColumnWidth(columna, ancho)
        self.sin_cargas = QLabel("Todavía no se le cargó saldo (en el último año).")
        self.sin_cargas.setObjectName("fichaVacia")
        capa.addWidget(self.tabla_cargas)
        capa.addWidget(self.sin_cargas)
        capa.addStretch()
        self._paginas.addWidget(pagina)

    def vaciar(self):
        self._paginas.setCurrentIndex(0)

    def mostrar(self, miembro, dias, visita, cargas, jugando=None):
        """`miembro`: el socio; `dias`: hace cuántos días no viene (None = nunca vino);
        `visita`: lo de ultima_visita_repo.ultimas_visitas() para él; `cargas`: sus cargas de
        historial_cargas_repo.listar_cargas, de la más nueva a la más vieja; `jugando`: lo de
        tiempo_del_socio_repo.socios_jugando() para él, o None si no está jugando."""
        self._paginas.setCurrentIndex(1)
        usuario = miembro["usuario"]
        self.avatar.setPixmap(_avatar(usuario, 68))
        self.etiqueta_nombre.setText(miembro["nombre"] or usuario)
        self.etiqueta_usuario.setText(f"Usuario: {usuario}")
        self._poner_las_pastillas(miembro, jugando)
        self.mostrar_el_saldo(miembro, jugando)
        vigentes = [carga for carga in cargas if not carga["anulada"]]
        if vigentes:
            ultima = vigentes[0]
            self.valor_carga.setText(texto_de_la_fecha(ultima["fecha"]))
            self.aclaracion_carga.setText(" · ".join(
                parte for parte in (formato_pesos(ultima["monto"]), ultima["medio"], ultima["operador"]) if parte))
        else:
            self.valor_carga.setText("Sin cargas")
            self.aclaracion_carga.setText("en el último año")
        self.valor_visita.setText(texto_no_viene(dias))
        self.aclaracion_visita.setText(texto_de_la_ultima_pc(visita))

        falta_dni = not miembros_repo.tiene_dni(miembro)
        _poner(self.datos["dni"], "Falta DNI" if falta_dni else miembro["dni"], falta=falta_dni, vacio=False)
        for clave, valor in (("celular", miembro["telefono"]), ("whatsapp", miembro["whatsapp"]),
                             ("email", miembro["email"])):
            _poner(self.datos[clave], valor or "(sin cargar)", vacio=not valor, falta=False)
        self._llenar_las_cargas(cargas[:CARGAS_EN_LA_FICHA])

    def mostrar_el_saldo(self, miembro, jugando=None):
        """El recuadro SALDO y el cartel celeste. Sin jugar, el saldo es lo que tiene. Jugando,
        el TOTAL (lo guardado más lo que le queda en la PC), de dónde sale cada parte y el
        cartel con hasta cuándo juega en la PC. MiembrosWindow lo vuelve a llamar cada tanto,
        para que lo de la PC no quede viejo con la ventana abierta."""
        minutos = miembro["saldo_minutos"]
        self.valor_saldo.setText(formato_tiempo(tiempo_del_socio_repo.segundos_totales(miembro, jugando)))
        if jugando:
            self.titulo_saldo.setText("SALDO TOTAL")
            self.aclaracion_saldo.setText(texto_de_las_partes(jugando, minutos))
            self.texto_jugando.poner_texto(texto_de_lo_que_juega(jugando, minutos))
        else:
            self.titulo_saldo.setText("SALDO")
            self.aclaracion_saldo.setText("tiempo disponible para jugar")
        self.cartel_jugando.setVisible(bool(jugando))

    def _poner_las_pastillas(self, miembro, jugando=None):
        while self.fila_pastillas.count():
            vieja = self.fila_pastillas.takeAt(0).widget()
            if vieja is not None:
                # Sin padre deja de verse en el acto; Qt la borra cuando puede.
                vieja.setParent(None)
                vieja.deleteLater()
        activo = bool(miembro["activo"])
        self.fila_pastillas.addWidget(pastilla_clara("ACTIVO" if activo else "INACTIVO",
                                                     TONO_VERDE if activo else TONO_GRIS))
        con_saldo = tiempo_del_socio_repo.segundos_totales(miembro, jugando) > 0
        self.fila_pastillas.addWidget(pastilla_clara("CON SALDO" if con_saldo else "SIN SALDO",
                                                     TONO_AZUL if con_saldo else TONO_GRIS))
        if jugando:
            self.fila_pastillas.addWidget(pastilla_clara(f"JUGANDO {_en_las_pcs(jugando).upper()}", TONO_CELESTE))
        if not miembros_repo.tiene_dni(miembro):
            self.fila_pastillas.addWidget(pastilla_clara("FALTA DNI", TONO_ROJO))
        self.fila_pastillas.addStretch()

    def _llenar_las_cargas(self, cargas):
        self.tabla_cargas.setRowCount(0)
        self.tabla_cargas.setVisible(bool(cargas))
        self.sin_cargas.setVisible(not cargas)
        for carga in cargas:
            fila = self.tabla_cargas.rowCount()
            self.tabla_cargas.insertRow(fila)
            valores = (formato_fecha_hora(carga["fecha"]), formato_tiempo(carga["minutos"] * 60),
                       formato_pesos(carga["monto"]), carga["medio"], carga["operador"])
            for columna, valor in enumerate(valores):
                item = QTableWidgetItem(valor)
                if columna == 2:
                    tipo = item.font()
                    tipo.setBold(True)
                    item.setFont(tipo)
                if carga["anulada"]:
                    # Una carga anulada no suma: se ve tachada y en rojo (como en el Historial).
                    tipo = item.font()
                    tipo.setStrikeOut(True)
                    item.setFont(tipo)
                    item.setForeground(QColor("#C62828"))
                    item.setToolTip("Carga anulada: no suma")
                self.tabla_cargas.setItem(fila, columna, item)
        self.tabla_cargas.setFixedHeight(42 + 34 * len(cargas))
