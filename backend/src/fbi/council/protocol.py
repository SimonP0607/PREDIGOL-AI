"""The deterministic deliberation of the Council v2 over one match, as of one moment (``council-protocol-v1``), in SHADOW.

``deliberate(conn, fixture_id, at=...)`` assembles, from what the shadow stored and nothing else:

    1. the pass       the newest pass of the shadow over the match known at ``at`` (``ai.match_runs``, run_kind ``shadow``): its
                      candidates by name with the model's numbers, and the ``contra-v1`` contradictions it recorded
    2. positions      the stances of the specialists on each candidate: the ``aa-v1`` evaluations of the Match and the Statistics agents
                      stored over the SAME package (``ai.agent_runs``, shadow, task ``evaluation``, status ok)
    3. weights        each position weighed by its agent version's record in the selection's family (``council.weights``)
    4. the market     each candidate's signals as of ``at`` (``fbi.market.signals``, read-only)
    5. findings       ``council.contradictions`` per candidate
    6. research       ``council.research_round``: whether the match warrants ONE targeted round, and its topics
    7. the baseline   the ``ctx-adj-v1`` adjustment the deterministic layer would propose WITHOUT the judge (``baseline``)
    8. the judge      the Council's actual verdict when the shadow has one (``ai.pick_reviews`` of ``ma-v1`` and ``ma-v1-h``, read by
                      ``context_adjustment.adjustments_for``), and whether the baseline agrees with it

THE BASELINE. Every position pulls by its stance (``STANCE_PULL``) times its weight times its novelty (the share of its drivers the model
does not already read: ``contradictions.novelty``); the score is the sum of the pulls over the sum of the weights of the voices heard (weight
above zero). A cd-v1 word is read off the score (``APPROVE_AT``, ``DOWNGRADE_AT``, ``REJECT_AT``) and mapped by ``ctx-adj-v1``'s own table
(``context_adjustment.map_verdict``); when the match's research round is requested and names the candidate, the information is missing and the
adjustment is at least ``FALTA_INFO`` - the more conservative of the two wins, as everywhere. No voice heard (every weight zero: no version is
promoted) is ``SIN_COUNCIL``: the deterministic layer proposes nothing. The confidence is how much weight was heard (``CONFIDENCE_AT``).

The adjustment carries no number (``ctx-adj-v1``): the score, the weights and the novelty are in the report beside it, for the reader, and
never in the record a decision could read. ``proposed_effect`` lowers a state or leaves it; nothing here can raise one, and nothing here is
read by anything that decides (``tests/unit/test_council_isolation.py``). Read-only: no row is written, no model is called.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Final

import psycopg
from psycopg.rows import dict_row

from fbi.ai.agents.common import assessment_label
from fbi.ai.calendar import day_bounds
from fbi.ai.contracts import parse
from fbi.ai.contracts.assessment import AssessmentOut
from fbi.ai.contracts.base import ASSESSMENT, RISK_CODES, SIGNAL_CODES, Level, parse_ref
from fbi.ai.contracts.mcp import family_of
from fbi.council import VERSION
from fbi.council import contradictions as contra
from fbi.council import research_round as research
from fbi.council import weights as w
from fbi.intel import context_adjustment as ctx
from fbi.intel.decision import RANK
from fbi.market import signals as market_signals

STANCE_PULL: Final[Mapping[str, int]] = {"SUPPORT": 1, "NEUTRAL": 0, "CONCERN": -1, "REJECT_SIGNAL": -2}
"""How hard a stance pulls: a support up by one, a concern down by one, a rejection signal down by two (it says the selection should not be
played, which is twice a reservation). A neutral voice pulls nothing and still counts in the weight heard: it dilutes."""

APPROVE_AT: Final = Decimal("0.5")
"""A score at or above this is an APPROVE (``CONFIRMA``): at least half the weight heard, net, in favour."""
DOWNGRADE_AT: Final = Decimal("-0.5")
"""At or below this, a DOWNGRADE (``RESERVA``): half the weight heard, net, against."""
REJECT_AT: Final = Decimal("-1.5")
"""At or below this, a REJECT (``BLOQUEA``): only reached when rejection signals carry most of the weight heard. Between ``DOWNGRADE_AT`` and
``APPROVE_AT`` the voices are split: an ABSTAIN answered (``FALTA_INFO``)."""
CONFIDENCE_AT: Final[tuple[tuple[Decimal, Level], ...]] = ((Decimal(2), "HIGH"), (Decimal(1), "MEDIUM"))
"""The confidence of the baseline is the weight heard: 2 or more (two promoted voices at least neutral) is HIGH, 1 or more MEDIUM, less LOW."""
SCORE_Q: Final = Decimal("0.0001")

ENGINE: Final = VERSION
"""The ``Source.engine`` and ``Source.contract`` of a baseline adjustment: it is the protocol's, not a Council engine's."""
JUDGES: Final = ctx.ENGINES
EVALUATION_AGENTS: Final = w.SPECIALISTS

PASS_SQL: Final = """
SELECT id, fixture_id, pass_kind, known_at, created_at, package_hash, packet_id, agents, contradictions, candidates
  FROM ai.match_runs
 WHERE fixture_id = %(fixture)s AND run_kind = 'shadow' AND known_at <= %(at)s AND created_at <= %(at)s
 ORDER BY known_at DESC, created_at DESC, id DESC
 LIMIT 1
"""
"""The newest pass of the shadow over the match that existed at ``at``."""

KICKOFF_SQL: Final = "SELECT kickoff_at FROM core.fixtures WHERE id = %(fixture)s"

RUNS_SQL: Final = """
SELECT DISTINCT ON (agent) id, agent, agent_version, output
  FROM ai.agent_runs
 WHERE run_kind = 'shadow' AND task_kind = 'evaluation' AND agent = ANY(%(agents)s) AND status = 'ok' AND output IS NOT NULL
   AND fixture_id = %(fixture)s AND package_hash = %(package)s AND finished_at <= %(at)s
 ORDER BY agent, finished_at DESC, id DESC
"""
"""The newest evaluation of each specialist over the package of the pass, finished by ``at``."""

DAY_SQL: Final = """
SELECT r.fixture_id, f.kickoff_at, max(r.created_at) AS pass_at
  FROM ai.match_runs r JOIN core.fixtures f ON f.id = r.fixture_id
 WHERE r.run_kind = 'shadow' AND f.kickoff_at >= %(start)s AND f.kickoff_at < %(end)s AND r.known_at <= %(at)s AND r.created_at <= %(at)s
 GROUP BY r.fixture_id, f.kickoff_at
 ORDER BY f.kickoff_at, r.fixture_id
"""
"""The matches of a day with a pass of the shadow by ``at``, and the moment the newest of those passes was written: the moment the judge
of that pass spoke (the orchestrator writes the state and the reviews of a pass together)."""


# -- the baseline (pure) ----------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class Baseline:
    adjustment: ctx.ContextAdjustment
    word: str
    """The cd-v1 word the deterministic layer reads off the score (``APPROVE``, ``DOWNGRADE``, ``REJECT``, ``ABSTAIN``)."""
    score: Decimal | None
    weight_heard: Decimal
    reasons: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {"word": self.word, "score": None if self.score is None else str(self.score), "weight_heard": str(self.weight_heard),
                "reasons": list(self.reasons), "adjustment": self.adjustment.as_json()}


def _confidence(heard: Decimal) -> Level:
    for floor, level in CONFIDENCE_AT:
        if heard >= floor:
            return level
    return "LOW"


def _word_of(score: Decimal) -> str:
    if score <= REJECT_AT:
        return "REJECT"
    if score <= DOWNGRADE_AT:
        return "DOWNGRADE"
    if score >= APPROVE_AT:
        return "APPROVE"
    return "ABSTAIN"


def _severity(verdict: ctx.AdjVerdict, level: Level) -> ctx.Severity:
    if verdict == "BLOQUEA":
        return "bloqueante"
    if verdict in ("RESERVA", "FALTA_INFO"):
        return ctx.SEVERITY_BY_LEVEL[level]
    return "baja"


def _more_conservative(a: str, b: str) -> str:
    """Of two cd-v1 words (answered), the one whose ``ctx-adj-v1`` effect is lower; ``a`` on a tie."""
    def rank(word: str) -> int:
        target = ctx.EFFECT[ctx.map_verdict(word, answered=True)]
        return RANK["APROBADO"] + 1 if target is None else RANK[target]
    return b if rank(b) < rank(a) else a


def baseline(sel: contra.Selection, positions: Sequence[contra.Position], *, research_requested: bool, at: datetime) -> Baseline:
    """The adjustment the deterministic layer proposes for one selection, without the judge. Pure."""
    mine = sorted((p for p in positions if p.candidate == sel.key), key=lambda p: (p.agent, p.version, p.run_id))
    heard = [p for p in mine if p.weight > 0]
    weight_heard = sum((p.weight for p in heard), Decimal(0))
    source = ctx.Source(engine=ENGINE, contract=VERSION)
    if weight_heard == 0:
        adj = ctx.ContextAdjustment(ctx.map_verdict("ABSTAIN", answered=False), "baja", source, at, contradictions=sel.contra)
        return Baseline(adj, "ABSTAIN", None, weight_heard, ("no_weighted_voice",))
    pull = sum((p.weight * contra.novelty(p, sel.family) * STANCE_PULL.get(p.stance, 0) for p in heard), Decimal(0))
    score = (pull / weight_heard).quantize(SCORE_Q)
    word = _word_of(score)
    reasons = [f"score_{word.lower()}"]
    if research_requested:
        stronger = _more_conservative(word, "ABSTAIN")
        if stronger != word:
            reasons.append("research_round_requested")
        word = stronger
    verdict = ctx.map_verdict(word, answered=True)
    level = _confidence(weight_heard)
    if word == "APPROVE":
        side = [p for p in heard if p.polarity == "FOR"]
    elif word in ("DOWNGRADE", "REJECT"):
        side = [p for p in heard if p.polarity == "AGAINST"]
    else:
        side = heard
    drivers = tuple(dict.fromkeys(d for p in side for d in p.drivers if d in SIGNAL_CODES))
    risks = tuple(dict.fromkeys(r for p in side for r in p.risks if r in RISK_CODES))
    evidence = sorted({int(ref.value) for p in side for r in p.refs if (ref := parse_ref(r)) is not None and ref.kind == "E"})
    against = ctx.DISSENTING[word]
    dissents = tuple(ctx.Dissent(p.label, p.stance) for p in heard if p.stance in against)
    adj = ctx.ContextAdjustment(verdict, _severity(verdict, level), source, at, council_verdict=word, confidence=level,
                                factor_codes=drivers + risks, contradictions=sel.contra, evidence_ids=tuple(evidence), dissents=dissents)
    return Baseline(adj, word, score, weight_heard, tuple(reasons))


@dataclass(frozen=True, slots=True)
class Agreement:
    engine: str
    status: str
    """``compared``, ``no_judge`` (no row of the engine as of the moment), ``judge_sin_council`` (the engine did not answer) or
    ``baseline_sin_council`` (no voice weighed)."""
    verdict_agrees: bool | None = None
    effect_agrees: bool | None = None
    """Whether the two would take a selection to the same state (``ctx.EFFECT``): RESERVA and CONFIRMA differ, two RESERVAs agree."""

    @property
    def compared(self) -> bool:
        return self.status == "compared"

    def as_json(self) -> dict[str, Any]:
        return {"engine": self.engine, "status": self.status, "verdict_agrees": self.verdict_agrees, "effect_agrees": self.effect_agrees}


def agreement(engine: str, base: ctx.ContextAdjustment, judge: ctx.ContextAdjustment | None) -> Agreement:
    if judge is None:
        return Agreement(engine, "no_judge")
    if judge.verdict == "SIN_COUNCIL":
        return Agreement(engine, "judge_sin_council")
    if base.verdict == "SIN_COUNCIL":
        return Agreement(engine, "baseline_sin_council")
    return Agreement(engine, "compared", base.verdict == judge.verdict, ctx.EFFECT[base.verdict] == ctx.EFFECT[judge.verdict])


# -- reading the pass (pure helpers) -----------------------------------------------------------------------------------------------------

def _dec(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        out = Decimal(str(value))
    except (InvalidOperation, ValueError):
        return None
    return out if out.is_finite() else None


def selections_of(candidates: Any, contradictions: Any) -> list[contra.Selection]:
    """The named candidates of a pass (``ai.match_runs.candidates``) with the ``contra-v1`` codes that touch each. A row without a name (left
    out), of no family, or with a line that is not a number is not a selection the agents spoke of."""
    touching: dict[str, set[str]] = {}
    for c in contradictions if isinstance(contradictions, list) else []:
        if isinstance(c, Mapping) and isinstance(c.get("code"), str):
            for key in c.get("candidates") or []:
                touching.setdefault(str(key), set()).add(str(c["code"]))
    out: list[contra.Selection] = []
    for row in candidates if isinstance(candidates, list) else []:
        if not isinstance(row, Mapping) or not isinstance(row.get("candidate"), str):
            continue
        market = str(row.get("market") or "")
        family = str(row.get("family") or "") or family_of(market) or ""
        line = _dec(row.get("line"))
        if not family or line is None:
            continue
        key = str(row["candidate"])
        out.append(contra.Selection(key, family, market, str(row.get("selection") or ""), line, _dec(row.get("p_model")), _dec(row.get("p_market")),
                                    _dec(row.get("edge")), _dec(row.get("ev")), tuple(sorted(touching.get(key, ())))))
    return sorted(out, key=lambda s: (len(s.key), s.key))


def positions_of(run_id: int, agent: str, version: str, output: Any, selections: Sequence[contra.Selection], book: w.Book
                 ) -> tuple[list[contra.Position], list[w.Weight], str | None]:
    """The positions of one stored evaluation, weighed; the weights used; or a problem code when the run cannot be read as ``aa-v1``."""
    parsed = parse(ASSESSMENT, output if isinstance(output, dict) else {})
    out = parsed.value
    if not isinstance(out, AssessmentOut) or parsed.problems:
        return [], [], f"run_unreadable:{run_id}"
    if out.agent != agent or out.mode != "EVALUATION":
        return [], [], f"run_not_an_evaluation_of_its_agent:{run_id}"
    by_key = {s.key: s for s in selections}
    label = assessment_label(out.agent, out.mode)
    positions: list[contra.Position] = []
    used: dict[tuple[str, str, str], w.Weight] = {}
    for c in out.candidates:
        sel = by_key.get(c.candidate)
        if sel is None:
            continue
        weight = used.setdefault((agent, version, sel.family), book.weight(agent, version, sel.family))
        positions.append(contra.Position(agent, version, label, c.candidate, c.stance, tuple(c.drivers), tuple(c.risks), tuple(c.refs), run_id,
                                         weight.weight))
    return positions, list(used.values()), None


# -- the deliberation -------------------------------------------------------------------------------------------------------------------

@dataclass(frozen=True, slots=True)
class SelectionReport:
    selection: contra.Selection
    positions: tuple[contra.Position, ...]
    market: contra.Market
    findings: tuple[contra.Finding, ...]
    research: research.Verdict
    baseline: Baseline
    judges: Mapping[str, ctx.ContextAdjustment | None]
    agreements: tuple[Agreement, ...]

    def as_json(self) -> dict[str, Any]:
        s = self.selection
        m = self.market
        return {
            "candidate": s.key, "family": s.family, "market_key": s.market_key, "selection": s.selection, "line": str(s.line),
            "model": {"p_model": None if s.p_model is None else str(s.p_model), "p_market": None if s.p_market is None else str(s.p_market),
                      "edge": None if s.edge is None else str(s.edge), "ev": None if s.ev is None else str(s.ev)},
            "contra_v1": list(s.contra),
            "positions": [{"agent": p.agent, "agent_version": p.version, "label": p.label, "stance": p.stance, "drivers": list(p.drivers),
                           "risks": list(p.risks), "refs": list(p.refs), "run_id": p.run_id, "weight": str(p.weight),
                           "novelty": str(contra.novelty(p, s.family))} for p in self.positions],
            "market": {"status": m.status, "movement_points": m.movement_points, "steam_up": m.steam_up, "steam_down": m.steam_down,
                       "stale": m.stale},
            "findings": [f.as_json() for f in self.findings],
            "research": self.research.as_json(),
            "baseline": self.baseline.as_json(),
            "judges": {e: None if a is None else a.as_json() for e, a in self.judges.items()},
            "agreement": [a.as_json() for a in self.agreements],
        }


@dataclass(frozen=True, slots=True)
class Deliberation:
    fixture_id: int
    at: datetime
    status: str
    """``ok``, ``unknown_fixture`` or ``no_shadow_pass``."""
    kickoff_at: datetime | None = None
    match_run_id: int | None = None
    pass_kind: str | None = None
    pass_known_at: datetime | None = None
    package_hash: str | None = None
    weights: tuple[w.Weight, ...] = ()
    selections: tuple[SelectionReport, ...] = ()
    round: research.Round | None = None
    problems: tuple[str, ...] = ()
    refused_judges: tuple[str, ...] = ()
    version: str = VERSION

    def findings(self) -> list[contra.Finding]:
        return [f for s in self.selections for f in s.findings]

    def as_json(self) -> dict[str, Any]:
        return {
            "version": self.version, "shadow": True, "fixture_id": self.fixture_id, "at": self.at.isoformat(), "status": self.status,
            "kickoff_at": None if self.kickoff_at is None else self.kickoff_at.isoformat(),
            "pass": None if self.match_run_id is None else {"match_run_id": self.match_run_id, "pass_kind": self.pass_kind,
                                                            "known_at": None if self.pass_known_at is None else self.pass_known_at.isoformat(),
                                                            "package_hash": self.package_hash},
            "weights": [x.as_json() for x in self.weights],
            "selections": [s.as_json() for s in self.selections],
            "research_round": None if self.round is None else self.round.as_json(),
            "problems": list(self.problems), "refused_judge_rows": list(self.refused_judges),
            "constants": constants(),
        }


def constants() -> dict[str, Any]:
    """Every constant the deliberation read, so that a report says what it was computed with."""
    return {
        "weights": {"version": w.VERSION, "prior_precision": str(w.PRIOR_PRECISION), "prior_strength": w.PRIOR_STRENGTH,
                    "min_weight": str(w.MIN_WEIGHT), "max_weight": str(w.MAX_WEIGHT), "upstream_counts": w.UPSTREAM_COUNTS},
        "contradictions": {"version": contra.VERSION, "market_move_points": contra.MARKET_MOVE_POINTS,
                           "model_knows": {k: sorted(v) for k, v in sorted(contra.MODEL_KNOWS.items())}},
        "research": {"version": research.VERSION, "min_ev": str(research.MIN_EV), "min_edge": str(research.MIN_EDGE),
                     "min_minutes": research.MIN_MINUTES, "topics_max": research.TOPICS_MAX},
        "baseline": {"stance_pull": dict(STANCE_PULL), "approve_at": str(APPROVE_AT), "downgrade_at": str(DOWNGRADE_AT),
                     "reject_at": str(REJECT_AT), "confidence_at": {lvl: str(floor) for floor, lvl in CONFIDENCE_AT}},
    }


def _market(conn: psycopg.Connection[Any], fixture_id: int, sel: contra.Selection, *, at: datetime) -> contra.Market:
    key = (fixture_id, sel.market_key, sel.selection, sel.line)
    got = market_signals.read_signals(conn, key, at=at, p_model=None if sel.p_model is None else float(sel.p_model))
    return contra.Market.unknown() if got is None else contra.Market.of(got)


def deliberate(conn: psycopg.Connection[Any], fixture_id: int, *, at: datetime, book: w.Book | None = None) -> Deliberation:
    """The deterministic deliberation of one match as of ``at``. Read-only; ``book`` may be passed to reuse one read of the weights."""
    if at.tzinfo is None:
        raise ValueError("a deliberation is made at a moment with its time zone")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(KICKOFF_SQL, {"fixture": fixture_id})
        ko = cur.fetchone()
        if ko is None:
            return Deliberation(fixture_id, at, "unknown_fixture")
        kickoff: datetime = ko["kickoff_at"]
        cur.execute(PASS_SQL, {"fixture": fixture_id, "at": at})
        p = cur.fetchone()
        if p is None:
            return Deliberation(fixture_id, at, "no_shadow_pass", kickoff_at=kickoff)
        selections = selections_of(p["candidates"], p["contradictions"])
        runs: list[dict[str, Any]] = []
        if p["package_hash"] is not None:
            cur.execute(RUNS_SQL, {"agents": list(EVALUATION_AGENTS), "fixture": fixture_id, "package": p["package_hash"], "at": at})
            runs = [dict(r) for r in cur.fetchall()]
    book = book or w.read_book(conn, at=at, families={s.family for s in selections})
    positions: list[contra.Position] = []
    weights: dict[tuple[str, str, str], w.Weight] = {}
    problems: list[str] = []
    for r in runs:
        ps, used, problem = positions_of(int(r["id"]), str(r["agent"]), str(r["agent_version"]), r["output"], selections, book)
        positions += ps
        weights.update({(x.agent, x.version, x.family): x for x in used})
        if problem:
            problems.append(problem)
    if p["package_hash"] is None:
        problems.append("pass_without_package_hash")
    elif not runs:
        problems.append("no_evaluation_over_the_package")
    markets = {s.key: _market(conn, fixture_id, s, at=at) for s in selections}
    findings = {s.key: contra.detect(s, positions, markets[s.key]) for s in selections}
    cases = [research.Case(s, findings[s.key], tuple(x for x in positions if x.candidate == s.key)) for s in selections]
    minutes = int((kickoff - at).total_seconds() // 60)
    rnd = research.decide(cases, minutes_to_kickoff=minutes)
    seen = ctx.adjustments_for(conn, at=at, fixture_ids=[fixture_id], max_age=None)
    reports: list[SelectionReport] = []
    verdicts = {v.candidate: v for v in rnd.per_candidate}
    for s in selections:
        key = (fixture_id, s.market_key, s.selection, s.line.quantize(ctx.LINE_Q))
        base = baseline(s, positions, research_requested=rnd.requested and s.key in rnd.candidates, at=at)
        judges: dict[str, ctx.ContextAdjustment | None] = {}
        for engine in JUDGES:
            j = seen.adjustments.get((key, engine))
            judges[engine] = j if j is not None and j.known_at >= p["known_at"] else None
        reports.append(SelectionReport(s, tuple(x for x in positions if x.candidate == s.key), markets[s.key], findings[s.key], verdicts[s.key],
                                       base, judges, tuple(agreement(e, base.adjustment, judges[e]) for e in JUDGES)))
    return Deliberation(fixture_id, at, "ok", kickoff_at=kickoff, match_run_id=int(p["id"]), pass_kind=str(p["pass_kind"]),
                        pass_known_at=p["known_at"], package_hash=p["package_hash"],
                        weights=tuple(x for _, x in sorted(weights.items())), selections=tuple(reports), round=rnd, problems=tuple(problems),
                        refused_judges=tuple(f"{x.review_id}:{x.why}" for x in seen.refused))


# -- the day ----------------------------------------------------------------------------------------------------------------------------

@dataclass(slots=True)
class DayTally:
    fixtures: int = 0
    deliberated: int = 0
    selections: int = 0
    by_kind: Counter[str] = field(default_factory=Counter)
    material_by_kind: Counter[str] = field(default_factory=Counter)
    by_code: Counter[str] = field(default_factory=Counter)
    rounds: int = 0
    topics: Counter[str] = field(default_factory=Counter)
    round_reasons: Counter[str] = field(default_factory=Counter)
    baseline: Counter[str] = field(default_factory=Counter)
    agreement: dict[str, Counter[str]] = field(default_factory=dict)
    statuses: Counter[str] = field(default_factory=Counter)
    problems: Counter[str] = field(default_factory=Counter)

    def add(self, d: Deliberation) -> None:
        self.fixtures += 1
        self.statuses[d.status] += 1
        if d.status != "ok":
            return
        self.deliberated += 1
        self.selections += len(d.selections)
        for f in d.findings():
            self.by_kind[f.kind] += 1
            self.by_code[f.code] += 1
            if f.material:
                self.material_by_kind[f.kind] += 1
        if d.round is not None:
            if d.round.requested:
                self.rounds += 1
                self.topics.update(d.round.topics)
            self.round_reasons.update(d.round.reasons)
        for s in d.selections:
            self.baseline[s.baseline.adjustment.verdict] += 1
            for a in s.agreements:
                c = self.agreement.setdefault(a.engine, Counter())
                c[a.status] += 1
                if a.compared:
                    c["verdict_agrees"] += bool(a.verdict_agrees)
                    c["effect_agrees"] += bool(a.effect_agrees)
        self.problems.update(p.split(":")[0] for p in d.problems)

    def as_json(self) -> dict[str, Any]:
        def rate(n: int, d: int) -> float | None:
            return None if d == 0 else round(n / d, 4)

        agreement = {}
        for engine in JUDGES:
            c = self.agreement.get(engine, Counter())
            n = c["compared"]
            agreement[engine] = {"selections": sum(c[k] for k in ("compared", "no_judge", "judge_sin_council", "baseline_sin_council")),
                                 "compared": n, "no_judge": c["no_judge"], "judge_sin_council": c["judge_sin_council"],
                                 "baseline_sin_council": c["baseline_sin_council"],
                                 "verdict_agrees": c["verdict_agrees"], "verdict_rate": rate(c["verdict_agrees"], n),
                                 "effect_agrees": c["effect_agrees"], "effect_rate": rate(c["effect_agrees"], n)}
        return {"fixtures": self.fixtures, "deliberated": self.deliberated, "statuses": dict(sorted(self.statuses.items())),
                "selections": self.selections,
                "contradictions": {"by_kind": {k: self.by_kind.get(k, 0) for k in contra.KINDS},
                                   "material_by_kind": {k: self.material_by_kind.get(k, 0) for k in contra.KINDS},
                                   "by_code": {k: self.by_code.get(k, 0) for k in contra.CODES}},
                "research_rounds": {"requested": self.rounds, "topics": dict(sorted(self.topics.items())),
                                    "reasons": dict(sorted(self.round_reasons.items()))},
                "baseline": {v: self.baseline.get(v, 0) for v in ctx.VERDICTS},
                "agreement": agreement, "problems": dict(sorted(self.problems.items()))}


def day_report(conn: psycopg.Connection[Any], day: date, *, at: datetime) -> dict[str, Any]:
    """Every match of a Bogotá day with a pass of the shadow by ``at``, each deliberated as of the moment its newest pass was written (never
    past the kick-off): the information the judge of that pass had, so that the baseline and the judge are compared on the same facts, and
    the research round is judged when it could still have been served. The counts of the findings by kind, the rounds that would be
    requested and the agreement of the baseline with each judge. Read-only."""
    start, end = day_bounds(day)
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(DAY_SQL, {"start": start, "end": end, "at": at})
        fixtures = [(int(r["fixture_id"]), r["kickoff_at"], r["pass_at"]) for r in cur.fetchall()]
    tally = DayTally()
    rows: list[dict[str, Any]] = []
    for fixture_id, kickoff, pass_at in fixtures:
        moment = min(at, pass_at, kickoff - timedelta(microseconds=1))
        d = deliberate(conn, fixture_id, at=moment)
        tally.add(d)
        rows.append({"fixture_id": fixture_id, "at": moment.isoformat(), "status": d.status, "selections": len(d.selections),
                     "findings": len(d.findings()), "material": sum(1 for f in d.findings() if f.material),
                     "round": None if d.round is None else {"requested": d.round.requested, "topics": list(d.round.topics)}})
    return {"version": VERSION, "shadow": True, "day": day.isoformat(), "at": at.isoformat(), **tally.as_json(), "fixtures_detail": rows,
            "constants": constants()}


__all__ = ["APPROVE_AT", "DOWNGRADE_AT", "REJECT_AT", "STANCE_PULL", "Agreement", "Baseline", "Deliberation", "SelectionReport", "agreement",
           "baseline", "constants", "day_report", "deliberate", "positions_of", "selections_of"]
