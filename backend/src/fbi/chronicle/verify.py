"""The verifier of the single chronicle (IA-104, plan piece AD-F02): ``chronicle-verify-v1``. Claim by claim: a sentence the plan does not
support is DROPPED - never shown, never mended - and the rest of the chronicle stands.

It reuses, imported and never copied, the checks of the readers' chronicle (``fbi.narrative.job``: the folding, the figures a sentence states,
``stated``, the system's tokens, the forbidden words of certainty and betting, the words of a rumour, of an attribution, of a cause, of a doubt
and of an injury, the comparison of the two languages), the reading of names of the Narrator (``fbi.narrator.verify.names_stated``), the health
filter of the news (``fbi.news.health``: a state, never a diagnosis) and the figure checker of the single figure (``fbi.forecasting.figure_text``).
What is its own: the plan (``fbi.chronicle.plan``) is the only list of facts, and the classes of claim (``fbi.chronicle.claims``).

A sentence stands only when (Spanish and English alike):

* it has 10 to 300 characters and cites 1 to 4 facts, every one of them PLANNED, at least one of them planned for its own section, and its
  section is not one the plan abstains on;
* every PERCENTAGE is a figure of ``forecast-v2`` the plan carries, written ``57 % [cifra forecast-v2 <id>]`` and rounded as the reader is
  shown it, and the figure is one the sentence cites (``figure_text.check``: uncited, other version, unknown reading, mismatch, orphan);
* it says nothing only the system says (an id, a code, a name with underscores, a link, markdown), no certainty and no betting word;
* EVERY other number it states is a number of a fact it cites (or of the claim of a news item it cites) - a computed number has no fact;
* EVERY name it states is the match's or is in a fact it cites;
* every CLASS of claim its words make (``claims.classes_stated``) is authorised by a fact it cites - «nada en juego» only with the engine's
  proved ``SIN_OBJETIVO_DEMOSTRADO``, «clasificado» only with a proved ``conseguido``, a superlative never;
* a rumour is told only among the risks and called one; a probable item is attributed; a doubt is told as a doubt; a descriptive fact is
  never a cause; a cause the provider did not give is not invented; no medical detail (``health-filter-v1``).

Then the two languages, sentence by sentence: a pair stands only when both stand, with the same facts and the same numbers. A sentence beyond
its section's cap, or without its counterpart, is dropped. When no sentence stands the chronicle abstains (``VERIFICACION_VACIA``).

Pure: no database, no call.
"""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import date
from typing import Any, Final

from pydantic import BaseModel, ConfigDict

from fbi.chronicle import claims
from fbi.chronicle.plan import EMPTY_VERIFICATION, SECTIONS, ContentPlan, PlanFact, mandatory_cited
from fbi.forecasting import figure_text
from fbi.narrative.job import (
    ATTRIBUTION,
    CAUSAL,
    DOUBT_WORDS,
    FORBIDDEN,
    INJURY_WORDS,
    RUMOUR_WORDS,
    SYSTEM_TOKENS,
    figures,
    fold,
    stated,
)
from fbi.narrative.job import _numbers_key as numbers_key
from fbi.narrator.verify import names_stated
from fbi.news import health

VERSION: Final = "chronicle-verify-v1"
TEXT_MIN, TEXT_MAX = 10, 300
MAX_FACTS: Final = 4
LANGS: Final = ("es", "en")
OWN_TOKENS: Final = re.compile(r"\b[SFU]:\S*|\bSIN_[A-Z_]+\b|\[cifra\b")
"""The plan's own ids (``S:``, ``F:``, ``U:``; ``P:`` and ``E:`` are the readers' chronicle's), its codes, and a citation left behind."""
NOT_NUMBERS: Final = frozenset({"evidence_id", "content_hash", "reading_id", "cita", "order", "known_at"})
"""Params that are identifiers, never a number a reader may be told."""
NAME_FREE: Final = frozenset({"predigol", "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday", "january",
                              "february", "march", "april", "may", "june", "july", "august", "september", "october", "november",
                              "december", "spanish", "english"})
"""Capitalised words that are no name of the match: PrediGol, and the days and months English writes with a capital."""
RUMOUR_NAMED: Final[dict[str, re.Pattern[str]]] = {
    "es": re.compile(r"\brumor\w*|\bcontradic\w*|\bversiones\b|\bse especula\w*"),
    "en": re.compile(r"\brumou?r\w*|\bcontradict\w*|\bconflicting\b|\bspeculat\w*"),
}
"""A rumour NAMED as one: only a rumour fact authorises it. «sin confirmar» alone may also tell a doubt or what is not out yet."""
WORD: Final = re.compile(r"[^\W\d_]+(?:['\u2019][^\W\d_]+)*")


# ── what the model returns ──────────────────────────────────────────────────────────────────────────────────────────────────

class SentenceOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str
    facts: list[str]


class LanguageOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    que_se_juega: list[SentenceOut]
    como_llega: list[SentenceOut]
    que_puede_definir: list[SentenceOut]
    estadisticas: list[SentenceOut]
    jugadores: list[SentenceOut]
    novedades: list[SentenceOut]
    riesgos: list[SentenceOut]
    que_falta: list[SentenceOut]


class ChronicleOut(BaseModel):
    model_config = ConfigDict(extra="forbid")
    es: LanguageOut
    en: LanguageOut


# ── one sentence ────────────────────────────────────────────────────────────────────────────────────────────────────────────

def _clean(text: str) -> str:
    return " ".join(text.split())


def _strip_names(text: str, names: Iterable[str]) -> str:
    out = text
    for name in sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True):
        out = re.sub(re.escape(name), " ", out, flags=re.IGNORECASE)
    return out


def _bare(word: str) -> str:
    return re.sub(r"['\u2019]s$", "", word)


def _tokens(text: str) -> set[str]:
    return {_bare(fold(m.group(0))) for m in WORD.finditer(text)}


def _numbers(value: Any, out: set[float]) -> None:
    if isinstance(value, bool) or value is None:
        return
    if isinstance(value, (int, float)):
        out.add(abs(float(value)))
    elif isinstance(value, (list, tuple)):
        for v in value:
            _numbers(v, out)


def allowed_numbers(cited: Iterable[PlanFact], texts: Mapping[str, str]) -> set[float]:
    """The numbers a sentence citing these facts may state: every numeric param, the day and year a news item was published, and the numbers
    of the claim of a news item it cites."""
    out: set[float] = set()
    for f in cited:
        for key, value in f.params.items():
            if key in NOT_NUMBERS:
                continue
            if key == "published" and isinstance(value, str):
                try:
                    d = date.fromisoformat(value)
                except ValueError:
                    continue
                out.update({float(d.day), float(d.year)})
                continue
            _numbers(value, out)
        claim = texts.get(f.id)
        if claim:
            out.update(g.value for lang in LANGS for g in figures(claim, lang))
    return out


def allowed_names(plan: ContentPlan, cited: Iterable[PlanFact], texts: Mapping[str, str]) -> set[str]:
    out = set(NAME_FREE)
    for name in plan.names:
        out |= _tokens(name)
    for f in cited:
        for value in f.params.values():
            if isinstance(value, str):
                out |= _tokens(value)
            elif isinstance(value, list):
                for v in value:
                    if isinstance(v, str):
                        out |= _tokens(v)
        if f.id in texts:
            out |= _tokens(texts[f.id])
    return out


def _without_figures(text: str) -> str:
    """The sentence with its cited percentages taken out (checked on their own by ``figure_text``)."""
    return figure_text.CITATION.sub(" ", figure_text.PERCENT.sub(lambda m: " " if _cited_after(text, m.end()) else m.group(0), text))


def _cited_after(text: str, end: int) -> bool:
    gap = re.compile(r"\s*").match(text, end)
    return figure_text.CITATION.match(text, end if gap is None else gap.end()) is not None


def check_sentence(text: str, fact_ids: Sequence[str], *, lang: str, section: str, plan: ContentPlan,
                   texts: Mapping[str, str]) -> str | None:
    """Why one sentence cannot stand (a short reason), or None when it can. ``texts``: the claims of the news the writer was given, by id."""
    text = _clean(text)
    ids = list(dict.fromkeys(i.strip() for i in fact_ids))
    if not TEXT_MIN <= len(text) <= TEXT_MAX:
        return f"length {len(text)} outside {TEXT_MIN}-{TEXT_MAX}"
    if not ids or len(ids) > MAX_FACTS:
        return f"{len(ids)} facts cited (1 to {MAX_FACTS})"
    known = plan.by_id()
    planned = {f.id for f in plan.planned}
    unknown = [i for i in ids if i not in planned]
    if unknown:
        return f"cites facts the plan does not hold: {', '.join(unknown)}"
    cited = [known[i] for i in ids]
    kinds = {f.kind for f in cited}
    if "news.rumour" in kinds and section != "riesgos":
        return "a rumour outside the risks"
    if not any(f.section == section for f in cited):
        return f"no cited fact is planned for {section}"

    readings = {str(f.params["reading_id"]): float(f.value) for f in cited if f.kind == "figure" and f.value is not None}
    version = next((str(f.source) for f in cited if f.kind == "figure"), plan.figure_version or "forecast-v2")
    found = figure_text.check(text, plan.readings(), version=version)
    if not found.accepted:
        return "figure: " + ", ".join(sorted({p.code for p in found.problems}))
    stray = [m.group("id") for m in figure_text.CITATION.finditer(text) if m.group("id") not in readings]
    if stray:
        return "a figure the sentence does not cite"
    rest = _without_figures(text)

    bare = _strip_names(rest, plan.names)
    for pattern in (SYSTEM_TOKENS, OWN_TOKENS):
        if (m := pattern.search(bare)) is not None:
            return f"says something only the system says: {m.group(0)!r}"
    folded = fold(bare)
    if (m := FORBIDDEN[lang].search(folded)) is not None:
        return f"forbidden word: {m.group(0)!r}"
    loose = [g.raw for g in figures(bare, lang) if not stated(g, allowed_numbers(cited, texts))]
    if loose:
        return f"numbers no cited fact has: {', '.join(loose)}"
    names = allowed_names(plan, cited, texts)
    strangers = [w for w in names_stated(rest) if _bare(fold(w)) not in names]
    if strangers:
        return f"names no cited fact has: {', '.join(strangers)}"
    for code in claims.classes_stated(folded, lang):
        if not claims.authorises(code, kinds):
            return f"class {code} without the fact that authorises it"
    rumour = RUMOUR_WORDS[lang].search(folded) is not None
    unconfirmed_state = any(k.startswith("unknown.") or k == "absence.doubtful" for k in kinds)
    if "news.rumour" not in kinds and (RUMOUR_NAMED[lang].search(folded) is not None or (rumour and not unconfirmed_state)):
        return "class RUMOR without the fact that authorises it"
    if "news.rumour" in kinds and not rumour:
        return "a rumour or a contradiction not called one"
    news = [f for f in cited if f.kind.startswith("news.")]
    if news and all(f.kind == "news.probable" for f in news) and ATTRIBUTION[lang].search(folded) is None:
        return "a probable item told as a fact (attribute it)"
    if kinds & claims.DESCRIPTIVE and (m := CAUSAL[lang].search(folded)) is not None:
        return f"a descriptive fact told as a cause: {m.group(0)!r}"
    absences = [f for f in cited if f.kind.startswith("absence.")]
    if any(f.kind == "absence.doubtful" for f in absences) and len(absences) == 1 and DOUBT_WORDS[lang].search(folded) is None:
        return "a doubt told as a certainty"
    if absences and all(f.params.get("kind") != "injury" for f in absences) and not news \
            and INJURY_WORDS[lang].search(folded) is not None:
        return "an injury the provider did not give"
    injury = bool(absences) or any(f.params.get("topic") in ("injury", "lineup", "availability") for f in news)
    told = health.check(rest, [health.Communicated(texts.get(f.id, ""), "press") for f in news], injury=injury)
    if told is not None:
        return f"health: {told}"
    return None


# ── the whole answer ────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Dropped:
    where: str
    text: str
    why: str

    def as_json(self) -> dict[str, str]:
        return {"where": self.where, "text": self.text[:200], "why": self.why[:200]}


@dataclass
class Verdict:
    content: dict[str, Any] | None
    """``{es: {section: [{text, facts}]}, en: {...}}`` with only the sections that kept a sentence, or None when none did."""
    dropped: list[Dropped] = field(default_factory=list)
    metrics: dict[str, Any] = field(default_factory=dict)

    @property
    def status(self) -> str:
        """ok - every sentence stood; partial - some were dropped and others stand; rejected - none stood (``VERIFICACION_VACIA``)."""
        if self.content is None:
            return "rejected"
        return "partial" if self.dropped else "ok"

    @property
    def abstention(self) -> str | None:
        return EMPTY_VERIFICATION if self.content is None else None

    @property
    def cited(self) -> list[str]:
        out: list[str] = []
        for sentences in (self.content or {}).get("es", {}).values():
            for s in sentences:
                out += [f for f in s["facts"] if f not in out]
        return out


def _pair_key(text: str, lang: str, names: Iterable[str]) -> tuple[Counter[float], frozenset[str]]:
    ids = frozenset(m.group("id") for m in figure_text.CITATION.finditer(text))
    return numbers_key(_without_figures(text), lang, names), ids


def verify(out: ChronicleOut, plan: ContentPlan, texts: Mapping[str, str] | None = None) -> Verdict:
    """Every check of the module's docstring: the sentences that stand, in both languages, why each other one was dropped, and the
    measures of the chronicle (support, coverage of the plan)."""
    texts = texts or {}
    dropped: list[Dropped] = []
    caps = {s.code: s.cap for s in plan.sections}
    kept: dict[str, dict[str, list[dict[str, Any]]]] = {lang: {} for lang in LANGS}
    proposed = 0
    reasons: Counter[str] = Counter()
    for section in SECTIONS:
        es: list[SentenceOut] = getattr(out.es, section)
        en: list[SentenceOut] = getattr(out.en, section)
        for i in range(max(len(es), len(en))):
            proposed += 1
            where = f"{section}[{i}]"
            a = es[i] if i < len(es) else None
            b = en[i] if i < len(en) else None
            if a is None or b is None:
                lone = a or b
                assert lone is not None
                dropped.append(Dropped(where, lone.text, "no counterpart in the other language"))
                reasons["pair"] += 1
                continue
            if i >= caps.get(section, 0):
                dropped.append(Dropped(where, a.text, f"beyond the section's cap of {caps.get(section, 0)}"))
                reasons["cap"] += 1
                continue
            why_es = check_sentence(a.text, a.facts, lang="es", section=section, plan=plan, texts=texts)
            why_en = check_sentence(b.text, b.facts, lang="en", section=section, plan=plan, texts=texts)
            if why_es is not None:
                dropped.append(Dropped(f"es.{where}", a.text, why_es))
                reasons[why_es.split(":")[0][:40]] += 1
            if why_en is not None:
                dropped.append(Dropped(f"en.{where}", b.text, why_en))
                reasons[why_en.split(":")[0][:40]] += 1
            if why_es is not None or why_en is not None:
                continue
            ids_es = list(dict.fromkeys(x.strip() for x in a.facts))
            if set(ids_es) != {x.strip() for x in b.facts}:
                dropped.append(Dropped(where, b.text, "the English cites other facts than the Spanish"))
                reasons["pair"] += 1
                continue
            if _pair_key(a.text, "es", plan.names) != _pair_key(b.text, "en", plan.names):
                dropped.append(Dropped(where, b.text, "the English says other numbers than the Spanish"))
                reasons["pair"] += 1
                continue
            kept["es"].setdefault(section, []).append({"text": _clean(a.text), "facts": ids_es})
            kept["en"].setdefault(section, []).append({"text": _clean(b.text), "facts": ids_es})
    n_kept = sum(len(v) for v in kept["es"].values())
    content = None if n_kept == 0 else {lang: {s: kept[lang][s] for s in SECTIONS if s in kept[lang]} for lang in LANGS}
    cited = [f for s in (content or {}).get("es", {}).values() for x in s for f in x["facts"]]
    have, want = mandatory_cited(plan, cited)
    metrics = {"version": VERSION, "proposed": proposed, "kept": n_kept, "dropped": len(dropped),
               "support": None if proposed == 0 else round(n_kept / proposed, 4),
               "mandatory_cited": have, "mandatory": want,
               "sections_written": [s for s in SECTIONS if content is not None and s in content["es"]],
               "sections_abstained": {s.code: s.abstention for s in plan.sections if s.abstention},
               "reasons": dict(sorted(reasons.items()))}
    return Verdict(content, dropped, metrics)


def facts_cited(content: Mapping[str, Any]) -> list[str]:
    """The fact ids a verified chronicle rests on, once each, in the order it first cites them."""
    out: list[str] = []
    for section in SECTIONS:
        for sentence in content.get("es", {}).get(section, []):
            for fid in sentence["facts"]:
                if fid not in out:
                    out.append(fid)
    return out


__all__ = ["VERSION", "ChronicleOut", "Dropped", "LanguageOut", "SentenceOut", "Verdict", "check_sentence", "facts_cited", "verify"]
