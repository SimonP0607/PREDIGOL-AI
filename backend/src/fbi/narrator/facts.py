"""The facts a reader may be told about ONE pick, taken from its trace and nothing else (``narrator-v1``).

WHAT IT READS. The JSON of a trace-v1 (``fbi.observability.trace.Trace.as_json``) anchored on the pick, and - optionally - the
match's identity (the two teams and the competition, read by ``fbi.narrator.job`` from the fixture the trace names: names, never a
reason). Of the trace, only what the pick's own decision used:

    the decision     the newest decision span that names the pick (else the selection's newest): its state, checkpoint, the
                     calibrated probability, the market's fair probability, the odds and how many books priced it, the
                     calibrated EV and edge, the Pick Score, the stake, its ten filters (passed or not, with their effect), the
                     reason codes it recorded and its context status
    the forecast     the interval of the prediction the pick was made from (``p_lo``, ``p_hi``)
    the review       the review the decision CITES (by its ``review_id``) - its verdict and confidence; never a review it did
                     not cite (the shadow engines' rows are in the trace and are never facts)
    the evidence     the evidence the decision CITES (its ``evidence_ids``) found in the trace: kind, status, the claim's text
                     as the trace keeps it and the outlet's domain. An OUTDATED item is not a fact; a RUMOR or a CONTRADICTORY
                     one is a risk, never a reason

Nothing else of the trace is a fact: not the agents' runs, not the packets, not the price snapshots, not the settlement, the
outcome or the post-mortem (a pick is explained BEFORE its result). The versions (decision, model, calibrator, code...) are kept
beside the facts for the report and the hash - they are the system's words, never the reader's.

EACH FACT has an id (``F:odds``, ``F:filter.ev``, ``F:evidence.123``), a role and a code with its params:

    identity   the match (names only)                       may be named in any sentence
    core       what the card shows: the pick, the probability, the odds, the value, the verdict, the score, the stake
    reason     a filter passed, the review's approval, a confirmed or probable piece of evidence
    risk       a filter not passed, a risk the decision recorded, a weak review, a rumour or a contradiction

The list is CLOSED and DETERMINISTIC: the same trace gives the same facts, in the same order, with the same ids and the same hash
(``PickFacts.hash``) - and a decision that changes gives another hash: the narrative is written again.

Pure: no database, no clock, no call.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final

from fbi.narrator import VERSION

TRACE_VERSION: Final = "trace-v1"
ROLES: Final = ("identity", "core", "reason", "risk")
NAME_KEYS: Final = ("home", "away", "competition")
"""Params that hold names, never numbers («Schalke 04»)."""
TEXT_KEYS: Final = ("claim", "source")
"""Params that hold text from outside: their names and numbers are allowed only to a sentence that cites them."""
SCORE_SCALE: Final = 100
"""The Pick Score is out of 100 (``fbi.intel.score``): a sentence that says «82 sobre 100» states the scale, a fact's own number."""
EVIDENCE_REASON: Final = ("CONFIRMED", "PROBABLE")
EVIDENCE_RISK: Final = ("RUMOR", "CONTRADICTORY")
REASON_RISKS: Final[Mapping[str, str]] = {
    "key_absence_reported": "key_absence",
    "price_not_fresh": "price_not_fresh",
    "correlated_same_match": "correlated",
    "edge_not_validated": "edge_not_validated",
}
"""The reason codes of ``decision-v1`` that are a risk a reader is told, and the fact each becomes. Any other code is not a fact
(it is already a filter, or it is the system's own word): a code this table does not know is never guessed at."""
RISK_PATTERNS: Final[tuple[tuple[str, re.Pattern[str], tuple[str, ...]], ...]] = (
    ("long_odds", re.compile(r"cuota (\d+(?:\.\d+)?) > (\d+(?:\.\d+)?)"), ("odds", "limit")),
    ("low_probability", re.compile(r"p calibrada (\d+(?:\.\d+)?) < (\d+(?:\.\d+)?)"), ("probability", "limit")),
    ("wide_interval", re.compile(r"intervalo (\d+(?:\.\d+)?) pts"), ("points",)),
)
"""The quantitative risks filter 7 writes in its ``why`` (``fbi.intel.decision``, risk-v1): read back as numbers. A ``why`` that
none of them matches gives the plain fact that the risk filter did not pass, with no number."""


@dataclass(frozen=True, slots=True)
class Identity:
    home: str | None = None
    away: str | None = None
    competition: str | None = None


@dataclass(frozen=True, slots=True)
class Fact:
    id: str
    role: str
    code: str
    params: Mapping[str, Any] = field(default_factory=dict)

    def as_json(self) -> dict[str, Any]:
        return {"id": self.id, "role": self.role, "code": self.code, "params": dict(self.params)}


@dataclass(frozen=True, slots=True)
class PickFacts:
    """The closed list of facts of one pick, and what identifies the decision they come from."""

    pick_id: int
    fixture_id: int | None
    trace_id: str | None
    decision_id: int | None
    decision_at: str | None
    market: str
    selection: str
    line: str
    pick_status: str | None
    versions: Mapping[str, str]
    facts: tuple[Fact, ...]

    def by_id(self) -> dict[str, Fact]:
        return {f.id: f for f in self.facts}

    @property
    def hash(self) -> str:
        """What the narrative is written from: the version, the decision row and its facts. Another decision (a new checkpoint,
        a new price, another state) is another hash - the narrative of the old one is not the pick's any more."""
        body = {"v": VERSION, "pick": self.pick_id, "decision": self.decision_id, "at": self.decision_at,
                "versions": dict(self.versions), "facts": [f.as_json() for f in self.facts]}
        return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False, default=str).encode()).hexdigest()

    @property
    def names(self) -> tuple[str, ...]:
        """The names of the match (the identity fact): a name is never read as a number."""
        out: set[str] = set()
        for f in self.facts:
            for key in NAME_KEYS:
                value = f.params.get(key)
                if isinstance(value, str) and value:
                    out.add(value)
        return tuple(sorted(out))

    def as_json(self) -> dict[str, Any]:
        return {"version": VERSION, "pick_id": self.pick_id, "fixture_id": self.fixture_id, "trace_id": self.trace_id,
                "decision_id": self.decision_id, "decision_at": self.decision_at, "market": self.market,
                "selection": self.selection, "line": self.line, "pick_status": self.pick_status, "versions": dict(self.versions),
                "input_hash": self.hash, "facts": [f.as_json() for f in self.facts]}


# ── reading the trace ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _obj(x: Any) -> Mapping[str, Any]:
    return x if isinstance(x, Mapping) else {}


def _num(x: Any) -> float | None:
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, (int, float)):
        return float(x)
    if isinstance(x, str):
        try:
            return float(x)
        except ValueError:
            return None
    return None


def _int(x: Any) -> int | None:
    n = _num(x)
    return None if n is None or n != int(n) else int(n)


def _present(spans: Iterable[Mapping[str, Any]], kind: str) -> list[Mapping[str, Any]]:
    return [s for s in spans if s.get("kind") == kind and s.get("status") == "present"]


def _row_id(span: Mapping[str, Any]) -> str | None:
    ids = span.get("row_ids")
    return str(ids[0]) if isinstance(ids, Sequence) and not isinstance(ids, str) and ids else None


def _clean(params: Mapping[str, Any]) -> dict[str, Any]:
    """Params without the empty ones: a fact says only what it has."""
    return {k: v for k, v in params.items() if v is not None and v != ""}


def _text(x: Any) -> str | None:
    return " ".join(str(x).split()) if isinstance(x, str) and x.strip() else None


def chosen_decision(spans: Sequence[Mapping[str, Any]], pick_id: int) -> Mapping[str, Any] | None:
    """The pick's decision: the newest decision span that names the pick (the trace lists them by time), else the selection's
    newest one."""
    decisions = _present(spans, "decision")
    own = [d for d in decisions if _int(_obj(d.get("payload")).get("pick_id")) == pick_id]
    pool = own or decisions
    return pool[-1] if pool else None


def from_trace(trace: Mapping[str, Any], *, pick_id: int, identity: Identity | None = None) -> PickFacts | str:
    """The facts of the pick ``pick_id`` from its trace's JSON, or why there are none (a code): ``not_trace_v1``, ``no_pick``,
    ``no_decision``."""
    if trace.get("version") != TRACE_VERSION:
        return "not_trace_v1"
    spans = [s for s in trace.get("spans") or [] if isinstance(s, Mapping)]
    pick_span = next((s for s in _present(spans, "pick") if _row_id(s) == str(pick_id)), None)
    if pick_span is None:
        return "no_pick"
    decision = chosen_decision(spans, pick_id)
    if decision is None:
        return "no_decision"
    d = _obj(decision.get("payload"))
    p = _obj(pick_span.get("payload"))
    market, selection = str(trace.get("market_key") or ""), str(trace.get("selection") or "")
    line = str(trace.get("line") or "0.00")
    facts: list[Fact] = []

    if identity is not None and (identity.home or identity.away):
        facts.append(Fact("F:match", "identity", "match", _clean({"home": identity.home, "away": identity.away,
                                                                   "competition": identity.competition})))
    line_value = _num(line)
    facts.append(Fact("F:pick", "core", "pick", _clean({"market": market, "selection": selection,
                                                        "line": line_value if line_value else None,
                                                        "checkpoint": _text(d.get("checkpoint"))})))
    filters = [f for f in d.get("filters") or [] if isinstance(f, Mapping) and f.get("key")]
    calibration = next((f for f in filters if f.get("key") == "calibration"), None)
    p_cal = _num(d.get("p_cal"))
    if p_cal is not None:
        facts.append(Fact("F:probability", "core", "probability",
                          {"probability": p_cal, "calibrated": bool(calibration is not None and calibration.get("ok") is True)}))
    forecast = next((s for s in _present(spans, "forecast") if _int(_obj(s.get("payload")).get("pick_id")) == pick_id), None)
    if forecast is not None:
        fp = _obj(forecast.get("payload"))
        low, high = _num(fp.get("p_lo")), _num(fp.get("p_hi"))
        if low is not None and high is not None:
            facts.append(Fact("F:interval", "core", "interval", {"low": low, "high": high}))
    p_market = _num(d.get("p_market"))
    if p_market is not None:
        facts.append(Fact("F:market_probability", "core", "market_probability", {"probability": p_market}))
    odds = _num(d.get("odds"))
    if odds is not None:
        facts.append(Fact("F:odds", "core", "odds", _clean({"odds": odds, "bookmakers": _int(d.get("n_bookmakers"))})))
    ev, edge = _num(d.get("ev_cal")), _num(d.get("edge_cal"))
    if ev is not None or edge is not None:
        facts.append(Fact("F:value", "core", "value", _clean({"ev": ev, "edge": edge})))
    if d.get("state"):
        facts.append(Fact("F:verdict", "core", "verdict", {"state": str(d["state"])}))
    score = _num(d.get("score"))
    if score is not None:
        facts.append(Fact("F:score", "core", "score", {"score": score, "out_of": SCORE_SCALE}))
    stake = _num(d.get("stake_units"))
    if stake is None:
        stake = _num(p.get("stake_units"))
    if stake is not None:
        facts.append(Fact("F:stake", "core", "stake", {"units": stake}))

    for f in sorted(filters, key=lambda f: (_int(f.get("n")) or 0, str(f.get("key")))):
        ok = f.get("ok")
        if ok is None:
            continue
        key = str(f["key"])
        facts.append(Fact(f"F:filter.{key}", "reason" if ok is True else "risk", "filter",
                          _clean({"filter": key, "passed": ok is True, "effect": None if ok is True else _text(f.get("effect"))})))
        if key == "risk" and ok is not True:
            facts.extend(_risk_details(str(f.get("why") or "")))

    reasons = [str(r) for r in d.get("reasons") or [] if isinstance(r, str)]
    for code in sorted({REASON_RISKS[r] for r in reasons if r in REASON_RISKS}):
        facts.append(Fact(f"F:risk.{code}", "risk", code, {}))
    if d.get("context_status") == "LIMITED":
        facts.append(Fact("F:context.limited", "risk", "context_limited", {}))

    review_id = _int(d.get("review_id"))
    if review_id is not None:
        review = next((s for s in _present(spans, "review") if _row_id(s) == str(review_id)), None)
        if review is not None:
            rp = _obj(review.get("payload"))
            verdict = _text(rp.get("decision"))
            if verdict:
                facts.append(Fact("F:review", "reason" if verdict == "APPROVE" else "risk", "review",
                                  _clean({"verdict": verdict, "confidence": _num(rp.get("confidence"))})))

    cited = sorted({i for i in (_int(e) for e in d.get("evidence_ids") or []) if i is not None})
    by_id = {_row_id(s): s for s in _present(spans, "evidence")}
    for eid in cited:
        span = by_id.get(str(eid))
        if span is None:
            continue
        ep = _obj(span.get("payload"))
        status = str(ep.get("status") or "")
        claim = _text(ep.get("claim"))
        if claim is None or status not in (*EVIDENCE_REASON, *EVIDENCE_RISK):
            continue
        facts.append(Fact(f"F:evidence.{eid}", "reason" if status in EVIDENCE_REASON else "risk", "evidence",
                          _clean({"kind": _text(ep.get("kind")), "status": status, "claim": claim,
                                  "source": _text(ep.get("source_domain"))})))

    versions = {f"decision.{k}": str(v) for k, v in sorted(_obj(decision.get("versions")).items())}
    versions |= {f"pick.{k}": str(v) for k, v in sorted(_obj(pick_span.get("versions")).items())}
    return PickFacts(pick_id=pick_id, fixture_id=_int(trace.get("fixture_id")),
                     trace_id=None if trace.get("trace_id") is None else str(trace["trace_id"]),
                     decision_id=_int(_row_id(decision)), decision_at=_text(decision.get("at")), market=market,
                     selection=selection, line=line, pick_status=_text(p.get("status")), versions=versions, facts=tuple(facts))


def _risk_details(why: str) -> list[Fact]:
    out: list[Fact] = []
    for code, pattern, keys in RISK_PATTERNS:
        m = pattern.search(why)
        if m is not None:
            out.append(Fact(f"F:risk.{code}", "risk", code, {k: float(v) for k, v in zip(keys, m.groups(), strict=True)}))
    return out
