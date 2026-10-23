# Match Knowledge — un partido terminado como un solo objeto, por capas (plan F7)

Documento técnico para quien mantenga el código. La guía para el dueño (qué es, qué ve cada quien, qué decide y las cifras medidas en
producción) es `docs/owner/POSTPARTIDO_F7.md`. El código está en `src/fbi/knowledge/` (cuatro módulos), `src/fbi/ingestion/match_knowledge.py`
(el trabajo del worker), `src/fbi/api/{contracts,services,routers}/knowledge.py` (la página del partido), `scripts/match_knowledge.py`
(la herramienta de línea de órdenes) y las migraciones `0089_event_kinds.py` y `0090_match_knowledge.py`.

## 1. Qué es, y qué no es

Cuando un partido termina, lo que PrediGol sabe de él está repartido en una docena de tablas que escriben trabajos distintos en momentos
distintos: el resultado y sus correcciones, las estadísticas de los equipos, los eventos, las hojas de alineación y lo que hizo cada
jugador, las cuotas desde la apertura hasta el cierre, las decisiones y los picks con su desenlace, el post-mortem. Cada lector que quería
«qué pasó en este partido» (la pantalla del partido, el post-mortem, la memoria de un equipo, de un árbitro o de un mercado, el dossier
siguiente) lo armaba otra vez con sus propias reglas. Match Knowledge es **un objeto por partido terminado**, armado **por reglas** (sin IA
y sin coste) a partir de hechos ya guardados, en **nueve capas**; cada capa dice de qué está hecha (`sources`), cuán fresca es (`known_at`)
y hasta dónde se puede confiar en ella (`status`).

Lo que **no** es:

* No es una señal. No cambia ningún modelo, pronóstico, decisión, pick ni liquidación, y **ningún lector de antes del partido puede
  leerlo** (§8): conocer cómo terminó un partido no puede colarse en lo que se dice antes de otro.
* No inventa ni adivina. Una capa que no se puede armar dice `missing`; una armada con menos de lo que necesita dice `partial` y por qué
  (`notes`); la capa del contexto externo está `off` hasta que el dueño decida otra cosa.
* No llama al proveedor. Lee solo lo que ya está guardado; cuesta CPU de la base y nada más.
* No es un registro de lo que PrediGol dijo (eso es `models.match_forecasts`, `intel.decisions`, `picks.*`): es lo que el partido resultó ser.

## 2. Qué se guarda (migraciones 0089 y 0090, solo aditivas)

| Objeto | Qué es | Lo escribe | Lo lee |
|---|---|---|---|
| `core.fixture_event_kinds` (0089) | Una fila por línea de `core.fixture_events` leída: su tipo (`kind`), su periodo (`1H`, `2H`, `ET`, `PEN`), el lado al que cuenta y el lado del jugador, la línea con la que se empareja (una segunda amarilla), las banderas, la versión de las reglas (`rules_version`) y el `fetched_at` de la línea de la que se leyó. **Tabla derivada**: se reescribe entera por partido cuando cambia su lista o las reglas (se borran las líneas que ya no están, se escriben las que difieren, el resto no se toca). Sin claves foráneas. | el constructor (`fbi.knowledge.builder`), en la misma transacción que la fila de Match Knowledge a la que pertenece | la API (solo lectura), la herramienta, `builder.coverage` |
| `intel.match_knowledge` (0090) | La historia de lo que cada partido terminado resultó ser: **una fila por construcción**, con `layers` (JSONB, nueve capas), `quality` (JSONB), `completeness`, `known_at`, `inputs_hash`, `content_hash`, `version` (`mk-v1`) y `supersedes`. **Solo se añade** (disparador `match_knowledge_append_only` con `intel.refuse_change`). Sin clave foránea a `core.fixtures` (necesitaría un bloqueo sobre una tabla que `fixtures_sync` mantiene en una transacción de escritura de ~27 minutos cada seis horas: las revisiones 0085 y 0086 esperaron por eso). | el constructor | la página del partido, la herramienta, `builder.coverage` |
| `intel.match_knowledge_latest` (0090) | Vista: la fila más reciente de cada (partido, versión). | — | la página, la herramienta |

Permisos (`deploy/vps/db/grants.sql`, por esquema, que `predigolctl deploy` aplica; probados en `tests/integration/test_db_roles.py`): la
API solo lee las dos tablas y la vista; el worker inserta en `intel.match_knowledge` (cambiarla o borrarla lo rechaza el disparador, también
al worker) y escribe y borra en `core.fixture_event_kinds`.

**Por qué una tabla derivada y no columnas en `core.fixture_events`** (el boceto del plan): (1) `audit.keep_settled_detail` (revisión 0061)
es un disparador `AFTER UPDATE OR DELETE` que copia, entera y en JSON, a `audit.settled_detail_changes` cada fila de un partido TERMINADO
cuyos valores cambian: rellenar dos columnas para los 3,2 millones de líneas las copiaría todas, y cambiar ese disparador no es un efecto
secundario aceptable de una clasificación; (2) la ingesta reemplaza la lista de un partido entera (`DELETE` + `INSERT`) cuando cambia, de modo
que una columna rellenada al escribir guardaría las reglas del día en que se escribió, y el periodo de una línea depende del estado final
del partido, que puede llegar después; (3) las reglas se van a mejorar y una tabla derivada con versión se reconstruye, una tabla del
proveedor no se reescribe. Nada de `core.fixture_events` cambia: ni un bloqueo, ni un disparador, ni una columna.

## 3. Los eventos: qué es cada línea (`events-v1`, `fbi.knowledge.events`)

El proveedor lista, en el orden en que ocurrieron las cosas, goles, tarjetas, cambios y decisiones del VAR como texto
`(type, detail, comments)`. Cinco cosas de ese texto no son lo que parecen; todas se midieron en producción (23 oct 2026, 3.218.434 eventos):

| Hallazgo | Regla |
|---|---|
| **Un gol de la lista no siempre es un gol del partido.** Las tandas de penales son `Goal / Penalty` y `Goal / Missed Penalty` con el comentario `Penalty Shootout` (10.908; todos en el minuto 120; en los antiguos `extra_minute` es el número del lanzamiento). Un autogol se archiva bajo el equipo que RECIBE el gol (1.154 partidos cuyo único gol fue un autogol). | `shootout_goal` / `shootout_miss` (periodo `PEN`) se distinguen de `penalty_goal` / `penalty_missed`; en un autogol, `side` es el lado al que cuenta y `player_side` el del jugador (el otro). |
| **Una segunda amarilla son dos líneas.** `Yellow Card` y `Red Card` del mismo jugador, del mismo lado y del mismo minuto (18.676 de 41.179 rojas con jugador; en otras 50 la amarilla viene DESPUÉS de la roja y en 40 de ellas ya tenía una amarilla antes: es lo mismo en otro orden); solo 100 eventos dicen `Second Yellow Card` sin más. Las estadísticas del propio proveedor concuerdan: `yellow_cards` incluye la amarilla del par y `red_cards` la roja (1.571 de 1.707 lados y 1.684 de 1.707). | La roja del par es `second_yellow` (cuenta en las expulsiones) y la amarilla del par lleva `second_of_pair`; las dos se apuntan con `pair_seq`. Una roja de un jugador con una amarilla en OTRO minuto es `red` con `after_yellow` (una roja directa tras una amarilla, o una segunda amarilla listada con una sola línea: **la lista no lo dice y no se adivina**, 1.529 casos en todo el historial). |
| **El VAR que anula un gol no deja un gol al que apuntar.** En 2.251 de los 2.253 lados con `Goal cancelled` / `Goal Disallowed*` los goles de la lista SON el marcador: el proveedor quita el gol y deja la decisión. | La decisión es un hecho del partido por sí misma (`var_goal_cancelled`, minuto, lado). No se enlaza con ninguna línea ni se resta del marcador. |
| **Algunas líneas no nombran a nadie.** 3.303 `Normal Goal` (de 90.175 en los últimos 400 días), 63 autogoles y 331 penales tienen ni id ni nombre de jugador. | Son goles igual (están en el marcador) pero no se pueden dar a un jugador: la bandera `no_player` lo dice y la capa de jugadores cuenta cuántos no pudo atribuir (`goals_with_no_player`). |
| **El periodo no es el minuto.** `minute` es el reloj: el descuento es `minute = 45` (o 90, 105, 120) con un `extra_minute`, y 73 partidos que terminaron en el tiempo reglamentario traen minutos sobre 90 (164 eventos). | Un minuto sobre 90 es tiempo extra **solo en un partido que fue** a tiempo extra (`AET`, `PEN`); en cualquier otro es el descuento del segundo tiempo (`2H` con la bandera `late_minute`). Sobre 120 es basura (`minute_out_of_range`): se conserva y cuenta en el último periodo. |

Tipos (`KINDS`): `goal`, `own_goal`, `penalty_goal`, `penalty_missed`, `shootout_goal`, `shootout_miss`, `yellow`, `second_yellow`, `red`,
`card_unknown`, `sub` (el jugador que SALE es `player_*` y el que ENTRA es `assist_*`: 97,5 % de los `player` muestreados eran titulares y
99,9 % de los `assist` estaban en el banco), `var_goal_cancelled`, `var_goal_confirmed`, `var_penalty_awarded`, `var_penalty_cancelled`,
`var_card_upgraded`, `var_card_cancelled`, `var_card_reviewed`, `var_other` y `other`. **Lo que cambia el marcador** (`SCORING`) es `goal`,
`own_goal` y `penalty_goal`; un penal fallado y las tandas no. Banderas: `after_yellow`, `second_of_pair`, `late_minute`,
`minute_out_of_range`, `unknown_detail` (palabras que la tabla no ha visto: la línea es `other`, `card_unknown` o `var_other`, **nunca una
suposición**), `no_side` (el equipo del proveedor no es ni el local ni el visitante: 0,07 % de los eventos) y `no_player`.

`normalize` es pura (ni base de datos ni reloj), determinista (la misma lista da la misma respuesta) e idempotente (normalizar de nuevo no
cambia nada), y no descarta ninguna línea: cada línea de la lista sale como un `Event`.

**Exactitud medida** (producción, solo lectura, 23 oct 2026, 34.777 partidos terminados con eventos en los últimos 400 días y 506.078
líneas): los goles de los 90 minutos que dice la lista coinciden con el resultado en 34.671 partidos (**99,70 %**), el descanso en 34.690 de
34.770 (**99,77 %**) y el tiempo extra en 210 de 213 (**98,59 %**; en ~5 % de las filas `AET` la columna de tiempo extra de
`core.fixture_results` es un total acumulado, revisión 0031: los 3 fallos pueden ser eso). De los 106 que no coinciden, a la lista le
FALTAN goles en 60 y le SOBRAN en 45 (19 con un gol que nadie marcó, 15 con un «Penalty cancelled» del VAR, 4 con un «Goal cancelled» donde
la lista conservó el gol): un «Penalty cancelled» puede quedar junto a un «Normal Goal» fantasma sin jugador del mismo lado.

## 4. Las nueve capas (`mk-v1`, `fbi.knowledge.layers`)

Cada capa es `{status, known_at, sources, data, notes}`: `status` es `ok` (armada con todo lo que necesita), `partial` (con menos, y
`notes` dice qué), `missing` (no se pudo armar) u `off` (no encendida); `known_at` es el momento más reciente en que PrediGol supo algo de
las que la forman (no el momento del partido: para un partido jugado hace un año y cargado en octubre es octubre); `notes` son códigos
estables, no frases.

| Capa | Qué dice (`data`) | Lee de | `ok` si | Códigos de `notes` |
|---|---|---|---|---|
| `c1_result` | marcador a los 90 (`reg`), al descanso (`ht`), tras el tiempo extra (`final`), la tanda (`pen`); `outcome`, `total`, `btts`; `decided_by` (`regulation`, `extra_time`, `penalties`); `neutral`; las correcciones del proveedor (`revisions`: cuántas, la última, tipos y campos); la eliminatoria (`tie`: formato, partidos, cuál es éste y, **solo en el partido que la cierra**, el global, el ganador, cómo se decidió, la tanda y si el proveedor contradice el global) | `core.fixtures`, `core.fixture_results`, `core.fixture_result_revisions`, `core.ties` | hay fila de resultado (si no, `missing`) | `no_result_row`, `no_half_time` |
| `c2_team_stats` | por lado: tiros, a puerta, fuera, bloqueados, dentro y fuera del área, córners, faltas, fuera de juego, amarillas, rojas, atajadas, posesión, pases, pases acertados, goles esperados (xG), goles evitados; **una cifra que el proveedor no dio es nula, nunca cero** | `core.fixture_team_stats` (se toma el proveedor que tiene los DOS lados, `api-football` antes que `football-data.co.uk`; no se mezcla un lado de uno con otro del otro) | los dos lados traen cifras (`partial` con uno; `missing` con ninguno) | `no_home`, `no_away`, `no_figures` |
| `c3_events` | `rules` (`events-v1`), `n`, `counts` por tipo, goles por periodo (`1H`, `2H`, `ET` si fue a tiempo extra, `PEN` si hay lanzamientos), `check` (¿la lista da el marcador?: `reg`, `ht`, `et`, `pen`, `cards`, y `listed` si el reglamentario difiere) y las listas compactas `goals`, `missed`, `shootout`, `cards`, `var` en orden cronológico (el orden del proveedor no lo es dentro del descuento) | `core.fixture_events` (leída por `events-v1`) | la lista da el marcador y todos los periodos que se pueden comprobar cuadran (si no, `partial`; sin eventos, `missing`) | `score_unknown`, `events_do_not_give_the_score`, `ht_differs`, `et_differs`, `pen_differs`, `cards_differ_from_the_statistics`, `words_not_met`, `no_events` |
| `c4_players` | por lado: cuántos figuran, cuántos jugaron, titulares y suplentes que entraron; **los tres mejor valorados** (id, nombre, nota, minutos, goles, asistencias), el capitán y los goles sin jugador | `core.fixture_player_stats` (la hoja de estadísticas pone a cada jugador en su lado también cuando la alineación vino cruzada) | los dos lados y los minutos están (`partial` si falta uno) | `no_home`, `no_away`, `no_minutes`, `no_ratings` |
| `c5_tactics` | por lado: formación, entrenador (`id:N` o `name:texto`) y los cambios `[minuto, ventaja]`; y la **historia del marcador** (`story`): quién fue por delante, cambios de ventaja, minutos en que cada lado (o ninguno) iba ganando, primer y último gol, primera expulsión con el marcador de ese momento | `core.fixture_lineups`, `core.fixture_events` | hay las dos hojas, los eventos dan el marcador y las dos formaciones están | `formation_missing`, `story_not_told`, `sheets_crossed` |
| `c6_market` | por mercado (`1X2`, `OU`, `BTTS`, `AH`; en `OU` y `AH` también la `line`): la probabilidad de consenso sin margen de cada desenlace **de la apertura al cierre** (`p: {desenlace: [apertura, cierre]}`), cuántas casas, cuándo y a cuántos minutos del inicio fue la última lectura; y, cuando el proveedor aún los tenía tras el partido, sus **últimos precios** (`final`: precio mediano de las casas, cuántas, y a cuántos minutos del inicio) | `market.market_consensus` (Shin), `market.final_prematch_odds` | están `1X2`, `OU` y `BTTS` | `no_1X2`, `no_OU`, `no_BTTS` |
| `c7_context` | — | — | **`off` siempre** (la decide el dueño) | `decided_by_the_owner` |
| `c8_picks` | `decisions`: cuántas, las líneas (mercado, desenlace, línea) con su último estado, el desenlace y las cinco mejores con su cuota, ventaja, apuesta, resultado, ganancia y CLV; `picks`: los picks en sombra por mercado y su ganancia | `intel.decisions`, `intel.decision_outcomes`, `picks.picks`, `picks.pick_results` | todo lo que podía liquidarse ya está liquidado (`partial` mientras no) | `not_settled_yet` |
| `c9_postmortem` | los post-mortems de esas decisiones: cuántos, la versión, los veredictos, las calidades y los cinco primeros con sus causas | `intel.postmortems` | hay al menos uno | — |

La eliminatoria sigue una regla de honestidad: **un partido de ida dice que fue el primero de dos y nada de lo que pasó después**, así que
el conocimiento de una ida no cambia cuando se juega la vuelta.

`c6_market` se lee con la línea principal: `OU` en 2,5 si se cotiza; si no, la línea que más casas cotizan y, entre esas, la de precios más
parejos (la regla del tablero de cuotas). La apertura es la primera lectura de consenso de la semana anterior al inicio
(`OPENING_LOOKBACK_DAYS = 7`, la del paquete de la IA). **El cierre es la última lectura de consenso guardada antes del inicio, y en
producción queda a unos 175 minutos de él** (mediana, p10 175, p90 179, sobre 1.513 partidos de 14 días), porque eso es lo que el reloj de
precios guarda; los últimos precios del proveedor (`final`) están mucho más cerca (mediana de 85 minutos antes del inicio, p90 de 218) pero
solo existen para el 72 % de los partidos de 30 días. Mientras el CLV no use una sola fuente (F8), hay dos cierres y los dos se guardan.

## 5. Calidad, dudas y completitud

`completeness`: `complete` si el resultado y las tres capas de hechos (`c2`, `c3`, `c4`) están `ok`; `minimal` si el resultado no está `ok`
o las tres de hechos faltan; `partial` entre medias. **Una capa que no es de hechos (mercado, picks, post-mortem) no cuenta para ser completo:**
un partido de hace un año puede ser `complete` sin haber tenido nunca un precio guardado.

`quality` es `{layers: {capa: estado}, events_give_the_score: bool | null, doubts: [...]}`. Las dudas (`doubts`) son lo que **no se pudo
afirmar**, con códigos estables que la web traduce:

| Código | Qué significa |
|---|---|
| `no_result` | el partido no tiene fila de resultado |
| `events_do_not_give_the_score` | los goles de los 90 minutos de la lista de eventos no suman el resultado (la historia del marcador no se cuenta) |
| `events_ht_differ`, `events_et_differ`, `events_pen_differ` | lo mismo para el descanso, el tiempo extra y la tanda |
| `cards_differ_from_the_statistics` | las amarillas o las expulsiones de los eventos no son las de las estadísticas |
| `sheets_crossed` | el proveedor cruzó las alineaciones de los dos equipos: no se usan las formaciones (`fbi.people.sides`) |
| `event_words_not_met` | algún evento trae palabras que `events-v1` no ha visto; se cuenta sin interpretar |
| `lines_with_no_player` | algún gol, penal o tarjeta no trae jugador |
| `odd_minutes` | algún evento trae un minuto fuera de lo normal (sobre 90 sin tiempo extra, o sobre 120) |

## 6. Cuándo se arma, cuándo se vuelve a armar y qué garantiza la base

* **Cuándo.** Un partido se arma cuando está terminado (`status_group = 'finished'`) y **asentado**: 26 horas después del inicio
  (`layers.SETTLE`), cuando el proveedor ya hizo su última relectura. `SETTLE` vive en el módulo puro y no en el constructor para que la
  página del partido pueda decir «todavía no está asentado» sin importar el módulo que escribe (la prueba de aislamiento lo guarda).
* **Qué partidos.** Por defecto, los de las competiciones que PrediGol sigue (`core.competitions.is_tracked`); `--all-competitions` en la
  herramienta quita ese filtro. En producción, los 38.121 partidos terminados de los últimos 400 días son de competiciones seguidas.
* **Cuándo se vuelve a armar.** Solo cuando la huella de las entradas no es la de la última construcción. `reader.fingerprints` calcula, con
  unas pocas consultas agregadas y sin transferir filas, **la huella del CONTENIDO** de lo que leen las capas (marcadores, líneas de
  eventos, estadísticas de los jugadores, el último precio, hojas) y **no de los momentos en que se bajaron**, más las versiones de las
  reglas (`layers.RULES`: `mk-v1`, `events-v1`, `sides-v1`). Que el proveedor relea un partido y encuentre lo mismo no cambia nada; si no,
  cada relectura añadiría una fila que dice lo que decía la anterior. Las columnas se declaran una sola vez (`*_FACTS` en la huella;
  `*_MOMENTS` solo en el `known_at` de las capas), así que una columna no puede leerse sin entrar en la huella: una prueba cambia cada una
  y ve moverse la huella. Las fuentes solo-anexar (decisiones, desenlaces, post-mortems, correcciones de resultado) entran por su conteo
  y su id más nuevo; el mercado, por su último consenso antes del inicio (después del partido nada escribe antes del inicio); los últimos
  precios, por lo cotizado. La huella se toma **antes** de leer las filas: un cambio que llegue entre medias lo encuentra el pase siguiente
  en vez de perderse.
* **`inputs_hash` y `content_hash`.** `inputs_hash` es el hash de la huella (¿hay que reconstruir?). `content_hash` es el hash de lo que
  el objeto DICE, sin los momentos (`known_at`): la misma lectura, hecha más tarde, dice lo mismo.
* **La cadena.** Cada fila nombra la que reemplazó (`supersedes`; la primera no tiene). Un índice único sobre `(fixture_id, version,
  COALESCE(supersedes, 0))` deja que una construcción sea reemplazada **una sola vez**: dos constructores que leyeron la misma fila más
  reciente (el worker y una persona en la consola) no pueden añadir ambos la siguiente; el segundo encuentra el sitio ocupado y se retira
  (`raced`; `INSERT … ON CONFLICT DO NOTHING`). Un partido puede ir A, B y otra vez A (el proveedor corrige un resultado y lo corrige de
  vuelta): la tercera fila tiene el contenido de la primera y es un hecho propio. La más reciente es lo que el partido es hoy; las
  anteriores, lo que fue. Una versión nueva de las reglas (`mk-v2`) añade filas al lado de las viejas, no las toca.
* **Las líneas de eventos** se reescriben en `core.fixture_event_kinds` en la misma transacción y solo por el constructor que es dueño de la
  fila nueva. Una línea está «rancia» si faltan o sobran filas respecto de la lista o fue leída con otra versión de las reglas
  (`rules_version`); `builder.coverage` las cuenta y la siguiente construcción del partido las repara. Que el proveedor baje la misma lista
  otra vez no las vuelve rancias (`event_fetched_at` dice de qué bajada salió la fila).
* **Un partido que falla** (un defecto en una regla, un valor que las capas rechazan) se deshace en su propio punto de guardado, se anota y
  el resto sigue. El que llama confirma, salvo `commit`, que confirma por tandas de 200 partidos.

## 7. Cómo se lee y cómo corre

**Trabajo del worker** (`fbi.ingestion.match_knowledge.run_job`): `match_knowledge` cada 30 minutos sobre los últimos 10 días (hasta 300
partidos por corrida y 240 s) y un **barrido** diario a las 10:30 UTC sobre los últimos 400 días (hasta 900 s y sin tope de partidos: un
resultado que el proveedor corrige semanas después, una regla que cambió, un partido que se perdió). Escribe una corrida en el libro
(`raw.ingestion_runs`) **solo si construyó, falló o se cortó**: una media hora sin novedades no deja fila. El vigilante de corridas
(`ops/run_watchdog.py`) lo conoce con un plazo de 20 minutos. Se apaga **sin desplegar** con `FBI_MATCH_KNOWLEDGE=0` en
`/etc/predigol/app.env` y reiniciando el worker; los ajustes finos son `FBI_MATCH_KNOWLEDGE_{MINUTES,DAYS,SWEEP_DAYS,PER_RUN,RUN_SECONDS,SWEEP_SECONDS}`.

**Herramienta** (`python -m scripts.match_knowledge`, 0 peticiones al proveedor; `build` es un ensayo en seco hasta `--apply`):

```bash
python -m scripts.match_knowledge status                         # cobertura, tamaño de las tablas, últimas corridas del trabajo
python -m scripts.match_knowledge coverage --days 400            # partidos con construcción, qué tan completos, líneas de eventos leídas
python -m scripts.match_knowledge build                          # ensayo en seco: lo que construiría un pase del worker (10 días)
python -m scripts.match_knowledge build --apply                  # construirlo
python -m scripts.match_knowledge build --days 400 --apply       # la carga inicial: un commit por 200 partidos
python -m scripts.match_knowledge build --fixture 123 --apply    # uno o más partidos, de cualquier edad (solo terminados)
python -m scripts.match_knowledge audit --sample 200 --seed 1    # los criterios del plan, sobre las filas guardadas y una muestra reconstruida
python -m scripts.match_knowledge show 123                       # la construcción más reciente, capa por capa
python -m scripts.match_knowledge show 123 --layer c6_market     # una capa, en JSON
python -m scripts.match_knowledge show 123 --json --fresh        # la fila entera, y si construirla hoy diría lo mismo
```

`audit` solo lee y **termina con código 1** si falla un criterio: menos de 95 % de los partidos terminados de las competiciones seguidas con
una construcción; una fila guardada cuyo `content_hash` no es el hash de sus propias capas; una fila al día (sus entradas son las que leyó)
que construirla hoy diría distinto (**cambió una regla y no su versión**); líneas de eventos rancias. Además cuenta los partidos
construidos más de cinco veces (`flapping`): son los que tienen entradas que no paran de cambiar.

**API** (`GET /api/v1/matches/{fixture_id}/knowledge`, `fbi.api.routers.knowledge`): solo lee; ninguna ruta construye una fila, llama al
proveedor ni puede cambiar un pick. Un **usuario** ve las capas de HECHOS (resultado, estadísticas de los equipos, eventos, jugadores,
táctica e historia del marcador, mercado de la apertura al cierre) **solo si el dueño enciende `FBI_KNOWLEDGE_USERS=1`** (hay que
reiniciar la API); hasta entonces contesta «no disponible». Del mercado, un usuario recibe **lo que el mercado creía** (las probabilidades
sin margen, de la apertura al cierre) **y nunca lo que habría pagado una apuesta**: los últimos precios del proveedor (`MarketBlock.final`)
van vacíos en su respuesta y solo los lleva la vista previa (la misma regla del pronóstico, que no da cuotas a un usuario). Cada capa
pasa por un modelo de `fbi.api.contracts.knowledge` que **nombra
cada campo que un usuario puede ver**, de modo que un campo que el constructor añada mañana no llega a su vista hasta que alguien lo
añada al modelo. Con `?preview=shadow` (solo SUPER_ADMIN; otro rol recibe 403) se ve haya o no interruptor, con la fila tal como está
guardada (las nueve capas, incluidos los picks, los post-mortems y el contexto), las fuentes y la cadena de reconstrucciones
(`MatchKnowledge.stored`): lo que PrediGol sabe de cómo se juzgó a sí mismo **nunca es de un usuario**. Cuando no hay objeto dice por qué,
con un código estable y en este orden: `not_finished`, `not_followed`, `not_settled_yet`, `no_build_yet`.

**Web** (`web/src/product/match/KnowledgeBlock.tsx`): bloque «Postpartido» en el Resumen de un partido terminado. Mientras carga, falla o
no está disponible, un usuario no ve nada (ni un hueco); el administrador con «Modo de evaluación» ve todos los estados y la insignia
MODO EVALUACIÓN. Catálogos ES/EN con una prueba de paridad.

## 8. Aislamiento: quién puede leerlo

`tests/unit/test_knowledge_isolation.py` guarda cuatro puertas (la misma lógica que `test_forecast_isolation.py` y
`test_context_isolation.py`, con una lista cerrada que se amplía con una razón escrita):

1. **Solo los archivos listados nombran las tablas** (`match_knowledge`, `fixture_event_kinds`) o importan los módulos: el paquete
   `fbi.knowledge`, el trabajo, la página (servicio, router y contrato), el planificador del worker, el vigilante y la herramienta. Un
   archivo nuevo que las nombre rompe la prueba hasta que alguien decida, y escriba por qué, que puede.
2. **Nada que arma o juzga una vista de antes del partido puede nombrarlas ni importarlas**: los paquetes de modelos
   (`models`, `features`, `predictions`, `backtesting`, `domain`) y `forecasting`, `picks`, `parlays`, `market`, `odds`, `datasets`,
   `validation`, `research`, `analyst`, `notify`, `competitions`, `people`, `catalog`, y los archivos de `intel/` y de `ai/` que
   construyen o revisan un paquete, una decisión, una puntuación, una apuesta, una calibración, el dossier o la narrativa. Una comprobación
   de cordura exige que esa lista cubra más de 100 archivos, para que un cambio de nombre no la vacíe en silencio.
3. **El paquete no importa nada nuestro salvo `fbi.people.sides`**, el constructor escribe **exactamente** sus dos tablas
   (`{intel.match_knowledge, core.fixture_event_kinds}`) y ningún hecho de un partido, y el trabajo solo toca el libro y el paquete.
4. **La página no escribe nada** y solo importa `fbi.api`, `fbi.core`, `fbi.auth` y `fbi.knowledge.layers`.

Verificado con mutaciones (12 de 12 detectadas): añadir una lectura en la capa de decisión, un `UPDATE` en la página, una importación del
constructor desde la API, etc., rompen la prueba. Solo 0089 y 0090 pueden nombrar las tablas entre las migraciones (una vista, una función
o una clave sobre ellas sería otra puerta).

**No hay una regla `knowledge_known` en la auditoría nocturna de fuga** (`leak-audit`) porque no hay ningún camino de Match Knowledge a un
paquete de la IA. Se añadirá cuando F8 deje que un bloque de antes del partido lo cite: entonces la regla comprobará que lo citado existe
en `intel.match_knowledge`, no es de después del momento del paquete y es de un partido que ya había terminado entonces.

## 9. Cómo cambiar una regla o añadir una capa

* **Cambiar una regla de los eventos o de las capas** = subir la versión (`events-v2` en `fbi/knowledge/events.py`, `mk-v2` en
  `layers.py`) **y** actualizar `RULES`. La versión entra en la huella: al pase siguiente (el barrido de las 10:30 UTC no tiene tope por
  corrida; o `build --days 400 --apply`) cada partido tocado recibe una fila nueva. Con `events-v2` bajo `mk-v1` la fila nueva reemplaza a la
  anterior en la misma cadena; con `mk-v2` las filas `mk-v1` se quedan al lado. Una regla cambiada sin cambiar su versión la delata
  `audit` («una fila al día que construirla hoy diría distinto») y `show --fresh`.
* **Añadir un campo a una capa**: cambia el contenido, así que es una regla nueva (versión). Si el campo es para el usuario, hay que
  añadirlo también a su modelo en `fbi.api.contracts.knowledge` (y a `web/src/lib/api/v1/types_knowledge.ts`, el espejo escrito a mano):
  hasta entonces no llega a su vista.
* **Añadir una columna que se lee** (una tabla de hechos nueva, una columna nueva): va en la lista `*_FACTS` o `*_MOMENTS` que
  corresponda; así queda en la huella (o fuera de ella, si es un momento) sin que nadie pueda olvidarlo.
* **Dejar que un lector nuevo lea Match Knowledge**: agregarlo a `NAMES_IT` o a `IMPORTS` en la prueba de aislamiento, con la razón. Si es
  un lector de antes del partido, **la respuesta es no** (puerta 2): lo que un partido terminado resultó ser no puede servir para decir
  algo de otro antes de que se juegue, salvo por la memoria de F8, que tiene su propia regla de «a fecha».
* **Código fuera de los paquetes de modelos.** El código de F7 vive fuera de `MODEL_PACKAGES = ("models", "features", "predictions",
  "backtesting", "domain")`: un cambio dentro de ellos es, por la regla del 5 de octubre, un modelo nuevo, y la huella del código de
  modelos (`mc9a7bec97ca`) cambiaría. Una prueba fija esa huella y una puerta de aislamiento comprueba que `fbi.knowledge` no esté en ese
  conjunto.
* **Arquitectura.** La prueba de ciclos de importación (`tests/unit/test_architecture.py`) fija que el ciclo mayor tenga como mucho 8
  módulos y que solo `api`, `analyst` y `picks` importen `fbi.api`. El trabajo vive en `fbi.ingestion` (no en `fbi.knowledge`) porque el
  libro de corridas es de la ingesta y el paquete se queda por debajo de ella.

## 10. Medidas (producción, solo lectura, 23 oct 2026)

Ensayo en seco sobre **todos** los partidos candidatos de los últimos 400 días (38.121, todos de competiciones seguidas), con la sesión de
la base en solo lectura: ver el detalle y las cifras por mes en `docs/owner/POSTPARTIDO_F7.md`. Lo que importa para quien mantenga el
código:

| Medida | Resultado |
|---|---|
| Partidos leídos y armados | **38.121 de 38.121, 0 fallos**; las páginas de la API leen las 38.121 filas con sus modelos sin un error |
| Determinismo | reconstruir con las mismas entradas dio otro `content_hash` en **0** partidos; las 38.121 huellas son distintas entre sí y no cambian con otra zona horaria ni otro formato de fecha de la sesión |
| Costo | huellas: 41 s en total (1,1 ms por partido); lectura: 3,2 ms por partido de media (p99 15,9); construcción: 0,93 ms (p99 2,7) |
| Peso de una fila | 2.978 bytes de JSON de media (p99 5.095, máx. 7.055), unos 1.190 comprimidos; las 38.121 filas, **113,5 MB en texto, ~45 MB comprimidas** (el tamaño real en disco se mide tras la carga) |
| Líneas de eventos | 505.302 líneas de las 38.121 construcciones, ninguna de tipo `other` ni `card_unknown` |
| Completitud | `complete` 23.174 (60,8 %), `partial` 11.559 (30,3 %), `minimal` 3.388 (8,9 %) |
