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

## Vuelta atrás

`FBI_WORKER_MEMWATCH=0` en `/etc/predigol/app.env` y `predigolctl up`: el worker deja de medir. Las claves `_mem` ya escritas se
quedan en sus filas (no se borran) y nadie las lee. El código se retira con un `revert` del PR.
