# API & data pipeline — status

Written 2026-09-29. Every number here is measured against the machine's database
or the provider, and says which. Nothing is projected.

## What the pipeline is

```
API-Football  ──►  raw store (gzip + sha256)  ──►  raw.ingestion_payloads
                                                        │
                        ┌───────────────────────────────┴──────────────┐
                        ▼                                              ▼
                 normalized rows                              audit.data_quality_issues
            (core.*, market.*), each                    (what we could not use as sent,
             carrying payload_hash                        with the payload it came from)
```

The rule the whole design serves: **what API-Football said and what we made of it
stay distinguishable.** Nothing repairs a provider value silently. A value that
cannot be stored as sent is dropped AND recorded, with the observed value, the
field, the payload and a sentence.

## Endpoints in use

| Endpoint | Unit kind | Normalised into | Notes |
|---|---|---|---|
| `/leagues` | `league_coverage` | `raw.league_coverage`, `core.competition_seasons` | one call, every league, every season, 12 coverage flags |
| `/fixtures?league&season` | `fixtures_season` | `core.fixtures`, `core.fixture_results` | one request per competition-season |
| `/fixtures?ids=` (≤20) | `fixture_details` | events, line-ups, team stats, player stats, `core.fixture_detail_coverage`, `core.players`, `core.coaches` | **3.21 KB/fixture gzipped, measured over 818 payloads / 16,053 fixtures** |
| `/fixtures?date=` | live sync | `core.fixtures`, `core.fixture_results` | visible **−365 … +90 days** on Ultra (measured 2026-09-29) |
| `/standings` | `standings_season` | `core.standings` | 1.8 KB/request measured |
| `/injuries` | `injuries_season` | `core.player_absences` | 43 KB/request measured |
| `/teams` | `teams_season` | `core.teams`, `core.venues`, `core.team_season_memberships` | was raw-only until 2026-09-29 |
| `/odds` | odds capture | `market.odds_snapshots` | prices exist to **T-18.2 days, measured**; documented figure is 14 |
| `/odds/live` | near-close | `market.odds_snapshots`, `market.near_close_snapshots` | **answered for the first time 2026-09-29**; in-play bet ids are a DIFFERENT namespace |
| `/odds/bets`, `/odds/live/bets` | catalogue | `market.provider_markets` | 338 pre-match + 266 in-play |
| `/players` | `players_season` | — | OPTIONAL, not fetched; per-fixture player stats already arrive with detail |
| `/predictions` | — | — | deliberately not used: the provider's own forecast is not a baseline we trust over the market |

## Market catalogue

`market.provider_markets` holds **604 bets** (338 pre-match, 266 in-play), of which
**10 are mapped** to the five markets we can represent — five per scope, because
**the two namespaces are incompatible**:

| Our market | Pre-match bet | In-play bet |
|---|---|---|
| 1X2 | 1 Match Winner | 59 Fulltime Result |
| OU | 5 Goals Over/Under | 36 Over/Under Line |
| BTTS | 8 Both Teams Score | 69 Both Teams to Score |
| DC | 12 Double Chance | 72 Double Chance |
| AH | 4 Asian Handicap | 33 Asian Handicap |

In-play bet 4 is *Extra Time Total Corners (3 Ways) (1st Half)* and in-play bet 5 is
*Extra Time Double Result*. One shared id map — which is what the code had — would
have written extra-time corner prices into our Over/Under series the first time
`/odds/live` ran. It had never run, so nothing had caught it.

`market.markets` now separates **`is_tracked`** (we store prices) from
**`is_model_enabled`** (our models may use it). 1X2, OU and BTTS are model-enabled,
exactly what decision rule `RULE_V1` covers. DC and AH are tracked and modelled by
nobody.

### Asian Handicap: the sign

API-Football repeats the **home** handicap on both rows of a pair:

```
{"value": "Home -0.25", "odd": "1.92"}
{"value": "Away -0.25", "odd": "1.88"}
```

Read that way, every sampled pair devigs to ~1.090; read as a per-side signed
handicap, the same prices devig to 0.468 — a book paying out more than it takes.
So the boundary **negates the away row**, and the stored `line` is always the
handicap that applies to the stored selection. `AH Away +0.75` is a complete
statement. Enforced in the schema by one trigger reading `market.markets`.

## Lineage

| Table | Traceable to | How |
|---|---|---|
| `market.odds_snapshots` | request | `payload_hash` → `raw.ingestion_payloads` → `run_id` |
| `market.near_close_snapshots` | request **and the series** | `payload_hash`, plus a trigger requiring the exact snapshot to exist and to agree on odds, minutes_to_ko, source and payload |
| `core.fixtures`, `core.fixture_results` | request | `source_payload_hash`, `source_fetched_at` |
| detail tables | request | `payload_hash`, `fetched_at` |
| `core.teams`, `venues`, `players`, `coaches` | request | `source_payload_hash` (NULL on rows written before 2026-09-29) |

`market.near_close_lineage` walks the whole chain in one query.

### Known lineage fault, recorded not hidden

**36,599 normalized rows are dated after the payload they name.** The raw store
deduplicates identical bodies and indexes the FIRST fetch, while the caller held
the second and passed it to the writers. Consequence: replaying such a payload
reads as stale, the monotonic writers refuse it — correctly — and 1,809 fixtures'
detail looked absent when it was present.

Fixed forward: writers now take `RunLedger.indexed_at(payload_hash)`. The existing
rows are **not** rewritten — backdating a timestamp to tidy a report is exactly
what this project does not do. The sweep's `lineage_holds` check reports the count
every run.

## Data quality: the state on 2026-09-29

From `scripts.quality_sweep --apply`, run 111:

| check | population | offenders | ratio |
|---|---|---|---|
| `results_are_resolved` | 17,884 finished fixtures | **6** | 0.0003 |
| `lineups_are_complete` | 35,766 line-ups | **15** | 0.0004 |
| `detail_has_been_fetched` | 17,884 finished fixtures | **0** | 0.0000 |
| `values_are_possible` | — (two populations) | 0 | — |
| `results_are_not_stale` | 1,633 unfinished | 5 | 0.0031 |
| `lineage_holds` | — (four tables) | 3 | — |
| `prices_come_from_known_books` | 33 bookmakers | 0 | 0.0000 |

Open issues by code:

| Code | Severity | Issues | Occurrences |
|---|---|---|---|
| `PROVIDER_INCONSISTENCY` | warning | 3,798 | 3,798 |
| `INCOMPLETE_LINEUP` | info | 203 | 203 |
| `UNKNOWN_PROVIDER_ENTITY` | info | 89 | 96 |
| `INCOMPLETE_LINEUP` | warning | 30 | 45 |
| `RESULT_UNRESOLVED` | error | 6 | 12 |
| `STALE_DATA` | warning | 5 | 10 |
| `LINEAGE_BROKEN` | warning | 3 | 3 |

The 3,798 provider inconsistencies are contradictions the old code nulled in
silence (`shots_on_target > shots`, `passes_accurate > passes`, negative counts).
They were recovered from the raw payloads, which is the whole argument for keeping
RAW: **none of them cost a request to find.**

The 6 `RESULT_UNRESOLVED` are matches decided after extra time or on penalties with
no extra-time score. `reg_goals_*` is `goals − COALESCE(et_goals, 0)`, so with the
extra-time score missing it *equals* the after-extra-time score — settling a
90-minute market on that counts extra-time goals as regulation goals. `settle()`
refuses them with a reason. **The shoot-out is not turned into a 90-minute result.**

## Quota

Internal budget **60,000/day** against the plan's 75,000. Spend on 2026-09-29:
**1,281 + 18 probe requests**, i.e. about 2.2% of the guard. `LIVE PRIORITY >
BACKFILL` is enforced by the backfill's own live reserve, computed every run.

## What is deliberately not done

| Not done | Why |
|---|---|
| `/players` season profiles | per-fixture player statistics already arrive with the detail payload; the season aggregate is OPTIONAL |
| `/players/squads` | never fetched; no unit kind. Squad membership is derivable from line-ups for matches that were played, which is what the models use |
| `/predictions` | the provider's own forecast is not a baseline we trust over the market |
| `core.competition_seasons.coverage` (JSONB) | the flags live in `raw.league_coverage` with their payload; a second copy would be two truths that can drift |
| rewriting the 36,599 drifted timestamps | backdating to tidy a report is not a fix |
