"""MATCH INTELLIGENCE PACKAGE - ``dossier-v4``: the part of a match's packet (``fbi.ai.packet``, block ``dossier``) that
describes the people and the situation, beyond the score-based form the packet already carries:

    teams        the last ten matches each (and split home / away): goals, expected goals, shots, on target, corners,
                 fouls, cards, offsides, possession, penalties for and against; streaks; how it behaves with the score
                 (first goal, leads lost, comebacks); the quality of the opponents it met (their Elo then)
    coaches      who sat on the bench, the formations used and how often, how many starters change from one match to
                 the next (rotation), the minute of the first substitution, the record in those matches
    players      the ten matches' most important players: starts, minutes, goals, assists, shots, fouls, cards, rating,
                 saves for a goalkeeper, the minutes of the last fourteen days (load), and whether the provider reports
                 them out for this match
    referee      the person (``fbi.people``) and his matches in the 400 days before - under any spelling the provider used
                 for him: cards (yellow + red) and fouls per match, penalties per match, how the cards split between home
                 and away sides
    context      a derby (same city), a cup or knockout round, a final, a friendly, the second leg of a tie and its first
                 result - and, from the packet's own stakes block, what each side plays for. The round is read by the one
                 classifier of round labels (``fbi.competitions.stages``) and the second leg from the legs of its tie
                 already recorded at the packet's moment (``fbi.competitions.context``)
    h2h          how much the head-to-head is worth: its size (and its effective size, once the meetings are weighed), its age
    tactics      what the last matches of each side show of how it lines up and how a match goes for it - formations and changes of
                 eleven, goals by quarter of an hour and the late ones, results by who scores first and by the half-time score, the
                 first substitution by the score - each with its sample (``fbi.intel.tactics``). Descriptions only
    national     (national-team matches only) the people of each senior national side - the eleven of the match's own sheet, or
                 of the previous match's while the sheet is not known - with the club each plays for on the day and since when,
                 his form there (``fbi.intel.national``), his record for the country and whether he is reported out

Everything is read AS OF the packet's moment: matches settled by then, statistics, events and line-ups fetched by
then, the absences the latest /injuries answer by then listed. A block without data says so (``n = 0``); nothing is estimated to fill a gap.
"Nunca convertir una narrativa emocional en una certeza estadística": these are descriptions with their sample sizes.
"""

from __future__ import annotations

import math
from collections import Counter, defaultdict
from collections.abc import Sequence
from datetime import datetime, timedelta
from itertools import pairwise
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.ai.absences import absences_as_of
from fbi.competitions import context as phase_context
from fbi.intel import national, tactics
from fbi.intel.h2h import NOTE_HIGH, NOTE_LOW, HeadToHead

VERSION = "dossier-v4"
"""v4 (plan F6): ``h2h`` is read from the weighted head-to-head (``fbi.intel.h2h``) the packet carries: ``n`` is the number of
meetings, ``n_effective`` the size that their weights leave (Kish), ``relevance`` follows the effective size and the age of the newest
meeting. The words are the ones the narrative already read (``nula`` / ``baja`` / ``media`` / ``alta``). The dossier gains ``tactics``
(``fbi.intel.tactics``, ``tactics-v1``). And a squad sheet that the statistics of its match put on the other side (the provider crossed
both sheets in 202 matches, ``fbi.people.sides``) no longer gives the ``coach`` block a formation or an eleven - the coach written beside
it is the right one and is still read.

v3 (plan F3): the referee is a person with an id. His matches are those whose referee, as the provider had named it at the
packet's moment, is HIM under any of the spellings the provider used (``core.fixture_officials`` through ``core.referee_aliases``,
``fbi.people``). v2 counted the matches whose facts EVER carried the same string, so a man written three ways was three referees
with a few matches each, two men with the same initial and surname were one, and a match whose referee the provider later
changed still counted for the first. A match the identity has not seen yet falls back to the string
(``referee.identity == "text"``). The block gains ``id`` and ``identity``. The dossier gains ``national``
(``fbi.intel.national``): the clubs, the club form and the record for the country of the players of a national-team match, as of
the packet's moment (None for a match of clubs).

v2 (plan F2): ``context.knockout`` / ``context.final`` come from the one classifier of round labels (a qualifying round is
a knockout round here too, as it already was in the packet's ``fixture.stage``) and ``context.second_leg`` from the tie the match
belongs to, not from a search for the last meeting of the two sides in the 60 days before (which read any earlier match of
the pair in the season - a group-stage meeting, a first leg played earlier than that - as a first leg)."""
N = 10
LOAD_WINDOW = timedelta(days=14)
REFEREE_WINDOW = timedelta(days=400)

MATCHES_SQL = """
SELECT f.id, f.kickoff_at, (f.home_team_id = %(team)s) AS at_home,
       CASE WHEN f.home_team_id = %(team)s THEN f.away_team_id ELSE f.home_team_id END AS opponent,
       COALESCE(r.reg_goals_home, r.goals_home) AS gh, COALESCE(r.reg_goals_away, r.goals_away) AS ga,
       r.ht_goals_home AS hth, r.ht_goals_away AS hta, f.competition_season_id
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
   AND f.kickoff_at >= %(kickoff)s - interval '400 days' AND r.settled_at <= %(at)s
 ORDER BY f.kickoff_at DESC LIMIT %(n)s
"""

STATS_SQL = """
SELECT DISTINCT ON (s.fixture_id, s.team_side) s.fixture_id, s.team_side, s.shots, s.shots_on_target, s.corners,
       s.fouls, s.yellow_cards, s.red_cards, s.offsides, s.possession_pct::float8 AS possession,
       s.expected_goals::float8 AS xg, s.saves
  FROM core.fixture_team_stats s
 WHERE s.fixture_id = ANY(%(fixtures)s) AND s.fetched_at <= %(at)s
 ORDER BY s.fixture_id, s.team_side, (s.source = 'api-football') DESC, s.fetched_at DESC
"""

EVENTS_SQL = """
SELECT e.fixture_id, e.minute, e.extra_minute, e.team_side, e.event_type, e.detail, e.comments
  FROM core.fixture_events e
 WHERE e.fixture_id = ANY(%(fixtures)s) AND e.fetched_at <= %(at)s
 ORDER BY e.fixture_id, e.minute, e.extra_minute NULLS FIRST, e.seq
"""

LINEUPS_SQL = """
SELECT l.fixture_id, l.team_side, l.formation, l.coach_name,
       array_agg(lp.provider_player_id ORDER BY lp.provider_player_id) FILTER (WHERE lp.is_starter) AS starters
  FROM core.fixture_lineups l
  LEFT JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side
       AND lp.source = l.source
 WHERE l.fixture_id = ANY(%(fixtures)s) AND l.fetched_at <= %(at)s
 GROUP BY l.fixture_id, l.team_side, l.formation, l.coach_name
"""

PLAYERS_SQL = """
SELECT p.fixture_id, p.team_side, p.provider_player_id, max(p.player_name) AS name, max(p.minutes) AS minutes,
       bool_or(NOT COALESCE(p.is_substitute, false)) AS started, max(p.goals) AS goals, max(p.assists) AS assists,
       max(p.shots_total) AS shots, max(p.shots_on) AS sot, max(p.fouls_committed) AS fouls,
       max(p.yellow_cards) AS yellow, max(p.red_cards) AS red, max(p.rating)::float8 AS rating, max(p.saves) AS saves,
       max(f.kickoff_at) AS kickoff_at
  FROM core.fixture_player_stats p JOIN core.fixtures f ON f.id = p.fixture_id
 WHERE p.fixture_id = ANY(%(fixtures)s) AND p.fetched_at <= %(at)s
 GROUP BY 1, 2, 3
"""

ELO_SQL = """
SELECT fixture_id, team_id, rating_before::float8 AS rating FROM features.elo_ratings
 WHERE elo_version = %(version)s AND run_id = %(run)s AND team_id = ANY(%(teams)s) AND fixture_id = ANY(%(fixtures)s)
"""
"""The opponents' Elo before each match. ``team_id`` is in the filter so the primary key (version, run, team, fixture)
serves it: by fixture alone the run's half a million rows were read (0.24-0.75 s per team on production, 13 Oct 2026),
by team 3 ms."""

REFEREE_TEXT_HEAD = """
WITH m AS (
    SELECT DISTINCT ON (ff.fixture_id) ff.fixture_id
      FROM core.fixture_facts ff
      JOIN core.fixtures f ON f.id = ff.fixture_id
      JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE ff.referee = %(referee)s AND ff.observed_at <= %(at)s AND f.kickoff_at < %(kickoff)s
       AND f.kickoff_at >= %(since)s AND r.settled_at <= %(at)s
     ORDER BY ff.fixture_id, ff.observed_at DESC
)"""
"""The matches whose facts carried this string, until the identity had seen them. Known flaw, kept only for the fallback: the
newest row is chosen among the rows with THIS string, so a match whose referee changed afterwards still counts."""

REFEREE_ID_HEAD = """
WITH m AS (
    SELECT o.fixture_id
      FROM core.referee_aliases a
      JOIN core.fixture_officials o ON o.alias_id = a.id AND o.role = 'referee'
      JOIN core.fixtures f ON f.id = o.fixture_id
      JOIN core.fixture_results r ON r.fixture_id = f.id
     WHERE a.referee_id = %(referee_id)s AND o.observed_at <= %(at)s AND f.kickoff_at < %(kickoff)s
       AND f.kickoff_at >= %(since)s AND r.settled_at <= %(at)s
       AND NOT EXISTS (SELECT 1 FROM core.fixture_officials n
                        WHERE n.fixture_id = o.fixture_id AND n.role = o.role
                          AND n.observed_at > o.observed_at AND n.observed_at <= %(at)s)
)"""
"""The matches whose referee, AS THE PROVIDER HAD NAMED IT at ``at`` (the newest officials row at or before it), is this person
under any of his spellings."""

REFEREE_TAIL = """
, s AS (
    SELECT DISTINCT ON (t.fixture_id, t.team_side) t.fixture_id, t.team_side, t.yellow_cards, t.red_cards, t.fouls
      FROM core.fixture_team_stats t JOIN m ON m.fixture_id = t.fixture_id
     WHERE t.fetched_at <= %(at)s
     ORDER BY t.fixture_id, t.team_side, (t.source = 'api-football') DESC, t.fetched_at DESC
), p AS (
    SELECT e.fixture_id, count(*) AS penalties FROM core.fixture_events e JOIN m ON m.fixture_id = e.fixture_id
     WHERE e.event_type = 'Goal' AND e.detail IN ('Penalty', 'Missed Penalty')
       AND COALESCE(e.comments, '') <> 'Penalty Shootout' AND e.fetched_at <= %(at)s
     GROUP BY 1
)
SELECT (SELECT count(*) FROM m) AS matches,
       count(DISTINCT s.fixture_id) AS with_stats,
       sum(COALESCE(s.yellow_cards, 0) + COALESCE(s.red_cards, 0)) AS cards,
       sum(COALESCE(s.yellow_cards, 0) + COALESCE(s.red_cards, 0)) FILTER (WHERE s.team_side = 'home') AS cards_home,
       sum(COALESCE(s.yellow_cards, 0) + COALESCE(s.red_cards, 0)) FILTER (WHERE s.team_side = 'away') AS cards_away,
       sum(COALESCE(s.red_cards, 0)) AS reds,
       sum(s.fouls) AS fouls, count(s.fouls) AS fouls_n,
       (SELECT COALESCE(sum(penalties), 0) FROM p) AS penalties
  FROM s
"""

REFEREE_SQL = REFEREE_TEXT_HEAD + REFEREE_TAIL
REFEREE_BY_ID_SQL = REFEREE_ID_HEAD + REFEREE_TAIL

def _avg(xs: Sequence[float | int | None], places: int = 2) -> float | None:
    v = [float(x) for x in xs if x is not None]
    return None if not v else round(sum(v) / len(v), places)


def _rows(conn: psycopg.Connection[Any], sql: str, params: dict[str, Any]) -> list[dict[str, Any]]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return [dict(r) for r in cur.fetchall()]


def scoreline_behaviour(events: list[dict[str, Any]], side: str, gf: int, ga: int) -> dict[str, bool]:
    """From the goal events of one match (in minute order): did the team score first, lead at some point, trail at
    some point - and the result. Pure."""
    lead = 0
    led = trailed = False
    first: str | None = None
    for e in events:
        if e["event_type"] != "Goal" or e["detail"] == "Missed Penalty" or e.get("comments") == "Penalty Shootout":
            continue
        scorer = e["team_side"]
        if e["detail"] == "Own Goal":  # the provider files an own goal under the team that benefits
            pass
        if first is None:
            first = scorer
        lead += 1 if scorer == side else -1
        led = led or lead > 0
        trailed = trailed or lead < 0
    return {"scored_first": first == side, "conceded_first": first is not None and first != side,
            "led": led, "trailed": trailed, "won": gf > ga, "drew": gf == ga, "lost": gf < ga}


def team_profile(conn: psycopg.Connection[Any], team: int, *, kickoff: datetime, at: datetime,
                 elo: tuple[str, int] | None) -> dict[str, Any]:
    matches = _rows(conn, MATCHES_SQL, {"team": team, "kickoff": kickoff, "at": at, "n": N})
    if not matches:
        return {"n": 0}
    fids = [int(m["id"]) for m in matches]
    stats: dict[int, dict[str, dict[str, Any]]] = defaultdict(dict)
    for r in _rows(conn, STATS_SQL, {"fixtures": fids, "at": at}):
        stats[int(r["fixture_id"])][str(r["team_side"])] = r
    events: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for r in _rows(conn, EVENTS_SQL, {"fixtures": fids, "at": at}):
        events[int(r["fixture_id"])].append(r)
    lineups: dict[tuple[int, str], dict[str, Any]] = {(int(r["fixture_id"]), str(r["team_side"])): r
                                                      for r in _rows(conn, LINEUPS_SQL, {"fixtures": fids, "at": at})}
    crossed = tactics.crossed_sheets(conn, fids, at=at)
    ratings: dict[tuple[int, int], float] = {}
    if elo is not None:
        opponents = sorted({int(m["opponent"]) for m in matches})
        for r in _rows(conn, ELO_SQL, {"version": elo[0], "run": elo[1], "teams": opponents, "fixtures": fids}):
            ratings[(int(r["fixture_id"]), int(r["team_id"]))] = float(r["rating"])
    per: list[dict[str, Any]] = []
    for m in matches:
        fid = int(m["id"])
        side = "home" if m["at_home"] else "away"
        opp = "away" if side == "home" else "home"
        gf, ga = (int(m["gh"]), int(m["ga"])) if side == "home" else (int(m["ga"]), int(m["gh"]))
        own, their = stats.get(fid, {}).get(side) or {}, stats.get(fid, {}).get(opp) or {}
        evs = events.get(fid, [])
        pens_for = sum(1 for e in evs if e["event_type"] == "Goal" and e["detail"] in ("Penalty", "Missed Penalty")
                       and e.get("comments") != "Penalty Shootout" and e["team_side"] == side)
        pens_against = sum(1 for e in evs if e["event_type"] == "Goal" and e["detail"] in ("Penalty", "Missed Penalty")
                           and e.get("comments") != "Penalty Shootout" and e["team_side"] == opp)
        subs = [int(e["minute"] or 0) for e in evs if str(e["event_type"]).lower() == "subst" and e["team_side"] == side]
        lu = lineups.get((fid, side)) or {}
        if fid in crossed:  # the provider gave each team the other's eleven: the coach beside it is right, the rest is not read
            lu = {"coach_name": lu.get("coach_name")}
        per.append({"fid": fid, "kickoff": m["kickoff_at"], "side": side, "gf": gf, "ga": ga,
                    "own": own, "their": their, "pens_for": pens_for, "pens_against": pens_against,
                    "events": bool(evs), "behaviour": scoreline_behaviour(evs, side, gf, ga) if evs else None,
                    "first_sub": min(subs) if subs else None, "formation": lu.get("formation"),
                    "coach": lu.get("coach_name"), "starters": set(lu.get("starters") or []),
                    "opponent_elo": ratings.get((fid, int(m["opponent"])))})

    def block(xs: list[dict[str, Any]]) -> dict[str, Any]:
        if not xs:
            return {"n": 0}
        with_stats = [x for x in xs if x["own"]]
        return {
            "n": len(xs), "wins": sum(x["gf"] > x["ga"] for x in xs), "draws": sum(x["gf"] == x["ga"] for x in xs),
            "losses": sum(x["gf"] < x["ga"] for x in xs), "goals_for": _avg([x["gf"] for x in xs]),
            "goals_against": _avg([x["ga"] for x in xs]), "n_stats": len(with_stats),
            "xg_for": _avg([x["own"].get("xg") for x in with_stats]),
            "xg_against": _avg([x["their"].get("xg") for x in with_stats]),
            "shots": _avg([x["own"].get("shots") for x in with_stats]),
            "shots_against": _avg([x["their"].get("shots") for x in with_stats]),
            "sot": _avg([x["own"].get("shots_on_target") for x in with_stats]),
            "sot_against": _avg([x["their"].get("shots_on_target") for x in with_stats]),
            "corners": _avg([x["own"].get("corners") for x in with_stats]),
            "corners_against": _avg([x["their"].get("corners") for x in with_stats]),
            "fouls": _avg([x["own"].get("fouls") for x in with_stats]),
            "fouls_against": _avg([x["their"].get("fouls") for x in with_stats]),
            "cards": _avg([(x["own"].get("yellow_cards") or 0) + (x["own"].get("red_cards") or 0) for x in with_stats
                           if x["own"].get("yellow_cards") is not None]),
            "reds": sum(int(x["own"].get("red_cards") or 0) for x in with_stats),
            "offsides": _avg([x["own"].get("offsides") for x in with_stats]),
            "possession": _avg([x["own"].get("possession") for x in with_stats], 1),
            "penalties_for": sum(x["pens_for"] for x in xs if x["events"]),
            "penalties_against": sum(x["pens_against"] for x in xs if x["events"]),
            "clean_sheets": sum(x["ga"] == 0 for x in xs), "failed_to_score": sum(x["gf"] == 0 for x in xs),
            "over_2_5": sum(x["gf"] + x["ga"] > 2 for x in xs), "btts": sum(x["gf"] > 0 and x["ga"] > 0 for x in xs),
        }

    ordered = sorted(per, key=lambda x: x["kickoff"], reverse=True)
    results = ["W" if x["gf"] > x["ga"] else "D" if x["gf"] == x["ga"] else "L" for x in ordered]

    def run(pred: Any) -> int:
        n = 0
        for x in ordered:
            if not pred(x):
                break
            n += 1
        return n

    beh = [x["behaviour"] for x in ordered if x["behaviour"] is not None]
    formations = Counter(x["formation"] for x in ordered if x["formation"])
    starters = [x["starters"] for x in ordered if x["starters"]]
    changes = [len(a - b) for a, b in pairwise(starters) if a and b]
    elos = [x["opponent_elo"] for x in ordered if x["opponent_elo"] is not None]
    coaches = [x["coach"] for x in ordered if x["coach"]]
    return {
        "n": len(per), "all": block(per), "home": block([x for x in per if x["side"] == "home"]),
        "away": block([x for x in per if x["side"] == "away"]), "results": "".join(results),
        "streaks": {"unbeaten": run(lambda x: x["gf"] >= x["ga"]), "winless": run(lambda x: x["gf"] <= x["ga"]),
                    "scoring": run(lambda x: x["gf"] > 0), "conceding": run(lambda x: x["ga"] > 0)},
        "scoreline": {"n": len(beh), "scored_first": sum(b["scored_first"] for b in beh),
                      "won_after_scoring_first": sum(b["scored_first"] and b["won"] for b in beh),
                      "leads_lost": sum(b["led"] and not b["won"] for b in beh),
                      "comebacks": sum(b["trailed"] and not b["lost"] for b in beh),
                      "conceded_first": sum(b["conceded_first"] for b in beh)},
        "opponents": {"n": len(elos), "mean_elo": _avg(elos, 0)},
        "coach": {"name": coaches[0] if coaches else None, "matches_seen": len(coaches),
                  "formations": dict(formations.most_common(3)),
                  "main_formation": formations.most_common(1)[0][0] if formations else None,
                  "rotation_avg_changes": _avg(changes, 1), "first_sub_minute": _avg([x["first_sub"] for x in ordered], 0),
                  "n_lineups": len(starters)},
        "_fixtures": fids,
    }


def players_profile(conn: psycopg.Connection[Any], fids: list[int], side_of_fixture: dict[int, str], *,
                    at: datetime, kickoff: datetime, absent: dict[int, str]) -> list[dict[str, Any]]:
    if not fids:
        return []
    acc: dict[int, dict[str, Any]] = {}
    for r in _rows(conn, PLAYERS_SQL, {"fixtures": fids, "at": at}):
        if side_of_fixture.get(int(r["fixture_id"])) != r["team_side"]:
            continue
        pid = int(r["provider_player_id"])
        a = acc.setdefault(pid, {"id": pid, "name": r["name"], "apps": 0, "starts": 0, "minutes": 0, "goals": 0,
                                 "assists": 0, "shots": 0, "sot": 0, "fouls": 0, "cards": 0, "saves": 0,
                                 "ratings": [], "minutes_14d": 0})
        mins = int(r["minutes"] or 0)
        if mins <= 0:
            continue
        a["apps"] += 1
        a["starts"] += int(bool(r["started"]))
        a["minutes"] += mins
        for k, col in (("goals", "goals"), ("assists", "assists"), ("shots", "shots"), ("sot", "sot"),
                       ("fouls", "fouls"), ("saves", "saves")):
            a[k] += int(r[col] or 0)
        a["cards"] += int(r["yellow"] or 0) + int(r["red"] or 0)
        if r["rating"] is not None:
            a["ratings"].append(float(r["rating"]))
        if r["kickoff_at"] >= kickoff - LOAD_WINDOW:
            a["minutes_14d"] += mins
    total = sum(a["minutes"] for a in acc.values()) or 1
    out = []
    for a in acc.values():
        if a["apps"] == 0:
            continue
        importance = a["minutes"] / total * 11 + 0.5 * (a["goals"] + a["assists"]) / max(1, a["apps"])
        out.append({k: v for k, v in a.items() if k != "ratings"} | {
            "rating": _avg(a["ratings"]), "importance": round(importance, 3),
            "reported_out": absent.get(a["id"])})
    out.sort(key=lambda p: -p["importance"])
    return out[:6]


def referee_profile(conn: psycopg.Connection[Any], referee: str | None, *, kickoff: datetime, at: datetime,
                    referee_id: int | None = None) -> dict[str, Any]:
    """The referee of the match and what he does, as known at ``at``. With ``referee_id`` the matches are his under every
    spelling; without it (the identity has not seen the match yet) they are the matches whose facts carried ``referee``."""
    if referee_id is None and not referee:
        return {"name": None, "matches": 0, "id": None, "identity": None}
    params: dict[str, Any] = {"at": at, "kickoff": kickoff, "since": kickoff - REFEREE_WINDOW}
    with conn.cursor(row_factory=dict_row) as cur:
        if referee_id is not None:
            cur.execute(REFEREE_BY_ID_SQL, params | {"referee_id": referee_id})
        else:
            cur.execute(REFEREE_SQL, params | {"referee": referee})
        r = dict(cur.fetchone() or {})
    n, ns = int(r.get("matches") or 0), int(r.get("with_stats") or 0)
    out: dict[str, Any] = {"name": referee, "id": referee_id, "identity": "id" if referee_id is not None else "text",
                           "matches": n, "with_stats": ns}
    if ns:
        out |= {"cards_per_match": round(float(r["cards"] or 0) / ns, 2),
                "reds_per_match": round(float(r["reds"] or 0) / ns, 3),
                "cards_home_per_match": round(float(r["cards_home"] or 0) / ns, 2),
                "cards_away_per_match": round(float(r["cards_away"] or 0) / ns, 2),
                "fouls_per_match": None if not r.get("fouls_n") else
                round(float(r["fouls"] or 0) / (int(r["fouls_n"]) / 2), 1)}
    if n:
        out["penalties_per_match"] = round(float(r.get("penalties") or 0) / n, 3)
    return out


def context_profile(conn: psycopg.Connection[Any], fx: dict[str, Any], *, at: datetime) -> dict[str, Any]:
    """Derby, cup, knockout, final, friendly, second leg. The round by the one classifier of round labels, the second leg by the
    legs of its tie already recorded at ``at`` - never by anything that came out of the tie."""
    name = str(fx.get("competition") or "")
    kind = str(fx.get("competition_kind") or fx.get("competition_type") or "")
    rnd = str(fx.get("round") or "")
    reading = phase_context.reading_of(rnd)
    friendly = "friendl" in name.lower() or "friendl" in kind.lower()
    cup = "cup" in kind.lower() or "copa" in name.lower() or "cup" in name.lower() or "pokal" in name.lower()
    knockout = reading is not None and reading.kind in ("knockout", "qualifying")
    final = reading is not None and reading.role == "final"
    derby = bool(fx.get("home_base_city")) and fx.get("home_base_city") == fx.get("away_base_city")
    out: dict[str, Any] = {"derby": derby, "friendly": friendly, "cup": cup, "knockout": knockout, "final": final,
                           "round": rnd or None}
    phase = phase_context.phase_as_of(conn, int(fx["id"]), at=at) if fx.get("id") is not None else None
    tie = None if phase is None else phase.tie
    if tie is not None and tie.format == "two_legged" and tie.leg >= 2 and tie.aggregate is not None and tie.previous:
        first = tie.previous[0]
        h, a = first.goals_home_side, first.goals_away_side  # the first leg from this match's home side's point of view
        out["second_leg"] = {"first_leg_at": first.kickoff_at.isoformat(), "first_leg_score_home_side": h,
                             "first_leg_score_away_side": a, "aggregate_need": (
                                 "el local remonta" if h < a else "el visitante remonta" if a < h else "empate global")}
    return out


def h2h_relevance(h2h: HeadToHead) -> dict[str, Any]:
    """How much the head-to-head is worth: few, old or minor meetings weigh little (the words of ``fbi.intel.h2h``)."""
    return {"n": h2h.n, "n_effective": round(h2h.n_effective, 1), "last_days_ago": h2h.last_age_days,
            "relevance": h2h.relevance, "note": NOTE_HIGH if h2h.relevance == "alta" else NOTE_LOW}


def build_dossier(conn: psycopg.Connection[Any], fx: dict[str, Any], *, at: datetime, elo: tuple[str, int] | None,
                  referee: str | None, h2h: HeadToHead, referee_id: int | None = None,
                  tactics_status: str = "DESCRIPTIVE") -> dict[str, Any]:
    """The dossier of one match as of ``at``. ``fx`` is the packet's FIXTURE_SQL row; ``referee`` and ``referee_id`` are the
    referee of the match as of ``at`` (``fbi.people.officials``), the id absent when the identity has not seen the match;
    ``tactics_status`` is the status of the tactics factor in the registry (``fbi.intel.factors``) as the packet read it."""
    kickoff: datetime = fx["kickoff_at"]
    home, away = int(fx["home_team_id"]), int(fx["away_team_id"])
    absent: dict[int, str] = {int(r["provider_player_id"]): str(r["absence_type"] or "")
                              for r in absences_as_of(conn, int(fx["id"]), at)}
    teams: dict[str, Any] = {}
    players: dict[str, Any] = {}
    for side, team in (("home", home), ("away", away)):
        prof = team_profile(conn, team, kickoff=kickoff, at=at, elo=elo)
        fids = prof.pop("_fixtures", [])
        teams[side] = prof
        sides = {}
        if fids:
            for r in _rows(conn, "SELECT id, (home_team_id = %(team)s) AS h FROM core.fixtures WHERE id = ANY(%(f)s)",
                           {"team": team, "f": fids}):
                sides[int(r["id"])] = "home" if r["h"] else "away"
        players[side] = players_profile(conn, fids, sides, at=at, kickoff=kickoff, absent=absent)
    return {"version": VERSION, "teams": teams, "players": players,
            "referee": referee_profile(conn, referee, kickoff=kickoff, at=at, referee_id=referee_id),
            "context": context_profile(conn, fx, at=at), "h2h": h2h_relevance(h2h),
            "tactics": tactics.block(conn, home=home, away=away, kickoff=kickoff, at=at, status=tactics_status),
            "national": national.block(conn, fx, at=at, absent=absent)}


def finite(x: Any) -> Any:
    """JSON-safe: NaN and infinities out (the packet hash is canonical JSON)."""
    if isinstance(x, float) and (math.isnan(x) or math.isinf(x)):
        return None
    if isinstance(x, dict):
        return {k: finite(v) for k, v in x.items()}
    if isinstance(x, list):
        return [finite(v) for v in x]
    return x
