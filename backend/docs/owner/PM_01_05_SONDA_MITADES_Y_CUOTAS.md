# PM-01-05 y PM-01-04 · Sondas de cobertura del proveedor (mitades y cuotas)

Plan Maestro PM, ola 1 («Medir y reconciliar»). Código BE-053. Guion: `backend/scripts/coverage_probe.py`.

Las dos sondas son **de solo lectura** frente a lo que PrediGol ya hace: no añaden ningún trabajo al worker, no cambian la ingesta,
no normalizan nada y no escriben ninguna tabla salvo el índice RAW (`raw.ingestion_payloads`) y el registro de ejecuciones
(`raw.ingestion_runs`). Toda petición pasa por `build_client`: el presupuesto diario común (60.000), el límite por minuto
compartido con el worker y, además, el tope propio de cada ejecución (`--max-requests`). La clave va en una cabecera; nunca sale
en un parámetro, en el registro ni en el informe. Se ejecutan a mano (o las programa el coordinador): **no hay interruptor nuevo**
porque nada corre solo.

## Cuándo se puede ejecutar

Nunca entre las 03:30 y las 05:00 UTC (PITR y copia), ni a menos de 20 min de las `fixtures_sync` (03:41, 09:41, 15:41 y
21:41 UTC; cada una dura cerca de una hora), ni hacia las 07:20 UTC (pasada de estadísticas), ni los lunes a las 06:00 UTC,
ni durante una cadena de despliegue (`systemctl list-units 'auto-*'` vacío). Hora recomendada: **12:10 UTC**.

## 1. PM-01-05 · Una semana de `half=true`

**Qué mide.** Si `GET /fixtures/statistics?fixture=…&half=true` trae los bloques de primera y segunda mitad
(`statistics_1h`, `statistics_2h`) y qué tipos llegan vacíos, partido a partido, en 12 competiciones de distinto nivel:
Primera A (239), Champions (2), Libertadores (13), Premier League (39), Brasileirão (71), Liga Profesional Argentina (128),
Liga MX (262), J1 League (98), K League 1 (292, el caso irregular: estadísticas en el 56 % de sus partidos el 19-nov),
Segunda División (141), Championship (40) y League One (41, tercer nivel).

**Muestra.** Todos los partidos terminados de esas 12 con saque entre el **20-oct-2026 00:00 y el 26-nov-2026 00:00 UTC**
(los de la semana medida y las cuatro anteriores, para que cada competición tenga muestra). La Libertadores solo tiene dos
partidos en la ventana (la final es el 28-nov): se amplía aparte con su temporada desde el 1-ago (apartado 1.2). Cada partido
se pide **una sola vez** y 2 h 30 min después del saque como pronto; uno ya pedido (su respuesta está en el índice RAW) no se
vuelve a pedir. Se pide del más antiguo al más reciente. Las respuestas no las lee ningún normalizador (ninguno trata
`/fixtures/statistics`): quedan en RAW como evidencia.

**Coste.** Entre 600 y 900 peticiones en total, **como mucho 150 al día** (el 0,25 % del límite diario; el margen habitual es
de 36.000 a 45.000). Cabe antes del fin de la suscripción (29-nov 21:45 UTC).

### 1.1 Cada día, del 20 al 26-nov (días 1 a 7)

Desde el portátil, por SSH `predigol`, una vez al día a las 12:10 UTC:

```
docker exec predigol-worker python -m scripts.coverage_probe half plan
docker exec predigol-worker python -m scripts.coverage_probe half run --max-requests 150
docker exec predigol-worker python -m scripts.coverage_probe half report
```

* `plan` (0 peticiones): cuántos partidos terminados hay, cuántos ya se pidieron y cuántos quedan, por competición.
* `run`: pide los que quedan, hasta 150. Imprime una línea JSON con `run_id`, `requests`, `answers` (`with_halves`,
  `without_halves`, `empty`, `error`) y `stopped_early`. Código de salida 0.
* `report` (0 peticiones): la tabla por competición y dato. Se puede repetir cuando se quiera; `--json` da el detalle.

Guarda la salida de cada día con su hora UTC (por ejemplo en `fbi_scratch\pm\pm0105_dia<N>.txt`).

### 1.2 Libertadores (una vez, el día 1 o el 2)

```
docker exec predigol-worker python -m scripts.coverage_probe half run --league 13 --since 2026-08-01 --max-requests 40
docker exec predigol-worker python -m scripts.coverage_probe half report --league 13 --since 2026-08-01
```

### 1.3 Cómo se lee el informe

* «Con 1T y 2T»: partidos pedidos cuyos dos equipos traen los dos bloques de mitad.
* Una columna por dato (córners, amarillas, rojas, tiros, tiros a puerta, faltas, fueras de juego, posesión, paradas, xG): el
  porcentaje de partidos pedidos que traen ese dato **en las dos mitades y para los dos equipos**. Un valor vacío (`null`) o
  ausente cuenta como **no entregado**, nunca como cero (la regla de PM-05-01).
* **Decisión por dato:** «construir» (C) si llega al 90 % con al menos 5 partidos; «no construir» (N) si no; «-» sin muestra.
  El 90 % es el criterio de aceptación de PM-05-01.
* «1T + 2T = partido»: en los tipos que se cuentan, cuántas veces la suma de las mitades da el total del partido.

### 1.4 Cierre (día 7, jueves 26-nov-2026, después de la ejecución de las 12:10 UTC)

```
docker exec predigol-worker python -m scripts.coverage_probe half plan
docker exec predigol-worker python -m scripts.coverage_probe half report
docker exec predigol-worker python -m scripts.coverage_probe half report --json
docker exec predigol-worker python -m scripts.coverage_probe half report --league 13 --since 2026-08-01
```

y, para contrastar el gasto con el libro (solo lectura):

```
docker exec predigol-postgres psql -U postgres -d fbi -c "SET default_transaction_read_only=on" -c "SELECT started_at::date, count(*), sum(api_calls), sum(payloads_stored), string_agg(DISTINCT status, ',') FROM raw.ingestion_runs WHERE job_type = 'half_probe' GROUP BY 1 ORDER BY 1"
```

La tabla de `half report` con su hora UTC es el informe final: va al documento de estado de PM. Con ella se decide el alcance
de PM-05-01 (qué competiciones y qué datos) y la regla de PM-05-03. Si `plan` aún dice que quedan partidos (`to_ask` > 0), se
hace una última ejecución `run` antes del informe.

## 2. PM-01-04 · `/odds` donde la bandera y la base discrepan

**Qué mide.** Las 21 competiciones del 19-nov-2026 en que la bandera `odds` de `/leagues` y la base no coinciden (17 con
`odds: false` y cuotas en la mitad o más de sus partidos; 4 con `odds: true` y en menos de la mitad). Para cada una:

* la base de los últimos 30 días (0 peticiones): partidos terminados, cuántos pidió la captura (`market.odds_asks`), cuántos
  respondieron con cuotas y cuántos tienen cierre (`market.final_prematch_odds`);
* hoy: **una** página de `GET /odds?league=&season=` por competición y `GET /odds?fixture=` de hasta tres partidos con saque
  **en menos de 48 h** (para no leer un partido sin ventana de cuotas abierta y concluir de más). Primero van las 21 páginas;
  después los partidos, una competición cada vez por turno, de modo que el tope de **60 peticiones** recorta partidos y nunca
  deja una competición sin leer.

Cada competición queda con una causa: `bandera_falsa_publica` (la bandera dice que no y el proveedor sí publica),
`no_se_pidio` (la captura no pidió la mayoría de los partidos), `no_publica` (se pidieron y el proveedor respondió sin cuotas),
`coincide` (ya no discrepan) o, sin partidos ni respuesta, `sin_evidencia`.

**Las respuestas de `/odds` de esta sonda NO se guardan en RAW** (`persist=False`): una respuesta indexada la leería el extractor
de cuotas y se convertiría en precios, y una sonda no debe cambiar lo que deja la captura. La evidencia es el informe impreso
(guárdalo con su hora UTC).

```
docker exec predigol-worker python -m scripts.coverage_probe odds --max-requests 60
docker exec predigol-worker python -m scripts.coverage_probe odds --max-requests 60 --json   # el detalle, si hace falta
```

La segunda línea gasta otra vez: úsala solo en lugar de la primera. Repetición una semana después (jueves 26-nov o viernes
27-nov), en tres competiciones: `… coverage_probe odds --league 3 --league 18 --league 299 --max-requests 12`.

## 3. Vuelta atrás

No hay nada que revertir: las lecturas no cambian ningún dato. Para parar la medición basta con no ejecutar el guion. Las
respuestas en RAW y sus filas de índice se quedan (no se borran); no las lee ningún trabajo del worker. El código se retira con
un `revert` del PR.
