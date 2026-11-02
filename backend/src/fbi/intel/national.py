"""The people of a national-team match, as the packet's moment saw them (plan F3): ``dossier.national``.

A national side picks players from clubs all over the world, so what a reader needs about them is not in the matches of the side:
where each one plays (and since when), how he has been playing there lately, and what he has done for his country. The block reads
the tables of the identity of people (``fbi.people``: ``core.player_spells`` for the club, ``core.player_national_caps`` for the
record) and the statistics of the club matches. For each SENIOR national side of the match (a youth or Olympic side, a club, and a
team nobody has classified are left out: ``senior = false`` and nothing else) it says whose it is about:

    squad = "lineup"      the starting eleven of THIS match, when the squad sheet had been fetched by the packet's moment
    squad = "last_match"  else the starting eleven of the side's previous match settled by then - a stand-in, said so
                          (``squad_fixture`` / ``squad_date``): the call-up of this match is not known yet
    squad = "none"        neither

and, per player, ``club`` (id, name, ``since``, how the streak is known, ``last_seen`` and its age: an open streak nobody has seen for
months is probably over), ``form`` (the last five matches he played for a club in the 120 days before: minutes, goals, assists,
rating), ``caps`` (squads, caps, starts, minutes, those not known yet, the last squad and the last cap, each with its match) and
``reported_out`` (the absence the packet's own absences block lists). Nothing is estimated to fill a gap: a man with no known club
has ``club = null``.

AS OF the moment ``at``. The club is the streak that contains the DAY of ``at``; what the streak went on to be afterwards (when it
ended, where he went) is not read, and ``last_seen`` is cut at that day. The form and the caps are the matches settled by ``at`` and
kicked off before this one, with the statistics fetched by then. The streaks are read in VALID time: they are built from all the facts
there are, so a transfer first read after ``at`` but dated before it is used - true history, never a result of this match or of any
later one. The nightly leak audit (``fbi.intel.leakage``, rule ``national_known``) checks every match the block cites."""

from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.people import caps as cp
from fbi.people import player_history as ph
from fbi.people import spells as sp

VERSION: Final = "national-v1"
FORM_N: Final = 5
"""Club matches the form is made of."""
FORM_WINDOW: Final = timedelta(days=120)
"""A club match older than this says nothing about how he is playing now."""
SQUAD_WINDOW: Final = timedelta(days=400)
"""How far back the stand-in sheet is looked for."""

TEAMS_SQL: Final = """
SELECT t.id, t.name, COALESCE(k.is_national, t.is_national) AS national
  FROM core.teams t LEFT JOIN core.team_kind k ON k.team_id = t.id WHERE t.id = ANY(%(teams)s)"""

SHEET_SQL: Final = """
SELECT lp.provider_player_id AS player, max(lp.player_name) AS name
  FROM core.fixture_lineups l
  JOIN core.fixture_lineup_players lp ON lp.fixture_id = l.fixture_id AND lp.team_side = l.team_side AND lp.source = l.source
 WHERE l.fixture_id = %(fixture)s AND l.team_side = %(side)s AND l.fetched_at <= %(at)s AND lp.is_starter
 GROUP BY lp.provider_player_id ORDER BY lp.provider_player_id"""
"""The starting eleven of one side of one match, from the sheets fetched by ``at``."""

LAST_MATCH_SQL: Final = """
SELECT f.id, f.kickoff_at, (f.home_team_id = %(team)s) AS at_home
  FROM core.fixtures f JOIN core.fixture_results r ON r.fixture_id = f.id
 WHERE (f.home_team_id = %(team)s OR f.away_team_id = %(team)s) AND f.kickoff_at < %(kickoff)s
   AND f.kickoff_at >= %(since)s AND r.settled_at <= %(at)s
 ORDER BY f.kickoff_at DESC, f.id DESC LIMIT 1"""
"""The side's previous match: kicked off before this one and settled by ``at``."""

FORM_SQL: Final = """
SELECT * FROM (
    SELECT p.provider_player_id AS player, f.id AS fixture_id, f.kickoff_at, max(p.minutes) AS minutes,
           max(p.goals) AS goals, max(p.assists) AS assists, max(p.rating)::float8 AS rating,
           row_number() OVER (PARTITION BY p.provider_player_id ORDER BY f.kickoff_at DESC, f.id DESC) AS rn
      FROM core.fixture_player_stats p
      JOIN core.fixtures f ON f.id = p.fixture_id
      JOIN core.fixture_results r ON r.fixture_id = f.id
      JOIN core.teams t ON t.id = CASE p.team_side WHEN 'home' THEN f.home_team_id ELSE f.away_team_id END
      LEFT JOIN core.team_kind k ON k.team_id = t.id
     WHERE p.provider_player_id = ANY(%(players)s) AND p.fetched_at <= %(at)s AND r.settled_at <= %(at)s
       AND f.kickoff_at < %(kickoff)s AND f.kickoff_at >= %(since)s
       AND COALESCE(k.is_national, t.is_national) IS FALSE AND COALESCE(p.minutes, 0) > 0
     GROUP BY p.provider_player_id, f.id, f.kickoff_at
) m WHERE m.rn <= %(n)s ORDER BY m.player, m.rn"""
"""The matches he played for a CLUB (a team classified as not national), newest first, at most ``n`` each."""

CLUBS_SQL: Final = "SELECT provider_team_id, name FROM core.teams WHERE provider_team_id = ANY(%(clubs)s)"


def _day(value: date | None) -> str | None:
    return None if value is None else value.isoformat()


def _avg(values: list[float]) -> float | None:
    return round(sum(values) / len(values), 2) if values else None


def _form(rows: list[dict[str, Any]], today: date) -> dict[str, Any] | None:
    """The form of one player from his rows, newest first; None when he played no club match in the window."""
    if not rows:
        return None
    last = rows[0]
    return {"n": len(rows), "minutes": sum(int(r["minutes"] or 0) for r in rows), "goals": sum(int(r["goals"] or 0) for r in rows),
            "assists": sum(int(r["assists"] or 0) for r in rows), "rating": _avg([float(r["rating"]) for r in rows if r["rating"] is not None]),
            "last_match": _day(last["kickoff_at"].astimezone(UTC).date()), "last_fixture": int(last["fixture_id"]),
            "last_days_ago": (today - last["kickoff_at"].astimezone(UTC).date()).days}


def _caps(caps: list[cp.Cap], *, kickoff: datetime, today: date) -> dict[str, Any]:
    """His record for the national side before ``kickoff`` (``caps`` is newest first, as ``player_history.caps_of`` gives it)."""
    record = cp.profile(caps, before=kickoff)
    last_squad = caps[0] if caps else None
    last_cap = next((c for c in caps if c.appeared is True), None)
    return {"squads": record.squads, "caps": record.caps, "starts": record.starts, "minutes": record.minutes, "unknown": record.unknown,
            "last_squad": _day(last_squad.kickoff.astimezone(UTC).date()) if last_squad else None,
            "last_squad_fixture": last_squad.fixture_id if last_squad else None,
            "last_cap": _day(last_cap.kickoff.astimezone(UTC).date()) if last_cap else None,
            "last_cap_fixture": last_cap.fixture_id if last_cap else None,
            "last_cap_days_ago": (today - last_cap.kickoff.astimezone(UTC).date()).days if last_cap else None}


def _club(streaks: list[sp.Spell], names: dict[int, str], today: date) -> dict[str, Any] | None:
    """The club on ``today`` and how well that is known: the streak that contains the day, nothing of what came after it."""
    spell = sp.club_at(streaks, today)
    if spell is None:
        return None
    seen = min(spell.last_evidence, today)
    return {"id": spell.club, "name": names.get(spell.club), "since": _day(spell.valid_from), "source": spell.source,
            "last_seen": _day(seen), "last_seen_days_ago": (today - seen).days}


def squad_of(conn: psycopg.Connection[Any], fx: dict[str, Any], side: str, *, at: datetime) -> dict[str, Any]:
    """Whose block it is about: ``{squad, squad_fixture, squad_date, players: [(id, name)]}``, see the module's docstring."""
    team = int(fx["home_team_id" if side == "home" else "away_team_id"])
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SHEET_SQL, {"fixture": int(fx["id"]), "side": side, "at": at})
        rows = cur.fetchall()
        if rows:
            return {"squad": "lineup", "squad_fixture": None, "squad_date": None,
                    "players": [(int(r["player"]), r["name"]) for r in rows]}
        cur.execute(LAST_MATCH_SQL, {"team": team, "kickoff": fx["kickoff_at"], "since": fx["kickoff_at"] - SQUAD_WINDOW, "at": at})
        last = cur.fetchone()
        if last is not None:
            cur.execute(SHEET_SQL, {"fixture": int(last["id"]), "side": "home" if last["at_home"] else "away", "at": at})
            rows = cur.fetchall()
            if rows:
                return {"squad": "last_match", "squad_fixture": int(last["id"]), "squad_date": _day(last["kickoff_at"].astimezone(UTC).date()),
                        "players": [(int(r["player"]), r["name"]) for r in rows]}
    return {"squad": "none", "squad_fixture": None, "squad_date": None, "players": []}


def _players(conn: psycopg.Connection[Any], fx: dict[str, Any], squad: dict[str, Any], *, at: datetime,
             absent: dict[int, str]) -> list[dict[str, Any]]:
    ids = [p for p, _ in squad["players"]]
    if not ids:
        return []
    today = at.astimezone(UTC).date()
    kickoff: datetime = fx["kickoff_at"]
    streaks = ph.spells_of(conn, ids)
    names = ph.spell_names(conn, ids)
    caps = ph.caps_of(conn, ids, before=kickoff, settled_by=at)
    rows: dict[int, list[dict[str, Any]]] = defaultdict(list)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(FORM_SQL, {"players": ids, "at": at, "kickoff": kickoff, "since": at - FORM_WINDOW, "n": FORM_N})
        for r in cur.fetchall():
            rows[int(r["player"])].append(r)
        missing = {s.club for p in ids if (s := sp.club_at(streaks.get(p, []), today)) is not None} - names.keys()
        if missing:
            cur.execute(CLUBS_SQL, {"clubs": sorted(missing)})
            names |= {int(r["provider_team_id"]): str(r["name"]) for r in cur.fetchall()}
    out = []
    for player, name in squad["players"]:
        out.append({"id": player, "name": name, "club": _club(streaks.get(player, []), names, today),
                    "form": _form(rows.get(player, []), today), "caps": _caps(caps.get(player, []), kickoff=kickoff, today=today),
                    "reported_out": absent.get(player)})
    out.sort(key=lambda p: (-p["caps"]["minutes"], p["id"]))
    return out


def block(conn: psycopg.Connection[Any], fx: dict[str, Any], *, at: datetime, absent: dict[int, str]) -> dict[str, Any] | None:
    """``dossier.national`` of one match as of ``at``; None when neither side is a senior national team (a club match).
    ``fx`` is the packet's FIXTURE_SQL row; ``absent`` the players its absences block reports out (provider id -> type)."""
    teams: dict[int, tuple[str, bool]] = {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(TEAMS_SQL, {"teams": [int(fx["home_team_id"]), int(fx["away_team_id"])]})
        for r in cur.fetchall():
            teams[int(r["id"])] = (str(r["name"]), cp.is_senior_national(str(r["name"]), r["national"]))
    if not any(senior for _, senior in teams.values()):
        return None
    out: dict[str, Any] = {"version": VERSION}
    for side in ("home", "away"):
        name, senior = teams[int(fx["home_team_id" if side == "home" else "away_team_id"])]
        if not senior:
            out[side] = {"team": name, "senior": False}
            continue
        squad = squad_of(conn, fx, side, at=at)
        players = _players(conn, fx, squad, at=at, absent=absent)
        out[side] = {"team": name, "senior": True, "squad": squad["squad"], "squad_fixture": squad["squad_fixture"],
                     "squad_date": squad["squad_date"], "n": len(players),
                     "club_known": sum(1 for p in players if p["club"] is not None),
                     "form_known": sum(1 for p in players if p["form"] is not None), "players": players}
    return out
