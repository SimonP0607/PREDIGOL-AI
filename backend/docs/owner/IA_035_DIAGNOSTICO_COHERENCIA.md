# IA-035 — Diagnóstico de coherencia: cada diferencia con su causa (INVESTIGACIÓN)

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-A01, ola 1.*

*Ejecutado el 11-nov-2026, de 04:50 a 06:31 UTC, en solo lectura sobre producción. Imagen `predigol-backend:5ae050a9c56a`, código de `main` 77518df0: `decision`, `forecasting` y la repetición no cambian desde BE-036. No se tocó `decision-v2` ni nada de Picks.*

## Resumen: cinco conclusiones

1. **Ninguna diferencia queda sin causa, en ninguna de las dos jornadas, y ninguna es un fallo de reglas de `decision-v2`.**
   - 7-nov: 116 filas en desacuerdo y 223 candidatos no reconstruidos, repartidos en siete causas y comprobados fila a fila con su consulta.
   - 8-nov: 27 filas en desacuerdo y 143 no reconstruidos, con tres de esas mismas causas.
   - Una causa es intención de diseño: la regla de `decision-v1.1`. Las demás son de la **repetición**, que lee el estado actual de los partidos o filas fechadas antes de que se confirmaran.
2. **Los casos más permisivos son 22, no 11, y todos tienen causa.**
   - Los 11 de Picks son los que llegan a CAUTELA. Hay otros 11 que pasan de RECHAZADO a ABSTAIN.
   - Causas de los 22: en 16, la repetición ve picks de una ejecución de `pick_pipeline` que empezó antes del momento y se confirmó después; 2, un saque aplazado 24 h; 2, un estado PST que hoy es FT; 1, una clase de datos recalculada hoy; 1, una cuota leída de vuelta horas después.
   - Con las dos correcciones de visibilidad de la sección 4, **17 de 17** vuelven a coincidir: los 16 picks en vuelo y la cuota tardía. Los otros 5 dependen de datos que hoy no tienen historial.
   - El 8-nov no hay ningún caso más permisivo.
3. **`edge_not_validated` es intención de diseño.**
   - Está escrito en `fbi/decision/engine.py` («where it differs… on purpose»), y `decision-v1` adoptó la misma regla en IA-017 (`decision-v1.1`, primera fila el 8-nov a las 07:14:49 UTC).
   - Los 44 casos de Picks (42 del 7-nov y 2 del 8-nov, CAUTELA → ABSTAIN en la etapa final) los escribió código anterior, sin la etiqueta `decision-v1.1`. También el caso 75287.
   - Hoy ningún mercado tiene edge validado (todas las filas `market_edge` son NOT_VALIDATED), así que ninguna selección puede llegar a APROBADO con ninguno de los dos motores.
4. **Los no reconstruidos son reprogramaciones y cuotas tardías, y el contraste corregido lo prueba.**
   - 7-nov: 26 del núcleo y 58 de familias son de dos partidos reprogramados fuera del horizonte de 36 h. Las otras 139 de familias se deben a que la repetición ve cuotas capturadas antes del momento pero extraídas después.
   - 8-nov: 143 de 143 por cuotas tardías.
   - Fechando cada cuota por su extracción, se reconstruyen y coinciden 139 de 139 el 7-nov y 143 de 143 el 8-nov.
5. **Las probabilidades difieren por causas conocidas, pero la vista común cubre solo el 5,8–7,3 % de las filas.**
   - `compare_probabilities` (72 h) encuentra 55 diferencias de más de 0,5 pp entre el Match Center y el tablero con el interruptor, todas con causa: otro modelo, pronóstico sin calibrar, otro momento u otra calibración.
   - Para cubrir hándicap, doble oportunidad y familias, la vista necesita para cada uno su definición de mercado completo, la regla del push, una fuente para las familias y una calibración (sección 6).
   - Lo más barato y coherente es derivar la doble oportunidad del 1X2 de la vista y calibrar la distribución de goles para las escaleras de líneas (INT-A02, segunda parte).

## 1. Método

- **Repetición**: `python -m scripts.ia_decision_v2 replay --day <día> --view --json` en `predigol-worker`, con la conexión de solo lectura del propio script. El 7-nov tardó 1.624 s y el 8-nov, unos 13 min, con el servidor a carga 10–13. Las dos reproducen exactamente las cifras de Picks del 10-nov:

| Jornada | Filas | Momentos | Acuerdo | Núcleo | Desacuerdos | No reconstruidos |
|---|---|---|---|---|---|---|
| 7-nov | 16.142 | 119 | 15.803 (97,90 %) | 4.498 de 4.600 (97,78 %) | 116 | 223 |
| 8-nov | 9.288 | 104 | 9.118 (98,17 %) | 2.472 de 2.485 (99,48 %) | 27 | 143 |

- **Atribución**: la decisión guardada por `decision-v1` dice qué leyó: `pick_id`, `price_at`, `calibrator_id`, `kickoff_at`, el texto de cada filtro y `code_version`. Se compara con lo que la repetición lee hoy «a la fecha del momento». Lo que difiere se fecha con el registro de ejecuciones (`raw.ingestion_runs.finished_at`) o con `market.odds_extractions.extracted_at`.
- **Contraste**: `decision-v2` se vuelve a ejecutar solo en los momentos afectados, con dos correcciones de visibilidad aplicadas en memoria (`A01/fixcheck.py`, solo lectura). Si la causa atribuida es la correcta, la fila vuelve a coincidir.
- **Probabilidades**: `python -m scripts.compare_probabilities --hours 24|72 --json`, tal cual, más una atribución ampliada (`A01/attr_mc.py`, solo lectura) para las selecciones sin lectura de Intelligence, que la herramienta no atribuye.
- Todo son consultas de solo lectura con `statement_timeout` de 95 s, una a la vez. Los scripts de trabajo (consultas de solo lectura) no forman parte del repositorio; esta sección y la 10 describen qué hace cada uno.

## 2. El 7-nov, fila a fila

### 2.1 Las 116 diferencias

| Causa (comprobada) | Filas | Dirección | Evidencia |
|---|---|---|---|
| A. Estado de **hoy** PST/ABD: 3 partidos aplazados o abandonados después del momento | 49 (familias 37, núcleo 12) | v2 más estricto (REJECTED) | Hoy ABD, 26 filas (1 partido); PST, 23 (2). El saque no cambió y `decision-v1` pasó el filtro de datos en su momento. |
| B. Regla anterior a IA-017 en `decision-v1`: un contexto negativo subía INVESTIGACIÓN a CAUTELA | 43 | v2 más estricto (CAUTELA → ABSTAIN) | 42 en la etapa final (30 `ai_downgrade`, 12 `ai_reject`) y 1 en contexto (75287), escritas por los códigos `da8466f0`, `80c2e0ab`, `32c003fb`, `ab8c8462` y `de9ec17e`, ninguno con la etiqueta `decision-v1.1`. |
| C. **Picks no confirmados** en el momento: `picks.picks.created_at` es el inicio de la transacción de `pick_pipeline`, que se confirma al final | 18 | 16 más permisivos, 2 más estrictos | En las 18 filas, el pick que lee la repetición es de una ejecución que empezó antes del momento y terminó después. Ejemplo: decisión 75312 a las 11:30:08, ejecución de 11:24:45 a 11:37:19. |
| D. Saque movido después del momento (partido 27072, +24 h) | 2 | más permisivo (RECHAZADO «menos de 10 min» → CAUTELA) | `kickoff_at` de la decisión: 7-nov 15:30; hoy, 8-nov 15:30. |
| E. Estado PST **en el momento** que hoy es FT (partido 136658) | 2 | más permisivo (RECHAZADO → ABSTAIN) | El filtro 1 de v1 dice «estado PST». BE-036 lee FT como NS porque no hay historial de estados. |
| F. Clase de datos recalculada **en su sitio** (temporada 951, PRODUCT_ONLY) | 1 | más permisivo (RECHAZADO → CAUTELA) | `analytics.competition_data_scores` guarda una sola fila, con `computed_at` del 11-nov a las 03:32. A la fecha del momento no hay ninguna y v2 lee «sin evaluar». |
| G. Cuota leída de vuelta después del saque con el sello del proveedor (partido 32905, 1X2_1H) | 1 | más permisivo (RECHAZADO «precio atípico» → ABSTAIN) | La captura de las 20:18:13 se descargó el 8-nov a las 02:00:55 y se extrajo a las 02:06:52. |
| **Total** | **116** | | |

El grupo C, por tipo:
- **12 «pronóstico de hace 72 h»**: v1 tenía el pick de T−96 h y el de T−24 h estaba en vuelo (6 → ABSTAIN y 6 → CAUTELA).
- **2 AH**: v1 no tenía el pick de `poisson` y eligió `dixon_coles` sin campeón; v2 tiene `poisson` con el campeón #610 (ABSTAIN → CAUTELA).
- **1 DC** con otro `p_model` (EV de +1,1 % a +3,8 %).
- **2 en el umbral de EV del 2 %**: 81308 pasa de 0,019884 a ≥ 0,02 y 83996 de 0,020421 a < 0,02.
- **1 de intervalo** (73293): 25,6 puntos en v1 frente a 24,7 en el pick en vuelo.

En la fila 75287, la revisión REJECT sellada a las 11:13:08 no era visible a las 11:15:07, cuando v1 leyó DOWNGRADE (la misma carrera, en `ai.pick_reviews`); pero el cambio de estado lo explica la regla B.

**`edge_not_validated` solo en v2: 51 filas el 7-nov.** Son las 42 de la etapa final más 9 de otras etapas, las que Picks no separó:
- 75287 (regla B);
- 6 RECHAZADO → ABSTAIN y 1 en la etapa de valor (81308), del grupo C;
- 73293, en la etapa de riesgo, también del grupo C.

### 2.2 Los 22 más permisivos

| Paso | Filas | Causa |
|---|---|---|
| RECHAZADO → CAUTELA (datos) | 9 | 6 C (72 h), 2 D (saque), 1 F (clase) |
| ABSTAIN → CAUTELA (calibración) | 2 | C (pick de `poisson` en vuelo) |
| RECHAZADO → ABSTAIN (datos → `edge_not_validated`) | 6 | C (72 h) |
| RECHAZADO → ABSTAIN (valor) | 2 | C (78586 DC; 81308 en el umbral) |
| RECHAZADO → ABSTAIN (datos, familia) | 2 | E (PST en su momento) |
| RECHAZADO → ABSTAIN (mercado, familia) | 1 | G (cuota tardía) |

Los 11 de Picks son las dos primeras filas: 9 RECHAZADO → CAUTELA y 2 ABSTAIN → CAUTELA. Ninguno de los 22 nace de una regla de `decision-v2` más laxa: en todos, `decision-v2` decide sobre una entrada que `decision-v1` no tenía.

### 2.3 Los 223 no reconstruidos

| Familia | Filas | Causa |
|---|---|---|
| Núcleo | 26 | 2 partidos reprogramados fuera del horizonte de 36 h: 27687 (de 7-nov 15:00 a 9-nov 18:00) y 29142 (de 8-nov 17:30 a 9-nov 19:30) |
| Familias | 58 | los mismos 2 partidos: el saque de hoy queda más allá de 36 h desde el momento |
| Familias | 139 (81 partidos) | Mismo saque y mismo pronóstico (138; 1 con un pronóstico nuevo). En todas hay cuotas con `captured_at` ≤ momento y `extracted_at` > momento: la repetición ve precios que la capa no tenía, y la regla del candidato (≥ 3 % al mejor precio, la mejor línea por mercado) elige otra línea u otra selección. Retraso entre captura y extracción el 7-nov: mediana 2,9 min, p90 297 min, p99 452 min (1.235 extracciones). |

### 2.4 La vista común frente a la probabilidad de `decision-v2`

944 filas con vista (711 calibradas, 233 sin calibrar), 17 de 941 dentro de 0,5 pp; mediana 1,96 pp, p90 7,73, máximo 32,84. La herramienta atribuye las 941:

| Causa | Filas | Por encima de 0,5 pp | Mediana |
|---|---|---|---|
| Calibración (la vista reescala el mercado a 1; `decision-v2` usa la calibrada por selección) | 539 | 536 | 1,75 pp |
| Otro modelo | 213 | 204 | 3,71 pp |
| Vista sin calibrar | 189 | 184 | 6,94 pp |

## 3. El 8-nov

### 3.1 Las 27 diferencias

| Causa (comprobada) | Filas | Dirección | Evidencia |
|---|---|---|---|
| A. Estado de **hoy** PST: un solo partido (26739), aplazado después de los momentos | 24 (familias 13, núcleo 11) | v2 más estricto (→ REJECTED) | Saque sin cambios (8-nov 11:15). Momentos de 05:18:51 a 10:29:58. El filtro de datos de v1 dice «datos PARTIAL», no «estado PST»: en su momento el partido no figuraba aplazado. |
| B. Regla anterior a IA-017 | 2 | v2 más estricto (CAUTELA → ABSTAIN, etapa final) | 86087 (05:18:51, partido 8192, 1X2 Visitante) y 86133 (05:33:51, partido 29727, 1X2 Local), las dos `ai_reject`, código `de9ec17e`, sin etiqueta `decision-v1.1` (la primera es de las 07:14:49) |
| G. Cuota leída de vuelta después del saque | 1 | v2 más estricto (ABSTAIN → REJECTED «precio atípico +27 %») | Decisión 94150 (18:14:58, partido 31701, OU_1H Menos). v1 usó el precio de las 16:05:14 (cuota 4,80, 7 casas). La extracción 37646, con `captured_at` 18:00:14 (sello del proveedor), se descargó a las 22:00:38 y se extrajo a las 22:06:31, después del saque de las 19:00. |
| **Total** | **27** | | |

Ninguna es más permisiva.

### 3.2 Los 143 no reconstruidos

Todos son de familias: goles por mitad 117, córners 22 y tarjetas 4. Corresponden a 71 partidos, todos con el mismo saque que guardó la decisión y hoy FT. En los 143 hay cuotas capturadas antes del momento y extraídas después: es la misma causa que las 139 del 7-nov. Retraso entre captura y extracción el 8-nov: mediana 7,8 min, p90 306 min, p99 456 min (651 extracciones). Ninguno es del núcleo.

### 3.3 La vista común

675 filas con vista (631 calibradas, 44 sin calibrar), 176 dentro de 0,5 pp; mediana 1,68 pp, p90 3,44, máximo 20,93. La herramienta atribuye las 675:

| Causa | Filas | Por encima de 0,5 pp | Mediana |
|---|---|---|---|
| Calibración (reescalado) | 517 | 352 | 1,64 pp |
| Otro modelo | 126 | 116 | 2,44 pp |
| Vista sin calibrar | 32 | 31 | 5,45 pp |

## 4. Contraste: la repetición corregida

`fixcheck.py` vuelve a decidir con `decision-v2`, con la maquinaria de la propia repetición (`replay.world_at`, `candidates_as_of`, `engine.decide_all`), solo los momentos y partidos de las filas objetivo. Aplica dos cambios en memoria, sin escribir nada:
- un pick cuenta en `at` solo si la ejecución que lo escribió había terminado (`pick_candidates.run_id → raw.ingestion_runs.finished_at ≤ at`);
- una cuota cuenta solo si su extracción existía (`odds_extractions.extracted_at ≤ at`).

| Jornada | Objetivo | Resultado tras la corrección |
|---|---|---|
| 7-nov | 18 filas C y la fila G (83202) | **19 de 19 coinciden** con `decision-v1` |
| 7-nov | 197 no reconstruidos de familias | **139 de 139** con cuotas tardías se reconstruyen y coinciden. Las 58 de los partidos 27687 y 29142 siguen sin reconstruirse, como se espera: el saque de hoy cae fuera de las 36 h y la corrección no lo cambia. |
| 8-nov | 143 no reconstruidos y la fila G (94150) | **143 de 143** se reconstruyen y coinciden. **94150 coincide**, con los mismos códigos que v1. |
| 8-nov | 2 filas B (86087, 86133) | Siguen en desacuerdo, como se espera: CAUTELA → ABSTAIN al añadir `edge_not_validated`. La corrección no cambia una regla. |

Ejecuciones: 7-nov de 06:07 a 06:11 UTC (216 objetivos); 8-nov de 06:23 a 06:29 (146).

**Lo que queda tras la corrección:**
- 7-nov: 97 diferencias, todas de causas que la corrección no toca (A 49, B 43, D 2, E 2, F 1), y 84 no reconstruidos de los dos partidos reprogramados (26 del núcleo y 58 de familias).
- 8-nov: 26 diferencias (A 24, B 2) y 0 no reconstruidos.

Ninguna nace de un fallo de reglas de `decision-v2`. La única diferencia de reglas es la B, y es intencionada.

## 5. Match Center, tablero e Intelligence (`compare_probabilities`)

Medido el 11-nov a las 06:06 UTC, con la herramienta tal cual. Sus cifras cambian con cada ejecución, porque mira los partidos de las próximas 24 o 72 h.

| Ventana | Partidos | Selecciones | Tablero con interruptor frente a Intelligence | Match Center frente a Intelligence | Match Center frente al tablero con interruptor |
|---|---|---|---|---|---|
| 24 h | 7 | 33 | 33, **0** por encima de 0,5 pp (máximo 0,0) | 20, 20 por encima; mediana 8,46 pp | 20, 20 por encima; mediana 8,46 pp |
| 72 h | 45 | 194 | 51, **0** por encima (máximo 0,0) | 29, 28 por encima; mediana 8,16 pp | 99, 55 por encima; mediana 1,98 pp |

El tablero sin el interruptor (la cruda del motor) difiere de Intelligence en todas las selecciones: medianas de 10,1 y 13,4 pp. Para eso existe el interruptor.

**Causas** (atribución de la herramienta para el Match Center frente a Intelligence; la de las selecciones sin Intelligence es la de `attr_mc.py`, a las 06:18, con las mismas cifras de ventana):

| Causa | 24 h | 72 h | Mediana (72 h) |
|---|---|---|---|
| Con Intelligence: el pronóstico del Match Center está sin calibrar (`needs_price`: no había precio de 6 h o menos) | 15 | 20 | 9,96 pp |
| Con Intelligence: otro modelo (p. ej. `elo_ologit` en el Match Center y `poisson` en Intelligence en 1X2) | 3 | 6 | 6,54 pp |
| Con Intelligence: mismo modelo y momento, otra calibración | 2 | 2 | 2,35 pp |
| Sin Intelligence (el tablero muestra la cruda del motor): otro modelo | 0 | 21 | 5,23 pp |
| Sin Intelligence: más de 6 h entre el pick y el pronóstico | 0 | 4 | 6,81 pp |
| Sin Intelligence: el Match Center calibra y el tablero muestra la cruda | 0 | 2 | 7,83 pp |
| Sin causa | **0** | **0** | |
| **Total por encima de 0,5 pp** | **20** | **55** | |

El 10-nov, en 72 h, la mediana era 2,77 pp y dominaba «momento distinto». Hoy domina el pronóstico sin calibrar (`needs_price`): el Match Center no tenía un precio de 6 h o menos en el momento del pronóstico. Encaja con INT-A02, donde el 48,6 % de las predicciones no tenía un consenso reciente, pero no lo comprobé fila a fila.

## 6. Qué falta para que la vista común cubra hándicap, doble oportunidad y familias

Hoy `fbi.forecasting.market_view.MARKETS` sale de `MARKET_ROWS`: 1X2, más/menos 2,5 y ambos marcan, siete filas fijas. Esas filas fueron 944 de 16.142 (5,8 %) el 7-nov y 675 de 9.288 (7,3 %) el 8-nov. El 7-nov, el núcleo decidió además 2.361 filas de AH, 1.162 de OU (con otras líneas) y 209 de DC, y las familias 11.542.

| Mercado | Qué hay | Qué falta |
|---|---|---|
| **Doble oportunidad** | predicciones (`fbi.models.quoted`), consenso y calibradores, solo CHALLENGER | No es un mercado que sume 1: 1X + 12 + X2 = 2. Lo coherente es **derivarla** del 1X2 de la vista (1X = L + E, 12 = L + V, X2 = E + V), sin calibrarla por su cuenta. Coste bajo y suma coherente por construcción. |
| **Hándicap asiático** | 45 líneas en las predicciones, consenso y campeones `logit2` (`poisson` desde el 2-nov y `dixon_coles` desde el 9-nov) | (1) Un mercado completo es el par (Local, L) y (Visitante, −L), no una línea fija de `MARKET_ROWS`: hay que enumerar los pares de cada partido. (2) El push: en líneas enteras y de cuarto, p(gana) + p(pierde) + p(push) = 1, y la vista debe dar la probabilidad condicionada a que se liquide, como hace `ev_of`. (3) Reescalar par a par no hace monótona la escalera de líneas. |
| **Más/menos, otras líneas** | 26 líneas en las predicciones y consenso | Lo mismo que en AH: la escalera completa sale de una sola distribución de goles calibrada, y así las líneas son monótonas (INT-A02, segunda parte). |
| **Familias** (mitades, córners, tarjetas) | pronósticos `family-v1` en `models.match_forecasts`, precios de `market.odds_quotes`, ningún calibrador en `intel.calibrators` | (1) La vista solo lee `models.predictions`: necesita una segunda fuente, y `test_forecast_isolation.py` exige una entrada justificada para leerla. (2) El precio de las familias se calcula con las casas completas de `odds_quotes`, no con `market_consensus`. (3) Sin campeón, la vista diría «sin calibrar» en todo. |

## 7. Qué cambiaría para que la repetición mida solo reglas (propuesta, sin tocar `decision-v2` ni Picks)

1. **Visibilidad por confirmación.** Un pick cuenta en `at` solo si la ejecución de `pick_pipeline` que lo escribió terminó antes de `at` (`pick_candidates.run_id → raw.ingestion_runs.finished_at`). Una cuota cuenta solo si `odds_extractions.extracted_at ≤ at`. Es lo que prueba `fixcheck.py`, y explica 19 de 19 diferencias y 139 de 139 no reconstruidos del 7-nov. `track_commit_timestamp` está apagado, así que no hay otra marca de confirmación.
2. **Lo que solo existe hoy**: el estado del partido, el saque y la clase de datos, que la repetición no puede fechar porque no hay historial.
   - Propuesta: marcar esas filas como «no comparables» en lugar de desacuerdos en tres casos: si el estado de hoy es PST, ABD o CANC; si `kickoff_at` difiere del que guardó la decisión; o si la clase de datos tiene un `computed_at` posterior al momento.
   - La decisión guarda `kickoff_at`, así que la comprobación es directa.
   - Con esto, las 49 + 24 filas de la causa A y las 5 de D, E y F saldrían del recuento de desacuerdos.
3. **Una repetición fijada**: la decisión ya guarda `pick_id`, `price_at` y `calibrator_id`. Leerlos tal cual permite medir la equivalencia de reglas sin depender de la reconstrucción.

## 8. Gate de INT-A01

- **0 diferencias sin causa: se cumple.**
  - 7-nov: 116 de 116 desacuerdos y 223 de 223 no reconstruidos tienen causa.
  - 8-nov: 27 de 27 y 143 de 143.
  - Vista común: todas las filas comparadas tienen causa, 941 el 7-nov y 675 el 8-nov.
  - `compare_probabilities`: 20 de 20 y 55 de 55.
  - El contraste corregido confirma las causas C y G y las cuotas tardías. Las causas A, D, E y F se apoyan en lo que guardó la decisión (saque, texto del filtro, `computed_at`), porque no hay historial con que repetirlas.
- **La vista común cubre todos los mercados del núcleo: no se cumple.** Falta lo de la sección 6, que es trabajo de INT-A02 y A03.

## 9. Limitaciones

- **Causa C**: no hay una marca de confirmación por fila. Se prueba con el contraste: con la corrección, las 18 filas coinciden.
- **Causas A, D, E y F**: no se pueden repetir con datos de la época, porque el estado, el saque y la clase de datos no tienen historial. La evidencia es lo que guardó `decision-v1` en su momento.
- **Ventanas de `compare_probabilities`**: mira el momento en que se ejecuta (06:06 y 06:18 del 11-nov) y sus cifras cambian cada día. La atribución de las selecciones sin Intelligence es mía (`attr_mc.py`), con el mismo orden de causas que la herramienta.
- **Dos jornadas**: 7 y 8-nov, las mismas que midió Picks. El 7-nov mezcla código anterior y posterior a varios despliegues, y el 8-nov cambia de reglas a las 07:14:49.

## 10. Reproducción

Scripts de trabajo de la medición (solo lectura; no están en el repositorio):
- `j1.sh`: repetición del 7-nov.
- `A02/j2.sh`: repetición del 8-nov y `compare_probabilities` 24 y 72 h.
- `an1.py` y `an2.py`: resumen y listas.
- `q5.sh`–`q12.sh`: evidencia por fila; `q12.sh` es la del 8-nov.
- `fixcheck.py`, con `j3.sh` (7-nov) y `j4.sh` (8-nov): contraste corregido.
- `attr_mc.py`: causas de las diferencias entre el Match Center y el tablero.

En el servidor, las salidas en JSON se guardaron en `/tmp/lab_a01/` y se borraron al terminar. Las cifras de este informe se copiaron de ellas en su momento.
