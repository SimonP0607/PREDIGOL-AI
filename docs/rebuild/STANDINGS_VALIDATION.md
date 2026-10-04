# Standings validation — data truth audit V2 (4 October 2026)

*Command: `python -m scripts.audit_standings [--league L --season S] [--external config/truth/external_standings_20261004.json]
[--decisions config/truth/official_decisions.json]` (code `fbi/truth/v2/standings.py`). One `/standings` request per
season, stored as a NEW raw payload; the audit writes only `audit.truth_v2_runs` and the evidence ledger (area
`standings`). Reports: `data/truth/<stamp>-standings/` on the machine. Final current-season run: `20261004T154333Z`.*

## 1. Method — three tables, and who is wrong

For each competition season three tables are compared row by row (team × table):

* **API** — `/standings?league&season` now;
* **DB** — our newest snapshot (`core.standings` at `max(snapshot_at)`), which is what the product shows;
* **FIX** — the table our own finished fixtures imply, for the phase or stage the provider's table describes
  (3 points a win). A table is matched to its rounds by agreement on games played; a phase that holds a regular
  season *and* a play-off group stage ("Apertura - 7" and "Apertura - Quadrangular - 3") is split by stage.

| Agreement | Verdict | Who |
|---|---|---|
| API = DB = FIX | ok | — |
| API ahead of DB | `predigol_behind` (or `predigol_lag_expected` when our hourly re-read after today's last match is due) | PrediGol |
| API = DB, FIX ahead | `provider_stale` (or `provider_lag_expected` under 3 h after the match: the provider updates hourly) | provider |
| API = DB, FIX behind | `fixtures_missing` | PrediGol |
| same games, points differ only | `adjusted` — a deduction or an award, checked against the official table | — |
| same games, W/D/L or goals differ | `provider_inconsistent` — its table and its fixtures disagree | to explain |
| table and fixtures name different team ids | `provider_identity` | provider |

**Results decided off the pitch** are counted at their official score, never silently: the provider's `AWD`/`WO`
score, and the decisions in `config/truth/official_decisions.json` (8 matches, each with its basis and sources: a
sports court, the league's disciplinary body, the press). A row that agrees only through one is `awarded`, and the
note names the fixture, both scores and the basis. Our fixtures keep the played (or stopped) score: bookmakers
settle on it and the models read it.

## 2. Official tables — the provider and PrediGol against the leagues' own sites

Read on 4 Oct 2026, 14:50–14:58 UTC, transcribed to `config/truth/external_standings_20261004.json` (played and
points per team, provider team ids):

| Competition | Official source | Rows | Provider vs official | PrediGol vs official |
|---|---|---:|---|---|
| Premier League 2026/27 | premierleague.com | 20 | 0 differences | 0 differences |
| LaLiga 2026/27 | laliga.com | 20 | 0 | 0 |
| Serie A 2026/27 | legaseriea.it | 20 | 0 | 0 |
| Bundesliga 2026/27 | bundesliga.com | 18 | 0 | 0 |
| Ligue 1 2026/27 | ligue1.com | 18 | 0 | 0 |
| UEFA Champions League 2026/27 (league phase) | uefa.com | 36 | 0 | 0 |
| **Total** | | **132** | **0** | **0** |

Tolerance 0 on played and points. The comparison is repeated by every run given `--external` (ledger keys
`standings:<league>:<season>:official:*`); none has ever been recorded.

## 3. Every current season with a table (92), final run

| Verdict | Seasons | Explained |
|---|---:|---|
| ok | 73 | — |
| adjusted | 8 | deductions in the provider's table, official: World Cup qualifying (South America, Ecuador −3), Championship (Southampton −4), Serie B (Juve Stabia −2), Chinese Super League (9 clubs), 1. Lig (Vanspor −2), Ligat Ha'al (Ironi Tiberias −6), Peru (UTC Cajamarca −5); Libertadores: Flamengo v Independiente Medellín awarded (`AWD`) |
| provider_lag_expected | 5 | FA WSL, Division 1 Féminine, Frauen-Bundesliga, Eerste Divisie, Serie A Women: matches ended under 3 h before |
| predigol_lag_expected | 3 | Nations League, Segunda División, Damallsvenskan: the provider updated after our 15:00 hourly re-read; the next re-read is due |
| provider_identity | 2 | the provider's table and its fixtures use two ids for one club: Sudamericana (Independiente 453 in the table, Independiente Petrolero 15702 in the fixtures), AFC Champions League Two (East Bengal 3463 vs East Bengal II 21137) |
| provider_stale | 1 | Chile Primera División: Coquimbo Unido and Huachipato each have one finished match more in the fixtures (23) than in the provider's table (22); the season's last match ended on 2 Oct, 40 h before the run |
| **predigol_behind / mismatch** | **0** | |

Chile also showed three rows whose W/D/L differ from the fixtures (Everton +3, Cobresal +3, Unión La Calera −6). The
ANFP disciplinary tribunal took six points from La Calera for fielding too many foreign players: rounds 1 (Everton
0-1 La Calera) and 2 (La Calera 3-1 Cobresal) were awarded 3-0 and 0-3 (ratified 8 Apr 2026; La Calera's appeal to
CAS was pending on 30 Sep). With those two decisions the three rows agree (`awarded`).

## 4. PrediGol bugs found, fixed, verified

| # | Bug | Effect | Fix | Verified |
|---|---|---|---|---|
| 1 | The context refresh read tables only for `type = 'league'` seasons | cups with a table (Nations League, UEFA Women's Champions League) stayed 5 days behind | `HAS_TABLE`: league type OR the coverage flag OR stored rows (`c65d8af`) | both `ok` since; `tests/integration/test_context_refresh.py` (cup test) |
| 2 | The pre-0048 writer kept one row per team | a team's second table (Apertura/Clausura, a third-place ranking, a championship round) was dropped: World Cup 2026 third-place ranking 48→60 rows, Euro 2024 24→30, AFCON 2025 24→30 … | `refresh_tables --legacy`: the rows were ADDED to the same snapshot from the very payload it was written from | **156 seasons**, each a row in `audit.data_repairs` (`standings_dropped_tables`, before/after) |
| 3 | A label the provider gives two tables merged them | Colombia 2022–2024: the Apertura and Clausura play-off groups are both "Group A"/"Group B" — a team in both kept one row; tables with no label (Colombia and Peru 2018, Challenger Pro League 2018) collided on ""; Nations League 2018–2022 "Group 1–4" of Leagues A–D merged into one table each | `labelled_rows` (parser and audit): the n-th table with a label is "&lt;label&gt; #n"; `refresh_tables --relabel` rebuilt each damaged snapshot as a **new** snapshot from its own payload, the old one kept | **16 seasons**, 616 → 669 rows (53 dropped rows back, 10 seasons un-merged); `audit.data_repairs` (`standings_group_label_collision`); tests below |
| 4 | Several tables of one season were judged as one by the audit itself (quadrangular rounds counted in the phase table) | false `provider_stale` / `predigol_behind` on Colombia | stages split from phases (`stage_of`) | golden Colombia 2023–2025 now 56/56, 56/56, 28/28 |

Tests: `tests/unit/test_standings_truth.py` (25: three tables, lags on both sides, deductions, AWD, decisions off the
pitch, repeated labels, play-off stages, identity), `tests/integration/test_data_truth_v2.py` (the real schema, the
relabel repair beside the damaged snapshot, decisions read against `core.fixtures`).

## 5. What the provider gets wrong (evidence entries)

* **Identity** (E-481, E-636): two team ids for one club between `/standings` and `/fixtures` — reported, both ids
  kept, never merged silently.
* **Stale tables**: Chile (E-017, current); **Ligue 1 2025/26 final table** (E-791, golden E-792): the provider's
  final table still shows Nantes and Toulouse on 33 games — it never counted the 0-0 the LFP homologated on 28 May
  2026 for their abandoned match of 17 May (Nantes 23 pts and Toulouse 44 at the provider; 24 and 45 in the official
  table, 34 games each). PrediGol's stored table is the provider's, so it carries the same two points short; our
  fixtures and the official decision give the right table.
* **Tables that apply a decision their fixtures do not** (explained, MONITOR): Bundesliga 2024/25 Union Berlin v Bochum
  (played 1-1, DFB court 0-2), four Colombian matches stopped by crowd trouble and awarded 0-3 by Dimayor (the
  provider's fixtures keep the score at the stop with status FT — 63rd minute for Patriotas v Pereira), Chile's two
  La Calera matches.
* **Coverage**: Colombia 2025 — `/standings` returns only the Clausura tables; the Apertura 2025 table is not served.

## 6. Cadence

The provider updates tables hourly. PrediGol re-reads a season's table hourly after each finished match until the
table changes (24 h at most), and every 12 h for every current season with a table, cups included. A table is shown
with its provider update time; a table older than the last finished match is never called current.

## 7. Past seasons and the golden dataset

The golden validation (`DATA_TRUTH_AUDIT_V2.md` §golden) re-audits 21 final tables of 7 competitions: 20 agree
row by row with our fixtures; the 21st is the Ligue 1 2025/26 table above (the provider's fault).
