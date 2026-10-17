# Daily picks (GATE D)

What PrediGol chooses for a day, as a record: chosen progressively, frozen when chosen, kept
after kick-off, settled after the match. Rule `daily-set-v2`. Code:
`src/fbi/picks/daily.py` (selection), `src/fbi/picks/product_settlement.py` (results),
`src/fbi/api/services/records.py` (read); tables `picks.daily_sets`,
`picks.daily_set_items` (migration 0053). API: `GET /api/v1/daily[?day=YYYY-MM-DD]`.

Before GATE D the picks page recomputed itself on every request from the picks whose matches
were still ahead: a pick disappeared at kick-off, nothing was settled, nothing could be
counted. That is gone.

## 1. The product day

Midnight to midnight in **America/Bogota**, where the users are. A match belongs to the day
its kick-off falls on in Bogota (a 22:30 kick-off in Bogota on 1 Aug is a 1 Aug pick even
though it is 2 Aug in UTC).

## 2. How a pick enters the day

Every pipeline run (every 30 min and right after each price capture, while the worker runs) looks
at the next 24 hours:

| Step | Rule |
|---|---|
| Window | the match kicks off within 24 h and at least 10 min from now |
| Stage | the tightest reached: **T-24h**, **T-12h**, **T-6h** or **T-3h** (stored on the item) |
| Value gate | `fbi.parlays.engine.assess` at the price available **now**: a price no older than 3 h, from >= 2 bookmakers, not an outlier (> 25 % above the de-vigged consensus), expected value > 0 at that price |
| Interval | the probability must have a measured interval; without one there is no pessimistic end and the pick is **not ranked** |
| Ranking | expected log growth of a 1 % stake at the **pessimistic** probability `p_low` (low end of the model's interval); must be > 0 |
| One per match | the best-ranked selection of a match; a match already in the set is not added twice |
| Size | **up to five**. Never padded: a day with two picks worth taking has two, a day with none has none |

The stage records how far ahead the pick was taken. A pick taken at T-24h is not revisited at
T-12h: the set only grows, in rank order, until it has five.

## 3. What is frozen

When an item enters the set, the record holds, and never changes: the price and its
bookmaker and capture instant, `p_model`, `p_low`, `p_push`, the market's fair probability,
the expected value, the model version, the stage, the instant of selection, and the gate's
inputs and limits (`inputs` JSON: rule version, source, model, pick status, number of
bookmakers, probability edge, growth at 1 %, kick-off). Later prices move; the record does
not. A database CHECK keeps `price_at <= selected_at` (no price from the future).

## 4. Two sets per day, never mixed

| Source | Built from | Who sees it |
|---|---|---|
| `qualified` | picks whose model version beat the de-vigged market in its own walk-forward backtest | every user (`GET /daily`) |
| `evaluation` | shadow picks too | the owner only (`GET /daily?preview=shadow`, `Permission.SHADOW_PREVIEW`), labelled **Modo de evaluación** |

While no model version has qualified, the qualified set stays empty and the board says why
(`reason: no_qualified_picks`). It is never filled from the evaluation set.

## 5. Lifecycle and settlement

| Record | States |
|---|---|
| set | `BUILDING` (its day is today or ahead) -> `COMPLETE` (the day is over) -> `SETTLED` (no item pending) |
| item | `PENDING` -> `WIN` / `LOSS` / `PUSH` / `VOID` / `HALF_WIN` / `HALF_LOSS` |

Items settle exactly as picks do (`fbi.picks.settlement`): the 90-minute score; quarter lines
as two halves; a cancelled match void; postponed, abandoned or awarded matches stay
`PENDING` for a human. Profit is per unit staked, at the **frozen** price.

## 6. First run (4 Oct 2026, rule v1)

No model version is qualified, so the qualified set for 4 Oct is empty. The evaluation set
filled five items at 09:14 UTC: Asian handicaps, a double chance and an Over 4.5 on UEFA and
CONCACAF Nations League and women's league matches, at prices 4.00-5.00, with model
probabilities 1.6-3.1 times the market's fair probability (e.g. Netherlands-Serbia, AH Away
+0.75 at 4.50: model 0.584, market 0.190).

That is not an edge; it is what the run exposed:

* **None of the five had a measured interval.** Rule v1 let `p_model` stand in for `p_low`,
  so the least-measured probabilities looked the firmest. Rule v2 does not rank them.
  The five v1 records stay as chosen (`inputs.rule_version = daily-set-v1`): a record is
  never rewritten.
* The models disagree with the market most on national teams and women's leagues, where
  their data are thinnest. Restricting picks to competitions the model has been validated
  on, and calibrated intervals for every market, are GATE E-G work
  (`docs/research/MODEL_RESEARCH_V2_2026.md`), not threshold changes here.

## 7. Tests

`tests/unit/test_daily_rules.py` (stages, Bogota day, pessimistic growth, no interval no
rank), `tests/integration/test_daily_records.py` (ranking, freezing, idempotence, settlement
at the frozen price), `tests/integration/test_records_api.py` (board, preview permission).
