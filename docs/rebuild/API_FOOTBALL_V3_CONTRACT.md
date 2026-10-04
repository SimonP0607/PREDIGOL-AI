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
