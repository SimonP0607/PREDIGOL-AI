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


_TOP_LISTS: tuple[tuple[str, Utility], ...] = (("scorers", "medium"), ("assists", "medium"), ("yellowcards", "low"),
                                               ("redcards", "low"))

USES: dict[str, Use] = {
    "/timezone": Use("FULL", "low", ("reference_refresh",), ("<none>",), "every 90 days (documented: not updated)",
                     ("raw only (by decision)",), (),
                     notes="PrediGol stores and requests in UTC; the user's zone is applied in the browser. The list "
                           "is kept as RAW only."),
    "/countries": Use("FULL", "low", ("reference_refresh",), ("<none>",), "weekly (documented: 1 call per day; "
                      "updated only when a country is added)", ("core.countries (change-only)",),
                      ("country flags (fallback to the league's country block)",)),
    "/leagues": Use("FULL", "high", ("catalogue_refresh (coverage)", "seasons refresh", "truth audit"),
                    ("<none>", "id", "team"), "every 24 h (documented: 1 call per hour)",
                    ("core.competitions", "core.competition_seasons", "raw.league_coverage"),
                    ("Matches, Admin catalogue, migration planner (coverage flags)",),
                    gaps=("the current flag is read once a day, not hourly: a season that turns current is seen up to "
                          "24 h late",),
                    notes="logo, flag, country code and per-season coverage stored (0046)."),
    "/leagues/seasons": Use("FULL", "low", ("reference_refresh",), ("<none>",), "weekly", ("raw only (by decision)",),
                            (), notes="Every season is listed per league by /leagues; kept as RAW."),
    "/teams": Use("FULL", "high", ("historical_backfill (teams of a league-season)", "scripts.sync_teams",
                                   "truth audit (id)"), ("league,season", "id"), "per season, then on demand",
                  ("core.teams", "core.venues", "core.team_season_memberships"),
                  ("team pages, logos everywhere", "national-team detection"),
                  notes="team.national, code, founded, logo and the venue block are kept."),
    "/teams/statistics": Use("FULL", "medium", ("reference_refresh (team_statistics)", "truth audit"),
                             ("league,season,team",),
                             "daily for teams playing within 72 h, weekly otherwise (documented: 1 call per day for "
                             "teams with a match that day, else 1 per week)",
                             ("core.team_season_stats (change-only snapshots: averages and totals apart; raw = the "
                              "whole answer)",), ("Admin data truth (provider vs our records)",),
                             notes="a per-competition, per-season aggregate tied to league+season+team and the payload "
                                   "time; never mixed across competitions. PrediGol's own team records are computed "
                                   "from fixtures; this is the provider's, labelled.",
                             fixed=("PARTIAL until 4 Oct 2026: audit samples only",)),
    "/teams/seasons": Use("COVERED", "low", ("contract probe",), ("team",), "never on a schedule",
                          covered_by="/teams?league&season and our fixtures (the seasons a team played)"),
    "/teams/countries": Use("FULL", "low", ("reference_refresh",), ("<none>",), "weekly", ("raw only (by decision)",),
                            (), notes="/countries holds names, codes and flags; kept as RAW."),
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
    "/fixtures/rounds": Use("FULL", "medium", ("reference_refresh (rounds, current_round)",),
                            ("league,season,dates", "league,season,current"),
                            "daily per current tracked season (documented: 1 call per day)",
                            ("core.season_rounds (snapshots: every round with its dates)",
                             "core.season_current_round"),
                            ("competition page: round calendar and current round",),
                            notes="lets the phase calendar be known before the fixtures of a later phase exist."),
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
                                      "requested: one request per match (~200 a day); the contract probe confirmed the "
                                      "statistics_1h / statistics_2h blocks",)),
    "/fixtures/events": Use("COVERED", "high", covered_by="/fixtures?ids= (events block)"),
    "/fixtures/lineups": Use("COVERED", "high", covered_by="/fixtures?ids= (lineups block)"),
    "/fixtures/players": Use("COVERED", "medium", covered_by="/fixtures?ids= (players block)"),
    "/injuries": Use("FULL", "high", ("context_refresh (every 12 h)", "truth audit"), ("league,season", "ids",
                                                                                      "player,season"),
                     "every 12 h for current seasons (documented: updated every 4 h, 1 call per day)",
                     ("core.player_absences",), ("Match Center absences",),
                     notes="data from April 2021 only (documented)."),
    "/predictions": Use("FULL", "medium", ("reference_refresh (predictions)",), ("fixture",),
                        "48 h, 24 h and 3 h before kick-off of each tracked match (documented: hourly in play, else "
                        "1 per day)", ("core.provider_predictions (change-only; comparison as sent)",),
                        ("Admin: the provider's prediction of a match (labelled, beside nothing of PrediGol's)",),
                        notes="AUXILIARY: the provider's opinion, labelled as such; no model reads it, no pick is "
                              "made from it (a test checks the model and pick code never names the table). The "
                              "teams' last-5 / season blocks and h2h it carries stay in RAW."),
    "/coachs": Use("FULL", "medium", ("reference_refresh (coachs)", "truth audit (id)"), ("team", "id"),
                   "daily for teams playing within 72 h, weekly otherwise (documented: 1 call per day)",
                   ("core.coach_profiles (change-only)", "core.coach_careers (snapshots)",
                    "core.coaches (identity from line-ups)"),
                   ("Match Center line-ups (coach name and photo)",)),
    "/players/seasons": Use("FULL", "low", ("reference_refresh",), ("<none>",), "weekly",
                            ("raw only (by decision)",), (), notes="The seasons the provider has player statistics "
                                                                    "for; kept as RAW."),
    "/players/profiles": Use("FULL", "high", ("historical_backfill (catalogue pages)", "truth audit"),
                             ("page (250 per page)", "player"), "monthly sweep (2,741 pages on 4 Oct 2026)",
                             ("core.players",), ("player pages (photo, birth, nationality, height, weight)",)),
    "/players": Use("PARTIAL", "high", ("historical_backfill (players_season units, weekly for current seasons)",
                                        "truth audit (id,season)"),
                    ("league,season,page", "id,season"), "weekly per current tracked season (documented: 1 call "
                    "per day)", ("core.player_season_stats (change-only, the provider's aggregate per team and "
                                 "competition)",),
                    ("truth audit (provider vs our aggregate)",),
                    gaps=("the product's player pages still show PrediGol's own aggregate of the per-match "
                          "statistics; the provider's (with its rating) is stored and audited, not yet displayed",
                          "the rating is the provider's own metric: kept labelled, never re-derived",),
                    fixed=("no players_season unit had ever been seeded (4 Oct 2026): the integration map claimed "
                           "a requester that never ran",)),
    "/players/squads": Use("FULL", "high", ("historical_backfill (team_squad units)", "truth audit"),
                           ("team", "player"), "weekly for the teams of current tracked seasons",
                           ("core.squad_members (first and last seen)",), ("team pages, current club",)),
    "/players/teams": Use("PARTIAL", "medium", ("truth audit",), ("player",), "audit only", ("raw only",),
                          gaps=("a player's clubs and national teams by season not stored: the club / national-"
                                "team split is computed from squads and appearances",)),
    **{f"/players/top{k}": Use("FULL", u, (f"reference_refresh (top{k})",), ("league,season",),
                               "daily per current season whose coverage has top lists (documented: 1 call per day)",
                               ("core.season_leaders (snapshots in the provider's order)",),
                               ("competition page: top lists",),
                               notes="the provider's list with its own tie-breaks (documented); its rating as sent.")
       for k, u in _TOP_LISTS},
    "/transfers": Use("FULL", "medium", ("reference_refresh (transfers)",), ("team", "player (probe)"),
                      "weekly per tracked team (documented: 1 call per day)",
                      ("core.player_transfers (snapshots per player)",), ("player page: transfers",),
                      notes="dated club changes, as the provider types them (a fee, Loan, Free, N/A)."),
    "/trophies": Use("FULL", "low", ("reference_refresh (trophies_players, trophies_coachs)",),
                     ("players (20 ids)", "coachs (20 ids)", "player", "coach"),
                     "weekly per person in scope, 20 a request (documented: 1 call per day)",
                     ("core.person_trophies (snapshots per person)",), ("player page: trophies",),
                     notes="a batched answer is one block per person ({id, trophies}) - a shape the documentation "
                           "does not show (contract probe, 4 Oct 2026)."),
    "/sidelined": Use("FULL", "medium", ("reference_refresh (sidelined_players, sidelined_coachs)",),
                      ("players (20 ids)", "coachs (20 ids)", "player", "coach"),
                      "weekly per person in scope, 20 a request (documented: 1 call per day)",
                      ("core.person_sidelined (snapshots per person)",), ("player page: periods out",),
                      notes="long-term absence history (type, start, end); /injuries says who misses a match. "
                            "Batched answers are one block per person ({id, sidelined})."),
    "/odds/live": Use("FULL", "high", ("live_odds tick",), ("<none> (all fixtures in play)", "fixture"),
                      "adaptive, every 15-60 s within the live budget (documented: updated every 5-60 s)",
                      ("market.live_odds_snapshots (change-only)", "market.live_fixture_states"),
                      ("Live page, Match Center live odds and movement",),
                      notes="no history at the provider: what is not captured live is lost."),
    "/odds/live/bets": Use("FULL", "medium", ("reference_refresh (odds_live_bets)", "catalogue file load"),
                           ("<none>",), "daily (documented: updated every 60 s, no call rate given)",
                           ("market.provider_markets (scope inplay)", "market.provider_catalogue_changes (renames)"),
                           ("odds mapping",)),
    "/odds": Use("FULL", "high", ("odds_capture (fixture, paginated)", "final_prematch"), ("fixture,page",),
                 "every 15 min within capture windows (documented: updated every 3 h)",
                 ("market.odds_snapshots", "market.market_consensus"), ("odds board, picks, settlement, backtests",),
                 notes="pre-match odds 1-14 days before kick-off, 7-day history at the provider (documented)."),
    "/odds/mapping": Use("PARTIAL", "medium", ("reference_refresh (odds_mapping, every page)",), ("page",),
                         "daily (documented: 1 call per day; 100 a page)",
                         ("market.odds_mapping_seen (first listing of each fixture)",), (),
                         gaps=("not yet read by the odds capture planner (it still asks for every tracked fixture in "
                               "its windows)",)),
    "/odds/bookmakers": Use("FULL", "medium", ("reference_refresh (odds_bookmakers)", "catalogue"), ("<none>",),
                            "daily (documented: 1 call per day)",
                            ("market.bookmakers", "market.provider_catalogue_changes (renames)"), ("odds board",)),
    "/odds/bets": Use("FULL", "medium", ("reference_refresh (odds_bets)", "catalogue file load"), ("<none>",),
                      "daily (documented: 1 call per day)",
                      ("market.provider_markets (scope prematch)", "market.provider_catalogue_changes (renames)"),
                      ("odds mapping",)),
}
