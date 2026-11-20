# PM-04 · Carriles del cupo de API-Football

Plan Maestro PM, bloque 4 (peticiones e ingesta). Esta guía crece con cada tarea del bloque:

| Tarea | Código | Qué añade | Interruptor |
| --- | --- | --- | --- |
| PM-04-01 | BE-060 | Carriles con techo diario y prioridad | `FBI_APIFOOTBALL_LANES` (`off` por defecto) |

## 1. Carriles (PM-04-01, BE-060)

### Qué es

El presupuesto propio (`FBI_APIFOOTBALL_DAILY_BUDGET`, 60.000 al día) era una sola bolsa con topes sueltos (vivo 12.000, refrescos
del libro 8.000, el seguimiento en vivo se para con menos de 3.000). Ahora cada trabajo pertenece a un **carril** con prioridad y
**techo diario**. La tabla está en `backend/src/fbi/providers/lanes.py` y la elige el `job_type` que el trabajo escribe en su
ejecución (`raw.ingestion_runs`), el mismo que ya cuenta PM-01-02 en `raw.provider_endpoint_usage`.

| Prioridad | Carril | Trabajos | Techo | Mayor día medido (15-oct–19-nov) | Vital |
| --- | --- | --- | --- | --- | --- |
| 1 | `directo` | `live_match_capture`, `live_odds_capture` | 15.000 | 5.606 | sí |
| 2 | `cuotas` | `odds_capture`, `odds_book_refresh`, `final_prematch` | 10.000 | 3.217 | sí |
| 3 | `alineaciones` | `prematch_lineups`, `lineup_watch` | 1.500 | 788 | sí |
| 4 | `resultados` | `results_sync`, `results_repair`, `post_match_detail` | 1.500 | 163 | sí |
| 5 | `calendario` | `fixtures_sync`, `catalogue_refresh`, `seasons_refresh`, `teams_sync` | 1.500 | 718 | no |
| 6 | `estadisticas_contexto` | `context_refresh`, `context_due`, `context_refresh_manual` | 3.000 | 2.527 (29-oct; si no, 952) | no |
| 7 | `referencia` | `reference_refresh` | 15.000 | 14.343 (martes: ronda semanal de personas) | no |
| 8 | `historicos` | `historical_backfill`, `historical_odds_import`, `raw_backfill_season_stats` | 8.000 | 6.533 (lunes: barrido semanal de `/players`) | no |
| 9 | `ampliacion` | sondas y expansión (`league_probe`, `league_expansion`, `plan_probe`, `window_probe`, `capacity_probe`, `odds_flag_probe`, `half_probe`) | 5.000 | 0 | no |
| 10 | `reparacion` | `reprocess_fixture_venues` | 1.500 | 0 | no |
| 11 | `sin_carril` | cualquier trabajo no listado y `/status` | 2.000 | 26 | no |

**Por qué no son los techos del plan.** La sección 6 del plan propone referencia 9.000, históricos 6.000 y estadísticas 2.000. Con el
consumo real de los 36 días medidos esos techos habrían cortado las rondas semanales de los lunes y martes (lo prueba
`tests/unit/test_quota_lanes.py`). La tabla inicial **cubre el mayor día medido de cada carril**: encenderla no cambia nada de lo que
hoy funciona. Los techos del plan se alcanzan con `FBI_APIFOOTBALL_LANE_CEILINGS` cuando PM-04-03 y PM-04-04 hayan recortado los
barridos y catorce días medidos digan que caben.

### Cómo decide

* Antes de gastar el presupuesto diario, el cliente pregunta al guardián del carril (`LaneGuard`). Si el carril ya llegó a su techo
  del día UTC, en `enforce` la petición **no sale ni gasta** y el trabajo se para como cuando se agota el presupuesto
  (`LaneLimitedError` es un `QuotaExhaustedError`). Los demás carriles siguen.
* Solo cuenta lo que gastó **su** carril: un barrido nunca retrasa a lo vivo. El guardián nunca espera; deja pasar o rechaza al
  momento. Si no puede leer los recuentos, deja pasar (y lo anota): su propio fallo nunca cuesta una petición.
* Los recuentos salen de `raw.provider_endpoint_usage` más lo que el contador del proceso aún tiene en memoria, leídos como mucho
  cada 15 s. Lo que otro proceso no ha volcado (≤ 1 min) no se ve: es un límite blando. El límite duro, compartido y atómico, sigue
  siendo el presupuesto diario.
* Se reinicia a las 00:00 UTC.
* El relleno histórico se para al primer rechazo (presupuesto, carril o cortacircuitos) y deja la unidad pendiente sin contar
  intento; la siguiente pasada la retoma. Los demás trabajos ya se paraban con el presupuesto agotado.
* La prioridad y la marca «vital» las usan los límites dinámicos y la reserva de PM-04-02.

### Interruptor

En `/etc/predigol/app.env` (el worker lo lee al arrancar; necesita `FBI_PROVIDER_USAGE` encendido, que lo está):

```
FBI_APIFOOTBALL_LANES=off        # por defecto: exactamente el comportamiento anterior
FBI_APIFOOTBALL_LANES=measure    # decide y anota quota.lane_would_limit; no rechaza nada
FBI_APIFOOTBALL_LANES=enforce    # rechaza el carril que pasa su techo
FBI_APIFOOTBALL_LANE_CEILINGS=referencia=9000,historicos=6000   # opcional, sobre la tabla
```

Una palabra desconocida es `off`, y una entrada de techos ilegible se ignora y se anota (`quota.lane_ceilings_ignored`): una errata
nunca impide que arranque el worker. Encender o cambiar: copia fechada de `app.env`, editar, `predigolctl up`. Volver atrás: `off` y
`predigolctl up`, sin despliegue.

### Comprobar (solo lectura, 0 peticiones)

```
docker exec predigol-worker python -m scripts.quota_lanes show
docker exec predigol-worker python -m scripts.quota_lanes report --days 14
docker exec predigol-worker python -m scripts.quota_lanes simulate --since 2026-10-15 --until 2026-11-20
```

Conexión de solo lectura (`default_transaction_read_only`, 90 s por consulta). `report` lee los días completos que el
contador de PM-01-02 tiene desde el 20-nov-2026 y da, por día y carril, lo gastado y lo que se habría rechazado; la última línea
resume cuántos días se habría limitado algún carril y cuántos un carril vital. Es la prueba del criterio de aceptación («catorce días
sin que ningún carril vivo habría sido limitado») y no necesita encender `measure`: el contador mide igual. `simulate` repasa los
días anteriores con el libro de ejecuciones (`api_calls`, que no cuenta los intentos fallidos).

### Criterio de aceptación y cierre

* Catorce días completos (desde el 21-nov) con `report --days 14` en «0 with a vital lane limited». Primer día posible: **5-dic-2026**.
* Encendido a `measure` y después a `enforce`: con el kit auditado de PM-15-03 (decisión del dueño). Memoria del worker medida antes
  y después (PM-13-05).
