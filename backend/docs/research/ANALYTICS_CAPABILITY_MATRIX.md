# Matriz de capacidades analíticas

**Fecha:** 25 sep 2026. Deriva de `FOOTBALL_ANALYTICS_STATE_OF_THE_ART_2026.md` y de las notas
`docs/research/notes/A1–A5`.

**Prioridades.** `P0` antes de operar en vivo · `P1` tras el backfill histórico · `P2` mejora
importante · `P3` investigación/futuro.
**¿Disponible?** `SÍ` (AVAILABLE_NOW) · `PROXY` (APPROXIMABLE: se dice qué se pierde) · `NO`.
**Proveedor extra:** `—` ninguno · `EVENTOS` (x/y; "+360" freeze frames) · `TRACKING` · `CUOTAS`
(historia tick a tick).
**Estado en V2:** ✅ implementado y probado · 🟡 parcial · ⏳ desbloqueado por el backfill ·
📋 planificado · 🔬 solo investigación.

## 1. Matriz

| Capacidad | Enfoque moderno | Datos necesarios | ¿Disponible? | Proveedor extra | Prioridad | Estado V2 |
|---|---|---|---|---|---|---|
| **Evaluación honesta** | log loss primario, Brier y RPS secundarios, calibración; walk-forward con corte temporal | predicciones + resultados + cuotas de cierre | SÍ | — | P0 | ✅ |
| Intervalos con dependencia | bootstrap por jornadas + Diebold–Mariano (HAC, HLN) | pérdidas por partido | SÍ | — | P0 | ✅ |
| Diferencia mínima detectable / "evidencia insuficiente" | potencia y equivalencia (±0,005 nats) | sd de ΔLL | SÍ | — | P0 | ✅ |
| Conjunto de confianza de modelos (MCS) | Hansen et al. 2011 por liga-temporada | matriz de pérdidas | SÍ | — | P1 | 📋 |
| Calibración CORP + ECE corregido; temperatura/isotónica | Dimitriadis 2021; Kumar 2019; Guo 2017 | temporada de validación | SÍ | — | P0 | 🟡 ECE por bins ✅; CORP 📋 |
| Registro de experimentos y model gate | tabla + ficheros con sha256; 6 checks | todo lo anterior | SÍ | — | P0 | ✅ |
| **Baseline de mercado** Pinnacle cierre (Shin, power, proporcional) | de-vig + comparación emparejada | Football-Data PSC/B365C/AvgC | SÍ | — | P0 | ✅ |
| Pre-cierre vs cierre | ΔLL emparejado por liga-temporada | FD PS vs PSC | SÍ | — | P0 | ✅ (Analytics → Market) |
| Sesgo favorito–longshot del cierre | recalibración por resultado | FD PSC desde 2012/13 | SÍ | — | P1 | 🟡 medido; recalibración 📋 |
| Cierre de Betfair neto de comisión | exchange como "verdad" casi sin margen | FD BFEC | SÍ | — | P1 | 📋 |
| Probabilidades implícitas del hándicap asiático | mapeo AH→1X2 (Hegarty & Whelan 2025a) | FD AH | PROXY | — | P2 | 📋 |
| Validación del near-close propio | 8 pruebas (procedencia, integridad, timing, cobertura, acuerdo, movimiento, estabilidad, archivo) | capturas propias + FD | SÍ (tras capturar) | — | P0 | 🟡 capturador ✅; validación ⏳ |
| CLV | O_decisión·p_cierre − 1 con IC por bloques | cuota de decisión + cierre | SÍ | — | P0 | 🟡 (line value por pick ✅; agregado 📋) |
| EV ajustado por incertidumbre | EV en el límite inferior del intervalo | p con intervalo + cuota | SÍ | — | P0 | ✅ (regla shadow-rule-v1) |
| Kelly encogido + simulación de bankroll | Baker & McHale 2013; Uhrín 2021 | picks shadow | SÍ | — | P2 | 🟡 Kelly solo informado |
| Control de multiple testing | White reality check / Hansen SPA / PBO | registro de todo lo probado | SÍ | — | P0 | 🟡 registro ✅; test 📋 |
| Steam moves, profundidad, límites | event study sobre ticks | historia tick a tick multi-casa | NO | CUOTAS | P3 | 🔬 |
| **Fuerza: Elo** margen de goles + logit ordenado | Hvattum & Arntzen 2010 | resultados | SÍ | — | P0 | ✅ |
| Ventaja de local por liga y variable en el tiempo | Elo con HA por liga + marca de puertas cerradas | resultados, sedes | SÍ | — | P0 | 🟡 (feature de liga ✅; en el Elo 📋) |
| pi-ratings | Constantinou & Fenton 2013 | resultados | SÍ | — | P1 | ✅ fv2 |
| Ratings GAP / tiros a puerta | Wheatcroft 2020 | FD tiros, a puerta, córners | SÍ | — | P1 | ✅ shares fv2 |
| xGD rodante | xG del proveedor por partido | xG de API-Football (cobertura desconocida) | PROXY | — | P1 | ⏳ |
| Ratings derivados del mercado | fuerza implícita del pre-cierre | FD PS / AH | SÍ | — | P1 | 📋 |
| Priors para ascendidos | resultados de la división inferior | tier 2–3 | PROXY | — | P1 | ⏳ |
| Glicko / Glicko-2 | desviación del rating | resultados | SÍ | — | P2 | 📋 (solo para mostrar) |
| Espacio de estados bayesiano | Owen 2011; Koopman & Lit 2015 | resultados (+ tiros) | SÍ | — | P2 | 📋 |
| **Predicción: tasas base** | referencia sin habilidad | resultados | SÍ | — | P0 | ✅ |
| Poisson (Maher) / Dixon–Coles | decaimiento + encogimiento en validación | resultados | SÍ | — | P0 | ✅ |
| Logit multinomial sobre features | L2 fijo a priori | features fv2 | SÍ | — | P1 | ✅ |
| GBM (CatBoost/LightGBM) sobre pi + tiros | Yeung 2024; Bunker 2024 | ≥ 5 temporadas | SÍ (tras backfill) | — | P2 | 📋 condición registrada |
| Apilado con pool calibrado | Ranjan & Gneiting 2010 | salidas de modelos | SÍ | — | P2 | 📋 |
| Modelo anclado al mercado | ajuste sobre el pre-cierre (Egidi 2018) | pre-cierre + modelo | SÍ | — | P1 | 📋 |
| Modelo de partido con alineaciones | Arntzen & Hvattum 2021 | alineaciones, minutos, lesiones | SÍ (tras backfill) | — | P1 | ⏳ tablas ✅ (0022) |
| Riesgo de gol en el partido (in-play) | hazard / semi-Markov por estados de marcador | minutos de goles/rojas + cuotas | SÍ | — | P1 (P0 si in-play) | ⏳ eventos |
| **xG a nivel de tiro** | localización, cuerpo, asistencia, presión | eventos x/y (+360) | NO | EVENTOS | P3 | 🔬 |
| xG-lite (dentro/fuera del área, bloqueados) | GLM de recuentos | estadísticas de equipo de API-Football | PROXY (se pierde localización y cuerpo) | — | P1 | ⏳ |
| xG / goals prevented del proveedor | caja negra, calibrada antes de usar | estadísticas de API-Football | SÍ (si el proveedor lo da) | — | P1 | ⏳ columnas ✅ |
| PSxG, habilidad de remate y de parada | GAX residualizado (Bajons & Kook 2025) | posición final del tiro, portero | NO | EVENTOS | P3 | 🔬 |
| **xT / VAEP / OBV** | valor de acción | eventos x/y | NO | EVENTOS | P3 | 🔬 |
| EPV / riesgo-recompensa del pase | tracking | tracking | NO | TRACKING | P3 | 🔬 |
| xT temporal semi-Markov (Le Coz 2026) | P(gol en T s) | eventos x/y con tiempo | NO | EVENTOS | P3 | 🔬 |
| Proxy de amenaza de equipo | Poisson de goles sobre tiros/área/córners | estadísticas de equipo | PROXY | — | P0 | 🟡 |
| **Fases tácticas** (T-GAN, FeatGRU) | grafo + Transformer | tracking + eventos + etiquetas | NO | TRACKING | P3 | 🔬 |
| Segmentación por estado de marcador | minutos ganando/empatando/perdiendo, 11 v 10 | minutos de goles y rojas | SÍ | — | P0 | ⏳ eventos |
| Índices de estilo | z-scores ajustados por estado | posesión, pases, tiros por zona | PROXY | — | P1 | ⏳ |
| **Pitch control, presión, pases, packing, forma** | física + ML sobre posiciones | tracking | NO | TRACKING | P3 | 🔬 |
| Formación declarada y roles por rejilla | alineaciones | alineaciones | SÍ | — | P1 | ⏳ tablas ✅ |
| PPDA sin localización | pases rivales / acciones defensivas | estadísticas de partido | PROXY (se pierde la zona) | — | P2 | ⏳ |
| **GNN** (receptor, pases, TacticAI, GIRL-GNN) | grafos de agentes | tracking | NO | TRACKING | P3 | 🔬 (no se implementa sin tracking) |
| Grafo de alineación para resultados | vecinos de rejilla | alineaciones | PROXY | — | P3 | 🔬 |
| **Transformers de eventos / LEM** | siguiente evento, simulación | eventos x/y de muchas temporadas | NO | EVENTOS | P3 | 🔬 |
| Modelo de secuencia sobre historiales de partido | fuerza cambiante | resultados, stats, cuotas | SÍ | — | P2 | 📋 |
| **Contrafactuales / RL** | MDP, un-xPass, RL sobre grafos | eventos x/y / tracking | NO | EVENTOS/TRACKING | P3 | 🔬 |
| Contrafactual de alineación (plus-minus) | RAPM por tramos | alineaciones, cambios, minutos de gol | SÍ (observacional) | — | P1 | ⏳ |
| **Defensa** ajustada por rival | goles/tiros/a puerta en contra, ajustados | estadísticas de equipo | SÍ | — | P0 | 🟡 shares en contra ✅ |
| Proxies de territorio | shares de tiros, área, córners, posesión | estadísticas | SÍ (no es field tilt) | — | P0 | 🟡 |
| Entradas/intercepciones ajustadas por posesión | per-90 ajustado | estadísticas de jugador | SÍ | — | P1 | ⏳ |
| DAxT, VDEP, contrapresión, compacidad | eventos/tracking | x/y; tracking | NO | EVENTOS/TRACKING | P3 | 🔬 |
| **Balón parado:** modelo de número de córners | binomial negativa / Poisson compuesta con cuotas | córners | SÍ | — | P1 | 📋 |
| Tasa y conversión de penaltis | encogimiento hacia la liga | eventos de penalti | SÍ | — | P1 | ⏳ eventos |
| xG de balón parado, zonas, primer contacto, segundas jugadas | eventos/tracking | x/y; tracking | NO | EVENTOS/TRACKING | P3 | 🔬 |
| **Jugadores:** per-90 por rol con encogimiento | fiabilidad split-half | stats de jugador, minutos, rejilla | SÍ | — | P0 | ⏳ tablas ✅ |
| RAPM de goles por tramos | Hvattum 2019; Kharrat 2020 | alineaciones, cambios, rojas, goles; ≥ 3 temporadas | SÍ | — | P1 | ⏳ |
| Rating de API-Football | caja negra validada | ratings | SÍ | — | P1 | ⏳ |
| Normalización por liga | Elo entre ligas; per-90 | todos los partidos, copas europeas | SÍ equipos / PROXY jugadores | — | P1 | 🟡 `league_elo_mean` |
| Nivel de reemplazo, curvas de edad, similitud | shrinkage, vectores per-90 | ratings, fechas de nacimiento | SÍ | — | P2 | 📋 |
| **Causal:** HA variable + puertas cerradas | experimento natural | resultados, marca de periodo | PROXY | — | P1 | 📋 |
| Regla "sin efecto entrenador" | Heuer 2011; van Ours 2016 | — | SÍ | — | P1 | ✅ (no existe ese feature) |
| Estudio DiD de cambios de entrenador | controles emparejados + placebo | resultados, cuotas, `/coachs` | PROXY | — | P3 | 🔬 |
| Actualización ajustada por rojas | minutos de rojas | eventos | PROXY | — | P2 | ⏳ |
| Efecto del pressing / estilo | cuasi-experimento | tracking / eventos | NO | TRACKING | P3 | 🔬 |
| **Incertidumbre:** gating por desviación / historia | intervalos, historia mínima | resultados | SÍ | — | P0 | 🟡 (Elo < 10 partidos declina ✅) |
| Banderas de desacuerdo y de datos incompletos | abstención selectiva | salidas, flags de cobertura | SÍ | — | P0 | 📋 |
| Intervalos posteriores / bootstrap paramétrico | cobertura PIT | modelo | SÍ | — | P1 | 🟡 Laplace ✅; PIT 📋 |
| Conjuntos conformes | cobertura garantizada | split de calibración | SÍ | — | P2 | 📋 |

## 2. Las cinco respuestas para cada técnica P0/P1 nueva

| Técnica | Pregunta | Datos | Baseline a batir | Validación | Valor de producto |
|---|---|---|---|---|---|
| pi-ratings (✅) | ¿cuánto mejor es un equipo, en goles esperados, en casa y fuera? | resultados | Elo V2 + logit | walk-forward ΔLL con bootstrap por jornadas | feature del modelo; ranking alternativo en Analytics |
| Shares de tiros / a puerta (✅) | ¿quién genera más peligro, más allá de los goles? | FD/API tiros, a puerta | modelo solo-goles | ΔLL con y sin el feature (ablation) | perfil de equipo; feature |
| Forma residual sobre Elo (✅) | ¿rinde por encima de lo que dice su rating? | resultados + Elo | ppg de los últimos 5 | ablation | "forma real" en el Match Center |
| Tasas base (✅) | ¿aprendió algo el modelo? | resultados | — (es el suelo) | log loss en muestra común | referencia visible en Models Lab |
| Logit multinomial (✅) | ¿añaden los features v2 algo a Elo? | features fv2 | Elo + logit ordenado; mercado | walk-forward; gate de 6 checks | primer modelo con features; hoy el más cercano al mercado |
| Bootstrap por jornadas + DM + MDD (✅) | ¿es real la diferencia y podía detectarse? | pérdidas por partido | bootstrap iid | cobertura simulada (test de bloques) | etiqueta de evidencia en cada comparación |
| HA por liga variable (📋 P0) | ¿cambió la ventaja de local y la valoramos? | resultados, periodos | HA constante | ΔLL 2020/21; pre-tendencias | menos sesgo en ligas con HA distinto |
| Validación del near-close (P0) | ¿nuestra captura es un cierre? | capturas + FD | cierre de FD | |Δp| mediana ≤ 0,5 pp, |ΔLL| < 0,002, pendiente ≈ 1 | CLV real en vez de provisional |
| Banderas de abstención (📋 P0) | ¿este pronóstico es frágil? | salidas, cobertura | sin banderas | log loss con/sin bandera; riesgo-cobertura | no se muestra "valor" donde no hay evidencia |
| Ratings de mercado (📋 P1) | ¿qué fuerza implica el mercado? | pre-cierre | Elo V2 | Δ vs pre-cierre y cierre | la mayor reducción esperada de la brecha |
| Modelo con alineaciones (⏳ P1) | ¿cómo cambia el pronóstico una ausencia? | alineaciones, lesiones, RAPM | modelo solo-equipo | walk-forward con marcas de tiempo | explicar movimientos del mercado por noticias |
| Riesgo de gol in-play (⏳ P1) | P(resultado) según avanza el partido | minutos de eventos + cuotas | Poisson de tasa constante | Brier/log loss por minuto | producto en vivo |
| MCS (📋 P1) | ¿qué modelos empatan con el mejor? | pérdidas | tests por pares | por liga-temporada | ranking honesto de modelos |
| Recalibración del cierre (📋 P1) | ¿queda FLB en el cierre de Pinnacle? | PSC 2012/13+ | mejor de-vig | fit en temporadas pasadas; diagramas | un baseline más justo y más duro |
