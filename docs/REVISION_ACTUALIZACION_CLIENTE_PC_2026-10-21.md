# Revisión: actualización remota del Cliente PC y reporte de cada PC (2026-10-21)

Solo revisión, sin cambios de código. Repos: CLIENTE PC en 9129336 (V1.2), CYBERCONTROL en b9af98e.
Pruebas que ya existen: CLIENTE PC test_actualizacion (52) + test_pulso, y CYBERCONTROL
test_actualizacion_cliente (59) + test_cortes_pc: todas pasan.

## Hallazgos, de más grave a menos

### 1. ALTA (comprobado): la vuelta atrás "por tiempo" no anda
- Dónde: CLIENTE PC/lanzador.py:188-194 (`proceso.kill()`), y después volver_atras, lanzador.py:146-148.
- Qué pasa: PCcliente.exe está armado en "un solo archivo" (PCcliente.spec, sin COLLECT). Ese tipo de
  exe arranca como DOS procesos: un envoltorio y, adentro, el programa de verdad. Cuando una versión
  nueva no avisa "arranqué bien" en 5 minutos, el lanzador mata solo al envoltorio. El programa de
  verdad sigue abierto y tiene agarrado actual\PCcliente.exe, así que borrar actual\ falla con
  "Acceso denegado". La versión no se anota como mala, "probando" queda puesto y el lanzador termina
  con "Error inesperado". La versión nueva sigue corriendo y nadie la vigila. Si de verdad estaba
  trabada (no habla con el Servidor), la PC queda así en cada reinicio y no se puede arreglar desde el
  mostrador: hay que ir a esa PC.
- Cómo lo comprobé: armé un exe de prueba con el mismo PyInstaller (6.22.3, un solo archivo), lo abrí
  como lo abre el lanzador e hice `kill()`. El proceso hijo siguió vivo, y borrar la carpeta dio
  `PermissionError [WinError 5]` justo sobre el exe.
- Las pruebas no lo ven: `ProcesoFalso` (tests/test_actualizacion.py:300) es un proceso solo.
- Cuando la versión se CIERRA sola antes de confirmar, la vuelta atrás sí anda: el envoltorio se cierra
  cuando se cierra el programa.
- Cómo reforzar: cerrar todos los procesos juntos (`taskkill /F /T /PID <pid>` ANTES de matar al
  envoltorio, o abrir el cliente dentro de un "Job" de Windows y cerrar el Job), esperar unos segundos
  a que el exe quede libre, y anotar la versión como mala ANTES de mover carpetas. Sumar una prueba con
  un exe de un solo archivo de verdad (tests/test_version_cliente.py ya usa el runw.exe de PyInstaller).

### 2. MEDIA-ALTA (leyendo el código): si el mostrador no está prendido, se descarta una versión buena
- Dónde: lanzador.py:47 (PLAZO_DE_PRUEBA_SEG = 300) y :188-189. La marca solo se deja cuando el
  Servidor contesta (actualizador.py:59-70).
- Qué pasa: el dueño manda una versión a la tarde y las PCs la copian. A la noche se apagan, y a la
  mañana se prenden ANTES de abrir CYBERCONTROL (o el mostrador tarda más de 5 minutos). Ahí todas las
  PCs dan la versión por mala: vuelven a la anterior, la anotan como mala y no la vuelven a bajar.
  Para mandarla de nuevo hay que volver a cargarla.
- Hoy no pasa del todo, pero solo porque el hallazgo 1 rompe la vuelta atrás. Si se arregla el 1 solo,
  este empieza a pasar. Hay que arreglarlos juntos.
- Cómo reforzar: antes de dar la versión por mala por tiempo, que el lanzador mismo pruebe si llega al
  Servidor (conectarse a servidor_ip:puerto de config.json). Si tampoco llega, la culpa no es de la
  versión: sigue esperando y no la corta.

### 3. MEDIA: con la carpeta sin excluir en Shadow Defender, "Lista" para siempre
- Dónde: actualizador.py:12-14 (copia también con la PC congelada); actualizacion_cliente_repo.py:441-442
  (situacion: LISTA); la exclusión es a mano (preparar_pc.bat:31 y :148).
- Qué pasa: si en una PC alguien se olvida de excluir C:\Program Files\AAAAA26\cliente, la copia se hace
  igual sobre el disco congelado y la pantalla dice "Lista: se pone en el próximo reinicio". Al reiniciar,
  Shadow Defender la borra y el Cliente PC la vuelve a bajar (22 MB). En la pantalla queda "Lista"
  después de cada reinicio y la versión nunca se pone en uso. La pantalla miente sin darse cuenta.
- Cómo reforzar: en el servidor, si una PC vuelve a copiar la MISMA versión después de reiniciar
  (`arranque` distinto, todavía con la versión vieja), mostrar "La copia se borra al reiniciar: ¿falta
  excluir la carpeta en Shadow Defender?" en lugar de "Lista".

### 4. BAJA-MEDIA: una PC instalada a mano puede volver a una V más vieja
- Dónde: preparar_pc.bat:130 (borra actual\version.json) + actualizador.py:112 (sin version.json la
  instalada cuenta como 0).
- Qué pasa: en el servidor está cargada la V1.1 y la PC 5 está marcada. El dueño le instala la V1.2 con
  el pendrive. La PC 5 ve "no sé qué versión tengo", baja la V1.1 y en el próximo reinicio vuelve a la V1.1.
- Cómo reforzar: decisión del dueño, porque él quiso poder mandar una V más vieja a propósito. Una
  opción es que solo en una instalación a mano (sin version.json) el Cliente PC no acepte una V más
  vieja que la suya (el "v" va firmado en el manifiesto) y lo cuente en la pantalla.

### 5. BAJA: se anota "en prueba" después de mover carpetas
- Dónde: lanzador.py:123-128 (aplicar_nueva) y :146-148 (volver_atras).
- Qué pasa: si se corta la luz justo entre poner la nueva y anotarla, o si el disco está lleno y no se
  puede escribir actualizacion.json, la versión nueva queda en uso sin que nadie la vigile.
- Cómo reforzar: anotar primero y mover después.

### 6. BAJA: un "Falló" viejo aparece en una versión nueva
- Dónde: actualizacion_cliente_repo.py:439-440; actualizador.py:171-172 no manda qué versión falló.
- Qué pasa: falló la versión X y el dueño carga la Y. Una PC que está apagada desde entonces muestra
  "Falló" para la Y, que esa PC ni probó.
- Cómo reforzar: mandar la versión que falló en `act_version` y mostrar FALLO solo si es la que le toca.

### 7. BAJA: si el reloj del mostrador está atrasado, "Esperando" para siempre
- Dónde: actualizacion_cliente_repo.py:172-174 (el número sale de la fecha y hora); actualizador.py:112
  (la PC no hace nada y no lo cuenta); situacion -> ESPERANDO (:449).
- Qué pasa: con la pila de la placa agotada (reloj en 2009, por ejemplo) y la carpeta data\cliente_pc
  perdida, la versión nueva tiene un número más chico que el que tienen las PCs. Las PCs no la bajan y
  la pantalla dice "empieza en segundos" para siempre.
- Cómo reforzar: que la PC cuente "la del Servidor no es más nueva que la mía".

### 8. BAJA: 40 PCs bajando a la vez
- Dónde: actualizador.revisar (todas empiezan en los primeros 5 s); servidor_red.py:408-428 (sin tope).
- Qué pasa: son unos 880 MB juntos. Con la placa de red del mostrador a 1 Gbps son segundos. Si quedó a
  100 Mbps (ya pasó con un cable), es más de un minuto con la red llena: algunas PCs pueden tardar más
  de 3 s en recibir la respuesta de /estado. Con sesión siguen con el tiempo que cuentan ellas mismas;
  sin sesión quedan bloqueadas, que es lo seguro.
- Cómo reforzar: atender pocas bajadas a la vez (por ejemplo 5) y a las demás contestarles "ocupado";
  esas PCs reintentan al minuto con un cartel claro.

### 9. BAJA (toca la firma): la clave privada está sin contraseña en el mostrador
- Dónde: actualizacion_cliente_repo.py:92-95 y :157 (`password=None`).
- Qué pasa: quien copie C:\Users\CyberBIOS\FirmaClientePC puede firmar exes que todas las PCs aceptan
  (corren como Administrador). Para usarla igual tendría que hacerse pasar por el Servidor en la red.
- Cómo reforzar (si el dueño quiere): ponerle una contraseña que se escribe al cargar una versión, o
  tenerla solo en el pendrive y enchufarlo para cargar.

### Carga (cada PC cada 5 s): está bien
- Lo de la actualización escribe en la base solo cuando algo cambió (registrar_reporte y el número de
  versión, en memoria). Lo que se suma a cada consulta son unos 300-600 bytes.
- Lo único que se repite en cada consulta es `version_para_estacion`: 4 lecturas de fecha de archivo y
  una consulta a la tabla configuracion (obtener_seleccion). Se podría guardar en memoria, pero es poco.
- Lo que más pesa en cada /estado es otra cosa: registrar_conexion escribe en la base en cada consulta,
  o sea unas 8 escrituras por segundo con 40 PCs. Eso es el latido, no la actualización.

## Lo que ya está bien hecho
- Firma Ed25519 comprobada en tres momentos: antes de bajar (manifiesto), con el exe entero bajado
  (tamaño y huella) y otra vez en el lanzador antes de ponerla. El Servidor no puede colar otro exe, y
  la PC solo escribe en nueva.armando\ con nombre fijo.
- Bajada en nueva.armando\ y paso a nueva\ de un solo cambio de nombre: una bajada a medias nunca se
  pone en uso, y los restos se borran.
- Se pone en uso solo al arrancar, con el cliente cerrado (mutex), nunca en medio de una sesión. Un corte
  de luz entre los dos cambios de nombre lo arregla ordenar_carpetas.
- Las versiones malas se recuerdan y no se vuelven a bajar. El número de versión siempre crece.
- "Actualizada con éxito" exige que la copia sea la versión que le toca (version_bajada), así una copia
  vieja no parece la nueva. Hay prueba.
- Si se desmarca una PC, se borra lo que copió. Al cargar una versión se vacía la selección. Se rechaza
  un exe que no es el Cliente PC.
- El pulso manda duraciones y no horas (el reloj de cada PC puede estar corrido).
