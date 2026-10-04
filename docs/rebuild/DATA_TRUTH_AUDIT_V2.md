# Data truth audit V2 — PrediGol, 4 October 2026

*The question: is the data right along the whole chain — API-Football → RAW → normalisation → PostgreSQL →
features → models — and where it is not, who is wrong: the provider, our reading of it, the endpoint, the
season / league / phase, an old copy, the normaliser, or a sync that never ran. Every claim below is an entry
of the evidence ledger (`audit.evidence_ledger`, codes E-NNN; Admin → Data truth → Auditoría V2;
`python -m scripts.audit_data_truth ledger`) with the provider payload, our rows and, where one exists, the
external source behind it.*

Detail documents: [baseline](DATA_TRUTH_BASELINE_2026.md) · [standings](STANDINGS_VALIDATION.md) ·
[teams](TEAM_DATA_VALIDATION.md) · [players](PLAYER_DATA_VALIDATION.md) · [identity](ENTITY_IDENTITY_AUDIT.md) ·
[historical safety and DATASET_V2](HISTORICAL_DATA_SAFETY_PLAN.md).

## Verdict

**The data PrediGol holds is right where it was checked against the outside world, and every difference found
has a named owner.** 132 rows of six official league tables equal the provider's and ours; 20 of 21 golden
competition-seasons (20,540 of 20,542 checks) validate three ways; team statistics recomputed from our fixtures
equal the provider's for 140 of 145 team-seasons, the other five explained by its own definitions and timing;
the four named players' appearances, goals and assists equal FBref's in 8 of 8 season blocks.

What was wrong on our side was **how the data was read and shown**, not the stored match results: cup tables
never refreshed, two writers that dropped or merged table rows, player "apps" that counted the bench, a player
labelled with his national team, a team "record" mixing every competition since 2015, match details nobody
fetched. Each is fixed in code, with tests, deployed, and the stored data repaired additively (new snapshots,
new rows; nothing updated in place, nothing deleted).

The audit stays **PARTIAL** on three points that need the owner or time rather than code: the 50 thin-history
teams and two competitions whose older seasons were never migrated (a scope decision), the provider's duplicate
ids (an alias table to build with evidence), and a model-ready dataset (DATASET_V2) that has not been built.
**No model may be trained until DATASET_V2 exists**: research stays frozen.

## 0. Security

The Widgets Builder screenshot sent in the conversation showed the API key in the generated code: the key must be
treated as exposed. **SECURITY_ACTION: rotation recommended — the owner decides; it was not rotated without
authorisation.** The provider's dashboard pages (Widgets Builder, Live Demo, IDs) were not opened during the audit,
because they display the key; ids were checked through the API instead. The key's value was never written to chat,
markdown, logs, git, tests, JSON or URLs; the secret scan (both working trees, both git histories, logs, the
scratch folder, every audit report and the newest raw payloads) finds it only in `.env`.

## 1. Sources and their weight

| Level | Source | Used for |
|---|---|---|
| 1 — official | premierleague.com, laliga.com, legaseriea.it, bundesliga.com, ligue1.com, uefa.com | current tables, 132 rows (`config/truth/external_standings_20261004.json`) |
| 1 — official | dfb.de (DFB Sports Court, Federal Court), bundesliga.com 2024/25 table, ligue1.com (LFP disciplinary commission) | results decided off the pitch (`config/truth/official_decisions.json`) |
| 2 | FBref (Opta-based) | player season figures, 8 blocks (`config/truth/external_players_20261004.json`) |
| 2 | Football-Data.co.uk results files | golden validation, every result of 15 seasons of the five big leagues |
| 2 | Eurosport (Ligue 1 2025/26 final table); Colombian and Chilean press (El Heraldo, Claro Sports, El País, Blu Radio, The Clinic, En Cancha, Emol) | Dimayor and ANFP decisions; the Dimayor resolutions themselves were not read |
| — | Transfermarkt | not used: consent-or-pay wall (never accepted) |

Widgets are a **reference only**: they render the provider's own data in the browser, with the key in the page;
PrediGol never reads them and never embeds them.

## 2. API-Football — what was inspected

* **Documentation** (v3): `/leagues`, `/fixtures` (+ `?ids` with events, line-ups, statistics, players),
  `/standings`, `/teams`, `/teams/statistics`, `/players`, `/players/teams`, `/players/squads`,
  `/players/profiles`, `/injuries`, `/coachs`, `/venues`, with their update frequencies (fixtures every 15 s,
  tables hourly, team statistics twice a day, player statistics and squads several times a week, injuries every
  4 h) and their scope rules ("calculated according to the team id, league id and season"; rating relative to
  position; squads current only; ids never reused).
* **Widgets** (League, Standings, Teams, Players docs pages): their data is the API's; capabilities noted,
  nothing taken from them.
* **IDs**: every entity keyed by the provider's own id; checked through the API (teams 10/10, player profiles
  10/10, venues 5/5, coaches 1/5 equal to ours on a random sample — `ENTITY_IDENTITY_AUDIT.md`).
* **Requests**: 3,365 in 48 audit runs (`audit.truth_v2_runs`), each answer kept as a NEW raw payload (594
  distinct payloads from 12 endpoints, plus the five 2025/26 Football-Data files read from a copy); daily guard
  60,000, never near it.

## 3. Baseline (block A)

Verified dump (1,033 TOC entries, sha256), RAW archive, tags, a count snapshot and a **restore test** (91 tables
restored in 91 s, 0 fewer rows) before anything was touched; research frozen (`data/research.frozen`). Every one
of the 225,753 fixtures points at an indexed raw payload. Details: `DATA_TRUTH_BASELINE_2026.md`.

## 4. Leagues and seasons (block C)

124 tracked competitions against the provider's 1,247: type, country and current season right for all of them;
no duplicate competition, no wrong season shown. **Mismatch**: `SEASON_NOT_MIGRATED` ×2 — Friendlies (2018–2025)
and Friendlies Clubs (2020–2025) have catalogue rows but no fixtures: the migration took their current season
only (E-465, scope, not corruption).

## 5. Fixtures and results (block D)

| Check | Result |
|---|---|
| Season lists, 124 current seasons | provider 32,302, ours 32,303; 32,452 of 32,464 compared equal |
| Status sample (FT, AET, PEN, NS, PST, CANC, ABD, AWD, WO — 156 fixtures) | 0 findings |
| Results | 18,661 of 18,662 equal |

The differences: 11 matches the provider still showed as not started after kick-off (its lag, E-467); one fixture
the provider **moved** from Friendlies to the Kirin Cup (1632353, Panama v New Zealand, an untracked league) that we
still hold under Friendlies (E-466, PrediGol stale competition); one result whose provider score blocks contradict
each other — final 2-0 after extra time, "fulltime" 4-0, "extratime" 0-2 — for which the writer keeps no result
rather than a wrong one (E-923, provider; five such fixtures platform-wide).

## 6. Standings (block E — priority)

*Full detail: `STANDINGS_VALIDATION.md`.*

* **API vs DB**: 92 current seasons — 73 ok, 8 adjusted (deductions and an awarded match, official), 5 provider lag
  under 3 h, 3 our hourly re-read pending, 2 provider identity errors, 1 provider stale (Chile); **0
  predigol_behind / mismatch**.
* **API vs official**: six official tables, 132 rows — **0 differences** on played and points, the provider's or ours.
* **Root causes fixed**: cups with tables were never refreshed (Nations League, UEFA Women's Champions League 5 days
  behind); the pre-0048 writer dropped a team's second table (156 seasons completed from their own payloads); a
  repeated table label merged tables (16 seasons rebuilt as new snapshots: Colombia 2022–2024 lost play-off rows,
  Nations League 2018–2022 merged Leagues A–D).

## 7. Teams (block F — priority)

*Full detail: `TEAM_DATA_VALIDATION.md`.*

* **API vs DB**: `/teams/statistics` for 145 team-seasons (the five clubs named, a national, a women's and a youth
  team, 10 random teams per golden league) — **140 equal field by field**, 4 differ only by the provider's
  shoot-out rule (it counts a match settled on penalties as won/lost, ACCEPTED as its definition), 1 provider lag
  (Chelsea W, a match of that afternoon).
* **What the user saw**: the team page's "record" added every result since 2015 in every competition — fixed: one
  competition and season as the headline, the campaign per competition, the lifetime figure labelled.
* **Missing history**: 80 thin teams classified — 50 `SEASON_NOT_MIGRATED` (Friendlies Clubs before 2026, seasons
  before 2018), 30 `REAL_LOW_HISTORY` (they play where we do not track), 0 missing backfill, 0 provider coverage.
* **Identity**: 2 duplicate team pairs (Nyasa Big Bullets, St Blazey) — provider-side, to resolve by alias.

## 8. Players (blocks G–H — priority)

*Full detail: `PLAYER_DATA_VALIDATION.md`.*

* **API vs DB**: `/players` season blocks for 104 players (Raphinha, Lamine Yamal, Haaland, Kane and 20 random
  players per golden league; seasons 2025 and 2026) — **737 blocks, 523 equal**. Every other block is explained,
  and **none is a wrong figure of ours**: 46 differ only in starts by 1–2 (the provider's season "lineups" against
  its own per-match substitute flag — a definition); 28 were settled by re-reading their matches on 4 Oct
  (`/fixtures?ids`, 28 of 28: our rows equal the provider's per-match data exactly, its season aggregate is what
  differs); 30 are teams whose matches the provider serves with an empty players block (fetched, nothing to store);
  17 are players its per-match lists omit while its aggregate counts them; 14 are its aggregate lagging our match
  rows ("several times a week"); 47 sit in seasons never migrated and 32 in competitions we do not track.
* **External**: FBref — appearances, goals and assists equal in **8 of 8** blocks for the four players (2025/26 and
  2026/27), minutes within 0–8 (stoppage time).
* **Incorrect fields, fixed**: "apps" counted unused substitutes (23.8 % of match rows have no minutes); the player
  list and page showed the **last appearance** as his team (Raphinha "Brazil", Kane "England") — now club (newest
  club squad, else last club appearance), national team and last appearance are three fields; the 400-day totals
  are labelled and the season table is per competition, season and team.
* **Identity**: 155 people carry two provider ids (311 rows — their statistics are split); display names are
  shared by different people (three "Raphinha"s), harmless because every join is by id.
* **Rating** is `PROVIDER_DEFINED_METRIC` (position-relative): shown, never compared, never a model target.
* Current club / national team / injuries for the four: Barcelona · Brazil · 3/3 injuries (Raphinha), Barcelona ·
  Spain (Lamine Yamal), Manchester City · Norway (Haaland), Bayern München · England (Kane); provider = ours.

## 9. Identity and the rest of the catalogue

Provider id is the key of every entity (a `provider` column becomes necessary before a second source — accepted
design note). Provider duplicates: 2 team pairs, 155 people under two player ids (311 rows), 80 venue groups
(162 rows). 12,970 coaches, of whom those known only from line-ups lack nationality and birth date; coach careers (team, start, end) are not stored
(`UNSUPPORTED_FIELD`). Squads exist from 4 Oct 2026 (the provider serves only the current squad): 2,286 teams,
62,476 rows, `captured_at` per row. Injuries: every tracked fixture of the next 48 h had its list checked in the
last 6 h. `ENTITY_IDENTITY_AUDIT.md`.

## 10. Data lost by normalisation (block I)

`python -m scripts.audit_data_truth fields` inventories every field of 580 `/fixtures` items, 9,023 player rows,
`/standings` and `/injuries` payloads against what the normalisers store and what any feature, model or page reads:

* `DROPPED_USEFUL_FIELD` — the fixture's **referee** (275/580), `league.standings` (whether a competition has a
  table: 580/580 — it would have kept cups in the table refresh), `teams.*.winner` (who went through a tie,
  366/580), a player's **position that match** (8,375/9,023), **offsides** (7,818), **dribbled past** (341),
  **penalties won / conceded / saved**; and, found by the golden check, **the official score of a match awarded
  off the pitch** (the provider sends it with status AWD/WO; we store no result).
* `UNSUPPORTED_FIELD` — coach careers; arrays that came back empty in the sample.
* `INTENTIONALLY_IGNORED` — 31 stored fields read by nothing (ACCEPTED).

All are added in DATASET_V2 as new columns filled from RAW (no request).

## 11. Golden dataset (block J)

Seven competitions — the five big leagues, the Champions League, Colombia's Primera A — three complete seasons
each (2023, 2024, 2025: 21 competition-seasons), checked three ways: the provider's season list and scores against
ours, the provider's final table against the table our fixtures imply, and every Football-Data result (big five)
against our fixture and score. Results decided off the pitch are counted at their official score and listed.

| Competition | 2023 | 2024 | 2025 |
|---|---|---|---|
| Premier League | VALIDATED 1.0 | VALIDATED 1.0 | VALIDATED 1.0 |
| La Liga | VALIDATED 1.0 | VALIDATED 1.0 | VALIDATED 1.0 |
| Serie A | VALIDATED 1.0 | VALIDATED 1.0 | VALIDATED 1.0 |
| Bundesliga | VALIDATED 1.0 | VALIDATED 1.0 ¹ | VALIDATED 1.0 |
| Ligue 1 | VALIDATED 1.0 | VALIDATED 1.0 | **NEEDS_REVIEW 0.972** ² |
| Champions League | VALIDATED 1.0 | VALIDATED 1.0 | VALIDATED 1.0 |
| Primera A (Colombia) | VALIDATED 1.0 ³ | VALIDATED 1.0 ³ | VALIDATED 1.0 ⁴ |

¹ Union Berlin v Bochum, 14 Dec 2024: played 1-1 (the provider's fixture and ours), awarded 0-2 by the DFB Sports
Court on 9 Jan 2025 (appeal rejected 28 Feb 2025); the provider's and the official table count 0-2, Football-Data
records 0-2.
² The provider's **final table** never counted the 0-0 the LFP homologated for Nantes v Toulouse (abandoned 17 May
2026): Nantes 33 games / 23 pts and Toulouse 33 / 44 at the provider, 34 / 24 and 34 / 45 officially. Our fixtures,
the provider's fixture list and every Football-Data result agree; the provider's table is wrong (E-791, E-792).
³ Four matches stopped by crowd trouble and awarded 0-3 by Dimayor (Once Caldas v Alianza 2023; Patriotas v
Pereira, Cali v Pasto, Nacional v Junior 2024): the provider's table counts 0-3, its fixtures the score at the stop.
Before the audit's fixes these seasons failed on our own bug (merged "Group A/B" tables).
⁴ Two matches the provider itself lists as AWD 0-3.

**Validation score**: 20 of 21 seasons GOLDEN_VALIDATED; 20,540 of 20,542 checks agree (99.99 %); the two that do
not are the provider's Ligue 1 table rows. Command: `python -m scripts.audit_data_truth golden --decisions
config/truth/official_decisions.json`.

## 12. Provider issues

* Identity: `/standings` and `/fixtures` name different team ids for one club (Sudamericana: Independiente 453 /
  Independiente Petrolero 15702; AFC Champions League Two: East Bengal 3463 / East Bengal II 21137).
* Stale tables: Chile 2026 (two team-matches not counted 40 h after); Ligue 1 2025/26 final table (above).
* Tables that apply an official decision their fixtures do not, with matches stopped early reported as FT: Bundesliga
  2024/25, Colombia (4), Chile 2026 (2 La Calera matches awarded by the ANFP tribunal, CAS appeal pending).
* Coverage: Colombia 2025 `/standings` serves only the Clausura; 14,450 finished matches of tracked competitions in
  the last 450 days were fetched with an **empty players block** (early cup rounds, lower divisions, women's,
  friendlies) while its season figures may count players.
* Self-contradicting score blocks (5 extra-time fixtures); 11 fixtures not updated after kick-off.
* Player season figures (`/players`) that differ from its own per-match data, and update "several times a week"
  (14 blocks behind our match rows).
* Duplicate ids: 155 people under two player ids, 2 team pairs, 80 venue groups.

## 13. PrediGol bugs — found, fixed, tested, deployed

| Bug | Fix (commit) | Test |
|---|---|---|
| cup tables never refreshed (`type = 'league'` only) | `HAS_TABLE` (c65d8af) | `test_context_refresh.py` cup test |
| pre-0048 writer dropped second tables | `refresh_tables --legacy`, 156 seasons completed from their own payloads | `audit.data_repairs` before/after |
| repeated table label merged tables | `labelled_rows`, `refresh_tables --relabel`, 16 new snapshots (c977a9a) | `test_standings_truth.py`, `test_data_truth_v2.py` |
| player "apps" counted unused substitutes | apps = minutes > 0 everywhere (c65d8af) | `test_data_truth_v2.py` |
| player shown with his national side as "team" | club / national team / last appearance (c65d8af, f753b28) | `test_data_truth_v2.py` |
| team "record" mixing every competition since 2015 | headline per competition-season, lifetime labelled (c65d8af, f753b28) | `test_team_record_scope.py` |
| 8,113 played matches never asked for details | `seed_current_details` before every backfill tick (c65d8af) | `test_backfill.py` |
| one fixture moved by the provider to another league kept under the old one | — open (E-466) | — |

The audit's own errors were fixed the same way (quadrangular rounds, a wrong "wrong season" on past seasons, lag on
our side, player blocks the provider's coverage explains, product views copied instead of read) — each with a test.

## 14. Stale data

* Our tables: never older than one hourly re-read after a finished match at the end of the audit (3 seasons were
  within that hour).
* Coaches known only from line-ups (no nationality / birth date); 6,262 players never profiled; squads begin on
  4 Oct 2026.
* The Kirin Cup fixture above. No match row of ours was found older than the provider's per-match data: the 28
  player blocks re-read on 4 Oct matched exactly.

## 15. Evidence ledger

417 entries at the close (4 Oct 2026, 15:56 UTC):

| Status | Entries | |
|---|---:|---|
| OPEN | 107 | 97 the provider's, 8 PrediGol's, 2 undetermined; 1 high (the provider's Ligue 1 2025/26 table), 0 critical |
| MONITOR | 12 | deductions and awards in tables, each to confirm with the official table |
| ACCEPTED | 6 | the owner's verdict: provider definitions (shoot-out rule, rating), scope (real low history), design notes |
| FIXED | 35 | PrediGol bugs fixed in code, with the commit and the test that proves it |
| CLEARED | 257 | no longer reproduced by a later run (kept, with the run that cleared them) |

The 8 open on our side: seasons never migrated (Friendlies 2018–2025, Friendlies Clubs 2020–2025, 50 thin-history
teams, 47 player blocks — one scope decision), the fixture the provider moved to the Kirin Cup, 3 national sides
flagged in club competitions, the dropped useful fields, one player id with match rows but no profile row, coach
careers not stored. None is a wrong stored result.

## 16. Historical safety

RAW is untouched: every audit request is a new payload; the content-addressed store cannot rewrite one. The
history was never updated in place or deleted: tables were completed or rebuilt as **new** snapshots from the
payloads they were written from (156 + 16 seasons, each a row in `audit.data_repairs` with before, after, reason
and payload hash); details and table snapshots were added. `core.fixtures`, `core.fixture_results`, `market.*` and
`features.*` were not modified by the audit. Backups: pre-audit (verified, restore-tested) and post-audit (below).
Plan and DATASET_V2 steps: `HISTORICAL_DATA_SAFETY_PLAN.md`.

## 17. Model readiness

**NO.** Research is frozen (`data/research.frozen`); no model was trained, stored or promoted; no new public pick.
The match results the models read are right where checked (golden 20/21, the 21st the provider's table), but the
model inputs are still the pre-audit dataset: DATASET_V2 — fixtures flagged by result basis (played / stopped /
awarded), official decisions, the dropped useful fields, alias-merged identities, a `dataset_version` on every
feature row — must be built from RAW and pass the golden set first, and the owner must unfreeze research.

## 18. Gates

| Gate | Result |
|---|---|
| `ruff check .` | clean |
| `mypy .` | 507 files, no issue |
| `pytest -q` (unit + integration against a scratch PostgreSQL) | **1,400 passed** |
| Standings / team / player / identity truth tests | `test_standings_truth.py` 25 · `test_team_player_truth.py` 14 · `test_truth_compare.py` 20 · `test_data_truth_v2.py` 10 (real schema: ledger, standings run, relabel repair, decisions, player recheck, admin endpoints) · `test_team_record_scope.py` 3 · `test_catalog_truth.py` 6 · `test_research_freeze.py` 6 |
| Frontend | typecheck clean, lint 0 errors (26 warnings, the baseline), production build, 91 unit tests |
| Backup | pre-audit (13:46 UTC): verified dump + RAW archive + sha256 + **restore test**; post-audit (16:00 UTC): dump `fbi-20261004T160044Z-post-data-truth-audit-v2.dump` (1,053 TOC entries, 512 MB), RAW archive (27,494 entries), sha256 in `~/backups/SHA256SUMS-post-data-truth-audit-v2` (re-verified OK), tags `post-data-truth-audit-v2` (backend e8e64ac, frontend 27b1da8) and a **restore test**: rc 0 in 61 s, 93 tables, 74 equal, 19 grew since the dump (live capture), 0 fewer, 39,250,328 rows |
| RAW untouched | content-addressed store, keyed by hash; the audit only added payloads |
| Secret scan | the key's value only in `.env` |
| Deployed | backend through the `be-43` … `be-50` bundles (migrations at head 0056), API and worker restarted, health 200; never pushed to GitHub |

## 19. Remaining issues and the next safe action

**Critical remaining issues** (nothing in the ledger is critical; these are what stands between the audit and a
model):

1. **The API key appeared in a screenshot in this conversation** — rotation recommended; the owner decides and
   rotates it on the provider's dashboard (not done without authorisation).
2. **DATASET_V2 does not exist** — result basis (played / stopped / awarded), official decisions, the dropped
   useful fields and the identity aliases are not in the model inputs yet; research stays frozen.
3. **The provider's Ligue 1 2025/26 final table is wrong** (and so is our stored copy): Nantes and Toulouse one
   game and one point short of the official table. Tables for models must come from fixtures + official decisions.
4. **Scope never migrated**: Friendlies 2018–2025, Friendlies Clubs 2020–2025 and every season before 2018 — a
   decision for the owner (≈7,000 club friendlies a season), not a correction.
5. **Provider duplicates**: 155 people, 2 team pairs, 80 venue groups — alias table with evidence, applied in reads.
6. **Open details**: the fixture the provider moved to the Kirin Cup; Dimayor's resolutions read through the press
   (level 2); La Calera's CAS appeal pending (the decisions file must follow its outcome).

**Exact next safe action**: the owner rotates the API-Football key (dashboard → new key → `.env` on the machine →
restart API and worker → secret scan). Then, with the owner's go, DATASET_V2 steps 1–2 of
`HISTORICAL_DATA_SAFETY_PLAN.md`: the `analytics.dataset_versions` table and the new normaliser columns (result
basis, official score, referee, tie winner, player position, offsides, dribbled past, penalties) with tests,
replayed from RAW into a scratch schema and compared with `core` table by table — no training, no promotion, no
public pick until the golden set passes on it and the owner unfreezes research.
