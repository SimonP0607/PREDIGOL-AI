# Live data — runbook

Written 2026-09-29. The horizons below are **measured on this account on that
date**, not taken from documentation. A capability claim without a date becomes a
permanent belief, which is how the Free plan's three-day result horizon went
unnoticed while eight fixtures we had prices for stayed permanently `NS`.

## What the provider can actually see (measured 2026-09-29, 18 requests)

| Question | Answer | How |
|---|---|---|
| `/fixtures?date=` horizon | **−365 to +90 days**, every offset tested returned a fixture list | `scripts.probe_windows --yes` |
| Pre-match prices exist from | **T-18.2 days** (26,194 min). Priced at 11.2 d and 18.2 d; **not** priced at 24.5 d or 32.2 d | same |
| `/odds/live` | **answers** — 1 fixture in play with prices | same |
| `/fixtures?ids=` detail blocks | all four, 20 fixtures per request | earlier probe |

So the documented 14-day odds window is a **floor**, and the real boundary sits
between 18.2 and 24.5 days. Nothing in the scheduler depends on the difference: the
furthest pre-match window is T-4320 min (3 days), well inside it.

Re-run the probe after any plan change. It writes every payload to the raw store,
so the answer is auditable rather than remembered.

## Capture cadence

`config` → `FBI_ODDS_PREMATCH_WINDOWS`, default `4320,2880,1440,720,360,180`:

| Window | Distance | Endpoint |
|---|---|---|
| 4320 | T-72 h | `/odds?fixture=` |
| 2880 | T-48 h | `/odds?fixture=` |
| 1440 | T-24 h | `/odds?fixture=` |
| 720 | T-12 h | `/odds?fixture=` |
| 360 | T-6 h | `/odds?fixture=` |
| 180 | T-3 h | `/odds?fixture=` |
| near-close | T-12 min (`FBI_ODDS_NEARCLOSE_WINDOW`, 5–15) | `/odds/live` |

`/odds` refreshes every 3 hours, so a window below 180 minutes returns the same row
and burns quota — the config validator refuses one.

## The one thing to know about live odds

**`/odds` and `/odds/live` number their bets differently.** In-play bet 4 is *Extra
Time Total Corners (3 Ways) (1st Half)*; in-play bet 5 is *Extra Time Double
Result*. The bet map is chosen by `source` (`prematch` → pre-match ids, `live` →
in-play ids) and the provider's own bet NAME is checked against the catalogue before
a price is accepted. A rename refuses the bet and records
`PROVIDER_INCONSISTENCY`, because a renumbering would relabel prices silently.

If a live capture suddenly stores nothing, look at `audit.data_quality_issues` for
`UNKNOWN_PROVIDER_ENTITY` on `provider_market`: the bet ids will be there, with the
names the provider sent.

## Near-close is not a closing line

`market.near_close_snapshots` is the last price we **managed** to capture, and the
schema makes the stronger claim unprovable by accident:

- `minutes_to_ko` records the real distance from kick-off;
- `is_validated_close` defaults to false and cannot be true without
  `close_validation_method`;
- there is no column or table named `closing_*` or `clv*` anywhere, enforced by a test.

Since revision 0026 it is also a **projection of the series, not a second
recording**: a trigger requires the exact snapshot to exist in
`market.odds_snapshots` and to agree on odds, `minutes_to_ko`, `source` and
`payload_hash`. A deferred constraint trigger refuses to delete a snapshot a
projection still names.

## Results

`/fixtures?date=` for the day, then again for the day before — extra time and
penalties can push a match past midnight. The result sync writes
`core.fixture_results` with `goals` (after extra time, penalties excluded) and, when
the provider gives it, `et_goals_*`.

**A match with status `AET` or `PEN` and no extra-time score is not settled.**
`reg_goals_*` is `goals − COALESCE(et_goals, 0)`, so with the extra-time score
missing it equals the after-extra-time score, and a 90-minute market settled on it
would count extra-time goals as regulation goals. `settle()` returns PENDING with a
reason and the sweep records `RESULT_UNRESOLVED`. Six fixtures are in this state.

Statuses and what they mean for settlement:

| Status | Settlement |
|---|---|
| `FT` | settles on the 90-minute score |
| `AET`, `PEN` | settles **only** with an extra-time score; otherwise `RESULT_UNRESOLVED` |
| `CANC` | void |
| `PST`, `SUSP`, `ABD`, `AWD`, `WO` | pending with the reason; void rules vary by book and are **not inferred** |

## Daily operation

```bash
python -m scripts.quality_sweep --apply        # nightly; 0 unless something needs a human
python -m scripts.migration gaps               # detail outstanding, priced; no request
python -m scripts.migration run --yes --max N  # spend at most N requests
python -m scripts.probe_windows --yes          # after a plan change only
python -m scripts.backup create --label why    # before a migration or a large ingestion
```

Nothing above needs an open terminal to survive: the worker runs in Docker with a
restart policy, and every long job commits per unit so an interruption resumes
rather than restarts.

## Budget

Internal guard **60,000/day** against the plan's 75,000. The backfill computes a
live reserve every run — one request per pre-match window per scheduled fixture in
the next 24 h, plus near-close, plus the standing syncs — and never spends it.
`LIVE PRIORITY > BACKFILL` is that reserve, not a convention.
