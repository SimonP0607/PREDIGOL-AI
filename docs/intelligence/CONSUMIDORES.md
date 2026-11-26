# Mapa de consumidores (RP-0.3)

<!-- Generado por `python -m scripts.consumers_map` desde el código de main. No lo edites a mano. -->

Quién lee o escribe cada tabla y cada versión que el plan conserva, consolida o retira. Encuentra **nombres** en el código (de tabla, de versión, de interruptor); no sigue llamadas, así que un módulo que llega a una tabla por una función que no escribe su nombre no aparece. Por eso la guarda de la prueba (un consumidor nuevo de algo marcado para retirar o consolidar la rompe) es un suelo, no una prueba de ausencia. Los archivos de prueba se cuentan aparte y no cuentan como consumidores.

| Candidato | Destino | Archivos | Sin pruebas | Escriben | Rutas | Trabajos | Web | Scripts |
|---|---|---|---|---|---|---|---|---|
| decision-v1 (referencia estable) (`decision_v1`) | conservar | 121 | 69 | 0 | 10 | 3 | 1 | 9 |
| decision-v2 en sombra (`decision_v2`) | consolidar | 98 | 56 | 1 | 8 | 6 | 0 | 1 |
| decisiones de familias (decision-fam-v1) (`decision_families`) | consolidar | 69 | 36 | 2 | 7 | 1 | 5 | 1 |
| ciclo de evaluación E1 a E4 (`eval_cycle`) | consolidar | 21 | 14 | 1 | 4 | 2 | 0 | 0 |
| ciclo de estados de la selección (`lifecycle`) | consolidar | 23 | 15 | 1 | 4 | 1 | 0 | 1 |
| forecast-v1 (cifra por modelo) (`forecast_v1`) | consolidar | 68 | 35 | 1 | 10 | 0 | 0 | 7 |
| forecast-v2 (cifra única) (`forecast_v2`) | conservar | 33 | 19 | 0 | 5 | 0 | 0 | 2 |
| circuito de noticias: news.items (`news_items`) | consolidar | 31 | 20 | 2 | 2 | 1 | 1 | 2 |
| almacén de evidencia: ai.evidence (`evidence`) | conservar | 176 | 105 | 2 | 17 | 2 | 1 | 5 |
| texto de los lectores (user-narrative-v3) (`user_narrative`) | consolidar | 25 | 14 | 0 | 4 | 1 | 3 | 0 |
| resumen del partido (brief-v8) (`brief_v8`) | consolidar | 29 | 15 | 0 | 0 | 0 | 3 | 0 |
| crónica única (chronicle-v4) (`chronicle_v4`) | conservar | 36 | 25 | 1 | 4 | 3 | 0 | 3 |
| extractor de investigación v1 (`extract_v1`) | consolidar | 23 | 14 | 0 | 0 | 0 | 0 | 1 |
| investigación v2 (extract-v3) (`extract_v3`) | consolidar | 35 | 19 | 0 | 1 | 0 | 0 | 1 |
| extractor nuevo en cuarentena (extract-v2) (`extract_v2`) | consolidar | 23 | 13 | 0 | 0 | 0 | 0 | 1 |
| investigación unificada (`unified_research`) | consolidar | 14 | 10 | 0 | 0 | 0 | 0 | 0 |
| brazo de comparación multiagente ma-v1-h (`haiku_arm`) | retirar | 86 | 47 | 0 | 6 | 1 | 8 | 3 |
| informe diario ai.shadow_reports (filas not_configured) (`shadow_reports`) | retirar | 10 | 6 | 1 | 2 | 0 | 0 | 0 |
| revisiones del modelo de lenguaje sobre candidatos (`pick_reviews`) | retirar | 105 | 56 | 2 | 11 | 0 | 2 | 3 |
| modelos experimentales hgb y hgb_market (`hgb`) | retirar | 7 | 4 | 0 | 1 | 0 | 0 | 0 |

## decision-v1 (referencia estable) (`decision_v1`) — conservar

Paquetes: `ai` (2), `api` (10), `apps` (1), `core` (2), `council` (1), `decision` (8), `evalcycle` (5), `evalpass` (1), `evaluation` (1), `familydecisions` (1), `forecasting` (1), `ingestion` (1), `intel` (4), `knowledge` (1), `lifecycle` (3), `narrator` (1), `observability` (1), `picks` (1), `playermarkets` (1), `plugins` (2), `portfolio` (4), `research` (1), `scripts` (9), `shadowjobs` (2), `tracking` (1), `valuation` (3), `web` (1).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## decision-v2 en sombra (`decision_v2`) — consolidar

Paquetes: `ai` (3), `api` (8), `apps` (1), `chronicle` (1), `decision` (10), `evalcycle` (5), `evalpass` (1), `evaluation` (1), `forecasting` (3), `intel` (2), `lifecycle` (3), `ops` (1), `plugins` (5), `protosign` (1), `research` (1), `scripts` (1), `shadowjobs` (5), `tracking` (2), `valuation` (2).

Escriben: `backend/src/fbi/decision/shadow.py`.

## decisiones de familias (decision-fam-v1) (`decision_families`) — consolidar

Paquetes: `ai` (1), `api` (7), `apps` (1), `core` (1), `countcal` (1), `decision` (4), `familydecisions` (3), `intel` (2), `knowledge` (2), `lifecycle` (3), `memoryread` (1), `observability` (1), `plugins` (2), `research` (1), `scripts` (1), `web` (5).

Escriben: `backend/src/fbi/familydecisions/memory.py`, `backend/src/fbi/familydecisions/postmortem.py`.

## ciclo de evaluación E1 a E4 (`eval_cycle`) — consolidar

Paquetes: `ai` (1), `api` (4), `apps` (1), `chronicle` (2), `evalcycle` (4), `factlinks` (1), `lifecycle` (1).

Escriben: `backend/src/fbi/evalcycle/run.py`.

## ciclo de estados de la selección (`lifecycle`) — consolidar

Paquetes: `api` (4), `apps` (1), `countcal` (1), `decision` (1), `evalcycle` (1), `lifecycle` (4), `scripts` (1), `tracking` (2).

Escriben: `backend/src/fbi/lifecycle/store.py`.

## forecast-v1 (cifra por modelo) (`forecast_v1`) — consolidar

Paquetes: `ai` (2), `api` (10), `coverage` (3), `decision` (2), `families` (2), `familydecisions` (1), `forecasting` (5), `intel` (1), `research` (2), `scripts` (7).

Escriben: `backend/src/fbi/forecasting/match_forecast.py`.

## forecast-v2 (cifra única) (`forecast_v2`) — conservar

Paquetes: `api` (5), `chronicle` (5), `decision` (3), `forecasting` (3), `scripts` (2), `valuation` (1).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## circuito de noticias: news.items (`news_items`) — consolidar

Paquetes: `ai` (1), `api` (2), `apps` (1), `factlinks` (1), `ingestion` (1), `news` (7), `newsdesk` (2), `newsroom` (1), `proposals` (1), `scripts` (2), `web` (1).

Escriben: `backend/src/fbi/news/store.py`, `backend/src/fbi/newsroom/moderation.py`.

## almacén de evidencia: ai.evidence (`evidence`) — conservar

Paquetes: `ai` (41), `api` (17), `chronicle` (4), `decision` (1), `evalcycle` (3), `evalpass` (1), `evaluation` (2), `evidence` (4), `factlinks` (3), `ingestion` (1), `intel` (5), `narrative` (1), `news` (7), `observability` (1), `people` (2), `picks` (1), `players` (1), `proposals` (1), `research` (1), `scripts` (5), `shadowjobs` (2), `web` (1).

Escriben: `backend/src/fbi/ai/evidence.py`, `backend/src/fbi/people/identity/store.py`.

## texto de los lectores (user-narrative-v3) (`user_narrative`) — consolidar

Paquetes: `ai` (1), `api` (4), `chronicle` (3), `intel` (1), `narrative` (1), `protosign` (1), `web` (3).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## resumen del partido (brief-v8) (`brief_v8`) — consolidar

Paquetes: `ai` (9), `chronicle` (1), `intel` (1), `protosign` (1), `web` (3).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## crónica única (chronicle-v4) (`chronicle_v4`) — conservar

Paquetes: `ai` (3), `api` (4), `apps` (1), `chronicle` (12), `intel` (1), `protosign` (1), `scripts` (3).

Escriben: `backend/src/fbi/chronicle/v4_job.py`.

## extractor de investigación v1 (`extract_v1`) — consolidar

Paquetes: `ai` (12), `research` (1), `scripts` (1).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## investigación v2 (extract-v3) (`extract_v3`) — consolidar

Paquetes: `ai` (15), `api` (1), `intel` (1), `research` (1), `scripts` (1).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## extractor nuevo en cuarentena (extract-v2) (`extract_v2`) — consolidar

Paquetes: `ai` (12), `scripts` (1).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## investigación unificada (`unified_research`) — consolidar

Paquetes: `ai` (10).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## brazo de comparación multiagente ma-v1-h (`haiku_arm`) — retirar

Paquetes: `ai` (20), `api` (6), `apps` (1), `council` (3), `decision` (1), `intel` (3), `observability` (1), `research` (1), `scripts` (3), `web` (8).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).

## informe diario ai.shadow_reports (filas not_configured) (`shadow_reports`) — retirar

Paquetes: `ai` (4), `api` (2).

Escriben: `backend/src/fbi/ai/shadow.py`.

## revisiones del modelo de lenguaje sobre candidatos (`pick_reviews`) — retirar

Paquetes: `ai` (24), `api` (11), `budgeting` (1), `council` (1), `evalpass` (1), `intel` (6), `lifecycle` (3), `observability` (1), `picks` (1), `protosign` (1), `research` (1), `scripts` (3), `web` (2).

Escriben: `backend/src/fbi/ai/orchestrator_store.py`, `backend/src/fbi/ai/review.py`.

## modelos experimentales hgb y hgb_market (`hgb`) — retirar

Paquetes: `api` (1), `backtesting` (1), `research` (2).

Nadie la escribe por nombre de tabla en este mapa (puede ser una versión o un interruptor, no una tabla).
