# Biblioteca científica por método y lugar de aplicación

Plan Maestro PM, tarea **PM-11-08** (DOC-009). Índice de los artículos y métodos del catálogo de recursos del 18-nov-2026 (los 136
artículos y 26 fichas de método de las notas «biblioteca científica y modelos» y «evaluación y patrones»), ordenados por **método** y
con el **lugar del código que lo aplica**. Complementa la página de lecturas (libros y cursos) de
[`DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md`](DISCIPLINA_CONOCIMIENTO_Y_ALTA_PROVEEDORES.md) (§6.3), que no se repite aquí.

## Reglas de esta página

1. **Tres cosas separadas, en tres columnas.** El **método** es conocimiento: cómo se estima o se evalúa algo. La **evidencia de
   partido** es lo que entra de cada partido cuando el método se aplica (goles, cuotas, árbitro, alineación). Los **datos de
   entrenamiento** son de dónde aprende sus parámetros, siempre datos propios o del proveedor con licencia, y siempre con hora de corte
   anterior al partido. Un artículo enseña un método; **nunca es evidencia de un partido ni dato de entrenamiento**.
2. **Solo enlaces.** Se enlaza la página oficial, el DOI o la copia legal; no se copia texto, figuras ni tablas de ningún artículo al
   repositorio, a la base de conocimiento, a la web ni a un prompt. **Ningún libro ni artículo entra en un prompt** (DOC-007, §1).
   Aplicar un método publicado no requiere licencia; reproducir su texto sí.
3. **El acceso es el del catálogo.** «CC BY…»: licencia abierta leída; «copia abierta»: copia legal del autor o de un repositorio;
   «lectura gratuita»: gratis para leer en la editorial, sin licencia de reutilización; «preprint arXiv»: la licencia la eligió el
   autor y no se leyó una por una; «cerrado (editorial)»: de pago o sin copia abierta (el método se conoce y, si se usa, ya está
   implementado). Gratis para leer no es libre para reutilizar.
4. **Estado.** «En uso»: el módulo enlazado lo aplica hoy (aunque esté en sombra). «Solo LAB»: retador posible, sin código de
   producción. «Propuesto»: oportunidad del plan PM con datos que ya existen. «No se aplica»: descartado o sin los datos necesarios,
   con su motivo en la tabla I.

Los enlaces de la columna «Dónde se aplica» llevan al archivo del repositorio. Cuando un método está «en uso» y no tiene referencia
propia en el catálogo, se dice; ninguno de los de abajo está en ese caso.

### A. Goles y resultado

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Poisson independiente con decaimiento temporal (Maher) y corrección de marcadores bajos (Dixon-Coles) | goles de los dos equipos (90') | resultados de partidos anteriores de la competición, con peso que decae (ξ) | [`models/goals.py`](../../backend/src/fbi/models/goals.py), [`backtesting/walkforward.py`](../../backend/src/fbi/backtesting/walkforward.py) | en uso | [Maher (1982)](https://doi.org/10.1111/j.1467-9574.1982.tb00782.x) (cerrado (editorial)); [Dixon y Coles (1997)](https://doi.org/10.1111/1467-9876.00065) (cerrado (editorial)); [Goddard (2005)](https://doi.org/10.1016/j.ijforecast.2004.08.002) (cerrado (editorial)); [Ley, Van de Wiele y Van Eetvelde (2019)](https://doi.org/10.1177/1471082X18817650) (lectura gratuita) |
| Elo con multiplicador de goles y logit ordenado para 1X2 | resultado, localía | historial de resultados (Elo recalculado cada 6 h) | [`features/elo.py`](../../backend/src/fbi/features/elo.py), [`models/elo_ologit.py`](../../backend/src/fbi/models/elo_ologit.py) | en uso | [Hvattum y Arntzen (2010)](https://doi.org/10.1016/j.ijforecast.2009.10.002) (cerrado (editorial)); [Szczecinski y Djebbi (2020)](https://doi.org/10.1515/jqas-2019-0102) (copia abierta); [Kovalchik (2020)](https://doi.org/10.1016/j.ijforecast.2020.01.006) (cerrado (editorial)) |
| pi-ratings | diferencia de goles en casa y fuera | historial de resultados | [`features/pi.py`](../../backend/src/fbi/features/pi.py) | en uso | [Constantinou y Fenton (2013)](https://doi.org/10.1515/jqas-2012-0036) (copia abierta) |
| Regresión logística multinomial sobre variables de fuerza (fv2) | variables de fuerza antes del saque | partidos anteriores con sus variables | [`models/logistic.py`](../../backend/src/fbi/models/logistic.py), [`models/families.py`](../../backend/src/fbi/models/families.py) | en uso | [Hubáček, Šourek y Železný (2019)](https://doi.org/10.1007/s10994-018-5704-6) (lectura gratuita); [Berrar, Lopes y Dubitzky (2019)](https://doi.org/10.1007/s10994-018-5747-8) (lectura gratuita); [Grinsztajn, Oyallon y Varoquaux (2022)](https://arxiv.org/abs/2207.08815) (preprint arXiv) |
| Combinación de modelos (ensemble) | las probabilidades de cada familia | predicciones fuera de muestra de las familias | [`research/v2.py`](../../backend/src/fbi/research/v2.py) | solo LAB | [Pitcan (2026)](https://arxiv.org/abs/2608.11505) (preprint arXiv); [Groll, Ley, Schauberger y Van Eetvelde (2019)](https://doi.org/10.1515/jqas-2018-0060) (copia abierta) |
| Poisson bivariante, inflación de empates, Weibull con cópula, PARX | goles | resultados | — | solo LAB | [Karlis y Ntzoufras (2003)](https://doi.org/10.1111/1467-9884.00366) (cerrado (editorial)); [Boshnakov, Kharrat y McHale (2017)](https://doi.org/10.1016/j.ijforecast.2016.11.006) (copia abierta); [Angelini y De Angelis (2017)](https://doi.org/10.1002/for.2471) (copia abierta) |
| Dinámica explícita de la fuerza (espacio de estados, score-driven) | goles | resultados en orden temporal | — | solo LAB | [Rue y Salvesen (2000)](https://doi.org/10.1111/1467-9884.00243) (cerrado (editorial)); [Crowder, Dixon, Ledford y Robinson (2002)](https://doi.org/10.1111/1467-9884.00308) (cerrado (editorial)); [Koopman y Lit (2015)](https://doi.org/10.1111/rssa.12042) (copia abierta); [Koopman y Lit (2019)](https://doi.org/10.1016/j.ijforecast.2018.10.011) (copia abierta); [Baker y McHale (2015)](https://doi.org/10.1111/rssa.12060) (copia abierta) |
| Bayesiano jerárquico (contracción entre equipos de una liga) | goles | resultados de ligas con poca historia | — | solo LAB | [Baio y Blangiardo (2010)](https://doi.org/10.1080/02664760802684177) (copia abierta); [Barrera Moreno et al. (2025)](https://revistas.usantotomas.edu.co/index.php/estadistica/article/download/11822/Art05_Rendimiento_Futbolistico/32987) (lectura gratuita) |

### B. Cuotas y mercado

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Quitar el margen de la casa (Shin; potencia) | cuotas de cada casa antes del saque | —(no se entrena: es una transformación) | [`market/consensus.py`](../../backend/src/fbi/market/consensus.py) | en uso | [Štrumbelj (2014)](https://doi.org/10.1016/j.ijforecast.2014.02.008) (cerrado (editorial)); [Clarke, Kovalchik e Ingram (2017)](https://doi.org/10.11648/j.ajss.20170506.12) (licencia sin comprobar) |
| Consenso de casas y cierre como referencia | cuotas de varias casas; cierre | — | [`market/consensus.py`](../../backend/src/fbi/market/consensus.py), [`market/closing_reference.py`](../../backend/src/fbi/market/closing_reference.py), [`market/closing_value.py`](../../backend/src/fbi/market/closing_value.py) | en uso | [Leitner, Zeileis y Hornik (2010)](https://doi.org/10.1016/j.ijforecast.2009.10.001) (cerrado (editorial)); [Pitcan (2026)](https://arxiv.org/abs/2608.11505) (preprint arXiv) |
| Fuerza derivada de cuotas (cuotas como prior, BORS) | cuotas históricas de cada equipo | cuotas de partidos pasados (`market.odds_quotes`) | — | propuesto | [Egidi, Pauli y Torelli (2018)](https://doi.org/10.1177/1471082X18798414) (copia abierta); [Wunderlich y Memmert (2018)](https://doi.org/10.1371/journal.pone.0198668) (CC BY) |
| Mercado frente a modelo; retorno no es precisión | probabilidad del modelo y del cierre | — | [`market/closing_value.py`](../../backend/src/fbi/market/closing_value.py) | en uso | [Pitcan (2026)](https://arxiv.org/abs/2608.11505) (preprint arXiv); [Berrar, Lopes y Dubitzky (2024)](https://doi.org/10.1007/s10994-024-06625-9) (CC BY); [Hubáček y Šír (2020/2023)](https://arxiv.org/abs/2010.12508) (preprint arXiv) |

### C. Conteos: córners, tarjetas, tiros

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Binomial negativa (NB2) por equipo, con árbitro contraído hacia 1 | córners y tarjetas de cada equipo; árbitro asignado | conteos de partidos anteriores (desde nov-2023) | [`families/counts.py`](../../backend/src/fbi/families/counts.py), [`families/fit.py`](../../backend/src/fbi/families/fit.py), [`families/forecast.py`](../../backend/src/fbi/families/forecast.py) | en uso | [Titman, Costain, Ridall y Gregory (2015)](https://doi.org/10.1111/rssa.12075) (cerrado (editorial)); [Hargreaves y Powell (2022)](https://eprints.whiterose.ac.uk/id/eprint/229624/1/Modelling_bookings_in_association_football.pdf) (copia abierta); [Gómez-Déniz y Dávila-Cárdenes (2017)](https://doi.org/10.1285/i20705948v10n3p629) (CC BY-NC-ND 3.0 IT); [Dawson, Dobson, Goddard y Wilson (2007)](https://doi.org/10.1111/j.1467-985X.2006.00451.x) (copia abierta) |
| Calibrador de conteos con una sola regla para la escalera de líneas (`count-cal-v1`) | la distribución del conteo | predicciones fuera de muestra de bloques anteriores | [`countcal/calibrator.py`](../../backend/src/fbi/countcal/calibrator.py), [`countcal/walkforward.py`](../../backend/src/fbi/countcal/walkforward.py) | en uso | [Czado, Gneiting y Held (2009)](https://doi.org/10.1111/j.1541-0420.2009.01191.x) (licencia sin comprobar) |
| Poisson compuesta para córners en tandas | córners | conteos por partido | — | solo LAB | [Yip, Zou, Hung y Yiu (2021-2023)](https://arxiv.org/abs/2112.13001) (preprint arXiv) |
| Tiros y estadísticas del partido como proceso | tiros, tiros a puerta | estadísticas de equipo | — | propuesto | [Wheatcroft (2020)](https://doi.org/10.1016/j.ijforecast.2019.11.001) (copia abierta); [Wheatcroft (2021a)](https://doi.org/10.3233/JSA-200462) (CC BY-NC) |

### D. Jugadores

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Tasas por jugador contraídas hacia su posición; conteos NB por jugador | minutos y estadísticas por jugador; alineación | líneas de jugador de partidos anteriores | [`players/rates.py`](../../backend/src/fbi/players/rates.py), [`players/props.py`](../../backend/src/fbi/players/props.py), [`players/v2.py`](../../backend/src/fbi/players/v2.py) | en uso | [Egidi y Gabry (2018)](https://doi.org/10.1515/jqas-2017-0066) (copia abierta); [Holmes y McHale (2024)](https://livrepository.liverpool.ac.uk/id/eprint/3170651) (copia abierta); [Hewitt y Karakuş (2023)](https://doi.org/10.1016/j.fraope.2023.100034) (CC BY-NC-ND) |

### E. Calibración y puntuación

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Log loss como métrica principal; Brier y RPS como secundarias | probabilidad y resultado | — | [`models/metrics.py`](../../backend/src/fbi/models/metrics.py), [`backtesting/evaluate.py`](../../backend/src/fbi/backtesting/evaluate.py) | en uso | [Constantinou y Fenton (2012)](https://doi.org/10.1515/1559-0410.1418) (copia abierta); [Wheatcroft (2021)](https://doi.org/10.1515/jqas-2019-0089) (lectura gratuita); [Constantinou y Fenton (2012)](https://doi.org/10.1515/1559-0410.1418) (cerrado (editorial)); [Wheatcroft (2019/2021)](https://arxiv.org/abs/1908.08980) (preprint arXiv) |
| Error de calibración (ECE) y diagramas de fiabilidad | probabilidad y resultado | — | [`models/metrics.py`](../../backend/src/fbi/models/metrics.py), [`evaluation/board.py`](../../backend/src/fbi/evaluation/board.py) | en uso | [Silva Filho et al. (2023)](https://doi.org/10.1007/s10994-023-06336-7) (lectura gratuita); [Nixon et al. (2019)](https://arxiv.org/abs/1904.01685) (preprint arXiv); [Roelofs et al. (2020/2022)](https://arxiv.org/abs/2012.08668) (preprint arXiv); [Dimitriadis, Gneiting y Jordan (2021)](https://doi.org/10.1073/pnas.2016191118) (CC BY 4.0) |
| Descomposición de la puntuación (fiabilidad, resolución, nitidez) | probabilidad y resultado | — | — | propuesto | [Pohle (2020)](https://arxiv.org/abs/2005.01835) (preprint arXiv); [Gneiting, Balabdaoui y Raftery (2007)](https://doi.org/10.1111/j.1467-9868.2007.00587.x) (licencia sin comprobar); [Murphy (1973)](https://doi.org/10.1175/1520-0450(1973)012<0595:ANVPOT>2.0.CO;2) (licencia sin comprobar) |
| Calibración multiclase coherente (temperatura, Dirichlet), Venn-Abers | probabilidades 1X2 | predicciones fuera de muestra | — | propuesto | [Kull et al. (2019)](https://arxiv.org/abs/1910.12656) (preprint arXiv); [Vovk y Petej (2012/2014)](https://arxiv.org/abs/1211.0025) (preprint arXiv) |
| Intervalos de proporciones (Wilson) | conteos de aciertos | — | [`ai/intervals.py`](../../backend/src/fbi/ai/intervals.py), [`coverage/levels.py`](../../backend/src/fbi/coverage/levels.py) | en uso | [Brown, Cai y DasGupta (2001)](https://doi.org/10.1214/ss/1009213286) (licencia sin comprobar) |
| Intervalos de línea por cuantiles de los errores fuera de muestra (la idea de la predicción conforme) | líneas de goles | residuos fuera de muestra | [`models/line_intervals.py`](../../backend/src/fbi/models/line_intervals.py) | en uso | [Gibbs y Candès (2021)](https://arxiv.org/abs/2106.00170) (preprint arXiv) |

### F. Validación temporal y sesgos de investigación

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Walk-forward (origen rodante) y validación sin barajar | — | solo lo conocido antes del bloque evaluado | [`backtesting/walkforward.py`](../../backend/src/fbi/backtesting/walkforward.py), [`countcal/walkforward.py`](../../backend/src/fbi/countcal/walkforward.py) | en uso | [Bergmeir, Hyndman y Koo (2018)](https://doi.org/10.1016/j.csda.2017.11.003) (cerrado (editorial)); [Validación cruzada purgada con embargo y CPCV (López de Prado 2018)](https://en.wikipedia.org/wiki/Purged_cross-validation) (CC BY-SA) |
| Prevención de fugas de información | — | variables con hora de corte antes del saque | [`backtesting/walkforward.py`](../../backend/src/fbi/backtesting/walkforward.py), [`research/protocol.py`](../../backend/src/fbi/research/protocol.py) | en uso | [Kaufman, Rosset, Perlich y Stitelman (2012)](https://doi.org/10.1145/2382577.2382579) (cerrado (editorial)); [Kapoor y Narayanan (2022/2023)](https://arxiv.org/abs/2207.07048) (preprint arXiv) |
| Prerregistro con huella antes de mirar los datos | — | — | [`research/protocol.py`](../../backend/src/fbi/research/protocol.py), [`protosign/records.py`](../../backend/src/fbi/protosign/records.py) | en uso | [Gelman y Loken (2013)](https://sites.stat.columbia.edu/gelman/research/unpublished/p_hacking.pdf) (página web); [Simmons, Nelson y Simonsohn (2011)](https://doi.org/10.1177/0956797611417632) (cerrado (editorial)); [Nosek et al. (2018)](https://doi.org/10.1073/pnas.1708274114) (copia abierta) |
| Comparaciones múltiples y «mejor de N» (FDR, Reality Check, sobreajuste del backtest) | — | — | [`research/pattern_search.py`](../../backend/src/fbi/research/pattern_search.py) | en uso | [White (2000)](https://doi.org/10.1111/1468-0262.00152) (cerrado (editorial)); [Hansen (2005)](https://ideas.repec.org/a/bes/jnlbes/v23y2005p365-380.html) (cerrado (editorial)); [Bailey, Borwein, López de Prado y Zhu (2016)](https://doi.org/10.21314/JCF.2016.322) (cerrado (editorial)); [Bailey y López de Prado (2014)](https://doi.org/10.2139/ssrn.2460551) (lectura gratuita); [Benjamini y Hochberg (1995)](https://doi.org/10.1111/j.2517-6161.1995.tb02031.x) (cerrado (editorial)); [Harvey, Liu y Zhu (2016)](https://doi.org/10.1093/rfs/hhv059) (cerrado (editorial)) |
| Comparación pareada de pronósticos (diferencia de pérdidas con remuestreo por días) | pérdidas por partido de dos modelos | — | [`ai/review_retirement.py`](../../backend/src/fbi/ai/review_retirement.py) | en uso | [Diebold y Mariano (1995)](https://doi.org/10.1080/07350015.1995.10524599) (cerrado (editorial)); [Hansen, Lunde y Nason (2011)](https://doi.org/10.3982/ECTA5771) (cerrado (editorial)) |
| Deriva y cambio de formato (vigilar la calibración por competición) | — | — | [`observability/drift.py`](../../backend/src/fbi/observability/drift.py) | en uso | [Gama et al. (2014)](https://doi.org/10.1145/2523813) (copia abierta); [Zeileis (2026)](https://www.r-bloggers.com/2026/06/machine-learning-meets-reality-forecast-evaluation-for-the-2026-fifa-world-cup) (página web) |

### G. Contexto del partido

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Ventaja de local por liga y variable en el tiempo | localía, liga, temporada | resultados por liga | [`features/elo.py`](../../backend/src/fbi/features/elo.py) | propuesto | [Peeters y van Ours (2021)](https://doi.org/10.1007/s10645-020-09372-z) (CC BY 4.0); [Leitner et al. (2023)](https://doi.org/10.1007/s11301-021-00254-5) (lectura gratuita); [Ventaja de local por liga, variable en el tiempo y contraída](https://www.r-bloggers.com/2026/06/machine-learning-meets-reality-forecast-evaluation-for-the-2026-fifa-world-cup) (licencia sin comprobar) |
| Regresión a la media y contracción (Bayes empírico) | tasas de equipo, árbitro y jugador | historial con su tamaño de muestra | [`players/rates.py`](../../backend/src/fbi/players/rates.py), [`statmath/formulas.py`](../../backend/src/fbi/statmath/formulas.py), [`families/fit.py`](../../backend/src/fbi/families/fit.py) | en uso | [Barnett, van der Pols y Dobson (2005)](https://doi.org/10.1093/ije/dyh299) (cerrado (editorial)); [Franks, D'Amour, Cervone y Bornn (2016)](https://doi.org/10.1515/jqas-2016-0098) (preprint arXiv); [Efron y Morris (1975)](https://doi.org/10.1080/01621459.1975.10479864) (cerrado (editorial)) |
| Rachas, cambio de entrenador, impulso (mito o dato) | — | — | — | no se aplica | [Miller y Sanjurjo (2018)](https://doi.org/10.3982/ECTA14943) (lectura gratuita); [Sousa et al. (2024)](https://doi.org/10.5114/biolsport.2024.131816) (CC BY-SA 4.0); [Heuer et al. (2011)](https://doi.org/10.1371/journal.pone.0017664) (CC BY); [Parsons y Rohde (2015)](https://research-repository.griffith.edu.au/items/0675b98f-a106-4a29-812f-6eaed7800ee3) (copia abierta); [Ötting, Deutscher, Singleton y De Angelis (2022)](https://doi.org/10.48550/arXiv.2211.06052) (preprint arXiv) |
| Altitud, distancia de viaje, congestión | altitud del estadio; viaje; días de descanso | —(sin datos cargados: 0 estadios con altitud, PM-07-01) | [`venues/elevation.py`](../../backend/src/fbi/venues/elevation.py) | propuesto | [McSharry (2007)](https://doi.org/10.1136/bmj.39393.451516.AD) (licencia sin comprobar); [Gore, McSharry, Hewitt y Saunders (2008)](https://doi.org/10.1111/j.1600-0838.2008.00836.x) (cerrado (editorial)); [Pollard y Armatas (2017)](https://doi.org/10.1080/24748668.2017.1304031) (cerrado (editorial)); [Cabrera-Hernández et al. (2021/2023)](https://doi.org/10.14198/jhse.2023.181.04) (copia abierta); [Oberhofer, Philippovich y Winner (2010)](https://doi.org/10.1016/j.joep.2009.11.003) (cerrado (editorial)); [Julian, Page y Harper (2021)](https://doi.org/10.1007/s40279-020-01359-9) (copia abierta); [Chumacero (2009)]() (licencia sin comprobar) |
| Efecto del árbitro y del marcador en las tarjetas | árbitro asignado, marcador | tarjetas por árbitro | [`families/counts.py`](../../backend/src/fbi/families/counts.py) | en uso | [Dawson, Dobson, Goddard y Wilson (2007)](https://doi.org/10.1111/j.1467-985X.2006.00451.x) (copia abierta); [Buraimo, Forrest y Simmons (2010)](https://doi.org/10.1111/j.1467-985X.2009.00604.x) (cerrado (editorial)); [Dohmen y Sauermann (2016)](https://doi.org/10.1111/joes.12106) (cerrado (editorial)) |

### H. Simulación de temporadas y torneos

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| Monte Carlo de la temporada (escenarios con semilla) y peso de cada partido | calendario pendiente, reglamento | probabilidades de partido | [`intel/scenarios.py`](../../backend/src/fbi/intel/scenarios.py), [`competitions/scenarios.py`](../../backend/src/fbi/competitions/scenarios.py) | en uso | [Groll, Hanekov, Hvattum, Michels, Schauberger, Sukhanova, Witte y Zeileis (2026)](https://www.r-bloggers.com/2026/06/football-meets-machine-learning-forecasting-the-2026-fifa-world-cup/) (página web) |

### I. Métodos que hoy no se aplican

| Método | Evidencia de partido (qué entra de cada partido) | Datos de entrenamiento (de dónde aprende) | Dónde se aplica | Estado | Referencias (acceso) |
| --- | --- | --- | --- | --- | --- |
| En juego (probabilidad durante el partido) | eventos en vivo, tiempo | partidos minuto a minuto | — | no se aplica | [Dixon y Robinson (1998)](https://doi.org/10.1111/1467-9884.00152) (cerrado (editorial)); [Robberechts, Van Haaren y Davis (2021)](https://doi.org/10.1145/3447548.3467194) (copia abierta); [Klemp, Wunderlich y Memmert (2021)](https://doi.org/10.1038/s41598-021-03157-3) (CC BY) |
| Espaciales y de secuencias (xG por tiro, VAEP, EPV, GNN, LEM) | posiciones y eventos con coordenadas | datos de seguimiento que API-Football no da | — | no se aplica | [Anzer y Bauer (2021)](https://doi.org/10.3389/fspor.2021.624475) (CC BY); [Mendes-Neves, Meireles y Mendes-Moreira (2024)](https://doi.org/10.1007/s10994-024-06606-y) (lectura gratuita); [Yang, Memmert y Klemp-Weins (2026)](https://arxiv.org/abs/2606.09327) (preprint arXiv); [Wang, Veličković et al. (2024)](https://doi.org/10.1038/s41467-024-45965-x) (CC BY) |
| Modelos tabulares fundacionales (TabPFN, TabICL) | variables de partido | conjuntos pequeños | — | solo LAB | [Hollmann et al. (2025)](https://doi.org/10.1038/s41586-024-08328-6) (CC BY); [Grinsztajn et al. (2025)](https://arxiv.org/abs/2511.08667) (preprint arXiv); [Qu, Holzmüller, Varoquaux y Le Morvan (2025)](https://arxiv.org/abs/2502.05564) (preprint arXiv) |
| Gradient boosting y redes sobre tablas | variables fv2 | partidos anteriores | — | no se aplica | [Yeung, Bunker, Umemoto y Fujii (2024)](https://doi.org/10.1007/s10994-024-06608-w) (lectura gratuita); [Grinsztajn, Oyallon y Varoquaux (2022)](https://arxiv.org/abs/2207.08815) (preprint arXiv); [Hubáček, Šourek y Železný (2022)](https://doi.org/10.1093/imaman/dpab029) (cerrado (editorial)) |
| LLM como pronosticadores | texto | — | —(regla: ningún LLM toca probabilidades) | no se aplica | [Halawi, Zhang, Yueh-Han y Steinhardt (2024)](https://arxiv.org/abs/2402.18563) (preprint arXiv); [Ding, Guo y Xu (2026)](https://arxiv.org/abs/2607.17765) (preprint arXiv); [Schröder et al. (2026)](https://arxiv.org/abs/2607.24573) (preprint arXiv); [Wang et al. (2026)](https://arxiv.org/abs/2607.18084) (preprint arXiv) |

## Qué enseña la biblioteca, en cinco líneas

* **El cierre del mercado es el techo** y las familias de modelos rinden casi igual: no se cambia de algoritmo sin información nueva
  (tablas A y B).
* **La cuota como entrada sí ayuda**, sobre todo donde no hay mercado: es la fuerza derivada de cuotas, propuesta (tabla B).
* **En tarjetas hay poca señal** más allá de la liga y el árbitro, que ya se modelan; los córners llegan en tandas (tabla C).
* **Medir bien importa más que el modelo**: log loss como métrica principal, calibración por competición, validación sin barajar,
  prerregistro y corrección por comparaciones múltiples (tablas E y F).
* **Lo espacial, lo de en juego y los LLM pronosticadores** no se aplican con los datos de API-Football ni con la regla «ningún LLM
  toca probabilidades» (tabla I).

## Cómo se mantiene

* Una fila nueva entra cuando un método se aplica o se propone en el código; su referencia, solo si su acceso está en el catálogo.
* Un método que deja de usarse no se borra: pasa a «no se aplica» con su motivo.
* La revisión trimestral de DOC-007 (§7) repasa también esta página.

Fuentes: catálogo de recursos del 18-nov-2026 (notas de la investigación «Recursos gratuitos e innovación PrediGol», ficheros 02 y 03)
y el informe de esa investigación, §4. Comprobado contra `main` del 20-nov-2026: cada módulo enlazado existe.
