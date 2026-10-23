"""Football context computed from stored data - pure functions, no database, unit-tested.

Everything here is DATA or a deterministic INFERENCE from data, labelled as such where it is shown:

* rest and congestion: days since each side's previous match, matches in the last 14 days, the
  next match within 7 days (rotation risk is an inference, said as one). Read from the competitions
  we FOLLOW they are bounds, not facts: the real rest is at most the recorded one, the real number of
  matches at least the recorded one (plan F0, defect 10). Where a team's own list of matches in every
  competition was read recently (plan F4, ``fbi.competitions.team_calendar``) they are the team's real
  figures, and ``calendar_scope`` says which of the two readings a packet is;
* what the match is worth: the zones of the table (from the provider's own row descriptions -
  champions, continental places, relegation), the points to the nearest zone boundary above and
  below and the most the team can still gain; "settled" when no boundary is reachable any more;
  for knockout rounds, the round itself;
* key players: from the season's minutes, goals, assists and rating of the team's own players -
  an absence is weighed by who is missing, never by how many;
* travel: the away side's own ground city and country against the venue's (no coordinates are
  stored, so no distance is ever claimed).
"""

from __future__ import annotations

import math
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any

# ── rest and congestion ──────────────────────────────────────────────────────

def rest_days(kickoff: datetime, previous: datetime | None) -> float | None:
    if previous is None:
        return None
    return round((kickoff - previous).total_seconds() / 86400, 1)


SHORT_REST_DAYS = 3.0
REST_GAP_DAYS = 3.0


def rest_flags(home_rest: float | None, away_rest: float | None) -> list[str]:
    """Inferences about rest, never facts about fitness - ASSUMING the calendar the rests were read from is complete."""
    flags: list[str] = []
    for side, rest, other in (("home", home_rest, away_rest), ("away", away_rest, home_rest)):
        if rest is not None and rest < SHORT_REST_DAYS:
            flags.append(f"{side}_short_rest")
        if rest is not None and other is not None and other - rest >= REST_GAP_DAYS:
            flags.append(f"{side}_rest_disadvantage")
    return flags


def rest_flags_recorded(home_rest: float | None, away_rest: float | None) -> list[str]:
    """The inferences about rest that stay true when the calendar is INCOMPLETE (plan F0, defect 10).

    The matches we know are those of the competitions we follow; a cup or a continental tie we do not follow is not
    there. The real rest is therefore at most the recorded one. "Short rest" holds (the real rest is shorter still);
    "X has three days less rest than Y" does not (Y's real rest may be as short as X's), so it is not claimed."""
    return [f"{side}_short_rest" for side, rest in (("home", home_rest), ("away", away_rest))
            if rest is not None and rest < SHORT_REST_DAYS]


CALENDAR_SCOPE: dict[str, Any] = {
    "scope": "tracked_competitions",
    "complete": None,
    "rest_days": "at_most",
    "matches_last_14d": "at_least",
    "next_match": "known_only",
    "note": ("Only the competitions this platform follows are certain to be in the calendar (a team's other competitions are "
             "in it only where its list was read, see home and away); a match in any other competition may be missing. So "
             "the real rest is at most rest_days, the real number of matches in 14 days is at least matches_last_14d, and "
             "a missing next_match does not mean there is none. Do not read a long rest as a fact, nor compare the two "
             "sides' rest."),
}
"""How to read the schedule block of a packet when nothing says the calendar is whole (``complete`` null in packet-v6, where
that was always the case; packet-v7 states it per side, see ``calendar_scope``)."""

CALENDAR_WHOLE_NOTE = (
    "The calendar is every competition the data provider lists for each team, read recently (home.fetched_at, "
    "away.fetched_at): rest_days, the matches in 7, 14 and 30 days and next_match count all of them, and outside_last_14d "
    "says how many of the fortnight's matches were in a competition this platform does not follow. Rest is counted from the "
    "kick-off of the previous match. A competition the provider does not list is still absent: present rest as what the "
    "calendar shows, not as a certainty.")
CALENDAR_MIXED_NOTE = (
    "Only a side whose calendar says complete: true (see home and away) has it whole: for it rest_days is exact and the "
    "matches in 14 days are all of them. For the other side the real rest is at most rest_days, the real number of matches "
    "at least the count, and a missing next_match does not mean there is none. Do not compare the two sides' rest.")


def calendar_scope(home: dict[str, Any], away: dict[str, Any]) -> dict[str, Any]:
    """How to read the schedule block of a packet (packet-v7, plan F4), from what is known of each side's calendar.

    ``home`` / ``away`` say whether the side's list was read recently and has no doubt in it (``complete``), why not
    (``reason``), when it was read (``fetched_at``) and how long before the packet (``age_hours``). The top-level words are
    the ones that hold for BOTH sides: "exact" only when both are whole; otherwise the bounds of ``CALENDAR_SCOPE``, which are
    true of an exact figure too (an exact rest is also "at most" itself)."""
    whole = bool(home.get("complete")) and bool(away.get("complete"))
    block = dict(CALENDAR_SCOPE)
    block["complete"] = whole
    block["home"], block["away"] = dict(home), dict(away)
    if whole:
        block.update(scope="provider_calendar", rest_days="exact", matches_last_14d="exact", next_match="listed",
                     note=CALENDAR_WHOLE_NOTE)
    elif home.get("complete") or away.get("complete"):
        block["note"] = CALENDAR_MIXED_NOTE
    return block


# ── what the match is worth ──────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class TableRow:
    team_id: int
    rank: int
    points: int
    played: int
    description: str | None


@dataclass(frozen=True, slots=True)
class Stakes:
    team_id: int
    rank: int
    zone: str | None
    gap_up: int | None
    """Points to the last team of the better zone (None: already in the best zone)."""
    gap_down: int | None
    """Points above the first team of the worse zone (None: no worse zone below)."""
    remaining: int | None
    max_gain: int | None
    settled: bool | None
    """No zone boundary reachable either way any more; None when the remaining games are unknown."""
    pressure: str
    """title | europe | relegation | promotion | mid_table | settled | unknown - an inference: the zone the team is in,
    or the nearest zone boundary within ``NEAR_POINTS`` that it can still reach."""
    zone_above: str | None = None
    """The kind of the nearest better zone (the one ``gap_up`` measures to)."""
    zone_below: str | None = None
    """The kind of the nearest worse zone (the one ``gap_down`` measures to)."""

    def as_json(self) -> dict[str, Any]:
        return {"rank": self.rank, "zone": self.zone, "gap_up": self.gap_up, "gap_down": self.gap_down,
                "zone_above": self.zone_above, "zone_below": self.zone_below, "remaining": self.remaining,
                "max_gain": self.max_gain, "settled": self.settled, "pressure": self.pressure, "rule": STAKES_RULE}


STAKES_RULE = "stakes-v2"
NEAR_POINTS = 6
"""stakes-v2 (13 Oct 2026): a zone boundary presses a team outside the zones when it is within two wins and still
reachable. stakes-v1 pressed on any reachable boundary: at round 10 of 38 every team of a 20-team table read as
fighting relegation - the 8th, level on points with the play-off places, too - and a narrative wrote that both
teams "were in the relegation zone"."""


def _zone_kind(description: str | None) -> str | None:
    if not description:
        return None
    d = description.lower()
    if "relegation" in d or "descenso" in d:
        return "relegation"
    if "promotion" in d and ("champions" in d or "europa" in d or "conference" in d or "libertadores" in d
                             or "sudamericana" in d or "concacaf" in d or "afc" in d):
        return "europe"
    if "champions" in d or "libertadores" in d or "title" in d or "winner" in d:
        return "title"
    if "europa" in d or "conference" in d or "sudamericana" in d:
        return "europe"
    if "promotion" in d or "play-off" in d or "playoff" in d or "qualification" in d or "next round" in d:
        return "promotion"
    return "other"


def stakes(table: Sequence[TableRow], team_id: int, remaining: int | None) -> Stakes | None:
    """The team's position against the zones of its table. A zone is a run of ranks sharing the
    provider's description; the boundary above is the last rank of the nearest better zone, the
    boundary below the first rank of the nearest worse one."""
    rows = sorted(table, key=lambda r: r.rank)
    me = next((r for r in rows if r.team_id == team_id), None)
    if me is None:
        return None
    zone = _zone_kind(me.description)
    above = [r for r in rows if r.rank < me.rank and r.description and r.description != me.description]
    below = [r for r in rows if r.rank > me.rank and r.description and r.description != me.description]
    gap_up = (above[-1].points - me.points) if above else None
    gap_down = (me.points - below[0].points) if below else None
    max_gain = None if remaining is None else 3 * max(0, remaining)
    settled: bool | None = None
    if not any(r.description for r in rows):
        # The provider gave no zones for this table: what is at stake is unknown, not settled.
        return Stakes(team_id, me.rank, None, None, None, remaining, max_gain, None, "unknown")
    if max_gain is not None:
        up_closed = gap_up is None or gap_up > max_gain
        down_closed = gap_down is None or gap_down > max_gain
        settled = up_closed and down_closed
    zone_above = _zone_kind(above[-1].description) if above else None
    zone_below = _zone_kind(below[0].description) if below else None
    if settled:
        pressure = "settled"
    elif zone in ("title", "europe", "relegation", "promotion"):
        pressure = zone
    elif max_gain is None:
        pressure = "unknown"
    else:
        near = min(max_gain, NEAR_POINTS)
        options = []  # (gap, the worse zone first on a tie, kind)
        if gap_down is not None and zone_below == "relegation" and gap_down <= near:
            options.append((gap_down, 0, "relegation"))
        if gap_up is not None and above and gap_up <= near:
            options.append((gap_up, 1, zone_above or "mid_table"))
        pressure = min(options)[2] if options else "mid_table"
    return Stakes(team_id, me.rank, zone, gap_up, gap_down, remaining, max_gain, settled, pressure, zone_above,
                  zone_below)


# ── form ─────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PastMatch:
    kickoff_at: datetime
    home_team_id: int
    away_team_id: int
    goals_home: int
    goals_away: int


def form(team_id: int, matches: Iterable[PastMatch]) -> dict[str, Any]:
    """W/D/L string (oldest first), points per game, goals for/against per game - regulation time."""
    seq: list[str] = []
    gf = ga = 0
    n = 0
    for m in sorted(matches, key=lambda x: x.kickoff_at):
        home = m.home_team_id == team_id
        f, a = (m.goals_home, m.goals_away) if home else (m.goals_away, m.goals_home)
        gf += f
        ga += a
        n += 1
        seq.append("W" if f > a else "D" if f == a else "L")
    if n == 0:
        return {"n": 0}
    points = sum(3 if r == "W" else 1 if r == "D" else 0 for r in seq)
    return {"n": n, "sequence": "".join(seq), "ppg": round(points / n, 2), "gf_pg": round(gf / n, 2),
            "ga_pg": round(ga / n, 2)}


# ── key players ──────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class PlayerSeason:
    provider_player_id: int
    name: str | None
    position: str | None
    minutes: int
    appearances: int
    goals: int
    assists: int
    rating: float | None


def importance(players: Sequence[PlayerSeason]) -> dict[int, dict[str, Any]]:
    """How much each player matters to his team this season, from his share of the team's most-used
    player's minutes and his share of the team's goals and assists. ``key`` = a regular starter
    (at least 60 % of the most-used player's minutes, among the team's eleven most-used) or a player
    with at least 20 % of the team's goal contributions. The goalkeeper with the most minutes is
    marked ``first_choice_gk``."""
    if not players:
        return {}
    top_minutes = max(p.minutes for p in players) or 1
    contributions = sum(p.goals + p.assists for p in players) or 1
    by_minutes = sorted(players, key=lambda p: -p.minutes)
    eleven = {p.provider_player_id for p in by_minutes[:11]}
    keepers = [p for p in by_minutes if (p.position or "").lower().startswith("goal")]
    first_gk = keepers[0].provider_player_id if keepers and keepers[0].minutes > 0 else None
    out: dict[int, dict[str, Any]] = {}
    for p in players:
        minutes_share = p.minutes / top_minutes
        ga_share = (p.goals + p.assists) / contributions
        key = (p.provider_player_id in eleven and minutes_share >= 0.6) or ga_share >= 0.2
        out[p.provider_player_id] = {
            "minutes": p.minutes, "minutes_share": round(minutes_share, 3), "goals": p.goals, "assists": p.assists,
            "ga_share": round(ga_share, 3), "rating": p.rating, "position": p.position,
            "key": bool(key), "first_choice_gk": p.provider_player_id == first_gk,
        }
    return out


def absence_weight(info: dict[str, Any] | None, absence_type: str | None) -> float:
    """0-1: how much a reported absence weakens a side - a first-choice goalkeeper or a key player
    out counts most, a doubtful player half. Unknown players count little, never zero."""
    certainty = 0.5 if (absence_type or "").lower().startswith("question") else 1.0
    if info is None:
        return round(0.1 * certainty, 3)
    if info.get("first_choice_gk"):
        base = 0.8
    elif info.get("key"):
        base = 0.4 + 0.4 * min(1.0, float(info.get("ga_share") or 0) / 0.3)
    else:
        base = 0.1 + 0.2 * float(info.get("minutes_share") or 0)
    return round(min(1.0, base) * certainty, 3)


# ── travel ───────────────────────────────────────────────────────────────────

def travel(venue_city: str | None, venue_country: str | None, base_city: str | None,
           base_country: str | None, *, neutral: bool) -> dict[str, Any]:
    if not venue_city and not venue_country:
        return {"known": False}
    out: dict[str, Any] = {"known": bool(base_city or base_country), "neutral_venue": neutral}
    if base_country and venue_country:
        out["international"] = base_country.strip().lower() != venue_country.strip().lower()
    if base_city and venue_city:
        out["same_city"] = base_city.strip().lower() == venue_city.strip().lower()
    return out


# ── market ───────────────────────────────────────────────────────────────────

def movement(opening: float | None, current: float | None) -> float | None:
    if opening is None or current is None:
        return None
    return round(current - opening, 4)


def interval_z(edge: float, p_lo: float | None, p_hi: float | None) -> float | None:
    """The edge in units of the model's own uncertainty (a 90 % interval spans about 3.29 sigma)."""
    if p_lo is None or p_hi is None or p_hi <= p_lo:
        return None
    sigma = (p_hi - p_lo) / 3.29
    return round(edge / sigma, 3) if sigma > 0 else None


def normal_cdf(z: float) -> float:
    return 0.5 * (1.0 + math.erf(z / math.sqrt(2.0)))
