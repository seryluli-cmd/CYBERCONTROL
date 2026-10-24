"""
utils.py
=========
Funciones chiquitas que se repiten en varias pantallas: dar formato a
números (pesos argentinos, tiempos), mostrar cuadros de mensaje (avisos,
errores, confirmaciones), un decorador para que ningún error inesperado
rompa una pantalla en silencio, otro para lo que desde otra PC solo avisa
que se hace en el mostrador, y los ajustes de widgets que hay que
repetir en cada formulario (clase de botón, salto con Enter, sin botón
por defecto).
"""

import functools
from datetime import datetime

from PySide6.QtCore import QDate, QEvent, QObject, QRect, QSize, Qt
from PySide6.QtGui import QFont, QGuiApplication, QIcon, QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QAbstractSpinBox, QComboBox, QDateEdit, QHBoxLayout, QHeaderView, QLabel, QMessageBox,
    QPushButton, QTableWidget, QWidget,
)

from admin_remoto import modo as modo_remoto
from errores import registrar_error
from turnos import dia_en_que_empezo_el_turno


def manejar_errores(func):
    """
    Decorador para los métodos de una pantalla que llaman a la base de
    datos (guardar, borrar, confirmar una venta, etc.). Antes, si algo
    fallaba ahí adentro, la excepción se propagaba sin control y la
    usuaria se encontraba con la pantalla rota. Con esto:

    - Un ValueError (los errores "de negocio", como intentar borrar un
      artículo que ya tiene ventas) se muestra tal cual, con su mensaje
      pensado para leerse directamente. Un PermissionError ("no tenés
      permiso para esto", ver playstation_repo) también: es un rechazo de
      negocio con su mensaje listo, no una falla del programa.
    - Cualquier otro error inesperado se guarda en el log de errores y
      se le muestra a la usuaria un cartel genérico, en vez de que la
      aplicación se rompa o quede en un estado raro.
    - Un RuntimeError de "objeto C++ ya borrado" (libshiboken) es un caso
      aparte: pasa cuando el refresco automático de 5s de Control de PCs
      (`PanelControlPcs._refrescar`) dispara justo mientras esa pantalla
      se está cerrando (logout o cierre del programa) y toca un widget
      que ya no existe. Ahí no hay a quién mostrarle un cartel -- el
      padre puede estar tan destruido como lo que falló, e intentarlo
      igual repetía el mismo error y se escapaba sin control (ver
      data/errores.log, 2026-09-28: "PanelActividad already deleted"
      seguido de "PanelControlPcs already deleted" al querer avisarle a
      esa misma ventana). Se registra en el log y se ignora en silencio.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        try:
            return func(self, *args, **kwargs)
        except (ValueError, PermissionError) as error:
            mostrar_error(self, "No se pudo completar", str(error))
        except RuntimeError as error:
            registrar_error(error)
            if "already deleted" not in str(error):
                _mostrar_error_seguro(self, error)
        except Exception as error:
            registrar_error(error)
            _mostrar_error_seguro(self, error)
    return wrapper


def solo_en_el_mostrador(func):
    """
    Decorador para lo que vende, cobra o atiende una PC (Vender, Cobrar un bono,
    Finalizar Sesión, Reiniciar...). En la copia para administrar desde otra PC
    (admin_remoto/) la pantalla se ve igual que en el mostrador (pedido del dueño,
    2026-10-24: "quiero que se vea tal cual"), pero eso lo hace la operadora en el
    mostrador: el botón está, y al apretarlo avisa y no hace nada. En el
    mostrador no cambia nada.
    """
    @functools.wraps(func)
    def wrapper(self, *args, **kwargs):
        if modo_remoto.es_copia_remota():
            avisar_que_es_en_el_mostrador(self)
            return None
        return func(self, *args, **kwargs)
    return wrapper


def avisar_que_es_en_el_mostrador(padre):
    """El aviso de `solo_en_el_mostrador` (también para el menú del clic derecho de
    una PC, que elige qué hacer recién después de abrirse)."""
    mostrar_info(
        padre, "Se hace en el mostrador",
        "Esto se hace en el mostrador.\n\nDesde esta PC ves todo como en el mostrador, pero vender, "
        "cobrar y atender las PCs lo hace la operadora allá.",
    )


def _mostrar_error_seguro(padre, error):
    """Mismo cartel genérico de `manejar_errores`, pero sin dejar que un
    segundo "objeto ya borrado" (el propio `padre`) se escape sin
    control -- ver el comentario de `manejar_errores` sobre el caso
    RuntimeError."""
    try:
        mostrar_error(
            padre, "Ocurrió un error inesperado",
            "Algo falló y la acción no se pudo completar.\n"
            "El detalle quedó guardado en data/errores.log para revisarlo después.\n\n"
            f"({error.__class__.__name__}: {error})"
        )
    except RuntimeError:
        pass


def formato_pesos(monto) -> str:
    """
    Convierte un número (1234.5) en un texto con formato de pesos
    argentinos ("$ 1.234,50"): punto para miles, coma para decimales.
    """
    try:
        monto = float(monto)
    except (TypeError, ValueError):
        monto = 0.0
    texto = f"{monto:,.2f}"
    # f-string nos da el formato "en inglés" (1,234.50); lo invertimos
    # a formato argentino cambiando temporalmente los separadores.
    texto = texto.replace(",", "TEMP").replace(".", ",").replace("TEMP", ".")
    return f"$ {texto}"


def formato_fecha_hora(fecha) -> str:
    """
    Una fecha con hora como se graba en la base ("2026-10-16T22:13:28.123456")
    convertida en "16/10/2026 22:13", para mostrar. Si no se puede leer, la
    devuelve tal cual (mejor ver el dato crudo que un cartel de error).
    """
    try:
        return datetime.fromisoformat(fecha).strftime("%d/%m/%Y %H:%M")
    except (TypeError, ValueError):
        return str(fecha)


def formato_tiempo(segundos: int, con_segundos: bool = False) -> str:
    """
    Convierte segundos en un texto legible ("2h 05m" o "45m 12s"). Con
    `con_segundos` también muestra los segundos pasada la hora ("2h 05m 31s"):
    es lo que usa la cuenta regresiva de la PlayStation 5, que se redibuja
    cada segundo y tiene que verse correr. Vive acá (y no en control_pcs/)
    porque tanto control_pcs/ui/pcs_window.py como
    control_pcs/ui/miembros_window.py lo necesitan, y ui/utils.py ya es el
    módulo compartido genérico que ambos lados de la app usan (ver
    CLAUDE.md) — puesto en cualquiera de los dos, el otro tendría que
    importarlo cruzado.
    """
    horas, resto = divmod(segundos, 3600)
    minutos, seg = divmod(resto, 60)
    if horas:
        return f"{horas}h {minutos:02d}m {seg:02d}s" if con_segundos else f"{horas}h {minutos:02d}m"
    return f"{minutos}m {seg:02d}s"


def formato_transcurrido(desde: datetime) -> str:
    """Cuánto pasó desde `desde` hasta ahora, como formato_tiempo ("2h 05m").
    Nunca negativo: un reloj apenas corrido no tiene que mostrar "-1m"."""
    return formato_tiempo(max(0, int((datetime.now() - desde).total_seconds())))


def aplicar_clase(widget, clase: str):
    """
    Marca un botón como "primario" (acción principal, ej. Cobrar,
    Guardar) o "peligro" (acción destructiva, ej. Cancelar, Borrar,
    Cerrar sesión) para que tome el color correspondiente de la hoja de
    estilos global (ver ui/hoja_de_estilos.py). No alcanza con setProperty solo: Qt
    necesita que se le pida "repintar" el widget con el selector CSS
    nuevo, si no el botón se queda con el aspecto neutro de siempre.
    """
    widget.setProperty("clase", clase)
    widget.style().unpolish(widget)
    widget.style().polish(widget)


def sin_boton_por_defecto(ventana):
    """
    Le saca a todos los botones de `ventana` la condición de "botón por
    defecto". Se llama una vez, al terminar de armar la interfaz.

    Sin esto, Qt marca como "default" el primer botón que se arma en cada
    diálogo, y apretar Enter en cualquier campo de texto lo activa como si
    se hubiera hecho clic en él. Se vio en Ventas: escanear un código de
    barras y apretar Enter abría la búsqueda F5, porque ese era el primer
    botón de la pantalla.
    """
    for boton in ventana.findChildren(QPushButton):
        boton.setAutoDefault(False)
        boton.setDefault(False)


def fila_guardar_cancelar(dialogo, al_guardar=None, texto_guardar: str = "Guardar"):
    """
    La fila de botones de un formulario: "Guardar" (azul, la acción
    principal) y "Cancelar" (cierra el diálogo con `reject`). `al_guardar`
    es lo que hace el primero (por defecto, aceptar el diálogo tal cual) y
    `texto_guardar` cómo se llama ("Ingresar", "Cobrar y cargar saldo"...).
    Devuelve el layout, para agregarlo al del diálogo.
    """
    boton_guardar = QPushButton(texto_guardar)
    aplicar_clase(boton_guardar, "primario")
    boton_guardar.clicked.connect(al_guardar or dialogo.accept)
    boton_cancelar = QPushButton("Cancelar")
    boton_cancelar.clicked.connect(dialogo.reject)
    botones = QHBoxLayout()
    botones.addWidget(boton_guardar)
    botones.addWidget(boton_cancelar)
    return botones


def fila_agregar_quitar(tabla: QTableWidget, texto_agregar: str, al_agregar):
    """
    Los botones de una tabla que se edita a mano: uno para agregar una fila
    (`texto_agregar`, y `al_agregar` es lo que hace) y "Quitar seleccionado",
    que borra la fila elegida de `tabla`. Devuelve el layout, para agregarlo
    al del diálogo.
    """
    def quitar_la_elegida():
        fila = tabla.currentRow()
        if fila >= 0:
            tabla.removeRow(fila)

    boton_agregar = QPushButton(texto_agregar)
    boton_agregar.clicked.connect(al_agregar)
    boton_quitar = QPushButton("Quitar seleccionado")
    aplicar_clase(boton_quitar, "peligro")
    boton_quitar.clicked.connect(quitar_la_elegida)
    botones = QHBoxLayout()
    botones.addWidget(boton_agregar)
    botones.addWidget(boton_quitar)
    return botones


class _FiltroEnter(QObject):
    """Intercepta la tecla Enter/Intro en el widget donde se instala y,
    en vez de dejarla pasar, ejecuta `accion` (ver `encadenar_enter`)."""

    def __init__(self, accion, widget):
        super().__init__()
        self._accion = accion
        self._widget = widget

    def eventFilter(self, watched, evento):
        if evento.type() == QEvent.KeyPress and evento.key() in (Qt.Key_Return, Qt.Key_Enter):
            # Un Enter que quedó apretado (la repetición del teclado) se
            # descarta: si no, saltaría todos los campos de un tirón y
            # dispararía la acción final (Cobrar, Guardar) sin que nadie la
            # pidiera. Un lector de códigos manda un Enter suelto, no repetido.
            if not evento.isAutoRepeat():
                # El Enter no le llega al campo (se lo queda este filtro): se
                # hace a mano lo que haría él, dar por terminado lo escrito,
                # para que la acción lea el número que se ve.
                if isinstance(self._widget, QAbstractSpinBox):
                    self._widget.interpretText()
                self._accion()
            return True
        return False


def _widgets_de_teclado(widget):
    """
    Dónde engancharse para ver el Enter de `widget`. QComboBox editable,
    QSpinBox, QDoubleSpinBox y QDateEdit tienen por dentro su propio
    QLineEdit, pero con el teclado de verdad el Enter le llega al widget de
    afuera (el de adentro le pasa el foco a él) y nunca al de adentro. Se
    midió el 2026-10-18 con el PySide6 del programa: enganchado solo al de
    adentro, Enter no hacía nada en ningún importe (el cobro, Contar plata,
    Trámites, Cargar Saldo...). Las pruebas no lo veían porque mandaban el
    Enter directo al de adentro. Se engancha a los dos por si otra versión
    de Qt lo entrega al de adentro: el primero que lo ve lo consume, así que
    un Enter nunca dispara la acción dos veces.
    """
    if isinstance(widget, QAbstractSpinBox) or (isinstance(widget, QComboBox) and widget.isEditable()):
        return [widget, widget.lineEdit()]
    return [widget]


def encadenar_enter(*widgets, accion_final=None):
    """
    Hace que apretar Enter en cualquiera de estos campos de un
    formulario pase el foco al siguiente, como si se apretara Tab, en
    vez de no hacer nada (el comportamiento por defecto de Qt para la
    mayoría de estos campos). Sirve para QLineEdit, QComboBox, QSpinBox,
    QDoubleSpinBox y QDateEdit indistintamente, y se puede mezclar
    cualquier combinación de esos tipos en la misma cadena.

    En el último campo, si se pasa `accion_final` (una función sin
    argumentos, típicamente el método que guarda o busca), Enter la
    ejecuta directamente en vez de pasar el foco a ningún lado.
    """
    destinos = list(widgets[1:])
    if accion_final is not None:
        destinos.append(accion_final)

    for widget, destino in zip(widgets, destinos):
        accion = destino.setFocus if isinstance(destino, QWidget) else destino
        filtro = _FiltroEnter(accion, widget)
        # Qt no retiene una referencia propia al filtro (solo la usa por
        # fuera, en C++); si no la guardamos nosotros en algún lado,
        # Python lo destruye enseguida y el filtro deja de funcionar.
        widget._filtro_enter = filtro
        for destino_de_la_tecla in _widgets_de_teclado(widget):
            destino_de_la_tecla.installEventFilter(filtro)


def crear_tabla(titulos, estirar=None, por_filas=False, una_sola=False) -> QTableWidget:
    """
    Una tabla de solo lectura, con filas alternadas, columnas `titulos` y
    sin filas todavía: así se muestran todas las listas del programa.

    - `estirar`: número de la columna que ocupa el ancho que sobra (las
      demás se ajustan solas).
    - `por_filas`: elegir una celda selecciona la fila entera.
    - `una_sola`: se puede elegir una sola fila a la vez.
    """
    tabla = QTableWidget(0, len(titulos))
    tabla.setHorizontalHeaderLabels(list(titulos))
    if por_filas:
        tabla.setSelectionBehavior(QTableWidget.SelectRows)
    if una_sola:
        tabla.setSelectionMode(QTableWidget.SingleSelection)
    tabla.setEditTriggers(QTableWidget.NoEditTriggers)
    tabla.setAlternatingRowColors(True)
    # Sin la numeración de filas (1, 2, 3...), que no le dice nada a nadie, y con
    # los títulos alineados a la izquierda como el contenido.
    tabla.verticalHeader().setVisible(False)
    tabla.horizontalHeader().setDefaultAlignment(Qt.AlignLeft | Qt.AlignVCenter)
    if estirar is not None:
        tabla.horizontalHeader().setSectionResizeMode(estirar, QHeaderView.Stretch)
    return tabla


def mostrar_columna_entera(tabla: QTableWidget, columna: int, de_mas: int = 0):
    """
    Ensancha `columna` lo justo para que su texto más largo se lea entero
    (llamarla después de llenar la tabla), con `de_mas` píxeles más si la
    celda se escribe (el campo que se abre tiene borde y relleno). Nunca la
    achica.

    Pensada para la columna de códigos de barras: Qt corta con "..." lo que
    no entra, y en la de 100 px de siempre un EAN-13 como 7798113301024 se
    veía "77981133010…". Parecía guardado con dos dígitos menos y se lo
    buscaba así, sin encontrarlo (2026-10-18).
    """
    necesario = max(tabla.sizeHintForColumn(columna) + de_mas,
                    tabla.horizontalHeader().sectionSizeHint(columna))
    if necesario > tabla.columnWidth(columna):
        tabla.setColumnWidth(columna, necesario)


def hoy_del_local() -> QDate:
    """
    El día del local en curso (de 06:00 a 06:00, ver turnos.HORA_CAMBIO_DE_DIA):
    hasta las 06:00 sigue siendo AYER, porque se está en la Noche que empezó ayer.
    Es el "hoy" de los reportes de ventas: a las 02:00, "Solo Hoy" tiene que
    mostrar la Noche en curso, no un día que todavía no empezó.
    """
    dia = dia_en_que_empezo_el_turno(datetime.now())
    return QDate(dia.year, dia.month, dia.day)


def crear_selector_de_fecha(fecha_inicial: QDate = None) -> QDateEdit:
    """
    Un campo de fecha con calendario desplegable, que arranca en
    `fecha_inicial` (hoy, por defecto). Qt pinta de rojo los sábados y
    domingos del calendario; acá se los deja como cualquier otro día, para
    que en los reportes el rojo no parezca un aviso.
    """
    campo = QDateEdit(fecha_inicial or QDate.currentDate())
    campo.setCalendarPopup(True)
    calendario = campo.calendarWidget()
    dia_comun = calendario.weekdayTextFormat(Qt.Monday)
    for dia in (Qt.Saturday, Qt.Sunday):
        calendario.setWeekdayTextFormat(dia, dia_comun)
    return campo


def armar_filtro_por_fechas(buscar, desde_inicial=None, extras=(), solo_hoy=False, estirar=True,
                            dias_del_local=False):
    """
    Arma la fila de filtros de las pantallas que consultan un rango de
    fechas: "Desde", "Hasta", lo que cada pantalla agregue (`extras`), el
    botón "Solo Hoy" (si se pide) y "Buscar".

    Devuelve (fecha_desde, fecha_hasta, layout): los dos QDateEdit, con
    calendario desplegable, para que la pantalla lea el rango, y la fila ya
    armada para agregarla a su layout.

    - `buscar`: función sin argumentos que hace la búsqueda; la disparan el
      botón "Buscar" y Enter en el último campo.
    - `desde_inicial`: QDate con el que arranca "Desde" (hoy, por defecto);
      "Hasta" siempre arranca en hoy.
    - `extras`: lista de (etiqueta, widget) que van entre "Hasta" y los
      botones (por ejemplo, un combo "Agrupar:"). Entran en la cadena de
      Enter, en ese orden.
    - `solo_hoy`: agrega "Solo Hoy", que pone las dos fechas en hoy y busca.
    - `estirar`: deja los botones pegados a la izquierda.
    - `dias_del_local`: "hoy" es el día del local (hoy_del_local), no el del
      calendario. Lo usan los reportes de ventas, que cuentan los días de 06:00 a
      06:00; el resto (historiales de accesos, de artículos) sigue con el calendario.
    """
    hoy = hoy_del_local() if dias_del_local else QDate.currentDate()
    fecha_desde = crear_selector_de_fecha(desde_inicial if desde_inicial is not None else hoy)
    fecha_hasta = crear_selector_de_fecha(hoy)

    filtros = QHBoxLayout()
    filtros.addWidget(QLabel("Desde:"))
    filtros.addWidget(fecha_desde)
    filtros.addWidget(QLabel("Hasta:"))
    filtros.addWidget(fecha_hasta)
    for etiqueta, widget in extras:
        filtros.addWidget(QLabel(etiqueta))
        filtros.addWidget(widget)

    if solo_hoy:
        def poner_solo_hoy():
            # Se recalcula al apretar: la ventana puede haber quedado abierta
            # desde antes de las 06:00, o desde el día anterior.
            hoy_ahora = hoy_del_local() if dias_del_local else QDate.currentDate()
            fecha_desde.setDate(hoy_ahora)
            fecha_hasta.setDate(hoy_ahora)
            buscar()

        boton_hoy = QPushButton("Solo Hoy")
        boton_hoy.clicked.connect(poner_solo_hoy)
        filtros.addWidget(boton_hoy)
    boton_buscar = QPushButton("Buscar")
    boton_buscar.clicked.connect(buscar)
    filtros.addWidget(boton_buscar)
    if estirar:
        filtros.addStretch()

    encadenar_enter(fecha_desde, fecha_hasta, *[widget for _, widget in extras], accion_final=buscar)
    return fecha_desde, fecha_hasta, filtros


def fecha_iso(fecha: QDate) -> str:
    """Una fecha de Qt como "YYYY-MM-DD", el formato con que los repos
    guardan y comparan fechas."""
    return fecha.toString("yyyy-MM-dd")


def rango_de_fechas(fecha_desde: QDateEdit, fecha_hasta: QDateEdit):
    """Las dos puntas de un filtro Desde/Hasta (ver `armar_filtro_por_fechas`)
    como "YYYY-MM-DD", listas para pasarle a un repo: `(desde, hasta)`."""
    return fecha_iso(fecha_desde.date()), fecha_iso(fecha_hasta.date())


# Cuadros de mensaje. Siempre usarlos en vez de QMessageBox directo, así el
# tono (error / aviso / información) queda igual en todas las pantallas.

def mostrar_error(padre, titulo: str, mensaje: str):
    """Algo no se pudo hacer (dato inválido, falta un campo, etc.)."""
    QMessageBox.critical(padre, titulo, mensaje)


def mostrar_aviso(padre, titulo: str, mensaje: str):
    """Advertencia que no impide seguir."""
    QMessageBox.warning(padre, titulo, mensaje)


def mostrar_info(padre, titulo: str, mensaje: str):
    """Confirmación de que algo salió bien."""
    QMessageBox.information(padre, titulo, mensaje)


def confirmar(padre, titulo: str, mensaje: str) -> bool:
    """Pregunta Sí/No (No por defecto, para que un Enter apurado no
    confirme algo destructivo). True si eligió Sí."""
    respuesta = QMessageBox.question(
        padre, titulo, mensaje, QMessageBox.Yes | QMessageBox.No, QMessageBox.No
    )
    return respuesta == QMessageBox.Yes


def icono_de_emoji(emoji: str, tamano_px: float):
    """
    El emoji dibujado como ícono, recortado justo a su borde: (QIcon, QSize). Sirve para un
    dibujito más grande que la letra del botón (un emoji dentro del texto mide lo que la letra).
    `tamano_px` es el tamaño de letra con que se lo dibuja; se dibuja a la escala de la pantalla
    para que no salga borroso.
    """
    pantalla = QGuiApplication.primaryScreen()
    escala = pantalla.devicePixelRatio() if pantalla is not None else 1.0
    letra = QFont("Segoe UI Emoji")
    letra.setPixelSize(max(1, round(tamano_px * escala)))
    lado = 2 * letra.pixelSize()
    imagen = QImage(lado, lado, QImage.Format_ARGB32_Premultiplied)
    imagen.fill(Qt.transparent)
    pintor = QPainter(imagen)
    pintor.setFont(letra)
    pintor.drawText(QRect(0, 0, lado, lado), Qt.AlignCenter, emoji)
    pintor.end()
    pintados = [(x, y) for y in range(lado) for x in range(lado) if imagen.pixelColor(x, y).alpha()]
    if pintados:
        xs, ys = [x for x, _y in pintados], [y for _x, y in pintados]
        imagen = imagen.copy(min(xs), min(ys), max(xs) - min(xs) + 1, max(ys) - min(ys) + 1)
    dibujo = QPixmap.fromImage(imagen)
    dibujo.setDevicePixelRatio(escala)
    return QIcon(dibujo), QSize(round(imagen.width() / escala), round(imagen.height() / escala))
