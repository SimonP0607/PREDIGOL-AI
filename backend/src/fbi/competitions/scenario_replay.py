"""The closing test of the scenarios engine (plan 2026, AD-B02, IA-082): a closed season replayed day by day, and every claim the engine
proved on the way held against what happened.

For each day on which the season's matches were played, the season is cut at the end of that day (the results of the matches that had
kicked off by then; the calendar whole), the engine reads it (certification only), and every objective it states as ``conseguido`` or
``descartado`` is checked against the team's FINAL place - the provider's last table when one has exactly the table's teams, the
regulation applied to every result otherwise. A false claim is a defect: the closing criterion is zero.

It also reports how early each objective was decided (days before the last one), whether a decided objective ever changed (it must
not), how many rows used the safe bound instead of the exact enumeration, and what is still open after the last match (a tie the
regulation leaves to lots or a play-off). Pure: the season in, the report out.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime, time, timedelta
from typing import Any, Final

from fbi.competitions import scenarios as sc
from fbi.competitions.rules import Answer, Coded

VERSION: Final = "scenarios-replay-v1"


@dataclass(frozen=True, slots=True)
class Match:
    """A match of the closed season with its final result (None when it never got one) and its kick-off."""

    fixture: sc.Fixture
    kickoff_at: datetime


def cut(matches: Sequence[Match], at: datetime) -> list[sc.Fixture]:
    """The season at ``at``: the result of every match that had kicked off by then, every other one still to play."""
    out: list[sc.Fixture] = []
    for m in matches:
        f = m.fixture
        known = f.played and m.kickoff_at < at
        out.append(sc.Fixture(f.id, f.round, f.home, f.away, f.home_goals if known else None, f.away_goals if known else None))
    return out


def _truth(reading: Mapping[str, Any], final: Mapping[str, Sequence[tuple[int, int]]], *, closed: bool
           ) -> dict[tuple[str, int], tuple[int, str]]:
    out: dict[tuple[str, int], tuple[int, str]] = {}
    sets = [frozenset(row["team"] for row in t["teams"]) for t in reading["tables"]]
    for t, members in zip(reading["tables"], sets, strict=True):
        # the provider's table of these teams - unless two tables of the season have the same teams (an Apertura and a Clausura):
        # then which final table is which cannot be told by the teams, and the regulation applied to the results is the truth
        provider = None if sets.count(members) > 1 else next(
            ((label, {team: rank for rank, team in rows}) for label, rows in final.items() if {team for _, team in rows} == members),
            None)
        if t["phantom"] or (t["pending"] and (provider is None or not closed)):
            # matches never scheduled, a season still being played, or neither the provider's final table nor every result:
            # no truth to hold the claims to
            continue
        for row in t["teams"]:
            if provider is not None:
                out[(t["key"], row["team"])] = (provider[1][row["team"]], f"proveedor:{provider[0]}")
            elif row["puesto"] is not None:
                out[(t["key"], row["team"])] = (int(row["puesto"]), "reglamento")
    return out


def replay(answer: Answer, matches: Sequence[Match], *, final: Mapping[str, Sequence[tuple[int, int]]] | None = None,
           groups: Mapping[str, Sequence[int]] | None = None, step: int = 1) -> dict[str, Any]:
    """Replay a closed season (see the module). ``final``: the provider's last tables, label -> (rank, team); ``groups``: the
    provider's groups, label -> teams (a group phase), when they are not in ``final``. ``step``: read one match day in ``step``
    (and always the last one); 1 reads them all."""
    if not isinstance(answer, Coded):
        return {"version": VERSION, "status": sc.NOT_CODED}
    hint = {label: [sc.ProviderRow(team, -1, -1) for team in teams] for label, teams in (groups or {}).items()}
    for label, rows in (final or {}).items():
        hint.setdefault(label, [sc.ProviderRow(team, -1, -1) for _, team in rows])
    last = max(m.kickoff_at for m in matches) + timedelta(days=1)
    end = sc.evaluate(answer, cut(matches, last), at=last, provider=hint, include_closed=True)
    results = [m.kickoff_at for m in matches if m.fixture.played]
    # closed: no match without a result kicks off after the last result (a match awarded without a score mid-season is not one)
    closed = not any(not m.fixture.played and results and m.kickoff_at > max(results) for m in matches)
    truth = _truth(end, final or {}, closed=closed)
    days = sorted({m.kickoff_at.astimezone(UTC).date() for m in matches})
    claims = 0
    false: list[dict[str, Any]] = []
    first: dict[tuple[str, int, str, int], int] = {}
    state: dict[tuple[str, int, str, int], str] = {}
    flips = 0
    inexact = 0
    for i, d in enumerate(days):
        if step > 1 and i % step and i != len(days) - 1:
            continue
        at = _end_of(d)
        reading = sc.evaluate(answer, cut(matches, at), at=at, provider=hint)
        for t in reading["tables"]:
            for row in t["teams"]:
                for o in row["objetivos"]:
                    key = (t["key"], int(row["team"]), str(o["objetivo"]), int(o["terminar_entre_los"]))
                    inexact += not o["exacto"]
                    before = state.get(key)
                    if before in ("conseguido", "descartado") and o["estado"] != before:
                        flips += 1
                    state[key] = o["estado"]
                    if o["estado"] == "abierto":
                        continue
                    seen = truth.get((t["key"], int(row["team"])))
                    if seen is None:
                        continue
                    claims += 1
                    holds = seen[0] <= key[3] if o["estado"] == "conseguido" else seen[0] > key[3]
                    if not holds:
                        false.append({"day": d.isoformat(), "table": t["key"], "team": key[1], "objetivo": key[2],
                                      "terminar_entre_los": key[3], "estado": o["estado"], "final": seen[0], "source": seen[1]})
                    first.setdefault(key, i)
    leads = sorted(len(days) - 1 - i for i in first.values())
    still_open = sum(1 for t in end["tables"] if not t["pending"] and not t["phantom"] for row in t["teams"] for o in row["objetivos"]
                     if o["estado"] == "abierto")
    return {"version": VERSION, "engine": sc.VERSION, "status": "ok", "league_id": answer.league_id, "season": answer.season,
            "days": len(days), "step": step, "season_closed": closed, "tables": sorted({k[0] for k in truth}), "teams": len({k[1] for k in truth}),
            "sources": sorted({v[1] for v in truth.values()}), "claims_checked": claims, "false_claims": len(false),
            "examples": false[:10], "objectives_decided": len(first),
            "days_before_end_median": leads[len(leads) // 2] if leads else None, "flips": flips, "inexact_rows": inexact,
            "open_after_last_match": still_open, "skipped": [s["reason"] for s in end["skipped"]]}


def _end_of(d: date) -> datetime:
    return datetime.combine(d + timedelta(days=1), time(0), tzinfo=UTC)
