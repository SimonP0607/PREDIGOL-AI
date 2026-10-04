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
(1100), Harry Kane (184) — plus 20 random players per golden league (104 players, **737 blocks** over the
2025 and 2026 seasons, 260 requests in the final run). For the four: `/players/teams` (career), `/players/squads`
(current squads), `/injuries?player&season`. Blocks that still differ after the checks below are **settled by
re-reading their matches** (`/fixtures?ids`, the per-match players block, as NEW raw payloads): if our rows equal the
provider's per-match data today, the provider's season aggregate is what differs; if not, our rows are older than
its corrections and a re-fetch is due.

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

## 3. Blocks by verdict (final run, 4 Oct 15:54 UTC, after the detail backfill)

| Verdict | Blocks | Meaning — who |
|---|---:|---|
| ok | **523** | equal |
| starts_definition | 46 | only starts differ, by 1–2: the provider's season "lineups" and its per-match substitute flag disagree (provider definition, ACCEPTED) |
| provider_aggregate_differs | 28 | **re-read on 4 Oct: our match rows equal the provider's per-match data in 28 of 28**; its `/players` season figures differ (a yellow card, minutes, a League Cup block it does not publish, Raphinha's 2025 Super Cup goals: aggregate 2, its matches 4) — provider |
| provider_no_match_rows | 30 | his team's matches WERE fetched and the provider's players block came back empty (early Copa del Rey / Taça rounds, 2026 national friendlies, Europa League qualifiers) while its aggregate counts him — provider coverage |
| player_rows_missing | 17 | every match of his team has player rows, he is in none of some, yet the provider's season figures count him (provider) |
| provider_behind | 14 | our rows have more appearances than the provider's season figures (Club World Cup 2025): its player statistics update "several times a week" (provider) |
| season_not_migrated | 47 | Friendlies Clubs before 2026 and friendlies before 2026 were never migrated (scope) |
| untracked | 32 | U21/U19 qualifiers, Premier League Summer Series, Emirates Cup — not tracked (not an issue) |

**No block shows a wrong figure of ours.** Before the backfill, 53 blocks were "details missing"; the backfill
fetched the never-asked matches (23 blocks became equal) and the remaining 30 turned out to be matches the
provider serves without player data: across tracked competitions, **14,450 finished matches of the last 450 days
were fetched with an empty players block** and only 20 were never fetched (`core.fixture_detail_coverage`).

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

The audit reads the product **through the product's own SQL** (`PLAYER_AGG`, the club / national team / last
appearance columns), next to the match rows counted independently — so a fixed bug stays fixed in the ledger:
the 31 per-player "national team shown as team" entries and the "apps counted the bench" entry are **FIXED** (commit
and test recorded), the rolling-window scope is ACCEPTED as labelled.

## 5. Match details nobody fetched — fixed

8,113 finished fixtures since July 2025 had never been asked for their detail (events, line-ups,
player rows): most national friendlies of 2026, the whole 2026/27 J1 League, King's Cup, and Friendlies
Clubs. The live follower reads matches while they are played; a match it never saw had no other way
in. `fbi.ingestion.backfill.seed_current_details` now queues detail units for every tracked current
season's played, never-fetched fixture before each backfill tick (priority 8, ahead of history,
inside the live-capture reserve); the first seeding queued **407 units** (≈ 8,100 fixtures) and the
backfill of 4 Oct fetched them all (19,156 backfill tasks done, 0 failed). What is still without player rows was
asked for and is empty at the provider (§3).

## 6. Rating

`rating` is `PROVIDER_DEFINED_METRIC`: "calculated according to the performance of the player in
relation to the other players of the game or the season who occupy the same position". Our
`avg_rating` is the mean of the provider's match ratings over matches played; the provider's season
rating is its own number. They are shown, never compared, never fed to a model as ground truth.

## 7. National side or club — PrediGol's own classification (4 Oct 2026, evening)

The provider's `team.national` is wrong both ways for some sides: 61 sides that play **only** national-team
competitions are flagged as clubs (youth national teams - Bolivia U20, Denmark U17, India U20 ... - and
Guadeloupe), 3 that play competitive club football are flagged national (Alo Egypt, France Aizenay, ...). The
product picked a player's club with that flag, so a youth national side could be shown as a player's club: **7 player
pages** did (45 players had a national youth squad counted as their club squad).

`core.team_kind` (migration 0060, `fbi/catalog/team_kind.py`, refreshed with the Elo job) decides from the
competitions a side plays: competitive club football (club scope, not a friendly) makes a club; only national-team
competitions, and no club friendly, make a national side; otherwise the provider's flag. Every product query that
picks a club or a national team reads it; the provider's flag is never overwritten. After the fix the players
audit (`python -m scripts.audit_players`, the product's own SQL over all 30,742 players of current tracked seasons)
finds **0 players whose club is a national side and 0 whose national team is a club**; 812 have only a national
side known (shown with no club). The 64 sides PrediGol classifies differently from the provider are evidence
entries `teams:national_flag:*` (provider at fault, MONITOR). Test:
`tests/integration/test_team_player_audits.py::test_a_youth_national_side_the_provider_flags_as_a_club_is_never_a_players_club`.

## 8. The provider's reference lists

Transfers, periods out (`/sidelined`) and trophies are read weekly for every player in scope (20 a request) and
shown on the player page with the payload each comes from; the provider's season aggregate per team and
competition (`/players?league&season`) is stored weekly in `core.player_season_stats` - its rating is the
provider's metric, kept as sent.
