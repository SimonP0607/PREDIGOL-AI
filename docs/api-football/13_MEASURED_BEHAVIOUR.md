# 13 — Measured behaviour

**Additive.** Documents 00–12 describe API-Football v3.9.3 as the provider
documents it. This file records what we have **observed** on our own account, with
the date and the request count, where observation and documentation differ or where
the documentation is silent.

A measurement here is true of this account on that date. It is not a permanent
capability, and it is not re-stated without re-measuring.

## Horizons — measured 2026-09-29, Ultra, 18 requests

| Claim | Documented | Measured | Note |
|---|---|---|---|
| `/fixtures?date=` horizon | not stated per plan | **−365 … +90 days**, every offset returned a list | on the Free plan this was **3 days**, which is why 8 fixtures stayed permanently `NS` |
| Pre-match odds appear | ~14 days before kick-off | **prices at T-18.2 days**; none at T-24.5 d | the documented figure is a floor — now `fbi.odds.horizons.MEASURED_FIRST_PRICE_DAYS = 19`, which the fixtures horizon and the worker both derive from |
| `/odds` refresh | every 3 hours | not re-measured | the config validator refuses a window below 180 min on this basis |
| `/odds` retention | 7 days | not re-measured | |
| `/odds/live` | published near kick-off, no history | **answers**; 1 fixture in play with prices | first confirmed 2026-09-29 |
| `/fixtures?ids=` | up to 20 ids, detail inline | confirmed: all four blocks, 20 per request | |

## Payload sizes — measured on our raw store (gzip)

| Endpoint | Documented estimate | **Measured** | Sample |
|---|---|---|---|
| `/fixtures?ids=` | ~40 KB JSON ≈ 7 KB gzipped per fixture | **3.21 KB per fixture** | 818 payloads, 52,742,076 bytes, 16,053 fixtures |
| `/standings` | 6 KB | **1.8 KB** | 54 payloads |
| `/injuries` | 25 KB | **43 KB** | 42 payloads |
| `/teams` | 6 KB | **2.5 KB** | 54 payloads |
| `/fixtures?league&season` | 17 KB | 17 KB (unchanged) | |

The detail estimate was **more than double** the real figure. A storage forecast
built on it would have been wrong by the same factor.

## Bet id namespaces — measured from `/odds/bets` and `/odds/live/bets`

The two catalogues are **not** the same id space, which the documentation does not
say plainly:

| id | Pre-match (`/odds/bets`, 338 entries) | In-play (`/odds/live/bets`, 266 entries) |
|---|---|---|
| 1 | Match Winner | Over/Under Extra Time |
| 4 | Asian Handicap | Extra Time Total Corners (3 Ways) (1st Half) |
| 5 | Goals Over/Under | Extra Time Double Result |
| 8 | Both Teams Score | Method of Victory |
| 12 | Double Chance | 1x2 Extra Time (1st Half) |

Full-match equivalents in the in-play space: **59** Fulltime Result, **36**
Over/Under Line, **69** Both Teams to Score, **72** Double Chance, **33** Asian
Handicap.

## Asian Handicap value encoding — measured on 22 real `/odds` payloads

Bet 4 sends the **same signed number on both rows of a pair**:

```
Bet365:      {"value": "Home -0.25", "odd": "1.92"}   {"value": "Away -0.25", "odd": "1.88"}
BetVictor:   {"value": "Home +0",    "odd": "1.59"}   {"value": "Away +0",    "odd": "2.17"}
Marathonbet: {"value": "Home -1.25", "odd": "3.50"}   {"value": "Away -1.25", "odd": "1.22"}
```

The number is the handicap **on the home team**; the word says which side you back.

Evidence, from BetVictor's five pairs: pairing `Home X` with `Away X` gives books of
1.090, 1.091, 1.090, 1.090, 1.090 — one consistent margin across every line. Pairing
`Home X` with `Away −X` gives 0.933, 1.090, 1.247 — no consistent margin and one
book below 1. On Marathonbet's wider lines the wrong reading produces **0.468**, a
bookmaker handing out money.

Integer handicaps are written `-1`, `-2`, and level ball is `+0` — not `0.0`.

## Injuries availability — measured on 42 stored payloads

| Season key | Meaning | Absences returned |
|---|---|---|
| 2020 | 2020/21 | **3,100** |
| 2021 | 2021/22 | 13,774 |
| 2022 | 2022/23 | 14,234 |
| 2023 | 2023/24 | 15,101 |
| 2024 | 2024/25 | 15,413 |
| 2025 | 2025/26 | 17,568 |
| 2026 | 2026/27 (in progress) | 2,940 |

The provider's "injuries from April 2021" cut-off falls **inside** season 2020,
because 2020/21 runs to May 2021. Season 2020 is therefore a real but partial
dataset — roughly the last two months — and the earliest season with any data at
all. Treating 2021 as the floor would discard 3,100 records.

## Bookmakers

33 in `/odds/bookmakers`. Ids used here: Pinnacle 4, Betfair 3, Marathonbet 2,
SBO 5, William Hill 7, Bet365 8, 1xBet 11, Betano 32, BetVictor 36.

## Raw-store integrity

All **818** stored `/fixtures?ids=` payloads re-hash to their recorded sha256
(verified 2026-09-29 during the replay). One consequence worth stating: the store
deduplicates identical bodies, so **a payload fetched twice keeps its FIRST fetch
time in the index** while the caller holds the second. Writers must take the index's
time; 36,599 rows predate that rule and are recorded, not rewritten.

## 2026-09-29, later: what the measurement was worth

The T-18.2-day figure sat in this document while the worker synced fixtures **four days**
ahead — the Free-plan value, kept after the upgrade by oversight. A fixture ten days out
was therefore not a row in `core.fixtures` at all, so the odds capture planner had nothing
to plan against, and the opening of its price series — the part no later request can
recover — was never captured.

A measurement that lives only in prose does not change behaviour. It is now
`fbi.odds.horizons.MEASURED_FIRST_PRICE_DAYS`, with `DEFAULT_HORIZON_DAYS` derived from it
(plus one sync interval of margin, since a fixture can enter the provider's horizon just
after a run), and both the sync and the worker read that one constant. `tests/unit/
test_horizons.py` asserts the horizon outreaches the measurement and that neither caller
keeps its own copy of the number — the defect was two numbers, not a wrong one.

Effect, measured the same day: fixtures in the capture horizon went from nothing the
planner could see to **322**, and odds snapshots from 663 on 2 fixtures to **8,727 on 26**.

Under `--strategy league` the wider horizon costs nothing: it only changes the `from`/`to`
parameters of the one request per competition-season.

## 2026-09-29: `score.extratime` does not always mean the same thing

Measured over the 1,645 `AET`/`PEN` fixtures in the raw store that carry a non-null
`extratime` block:

| relation | fixtures | what `extratime` means there |
|---|---|---|
| `goals == fulltime + extratime` | 1,557 | goals scored **during** extra time |
| `goals == extratime` | 82 | the **running total** after extra time |
| neither | 4 | — |

So `extratime` is the increment about 95% of the time and the running total about 5% of
the time, with no flag distinguishing the two. Any code that derives the 90-minute score
as `goals - extratime` is therefore wrong on roughly one in twenty extra-time fixtures,
and wrong in the worst way: the subtraction yields `0-0`, so a tie that stood 2-1 after
ninety minutes reads as a goalless draw.

**Do not derive the 90-minute score. `score.fulltime` states it.** That is now
`core.fixture_results.ft_goals_*`, and `reg_goals_*`, `outcome_1x2`, `total_goals` and
`btts` all read `COALESCE(ft_goals, goals - COALESCE(et_goals, 0))`.

Two related observations from the same sweep:

* A `PEN` fixture with `extratime` null is **not** missing data. The tie went from ninety
  minutes straight to penalties, which is how several competitions are played, and
  `fulltime` gives the score. Treating a null extratime as unusable left 6 Champions
  League ties with no result row at all.
* `fulltime + extratime != goals` is the provider contradicting itself. It is recorded as
  a disagreement rather than resolved silently, because it is the provider's fact and not
  our arithmetic.

Cost of finding this: zero requests. Every payload needed was already in the raw store —
which is the argument for keeping it.

## 2026-10-01: `/odds/live` serves matches IN PLAY, not the minutes before kick-off

This file previously recorded, and `config/odds.py` asserted, that `/odds/live` publishes
a fixture between T-15 and T-5 minutes. That was never measured. It is wrong.

One unfiltered `/odds/live` call — the authoritative probe, since it returns every fixture
the provider currently prices live:

| fixtures returned | elapsed (minutes) | status | markets |
|---|---|---|---|
| 11 | 6, 45, 45, 48, 57, 59, 83, 86, 86, 91, 93 | "Second Half" etc. | "Last Corner", "How many goals will Away Team score?" |

**Not one fixture before kick-off.** A second unfiltered sample agreed. And two fixtures
probed by id at T-14 and again at T-9 — Primera A (Colombia) and Friendlies Clubs, both
with `has_odds` true for the season — returned `results: 0, errors: []` on every call.

### What follows

* **The closing price is UNSUPPORTED.** The last price before kick-off is not obtainable
  from this provider. The latest pre-match price available is the **180-minute** window,
  because `/odds` refreshes every three hours and a window below that returns the same
  row. Anything written about capturing "the market's final word" has to be read against
  that limit.
* **In-play odds ARE available**, and they are a different product: live markets, after
  the whistle, with no history kept. Capturing them is a decision about what the platform
  is for, not a cadence setting.
* `market.near_close_snapshots` being empty was never evidence of a bug in the capture.
  It was the endpoint having nothing to give at the moment it was asked. The code half-knew
  this: `normalize.py` already carried the note that no real `/odds/live` price payload had
  ever been observed, with the live bet ids taken from the `/odds/live/bets` catalogue
  instead.
* `odds_capture_near_close` now defaults to **false**, so no request is spent on a call
  measured to return nothing. The capture path is kept intact for whenever the window is
  re-grounded on in-play.

### What this cost before it was measured

Nothing, until the capture tick was tightened to five minutes so that the six-minute
near-close window would reliably be hit. That worked - the tasks fired at T-14 and T-9
exactly as intended - and each one spent a request to receive `results: 0`. Two fixtures,
four requests, no prices. Left on, it would have been one or two wasted requests for every
fixture that reaches kick-off, indefinitely.

The cadence fix was still right: a tick that cannot hit its window is broken whatever the
window holds. It simply revealed that the window was pointed at the wrong place.

---

## 14. /odds/live, measured end to end (2026-10-01)

Everything below was measured against real payloads, not inferred from the
documentation. Three findings changed the design; two of them would have
corrupted the series silently.

### 14.1 It serves matches already in play. There is no pre-kick-off price.

One unfiltered call returned 11 fixtures, every one between the 6th and 93rd
minute, with markets like "Last Corner". Two fixtures probed individually at
T-14 and T-9 minutes returned `results: 0` with `errors: []` - a well-formed
empty answer, not a refusal.

**Therefore the closing line is UNSUPPORTED by this provider.** The latest price
obtainable before kick-off is the 180-minute pre-match window. The last
pre-match snapshot is NOT called a closing line anywhere, because it cannot be
shown to be one; `near_close` capture stays off
(`odds_capture_near_close=False`) and `market.near_close_snapshots` stays empty.

### 14.2 There is no bookmaker dimension.

Not one fixture carried a `bookmakers` key. Pre-match prices are quoted BY a
named book; a live price here is the provider's single aggregated number. These
are different kinds of observation, which is why
`market.live_odds_snapshots` has no bookmaker column and is a separate table
rather than more rows in `market.odds_snapshots`.

Payload shape, per fixture:

| key | contents |
|---|---|
| `fixture` | `id`, `status.long`, `status.elapsed`, `status.seconds` ("77:00") |
| `league` | `id`, `season` |
| `teams` | `home`/`away` with `id` and live `goals` |
| `status` | `stopped`, `blocked`, `finished` |
| `update` | the provider's own last-change time |
| `odds` | flat list of markets, each with `values` |

Each value carries `value`, `odd`, `handicap`, `main`, `suspended`.

### 14.3 The handicap is signed per selection. Pre-match it is not.

Pre-match repeats the home team's handicap on both rows of an Asian Handicap
pair, so the pre-match parser negates the away row. Live sends the handicap that
applies to the selection named:

```
{"value": "Home", "handicap": "-0.75", "odd": "1.90"}
{"value": "Away", "handicap":  "0.75", "odd": "1.98"}
```

Settled by devigging 40 real pairs both ways:

| reading | pairs formed | overround |
|---|---|---|
| away handicap already negated (as sent) | 40 | 1.0528 – 1.0827 |
| away handicap repeats the home number | 7 | 0.8413 – 1.2937 |

Only the first produces a possible book on every pair; the second barely forms
pairs and yields overrounds below 1.0, which would be free money. **Live rows
are stored as sent.** Reusing `normalize._selection()` here would have flipped
the sign on every away line in the series.

### 14.4 The bet ids are a different namespace.

| concept | pre-match | live |
|---|---|---|
| 1X2 | 1 Match Winner | 59 Fulltime Result |
| Asian Handicap | 4 Asian Handicap | 33 Asian Handicap |
| Over/Under | 5 Goals Over/Under | 36 Over/Under Line |
| Both teams to score | 8 Both Teams Score | 69 Both Teams to Score |
| Double Chance | 12 Double Chance | 72 Double Chance |

Pre-match bet 4 is Asian Handicap; **in-play bet 4 is "Extra Time Total Corners
(3 Ways) (1st Half)"**. The catalogues are separate rows in
`market.provider_markets` (scope `prematch` 338 entries, scope `inplay` 266), and
`live_market_of()` consults the in-play map only.

The vocabulary differs too: live Double Chance says "Home or Draw", pre-match
says "Home/Draw".

### 14.5 72 of 266 in-play markets were seen carrying prices.

26–56 markets per fixture, 1,933 values across 8 fixtures. 5 map to markets we
model; the other 67 are in-play only (Match Corners, Race to the 9th Corner,
Last Team to Score, Anytime Goal Scorer) and are stored with `market_key` NULL
and the provider's own selection text. **/odds/live keeps no history**, so a
value not stored at the instant it was quoted does not exist anywhere - dropping
an unmapped market would be an unrecoverable loss, which is why the live table's
`market_key` is nullable and the pre-match one's is not.

Bet 36 ("Over/Under Line") is the OU equivalent and carries quarter lines plus a
`main` flag; bet 25 ("Match Goals") is a separate, coarser market.

### 14.6 57 of 1,933 values were not prices.

56 were `"odd": "0"` **and** suspended - the provider declining to quote - plus
one Double Chance leg at exactly 1.00, not suspended. Both violate
`odds_decimal > 1.0`. They are refused into the parse log, counted in the
fixture state's `values_suspended`, and never coerced into a number we invented.

210 values were suspended *with* a real price. Those ARE stored, with
`is_suspended = true`: that is how the series shows a market freezing and what
it reopened at.

`main` was `null` on 1,575 values, `false` on 275 and `true` on 83 - hence a
nullable boolean.

### 14.7 The provider refreshes once every ~31 seconds.

12 unfiltered calls, 10.4 s apart, 7 live fixtures:

| gap | fixtures whose `update` moved | prices that moved |
|---|---|---|
| 10.6s | 7/7 | 387/1682 |
| 10.4s | 0/7 | 0/1682 |
| 10.4s | 0/7 | 0/1682 |
| 10.4s | 7/7 | 518/1673 |
| 10.4s | 0/7 | 0/1678 |
| 10.4s | 0/7 | 0/1678 |
| 10.4s | 7/7 | 303/1353 |
| 10.4s | 0/7 | 0/1362 |
| 10.4s | 0/7 | 0/1362 |
| 10.4s | 7/7 | 334/1350 |
| 10.4s | 0/7 | 0/1356 |

Exactly one real refresh every three ticks, and `update` moves for ALL fixtures
at once or for none: the provider sweeps its whole live book on a single cycle.
**5 distinct payloads came back from 12 calls, so 58% of a 10-second poll is
spent on bytes already in hand** - our payload dedup recognised them
(`cached=True`), but the request was spent.

So the capture floor is 30 s, and it is a floor on *information*: asking faster
cannot return a price we do not already have. Not polling every 5 seconds turns
out to be a lower bound the provider enforces anyway - at 5 s, five of every six
calls would be waste.

Movement worth capturing: 9.2% of prices moved per 10 s tick (~27% per refresh
cycle); suspensions churn heavily (96 values thawed in one cycle); markets
appear and vanish between cycles (one cycle dropped 325 values as a match wound
down); and 20.9% of prices did not move at all across the two minutes.

Reproduce from the stored payloads, no requests:

```
python scripts/measure_live_cadence.py
```

### 14.8 What a tick costs

One unfiltered call covers every live fixture, so **cost is per tick, not per
match**: 90 live matches cost the same as 2. At the 30 s floor that is 2,880
calls per 24 h of continuous football - under 5% of the 60,000/day guard.

What actually decides the daily spend is how many hours have any football at
all, so the cadence returns SKIP when nothing can be on the pitch and says when
to look again. That check reads `core.fixtures` and costs no request.

### 14.9 First production capture (2026-10-01 01:38)

6 fixtures priced, 1,188 quotes read, 772 written, 3 fixtures in competitions we
do not track (416 quotes, counted not dropped silently), 245 suspended values,
39 refused, 704 rows kept with `market_key` NULL, 56 markets observed, 1 quality
issue - the Double Chance leg at 1.00. One API call, 450 ms.

`market.odds_snapshots` rows with `source = 'live'`: **0**.
`market.near_close_snapshots`: **0**.

---

## 15. The pre-match markets, measured (2026-10-01)

### 15.1 Asian Handicap: the stored lines collide, and the overround tells pairs apart

The signing convention is real — the stored line is the handicap that applies to
the stored selection — but it is not sufficient to pair a bet. The provider
offers several handicap bets per bookmaker and their stored lines collide. One
fixture, one book, one instant:

```
Home  +2.5  @ 1.020
Away  -2.5  @ 11.000     <- the real partner, book 1.071
Away  +2.5  @ 1.020      <- a different bet entirely
```

Pairing on the sign alone took the wrong partner. 119 of 948 pairs were affected
and 58 of them devigged above 1.50 — a 50%+ margin no bookmaker carries — while
others came out below 1.0, which is free money.

Two near-certainties are never two sides of one bet, so the pairing is decided
by the overround. Measured over the same payloads, the markets whose pairing is
unambiguous:

| market | avg overround | range |
|---|---|---|
| 1X2 | 1.0809 | 1.0591 – 1.1219 |
| BTTS | 1.0809 | 1.0713 – 1.1284 |
| OU | 1.0831 | 1.0246 – 1.1344 |
| DC | 1.0672 | 1.0274 – 1.1016 |

Asian Handicap, paired on the sign: **1.1372, up to 1.9513**.
Asian Handicap, paired on the book: **1.0805, 1.0105 – 1.1217**.

The handicap book now carries the same margin as every other market from the
same bookmakers, and 1,271 pairs sum to exactly 1.000000. A quote with no
believable partner takes no part in the consensus; its price is still stored.

### 15.2 Most of the handicap and total series can push

| market | half lines (no push) | quarter (half the stake) | whole (full push) |
|---|---|---|---|
| AH | 2,405 rows | 4,309 | 2,127 |
| OU | 5,013 rows | 3,410 | 1,817 |

66% of the Asian Handicap series and 51% of the Over/Under series sit on lines
that can return the stake. Pricing only the clean half lines would have used 27%
of the handicap series.

A returned stake is not a loss the price has to cover, so the fair price is
`(1 - push) / p_win` — **shorter** than `1/p_win`. Treating the two as the same
overstates the edge on every whole and quarter line quoted.

A quarter line needs no special representation. Its expected value is the mean
of its two half-stake legs' expected values, so averaging their win and push
probabilities reproduces it exactly:

```
EV = ½[w_a(d-1) - (1-w_a-u_a)] + ½[w_b(d-1) - (1-w_b-u_b)]
   = w̄(d-1) - (1 - w̄ - ū)
```

Confirmed in the stored predictions: a quarter line's push comes out as exactly
half the adjacent whole line's.

### 15.3 A de-vigged two-way probability is conditional

`market.market_consensus.p_fair` comes from de-vigging selections to sum to 1, so
on a pushable line it is P(win | the bet is settled).
`models.predictions.p_calibrated` is P(win) outright. Compared directly, a model
agreeing *exactly* with the market reads as pessimistic by the push probability —
and as disagreement, not as a bug.

So the edge is computed on the conditional pair and the expected value on the
unconditional one, with `p_win = p_conditional × (1 - push)` derived rather than
passed alongside. Passed alongside, the point estimate and the lower bound
converted differently and the lower-bound expected value came out *higher* than
the point estimate.

### 15.4 Double Chance sums to two

Each of 1X, X2 and 12 covers two of three outcomes, so a fair book sums to 2 and
`devig` cannot be pointed at it. The three prices map to the 1X2 book they imply
— `P(home) = 1X + 12 - 1`, and the same linear map on the raw implied
probabilities carries the same proportional margin — which the usual Shin
estimator removes. 72 instants, all summing to 2.000000 ± 1e-6.

A book implying a non-positive outcome is dropped, not clipped: X2 at 1.02
against 1X at 3.00 and 12 at 4.00 implies a negative home probability, and
clipping would turn a broken quote into a confident number.

### 15.5 What this unlocked

| market | predictions before | after | lines |
|---|---|---|---|
| 1X2 | yes | yes | 1 |
| BTTS | yes | yes | 1 |
| OU | 2.5 only | every quoted line | 25 |
| AH | none | every quoted line | 43 |
| DC | none | yes | 1 |

8,841 Asian Handicap and 1,444 Double Chance prices had been captured, stored,
and compared against nothing. Nothing new was fitted: both are exact projections
of the score matrix the goal model already computes. The lines priced are the
lines the market actually quotes, read from the stored snapshots — a handicap
nobody quotes has nothing to compare against.

Verified two ways: every probability against what `fbi.picks.settlement` would
actually pay out, summed over the whole score distribution (two independent
implementations of one convention agreeing), and the model's fair price shown to
break even when settled.
