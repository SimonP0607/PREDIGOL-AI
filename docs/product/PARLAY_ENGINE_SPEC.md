# Parlay engine (GATE D)

PrediGol's daily and multi-day parlays as records: built once from the legs that are worth
combining, frozen, then followed to the end. Rule `parlay-v3`. Code:
`src/fbi/parlays/engine.py` (value gate, correlation guard), `src/fbi/parlays/persist.py`
(choice and lifecycle), `src/fbi/picks/product_settlement.py` (results); tables
`picks.parlays`, `picks.parlay_legs` (migration 0053). API: `GET /api/v1/daily` (fields
`daily_parlay`, `multiday_parlay`).

## 1. Kinds

| Kind | Window | Legs | Days |
|---|---|---|---|
| `daily` | the product day (midnight to midnight, America/Bogota) | 2 to 5 | one |
| `multiday` | the next 72 h from the moment it is built | 3 to 7 | at least two product days |

One of each per day and source (`qualified` for users, `evaluation` for the owner's preview,
as in `DAILY_PICKS_SPEC.md`).

## 2. Which legs may be combined

Every leg passes the same gate as a daily pick, at the price available when the parlay is
built (current price from >= 2 books, not an outlier, positive expected value, a measured
interval). Across legs (`fbi.parlays.engine.guard`):

* **one leg per match** - two selections on one match are dependent ("home" and "over 2.5"
  move together);
* **no team twice** - two matches of one team share its news, injuries and rotation;
* **no quarter lines** (.25 / .75) - a half-won leg has no clean meaning inside a parlay.

With distinct matches between distinct teams the legs are treated as independent and the
joint probability is the product. The guard is the correlation model: it removes the
dependence rather than estimating it.

## 3. How the legs are chosen

By **expected log growth** of a 1 % stake on the whole parlay, with each leg at its
**pessimistic** probability (the low end of the model's interval; a push counted as a loss):

1. Greedily add the leg that raises the parlay's growth most, up to the minimum number of
   legs. The day rule is honoured while choosing: once the slots left are only enough to
   reach the required number of days, the next leg must come from a day the parlay does not
   have yet.
2. The parlay is built only if that minimum already grows (> 0).
3. Beyond the minimum, a leg is added only while it still raises the growth, up to the
   maximum.

A long parlay of long shots does not survive this: each leg multiplies its uncertainty in,
and the growth turns down well before the leg limit. No parlay is ever padded to a size.

## 4. Lifecycle

| Status | Meaning |
|---|---|
| `BUILDING` | the day's parlay is being looked for: candidates exist, no combination grows yet |
| `READY` | built; legs, prices and probabilities frozen; no leg has kicked off |
| `ACTIVE` | at least one leg has kicked off |
| `WON` | every leg won |
| `LOST` | a leg lost (or half-lost), whatever the others are doing |
| `PARTIAL_VOID` | the others won and at least one leg was void or pushed: pays at the winning legs' odds |
| `VOID` | every leg void or pushed (stake back), **or** the day ended without a parlay being built (no legs, profit 0) |

A record past `BUILDING` is never rebuilt. When a parlay is built, its `rule_version` and its
window are those the legs were actually chosen with.

## 5. Frozen per leg

Price, bookmaker, capture instant, `p_model`, `p_low`, `p_push`, the market's fair
probability, expected value, and the gate's inputs (`inputs` JSON). Per parlay: combined
odds, the probability that every leg wins at the pessimistic end (`p_all_low`), and the
expected log growth.

## 6. First run (4 Oct 2026, rule v2)

The evaluation daily parlay was built with 5 legs at combined odds 101.17, `p_all_low` 0.093
(an implied return of 9.4 times the stake). Not credible, and for the reason given in
`DAILY_PICKS_SPEC.md` section 6: four of the five legs were Asian handicaps without a
measured interval, ranked as if certain. Rule v3 no longer ranks such legs and enforces the
multi-day rule while choosing. The v2 record stays as built (evaluation only, never shown
to a user). The qualified parlays are not built: no model version has qualified.

## 7. Tests

`tests/unit/test_daily_rules.py` (outcomes, quarter lines, multi-day day rule),
`tests/integration/test_daily_records.py` (growth-based choice, freeze, ACTIVE, LOST, a parlay
never built is VOID once its day is over).
