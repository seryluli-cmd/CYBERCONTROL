"""
miembros_ficha.py
=================
Las piezas de la ventana de Administración de Miembros con el diseño "ficha del socio" que
eligió el dueño el 2026-10-29 (maqueta B, entre tres): a la izquierda la lista de socios, con
su círculo de iniciales, su saldo y hace cuánto vino (`DelegadoDeSocios`), y a la derecha la
ficha del que está elegido (`FichaDelSocio`): saldo, última carga, última visita, datos de
contacto, los botones que actúan sobre ESE socio y sus últimas cargas. Arriba de la lista, los
filtros en una pista de botones (`Segmentos`).

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
from control_pcs.repositories import miembros_repo
from control_pcs.ui.dibujos_de_ventana import pixmap_de_avatar, poner_icono
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_ROJO, TONO_VERDE, pastilla_clara, tecla, titulo_de_seccion,
)
from ui.utils import aplicar_clase, crear_tabla, formato_fecha_hora, formato_pesos, formato_tiempo

# El dato de cada renglón de la lista: {"miembro": socio, "dias": hace cuántos días no viene}.
ROL_DATOS = Qt.UserRole + 1
# "Hace N días" en naranja pasados dominio.DIAS_SIN_VENIR_AVISO días.
COLOR_NO_VIENE = QColor("#D35400")
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
        pintor.setPen(QColor(color_del_saldo(miembro["saldo_minutos"]) if activo else "#A7ADB8"))
        pintor.drawText(QRectF(columna.left(), zona.top() + 9, columna.width(), 20), Qt.AlignRight | Qt.AlignVCenter,
                        formato_tiempo(miembro["saldo_minutos"] * 60))

        letra.setPixelSize(11)
        letra.setBold(False)
        pintor.setFont(letra)
        if not activo:
            texto, color = "Inactivo", QColor("#8A94A6")
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


def _bloque(titulo: str, destacado: bool = False):
    """Un recuadro con un título chico, un valor grande y una línea que lo aclara:
    (el recuadro, la etiqueta del valor, la de la aclaración)."""
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
    return marco, valor, aclaracion


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
        bloque_saldo, self.valor_saldo, aclaracion_saldo = _bloque("SALDO", destacado=True)
        aclaracion_saldo.setText("tiempo disponible para jugar")
        bloque_carga, self.valor_carga, self.aclaracion_carga = _bloque("ÚLTIMA CARGA")
        bloque_visita, self.valor_visita, self.aclaracion_visita = _bloque("ÚLTIMA VISITA")
        tres.addWidget(bloque_saldo, 5)
        tres.addWidget(bloque_carga, 4)
        tres.addWidget(bloque_visita, 4)
        capa.addLayout(tres)

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

    def mostrar(self, miembro, dias, visita, cargas):
        """`miembro`: el socio; `dias`: hace cuántos días no viene (None = nunca vino);
        `visita`: lo de ultima_visita_repo.ultimas_visitas() para él; `cargas`: sus cargas de
        historial_cargas_repo.listar_cargas, de la más nueva a la más vieja."""
        self._paginas.setCurrentIndex(1)
        usuario = miembro["usuario"]
        self.avatar.setPixmap(_avatar(usuario, 68))
        self.etiqueta_nombre.setText(miembro["nombre"] or usuario)
        self.etiqueta_usuario.setText(f"Usuario: {usuario}")
        self._poner_las_pastillas(miembro)

        minutos = miembro["saldo_minutos"]
        self.valor_saldo.setText(formato_tiempo(minutos * 60))
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

    def _poner_las_pastillas(self, miembro):
        while self.fila_pastillas.count():
            vieja = self.fila_pastillas.takeAt(0).widget()
            if vieja is not None:
                # Sin padre deja de verse en el acto; Qt la borra cuando puede.
                vieja.setParent(None)
                vieja.deleteLater()
        activo = bool(miembro["activo"])
        self.fila_pastillas.addWidget(pastilla_clara("ACTIVO" if activo else "INACTIVO",
                                                     TONO_VERDE if activo else TONO_GRIS))
        con_saldo = miembro["saldo_minutos"] > 0
        self.fila_pastillas.addWidget(pastilla_clara("CON SALDO" if con_saldo else "SIN SALDO",
                                                     TONO_AZUL if con_saldo else TONO_GRIS))
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
