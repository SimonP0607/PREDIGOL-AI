"""Controlled learning (IA-139, AD-K07 of the plan of the definitive architecture 2026): ``proposals-v1``. The system PROPOSES a change
with its evidence; only the owner's signature lets it be applied, and applying it is a new version with its way back.

THE KINDS (closed):

    umbral               a threshold of a version (``threshold:<module>.<NAME>``) - lowering one is never proposed by the system
    peso_fuente          the weight of a source (``source:<key>``)
    promocion_capacidad  a capability (``capability:<key>``) or a validated cell of the board (``validation:<layer>/<family>/<market>``)
    retirada             a redundant writer or store (``writer:<module>``, ``store:<schema.table>``), AD-K06: its tables are kept

THE THREE SAFEGUARDS, in code and in the database (revision 0165):

1. A proposal changes nothing. No job, route or agent applies one: this package is imported by no module of ``src/fbi`` (a guard,
   ``tests/unit/test_proposals.py``), and an application row (``ai.change_applications``) cannot exist without the owner's ``firmada``
   signature of the same proposal, bound to the evidence hash the owner saw.
2. The evidence is figures and references, never a third party's text: ``problems`` refuses a long string, a key that carries text
   (``TEXT_KEYS``) and a reference to a table of third parties' text (``UNTRUSTED``). So an outside text that asks to change a threshold
   cannot become a proposal - it is not evidence, and the generator (``from_board``) reads only the board's numbers and verdicts.
3. No proposal moves a probability: a change that names one is refused here and by the database; a ``retirada`` cannot be signed until
   its parity was compared (``parity = igual``); every promotion keeps ``rollback_to`` (the version in force).

Pure: no database, no clock (``fbi.proposals.store`` reads and writes; ``scripts/ia_proposals.py`` is the owner's command)."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, Literal

VERSION: Final = "proposals-v1"
Json = dict[str, Any]
Kind = Literal["umbral", "peso_fuente", "promocion_capacidad", "retirada"]
KINDS: Final[tuple[str, ...]] = ("umbral", "peso_fuente", "promocion_capacidad", "retirada")
TARGETS: Final[Mapping[str, tuple[str, ...]]] = {
    "umbral": ("threshold",), "peso_fuente": ("source",), "promocion_capacidad": ("capability", "validation"),
    "retirada": ("writer", "store"),
}
TARGET: Final = re.compile(r"^(threshold|source|capability|validation|writer|store):[A-Za-z0-9_.:/*-]{1,160}$")
PROBABILITY_KEYS: Final = frozenset({"p", "probability", "probabilities", "p_model", "p_judged", "p_market", "prob"})
"""Keys a change may never carry (revision 0165 refuses the same: ``change_proposals_no_probability``)."""
TEXT_KEYS: Final = frozenset({"text", "texto", "content", "snippet", "quote", "body", "title", "headline", "summary", "prompt", "message"})
"""Keys of the evidence that would carry someone's words: refused at any depth."""
UNTRUSTED: Final = frozenset({"ai.evidence", "ai.research_cache", "news.items", "news.story_texts", "news.stories"})
"""Tables of third parties' text: never a reference of a proposal's evidence."""
MAX_STRING: Final = 160
REASON_MAX: Final = 600
SIGNATURE_MIN: Final = 10
SIGNATURE_MAX: Final = 600
BOARD_VERSION: Final = "board-v1"
SIGNED: Final = "firmada"
REJECTED: Final = "rechazada"


def evidence_hash(evidence: Mapping[str, Any], refs: Sequence[Mapping[str, Any]]) -> str:
    """sha256 of the canonical JSON of the evidence and its references: what the owner signs is bound to it."""
    doc = {"evidence": evidence, "refs": list(refs)}
    return hashlib.sha256(json.dumps(doc, sort_keys=True, separators=(",", ":"), ensure_ascii=False, default=str).encode()).hexdigest()


@dataclass(frozen=True, slots=True)
class Proposal:
    kind: str
    target: str
    current_version: str
    proposed_version: str
    change: Json
    evidence: Json
    evidence_refs: tuple[Json, ...]
    reason: str
    proposed_by: Literal["system", "owner"] = "system"
    version: str = VERSION

    @property
    def rollback_to(self) -> str:
        return self.current_version

    @property
    def hash(self) -> str:
        return evidence_hash(self.evidence, self.evidence_refs)


def _walk(x: Any, path: str = "") -> Iterable[tuple[str, Any]]:
    if isinstance(x, Mapping):
        for k, v in x.items():
            yield f"{path}.{k}", k
            yield from _walk(v, f"{path}.{k}")
    elif isinstance(x, list | tuple):
        for i, v in enumerate(x):
            yield from _walk(v, f"{path}[{i}]")
    else:
        yield path, x


def problems(p: Proposal) -> list[str]:
    """Why ``p`` may not be registered (empty: it may). Pure."""
    out: list[str] = []
    if p.kind not in KINDS:
        return [f"unknown kind {p.kind!r}: one of {', '.join(KINDS)}"]
    m = TARGET.match(p.target)
    if m is None or m.group(1) not in TARGETS[p.kind]:
        out.append(f"a {p.kind} names {' or '.join(t + ':' for t in TARGETS[p.kind])}<...>, not {p.target!r}")
    if not p.current_version or not p.proposed_version or p.current_version == p.proposed_version:
        out.append("a proposal is a NEW version: proposed_version differs from current_version (kept as rollback_to)")
    if p.proposed_by not in ("system", "owner"):
        out.append(f"proposed_by is 'system' or 'owner', not {p.proposed_by!r}")
    if not p.reason.strip() or len(p.reason) > REASON_MAX:
        out.append(f"a proposal carries its reason (1 to {REASON_MAX} characters)")
    keys = {str(k).lower() for _, k in _walk(p.change) if isinstance(k, str)} | {str(k).lower() for k in p.change}
    if keys & PROBABILITY_KEYS:
        out.append(f"no proposal moves a probability: the change names {sorted(keys & PROBABILITY_KEYS)}")
    if not p.evidence:
        out.append("a proposal carries its evidence")
    if not p.evidence_refs:
        out.append("a proposal carries at least one reference of its evidence")
    for path, value in [*_walk(p.evidence, "evidence"), *_walk(list(p.evidence_refs), "refs")]:
        if path.rsplit(".", 1)[-1].lower() in TEXT_KEYS:
            out.append(f"the evidence carries figures and references, not words: {path}")
        if isinstance(value, str) and len(value) > MAX_STRING:
            out.append(f"the evidence carries figures and references, not text ({len(value)} characters at {path})")
    for ref in p.evidence_refs:
        if str(ref.get("table", "")).lower() in UNTRUSTED:
            out.append(f"a third party's text is never evidence of a proposal: {ref.get('table')}")
    if p.kind == "umbral" and p.proposed_by == "system" and p.change.get("direction") == "lower":
        out.append("the system never proposes to lower a threshold")
    return sorted(set(out))


def sign_problems(p: Proposal, decision: str, signature: str, *, seen_hash: str) -> list[str]:
    """Why the owner's decision on ``p`` may not be recorded (empty: it may)."""
    out: list[str] = []
    if decision not in (SIGNED, REJECTED):
        out.append(f"the decision is {SIGNED!r} or {REJECTED!r}, not {decision!r}")
    if not SIGNATURE_MIN <= len(signature.strip()) <= SIGNATURE_MAX:
        out.append(f"the owner signs in their own words ({SIGNATURE_MIN} to {SIGNATURE_MAX} characters)")
    if seen_hash != p.hash:
        out.append("the evidence is not the one the owner saw: sign what was shown")
    if decision == SIGNED and p.kind == "retirada" and p.evidence.get("parity") != "igual":
        out.append("a retirement is signed only after its parity was compared (evidence.parity = 'igual')")
    return out


@dataclass(frozen=True, slots=True)
class Row:
    """A registered proposal and what happened to it, as the store reads it."""

    id: int
    proposal: Proposal
    decision: str | None = None
    applied: tuple[str, ...] = field(default_factory=tuple)

    @property
    def status(self) -> str:
        if "revertida" in self.applied:
            return "revertida"
        if "aplicada" in self.applied:
            return "aplicada"
        if self.decision == SIGNED:
            return "firmada"
        if self.decision == REJECTED:
            return "rechazada"
        return "pendiente_de_firma"


def from_board(board: Mapping[str, Any], *, period: Mapping[str, str]) -> list[Proposal]:
    """The promotions the validation board (``board-v1``, AD-K02) supports: one per cell whose verdict is VALIDADO and whose three checks
    all hold, with the cell's figures as its evidence. Nothing else of the board is read - no notice, no word - so no text can make one."""
    if board.get("version") != BOARD_VERSION:
        return []
    stamp = board.get("protocol")
    protocol_ref = ({"protocol": stamp.get("protocol"), "version": stamp.get("version"), "fingerprint": stamp.get("fingerprint")}
                    if isinstance(stamp, Mapping) else {})
    out: list[Proposal] = []
    for cell in board.get("cells") or ():
        if not isinstance(cell, Mapping) or cell.get("verdict") != "VALIDADO":
            continue
        checks = cell.get("checks")
        if not isinstance(checks, Mapping) or not all(checks.get(k) is True for k in ("supera_al_mercado", "calibrada", "supera_la_vara")):
            continue
        layer, family, market = (str(cell.get(k, "")) for k in ("layer", "family", "market"))
        if not all(re.fullmatch(r"[A-Za-z0-9_.*-]{1,40}", x) for x in (layer, family, market)):
            continue
        evidence = {"board": BOARD_VERSION, "sample": int(cell.get("sample") or 0), "needed": int(cell.get("needed") or 0),
                    "days": int(cell.get("days") or 0), "ece": (cell.get("calibration") or {}).get("ece"),
                    "log_loss_diff_high": (cell.get("log_loss") or {}).get("high"), "clv_low": (cell.get("clv") or {}).get("low"),
                    "clv_vara_high": (cell.get("clv") or {}).get("vara_high"), "bonferroni_level": (board.get("bonferroni") or {}).get("level"),
                    "period": dict(period), **({"protocol": protocol_ref} if protocol_ref else {})}
        refs = ({"table": "intel.selection_evaluations", "layer": layer, "family": family, "market": market, **dict(period)},)
        out.append(Proposal("promocion_capacidad", f"validation:{layer}/{family}/{market}", "en_sombra", "lista_para_revision",
                            {"from": "en_sombra", "to": "lista_para_revision"}, evidence, refs,
                            f"board-v1: VALIDADO en {layer}/{family}/{market} con {evidence['sample']} selecciones; la firma del dueño decide"))
    return out


VERDICT_STAGE_FROM: Final = "en_sombra"
VERDICT_STAGE_TO: Final = "lista_para_revision"
VERDICT_FIGURES: Final = ("n", "mean", "low", "high", "adjusted_p")
DESCRIPTIVE: Final = frozenset({"EXP-E7", "EXP-E8"})
"""The experiments whose protocol says «descriptivo»: their table is measured, not won, so a verdict of success proposes no promotion."""


def from_verdicts(rows: Iterable[Mapping[str, Any]]) -> list[Proposal]:
    """The proposals the verdicts of the plan's experiments support (RP-8.4): one per verdict of SUCCESS (``exito``), with its figures, the protocol it stood on
    (version and fingerprint) and its thresholds as evidence, and the verdict itself as its reference. An abandonment or an «insufficient» verdict proposes nothing:
    there is nothing to promote, and neither does a DESCRIPTIVE experiment (``DESCRIPTIVE``: its table is measured, not won). Only numbers, versions and fingerprints are read from a row - never its reason or its population text - so no text can make one.
    A proposal changes nothing: it moves a capability from ``en_sombra`` to ``lista_para_revision`` and waits for the owner's signature, and it never names a
    probability or lowers a threshold (``problems`` refuses both)."""
    out: list[Proposal] = []
    for row in rows:
        experiment = str(row.get("experiment", ""))
        if row.get("verdict") != "exito" or not re.fullmatch(r"EXP-E[0-9]{1,2}", experiment) or experiment in DESCRIPTIVE:
            continue
        figures = {k: row.get(k) for k in VERDICT_FIGURES if isinstance(row.get(k), int | float) and not isinstance(row.get(k), bool)}
        thresholds = {str(k): v for k, v in dict(row.get("thresholds") or {}).items() if isinstance(v, int | float) and not isinstance(v, bool)}
        population = {str(k): v for k, v in dict(row.get("population") or {}).items() if isinstance(v, int | float | str) and not isinstance(v, bool) and len(str(v)) <= 80
                      and str(k).lower() not in TEXT_KEYS}
        evidence = {"verdict_id": int(row.get("id") or 0), "experiment": experiment, "protocol": {"version": str(row.get("protocol_version", "")),
                    "fingerprint": str(row.get("protocol_fingerprint", ""))}, "figures": figures, "thresholds": thresholds, "population": population,
                    "computed_at": str(row.get("computed_at", ""))}
        refs = ({"table": "analytics.experiment_verdicts", "id": int(row.get("id") or 0), "experiment": experiment},)
        out.append(Proposal("promocion_capacidad", f"capability:{experiment.lower()}", VERDICT_STAGE_FROM, VERDICT_STAGE_TO,
                            {"from": VERDICT_STAGE_FROM, "to": VERDICT_STAGE_TO, "experiment": experiment}, evidence, refs,
                            f"{experiment}: veredicto de éxito con {int(figures.get('n') or 0)} partidos, con su protocolo y sus umbrales fijados antes de los datos; la firma del dueño decide"))
    return out


__all__ = ["BOARD_VERSION", "KINDS", "PROBABILITY_KEYS", "REJECTED", "SIGNED", "TARGETS", "TEXT_KEYS", "UNTRUSTED", "VERSION", "Proposal",
           "Row", "evidence_hash", "from_board", "problems", "sign_problems"]
