# Pre-upgrade readiness — 32 capas

**Fecha:** 25 sep 2026, 03:00 UTC. **Código:** backend `056910d` (+ docs), frontend `ffde018`.

**Dónde se verificó.** En la **réplica** (entorno de trabajo en la nube: restauración de la base
de datos de la máquina del 24 sep 19:49 UTC + todo el código posterior). La **máquina** de Simon
(WSL2 + Docker Desktop) está sin conexión desde el 24 sep 19:49 UTC y sigue en backend `22ff00c`,
Alembic 0018, frontend `1625ee7`: nada de lo nuevo está desplegado allí todavía.

**Criterio.** `DONE` = existe + se ejecuta + tiene tests + está integrado + se puede verificar.
Un fichero no basta. Estados: `DONE` · `FUNCTIONAL_BUT_IMMATURE` · `IN_PROGRESS` ·
`BLOCKED_BY_DATA` · `BLOCKED_BY_PLAN` · `NOT_STARTED`.

## Matriz

| # | Capa | Estado | Evidencia | Falta | Riesgo | Siguiente acción |
|---|---|---|---|---|---|---|
| 01 | Infraestructura | FUNCTIONAL_BUT_IMMATURE | PostgreSQL 16 en Docker; `scripts/dev-up`/`dev-down`/`dev-status`; imagen con código horneado y perfil `stack` de compose; worker con lock de instancia única (exit 75) y heartbeat | portátil como servidor; keeper `wsl.exe` ad hoc; sin monitorización externa ni copia fuera del equipo | una caída del portátil para la captura | sincronizar la máquina; decidir copia externa (Simon) |
| 02 | Git / entrega | FUNCTIONAL_BUT_IMMATURE | backend: historia completa, commits por grupo lógico, tests verdes en cada uno; frontend en GitHub (Lovable) | el backend no tiene remoto (solo portátil + réplica); sin CI; los 6 commits nuevos del frontend esperan push desde la máquina | pérdida del repo backend si falla el portátil | push del frontend y, con permiso de Simon, un remoto privado para el backend |
| 03 | PostgreSQL / esquema | DONE | 24 migraciones; la suite construye el esquema solo con Alembic; restricciones que rechazan fuga temporal, PRODUCTION sin gate, publicación de picks | máquina en 0018 | migración con datos reales | backup 6/6 → `alembic upgrade head` en la máquina |
| 04 | Almacén raw | DONE | payloads gzip inmutables con hash, índice `raw.ingestion_payloads`, redacción de credenciales con test, replay; incluido en el backup | — | — | — |
| 05 | Proveedor API-Football | DONE | cliente con rate limit, circuit breaker, reintentos y cuota persistente; en producción en plan Free desde el 12 sep; endpoints de detalle, lesiones, cobertura, equipos, jugadores probados contra HTTP falso | primera llamada real a `ids=`/`/leagues` | que `ids=` no esté en el plan | `scripts.probe_plan --yes` |
| 06 | Cuota / scheduling | DONE | `raw.provider_quota` compartida por todos los procesos; reserva para el vivo; scheduler consciente del plan (horizonte 4 días y backfill horario en planes de pago) | — | — | ajustar `FBI_APIFOOTBALL_PLAN` tras comprar |
| 07 | Ingesta de fixtures | DONE | sync por fecha con linaje de payload (0015); 6.058 partidos en la réplica | — | — | — |
| 08 | Ingesta de resultados | DONE | sync de resultados con linaje, marcador de 90' separado de prórroga/penaltis (0020), detección de "awaiting result" | en Free, inalcanzable ~1 día después del partido | resultados perdidos en Free | se resuelve con el plan de pago |
| 09 | Ingesta de cuotas | IN_PROGRESS | capturador con 6 ventanas pre-partido + near-close, tolerancia ±45 min, timeline que distingue capturado/perdido/inalcanzable; tests | **0 capturas reales** a 24 sep 19:49 UTC; en Free las ventanas T-72h/T-48h son inalcanzables | sin series propias no hay CLV propio | ver la máquina: las primeras ventanas eran las de la Premier del 26 sep |
| 10 | Migración histórica | BLOCKED_BY_PLAN | planificador, unidades resumibles (0023), motor, dry run 9/9 PASS, NAME CHECK, sonda; 72 competiciones × ≤ 9 temporadas priced | el plan de pago | ids de competición erróneos (mitigado) | sonda → compra → tier 1 |
| 11 | Calidad de datos | FUNCTIONAL_BUT_IMMATURE | informe de calidad con nulos explicados, issues derivados en cada petición, cobertura, Jobs, Analytics → Coverage, Audit por partido | las validaciones de detalle por tier (§8 del plan) están descritas, no automatizadas | detalle incoherente sin aviso | automatizar §8 antes del tier 2 |
| 12 | Feature Engine | DONE | fv1 (30) y **fv2 (43)**: pi-ratings, shares de tiros, forma residual, contexto de liga; point-in-time; la BD rechaza fuga; hash del conjunto de información; 6.058 conjuntos fv2 | historia (3 temporadas) | — | recalcular tras el backfill |
| 13 | Market baseline | DONE | Shin/power/proporcional sobre cierre y pre-cierre de Pinnacle, media y Bet365 (5.329 partidos); consenso de-vigged desde capturas | consenso real (0 capturas) | — | llega con las capturas |
| 14 | Elo | DONE | Elo V2 (K 20, local 65, multiplicador de margen), historia persistida, ordered logit; declina con < 10 partidos | HA por liga variable en el tiempo | sesgo en ligas con HA distinta | P0 del roadmap |
| 15 | Poisson | DONE | Maher con decaimiento y encogimiento elegidos en validación (rejilla que se amplía si el óptimo cae en el borde); intervalos Laplace | — | — | — |
| 16 | Dixon–Coles | DONE | ρ estimado conjuntamente; corrección inválida → declina | — | — | — |
| 17 | Calibración | FUNCTIONAL_BUT_IMMATURE | ECE por bins y diagramas de fiabilidad por modelo; check de calibración en el gate | recalibración (temperatura/isotónica) no ajustada; CORP | probabilidades mal calibradas en producción | ajustar en validación tras el backfill |
| 18 | Backtesting predictivo | DONE | walk-forward con reajuste diario y control de fuga por bloque; bootstrap por jornadas, DM-HLN, MDD, RPS, etiqueta de evidencia; sesión 2 reproducida bit a bit | MCS | — | — |
| 19 | Backtesting económico | FUNCTIONAL_BUT_IMMATURE | apuestas hipotéticas con IC del ROI y drawdown sobre precios de FD | CLV agregado; el ROI no informa con < 10.000 apuestas | sobrelectura del ROI | CLV con IC por bloques |
| 20 | Value Engine | BLOCKED_BY_DATA | EV en el límite inferior del intervalo, consenso de-vigged, regla versionada; test de pipeline de extremo a extremo | precios capturados reales | — | llega con las capturas |
| 21 | Pick Engine | BLOCKED_BY_DATA | picks shadow con ciclo de vida y eventos; publicar es imposible en el esquema | ídem | — | ídem |
| 22 | Settlement | BLOCKED_BY_DATA | liquidación a 90', cola de revisión, línea de valor | picks reales | — | ídem |
| 23 | Product API | DONE | **32 operaciones** bajo `/api/v1` (31 GET + `POST /analyst/ask`), solo lectura, envelope de 4 estados con motivo, 404/422/500 en JSON; nuevas: `/matches/{id}/audit` y 6 de `/analytics` | desplegar en la máquina | — | sincronizar |
| 24 | Frontend | DONE | 15 rutas LIVE en modo live (inventario abajo); lint 0 errores, typecheck, build; 84 E2E | desplegar en la máquina/Lovable | — | push desde la máquina |
| 25 | Match Center | DONE | Overview, Markets, Models, Timeline, Lineage y **Audit** (cadena completa con estado por paso) | — | — | — |
| 26 | Odds Intelligence | FUNCTIONAL_BUT_IMMATURE | mercado histórico, márgenes, pre-cierre→cierre, calibración del cierre | tablero en vivo, movimiento y near-close sin datos propios | — | llega con las capturas |
| 27 | Models Lab | DONE | modelos y sesiones, calibración, ligas, estabilidad temporal, protocolo; registro con gate en Analytics → Models | — | — | — |
| 28 | Performance | BLOCKED_BY_DATA | responde `insufficient_data` con motivo | picks liquidados | — | — |
| 29 | Observabilidad | FUNCTIONAL_BUT_IMMATURE | logs estructurados con request id, heartbeat del worker, job ledger con estado parcial, `/health`, Jobs | alertas y métricas exportadas | un fallo nocturno pasa inadvertido | alertas cuando el vivo esté activo |
| 30 | Seguridad | DONE | escaneo de secretos en el historial de ambos repos: 0; clave solo en `.env` de la máquina, redactada antes de disco y logs, nunca en el navegador; URLs enmascaradas; CORS restringido; la API no puede escribir | — | credenciales del sistema legacy | `SECURITY_ACTION: Rotación recomendada posteriormente` (legacy; no ejecutada por restricción) |
| 31 | Preparación IA | FUNCTIONAL_BUT_IMMATURE | herramientas de solo lectura con linaje; la IA explica, no genera probabilidades; consola de herramientas | credencial del LLM; bloqueado a propósito hasta la plataforma sólida | — | tras la puerta del modelo |
| 32 | Preparación Telegram | FUNCTIONAL_BUT_IMMATURE | notificador con un mensaje por evento, modo investigación, sin fugas de token (test) | token del bot; bloqueado a propósito | — | tras la puerta del modelo |

**Recuento:** DONE 17 · FUNCTIONAL_BUT_IMMATURE 9 · IN_PROGRESS 1 · BLOCKED_BY_DATA 4 ·
BLOCKED_BY_PLAN 1 · NOT_STARTED 0.

## Inventario LIVE del frontend (D3)

Modo `live` (`VITE_DATA_MODE=live`). **LIVE** = lee la API · **EMPTY_REAL** = lee la API y la API
dice honestamente que no hay datos · **DEMO** = datos de demostración · **NOT_IMPLEMENTED**.

| Ruta | Widgets | Clasificación |
|---|---|---|
| `/` Overview | Worker, System health, Provider & quota, Database, Upcoming matches, Picks, Performance | LIVE; Picks/Performance EMPTY_REAL (sin picks liquidados) |
| `/matches` | lista con filtros y "awaiting result" | LIVE |
| `/matches/:id` | Overview, Markets, Models, Timeline, Lineage, Audit | LIVE; Markets EMPTY_REAL sin capturas (histórico FD visible) |
| `/odds` | Fixtures with prices, Board, Movement, Near-close, Consensus, Historical market, Bookmaker margins | Historical LIVE; el resto EMPTY_REAL (0 capturas) |
| `/models` | Models, Market baseline, Predictive quality, Model detail (Calibration, Leagues, Temporal stability, Markets, Protocol) | LIVE |
| `/backtesting` | Protocol, sesión, selección de hiperparámetros | LIVE |
| `/picks` | Lifecycle, Decision rule, Shadow picks, Recent candidates | LIVE; listas EMPTY_REAL hasta capturar |
| `/performance` | resumen | EMPTY_REAL (`insufficient_data`) |
| `/analytics` | Competitions, Teams, Models (registro), Market, Coverage, Migration | LIVE (antes placeholder) |
| `/competitions`, `/teams`, `/rankings` | catálogo, equipos, Elo | LIVE |
| `/data-quality` | Issues, Coverage, Jobs, Notes | LIVE |
| `/ai-analyst` | herramientas; LLM | herramientas LIVE; LLM EMPTY_REAL (sin credencial, dicho) |
| `/settings` | competiciones, regla, analista, bot | LIVE |
| Búsqueda global (topbar y ⌘K) | entidades | **LIVE desde hoy** — antes buscaba en el índice DEMO también en modo live (corregido en `ffde018`, con E2E) |

Ningún widget DEMO en modo live tras la corrección; ninguno NOT_IMPLEMENTED. Los módulos `src/mock`
solo se importan en las ramas de modo demo de cada ruta.
