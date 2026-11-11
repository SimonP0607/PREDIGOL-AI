# IA-036 — Calibración coherente multiclase (LAB)

*Plan Maestro de Evolución de PrediGol Intelligence 2026, pieza INT-A02, ola 1. Protocolo proto-int-a02-v1, huella 2a1cdb3e…; ejecutado el 11-nov-2026.*

**En una línea:** la calibración coherente suma 1 en el 100 % de los mercados, pero **no** pronostica igual o mejor que la reescalada de `cal-logit2-v1`. El límite superior del IC 95 % de la diferencia pareada es > 0 en 1X2, más/menos 2,5 y ambos marcan, y en 1X2 además empeora el ECE de Local y Empate en más de 0,005. **Veredicto: RECHAZA en los tres mercados.** La reescalada sigue siendo la cifra coherente y el calibrador coherente queda en el LAB con su motivo.

## Protocolo (sello)

| Campo | Valor |
|---|---|
| Clave, versión y marco | `INT-A02`, `proto-int-a02-v1`, `lab-protocol-v1` |
| Huella (SHA-256 del JSON canónico) | `2a1cdb3ec31a6b5075010a989e6205bf60bc699c54891a62ac861ad0fd69ae6d`. Comprobada al ejecutar: el script llama primero a `protocol.require("INT-A02")` y el resultado lleva `protocol.stamp` |
| Dónde | objeto `A02` en `backend/src/fbi/research/protocol.py`, commit `1d8c98d` (PR #236), fechado el 11-nov a las 04:21:22 UTC. El fichero usado es idéntico al del commit (sha256 `a7a95ab7…`) |
| Registrado y semilla | 2026-11-11; semilla 20261111 (bootstrap de días y de ajustes) |
| Cronología (UTC) | protocolo en git a las 04:21:22 → esta sesión empieza a las 04:25 → de 04:30 a 04:50, consultas de estructura: columnas, índices, recuentos por semana y por estado, horas antes del saque y planes de consulta. Ninguna calcula una métrica de los métodos que se comparan → el script se prueba con datos sintéticos → extracción válida de 05:41:31 a 05:51:15 → **única evaluación válida, de 05:51:23 a 05:52:34** |

**Incidencia, declarada.** Una primera ejecución automática (extracción desde las 05:20:19 y evaluación terminada a las 05:32:12) corrió sobre una extracción incompleta. Seis de los once tramos semanales de `units` se cancelaron por el `statement_timeout` de 95 s y quedaron con 0 filas: la consulta materializaba un CTE que recorría `models.predictions`. Aun así, la tarea encadenada evaluó. Su salida se apartó **sin leerla** (`/tmp/lab_a02/invalid/`, sha256 `94cc3f78…`, 80.824 bytes).

Fue un fallo de ejecución, no de método. La ejecución válida usa el mismo script, el mismo módulo (mismos sha256), la misma ventana, los mismos días y los mismos mercados. Solo cambió la consulta de extracción, que pasó a un LATERAL por partido, en tramos diarios y con parada si un tramo falla. Las definiciones de los datos no cambiaron.

**Cómo se concretó lo que el protocolo deja abierto** (fijado en el script antes de ejecutar):
- **Momento de la predicción**: `t` = su `created_at`. Coincide con `data_cutoff_ts`: como mucho 0,97 s de diferencia en las 69.163 filas extraídas. `q` = `p_raw`, que es igual a `p_calibrated` en las 69.163 filas.
- **Resultado**: el marcador reglamentario liquidado con `fbi.picks.settlement.market_outcome`, la regla de los picks. «Liquidado» se lee en `core.fixture_results.settled_at`.
- **Walk-forward**: días de Bogotá. El día D se ajusta con los partidos que empezaron en [D − 28 d, D) y se liquidaron antes de que empezara D; mínimo 500; se saltan los 3 primeros días con datos. Un día cuenta solo si pueden ajustarse **los dos** calibradores.
- **Coherente** (`cal-coherent-v1`): p_k ∝ exp(a_k + b·log q_k + c·log m_k), con a = 0 en el último resultado (Visitante, Menos, No) y L2 = 1,0 en b y c, como `fbi.intel.stats`.
- **Referencia reescalada**: `cal-logit2-v1` tal como lo ajusta producción. Se usan `calibration.train_set` y `fit_params("logit2")` sobre su población: el último pick liquidado de cada selección y modelo, con todas las líneas de OU porque así se agrupa en producción. Se aplica con `apply_params` a cada resultado del partido-mercado y se divide por la suma, como `market_view._calibrate`. Es la probabilidad que hoy muestra el Match Center (`forecast-v1`) cuando hay campeón y un precio de 6 h o menos.
- **Estadístico primario**: la media de las diferencias diarias (coherente − reescalada), en la que cada día cuenta una vez, como en la nota de potencia. IC 95 % por percentiles de 10.000 remuestreos de días. Como control, la media por unidad con los días remuestreados enteros.
- **ECE**: por resultado, 10 grupos de igual tamaño. **Peso del mercado**: c / (b + c).

## Datos

- **Universo**: partidos terminados (FT, AET o PEN) con saque desde el 1-sep (Bogotá) y resultado liquidado. Las predicciones reales (sin `backtest_session_id`) empiezan a finales de septiembre: la primera unidad válida es del 25-sep (`elo_ologit`) y del 29-sep (`dixon_coles` y `poisson`).
- **Modelos**: `poisson` y `dixon_coles` en los tres mercados, y `elo_ologit` en 1X2.
- **Unidad** (la del protocolo): un partido, un modelo y un mercado completo. **Candidatas: 28.461; válidas: 14.633.**
- **Exclusiones**: solo una, «sin consenso sin margen de 6 h o menos en el momento de la predicción»: **13.828 (48,6 %)**.
- **Antelación de la predicción**: en `poisson` y `dixon_coles`, la última predicción guardada 3 h o más antes del saque queda a una mediana de 19,4 h del partido (p10 6,0 h; p90 92,1 h; 24.330 unidades). A esa distancia a menudo no hay consenso reciente. En `elo_ologit` la mediana es 3,4 h (p90 6,2 h). Entre las unidades válidas: 19,6 h (p90 23,9 h) y 3,4 h (p90 4,5 h).
- Válidos por mercado y modelo: 1X2 `dixon_coles` 1.807, `elo_ologit` 3.790, `poisson` 1.810; OU 1.805 y 1.808; BTTS 1.805 y 1.808.
- **Población de `cal-logit2-v1`** (picks liquidados ganados o perdidos; orden `dixon_coles`, `elo_ologit`, `poisson`): 1X2 3.323, 3.696 y 3.061; BTTS 2.364 y 2.441; OU 14.921 y 15.154 (todas las líneas). Como hace `SETTLED_SQL` (solo `win` y `loss`), se dejan fuera 1.829 medias pérdidas, 1.712 devoluciones (push), 1.681 medias ganancias y 326 anuladas.
- **Fuera de muestra**: 1X2 5.796 unidades (31 días, del 11-oct al 10-nov), OU 2.602 y BTTS 2.602 (26 días, del 16-oct al 10-nov). En **partidos distintos**: 3.250, 1.308 y 1.308.
- **Días sin puntuar**: los 3 primeros de cada modelo y los que no llegaban a 500 para ajustar (9 en `elo_ologit`, 13 en `poisson`, 14 en `dixon_coles`). El primer día puntuado es el 11-oct, el 16-oct y el 17-oct; desde ahí, los días son seguidos hasta el 10-nov.
- **Selecciones marcadas por el modelo** (un pick antes del saque) dentro de lo puntuado: 1X2 5.136, OU 1.825, BTTS 1.579.
- **Entradas**: `units.csv` (69.163 filas, sha256 `1bf1318b…`) y `picks.csv` (50.508 filas, `34b9da9a…`). Imagen `predigol-backend:5ae050a9c56a`, sin red.

## Resultados por mercado y modelo

### Primaria por mercado (modelos juntos; log loss multiclase, en nats)

| Mercado | n | Días | LL coherente | LL reescalada | Diferencia media por día | IC 95 % | DE diaria | DMD (2,80·s/√n) | Días que gana la coherente | Control: media por unidad (IC 95 %) |
|---|---|---|---|---|---|---|---|---|---|---|
| 1X2 | 5.796 | 31 | 0,9569 | 0,9553 | +0,00250 | [−0,00006; +0,00532] | 0,00779 | 0,00392 | 14 de 31 | +0,00160 [−0,00012; +0,00350] |
| Más/menos 2,5 | 2.602 | 26 | 0,6660 | 0,6654 | +0,00455 | [+0,00021; +0,01075] | 0,01448 | 0,00796 | 11 de 26 | +0,00059 [−0,00113; +0,00249] |
| Ambos marcan | 2.602 | 26 | 0,6751 | 0,6787 | +0,00443 | [−0,00274; +0,01462] | 0,02362 | 0,01298 | 13 de 26 | −0,00358 [−0,00675; +0,00036] |

Con las dos agregaciones, el límite superior es > 0 en los tres mercados. En ambos marcan la media por unidad sale a favor de la coherente (−0,0036), pero su intervalo toca el 0 por arriba (+0,0004). Además, la media por día la arrastran días muy pequeños: el 10-nov tiene 4 partidos-mercado y una diferencia de +0,107.

### Suma = 1

| Mercado | Coherente: mercados que suman 1 (tolerancia 1e-9) | Desvío máximo, coherente | `cal-logit2-v1` sin reescalar: suma − 1 en pp, mediana [p10; p90], desvío máximo |
|---|---|---|---|
| 1X2 | 5.796 de 5.796 (100 %) | 2,2e-16 | +1,63 [−5,79; +3,85], 13,24 |
| Más/menos 2,5 | 2.602 de 2.602 (100 %) | 2,2e-16 | −1,71 [−7,14; +3,29], 8,42 |
| Ambos marcan | 2.602 de 2.602 (100 %) | 1,1e-16 | −3,23 [−5,99; −0,15], 6,75 |

### ECE por resultado (10 grupos de igual tamaño)

| Mercado | Resultado | Coherente | Reescalada | Coherente − reescalada | Modelo bruto | Mercado sin margen |
|---|---|---|---|---|---|---|
| 1X2 | Local | 0,0233 | 0,0172 | **+0,0061** | 0,0221 | 0,0201 |
| 1X2 | Empate | 0,0165 | 0,0108 | **+0,0057** | 0,0248 | 0,0191 |
| 1X2 | Visitante | 0,0231 | 0,0195 | +0,0035 | 0,0232 | 0,0327 |
| Más/menos 2,5 | Más | 0,0319 | 0,0385 | −0,0065 | 0,0566 | 0,0348 |
| Más/menos 2,5 | Menos | 0,0334 | 0,0377 | −0,0043 | 0,0576 | 0,0355 |
| Ambos marcan | Sí | 0,0322 | 0,0463 | −0,0141 | 0,0686 | 0,0340 |
| Ambos marcan | No | 0,0344 | 0,0478 | −0,0134 | 0,0688 | 0,0325 |

### Secundarias: frente al modelo sin calibrar y frente al mercado solo (diferencia media por día, IC 95 %)

| Mercado | Coherente − bruto | Coherente − mercado | Reescalada − mercado | LL bruto | LL mercado |
|---|---|---|---|---|---|
| 1X2 | −0,03175 [−0,04514; −0,01900] | +0,00191 [−0,00193; +0,00590] | −0,00059 [−0,00393; +0,00305] | 0,9810 | 0,9566 |
| Más/menos 2,5 | −0,00415 [−0,02421; +0,02307] | +0,00250 [+0,00061; +0,00500] | −0,00205 [−0,00851; +0,00189] | 0,6827 | 0,6647 |
| Ambos marcan | −0,00502 [−0,02345; +0,02023] | +0,00373 [−0,00221; +0,01070] | −0,00070 [−0,00644; +0,00447] | 0,6924 | 0,6735 |

### Secundaria: ECE de las selecciones que el modelo marca (la población que juzga la decisión)

| Mercado | n | Acierto | Coherente (p media) | `cal-logit2-v1` sin reescalar | Reescalada | Mercado |
|---|---|---|---|---|---|---|
| 1X2 | 5.136 | 0,317 | 0,0199 (0,315) | 0,0177 (0,315) | 0,0165 (0,316) | 0,0255 (0,309) |
| Más/menos 2,5 | 1.825 | 0,441 | 0,0321 (0,460) | 0,0338 (0,451) | 0,0313 (0,459) | 0,0290 (0,460) |
| Ambos marcan | 1.579 | 0,441 | 0,0326 (0,444) | 0,0562 (0,466) | 0,0489 (0,480) | 0,0643 (0,458) |

### Por modelo, con el peso del mercado en el pool

| Mercado | Modelo | n | Días | Diferencia media por día (IC 95 %) | c / (b + c): ajuste conjunto (IC 95 %, 500 remuestreos de días) | Mediana de los ajustes diarios [p25; p75] | b, c (conjunto) |
|---|---|---|---|---|---|---|---|
| 1X2 | `dixon_coles` | 1.296 | 25 | +0,00607 [+0,00019; +0,01448] | 0,768 [0,565; 1,028] | 0,779 [0,747; 0,824] | 0,286, 0,944 |
| 1X2 | `elo_ologit` | 3.190 | 31 | +0,00117 [−0,00101; +0,00346] | 0,945 [0,775; 1,159] | 0,931 [0,830; 0,957] | 0,062, 1,058 |
| 1X2 | `poisson` | 1.310 | 26 | +0,00678 [−0,00051; +0,01665] | 0,755 [0,544; 0,997] | 0,793 [0,744; 0,845] | 0,301, 0,929 |
| Más/menos 2,5 | `dixon_coles` | 1.294 | 25 | +0,00387 [−0,00034; +0,01037] | 0,927 [0,701; 1,192] | 0,961 [0,942; 0,985] | 0,075, 0,952 |
| Más/menos 2,5 | `poisson` | 1.308 | 26 | +0,00457 [+0,00029; +0,01066] | 0,922 [0,689; 1,187] | 0,950 [0,924; 0,982] | 0,081, 0,960 |
| Ambos marcan | `dixon_coles` | 1.294 | 25 | +0,00366 [−0,00274; +0,01224] | 1,109 [0,728; 1,552] | 1,149 [1,110; 1,202] | −0,098, 0,993 |
| Ambos marcan | `poisson` | 1.308 | 26 | +0,00502 [−0,00314; +0,01714] | 1,151 [0,772; 1,697] | 1,172 [1,130; 1,228] | −0,132, 1,003 |

Todos los ajustes diarios convergieron.

### Ligas prioritarias (grupos 1–3 de `comp-priority-v1`) frente al resto

| Mercado | Segmento | n | Días | Diferencia media por día (IC 95 %) | ECE coherente − reescalada, peor resultado |
|---|---|---|---|---|---|
| 1X2 | prioritarias | 783 | 29 | +0,00065 [−0,00620; +0,00780] | −0,0055 |
| 1X2 | resto | 5.013 | 31 | +0,00016 [−0,00409; +0,00403] | +0,0053 |
| Más/menos 2,5 | prioritarias | 318 | 21 | +0,00070 [−0,00403; +0,00543] | −0,0268 |
| Más/menos 2,5 | resto | 2.284 | 26 | +0,00551 [+0,00090; +0,01185] | −0,0107 |
| Ambos marcan | prioritarias | 318 | 21 | −0,00438 [−0,01997; +0,01168] | +0,0143 |
| Ambos marcan | resto | 2.284 | 26 | +0,00330 [−0,00458; +0,01397] | −0,0150 |

Las series diarias de los segmentos recomponen exactamente la del total (error < 1e-6). Que las medias por día de los dos segmentos queden por debajo de la del total no es un error: una media de medias diarias no es aditiva entre segmentos.

### Fiabilidad (10 grupos de igual tamaño; probabilidad media → frecuencia observada)

| Mercado · resultado | Coherente | Reescalada |
|---|---|---|
| 1X2 · Local | 0,10→0,14 · 0,22→0,23 · 0,29→0,26 · 0,35→0,42 · 0,41→0,43 · 0,46→0,45 · 0,52→0,52 · 0,59→0,58 · 0,68→0,66 · 0,83→0,82 | 0,13→0,14 · 0,25→0,22 · 0,32→0,28 · 0,38→0,41 · 0,42→0,42 · 0,47→0,46 · 0,52→0,53 · 0,59→0,57 · 0,67→0,66 · 0,80→0,81 |
| 1X2 · Empate | 0,10→0,13 · 0,17→0,18 · 0,20→0,21 · 0,22→0,24 · 0,23→0,23 · 0,25→0,22 · 0,26→0,24 · 0,27→0,24 · 0,28→0,28 · 0,31→0,32 | 0,12→0,13 · 0,18→0,18 · 0,20→0,20 · 0,22→0,22 · 0,23→0,24 · 0,24→0,21 · 0,25→0,22 · 0,26→0,26 · 0,27→0,28 · 0,30→0,32 |
| 1X2 · Visitante | 0,05→0,06 · 0,12→0,14 · 0,18→0,18 · 0,23→0,25 · 0,27→0,25 · 0,32→0,31 · 0,37→0,34 · 0,44→0,46 · 0,54→0,58 · 0,73→0,66 | 0,07→0,05 · 0,14→0,15 · 0,19→0,19 · 0,23→0,23 · 0,27→0,26 · 0,31→0,31 · 0,36→0,35 · 0,42→0,46 · 0,51→0,58 · 0,68→0,66 |
| OU 2,5 · Más | 0,41→0,43 · 0,47→0,40 · 0,51→0,46 · 0,53→0,53 · 0,56→0,56 · 0,58→0,60 · 0,60→0,60 · 0,63→0,56 · 0,67→0,73 · 0,73→0,72 | 0,39→0,42 · 0,46→0,39 · 0,50→0,45 · 0,53→0,57 · 0,56→0,56 · 0,58→0,57 · 0,61→0,65 · 0,64→0,57 · 0,67→0,71 · 0,75→0,72 |
| BTTS · Sí | 0,48→0,48 · 0,52→0,52 · 0,53→0,49 · 0,55→0,55 · 0,56→0,52 · 0,58→0,64 · 0,59→0,65 · 0,60→0,55 · 0,62→0,65 · 0,66→0,68 | 0,44→0,51 · 0,48→0,55 · 0,50→0,51 · 0,52→0,48 · 0,53→0,54 · 0,54→0,57 · 0,55→0,63 · 0,56→0,65 · 0,58→0,60 · 0,62→0,69 |

Las tablas de Menos y de No (complementarias) están en `a02_result.json`.

## Veredicto según el protocolo

| Mercado | Suma = 1 | IC 95 % de la diferencia ≤ 0 | ECE: ningún resultado empeora más de 0,005 | Muestra (≥ 1.500 en ≥ 5 días) | **Veredicto** |
|---|---|---|---|---|---|
| 1X2 | sí (100 %) | **no** (+0,00532) | **no** (Local +0,0061, Empate +0,0057) | sí (5.796 en 31) | **RECHAZA** |
| Más/menos 2,5 | sí (100 %) | **no** (+0,01075; todo el intervalo > 0) | sí | sí (2.602 en 26) | **RECHAZA** |
| Ambos marcan | sí (100 %) | **no** (+0,01462) | sí | sí (2.602 en 26) | **RECHAZA** |

**Lectura del mínimo de muestra.** El protocolo pide «al menos 1.500 partidos-mercado fuera de muestra en al menos 5 días por mercado» y define la unidad como «un partido, un modelo y un mercado completo». Aquí se cuentan unidades, igual que `calib-gate-v1` cuenta las selecciones de cada modelo.

Si se contaran partidos distintos, más/menos 2,5 y ambos marcan tendrían 1.308, por debajo de 1.500. Su veredicto sería entonces «pendiente por muestra» y no se interpretaría. 1X2, con 3.250 partidos distintos, seguiría en RECHAZA. En las dos lecturas la consecuencia es la misma: la coherente no sustituye a la reescalada.

**Consecuencia (regla de rechazo):** la reescalada sigue siendo la cifra coherente y la calibración coherente queda en el LAB con su motivo. Para G-COH (INT-A04), falla la condición de log loss en los tres mercados y la de calibración en 1X2; el plan prevé este caso: «queda la reescalada como cifra coherente y se sigue en el LAB». Cambiar el método es un protocolo nuevo, `proto-int-a02-v2`, registrado antes de mirar datos; no se hizo nada de eso aquí.

**Cinco conclusiones**
1. La coherente cumple lo que promete por construcción: suma 1 en el 100 % de las 11.000 unidades puntuadas. `cal-logit2-v1` sin reescalar se desvía una mediana de +1,6, −1,7 y −3,2 pp, y hasta 13 pp.
2. No es mejor pronosticador: frente a la reescalada, pierde +0,0025, +0,0045 y +0,0044 nats por unidad (media de días) en 1X2, más/menos 2,5 y ambos marcan. En más/menos 2,5 es peor con un intervalo que excluye el 0.
3. La calibración se mueve en sentidos opuestos según el mercado: peor en 1X2 (Local y Empate, por encima del umbral) y mejor en más/menos y ambos marcan (−0,004 a −0,014). En las selecciones que el modelo marca de ambos marcan, la coherente está mucho mejor calibrada que `cal-logit2-v1` (ECE 0,033 frente a 0,056).
4. Ninguna de las dos calibraciones gana al mercado sin margen: la reescalada queda a ≈ 0 y la coherente, entre +0,002 y +0,004 peor (con significación solo en más/menos). El peso del mercado en el pool es 0,76–0,95 en 1X2 (el intervalo de `dixon_coles` y `poisson` roza el 1), ≈ 0,92 en más/menos y > 1 en ambos marcan (b < 0). En más/menos y ambos marcan, a esta distancia del saque, el modelo no aporta información demostrable sobre el mercado.
5. Contada en unidades, la muestra supera el mínimo del protocolo: de 2.602 a 5.796 en 26 a 31 días. Con ella, la diferencia mínima detectable va de 0,004 a 0,013 nats, y las estimaciones caen del lado de «peor». Contados en partidos distintos, más/menos y ambos marcan se quedan en 1.308 (véase la lectura del mínimo).

## Limitaciones

- **Lectura de la referencia.** Se tomó `cal-logit2-v1` con su población de producción, los picks liquidados, por dos motivos: la pregunta del protocolo es «la probabilidad que hoy se muestra», y la secundaria de las selecciones marcadas compara con ese calibrador.
  - La otra lectura posible es reajustar `logit2` por selección sobre las mismas unidades que la coherente. No se calculó (regla de parada).
  - En los mercados de dos resultados esa variante es, por álgebra, **idéntica** a la coherente: con dos clases, el pool es el `logit2` de un lado. La prueba `test_two_outcomes_is_cal_logit2_of_one_side` lo comprueba hasta 1e-6. El otro lado del mercado sale con los mismos coeficientes y el intercepto cambiado de signo, así que reescalar no cambia nada.
  - Por tanto, en más/menos 2,5 y ambos marcan, toda la diferencia medida viene de la población y del tamaño del ajuste. En todo el periodo, la referencia aprende de los picks: en OU, de todas las líneas, unas 15.000 observaciones por modelo. La coherente aprende de las unidades de la vista: unas 1.800 por modelo.
  - Solo en 1X2 la variante sería un método distinto.
- **Poblaciones distintas.** La coherente aprende de todos los resultados de cada mercado y la referencia, de los picks. Es parte de lo que se compara.
- **Frescura**: el 48,6 % de las unidades no tiene consenso de 6 h o menos en el momento de la predicción. La última predicción de `poisson`/`dixon_coles` guardada antes de T−3 h está a una mediana de T−19,4 h. El resultado no dice nada de predicciones a T−3 h.
- **Estadístico**: en la media por día, un día pesa lo mismo con 4 unidades (OU y BTTS, 10-nov) que con 480 (1X2). La media por unidad da el mismo veredicto. El umbral de ECE (0,005) se aplica a estimaciones puntuales, sin intervalo.
- **Sin fuga**: predicción guardada ≥ 3 h antes del saque; consenso con `as_of` ≤ `t`; ajuste solo con partidos liquidados antes del día; picks de la referencia creados antes del saque. Las predicciones reales no existen antes de finales de septiembre.
- **Alcance**: tres mercados de la vista común. La segunda parte de la ficha (escaleras de líneas y hándicaps a partir de la distribución de goles; vigilancia de deriva) no estaba en este protocolo.
- **Dependencia**: el script importa `fbi.research.protocol`, que llega con el PR #236. En el servidor se cargó desde ese commit con `lab/run_a02.py` (mismo fichero byte a byte).

## Reproducción

- **Módulo puro** (este PR): `backend/src/fbi/intel/calibration_coherent.py`. Pruebas: `backend/tests/unit/test_calibration_coherent.py`, 14 pruebas que cubren suma = 1, recuperación de parámetros, equivalencia con `cal-logit2-v1` en dos resultados, invariancia de la referencia, penalización, ECE por grupos iguales, regla de entrenamiento y bootstrap. `PYTHONPATH=src …/.venv/bin/python -m pytest` pasa; `ruff check .` y `mypy` estricto (723 ficheros) sin errores. Sin migración y sin tocar el calibrador activo.
- **Evaluación sobre CSV**: `cd backend && python -m scripts.ia_lab_a02_coherente --units units.csv --picks picks.csv --out a02.json`. Necesita el PR #236 en la rama, por `fbi.research.protocol`.
  - En el servidor se ejecutó en la imagen desplegada, sin red y sin acceso a la base de datos: `docker run --rm --network none -v /tmp/lab_a02:/lab --entrypoint python <imagen> /lab/lab/run_a02.py /lab/lab/overlay /lab/lab/ia_lab_a02_coherente.py …`.
  - Antes de tocar datos reales se probó con datos sintéticos.
  - sha256: script `e8c0a741…`, módulo `f5f7ece9…`, `protocol.py` `a7a95ab7…`, `run_a02.py` `e04faaf4…`.
- **Extracción** (solo lectura, `statement_timeout` de 95 s, un tramo diario cada vez): `backend/docs/owner/lab/IA_036/extract.sql` (sha256 `7f1c67ab…`), con `psql -v ON_ERROR_STOP=1 -v units=true|false -v lo=… -v hi=…`. La tarea que la corre día a día es `j2.sh`.
- **Recuentos descriptivos**: partidos distintos, antelación, `t` frente a `data_cutoff_ts`. Salen de `lab/count_units.py` (sha256 `d286dda2…`), que no calcula ninguna métrica.
- **Resultado**: `backend/docs/owner/lab/IA_036/resultado.json` (113.861 bytes, sha256 `0dd331f9…`). Tablas generadas con `lab/tables.py` en `a02_tables.md`.
- **Entradas**: los CSV se borran del servidor al terminar, como pide el brief. Sus sha256 quedan en «Datos» para comprobar una nueva extracción. Repetirla con las mismas fechas añadiría los partidos liquidados después y las correcciones posteriores del origen.
