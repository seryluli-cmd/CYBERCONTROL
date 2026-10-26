"""
control_cierres_window.py
==========================
Las pantallas para controlar los cierres después (Admin, o una Empleada con
`permiso_control_cierres`):
- ControlCierresWindow: historial de cierres (uno por caja cerrada) con
  los totales de cada sobre, y para cargar lo que realmente se contó (solo
  el Admin).
- DialogoDetalleCierre: el detalle de un cierre puntual -- el cierre como
  lo mostraba la pantalla Cierre de Turno (también el forzoso, que nadie
  vio) y venta por venta (ver turnos_repo.detalle_cierre), para entender
  cómo se llegó a esos totales sin tener que ir a buscarlas por separado en
  Consulta de Ventas.

Se separaron de caja_window.py el 2026-10-18, cuando las cajas con número le
sumaron columnas (caja, responsable, apertura, cómo se cerró) y ese archivo
pasaba las 600 líneas (CLAUDE.md, regla 12). caja_window las reexporta.
"""

from datetime import datetime

from PySide6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QLabel, QPushButton, QTableWidgetItem,
    QWidget, QListWidget,
)
from PySide6.QtCore import Qt

import dominio
from admin_remoto import modo as modo_remoto
from turnos import MINUTOS_AVISO_ANTES_DEL_FIN, MINUTOS_PARA_CIERRE_FORZOSO, etiqueta_turno
from repositories import envio_pwa_repo, turnos_repo
from ui.detalle_venta import VentanaConDetalleDeVenta, crear_tabla_detalle_venta
from ui.envio_pwa_progreso import DialogoEnviandoCierre
from ui.ingreso_caja import texto_de_la_diferencia
from ui.tarjeta_cierre import TarjetaCierreDeTurno
from ui.utils import (
    formato_pesos, mostrar_error, manejar_errores, aplicar_clase, sin_boton_por_defecto, crear_tabla, pedir_pesos,
    mostrar_columna_entera, confirmar, mostrar_info,
)

# Columnas de la tabla de cierres que se ensanchan para leerse enteras.
_COLUMNA_APERTURA = 4
_COLUMNA_CIERRE = 5


def _hora(fecha_iso: str) -> str:
    """"14:05" a partir de una fecha ISO de la base."""
    return datetime.fromisoformat(fecha_iso).strftime("%H:%M")


def texto_del_cierre(cierre) -> str:
    """
    Cómo se cerró una caja, para Control de Cierres: "Forzoso 14:15", "Gaby, en
    ausencia de Lucía · 14:05", "A horario 14:00" (desde que titila el botón
    hasta el fin del turno), "22:40 (40 min después)" o "10:00 (240 min antes)".
    Un cierre sin caja (de antes de las cajas, o de ventas que quedaron sin
    caja) muestra solo la hora. `cierre` es una fila de turnos_repo.listar_cierres.
    """
    hora = _hora(cierre["fecha_cierre"])
    if cierre["cierre_forzoso"]:
        return f"Forzoso {hora}"
    if cierre["cerrada_en_ausencia"]:
        return f"{cierre['empleada']}, en ausencia de {cierre['responsable']} · {hora}"
    if cierre["caja_numero"] is None:
        return hora
    minutos = cierre["minutos_despues_del_fin"]
    if minutos > 0:
        return f"{hora} ({minutos} min después)"
    if minutos < -MINUTOS_AVISO_ANTES_DEL_FIN:
        return f"{hora} ({-minutos} min antes)"
    return f"A horario {hora}"


def nota_del_cierre(cierre) -> str:
    """
    Lo que va abajo de la tarjeta del Cierre de Turno en el detalle de un cierre
    ya hecho, en vez de "Retirá el efectivo...": cómo se cerró. `cierre` es una
    fila de turnos_repo.listar_cierres.
    """
    if cierre["cierre_forzoso"]:
        return (
            f"Se cerró sola a las {_hora(cierre['fecha_cierre'])}: nadie la cerró y pasaron "
            f"{MINUTOS_PARA_CIERRE_FORZOSO} minutos del fin del turno (cierre forzoso)."
        )
    if cierre["cerrada_en_ausencia"]:
        return f"La cerró {texto_del_cierre(cierre)}."
    return f"La cerró {cierre['empleada']}: {texto_del_cierre(cierre)}."


def texto_de_la_apertura(cierre) -> str:
    """Cómo arrancó una caja: "05:55 · contó $ 50.000,00 (coincide)", "14:00 · sin
    contar (lo dejó ella)" o "—" si el cierre no tiene caja."""
    if cierre["caja_numero"] is None:
        return "—"
    hora = _hora(cierre["abierta_en"])
    if cierre["cambio_contado"] is None:
        return f"{hora} · sin contar (lo dejó ella)"
    diferencia = round(cierre["cambio_contado"] - cierre["cambio_esperado"], 2)
    return f"{hora} · contó {formato_pesos(cierre['cambio_contado'])} ({texto_de_la_diferencia(diferencia)})"


class ControlCierresWindow(QDialog):
    """Pantalla para revisar el historial de cierres de turno (Admin, o
    Empleada con `permiso_control_cierres`): cargar cuánto se contó
    realmente en cada sobre y ver qué turnos del mes en curso quedaron sin
    cerrar."""

    def __init__(self, usuario, parent=None):
        super().__init__(parent)
        self.usuario = usuario
        self.setWindowTitle("Control de Cierres de Turno")
        self.resize(1360, 540)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        # Aviso de turnos ya vencidos (ventana + turnos.TURNO_GRACIA_MIN) del
        # mes en curso que todavía no tienen cierre cargado — ver
        # turnos_repo.turnos_faltantes(). Es una QListWidget (no un QLabel)
        # con alto máximo y scroll propio: puede haber más de un centenar de
        # líneas (kiosko recién instalado, o meses sin revisar esta pantalla)
        # y no debe empujar la tabla ni los botones fuera de la ventana.
        # Seleccionar una fila no dispara ninguna acción (ver nota debajo):
        # un turno vencido no se puede cargar por separado, así que es un
        # aviso, no una lista para "completar". Arranca oculto y solo se
        # muestra si hay algo que avisar (ver _cargar_faltantes).
        self.panel_faltantes = QWidget()
        panel_layout = QVBoxLayout(self.panel_faltantes)
        panel_layout.setContentsMargins(0, 0, 0, 0)
        panel_layout.setSpacing(4)

        self.titulo_faltantes = QLabel()
        self.titulo_faltantes.setStyleSheet("color: #A6323C; font-weight: 600;")

        self.lista_faltantes = QListWidget()
        self.lista_faltantes.setMaximumHeight(140)
        self.lista_faltantes.setStyleSheet(
            "QListWidget { background-color: #FBEAEA; border: 1px solid #D9838A; "
            "border-radius: 6px; color: #A6323C; } "
            "QListWidget::item { padding: 3px 6px; } "
            "QListWidget::item:selected { background-color: #F3D3D3; color: #A6323C; }"
        )

        nota_faltantes = QLabel(
            "Un turno vencido no se carga por separado: al confirmar \"Cierre de "
            "Turno\" ahora, todo lo vendido desde el último cierre se agrupa junto, "
            "sin importar cuántos turnos nominales pasaron en el medio. El nombre al "
            "final de cada línea es quién vendió algo o inició sesión en ese horario "
            "(no hay horarios asignados por empleada, así que es una pista de a quién "
            "preguntarle, no una certeza)."
        )
        nota_faltantes.setWordWrap(True)
        nota_faltantes.setStyleSheet("color: #A6323C; font-style: italic; font-size: 11px;")

        panel_layout.addWidget(self.titulo_faltantes)
        panel_layout.addWidget(self.lista_faltantes)
        panel_layout.addWidget(nota_faltantes)
        self.panel_faltantes.hide()

        self.tabla = crear_tabla(
            ["Fecha", "Turno", "Caja", "Responsable", "Apertura", "Cierre", "Cambio Fijo", "Ventas Ef.",
             "Kiosko", "Alquiler PCs", "PlayStation 5", "A Retirar", "Contado", "Diferencia"],
            estirar=3, por_filas=True,
        )
        self.tabla.doubleClicked.connect(self._ver_detalle)

        boton_detalle = QPushButton("Ver Detalle del cierre seleccionado")
        boton_detalle.clicked.connect(self._ver_detalle)
        boton_verificar = QPushButton("Cargar monto contado en el cierre seleccionado")
        aplicar_clase(boton_verificar, "primario")
        boton_verificar.clicked.connect(self._verificar)
        # Lo contado en el sobre lo carga solo el dueño (pedido 2026-10-18; el repo
        # también lo exige): una empleada con el permiso ve los cierres, nada más.
        boton_verificar.setVisible(dominio.es_admin(self.usuario))
        # Mandar (o volver a mandar) un cierre a la app de gastos del dueño (pedido
        # suyo, 2026-10-26): para uno hecho con el envío apagado o borrado por error
        # allá. Solo el Admin, como el sobre.
        self.boton_mandar = QPushButton("Mandar este cierre a la PWA")
        self.boton_mandar.clicked.connect(self._mandar_a_la_app)
        self.boton_mandar.setVisible(dominio.es_admin(self.usuario))
        boton_salir = QPushButton("Salir")
        boton_salir.clicked.connect(self.close)

        botones = QHBoxLayout()
        botones.addWidget(boton_detalle)
        botones.addWidget(boton_verificar)
        botones.addWidget(self.boton_mandar)
        botones.addStretch()
        botones.addWidget(boton_salir)

        layout = QVBoxLayout()
        layout.addWidget(self.panel_faltantes)
        layout.addWidget(self.tabla)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        self.cierres = turnos_repo.listar_cierres()
        self.tabla.setRowCount(0)
        for cierre in self.cierres:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            caja = f"Nº {cierre['caja_numero']}" if cierre["caja_numero"] is not None else "sin caja"
            item_cierre = QTableWidgetItem(texto_del_cierre(cierre))
            if cierre["cierre_forzoso"] or cierre["cerrada_en_ausencia"]:
                item_cierre.setForeground(Qt.red)
            valores = [
                QTableWidgetItem(cierre["fecha"]),
                QTableWidgetItem(etiqueta_turno(cierre["fecha"], cierre["turno"])),
                QTableWidgetItem(caja),
                QTableWidgetItem(" → ".join(cierre["responsables"])),
                QTableWidgetItem(texto_de_la_apertura(cierre)),
                item_cierre,
                QTableWidgetItem(formato_pesos(cierre["fondo_cambio"])),
                QTableWidgetItem(formato_pesos(cierre["ventas_efectivo"])),
                QTableWidgetItem(formato_pesos(cierre["kiosko_efectivo"] + cierre["kiosko_digital"])),
                QTableWidgetItem(formato_pesos(cierre["pcs_efectivo"] + cierre["pcs_digital"])),
                QTableWidgetItem(formato_pesos(cierre["playstation_efectivo"] + cierre["playstation_digital"])),
                QTableWidgetItem(formato_pesos(cierre["monto_a_retirar"])),
            ]
            contado = cierre["monto_contado"]
            valores.append(QTableWidgetItem(formato_pesos(contado) if contado is not None else "—"))
            diferencia = cierre["diferencia"]
            item_diferencia = QTableWidgetItem(formato_pesos(diferencia) if diferencia is not None else "—")
            if diferencia is not None and abs(diferencia) > 0.01:
                item_diferencia.setForeground(Qt.red)
            valores.append(item_diferencia)
            for columna, item in enumerate(valores):
                self.tabla.setItem(fila, columna, item)

        # Apertura y Cierre son frases cortas ("06:20 · contó $ 50.000,00 (coincide)"):
        # cortadas con "..." no se entienden.
        for columna in (_COLUMNA_APERTURA, _COLUMNA_CIERRE):
            mostrar_columna_entera(self.tabla, columna)

        self._cargar_faltantes()

    def _cargar_faltantes(self):
        """Turnos del mes en curso ya vencidos (con su gracia) que todavía
        no tienen cierre — ver turnos_repo.turnos_faltantes()."""
        faltantes = turnos_repo.turnos_faltantes()
        if not faltantes:
            self.panel_faltantes.hide()
            return
        faltantes_ordenados = sorted(faltantes, key=lambda s: (s["fecha"], s["turno"]), reverse=True)
        self.titulo_faltantes.setText(f"⚠️ TURNOS SIN CERRAR ESTE MES ({len(faltantes)}):")
        self.lista_faltantes.clear()
        for slot in faltantes_ordenados:
            # "usuarios": quién vendió algo o inició sesión en esa
            # ventana (no hay horarios asignados en el sistema, así que
            # es una inferencia, no una certeza — ver
            # turnos_faltantes_repo._responsables_del_mes).
            quien = ", ".join(slot["usuarios"]) if slot["usuarios"] else "sin actividad registrada"
            texto = f"{etiqueta_turno(slot['fecha'], slot['turno'])} — {slot['fecha'].strftime('%d/%m')} — {quien}"
            self.lista_faltantes.addItem(texto)
        self.panel_faltantes.show()

    @manejar_errores
    def _ver_detalle(self, _=None):
        # El "_=None" no se usa: recibe el dato que manda `doubleClicked`
        # (la fila clickeada). Qt solo recorta los argumentos que una
        # función no acepta si ve su firma real; @manejar_errores la envuelve
        # en "*args, **kwargs", así que Qt le pasa todo. Sin este parámetro,
        # doble clic en una fila tiraba "takes 1 positional argument but 2
        # were given" en vez de abrir el detalle. (Mismo caso en
        # ArticulosWindow._cargar_grilla.)
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un cierre de la lista.")
            return
        cierre = self.cierres[fila]
        DialogoDetalleCierre(cierre, self).exec()

    @manejar_errores
    def _verificar(self):
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un cierre de la lista.")
            return
        cierre = self.cierres[fila]

        monto, aceptado = pedir_pesos(
            self, "Monto contado",
            f"Turno {etiqueta_turno(cierre['fecha'], cierre['turno'])} del {cierre['fecha']} — {cierre['responsable']}\n"
            f"Se esperaba retirar: {formato_pesos(cierre['monto_a_retirar'])}\n\n"
            "¿Cuánto contaste realmente en el sobre?",
            cierre["monto_a_retirar"],
        )
        if not aceptado:
            return

        turnos_repo.verificar_cierre(cierre["id"], monto, self.usuario["id"])
        self._cargar()

    @manejar_errores
    def _mandar_a_la_app(self):
        """El cierre seleccionado se manda (o se vuelve a mandar) a la app de gastos
        del dueño: lo encola envio_pwa_repo.mandar_cierre y lo manda el hilo del
        mostrador. En el mostrador se ve la barra "ENVIANDO CIERRE DE TURNO"; desde
        otra PC solo se avisa (el hilo vive en el mostrador)."""
        fila = self.tabla.currentRow()
        if fila < 0:
            mostrar_error(self, "Nada seleccionado", "Elegí primero un cierre de la lista.")
            return
        cierre = self.cierres[fila]
        turno = f"Turno {etiqueta_turno(cierre['fecha'], cierre['turno'])} del {cierre['fecha']} — {cierre['responsable']}"
        if not confirmar(
            self, "Mandar a la app de gastos",
            f"{turno}\n\n¿Lo mando a la app de gastos?\n"
            "Si ya estaba allá, se pisa con los mismos números (no se duplica).",
        ):
            return
        resultado = envio_pwa_repo.mandar_cierre(self.usuario["id"], cierre["id"])
        if not resultado["activado"]:
            mostrar_info(
                self, "Queda en la cola",
                "El envío a la app de gastos está apagado: el cierre queda en la cola y se manda solo "
                "cuando lo prendas (Configuración ADMIN > Cierres a la app de gastos).",
            )
        elif modo_remoto.es_copia_remota():
            mostrar_info(
                self, "Se manda desde el mostrador",
                "Listo: el mostrador lo manda enseguida. Cómo fue se ve en Configuración ADMIN > "
                "Cierres a la app de gastos, en el mostrador.",
            )
        else:
            DialogoEnviandoCierre(cierre["id"], self).exec()


class DialogoDetalleCierre(VentanaConDetalleDeVenta):
    """
    Detalle de un cierre puntual. A la izquierda, el cierre tal como lo
    mostraba la pantalla Cierre de Turno (la misma TarjetaCierreDeTurno, con
    los números de turnos_repo.detalle_cierre()["resumen"]), sea un cierre
    común, forzoso o en ausencia: pedido del dueño (2026-10-20), porque el
    cierre forzoso lo hace el programa solo y nadie veía ese resumen. Abajo de
    la tarjeta, en vez de "Retirá el efectivo...", dice cómo se cerró.

    A la derecha, la lista de ventas que cayeron dentro de ese turno, para
    que el Admin pueda ver venta por venta cómo se llegó al total del sobre.
    Mismo patrón maestro-detalle que ConsultaVentasWindow: al seleccionar una
    venta, abajo aparecen sus artículos -- una venta sin detalle real (bono de
    PC, bono de la PlayStation 5, carga de saldo de Miembro) simplemente deja
    esa tabla vacía, no hace falta un caso especial.
    """

    def __init__(self, cierre, parent=None):
        super().__init__(parent)
        self.cierre = cierre
        self.setWindowTitle(
            f"Detalle — Turno {etiqueta_turno(cierre['fecha'], cierre['turno'])} del {cierre['fecha']}"
        )
        # Alta para la tarjeta del Cierre de Turno (con su cabecera y sus cifras desde el
        # 2026-10-26): con 600 los renglones quedaban apretados.
        self.resize(1280, 680)
        self._armar_interfaz()
        self._cargar()

    def _armar_interfaz(self):
        # La tarjeta va a la izquierda con el ancho de la pantalla Cierre de Turno
        # (460) y no arriba: arriba, con la lista de ventas debajo, la ventana no
        # entraba en una pantalla común.
        self.tarjeta = TarjetaCierreDeTurno()
        self.tarjeta.setFixedWidth(440)
        columna_tarjeta = QVBoxLayout()
        columna_tarjeta.addWidget(self.tarjeta)
        columna_tarjeta.addStretch()

        self.encabezado = QLabel()
        self.encabezado.setWordWrap(True)
        self.encabezado.setStyleSheet("font-weight: 600;")

        self.tabla = crear_tabla(
            ["Hora", "Vendedor", "Origen", "Total", "Método", "Estado"],
            estirar=1, por_filas=True,
        )
        self.tabla.itemSelectionChanged.connect(self._mostrar_detalle)

        self.tabla_detalle = crear_tabla_detalle_venta()

        boton_cerrar = QPushButton("Cerrar")
        boton_cerrar.clicked.connect(self.close)
        botones = QHBoxLayout()
        botones.addStretch()
        botones.addWidget(boton_cerrar)

        columna_ventas = QVBoxLayout()
        columna_ventas.addWidget(self.encabezado)
        columna_ventas.addWidget(QLabel("Ventas del turno:"))
        columna_ventas.addWidget(self.tabla)
        columna_ventas.addWidget(QLabel(
            "Artículos de la venta seleccionada (vacío si es bono de PC, de PlayStation o carga de saldo):"
        ))
        columna_ventas.addWidget(self.tabla_detalle)

        columnas = QHBoxLayout()
        columnas.addLayout(columna_tarjeta)
        columnas.addSpacing(16)
        columnas.addLayout(columna_ventas, 1)

        layout = QVBoxLayout()
        layout.addLayout(columnas)
        layout.addLayout(botones)
        self.setLayout(layout)
        sin_boton_por_defecto(self)

    @manejar_errores
    def _cargar(self):
        resultado = turnos_repo.detalle_cierre(self.cierre["id"])
        self.ventas = resultado["ventas"]
        self.tarjeta.mostrar(resultado["resumen"])
        caja = {**self.cierre, **resultado["caja"]}
        self.tarjeta.poner_nota(nota_del_cierre(caja), alerta=caja["cierre_forzoso"] or caja["cerrada_en_ausencia"])
        self.encabezado.setText(self._texto_del_encabezado(resultado))

        self.tabla.setRowCount(0)
        for venta in self.ventas:
            fila = self.tabla.rowCount()
            self.tabla.insertRow(fila)
            self.tabla.setItem(fila, 0, QTableWidgetItem(venta["fecha"][11:16]))
            # Si la cobró el Admin con la caja de ella abierta, queda a nombre de ella
            # (ver cajas_repo._quien_vende) y acá se aclara quién apretó el botón.
            vendedor = venta["vendedor"]
            if venta["cargada_por_nombre"]:
                vendedor += f" (cargó {venta['cargada_por_nombre']})"
            self.tabla.setItem(fila, 1, QTableWidgetItem(vendedor))
            self.tabla.setItem(fila, 2, QTableWidgetItem(dominio.NOMBRE_ORIGEN_VENTA[venta["origen"]]))
            self.tabla.setItem(fila, 3, QTableWidgetItem(formato_pesos(venta["total"])))
            metodos = venta["metodos"].split(",") if venta["metodos"] else []
            texto_metodos = " + ".join(dominio.NOMBRE_METODO_PAGO[metodo] for metodo in metodos)
            self.tabla.setItem(fila, 4, QTableWidgetItem(texto_metodos))
            item_estado = QTableWidgetItem(venta["estado"])
            if venta["estado"] == dominio.VENTA_ANULADA:
                item_estado.setForeground(Qt.red)
            self.tabla.setItem(fila, 5, item_estado)
        self.tabla_detalle.setRowCount(0)

    def _texto_del_encabezado(self, resultado) -> str:
        """La caja del cierre en pocas líneas: quién la tuvo, cómo se abrió, los
        relevos y los conteos del sobre. Lo que había que retirar y cómo se cerró
        ya están en la tarjeta del Cierre de Turno, al lado."""
        caja = resultado["caja"]
        # "desde" y "fecha_cierre" son ISO "YYYY-MM-DDTHH:MM:SS" -- solo se
        # muestra la hora acá, la fecha ya está en el título.
        lineas = [
            f"Responsable: {' → '.join(caja['responsables'])}   ·   "
            f"Rango: {resultado['desde'][11:16]} → {self.cierre['fecha_cierre'][11:16]}"
        ]
        if caja["caja_numero"] is not None:
            lineas.append(f"Caja Nº {caja['caja_numero']}   ·   Abrió: {texto_de_la_apertura(caja)}")
            for relevo in caja["relevos"]:
                lineas.append(
                    f"{_hora(relevo['fecha'])}: {relevo['a_nombre']} recibió la caja de {relevo['de_nombre']} y "
                    f"contó {formato_pesos(relevo['monto_contado'])} "
                    f"(tenía que haber {formato_pesos(relevo['monto_esperado'])}: "
                    f"{texto_de_la_diferencia(relevo['diferencia'])})"
                )
        # Lo de la Cuenta de la PC que quedó fiado en este turno al cerrarlo (2026-10-25).
        for fiado in resultado.get("fiado_sin_cobrar", []):
            a_nombre = f", {fiado['nombre']}" if fiado["nombre"] else ""
            lineas.append(f"💳 Fiado sin cobrar al cerrar: {formato_pesos(fiado['monto'])} ({fiado['estacion']}{a_nombre})")
        for verificacion in resultado["verificaciones"]:
            lineas.append(
                f"Sobre contado el {verificacion['fecha'][8:10]}/{verificacion['fecha'][5:7]} "
                f"{verificacion['fecha'][11:16]} por {verificacion['verificado_por_nombre']}: "
                f"{formato_pesos(verificacion['monto_contado'])} ({texto_de_la_diferencia(verificacion['diferencia'])})"
            )
        return "\n".join(lineas)

