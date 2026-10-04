"""What PrediGol does with each documented API-Football v3 endpoint: who requests it, how often, where its
data lands, who reads it - the integration side of the contract (``contract.py`` is the provider's side).

Kept by hand and checked by ``scripts.audit_api_contract`` against the RAW payloads actually stored
(``raw.ingestion_payloads``): an endpoint said to be requested that has no payload, or one with payloads
that the map does not know, is reported.

Status:

* ``FULL`` - requested on a schedule, normalized, read by the product (and the models where useful);
* ``PARTIAL`` - requested, but only part of what it serves is kept or used (or only by an audit / a
  one-off job, or only some of its useful parameter forms);
* ``COVERED`` - its data arrives through another endpoint (``/fixtures?ids=`` returns each match's
  events, line-ups, statistics and players);
* ``MISSING`` - never requested; what it serves is not obtained otherwise;
* ``WRONG`` - requested but misread (none at present; ``/standings`` was until 4 Oct 2026).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

Status = Literal["FULL", "PARTIAL", "COVERED", "MISSING", "WRONG"]
Utility = Literal["high", "medium", "low"]


@dataclass(frozen=True)
class Use:
    status: Status
    utility: Utility
    requested_by: tuple[str, ...] = ()
    params_used: tuple[str, ...] = ()
    cadence: str = ""
    stored_in: tuple[str, ...] = ()
    read_by: tuple[str, ...] = ()
    covered_by: str | None = None
    gaps: tuple[str, ...] = ()
    notes: str = ""
    history: str = ""
    fixed: tuple[str, ...] = field(default_factory=tuple)


USES: dict[str, Use] = {
    "/timezone": Use("MISSING", "low", notes="PrediGol stores and requests in UTC; the user's zone is applied in the "
                     "browser. Not needed."),
    "/countries": Use("MISSING", "low", notes="Country name, code and flag arrive with every league (/leagues "
                      "country block); the flag URL is deterministic (media.api-sports.io/flags/{code}.svg)."),
    "/leagues": Use("FULL", "high", ("catalogue_refresh (coverage)", "seasons refresh", "truth audit"),
                    ("<none>", "id", "team"), "every 24 h (documented: 1 call per hour)",
                    ("core.competitions", "core.competition_seasons", "raw.league_coverage"),
                    ("Matches, Admin catalogue, migration planner (coverage flags)",),
                    gaps=("the current flag is read once a day, not hourly: a season that turns current is seen up to "
                          "24 h late",),
                    notes="logo, flag, country code and per-season coverage stored (0046)."),
    "/leagues/seasons": Use("MISSING", "low", notes="Every season is listed per league by /leagues."),
    "/teams": Use("FULL", "high", ("historical_backfill (teams of a league-season)", "scripts.sync_teams",
                                   "truth audit (id)"), ("league,season", "id"), "per season, then on demand",
                  ("core.teams", "core.venues", "core.team_season_memberships"),
                  ("team pages, logos everywhere", "national-team detection"),
                  notes="team.national, code, founded, logo and the venue block are kept."),
    "/teams/statistics": Use("PARTIAL", "medium", ("truth audit (team statistics vs ours)",), ("league,season,team",),
                             "audit only", ("raw only (core.team_season_stats exists since 0003, never written)",),
                             ("Admin data truth",),
                             gaps=("not stored as data: PrediGol computes its own team records from fixtures and "
                                   "uses the provider's only to check them",),
                             notes="a per-competition, per-season aggregate tied to league+season+team; never mixed "
                                   "across competitions (audit V2)."),
    "/teams/seasons": Use("MISSING", "low", notes="Derivable from /teams?league&season and our fixtures."),
    "/teams/countries": Use("MISSING", "low"),
    "/venues": Use("PARTIAL", "low", ("truth audit (id)",), ("id",), "audit only", ("core.venues (from /teams and "
                   "/fixtures venue blocks)",), ("match header (venue name, city)",),
                   gaps=("capacity, surface, address and image only for venues met through /teams",)),
    "/standings": Use("FULL", "high", ("context_refresh (every 12 h)", "context_due (hourly after a finished match)",
                                       "truth audit"), ("league,season",),
                      "hourly after a match until the table changes, every 12 h otherwise (documented: 1 call per "
                      "hour while a fixture is in progress, else 1 per day)",
                      ("core.standings (every table apart: group_key; all/home/away, form, status, description, "
                       "update)",),
                      ("Match Center (the table of the match's stage)", "competition page (each table apart)",
                       "AI analyst"),
                      notes="multiple tables per season since 0048 (writer) and 4 Oct 2026 (readers: "
                            "fbi.competitions).", fixed=("WRONG until 4 Oct 2026: the Match Center mixed tables "
                                                        "(DISTINCT ON team) and the competition page flattened "
                                                        "them; 1,628 current-season matches affected",)),
    "/fixtures/rounds": Use("MISSING", "medium",
                            notes="Round labels arrive with every fixture (league.round); the current round and "
                                  "the dates of each round (dates=true) would let the phase calendar be known "
                                  "before the fixtures of a later phase exist."),
    "/fixtures": Use("FULL", "high", ("fixtures_sync", "results_sync", "historical_backfill", "results_repair",
                                      "live_match (ids)", "detail backfill (ids)", "truth audit"),
                     ("league,season", "league,season,from,to", "date", "ids (20 per call)", "id"),
                     "every 6-12 h (calendar), every 6 h (results), every minute for live matches (ids), "
                     "hourly backfill (documented: 1 per minute while in progress, else 1 per day)",
                     ("core.fixtures", "core.fixture_results", "core.fixture_events", "core.fixture_lineups",
                      "core.fixture_lineup_players", "core.fixture_team_stats", "core.fixture_player_stats",
                      "core.fixture_live_states", "core.venues"),
                     ("every product page", "features (results, statistics)", "settlement"),
                     gaps=("fixture.periods (first/second half start) and status.extra (added time) - field "
                           "coverage audit", "league.standings (3.9.3 flag: does the competition cover standings)"),
                     notes="fixtures?ids= returns events, line-ups, statistics and players per match: the four "
                           "fixtures/* detail endpoints are covered by it."),
    "/fixtures/headtohead": Use("COVERED", "low", covered_by="/fixtures (our stored history of both teams)",
                                notes="The Match Center's head to head reads our fixtures; the endpoint would add "
                                      "meetings in competitions we do not store. Never a model input without a "
                                      "date cut-off (only meetings before kick-off)."),
    "/fixtures/statistics": Use("COVERED", "medium", covered_by="/fixtures?ids= (statistics block, full match)",
                                gaps=("half=true (first and second half statistics, from the 2024 season) is not "
                                      "requested",)),
    "/fixtures/events": Use("COVERED", "high", covered_by="/fixtures?ids= (events block)"),
    "/fixtures/lineups": Use("COVERED", "high", covered_by="/fixtures?ids= (lineups block)"),
    "/fixtures/players": Use("COVERED", "medium", covered_by="/fixtures?ids= (players block)"),
    "/injuries": Use("FULL", "high", ("context_refresh (every 12 h)", "truth audit"), ("league,season", "ids",
                                                                                      "player,season"),
                     "every 12 h for current seasons (documented: updated every 4 h, 1 call per day)",
                     ("core.player_absences",), ("Match Center absences",),
                     notes="data from April 2021 only (documented)."),
    "/predictions": Use("MISSING", "medium",
                        notes="The provider's own forecast (Poisson, form, comparison). Wanted only as an "
                              "auxiliary, labelled source next to PrediGol's models and the market - never as a "
                              "model input or a pick."),
    "/coachs": Use("PARTIAL", "medium", ("truth audit (id)",), ("id",), "audit only",
                   ("core.coaches (identity from line-ups: id, name)",), ("Match Center line-ups (coach name)",),
                   gaps=("careers, photos, birth and nationality from /coachs not stored",)),
    "/players/seasons": Use("MISSING", "low"),
    "/players/profiles": Use("FULL", "high", ("historical_backfill (catalogue pages)", "truth audit"),
                             ("page (250 per page)", "player"), "monthly sweep (2,741 pages on 4 Oct 2026)",
                             ("core.players",), ("player pages (photo, birth, nationality, height, weight)",)),
    "/players": Use("PARTIAL", "high", ("historical_backfill (players_season units: league,season pages)",
                                        "truth audit (id,season)"),
                    ("league,season,page", "id,season"), "per season (backfill) and audit",
                    ("raw only (players_season units store the pages; nothing normalizes them)",),
                    ("none: player pages aggregate the per-match statistics of /fixtures?ids=",),
                    gaps=("season statistics per team and competition are not normalized; the provider's season "
                          "aggregate is checked against ours by the audit only",
                          "the rating is the provider's own metric: kept labelled, never re-derived",)),
    "/players/squads": Use("FULL", "high", ("historical_backfill (team_squad units)", "truth audit"),
                           ("team", "player"), "weekly for the teams of current tracked seasons",
                           ("core.squad_members (first and last seen)",), ("team pages, current club",)),
    "/players/teams": Use("PARTIAL", "medium", ("truth audit",), ("player",), "audit only", ("raw only",),
                          gaps=("a player's clubs and national teams by season not stored: the club / national-"
                                "team split is computed from squads and appearances",)),
    "/players/topscorers": Use("MISSING", "medium", notes="Computable from our player season stats; the provider's "
                               "list applies its own tie-breaks (documented)."),
    "/players/topassists": Use("MISSING", "medium"),
    "/players/topyellowcards": Use("MISSING", "low"),
    "/players/topredcards": Use("MISSING", "low"),
    "/transfers": Use("MISSING", "medium", notes="Dated club changes: would date a player's current club instead of "
                      "inferring it from squads and the last appearance."),
    "/trophies": Use("MISSING", "low"),
    "/sidelined": Use("MISSING", "medium", notes="Long-term absence history per player (type, start, end); "
                      "/injuries only says who misses a given match."),
    "/odds/live": Use("FULL", "high", ("live_odds tick",), ("<none> (all fixtures in play)", "fixture"),
                      "adaptive, every 15-60 s within the live budget (documented: updated every 5-60 s)",
                      ("market.live_odds_snapshots (change-only)", "market.live_fixture_states"),
                      ("Live page, Match Center live odds and movement",),
                      notes="no history at the provider: what is not captured live is lost."),
    "/odds/live/bets": Use("PARTIAL", "medium", ("catalogue file load",), ("<none>",), "on catalogue reload",
                           ("market.provider_markets (scope inplay)",), ("odds mapping",),
                           gaps=("read from a saved catalogue file, not re-requested on a schedule",)),
    "/odds": Use("FULL", "high", ("odds_capture (fixture, paginated)", "final_prematch"), ("fixture,page",),
                 "every 15 min within capture windows (documented: updated every 3 h)",
                 ("market.odds_snapshots", "market.market_consensus"), ("odds board, picks, settlement, backtests",),
                 notes="pre-match odds 1-14 days before kick-off, 7-day history at the provider (documented)."),
    "/odds/mapping": Use("MISSING", "medium", notes="Which fixtures have pre-match odds: would let the capture skip "
                         "fixtures without any instead of asking for them."),
    "/odds/bookmakers": Use("PARTIAL", "medium", ("catalogue",), ("<none>",), "one call (4 Oct 2026)",
                            ("market.bookmakers",), ("odds board",)),
    "/odds/bets": Use("PARTIAL", "medium", ("catalogue file load",), ("<none>",), "on catalogue reload",
                      ("market.provider_markets (scope prematch)",), ("odds mapping",),
                      gaps=("read from a saved catalogue file, not re-requested on a schedule",)),
}
