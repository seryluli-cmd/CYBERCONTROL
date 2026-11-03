# Dos PCs que se reiniciaron y "se les borró el tiempo" (02/11/2026)

Lo que contó el empleado: a dos chicos se les reinició la PC mientras jugaban y, cuando volvió,
ya no tenían tiempo. Los dos tenían bonos comunes, no eran socios.

Esto es una revisión del código de CYBERCONTROL (el mostrador) y del Cliente PC. **No se cambió
nada.** Todavía no vi la base del local ni las PCs: lo de abajo dice qué puede haber pasado y cómo
confirmarlo, no qué pasó.

---

## Lo corto

1. **Un reinicio no borra el tiempo, por sí solo.** El mostrador no guarda "cuánto le queda": guarda
   la **hora en que termina** la sesión. La PC vuelve, pregunta y sigue con lo que le queda. Esto
   está comprobado en el código y lo prueban los tests (`test_una_pc_que_se_reinicia_sigue_con_su_sesion_y_su_tiempo`).
2. **Pero el reloj sigue corriendo mientras la PC se reinicia.** Si el reinicio tarda (Windows
   Update puede tardar 10 a 30 minutos) y le quedaba poco al bono, el tiempo se puede terminar en el
   medio. La PC vuelve bloqueada y parece que el tiempo "se borró".
3. **La otra forma de perder el tiempo es que la sesión se cierre en el mostrador.** Pasa con
   "Cerrar sesión y reiniciar", con "Finalizar Sesión" o con "Intercambiar de máquina". A los 5
   segundos la PC se entera y **se reinicia sola**. Desde la silla se ve igual que la otra: "se
   reinició y perdí el tiempo". Con un **bono no se devuelve nada**; con un socio, lo que sobra
   vuelve a su saldo.
4. **Para saber cuál fue hace falta la base del local.** "Actividad reciente" muestra solo los
   últimos 30 movimientos, así que lo de ayer ya no se ve en pantalla. Está todo en la base.

---

## Cada cuánto se comunican

| Qué | Cada cuánto |
|---|---|
| El Cliente PC le pregunta al mostrador "¿estoy bloqueada? ¿cuánto me queda?" | **cada 5 segundos** |
| Cuánto espera el Cliente PC cada respuesta | 3 segundos (si no llega, cuenta como falla) |
| La pantalla de PCs del mostrador se actualiza, y ahí **cierra las sesiones que llegaron a cero** | cada 5 segundos |
| El mostrador marca la PC **SIN CLIENTE** (titilando) | a los **30 segundos** sin noticias |
| El seguro de fin de sesión (una tarea de Windows en cada PC) reinicia la PC si el Cliente PC no lo hizo | a la hora de fin **+ 2 minutos** |

Un detalle importante: **el mostrador nunca le habla a la PC; solo le contesta.** Las órdenes
(Reiniciar, Apagar, Mensaje, Descongelar...) viajan dentro de la respuesta a esa consulta de cada
5 segundos. Por eso tardan hasta 5 segundos en llegar, y no le llegan a una PC con el Cliente PC
cerrado.

---

## Qué pasa cuando NO se comunican

| Caso | Qué ve el chico | Qué ve el empleado | Qué pasa con el tiempo |
|---|---|---|---|
| **Se corta la red o falla el cable** | Sigue jugando; la PC cuenta el tiempo sola | A los 30 s, SIN CLIENTE titilando | Al volver la red, **gana el menor** entre la cuenta de la PC y la del mostrador, y queda anotado ("volvió la conexión y se tomó el tiempo de la PC"). Si el tiempo se termina durante el corte, la PC se reinicia sola y queda bloqueada |
| **El Cliente PC se cerró o se trabó** | La PC queda **sin bloqueo** | SIN CLIENTE titilando | El tiempo corre en el mostrador. Al terminar, el seguro de Windows reinicia la PC (fin + 2 min) y el mostrador titila TIEMPO AGOTADO hasta que la PC vuelva o alguien apriete "Ya revisé la PC" |
| **La PC se reinicia** (luz, pantalla azul, Windows Update, botón de reset, orden Reiniciar) | Se apaga y vuelve en un minuto o dos, **con su tiempo** | SIN CLIENTE mientras tanto. Al volver, Actividad reciente anota el corte "la PC se reinició" y aclara si la reinició el Cliente PC o **no** (luz, cuelgue, Windows Update o alguien con el botón) | La sesión sigue igual, pero **los minutos del reinicio se descuentan**. Si el bono se termina en el medio, vuelve bloqueada |
| **El mostrador está cerrado o reiniciándose** | Sigue jugando; cada PC cuenta sola | — | No se pierde nada: el mostrador guarda la hora de fin. **Ojo:** una PC que se reinicia mientras el mostrador está caído **vuelve bloqueada** hasta que el mostrador responde. Está hecho así a propósito para no regalar tiempo; el tiempo sigue corriendo mientras tanto |

**Shadow Defender:** si la PC está congelada, cada reinicio borra lo que el chico tenía en el juego
(partidas guardadas, sesiones iniciadas). El tiempo no lo toca: está en el mostrador. Hay que
preguntar qué se borró, si el tiempo o lo del juego.

---

## Lo de ayer: causas posibles

Sin la base no las puedo ordenar con certeza. Este orden es lo que me parece más probable:

1. **Se terminó la sesión y la PC se reinició como siempre.** Al terminar una sesión la PC se
   reinicia siempre, y desde la silla no se distingue de un reinicio raro. La sesión puede haber
   terminado porque se acabó el bono de verdad, o porque alguien la cerró desde el mostrador
   (Cerrar sesión y reiniciar, Finalizar Sesión, Intercambiar de máquina).
   - *Cómo se confirma:* en la base, la sesión terminó **antes** de su hora de fin (la cortaron) o
     **justo** a su hora (se acabó). Además, el Cliente PC avisa: si la cortaron con tiempo,
     Actividad reciente dice "el mostrador dio la sesión por terminada cuando, según la PC, le
     quedaban X".
2. **Un reinicio inesperado que tardó.** Puede ser Windows Update, la luz o un cuelgue. El bono se
   terminó durante el reinicio, o volvió con muy poco.
   - *Cómo se confirma:* corte "la PC se reinició **SIN** que la reiniciara el Cliente PC" y cuánto
     duró. En la PC: Visor de eventos (abajo).
   - Si fueron las dos PCs **a la misma hora**, apunta a Windows Update o a la luz.
3. **Se reiniciaron mientras la red o el mostrador estaban caídos.** Vuelven bloqueadas con el
   cartel "Sin conexión con el Servidor" hasta que el mostrador contesta. El tiempo no se borra,
   pero no lo pueden usar y sigue corriendo.
4. **"Gana el menor" bajó el tiempo al volver de un corte.** Queda anotado en la base y en
   Actividad reciente.
5. **Alguien quitó o anuló el bono** (solo el Administrador puede). Queda anotado: la venta queda
   ANULADA con quién y por qué.
6. **Saltó la hora de la PC del mostrador.** Pasa si alguien la cambió o la corrigió Windows. Las
   sesiones con poco tiempo se cerrarían todas juntas. Si fuera esto, lo habrían notado varias PCs,
   no dos.

---

## Cómo confirmarlo

**1. Una copia de la base del local.** Sirve la última copia automática que haya quedado después de
lo de ayer: el programa hace una al cerrar cada turno y otra cada 8 horas. Está en `data\backups`,
al lado de CyberBios.exe en el mostrador, y en las otras carpetas que se hayan agregado (el 19/10
se habían elegido `D:\BACKUPS` y `\\192.168.1.111\backups`). Se llama
`kiosko_2026-11-0X_HHMMSS.db`. Nunca el `kiosko.db` del programa abierto.
Con esa copia corro un script que lista cada sesión del día y cuenta:
- cuándo empezó;
- qué bonos compró y si alguno se anuló;
- su hora de fin y a qué hora terminó de verdad (si la cortaron antes, cuánto le quedaba);
- todo lo que pasó en esa PC mientras tanto: cortes con su causa, reinicios que pidió el Cliente PC
  y por qué, ajustes de "gana el menor", traslados y órdenes del mostrador.

El script ya está armado y probado con una base de prueba.

**2. En cada una de esas dos PCs: Visor de eventos.** Ir a Registros de Windows → Sistema →
"Filtrar registro actual" y poner `1074, 41, 6008, 1001`:
- **1074**: alguien pidió el reinicio, y dice quién. `shutdown.exe` es el Cliente PC o su seguro;
  `TrustedInstaller` o `MoUsoCoreWorker` es Windows Update.
- **41** sin un 1074 antes: se cortó la luz, se colgó o alguien apretó el botón.
- **6008**: el apagado anterior fue inesperado.
- **1001**: hubo pantalla azul.

Además, en Configuración → Windows Update → Historial de actualizaciones se ve si instaló algo
ayer.

**3. Las preguntas al empleado:**
- ¿Qué PCs fueron y a qué hora? ¿Las dos al mismo tiempo?
- ¿Cómo fue? ¿Se apagó de golpe, salió pantalla azul, salió un cartel de reinicio, o se colgó
  antes?
- Cuando volvió, ¿qué mostraba la PC? ¿Pantalla de bloqueo normal, "Sin conexión con el
  Servidor", TIEMPO AGOTADO?
- ¿Y el mostrador, qué decía de esas PCs? ¿Libre, SIN CLIENTE, TIEMPO AGOTADO?
- ¿Cuánto les quedaba, según ellos? ¿Qué hiciste? ¿Les cargaste otro bono, les devolviste la plata?
  ¿Tocaste "Cerrar sesión y reiniciar" o "Finalizar Sesión" en alguna?
- ¿Se borró el tiempo, o lo que tenían en el juego?

---

## Cosas que encontré y se podrían mejorar (NO están hechas)

1. **Cerrar una sesión no deja anotado quién la cerró ni con qué botón.** "Cerrar sesión y
   reiniciar" y "Finalizar Sesión" cierran la sesión, pero Actividad reciente solo dice "sesión
   finalizada". Si quedara "la cerró Fulano desde el mostrador con N minutos por delante", un caso
   como este se respondería en un minuto.
2. **Los minutos de un reinicio inesperado se descuentan.** Hoy es así a propósito: nunca se regala
   tiempo. Si querés cambiarlo hay dos caminos:
   - **A.** Un botón en la ficha de la PC: "Devolver los X min del corte". Aparece solo cuando la
     PC se reinició **sin** que la reiniciara el Cliente PC, lo decide el empleado y queda anotado
     quién.
   - **B.** Que el mostrador los devuelva solo en ese mismo caso.

   La A es más segura: un chico que aprieta el botón de reset no gana nada por sí solo.
3. **Windows Update en las PCs del cyber.** Si el Visor de eventos muestra `TrustedInstaller` o
   `MoUsoCoreWorker`, conviene revisar en cada PC el horario de uso activo o pausar las
   actualizaciones. Con Shadow Defender, una actualización que se instala y se borra al reiniciar
   puede volver a pedir el reinicio una y otra vez.

---

## Lo que se revisó

- Código del mostrador: `servidor_red.py` (la consulta de cada 5 s), `pcs_repo.py` (abrir,
  extender y cerrar sesiones), `reconexion_repo.py` (gana el menor), `reinicios_pc_repo.py`, la
  pantalla de PCs (`pcs_window.py`: el cierre de las vencidas y el clic derecho) y
  `reinicio_actualizacion_repo.py`. Este último no reinicia una PC con un cliente jugando.
- Código del Cliente PC: el ciclo de 5 s (`cliente_pc.py`), `reconexion.py` y `seguro_fin.py`.
- Pruebas: corrí las del tiempo de las PCs, los avisos de fin, la reconexión y el seguro de fin.
  Son 68 y pasan todas.
- **No visto:** la base del local, las PCs del local y su Visor de eventos.
