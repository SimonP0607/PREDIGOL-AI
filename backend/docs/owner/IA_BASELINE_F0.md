# Línea base de producción · Plan Maestro IA, Fase 0

> **Generado por código, sin cifras escritas a mano.** `backend/scripts/ia_baseline.sql` lee producción en una transacción de solo lectura; `backend/scripts/ia_baseline_report.py` convierte su salida en este informe. Para repetirlo: `bash ia_baseline.sh` en el servidor y `python -m scripts.ia_baseline_report <archivo> > docs/owner/IA_BASELINE_F0.md`.

| Dato | Valor |
|:---|:---|
| Archivo de medición | `baseline_20261025T0503Z.txt` |
| sha256 del archivo | `c8197487f658c1abf5b73cad7e8419692183124519b1597a1fb0634620c3d8dd` |
| Tamaño | 70.378 bytes, 41 secciones |
| Hora de la lectura (UTC) | 2026-10-25T05:03:47Z |
| Base de datos | fbi, migración 0093, 20 GB |
| Transacción | solo lectura (`read_only = on`), terminada con ROLLBACK; ningún dato se modificó |

## 1. Qué datos hay y cuáles no

El plan pide ≥ 30 días «donde existan». La contabilidad de IA de PrediGol (`ai.usage`) empezó el 2026-10-08, así que hay **16,2 días**, no 30. Se dice aquí una vez y las cifras de abajo llevan siempre su muestra.

| Tabla | Filas | Primera | Última | Días |
|:---|---:|:---|:---|---:|
| `ai.usage` | 8.843 | 2026-10-08 21:28 | 2026-10-25 03:24 | 16,2 |
| `ai.match_briefs` | 5.456 | 2026-10-09 00:56 | 2026-10-25 03:24 | 16,1 |
| `ai.fixture_passes` | 5.572 | 2026-10-09 05:05 | 2026-10-25 03:24 | 15,9 |
| `ai.pick_reviews` | 115.220 | 2026-10-08 21:28 | 2026-10-25 04:54 | 16,3 |
| `ai.match_packets` | 67.445 | 2026-10-08 21:28 | 2026-10-25 04:54 | 16,3 |
| `ai.evidence` | 9.543 | 2026-10-07 02:03 | 2026-10-25 02:50 | 18,0 |
| `ai.research_cache` | 3.756 | 2026-10-08 21:56 | 2026-10-24 07:49 | 15,4 |
| `ai.day_plans` | 34 | 2026-10-09 00:51 | 2026-10-24 12:35 | 15,5 |
| `intel.decisions` | 33.956 | 2026-10-13 07:32 | 2026-10-25 04:56 | 11,9 |
| `intel.decision_outcomes` | 23.103 | 2026-10-10 23:34 | 2026-10-24 12:24 | 13,5 |
| `intel.postmortems` | 2.920 | 2026-10-14 12:50 | 2026-10-24 12:35 | 10,0 |
| `analytics.ai_runs` | 84 | 2026-10-04 11:05 | 2026-10-24 11:05 | 20,0 |
| `ai.cycles` | 1.545 | 2026-10-08 21:28 | 2026-10-25 04:54 | 16,3 |
| `ai.budget_alerts` | 0 | — | — | — |

`intel.decisions` solo existe desde el 2026-10-13: las cifras de decisiones y CLV cubren menos días que las de gasto.

## 2. Gasto

- **Mes en curso (hasta 2026-10-25 05:03 UTC):** 87,65 USD en 8.843 llamadas: Claude 77,01 USD, Exa 10,64 USD. Es lo que cuenta `ai.usage` desde el 2026-10-08.
- **Presupuesto mensual vigente:** 180 USD (Claude y Exa juntos; sale del «mes» del plan del día).
- **Claude por día completo (UTC), 16 días del 2026-10-09 al 2026-10-24:** media 4,67 USD, mínimo 2,89 USD, máximo 7,50 USD.
- **Últimos 7 días completos (2026-10-18 a 2026-10-24):** Claude 5,17 USD al día (155 USD por 30 días); los 7 anteriores, 4,23 USD al día (22,4 % de cambio). Es una proyección lineal, no una previsión: cambia con la carga de partidos.
- **Sábado y domingo:** Claude 5,79 USD al día (5 días); lunes a viernes 4,16 USD (11 días). La carga de partidos manda: una semana con otro calendario se mueve más que cualquier optimización pequeña.
- **Exa:** 0,76 USD al día en esos 7 días (23 USD por 30 días); 56 búsquedas el 2026-10-24 (hora de Bogotá), frente a 31 el 2026-10-09.

| Día UTC | Llamadas | Claude USD | Exa USD | Total USD |
|:---|---:|---:|---:|---:|
| 2026-10-08 (parcial) | 84 | 2,27 | 0,14 | 2,40 |
| 2026-10-09 | 455 | 3,69 | 0,48 | 4,17 |
| 2026-10-10 | 955 | 5,22 | 0,48 | 5,70 |
| 2026-10-11 | 696 | 4,57 | 0,48 | 5,05 |
| 2026-10-12 | 341 | 2,89 | 0,48 | 3,37 |
| 2026-10-13 | 327 | 3,71 | 0,48 | 4,19 |
| 2026-10-14 | 349 | 4,47 | 0,62 | 5,09 |
| 2026-10-15 | 338 | 3,50 | 0,69 | 4,19 |
| 2026-10-16 | 435 | 4,34 | 0,74 | 5,08 |
| 2026-10-17 | 1.073 | 6,10 | 0,75 | 6,85 |
| 2026-10-18 | 770 | 5,57 | 0,80 | 6,37 |
| 2026-10-19 | 345 | 4,61 | 0,82 | 5,43 |
| 2026-10-20 | 400 | 4,43 | 0,69 | 5,12 |
| 2026-10-21 | 381 | 4,30 | 0,69 | 4,99 |
| 2026-10-22 | 331 | 4,55 | 0,68 | 5,23 |
| 2026-10-23 | 491 | 5,26 | 0,80 | 6,05 |
| 2026-10-24 | 1.061 | 7,50 | 0,84 | 8,34 |
| 2026-10-25 (parcial) | 11 | 0,04 | 0,00 | 0,04 |

## 3. Dónde se gasta

| Propósito | Llamadas | Correctas | USD | Parte del gasto de Claude |
|:---|---:|---:|---:|---:|
| `pick_review` | 1.459 | 1.440 | 60,74 | 78,9 % |
| `match_brief` | 5.724 | 5.724 | 14,69 | 19,1 % |
| `pattern_review` | 17 | 17 | 0,74 | 1,0 % |
| `evidence_extraction` | 569 | 569 | 0,39 | 0,5 % |
| `postmortem` | 348 | 348 | 0,29 | 0,4 % |
| `learning` | 17 | 17 | 0,16 | 0,2 % |

Total Claude en la ventana: 77,01 USD. Exa: 10,64 USD (709 búsquedas a 0,015 USD).

Por modelo, con una comprobación contra la lista de precios publicada (entrada y salida por millón de tokens):

| Modelo | Llamadas | Tokens de entrada | Tokens de salida | En caché | USD registrado | USD por lista | Diferencia |
|:---|---:|---:|---:|---:|---:|---:|---:|
| claude-haiku-5-5 | 6.632 | 74.196.762 | 15.698.279 | 0 | 15,2688 | 15,2688 | 0,000 % |
| claude-opus-5-5 | 283 | 3.004.595 | 466.850 | 0 | 21,3554 | 21,3554 | 0,000 % |
| claude-sonnet-5-5 | 1.219 | 14.365.774 | 1.165.804 | 0 | 40,3896 | 40,3896 | 0,000 % |

El registro cuadra con la lista de precios al céntimo: la contabilidad interna no es una fuente de error. Lo que **no** hay es conciliación con la Consola de Anthropic (hace falta el CSV de costes por workspace, acción manual del dueño); sin ella este informe es el libro interno, no la factura.

Por modelo y versión de prompt (las filas con más gasto):

| Propósito | Modelo | Prompt | Llamadas | Entrada media | Salida media | USD | USD por llamada |
|:---|:---|:---|---:|---:|---:|---:|---:|
| `pick_review` | sonnet-5-5 | review-v2 | 1.172 | 11.941 | 973 | 39,39 | 0,0336 |
| `pick_review` | opus-5-5 | review-v2 | 253 | 11.447 | 1.774 | 20,56 | 0,0813 |
| `match_brief` | haiku-5-5 | brief-v5 | 2.759 | 12.262 | 2.811 | 7,26 | 0,0026 |
| `match_brief` | haiku-5-5 | brief-v8 | 1.064 | 20.303 | 2.923 | 3,72 | 0,0035 |
| `match_brief` | haiku-5-5 | brief-v3 | 1.783 | 7.914 | 2.213 | 3,38 | 0,0019 |

## 4. Llamadas, tokens y tiempos

| Propósito | Modelo | Llamadas | Latencia p50 (s) | p95 (s) | Entrada p50 | Entrada p95 | Salida p50 | Salida p95 |
|:---|:---|---:|---:|---:|---:|---:|---:|---:|
| `evidence_extraction` | haiku-5-5 | 569 | 2,6 | 5,3 | 3.753 | 4.682 | 575 | 1.400 |
| `learning` | sonnet-5-5 | 17 | 4,2 | 4,7 | 2.596 | 2.661 | 472 | 554 |
| `match_brief` | haiku-5-5 | 5.724 | 11,2 | 14,3 | 12.028 | 20.937 | 2.703 | 3.428 |
| `pattern_review` | sonnet-5-5 | 17 | 7,5 | 8,9 | 18.175 | 20.556 | 798 | 945 |
| `pick_review` | opus-5-5 | 268 | 16,6 | 20,6 | 10.997 | 16.098 | 1.741 | 2.126 |
| `pick_review` | sonnet-5-5 | 1.172 | 6,6 | 8,5 | 11.953 | 16.498 | 967 | 1.101 |
| `postmortem` | haiku-5-5 | 339 | 3,5 | 4,7 | 2.759 | 3.791 | 576 | 710 |
| `postmortem` | sonnet-5-5 | 9 | 4,5 | 5,3 | 2.820 | 3.189 | 528 | 594 |

Estados de las 8.134 llamadas a Claude: 19 `refused` en `pick_review`; el resto, `ok`. Las que no terminaron `ok` pertenecen a: `review-v1` (19); ninguna otra versión de prompt tiene llamadas fallidas en el registro.

Ciclos de análisis: 1.525 correctos y 2 fallidos (duración media 2.128 s); 67 se ejecutaron con el presupuesto del día en `REDUCED` (coste total de esos ciclos 0,045 USD). Todos en modo `shadow`.

## 5. Coste por partido y por candidato

- **Por partido y día** (llamadas que nombran un partido, Claude y Exa; 2.193 partidos-día en 17 días): media ponderada 0,0396 USD; la media diaria va de 0,0207 USD a 0,0874 USD. El p90 diario ronda 0,125 USD y el máximo de un partido-día fue 1,33 USD.
- **Llamadas por partido y día:** `evidence_extraction` 1,26 de media (p90 2, máx. 2; 453 partidos-día); `match_brief` 3,00 de media (p90 4, máx. 6; 1.906 partidos-día); `pick_review` 2,33 de media (p90 4, máx. 24; 627 partidos-día); `postmortem` 1,30 de media (p90 2, máx. 11; 268 partidos-día); `web_search` 1,57 de media (p90 3, máx. 6; 453 partidos-día).
- **Por candidato revisado por el modelo:** 0,0508 USD (1.185 selecciones con revisión de modelo de 3.626, 32,7 %). Cuadra con `ai.usage`: 60,74 USD de `pick_review` entre 1.185 = 0,0513 USD. (La primera versión de esta medición sumaba también la fila «combined», que repite el coste de la del modelo, y daba el doble; está corregida en el SQL.)
- **Revisiones de modelo por partido y pasada:** `final` 1,81 de media (p90 2, máx. 14; 159 pasadas); `first` 1,77 de media (p90 2, máx. 24; 456 pasadas); `pre` 2,01 de media (p90 3, máx. 15; 145 pasadas).

## 6. Duplicación y reutilización

- **Briefs por partido y día:** 2,87 de media (5.447 briefs de 1.900 partidos-día, días 2026-10-09 a 2026-10-24); 96,7 % de los partidos-día tienen 2 o más. Es el tope de `ai.fixture_passes` (primera, previa y final).
- **Briefs posteriores que llegan a la misma conclusión que el anterior del mismo partido y día** (mismas razones, incertidumbre, calidad de datos y marca de escalado): 1.691 de 3.511 = 48,2 %. Es una cota de lo que una regla de «cambio material» podría ahorrar; la regla concreta se mide aparte, sobre paquetes guardados, antes de activarla.
- **Entradas idénticas pagadas dos veces** (mismo propósito, partido y `input_hash`): `evidence_extraction` 1 de 569 (0,2 %, 0,001 USD de 0,39 USD); `match_brief` 302 de 5.724 (5,3 %, 0,722 USD de 14,69 USD); `pick_review` 10 de 1.459 (0,7 %, 0,531 USD de 60,74 USD).
- **Paquetes:** `packet-v8` pesa 6.320 tokens aproximados de media (p95 7.353) y se guardó 13.088 veces el 2026-10-24 para 707 partidos: un paquete nuevo por cada ciclo en que algo cambia.

## 7. Caché y Batch: hoy y potencial medido

- **Caché de prompts:** 0 tokens leídos de caché de 91.567.131 de entrada = 0,0 %. El proveedor no pide ni registra caché (`ai.usage` ni siquiera tiene columna para las escrituras en caché).
- **Batch:** 0 % de las llamadas (no existe la ruta).

Llamadas que llegaron después de otra del mismo propósito y modelo (lo que una caché podría haber reutilizado):

| Propósito | Modelo | Llamadas | USD | Mismo partido ≤ 5 min | Mismo partido ≤ 1 h | Cualquier partido ≤ 5 min | Cualquier partido ≤ 1 h |
|:---|:---|---:|---:|---:|---:|---:|---:|
| `pick_review` | sonnet-5-5 | 1.176 | 39,39 | 43,5 % | 43,7 % | 89,0 % | 94,0 % |
| `pick_review` | opus-5-5 | 283 | 21,36 | 15,5 % | 21,9 % | 79,5 % | 85,9 % |
| `match_brief` | haiku-5-5 | 5.724 | 14,69 | 5,3 % | 5,3 % | 87,5 % | 98,6 % |
| `evidence_extraction` | haiku-5-5 | 569 | 0,39 | 0,0 % | 0,0 % | 81,7 % | 92,1 % |
| `postmortem` | haiku-5-5 | 339 | 0,19 | 23,3 % | 23,3 % | 95,0 % | 95,0 % |
| `postmortem` | sonnet-5-5 | 9 | 0,10 | 0,0 % | 0,0 % | 55,6 % | 55,6 % |

«Mismo partido» es el caso de los datos del partido (el paquete) repetidos entre candidatos; «cualquier partido» es el de las instrucciones, que son las mismas para todas las llamadas. Es potencial, no ahorro: depende de que el prefijo sea idéntico byte a byte y de que la caché responda.

Gasto por pasada y, de él, el hecho con el partido a 4 h o más (la parte que puede esperar el resultado de un Batch):

| Propósito | Modelo | Pasada | Llamadas | USD | Llamadas con KO ≥ 4 h | USD con KO ≥ 4 h |
|:---|:---|:---|---:|---:|---:|---:|
| `pick_review` | sonnet-5-5 | first | 632 | 21,28 | 578 | 19,29 |
| `pick_review` | opus-5-5 | first | 177 | 14,59 | 161 | 13,23 |
| `pick_review` | sonnet-5-5 | final | 268 | 9,13 | 0 | 0,00 |
| `pick_review` | sonnet-5-5 | pre | 250 | 8,37 | 208 | 6,97 |
| `match_brief` | haiku-5-5 | first | 2.035 | 5,00 | 1.938 | 4,78 |
| `match_brief` | haiku-5-5 | final | 1.872 | 4,94 | 0 | 0,00 |
| `match_brief` | haiku-5-5 | pre | 1.807 | 4,73 | 1.648 | 4,29 |
| `pick_review` | opus-5-5 | pre | 41 | 3,34 | 34 | 2,78 |
| `pick_review` | opus-5-5 | outside_a_pass | 46 | 1,90 | 0 | 0,00 |
| `pick_review` | opus-5-5 | final | 19 | 1,53 | 0 | 0,00 |
| `pick_review` | sonnet-5-5 | outside_a_pass | 26 | 0,60 | 0 | 0,00 |

En las pasadas `first` y `pre`, con el partido a ≥ 4 h, hay **51,69 USD** (67,1 % del gasto de Claude de la ventana), de los que 42,27 USD son revisión de selecciones (69,6 % del gasto de `pick_review`). Con el 50 % de descuento del Batch eso sería, como máximo, 25,84 USD en la ventana; el ahorro real depende de cuánto de ello pase realmente por Batch y de que la revisión pueda esperar. Se atribuye cada llamada a la pasada de su partido por la ventana de tiempo de la pasada (aproximación).

## 8. Cobertura y volumen (la referencia del Gate A)

- **Partidos del día con mercado:** 1.837 de 1.957 partidos en 16 días (2026-10-09 a 2026-10-24).
- **Pasadas terminadas:** `final` ok 1.787; `first` ok 1.819; `pre` ok 1.726.
- **Partidos-día con al menos un brief:** 1.900, frente a 1.837 con mercado al abrir el día (la diferencia son partidos que entraron al plan después de abrir).
- **Decisiones con revisión de IA enlazada:** `CAUTELA` 0 de 257 (0,0 %); `INVESTIGACION` 3.659 de 16.221 (22,6 %); `RECHAZADO` 1.648 de 17.478 (9,4 %).
- **Candidatos por día** (2026-10-13 a 2026-10-24, 12 días): media 1.616 selecciones en 248 partidos; no rechazadas, 410 al día.
- **Familias de mercado en las decisiones:** AH 15.784 (6.731 selecciones); OU 7.421 (6.805 selecciones); 1X2 5.564 (2.019 selecciones); BTTS 2.997 (938 selecciones); DC 2.190 (526 selecciones).

**Tiempos frente al inicio del partido** (minutos que faltaban al terminar cada pasada): `final` p50 40 min, p5 32 min (1.868 pasadas, terminadas después de T-15: 0); `first` p50 628 min, p5 238 min (1.900 pasadas, terminadas después de T-15: 1); `pre` p50 347 min, p5 186 min (1.804 pasadas, terminadas después de T-15: 0). El veredicto final llega antes de T-15 en 100,00 % de las pasadas; el SLO del plan es ≥ 99 %.

## 9. Resultados de las decisiones (CLV): la referencia de las comparaciones futuras

Las cifras son lo que ya hay liquidado en `intel.decision_outcomes`. Sirven como punto de partida para comparar brazos más adelante, **no** para atribuir nada a la IA: quién se revisa no es aleatorio.

| Estado de la decisión | Liquidadas | CLV medio | IC 95 % (pp) | CLV mediano | Ganadas | Perdidas |
|:---|---:|---:|---:|---:|---:|---:|
| `RECHAZADO` | 11.571 | -6,30 % | ± 0,14 | -4,96 % | 3.904 | 6.125 |
| `INVESTIGACION` | 11.309 | -3,35 % | ± 0,09 | -3,00 % | 4.654 | 5.520 |
| `CAUTELA` | 223 | -1,08 % | ± 0,28 | -1,22 % | 104 | 86 |

| Veredicto de la revisión | Motor | Liquidadas | CLV medio | IC 95 % (pp) |
|:---|---:|---:|---:|---:|
| `UNREVIEWED` | - | 19.319 | -5,16 % | ± 0,09 |
| `APPROVE` | combined | 1.562 | -3,34 % | ± 0,28 |
| `DOWNGRADE` | combined | 1.469 | -2,69 % | ± 0,28 |
| `REJECT` | combined | 753 | -2,85 % | ± 0,41 |

«IC 95 %» es 1,96 errores estándar de la media (puntos porcentuales). Las filas no son comparables entre sí como efecto de la IA: la revisión con modelo solo se hace a una parte de los candidatos y los datos cubren pocos días.

## 10. Investigación (Exa y caché de investigación)

- **Caché de investigación:** `search` 626 filas, 95 reutilizaciones (80 filas reutilizadas, vida media 6,6 h); `url` 3.130 filas, 768 reutilizaciones (648 filas reutilizadas, vida media 168,0 h).
- **Evidencia por partido:** 1.380 partidos con evidencia, media 6,92 (p50 3, p90 17, máx. 35).
- **Búsquedas Exa por día (hora de Bogotá):** 31, 32, 32, 32, 32, 41, 46, 49, 50, 53, 55, 46, 46, 45, 53, 56 (del 2026-10-09 al 2026-10-24); coste por búsqueda 0,015 USD.

## 11. Lo que este informe no permite concluir

- Con 16 días completos de contabilidad no se puede separar tendencia de ritmo semanal: hay apenas dos semanas y el calendario de partidos cambia de una a otra.
- No hay conciliación con la Consola (falta el CSV por workspace). Hasta tenerla, «gasto» es el libro interno, que cuadra con los precios publicados.
- El potencial de caché y de Batch es una cota superior medida sobre llamadas pasadas; el ahorro real se mide en los 7 días completos del Gate A.
- La atribución de cada llamada a una pasada usa la ventana de tiempo de la pasada de ese partido; las llamadas fuera de pasada aparecen como `outside_a_pass`.
- El CLV es el de los partidos ya liquidados desde que existe `intel.decisions`; no distingue causa y efecto.

## 12. Referencias para el Gate A

Lo que se comparará con los 7 días completos de medición de la Fase 0 (se mide igual, con el mismo SQL):

| Magnitud | Referencia de esta línea base |
|:---|---:|
| Claude por día (media de los últimos 7 días completos) | 5,17 USD |
| Proyección mensual de producción con ese ritmo (por 30 días) | 155 USD |
| Exa por día / por 30 días | 0,76 USD / 23 USD |
| Briefs por partido y día | 2,87 |
| Entradas idénticas pagadas dos veces (briefs) | 5,3 % |
| Candidatos con revisión de modelo / candidatos revisados por reglas | 32,7 % |
| Coste por candidato revisado por el modelo | 0,0508 USD |
| Veredicto final antes de T-15 | 100,00 % |
| Tokens leídos de caché / llamadas por Batch | 0 % / 0 % |

