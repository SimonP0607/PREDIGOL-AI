# Odds provider gap analysis 2026 (GATE B)

*4 Oct 2026. Measured on our own database and account; researched 3-4 Oct 2026 (sources at the
end). "Requires payment - not contracted" marks anything that costs money: the owner's rule is
that nothing is bought without the owner.*

## 1. What was found

1. **Our capture, not the provider, was the main gap.** Of 675 played matches of tracked
   competitions between 25 Sep and 4 Oct, **182 (27%) were priced before kick-off**. Every match
   not asked for in time now carries a measured cause (§3): the machine was off for about
   **170 hours** of the 9.1-day window (no worker run at all on 26, 27, 28 Sep and 2 Oct), and
   **305** matches only reached the database after their last capture window - 214 inserted
   on 29-30 Sep when the worker came back from three days off, 90 on 3-4 Oct (62 of them by
   the whole-season fixture sync the data truth audit introduced, GATE A). Both causes are
   the machine and the old date-window sync, not the provider.
2. **The provider keeps the last pre-match prices for 7 days, readable after the match.**
   Measured today: a match 5 days old answered with 9 bookmakers stamped 30 minutes before
   kick-off; one 8 days old answered with nothing. The new hourly `final_prematch` job reads
   them once per played match: its first two runs asked 453 matches - **289 priced (89,961
   prices), stamped a median 76-118 minutes before kick-off (as close as 7)**, 135 empty, 29
   refused because the stamp was after kick-off. This is the near-closing line the platform
   did not have.
3. **9 of the 33 bookmakers API-Football lists price our matches**: Marathonbet, 1xBet,
   Betfair, Bet365, **Betano**, Pinnacle, BetVictor, William Hill, SBO. **bwin and 23 others
   never priced a single match** in our stored payloads. One catalogue entry (id 37) has no
   name.
4. **Of Colombia's 14 licensed operators (Coljuegos), only the Betano brand is priced by our
   provider** - not confirmed to be Betano.co's own prices. bwin and Betsson are listed by the
   provider and never priced; Wplay, Betplay, Codere, Rushbet, Yajuego and the other seven are
   not offered at all. **No free, legitimate source of Colombian operator prices exists**;
   the only researched route is paid (Odds-API.io: Betplay, Codere CO, RushBet CO).
5. **The "Pinnacle closing via football-data.co.uk" benchmark is broken for current
   seasons**: Pinnacle closed its public API on 23 Jul 2025, football-data.co.uk calls its
   Pinnacle odds since then "systematically out of date", and its 2026/27 files carry no
   Pinnacle columns. API-Football still prices Pinnacle for 70% of our priced matches; treat
   post-July-2025 Pinnacle prices with the same caution.

## 2. How it is measured

`python -m scripts.odds_coverage [--days 14]` (database only, no request) writes
`data/odds_coverage/<stamp>/REPORT.md` and `report.json`; the same report is in the Admin
Console (Data truth -> Odds coverage) and at `GET /api/v1/admin/data/odds-coverage`. Code:
`src/fbi/market/coverage.py`.

* **Population:** played matches of tracked competitions, kicked off in the last `days`,
  bounded below by the first stored pre-match price (25 Sep 2026 06:32 UTC). Every capture
  window has passed, so "priced or not" is final.
* **Provider question:** a match is *priced* when a price was captured before kick-off or read
  after it (`market.final_prematch_odds`); a competition's state (COVERED / PARTIAL / THIN /
  UNPRICED_BY_PROVIDER / NOT_COVERED / NOT_ASKED) is judged on the matches asked for.
* **Capture question:** only a price captured before kick-off can feed a pick. Each match not
  asked for before kick-off gets one cause: `worker_down` (no job started on both sides of any
  of its windows), `known_too_late` (the fixture reached the database after its last window),
  `kickoff_moved` (the provider changed its kick-off near its windows; kept in
  `core.fixture_kickoff_changes` from 4 Oct 2026) or `missed_while_up` - the only one that is a
  planner defect and the only one listed as critical.
* **Upcoming matches** (next 72 h) are judged by the capture plan (`price_state`).

## 3. Measured coverage (4 Oct 2026, 09:00 UTC; 25 Sep 06:32 - 4 Oct 09:00)

| | Matches |
|---|---:|
| Played, tracked competitions | 675 |
| Asked for at all (before kick-off or after it) | 455 |
| Priced by the provider | 308 (68% of asked) |
| Captured before kick-off | 182 (27% of played) |
| Read only after the match (final pre-match) | 126 |
| Not asked before kick-off: fixture known too late | 305 |
| Not asked before kick-off: machine off | 101 |
| Not asked before kick-off: kick-off moved by the provider | 1 (a club friendly published at 12:00 and played at 08:30; the change was recovered from the stored payloads) |
| Not asked before kick-off: planner, worker running | **0** |

The two `final_prematch` runs that cleared the backlog asked 453 matches: 289 priced (89,961
prices, median stamp 76 and 118 minutes before kick-off), 135 empty, 29 refused as stamped
after kick-off. Matches older than six days (Liga MX 9, 3. Liga 1, K League 1 1, Taça de
Portugal 1) were beyond the provider's history: those prices are lost.

### Bookmakers

| Bookmaker | API id | Matches priced | Share of priced | Markets |
|---|---:|---:|---:|---|
| Marathonbet | 2 | 180 | 99% | 1X2, BTTS, OU, AH, DC |
| 1xBet | 11 | 179 | 98% | 1X2, OU, AH, DC, BTTS |
| Betfair | 3 | 175 | 96% | 1X2, DC, OU, BTTS, AH |
| Bet365 | 8 | 175 | 96% | 1X2, OU, AH, DC, BTTS |
| Betano | 32 | 169 | 93% | 1X2, OU, DC, AH, BTTS |
| BetVictor | 36 | 132 | 73% | 1X2, OU, BTTS, AH, DC |
| Pinnacle | 4 | 128 | 70% | 1X2, OU, AH |
| William Hill | 7 | 116 | 64% | 1X2, BTTS, DC |
| SBO | 5 | 65 | 36% | 1X2, OU, AH, DC |
| 10Bet, **Bwin**, Dafabet, Ladbrokes, BetFred, 188Bet, Interwetten, Unibet, 5Dimes, Intertops, Bovada, Betcris, 888Sport, Tipico, Sportingbet, Betway, Expekt, **Betsson**, NordicBet, ComeOn, Netbet, Fonbet, Superbet, #37 (no name) | | 0 | - | listed by `/odds/bookmakers`, never priced |

*(Captured prices only; the final pre-match prices add the same nine books.)*

### Markets (captured)

Every priced match had 1X2 (median 8 books), Over/Under (6), BTTS (5); Asian handicap 99%,
double chance 98%.

### Competitions

At 08:39: 23 COVERED, 3 PARTIAL, 3 NOT_COVERED by the provider's own flag (Copa del Rey,
Feminine Division 1, CAF Champions League), 4 with no match asked for at all (Liga MX 9,
3. Liga 1, K League 1 1, Taça de Portugal 1 - all while the machine was off or before the
fixture was known; the final pre-match read covers those still inside 7 days). Colombia's
Primera A: priced by 9 books whenever asked.

## 4. The Colombian market

Coljuegos' authorised online operators (page modified 1 Oct 2026): Wplay, Betplay, Betsson,
Zamba, Codere, Luckia, Sportium, Rushbet, Rivalo, Yajuego, bwin (sports.bwin.co), Stake,
Betano, MrYoker. The page text still says "16 páginas" and a July 2026 report counted 15;
re-check before relying on the count. Kept in `src/fbi/market/local_operators.py`.

| Brand | Our provider | Matches priced for us |
|---|---|---:|
| Betano | Betano (id 32) - brand only; the Colombian edition is not confirmed | 169 |
| bwin | Bwin (id 6) listed, never priced | 0 |
| Betsson | Betsson (id 26) listed, never priced | 0 |
| Wplay, Betplay, Zamba, Codere, Luckia, Sportium, Rushbet, Rivalo, Yajuego, Stake, MrYoker | not offered | 0 |

No operator publishes an odds API. Only paid aggregators list any of them: Odds-API.io
(Betplay, Codere CO, RushBet CO - the last two added 17 Sep 2026), OpticOdds (Betplay,
RushBet, Codere; jurisdiction not stated), OddsPapi (Rushbet CO and a "BetPlay" grouped under
Brazil). Not in any list checked: the Colombian editions of Wplay, Yajuego, Zamba, Luckia,
Sportium, Rivalo, MrYoker, Betsson, Betano, bwin, Stake.

**Scraping is excluded**: Rushbet's terms treat bots and scripts as grounds for suspension, and
Ley 1273 de 2009 art. 269A makes accessing a system "sin autorización o por fuera de lo
acordado" a crime (48-96 months). Not legal advice; it supports the rule we already hold.

## 5. Complementary providers

The registry with access and cost is code: `src/fbi/providers/odds_sources.py` (shown in the
Admin Console). `enabled_sources()` returns ACTIVE sources only; a paid or account-bound
source becomes active by an owner decision recorded there, never by configuration alone.

| Provider | Books / coverage | History / closing | Access and price | Decision |
|---|---|---|---|---|
| **API-Football** (Ultra) | 33 listed, 9 price our matches | final pre-match prices readable 7 days after the match | contracted, 75,000 req/day, until 29 Oct 2026 | primary |
| **football-data.co.uk** | 22 European divisions + 16 extra leagues (ARG, BRA, MEX, USA...); no Colombia | closing and pre-closing columns; Pinnacle unreliable after 23 Jul 2025 | free for private individuals; no automated bots/scrapers/AI for commercial or data-training products | historical backtests only (imported); ask the owner before automating |
| The Odds API | 100+ books; EU: Pinnacle (website delay), Betfair Exchange, Betsson, Marathon Bet, 1xBet; UK: Betano UK; no Colombian league or book | snapshots since 2020 on paid plans | free tier 500 credits/month with an account in the owner's name; paid from USD 30/month | not pursued without the owner |
| Odds-API.io | 361 active incl. **Betplay, Codere CO, RushBet CO**, Betano (BR/MX/PE), bwin (DE/ES/FR/IT) | historical closing lines (paid) | **requires payment - not contracted**: from GBP 49/month for 2 books; new free keys paused | the only researched route to Colombian prices |
| OpticOdds | 169 books + 18 exchanges incl. Betano, bwin, Betsson, Betplay, RushBet, Codere; no Pinnacle | historical endpoint | **requires payment - not contracted** (custom quote) | - |
| SportMonks | 142 books (Pinnacle standard, Betano premium); no Colombian books | old seasons as add-on | **requires payment - not contracted**: EUR 29-249/month + odds add-on from EUR 24 | - |
| BetsAPI | single-book feeds: Bet365, bwin, Betfair, SBOBET, 1xBet | not stated | **requires payment - not contracted**: USD 100-300/month | the only researched paid route to bwin |
| Betfair Exchange API | the exchange | data from 2015; free BASIC tier | delayed key free; live key GBP 499; needs a Betfair account, possibly not allowed from Colombia (unverified) | owner's question |
| Pinnacle API | - | - | closed to the public since 23 Jul 2025 | unavailable |
| Operator websites | - | - | - | excluded (terms, Ley 1273) |

Also seen: OddsJam (prices not published), OddsPapi (350+ books, self-reported free tier, not
verified), SharpAPI (US books), Unabated (from USD 3,000/month), TheStatsAPI (from USD 50/month),
Sportradar, Genius Sports, OddsMatrix (enterprise, sales-led). Provenance caveat: The Odds API
says books drop out when they change their site or remove odds from public view, which implies
collection from public websites; any vendor should give a data-rights warranty before a
contract.

## 6. What GATE B changed

* **BOOKMAKER_COVERAGE_REPORT** per competition, country, market and bookmaker, with capture
  misses by cause (`fbi.market.coverage`, script, API, Admin Console tab).
* **Final pre-match prices** for every played match inside the provider's 7-day history
  (`fbi.odds.final_prematch`, `market.final_prematch_odds`, hourly; migration 0050). Not a
  capture: no pick may read it. Its uses: closing-line value of picks, coverage, research.
* **Catch-up capture**: a fixture whose most recent window closed unasked is asked once, now,
  at its real distance from kick-off (`CapturePlanner.plan(last_asked=...)`). A worker that
  comes back before kick-off now gets a price for everything it slept through.
* **Kick-off changes kept** (`core.fixture_kickoff_changes`, migration 0051).
* **PRICE_UNAVAILABLE / MODEL_INTERESTING_NO_PRICE**: each core market of an upcoming match
  says whether it is priced and why not (`fbi.market.price_status`); where nothing is priced,
  the watch model's fair odds and the minimum odds that would carry the rule's margin
  (`fbi.picks.no_price`, rule `no-price-watch-v1`), labelled evaluation mode. Never a
  bookmaker's price and never a pick. Shown in the Match Center.
* **OddsProvider interface and source registry** (`fbi.providers.odds_sources`).

## 7. Recommendations (owner decisions marked)

1. **Keep the worker running (owner decision).** The single largest loss is the machine being
   off: 170 of 218 hours in the window. Options: disable sleep while the platform must run, or
   a small always-on private host (not a public deployment). The catch-up and the final
   pre-match read limit the damage of short outages; nothing recovers a window more than 7
   days old.
2. **Use the final pre-match prices as the closing-line benchmark** for every league,
   including Colombia's, instead of football-data.co.uk's Pinnacle columns for current seasons.
   Keep football-data.co.uk (BFEC*/AvgC*) for historical European backtests.
3. **Colombian prices: no free route exists.** Show users the model's minimum odds for their
   own bookmaker (done) rather than estimate one. If the owner wants real Betplay/Codere/
   RushBet prices: Odds-API.io Solo (GBP 49/month, 2 books) after confirming its Liga BetPlay
   coverage and that its "Betplay" is betplay.com.co - **requires payment, not contracted**.
4. **Ask API-Football support (owner action)** which of the 24 silent bookmakers should price
   which leagues, and whether bwin is expected at all.
5. **The Odds API free tier** (owner's account) would add a second view of European prices; it
   adds nothing for Colombia.

## Sources

1. API-Football documentation v3 (odds, bookmakers, odds/live, leagues coverage) - https://www.api-football.com/documentation-v3 (accessed 4 Oct 2026)
2. API-Football, "How to get started with API-Football", 13 Mar 2026 - https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide
3. The Odds API, plans - https://the-odds-api.com/ ; bookmakers by region - https://the-odds-api.com/sports-odds-data/bookmaker-apis.html ; sports - https://the-odds-api.com/sports-odds-data/sports-apis.html ; historical - https://the-odds-api.com/historical-odds-data/ ; update intervals - https://the-odds-api.com/sports-odds-data/update-intervals.html ; v4 credits - https://the-odds-api.com/liveapi/guides/v4/
4. OddsJam Odds API - https://oddsjam.com/odds-api
5. OpticOdds sportsbooks ("Refreshed September 2026") - https://developer.opticodds.com/docs/sportsbooks.md ; pricing - https://opticodds.com/pricing ; competitor estimate - https://sportsgameodds.com/compare/opticodds
6. SportMonks plans (modified 4 Aug 2026) - https://www.sportmonks.com/football-api/plans-pricing/ ; bookmakers - https://docs.sportmonks.com/football/tutorials-and-guides/tutorials/odds-and-predictions/bookmakers ; free plan - https://www.sportmonks.com/football-api/free-plan/
7. Odds-API.io pricing - https://odds-api.io/pricing ; bookmakers (queried 4 Oct 2026) - https://api.odds-api.io/v3/bookmakers ; docs - https://docs.odds-api.io/llms.txt ; "Pinnacle shut down their API", 1 Feb 2026 - https://odds-api.io/blog/pinnacle-api-shutdown-alternatives
8. BetsAPI pricing - https://betsapi.com/mm/pricing_table
9. Betfair Developer Program: costs (12 Sep 2026) - https://support.developer.betfair.com/hc/en-us/articles/115003864531 ; delayed vs live key (26 Sep 2026) - https://support.developer.betfair.com/hc/en-us/articles/360009638032 ; historical data (24 Sep 2026) - https://support.developer.betfair.com/hc/en-us/articles/360002407732 ; country restrictions (third party) - https://www.cheekypunter.com/faq/betfair-country-restrictions/
10. Pinnacle API documentation README - https://github.com/pinnacleapi/pinnacleapi-documentation
11. football-data.co.uk data (updated 2 Oct 2026) - https://www.football-data.co.uk/data.php ; extra leagues - https://www.football-data.co.uk/all_new_data.php ; notes - https://www.football-data.co.uk/notes.txt ; files checked 4 Oct 2026 - https://www.football-data.co.uk/mmz4281/2627/E0.csv , https://www.football-data.co.uk/mmz4281/2627/SP1.csv , https://www.football-data.co.uk/mmz4281/2526/E0.csv , https://www.football-data.co.uk/new/BRA.csv
12. OddsPapi - https://oddspapi.io/sportsbooks ; SharpAPI - https://sharpapi.io/pricing ; Unabated - https://unabated.com/odds-api/enterprise ; TheStatsAPI - https://www.thestatsapi.com/odds-api/closing-odds ; Sportradar - https://developer.sportradar.com/odds/v1/reference/oc-regular-overview ; Genius Sports - https://www.geniussports.com/bet/odds-feeds-api/ ; OddsMatrix - https://oddsmatrix.com/
13. Coljuegos, "Operadores de Juegos Online Autorizados" (modified 1 Oct 2026) - https://www.coljuegos.gov.co/publicaciones/301841/juegosonline/ ; InfoPlay, 6 Jul 2026 - https://www.infoplay.info/es/2026-07-06/coljuegos-recuerda-en-pleno-mundial-cuales-son-los-operadores-online-autorizados-para-apostar-en-colombia/36527/noticia/ ; FocusGN, Betano authorised, 19 Nov 2024 - https://focusgn.com/latinoamerica/nuevo-operador-autorizado-en-colombia-betano-recibio-el-aval-de-coljuegos
14. Rushbet.co terms - https://www.rushbet.co/?page=eula ; Ley 1273 de 2009 art. 269A - http://www.secretariasenado.gov.co/senado/basedoc/ley_1273_2009.html ; Codere Partners - https://www.codere-partners.com/
15. Our measurements: `data/odds_coverage/20261004T083942/REPORT.md` (coverage), the `final_prematch` ledger run of 4 Oct 2026 08:26 UTC, and the retention probe of 4 Oct 2026 (three `/odds` requests: 5, 6 and 8 days after kick-off).
