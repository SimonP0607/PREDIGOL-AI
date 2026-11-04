"""WHAT A PASS OF THE FAMILIES WOULD DO, said before the switch is on (plan F11): the pass run as a dry run and put into words.

WHY. ``FBI_FAMILY_DECISIONS`` is ``off`` until the owner turns it to ``shadow``, and from then on the worker writes rows once an hour. The owner should
not have to throw the switch to learn what those rows will look like. A dry run (``fbi.familydecisions.decide.decide_families`` with ``write=False``)
reads exactly what the pass reads - the last forecast of every selection, the prices the books had quoted by the moment, the world the decision layer
judges in - and judges exactly as it judges; it writes nothing, spends nothing and asks nobody. This module gives its result a shape a person can
read: the funnel from forecasts to rows, what the decisions are, what each lacked and what finding it out would cost if anyone served the request.

WHAT IT SAYS.

* The FUNNEL: forecasts read -> selections with a price -> candidates (the value the plan's criterion asks, at the best price, behind enough complete
  books) -> decisions judged -> rows the pass would write (what is already written is not written again). The funnel is also the diagnosis of an empty
  pass: it says at which step the selections ran out.
* The DECISIONS: per family, state and reason, and one line for each selection - the match, what the model said, what the books said, the price, the
  value the model sees, the state, why, and what the decision did not know.
* What the decisions LACK, added up the way the cost would add up (``lacking``): how many lack each need (``fbi.familydecisions.research``) and how many
  searches finding it out would take if anyone served the request - the levels of the searches of one match are united, not added, because a search of
  a level serves every selection of the match.

WHAT IT IS NOT. It is not a forecast, a price or a pick, and it is not a promise: a later pass sees later prices and reads later forecasts. It reads
the rows of ``intel.decisions`` of the families only to know what is already written (``decision.should_write``). Pure: it reads nothing and writes
nothing (the reading is the pass's, the command line's job is to open a connection that cannot write: ``scripts.families decide``).
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Mapping, Sequence
from datetime import datetime, timedelta
from typing import Any, Final

from fbi.familydecisions import research
from fbi.familydecisions.decide import SWITCH, VERSION, FamilyReport
from fbi.intel.decision import Evaluated

DEFAULT_TOP: Final = 20
"""The decisions the text lists (the JSON carries all of them)."""

MODE_SAYS: Final[Mapping[str, str]] = {
    "off": "the worker runs no pass; set to 'shadow' it runs one an hour and writes rows like these",
    "shadow": "the worker runs one pass an hour and writes rows like these",
}
"""What the switch means in each of its positions (a test holds the keys equal to ``decide.MODES``)."""


def _record(e: Evaluated, key: str) -> Mapping[str, Any] | None:
    """The record of a filter among the decision's filters (None: the decision has none of that key)."""
    for f in e.filters:
        if f.get("key") == key:
            return f
    return None


def _data(record: Mapping[str, Any] | None) -> Mapping[str, Any]:
    found = None if record is None else record.get("data")
    return found if isinstance(found, Mapping) else {}


def _float(x: Any) -> float | None:
    return None if x is None else float(x)


def line_of(e: Evaluated) -> dict[str, Any]:
    """A decision of the pass as the preview says it: the match, the selection, what the model and the books said, the state and why, and what the
    decision did not know (the request for research it carries; None when the pass could not read the referees and wrote none)."""
    r = e.row
    family = _record(e, "family")
    asked = _record(e, research.KEY)
    ask = _data(asked)
    failed = [{"filter": f["key"], "why": f.get("why"), "effect": f.get("effect")} for f in e.filters if f.get("ok") is False]
    return {
        "fixture_id": e.key[0], "kickoff_at": r["kickoff_at"].isoformat(), "competition": r.get("competition_name"),
        "home": r.get("home_name"), "away": r.get("away_name"), "family": _data(family).get("family"), "model": r.get("model_used"),
        "market": e.key[1], "selection": e.key[2], "line": float(e.key[3]),
        "p_model": _float(r.get("p_model")), "p_market": _float(r.get("p_fair")), "odds": _float(r.get("best_odds")), "books": r.get("n_bookmakers"),
        "value": _float(_data(family).get("believed", e.ev_raw)),
        "state": e.state, "reasons": list(e.reasons), "failed": failed, "score": None if e.score is None else e.score.total,
        "stake": e.stake.units, "context": e.context.status,
        "research": None if asked is None else {
            "open": list(ask.get("open", [])), "levels": list(ask.get("levels", [])), "searches": int(ask.get("searches", 0)),
            "served": bool(ask.get("served", False)), "said": asked.get("why")},
    }


def lacking(lines: Sequence[Mapping[str, Any]]) -> dict[str, Any]:
    """What the decisions would want to know, added up: how many lack each need, how many were asked about at all, and how many searches finding
    it out would take if anyone served the requests. A search of a level serves every selection of a match, so the levels of a match's decisions are
    united: three selections of one match are one set of searches, not three."""
    asked = [x["research"] for x in lines if x.get("research") is not None]
    needs = Counter(need for r in asked for need in r["open"])
    levels: dict[int, set[int]] = defaultdict(set)
    for x in lines:
        if x.get("research") is not None:
            levels[int(x["fixture_id"])].update(x["research"]["levels"])
    return {"asked": len(asked), "needs": dict(sorted(needs.items())), "matches": sum(1 for v in levels.values() if v),
            "searches": sum(len(v) for v in levels.values())}


def summarise(report: FamilyReport, evaluated: Sequence[Evaluated], *, at: datetime, horizon: timedelta, mode: str) -> dict[str, Any]:
    """The preview of a dry run: the funnel and the counts of the report, what the decisions lack and the decisions themselves, the ones the model sees
    most value in first (then by match, so that the same pass reads the same)."""
    lines = sorted((line_of(e) for e in evaluated),
                   key=lambda x: (-(x["value"] if x["value"] is not None else float("-inf")), x["fixture_id"], x["market"], x["line"], x["selection"]))
    return {"version": VERSION, "at": at.isoformat(), "horizon_hours": horizon.total_seconds() / 3600, "mode": mode,
            "report": {**report.as_dict(), "would_write": report.would_write}, "lacking": lacking(lines), "decisions": lines}


def _counts(counts: Mapping[str, int]) -> str:
    return ", ".join(f"{k} {v}" for k, v in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0]))) or "none"


def _percent(x: float | None) -> str:
    return "?" if x is None else f"{x * 100:.1f} %"


def _price(x: float | None) -> str:
    return "?" if x is None else f"{x:.2f}"


def _value(x: float | None) -> str:
    return "?" if x is None else f"{x:+.1%}"


def _empty(report: Mapping[str, Any]) -> str | None:
    """Why a pass that decided nothing decided nothing: the first step of the funnel that ran dry."""
    if report["forecasts"] == 0:
        return "nothing to decide: the families have stated no forecast for a match that kicks off in the window"
    if report["priced"] == 0:
        return "nothing to decide: no selection that was forecast has a price from complete books by that moment"
    if report["candidates"] == 0:
        return "nothing to decide: no priced selection shows the value the plan's criterion asks (at the best price, behind enough complete books)"
    if report["evaluated"] == 0:
        return "nothing was judged: every candidate failed (see the errors)"
    return None


def render(summary: Mapping[str, Any], *, top: int = DEFAULT_TOP) -> str:
    """The preview as text: the funnel, the counts, what the decisions lack and the ``top`` decisions the model sees most value in."""
    rep, lack = summary["report"], summary["lacking"]
    mode = summary["mode"]
    out = [f"decisions of the families, dry run: what a pass would do at {summary['at'][:16].replace('T', ' ')} UTC over the next "
           f"{summary['horizon_hours']:g} h under {summary['version']} - it reads, it writes nothing, it asks nobody",
           f"  {SWITCH} is {mode}: {MODE_SAYS.get(mode, 'unknown')}",
           f"  funnel: {rep['forecasts']} forecasts of {rep['fixtures']} matches -> {rep['priced']} priced selections -> {rep['candidates']} candidates -> "
           f"{rep['evaluated']} judged ({rep['failed']} failed) -> {rep['would_write']} rows to write (what is already written is not written again)"]
    why = _empty(rep)
    if why:
        out.append(f"  {why}")
    if rep["evaluated"]:
        out.append(f"  by family: {_counts(rep['by_family'])}")
        out.append(f"  by state: {_counts(rep['by_state'])} (a family never goes above INVESTIGACION: that is the owner's to give)")
        out.append(f"  by reason: {_counts(rep['by_reason'])}")
    if lack["asked"]:
        needs = _counts(lack["needs"])
        out.append(f"  what they lack (the request for research each carries; nothing serves it): {needs} of {lack['asked']} decisions; "
                   f"{lack['searches']} searches in {lack['matches']} matches if anyone served them")
    elif rep["evaluated"]:
        out.append("  what they lack: not said - the referees could not be read, so the decisions carry no request for research")
    for error in rep["errors"]:
        out.append(f"  error: {error}")
    shown = summary["decisions"][:max(top, 0)]
    for x in shown:
        when = x["kickoff_at"][5:16].replace("T", " ")
        out.append(f"  {when} {x['home']} - {x['away']} ({x['competition']}) {x['market']} {x['selection']} {x['line']:g} [{x['family']}]: model "
                   f"{_percent(x['p_model'])}, books {_percent(x['p_market'])} ({x['books']}), best price {_price(x['odds'])}, value {_value(x['value'])} "
                   f"-> {x['state']} ({', '.join(x['reasons'])}); stake {x['stake']:g}; context {x['context']}")
        for f in x["failed"]:
            if f["effect"] == "RECHAZADO" and f["filter"] != "final":  # the last filter adds up the others
                out.append(f"      rejected by {f['filter']}: {f['why']}")
        if x["research"] is not None:
            out.append(f"      {x['research']['said']}")
    if len(summary["decisions"]) > len(shown):
        out.append(f"  ... and {len(summary['decisions']) - len(shown)} more (--top, or --json for all of them)")
    return "\n".join(out)
