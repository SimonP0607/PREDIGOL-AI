"""The deterministic layer of the battery: what PrediGol's own code does with each attack, with no model in it (rule 4 of ``fbi.ai.battery``).

Three things are checked for every case, and they cost nothing:

* what ``fbi.ai.untrusted`` does to the text: it raises the flags the attack is written to raise (``expect``), the text that was meant to
  stay hidden does not survive (``hidden``), the words that were disguised can be read plain (``phrase``), and nothing it hands on holds an
  invisible character, an address or the syntax of a link;
* that the request keeps the text inside its own string: the request is JSON, the text is found whole in one string of it, and the request
  has exactly the keys of the clean one - an attack that breaks out of its string would add some;
* that the clean bases raise nothing: a flag that goes off on clean data is a flag nobody reads.

A defect found here is a defect of PrediGol, not of a model, and it fails the gate like a confirmed case does.
"""

from __future__ import annotations

import json
import unicodedata
from collections.abc import Iterator, Sequence
from dataclasses import dataclass
from typing import Any, Final

from fbi.ai.battery import MIN_CASES, TARGETS
from fbi.ai.battery.corpus import CASES, check_sizes, request_for, target
from fbi.ai.battery.model import Case
from fbi.ai.providers.base import JsonRequest
from fbi.ai.untrusted import sanitize

MAX_CHARS: Final = 4000
"""The cap given to ``sanitize``: far above any text of the corpus, so that truncation is never what is being measured."""
CLEAN_FLAGS: Final = frozenset({"instruction_like", "mixed_script", "invisible", "control"})
"""Flags that must not go off on the data of a clean base."""
INVISIBLE: Final = ("Cc", "Cf", "Cs", "Co", "Cn")


@dataclass(frozen=True, slots=True)
class Finding:
    subject: str
    """The case or base the finding is about."""
    check: str
    detail: str

    def as_json(self) -> dict[str, str]:
        return {"subject": self.subject, "check": self.check, "detail": self.detail}


@dataclass(frozen=True, slots=True)
class OfflineReport:
    checked: dict[str, int]
    findings: tuple[Finding, ...]

    @property
    def ok(self) -> bool:
        return not self.findings

    def as_json(self) -> dict[str, Any]:
        return {"verdict": "PASA" if self.ok else "NO PASA", "checked": self.checked,
                "findings": [f.as_json() for f in self.findings]}


def leaves(value: Any) -> Iterator[str]:
    """Every string of a parsed JSON, keys excluded."""
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for v in value.values():
            yield from leaves(v)
    elif isinstance(value, list):
        for v in value:
            yield from leaves(v)


def key_paths(value: Any, prefix: tuple[str, ...] = ()) -> Iterator[tuple[str, ...]]:
    """The paths of the keys of a parsed JSON, a list index written ``*``: the SHAPE of the document, not its length or its text."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield (*prefix, k)
            yield from key_paths(v, (*prefix, k))
    elif isinstance(value, list):
        for v in value:
            yield from key_paths(v, (*prefix, "*"))


def documents(request: JsonRequest) -> list[Any]:
    """The JSON documents a request carries in its user message: the message, or the parts of its other layout."""
    texts = [request.user] if request.split is None else [request.user, *request.split]
    return [json.loads(t) for t in texts]


def check_text(case: Case) -> list[Finding]:
    """What ``fbi.ai.untrusted`` does to the text of a case."""
    found: list[Finding] = []
    block = sanitize(case.text, origin="battery", max_chars=MAX_CHARS)
    for flag in case.attack.expect:
        if flag not in block.flags:
            found.append(Finding(case.id, "flag_missing", f"the text was written to raise {flag!r} and the flags are {list(block.flags)}"))
    if case.hidden and case.hidden.casefold() in block.text.casefold():
        found.append(Finding(case.id, "hidden_survives", f"{case.hidden!r} is still in the text a model would read"))
    if case.phrase and case.phrase.casefold() not in block.text.casefold():
        found.append(Finding(case.id, "phrase_lost", f"{case.phrase!r} cannot be read in the text a model would read"))
    if any(unicodedata.category(ch) in INVISIBLE for ch in block.text):
        found.append(Finding(case.id, "invisible_left", "an invisible or control character is still in the text"))
    lowered = block.text.casefold()
    if "http://" in lowered or "https://" in lowered or "www." in lowered or "](" in lowered:
        found.append(Finding(case.id, "link_left", "an address or the syntax of a link is still in the text"))
    if block.as_block().get("untrusted") is not True or not block.origin:
        found.append(Finding(case.id, "not_labelled", "the block does not say that it is untrusted data and where it comes from"))
    return found


def check_request(case: Case, *, native: bool = False) -> list[Finding]:
    """That the request keeps the text of a case inside its own string, and nothing else changes."""
    clean = request_for(case.target, case.base, native=native)
    attacked = request_for(case.target, case.base, case, native=native)
    found: list[Finding] = []
    try:
        docs, base_docs = documents(attacked), documents(clean)
    except ValueError:
        return [Finding(case.id, "not_json", "the user message of the request is not JSON")]
    if len(docs) != len(base_docs):
        return [Finding(case.id, "layout", "the request has another layout than the clean one")]
    door = target(case.target).door
    if door is None:
        if not any(case.text in leaf for doc in docs for leaf in leaves(doc)):
            found.append(Finding(case.id, "text_not_whole", "the text is not found, whole, in one string of the request"))
    else:
        found += [Finding(case.id, check, detail) for check, detail in door(case, attacked, clean)]
    extra = sorted({"/".join(p) for d, b in zip(docs, base_docs, strict=True) for p in set(key_paths(d)) - set(key_paths(b))})
    if extra:
        found.append(Finding(case.id, "keys_added", f"the request has keys the clean one has not: {extra[:6]}"))
    if (attacked.system, attacked.schema, attacked.schema_name) != (clean.system, clean.schema, clean.schema_name):
        found.append(Finding(case.id, "prompt_changed", "the system prompt or the schema is not the clean request's"))
    return found


def check_bases(names: Sequence[str], *, native: bool = False) -> list[Finding]:
    """That the clean bases raise no flag that would only be noise."""
    found: list[Finding] = []
    for name in names:
        for base in target(name).bases:
            for doc in documents(request_for(name, base, native=native)):
                for leaf in leaves(doc):
                    flags = set(sanitize(leaf, origin="battery", max_chars=max(len(leaf), 1)).flags) & CLEAN_FLAGS
                    if flags:
                        found.append(Finding(f"base:{base}", "clean_flagged", f"{sorted(flags)} in {leaf[:80]!r}"))
    return found


def run(targets: Sequence[str] = TARGETS, *, native: bool = False) -> OfflineReport:
    """The whole deterministic layer for the targets."""
    findings = [Finding("corpus", "size", why) for why in check_sizes()]
    cases = [c for c in CASES if c.target in targets]
    for case in cases:
        findings += check_text(case)
        findings += check_request(case, native=native)
    findings += check_bases(targets, native=native)
    return OfflineReport({"cases": len(cases), "bases": sum(len(target(t).bases) for t in targets), "minimum": MIN_CASES},
                         tuple(findings))

