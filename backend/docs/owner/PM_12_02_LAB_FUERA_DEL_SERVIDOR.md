# PM-12-02 · El LAB fuera del servidor: exportación de solo lectura con manifiesto (OPS-013)

Plan Maestro PM, tarea **PM-12-02** (OP-04), decisión **DM-02** del dueño (19-nov-2026). Los experimentos del LAB compiten con
producción por memoria y CPU; aquí se sacan **copias de solo lectura** de las tablas que un experimento necesita, en Parquet y con un
manifiesto, para trabajarlas en el portátil con DuckDB. **No añade llaves, roles, accesos ni tareas programadas**: el guion corre
dentro del worker con su conexión de siempre, abierta en solo lectura, y la copia baja al portátil por el SSH que ya existe.

No es el archivo frío del servidor ni una copia de seguridad: no sustituye a la copia diaria ni a la decisión D1 de seguridad (copia
fuera del servidor), y no mueve nada fuera salvo estas copias para el portátil del dueño.

## 1. Qué sale y qué no sale nunca

`scripts/lab_export.py` tiene una **lista cerrada** (`TABLES`, versión `lab-export-v1`) de 13 tablas de los esquemas `core`, `market`,
`models` y `analytics` (y `features`, permitido pero sin tablas hoy): competiciones, temporadas, equipos, partidos, resultados,
estadísticas de equipo, casas, familias y versiones de modelo, probabilidades guardadas y las sesiones, ejecuciones y muestras de los
backtests del LAB.

* **`auth` y `customer` no salen nunca**: el guion los rechaza por su nombre antes de preguntar nada a la base (y el rol del worker
  tampoco tiene acceso a esos esquemas: comprobado el 20-nov-2026). Tampoco puede nombrarse ninguna tabla fuera de la lista (`ai`,
  `picks`, `audit`, `intel`, `raw`…): es un error. Añadir una tabla es un PR que cambia la lista y su prueba.
* Las tablas grandes (partidos, resultados, estadísticas, probabilidades, muestras) **no salen enteras**: exigen un filtro
  (`--session N`, una sesión del LAB, o `--since AAAA-MM-DD`).
* La ficha nombraba `core`, `market`, `features` y `models`; se añadió `analytics` solo para las tres tablas de backtests, porque
  son las que permiten **reproducir** un experimento (sin datos de personas).

## 2. Cómo es una exportación

* **Una sola foto y ninguna escritura posible**: todo se lee en una transacción `REPEATABLE READ READ ONLY`, con
  `default_transaction_read_only` y `statement_timeout` de 300 s. Las filas se leen con un cursor del servidor, de 20.000 en 20.000,
  y se escriben a un Parquet por tabla (zstd): la memoria no crece con el tamaño de la tabla.
* **Tope de 5 GB** (`--max-bytes`, el espacio temporal de la ficha): se para antes de pasarlo y lo dice en el manifiesto.
* **No empieza entre las 03:30 y las 05:00 UTC** (PITR y copia diaria). Deja además 20 minutos alrededor de cada `fixtures_sync`
  (hoy a las 03:55, 09:55, 15:55 y 21:55 UTC; sus horas cambian: míralas antes) y evita las 07:20 UTC (pasada de estadísticas).
* **`manifest.jsonl`**, una línea JSON por objeto: `run` (hora, versión del código, foto de la base `pg_current_snapshot`, filtros,
  tablas), una línea `table` por archivo (filas, columnas con su tipo de Postgres y el de Parquet, bytes, **SHA-256**, la consulta
  exacta y sus parámetros) y `end` (totales y si se paró). Tipos: `numeric` se escribe como doble; `json`, `jsonb`, matrices y
  cualquier tipo no listado, como texto (JSON); nada se descarta.

## 3. Pasos (el dueño, o quien él designe, fuera de las ventanas)

En el servidor, dentro del worker (0 peticiones al proveedor):

```
docker exec -w /app predigol-worker python -m scripts.lab_export plan --session 4      # qué saldría y cuántas filas; no escribe nada
docker exec -w /app predigol-worker python -m scripts.lab_export run --session 4       # escribe /tmp/predigol-lab/<hora>/ en el contenedor
```

En el portátil (PowerShell), bajar la carpeta por el SSH de siempre y comprobarla:

```
$d = 'C:\Users\simon_zkmbj72\fbi_scratch\lab'
cmd /c "ssh -o BatchMode=yes predigol docker exec predigol-worker tar -C /tmp/predigol-lab -cf - <hora> > $d\<hora>.tar"
tar -xf "$d\<hora>.tar" -C $d
py -3.12 -m venv $d\venv ; & $d\venv\Scripts\pip install duckdb pyarrow      # una vez
& $d\venv\Scripts\python <repo>\backend\scripts\lab_export.py verify $d\<hora>
& $d\venv\Scripts\python <repo>\backend\scripts\lab_reproduce.py $d\<hora>
```

`verify` vuelve a calcular el SHA-256 de cada archivo contra el manifiesto (solo biblioteca estándar). `lab_reproduce` recalcula con
DuckDB, para cada ejecución de la sesión, el log loss y el Brier del 1X2 con las mismas fórmulas que `fbi.models.metrics` y los
compara con lo que el servidor guardó (tolerancia 2·10⁻⁵: las probabilidades se guardaron redondeadas a 6 decimales); comprueba
también que el resultado de cada muestra es el del partido.

## 4. La primera exportación y su reproducción (criterio de aceptación)

El experimento elegido es la **sesión 4 del LAB** (`research-v2-2024-20261004T111558Z`, 4-oct-2026):
ocho familias de modelo (Poisson, Dixon-Coles, Elo + logit ordenado, tasas base, logit multinomial, HGB, HGB con mercado y el
ensemble) evaluadas en walk-forward sobre las ligas de 2024-25 (15-ago-2024 a 29-may-2025), con su log loss y su Brier guardados en
`analytics.backtest_runs` (ejecuciones 20 a 27).

**Exportación** (20-nov-2026, 07:29:59–07:30:06 UTC, fuera de la copia, de `fixtures_sync` y tras la pasada de estadísticas; antes de
desplegar este PR, con su `scripts/lab_export.py` pasado al worker por la entrada estándar, SHA-256 del archivo `1335660f…5b82f3f`;
código desplegado `3338f788cc61`): `plan --session 4` y `run --session 4`. Foto `4624765:4624765:`, `repeatable read, read only`.
**13 tablas, 133.307 filas, 3,4 MB**, sin parar por el tope:

| Tabla | Filas | Bytes | SHA-256 (inicio) |
| --- | ---: | ---: | --- |
| core.competitions | 165 | 10.234 | `d01c57449cba` |
| core.competition_seasons | 1.906 | 20.171 | `5c1d1b0d272d` |
| core.teams | 8.325 | 326.330 | `e1657d0bc6da` |
| core.fixtures (sesión 4) | 1.756 | 39.263 | `88b13004443f` |
| core.fixture_results (sesión 4) | 1.756 | 21.043 | `b4fe34979d78` |
| core.fixture_team_stats (sesión 4) | 7.014 | 73.546 | `8e7a624c79ff` |
| market.bookmakers | 33 | 2.310 | `eb9590054269` |
| models.model_registry | 12 | 3.332 | `2a6d5a340666` |
| models.model_versions | 249 | 11.520 | `bb9373dcf114` |
| models.predictions (sesión 4) | 56.041 | 1.875.350 | `d543a295763b` |
| analytics.backtest_sessions (sesión 4) | 1 | 16.392 | `da632d337198` |
| analytics.backtest_runs (sesión 4) | 8 | 36.722 | `bbf2a0e055c5` |
| analytics.backtest_samples (sesión 4) | 56.041 | 987.591 | `18f0dbf623b5` |

**En el portátil** (07:31 UTC, `C:\Users\simon_zkmbj72\fbi_scratch\lab\20261120T072959Z\`, Python 3.12 con duckdb 2.0.0 y
pyarrow 26.0.0 de `constraints.txt` en un entorno propio de esa carpeta): `verify` → «every file matches the manifest»;
`lab_reproduce` → **las 8 ejecuciones reproducidas**, con el mismo número de partidos y el mismo log loss y Brier a seis decimales:

| Ejecución | Modelo | Partidos | Log loss (portátil = servidor) | Brier |
| ---: | --- | ---: | ---: | ---: |
| 20 | Poisson | 1.748 | 0,987084 | 0,588585 |
| 21 | Dixon-Coles | 1.748 | 0,987077 | 0,588579 |
| 22 | Elo + logit ordenado | 1.756 | 0,986186 | 0,588231 |
| 23 | Tasas base | 1.756 | 1,079748 | 0,654245 |
| 24 | Logit multinomial | 1.756 | 0,981762 | 0,584851 |
| 25 | HGB | 1.756 | 0,996625 | 0,592664 |
| 26 | HGB con mercado | 1.751 | 1,023697 | 0,602898 |
| 27 | Ensemble | 1.748 | 0,979279 | 0,583309 |

En ninguna muestra discrepa el resultado guardado del que da el partido (0 de 56.041), y cada partido tiene sus tres
probabilidades 1X2.

## 5. Vuelta atrás

No hay nada que revertir en el servidor: las lecturas no dejan rastro en la base. La carpeta de `/tmp/predigol-lab` vive en el
contenedor del worker y desaparece cuando el contenedor se recrea (el siguiente despliegue). En el portátil, la carpeta de
`fbi_scratch\lab` es una copia que el dueño conserva o borra cuando quiera. El código se revierte con un `revert` del PR.

## 6. `lab-export-v2` (IA-154, 21-nov-2026): las líneas del LAB del plan PM

Para PM-10-08, PM-08-07, PM-09-07 y PM-12-03 la lista cerrada crece en ocho tablas (versión `lab-export-v2`). Siguen fuera `auth`,
`customer` y todo lo que no esté en la lista; lo que es de personas sale **sin nombres, sin texto libre y sin identificadores
externos**: la tabla dice qué columnas salen (`columns`) y una prueba lo comprueba.

| Tabla | Para qué | Filtro | Columnas que salen |
| --- | --- | --- | --- |
| `core.fixture_events` | amarillas con jugador (apercibidos, PM-08-07) | `--since` obligatorio | ids del partido, equipo y jugador, minuto, tipo y detalle (sin nombres ni comentarios) |
| `core.fixture_lineups` | entrenador del partido (PM-08-07) | `--since` obligatorio | partido, lado, formación, ids del entrenador (sin nombre) |
| `core.fixture_officials` | árbitro designado (PM-08-07) | `--since` obligatorio | partido, papel, id del alias |
| `core.entity_aliases` | a qué persona apunta el alias de un árbitro | `--since` (solo alias de árbitros de esos partidos) | ids, tipo y origen del alias (sin el texto) |
| `core.entity_ids` | si la persona tiene identificador abierto | entera | tipo e id de la entidad, sistema, espacio, método, confianza, revisión (sin el identificador ni la evidencia) |
| `core.standings` | tabla del proveedor para descartar sanciones (PM-09-07) | `--since` obligatorio (temporadas con partidos desde esa fecha) | todas |
| `market.historical_odds` | cuotas de cierre de football-data.co.uk (PM-12-03) | entera | todas |
| `analytics.promoted_forecast_spec` | xi, penalización y ventana del modelo en vigor | entera | id, sesión, fecha y especificación |

La exportación de estas líneas es **una sola**: `run --since 2019-01-01`, fuera de la copia (03:30–05:00 UTC), a más de 20 minutos de
una `fixtures_sync` y lejos de las 07:20 UTC. Los protocolos que la leen (`PM-10-08`, `PM-08-07`, `PM-09-07`, `PM-12-03-OP26`,
`-OP27`, `-OP29`, `-OP30` en `fbi/research/protocol.py`) se registraron antes de tomarla. Vuelta atrás: la misma que arriba (un
`revert` devuelve la lista v1; las lecturas no dejan nada).
