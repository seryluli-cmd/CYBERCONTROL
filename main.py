"""
main.py
========
Punto de entrada del programa. Al ejecutar este archivo:
1. Se verifica que no haya otra copia abierta en la misma PC.
2. Se prepara la base de datos (si es la primera vez, se crea) y arrancan
   las copias de seguridad automáticas (repositories/copias_repo.py: después
   de cada Cierre de Turno y cada 8 horas, con el programa abierto).
3. Se levanta el servidor de red que consultan las PCs cliente
   (servidor_red.py).
4. Se muestra la pantalla de Login.
5. Al loguearse correctamente, se abre la ventana principal con los
   permisos que correspondan según el rol del usuario.
6. Al cerrar sesión desde la ventana principal, se vuelve al Login
   (sin tener que reabrir todo el programa).

Si el programa se abrió desde la carpeta compartida del mostrador (otra PC del
local, ver admin_remoto/modo.py), es una copia para ADMINISTRAR desde ahí: no
toca ninguna base ni levanta el servidor de las PCs, se conecta al CyberBIOS
del mostrador y le pide todo a él (pasos 2 y 3 los hace el mostrador).

Para arrancar el sistema, se ejecuta:  python main.py
"""

import gc
import socket
import sys
import traceback
from pathlib import Path
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QMessageBox
from PySide6.QtGui import QIcon

from admin_remoto import cliente as cliente_remoto, modo as modo_remoto
from database import inicializar_base_de_datos
from repositories import copias_repo
from servidor_red import iniciar_servidor
from ui.hoja_de_estilos import HOJA_DE_ESTILOS
from ui.ingreso_caja import resolver_caja_al_entrar
from ui.login_window import LoginWindow
from ui.main_window import MainWindow


# --------------------------------------------------------------------
# Rutas de recursos
# --------------------------------------------------------------------
# Carpeta del programa (donde está este archivo), para ubicar el ícono
# sin importar desde qué directorio se lo ejecute.
CARPETA_BASE = Path(__file__).resolve().parent
RUTA_ICONO = CARPETA_BASE / "assets" / "icono.ico"


# --------------------------------------------------------------------
# Instancia única (una sola copia de Kiosko por PC)
# --------------------------------------------------------------------
# Puerto dedicado SOLO para detectar una segunda copia abierta -- no tiene
# nada que ver con servidor_red.PUERTO_SERVIDOR (8899, el que hablan los
# Clientes PC). Bindear un socket TCP en localhost es un "mutex" de
# instancia única liviano y sin dependencias nuevas: el sistema operativo
# libera el puerto solo en cuanto el proceso termina, sea un cierre normal
# o un crash, así que nunca queda un candado colgado que obligue a
# reiniciar Windows para poder volver a abrir el programa.
PUERTO_INSTANCIA_UNICA = 8898

# Referencia viva al socket-candado: si se dejara que el recolector de
# basura la destruya, el socket se cerraría solo y el "candado" dejaría de
# valer apenas terminara main(). Mantenerla acá arriba lo mantiene abierto
# mientras el proceso siga vivo.
_candado_instancia_unica = None


def _ya_hay_una_copia_abierta() -> bool:
    """True si otra copia del programa ya tiene tomado el puerto-candado.
    Si no, toma el candado para esta copia y devuelve False."""
    global _candado_instancia_unica
    candado = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    try:
        candado.bind(("127.0.0.1", PUERTO_INSTANCIA_UNICA))
    except OSError:
        candado.close()
        return True
    _candado_instancia_unica = candado
    return False




def aplicar_estilo(app):
    """
    Deja el aspecto de todo el programa en un solo lugar (lo usan main() y las
    pruebas de pantalla): estilo Fusion (look limpio y parejo entre PCs), esquema
    de color CLARO y la hoja de estilos (ui/hoja_de_estilos.py).

    El esquema claro se fija a propósito: Fusion toma los colores de Windows, y con
    el modo oscuro puesto los cuadros que la hoja no pinta (el log de "Actividad
    reciente", la numeración de las filas) salían negros y con la letra oscura de la
    hoja encima, o sea casi ilegibles. El programa está diseñado en claro.
    """
    app.setStyle("Fusion")
    app.styleHints().setColorScheme(Qt.ColorScheme.Light)
    app.setStyleSheet(HOJA_DE_ESTILOS)


class Aplicacion:
    """
    Pequeña clase que coordina el ir y venir entre la pantalla de Login
    y la ventana principal, para poder "cerrar sesión" y volver a
    loguearse sin cerrar todo el programa.
    """

    def __init__(self, conexion_remota=None):
        # La conexión con el mostrador si esta es una copia para administrar
        # desde otra PC (ver main y admin_remoto/); None en el mostrador.
        self.conexion_remota = conexion_remota
        self.ventana_principal = None
        self.ventana_login = None
        self._mostrar_login()

    def _mostrar_login(self):
        if self.conexion_remota is not None:
            # Cerrar sesión en la otra PC también la cierra en el mostrador.
            self.conexion_remota.salir()
            try:
                self.ventana_login = LoginWindow(al_loguearse=self._al_loguearse)
            except (ValueError, PermissionError) as error:  # sin red, o la entrada se apagó
                QMessageBox.warning(None, "Administrar desde otra PC", str(error))
                QApplication.quit()
                return
        else:
            self.ventana_login = LoginWindow(al_loguearse=self._al_loguearse)
        self.ventana_login.show()

    def _al_loguearse(self, usuario):
        # Antes de entrar, la caja tiene que quedar lista: abrirla contando el
        # cambio, recibirla de quien cubrió el turno o cerrar la de quien se fue
        # (ver ui/ingreso_caja.py). Si se cancela, se queda en el ingreso. Desde
        # otra PC no: ahí no hay cajón (y solo entra el Administrador).
        if self.conexion_remota is None and not resolver_caja_al_entrar(self.ventana_login, usuario):
            return
        self.ventana_login.close()
        self.ventana_principal = MainWindow(usuario, al_cerrar_sesion=self._mostrar_login)
        self.ventana_principal.showMaximized()


def _manejar_excepcion_no_capturada(tipo, valor, tb):
    """
    Red de seguridad final: cada pantalla ya envuelve sus propias
    acciones con el decorador `manejar_errores` (ver ui/utils.py), pero
    esto cubre cualquier excepción que igual se escape de ahí (por
    ejemplo, durante la construcción de una ventana). En vez de que la
    aplicación se cierre en silencio o quede en un estado raro, se deja
    el detalle en el log y se avisa con un cartel.
    """
    traceback.print_exception(tipo, valor, tb)
    try:
        from errores import registrar_error
        registrar_error(valor)
    except Exception:
        pass
    try:
        QMessageBox.critical(
            None, "Ocurrió un error inesperado",
            "Algo falló y quedó registrado en data/errores.log.\n"
            "Conviene cerrar y volver a abrir el programa si algo se ve raro.\n\n"
            f"({tipo.__name__}: {valor})"
        )
    except Exception:
        pass


def main():
    # Recolector cíclico de basura desactivado a propósito. Un QTimer
    # conectado a un método propio (ej. PanelControlPcs._timer ->
    # self._refrescar) arma un ciclo de referencias que solo ese recolector
    # puede romper, y puede dispararse desde CUALQUIER hilo que esté
    # asignando memoria, no solo el hilo dueño del QObject. Como
    # servidor_red.py corre un hilo de fondo real todo el tiempo, ese hilo
    # podía destruir un QTimer de la interfaz: Qt tira "QObject::killTimer:
    # Timers cannot be stopped from another thread" y deja el objeto C++
    # roto -- el origen de los "Internal C++ object already deleted" de
    # data/errores.log. Qt libera sus QObject solo por relación
    # padre/hijo y el resto del programa no depende de ciclos; lo único que
    # se pierde son unos pocos ciclos de la UI (uno por pantalla con
    # timer), que en un programa que se reinicia a diario no pesan.
    gc.disable()
    sys.excepthook = _manejar_excepcion_no_capturada
    # QApplication se crea PRIMERO (antes de tocar la base o el servidor)
    # porque el cartel de "ya hay una copia abierta" necesita una
    # QApplication viva para poder mostrarse.
    app = QApplication(sys.argv)
    if _ya_hay_una_copia_abierta():
        QMessageBox.warning(
            None, "Kiosko ya está abierto",
            "Ya hay una copia de Kiosko abierta en esta PC.\n\n"
            "Cerrala antes de abrir otra -- tener dos copias a la vez "
            "puede pisar cambios entre ellas."
        )
        sys.exit(0)
    aplicar_estilo(app)
    # Ícono de la caja registradora: al ponerlo en la aplicación (y no en
    # cada ventana por separado), TODAS las ventanas y cuadros de diálogo
    # lo heredan automáticamente en la esquina superior izquierda, en vez
    # del ícono genérico de Qt.
    app.setWindowIcon(QIcon(str(RUTA_ICONO)))

    mostrador = modo_remoto.direccion_del_mostrador()
    if mostrador is not None:
        conexion_remota = _conectar_con_el_mostrador(mostrador)
        if conexion_remota is None:
            sys.exit(0)
        Aplicacion(conexion_remota)
        sys.exit(app.exec())

    inicializar_base_de_datos()
    copias_repo.iniciar_copias_automaticas()
    # Corre todo el tiempo que Kiosko esté abierto, sin importar quién
    # esté logueado -- es lo que consultan las PCs bloqueadas del local
    # (ver servidor_red.py y la carpeta hermana "CLIENTE PC").
    iniciar_servidor()
    Aplicacion()
    sys.exit(app.exec())


def _conectar_con_el_mostrador(mostrador: str):
    """
    Esta copia se abrió desde otra PC (ver admin_remoto/modo.py): se presenta al
    CyberBIOS del mostrador y, si está y deja entrar, hace que todas las
    pantallas le pidan los datos a él. Devuelve la conexión, o None después de
    avisar por qué no se puede (el mostrador cerrado, la entrada apagada, otro
    .exe).
    """
    try:
        conexion = cliente_remoto.conectar(mostrador)
    except (ValueError, PermissionError) as error:
        QMessageBox.warning(None, "Administrar desde otra PC", str(error))
        return None
    cliente_remoto.instalar(conexion)
    return conexion


if __name__ == "__main__":
    main()
