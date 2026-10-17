# API-Football v3 - matriz de endpoints

Generada por `python -m scripts.endpoint_matrix` desde `fbi.providers.api_football.integration` (qué hacemos) y `.value` (cuánto vale). "Guardamos todo" = la respuesta completa queda en RAW (gzip + índice), así que un campo no normalizado hoy se recupera después sin pedir de nuevo.

| Endpoint | Ya ingerimos | Guardamos todo | Usamos | Valor potencial | Clase | Prioridad | Acción |
|---|---|---|---|---|---|---|---|
| `/timezone` | Sí | Sí (RAW) | - | zone names; PrediGol stores UTC and converts in the browser | LOW_VALUE | P3 | - |
| `/countries` | Sí | Sí (RAW) | country flags (fallback to the league's country block) | country names and flags | REFERENCE | P3 | - |
| `/leagues` | Sí | Sí (RAW) | Matches, Admin catalogue, migration planner (coverage flags) | seasons, current flag and per-season coverage flags that decide what can be asked at all | REFERENCE | P0 | read the current flag more often than daily when a season turns over |
| `/leagues/seasons` | Sí | Sí (RAW) | - | the list of season years | LOW_VALUE | P3 | - |
| `/teams` | Sí | Sí (RAW) | team pages, logos everywhere; national-team detection | team identity, venue, national/club | REFERENCE | P0 | - |
| `/teams/statistics` | Sí | Sí (RAW) | Admin data truth (provider vs our records) | the provider's season aggregates per team (form, goals by minute, line-ups used, penalties): a cross-check of our own aggregates | STORE_FOR_FUTURE | P2 | keep as validation; do not feed models what we already derive from fixtures |
| `/teams/seasons` | Sí, vía /fixtures?ids | Sí (RAW de /fixtures?ids) | - | the seasons a team has data for | LOW_VALUE | P3 | - |
| `/teams/countries` | Sí | Sí (RAW) | - | countries that have teams | LOW_VALUE | P3 | - |
| `/venues` | Sí | Sí (RAW) | match header (venue, city, capacity); team page (ground) | capacity, surface, city | PRODUCT_ONLY | P3 | surface/altitude only if a study shows value |
| `/standings` | Sí | Sí (RAW) | Match Center (the table of the match's stage); competition page (each table apart); AI analyst | table position, points gap, form, phase: motivation and context; the competition page | MODEL_FEATURE | P0 | - |
| `/fixtures/rounds` | Sí | Sí (RAW) | competition page: round calendar and current round | round names and dates: stage of a cup, last rounds of a league (match importance) | STORE_FOR_FUTURE | P2 | feed a match-importance feature once it is studied |
| `/fixtures` | Sí | Sí (RAW) | every product page; features (results, statistics); settlement | results, statuses, events, line-ups, team and player statistics: the spine of every model and page | MODEL_FEATURE | P0 | - |
| `/fixtures/headtohead` | Sí, vía /fixtures?ids | Sí (RAW de /fixtures?ids) | - | past meetings: derived better from our own fixtures, with the same cut-off as every other feature | AVOID | P3 | - |
| `/fixtures/statistics` | Sí, vía /fixtures?ids | Sí (RAW de /fixtures?ids) | - | half-time split of team statistics (half=true): only for in-play modelling | STORE_FOR_FUTURE | P3 | not before an in-play model exists |
| `/fixtures/events` | Sí, vía /fixtures?ids | Sí (RAW de /fixtures?ids) | - | goals, cards, substitutions by minute (via /fixtures?ids) | MODEL_FEATURE | P1 | - |
| `/fixtures/lineups` | Sí, vía /fixtures?ids | Sí (RAW de /fixtures?ids) | - | starting XI and formation: lineup strength, availability (via /fixtures?ids) | MODEL_FEATURE | P0 | a pre-kick-off read (~T-40 min) for lineup features |
| `/fixtures/players` | Sí, vía /fixtures?ids | Sí (RAW de /fixtures?ids) | - | per-player match statistics and ratings (via /fixtures?ids): player quality ratings | MODEL_FEATURE | P1 | - |
| `/injuries` | Sí | Sí (RAW) | Match Center absences | who is out for a fixture: player availability | MODEL_FEATURE | P1 | coverage is thin (the provider flags injuries for few leagues): measure before relying |
| `/predictions` | Sí | Sí (RAW) | Admin: the provider's prediction of a match (labelled, beside nothing of PrediGol's) | the provider's own model: a benchmark to compare against, never an input (its inputs and timing are unknown: leakage risk) | AVOID | P2 | keep as benchmark only |
| `/coachs` | Sí | Sí (RAW) | Match Center line-ups (coach name and photo) | coach careers: a new-coach effect feature | STORE_FOR_FUTURE | P2 | study before use |
| `/players/seasons` | Sí | Sí (RAW) | - | season years with player data | LOW_VALUE | P3 | - |
| `/players/profiles` | Sí | Sí (RAW) | player pages (photo, birth, nationality, height, weight) | player identity: birth, nationality, height, photo | REFERENCE | P1 | - |
| `/players` | Sí | Sí (RAW) | player page: the provider's season aggregate, labelled as the provider's, next to PrediGol's own; truth audit (provider vs our aggregate) | player season aggregates: priors for player ratings | MODEL_FEATURE | P1 | complete the current season for tracked leagues before any player-based model |
| `/players/squads` | Sí | Sí (RAW) | team pages, current club | current squads: who can play | REFERENCE | P1 | - |
| `/players/teams` | Sí | Sí (RAW) | player page: career (teams and seasons; club or national side by core.team_kind) | a player's career on the player page: clubs and national sides by season, beyond the seasons PrediGol tracks | PRODUCT_ONLY | P3 | - |
| `/players/topscorers` | Sí | Sí (RAW) | competition page: top lists | competition page leaders | PRODUCT_ONLY | P2 | - |
| `/players/topassists` | Sí | Sí (RAW) | competition page: top lists | competition page leaders | PRODUCT_ONLY | P2 | - |
| `/players/topyellowcards` | Sí | Sí (RAW) | competition page: top lists | competition page leaders | PRODUCT_ONLY | P3 | - |
| `/players/topredcards` | Sí | Sí (RAW) | competition page: top lists | competition page leaders | PRODUCT_ONLY | P3 | - |
| `/transfers` | Sí | Sí (RAW) | player page: transfers | squad turnover between seasons | STORE_FOR_FUTURE | P2 | watch storage: whole histories per team (422k rows in a day) |
| `/trophies` | Sí | Sí (RAW) | player page: trophies | player and coach honours | PRODUCT_ONLY | P3 | - |
| `/sidelined` | Sí | Sí (RAW) | player page: periods out | injury and suspension history per person: availability priors | STORE_FOR_FUTURE | P2 | - |
| `/odds/live` | Sí | Sí (RAW) | Live page, Match Center live odds and movement | in-play prices and states for the live page; never a pre-match input (it serves fixtures in play only) | PRODUCT_ONLY | P1 | - |
| `/odds/live/bets` | Sí | Sí (RAW) | odds mapping | the in-play bet catalogue | REFERENCE | P3 | - |
| `/odds` | Sí | Sí (RAW) | odds board, picks, settlement, backtests | pre-match prices by bookmaker: the market baseline every model must beat, the consensus, the price a pick is taken at; 5 of 338 bet types normalized | MODEL_FEATURE | P0 | normalize more markets from RAW only when a model targets them (team totals, HT/FT, corners) |
| `/odds/mapping` | Sí | Sí (RAW) | odds capture planner (a listed fixture is asked even where the season's coverage flag says no odds); price status and odds freshness (listed = covered); data quality (a listed fixture without a price is ours to catch; never listed is the provider's) | which fixtures the provider prices: overrules a stale coverage flag, and splits a missing price into ours (listed) and the provider's (never listed) | REFERENCE | P2 | never a skip list: the daily listing lags the prices (5 Oct 2026: 4 of 10 unlisted fixtures were priced before the listing was read) |
| `/odds/bookmakers` | Sí | Sí (RAW) | odds board | bookmaker catalogue (33) | REFERENCE | P2 | - |
| `/odds/bets` | Sí | Sí (RAW) | odds mapping | pre-match bet catalogue (338) | REFERENCE | P2 | - |

Endpoints revisados: 38. Integración: COVERED 6, FULL 32. Clases: AVOID 2, LOW_VALUE 5, MODEL_FEATURE 8, PRODUCT_ONLY 8, REFERENCE 9, STORE_FOR_FUTURE 6.
