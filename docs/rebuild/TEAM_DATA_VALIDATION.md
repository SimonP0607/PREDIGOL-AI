# Team data validation — data truth audit V2 (4 October 2026)

*Command: `python -m scripts.audit_team_stats [--history N]` (code `fbi/truth/v2/team_stats.py`,
`team_history.py`). Every provider answer is a new raw payload; nothing in `core` is written.
Ledger entries: area `team_stats` and `team_history` (`python -m scripts.audit_data_truth ledger`,
Admin → Data truth → Auditoría V2).*

## 1. What was compared

`/teams/statistics?league&season&team` is the provider's figure for **one competition and one
season** ("Returns the statistics of a team in relation to a given competition and season", updated
twice a day). PrediGol stores no copy of it — `core.team_season_stats` is empty — and computes every
team figure from its fixtures. Per team-season the audit recomputes, from our finished fixtures of
exactly that league and season: played / wins / draws / losses (home, away, total), goals for and
against, clean sheets, failed to score; and compares field by field, tolerance 0.

Teams audited (145 team-seasons, 225 requests with the thin-history sample):

* the mandate's: Manchester City (50), Real Madrid (541), Barcelona (529), Bayern München (157),
  Inter (505) — every competition of their last two seasons; a national team (Colombia, 8: World
  Cup 2026, qualifiers, friendlies); a women's team (Chelsea W, FA WSL 2026); a youth team (England
  U21, UEFA U21 Championship 2025);
* 10 random teams per golden league (Premier League, La Liga, Serie A, Bundesliga, Ligue 1), current
  and previous season.

## 2. Result

| Verdict | Team-seasons |
|---|---:|
| **ok** — every field equal | **140** |
| shootout_rule — equal under the provider's own rule (below) | 4 |
| provider_lag_expected — Chelsea W: a WSL match of that afternoon not yet in the provider's figures (it updates twice a day) | 1 |
| ours_missing / provider_behind / result_mismatch | **0** |

(Final run `20261004T153914Z`; the first runs had 141 ok — the Chelsea W match was played between them.)

**The data is right.** Same scope, same numbers, for every audited team — including Real Madrid's 14
Champions League matches of 2025/26 (9-0-5, 33-20), Bayern's 34 Bundesliga matches (28-5-1,
122-36), Colombia's 18 qualifiers (7-7-4, 28-18) and every golden-league sample.

The four differences are one **provider definition** (E-ledger `team_stats:provider_rule:shootout`,
`PROVIDER_DEFINED_METRIC`, ACCEPTED): `/teams/statistics` counts a match settled on penalties as won
or lost and gives the shoot-out winner one goal. Inter's 2025 Super Cup (1-1, lost on penalties):
provider 0-0-1 and 1-2, our fixtures a draw and 1-1. Same for City's and Barcelona's club friendlies
and Inter's. Recomputed with that rule, all four agree exactly. Football's result (and our models'
input) is the draw; neither side is wrong, the numbers just must never be compared without the rule.

The official tables confirm the same figures for the current season: the five golden leagues' and the
Champions League's official tables (132 rows, read on 4 Oct from premierleague.com, laliga.com,
legaseriea.it, bundesliga.com, ligue1.com, uefa.com) equal the provider's and ours on played and
points for every row (`STANDINGS_VALIDATION.md`).

## 3. What the user saw — and why it differed

**PRODUCT_SCOPE (PrediGol bug, high)** — the team page's "record" was
`catalog.team_record`: **every recorded result of the team in every competition and season since
2015**, unlabelled, e.g. Manchester City 491 matches across 8 competitions, shown next to the
provider's per-season figures and the standings. It mixed leagues, cups, friendlies and (for a
national side) every competition. Fixed (`c65d8af`, frontend `f753b28`):

* `record` is now the **domestic league's current season** (a national side: its latest
  competition), labelled "Premier League · temporada 2026";
* `records` lists every competition of the current campaign, one row each;
* `lifetime` keeps the old figure, written as "Todo lo almacenado: N partidos … en K competiciones
  desde … — no es una tabla de temporada".

The audit reads the page **through the product's own service** (`team_records` + `team_record_sections`), not a copy
of its query: the PRODUCT_SCOPE entry is FIXED in the ledger (E-025, commit and tests recorded) and a regression
would re-open it.

A second definition inside the product, **not changed** in this audit: the explorer's team analytics
(`explorer.team_results`) use the 90-minute score (what the models read), the record uses the final
score (the table's convention). Both are correct for their use; they differ only for matches with
extra time, and the explorer page should say "90 minutes" (open item).

## 4. Thin histories: 338 matches versus 0, 8 or 14

Fixtures per team (8,165 teams): 0 → 0 · 1–9 → 4,717 · 10–49 → 1,765 · 50–149 → 539 · 150–299 → 536 ·
300+ → 608. Big clubs have 300–500 because the migration holds 2018 onwards in every tracked
competition; most thin teams are clubs that appear only when they meet a tracked team (cup rounds,
club friendlies). 80 thin teams (< 20 fixtures) were classified with `/leagues?team` (one request
each): every league-season the provider has them in, against what we track and hold.

| Class | Teams | Meaning |
|---|---:|---|
| REAL_LOW_HISTORY | 30 | they play in competitions PrediGol does not track; we hold every match of theirs in what we track (ACCEPTED) |
| SEASON_NOT_MIGRATED | 50 | the provider has them in tracked competitions' seasons we never migrated: **Friendlies Clubs before 2026** (only the current season was migrated) and **every competition before 2018** (the migration floor) |
| MISSING_BACKFILL | 0 | a migrated season lacking their matches |
| IDENTITY_MAPPING_ERROR | 0 in the sample | (2 duplicate team rows found platform-wide: Nyasa Big Bullets ×2, St Blazey ×2 — `ENTITY_IDENTITY_AUDIT.md`) |
| PROVIDER_COVERAGE | 0 | the provider lists nothing for them |

The first run said MISSING_BACKFILL for those 50 — wrong: a catalogue row existed for those seasons
(the `/leagues` listing creates it) with zero fixtures. A season now counts as held only when it has
fixtures; the evidence entry was cleared by the re-run (the ledger keeps both).

Whether to migrate Friendlies Clubs 2020–2025 (the provider lists ~7,000 matches per season) and the
pre-2018 seasons is a product decision, not a correction: nothing that exists was lost, it was never
fetched (`HISTORICAL_DATA_SAFETY_PLAN.md`).

## 5. Evidence

`team_stats:product_scope:team_record` (PRODUCT_SCOPE, PrediGol — fixed in code, verified by
`tests/unit/test_team_record_scope.py`), `team_stats:provider_rule:shootout` (provider definition,
ACCEPTED), `team_history:SEASON_NOT_MIGRATED`, `team_history:REAL_LOW_HISTORY` (ACCEPTED). Reports:
`data/truth/20261004T142038Z-team_stats/`, `…T143829Z-team_stats/` and the post-fix run.
