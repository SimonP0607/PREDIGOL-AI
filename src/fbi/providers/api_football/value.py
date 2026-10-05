"""What each documented API-Football v3 endpoint is worth to PrediGol, and what to do about it.

``integration.USES`` says what PrediGol does with an endpoint today (requested, stored, read). This says what it is
WORTH: one class, a priority and the reason, so the endpoint matrix (``scripts.endpoint_matrix``) is generated
from code that a test keeps complete, not from a document that drifts.

Classes (the 5 Oct 2026 mandate's):

* ``INGEST_NOW``       - useful and not (fully) taken yet: take it now;
* ``STORE_FOR_FUTURE`` - kept (RAW, or a change-only table) for a use that is not built yet; no model reads it;
* ``PRODUCT_ONLY``     - shown to users; no model reads it, by decision;
* ``MODEL_FEATURE``    - a model input, or the market baseline a model is judged against;
* ``REFERENCE``        - catalogues and identities everything else hangs on;
* ``LOW_VALUE``        - served, cheap, nearly useless here;
* ``AVOID``            - must not be relied on (leakage, duplication of what we derive better ourselves).

Everything any endpoint answers is in RAW (``raw.ingestion_payloads`` + the gzipped body), so a field not
normalized today is recoverable later without a request - that is what "guardamos todo" means in the matrix.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

Klass = Literal["INGEST_NOW", "STORE_FOR_FUTURE", "PRODUCT_ONLY", "MODEL_FEATURE", "REFERENCE", "LOW_VALUE", "AVOID"]
Priority = Literal["P0", "P1", "P2", "P3"]


@dataclass(frozen=True, slots=True)
class Value:
    klass: Klass
    priority: Priority
    potential: str
    """What it could give, in one line."""
    action: str = ""
    """What to do next, when anything."""


VALUES: dict[str, Value] = {
    "/timezone": Value("LOW_VALUE", "P3", "zone names; PrediGol stores UTC and converts in the browser"),
    "/countries": Value("REFERENCE", "P3", "country names and flags"),
    "/leagues": Value("REFERENCE", "P0", "seasons, current flag and per-season coverage flags that decide what can "
                      "be asked at all", "read the current flag more often than daily when a season turns over"),
    "/leagues/seasons": Value("LOW_VALUE", "P3", "the list of season years"),
    "/teams": Value("REFERENCE", "P0", "team identity, venue, national/club"),
    "/teams/statistics": Value("STORE_FOR_FUTURE", "P2", "the provider's season aggregates per team (form, goals "
                               "by minute, line-ups used, penalties): a cross-check of our own aggregates",
                               "keep as validation; do not feed models what we already derive from fixtures"),
    "/teams/seasons": Value("LOW_VALUE", "P3", "the seasons a team has data for"),
    "/teams/countries": Value("LOW_VALUE", "P3", "countries that have teams"),
    "/venues": Value("PRODUCT_ONLY", "P3", "capacity, surface, city", "surface/altitude only if a study shows value"),
    "/standings": Value("MODEL_FEATURE", "P0", "table position, points gap, form, phase: motivation and context; "
                        "the competition page"),
    "/fixtures/rounds": Value("STORE_FOR_FUTURE", "P2", "round names and dates: stage of a cup, last rounds of a "
                              "league (match importance)", "feed a match-importance feature once it is studied"),
    "/fixtures": Value("MODEL_FEATURE", "P0", "results, statuses, events, line-ups, team and player statistics: the "
                       "spine of every model and page"),
    "/fixtures/headtohead": Value("AVOID", "P3", "past meetings: derived better from our own fixtures, with the "
                                  "same cut-off as every other feature"),
    "/fixtures/statistics": Value("STORE_FOR_FUTURE", "P3", "half-time split of team statistics (half=true): only "
                                  "for in-play modelling", "not before an in-play model exists"),
    "/fixtures/events": Value("MODEL_FEATURE", "P1", "goals, cards, substitutions by minute (via /fixtures?ids)"),
    "/fixtures/lineups": Value("MODEL_FEATURE", "P0", "starting XI and formation: lineup strength, availability "
                               "(via /fixtures?ids)", "a pre-kick-off read (~T-40 min) for lineup features"),
    "/fixtures/players": Value("MODEL_FEATURE", "P1", "per-player match statistics and ratings (via /fixtures?ids): "
                               "player quality ratings"),
    "/injuries": Value("MODEL_FEATURE", "P1", "who is out for a fixture: player availability",
                       "coverage is thin (the provider flags injuries for few leagues): measure before relying"),
    "/predictions": Value("AVOID", "P2", "the provider's own model: a benchmark to compare against, never an input "
                          "(its inputs and timing are unknown: leakage risk)", "keep as benchmark only"),
    "/coachs": Value("STORE_FOR_FUTURE", "P2", "coach careers: a new-coach effect feature", "study before use"),
    "/players/seasons": Value("LOW_VALUE", "P3", "season years with player data"),
    "/players/profiles": Value("REFERENCE", "P1", "player identity: birth, nationality, height, photo"),
    "/players": Value("MODEL_FEATURE", "P1", "player season aggregates: priors for player ratings",
                      "complete the current season for tracked leagues before any player-based model"),
    "/players/squads": Value("REFERENCE", "P1", "current squads: who can play"),
    "/players/teams": Value("LOW_VALUE", "P3", "a player's clubs by season (also in transfers and squads)"),
    "/players/topscorers": Value("PRODUCT_ONLY", "P2", "competition page leaders"),
    "/players/topassists": Value("PRODUCT_ONLY", "P2", "competition page leaders"),
    "/players/topyellowcards": Value("PRODUCT_ONLY", "P3", "competition page leaders"),
    "/players/topredcards": Value("PRODUCT_ONLY", "P3", "competition page leaders"),
    "/transfers": Value("STORE_FOR_FUTURE", "P2", "squad turnover between seasons",
                        "watch storage: whole histories per team (422k rows in a day)"),
    "/trophies": Value("PRODUCT_ONLY", "P3", "player and coach honours"),
    "/sidelined": Value("STORE_FOR_FUTURE", "P2", "injury and suspension history per person: availability priors"),
    "/odds/live": Value("PRODUCT_ONLY", "P1", "in-play prices and states for the live page; never a pre-match input "
                        "(it serves fixtures in play only)"),
    "/odds/live/bets": Value("REFERENCE", "P3", "the in-play bet catalogue"),
    "/odds": Value("MODEL_FEATURE", "P0", "pre-match prices by bookmaker: the market baseline every model must beat, "
                   "the consensus, the price a pick is taken at; 5 of 338 bet types normalized",
                   "normalize more markets from RAW only when a model targets them (team totals, HT/FT, corners)"),
    "/odds/mapping": Value("INGEST_NOW", "P1", "which fixtures the provider prices: the capture can skip the rest",
                           "let the capture planner skip fixtures absent from a fresh mapping (saves requests)"),
    "/odds/bookmakers": Value("REFERENCE", "P2", "bookmaker catalogue (33)"),
    "/odds/bets": Value("REFERENCE", "P2", "pre-match bet catalogue (338)"),
}
