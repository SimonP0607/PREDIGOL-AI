# API-Football v3 (API-Sports): capabilities, request costs and prices

Retrieved 2026-09-25. Only official API-Sports / API-Football pages were used, plus archived copies (web.archive.org) of official pages where the date is stated.

- Documentation: v3.9.3, marked "Current" in the site menu: https://www.api-football.com/documentation-v3 (Redoc page built from https://www.api-football.com/public/doc/openapi.yaml).
- The docs mirror at https://api-sports.io/documentation/football/v3 loads https://api-sports.io/public/documentations/football-v3.yaml. That file is byte-identical to the api-football.com spec.
- https://www.api-football.com/documentation-beta is also identical to v3.9.3.
- Base URL: `https://v3.football.api-sports.io/`. Only GET requests are accepted, and the only allowed header is `x-apisports-key` ([docs#Authentication](https://www.api-football.com/documentation-v3#section/Authentication)).
- "Derived" marks my own arithmetic from official numbers. It is not an official statement.

---

## Plans, limits and prices

| Plan | Price, 1 month ([pricing](https://www.api-football.com/pricing)) | Requests/day | Requests/min | Requests/s | Seats ([api-sports.io](https://api-sports.io/sports/football)) | 3 / 6 / 12-month prepaid price ([api-sports.io](https://api-sports.io/sports/football)) |
|---|---|---|---|---|---|---|
| Free | $0 | 100 | 10 ([ratelimit post, 2026-06-12](https://www.api-football.com/news/post/how-ratelimit-works)) | not stated | not stated | n/a |
| Pro | $19 | 7,500 | 300 | 5 | 1 | $51.30 / $91.20 / $159.60 (list $57 / $114 / $228) |
| Ultra | $29 | 75,000 | 450 | **7** (2026-06-12 post) vs **7.5** ([optimize post, 2026-07-27](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage)) | 2 | $78.30 / $139.20 / $243.60 (list $87 / $174 / $348) |
| Mega | $39 | 150,000 | 900 | 15 | 3 | $105.30 / $187.20 / $327.60 (list $117 / $234 / $468) |
| Custom | not published ("contact us") | up to 1,500,000 ([pricing FAQ](https://www.api-football.com/pricing)) | 1,200 | 20 | n/a | n/a |

Notes:
- **Per-minute limits.** The per-minute and per-second limits come from the [ratelimit post (2026-06-12)](https://www.api-football.com/news/post/how-ratelimit-works) and the [optimize post (2026-07-27)](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage). The api-sports.io plan pop-ups say "Rate Limit : 300 / 450 / 900 requests/min" for Pro / Ultra / Mega ([api-sports.io/sports/football](https://api-sports.io/sports/football)). The api-football.com pricing page itself shows no per-minute figures.
- **Currency.** The pricing page shows "$". The multi-month prices come from the page's `data-one-month`, `data-three-month`, `data-six-month` and `data-yearly` attributes, which carry no currency symbol. They work out to 10 / 20 / 30 % off (derived). This matches "Up to **-30%** for any subscription according to the chosen duration" ([pricing](https://www.api-football.com/pricing)).
- **What every plan includes.** "All our plans include all competitions and endpoints. *(Free plans are limited in terms of available seasons)*" ([pricing](https://www.api-football.com/pricing)). The [homepage](https://www.api-football.com/) says the same. api-sports.io says "All our paid plans give you access to all endpoints and all competitions" ([api-sports.io](https://api-sports.io/sports/football)).
- **Billing.** Plans are prepaid for the chosen duration: "no auto-renewal or hidden charges. When it expires, your account automatically returns to the free plan" ([pricing](https://www.api-football.com/pricing)). Terms (last updated "Mai 21, 2025") add:
  - durations of 1, 3, 6 or 12 months;
  - no cancellation or refund;
  - upgrades change only the plan and requests/day, not the end date, and you pay the price difference;
  - "Plan upgrades are final and it is not possible to downgrade" ([terms](https://www.api-football.com/terms), identical at [api-sports.io/terms](https://api-sports.io/terms)).
- **Price history.** Archived copies of the official pricing page show the same four plans and prices ($0/$19/$29/$39 for 100 / 7,500 / 75,000 / 150,000 requests per day) on:
  - [2020-03-12](https://web.archive.org/web/20200312192600/https://www.api-football.com/pricing)
  - [2022-01-18](https://web.archive.org/web/20220118213223/https://www.api-football.com/pricing)
  - [2023-02-02](https://web.archive.org/web/20230202170118/https://www.api-football.com/pricing)
  - [2024-08-11](https://web.archive.org/web/20240811142804/https://www.api-football.com/pricing)
  - [2026-03-14](https://web.archive.org/web/20260314113151/https://www.api-football.com/pricing)

  The [beginner's guide (2026-03-13)](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide) quotes the same $19 / $29 / $39 prices. **I found no official article with different list prices.** Only older promotions differ:
  - [50% OFF, 2020-07-01](https://www.api-football.com/news/post/50-off): "Up to 50% off for any subscription longer than 3 months".
  - [WINTER SALE, 2021-12-21](https://www.api-football.com/news/post/winter-sale): code WINTER10 plus 10 % for crypto payments, "up to 70%" combined with the dashboard discounts.
- **Minor inconsistency.** The pricing page's meta description says "Secure Payment via Stripe or PayPal", but the page body says "Secure payment by Paypal or Credit Card" ([pricing](https://www.api-football.com/pricing)).

### RapidAPI
- **Terms.** The Terms still describe RapidAPI as a second channel ([terms](https://www.api-football.com/terms)). On RapidAPI:
  - the subscription is monthly and recurring;
  - "overage fees may be applied when a user that exceeds a plan's quota limits";
  - overage costs are not refundable;
  - the daily quota resets 24 h after the time you subscribed.
- **Live listing gone.** https://rapidapi.com/api-sports/api/api-football and its `/pricing` page return "Page Not Found – API not found" (checked 2026-09-25).
- **Archived listing, [2026-02-01](https://web.archive.org/web/20260201125242/https://rapidapi.com/api-sports/api/api-football/pricing).** The embedded plan data shows:
  - BASIC: $0, 100/day (hard limit).
  - PRO: $19/month, 7,500/day, overage $0.0025 per request, 300/min, flagged `hidden: true`.
  - MEGA: $39/month, 150,000/day, overage $0.001 per request, 900/min, also hidden.
  - An ULTRA entry, also hidden, with inconsistent values: $119, 148,888/day. I treat it as unreliable.
  - Listing text: "October 1, 2019 price decrease for overages: FREE $0.005, PRO $0.0025, ULTRA $0.0015, MEGA $0.0010 per additional request".
  - RapidAPI base URL `https://api-football-v1.p.rapidapi.com/v3` with the `x-rapidapi-host` and `x-rapidapi-key` headers.
- **Archived listing, [2026-04-23](https://web.archive.org/web/20260423002013/https://rapidapi.com/api-sports/api/api-football/pricing).** Already shows "API not found".
- **Conclusion.** Where comparable (Basic, Pro, Mega), RapidAPI base prices matched the dashboard's. The difference was the overage model and a rolling 24 h reset. I could not find a current RapidAPI price.

---

## Quota mechanics

- **Daily reset, dashboard subscriptions: 00:00:00 UTC.**
  - Terms: "The daily quota period starts at 00:00:00 UTC … your daily quota will reset at 00:00:00 UTC each day. **Unused requests are lost**." ([terms](https://www.api-football.com/terms))
  - api-sports.io: "The daily request quota reset to zero every day at 00:00 UTC, unused requests are lost." ([api-sports.io](https://api-sports.io/sports/football))
  - RapidAPI subscriptions instead reset 24 h after subscription time ([terms](https://www.api-football.com/terms)).
  - The [beginner's guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide) only says "a 24-hour period".
- **When the daily quota runs out.** "It is not possible to exceed the quota limit on our dashboard, when your quota limit is reached, your account will be suspended for the rest of the day." ([terms](https://www.api-football.com/terms)) Also: "once your quota is reached, the API automatically stops processing requests and sends an error message instead of billing extra" ([pricing FAQ](https://www.api-football.com/pricing)). The exact text of that error is not documented.
- **Response headers** ([docs#API-SPORTS-Account](https://www.api-football.com/documentation-v3#section/Authentication/API-SPORTS-Account)). The daily and per-minute headers have different names. They do not differ only by case.
  - `x-ratelimit-requests-limit`: requests allocated per day.
  - `x-ratelimit-requests-remaining`: remaining requests per day.
  - `X-RateLimit-Limit`: maximum calls per minute.
  - `X-RateLimit-Remaining`: calls remaining before the per-minute limit.
  - The same list appears in the [ratelimit post](https://www.api-football.com/news/post/how-ratelimit-works) and the [optimize post](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage).
- **`/status`.** "This call does not count against the daily quota." ([docs#API-SPORTS-Account](https://www.api-football.com/documentation-v3#section/Authentication/API-SPORTS-Account)) The sample response:
  ```json
  {"get":"status","parameters":[],"errors":[],"results":1,
   "response":{"account":{"firstname":"…","lastname":"…","email":"…"},
               "subscription":{"plan":"Free","end":"2020-04-10T23:24:27+00:00","active":true},
               "requests":{"current":12,"limit_day":100}}}
  ```
- **Logos and images are free.** "Calls to logos/images do not count towards your daily quota … However these calls are subject to a rate per second & minute, it is recommended to save this data on your side" ([docs#Logos-Images](https://www.api-football.com/documentation-v3#section/Logos-Images); [terms](https://www.api-football.com/terms)).
- **Do errors or empty results count?** Not found in official sources. The only calls documented as not counted are `/status` and logos/images. Separately, the odds/live beta in 2022 was free during testing ([in-play odds post, 2022-02-02](https://www.api-football.com/news/post/in-play-odds)). The guide warns that a `200` can carry no data for an "incorrect parameter (season=2054)", "a parameter that does not exist" or a normal lack of data ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
- **Per-minute enforcement** ([ratelimit post, 2026-06-12](https://www.api-football.com/news/post/how-ratelimit-works)):
  - A proxy converts the per-minute limit into a per-second rate (Mega: 900/min becomes 15/s).
  - A small excess is queued ("burst"); a larger excess gets **HTTP 429** with `errors.rateLimit`.
  - Limits apply "per user and per API", and the protection "also takes into account the IP address". Shared-IP serverless platforms are discouraged: Cloudflare Workers, AWS Lambda, Cloud Run, Vercel, Netlify and similar.
  - Abuse can cause temporary or permanent firewall blocks of the key and/or IP "without prior notice". Stated in the [docs](https://www.api-football.com/documentation-v3#section/Authentication/API-SPORTS-Account) and, as a breach of the Terms with no refund, in the [terms](https://www.api-football.com/terms).
  - The 429 message text differs between posts. 2026-06-12: "Too many requests. You have exceeded the limit of requests per minute of your subscription." 2026-07-27: "…You have reached your per-minute request limit. Please wait a few seconds before retrying or upgrade your plan for higher limits." ([optimize post](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage))
  - Other status codes: `499` is a timeout and `500` a server error; both are "safe to retry once after a short wait" ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
- **Account rules.** "Accounts are individual and may not be shared with other developers. It is forbidden to have multiple accounts to increase the limit of the free plan." ([terms](https://www.api-football.com/terms))
- **Update frequencies are indicative.** "given as an indication and may vary for certain competitions" ([docs#Introduction](https://www.api-football.com/documentation-v3#section/Introduction)); "not guaranteed" ([terms](https://www.api-football.com/terms)).
- **Dashboard.** It shows usage by day or month and can send quota alert emails ([optimize post](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage); [pricing](https://www.api-football.com/pricing)). The dashboard itself (e.g. https://dashboard.api-football.com/soccer/ids) requires login, so I could not read it.

---

## Historical depth

- **Free plan season window: not published.** Official wording only:
  - "Free plans are limited in terms of available seasons" ([pricing](https://www.api-football.com/pricing));
  - "The free plan covers recent seasons … Paid plans unlock deeper historical archives" and "The difference between plans is purely about volume and historical range, not features" ([guide, 2026-03-13](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide));
  - the Free plan "remains limited in terms of available data. We reserve the right to modify the Free Plan and the available data at any time without prior notice" ([terms](https://www.api-football.com/terms)).

  No official page lists the seasons. The team's observation (2022–2024 allowed, "Free plans do not have access to this season" for 2025) cannot be confirmed or dated from official pages.
- **Paid plans.** Official pages say all endpoints and competitions (see above) and "deeper historical archives". No page says whether Pro, Ultra and Mega differ in seasons, or that paid plans get "all seasons".
- **Earliest seasons in the API** (examples only):
  - `/leagues/seasons` sample: `[2008, 2010, 2011, …, 2020]` ([docs#get-seasons](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-seasons)). The guide describes it as "something like `[2008, 2010, 2011, 2012, ..., 2025]`".
  - `/leagues?id=39` sample (Premier League) lists seasons 2010 and 2011, which may be abridged. For both, `events` and `lineups` are true, `statistics_fixtures` and `statistics_players` are false, `odds` is false ([docs#get-leagues](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-leagues)).
  - `/teams/seasons?team=33` sample: 2010–2021 ([docs#get-teams-seasons](https://www.api-football.com/documentation-v3#tag/Teams/operation/get-teams-seasons)).
  - `/players/seasons` sample includes 1966, 1982, 1986 and 1990–2020 plus 2022 ([docs#get-players-seasons](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-seasons)).
- **Which competitions go back to 2008 / 2010 / 2015: not found in official sources.**
  - The coverage pages show a per-competition "Historical data" checkmark but no years. [api-sports.io/sports/football](https://api-sports.io/sports/football) lists 1,247 entries; [api-football.com/coverage](https://www.api-football.com/coverage) says "1246 Leagues & Cups", "[Last-Update 2026-09-24]", "* May vary according to the seasons or fixtures".
  - The official way to get a league's seasons is `/leagues?id={id}`: "Allows to retrieve all the seasons available for a league/cup" ([docs#get-leagues](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-leagues)). Each season carries its own `coverage`.
- **Documented data-start dates:**
  - `/injuries`: "only available from April 2021";
  - VAR events: from the 2020-2021 season;
  - `fixtures/statistics?half=true`: "Data start from 2024 season";
  - pre-match odds: 7-day history only;
  - live odds: "No history is stored".

  Sources: docs for [injuries](https://www.api-football.com/documentation-v3#tag/Injuries/operation/get-injuries), [events](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-events), [statistics](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-statistics), [odds](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-odds), [odds/live](https://www.api-football.com/documentation-v3#tag/Odds-(In-Play)/operation/get-odds-live).
- **Season keys** are 4-digit start years: "the `2018-2019` season in the API will be `2018`" ([docs#get-seasons](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-seasons)).
- **Current seasons.** "a season is considered current as long as it has not been renewed" ([standings tutorial, 2022-02-01](https://www.api-football.com/news/post/how-to-get-standings-for-all-current-seasons)).

---

## Endpoint inventory

Legend:
- `*` marks a required parameter.
- "No page param" means no `page` parameter and no pagination statement in the docs.
- Upd / Rec are the docs' "Update Frequency" and "Recommended Calls".
- Every response carries `paging {current,total}`.

Source for every row, unless another link is given: the operation anchor of https://www.api-football.com/documentation-v3 (v3.9.3).

| Endpoint | Key params | Paginated? page size | Max per request | Update frequency (Upd / Rec) | History kept | Source URL |
|---|---|---|---|---|---|---|
| `/status` | none | no | n/a | n/a (does not count against quota) | n/a | [docs](https://www.api-football.com/documentation-v3#section/Authentication/API-SPORTS-Account) |
| `/timezone` | none | no (sample: 425 results, 1 page) | all | "not updated" / "1 call when you need" | static | [docs](https://www.api-football.com/documentation-v3#tag/Timezone/operation/get-timezone) |
| `/countries` | name, code, search (=3 chars) | no page param | all | when a league from a new country is added / 1 per day | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Countries/operation/get-countries) |
| `/leagues` (includes per-season `coverage`) | id, name, country, code, season, team, type (league\|cup), current, search (≥3), last (≤2 digits, e.g. 99) | no page param. Official example: `current=true` returned 900 leagues on 1 page ([tutorial 2022-02-01](https://www.api-football.com/news/post/how-to-get-standings-for-all-current-seasons)) | all matches | several times a day / 1 per hour | every season of each league, each with its own coverage | [docs](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-leagues) |
| `/leagues/seasons` | none | no | all | when a new league is added / 1 per day | sample starts 2008 | [docs](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-seasons) |
| `/teams` | id, name, league, season, country, code (3), venue, search (≥3). At least one required | no page param. league+season = 1 call (20 teams, 1 page, [tutorial 2021-12-14](https://www.api-football.com/news/post/how-to-get-all-teams-and-players-from-a-league-id)) | n/a | several times a week / 1 per day | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Teams/operation/get-teams) |
| `/teams/statistics` | league\*, season\*, team\*, date | no | 1 team-league-season | twice a day / 1 per day if the team plays that day, else 1 per week | per season; `date` computes stats up to that date | [docs](https://www.api-football.com/documentation-v3#tag/Teams/operation/get-teams-statistics) |
| `/teams/seasons` | team\* | no | n/a | several times a week / 1 per day | list of seasons | [docs](https://www.api-football.com/documentation-v3#tag/Teams/operation/get-teams-seasons) |
| `/teams/countries` | none | no | all | several times a week / 1 per day | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Teams/operation/get-teams-countries) |
| `/venues` | id, name, city, country, search (≥3). At least one required | no page param | n/a | several times a week / 1 per day | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Venues/operation/get-venues) |
| `/standings` | season\*, league, team | no page param | all groups of a league-season | every hour / 1 per hour if a fixture is in progress, else 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Standings/operation/get-standings) |
| `/fixtures/rounds` | league\*, season\*, current, dates (bool), timezone | no | all rounds | every day / 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-rounds) |
| `/fixtures` | id, **ids** ("id-id-id"), live (all \| id-id), date, league, season, team, last/next (≤2 digits), from, to, round, status (one or more, e.g. `FT-AET-PEN`), venue, timezone | no page param. league+season returns the whole season in one response (see Batching) | **ids: maximum 20** | every 15 s / 1 per minute if in progress, else 1 per day | IDs never change. TBD/PST/CANC are re-checked daily. Result-only competitions can take "up to 48 hours" | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures) |
| `/fixtures/headtohead` | h2h\* (ID-ID), date, league, season, last, next, from, to, status, venue, timezone | no page param | n/a | every 15 s / as `/fixtures` | all meetings, across all competitions ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)) | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-headtohead) |
| `/fixtures/statistics` | fixture\*, team, type, half (bool) | no | 1 fixture | every minute / 1 per minute if in progress, else 1 per day | `half` data from 2024 season | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-statistics) |
| `/fixtures/events` | fixture\*, team, player, type | no | 1 fixture | every 15 s / 1 per minute if in progress, else 1 per day | VAR events from 2020-21 | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-events) |
| `/fixtures/lineups` | fixture\*, team, player, type | no | 1 fixture | every 15 min / 1 per 15 min if in progress, else 1 per day | "available between 20 and 40 minutes before the fixture" when covered; otherwise after the match "with a variable delay" (docs) / "within 24 to 72 hours" ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)) | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-lineups) |
| `/fixtures/players` | fixture\*, team | no | 1 fixture | every minute / 1 per minute if in progress, else 1 per day | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-players) |
| `/injuries` | league, season (required with league/team/player), fixture, team, player, date, **ids**, timezone. At least one required | no page param (docs example `injuries?league=2&season=2020` is one call) | **ids: maximum 20 fixtures** | every 4 h / 1 per day | "only available from April 2021" | [docs](https://www.api-football.com/documentation-v3#tag/Injuries/operation/get-injuries) |
| `/predictions` | fixture\* | no | 1 fixture (no batch param) | every hour / 1 per hour if in progress, else 1 per day | not stated | [docs](https://www.api-football.com/documentation-v3#tag/Predictions/operation/get-predictions) |
| `/coachs` | id, team, search (≥3) | no page param | n/a | every day / 1 per day | coach career history | [docs](https://www.api-football.com/documentation-v3#tag/Coachs/operation/get-coachs) |
| `/players/seasons` | player | no | all | every day / 1 per day | sample back to 1966 | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-seasons) |
| `/players/profiles` | player, search (≥4, last name), page | **yes, 250 per page** | 250 | several times a week / 1 per week | all players | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-profiles) |
| `/players` (season stats) | id, team, league, season (needs id, league or team), search (≥4, needs league or team), page | **yes, 20 per page** | 20 | several times a week / 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players) |
| `/players/squads` | team or player. At least one required | no page param | 1 team | several times a week / 1 per week | **current** squad only | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-squads) |
| `/players/teams` | player\* | no | 1 player | several times a week / 1 per week | whole career (teams and seasons) | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-teams) |
| `/players/topscorers` | league\*, season\* | no | 20 players | several times a week / 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-topscorers) |
| `/players/topassists` | league\*, season\* | no | 20 | several times a week / 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-topassists) |
| `/players/topyellowcards` | league\*, season\* | no | 20 | several times a week / 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-topyellowcards) |
| `/players/topredcards` | league\*, season\* | no | 20 | several times a week / 1 per day | per season | [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-topredcards) |
| `/transfers` | player, team | no page param | 1 player or team | several times a week / 1 per day | "all available transfers" | [docs](https://www.api-football.com/documentation-v3#tag/Transfers/operation/get-transfers) |
| `/trophies` | player, **players**, coach, **coachs** | no page param | **players / coachs: maximum 20 ids** | several times a week / 1 per day | "all available trophies for a player or a coach" | [docs](https://www.api-football.com/documentation-v3#tag/Trophies/operation/get-trophies) |
| `/sidelined` | player, **players**, coach, **coachs** | no page param | **maximum 20 ids** | several times a week / 1 per day | full injury/suspension record ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)) | [docs](https://www.api-football.com/documentation-v3#tag/Sidelined/operation/get-sidelined) |
| `/odds/live` | fixture, league ("season" not needed), bet | no page param | all live fixtures | every 5 s ("can change in the range of 5 to 60 seconds") | **none**: fixtures added 15–5 min before kick-off, removed 5–20 min after the end | [docs](https://www.api-football.com/documentation-v3#tag/Odds-(In-Play)/operation/get-odds-live) |
| `/odds/live/bets` | id, search (=3) | no | all | every 60 s / not given | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Odds-(In-Play)/operation/get-bets) |
| `/odds` (pre-match) | fixture, league, season, date, timezone, page, bookmaker, bet | **yes, 10 per page** | 10 | every 3 h / 1 call every 3 h | offered 1–14 days before the fixture; **7-day history** | [docs](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-odds) |
| `/odds/mapping` | page | **yes, 100 per page** | 100 | every day / 1 per day | "the list of available fixtures `id` for the endpoint odds" | [docs](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-odds-mapping) |
| `/odds/bookmakers` | id, search (=3) | no | all | several times a week / 1 per day | n/a | [docs](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-bookmakers) |
| `/odds/bets` | id, search (=3) | no | all | several times a week / 1 per day | n/a (IDs differ from `/odds/live/bets`) | [docs](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-bets) |

### Coverage object in `/leagues` (per league and season)

Source: [docs#get-leagues](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-leagues).

Fields:
- `fixtures.events`, `fixtures.lineups`, `fixtures.statistics_fixtures`, `fixtures.statistics_players`
- `standings`, `players`, `top_scorers`, `top_assists`, `top_cards`, `injuries`, `predictions`, `odds`

How the docs describe it:
- "The values returned by the coverage indicate the **data available at the moment** you call the API". A competition that has not started has everything `False`.
- "The coverage of a competition can vary from season to season and values set to `True` do not guarantee 100% data availability."
- Friendlies are exceptions whose data "may differ depending on the match".
- Cup fixtures are added once both teams are known.
- New seasons are created automatically, with a possible delay.

Which endpoint each flag governs:
- The names imply events → `/fixtures/events`, lineups → `/fixtures/lineups`, statistics_fixtures → `/fixtures/statistics`, statistics_players → `/fixtures/players`, top_cards → `/players/topyellowcards` and `/players/topredcards`, and so on. The docs do not state this mapping explicitly.
- The [guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide) confirms it for `standings`, `injuries` and `predictions` ("If `injuries` is `false`, don't call `/injuries`").
- The [optimize post](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage) notes that fields for `events`, `lineups`, `/fixtures/statistics`, `/players/statistics` and `/players/topscorers` can be `false` before a competition starts.

Other official discrepancies:
- **/players page size.** 20 per page in the docs, the [2021 tutorial](https://www.api-football.com/news/post/how-to-get-all-teams-and-players-from-a-league-id) and the guide's pagination section. The same guide's tips section says a call without paging "will give you only the first 25 players".
- **/players search minimum.** 4 characters in the spec; "minimum 3 characters" in the guide.
- **Lineups timing.** The guide's quick reference says "typically available 30–60 minutes before kickoff"; its body says 20–40 minutes.
- **/players/squads.** The guide says `team` is required. The docs accept `team` or `player`.
- **Allowed headers.** The docs allow only `x-apisports-key`. Older official tutorials send `x-rapidapi-key` (and `x-rapidapi-host`) to `v3.football.api-sports.io`: [2021-12-14](https://www.api-football.com/news/post/how-to-get-all-teams-and-players-from-a-league-id), [2022-02-01](https://www.api-football.com/news/post/how-to-get-standings-for-all-current-seasons), [2024-12-12](https://www.api-football.com/news/post/how-to-get-all-fixtures-data-from-one-league).

---

## Batching and request-cost facts for a backfill

- **`/fixtures?ids=` takes up to 20 fixtures and returns events, lineups, statistics and players for each.**
  - Changelog 3.9.2: "Add the `ids` parameter that allows to retrieve data from several fixtures including events, lineups, statistics and players in one Api call" ([docs#Changelog](https://www.api-football.com/documentation-v3#section/Changelog); release post [2022-06-08](https://www.api-football.com/news/post/api-football-new-release)).
  - The spec says "Maximum of 20 fixtures ids". The Use Cases state that events, lineups, statistics and players are returned for both `id=` and `ids=` ([docs#get-fixtures](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures)).
  - Also confirmed in: [tutorial 2024-12-12](https://www.api-football.com/news/post/how-to-get-all-fixtures-data-from-one-league) ("we get 20 results including events, lineups, statistics and players statistics for each fixture"); [WC guide 2026-04-13](https://www.api-football.com/news/post/fifa-world-cup-2026-guide-to-using-data-with-api-sports); [match reports 2026-07-01](https://www.api-football.com/news/post/fifa-world-cup-2026-group-stage-recap-and-complete-match-reports-with-api-football).
  - **Caveat:** the [optimize post (2026-07-27)](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage) says "**When available for your plan**, … you can call `/fixtures` with the `ids` parameter". No page says which plans lack it.
- **One `ids` call is one request.** The tutorial retrieved a whole league's fixture data "in just **9** API calls": 1 list call plus 8 `ids` calls for 149 fixtures. It added a 1,000 ms delay between calls "to take account of the API Ratelimit" ([tutorial 2024-12-12](https://www.api-football.com/news/post/how-to-get-all-fixtures-data-from-one-league)).
- **`/fixtures?league=&season=` returns a whole season in one request, without the detail blocks.**
  - "Pass `league=39&season=2025` and you get all 380 Premier League fixtures … in a single response" ([guide 2026-03-13](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
  - The tutorial's `league=39&season=2024&status=FT-AET-PEN-…` returned 149 fixtures in one call.
  - The detail blocks come only with `id`/`ids`: "Unlike a broad `/fixtures` query by league, season or date, a request using `ids` can return detailed blocks" ([2026-07-01](https://www.api-football.com/news/post/fifa-world-cup-2026-group-stage-recap-and-complete-match-reports-with-api-football)). `live=all` returns events ([docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures)).
- **`/injuries` by league+season:** documented as a single call, with no `page` parameter and no pagination statement ([docs](https://www.api-football.com/documentation-v3#tag/Injuries/operation/get-injuries)). The docs never say that very large results are *not* paginated. `ids` (up to 20 fixtures) was added in 3.9.3 ([release post 2024-10-09](https://www.api-football.com/news/post/api-football-new-release-available)).
- **`/players` by league+season: yes, 20 per page.**
  - Stated in the [docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players).
  - Official example: Premier League 2021 = `paging.total` 39, 771 players, so 39 requests ([tutorial 2021-12-14](https://www.api-football.com/news/post/how-to-get-all-teams-and-players-from-a-league-id)). That tutorial paused 1 s every 2 pages to avoid 429s.
  - Guide: "500+ registered players … more than 25 sequential API calls".
- **Other batch parameters:** `trophies` and `sidelined` accept `players`/`coachs` with up to 20 ids (3.9.3). `/players/profiles` returns 250 per page. `/odds` returns 10 per page and `/odds/mapping` 100 per page ([docs](https://www.api-football.com/documentation-v3#tag/Players/operation/get-players-profiles)).
- **No batch parameter** exists for `/predictions`, `/fixtures/statistics`, `/fixtures/events`, `/fixtures/lineups`, `/fixtures/players` (fixture\* only) or `/teams/statistics` (league\*+season\*+team\*) ([docs](https://www.api-football.com/documentation-v3)).
- **Finished-status filter** used officially: `status=FT-AET-PEN`; add `1H-HT-2H-ET-BT-P` for matches in progress ([tutorial](https://www.api-football.com/news/post/how-to-get-all-fixtures-data-from-one-league)). The full status table (TBD, NS, 1H, HT, 2H, ET, BT, P, SUSP, INT, FT, AET, PEN, PST, CANC, ABD, AWD, WO, LIVE) is in the [docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures).
- **Derived: minimum requests per fully covered 20-team league-season** (380 fixtures):

  | Item | Requests |
  |---|---|
  | fixtures list | 1 |
  | `ids` batches (all four detail blocks) | 19 |
  | standings | 1 |
  | teams | 1 |
  | rounds | 1 |
  | top scorers, assists, yellow and red cards | 4 |
  | injuries (if one page) | 1 |
  | players (e.g. 39 pages, the 2021 example) | ~39 |
  | **Total** | **≈ 67** |

  Predictions would add 380 (1 per fixture). Historical odds cannot be backfilled (see below).
- **Derived: how long the daily quota lasts at full per-minute speed:**

  | Plan | Daily quota | Per-minute limit | Minutes to exhaust |
  |---|---|---|---|
  | Free | 100 | 10 | 10 |
  | Pro | 7,500 | 300 | 25 |
  | Ultra | 75,000 | 450 | ~167 |
  | Mega | 150,000 | 900 | ~167 |

  So the daily quota is the binding limit, and bursts must still be smoothed.
- **Reference IDs:** league and team IDs are stable across seasons; fixture IDs never change ([docs](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-leagues); [guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).

---

## Odds specifics

- **Pre-match `/odds`** ([docs](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-odds)):
  - "We provide pre-match odds between 1 and 14 days before the fixture. We keep a 7-days history *(The availability of odds may vary according to the leagues, seasons, fixtures and bookmakers)*".
  - Updated every 3 hours; the recommendation is 1 call every 3 hours; 10 results per page.
  - The guide spells it out: "Only the last seven days of odds data is retained. Query for odds on a fixture from eight days ago and you'll get nothing back … You can't retrieve it retroactively" ([guide 2026-03-13](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)). Also "Only odds data from the last 7 days can be retrieved" ([WC guide 2026-04-13](https://www.api-football.com/news/post/fifa-world-cup-2026-guide-to-using-data-with-api-sports)).
- **Historical odds for past seasons: not offered in any official source.** The per-season `coverage.odds` flag exists, but the 7-day statement above rules out a retroactive backfill. Treating `odds: true` on old seasons as meaning "archived odds exist" would be my inference, and it contradicts the docs.
- **`/odds/mapping`** lists fixture IDs that have odds (100 per page, daily). **`/odds/bookmakers`** and **`/odds/bets`** are updated several times a week. Pre-match and live bet IDs "are not compatible" with each other ([docs](https://www.api-football.com/documentation-v3#tag/Odds-(Pre-Match)/operation/get-bets); [guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
- **In-play `/odds/live`** ([docs](https://www.api-football.com/documentation-v3#tag/Odds-(In-Play)/operation/get-odds-live)):
  - in-play odds for fixtures in progress;
  - fixtures "added between 15 and 5 minutes before the start" and "removed … between 5 and 20 minutes" after the end;
  - "**No history is stored**";
  - updated every 5 s ("can change in the range of 5 to 60 seconds");
  - status flags `stopped`, `blocked`, `finished`, plus `main` and `suspended` per value;
  - parameters `fixture`, `league` (no `season`), `bet`;
  - `/odds/live/bets` is updated every 60 s.
- **Release history:** the odds/live beta was announced 2022-02-02 ([post](https://www.api-football.com/news/post/in-play-odds)) and it shipped in v3.9.2 on 2022-06-08 ([post](https://www.api-football.com/news/post/api-football-new-release)).

---

## Statistics coverage (xG etc.)

- **The documentation does not list xG.** The v3.9.3 "Available statistics" for `/fixtures/statistics` are 16 types: Shots on Goal, Shots off Goal, Shots insidebox, Shots outsidebox, Total Shots, Blocked Shots, Fouls, Corner Kicks, Offsides, Ball Possession, Yellow Cards, Red Cards, Goalkeeper Saves, Total passes, Passes accurate, Passes %. There is **no `expected_goals` or `goals_prevented`**, and the response sample has neither ([docs#get-fixtures-statistics](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-statistics)). The 2026 guide lists the same stats ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
- **Indirect official evidence that the types exist.** The official widget translation file, which the docs reference, has keys for exactly the 16 documented types followed by `"s_expected_goals": "Expected goals"` and `"s_goals_prevented": "Goals prevented"` ([widgets.api-sports.io/3.1.0/en.json](https://widgets.api-sports.io/3.1.0/en.json)). This suggests the feed can return those `type` values. It says nothing about since when or for which competitions.
- **No official announcement, start date or competition list for xG / goals prevented was found.** I checked:
  - the docs, changelog and beta docs;
  - the release posts of 2022-06-08 and 2024-10-09;
  - blog index pages 1–9;
  - the 2026 guide and the World Cup posts.

  The official public roadmap on GitHub, linked from the [2021-05-27 post](https://www.api-football.com/news/post/public-roadmap), now returns 404 (https://github.com/api-sports/public-roadmap). **Status: not found in official sources.**
- **Other statistics notes:**
  - Half-time statistics (`half=true`) from the 2024 season onward ([docs](https://www.api-football.com/documentation-v3#tag/Fixtures/operation/get-fixtures-statistics); added in 3.9.3, [2024-10-09](https://www.api-football.com/news/post/api-football-new-release-available)).
  - "Not every league tracks every statistic … you'll encounter `null` values" ([guide](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
  - Whether stats exist is governed by `coverage.fixtures.statistics_fixtures` and `statistics_players` ([docs#get-leagues](https://www.api-football.com/documentation-v3#tag/Leagues/operation/get-leagues)).

---

## Terms relevant to local storage

Terms at [api-football.com/terms](https://www.api-football.com/terms) and [api-sports.io/terms](https://api-sports.io/terms), identical, "Last updated: Mai 21, 2025":
- **No clause forbids storing or caching data locally.** Neither Terms page addresses private analysis explicitly.
- **Resale is prohibited.** "it is prohibited to resell this data to third parties … you cannot directly sell the data we provide. We provide data for you to create different projects such as applications, websites, fantasy soccer games etc."
- **No licence to publish.** "We do not provide a "license" for the use and publication of the data … Any license or permission to publish the data must be requested by the user from the competent authorities." Data may be subject to third-party IP. Betting, TV, fantasy or mass-media use "may require additional licenses from the relevant rights holders".
- **Accounts.** Accounts are individual. Multiple accounts to raise the free limit are forbidden. Access can be cut without refund after a rights-holder complaint.
- **No guarantee.** Data is "as is" and without guarantee.

Official material actively recommends keeping data locally:
- Logos: "recommended to save this data on your side" ([docs#Logos-Images](https://www.api-football.com/documentation-v3#section/Logos-Images)).
- The docs' "Databases Solutions" section suggests Aiven or Firebase to "store, manage, and analyze your data" ([docs](https://www.api-football.com/documentation-v3#tag/Databases-Solutions)).
- Guide: "store the results in a local database or cache" ([2026-03-13](https://www.api-football.com/news/post/how-to-get-started-with-api-football-the-complete-beginners-guide)).
- Optimize post: "A server-side synchronization may need to go through all pages to prepare a local database" ([2026-07-27](https://www.api-football.com/news/post/how-to-optimize-api-sports-calls-and-quota-usage)).

The Terms offer "If you have any doubts about how you would like to use it, you can contact us directly by email."

---

## Open questions (things official sources did not answer)

1. The exact Free-plan season window, and whether and when it rolls forward. Also whether Pro, Ultra and Mega differ in historical range.
2. Whether error responses (4xx/429/5xx) or empty `200` results count against the daily quota, and the exact error text when the daily quota is exhausted.
3. Whether `/fixtures?ids=` is restricted on some plans ("When available for your plan", 2026-07-27).
4. The earliest season per competition. There is no published list; you must call `/leagues?id=` per league.
5. Since when, and for which competitions, `expected_goals` and `goals_prevented` are returned. No announcement was found.
6. Whether `/injuries`, `/fixtures` and `/leagues` impose any maximum result size or silently paginate on very large results. None is documented.
7. Whether `/predictions` remain retrievable for old, finished fixtures. Retention is not documented.
8. The Ultra per-second limit: 7/s (2026-06-12) or 7.5/s (2026-07-27).
9. Whether multiple API keys or "seats" (Pro 1, Ultra 2, Mega 3) share one daily quota. The pricing page mentions "assign API keys per project" without detail.
10. The status of RapidAPI subscriptions. The Terms still describe them, but the listing returns "API not found" (live on 2026-09-25, and in the 2026-04-23 archive). No current RapidAPI price could be verified.
11. The exact per-IP limits, versus per-key limits. They are described only qualitatively.
12. The dashboard documentation and league-ID pages require login and could not be read.
