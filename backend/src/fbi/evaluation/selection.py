"""``eval-sel-v1``: the ONE evaluation after the match of a settled selection (IA-112, AD-K01). Pure: no database, no clock.

A selection is ``(layer, fixture, market, selection, line)``. What is evaluated is the decision that STOOD: the layer's last decision
before ``LAST_WORD`` (10 min) before kick-off - inside that window decision-v1 rejects everything because the match is about to start,
which says nothing about the selection (the same limit as the cycle of states, ``fbi.lifecycle.derive.LAST_WORD``).

THE QUESTIONS, each answered by a rule of this module:

1. ANTICIPATED AND HAPPENED. The probability the decision judged (its calibrated one, ``calibrada``, or the model's own,
   ``sin_calibrar``), the market's de-vigged probability at the same moment, and the result of the settlement of record
   (``settle-v4`` through ``intel.decision_outcomes``; for a layer without outcomes, ``settle-v4`` on the regulation score). A full
   result (win or loss) is scored: log loss and Brier of the judged probability and of the market's. A half result, a push or a void
   is not scored (the probability is of a full win): it is counted, never guessed.
2. VALUE AGAINST THE CLOSE. ``clv-v1`` (``fbi.market.closing_value``: odds x closing fair probability - 1), the quality of the price
   (GOOD above +1 %, BAD below -1 %, NEUTRAL, UNKNOWN without a close) and the verdict quality x result of the post-mortem
   (``verdict_of``, the post-mortem's rule held equal to it by a test: MERECIDO, SUERTE, VARIANZA, ERROR, NULO, SIN_DATOS). A hit is never value: a win with a BAD
   price is SUERTE.
3. THE FACTS CITED (``eval-evidence-v1``). Each item of evidence the decision cited is ``sostenido``, ``contradicho`` or
   ``no_evaluable``, by what the provider says the player did in the match: an absence (``out``, or an injury or suspension without
   another assertion) is held when he did not play; a starter (``starts``) when he started; a call-up (``available``) when he was in
   the squad. A doubt, an information, news, a coach: no rule, ``no_evaluable``. A fact without the provider's player id, or a match
   without the official line-up, cannot be judged - never matched by name.
4. THE LINE-UP (``eval-lineup-v1``). Whether the decision changed once the official line-up was known (the last decision before it
   against the one that stood), by how many points its probability moved, and how many of the estimated starters (AD-D04) started.
5. THE SCENARIO. Not judged in ``eval-sel-v1``: the scenario engine (AD-B02) keeps no reading by selection yet.

PARITY with ``intel.decision_outcomes``: the result re-derived with ``settle-v4`` from the regulation score (the core markets) against
the stored one, and ``clv-v1`` recomputed from the stored closing probability against the stored CLV. ``igual``, ``difiere`` (with the
reason) or ``sin_referencia``.

The same inputs give the same evaluation and the same ``input_hash``: an evaluation is never rewritten, a new rule is a new version.
"""

from __future__ import annotations

import hashlib
import json
import math
from collections.abc import Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal

from fbi.lifecycle import derive
from fbi.lifecycle.reader import family_of
from fbi.market import closing_value

VERSION: Final = "eval-sel-v1"
EVIDENCE_RULES: Final = "eval-evidence-v1"
LINEUP_RULES: Final = "eval-lineup-v1"
LAST_WORD: Final = timedelta(minutes=10)
"""The standing decision is the last one at least this long before kick-off (``fbi.lifecycle.derive.LAST_WORD``; a test holds them equal)."""
EPS: Final = 1e-6
"""A probability is clipped to [EPS, 1 - EPS] before its logarithm: a stored 0 or 1 would make the log loss infinite."""
CLV_Q: Final = Decimal("0.000001")
V2_LAYER: Final = "decision-v2"

FactStatus = Literal["sostenido", "contradicho", "no_evaluable"]
FACT_STATUSES: Final[tuple[str, ...]] = ("sostenido", "contradicho", "no_evaluable")
Parity = Literal["igual", "difiere", "sin_referencia"]
FULL_RESULTS: Final = frozenset({"win", "loss"})
RESULTS: Final[tuple[str, ...]] = ("win", "loss", "push", "void", "half_win", "half_loss")
ABSENCE_KINDS: Final = frozenset({"injury", "suspension"})


# ── what an evaluation is made of ────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Point:
    """A decision of the selection at one moment: its state (the layer's own word) and the probability it judged."""

    known_at: datetime
    state: str
    p: float


@dataclass(frozen=True, slots=True)
class Decided:
    """The decision that stood (read by ``fbi.evalpass.reads``)."""

    layer: str
    source: str
    decision_id: int
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal
    known_at: datetime
    kickoff_at: datetime
    checkpoint: str
    state: str
    p_model: float
    p_cal: float | None
    p_market: float | None
    odds: Decimal | None
    evidence_ids: tuple[int, ...] = ()
    reasons: tuple[str, ...] = ()
    context_status: str = "FULL"

    @property
    def cycle(self) -> tuple[str, str]:
        """Where the standing decision leaves the selection in the cycle (``lifecycle-map-v1``, ``fbi.lifecycle.derive.map_decision``);
        decision-v2 speaks its own words: RECOMMENDED is confirmed in the shadow, anything else is under evaluation."""
        if self.layer == V2_LAYER:
            return ("confirmada_sombra", "cumple_todo") if self.state == "RECOMMENDED" else ("en_evaluacion", "sin_motivo_conocido")
        return derive.map_decision(derive.Decision(self.decision_id, self.layer, self.known_at, self.checkpoint, self.state,
                                                   self.reasons, self.context_status, self.kickoff_at))

    @property
    def taken(self) -> bool:
        """The layer would take it: confirmed in the shadow - approved, or parked ONLY by its market's validation (what the board
        exists to measure)."""
        return self.cycle[0] == "confirmada_sombra"

    @property
    def family(self) -> str:
        return family_of(self.market_key)

    @property
    def p_judged(self) -> float:
        return self.p_cal if self.p_cal is not None else self.p_model

    @property
    def seal(self) -> str:
        return "calibrada" if self.p_cal is not None else "sin_calibrar"


@dataclass(frozen=True, slots=True)
class Settled:
    """The settlement of record of the standing decision and its close: ``intel.decision_outcomes`` for decision-v1 and the families,
    ``settle-v4`` on the regulation score (``source = 'settle-v4'``) for a layer that keeps no outcome."""

    result: str
    settled_at: datetime
    source: str
    version: str | None
    close_p_fair: Decimal | None
    close_minutes_to_ko: int | None
    stored_clv: Decimal | None


@dataclass(frozen=True, slots=True)
class Fact:
    """One item of evidence the decision cited (``ai.evidence``: its kind, the extractor's assertion and the provider's player id)."""

    id: int
    kind: str
    assertion: str | None
    provider_player_id: int | None


@dataclass(frozen=True, slots=True)
class PlayerDay:
    """What the provider says one player did in the match: in the squad (the official line-up, starters and substitutes, or a line of
    the player statistics), started, and his minutes (None: no statistics)."""

    in_squad: bool
    starter: bool
    minutes: int | None


@dataclass(frozen=True, slots=True)
class Match:
    """What happened in the match that the evaluation needs."""

    status: str
    reg_home: int | None
    reg_away: int | None
    lineup_at: datetime | None
    """When the official line-up was first seen (``core.fixture_lineups.first_seen_at``, the earliest side); None: never before kick-off."""
    players: Mapping[int, PlayerDay] = field(default_factory=dict)
    rederived: str | None = None
    """The result ``settle-v4`` gives on the regulation score (core markets only; None: not derivable)."""

    @property
    def lineup_known(self) -> bool:
        return any(p.in_squad for p in self.players.values())


@dataclass(frozen=True, slots=True)
class Inputs:
    decided: Decided
    settled: Settled
    match: Match
    facts: tuple[Fact, ...] = ()
    before_lineup: Point | None = None
    """The layer's last decision of the selection known before the official line-up (None: none, or no official line-up)."""
    estimate: tuple[int, int] | None = None
    """(estimated starters who started, estimated starters) of the two sides (AD-D04), None without an estimate."""


# ── the rules ────────────────────────────────────────────────────────────────────────────────────────────────────────

def clip(p: float) -> float:
    return min(max(p, EPS), 1.0 - EPS)


def log_loss(p: float, hit: int) -> float:
    q = clip(p)
    return -math.log(q if hit == 1 else 1.0 - q)


def brier(p: float, hit: int) -> float:
    return (p - hit) ** 2


def hit_of(result: str) -> int | None:
    """1 for a full win, 0 for a full loss; None for what a probability of a full win cannot be scored against."""
    if result not in RESULTS:
        raise ValueError(f"unknown result {result!r}")
    return {"win": 1, "loss": 0}.get(result)


def verdict_of(result: str, quality: str) -> str:
    """Quality x result, the post-mortem's rule (pm-v6; ``tests/unit/test_selection_evaluation.py`` holds the two equal on every pair):
    a push or a void is NULO, no close is SIN_DATOS, a win with a BAD price is SUERTE, a loss with a BAD one ERROR, a loss otherwise
    VARIANZA, a win otherwise MERECIDO. A half result counts as its side."""
    if result in ("push", "void"):
        return "NULO"
    if quality == "UNKNOWN":
        return "SIN_DATOS"
    if result in ("win", "half_win"):
        return "SUERTE" if quality == "BAD" else "MERECIDO"
    return "ERROR" if quality == "BAD" else "VARIANZA"


def assertion_of(fact: Fact) -> str | None:
    """What the fact claims: the extractor's assertion, or an absence for an injury or a suspension that says nothing else."""
    if fact.assertion:
        return fact.assertion
    return "out" if fact.kind in ABSENCE_KINDS else None


def judge_fact(fact: Fact, match: Match) -> tuple[str, str]:
    """``eval-evidence-v1``: (status, why) of one fact against what the provider says the player did."""
    claim = assertion_of(fact)
    if claim not in ("out", "starts", "available"):
        return "no_evaluable", "duda_sin_afirmacion" if claim == "doubtful" else "sin_regla"
    if fact.provider_player_id is None:
        return "no_evaluable", "sin_jugador_identificado"
    if not match.lineup_known:
        return "no_evaluable", "sin_alineacion_oficial"
    day = match.players.get(fact.provider_player_id)
    if claim == "starts":
        return ("sostenido", "fue_titular") if day is not None and day.starter else ("contradicho", "no_fue_titular")
    if claim == "available":
        return ("sostenido", "convocado") if day is not None and day.in_squad else ("contradicho", "no_convocado")
    if day is None:
        return "sostenido", "no_jugo"
    if day.starter or (day.minutes or 0) > 0:
        return "contradicho", "jugo"
    if day.minutes is None:
        return "no_evaluable", "minutos_desconocidos"
    return "sostenido", "no_jugo"


def lineup_effect(inputs: Inputs) -> dict[str, Any]:
    """``eval-lineup-v1``: did the official line-up change the decision, and how good was the estimate of the starters."""
    d, before, match = inputs.decided, inputs.before_lineup, inputs.match
    out: dict[str, Any] = {"rules": LINEUP_RULES, "official_known": match.lineup_at is not None
                           and match.lineup_at < d.kickoff_at,
                           "official_at": None if match.lineup_at is None else match.lineup_at.isoformat()}
    if match.lineup_at is None:
        out.update(changed=None, why="hora_de_la_alineacion_desconocida" if match.lineup_known else "sin_alineacion_oficial")
    elif not out["official_known"]:
        out.update(changed=None, why="sin_alineacion_oficial_antes_del_saque")
    elif match.lineup_at is not None and d.known_at < match.lineup_at:
        out.update(changed=None, why="sin_decision_tras_la_alineacion")
    elif before is None:
        out.update(changed=None, why="sin_decision_previa")
    else:
        out.update(changed=before.state != d.state, why="comparada", before={"state": before.state, "p": round(before.p, 6),
                                                                            "known_at": before.known_at.isoformat()},
                   p_change_pp=round((d.p_judged - before.p) * 100, 2))
    if inputs.estimate is None:
        out["estimate"] = {"why": "sin_estimacion", "piece": "AD-D04"}
    else:
        hits, of = inputs.estimate
        out["estimate"] = {"hits": hits, "of": of, "share": None if of == 0 else round(hits / of, 4)}
    return out


def parity(inputs: Inputs, clv: Decimal | None) -> dict[str, Any]:
    """The evaluation against ``intel.decision_outcomes``: the result re-derived with ``settle-v4`` and ``clv-v1`` recomputed."""
    s, m = inputs.settled, inputs.match
    if s.source != "intel.decision_outcomes":
        return {"status": "sin_referencia", "why": "la_capa_no_guarda_liquidacion"}
    diffs: list[dict[str, Any]] = []
    if m.rederived is not None and m.rederived != s.result:
        diffs.append({"what": "resultado", "stored": s.result, "settle_v4": m.rederived})
    if (s.stored_clv is None) != (clv is None) or (clv is not None and s.stored_clv is not None
                                                   and abs(s.stored_clv - clv) > CLV_Q):
        diffs.append({"what": "clv", "stored": None if s.stored_clv is None else str(s.stored_clv),
                      "recomputed": None if clv is None else str(clv)})
    checked = ["clv"] + (["resultado"] if m.rederived is not None else [])
    return {"status": "difiere" if diffs else "igual", "checked": checked, "differences": diffs,
            "outcome_version": s.version}


@dataclass(frozen=True)
class Evaluation:
    """One evaluation, as ``intel.selection_evaluations`` keeps it."""

    row: Mapping[str, Any]
    detail: Mapping[str, Any]

    def as_json(self) -> dict[str, Any]:
        return {**{k: _plain(v) for k, v in self.row.items()}, "detail": dict(self.detail)}


def _plain(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, Decimal):
        return str(v)
    return v


def _canonical(inputs: Inputs) -> str:
    def enc(o: Any) -> Any:
        if isinstance(o, (datetime, Decimal)):
            return _plain(o)
        raise TypeError(type(o).__name__)

    raw = asdict(inputs)
    raw["match"]["players"] = {str(k): v for k, v in sorted(raw["match"]["players"].items())}
    raw["facts"] = sorted(raw["facts"], key=lambda f: f["id"])
    return json.dumps(raw, sort_keys=True, default=enc, separators=(",", ":"))


def input_hash(inputs: Inputs) -> str:
    return hashlib.sha256(f"{VERSION}|{_canonical(inputs)}".encode()).hexdigest()


def evaluate(inputs: Inputs) -> Evaluation:
    """The evaluation of one settled selection. Raises ``ValueError`` for a decision that did not stand before kick-off."""
    d, s = inputs.decided, inputs.settled
    if d.known_at >= d.kickoff_at:
        raise ValueError("the standing decision is known before kick-off")
    hit = hit_of(s.result)
    p = d.p_judged
    clv = None if s.close_p_fair is None or d.odds is None else closing_value.clv(d.odds, s.close_p_fair).quantize(CLV_Q)
    quality = closing_value.quality(None if clv is None else float(clv))
    verdict = verdict_of(s.result, quality)
    facts = [(f, *judge_fact(f, inputs.match)) for f in sorted(inputs.facts, key=lambda f: f.id)]
    counts = {st: sum(1 for _, x, _ in facts if x == st) for st in FACT_STATUSES}
    lineup = lineup_effect(inputs)
    par = parity(inputs, clv)
    row: dict[str, Any] = {
        "version": VERSION, "layer": d.layer, "decision_source": d.source, "decision_id": d.decision_id,
        "fixture_id": d.fixture_id, "family": d.family, "taken": d.taken, "market_key": d.market_key, "selection": d.selection, "line": d.line,
        "kickoff_at": d.kickoff_at, "decided_at": d.known_at, "settled_at": max(s.settled_at, d.kickoff_at), "result": s.result,
        "p_judged": Decimal(repr(clip(p))).quantize(CLV_Q), "seal": d.seal,
        "p_market": None if d.p_market is None else Decimal(repr(d.p_market)).quantize(CLV_Q),
        "odds": d.odds, "p_close": None if clv is None else s.close_p_fair, "clv": clv, "hit": hit,
        "log_loss": None if hit is None else round(log_loss(p, hit), 6),
        "brier": None if hit is None else round(brier(p, hit), 6),
        "market_log_loss": round(log_loss(d.p_market, hit), 6) if d.p_market is not None and hit is not None else None,
        "market_brier": round(brier(d.p_market, hit), 6) if d.p_market is not None and hit is not None else None,
        "price_quality": quality, "verdict": verdict,
        "evidence_held": counts["sostenido"], "evidence_contradicted": counts["contradicho"],
        "evidence_unevaluable": counts["no_evaluable"], "lineup_changed": lineup.get("changed"),
        "parity": par["status"], "input_hash": input_hash(inputs),
    }
    detail = {
        "anticipated": {"p": round(p, 6), "seal": d.seal, "p_model": round(d.p_model, 6),
                        "p_market": None if d.p_market is None else round(d.p_market, 6),
                        "odds": None if d.odds is None else str(d.odds),
                        "expected_value": None if d.odds is None else round(float(d.odds) * p - 1, 6),
                        "state": d.state, "checkpoint": d.checkpoint, "decided_at": d.known_at.isoformat(),
                        "reasons": list(d.reasons), "cycle": {"state": d.cycle[0], "reason": d.cycle[1]}, "taken": d.taken},
        "happened": {"result": s.result, "source": s.source, "hit": hit, "scored": hit is not None,
                     "not_scored_why": None if hit is not None else "resultado_no_completo"},
        "value": {"clv": None if clv is None else str(clv), "p_close": None if clv is None else str(s.close_p_fair),
                  "close_minutes_to_ko": s.close_minutes_to_ko, "quality": quality, "verdict": verdict,
                  "notice_es": "Un acierto no valida el mercado."},
        "evidence": {"rules": EVIDENCE_RULES, "items": [{"id": f.id, "kind": f.kind, "claim": assertion_of(f), "status": st, "why": why}
                                                         for f, st, why in facts], **counts},
        "lineup": lineup,
        "scenario": {"status": "no_evaluable", "why": "sin_lectura_por_seleccion", "piece": "AD-B02"},
        "parity": par,
    }
    return Evaluation(row=row, detail=detail)


def standing(points: Sequence[tuple[datetime, Any]], kickoff_at: datetime) -> Any | None:
    """The last item known at least ``LAST_WORD`` before kick-off, from (known_at, item) pairs in any order."""
    eligible = [(k, i, x) for i, (k, x) in enumerate(points) if k <= kickoff_at - LAST_WORD]
    return max(eligible, key=lambda t: (t[0], t[1]))[2] if eligible else None
