# Registro de sombras de Intelligence (RP-0.2)

<!-- Generado por `python -m scripts.shadow_registry` desde `docs/intelligence/sombras.json`. No lo edites a mano. -->

Medido el 2026-11-26T03:20:00Z. 26 interruptores FBI_* en modo shadow en /etc/predigol (lectura, 26-nov-2026); desde = primera fila de su tabla de salida.

**26 interruptores en sombra; 11 con comparación y condición numérica definidas, 15 sin ellas.** Una fila marcada «no» dice la verdad: hoy ningún criterio del código decide esa sombra, y no se inventa uno aquí. Cada criterio nuevo pasa por la aprobación previa de la decisión D7 antes de medir.

| Interruptor | Qué corre | Dónde escribe | Desde | Filas | Quién lo lee | Comparación que lo decide | Condición | Quién decide | ¿Definida? |
|---|---|---|---|---|---|---|---|---|---|
| FBI_AI_MODE | Capa de IA: cada revisión de candidatos se registra y se muestra al dueño; los usuarios no ven nada nuevo (enforce se comporta como shadow hasta que pase su puerta) | ai.shadow_reports (informe diario ai-gate-v2), ai.match_runs, ai.pick_reviews | 2026-10-08 (informes) / 2026-10-26 (pasadas) | 193 informes; 10180 pasadas | solo la consola del dueño | ai-gate-v2: lo que la revisión rechazó rindió peor que lo que aprobó, sin perder valor de cierre ni calibración | 300 selecciones liquidadas, 30 días, 50 rechazadas, z >= 2,0 | dueño (cambiar a enforce); el código lo ignora hasta que la puerta pase | sí |
| FBI_AI_EXTRACTOR | Extractor en cuarentena (extract-v2) sobre las páginas que lee v1, tope FBI_AI_EXTRACTOR_SHADOW_MAX_PER_DAY (150 al día) | no guarda salida propia; cuesta presupuesto del LAB | sin medir (sin tabla propia) | sin medir | nadie | ninguna definida en el código | ninguna | dueño | no |
| FBI_AI_RESEARCH_UNIFIED | Investigación unificada (una sola vía en lugar de v1 y v2) tras la investigación del ciclo, tope FBI_AI_RESEARCH_UNIFIED_MAX_PER_DAY (60 al día) | sin tabla propia medida (no toca las filas de v1 ni de v2 en ai.evidence) | sin medir (sin tabla propia) | sin medir | nadie | se mide al lado de v1 y v2 antes de que nada dependa de ella; sin criterio numérico en el código | ninguna | dueño | no |
| FBI_AI_RESEARCH_V2 | Investigación por entidad y tema (extract-v3, claim-v1) detrás de la puerta untrusted-v3, al lado de v1 | afirmaciones tipadas; no mueve estados, paquetes ni picks de v1 | sin medir (sin tabla propia) | sin medir | nadie | puerta research_v2: recuperó 23,1 % de lo que halló v1 (fila 17, 12-nov: NO PASA, se conserva) | puerta research_v2 registrada en ai.feature_gates | dueño | sí |
| FBI_CHRONICLE_V4 | Crónica única: plan de contenido por código y texto del modelo pequeño verificado frase por frase (chronicle-v4) | ai.chronicles (ruta propia) | sin medir (se separa por versión en RP-1.3) | sin medir | nadie | chronicle-review-v2 (hechos citados) y retire-compare-v1 (frente a los textos que hoy ven los lectores) | retire-compare-v1: al menos 100 partidos y margen 0,05; sin apoyo = 0 | dueño, firma individual por retirada (D6) | sí |
| FBI_CHRONICLE_LINEUP | Actualización de la crónica tras la alineación oficial (E3) y porqué de cada selección, por plantilla, sin modelo ni coste | ai.chronicles (custom_id lineup-update:<E3>) | 2026-11-18 | 567 | nadie | ninguna definida: la revisión factual de la crónica única la cubre sin medirla aparte | ninguna | dueño | no |
| FBI_CHRONICLE_REPEAT | Mide frases de plantilla y repeticiones de cada crónica frente a la anterior del mismo equipo (repeat-check-v1); en shadow solo mide | medidas por crónica (sin tabla propia) | sin medir | sin medir | nadie | umbrales de repeat-check-v1 | tasa de plantilla <= 0,10 y de repetición <= 0,10 sobre un corpus de al menos 20 crónicas | dueño (pasar a on) | sí |
| FBI_CHRONICLE_REVIEW_V2 | Juicio factual de la crónica única tras el partido (chronicle-review-v2, chronicle-metrics-v1) | ai.chronicle_reviews | 2026-11-10 | 887 | solo la consola del dueño | protocolo de muestreo humano chronicle-protocol-v1 (sin firmar) y banco de partidos trampa en CI | frases sin apoyo = 0 (protocolo AD-F06) | dueño (firma del protocolo y de la muestra) | sí |
| FBI_COUNCIL_REDUCED | Council reducido: reglas por defecto y juez solo ante contradicción material con valor y tiempo | ai.council_reduced | 2026-11-18 | 1376 | nadie | ninguna definida en el código | ninguna | dueño | no |
| FBI_COUNT_CALIBRATION | Habilita el ajuste de calibradores de conteos por orden del dueño (scripts/count_calibration.py); nada lo programa | intel.count_calibrators | sin filas | 0 | nadie | protocolo AD-B07 | al menos 500 observaciones para ajustar; solo se firma CAMPEÓN con VALIDADO | dueño (firma) | sí |
| FBI_COUNT_EVAL | Evaluación privada de córneres y tarjetas: ciclo de estados solo de las selecciones que la admisión deja pasar | intel.selection_lifecycle (solo escribe ahí, solo cadenas de los seis mercados de conteo) | sin medir (comparte tabla con el ciclo) | sin medir | nadie | admisión: regla de liquidación, calibrador VALIDADO firmado y al menos 3 casas con la línea | 3 casas completas y calibrador firmado | dueño | sí |
| FBI_DECISION_V2 | decision-v2 decide por sí mismo en E1, E4 y el espejo de decision-v1 y guarda cada decisión | intel.decisions_v2, intel.decision_v2_moments | 2026-11-18 | 63332 decisiones; 6445 momentos | nadie | ninguna definida frente a decision-v1 | ninguna | dueño (D6, tras comparación y pruebas) | no |
| FBI_EVAL_CYCLE | Ciclo de evaluación E1 a E4 y cadenas de estados, con lectura del partido y alineación (E3) | intel.eval_runs, eval_facts, eval_verdicts, private_alerts | 2026-11-18 | 2916 pasadas | rutas privadas de la consola (a confirmar en el mapa de consumidores, RP-0.3) | ninguna definida frente al ciclo por partido anterior | ninguna | dueño (D6) | no |
| FBI_FAMILY_DECISIONS | Una pasada por hora de decisiones de familias (córneres, tarjetas, goles por mitad), con liquidación, post-mortem y memoria nocturnos | intel.decision_outcomes, family_postmortems, family_memory | 2026-10-13 (resultados) / 2026-11-07 (post-mortems) | 149038 resultados; 10323 post-mortems; 1736 memoria | solo Aprendizaje > Familias de la consola | calibración por familia (RP-2.3) y pérdida frente al mercado (indicador 4) | ninguna fijada todavía; el criterio de aceptación D7 lo fijará | dueño | no |
| FBI_LINEUP_ESTIMATE | Estima los titulares de cada lado en E1 y E4 con lo que se sabía en ese momento | intel.lineup_estimates | 2026-11-18 | 60221 | nadie | calibración de la estimación por competición; por debajo de la muestra mínima toda cifra dice sin_calibrar | al menos 60 lados por competición | dueño | sí |
| FBI_LINEUP_WATCH | Vigila la alineación oficial cada 3 minutos desde T-90, una petición por 20 partidos | core.fixture_lineup_arrivals (canal lineup_watch) | 2026-11-18 (según el canal) | 1151 llegadas | sin verificar quién la consulta (lo aclara el mapa de consumidores, RP-0.3) | minutos entre llegada y lectura frente a la lectura previa (cada 10 minutos) | ninguna numérica en el código | dueño | no |
| FBI_NEWS_STORIES | Agrupa artículos en historias, entidades, categoría, idioma, país y moderación (news-pipeline-v1); sin modelo | news.item_entities, stories, item_story, moderation_log | 2026-11-18 | 565 historias | nadie (la web no lee noticias antes de FBI_NEWS_V2) | ninguna definida | ninguna | dueño | no |
| FBI_NEWS_TEXT | Titular y resumen propios de las historias cuyas fuentes lo permiten (autorizada, firmada, no reservada) | news.story_texts | sin filas | 0 | nadie | verificador news-verify-v1 y derechos de fuente (D4) | fuente autorizada y firmada; ninguna firmada el 17-nov | dueño (firma de fuentes, D4) | sí |
| FBI_PARLAY_V6 | Construye parlay-v6 con las cadenas confirmadas en la sombra y lo sigue hasta su resultado | intel.parlays_v6, parlay_v6_legs | 2026-11-18 | 24 combinadas | nadie (el producto muestra parlay-v5) | ninguna definida frente a parlay-v5 | mínimo 2 selecciones y 3 casas con precio | dueño | no |
| FBI_PLAYER_ENGINE_V2 | Pronóstico de todos los mercados de jugador por lado, en E1 y E4 | intel.player_forecasts | 2026-11-18 | 607692 | nadie | ninguna definida | ninguna | dueño | no |
| FBI_SCENARIOS | Motor de escenarios: una lectura cada 6 horas por competición viva con código | intel.scenario_readings | 2026-11-18 | 174 | nadie | ninguna definida | ninguna | dueño | no |
| FBI_SELECTION_EVAL | Evaluación tras el partido de cada selección liquidada en los últimos 7 días | intel.selection_evaluations | 2026-11-18 | 23067 | nadie | ninguna definida | ninguna | dueño | no |
| FBI_SELECTION_LIFECYCLE | Cadena de estados de cada selección de las capas de decisión | intel.selection_lifecycle | 2026-11-18 | 110328 | rutas privadas de la consola (a confirmar en el mapa de consumidores, RP-0.3) | ninguna definida | ninguna | dueño | no |
| FBI_SELECTION_SETTLE | Liquida con settle-v4 las cadenas de decision-v2 en sombra | intel.selection_settlements | 2026-11-18 | 435 | nadie | coincidencia con la liquidación oficial | ninguna numérica en el código | dueño | no |
| FBI_SIGNALS | Lee los RSS y sitemaps del directorio v2 según la cercanía de los partidos; la política de fuentes decide primero | news.feed_reads, news.items | 2026-11-18 | 6099 lecturas | nadie | política de fuentes de IA-063 (derechos) antes de cada lectura | fuente no bloqueada, comprobada y sin reserva de IA | dueño (D4) | sí |
| FBI_SOURCE_CREDIBILITY | Credibilidad por fuente y tipo de hecho, una vez al día (credibility-v2), con intervalo de Wilson | ai.source_credibility | 2026-11-18 | 92 | nadie (la confianza del motor sigue leyendo la versión anterior) | mínimo registrado de muestra por fuente y tipo | alcanzar el mínimo registrado | dueño | sí |

## Notas

- `FBI_AI_EXTRACTOR`: la fijará la pieza que consolide la extracción.
- `FBI_AI_RESEARCH_UNIFIED`: la fijará la pieza que consolide la investigación.
- `FBI_CHRONICLE_LINEUP`: la fijará la pieza de narrativa.
- `FBI_COUNCIL_REDUCED`: su retirada o promoción es una decisión D6 con comparación previa.
- `FBI_COUNT_CALIBRATION`: la tabla está vacía: ningún calibrador de conteos se ha ajustado; lo aborda RP-2.3.
- `FBI_DECISION_V2`: RP-0.1 mide su pérdida frente al mercado (indicadores 1 a 5); la comparación formal con decision-v1 llega con la consolidación de motores.
- `FBI_EVAL_CYCLE`: dos ciclos corren a la vez (hallazgo H28); su consolidación exige comparación previa.
- `FBI_NEWS_STORIES`: su criterio llega con la cadena de noticias (RP-1 y bloques de noticias).
- `FBI_NEWS_TEXT`: sin ninguna fuente firmada no escribe nada; es un bloqueo de derechos, no de código.
- `FBI_PARLAY_V6`: D9: sin tope arbitrario; exigirá referencia de liga, muestra suficiente e incertidumbre visible.
- `FBI_PLAYER_ENGINE_V2`: su evaluación privada es RP-3.6.

## Sombras sin comparación o condición definida

- `FBI_AI_EXTRACTOR`
- `FBI_AI_RESEARCH_UNIFIED`
- `FBI_CHRONICLE_LINEUP`
- `FBI_COUNCIL_REDUCED`
- `FBI_DECISION_V2`
- `FBI_EVAL_CYCLE`
- `FBI_FAMILY_DECISIONS`
- `FBI_LINEUP_WATCH`
- `FBI_NEWS_STORIES`
- `FBI_PARLAY_V6`
- `FBI_PLAYER_ENGINE_V2`
- `FBI_SCENARIOS`
- `FBI_SELECTION_EVAL`
- `FBI_SELECTION_LIFECYCLE`
- `FBI_SELECTION_SETTLE`
