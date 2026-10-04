# Competition phases — a season is not one table (4 October 2026)

*Code: `fbi/competitions/phases.py` (rules, mapping version `phases-1`), `fbi/competitions/tables.py` (loading,
per-match choice), `fbi/api/services/center.py` (Match Center and competition page). Command:
`python -m scripts.audit_competition_phases [--all | --league L --season S | --golden config/truth/phase_golden.json]`.
Reports: `data/truth/<stamp>-phases/` on the machine; final runs `20261004T173258Z` (all current seasons) and the
golden run of the same minute.*

## 1. The P0 defect

`/standings?league&season` returns **a list of tables** (`response[0].league.standings` is a list of lists, each
with its own `group` label): Colombia 2026 has an *Apertura* and a *Clausura* table, Argentina four zones
(*Apertura/Clausura - Group A/B*), a cup one table per group plus a ranking of third-placed teams. The tables were
stored separately, but the Match Center read them with `DISTINCT ON (team)` over the whole season: each team got
its newest row **from any table**. For Llaneros v América de Cali (fixture 1549811, *Clausura - 11*) one team came
from the Apertura table and the other from the Clausura table — the screenshot in the brief.

Replayed over every current season (92 seasons, 21,566 fixtures), the old query showed a team in a table that
was not the match's in **1,628 fixtures of 18 seasons**: 641 with the two teams in two different tables, 504 of
them upcoming. Worst: Peru 301, Eerste Divisie 284 (a period table), Ecuador 239, Argentina 220, Colombia 173,
Europa Conference League 100, World Cup qualifying Asia 92. The competition page had the same flaw (one list of
rows).

## 2. The model — season, phase, stage, table

| Term | What it is | Colombia 2026 example |
|---|---|---|
| season | `league + season` (`core.competition_seasons`) | Primera A 2026 |
| round | the provider's `fixture.league.round` | `Clausura - 11` |
| stage | the round without its trailing matchday number | `Clausura` (and `Clausura - Quadrangular` later) |
| phase | the first `" - "` segment of the round | `Clausura` |
| stage kind | `league` (a table is played), `knockout`, `qualifying`, `friendly` | `league` |
| table | one block of `/standings`, kept with its label, all/home/away, description, form and snapshot | `Clausura`, 20 rows |

Stage kinds come from words, never from league ids: a round with a matchday number is a league stage unless it
names a knockout (final, play-off, round of N, quarter/semi, 1/N, qualifying, promotion/relegation play-off,
third place, super cup, repechage, elimination); "Final Round/Stage/Phase/Tournament" with matchdays stays a league
(CONCACAF qualifying); league-format words always win.

**Mapping a table to a stage** (`map_tables`, at the table's snapshot time):

1. **label** — the table's label names a league stage or phase (`Clausura - Group A` → phase Clausura).
2. **games** — each team's games played agree (strict majority) with the games it had finished in one league
   stage, or in all of them, by the snapshot (window: finished before snapshot − 30 h … before snapshot, because the
   provider updates tables hourly and late).
3. **teams** — the one league stage that every team of the table plays in and none has played more games than the
   table says; tables parallel to another mapped table are excluded.

**Kinds**: `full` (one table for the stage), `group` (one of several tables of a stage), `ranking` (a table made of
rows of other tables, e.g. third-placed teams), `aggregate` (a table across stages, e.g. Peru's *Tabla Anual*),
`other` (a parallel period table such as Eerste Divisie periods, or a table no rule maps). A match is never shown
a `ranking`, `aggregate` or `other` table, nor a table of another phase.

**Choosing the table for a match** (`choose`): the table of the fixture's own stage that holds both teams; for a
knockout match, the league stage of the same phase that started before it (a quadrangular's or a cup's group
table) — or, when the season is not split into phases, the latest league stage; otherwise per team. The answer
carries `selection` (fixture_stage / previous_stage / phase_league_stage / per_team), the stage, the phase and the
mapping method, so the page says which table it shows and why. Results decided off the pitch (`AWD`, `WO`) count
as played. Nothing in the rules names a league: Colombia and Argentina are golden cases, not exceptions.

## 3. Results

| Run | Seasons | Tables | Kinds | Methods | Wrong table now |
|---|---:|---:|---|---|---:|
| all current seasons | 92 | 195 | full 86, group 101, ranking 3, aggregate 1, other 4 | games 155, label 37, unmapped 3 | **0** |
| golden (`config/truth/phase_golden.json`) | 12 | 64 | — | — | **0**, 41 checks PASS |

Stages without any provider table: 11, all the provider's — World Cup qualifying Asia (2nd Round groups A–I, 3rd
Round) and CONCACAF (2nd Round). Those matches show "no table for this stage", never another stage's table.
Unmapped: Eerste Divisie periods 2–4 (no matches in those periods yet; kind `other`).

| Case | Structure | What the Match Center shows now |
|---|---|---|
| Colombia 2026 (239) | Apertura and Clausura tables; quadrangulars later | the Clausura table for Clausura rounds; Llaneros #9 (11 PJ, 14 pts) and América #1 (11 PJ, 24 pts) |
| Argentina 2026 (128) | Apertura and Clausura, each in zones A and B | the zone of each team, of the fixture's phase (both teams can sit in different zones of the same phase) |
| Peru 2026 (281) | Apertura, Clausura, *Tabla Anual* | the phase table; the annual table is `aggregate` and only on the competition page |
| Ecuador 2026 (242) | regular season, then championship / placement / relegation groups | the group of the fixture's stage, never the regular season for a group match |
| Eerste Divisie 2026 (89) | regular season + four period tables | the regular season; period tables are `other` |
| Euro 2024 (4), Copa América, AFCON | groups + ranking of third-placed teams | the group; knockout matches show the group tables of both teams |
| World Cup 2026 (1) | 12 groups + a ranking table labelled "Group Stage" | the group; never the ranking |
| Libertadores / Sudamericana 2026 | qualifying, groups, knockout | qualifying: no table; groups: the group; knockout: the group of each team |
| CONCACAF qualifying 2026 (31) | 2nd Round (no provider table) and Final Round groups | the Final Round group; 2nd Round: no table |
| MLS 2026 (253) | Eastern and Western Conference tables | the conference of each team |
| Champions / Europa / Conference League 2026 | one league-phase table, qualifying and knockout rounds | the league phase; qualifying: no table |

**External check** (`config/truth/external_standings_20261004b.json`, compared per table by
`scripts.audit_standings --external`): Colombia *Clausura* against DIMAYOR (official, 20 rows) and Argentina
*Clausura* zones A and B against futbolargentino.com (secondary — the LPF site's Opta widgets did not load; 30 rows):
**0 differences** in played and points, for the provider and for PrediGol's stored tables.

## 4. What changed in the product and the API

* `GET /api/v1/matches/{id}/center`: `standings` rows carry `table`, `table_key`, `table_kind`, `stage`, `phase`,
  `fixture_stage` and `selection`; `standings_tables` holds every table of the stage for "show full tables".
* `GET /api/v1/competitions/{id}/standings[?season=]`: `seasons`, `stages` (kind, fixtures, finished, current),
  `tables` (one per table: label, kind, stage, method, agreement, rows with all/home/away, description, zone) and
  `mapping_version`; the flat `rows` list is kept, deprecated.
* Match Center: the caption names the table and the reason; the competition page has a season selector, stage
  tabs, all/home/away, and a stale note when the snapshot predates the last finished match.

## 5. Evidence and regression tests

Ledger keys (area `phases`): `phases:<league>:<season>:match_center_mixed` (FIXED, with the old and new tables of
example fixtures), `:current`, `:unmapped:<table>`, `:no_table:<stage>`, `:golden`.

Tests: `tests/unit/test_competition_phases.py` (45: stage and kind rules, label/games/teams mapping, ranking and
aggregate detection, period tables, the choice for league, group and knockout matches, Colombia, Argentina, Euro,
CONCACAF, MLS), `tests/integration/test_competition_phases_db.py` (4, including an `AWD` result), and
`tests/unit/test_standings_truth.py::test_an_official_table_is_compared_with_its_own_table_only`.
