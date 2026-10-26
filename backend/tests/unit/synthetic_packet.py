"""A ``packet-v8`` written by hand, with the shapes the builder (``fbi.ai.packet``) and the dossier (``fbi.intel.dossier``) really produce:
the unit tests of the package, the router, the idempotency and the battery of IA phase 1 read it without a database.

It carries BOTH families of data on purpose - goals and result on one side, corners and cards on the other - so that a test can tell what
a slice kept from what it should have left out. Every moment in it is at or before ``AT``; a test that wants a leak moves one."""

from __future__ import annotations

import copy
from datetime import UTC, datetime, timedelta
from typing import Any

from fbi.ai.packet import PACKET_VERSION, Packet

AT = datetime(2026, 10, 25, 12, 0, tzinfo=UTC)
KICKOFF = datetime(2026, 10, 25, 19, 0, tzinfo=UTC)
FIXTURE = 4242
HOME_ID, AWAY_ID = 11, 22


def iso(delta: timedelta = timedelta(0), *, base: datetime = AT) -> str:
    return (base + delta).isoformat()


def split(n: int, scale: float = 1.0) -> dict[str, Any]:
    """One split (all / home / away) of a team's last matches: goals and result data, and counts."""
    return {
        "n": n, "wins": n // 2, "draws": n // 4, "losses": n - n // 2 - n // 4, "goals_for": round(1.6 * scale, 2),
        "goals_against": 1.0, "n_stats": n, "xg_for": 1.5, "xg_against": 1.1, "shots": 13.2, "shots_against": 10.1, "sot": 4.9,
        "sot_against": 3.6, "possession": 54.3, "penalties_for": 2, "penalties_against": 1, "clean_sheets": 4, "failed_to_score": 1,
        "over_2_5": 5, "btts": 6,
        # the counts: corners, fouls, cards, reds, offsides
        "corners": round(5.8 * scale, 2), "corners_against": 4.4, "fouls": 11.2, "fouls_against": 12.0, "cards": 1.9, "reds": 1,
        "offsides": 2.1}


def team(scale: float = 1.0) -> dict[str, Any]:
    return {"n": 10, "all": split(10, scale), "home": split(5, scale), "away": split(5, scale), "results": "WWDLWWDWLW",
            "streaks": {"unbeaten": 4, "winless": 0, "scoring": 8, "conceding": 2},
            "scoreline": {"n": 10, "scored_first": 6, "won_after_scoring_first": 5, "leads_lost": 1, "comebacks": 1, "conceded_first": 4},
            "opponents": {"n": 10, "mean_elo": 1620},
            "coach": {"name": "Pep Example", "matches_seen": 10, "formations": {"4-3-3": 8}, "main_formation": "4-3-3",
                      "rotation_avg_changes": 2.1, "first_sub_minute": 62, "n_lineups": 10}}


def player(pid: int, name: str, **over: Any) -> dict[str, Any]:
    return {"id": pid, "name": name, "apps": 9, "starts": 8, "minutes": 700, "goals": 5, "assists": 2, "shots": 21, "sot": 9, "fouls": 11,
            "cards": 3, "saves": 0, "minutes_14d": 180, "rating": 7.1, "importance": 1.42, "reported_out": None} | over


def meeting(days_ago: int, *, scope: str = "league") -> dict[str, Any]:
    return {"scope": scope, "weight": 0.8, "days_ago": days_ago, "fixture_id": 9000 + days_ago, "competition": "La Liga",
            "coach_changed": False, "home_side_was": "home", "goals_home_side": 2, "goals_away_side": 1, "after_extra_time": False}


def selection(market: str, name: str, p_fair: float, line: str | None = None, **over: Any) -> dict[str, Any]:
    return {"market": market, "selection": name, "line": line, "p_fair": p_fair, "best_odds": round(1 / p_fair, 2),
            "bookmaker": "bookie", "overround": 1.05, "movement": 0.01, "dispersion": 0.02, "n_bookmakers": 7,
            "opening_as_of": iso(timedelta(hours=-30)), "opening_p_fair": p_fair - 0.01} | over


def modelled(market: str, name: str, p: float, line: str | None = None) -> dict[str, Any]:
    return {"market": market, "selection": name, "line": line, "p": p, "p_lo": round(p - 0.04, 3), "p_hi": round(p + 0.04, 3),
            "calibrated": True}


GOALS_SELECTIONS = [("1X2", "HOME", 0.48, None), ("1X2", "DRAW", 0.27, None), ("1X2", "AWAY", 0.25, None), ("DC", "1X", 0.75, None),
                    ("OU", "OVER", 0.55, "2.5"), ("OU", "UNDER", 0.45, "2.5"), ("BTTS", "YES", 0.52, None), ("BTTS", "NO", 0.48, None),
                    ("AH", "HOME", 0.5, "-0.5"), ("AH", "AWAY", 0.5, "-0.5")]
COUNT_SELECTIONS = [("CORNERS_OU", "OVER", 0.5, "9.5"), ("CORNERS_OU", "UNDER", 0.5, "9.5"), ("CARDS_OU", "OVER", 0.48, "4.5"),
                    ("CARDS_OU", "UNDER", 0.52, "4.5"), ("CARDS_OU_HOME", "OVER", 0.4, "1.5"), ("CORNERS_1X2", "HOME", 0.4, None)]
OTHER_SELECTIONS = [("HT_1X2", "HOME", 0.4, None), ("YELLOW_CARDS_OU", "OVER", 0.5, "3.5"), ("FIRST_GOAL", "HOME", 0.5, None)]


def evidence(i: int, kind: str = "news", claim: str = "A short report.", *, side: str | None = "home", tier: str = "media",
             url: str | None = "https://www.marca.com/futbol/2026/10/24/report.html", status: str = "PROBABLE",
             retrieved: timedelta = timedelta(hours=-3), published: timedelta | None = timedelta(hours=-5), **over: Any) -> dict[str, Any]:
    return {"id": i, "kind": kind, "claim": claim, "side": side, "player_id": 10 if kind in ("injury", "doubtful") else None,
            "status": status, "origin": "search", "tier": tier, "source": "Marca", "url": url,
            "published_at": None if published is None else iso(published), "retrieved_at": iso(retrieved), "confidence": 0.7,
            "relevance": round(1 - i / 100, 3)} | over


def content() -> dict[str, Any]:
    """The ``content`` of a packet-v8 for a league match of the 25th of October 2026, at noon, seven hours before the kick-off."""
    return {
        "fixture": {
            "id": FIXTURE, "provider_fixture_id": 1234567, "kickoff_at": iso(base=KICKOFF), "competition": "La Liga",
            "competition_country": "Spain", "competition_type": "League", "competition_tier": 1, "season": 2026,
            "round": "Regular Season - 10", "stage": "league", "venue": "Estadio Example", "venue_city": "Madrid", "venue_country": "Spain",
            "neutral": False, "status": "NS", "referee": "A. Referee", "referee_id": 77, "referee_seen_at": iso(timedelta(hours=-20)),
            "home": {"id": HOME_ID, "name": "Home FC", "country": "Spain"}, "away": {"id": AWAY_ID, "name": "Away CF", "country": "Spain"},
            "kickoff_changes": [{"observed_at": iso(timedelta(days=-2)), "before": iso(base=KICKOFF - timedelta(hours=1)),
                                 "after": iso(base=KICKOFF)}]},
        "phase": {"version": "phase-v2", "stage": "Regular Season", "kind": "league", "role": "round", "round_key": "regular_season",
                  "tie": None},
        "standings": {"home": {"position": 3, "points": 20, "played": 9, "goal_difference": 7},
                      "away": {"position": 9, "points": 12, "played": 9, "goal_difference": 0},
                      "note": "Table of the stage of the match, as of the last snapshot before the moment."},
        "stakes": {"home": {"title": 0.12, "europe": 0.8, "relegation": 0.0}, "away": {"title": 0.0, "europe": 0.1, "relegation": 0.05}},
        "scenarios": {"status": "stands", "reading": "none", "note": "What the match alone does to the table."},
        "form": {"home": {"n": 5, "results": "WWDLW", "points": 10}, "away": {"n": 5, "results": "LDLWD", "points": 5}},
        "elo": {"home": 1710, "away": 1580, "diff": 130, "version": "elo-v2", "as_of": iso(timedelta(hours=-6))},
        "absences": {"home": [{"player_id": 10, "name": "A. Striker", "kind": "injury", "status": "OUT", "importance": 1.8}], "away": []},
        "lineups": {"confirmed": False, "home": None, "away": None},
        "travel": {"km": 0, "same_city": True},
        "factors": {"version": "factors-v1", "items": [{"code": "FORM", "status": "stands", "direction": "HOME"}]},
        "h2h": {"n": 8, "n_effective": 4.2, "status": "stands", "record": {"home": 4, "draws": 2, "away": 2},
                "note": "The meetings of the two sides, weighted by age and relevance.",
                "weights_note": "Weights: league 1.0, cup 0.8, friendly 0.2; halved every 3 years.",
                "weights": {"league": 1.0, "cup": 0.8, "friendly": 0.2}, "same_venue": 4, "last_days_ago": 120, "oldest_days_ago": 2900,
                "meetings": [meeting(d) for d in (120, 410, 800, 1200, 1500, 1900, 2400, 2900)]},
        "schedule": {"home": {"rest_days": 6, "load_14d": 3}, "away": {"rest_days": 3, "load_14d": 4}, "flags": ["away_short_rest"],
                     "calendar": {"note": "Matches of the clubs this season, with the competitions PrediGol follows."}},
        "stats": {"home": {"shots": 13.2, "sot": 4.9, "xg": 1.5, "n_xg": 8, "possession": 54.3, "corners": 5.8, "shots_against": 10.1,
                           "sot_against": 3.6, "xg_against": 1.1, "n": 10},
                  "away": {"shots": 11.0, "sot": 3.9, "xg": 1.2, "n_xg": 8, "possession": 47.0, "corners": 4.1, "shots_against": 12.4,
                           "sot_against": 4.4, "xg_against": 1.5, "n": 10}},
        "dossier": {
            "version": "dossier-v3", "teams": {"home": team(1.0), "away": team(0.8)},
            "players": {"home": [player(10, "A. Striker", reported_out="OUT"), player(12, "B. Midfielder")],
                        "away": [player(20, "C. Defender"), player(21, "D. Keeper", saves=40, fouls=1, cards=0)]},
            "referee": {"name": "A. Referee", "id": 77, "identity": "id", "matches": 31, "with_stats": 29, "cards_per_match": 5.1,
                        "reds_per_match": 0.2, "cards_home_per_match": 2.4, "cards_away_per_match": 2.7, "fouls_per_match": 24.3,
                        "penalties_per_match": 0.21},
            "context": {"derby": True, "friendly": False, "cup": False, "knockout": False, "final": False, "round": "Regular Season - 10"},
            "h2h": {"n": 8, "n_effective": 4.2, "last_days_ago": 120, "oldest_days_ago": 2900},
            "tactics": {"status": "stands", "home": {"press": "high"}, "away": {"press": "low"}},
            "national": {}},
        "market": {"selections": [selection(m, s, p, line) for m, s, p, line in GOALS_SELECTIONS + COUNT_SELECTIONS + OTHER_SELECTIONS]},
        "models": {"poisson": {"selections": [modelled(m, s, p, line) for m, s, p, line in GOALS_SELECTIONS + COUNT_SELECTIONS + OTHER_SELECTIONS]},
                   "elo": {"selections": [modelled(m, s, p, line) for m, s, p, line in GOALS_SELECTIONS[:3]]}},
        "forecast": {"version": "forecast-v1", "markets": [
            {"market": "1X2", "line": None, "model": "poisson", "calibration": "isotonic", "basis": "goals", "likely": "HOME",
             "known_at": iso(timedelta(hours=-4)), "data_cutoff_at": iso(timedelta(hours=-6)),
             "outcomes": [{"selection": "HOME", "p": 0.49}, {"selection": "DRAW", "p": 0.27}, {"selection": "AWAY", "p": 0.24}]},
            {"market": "CORNERS_OU", "line": "9.5", "model": "poisson", "calibration": "none", "basis": "counts", "likely": "OVER",
             "known_at": iso(timedelta(hours=-4)), "data_cutoff_at": iso(timedelta(hours=-6)),
             "outcomes": [{"selection": "OVER", "p": 0.52}, {"selection": "UNDER", "p": 0.48}]}]},
        "quality": {"competition_score": {"class": "FULL", "score": 0.93, "computed_at": iso(timedelta(days=-1))},
                    "fixture_validation": {"state": "VALIDATED", "validated_at": iso(timedelta(days=-1))}, "lineups_confirmed": False},
        "evidence": [
            evidence(1, "injury", "Striker A. Striker will miss the match with a hamstring injury.", status="CONFIRMED", tier="official",
                     url="https://www.homefc.example/news/injury-update"),
            evidence(2, "doubtful", "The goalkeeper D. Keeper is a doubt after a knock.", side="away", tier="journalist",
                     url="https://twitter.com/reporter/status/1"),
            evidence(3, "lineup", "Probable line-up: 4-3-3 with B. Midfielder starting.", tier="media",
                     url="https://www.as.com/futbol/lineups.html"),
            evidence(4, "news", "The coach praised the team's recent form.", tier="media", url="https://localpaper.example/story"),
            evidence(5, "transfer", "Home FC is in talks to sign a left back in January.", tier="media", url=None, published=None),
            evidence(6, "weather", "Rain expected in Madrid in the evening.", side=None, tier="provider", url=None),
        ],
    }


SOURCES: list[dict[str, Any]] = [
    {"block": "models", "tables": ["models.predictions"], "versions": {"poisson": "v3", "elo": "v2"},
     "data_cutoff_ts": {"elo": iso(timedelta(hours=-7)), "poisson": iso(timedelta(hours=-6))}},
    {"block": "evidence", "table": "ai.evidence", "ids": [1, 2, 3, 4, 5, 6]}]

FAMILIES: dict[str, Any] = {"version": "family-v1", "markets": [
    {"family": "CORNERS", "market": "CORNERS_OU", "line": "9.5", "model": "nb", "calibration": "none", "basis": "counts",
     "known_at": iso(timedelta(hours=-3)), "data_cutoff_at": iso(timedelta(hours=-5)), "code": "abc123", "likely": "OVER",
     "outcomes": [{"selection": "OVER", "p": 0.521, "p_lo": 0.47, "p_hi": 0.57}, {"selection": "UNDER", "p": 0.479, "p_lo": 0.43, "p_hi": 0.53}]},
    {"family": "CARDS", "market": "CARDS_OU", "line": "4.5", "model": "nb", "calibration": "none", "basis": "counts",
     "known_at": iso(timedelta(hours=-3)), "data_cutoff_at": iso(timedelta(hours=-5)), "code": "abc123", "likely": "OVER",
     "outcomes": [{"selection": "OVER", "p": 0.55, "p_lo": 0.5, "p_hi": 0.6}, {"selection": "UNDER", "p": 0.45, "p_lo": 0.4, "p_hi": 0.5}]}]}


def packet(mutate: Any = None, *, missing: list[str] | None = None, as_of: datetime = AT) -> Packet:
    """A packet; ``mutate(content)`` edits the content before it is wrapped."""
    c = content()
    if mutate is not None:
        mutate(c)
    return Packet(fixture_id=FIXTURE, as_of=as_of, content=c, sources=copy.deepcopy(SOURCES), missing=list(missing or []),
                  quality=dict(c.get("quality") or {}), version=PACKET_VERSION)
