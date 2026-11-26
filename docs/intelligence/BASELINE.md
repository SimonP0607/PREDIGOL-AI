# Línea base de Intelligence (RP-0.1)

<!-- Generado por `python -m scripts.intel_baseline_report --doc` desde `docs/intelligence/baseline/baseline-v1.json`. No lo edites a mano. -->

Los 22 indicadores de la sección 23 del Plan Maestro, medidos en producción en solo lectura al aprobarse el plan, antes de
cambiar nada. Es el punto contra el que se mide toda mejora o empeoramiento posterior: ninguna pieza se da por buena con una comparación que no
use estas definiciones.

**Cómo se midió.** `backend/scripts/intel_baseline.sql` corre dentro de una transacción de solo lectura con límite de tiempo
(`intel_baseline.sh`); cada cifra está acotada por el corte (`cut_utc`), así que repetir la medición con el mismo corte da la misma huella
sha256 en cada sección (comprobado con dos ejecuciones; las secciones «vivas» —latido del trabajador— se dejan fuera de esa comprobación).
Las competiciones de la base fija son las seguidas y creadas antes del 24-nov-2026 (`base_before_utc`), para que las que se añadan después no
muevan la línea base.

**Qué no está medido, y por qué.** I6 (coherencia matemática) lo crea la pieza RP-2.2; I14 (afirmaciones sin apoyo) lo crea RP-7.4 con su muestra
de 50 textos; I22 (latencia) solo se mide con `baseline_snapshot` una vez desplegado este cambio. El indicador I9 cuenta todos los partidos de la base,
porque la lista de competiciones prioritarias (D2) se aplica después, en RP-5.4.

**Diferencias de definición con la auditoría.** No se reproducen al dígito las cifras de 1X2 de la auditoría (3.098 partidos, +0,0326 bruta,
+0,0075 mostrada) porque la consulta de entonces no se guardó; esta definición queda fijada y es la que se usará en adelante: 3.165 partidos,
+0,0378 bruta y +0,0113 mostrada.

Versión de la definición: `intel-baseline-v1`. Código: `527d04d8`. Migración: `0177`. Corte: `2026-11-26T03:00:00Z`.

## I1 · Predicción (`i01_i02_forecast_vs_market`)

| matches | raw_minus_market | raw_se | shown_minus_market | shown_se |
|---|---|---|---|---|
| 3165 | 0.0378 | 0.0041 | 0.0113 | 0.0020 |

## I2 · Predicción (`i01_i02_forecast_vs_market`)

| matches | raw_minus_market | raw_se | shown_minus_market | shown_se |
|---|---|---|---|---|
| 3165 | 0.0378 | 0.0041 | 0.0113 | 0.0020 |

## I3 · Calibración (`i03_calibration_by_family`)

| family | freq | gap_points | layer | mean_p | n |
|---|---|---|---|---|---|
| cards | 0.4228 | 14.37 | decision-fam-v1 | 0.5665 | 149 |
| corners | 0.4088 | 8.44 | decision-fam-v1 | 0.4932 | 1688 |
| goals_halves | 0.3577 | 7.49 | decision-fam-v1 | 0.4326 | 4811 |
| core | 0.4038 | -1.43 | decision-v1 | 0.3894 | 7928 |
| core | 0.3884 | -1.10 | decision-v2 | 0.3774 | 6362 |

## I4 · Por mercado (`i04_loss_vs_market_by_family`)

| family | layer | loss_minus_market | n | se |
|---|---|---|---|---|
| cards | decision-fam-v1 | 0.0388 | 149 | 0.0161 |
| corners | decision-fam-v1 | 0.0192 | 1688 | 0.0041 |
| goals_halves | decision-fam-v1 | 0.0199 | 4811 | 0.0025 |
| core | decision-v1 | 0.0013 | 7928 | 0.0005 |
| core | decision-v2 | 0.0042 | 6324 | 0.0013 |

## I5 · Por competición (`i05_by_competition_level`)

67 filas (todas en el JSON); las primeras 12:

| level | market_key | model_name | n | skill | skill_high | skill_low | source | verdict |
|---|---|---|---|---|---|---|---|---|
| A | 1X2 | elo_ologit | 1728 | -0.0637 | -0.0432 | -0.0824 | prediction | apta |
| A | 1X2 | elo_ologit | 1728 | -0.0904 | -0.0682 | -0.1151 | forecast | apta |
| A | 1X2 | dixon_coles | 9 | -0.1782 | 0.2496 | -0.5697 | forecast | insuficiente |
| A | 1X2 | poisson | 1736 | -0.0653 | -0.0449 | -0.0842 | prediction | apta |
| A | 1X2 | dixon_coles | 1733 | -0.0638 | -0.0429 | -0.0827 | prediction | apta |
| B | 1X2 | elo_ologit | 347 | -0.0675 | -0.0298 | -0.1036 | prediction | apta |
| B | 1X2 | poisson | 354 | -0.0532 | -0.0148 | -0.0904 | prediction | apta |
| B | 1X2 | dixon_coles | 8 | -0.1437 | -0.0143 | -0.3339 | forecast | insuficiente |
| B | 1X2 | elo_ologit | 341 | -0.0688 | -0.0311 | -0.1078 | forecast | apta |
| B | 1X2 | dixon_coles | 354 | -0.0513 | -0.0110 | -0.0906 | prediction | apta |
| B* | 1X2 | dixon_coles | 8 | 0.2859 | 0.4836 | 0.1805 | prediction | insuficiente |
| B* | 1X2 | elo_ologit | 8 | 0.3297 | 0.8043 | 0.1655 | prediction | insuficiente |

## I6 · Coherencia (`i06_coherence`)

| note | state |
|---|---|
| RP-2.2 adds the nightly audit | not_measured |

## I7 · Cierre (`i07_close_minutes`)

| matches | median_min | p10_min | p90_min | within_30_min |
|---|---|---|---|---|
| 2676 | 177.1 | 175.0 | 179.7 | 2 |

## I8 · Investigación (`i08_research_coverage_played`)

| matches | pct | with_web_search |
|---|---|---|
| 698 | 39.1 | 273 |

## I9 · Investigación (`i09_researched_before_match_day`)

| matches | searched_before_day |
|---|---|
| 753 | 0 |

## I10 · Hechos (`i10_facts_per_researched_match`)

| confirmed_facts | confirmed_per_match | researched_matches | web_facts |
|---|---|---|---|
| 869 | 1.74 | 500 | 7743 |

## I11 · Hechos (`i11_unknown_tier_share`)

| facts | pct | tier |
|---|---|---|
| 7754 | 63.9 | unknown |
| 2608 | 21.5 | media |
| 1231 | 10.1 | aggregator |
| 360 | 3.0 | club |
| 150 | 1.2 | competition |
| 37 | 0.3 | official |

## I12 · Noticias (`i12_stories_with_own_text`)

| evidence_with_item | item_domains | items | stories | stories_with_text |
|---|---|---|---|---|
| 0 | 2 | 651 | 565 | 0 |

## I13 · Texto (`i13_complete_texts`)

| n | pct_of_total | route | status |
|---|---|---|---|
| 1108 | 50.5 | batch | invalid_output |
| 479 | 21.8 | batch | partial |
| 426 | 19.4 | none | ok |
| 141 | 6.4 | none | partial |
| 40 | 1.8 | none | abstained |
| 2 | 0.1 | batch | ok |

## I14 · Texto (`i14_unsupported_claims`)

| note | state |
|---|---|
| RP-7.4 defines the 50-text sample | not_measured |

## I15 · Coste (`i15_cost_per_analyzed_match`)

| cost_usd | cost_without_fixture | fixtures | usd_per_fixture |
|---|---|---|---|
| 47.8559 | 0.5933 | 669 | 0.0715 |

## I16 · Coste (`i16_cost_per_confirmed_fact`)

| confirmed_web_facts | search_extraction_usd |
|---|---|
| 601 | 10.3294 |

## I17 · Coste (`i17_review_share_of_spend`)

| calls | cost_usd | pct | purpose |
|---|---|---|---|
| 866 | 26.2309 | 54.8 | pick_review |
| 638 | 9.1200 | 19.1 | web_search |
| 3245 | 7.3039 | 15.3 | match_brief |
| 807 | 2.1030 | 4.4 | other |
| 1824 | 1.2094 | 2.5 | evidence_extraction |
| 426 | 1.1904 | 2.5 | match_analysis |
| 7 | 0.3851 | 0.8 | pattern_review |
| 103 | 0.2231 | 0.5 | postmortem |
| 7 | 0.0901 | 0.2 | learning |

## I18 · Aprendizaje (`i18_hypotheses`)

| by_ai | n | status |
|---|---|---|
| 84 | 96 | PROPOSED |
| 0 | 7 | ACCEPTED |
| 1 | 2 | SHADOW |
| 2 | 2 | INVESTIGATING |

## I19 · Aprendizaje (`i19_experiments_since_4_oct`)

| experiments_total | last_started | since_5_oct | since_5_oct_with_gate |
|---|---|---|---|
| 65 | 2026-10-04 11:15:58.440138+00 | 0 | 0 |

## I20 · Operación (`i20_runs_by_status_7d`)

| runs | status |
|---|---|
| 38279 | completed |
| 118 | aborted |
| 71 | interrupted |
| 33 | partial |
| 8 | failed |

## I21 · Parlays (`i21_parlays_30d`)

| calibration_error | mean_legs | mean_odds | mean_p_joint | parlays |
|---|---|---|---|---|
| not_measured | 1.58 | 5.75 | 0.2611 | 24 |

## I22 · Operación (`i22_latency`)

| note | state |
|---|---|
| baseline_snapshot.py manifest timings_ms | measured_outside_sql |
