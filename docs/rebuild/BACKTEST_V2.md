# Backtest V2 — champion / challenger on the validated history (GATE G)

*Written 4 October 2026 from the stored runs `research-v2-2024-20261004T100808Z` and
`research-v2-2024-20261004T102001Z` (both `run_label = RESEARCH_V2`) and the read-only audit of
10:30 UTC. Data as of 04 Oct 2026 02:00 UTC. Nothing in this gate changes a pick rule or promotes
a model.*

## 1. What changed from the legacy backtests

| | Legacy runs (`LEGACY_RESEARCH_RUN`) | Backtest V2 (`RESEARCH_V2`) |
|---|---|---|
| History | every finished fixture | only fixtures the historical validation did not quarantine (`fv2.1.0`, `docs/rebuild/MODEL_READY_DATASET.md`) |
| Competitions | the five leagues, any season | leagues whose validation **and** test seasons are `MODEL_READY` (results, integrity, Elo and market prices) |
| Market baseline | one baseline per comparison | **E1**: every de-vigged baseline scored on the fixtures *all* of them priced; the lowest log loss is the CHAMPION |
| Comparison sample | each model on its own matched subset | paired: model and champion on the fixtures both priced |
| Interval | per-match bootstrap | block bootstrap by match day (2,000 draws) + Diebold–Mariano (Newey–West, HLN) |
| Blend | — | **E2**: logarithmic opinion pool, weight fitted on the validation season, applied unchanged to the test season; test-season weight with a match-day bootstrap interval |
| Models | base rates, Poisson, Dixon–Coles, Elo ordered logit, multinomial logit | the same + **E5** gradient-boosted trees without / with the pre-closing market as an input |
| Outcome | a table | a **role** per model with its evidence, stored per experiment (`analytics.experiments.role`, `role_reason`, `segment`, `data_as_of`) |
| Picks | realised ROI | **E0**: realised = price paid + market movement + luck, standard errors clustered by match |
| Live check | — | **prospective**: the forecasts stored before kick-off since 25 Sep 2026 vs the closing consensus, per segment |

The legacy runs are kept and labelled (migration 0054); the admin page lists them next to V2.

## 2. Protocol (fixed before the run)

* Walk-forward: models refit every match day (trees every 30 days) using only matches that
  kicked off before the forecast's data cut-off; hyper-parameters chosen on the validation
  season (2023/24) only; scored once on the test season (2024/25).
* Competitions: Premier League, Serie A, La Liga, Bundesliga, Ligue 1 — the only seasons with
  historical closing prices to judge a model against. 1,756 test fixtures, dataset hash
  `92ee9e97373dff22…`.
* Metric: 1X2 log loss (ranking); Brier, ECE and accuracy reported, accuracy never used to rank.
* Roles (`fbi/research/roles.py`):
  * **CHAMPION** — the market forecast with the lowest log loss on the common fixtures.
  * **CHALLENGER** — beats the champion with the whole 95 % interval below zero, *or* its
    test-season blend weight is above zero *and* the validation-fitted blend beats the champion.
    Waits for an explicit promotion; never promoted automatically.
  * **REJECTED** — worse than the champion with the interval above zero *and* adds nothing in a
    blend. Kept and shown: a losing model is a result.
  * **RESEARCH** — the evidence cannot tell.
* Prospective segments are judged only with ≥ 50 matches on ≥ 5 match days; below that they are
  reported, not judged.

## 3. Results

### E1 — the market champion (1,751 fixtures every baseline priced)

| Baseline | Log loss | vs champion |
|---|---:|---:|
| `pinnacle/closing/power` **CHAMPION** | 0.95967 | — |
| `AVG/closing/shin` | 0.95967 | +0.00000 |
| `pinnacle/closing/shin` | 0.95977 | +0.00010 |
| `pinnacle/closing/proportional` | 0.96014 | +0.00047 |
| `bet365/closing/shin` | 0.96068 | +0.00101 |
| `pinnacle/pre_closing/shin` | 0.96248 | +0.00281 |
| `AVG/pre_closing/shin` | 0.96287 | +0.00320 |

The de-vig method matters little (≤ 0.0005); the timing matters more (pre-closing is 0.003
worse than closing).

### Models against the champion (1X2, test season)

| Model | Predicted | Log loss | vs champion [95 %] | ECE | Blend weight *w* (test) [95 %] | Role |
|---|---:|---:|---|---:|---|---|
| Multinomial logit | 1756 | 0.98176 | +0.0210 [+0.0127, +0.0290] | 0.0125 | −0.206 [−0.467, +0.060] | REJECTED |
| Elo ordered logit | 1756 | 0.98619 | +0.0256 [+0.0177, +0.0336] | 0.0087 | −0.266 [−0.530, −0.034] | REJECTED |
| Poisson | 1748 | 0.98708 | +0.0261 [+0.0170, +0.0353] | 0.0163 | −0.213 [−0.454, +0.019] | REJECTED |
| Dixon–Coles | 1748 | 0.98708 | +0.0262 [+0.0173, +0.0356] | 0.0068 | −0.224 [−0.480, +0.012] | REJECTED |
| Gradient-boosted trees | 1756 | 0.99663 | +0.0358 [+0.0217, +0.0498] | 0.0272 | +0.056 [−0.118, +0.228] | REJECTED |
| Trees + pre-closing market | 1751 | 1.02370 | +0.0640 [+0.0437, +0.0836] | 0.0541 | +0.052 [−0.065, +0.187] | REJECTED |
| League base rates | 1756 | 1.07975 | +0.1193 [+0.1016, +0.1379] | 0.0138 | −0.102 [−0.210, +0.019] | REJECTED |

* Every model is worse than the closing market by 0.021–0.119 nats, with intervals far from zero.
* No blend weight is reliably above zero. Elo's is reliably **below** zero: where Elo disagrees
  with the market, the outcome sides with the market — more strongly than the market itself.
  Against the pre-closing price (what a pick would have taken) the four classical models' weights
  are all below zero — Poisson −0.308 [−0.579, −0.039], Dixon–Coles −0.296 [−0.558, −0.051] and
  Elo −0.359 [−0.618, −0.106] reliably so.
* The trees do not help, and adding the market as an input makes them worse (overfitting:
  ECE 0.054).
* Over/Under 2.5 and BTTS (goal models only): Poisson log loss 0.6795 and 0.6907, Dixon–Coles
  0.6796 and 0.6901 — no historical totals prices are stored, so there is no market comparison
  for these markets yet.

### E0 — where the shadow picks' −22 % came from (925 settled picks, 128 matches)

realised ROI = EV at the pick (price paid against the market's view then) + movement (how that
view changed until our last capture) + luck (realised − EV at the close).

| | Value |
|---|---|
| Realised ROI | −22.3 % ± 8.7 % |
| Claimed EV (the model's) | +23.9 % |
| EV at the pick | **−4.7 % ± 0.2 %** |
| Movement until our last capture | +0.0 % ± 0.2 % |
| EV at the close | −4.7 % ± 0.3 % |
| Luck | −17.6 %; z = −2.1 with the empirical error (8.6 %), −1.0 with the conservative error under the closing prices (17.5 %) |

By odds: every bucket has a negative EV at the pick (−3.5 % at 1.0–1.6 to −7.7 % at 5.0+); by
market: 1X2 −4.0 %, AH −4.6 %, DC −4.4 %, OU −5.3 %, BTTS −5.9 %; by model: Elo −3.6 %,
Poisson −5.0 %, Dixon–Coles −5.0 %.

Reading: **the value gate selected bets that were already losing bets by the market's own
de-vigged price at the moment they were taken.** The model's +24 % "edge" was disagreement with
the market, and the market did not move towards the model afterwards (movement ≈ 0). The
expected return of these picks was about −4.7 %; the remaining −17.6 % is within 1–2 standard
errors of luck. The earlier statement that −22 % was "3–7 standard errors" from break-even
(`docs/research/MODEL_RESEARCH_V2_2026.md` §2) is corrected in §9 of that document: break-even was
the wrong null, and picks on one match are not independent.

Limits: our "close" is the last consensus we captured, a median **12 h** before kick-off — not the
final price, so movement here is not true closing-line value. The consensus comes from the
bookmakers API-Football covers, not from Colombian local books
(`docs/research/ODDS_PROVIDER_GAP_ANALYSIS_2026.md`).

### Prospective — forecasts stored before kick-off, 25 Sep – 4 Oct 2026

680 matches played and validated; 181 with a closing 1X2 consensus from 2+ books.

| Segment | Model | Matches | Model LL | Close LL | Difference [95 %] | Reading |
|---|---|---:|---:|---:|---|---|
| all | Elo ordered logit | 157 | 0.9792 | 0.9455 | +0.0337 [+0.0137, +0.0727] | REJECTED |
| all | Poisson | 130 | 1.0377 | 0.9750 | +0.0627 [+0.0371, +0.1506] | REJECTED |
| all | Dixon–Coles | 128 | 1.0421 | 0.9821 | +0.0600 [−0.0057, +0.1329] | RESEARCH |
| other leagues | Elo ordered logit | 50 | 1.0176 | 1.0218 | −0.0042 [−0.0377, +0.1752] | RESEARCH |

Every other segment (domestic cups, national teams, women, friendlies) has fewer than 50 matches
and is not judged. The prospective result agrees with the backtest: no model beats the market.

## 4. Decision

* **Champion**: the de-vigged market (`pinnacle/closing/power` historically; the live Shin
  consensus prospectively).
* **Challengers**: none. **Qualified models: 0. Qualified picks: 0.** Picks stay in shadow
  ("Modo de evaluación", owner only). No threshold was changed to improve these numbers.
* The goal models stay in service where they are needed — pricing fixtures without a market and
  deriving consistent O/U, BTTS, AH and DC probabilities from one score matrix — with REJECTED
  meaning "does not beat the market", not "deleted".

## 5. How to run and where results live

```
python -m scripts.research_v2                # dry run: report written, nothing stored
python -m scripts.research_v2 --apply        # store (refuses on uncommitted code)
python -m scripts.research_v2 --audit-only   # E0 + prospective, read only, seconds
```

* Session: `analytics.backtest_sessions` (`run_label`), predictions in `models.predictions` with
  `backtest_session_id`.
* One experiment per model, per market baseline, the prospective evaluation and the audit:
  `analytics.experiments` with `run_label`, `role`, `role_reason`, `segment`, `data_as_of`
  (`role` is required for every completed V2 experiment except the audit — a CHECK constraint).
* Reports: `data/reports/research-v2-<season>-<stamp>.{md,json}`.
* Admin: `GET /api/v1/admin/research/v2` and *Admin → Modelos → Investigación V2*.

## 6. Next experiments (become hypotheses in the evolution loop, `docs/rebuild/EVOLUTION_LOOP.md`)

1. Price-only selection (research): a candidate only where the best available price beats the
   de-vigged consensus (EV at the pick > 0 by the market's own view), the model as a sanity
   check — the one route E0 says can have a non-negative expectation.
2. Capture the consensus close to kick-off for fixtures with picks, so that movement measures
   closing-line value.
3. Totals prices in the historical dataset, to judge O/U and BTTS against a market.
4. New information rather than new algorithms (E4 shots/xG ratings, E6 line-ups), as the
   literature predicts.
5. Let the prospective window grow: segments are judged at ≥ 50 matches on ≥ 5 days.
