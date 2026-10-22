# Football Intelligence Platform — V2

Plataforma privada, **local-first**, para análisis de fútbol y evaluación honesta de valor
en mercados de apuestas. No custodia dinero, no publica picks y no promete rentabilidad.

Reconstrucción del sistema auditado en `football-bot/docs/rebuild/`. La auditoría concluyó, entre
otras cosas, que el sistema anterior nunca midió rentabilidad (guardaba *accuracy* en una columna
llamada `roi_pct`), que su histórico de cuotas no existía (un `UNIQUE` sin componente temporal
sobrescribía cada precio) y que 128 de sus 152 calibradores no tenían validación.
Esta versión no arregla esos fallos con disciplina: los hace **imposibles en el esquema**.

El estado real, con evidencia, está en `docs/rebuild/V2_IMPLEMENTATION_STATUS.md`.

## Principios que el código impone, no sugiere

| Principio | Cómo se impone |
|---|---|
| Una cuota nunca se sobrescribe | `captured_at` forma parte de la clave primaria de `market.odds_snapshots` |
| No hay calibrador sin holdout **temporal** | `n_val >= 100` y `CHECK (val_from > train_to)` |
| Un ROI sin apuestas es NULL, no cero | `CHECK (roi_pct IS NULL OR total_stake_units > 0)` |
| Ningún pick seleccionado sin precio | `CHECK (decision <> 'selected' OR market_odds IS NOT NULL)` |
| Ninguna decisión usa información posterior | `CHECK (data_cutoff_ts <= odds_captured_at)`; el backtest comprueba cada bloque y un test reescribe el futuro y exige predicciones pasadas idénticas |
| **Ningún snapshot propio se llama "cierre" sin evidencia** | no existe columna `closing_*` ni `clv_*`; `is_validated_close` exige `close_validation_method`. El `closing` del histórico es la etiqueta de la fuente externa, guardada aparte |
| Un pick no se publica | `CHECK picks_publishing_disabled`: ningún pick puede estar `published` ni en modo distinto de `shadow` |
| Un modelo no "califica" sin batir al mercado | la regla exige que **esa versión exacta** tenga veredicto `better` frente al mercado sin margen en ≥ 1000 partidos de backtest |
| Un solo worker por base de datos | advisory lock de PostgreSQL; un segundo worker sale con código 75 y dice quién tiene el lock |

La suite (unos 1 640 tests, la mayoría contra un PostgreSQL real construido solo con las
migraciones) lo demuestra. Si un test de invariante falla, el esquema ha regresado: no se
arregla el test.

## Qué hay

```
API-Football ─▶ ingesta (fixtures · resultados · cuotas) ─▶ raw store (.json.gz + hash)
            ─▶ PostgreSQL (76 migraciones) ─▶ historial de cuotas + consenso de mercado sin margen
            ─▶ features point-in-time ─▶ modelos (Poisson, Dixon-Coles, Elo + logit ordenado)
            ─▶ backtest walk-forward contra el mercado ─▶ value engine ─▶ shadow picks ─▶ liquidación
            ─▶ API de producto /api/v1 (solo lectura) ─▶ frontend (repo football-intelligence-hub)
            ─▶ analista IA (herramientas con procedencia) · notificador (Telegram opcional)
```

## Arranque

Primera vez:

```bash
cp .env.example .env          # y pon tu FBI_APIFOOTBALL_KEY
python -m venv .venv && source .venv/bin/activate
pip install -e ".[dev,analytics]"
docker compose up -d postgres  # sin perfil solo arranca postgres
alembic upgrade head
make check                    # ruff + mypy + pytest
```

El repo debe vivir en el sistema de ficheros de Linux (`~/projects/...`), **nunca** en `/mnt/c/...`:
en WSL2 el I/O a través de 9P es entre 5 y 20 veces más lento y se nota en cada `pytest`.

Después, **uno** de los dos modos — nunca los dos a la vez:

| | Modo host (el habitual) | Modo compose |
|---|---|---|
| Arrancar | `scripts/dev-up` | `make up` |
| Parar | `scripts/dev-down` | `make down` |
| Estado | `scripts/dev-status` | `docker compose ps` · `scripts/dev-status` |
| Dónde corre | API, worker y web como procesos en WSL; PostgreSQL en Docker | PostgreSQL, API y worker en contenedores; web en el host (`bun run dev`) |

Los dos comparten la base de datos (volumen `pgdata`) y el raw store (`./data/raw`), así que
cambiar de modo no pierde nada. Si aun así hubiera dos workers, el segundo se niega a arrancar.

`scripts/dev-up` comprueba la base de datos (arranca Docker Desktop si hace falta) y el esquema:
si está por detrás no arranca nada; con `--migrate` primero hace `pg_dump` a `~/backups` y solo
entonces migra. Acepta un subconjunto: `scripts/dev-up api web`. Logs y pids en `~/.fbi`.

`make up` construye la imagen en el commit actual (queda en `FBI_CODE_VERSION`), comprueba el
esquema y arranca el perfil `stack`. La imagen no contiene `.env` ni `.git` ni `data/`.

## Comandos

```
scripts/dev-up [--migrate] [api] [worker] [web]    modo host
scripts/dev-down [api] [worker] [web]
scripts/dev-status
make up · make down · make logs · make image        modo compose
make schema      ¿está la base de datos en la última migración?
make migrate     alembic upgrade head (haz antes un backup)
make check       ruff + mypy + pytest
make capture     python -m scripts.capture_odds run --window auto
make report      python -m scripts.capture_odds report
make fresh CONFIRM=wipe   BORRA el volumen de la base de datos y la reconstruye
```

Antes de gastar una sola llamada de API:

```bash
python -m scripts.capture_odds plan     # muestra qué se capturaría. No llama a nadie.
```

Trabajo de investigación, a mano y solo sobre base de datos (cero requests):

```bash
python -m scripts.import_historical_odds --apply   # cuotas históricas de Football-Data.co.uk
python -m scripts.run_backtest --apply             # walk-forward contra el mercado (árbol limpio)
python -m scripts.pipeline --apply                 # forecasts, shadow picks, liquidación (sin --apply: en seco)
```

## Estructura

```
src/fbi/
  core/          reloj, configuración por dominio, logging con redacción, versión de código
  providers/     abstracción de proveedor + API-Football + rate limit + circuit breaker
  ingestion/     raw store inmutable, ledger de jobs, fixtures, resultados, backfill, replay
  odds/          cadencia de captura, persistencia, particiones
  market/        consenso de mercado sin margen (shin · proporcional · power)
  features/      feature store point-in-time
  models/        Poisson, Dixon-Coles, Elo + logit ordenado, scoring de mercados
  backtesting/   walk-forward, evaluación contra baselines, persistencia de sesiones
  predictions/   forecasts en tiempo real
  picks/         value engine, reglas versionadas, ciclo de vida, liquidación a 90 minutos
  analyst/       herramientas del analista IA y el bucle LLM → herramientas
  notify/        eventos → audit.notifications → Telegram (si hay token)
  api/           API de producto /api/v1, solo lectura
  ops/ quality/  heartbeat, lock del worker, /health y calidad de datos
  ai/            capa de decisión de IA (docs/ai/AI_DECISION_LAYER.md)
  auth/          personas, roles y sesiones
  catalog/       catálogos de referencia: competiciones, temporadas, casas de apuestas, mercados
  competitions/  estructura de competición: temporadas, fases, etapas y las tablas que las ordenan
  datasets/      versiones de dataset: de qué pueden aprender los modelos
  domain/        el dominio: números con significado
  intel/         PrediGol Intelligence: calibración por mercado y capa de decisión
  migration/     migración histórica: plan (precio antes de gastar), unidades semilla, ejecución reanudable
  parlays/       combinadas construidas solo con selecciones que aportan valor por sí solas
  research/      registro de investigación: experimentos, artefactos y la puerta de modelos
  storage/       modelos y repositorios de almacenamiento
  truth/         verdad de datos: el proveedor contra la base de datos, y la base contra sí misma
  userdata/      registros del usuario: picks guardados, combinadas construidas e historial
  validation/    si los datos guardados sirven para entrenar, juzgar un modelo o mostrarse
apps/            api · worker · bot (paquete vacío: solo __init__.py, sin código ni referencias)
migrations/      76 revisiones Alembic
tests/           unitarios + integración contra PostgreSQL real
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

En el plan Free solo se ven los partidos a ±1 día, así que T−72h y T−48h son inalcanzables y
no se simulan.

Lo que sale de ahí a T−12 es un `near_close_snapshot`. **No es la línea de cierre**, y este
código no lo llama así. Se rotulará CLV cuando alguien demuestre que coinciden y registre cómo
lo demostró.

## Configuración

Las ligas activas son configuración (`config/competitions.yaml`, aplicado con
`python -m scripts.manage_competitions apply`, que marca `core.competitions.is_tracked`),
nunca constantes en el dominio. El sistema anterior tenía nueve ids de liga repartidos por cinco
ficheros.

La clave de API viaja en la cabecera `x-apisports-key`, jamás en una URL, y nunca llega al
navegador: el frontend solo habla con la API de producto. Antes de escribir en disco o en un log,
todo parámetro cuyo nombre contenga `key`/`token`/`secret`/`password`/`authorization` se sustituye
por `[REDACTED]`, y las cadenas de log se filtran por patrones de credenciales. Hay tests que lo
comprueban; si fallan, para y rota la clave antes de hacer nada más.

Opcionales, solo en el host: `FBI_ANALYST_API_KEY` + `FBI_ANALYST_MODEL` (analista IA) y
`FBI_TELEGRAM_BOT_TOKEN` + `FBI_TELEGRAM_CHAT_ID` (notificaciones). Sin ellas, el analista dice
que no está configurado y los mensajes quedan como `skipped`.
