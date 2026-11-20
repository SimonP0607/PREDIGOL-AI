# PM-04 · Carriles del cupo de API-Football

Plan Maestro PM, bloque 4 (peticiones e ingesta). Esta guía crece con cada tarea del bloque:

| Tarea | Código | Qué añade | Interruptor |
| --- | --- | --- | --- |
| PM-04-01 | BE-060 | Carriles con techo diario y prioridad | `FBI_APIFOOTBALL_LANES` (`off` por defecto) |
| PM-04-02 | BE-061 | Límites dinámicos, pausas, reserva de emergencia y pausa de la cuenta | `FBI_APIFOOTBALL_DYNAMIC_LIMITS` (`off`); `FBI_APIFOOTBALL_ACCOUNT_GUARD` (`on`) |

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

## 2. Límites dinámicos, pausas y reserva (PM-04-02, BE-061)

### Sobre los carriles

Con `FBI_APIFOOTBALL_DYNAMIC_LIMITS=on` (y los carriles en `measure` o `enforce`), además del techo de cada carril:

| Gastado del presupuesto del día | Se pausan hasta las 00:00 UTC |
| --- | --- |
| 60 % (36.000) | `historicos`, `ampliacion`, `reparacion`, `sin_carril` |
| 75 % (45.000) | además `referencia` |
| 88 % (52.800) | además `calendario` y `estadisticas_contexto`: solo quedan `directo`, `cuotas`, `alineaciones`, `resultados` |

* **Reserva de emergencia**: las últimas `FBI_APIFOOTBALL_EMERGENCY_RESERVE` peticiones (7.000) solo las gastan los cuatro carriles
  vitales. Los vitales nunca se pausan: solo los para su techo o el presupuesto entero.
* **Sin rellenos de 03:50 a 05:00 UTC** (copia PITR y copia diaria): `historicos` y `ampliacion` esperan a las 05:00.
* El total es el del propio presupuesto (`raw.provider_quota.spent`), leído con los carriles cada 15 s. Al día siguiente todo
  vuelve a empezar a las 00:00 UTC.
* **Picos del lunes**: el carril de históricos sube a ≈ 6.300 los lunes por el barrido semanal de `/players`; PM-04-03 (BE-062) lo
  pasa a mensual y escalonado. Ningún día medido pasa del 39 % del presupuesto (23.324 el 26-oct), así que hoy ninguna pausa se
  habría disparado.

### La pausa de la cuenta (corrección de PM-01-03)

El 29-oct-2026 la cuenta pasó al plan gratuito de 04:45 a 21:31 UTC y el proveedor contestó cada petición con **HTTP 200** y un
objeto `errors` («request limit for the day», «Free plans do not have access…»). El cortacircuitos lo contaba como éxito y se gastaron
47.000 peticiones del presupuesto en 16 horas (OPS-009). Ahora:

* Un error **de la cuenta** dentro de un 200 —clave `requests` o texto «request limit», clave `token`, `access` o `subscription`,
  «suspended», y `plan` / «Free plans» **solo si el plan configurado es de pago**— para **todas las peticiones del proceso** durante
  `FBI_APIFOOTBALL_ACCOUNT_PAUSE_SECONDS` (900 s). No salen ni gastan presupuesto; el trabajo se para como con el cortacircuitos
  abierto (`ProviderAccountError` es un `CircuitOpenError`). Pasada la pausa, la primera petición vuelve a probar: si la cuenta sigue
  igual, otra pausa. Un día como el 29-oct gasta 4 peticiones por hora en vez de miles, y en cuanto se renueva la cuenta todo vuelve
  en 15 minutos como mucho.
* Un error **de la petición** (`league`, `season`, parámetros) sigue siendo un error normal y no pausa nada. El límite por minuto
  (`rateLimit`) sigue siendo un reintento. En el plan gratuito, «Free plans do not have access to this season» es la respuesta de esa
  temporada (el relleno la anota como rechazo) y no pausa.
* El mensaje del error no copia el texto del proveedor: «do not have access» haría que el relleno retirara unidades para siempre.
* La referencia y el relleno ya no anotan nada cuando el cortacircuitos o la pausa rechazan antes de enviar: se paran y la siguiente
  pasada pregunta (antes la referencia marcaba el objetivo como consultado y lo dejaba una semana sin pedir).
* Registro: `provider.account_paused` (motivo, endpoint, segundos, veces), sin datos de la cuenta.
* Una pausa por proceso (el worker es un proceso). Un guion suelto que arranque durante la pausa hace su propia primera petición.
* **Encendida por defecto** (`FBI_APIFOOTBALL_ACCOUNT_GUARD=on`): es una corrección y la suscripción vence el 29-nov-2026.
  `off` devuelve el comportamiento anterior.

### Simulación del 29-oct (criterio de aceptación)

`tests/unit/test_quota_dynamic_limits.py` repasa el 29-oct hora a hora (`tests/fixtures/quota/pm_04_02_29_octubre_por_hora.csv`:
60.042 peticiones, el presupuesto entero):

| Escenario | Qué pasa |
| --- | --- |
| Como fue (sin carriles) | El presupuesto se acaba a las 21:3x y todo se para, lo vivo incluido |
| Solo carriles y límites dinámicos | Lo vivo sigue hasta las 23:59 y el presupuesto nunca se acaba, pero los rechazos de la cuenta llenan el techo de cuotas |
| Con la pausa de la cuenta | **Lo vivo y las cuotas siguen hasta el final del día** sin un solo rechazo; el día gasta menos de 10.000 |

### Comprobar

```
docker exec predigol-worker python -m scripts.quota_lanes show
docker logs predigol-worker --since 24h 2>&1 | grep -E "provider.account_paused|quota.lane_(would_)?limit" | tail
```

### Criterio de aceptación y cierre

* Simulación del 29-oct: cumplida en pruebas (arriba).
* Encender `FBI_APIFOOTBALL_DYNAMIC_LIMITS` junto con los carriles en `measure`, siete días sin incidentes y memoria del worker antes
  y después: con el kit auditado (PM-15-03).
