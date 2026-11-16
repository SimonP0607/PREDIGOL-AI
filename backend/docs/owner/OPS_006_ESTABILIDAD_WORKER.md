# OPS-006 · Estabilidad del worker (pieza AD-A05)

Pieza AD-A05 del plan de la arquitectura definitiva 2026. Cambia **cómo** escribe la sincronización de partidos
(`fixtures_sync`) y **dónde** corren la captura en vivo y el latido del worker. **No cambia qué se sincroniza ni lo que
queda guardado**: los mismos partidos, resultados, hechos y veredictos de campo neutral, con la misma regla de que un
dato más viejo nunca pisa uno más nuevo. Sin migración, sin interruptores, sin efecto en el lector, sin coste de API.

## 1. El problema (medición en producción, solo lectura, 16-nov-2026)

| Medida | Valor | Fuente |
| --- | --- | --- |
| Reinicios del worker por el chequeo de salud, 13 al 15-nov | 7, todos durante una `fixtures_sync` o al acabarla | `journalctl -u predigol-health.service` (informe de estado del plan, 16-nov 17:40 UTC) |
| Capturas en vivo de más de 2 min en 4 días | 21, todas durante una `fixtures_sync` (fuera de ella, 0 de 3.387); la más larga, 1.636 s | `raw.ingestion_runs`, 16-nov 20:46 UTC |
| Temporada «Friendlies Clubs» (liga 667, 2026) | 8.400 partidos, 7.682 terminados | `core.fixtures`, 16-nov 20:46 UTC |
| Duración de una `fixtures_sync` | 3.647 a 4.172 s (las 5 últimas completas); la liga 667 sola, ~30 min (16:13–16:44) | `raw.ingestion_runs`; registro del worker |
| Lo que cambia de verdad entre dos lecturas de la liga 667 | 1 o 2 partidos y 0 o 1 resultados de 8.400 (tres pares de respuestas consecutivas del 15 y 16-nov) | respuestas guardadas en el almacén RAW, comparadas campo a campo dentro del contenedor del worker |
| La sync de las 15:41 del 16-nov | aplicó **la misma respuesta, byte a byte**, que la de las 10:17 (mismo `payload_hash` `3528ff79…`) y aun así reescribió las 8.397 filas de partido y las 7.679 de resultado | `core.fixtures.source_payload_hash`/`source_fetched_at`, `core.fixture_results` |
| La sync de las 21:41 del 16-nov | la liga 667 fue **una transacción de 30 min 0,7 s** (todas sus filas con `updated_at` 22:14:28, la línea `fixtures.synced` a las 22:44:28) que reescribió 8.400 filas de partido y 7.682 de resultado con la misma respuesta por tercera vez (`3528ff79…`); durante ella, el mismo proceso tuvo abierto un `RowExclusiveLock` en `core.fixtures` en las tres lecturas (22:18, 22:18 y 22:29) | `core.fixtures.updated_at`, registro del worker, `pg_locks` |
| `lock_timeout` de la base | 0 (esperar para siempre); `log_lock_waits=off` | `pg_settings` |

**El mecanismo:** la sync hacía un único `commit` por temporada y reescribía todas las filas, cambiaran o no. Las 8.400
filas de amistosos quedaban bloqueadas ~30 min. La captura en vivo de cualquiera de esos partidos esperaba ese bloqueo
**dentro del bucle del planificador**, que se congelaba entero; el latido del worker se escribe en ese bucle, dejaba de
latir y el chequeo de salud reiniciaba un worker que estaba vivo. Solo pasa cuando hay amistosos de clubes en juego en esa
media hora (ventana FIFA del 13 al 18-nov).

## 2. Qué cambia

1. **Las filas iguales no se reescriben** (`fbi/ingestion/fixtures.py`, `fbi/ingestion/results.py`). Antes de escribir se
   lee lo que tiene cada fila y se compara con la respuesta. Si no cambia nada, la fila no pasa por el `upsert` campo a
   campo: solo avanza su procedencia (`source_payload_hash`, `source_fetched_at` y `updated_at`), en **una sentencia para
   todas**. La procedencia sí se sigue moviendo porque la leen la pantalla del partido («resultado pendiente del
   proveedor»), los informes de frescura y las auditorías («cuándo dijo esto el proveedor por última vez»): dejarla quieta
   cambiaría lo que ven. El estado del partido que el sincronizador de resultados escribía por segunda vez en la misma
   fila (idéntico) ya no se escribe. Si otra sesión tocó la fila entre la lectura y la escritura, esa fila va por el
   `upsert` de siempre (se comprueba con la versión de la fila, `xmin`).
2. **Commit por bloques.** Cada respuesta se aplica en bloques de 250 partidos (`FIXTURE_BLOCK`), cada uno con su
   partido, resultado y hechos juntos, y con su `commit`. Después, los veredictos de campo neutral en bloques de 500
   (`CLASSIFY_BLOCK`), igual que antes: cuando ya está escrita toda la respuesta.
3. **`lock_timeout` de 5 s con reintento del bloque.** Cada bloque corre con `lock_timeout = 5s` (local a su transacción).
   Si espera más, se deshace y se reintenta tras 2, 5 y 15 s. Si aún no puede, se abandona **ese bloque** y queda como
   error de la ejecución (estado `partial`): la siguiente sync lo vuelve a aplicar y la respuesta sigue en el almacén RAW.
4. **La captura en vivo fuera del bucle del planificador** (`apps/worker/scheduler.py`): `live_match_capture` pasa a
   `OWN_LOOP_JOBS`, como ya estaba `fixtures_sync`. La liquidación rápida que arranca al acabar un partido se sigue
   lanzando en el bucle del planificador, para no hacer esperar a la captura.
5. **El latido en su propio hilo** (`fbi/ops/heartbeat.py`, `LivenessPulse`): cada 60 s escribe `last_beat_at` con su
   propia conexión, pase lo que pase en el bucle. Sigue siendo un chequeo de verdad: deja de latir si el bucle no ejecuta
   nada en 10 min (`LOOP_STALL_SECONDS`) o si el planificador se paró, y nunca revive un worker que anunció su parada. El
   latido del tick (`last_tick_at`, resultado, duración, número de ticks) sigue igual, así que un tick parado se sigue
   viendo en la consola.

## 3. Qué no cambia

- Qué competiciones y temporadas se piden, cuántas peticiones se gastan y cuándo corre la sync.
- El contenido final de `core.fixtures`, `core.fixture_results`, `core.fixture_facts`, `core.fixture_venue_class`, los
  cambios de hora (`core.fixture_kickoff_changes`), las reparaciones (`audit.data_repairs`) y las revisiones de
  resultado: una prueba diferencial lo compara contra el `upsert` fila a fila.
- La regla de monotonía (`MONOTONIC_SQL`): un dato más viejo nunca pisa uno más nuevo.
- Los contadores del registro de ejecuciones (`rows_updated` cuenta una fila confirmada igual que antes).
- Nada de agentes, prompts, motores, umbrales, picks, interruptores ni del lector.

Una diferencia menor y buscada: mientras corre la sync, otra sesión puede ver la temporada a medio aplicar (unos bloques
nuevos y otros todavía de la lectura anterior). Cada fila sigue siendo correcta por sí sola y la siguiente lectura completa
el resto.

## 4. Pruebas (local, PostgreSQL 16, 16-nov-2026)

- Unitarias (`tests/unit/test_worker_stability_ops006.py`, 24): igualdad de filas, troceo en bloques en orden y
  clasificación al final, reintento y abandono de un bloque, latido con el bucle bloqueado, latido que se calla si el bucle
  no responde o el planificador se paró, y la captura en vivo en `OWN_LOOP_JOBS`.
- De integración (`tests/integration/test_fixtures_sync_blocks.py`, 5): temporada sintética de 8.400 partidos (7.680
  terminados) con una captura en vivo concurrente; reintento con una fila bloqueada; abandono del bloque; prueba
  diferencial; latido sobre la tabla real.

Medición local con esa temporada sintética (misma máquina, código anterior frente a nuevo):

| | Antes | Después |
| --- | ---: | ---: |
| Sync de la temporada sin cambios | 19,6–22,1 s | 4,7–5,0 s |
| Escritura en vivo de 20 partidos ya tocados por la sync en curso | 16,4 s (esperó a que acabara la sync entera) | 0,13 s (la sync siguió 2,6 s más) |
| Sentencias fila a fila en una sync sin cambios | ~16.000 (8.400 partidos + 7.680 resultados) | 0 |

En producción las tablas son mayores (`core.fixtures` 247.424 filas, 175 MB) y la sync de la liga 667 tarda ~30 min; la
espera en vivo pasa de «toda la temporada» a «un bloque».

## 5. Cómo comprobarlo después del desplegar (solo lectura)

Desplegar **fuera** de una ventana de `fixtures_sync` (empiezan a las 03:41, 09:41, 15:41 y 21:41 UTC y duran ~1 h; la
liga 667 entra unos 32 min después del inicio).

1. **Durante una sync** (por ejemplo entre las 04:13 y las 04:44 UTC), dos o tres veces. Con el usuario de solo lectura
   (`fbi`, sin `pg_read_all_stats`) `pg_stat_activity` **no** muestra el estado, la espera ni la consulta de las sesiones
   del worker (`predigol_worker`: «insufficient privilege»; comprobado el 16-nov a las 22:18 UTC). `pg_locks` sí se ve,
   y una espera aparece ahí con su hora de inicio:

   ```sql
   -- esperas de bloqueo en curso: quién espera, cuánto y quién lo bloquea (bien: ninguna de más de unos segundos)
   select l.pid, l.locktype, l.mode, round(extract(epoch from now()-l.waitstart)) espera_s, pg_blocking_pids(l.pid)
   from pg_locks l where not l.granted;
   -- quién tiene abierta una escritura en core.fixtures (la sync debería cambiar de transacción cada pocos segundos)
   select l.pid, l.mode, l.granted from pg_locks l where l.relation = 'core.fixtures'::regclass;
   ```

   Con un usuario con `pg_read_all_stats` (o el de administración), la consulta completa:

   ```sql
   select a.pid, a.application_name, a.state, a.wait_event_type, a.wait_event,
          round(extract(epoch from now()-a.xact_start)) xact_s, pg_blocking_pids(a.pid) blocked_by,
          left(regexp_replace(a.query,'\s+',' ','g'),90)
   from pg_stat_activity a where a.datname='fbi' and a.state<>'idle' order by a.xact_start limit 15;
   ```

   Bien: ninguna sesión con `wait_event_type = 'Lock'` sobre `core.fixtures` de más de unos segundos, y ninguna
   transacción de la sync con `xact_s` de minutos.

   **La duración de cada transacción se lee también después**, sin privilegios: `updated_at` de las filas es la hora de
   inicio de la transacción que las escribió. Antes, las 8.400 filas de la liga 667 compartían un único `updated_at` y
   el bloque duraba ~30 min hasta la línea `fixtures.synced` de la liga; después, cada bloque de 250 tiene el suyo, a
   segundos del anterior:

   ```sql
   select date_trunc('second', f.updated_at) inicio, count(*) filas
   from core.fixtures f join core.competition_seasons cs on cs.id = f.competition_season_id
   join core.competitions c on c.id = cs.competition_id
   where c.provider_league_id = 667 and cs.season = 2026 and f.updated_at > now() - interval '2 hours'
   group by 1 order by 1;
   ```

2. **Al acabar la ventana:**

   ```sql
   -- capturas en vivo largas durante la sync de hoy (debería ser 0 con amistosos en juego)
   select r.started_at, round(extract(epoch from r.finished_at-r.started_at)) s, r.status
   from raw.ingestion_runs r join raw.ingestion_runs s on s.job_type='fixtures_sync'
     and r.started_at between s.started_at and coalesce(s.finished_at, now())
   where r.job_type='live_match_capture' and s.started_at > now()-interval '8 hours'
     and r.finished_at-r.started_at > interval '120 seconds';
   -- la sync: duración, estado y errores (un bloque abandonado sale aquí)
   select id, started_at, finished_at, status, round(extract(epoch from finished_at-started_at)) s, last_error
   from raw.ingestion_runs where job_type='fixtures_sync' order by started_at desc limit 3;
   ```

3. **Registro del worker:** cada liga escribe `fixtures.synced` con `updated` y, nuevo, `unchanged` (filas confirmadas
   sin cambios). Para la liga 667 se espera `unchanged` cerca de 8.400. `fixtures.block_lock_wait` cuenta reintentos;
   `fixtures.block_gave_up`, bloques abandonados.
4. **Reinicios:** `journalctl -u predigol-health.service --since …` sin «worker heartbeat stopped».

**Criterio de cierre de la pieza:** en la primera ventana con amistosos en juego tras desplegar, 0 reinicios por latido,
0 capturas en vivo de más de 120 s durante la liga 667 y `pg_stat_activity` sin esperas `Lock` de `core.fixtures`.

## 6. Cómo se apaga o se revierte

No hay interruptor: se revierte el PR y se redespliega. No se pierde nada, porque la sync vuelve a escribir lo mismo.
Ajustes sin revertir (en código): `FIXTURE_BLOCK`, `LOCK_TIMEOUT` y `LOCK_RETRY_PAUSES_S` en `fbi/ingestion/fixtures.py`;
`PULSE_SECONDS` y `LOOP_STALL_SECONDS` en `fbi/ops/heartbeat.py`. Para volver a la captura en vivo en el bucle del
planificador basta con quitar `live_match_capture` de `OWN_LOOP_JOBS`.
