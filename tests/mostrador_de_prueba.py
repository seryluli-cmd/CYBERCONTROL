"""
tests/mostrador_de_prueba.py
=============================
Un "mostrador" para las pruebas de la administración desde otra PC
(tests/test_admin_remoto.py): una base de PRUEBA en la carpeta que se le pasa,
con algunos datos, y el servidor de red atendiendo en 127.0.0.1 en un puerto
libre. Escribe ese puerto en la salida y se cierra solo cuando la prueba le
cierra la entrada (o lo termina).

Corre en un proceso APARTE a propósito: la prueba convierte su propio proceso
en una copia remota (admin_remoto.cliente.instalar cierra la base y reemplaza
los repos), y el mostrador necesita sus repos de verdad.

No se llama test_*.py para que unittest no lo tome como una prueba.

    python tests/mostrador_de_prueba.py <carpeta de la base>
"""

import os
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import database  # noqa: E402
import dominio  # noqa: E402

CLAVE_ADMIN = "1234"      # la de fábrica del primer Administrador (database._cargar_datos_iniciales)
CLAVE_EMPLEADA = "4321"
CODIGO_ALFAJOR = "7790001"
# Dos PCs para la grilla de la pantalla principal: la primera con un bono.
PC_OCUPADA = "PC1"
PC_LIBRE = "PC2"
# Reemplaza a la contraseña real de ORDENAR Stock, que no se escribe en el repo.
CLAVE_ORDENAR_STOCK = "clave-de-prueba"


def preparar_base(carpeta: str):
    database.DATA_DIR = carpeta
    database.DB_PATH = os.path.join(carpeta, "kiosko_prueba.db")
    database.inicializar_base_de_datos()

    from repositories import admin_remoto_repo, articulos_repo, turnos_repo, usuarios_repo, ventas_repo
    from control_pcs.repositories import pcs_repo

    articulos_repo.CLAVE_ORDENAR_STOCK = database.hash_clave(CLAVE_ORDENAR_STOCK)
    admin = usuarios_repo.listar_usuarios()[0]
    admin_remoto_repo.activar(admin["id"], True)
    usuarios_repo.crear_usuario("LUCIA", CLAVE_EMPLEADA, dominio.ROL_EMPLEADA)
    lucia = next(u for u in usuarios_repo.listar_usuarios() if u["nombre"] == "LUCIA")

    rubro_id = articulos_repo.listar_rubros()[0]["id"]
    articulos_repo.crear_articulo(CODIGO_ALFAJOR, "Alfajor de prueba", None, rubro_id, 1000.0, 600.0, 2)
    linea = {"codigo": CODIGO_ALFAJOR, "descripcion": "Alfajor de prueba", "cantidad": 2, "precio_unitario": 1000.0}
    efectivo = [{"metodo": dominio.PAGO_EFECTIVO, "monto": 2000.0}]
    # Una venta que queda en un cierre (para Control de Cierres) y otra después,
    # para anular. El bono de la PC también queda en el cierre.
    ventas_repo.confirmar_venta(lucia["id"], [linea], efectivo)
    ocupada = pcs_repo.crear_estacion(PC_OCUPADA)
    pcs_repo.crear_estacion(PC_LIBRE)
    bono_id = pcs_repo.crear_bono("1 hora", 60, 1500.0)
    pcs_repo.asignar_bono(ocupada, bono_id, lucia["id"], [{"metodo": dominio.PAGO_EFECTIVO, "monto": 1500.0}])
    turnos_repo.cerrar_turno(lucia["id"])
    ventas_repo.confirmar_venta(lucia["id"], [linea], efectivo)


def _cerrar_cuando_se_cierre_la_entrada():
    sys.stdin.read()
    os._exit(0)


def main():
    preparar_base(sys.argv[1])

    from http.server import ThreadingHTTPServer
    import servidor_red

    servidor = ThreadingHTTPServer(("127.0.0.1", 0), servidor_red._ManejadorEstado)
    threading.Thread(target=_cerrar_cuando_se_cierre_la_entrada, daemon=True).start()
    print(servidor.server_address[1], flush=True)
    servidor.serve_forever()


if __name__ == "__main__":
    main()
