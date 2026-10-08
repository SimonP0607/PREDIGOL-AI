# Capa de decisión IA de PrediGol (`fbi.ai`)

*Versión de la capa: packet-v1 · rules-review-v1 · review-v2 · match-analysis-v1 · pm-v1 · patterns-v1 ·
ai-gate-v1 · icc-v1 · daily-set-v3 · parlay-v4. Migración 0072. Escrito el 8 oct 2026.*

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
| Nunca pagar dos veces lo mismo | revisión con entrada idéntica (hash) se reutiliza; una revisión vigente (< 6 h, sin cambio material) se combina sin volver a llamar |
| Fallar hacia lo seguro | timeout, caída, respuesta inválida o presupuesto agotado → la revisión del modelo se abstiene y manda el revisor de reglas; el pipeline cuantitativo no depende de nada de esto |
| Auditoría completa | modelo, versión, `prompt_version`, `input_hash`, fuentes, evidencias, uso (tokens, caché, costo) por llamada; sin claves ni prompts guardados |
| Append-only | trigger `ai.refuse_change` en paquetes, revisiones, análisis, memoria, post-mortems, shadow, correlaciones y uso; la evidencia solo cambia de estado (con historial) |

## 2. El ciclo (worker)

| Job | Cuándo | Qué hace |
|---|---|---|
| `ai_cycle` | cada 30 min (`FBI_AI_CYCLE_MINUTES`) | evidencias del proveedor (48 h), shortlist con el mismo filtro de valor de los picks del día (72 h), web opcional (36 h, 2 búsquedas máx. por partido), paquetes, revisiones, análisis |
| `ai_learn` | 07:35 Bogotá (+ recuperación si pasaron > 26 h) | post-mortems y memoria, patrones → hipótesis (con modelo los lunes), correlación semanal entre piernas, evaluación shadow de la IA |
| `ai_requests` | cada 2 min | ejecuta el «ejecutar ahora» del dueño (máx. 5 en cola) |

Paquete (`fbi.ai.packet`): partido (estado, cambios de hora), tabla y lo que está en juego, forma, calendario
(descanso, rotación), H2H, Elo, estadísticas, bajas ponderadas por importancia del jugador, alineaciones,
viaje, mercado (Shin, apertura fija = primer consenso de la semana previa, movimiento, dispersión, nº de casas),
modelos (Dixon-Coles, Poisson, Elo-ologit con intervalos), calidad de datos y evidencias. Todo **as-of**: nada
registrado después del momento del paquete. Probabilidades redondeadas a 3 decimales y marcas de tiempo en
`sources`: un paquete nuevo solo se guarda si el contexto cambió. Un partido sin candidatas se revisa cada hora (cada 3 h si falta más de un día). Medido en un día real simulado: 3,2 paquetes por partido y día y ~7 MB/día en el esquema `ai` (~210 MB/mes).

## 3. Revisores

* **Reglas (`rules-review-v1`, siempre, sin costo):** señales `hard` (partido aplazado/cancelado, datos no aptos,
  cuarentena, mercado fuertemente en contra, bajas clave del lado elegido), `soft`, `uncertain` y `positive`.
  `REJECT` con una dura o 3 suaves; `DOWNGRADE` con una suave o 2 incertidumbres; si no, `APPROVE`; sin
  mercado, `ABSTAIN`.
* **Modelo de lenguaje (`review-v1`, opcional):** recibe el paquete, la candidata y las señales; responde JSON
  validado (`ReviewOut`) con afirmaciones tipadas (DATA/INFERENCE/NEWS/OPINION/UNKNOWN). El servidor
  recalcula la cuota justa y la mínima (no confía en las del modelo) y descarta afirmaciones sin base.
* **Combinada:** la más conservadora de las opiniones (ignorando abstenciones).

Niveles: `bulk` (extracción de noticias, narrativas), `analysis` (revisiones de las próximas 24 h), `final`
(las mejores del día, máx. `FBI_AI_MAX_DEEP_PER_DAY`). Presupuesto diario y mensual único para toda la IA:
NORMAL < 70 % · REDUCED ≥ 70 % (sin nivel final) · CHEAP_ONLY ≥ 90 % · EXHAUSTED ≥ 100 % (solo reglas).

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

## 5. Aprendizaje (nunca automático)

OBSERVAR → MEMORIA → HIPÓTESIS → (dueño) INVESTIGAR / APROBAR EXPERIMENTO → BACKTEST → SHADOW → EVALUACIÓN →
(dueño) PROMOCIÓN. Los post-mortems escriben `ai.memory_events`; los patrones solo proponen con z ≥ 3 y muestra
mínima; una hipótesis de la IA sin referencias a la memoria se rechaza. Promover exige `DONE` con
`gate_passed=true` y la palabra escrita por el dueño; registra la decisión, el cambio sale como versión propia.

## 6. Evaluación shadow de la IA (`ai-gate-v1`)

Ventana 60 días; grupos: modelo solo, modelo + IA (sin rechazados), aprobados, con cautela, rechazados,
abstenciones; métricas: n, acierto, ROI, EV declarado y de mercado, CLV, log loss y Brier (modelo y mercado),
ECE, drawdown. La puerta pide ≥ 300 selecciones, ≥ 30 días, ≥ 50 rechazos, calidad de rechazo z ≥ 2 (bootstrap
por partido), CLV de lo conservado ≥ CLV de lo rechazado y calibración no peor (+0,002).

## 7. Configuración (variables)

`FBI_AI_MODE` (off | shadow | enforce) · `FBI_AI_MODEL_BULK|ANALYSIS|FINAL` («proveedor:modelo») ·
`FBI_AI_KEY_<PROVEEDOR>` · `FBI_AI_DAILY_BUDGET_USD` (1,00) · `FBI_AI_MONTHLY_BUDGET_USD` (20) ·
`FBI_AI_MAX_LLM_REVIEWS_PER_DAY` (60) · `FBI_AI_MAX_DEEP_PER_DAY` (10) · `FBI_AI_SEARCH` (exa | brave | tavily
| none) · `FBI_AI_HORIZON_HOURS` (96) · `FBI_AI_MULTIMODAL` (off). Un modelo solo se activa con su
`FBI_AI_MODEL_*`: la configuración antigua del analista no enciende esta capa.

Se leen del entorno del proceso **y** del `.env` del backend (`fbi.core.env`: el proceso gana), como el resto de
la configuración; en el portátil (`scripts/dev-up`) nada exporta el `.env`. Cada ciclo relee el archivo: una clave
nueva se usa desde el ciclo siguiente, sin reiniciar. Las claves se guardan con `scripts/set-secret NOMBRE`
(entrada oculta, archivo solo legible por su dueño, nunca se imprimen).

## 8. Herramientas

* `python -m scripts.ai_replay --dsn …` — replay del revisor de reglas sobre los picks históricos (as-of).
* `python -m scripts.ai_simulate --dsn <copia> --start … --days 3 --search` — mide en una **copia** cuántas
  llamadas haría la capa y las cotiza con cada perfil de proveedor.
* Admin Console → «Capa de decisión IA» y «Evolución».
