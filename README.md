# Football Intelligence Platform — V2

Plataforma privada, **local-first**, para análisis de fútbol y evaluación honesta de valor
en mercados de apuestas. No custodia dinero, no publica picks y no promete rentabilidad.

Reconstrucción del sistema auditado en `football-bot/docs/rebuild/`. La auditoría concluyó, entre
otras cosas, que el sistema anterior nunca midió rentabilidad (guardaba *accuracy* en una columna
llamada `roi_pct`), que su histórico de cuotas no existía (un `UNIQUE` sin componente temporal
sobrescribía cada precio) y que 128 de sus 152 calibradores no tenían validación.
Esta versión no arregla esos fallos con disciplina: los hace **imposibles en el esquema**.

## Principios que el código impone, no sugiere

| Principio | Cómo se impone |
|---|---|
| Una cuota nunca se sobrescribe | `captured_at` forma parte de la clave primaria de `market.odds_snapshots` |
| No hay calibrador sin holdout **temporal** | `n_val >= 100` y `CHECK (val_from > train_to)` |
| Un ROI sin apuestas es NULL, no cero | `CHECK (roi_pct IS NULL OR total_stake_units > 0)` |
| Ningún pick seleccionado sin precio | `CHECK (decision <> 'selected' OR market_odds IS NOT NULL)` |
| Ninguna decisión usa información posterior | `CHECK (data_cutoff_ts <= odds_captured_at)` |
| **Ningún snapshot se llama "cierre" sin evidencia** | no existe columna `closing_*` ni `clv_*`; `is_validated_close` exige `close_validation_method` |

Hay 108 tests que lo demuestran. Si uno falla, el esquema ha regresado: no se arregla el test.

## Arranque

```bash
cp .env.example .env          # y pon tu FBI_APIFOOTBALL_KEY
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,analytics]"

docker compose up -d postgres
alembic upgrade head
make check                    # ruff + mypy + pytest
```

El repo debe vivir en el sistema de ficheros de Linux (`~/projects/...`), **nunca** en `/mnt/c/...`:
en WSL2 el I/O a través de 9P es entre 5 y 20 veces más lento y se nota en cada `pytest`.

## Comandos

```
make up          postgres + api + worker
make migrate     alembic upgrade head
make test        pytest -q
make check       ruff + mypy + pytest
make capture     python -m scripts.capture_odds run
make report      python -m scripts.capture_odds report
make fresh       borra el volumen y reconstruye desde cero
```

Antes de gastar una sola llamada de API:

```bash
python -m scripts.capture_odds plan     # muestra qué se capturaría. No llama a nadie.
```

## Estructura

```
src/fbi/
  core/          reloj, configuración por dominio, logging, errores
  providers/     abstracción de proveedor + API-Football + rate limit + circuit breaker
  ingestion/     almacén inmutable de payloads crudos
  odds/          cadencia de captura, persistencia, particiones
  domain/        modelo de dominio            (pendiente)
  features/      feature store point-in-time  (pendiente)
  models/        registro, calibración        (pendiente)
  picks/         motor de decisión            (pendiente)
  backtesting/   walk-forward                 (pendiente)
apps/            api · worker · bot
migrations/      10 revisiones Alembic; el DDL validado, embebido literalmente
tests/           108 tests · unitarios + integración contra PostgreSQL real
```

## La cadencia de captura, y por qué es esa

```
prematch   /odds        T−72h · T−48h · T−24h · T−12h · T−6h · T−3h
near-close /odds/live   T−12min
```

`/odds` se refresca **cada 3 horas** y conserva 7 días. Una ventana por debajo de 180 minutos
devuelve la misma fila y gasta cuota: la configuración la rechaza por validación.
`/odds/live` es la única vista de un precio cerca del saque, y el proveedor lo publica entre
T−15 y T−5. **No conserva histórico**, así que cada día sin capturar es un día perdido para siempre.

Lo que sale de ahí a T−12 es un `near_close_snapshot`. **No es la línea de cierre**, y este
código no lo llama así. Se rotulará CLV cuando alguien demuestre que coinciden y registre cómo
lo demostró.

## Configuración

Las ligas activas son configuración (`FBI_ACTIVE_LEAGUES` + `core.competitions.is_tracked`),
nunca constantes en el dominio. El sistema anterior tenía nueve ids de liga repartidos por cinco
ficheros.

La clave de API viaja en la cabecera `x-apisports-key`, jamás en una URL. Antes de escribir en
disco o en un log, todo parámetro cuyo nombre contenga `key`/`token`/`secret`/`password`/
`authorization` se sustituye por `[REDACTED]`. Hay dos tests que lo comprueban; si fallan, para y
rota la clave antes de hacer nada más.
