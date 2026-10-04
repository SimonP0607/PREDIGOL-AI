# API-Football v3 data contract (4 October 2026)

*Sources: `config/api_football/v3_contract.txt` - the provider's OpenAPI document v3.9.3 written out operation by
operation and checked byte for byte against the documentation page (sha256 `601485c8…37047b`, format in
`v3_contract.meta.json`; no API key, not even its placeholder, appears in it - a test asserts this) - and
`fbi.providers.api_football.integration` (what PrediGol does with each endpoint). Command:
`python -m scripts.audit_api_contract [--probe] [--sample N]` (`--export` writes the documented side as JSON).
Final run: `data/truth/20261004T184151Z-api_contract` (run kind `api_contract`, evidence area `api_contract`).*

## 1. What the provider documents

38 GET operations, 140 query parameters (plus the key header), 993 documented response field paths, each
endpoint's update frequency, recommended call rate, pagination and id batch limits. All 38 are inventoried; every
documented field of every endpoint PrediGol has a payload for was seen in the sampled RAW payloads
(`documented_unseen` 0); 288 fields are sent but absent from the documentation's examples (below).

## 2. Status of every endpoint

| Status | Endpoints |
|---|---|
| **FULL** (28) - requested on a schedule, normalized, read | `/timezone` `/countries` `/leagues` `/leagues/seasons` `/teams` `/teams/statistics` `/teams/countries` `/standings` `/fixtures/rounds` `/fixtures` `/injuries` `/predictions` (auxiliary) `/coachs` `/players/seasons` `/players/profiles` `/players/squads` `/players/topscorers` `/players/topassists` `/players/topyellowcards` `/players/topredcards` `/transfers` `/trophies` `/sidelined` `/odds/live` `/odds/live/bets` `/odds` `/odds/bookmakers` `/odds/bets` |
| **COVERED** (6) - its data arrives through another endpoint | `/fixtures/events`, `/fixtures/lineups`, `/fixtures/statistics`, `/fixtures/players` (all in `/fixtures?ids=`, 20 matches a request); `/fixtures/headtohead` (our stored fixtures, read with a date cut-off); `/teams/seasons` (`/teams?league&season` and our fixtures) |
| **PARTIAL** (4) | `/players` - the provider's season aggregates are stored weekly (`core.player_season_stats`) and audited, not yet shown on player pages; `/odds/mapping` - stored daily (`market.odds_mapping_seen`), not yet read by the capture planner; `/players/teams`, `/venues` - RAW from audits only (one request per player / venue; the same data arrives with squads, appearances and `/teams`) |
| **MISSING** | none (16 on the morning of 4 Oct 2026) |
| **WRONG** | none (`/standings` was misread until 4 Oct 2026 - see `COMPETITION_PHASES.md`) |

The documented frequency, recommended rate and PrediGol's cadence of each endpoint are in the report table and in
`fbi/ingestion/reference.py` (the cadence table). Where ours is lower than recommended it is deliberate and stated:
people (coaches, transfers, sidelined, trophies) weekly instead of daily - the tracked scope is 5,525 teams,
30,742 players and 4,571 coaches; asked daily they would cost ~20,000 requests a day for answers that change a few
times a season.

## 3. What changed on 4 Oct 2026

* **Reference feeds** (`fbi.ingestion.reference`, worker job `reference_refresh` every 30 min, at most 300
  requests a run, never into the live reserve): predictions, rounds and current round, the four top lists, team
  statistics, coaches, transfers, sidelined, trophies, countries, the three odds catalogues and the odds mapping.
  Each answer is RAW first; rows are change-only with the payload hash and the normalizer version;
  `core.reference_checks` records every question, so "asked, nothing returned" is not "never asked".
  Each feed with something due first gets a fair share of a run's requests, then the rest goes in priority
  order (predictions first): the first worker run (6435, 19:10 UTC) spent all 300 on the first seven feeds, and
  the 5,525-team sweep of `/teams/statistics` would have held `/sidelined` and `/trophies` back for a day.
  Never-asked teams are taken by next kick-off, people by their latest appearance.
* **Production check, 4 Oct 19:10-19:13 UTC**: every one of the 23 feeds answered with 0 errors (run 6435
  plus one capped run per remaining feed, 4 requests each): 107 predictions, 2,566 rounds, 320 leader rows,
  8 coaches with 40 career rows, 820 sidelined periods, 2,581 trophies, 171 countries, 2,814 odds-mapping
  rows; the odds catalogues matched the stored ones (no rename). The first worker run with the fair share
  (6542, 19:33 UTC, be-64) spread its 300 requests over 13 feeds (23 each, the rest to the current rounds),
  0 errors: 2,087 leader rows, 102 coaches, 2,000 periods out, 7,662 trophies, 11,793 transfer rows in all.
* **/predictions is auxiliary**: `core.provider_predictions` is labelled the provider's opinion; it is served only by
  an admin route (`/admin/matches/{id}/provider-prediction`) and a test fails if any feature, model, backtest,
  pick, parlay or validation module names it.
* **/players season pages**: the backfill's `players_season` units had never been seeded (the integration map
  claimed a requester that never ran); they are now seeded weekly for current seasons and normalized.
* **/teams/statistics**: written into `core.team_season_stats` (0003, never written before) with provenance,
  averages and totals in separate columns.

## 4. The contract probe - what the documentation does not show

`--probe` asked each never-stored endpoint form once, with ids read from the database (34 requests; six of them
asked about player id 0 - a placeholder the first probe query did not exclude, fixed):

* **Batched `/sidelined` and `/trophies`** (`players=a-b`, `coachs=a-b`) answer one block per person -
  `{"id": 5179, "sidelined": [...]}` - while the single form answers the bare list. The normalizer attributes a
  batched answer by the id in each block and never guesses a nameless one. People absent from a batched answer
  have nothing listed.
* **`/fixtures/statistics?half=true`** adds `statistics_1h` and `statistics_2h`. Not requested on a schedule (one
  request per match); recorded as a known gap.
* **`/fixtures/rounds?current=true`** can name two current rounds (Colombia: "Clausura - 13", "Clausura - 17" - a
  postponed match); stored as a list.
* **Cards by minute** in `/teams/statistics` and `/predictions` carry an empty-string bucket (`""`: cards without a
  minute); kept as sent in the `raw` document.
* Numbers sent as strings: `last_5.goals.*.average` in `/predictions`, statistics values (`"44%"`), odds values.
* **A rating of `0` means "not rated"** (match players and the season lists): 13,788 match rows, 999 with minutes;
  the provider's season rating averages those zeros. Stored as sent, never shown or averaged as a rating
  (`PLAYER_DATA_VALIDATION.md` §6).
* **`/trophies` adds a season-less row after the dated rows of each competition and place** (672 of 1,285
  groups): a group summary, stored as sent and not listed as another trophy.

Fields sent but undocumented, by endpoint: `/predictions` 187 (per-minute goals and cards, under/over, line-ups
of both teams), `/fixtures` 82 (the detail blocks of `?ids=`), `/trophies` 5 and `/sidelined` 4 (batched shapes),
`/teams/statistics` 4, `/fixtures/statistics` 4 (half blocks), `/fixtures/rounds` 2 (`dates=true`).

## 5. Field coverage

`python -m scripts.audit_field_coverage --sample 30` follows every field from the payload to the column, the
page and the model (`data/truth/20261004T184153Z-field_coverage`): **1,170 fields of 34 endpoints - stored and used
574, stored not used 69, intentionally ignored 500 (each with its reason), unsupported 27 (resolved in be-59: empty
list containers, lineup shirt colours, half statistics, RAW-only audit endpoints), dropped by a bug 0** (six on the
morning of 4 Oct: the referee, both winner flags, half starts, position played, offsides, dribbled past and
penalties won/committed/saved - now in `core.fixture_facts` and `core.fixture_player_extras`, filled from RAW:
210,952 fact rows and 5,221,180 player rows replayed from 14,285 payloads).

## 6. RAW integrity

`python -m scripts.audit_raw_integrity` re-reads every indexed payload (exists, decodes, sha256 of the body equals
its hash): 26,977 payloads, 3 damaged - all written between 02:57:16 and 02:57:46 UTC on 4 Oct 2026, just before
the machine stopped: two empty files and one missing (two `/odds/live`, one `/fixtures?ids=`). The rows written from
them at the time stay (40 rows name them: live odds and live states); their source cannot be re-read. Cause: the payload was renamed into
place before its bytes reached the disk. Fix: the store now syncs the file before the rename and the directory
after it, and an empty file is rewritten from the same body instead of being taken as already captured
(`tests/unit/test_payload_store.py`). RAW is never repaired; the three are evidence entries (`raw_integrity:*`).

## 7. Cadences - the provider's documented rate and PrediGol's

| Endpoint | Documented update / recommended call | Worker job | PrediGol's cadence |
|---|---|---|---|
| `/leagues` | several times a day / 1 per hour | `catalogue_refresh` | every 24 h (one request: every league, season and coverage flag) |
| `/fixtures` (list) | every 15 s / 1 per minute in play, else 1 per day | `fixtures_sync`, `results_sync` | every 6 h per current season; results every 6 h, 1-day lookback |
| `/fixtures?ids=` | every 15 s | `live_match`, `results_repair`, backfill | every minute while in play (20 ids a request); unfinished-past-kick-off every 30 min; one settled re-read |
| `/odds` | every 3 h / 1 per 3 h | `odds_capture`, `final_prematch` | every 15 min inside the capture windows; the last pre-match prices once, after kick-off |
| `/odds/live` | every 5 s | `live_odds` | adaptive 15-60 s within the live budget |
| `/standings` | every hour / 1 per hour in play, else 1 per day | `context_due`, `context_refresh` | hourly after a finished match until the table changes (24 h at most); every 12 h otherwise |
| `/injuries` | every 4 h / 1 per day | `context_due`, `context_refresh` | every 4 h for seasons with a match in 48 h; every 12 h otherwise |
| `/predictions` | every hour / 1 per hour in play, else 1 per day | `reference_refresh` | 48 h, 24 h and 3 h before each tracked kick-off |
| `/fixtures/rounds` | every day / 1 per day | `reference_refresh` | daily per current season (with dates; and `current`) |
| `/players/top*` (4) | several times a week / 1 per day | `reference_refresh` | daily per current season the coverage flags allow |
| `/teams/statistics` | twice a day / 1 per day if playing, else 1 per week | `reference_refresh` | daily within 24 h of a match, weekly otherwise |
| `/coachs`, `/transfers` | daily / several a week; 1 per day | `reference_refresh` | weekly per tracked team (`/transfers`: clubs only - asked on 4 Oct, national sides answered nothing) |
| `/sidelined`, `/trophies` | several times a week / 1 per day | `reference_refresh` | weekly per person in scope, 20 a request |
| `/odds/bets`, `/odds/live/bets`, `/odds/bookmakers`, `/odds/mapping` | several a week - daily / 1 per day | `reference_refresh` | daily (mapping: every page) |
| `/players/squads` | several times a week / 1 per week | `historical_backfill` (seeded weekly) | weekly per tracked team |
| `/players/profiles` | several times a week / 1 per week | `historical_backfill` (seeded monthly) | monthly sweep of every page |
| `/players?league&season` | several times a week / 1 per day | `historical_backfill` (seeded weekly) | weekly per current season |
| `/countries`, `/leagues/seasons`, `/players/seasons`, `/teams/countries` | when added / 1 per day | `reference_refresh` | weekly (`/timezone` every 90 days) |

Every requesting job spends behind the live reserve (`fbi.ingestion.backfill.live_reserve`: what odds capture and the
standing syncs may need over the next 24 h) and inside the daily budget (60,000; the plan's limit is higher).
