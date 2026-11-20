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


AVAILABILITY: Final = "FBI_AVAILABILITY"
"""The availability matrix over HTTP (plan PM, PM-02-05; contract C-16): OFF while the line is absent - its five routes answer 404,
the private ones too - and ``=1`` opens them (the API recreated). It reads the tables of the nightly batch and the match's own data;
it changes nothing a page shows until a module reads it (PM-14-04)."""

AVAILABILITY_PHASES: Final = "FBI_AVAILABILITY_PHASES"
"""The cups split by phase in C-16 (plan PM, PM-02-07): OFF while the line is absent - C-16 answers ``todas`` only and a match's blocks
read its season's ``todas`` - and ``=1`` adds each season's phase cells (``previa``, ``liga_o_grupos``, ``eliminatoria``) and grades a
cup match's blocks by the cells of its own phase. The nightly batch measures the phases either way (invisible while it is off)."""

USAGE_CONSOLE: Final = "FBI_USAGE_CONSOLE"
"""The owner's console of the provider's requests by lane, endpoint and competition (plan PM, PM-04-05; BE-076, UX-175): OFF while
the line is absent - ``GET /admin/monitoring/provider-usage`` answers 404 and the console shows no tab - and ``=1`` opens it (the
API recreated). It reads what the worker already counts; it asks the provider nothing."""

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


def availability_on() -> bool:
    """Whether the routes of C-16 answer (``FBI_AVAILABILITY``, off by default)."""
    return user_switch(AVAILABILITY, default=False)


def availability_phases_on() -> bool:
    """Whether C-16 reads the cups by phase (``FBI_AVAILABILITY_PHASES``, off by default)."""
    return user_switch(AVAILABILITY_PHASES, default=False)


def usage_console_on() -> bool:
    """Whether the owner's console of the provider's requests answers (``FBI_USAGE_CONSOLE``, off by default)."""
    return user_switch(USAGE_CONSOLE, default=False)


def market_probs_on() -> bool:
    """Whether readers get the probabilities by market (``FBI_MARKET_PROBS``, off by default)."""
    return user_switch(MARKET_PROBS, default=False)


def parlay_markets_v2_on() -> bool:
    """Whether Mi parlay accepts the markets the catalogue settles (``FBI_PARLAY_MARKETS_V2``, off by default)."""
    return user_switch(PARLAY_MARKETS_V2, default=False)


def player_markets_on() -> bool:
    """Whether readers get the players' markets of a match (``FBI_PLAYER_MARKETS``, off by default)."""
    return user_switch(PLAYER_MARKETS, default=False)
