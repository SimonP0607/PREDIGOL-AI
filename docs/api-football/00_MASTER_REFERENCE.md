# API-Football v3 — referencia maestra

**Extraído:** 29 sep 2026 de la documentación oficial (`api-football.com/documentation-v3`,
versión declarada **3.9.3**), el dashboard de la cuenta y el endpoint `/status` en vivo.
**Plan de la cuenta:** Ultra. **Clave:** `API_KEY=[REDACTED]` — nunca en estos documentos.

Este directorio responde nueve preguntas y nada más:

| Pregunta | Documento |
|---|---|
| Qué existe | `01_ENDPOINT_CATALOG.md` |
| Qué parámetros admite y cuáles se combinan | `02_PARAMETER_MATRIX.md` |
| Qué devuelve y cómo se enlaza | `03_RESPONSE_ENTITIES.md`, `04_RELATIONSHIP_MAP.md` |
| Cuánto histórico hay de verdad | `05_HISTORICAL_COVERAGE.md` |
| Cuándo se actualiza y cada cuánto preguntar | `06_UPDATE_FREQUENCIES.md` |
| Qué permite nuestro plan | `07_ULTRA_PLAN_LIMITS.md` |
| Cuánto cuesta en peticiones | `08_REQUEST_COST_MODEL.md` |
| Qué nos falta implementar | `09_V2_GAP_ANALYSIS.md` |
| Qué descargamos y qué consultamos en vivo | `10_BACKFILL_ENDPOINT_PLAN.md`, `11_LIVE_ENDPOINT_PLAN.md` |

Inventario legible por máquina: `endpoints.yaml` · `ENDPOINT_MATRIX.csv` · `12_API_FOOTBALL_ID_MAP.md`.

## 1. Lo esencial del contrato

- **Base:** `https://v3.football.api-sports.io/` · **solo GET**.
- **Cabecera:** `x-apisports-key`. La documentación es explícita: *"If you make non-GET requests
  or add headers that are not in the list, you will receive an error from the API"*. Algunos
  frameworks (JS/Node) añaden cabeceras solas y hay que quitarlas.
- **Códigos:** 200 · 204 No Content · 499 Time Out · 500.
- **Los errores llegan dentro de un 200** con el objeto `errors` poblado (cuota, plan, parámetro).
  Tratar eso como éxito es exactamente cómo el sistema heredado guardó días vacíos. Nuestro
  cliente ya lo rechaza (`client.py::_finalise`).
- **Sobre cada respuesta:** `get`, `parameters`, `errors`, `results`, `paging{current,total}`,
  `response[]`.
- **Cabeceras de respuesta:** `x-ratelimit-requests-limit` / `-remaining` (día) y
  `X-RateLimit-Limit` / `-Remaining` (minuto).
- **Política antiabuso, textual:** *"If you exceed your allowed request rate per minute, either
  through continuous excessive usage or by generating abnormal traffic spikes, your access may be
  temporarily or permanently blocked by our firewall without prior notice."* No es solo una
  cuota: un pico anómalo puede costar la cuenta. Nuestro limitador por minuto no es opcional.
- **`/status` no consume cuota.** Logos e imágenes tampoco, pero tienen límite por segundo.

## 2. Las siete verdades que cambian nuestro plan

1. **`/fixtures?ids=` devuelve el partido con `events`, `lineups`, `statistics` y `players`
   dentro.** Máximo 20 ids. Es la diferencia entre 1 petición por cada 20 partidos y 4 por
   partido. Verificado en nuestra cuenta el 29 sep: los cuatro bloques vuelven completos,
   **3,8 KB por partido** comprimido (la estimación previa era 7 KB).
2. **No hay histórico de cuotas y no lo habrá.** Pre-match: *"We provide pre-match odds between 1
   and 14 days before the fixture. We keep a 7-days history"*. In-play: *"No history is stored"*.
   El histórico de precios solo puede venir de fuera (Football-Data.co.uk).
3. **Las lesiones empiezan en abril de 2021.** *"Being a new endpoint, the data is only available
   from April 2021"*. Pedir `/injuries` de 2018–2020 es gastar peticiones para nada.
4. **Los eventos VAR empiezan en 2020-21** y las estadísticas por mitad (`half=true`) **en 2024**.
   Cualquier feature que dependa de ellos tiene una frontera temporal, no un hueco aleatorio.
5. **La cobertura es por liga Y por temporada, y `true` no garantiza nada.** Textual: *"The
   coverage of a competition can vary from season to season and values set to True do not
   guarantee 100% data availability"*. Además *"Some competitions, such as the friendlies, are
   exceptions to the coverage indicated in the leagues endpoint"*.
6. **`/fixtures` se actualiza cada 15 segundos**, pero *"Not all competitions have livescore
   available and only have final result. In this case, the status remains in NS and will be
   updated in the minutes/hours following the match (this can take up to 48 hours)"*. Nuestro
   detector de "awaiting result" está midiendo un fenómeno real del proveedor.
7. **3.9.3 añade campos que no capturamos:** `fixture.extra` (descuento jugado por mitad) y
   `league.standings` (booleano), más los endpoints `players/profiles` y `players/teams`.

## 3. Lo que NO vamos a usar, y por qué

| Cosa | Motivo |
|---|---|
| Widgets de API-SPORTS | exponen la clave en el navegador (`data-key`) y gastan cuota por visita. Nuestra UI consume nuestra propia FastAPI. Analizados solo para entender qué combina el proveedor. |
| `/predictions` | pronósticos del proveedor. Clasificado `RESEARCH_ONLY`: sirve como tercer punto de comparación (nuestro modelo vs mercado vs proveedor), nunca como fuente de nuestras probabilidades. |
| `/players/topscorers` y hermanos | derivables de las estadísticas por partido que ya bajamos. |
| CDN / Aiven / Firebase | recomendaciones comerciales del proveedor, no parte de la API. |

## 4. Procedencia

Todo lo citado aquí sale de la documentación oficial leída el 29 sep 2026 y de respuestas reales
de nuestra cuenta (`/status`, sonda `ids=`, `/leagues`). Donde un número es **medido** por
nosotros se dice; donde es **declarado** por el proveedor, también. No hay estimaciones sin
etiqueta.
