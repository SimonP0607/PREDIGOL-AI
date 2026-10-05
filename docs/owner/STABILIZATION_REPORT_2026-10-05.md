# PrediGol — informe de estabilización (5 oct 2026)

Fase de estabilización integral y preparación comercial. Todo lo de abajo está medido en la base de datos, el código,
los logs o el proveedor, con el comando o el archivo que lo respalda; nada se ha dado por bueno por verlo en la UI.

```text
PREDIGOL STABILIZATION REPORT
Fecha: 2026-10-05 (cierre 09:00 UTC aprox.)
Commit backend: ef573af (código = 5021d04; este informe va en un commit de documentación posterior)
Commit frontend: f482844
Schema: 0064 (head)

SYSTEM
worker: OK — vivo, latido < 5 min; heartbeat + watchdog activos; 0 ejecuciones atascadas; compilación = código del backend
database: OK — PostgreSQL 16, 9,0 GB, esquema 0064
api: OK — /health 200; API, base, worker y proveedor en OK
frontend: OK — build, 110 tests unitarios y 53 e2e en verde; consola local en 127.0.0.1:5173 (sin despliegue público)

PICKS
ready for users: NO
reason: ningún modelo supera al mercado sin margen (8/8 RECHAZADOS, +0,018 a +0,119 de log loss, IC 95 % > 0, ningún peso de mezcla > 0); los picks shadow no tienen ventaja: ROI +5,5 % con IC por partido [−16,9 %, +26,9 %] en 181 partidos, VE frente al consenso sin margen −4,6 % ± 0,4, VE frente al cierre de Pinnacle sin margen −1,0 % [−2,1 %, +0,0 %]; dataset VALIDATED, no promovido
qualified models: 0
publication status: desactivada por restricción de la base de datos; KEEP_SHADOW = YES

MODELS
champion: el mercado — Pinnacle al cierre sin margen (power), log loss 0,95967 en 1.751 partidos 2024/25
challengers: 0
market baseline: Pinnacle cierre de-vig (power/shin); el promedio de casas al cierre (shin) empata en 0,95967
qualified: 0
key finding: los modelos solo usan información que el mercado ya incorpora (goles, Elo, forma, tiros agregados) y son sobreconfiados en lo que seleccionan (VE prometido +29 % frente a −4,6 % real); la única vía con evidencia publicada es información nueva (xG/tiros, alineaciones confirmadas) — 5 experimentos definidos con criterios de aprobación

BACKTESTING
sample: 1.756 partidos de prueba (Premier League, LaLiga, Bundesliga, Serie A, Ligue 1, 2024/25); validación 2023/24
protocol: walk-forward con reajuste diario; corte 60 min antes del primer partido del bloque; solo resultados públicos 3 h tras el inicio; hiperparámetros solo en validación; IC remuestreando jornadas; re-ejecutado en seco el 5 oct 07:55 UTC sobre los datos reparados (no guarda: ningún dataset es MODEL_READY)
market comparison: todos los modelos peores que el cierre sin margen; ninguna mezcla con el mercado lo mejora (ΔLL −0,0009…0,0000, IC cruzan 0)
best result: ensamble 0,97928 = +0,0182 [+0,0105, +0,0261] frente al mercado (sigue siendo peor)

DATA TRUTH
datasets: 14 — 10 al día, 3 incompletos por el primer llenado de los feeds de referencia (jugadores, plantillas, entrenadores), 1 sin nada que medir ahora (en vivo)
model-ready: 16 temporadas-competición MODEL_READY; versión de datos DATASET_V2 VALIDATED (reconstruida 5 oct 08:14 UTC, todas las puertas pass/note), promoción pendiente del dueño
high issues: última auditoría (#6, 370 peticiones) 0; registro de evidencias: 1 abierta del proveedor (tabla Ligue 1 2025/26 frente a la decisión de la LFP) y 3 propias en seguimiento (3 payloads RAW dañados el 4 oct 02:57, 40 filas, causa corregida)
critical issues: 0

DATA QUALITY
stuck runs: 0
failed 24h: 17 — todas del 4 oct 10:18–11:11 (CheckViolation del pipeline de picks, corregida); salen de la ventana a las 11:11 UTC
provider errors: 8 en 24 h — límite por minuto del 5 oct 02:46 (corregido: límite compartido entre procesos), 6 de una auditoría con player=0 y 1 conexión reiniciada
stale fixtures: 0 (precios atrasados 0; 2 partidos sin cerrar por el proveedor)
odds coverage: 89 % de lo que el proveedor cotiza (80/90 en 96 h); 50 % de todos los previstos; precio final pre-partido 65 % (7 d)

API
plan: Ultra, activo hasta el 29 oct 2026 04:31 UTC (renovar es decisión del dueño)
provider limit: 75.000 peticiones/día · 450/min
internal budget: 60.000/día, contado en la base antes de cada petición; límite por minuto compartido
today: 15.927 a las 08:45 UTC — sobre todo cargas únicas: migración 5.787 (terminada), primer llenado de la referencia 4.800, auditorías 1.110; captura pre-partido 2.631, en vivo 756
daily median: 6.133 (5 días completos, con cargas únicas) · régimen estable 6.018
P95: 24.761 medido (con migración) · 8.153 en régimen estable
historical max: 29.418 (4 oct: migración + captura antes del arreglo de re-preguntas)
safe headroom: ~51.800/día en un día P95 estable (86 % del presupuesto interno libre)

+50 LEAGUES
possible: YES — la API y el almacenamiento lo permiten; recomendado por tandas de 10–25 y con la retención diseñada
estimated P95 requests: 11.430/día (19 % del presupuesto interno)
recommended leagues: Veikkausliiga, Primera División URU, División Profesional PAR, Botola Pro, National League ENG, Primera Nacional ARG, USL Championship, 1.ª RFEF G1/G2, J2/J3, Prva Liga SRB, Ligue 3… (las 50 en API_CAPACITY.md)
risk: +43 % de crecimiento de la base (127,5 GB a 12 meses sin retención), cobertura irregular en ligas menores; no cambia la decisión de picks

API-FOOTBALL
endpoints reviewed: 38
fully integrated: 34
partial: 4 (/venues, /players, /players/teams, /odds/mapping)
missing useful: 0 (todo lo que responde el proveedor queda en RAW)
recommended additions: /odds/mapping en el planificador (no preguntar partidos sin cuotas); lectura de alineaciones ~T-40 min para features de alineación; medir la cobertura real de /injuries antes de usarla; normalizar más mercados de /odds desde RAW solo cuando un modelo los pida; /predictions solo como benchmark (nunca input)

STORAGE
current PostgreSQL: 9,0 GB
current raw: 0,7 GB (0,86 GB en disco)
growth/day: ≈ 233 MB de base (147 MB precios en vivo) + 62 MB de RAW
30d: 15,9 GB base · 32,5 GB total con copias
6m: 50,4 GB base · 125,9 GB total (36,8 / 101,4 con retención)
12m: 92,1 GB base · 232,5 GB total (52,1 / 160,9 con retención)
+50 leagues 12m: 127,5 GB base · 323,2 GB total (70,6 / 221,5 con retención)

DEPLOYMENT
MVP/month: €12,24 ($13,74) — Hetzner CX33 + copias + B2 + dominio (+€6–11 de volumen para el crecimiento; €44,64 si la CX33 sigue sin stock)
Recommended/month: $95,63 (€85,19) — DigitalOcean Frankfurt con PostgreSQL gestionado y PITR (alt. Hetzner dos servidores €74,50)
HA/month: $168,90 (€150,47) — AWS Ohio, dos zonas, RDS Multi-AZ

AI
recommended provider/model options: 1) OpenAI gpt-6.1-sol + gpt-6-luna (Flex/lote; residencia UE +10 %); 2) Anthropic Claude Sonnet 5.5 + Haiku 4.5, Opus 5.5 para la revisión diaria (UE vía Bedrock/Google Cloud); 3) Google Gemini 3.1 Flash-Lite / 3.1 Pro (presupuesto)
estimated monthly low: $9–42 (50–100 tareas/día)
medium: $56–165
high: $191–875
implementation status: DEFERRED

COMMERCIAL
trial: FREE €0 + 7–14 días de PRO sin tarjeta
standard: €4,99–6,99/mes (€39–59/año)
pro: €12,99–17,99/mes (€99–149/año)

QA
backend tests: 1.582 passed (máquina y nube); ruff 0; mypy 0 errores en 578 archivos
frontend tests: 110 unitarios; typecheck 0; lint 0 errores (26 avisos previos); build OK
browser tests: e2e Playwright 53 passed; QA de los 20 módulos en ES (EN comprobado) con 27 capturas reales
security: escaneo de la clave de API-Football (por valor, sin mostrarla): 0 en ambos historiales git, 0 en ambos árboles, 0 en logs, scratch, informes y 400 payloads RAW; admin protegido por rol en API y UI; SECURITY_ACTION: rotación recomendada posteriormente
backup restore: POST_STABILIZATION_20261005 — volcado 596 MB (1.193 entradas) y RAW 47.766 ficheros con SHA-256 OK, etiquetas en ambos repos; restauración en base temporal rc=0 en 91 s: 114 tablas, 112 iguales, 2 crecieron desde el volcado, 0 con menos filas, 48.368.383 filas

FINAL DECISION
Can PrediGol publish picks today: NO
Can PrediGol deploy online today: NO
Can we add 50 leagues: YES
Next safest action: mantener shadow; decidir la renovación de API-Football antes del 29 oct; revisar DATASET_V2 y, si se aprueba, descongelar la investigación y promoverlo; correr en shadow los experimentos 1–3 (mezcla con el cierre, fiabilidad de la ventaja, CLV sin margen); diseñar y probar la retención de precios en vivo antes de 90 días
```

## Qué se arregló hoy (cada arreglo con su test de regresión)

| Problema encontrado | Arreglo | Test |
|---|---|---|
| Ejecuciones atascadas > 2 h, estados sin cierre | latido + vigilante; estados running → completed / partial / failed / aborted / interrupted / stale | `test_worker_heartbeat`, `test_run_watchdog` |
| "Proveedor DEGRADED" por errores que no eran del proveedor | clasificación de errores (base de datos, topes, plazos no cuentan) | `test_provider_error_kind`, `test_health_and_quality` |
| La captura volvía a preguntar cada ciclo por partidos sin cuotas (~8.000 peticiones/día) | una pregunta por ventana, registrada en `market.odds_asks`; ligas sin cuotas no se preguntan | `test_odds_capture` |
| Límite por minuto por proceso: el proveedor rechazó peticiones (5 oct 02:46) | límite por minuto compartido en la base | `test_run_watchdog` (límite por minuto compartido) |
| `goals_prevented` negativo descartado (14.442 filas) | normalizador con signo y reparación con rastro en `audit.data_repairs` | `test_repair_signed_team_stats` |
| ROI de Rendimiento con un ± engañoso (±6 por picks) | intervalo agrupado por partido (±23 sobre 181 partidos) | `test_performance_interval` |
| Cada despliegue creaba versiones nuevas de todos los modelos | versión = huella del código de modelos | `test_model_code_version`, `test_pick_pipeline` |
| El pipeline guardaba el mismo vector de features cada 30 min (73 % duplicados) | no se guarda un vector idéntico al último | `test_pick_pipeline` |
| La investigación semanal "tocaba" tras cualquier despliegue; la página no decía que estaba congelada | se compara el código de modelos y la versión del dataset; la página muestra el congelado | `test_research_due`, `test_evolution` |
| Rankings mezclaba hombres, mujeres y juveniles | grupo de rating por equipo | `test_rankings_pools` |
| Textos del backend en inglés en la consola en español | códigos estables traducidos (salud, incidencias, auditoría, tareas, picks, IA) | `healthReason.test`, `auditDetail.test`, `evolutionDue.test` |
| CLV contra Pinnacle sin quitar su margen (+4,7 % engañoso) | VE contra el cierre de Pinnacle sin margen (−1,0 %) | `test_shadow_evaluation` |
| Sin previsión de almacenamiento | `scripts.storage_forecast` | `test_storage_forecast*` |

## Documentos

| Documento | Contenido |
|---|---|
| `PREDIGOL_ADMIN_GUIDE.md` / `.pdf` | guía del dueño con 27 capturas reales; backtesting y Evolución explicados |
| `PICKS_DECISION_2026-10-05.md` | la decisión de picks, el backtesting en sencillo, la descomposición del error, literatura y experimentos |
| `API_CAPACITY.md` | consumo medido, percentiles, escenarios +25/+50/+75, 50 ligas candidatas |
| `API_FOOTBALL_ENDPOINT_MATRIX.md` | los 38 endpoints: qué ingerimos, qué guardamos, qué usamos, valor y prioridad |
| `STORAGE_FORECAST.md` | tamaño, crecimiento, proyección y retención HOT/WARM/COLD |
| `DEPLOYMENT_COSTS.md` | MVP / recomendado / alta disponibilidad, con precios del 5 oct |
| `AI_COSTS_AND_ARCHITECTURE.md` | precios de IA, coste por escenario y arquitectura futura (DEFERRED) |
| `COMMERCIAL_PLANS.md` | planes, comparables y cumplimiento |

## Decisiones que son del dueño (no se ha hecho nada de esto)

1. Renovar (o cambiar) el plan de API-Football antes del 29 oct 2026.
2. Rotar la clave de API-Football (se vio en capturas del panel del proveedor) y actualizar el servidor a la vez.
3. Revisar DATASET_V2, retirar `data/research.frozen` y promoverlo (o no).
4. Contratar hosting y desplegar; antes, revisión legal y desactivar las cuentas QA.
5. Configurar (o no) un proveedor de IA y su tope mensual.
