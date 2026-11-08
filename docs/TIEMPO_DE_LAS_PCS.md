# Cómo funciona el tiempo de las PCs

**Escrito el 20/10/2026**, cuando se arregló lo de este archivo. Es para vos,
sin términos de programación. Si lo querés revisar con ChatGPT, se puede
adjuntar tal cual.

## Lo que preguntaste y pediste

> "Si cierro sesión en el programa, ¿las PC cliente se bloquean? No debería
> hacerlo [...] Siempre que haya una desconexión entre SERVIDOR y PCCLIENTE, al
> volverse a conectar, se toma el tiempo que menor valor tiene."

## Lo básico: dos relojes que cuentan a la vez

- **El mostrador** (CyberBIOS) no anota "a la PC 5 le quedan 3 horas". Anota
  **a qué hora termina**: "la PC 5 termina a las 13:00". Por eso su cuenta
  nunca se frena: aunque CyberBIOS esté cerrado o la PC del mostrador apagada,
  cuando vuelve calcula lo que falta para las 13:00.
- **Cada PC** le pregunta al mostrador cada 5 segundos cuánto le queda, y además
  lleva **su propia cuenta**, por si el mostrador no contesta.

Normalmente las dos cuentas dan igual, porque las dos van con el reloj.

## Cerrar sesión en el mostrador: las PCs no se enteran

La parte de CyberBIOS que atiende a las PCs arranca cuando abrís el programa y
sigue andando aunque no haya nadie logueado. Cerrar sesión solo cierra la
pantalla del mostrador.

Para pasar de un Operador a vos como Admin: cerrás sesión y entrás. Los
clientes siguen jugando y no se dan cuenta de nada.

Mientras no hay nadie logueado, a una PC que se le termina el tiempo le pasa lo
de siempre: se bloquea y se reinicia. En el mostrador esa sesión queda anotada
con la hora en que terminó de verdad, no con la hora en que alguien volvió a
entrar. Si un socio entra a esa PC en ese rato, arranca una sesión nueva con su
nombre. *(Antes se pegaba a la sesión vieja y la PC podía mostrar el nombre del
cliente anterior. Se arregló el 20/10.)*

## Cerrar CyberBIOS o apagar el mostrador (por ejemplo, para limpiarlo)

- **PCs que están jugando:** siguen jugando con su propia cuenta. Si se les
  termina el tiempo, se bloquean y se reinician solas, como siempre.
- **PCs libres:** quedan bloqueadas. Nadie puede entrar (tampoco los socios) y
  no se puede vender tiempo hasta que vuelva el mostrador.
- **PlayStation 5:** no tiene un programa propio. Su tiempo vive solo en el
  mostrador y sigue corriendo. Cuando volvés a abrir CyberBIOS, si se le terminó,
  titila en rojo como siempre.

## Cuando vuelve la conexión: gana el MENOR

Con tu ejemplo:

- A las 10:00 un cliente carga 3 horas. El mostrador anota: termina a las 13:00.
- De 10:10 a 12:10 apagás el mostrador para limpiarlo.
- Al prenderlo, el mostrador calcula 13:00 − 12:10 = **50 minutos**. La PC, que
  siguió contando sola, también dice unos 50 minutos. Dan igual: no hay nada
  que corregir.

Las dos cuentas solo darían distinto si en el medio **cambia la hora de la PC
del mostrador** (se desconfigura, o alguien la corrige). En ese caso:

- La PC le cuenta al mostrador cuánto le queda según ella.
- **Gana el que tiene menos tiempo, y el mostrador lo guarda.** Desde ese momento
  la PC y el mostrador muestran lo mismo.
- Queda escrito en **Actividad reciente**, por ejemplo: *"PC05X: volvió la
  conexión y se tomó el tiempo de la PC, que era menor: le quedaban 1h 00m (el
  mostrador decía 1h 05m)."*
- **Nunca se sube el tiempo.** La PC solo puede bajarlo, así que tocar una PC no
  le regala tiempo a nadie.
- Diferencias de hasta 30 segundos no se tocan: son del redondeo de cada consulta.

### Si durante el corte se le cargó tiempo a esa PC

Pasa cuando se corta solo la red de esa PC (un cable, por ejemplo) y el
mostrador sigue andando: el cliente se acerca y le venden otra hora. La PC no se
enteró, así que su cuenta tiene una hora menos.

**Esa hora no se pierde.** Antes de comparar, el mostrador le suma a la cuenta de
la PC todo lo que se cargó durante el corte. O sea, se compara el tiempo
**usado**, no el que queda.

### Si a la PC se le terminó el tiempo durante el corte

Se reinicia y queda bloqueada, como siempre. Antes de reiniciarse deja anotado
"a esta sesión se le terminó el tiempo". Cuando el mostrador vuelve, se lo
avisa, y si el mostrador creía que todavía le quedaba, la sesión termina ahí.
Así la PC no se vuelve a abrir con tiempo que ya se usó.

Esto necesita que la carpeta del Cliente PC (`C:\Program Files\AAAAA26\cliente`)
esté **fuera de lo que congela Shadow Defender**, igual que para las
actualizaciones. Si no, lo anotado se borra al reiniciar y decide el mostrador
solo, como antes.

### Si la PC se reinició por otra cosa durante el corte

Por ejemplo, se colgó o se cortó la luz. Queda bloqueada hasta que vuelve el
mostrador (nunca se regala tiempo por una falla). Cuando vuelve, sigue con lo
que le queda según el mostrador; los minutos que estuvo bloqueada se pierden.

Esto **no se cambió a propósito**: para que la PC siguiera sola después de
reiniciarse, tendría que creerle a la hora de Windows de esa PC, y un cliente
podría atrasarla para jugar gratis. Es un caso raro.

## Socios

Si se corta la sesión antes de tiempo, se le devuelve al socio lo que le
quedaba, en bloques de 30 minutos, como siempre. Si al volver la conexión se le
bajó el tiempo, se le devuelve lo que le quedaba después de bajarlo.

### Cuando la PC dice una cosa y Miembros otra (07/11/2026)

> "Tengo problemas con los miembros y sus tiempos no concuerdan, a veces, lo
> que dice el servidor y lo que dice el cliente."

Al entrar a una PC, el socio **se lleva su saldo a la PC**. Lo que se ve en
Miembros es lo que le queda **guardado aparte**, y no baja mientras juega. Lo
que baja es el contador de la PC.

Casi siempre se lleva todo y lo guardado queda en cero. Pero si esa PC está
**reservada por otro cliente más tarde**, se lleva solo el tiempo hasta la
hora de la reserva, y el resto queda guardado. Esa regla es del 20/10.

Lo que pasó con Eros el 06/11: entró a la PC15X a las 10:39 con unas 43 h y
media. La PC15X estaba reservada a las 22:00, así que se llevó 11 h 20 m y
quedaron 32 h 18 m guardadas. A las 15:26 la PC decía **6 h 33 m** y Miembros
**32 h 18 m**. Las dos cosas eran ciertas y no se perdió nada: tenía 38 h 51 m
entre las dos. A las 22:00 la PC se bloquea y él sigue en otra PC con lo
guardado.

Desde el 07/11 se ve así:

- **Miembros**, con el socio jugando, dice **SALDO TOTAL** (lo guardado más lo
  que le queda en la PC) y abajo de dónde sale cada parte: "32h 18m guardado +
  6h 33m en la PC15X". Un cartel celeste explica hasta cuándo juega en la PC y
  por qué. La lista de socios dice "Jugando · PC15X". Se actualiza sola cada 30
  segundos.
- **El cuadro de la PC** en Control de PCs dice **"Hasta 22:00 · Eros"** desde
  que entra (antes, la reserva recién se veía 2 horas antes).
- **Al cargarle saldo** a un socio que juega, el cartel dice cuánto pasó a la PC
  y, si una reserva no dejó pasar todo, cuánto quedó guardado y por qué. A Oscar
  le cargaron 13 h el 07/11 y el cartel decía solo "8h 40m"; ahora diría también
  "Las otras 4h 20m le quedaron guardadas en su cuenta: la PC13X está reservada…".
  "Saldo actual", en la ventana de Cargar Saldo, cuenta lo de la PC.
- **ORDENAR SALDOS** sigue mostrando solo lo guardado, que es lo que corrige.

La regla no cambió: el socio sigue entrando solo hasta la hora de la reserva.

### Un socio, una sola PC a la vez (07/11/2026)

> "No quiero que haya multilogin, o sea que un usuario pueda loguearse una sola
> vez."

Como le quedaba saldo guardado, ese socio podía entrar a **otra PC al mismo
tiempo** con su usuario (él o un amigo con su contraseña). Desde el 07/11 no se
puede: si ya está jugando en una PC e intenta entrar en otra, la PC le dice:

*"Eros ya está jugando en la PC15X: un socio entra a una sola PC a la vez. Para
usar esta PC, primero cerrá la sesión en la PC15X o pedí en el mostrador que te
cambien de PC."*

- **En la misma PC** sí puede volver a entrar: le suma lo guardado a esa sesión.
- **Para cambiarlo de PC sin que pierda nada:** en Control de PCs, clic derecho en
  su PC y "Intercambiar de máquina...". Se lleva su sesión entera.
- **Si cierra la sesión** para ir a otra PC, se le devuelve lo que le quedaba como
  siempre, en bloques de media hora, y después entra en la otra.
- **Si se le colgó la PC** y no puede cerrar, el operador le corta la sesión
  desde Control de PCs, o lo cambia de PC con "Intercambiar de máquina...".
- Una sesión a la que ya se le terminó el tiempo no lo traba.
- Vale también para "Abrir PC con Miembro" en el mostrador.

Para que lo vea el socio en la PC no hace falta un Cliente PC nuevo: el mensaje
lo arma el mostrador.

## PCSTREAM

Funciona igual que cualquier PC.

## Qué hace falta para que ande en el local

1. **CyberBIOS nuevo** (armar el `.exe`).
2. **Cliente PC nuevo en cada PC** (va a ser la versión V1.1). Mientras una PC
   tenga el Cliente PC viejo, sigue como antes: compara un instante al volver y
   después queda el número del mostrador. Todo lo demás de este archivo anda igual.
3. Shadow Defender con la carpeta del Cliente PC excluida (ver más arriba).

## Cómo probarlo

1. Dale 30 minutos a una PC. Cerrá sesión en el mostrador: la PC sigue jugando.
   Volvé a entrar.
2. Cerrá CyberBIOS 5 minutos. La PC sigue jugando y su tiempo sigue bajando.
   Abrilo de nuevo y compará el tiempo de la PC con el del mostrador: tienen que
   dar casi igual.
3. Para ver "gana el menor" (con los dos programas nuevos) hay que atrasar 10
   minutos la hora de Windows del mostrador con CyberBIOS cerrado. **Hacelo solo
   en la PC de tu casa, nunca en el local**: cambiar la hora del mostrador cambia
   la hora de las ventas. Al
   abrir CyberBIOS, el mostrador cree que le quedan 10 minutos más; la PC no. En
   Actividad reciente aparece el renglón "se tomó el tiempo de la PC".

---

*Para quien programe:* la regla está en
`control_pcs/repositories/reconexion_repo.py` (CyberBIOS) y en `reconexion.py`
(Cliente PC). Las pruebas están en `tests/test_tiempo_de_las_pcs.py` (CyberBIOS),
y en `tests/test_reconexion.py` y `TestTiempoAlReconectar` (Cliente PC).
