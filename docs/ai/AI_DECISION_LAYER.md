# Capa de decisión IA de PrediGol (`fbi.ai`)

*Versión de la capa: packet-v1 · rules-review-v1 · review-v2 · brief-v1 · day-v1 · match-analysis-v1 · pm-v1 ·
pm-v2 · learning-v1 · patterns-v1 · ai-gate-v1 · icc-v1 · daily-set-v3 · parlay-v4. Migraciones 0072-0073.
Escrito el 8 oct 2026; **V2** (el día de Bogotá, los tres pasos, L1/L2/L3, presupuesto adaptable de US$150,
post-mortems por selección y aprendizaje diario) el mismo día.*

La IA es la capa de razonamiento **sobre** el pipeline cuantitativo, no un reemplazo de él. Lee lo que la
plataforma ya mide (modelos, mercado, calidad de datos, bajas, alineaciones, calendario, tabla), le suma
noticias con procedencia cuando se configura una búsqueda, y **solo puede confirmar, rebajar, rechazar o
abstenerse** sobre lo que el pipeline ya eligió. No crea picks, no sube probabilidades, no toca reglas.

## 1. Principios (en código, no solo en documentos)

| Principio | Dónde se hace cumplir |
|---|---|
| La IA nunca altera producción por sí misma | escribe solo en el esquema `ai` y propone hipótesis `PROPOSED` (`fbi.research.evolution.propose`); no tiene permisos de escritura en `picks`, `models` ni reglas |
| Filtrar lo que ven los usuarios exige dos llaves | `fbi.ai.gating.enforcement`: `FBI_AI_MODE=enforce` **y** la última evaluación shadow (`engine=combined`) con veredicto `pass`; si no, modo shadow |
| Nada sin procedencia | cada bloque del paquete lleva su fuente (`sources`), cada evidencia su URL/dominio/nivel/fechas, cada afirmación de una revisión cita `P:<bloque>` o `E:<id>` |
| No inventar | `fbi.ai.claims.check`: un DATA debe citar el paquete y sus números deben estar en él; un NEWS debe citar evidencia no desactualizada; si no queda base, la revisión se abstiene |
| No llamar «value» sin cuota observable | sin precio: tarjeta `no_market` («MERCADO NO OBSERVADO»), con probabilidad, cuota justa y cuota mínima; nunca ventaja ni EV |
| Una llamada por partido, no por usuario | el worker calcula y guarda (`ai.match_packets`, `ai.pick_reviews`, `ai.match_analyses`); la API solo lee |
| Nunca pagar dos veces lo mismo | brief y revisión con entrada idéntica (hash) se reutilizan; una revisión vigente (sin cambio material: cuota ±3 %, evidencia nueva, alineaciones) se combina sin volver a llamar; una búsqueda con respuesta fresca en caché no se repite; un paso corre una vez por partido y día; un ciclo a la vez (candado) |
| Solo hoy y solo con mercado | modelos y web solo para los partidos de HOY (Bogotá) con mercado (`fbi.ai.day`); sin mercado: números del modelo y «mercado no observado», sin IA |
| Ningún gasto por usuario | todo lo calcula el worker; el parlay personal del usuario nunca llama a un modelo |
| Fallar hacia lo seguro | timeout, caída, respuesta inválida o presupuesto agotado → la revisión del modelo se abstiene y manda el revisor de reglas; el pipeline cuantitativo no depende de nada de esto |
| Auditoría completa | modelo, versión, `prompt_version`, `input_hash`, fuentes, evidencias, uso (tokens, caché, costo) por llamada; sin claves ni prompts guardados |
| Append-only | trigger `ai.refuse_change` en paquetes, revisiones, análisis, memoria, post-mortems, shadow, correlaciones y uso; la evidencia solo cambia de estado (con historial) |

## 2. El día de la IA (V2) y el ciclo (worker)

| Job | Cuándo | Qué hace |
|---|---|---|
| `ai_cycle` | cada 15 min (`FBI_AI_CYCLE_MINUTES`) | **gratis** para 4 días: evidencias del proveedor (48 h), shortlist con el filtro de valor (72 h), paquetes, reglas, análisis; **pagado** solo en los pasos debidos de los partidos de hoy con mercado |
| `ai_day_start` | 00:05 Bogotá | abre el día (`ai.day_plans`, etapa `opened`, con su presupuesto) y corre los primeros pasos |
| `ai_learn` | 07:35 Bogotá (+ recuperación si pasaron > 26 h) | post-mortems por partido (pm-v1) y por selección (pm-v2), notas del día anterior, estadísticas de fuentes, patrones → hipótesis (con modelo, máx. 2 al día), correlación semanal, shadow, alertas de presupuesto y **mañana preparado** (sin modelo ni búsqueda) |
| `ai_requests` | cada 2 min | ejecuta el «ejecutar ahora» del dueño (máx. 5 en cola); un partido de hoy se analiza como un paso |

**Los tres pasos** (`fbi.ai.day.due_pass`, una vez por partido y día, `ai.fixture_passes`):

| Paso | Cuándo | Qué |
|---|---|---|
| `first` | desde 00:05 Bogotá | paquete, **L1**, web para los candidatos y los partidos más importantes (`FBI_AI_MAX_WEB_FIRST`, 20), revisiones L2/L3 |
| `pre` | 6 a 4 h antes (hasta 90 min; ≥ 2 h después del primero) | lo que cambió: noticias, bajas, sanciones, cuotas; web solo para escalados (`FBI_AI_MAX_WEB_PRE`, 12) y solo si la caché venció |
| `final` | 100 a 10 min antes; espera alineaciones hasta 50 min antes | XI, portero, formación, bajas definitivas, mercado actualizado |

**Niveles:** **L1** (`bulk`, Haiku) brief de cada partido del día con mercado en cada paso, si su entrada cambió:
resumen, contexto, lesiones, cambios, calidad, incertidumbre, contradicción y por tarjeta «¿por qué?» / «¿qué
puede salir mal?» (afirmaciones tipadas y verificadas como las de una revisión). **Escala** el servidor, no el
modelo: candidato, brecha modelo-mercado ≥ 8 pts, movimiento ≥ 4 pts, noticia importante, alta incertidumbre,
contradicción (el brief solo puede añadir sus banderas). **L2** (`analysis`, Sonnet): los candidatos del día, de
nuevo solo tras un cambio material; un partido escalado sin candidato recibe a lo sumo una revisión «watch» de su
selección más cercana al valor (EV ≥ −2 %, `FBI_AI_MAX_WATCH_PER_DAY`, 8). **L3** (`final`, Opus): solo los 5
mejores candidatos del día (uno por partido), los picks del día, las piernas de los parlays, un candidato con
contradicción o noticia importante, y una revisión L2 que las reglas contradicen de plano (APPROVE↔REJECT).
Sin modelo disponible, el brief lo escriben las reglas (`engine=rules`). Un paso que el proveedor falló (caído,
timeout) no se registra y se reintenta en el ciclo siguiente; el resto del ciclo no vuelve a llamarlo.

Paquete (`fbi.ai.packet`): partido (estado, cambios de hora), tabla y lo que está en juego, forma, calendario
(descanso, rotación), H2H, Elo, estadísticas, bajas ponderadas por importancia del jugador, alineaciones,
viaje, mercado (Shin, apertura fija = primer consenso de la semana previa, movimiento, dispersión, nº de casas),
modelos (Dixon-Coles, Poisson, Elo-ologit con intervalos), calidad de datos y evidencias. Todo **as-of**: nada
registrado después del momento del paquete. Un paquete nuevo solo se guarda si el contexto cambió.

**Web (Exa).** Consulta en el idioma de la competición (español, portugués, inglés); dos cubetas por partido:
«temprana» (> 12 h, fresca 24 h) y «tardía» (≤ 12 h, fresca 4 h); se leen hasta 6 resultados, primero las fuentes
de mayor nivel (oficial → competición → club → periodista → medio → agregador → social/desconocida). La URL la
resuelve el servidor; cada evidencia guarda fuente, URL, dominio, nivel, fecha publicada y consultada, primera y
última vez vista (`last_seen_at`, `seen_count`). Una caída de la búsqueda se registra (costo 0) y el día sigue.

## 3. Revisores

* **Reglas (`rules-review-v1`, siempre, sin costo):** señales `hard` (partido aplazado/cancelado, datos no aptos,
  cuarentena, mercado fuertemente en contra, bajas clave del lado elegido), `soft`, `uncertain` y `positive`.
  `REJECT` con una dura o 3 suaves; `DOWNGRADE` con una suave o 2 incertidumbres; si no, `APPROVE`; sin
  mercado, `ABSTAIN`.
* **Modelo de lenguaje (`review-v1`, opcional):** recibe el paquete, la candidata y las señales; responde JSON
  validado (`ReviewOut`) con afirmaciones tipadas (DATA/INFERENCE/NEWS/OPINION/UNKNOWN). El servidor
  recalcula la cuota justa y la mínima (no confía en las del modelo) y descarta afirmaciones sin base.
* **Combinada:** la más conservadora de las opiniones (ignorando abstenciones).

**Presupuesto (V2, `fbi.ai.usage`).** Tope mensual duro (`FBI_AI_MONTHLY_BUDGET_USD`, en el portátil US$150) y
objetivo diario blando (`FBI_AI_DAILY_TARGET_USD`, US$5). El presupuesto del día se adapta: *ritmo* = lo que queda
del mes antes de hoy / días que quedan; *carga* = partidos con mercado de hoy / los de un día típico (mediana de 14
días), entre 0,5 y `FBI_AI_DAILY_MAX_FACTOR` (2); presupuesto = ritmo × carga (≤ objetivo × factor, ≤ lo que
queda); techo = 1,5 × presupuesto (≤ lo que queda). Estados: NORMAL · REDUCED ≥ 100 % del día (sin nivel final) ·
CHEAP_ONLY ≥ 125 % (solo L1, sin web) · EXHAUSTED en el techo o con el mes gastado (solo reglas). Cada paso tiene su
parte para L2/L3/web: el primero hasta 55 % del día, el segundo hasta 75 %, el final el resto. Alertas al 70, 85,
95 y 100 % del mes, una vez cada una (`ai.budget_alerts`), enviadas por el notificador (`ai_budget`). La
proyección del mes usa el ritmo de los últimos 7 días completos.

**Claude 5.5 (8-oct-2026, primeras llamadas reales).** No acepta un `tool_choice` forzado: se le pide con `auto` y la
instrucción de responder solo con la herramienta. Piensa antes de responder (pensamiento adaptativo, cobrado como
salida y contado en `max_tokens`): el esfuerzo se fija por nivel (`output_config.effort`: masivo `low`, análisis y
final `medium`) y `max_tokens` deja sitio (revisión 8.000). Con 1.200 las respuestas de `review-v1` salían cortadas;
`review-v2` es la misma consigna con estos parámetros, y una revisión de una versión anterior no frena una nueva.

## 4. Producto

* **Partido → «Análisis PrediGol»:** hasta 3 tarjetas (mercado, selección, cuota y casa, probabilidad modelo y
  mercado, cuota justa, cuota mínima, ventaja, veredicto, confianza, razón, riesgos). Un usuario ve solo las
  de picks calificados y la vista sin mercado; las de evaluación son la vista previa del dueño.
* **Picks del día / parlays:** cada selección guarda la revisión vigente al congelarse (`inputs.ai`). En shadow
  se muestra y no cambia nada; con enforcement, un `REJECT` queda fuera (y en parlays también `DOWNGRADE`).
* **Parlays (`parlay-v4`):** máx. 2 piernas por competición, ≥ 3 casas por pierna, intervalo ≤ 0,40,
  probabilidad conjunta con la correlación medida (ICC por competición-día, Bahadur de 2.º orden); estados de
  progreso OPEN / PARTIAL_WON / PARTIAL_LOST / WON / LOST / VOID; visible hasta liquidarse.
* **Mis picks / armador:** cuota combinada, probabilidad de mercado y del modelo (en evaluación), valor
  esperado, riesgo, nº de selecciones, avisos de dependencia medida — sin llamadas a IA.

## 5. Aprendizaje diario (nunca automático)

OBSERVACIÓN → PATRÓN → HIPÓTESIS → MUESTRA SUFICIENTE → EXPERIMENTO → BACKTEST → SHADOW → COMPARACIÓN CON
MERCADO → APROBACIÓN DEL DUEÑO. Nada aquí ejecuta `adjust_weights` ni cambia una regla.

* **Post-mortem por selección (`pm-v2`, `ai.pick_postmortems`):** picks del día, piernas de parlay, todo lo que
  revisó un modelo y lo revisado en partidos con paso. Diez preguntas respondidas con lo guardado antes del
  partido y el resultado (¿qué esperaba PrediGol?, ¿qué ocurrió?, ¿falló el modelo?, ¿falló la información?,
  ¿había una señal ignorada?, ¿se movió la cuota?, ¿existía una baja importante?, ¿cambió la alineación?, ¿la
  incertidumbre estaba subestimada?, ¿fue varianza?) y la clase de una pérdida, la primera que aplica:
  DATA_ERROR → EXECUTION_ERROR → CONTEXT_ERROR → MARKET_ERROR (CLV ≤ −3 %) → MODEL_ERROR (modelo ≥ 8 pts sobre el
  cierre) → NORMAL_VARIANCE → UNKNOWN. Narrativa con Haiku (máx. 12) y Sonnet para pérdidas de picks del día (3).
* **Notas del día (`ai.learning_notes`, QUÉ APRENDIÓ PREDIGOL HOY):** resumen, aprobadas perdidas por clase,
  rechazos (acertados / habrían ganado), contexto que falló, noticias confirmadas o desmentidas por la alineación,
  bajas, mercado (CLV), modelo frente al cierre, fuentes; y hasta 3 lecciones de Sonnet que citan las notas.
* **Patrones → hipótesis:** fiabilidad por nivel de fuente, señales de revisión, ligas (z ≥ 3) y, en V2, clases
  de pérdida (≥ 20 pérdidas, z ≥ 2 frente a un reparto parejo); cada propuesta lleva nº de partidos, impacto
  potencial y costo de investigarla. Una hipótesis de la IA sin referencias a la memoria se rechaza. Promover
  exige `DONE` con `gate_passed=true` y la palabra escrita por el dueño.

## 6. Evaluación shadow de la IA (`ai-gate-v1`)

Ventana 60 días; grupos: modelo solo, modelo + IA (sin rechazados), aprobados, con cautela, rechazados,
abstenciones; métricas: n, acierto, ROI, EV declarado y de mercado, CLV, log loss y Brier (modelo y mercado),
ECE, drawdown. La puerta pide ≥ 300 selecciones, ≥ 30 días, ≥ 50 rechazos, calidad de rechazo z ≥ 2 (bootstrap
por partido), CLV de lo conservado ≥ CLV de lo rechazado y calibración no peor (+0,002).

## 7. Configuración (variables)

`FBI_AI_MODE` (off | shadow | enforce) · `FBI_AI_MODEL_BULK|ANALYSIS|FINAL` («proveedor:modelo») ·
`FBI_AI_KEY_<PROVEEDOR>` · `FBI_AI_MONTHLY_BUDGET_USD` (20; portátil 150) · `FBI_AI_DAILY_TARGET_USD` (mes/30;
antes `FBI_AI_DAILY_BUDGET_USD`) · `FBI_AI_DAILY_MAX_FACTOR` (2) · `FBI_AI_MAX_LLM_REVIEWS_PER_DAY` (60) ·
`FBI_AI_MAX_DEEP_PER_DAY` (10) · `FBI_AI_MAX_WEB_FIRST` (20) · `FBI_AI_MAX_WEB_PRE` (12) ·
`FBI_AI_MAX_WATCH_PER_DAY` (8) · `FBI_AI_SEARCH` (exa | brave | tavily | none) · `FBI_AI_HORIZON_HOURS` (96) ·
`FBI_AI_CYCLE_MINUTES` (15) · `FBI_AI_MULTIMODAL` (off). Un modelo solo se activa con su
`FBI_AI_MODEL_*`: la configuración antigua del analista no enciende esta capa.

Se leen del entorno del proceso **y** del `.env` del backend (`fbi.core.env`: el proceso gana), como el resto de
la configuración; en el portátil (`scripts/dev-up`) nada exporta el `.env`. Cada ciclo relee el archivo: una clave
nueva se usa desde el ciclo siguiente, sin reiniciar. Las claves se guardan con `scripts/set-secret NOMBRE`
(entrada oculta, archivo solo legible por su dueño, nunca se imprimen).

## 8. Herramientas

* `python -m scripts.ai_replay --dsn …` — replay del revisor de reglas sobre los picks históricos (as-of).
* `python -m scripts.ai_simulate --dsn <copia> --start … --days 3 --search` — mide en una **copia** cuántas
  llamadas haría la capa y las cotiza con cada perfil de proveedor.
* Admin Console → «Capa de decisión IA» (presupuesto, proyección, alertas, eficiencia, stack real, comparación
  shadow), «IA e investigación» (HOY, INVESTIGACIONES, POST-MORTEMS, APRENDIZAJE, FUENTES, COSTOS) y «Evolución»
  (EL DÍA EN PREDIGOL AI, QUÉ APRENDIÓ PREDIGOL HOY, MEJORAS PROPUESTAS).
* API (solo lectura, SUPER_ADMIN): `/admin/ai/overview`, `/today`, `/research`, `/postmortems`, `/learning`,
  `/sources`, `/costs`, `/comparison`, `/reviews`, `/evidence`, `/packets/{id}`, `/memory`, `/shadow`; producto:
  `/matches/{id}/analysis` (el brief y las notas por tarjeta solo en la vista del dueño o con enforcement).
