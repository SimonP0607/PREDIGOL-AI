# Entity identity audit — data truth audit V2 (4 October 2026)

*Command: `python -m scripts.audit_data_truth identity` (code `fbi/truth/v2/identity.py`): database
checks with no request, plus provider samples (`/teams?id`, `/players/profiles?player`, `/coachs?id`,
`/venues?id`). Ledger area `identity` / `coaches`.*

## 1. The key

Every entity is keyed by the provider's own id (`provider_team_id`, `provider_player_id`,
`provider_coach_id`, `provider_venue_id`, `provider_fixture_id`, `provider_league_id`), unique, never
reused by the provider ("The fixtures ids are unique … In no case an ID will change"; "players keep
it among all the teams they have been in"; "teams keep it among all the leagues/cups"). Joins are by
id, never by name. With one provider the provider is implicit; **a second data source would need
`provider + provider_id`** (a `provider` column on the identity keys) — recorded as an accepted design
note (`identity:keys`), to be done before any second source is wired in. The IDs pages of the
provider's dashboard were not opened: the dashboard is the account page that also displays the API key
(see the security note in `DATA_TRUTH_AUDIT_V2.md`); ids were checked through the API instead.

## 2. Findings

| Check | Result | Who / class |
|---|---|---|
| Team rows sharing a name and country | **2 pairs**: Nyasa Big Bullets (4596, 4599, Malawi), St Blazey (12112, 28344, England) | provider duplicates — `DUPLICATE_ENTITY`, to confirm on the provider's pages; merge only through an alias map, never silently |
| Players with the same full name **and** birth date under two ids | **155 people, 311 rows** (e.g. Afonso Sousa 2007-04-17: 561571 / 620093; the audit now reports the total, not its 50 examples) | provider duplicates — their statistics are split between two ids; `DUPLICATE_ENTITY` (E-470) |
| Display names shared by different people | 11,891 names over 33,701 players (three "Raphinha": 1496, 350428, 354362 — three different men) | harmless while every join is by id; the search box lists all of them |
| Match rows of a player without a `core.players` row | 1 | `MAPPING_ERROR`, low |
| Players never profiled | 16 of 179,298 (37,052 without a birth date — the provider has none) | fine |
| `is_national` flag | 453 national, 7,709 club, **3 unknown** (NULL); 3 national rows play club competitions | the product now reads an unknown flag as a club |
| Venue rows sharing a name and city | 80 groups, 162 rows (Allianz Stadium Sydney 7955/20808, Arena Khimki, Arena Lviv …) | provider duplicates, `DUPLICATE_ENTITY`, low |
| A fixture the provider moved to another competition | 1632353 Panama v New Zealand (1 Oct 2026, 1-1, 3-5 pens): the provider now lists it in the **Kirin Cup** (916, untracked, semi-final); we hold it under Friendlies 2026 | PrediGol `STALE_ENTITY` (E-466): a held fixture missing from its season list is not re-read by id; re-home it through `audit.data_repairs` (DATASET_V2) |
| Coaches without nationality / birth date | 12,866 — created from line-ups (name only); `/coachs` never asked for them | `STALE_ENTITY`; the sample of 5 coaches: 1 matches, 4 lack fields or differ (coach 3933's current team: provider Stockholm Internazionale, ours the team of his last line-up) |
| Coach career (team, start, end) | **not stored** — `/coachs` returns it, `core.coaches` keeps only the person | `UNSUPPORTED_FIELD` — a coach's tenure cannot be read from the database |
| Provider samples (random, two runs) | teams 10/10 equal, player profiles 10/10, venues 4/5 then 5/5 (Stade Saputo: "Montreal, Quebec" vs "Montreal"), coaches 1/5 (the other four lack nationality and birth date: created from line-ups) | — |

## 3. Squads

`/players/squads` returns the **current** squad only — there is no season parameter. PrediGol keeps
each player's `first_seen_at` / `last_seen_at` per team (weekly round, started 4 Oct 2026 06:49):
2,286 teams, 62,476 rows, none older than 14 days. The effective season of a squad is therefore
"the season in progress at capture time"; history of squads starts on 4 Oct 2026 and grows weekly.
838 players appear in two clubs' newest squads at once (loans, or a transfer the provider has not
removed from the old squad): the product's **club** takes the most recently captured one.

## 4. Injuries

`/injuries` is updated every 4 h by the provider and data exists from April 2021. On 4 Oct, all 95
tracked fixtures in the next 48 h had their season's injury list checked in the last 6 h (oldest check
11:02 UTC). For the four focus players: provider 3 / ours 3 (Raphinha), 0 / 0 for the others.

## 5. Current club vs national team vs last appearance

See `PLAYER_DATA_VALIDATION.md` §4: three separate fields since 4 Oct (club from the newest club
squad, else the last club appearance; national team likewise; last appearance as it was).

## 6. Next (not done here)

* An alias table `(provider, provider_id) -> canonical id` for the 155 player and 2 team duplicates,
  each entry with its evidence (the provider's pages), applied in reads — never by rewriting rows.
* `/coachs?id` for the coaches we know only from line-ups, and the career as dated rows.
* `provider` column on identity keys before a second source.
