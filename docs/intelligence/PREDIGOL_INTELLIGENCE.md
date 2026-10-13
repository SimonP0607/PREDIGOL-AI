# PrediGol Intelligence — arquitectura, contratos y ciclo diario

Versión del documento: **pi-arch-v1** (13 oct 2026). Estado: **SHADOW** (nada de esto publica picks ni mueve dinero).

> Prioridad absoluta: una inteligencia cada día más informada y mejor calibrada, no una que produzca cada día más
> picks. «Más información ≠ más certeza».

## 0. Por qué (lo que mostró la auditoría inicial, datos reales del servidor)

| Hallazgo | Evidencia (producción, 29 sep – 12 oct) |
|---|---|
| El modelo está **sobreconfiado** en los candidatos que elige | 72.453 picks shadow liquidados: p_modelo media 0,50–0,58 frente a tasa de acierto 0,38–0,42 en todos los mercados; ECE del modelo 0,07–0,15, del mercado 0,01–0,03 |
| El mercado (Shin, sin margen) está mejor calibrado que el modelo | log loss fuera de muestra: OU modelo 0,678 / mercado 0,636; AH 0,648 / 0,613; 1X2 0,603 / 0,587; BTTS 0,732 / 0,686 |
| Ningún mercado tiene edge demostrado | ROI plano −4 % a −12 % y CLV (sin margen) −3 % a −7 % en los cinco mercados |
| Una recalibración con dos entradas (logit p_modelo, logit p_mercado) corrige casi toda la sobreconfianza | walk-forward por día: OU log loss 0,6415 y ECE 0,045; 1X2 0,5873 y 0,023 — pero sigue sin superar al mercado salvo en 1X2 (empate técnico) |
| Stakes | 79.362 picks, todos con 1 u (sin Kelly ni límites) |
| Memoria | eventos por partido, mercado, fuente, revisor; sin memoria por equipo, entrenador, árbitro, liga ni combinación equipo×mercado |
| Investigación externa | 592 de 724 evidencias web en nivel `unknown`/RUMOR (sitios de apuestas, streaming); medios reconocidos sin clasificar |
| Mercados | 338 mercados prepartido ofrecidos por API-Football, 5 modelados; sin registro ni proceso de incorporación |
| Presupuesto IA | US$22 en octubre (≈ US$4,4/día), tope configurado US$150, alertas 70/85/95/100; las respuestas inválidas no cuentan sus tokens; el analista antiguo tiene su propio tope de US$20 sobre el gasto de toda la capa |
| Hipótesis | 5 hipótesis de la IA sobre sobreconfianza en cuotas altas (#14, #21, #26, #32, #39) atascadas en PROPOSED/INVESTIGATING sin experimento |

La conclusión cuantitativa decide la arquitectura: **la capa de decisión debe trabajar con probabilidades
calibradas fuera de muestra y exigir evidencia de edge por mercado antes de aprobar nada**. Hoy eso significa
pocos o ningún pick aprobado, y es el resultado correcto mientras la evidencia no cambie.

## 1. Las cuatro capas (no se mezclan)

```
CAPA 1 · DATOS           API-Football (fixtures, odds de todas las casas, stats, eventos, alineaciones, lesiones,
                         árbitro, entrenadores) + RAW comprimido + consenso Shin. (existente: fbi.ingestion, fbi.odds,
                         fbi.market). Toda fila con su marca de tiempo de conocimiento (fetched_at / captured_at /
                         observed_at / retrieved_at / settled_at).
CAPA 2 · MODELOS         Por mercado: Poisson, Dixon-Coles (goles), Elo ordered-logit (1X2) -> P_modelo con intervalo
                         (existente: fbi.models, picks shadow-rule-v2). NUEVO: calibración por (mercado, modelo)
                         fbi.intel.calibration -> P_calibrada, versionada, champion/challenger con criterios fijos.
CAPA 3 · PREDIGOL        Contexto: paquete del partido (packet-v2 = packet-v1 + dossier-v1), evidencia con fuente,
INTELLIGENCE             nivel y estado, brief L1 / revisión L2 / revisión L3 (existente: fbi.ai). NUEVO: dossier
                         (equipo, árbitro, entrenador, contexto competitivo, jugadores clave), fuentes clasificadas
                         (sources-v2), estado de contexto FULL / PARTIAL / LIMITED (CONTEXTO EXTERNO LIMITADO) /
                         PENDING, narrativa por secciones. La IA contextualiza: no cambia la matemática ni inventa
                         probabilidades.
CAPA 4 · DECISIÓN        NUEVO fbi.intel.decision (decision-v1): 10 filtros -> estado (RECHAZADO, INVESTIGACIÓN,
                         CAUTELA, APROBADO, PICK DEL DÍA, CANDIDATO A PARLAY, PICK PREMIUM), PrediGol Pick Score
                         (pick-score-v1), stake (stake-v1), selección del día (0-5, nunca relleno), parlays solo de
                         aprobados con correlación. Todo en intel.decisions, append-only.
```

La capa 4 solo lee de las capas 1–3; nunca escribe en ellas. La capa 3 nunca modifica una probabilidad: produce
señales de contexto que la capa 4 usa como filtro de riesgo y como componente del score.

## 2. Ciclo diario (America/Bogota)

| Hora | Trabajo | Módulo | Coste IA |
|---|---|---|---|
| continuo | captura de cuotas, fixtures, resultados, estadísticas, alineaciones | worker existente | 0 |
| cada 30 min | pronósticos y picks shadow (escaneo cuantitativo de todas las selecciones) | `pick_pipeline` | 0 |
| 23:59 | CIERRE DEL DÍA (revisiones hasta que el día queda completo) | `ai_day_close`, `ai_day_follow` | 0 |
| 00:05 | apertura del día de la IA, primera pasada (paquete, brief L1, web, revisiones) | `ai_day_start` | Nivel A/B |
| 00:10 y cada 15 min | **decisión**: candidatos de las próximas 36 h re-evaluados en sus puntos de control (T−24h, T−12h, T−6h, T−3h, T−90m, T−60m, alineaciones, T−15m para PICK DEL DÍA/PREMIUM); una fila nueva solo si cambia el punto de control, el estado o el precio > 3 % | `intel_decide` | 0 |
| 6–4 h antes | pasada `pre` (noticias, lesiones, movimientos) | `ai_cycle` | Nivel B |
| 06:00 | **PICKS DEL DÍA PI** (v6, shadow): hasta 5 APROBADOS por score, uno por partido, máx. 2 por competición; después se añaden los de partidos tardíos hasta completar 5 | `intel_decide` | 0 |
| 100–10 min antes | pasada `final` tras alineaciones; L3 solo para los mejores | `ai_cycle` | Nivel C/D |
| 07:35 | aprendizaje IA existente (post-mortems pm-v2, notas, patrones, sombra de la IA) | `ai_learn` | bajo |
| 07:50 | **ciclo nocturno PI**: liquidación y CLV de decisiones, post-mortems pm-v3, memoria longitudinal, calibradores (challenger nuevo + evaluación prospectiva + promoción por criterios), auditoría de fugas, DAILY LEARNING REPORT, vínculo hipótesis↔experimentos | `intel_nightly` | 0 |
| lunes 04:40 | **MARKET DISCOVERY ENGINE** (propone, nunca activa) | `intel_weekly` | 0 |

Nada se recalcula si sus entradas no cambiaron: el paquete y el brief se guardan por hash, las búsquedas web se
cachean, la decisión se deduplica por (selección, punto de control, hash de entradas).

## 3. Contratos de datos (migración 0076, esquema `intel`)

Todas las tablas son **append-only** (trigger `ai.refuse_change` / `intel.refuse_change`); una corrección es una
fila nueva. Nada se reescribe después del saque ni después del resultado.

| Tabla | Una fila por | Claves de reproducibilidad |
|---|---|---|
| `intel.calibrators` | ajuste de un calibrador (mercado, modelo, método, versión) | `known_at` (corte), `train_from/train_to`, `n_train`, `train_hash` (ids de los picks usados), `params`, métricas walk-forward |
| `intel.calibrator_evaluations` | evaluación prospectiva diaria de un calibrador | día, n, log loss / Brier / ECE calibrado vs crudo vs mercado, CLV de la regla |
| `intel.promotions` | cambio de rol (CHALLENGER → CHAMPION, CHAMPION → RETIRED, rollback) | criterios evaluados y sus valores, `gate_version`, quién/por qué |
| `intel.decisions` | evaluación de una selección en un punto de control | `known_at`, pick y versión de modelo, precio, casa, `price_at`, p_modelo, p_calibrada, `calibrator_id`, p_mercado, EV/edge crudos y calibrados, 10 filtros, estado, score y componentes, stake y componentes, contexto (estado, revisión, evidencias), `input_hash`, `decision_version` |
| `intel.day_selections` | pick del día / parlay elegido por la regla v6 | decisión(es) congeladas, rango, stake, correlación |
| `intel.decision_outcomes` | resultado de una decisión | estado del pick, P&L a la cuota de la decisión (plano y con stake), CLV contra el cierre sin margen |
| `intel.postmortems` | post-mortem pm-v3 de una decisión | calidad de la decisión separada del resultado, causas del partido, preguntas respondidas, evidencia |
| `intel.entity_memory` | estado acumulado de una entidad × aspecto en un día | equipo, jugador, entrenador, árbitro, competición, mercado; decisiones, aciertos, CLV, errores, contexto recurrente |
| `intel.daily_reports` | revisión del DAILY LEARNING REPORT de un día | contenido JSON + texto, hash |
| `intel.market_registry` | estado de un mercado del proveedor en una corrida de discovery | 10 criterios, cobertura, casas, historial, estabilidad, modelabilidad, estado (ACTIVE / RESEARCH / CANDIDATE / NOT_MODELABLE) |
| `intel.runs` | ejecución de un trabajo PI | duración, estado, conteos, errores, coste, versión de código |
| `intel.audit_checks` | comprobación de fugas de datos de un día | regla, n revisadas, violaciones, ejemplos |

Además: `ai.budget_alerts` acepta 50 %; `ai.sources` recibe la semilla `sources-v2` (medios reconocidos, oficiales,
sitios de apuestas como agregadores).

## 4. Calibración (Capa 2) — `cal-logit2-v1`

* Muestra: picks shadow liquidados (win/loss; push, void y medios resultados fuera), **el último pick antes del
  saque por (partido, mercado, selección, línea, modelo)** — una observación por selección.
* Modelo: `logit p_cal = a + b·logit(p_modelo) + c·logit(p_mercado)` (Newton-Raphson, L2 = 1), por (mercado,
  modelo). Ventana: últimos 28 días con resultado conocido antes del corte. Mínimo 500 selecciones.
* Sin fuga: un calibrador ajustado en el instante T solo usa picks cuyo resultado se liquidó antes de T
  (`settled_at < T`) y cuyo partido empezó antes de T.
* Validación del **método** por walk-forward diario (ajuste con los días < D, evaluación en D).

**Criterios de CHAMPION (`calib-gate-v1`, fijados antes de ver resultados nuevos):**

1. fuera de muestra ≥ 1.500 selecciones en ≥ 5 días;
2. log loss(calibrada) ≤ log loss(modelo crudo) − 0,005;
3. ECE(calibrada) ≤ 0,03;
4. log loss(calibrada) ≤ log loss(mercado) + 0,002 (si no, el mercado solo es mejor probabilidad).

**Criterio de EDGE del mercado (`edge-gate-v1`)**, necesario para que una decisión pueda ser APROBADA: la regla
«EV calibrado ≥ 2 %» tuvo, fuera de muestra, ≥ 300 selecciones y **CLV medio ≥ 0** contra el cierre sin margen.
Mientras no se cumpla, sus candidatos quedan en INVESTIGACIÓN (se miden en shadow, no se aprueban).

El champion se reemplaza solo si un challenger cumple los criterios **y** mejora el log loss del champion en ≥ 0,002
en el mismo periodo; nunca por un resultado de un día («perdimos ayer → cambiar modelo hoy» está prohibido). Cada
promoción y cada rollback es una fila en `intel.promotions`.

## 5. Capa 4 — los 10 filtros y los estados (`decision-v1`)

| # | Filtro | Falla → |
|---|---|---|
| 1 | Calidad de datos: partido programado, ≥ 10 min al saque, pronóstico ≤ 48 h, sin bloqueo de calidad | RECHAZADO |
| 2 | Modelo especializado del mercado disponible (p_modelo con intervalo) | RECHAZADO |
| 3 | Mercado: precio actual de ≥ 3 casas, ≤ 3 h, no atípico (≤ 25 % sobre el consenso) | RECHAZADO (precio viejo → INVESTIGACIÓN) |
| 4 | Calibración: calibrador CHAMPION del (mercado, modelo) | tope INVESTIGACIÓN |
| 5 | EV: EV calibrado ≥ 2 % y edge calibrado ≥ 1 pto | RECHAZADO |
| 6 | Contexto PI: revisión combinada y evidencias; REJECT/DOWNGRADE de la IA o evidencia en contra no confirmada → CAUTELA; ausencia clave CONFIRMADA en el lado elegido → RECHAZADO; sin contexto → «CONTEXTO EXTERNO LIMITADO» (no rechaza, penaliza) | CAUTELA / RECHAZADO |
| 7 | Riesgo: cuota > 3,00 (risk-v1, evidencia P5), p_calibrada < 0,30, intervalo > 0,25 | CAUTELA |
| 8 | Correlación: una selección por partido (la de mayor score); el resto | CAUTELA |
| 9 | Precio actual: el EV se recalcula con el mejor precio vigente en cada punto de control | RECHAZADO |
| 10 | Clasificación final: APROBADO solo con edge-gate del mercado cumplido; PICK DEL DÍA (top 5 por score, uno por partido, máx. 2 por competición); PICK PREMIUM (score ≥ 80 y CLV histórico del tipo > 0); CANDIDATO A PARLAY (aprobado, cuota 1,25–2,20, p ≥ 0,5) | — |

**PrediGol Pick Score (`pick-score-v1`, 0–100, explicable):** suma ponderada de componentes en [0, 1]:
EV calibrado (15), edge calibrado (10), calidad de calibración del mercado (10), historial del modelo/mercado —
CLV walk-forward (10), calidad de datos (10), frescura del precio (5), calidad del mercado — casas y margen (10),
profundidad del contexto (10), consenso entre modelos (5), incertidumbre — ancho del intervalo (5), riesgo
contextual (5), CLV histórico del tipo de pick (5). Cada decisión guarda cada componente, su valor y su aporte.

**Stake (`stake-v1`):** Kelly fraccional ¼ sobre la probabilidad calibrada (con push), 1 u = 1 % del bankroll,
redondeo hacia abajo a 0,25 u, topes por estado: CAUTELA 0,25 u, APROBADO 1,00 u, PICK DEL DÍA 1,00 u, PREMIUM
1,50 u, parlay 0,25 u; INVESTIGACIÓN y RECHAZADO 0. Los topes se validan por simulación
(`scripts/intel_stake_sim.py`) y nunca se usa Kelly completo.

**Parlays:** solo de CANDIDATOS A PARLAY de partidos y competiciones distintos; probabilidad conjunta con la
dependencia medida (`ai.correlation_estimates`, icc-v1), no el producto ingenuo; se muestran cuota combinada,
probabilidad estimada, EV, riesgo, correlación y stake (¼ Kelly, tope 0,25 u).

## 6. Capa 3 — dossier, investigación y narrativa

* **dossier-v1** (en `packet-v2`, todo a la fecha de corte): por equipo, últimos 10 partidos en casa/fuera con goles,
  xG, tiros, a puerta, córners, faltas, tarjetas, fueras de juego, posesión, penaltis (eventos), rachas, calidad del
  rival (Elo), comportamiento según marcador (goles a favor/en contra yendo por delante/detrás); árbitro (partidos,
  amarillas, rojas, faltas, penaltis por partido, reparto local/visitante); entrenadores (formaciones, alternativas,
  rotación entre partidos, minuto medio de cambios, rendimiento casa/fuera); contexto competitivo (posición, puntos a
  título / plazas / descenso, partidos restantes, ida/vuelta, copa, final, derbi, amistoso); jugadores clave (minutos,
  goles, asistencias, rating, ausencias, carga de los últimos 14 días); H2H con peso por antigüedad.
* **sources-v2**: oficiales (ligas, federaciones, clubes) > prensa reconocida (ESPN, TyC Sports, Win Sports, Gol
  Caracol, RCN, DirecTV Sports, BBC Sport, Sky Sports, The Athletic, Marca, AS, Mundo Deportivo, L'Équipe, Bild,
  Gazzetta y equivalentes por país) > medios locales > periodistas > secundarios/agregadores > redes solo verificadas.
  Cada evidencia guarda URL, medio, fecha, idioma, partido, equipo, jugador, tipo, confianza, resumen, relevancia y
  hora de captura (`ai.evidence`, existente).
* **Ligas de baja cobertura**: búsqueda escalonada en 6 niveles (oficial → prensa nacional → local → periodistas →
  agregadores → redes verificadas), en el idioma de la liga; si no hay nada: **CONTEXTO EXTERNO LIMITADO** (no se
  inventa, no se rechaza automáticamente).
* **Narrativa** por partido cubierto (Cómo llega el local / el visitante, Qué está en juego, Claves tácticas,
  Jugadores importantes, Riesgos, Mercados interesantes, Conclusión PrediGol Intelligence), construida solo con datos
  del dossier, evidencias citadas y decisiones; una afirmación sin dato no se escribe.

## 7. Aprender sin sobreajustar

* **pm-v3** (cada decisión CAUTELA o superior y las 20 mejores INVESTIGACIONES del día): calidad de la decisión
  (CLV, EV al cierre, p_calibrada frente al cierre) separada del resultado — merecido / varianza / suerte / error —;
  causas del partido (roja y minuto, penaltis, gol temprano, lesiones antes del 30', tarjetas frente a lo esperado del
  árbitro, alineación distinta de la esperada); las preguntas del POST_MATCH_REVIEW respondidas con datos. Un pick
  perdido nunca ajusta un modelo.
* **Memoria longitudinal** (`memory-v1`): instantánea diaria por entidad × aspecto (equipo×mercado,
  competición×mercado, árbitro, entrenador, jugador-disponibilidad, mercado) con decisiones, aciertos, CLV, errores
  y contexto recurrente. Una racha es una señal a investigar, no una regla.
* **DAILY LEARNING REPORT** (`learn-report-v1`): ganadas/perdidas/nulas, CLV, ROI, calibración, errores, contexto
  que funcionó y que falló, noticias, anomalías de modelo y mercado, equipos y jugadores, hipótesis nuevas,
  oportunidades (discovery). Revisiones append-only.
* **Champion/challenger** (sección 4) y **hipótesis**: las hipótesis de sobreconfianza (#14, #21, #26, #32, #39)
  quedan enlazadas al experimento de calibración con su resultado (`stage_history`, `outcome`).

## 8. Mercados — `discovery-v1` y los 10 criterios

Semanal: lee el catálogo del proveedor (`market.provider_markets`), lo visto en las cuotas reales
(`market.odds_mapping_seen`, `raw.ingestion_payloads`) y los datos de resultado disponibles (`core.fixture_team_stats`,
`core.fixture_events`). Por mercado evalúa: (1) cobertura, (2) historial, (3) precio real, (4) modelo, (5)
calibración, (6) backtest, (7) contra el mercado, (8) Shadow, (9) volumen mínimo, (10) estabilidad. Estado:
ACTIVE (los 5 modelados), RESEARCH (datos y precio suficientes, falta modelo/backtest), CANDIDATE (precio sin datos de
resultado o al revés), NOT_MODELABLE. **Nunca activa un mercado**: la activación sigue Mercado → Datos → Features →
Modelo → Calibración → Backtest → Shadow → Producción con aprobación explícita.

## 9. Presupuesto IA (US$180/mes)

* Tope mensual único US$180 para toda la capa (decisión + analista); alertas 50/70/85/95/100 % (una vez por mes).
* Día adaptativo existente (ritmo × carga, techo 1,5×), más **reserva de prioridad**: el trabajo marginal (brief
  LLM y web de partidos sin candidatos) se detiene al 80 % del presupuesto del día o con el mes ≥ 85 %; el análisis
  de candidatos críticos (APROBADOS / mejores del día) sigue hasta el techo.
* Niveles: A escaneo (reglas + Haiku), B investigación (web + Haiku), C profundo (Sonnet), D final (Opus, solo los
  mejores del día).
* Los tokens de respuestas inválidas se cuentan. Métricas: coste por partido, candidato, pick, investigación,
  post-mortem, día y proyección mensual. Los análisis son compartidos: ningún token por usuario.

## 10. Fugas de datos (`leak-audit-v1`, diario y en tests)

Para cada decisión: `known_at` < saque; `price_at` ≤ `known_at`; pick `data_cutoff_ts` y `created_at` ≤ `known_at`;
calibrador `fitted_at` ≤ `known_at` y sus datos liquidados antes de `fitted_at`; revisión y paquete ≤ `known_at`;
evidencias `retrieved_at` (y `published_at` si existe) ≤ `known_at`. Toda violación queda en `intel.audit_checks`.

## 11. Autonomía controlada

Automático: investigación, recopilación, memoria, post-mortems, ajuste de challengers, backtests, hipótesis,
evaluación y promoción **dentro de shadow** con criterios fijos y rollback. Requiere decisión explícita del dueño:
publicar picks a usuarios, activar un mercado, cambiar la regla que ven los usuarios (daily-set-v5 sigue siendo la
de usuarios hasta que v6 cumpla su propio criterio de promoción: ≥ 30 días, CLV ≥ v5 y ≥ 0, sin regresión de
calibración).

## 12. Lo que no se afirma

No se afirma rentabilidad. La calibración corrige la sobreconfianza; no crea edge. Con la evidencia de hoy el
número esperado de picks APROBADOS es bajo o cero y así se mostrará.

## 13. Primer día en producción (13 oct 2026, datos reales del servidor)

**Despliegue.** Backend `cc4eff3`, web `de5d976`, migración 0076. Copia `pre-pi-0076` (787 MB, sha256 `a9261997…`)
con prueba de restauración aprobada (401 s, contenedor desechable) antes de migrar, y la copia `pre-deploy` del propio
despliegue (`1be22877…`) también restaurada con éxito (406 s). Presupuesto en el servidor: US$180/mes, objetivo diario
US$6,00 (copia fechada de `app.env`; solo cambiaron esas tres líneas).

**Incidente del primer intento (06:59 UTC), corregido.** La migración esperó el bloqueo de `ai.budget_alerts` detrás
de la transacción del notificador mientras ya tenía los de las claves foráneas sobre `core.fixtures` y `picks.picks`;
una escritura del worker quedó en cola. Se detuvo el despliegue antes de tocar los servicios y la migración se deshizo
entera (revisión 0075, sin esquema `intel`, 0 bloqueos en espera). Causa raíz: el notificador re-redactaba cada pick
shadow de la semana en cada pasada (137.974 borradores cada 10 min, 7–9 min de cada 10 dentro de una transacción) y
dejaba 132.082 mensajes en cola por delante de cualquier alerta. Arreglos con test de regresión: 0076 toma primero el
único bloqueo exclusivo y falla entera si espera más de 10 s; el notificador redacta solo lo no registrado (149
borradores en 5 s tras el despliegue) y envía primero lo operativo (presupuesto, worker, fallos). En el segundo
intento el primer `alembic upgrade` falló por el tope de 10 s, el despliegue reintentó y aplicó 0076 completa.

**Primeras ejecuciones.** `decide` cada 15 min (0,7–3,4 s): 611–635 selecciones en las próximas 36 h; con los
calibradores CHALLENGER del primer `nightly`, 562 RECHAZADO / 49 INVESTIGACIÓN / 0 aprobadas → 0 picks del día v6 y 0
parlays. La calibración encoge el EV crudo del modelo: AH +20 % → −14 %, OU +30 % → −6,5 %, BTTS +22 % → −9,5 %, 1X2
+24 % → −6,5 % (medias de las rechazadas). `nightly` (5,9 s): 24 ajustes, 0 campeones, 8 mercados×modelo con edge
NOT_VALIDATED, memoria 965 filas, informes de 11 y 12 oct, 8 hipótesis enlazadas. `weekly` (36,8 s): 338 mercados,
5 ACTIVE, 28 RESEARCH, 199 CANDIDATE, 106 NOT_MODELABLE.

| Calibrador (logit2) | n fuera de muestra | días | ECE | vs crudo | vs mercado | CLV regla EV≥2 % (n) | Falla |
|---|---|---|---|---|---|---|---|
| AH / Poisson | 2.695 | 6 | 0,017 | −0,032 | +0,005 | −0,8 % (462) | vs_market, edge |
| AH / Dixon-Coles | 2.688 | 6 | 0,029 | −0,032 | +0,006 | −1,0 % (440) | vs_market, edge |
| OU / Dixon-Coles | 2.805 | 6 | 0,034 | −0,048 | +0,002 | −2,9 % (1.125) | ECE, edge |
| OU / Poisson | 2.847 | 6 | 0,043 | −0,047 | +0,0025 | −2,9 % (1.548) | ECE, vs_market, edge |
| 1X2 / Elo | 205 | 2 | 0,061 | −0,011 | −0,004 | −1,0 % (100) | n, días, ECE, edge |
| 1X2 / Dixon-Coles · Poisson | 222 · 47 | 2 · 1 | 0,057 · 0,146 | | | | n, días, ECE, edge |
| BTTS / Poisson | 0 (505 para ajustar, ningún día con 500 previos) | 0 | | | | | n, días |
| DC | <500 | | | | | | sin ajuste |

Sin calibrar (identidad), el modelo tiene ECE 0,11–0,13 en AH y OU y la regla «EV ≥ 2 %» pierde 4,6–6,5 % de CLV;
calibrada pierde 0,8–2,9 %: la calibración corrige la sobreconfianza, no crea edge.

**Stakes (`scripts/intel_stake_sim.py`, 60 días, apuestas fuera de muestra con EV calibrado ≥ 2 %).** En el mundo
«calibración correcta» el cuarto de Kelly con tope 1 u tiene las menores caídas (mediana 8–19 %, P(caída ≥ 30 %) ≤ 7 %);
medio Kelly 63–100 % y Kelly completo ≈ 100 %. En el mundo real (los resultados que ocurrieron) todas las políticas
pierden en AH y OU — no hay edge — y el cuarto de Kelly pierde menos que la apuesta plana en los cuatro grupos (93,7
frente a 92,6; 83,6 / 79,4; 80,3 / 75,8; 94,8 / 90,8 sobre 100) con menor caída máxima; medio Kelly termina en 5–25 y
Kelly completo en ruina. stake-v1 se mantiene; con edge NOT_VALIDATED el stake de todo es 0.

**Observaciones para decision-v2 (no se cambian sin evidencia).** El filtro de riesgo marca el 97 % de las
selecciones, casi siempre por la anchura del intervalo del modelo (> 25 puntos en 525 de 611; mediana 0,37): hay que
medir en shadow si la anchura predice CLV antes de mover el umbral. El 41 % tiene precio de más de 3 h (lejos del
saque): normal en T−24/T−12. La narrativa LLM (brief-v4) usó bien el dossier pero leyó «presión de descenso» como
«están en zona de descenso»: stakes-v2 (presión solo a ≤ 2 victorias, con los huecos y el nombre de cada zona) y
brief-v5 lo corrigen. El criterio «historial» de discovery leía la fecha de carga del catálogo (29 sep) para los 338
mercados: ahora cuenta el historial con precio de los mercados activos (desde 2022).

**Disco: la prueba de restauración dejaba cada copia restaurada (corregido).** `restore-test.sh` (y el simulacro de
R2) borraban el contenedor desechable con `docker rm -f`, que conserva el volumen anónimo de datos de la imagen de
PostgreSQL: 7 volúmenes huérfanos, 78 GB, el 40 % del disco del servidor entre el 9 y el 13 de octubre, camino de
llenar el disco bajo la base viva. Ahora `docker rm -f -v` (test de regresión). Se borraron solo los dos volúmenes de
las pruebas de hoy (copias de dos copias que siguen en `backups/db`); los cinco anteriores (9–12 oct, ≈ 54 GB) quedan
para que el dueño confirme que no los necesita antes de borrarlos.
