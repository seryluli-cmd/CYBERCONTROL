"""
programas_pc_repo.py
=====================
"Programas y estado" del clic derecho de una PC en Control de PCs (pedido del dueño,
2026-10-22; la ventana es control_pcs/ui/pcs_programas_dialogo.py): cómo está la PC, qué
programas tiene abiertos (cerrar el que se trabó) y qué íconos hay en su escritorio (abrir uno).
Para cualquier operador.

Todo viaja como comandos (ver comandos_pc_repo): INFO_PC trae el estado, los programas y los
íconos en JSON; CERRAR_PROGRAMA y ABRIR_PROGRAMA contestan "OK: ..." o "ERROR: ...". El Cliente
PC (CLIENTE PC/programas_pc.py) solo cierra algo de su lista de ese momento y solo abre un ícono
de su escritorio: desde acá no se puede cerrar un proceso cualquiera ni abrir un archivo
cualquiera. Lo contesta un Cliente PC desde la dominio.VERSION_CLIENTE_PROGRAMAS: a una PC que
avisó una versión anterior ni se le manda (`le_falta_la_version`).

Cada INFO_PC deja su respuesta (unas pocas letras por programa e ícono) en la fila del comando;
al pedir uno nuevo para esa PC se vacían las de antes, que ya nadie mira: así la base no crece
con cada vez que se abre la ventana.
"""

import json

import dominio
from database import conexion_db
from control_pcs.repositories import actualizacion_cliente_repo, comandos_pc_repo

RESPUESTA_QUE_NO_SE_ENTIENDE = "La PC mandó una respuesta que no se entiende."


def le_falta_la_version(estacion) -> bool:
    """¿Esa PC avisó un Cliente PC anterior a la V1.6 (o ninguno)? Entonces no contesta nada de
    "Programas y estado" ni del mantenimiento a distancia."""
    numero = estacion["numero_version_cliente"] if "numero_version_cliente" in estacion.keys() else None
    return not numero or actualizacion_cliente_repo.es_mas_vieja(numero, dominio.VERSION_CLIENTE_PROGRAMAS)


def pedir_info(estacion_id: int) -> int:
    """Le pide a la PC su estado, sus programas y sus íconos. Devuelve el id del comando."""
    with conexion_db() as conexion:
        conexion.execute(
            "UPDATE comandos_pc SET resultado = NULL WHERE estacion_id = ? AND tipo = ? AND estado = ? "
            "AND resultado IS NOT NULL",
            (estacion_id, comandos_pc_repo.TIPO_INFO_PC, dominio.ESTADO_COMANDO_ENTREGADO),
        )
    return comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_INFO_PC)


def _texto(valor, largo: int = 200) -> str:
    return str(valor if valor is not None else "")[:largo]


def _entero(valor):
    return valor if isinstance(valor, int) and not isinstance(valor, bool) and valor >= 0 else None


def leer_info(resultado: str) -> dict:
    """Lo que contestó la PC a un INFO_PC, revisado: {"estado", "programas", "iconos"}.

    "estado": {"discos": [{"unidad", "libre", "total"}], "memoria": {"usada", "total"} o None,
    "cpu", "prendida", "temp_cpu", "temp_gpu" (enteros o None), "version"}. "programas":
    [{"pid", "exe", "titulo", "no_responde"}]. "iconos": [nombres]. Lo que no vino o no se
    entiende queda vacío. ValueError con el motivo si la PC contestó un error o algo que no es
    esa respuesta."""
    texto = str(resultado or "")
    if texto.startswith("ERROR:"):
        raise ValueError(texto[len("ERROR:"):].strip() or RESPUESTA_QUE_NO_SE_ENTIENDE)
    try:
        datos = json.loads(texto)
    except ValueError:
        raise ValueError(RESPUESTA_QUE_NO_SE_ENTIENDE) from None
    if not isinstance(datos, dict):
        raise ValueError(RESPUESTA_QUE_NO_SE_ENTIENDE)

    estado = datos.get("estado") if isinstance(datos.get("estado"), dict) else {}
    discos = []
    for disco in estado.get("discos") or []:
        if isinstance(disco, dict) and _entero(disco.get("libre")) is not None and _entero(disco.get("total")):
            discos.append({"unidad": _texto(disco.get("unidad"), 3), "libre": disco["libre"], "total": disco["total"]})
    memoria = estado.get("memoria")
    if not (isinstance(memoria, dict) and _entero(memoria.get("usada")) is not None and _entero(memoria.get("total"))):
        memoria = None
    else:
        memoria = {"usada": memoria["usada"], "total": memoria["total"]}

    programas = []
    for programa in datos.get("programas") or []:
        if isinstance(programa, dict) and _entero(programa.get("pid")) is not None:
            programas.append({
                "pid": programa["pid"], "exe": _texto(programa.get("exe")), "titulo": _texto(programa.get("titulo")),
                "no_responde": programa.get("no_responde") is True,
            })
    iconos = [_texto(icono) for icono in datos.get("iconos") or [] if isinstance(icono, str) and icono]

    return {
        "estado": {
            "discos": discos, "memoria": memoria, "cpu": _entero(estado.get("cpu")),
            "prendida": _entero(estado.get("prendida")), "temp_cpu": _entero(estado.get("temp_cpu")),
            "temp_gpu": _entero(estado.get("temp_gpu")), "version": _texto(estado.get("version"), 10),
        },
        "programas": programas,
        "iconos": iconos,
    }


def cerrar_programa(estacion_id: int, programa: dict) -> int:
    """Le pide a la PC cerrar a la fuerza `programa` (uno de los de `leer_info`). Devuelve el id
    del comando."""
    payload = json.dumps({"pid": programa["pid"], "exe": programa["exe"]})
    return comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_CERRAR_PROGRAMA, payload)


def abrir_programa(estacion_id: int, icono: str) -> int:
    """Le pide a la PC abrir el ícono de su escritorio que se llama `icono`. Devuelve el id del
    comando."""
    return comandos_pc_repo.encolar_comando(estacion_id, comandos_pc_repo.TIPO_ABRIR_PROGRAMA, icono)


def leer_respuesta(resultado: str) -> tuple:
    """(salió bien, texto) de un "OK: ..." o "ERROR: ..." que contestó la PC."""
    texto = str(resultado or "")
    for prefijo, ok in (("OK:", True), ("ERROR:", False)):
        if texto.startswith(prefijo):
            return ok, texto[len(prefijo):].strip()
    return False, RESPUESTA_QUE_NO_SE_ENTIENDE
