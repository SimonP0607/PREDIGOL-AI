# Which competitions, and why — 2026-09-29

The mandate asked for 120 or more competitions, with one condition attached: *"No
agregues ligas únicamente para aumentar el número"*. This is the record of what was
selected, what was refused, and which of those judgements rest on measurement rather
than on a name.

Nothing here cost a provider request. `raw.league_coverage` already held one `/leagues`
call — 8,746 league-seasons across 1,247 leagues, twelve coverage flags each, observed
2026-09-29 — and that payload answers every question the selection asks.

## The bar

A season counts as **full detail** when the provider covers all four of `events`,
`lineups`, `statistics_fixtures` and `statistics_players`. Not any of them: a season
with fixtures and no statistics is a scoreline, and a model cannot be built on it.

Measured across the 1,247 leagues:

| seasons of full detail | leagues |
|---|---|
| ≥ 1 | 150 |
| ≥ 3 | 124 |
| ≥ 5 | 83 |
| ≥ 8 | 55 |

The minimum is three, which is what makes the count 124 rather than a target chosen
first and justified afterwards.

## Tiers

| tier | rule | competitions | full-detail seasons |
|---|---|---|---|
| 1 | reference set, already migrated and calibrated against | 6 | 73 |
| 2 | 8+ seasons of full detail | 49 | 499 |
| 3 | 5–7 such seasons | 27 | 163 |
| 4 | 3–4 such seasons | 40 | 139 |

**122 competitions for the historical migration; 124 tracked for live prices.** The two
numbers differ by the friendlies, below.

## The friendlies, and why they are tracked but not backfilled

Leagues 10 (Friendlies), 666 (Friendlies Women) and 667 (Friendlies Clubs) clear the
coverage bar comfortably — the provider records events, line-ups and both statistics
blocks for them. They are also, on the current season alone, among the largest
competitions on the account: 116 fixtures for Friendlies, 97 for Friendlies Clubs, and
one `/teams` call for Friendlies Clubs returned **3,973 teams**, which is what a
catch-all bucket looks like rather than a competition.

Nine seasons of results that say nothing about strength would sit in the same tables
every feature computation reads, and every consumer would have to remember to filter
them. So their history is dropped and their `elo_weight` is 0.

They stay **tracked**, because their odds are real markets and a pre-match window that
closes unobserved cannot be recovered. What is dropped is the history, not the capture.

The provider publishes no flag that says a competition is friendly — only the name. A
rule that reads names is exactly the drift this selection avoids elsewhere, so instead
the three ids are **pinned with the date they were observed**, in
`fbi.catalog.scopes.FRIENDLY_LEAGUES`, next to the query that re-checks them:

```sql
SELECT provider_league_id, league_name FROM raw.league_coverage
 WHERE league_name ILIKE '%friendl%';
```

Anything the provider adds later shows up as an unpinned competition to be judged
deliberately, rather than being guessed at.

## What the provider's two fields cannot decide

`league_type` and `country` determine league-versus-cup and domestic-versus-not. They do
**not** determine who plays. The UEFA Champions League and the World Cup are both `Cup`
with country `World`.

The first catalogue build read those two fields and therefore classified the World Cup,
the Euros, the Africa Cup of Nations, Copa America, every World Cup qualifying
confederation, the Nations League and UEFA U21 — about twenty national-team competitions
— as continental **club** football, each carrying a Champions-League rating weight of
0.90.

The missing fact is published on the team, not the competition: `/teams` returns
`national: true`. So the classification is settled from the teams actually recorded in a
competition, and `core.team_season_memberships` — written from that same `/teams`
payload — is the evidence of record, with fixtures as the fallback. Membership matters
because 34 of the 124 are out of season right now and have no fixture inside the sync
horizon at all.

Thresholds: at least 80% of the field national to call it national-team football, at most
20% to call it club. In between, a `PROVIDER_INCONSISTENCY` is recorded and **nothing is
changed**. A competition with no team on record records an `UNKNOWN_PROVIDER_ENTITY` and
keeps the value it had. The 80% is not 100% because a qualifying group can hold an
unflagged provider record, and one of those should not leave the World Cup classified as
clubs.

Result after `/teams` for the 124 current seasons (124 requests):

| | competitions |
|---|---|
| national-team football | 13 |
| club football | 109 |
| friendlies, weight 0 | 2 |
| undecided | 0 |
| contradictory | 0 |

The 34 issues opened while the evidence was missing were closed when it arrived, each
with the count that decided it. An entry reading *"undecided, needs /teams"* that
survives `/teams` answering costs an operator their trust in every other entry.

## What was refused, and on what grounds

1,125 competitions were evaluated and left out. Each carries the count that excluded it
(`scripts.select_competitions --excluded`), so a refusal can be argued with rather than
just observed. The overwhelming reason is fewer than three seasons of full detail.

## One judgement deliberately deferred

Nine of the selected competitions average **0–3 days per season**: the Community Shield,
the Trophée des Champions, and six domestic Super Cups plus the UEFA and CAF Super Cups.
They are one- or two-match competitions that pass a coverage-depth bar honestly but
contribute almost no data.

They were **kept**, for two reasons. Their cost is self-limiting — three seasons of one
fixture is three fixtures — and the measure that would separate them from the short
tournaments that *are* valuable is matches per season, which the `/leagues` payload does
not carry. The World Cup averages 32 days and 64 matches; the UEFA Super Cup averages 11
days and one match. Season span cannot tell them apart.

That number arrives free: `/fixtures?league&season` returns the real count, and the
migration spends one such call per league-season anyway. The gate, if one is wanted,
belongs in the planner keyed on the measured count — not in a guess made beforehand.

## Cost of the resulting migration

Priced before anything was spent (`scripts.migration plan --tiers 1,2,3,4`):

```
league-seasons 991 · fixtures 327,740 · requests 19,164 · raw storage 1,050 MB (gzip)
by unit kind: league_coverage 1, fixtures_season 956, fixture_details 16,318,
              standings_season 734, injuries_season 164, teams_season 991
by tier:      T1 1,140 · T2 8,508 · T3 3,898 · T4 5,617
```

Against the Ultra plan's 60,000-request internal guard, with a 35% buffer on every
estimate and 10% of the quota never touched by the backfill: 0.3 days of capacity, 97.6%
headroom over the measured live peak of 1,347 requests a day.
