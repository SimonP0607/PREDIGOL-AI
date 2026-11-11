# IA-042 — Lo que API-Football ya entrega: bajas, sanciones, historial de bajas, entrenadores y alineaciones por liga

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-B05, ola 1. Medido el 11-nov-2026 en producción, solo lectura.*

## Qué se midió

1. **Indicadores de cobertura del proveedor.**
   - Se hizo **una** llamada a `/leagues?current=true`, dentro de `predigol-worker`, con el cliente del propio código (`ApiFootballClient`).
   - Se usaron `persist=False`, cuota y limitador en memoria, y no se escribió nada en la base de datos ni en el RAW. No se imprimieron la clave ni las cabeceras.
   - Respondió HTTP 200 a las 04:57:33 UTC, con 1.244 ligas y su temporada actual.
   - Se leyeron los indicadores `injuries`, `lineups`, `statistics_fixtures`, `statistics_players`, `odds` y `predictions`.
   - Se compararon con los que PrediGol ya guarda en `raw.league_coverage`.
2. **Lo que PrediGol guarda.** 3.368 partidos terminados, con saque entre el 12-oct y el 10-nov-2026.
   - **Bajas.** Historial de respuestas de `/injuries` en `core.player_availability_obs` (cambios LISTED/CLEARED con `observed_at`). Se toma lo que se sabía en el momento del saque y la antelación con que PrediGol vio cada baja por primera vez. También se miró la tabla «última respuesta» `core.player_absences`.
   - **Alineaciones.** Las guardadas (`core.fixture_lineups` y sus jugadores). La hora en que se vieron por primera vez completas antes del saque sale de leer los RAW de `/fixtures?ids` (2.717 ficheros, solo lectura).
   - **Juez de las noticias.** Precisión: ¿juega de titular quien el proveedor da como baja? Aproximación a la sensibilidad: ¿estaban en la lista los titulares del partido anterior que ni siquiera van convocados?
3. **`/sidelined` y `/coachs`.** Si se piden (`core.reference_checks`), qué se guarda (`core.person_sidelined`, `core.coach_profiles`, `core.coach_careers`) y para qué sirve hoy.

## Resultados

### 1. Lo que dice el proveedor (`/leagues?current=true`)

**Sobre las 1.244 ligas.**

| Indicador | Ligas en `true` |
| --- | ---: |
| `predictions` | 1.244 |
| `events` | 1.023 |
| `lineups` | 758 |
| `standings` | 742 |
| `players` | 492 |
| `odds` | 416 |
| `statistics_fixtures` | 151 |
| `statistics_players` | 129 |
| **`injuries`** | **23** |

**Las 23 con `injuries`:**

- Ligas europeas: Premier League, Championship, LaLiga, Serie A, Bundesliga, Ligue 1, Eredivisie, Süper Lig, Rusia, Allsvenskan, Eliteserien y Superliga danesa.
- Copas UEFA: Champions y Europa League.
- Fuera de Europa: Brasileirão, MLS y A-League.
- Selecciones: Mundial, eliminatorias de Europa y de CONCACAF, Eurocopa femenina, Sub-21 de la UEFA (clasificación) y Copa Asiática Sub-23 (clasificación).

**En las 104 ligas y temporadas con partidos en la ventana:**

- `injuries` está en 17, `lineups` en 100, `statistics_players` en 87 y `odds` en 91.
- Los indicadores guardados en `raw.league_coverage` coinciden con la llamada en las 104 (0 diferencias).

### 2. Indicador del proveedor frente a lo observado, por liga prioritaria (30 días)

| Competición | Indicadores del proveedor (bajas / alineaciones / estadísticas de jugador / cuotas) | Partidos | Con alguna baja del proveedor al saque | Antelación de la baja, h (p25 / mediana / p75) | Alineaciones completas guardadas | Alineaciones vistas antes del saque | Antelación de la alineación, min (mediana) |
| --- | --- | ---: | ---: | --- | ---: | ---: | ---: |
| Champions | sí / sí / sí / sí | 54 | 46 (85,2 %) | 4,6 / 46,7 / 55,5 | 54 | 54 | 19,7 |
| Premier League | sí / sí / sí / sí | 41 | 31 (75,6 %) | 39,0 / 48,4 / 67,2 | 41 | 41 | 19,3 |
| LaLiga | sí / sí / sí / sí | 42 | 31 (73,8 %) | 39,2 / 56,0 / 64,0 | 39 | 42 | 19,6 |
| Serie A | sí / sí / sí / sí | 52 | 50 (96,2 %) | 43,7 / 56,5 / 65,2 | 52 | 50 | 19,5 |
| Bundesliga | sí / sí / sí / sí | 36 | 26 (72,2 %) | 38,4 / 43,0 / 55,0 | 36 | 36 | 19,5 |
| Ligue 1 | sí / sí / sí / sí | 36 | 26 (72,2 %) | 51,5 / 59,4 / 61,7 | 35 | 36 | 19,6 |
| Primeira Liga | **no** / sí / sí / sí | 28 | 0 | — | 28 | 28 | 19,4 |
| Europa League | sí / sí / sí / sí | 54 | 49 (90,7 %) | 5,7 / 7,9 / 56,7 | 52 | 54 | 19,7 |
| Conference League | **no** / sí / sí / sí | 54 | 0 | — | 54 | 54 | 19,7 |
| Libertadores | **no** / sí / sí / **no** | 4 | 0 | — | 4 | 4 | 19,7 |
| Sudamericana | **no** / sí / sí / **no** | 4 | 0 | — | 4 | 4 | 20,1 |
| Eliminatorias | Europa y CONCACAF: bajas sí; Sudamérica, África, Asia y Oceanía: no; cuotas no en todas | 0 | — | — | — | — | — |
| Resto (grupo 4) | variable | 2.916 | 302 (10,4 %) | 41,9 / 56,4 / 61,1 | 1.909 | 2.287 | 19,5 |
| **Total** | | 3.368 | 561 (16,7 %) | 38,4 / 55,3 / 60,4 | 2.342 | 2.737 | 19,5 |

**Fuera de las prioritarias, con `injuries` en sí** (partidos con alguna baja / partidos): Championship 53/73, MLS 57/90, Brasileirão 38/43, Allsvenskan 31/42, Süper Lig 28/37, Eredivisie 24/36, Eliteserien 23/33, Rusia 17/32, Superliga danesa 16/25 y A-League 15/23. Colombia (Primera A) tiene `injuries = false`: 55 partidos y 0 bajas.

La tabla completa de las 104 ligas y temporadas está en `lab/IA_042/b05_cobertura_por_liga_20261111.csv`.

**Agregados por indicador.**

- **Bajas.**
  - Con `injuries` en sí: 749 partidos, 561 (74,9 %) con alguna baja al saque.
  - Con `injuries` en no: 2.619 partidos, **0** con alguna baja.
  - La última consulta de bajas de PrediGol devolvió 0 filas en Primeira, Conference, Libertadores y Sudamericana, y entre 946 y 1.500 en las cinco grandes ligas, la Champions y la Europa League.
- **Alineaciones.**
  - Con `lineups` en sí: 3.313 partidos, 2.342 con las dos completas guardadas (70,7 %).
  - Con `lineups` en no: 55 partidos, 0 alineaciones.
- **Cuotas.** El indicador `odds = false` de Libertadores y Sudamericana es falso en la práctica: los 8 partidos tienen cuotas de 10 casas (IA-038).
- **Estadísticas.** Las de jugador (bloque presente y con filas) están en 2.597 partidos (77,1 %; 289/289 en el grupo 1). Las de equipo, en 3.308 (98,2 %).

### 3. Bajas y sanciones: contenido, antelación y fiabilidad

**Contenido, en el saque.** 3.828 bajas (jugador y partido):

- 78,2 % «Missing Fixture» y 21,8 % «Questionable»;
- 180 (4,7 %) con motivo de sanción («Suspended», tarjeta roja o amarillas);
- grupo 1: 1.402 bajas, 41 de ellas sanciones (2,9 %).

**Antelación con que las vio PrediGol.**

- Mediana de 55,3 h antes del saque (p25 38,4, p75 60,4). Un 19,4 % llegó con menos de 24 h.
- En la Europa League (mediana de 7,9 h) y parte de la Champions (p25 de 4,6 h) llegan mucho más tarde.
- Es el momento en que PrediGol las vio. Se consultan cada 4 h si el partido está a menos de 48 h, y cada 12 h si no.

**Bajas que solo aparecen después del saque.** 2.071 (jugador y partido) se vieron por primera vez tras el saque: el **35,1 %** de todas las bajas de esos partidos (grupo 1: 811, el 36,6 %). Parte puede deberse a la cadencia de 4 h.

**Precisión: ¿juega quien figura como baja al saque?** Partidos con alineación.

| | n | Titular | En la convocatoria |
| --- | ---: | ---: | ---: |
| «Missing Fixture», grupo 1 | 1.105 | 6 (0,5 %) | 45 (4,1 %) |
| «Missing Fixture», total | 2.899 | 44 (1,5 %) | 195 (6,7 %) |
| «Questionable», grupo 1 | 275 | 59 (21,5 %) | 182 (66,2 %) |
| «Questionable», total | 809 | 136 (16,8 %) | 424 (52,4 %) |

**Aproximación a la sensibilidad.** Se toman los titulares del partido anterior del mismo equipo en la misma competición (como mucho 14 días antes) que no están ni en el banquillo. De ellos, ¿cuántos daba el proveedor como baja al saque?

| Grupo | Partidos de equipo | Titulares anteriores fuera de la convocatoria | Que el proveedor daba como baja |
| --- | ---: | ---: | ---: |
| Champions, Europa League y las cinco grandes ligas (todas con `injuries`) | 405 | 275 | **155 (56,4 %)** |
| Champions | — | 35 | 22 (62,9 %) |
| Europa League | — | 40 | 26 (65,0 %) |
| Bundesliga | — | 46 | 27 (58,7 %) |
| Ligue 1 | — | 34 | 19 (55,9 %) |
| Serie A | — | 50 | 27 (54,0 %) |
| LaLiga | — | 35 | 18 (51,4 %) |
| Premier League | — | 35 | 16 (45,7 %) |

Es una cota inferior: parte de esos ausentes son descartes técnicos, no bajas.

### 4. Alineaciones

- **Cuándo llegan.** PrediGol las ve completas antes del saque en 2.737 partidos (81,3 %; grupo 1: 287 de 289). La mediana es de **19,5 min antes del saque** (p25 19,2, p75 20,0). Solo el 0,1 % llega 40 min o más antes y el 25 % 20 min o más.
- **Quién las trae.** La lectura prepartido (`prematch_lineups`) en 2.676 casos y el seguimiento en vivo en 61.
- **Por qué es la hora real.** La lectura empieza a preguntar unos 75 min antes (3.278 respuestas guardadas a 70–75 min del saque) y repite cada 10 min. Aun así, solo el 0,1 % de las alineaciones aparece a 40 min o más, y el 75 % a menos de 20. El proveedor las publica, por tanto, en el extremo tardío de los «20–40 min» que documenta (`docs/api-football/01_ENDPOINT_CATALOG.md`). Con preguntas cada 10 min, la hora vista puede ir hasta 10 min por detrás de la publicación.
- **Guardadas completas** (11 titulares por lado): 2.342 partidos (69,5 %; grupo 1: 285, el 98,6 %). En 533 partidos con las dos alineaciones vistas en el RAW, lo guardado no llega a 11 titulares por lado. Hipótesis, sin comprobar: jugadores sin id del proveedor.

### 5. `/sidelined` y `/coachs`: se piden y se guardan; ningún modelo los lee

| Fuente | Peticiones registradas (`core.reference_checks`) | Lo guardado | Quién lo lee hoy |
| --- | --- | --- | --- |
| `/sidelined`, jugadores | 34.273 jugadores; 12.315 con datos; 33.634 consultados en 8 días; 0 errores; desde el 25-oct | `core.person_sidelined`: 48.692 filas, 12.367 personas | Página del jugador (`api/repositories/center.py`) |
| `/sidelined`, entrenadores | 5.227; 52 con datos | (misma tabla) | — |
| `/coachs`, por equipo | 5.751 equipos; 4.398 con datos; desde el 19-oct | `core.coach_profiles` (22.795 filas, 15.578 entrenadores) y `core.coach_careers` (63.803 filas, 15.465) | Centro del partido (foto y ficha), almacén de conocimiento en sombra (`knowledge/store.py`) y enlace de identidad |
| `/coachs`, por id | 4.738; 4.734 con datos | (mismas tablas) | — |

**`/sidelined` frente a `/injuries`.**

- 21.725 titulares distintos en la ventana: el 88,8 % consultado y el 39,7 % con algún periodo de baja.
- Bajas «Missing Fixture» al saque (n = 2.992): el 64,7 % tiene algún periodo en `/sidelined`, pero **solo el 11,5 % tiene uno que cubra la fecha del partido**.
- «Questionable» (n = 836): 74,6 % con algún periodo y 13,3 % con uno que cubra la fecha.

**Entrenadores.**

- **Cambios aparentes.** El id de entrenador de la alineación cambia 1.305 veces en 30 días (2.265 equipos). De esos cambios, 413 vuelven al id anterior en el partido siguiente y 220 tienen el mismo nombre con otro id (por ejemplo, «C. Bucchi» y «Cristian Bucchi»).
- **Cambios reales probables.** Agrupando por apellido y quitando los que vuelven atrás quedan 271 (18 en el grupo 1).
  - `/coachs` da al nuevo entrenador un periodo en ese equipo en 119 de ellos (44 %).
  - Ese periodo empieza en los 30 días previos al partido solo en 17.
  - La foto de la carrera era anterior al partido en 82.

## Conclusiones

1. **Bajas.** El indicador `injuries` acierta del todo y deja la cobertura en 17 de las 104 ligas y temporadas seguidas con partidos en la ventana.
   - **Donde está en sí:** el 75 % de los partidos tiene bajas del proveedor (72–96 % en las cinco grandes ligas, 85 % en la Champions y 91 % en la Europa League), y llegan con unas 55 h de mediana.
   - **Donde está en no:** cero, en 2.619 partidos. Incluye Primeira, Conference, Libertadores, Sudamericana y la Primera A de Colombia.
   - La hipótesis de la ficha («cubren la mayoría de las bajas en las ligas prioritarias») se cumple en las cinco grandes ligas, la Champions y la Europa League, y no en la Primeira, la Conference ni las copas sudamericanas.
2. **«Missing Fixture» es un hecho fiable; «Questionable» casi no informa.**
   - Del primero solo es titular el 0,5 % en el grupo 1.
   - Del segundo es titular el 21,5 % y va convocado el 66 %.
   - Como juez de las noticias, la lista del proveedor es necesaria pero no suficiente: recoge un 56 % (cota inferior) de los titulares habituales que se quedan fuera de la convocatoria.
3. **Las bajas solo valen leídas a la hora de la decisión.**
   - El 35 % de las bajas de un partido aparece por primera vez después del saque.
   - Leer `core.player_absences` (la última respuesta) para decidir o para entrenar sería una fuga; `core.player_availability_obs` con `observed_at ≤ momento` es la lectura correcta.
4. **Las alineaciones del proveedor llegan a unos 20 min del saque, no a 60.**
   - Están en el 99 % del grupo 1 y en el 81 % de todos los partidos, con una mediana de 19,5 min y solo el 0,1 % a 40 min o más.
   - Cualquier punto de control con alineación confirmada tiene que estar a T-20 o después. A T-90 o T-60, el once hay que predecirlo, no leerlo. Esto condiciona E6 (INT-A08) y la verificación de noticias.
5. **`/sidelined` y `/coachs` se piden y se guardan, pero aún no sirven para decidir.**
   - `/sidelined` es historial: solo cubre la fecha del partido para el 11,5 % de las bajas confirmadas, y empezó el 25-oct. Sirve para conocimiento previo en E6, no para saber quién juega.
   - En las alineaciones, el id de entrenador tiene duplicados. Un detector de cambio de entrenador necesita antes resolver la identidad (nombre y `coach_careers`), así que es material de LAB y no un rasgo listo.

**Recomendación concreta, sin coste extra** (todo está ya guardado y no hacen falta peticiones nuevas):

- **E6.** Usar «Missing Fixture» leído a la hora de la decisión como hecho duro solo en las 17 ligas y temporadas con `injuries`. Usar «Questionable» como señal débil. Dejar las alineaciones para el punto de control de T-20.
- **Juez de noticias.** Contrastar cada afirmación con la lista del proveedor a la hora de la decisión y, después, con el once oficial. En las ligas sin `injuries`, las noticias son la única fuente de bajas.
- **Ahorro posible, a medir antes de tocar nada** (es un cambio de código, no para antes del 25-nov): las consultas a `/injuries` de temporadas con `injuries = false` devuelven 0 filas.

## Limitaciones

- **La antelación es la de PrediGol.** Es cuándo vio cada baja o alineación, no cuándo la publicó el proveedor, con la cadencia de 4 h (bajas) y 10 min (alineaciones). Una parte del «35 % después del saque» puede ser cadencia.
- **Historial reciente.** `core.player_availability_obs` existe desde la migración 0078 (principios de octubre). En la ventana conviven algunas filas copiadas de la tabla anterior (`origin = 'snapshot'`) con las respuestas reales.
- **La sensibilidad es una aproximación.** «Titular anterior no convocado» incluye descartes técnicos, y equipos con pocos partidos en 30 días pesan poco. Las cifras por liga tienen n = 34–50.
- **Comparación con `/sidelined`.** Se usó la última foto de cada persona. La alimentación de jugadores empezó el 25-oct, así que no hay historia anterior.
- **Entrenadores.** La agrupación por apellido es una heurística: falla con apellidos compuestos o repetidos. Los 271 cambios no están revisados uno a uno.
- **Muestra.** Libertadores y Sudamericana tienen n = 4. No hubo eliminatorias en la ventana: sus indicadores son los de la temporada actual que da el proveedor (ciclo del Mundial 2026).
- **Alineaciones incompletas.** No se investigaron los 533 partidos con alineación en el RAW pero incompleta en la base.

## Cómo se midió (consultas resumidas)

Todo en solo lectura (`default_transaction_read_only=on`, `statement_timeout=95 s`), con una consulta cada vez. Los cálculos se hicieron en la imagen del backend con `--network none` y con `/tmp/lab_B05` y el RAW (`/srv/predigol/raw`) montados en solo lectura. La carpeta de trabajo se borró al terminar.

1. **Llamada única al proveedor.** Dentro de `predigol-worker`, `ApiFootballClient(settings.api_football, PayloadStore(...)).get("/leagues", {"current": "true"}, persist=False)`. Solo se volcaron a CSV los indicadores de cobertura por liga y temporada.
2. **Población.** `core.fixtures` con `kickoff_at` en [2026-10-12, 2026-11-11) y `status_group = 'finished'` (3.368), unida a competición, temporada y equipos.
3. **Bajas.**
   - `core.player_availability_obs` de esos partidos (7.657 filas) y `core.player_absences` (6.155).
   - Estado al saque: por jugador, la fila más reciente con `observed_at ≤ kickoff_at`, si es LISTED. Primera vez vista: el mínimo `observed_at` LISTED.
   - Consultas de bajas por temporada: `core.context_checks` (`dataset = 'injuries'`).
4. **Indicadores guardados.** `raw.league_coverage` de las 104 ligas y temporadas.
5. **Alineaciones.**
   - Guardadas: `core.fixture_lineups` y `core.fixture_lineup_players`.
   - Bloques de detalle: `core.fixture_detail_coverage`.
   - Respuestas antes del saque: `raw.ingestion_payloads` de `/fixtures` con `params ? 'ids'`, unidos a `raw.ingestion_runs` para el trabajo, desplegando `ids` y quedándose con lo pedido antes del saque y en las 24 h previas (20.849 filas).
   - De esas respuestas se leyeron los RAW de los últimos 150 min (2.717 ficheros, sobre con `body`) buscando el primero con los dos `startXI` de 11 o más.
6. **Juez de noticias.** Cruce del estado al saque con los titulares y convocados. Para la sensibilidad, partido anterior del mismo equipo en la misma temporada de competición, a 14 días como mucho.
7. **`/sidelined` y `/coachs`.**
   - Peticiones: `core.reference_checks`, por feed.
   - Historial: última foto de `core.person_sidelined` de los jugadores de la ventana.
   - Entrenadores: `core.fixture_lineups` desde el 1-ago (id y nombre del entrenador por partido) y última foto de `core.coach_careers`.
   - Uso en el código: `grep` de las tablas en `src/fbi`.

Resultados en bruto guardados junto a este informe: `lab/IA_042/b05_results_20261111.json` y `lab/IA_042/b05_cobertura_por_liga_20261111.csv` (indicadores de la llamada frente a lo observado en las 104 ligas y temporadas).
