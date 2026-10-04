# Model-ready dataset (GATE C)

Which played matches a model may learn from, which it may be judged on against the market,
and which are kept out. Measured on 4 Oct 2026 (rule `historical-validation-v2`); recomputed
after every Elo refresh (6-hourly) and by `python -m scripts.validate_history`. Code:
`src/fbi/validation/historical.py`; tables `analytics.fixture_validation`,
`analytics.competition_data_scores`; view `analytics.model_ready_fixtures` (migration 0052).

## 1. Every finished match has one state

| State | Matches | Meaning |
|---|---:|---|
| HISTORICAL_APPROVED | 209,219 | passes every integrity rule, has an Elo rating, and its competition-season is MODEL_READY or PARTIAL |
| VALIDATED | 672 | passes every integrity rule; its competition-season is not fit for modelling (671), or it has no Elo rating (6) |
| QUARANTINED | 19 | fails an integrity rule: excluded from every model, every backtest and Elo-based input |
| INGESTED | 5 | stored, no usable result yet (extra-time matches without their 90-minute score) |

Integrity rules (a failure quarantines; every failed rule is named in `failed`, nothing is
deleted):

| Rule | Matches | |
|---|---:|---|
| `provider_duplicate` | 10 | the same pairing twice within 36 hours under two fixture ids (5 pairs, mostly club friendlies) |
| `halftime_exceeds_score` | 9 | more goals at half-time than at 90 minutes |
| `no_regulation_score` | 0 | an extra-time result stored without its 90-minute score |
| `finished_in_future` | 0 | finished with a kick-off still to come |

v1 also quarantined 241 penalty decisions after an unlevel score; they were second legs of
two-legged ties, level on aggregate. That rule was wrong and is gone (v2).

## 2. Every competition-season has a data score and a class

Components are shares of its finished matches: results, integrity, team statistics (shots),
line-ups, a market price (captured before kick-off, read after it from the provider's final
pre-match prices, or from football-data.co.uk) and an Elo rating. Score = 0.35 results +
0.15 integrity + 0.15 statistics + 0.05 line-ups + 0.20 prices + 0.10 Elo.

| Class | Seasons | Finished matches | Allows | Requires |
|---|---:|---:|---|---|
| MODEL_READY | 15 | 5,341 | training **and** judging against the market | results >= 95%, integrity >= 98%, prices >= 60%, Elo >= 95%, >= 50 matches |
| PARTIAL | 861 | 203,903 | training; not enough prices to judge against the market | results >= 95%, integrity >= 98%, >= 30 matches |
| PRODUCT_ONLY | 21 | 469 | shown in the product, not learned from | results >= 80% |
| INSUFFICIENT | 93 | 202 | nothing | fewer than 10 finished matches, or results < 80% |

The 15 MODEL_READY seasons are the five big European leagues 2022-2024 (Premier League,
La Liga, Bundesliga, Serie A, Ligue 1), whose prices come from football-data.co.uk. Every
other season lacks prices: our own capture began on 25 Sep 2026, so current seasons are
priced at 0-56% so far (UEFA Nations League 56%, the highest).

## 3. The approved population

`analytics.model_ready_fixtures`: 209,219 matches, 113 competitions, 876 competition-seasons,
12 Mar 2015 - 4 Oct 2026.

| Segment | Approved | of which MODEL_READY |
|---|---:|---:|
| Other leagues | 143,180 | 0 |
| Domestic cups | 17,100 | 0 |
| Top leagues | 14,561 | 5,341 |
| Continental club | 13,973 | 0 |
| Club friendlies | 7,594 | 0 |
| Women | 7,437 | 0 |
| National teams | 5,024 | 0 |
| Youth | 350 | 0 |

Segments (`fbi.catalog.segments`): youth and women first, then national teams, club
friendlies, continental club competitions, domestic cups, top leagues (tier 1) and other
leagues. Women's and youth football are never pooled with the senior men's game.

## 4. How models use it

* **Training**: approved matches only (MODEL_READY and PARTIAL seasons). QUARANTINED and
  INGESTED matches never enter a feature, a fit or a rating.
* **Judging against the market** (log loss / Brier / ECE against the de-vigged price, CLV):
  matches with a price only - today the MODEL_READY seasons; from now on, every played match
  the provider prices, through the final pre-match prices read after each match.
* **No future data**: every feature is computed from data stamped before the match's
  `data_cutoff` (kick-off for training rows; the prediction instant in production) - Elo
  `rating_before`, league tables taken before kick-off, prices captured before kick-off. The
  final pre-match prices are read after kick-off and are used only to judge, never as an input.
* **Segments are evaluated apart**: a model is promoted per market and segment, never on a
  pooled number that a large segment dominates.

## 5. Known limits (and what removes them)

| Limit | Effect | Remedy |
|---|---|---|
| Prices for history exist only for the big-5 leagues 2022-24 | 15 seasons can judge a model against the market | the final pre-match prices, from 25 Sep 2026 on, for every priced league; more football-data.co.uk seasons would need the owner's decision on its terms |
| The Elo walk still reads the 19 quarantined results | a duplicate counts twice in two teams' ratings | GATE E: the Elo rebuild reads approved and validated results only |
| A season's class is recomputed, not frozen | a backtest run today and next month may read different populations | every backtest records the rule version and the run instant; GATE G freezes the population per run |

## 6. Re-running

```
python -m scripts.validate_history          # ~5 s, no provider request
```

The worker runs it right after each Elo refresh; the Admin Console shows it under
Data truth -> Validation (`GET /api/v1/admin/data/validation`, `/validation/competitions`,
`/validation/quarantine`).
