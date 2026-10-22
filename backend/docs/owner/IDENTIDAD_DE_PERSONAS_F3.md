# Identidad de las personas: árbitros, jugadores, entrenadores y ausencias a fecha (Plan Maestro, fase F3)

**Qué es.** Hasta hoy el sistema trataba a las personas como texto. El árbitro de un partido llegaba como una cadena del proveedor
(`M. Oliver`, `Michael Oliver, England`, `Brooks, John, England`) sin ningún identificador: los 199.890 partidos con árbitro traían
9.510 grafías distintas para unas seis mil personas, así que el mismo árbitro eran varios «árbitros» con pocos partidos cada uno, y
dos hombres distintos con la misma inicial y apellido eran uno solo. De un jugador no se sabía «de qué día a qué día estuvo en este
club» ni cuántas veces jugó con su selección: un partido de selecciones era un partido más de un jugador cuyo club no se conocía.
Los entrenadores eran instantáneas sin vínculo con una persona ni con un club. Y nada comprobaba, noche tras noche, que el paquete de
la IA no listara como lesionado a quien el proveedor ya había dado por recuperado. F3 guarda cada identidad **una vez**, con reglas
conservadoras que prefieren dudar a equivocarse, y todo lo demás pregunta a la base de datos. **No cambia ningún modelo, pronóstico,
pick ni liquidación, ni el modo SHADOW.**

## Qué escribe (y qué no)

Tres migraciones, solo aditivas:

| Migración | Objeto | Para qué |
|---|---|---|
| **0083** | `core.referees` | Una fila por persona: el nombre con que se muestra, su país y si un administrador fijó el nombre. |
| | `core.referee_aliases` | Una fila por grafía **en un ámbito** (el nombre normalizado y el país que nombra la cadena, o el de la competición nacional donde se escribió, o `?` en las continentales): a qué árbitro pertenece, por qué (`basis`) y quién la colocó (las reglas o una persona). |
| | `core.fixture_officials` | Quién arbitró cada partido, como historia de lo que dijo el proveedor (una fila por cambio, igual que `core.fixture_facts`, de donde se lee). Apunta a la **grafía** y no a la persona, de modo que una fusión nunca la toca. Grafía nula: el proveedor quitó al árbitro del partido. |
| | `core.fixture_referees` (vista) | La fila más reciente de cada partido con su árbitro: lo que leen todos los demás. |
| | `core.referee_candidates` | La cola de dudas: parejas que las reglas no supieron decidir (motivo, puntuación, las dos grafías que lo sugirieron y los partidos del lado pequeño como `impact`). Las rechazadas se guardan como decisión para no volver a sugerirlas. |
| | `core.referee_events` | Lo que una persona cambió: fusionar, deshacer, separar, rechazar, reabrir, renombrar (con lo que se movió, que es lo que necesita «deshacer»). |
| **0084** | `core.player_spells` | Una fila por **racha** de un jugador en un club (A, B, A son tres): el club, `valid_from` (nulo: nadie dice desde cuándo), `valid_to` (primer día que ya **no** está; nulo: sigue allí hasta donde se sabe), cómo se conoce el inicio (`transfer`, `lineup`, `squad`), los partidos que la sostienen y el último día con evidencia. «¿Dónde estaba el día D?» es `valid_from <= D < valid_to`. |
| | `core.player_national_caps` | Una fila por (jugador, partido **terminado** de una selección **absoluta** cuya hoja de convocados lo incluye): titular o suplente, si jugó (nulo hasta que llegan las estadísticas del partido) y sus minutos. |
| | `core.coach_careers` + `coach_id`, `team_id` | Dos columnas nulas sin valor por defecto (instantáneo en una tabla viva): la persona (`core.coaches`) y el club de cada instantánea, que rellena la pasada de enlaces. La vista `core.coach_spells` da la instantánea más reciente de cada carrera con ambos enlaces. |
| **0085** | índice `fixture_lineup_players_player` | La tabla de alineaciones (8,4 millones de filas en producción, 1,1 GB) solo se podía leer por partido; ahora también por jugador. Se construye **sin bloquear** las escrituras del worker (`CREATE INDEX CONCURRENTLY`); si una construcción se interrumpe, la migración borra el índice inválido y se puede repetir. Ocupará del orden de 250 MB (estimado: 28 bytes por fila). |

Todo lo de jugadores y entrenadores es **derivado** de hechos ya guardados (traspasos, plantillas, alineaciones, estadísticas): una
pasada es idempotente y lo reconstruye, y no se pide nada al proveedor. En árbitros, lo que reconstruyen las reglas también es
derivado, pero **las decisiones de una persona no se pueden reconstruir**: por eso la reversión pide la copia de despliegue (ver «Cómo
deshacerlo»). `core.fixture_facts` no se toca: la cadena original del proveedor sigue donde estaba, y un árbitro que no se pueda
colocar deja a los lectores en el texto que leían antes.

## Qué ve el producto ahora

* **Consola de administración → Árbitros** (`/admin/referees`, solo SUPER_ADMIN):
  * contadores de salud de la identidad: personas, grafías, partidos con árbitro, partidos sin duda pendiente, dudas en espera,
    partidos con una duda y problemas de tabla (si una invariante no se cumple, se nombra);
  * el listado por nombre **o por cualquiera de sus grafías**, con país, partidos, primer y último partido, y una marca en los
    nombres que fijó un administrador;
  * **la cola de dudas** (en espera / personas distintas / fusionadas; por motivo): cada pareja con los dos nombres, el de más
    partidos primero, y las respuestas «quedarse con este», «son dos personas» y «volver a dudar»;
  * la ficha de un árbitro: sus grafías con la base de cada una, sus partidos recientes, sus dudas y el historial de decisiones;
    **deshacer** una fusión que nadie ha revertido, **separar** las grafías marcadas en una persona nueva, **renombrar** (y devolver
    el nombre a las reglas);
  * lo que las reglas prohíben se rechaza con su motivo (dos hombres que arbitran a la vez no se pueden fusionar; una fusión ya
    deshecha no se deshace dos veces) y el botón de forzar solo se ofrece cuando la API contesta 409. Cada decisión se firma
    `admin:<correo>`, se guarda en `core.referee_events` y entra en la auditoría de escrituras de administración. Si el pase horario
    está escribiendo, la acción contesta «ocupado» en vez de esperar.
* **Ficha del partido:** `facts.referee` es el nombre de la persona (con país) y `facts.referee_id` aparece cuando la identidad está
  al día con la observación más reciente; si no, sale la cadena tal como llegó.
* **Ficha del jugador** (`GET /api/v1/players/{id}`, campos nuevos `club_history` y `national_caps`; en la web, dos paneles):
  * «Dónde ha jugado»: las rachas, la más reciente primero, la abierta marcada como actual y el inicio desconocido dicho como tal;
  * «Con su selección»: los partidos de una selección absoluta (los últimos 200) con su papel, el resultado **visto desde su
    equipo**, y el balance. Una entrada a la que todavía le faltan las estadísticas del partido se muestra aparte y **nunca se llama
    «jugó»**;
  * un jugador que el trabajo aún no ha visto contesta con una frase («Todavía no hay ninguna racha construida…»), no con una lista
    vacía que se leería como «nunca jugó en ningún sitio».
* **Paquete de la IA y lo que lo rodea (versiones nuevas, en producción desde el 22 oct 2026):**
  * `packet-v5`: `fixture.referee`, `referee_id` y `referee_seen_at` se leen **a la hora del paquete** desde `core.fixture_officials`
    por una sola puerta (`fbi.people.officials.referee_as_of`): lo último que el proveedor había dicho para entonces; nada si lo había
    quitado; y la cadena que escribió mientras el pase horario no ha alcanzado un cambio (nunca una persona que ya no es la nombrada).
    El respaldo de texto ahora sí es «a fecha»: antes `fixture_facts_latest` no encontraba nada cuando la fila más reciente era
    posterior al momento del paquete.
  * `dossier-v3`: los partidos de un árbitro se cuentan bajo **todas** las grafías que el proveedor usó para él; los homónimos no se
    mezclan; un partido cuyo árbitro el proveedor cambió después ya no cuenta para el primero. Bloque nuevo `national`
    (`national-v1`) en partidos de selecciones: por lado, la plantilla del partido (su propia hoja si estaba descargada a la hora del
    paquete; si no, la del partido anterior de esa selección, hasta 400 días atrás; si no, nada) y, por jugador, el club al que
    pertenecía **ese día** (desde cuándo, cómo se sabe, y la última vez que alguien lo vio allí con su antigüedad: una racha abierta
    que nadie ve desde hace meses probablemente terminó), su forma en los últimos partidos de club (hasta 5 en 120 días), su balance
    con la selección absoluta antes del partido y si figura como baja. Todo leído a la hora del paquete (partidos con resultado
    registrado para entonces, filas descargadas para entonces). **No se estima nada para llenar un hueco:** un jugador sin club
    conocido tiene `club = null`.
  * `brief-v6`: la IA conoce el bloque. `pm-v5`: «tarjetas por encima / por debajo de lo habitual del árbitro» usa el promedio de sus
    partidos por identificador. `memory-v3`: la entidad es la persona; las filas que escribió `memory-v2` bajo una cadena de texto
    quedan como historia, no se reconcilian y se ocultan de la lista de la consola.
  * **`leak-audit-v3`**, tres reglas nuevas en la auditoría nocturna de fuga (todas probadas con mutaciones):
    * `referee_known`: todo paquete que nombra un árbitro cita una observación que existe, no es posterior a su momento y era la más
      reciente entonces; no depende de fusiones ni separaciones posteriores;
    * `national_known`: todo partido que cita el bloque nacional empezó antes del partido del paquete y tenía su resultado
      registrado a la hora del paquete; una hoja que se dice «del propio partido» estaba descargada para entonces; ningún día de club
      es posterior al día del paquete;
    * `absences_known`: cada jugador listado como baja fue nombrado por una respuesta del proveedor registrada antes del momento del
      paquete, esa respuesta es la **más reciente** sobre él (si una posterior lo dio por recuperado, no puede seguir listado), es
      del mismo partido y el tipo de ausencia es el que dio la respuesta. Una comprobación por jugador listado.

## Reglas que se respetan

**Árbitros (`refid-v1`)**, de la más segura a la menos segura:

1. **Misma zona, misma persona escrita de dos maneras: se unen.** (a) Dos nombres completos que empiezan y acaban con las mismas
   palabras (`danny makkelie` y `danny desmond makkelie`). (b) Una inicial y un apellido junto a **un solo** nombre completo que
   acaba igual y empieza por esa letra. Si encajan dos (`r gupta` con `rahul kumar gupta` y con `rajesh gupta`), no se une nada y la
   duda se queda para una persona.
2. **Otra zona: solo el visitante y con testigo.** Un árbitro es extranjero en unos pocos partidos fuera de casa (`d makkelie` es
   holandés y aparece en Arabia Saudí, Grecia, Emiratos): el mismo nombre en un grupo **pequeño** de otra zona se une al único grupo
   «casa» posible (con al menos 20 partidos, del que el visitante es como mucho 15 partidos y el 15 %). Una grafía sin zona (`?`, un
   partido continental) se une a la única zona posible, sea cual sea el tamaño. Donde caben dos casas (`j martinez` en España y en
   México), no se une nada.
3. **Una persona no puede arbitrar dos partidos a la vez, y esto manda sobre todas las reglas.** Dos grupos con un partido cada uno
   que empiezan con menos de 120 minutos de diferencia son dos personas, digan lo que digan sus nombres: la pareja queda **vetada**,
   no se une por regla ni se vuelve a sugerir. Es la única evidencia de «distinto» que hay en los datos (12 vetos en toda la historia).
4. **Lo que queda se sugiere, nunca se decide:** las parejas cuyos nombres podrían ser uno y que ninguna regla unió (varias casas,
   una inicial ambigua, una variante de escritura) van a la cola con un motivo y una puntuación. Una persona fusiona o rechaza.
5. **Lo ya colocado no se mueve por regla.** Una grafía guardada nunca cambia de árbitro por una regla; una grafía nueva puede unirse
   a un árbitro guardado; **dos árbitros guardados no se unen jamás por regla**, solo por una persona. Fusionar y separar **solo mueven
   grafías**: no reescriben ninguna fila de `core.fixture_officials`, por eso son reversibles y la historia no se reescribe. El nombre
   que un administrador fija con «renombrar» queda bloqueado y las reglas no lo vuelven a cambiar. El resultado no depende del orden
   en que llegan los datos.

**Jugadores (`spells-v1`) y selecciones (`caps-v1`):**

* **Cuatro clases de prueba actúan cada día, en este orden, y la última palabra del día es el estado al terminar:**
  *plantilla* (una lista de plantilla lo incluyó; la más débil, de **peso cero**: rellena un hueco y confirma el club donde ya se sabe
  que está, pero nunca lo saca de donde un traspaso o un partido lo puso, porque esas listas van con retraso) < *salida* (un traspaso
  dice que dejó el club ese día) < *fichaje* (llegó ese día, con el texto del proveedor: cesión, libre, traspaso…) < *visto* (estuvo
  en la hoja de convocados de un partido del club ese día: la prueba más dura; abre una racha si no estaba en ese club, así una cesión
  que nadie registró aparece en cuanto juega). `valid_to` es exclusivo. Un partido el día de su salida es del club que deja.
* **Un traspaso de papel no es una racha:** un club al que se llega y se deja el mismo día se salta, y toda racha que empieza y acaba
  el mismo día (dos clubes el mismo día; un traspaso que ese día contradice un partido con un tercer club) se descarta y se cuenta
  como **fantasma** (A, un club de un día, A es una sola racha). Un traspaso sin fecha no se puede ubicar y se deja fuera; de cada
  jugador solo cuenta la lista de traspasos más reciente. Una racha sin inicio conocido es solo historia: no responde a «dónde
  estaba el día D».
* **Leer «dónde estaba el día D» nunca usa nada posterior a D** (lo comprueba una prueba con historias aleatorias).
* **Una selección o un equipo sin clasificar nunca da prueba de club.** Manda la clasificación de PrediGol (`core.team_kind`) sobre
  la bandera del proveedor. Los días son días UTC.
* **Selección absoluta** = clasificada como nacional y cuyo nombre no es juvenil ni olímpico (`U15`–`U23`, `Under 15`–`23`,
  `Olympic`). Un *cap* es una entrada en la hoja de convocados de un partido **terminado**, titular o suplente, con lo que se pueda
  decir de si jugó: un titular jugó salvo que tenga 0 minutos; un suplente necesita que el partido tenga estadísticas de su lado (con
  ellas y sin minutos, no jugó; sin ellas, «aún no se puede decir» y se revisa hasta que lleguen, que es horas después del pitido).
* **«Baja» en el bloque nacional** es la última respuesta del proveedor a la hora del paquete; cualquier respuesta posterior que lo
  limpie (se recuperó) hace que ya no figure en el paquete de un momento posterior y que siga figurando en el de uno anterior.
* **El «jugador 0» del proveedor no es una persona.** Cada partido trae en las estadísticas una fila de relleno con el identificador 0
  (4.820 filas, una por partido). Ninguna lectura del historial la usa: sin esta guarda, una racha «del jugador 0» rompe la restricción
  de la tabla y el pase completo se deshace (ocurrió en producción la primera noche; ver «Lo que se aprendió al desplegar»).

**Qué lado fue cada hombre (`sides-v1`).** El proveedor dice quién jugó un partido **dos veces**: en la hoja de convocados (titulares y
suplentes) y en las estadísticas del jugador, y las dos nombran un lado, local o visitante. Casi siempre coinciden. Pero en **202 de los
137.400 partidos** que tienen las dos (casi todos de 2025, casi ninguno desde la primavera de 2026) el proveedor dio **a cada equipo la
hoja del otro**: los once del Nashville bajo el Inter Miami y al revés, con el entrenador correcto al lado, mientras que las
estadísticas del mismo partido tienen a cada hombre en su lado. Se equivoca por **hojas enteras**, nunca por hombres sueltos: de las
274.813 hojas que comparten hombres con las estadísticas, 274.367 coinciden en todos, 404 (las dos de esos 202 partidos) discrepan en
todos menos uno, **ninguna en un punto intermedio**, y otras 42 difieren en un solo hombre, listado en las dos hojas de su partido. Sin
corregirlo, esos jugadores habrían quedado con una racha en el club contrario y con partidos de otra selección. La regla es la que
aplicaría una persona:

1. **Las estadísticas mandan.** Un hombre que las estadísticas colocan está del lado que ellas dicen, diga lo que diga su hoja.
   (Contrastado con el club en que jugó en los partidos de alrededor, las estadísticas aciertan en el 97,7 % de las discrepancias.)
2. **Una hoja que las estadísticas dan la vuelta es del otro lado.** Si al menos **5** de sus hombres están en las estadísticas y al
   menos el **80 %** de ellos están colocados en el otro lado, la hoja está *cruzada*, y todo hombre suyo que **no** está en las
   estadísticas (un suplente que no llegó a salir) se lee también en el otro lado. Una hoja con pocos hombres en las estadísticas no se
   da la vuelta con tan poca prueba.
3. **Un hombre que está en las dos hojas y no en las estadísticas no está en ninguna parte:** nada dice cuál es su lado y una
   conjetura le pondría en un club en el que nunca jugó.
4. **Un partido sin estadísticas conserva su hoja tal cual:** nada dice lo contrario. Es el residuo que esta regla **no puede alcanzar**
   (alrededor de uno de cada cinco partidos recientes no tiene estadísticas); `audit` lo cuenta y la reparación de verdad está en la
   entrada de datos (orientar las hojas con las estadísticas de la misma respuesta). Es una decisión tuya, abajo.

La versión de las tres reglas (`sides-v1`) forma parte de la versión del constructor de historiales: cambiarla obliga a reconstruir.

## Cómo corre

* **Worker:**
  * `referee_identity` **cada hora** (`FBI_REFEREE_IDENTITY_MINUTES`, 60): coloca las grafías nuevas y escribe solo la diferencia,
    jamás toca una decisión de una persona; un pase sin cambios no deja fila en el registro de corridas. Un barrido con auditoría
    una vez al día a las **09:50 UTC**. Se apaga con `FBI_REFEREE_IDENTITY=0` sin desplegar. El perro guardián lo da por colgado a los
    30 minutos.
  * `player_history` **cada 240 minutos** (`FBI_PLAYER_HISTORY_MINUTES`): rehace las rachas de los jugadores de los partidos, los
    traspasos leídos y las plantillas nuevas de los últimos 4 días, y los *caps* de los partidos recientes o con estadísticas
    pendientes; después enlaza las carreras de los entrenadores con su persona y su club. Un barrido diario a las **10:00 UTC** sobre
    todos los jugadores (recoge lo que llegó tarde) y una auditoría que **registra** lo que esté mal (`player_history.audit`). Se
    apaga con `FBI_PLAYER_HISTORY=0`. El perro guardián lo da por colgado a las 3 horas. El primer pase ocurre 23 minutos después de
    arrancar el worker.
  * Los dos trabajos escriben bajo un candado de transacción: si una persona o otro pase está escribiendo, el del worker cede; la
    consola espera hasta 20 s.
* **A mano, desde `backend/` (0 peticiones al proveedor; todo lo que cambia algo es un ensayo en seco hasta que se pone `--apply`):**

```bash
python -m scripts.referee_identity status                       # contadores, cola por motivo, últimas corridas
python -m scripts.referee_identity build                        # ensayo en seco: lo que escribiría un pase
python -m scripts.referee_identity build --apply                # un pase (el primero coloca toda la historia)
python -m scripts.referee_identity audit                        # invariantes y criterios del plan
python -m scripts.referee_identity queue --limit 30             # las parejas en espera, las más grandes primero
python -m scripts.referee_identity find oliver                  # árbitros por (parte de) un nombre o de cualquier grafía
python -m scripts.referee_identity show 123                     # un árbitro: grafías, dudas, cambios, últimos partidos
python -m scripts.referee_identity merge 123 456 --note "..." --apply    # 456 es la misma persona que 123
python -m scripts.referee_identity undo 17 --apply              # deshace el evento de fusión 17

python -m scripts.player_history status                         # contadores de las tablas y últimas corridas
python -m scripts.player_history build                          # ensayo en seco de un pase sobre todos
python -m scripts.player_history build --apply                  # un pase sobre todos (el primero construye toda la historia)
python -m scripts.player_history build --recent --apply         # lo que hace el worker: los jugadores de los últimos días
python -m scripts.player_history build --player 123 --apply     # solo las rachas de ese jugador (repetible)
python -m scripts.player_history audit                          # invariantes, hojas cruzadas y un pase simulado sobre todo (lento; sale con 1 si falla)
python -m scripts.player_history show 123 --at 2026-03-20       # un jugador: rachas, caps, dónde estaba ese día
python -m scripts.player_history coach 456                      # un entrenador: la persona y su carrera con los enlaces
```

## Resultado de la prueba general (22 oct 2026)

**Árbitros — copia de desarrollo (245.872 partidos) con las observaciones reales de árbitros leídas de producción, solo lectura.**
La primera pasada coloca toda la historia en **9 segundos** y una segunda no escribe nada (`audit`: «un pase escribiría» = 0 en cada
tabla; ninguna invariante rota).

| Medida | Resultado |
|---|---|
| Partidos con árbitro / observaciones | 199.890 / 210.275 |
| Grafías (nombre + ámbito) | 9.694 (9.510 son la última palabra de algún partido; 184 solo salen en observaciones que el proveedor corrigió después) |
| Personas | **6.006** (base de las grafías: ancla 6.006, nombre más largo 123, inicial 2.124, visitante 528, sin ámbito 913) |
| Partidos asignados a una persona | **199.890 de 199.890 (100 %)** — criterio del plan: ≥ 95 % |
| Partidos cuyo árbitro no tiene una duda esperando | **98,21 %** (3.578 partidos, el 1,8 %, esperan a una persona; contando los dos lados de cada pareja dudosa serían el 90,32 %) |
| Vetos (dos partidos a la vez) | 12 |
| Filas de historia de oficiales | 206.469 |
| Cola de dudas | **679 parejas**: mismo nombre en otra zona 287 (2.337 partidos en el lado pequeño) · inicial y nombre completo 325 (2.021) · variante de escritura 45 (215) · nombre más largo 22 (144) |
| Pantallas de administración con los datos reales | lista 0,24 s · contadores 0,36 s · cola 0,03 s · ficha del árbitro más ocupado ≤ 0,4 s |

**Qué te va a pedir decidir la cola.** Las parejas más grandes son casi siempre «el mismo nombre en dos países, los dos con muchos
partidos» (`Drew Fischer`: 90 partidos como EE. UU. y 84 como Canadá; `Alex Chilowicz`: 77 y 115): puede ser una sola persona que arbitra
en dos ligas o dos homónimos, y los datos no lo dicen, por eso la regla no decide. En cambio `Miguel Ortiz` (España, 123 partidos)
y `M. Ortíz` (México, 144) comparten apellido e inicial pero cada uno tiene muchísimos partidos en su país: lo más probable es que sean
dos personas, y rechazar la pareja evita que se vuelva a sugerir. Ninguna duda es urgente: mientras esperan, las dos grafías se tratan como dos
personas (más prudente: nadie mezcla historias), y cada decisión se puede deshacer.

**Jugadores — por qué no hay cifras de la construcción completa en la copia.** La copia de desarrollo no contiene alineaciones,
estadísticas ni plantillas de jugadores, así que la construcción entera no se puede ensayar allí. Se probó de tres maneras:
(1) las reglas puras (`spells`, `caps`) con pruebas unitarias y un mundo en miniatura con base de datos real para el almacén, el
trabajo, la consola, los entrenadores, el bloque nacional y las tres reglas de fuga, **todas verificadas con mutaciones** (sin
supervivientes salvo equivalentes documentados); (2) la prueba de punta a punta de que el paquete de un momento no contiene una baja
que una respuesta posterior ya limpió; (3) **consultas de solo lectura sobre producción**, con límite de tiempo y en transacción de
solo lectura:

| Medida (producción, solo lectura) | Resultado |
|---|---|
| Tablas que lee el historial | alineaciones 8,4 M filas (1,1 GB) · estadísticas de jugador 5,3 M (1,5 GB) · traspasos 2,9 M (714 MB) · plantillas 69.720 |
| Jugadores con datos | 209.537 con traspasos · 102.184 con estadísticas · 64.946 en plantillas (unos 140 lotes de 2.000 en total) |
| Un lote de 2.000 jugadores | traspasos 1,2–1,9 s · partidos con estadísticas 1,8–4,3 s (según caché) · plantillas 0,01–0,06 s; las alineaciones, con el índice 0085, serán del orden de las estadísticas |
| Primera construcción completa (estimación) | **entre 15 y 30 minutos** de lectura de una sola conexión, en una sola transacción: o se escribe todo o nada |
| Barrido diario (estimación) | construir y auditar leen a todos dos veces: **entre 15 y 30 minutos al día** (10:00 UTC) de una conexión, sin escribir si nada cambió |
| Ficha de una selección (`FORM_SQL`, 51 jugadores) | 0,26 s |
| Clasificación de equipos | 7.710 clubes · 529 selecciones (214 absolutas y 315 juveniles u olímpicas) · **6 sin clasificar** |
| Partidos terminados con una selección absoluta | 4.776 (de aquí salen los *caps*; unas 200.000 filas, estimado) |
| Nombres de selecciones que la regla juvenil/olímpica deja pasar | **0** (se revisaron todos los de aspecto juvenil: `U-nn`, `Under`, `Olympic`, `Sub-`, `Youth`, `B`, `II`, `Reserve`, `W`, `Women`…) |
| Servidor | 6 CPU, 12 GB (4 GB la base, 2 GB el worker), 95 GB libres de 193 GB |

**Verificación de los criterios del plan.**

| Criterio de «hecho» | Resultado | Prueba |
|---|---|---|
| ≥ 95 % de los partidos con árbitro resueltos a un identificador | 100 % asignados; 98,21 % sin duda pendiente | `scripts.referee_identity audit` (`placed_share`) |
| 0 bajas viejas en el paquete | ninguna: cada baja listada es la última respuesta a la hora del paquete | `test_a_packet_built_by_the_builder_lists_only_what_was_the_latest_word`, `test_the_players_reported_out_are_the_latest_answer_as_of_the_moment` y la regla nocturna `absences_known` |
| La lectura de bajas «a fecha» es lo que se sabía | sí, incluido el borde «respuesta registrada en el mismo instante» | `test_a_player_a_later_answer_cleared_but_the_packet_still_lists_is_a_violation`, `test_an_answer_recorded_at_the_very_moment_is_known_at_it` |
| Un jugador traspasado conserva su historia | sí: una racha por club, con las fechas | `test_a_chain_of_transfers_dates_every_streak`, `test_the_streaks_come_from_transfers_matches_and_squad_lists_and_a_second_pass_writes_nothing` |
| Una fusión de árbitros es reversible | sí: solo mueve grafías y guarda lo que movió | `test_a_merge_moves_aliases_and_nothing_else_and_an_undo_puts_them_back`, `test_a_merge_is_reversible_and_leaves_who_did_it`, `test_a_merge_and_its_undo_leave_the_aggregates_as_they_were` |

La suite pasa de 3.094 a **3.468 pruebas** (3.427 al desplegar F3 y 41 más con F3.1; 4 omitidas, como antes) y la web de 339 a 355;
`ruff`, `mypy` estricto (394 archivos) y `mypy .` (875) limpios; la construcción de producción de la web (`NITRO_PRESET=node-server VITE_DATA_MODE=live`) pasa.

## Lo que se decidió distinto del plan (y los límites que conviene conocer)

* **«Resuelto a un identificador» se mide como «asignado a una persona» (100 %)** y se publica aparte el porcentaje sin duda pendiente
  (98,21 %). Contar solo los partidos sin ninguna duda daría una cifra más baja (90,32 % si se cuentan los dos lados de cada pareja);
  prefiero que veas las dos y sepas qué mide cada una. El informe de la pasada ahora lo dice con palabras, no con un «settled»
  ambiguo.
* **El historial de clubes es de «tiempo de validez», no de «tiempo de conocimiento».** Lo que se lee para el día D nunca usa un
  hecho fechado después de D, pero un traspaso que supimos *después* del partido y que está fechado *antes* de él sí se usa para ese
  partido, como historia verdadera (nunca como un resultado de ese partido ni de uno posterior): el código y el bloque lo dicen. Para
  un partido futuro es lo correcto. Para reconstruir exactamente lo que se sabía en el paquete de un partido pasado (un backtest de
  jugadores) habría que guardar también cuándo se supo cada hecho: es otra fase, y la regla `national_known` ya impide lo grave
  (citar un partido posterior, una hoja no descargada o un día de club posterior al del paquete).
* **Selecciones absolutas únicamente.** El plan hablaba de «caps internacionales»; los partidos de selecciones juveniles y olímpicas
  se excluyen por nombre porque no son la carrera absoluta del jugador. La regla está en un solo lugar (`fbi.people.caps`).
* **Los árbitros no se fusionan solos cuando el parecido es solo del nombre.** Las 679 parejas esperan a una persona. Es la parte más
  lenta de F3 y no se puede acelerar sin equivocarse: el sistema prefiere dos personas a una mezcla.
* **`memory-v2` no se reconcilia.** Lo que ese motor guardó bajo una cadena de texto queda como historia (y oculto en la lista); la
  memoria nueva usa la persona. Mezclar ambas habría inventado un pasado.
* **Las hojas cruzadas se corrigen al leer, no en el dato guardado.** Las filas de `core.fixture_lineup_players` siguen siendo lo que
  el proveedor dijo (la evidencia no se reescribe); el constructor de historiales las lee con la regla `sides-v1` y `audit` cuenta lo
  que giró. Quien más abajo lea esa tabla directamente (la ficha del partido, los modelos de plantilla) debe saber que en 202 partidos
  de 2025 los lados de la hoja están al revés; reparar la fuente es una decisión tuya (abajo).
* **La regla no alcanza a los partidos sin estadísticas** (alrededor de uno de cada cinco recientes): ahí la hoja se toma como llega.
  Es un límite medido, no un olvido; se vigila con `fixtures_with_sheets_only` y `lone_stints` (rachas de un solo partido, que es donde
  un cruce no corregido se notaría).
* **El barrido diario de jugadores es el punto más pesado de F3** (ver la tabla de arriba). Si al medirlo en producción pasa de 30
  minutos o molesta a otro trabajo, se puede espaciar (semanal, con la pasada de cada 4 horas cubriendo el día a día) sin tocar
  nada más.

## Cómo estrenarlo en producción (y qué te aviso antes de cada paso)

1. Copia verificada y **prueba de restauración** antes de migrar, como en F2 (esta vez F3 añade tres migraciones: 0083, 0084 y 0085).
2. `predigolctl deploy`: respaldo propio del despliegue, migraciones (la 0085 construye el índice sin bloquear), permisos, reinicio y
   salud. Con las tablas vacías todo se comporta como antes: la API devuelve las secciones nuevas vacías y los paquetes siguen con la
   cadena del proveedor.
3. Árbitros: `build` en seco, `build --apply` (≈ 10 s) y `audit`.
4. Jugadores: `build --player` en seco con un jugador conocido, luego `build --apply` sobre todos **en segundo plano** (15–30 min;
   los pasos programados ceden mientras tanto) y `audit`.
5. Medir y escribir aquí lo medido (sección «Resultado en producción»), igual que se hizo con F2.

F3 viaja en el mismo paquete que **F1.1** (`tax-v2`: el reloj de precios lee también el hándicap asiático por mitades, apuestas 19 y
104; el extractor relee en segundo plano los cuerpos de la taxonomía anterior; RAW no se toca): ver `RELOJ_DE_PRECIOS_F1.md`.

## Lo que se aprendió al desplegar (22 oct 2026)

F3 + F1.1 entraron en producción el 22 oct 2026 a las 22:50 UTC (backend `be8050de78fd`, web `e8d37dda5eb8`, migraciones 0083–0085),
con copia verificada y prueba de restauración antes. Cuatro cosas salieron al desplegar y están corregidas en el paquete **F3.1**
(solo backend, sin migraciones), que es el que deja todo el sistema como lo describe esta guía:

1. **El primer pase programado de jugadores (23:14 UTC) falló limpiamente y no escribió nada.** El proveedor mete en las estadísticas
   de cada partido una fila de relleno con el jugador «0»; el constructor la tomó por una persona y la restricción de la tabla
   (`player_spells_player_check`) tumbó la transacción entera, que se deshizo. Ahora todas las lecturas ignoran el identificador 0, con
   una prueba de regresión que lo reproduce. Hasta el despliegue de F3.1 el trabajo falló cada 4 horas, sin daño: la tabla de
   jugadores solo tenía 6 jugadores de prueba.
2. **Las hojas de convocados cruzadas del proveedor** (la regla `sides-v1` de arriba) se vieron al contrastar, con datos reales de
   producción en solo lectura, la hoja de un partido con las estadísticas del mismo partido (el ejemplo: Nashville – Inter Miami).
   Son 202 partidos de 137.400; la corrección se hace al leer, sin tocar el dato guardado.
3. **Los permisos de la base no se reaplicaban con el archivo nuevo.** `predigolctl deploy` aplica `grants.sql` dentro del contenedor de
   la base, pero ese archivo estaba montado como archivo suelto, y `git checkout` lo reemplaza por otro (otro inodo) sin que el
   contenedor lo note: se aplicaba la versión **anterior**. Ahora el despliegue lo lee de la copia de trabajo y se lo pasa por la
   entrada estándar (`backend/deploy/vps/bin/lib.sh`); una prueba con un `docker` falso comprueba lo que recibe la base.
4. **Dos reintentos de la migración 0085** (el índice se construye sin bloquear y espera a las transacciones abiertas del worker; su
   límite de espera de bloqueo es de 10 s). El despliegue reintenta solo y a la tercera se aplicó; la migración borra el índice inválido
   que deja un intento interrumpido.

Una nota de higiene: la imagen de producción instala las **últimas versiones permitidas** de las librerías al construirse (en este
despliegue entró FastAPI 0.161.1; la batería completa se repitió con esa versión y pasó: 3.427 pruebas). Fijarlas es un cambio pequeño
para la puerta de calidad final (F14), no de F3.

## Cómo deshacerlo

* Parar solo los trabajos: `FBI_REFEREE_IDENTITY=0` y/o `FBI_PLAYER_HISTORY=0` y reiniciar el worker. Con las tablas vacías o sin
  actualizar, la API devuelve las secciones nuevas vacías y la web no pinta nada, y los lectores del paquete vuelven a la cadena del
  proveedor.
* Quitar todo: volver a la versión anterior del código (`predigolctl rollback`) y `alembic downgrade 0082`, que borra las tablas y
  columnas de F3 (el índice 0085 también). Lo derivado se reconstruye con
  `scripts.player_history build --apply` y `scripts.referee_identity build --apply`; lo único que se perdería son **las decisiones de
  una persona sobre árbitros** (`core.referee_events` y las fusiones), así que antes se hace la copia de despliegue habitual.
* `packet-v5`, `dossier-v3`, `brief-v6`, `memory-v3` y `pm-v5` corren desde el despliegue: los paquetes de partidos próximos son
  distintos de los de v4 (filas nuevas en `ai.match_packets`, que solo se añade) y la IA puede volver a revisar esos partidos una vez.
  Esas revisiones quedan dentro de los topes de presupuesto de siempre (PrediGol Intelligence, 180 US$/mes).

## Lo que decides tú

* **La cola de árbitros** (679 parejas): no hay prisa; las de mayor impacto están arriba. Si prefieres que las revise yo con
  evidencia (competiciones, fechas, país) y te traiga una propuesta, lo hago, pero la decisión de fusionar es tuya.
* Si el barrido diario de jugadores debe seguir siendo diario (ver arriba).
* **Si la entrada de datos debe orientar las hojas de convocados con las estadísticas de la misma respuesta**, de modo que un cruce
  del proveedor no llegue nunca a la base (lo propondría para F8, junto con lo demás que se aprende de cada partido terminado). Hoy
  se corrige al leer y los partidos sin estadísticas quedan tal cual.
* Nada más de F3 pide una decisión tuya: lo demás son hechos guardados y lecturas a fecha.

## Lo que queda vigilado tras desplegar

1. La auditoría de fuga nocturna con las tres reglas nuevas (`referee_known`, `national_known`, `absences_known`), el barrido de
   las 09:50 UTC (`referee_identity.audit`) y el de las 10:00 UTC (`player_history.audit`) en el registro del worker.
2. El tiempo real de la primera construcción y de los barridos diarios de jugadores.
3. El gasto de IA de los primeros días con `packet-v5` / `brief-v6`.
4. El drenaje del atraso de cuotas y la relectura de `tax-v2` (F1.1).
5. Las cifras de `audit` de jugadores que delatan un cruce sin corregir: `lone_stints` (rachas de un solo partido) y
   `fixtures_with_sheets_only` (partidos con hoja y sin estadísticas); y las que cuentan lo corregido (`sheets_crossed`,
   `sheets_doubtful`, `men_nowhere`).
