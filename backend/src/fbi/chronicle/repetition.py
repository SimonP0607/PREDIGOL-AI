"""Stock phrases and repetitions in the single chronicle (IA-117, plan piece AD-F04): ``repeat-check-v1``. A rule of the verifier, IN SHADOW.

WHY. Doc 1 measured the readers' texts of 14 days (n = 2,684 briefs): «alineaciones no confirmadas» in 96 % of them, «sin datos suficientes» in
56-60 %, internal jargon in 80-83 %, and a length that barely moves from match to match. The template spoke louder than the facts. This rule
reads every sentence the verifier (``chronicle-verify-v1``) let stand and measures, sentence by sentence:

* its TEMPLATE: the sentence with its names (the match's and its facts': ``plan.names``), its numbers and its figure citations masked
  (``mask``) - «<n> suma # puntos en # partidos» - and how many of the recent chronicles carry the same template (``Corpus.share``);
* a STOCK PHRASE (``GENERIC``): a closed list of the formulas Doc 1 counted (line-ups not confirmed, not enough data, the system's jargon),
  or a template carried by at least ``SHARE_MAX`` of the recent chronicles;
* a REPETITION: the same sentence (names and numbers as they are) the previous chronicle of one of the two teams already said
  (``Corpus.previous``) - nothing new was told;
* whether the chronicle OPENS with what changed: its first sentence cites a fact the previous plan of the match did not have.

THE SWITCH ``FBI_CHRONICLE_REPEAT``: ``shadow`` (default) measures and records, in ``metrics.repetition`` of every chronicle, which sentences the
rule WOULD drop - it drops nothing; ``on`` drops them like a sentence without support, each with its reason in ``dropped`` (the verifier is then
``chronicle-verify-v2``: v1 plus this rule); ``off`` measures nothing. The whole chronicle is shadow (``FBI_CHRONICLE_V4``): nothing reaches a
reader either way.

A sentence that cites a MANDATORY fact of the plan is never dropped for repetition (a decided objective, a key absence, a confirmed news item
must be told even when it was told yesterday): it is counted as ``exempt``. The thresholds are PROPOSED until the owner signs them as the
protocol ``AD-F04`` of the register of signatures (IA-143, ``fbi.protosign.records.F04``, held equal to the constants below by a test; the
protocol of AD-F06, ``fbi.chronicle.protocol``, holds the chronicle to the same figures). ``thresholds.signed`` in every report says whether
that signature is on file for the fingerprint of now (``Corpus.signed``, read with the corpus); a signature turns nothing on - ``on`` is
still the owner's change of the switch.

Pure: no database, no clock, no model (the corpus is read by ``fbi.chronicle.inputs.repetition_corpus``)."""

from __future__ import annotations

import hashlib
import os
import re
from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field, replace
from typing import Any, Final, Literal

from fbi.chronicle.plan import SECTIONS, ContentPlan
from fbi.chronicle.verify import Dropped, Verdict
from fbi.forecasting import figure_text
from fbi.narrative.job import NUMBER, fold

VERSION: Final = "repeat-check-v1"
KEY: Final = "AD-F04"
"""Its key in the register of the owner's signatures (``fbi.protosign``)."""
VERIFY_WITH_RULE: Final = "chronicle-verify-v2"
"""The verifier's version when the rule drops (``on``): ``chronicle-verify-v1`` plus ``repeat-check-v1``."""
SWITCH: Final = "FBI_CHRONICLE_REPEAT"

Mode = Literal["off", "shadow", "on"]

SHARE_MAX: Final = 0.30
"""PROPOSED (unsigned): a template carried by this share of the recent chronicles is a stock phrase."""
MIN_CORPUS: Final = 20
"""With fewer recent chronicles the share of a template is not measured (it would say nothing)."""
WINDOW_DAYS: Final = 14
CORPUS_LIMIT: Final = 300
"""The recent chronicles read: the newest ``CORPUS_LIMIT`` of the last ``WINDOW_DAYS`` days, other matches only."""
GENERIC_RATE_MAX: Final = 0.10
REPEAT_RATE_MAX: Final = 0.10
"""PROPOSED (unsigned) per chronicle: at most one sentence in ten a stock phrase, at most one in ten a repetition (the criterion of AD-F04)."""
HASH_LEN: Final = 16

GENERIC: Final[dict[str, re.Pattern[str]]] = {
    "es": re.compile("|".join([
        r"\balineaciones?\b[^.]{0,40}?\b(?:no|sin|aun|todavia)\b[^.]{0,25}?\b(?:confirm|publica|conoc)\w*",
        r"\bsin (?:suficientes )?datos(?: suficientes)?\b", r"\bdatos (?:insuficientes|limitados|escasos)\b",
        r"\bno hay (?:suficientes )?datos\b", r"\bfalta(?:n)? datos\b",
        r"\b(?:segun |para )?(?:nuestro|el) modelo\b", r"\bla sombra\b", r"\bel sistema\b", r"\bmuestra (?:pequena|reducida|limitada)\b",
        r"\bincertidumbre (?:alta|elevada|considerable)\b", r"\bhabra que (?:esperar|ver)\b", r"\bpartido (?:abierto|igualado|parejo)\b",
    ])),
    "en": re.compile("|".join([
        r"\bline-?ups?\b[^.]{0,40}?\b(?:not|yet to|still to)\b[^.]{0,25}?\b(?:confirmed|announced|out|known|published)\b",
        r"\bunconfirmed line-?ups?\b", r"\b(?:not enough|insufficient|limited) data\b", r"\bno (?:sufficient )?data\b",
        r"\b(?:our|the) model\b", r"\bthe shadow\b", r"\bthe system\b", r"\bsmall sample\b", r"\bhigh uncertainty\b",
        r"\bremains to be seen\b", r"\b(?:an )?(?:open|even|balanced) (?:match|game|contest)\b",
    ])),
}
"""The closed list of the formulas Doc 1 counted (and the jargon a reader is not told), on the folded text. A new formula is a new version."""


def mode(env: Mapping[str, str] | None = None) -> Mode:
    raw = ((os.environ if env is None else env).get(SWITCH) or "shadow").strip().lower()
    return "on" if raw == "on" else "off" if raw == "off" else "shadow"


# ── the two keys of a sentence ──────────────────────────────────────────────────────────────────────────────────────────────

PUNCT: Final = re.compile(r"[^\w<>#\s]+")
SPACES: Final = re.compile(r"\s+")


def _strip(text: str, names: Iterable[str], token: str) -> str:
    out = text
    for name in sorted({n for n in names if n and len(n) >= 2}, key=len, reverse=True):
        out = re.sub(re.escape(fold(name)), f" {token} ", out)
    return out


def _base(text: str) -> str:
    """Folded, the figure citations and the percentages they carry taken out."""
    out = figure_text.CITATION.sub(" <cifra> ", text)
    out = figure_text.PERCENT.sub(" <cifra> ", out)
    return fold(out)


def mask(text: str, names: Iterable[str]) -> str:
    """The TEMPLATE of a sentence: folded, names as ``<n>``, numbers as ``#``, figures as ``<cifra>``, no punctuation, single spaces."""
    out = _strip(_base(text), names, "<n>")
    out = NUMBER.sub(" # ", out)
    out = PUNCT.sub(" ", out)
    return SPACES.sub(" ", out).strip()


def exact(text: str) -> str:
    """The sentence as it is said (names and numbers kept), folded and without punctuation: two chronicles that say exactly the same."""
    return SPACES.sub(" ", PUNCT.sub(" ", _base(text))).strip()


def key(text: str) -> str:
    return hashlib.sha256(text.encode()).hexdigest()[:HASH_LEN]


def generic_formula(text_es: str, text_en: str) -> str | None:
    """The stock formula a pair of sentences carries (its Spanish words first), or None."""
    for lang, text in (("es", text_es), ("en", text_en)):
        m = GENERIC[lang].search(fold(text))
        if m is not None:
            return f"{lang}: {m.group(0)}"
    return None


# ── what the recent chronicles said ─────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Corpus:
    """The recent chronicles of OTHER matches: how many carry each template (once per chronicle), and the exact sentences the previous
    chronicle of each team of the match said."""

    size: int = 0
    templates: Mapping[str, int] = field(default_factory=dict)
    previous: Mapping[str, frozenset[str]] = field(default_factory=dict)
    """By side (``home``, ``away``): the ``exact`` keys of that team's previous chronicle."""
    previous_ids: Mapping[str, int] = field(default_factory=dict)
    """By side: the ``ai.chronicles`` row of that previous chronicle."""
    signed: bool = False
    """Whether the owner signed AD-F04 in its fingerprint of now (``fbi.chronicle.inputs.repetition_corpus`` reads it). Reported only."""

    def share(self, template_key: str) -> float | None:
        if self.size < MIN_CORPUS:
            return None
        return round(self.templates.get(template_key, 0) / self.size, 4)


def corpus_of(rows: Iterable[Mapping[str, Any]], previous: Mapping[str, Mapping[str, Any]] | None = None) -> Corpus:
    """The corpus from stored rows: each recent row's ``metrics.repetition.templates`` (written by this rule), and each team's previous row's
    ``metrics.repetition.exact``. A row the rule never measured adds nothing (it is not counted in ``size``)."""
    counts: Counter[str] = Counter()
    size = 0
    for r in rows:
        rep = (r.get("metrics") or {}).get("repetition") if isinstance(r.get("metrics"), Mapping) else None
        if not isinstance(rep, Mapping) or not isinstance(rep.get("templates"), list):
            continue
        size += 1
        counts.update({str(t) for t in rep["templates"]})
    prev: dict[str, frozenset[str]] = {}
    prev_ids: dict[str, int] = {}
    for side, r in (previous or {}).items():
        rep = (r.get("metrics") or {}).get("repetition") if isinstance(r.get("metrics"), Mapping) else None
        if isinstance(rep, Mapping) and isinstance(rep.get("exact"), list):
            prev[side] = frozenset(str(x) for x in rep["exact"])
            if r.get("id") is not None:
                prev_ids[side] = int(r["id"])
    return Corpus(size, dict(counts), prev, prev_ids)


# ── the rule ────────────────────────────────────────────────────────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Judged:
    where: str
    section: str
    index: int
    template: str
    exact: str
    share: float | None
    formula: str | None
    repeated_of: str | None
    """The side whose previous chronicle said exactly this, or None."""
    exempt: bool
    """It cites a mandatory fact: never dropped for repetition."""

    @property
    def generic(self) -> bool:
        return self.formula is not None or (self.share is not None and self.share >= SHARE_MAX)

    @property
    def would_drop(self) -> bool:
        stock = self.share is not None and self.share >= SHARE_MAX
        return not self.exempt and (stock or self.repeated_of is not None)

    def why(self) -> str:
        if self.repeated_of is not None:
            return f"repetida: la crónica anterior del equipo ({self.repeated_of}) ya dijo esta frase"
        return f"coletilla: su plantilla está en el {round((self.share or 0) * 100)} % de las crónicas recientes"


def judge(content: Mapping[str, Any], plan: ContentPlan, corpus: Corpus) -> list[Judged]:
    """Every pair of sentences that stood, in the sections' order."""
    mandatory = {i for s in plan.sections for i in s.mandatory}
    out: list[Judged] = []
    es, en = content.get("es") or {}, content.get("en") or {}
    for section in SECTIONS:
        for i, a in enumerate(es.get(section) or []):
            b = (en.get(section) or [])[i] if i < len(en.get(section) or []) else {"text": ""}
            template = key(mask(str(a["text"]), plan.names))
            said = key(exact(str(a["text"])))
            repeated = next((side for side in ("home", "away") if said in corpus.previous.get(side, frozenset())), None)
            out.append(Judged(f"{section}[{i}]", section, i, template, said, corpus.share(template),
                              generic_formula(str(a["text"]), str(b["text"])), repeated, bool(mandatory & set(a.get("facts") or []))))
    return out


def opens_with_change(content: Mapping[str, Any], plan: ContentPlan) -> bool | None:
    """Whether the chronicle's first sentence cites a fact the previous plan of the match did not have (None: no previous plan, or no text)."""
    if not plan.previous:
        return None
    first = next((s for section in SECTIONS for s in (content.get("es") or {}).get(section) or []), None)
    if first is None:
        return None
    before = set(plan.previous)
    by = plan.by_id()
    return any(by[f].key not in before for f in first.get("facts") or [] if f in by)


def _rate(k: int, n: int) -> float | None:
    return None if n == 0 else round(k / n, 4)


def apply(verdict: Verdict, plan: ContentPlan, corpus: Corpus, *, mode_word: Mode) -> tuple[Verdict, str | None]:
    """The rule over a verdict: the verdict to keep (its content without the dropped sentences when ``on``) and the verifier's version to
    record when it differs from v1 (``on``: ``chronicle-verify-v2``). ``off`` returns the verdict as it is."""
    if mode_word == "off" or verdict.content is None:
        return verdict, None
    judged = judge(verdict.content, plan, corpus)
    n = len(judged)
    drop = [j for j in judged if j.would_drop]
    report: dict[str, Any] = {
        "version": VERSION, "mode": mode_word, "corpus": corpus.size, "min_corpus": MIN_CORPUS,
        "thresholds": {"share_max": SHARE_MAX, "generic_rate_max": GENERIC_RATE_MAX, "repeat_rate_max": REPEAT_RATE_MAX,
                       "signed": corpus.signed},
        "sentences": n, "generic": sum(1 for j in judged if j.generic), "repeated": sum(1 for j in judged if j.repeated_of is not None),
        "exempt": sum(1 for j in judged if j.exempt and (j.repeated_of is not None or (j.share or 0) >= SHARE_MAX)),
        "generic_rate": _rate(sum(1 for j in judged if j.generic), n), "repeat_rate": _rate(sum(1 for j in judged if j.repeated_of), n),
        "would_drop": [{"where": j.where, "why": j.why()} for j in drop],
        "formulas": sorted({j.formula for j in judged if j.formula}),
        "previous_chronicles": dict(corpus.previous_ids),
        "opens_with_change": opens_with_change(verdict.content, plan),
        "templates": sorted({j.template for j in judged}), "exact": sorted({j.exact for j in judged}),
    }
    if mode_word != "on" or not drop:
        metrics = {**verdict.metrics, "repetition": {**report, "dropped": 0}}
        return replace(verdict, metrics=metrics), (VERIFY_WITH_RULE if mode_word == "on" else None)
    gone = {(j.section, j.index) for j in drop}
    content: dict[str, Any] = {}
    for lang in ("es", "en"):
        kept_lang: dict[str, list[dict[str, Any]]] = {}
        for section in SECTIONS:
            kept = [s for i, s in enumerate((verdict.content.get(lang) or {}).get(section) or []) if (section, i) not in gone]
            if kept:
                kept_lang[section] = kept
        content[lang] = kept_lang
    dropped = [*verdict.dropped, *(Dropped(j.where, str(verdict.content["es"][j.section][j.index]["text"]), j.why()) for j in drop)]
    left = sum(len(v) for v in content["es"].values())
    metrics = {**verdict.metrics, "kept": left, "dropped": len(dropped),
               "support": None if not verdict.metrics.get("proposed") else round(left / int(verdict.metrics["proposed"]), 4),
               "repetition": {**report, "dropped": len(drop)}}
    return Verdict(content if left else None, dropped, metrics), VERIFY_WITH_RULE


__all__ = ["GENERIC", "MIN_CORPUS", "SHARE_MAX", "SWITCH", "VERIFY_WITH_RULE", "VERSION", "Corpus", "Judged", "apply", "corpus_of", "exact",
           "generic_formula", "judge", "key", "mask", "mode", "opens_with_change"]
