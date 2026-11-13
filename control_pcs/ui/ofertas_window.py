"""
ofertas_window.py
=================
Configuración ADMIN > Ofertas: los 2x1 y 50% de los bonos, por día y turno (pedido del
dueño, 2026-11-13). Es la maqueta B, "la semana en una grilla", que eligió el dueño
entre las de PROPUESTA_OFERTAS:
- arriba, las ofertas como fichas (las terminadas, con VER TERMINADAS) y ＋ NUEVA;
- a la izquierda, la semana de la oferta elegida: cada cuadrito es un día y un turno y
  se prende o apaga con un clic (el domingo tiene sus dos turnos, T1 y T2); debajo, las
  próximas veces que corre y "Así queda:" con la oferta entera en castellano;
- a la derecha, el nombre, 2x1 o 50%, desde y hasta cuándo, y en qué bonos, cada uno
  con cómo queda con la oferta. Abajo TERMINAR, PAUSAR / REANUDAR y GUARDAR.

La pantalla solo junta lo elegido: valida, revisa choques y guarda ofertas_repo (solo
el Administrador, también desde otra PC). Las cuentas y las frases son las del repo.
Las piezas están en ofertas_piezas.py.
"""

import html
from datetime import datetime, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QScrollArea, QVBoxLayout, QWidget,
)

import dominio
import turnos
from control_pcs.repositories import ofertas_repo, pcs_repo, pcstream_repo, playstation_repo
from control_pcs.ui.dibujos_de_ventana import pixmap_de
from control_pcs.ui.ofertas_piezas import (
    TONO_DEL_ESTADO, CuadritoDeLaSemana, FichaDeOferta, RenglonDeBono, TarjetaDeTipo, avisar_choque, repintar, vaciar,
)
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, TONO_VERDE, agregar_pastilla, cabecera_oscura, panel_blanco, pastilla_clara,
    pie_de_ventana, tecla, titulo_de_seccion,
)
from ui.utils import confirmar, crear_selector_de_fecha, manejar_errores, mostrar_info, sin_boton_por_defecto

# Los catálogos en el orden del panel de la PC, con su título.
CATALOGOS = (
    (dominio.EQUIPO_RESERVA_PC, "Bonos de las PCs"),
    (dominio.EQUIPO_RESERVA_PLAYSTATION, "PlayStation 5"),
    (dominio.EQUIPO_RESERVA_PCSTREAM, dominio.NOMBRE_PCSTREAM),
)
# Una oferta nueva arranca hoy y dura un mes (se cambia con HASTA).
DIAS_DE_UNA_NUEVA = 30
CUANTAS_VECES = 5
_ORDEN_DE_LAS_FICHAS = (dominio.OFERTA_ACTIVA, dominio.OFERTA_PROGRAMADA, dominio.OFERTA_PAUSADA,
                        dominio.OFERTA_TERMINADA)


def _a_qdate(dia) -> QDate:
    return QDate(dia.year, dia.month, dia.day)


class OfertasWindow(QDialog):
    """La ventana de las ofertas. `usuario`: el que la abre (tiene que ser Admin para
    guardar, pausar o terminar: lo exige el repo)."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Ofertas")
        self.resize(1200, 940)
        self._ofertas = []
        self._catalogos = {}
        self._ver_terminadas = False
        self._borrador = None  # la oferta que se ve y se edita (un dict como los del repo)
        self._guardada = None  # cómo estaba al elegirla, para saber si hay cambios sin guardar
        self._armar_interfaz()
        self._recargar()

    # -----------------------------------------------------------------
    # Armado
    # -----------------------------------------------------------------

    def _armar_interfaz(self):
        cabecera = cabecera_oscura("", "Ofertas", "2x1 y 50% en los bonos, por día y turno  ·  Las arma solo el "
                                                  "Administrador; se aplican solas al cobrar")
        cabecera.icono.setPixmap(pixmap_de("etiqueta", 30, "#FFB677", 1.7))
        self.pastilla_activas = agregar_pastilla(cabecera, "", TONO_VERDE)
        self.pastilla_programadas = agregar_pastilla(cabecera, "", TONO_AZUL)
        self.pastilla_pausadas = agregar_pastilla(cabecera, "", TONO_GRIS)

        # Las fichas de arriba, en una tira que se desplaza de costado si son muchas.
        self.contenedor_fichas = QWidget()
        self.contenedor_fichas.setObjectName("tiraDeOfertas")
        self.capa_fichas = QHBoxLayout(self.contenedor_fichas)
        self.capa_fichas.setContentsMargins(0, 0, 0, 0)
        self.capa_fichas.setSpacing(8)
        tira = QScrollArea()
        tira.setObjectName("tiraDeOfertas")
        tira.setWidgetResizable(True)
        tira.setFrameShape(QFrame.NoFrame)
        tira.setVerticalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        tira.setFixedHeight(72)
        tira.setWidget(self.contenedor_fichas)
        self.boton_terminadas = tecla("VER TERMINADAS", self._alternar_terminadas)
        self.boton_nueva = tecla("＋  NUEVA", self._nueva, "teclaAzul")
        fila_fichas = QHBoxLayout()
        fila_fichas.setSpacing(8)
        fila_fichas.addWidget(tira, 1)
        fila_fichas.addWidget(self.boton_terminadas, 0, Qt.AlignTop)
        fila_fichas.addWidget(self.boton_nueva, 0, Qt.AlignTop)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        cuerpo.addWidget(self._armar_semana(), 1)
        cuerpo.addWidget(self._armar_datos())

        pie = QHBoxLayout()
        pie.addWidget(pie_de_ventana(
            "Arriba, las ofertas: tocá una para verla en la semana  ·  Cada cuadrito es un día y un turno: así se "
            "puede armar, por ejemplo, viernes Noche y sábado Tarde en la misma oferta  ·  Vale la hora en que se "
            "COBRA"), 1)
        pie.addWidget(tecla("CERRAR", self.reject, "teclaRoja"))

        capa = QVBoxLayout(self)
        capa.setContentsMargins(16, 16, 16, 12)
        capa.setSpacing(12)
        capa.addWidget(cabecera)
        capa.addLayout(fila_fichas)
        capa.addLayout(cuerpo, 1)
        capa.addLayout(pie)
        sin_boton_por_defecto(self)

    def _armar_semana(self) -> QWidget:
        panel, capa = panel_blanco()
        self.titulo_semana = titulo_de_seccion("")
        self.titulo_semana.setTextFormat(Qt.PlainText)  # lleva el nombre de la oferta tal cual
        capa.addWidget(self.titulo_semana)
        grilla = QGridLayout()
        grilla.setSpacing(6)
        for columna, dia in enumerate(ofertas_repo.DIAS, start=1):
            cabeza = QLabel(dia[:3].upper())
            cabeza.setObjectName("diaSemanaOferta")
            cabeza.setAlignment(Qt.AlignCenter)
            grilla.addWidget(cabeza, 0, columna)
        self.cuadritos = {}
        for fila, turno in enumerate(dominio.TURNOS, start=1):
            inicio, fin = ofertas_repo.horario_de_la_franja(0, turno)
            rotulo = QLabel(f"<b>{turno}</b><br>{inicio} a {fin}")
            rotulo.setObjectName("turnoSemanaOferta")
            grilla.addWidget(rotulo, fila, 0)
        for dia, turno in ofertas_repo.franjas_de_la_semana():
            cuadrito = CuadritoDeLaSemana(dia, turno, self._tocar_cuadrito)
            self.cuadritos[(dia, turno)] = cuadrito
            fila = dominio.TURNOS.index(turno) + 1
            if dia != ofertas_repo.DOMINGO:
                grilla.addWidget(cuadrito, fila, dia + 1)
            elif turno == dominio.TURNO_MANANA:
                grilla.addWidget(cuadrito, 1, dia + 1, 2, 1)  # el T1 del domingo ocupa Mañana y Tarde
            else:
                grilla.addWidget(cuadrito, 3, dia + 1)
        grilla.setColumnMinimumWidth(0, 74)
        for columna in range(1, 8):
            grilla.setColumnStretch(columna, 1)
        capa.addLayout(grilla)
        nota = QLabel("La Noche de cada día termina a las 06:00 del día siguiente.  El domingo tiene 2 turnos (T1 y "
                      "T2), por eso su columna es distinta.  En chiquito, las otras ofertas: si una toca los mismos "
                      "bonos en el mismo cuadrito, no deja guardar.")
        nota.setObjectName("notaOferta")
        nota.setWordWrap(True)
        capa.addWidget(nota)
        capa.addSpacing(4)
        capa.addWidget(titulo_de_seccion("Las próximas veces"))
        # Siempre HTML: con una sola vez no hay ningún <br> y Qt lo tomaría como texto
        # común, con los &nbsp; a la vista.
        self.etiqueta_veces = QLabel()
        self.etiqueta_veces.setTextFormat(Qt.RichText)
        self.etiqueta_veces.setObjectName("textoOferta")
        self.etiqueta_veces.setWordWrap(True)
        capa.addWidget(self.etiqueta_veces)
        capa.addStretch()
        self.asi_queda = QLabel()
        self.asi_queda.setTextFormat(Qt.RichText)
        self.asi_queda.setObjectName("asiQuedaOferta")
        self.asi_queda.setWordWrap(True)
        capa.addWidget(self.asi_queda)
        return panel

    def _armar_datos(self) -> QWidget:
        panel, capa = panel_blanco()
        panel.setFixedWidth(410)
        capa.setSpacing(8)
        rotulo = QLabel("NOMBRE")
        rotulo.setObjectName("rotuloCampoOferta")
        capa.addWidget(rotulo)
        self.campo_nombre = QLineEdit()
        self.campo_nombre.setMaxLength(ofertas_repo.LARGO_MAXIMO_DEL_NOMBRE)
        self.campo_nombre.setPlaceholderText("Por ejemplo, Noche de finde")
        self.campo_nombre.textEdited.connect(self._cambiar_nombre)
        self.pastilla_estado = pastilla_clara("", TONO_GRIS)
        fila = QHBoxLayout()
        fila.addWidget(self.campo_nombre, 1)
        fila.addWidget(self.pastilla_estado)
        capa.addLayout(fila)

        capa.addWidget(titulo_de_seccion("Qué oferta"))
        self.tarjetas_tipo = [TarjetaDeTipo(tipo, self._elegir_tipo) for tipo in dominio.TIPOS_OFERTA]
        for tarjeta in self.tarjetas_tipo:
            capa.addWidget(tarjeta)

        capa.addWidget(titulo_de_seccion("Desde y hasta cuándo"))
        self.campo_desde = crear_selector_de_fecha()
        self.campo_hasta = crear_selector_de_fecha()
        fechas = QHBoxLayout()
        for texto, campo in (("DESDE", self.campo_desde), ("HASTA", self.campo_hasta)):
            rotulo = QLabel(texto)
            rotulo.setObjectName("rotuloCampoOferta")
            campo.setFixedWidth(130)
            campo.dateChanged.connect(self._cambiar_fechas)
            fechas.addWidget(rotulo)
            fechas.addWidget(campo)
            if texto == "DESDE":
                fechas.addStretch()
        capa.addLayout(fechas)

        capa.addWidget(titulo_de_seccion("En qué bonos"))
        self.contenedor_bonos = QWidget()
        self.contenedor_bonos.setObjectName("bonosDeLaOferta")
        self.capa_bonos = QVBoxLayout(self.contenedor_bonos)
        self.capa_bonos.setContentsMargins(0, 0, 4, 0)
        self.capa_bonos.setSpacing(2)
        area = QScrollArea()
        area.setObjectName("bonosDeLaOferta")
        area.setWidgetResizable(True)
        area.setFrameShape(QFrame.NoFrame)
        area.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        area.setWidget(self.contenedor_bonos)
        capa.addWidget(area, 1)
        self.renglones = []

        self.boton_terminar = tecla("TERMINAR", self._terminar, "teclaRoja")
        self.boton_pausar = tecla("PAUSAR", self._pausar_o_reanudar)
        self.boton_usar_de_nuevo = tecla("USAR DE NUEVO", self._usar_de_nuevo)
        self.boton_guardar = tecla("GUARDAR", self._guardar, "teclaAzul")
        teclas = QHBoxLayout()
        teclas.addWidget(self.boton_terminar)
        teclas.addStretch()
        for boton in (self.boton_pausar, self.boton_usar_de_nuevo, self.boton_guardar):
            teclas.addWidget(boton)
        capa.addLayout(teclas)
        return panel

    # -----------------------------------------------------------------
    # Leer
    # -----------------------------------------------------------------

    @manejar_errores
    def _recargar(self, elegir_id=None):
        """Vuelve a leer las ofertas y los bonos y muestra `elegir_id` (o la que se
        estaba viendo, o la primera, o una nueva si no hay ninguna)."""
        self._ofertas = ofertas_repo.listar_ofertas()
        for equipo, repo in ((dominio.EQUIPO_RESERVA_PC, pcs_repo), (dominio.EQUIPO_RESERVA_PCSTREAM, pcstream_repo),
                             (dominio.EQUIPO_RESERVA_PLAYSTATION, playstation_repo)):
            self._catalogos[equipo] = [{clave: fila[clave] for clave in fila.keys()}
                                       for fila in repo.listar_bonos(False)]
        cuantas = {estado: sum(1 for o in self._ofertas if o["estado"] == estado) for estado in _ORDEN_DE_LAS_FICHAS}
        for pastilla, estado, una, varias in (
                (self.pastilla_activas, dominio.OFERTA_ACTIVA, "ACTIVA AHORA", "ACTIVAS AHORA"),
                (self.pastilla_programadas, dominio.OFERTA_PROGRAMADA, "PROGRAMADA", "PROGRAMADAS"),
                (self.pastilla_pausadas, dominio.OFERTA_PAUSADA, "PAUSADA", "PAUSADAS")):
            pastilla.setText(f"{cuantas[estado]} {una if cuantas[estado] == 1 else varias}")
            pastilla.setVisible(cuantas[estado] > 0)
        self._poner_boton_terminadas()

        if elegir_id is None and self._borrador is not None:
            elegir_id = self._borrador["id"]
        elegida = next((o for o in self._ofertas if o["id"] == elegir_id), None) if elegir_id is not None else None
        if elegida is None and (self._borrador is None or self._borrador["id"] is not None):
            elegida = next((o for o in self._fichas_a_mostrar()), None)
        if elegida is not None:
            self._mostrar(elegida)
        elif self._borrador is None:
            self._mostrar(self._oferta_nueva())
        else:
            self._dibujar_fichas()

    def _poner_boton_terminadas(self):
        terminadas = sum(1 for o in self._ofertas if o["estado"] == dominio.OFERTA_TERMINADA)
        self.boton_terminadas.setText("OCULTAR TERMINADAS" if self._ver_terminadas else
                                      f"VER TERMINADAS ({terminadas})")
        self.boton_terminadas.setEnabled(terminadas > 0 or self._ver_terminadas)

    def _fichas_a_mostrar(self) -> list:
        ofertas = [o for o in self._ofertas if self._ver_terminadas or o["estado"] != dominio.OFERTA_TERMINADA]
        return sorted(ofertas, key=lambda o: _ORDEN_DE_LAS_FICHAS.index(o["estado"]))

    def _dibujar_fichas(self):
        vaciar(self.capa_fichas)
        self.fichas = []
        for oferta in self._fichas_a_mostrar():
            ficha = FichaDeOferta(oferta, self._elegir_ficha)
            ficha.setChecked(self._borrador is not None and oferta["id"] == self._borrador["id"])
            self.fichas.append(ficha)
            self.capa_fichas.addWidget(ficha)
        if not self.fichas:
            vacio = QLabel("Todavía no hay ofertas: armá la primera a la derecha y apretá GUARDAR.")
            vacio.setObjectName("notaOferta")
            self.capa_fichas.addWidget(vacio)
        self.capa_fichas.addStretch()

    def _oferta_nueva(self) -> dict:
        hoy = turnos.dia_en_que_empezo_el_turno(datetime.now())
        return {"id": None, "nombre": "", "tipo": dominio.OFERTA_2X1, "desde": hoy,
                "hasta": hoy + timedelta(days=DIAS_DE_UNA_NUEVA), "franjas": [], "bonos": [], "pausada": False,
                "terminada_fecha": None, "estado": None}

    # -----------------------------------------------------------------
    # Mostrar la oferta elegida
    # -----------------------------------------------------------------

    def _mostrar(self, oferta: dict):
        self._borrador = dict(oferta, franjas=list(oferta["franjas"]), bonos=list(oferta["bonos"]))
        self._guardada = self._como_esta()
        self._dibujar_fichas()
        editable = self._editable()
        self.campo_nombre.setText(oferta["nombre"])
        self.campo_nombre.setReadOnly(not editable)
        estado = oferta["estado"] or "NUEVA"
        self.pastilla_estado.setText(estado)
        repintar(self.pastilla_estado, tono=TONO_DEL_ESTADO.get(oferta["estado"], TONO_GRIS))
        for campo, dia in ((self.campo_desde, oferta["desde"]), (self.campo_hasta, oferta["hasta"])):
            campo.blockSignals(True)
            campo.setDate(_a_qdate(dia))
            campo.blockSignals(False)
            campo.setEnabled(editable)
        self._armar_renglones()
        nueva, terminada = oferta["id"] is None, oferta["estado"] == dominio.OFERTA_TERMINADA
        self.boton_terminar.setVisible(not nueva and not terminada)
        self.boton_pausar.setVisible(not nueva and not terminada)
        self.boton_pausar.setText("REANUDAR" if oferta["pausada"] else "PAUSAR")
        self.boton_usar_de_nuevo.setVisible(terminada)
        self.boton_guardar.setVisible(not terminada)
        self._pintar()

    def _editable(self) -> bool:
        return self._borrador is not None and self._borrador["estado"] != dominio.OFERTA_TERMINADA

    def _armar_renglones(self):
        """Un renglón por bono a la venta de cada catálogo, más los dados de baja que
        la oferta tiene (para poder sacarlos). Los de Socios nunca llevan oferta."""
        vaciar(self.capa_bonos)
        self.renglones = []
        for equipo, titulo in CATALOGOS:
            rotulo = QLabel(titulo.upper())
            rotulo.setObjectName("rotuloCampoOferta")
            self.capa_bonos.addWidget(rotulo)
            bonos = [bono for bono in self._catalogos.get(equipo, [])
                     if bono["activo"] or (equipo, bono["id"]) in self._borrador["bonos"]]
            if not bonos:
                vacio = QLabel("No hay bonos cargados.")
                vacio.setObjectName("notaOferta")
                self.capa_bonos.addWidget(vacio)
            for bono in bonos:
                renglon = RenglonDeBono(equipo, bono, self._tildar_bono)
                self.renglones.append(renglon)
                self.capa_bonos.addWidget(renglon)
        nota = QLabel("Los bonos de Socios nunca llevan oferta.")
        nota.setObjectName("notaOferta")
        self.capa_bonos.addWidget(nota)
        self.capa_bonos.addStretch()

    def _pintar(self):
        """Todo lo que cambia al tocar algo: los cuadritos, las tarjetas, los bonos y
        el resumen de abajo."""
        oferta, editable = self._borrador, self._editable()
        self._poner_titulo_semana()
        otras = [o for o in self._ofertas if o["id"] != oferta["id"] and o["estado"] != dominio.OFERTA_TERMINADA]
        for franja, cuadrito in self.cuadritos.items():
            cuadrito.pintar(franja in oferta["franjas"], oferta["tipo"], [o for o in otras if franja in o["franjas"]])
        for tarjeta in self.tarjetas_tipo:
            tarjeta.pintar(tarjeta.tipo == oferta["tipo"])
        for renglon in self.renglones:
            renglon.pintar((renglon.equipo, renglon.bono["id"]) in oferta["bonos"], oferta["tipo"], editable)
        self._pintar_resumen()

    def _poner_titulo_semana(self):
        nombre = self._borrador["nombre"].strip()
        self.titulo_semana.setText((f"La semana de «{nombre}»" if nombre else "La semana de la oferta").upper()
                                   + ("  ·  TOCÁ UN CUADRITO PARA PRENDERLO O APAGARLO" if self._editable() else ""))

    def _pintar_resumen(self):
        oferta = self._borrador
        ahora = datetime.now()
        nombres = {(equipo, bono["id"]): bono["nombre"] for equipo, bonos in self._catalogos.items() for bono in bonos}
        if oferta["estado"] == dominio.OFERTA_TERMINADA:
            veces = "Ya terminó: no se aplica más. Para volver a ponerla, USAR DE NUEVO arma una copia."
        elif oferta["hasta"] < oferta["desde"]:
            veces = "La fecha HASTA es anterior a DESDE."
        elif not oferta["franjas"]:
            veces = "Marcá en la semana los días y turnos en que corre."
        else:
            # Pausada, se muestra cuándo correría al reanudarla.
            sin_pausa = dict(oferta, pausada=False, terminada_fecha=None)
            proximas = ofertas_repo.proximas_veces(sin_pausa, ahora, CUANTAS_VECES + 1)
            renglones = [ofertas_repo.frase_de_la_vez(inicio, fin, ahora, ultima=numero == len(proximas) - 1)
                         for numero, (inicio, fin) in enumerate(proximas[:CUANTAS_VECES])]
            if not renglones:
                veces = "Entre esas fechas no queda por delante ningún día con los turnos marcados."
            else:
                veces = "<br>".join(f"●&nbsp;&nbsp;{html.escape(renglon)}" for renglon in renglones)
                if oferta["pausada"]:
                    veces = "<b>Está PAUSADA:</b> no se aplica hasta que la reanudes. Al reanudarla:<br>" + veces
        self.etiqueta_veces.setText(veces)
        if oferta["franjas"] and oferta["bonos"]:
            self.asi_queda.setText(f"<b>Así queda:</b>  {html.escape(ofertas_repo.frase(oferta, nombres))}")
        else:
            self.asi_queda.setText("<b>Así queda:</b>  elegí los días y turnos en la semana y los bonos a la "
                                   "derecha.")

    # -----------------------------------------------------------------
    # Lo que toca el Administrador
    # -----------------------------------------------------------------

    def _como_esta(self) -> tuple:
        oferta = self._borrador
        return (oferta["nombre"].strip(), oferta["tipo"], oferta["desde"], oferta["hasta"],
                sorted(oferta["franjas"]), sorted(oferta["bonos"]))

    def _hay_cambios(self) -> bool:
        if self._borrador is None or not self._editable():
            return False
        if self._borrador["id"] is None:
            nombre, _, _, _, franjas, bonos = self._como_esta()
            return bool(nombre or franjas or bonos)
        return self._como_esta() != self._guardada

    def _se_pueden_dejar_los_cambios(self) -> bool:
        return not self._hay_cambios() or confirmar(
            self, "Cambios sin guardar", "Hay cambios sin guardar en esta oferta. ¿Dejarlos sin guardar?")

    def _elegir_ficha(self, oferta: dict):
        if oferta["id"] == self._borrador["id"] or not self._se_pueden_dejar_los_cambios():
            self._dibujar_fichas()  # vuelve a marcar la que se está viendo
            return
        self._mostrar(oferta)

    def _alternar_terminadas(self):
        # Sin volver a leer: lo que se está editando no se pierde.
        self._ver_terminadas = not self._ver_terminadas
        self._poner_boton_terminadas()
        self._dibujar_fichas()

    def _nueva(self):
        if self._se_pueden_dejar_los_cambios():
            self._mostrar(self._oferta_nueva())
            self.campo_nombre.setFocus()

    def _usar_de_nuevo(self):
        """Una copia de la terminada, para volver a ponerla: arranca hoy y dura lo mismo."""
        vieja = self._borrador
        hoy = turnos.dia_en_que_empezo_el_turno(datetime.now())
        self._mostrar(dict(vieja, id=None, estado=None, pausada=False, terminada_fecha=None, desde=hoy,
                           hasta=hoy + (vieja["hasta"] - vieja["desde"])))

    def _cambiar_nombre(self, texto: str):
        self._borrador["nombre"] = texto
        self._poner_titulo_semana()
        self._pintar_resumen()

    def _elegir_tipo(self, tipo: str):
        if self._editable():
            self._borrador["tipo"] = tipo
        self._pintar()

    def _cambiar_fechas(self, *_):
        self._borrador["desde"] = self.campo_desde.date().toPython()
        self._borrador["hasta"] = self.campo_hasta.date().toPython()
        self._pintar_resumen()

    def _tocar_cuadrito(self, dia: int, turno: str):
        if self._editable():
            franjas = self._borrador["franjas"]
            if (dia, turno) in franjas:
                franjas.remove((dia, turno))
            else:
                franjas.append((dia, turno))
        self._pintar()

    def _tildar_bono(self, equipo: str, bono_id: int, marcado: bool):
        bonos = self._borrador["bonos"]
        if marcado and (equipo, bono_id) not in bonos:
            bonos.append((equipo, bono_id))
        elif not marcado and (equipo, bono_id) in bonos:
            bonos.remove((equipo, bono_id))
        self._pintar()

    @manejar_errores
    def _guardar(self):
        oferta = self._borrador
        try:
            oferta_id = ofertas_repo.guardar_oferta(
                self.usuario["id"], oferta["id"], oferta["nombre"], oferta["tipo"], oferta["desde"],
                oferta["hasta"], oferta["franjas"], oferta["bonos"],
            )
        except ofertas_repo.ChocaConOtraOferta as choque:
            avisar_choque(self, str(choque))
            return
        nombres = {(equipo, bono["id"]): bono["nombre"] for equipo, bonos in self._catalogos.items() for bono in bonos}
        frase = ofertas_repo.frase(oferta, nombres)
        self._borrador = None
        self._recargar(elegir_id=oferta_id)
        mostrar_info(self, "Oferta guardada", f"«{oferta['nombre'].strip()}» quedó guardada:\n\n{frase}\n\n"
                                              "Se aplica sola al cobrar, en el panel de la PC.")

    @manejar_errores
    def _pausar_o_reanudar(self):
        oferta = self._borrador
        sin_guardar = "\n\nLos cambios sin guardar se pierden." if self._hay_cambios() else ""
        if oferta["pausada"]:
            if not confirmar(self, "Reanudar", f"¿Reanudar «{oferta['nombre']}»? Vuelve a aplicarse en sus días y "
                                               f"turnos.{sin_guardar}"):
                return
            ofertas_repo.reanudar_oferta(self.usuario["id"], oferta["id"])
        else:
            if not confirmar(self, "Pausar", f"¿Pausar «{oferta['nombre']}»? Deja de aplicarse hasta que la "
                                             f"reanudes; los bonos se cobran como siempre.{sin_guardar}"):
                return
            ofertas_repo.pausar_oferta(self.usuario["id"], oferta["id"])
        self._borrador = None
        self._recargar(elegir_id=oferta["id"])

    @manejar_errores
    def _terminar(self):
        oferta = self._borrador
        if not confirmar(self, "Terminar", f"¿Terminar «{oferta['nombre']}» ya? Deja de aplicarse en el acto y "
                                           "queda en la lista como TERMINADA (con VER TERMINADAS).\n\n"
                                           "No se vuelve a prender: para ponerla otra vez, USAR DE NUEVO arma una "
                                           "copia."):
            return
        ofertas_repo.terminar_oferta(self.usuario["id"], oferta["id"])
        self._borrador = None
        self._recargar()

    def reject(self):
        # Cerrar con la X, con Esc o con CERRAR: avisa si hay algo sin guardar.
        if self._se_pueden_dejar_los_cambios():
            super().reject()
