# Migración histórica desde API-Football

**Fecha:** 25 sep 2026 · **Código:** `src/fbi/migration/`, `src/fbi/ingestion/backfill.py`,
`config/migration.yaml`, `scripts/migration.py`, `scripts/probe_plan.py` · **Esquema:**
Alembic 0022 (detalle de partido), 0023 (unidades de migración), 0024 (registro).

Todo lo que sigue se calcula **antes** de gastar una sola petición: `python -m scripts.migration
plan|capacity` lee la configuración y la base de datos y no llama al proveedor.

## 1. Objetivo

Construir el histórico que los modelos necesitan para salir de RESEARCH y que el producto necesita
para Match Center, Analytics y los perfiles de jugador:

- **72 competiciones** (las ~70 mejores pedidas) en tres tiers, **hasta 9 temporadas** cada una:
  8 completadas (2018/19–2025/26) + la actual (2026/27), cuando el proveedor las tiene.
- **Primero lo que los modelos necesitan** (fixtures, resultados, estadísticas, eventos,
  alineaciones, lesiones), después lo que las páginas necesitan (clasificaciones, equipos) y,
  solo si se pide, lo opcional (perfiles de temporada de jugadores).
- **Resumible:** "se puede apagar el PC y continuar mañana". Cada unidad de trabajo es una fila
  con estado; nada depende de la memoria del proceso.

## 2. Inventario de endpoints y clasificación

| Unidad | Endpoint | Clasificación | Por qué | Peticiones |
|---|---|---|---|---|
| `league_coverage` | `/leagues` | MODEL_REQUIRED | los flags de cobertura por temporada deciden todas las demás unidades; una llamada devuelve todas las ligas y el nombre del proveedor para cada id | 1 |
| `fixtures_season` | `/fixtures?league&season` | MODEL_REQUIRED | fixtures, marcadores (HT, prórroga, penaltis), sede, estado: la temporada entera en una respuesta | 1 por competición-temporada |
| `fixture_details` | `/fixtures?ids=` (≤ 20) | MODEL_REQUIRED | eventos, alineaciones, estadísticas de equipo y de jugador de 20 partidos en una petición | 1 por 20 partidos (4 por partido sin batching) |
| `injuries_season` | `/injuries?league&season` | MODEL_REQUIRED | ausencias para la fuerza sensible a la alineación; el proveedor las tiene desde abril de 2021 | 1 por competición-temporada ≥ 2020 |
| `standings_season` | `/standings` | PRODUCT_REQUIRED | tablas finales para Analytics; derivables de resultados, se guardan por linaje | 1 |
| `teams_season` | `/teams?league&season` | PRODUCT_REQUIRED | identidad de equipos y sedes por temporada | 1 |
| `players_season` | `/players?league&season&page` | OPTIONAL | perfiles y totales de temporada (20 por página, ~36 páginas); las estadísticas por partido ya llegan con `fixture_details` | ~36 |
| — | `/predictions` | NOT_NEEDED | pronósticos del proveedor, 1 petición por partido; no es un baseline en el que confiemos más que en el mercado | — |
| — | `/players/topscorers…` | NOT_NEEDED | derivables de las estadísticas por partido | — |
| — | `/odds` | NOT_AVAILABLE | el proveedor guarda 7 días de cuotas pre-partido y ninguna en vivo: **el histórico de cuotas viene de Football-Data.co.uk** (ya importado: 345.964 cuotas, 5.329 partidos) | — |

Fuente de cada hecho del proveedor (lotes de 20, paginación, fechas de inicio, retención):
`docs/research/notes/A5_api_football_inventory.md` (documentación oficial v3.9.3, leída el 25 sep
2026).

## 3. Alcance: tiers, competiciones y profundidad

| Tier | Qué | Competiciones |
|---|---|---|
| 1 | Top-5 + Champions League | Premier League, La Liga, Bundesliga, Serie A, Ligue 1, UEFA Champions League (6) |
| 2 | Secundarias relevantes y copas europeas | Europa League, Championship, Eredivisie, Primeira Liga, Jupiler Pro League, Serie B, 2. Bundesliga, Segunda División, Ligue 2, Brasileirão, Liga Profesional Argentina, Liga MX, MLS, Allsvenskan, Eliteserien, Superliga (DK), **Süper Lig, Premiership (SCO), Bundesliga (AUT), Super League (SUI), Super League 1 (GRE), Czech Liga, HNL, Premier League (UKR), J1 League, Saudi Pro League, A-League, Conference League, Libertadores, Sudamericana** (30) |
| 3 | Cola larga del catálogo | Serie B (Brazil), 3. Liga, Eerste Divisie, Segunda Liga, Ekstraklasa, Superettan, Primera Nacional, Challenger Pro League, Primera A (Colombia), Primera Division (Chile), Liga I, Super Liga (Serbia), K League 1, Thai League 1, National 1, USL Championship, Liga de Expansion MX, Primera B (Chile), Primera Division (Uruguay), Primera Division (Peru), Premier Soccer League, K League 2, I Liga, 1. Division (Norway), 1. Division (Denmark), Liga II, Prva Liga, Primera B (Colombia), Segunda Division (Uruguay), Segunda Division (Peru), 1st Division (South Africa), Thai League 2, Primera Division (Venezuela), Segunda Division (Venezuela), 2. Division (Denmark), K3 League (36) |

- Los 14 añadidos en negrita no estaban en el catálogo heredado (77 competiciones). Sus ids son
  los publicados por el proveedor y **se comprueban, no se confían**: la primera unidad
  (`/leagues`) guarda el nombre del proveedor para cada id y `scripts.migration plan` imprime
  todo id cuyo nombre no coincide ("NAME CHECK") antes de sembrar el tier 2.
- **Profundidad:** objetivo 8 temporadas completadas + la actual. La selección final la deciden
  los flags de cobertura reales: una temporada sin cobertura de estadísticas no se consulta para
  ellas, y una competición con menos temporadas se muestra con las que tiene (3, 5, 10…). Hoy,
  sin `/leagues`, **las 648 competición-temporadas figuran como `unverified`**.
- Ya almacenado (no se vuelve a pedir la lista de fixtures): 5 ligas top × 2022–2024 y la
  Champions 2022–2024, con resultados. Sus **detalles** (eventos, alineaciones, stats) sí se
  piden: no los tenemos.

## 4. Coste estimado (antes de comprar)

`python -m scripts.migration capacity` · margen de seguridad **35 %** sobre cada estimación ·
**10 %** de la cuota diaria nunca lo toca el backfill · reserva adicional para la operación en
vivo calculada en cada ejecución.

| Escenario | Competición-temporadas | Partidos | Peticiones | Con margen 35 % |
|---|---|---|---|---|
| **Tiers 1–3, con `ids=`** (documentado) | 648 | 191.457 | **12.139** | 16.388 |
| Tiers 1–3, con `ids=` + opcionales (jugadores) | 648 | 191.457 | 35.467 | 47.881 |
| Tiers 1–3, **sin** `ids=` (4 por partido) | 648 | 191.457 | 768.261 | 1.037.153 |
| Tier 1, sin `ids=` | 54 | 18.396 | 73.773 | 99.594 |
| Tiers 1–2, sin `ids=` | 324 | 99.279 | 398.325 | 537.739 |

Por tipo de unidad (tiers 1–3, con `ids=`): `league_coverage` 1 · `fixtures_season` 632 ·
`fixture_details` 9.706 · `standings_season` 648 · `injuries_season` 504 · `teams_season` 648.
Por tier: T1 1.119 · T2 5.142 · T3 5.877.

**Almacenamiento:** ~1,34 GB de payloads comprimidos (1,8 GB con opcionales); en PostgreSQL
~30 KB por partido normalizado (≈ 5,7 GB para 191.457 partidos, estimado). El tamaño del
payload de detalle (7 KB/partido comprimido) es **una estimación** hasta el primer `ids=` real:
`scripts.probe_plan` lo mide.

La duración por plan, la operación en vivo y la recomendación están en
`API_PLAN_CAPACITY_MODEL.md`.

## 5. Unidades resumibles

Tabla `raw.backfill_tasks` (0016, ampliada en 0023): una fila por unidad con `provider`, `kind`,
`endpoint`, `params`, liga, temporada, `page`, `batch_key` (los 20 ids de un lote), `tier`,
`plan_id`, `priority`, `status` (`pending`/`running`/`done`/`failed`), `attempts`, `retryable`,
`started_at`, `completed_at`, `rows_written`, `requests_spent`, `last_payload_hash`,
`last_error`. Índice único por `(provider, kind, liga, temporada, page, batch_key)`: sembrar dos
veces no duplica nada.

- **Orden:** por `priority` (tier primero, luego tipo: cobertura → fixtures → detalles →
  clasificaciones/lesiones/equipos → opcionales).
- **Expansión:** una unidad `fixtures_season` completada crea sus lotes `fixture_details` de 20
  con los ids reales del proveedor; la página 1 de `players_season` crea las restantes.
- **Caída del proceso:** una unidad `running` durante más de 30 minutos se considera huérfana y
  se reanuda; los fallos reintentables se reintentan hasta 3 veces; un rechazo del plan se marca
  y no se reintenta a ciegas.
- **Idempotencia:** cada payload se guarda con su hash; reaplicar un payload o volver a correr no
  cambia ninguna fila (comprobado en el dry run).
- **Cuota:** cada petición pasa por el contador persistente (`raw.provider_quota`, el mismo que
  usa el worker) y el backfill nunca gasta la reserva de la operación en vivo. La cuota del
  proveedor se reinicia a las 00:00 UTC; si se agota, la cuenta queda suspendida el resto del día
  (términos del proveedor): por eso el techo propio.

## 6. Pruebas antes de pagar

### 6.1 Dry run de extremo a extremo (hoy, 25 sep 2026)

`python -m scripts.migration dry-run`: base de datos temporal migrada desde cero, cliente real,
almacén raw real, normalizadores reales y el motor real contra un HTTP falso; se interrumpe a sí
mismo, reanuda, reproduce y se borra.

```
scratch database fbi_dryrun_50a51984df (dropped); 30 fake requests; 7 unit kinds
  PASS  every unit completed                      ({'done': 30})
  PASS  API: one request per unit                 (30 requests made, 30 recorded on units)
  PASS  LEDGER: runs account for every request    (ingestion runs recorded 30)
  PASS  QUOTA: the persistent counter saw every request (raw.provider_quota spent 30)
  PASS  RESUME: a unit left running by a dead process was finished
  PASS  RAW+HASH: every payload file re-hashes to its recorded hash (30 payloads, 0 mismatched)
  PASS  NORMALISED: every fixture, result and detail block landed (fixtures=120, results=120,
        team_stats=240, events=405, lineups=240, lineup_players=3360, player_stats=3360,
        standings=24, absences=12, coverage=4)
  PASS  IDEMPOTENCY: replaying every payload and running again changes nothing
  PASS  every unit kind exercised
DRY RUN OK
```

También en la suite de integración (`tests/integration/test_migration_dryrun.py`).

### 6.2 La sonda previa a la compra (2 peticiones, plan Free)

`python -m scripts.probe_plan --yes` responde las dos preguntas de las que depende el plan:

1. **¿Devuelve `/fixtures?ids=` los bloques de detalle en esta cuenta?** La documentación lo da
   para todos los planes; un post oficial (27 jul 2026) dice "when available for your plan". Con
   batching el detalle cuesta 1 petición por cada 20 partidos; sin él, 4 por partido (el total de
   la migración pasa de 12.139 a 768.261 peticiones, ×63). Si los
   bloques vuelven en Free, vuelven en un plan de pago. Además mide el payload real.
2. **¿Qué cubre de verdad el proveedor?** `/leagues` en una petición: todas las ligas, todas las
   temporadas, sus flags y sus nombres → el plan pasa de `unverified` a `verified` y el "NAME
   CHECK" revisa los 72 ids.

Ambos payloads quedan guardados e indexados (linaje) y las dos peticiones pasan por la misma
cuota persistente que el worker. **Pendiente de ejecutar en la máquina** (la clave vive solo en
su `.env`; este entorno no tiene ninguna).

## 7. Runbook tras activar el plan

```
# 0. el plan: GET /status (gratis)             python -m scripts.capture_odds status
# 1. ajustar la cuota                           FBI_APIFOOTBALL_PLAN=<pro|ultra|mega> y FBI_APIFOOTBALL_DAILY_BUDGET
#                                               en .env; reiniciar el worker (un solo worker: el lock lo garantiza)
# 2. precio con cobertura real                  python -m scripts.migration plan      (tras la sonda: "verified")
#                                               python -m scripts.migration capacity
# 3. sembrar tier 1 y correr                    python -m scripts.migration seed --tiers 1 --yes
#                                               python -m scripts.migration run --yes --max 2000   (repetible)
#                                               (el worker también avanza el backfill cada hora en planes de pago)
# 4. vigilar                                    python -m scripts.migration status   · Analytics → Migration
# 5. validar calidad del tier                   §8
# 6. features, entrenamiento, walk-forward      python -m scripts.build_features --apply
#                                               python -m scripts.run_backtest --apply
#                                               python -m scripts.experiment reproduce <id>
# 7. comparar con el mercado y registrar        Models Lab · Analytics → Models
# 8. sembrar tiers 2 y 3 (tras el NAME CHECK)   python -m scripts.migration seed --tiers 2 --yes …
```

## 8. Validación de calidad por tier (antes del siguiente)

- Cada `fixtures_season` terminado: nº de partidos contra el del proveedor (`paging`/`results`) y
  contra la clasificación (partidos jugados).
- Resultados: 0 partidos `finished` sin fila de resultado; goles de eventos = marcador final
  (excepto partidos adjudicados).
- Estadísticas: tiros a puerta ≤ tiros; posesión local + visitante = 100 ± 1; donde existan ambas
  fuentes, la discrepancia API-Football vs Football-Data se **mide** (no se asume).
- Alineaciones: 11 titulares por lado; minutos de jugadores coherentes con cambios y rojas.
- Linaje: toda fila normalizada apunta a un payload cuyo fichero re-hashea a su hash
  (`scripts.backup restore-test` lo comprueba en una copia).
- Data Quality y Analytics → Coverage muestran la cobertura por competición-temporada.

## 9. Riesgos y mitigación

| Riesgo | Mitigación |
|---|---|
| `ids=` no disponible en el plan | la sonda lo detecta antes de pagar; ruta de upgrade (Pro→Ultra/Mega) a precio diferencial, sin downgrade posible |
| Ids de competición erróneos | NAME CHECK contra `/leagues` antes de sembrar |
| Temporadas antiguas sin cobertura | los flags reales deciden; se muestra la profundidad real por competición |
| Agotar la cuota y quedar suspendido | techo propio persistente + reserva para el vivo + margen 35 % |
| Caídas del PC / de la red | unidades resumibles; `running` huérfano se reanuda a los 30 min |
| Cambios del proveedor (formato, límites) | payload crudo guardado siempre: se puede re-normalizar sin volver a pedir |
| Discrepancias entre fuentes de estadísticas | precedencia explícita (API-Football > Football-Data) y medición de la discrepancia |
