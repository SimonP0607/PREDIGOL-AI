"""SCENARIOS OF A MATCH - ``scenarios-v1`` (plan F6): what THIS match alone can do to a table or to a tie, said as arithmetic.

A reader of a match asks "what does it change?": a win moves a side from the fifth place to the third, a draw keeps the second leg
open, the home side can lose by one goal and still go through. The packet used to carry the pieces (the table row, the stakes, the
first leg) and leave the sums to the reader, so the brief either skipped the question or did the sum in prose - and a sum in prose is
where a language model is least reliable. This module does the sums, once, from the numbers the packet already carries, and writes the
result as figures a claim can cite (``P:scenarios``).

TABLE. ``table_effect`` takes the table of the match's own stage as it stood at the packet's moment and, for each of the three results,
what the two sides have afterwards: their points and the best and the worst place they can hold. EVERY OTHER TEAM KEEPS ITS CURRENT
POINTS - the other matches of the round are not simulated and nobody is told they are - so a place is an interval, not a number: the
best place counts only the teams with MORE points, the worst one counts the teams with as many (a tie is settled by a tiebreak the
table does not carry). The zone is the provider's own description of the rows at those places (a title place, a continental place, a
relegation place). A table the provider did not order by points (a deduction not in the points, a ranking by points per game, two
tables mixed) is not read: the block says so instead of a plausible interval.

TIE. ``tie_reading`` takes the tie as it could be seen before the match (``fbi.competitions.context.TieAsOf``) and, for the second leg
of a two-legged tie, says for each side the margin - its goals minus the other side's in THIS match, in 90 minutes - with which it is
ahead on aggregate, level, or behind: the home side that leads by two "can lose by one goal and still be ahead". What happens when
the aggregate is level is the competition's rule (extra time, penalties, an away-goals rule) and the block says ``competition_rules``:
it is not assumed. The other kinds (a single match, a first leg, a replay, a series) are passed through as they are.

These are readings of the arithmetic, not probabilities: no model is asked and nothing here says which result is likely. They live
outside the model packages and no model reads them (``tests/unit/test_context_isolation.py``). Pure.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime
from typing import Any, Final

from fbi.ai.context import TableRow, zone_kind
from fbi.competitions.context import TieAsOf

VERSION: Final = "scenarios-v1"

NOTE: Final = (
    "Lecturas aritméticas de ESTE partido solo: los demás partidos no se simulan (cada equipo conserva sus puntos actuales, así que "
    "un puesto es un intervalo) y no son probabilidades. Si la eliminatoria queda igualada, decide el reglamento de la competición.")

RESULTS: Final = (("home_win", 3, 0), ("draw", 1, 1), ("away_win", 0, 3))
"""The three results of the match and the points each side takes from it (home, away)."""

TABLE_UNAVAILABLE: Final = "rank_not_by_points"
"""The reason a table is not read: its ranks are not the order of its points."""


def _best_worst(points: int, others: Sequence[int]) -> tuple[int, int]:
    """The best and the worst place of a side with ``points`` among teams with ``others`` points: ties go either way."""
    return 1 + sum(1 for q in others if q > points), 1 + sum(1 for q in others if q >= points)


def _zones(zone_at: dict[int, str | None], best: int, worst: int) -> list[dict[str, str | None]]:
    """The zones the places best..worst belong to, in order, without repeats: the provider's description and its kind."""
    seen: list[str | None] = []
    for rank in range(best, worst + 1):
        d = zone_at.get(rank)
        if d not in seen:
            seen.append(d)
    return [{"description": d, "kind": zone_kind(d) if d else None} for d in seen]


def table_effect(table: Sequence[TableRow], home: int, away: int, *, snapshot_at: datetime | None = None,
                 group: str | None = None) -> dict[str, Any] | None:
    """What the match alone does to the table: for each result, the points and the interval of places of both sides.

    ``table`` is one group of the table of the match's own stage; ``home`` and ``away`` are the team ids. None when either side is
    not in it. A table whose ranks are not the order of its points (the places now are not inside the intervals the points give)
    comes back as ``{"unavailable": "rank_not_by_points"}``."""
    rows = {r.team_id: r for r in table}
    if home == away or home not in rows or away not in rows:
        return None
    zone_at: dict[int, str | None] = {r.rank: r.description for r in table}
    others_now = [r.points for r in table if r.team_id not in (home, away)]
    for me, other in ((rows[home], rows[away]), (rows[away], rows[home])):
        best, worst = _best_worst(me.points, [*others_now, other.points])
        if not best <= me.rank <= worst:
            return {"version": VERSION, "unavailable": TABLE_UNAVAILABLE, "group": group,
                    "snapshot_at": None if snapshot_at is None else snapshot_at.isoformat()}

    def side(r: TableRow) -> dict[str, Any]:
        return {"team_id": r.team_id, "rank_now": r.rank, "points_now": r.points, "played": r.played, "zone_now": r.description}

    out: dict[str, Any] = {
        "version": VERSION, "basis": "this_match_alone", "group": group,
        "snapshot_at": None if snapshot_at is None else snapshot_at.isoformat(), "teams": len(table),
        "home": side(rows[home]), "away": side(rows[away]), "after": {},
    }
    for result, dh, da in RESULTS:
        hp, ap = rows[home].points + dh, rows[away].points + da
        entry: dict[str, Any] = {}
        for key, points, versus in (("home", hp, ap), ("away", ap, hp)):
            best, worst = _best_worst(points, [*others_now, versus])
            entry[key] = {"points": points, "rank_best": best, "rank_worst": worst,
                          "zones": _zones(zone_at, best, worst)}
        out["after"][result] = entry
    return out


def tie_reading(tie: TieAsOf | None) -> dict[str, Any] | None:
    """What the match does to the tie it is a leg of, as it could be seen before it. None when it is not a leg of a tie."""
    if tie is None:
        return None
    outlook = dict(tie.outlook)
    kind = str(outlook.get("kind"))
    if kind != "second_leg":
        return {"version": VERSION, "kind": kind, **{k: v for k, v in outlook.items() if k != "kind"}}
    if tie.aggregate is None:
        return {"version": VERSION, "kind": kind, "aggregate": "unknown",
                "note": "falta el resultado de la ida: no se puede decir qué hace este partido a la eliminatoria"}
    home_goals, away_goals = tie.aggregate
    lead = home_goals - away_goals  # of this match's home side, before the match
    return {
        "version": VERSION, "kind": kind,
        "aggregate_before": {"home_side": home_goals, "away_side": away_goals}, "lead_home_side": lead,
        "margin": "goles del equipo menos goles del rival en ESTE partido, en 90 minutos",
        "home_side": {
            "ahead_if_margin_at_least": 1 - lead, "level_if_margin": -lead, "behind_if_margin_at_most": -lead - 1,
            "can_lose_by_up_to": lead - 1 if lead >= 1 else None, "needs_to_win_by_at_least": 1 - lead if lead <= 0 else None},
        "away_side": {
            "ahead_if_margin_at_least": lead + 1, "level_if_margin": lead, "behind_if_margin_at_most": lead - 1,
            "can_lose_by_up_to": -lead - 1 if lead <= -1 else None, "needs_to_win_by_at_least": lead + 1 if lead >= 0 else None},
        "if_level": "competition_rules",
    }


def scenarios_block(table: dict[str, Any] | None, tie: dict[str, Any] | None, *, status: str = "DESCRIPTIVE"
                    ) -> dict[str, Any] | None:
    """The block of the packet (``content["scenarios"]``), or None when there is nothing to say (no table of the match's own
    stage and no tie)."""
    if table is None and tie is None:
        return None
    return {"version": VERSION, "status": status, "table": table, "tie": tie, "note": NOTE}
