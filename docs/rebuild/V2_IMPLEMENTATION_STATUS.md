# V2 — Implementation status

**Actualizado:** 2026-09-23 · **Fuente:** ejecución real en la máquina de Simon (WSL2 + Docker), no estimación.

Este documento dice qué corre de verdad. Una casilla marcada significa: ejecutado,
verificado y con tests en verde en la máquina objetivo. Nada aquí está marcado por
haber sido escrito.

---

## 0. Lectura rápida

```
API-Football        ✅ conectada, plan Free verificado
  ↓
Data Ingestion      ✅ fixtures · resultados · cuotas (capturador construido, sin captura real aún)
  ↓
Raw storage         ✅ .json.gz + hash + índice en raw.ingestion_payloads
  ↓
PostgreSQL          ✅ 16.15 en Docker, Alembic 0013, 33 tablas
  ↓
Odds history        ⛔ 0 snapshots — ninguna ventana de captura ha coincidido con una sesión
  ↓
Feature Engine      ⛔ no empezado
  ↓
Prediction Models   ⛔ no empezado
  ↓
Market Baseline     ⛔ no empezado
  ↓
Value Engine        ⛔ no empezado
  ↓
Shadow Picks        ⛔ no empezado
  ↓
FastAPI             🟡 /health y /health/quality reales; el resto del producto no existe
  ↓
Frontend            🟡 completo y funcionando en localhost con datos DEMO; sin conectar al backend
  ↓
Analytics / AI / Bot ⛔ no empezado
```

El cuello de botella no es código. Es **profundidad de datos**: sin cuotas capturadas
no hay baseline de mercado, sin baseline no hay con qué comparar un modelo, y sin
modelos no hay picks. Todo lo aguas abajo depende de que el capturador acumule
historia, y eso ocurre en tiempo real, no en una sesión de trabajo.

---

## 1. Infraestructura

| | Estado | Evidencia |
|---|---|---|
| WSL2 Ubuntu 26.04 | ✅ | repos en ext4, no en `/mnt/c` |
| Docker + PostgreSQL 16.15 | ✅ | `postgres running/healthy`, puerto 5433 |
| Alembic | ✅ | revisión **0013**, roundtrip upgrade→downgrade→upgrade verificado |
| Gates backend | ✅ | `ruff` limpio · `mypy` 108 ficheros sin errores · **307 tests** |
| Gates frontend | ✅ | `lint` 0 errores · `typecheck` 0 · `build` OK |

## 2. Ingesta

| | Estado | Notas |
|---|---|---|
| Provider API-Football | ✅ | clave solo por `.env`; 0 apariciones en disco/logs |
| Catálogo legacy migrado | ✅ | 77 competiciones, 32 bookmakers, 81 filas de contexto |
| Fixtures sync | ✅ | estrategia `date`, única que sirve el plan Free |
| **Results sync** | ✅ **nuevo** | `scripts/sync_results.py`, coste 0 requests extra |
| Odds capture | 🟡 | construido y validado en dry-run; **sin captura real todavía** |
| Cuota diaria persistente | ✅ | `raw.provider_quota`, probada entre procesos independientes |
| Job ledger | ✅ | `completed / partial / failed / aborted` |
| Worker | ✅ **corriendo** | tick 15 min · fixtures 12 h · resultados 6 h |

### Lo que el plan Free permite de verdad (medido, no supuesto)

```
/fixtures?league=&season=   RECHAZADO  "Free plans do not have access to this season"
/fixtures?date=             ±1 día solamente
parámetro `last`            RECHAZADO
cuota                       10 req/min · 100 req/día
```

Consecuencias que no se pueden programar para que desaparezcan:

* Ventanas alcanzables: **T−1440, T−720, T−360, T−180 y near-close T−12**.
* Ventanas **inalcanzables**: T−2880 y T−4320 — el partido ni siquiera es visible
  a esa distancia. No se simulan.
* Un resultado no recogido en ~24 h tras el pitido final es **irrecuperable**.
  Por eso el worker corre cada 6 h y no una vez al día.

Coste fijo del worker: ~12 requests/día, dejando ~48 de 60 para capturar cuotas.

## 3. Datos actuales

```
competiciones conocidas      77
competiciones activas         1  (Premier League, piloto)
fixtures                      9
fixtures con resultado        0
odds snapshots                0
near-close snapshots          0
requests gastadas hoy         2 / 60
```

**3 fixtures quedaron obsoletos de forma permanente** (13–14 sept, aún `NS`). Sus
fechas caen fuera de la ventana que sirve el plan: no son recuperables. El result
sync existe para que no vuelva a pasar hacia delante, no para resucitar esos.

## 4. Frontend

Repo: `SimonP0607/football-intelligence-hub` · 115 archivos · `main` sincronizado ·
corre en `http://localhost:5173`.

15 rutas devuelven 200 y renderizan. Barrido de defectos sobre el HTML servido:
**0 casos** de `undefined`, `NaN`, `[object Object]`, `Infinity` o fugas de `null`.

Corregido esta sesión:

* 96 errores `prettier/prettier` → 0.
* Un `useMemo` que no memoizaba nada: `matches.data ?? []` creaba un array nuevo en
  cada render e invalidaba todas las dependencias aguas abajo.
* `typecheck` añadido (`tsc --noEmit`), pasa limpio.
* DEMO DATA se anunciaba dos veces por pantalla en 10 rutas → una sola vez, en la topbar.
* "System state: Degraded" se renderizaba con el mismo peso y color que una fecha →
  ahora ámbar con punto, sin depender solo del color.
* El mock de cuota decía "7,500/day" (plan Pro). La cuenta es Free → "Budget 60/day ·
  plan limit 100".

Pendiente y conocido: 12 avisos `react-refresh/only-export-components` — 6 son de
shadcn upstream (tocarlos rompe `shadcn add`), 6 son nuestros y solo afectan a la
granularidad del hot-reload.

## 5. Lo que NO existe

Feature engine · modelos (Elo, Poisson, Dixon-Coles) · market baseline · backtest ·
value engine · pick engine · settlement · API de producto · conexión frontend↔backend ·
AI analyst · bot · dataset histórico de cuotas.

No están empezados. Son el grueso del trabajo restante y dependen, en su mayoría, de
tener historia de cuotas que todavía no existe.

## 6. Bloqueos reales

1. **Sin ventana de captura disponible.** Hace falta un partido de Premier dentro de
   las ~24 h que el plan deja ver. El 23 de septiembre es jornada de copa: no hay.
   El worker ya está en marcha y capturará solo cuando la haya.
2. **Historia de cuotas a T−72h imposible en plan Free.** Cualquier estudio de
   movimiento de línea o CLV requiere plan de pago o un dataset externo. Decisión
   pendiente, documentada en `docs/research/HISTORICAL_ODDS_OPTIONS.md`.
3. **Persistencia del worker.** Lo sostiene un proceso `wsl.exe` oculto en Windows.
   Un reinicio lo tumba. Una tarea programada de Windows o `loginctl enable-linger`
   (necesita sudo) lo haría permanente.
