# V2 — Implementation status

**Actualizado:** 2026-09-24 22:40 UTC.

Dos fuentes, y este documento no las mezcla:

* **Máquina** — el portátil de Simon (WSL2 + Docker Desktop). Último contacto: 2026-09-24
  19:49 UTC. Corre el backend en `22ff00c` (features + backfill) y el frontend en `1625ee7`.
* **Réplica** — un `pg_dump` de la base de datos de la máquina tomado en ese contacto,
  restaurado en el entorno de trabajo en la nube. Todo lo posterior a `22ff00c` se construyó,
  se probó y se midió ahí. **No está desplegado en la máquina todavía** (ver §12).

Una casilla ✅ significa: ejecutado, verificado y con tests en verde en el sitio indicado.
Nada está marcado por haber sido escrito.

---

## 0. Lectura rápida

```
                        máquina (22ff00c)              réplica (HEAD)
API-Football            ✅ plan Free, clave solo .env    — (sin clave: no llama a nadie)
Ingesta                 ✅ fixtures · resultados · backfill
Raw storage             ✅ 47 payloads, 1,3 MB           ✅ + CSVs de Football-Data
PostgreSQL              ✅ Alembic 0018                  ✅ Alembic 0021
Odds history (propio)   ⛔ 0 snapshots                   ⛔ 0 snapshots
Odds history (externo)  ⛔ sin importar                  ✅ 345.964 cuotas · 5.329 partidos
Feature Engine          ✅ 181.740 features · 12.110 Elo ✅
Modelos                 ⛔ código no desplegado          ✅ Poisson · Dixon-Coles · Elo+logit
Market Baseline         ⛔                               ✅ histórico · ⛔ consenso propio (0 capturas)
Backtest walk-forward   ⛔                               ✅ sesión 1 (código 9a83ac0)
Value Engine / Picks    ⛔                               ✅ código + tests · 0 picks (0 capturas)
FastAPI /api/v1         🟡 versión de 22ff00c            ✅ 25 operaciones
Frontend                🟡 versión de 1625ee7            ✅ 14 rutas LIVE · 1 placeholder
Analista IA             ⛔                               🟡 herramientas ✅ · LLM sin credencial
Bot (notificador)       ⛔                               🟡 ✅ · Telegram sin credencial
Arranque local          🟡 lanzadores ad hoc             ✅ dev-up/dev-down · compose verificado
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
| Alembic | réplica | ✅ 0021 | roundtrip `upgrade head → downgrade base → upgrade head` limpio (49 tablas) |
| Alembic | máquina | 🟡 0018 | 0019–0021 pendientes (§12) |
| Worker | máquina | ✅ corriendo | heartbeat `Mila:worker`, arrancado 19:49:07 UTC en `22ff00c` |
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

**Pendiente de honestidad:** la sesión se ejecutó con el código `9a83ac0`, anterior al cambio que
liquida sobre el marcador a 90 minutos. Hay que repetirla en la máquina con el código actual
(§12) antes de citar estas cifras como definitivas.

## 5. Picks

Motor de valor (edge de probabilidad, edge de precio, EV, Kelly solo informativo), reglas
versionadas, ciclo `candidate → shadow → qualified → published (desactivado por CHECK) →
settled` + `rejected`, liquidación sobre 90 minutos con líneas asiáticas partidas, CANC nulo y
PST/SUSP/ABD/AWD/WO pendientes con motivo. **0 candidatos y 0 picks**: no hay precios capturados
que evaluar. Ninguna versión de modelo puede calificar mientras su backtest sea `worse`.

## 6. API de producto

25 operaciones bajo `/api/v1` (24 GET + `POST /analyst/ask`), solo lectura con conexiones
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
| `mypy` (estricto, 17 paquetes) · `mypy .` | 124 ficheros sin errores · 214 sin errores |
| `pytest` | 490 passed |
| Migraciones | roundtrip completo limpio |
| `pip-audit` | sin vulnerabilidades conocidas |
| Frontend `lint` · `typecheck` · `build` | 0 errores (11 avisos react-refresh conocidos) · limpio · OK |
| `bun audit` | sin vulnerabilidades (tras fijar nanoid, js-yaml y brace-expansion) |
| Playwright | 81/81 contra la réplica · 81/81 contra la base sintética de UI |

## 10. Seguridad

La clave de API-Football solo vive en `.env` de la máquina, viaja en cabecera, se redacta antes
de disco y de logs (parámetros y cadenas), y nunca llega al navegador. La imagen Docker no
contiene `.env` ni `.git`. `httpx`/`httpcore` en WARNING para que un token en una URL no acabe
en un log. CORS limitado a GET/POST/OPTIONS y a los orígenes locales. Publicar picks es
imposible en el esquema. `SECURITY_ACTION: Rotación recomendada posteriormente` para cualquier
credencial que estuviera en el sistema legacy.

## 11. Bloqueos reales

1. **Sin captura real todavía.** Depende del calendario y del plan Free. El worker de la máquina
   capturará solo cuando haya una ventana alcanzable.
2. **Máquina desconectada** desde las 19:49 UTC del 24-09: el despliegue de todo lo posterior a
   `22ff00c` espera a que vuelva (§12).
3. **Credenciales que no existen:** LLM del analista y Telegram. Son decisiones de Simon.
4. **Plan Free:** sin temporada 2025/26 por liga, sin T−72h/T−48h, sin historia de línea.

## 12. Despliegue pendiente en la máquina (en este orden)

1. Comprobar WS0 (worker, cuota, próximas ventanas) y hacerlo lejos de una ventana de captura.
2. `pg_dump` a `~/backups`.
3. Traer los commits (bundle) y fast-forward: backend `22ff00c → HEAD`, frontend `1625ee7 → HEAD`.
4. `pip install -e ".[dev,analytics]"` (numpy, scipy) y `bun install`.
5. `scripts/dev-down`, `scripts/dev-up --migrate` (hace el backup y migra 0018 → 0021).
6. `python -m scripts.import_historical_odds --apply` y `python -m scripts.run_backtest --apply`
   con el árbol limpio.
7. Push del frontend a GitHub (`main`, sincroniza con Lovable) y verificación en el navegador.
