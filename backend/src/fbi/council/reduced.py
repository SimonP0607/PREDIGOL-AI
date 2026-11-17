"""The reduced Council (IA-124, AD-D10 of the plan of the definitive architecture 2026): ``council-reduced-v1``, built on
``council-protocol-v1``. Pure: no row, no model, no clock.

THE DEFAULT IS THE RULES. For every selection of a pass of the shadow the positions of the readers are aggregated by the protocol's own rule
(``protocol.baseline``: the stance's pull times the weight of the agent's record in the family times its novelty against what the model
already reads). That word is the reduced Council's answer unless the three conditions of the judge hold at once (``need``):

    material      a MATERIAL finding of ``council.contradictions`` touches the selection (a contradiction between voices that weigh), or
                  ``contra-v1`` found evidence in conflict on it (C07): the same materiality as the research round (``research_round``)
    value         what is at stake on it clears the decision layer's own bar (``research_round.value_of``: ``ev`` against ``EV_MIN``, or
                  the model's edge against ``EDGE_MIN`` when the pass stored no expected value)
    time          at least ``JUDGE_MIN_MINUTES`` to the kick-off, so three readings can still be made and kept before it

THE JUDGE reads three times (``READINGS``) the same view - the positions, the computed contradictions and the index of the evidence, never
a text from outside directly (``fbi.ai.agents.council.council_view``) - and its word stands only by MAJORITY: two of the three readings
agree on one cd-v1 word (``majority``). A split, or fewer than two answered readings, is an abstention: the rules stand. A majority of
ABSTAIN is an abstention too.

IT ONLY LOWERS. The judge's majority can make the rules' adjustment more conservative and nothing else (``settle``): the final
``ctx-adj-v1`` verdict is the one of the two whose effect (``context_adjustment.EFFECT``) is the lower state, the rules' on a tie. No
number is read or written: the verdicts are words, the rank is decision-v1's own order of states.

THE HAIKU ARM IS NO JUDGE HERE. This version's judge is the Council of ``ma-v1`` (Sonnet, the router's ``complex`` level); the arm
``ma-v1-h`` (``fbi.ai.arms.MULTIAGENT_HAIKU``: Haiku as the judge) is not read as a judge by it (``RETIRED_JUDGES``). Its rows and the
arm itself stay as they are in ``arms-v1``: retiring it from the engines the owner runs is ``FBI_AI_ENGINES`` without ``ma-v1-h``.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.ai.contracts.base import Level
from fbi.council import VERSION as PROTOCOL
from fbi.council import contradictions as contra
from fbi.council import protocol
from fbi.council import research_round as research
from fbi.intel import context_adjustment as ctx
from fbi.intel.decision import RANK

VERSION: Final = "council-reduced-v1"
JUDGE_ENGINE: Final = "ma-v1"
"""The judge of this version: the Council of the multi-agent arm (Sonnet). ``fbi.ai.arms.MULTIAGENT`` (a test holds them equal)."""
RETIRED_JUDGES: Final[tuple[str, ...]] = ("ma-v1-h",)
"""The arm whose Council this version never reads as a judge: Haiku as the judge (``fbi.ai.arms.MULTIAGENT_HAIKU``). It repeated its own
positions differently 25,1 % of the time against 6,5 % for Sonnet (bench C02, 11 Nov 2026)."""
READINGS: Final = 3
MAJORITY: Final = 2
JUDGE_MIN_MINUTES: Final = 30
"""The fewest minutes to the kick-off at which the judge is asked: three readings of Sonnet with their retries end well before the T-15
deadline of the shadow (``fbi.ai.runtime``). Preregistered here."""
WORDS: Final[tuple[str, ...]] = ("APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN")
"""The cd-v1 words a reading can answer for a candidate."""
CONFLICT: Final = research.CONFLICT

Reading = Mapping[str, str | None]
"""One reading of the judge over a match: the cd-v1 word of each candidate it answered (None: no answer for it)."""
Judge = Callable[[int], Reading]
"""What asks the judge: called with the reading's number (0, 1, 2); raises or returns no word for a candidate it could not answer."""


@dataclass(frozen=True, slots=True)
class Need:
    """Whether the judge is wanted for a selection, and why (codes)."""

    wanted: bool
    material: tuple[str, ...]
    reasons: tuple[str, ...]

    def as_json(self) -> dict[str, Any]:
        return {"wanted": self.wanted, "material": list(self.material), "reasons": list(self.reasons)}


def need(sel: contra.Selection, findings: Sequence[contra.Finding], *, minutes_to_kickoff: int | None) -> Need:
    """The three conditions of the judge for one selection. Pure."""
    material = tuple(sorted({f.code for f in findings if f.material and f.candidate == sel.key} | ({CONFLICT} & set(sel.contra))))
    _, basis, at_stake = research.value_of(sel)
    reasons: list[str] = []
    if not material:
        reasons.append("no_material_contradiction")
    if basis is None:
        reasons.append("no_value_measure")
    elif not at_stake:
        reasons.append(f"value_below_{basis}_threshold")
    if minutes_to_kickoff is None:
        reasons.append("kickoff_unknown")
    elif minutes_to_kickoff < JUDGE_MIN_MINUTES:
        reasons.append("too_close_to_kickoff")
    return Need(not reasons, material, tuple(reasons) or ("material_value_and_time",))


@dataclass(frozen=True, slots=True)
class Majority:
    """What three readings say of one candidate: the word two of them agree on, or None (an abstention), with why."""

    word: str | None
    status: str
    """``majority``, ``abstain_majority`` (two or three said ABSTAIN), ``split`` (no two agree) or ``short`` (fewer than two answered)."""
    words: tuple[str | None, ...]
    agree: int = 0

    def as_json(self) -> dict[str, Any]:
        return {"word": self.word, "status": self.status, "words": list(self.words), "agree": self.agree}


def majority(words: Sequence[str | None]) -> Majority:
    """Two of the three readings on one word, or an abstention. A word outside cd-v1 counts as no answer."""
    if len(words) != READINGS:
        raise ValueError(f"the judge reads {READINGS} times: {len(words)} readings")
    clean = tuple(w if w in WORDS else None for w in words)
    answered = [w for w in clean if w is not None]
    if len(answered) < MAJORITY:
        return Majority(None, "short", clean)
    word, n = Counter(answered).most_common(1)[0]
    if n < MAJORITY:
        return Majority(None, "split", clean)
    if word == "ABSTAIN":
        return Majority(None, "abstain_majority", clean, n)
    return Majority(word, "majority", clean, n)


def read_three(judge: Judge, keys: Sequence[str]) -> dict[str, tuple[str | None, ...]]:
    """The three readings of a match, by candidate. A reading that raises answers nothing (fail closed: it is no vote)."""
    out: dict[str, list[str | None]] = {k: [] for k in keys}
    for i in range(READINGS):
        try:
            got = judge(i)
        except Exception:  # a reading that failed is no vote; it never stops the pass
            got = {}
        for k in keys:
            word = got.get(k) if isinstance(got, Mapping) else None
            out[k].append(word if isinstance(word, str) else None)
    return {k: tuple(v) for k, v in out.items()}


def _rank(verdict: ctx.AdjVerdict) -> int:
    target = ctx.EFFECT[verdict]
    return RANK["APROBADO"] + 1 if target is None else RANK[target]


@dataclass(frozen=True, slots=True)
class Outcome:
    """The reduced Council's answer for one selection."""

    key: str
    rules: protocol.Baseline
    need: Need
    judge_status: str
    """``not_needed`` (a condition failed: the rules alone), ``not_asked`` (wanted, but no judge was given: the rules stand), ``asked``."""
    majority: Majority | None
    final: ctx.ContextAdjustment
    source: str
    """``rules`` or ``judge`` (the judge's majority was the more conservative)."""

    @property
    def lowered(self) -> bool:
        return self.source == "judge"

    def as_json(self) -> dict[str, Any]:
        return {"candidate": self.key, "rules": self.rules.as_json(), "need": self.need.as_json(), "judge_status": self.judge_status,
                "majority": None if self.majority is None else self.majority.as_json(), "final": self.final.as_json(),
                "source": self.source, "version": VERSION, "protocol": PROTOCOL}


def _confidence(m: Majority) -> Level:
    return "HIGH" if m.agree == READINGS else "MEDIUM"


def settle(sel: contra.Selection, rules: protocol.Baseline, need_: Need, readings: tuple[str | None, ...] | None, *, at: datetime) -> Outcome:
    """The final adjustment of one selection: the rules' unless the judge was asked and its majority is MORE conservative."""
    base = rules.adjustment
    if not need_.wanted:
        return Outcome(sel.key, rules, need_, "not_needed", None, base, "rules")
    if readings is None:
        return Outcome(sel.key, rules, need_, "not_asked", None, base, "rules")
    m = majority(readings)
    if m.word is None:
        return Outcome(sel.key, rules, need_, "asked", m, base, "rules")
    verdict = ctx.map_verdict(m.word, answered=True)
    if _rank(verdict) >= _rank(base.verdict):
        return Outcome(sel.key, rules, need_, "asked", m, base, "rules")
    level = _confidence(m)
    severity: ctx.Severity = "bloqueante" if verdict == "BLOQUEA" else ctx.SEVERITY_BY_LEVEL[level]
    final = ctx.ContextAdjustment(verdict, severity, ctx.Source(engine=VERSION, engine_version=f"{VERSION}+{JUDGE_ENGINE}"), at,
                                  council_verdict=m.word, confidence=level, factor_codes=base.factor_codes, contradictions=sel.contra,
                                  evidence_ids=base.evidence_ids, dissents=base.dissents)
    return Outcome(sel.key, rules, need_, "asked", m, final, "judge")


@dataclass(frozen=True, slots=True)
class Reduced:
    """The reduced Council over one deliberation of the protocol."""

    deliberation: protocol.Deliberation
    outcomes: tuple[Outcome, ...]
    judge_readings: int
    """How many readings of the judge were asked for the match (0 or ``READINGS``)."""

    def as_json(self) -> dict[str, Any]:
        d = self.deliberation
        return {"version": VERSION, "protocol": PROTOCOL, "shadow": True, "fixture_id": d.fixture_id, "at": d.at.isoformat(),
                "status": d.status, "match_run_id": d.match_run_id, "judge_engine": JUDGE_ENGINE, "retired_judges": list(RETIRED_JUDGES),
                "judge_readings": self.judge_readings, "outcomes": [o.as_json() for o in self.outcomes]}


def reduce(d: protocol.Deliberation, *, judge: Judge | None = None) -> Reduced:
    """The reduced Council over a deliberation (``protocol.deliberate``): the rules for every selection, and the judge - three readings,
    once for the match - only when at least one selection needs it and a judge is given."""
    if d.status != "ok":
        return Reduced(d, (), 0)
    minutes = None if d.kickoff_at is None else int((d.kickoff_at - d.at).total_seconds() // 60)
    needs = {s.selection.key: need(s.selection, s.findings, minutes_to_kickoff=minutes) for s in d.selections}
    wanted = [k for k, n in needs.items() if n.wanted]
    readings: dict[str, tuple[str | None, ...]] = {}
    asked = 0
    if wanted and judge is not None:
        readings = read_three(judge, wanted)
        asked = READINGS
    outcomes = tuple(settle(s.selection, s.baseline, needs[s.selection.key], readings.get(s.selection.key) if judge is not None else None,
                            at=d.at) for s in d.selections)
    return Reduced(d, outcomes, asked)


__all__ = ["CONFLICT", "JUDGE_ENGINE", "JUDGE_MIN_MINUTES", "MAJORITY", "PROTOCOL", "READINGS", "RETIRED_JUDGES", "VERSION", "WORDS", "Judge", "Majority",
           "Need", "Outcome", "Reading", "Reduced", "majority", "need", "read_three", "reduce", "settle"]
