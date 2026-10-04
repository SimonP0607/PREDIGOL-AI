# Data truth audit (GATE A)

What the provider says today against what the database holds, field by field; what was
wrong; what was fixed; what remains. 4 October 2026, machine `mila`, backend from `b067d24`
(audit #1) to `9172791`+ (audit #2).

## How it is measured

`python -m scripts.truth_audit` (package `fbi.truth`, ~375 provider requests, 2–3 minutes):

* **Asks the provider** — `/leagues` (every competition, season and coverage flag, 1
  request); the **whole fixture list of every current season** (124) plus 20 sampled past
  seasons; 83 sampled fixtures in full detail (`/fixtures?ids=`: status, score, events,
  line-ups, team and player statistics); every current league table (72); 48 teams, 48
  players, ~20 coaches, 12 squads; injuries and prices of 24 upcoming fixtures; the bookmaker
  list.
* The sample is **stratified by segment** (`fbi.catalog.segments`: top leagues, other leagues,
  domestic cups, continental club competitions, club friendlies, national teams, women,
  youth) and by time (played in the last 7 days, upcoming in the next 7, past seasons), with a
  recorded seed so a run can be repeated on the same rows.
* **Reads the provider's JSON directly**, not through the ingestion parsers, so a parser defect
  cannot agree with itself (that is how the `Canc` defect hid).
* **Checks the database against itself** (zero requests): status spelling and groups, results
  without a finish and the reverse, score parts, stale and stuck fixtures, duplicate pairings,
  pre-match prices captured after kick-off, table staleness, Elo coverage, player profiles.
* Measures **freshness** (FRESH / STALE / UNKNOWN / UNAVAILABLE per dataset, against service
  levels taken from the provider's own update cadence — `DATA_VALIDATION_RULES.md` §4) and the
  **MODEL_DATA_GATE**.
* Writes `audit.truth_runs` / `audit.truth_findings`, a report folder
  `data/truth/<stamp>-truth-<id>/` and the Admin Console page **Sistema → Verdad de datos**.
  Every provider answer it used is in the raw store under a `truth_audit` ledger run.

Severity is about consequences: CRITICAL = a wrong number can reach settlement, a model or a
user; HIGH = a wrong fact a page states; MEDIUM = context behind or missing; LOW = identity
details; INFO = agreement on "nothing", or a field we never stored.

## Audit #1 (06:47 UTC, before any fix)

| Dataset | API | DB | Difference | Freshness | Model safe? |
|---|---|---|---|---|---|
| competitions | 1,247 listed, 124 ours | 124 tracked | 91/124 agree; 34 stale (current season, end dates, coverage flags), 1 current season missing | FRESH 100% | n/a |
| fixtures | **36,785** in 144 seasons | **27,621** | **9,165 missing in DB**, 35 stale, 10 mismatch, 3 inconsistent | STALE 12% | **NO** |
| results | finished scores in those lists | fixture_results | 7 missing, 5 mismatch (half-time), 14 inconsistent parts | FRESH 99% | **NO** |
| events | 83 sampled fixtures | stored rows | 35/83 agree; 36 revised by the provider, 29 mismatch, 12 missing | STALE 63% | PARTIAL |
| lineups | 83 sampled fixtures | stored rows | 70/102 agree; 30 missing | STALE 71% | PARTIAL |
| team_stats | 83 sampled fixtures | stored rows | 56/120 agree; 52 missing, 21 stale | STALE 63% | PARTIAL |
| player_stats | 83 sampled fixtures | stored rows | 903/1,136 agree; 156 missing | STALE 63% | PARTIAL |
| standings | 1,380 rows, 72 seasons | 1,198 rows | **182 rows missing** (one team in two tables kept once), 94 inconsistent, extended fields not stored | FRESH 100% | YES (optional) |
| teams | 48 sampled | teams + venues | 1 duplicate identity | FRESH 100% | n/a |
| players | 48 sampled | players | **4 of 58,663 players in a line-up had a profile** | UNKNOWN 100% | n/a |
| coaches | 18 sampled | coaches | 14 profile fields missing | UNKNOWN 100% | n/a |
| squads | 12 sampled | not stored | not stored | n/a | n/a |
| injuries | 24 upcoming | absences | 24/24 agree | UNAVAILABLE 100% | YES (optional) |
| odds | 12 of 24 priced; 9 books | newest prices | 286/297 agree; 18 missing, 4 stale | (flat 3 h rule, replaced) | PARTIAL |
| bookmakers | 33 offered | 9 ever priced | 24 never priced | — | PARTIAL |
| elo | finished fixtures | elo_ratings | **7,459 of 201,781 rated**; never extended since 24 Sep | STALE 100% | PARTIAL |

MODEL_DATA_GATE, next 72 h (174 fixtures): market baseline 21 pass; Poisson/DC 19; Elo ordered
logit 1; logit features v2 1.

## What was wrong, and what was done

| # | Finding | Cause | Fix (commit) | Cost |
|---|---|---|---|---|
| 1 | 78 cancelled and 1 abandoned fixtures stored as *scheduled*; 85 "awaiting results"; picks on them could never settle | The provider spells `Canc`/`Abd` as well as `CANC`/`ABD`; every status map was case-sensitive | `canonical_status` at the parser boundary; case-insensitive group and settlement; migration 0047 repaired the 79 rows, each recorded in `audit.data_repairs` (`f52a6e1`) | 0 requests |
| 2 | 9,165 fixtures missing (club friendlies 8,150; international friendlies 651; J1 League 2026-27 340, 80 played; King's Cup 24) | The league sync asked for *today..today+horizon*: nothing before a season's first sync was ever stored; reschedulings beyond the window kept old kick-offs | The sync reads **whole seasons** (same one request); the audit's own lists were replayed from RAW (`replay_raw --since`) — 9,165 inserted, 13,443 results written (`9172791`) | 0 requests |
| 3 | A fixture whose away side the provider changed kept the old team | `upsert_fixtures` never updated sides ("identity never changes") | Sides follow the provider; every change recorded (`fixture_sides`) | 0 |
| 4 | Seasons and coverage flags only refreshed by hand: the Italian Super Cup's current 2026 edition did not exist; 5 end dates and 25 flags stale | No job | Daily `catalogue_refresh` (one `/leagues` request): 1,784 seasons, 8,762 coverage rows; current season changed for 16 competitions | 1 request/day |
| 5 | 182 table rows missing; home/away split, zone description and update stamp dropped | Key without group; parser read only the `all` block | Migration 0048: group in the key, full row stored; `core.context_checks` records every request | 0 |
| 6 | Tables up to 12 h behind the match that changed them | 12-hour refresh only | `context_due` every 30 min: a table is re-asked hourly after its last match ends until it changes; injuries every 4 h for seasons playing within 48 h | ~150 requests/day |
| 7 | 63% of last week's matches had detail read only at the final whistle; events revised since | The live follower's last read is at full time | `post_match_detail`: one more read ≥ 150 min after kick-off (20 fixtures per request) | ~20–40 requests/day |
| 8 | Elo computed once (24 Sep) from 13,500 results | Never extended | `elo_refresh` every 6 h: the whole history from every stored result (209,909 matches, 419,818 rows); previous refresh runs pruned, feature-build runs never touched | 0 requests |
| 9 | 58,663 line-up players, 4 profiles; squads not stored | `/players` never normalised; no squad table | `/players/profiles` (2,741 pages, monthly) fills known players; `/players/squads` weekly into `core.squad_members` (first/last seen) — migration 0049 | ~2,741/month + ~2,600/week |
| 10 | Odds freshness and the model gate judged prices by a flat 3 h | Wrong rule: captures follow fixed windows T-72…T-3 h | `price_state`: FRESH = captured at the most recent window reached; asked-and-unpriced = UNAVAILABLE | 0 |
| 11 | The pick pipeline fitted a goal model on 8,000 club friendlies (thousands of teams), blocking worker restarts | No size guard | No per-competition goal model above 250 teams (reported uncovered) | 0 |
| 12 | Results repair ran only every 6 h; fixture sync every 12 h | Free-plan cadences kept after the upgrade | Results repair every 30 min; fixture sync every 6 h | ~250 requests/day |

## Audit #2 (07:46 UTC, after the fixes; same seed)

| Dataset | API | DB | Difference | Freshness | Model safe? |
|---|---|---|---|---|---|
| competitions | 1,247 listed, 124 ours | 124 tracked | 106/124 agree; 19 stale (coverage flags the daily refresh had not re-read yet) | FRESH 100% | n/a |
| fixtures | **35,638** in 144 seasons | **35,631** | 261,433/261,467 field checks agree; 8 new fixtures (FA Cup and CAF draws, Italian Super Cup) not yet synced; 18 mismatch; 5 friendlies NS past kick-off (provider lag); 5 provider duplicates | STALE 10% | NO → fixed at the next sync |
| results | finished scores | fixture_results | 441,757/441,765 agree; 6 AET matches without a stated 90-minute score (no result by rule); 2 half-time mismatches | FRESH 99% | PARTIAL (documented rule) |
| events | 83 sampled | stored rows | 48/83 agree (was 35) | STALE 45% (was 63%) — post-match reads catching up | PARTIAL |
| lineups | 83 sampled | stored rows | 77/91 agree (was 70/102) | STALE 45% | PARTIAL |
| team_stats | 83 sampled | stored rows | 82/120 agree (was 56) | STALE 45% | PARTIAL |
| player_stats | 83 sampled | stored rows | **1,184/1,186** agree (was 903/1,136) | STALE 45% | PARTIAL |
| standings | 1,380 rows | 1,328 rows | 52 rows missing (two seasons whose newest table predates the key fix), 184 split-season "played" notes (now excluded) | FRESH 100% | YES (optional) |
| players | 48 sampled | players | profiles queued (2,740 pages pending) | UNKNOWN 100% | n/a |
| squads | 12 sampled | **stored** | 6/11 agree; round 57% done | FRESH 57% | n/a |
| injuries | 24 upcoming | absences | 24/24 agree | UNAVAILABLE 100% (the provider covers injuries in 19 of 124 current seasons) | YES (optional) |
| odds | 14 of 24 priced; 9 books | newest prices | 286/297 agree; 1 fixture's prices differ after the provider's update stamp | STALE 17% · UNAVAILABLE 34% · FRESH 49% | PARTIAL |
| elo | finished fixtures | elo_ratings | **209,909/209,914** rated (5 = the AET matches above) | **FRESH 100%** | YES |

MODEL_DATA_GATE, next 72 h (174 fixtures): **market baseline 85 pass** (was 21); Poisson/DC 74
(was 19); Elo ordered logit 74 (was 1); logit features v2 67 (was 1). The rest are blocked by
missing prices (89: the provider prices them later or not at all) and thin result history (69:
mostly friendlies and newly promoted sides).

## What remains (and why it is not hidden)

* **Provider lag, not ours:** 5 club and international friendlies still `NS` a day after
  kick-off; the provider itself says `NS` (it documents up to 48 h for some competitions).
* **Provider duplicates:** 5 pairings appear twice within 36 hours under two fixture ids
  (Primera División 2018/2020, two friendlies). Kept as the provider sent them; flagged for
  exclusion from model training in GATE C.
* **AET without a 90-minute score:** 6 matches (UEFA Europa League 2026, Copa del Rey 2025, …):
  no result row by rule — a wrong 1X2 is worse than none. They are also unrated by Elo.
* **The provider's odds `update` stamp is not reliable at price level:** one fixture's prices
  changed after the stamp we compared against. Recorded as HIGH; prices are always kept as
  captured.
* **Injuries:** the provider covers them for 19 of the 124 current seasons (top European
  leagues, MLS, Brazil, Russia, UEFA club competitions, World Cup). Everywhere else injuries
  are UNAVAILABLE_BY_PROVIDER, never "nobody is injured".
* **Coaches' profiles** are not fetched (LOW; no model or page needs them yet).
* **Bookmakers:** 24 of the 33 bookmakers the provider lists have never priced a fixture for us
  — GATE B (`docs/research/ODDS_PROVIDER_GAP_ANALYSIS_2026.md`).

## Request budget

Audit: ~375 requests per run. New standing jobs: ~1 (catalogue) + ~150 (tables/injuries after
matches) + ~40 (post-match detail) + ~250 (fixture sync every 6 h) + ~2,600/week squads +
~2,741/month profiles. Measured spend on 4 Oct by 07:45 UTC: 3,269 of the 60,000 guard (plan
75,000).

## Re-running

```bash
python -m scripts.truth_audit                       # full audit
python -m scripts.truth_audit --seed 0.5            # same sample as audit #2
python -m scripts.truth_audit --internal-only       # zero requests: database checks, freshness, gate
python -m scripts.replay_raw --apply --since <ISO>  # apply stored full-season lists (zero requests)
```
