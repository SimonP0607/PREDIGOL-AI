# API incidents — runbook

Written 2026-09-29. Each entry is a failure that has actually happened here, or one
the schema now refuses; the response is what to do, not what to feel.

## First principle

**An error from API-Football arrives inside HTTP 200**, in the `errors` object. A
response with `results: 0` and a populated `errors` is a refusal, not an empty day.
Anything that treats the two the same will eventually store an empty week as fact.

## Quota

| Symptom | Where to look | What to do |
|---|---|---|
| `QuotaExhaustedError` | `raw.provider_quota` (`quota_date`, `spent`, `budget`) | nothing: the guard worked. The backfill defers and says so in its report |
| Internal count disagrees with the provider's | `x-ratelimit-requests-remaining` in the client's logs vs `raw.provider_quota.spent` | record the drift; do not "correct" the counter to match. Both numbers are evidence |
| 429 | client retry log | the client backs off with jitter and honours `Retry-After`. Repeated 429s inside the budget mean the minute limit, not the daily one |

The budget is a guard, not a target. Raising it needs a demonstrated need, and the
live reserve is never inside it.

## The plan refuses something

| Symptom | Meaning | What to do |
|---|---|---|
| `errors.plan` on `/fixtures?ids=` | this plan does not allow batching | the probe records the refusal word for word and still asks `/leagues`. Detail then costs 4 requests per fixture instead of 1 per 20 — reprice before seeding |
| `errors.plan` on a date | the date is outside the plan's horizon | re-run `scripts.probe_windows --yes` and write the new horizon into `LIVE_DATA_RUNBOOK.md` with its date. **A window we did not observe stays lost** — it is not reconstructed later |
| A unit marked `refused` | the provider or the plan said no | it is **not** retried automatically. Asking again in a loop is how quota is spent on an answer we already have |

## The provider changed under us

| Symptom | Recorded as | What to do |
|---|---|---|
| A bet arrives under a different name | `PROVIDER_INCONSISTENCY` on `provider_market`, and the prices are **not** stored | check whether the id was renumbered. Update `PREMATCH_BETS` / `INPLAY_BETS`, add a test with the real payload shape, then re-run |
| A bet id we do not map | `UNKNOWN_PROVIDER_ENTITY`, plus a `market.provider_markets` row with `source = 'observed'` | nothing, unless we want that market. "Observed and not in the catalogue" is the signal that the catalogue moved |
| A statistic type with no column | `UNKNOWN_PROVIDER_ENTITY` on `team_statistics` | the value is in the raw payload. Add a column and replay from RAW — no request needed |
| A field disappears | rows stop being written for it; `values_are_possible` will not catch it | compare `raw.ingestion_payloads` bodies across dates. RAW is why this is answerable |

## Data looks wrong

| Symptom | Where to look |
|---|---|
| A statistic is NULL and the source did report it | `core.fixture_team_stats.dropped_fields` names the column; `audit.data_quality_issues` has the observed value |
| A line-up has fewer than 11 starters | `INCOMPLETE_LINEUP`. It is stored as received and **not** padded |
| A match will not settle | `picks.pick_results.review_reason`. For `AET`/`PEN` it is almost always the missing extra-time score |
| Detail appears to be missing | check `core.fixture_detail_coverage` **before** re-fetching. No row means never fetched; `block_present = false` means the provider does not publish it |
| A price series has a gap | `market.odds_snapshots` is append-only. A gap is a window we did not capture, and it stays a gap: **no backdating, no reconstruction** |

## Something is slow or stuck

| Symptom | What to do |
|---|---|
| A unit stuck in `running` | a process died. The resumable loop picks it up again; `started_at` says when it was claimed |
| The worker is not heartbeating | `raw.worker_heartbeat`. Docker restarts it; an open terminal is not part of the design |
| A long job was interrupted | it resumes. Every long path commits per unit or per payload — `reprocess_details`, `migration run`, the sweep |

## Restoring

`scripts.backup create --label why` before any schema migration, large ingestion or
destructive normalisation change. `scripts.backup verify <dir>` restores into a
scratch database and checks files, restore, tables, schema, raw store and lineage —
**six checks, because `pg_dump` exiting 0 proves nothing about what is inside.**

## What never to do

- Do not rewrite a timestamp to make a report tidy. The 36,599 rows dated after
  their payload are recorded, not corrected; the cause is fixed forward.
- Do not fill in a provider value that is missing or contradictory. Record it.
- Do not turn a penalty shoot-out into a 90-minute result.
- Do not re-request a dataset the provider has already declined to publish.
- Do not raise the daily budget to make a backfill fit.
