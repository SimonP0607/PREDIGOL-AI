"""The bank of pages labelled by people and the score of the extraction against it (IA-127, plan piece AD-C09, ``page-bank-v1`` under the
preregistered protocol ``AD-C09`` = ``extract-protocol-v1``).

WHY. ``label-bank-v1`` (``fbi.ai.label_bank``) labels pieces of evidence already written: it measures how often what was extracted is
right (precision), never what the page said and nobody extracted (recall). The gate of research v2 (row 17, NO PASA, 23,07 % of v1's
facts) measured one extractor against ANOTHER extractor. Here the reference is a person reading a whole page and writing down every
verifiable claim it makes - subject, type and quote - so that each of the four arms of AD-C05 (``extract-v3`` cut at 700 characters,
``extract-v3`` with the whole text, ``extract-v4``, windows chosen by code) is measured against the same truth.

* **The sample** (``sample``): stratified (club or national team, language of the search, kind of search) and deterministic - the rows of
  each stratum ordered by a hash of the protocol's seed and their id, the quota shared equally (``label_bank.allocate``), a quarter of each
  stratum (rounded up) marked for a second, blind labeller. Same pages in, same sheet out.
* **The labels** (``read_labels``): one row per claim a labeller found (``page_id, labeller, subject, provider_id, claim_type, quote``),
  and one row ``NONE`` for a page read that makes no verifiable claim. A page with no row of a labeller was not labelled by him: it is
  left out, never guessed. A row with a word out of its list is listed and does not count.
* **The reference** (``reference``): one labeller's claims on a single page; on a double page, the claims BOTH labellers wrote (matched
  one to one). A claim only one of them wrote is disputed: it is kept apart and counts neither for nor against an arm.
* **The score** (``score``): per arm, its first 50 claims in the order of the seed checked against the reference (the manual review:
  at least 47 of 50), and its recall with the Wilson interval at the level Bonferroni-corrected for the four arms; precision, recall by
  stratum and by type; the agreement between labellers. ``verdict`` applies the protocol's rule: PASA / NO_PASA / INSUFICIENTE /
  NO_EVALUABLE per arm - it activates nothing.

The truth is the human label, never a model's output, and the labels train nothing. The pages are third-party text, kept as untrusted data
and never published. Pure: no database, no clock (the readers are ``fbi.ai.page_bank_readers``; the gate is ``fbi.ai.extract_protocol``).
"""

from __future__ import annotations

import csv
import io
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Any, Final, get_args

from fbi.ai.contracts.claim import ClaimType
from fbi.ai.intervals import Proportion, wilson
from fbi.ai.label_bank import allocate, rank
from fbi.people.identity.names import alias_key, names_compatible
from fbi.research import protocol

BANK_VERSION: Final = "page-bank-v1"
PROTOCOL: Final = "AD-C09"
PAGES: Final = "pages"
QUOTA: Final = 150
"""Pages of the bank (the protocol's minimum)."""
DOUBLE_SHARE: Final = 0.25
SEED: Final = f"{protocol.PROTOCOLS[PROTOCOL].version}:{protocol.PROTOCOLS[PROTOCOL].seed}"

ARMS: Final[tuple[str, ...]] = ("v3_corte_700", "v3_completo", "v4", "ventanas")
"""The four arms of AD-C05, measured on the same pages. ``ventanas`` is the unified road (``fbi.ai.unified_research``): the one that would
replace v1, so the row of the gate says ``passed`` only for it."""
CANDIDATE_ARM: Final = "ventanas"
REVIEW: Final = 50
"""The manual review: the first 50 claims of an arm in the order of the seed."""
REVIEW_MIN: Final = 47
RECALL_MIN: Final = 0.60
"""The lower bound of the corrected interval of the recall an arm needs."""
AGREEMENT_MIN: Final = 0.80
"""Below this agreement between the two labellers the labels are not a firm reference: NO_EVALUABLE."""
ALPHA: Final = 0.05
Z_CORRECTED: Final = protocol.z(1.0 - ALPHA / (2 * len(ARMS)))
"""The two-sided quantile at the level Bonferroni-corrected for the four arms (1 - 0.05/4): about 2.50."""

CLAIM_TYPES: Final[tuple[str, ...]] = get_args(ClaimType)
LIST_TYPES: Final[dict[str, str]] = {"LIST_OUT": "OUT", "LIST_STARTER": "STARTER"}
"""A list (a line-up, a list of absentees) counts as one claim per player, of the type of its members."""
NONE: Final = "NONE"
LABELLERS: Final = ("a", "b")
LABEL_COLUMNS: Final = ("page_id", "labeller", "subject", "provider_id", "claim_type", "quote", "notes")
PAGE_COLUMNS: Final = ("bank", "id", "stratum", "double", "url", "domain", "title", "published_at", "match", "scope", "language", "topic",
                       "text")


# ── the sample ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Page:
    """A saved page that may be sampled: a stable id (of its canonical address), its stratum and what the sheet shows of it."""

    id: str
    stratum: str
    fields: Mapping[str, Any] = field(default_factory=dict)


def stratum_of(*, national: bool | None, language: str, topic: str) -> str:
    scope = "seleccion" if national else "club"
    lang = language if language in ("es", "en", "pt") else "otro"
    return f"{scope}|{lang}|{topic}"


def sample(pages: Iterable[Page], *, quota: int = QUOTA, seed: str = SEED, double_share: float = DOUBLE_SHARE) -> list[dict[str, Any]]:
    """The sheet's pages: per stratum the lowest ranks up to its allocation, a share of them (at least ``double_share``, rounded up) marked
    ``double`` by a second rank. A repeated id counts once."""
    seen: dict[str, Page] = {}
    for p in pages:
        seen.setdefault(p.id, p)
    strata: dict[str, list[Page]] = defaultdict(list)
    for p in seen.values():
        strata[p.stratum].append(p)
    take = allocate({s: len(v) for s, v in strata.items()}, quota)
    rows: list[dict[str, Any]] = []
    for stratum in sorted(strata):
        chosen = sorted(strata[stratum], key=lambda p: rank(seed, PAGES, p.id))[:take[stratum]]
        doubles = {p.id for p in sorted(chosen, key=lambda p: rank(seed, "double", p.id))[:math.ceil(double_share * len(chosen))]}
        for p in chosen:
            rows.append({"bank": PAGES, "id": p.id, "stratum": p.stratum, "double": p.id in doubles} | dict(p.fields))
    return rows


def sheet(rows: Sequence[Mapping[str, Any]], *, window: Mapping[str, str], seed: str = SEED) -> dict[str, Any]:
    """The JSON of the bank: its pages, the label sheet's columns and words, and the protocol it is measured under."""
    return {"version": BANK_VERSION, "protocol": protocol.stamp(PROTOCOL), "seed": seed, "window": dict(window), "double_share": DOUBLE_SHARE,
            "label_columns": list(LABEL_COLUMNS), "claim_types": [*CLAIM_TYPES, NONE],
            "strata": dict(sorted(Counter(str(r["stratum"]) for r in rows).items())), "pages": [dict(r) for r in rows],
            "untrusted": True, "publish": False, "decides": False,
            "note": "texto de terceros: datos no confiables; no se publica, no entrena nada, no pasa por ningún modelo desde aquí"}


def labels_template(rows: Sequence[Mapping[str, Any]]) -> str:
    """The empty label sheet (CSV): one line per page and labeller it needs, to be replaced by one line per claim found (or NONE)."""
    out = io.StringIO()
    w = csv.writer(out, lineterminator="\n")
    w.writerow(LABEL_COLUMNS)
    for r in rows:
        for who in LABELLERS[:2 if r.get("double") else 1]:
            w.writerow([r["id"], who, "", "", "", "", ""])
    return out.getvalue()


# ── the labels ──────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Fact:
    """One claim of one page: by a labeller, or by an arm."""

    page_id: str
    subject: str
    claim_type: str
    provider_id: int | None = None
    quote: str = ""
    source: str = ""

    def compatible(self, other: Fact) -> bool:
        """The protocol's rule: same page, same type, a compatible subject (the same provider id when both have one; else names that could
        be the same entity, a person's or a team's; two empty subjects - a claim about the match - are compatible)."""
        if self.page_id != other.page_id or self.claim_type != other.claim_type:
            return False
        if self.provider_id is not None and other.provider_id is not None:
            return self.provider_id == other.provider_id
        a, b = alias_key(self.subject), alias_key(other.subject)
        if not a or not b:
            return not a and not b
        return names_compatible([self.subject], [other.subject]) or names_compatible([self.subject], [other.subject], person=False)


def _int(value: Any) -> int | None:
    try:
        return int(str(value).strip()) if str(value or "").strip() else None
    except ValueError:
        return None


def read_labels(text: str) -> tuple[dict[tuple[str, str], list[Fact]], list[dict[str, Any]]]:
    """(page id, labeller) -> the claims he found ([] for a page he marked NONE), and the rows that do not count, with why. A line with
    no type is an unfilled line of the template: it labels nothing."""
    stripped = text.lstrip("﻿").lstrip()
    rows = json.loads(stripped).get("labels") or [] if stripped.startswith("{") else list(csv.DictReader(io.StringIO(stripped)))
    found: dict[tuple[str, str], list[Fact]] = {}
    invalid: list[dict[str, Any]] = []
    for r in rows:
        page = str(r.get("page_id") or "").strip()
        who = str(r.get("labeller") or "").strip().lower()
        kind = str(r.get("claim_type") or "").strip().upper()
        if not kind:
            continue
        if not page or who not in LABELLERS:
            invalid.append({"page_id": page, "labeller": who, "why": "page_or_labeller"})
            continue
        if kind == NONE:
            found.setdefault((page, who), [])
            continue
        if kind not in CLAIM_TYPES:
            invalid.append({"page_id": page, "labeller": who, "claim_type": kind, "why": "claim_type"})
            continue
        found.setdefault((page, who), []).append(Fact(page, str(r.get("subject") or "").strip(), kind, _int(r.get("provider_id")),
                                                      " ".join(str(r.get("quote") or "").split()), f"label:{who}"))
    return found, invalid


def _match(left: Sequence[Fact], right: Sequence[Fact]) -> tuple[list[tuple[Fact, Fact]], list[Fact], list[Fact]]:
    """One-to-one, in order: (pairs, left unmatched, right unmatched)."""
    free = list(right)
    pairs: list[tuple[Fact, Fact]] = []
    alone: list[Fact] = []
    for f in left:
        hit = next((i for i, g in enumerate(free) if f.compatible(g)), None)
        if hit is None:
            alone.append(f)
        else:
            pairs.append((f, free.pop(hit)))
    return pairs, alone, free


@dataclass
class Reference:
    """The human truth of the bank: per labelled page, the claims that count and the ones disputed."""

    pages: dict[str, list[Fact]]
    disputed: dict[str, list[Fact]]
    how: dict[str, str]
    """page -> ``single`` | ``both``."""
    agreement_pairs: int = 0
    agreement_total: int = 0

    @property
    def agreement(self) -> float | None:
        """Dice between labellers on the double pages: 2 x claims both wrote / claims either wrote (1 when both marked NONE everywhere)."""
        if not any(h == "both" for h in self.how.values()):
            return None
        return 1.0 if self.agreement_total == 0 else round(2 * self.agreement_pairs / self.agreement_total, 4)


def reference(rows: Sequence[Mapping[str, Any]], labels: Mapping[tuple[str, str], Sequence[Fact]]) -> Reference:
    """The reference of the bank's pages (``rows``): a page nobody labelled is left out."""
    ref = Reference({}, {}, {})
    for r in rows:
        page = str(r["id"])
        a, b = labels.get((page, "a")), labels.get((page, "b"))
        if a is not None and b is not None:
            pairs, only_a, only_b = _match(a, b)
            ref.pages[page] = [x for x, _ in pairs]
            ref.disputed[page] = [*only_a, *only_b]
            ref.how[page] = "both"
            ref.agreement_pairs += len(pairs)
            ref.agreement_total += len(a) + len(b)
        elif a is not None or b is not None:
            ref.pages[page] = list(a if a is not None else b or [])
            ref.disputed[page] = []
            ref.how[page] = "single"
    return ref


# ── the arms ────────────────────────────────────────────────────────────────────────────────────────────────────────

def read_arms(text: str) -> tuple[dict[str, dict[str, list[Fact]]], list[dict[str, Any]]]:
    """The arms' output, ``{"arms": {arm: {page_id: [{subject, provider_id, claim_type, quote, players}]}}}``: a list claim (``LIST_OUT``,
    ``LIST_STARTER``) becomes one claim per member of ``players`` (each ``{subject, provider_id}``). Unknown arms and types are listed."""
    doc = json.loads(text)
    out: dict[str, dict[str, list[Fact]]] = {}
    invalid: list[dict[str, Any]] = []
    for arm, pages in (doc.get("arms") or {}).items():
        if arm not in ARMS:
            invalid.append({"arm": arm, "why": "arm"})
            continue
        for page, claims in (pages or {}).items():
            got = out.setdefault(arm, {}).setdefault(str(page), [])
            for c in claims or []:
                kind = str(c.get("claim_type") or "").upper()
                if kind in LIST_TYPES:
                    got += [Fact(str(page), str(m.get("subject") or ""), LIST_TYPES[kind], _int(m.get("provider_id")), "", f"arm:{arm}")
                            for m in c.get("players") or []]
                elif kind in CLAIM_TYPES:
                    got.append(Fact(str(page), str(c.get("subject") or ""), kind, _int(c.get("provider_id")),
                                    " ".join(str(c.get("quote") or "").split()), f"arm:{arm}"))
                else:
                    invalid.append({"arm": arm, "page_id": page, "claim_type": kind, "why": "claim_type"})
    return out, invalid


def _corrected(k: int, n: int) -> dict[str, Any]:
    p = Proportion(k, n)
    ci = wilson(k, n, Z_CORRECTED) if n else None
    return p.as_json() | {"ci_corrected": None if ci is None else [round(ci[0], 4), round(ci[1], 4)],
                          "level_corrected": round(1 - ALPHA / len(ARMS), 4)}


def score_arm(arm: str, ref: Reference, system: Mapping[str, Sequence[Fact]], strata: Mapping[str, str], *, seed: str = SEED
              ) -> dict[str, Any]:
    """One arm against the reference, on the labelled pages only."""
    tp = fp = neutral = outside = 0
    found = 0
    judged: list[tuple[str, bool]] = []
    by_stratum: dict[str, Counter[str]] = defaultdict(Counter)
    by_type: dict[str, Counter[str]] = defaultdict(Counter)
    for page, claims in system.items():
        if page not in ref.pages:
            outside += len(claims)
    for page in sorted(ref.pages):
        truth = ref.pages[page]
        claims = list(system.get(page, []))
        pairs, rest, missed = _match(claims, truth)
        _, wrong, _ = _match(rest, ref.disputed.get(page, []))
        s = strata.get(page, "?")
        tp += len(pairs)
        fp += len(wrong)
        neutral += len(rest) - len(wrong)
        found += len(pairs)
        where = {id(f): i for i, f in enumerate(claims)}
        for f, _ in pairs:
            judged.append((f"{page}|{where[id(f)]}", True))
            by_type[f.claim_type]["tp"] += 1
        for f in wrong:
            judged.append((f"{page}|{where[id(f)]}", False))
            by_type[f.claim_type]["fp"] += 1
        for f in missed:
            by_type[f.claim_type]["fn"] += 1
        by_stratum[s]["tp"] += len(pairs)
        by_stratum[s]["fp"] += len(wrong)
        by_stratum[s]["fn"] += len(missed)
    review = sorted(judged, key=lambda j: rank(seed, arm, j[0]))[:REVIEW]
    relevant = sum(len(v) for v in ref.pages.values())

    def pr(c: Counter[str]) -> dict[str, Any]:
        return {"precision": _corrected(c["tp"], c["tp"] + c["fp"]), "recall": _corrected(c["tp"], c["tp"] + c["fn"])}

    return {"arm": arm, "claims": tp + fp + neutral, "true": tp, "false": fp, "disputed_neutral": neutral, "outside_bank": outside,
            "review": {"checked": len(review), "correct": sum(1 for _, ok in review if ok), "needed": REVIEW_MIN, "of": REVIEW},
            "precision": _corrected(tp, tp + fp), "recall": _corrected(found, relevant),
            "by_stratum": {s: pr(c) for s, c in sorted(by_stratum.items())}, "by_type": {t: pr(c) for t, c in sorted(by_type.items())}}


Verdict = str
VERDICTS: Final = ("PASA", "NO_PASA", "INSUFICIENTE", "NO_EVALUABLE")


def verdict(arm: Mapping[str, Any], *, pages: int, double: int, agreement: float | None) -> tuple[Verdict, list[str]]:
    """The protocol's rule for one arm, and why."""
    why: list[str] = []
    if pages < QUOTA:
        why.append(f"{pages} páginas etiquetadas de {QUOTA}")
    if double < math.ceil(DOUBLE_SHARE * pages) or double == 0:
        why.append(f"{double} páginas con doble etiqueta: menos de un cuarto")
    if arm["review"]["checked"] < REVIEW:
        why.append(f"{arm['review']['checked']} afirmaciones juzgables del brazo de {REVIEW}")
    if why:
        return "INSUFICIENTE", why
    if agreement is None or agreement < AGREEMENT_MIN:
        return "NO_EVALUABLE", [f"acuerdo entre etiquetadores {agreement} < {AGREEMENT_MIN}"]
    ok_review = arm["review"]["correct"] >= REVIEW_MIN
    low = (arm["recall"]["ci_corrected"] or [0.0, 0.0])[0]
    ok_recall = low >= RECALL_MIN
    if not ok_review:
        why.append(f"revisión manual {arm['review']['correct']}/{REVIEW} < {REVIEW_MIN}")
    if not ok_recall:
        why.append(f"recuperación: extremo inferior corregido {low} < {RECALL_MIN}")
    return ("PASA" if ok_review and ok_recall else "NO_PASA"), why


def score(rows: Sequence[Mapping[str, Any]], labels: Mapping[tuple[str, str], Sequence[Fact]],
          arms: Mapping[str, Mapping[str, Sequence[Fact]]], *, invalid: Sequence[Mapping[str, Any]] = ()) -> dict[str, Any]:
    """The measurement of the bank: the reference, each arm's score and its verdict. It decides nothing on its own: the verdict becomes a
    row of the gate only through ``fbi.ai.extract_protocol.record`` and only under the owner's signature."""
    ref = reference(rows, labels)
    strata = {str(r["id"]): str(r["stratum"]) for r in rows}
    pages = len(ref.pages)
    double = sum(1 for h in ref.how.values() if h == "both")
    out_arms: dict[str, Any] = {}
    for arm in ARMS:
        if arm not in arms:
            out_arms[arm] = {"arm": arm, "verdict": "INSUFICIENTE", "why": ["sin salidas del brazo"]}
            continue
        s = score_arm(arm, ref, arms[arm], strata)
        v, why = verdict(s, pages=pages, double=double, agreement=ref.agreement)
        out_arms[arm] = s | {"verdict": v, "why": why}
    return {"version": BANK_VERSION, "protocol": protocol.stamp(PROTOCOL), "reference": "la etiqueta humana, nunca la salida de un modelo",
            "pages_in_bank": len(rows), "pages_labelled": pages, "pages_double": double,
            "unlabelled": len(rows) - pages, "reference_claims": sum(len(v) for v in ref.pages.values()),
            "disputed_claims": sum(len(v) for v in ref.disputed.values()),
            "disputed": [{"page_id": f.page_id, "by": f.source, "subject": f.subject, "claim_type": f.claim_type}
                         for v in ref.disputed.values() for f in v],
            "agreement": ref.agreement, "agreement_min": AGREEMENT_MIN, "invalid": list(invalid), "arms": out_arms,
            "candidate_arm": CANDIDATE_ARM, "decides": False}


__all__ = ["ARMS", "BANK_VERSION", "CANDIDATE_ARM", "LABEL_COLUMNS", "QUOTA", "RECALL_MIN", "REVIEW", "REVIEW_MIN", "SEED", "VERDICTS",
           "Fact", "Page", "Reference", "labels_template", "read_arms", "read_labels", "reference", "sample", "score", "score_arm",
           "sheet", "stratum_of", "verdict"]
