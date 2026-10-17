# Historical migration — status

Written 2026-09-29, after closing the detail gap. Every figure is a query against
the machine's database on that date.

> **Superseded in part, same day.** The table below describes the state when only
> 7 competitions were configured. The migration was then widened to **122
> competitions** chosen on the provider's own coverage flags — see
> [COMPETITION_SELECTION_2026-09-29.md](COMPETITION_SELECTION_2026-09-29.md) for
> which, why, and what was refused — and priced at **991 league-seasons, 327,740
> fixtures, 19,164 requests, 1,050 MB of raw storage**. The planner analysis in
> this document is what made that widening safe, so it is kept rather than
> rewritten.

## Where it stands

| | fixtures |
|---|---|
| Finished fixtures stored | **17,884** |
| With detail coverage | **17,884** |
| Without detail | **0** |

`scripts.migration gaps` prints `0 league-season(s), 0 fixture(s) without detail`.

### By competition

| Tier | League | Name | Played | Seasons |
|---|---|---|---|---|
| 1 | 39 | Premier League | 3,090 | 2018–2026 |
| 1 | 140 | La Liga | 3,109 | 2018–2026 |
| 1 | 135 | Serie A | 3,091 | 2018–2026 |
| 1 | 61 | Ligue 1 | 2,771 | 2018–2026 |
| 1 | 78 | Bundesliga | 2,500 | 2018–2026 |
| 1 | 2 | UEFA Champions League | 1,918 | 2018–2026 |
| 4 | 141 | Segunda División | 1,405 | 2022–2026 |

## The planner bug, and what it actually cost

`fixtures_season` completed was being treated as proof that `fixture_details`
completed. **It is not, and the two were never connected.** Three separate faults:

1. **`seed_plan` was an `if/elif`.** When the plan priced a fixtures unit it called
   `add_unit` and skipped the `elif` that expands detail. A season whose fixtures a
   PREVIOUS plan had already stored hit `ON CONFLICT DO NOTHING`, created nothing,
   and expanded nothing. Fingerprint in the data: **season 2022 missing wholesale
   for Serie A, La Liga, Ligue 1, Bundesliga and most of the Premier League.**

2. **"Already covered" was read from task batch keys, regardless of status.** A unit
   that was pending, failed or refused counted as done. And because the unique key
   already held a row, inserting again did nothing — "regenerate what is missing"
   could not regenerate anything.

3. **Nothing recorded what a payload actually CARRIED.** An empty table meant "the
   provider does not publish this", "we never asked" and "we asked and it failed",
   all at once.

### What replaced it

`core.fixture_detail_coverage`: one row per fixture, source and dataset, recording
whether the block arrived and how many rows came out of it.

| State | Meaning | Planner action |
|---|---|---|
| no row | never fetched | **request it** |
| `block_present = false` | the provider does not publish it | never ask again; `MISSING_DETAIL` |
| `block_present, rows_written = 0` | the block arrived empty | never ask again |
| `block_present, rows_written > 0` | we have it | nothing |

`core.detail_completeness` reports `played`, `fetched`, `delivered`, `with_rows`,
`never_fetched` and `not_published` per league-season and dataset, and returns **no
percentage at all** when nothing has been played.

A retryable failed unit is now put back in the queue by `expand_detail_batches`.
A `refused` or unretryable-failed unit is left alone: asking again in a loop is how
quota is wasted on an answer we already have.

## The closing run, 2026-09-29

| Step | Requests | Rows | Note |
|---|---|---|---|
| Replay 818 stored detail payloads | **0** | 56,968 coverage rows | every file re-hashed before it was trusted |
| Derive coverage from stored detail | **0** | 7,236 coverage rows | the 1,809 fixtures whose replay read as stale |
| Normalise 54 stored `/teams` payloads | **0** | 4,812 rows (teams, venues, memberships) | fetched long ago, discarded |
| Derive identity from stored detail | **0** | 13,322 players, 687 coaches, 31,971 line-ups linked | |
| Tier 1 detail (UCL 2022, 2023) | **22** | 41,236 | |
| Tier 2 detail (Segunda 2022–2026) | **73** | 152,332 | |
| **Total** | **95** | **~276,000** | |

**The gap looked like 3,642 fixtures and was 1,833.** The difference — 1,809 — had
full detail already; only their coverage rows were missing, because the raw store
deduplicates identical bodies and the replay of their payload read as stale.
Re-fetching them would have spent 91 requests to collect data we held.

## Identity tables, before and after

| Table | Before | After | Source |
|---|---|---|---|
| `core.teams` | stubs from the fixtures importer | **371** filled in | 54 stored `/teams` payloads |
| `core.venues` | ~empty | **459** | same |
| `core.team_season_memberships` | **0** (no writer) | **1,604** | same |
| `core.players` | **0** (no writer) | **16,669** | line-ups and player statistics already stored |
| `core.coaches` | table did not exist | **837** | line-ups already stored |
| `core.fixture_lineups.coach_id` | column did not exist | **32,827** linked | |

All of it at **zero API cost**. Identity is the provider's id, never the name: two
clubs really are called Arsenal, and one club really does get renamed.

## Seasons

`refresh_seasons` used to write exactly one row per competition — the current
season — and drop every other season `/leagues` had listed, plus `has_fixtures`,
which was parsed and never stored. It now upserts every listed season with its own
start and end, keeps `has_fixtures` (a season listed WITHOUT a fixture list is
nothing to fetch, which is not a gap), and records `listed_at`. A season that stops
being listed is kept, because the fixtures we hold for it happened.

## Injuries: the earliest season is a tail, not a year

`since_season: 2020` is **correct and was nearly changed by mistake.** API-Football
season 2020 means 2020/21, which runs to May 2021, so the provider's April-2021
cut-off falls inside it: our six stored `/injuries` payloads for that season
returned **3,100** absences against **13,774** for 2021. Raising the floor to 2021
would have discarded those. It is flagged `since_season_is_partial: true`, because a
two-month tail must never read as a complete season.

## Next, and what it costs

| Work | Requests | Note |
|---|---|---|
| Tier 2 proper (30 competitions in `config/migration.yaml`) | priced by `scripts.migration plan --tiers 2` | not seeded |
| Tier 3 (36 competitions) | same | not seeded |
| `/players` season profiles | 20 per page, ~36 pages per league-season | OPTIONAL; not planned |
| `/players/squads` | one per team-season | no unit kind exists; deliberate |
