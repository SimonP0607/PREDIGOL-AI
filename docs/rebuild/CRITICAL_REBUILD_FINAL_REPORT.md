# PrediGol — Critical Rebuild: informe final (4 oct 2026)

*Gates A→J ejecutados en orden sobre la máquina local `mila` (WSL; API :8010, web :5173). Nada
publicado en GitHub, nada desplegado públicamente, nada contratado. Cada cifra sale de la base de
datos o de un documento enlazado; donde algo falta se dice.*

## DATA TRUTH (GATE A) — `docs/rebuild/DATA_TRUTH_AUDIT.md`

| | Estado |
|---|---|
| Fixtures | API 35,638 vs BD 35,631 en las 144 temporadas auditadas (eran **9,165 faltantes**: la sync leía solo hoy..horizonte; ahora lee temporadas completas, recuperado desde RAW con 0 requests). 225,753 partidos en total |
| Results | 441,757 / 441,765 campos coinciden; 78 cancelados + 1 abandonado mal guardados como *scheduled* (`Canc`/`Abd`) corregidos y registrados en `audit.data_repairs`; 6 partidos con prórroga sin marcador de 90' quedan sin resultado por regla |
| Standings | 1,328 / 1,380 filas (faltaban 182: clave sin grupo); refresco por partido terminado cada 30 min; una tabla vieja se marca *stale*, nunca "actual" |
| Teams | 8,165 equipos, 8,162 con escudo; cambios de local/visitante del proveedor ahora se siguen y registran |
| Players | 179,294 jugadores, 151,392 con perfil (84 %; antes 4 perfiles); planteles semanales en `core.squad_members` |
| Current season | `catalogue_refresh` diario: temporada actual corregida en 16 competiciones; 124 competiciones seguidas, 154 temporadas actuales |
| Historical validation (GATE C) | 209,219 HISTORICAL_APPROVED · 672 VALIDATED · **19 QUARANTINED** (10 duplicados del proveedor, 9 medio tiempo > final) · 5 INGESTED; 15 temporadas MODEL_READY (5 grandes ligas 2022-2024), 861 PARTIAL, 21 PRODUCT_ONLY, 93 INSUFFICIENT — `MODEL_READY_DATASET.md` |

## ODDS (GATE B) — `docs/research/ODDS_PROVIDER_GAP_ANALYSIS_2026.md`

* **Cobertura**: de 675 partidos jugados (25 sep–4 oct), 182 con precio antes del inicio (27 %).
  Causa medida: máquina apagada ~170 h y 305 partidos conocidos tarde — **0** fallos del planificador
  con el worker encendido. Nuevo `final_prematch`: lee los últimos precios previos (7 días de
  historia del proveedor): 289 partidos recuperados, mediana 76–118 min antes del inicio.
* **Casas**: 9 de las 33 que lista API-Football cotizan (Marathonbet, 1xBet, Betfair, Bet365,
  Betano, BetVictor, Pinnacle, William Hill, SBO); 24 nunca cotizaron (incluida bwin).
* **Mercados**: 1X2, Over/Under, BTTS, hándicap asiático, doble oportunidad.
* **Falta cobertura local**: de los 14 operadores con licencia en Colombia solo aparece la marca
  Betano (no confirmado que sean los precios de Betano.co); Wplay, Betplay, Codere, Rushbet,
  Yajuego… no existen en el proveedor. El producto muestra la cuota mínima del modelo para la casa
  del usuario en vez de inventar un precio.
* **Recomendación**: mantener el worker encendido (decisión del dueño); usar los precios finales
  pre-partido como referencia de cierre; si se quieren precios colombianos reales, Odds-API.io
  (pago, **no contratado**).

## DAILY PICKS / PARLAYS / USER PICKS (GATE D) — `docs/product/*.md`

* `picks.daily_sets` persistente (PENDING/WIN/LOSS/PUSH/VOID/HALF_*), etapas T-24h/12h/6h/3h con
  entradas congeladas, **hasta 5**, nunca relleno; regla v2: sin intervalo medido no se rankea.
* Parlays diario y multi-día (BUILDING/READY/ACTIVE/WON/LOST/VOID/PARTIAL_VOID) por crecimiento
  logarítmico esperado al extremo pesimista; una pierna por partido, ningún equipo dos veces, sin
  líneas de cuarto.
* Mis picks: guardar con snapshot, precio propio, parlays propios validados, historial
  Hoy/7/30 días/Todo en cuatro grupos (Picks PrediGol, Mis picks, Parlays PrediGol, Mis parlays).
* Hoy: **0 picks calificados** (ningún modelo calificado); el conjunto de evaluación existe solo
  para el dueño ("Modo de evaluación").

## MODELS / BACKTEST (GATES E-G) — `BACKTEST_V2.md`, `MODEL_RESEARCH_V2_2026.md` §9

* Features `fv2.1.0` solo del historial validado, con `data_cutoff` y segmento por partido;
  intervalos para líneas cotizadas.
* Escalera: mercado (campeón), base rates, Poisson, Dixon-Coles, Elo + ordered logit, logit
  multinomial, gradient boosting (sin/con mercado), **ensamble** (pool logarítmico).
* Campeón: `pinnacle/closing/power`, log loss 0.95967 en 1,751 partidos. Mejor modelo nuestro: el
  ensamble, 0.97928 (+0.018 [+0.011, +0.026]). Ninguno aporta información en mezcla (pesos ≤ 0).
  **Todos REJECTED, challengers 0, modelos calificados 0, picks calificados 0.**
* E0: los picks shadow (−22.3 %) ya eran **−4.7 % de EV al momento de elegirlos** según el propio
  mercado; el movimiento posterior fue ~0 y el resto (−17.6 %) es compatible con suerte (z −1.0 a
  −2.1). El "valor" era desacuerdo con el mercado, no información. Ningún umbral se tocó.
* Prospectivo (25 sep–4 oct, 181 partidos con cierre): Elo y Poisson peores que el cierre; los
  demás segmentos aún sin muestra suficiente.

## AI (GATE H) y EVOLUTION LOOP (GATE I) — `AI_PROVIDER_SELECTION_2026.md`, `EVOLUTION_LOOP.md`

* Proveedor: Claude Haiku 4.5 (integración existente) con tope mensual; búsqueda Exa (plan
  gratuito). **Faltan las claves (decisión del dueño)**: hasta entonces el informe diario lleva solo
  datos de la plataforma y el revisor de picks solo sus reglas — registrado como `not_configured`.
* Herramientas: las 12 obligatorias (get_fixture … web_research) + search/list_matches; solo
  lectura, sin SQL; procedencia por afirmación (fuente, publicado, consultado,
  CONFIRMED/REPORTED/RUMOR); el revisor solo emite avisos.
* Loop: memoria (14 hallazgos) y 5 propuestas esperando al dueño (selección solo-por-precio,
  captura cerca del cierre, E4 tiros, E6 alineaciones, cuotas históricas de totales). Investigación
  V2 semanal si cambia el código.

## Incidente durante el rebuild (corregido)

GATE E dio intervalos a las líneas cotizadas; el pick guardaba su probabilidad condicional y su
intervalo incondicional, y en líneas enteras la restricción `picks_interval_check` rechazaba la fila:
**el pipeline de picks falló de 10:18 a 11:14 UTC** (cada corrida se revertía: pronósticos, picks,
liquidación). Corregido en `24f1dfb` con prueba que lleva una línea entera hasta el pick escrito;
las corridas siguientes completan y ponen al día la liquidación. Lección aplicada:
`post_deploy_check.sh` revisa el ledger de cada job tras cada despliegue.

## TESTS

* Backend: `ruff check .` limpio, `mypy .` limpio (481 archivos), `pytest -q` **1,329 passed**.
* Frontend: lint 0 errores (26 avisos base), typecheck limpio, build OK, 91 pruebas unitarias.
* E2E (Playwright contra la app local, cuentas QA): **53 / 53 passed** — USER ES/EN, ADMIN (todas las páginas, Data truth, cuentas, Preview as USER, modo evaluación, IA y Evolución), preferencias (idioma, zona horaria con DST) y responsive 390–1440 px.

## Pendientes (decisiones del dueño o datos que faltan)

1. Claves de IA (`FBI_ANALYST_API_KEY`, `FBI_ANALYST_MODEL`, `EXA_API_KEY`) — pagos/cuentas: del dueño.
2. Precios de casas colombianas — solo por proveedor pago (no contratado).
3. Worker siempre encendido — el mayor hueco de cobertura de cuotas.
4. Decidir las 5 hipótesis en Admin → Evolución.
5. Los registros v1 del conjunto diario del 4 oct (sin intervalo medido) se conservan como se
   eligieron.
