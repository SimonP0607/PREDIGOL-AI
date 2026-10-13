"""What a review may say, and how the server checks it before anything is stored (anti-hallucination).

Every statement in a review is a CLAIM with a type:

    DATA       a fact from the packet - must cite the packet block it comes from (``P:market``,
               ``P:absences.home``...) and every number in it must be in that packet
    NEWS       something reported outside the numbers - must cite evidence ids (``E:123``) that are in the
               packet and not OUTDATED; a claim resting only on rumours is shown as a rumour
    INFERENCE  a conclusion drawn from data or news - shown as an inference, never as a fact
    OPINION    a judgement - shown as one
    UNKNOWN    something the reviewer could not establish - said, not guessed

A claim that breaks its type's rule is refused and listed (``rejected_claims``), not silently dropped.
A decision that rests on nothing left standing is not taken: an APPROVE needs a DATA claim in its favour,
a REJECT or DOWNGRADE a valid claim against; otherwise the review ABSTAINs, with that reason.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from fbi.analyst.agent import _numbers

ClaimType = Literal["DATA", "INFERENCE", "NEWS", "OPINION", "UNKNOWN"]
Decision = Literal["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]
REF = re.compile(r"^(P:[a-z_][a-z_0-9]*(\.[a-z_0-9]+)*|E:\d+)$")
"""``P:h2h`` has a digit: a block name may (9 Oct 2026, the first real briefs cited it and were refused)."""
BLOCKS = frozenset({"fixture", "standings", "stakes", "form", "schedule", "h2h", "elo", "stats", "absences",
                    "lineups", "travel", "market", "models", "quality", "evidence", "candidate", "signals", "cards",
                    "previous", "dossier"})
"""The blocks a claim may cite (``P:<block>``): the packet's, the review's candidate and signals, and the brief's
cards and previous reading (``fbi.ai.brief``)."""


class ClaimOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=3, max_length=240)
    type: ClaimType
    refs: list[str] = Field(default_factory=list, max_length=6)


class ReviewOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    decision: Decision
    confidence: float = Field(ge=0, le=1)
    context_score: float = Field(ge=0, le=1)
    model_score: float = Field(ge=0, le=1)
    market_score: float = Field(ge=0, le=1)
    positive_evidence: list[ClaimOut] = Field(default_factory=list, max_length=8)
    negative_evidence: list[ClaimOut] = Field(default_factory=list, max_length=8)
    uncertainties: list[ClaimOut] = Field(default_factory=list, max_length=8)
    contradictions: list[ClaimOut] = Field(default_factory=list, max_length=6)
    reason: str = Field(min_length=3, max_length=400)
    minimum_playable_odds: float | None = Field(default=None, ge=1.0, le=1000)
    fair_odds: float | None = Field(default=None, ge=1.0, le=1000)


def _claim_schema() -> dict[str, Any]:
    return {"type": "object", "additionalProperties": False, "required": ["text", "type", "refs"],
            "properties": {"text": {"type": "string", "maxLength": 240},
                           "type": {"type": "string", "enum": ["DATA", "INFERENCE", "NEWS", "OPINION", "UNKNOWN"]},
                           "refs": {"type": "array", "maxItems": 6, "items": {"type": "string"}}}}


REVIEW_SCHEMA: dict[str, Any] = {
    "type": "object", "additionalProperties": False,
    "required": ["decision", "confidence", "context_score", "model_score", "market_score", "positive_evidence",
                 "negative_evidence", "uncertainties", "contradictions", "reason", "minimum_playable_odds", "fair_odds"],
    "properties": {
        "decision": {"type": "string", "enum": ["APPROVE", "DOWNGRADE", "REJECT", "ABSTAIN"]},
        "confidence": {"type": "number", "minimum": 0, "maximum": 1},
        "context_score": {"type": "number", "minimum": 0, "maximum": 1},
        "model_score": {"type": "number", "minimum": 0, "maximum": 1},
        "market_score": {"type": "number", "minimum": 0, "maximum": 1},
        "positive_evidence": {"type": "array", "maxItems": 8, "items": _claim_schema()},
        "negative_evidence": {"type": "array", "maxItems": 8, "items": _claim_schema()},
        "uncertainties": {"type": "array", "maxItems": 8, "items": _claim_schema()},
        "contradictions": {"type": "array", "maxItems": 6, "items": _claim_schema()},
        "reason": {"type": "string", "maxLength": 400},
        "minimum_playable_odds": {"type": ["number", "null"]},
        "fair_odds": {"type": ["number", "null"]},
    },
}

GROUPS = ("positive_evidence", "negative_evidence", "uncertainties", "contradictions")


@dataclass
class Checked:
    review: ReviewOut
    rejected: list[dict[str, str]] = field(default_factory=list)
    decision_changed: str | None = None


def _corpus_numbers(packet_content: dict[str, Any], extra: dict[str, Any]) -> set[float]:
    corpus = json.dumps(packet_content, default=str) + " " + json.dumps(extra, default=str)
    return {float(x) for x in re.findall(r"-?\d+(?:\.\d+)?", corpus)}


def _unverified(text: str, stored: set[float]) -> list[str]:
    out = []
    for n in sorted(_numbers(text)):
        try:
            v = float(n)
        except ValueError:
            continue
        if v.is_integer() and 0 <= v <= 10:
            continue
        decimals = len(n.split(".", 1)[1]) if "." in n else 0
        tol = 0.5 * 10 ** (-decimals)
        if any(abs(s - v) <= tol or abs(s * 100 - v) <= tol for s in stored):
            continue
        out.append(n)
    return out


def corpus_numbers(packet_content: dict[str, Any], extra: dict[str, Any] | None = None) -> set[float]:
    """Every number a claim about this packet may use."""
    return _corpus_numbers(packet_content, extra or {})


def refused(c: ClaimOut, *, stored: set[float], evidence_status: dict[int, str]) -> str | None:
    """Why a claim cannot stand (its references, its type's rule, its numbers), or None when it can."""
    refs = [r.strip() for r in c.refs]
    bad_ref = next((r for r in refs if not REF.match(r)), None)
    if bad_ref is not None:
        return f"unknown reference {bad_ref!r}"
    p_refs = [r for r in refs if r.startswith("P:")]
    e_refs = [int(r[2:]) for r in refs if r.startswith("E:")]
    if any(r[2:].split(".")[0] not in BLOCKS for r in p_refs):
        return "cites a packet block that does not exist"
    missing = [e for e in e_refs if e not in evidence_status]
    if missing:
        return f"cites evidence not given: {missing}"
    if c.type == "DATA":
        if not p_refs:
            return "a DATA claim must cite the packet"
        figures = _unverified(c.text, stored)
        if figures:
            return f"numbers not in the packet: {', '.join(figures)}"
    if c.type == "NEWS":
        if not e_refs:
            return "a NEWS claim must cite evidence"
        if all(evidence_status[e] == "OUTDATED" for e in e_refs):
            return "rests only on outdated evidence"
    return None


def check(review: ReviewOut, *, packet_content: dict[str, Any], evidence_status: dict[int, str],
          extra: dict[str, Any] | None = None) -> Checked:
    """Validate every claim against the packet and the evidence the review was given; drop the invalid
    ones (listed); then decide whether the decision still has a basis."""
    stored = _corpus_numbers(packet_content, extra or {})
    rejected: list[dict[str, str]] = []
    kept: dict[str, list[ClaimOut]] = {g: [] for g in GROUPS}
    for group in GROUPS:
        for c in getattr(review, group):
            why = refused(c, stored=stored, evidence_status=evidence_status)
            if why is not None:
                rejected.append({"group": group, "text": c.text, "why": why})
                continue
            kept[group].append(ClaimOut(text=" ".join(c.text.split()), type=c.type, refs=[r.strip() for r in c.refs]))
    cleaned = review.model_copy(update=kept)
    changed: str | None = None
    if cleaned.decision == "APPROVE" and not any(c.type == "DATA" for c in cleaned.positive_evidence):
        changed = "APPROVE without a verified DATA claim in its favour"
    elif cleaned.decision in ("REJECT", "DOWNGRADE") and not (cleaned.negative_evidence or cleaned.uncertainties
                                                             or cleaned.contradictions):
        changed = f"{cleaned.decision} without a verified claim against"
    if changed:
        cleaned = cleaned.model_copy(update={"decision": "ABSTAIN", "reason": f"ABSTAIN: {changed}."[:400]})
    return Checked(cleaned, rejected, changed)


def rumour_only(claim: ClaimOut, evidence_status: dict[int, str]) -> bool:
    ids = [int(r[2:]) for r in claim.refs if r.startswith("E:")]
    return bool(ids) and all(evidence_status.get(i) == "RUMOR" for i in ids)
