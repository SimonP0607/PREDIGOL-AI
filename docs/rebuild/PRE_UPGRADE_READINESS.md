# Pre-upgrade readiness — 32 capas

**Fecha:** 25 sep 2026, 03:40 UTC. **Código:** backend `ea1d0c8` (+ docs), frontend `ffde018`.

**Dónde se verificó.** Primero en la **réplica** (entorno en la nube: restauración de la base de
la máquina del 24 sep 19:49 UTC + todo el código posterior) y, desde las 02:53 UTC del 25 sep,
**en la máquina** de Simon (WSL2 + Docker Desktop), que volvió a estar en línea a las 02:45 UTC:

| Paso en la máquina (25 sep, UTC) | Resultado |
|---|---|
| 02:53 backup previo | `pg_dump` en el contenedor: 1,9 MB, 43 tablas con datos, Alembic 0017 |
| 02:53–03:12 código | backend `22ff00c` → `938d55e` → `ea1d0c8`, frontend `1625ee7` → `ffde018` (fast-forward desde bundles git, historia intacta) |
| 02:55 migración | Alembic **0017 → 0024** (7 migraciones, ninguna destructiva sobre datos originales) |
| 02:56 servicios | worker, API y web reiniciados, cada uno en su proceso `wsl.exe` oculto (el worker otra vez a las 03:07 y 03:12, sin ventanas pendientes, para correr el código final: `code_version` `ea1d0c822bdc`) |
| 02:58 tests en la máquina | ruff limpio; mypy estricto 153 ficheros y `mypy .` 258; **pytest 551 passed** (a `938d55e`) |
| 03:10 frontend | lint 0 errores, typecheck, build en la máquina; **push a GitHub** (14 commits, fast-forward: `origin/main` = `ffde018`) |
| 03:12–03:17 research | Football-Data importado (5.329 partidos), fv2 (7.467 conjuntos), sesión walk-forward (168 s), 5 experimentos, dry run de la migración 9/9 PASS |
| 03:18 backup + restore | **6/6 PASS** (1.121.683 filas, 57 payloads verificados) |
| 03:23 sonda | `ids=` **rechazado en Free**; `/leagues` 8.746 filas → cobertura verificada |
| 03:25 reproducción | los 5 experimentos de la máquina **idénticos** al re-ejecutarse |

**Criterio.** `DONE` = existe + se ejecuta + tiene tests + está integrado + se puede verificar.
Un fichero no basta. Estados: `DONE` · `FUNCTIONAL_BUT_IMMATURE` · `IN_PROGRESS` ·
`BLOCKED_BY_DATA` · `BLOCKED_BY_PLAN` · `NOT_STARTED`.

## Matriz

| # | Capa | Estado | Evidencia | Falta | Riesgo | Siguiente acción |
|---|---|---|---|---|---|---|
| 01 | Infraestructura | FUNCTIONAL_BUT_IMMATURE | PostgreSQL 16 en Docker Desktop (sano); worker, API y web en la máquina a HEAD, cada uno en un `wsl.exe` oculto; worker con lock de instancia única (exit 75) y heartbeat; herramientas de PostgreSQL por `docker exec` (sin integración WSL de Docker) | portátil como servidor; arranque manual tras reinicio de Windows; sin monitorización externa ni copia fuera del equipo | una caída o suspensión del portátil corta la captura (el 24 sep murió a las 20:34 UTC) | arranque automático al iniciar sesión y copia externa: decisiones de Simon |
| 02 | Git / entrega | FUNCTIONAL_BUT_IMMATURE | backend: historia completa, commits por grupo lógico, tests verdes en cada uno, sincronizado a la máquina por bundles (fast-forward); frontend **empujado a GitHub** el 25 sep (14 commits, `origin/main` = `ffde018`, sin reescribir historia) | el backend no tiene remoto (portátil + réplica); sin CI | pérdida del repo backend si fallan portátil y réplica a la vez | con permiso de Simon, un remoto privado para el backend |
| 03 | PostgreSQL / esquema | DONE | 24 migraciones; la suite construye el esquema solo con Alembic; restricciones que rechazan fuga temporal, PRODUCTION sin gate, publicación de picks; **máquina migrada 0017 → 0024** el 25 sep tras backup | — | — | — |
| 04 | Almacén raw | DONE | payloads gzip inmutables con hash, índice `raw.ingestion_payloads`, redacción de credenciales con test, replay; incluido en el backup | — | — | — |
| 05 | Proveedor API-Football | DONE | cliente con rate limit, circuit breaker, reintentos y cuota persistente; en producción en plan Free desde el 12 sep; endpoints de detalle, lesiones, cobertura, equipos, jugadores probados contra HTTP falso; **`/leagues` real** (8.746 filas) y **`ids=` real: rechazado en Free** con las palabras del proveedor | `ids=` en el plan de pago | que Pro tampoco lo sirva (ruta de upgrade documentada) | sonda en la primera hora del plan de pago |
| 06 | Cuota / scheduling | DONE | `raw.provider_quota` compartida por todos los procesos; reserva para el vivo; scheduler consciente del plan (horizonte 4 días y backfill horario en planes de pago) | — | — | ajustar `FBI_APIFOOTBALL_PLAN` tras comprar |
| 07 | Ingesta de fixtures | DONE | sync por fecha con linaje de payload (0015); 6.058 partidos en la réplica | — | — | — |
| 08 | Ingesta de resultados | DONE | sync de resultados con linaje, marcador de 90' separado de prórroga/penaltis (0020), detección de "awaiting result" | en Free, inalcanzable ~1 día después del partido | resultados perdidos en Free | se resuelve con el plan de pago |
| 09 | Ingesta de cuotas | IN_PROGRESS | capturador con 6 ventanas pre-partido + near-close, tolerancia ±45 min, timeline que distingue capturado/perdido/inalcanzable; tests | **0 capturas reales** hasta el 25 sep: la Premier está en su primer parón internacional de tres semanas y Free solo ve un día por delante; en Free T-72h/T-48h son inalcanzables | sin series propias no hay CLV propio | ciclo en vivo sobre la Segunda División (5 partidos 25–26 sep; primera ventana 06:30 UTC) |
| 10 | Migración histórica | BLOCKED_BY_PLAN | planificador, unidades resumibles (0023), motor; dry run 9/9 PASS **también en la máquina**; cobertura **verificada**: 72 competiciones, 643 competición-temporadas, 190.313 partidos, **11.611 peticiones (15.675 con margen)**; NAME CHECK: un renombre (63 → "Ligue 3"), ningún id erróneo | el plan de pago | `ids=` en el plan de pago | compra → sonda → tier 1 |
| 11 | Calidad de datos | FUNCTIONAL_BUT_IMMATURE | informe de calidad con nulos explicados, issues derivados en cada petición, cobertura, Jobs, Analytics → Coverage, Audit por partido | las validaciones de detalle por tier (§8 del plan) están descritas, no automatizadas; **3 resultados de la Premier del 13–14 sep siguen "awaiting result"** en la máquina (el worker estaba parado y Free ya no sirve esas fechas) | detalle incoherente sin aviso | automatizar §8 antes del tier 2; los 3 resultados llegan con el tier 1 |
| 12 | Feature Engine | DONE | fv1 (30) y **fv2 (43)**: pi-ratings, shares de tiros, forma residual, contexto de liga; point-in-time; la BD rechaza fuga; hash del conjunto de información; **7.467 conjuntos fv2 en la máquina** | historia (3 temporadas) | — | recalcular tras el backfill |
| 13 | Market baseline | DONE | Shin/power/proporcional sobre cierre y pre-cierre de Pinnacle, media y Bet365 (5.329 partidos, también en la máquina); consenso de-vigged desde capturas | consenso real (0 capturas); **Football-Data.co.uk está bloqueado en la red de la máquina** (redirección a coljuegos.gov.co): las CSV llegan desde la réplica con `scripts.raw_transfer` (linaje verificado) | actualizar temporadas futuras | decisión de Simon sobre la vía de descarga |
| 14 | Elo | DONE | Elo V2 (K 20, local 65, multiplicador de margen), historia persistida, ordered logit; declina con < 10 partidos | HA por liga variable en el tiempo | sesgo en ligas con HA distinta | P0 del roadmap |
| 15 | Poisson | DONE | Maher con decaimiento y encogimiento elegidos en validación (rejilla que se amplía si el óptimo cae en el borde); intervalos Laplace | — | — | — |
| 16 | Dixon–Coles | DONE | ρ estimado conjuntamente; corrección inválida → declina | — | — | — |
| 17 | Calibración | FUNCTIONAL_BUT_IMMATURE | ECE por bins y diagramas de fiabilidad por modelo; check de calibración en el gate | recalibración (temperatura/isotónica) no ajustada; CORP | probabilidades mal calibradas en producción | ajustar en validación tras el backfill |
| 18 | Backtesting predictivo | DONE | walk-forward con reajuste diario y control de fuga por bloque; bootstrap por jornadas, DM-HLN, MDD, RPS, etiqueta de evidencia; sesión 2 de la réplica y **sesión 1 de la máquina reproducidas bit a bit** (5/5 idénticos) | MCS | — | — |
| 19 | Backtesting económico | FUNCTIONAL_BUT_IMMATURE | apuestas hipotéticas con IC del ROI y drawdown sobre precios de FD | CLV agregado; el ROI no informa con < 10.000 apuestas | sobrelectura del ROI | CLV con IC por bloques |
| 20 | Value Engine | BLOCKED_BY_DATA | EV en el límite inferior del intervalo, consenso de-vigged, regla versionada; test de pipeline de extremo a extremo | precios capturados reales | — | llega con las capturas |
| 21 | Pick Engine | BLOCKED_BY_DATA | picks shadow con ciclo de vida y eventos; publicar es imposible en el esquema | ídem | — | ídem |
| 22 | Settlement | BLOCKED_BY_DATA | liquidación a 90', cola de revisión, línea de valor | picks reales | — | ídem |
| 23 | Product API | DONE | **32 operaciones** bajo `/api/v1` (31 GET + `POST /analyst/ask`), solo lectura, envelope de 4 estados con motivo, 404/422/500 en JSON; `/matches/{id}/audit` y 6 de `/analytics`; **desplegada en la máquina** (`/health` 200) | — | — | — |
| 24 | Frontend | DONE | 15 rutas LIVE en modo live (inventario abajo); lint 0 errores, typecheck, build (también en la máquina); 84 E2E; **desplegado en la máquina y en GitHub/Lovable**; comprobado en Chrome contra los datos de la máquina (Matches, Match Center → Audit) | — | — | — |
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

## Hallazgos de la sincronización con la máquina (25 sep 2026)

1. **La Premier League está parada.** Su temporada 2026/27 tiene por primera vez un parón
   internacional de tres semanas entre finales de septiembre y principios de octubre:
   `/fixtures?date=2026-09-26` devuelve 1.214 partidos y ninguno de la Premier; el último
   partido guardado es del 14 sep. En Free (un día de visión) no hay nada que capturar hasta que
   vuelva. Para demostrar el ciclo en vivo se sigue **temporalmente la Segunda División** (141),
   que sigue jugando (`012073e`): 3 temporadas de historia de Free (2022–2024, 3 peticiones) y
   5 partidos el 25–26 sep; hay previsión donde los equipos tienen historia (Girona–Albacete,
   Granada–Andorra: Elo-ologit; Tenerife–Cádiz: los tres modelos) y donde no la hay el sistema
   no pronostica y dice por qué (un filial y un ascendido sin historia en las temporadas que
   Free sirve). Las previsiones se hacen con resultados que terminan en junio de 2025, y el
   linaje lo dice: **no son evidencia de calidad del modelo**, solo del ciclo.
2. **`ids=` rechazado en Free** (capa 05; `API_PLAN_CAPACITY_MODEL.md §5`): la sonda no puede
   cerrar la pregunta del plan de pago antes de pagar; se cierra en la primera hora del plan.
3. **Football-Data.co.uk bloqueado en la red de la máquina:** `http://football-data.co.uk`
   redirige a `coljuegos.gov.co` y HTTPS se corta (conexión reiniciada). Las 15 CSV (5 ligas ×
   2022–2024) llegaron desde la réplica con `scripts.raw_transfer` (`ea1d0c8`): cada fichero
   verificado por sha256 y por el hash de su cuerpo, filas insertadas bajo un run propio del
   ledger (`raw_transfer`, run 57) que dice el origen y el motivo, `fetched_at` original.
4. **NAME CHECK:** el id 63 es la tercera división francesa, que el proveedor ya llama
   "Ligue 3" (antes "National 1"). Id correcto; la configuración usa el nombre nuevo.
5. **3 resultados de la Premier del 13–14 sep** siguen "awaiting result" en la máquina: el
   worker estaba parado y Free ya no sirve esas fechas. Llegan con el tier 1.
6. **8 ficheros raw sin fila de índice** de antes del 25 sep (6 `/status` gratuitos, 1
   `/fixtures` anterior al ledger, 1 `/leagues`): documentados en `BACKUP_RECOVERY_TEST.md §4`.
7. **Procesos en la máquina:** lo que deja atrás un `wsl.exe` que termina muere con él (el
   primer `deps` en segundo plano no llegó a abrir su log). Las fases largas corren ahora en
   primer plano dentro de un `wsl.exe` oculto, igual que el worker, la API y la web.

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
