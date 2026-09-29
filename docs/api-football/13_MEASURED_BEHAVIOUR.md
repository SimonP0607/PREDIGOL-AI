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
