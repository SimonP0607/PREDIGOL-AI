# Cuotas en vivo efímeras: histórico in-play retirado (6 oct 2026)

Fase LIVE ODDS STORAGE CLEANUP, ejecutada el 6 oct 2026 entre las 22:34 y las 23:52 UTC en el portátil (WSL,
PostgreSQL en Docker). Código final `c7eec0d` (backend) y `64e2867` (frontend). Nada se publicó ni se contrató.

## 1. Qué cambió

| Antes | Ahora |
|---|---|
| Cada 30 s, `/odds/live` dejaba filas nuevas en `market.live_odds_snapshots` (solo cambios, ~15.851 por partido) y en `market.live_fixture_states`, más un fichero RAW por consulta | La misma consulta cada 30 s actualiza un **libro actual**: `market.live_odds_current` (una fila por partido, mercado, selección y línea) y `market.live_fixture_current` (una por partido). Son tablas UNLOGGED, sin histórico |
| El RAW de cada consulta se guardaba (≈ 1,25 MB por partido) | La respuesta se resume con su hash y **no se escribe**. Solo se guarda si abre una incidencia de calidad nueva, como evidencia |
| Las vistas `live_market_movement` y `live_odds_at_instant` leían el histórico | El movimiento se lee del libro: precio anterior, tipo de cambio y minuto del último cambio de cada cuota |
| — | Un partido sale del libro 10 min después de su último tick, aunque no haya más ticks |

Lo que **sigue guardándose** igual que antes, por `/fixtures` y el detalle post-partido: marcador, minuto y estado
(`core.fixture_live_states`), eventos, estadísticas, alineaciones, jugadores y resultado final.

La página En vivo y el Centro de partido muestran las cuotas en vivo del libro mientras el partido se juega. Al
terminar, el Centro de partido explica que no se conservan.

## 2. Por qué es seguro: nada pre-partido dependía del histórico in-play

* `tests/unit/test_prematch_independence.py` lee el código de features, modelos, picks, parlays, backtesting,
  predicciones, research, datasets, mercado, validación, analyst y notify, más la captura pre-partido (78 módulos).
  Comprueba que ninguno nombra una tabla in-play en su SQL ni importa el circuito en vivo. Comprueba también que
  ningún modelo pide el dataset `live` y que MODEL_READY cuenta solo precios pre-partido.
* `tests/integration/test_prematch_without_inplay.py` ejecuta la cadena completa dos veces sobre el mismo partido:
  predicción, consenso, candidatos, picks y liquidación. La segunda vez llena el libro y el histórico con precios
  absurdos para ese mismo partido. Las salidas son idénticas y la liquidación sigue solo el resultado.
* Se encontró y corrigió una dependencia oculta: el seguimiento en vivo (`ingestion/live_match.py`) elegía qué
  partidos seguir leyendo el histórico de estados. Ahora lee el libro.
* En PostgreSQL ninguna FK, función ni trigger apuntaba al histórico. Solo dependían las dos vistas, que se retiraron
  con él (medido por `inplay_cleanup measure`).

## 3. Orden de la limpieza y lo que se registró

1. **Backup verificable** (22:34–22:41 UTC, etiqueta `PRE_LIVE_ODDS_CLEANUP_20261006`):
   * volcado `~/backups/fbi-20261006T223851Z-PRE_LIVE_ODDS_CLEANUP_20261006.dump` (649.274.571 B), leído entero
     (`full_read_rc=0`), con su sha256 y los recuentos por tabla;
   * RAW en `~/backups/raw-20261006T223431Z-PRE_LIVE_ODDS_CLEANUP_20261006.tar` (982.968.320 B);
   * línea base de 62 endpoints y 115 tablas en `data/baselines/20261006T223454Z-PRE_LIVE_ODDS_CLEANUP_20261006`.
2. **Revisión 0068** (23:09 UTC): libro actual en marcha. Desde ese tick el histórico no creció ni una fila.
3. **Archivo fuera de PostgreSQL y del RAW**, en `~/archive/inplay/20261006T232319Z` (232.860.363 B):
   * las dos tablas en CSV gzip;
   * los 7.171 ficheros `/odds/live` en un tar con el sha256 de cada fichero.

   Todo se **releyó y comparó** con la base: filas, hash del contenido, partidos, intervalo y suma de cuotas por
   tabla, y cada payload contra el hash del índice. Solo entonces se registró en `audit.storage_cleanups`. Se
   volvió a verificar antes de borrar y otra vez después.
4. **Revisión 0069** (23:28 UTC): borra las dos tablas y sus vistas. Se niega si no hay un archivo verificado con
   exactamente sus filas. Registra filas y bytes de cada tabla.
5. **`purge-raw`** (23:40 UTC): borra del RAW los payloads archivados y sus filas de índice. Conserva los que nombra
   una incidencia de calidad y registra lo liberado.

`audit.storage_cleanups` tras la fase:

| id | Tipo | Qué | Filas | Bytes |
|---:|---|---|---:|---:|
| 1 | inplay_archive | market.live_odds_snapshots | 2.443.324 | 714.588.160 |
| 2 | inplay_archive | market.live_fixture_states | 36.914 | 0 (ver §6) |
| 3 | inplay_archive | raw:/odds/live | 7.171 ficheros | 168.367.042 |
| 4 | inplay_drop | market.live_odds_snapshots | 2.443.324 | 714.588.160 |
| 5 | inplay_drop | market.live_fixture_states | 36.914 | 7.757.824 |
| 6 | inplay_raw_purge | raw:/odds/live | 7.167 filas de índice | 168.291.358 |

El histórico abarcaba 195 partidos, del 1 oct 01:38:59 al 6 oct 23:08:32 UTC.

Las 16.688 filas de cuotas y 215 estados capturados entre el volcado (22:38) y el cambio (23:08) solo están en el
archivo verificado, no en el volcado. Lo mismo pasa con sus payloads.

## 4. Antes y después

| | Antes | Después |
|---|---:|---:|
| PostgreSQL | 10.661.542.935 B (23:23) | 9.940.179.991 B (23:29) |
| RAW | 922.360.853 B, 86.060 ficheros (23:35) | 754.125.256 B, 78.898 ficheros (23:41) |
| Filas in-play permanentes | 2.443.324 cuotas + 36.914 estados | **0**. El libro actual tenía 6 partidos y 1.966 precios (0,75 MB) a las 23:48 |
| Índice RAW `/odds/live` | 7.172 filas | 5: evidencia de incidencias de calidad |
| Ficheros `/odds/live` en el RAW | 7.179 (168.471.756 B) | 13 (180.398 B), ver §6 |

**Espacio recuperado: 890.637.342 B (0,83 GiB).** Son 722.345.984 B de PostgreSQL y 168.291.358 B de RAW. Además
quedan 0,22 GiB de archivo fuera de la base, que en producción irá a almacenamiento frío.

### Crecimiento diario

| | Antes | Después |
|---|---:|---:|
| Cuotas in-play, modelo con el calendario real de 133 ligas (`LIVE_ODDS_STORAGE_2026-10-06.md`) | ≈ 270 MB/día en PostgreSQL + ≈ 70 MB/día de RAW | **0** (libro acotado a los partidos en juego) |
| Cuotas in-play observadas del 1 al 6 oct, con cortes de la máquina | ≈ 150 MB/día | 0 filas en 92 ticks (23:09–23:55) |
| Resto de PrediGol (`storage_forecast`, 23:48, días completos 3–5 oct) | ≈ 114 MB/día | 95 MB/día en PostgreSQL + 19 MB/día de RAW |
| Total medio | **≈ 0,45 GB/día**; un sábado medio 1,19 GB | **≈ 0,11 GB/día**; un sábado medio ≈ 0,32 GB |

Lo que más crece ahora:

* `models.predictions`: 32,9 MB/día;
* `features.feature_sets`: 29,8 MB/día.

Se puede revisar en otra fase.

### Peticiones al proveedor

Sin cambios: `/odds/live` se sigue consultando cada 30 s mientras hay partidos en juego. En las últimas 24 h
fueron 1.881 llamadas, con días completos de ~2.200 a 2.900. El total del día fue 20.664, de las que 15.400 fueron
la primera carga de los feeds de referencia. Guardar o no guardar no cambia el consumo.

### Previsión (PostgreSQL + RAW, sin sistema ni copias locales)

| | 6 meses | 12 meses | 24 meses |
|---|---:|---:|---:|
| 133 ligas, con histórico in-play | ≈ 93 GB | ≈ 176 GB | ≈ 340 GB |
| 133 ligas, sin histórico (ahora) | **30 GB** | **51 GB** | **91 GB** |
| +50 ligas, con histórico | ≈ 125 GB | ≈ 240 GB | ≈ 468 GB |
| +50 ligas, sin histórico (ahora) | **38 GB** | **66 GB** | **123 GB** |

Las cifras sin histórico vienen de `storage_forecast` (23:48 UTC, a 6 y 12 meses); a 24 meses es la misma tasa
diaria. Las cifras con histórico suman a esa base la tasa in-play medida (0,34 GB/día; ×1,389 con +50 ligas).

### Dinero

En OVH, el VPS-3 (100 GB) cuesta €10,40/mes y el VPS-4 (200 GB) €19,96/mes, sin IVA. Contando ~13 GB de sistema y
WAL y un volcado local:

| | Con histórico in-play | Sin histórico |
|---|---|---|
| VPS-3 al 90 % | ≈ feb 2027 | ≈ abr 2028 |
| VPS-4 (el mayor de OVH) | se llenaría hacia sep 2027 | — |

| Ahorro | |
|---|---|
| Mensual, desde feb 2027 | €9,56 (≈ $10,7) |
| Año 1 | ≈ €76 (≈ $86) |
| Año 2 | ≥ €115 (≈ $129) |

En el año 2 el ahorro principal es otro: no tener que salir de OVH a almacenamiento por GB (€95–€179 al año según el
número de ligas; ver `LIVE_ODDS_STORAGE_2026-10-06.md` §6). Lo operativo pesa más que el dinero: copias y
restauraciones mueven 0,9 GB menos hoy y ~125 GB menos al año.

## 5. Verificaciones

* **Pre-partido intacto.** Se tomó una huella por fila (suma de md5) antes (23:25) y después (23:41) sobre lo
  anterior a las 23:00. Coinciden en filas, suma y huella:
  * `odds_snapshots`: 293.769 filas;
  * `final_prematch_odds`: 145.535;
  * `historical_odds`: 345.964;
  * `market_consensus`: 232.776;
  * índice RAW `/odds`: 2.147;
  * `fixture_events`: 3.191.598;
  * `fixture_live_states`: 16.938;
  * `picks`: 11.655.

  En `fixture_results` coinciden filas (228.768) y goles. La huella cambia por un solo partido (21809, 4-0): el
  detalle post-partido de las 23:32 renovó su payload de origen, como hace con todos los partidos recién terminados.
* **En vivo.** 92 ticks de 23:09 a 23:55 sin un fallo y con `payloads_stored = 0`. El histórico no existe. El índice
  RAW `/odds/live` sigue en 5.
  * El libro sigue a los partidos en juego: pasó de 4 a 6 partidos y de 0,57 a 0,77 MB.
  * Las cuotas que el proveedor retira salen del libro: el partido 476908 pasó de 199 a 140 precios entre el min 45 y
    el 76.
  * Marcador, minuto y eventos siguen guardándose: 157 estados de 6 partidos y 25 eventos desde el cambio.
* **Finalización con el cambio en marcha.** El partido 476908 terminó 1-1 a las 00:13:37 UTC del 7 oct:
  * el resultado quedó guardado en ese mismo instante, con 17 eventos, estadísticas de equipo, alineaciones y su
    último estado;
  * salió del libro de cuotas a los 10 min de su último tick (00:13:17 → fuera a las 00:23:59), sin dejar ninguna
    fila permanente de cuotas.
* **Integridad RAW** (`audit_raw_integrity`, 23:51): 70.088 payloads con hash verificado.
  * Antes había 3 dañados: 2 de `/odds/live` y 1 de `/fixtures`, todos del corte del 4 oct a las 02:57.
  * Queda solo el de `/fixtures`, que es previo y ajeno a esta fase.
  * Los dos de `/odds/live` están en el archivo tal como estaban.
* **Archivo.** Verifica antes del borrado, antes de `purge-raw` y después: 2.480.238 filas y 7.171 ficheros.
* **Calidad.** El barrido de calidad vuelve a completar: 7 checks en 10,8 s a las 23:50 (§6).
* **Gates:**
  * migraciones 0068 y 0069 up/down/up;
  * ruff limpio;
  * mypy estricto en 280 ficheros y en el árbol completo (601);
  * pytest 1.764 pasan y 4 se saltan;
  * frontend: lint con 0 errores, typecheck, 113 tests unitarios y build;
  * Playwright en la máquina contra el stack real: 57/57, con partidos en juego. Incluye el Centro de partido en
    vivo con el libro y un partido terminado sin cuotas in-play;
  * HTTP E2E del ciclo pre-partido → en vivo → final (Odds, En vivo, Centro de partido, Picks).

## 6. Problemas encontrados y cómo quedaron

1. **El primer volcado salió truncado** (22 MB). `docker.exe exec` lanzado desde una sesión WSL en segundo plano
   devolvía antes de tiempo. Se rehízo con `pg_dump` dentro del contenedor y lectura completa. El truncado quedó
   renombrado como `.INCOMPLETE-truncated`.
2. **Dos intentos de archivo fallaron.**
   * Uno, por un payload vacío en origen. Ahora se archiva byte a byte y se marca como `damaged_at_source`.
   * Otro, por un payload indexado cuyo fichero ya no existía desde el corte del 4 oct. Ahora queda nombrado en
     `missing_at_source` y su fila de índice se purga.

   Ninguno de los dos intentos se registró. Sus carpetas (`...-INCOMPLETE-not-recorded`, 0,47 GB juntas) se pueden
   borrar cuando el dueño lo autorice.
3. **0 bytes para `live_fixture_states` en el registro del archivo.** `pg_partition_tree()` no lista nada para una
   tabla sin particiones. Se corrigió el cálculo (`8e34cdf`). El registro del archivo se deja tal como se escribió y
   el tamaño real (7.757.824 B) quedó en el registro del borrado.
4. **El primer `purge-raw --confirm` se canceló a los 3 min sin borrar nada.** Al borrar una fila del índice RAW,
   PostgreSQL revisa fila a fila 51 FKs, 49 de ellas sin índice (hasta 5,2 M filas). Ahora el borrado salta esa
   revisión por fila y comprueba las referencias una vez por tabla, después del borrado y en la misma transacción
   (`c7eec0d`). Si encuentra una sola, revierte todo.
5. **El barrido de calidad fallaba desde las 19:44 UTC** (antes de esta fase). Daba `DiskFull` en `/dev/shm`, que
   mide 64 MB en el contenedor local. Ahora usa planes sin paralelismo (`578c439`). El `docker-compose.yml` local
   pide 512 MB, como el de producción, para cuando se recree el contenedor.
6. **Quedan 8 ficheros `/odds/live` sin fila de índice** (104.714 B). No están en el archivo, así que no se tocan:
   * 7 son del 1 oct, de 00:55 a 01:31, antes de la primera fila del histórico;
   * 1 es una copia del 4 oct a las 00:00 de un payload que sí está indexado.

## 7. Decisiones del dueño

* Borrar las dos carpetas de archivo fallidas (0,47 GB).
* Llevar `~/archive/inplay/20261006T232319Z` a almacenamiento frío cuando exista el destino (R2 o equivalente).
* Recrear el contenedor de PostgreSQL local para aplicar `shm_size`. Es un reinicio breve de la base.
