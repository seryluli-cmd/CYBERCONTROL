"""
pcs_programas_dialogo.py
=========================
Dos ventanas del clic derecho de una PC en Control de PCs (pedido del dueño, 2026-10-22; eligió
la maqueta), para cualquier operador:

- `DialogoProgramas`, "📋 Programas y estado...": arriba, cómo está la PC (disco, memoria,
  procesador con su temperatura, cuánto hace que está prendida y su versión del Cliente PC); a la
  izquierda, sus programas abiertos, con el que se trabó en rojo ("NO RESPONDE"), para cerrarlo a
  la fuerza; a la derecha, los íconos de su escritorio, para abrir uno.
- `DialogoMantenimiento`, "🛠️ Hacer mantenimiento (15 min)" / "Terminar mantenimiento": manda la
  orden y muestra lo que contesta la PC.

Todo viaja como comandos que el Cliente PC recoge en su consulta de cada 5 s (ver
programas_pc_repo, mantenimiento_pc_repo y comandos_pc_repo): cada pedido tarda unos segundos, y
mientras tanto la ventana lo dice y no deja mandar otro. Si la PC avisó un Cliente PC anterior a
la V1.6, no se manda nada: no lo entendería.
"""

from datetime import datetime

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QDialog, QFrame, QGridLayout, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem, QVBoxLayout,
)

import dominio
from control_pcs.repositories import (
    actualizacion_cliente_repo, comandos_pc_repo, mantenimiento_pc_repo, programas_pc_repo,
)
from control_pcs.ui.pcs_comandos_dialogos import SEGUNDOS_ESPERA_CAPTURA
from ui.utils import aplicar_clase, confirmar, crear_tabla, formato_tiempo, manejar_errores, sin_boton_por_defecto

COLOR_ALERTA = "#C62828"

MENSAJE_SIN_RESPUESTA = ("No llegó respuesta a tiempo: revisá que la PC esté prendida y conectada, "
                         "o probá de nuevo.")

# Un disco con menos de esta parte libre se ve en rojo.
PARTE_LIBRE_MINIMA = 0.1


def texto_falta_version(estacion) -> str:
    """Por qué no se le manda nada a una PC con un Cliente PC viejo."""
    version = actualizacion_cliente_repo.nombre_de_version(
        estacion["numero_version_cliente"] if "numero_version_cliente" in estacion.keys() else None)
    tiene = f"tiene el Cliente PC {version}" if version else "tiene un Cliente PC viejo"
    return (f"{estacion['nombre']} {tiene}: esto necesita la V{dominio.VERSION_CLIENTE_PROGRAMAS} o más "
            "nueva. Hay que actualizarla (Config ADMIN → Gestionar Estaciones → Actualizar el Cliente PC).")


def _gb(cantidad_de_bytes: int) -> str:
    """"9,1 GB" o "465 GB", en las mismas unidades que muestra Windows."""
    valor = cantidad_de_bytes / 1024 ** 3
    if valor < 10:
        return f"{valor:.1f}".replace(".", ",") + " GB"
    return f"{round(valor):,}".replace(",", ".") + " GB"


def _texto_prendida(segundos: int) -> str:
    """Cuánto hace que está prendida: "3h 12m", o "2 días 5 h" pasado el día."""
    dias, resto = divmod(segundos, 86400)
    if not dias:
        return formato_tiempo(segundos)
    return f"{dias} {'día' if dias == 1 else 'días'} {resto // 3600} h"


def _texto_hace(segundos: int) -> str:
    if segundos < 60:
        return f"{segundos} {'segundo' if segundos == 1 else 'segundos'}"
    minutos = segundos // 60
    return f"{minutos} {'minuto' if minutos == 1 else 'minutos'}"


class _Recuadro(QFrame):
    """Uno de los cuatro datos de arriba: un título chico, el valor grande y un detalle."""

    def __init__(self, titulo: str):
        super().__init__()
        self.setFrameShape(QFrame.StyledPanel)
        self.etiqueta_titulo = QLabel(titulo)
        self.etiqueta_titulo.setStyleSheet("color: #666666; font-size: 11px;")
        self.etiqueta_valor = QLabel("—")
        self.etiqueta_detalle = QLabel("")
        self.etiqueta_detalle.setStyleSheet("color: #666666; font-size: 11px;")
        self.etiqueta_detalle.setWordWrap(True)
        caja = QVBoxLayout(self)
        caja.setContentsMargins(10, 6, 10, 6)
        for etiqueta in (self.etiqueta_titulo, self.etiqueta_valor, self.etiqueta_detalle):
            caja.addWidget(etiqueta)
        self.poner("—", "")

    def poner(self, valor: str, detalle: str, titulo: str = None, alerta: bool = False):
        if titulo is not None:
            self.etiqueta_titulo.setText(titulo)
        self.etiqueta_valor.setText(valor)
        color = f" color: {COLOR_ALERTA};" if alerta else ""
        self.etiqueta_valor.setStyleSheet(f"font-size: 17px; font-weight: bold;{color}")
        self.etiqueta_detalle.setText(detalle)


class DialogoProgramas(QDialog):
    """"Programas y estado" de una PC (ver el docstring del módulo)."""

    def __init__(self, estacion, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Programas y estado — {estacion['nombre']}")
        self.resize(860, 560)
        # Lo que se está esperando de la PC: {"id", "al_llegar", "despues", "segundos"}, o None.
        self._espera = None
        self._aviso = ""
        self._recibida = None
        self._armar_interfaz()

        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._cada_segundo)
        self._timer.start()

        if programas_pc_repo.le_falta_la_version(estacion):
            self._aviso = texto_falta_version(estacion)
            self._habilitar(False)
            self.boton_actualizar.setEnabled(False)
            self._mostrar_aviso()
        else:
            self._pedir_info()

    # -- armado ---------------------------------------------------------------

    def _armar_interfaz(self):
        self.recuadro_disco = _Recuadro("Disco C:")
        self.recuadro_memoria = _Recuadro("Memoria")
        self.recuadro_procesador = _Recuadro("Procesador")
        self.recuadro_prendida = _Recuadro("Prendida hace")
        fila_estado = QGridLayout()
        for columna, recuadro in enumerate((self.recuadro_disco, self.recuadro_memoria,
                                            self.recuadro_procesador, self.recuadro_prendida)):
            fila_estado.addWidget(recuadro, 0, columna)

        self.tabla_programas = crear_tabla(["Programa", "Estado"], estirar=0, por_filas=True, una_sola=True)
        self.tabla_programas.setColumnWidth(1, 150)
        self.boton_cerrar_programa = QPushButton("Cerrar el programa elegido")
        aplicar_clase(self.boton_cerrar_programa, "peligro")
        self.boton_cerrar_programa.clicked.connect(self._cerrar_elegido)

        self.tabla_iconos = crear_tabla(["Íconos del escritorio de la PC"], estirar=0, por_filas=True, una_sola=True)
        self.tabla_iconos.cellDoubleClicked.connect(lambda _fila, _columna: self._abrir_elegido())
        self.boton_abrir = QPushButton("Abrir el elegido")
        aplicar_clase(self.boton_abrir, "primario")
        self.boton_abrir.clicked.connect(self._abrir_elegido)

        izquierda = QVBoxLayout()
        izquierda.addWidget(self._titulo("Programas abiertos"))
        izquierda.addWidget(self.tabla_programas, 1)
        izquierda.addWidget(self.boton_cerrar_programa)
        derecha = QVBoxLayout()
        derecha.addWidget(self._titulo("Abrir un programa"))
        derecha.addWidget(self.tabla_iconos, 1)
        derecha.addWidget(self.boton_abrir)
        columnas = QHBoxLayout()
        columnas.addLayout(izquierda, 3)
        columnas.addSpacing(12)
        columnas.addLayout(derecha, 2)

        self.etiqueta_estado = QLabel("")
        self.etiqueta_estado.setWordWrap(True)
        self.boton_actualizar = QPushButton("🔄 Actualizar")
        self.boton_actualizar.clicked.connect(lambda: self._pedir_info())
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        abajo = QHBoxLayout()
        abajo.addWidget(self.etiqueta_estado, 1)
        abajo.addWidget(self.boton_actualizar)
        abajo.addWidget(boton_cerrar)

        layout = QVBoxLayout(self)
        layout.addLayout(fila_estado)
        layout.addSpacing(8)
        layout.addLayout(columnas, 1)
        layout.addLayout(abajo)
        sin_boton_por_defecto(self)

    @staticmethod
    def _titulo(texto: str) -> QLabel:
        etiqueta = QLabel(texto)
        etiqueta.setStyleSheet("font-weight: bold; font-size: 13px;")
        return etiqueta

    # -- esperar a la PC ------------------------------------------------------

    def _esperar(self, comando_id: int, al_llegar, mientras: str, despues: str = ""):
        """Espera lo que conteste la PC al comando `comando_id` y se lo pasa a `al_llegar`.
        `mientras` se ve mientras tanto; `despues` queda a la vista cuando llega."""
        self._espera = {"id": comando_id, "al_llegar": al_llegar, "despues": despues, "segundos": 0}
        self._aviso = mientras
        self._habilitar(False)
        self._mostrar_aviso()

    def _cada_segundo(self):
        espera = self._espera
        if espera is not None:
            espera["segundos"] += 1
            fila = comandos_pc_repo.obtener_comando(espera["id"])
            if fila is not None and fila["resultado"]:
                self._espera = None
                self._aviso = espera["despues"]
                self._habilitar(True)
                espera["al_llegar"](fila["resultado"])
            elif espera["segundos"] >= SEGUNDOS_ESPERA_CAPTURA:
                self._espera = None
                self._aviso = MENSAJE_SIN_RESPUESTA
                self._habilitar(True)
        self._mostrar_aviso()

    def _mostrar_aviso(self):
        partes = [self._aviso] if self._aviso else []
        if self._recibida is not None and self._espera is None:
            hace = int((datetime.now() - self._recibida).total_seconds())
            partes.append(f"Datos de hace {_texto_hace(max(0, hace))}.")
        self.etiqueta_estado.setText(" ".join(partes))

    def _habilitar(self, si: bool):
        for boton in (self.boton_cerrar_programa, self.boton_abrir, self.boton_actualizar):
            boton.setEnabled(si)

    def done(self, resultado):
        self._timer.stop()
        super().done(resultado)

    def closeEvent(self, evento):
        self._timer.stop()
        super().closeEvent(evento)

    # -- pedir y mostrar ------------------------------------------------------

    @manejar_errores
    def _pedir_info(self, despues: str = ""):
        comando_id = programas_pc_repo.pedir_info(self.estacion["id"])
        mientras = f"{despues} Actualizando la lista..." if despues else "Pidiendo los datos a la PC..."
        self._esperar(comando_id, self._llego_info, mientras, despues)

    def _llego_info(self, resultado: str):
        try:
            info = programas_pc_repo.leer_info(resultado)
        except ValueError as error:
            self._aviso = f"La PC contestó con un error: {error}"
            return
        self._recibida = datetime.now()
        self._mostrar_estado(info["estado"])
        self._mostrar_programas(info["programas"])
        self._mostrar_iconos(info["iconos"])

    def _mostrar_estado(self, estado: dict):
        discos = estado["discos"]
        if discos:
            principal = next((disco for disco in discos if disco["unidad"].upper() == "C:"), discos[0])
            otros = [f"{disco['unidad']} {_gb(disco['libre'])} libres" for disco in discos if disco is not principal]
            detalle = " · ".join([f"de {_gb(principal['total'])}"] + otros)
            self.recuadro_disco.poner(
                f"{_gb(principal['libre'])} libres", detalle, titulo=f"Disco {principal['unidad']}",
                alerta=principal["libre"] < principal["total"] * PARTE_LIBRE_MINIMA,
            )
        else:
            self.recuadro_disco.poner("—", "No se pudo leer")
        memoria = estado["memoria"]
        if memoria:
            self.recuadro_memoria.poner(f"{_gb(memoria['usada'])} en uso", f"de {_gb(memoria['total'])}")
        else:
            self.recuadro_memoria.poner("—", "No se pudo leer")
        if estado["temp_cpu"] is not None:
            temperatura = f"{estado['temp_cpu']} °C"
        elif estado["temp_gpu"] is not None:
            temperatura = f"Placa de video: {estado['temp_gpu']} °C"
        else:
            temperatura = "Sin temperatura"
        self.recuadro_procesador.poner("—" if estado["cpu"] is None else f"{estado['cpu']} %", temperatura)
        prendida = "—" if estado["prendida"] is None else _texto_prendida(estado["prendida"])
        version = f"Cliente PC V{estado['version']}" if estado["version"] else ""
        self.recuadro_prendida.poner(prendida, version)

    def _mostrar_programas(self, programas: list):
        elegido = self._programa_elegido()
        tabla = self.tabla_programas
        tabla.setRowCount(0)
        # Los que no responden, primero: son los que se vienen a buscar.
        for programa in sorted(programas, key=lambda p: not p["no_responde"]):
            fila = tabla.rowCount()
            tabla.insertRow(fila)
            nombre = QTableWidgetItem(programa["titulo"] or programa["exe"])
            nombre.setData(Qt.UserRole, programa)
            nombre.setToolTip(programa["exe"])
            tabla.setItem(fila, 0, nombre)
            if programa["no_responde"]:
                estado = QTableWidgetItem("⚠️ NO RESPONDE")
                estado.setForeground(QColor(COLOR_ALERTA))
                fuente = estado.font()
                fuente.setBold(True)
                estado.setFont(fuente)
            else:
                estado = QTableWidgetItem("Funciona")
            tabla.setItem(fila, 1, estado)
            if elegido is not None and programa["pid"] == elegido["pid"]:
                tabla.selectRow(fila)

    def _mostrar_iconos(self, iconos: list):
        elegido = self._icono_elegido()
        tabla = self.tabla_iconos
        tabla.setRowCount(0)
        for nombre in iconos:
            fila = tabla.rowCount()
            tabla.insertRow(fila)
            tabla.setItem(fila, 0, QTableWidgetItem(nombre))
            if nombre == elegido:
                tabla.selectRow(fila)

    def _programa_elegido(self):
        fila = self.tabla_programas.currentRow()
        if fila < 0 or not self.tabla_programas.selectionModel().isRowSelected(fila):
            return None
        return self.tabla_programas.item(fila, 0).data(Qt.UserRole)

    def _icono_elegido(self):
        fila = self.tabla_iconos.currentRow()
        if fila < 0 or not self.tabla_iconos.selectionModel().isRowSelected(fila):
            return None
        return self.tabla_iconos.item(fila, 0).text()

    # -- acciones -------------------------------------------------------------

    @manejar_errores
    def _cerrar_elegido(self):
        programa = self._programa_elegido()
        if programa is None:
            self._aviso = "Elegí un programa de la lista de la izquierda."
            self._mostrar_aviso()
            return
        nombre = programa["titulo"] or programa["exe"]
        if not confirmar(
            self, "Cerrar programa",
            f"¿Cerrar «{nombre}» en {self.estacion['nombre']}?\n\n"
            "Se cierra a la fuerza, como desde el Administrador de tareas: "
            "se pierde lo que no estaba guardado.",
        ):
            return
        self._esperar(programas_pc_repo.cerrar_programa(self.estacion["id"], programa), self._llego_respuesta,
                      f"Cerrando «{nombre}»...")

    @manejar_errores
    def _abrir_elegido(self):
        if self._espera is not None:
            return
        icono = self._icono_elegido()
        if icono is None:
            self._aviso = "Elegí un ícono de la lista de la derecha."
            self._mostrar_aviso()
            return
        self._esperar(programas_pc_repo.abrir_programa(self.estacion["id"], icono), self._llego_respuesta,
                      f"Abriendo «{icono}»...")

    def _llego_respuesta(self, resultado: str):
        """Lo que contestó la PC al cerrar o abrir: se muestra y se vuelve a pedir la lista."""
        ok, texto = programas_pc_repo.leer_respuesta(resultado)
        self._pedir_info(despues=texto if ok else f"No se pudo: {texto}")


class DialogoMantenimiento(QDialog):
    """Manda empezar o terminar el mantenimiento de una PC (`orden`, uno de
    dominio.ORDENES_MANTENIMIENTO) y muestra lo que contesta. Quien lo mandó (`usuario`) queda
    anotado para Actividad reciente (ver mantenimiento_pc_repo)."""

    def __init__(self, estacion, orden: str, usuario, parent=None):
        super().__init__(parent)
        self.estacion = estacion
        self.setWindowTitle(f"Mantenimiento — {estacion['nombre']}")
        self.resize(400, 160)
        self.etiqueta_estado = QLabel("Esperando que la PC responda...")
        self.etiqueta_estado.setWordWrap(True)
        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        layout = QVBoxLayout(self)
        layout.addWidget(self.etiqueta_estado, 1)
        layout.addWidget(boton_cerrar)
        sin_boton_por_defecto(self)

        self._comando_id = None
        self._segundos = 0
        self._timer = QTimer(self)
        self._timer.setInterval(1000)
        self._timer.timeout.connect(self._revisar)
        if programas_pc_repo.le_falta_la_version(estacion):
            self.etiqueta_estado.setText(texto_falta_version(estacion))
            return
        self._comando_id = mantenimiento_pc_repo.ordenar(estacion["id"], orden, usuario)
        self._timer.start()

    def _revisar(self):
        self._segundos += 1
        fila = comandos_pc_repo.obtener_comando(self._comando_id)
        if fila is not None and fila["resultado"]:
            self._timer.stop()
            ok, texto = programas_pc_repo.leer_respuesta(fila["resultado"])
            self.etiqueta_estado.setText(f"Listo: {texto}" if ok else f"No se pudo: {texto}")
        elif self._segundos >= SEGUNDOS_ESPERA_CAPTURA:
            self._timer.stop()
            self.etiqueta_estado.setText(MENSAJE_SIN_RESPUESTA)

    def done(self, resultado):
        self._timer.stop()
        super().done(resultado)
