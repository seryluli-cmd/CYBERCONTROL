"""
congelado_repo.py
===================
Congelar y descongelar las PCs con Shadow Defender desde el mostrador
(pedido del dueño, 2026-10-18: para instalar o actualizar algo sin ir PC por
PC). Shadow Defender no tiene consola de red: cada PC lo hace con su CmdTool.exe
cuando su Cliente PC recibe el comando (ver CLIENTE PC/shadow_defender.py). Acá
solo se decide qué se manda y a qué PCs, y se traduce lo que contestan.

Reglas:
- **La clave de Shadow Defender no se guarda en ningún lado.** La escribe el
  dueño en la ventana cada vez; viaja en el payload del comando y
  comandos_pc_repo la borra apenas la PC la recibe o, si no la pide, a los
  MINUTOS_VIGENCIA_CON_CLAVE. Sin la clave correcta CmdTool no hace nada, así
  que una empleada que abra la ventana no puede descongelar.
- **Descongelar reinicia la PC** (Shadow Defender suelta el disco recién al
  reiniciar): no se le manda a una PC con un cliente usándola, y si se eligió
  alguna no se manda nada. El Cliente PC lo vuelve a revisar por las dudas.
- **Congelar y ver cómo está tampoco van a una PC con un cliente**, aunque no
  reinician: la clave viajaría a una PC donde el cliente es Administrador de
  Windows y podría verla (CmdTool la lleva en su línea de comandos). Esas PCs
  se saltean y las demás se hacen igual; la ventana lo avisa en su renglón
  (pedido del dueño, 2026-10-19).
"""

import json

import dominio
from control_pcs.repositories import comandos_pc_repo, pcs_repo

DESCONGELAR = dominio.COMANDO_DESCONGELAR
CONGELAR = dominio.COMANDO_CONGELAR
ESTADO = dominio.COMANDO_ESTADO_CONGELADO

# Cuánto espera la ventana la respuesta de cada PC: una PC prendida pide su
# comando en 5 s y CmdTool tarda un instante. Menos que la vigencia de la clave
# (comandos_pc_repo.MINUTOS_VIGENCIA_CON_CLAVE), así nunca queda una clave
# esperando en la cola sin que nadie espere la respuesta.
SEGUNDOS_ESPERA_RESPUESTA = 45

DISCOS_DE_SIEMPRE = "C"


def normalizar_discos(texto) -> str:
    """Las letras de los discos, en mayúscula y sin repetir: "c" -> "C",
    "C, D" -> "CD". Acepta espacios, comas y dos puntos entre letras; cualquier
    otra cosa es un error (mejor avisar que adivinar qué disco quiso decir)."""
    letras = ""
    for caracter in str(texto or "").upper():
        if "A" <= caracter <= "Z":
            if caracter not in letras:
                letras += caracter
        elif caracter not in " ,;:":
            raise ValueError("Los discos se escriben con su letra: C, o C y D.")
    if not letras:
        raise ValueError("Escribí qué discos (casi siempre C).")
    return letras


def esta_ocupada(item) -> bool:
    """¿Hay un cliente usando la PC? (un item de pcs_repo.estado_estaciones)"""
    return item["sesion"] is not None and bool(item["segundos_restantes"])


def pedir(estacion_ids, tipo: str, clave: str, discos: str = DISCOS_DE_SIEMPRE) -> dict:
    """
    Le manda `tipo` (DESCONGELAR, CONGELAR o ESTADO) a cada PC de
    `estacion_ids`. Devuelve {estacion_id: comando_id} para esperar las
    respuestas; una PC elegida que no está ahí se salteó porque tiene un
    cliente (CONGELAR y ESTADO, ver texto_salteada). Levanta ValueError (con un
    texto para la pantalla) sin mandar nada si falta la clave, los discos están
    mal, alguna PC no existe o, para descongelar, alguna tiene un cliente.
    """
    if tipo not in dominio.COMANDOS_CON_CLAVE:
        raise ValueError(f"Pedido desconocido: {tipo}")
    if not clave:
        raise ValueError("Escribí la clave de Shadow Defender.")
    discos = normalizar_discos(discos)
    estacion_ids = list(dict.fromkeys(estacion_ids))
    if not estacion_ids:
        raise ValueError("Elegí al menos una PC.")

    por_id = {item["estacion"]["id"]: item for item in pcs_repo.estado_estaciones()}
    faltan = [estacion_id for estacion_id in estacion_ids if estacion_id not in por_id]
    if faltan:
        raise ValueError("Alguna de las PCs elegidas ya no está activa. Cerrá y volvé a abrir la ventana.")
    ocupadas = [estacion_id for estacion_id in estacion_ids if esta_ocupada(por_id[estacion_id])]
    if tipo == DESCONGELAR and ocupadas:
        nombres = [por_id[estacion_id]["estacion"]["nombre"] for estacion_id in ocupadas]
        raise ValueError(
            "Descongelar reinicia la PC, y estas tienen un cliente usándolas: "
            f"{', '.join(nombres)}. Descongelalas cuando estén libres."
        )

    payload = json.dumps({"clave": clave, "discos": discos})
    return {
        estacion_id: comandos_pc_repo.encolar_comando(estacion_id, tipo, payload)
        for estacion_id in estacion_ids
        if estacion_id not in ocupadas
    }


def interpretar_respuesta(resultado):
    """`(salió bien, texto)` de lo que contestó la PC ("OK: ..." / "ERROR: ...",
    ver CLIENTE PC/cliente_pc._congelar_o_descongelar), o None si todavía no
    contestó."""
    if not resultado:
        return None
    if resultado.startswith("OK:"):
        return True, resultado[3:].strip()
    if resultado.startswith("ERROR:"):
        return False, resultado[6:].strip()
    return False, resultado


def texto_salteada() -> str:
    """Qué decir de una PC elegida a la que `pedir` no le mandó nada por tener un cliente."""
    return "Salteada: tiene un cliente usándola. Probá de nuevo cuando esté libre."


def texto_sin_respuesta() -> str:
    """Qué decir de una PC que no contestó en SEGUNDOS_ESPERA_RESPUESTA."""
    return ("No contestó: está apagada, sin conexión, o su Cliente PC es de antes del "
            "18/10/2026 y no sabe congelar.")
