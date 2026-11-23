"""The switches that decide what a reader is shown (plan UX, A9): one rule for all of them.

``FBI_FORECAST_USERS``, ``FBI_CALENDAR_USERS``, ``FBI_KNOWLEDGE_USERS`` and ``FBI_READING_USERS`` are ON when the line is
absent - the owner approved showing PrediGol's forecast, the calendar, the base of the post-match and the structured reading
with phase A9 - and a line in ``/etc/predigol/app.env`` turns any of them off again without a deploy (``=0`` and the API
recreated). A value that reads as neither on nor off counts as off: when the owner wrote something to that line, showing less
is the safer reading of it. The Admin Console's preview never depends on them.
"""

from __future__ import annotations

from typing import Final

from fbi.core.env import environment

ON: Final = frozenset({"1", "on", "true", "yes"})


TRANSPARENCY: Final = "FBI_TRANSPARENCY"
"""«Cómo le va a PrediGol» (plan UX, A12): OFF while the line is absent - the page is published only after the owner reviewed
it in QA (P9) - and ``=1`` opens it to every signed-in reader (the API recreated). The Admin Console's preview
(``preview=shadow``) shows it either way."""


EXPLAIN: Final = "FBI_EXPLAIN"
"""«Explícame» (plan UX, B9): ON while the line is absent - it reads what PrediGol already keeps, calls no AI and costs
nothing - and ``=0`` takes the buttons and their routes away (the API recreated)."""


ODDS_EXPLORER: Final = "FBI_ODDS_EXPLORER"
"""The new Cuotas explorer (plan Cuotas, BE-011 exposes it, UX-068 reads it): OFF while the line is absent - the explorer is
deployed off and switched on once it is verified in production (decision 8 of the plan) - and ``=1`` shows it instead of the
current Cuotas page (the API recreated). The explorer's endpoints answer either way: the switch decides what the page shows."""


ODDS_STATUS: Final = "FBI_ODDS_STATUS"
"""«Estado de los precios» (plan maestro UX/UI 2026, decision 4; BE-038): OFF while the line is absent - ``GET /odds/status``
does not exist (404) and the page shows no way to it - and ``=1`` opens it to every signed-in reader (the API recreated). It
reads what the capture already stored: it asks the provider nothing and changes no price."""


NEWS_FEED: Final = "FBI_NEWS_FEED"
"""The Noticias section (plan maestro UX/UI 2026, decision 2; BE-040): OFF while the line is absent - ``GET /news`` does not
exist (404) and the page shows no way to it - and ``=1`` opens it to every signed-in reader (the API recreated). It lists the
items the matches' news already show (``FBI_NEWS_USERS`` still decides whether readers see news at all); it searches nothing."""


ODDS_BY_MATCH: Final = "FBI_ODDS_BY_MATCH"
"""Cuotas «Por partido» (plan maestro unificado UX/UI e Intelligence 2026, UX-141; sheets C01, C02, C06): OFF while the line is
absent - Cuotas is the explorer by families alone - and ``=1`` opens the page on the view by match, the explorer one tap away
(«Por mercado»). It reads the explorer's own endpoints: no new query, no price changed."""


NAV_V2: Final = "FBI_NAV_V2"
"""The navigation of the unified plan (UX-152; decisions D-01 and D-02): OFF while the line is absent - the bars of today - and
``=1`` gives the phone Inicio · Partidos · Noticias · Picks · Más («Mis picks» inside Picks and «Más») and the desk its new bar."""


SEARCH: Final = "FBI_SEARCH"
"""The readers' global search (UX-153; maqueta 14): OFF while the line is absent and ``=1`` puts the search in the top bar. It
reads ``GET /search`` as it is: what a reader may already open."""


PROFILES: Final = "FBI_PROFILES"
"""The pages of a club, a national team and a player, and «Equipos» (UX-154 to UX-157; maquetas 11-13, decision D-03): OFF
while the line is absent and ``=1`` opens them to every signed-in reader. They read stored data only; nothing private."""


NEWS_V2: Final = "FBI_NEWS_V2"
"""Noticias as the maquetas 08-10 draw it (UX-158 to UX-160): OFF while the line is absent - the Noticias of today - and ``=1``
shows the new front page. Only with ``FBI_NEWS_FEED`` on; it changes how the same items are shown, never which."""


MATCH_INTELLIGENCE: Final = "FBI_MATCH_INTELLIGENCE"
"""The «Intelligence» tab of a match for readers (UX-162 to UX-166; maquetas 01-04 and 16): OFF while the line is absent - the
«Análisis» tab of today - and ``=1`` shows the public projection of the match's contract. It is the owner's switch: nothing
experimental reaches a reader either way, the server never sends it."""


STATS_V2: Final = "FBI_STATS_V2"
"""The advanced statistics (plan EA: profiles, comparisons, the Match Center's statistics; contract C-13): OFF while the line is
absent and ``=1`` opens them to every signed-in reader. They read the documents the nightly pass wrote (``FBI_STATS_AGG``): history,
measured; nothing private, nothing forecast."""


MATCH_SHOT_FUNNEL: Final = "FBI_MATCH_SHOT_FUNNEL"
"""The Match Center's shot funnel and its two shot zones (plan PM, PM-10-01, lámina I01 «M01»; FE-005): OFF while the line is absent -
Estadísticas is as it was - and ``=1`` draws them at the top of the tab once a match is under way, where the team statistics are of
level B or better (C-16, when it answers) and the match delivered every figure. It reads the match detail it already reads."""

MATCH_BALANCE: Final = "FBI_MATCH_BALANCE"
"""The Match Center's balance of the match and strip of the score's state (plan PM, PM-10-02, lámina I01 «M04»; FE-006): OFF while
the line is absent - Estadísticas is as it was - and ``=1`` draws the balance where the team statistics are of level B or better and
the strip of a finished match where the events are (C-16, when it answers). It reads the match detail it already reads."""

LINEUP_LAYERS: Final = "FBI_LINEUP_LAYERS"
"""The data layers of the Match Center's line-up pitch (plan PM, PM-10-04, lámina I02 «M02»; UX-176): OFF while the line is absent -
Alineaciones is as it was - and ``=1`` lets the reader put each starter's rating, minutes, cards or goals and assists on his marker,
where the player statistics are of level B or better (C-16, when it answers) and every starter has his line. It reads the match
detail it already reads."""

MATCH_COVERAGE: Final = "FBI_MATCH_COVERAGE"
"""The Match Center adapted to the coverage levels of C-16 (plan PM, PM-14-02, láminas I01 and I04; UX-177): OFF while the line is
absent - the six tabs and blocks as always - and ``=1`` leaves out the tabs that would open on nothing in the competition
(line-ups graded D, no market and no price, no reading of PrediGol where the result market is C or D), shows in Estadísticas what a
competition without team statistics does deliver, and notes partial odds. It reads C-16, so it needs ``FBI_AVAILABILITY`` on; with
C-16 off or silent nothing changes. It is turned on only after the shadow comparison (PM-02-06) shows no unexplained discrepancy."""

PROB_ICONS: Final = "FBI_PROB_ICONS"
"""The result forecast of «Pronóstico PrediGol» also in 100 icons, with «Mito o dato» (plan PM, PM-10-07, lámina I09 «M08»; UX-182):
OFF while the line is absent - the block is as it was - and ``=1`` offers «Barras | Iconos» on the result market where it is calibrated
with a validated calibrator (state 5 of C-16) and readers may see the forecast. It counts the figure the bars show; it computes
nothing and reads nothing new."""

AVAILABILITY: Final = "FBI_AVAILABILITY"
"""The availability matrix over HTTP (plan PM, PM-02-05; contract C-16): OFF while the line is absent - its five routes answer 404,
the private ones too - and ``=1`` opens them (the API recreated). It reads the tables of the nightly batch and the match's own data;
it changes nothing a page shows until a module reads it (PM-14-04)."""

AVAILABILITY_PHASES: Final = "FBI_AVAILABILITY_PHASES"
"""The cups split by phase in C-16 (plan PM, PM-02-07): OFF while the line is absent - C-16 answers ``todas`` only and a match's blocks
read its season's ``todas`` - and ``=1`` adds each season's phase cells (``previa``, ``liga_o_grupos``, ``eliminatoria``) and grades a
cup match's blocks by the cells of its own phase. The nightly batch measures the phases either way (invisible while it is off)."""

PROB_BY_COMPETITION: Final = "FBI_PROB_BY_COMPETITION"
"""State 5 of C-16 by competition (plan PM, PM-12-06; IA-152): OFF while the line is absent - a market's forecast is authorised as
before (catalogue ``evaluable`` and ``FBI_FORECAST_USERS``) - and ``=1`` also asks the competition's own sample: the newest weekly
report of ``fbi.coverage.model_segments`` must call the market ``apta`` there; a competition with no verdict reads «no autorizada». It
changes only what C-16 says (itself behind ``FBI_AVAILABILITY``): no pick, model or forecast reads it."""

EVALUATION_BOARD: Final = "FBI_EVALUATION_BOARD"
"""The owner's private evaluation board (plan PM, PM-12-01; IA-153): OFF while the line is absent - ``GET /admin/evaluation/board``
answers 404, the weekly batch computes no board and the Performance page shows no panel - and ``=1`` opens it. It reads predictions,
the market and the provider's forecast; it changes no pick, model or forecast."""

USAGE_CONSOLE: Final = "FBI_USAGE_CONSOLE"
"""The owner's console of the provider's requests by lane, endpoint and competition (plan PM, PM-04-05; BE-076, UX-175): OFF while
the line is absent - ``GET /admin/monitoring/provider-usage`` answers 404 and the console shows no tab - and ``=1`` opens it (the
API recreated). It reads what the worker already counts; it asks the provider nothing."""

COMPETITION_PAGE: Final = "FBI_COMPETITION_PAGE"
"""A competition's page for readers (plan PM, PM-09-04; UX-178): its tables, calendar and results, leaders and coverage level. OFF
while the line is absent - no route links to it and ``/competitions/{id}`` in the browser says it is not open - and ``=1`` opens it
(the API recreated). It reads routes readers already have (standings, reference, matches) and C-16 where ``FBI_AVAILABILITY`` is on."""

COMPETITION_DIRECTORY: Final = "FBI_COMPETITION_DIRECTORY"
"""The world directory of competitions with their level and priority (plan PM, PM-09-05; UX-179, lámina I08): OFF while the line is
absent and ``=1`` opens it. It reads C-16's directory, so it shows nothing until ``FBI_AVAILABILITY`` is on too."""

PLAYER_PROFILE_EXTRAS: Final = "FBI_PLAYER_PROFILE_EXTRAS"
"""The player's profile with the new data, the goalkeeper's included (plan PM, PM-08-06; UX-180, lámina I06): OFF while the line is
absent and ``=1`` draws the blocks. They read C-13's ``provider_extras`` (``FBI_STATS_PROVIDER_EXTRAS``) and the goals prevented only
when ``FBI_STATS_GOALS_PREVENTED`` let them through."""

WHAT_IF: Final = "FBI_WHAT_IF"
"""The calculator «¿Qué pasa si…?» of a competition's tables (plan PM, PM-09-03; UX-181, lámina I07): OFF while the line is absent
and ``=1`` shows it under the season tables (which need ``FBI_COMPETITION_TABLES``). Computed in the browser from the served rules:
no probability, no forecast. Turned on only with the owner's signature of publication (DM-14)."""

HOME_UNIFIED: Final = "FBI_HOME_UNIFIED"
"""One Inicio for everyone, with the «Tus favoritos» strip (plan de correcciones UX, AP-I01, decision D1): OFF while the line is absent, ``=1`` turns it on (the API recreated). The UX session turns it on after verifying it (D1 is approved)."""

MARKETS_V3: Final = "FBI_MARKETS_V3"
"""A match's markets as a bookmaker lays them out (plan de correcciones UX, AP-P08, decision D6): OFF while the line is absent, ``=1`` turns it on (the API recreated). The UX session turns it on after verifying it."""

DAY_HIGHLIGHTS: Final = "FBI_DAY_HIGHLIGHTS"
"""«Lo más interesante de hoy» on days without picks (plan de correcciones UX, AP-K04, decision D2): OFF while the line is absent, ``=1`` turns it on (the API recreated). The UX session turns it on after verifying it."""

MY_BOOKS: Final = "FBI_MY_BOOKS"
"""«Mis casas»: the bookmakers the reader plays at, in Perfil, Mercados and Cuotas (plan de correcciones UX, AP-P10, decision D5): OFF while the line is absent, ``=1`` turns it on (the API recreated). Only the owner turns it on, after the lawyer's answer."""

STAKES: Final = "FBI_STAKES"
"""Variable units on picks, parlays, Mis picks and Transparencia (plan de correcciones UX, AP-K07, decision D3): OFF while the line is absent, ``=1`` turns it on (the API recreated). Only the owner turns it on, when contract C-17 is active with calibrated models."""

TREND_BUILDER: Final = "FBI_TREND_BUILDER"
"""The parlay builder «Por tendencias» (plan de correcciones UX, AP-L02, decision D7): OFF while the line is absent, ``=1`` turns it on (the API recreated). Only the owner turns it on, after Intelligence validates contract C-18."""

MARKET_PROBS: Final = "FBI_MARKET_PROBS"
"""The probabilities by market of a match (plan EA, EA-201/EA-202; contract C-14): OFF while the line is absent and ``=1`` shows the
three marks - model, implied, history - on the Mercados tab. A reader sees a model's figure only for a market the catalogue holds
EVALUABLE; the rest stays the owner's (decision D-EA-2)."""


PARLAY_MARKETS_V2: Final = "FBI_PARLAY_MARKETS_V2"
"""Mi parlay accepts the markets the catalogue can settle (plan EA, EA-501 to EA-503): OFF while the line is absent - the five
markets of today - and ``=1`` admits every selection with a settlement rule, a price in force and a consensus of three houses. The
module, its rules and its look do not change."""


PLAYER_MARKETS: Final = "FBI_PLAYER_MARKETS"
"""The players' markets of a match (plan EA, EA-306/EA-401; contract C-15): OFF while the line is absent and ``=1`` shows the
prices and the history of each line. The player engine's figure stays the owner's until the catalogue holds the market evaluable."""


def user_switch(name: str, *, default: bool) -> bool:
    """Whether the switch ``name`` is on: ``default`` while the line is absent or empty, off for a value it cannot read."""
    raw = environment().get(name)
    if raw is None or not raw.strip():
        return default
    return raw.strip().lower() in ON


def transparency_open() -> bool:
    """Whether readers see «Cómo le va a PrediGol» (``FBI_TRANSPARENCY``, off by default)."""
    return user_switch(TRANSPARENCY, default=False)


def explain_on() -> bool:
    """Whether readers get «Explícame» (``FBI_EXPLAIN``, on by default)."""
    return user_switch(EXPLAIN, default=True)


def odds_explorer_on() -> bool:
    """Whether the page shows the new Cuotas explorer (``FBI_ODDS_EXPLORER``, off by default)."""
    return user_switch(ODDS_EXPLORER, default=False)


def odds_status_on() -> bool:
    """Whether readers get «Estado de los precios» (``FBI_ODDS_STATUS``, off by default)."""
    return user_switch(ODDS_STATUS, default=False)


def news_feed_on() -> bool:
    """Whether readers get the Noticias section (``FBI_NEWS_FEED``, off by default)."""
    return user_switch(NEWS_FEED, default=False)


def odds_by_match_on() -> bool:
    """Whether Cuotas opens on the view by match (``FBI_ODDS_BY_MATCH``, off by default)."""
    return user_switch(ODDS_BY_MATCH, default=False)


def nav_v2_on() -> bool:
    """Whether the bars are the unified plan's (``FBI_NAV_V2``, off by default)."""
    return user_switch(NAV_V2, default=False)


def search_on() -> bool:
    """Whether readers get the global search (``FBI_SEARCH``, off by default)."""
    return user_switch(SEARCH, default=False)


def profiles_on() -> bool:
    """Whether readers get the club, national team and player pages (``FBI_PROFILES``, off by default)."""
    return user_switch(PROFILES, default=False)


def news_v2_on() -> bool:
    """Whether Noticias shows its new front page (``FBI_NEWS_V2``, off by default)."""
    return user_switch(NEWS_V2, default=False)


def match_intelligence_on() -> bool:
    """Whether readers get a match's «Intelligence» tab (``FBI_MATCH_INTELLIGENCE``, off by default)."""
    return user_switch(MATCH_INTELLIGENCE, default=False)


def stats_v2_on() -> bool:
    """Whether readers get the advanced statistics (``FBI_STATS_V2``, off by default)."""
    return user_switch(STATS_V2, default=False)


def match_shot_funnel_on() -> bool:
    """Whether readers get the Match Center's shot funnel and two zones (``FBI_MATCH_SHOT_FUNNEL``, off by default)."""
    return user_switch(MATCH_SHOT_FUNNEL, default=False)


def match_balance_on() -> bool:
    """Whether readers get the Match Center's balance and strip of the score's state (``FBI_MATCH_BALANCE``, off by default)."""
    return user_switch(MATCH_BALANCE, default=False)


def lineup_layers_on() -> bool:
    """Whether readers get the data layers of the line-up pitch (``FBI_LINEUP_LAYERS``, off by default)."""
    return user_switch(LINEUP_LAYERS, default=False)


def match_coverage_on() -> bool:
    """Whether the Match Center adapts to the coverage levels of C-16 (``FBI_MATCH_COVERAGE``, off by default)."""
    return user_switch(MATCH_COVERAGE, default=False)


def prob_icons_on() -> bool:
    """Whether readers may read the result forecast in 100 icons, with «Mito o dato» (``FBI_PROB_ICONS``, off by default)."""
    return user_switch(PROB_ICONS, default=False)


def availability_on() -> bool:
    """Whether the routes of C-16 answer (``FBI_AVAILABILITY``, off by default)."""
    return user_switch(AVAILABILITY, default=False)


def availability_phases_on() -> bool:
    """Whether C-16 reads the cups by phase (``FBI_AVAILABILITY_PHASES``, off by default)."""
    return user_switch(AVAILABILITY_PHASES, default=False)


def prob_by_competition_on() -> bool:
    """Whether state 5 of C-16 asks the competition's own sample (``FBI_PROB_BY_COMPETITION``, off by default)."""
    return user_switch(PROB_BY_COMPETITION, default=False)


def evaluation_board_on() -> bool:
    """Whether the owner's private evaluation board answers (``FBI_EVALUATION_BOARD``, off by default)."""
    return user_switch(EVALUATION_BOARD, default=False)


def usage_console_on() -> bool:
    """Whether the owner's console of the provider's requests answers (``FBI_USAGE_CONSOLE``, off by default)."""
    return user_switch(USAGE_CONSOLE, default=False)


def competition_page_on() -> bool:
    """Whether readers get a competition's page (``FBI_COMPETITION_PAGE``, off by default)."""
    return user_switch(COMPETITION_PAGE, default=False)


def competition_directory_on() -> bool:
    """Whether readers get the world directory of competitions (``FBI_COMPETITION_DIRECTORY``, off by default)."""
    return user_switch(COMPETITION_DIRECTORY, default=False)


def player_profile_extras_on() -> bool:
    """Whether the player's profile draws the new data (``FBI_PLAYER_PROFILE_EXTRAS``, off by default)."""
    return user_switch(PLAYER_PROFILE_EXTRAS, default=False)


def what_if_on() -> bool:
    """Whether readers get the calculator «¿Qué pasa si…?» (``FBI_WHAT_IF``, off by default)."""
    return user_switch(WHAT_IF, default=False)


def home_unified_on() -> bool:
    """Whether one Inicio for everyone, with the «Tus favoritos» strip (plan de correcciones UX, AP-I01, decision D1) is on (``FBI_HOME_UNIFIED``, off by default)."""
    return user_switch(HOME_UNIFIED, default=False)


def markets_v3_on() -> bool:
    """Whether a match's markets as a bookmaker lays them out (plan de correcciones UX, AP-P08, decision D6) is on (``FBI_MARKETS_V3``, off by default)."""
    return user_switch(MARKETS_V3, default=False)


def day_highlights_on() -> bool:
    """Whether «Lo más interesante de hoy» on days without picks (plan de correcciones UX, AP-K04, decision D2) is on (``FBI_DAY_HIGHLIGHTS``, off by default)."""
    return user_switch(DAY_HIGHLIGHTS, default=False)


def my_books_on() -> bool:
    """Whether «Mis casas»: the bookmakers the reader plays at, in Perfil, Mercados and Cuotas (plan de correcciones UX, AP-P10, decision D5) is on (``FBI_MY_BOOKS``, off by default)."""
    return user_switch(MY_BOOKS, default=False)


def stakes_on() -> bool:
    """Whether variable units on picks, parlays, Mis picks and Transparencia (plan de correcciones UX, AP-K07, decision D3) is on (``FBI_STAKES``, off by default)."""
    return user_switch(STAKES, default=False)


def trend_builder_on() -> bool:
    """Whether the parlay builder «Por tendencias» (plan de correcciones UX, AP-L02, decision D7) is on (``FBI_TREND_BUILDER``, off by default)."""
    return user_switch(TREND_BUILDER, default=False)


def market_probs_on() -> bool:
    """Whether readers get the probabilities by market (``FBI_MARKET_PROBS``, off by default)."""
    return user_switch(MARKET_PROBS, default=False)


def parlay_markets_v2_on() -> bool:
    """Whether Mi parlay accepts the markets the catalogue settles (``FBI_PARLAY_MARKETS_V2``, off by default)."""
    return user_switch(PARLAY_MARKETS_V2, default=False)


def player_markets_on() -> bool:
    """Whether readers get the players' markets of a match (``FBI_PLAYER_MARKETS``, off by default)."""
    return user_switch(PLAYER_MARKETS, default=False)
