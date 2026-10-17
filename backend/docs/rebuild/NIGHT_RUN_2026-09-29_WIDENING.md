# Widening the migration to 122 competitions — 2026-09-29

What this run did, what it found, and what it deliberately did not do. Every number is a
query against the machine's database or a count from its raw store on that date.

## The shape of the run

The mandate asked for 120 or more competitions, chosen on API-Football's real coverage,
with live odds capture never sacrificed to history. Three things had to happen in order:
decide which competitions on evidence, get the current season and its fixtures in so the
odds capture had something to plan against, and only then spend the quota on history.

It also asked for something harder: fix what is wrong rather than work around it. Five
defects came out of that, and they are the substance of this run.

## What was already broken

### 1. The 90-minute score was reconstructed by subtraction

Four generated columns — `reg_goals_*`, `outcome_1x2`, `total_goals`, `btts` — derived the
score at ninety minutes as `goals - COALESCE(et_goals, 0)`. Those four settle 1X2,
Over/Under and BTTS: they are the core markets.

Measured over the 1,645 `AET`/`PEN` fixtures in the raw store carrying a non-null
`extratime`:

| relation | fixtures | what `extratime` means there |
|---|---|---|
| `goals == fulltime + extratime` | 1,557 | goals scored **during** extra time |
| `goals == extratime` | 82 | the **running total** after extra time |
| neither | 4 | — |

In those 82 the subtraction yields 0, so a tie that stood 2-1 after ninety minutes was
stored as `reg_goals 0-0` and settled `outcome_1x2 = 'Draw'`. **78 rows were wrong when
first measured; 323 by the time the migration had widened**, because every new knockout
competition brought more.

The guard written for exactly this rejected `et > goals` and not `et == goals`, which is
the corruption's actual signature.

The provider states the score in `score.fulltime`. Revision 0031 reads it into
`ft_goals_*` and the four columns became
`COALESCE(ft_goals, goals - COALESCE(et_goals, 0))`. A value that is read cannot be wrong
about the semantics of a different field.

Correcting it cost **no provider requests**: every payload was already on disk.
`reprocess_results` re-derived 219,288 results from 1,934 stored payloads. Afterwards, of
3,580 AET/PEN results checked against the raw store, **0 disagree** with the provider's
stated fulltime, against 78 before.

### 2. A tie that went straight to penalties was thrown away

A `PEN` fixture whose `extratime` is null did not lose its data — it went from ninety
minutes to penalties, which is how several competitions are played, and the provider
records that by leaving extratime null. The normaliser skipped such fixtures wholesale, so
**six Champions League ties had no result row at all** while `score.fulltime` stated the
score plainly. They now settle correctly (1383439: 2-0 Home, shoot-out 11-10).

### 3. The fixtures horizon was four days, with prices measured at T-18.2 days

The worker synced fixtures four days ahead — the Free-plan figure, kept after the upgrade
by oversight. A fixture ten days out was not a row in `core.fixtures` at all, so the odds
capture planner had nothing to plan against and the opening of its price series — the part
no later request can recover — was never captured.

`MEASURED_FIRST_PRICE_DAYS = 19` and `DEFAULT_HORIZON_DAYS = 21` now live in one leaf
module that the sync, the worker and the probe all read, with one sync interval of margin.
Under `--strategy league` the wider horizon costs nothing: it only changes the `from`/`to`
of the one request per competition-season.

Effect the same day: fixtures the planner could see went from nothing to **322**, and odds
snapshots from **663 on 2 fixtures to 11,890 on 28**. The capture had been idle since
25 September.

### 4. The World Cup was catalogued as club football

`league_type` and `country` determine league-versus-cup and domestic-versus-not. They do
not determine who plays: the UEFA Champions League and the World Cup are both `Cup` with
country `World`. About twenty national-team competitions — the Euros, Copa America, the
Africa Cup of Nations, every World Cup qualifying confederation, the Nations League, UEFA
U21 — were catalogued as continental **club** competitions with a Champions-League rating
weight of 0.90.

`/teams` publishes the missing fact on the team (`national: true`).
`core.team_season_memberships`, written from that same payload, is the evidence of record,
with fixtures as the fallback — membership matters because 34 of the 124 are out of season
and have no fixture inside the sync horizon.

Thresholds: at least 80% of the field national to call it national-team football, at most
20% for club, and in between a `PROVIDER_INCONSISTENCY` is recorded and nothing changes.
The 80% is not 100% because a qualifying group can hold an unflagged provider record, and
one of those should not leave the World Cup classified as clubs.

After `/teams` for the 124 current seasons: **13 national-team, 109 club, 2 friendlies at
weight 0, 0 undecided, 0 contradictory**.

### 5. "Friendlies Clubs" carried the weight of a Champions League tie

One `/teams` call for league 667 returned **3,973 teams** — a catch-all bucket, not a
competition. On the current season alone Friendlies has 116 fixtures and Friendlies Clubs
97, among the largest on the account, and a friendly result says nothing about strength.

The provider gives no flag for this, only the name, and a rule that reads names is the
drift the rest of the selection avoids. So the three ids observed on this account are
pinned with the date and the query that re-checks them. Their `elo_weight` is 0 and their
history is dropped; they stay **tracked**, because their odds are real markets and a
pre-match window that closes unobserved cannot be recovered.

## Two smaller faults, both about trust in the record

`--write-config` did a full YAML round-trip: every value survived and every comment did
not — 913 lines in, 143 out, including the measured reason the injuries cut-off is a
partial season (6 stored payloads, 3,100 absences against 13,774 for the next year). The
tiers block is now spliced as text and the rest of the file stays byte-identical.

The quality sweep only ever recorded. Six ties whose results had just been recovered still
sat there as `RESULT_UNRESOLVED` and nothing could ever close them. A sweep now closes what
its checks no longer find, under two guards: a check whose listing was truncated at 500
rows closes nothing, and a check may only close its own `(code, entity_type)` pairs —
because `UNKNOWN_PROVIDER_ENTITY` is opened both by the bookmaker check and, on a different
entity, by detail ingestion, and closing by code alone would have silently resolved 89 real
statistics issues.

## What the provider cannot give, recorded as such

Six fixtures of 201,384 cannot be settled at ninety minutes, and each is now a registry
entry carrying the provider's own numbers rather than a silent gap:

* **Five AET fixtures** whose score blocks contradict each other — 1477537, for instance,
  reports `fulltime 4-0`, `extratime 0-2` and a final of `2-0`. `goals` includes extra
  time, so fulltime cannot exceed it and extratime cannot either. Nothing indicates which
  field is wrong, so no result is written.
* **One PEN fixture** (212507, Taça de Portugal 2018) with the running-total shape and no
  stated fulltime. Its 1X2 is safe — the match was level or it would not have gone to
  extra time — but Over/Under and BTTS cannot be settled.

A goalless final is deliberately **not** flagged: `0 - 0` is 0 whichever way `extratime` is
meant, so the subtraction is exact there. That is 31 of the 32 rows still without a stated
fulltime.

## What was deliberately not fetched

* `/players?league&season` — **OPTIONAL**, ~36 pages per league-season, so about **35,676
  requests** across 991 seasons. Nearly twice the entire core migration, for season totals
  that per-fixture player statistics already give at finer grain, and player identity
  arrives with line-ups. Not fetched; the reason is the cost-to-value ratio, not coverage.
* `/predictions` — **NOT_NEEDED**. The provider's own forecasts are not a baseline to
  prefer over the market, and the mandate excludes them.
* `/players/topscorers` and friends — **NOT_NEEDED**, derivable from per-fixture player
  statistics.
* Nine one-match competitions (Community Shield, Trophée des Champions, six domestic Super
  Cups, the UEFA and CAF Super Cups) were **kept**. Their cost is self-limiting — three
  seasons of one fixture is three fixtures — and the measure that would separate them from
  the short tournaments that *are* valuable is matches per season, which the `/leagues`
  payload does not carry. The World Cup averages 32 days and 64 matches; the UEFA Super Cup
  averages 11 days and one match. Season span cannot tell them apart, and the real count
  arrives free with the migration's own `/fixtures` call.

## Operational notes

The worker died with the WSL session at about 19:40 and was down for nearly four hours —
no odds capture, no results sync. It was restarted with `FBI_BACKFILL_MAX_PER_RUN=0`
exported for that process only, deliberately **not** written to `devenv.sh`, so a later
plain `scripts/dev-up` restores the 1,500-per-hour default by itself. The reason: two
backfill runners claim pending units without a lock, so the worker's hourly run and a
manual `--until-done` run would hand the same unit to both and pay for it twice. With the
worker's share at zero it keeps doing odds, results, fixtures and picks — the live
priorities — while history is driven at full speed.

`FBI_PG_CONTAINER=fbi-postgres` was added to `devenv.sh`: without it `scripts.backup`
fails with "pg_dump is not installed here", and a backup that fails on an unset variable
is a backup that does not exist.

An interrupted `git stash` left three working-tree files truncated to zero bytes and five
loose objects empty, with two refs carrying invalid content. Every object reachable from
HEAD verified intact and the branch had already been pushed complete, so the repair removed
only zero-byte files — which by definition hold nothing — and `git fsck --strict` is now
clean.
