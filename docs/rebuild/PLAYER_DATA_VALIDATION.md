# Player data validation — data truth audit V2 (4 October 2026)

*Command: `python -m scripts.audit_player_stats [--external FILE]` (code `fbi/truth/v2/players.py`).
Every provider answer is a new raw payload; nothing in `core` is written. Ledger area
`player_stats`.*

## 1. What was compared

The provider's player statistics are "calculated according to the team id, league id and season" —
one block per team × competition × season (a transfer gives two). PrediGol stores one row per player
per match (`core.fixture_player_stats`, from `/fixtures/players`), **including the substitutes who
never came on** (minutes NULL). For each block the audit adds up our rows for the same team,
competition and season and compares appearances (minutes > 0), starts, minutes (± 10 for the
provider's own corrections), goals, assists, yellow and red cards. The provider's `rating` is its own
position-relative algorithm (`PROVIDER_DEFINED_METRIC`): compared to nothing, averaged by nobody else.

Sample: the four players the mandate named — Raphinha (1496), Lamine Yamal (386828), Erling Haaland
(1100), Harry Kane (184) — plus 20 random players per golden league (104 players, 717 blocks over the
2025 and 2026 seasons, 220 requests). For the four: `/players/teams` (career), `/players/squads`
(current squads), `/injuries?player&season`.

## 2. External verification (FBref, Opta-based)

| Player | Competition, season | FBref (apps · goals · assists · min) | Provider | PrediGol |
|---|---|---|---|---|
| Haaland | Premier League 2025/26 | 35 · 27 · 8 · 2,953 | 35 · 27 · 8 · 2,958 | 35 · 27 · 8 · 2,958 |
| Haaland | Premier League 2026/27 | 5 · 5 · 0 · 450 | 5 · 5 · 0 · 450 | 5 · 5 · 0 · 450 |
| Kane | Bundesliga 2025/26 | 31 · 36 · 5 · 2,377 | 31 · 36 · 5 · 2,382 | 31 · 36 · 5 · 2,382 |
| Kane | Bundesliga 2026/27 | 4 · 3 · 1 · 294 | 4 · 3 · 1 · 296 | 4 · 3 · 1 · 296 |
| Lamine Yamal | La Liga 2025/26 | 28 · 16 · 11 · 2,262 | 28 · 16 · 11 · 2,268 | 28 · 16 · 11 · 2,268 |
| Lamine Yamal | La Liga 2026/27 | 7 · 7 · 4 · 579 | 7 · 7 · 4 · 581 | 7 · 7 · 4 · 581 |
| Raphinha | La Liga 2025/26 | 22 · 13 · 3 · 1,380 | 22 · 13 · 3 · 1,388 | 22 · 13 · 3 · 1,388 |
| Raphinha | La Liga 2026/27 | 7 · 12 · 3 · 550 | 7 · 12 · 3 · 555 | 7 · 12 · 3 · 555 |

Appearances, goals and assists: **identical in all three sources, 8 of 8**. Minutes differ by 0–8
(stoppage time counted differently), inside the tolerance. Read on fbref.com in Chrome
(4 Oct 2026, 15:05–15:09 UTC); Transfermarkt sits behind a consent-or-pay wall and was not used.

Current club, national team and injuries for the four, from the provider and our data:

| Player | Club (squad / career) | National team | Last appearance | Injuries 2026 (provider / ours) |
|---|---|---|---|---|
| Raphinha | Barcelona | Brazil | Brazil (29 Sep friendly v Australia) | 3 / 3 |
| Lamine Yamal | Barcelona | Spain | Spain | 0 / 0 |
| Erling Haaland | Manchester City | Norway | Norway | 0 / 0 |
| Harry Kane | Bayern München | England | England | 0 / 0 |

## 3. Blocks by verdict (second run, before the detail backfill)

| Verdict | Blocks | Meaning — who |
|---|---:|---|
| ok | 501 | equal |
| starts_definition | 46 | only starts differ, by 1–2: the provider's season "lineups" and its per-match substitute flag disagree (provider definition, ACCEPTED) |
| details_missing | 53 | finished matches of his team without any player rows — national friendlies before the live follower existed, early Copa del Rey/Taça rounds (PrediGol: MISSING_BACKFILL) |
| season_not_migrated | 47 | Friendlies Clubs before 2026 and friendlies before 2026 were never migrated (scope) |
| untracked | 32 | U21/U19 qualifiers, Premier League Summer Series, Emirates Cup — not tracked (not an issue) |
| stats_mismatch | 24 | small provider-internal differences: a yellow card (10), minutes on blocks where the provider has none (10), starts by > 2 (4), Raphinha's 2025 Spanish Super Cup goals (provider 2, our rows 4) |
| player_rows_missing | 16 | every match of his team has player rows, he is in none of some, yet the provider's season figures count him (provider) |
| provider_behind | 14 | our rows have more appearances than the provider's season figures (Club World Cup 2025: 7) — its player statistics update "several times a week" (provider) |
| not_at_provider | 4 | we have rows, the provider has no block (League Cup) |

The per-match data and the provider's season data agree for the competitions that matter to the
product and the models; where they differ it is overwhelmingly a definition (starts) or the provider's
own aggregation lag.

## 4. What the user saw — PrediGol bugs, fixed

**"Equipo último: España / Noruega / Inglaterra"** (`PRODUCT_SCOPE`, high): the player list and page
labelled a player with the team of his **last appearance** (`PLAYER_AGG` / `PLAYERS_ACTIVE`:
`array_agg(team ORDER BY kickoff DESC)[1]`). After an international window that is the national side
for every international. Now three fields (`c65d8af`, frontend `f753b28`):

* **club** — the club whose newest squad (`/players/squads`, weekly) lists him, else the club of his
  last club appearance (`club_source` says which);
* **national team** — likewise among national sides;
* **last appearance** — whoever he last played for.

An unknown `is_national` flag (NULL on most club rows) is treated as a club, never as a national side.

**Apps counted the bench** (`PLAYER_STATS_MISMATCH`, high): `count(*)` over the match rows counted an
unused substitute as an appearance — 220,320 of 924,125 rows in the last 400 days have no minutes
(23.8 %). Appearances are now matches played (minutes > 0) everywhere (list, profile, squad, season
table); starts likewise.

**Window scope** (`PRODUCT_SCOPE`, medium): the totals add 400 days of every competition, national
team included. They stay a rolling total (labelled), and the season table is now one row per
competition, season **and team** — the provider's own scope (a transfer gives two rows).

Tests: `tests/integration/test_data_truth_v2.py::test_a_player_is_shown_with_his_club_not_his_national_side_and_bench_rows_are_not_apps`.

## 5. Match details nobody fetched — fixed

8,113 finished fixtures since July 2025 had never been asked for their detail (events, line-ups,
player rows): most national friendlies of 2026, the whole 2026/27 J1 League, King's Cup, and Friendlies
Clubs. The live follower reads matches while they are played; a match it never saw had no other way
in. `fbi.ingestion.backfill.seed_current_details` now queues detail units for every tracked current
season's played, never-fetched fixture before each backfill tick (priority 8, ahead of history,
inside the live-capture reserve); the first seeding queued **407 units** (≈ 8,100 fixtures) and the
backfill run of 4 Oct fetched them (see `DATA_TRUTH_AUDIT_V2.md` §after).

## 6. Rating

`rating` is `PROVIDER_DEFINED_METRIC`: "calculated according to the performance of the player in
relation to the other players of the game or the season who occupy the same position". Our
`avg_rating` is the mean of the provider's match ratings over matches played; the provider's season
rating is its own number. They are shown, never compared, never fed to a model as ground truth.
