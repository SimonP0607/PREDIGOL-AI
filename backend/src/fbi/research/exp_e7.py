"""EXP-E7 of the plan (RP-9.7): how much do goals, corners and cards of one match depend on each other? A DESCRIPTIVE experiment.

The protocol is ``fbi.research.exp_protocol.E7`` (registered and fingerprinted on 2026-11-26). The meter already existed and is kept unchanged
(``fbi.families.dependence``: the lift of every combination of two events of two different families, inside strata of competition and half-year, with an interval
from a bootstrap of competition-days). What this module adds is the FORMAL RUN of the plan: the table over the whole history, the same table over each half of it
(the first half in time and the second), and a mark of STABILITY for each pair - the verdict of the pair and the side the lift lies on are the same in both halves.

There is no prospective sample (the plan says so): the experiment is due once the history has the matches the meter needs, and a verdict on the current protocol is
final. It is descriptive, so its verdict is «success» only in the sense that the table was measured with an interval for the pairs of every family pair named in the
protocol (goals-corners, goals-cards, corners-cards); it never abandons. A «success» of a descriptive experiment promotes nothing and proposes nothing
(``fbi.proposals.from_verdicts`` skips ``DESCRIPTIVE``): the table is the base of RP-11.2 and nothing reads it to price, stake or publish. 0 provider requests, 0 AI.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from datetime import UTC, date, datetime
from typing import Any, Final

import psycopg

from fbi.families import dependence, history
from fbi.research import exp_conditions, exp_protocol
from fbi.research.exp_protocol import Judgement

KEY: Final = "EXP-E7"
SINCE: Final = datetime(2020, 1, 1, tzinfo=UTC)
FAMILY_PAIRS: Final = tuple(exp_protocol.E7.segments)
"""goles-córneres, goles-tarjetas, córneres-tarjetas."""
NAMES: Final = {"goals": "goles", "corners": "córneres", "cards": "tarjetas"}
REQUIRED: Final = dependence.MIN_MATCHES
"""The matches the meter needs to say anything (it returns an empty table below it)."""
TOP: Final = 12


def family_pair(first: str, second: str) -> str:
    """The family pair of the protocol an event pair belongs to (the events are named ``family.kind``)."""
    a, b = (NAMES[first.split(".")[0]], NAMES[second.split(".")[0]])
    name = f"{a}-{b}"
    return name if name in FAMILY_PAIRS else f"{b}-{a}"


def worst_cell(pair: Mapping[str, Any]) -> tuple[str, Mapping[str, Any]] | None:
    """The combination of the pair whose lift lies farthest from 1 (the one that matters most to a parlay), with its name."""
    cells = [(name, c) for name, c in pair["cells"].items() if c["lift"] is not None and c["low"] is not None and c["high"] is not None]
    return max(cells, key=lambda x: abs(float(x[1]["lift"]) - 1.0)) if cells else None


def side(lift: float | None) -> int:
    return 0 if lift is None else (1 if lift > 1.0 else -1 if lift < 1.0 else 0)


def excludes_one(cell: Mapping[str, Any]) -> int:
    """The side of 1 a combination's whole interval lies on (1 above, -1 below), or 0 when the interval holds 1 or the cell has none."""
    low, high = cell.get("low"), cell.get("high")
    if low is None or high is None:
        return 0
    return 1 if float(low) > 1.0 else -1 if float(high) < 1.0 else 0


def stability(whole: Mapping[str, Any], first: Mapping[str, Any], second: Mapping[str, Any]) -> dict[str, bool]:
    """For each event pair, whether it is STABLE across the two halves of the history. A pair that is negligible as a whole is stable when it is negligible in both
    halves. Any other pair is stable when its WORST combination (the one whose lift lies farthest from 1) has, in each half, an interval that excludes 1 on the
    side where the whole one lies: the same dependence, the same direction, each time with its own interval (a point estimate on the same side is what half the
    pairs have by chance)."""
    a = {(p["first"], p["second"]): p for p in first["pairs"]}
    b = {(p["first"], p["second"]): p for p in second["pairs"]}
    out: dict[str, bool] = {}
    for p in whole["pairs"]:
        k = (p["first"], p["second"])
        in_first, in_second = a.get(k), b.get(k)
        name = f"{k[0]} | {k[1]}"
        if in_first is None or in_second is None:
            out[name] = False
            continue
        halves = (in_first, in_second)
        if p["verdict"] == dependence.NEGLIGIBLE:
            out[name] = all(h["verdict"] == dependence.NEGLIGIBLE for h in halves)
        else:
            worst = worst_cell(p)
            if worst is None:
                out[name] = False
                continue
            wanted = side(worst[1]["lift"])
            out[name] = all(excludes_one(h["cells"][worst[0]]) == wanted != 0 for h in halves)
    return out


def split(rows: Sequence[dependence.Row]) -> tuple[list[dependence.Row], list[dependence.Row]]:
    """The matches in time order cut in two halves with the same number of matches."""
    ordered = sorted(rows, key=lambda r: (r.kickoff_at, r.fixture_id))
    cut = len(ordered) // 2
    return ordered[:cut], ordered[cut:]


def table(rows: Sequence[dependence.Row], *, replicates: int = dependence.REPLICATES) -> tuple[Judgement, dict[str, Any]]:
    """The table over the rows, its two halves and the stability of each pair; the judgement says only that it was measured."""
    whole = dependence.measure(rows, replicates=replicates)
    if not whole["pairs"]:
        return (Judgement("insuficiente", f"muestra {len(rows)} de {REQUIRED}: el medidor no devuelve tabla", float("nan"), float("nan"), float("nan"), len(rows)),
                {"matches": len(rows)})
    first_rows, second_rows = split(rows)
    first, second = dependence.measure(first_rows, replicates=replicates), dependence.measure(second_rows, replicates=replicates)
    stable = stability(whole, first, second)
    by_family: dict[str, Counter[str]] = {p: Counter() for p in FAMILY_PAIRS}
    listed: list[dict[str, Any]] = []
    for pair in whole["pairs"]:
        name = family_pair(pair["first"], pair["second"])
        mark = stable[f"{pair['first']} | {pair['second']}"]
        by_family[name][pair["verdict"]] += 1
        by_family[name]["stable"] += int(mark)
        worst = worst_cell(pair)
        if worst is not None:
            listed.append({"family_pair": name, "first": pair["first"], "second": pair["second"], "verdict": pair["verdict"], "stable": mark, "cell": worst[0],
                           "lift": worst[1]["lift"], "low": worst[1]["low"], "high": worst[1]["high"]})
    listed.sort(key=lambda x: -abs(float(x["lift"]) - 1.0))
    covered = [p for p in FAMILY_PAIRS if sum(by_family[p][v] for v in (dependence.NEGLIGIBLE, dependence.BORDERLINE, dependence.MATERIAL)) > 0]
    population = {"matches": whole["data"]["matches"], "strata": whole["data"]["strata"], "halves": [first["data"]["matches"], second["data"]["matches"]],
                  "family_pairs": {p: dict(c) for p, c in by_family.items()}, "top": listed[:TOP], "summary": whole["summary"], "meter": dependence.VERSION}
    if not listed or set(covered) != set(FAMILY_PAIRS):
        return (Judgement("insuficiente", "la tabla no cubre los tres pares de familias del protocolo", float("nan"), float("nan"), float("nan"), len(rows)),
                population)
    top = listed[0]
    stable_n = sum(1 for v in stable.values() if v)
    return (Judgement("exito", f"tabla medida: {whole['summary']['pairs']} pares de sucesos con intervalo, {whole['summary'][dependence.MATERIAL]} materiales, {stable_n} estables "
                               "(descriptivo: no promueve nada)", float(top["lift"]), float(top["low"]), float(top["high"]), len(rows)), population)


def count(conn: psycopg.Connection[Any], since: date) -> int:
    """The matches the meter can read: finished matches of the followed competitions with goals and corners known (a light count; the cards are checked by the run)."""
    where = f"o.is_tracked AND {history.complete_condition('goals_ft')} AND {history.complete_condition('corners_ft')}"
    row = conn.execute(f"SELECT count(*) FROM market.fixture_outcomes o WHERE {where}").fetchone()
    return 0 if row is None else int(row[0])


def run(conn: psycopg.Connection[Any], at: datetime) -> tuple[Judgement, dict[str, Any]]:
    rows, coverage = dependence.join(dependence.read(conn, since=SINCE, cutoff=at))
    judgement, population = table(rows)
    population["coverage"] = coverage
    return judgement, population


def register() -> exp_conditions.Spec:
    """Say how the experiment counts and runs (``scripts.exp_run`` calls it for each module of its ``PLUGINS``)."""
    return exp_conditions.register(KEY, count=count, required=REQUIRED, run=run)


__all__ = ["KEY", "REQUIRED", "count", "family_pair", "register", "run", "split", "stability", "table", "worst_cell"]
