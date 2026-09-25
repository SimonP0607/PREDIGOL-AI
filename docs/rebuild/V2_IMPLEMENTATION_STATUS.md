# V2 — Implementation status

**Actualizado:** 2026-09-25 03:40 UTC (fase pre-upgrade; máquina sincronizada). La matriz de
32 capas está en `PRE_UPGRADE_READINESS.md`; este documento sigue siendo el detalle por área.

Dos fuentes, y este documento no las mezcla:

* **Máquina** — el portátil de Simon (WSL2 + Docker Desktop). Sin conexión del 24 sep 19:49 UTC
  al 25 sep 02:45 UTC; **sincronizada el 25 sep 02:53–03:25 UTC**: backend `ea1d0c8`, Alembic
  **0024** (venía de 0017), frontend `ffde018`, research repetido allí (ver §12 y
  `PRE_UPGRADE_READINESS.md`).
* **Réplica** — un `pg_dump` de la base de datos de la máquina tomado el 24 sep a las 19:49 UTC,
  restaurado en el entorno de trabajo en la nube. Todo lo posterior a `22ff00c` se construyó,
  se probó y se midió ahí antes de desplegarse.

Una casilla ✅ significa: ejecutado, verificado y con tests en verde en el sitio indicado.
Nada está marcado por haber sido escrito.

---

## 0. Lectura rápida

```
                        máquina (25 sep, ea1d0c8)                 réplica (HEAD)
API-Football            ✅ plan Free, clave solo .env; sonda hecha  — (sin clave: no llama a nadie)
Ingesta                 ✅ fixtures · resultados · backfill (+ Segunda 2022–2024)
Raw storage             ✅ 65 ficheros, 57 indexados, 1,9 MB        ✅ + CSVs de Football-Data
PostgreSQL              ✅ Alembic 0024 · 1.121.683 filas            ✅ Alembic 0024
Odds history (propio)   ⏳ 0 snapshots; ventanas programadas         ⛔ 0 snapshots
Odds history (externo)  ✅ 5.329 partidos (vía raw_transfer)         ✅ 345.964 cuotas · 5.329 partidos
Feature Engine          ✅ fv2 · 7.467 conjuntos                     ✅
Modelos                 ✅ 5 familias · 5 experimentos reproducidos  ✅ 5 familias · registro · model gate
Market Baseline         ✅ histórico · ⏳ consenso propio            ✅ histórico · ⛔ consenso propio
Backtest walk-forward   ✅ sesión 1 (reproducida bit a bit)          ✅ sesiones 1 y 2 (2 reproducida)
Value Engine / Picks    ⏳ previsiones en vivo; 0 precios aún        ✅ código + tests · 0 picks (0 capturas)
FastAPI /api/v1         ✅ 32 operaciones                            ✅ 32 operaciones (audit + analytics)
Frontend                ✅ 15 rutas LIVE; GitHub `ffde018`           ✅ 15 rutas LIVE · búsqueda LIVE
Analista IA             🟡 herramientas ✅ · LLM sin credencial      🟡 herramientas ✅ · LLM sin credencial
Bot (notificador)       🟡 ✅ · Telegram sin credencial              🟡 ✅ · Telegram sin credencial
Arranque local          🟡 wsl.exe ocultos, arranque manual          ✅ dev-up/dev-down · compose verificado
```

El cuello de botella sigue sin ser código: **no hay ni una cuota capturada por la plataforma**.
Sin captura no hay consenso propio, ni candidatos, ni shadow picks, ni liquidación que medir.
El capturador está en marcha en la máquina y la primera ventana alcanzable depende del
calendario (plan Free: solo ±1 día).

---

## 1. Infraestructura

| | Dónde | Estado | Evidencia |
|---|---|---|---|
| WSL2 + Docker Desktop + PostgreSQL 16 | máquina | ✅ | `fbi-postgres` healthy, puerto 5433, volumen `pgdata` |
| Alembic | réplica | ✅ 0024 | roundtrip `upgrade head → downgrade base → upgrade head` limpio |
| Alembic | máquina | ✅ 0024 | 0017 → 0024 el 25 sep 02:55 UTC, tras `pg_dump` previo |
| Worker | máquina | ✅ corriendo | heartbeat `Mila:worker` en `ea1d0c822bdc` desde el 25 sep 03:12 UTC |
| Un solo worker por BD | réplica | ✅ | advisory lock; 2.º worker sale con código 75 (host y contenedor, verificado) |
| Modo host | réplica | ✅ | `scripts/dev-up` / `dev-down` / `dev-status`, probado de extremo a extremo |
| Modo compose | nube | ✅ | imagen construida (sin `.env` ni `.git`, uid 1000), migraciones, api healthy, worker |

## 2. Datos (réplica = máquina a las 19:49 + importación histórica)

```
competiciones conocidas        77      activas: 1 (Premier League, piloto)
fixtures                       6.058   con resultado: 6.055   programados: 3 (obsoletos)
  por competición              PL 1.150 · Serie A 1.141 · La Liga 1.140 · Ligue 1 996 ·
                               Bundesliga 924 · Champions 707   (temporadas 2022–2024 + actuales)
equipos                        236
payloads crudos                47 (1,3 MB)
odds snapshots propios         0
near-close snapshots           0
cuotas históricas externas     345.964 filas · 5.329 partidos (Football-Data.co.uk)
```

El histórico externo es de **otra fuente**, con su propia semántica (`closing` y `pre_closing`
según la fuente, no validados por nosotros). Se guarda en `market.historical_odds`, separado de
`market.odds_snapshots`, y nunca se mezcla con lo capturado.

Consecuencias del plan Free (medidas, no supuestas): `/fixtures?league=&season=` solo sirve
2022–2024; `/fixtures?date=` solo ±1 día; T−72h y T−48h son inalcanzables; un resultado no
recogido en ~24 h es irrecuperable. Por eso los ascendidos de 2025/26 (Hull, Sunderland,
Coventry, Leeds) no tienen historia para los modelos de goles, y los Elo muestran último partido
de mayo de 2025.

## 3. Features

181.740 `fixture_features` y 12.110 filas de Elo, calculadas walk-forward: cada feature de un
partido solo ve resultados públicos antes de su cut-off (resultado disponible a kickoff + 3 h).
Ejecutado en la máquina (`feature_build` completado) y copiado en la réplica.

## 4. Modelos y backtest (réplica, sesión 1)

Protocolo: temporada de validación 2023/24 solo para hiper-parámetros (con ampliación de la
rejilla si el óptimo cae en el borde, usando solo validación); test 2024/25; refit diario;
cut-off 60 min antes del primer kickoff de cada bloque; cada bloque comprobado contra fugas.
5 ligas, 1.756 partidos de test. Mercado de referencia: Pinnacle closing de la fuente, sin
margen por Shin. Veredicto `better` solo si todo el IC 95 % bootstrap está por debajo de 0.

| Modelo | Versión | Muestra | Brier | Log loss | ECE | Δ log loss vs mercado [IC 95 %] | Veredicto |
|---|---|---|---|---|---|---|---|
| Poisson (Maher) | `2.0.0/xi=0.004,penalty=1@9a83ac0` | 1.748 | 0,5891 | 0,9878 | 0,0108 | +0,0268 [+0,0178, +0,0354] (n=1.744) | peor |
| Dixon-Coles | `2.0.0/xi=0.004,penalty=1@9a83ac0` | 1.748 | 0,5893 | 0,9880 | 0,0108 | +0,0270 [+0,0182, +0,0359] (n=1.744) | peor |
| Elo V2 + logit ordenado | `2.0.0/elo-v2.0 (K=20, home=65) + ordered logit@9a83ac0` | 1.756 | 0,5917 | 0,9912 | 0,0195 | +0,0303 [+0,0211, +0,0394] (n=1.751) | peor |
| Mercado (Pinnacle closing, Shin) | — | 1.744 | 0,5706 | 0,9604 | — | — | referencia |

Los tres son **peores que el mercado** frente a las 7 referencias 1X2 sin margen, y Poisson y
Dixon-Coles también en Over/Under 2,5 (3 referencias). BTTS no tiene referencia de mercado (la
fuente no publica esas cuotas): se evalúa solo contra resultados y no puede llamarse mejor ni
peor. Apuestas hipotéticas (EV ≥ 5 % al precio Pinnacle closing, 1 unidad): Poisson −7,57 %
[−17,2 %, +2,6 %] en 1.433 apuestas; Dixon-Coles −7,82 % en 1.366; Elo −8,62 % en 1.339.
Ningún resultado de apuestas es rentable ni distinguible de cero con confianza.

**Resuelto el pendiente de honestidad** de la sesión 1 (código anterior a la liquidación a 90'):
la sesión 2 corre con el código actual.

### Sesión 2 (25 sep, código `ac8ec90`, features fv2, 5 familias)

Mismo protocolo, intervalos por **bloques de jornada** (2.000 remuestreos), Diebold–Mariano
(HAC + HLN), RPS y diferencia mínima detectable; etiqueta de evidencia. Muestra común (todas las
familias y el mercado): **1.674 partidos**.

| Familia | Log loss (común) | Brier | ECE | Δ log loss vs Pinnacle cierre (Shin) [IC 95 %] | DM p | Veredicto |
|---|---|---|---|---|---|---|
| Mercado (Pinnacle cierre, Shin) | 0,95853 | 0,56921 | 0,0093 | — | — | referencia |
| Logit multinomial (fv2) | 0,98145 | 0,58415 | 0,0187 | +0,0229 [+0,0140, +0,0314] (n=1.674) | < 0,001 | peor (evidencia suficiente) |
| Poisson | 0,98295 | 0,58596 | 0,0093 | +0,0268 [+0,0175, +0,0360] (n=1.744) | < 0,001 | peor |
| Dixon-Coles | 0,98329 | 0,58624 | 0,0106 | +0,0270 [+0,0180, +0,0362] (n=1.744) | < 0,001 | peor |
| Elo V2 + logit ordenado | 0,98791 | 0,58943 | 0,0211 | +0,0294 [+0,0212, +0,0375] (n=1.674) | < 0,001 | peor |
| Tasas base (sin habilidad) | 1,07772 | 0,65293 | 0,0124 | +0,1192 [+0,1017, +0,1375] (n=1.751) | < 0,001 | peor |

Las cinco familias quedan registradas como experimentos (`analytics.experiments` 1–5) con su
model gate; `scripts.experiment reproduce 5` re-ejecutó la sesión y **las cinco dieron
predicciones idénticas** (experimentos 6–10). Gate: ninguna supera `beats_market`; el Elo además
falla `calibrated`. **Todas en RESEARCH.** Apuestas hipotéticas (EV ≥ 5 %): mnlogit −3,18 %
[−11,5 %, +4,9 %] en 1.306; Poisson −7,32 %; Dixon-Coles −7,07 %; Elo −7,44 %; tasas base
−11,07 % [−21,0 %, −0,6 %].

## 5. Picks

Motor de valor (edge de probabilidad, edge de precio, EV, Kelly solo informativo), reglas
versionadas, ciclo `candidate → shadow → qualified → published (desactivado por CHECK) →
settled` + `rejected`, liquidación sobre 90 minutos con líneas asiáticas partidas, CANC nulo y
PST/SUSP/ABD/AWD/WO pendientes con motivo. **0 candidatos y 0 picks**: no hay precios capturados
que evaluar. Ninguna versión de modelo puede calificar mientras su backtest sea `worse`.

## 6. API de producto

32 operaciones bajo `/api/v1` (31 GET + `POST /analyst/ask`; nuevas: `/matches/{id}/audit` y
seis de `/analytics/*`), solo lectura con conexiones
read-only; cada respuesta es `ok | empty | insufficient_data | not_available` con motivo. Errores
inesperados salen como JSON 500 con cabeceras CORS. Límite por cliente (240/min por defecto).

## 7. Frontend (repo `football-intelligence-hub`, modo `live`)

| Ruta | Estado |
|---|---|
| Overview · Matches · Match Center · Odds (propias + históricas) · Models · Picks · Performance · Backtesting · Competitions · Teams · Rankings · Data Quality · AI Analyst · Settings | LIVE (14) |
| Analytics | placeholder declarado, sin datos simulados |

En modo `live` ninguna página cae a datos demo; el adaptador demo solo existe con
`VITE_DATA_MODE=mock`. Suite Playwright (`bun run test:e2e`): 6 flujos + 14 rutas × 5 anchos
(1440/1280/1024/768/390) + Match Center × 5 = 81 pruebas, verdes contra la réplica y contra
la base sintética. Los flujos
con datos poblados (Odds → Match, linaje de un pick) solo pueden ejercitarse contra una base de
datos sintética de pruebas de UI, porque en la real no hay capturas: la suite lo anota en vez
de fingirlo. La suite encontró y se corrigió un fallo real (Backtesting y la ficha de modelo
rompían con sesiones guardadas sin la rejilla de validación).

## 8. Analista IA y bot

* Analista: 9 herramientas (búsqueda, partidos, partido, cuotas, predicciones, picks, rendimiento,
  calidad, evaluación de modelos), cada resultado con procedencia; bucle LLM → herramientas →
  API; cada cifra de la respuesta se verifica contra los resultados de herramientas y lo no
  encontrado se lista como no verificado. **Sin LLM configurado** (`FBI_ANALYST_API_KEY` /
  `FBI_ANALYST_MODEL` sin definir): responde que no está configurado y no envía nada.
* Bot: eventos (shadow pick, liquidación, primera captura, captura fallida, worker caído) →
  `audit.notifications` deduplicado → Telegram. **Sin token**: los mensajes quedan `skipped`
  con el motivo. Nunca recomienda una apuesta.

## 9. QA (réplica / nube, HEAD)

| Gate | Resultado |
|---|---|
| `ruff check .` | limpio |
| `mypy` (estricto, 19 paquetes) · `mypy .` | 153 ficheros sin errores · 257 sin errores |
| `pytest` | 548 passed |
| Migraciones | roundtrip completo limpio |
| `pip-audit` | sin vulnerabilidades conocidas |
| Frontend `lint` · `typecheck` · `build` | 0 errores (13 avisos react-refresh) · limpio · OK |
| `bun audit` | sin vulnerabilidades (tras fijar nanoid, js-yaml y brace-expansion) |
| Playwright | 84 flujos y vistas contra la réplica (Audit, Analytics y búsqueda nuevos) |

## 10. Seguridad

La clave de API-Football solo vive en `.env` de la máquina, viaja en cabecera, se redacta antes
de disco y de logs (parámetros y cadenas), y nunca llega al navegador. La imagen Docker no
contiene `.env` ni `.git`. `httpx`/`httpcore` en WARNING para que un token en una URL no acabe
en un log. CORS limitado a GET/POST/OPTIONS y a los orígenes locales. Publicar picks es
imposible en el esquema. `SECURITY_ACTION: Rotación recomendada posteriormente` para cualquier
credencial que estuviera en el sistema legacy.

## 11. Bloqueos reales

1. **Sin captura real todavía.** Depende del calendario y del plan Free: la Premier está en su
   parón internacional de tres semanas; el ciclo en vivo se demuestra sobre la Segunda División
   (primera ventana 25 sep 06:30 UTC).
2. ~~Máquina desconectada~~ — resuelto: sincronizada el 25 sep (§12).
3. **Credenciales que no existen:** LLM del analista y Telegram. Son decisiones de Simon.
4. **Plan Free:** sin temporada 2025/26 por liga, sin T−72h/T−48h, sin historia de línea, sin
   `ids=` (rechazado por el proveedor el 25 sep).
5. **Football-Data.co.uk bloqueado en la red de la máquina** (redirección a coljuegos.gov.co):
   las CSV se descargan en la réplica y llegan con `scripts.raw_transfer`.

## 12. Despliegue en la máquina — hecho el 25 sep 2026 (02:53–03:25 UTC)

Por fases (`sync-machine.sh`, cada fase corta o en primer plano dentro de un `wsl.exe` oculto):

1. ✅ WS0: worker caído desde el 24 sep 20:34 UTC, 0 capturas, ninguna ventana pendiente.
2. ✅ `pg_dump` previo (`~/backups/fbi-20260925T025324Z-pre-sync.dump`, Alembic 0017).
3. ✅ Fast-forward desde bundles: backend `22ff00c → ea1d0c8`, frontend `1625ee7 → ffde018`.
4. ✅ `pip install -e ".[dev,analytics]"` y `bun install`.
5. ✅ Alembic 0017 → 0024; worker, API y web reiniciados (sin ventanas en ±45 min).
6. ✅ Tests en la máquina (ruff, mypy, pytest 551) y gates del frontend.
7. ✅ Football-Data por `raw_transfer` + `import_historical_odds --from-raw --apply`, fv2,
   `run_backtest --apply`, `experiment reproduce` (5/5 idénticos), dry run de la migración 9/9.
8. ✅ `scripts.backup create --label post-sync --restore-test`: **6/6 PASS**.
9. ✅ Sonda: `ids=` rechazado en Free; `/leagues` → cobertura verificada.
10. ✅ Push del frontend a GitHub (`origin/main` = `ffde018`) y verificación en Chrome.
