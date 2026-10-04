# A user's picks, parlays and history (GATE D)

What a user keeps: the selections they saved, the parlays they built, and how it all went
next to what PrediGol chose. Code: `src/fbi/userdata/records.py` (rules, writes, history),
`src/fbi/userdata/db.py` (the only writable connection besides auth),
`src/fbi/api/routers/records.py`; tables `picks.user_picks`, `picks.user_parlays`,
`picks.user_parlay_legs` (migration 0053).

| Endpoint | |
|---|---|
| `GET /api/v1/me/picks[?status=open\|settled]` | the user's saved picks, newest match first |
| `POST /api/v1/me/picks` | save one (`fixture_id`, `market_key`, `selection`, `line`, optional `pick_id`, optional `user_odds`) |
| `DELETE /api/v1/me/picks/{id}` | remove one, only before its match starts |
| `POST /api/v1/me/parlays/validate` | check a parlay against the rules without storing it |
| `GET` / `POST /api/v1/me/parlays` | the user's parlays / build one |
| `GET /api/v1/me/history?period=today\|7d\|30d\|all` | the four groups below |

Every write needs the same-site header (`x-requested-with: predigol`) and touches only the
signed-in user's rows; another user's id gets nothing (no existence leak).

## 1. Saving a pick

A saved pick is a **snapshot** of what we showed at that moment: the best price for that
selection (bookmaker, capture instant, number of books, the market's fair probability) and,
when it was one of PrediGol's picks, the model's numbers (model, `p_model`, `p_low`, EV).

* `origin` is `predigol_pick` (saved from a PrediGol pick: `pick_id` set) or `market` (saved
  from the match's odds).
* A user may add the price they actually got at their own bookmaker (`user_odds`). Settlement
  and profit use that price when given, ours otherwise; with neither, the pick is settled
  without a profit figure.
* A user cannot save a shadow pick as PrediGol's (`unknown_pick`). The owner can, from the
  preview.
* One save per selection (`already_saved`, 409). Only a match still to be played
  (`started`). Only selections we settle (`invalid_selection`).
* Removal only before kick-off; after it, the pick is history.

## 2. Building a parlay

Validated before it is stored (`POST /me/parlays/validate` gives the same answer without
storing):

| Check | Code | Effect |
|---|---|---|
| 2 to 10 legs | `leg_count` | error |
| a selection we settle | `invalid_selection` | error |
| no quarter lines | `quarter_line` | error |
| the match exists and is still to start | `unknown_fixture`, `started` | error |
| one leg per match | `same_fixture` | error |
| a team in two legs | `shared_team` | warning: allowed, the user is told the legs are linked |
| no current price for a leg | `no_price` | warning: the parlay has no combined odds until the user gives one |

Each leg keeps the price we showed (or the user's) and a snapshot. The parlay follows the
same lifecycle and settlement as PrediGol's (`PARLAY_ENGINE_SPEC.md` section 4), from
`READY`.

## 3. History

Four groups, over **today**, the **last 7 days**, the **last 30 days** or **everything**, by
the day the match kicks off **in the user's own time zone** (a parlay by its first leg's
kick-off):

| Group | Records |
|---|---|
| `predigol_picks` | the daily set's items (the qualified set; the owner's preview reads the evaluation set alone, never both) |
| `my_picks` | the user's saved picks |
| `predigol_parlays` | PrediGol's daily and multi-day parlays that were built |
| `my_parlays` | the user's parlays |

Per group: total, pending, won, lost, push, void, **hit rate** (won / (won + lost)), units
staked (one per settled, priced, non-void record), **profit** and **ROI**. A parlay that
pays after a void leg counts as won. An empty period answers `EMPTY` with the zeros, not an
error.

## 4. What the user sees

* PrediGol's pick, what the user saved, and the result are labelled apart: **PrediGol Pick**,
  **Guardado por mí**, **Resultado**.
* Profit is in units of one stake, never in money: PrediGol holds no balance and takes no
  bets.
* Nothing here promises a return; a history with losses shows losses.

## 5. Tests

`tests/integration/test_daily_records.py` (snapshot, user price, shadow refusal, started,
validation codes, settlement, history totals and ROI, preview history),
`tests/integration/test_records_api.py` (HTTP flow, 409/422/403, same-site header, another
user's rows), `tests/unit/test_daily_rules.py` (periods end at the user's midnight).
