# Recuperación tras el apagado del 5–6 oct 2026

Mandato: reanudar todo el sistema tras el periodo offline y recuperar de forma segura lo que no se sincronizó, sin
inventar ni retrofechar nada, marcando lo irrecuperable; reparar inconsistencias antes de seguir ampliando ligas;
`SHADOW` activo y ningún pick publicado.

**Resultado (6 oct 2026):**

* **Ventana offline medida con evidencia**: el equipo se apagó desde el menú Inicio a las **18:38:04 UTC del 5 oct**
  (evento 1074 de Windows) y el apagado no terminó limpio (Kernel-Power 41 y evento 6008 al arrancar). Último dato
  escrito: **18:37:57,242 UTC** (run 10389, captura en vivo). Windows volvió a las **01:12:06 UTC** del 6 oct,
  PostgreSQL a las 01:20:35 y el worker a las **01:34:36,5 UTC**. **Hueco de captura: 6 h 56 min 39 s.**
* **Sin pérdida ni daño de datos guardados**: PostgreSQL hizo su recuperación por WAL (0,07 s) y quedó íntegro; los
  59.234 payloads RAW verificados por hash tienen los **mismos 3 daños de siempre** (ninguno nuevo).
* **Catch-up completo con el mismo código y la misma trazabilidad** (RAW → hash → fila, una ejecución por tarea en
  el ledger): calendario, resultados, detalle post-partido, tablas, lesiones, cuotas pre-partido, cuotas finales
  pre-partido de los partidos jugados en el hueco, feeds de referencia. Nada retrofechado.
* **Lo irrecuperable, marcado** (§4): cuotas en vivo y estados en vivo del hueco, la ventana near-close de 13
  partidos, la ventana T-180 de 9, y 5 min 21 s sin captura en vivo durante el propio catch-up.
* **Tres defectos encontrados y corregidos, con tests** (§6): el notificador llevaba 21 h sin registrar nada (una
  restricción de la base de datos), los trabajos pesados bloqueaban la captura en vivo minutos enteros, y la
  auditoría llamaba "alto" a un precio nuestro más nuevo que la respuesta en caché del proveedor.
* **Auditoría tras la recuperación**: linaje 100 %, RAW sin daños nuevos, auditoría de verdad nº 12 con **0 críticos
  y 0 altos**, registro **14/14 FRESH**, libro de evidencias sin críticos ni altos abiertos (§10).
* **Segunda caída** de 02:37 a 05:27 UTC: una actualización de la app de Claude cerró los procesos de WSL que
  había lanzado. Pila relanzada fuera del árbol de la app; perdido y marcado en §12.
* `PICKS READY: NO` · `SHADOW: ON`.

## 1. Cronología (UTC)

| Momento | Evidencia | Qué |
|---|---|---|
| 5 oct 17:34:56 | `raw.worker_heartbeats` | worker en marcha (be-100, `e9741e7`) |
| 18:17:08 → 18:23:15 | Kernel-Power 506/507 | Modern Standby por inactividad y salida (el worker siguió) |
| 18:36:10 | log de PostgreSQL | último checkpoint |
| 18:37:56,828 | `raw.ingestion_payloads` | último payload RAW (`/odds/live`) |
| 18:37:57,242 | `raw.ingestion_runs` | **última ejecución terminada** (captura en vivo) |
| 18:38:04 | evento 1074 (User32) | apagado iniciado desde el menú Inicio |
| 18:38:07,928 | log de PostgreSQL | última sentencia del worker (la del notificador que fallaba, §6.1) |
| 18:38:09 | log de Docker Desktop | última línea del backend de Docker |
| 6 oct 01:12:06 | Kernel-General 12, Kernel-Power 41, EventLog 6008 | Windows arranca; el apagado anterior "no fue limpio" |
| 01:20:34–35 | log de PostgreSQL | `not properly shut down; automatic recovery in progress` → `redo done` → listo |
| 01:29 | consultas de solo lectura | hueco medido antes de tocar nada |
| 01:31 | `dev-up api web` | API y web en marcha, **sin** worker |
| 01:32:20–01:34:29 | `backup_label.sh` | respaldo `PRE_OFFLINE_RECOVERY_20261006` |
| 01:34:36,5 | `raw.worker_heartbeats` | worker en marcha (`6d2db63`): recupera runs abiertos y empieza el catch-up |
| 01:43 | alembic 0067 | corrección del notificador (be-102) |
| 01:48:17 | `raw.worker_heartbeats` | worker con be-103 (`2d942d3`): trabajos pesados fuera del bucle de la captura en vivo |
| 01:51:53–02:08:51 | run 10469 | catch-up de los feeds de referencia (4.000 peticiones, §3.1) |
| 02:09 | auditorías | linaje, integridad RAW, auditoría de verdad nº 11 (1 alto, falso: §6.3), registro, libro |
| 02:16 | be-104 (`f964d3a`) | comparador de cuotas corregido; auditoría de verdad nº 12: 0 críticos, 0 altos |

## 2. Arranque seguro

Orden seguido: Docker y PostgreSQL → API y web (sin worker) → medición del hueco con consultas de solo lectura →
respaldo → worker. El worker es el motor del catch-up: al arrancar cierra los runs que quedaron abiertos y sus
sincronizaciones se anclan al ledger, no al arranque del proceso, así que lo vencido corre de inmediato.

* **Respaldo previo** `PRE_OFFLINE_RECOVERY_20261006` (01:32:20 UTC): volcado verificado de 625.485.593 bytes
  (1.208 entradas), archivo RAW de 895.457.280 bytes (66.824 entradas), `SHA256SUMS`
  (`15d6492a…` volcado, `b20789f5…` RAW), etiquetas en backend (`6d2db63`) y frontend (`9be8559`) empujadas a los
  repos bare locales, instantánea de conteos (115 tablas) y escaneo de secretos.
* **PostgreSQL**: recuperación por WAL de `15/9A363C28` a `15/9AC89F78` en 0,07 s. El aviso
  `unexpected pageaddr` es el fin normal del WAL válido, no un error. Las estadísticas acumuladas (que usa el
  autovacuum) se reinician tras una recuperación así: se ejecutó `ANALYZE` (01:56, 8 s, ninguna fila cambia).
* **RAW**: 59.234 payloads re-hasheados (01:36): 3 dañados, **los mismos 3** de los informes anteriores
  (`05dbfadb…`, `0fd2243f…`, `67be90b8…`). El escritor RAW sincroniza el fichero antes de renombrarlo desde el
  4 oct; por eso el apagado brusco no dejó payloads vacíos.
* **Log del worker**: 1.338 bytes NUL al final de lo escrito antes del apagado (el log no se sincroniza; no es un
  dato). Las herramientas de lectura usan `grep -a`.
* **Docker Desktop** arrancó solo; su integración con WSL sigue apagada (conocido, `docs/RUNNING.md`): los scripts
  usan `docker.exe`.

## 3. Catch-up ejecutado

Todo por los caminos normales del worker y de los scripts, con su payload RAW, su hash y su ejecución en el ledger.

| Qué | Ejecución(es) | Resultado |
|---|---|---|
| Calendario (133 ligas, temporada completa) | 10415 `fixtures_sync` | 110 peticiones (una por temporada activa); 0 cambios de horario, 0 de competición, 0 partidos nuevos |
| Resultados | 10418 `results_sync`, 10419/10434 `results_repair` | los 17 partidos terminados en el hueco, con marcador; 2 amistosos siguen `NS` en el proveedor (`STALE_DATA`, del proveedor) |
| Detalle post-partido | 10435 `post_match_detail` | 49 partidos seguidos, 3 peticiones; los 17 con su lectura `settled` |
| Cuotas pre-partido | 10417, 10439 `odds_capture` | 61 peticiones, 16.269 precios, cada uno con su `minutes_to_ko` real |
| Cuotas finales pre-partido (partidos jugados en el hueco) | 10441 `final_prematch` | 19 de 20 con precio: 6.945 precios, mediana 44 min antes del inicio; 1 vacío |
| Tablas y lesiones | 10440 `context_due` | 4 tablas, 8.239 filas de ausencias |
| Feeds de referencia | catch-up manual (§3.1) | ver §3.1 |
| Cuotas en vivo | captura en vivo | desde las 01:34:37 (5 partidos en juego) |
| Elo y validación histórica | 10450, 10453 | 228.652 partidos; 228.001 aprobados; clases sin cambios |
| Picks (solo SHADOW) | 10426, 10427 | previsiones y liquidación; 0 calificados |

### 3.1 Feeds de referencia

Los feeds de referencia no pierden datos con un apagado (se pueden leer después), pero su cola de pendientes crece.
Además del reparto normal del worker (300 peticiones cada 30 min), se hizo una pasada de catch-up con el mismo código
(`python -m scripts.reference_refresh` con los feeds que se mueven cuando se juegan partidos, `--per-feed 1200
--max-requests 4000`), 01:51:53–02:08:51 UTC, dentro del presupuesto y sin tocar la reserva en vivo (441):

| Feed | Pedidos | Filas |
|---|---:|---:|
| `team_statistics` | 1.200 | 1.199 |
| `coachs` | 1.200 | 9.768 |
| `transfers` | 781 | 134.610 |
| `profiles_players` | 235 | 235 |
| tablas de goleadores, asistencias y tarjetas (4) | 408 | 1.099 |
| `current_round` / `rounds` | 114 | 10 |
| `predictions` (auxiliar; nunca entrada de un modelo) | 43 | 21 |
| `coachs_by_id`, `sidelined_*`, `trophies_*`, `venues` | 19 | 112 |
| **Total** | **4.000** | **147.054** |

Lo que sigue pendiente es la cola de siempre (P1), no algo del apagado: `players_teams` ~31.000, `team_statistics`
~3.660, `coachs` ~2.330, `transfers` ~2.260, `profiles_players` ~2.020. La absorbe el reparto normal del worker.

## 4. Lo irrecuperable, marcado

`/odds/live` no tiene historia y `/odds` solo da el precio actual: lo que no se leyó en su momento no existe para
nosotros y **no se rellena con precios posteriores**. Lo recuperable de esos partidos es el último precio
pre-partido que el proveedor guarda 7 días, que vive aparte (`market.final_prematch_odds`, con el sello del
proveedor; ningún pick puede leerlo).

**Ventanas pre-partido** (4320, 2880, 1440, 720, 360 y 180 min; tolerancia 45) que pasaron dentro del hueco sin
pedirse:

| Ventana | Partidos | Jugados en el hueco (perdida) | Sustituida por la pregunta de catch-up (a su distancia real) | Aún sin pedir |
|---|---|---|---|---|
| 4320 | 8 | 0 | 6 | 2 |
| 2880 | 12 | 0 | 12 | 0 |
| 1440 | 29 | 0 | 28 | 1 |
| 720 | 16 | 0 | 10 | 6 |
| 360 | 2 | 0 | 2 | 0 |
| 180 | 11 | **9** | 2 | 0 |

"Aún sin pedir" son partidos cuya próxima ventana todavía no llegó: la pedirá el planificador a su hora.

**Partidos jugados (o en juego) durante el hueco**: 22. Para cada uno: su último precio pre-partido capturado, si
su ventana near-close (T-12, `/odds/live`) cayó dentro del hueco y los minutos de directo perdidos. Los 17 terminados
en el hueco tienen su último precio pre-partido recuperado después del partido (8–9 casas, sellos del proveedor de
18:00 a 20:47 UTC); los 5 que seguían en juego lo tendrán cuando el trabajo de cuotas finales los pida.

| Partido (id proveedor) | Inicio (UTC) | Liga | Último precio capturado | Near-close (T-12) dentro del hueco | Minutos en vivo perdidos |
|---|---|---|---|---|---|
| Córdoba – Tenerife (1569952) | 5 oct 18:30 | Segunda División | T-175 | no | 107 |
| Francia – Bélgica (1528944) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Italia – Turquía (1528945) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Ucrania – Hungría (1528946) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Irlanda del Norte – Georgia (1528947) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Bosnia – Polonia (1528948) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Rumanía – Suecia (1528949) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Montenegro – Armenia (1528950) | 18:45 | UEFA Nations League | T-178 | no | 115 |
| Liechtenstein – Gibraltar (1610880) | 18:45 | Amistosos | T-178 | no | 115 |
| Guadalupe – Santa Lucía (1639992) | 19:00 | CONCACAF Nations League | T-177 | **sí** | 115 |
| Dep. Riestra – Central Córdoba (1493157) | 19:45 | Liga Profesional Argentina | T-178 | **sí** | 115 |
| Sp. Trinidense – Sp. Luqueño (1632025) | 20:00 | Paraguay Clausura | T-175 | **sí** | 115 |
| Cuba – San Cristóbal y Nieves (1639993) | 21:00 | CONCACAF Nations League | T-175 | **sí** | 115 |
| Estudiantes LP – Gimnasia M. (1493158) | 22:00 | Liga Profesional Argentina | T-357 | **sí** | 115 |
| Vélez – Platense (1493166) | 22:00 | Liga Profesional Argentina | T-357 | **sí** | 115 |
| Martinica – El Salvador (1639994) | 22:00 | CONCACAF Nations League | T-357 | **sí** | 115 |
| Cerro Porteño – 2 de Mayo (1632021) | 22:15 | Paraguay Clausura | T-310 | **sí** | 115 |
| Ind. Medellín – Santa Fe (1549809) | 6 oct 00:00 | Primera A | T-355 | **sí** | 95 |
| Bermudas – Barbados (1639995) | 00:00 | CONCACAF Nations League | T-355 | **sí** | 95 |
| Granada – Bonaire (1639996) | 00:00 | CONCACAF Nations League | T-355 | **sí** | 95 |
| Guatemala – Surinam (1639997) | 00:00 | CONCACAF Nations League | T-355 | **sí** | 95 |
| Banfield – Rosario Central (1493154) | 00:15 | Liga Profesional Argentina | T-355 | **sí** | 80 |

Los cinco últimos se capturan en vivo desde las 01:34:37. Además, **01:38:52–01:44:13 (5 min 21 s)** sin captura en
vivo para esos cinco: el calendario de amistosos de clubes bloqueó el bucle del worker (§6.2, corregido).

Lo que el sistema ya hace con esto: la cobertura de casas atribuye los partidos nunca pedidos antes del inicio a
`worker_down` (ningún run del worker cerca de sus ventanas), no a un fallo de planificación; la validación de
cierre usa `market.final_prematch_odds` solo como referencia de mercado, nunca como captura.

## 5. Jobs interrumpidos

* **10385 `pick_pipeline`**, abierto a las 18:36:56 del 5 oct: cerrado al arrancar el worker como `interrupted`
  ("started before this machine booted"); su trabajo lo rehicieron 10426/10427 (solo base de datos, idempotente).
* Ninguna otra ejecución quedó abierta. Unidades de migración: **29.554 hechas, 0 pendientes, 0 en curso**.
* **Championship 2021 (unidad 171537)**: hecha a las 18:22:25 del 5 oct (run 10340, segundo intento, 1 petición);
  la temporada tiene 186 partidos, todos terminados con resultado.
* El reinicio para desplegar be-103 (01:48:17) no interrumpió ninguna ejecución.

## 6. Problemas encontrados y corregidos

### 6.1 El notificador no registraba nada desde el 5 oct 04:07 UTC (be-102, `634bbc0`, migración 0067)

Encontrado en el log de PostgreSQL al medir el apagado: cada 10 min, `new row for relation "notifications"
violates check constraint "notifications_kind_check"`. Desde el 5 oct 05:45 el notificador redacta dos tipos nuevos
(`run_recovered`, `job_failing`) que la restricción de la revisión 0021 no admitía; el primer rechazo deshacía
**todos** los mensajes de esa ejecución, en cada ejecución, y solo quedaba `notify.failed` en el log.

* 0067: la restricción admite todos los tipos de `fbi.notify.service.KINDS` (el downgrade conserva las filas).
* Un `Draft` con un tipo fuera de `KINDS` falla al crearse; cada mensaje se inserta en su propio savepoint: uno
  rechazado se cuenta (`refused`) y se registra, sin arrastrar a los demás.
* Tests: la restricción de la base de datos acepta cada tipo que el código redacta; los mensajes del watchdog se
  guardan; un mensaje rechazado no se lleva a los demás.
* Verificado en el equipo: la ejecución de las 01:47:36 registró 6 `run_recovered`, 2.573 `shadow_pick` y 1.531
  `pick_settled` (eventos de los últimos días que estaban en la base de datos; sin canal configurado quedan como
  `skipped`).

### 6.2 Los trabajos pesados bloqueaban la captura en vivo (be-103, `2d942d3`)

Durante el catch-up, el calendario de amistosos de clubes (liga 667: 8.327 partidos en un payload) ocupó el único
bucle de eventos del worker 5 min 21 s con escrituras bloqueantes, y la captura en vivo no corrió. El ledger muestra
lo mismo el 5 oct: 5 min 8 s (calendario) y 7 min (referencia).

* `fbi.core.deadline.run_in_own_loop`: el trabajo corre en su propio bucle, en un hilo; una cancelación (plazo o
  parada del worker) llega a su tarea con su motivo y quien espera aguarda a que termine (sigue habiendo una sola
  ejecución a la vez).
* Van así `fixtures_sync`, `results_sync`, `historical_backfill`, `reference_refresh`, `catalogue_refresh`,
  `final_prematch`, `context_refresh`, `context_due` y `results_repair`. La captura en vivo y el tick pre-partido
  siguen en el bucle del planificador.
* Tests: el bucle del planificador sigue latiendo durante 0,6 s de trabajo bloqueante; los errores llegan a quien
  espera; un plazo cancela dentro del bucle del trabajo, dice por qué y se espera.

### 6.3 Un falso ALTO de la auditoría en cuotas (be-104, `f964d3a`)

La auditoría nº 11 dio un alto: partido 1640003, "32 precios difieren". Los payloads RAW lo explican: nuestra
captura de las 02:03:18 (`fixture` y `page=1`) venía sellada por el proveedor a las **00:45:21**; la petición de la
auditoría a las 02:11:06 (solo `fixture`, otra URL para la caché del proveedor) volvió sellada a las **20:47:14 del
día anterior**, con 7 casas en vez de 8. La respuesta vieja era la del proveedor, no la nuestra.

* `compare_odds`: un precio de una respuesta con sello posterior al sello actual del proveedor es `PROVIDER_LAG`,
  bajo, con los dos sellos como evidencia; con sellos iguales y precios distintos sigue siendo un alto; sin el sello
  de nuestra respuesta, el momento de captura sigue haciendo de sello.
* Tests: los dos casos nuevos junto a los cuatro que ya había. Auditoría nº 12: 0 altos.

### 6.4 Observado, sin corregir hoy

* **Dos ejecuciones del pipeline a la vez** (01:36:24 y 01:36:38): la del tick de cuotas y la programada. Las
  restricciones únicas evitaron candidatos duplicados (la segunda escribió 0), pero las previsiones se guardaron dos
  veces con 14 s de diferencia. Sin efecto en picks (SHADOW); queda en vigilancia.
* **El arranque automático tras reiniciar no está registrado** en Windows: tras el arranque de las 01:12 nada se
  levantó solo. Es una tarea programada de Windows (`scripts\windows\install-autostart.ps1`, `docs/RUNNING.md`);
  cambia la configuración del equipo y se deja a decisión del dueño.

## 7. API-Football

| Medida | Valor |
|---|---|
| Plan | Ultra, 75.000/día; presupuesto interno 60.000; suscripción activa hasta el 29 oct 04:31 UTC |
| 5 oct | 37.107 peticiones; la última a las 18:37:56, ninguna durante el apagado |
| No gastado durante el hueco | ~5.500 al ritmo recurrente del 5 oct (~800/h entre 09 y 14 h). No es consumo perdido (la cuota es diaria): lo que cuenta es lo que no se leyó a tiempo (§4) |
| 6 oct, hasta 02:18 UTC | **5.627** nuestras / **5.622** del proveedor (la diferencia: `/status` y peticiones que el proveedor no cuenta) |
| De ellas, el catch-up | referencia 4.300 (4.000 la pasada manual + 300 el worker), 2 auditorías de verdad 788, tablas 198, calendario 110, cuotas 65, en vivo 118, cuotas finales 20, tablas y lesiones debidas 18, resultados y detalle 8 |
| Restante hoy | 54.373 del presupuesto interno; 69.378 del plan |

Todas las peticiones del catch-up tienen su ejecución en el ledger y su payload en RAW.

## 8. P3 tanda 1, tras la recuperación

* 9 ligas seguidas (nivel 5), 81 temporadas 2018–2026, 19.927 partidos; **0 terminados sin resultado y 0
  atrasados**. Unidades de migración de la tanda: 1.223 hechas (calendarios 81, equipos 81, tablas 80, lesiones 7,
  detalle 974).
* Validación histórica: las 81 temporadas siguen `PARTIAL` por falta de cuotas históricas (Football-Data no cubre
  estas ligas; hace falta un 60 % con precio para juzgar contra el mercado); 18.655 aprobados y 2 en cuarentena,
  como antes.
* Los 2 partidos de la Clausura paraguaya jugados durante el hueco ya tienen resultado, detalle y su último precio
  pre-partido (9 casas, leído después del partido y guardado aparte); su near-close y su directo se perdieron (§4).
* La tanda 2 sigue esperando un día completo medido con la tanda 1: este apagado lo interrumpió, así que el día de
  referencia empieza de nuevo (`EXPANSION_P3.md` §6).

## 9. `/odds/mapping`

El barrido diario del 5 oct se hizo **antes** del apagado: 18:19:10–18:19:18 UTC, 26 páginas, 2.598 partidos
listados, 237 nuevos, comprobación sin error (completo, por debajo del tope de 200 páginas). La cadencia es de 23 h:
el apagado no se llevó ninguna lectura; la siguiente toca el 6 oct ~17:19 UTC. Hoy la tabla tiene 3.051 partidos y
546 de los 711 partidos seguidos de los próximos 7 días están listados.

## 10. Auditoría tras la recuperación

| Comprobación | Resultado |
|---|---|
| Linaje (10 tablas de modelos y páginas) | **100 % trazado a RAW**: 0 filas sin hash, 0 hashes sin payload (fixtures 245.680; resultados 228.677; tablas 22.375; alineaciones 436.377; eventos 3.191.457; estadísticas de equipo 350.592 y de jugador 5.238.783; ausencias 183.892; cuotas 213.443; cuotas históricas 345.964) |
| Integridad RAW (02:09) | 63.125 payloads re-hasheados; 3 dañados, los mismos 3 de siempre |
| Auditoría de verdad nº 11 (02:09, 394 peticiones, 0 fallos) | 0 críticos, **1 alto**: falso positivo del comparador de cuotas (§6.3) |
| Auditoría de verdad nº 12 (02:16, 394 peticiones, 0 fallos), tras be-104 | **0 críticos, 0 altos**. El mismo partido sale ahora como `provider_lag` bajo, con los dos sellos |
| Registro de datasets | **14/14 FRESH** |
| Libro de evidencias | 0 críticos y 0 altos abiertos o en vigilancia; OPEN medio 11, bajo 93, info 1 (sin cambios) |
| Versiones del dataset | `DATASET_V2` VALIDATED, ninguna MODEL_READY (decisión del dueño): ningún modelo puede entrenar |
| Captura en vivo con be-103 | 61 ciclos desde 01:48:17, peor hueco **30,0 s** (su intervalo), con la referencia, las tablas y las auditorías corriendo a la vez |

Medios de la nº 12, todos de tipos ya conocidos: resultados 23 (contradicciones del proveedor y partes del marcador
de partidos antiguos, abiertos en el libro), eventos 3 / alineaciones 9 / estadísticas 23 (revisiones tardías del
proveedor que recoge la relectura de las 26 h), tablas 4 (dos por un partido de la Apertura paraguaya con estado
`AWD` que la tabla del proveedor cuenta como jugado y nosotros no guardamos como terminado: no hay marcador real que
guardar), jugadores 2 (perfiles aún no leídos, cola P1), plantillas 1, cuotas 7 (precios que se movieron entre dos
ventanas de captura, por diseño).

## 11. Estado y siguiente paso

**Estado: verde.** PostgreSQL, API, worker (todos sus trabajos programados, a su cadencia normal) y web en marcha
desde las 01:34–01:48 UTC del 6 oct; `/health` ok; catch-up hecho; auditorías sin críticos ni altos; SHADOW
activo y ningún pick publicado (ningún modelo ha superado al mercado y ningún dataset está MODEL_READY).

Siguiente:

1. **Dueño**: registrar el arranque automático tras un reinicio (`powershell -ExecutionPolicy Bypass -File
   scripts\windows\install-autostart.ps1`, ver `docs/RUNNING.md`). Hoy, tras arrancar Windows, nada se levantó solo:
   el sistema quedó parado hasta la intervención. Es una tarea programada de Windows; no se creó sin tu permiso.
2. Medir el día completo con la tanda 1 dentro (hasta el 7 oct 01:34 UTC): consumo real por liga, cuotas en cada
   ventana, frescura. Solo entonces decidir la tanda 2 (`EXPANSION_P3.md` §5–6).
3. Vigilar las dos ejecuciones simultáneas del pipeline (§6.4).
4. P4 (reentrenar con backtesting walk-forward contra el mercado) necesita un dataset MODEL_READY: la promoción de
   `DATASET_V2` es decisión del dueño.

## 12. Segunda caída: una actualización de la app de Claude (6 oct, 02:36:50 UTC)

* **Qué pasó**: a las 02:36:50 UTC Windows instaló una actualización de la app de escritorio de Claude
  (`Claude_2.19675.1.0`, eventos 7045 y 2562; servicio CoworkVMService parado y arrancado) y cerró los `wslhost.exe`
  de esa app (evento 1002, "wslhost.exe ... stopped interacting with Windows and was closed"). La API, el worker y la
  web se habían lanzado a través del puente de la app, así que cayeron con ellos sin cerrar nada (sin
  `worker.stopped`). PostgreSQL siguió en marcha (vive en la distribución de Docker Desktop).
* **Hueco**: última ejecución 02:37:02,78 (run 10619) → worker de nuevo a las 05:27:02 (`ec5a0c9`): **2 h 50 min**.
  Ningún run quedó abierto. Perdido y marcado: el directo de Honduras – Jamaica (1639998, CONCACAF Nations League)
  y Australia U23 – Corea U23 (1643012, amistoso), 78 minutos cada uno; ventanas T-720 (21 partidos) y T-360 (7)
  pasaron sin pedirse y las cubre la pregunta de catch-up a su distancia real. Tras el arranque: cuotas (11
  peticiones), resultados, detalle post-partido, tablas y cuotas finales pre-partido (2 con precio, 712 precios; 4
  rechazadas por estar selladas después del inicio, como debe ser).
* **Corrección**: la pila se relanzó con `Win32_Process.Create` (WMI): el proceso cuelga de `WmiPrvSE.exe`, fuera
  del árbol de la app, y sobrevive a sus actualizaciones (comprobado con un proceso de prueba). Un reinicio de
  Windows todavía la para: la tarea de arranque automático (`scripts\windows\install-autostart.ps1`) sigue siendo
  decisión del dueño. Es otra razón para sacar producción del portátil (`DEPLOYMENT_COSTS.md`).
