# PM-13-05 · Memoria del worker por trabajo (siete días de medición)

Plan Maestro PM, ola 1 («Medir y reconciliar»). Código OPS-010. Módulo: `backend/src/fbi/ops/memwatch.py`.

## Por qué

El 19-nov-2026 el worker usaba 2,80 de sus 3 GiB y tocó el límite 4.160 veces en diez horas (`memory.events`), sin muertes
por memoria. Nada decía qué trabajo lo lleva ahí. Esta medición lo dice **sin subir ningún límite** y sin mover nada todavía.

## Qué mide (y qué cuesta)

* Un hilo del propio worker lee cada **5 s** su memoria residente (`/proc/self/statm`) y su máximo histórico (`VmHWM`). Es una
  lectura de un archivo pequeño: no hay copia de objetos ni recuento de Python (`tracemalloc` no se usa).
* Cada ejecución de un trabajo es un **tramo**: un trabajo de APScheduler entre su arranque y su final (los 73 trabajos,
  incluidos los de IA) y una ejecución del libro (`raw.ingestion_runs`) entre su apertura y su cierre.
* Al cerrar un tramo se anota, en MiB: memoria al empezar (`rss_start_mib`), al terminar (`rss_end_mib`), la mayor vista
  (`rss_max_mib`), lo que quedó retenido (`grew_mib`), el pico sobre el arranque (`peak_over_start_mib`), **cuánto subió el
  máximo histórico del proceso durante el tramo** (`hwm_raised_mib`: el tramo que empuja el proceso a un pico nuevo es el
  candidato a salir), el máximo histórico tras él (`hwm_mib`), cuántos tramos había abiertos a la vez (`overlap`) y cuántas
  muestras tuvo (`samples`).
* Dónde queda: una línea `job.memory` en el registro del worker por cada trabajo de APScheduler, y en la fila de su ejecución
  del libro, `raw.ingestion_runs.params->'_mem'` (persistente: sobrevive a los reinicios de cada despliegue). No hay tabla
  nueva, ni migración, ni permisos nuevos: el worker ya escribe esa fila al cerrarla.
* Límite de lectura: el worker es **un proceso con hilos**; la memoria es del proceso. Con `overlap` > 1 la cifra de un tramo
  es una cota superior (incluye lo de los demás). Por eso se mira sobre todo `hwm_raised_mib` y los tramos con `overlap` bajo.

Interruptor: `FBI_WORKER_MEMWATCH` (encendido por omisión, porque no se ve en ninguna pantalla); `0` lo apaga tras reiniciar
el worker con `predigolctl up`. Fuera del worker (API, mensajero, guiones) no se mide nada.

## Calendario

* **Día 0**: el despliegue que trae OPS-010 (la hora sale de `predigolctl status` y del `chain.status` de la cadena).
* **Días 1 a 6**: nada que hacer. Si se quiere, la lectura diaria de abajo (una consulta, solo lectura).
* **Día 7** (día 0 + 7, después de las 12:00 UTC y fuera de las ventanas de copia y de `fixtures_sync`, que hoy empiezan a
  las 03:55, 09:55, 15:55 y 21:55 UTC y duran una hora): la consulta de cierre y la propuesta.

## Consulta de cierre (solo lectura; sustituye `<D0>` por la hora del despliegue, en UTC)

```
docker exec predigol-postgres psql -U postgres -d fbi -c "SET default_transaction_read_only=on" -c "SET statement_timeout='90s'" -c "
SELECT job_type, count(*) AS runs,
       round(avg((params->'_mem'->>'grew_mib')::numeric),1) AS grew_avg,
       round(max((params->'_mem'->>'peak_over_start_mib')::numeric),1) AS peak_over_start_max,
       round(max((params->'_mem'->>'rss_max_mib')::numeric),1) AS rss_max,
       count(*) FILTER (WHERE (params->'_mem'->>'hwm_raised_mib')::numeric > 0) AS raised_hwm,
       round(sum((params->'_mem'->>'hwm_raised_mib')::numeric),1) AS hwm_raised_total,
       round(avg((params->'_mem'->>'overlap')::numeric),1) AS overlap_avg
  FROM raw.ingestion_runs
 WHERE started_at >= '<D0>' AND params ? '_mem'
 GROUP BY 1 ORDER BY hwm_raised_total DESC NULLS LAST, peak_over_start_max DESC NULLS LAST"
```

Y, en el mismo momento, el total del contenedor (solo lectura):

```
CID=$(docker inspect -f '{{.Id}}' predigol-worker); CG=/sys/fs/cgroup/system.slice/docker-$CID.scope
cat $CG/memory.current $CG/memory.peak $CG/memory.events; grep -E '^(anon|file) ' $CG/memory.stat
docker inspect -f '{{.State.StartedAt}}' predigol-worker
```

Los trabajos sin fila en el libro (los de IA: `ai_cycle`, `ai_orchestrate`, `intel_decide`…) se leen en el registro del día
(se pierde en cada recreación del contenedor, así que se mira el del día 7):

```
docker logs --since 24h predigol-worker 2>&1 | grep '"job.memory"' > /tmp/pm1305_dia7.jsonl; wc -l /tmp/pm1305_dia7.jsonl
```

(cópialo al portátil con la sesión SSH y bórralo del servidor después; no contiene datos de usuarios ni secretos).

## Cómo se comprueba que cuadra con el total

La suma de `hwm_raised_mib` desde el arranque del contenedor tiene que ser **igual o mayor** (por los solapes) que la subida del
máximo histórico del proceso (`VmHWM` actual menos el del primer tramo), y ningún `rss_max_mib` puede pasar de
`memory.peak` del contenedor. Si no cuadra, la medición no vale y se dice.

## Propuesta que sale de aquí (día 7)

Una tabla «trabajo → MiB que añade al pico, veces, solapes» y la lista de los que salen a un proceso por lotes aparte
(`docker exec predigol-worker python -m …` lanzado por su temporizador, o un contenedor de un solo uso), con la regla:
sale el que sube el máximo histórico en más de 200 MiB en al menos tres de sus ejecuciones, o el que pasa de 500 MiB sobre su
arranque. **Ningún trabajo nuevo del Plan PM corre dentro del worker** mientras tanto. No se sube ningún límite de memoria.

Candidatos a mirar primero (por lo que hacen, sin medir todavía): `fixtures_sync` (una hora, 230.000 filas por pasada),
`elo_refresh` (1,9 millones de filas), `historical_validation` (0,9 millones), `pick_pipeline`, `odds_book_refresh` y el
análisis de IA (`ai_cycle`, hasta 18 min).

## Decisión del 26-nov-2026 (siete días medidos: 20-nov 05:40 a 26-nov 23:15 UTC, 39.015 ejecuciones de 73 trabajos)

Lectura solo de `raw.ingestion_runs.params->'_mem'`, del cgroup del worker y de `/proc/<pid>/smaps` (sin tocar nada). Con `overlap`
medio de 10 a 25 tramos abiertos a la vez, la cifra de un tramo es una cota; por eso se cruzó con una atribución que reparte cada
cambio de memoria entre los tramos abiertos en ese intervalo (1/k) y se miró cada vida larga del worker por separado.

**Lo que se vio**

1. El worker no llega a 3 GiB de golpe: sube unos 330 MiB por hora y casi no baja. Suelo entre dos ejecuciones: 1,7 GiB a las 17:00 y
   3,0 GiB a las 21:00 del 25-nov. Hoy (26-nov) los despliegues lo reinician cada una o dos horas (nueve reinicios), y por eso no pasó de
   1,9 GiB salvo picos de 3,0 GiB a las 11:30 y 12:00.
2. Lo que se queda: `pick_pipeline` (850 pasos, cada 12 a 30 minutos) se lleva del 84 % al 139 % del crecimiento neto en las cuatro vidas largas
   del worker (de 15 a 67 MiB que quedan retenidos por paso; 331 de 850 pasos dejaron ≥ 100 MiB). `stats_documents`, `research_monitor`
   y `elo_refresh` le siguen. Ningún caché de módulo explica el crecimiento (las `lru_cache` son de 1 a 4.096 entradas pequeñas y no hay
   diccionarios globales grandes).
3. Los picos: `stats_documents` (12 pasos el 26-nov, 26 a 35 minutos cada uno, +470 a +1.930 MiB, hasta 2,15 GiB sobre su arranque;
   al menos cinco pararon en el tope de 35 minutos (`stopped_reason = tiempo_maximo`)). Corría a los 12 minutos de **cada** arranque del worker (nueve al día por los despliegues).
   Le siguen `ai_cycle` (57 pasos, hasta +1,85 GiB), `research_monitor` (7 pasos, hasta +2,26 GiB; +1,1 GiB retenido en uno),
   `fixtures_sync` (+1,04 GiB) y `elo_refresh` (+0,66 GiB).
4. `/proc/<pid>/smaps` del worker a las 23:19 UTC, 58 minutos después de un reinicio: 1,15 GiB residentes y 0,19 GiB en swap; siete
   arenas de 64 MiB de `malloc` (231 MiB residentes y 159 MiB en swap) y 303 mapeos anónimos con 1.047 MiB; 24 hilos; el entorno del
   worker no fija `MALLOC_ARENA_MAX`, el de los procesos de la matriz sí (2).

**Qué sale a proceso aparte, por la regla de la guía (> 200 MiB de máximo histórico en ≥ 3 ejecuciones o > 500 MiB sobre su arranque)**

| Trabajo | Ejecuciones ≥ 500 MiB sobre su arranque | Pico máx. sobre su arranque | Decisión |
| --- | --- | --- | --- |
| `stats_documents` | 10 de 10 | 2.155 MiB | Primero: ya no se repite a cada arranque (este PR). El pase de las 07:20 UTC pasa a proceso aparte, por temporadas, en el siguiente PR (hoy un proceso aparte no baja el pico del contenedor, solo evita que el worker lo conserve). |
| `research_monitor` | 5 de 7 | 2.256 MiB | Segundo: una vez al día; script aparte con su tope, como `availability_refresh`. Siguiente PR. |
| `ai_cycle` | 5 de 57 | 1.851 MiB | Zona de Intelligence: se avisa con estos datos; no se toca. |
| `pick_pipeline` | 91 de 850 | 1.465 MiB | **Se queda**: corre cada 12 a 30 minutos y tras cada captura; el cambio de este PR (devolver memoria tras cada paso pesado) es lo que se mide. Si el suelo sigue subiendo tras el cambio, se procesa por lotes de partidos. |

**Qué cambia en este PR (OPS-026)**

* `stats_documents`: el pase de «puesta al día» tras un arranque solo se programa si ningún pase completo terminó en las últimas 20
  horas (`analytics.stat_runs.stopped_reason IS NULL`). El de las 07:20 UTC no cambia.
* `fbi.ops.memrelease` (interruptor `FBI_WORKER_MEMTRIM`, encendido por omisión): al arrancar, glibc se limita a dos arenas; tras una
  ejecución pesada (sube el proceso ≥ 50 MiB o pasa ≥ 150 MiB sobre su arranque), como mucho cada cinco minutos, `gc.collect()` y
  `malloc_trim(0)`. Lo hecho queda en `params._mem.release` de la fila de esa ejecución: `rss_before_mib`, `rss_after_mib`, `freed_mib`,
  `freed_by_trim_mib`, `blocks_before`/`blocks_after` (bloques vivos de Python), `collected` y `seconds`.

**Cómo se lee el resultado**

```
SELECT job_type, count(*) n, round(avg((params->'_mem'->'release'->>'freed_mib')::numeric),1) liberado_medio,
       round(max((params->'_mem'->'release'->>'freed_mib')::numeric),1) liberado_max,
       round(avg((params->'_mem'->'release'->>'seconds')::numeric),2) segundos_medio,
       round(avg(((params->'_mem'->'release'->>'blocks_before')::bigint - (params->'_mem'->'release'->>'blocks_after')::bigint)),0) bloques_menos
  FROM raw.ingestion_runs WHERE params->'_mem' ? 'release' AND started_at >= '<D0>' GROUP BY 1 ORDER BY liberado_medio DESC
```

* Si `freed_mib` es grande y los bloques de Python no bajan, lo retenido era memoria de `malloc` fragmentada: el cambio sirve y se queda.
* Si `freed_mib` es ≈ 0 y los bloques no bajan, el trabajo guarda datos reales: se procesa por lotes (o sale a proceso aparte).
* Si `seconds` pasa de 1 s de media, se quita el `gc.collect()` (queda solo el `malloc_trim`).
* Antes/después del suelo: el mínimo de `rss_start_mib` de `pick_pipeline` por vida del worker (antes: 1,7 → 3,0 GiB en 4 horas el 25-nov).

**Vuelta atrás de este PR**: `FBI_WORKER_MEMTRIM=0` y `predigolctl up` (devuelve el worker a su comportamiento anterior, salvo el pase de
`stats_documents` tras un arranque, que se retira con un `revert`).

## Vuelta atrás

`FBI_WORKER_MEMWATCH=0` en `/etc/predigol/app.env` y `predigolctl up`: el worker deja de medir. Las claves `_mem` ya escritas se
quedan en sus filas (no se borran) y nadie las lee. El código se retira con un `revert` del PR.
