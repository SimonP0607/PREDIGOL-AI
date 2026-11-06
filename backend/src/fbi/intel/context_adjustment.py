"""``ctx-adj-v1``: the typed contract between the Council (``cd-v1``) and the decision layer, in SHADOW (plan IA, P0).

WHY. The Council of the shadow engines (``ma-v1``: Match Agent + Council Sonnet, Opus by rule; ``ma-v1-h``: the same with Haiku as the judge)
writes one verdict per selection into ``ai.pick_reviews``, and filter 6 of ``decision-v1`` never reads it (``fbi.intel.decision.REVIEWS_SQL``
reads ``combined`` and ``rules`` only). Before anyone can ask whether the Council SHOULD touch a decision, the question has to be answered
in a form that cannot leak: what would the Council's verdict do to the state decision-v1 gave, if it were allowed to act? This module is
that form, and nothing else:

* ``ContextAdjustment`` - a frozen record of what the Council said of ONE selection, in five words (``CONFIRMA``, ``RESERVA``, ``BLOQUEA``,
  ``FALTA_INFO``, ``SIN_COUNCIL``), an ordinal severity, the cd-v1 codes it rests on, the evidence it cites, the agents it overruled and
  where it came from. It carries NO number that could reach a probability, a price or a stake: a model's output never carries a number
  into a decision (the only integers are the ids of the rows it was read from and of the evidence it cites).
* ``from_review`` / ``from_council_output`` - STRICT parsers of what the shadow really stores (a row of ``ai.pick_reviews`` written by
  ``fbi.ai.orchestrator.review_rows``; the cd-v1 answer ``ai.agent_runs.output`` keeps). A verdict, a code, a status, a version that is not
  known here raises ``UnknownCouncilOutputError``: a new word of the Council is a new version of this contract, never a guess.
* ``proposed_effect`` - the deterministic, MONOTONE effect: an adjustment can lower a state or leave it, never raise it.
* ``adjustments_for`` - the as-of reader (``reviewed_at <= at``) of the two engines.
* ``shadow_report`` - decision-v1 against what the adjustment would have proposed, over a window. It writes nothing.

Nothing here is imported by ``fbi.intel.decision`` or by anything that decides, shows or stakes: it is computed and reported, never wired.
"""

from __future__ import annotations

from collections import Counter, defaultdict
from collections.abc import Collection, Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Any, Final, Literal, get_args

import psycopg
from psycopg.rows import dict_row

from fbi.ai.agents.common import CONTRA_CODES
from fbi.ai.contracts import parse
from fbi.ai.contracts.base import COUNCIL, RISK_CODES, SIGNAL_CODES, Level, Stance, parse_ref
from fbi.ai.contracts.council import CouncilOut, EscalationRule
from fbi.core.decision_versions import DECISION_CORE
from fbi.intel.decision import APPROVED, RANK

VERSION: Final = "ctx-adj-v1"

AdjVerdict = Literal["CONFIRMA", "RESERVA", "BLOQUEA", "FALTA_INFO", "SIN_COUNCIL"]
VERDICTS: Final = get_args(AdjVerdict)
Severity = Literal["baja", "media", "alta", "bloqueante"]
SEVERITIES: Final = get_args(Severity)

ENGINES: Final = ("ma-v1", "ma-v1-h")
"""The engines whose Council this contract reads (``fbi.ai.arms.MULTIAGENT`` and ``MULTIAGENT_HAIKU``, held equal by a test). ``cs-v1``
(COUNCIL SOLO) is out of scope: it reads no specialist, so it has no agent to overrule and is not the Council the plan wires next."""
CONTRACT: Final = COUNCIL
"""``cd-v1``: the only Council contract this version accepts (``output.contract`` of every row of the two engines)."""
COUNCIL_VERSIONS: Final = frozenset({"council-v1"})
"""The Council versions (a part of ``engine_version``) this parser knows. A new council prompt or view is read only once it is listed here."""

ANSWERED: Final = "ok"
UNANSWERED: Final = frozenset({"fallback", "invalid_output", "failed", "over_budget"})
"""``ai.pick_reviews.status`` of a shadow row: ``ok`` is a Council verdict that stands; the others are the orchestrator's ABSTAIN with no
verdict behind it (the arm did not run, the answer did not validate, the call failed, the budget said no) - ``fbi.ai.orchestrator``."""

VERDICT_MAP: Final[Mapping[tuple[str, str], AdjVerdict]] = {
    ("APPROVE", "answered"): "CONFIRMA",
    ("DOWNGRADE", "answered"): "RESERVA",
    ("REJECT", "answered"): "BLOQUEA",
    ("ABSTAIN", "answered"): "FALTA_INFO",
    ("ABSTAIN", "unanswered"): "SIN_COUNCIL",
}
"""cd-v1 verdict x whether the Council answered -> the adjustment's verdict. THE mapping of this contract; any other pair raises.

    APPROVE    answered    CONFIRMA      the Council found nothing against the selection: it confirms, it never promotes
    DOWNGRADE  answered    RESERVA       it keeps a reservation: the selection is held at CAUTELA at most
    REJECT     answered    BLOQUEA       it blocks: the selection would be RECHAZADO
    ABSTAIN    answered    FALTA_INFO    it read the match and could not stand on anything - its own ABSTAIN, or one ``contracts.council.check``
                                         made of an APPROVE without data in its favour or a REJECT/DOWNGRADE without a reference that stands:
                                         information is missing, the selection would wait (INVESTIGACION, WATCH in state-v2)
    ABSTAIN    unanswered  SIN_COUNCIL   no Council verdict exists (status fallback / invalid_output / failed / over_budget): nothing changes

An APPROVE, DOWNGRADE or REJECT on a row the Council did not answer cannot exist (the orchestrator writes ABSTAIN there) and is refused."""

SEVERITY_BY_LEVEL: Final[Mapping[str, Severity]] = {"LOW": "baja", "MEDIUM": "media", "HIGH": "alta"}
"""The severity of a RESERVA or a FALTA_INFO is the Council's own confidence (``Level``) in words. A BLOQUEA is always ``bloqueante``; a
CONFIRMA and a SIN_COUNCIL are ``baja`` (they change nothing). The severity is ORDINAL and informative: ``proposed_effect`` never reads it."""

EFFECT: Final[Mapping[AdjVerdict, str | None]] = {
    "BLOQUEA": "RECHAZADO",
    "FALTA_INFO": "INVESTIGACION",
    "RESERVA": "CAUTELA",
    "CONFIRMA": None,
    "SIN_COUNCIL": None,
}
"""The state each verdict would take a selection DOWN to (None: unchanged). Applied as the most conservative of the two (``RANK``)."""

DISSENTING: Final[Mapping[str, frozenset[str]]] = {
    "APPROVE": frozenset({"CONCERN", "REJECT_SIGNAL"}),
    "DOWNGRADE": frozenset({"SUPPORT"}),
    "REJECT": frozenset({"SUPPORT"}),
    "ABSTAIN": frozenset(),
}
"""cd-v1 itself carries no dissent field. What the shadow row DOES carry is the stance each assessment took on the candidate
(``output.assessment``: ``{label: stance}``), and a dissent is an assessment whose stance pulls the other way from the verdict that stood:
a concern or a rejection signal the Council approved over, a support it downgraded or rejected over. An ABSTAIN overrules nobody. A cd-v1
answer read from ``ai.agent_runs`` has no assessments beside it, so its dissents are always empty."""

STANCES: Final = frozenset(get_args(Stance))
LEVELS: Final = frozenset(get_args(Level))
ASSESSMENT_LABELS: Final = frozenset({"match_context", "match_evaluation", "stats_context", "stats_evaluation"})
"""``agents.common.assessment_label`` of every agent x mode: how an assessment is cited (``A:<label>``) and keyed in ``output.assessment``."""
CHANGE_CODES: Final = frozenset({"approve_without_data_in_its_favour", "against_without_a_reference_that_stands"})
"""The ``why`` of every ``contracts.council.Change`` (``output.changes``): the server demoting a verdict to ABSTAIN."""
ESCALATION_RULES: Final = frozenset(get_args(EscalationRule))
REVIEW_MAX_AGE: Final = timedelta(hours=12)
"""How old a shadow verdict may be and still count, by default: the same twelve hours filter 6 gives the reviews it reads, so that the
shadow and decision-v1 are compared on context of the same age. ``max_age=None`` lifts it."""

Key = tuple[int, str, str, Decimal]
LINE_Q: Final = Decimal("0.01")


class UnknownCouncilOutputError(ValueError):
    """A shadow row or a cd-v1 answer this version of the contract does not know. Raised, never guessed around."""


@dataclass(frozen=True, slots=True)
class Source:
    """Where an adjustment was read from: the engine, the review (``ai.pick_reviews.id``) or the run (``ai.agent_runs.id``), the versions."""

    engine: str
    review_id: int | None = None
    run_id: int | None = None
    engine_version: str | None = None
    council_version: str | None = None
    contract: str = CONTRACT
    model: str | None = None
    escalation_rule: str | None = None
    """``E1``..``E7`` when ``router-v1`` sent the selection to Opus (and Opus' verdict is the one that stands, or it was skipped)."""


@dataclass(frozen=True, slots=True)
class Dissent:
    """An agent position the Council set aside: the assessment's label and its stance on the candidate."""

    agent: str
    stance: str


@dataclass(frozen=True, slots=True)
class ContextAdjustment:
    """What the Council said of one selection, typed. No field is a number a decision could compute with."""

    verdict: AdjVerdict
    severity: Severity
    source: Source
    known_at: datetime
    council_verdict: str | None = None
    """The cd-v1 word itself (``APPROVE``...), None when no Council answered."""
    confidence: str | None = None
    """The cd-v1 ``Level`` (``LOW``/``MEDIUM``/``HIGH``), a word; None when no Council answered."""
    factor_codes: tuple[str, ...] = ()
    """The cd-v1 codes the verdict rests on: its drivers (``SignalCode``) then its risks (``RiskCode``), in the Council's order."""
    contradictions: tuple[str, ...] = ()
    """The ``contra-v1`` codes (C01..C08) the server found touching this candidate."""
    evidence_ids: tuple[int, ...] = ()
    dissents: tuple[Dissent, ...] = ()
    server_changes: tuple[str, ...] = ()
    """``contracts.council.check`` demotions to ABSTAIN (``CHANGE_CODES``)."""
    version: str = VERSION

    @classmethod
    def absent(cls, engine: str, *, at: datetime) -> ContextAdjustment:
        """No row of the engine for the selection as of ``at``: the same as a Council that did not answer."""
        return cls("SIN_COUNCIL", "baja", Source(engine=engine), at)

    def as_json(self) -> dict[str, Any]:
        s = self.source
        return {"version": self.version, "verdict": self.verdict, "severity": self.severity, "council_verdict": self.council_verdict,
                "confidence": self.confidence, "factor_codes": list(self.factor_codes), "contradictions": list(self.contradictions),
                "evidence_ids": list(self.evidence_ids), "dissents": [{"agent": d.agent, "stance": d.stance} for d in self.dissents],
                "server_changes": list(self.server_changes), "known_at": self.known_at.isoformat(),
                "source": {"engine": s.engine, "review_id": s.review_id, "run_id": s.run_id, "engine_version": s.engine_version,
                           "council_version": s.council_version, "contract": s.contract, "model": s.model,
                           "escalation_rule": s.escalation_rule}}


# -- parsing ---------------------------------------------------------------------------------------------------------------------------

def _refuse(why: str) -> UnknownCouncilOutputError:
    return UnknownCouncilOutputError(why)


def _codes(values: object, known: Collection[str], what: str) -> tuple[str, ...]:
    if values is None:
        return ()
    if not isinstance(values, list | tuple):
        raise _refuse(f"{what}: not a list")
    out: list[str] = []
    for v in values:
        if not isinstance(v, str) or v not in known:
            raise _refuse(f"{what}: unknown code {v!r}")
        out.append(v)
    return tuple(out)


def _evidence_of_refs(refs: object) -> tuple[int, ...]:
    if refs is None:
        return ()
    if not isinstance(refs, list | tuple):
        raise _refuse("refs: not a list")
    ids: set[int] = set()
    for r in refs:
        ref = parse_ref(r) if isinstance(r, str) else None
        if ref is None:
            raise _refuse("refs: a reference that is not E:/P:/A:")
        if ref.kind == "E":
            ids.add(int(ref.value))
    return tuple(sorted(ids))


def _severity(verdict: AdjVerdict, level: str | None) -> Severity:
    if verdict == "BLOQUEA":
        return "bloqueante"
    if verdict in ("RESERVA", "FALTA_INFO"):
        if level is None or level not in SEVERITY_BY_LEVEL:
            raise _refuse(f"confidence: unknown level {level!r}")
        return SEVERITY_BY_LEVEL[level]
    return "baja"


def map_verdict(council_verdict: str, *, answered: bool) -> AdjVerdict:
    """``VERDICT_MAP`` as a function: an unknown pair raises."""
    key = (council_verdict, "answered" if answered else "unanswered")
    if key not in VERDICT_MAP:
        raise _refuse(f"verdict: {council_verdict!r} ({key[1]}) is not mapped by {VERSION}")
    return VERDICT_MAP[key]


def council_version_of(engine: str, engine_version: object) -> str:
    """The Council part of ``engine_version`` (``ma-v1+match-v2+council-v1+contra-v1+router-v1``), which must be a known one."""
    if not isinstance(engine_version, str):
        raise _refuse("engine_version: missing")
    parts = engine_version.split("+")
    if parts[0] != engine:
        raise _refuse(f"engine_version: does not start with the engine {engine!r}")
    found = [p for p in parts if p.startswith("council-")]
    if len(found) != 1 or found[0] not in COUNCIL_VERSIONS:
        raise _refuse(f"engine_version: council version {found!r} is not known to {VERSION}")
    return found[0]


def _dissents(assessment: object, council_verdict: str) -> tuple[Dissent, ...]:
    if assessment is None:
        return ()
    if not isinstance(assessment, Mapping):
        raise _refuse("assessment: not an object")
    against = DISSENTING[council_verdict]
    out: list[Dissent] = []
    for label in sorted(assessment):
        stance = assessment[label]
        if label not in ASSESSMENT_LABELS:
            raise _refuse(f"assessment: unknown label {label!r}")
        if stance not in STANCES:
            raise _refuse(f"assessment: unknown stance {stance!r}")
        if stance in against:
            out.append(Dissent(str(label), str(stance)))
    return tuple(out)


def from_review(row: Mapping[str, Any]) -> ContextAdjustment:
    """A row of ``ai.pick_reviews`` of ``ma-v1`` or ``ma-v1-h`` (``fbi.ai.orchestrator.review_rows``), strictly. Raises ``UnknownCouncilOutputError``
    on anything this version does not know: the engine, the mode, the status, the verdict, the contract, a code, a level, a version."""
    engine = row.get("engine")
    if engine not in ENGINES:
        raise _refuse(f"engine: {engine!r} is not a Council engine of {VERSION}")
    if row.get("mode") != "shadow":
        raise _refuse(f"mode: {row.get('mode')!r} (the Council engines only run in shadow)")
    status = row.get("status")
    if status != ANSWERED and status not in UNANSWERED:
        raise _refuse(f"status: unknown {status!r}")
    answered = status == ANSWERED
    decision = row.get("decision")
    if not isinstance(decision, str):
        raise _refuse("decision: missing")
    verdict = map_verdict(decision, answered=answered)
    out = row.get("output")
    if not isinstance(out, Mapping):
        raise _refuse("output: not an object")
    if out.get("contract") != CONTRACT:
        raise _refuse(f"output.contract: {out.get('contract')!r} is not {CONTRACT}")
    if out.get("verdict") != decision:
        raise _refuse("output.verdict differs from the row's decision")
    if out.get("engine", engine) != engine:
        raise _refuse("output.engine differs from the row's engine")
    known_at = row.get("reviewed_at")
    if not isinstance(known_at, datetime) or known_at.tzinfo is None:
        raise _refuse("reviewed_at: not an aware timestamp")
    council_version = council_version_of(engine, row.get("engine_version"))
    contradictions = _codes(out.get("contradictions"), CONTRA_CODES, "contradictions")
    escalation = out.get("escalation")
    rule = None
    if escalation is not None:
        if not isinstance(escalation, Mapping):
            raise _refuse("escalation: not an object")
        rule = escalation.get("rule")
        if rule is not None and rule not in ESCALATION_RULES:
            raise _refuse(f"escalation.rule: unknown {rule!r}")
    raw_ids = row.get("evidence_ids") or []
    if not isinstance(raw_ids, list | tuple) or not all(isinstance(i, int) for i in raw_ids):
        raise _refuse("evidence_ids: not a list of ids")
    review_id = row.get("id")
    source = Source(engine=engine, review_id=None if review_id is None else int(review_id), engine_version=str(row["engine_version"]),
                    council_version=council_version, model=None if row.get("model") is None else str(row["model"]),
                    escalation_rule=None if rule is None else str(rule))
    if not answered:
        if out.get("drivers") or out.get("risks"):
            raise _refuse("an unanswered row carries drivers or risks")
        return ContextAdjustment(verdict, "baja", source, known_at, contradictions=contradictions,
                                 evidence_ids=tuple(sorted(set(raw_ids))))
    level = out.get("confidence_level")
    if level not in LEVELS:
        raise _refuse(f"confidence_level: unknown {level!r}")
    drivers = _codes(out.get("drivers"), SIGNAL_CODES, "drivers")
    risks = _codes(out.get("risks"), RISK_CODES, "risks")
    _evidence_of_refs(out.get("refs"))  # the references must be well formed; the ids stored beside them are the row's
    return ContextAdjustment(
        verdict, _severity(verdict, str(level)), source, known_at, council_verdict=decision, confidence=str(level),
        factor_codes=drivers + risks, contradictions=contradictions, evidence_ids=tuple(sorted(set(raw_ids))),
        dissents=_dissents(out.get("assessment"), decision), server_changes=_codes(out.get("changes"), CHANGE_CODES, "changes"))


def from_council_output(payload: str | bytes | dict[str, Any], *, candidate: str, engine: str, known_at: datetime,
                        run_id: int | None = None, council_version: str = "council-v1") -> ContextAdjustment:
    """One candidate's verdict out of a cd-v1 answer (``ai.agent_runs.output`` of a ``council`` or ``escalation`` task), strictly: the answer
    goes through ``fbi.ai.contracts.parse`` (the contract's own validation) and any problem, a missing candidate, an unknown engine or council
    version raises. The answer carries no assessments, so its ``dissents`` are empty; and no contradictions (those are the server's)."""
    if engine not in ENGINES:
        raise _refuse(f"engine: {engine!r} is not a Council engine of {VERSION}")
    if council_version not in COUNCIL_VERSIONS:
        raise _refuse(f"council version {council_version!r} is not known to {VERSION}")
    if known_at.tzinfo is None:
        raise _refuse("known_at: not an aware timestamp")
    parsed = parse(CONTRACT, payload)
    if not isinstance(parsed.value, CouncilOut) or parsed.problems:
        raise _refuse("cd-v1: " + ",".join(parsed.problems or ("invalid",)))
    found = [v for v in parsed.value.verdicts if v.candidate == candidate]
    if not found:
        raise _refuse(f"cd-v1: no verdict for {candidate!r}")
    v = found[0]
    verdict = map_verdict(v.verdict, answered=True)
    return ContextAdjustment(
        verdict, _severity(verdict, v.confidence), Source(engine=engine, run_id=run_id, council_version=council_version), known_at,
        council_verdict=v.verdict, confidence=v.confidence, factor_codes=tuple(v.drivers) + tuple(v.risks),
        evidence_ids=_evidence_of_refs(v.refs))


# -- the effect ------------------------------------------------------------------------------------------------------------------------

def base_state(state: str) -> str:
    """decision-v1's four states: the labels of an approval (PICK_PREMIUM, CANDIDATO_PARLAY, PICK_DEL_DIA) are APROBADO."""
    if state in APPROVED:
        return "APROBADO"
    if state not in RANK:
        raise ValueError(f"unknown decision state {state!r}")
    return state


def proposed_effect(adj: ContextAdjustment, decision_state: str) -> str:
    """The state the adjustment would leave the selection in: the more conservative of decision-v1's state and the verdict's (``EFFECT``).
    Unchanged, the state comes back as it was (a label included); lowered, it is one of the four. It never raises a state."""
    current = base_state(decision_state)
    target = EFFECT[adj.verdict]
    if target is None or RANK[target] >= RANK[current]:
        return decision_state
    return target


# -- reading as of a moment ------------------------------------------------------------------------------------------------------------

ADJUSTMENTS_SQL: Final = """
SELECT DISTINCT ON (r.fixture_id, r.market_key, r.selection, r.line, r.engine)
       r.id, r.engine, r.engine_version, r.fixture_id, r.market_key, r.selection, r.line, r.decision, r.reviewed_at, r.output,
       r.evidence_ids, r.mode, r.status, r.model
  FROM ai.pick_reviews r
 WHERE r.fixture_id = ANY(%(fixtures)s) AND r.engine IN ('ma-v1', 'ma-v1-h') AND r.mode = 'shadow' AND r.reviewed_at <= %(at)s
   AND (%(since)s::timestamptz IS NULL OR r.reviewed_at >= %(since)s)
 ORDER BY r.fixture_id, r.market_key, r.selection, r.line, r.engine, r.reviewed_at DESC, r.id DESC
"""
"""The newest row of each Council engine for each selection, as of ``at``: nothing reviewed after the moment is seen."""


def selection_key(r: Mapping[str, Any]) -> Key:
    return int(r["fixture_id"]), str(r["market_key"]), str(r["selection"]), Decimal(str(r["line"])).quantize(LINE_Q)


@dataclass(frozen=True, slots=True)
class Refused:
    """A shadow row the parser refused, and why (counted and listed, never guessed around)."""

    review_id: int
    engine: str
    key: Key
    why: str


@dataclass(frozen=True, slots=True)
class AsOf:
    """What the Council engines had said by ``at``: the adjustments by (selection, engine) and the rows refused."""

    at: datetime
    adjustments: Mapping[tuple[Key, str], ContextAdjustment] = field(default_factory=dict)
    refused: tuple[Refused, ...] = ()


def adjustments_for(conn: psycopg.Connection[Any], *, at: datetime, fixture_ids: Iterable[int], engines: Sequence[str] = ENGINES,
                    max_age: timedelta | None = REVIEW_MAX_AGE) -> AsOf:
    """The adjustments of the selections of ``fixture_ids`` as of ``at`` (read-only). A row the parser refuses is in ``refused``, not in
    ``adjustments``: the selection then has no adjustment of that engine, it is not read as a SIN_COUNCIL."""
    wanted = [e for e in engines if e in ENGINES]
    if len(wanted) != len(engines):
        raise ValueError(f"engines must be among {ENGINES}")
    fixtures = sorted({int(f) for f in fixture_ids})
    if not fixtures:
        return AsOf(at)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(ADJUSTMENTS_SQL, {"fixtures": fixtures, "at": at, "since": None if max_age is None else at - max_age})
        rows = cur.fetchall()
    found: dict[tuple[Key, str], ContextAdjustment] = {}
    refused: list[Refused] = []
    for r in rows:
        if r["engine"] not in wanted:
            continue
        key = selection_key(r)
        try:
            found[(key, str(r["engine"]))] = from_review(r)
        except UnknownCouncilOutputError as exc:
            refused.append(Refused(int(r["id"]), str(r["engine"]), key, str(exc)))
    return AsOf(at, found, tuple(refused))


# -- the report ------------------------------------------------------------------------------------------------------------------------

DECISIONS_SQL: Final = """
SELECT d.id, d.known_at, d.checkpoint, d.fixture_id, d.market_key, d.selection, d.line, d.state, d.reasons, d.review_id
  FROM intel.decisions d
 WHERE d.decision_version = %(version)s AND d.known_at >= %(since)s AND d.known_at < %(until)s
 ORDER BY d.known_at, d.id
"""
"""The core layer's decisions of the window (``decision-v1`` only: the families never become a pick, so a Council effect on them is moot)."""

HELD: Final = frozenset({"APROBADO", "CAUTELA"})
"""The states a shadow block or hold-back is listed for: the ones a user would have seen as a pick or a pick with caution."""


def _rate(hit: int, n: int) -> float | None:
    return None if n == 0 else round(hit / n, 4)


def shadow_report(conn: psycopg.Connection[Any], *, since: datetime, until: datetime, engines: Sequence[str] = ENGINES,
                  max_age: timedelta | None = REVIEW_MAX_AGE) -> dict[str, Any]:
    """For each decision of ``[since, until)``: decision-v1's state against the state the adjustment of each engine (as of the decision's
    ``known_at``) would propose. Per engine: the counts by verdict, the agreement (the proposed state equals decision-v1's), the confusion
    table (decision-v1's base state x proposed state), the rows the parser refused and the selections an APROBADO or a CAUTELA would have been
    blocked or held back from. Read-only."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DECISIONS_SQL, {"version": DECISION_CORE, "since": since, "until": until})
        decisions = [dict(r) for r in cur.fetchall()]
    by_moment: dict[datetime, list[dict[str, Any]]] = defaultdict(list)
    for d in decisions:
        by_moment[d["known_at"]].append(d)
    per: dict[str, dict[str, Any]] = {e: {"rows": 0, "with_review": 0, "refused": [], "by_verdict": Counter(), "agree": 0, "agree_council": 0,
                                          "n_council": 0, "confusion": defaultdict(Counter), "verdict_x_state": defaultdict(Counter),
                                          "held_back": []} for e in engines}
    for at, rows in sorted(by_moment.items()):
        seen = adjustments_for(conn, at=at, fixture_ids={int(d["fixture_id"]) for d in rows}, engines=engines, max_age=max_age)
        refused = {(x.key, x.engine): x for x in seen.refused}
        for d in rows:
            key = selection_key(d)
            actual = base_state(str(d["state"]))
            for engine in engines:
                acc = per[engine]
                acc["rows"] += 1
                if (key, engine) in refused:
                    x = refused[(key, engine)]
                    acc["refused"].append({"decision_id": int(d["id"]), "review_id": x.review_id, "why": x.why})
                    continue
                adj = seen.adjustments.get((key, engine))
                if adj is None:
                    adj = ContextAdjustment.absent(engine, at=at)
                else:
                    acc["with_review"] += 1
                proposed = base_state(proposed_effect(adj, str(d["state"])))
                acc["by_verdict"][adj.verdict] += 1
                acc["confusion"][actual][proposed] += 1
                acc["verdict_x_state"][adj.verdict][actual] += 1
                agree = proposed == actual
                acc["agree"] += agree
                if adj.verdict != "SIN_COUNCIL":
                    acc["n_council"] += 1
                    acc["agree_council"] += agree
                if actual in HELD and RANK[proposed] < RANK[actual]:
                    acc["held_back"].append({
                        "decision_id": int(d["id"]), "known_at": at.isoformat(), "checkpoint": d["checkpoint"], "fixture_id": key[0],
                        "market_key": key[1], "selection": key[2], "line": str(key[3]), "state": str(d["state"]), "proposed": proposed,
                        "verdict": adj.verdict, "severity": adj.severity, "factor_codes": list(adj.factor_codes),
                        "dissents": [f"{x.agent}:{x.stance}" for x in adj.dissents], "review_id": adj.source.review_id})
    out: dict[str, Any] = {"version": VERSION, "decision_version": DECISION_CORE, "from": since.isoformat(), "to": until.isoformat(),
                           "max_age_hours": None if max_age is None else max_age.total_seconds() / 3600, "decisions": len(decisions),
                           "engines": {}}
    for engine, acc in per.items():
        judged = acc["rows"] - len(acc["refused"])
        out["engines"][engine] = {
            "rows": acc["rows"], "judged": judged, "with_review": acc["with_review"], "refused": len(acc["refused"]),
            "by_verdict": {v: acc["by_verdict"].get(v, 0) for v in VERDICTS},
            "agreement": {"n": judged, "agree": acc["agree"], "rate": _rate(acc["agree"], judged)},
            "agreement_with_council": {"n": acc["n_council"], "agree": acc["agree_council"], "rate": _rate(acc["agree_council"], acc["n_council"])},
            "confusion": {a: dict(sorted(c.items())) for a, c in sorted(acc["confusion"].items())},
            "verdict_x_state": {v: dict(sorted(c.items())) for v, c in sorted(acc["verdict_x_state"].items())},
            "held_back": acc["held_back"], "refused_rows": acc["refused"]}
    return out
