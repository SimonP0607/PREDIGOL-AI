"""The Narrator's verifier (``narrator-v1``): every sentence checked against the facts it cites; one the facts do not support is
DROPPED, never shown and never mended.

It reuses the checks of the readers' chronicle (``fbi.narrative.job``, UX-025/026) as they are - the folding of accents, the
figures a sentence states (digits and the counts written in words), ``stated`` (a figure is a fact's number as shown, a share of 1
written as a percentage), the system's own tokens, the words of a rumour, of an attribution and of an uncalibrated probability, the
two sides of a goals line - imported, never copied and never changed. What is its own: it drops a sentence instead of refusing the
whole text, it checks the NAMES a sentence states, and its list of forbidden words is certainty only (a pick's «why» may say
«valor» and «pick»; it may never say «seguro»).

A sentence stands only when (Spanish and English alike):

* its length is 10 to 300 characters and it cites 1 to 4 fact ids, every one of them a fact of the pick;
* it cites at least one fact that is not the match's identity; in ``why`` it cites no risk fact, in ``risks`` at least one;
* it says nothing only the system says (an id, a code, a name with underscores, a link, markdown) and no certainty;
* EVERY number it states is a number of a fact it cites (or of the claim of evidence it cites) - a reason the decision did not
  use has no fact to rest on, so it has no number either;
* EVERY name it states (a capitalised word that does not open the sentence) is the match's (its teams, its competition) or is in a
  fact it cites (a claim, an outlet);
* an uncalibrated probability stated is called so; a rumour or a contradiction is in ``risks`` and called one; a PROBABLE item is
  attributed; a sentence about an Over never says «under» (and the reverse).

Then the two languages, sentence by sentence: a pair stands only when both stand, with the same fact ids and the same numbers. A
sentence beyond its section's limit, or without its counterpart, is dropped.

Pure: no database, no call.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from fbi.narrative.job import (
    ATTRIBUTION,
    RUMOUR_WORDS,
    SYSTEM_TOKENS,
    TOTAL_AGAINST,
    UNCALIBRATED_WORDS,
    figures,
    fold,
    stated,
)
from fbi.narrator.facts import NAME_KEYS, TEXT_KEYS, Fact, PickFacts
from fbi.narrator.prompt import LIMITS, MAX_FACTS, SECTIONS

TEXT_MIN, TEXT_MAX = 10, 300
LANGS: Final = ("es", "en")


# ── what the model returns ────────────────────────────────────────────────────────────────────────────────────────────

class SentenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    facts: list[str]


class LanguageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    why: list[SentenceOut]
    risks: list[SentenceOut]


class NarratorOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    es: LanguageOut
    en: LanguageOut


# ── the words ─────────────────────────────────────────────────────────────────────────────────────────────────────────

def _words(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


CERTAINTY: Final[dict[str, re.Pattern[str]]] = {
    "es": _words([
        r"\bsegur[oa]s?\b", r"\bseguramente\b", r"\bfij[oa]s?\b", r"\bgarantiz\w*", r"\bgarantias?\b", r"\bsin (?:ninguna )?duda\b",
        r"\bindudabl\w*", r"\binfalibl\w*", r"\bimperdibl\w*", r"\bcantad[oa]s?\b", r"\bno falla\b", r"\bno (?:puede|va a) (?:fallar|perder)\b",
        r"\bcertez\w*", r"\basegur\w*", r"\bganaran?\b", r"\bperderan?\b", r"\bvan? a (?:ganar|perder)\b", r"\bclaramente\b",
        r"\bevidentemente\b", r"\bobviamente\b", r"\bregalo\b", r"\bdinero facil\b", r"\bganancias? (?:segura|asegurada)s?\b"]),
    "en": _words([
        r"\bsure(?:ly)?\b", r"\bcertain(?:ly|ty)?\b", r"\bguarantee\w*", r"\blocks?\b", r"\bbanker\b", r"\bno[- ]brainer\b",
        r"\bcan(?:no|')t lose\b", r"\bwon't lose\b", r"\bfree money\b", r"\bdefinitely\b", r"\bundoubtedly\b",
        r"\bwithout (?:a )?doubt\b", r"\bwill (?:win|lose)\b", r"\b(?:is|are) going to (?:win|lose)\b", r"\bnailed on\b",
        r"\bobviously\b", r"\bclearly\b", r"\bsafe bet\b", r"\beasy money\b"]),
}
"""Certainty and promises of profit (on the folded text). Unlike the chronicle, a pick's «why» may say «valor», «value» and «pick»."""

OWN_TOKENS: Final = re.compile(r"\bF:\S*|\b(?:APROBADO|CAUTELA|INVESTIGACION|RECHAZADO|APPROVE|DOWNGRADE|REJECT|ABSTAIN|LIMITED)\b")
"""The Narrator's own system words: its fact ids and the decision's and the review's codes in capitals."""

WORD: Final = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*")
OPENERS: Final = ".!?:;«\"(¿¡—-"
ALWAYS_NAMES: Final = frozenset({"predigol", "intelligence", "pick", "score"})
"""Capitalised words that are PrediGol's own (``PrediGol Intelligence``, the ``Pick Score``), never a name of the match."""


# ── one sentence ──────────────────────────────────────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return " ".join(text.split())


def _strip_names(text: str, names: Iterable[str]) -> str:
    out = text
    for name in sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True):
        out = re.sub(re.escape(name), " ", out, flags=re.IGNORECASE)
    return out


def _numbers(value: Any, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.add(abs(float(value)))
    elif isinstance(value, str):
        out.update(f.value for f in figures(value, "es"))


def allowed_numbers(cited: Iterable[Fact]) -> set[float]:
    """The numbers a sentence citing these facts may state: every numeric param, and the numbers inside a claim it cites."""
    out: set[float] = set()
    for f in cited:
        for key, value in f.params.items():
            if key in NAME_KEYS:
                continue
            if isinstance(value, str) and key not in TEXT_KEYS:
                continue  # a code (a market, a state) carries no number a reader may be told
            _numbers(value, out)
    return out


def _tokens(text: str) -> set[str]:
    return {_bare(fold(m.group(0))) for m in WORD.finditer(text)}


def _bare(word: str) -> str:
    return re.sub(r"['\u2019]s$", "", word)


def allowed_names(pf: PickFacts, cited: Iterable[Fact]) -> set[str]:
    """The folded words a capitalised word may be: the match's names, and any word of a cited fact's text."""
    out = set(ALWAYS_NAMES)
    for name in pf.names:
        out |= _tokens(name)
    for f in cited:
        for value in f.params.values():
            if isinstance(value, str):
                out |= _tokens(value)
    return out


def names_stated(text: str) -> list[str]:
    """The capitalised words of a sentence that do not open it (or one of its clauses): what reads as a name."""
    out = []
    for m in WORD.finditer(text):
        word = m.group(0)
        if len(word) < 2 or not word[0].isupper():
            continue
        before = text[: m.start()].rstrip()
        if not before or before[-1] in OPENERS:
            continue
        out.append(word)
    return out


def check_sentence(text: str, fact_ids: list[str], *, lang: str, section: str, pf: PickFacts) -> str | None:
    """Why one sentence cannot be shown, or None when it can."""
    text = _clean(text)
    ids = [i.strip() for i in fact_ids]
    if not TEXT_MIN <= len(text) <= TEXT_MAX:
        return f"length {len(text)} outside {TEXT_MIN}-{TEXT_MAX}"
    if not ids or len(ids) > MAX_FACTS:
        return f"{len(ids)} facts cited (1 to {MAX_FACTS})"
    known = pf.by_id()
    unknown = [i for i in ids if i not in known]
    if unknown:
        return f"cites facts that do not exist: {', '.join(unknown)}"
    cited = [known[i] for i in dict.fromkeys(ids)]
    if all(f.role == "identity" for f in cited):
        return "cites only the match's identity: no fact of the pick"
    risky = [f.id for f in cited if f.role == "risk"]
    if section == "why" and risky:
        return f"a risk cited as a reason: {', '.join(risky)}"
    if section == "risks" and not risky:
        return "a risk sentence that cites no risk"
    bare = _strip_names(text, pf.names)
    for pattern in (SYSTEM_TOKENS, OWN_TOKENS):
        if (m := pattern.search(bare)) is not None:
            return f"says something only the system says: {m.group(0)!r}"
    folded = fold(bare)
    if (m := CERTAINTY[lang].search(folded)) is not None:
        return f"certainty: {m.group(0)!r}"
    stated_here = figures(bare, lang)
    allowed = allowed_numbers(cited)
    loose = [f.raw for f in stated_here if not stated(f, allowed)]
    if loose:
        return f"numbers no cited fact has: {', '.join(loose)}"
    names = allowed_names(pf, cited)
    strangers = [w for w in names_stated(text) if _bare(fold(w)) not in names]
    if strangers:
        return f"names no cited fact has: {', '.join(strangers)}"
    for f in cited:
        if f.code == "probability" and f.params.get("calibrated") is False:
            share = f.params.get("probability")
            if isinstance(share, float) and any(stated(fg, [share]) for fg in stated_here) \
                    and UNCALIBRATED_WORDS[lang].search(folded) is None:
                return "an uncalibrated probability without its label"
        if f.code == "pick" and f.params.get("market") == "OU":
            against = TOTAL_AGAINST.get((lang, str(f.params.get("selection", "")).lower()))
            if against is not None and against.search(folded) is not None:
                return "says the other side of the goals line the pick is on"
    evidence = [f for f in cited if f.code == "evidence"]
    weak = [f for f in evidence if f.params.get("status") in ("RUMOR", "CONTRADICTORY")]
    if weak and RUMOUR_WORDS[lang].search(folded) is None:
        return "a rumour or a contradiction not called one"
    if evidence and all(f.params.get("status") == "PROBABLE" for f in evidence) and ATTRIBUTION[lang].search(folded) is None:
        return "a probable item told as a fact (attribute it)"
    return None


# ── the whole answer ──────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Dropped:
    where: str
    text: str
    why: str

    def as_json(self) -> dict[str, str]:
        return {"where": self.where, "text": self.text[:200], "why": self.why}


@dataclass
class Verdict:
    content: dict[str, Any] | None
    """``{es: {why: [...], risks: [...]}, en: {...}}`` with the sentences that stand, or None when no ``why`` sentence does."""
    dropped: list[Dropped] = field(default_factory=list)

    @property
    def status(self) -> str:
        """ok - every sentence stood; partial - some were dropped and the «why» still stands; rejected - no «why» sentence stood."""
        if self.content is None:
            return "rejected"
        return "partial" if self.dropped else "ok"

    @property
    def kept(self) -> int:
        if self.content is None:
            return 0
        return sum(len(v) for v in self.content["es"].values())


def _numbers_key(text: str, lang: str) -> Counter[float]:
    return Counter(round(f.value, 3) for f in figures(text, lang))


def verify(out: NarratorOut, pf: PickFacts) -> Verdict:
    """Every check of the module's docstring: the sentences that stand, in both languages, and why each other one was dropped."""
    dropped: list[Dropped] = []
    kept: dict[str, dict[str, list[dict[str, Any]]]] = {lang: {s: [] for s in SECTIONS} for lang in LANGS}
    for section in SECTIONS:
        es: list[SentenceOut] = getattr(out.es, section)
        en: list[SentenceOut] = getattr(out.en, section)
        limit = LIMITS[section]
        for i in range(max(len(es), len(en))):
            where = f"{section}[{i}]"
            a = es[i] if i < len(es) else None
            b = en[i] if i < len(en) else None
            if a is None or b is None:
                lone = a or b
                assert lone is not None
                dropped.append(Dropped(where, lone.text, "no counterpart in the other language"))
                continue
            if i >= limit:
                dropped.append(Dropped(where, a.text, f"beyond the limit of {limit} sentences"))
                continue
            why_es = check_sentence(a.text, a.facts, lang="es", section=section, pf=pf)
            why_en = check_sentence(b.text, b.facts, lang="en", section=section, pf=pf)
            if why_es is not None:
                dropped.append(Dropped(f"es.{where}", a.text, why_es))
            if why_en is not None:
                dropped.append(Dropped(f"en.{where}", b.text, why_en))
            if why_es is not None or why_en is not None:
                continue
            ids_es, ids_en = [x.strip() for x in a.facts], [x.strip() for x in b.facts]
            if set(ids_es) != set(ids_en):
                dropped.append(Dropped(where, b.text, "the English cites other facts than the Spanish"))
                continue
            if _numbers_key(a.text, "es") != _numbers_key(b.text, "en"):
                dropped.append(Dropped(where, b.text, "the English says other numbers than the Spanish"))
                continue
            kept["es"][section].append({"text": _clean(a.text), "facts": list(dict.fromkeys(ids_es))})
            kept["en"][section].append({"text": _clean(b.text), "facts": list(dict.fromkeys(ids_es))})
    if not kept["es"]["why"]:
        return Verdict(None, dropped)
    return Verdict({lang: dict(kept[lang]) for lang in LANGS}, dropped)


def facts_cited(content: Mapping[str, Any]) -> list[str]:
    """The fact ids a verified narrative rests on, once each, in the order it first cites them."""
    out: list[str] = []
    for section in SECTIONS:
        for sentence in content.get("es", {}).get(section, []):
            for fid in sentence["facts"]:
                if fid not in out:
                    out.append(fid)
    return out
