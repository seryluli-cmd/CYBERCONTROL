"""
reservas_nueva.py
=================
La ventana NUEVA RESERVA (tecla de la ventana RESERVAS) con el diseño "B: equipos a la
vista" que eligió el dueño el 2026-11-21 entre tres (PROPUESTA_NUEVA_RESERVA en la carpeta
de los proyectos). Pidió "que parezca más profesional: me suma puntos cuando muestro el
programa".

- Arriba, la cabecera oscura, como en Reservas.
- A la izquierda, el cliente, el día y la hora, los bonos del equipo elegido como
  tarjetas y cuánto paga ahora (50%, 100% u otro monto).
- A la derecha, los equipos a la vista con el color de su rubro: las PS5 en tarjetas
  rosas grandes, arriba de todo (arranca en la PS5-1, pedido del dueño); después
  "Cualquier PC disponible" y una ficha azul por PC (PCSTREAM en celeste). El equipo
  que ya tiene una reserva a esa hora lo dice (reservas_repo.reservados_a_esa_hora).
- Abajo, una barra con el resumen, lo que se cobra ahora en verde y COBRAR.

Las reglas (qué se puede reservar, cuánto se cobra, qué pasa si no viene) siguen en
control_pcs/repositories/reservas_repo.py: acá solo se pregunta y se muestra. La
ventana salió de reservas_dialogos.py, que con ella pasaba las 600 líneas (regla 12).
Los colores están en ui/hoja_de_estilos.py, por "clase" u objectName.
"""

from datetime import timedelta

from PySide6.QtCore import QDate, Qt, QTime
from PySide6.QtWidgets import (
    QAbstractSpinBox, QButtonGroup, QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea,
    QVBoxLayout, QWidget,
)

import dominio
from control_pcs.repositories import reservas_repo, reservas_socios_repo
from control_pcs.ui.dibujos_de_ventana import pixmap_de
from control_pcs.ui.reservas_dialogos import (
    TONO_DEL_EQUIPO, _campo_hora, _momento, _proxima_hora_en_punto, texto_dia_y_hora,
)
from ui.dialogo_pago import cobrar
from ui.dibujos_tabla import color_fuerte
from ui.piezas_ventana import TONO_CELESTE, agregar_pastilla, cabecera_oscura, panel_blanco, tecla, titulo_de_seccion
from ui.utils import (
    CampoPesos, aplicar_clase, crear_selector_de_fecha, encadenar_enter, formato_pesos, manejar_errores,
    mostrar_error, mostrar_info, sin_boton_por_defecto,
)

# Cuántas fichas de PC van por fila: con las 30 del local quedan 5 filas y la ventana
# entra en una pantalla de 1366 x 768.
PCS_POR_FILA = 6

# El tamaño con que abre (ver DialogoNuevaReserva.__init__): el alto es 680 + 30%.
ANCHO_DE_LA_VENTANA = 1100
ALTO_DE_LA_VENTANA = 884


def _repintar(widget):
    """Vuelve a aplicar la hoja de estilos después de cambiarle una propiedad."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _rotulo(texto: str) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName("rotuloCampo")
    return etiqueta


def _con_rotulo(texto: str, widget) -> QVBoxLayout:
    """El campo con su nombre chiquito arriba."""
    capa = QVBoxLayout()
    capa.setSpacing(4)
    capa.addWidget(_rotulo(texto))
    capa.addWidget(widget)
    return capa


def _que_no_tape_el_clic(*etiquetas):
    """Las etiquetas de adentro de un botón: que el clic le llegue al botón."""
    for etiqueta in etiquetas:
        etiqueta.setAttribute(Qt.WA_TransparentForMouseEvents)


class DialogoNuevaReserva(QDialog):
    """Tomar una reserva y cobrar la seña (o todo). Al aceptar queda
    `self.reserva_id`, el número de la reserva nueva."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.reserva_id = None
        self.setWindowTitle("Nueva reserva")
        self.equipos = reservas_repo.equipos_para_reservar()
        self._armar_interfaz()
        # Un 30% más alta que al principio (680), pedido del dueño 2026-11-21: "para que
        # cuando se elija una PC se puedan ver todas las promos" (la lista de bonos se estira
        # con la ventana). Nunca más que la pantalla, para que no se salga de ella.
        ancho, alto = ANCHO_DE_LA_VENTANA, ALTO_DE_LA_VENTANA
        if self.screen() is not None:
            disponible = self.screen().availableGeometry()
            ancho = min(ancho, disponible.width() - 20)
            alto = min(alto, disponible.height() - 40)
        self.resize(ancho, alto)
        self._marcar_reservados()
        self._cargar_bonos()

    # ------------------------------------------------------------ armado

    def _armar_interfaz(self):
        cabecera = cabecera_oscura("📅", "Nueva reserva", "Se cobra ahora la seña o todo · el precio queda fijo")
        agregar_pastilla(cabecera, f"TOLERANCIA  {dominio.texto_tolerancia_reserva().upper()}", TONO_CELESTE)

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)
        cuerpo.addWidget(self._panel_del_cliente())
        cuerpo.addWidget(self._panel_de_equipos(), 1)

        self.aviso = QLabel()
        self.aviso.setObjectName("avisoNuevaReserva")
        self.aviso.setWordWrap(True)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(16, 16, 16, 16)
        layout.setSpacing(12)
        layout.addWidget(cabecera)
        layout.addLayout(cuerpo, 1)
        layout.addWidget(self._barra_de_cobro())
        layout.addWidget(self.aviso)
        # El equipo y el bono se eligen tocando: Enter va de campo en campo y en la
        # hora cobra, como antes en el último campo.
        encadenar_enter(self.campo_cliente, self.campo_celular, self.campo_dia, self.campo_hora,
                        accion_final=self._cobrar)
        sin_boton_por_defecto(self)
        self.campo_cliente.setFocus()

    def _panel_del_cliente(self) -> QFrame:
        panel, capa = panel_blanco()
        panel.setFixedWidth(340)
        capa.addWidget(titulo_de_seccion("Cliente y horario"))
        self.campo_cliente = QLineEdit()
        self.campo_cliente.setPlaceholderText("Nombre de quien reserva")
        self.campo_celular = QLineEdit()
        self.campo_celular.setPlaceholderText("Opcional")
        inicio = _proxima_hora_en_punto()
        self.campo_dia = crear_selector_de_fecha(QDate(inicio.year, inicio.month, inicio.day))
        self.campo_hora = _campo_hora(QTime(inicio.hour, 0))
        # Sin flechitas, como los demás campos de números del programa: con el borde de
        # la hoja de estilos se dibujan rotas. La hora se escribe o se mueve con la ruedita.
        self.campo_hora.setButtonSymbols(QAbstractSpinBox.NoButtons)
        for campo in (self.campo_cliente, self.campo_celular, self.campo_dia, self.campo_hora):
            campo.setObjectName("campoReserva")
        capa.addLayout(_con_rotulo("Nombre", self.campo_cliente))
        capa.addLayout(_con_rotulo("Celular (para avisarle)", self.campo_celular))
        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addLayout(_con_rotulo("Día", self.campo_dia), 3)
        fila.addLayout(_con_rotulo("Hora", self.campo_hora), 2)
        capa.addLayout(fila)
        self.campo_dia.dateChanged.connect(self._al_cambiar_la_hora)
        self.campo_hora.timeChanged.connect(self._al_cambiar_la_hora)

        # Los bonos del equipo elegido, como tarjetas; si son muchos, se desplazan.
        capa.addSpacing(4)
        self.titulo_bonos = titulo_de_seccion("Bono")
        capa.addWidget(self.titulo_bonos)
        self.etiqueta_sin_bonos = QLabel()
        self.etiqueta_sin_bonos.setObjectName("sinBonos")
        self.etiqueta_sin_bonos.setWordWrap(True)
        self.etiqueta_sin_bonos.hide()
        capa.addWidget(self.etiqueta_sin_bonos)
        contenido = QWidget()
        contenido.setObjectName("contenidoBonos")
        self.capa_bonos = QVBoxLayout(contenido)
        self.capa_bonos.setContentsMargins(0, 0, 0, 0)
        self.capa_bonos.setSpacing(6)
        self.capa_bonos.addStretch()
        lista = QScrollArea()
        lista.setObjectName("listaDeBonos")
        lista.setWidgetResizable(True)
        lista.setFrameShape(QFrame.NoFrame)
        lista.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        lista.setWidget(contenido)
        capa.addWidget(lista, 1)
        self.grupo_bono = QButtonGroup(self)
        self.grupo_bono.buttonToggled.connect(self._al_elegir_bono)

        # Cuánto paga ahora: la mitad, todo, u otro monto (más de cero y hasta el precio).
        capa.addWidget(titulo_de_seccion("Paga ahora"))
        pista = QFrame()
        pista.setObjectName("pistaSegmentos")
        capa_pista = QHBoxLayout(pista)
        capa_pista.setContentsMargins(3, 3, 3, 3)
        capa_pista.setSpacing(2)
        self._grupo_paga = QButtonGroup(self)
        segmentos = []
        for texto in ("50%", "100%", "OTRO MONTO"):
            segmento = QPushButton(texto)
            aplicar_clase(segmento, "segmento")
            segmento.setCheckable(True)
            self._grupo_paga.addButton(segmento)
            capa_pista.addWidget(segmento)
            segmentos.append(segmento)
        self.opcion_mitad, self.opcion_todo, self.opcion_otro = segmentos
        self.opcion_mitad.setChecked(True)
        self._grupo_paga.buttonToggled.connect(self._actualizar_monto)
        capa.addWidget(pista)
        self.spin_otro = CampoPesos()
        self.spin_otro.valueChanged.connect(self._actualizar_monto)
        self.fila_otro = QWidget()
        capa_otro = QHBoxLayout(self.fila_otro)
        capa_otro.setContentsMargins(0, 0, 0, 0)
        capa_otro.addWidget(_rotulo("Monto que deja:"))
        capa_otro.addWidget(self.spin_otro, 1)
        self.fila_otro.hide()
        capa.addWidget(self.fila_otro)
        return panel

    def _panel_de_equipos(self) -> QFrame:
        panel, capa = panel_blanco()
        capa.addWidget(titulo_de_seccion("Elegí el equipo"))
        self.grupo_equipo = QButtonGroup(self)
        self.botones_equipo = []
        consolas = QHBoxLayout()
        consolas.setSpacing(12)
        grilla = QGridLayout()
        grilla.setSpacing(6)
        cualquier_pc = None
        fichas = 0
        for opcion in self.equipos:
            if opcion["equipo"] == dominio.EQUIPO_RESERVA_PLAYSTATION:
                boton = self._tarjeta_de_consola(opcion)
                consolas.addWidget(boton)
            elif opcion["equipo"] == dominio.EQUIPO_RESERVA_PC and opcion["estacion_id"] is None:
                boton = cualquier_pc = self._tarjeta_de_cualquier_pc(opcion)
            else:
                boton = self._ficha_de_pc(opcion)
                grilla.addWidget(boton, fichas // PCS_POR_FILA, fichas % PCS_POR_FILA)
                fichas += 1
            boton.setCheckable(True)
            self.grupo_equipo.addButton(boton)
            self.botones_equipo.append((boton, opcion))
        capa.addLayout(consolas)
        if cualquier_pc is not None:
            capa.addSpacing(4)
            capa.addWidget(cualquier_pc)
        capa.addLayout(grilla)
        capa.addStretch()
        # Arranca en el primero, la PS5-1 (lo eligió el dueño el 2026-11-21, sabiendo
        # que una reserva de PC hecha sin mirar apartaría la consola: los bonos que
        # se ofrecen son los de la PS5, y eso avisa).
        self.botones_equipo[0][0].setChecked(True)
        self.grupo_equipo.buttonToggled.connect(self._al_elegir_equipo)
        return panel

    def _tarjeta_de_consola(self, opcion: dict) -> QPushButton:
        """Una PlayStation 5: tarjeta rosa grande con el joystick, el nombre, si está
        libre a esa hora y un tilde cuando es la elegida."""
        boton = QPushButton()
        aplicar_clase(boton, "tarjetaConsola")
        boton.setAccessibleName(opcion["nombre"])
        icono = QLabel()
        icono.setPixmap(pixmap_de("consola", 34, color_fuerte(TONO_DEL_EQUIPO[opcion["equipo"]]).name(), 1.6))
        titulo = QLabel(opcion["nombre"])
        titulo.setObjectName("tituloEquipo")
        boton.detalle = QLabel()
        boton.detalle.setObjectName("detalleEquipo")
        boton.tilde = QLabel("✓")
        boton.tilde.setObjectName("tildeEquipo")
        boton.tilde.setAlignment(Qt.AlignCenter)
        boton.tilde.setFixedSize(24, 24)
        boton.tilde.hide()
        boton.toggled.connect(boton.tilde.setVisible)
        _que_no_tape_el_clic(icono, titulo, boton.detalle, boton.tilde)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addStretch()
        textos.addWidget(titulo)
        textos.addWidget(boton.detalle)
        textos.addStretch()
        capa = QHBoxLayout(boton)
        capa.setContentsMargins(14, 8, 12, 8)
        capa.setSpacing(12)
        capa.addWidget(icono)
        capa.addLayout(textos, 1)
        capa.addWidget(boton.tilde, 0, Qt.AlignTop)
        return boton

    def _tarjeta_de_cualquier_pc(self, opcion: dict) -> QPushButton:
        boton = QPushButton()
        aplicar_clase(boton, "tarjetaCualquierPc")
        boton.setAccessibleName(opcion["nombre"])
        icono = QLabel()
        icono.setPixmap(pixmap_de("monitor", 22, color_fuerte(TONO_DEL_EQUIPO[opcion["equipo"]]).name(), 1.7))
        titulo = QLabel(opcion["nombre"].upper())
        titulo.setObjectName("tituloCualquierPc")
        detalle = QLabel("·  no aparta ninguna: cuando llega se le da la que esté libre")
        detalle.setObjectName("detalleCualquierPc")
        _que_no_tape_el_clic(icono, titulo, detalle)
        capa = QHBoxLayout(boton)
        capa.setContentsMargins(12, 4, 12, 4)
        capa.setSpacing(8)
        capa.addWidget(icono)
        capa.addWidget(titulo)
        capa.addWidget(detalle, 1)
        return boton

    def _ficha_de_pc(self, opcion: dict) -> QPushButton:
        boton = QPushButton(opcion["nombre"])
        aplicar_clase(boton, "fichaPc")
        boton.setProperty("tono", TONO_DEL_EQUIPO[opcion["equipo"]])
        boton.setAccessibleName(opcion["nombre"])
        return boton

    def _tarjeta_de_bono(self, bono: dict, tono: str) -> QPushButton:
        """Un bono: el puntito de elegido, el nombre, cuánto dura y el precio."""
        boton = QPushButton()
        aplicar_clase(boton, "tarjetaBono")
        boton.setProperty("tono", tono)
        boton.setCheckable(True)
        boton.setAccessibleName(bono["nombre"])
        boton.bono = bono
        boton.punto = QLabel("○")
        boton.punto.setObjectName("puntoBono")
        boton.punto.setProperty("tono", tono)
        nombre = QLabel(bono["nombre"])
        nombre.setObjectName("nombreBono")
        dura = QLabel(reservas_socios_repo.texto_de_horas(bono["minutos"]))
        dura.setObjectName("detalleBono")
        precio = QLabel(formato_pesos(bono["precio"]))
        precio.setObjectName("precioBono")
        _que_no_tape_el_clic(boton.punto, nombre, dura, precio)
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(nombre)
        textos.addWidget(dura)
        capa = QHBoxLayout(boton)
        capa.setContentsMargins(12, 6, 12, 6)
        capa.setSpacing(10)
        capa.addWidget(boton.punto)
        capa.addLayout(textos, 1)
        capa.addWidget(precio)
        return boton

    def _barra_de_cobro(self) -> QFrame:
        barra = QFrame()
        barra.setObjectName("barraCobro")
        self.etiqueta_resumen = QLabel()
        self.etiqueta_resumen.setObjectName("resumenReserva")
        self.etiqueta_cobras = QLabel()
        self.etiqueta_cobras.setObjectName("cobrasAhora")
        self.etiqueta_falta = QLabel()
        self.etiqueta_falta.setObjectName("faltaCuandoLlegue")
        fila = QHBoxLayout()
        fila.setSpacing(8)
        fila.addWidget(self.etiqueta_cobras)
        fila.addWidget(self.etiqueta_falta, 0, Qt.AlignBottom)
        fila.addStretch()
        textos = QVBoxLayout()
        textos.setSpacing(0)
        textos.addWidget(self.etiqueta_resumen)
        textos.addLayout(fila)
        boton_cancelar = tecla("CANCELAR", self.reject, "teclaBlanca")
        self.boton_cobrar = tecla("", self._cobrar, "teclaVerde")
        for boton in (boton_cancelar, self.boton_cobrar):
            boton.setObjectName("teclaGrandeReserva")
        capa = QHBoxLayout(barra)
        capa.setContentsMargins(16, 10, 12, 10)
        capa.setSpacing(10)
        capa.addLayout(textos, 1)
        capa.addWidget(boton_cancelar)
        capa.addWidget(self.boton_cobrar)
        return barra

    # ------------------------------------------------------------ lo elegido

    def _equipo(self) -> dict:
        for boton, opcion in self.botones_equipo:
            if boton.isChecked():
                return opcion
        return self.botones_equipo[0][1]

    def _bono(self):
        boton = self.grupo_bono.checkedButton()
        return boton.bono if boton is not None else None

    def _inicio(self):
        return _momento(self.campo_dia.date(), self.campo_hora.time())

    def elegir_equipo(self, nombre: str):
        """Toca el equipo que se llama `nombre` (lo usan las pruebas)."""
        for boton, opcion in self.botones_equipo:
            if opcion["nombre"] == nombre:
                boton.setChecked(True)
                return
        raise ValueError(f"No hay un equipo {nombre}")

    def elegir_bono(self, nombre: str):
        """Toca el bono que se llama `nombre` (lo usan las pruebas)."""
        for boton in self.grupo_bono.buttons():
            if boton.bono["nombre"] == nombre:
                boton.setChecked(True)
                return
        raise ValueError(f"No hay un bono {nombre}")

    # ------------------------------------------------------------ lo que cambia

    def _al_elegir_equipo(self, _boton, elegido: bool):
        if elegido:
            self._cargar_bonos()

    def _al_cambiar_la_hora(self, _=None):
        self._marcar_reservados()
        self._actualizar_monto()

    def _marcar_reservados(self):
        """Cada equipo dice si ya tiene una reserva a la hora elegida: las PS5 en su
        tarjeta ("libre a las 16:00" o "reservada · Santi"); las PCs, en gris con el
        nombre al pasar el mouse. Se puede tocar igual: al cobrar, el repo dice si de
        verdad se pisa."""
        momento = self._inicio()
        reservados = reservas_repo.reservados_a_esa_hora(momento)
        for boton, opcion in self.botones_equipo:
            cliente = reservados.get(reservas_repo.clave_del_equipo(opcion))
            if opcion["equipo"] == dominio.EQUIPO_RESERVA_PLAYSTATION:
                boton.detalle.setText(f"Reservada a las {momento:%H:%M} · {cliente}" if cliente
                                      else f"PlayStation 5  ·  libre a las {momento:%H:%M}")
                boton.detalle.setProperty("reservada", "true" if cliente else "false")
                _repintar(boton.detalle)
            elif boton.property("clase") == "fichaPc":
                boton.setProperty("reservada", "true" if cliente else "false")
                boton.setToolTip(f"Reservada a las {momento:%H:%M} para {cliente}" if cliente else "")
                _repintar(boton)

    def _cargar_bonos(self, _=None):
        """Los bonos del catálogo del equipo elegido (cada equipo cobra con el suyo),
        como tarjetas de su color; arranca elegido el primero."""
        equipo = self._equipo()
        tono = TONO_DEL_EQUIPO[equipo["equipo"]]
        for boton in self.grupo_bono.buttons():
            # setParent(None) antes de deleteLater: si no, sigue en la lista hasta que
            # vuelve el bucle de eventos (ver la trampa en docs/guia/PANTALLA.md).
            self.grupo_bono.removeButton(boton)
            boton.setParent(None)
            boton.deleteLater()
        for bono in reservas_repo.bonos_para(equipo["equipo"]):
            boton = self._tarjeta_de_bono(bono, tono)
            self.grupo_bono.addButton(boton)
            self.capa_bonos.insertWidget(self.capa_bonos.count() - 1, boton)
        self.titulo_bonos.setText(f"BONO  ·  {equipo['nombre'].upper()}")
        botones = self.grupo_bono.buttons()
        self.etiqueta_sin_bonos.setText(
            f"Todavía no hay bonos para {equipo['nombre']}: el Admin los crea en Configuración ADMIN."
        )
        self.etiqueta_sin_bonos.setVisible(not botones)
        if botones:
            botones[0].setChecked(True)
        self._actualizar_monto()

    def _al_elegir_bono(self, boton, elegido: bool):
        boton.punto.setText("●" if elegido else "○")
        boton.punto.setProperty("elegido", "true" if elegido else "false")
        _repintar(boton.punto)
        if elegido:
            self._actualizar_monto()

    def _monto(self) -> float:
        """Lo que paga ahora, según la opción elegida."""
        bono = self._bono()
        if bono is None:
            return 0.0
        if self.opcion_todo.isChecked():
            return round(bono["precio"], 2)
        if self.opcion_otro.isChecked():
            return round(self.spin_otro.value(), 2)
        return round(bono["precio"] / 2, 2)

    def _actualizar_monto(self, *_):
        """La barra de abajo (qué se reserva, cuánto se cobra ahora y cuánto falta),
        el botón Cobrar y el aviso (qué pasa si no viene) siguen a lo elegido."""
        bono = self._bono()
        equipo = self._equipo()
        precio = bono["precio"] if bono else 0.0
        self.fila_otro.setVisible(self.opcion_otro.isChecked())
        monto = self._monto()
        self.boton_cobrar.setText(f"✓  COBRAR {formato_pesos(monto)}")
        self.boton_cobrar.setEnabled(bono is not None)
        inicio = self._inicio()
        if bono is None:
            self.etiqueta_resumen.setText(f"{equipo['nombre']}  ·  {texto_dia_y_hora(inicio.isoformat())}")
            self.etiqueta_cobras.setText("Elegí un equipo que tenga bonos")
            self.etiqueta_falta.setText("")
            self.aviso.setText("")
            return
        fin = inicio + timedelta(minutes=bono["minutos"])
        self.etiqueta_resumen.setText(
            f"{equipo['nombre']}  ·  {texto_dia_y_hora(inicio.isoformat())} a {fin:%H:%M}  ·  {bono['nombre']}")
        self.etiqueta_cobras.setText(f"Cobrás ahora {formato_pesos(monto)}")
        paga_todo = monto >= round(precio, 2)
        self.etiqueta_falta.setText("·  paga todo" if paga_todo
                                    else f"·  falta {formato_pesos(round(precio - monto, 2))} cuando llegue")
        if paga_todo:
            self.aviso.setText(
                f"ⓘ  El precio queda fijo en {formato_pesos(precio)} aunque después cambie el bono. "
                "Paga todo: si no viene, queda \"A reprogramar\" para darle otro día (con cualquier PC "
                f"disponible), y vence a los {dominio.DIAS_PARA_REPROGRAMAR_RESERVA} días."
            )
        else:
            self.aviso.setText(
                f"ⓘ  El precio queda fijo en {formato_pesos(precio)} aunque después cambie el bono. "
                f"Cuando llegue se cobra lo que falta. Si no viene (o llega más de "
                f"{dominio.texto_tolerancia_reserva()} tarde), pierde la seña."
            )

    # ------------------------------------------------------------ cobrar

    @manejar_errores
    def _cobrar(self):
        cliente = self.campo_cliente.text().strip()
        if not cliente:
            mostrar_error(self, "Falta el cliente", "Escribí el nombre de quien reserva.")
            self.campo_cliente.setFocus()
            return
        bono = self._bono()
        if bono is None:
            mostrar_error(self, "Sin bono", "Elegí un equipo que tenga bonos.")
            return
        equipo = self._equipo()
        inicio = self._inicio()
        monto = self._monto()
        # Antes de cobrar: que no se cobre una reserva que después no se puede guardar.
        reservas_repo.revisar_reserva(equipo["equipo"], equipo["estacion_id"], bono["id"], inicio, monto,
                                      consola=equipo["consola"])
        pagos = cobrar(self, monto)
        if pagos is None:
            return
        self.reserva_id = reservas_repo.crear_reserva(
            self.usuario["id"], cliente, self.campo_celular.text(), equipo["equipo"], equipo["estacion_id"],
            bono["id"], inicio, monto, pagos, consola=equipo["consola"],
        )
        mostrar_info(
            self, "Reserva tomada",
            f"Reserva Nº {self.reserva_id}: {cliente}, {equipo['nombre']}, {texto_dia_y_hora(inicio.isoformat())}.\n"
            f"{bono['nombre']} · cobraste {formato_pesos(monto)}"
            + ("." if monto >= bono["precio"] else f", falta {formato_pesos(bono['precio'] - monto)}."),
        )
        self.accept()
