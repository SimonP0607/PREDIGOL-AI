# Data validation rules

What the platform accepts as true, what it refuses, and how it decides that a dataset is
current. Every rule below is enforced in code (module named) and most by a test; none is a
convention someone has to remember. Written for GATE A of the critical rebuild (4 Oct 2026).

## 1. Identity

| Rule | Where | Why |
|---|---|---|
| A fixture's identity is the provider's fixture id. Its sides **follow the provider** when it corrects them, and the change is written to `audit.data_repairs` (`fixture_sides`). | `ingestion/fixtures.py` `upsert_fixtures` | The provider re-assigned the away side of club friendlies after we stored them; the old row kept the wrong team. |
| Provider id `0` is nobody: never a player or coach row. | `ingestion/identity.py`, migration 0043 | One "player" accumulated 3,926 unidentified people. |
| A player we never saw in a match is not created from the profile catalogue. | `ingestion/people.py` | The catalogue stays the players of our competitions (685k providers' players vs 179k ours). |
| A competition's gender and age group come from its name with the patterns in `catalog/segments.py`, the same expression the database uses for the generated columns. | migration 0048 | The provider has neither field; women's and youth football must not be pooled with the senior men's game. |

## 2. Status and results

| Rule | Where |
|---|---|
| The short status is upper-cased once, at the parser boundary (`canonical_status`); the group map, settlement and the live follower read it case-insensitively too. The provider sends both `CANC` and `Canc`. | `providers/api_football/normalize.py`, `ingestion/fixtures.py`, `picks/settlement.py` |
| Only `FT`, `AET`, `PEN` are finished. A postponed, cancelled, abandoned or awarded match never acquires a score, even when the provider reports 0-0. | `normalize.iter_fixture_results` |
| `fulltime` is the 90-minute score and is read, never derived by subtraction. A stated `fulltime` greater than the final score is ignored (recorded as a disagreement). | same |
| An `AET`/`PEN` match without a stated 90-minute score or an extra-time breakdown gets **no** result row (an awaited result beats a wrong one). | same |
| `extratime` greater than the final: no result, recorded. Parts that do not add up: `fulltime` is used, the disagreement recorded. | same |
| Writes to fixtures and results are **monotonic** on the payload's fetch time: an older payload never overwrites a newer one. | `ingestion/fixtures.py` `MONOTONIC_SQL` |
| A pre-match price can only be captured before kick-off (`minutes_to_ko` floored at 0; the truth audit counts any price captured after kick-off as CRITICAL). | `normalize.minutes_to_kickoff`, `truth/internal.py` |

## 3. League tables

| Rule | Where |
|---|---|
| A table row is keyed by (season, team, snapshot time, **group**): a team in a conference table and an overall table keeps both rows. | migration 0048 |
| The whole provider row is kept: goal difference, zone description, up/down marker, home and away split, the provider's own `update` stamp. | `details.iter_standings`, `ingestion/details.apply_standings_outcome` |
| A row for a team not in `core.teams` is counted (`rows_skipped`), never silently dropped. | same |
| Every request for a table is recorded in `core.context_checks` (asked at, content changed at), so "asked an hour ago, unchanged" differs from "never asked". | `ingestion/context_refresh.record_check` |
| **A table is current when its newest content is later than the season's last match end (kick-off + 2 h).** If it was asked for after that and is unchanged, the provider has not updated (UNAVAILABLE, its lag); if it was not asked for since, it is STALE (ours). | `truth/freshness.table_reason` |
| A pre-match view uses the newest snapshot **taken before kick-off**; no model reads a table taken after a prediction's cut-off. | `api/repositories/center.py` `STANDINGS` |

## 4. Freshness: FRESH / STALE / UNKNOWN / UNAVAILABLE

Four states, never more. STALE means the provider has newer data and asking was our job;
UNAVAILABLE means the provider does not have it (coverage flag says no, or we asked after the
event and it had not published). Service levels follow the provider's own update cadence
(`docs/api-football/06_UPDATE_FREQUENCIES.md`); code in `truth/freshness.py`.

| Dataset | Provider updates | FRESH when |
|---|---|---|
| fixtures (schedule) | every 15 s | the season's full list was read in the last 14 h (sync every 6 h, whole season per request) |
| results | every 15 s; some competitions up to 48 h | a match 3 h past kick-off has a final status; re-read and still NS = provider lag |
| live | every 15 s | a match in play was read in the last 3 min |
| standings | hourly | the table was read after the last match ended (re-asked hourly for 24 h after each match) |
| injuries | every 4 h | read in the last 6 h for a season playing in the next 48 h |
| lineups / match detail | 15 min / 1 min | a played match has them, read after it settled (≥ 150 min after kick-off) |
| pre-match odds | every 3 h | captured at the most recent window the match reached (T-72/48/24/12/6/3 h ± 45 min) |
| Elo | ours | every match finished in the last 30 days is rated (full recompute every 6 h) |
| teams | several times a week | identity read in the last 120 days |
| player profiles | several times a week | read in the last 45 days (monthly sweep) |
| squads | several times a week | read in the last 8 days (weekly round) |
| coverage flags | several times a day | read in the last 8 days (daily refresh) |

A dataset's overall state is STALE if any entity is stale; otherwise the state of most
entities, FRESH winning ties.

## 5. MODEL_DATA_GATE

Each model family declares what it reads (`truth/gate.py` `MODEL_NEEDS`); each input is
REQUIRED, OPTIONAL, UNAVAILABLE_BY_PROVIDER or NOT_USED. A fixture passes a model's gate only
when every REQUIRED input is present and current:

| Input | Passes when |
|---|---|
| fixtures | the fixture is stored with its competition and kick-off |
| results | both sides have ≥ 10 scored matches in the last two years |
| elo | both sides have a rating before kick-off |
| match_detail | both sides have shot data for ≥ 5 matches in the last year (else UNAVAILABLE_BY_PROVIDER if the provider publishes no statistics there) |
| odds_prematch | priced at the most recent capture window (above) by ≥ 2 bookmakers; asked and unpriced = UNAVAILABLE_BY_PROVIDER |

`odds_prematch` is REQUIRED of every family: a pick is a comparison with a price.

## 6. Repairs

A stored value is corrected outside normal ingestion only by a migration or a recorded rule,
and every correction is a row in `audit.data_repairs` (rule, entity, before, after, why,
evidence). Raw payloads are never modified or deleted; a correction can always be traced back
to the bytes that justified it.
