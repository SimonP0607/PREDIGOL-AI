"""A synthetic API-Football for migration dry runs - clearly fake, never stored as real.

Two invented competitions (provider league ids 9901 and 9902, named "Dry-run
League A/B"), six invented teams each, seasons 2023 and 2024, a double round
robin. Every response follows the documented v3 shapes, so the dry run goes
through the real client, the real raw store, the real normalisers and the
real migration engine - only the HTTP layer is replaced. The universe is
deterministic: the same request always gets the same bytes.

Nothing here may be used against the real database: the dry-run command
creates a scratch database, runs there, and drops it.
"""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

LEAGUES = {9901: "Dry-run League A", 9902: "Dry-run League B"}
SEASONS = (2023, 2024)
TEAMS_PER_LEAGUE = 6
PLAYERS_PER_TEAM = 14


def team_ids(league: int) -> list[int]:
    return [league * 100 + k for k in range(1, TEAMS_PER_LEAGUE + 1)]


def _n(*parts: object) -> int:
    return int(hashlib.sha256("|".join(map(str, parts)).encode()).hexdigest()[:8], 16)


def fixtures_of(league: int, season: int) -> list[dict[str, Any]]:
    teams = team_ids(league)
    out = []
    k = 0
    start = datetime(season, 8, 10, 15, 0, tzinfo=UTC)
    for rnd in range(2):
        for i, h in enumerate(teams):
            for j, a in enumerate(teams):
                if i == j or (rnd == 0 and i > j) or (rnd == 1 and i < j):
                    continue
                fid = league * 100_000 + (season % 100) * 1000 + k
                ko = start + timedelta(days=7 * (k // 3), hours=2 * (k % 3))
                gh, ga = _n(fid, "h") % 4, _n(fid, "a") % 3
                out.append({
                    "fixture": {"id": fid, "date": ko.isoformat(), "timezone": "UTC",
                                "status": {"long": "Match Finished", "short": "FT", "elapsed": 90},
                                "venue": {"id": None, "name": None, "city": None}},
                    "league": {"id": league, "name": LEAGUES[league], "season": season,
                               "round": f"Regular Season - {k // 3 + 1}"},
                    "teams": {"home": {"id": h, "name": f"Dry-run Team {h}"},
                              "away": {"id": a, "name": f"Dry-run Team {a}"}},
                    "goals": {"home": gh, "away": ga},
                    "score": {"halftime": {"home": min(gh, 1), "away": min(ga, 1)},
                              "fulltime": {"home": gh, "away": ga},
                              "extratime": {"home": None, "away": None}, "penalty": {"home": None, "away": None}},
                })
                k += 1
    return out


def _players(team: int) -> list[int]:
    return [team * 100 + p for p in range(1, PLAYERS_PER_TEAM + 1)]


def _detail(fx: dict[str, Any]) -> dict[str, Any]:
    fid = fx["fixture"]["id"]
    h, a = fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]
    gh, ga = fx["goals"]["home"], fx["goals"]["away"]
    events: list[dict[str, Any]] = []
    for side_team, goals in ((h, gh), (a, ga)):
        for g in range(goals):
            scorer = _players(side_team)[9 + g % 2]
            events.append({"time": {"elapsed": 10 + 20 * g + (side_team % 7), "extra": None},
                           "team": {"id": side_team, "name": f"Dry-run Team {side_team}"},
                           "player": {"id": scorer, "name": f"Player {scorer}"}, "assist": {"id": None, "name": None},
                           "type": "Goal", "detail": "Normal Goal", "comments": None})
    events.append({"time": {"elapsed": 60, "extra": None}, "team": {"id": h, "name": f"Dry-run Team {h}"},
                   "player": {"id": _players(h)[12], "name": "Sub in"}, "assist": {"id": _players(h)[5], "name": "Out"},
                   "type": "subst", "detail": "Substitution 1", "comments": None})
    events.sort(key=lambda e: e["time"]["elapsed"])

    def lineup(team: int) -> dict[str, Any]:
        ps = _players(team)
        return {"team": {"id": team, "name": f"Dry-run Team {team}"}, "coach": {"id": team * 10, "name": "Coach"},
                "formation": "4-3-3",
                "startXI": [{"player": {"id": p, "name": f"Player {p}", "number": i + 1, "pos": "GDDDDMMMFFF"[i],
                                        "grid": f"{i // 4 + 1}:{i % 4 + 1}"}} for i, p in enumerate(ps[:11])],
                "substitutes": [{"player": {"id": p, "name": f"Player {p}", "number": 12 + i, "pos": "M",
                                            "grid": None}} for i, p in enumerate(ps[11:])]}

    def stats(team: int, goals: int) -> dict[str, Any]:
        shots = 6 + _n(fid, team, "s") % 12
        on = min(shots, goals + _n(fid, team, "o") % 5)
        passes = 300 + _n(fid, team, "p") % 250
        return {"team": {"id": team, "name": f"Dry-run Team {team}"}, "statistics": [
            {"type": "Shots on Goal", "value": on}, {"type": "Shots off Goal", "value": shots - on},
            {"type": "Total Shots", "value": shots}, {"type": "Blocked Shots", "value": _n(fid, team, "b") % 4},
            {"type": "Shots insidebox", "value": shots // 2}, {"type": "Shots outsidebox", "value": shots - shots // 2},
            {"type": "Fouls", "value": 8 + _n(fid, team, "f") % 8}, {"type": "Corner Kicks", "value": _n(fid, team, "c") % 9},
            {"type": "Offsides", "value": _n(fid, team, "x") % 4},
            {"type": "Ball Possession", "value": f"{50 + (5 if team == h else -5)}%"},
            {"type": "Yellow Cards", "value": _n(fid, team, "y") % 4}, {"type": "Red Cards", "value": None},
            {"type": "Goalkeeper Saves", "value": _n(fid, team, "k") % 5}, {"type": "Total passes", "value": passes},
            {"type": "Passes accurate", "value": int(passes * 0.8)}, {"type": "Passes %", "value": "80%"},
            {"type": "expected_goals", "value": f"{(on * 0.3):.2f}"}]}

    def players(team: int) -> dict[str, Any]:
        return {"team": {"id": team, "name": f"Dry-run Team {team}"}, "players": [
            {"player": {"id": p, "name": f"Player {p}"}, "statistics": [{
                "games": {"minutes": 90 if i < 11 else (30 if i < 12 else None), "number": i + 1, "position": "M",
                          "rating": f"{6.0 + (_n(fid, p) % 20) / 10:.1f}", "captain": i == 0, "substitute": i >= 11},
                "offsides": None, "shots": {"total": _n(fid, p, "s") % 3, "on": _n(fid, p, "s") % 2},
                "goals": {"total": None, "conceded": 0, "assists": None, "saves": None},
                "passes": {"total": 20 + _n(fid, p) % 40, "key": _n(fid, p, "k") % 3, "accuracy": "84"},
                "tackles": {"total": _n(fid, p, "t") % 4, "blocks": 0, "interceptions": _n(fid, p, "i") % 3},
                "duels": {"total": 6, "won": 3}, "dribbles": {"attempts": 1, "success": 1, "past": None},
                "fouls": {"drawn": 1, "committed": 1}, "cards": {"yellow": 0, "red": 0},
                "penalty": {"won": None, "commited": None, "scored": 0, "missed": 0, "saved": None}}]}
            for i, p in enumerate(_players(team))]}

    return {**fx, "events": events, "lineups": [lineup(h), lineup(a)], "statistics": [stats(h, gh), stats(a, ga)],
            "players": [players(h), players(a)]}


def _envelope(get: str, params: dict[str, str], response: list[dict[str, Any]], page: int = 1,
              total: int = 1) -> dict[str, Any]:
    return {"get": get, "parameters": params, "errors": [], "results": len(response),
            "paging": {"current": page, "total": total}, "response": response}


def _coverage(season: int) -> dict[str, Any]:
    return {"fixtures": {"events": True, "lineups": True, "statistics_fixtures": True, "statistics_players": True},
            "standings": True, "players": True, "top_scorers": True, "top_assists": True, "top_cards": True,
            "injuries": season >= 2024, "predictions": False, "odds": False}


class FakeApi:
    """The MockTransport handler. ``calls`` records every request path+query."""

    def __init__(self) -> None:
        self.calls: list[str] = []

    def transport(self) -> httpx.MockTransport:
        return httpx.MockTransport(self.handle)

    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        q = dict(request.url.params.items())
        self.calls.append(f"{path}?{request.url.query.decode()}")
        if path.endswith("/leagues"):
            body = [{"league": {"id": lid, "name": name, "type": "League"}, "country": {"name": "Nowhere"},
                     "seasons": [{"year": s, "start": f"{s}-08-01", "end": f"{s + 1}-05-31", "current": False,
                                  "coverage": _coverage(s)} for s in SEASONS]}
                    for lid, name in LEAGUES.items() if "id" not in q or int(q["id"]) == lid]
            return httpx.Response(200, json=_envelope("leagues", q, body))
        if path.endswith("/fixtures") and "ids" in q:
            wanted = {int(x) for x in q["ids"].split("-")}
            found = [_detail(fx) for lid in LEAGUES for s in SEASONS for fx in fixtures_of(lid, s)
                     if fx["fixture"]["id"] in wanted]
            return httpx.Response(200, json=_envelope("fixtures", q, found))
        if path.endswith("/fixtures"):
            lid, season = int(q.get("league", 0)), int(q.get("season", 0))
            if lid not in LEAGUES or season not in SEASONS:
                return httpx.Response(200, json=_envelope("fixtures", q, []))
            return httpx.Response(200, json=_envelope("fixtures", q, fixtures_of(lid, season)))
        if path.endswith("/standings"):
            lid, season = int(q["league"]), int(q["season"])
            table: dict[int, dict[str, int]] = {t: {"p": 0, "w": 0, "d": 0, "l": 0, "gf": 0, "ga": 0, "pts": 0}
                                                for t in team_ids(lid)}
            for fx in fixtures_of(lid, season):
                h, a = fx["teams"]["home"]["id"], fx["teams"]["away"]["id"]
                gh, ga = fx["goals"]["home"], fx["goals"]["away"]
                for t, gf, gc in ((h, gh, ga), (a, ga, gh)):
                    r = table[t]
                    r["p"] += 1
                    r["gf"] += gf
                    r["ga"] += gc
                    r["w" if gf > gc else "d" if gf == gc else "l"] += 1
                    r["pts"] += 3 if gf > gc else 1 if gf == gc else 0
            rows = sorted(table.items(), key=lambda kv: (-kv[1]["pts"], kv[1]["ga"] - kv[1]["gf"]))
            standings = [{"rank": i + 1, "team": {"id": t, "name": f"Dry-run Team {t}"}, "points": r["pts"],
                          "goalsDiff": r["gf"] - r["ga"], "group": LEAGUES[lid], "form": None,
                          "all": {"played": r["p"], "win": r["w"], "draw": r["d"], "lose": r["l"],
                                  "goals": {"for": r["gf"], "against": r["ga"]}}}
                         for i, (t, r) in enumerate(rows)]
            return httpx.Response(200, json=_envelope("standings", q, [
                {"league": {"id": lid, "season": season, "name": LEAGUES[lid], "standings": [standings]}}]))
        if path.endswith("/injuries"):
            lid, season = int(q["league"]), int(q["season"])
            first_three = fixtures_of(lid, season)[:3]
            body = [{"player": {"id": f["teams"]["home"]["id"] * 100 + 2, "name": "Injured Player",
                                "type": "Missing Fixture", "reason": "Knee Injury"},
                     "team": {"id": f["teams"]["home"]["id"]}, "fixture": {"id": f["fixture"]["id"]},
                     "league": {"id": lid, "season": season}} for f in first_three]
            return httpx.Response(200, json=_envelope("injuries", q, body))
        if path.endswith("/teams"):
            lid = int(q["league"])
            body = [{"team": {"id": t, "name": f"Dry-run Team {t}", "founded": 1900}, "venue": {"id": None}}
                    for t in team_ids(lid)]
            return httpx.Response(200, json=_envelope("teams", q, body))
        if path.endswith("/players"):
            page = int(q.get("page", 1))
            lid = int(q["league"])
            allp = [p for t in team_ids(lid) for p in _players(t)]
            chunk = allp[(page - 1) * 20: page * 20]
            body = [{"player": {"id": p, "name": f"Player {p}"}, "statistics": []} for p in chunk]
            return httpx.Response(200, json=_envelope("players", q, body, page, -(-len(allp) // 20)))
        return httpx.Response(404, json={"errors": {"endpoint": "not in the dry-run universe"}})
