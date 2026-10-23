# Dos propuestas abiertas: las listas de jugadores que el proveedor entrega cruzadas (decisión 9, F3) y las subidas por bloques de `fixtures_sync` (decisión 11, F4)

*Escrito el 23 de octubre de 2026, al cerrar F8. Todo lo que se cita como medido salió de leer la base de producción con una sesión de **solo
lectura** (nada se escribió, ninguna petición al proveedor); las consultas están en la carpeta del despliegue de F8 del servidor
(`lone_probe.sql` … `lone_probe8.sql`); las dos primeras se probaron antes con datos inventados que contenían los casos esperados y todas se
revisaron contra una base local antes de lanzarlas.*

Dejé estas dos decisiones diciendo «la propongo más adelante». Esta es la propuesta, con lo que se midió. **La primera trae una corrección
mía**, porque dos cosas que escribí sobre las 18.937 «rachas de un solo partido» eran erróneas, una por exceso y otra por defecto (está
explicada al final de la decisión 9).

---

## Decisión 9 — Listas de jugadores que el proveedor entrega cruzadas (F3)

### Qué pasa

El proveedor nos dice quién jugó un partido por dos caminos: la **hoja de convocados** (titulares y suplentes de cada lado) y las
**estadísticas de jugadores**. Cada fila trae un lado, «local» o «visitante», que el sistema decide comparando el equipo que el proveedor
pone en esa lista con los dos equipos del partido. Casi siempre todo coincide. A veces la lista de jugadores de un equipo llega en el lado
del otro: los once de Nashville bajo Inter Miami y al revés.

Lo que ya hace F3 (`sides-v1`): cuando al menos 5 jugadores de una hoja están en las estadísticas del mismo partido y el 80 % o más de ellos
están al otro lado, la hoja se lee dada la vuelta. Son **404 hojas** (202 partidos), sin reescribir el dato guardado. Donde las estadísticas
no existen, o dicen lo mismo que la hoja, esa regla no puede decir nada.

### Lo que se midió (23 de octubre)

La señal para saber si una hoja está cruzada **sin** estadísticas es el historial de sus jugadores. Una *racha de un solo partido* es un
jugador que estaba en el club A, aparece en la hoja del club B en un único partido y vuelve a A. Si ese único partido **fue contra A**, lo
más probable es que no jugara con B contra su propio club, sino que su hoja viniera cruzada.

| Qué | Cifra |
|---|---|
| Rachas de un solo partido (lo que cuenta la auditoría de jugadores) | **18.937** |
| De ellas, con el partido encontrado en una hoja | 16.941 (las otras 1.996 no se encontraron en ninguna hoja de ese día y club; probablemente las sostienen estadísticas) |
| Jugadas **contra el club al que el jugador vuelve** (la firma de una hoja cruzada) | **5.053** (el 27 %), en **319 hojas** |
| Las demás | 13.884: no tienen la firma del cruce (el partido fue contra otro club, o no se encontró en una hoja). Lo más probable son cesiones y registros dobles que nadie anotó; no lo he comprobado una a una |
| Hojas con 5 o más de esas rachas («parecen cruzadas por el historial») | **288**, en **162 partidos**; en 126 de ellos están cruzadas las dos hojas del partido. **268 de las 288 no tienen ninguna estadística** del partido |
| Tamaño típico | una hoja cruzada deja hasta 23 rachas a la vez (un partido entero de jugadores); las 288 hojas suman 4.994 |

Las dos detecciones, cada una sobre su población (las hojas que las estadísticas pueden comprobar y las que no), cuentan la misma historia en
el tiempo, y desde marzo de 2026 no cuentan nada salvo el caso de octubre que se explica abajo:

| Mes | Hojas que dan la vuelta las estadísticas | Hojas que parecen cruzadas por el historial |
|---|---|---|
| 2025-07 | 36 (de 1.566 que se pueden comprobar) | **129** (de 736 sin estadísticas suficientes: **una de cada seis**) |
| 2025-08 | 100 (de 4.258) | **81** (de 1.596) |
| 2025-09 · 10 · 11 · 12 | 26 · 10 · 60 · 24 | 2 · 2 · 4 · 6 |
| 2026-01 · 02 | 4 · 16 | 11 · 26 |
| 2026-03 a 2026-09 | **0** (de ≈ 31.000 hojas) | **0** |
| 2026-10 | 0 | 12 (los 6 partidos del 6 de octubre; ver abajo) |

**Dónde:** la Conference League (168 hojas, del 10 de julio al 28 de agosto de 2025: las rondas previas), la Europa League (22, mismas
fechas), «Amistosos de clubes» (22, del 10 de enero al 15 de febrero de 2026), la AFC Champions League Two (15), la Leagues Cup (9, desde
2023) y la EFL Trophy (12). Son rachas en bloque: una competición y unos días.

### Lo que NO es

* **No es que el partido cambiara de orientación.** Los eventos de un partido guardan el lado y además el id de equipo del proveedor, así
  que se pueden comparar con la orientación actual del partido: en los **52.663** partidos terminados con eventos desde enero de 2025 no
  hay **ni uno** que la contradiga, tampoco en los 145 partidos con una hoja dada la vuelta por las estadísticas. El partido y sus
  eventos están bien orientados; lo que llega cruzada es la *lista de jugadores*.
* **No parece que una relectura posterior lo arregle.** En Rotherham–Bradford (6 de octubre, siguiente apartado), el jugador cuyas
  versiones guardadas revisé (Nemane) ya venía en el lado equivocado en la primera lectura guardada, a las 19:53 UTC, y siguió en él en las
  relecturas posteriores. No sé si el proveedor lo corrige semanas después: es lo que probaría la opción (c).

### Lo nuevo: el 6 de octubre de 2026

Seis partidos de la EFL Trophy de esa tarde (Rotherham–Bradford, Fleetwood–Barnsley, Port Vale–Mansfield, Wycombe–Bristol Rovers,
Stevenage–Leicester, Crawley–Bromley) tienen **las doce hojas con la firma del cruce** (151 jugadores en total) y, a la vez, **las
estadísticas del partido coinciden con la hoja**: las dos fuentes dan los mismos jugadores en el mismo lado, y los dos lados son los del
rival. Las comprobé en el detalle: en Rotherham–Bradford, los cinco jugadores de la hoja «visitante» que miré tienen todo su historial en
Rotherham, con partidos suyos antes y después de ese día (Nemane, Rafferty, Bradshaw, Ashley, Cann). El **entrenador** de cada lado sí es el
del equipo correcto en los cuatro casos en que conocemos su club (Bruce en Rotherham, Revell en Stevenage, Clough en Mansfield, Woodman en
Bromley): lo que viene intercambiado son los jugadores dentro de la respuesta del proveedor, en la hoja y en las estadísticas a la vez.

Por eso `sides-v1` **no lo ve** (compara hoja con estadísticas, y aquí coinciden), y por eso lo vio únicamente el historial: la señal salió
cuando los jugadores volvieron a jugar con su club, unos días después. Es la prueba de que el defecto **no está cerrado**: hubo un
verano de 2025 con cientos de hojas, un grupo en enero–febrero, siete meses sin nada y ahora un día con seis partidos.

### A quién afecta

* **El historial de clubes de F3.** Cada jugador afectado recibe una racha de un día en el club equivocado. Como «dónde estaba el día D»
  solo se equivoca ese día, los dossiers de los partidos posteriores no cambian; lo que sí se llena es la cuenta de `lone_stints`.
* **Quien lee las hojas tal como llegan.** Ya corrigen lo que las estadísticas permiten (`sides-v1`) el historial de jugadores (F3), las
  tácticas (F6) y Match Knowledge (F8, que marca `sheets_crossed`). Leen la hoja sin corregir la ficha del partido del Centro, el dossier
  (las alineaciones de los partidos anteriores de cada equipo), los paquetes de la IA (la alineación del propio partido) y la revisión
  posterior al partido. Para las hojas que ninguna estadística delata, todos ven la lista del rival. Los partidos de 2025 y de
  enero–febrero ya no entran en las ventanas de «partidos recientes»; los 6 de octubre sí. **No medí cuántos paquetes recientes los
  usaron.**
* Lo que no se ve: el detector por historial solo cuenta jugadores con un club antes y después, así que **es un mínimo**; una hoja cruzada de
  jugadores sin historial no deja ninguna racha.

### Opciones

| | Qué hace | Qué cuesta / qué no arregla |
|---|---|---|
| **(a)** | Nada. | El defecto se queda donde está y no nos enteramos de la próxima vez salvo por casualidad (así vi la del 6 de octubre). |
| **(b)** | **Vigilar con el historial.** Sumar a la auditoría diaria de jugadores el recuento por mes de «hojas que parecen cruzadas» (5 o más jugadores que vuelven al club contra el que se jugó) y abrir una incidencia de calidad con el partido. | Unas 30 líneas y su prueba; no toca datos ni lectores. Avisa unos días después del partido (cuando los jugadores vuelven a jugar), no el mismo día. |
| **(c)** | **Volver a pedir al proveedor** los partidos sospechosos (los 162 que tienen alguna hoja sospechosa, 6 de ellos los de octubre: unas 160 peticiones, el 0,3 % de un día de presupuesto). Si ya corrigió su dato, la base queda arreglada en el origen y la versión anterior se guarda en la auditoría de detalle; si no, sabemos que no corrige. | Empezar por los 6 de octubre (6 peticiones). Escribe datos de partidos terminados por la vía normal de relectura, por eso lo pido. |
| **(d)** | **Regla de lectura por historial** (`sides-v2`) para el historial de clubes: una hoja cuyos jugadores, en su gran mayoría, tienen su club en el equipo rival (y la hoja de enfrente también) se lee dada la vuelta. | Corrige F3, no las demás pantallas. Se valida a ciegas contra las 404 hojas que las estadísticas ya resolvieron: cuántas encuentra y cuántas hojas normales marcaría de más. |
| **(e)** | **Tabla de orientación para todos los lectores**: una fila por hoja cruzada (partido, lado, regla, evidencia) y una vista que todos usan. Hoy serían unas 700 hojas (404 + 288). | Es el arreglo completo y el más grande: toca a los lectores que hoy leen la hoja sin corregir y a los que ya la corrigen, cada uno con su prueba. Solo merece la pena si el defecto vuelve o si quieres limpia la historia de esos meses. |

**Mi recomendación:** **(b)** ahora (lo hago yo, va en el siguiente despliegue) y **(c) con los 6 partidos de octubre** si me das permiso para esas
6 peticiones. Dejaría **(d)** y **(e)** para si el proveedor no corrige y tú quieres la historia limpia o el defecto vuelve una tercera vez.
Un detalle útil de (b): como el detector llega unos días tarde, si quieres detección **el mismo día** se puede comparar la hoja con la
plantilla vigente de cada equipo ya en la entrada de datos; es más trabajo y lo propondría solo después de ver cómo se comporta (b).

### Lo que corrijo de lo que te dije

1. En la guía de F3 escribí que las **18.937** rachas de un solo partido eran hojas cruzadas sin estadísticas. **Eran demasiadas:** lo son
   5.053 (el 27 %), en 319 hojas; las otras 13.884 no tienen esa firma.
2. Al preparar esta propuesta, mi primera cuenta fue que, con la tasa medida del 0,15 %, el defecto explicaría «del orden de cien
   partidos entre los 76.857» y no 18.937 rachas. **Comparaba partidos con jugadores:** cada hoja cruzada deja hasta 23 rachas. Con la
   medición, 288 hojas (162 partidos) explican 4.994 rachas. Las dos frases eran erróneas, en sentidos contrarios.
3. En la guía de F3 dije también que el defecto casi no aparecía desde la primavera de 2026. Es verdad para lo que `sides-v1` puede ver
   (cero hojas desde marzo), pero el 6 de octubre apareció una variante que `sides-v1` no puede ver.

### Lo que decides tú

* **(c) con los 6 partidos de octubre:** sí / no. Es la única opción que vuelve a leer partidos terminados y la que más información da (si
  el proveedor corrige o no).
* **(d) y/o (e):** ahora o solo si el defecto vuelve. Mi sugerencia: solo si vuelve.
* Si no dices nada: hago **(b)** (sin cambiar ningún dato) y no hago nada más.

---

## Decisión 11 — Subidas por bloques de `fixtures_sync` (F4)

### Qué pasa

`fixtures_sync` pide una temporada entera por liga (una petición) y la aplica en **una sola transacción**: `ingestion/fixtures.py` aplica
el contenido y confirma (`conn.commit()`) una vez por temporada. La de «Friendlies Clubs» (liga 667, 8.359 partidos) dura unos **27
minutos** (≈ 0,19 s por partido) y mantiene abierta una transacción de escritura sobre `core.fixtures` y tablas relacionadas, **cuatro
veces al día** (01:03, 07:03, 13:03 y 19:03 UTC; las transacciones quedan abiertas entre unos 24 y 51 minutos después de empezar, la de
las 07:03 llegó hasta las 07:54). Hizo fallar el primer intento de migrar F5: la migración pidió un bloqueo y se rindió a los 10 segundos.

### Lo que hacemos hoy

Migrar solo con la **comprobación de calma**: `step_deploy.sh` no empieza si hay una transacción de escritura de más de 20 s sobre esas
tablas, ni en las horas de `fixtures_sync`, ni después de las 18:30 UTC. Funciona: F5 (el segundo intento), F4, F6, F7 y F8 se desplegaron
sin una sola espera de bloqueo (la vigilancia de cada despliegue lo comprueba; la de F8, una hora, solo registró mis propias cargas).
El coste es de calendario —hay horas en las que no se despliega—, no de dinero ni de datos.

### Opciones

| | Qué hace | Qué cuesta |
|---|---|---|
| **(a)** | Dejarlo como está. | Cero riesgo. La regla de calma queda en la plantilla de despliegue. |
| **(b)** | **Confirmar por bloques:** partir la respuesta de la temporada en trozos de 250–500 partidos y aplicar y confirmar cada uno (`apply_fixtures_payload` ya dice que «el llamador es dueño de la transacción»; las escrituras son monótonas por hora de lectura, así que repetir un trozo es inofensivo). Cada transacción duraría de unos 50 s a 1,5 min en lugar de 27. | Un fallo a mitad deja la respuesta a medio aplicar hasta el siguiente ciclo, que la rehace; los contadores de la corrida se suman por trozo. Cambia el comportamiento de la entrada de datos, por eso necesita una prueba que mata el proceso a mitad y comprueba que el ciclo siguiente converge al mismo estado. No retrasa ninguna actualización: las filas de los primeros trozos se ven antes, no después. |
| **(c)** | **Averiguar por qué** cuesta 0,19 s por partido (los disparadores de la 0080 sobre estado y resultado, la clasificación de sede neutral, `apply_fixture_facts`, los índices) y acelerar esa parte. Puede bajar de 27 minutos a unos pocos sin cambiar ninguna semántica. | Se mide repitiendo la misma respuesta guardada sobre una copia restaurada (ya hacemos una prueba de restauración en cada despliegue): no se toca producción. |

**Mi recomendación:** **(c) primero** y **(b)** si después sigue durando más de unos minutos.

### Lo que decides tú

* **(b):** sí / no. Es un cambio de comportamiento de la entrada de datos.
* Si no dices nada: hago solo **(c)** —medir en la copia restaurada en el siguiente despliegue— y te cuento el resultado. No cambia nada en
  producción.
