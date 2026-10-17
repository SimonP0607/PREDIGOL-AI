# MASTER STATUS REPORT — Football Intelligence Platform V2

**Fecha:** 2026-09-23 · **Máquina:** `mila` (WSL2 Ubuntu 26.04 + Docker Desktop)
**Base del informe:** ejecución y consulta reales sobre esa máquina, no estimación.
Todo número de esta página se ha leído de PostgreSQL, de `git`, del proceso vivo o
de la salida de los tests en el momento de escribirla.

**Aviso de alcance, primero y sin rodeos:** de las 30 fases del mandato hay **5
completadas**. No me paró el entorno; me paró la sesión. Las fases 6–30 siguen
sin empezar, y una parte importante de ellas **no depende de datos** y podría
haberse escrito. Lo digo aquí arriba para que el resto del informe se lea con esa
escala en mente.

---

## 1. Arquitectura

Dos repositorios, deliberadamente separados:

```
football-intelligence-v2        backend, ingesta, dominio, worker, API
football-intelligence-hub       frontend (React 19 · TanStack Start · Vite 8)
```

El backend está por capas, y la capa de dominio no sabe que existe un proveedor:

```
apps/            api (FastAPI) · worker (APScheduler) · bot (vacío)
src/fbi/
  domain/        tipos puros: probabilidad, cuota, mercado, valor, unidades
  providers/     API-Football: cliente, rate limit, cuota, circuit breaker
  ingestion/     fixtures · resultados · payload store · ledger de runs
  odds/          planificador de ventanas · capturador · particiones
  catalog/       competiciones, temporadas, activación
  quality/       health y métricas de calidad
  features/ models/ predictions/ picks/ backtesting/     ← stubs vacíos
```

Flujo real hoy:

```
API-Football ──► ingestion ──► raw.ingestion_payloads (.json.gz + hash)
                     │
                     └──► core.fixtures / core.teams / core.competitions
                              │
                              ▼
                        market.odds_snapshots   ← VACÍO. Aquí se corta todo.
```

Todo lo que viene después de ese punto —features, modelos, baseline, picks—
existe como carpeta y como esquema de base de datos, y como nada más.

---

## 2. Backend

| | Estado | Evidencia verificada |
|---|---|---|
| PostgreSQL 16.15 (Docker, :5433) | ✅ | `running/healthy` |
| Alembic | ✅ | revisión **0013**, roundtrip up→down→up probado |
| Esquema | ✅ | **27 tablas** en `core`(10) · `market`(11) · `raw`(3) · `analytics`(3) |
| Particionado de odds | ✅ | `odds_snapshots_2026_09…12` creadas por el worker al arrancar |
| Proveedor API-Football | ✅ | clave solo en `.env`; 0 apariciones en disco, logs o git |
| Cuota diaria persistente | ✅ | `raw.provider_quota`, reserva atómica, probada entre 2 procesos OS reales |
| Ledger de runs | ✅ | `completed / partial / failed / aborted` + backfill 0013 |
| Fixtures sync | ✅ | estrategia `date` (la única que sirve el plan Free) |
| Results sync | ✅ | coste **0 requests extra**: los goles ya venían en el payload |
| Capturador de odds | 🟡 | construido, validado en dry-run, **nunca ejecutado en real** |
| Worker | ✅ **vivo** | PID 433, arrancado 12:36:09 UTC, 2 ticks ejecutados |
| `ruff` / `mypy` | ✅ | limpios, 108 ficheros |

Worker, última evidencia literal:

```
{"tick_minutes": 15, "fixtures_sync_hours": 12, "results_sync_hours": 6,
 "daily_budget": 60, "event": "worker.started", "timestamp": "2026-09-23T12:36:09Z"}
Running job "_tick (next run at: 2026-09-23 13:06:09 UTC)"
{"partitions": ["market.odds_snapshots_2026_09", …], "event": "partitions.created"}
{"event": "tick.nothing_scheduled"}
Job "_tick" executed successfully
```

`tick.nothing_scheduled` es la respuesta correcta, no un fallo: no hay ningún
partido dentro de una ventana de captura. El worker está esperando, que es
exactamente lo que debe hacer.

Coste fijo del worker: **~12 requests/día**, dejando ~48 de 60 para cuotas.

---

## 3. Datos

Leído de la base de datos ahora mismo:

```
competiciones conocidas        77
competiciones activas           1     (Premier League, piloto)
bookmakers                     32
equipos                        20
fixtures                       10
fixtures con resultado          0     ← core.fixture_results está vacía
odds snapshots                  0     ← el bloqueo real
near-close snapshots            0
payloads crudos guardados       9
requests gastadas hoy         2 / 60
runs de ingesta                 6     (4 completed · 1 partial · 1 failed)
```

Los 10 fixtures son del **12–14 de septiembre**. Siete están en `FT` (estado, sin
marcador: el código antiguo leía la identidad del partido y tiraba los goles).
Tres siguen en `NS` y **son irrecuperables**: sus fechas caen fuera de lo que el
plan sirve. El results sync existe para que esto no vuelva a pasar hacia delante,
no para resucitarlos. No los voy a rellenar con nada.

### Lo que el plan Free permite de verdad (medido, no supuesto)

```
/fixtures?league=&season=   RECHAZADO  "Free plans do not have access to this season"
/fixtures?date=             ±1 día solamente
parámetro `last`            RECHAZADO
cuota                       10 req/min · 100 req/día
```

Consecuencias que no se arreglan programando:

* Ventanas **alcanzables**: T−1440, T−720, T−360, T−180 y near-close T−12.
* Ventanas **inalcanzables**: T−2880 y T−4320. El partido ni siquiera es visible a
  esa distancia. No se simulan, no se interpolan, no se inventan.
* Un resultado no recogido en ~24 h tras el pitido final es irrecuperable. Por eso
  el worker corre cada 6 h y no una vez al día.
* La primera captura real será, forzosamente, un **T−1440**: el partido aparece
  en el horizonte del plan aproximadamente 24 h antes de su saque inicial.

---

## 4. Modelos

**No empezados.** Sin adornos:

```
src/fbi/features/__init__.py        1 línea
src/fbi/models/__init__.py          1 línea
src/fbi/predictions/__init__.py     1 línea
src/fbi/backtesting/__init__.py     1 línea
```

No hay Elo. No hay Poisson. No hay Dixon-Coles. No hay entrenamiento, ni
validación temporal, ni calibración, ni backtest.

Lo que **sí** existe y está probado es la capa matemática sobre la que se
construirán, en `src/fbi/domain/`:

| Módulo | Qué aporta |
|---|---|
| `probability.py` | `Probability`, `ProbabilityDistribution`, tolerancia de suma explícita |
| `market_probability.py` | `devig()` con **Shin**, **power** y **logarítmico**; `RawImpliedProbability` vs `FairProbability` separadas por tipo |
| `odds.py` | `DecimalOdds`, `overround()` |
| `value.py` | `Edge`, `PriceEdge`, `ExpectedValue` — una convención cada uno, sin escapatoria |
| `units.py` | `StakeUnits`, `ProfitUnits`, `roi()` — unidades teóricas, la plataforma no custodia dinero |
| `market.py` | `MarketType`, `Side`, `MarketLine`, `Selection` |

Son **61 tests unitarios** de dominio. El tipado impide confundir probabilidad
implícita con probabilidad justa, y probabilidad con confianza. Es cimiento, no
es un modelo.

---

## 5. Picks

**Nada.** `src/fbi/picks/__init__.py` tiene una línea.

Las tablas existen y están vacías: `analytics.backtest_runs`,
`analytics.backtest_samples`, `analytics.bankroll_ledger`.

No hay value engine, ni shadow picks, ni settlement, ni ledger de resultados.
No hay ninguna cifra de rendimiento en ninguna parte de este sistema, y eso es
correcto: con 0 snapshots de cuotas y 0 resultados almacenados, cualquier número
de ROI que apareciera hoy sería inventado.

---

## 6. API

`apps/api/main.py` — **71 líneas, 2 endpoints**:

```
GET /health            estado del stack, migración actual, runs colgados
GET /health/quality    métricas reales de calidad de datos
```

`/health/quality` es honesto y ya reporta: `fixtures_awaiting_result`,
`fixtures_with_result`, `partial_jobs_24h`, `unattributed_requests_today`,
`stale_running_jobs`. Hoy dice, correctamente, que hay 3 fixtures esperando
resultado.

**No existe API de producto**: ni `/fixtures`, ni `/odds`, ni `/picks`, ni
`/models`, ni `/performance`. `src/fbi/api/` no tiene rutas.

---

## 7. Frontend

Repo `SimonP0607/football-intelligence-hub` · 115 archivos · árbol limpio ·
`main` **2 commits por delante de origin** · sirviendo en `http://localhost:5173`.

15 rutas devuelven 200 y renderizan. Barrido sobre el HTML servido: **0 casos**
de `undefined`, `NaN`, `[object Object]`, `Infinity` o fugas de `null`.

Corregido y verificado en esta sesión:

* 96 errores `prettier/prettier` → **0**.
* Un `useMemo` que no memoizaba nada: `matches.data ?? []` creaba un array nuevo
  en cada render e invalidaba todas las dependencias aguas abajo. Era un defecto
  real, no cosmética.
* `typecheck` añadido (`tsc --noEmit`) — pasa limpio. No lo inventé antes de
  comprobar que no existía.
* "DEMO DATA" se anunciaba dos veces por pantalla en 10 rutas → una sola vez, en
  la topbar.
* "System state: Degraded" se pintaba con el mismo peso y color que una fecha →
  ahora ámbar con punto, sin depender solo del color.
* El mock de cuota decía "7,500/day" (plan Pro). La cuenta es Free →
  "Budget 60/day · plan limit 100".

**Todo lo que muestra es DEMO.** No hay una sola llamada al backend. `src/lib/api/`
apunta a mocks. Conectarlo es trabajo real y no está hecho.

Conocido y pendiente: 12 avisos `react-refresh/only-export-components` — 6 son de
shadcn upstream (tocarlos rompe `shadcn add`), 6 son nuestros y solo afectan a la
granularidad del hot-reload.

---

## 8. AI

**Nada.** No hay analista, ni generación de narrativa, ni explicación de picks,
ni integración de LLM en el producto. No hay carpeta, no hay stub, no hay diseño.

---

## 9. Bot

**Nada.** `apps/bot/__init__.py` tiene una línea. Sin Telegram, sin comandos, sin
publicación. Lo cual es coherente con la restricción de no publicar apuestas
automáticamente: no hay nada que publicar ni con qué publicarlo.

---

## 10. QA

**Backend: 307 tests** en 26 ficheros, `ruff` y `mypy` limpios.

```
integration   105 tests   esquema, cuota persistente, ledger, captura,
                          near-close, particiones, health, results sync,
                          guardas estructurales
unit          202 tests   dominio (61), planificador de ventanas (18),
                          cliente y rate limit (17), normalización (12),
                          validación de plan (6), payload store (6), …
```

Los que más valen no son los que cuentan líneas, sino los que capturan un fallo
que ya ocurrió de verdad:

* `test_ledger_states.py` — reproduce la sync real de 9 requests con 7 rechazos
  que el ledger llamaba `completed`. Ahora es `partial`, y el test lo fija.
* `test_persistent_quota.py` — dos procesos independientes no pueden gastar
  juntos más del presupuesto. Probado con procesos reales del sistema operativo,
  no con hilos.
* `test_capture_schedule.py` — la banda de tolerancia corría hacia atrás, así que
  `next_run_at` apuntaba al instante en que la ventana **se cerraba**. Un tick un
  minuto tarde perdía la ventana entera.
* `test_results_sync.py` — un partido aplazado no puede adquirir un 0-0, y la
  prórroga y los penaltis no se mezclan con el marcador de 90 minutos.
* `test_schema_invariants.py` (22) — la base de datos rechaza lo que el código
  no debería poder escribir.

**Frontend:** `lint` 0 errores / 12 avisos · `typecheck` 0 · `build` OK.

No hay tests de frontend, ni E2E, ni tests de carga, ni tests de la API de
producto (que no existe).

---

## 11. Repositorios

**`football-intelligence-v2`** — árbol limpio, `HEAD` = `c46bd8f`

```
c46bd8f  docs(rebuild): record what actually runs, and what does not
82deb7b  feat(ingestion): sync results, so a played fixture stops claiming otherwise
9470ed4  fix(health): unattributed requests are a number, not an alarm — and relabel history
bd57726  feat(ops): keep the daily budget in the database, and let a run say "partial"
6720a2b  fix(odds): the window tolerance ran backwards, so next_run_at named its end
7c08eca  docs(plan): record the free plan's ~24h fixture horizon, measured
b9d3022  fix(ingestion): sync fixtures by date, the only query the Free plan serves
e0dde68  feat(config): enable the Premier League as the single capture pilot
```

**`football-intelligence-hub`** — árbol limpio, `main` **ahead 2** de origin

```
c42793b  fix(web): stop repeating DEMO DATA, make a degraded state look degraded
1a6be94  fix(web): resolve lint, add typecheck, and fix a memo that never memoised
```

Los dos commits del frontend están **sin empujar**. No los he subido porque
empujar a GitHub es publicar, y eso no me lo autorizaste explícitamente para este
repo. Un `git push` cuando quieras.

**Seguridad:** `API_FOOTBALL_KEY=[SECRETO DETECTADO — NO MOSTRADO]`, presente solo
en `.env`, 0 apariciones en el historial de git, en logs o en payloads guardados.

---

## 12. Bloqueos reales

**1 — Sin ventana de captura todavía. (El bloqueo que importa.)**
0 snapshots de cuotas. Hace falta un partido de Premier dentro de las ~24 h que
el plan deja ver; hoy es jornada de copa y no hay ninguno. El worker está vivo y
capturará solo cuando aparezca: no requiere que yo esté presente. Hasta que eso
ocurra, **todo lo aguas abajo es imposible de validar con datos reales**, no solo
difícil.

**2 — Historia de cuotas a T−72h: imposible en plan Free.**
Cualquier estudio de movimiento de línea, CLV o closing line necesita plan de pago
o un dataset externo. Opciones documentadas en
`docs/research/HISTORICAL_ODDS_OPTIONS.md`. Es una decisión tuya porque cuesta
dinero — por eso no la he tomado.

**3 — Persistencia del worker.**
Lo sostiene un proceso `wsl.exe` oculto en Windows. Un reinicio lo tumba. Lo
permanente sería una tarea programada de Windows o `loginctl enable-linger`, y lo
segundo necesita `sudo`, que no tengo.

**4 — El límite real de esta sesión.**
Ninguno de los tres bloqueos anteriores impedía escribir la API de producto, el
settlement, el motor de features o la conexión frontend↔backend. Eso se quedó sin
hacer por alcance de sesión, no por el entorno.

---

## 13. Roadmap restante

Fases 6–30, separadas por lo único que importa para ordenarlas: **si necesitan
datos que aún no existen o no**.

### Se puede escribir ya, sin un solo snapshot más

| Fase | Trabajo | Nota |
|---|---|---|
| 18 | **API de producto (FastAPI)** | fixtures, odds, quality, admin. Es el mayor bloque desbloqueado. |
| 19 | **Conectar frontend ↔ backend** | sustituir `src/lib/api/` mock por el cliente real; el badge DEMO pasa a significar algo |
| 20–21 | Match Center · Data Quality | ambas pantallas se alimentan de datos que ya existen |
| 6 | Motor de features | Elo, forma, descanso: se escribe y se prueba con datos sintéticos; se *ajusta* después |
| 17 | Settlement | lógica pura de liquidación 1X2/OU/BTTS contra `core.fixture_results` |
| 27–30 | Observabilidad · seguridad · testing · QA final | independientes del dato |

### Bloqueadas hasta que haya historia real

| Fase | Trabajo | Espera a |
|---|---|---|
| 3 | Primera captura real | la próxima jornada de Premier |
| 7–8 | Profundidad histórica · odds intelligence | N capturas acumuladas |
| 9–10 | Market baseline (devig sobre cuotas reales) | snapshots |
| 11–12 | Modelos base y backtest predictivo | resultados + features sobre historia |
| 13–14 | Dataset histórico de cuotas · backtest económico | decisión del bloqueo 2 |
| 15–16 | Value engine · shadow picks | baseline + modelo calibrado |
| 22–26 | Models Lab · Picks Center · Performance · AI Analyst · Bot V2 | todo lo anterior |

**El orden que yo seguiría:** 18 → 19 → 20 → 6 → 17, mientras el worker acumula
historia en paralelo. Cuando llegue la primera captura real, las fases 9–16 dejan
de estar bloqueadas por falta de datos y pasan a estar limitadas solo por trabajo.

---

## Resumen en una línea

El stack corre de verdad en tu máquina, con 307 tests en verde y un worker vivo
esperando la próxima jornada; el cuello de botella dejó de ser código y pasó a ser
**profundidad de datos**, y de las 30 fases hay 5 hechas —con las fases 18–21 y 6
esperando trabajo, no esperando datos.
