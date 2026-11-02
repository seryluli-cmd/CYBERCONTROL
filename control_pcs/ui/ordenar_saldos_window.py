"""
ordenar_saldos_window.py
========================
ORDENAR SALDOS (botón de Miembros que solo ve el Admin y que pide la contraseña de
ORDENAR Stock; pedido del dueño, 2026-11-01): corregir a mano el saldo de tiempo de
un socio sin cobrar nada ni tocar la caja. El caso que lo trajo: una empleada le
cargó horas a un socio que no era (se equivocó de cuenta).

Se elige el socio de la lista, se escribe el tiempo (horas y minutos) y:
- SUMAR / RESTAR: le suma o le saca ese tiempo al saldo;
- PASAR A OTRO SOCIO: se lo saca a este y se lo da al socio que se elija, de una
  sola vez (la carga hecha a la cuenta equivocada).
Cada corrección pregunta antes y queda en "Últimas correcciones" con quién y
cuándo. Las reglas (solo Admin con la contraseña, nunca un saldo negativo, lo que
se suma a un socio que está jugando pasa a su PC) son de ajustes_saldo_repo, que
las vuelve a mirar en cada corrección.

Con las piezas de la ventana de Miembros: la cabecera oscura, la lista de socios a
la izquierda (miembros_ficha.DelegadoDeSocios) y el socio elegido a la derecha.

Se abre también desde otra PC (el botón Miembros de la pantalla principal se lo
ofrece al Administrador, mismo día): no mueve plata, así que no es de lo que se
hace solo en el mostrador. Por eso todo lo que pide a los repos está en
admin_remoto/lista_blanca.py, y las correcciones las graba el mostrador.
"""

from datetime import datetime

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QDialog, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QSpinBox,
    QTableWidgetItem, QVBoxLayout,
)

from control_pcs.repositories import ajustes_saldo_repo, miembros_repo, ultima_visita_repo
from control_pcs.ui.dibujos_de_ventana import pixmap_de_avatar
from control_pcs.ui.miembros_ficha import ROL_DATOS, DelegadoDeSocios, texto_de_la_ultima_pc
from ui.piezas_ventana import (
    TONO_AZUL, buscador, cabecera_oscura, cifra_destacada, panel_blanco, panel_de_tabla, pie_de_ventana, tecla,
    titulo_de_seccion,
)
from ui.utils import (
    confirmar, crear_tabla, encadenar_enter, fila_guardar_cancelar, formato_fecha_hora, formato_tiempo,
    manejar_errores, mostrar_error, mostrar_info, sin_boton_por_defecto,
)

# Las columnas de "Últimas correcciones".
TITULOS_CORRECCIONES = ("Fecha", "Socio", "Cambio", "Saldo", "Quién")
COLUMNA_CAMBIO = 2


def texto_saldo(minutos: int) -> str:
    """Un saldo como lo muestra Miembros ("5h 00m")."""
    return formato_tiempo(minutos * 60)


def texto_del_cambio(ajuste) -> str:
    """Lo que dice la columna Cambio: "+3h 00m" o "-3h 00m" y, en un pase, de quién
    vino o a quién fue."""
    minutos = ajuste["minutos"]
    texto = ("+" if minutos >= 0 else "-") + texto_saldo(abs(minutos))
    if ajuste["otro_socio"] is not None:
        texto += f", pasado de {ajuste['otro_socio']}" if minutos >= 0 else f", pasado a {ajuste['otro_socio']}"
    return texto


def abrir_ordenar_saldos(padre, usuario_id: int) -> bool:
    """
    Pide la contraseña y, si es la buena, abre la ventana; devuelve si se abrió. Es la
    entrada de Miembros en el mostrador y del botón Miembros desde otra PC (pedido del
    dueño, 2026-11-01). Una contraseña equivocada (o un usuario que dejó de ser Admin)
    levanta PermissionError sin abrir nada: lo muestra el @manejar_errores de quien llama.
    """
    clave, aceptado = QInputDialog.getText(
        padre, "ORDENAR SALDOS", "Contraseña de ORDENAR SALDOS (la misma de ORDENAR Stock):", QLineEdit.Password
    )
    if not aceptado:
        return False
    ajustes_saldo_repo.comprobar_clave_para_ordenar_saldos(usuario_id, clave)
    OrdenarSaldosWindow(padre, usuario_id, clave).exec()
    return True


def _campo_de_tiempo(maximo: int, sufijo: str) -> QSpinBox:
    campo = QSpinBox()
    campo.setRange(0, maximo)
    campo.setSuffix(sufijo)
    # Sin flechitas, como en Miembros: con esta hoja de estilos salen como una rayita.
    campo.setButtonSymbols(QSpinBox.NoButtons)
    campo.setFixedWidth(90)
    campo.setAlignment(Qt.AlignRight)
    return campo


class OrdenarSaldosWindow(QDialog):
    """La lista de socios a la izquierda y, a la derecha, el saldo del elegido, el tiempo a
    corregir con sus tres botones y las últimas correcciones de todos los socios."""

    def __init__(self, parent, usuario_id: int, clave: str):
        super().__init__(parent)
        self.usuario_id = usuario_id
        # La contraseña viaja en cada corrección porque el repo la vuelve a pedir; no
        # se guarda en ningún lado y se va con la ventana (como ORDENAR Stock).
        self._clave = clave
        # Lo que se ve, en el mismo orden que la lista (como MiembrosWindow).
        self.socios = []
        self._visitas = {}
        self._dias = {}
        self.setWindowTitle("ORDENAR SALDOS")
        self.resize(1180, 760)
        self._armar_interfaz()
        self._cargar_lista()
        self._cargar_correcciones()

    def _armar_interfaz(self):
        raiz = QVBoxLayout(self)
        raiz.setContentsMargins(16, 16, 16, 12)
        raiz.setSpacing(12)
        raiz.addWidget(cabecera_oscura(
            "⚙", "ORDENAR SALDOS",
            "Acá se corrige el SALDO de los socios: sumar, restar o pasar de un socio a otro. "
            "No se cobra nada y la caja no se toca",
        ))

        cuerpo = QHBoxLayout()
        cuerpo.setSpacing(12)

        # ---- la lista de socios
        izquierda, capa = panel_blanco()
        izquierda.setFixedWidth(420)
        self.campo_buscar = buscador("Buscar por usuario...")
        self.campo_buscar.textChanged.connect(self._cargar_lista)
        capa.addWidget(self.campo_buscar)
        self.lista = QListWidget()
        self.lista.setItemDelegate(DelegadoDeSocios(self.lista))
        self.lista.setStyleSheet("QListWidget { border: none; background: transparent; outline: none; }")
        self.lista.setMouseTracking(True)
        self.lista.setUniformItemSizes(True)
        self.lista.currentRowChanged.connect(lambda _fila: self._mostrar_elegido())
        capa.addWidget(self.lista, 1)
        cuerpo.addWidget(izquierda)

        # ---- el socio elegido
        derecha, capa = panel_blanco()
        quien = QHBoxLayout()
        quien.setSpacing(14)
        self.avatar = QLabel()
        self.avatar.setFixedSize(56, 56)
        quien.addWidget(self.avatar, 0, Qt.AlignTop)
        nombres = QVBoxLayout()
        nombres.setSpacing(2)
        self.etiqueta_usuario = QLabel()
        self.etiqueta_usuario.setObjectName("fichaNombre")
        self.etiqueta_nombre = QLabel()
        self.etiqueta_nombre.setObjectName("fichaUsuario")
        nombres.addWidget(self.etiqueta_usuario)
        nombres.addWidget(self.etiqueta_nombre)
        # Juntos arriba, al lado del círculo: si no, se reparten el alto del recuadro del saldo.
        nombres.addStretch()
        quien.addLayout(nombres, 1)
        self.cifra_saldo = cifra_destacada("SALDO", "lo que tiene ahora para jugar", TONO_AZUL)
        self.cifra_saldo.setMinimumWidth(240)
        quien.addWidget(self.cifra_saldo)
        capa.addLayout(quien)

        # Si está usando una PC: lo que se le suma pasa a esa sesión y lo que ya corre
        # en la PC no se puede restar (ajustes_saldo_repo).
        self.aviso_jugando = QLabel()
        self.aviso_jugando.setWordWrap(True)
        self.aviso_jugando.setStyleSheet("color: #B26A00; font-weight: bold;")
        capa.addWidget(self.aviso_jugando)

        capa.addWidget(titulo_de_seccion("Corregir el saldo"))
        fila_tiempo = QHBoxLayout()
        fila_tiempo.setSpacing(8)
        self.campo_horas = _campo_de_tiempo(999, " h")
        self.campo_minutos = _campo_de_tiempo(59, " min")
        fila_tiempo.addWidget(QLabel("Tiempo:"))
        fila_tiempo.addWidget(self.campo_horas)
        fila_tiempo.addWidget(self.campo_minutos)
        fila_tiempo.addStretch()
        capa.addLayout(fila_tiempo)
        fila_botones = QHBoxLayout()
        fila_botones.setSpacing(8)
        self.boton_sumar = tecla("＋  SUMAR", self._sumar, "teclaVerde")
        self.boton_restar = tecla("－  RESTAR", self._restar, "teclaRoja")
        self.boton_pasar = tecla("⇄  PASAR A OTRO SOCIO", self._pasar, "teclaAzul")
        for boton in (self.boton_sumar, self.boton_restar, self.boton_pasar):
            fila_botones.addWidget(boton)
        fila_botones.addStretch()
        capa.addLayout(fila_botones)
        # Lo último que se guardó, en negrita para que se vea al toque que quedó.
        self.etiqueta_estado = QLabel("")
        self.etiqueta_estado.setWordWrap(True)
        self.etiqueta_estado.setStyleSheet("font-weight: bold;")
        capa.addWidget(self.etiqueta_estado)

        capa.addWidget(titulo_de_seccion("Últimas correcciones"))
        self.tabla = crear_tabla(TITULOS_CORRECCIONES, estirar=COLUMNA_CAMBIO, por_filas=True)
        capa.addWidget(panel_de_tabla(self.tabla, 32), 1)
        cuerpo.addWidget(derecha, 1)
        raiz.addLayout(cuerpo, 1)

        pie = QHBoxLayout()
        pie.setSpacing(12)
        pie.addWidget(pie_de_ventana(
            "Elegí el socio, escribí el tiempo y apretá SUMAR, RESTAR o PASAR A OTRO SOCIO  ·  No se cobra ni "
            "se devuelve plata: las ventas y la caja quedan como estaban  ·  Cada corrección queda anotada "
            "con quién y cuándo"), 1)
        pie.addWidget(tecla("SALIR", self.close))
        raiz.addLayout(pie)

        encadenar_enter(self.campo_buscar, self.campo_horas, self.campo_minutos)
        sin_boton_por_defecto(self)
        self.campo_buscar.setFocus()

    # ------------------------------------------------------------ lo que se muestra
    @manejar_errores
    def _cargar_lista(self, _=None):
        # El "_=None" absorbe el texto que manda `textChanged`.
        elegido = self._id_elegido()
        self.socios = miembros_repo.listar_miembros(texto_busqueda=self.campo_buscar.text())
        self._visitas = ultima_visita_repo.ultimas_visitas()
        ahora = datetime.now()
        self._dias = {s["id"]: ultima_visita_repo.dias_sin_venir(self._visitas.get(s["id"]), ahora)
                      for s in self.socios}
        self.lista.blockSignals(True)
        self.lista.clear()
        for socio in self.socios:
            renglon = QListWidgetItem()
            renglon.setData(ROL_DATOS, {"miembro": socio, "dias": self._dias[socio["id"]]})
            self.lista.addItem(renglon)
        # Sigue elegido el mismo socio (o el primero), como en Miembros.
        fila = next((i for i, s in enumerate(self.socios) if s["id"] == elegido), 0 if self.socios else -1)
        self.lista.setCurrentRow(fila)
        self.lista.blockSignals(False)
        if fila >= 0:
            self.lista.scrollToItem(self.lista.item(fila))
        self._mostrar_elegido()

    def _mostrar_elegido(self):
        socio = self._elegido()
        hay = socio is not None
        for boton in (self.boton_sumar, self.boton_restar, self.boton_pasar):
            boton.setEnabled(hay)
        if not hay:
            self.avatar.clear()
            self.etiqueta_usuario.setText("No hay socios para mostrar")
            self.etiqueta_nombre.setText("")
            self.cifra_saldo.valor.setText("—")
            self.aviso_jugando.setVisible(False)
            return
        self.avatar.setPixmap(pixmap_de_avatar(socio["usuario"], 56))
        self.etiqueta_usuario.setText(socio["usuario"])
        self.etiqueta_nombre.setText(socio["nombre"] if socio["nombre"] != socio["usuario"] else "")
        self.cifra_saldo.valor.setText(texto_saldo(socio["saldo_minutos"]))
        visita = self._visitas.get(socio["id"])
        jugando = visita is not None and visita["jugando"]
        self.aviso_jugando.setVisible(jugando)
        if jugando:
            self.aviso_jugando.setText(
                f"{texto_de_la_ultima_pc(visita)}: lo que le sumes pasa a esa PC; lo que ya está corriendo en "
                "la PC no se puede restar desde acá (cerrale la sesión y lo que no usó vuelve a su saldo)."
            )

    @manejar_errores
    def _cargar_correcciones(self):
        ajustes = ajustes_saldo_repo.listar_ajustes()
        self.tabla.setRowCount(len(ajustes))
        for fila, ajuste in enumerate(ajustes):
            textos = (
                formato_fecha_hora(ajuste["fecha"]), ajuste["socio"], texto_del_cambio(ajuste),
                f"{texto_saldo(ajuste['saldo_anterior'])} → {texto_saldo(ajuste['saldo_nuevo'])}",
                ajuste["operador"],
            )
            for columna, texto in enumerate(textos):
                self.tabla.setItem(fila, columna, QTableWidgetItem(texto))
        self.tabla.resizeColumnsToContents()

    def _elegido(self):
        fila = self.lista.currentRow()
        return self.socios[fila] if 0 <= fila < len(self.socios) else None

    def _id_elegido(self):
        socio = self._elegido()
        return socio["id"] if socio is not None else None

    def _minutos_escritos(self):
        """Los minutos de los dos campos, o None (con el aviso) si quedaron en cero."""
        minutos = self.campo_horas.value() * 60 + self.campo_minutos.value()
        if minutos <= 0:
            mostrar_error(self, "Falta el tiempo", "Escribí cuánto tiempo (horas y minutos) antes de apretar.")
            self.campo_horas.setFocus()
            self.campo_horas.selectAll()
            return None
        return minutos

    def _despues_de_guardar(self, texto: str, sumado_a_la_sesion=None):
        self.etiqueta_estado.setText(texto)
        self.campo_horas.setValue(0)
        self.campo_minutos.setValue(0)
        self._cargar_lista()
        self._cargar_correcciones()
        # Como Cargar Saldo: si el socio está usando una PC, que se sepa que el tiempo ya corre ahí.
        if sumado_a_la_sesion is not None:
            mostrar_info(
                self, "Saldo corregido",
                f"Se le sumaron {texto_saldo(sumado_a_la_sesion['minutos'])} a su sesión en "
                f"{sumado_a_la_sesion['estacion']}: le aparecen en la PC en unos segundos.",
            )

    # ------------------------------------------------------------ las tres correcciones
    @manejar_errores
    def _sumar(self):
        socio = self._elegido()
        minutos = self._minutos_escritos() if socio is not None else None
        if minutos is None or not confirmar(
            self, "Sumar saldo",
            f"¿Sumarle {texto_saldo(minutos)} al saldo de {socio['usuario']}?\n\n"
            f"Ahora tiene {texto_saldo(socio['saldo_minutos'])}.\n\nNo se cobra nada: la caja no se toca.",
        ):
            return
        resultado = ajustes_saldo_repo.sumar(self.usuario_id, socio["id"], minutos, self._clave)
        self._despues_de_guardar(
            f"Guardado: {socio['usuario']} +{texto_saldo(minutos)}, saldo "
            f"{texto_saldo(resultado['saldo_anterior'])} → {texto_saldo(resultado['saldo_nuevo'])}",
            resultado["sumado_a_la_sesion"],
        )

    @manejar_errores
    def _restar(self):
        socio = self._elegido()
        minutos = self._minutos_escritos() if socio is not None else None
        if minutos is None or not confirmar(
            self, "Restar saldo",
            f"¿Sacarle {texto_saldo(minutos)} del saldo a {socio['usuario']}?\n\n"
            f"Ahora tiene {texto_saldo(socio['saldo_minutos'])}.\n\nNo se devuelve plata: la caja no se toca.",
        ):
            return
        resultado = ajustes_saldo_repo.restar(self.usuario_id, socio["id"], minutos, self._clave)
        self._despues_de_guardar(
            f"Guardado: {socio['usuario']} -{texto_saldo(minutos)}, saldo "
            f"{texto_saldo(resultado['saldo_anterior'])} → {texto_saldo(resultado['saldo_nuevo'])}"
        )

    @manejar_errores
    def _pasar(self):
        desde = self._elegido()
        minutos = self._minutos_escritos() if desde is not None else None
        if minutos is None:
            return
        elegir = DialogoElegirSocio(self, desde, minutos)
        if not elegir.exec() or elegir.elegido is None:
            return
        hacia = elegir.elegido
        if not confirmar(
            self, "Pasar saldo a otro socio",
            f"¿Pasar {texto_saldo(minutos)} de {desde['usuario']} a {hacia['usuario']}?\n\n"
            f"{desde['usuario']}: tiene {texto_saldo(desde['saldo_minutos'])}\n"
            f"{hacia['usuario']}: tiene {texto_saldo(hacia['saldo_minutos'])}\n\n"
            "No se cobra ni se devuelve plata: la caja no se toca.",
        ):
            return
        resultado = ajustes_saldo_repo.pasar(self.usuario_id, desde["id"], hacia["id"], minutos, self._clave)
        restado, sumado = resultado["desde"], resultado["hacia"]
        self._despues_de_guardar(
            f"Pasado: {texto_saldo(minutos)} de {desde['usuario']} "
            f"({texto_saldo(restado['saldo_anterior'])} → {texto_saldo(restado['saldo_nuevo'])}) a "
            f"{hacia['usuario']} ({texto_saldo(sumado['saldo_anterior'])} → {texto_saldo(sumado['saldo_nuevo'])})",
            sumado["sumado_a_la_sesion"],
        )


class DialogoElegirSocio(QDialog):
    """A qué socio se le pasa el tiempo: la lista de los demás socios activos con su buscador.
    Doble clic, Enter o "Elegir". El elegido queda en `elegido` (None si se cancela)."""

    def __init__(self, parent, desde, minutos: int):
        super().__init__(parent)
        self.desde = desde
        self.elegido = None
        self.socios = []
        self.setWindowTitle("Pasar a otro socio")
        self.resize(460, 560)

        explicacion = QLabel(f"¿A qué socio le pasás {texto_saldo(minutos)} de {desde['usuario']}?")
        explicacion.setWordWrap(True)
        explicacion.setStyleSheet("font-weight: bold;")
        self.campo_buscar = buscador("Buscar por usuario...")
        self.campo_buscar.textChanged.connect(self._cargar_lista)
        self.lista = QListWidget()
        self.lista.setItemDelegate(DelegadoDeSocios(self.lista))
        self.lista.setUniformItemSizes(True)
        self.lista.itemDoubleClicked.connect(lambda _item: self._elegir())

        capa = QVBoxLayout(self)
        capa.addWidget(explicacion)
        capa.addWidget(self.campo_buscar)
        capa.addWidget(self.lista, 1)
        capa.addLayout(fila_guardar_cancelar(self, self._elegir, texto_guardar="Elegir"))
        # Enter en el buscador elige el de arriba (o el que se marcó con las flechas).
        encadenar_enter(self.campo_buscar, accion_final=self._elegir)
        sin_boton_por_defecto(self)
        self._cargar_lista()
        self.campo_buscar.setFocus()

    @manejar_errores
    def _cargar_lista(self, _=None):
        self.socios = [s for s in miembros_repo.listar_miembros(texto_busqueda=self.campo_buscar.text())
                       if s["id"] != self.desde["id"]]
        visitas = ultima_visita_repo.ultimas_visitas()
        ahora = datetime.now()
        self.lista.clear()
        for socio in self.socios:
            renglon = QListWidgetItem()
            renglon.setData(ROL_DATOS, {
                "miembro": socio, "dias": ultima_visita_repo.dias_sin_venir(visitas.get(socio["id"]), ahora)})
            self.lista.addItem(renglon)
        self.lista.setCurrentRow(0 if self.socios else -1)

    def _elegir(self):
        fila = self.lista.currentRow()
        if not 0 <= fila < len(self.socios):
            mostrar_error(self, "Nada elegido", "Elegí de la lista el socio que tiene que recibir el tiempo.")
            return
        self.elegido = self.socios[fila]
        self.accept()
