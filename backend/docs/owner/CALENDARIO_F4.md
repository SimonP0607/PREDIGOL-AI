# Calendario global del equipo: cuánto descansó cada equipo, contado con TODOS sus partidos (Plan Maestro, fase F4)

**Qué es.** PrediGol solo guarda los partidos de las competiciones que sigue. Un equipo juega más que eso: una eliminatoria de copa, una noche
de Champions, un amistoso. Hasta hoy, el «descanso» y la «congestión» que veían los modelos, la IA y la página de un partido salían solo de lo
guardado: un equipo que jugó la copa hace dos días «descansaba ocho» si su último partido de liga fue hace ocho. Eran **cotas**: el descanso real,
como mucho el anotado; los partidos reales, como mínimo los anotados. F4 le da al sistema el **calendario completo de cada equipo** y dice, cada
vez, **qué tan seguro está de que está completo**.

| | Antes de F4 | Con F4 |
|---|---|---|
| Qué cuenta el descanso | partidos de las competiciones que PrediGol sigue | todos los partidos que el proveedor lista para el equipo (copa, continental, amistosos) |
| Qué sabía la IA | «descanso ≥ lo anotado», con una advertencia | el descanso real **cuando el calendario del equipo está completo**; si no, sigue siendo una cota y lo dice |
| Qué ve el usuario | nada de calendario | **nada hasta que tú lo decidas** (`FBI_CALENDAR_USERS`); tú, en la vista previa de administrador, ya: «Jugó hace 2 días (Copa) · juega en 3 días (Champions)» |
| Qué ven los modelos y los picks | su descanso de siempre | **exactamente lo mismo**: F4 no cambia ningún modelo, Elo, calibrador, regla de valor, pick ni liquidación |

**F4 no cambia ningún modelo ni ningún pick.** Los partidos de competiciones que PrediGol no sigue viven en tablas propias que ningún modelo lee
(una prueba lo impide por construcción, abajo); el descanso «real» para modelos solo existe como **experimento** con un veredicto fijado de antemano
(F4.4) y pasar a producción pide la puerta completa de F10/F14 y tu decisión.

## Qué escribe (y qué no)

Una migración, solo aditiva (**0087**): dos tablas y dos vistas. Nada existente se altera.

| Objeto | Para qué |
|---|---|
| `core.calendar_matches` | Una fila por (partido del proveedor, `observed_at`), **solo cuando algo cambió** (se reprograma, se juega, cambia el marcador). «Qué sabíamos del calendario a la hora T» es la fila más reciente con `observed_at ≤ T`. Guarda solo los partidos que `core.fixtures` **no** tiene. |
| `core.calendar_fetches` | El registro de las preguntas: cuándo se leyó por última vez la lista de cada equipo y temporada, cuántos partidos dio y cuántos ya seguía PrediGol. Un calendario es tan completo como su última lectura. |
| `core.calendar_matches_latest` | Vista: la fila más reciente de cada partido (y cuándo se vio por primera vez). |
| `core.team_calendar` | Vista: por equipo, los partidos de las dos fuentes juntos (`source` = `followed` o `calendar`). |

Cada fila nombra el RAW que la dijo; son tablas **derivadas**: perderlas no pierde nada que no se pueda volver a leer. **No se crea ninguna
competición, temporada, equipo ni partido en `core.*` para una competición que PrediGol no sigue**: el rival de un partido así es un nombre y un
identificador del proveedor dentro de la fila del calendario, nada más.

## De dónde sale: una petición por equipo y temporada

La lectura la hace el job que ya existe para los datos de referencia (`reference_refresh`, cada 30 min), como un feed más (`team_fixtures`) que
comparte el cupo diario, la reserva para el vivo y el registro de cada petición. La petición es `GET /fixtures?team=<id>&season=<año>`: el proveedor
devuelve **toda la temporada del equipo** (jugados y por jugar) en una sola respuesta.

**A quién se le pregunta, y cada cuánto.** Solo a los equipos con un partido de una competición seguida en los próximos 7 días, una vez por
temporada en la que juegan: cada ~20 h si su próximo partido es en ≤ 2 días (una copa a media semana es de lo que depende su descanso), cada ~44 h
si es en ≤ 4 días y cada 7 días si es en ≤ 7. Un equipo sin partido en los próximos 7 días no se pregunta: su calendario se lee cuando se acerca su
siguiente partido. Un tope de 60 equipos por pasada de 30 min acota el gasto en el peor caso.

| Medida (22 oct 2026, producción, solo lectura) | Cifra |
|---|---|
| Partidos guardados en `core.fixtures`, todos de competiciones seguidas | 246.017 |
| Pares (equipo, temporada) con un partido seguido en los próximos 7 días | 1.509 |
| Peticiones por día una vez leídos todos (régimen estable) | ≈ **1.085** |
| Máximo posible por el tope por pasada (60 × 48 pasadas) | 2.880 |
| Tope diario configurado | 60.000 |
| Lo más que se gastó en un día de la última semana | 22.395 |
| La primera lectura de los 1.509 pares | 26 pasadas de 30 min ≈ 13 horas |

**Atención a la cifra del plan.** El plan estimó **≈ 300–450 llamadas diarias**. Medido, son **≈ 1.085**: unas 2,4–3,6 veces más, porque la
cadencia diaria de los equipos con partido en ≤ 2 días pesa más de lo que se supuso. Sigue siendo el 1,8 % del tope diario, y el reparto justo del
feed (cada feed con algo pendiente recibe una parte antes de que otro gaste más) y la reserva para el vivo protegen lo demás; pero **la decisión del
cupo es tuya** (abajo).

## Cuándo un calendario es «completo»

Un calendario no se da por completo sin pruebas. Para un partido, el calendario de **un equipo** es completo cuando:

1. su lista se leyó **como mucho 96 horas antes** del momento en que se pregunta (un equipo juega como mucho cada ~3 días), y
2. **ningún partido de las dos últimas semanas sigue marcado «por jugar»** pasado su inicio en la lista (se jugó o se movió y la lista no se ha
   enterado). Los partidos seguidos no se dudan: los mantiene al día el pipeline en vivo.

Si no se cumple, el calendario es **parcial** y se dice por qué: `never_fetched` (nunca leído), `stale` (leído hace demasiado) o
`unconfirmed_match` (un partido sin confirmar). Entonces el descanso es **como máximo** lo que se muestra y los partidos **como mínimo**: lo mismo
que hacía la IA para todos los equipos hasta hoy. Para un partido, «los dos calendarios completos» es lo único que deja afirmar que un equipo llega
con más o menos descanso que el rival.

## Qué ve cada quien

**La IA (`packet-v7`).** El bloque `schedule` del paquete lleva, por equipo: días desde su último partido **en cualquier competición**, partidos
en 7/14/30 días, cuántos de las dos últimas semanas fueron en competiciones que PrediGol no sigue, los últimos partidos y los próximos (con su
competición y si PrediGol la sigue), y un bloque `calendar` que dice si la lista es completa y por qué no. **No lleva resultados ni rivales**: son
datos del pasado que la IA ya tiene en `form` para lo seguido, y el paquete no se vuelve una vía para colar información. Las banderas de
descanso («llega con 2 días menos») solo se afirman si **los dos** calendarios son completos; si no, se dicen como cotas. Un calendario que no
se puede leer se anota como `schedule` en `missing` y no cuesta nada más del paquete.

**La auditoría de fuga (`leak-audit-v5`, regla `calendar_known`).** La auditoría nocturna comprueba que el paquete **no leyó el futuro**: cada
lectura citada existía a esa hora, no había una más nueva con más de un minuto de antelación, una lista «completa» no tenía más de 96 horas, y
cada partido citado existía a esa hora con el mismo inicio (un partido seguido grabado después, o un anuncio posterior, es una violación).

**La API (`GET /matches/{id}/calendar`).** Por equipo: `rest_days`, partidos en 7/14/30 días, `outside_last_14d`, los últimos 5 partidos
(competición, tipo, rival, resultado desde el lado del equipo —sí se puede decir en la página: son hechos del pasado, mostrados a una persona— y
si PrediGol la sigue) y los próximos 3 de la semana siguiente; más `complete` y `scope`: `provider_calendar` si los dos lados son completos y
`tracked_competitions` si al menos uno es solo lo que PrediGol sigue. Un usuario recibe «no disponible» con la razón hasta que tú lo decidas; la
vista previa de administrador (`?preview=shadow`, solo SUPER_ADMIN) lo ve siempre.

**La web (bloque «Calendario y descanso» del Resumen del partido).** Muestra por equipo «Descanso», «Últimos 14 días» (con «N en competiciones
que PrediGol no sigue»), «Jugó antes» y «Juega después», con la marca **Completo / Parcial**. En un calendario parcial dice, por equipo, lo que
falta («PrediGol todavía no ha leído el calendario completo de X: su descanso podría ser menor y haber más partidos de los que se muestran») y
usa «como máximo» y «al menos». Es contexto, no una recomendación: cuenta días y partidos, no dice quién va a ganar. Hoy solo lo ven los
administradores con el modo de evaluación.

## Experimentos: descanso y congestión REALES para los modelos (F4.4, solo experimentos)

La familia de regresión logística multinomial ya lee el descanso de los dos equipos, pero contado solo con partidos seguidos. ¿Mejora si lee el
real? Eso **se mide, no se supone**, con un protocolo escrito antes de ver ningún resultado:

* **Definiciones (`rest-v1`, `fbi.research.rest_features`).** Por lado y partido: descanso real, descanso solo con lo seguido, descanso desde el
  último partido fuera de lo seguido, partidos en 7/14/30 días, los de las dos últimas semanas fuera de lo seguido y el siguiente partido.
  El calendario de un partido ya jugado es *completo* si su lista se leyó **después** del partido, no quedó sin confirmar ningún partido de las dos
  semanas anteriores y hay un partido anterior en los sesenta días previos.
* **Prueba (`rest-ab-v1`, `fbi.research.rest_ab`).** El mismo modelo de producción con sus ocho entradas, con la del descanso sustituida por la
  **más corta** entre la de producción y la del último partido fuera de lo seguido (el calendario solo puede *acortar* un descanso), ajustado
  por quincenas hacia delante (*walk-forward*), con pérdida logarítmica y un intervalo del 95 % por *bootstrap* sobre días de partidos.
  El veredicto es aritmético: **`promising`** (el intervalo entero por debajo de cero y una mejora ≥ 0,0005 por partido), **`harmful`** (entero por
  encima) o **`inconclusive`** (cualquier otro caso, y siempre con menos de 2.000 partidos de prueba). Se informa también del modelo sin descanso,
  del que añade la carga de la quincena y de lo que el calendario cambia en el descanso antes de entrenar nada.
* **`promising` no promueve nada.** Dice que merece la pena la puerta completa de F10/F14 (varias familias y mercados, calibración, precios) y tu
  decisión.

```bash
python -m scripts.calendar_features coverage                       # cuántos partidos de la semana próxima tienen calendario completo en los dos lados, y qué cambia en el descanso de los jugados
python -m scripts.calendar_features coverage --days 3 --since 2026-10-01
python -m scripts.calendar_features export --since 2026-10-01 --out calendario.csv   # una fila por partido jugado con el calendario completo de los dos lados
python -m scripts.calendar_features compare --since 2026-09-01 --out rest_ab.json    # la prueba (solo lectura)
```

**Cuándo tendrá sentido correrla.** La muestra son los partidos jugados cuyos dos equipos se leyeron *después* del partido, de la temporada en
curso: crece con cada día de lecturas. Un descanso es un efecto pequeño: con unos miles de partidos solo se ve una mejora de ~0,001 *nats* por
partido, y por eso la prueba dice `inconclusive` («aún no hay evidencia») hasta tener ≥ 2.000 partidos de prueba. Mi sugerencia es mirar
`coverage` a las dos semanas y correr `compare` cuando `coverage` muestre varios miles de partidos en la muestra.

## Reglas que se respetan

* **Ningún modelo, Elo, calibrador, regla de valor, pick, liquidación ni backtest lee estas tablas.** Lo prueba `test_calendar_isolation.py`
  con seis comprobaciones: solo los archivos listados nombran las tablas o importan el lector; solo el feed escribe; nada de `models`,
  `predictions`, `picks`, `domain`, `backtesting`, `intel` (salvo la auditoría de fuga), `parlays`, `market`, `odds` ni `datasets` las nombra
  o importa el lector; el motor de *features* y el Elo no mencionan el calendario; y solo el comando de experimentos importa las funciones de
  descanso real. Un lector nuevo rompe la prueba hasta que alguien decida, por escrito, que puede leer.
* **Lo que se sabía en ese momento.** El lector lee «a la hora T»: un partido jugado antes de T es un hecho se grabara cuando se grabara; un
  partido por jugar debe haberse **grabado** antes de T; una lista es tan completa como su última lectura antes de T.
* **Un calendario que no se pudo leer no cuesta el resto del paquete** (punto de guardado propio) y el feed se puede pausar sin desplegar.

## Cómo corre

* **Worker:** el feed `team_fixtures` dentro de `reference_refresh` (cada 30 min, tope de 60 equipos por pasada). Se pausa **sin desplegar** con
  `FBI_TEAM_CALENDAR=0` en `/etc/predigol/app.env` y reiniciando el worker; lo leído se queda.
* **API:** `FBI_CALENDAR_USERS=1` lo enseña a todos los usuarios (necesita reiniciar la API); apagado es el valor de fábrica.
* **A mano:** `python -m scripts.calendar_features …` (arriba). No hay un comando que pregunte al proveedor: el feed es el único que lo hace.

## Lo que se midió antes de estrenar

Producción, solo lectura, 22 oct 2026: las cifras de la tabla de arriba (246.017 partidos guardados, 1.509 pares, ≈ 1.085 peticiones por día,
tope 60.000, máximo reciente 22.395). Lo que **no** se puede medir sin estrenar, y se mide en la primera semana: cuántos partidos de la
semana tienen calendario completo en los dos lados, cuántos partidos no seguidos aparecen por equipo (el modelo del plan decía «1 por equipo y
semana»), el tamaño de las dos tablas y el reparto de motivos de «parcial».

## Resultado de la prueba general

Pasada el 23 oct 2026 sobre la rama `plan/f4` (encima de F5), antes de preparar el paquete. Nada de esto toca producción.

| Comprobación | Resultado |
|---|---|
| `ruff check` | sin errores |
| `mypy` estricto sobre `src/fbi` (405 archivos) y sobre todo el árbol, pruebas y scripts incluidos (908) | sin errores |
| `pytest` del backend completo, con PostgreSQL | **3.656 pasan**, 4 se saltan (necesitan datos fuente que no existen en el entorno local y ya se saltaban antes), 0 fallan; 104 pruebas más que al cerrar F5 |
| Web: `lint`, `typecheck`, `bun test src` | 0 errores (26 avisos que ya existían), tipos sin errores, **421 pruebas pasan** (28 más que al cerrar F5) |
| Web: compilación de producción (`NITRO_PRESET=node-server VITE_DATA_MODE=live`) | correcta |
| Migración 0087 | sube y baja sola dejando la base como estaba (`test_0087_adds_two_tables_and_two_views_and_nothing_else_and_comes_back_out`, la prueba de que todas las migraciones son reversibles y el ensayo de cadena completa) |
| Aislamiento del calendario | las seis comprobaciones de `test_calendar_isolation.py`: ningún modelo, Elo, calibrador, regla de valor, pick, liquidación ni backtest lee las tablas |
| Auditoría de fuga `leak-audit-v5` (regla `calendar_known`) | 19 pruebas, incluidas las que escriben a mano paquetes que leen el futuro y deben ser violaciones |

Lo único que esta prueba no puede decir es cómo se comporta el proveedor con `fixtures?team=&season=` en producción (forma exacta de la respuesta, tiempo
por petición, partidos de competiciones raras): eso se valida con 1–3 peticiones reales antes de dejar correr el feed (paso 3 de «Cómo estrenarlo»).

## Verificación de los criterios del plan

| Criterio de «hecho» | Resultado | Prueba |
|---|---|---|
| Los partidos fuera de lo seguido nunca entran a modelos de goles ni a picks | sí, por construcción (tablas aparte) y por prueba | `test_nothing_that_trains_predicts_decides_or_settles_names_or_imports_the_calendar`, `test_the_feature_engine_the_elo_and_the_backtests_do_not_see_it_either`, `test_only_the_listed_files_name_the_tables` |
| El descanso cambia correctamente con un partido de copa no seguida | sí | `test_a_cup_tie_the_platform_does_not_follow_changes_the_rest_of_a_team_whose_list_is_whole`, `test_the_real_rest_of_a_finished_match_is_what_the_cup_tie_leaves_not_what_the_league_alone_says` |
| El calendario sabe lo que se sabía en cada momento | sí | `test_the_reader_knows_only_what_was_known_at_the_moment`, `test_a_list_read_after_the_moment_is_not_known_at_it_but_a_match_already_played_is_a_fact` |
| Un equipo sin lectura reciente no se da por completo y se dice | sí | `test_a_side_whose_list_was_never_read_keeps_the_bounds_of_before`, `test_a_list_is_as_fresh_as_its_last_reading_at_the_moment`, `test_a_match_the_list_has_not_confirmed_makes_the_calendar_doubtful` |
| Se cambia solo lo que cambia (sin latido) y cada pregunta queda registrada | sí | `test_a_reading_that_says_nothing_new_adds_no_match_row_but_is_logged`, `test_a_match_that_moves_or_is_played_is_a_new_row_and_the_first_sighting_is_kept` |
| La migración se deshace sola y no toca nada más | sí | `test_0087_adds_two_tables_and_two_views_and_nothing_else_and_comes_back_out` |
| La IA lo cita sin colar resultados y el paquete no leyó el futuro | sí: la auditoría nocturna lo comprueba (19 pruebas) | `test_the_calendar_names_the_competition_and_nothing_that_could_leak_a_result`, `test_calendar_leak_audit.py` |
| Un usuario no ve nada hasta que se decide; el administrador sí en la vista previa | sí | `test_a_user_gets_nothing_until_the_owner_decides_and_then_the_calendar_of_each_side`, `test_the_admin_preview_sees_it_whether_or_not_users_do` |
| Quién se pregunta y cada cuánto, y el feed se puede pausar | sí | `test_who_is_asked_about_and_how_often`, `test_the_feed_can_be_paused_without_a_deploy` |
| Los experimentos están preregistrados y no pueden promover nada | sí | `test_rest_ab.py`, `test_rest_features.py`, `test_calendar_features_cli.py`, `test_only_the_experiments_command_imports_the_rest_features` |

## Lo que se decidió distinto del plan (y los límites que conviene conocer)

* **Tablas aparte, no una marca `calendar_only` en `fixtures`.** El plan decía «1 columna + 1 vista». Un partido de una competición no seguida
  necesitaría una competición, una temporada y, para el rival, un equipo en `core`, y cada consulta de `core.fixtures` (Elo, *features*,
  *backtests*, picks, liquidación) tendría que aprender a dejarlo fuera: bastaría olvidar un filtro para que contaminara un modelo. Con tablas
  propias es imposible por construcción. El resultado que pedía el plan (un calendario con todos los partidos del equipo) es el mismo; cambia el
  mecanismo: **2 tablas + 2 vistas en lugar de 1 columna + 1 vista.**
* **Un endpoint propio (`/matches/{id}/calendar`) en vez de añadirlo a `/center`.** Así el calendario tiene su interruptor, su vista previa y sus
  estados («no disponible» con razón) sin tocar el contrato del centro del partido.
* **El gasto de API es ≈ 1.085 peticiones por día, no 300–450** (arriba). Es el 1,8 % del tope diario y se puede pausar sin desplegar, pero es
  tu cupo: decídelo.
* **Solo las temporadas en curso.** El feed pregunta por la temporada actual de cada equipo; los partidos de la temporada anterior cerca del
  cambio de temporada (p. ej. una liga de año natural en enero o febrero, con partidos de diciembre) no se leen, mientras el calendario puede
  seguir diciendo «completo». Es una cota conocida: afecta a los primeros partidos de una temporada, y la prueba de F4.4 descarta los primeros
  partidos sin un anterior en los sesenta días previos.
* **No hay calendarios retroactivos.** Las tablas empiezan el día del despliegue (la primera lectura de cada equipo trae la temporada entera,
  pasada incluida); lo que PrediGol «habría sabido» el mes pasado es una pregunta de *backtest* (F10/F14), no un dato que se invente aquí.
* **Los viajes no entran.** El plan los menciona; hacen falta coordenadas de estadios y de equipos y su calidad no se ha medido. F4.4 se limita
  a descanso, congestión y prioridad (próxima competición).
* **El «descanso» de un partido no jugado es un máximo.** Si el proveedor aún lo marca «por jugar» pasado su inicio, no cuenta como descanso hasta
  que se confirme, y el calendario deja de ser completo.

## Cómo estrenarlo en producción (y qué te aviso antes de cada paso)

1. Copia verificada y **prueba de restauración** antes de migrar (0087 son dos tablas nuevas y dos vistas; sus claves foráneas piden un bloqueo
   corto sobre `raw.ingestion_payloads`). **Se migra en un momento tranquilo**: el job `fixtures_sync` (cada 6 h) mantiene hasta ~27 minutos una
   transacción abierta sobre varias tablas, y una migración que pida un bloqueo sobre ellas esperaría; el paso de despliegue lo comprueba antes
   de empezar.
2. `predigolctl deploy`: respaldo propio del despliegue, migración, permisos, reinicio y salud. Con las tablas vacías todo se comporta como antes.
3. La primera pasada del job de referencia empieza a leer calendarios (60 por pasada). Antes de dejarlo correr se **valida con 1–3 peticiones
   reales** que la respuesta de `fixtures?team=&season=` es la esperada, y se mide el gasto real frente a la estimación.
4. A las pocas horas se mira `coverage` (cuántos partidos de la semana tienen calendario completo) y en el Resumen de un partido con el «Modo
   de evaluación» encendido, el bloque «Calendario y descanso».
5. Se vigila (abajo) y se anota aquí el «Resultado en producción».

## Cómo deshacerlo

* **Dejar de leer calendarios:** `FBI_TEAM_CALENDAR=0` y reiniciar el worker. Lo leído se queda; el paquete y la página siguen diciendo lo que
  saben y de cuándo.
* **Ocultarlo a los usuarios:** `FBI_CALENDAR_USERS=0` (valor de fábrica) y reiniciar la API.
* **Quitarlo todo:** `predigolctl rollback` a la versión anterior del código y `alembic downgrade 0086`, que borra las dos tablas y las dos
  vistas. Lo único que se pierde es lo leído del proveedor (se puede volver a leer), así que antes se hace la copia de despliegue habitual.
  `packet-v6` y `leak-audit-v4` vuelven con el código; los paquetes ya escritos solo se añaden y no se tocan.

## Lo que decides tú

* **El cupo diario de API-Football.** El plan decía ≈ 300–450 peticiones diarias; medido son ≈ 1.085 una vez leídos todos los equipos (el 1,8 %
  del tope configurado de 60.000, con la reserva del vivo protegida). Hasta que lo confirmes, el feed se limita —como pediste— a los equipos con
  un partido en los próximos 7 días. Si prefieres menos, la lectura se puede espaciar (por ejemplo, semanal para todos) o pausar.
* **¿Los usuarios ven el calendario?** Es contexto, no una recomendación, pero lo muestra un administrador hasta que tú decidas.
  Opciones: (a) **no, por ahora** (lo que queda al desplegar), (b) **sí, tal como está** (con «Parcial» donde corresponda). Mi sugerencia: (a)
  una semana, mirando `coverage` y el reparto de motivos de «parcial», y decidir con datos.
* **¿Se corre el experimento de descanso real?** Cuando haya muestra suficiente; el resultado solo dice si merece la puerta completa.
* Nada más de F4 pide una decisión tuya.

## Lo que queda vigilado tras desplegar

1. El gasto real del feed frente a la estimación (peticiones del job de referencia por día, en `raw.ingestion_runs` y `api_calls`); el tope por
   pasada y la reserva del vivo se respetan.
2. `scripts.calendar_features coverage`: la parte de partidos de la semana con calendario completo en los dos lados y el reparto de motivos de
   «parcial» (`never_fetched` debe bajar a casi cero en ~13 horas; `unconfirmed_match` indica partidos que la lista no confirmó).
3. El tamaño de `core.calendar_matches` la primera semana y que el número de filas nuevas por lectura se estabiliza (solo cambios).
4. La auditoría nocturna de fuga con `calendar_known`: `checked` sube con los paquetes que citan el calendario y `violations` queda en 0.
5. Que el job de referencia no registre errores del feed (`team_fixtures` en las notas de la corrida) y que el resto de feeds siga recibiendo su
   parte.
