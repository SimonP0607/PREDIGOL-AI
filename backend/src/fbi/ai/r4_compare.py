"""The review of production (``review-v2``, engine ``llm``) beside the Council of the shadow (IA-029, R4 of the audit of 10 Nov 2026).

Two pieces of the same question are paid for twice: ``llm`` reviews the selections of production with ``review-v2`` (and ``brief-v8`` writes its
reading), and the shadow judges the same selections with the Council (``ma-v1`` with the Match Agent and Sonnet, ``ma-v1-h`` with the Match Agent
and Haiku, ``cs-v1`` with the Council alone). This module says, on the selections two engines both reviewed before the kick-off, how often they
agree, where they do not, what the selections they disagreed on did after the match (the outcome at a flat stake of 1 and the CLV), what each
engine's kept and rejected selections did, and what each engine cost. Every rate carries its cases and its 95 % interval (``fbi.ai.intervals``).

It INFORMS and decides nothing (``"decides": False``): it names no threshold, retires nothing (``review-v2`` and ``brief-v8`` stay until the
conditions of P2), changes no routing (which model the Council escalates to is the owner's), and a sample this small says what it says with its
interval, never more. Pure: no database, no clock (the readers are ``fbi.ai.r4_readers``)."""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Final

from fbi.ai.intervals import Proportion
from fbi.picks.settlement import Status, market_outcome, profit

R4_VERSION: Final = "r4-compare-v1"
PRODUCTION: Final[tuple[str, ...]] = ("llm", "rules")
"""The engines of production compared: the model's review (``review-v2``) and the rules it is set against."""
SHADOW: Final[tuple[str, ...]] = ("ma-v1", "ma-v1-h", "cs-v1")
ENGINES: Final[tuple[str, ...]] = (*PRODUCTION, *SHADOW)
PAIRS: Final[tuple[tuple[str, str], ...]] = (("llm", "ma-v1"), ("llm", "ma-v1-h"), ("llm", "cs-v1"), ("ma-v1", "ma-v1-h"), ("rules", "llm"))
"""The comparisons the report makes: review-v2 against each arm of the Council, the two judges of the Council against each other, and the rules
against review-v2."""
KEPT_STATUSES: Final = frozenset({"ok", "fallback"})
"""The reviews that stand for a judgement: a review that failed, came back invalid or was over the budget judged nothing."""
REJECT: Final = "REJECT"
SETTLED: Final = frozenset(s.value for s in Status if s != Status.PENDING)
WON: Final = frozenset({Status.WIN.value, Status.HALF_WIN.value})
LOST: Final = frozenset({Status.LOSS.value, Status.HALF_LOSS.value})

Key = tuple[int, str, str, str]
"""A selection: the fixture, the market, the selection and the line (as a normalised decimal string)."""


@dataclass(frozen=True, slots=True)
class Review:
    """One review of one selection by one engine, with what happened after (when the match is settled)."""

    id: int
    engine: str
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    decision: str
    status: str
    reviewed_at: datetime
    kickoff_at: datetime
    odds: Decimal | None = None
    model: str | None = None
    cost_usd: Decimal | None = None
    outcome: str | None = None
    """The settlement at the regulation score (``fbi.picks.settlement``), None while the match is not settled or the market is not one it knows."""
    profit: float | None = None
    """At a flat stake of 1, at the odds of the review."""
    clv: float | None = None
    """``odds * p_close - 1``: the price of the review against the closing fair probability (Shin consensus before the kick-off)."""

    @property
    def key(self) -> Key:
        return (self.fixture_id, self.market_key, self.selection, _line(self.line))

    @property
    def pre_match(self) -> bool:
        return self.reviewed_at < self.kickoff_at

    @property
    def settled(self) -> bool:
        return self.outcome in SETTLED


def _line(line: Decimal) -> str:
    return str(line.normalize()) if line != 0 else "0"


def _dec(value: Any) -> Decimal | None:
    if value is None:
        return None
    try:
        return Decimal(str(value))
    except InvalidOperation:
        return None


def settle(market_key: str, selection: str, line: Decimal, home: int | None, away: int | None, odds: Decimal | None) -> tuple[str | None, float | None]:
    """The outcome and the profit at a flat stake of 1, or (None, None) when there is no score, no price, or a market the settlement does not know."""
    if home is None or away is None or odds is None:
        return None, None
    try:
        status = market_outcome(market_key, selection, line, int(home), int(away))
    except ValueError:
        return None, None
    if status == Status.PENDING:
        return None, None
    return status.value, float(profit(status, odds, Decimal(1)))


def clv_of(odds: Decimal | None, p_close: Decimal | None) -> float | None:
    if odds is None or p_close is None:
        return None
    return float(odds) * float(p_close) - 1


def review_of(row: Mapping[str, Any]) -> Review:
    """A row of ``fbi.ai.r4_readers`` (the review, the kick-off, the regulation score when there is one, the closing fair probability) as a ``Review``."""
    line = _dec(row["line"]) or Decimal(0)
    odds = _dec(row.get("odds"))
    outcome, prof = settle(str(row["market_key"]), str(row["selection"]), line, row.get("reg_goals_home"), row.get("reg_goals_away"), odds)
    return Review(int(row["id"]), str(row["engine"]), int(row["fixture_id"]), str(row["market_key"]), str(row["selection"]), line,
                  str(row["decision"]), str(row["status"]), row["reviewed_at"], row["kickoff_at"], odds, row.get("model"), _dec(row.get("cost_usd")),
                  outcome, prof, clv_of(odds, _dec(row.get("p_close"))))


def newest(reviews: Iterable[Review]) -> dict[str, dict[Key, Review]]:
    """For each engine, the newest review of each selection made BEFORE the kick-off and that judged something (``KEPT_STATUSES``); a tie in time
    goes to the later row. A review made after the kick-off is never the one compared."""
    out: dict[str, dict[Key, Review]] = defaultdict(dict)
    for r in reviews:
        if not r.pre_match or r.status not in KEPT_STATUSES:
            continue
        old = out[r.engine].get(r.key)
        if old is None or (r.reviewed_at, r.id) > (old.reviewed_at, old.id):
            out[r.engine][r.key] = r
    return dict(out)


def _money(rows: Sequence[Review]) -> dict[str, Any]:
    """What a set of selections did after the match: how many settled, won and lost, the profit and the ROI at a flat stake, the mean CLV and how
    many had a positive one - each rate with its interval."""
    settled = [r for r in rows if r.settled]
    won = sum(1 for r in settled if r.outcome in WON)
    lost = sum(1 for r in settled if r.outcome in LOST)
    gain = sum(r.profit or 0.0 for r in settled)
    clvs = [r.clv for r in rows if r.clv is not None]
    return {"selections": len(rows), "settled": len(settled), "won": won, "lost": lost,
            "won_of_decided": Proportion(won, won + lost).as_json(),
            "profit_flat_stake": round(gain, 2), "roi_pct": None if not settled else round(100 * gain / len(settled), 1),
            "with_clv": len(clvs), "mean_clv_pct": None if not clvs else round(100 * sum(clvs) / len(clvs), 2),
            "positive_clv": Proportion(sum(1 for c in clvs if c > 0), len(clvs)).as_json()}


def agreement(by: Mapping[str, Mapping[Key, Review]], a: str, b: str) -> dict[str, Any]:
    """Two engines on the selections both judged: the matrix of their decisions, how often they agree (with its interval), and the selections where
    one rejects and the other does not - read at the price of the one that KEPT it (what following it would have done)."""
    left, right = by.get(a, {}), by.get(b, {})
    common = sorted(set(left) & set(right))
    matrix = Counter((left[k].decision, right[k].decision) for k in common)
    agree = sum(n for (x, y), n in matrix.items() if x == y)
    same_reject = sum(1 for k in common if (left[k].decision == REJECT) == (right[k].decision == REJECT))
    kept_by: dict[str, list[Review]] = {f"{a}_rejects": [], f"{b}_rejects": []}
    for k in common:
        x, y = left[k].decision == REJECT, right[k].decision == REJECT
        if x and not y:
            kept_by[f"{a}_rejects"].append(right[k])
        elif y and not x:
            kept_by[f"{b}_rejects"].append(left[k])
    return {"engines": [a, b], "common": len(common), "only": {a: len(set(left) - set(right)), b: len(set(right) - set(left))},
            "agree": Proportion(agree, len(common)).as_json(), "agree_on_reject_or_not": Proportion(same_reject, len(common)).as_json(),
            "matrix": {f"{x}|{y}": n for (x, y), n in sorted(matrix.items())},
            "disagreements_on_reject": {tag: _money(rows) for tag, rows in kept_by.items()}}


def kept_and_rejected(rows: Iterable[Review]) -> dict[str, Any]:
    """One engine's selections it kept (any decision but REJECT) and the ones it rejected, and what each did after the match."""
    kept: list[Review] = []
    rejected: list[Review] = []
    for r in rows:
        (rejected if r.decision == REJECT else kept).append(r)
    return {"kept": _money(kept), "rejected": _money(rejected)}


def engine_summary(engine: str, rows: Mapping[Key, Review]) -> dict[str, Any]:
    reviews = list(rows.values())
    cost = sum((r.cost_usd or Decimal(0) for r in reviews), Decimal(0))
    rejected = sum(1 for r in reviews if r.decision == REJECT)
    return {"engine": engine, "selections": len(reviews), "decisions": dict(sorted(Counter(r.decision for r in reviews).items())),
            "reject_rate": Proportion(rejected, len(reviews)).as_json(),
            "models": dict(sorted(Counter(r.model or "-" for r in reviews).items())),
            "cost_usd_of_the_compared_reviews": str(cost.quantize(Decimal("0.01"))),
            "fixtures": len({r.fixture_id for r in reviews}), **kept_and_rejected(reviews)}


def usage_inventory(rows: Iterable[Mapping[str, Any]]) -> dict[str, Any]:
    """The calls of the window from ``ai.usage`` by purpose, prompt and model, with each line's share of the spend (no line is called unnecessary
    here: that is a person's reading of it)."""
    items = sorted(((r.get("purpose"), r.get("prompt_version"), r.get("model"), int(r.get("calls") or 0), _dec(r.get("usd")) or Decimal(0))
                    for r in rows), key=lambda i: (-i[4], str(i[1]), str(i[2])))
    total = sum((usd for *_, usd in items), Decimal(0))
    cent, tenth = Decimal("0.01"), Decimal("0.1")
    return {"total_usd": str(total.quantize(cent)), "calls": sum(calls for _, _, _, calls, _ in items),
            "lines": [{"purpose": purpose, "prompt_version": prompt, "model": model, "calls": calls, "usd": str(usd.quantize(cent)),
                       "share_pct": None if total == 0 else str((100 * usd / total).quantize(tenth))}
                      for purpose, prompt, model, calls, usd in items]}


def report(reviews: Iterable[Review], usage: Iterable[Mapping[str, Any]] = (), *, since: datetime | None = None,
           until: datetime | None = None) -> dict[str, Any]:
    """The whole comparison, as JSON: per engine, per pair (``PAIRS``) and the spend of the window."""
    by = newest(reviews)
    return {"version": R4_VERSION, "decides": False, "since": None if since is None else since.isoformat(),
            "until": None if until is None else until.isoformat(),
            "engines": {e: engine_summary(e, by.get(e, {})) for e in ENGINES},
            "pairs": {f"{a}_vs_{b}": agreement(by, a, b) for a, b in PAIRS},
            "usage": usage_inventory(usage)}


def _ci(p: Mapping[str, Any]) -> str:
    if not p.get("cases"):
        return "0 casos"
    w = p.get("ci95_wilson_pct") or ["-", "-"]
    return f"{p['counted']}/{p['cases']} · {p['pct']} % · IC95 {w[0]}-{w[1]} %"


def lines(rep: Mapping[str, Any]) -> list[str]:
    """The report for a person, in Spanish: one line per engine, per pair and per disagreement, and the five dearest lines of the spend."""
    out = [f"Comparación {rep['version']} (informa, no decide) desde {rep.get('since') or '-'} hasta {rep.get('until') or '-'}"]
    for e, s in rep["engines"].items():
        k, r = s["kept"], s["rejected"]
        out.append(f"  {e}: {s['selections']} selecciones, rechaza {_ci(s['reject_rate'])}; coste US$ {s['cost_usd_of_the_compared_reviews']}; "
                   f"guardadas ROI {k['roi_pct']} % en {k['settled']} liquidadas, CLV medio {k['mean_clv_pct']} %; "
                   f"rechazadas ROI {r['roi_pct']} % en {r['settled']}, CLV medio {r['mean_clv_pct']} %")
    for name, p in rep["pairs"].items():
        out.append(f"  {name}: {p['common']} en común · acuerdo {_ci(p['agree'])} · mismo rechazar o no {_ci(p['agree_on_reject_or_not'])}")
        for tag, d in p["disagreements_on_reject"].items():
            if d["selections"]:
                out.append(f"      {tag}: {d['selections']} selecciones, {d['settled']} liquidadas, ganadas {_ci(d['won_of_decided'])}, "
                           f"ROI {d['roi_pct']} %, CLV medio {d['mean_clv_pct']} % (precio de quien la guardó)")
    u = rep["usage"]
    out.append(f"  Gasto de la ventana: US$ {u['total_usd']} en {u['calls']} llamadas")
    for i in u["lines"][:5]:
        out.append(f"      {i['purpose']} · {i['prompt_version']} · {i['model']}: US$ {i['usd']} ({i['share_pct']} %), {i['calls']} llamadas")
    return out


__all__ = ["ENGINES", "PAIRS", "R4_VERSION", "Review", "agreement", "clv_of", "engine_summary", "kept_and_rejected", "lines", "newest", "report",
           "review_of", "settle", "usage_inventory"]
