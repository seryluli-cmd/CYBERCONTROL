"""
horarios_personal_window.py
============================
HORARIOS DEL PERSONAL (pedido del dueño, 2026-11-19; eligió la maqueta B de
PROPUESTA_HORARIOS): arriba, una tarjeta por empleada con cuántos días llegó
temprano, cuántos llegó tarde, cuántos se fue antes y el saldo en grande ("LE
DEBÉS 1 h 20 min" en verde, "TE DEBE 35 min" en rojo); abajo, el detalle día
por día de la tarjeta elegida. Se abre desde Administrar Kiosko > Caja y
personal, solo el Administrador.

Solo dibuja: de dónde sale cada hora y cada minuto está en
repositories/horarios_repo.py.
"""

from datetime import date, timedelta

from PySide6.QtCore import QDate, Qt
from PySide6.QtGui import QBrush, QColor
from PySide6.QtWidgets import QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QTableWidgetItem, QVBoxLayout, QWidget

from control_pcs.ui.dibujos_de_ventana import pixmap_de
from repositories import horarios_repo
from ui.piezas_ventana import (
    TONO_AZUL, TONO_GRIS, agregar_pastilla, cabecera_oscura, panel_blanco, panel_de_tabla, pastilla_clara,
    pie_de_ventana, tecla, titulo_de_seccion,
)
from ui.utils import (
    crear_selector_de_fecha, crear_tabla, encadenar_enter, fecha_iso, hoy_del_local, manejar_errores,
    sin_boton_por_defecto,
)

TARJETAS_POR_FILA = 5

# Los tonos de la hoja de estilos (tarjetaHorario, saldoDelDetalle): verde = a favor
# de ella, rojo = en contra.
TONO_A_FAVOR = "verde"
TONO_EN_CONTRA = "rojo"
TONO_A_MANO = "gris"
VERDE = QColor("#1E9E50")
ROJO = QColor("#D93A45")
GRIS = QColor("#8A94A6")

COLUMNAS = ["FECHA", "TURNO", "HORARIO", "LLEGÓ", "AL LLEGAR", "SE FUE", "AL IRSE", "DEL DÍA", "QUÉ PASÓ"]
ANCHOS = [105, 150, 120, 70, 120, 70, 140, 100]
COLUMNA_AL_IRSE = 6
DIAS = ("Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom")
MESES = ("ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO", "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE",
         "NOVIEMBRE", "DICIEMBRE")

AYUDA = ("Llegada = cuando abrió su caja (o la recibió de quien la cubría). Salida = cuando la cerró (o la "
         "entregó a quien llegó). Si la caja la cerró el programa u otra persona, la salida queda \"sin dato\" "
         "y no suma ni resta. Tocá una tarjeta para ver el detalle de esa persona.")


def duracion(minutos: int) -> str:
    """80 → "1 h 20 min"; sin el signo (lo pone quien la usa)."""
    horas, resto = divmod(abs(minutos), 60)
    if horas and resto:
        return f"{horas} h {resto} min"
    return f"{horas} h" if horas else f"{resto} min"


def frase_del_saldo(saldo: int) -> tuple:
    """(lo que se lee, su tono) del saldo de una empleada, mirado desde el dueño:
    positivo = el local le debe tiempo a ella; negativo = ella le debe al local."""
    if saldo > 0:
        return f"LE DEBÉS {duracion(saldo)}", TONO_A_FAVOR
    if saldo < 0:
        return f"TE DEBE {duracion(saldo)}", TONO_EN_CONTRA
    return "ESTÁN A MANO", TONO_A_MANO


def texto_al_llegar(minutos: int) -> tuple:
    if minutos > 0:
        return f"{minutos} min antes", VERDE
    if minutos < 0:
        return f"{duracion(minutos)} tarde", ROJO
    return "a horario", GRIS


def texto_al_irse(minutos: int) -> tuple:
    if minutos > 0:
        return f"se quedó {duracion(minutos)}", VERDE
    if minutos < 0:
        return f"{duracion(minutos)} antes", ROJO
    return "a horario", GRIS


def texto_del_dia(minutos: int) -> tuple:
    if minutos > 0:
        return f"+{duracion(minutos)}", VERDE
    if minutos < 0:
        return f"−{duracion(minutos)}", ROJO
    return "0", GRIS


def nombre_del_periodo(desde: date, hasta: date, hoy: date) -> str:
    """La pastilla de la cabecera: el mes entero ("NOVIEMBRE 2026", también el mes en
    curso hasta hoy) o las dos puntas ("01/11 AL 15/11")."""
    fin_de_mes = (desde.replace(day=28) + timedelta(days=4)).replace(day=1) - timedelta(days=1)
    if desde.day == 1 and hasta.month == desde.month and hasta.year == desde.year and hasta in (fin_de_mes, hoy):
        return f"{MESES[desde.month - 1]} {desde.year}"
    return f"{desde:%d/%m} AL {hasta:%d/%m}"


def _repintar(widget):
    """Que Qt vuelva a mirar la hoja de estilos después de cambiar una propiedad."""
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def _etiqueta(texto: str, nombre: str, tono: str = None) -> QLabel:
    etiqueta = QLabel(texto)
    etiqueta.setObjectName(nombre)
    if tono:
        etiqueta.setProperty("tono", tono)
    return etiqueta


class TarjetaDeEmpleada(QFrame):
    """La tarjeta de una empleada (maqueta B): su nombre, turno y días, los tres
    números y el saldo. Al tocarla, avisa a `al_elegir` con su usuario_id."""

    def __init__(self, empleada: dict, al_elegir):
        super().__init__()
        self.usuario_id = empleada["usuario_id"]
        self._al_elegir = al_elegir
        self.setObjectName("tarjetaHorario")
        self.setProperty("elegida", "false")
        self.setAccessibleName(empleada["nombre"])
        self.setCursor(Qt.PointingHandCursor)

        capa = QVBoxLayout(self)
        capa.setContentsMargins(16, 12, 16, 14)
        capa.setSpacing(6)
        capa.addWidget(_etiqueta(empleada["nombre"].upper(), "nombreHorario"))
        dias = "1 día trabajado" if empleada["dias"] == 1 else f"{empleada['dias']} días trabajados"
        capa.addWidget(_etiqueta(f"{empleada['turno_habitual']} · {dias}", "detalleHorario"))

        numeros = QHBoxLayout()
        numeros.setSpacing(4)
        self.numeros = {}
        for clave, rotulo, tono in (
            ("llego_temprano", "llegó\ntemprano", TONO_A_FAVOR),
            ("llego_tarde", "llegó\ntarde", TONO_EN_CONTRA),
            ("se_fue_antes", "se fue\nantes", TONO_EN_CONTRA),
        ):
            valor = empleada[clave]
            numero = _etiqueta(str(valor), "numeroHorario", tono if valor else None)
            self.numeros[clave] = numero
            columna = QVBoxLayout()
            columna.setSpacing(0)
            columna.addWidget(numero, 0, Qt.AlignHCenter)
            columna.addWidget(_etiqueta(rotulo, "rotuloHorario"), 0, Qt.AlignHCenter)
            numeros.addLayout(columna)
        capa.addLayout(numeros)

        texto, tono = frase_del_saldo(empleada["saldo"])
        self.saldo = _etiqueta(texto, "saldoHorario", tono)
        self.saldo.setAlignment(Qt.AlignCenter)
        capa.addWidget(self.saldo)

    def marcar(self, elegida: bool):
        self.setProperty("elegida", "true" if elegida else "false")
        _repintar(self)

    def mousePressEvent(self, evento):
        if evento.button() == Qt.LeftButton:
            self._al_elegir(self.usuario_id)
        super().mousePressEvent(evento)


class HorariosPersonalWindow(QDialog):
    """HORARIOS DEL PERSONAL, para el Administrador (ver el docstring del archivo)."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.empleadas = []
        self.elegida = None
        self.tarjetas = {}
        self.setWindowTitle("Horarios del personal")
        self.resize(1400, 900)
        self._armar_interfaz()
        self._poner_este_mes()

    # ------------------------------------------------------------------
    # Armado
    # ------------------------------------------------------------------
    def _armar_interfaz(self):
        capa = QVBoxLayout(self)
        capa.setContentsMargins(16, 16, 16, 16)
        capa.setSpacing(10)

        cabecera = cabecera_oscura(
            "", "HORARIOS DEL PERSONAL",
            "Cuándo abrió y cerró su caja cada empleada, comparado con el horario de su turno",
        )
        # Dibujado: hay emojis que el Windows del mostrador no trae.
        cabecera.icono.setPixmap(pixmap_de("reloj", 30, "#EAF4FF", 1.6))
        self.pastilla_periodo = agregar_pastilla(cabecera, "", TONO_AZUL)
        capa.addWidget(cabecera)
        capa.addWidget(self._fila_del_periodo())

        self.zona_tarjetas = QWidget()
        self.grilla_tarjetas = QGridLayout(self.zona_tarjetas)
        self.grilla_tarjetas.setContentsMargins(0, 0, 0, 0)
        self.grilla_tarjetas.setSpacing(12)
        for columna in range(TARJETAS_POR_FILA):
            self.grilla_tarjetas.setColumnStretch(columna, 1)
        capa.addWidget(self.zona_tarjetas)
        self.sin_nadie = pie_de_ventana("Nadie abrió una caja en esas fechas.")
        capa.addWidget(self.sin_nadie)

        titulo = QHBoxLayout()
        self.titulo_detalle = titulo_de_seccion("")
        titulo.addWidget(self.titulo_detalle)
        titulo.addStretch()
        self.saldo_detalle = _etiqueta("", "saldoDelDetalle")
        titulo.addWidget(self.saldo_detalle)
        capa.addSpacing(4)
        capa.addLayout(titulo)

        self.tabla = crear_tabla(COLUMNAS, estirar=len(COLUMNAS) - 1, por_filas=True, una_sola=True)
        for columna, ancho in enumerate(ANCHOS):
            self.tabla.setColumnWidth(columna, ancho)
        capa.addWidget(panel_de_tabla(self.tabla), 1)
        capa.addWidget(pie_de_ventana(AYUDA))
        sin_boton_por_defecto(self)

    def _fila_del_periodo(self) -> QFrame:
        panel, capa = panel_blanco()
        capa.setContentsMargins(16, 10, 16, 10)
        fila = QHBoxLayout()
        fila.setSpacing(10)
        fila.addWidget(titulo_de_seccion("Período"))
        fila.addWidget(tecla("ESTE MES", self._poner_este_mes))
        fila.addWidget(tecla("MES ANTERIOR", self._poner_mes_anterior))
        fila.addSpacing(16)
        hoy = hoy_del_local()
        self.fecha_desde = crear_selector_de_fecha(QDate(hoy.year(), hoy.month(), 1))
        self.fecha_hasta = crear_selector_de_fecha(hoy)
        fila.addWidget(titulo_de_seccion("Desde"))
        fila.addWidget(self.fecha_desde)
        fila.addWidget(titulo_de_seccion("Hasta"))
        fila.addWidget(self.fecha_hasta)
        fila.addWidget(tecla("BUSCAR", self._cargar, "teclaAzul"))
        encadenar_enter(self.fecha_desde, self.fecha_hasta, accion_final=self._cargar)
        fila.addStretch()
        self.margen = _etiqueta("", "margenHorario")
        fila.addWidget(self.margen)
        capa.addLayout(fila)
        return panel

    # ------------------------------------------------------------------
    # Período
    # ------------------------------------------------------------------
    def _poner_este_mes(self, *_):
        # Se recalcula al apretar: la ventana puede haber quedado abierta de un día para otro.
        hoy = hoy_del_local()
        self.fecha_desde.setDate(QDate(hoy.year(), hoy.month(), 1))
        self.fecha_hasta.setDate(hoy)
        self._cargar()

    def _poner_mes_anterior(self, *_):
        hoy = hoy_del_local()
        primero_de_este = QDate(hoy.year(), hoy.month(), 1)
        self.fecha_desde.setDate(primero_de_este.addMonths(-1))
        self.fecha_hasta.setDate(primero_de_este.addDays(-1))
        self._cargar()

    # ------------------------------------------------------------------
    # Datos
    # ------------------------------------------------------------------
    @manejar_errores
    def _cargar(self, *_):
        desde, hasta = fecha_iso(self.fecha_desde.date()), fecha_iso(self.fecha_hasta.date())
        datos = horarios_repo.horarios_del_personal(self.usuario["id"], desde, hasta)
        hoy = hoy_del_local()
        self.pastilla_periodo.setText(nombre_del_periodo(
            date.fromisoformat(desde), date.fromisoformat(hasta), date(hoy.year(), hoy.month(), hoy.day())))
        self.margen.setText(f"Hasta {datos['margen']} minutos antes o después cuenta como \"a horario\"")
        self.empleadas = datos["empleadas"]
        self._poner_tarjetas()
        ids = [empleada["usuario_id"] for empleada in self.empleadas]
        self.elegir(self.elegida if self.elegida in ids else (ids[0] if ids else None))

    def _poner_tarjetas(self):
        for tarjeta in self.tarjetas.values():
            # Sin padre al instante: con deleteLater solo, la vieja se seguía viendo
            # detrás de la nueva hasta que Qt la borraba.
            self.grilla_tarjetas.removeWidget(tarjeta)
            tarjeta.setParent(None)
            tarjeta.deleteLater()
        self.tarjetas = {}
        for numero, empleada in enumerate(self.empleadas):
            tarjeta = TarjetaDeEmpleada(empleada, self.elegir)
            self.tarjetas[empleada["usuario_id"]] = tarjeta
            self.grilla_tarjetas.addWidget(tarjeta, numero // TARJETAS_POR_FILA, numero % TARJETAS_POR_FILA)
        self.zona_tarjetas.setVisible(bool(self.empleadas))
        self.sin_nadie.setVisible(not self.empleadas)

    def elegir(self, usuario_id):
        """Marca la tarjeta de `usuario_id` y muestra su detalle (None = ninguna)."""
        self.elegida = usuario_id
        for clave, tarjeta in self.tarjetas.items():
            tarjeta.marcar(clave == usuario_id)
        empleada = next((e for e in self.empleadas if e["usuario_id"] == usuario_id), None)
        self.tabla.setRowCount(0)
        if empleada is None:
            self.titulo_detalle.setText("")
            self.saldo_detalle.setText("")
            return
        self.titulo_detalle.setText(f"{empleada['nombre']} — día por día".upper())
        texto, tono = frase_del_saldo(empleada["saldo"])
        self.saldo_detalle.setText(texto)
        self.saldo_detalle.setProperty("tono", tono)
        _repintar(self.saldo_detalle)
        for dia in empleada["detalle"]:
            self._agregar_dia(dia)

    def _agregar_dia(self, dia: dict):
        fila = self.tabla.rowCount()
        self.tabla.insertRow(fila)
        fecha = dia["dia"]
        celdas = [
            (f"{DIAS[fecha.weekday()]} {fecha:%d/%m}", None, True),
            (dia["turno_label"], None, False),
            (f"{dia['inicio']:%H:%M} a {dia['fin']:%H:%M}", GRIS, False),
            (f"{dia['llegada']:%H:%M}", None, True),
            (*texto_al_llegar(dia["al_llegar"]), False),
            ("—" if dia["salida"] is None else f"{dia['salida']:%H:%M}", None, True),
            (*texto_al_irse(dia["al_irse"] or 0), False),
            (*texto_del_dia(dia["del_dia"]), True),
            (dia["que_paso"], GRIS, False),
        ]
        for columna, (texto, color, negrita) in enumerate(celdas):
            celda = QTableWidgetItem(texto)
            if color is not None:
                celda.setForeground(QBrush(color))
            if negrita:
                fuente = celda.font()
                fuente.setBold(True)
                celda.setFont(fuente)
            self.tabla.setItem(fila, columna, celda)
        if dia["al_irse"] is None:
            # Sin salida: o todavía está, o no se sabe (la caja la cerró el programa u otra).
            texto = "TRABAJANDO" if dia["en_curso"] else "SIN DATO"
            self.tabla.item(fila, COLUMNA_AL_IRSE).setText("")
            caja = QWidget()
            capa = QHBoxLayout(caja)
            capa.setContentsMargins(6, 4, 6, 4)
            capa.addWidget(pastilla_clara(texto, TONO_AZUL if dia["en_curso"] else TONO_GRIS, chica=True))
            capa.addStretch()
            self.tabla.setCellWidget(fila, COLUMNA_AL_IRSE, caja)
