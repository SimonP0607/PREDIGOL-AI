# El ciclo de la IA y cómo aprende PrediGol (F8, F9, F11, F13, F14)

Este documento resume las piezas que ya existían y lo que se añadió el 9 de octubre. Garantía de fondo: **la IA
nunca modifica producción por sí misma.** Funciona en modo sombra; sus registros no se pueden reescribir (solo se
añaden); un pick prepartido queda congelado por un trigger; y para promover cualquier cosa hacen falta un
experimento, una prueba superada y la decisión explícita del dueño.

> **Después de F8 (23 oct 2026):** donde este documento habla del post-mortem de una selección hay **uno solo**, `pm-v6`
> (`fbi.intel.postmortem`, tabla `intel.postmortems`), armado por reglas a coste cero; los dos que escribía la IA (`pm-v1.1` por partido,
> `ai.postmortems`, y `pm-v2` por selección, `ai.pick_postmortems`) están congelados y siguen legibles. La narrativa de un modelo
> es aparte y opcional (`ai.postmortem_narratives`). La memoria con confianza y evidencia (`memory-v4`) y su página están en
> **Admin → Memoria**. Todo lo que cambió y por qué está en `docs/owner/POSTMORTEM_MEMORIA_F8.md`.

## 1. El ciclo formal (F8)

| Paso | Qué hace | Dónde | Registro |
|---|---|---|---|
| **LEER** | Junta los datos del partido: forma, tabla, bajas, alineaciones, mercado y su movimiento | `fbi.ai.packet` | `ai.match_packets` |
| **EVALUAR** | Pasa cada selección por las reglas: precio, discrepancia con el mercado, datos que faltan | `fbi.ai.review` | `ai.pick_reviews` (motor `rules`) |
| **INVESTIGAR** | Busca en la web solo los partidos que lo merecen y cuando la caché está vieja | `fbi.ai.collectors`, `fbi.ai.cache` | `ai.evidence`, `ai.research_cache` |
| **REDACTAR** | Escribe el resumen y el porqué con un modelo de lenguaje (económico por defecto) | `fbi.ai.brief`, `fbi.ai.analysis` | `ai.match_briefs`, `ai.match_analyses` |
| **SELECCIONAR** | Decide **APROBADO**, **CAUTELA**, **RECHAZADO** o **SIN JUICIO** | `fbi.ai.review` (motor `combined`) | `ai.pick_reviews` |
| **MEDIR** | Compara la decisión con el resultado y con el cierre (un solo post-mortem por selección, `pm-v6`); contrasta la IA con el modelo y con el mercado en sombra | `fbi.intel.postmortem` (antes `fbi.ai.pick_postmortem`), `fbi.ai.shadow` | `intel.postmortems` (antes `ai.pick_postmortems`), `ai.shadow_reports` |
| **APRENDER** | Escribe las notas del día, con la evidencia que las respalda, y la memoria con su confianza (`memory-v4`) | `fbi.ai.learning` (07:35 Bogotá), `fbi.intel.memory` (07:50) | `ai.learning_notes`, `intel.entity_memory` |
| **PROPONER** | Convierte los patrones en hipótesis para el dueño; nunca en cambios | `fbi.ai.patterns`, `fbi.research.evolution` | `analytics.research_hypotheses` |
| **CERRAR EL DÍA** *(nuevo)* | A las 23:59 escribe el cierre del día y lo revisa mientras algo de ese día cambie | `fbi.ai.daily_review` | `ai.daily_reviews` |

## 2. Hechos, patrones e hipótesis, por separado (F13)

| Tipo | Qué es | Dónde vive | Ejemplo |
|---|---|---|---|
| **Hecho** | Un registro de lo que pasó | picks, resultados, post-mortems, `v_pick_record` | «El empate de Daejeon se tomó a 3,61 y perdió 2-1» |
| **Patrón estadístico** | Algo que se repite, a 3 o más errores típicos y con muestra mínima | `ai.memory_events` (`*_pattern`) | «En la liga X el modelo pierde frente al cierre en log loss» |
| **Hipótesis de la IA** | Una propuesta que se puede probar, con lo que cambiaría y lo que costaría investigarla | `analytics.research_hypotheses` | H-F17-1: encoger la probabilidad del modelo hacia la del mercado |

Las pantallas nunca los mezclan. En Memoria por partido solo hay hechos; en Evolución, patrones e hipótesis; y el
cierre del día los cuenta en apartados distintos.

## 3. Sin sobreajuste (F11)

**Observación → repetición → patrón → hipótesis → experimento → backtesting → sombra → comparación con el mercado
→ promoción manual.**

- **Observación:** un post-mortem o una nota del día.
- **Repetición y patrón:** `fbi.ai.patterns` solo acepta un patrón a 3 o más errores típicos y con muestra mínima
  (30 informes de una fuente, 50 selecciones con una señal, 30 partidos de una liga, 20 pérdidas de una clase).
- **Hipótesis:** estado `PROPOSED`. El dueño puede responder `REJECTED`, `INVESTIGATING` o `ACCEPTED`.
- **Experimento, backtesting y sombra:** estados `RUNNING` → `SHADOW` → `DONE`, con su resultado (`gate_passed`).
- **Promoción manual:** estado `PROMOTED`, solo a mano del dueño y solo si el experimento pasó la prueba
  (`fbi.research.evolution.promote`).

Un solo día no prueba nada. Por eso los cinco picks del 9 oct quedan como hechos, los empates de `elo_ologit`
quedan en observación, y solo el patrón de sobreconfianza (8.822 selecciones) llega a hipótesis.

## 4. Memoria por partido (F9) y reutilización (F14)

**Admin → Memoria** (desde F8; antes estaba repartida en cuatro sitios). Se busca por equipo, liga, entrenador, jugador, mercado, rango de
cuota y modelo. Cada partido muestra:

- **ANTES:** el último resumen de la IA antes del saque (con la calidad de datos y la incertidumbre), sus decisiones
  y los picks en sombra (mercados y modelos);
- **DESPUÉS:** el marcador a 90 minutos, cómo se liquidaron los picks (ganados, perdidos, P&L), las clases de los
  post-mortems, si los aciertos fueron merecidos o con suerte, y los eventos de memoria.

**No es otra tabla:** son los propios registros leídos juntos (`fbi.api.services.match_memory`), así que no se
desincronizan. Las mismas fuentes alimentan el cierre del día, el post-mortem, el aprendizaje, la comparación en
sombra y las pantallas, sin silos.

## 5. Post-mortems también de los aciertos (F10)

Cada selección relevante (los picks del día, las piernas de parlay y todo lo que revisó la IA) recibe su
post-mortem, gane o pierda.

- **Pérdidas:** se clasifican en MODEL_ERROR, CONTEXT_ERROR, DATA_ERROR, MARKET_ERROR, EXECUTION_ERROR,
  NORMAL_VARIANCE o UNKNOWN.
- **Aciertos:** se juzgan con la misma vara, frente al cierre, por el valor del precio (el CLV, `clv-v1`, con una banda de ±1 %).
  Son **merecidos** si el precio fue bueno o neutro; **con suerte** si fue malo (el mercado iba en contra); y **sin datos** si no hay
  cierre con qué comparar. Un acierto con suerte no enseña nada sobre el modelo, así que no se aprende de él como si fuera una buena
  decisión. (Hasta F8 el criterio era el movimiento del precio de la misma casa, que lleva el margen dentro y no es un CLV.)

## 6. Evaluación no es recomendación (F16)

Cada pick del día muestra su cadena de decisión: **elegido por el modelo** → **lo que dijo la IA** en su última
revisión antes del saque → **no publicado** (modo evaluación) → **liquidado**. La publicación sigue bloqueada por la
restricción `picks_publishing_disabled`. Activarla requiere una migración y la decisión del dueño, no un interruptor.
