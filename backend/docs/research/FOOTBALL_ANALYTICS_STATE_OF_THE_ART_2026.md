# Estado del arte en analítica de fútbol 2024–2026, leído contra nuestros datos

**Fecha:** 25 sep 2026. **Alcance:** las 15 áreas pedidas (PARTE B), con la pregunta que importa
para V2 en cada una: *¿qué se puede construir con API-Football v3 + Football-Data.co.uk, qué
baseline hay que batir y cómo se valida?*

## Método

- **Fuentes.** Revistas revisadas por pares (IJF, JQAS, Machine Learning, JRSS, Scientific
  Reports, PLOS ONE, Statistical Modelling, JASA…), arXiv, actas (KDD, MIT SSAC, MLSA, ISACE,
  CVPR-W, StatsBomb Conference, Hudl Performance Insights), laboratorios universitarios (KU Leuven
  DTAI, TU Munich) y la metodología publicada por los proveedores (Hudl StatsBomb, SkillCorner,
  Stats Perform/Opta). **Se excluyeron** los blogs de SEO y los agregadores sin autor.
- **Verificación.** Cada ítem citado se abrió en el editor, en arXiv, PubMed, Crossref o ML
  Anthology, y cada afirmación se comprobó contra su resumen o su texto. Cuando solo se pudo leer
  el registro bibliográfico, la afirmación no pasa del título o se marca *(no verificado)*. Los
  cuatro trabajos que pediste por su nombre existen y están verificados (§2, §3, §5).
- **Clasificación de cada técnica contra nuestros datos:**
  `AVAILABLE_NOW` (se construye hoy) · `APPROXIMABLE` (con un proxy; se dice qué se pierde) ·
  `REQUIRES_EVENT_PROVIDER` (necesita eventos con coordenadas x/y; "+360" = además freeze frames)
  · `REQUIRES_TRACKING_PROVIDER` (necesita tracking de los 22 jugadores).
- **Prioridad:** `P0` antes de operar en vivo · `P1` tras el backfill histórico · `P2` mejora
  importante · `P3` investigación/futuro. Detalle en `ANALYTICS_CAPABILITY_MATRIX.md`.
- **Regla para toda técnica nueva:** qué pregunta responde, qué datos necesita, qué baseline debe
  batir, cómo se valida y qué valor de producto tiene. Sin las cinco respuestas no entra.
- Donde la literatura no permite concluir, este documento dice **NO HAY EVIDENCIA SUFICIENTE**.

### Nuestros datos, sin adornos

| Fuente | Qué tenemos | Qué NO tenemos |
|---|---|---|
| API-Football v3 (plan de pago tras la compra) | fixtures, resultados (HT/ET/penaltis), eventos con minuto (goles, tarjetas, cambios, VAR), estadísticas de equipo y de jugador por partido, alineaciones con posición en rejilla, lesiones (desde abr-2021), clasificaciones, cuotas pre-partido (historia de 7 días) y en vivo (sin historia) | coordenadas x/y de ninguna acción, freeze frames, tracking; xG documentado (solo aparece como etiqueta en el fichero de traducción de los widgets) |
| Football-Data.co.uk | resultados, tiros, tiros a puerta, córners, faltas, tarjetas; cuotas de cierre y pre-cierre (Pinnacle, Bet365, media, máxima, Betfair) | eventos, alineaciones |

**Conclusión de partida:** casi todo el estado del arte de 2024–2026 (xT, VAEP, EPV, fases con
tracking, GNN, pitch control, pressing) necesita datos que no tenemos. Lo que sí podemos hacer
bien está a nivel de partido: ratings de fuerza, procesos de tiros, modelos de riesgo de gol en
el partido, plus-minus de alineaciones y, sobre todo, una evaluación honesta contra el mercado.

---

## Resumen ejecutivo: lo que cambia nuestro roadmap

1. **Ningún modelo público verificado bate un cierre "sharp" con una regla de puntuación
   propia** (log loss, Brier). Los "beneficios" publicados se miden contra cuotas medias,
   Bet365 o las mejores disponibles, en pocas temporadas (Holmes & McHale 2024; Wilkens 2026;
   Bunker et al. 2024). El mercado es el baseline a batir, no un rival a ignorar.
2. **Nuestra brecha es real y está medida:** sesión 2, 1.674 partidos comunes, el mejor modelo
   (logit multinomial con features v2) pierde contra el cierre de Pinnacle por **+0,0229 nats
   [+0,0140, +0,0314]** con bootstrap por jornadas y DM p < 0,001. El Elo de Hvattum &
   Arntzen (2010) quedaba a ≈0,005–0,006 nats, pero de las cuotas máximas y medias: un benchmark
   más blando que el cierre de Pinnacle.
3. **Lo que más puede cerrar la brecha**, por orden de evidencia: (a) medirse y anclarse al
   **pre-cierre** de Pinnacle y al hándicap asiático; (b) ratings de jugadores sensibles a
   alineación y lesiones; (c) ratings de tiros/tiros a puerta y, si existe, xG del proveedor;
   (d) pi-ratings + gradient boosting con apilado calibrado; (e) ventaja de local por liga y
   variable en el tiempo.
4. **Pi-ratings** son el mejor feature de solo-goles en los dos desafíos de predicción
   (2017, 2023) → **implementados** (fv2.0.0, parámetros publicados, no ajustados).
5. **Tiros y tiros a puerta** llevan información más allá de las cuotas (Wheatcroft 2020, 2021a)
   → **implementados** desde los CSV de Football-Data que ya teníamos (10.658 filas).
6. **El bootstrap pareado por partido subestima la incertidumbre**; bloques por jornada + test de
   Diebold–Mariano con varianza HAC y corrección HLN + diferencia mínima detectable →
   **implementados** en toda comparación modelo-mercado.
7. **Log loss es la métrica principal**; RPS solo para comparar con la literatura (Wheatcroft
   2021b); la accuracy no ordena nada → así está en el código y en la UI.
8. **Proporcional deja dentro el sesgo favorito–longshot**; Shin/power lo reducen. En nuestros
   5.329 partidos, el cierre de Pinnacle de-vigged por Shin sigue sobreestimando los longshots
   (bucket 0–10 %: 7,3 % declarado vs 5,2 % observado) → recalibración por resultado es P1.
9. **GNN, Transformers, fases tácticas, pitch control y modelos contrafactuales** requieren
   tracking o eventos x/y → **RESEARCH/FUTURE**, no se implementan sin esos datos.
10. **Inferencia causal:** el "efecto del nuevo entrenador" es regresión a la media (Heuer et al.
    2011; van Ours & van Tuijl 2016) → **no** se crea ese feature. La importancia de un feature
    no es un efecto causal y la UI no lo presenta como tal.

---

## 1. Expected goals (xG), post-shot y porteros

**Estado del arte.**
- Un xG moderno usa localización, ángulo, parte del cuerpo, tipo de jugada, acción previa y
  contexto de portero y defensores; Opta usa más de 20 variables y fija el penalti en 0,79
  (Opta Analyst 2023). Los freeze frames añaden bloqueadores (Vatvani 2022), el tracking añade
  presión (Anzer & Bauer 2021) y los esqueletos 3D la orientación del cuerpo (Xu et al. 2025).
- **Rendimientos decrecientes:** los árboles potenciados necesitan como mucho ~5 temporadas;
  mezclar ligas vale, mezclar proveedores no (Robberechts & Davis 2020). Un modelo bayesiano
  mixto de 7 variables alcanza AUC 0,781 frente a 0,801 de StatsBomb (Iapteff et al. 2025).
- **Validación:** log loss, Brier y calibración por subgrupo; la AUC es secundaria; la accuracy
  es inútil (StatsBomb 0,911 vs 0,904 de una constante, pero log loss 0,254 vs 0,316; Bajons &
  Harringer 2025). Partir por partido o temporada (Davis et al. 2024). Las probabilidades de
  partido se calculan exactas con una Poisson-binomial, no con Monte Carlo (Davis, Robberechts &
  Van Haaren 2025).
- **Habilidad de remate:** goles sobre xG (GAX) es ruidoso y sesgado hacia cero (Davis &
  Robberechts 2024); el GAX residualizado da intervalos válidos (Bajons & Kook 2025).

**Con nuestros datos.** No podemos construir xG a nivel de tiro, PSxG ni habilidad de remate o
de parada: no tenemos localización, parte del cuerpo, tipo de asistencia ni posición final.
Sí podemos: ratings de tiros y tiros a puerta (`AVAILABLE_NOW`), un "xG-lite" con los tiros
dentro/fuera del área y bloqueados de API-Football (`APPROXIMABLE`: se pierde localización fina,
cuerpo y presión) y el `expected_goals` del proveedor como caja negra, **solo tras comprobar su
calibración** (su cobertura no está documentada: NO HAY EVIDENCIA SUFICIENTE de desde cuándo ni
en qué ligas existe).

**Decisión.** P0: shares de tiros y de tiros a puerta (hecho, fv2). P1: xG-lite y xG del
proveedor, con una prueba de calibración (xG sumado vs goles) antes de usarlo. P3: xG a nivel de
tiro (P1 si se compran eventos x/y).

## 2. Valor de posesión (xT, VAEP, EPV, OBV)

**Estado del arte.**
- **xT** valora zonas por probabilidades de tirar/mover (Singh 2019); **VAEP** valora una acción
  por su cambio en P(marcar) − P(encajar) en las 10 acciones siguientes (Decroos et al. 2019);
  **EPV** descompone el valor desde tracking (Fernández et al. 2021); **OBV** ajusta modelos de
  gol a favor y en contra sin historial de posesión (StatsBomb 2021). Estabilidad split-half:
  ρ 0,89 xT vs 0,25 VAEP (Van Roy et al. 2020).
- **Le Coz, Boustila & Imbach (2026), *Scientific Reports* 16:22590 — verificado.** Marco
  semi-Markov: estados = tipo de acción × zona; duraciones con modelos AFT condicionados a
  distancia y ángulo, con la familia de distribución elegida por transición. *xT temporal* =
  P(gol en T s), por inducción hacia atrás. 537 partidos de StatsBomb open data. Mejora el Brier
  de un baseline de retardo fijo en todos los horizontes (0,0190 vs 0,0568 a 300 s), la AUC solo
  entre 120–300 s, y el xT estándar mantiene mejor Brier a 300 s (0,0152): los autores lo
  reservan para decisiones de final de partido. Sin covariables de marcador ni rival.
- **van Arem, Söhl, Bruinsma & Jongbloed (2026), arXiv:2604.21087 — verificado.** El error
  máximo entre zonas (bootstrap de la cadena de Markov) es aproximadamente lognormal en el
  tamaño N y el número de zonas M. Con la tolerancia de 0,0192 fijada por expertos (menos del
  10 % de jugadores cambian de cuartil de scouting con probabilidad 0,9), 2,48 M de eventos
  sostienen una rejilla 10×8 y la 16×12 necesita ~3,35 M (~5,4 temporadas).
- No se pudo replicar EPV (Overmeer et al. 2025). Con tracking de 918 partidos de Bundesliga,
  el RPS pre-partido fue 0,194 con EPV, 0,199 con xG y 0,202 con Elo (Forcher et al. 2025b):
  ganancia pequeña, y necesitó tracking.

**Con nuestros datos.** Nada a nivel de acción (`REQUIRES_EVENT_PROVIDER`; EPV
`REQUIRES_TRACKING_PROVIDER`). Sí un proxy de amenaza de equipo (tiros en el área, a puerta,
córners; `APPROXIMABLE`, se pierde crédito por acción, localización y secuencia).

**Decisión.** P0 proxy de amenaza de equipo (parcialmente hecho: shares de tiros). P3 xT/VAEP;
si algún día se licencian eventos x/y, **dimensionar la rejilla xT con la regla de van Arem**
antes de publicar valores por jugador.

## 3. Fases tácticas

**Estado del arte.** **Li & Link (2026), arXiv:2606.09289 (TU München) — verificado.** Tres
intenciones (Invadir espacio, Mantener posesión, Finalizar) en seis fases; *T-GAN* = grafo de
interacción por frame + Transformer temporal; 7 partidos de Bundesliga (TRACAB), un anotador,
leave-one-match-out. F1 por frame 0,87 (intenciones) y 0,76–0,79 (fases); tIoU 0,67 y 0,57. Un
Transformer solo casi iguala en intenciones; el grafo ayuda sobre todo en *contraataque*.
Antecedentes: FeatGRU 80 % de acuerdo con expertos (Biermann et al. 2025), segmentación CNN F1
0,76 (Bauer, Anzer & Shaw 2023). SkillCorner (2025) define fases con tracking + eventos Wyscout
con reglas explícitas (p. ej., *Direct* = balón largo ≥ 32 m).

**Con nuestros datos.** Imposible sin secuencias de posesión. Posible: segmentación por estado
del marcador desde los minutos de goles y rojas (`AVAILABLE_NOW`) y índices de estilo por
temporada (`APPROXIMABLE`).

**Decisión.** P0 segmentación por estado de marcador (desbloqueada por los eventos del
backfill). P3 fases.

## 4. Analítica espacial y de tracking

| Técnica | Pregunta | Clasificación |
|---|---|---|
| Pitch control / OBSO (Spearman et al. 2017; Spearman 2018) | quién controla qué espacio y su valor | REQUIRES_TRACKING_PROVIDER |
| Presión sobre el portador (Bekkers 2025; Narizuka et al. 2026) | cuánta presión, y qué provoca | REQUIRES_TRACKING_PROVIDER |
| Dificultad de pase / receptor (Anzer & Bauer 2022, AUC 93,4 %; Rahimian et al. 2026; Masella et al. 2026) | qué pases estaban disponibles | REQUIRES_TRACKING_PROVIDER |
| Packing / líneas superadas (Rein et al. 2017; Karakuş & Arkadaş 2026) | defensores superados por pase | REQUIRES_TRACKING_PROVIDER (o freeze frames) |
| Compacidad, anchura/profundidad (Low et al. 2020; Brandes et al. 2025) | forma del equipo | REQUIRES_TRACKING_PROVIDER |
| Carreras sin balón, orientación (May 2023; Arbués-Sangüesa et al. 2020) | calidad de movimiento | REQUIRES_TRACKING_PROVIDER |
| Formación declarada y roles por rejilla | forma nominal | **AVAILABLE_NOW** (alineaciones) |
| PPDA sin localización | presión que sufre el rival | **APPROXIMABLE** (se pierde la zona, el núcleo del pressing) |

**Decisión.** P1 formación declarada (llega con el backfill); P2 PPDA-lite; el resto P3.

## 5. Graph Neural Networks — el problema antes que el modelo

**Cuándo gana una GNN.** Cuando (a) la entrada es un conjunto no ordenado de agentes que
interactúan (22 jugadores + balón), (b) la respuesta depende de dónde están unos respecto de
otros (quién puede recibir, qué línea está cerrada) y (c) la salida es por jugador o por
situación. Eso requiere la posición de todos: tracking o freeze frames.

**Evidencia.** TacticAI (Wang et al. 2024, 7.176 córners de Liverpool): top-3 de receptor 0,364
CNN → 0,723 MPNN → 0,782 GATv2 con simetría; los expertos prefirieron sus sugerencias en 45 de 50
casos. **Lin, Chen & Liu (2026), *Scientific Reports* 16:26974 (GIRL-GNN) — verificado:** grafo
jugador/balón/zona + RL offline con restricción de factibilidad; 7 partidos IDSSE; ΔxT +0,04 a
+0,08 estimado por los propios modelos para acciones nunca jugadas; analistas prefirieron su
elección el 61 % (κ = 0,51). Un MPNN supera a un ranker LambdaMART en receptor, 75,8 % vs 44,6 %
top-1 (Masella et al. 2026).

**Con nuestros datos.** No hay posiciones ni interacciones jugador-jugador: una GNN no tiene
nada relacional que aprender. Un "grafo de alineación" (vecinos de rejilla) es posible pero
**NO HAY EVIDENCIA** de que bata a gradient boosting con Elo y cuotas. **Decisión: P3; no se
implementa GNN sin tracking.**

## 6. Transformers y modelos de secuencia

**Estado del arte.** Secuencias de eventos: Seq2Event (Simpson et al. 2022), Large Events Model
(Mendes-Neves et al. 2024), simulación de fichajes estilo GPT (Hong et al. 2025, 2026); las
*path signatures*, más baratas, baten a un Transformer de referencia (Hirnschall & Bajons 2025).
El Transformer axial de Stats Perform (58.501 partidos) se valida solo por calibración "given the
unavailability of existing baseline models" (Horton & Lucey 2025).

| Familia | Datos (indicativo) | Interpretabilidad | Validación |
|---|---|---|---|
| RNN | cientos a miles de partidos de eventos | baja | log-loss del siguiente evento; acuerdo con expertos |
| Transformer | el mayor (muchas temporadas) | baja; atención ≠ explicación | debe batir a Markov y path signatures en cortes temporales; los contrafactuales no se pueden verificar |
| Temporal Graph Network | interacciones con marca de tiempo entre jugadores (tracking o pases) | baja–media | calibración por arista; hold-out por partido |
| **Semi-Markov / riesgo (hazard)** | marcas de tiempo + espacio de estados pequeño; funciona con datos escasos | **alta** | Brier y AUC por horizonte; calibración por minuto |

**Con nuestros datos.** Un partido tiene ~10–20 eventos con minuto: demasiado poco para un
Transformer. Sí cabe un **modelo de riesgo de gol / estados de marcador** (el análogo de partido
del xT temporal de Le Coz et al.): `AVAILABLE_NOW`, baseline Poisson de tasa constante desde las
cuotas y Dixon–Coles, validación Brier/log-loss por minuto. **Decisión:** P1 (P0 si hay
producto in-play); Transformers P3 hasta que exista un problema definido y los datos.

## 7. Modelos contrafactuales y de decisión — RESEARCH/FUTURE

Con eventos: MDP de decisiones de equipo (Van Roy et al. 2021, 2023), un-xPass (Robberechts et
al. 2023), xG contrafactual bayesiano (Mahmudlu et al. 2025). Con tracking: EPV de opciones no
elegidas, RL multiagente (Nakahara et al. 2023), RL sobre grafos para córners (Groom et al. 2026:
+0,068 de P(tiro) esperada por córner, puntuada por una GNN congelada; los defensores no
reaccionan y nada se probó en el campo). **Limitación común:** el resultado contrafactual nunca
se observa; la evaluación es modelo-sobre-modelo o preferencia de expertos.
**Con nuestros datos:** contrafactual de alineación vía plus-minus regularizado (observacional,
no causal; baseline: el cierre, que se fija después de conocer las alineaciones). **Decisión:**
todo el bloque es **RESEARCH/FUTURE (P3)**, salvo el plus-minus de alineaciones (P1, §11).

## 8. Analítica defensiva

**Estado del arte.** PPDA mide intensidad y estilo, no calidad, y lo confunde el dominio
territorial (Trainor 2014; Stats Perform). Los recuentos brutos de entradas e intercepciones no
correlacionan con tiros ni goles en contra; ajustados por posesión explican ~40 % (Knutson 2014,
evidencia de blog). DAxT (Merhej et al. 2021) y VDEP (Toda et al. 2022; F1 > 0,483 vs < 0,201 de
los clasificadores basados en gol) necesitan eventos o tracking; compacidad y contrapresión
(Bauer & Anzer 2021, AUC 0,874; Forcher et al. 2024a/b) necesitan tracking.

**Con nuestros datos.** Ratings defensivos ajustados por rival (goles, tiros, a puerta en
contra; `AVAILABLE_NOW`); proxies de territorio (shares de tiros y córners; **no** son field
tilt); entradas/intercepciones ajustadas por posesión; PPDA-lite de partido entero; plus-minus
defensivo. **Decisión:** P0 ajustado por rival (hecho en parte: shares a favor/en contra y
forma residual sobre Elo), P1–P2 el resto, P3 lo que requiere x/y.

## 9. Balón parado

**Estado del arte.** Lo lidera el tracking: TacticAI (receptor top-3 0,782, F1 de tiro 0,71),
RL sobre grafos para colocar jugadores (Groom et al. 2026), clasificación de roles defensivos
89,3 % (Bauer, Anzer & Smith 2022). **Tasas base:** córner → tiro 20,7–31,2 %, gol 2,2–4,43 %
(Plakias et al. 2025); falta directa 9/264 goles en la Premier 2023/24 (Ridge 2024); saques de
banda 8,8 % → tiro (Stone et al. 2021). Recuentos de córners: Poisson compuesta con cuotas (Yip
et al. 2024). **No hay modelo revisado por pares de segundas jugadas** (NO HAY EVIDENCIA).

**Con nuestros datos.** Modelo de número de córners (binomial negativa/Poisson compuesta con la
fuerza tomada de las cuotas; `AVAILABLE_NOW`), córners como input del modelo de partido, tasas de
penaltis encogidas hacia la liga. Los goles no traen etiqueta de tipo de jugada (salvo
penalti/propia, a confirmar), así que xG de balón parado, zonas de centro, primer contacto y
segundas jugadas son `REQUIRES_EVENT_PROVIDER`/`TRACKING`. **Decisión:** P1 córners y penaltis;
P3 el resto. Multiplicar córners por un 2–4 % de conversión es demasiado burdo para publicarlo.

## 10. Fuerza de equipo

**Estado del arte.**
- **Elo** con margen de goles en un logit ordenado (Hvattum & Arntzen 2010) — nuestro Elo V2 —
  bate a seis benchmarks no de mercado y pierde claramente contra las cuotas.
- **pi-ratings** "substantially outperform" a Elo (Constantinou & Fenton 2013) y son el feature
  por defecto en los dos desafíos de predicción (Hubáček et al. 2019a; Yeung et al. 2024).
- **Glicko/Glicko-2:** evidencia escasa en fútbol; un Glicko-2 adaptativo mejora el Brier un
  4,04 % sobre el estándar y sigue por detrás del mercado (Nguyen & Tran 2026).
- **Modelos de goles:** Poisson con decaimiento temporal, bivariante y bivariante con inflación
  diagonal; con decaimiento, la Poisson bivariante e independiente fueron las mejores de diez
  (Ley et al. 2019). **Dinámicos/espacio de estados** baten a estáticos (Owen 2011; Koopman &
  Lit 2015, 2019).
- **Ratings de mercado, multitud y jugadores:** el Elo actualizado con cuotas bate al de goles,
  pero las cuotas siguen siendo mejores (Wunderlich & Memmert 2018); Elo de equipo +
  plus-minus de jugadores bate a cada uno por separado (Arntzen & Hvattum 2021).
- **Tiros y xG:** ratings GAP con tiros, a puerta y córners (Wheatcroft 2020); las estadísticas
  predichas añaden información más allá de las cuotas máximas, con "a downturn in profit in
  recent seasons" (Wheatcroft 2021a). xG predice mejor que goles o tiros (Mead et al. 2023; con
  coordenadas).
- **La revisión de Sciety** (Lee, Mohamad & Asirvatham 2026, Preprints.org, **no revisada por
  pares**, 0 evaluaciones): "Rolling expected goal difference was the most transferable
  team-level signal". Su apoyo principal (Brechot & Flepp 2020) usa xG para evaluar
  rendimiento, no como benchmark de predicción → **hipótesis a probar, no un hecho.**

**Con nuestros datos / decisión.** Implementado (fv2): pi-ratings con parámetros publicados,
shares de tiros y a puerta de los últimos 10 partidos con estadísticas, forma como resultado −
esperado por Elo, ventaja de local actual de la liga en goles y Elo medio de la liga. P0
pendiente: ventaja de local por liga **variable en el tiempo** dentro del Elo. P1: ratings
derivados del mercado (pre-cierre), priors para ascendidos, xGD rodante donde el proveedor dé
xG. P2: espacio de estados bayesiano; Glicko solo para mostrar incertidumbre.

## 11. Evaluación de jugadores

**Estado del arte.** Valores de acción (VAEP, xT, OBV, EPV) con validación separada del modelo:
validez aparente, robustez split-half (VAEP solo moderadamente robusto), validez divergente y
utilidad (Davis, Robberechts & Van Roy 2025). **Plus-minus:** revisado por Hvattum (2019); batió
a un rating basado en VAEP en fiabilidad y validez predictiva (Hvattum & Gelade 2021); Elo +
plus-minus predice mejor que cada uno (Arntzen & Hvattum 2021). El contexto (fuerza del equipo,
de la liga) confunde el output individual (Andorra & Göbel 2024; Shelopugin & Sirotkin 2026);
pocos jugadores cambian de liga para traducir números directamente (McIntosh & Beckmann 2025).
Pico de rendimiento ~25–27 años (Dendir 2016; Säfvenberg et al. 2024).

**Con nuestros datos.** Lo más fuerte es un **RAPM por tramos** desde alineaciones, cambios,
rojas y minutos de gol (≥ 3 temporadas, priors por rol), alimentando un modelo de partido
sensible a la alineación. También: per-90 ajustado por rol con encogimiento, el rating de
API-Football tras validarlo, Elo entre ligas, nivel de reemplazo, curvas de edad, similitud.
**No:** VAEP, xT, OBV, EPV, valor sin balón, embeddings de secuencias. **Decisión:** P0 per-90
ajustado por rol; P1 RAPM y modelo con alineaciones (tras el backfill de eventos y alineaciones).

## 12. Predicción de partidos — reglas de puntuación propias, no accuracy

**Estado del arte.**
- **Desafíos:** 2017 (206 partidos, RPS) lo ganaron features a mano + árboles potenciados
  (Hubáček et al. 2019a); 2023 (736 partidos): "relatively simple learning algorithms perform
  remarkably well" (Berrar et al. 2024). CatBoost + pi-ratings: RPS 0,1991–0,2145 en tres
  temporadas de test, el consenso de casas le ganó un 6,42 % (Yeung et al. 2024).
- **El mercado:** Shin bate a la normalización, menos en mercados grandes (Štrumbelj 2014); 1X2
  con fuerte sesgo favorito–longshot y hándicap asiático eficiente (Hegarty & Whelan 2025); las
  ineficiencias aparentes de una temporada no persisten entre ligas (Winkelmann et al. 2024).
- **Reglas de puntuación:** el log score es la única regla propia local (Gneiting & Raftery
  2007); en simulación el ignorance (log) score bate a RPS y Brier (Wheatcroft 2021b).
- **Calibración:** diagramas CORP con bandas (Dimitriadis et al. 2021); ECE con estimadores
  corregidos (Kumar et al. 2019); los pools lineales salen descalibrados y un pool beta lo corrige
  (Ranjan & Gneiting 2010).
- **Validación:** fuera de muestra en orden temporal (Cerqueira et al. 2020); la fuga temporal es
  parte de la taxonomía de leakage (Kapoor & Narayanan 2023).

**Qué hacemos (implementado).** Log loss principal; Brier y RPS secundarios; ECE por
bins; accuracy mostrada solo como dato "no rankeado". Walk-forward con reajuste diario,
hiperparámetros solo en la temporada de validación, corte 60 min antes del primer kick-off del
bloque y **comprobación de fuga en cada bloque** (y test que reescribe el futuro y exige el mismo
pasado). Cinco familias activas: **base rates** (referencia sin habilidad), Poisson, Dixon–Coles,
Elo + logit ordenado, **logit multinomial** (fv2). GBM y ensemble **planificados** con su
condición (≥ 5 temporadas por competición; ≥ 2 familias en el conjunto de confianza).

**Resultados reales (sesión 2, test 2024/25, 5 ligas, 1.674 partidos comunes, log loss):**
Pinnacle cierre (Shin) 0,95853 · mnlogit 0,98145 · Poisson 0,98295 · Dixon–Coles 0,98329 · Elo
0,98791 · base rates 1,07772. Todos baten a las tasas base por mucho; ninguno al mercado.

## 13. Inteligencia de mercado de apuestas

**Estado del arte.**
- **De-vig:** proporcional, aditivo, Shin, power, odds-ratio (Clarke et al. 2017). Shin ganó en
  217 de 412 pares casa–competición (Štrumbelj 2014); el z de Shin correlaciona 0,99 con el
  overround en fútbol: mide margen, no insiders (Whelan 2025b).
- **FLB:** con normalización proporcional de las medias de cierre en 84.230 partidos, los
  longshots devuelven 0,83 por unidad y los favoritos 0,98; el hándicap asiático es insesgado
  (Hegarty & Whelan 2025a). Las tasas de pérdida realizadas superan el margen implícito (8,7 % vs
  7,1 %), Pinnacle incluido (Hegarty & Whelan 2025b).
- **Sharp vs soft:** las casas "position-takers" limitan a los informados; ~la mitad de 545
  carteras de arbitraje no eran ejecutables (Grant et al. 2018); apostar donde la máxima se
  aparta del consenso rindió 3,5 % simulado hasta que limitaron las cuentas (Kaunitz et al.
  2017).
- **El cierre** es el mejor benchmark, no un oráculo; **no encontramos validación revisada por
  pares del CLV en sí** (NO HAY EVIDENCIA SUFICIENTE); su justificación descansa en la eficiencia
  del cierre y en que el ROI es una medida ruidosa (Wunderlich & Memmert 2020).
- **Staking:** Kelly formal fue "infeasible in almost all practical scenarios" con
  probabilidades estimadas; Kelly fraccional sí funcionó (Uhrín et al. 2021).
- **Tamaño muestral del ROI (aritmética nuestra):** 1.000 apuestas dan un IC95 de ±6–9 puntos;
  bajar a ±2 puntos exige 9.600–21.600 apuestas. Nuestro ROI hipotético de −3,2 % (mnlogit, IC
  [−11,5 %, +4,9 %]) no dice nada; la brecha en log loss sí.

**Con nuestros datos / decisión.** Hecho: baseline Pinnacle cierre Shin + proporcional y power +
pre-cierre + media + Bet365, todos comparados por partido emparejado. **Medido hoy** en 5.329
partidos: calibración del cierre por buckets y cuánto aporta el pre-cierre→cierre por liga y
temporada (Analytics → Market). Pendiente P0 en vivo: las 8 pruebas antes de llamar "cierre" a
nuestra captura near-close (hoy: "near-close snapshot (no validado)"). P1: recalibración por
resultado del cierre, cierre de Betfair neto de comisión, apilado modelo–mercado. P3: timing de
"steam moves" (necesita ticks: `REQUIRES_ODDS_PROVIDER`).

## 14. Inferencia causal

**Estado del arte.** Predecir y explicar difieren en cada paso (Shmueli 2010); la importancia de
un feature no es un efecto. Cambios de entrenador: sin efecto; la recuperación es regresión a la
media y los controles emparejados mejoran igual (Heuer et al. 2011; van Ours & van Tuijl 2016).
Rojas: suben la tasa de gol del equipo **no** penalizado (Titman et al. 2015). Ventaja de local
sin público (experimentos naturales, DiD, mediación): bajó en 11 de 17 ligas y subió en 6 (Benz &
Lopez 2023); ~80 % del descenso vía rendimiento y ~20 % vía árbitros (Bilalić et al. 2021); el
mercado la valoró mal a corto plazo (Winkelmann et al. 2021). Tácticas y pressing: casi todo
correlacional; **no se encontró una estimación cuasi-experimental verificada del efecto del
pressing** (NO HAY EVIDENCIA SUFICIENTE).

**Decisión.** Estructura del modelo informada por lo causal: ventaja de local variable en el
tiempo con marca de partidos a puerta cerrada (P1), **ningún feature de "efecto entrenador"**,
bajar el peso de goles tras una roja temprana (P2). Estudio interno factible: DiD de cambios de
entrenador con controles emparejados (P3, con `/coachs`). Toda correlación táctica se etiqueta
como asociativa.

## 15. Incertidumbre

**Estado del arte.** Diebold–Mariano para comparar pronósticos con errores correlacionados
(Diebold & Mariano 1995; Diebold 2015) y su corrección HLN (Harvey, Leybourne & Newbold 1997);
Giacomini–White condicional (2006); el conjunto de confianza de modelos (MCS) crece cuando los
datos no informan: un "evidencia insuficiente" formal (Hansen et al. 2011). Bootstrap por
bloques/estacionario para dependencia (Künsch 1989; Politis & Romano 1994). Separar incertidumbre
epistémica y aleatoria (Hüllermeier & Waegeman 2021); abstención selectiva y conjuntos conformes
con cobertura garantizada (Geifman & El-Yaniv 2017; Angelopoulos & Bates 2021).

**Implementado.** Bootstrap por jornadas (bloque = fecha de kick-off, 2.000 remuestreos),
DM con Newey–West y HLN contra t(n−1), RPS con intervalo, diferencia mínima detectable al 80 % de
potencia desde el error estándar del bootstrap, y **etiqueta de evidencia**: `sufficient` (el
intervalo excluye 0), `equivalent` (dentro de ±0,005 nats, fijado antes de la sesión 2) o
`insufficient`. Intervalos de parámetros (Laplace) en Poisson/DC/Elo. **Pendiente:** MCS por
liga-temporada (P1), reglas de abstención (disputa entre modelos, datos incompletos, equipos con
poca historia) para suprimir etiquetas de "valor" (P0 para el live, ver GO_LIVE_CHECKLIST).

---

## Qué incorporamos (con código, tests y commit)

| Hallazgo | Implementación | Dónde |
|---|---|---|
| pi-ratings (Constantinou & Fenton 2013) | fv2: `pi_home`, `pi_away`, `pi_expected_gd`, λ = 0,035, γ = 0,7, b = 10, c = 3 fijos | `src/fbi/features/pi.py`, `engine.py` (f8b8969) |
| Tiros/a puerta informan más allá de las cuotas (Wheatcroft 2020, 2021a) | shares de tiros y de tiros a puerta (últimos 10 con estadísticas) + su n | `engine.py`; datos FD `f5e8520` |
| Forma ajustada por rival | resultado − esperado por Elo, últimos 10 | `engine.py` |
| Ventaja de local y fuerza por liga | `league_home_gd_avg`, `league_elo_mean` | `engine.py` |
| Bootstrap por bloques, DM-HLN, MDD, RPS (A3) | toda comparación modelo–mercado | `metrics.py`, `evaluate.py` (e5416d4) |
| "Evidencia insuficiente" formal | etiqueta `sufficient/equivalent/insufficient` | `evaluate.py` |
| Tasas base como referencia sin habilidad | familia `base_rates` | `walkforward.py`, `families.py` |
| Features de GBM sin GBM (datos insuficientes) | logit multinomial L2 fijo a priori sobre fv2 | `logistic.py` |
| Registro de investigación y model gate | 6 checks; PRODUCTION solo con gate superado | `src/fbi/research/` (ac8ec90) |
| Mercado como baseline, FLB medido | calibración del cierre y pre-cierre→cierre por liga | `/api/v1/analytics/market` (432a73b) |

## Qué NO implementamos a propósito (y qué dato falta)

| Técnica | Por qué no | Qué haría falta |
|---|---|---|
| xG a nivel de tiro, PSxG, GAX | sin localización, cuerpo, asistencia | eventos x/y (+360) |
| xT, VAEP, OBV, EPV | sin acciones con coordenadas; EPV sin tracking | eventos x/y; tracking |
| Fases tácticas (T-GAN, FeatGRU) | sin secuencias de posesión | tracking + eventos + etiquetas |
| GNN de cualquier tipo | sin posiciones ni interacciones | tracking o freeze frames |
| Transformers de secuencia | ~10–20 eventos por partido; ningún problema definido que lo requiera | eventos x/y de muchas temporadas |
| Contrafactuales / RL | resultado contrafactual inobservable; sin tracking | tracking + eventos |
| Pressing, compacidad, pitch control | sin posiciones | tracking a 25 Hz |
| GBM / ensemble | 3 temporadas por competición; la literatura espera ganancia modesta | backfill de 5+ temporadas (planificado) |
| Timing de steam moves | sin historia tick a tick | proveedor de cuotas con ticks |
| Feature de "efecto entrenador" | la evidencia causal dice que no existe | — |
| Probabilidades generadas por IA | prohibido: la IA explica, los modelos cuantifican | — |

---

## Bibliografía

Referencias verificadas, deduplicadas, en orden alfabético (248). Las notas completas por área,
con las tablas de técnicas y el detalle de verificación de cada fuente, están en
`docs/research/notes/` (A1 xG, balón parado, defensa y jugadores · A2 posesión, fases, tracking,
grafos y secuencias · A3 fuerza, predicción, incertidumbre y causalidad · A4 mercado de apuestas ·
A5 inventario oficial de API-Football).


- Abadie, A. (2021). Using synthetic controls: feasibility, data requirements, and methodological aspects. Journal of Economic Literature 59(2), 391–425. https://doi.org/10.1257/jel.20191450
- Adjileye, A. A. (2024). RisingBALLER: A player is a token, a match is a sentence. A path towards a foundational model for football players data analytics. StatsBomb Conference 2024; arXiv:2410.00943. https://arxiv.org/abs/2410.00943
- Andorra, A., & Göbel, M. (2024). Unveiling true talent: The Soccer Factor Model for skill evaluation. arXiv:2412.05911. https://arxiv.org/abs/2412.05911
- Andrienko, G., Andrienko, N., Budziak, G., Dykes, J., Fuchs, G., von Landesberger, T., & Weber, H. (2017). Visual analysis of pressure in football. Data Mining and Knowledge Discovery, 31(6), 1793–1839. https://doi.org/10.1007/s10618-017-0513-2
- Angelini, G., & De Angelis, L. (2019). Efficiency of online football betting markets. International Journal of Forecasting 35(2), 712–721. https://doi.org/10.1016/j.ijforecast.2018.07.008
- Angelopoulos, A.N., Bates, S. (2021). A gentle introduction to conformal prediction and distribution-free uncertainty quantification. arXiv:2107.07511. https://arxiv.org/abs/2107.07511
- Anzer, G., & Bauer, P. (2021). A goal scoring probability model for shots based on synchronized positional and event data in football (soccer). Frontiers in Sports and Active Living, 3, 624475. https://doi.org/10.3389/fspor.2021.624475
- Anzer, G., Bauer, P. (2022). Expected passes. Data Mining and Knowledge Discovery 36. https://doi.org/10.1007/s10618-021-00810-3
- API-SPORTS (2026). How to get started with API-Football: the complete beginner's guide. API-Football blog, 13 Mar 2026. https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
- Arbués-Sangüesa, A. et al. (2020). Using Player's Body-Orientation to Model Pass Feasibility in Soccer. CVPR Workshops. https://arxiv.org/abs/2004.07209
- Arntzen, H., & Hvattum, L. M. (2021). Predicting match outcomes in association football using team ratings and player ratings. Statistical Modelling, 21(5), 449–470. https://doi.org/10.1177/1471082X20929881
- Ayana, G., Ehlert, A., Ehlert, J., Santagata, L., Torricelli, M., & Klein, B. (2025). Temporal dynamics of goal scoring in soccer. arXiv:2501.18606. https://arxiv.org/abs/2501.18606
- Baboota, R., Kaur, H. (2019). Predictive analysis and modelling football results using machine learning approach for English Premier League. IJF 35(2), 741–755. https://doi.org/10.1016/j.ijforecast.2018.01.003
- Bailey, D. H., Borwein, J. M., López de Prado, M., & Zhu, Q. J. (2016). The probability of backtest overfitting. Journal of Computational Finance 20(4), 39–69. https://doi.org/10.21314/JCF.2016.322
- Bajons, R., & Harringer, T. (2025). One xG model to rule them all? Challenging the most accurate xG model. Hudl Performance Insights 2025. https://static.hudl.com/craft/performance-insights-research-stage/2025/One-xG-model-to-rule-them-all_-Robert-Bajons-Tobias-Harringer.pdf
- Bajons, R., & Hornik, K. (2024). Regularized adjusted plus-minus models for evaluating and scouting football (soccer) players using possession sequences. arXiv:2407.17832. https://arxiv.org/abs/2407.17832
- Bajons, R., & Kook, L. (2025). Rethinking player evaluation in sports: Goals above expectation and beyond. arXiv:2509.20083. https://arxiv.org/abs/2509.20083
- Baker, R. D., & McHale, I. G. (2013). Optimal betting under parameter uncertainty: Improving the Kelly criterion. Decision Analysis 10(3), 189–199. https://doi.org/10.1287/deca.2013.0271
- Bandara, I., Shelyag, S., Rajasegarar, S., Dwyer, D., Kim, E.-J., & Angelova, M. (2024). Predicting goal probabilities with improved xG models using event sequences in association football. PLOS ONE, 19(10), e0312278. https://doi.org/10.1371/journal.pone.0312278
- Baron, E., Sandholtz, N., Pleuler, D., & Chan, T. C. Y. (2024). Miss it like Messi: Extracting value from off-target shots in soccer. JQAS, 20(1), 37–50. https://doi.org/10.1515/jqas-2022-0107
- Bassek, M. et al. (2025). An integrated dataset of spatiotemporal and event data in elite soccer. Scientific Data 12:195. https://doi.org/10.1038/s41597-025-04505-y
- Bauer, P., & Anzer, G. (2021). Data-driven detection of counterpressing in professional football. Data Mining and Knowledge Discovery, 35(5), 2009–2049. https://doi.org/10.1007/s10618-021-00763-7
- Bauer, P., Anzer, G., & Smith, J. W. (2022). Individual role classification for players defending corners in football (soccer). JQAS, 18(2), 147–160. https://doi.org/10.1515/jqas-2022-0003
- Bauer, P., Anzer, G., Shaw, L. (2023). Putting team formations in association football into context. Journal of Sports Analytics 9. https://doi.org/10.3233/JSA-220620
- Bekkers, J. (2025). Pressing intensity: An intuitive measure for pressing in soccer. arXiv:2501.04712. https://arxiv.org/abs/2501.04712
- Bekkers, J., Sahasrabudhe, A. (2024). A Graph Neural Network deep-dive into successful counterattacks. arXiv (MIT SSAC 2023). https://arxiv.org/abs/2411.17450
- Benz, L.S., Lopez, M.J. (2023). Estimating the change in soccer's home advantage during the Covid-19 pandemic using bivariate Poisson regression. AStA Advances in Statistical Analysis 107, 205–232. https://doi.org/10.1007/s10182-021-00413-9
- Berrar, D., Lopes, P., Davis, J., Dubitzky, W. (2019a). Guest editorial: special issue on machine learning for soccer. Machine Learning 108, 1–7. https://doi.org/10.1007/s10994-018-5763-8
- Berrar, D., Lopes, P., Dubitzky, W. (2019b). Incorporating domain knowledge in machine learning for soccer outcome prediction. Machine Learning 108, 97–126. https://doi.org/10.1007/s10994-018-5747-8
- Berrar, D., Lopes, P., Dubitzky, W. (2024). A data- and knowledge-driven framework for developing machine learning models to predict soccer match outcomes. Machine Learning 113, 8165–8204. https://doi.org/10.1007/s10994-024-06625-9
- Betfair (n.d.). Exchange: What is the Market Base Rate? Betfair Support. https://support.betfair.com/app/answers/detail/412-exchange-what-is-the-market-base-rate/
- Biermann, H. et al. (2025). Contextualization of soccer analysis with tactical periodization and machine learning. Data Mining and Knowledge Discovery 39. https://doi.org/10.1007/s10618-025-01092-9
- Bilalić, M., Gula, B., Vaci, N. (2021). Home advantage mediated (HAM) by referee bias and team performance during covid. Scientific Reports 11, 21558. https://doi.org/10.1038/s41598-021-00784-8
- Brandes, U. et al. (2025). Shape graphs and the instantaneous inference of tactical positions in soccer. npj Complexity 2:25. https://doi.org/10.1038/s44260-025-00047-x
- Bransen, L., Janssen, T., & Davis, J. (2025). Stop guessing: Optimizing goalkeeper policies for soccer penalty kicks. arXiv:2505.24629. https://arxiv.org/abs/2505.24629
- Brechot, M., Flepp, R. (2020). Dealing with randomness in match outcomes: how to rethink performance evaluation in European club football using expected goals. Journal of Sports Economics 21(4), 335–362. https://doi.org/10.1177/1527002519897962
- Bryson, A., Dolton, P., Reade, J.J., Schreyer, D., Singleton, C. (2021). Causal effects of an absent crowd on performances and refereeing decisions during Covid-19. Economics Letters 198, 109664. https://doi.org/10.1016/j.econlet.2020.109664
- Buldú, J. M. et al. (2018). Using Network Science to Analyse Football Passing Networks: Dynamics, Space, Time, and the Multilayer Nature of the Game. Frontiers in Psychology 9:1900. https://doi.org/10.3389/fpsyg.2018.01900
- Bunker, R., Yeung, C., Fujii, K. (2024). Machine learning for soccer match result prediction (book chapter). arXiv:2403.07669. https://arxiv.org/abs/2403.07669
- Cain, M., Law, D., & Peel, D. A. (2000). The favourite-longshot bias and market efficiency in UK football betting. Scottish Journal of Political Economy 47(1), 25–36. https://doi.org/10.1111/1467-9485.00151
- Caliendo, M., Radic, D. (2006). Ten do it better, do they? An empirical analysis of an old football myth. IZA DP 2158. https://ideas.repec.org/p/iza/izadps/dp2158.html
- Capellera, G. et al. (2024). TranSPORTmer: A Holistic Approach to Trajectory Understanding in Multi-Agent Sports. ACCV. https://arxiv.org/abs/2410.17785
- Casal, C. A., Armatas, V., Losada, J. L., & Mitrotasios, M. (2023). Effects of tactical dimension and situational variables in throw-ins on the offensive performance in football. PLOS ONE, 18(11), e0294317. https://doi.org/10.1371/journal.pone.0294317
- Cerqueira, V., Torgo, L., Mozetič, I. (2020). Evaluating time series forecasting models: an empirical study on performance estimation methods. Machine Learning 109, 1997–2028. https://arxiv.org/abs/1905.11744
- Clarke, S., Kovalchik, S., & Ingram, M. (2017). Adjusting bookmaker's odds to allow for overround. American Journal of Sports Science 5(6), 45–49. https://doi.org/10.11648/j.ajss.20170506.12
- Constantinou, A. C., & Fenton, N. E. (2012). Solving the problem of inadequate scoring rules for assessing probabilistic football forecast models. Journal of Quantitative Analysis in Sports 8(1). https://doi.org/10.1515/1559-0410.1418
- Constantinou, A.C. (2019). Dolores: a model that predicts football match outcomes from all over the world. Machine Learning 108, 49–75. https://doi.org/10.1007/s10994-018-5703-7
- Constantinou, A.C., Fenton, N.E. (2013). Determining the level of ability of football teams by dynamic ratings based on the relative discrepancies in scores between adversaries. JQAS 9(1), 37–50. https://doi.org/10.1515/jqas-2012-0036
- Croxson, K., & Reade, J. J. (2014). Information and efficiency: Goal arrival in soccer betting. Economic Journal 124(575), 62–91. https://ideas.repec.org/a/wly/econjl/v124y2014i575p62-91.html
- da Silva, M. F. et al. (2025). The interplay between pitch control and top speed in soccer considering the stamina factor. Scientific Reports 15:38799. https://doi.org/10.1038/s41598-025-22778-6
- Davis, J., & Robberechts, P. (2024). Biases in expected goals models confound finishing ability. arXiv:2401.09940. https://arxiv.org/abs/2401.09940
- Davis, J., Bransen, L., Devos, L., Jaspers, A., Meert, W., Robberechts, P., Van Haaren, J., & Van Roy, M. (2024). Methodology and evaluation in sports analytics: challenges, approaches, and lessons learned. Machine Learning, 113(9), 6977–7010. https://doi.org/10.1007/s10994-024-06585-0
- Davis, J., Robberechts, P., & Van Haaren, J. (2025). Expected goals and the Monte Carlo trap. KU Leuven DTAI Sports Analytics Lab. https://dtai.cs.kuleuven.be/sports/blog/expected-goals-and-the-monte-carlo-trap/
- Davis, J., Robberechts, P., & Van Roy, M. (2025). How do we know a metric is good? A case study on VAEP. KU Leuven DTAI Sports Analytics Lab. https://dtai.cs.kuleuven.be/sports/blog/how-do-we-know-a-metric-is-good-a-case-study-on-vaep/
- Decroos, T., & Davis, J. (2020). Player vectors: Characterizing soccer players' playing style from match event streams. ECML PKDD 2019, LNCS, 569–584. https://doi.org/10.1007/978-3-030-46133-1_34
- Decroos, T., Bransen, L., Van Haaren, J., & Davis, J. (2019). Actions speak louder than goals: Valuing player actions in soccer. KDD '19, 1851–1861. https://doi.org/10.1145/3292500.3330758
- Dendir, S. (2016). When do soccer players peak? A note. Journal of Sports Analytics, 2(2), 89–105. https://doi.org/10.3233/JSA-160021
- Diebold, F. X., & Mariano, R. S. (1995). Comparing predictive accuracy. Journal of Business & Economic Statistics 13(3), 253–263. https://ideas.repec.org/a/bes/jnlbes/v13y1995i3p253-63.html
- Diebold, F.X. (2015). Comparing predictive accuracy, twenty years later: a personal perspective on the use and abuse of Diebold–Mariano tests. JBES 33(1). https://doi.org/10.1080/07350015.2014.983236
- Dimitriadis, T., Gneiting, T., Jordan, A.I. (2021). Stable reliability diagrams for probabilistic classifiers. PNAS 118, e2016191118. https://doi.org/10.1073/pnas.2016191118
- Dixon, M.J., Coles, S.G. (1997). Modelling association football scores and inefficiencies in the football betting market. JRSS C 46(2), 265–280. https://doi.org/10.1111/1467-9876.00065
- Egidi, L., Pauli, F., Torelli, N. (2018). Combining historical data and bookmakers' odds in modelling football scores. Statistical Modelling 18(5–6), 436–459. https://doi.org/10.1177/1471082X18798414
- Egidi, L., Torelli, N. (2021). Comparing goal-based and result-based approaches in modelling football outcomes. Social Indicators Research 156, 801–813. https://doi.org/10.1007/s11205-020-02293-z
- Fassmeyer, D. et al. (2021). Toward Automatically Labeling Situations in Soccer. Frontiers in Sports and Active Living 3. https://doi.org/10.3389/fspor.2021.725431
- Fernández, J., Bornn, L. (2018). Wide Open Spaces: A statistical technique for measuring space creation in professional soccer. MIT SSAC. https://www.sloansportsconference.com/research-papers/wide-open-spaces-a-statistical-technique-for-measuring-space-creation-in-professional-soccer
- Fernández, J., Bornn, L., & Cervone, D. (2021). A framework for the fine-grained evaluation of the instantaneous expected value of soccer possessions. Machine Learning, 110(6), 1389–1427. https://doi.org/10.1007/s10994-021-05989-6
- Fischer, K., Haucap, J. (2021). Does crowd support drive the home advantage in professional football? Evidence from German ghost games during the COVID-19 pandemic. Journal of Sports Economics 22(8), 982–1008. https://doi.org/10.1177/15270025211026552
- Fischer, K., Haucap, J. (2022). Home advantage in professional soccer and betting market efficiency: the role of spectator crowds. Kyklos 75(2), 294–316. https://doi.org/10.1111/kykl.12291
- Flepp, R., Nüesch, S., & Franck, E. (2017). The liquidity advantage of the quote-driven market: Evidence from the betting industry. Quarterly Review of Economics and Finance 64, 306–317. https://doi.org/10.1016/j.qref.2016.07.016
- Football-Data.co.uk (n.d.). Notes for football data; Data files page. https://www.football-data.co.uk/notes.txt ; https://www.football-data.co.uk/data.php
- Forcher, L. et al. (2025b). AI in Bundesliga match analysis—EPV vs. xG to predict match outcomes. Frontiers in Sports and Active Living 7. https://doi.org/10.3389/fspor.2025.1713852
- Forcher, L., Forcher, L., Altmann, S., & Woll, A. (2025). The strategy tradeoff between risk and reward in soccer: Expected ball gain and expected possession value in Bundesliga. International Journal of Sports Science & Coaching (online first). https://doi.org/10.1177/17479541251389831
- Forcher, L., Forcher, L., Altmann, S., Jekauc, D., & Kempe, M. (2024a). The keys of pressing to gain the ball: Characteristics of defensive pressure in elite soccer using tracking data. Science and Medicine in Football, 8(2), 161–169. https://doi.org/10.1080/24733938.2022.2158213
- Forcher, L., Forcher, L., Altmann, S., Jekauc, D., & Kempe, M. (2024b). Is a compact organization important for defensive success in elite soccer? Analysis based on player tracking data. International Journal of Sports Science & Coaching, 19(2), 757–768. https://doi.org/10.1177/17479541231172695
- Forrest, D., Goddard, J., & Simmons, R. (2005). Odds-setters as forecasters: The case of English football. International Journal of Forecasting 21(3), 551–564. https://doi.org/10.1016/j.ijforecast.2005.03.003
- Franck, E., Verbeek, E., & Nüesch, S. (2010). Prediction accuracy of different market structures — bookmakers versus a betting exchange. International Journal of Forecasting 26(3), 448–459. https://doi.org/10.1016/j.ijforecast.2010.01.004
- Gallagher, J., Dinsdale, D., Murali, A., Mackay, N., Foroni, D., & Lucey, P. (2026). Addressing last mile issues in sports analytics: A case study in expected goals in soccer. Sports Analytics (ISACE 2026), LNCS 16610, 475–483. https://doi.org/10.1007/978-3-032-27272-0_30
- Gauriot, R., Page, L. (2019). Fooled by performance randomness: overrewarding luck. Review of Economics and Statistics 101(4), 658–666. https://doi.org/10.1162/rest_a_00783
- Geifman, Y., El-Yaniv, R. (2017). Selective classification for deep neural networks. NeurIPS 30. https://papers.nips.cc/paper/7073-selective-classification-for-deep-neural-networks
- Giacomini, R., White, H. (2006). Tests of conditional predictive ability. Econometrica 74(6), 1545–1578. https://doi.org/10.1111/j.1468-0262.2006.00718.x
- Glickman, M.E. (1999). Parameter estimation in large dynamic paired comparison experiments. JRSS C 48(3), 377–394. https://doi.org/10.1111/1467-9876.00159
- Glickman, M.E. (2001). Dynamic paired comparison models with stochastic variances. Journal of Applied Statistics 28(6), 673–689. https://www.glicko.net/research/dpcmsv.pdf
- Gneiting, T., & Raftery, A. E. (2007). Strictly proper scoring rules, prediction, and estimation. Journal of the American Statistical Association 102, 359–378. https://ideas.repec.org/a/bes/jnlasa/v102y2007p359-378.html
- Goodman, M. (2018). A new way to measure keepers' shot stopping: Post-shot expected goals. StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/a-new-way-to-measure-keepers-shot-stopping-post-shot-expected-goals/
- Goto, K., Takeishi, N., & Yairi, T. (2026). Forecast sports outcomes under efficient market hypothesis: Theoretical and experimental analysis of odds-only and generalised linear models. arXiv:2604.17194. https://arxiv.org/abs/2604.17194
- Grant, A., Oikonomidis, A., Bruce, A. C., & Johnson, J. E. V. (2018). New entry, strategic diversity and efficiency in soccer betting markets: the creation and suppression of arbitrage opportunities. European Journal of Finance 24(18), 1799–1816. https://doi.org/10.1080/1351847X.2018.1443148
- Greenhalgh, S., Anghel, D., Kutibashvili, S., Arsénio, H., & Pascual, R. (2025). Defending the long throw: A dual-model framework for minimising defensive risk. Hudl Performance Insights 2025. https://static.hudl.com/craft/performance-insights-research-stage/2025/Defending-the-Long-Throw_-A-Dual-Model-Framework-for-Minimising-Defensive-Risk-Sebastian-Greenhalgh-Dan-Anghel.pdf
- Groll, A., Ley, C., Schauberger, G., Van Eetvelde, H. (2019). A hybrid random forest to predict soccer matches in international tournaments. JQAS 15(4), 271–287. https://doi.org/10.1515/jqas-2018-0060
- Groom, S., Groom, M., Belo, F., Rice, A., Anderson, L., Darvariu, V.-A., & Wang, S. (2026). Maximising the set-piece return: Optimising football corner tactics with graph reinforcement learning. arXiv:2606.06353. https://arxiv.org/abs/2606.06353
- Guo, C., Pleiss, G., Sun, Y., Weinberger, K.Q. (2017). On calibration of modern neural networks. ICML, PMLR 70, 1321–1330. https://proceedings.mlr.press/v70/guo17a.html
- Hansen, P. R. (2005). A test for superior predictive ability. Journal of Business & Economic Statistics 23(4), 365–380. https://ideas.repec.org/a/bes/jnlbes/v23y2005p365-380.html
- Hansen, P.R., Lunde, A., Nason, J.M. (2011). The model confidence set. Econometrica 79(2), 453–497. https://doi.org/10.3982/ECTA5771
- Harvey, D., Leybourne, S., Newbold, P. (1997). Testing the equality of prediction mean squared errors. IJF 13(2), 281–291. https://doi.org/10.1016/S0169-2070(96)00719-4
- Hegarty, T., & Whelan, K. (2023). The wisdom of no crowds: The reaction of betting markets to lockdown soccer games. Journal of Prediction Markets. https://ubplj.org/index.php/jpm/article/view/2089
- Hegarty, T., & Whelan, K. (2025a). Forecasting soccer matches with betting odds: A tale of two markets. International Journal of Forecasting 41(2), 803–820. https://doi.org/10.1016/j.ijforecast.2024.06.013
- Hegarty, T., & Whelan, K. (2025b). Estimating expected loss rates in betting markets: Theory and evidence. Applied Economics (online). https://doi.org/10.1080/00036846.2025.2507979
- Hegarty, T., & Whelan, K. (2026). Market structure and prices in online betting markets: theory and evidence. Oxford Economic Papers 78(1), 90–113. https://doi.org/10.1093/oep/gpaf023
- Hernán, M.A., Hsu, J., Healy, B. (2019). Data science is science's second chance to get causal inference right: a classification of data science tasks. CHANCE 32(1), 42–49. https://doi.org/10.1080/09332480.2019.1579578
- Heuer, A., Müller, C., Rubner, O., Hagemann, N., Strauss, B. (2011). Usefulness of dismissing and changing the coach in professional soccer. PLOS ONE 6(3), e17664. https://doi.org/10.1371/journal.pone.0017664
- Hirnschall, D., Bajons, R. (2025). The path to a goal: Understanding soccer possessions via path signatures. arXiv. https://arxiv.org/abs/2508.12930
- Hirotsu, N., Wright, M. (2002). Using a Markov process model of an association football match to determine the optimal timing of substitution and tactical decisions. JORS 53. https://doi.org/10.1057/palgrave/jors/2601254
- Holmes, B., & McHale, I. G. (2024). Forecasting football match results using a player rating based model. International Journal of Forecasting 40(1), 302–312. https://doi.org/10.1016/j.ijforecast.2023.03.002
- Hong, M. et al. (2026). Modeling Matches as Language: A Generative Transformer Approach for Counterfactual Player Valuation in Football. ECML-PKDD (accepted). https://arxiv.org/abs/2603.15212
- Hong, M., Lee, M., Jo, G., So, J.-H., Bauer, P., & Ko, S.-K. (2025). EventGPT: Capturing player impact from team action sequences using GPT-based framework. arXiv:2512.17266 (Hudl Performance Insights 2025). https://arxiv.org/abs/2512.17266
- Horton, M., Lucey, P. (2025). Large-Scale In-Game Outcome Forecasting for Match, Team and Players in Football using an Axial Transformer Neural Network. arXiv. https://arxiv.org/abs/2511.18730
- Hubáček, O., Šourek, G., Železný, F. (2019a). Learning to predict soccer results from relational data with gradient boosted trees. Machine Learning 108, 29–47. https://doi.org/10.1007/s10994-018-5704-6
- Hubáček, O., Šourek, G., Železný, F. (2019b). Exploiting sports-betting market using machine learning. IJF 35(2), 783–796. https://doi.org/10.1016/j.ijforecast.2019.01.001
- Hudl StatsBomb (2025). On-Ball Value (OBV): Valuing player actions in football. https://www.hudl.com/blog/statsbomb-on-ball-value
- Hvattum, L. M. (2019). A comprehensive review of plus-minus ratings for evaluating individual players in team sports. International Journal of Computer Science in Sport, 18(1), 1–23. https://doi.org/10.2478/ijcss-2019-0001
- Hvattum, L. M., & Arntzen, H. (2010). Using ELO ratings for match result prediction in association football. International Journal of Forecasting, 26(3), 460–470. https://doi.org/10.1016/j.ijforecast.2009.10.002
- Hvattum, L. M., & Gelade, G. A. (2021). Comparing bottom-up and top-down ratings for individual soccer players. International Journal of Computer Science in Sport, 20(1), 23–42. https://doi.org/10.2478/ijcss-2021-0002
- Hüllermeier, E., Waegeman, W. (2021). Aleatoric and epistemic uncertainty in machine learning: an introduction to concepts and methods. Machine Learning 110, 457–506. https://doi.org/10.1007/s10994-021-05946-3
- Iapteff, L., Le Coz, S., Rioland, M., Houde, T., Carling, C., & Imbach, F. (2025). Toward interpretable expected goals modeling using Bayesian mixed models. Frontiers in Sports and Active Living, 7, 1504362. https://doi.org/10.3389/fspor.2025.1504362
- Isaacs, R. L., Hu, X. J., Peng, K. K., & Swartz, T. (2026). Learning about corner kicks in soccer by analysis of event times using a frailty model. arXiv:2602.22684 (also Sports Analytics, ISACE 2026, LNCS 16610). https://arxiv.org/abs/2602.22684
- Kapoor, S., Narayanan, A. (2023). Leakage and the reproducibility crisis in machine-learning-based science. Patterns 4, 100804 (preprint arXiv:2207.07048). https://arxiv.org/abs/2207.07048
- Karakuş, O., Arkadaş, H. (2026). Structural Pass Analysis in Football: Learning Pass Archetypes and Tactical Impact from Spatio-Temporal Tracking Data. arXiv. https://arxiv.org/abs/2603.28916
- Karimov, A., Koshkin, A., Kaplun, D., & Butusov, D. (2025). Domain-driven identification of football probabilities. Mathematics 13(24), 3976. https://doi.org/10.3390/math13243976
- Karlis, D., Ntzoufras, I. (2003). Analysis of sports data by using bivariate Poisson models. JRSS D 52(3), 381–393. https://doi.org/10.1111/1467-9884.00366
- Karlis, D., Ntzoufras, I. (2009). Bayesian modelling of football outcomes: using the Skellam's distribution for the goal difference. IMA J. Management Mathematics 20(2), 133–145. https://doi.org/10.1093/imaman/dpn026
- Kaunitz, L., Zhong, S., & Kreiner, J. (2017). Beating the bookies with their own numbers — and how the online sports betting market is rigged. arXiv:1710.02824. https://arxiv.org/abs/1710.02824
- Kelly, J. L. (1956). A new interpretation of information rate. Bell System Technical Journal 35(4), 917–926. https://archive.org/details/bstj35-4-917
- Kharrat, T., McHale, I. G., & Peña, J. L. (2020). Plus–minus player ratings for soccer. European Journal of Operational Research, 283(2), 726–736. https://doi.org/10.1016/j.ejor.2019.11.026
- Knutson, T. (2014). More discussion about possession adjusted defensive stats. StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/more-discussion-about-possession-adjusted-defensive-stats/
- Koopman, S.J., Lit, R. (2015). A dynamic bivariate Poisson model for analysing and forecasting match results in the English Premier League. JRSS A 178(1), 167–186. https://doi.org/10.1111/rssa.12042
- Koopman, S.J., Lit, R. (2019). Forecasting football match results in national league competitions using score-driven time series models. IJF 35(2), 797–809. https://doi.org/10.1016/j.ijforecast.2018.10.011
- Kumar, A., Liang, P., Ma, T. (2019). Verified uncertainty calibration. NeurIPS 2019. https://arxiv.org/abs/1909.10155
- Künsch, H.R. (1989). The jackknife and the bootstrap for general stationary observations. Annals of Statistics 17(3), 1217–1241. https://doi.org/10.1214/aos/1176347265
- Lakshminarayanan, B., Pritzel, A., Blundell, C. (2017). Simple and scalable predictive uncertainty estimation using deep ensembles. NeurIPS 2017. https://arxiv.org/abs/1612.01474
- Lasek, J., Szlávik, Z., Bhulai, S. (2013). The predictive power of ranking systems in association football. Int. J. Applied Pattern Recognition 1(1), 27–46. https://doi.org/10.1504/IJAPR.2013.052339
- Le Coz, S., Boustila, F., Imbach, F. (2026). A Semi-Markov framework for modeling football possessions and temporal expected threat. Scientific Reports 16:22590. https://doi.org/10.1038/s41598-026-52938-1
- Lee, C.H., Mohamad, A.H., Asirvatham, D. (2026). Data-driven football performance measurement: a measure-first systematic review of action-centric, individual, team, and financial analytics (2018–2024). Preprints.org (not peer-reviewed; on Sciety). https://doi.org/10.20944/preprints202607.0281.v1
- Lee, M., Jo, G., Hong, M., Bauer, P., & Ko, S.-K. (2026). Contextual evaluation of individual contributions from pressing situations in football. MLSA 2025, CCIS 2833, 35–47. https://doi.org/10.1007/978-3-032-15165-0_3
- Leitner, C., Zeileis, A., Hornik, K. (2010). Forecasting sports tournaments by ratings of (prob)abilities: a comparison for the EURO 2008. IJF 26(3), 471–481. https://ideas.repec.org/a/eee/intfor/v26yi3p471-481.html
- Lepschy, H., Wäsche, H., Woll, A. (2018). How to be successful in football: a systematic review. Open Sports Sciences Journal 11, 3–23. https://doi.org/10.2174/1875399X01811010003
- Ley, C., Van de Wiele, T., Van Eetvelde, H. (2019). Ranking soccer teams on the basis of their current strength: a comparison of maximum likelihood approaches. Statistical Modelling 19(1), 55–73. https://doi.org/10.1177/1471082X18817650
- Li, Y., Link, D. (2026). Intention Driven Identification of In-Possession Match Phases in Association Football through Temporal Graph Learning. arXiv. https://arxiv.org/abs/2606.09289
- Lin, J., Chen, F., Liu, J. (2026). A graph-integrated reinforcement learning framework with graph neural networks for tactical decision modeling in professional football. Scientific Reports 16:26974. https://doi.org/10.1038/s41598-026-50061-9
- Lindstrøm, J. C. (2023). implied: Convert between bookmaker odds and probabilities (R package 0.5). CRAN. https://cran.r-project.org/web/packages/implied/vignettes/introduction.html
- Lopez, M.J., Matthews, G.J., Baumer, B.S. (2017). How often does the best team win? A unified approach to understanding randomness in North American sport. arXiv:1701.05976. https://arxiv.org/abs/1701.05976
- Low, B., Coutinho, D., Gonçalves, B., Rein, R., Memmert, D., & Sampaio, J. (2020). A systematic review of collective tactical behaviours in football using positional data. Sports Medicine, 50(2), 343–385. https://doi.org/10.1007/s40279-019-01194-7
- MacLean, L. C., Thorp, E. O., & Ziemba, W. T. (2010). Long-term capital growth: the good and bad properties of the Kelly and fractional Kelly capital growth criteria. Quantitative Finance 10(7), 681–687. https://doi.org/10.1080/14697688.2010.506108
- Macrì-Demartino, R., Egidi, L., Torelli, N. (2025). Bayesian weighted discrete-time dynamic models for association football prediction. arXiv:2508.05891. https://arxiv.org/abs/2508.05891
- Maher, M.J. (1982). Modelling association football scores. Statistica Neerlandica 36(3), 109–118. https://doi.org/10.1111/j.1467-9574.1982.tb00782.x
- Mahmudlu, M., Karakuş, O., Arkadaş, H. (2025). What If They Took the Shot? A Hierarchical Bayesian Framework for Counterfactual Expected Goals. arXiv. https://arxiv.org/abs/2511.23072
- Masella, G. et al. (2026). Evaluating passing decision-making in professional football: An enhanced MPNN approach to Receiver Selection. arXiv. https://arxiv.org/abs/2605.25696
- May, E. (2023). Game Intelligence: Off-Ball Run Types. SkillCorner. https://skillcorner.com/articles/game-intelligence-off-ball-run-types
- McIntosh, R., & Beckmann, T. (2025). Modelling player performance after potential transfers between leagues. Hudl Performance Insights 2025. https://static.hudl.com/craft/performance-insights-research-stage/2025/Modelling-player-performance-after-potential-transfers-between-leagues-Richard-McIntosh-Tobias-Beckmann.docx.pdf
- Mead, J., O'Hare, A., & McMenemy, P. (2023). Expected goals in football: Improving model performance and demonstrating value. PLOS ONE, 18(4), e0282295. https://doi.org/10.1371/journal.pone.0282295
- Mechtel, M., Bäker, A., Brändle, T., Vetter, K. (2011). Red cards: not such bad news for penalized guest teams. Journal of Sports Economics 12(6), 621–646. https://doi.org/10.1177/1527002510388478
- Meier, P. F., Flepp, R., & Franck, E. (2021). Are sports betting markets semi-strong efficient? Evidence from the COVID-19 pandemic. International Journal of Sport Finance 16(3), 111–126. https://doi.org/10.32731/IJSF.163.082021.01
- Mendes-Neves, T., Meireles, L., & Mendes-Moreira, J. (2024a). Estimating player performance in different contexts using fine-tuned large events models. arXiv:2402.06815. https://arxiv.org/abs/2402.06815
- Mendes-Neves, T., Meireles, L., & Mendes-Moreira, J. (2024b). Towards a foundation large events model for soccer. Machine Learning, 113(11–12), 8687–8709. https://doi.org/10.1007/s10994-024-06606-y
- Merhej, C., Beal, R., Matthews, T., & Ramchurn, S. (2021). What happened next? Using deep learning to value defensive actions in football event-data. KDD '21. https://doi.org/10.1145/3447548.3467090
- Monte, J. (2024). Measuring throw-in success. Hudl StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/measuring-throw-in-success/
- Moskowitz, T. J. (2021). Asset pricing and sports betting. Journal of Finance 76(6), 3153–3209. https://doi.org/10.1111/jofi.13082
- Nakahara, H. et al. (2023). Action valuation of on- and off-ball soccer players based on multi-agent deep reinforcement learning. IEEE Access. https://doi.org/10.1109/ACCESS.2023.3336425
- Narizuka, T. et al. (2026). Quantifying defensive pressure on the ball carrier in soccer based on minimum arrival time. arXiv. https://arxiv.org/abs/2606.09452
- Newall, P. W. S., & Cortis, D. (2021). Are sports bettors biased toward longshots, favorites, or both? A literature review. Risks 9(1), 22. https://doi.org/10.3390/risks9010022
- Nguyen, B.V., Tran, N.A. (2026). An adaptive Glicko-2 rating framework for probabilistic football forecasting and season simulation. arXiv:2607.01722. https://arxiv.org/abs/2607.01722
- Ogawa, Y., Umemoto, R., Fujii, K. (2025). Space evaluation at the starting point of soccer transitions. arXiv. https://arxiv.org/abs/2505.14711
- Opta Analyst (2021). What are expected goals on target (xGOT)? https://theanalyst.com/articles/what-are-expected-goals-on-target-xgot
- Opta Analyst (2023). What is expected goals (xG)? (penalty xG = 0.79). https://theanalyst.com/articles/what-is-expected-goals-xg
- Otero-Saborido, F.M., Aguado-Méndez, R.D., Torreblanca-Martínez, V.M., González-Jurado, J.A. (2021). Technical-tactical performance from data providers: a systematic review in regular football leagues. Sustainability 13(18), 10167. https://doi.org/10.3390/su131810167
- Overmeer, T., Janssen, T., Nuijten, W. (2025). Revisiting Expected Possession Value in Football: Introducing a Benchmark, U-Net Architecture, and Reward and Risk for Passes. arXiv. https://arxiv.org/abs/2502.02565
- Owen, A. (2011). Dynamic Bayesian forecasting models of football match outcomes with estimation of the evolution variance parameter. IMA J. Management Mathematics 22(2), 99–113. https://doi.org/10.1093/imaman/dpq018
- Palacios-Huerta, I. (2003). Professionals play minimax. Review of Economic Studies, 70(2), 395–415. https://doi.org/10.1111/1467-937X.00249
- Pappalardo, L., Cintia, P., Ferragina, P., Massucco, E., Pedreschi, D., & Giannotti, F. (2019). PlayeRank: Data-driven performance evaluation and player ranking in soccer via a machine learning approach. ACM TIST, 10(5). https://doi.org/10.1145/3343172
- Peeters, T. (2018). Testing the Wisdom of Crowds in the field: Transfermarkt valuations and international soccer results. IJF 34(1), 17–29. https://doi.org/10.1016/j.ijforecast.2017.08.002
- Peng, K. K., Hu, X. J., & Swartz, T. B. (2024). On the time of corner kicks in soccer: an analysis of event history data. Computational Statistics, 40(4), 2067–2083 (online 2024). https://doi.org/10.1007/s00180-024-01567-1
- Petretta, M., Schiavon, L., Diquigiovanni, J. (2025). Modelling dependence in football match outcomes: traditional assumptions and an alternative proposal. Statistical Modelling 25(3), 255–269. https://doi.org/10.1177/1471082X241238802
- Pettersson-Lidbom, P., Priks, M. (2010). Behavior under social pressure: empty Italian stadiums and referee bias. Economics Letters 108(2), 212–214. https://ideas.repec.org/a/eee/ecolet/v108y2010i2p212-214.html
- Pipping-Gamón, J., Feng, T., & Sabin, R. P. (2025). Beyond expected goals: A probabilistic framework for shot occurrences in soccer. arXiv:2512.00203. https://arxiv.org/abs/2512.00203
- Plakias, S., Armatas, V., & Giakas, G. (2025). Technical–tactical analysis of corner kicks in male soccer: A systematic review. Applied Sciences, 15(9), 4984. https://doi.org/10.3390/app15094984
- Politis, D. N., & Romano, J. P. (1994). The stationary bootstrap. Journal of the American Statistical Association 89(428), 1303–1313. https://doi.org/10.1080/01621459.1994.10476870
- Ponzo, M., Scoppa, V. (2018). Does the home advantage depend on crowd support? Evidence from same-stadium derbies. Journal of Sports Economics 19(4), 562–582. https://doi.org/10.1177/1527002516665794
- Power, P. et al. (2017). "Not All Passes Are Created Equal": Objectively Measuring the Risk and Reward of Passes in Soccer from Tracking Data. KDD. https://doi.org/10.1145/3097983.3098051
- Rahimian, P., Davis, J., Toka, L. (2026). Temporal Graph Network Framework for Quantifying Pass Reception Probabilities Against Defensive Structures. Machine Learning 115. https://doi.org/10.1007/s10994-025-06935-6
- Ranjan, R., Gneiting, T. (2010). Combining probability forecasts. JRSS B 72(1), 71–91. https://doi.org/10.1111/j.1467-9868.2009.00726.x
- Reade, J.J., Schreyer, D., Singleton, C. (2022). Eliminating supportive crowds reduces referee bias. Economic Inquiry 60(3), 1416–1436. https://doi.org/10.1111/ecin.13063
- Rein, R., Raabe, D., Memmert, D. (2017). "Which pass is better?" Novel approaches to assess passing effectiveness in elite soccer. Human Movement Science 55. https://doi.org/10.1016/j.humov.2017.07.010
- Ridder, G., Cramer, J.S., Hopstaken, P. (1994). Down to ten: estimating the effect of a red card in soccer. JASA 89, 1124–1127. https://doi.org/10.1080/01621459.1994.10476850
- Ridge, P. (2024). What's happened to the Premier League's direct free-kick goals? Opta Analyst. https://theanalyst.com/2024/05/whats-happened-to-goals-from-premier-league-free-kicks/
- Robberechts, P., & Davis, J. (2020). How data availability affects the ability to learn good xG models. MLSA 2020, CCIS 1324, 17–27. https://doi.org/10.1007/978-3-030-64912-8_2
- Robberechts, P., Van Haaren, J., & Davis, J. (2021). A Bayesian approach to in-game win probability in soccer. KDD '21, 3512–3521. https://doi.org/10.1145/3447548.3467194
- Robberechts, P., Van Roy, M., Davis, J. (2023). un-xPass: Measuring Soccer Player's Creativity. KDD. https://doi.org/10.1145/3580305.3599924
- Rue, H., Salvesen, Ø. (2000). Prediction and retrospective analysis of soccer matches in a league. JRSS D 49(3), 399–418. https://doi.org/10.1111/1467-9884.00243
- Scholtes, A., & Karakuş, O. (2024). Bayes-xG: Player and position correction on expected goals (xG) using Bayesian hierarchical approach. Frontiers in Sports and Active Living, 6, 1348983. https://doi.org/10.3389/fspor.2024.1348983
- Shaw, L., & Gopaladesikan, S. (2020). Routine inspection: A playbook for corner kicks. MLSA 2020, CCIS 1324, 3–16. https://doi.org/10.1007/978-3-030-64912-8_1
- Shelopugin, A., & Sirotkin, A. (2026). Constructing football club ratings with league strength awareness using a modified Glicko model. Sports Analytics (ISACE 2026), LNCS 16610. https://doi.org/10.1007/978-3-032-27272-0_4
- Shin, H. S. (1991). Optimal betting odds against insider traders. Economic Journal 101(408), 1179–1185. https://ideas.repec.org/a/ecj/econjl/v101y1991i408p1179-85.html
- Shin, H. S. (1993). Measuring the incidence of insider trading in a market for state-contingent claims. Economic Journal 103(420), 1141–1153. https://doi.org/10.2307/2234240
- Shmueli, G. (2010). To explain or to predict? Statistical Science 25(3), 289–310. https://doi.org/10.1214/10-STS330
- Simpson, I. et al. (2022). Seq2Event: Learning the Language of Soccer Using Transformer-based Match Event Prediction. KDD. https://doi.org/10.1145/3534678.3539138
- Singh, K. (2019). Introducing Expected Threat (xT). Blog. https://karun.in/blog/expected-threat.html
- SkillCorner (2025). Phases of Play – CSV Specifications. https://26560301.fs1.hubspotusercontent-eu1.net/hubfs/26560301/Guides/Phases%20of%20Play/20250216%20-%20Phases%20of%20Play%20CSV%20Specifications.pdf
- Skripnikov, A., Cemek, A., & Gillman, D. (2025). Leveraging minute-by-minute soccer match event data to adjust team's offensive production for game context. arXiv:2508.04008 (accepted, JQAS). https://arxiv.org/abs/2508.04008
- Spearman, W. (2018). Beyond Expected Goals. MIT SSAC. (Verified via citing work, e.g. https://arxiv.org/abs/2206.01899)
- Spearman, W. et al. (2017). Physics-Based Modeling of Pass Probabilities in Soccer. MIT SSAC. https://static.hudl.com/craft/downloads/SSAC17-Physics-Based-Modeling-of-Pass-Probabilities-in-Soccer.pdf
- Stats Perform (2025). Enhancing expected goals on target: Deeper insights into shot execution, goalkeeper performance, and a dedicated model for women's football. https://www.statsperform.com/insights/enhancing-expected-goals-on-target/
- Stats Perform (n.d.). How we measure pressure. https://www.statsperform.com/insights/how-we-measure-pressure/
- StatsBomb (2021). Introducing On-Ball Value (OBV). https://statsbomb.com/articles/soccer/introducing-on-ball-value-obv/
- Stone, J. A., Smith, A., & Barry, A. (2021). The undervalued set piece: Analysis of soccer throw-ins during the English Premier League 2018–2019 season. International Journal of Sports Science & Coaching, 16(3), 830–839. https://doi.org/10.1177/1747954121991447
- Säfvenberg, R., Nordgaard, A., Lidmark Eriksson, O., Carlsson, N., & Lambrix, P. (2024). Age of peak performance among soccer players in Sweden. Sports Analytics (ISACE 2024), LNCS, 278–290. https://doi.org/10.1007/978-3-031-69073-0_24
- Tashman, L. J. (2000). Out-of-sample tests of forecasting accuracy: an analysis and review. International Journal of Forecasting 16(4), 437–450. https://ideas.repec.org/a/eee/intfor/v16y2000i4p437-450.html
- Titman, A.C., Costain, D.A., Ridall, P.G., Gregory, K. (2015). Joint modelling of goals and bookings in association football. JRSS A 178(3), 659–683. https://ideas.repec.org/a/bla/jorssa/v178y2015i3p659-683.html
- Toda, K., Teranishi, M., Kushiro, K., & Fujii, K. (2022). Evaluation of soccer team defense based on prediction models of ball recovery and being attacked: A pilot study. PLOS ONE, 17(1), e0263051. https://doi.org/10.1371/journal.pone.0263051
- Trainor, C. (2014). Defensive metrics: Measuring the intensity of a high press. StatsBomb (Hudl blog). https://www.hudl.com/blog/defensive-metrics-measuring-the-intensity-of-a-high-press
- Tsokos, A. et al. (2019). Modeling outcomes of soccer matches. Machine Learning 108, 77–95. https://doi.org/10.1007/s10994-018-5741-1
- Tweedale, A. (2024). Possession and territory, but too few chances created: Tottenham's final-third problems analysed. Opta Analyst. https://theanalyst.com/articles/tottenham-problems-chances-created
- Uhrín, M., Šourek, G., Hubáček, O., & Železný, F. (2021). Optimal sports betting strategies in practice: an experimental review. IMA Journal of Management Mathematics 32(4), 465–489. https://doi.org/10.1093/imaman/dpaa029
- Umemoto, R., & Fujii, K. (2023). Evaluation of team defense positioning by computing counterfactuals using StatsBomb 360 data. StatsBomb Conference 2023. https://blogarchive.statsbomb.com/uploads/2023/10/Evaluation-of-Team-Defense-Positioning-by-Computing-Counterfactuals-Using-StatsBomb-360-Data.pdf
- Uribe, A., Sanders, S., Ehrlich, J., Reade, J. J., & Singleton, C. (2025). Do behavioral considerations cloud penalty-kick location optimization in professional soccer? MIT Sloan Sports Analytics Conference. https://www.sloansportsconference.com/research-papers/do-behavioral-considerations-cloud-penalty-kick-location-optimization-in-professional-soccer-game-theory-empirical-testing-using-polynomial-regression-and-ml-gradient-boosting
- van Arem, K. W., Goes-Smit, F., & Söhl, J. (2025a). Forecasting the future development in quality and value of professional football players. Applied Sciences, 15, 8916. https://doi.org/10.3390/app15168916
- van Arem, K. W., Söhl, J., Bruinsma, M., & Jongbloed, G. (2025b). The trade-off between model flexibility and accuracy of the Expected Threat model in football. MathSport International 2025; arXiv:2511.09457. https://arxiv.org/abs/2511.09457
- van Arem, K., Söhl, J., Bruinsma, M., Jongbloed, G. (2026). Model quality in football: Quantifying the quality of an Expected Threat model. arXiv. https://arxiv.org/abs/2604.21087
- van Ours, J.C., van Tuijl, M.A. (2016). In-season head-coach dismissals and the performance of professional football teams. Economic Inquiry 54(1), 591–604. https://ideas.repec.org/a/bla/ecinqu/v54y2016i1p591-604.html
- Van Roy, M. et al. (2020). Valuing On-the-Ball Actions in Soccer: A Critical Comparison of xT and VAEP. AAAI-20 Workshop on AI in Team Sports. https://tomdecroos.github.io/reports/xt_vs_vaep.pdf
- Van Roy, M. et al. (2021). Leaving Goals on the Pitch: Evaluating Decision Making in Soccer. MIT SSAC. https://arxiv.org/abs/2104.03252
- Van Roy, M. et al. (2023). A Markov Framework for Learning and Reasoning About Strategies in Professional Soccer. JAIR 77. https://doi.org/10.1613/jair.1.13934
- Vatvani, D. (2022). Upgrading expected goals. StatsBomb. https://blogarchive.statsbomb.com/articles/soccer/upgrading-expected-goals/
- Walsh, C., & Joshi, A. (2025). Corrigendum to "Machine learning for sports betting: Should model selection be based on accuracy or calibration?". Machine Learning with Applications 19, 100627. https://doi.org/10.1016/j.mlwa.2025.100627
- Walsh, C., Joshi, A. (2024). Machine learning for sports betting: should model selection be based on accuracy or calibration? Machine Learning with Applications 16, 100539 (corrigendum 2025). https://doi.org/10.1016/j.mlwa.2024.100539
- Wang, L. et al. (2025). Player-Team Heterogeneous Interaction Graph Transformer for Soccer Outcome Prediction. KDD. https://arxiv.org/abs/2507.10626
- Wang, Z., Veličković, P., Hennes, D., Tomašev, N., et al. (2024). TacticAI: an AI assistant for football tactics. Nature Communications, 15, 1906. https://doi.org/10.1038/s41467-024-45965-x
- Wheatcroft, E. (2020). A profitable model for predicting the over/under market in football. International Journal of Forecasting 36(3), 916–932. https://doi.org/10.1016/j.ijforecast.2019.11.001
- Wheatcroft, E. (2021). Evaluating probabilistic forecasts of football matches: the case against the ranked probability score. Journal of Quantitative Analysis in Sports 17(4), 273–287. https://doi.org/10.1515/jqas-2019-0089
- Wheatcroft, E. (2021a). Forecasting football matches by predicting match statistics. Journal of Sports Analytics, 7(2), 77–97. https://doi.org/10.3233/JSA-200462
- Whelan, K. (2025a). How does inside information affect sports betting odds? Scottish Journal of Political Economy. https://doi.org/10.1111/sjpe.70017
- Whelan, K. (2025b). On estimates of insider trading in sports betting. The Manchester School. https://doi.org/10.1111/manc.12505
- Whelan, K. (2025c). On optimal betting strategies with multiple mutually exclusive outcomes. Bulletin of Economic Research 77(1), 67–85. https://doi.org/10.1111/boer.12474
- Whelan, K. (2025d). Ruin probabilities for strategies with asymmetric risk. Working paper, University College Dublin. http://www.karlwhelan.com/Papers/Ruin.pdf
- Whelan, K. (2026). Agreeing to disagree: The economics of betting exchanges. Working paper, University College Dublin (draft 26 Jan 2026). http://www.karlwhelan.com/Papers/Betfair.pdf
- White, H. (2000). A reality check for data snooping. Econometrica 68(5), 1097–1126. https://ideas.repec.org/a/ecm/emetrp/v68y2000i5p1097-1126.html
- Whitmore, J. (2021). Sequences and Possessions in Football. Opta Analyst. https://theanalyst.com/articles/possessions-and-sequences-in-football
- Whitmore, J. (2021). What Is Possession Value (PV)? Opta Analyst. https://theanalyst.com/articles/what-is-possession-value
- Whitmore, J., et al. (2026). Opta Power Rankings explained: How our global football rating system works. Opta Analyst. https://theanalyst.com/articles/power-rankings-your-club-ranked
- Wilkens, S. (2026). Can simple models predict football — and beat the odds? Lessons from the German Bundesliga. Journal of Sports Analytics 12. https://doi.org/10.1177/22150218261416681
- Winkelmann, D., Deutscher, C., Ötting, M. (2021). Bookmakers' mispricing of the disappeared home advantage in the German Bundesliga after the COVID-19 break. Applied Economics 53(26), 3054–3064. https://doi.org/10.1080/00036846.2021.1873234
- Winkelmann, D., Ötting, M., Deutscher, C., & Makarewicz, T. (2024). Are betting markets inefficient? Evidence from simulations and real data. Journal of Sports Economics 25(1), 54–97. https://doi.org/10.1177/15270025231204997
- Wunderlich, F., & Memmert, D. (2020). Are betting returns a useful measure of accuracy in (sports) forecasting? International Journal of Forecasting 36(2), 713–722. https://doi.org/10.1016/j.ijforecast.2019.08.009
- Wunderlich, F., Memmert, D. (2018). The Betting Odds Rating System: using soccer forecasts to forecast soccer. PLOS ONE 13(6), e0198668. https://doi.org/10.1371/journal.pone.0198668
- Wunderlich, F., Weigelt, M., Rein, R., Memmert, D. (2021). How does spectator presence affect football? Home advantage remains in European top-class football matches played without spectators during the COVID-19 pandemic. PLOS ONE 16(3), e0248590. https://doi.org/10.1371/journal.pone.0248590
- Xu, Y., Bretzner, L., Wang, T., & Maki, A. (2025). Skor-xG: SKeleton-ORiented expected goal estimation in soccer. CVPR 2025 Workshops (CVsports). https://openaccess.thecvf.com/content/CVPR2025W/CVSPORTS/papers/Xu_Skor-xG_SKeleton-ORiented_Expected_Goal_Estimation_in_Soccer_CVPRW_2025_paper.pdf
- Yeung, C., Bunker, R., Umemoto, R., Fujii, K. (2024). Evaluating soccer match prediction models: a deep learning approach and feature optimization for gradient-boosted trees. Machine Learning 113(10), 7541–7564. https://doi.org/10.1007/s10994-024-06608-w
- Yip, S., Zou, Y., Hung, R. T. H., & Yiu, K. F. C. (2024). Forecasting number of corner kicks taken in association football using compound Poisson distribution. Journal of the Operational Research Society, 75(11), 2127–2137. https://doi.org/10.1080/01605682.2024.2306170
- Štrumbelj, E. (2014). On determining probability forecasts from betting odds. International Journal of Forecasting 30(4), 934–943. https://doi.org/10.1016/j.ijforecast.2014.02.008
- Štrumbelj, E. (2016). A comment on the bias of probabilities derived from betting odds and their use in measuring outcome uncertainty. Journal of Sports Economics 17(1), 12–26. https://doi.org/10.1177/1527002513519329
- Štrumbelj, E., & Robnik Šikonja, M. (2010). Online bookmakers' odds as forecasts: The case of European soccer leagues. International Journal of Forecasting 26(3), 482–488. https://doi.org/10.1016/j.ijforecast.2009.10.005
