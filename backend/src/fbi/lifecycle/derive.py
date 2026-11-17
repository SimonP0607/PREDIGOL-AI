"""``lifecycle-map-v1``: the cycle of a selection read off the layers that exist today (IA-068, AD-D02). Pure.

A selection is ``(fixture, market, selection, line)`` - decision-v1's key (``fbi.intel.decision.Key``). What each layer says
becomes a step of the cycle, in the order it was known:

    picks.picks (the shadow rule flags it)          the first sight of the selection             -> detectado
    intel.decisions (decision-v1, decision-fam-v1)  each decision before kick-off (``map_decision``):
                                                      the context not read yet (PENDING)        -> en_investigacion   contexto_pendiente
                                                      approved (APROBADO and its labels)        -> confirmada_sombra  cumple_todo
                                                      parked ONLY by its market's validation    -> confirmada_sombra  cumple_salvo_validacion
                                                        (edge_not_validated, family_shadow_only)
                                                      a key absence reported, nothing else,
                                                        before the line-ups                     -> pendiente_alineaciones  baja_por_confirmar
                                                      anything else                             -> en_evaluacion with its most severe blocker
                                                    a confirmed or waiting selection the next decision no longer holds
                                                                                                -> retirada (the blocker)
    ai.pick_reviews (combined review)               REJECT or DOWNGRADE of a waiting or confirmed selection, any mode
                                                                                                -> retirada  revision_en_contra (actor model)
    core.fixtures                                   the kick-off: a confirmed selection         -> en_juego  saque
                                                                  any other open one            -> descartada (why it never met)
                                                    a match that will not be played             -> descartada  partido_no_jugado
    intel.decision_outcomes                         the settlement of the decision that stood   -> liquidada  resultado
    intel.postmortems / intel.family_postmortems    its post-mortem                             -> evaluada  evaluacion_posterior

The decisions are read up to ten minutes before kick-off (``LAST_WORD``): inside that window decision-v1 rejects everything because
the match is about to start, which says nothing about the selection.

A rejection before kick-off is NOT ``descartada``: in 14 days of production (16-nov-2026) 709 of the 10.181 selections that
decision-v1 rejected at some checkpoint were not rejected at a later one, so the cycle keeps them under evaluation with the
reason and closes them at kick-off with the last one. Repeated rows that say the same thing are one step. Nothing here reads
a clock: ``now`` is given, and the same inputs give the same chain.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final

from fbi.lifecycle import machine
from fbi.lifecycle.machine import Step

MAP_VERSION: Final = "lifecycle-map-v1"
LINE_Q: Final = Decimal("0.01")

APPROVED: Final = frozenset({"APROBADO", "PICK_DEL_DIA", "PICK_PREMIUM", "CANDIDATO_PARLAY"})
"""decision-v1's approval and its labels (``fbi.intel.decision.APPROVED``)."""
MARKET_LEVEL: Final = frozenset({"edge_not_validated", "family_shadow_only"})
"""What parks a selection that meets everything of its own: its market's edge is not validated out of sample (edge-gate-v1), or
it is a family's, which only the owner can lift (``fbi.familydecisions.decide.REASON_CAPPED``). The shadow exists to measure
exactly these: the selection is confirmed IN THE SHADOW, with the reason that says so."""
INFO: Final = frozenset({"family_research"})
"""Reasons that move no state (``fbi.decision.families.INFO_CODES``)."""

BLOCKER_OF: Final[Mapping[str, str]] = {
    "data": "datos_insuficientes", "model": "sin_modelo", "no_price": "sin_precio", "thin_market": "mercado_estrecho",
    "price_outlier": "precio_atipico", "context_stop": "contexto_lo_impide", "key_absence_confirmed": "baja_clave_confirmada",
    "ev_cal_below": "valor_insuficiente", "not_calibrated": "sin_calibrar", "ev_unknown": "sin_calibrar",
    "price_stale": "precio_antiguo", "ai_reject": "revision_en_contra", "ai_downgrade": "revision_en_contra",
    "key_absence_reported": "baja_por_confirmar", "price_not_fresh": "precio_antiguo",
    "correlated_same_match": "otra_del_partido", "risk": "riesgo",
}
"""Every reason code decision-v1 writes (``fbi.intel.state_v2.REASON_EFFECT``) and the cycle's blocker, in order of severity:
the rejections first, then what parks it (calibration, the price's age), then what only cautions. A row's reason is its first."""
PRIORITY: Final[tuple[str, ...]] = tuple(BLOCKER_OF)

STARTED_STATUS: Final = frozenset({"1H", "HT", "2H", "ET", "BT", "P", "LIVE", "FT", "AET", "PEN", "INT", "SUSP"})
NOT_PLAYED: Final = frozenset({"CANC", "ABD", "AWD", "WO"})
"""A match that will not be played as scheduled: closed at once."""
DEFERRED: Final = frozenset({"PST", "TBD"})
"""Postponed: the same fixture may be played on another day, so its selections stay open for ``DEFERRED_GRACE``."""
DEFERRED_GRACE: Final = timedelta(days=3)
LAST_WORD: Final = timedelta(minutes=10)
"""decision-v1 rejects every selection in the last 10 minutes before its kick-off (filter 1, ``MIN_MINUTES``: «menos de 10 min al
saque»): a row written that close says the match is about to start, not that the selection lost its ground. The cycle reads the
decisions up to that limit; the selection's word is the last one before it (``tests/unit/test_lifecycle_derive.py`` holds the
limit equal to ``fbi.intel.decision.MIN_MINUTES``). In 14 days of production (16-nov-2026) 596 rows of decision-v1 were of this
kind (568 at the ``lineups`` checkpoint), and every selection confirmed in the shadow was «withdrawn» by one of them."""


@dataclass(frozen=True, slots=True)
class Key:
    fixture_id: int
    market_key: str
    selection: str
    line: Decimal

    @staticmethod
    def of(fixture_id: int, market_key: str, selection: str, line: Decimal | float | str) -> Key:
        return Key(int(fixture_id), str(market_key), str(selection), Decimal(str(line)).quantize(LINE_Q))


@dataclass(frozen=True, slots=True)
class Decision:
    id: int
    layer: str
    known_at: datetime
    checkpoint: str
    state: str
    reasons: tuple[str, ...]
    context_status: str
    kickoff_at: datetime | None = None
    """The kick-off the decision was taken for (``intel.decisions.kickoff_at``)."""
    evaluation: str | None = None
    """The evaluation (E1-E4) the decision was taken in, where its layer records one (decision-v2's shadow, IA-093); None otherwise."""
    evaluation_version: int | None = None


@dataclass(frozen=True, slots=True)
class Review:
    id: int
    reviewed_at: datetime
    decision: str


@dataclass(frozen=True, slots=True)
class Fixture:
    id: int
    kickoff_at: datetime
    status_short: str | None
    status_group: str | None = None


@dataclass(frozen=True, slots=True)
class Outcome:
    decision_id: int
    settled_at: datetime
    result_status: str


@dataclass(frozen=True, slots=True)
class Evaluation:
    decision_id: int
    created_at: datetime
    source: str
    source_id: int


@dataclass(slots=True)
class History:
    """Everything the layers hold about one selection."""

    key: Key
    detected_at: datetime | None = None
    detected_pick: int | None = None
    decisions: list[Decision] = field(default_factory=list)
    reviews: list[Review] = field(default_factory=list)
    outcomes: dict[int, Outcome] = field(default_factory=dict)
    evaluations: dict[int, Evaluation] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class Row:
    """One row of ``intel.selection_lifecycle`` as the shadow writer would append it."""

    step: Step
    known_at: datetime
    source: str
    source_id: int | None
    layer: str


def map_decision(d: Decision) -> tuple[str, str]:
    """(state, reason) of the cycle for one decision row before kick-off. Pure, total: an unknown code is
    ``sin_motivo_conocido``, never an exception."""
    codes = [c for c in d.reasons if c not in INFO]
    known = [c for c in PRIORITY if c in codes]
    unknown = [c for c in codes if c not in BLOCKER_OF and c not in MARKET_LEVEL]
    if d.context_status == "PENDING" and d.state != "RECHAZADO":
        return "en_investigacion", "contexto_pendiente"
    if d.state in APPROVED:
        return "confirmada_sombra", "cumple_todo"
    if d.state == "INVESTIGACION" and not known and not unknown and any(c in MARKET_LEVEL for c in codes):
        return "confirmada_sombra", "cumple_salvo_validacion"
    if known == ["key_absence_reported"] and not unknown and d.checkpoint != "lineups":
        return "pendiente_alineaciones", "baja_por_confirmar"
    if known:
        return "en_evaluacion", BLOCKER_OF[known[0]]
    return "en_evaluacion", "sin_motivo_conocido"


def closing_reason(state: str, reason: str) -> str:
    """Why an open selection that was not confirmed at kick-off is discarded: the last thing that held it."""
    if state == "detectado":
        return "sin_decision"
    if state == "en_investigacion":
        return "contexto_pendiente"
    if state == "pendiente_alineaciones":
        return "sin_alineacion_a_tiempo"
    if state == "retirada":
        return "retirada_al_saque"
    return reason if reason in machine.REASONS["descartada"] else "sin_motivo_conocido"


class _Chain:
    def __init__(self, layer: str) -> None:
        self.rows: list[Row] = []
        self.layer = layer

    @property
    def state(self) -> str | None:
        return self.rows[-1].step.state if self.rows else None

    @property
    def reason(self) -> str | None:
        return self.rows[-1].step.reason if self.rows else None

    @property
    def at(self) -> datetime | None:
        return self.rows[-1].known_at if self.rows else None

    def emit(self, step: Step, at: datetime, source: str, source_id: int | None) -> None:
        machine.check(self.state, step)
        last = self.at
        self.rows.append(Row(step, at if last is None or at >= last else last, source, source_id, self.layer))

    def code(self, state: str, reason: str, at: datetime, source: str, source_id: int | None, *, evaluation: str | None = None,
             evaluation_version: int | None = None) -> None:
        """A move the code makes from what a layer says, folded into the cycle (with the evaluation it was made in, when there is one)."""
        current = self.state
        if current == state and reason == self.reason:
            return
        if current == "retirada" and state in ("en_evaluacion", "en_investigacion"):
            return  # withdrawn it stays, until it comes back or closes
        if current in ("pendiente_alineaciones", "confirmada_sombra") and state in ("en_evaluacion", "en_investigacion"):
            self.emit(Step("retirada", reason if reason in machine.REASONS["retirada"] else "sin_motivo_conocido",
                           evaluation=evaluation, evaluation_version=evaluation_version), at, source, source_id)
            return
        self.emit(Step(state, reason, evaluation=evaluation, evaluation_version=evaluation_version), at, source, source_id)


def _played(f: Fixture, now: datetime) -> bool:
    return now >= f.kickoff_at and ((f.status_short or "") in STARTED_STATUS or f.status_group in ("live", "finished"))


def _not_played(f: Fixture, now: datetime) -> bool:
    status = f.status_short or ""
    return status in NOT_PLAYED or (status in DEFERRED and now >= f.kickoff_at + DEFERRED_GRACE)


DECISIONS: Final = "intel.decisions"
"""Where the decisions of today's layers are read from (``source`` of their rows)."""


def derive(h: History, fixture: Fixture, *, now: datetime, source: str = DECISIONS) -> list[Row]:
    """The chain of one selection as of ``now``: every step the layers support, each checked by the machine. ``source``: the table the
    decisions of ``h`` were read from (``intel.decisions`` for decision-v1 and decision-fam-v1; ``intel.decisions_v2`` for decision-v2's
    shadow, IA-093)."""
    before = [d for d in h.decisions if d.known_at < fixture.kickoff_at - LAST_WORD
              and (d.kickoff_at is None or d.known_at < d.kickoff_at - LAST_WORD)]
    by_moment: dict[datetime, Decision] = {}
    for d in sorted(before, key=lambda x: (x.known_at, x.id)):
        by_moment[d.known_at] = d  # two models at one moment: the newest row is the selection's word
    decisions = list(by_moment.values())
    seen = sorted((d for d in h.decisions if d.known_at < fixture.kickoff_at), key=lambda x: (x.known_at, x.id))
    layer = seen[0].layer if seen else "decision-v1"
    chain = _Chain(layer)
    firsts = [t for t in (h.detected_at, seen[0].known_at if seen else None) if t is not None]
    if not firsts:
        return []
    start = min(firsts)
    if h.detected_at is not None and h.detected_at == start:
        chain.emit(Step("detectado", "candidato_nuevo"), start, "picks.picks", h.detected_pick)
    else:
        chain.emit(Step("detectado", "candidato_nuevo"), start, source, seen[0].id)

    events: list[tuple[datetime, int, int, Decision | Review]] = [(d.known_at, 0, d.id, d) for d in decisions]
    events += [(r.reviewed_at, 1, r.id, r) for r in h.reviews
               if start <= r.reviewed_at < fixture.kickoff_at and r.decision in ("REJECT", "DOWNGRADE")]
    for at, _, _, ev in sorted(events, key=lambda e: (e[0], e[1], e[2])):
        if isinstance(ev, Decision):
            state, reason = map_decision(ev)
            chain.code(state, reason, at, source, ev.id, evaluation=ev.evaluation, evaluation_version=ev.evaluation_version)
        elif chain.state in ("pendiente_alineaciones", "confirmada_sombra"):
            chain.emit(Step("retirada", "revision_en_contra", actor="model"), at, "ai.pick_reviews", ev.id)

    standing = decisions[-1] if decisions else None
    current = chain.state
    if current in machine.OPEN and _not_played(fixture, now):
        if current in ("pendiente_alineaciones", "confirmada_sombra"):
            chain.emit(Step("retirada", "partido_no_jugado"), fixture.kickoff_at, "core.fixtures", fixture.id)
        chain.emit(Step("descartada", "partido_no_jugado"), fixture.kickoff_at, "core.fixtures", fixture.id)
    elif current in machine.OPEN and _played(fixture, now):
        if current == "confirmada_sombra":
            chain.emit(Step("en_juego", "saque"), fixture.kickoff_at, "core.fixtures", fixture.id)
        else:
            chain.emit(Step("descartada", closing_reason(str(current), str(chain.reason))), fixture.kickoff_at, "core.fixtures",
                       fixture.id)
    if chain.state == "en_juego" and standing is not None:
        out = _newest(h.outcomes, h.decisions, standing.id)
        if out is not None and out.result_status in machine.SETTLED_RESULTS and out.settled_at <= now:
            chain.emit(Step("liquidada", "resultado", settlement_result=out.result_status), out.settled_at,
                       "intel.decision_outcomes", out.decision_id)
    if chain.state == "liquidada" and standing is not None:
        post = _newest(h.evaluations, h.decisions, standing.id)
        if post is not None and post.created_at <= now:
            chain.emit(Step("evaluada", "evaluacion_posterior"), post.created_at, post.source, post.source_id)
    return chain.rows


def _newest[T](by_decision: Mapping[int, T], decisions: Sequence[Decision], standing: int) -> T | None:
    """The settlement (or post-mortem) of the decision that stood, else of the newest decision of the selection that has one:
    every row of one selection settles the same bet (a post-mortem is written for the last row of a match, which may be one
    inside the last ten minutes)."""
    if standing in by_decision:
        return by_decision[standing]
    for d in sorted(decisions, key=lambda x: (x.known_at, x.id), reverse=True):
        if d.id in by_decision:
            return by_decision[d.id]
    return None


def steps_of(rows: Sequence[Row]) -> list[Step]:
    return [r.step for r in rows]


def as_of(h: History, now: datetime) -> History:
    """What the layers held about ``h`` at ``now`` (the rows they had written by then). Pure: the replay of a past moment, so
    that a chain derived then can be checked as a prefix of the chain derived later."""
    picked = h.detected_at is not None and h.detected_at <= now
    return History(h.key, h.detected_at if picked else None, h.detected_pick if picked else None,
                   [d for d in h.decisions if d.known_at <= now], [r for r in h.reviews if r.reviewed_at <= now],
                   {i: o for i, o in h.outcomes.items() if o.settled_at <= now},
                   {i: e for i, e in h.evaluations.items() if e.created_at <= now})
