"""What a chronicle may claim, and the fact that authorises each claim (IA-103, plan piece AD-F01): ``claim-classes-v1``.

WHY. ``stakes-v5`` wrote «nada en juego» in 82 of 432 approved chronicles (19 %, 14 days) without a computation behind it, and 4 of 5 cases
checked were false (Doc 1). A sentence of the single chronicle (``chronicle-v4``) states something of a CLASS - «nothing at stake», «already
qualified», «a streak», «a doubt», «a rumour», «a probability» - and each class is authorised by facts of given KINDS of the content plan
(``fbi.chronicle.plan``). The table is the rule, written once and used twice:

* the PLAN lets a class in only when one of its authorising facts is in the plan (no fact, no class: ``allowed_classes``);
* the VERIFIER (``fbi.chronicle.verify``) reads the class of every sentence from its words (``cues``) and drops the sentence unless it CITES a
  fact of an authorising kind. A class whose ``authorised_by`` is empty is never authorised: its words always drop the sentence.

THE HIGH-RISK CLASSES (``risk == "alto"``) are the ones whose false statement is what Doc 1 measured: ``SIN_OBJETIVO_DEMOSTRADO`` (only from the
proved ``SIN_OBJETIVO_DEMOSTRADO`` of the scenarios engine, ``scenarios-v2``: a language model never writes it), a decided objective (proved
secured or proved lost), a superlative of history or of the league (no code computes one today: never authorised), a probability (only a
figure of ``forecast-v2`` repeated with its citation, ``fbi.forecasting.figure_text``), a rumour (only a fact that IS a rumour, in the risks,
called one) and a medical detail (never: ``fbi.news.health``).

The cues are read on the folded text (lower case, no accents: ``fbi.narrative.job.fold``). They are deliberately wide: a sentence that reads as
a class it cannot prove is dropped, never mended (fail closed). Pure: no database, no clock, no model.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from typing import Final, Literal

VERSION: Final = "claim-classes-v1"

Risk = Literal["alto", "medio", "bajo"]

# The kinds of fact the plan can hold (``fbi.chronicle.plan.PlanFact.kind``): a closed list.
KINDS: Final[tuple[str, ...]] = (
    "match.intro", "match.kind", "table.position", "table.gap", "table.pressure",
    "scenario.no_objective", "scenario.secured", "scenario.lost", "scenario.open", "scenario.result_effect",
    "tie.first_leg", "tie.outlook",
    "form", "result", "streak.unbeaten", "streak.winless", "venue_record", "xg", "top_scorer",
    "h2h.summary", "h2h.meeting",
    "absence.out", "absence.doubtful",
    "news.confirmed", "news.probable", "news.rumour",
    "figure",
    "unknown.lineups", "unknown.rules", "unknown.scenarios",
)
DESCRIPTIVE: Final = frozenset({"h2h.summary", "h2h.meeting", "table.position", "table.gap", "venue_record"})
"""Kinds that describe and never explain: a sentence that cites one of them never says «porque», «because»... (the brief's own rule,
``fbi.ai.brief.descriptive_factor``)."""
SCENARIO_DECIDED: Final = frozenset({"scenario.no_objective", "scenario.secured", "scenario.lost"})


def _words(patterns: Iterable[str]) -> re.Pattern[str]:
    return re.compile("|".join(f"(?:{p})" for p in patterns))


@dataclass(frozen=True, slots=True)
class ClaimClass:
    code: str
    risk: Risk
    authorised_by: tuple[str, ...]
    """The kinds of fact that authorise the class. Empty: nothing authorises it today (its words always drop the sentence)."""
    meaning: str
    cues: Mapping[str, re.Pattern[str]] = field(default_factory=dict)
    """How a sentence reads as this class, per language (on the folded text). No cue: the class is checked by its own rule (the
    probability by ``figure_text``, the medical detail by ``fbi.news.health``)."""
    section: str | None = None
    """The only section a sentence of this class may stand in (None: any)."""

    def as_json(self) -> dict[str, object]:
        return {"code": self.code, "risk": self.risk, "authorised_by": list(self.authorised_by), "meaning": self.meaning,
                "cues": {lang: p.pattern for lang, p in sorted(self.cues.items())}, "section": self.section}


CLASSES: Final[tuple[ClaimClass, ...]] = (
    ClaimClass(
        "SIN_OBJETIVO_DEMOSTRADO", "alto", ("scenario.no_objective",),
        "nothing is at stake for a team: only the proved SIN_OBJETIVO_DEMOSTRADO of scenarios-v2",
        {"es": _words([r"\bnada (?:en juego|que jugarse|por (?:lo )?que (?:jugar|pelear)|que (?:ganar|perder))\b",
                       r"\bsin (?:nada en juego|objetivos?(?: en juego)?|nada que (?:ganar|perder|jugarse))\b", r"\bintrascendent\w*",
                       r"\bya no se juega nada\b", r"\bno se juega(?:n)? nada\b", r"\b(?:cumplir|cumple|cumplen) (?:el|con el) (?:tramite|expediente|calendario)\b",
                       r"\bsolo (?:por|para) cumplir\b", r"\bsin (?:aspiraciones|motivacion)\b", r"\b(?:partido|duelo) de tramite\b"]),
         "en": _words([r"\bnothing (?:left )?(?:at stake|to play for)\b", r"\bdead rubber\b", r"\bmeaningless\b", r"\bplaying for pride\b",
                       r"\bno(?:thing)? (?:longer )?(?:anything )?to play for\b", r"\bnothing to (?:gain|lose)\b", r"\binconsequential\b"])}),
    ClaimClass(
        "OBJETIVO_CONSEGUIDO", "alto", ("scenario.secured",),
        "an objective already secured (title, qualification, promotion, survival): only a proved 'conseguido' of scenarios-v2",
        {"es": _words([r"\b(?:ya )?clasificad[oa]s?\b", r"\bcampeon(?:es|a|as)?\b", r"\bascendid[oa]s?\b", r"\bsalvad[oa]s?\b",
                       r"\bpermanencia (?:asegurada|garantizada)\b", r"\basegur(?:o|aron|ado|ada|ados|adas) (?:la|el|su|sus)\b",
                       r"\bmatematicamente\b", r"\bse consagr\w*", r"\bsello (?:el|la|su)\b", r"\bya tiene (?:el|la|su)\b"]),
         "en": _words([r"\b(?:already )?qualified\b", r"\bchampions?\b", r"\bpromoted\b", r"\bclinch\w*", r"\bsecured\b", r"\bsealed\b",
                       r"\bmathematical\w*", r"\bsafe from relegation\b", r"\bsurvival (?:is )?(?:secured|assured)\b", r"\bcrowned\b"])}),
    ClaimClass(
        "OBJETIVO_DESCARTADO", "alto", ("scenario.lost", "scenario.result_effect", "tie.outlook"),
        "an objective already lost (relegated, eliminated, out of the race): only a proved 'descartado', or what a result would do",
        {"es": _words([r"\beliminad[oa]s?\b", r"\bdescendid[oa]s?\b", r"\bsin (?:opciones|posibilidades|chances)\b", r"\bdesahuciad\w*",
                       r"\bcondenad[oa]s? al descenso\b", r"\bfuera de (?:la pelea|la carrera|carrera)\b", r"\bya no (?:puede|pueden)\b"]),
         "en": _words([r"\beliminated\b", r"\brelegated\b", r"\bknocked out\b", r"\bno (?:longer )?(?:a )?chance\b", r"\bout of (?:contention|the race)\b",
                       r"\bcan no longer\b", r"\bcannot (?:reach|finish|qualify|avoid)\b"])}),
    ClaimClass(
        "OBJETIVO_EN_JUEGO", "medio",
        ("scenario.open", "scenario.result_effect", "scenario.no_objective", "scenario.secured", "scenario.lost", "table.pressure", "table.position", "table.gap", "tie.outlook", "tie.first_leg",
         "match.kind"),
        "what a team is still playing for: an open objective of scenarios-v2, the table, or the tie",
        {"es": _words([r"\bse juega(?:n)?\b", r"\ben juego\b", r"\bpelea(?:n)? (?:por|el|la)\b", r"\blucha(?:n)? (?:por|el|la)\b",
                       r"\baspira\w*", r"\bopta(?:n)? a\b", r"\bdepende(?:n)? de (?:si|el|ella|ellos|otros|terceros)\b"]),
         "en": _words([r"\bat stake\b", r"\bfighting (?:for|to)\b", r"\bbattle (?:for|to)\b", r"\bin the race\b", r"\bchasing\b",
                       r"\bplay(?:s|ing)? for\b", r"\bdepends? on (?:itself|themselves|others|other results)\b"])}),
    ClaimClass(
        "SUPERLATIVO", "alto", (),
        "a superlative of history or of the league («nunca», «el mejor de la liga», «récord», «por primera vez»): no code computes one "
        "today, so no fact authorises it",
        {"es": _words([r"\bnunca\b", r"\bjamas\b", r"\bhistoric\w*", r"\brecord\w*", r"\b(?:el|la|los|las) (?:mejor|mejores|peor|peores)\b",
                       r"\bprimera vez\b", r"\bmas (?:goleador|en forma|solido|fuerte)\w* de\b", r"\binedit\w*", r"\bsin precedentes\b",
                       r"\b(?:lider|lideres) absolut\w*"]),
         "en": _words([r"\bnever\b", r"\bhistoric\w*", r"\b(?:a|club|league|all-time|new) records?\b", r"\brecord-\w+",
                       r"\bthe (?:best|worst)\b", r"\bfirst time\b", r"\bever\b", r"\bunprecedented\b", r"\bunmatched\b"])}),
    ClaimClass(
        "RACHA", "medio", ("streak.unbeaten", "streak.winless", "form", "result"),
        "a run of results: a streak, a form, results in a row",
        {"es": _words([r"\bracha\b", r"\bseguid[oa]s\b", r"\bconsecutiv\w*", r"\binvict\w*", r"\bsin (?:perder|ganar|conocer la (?:derrota|victoria))\b",
                       r"\bimbatid\w*"]),
         "en": _words([r"\bstreak\b", r"\bin a row\b", r"\bconsecutive\b", r"\bunbeaten\b", r"\bwinless\b",
                       r"\bwithout (?:a )?(?:win|defeat|loss|victory)\b", r"\brun of\b"])}),
    ClaimClass(
        "DISPONIBILIDAD", "medio", ("absence.out", "absence.doubtful", "news.confirmed", "news.probable", "news.rumour", "unknown.lineups"),
        "who can play: an absence or a doubt as the provider or a news item gives it - a STATE, never a diagnosis",
        {"es": _words([r"\bbajas?\b", r"\bdudas?\b", r"\bdudos[oa]s?\b", r"\blesionad\w*", r"\bsancionad\w*", r"\bausen\w*", r"\bno estara\w*",
                       r"\bse (?:pierde|perdera)\b", r"\bsuspendid[oa]\b", r"\bdisponibles?\b"]),
         "en": _words([r"\bruled out\b", r"\bdoubt\w*", r"\binjur\w*", r"\bsuspend\w*", r"\bmiss(?:es|ing)?\b", r"\babsen\w*", r"\bsidelined\b",
                       r"\bunavailable\b", r"\bavailable\b"])}),
    ClaimClass(
        "RUMOR", "alto", ("news.rumour",),
        "a rumour or conflicting reports: only a fact that IS a rumour, told among the risks and called one",
        {}, section="riesgos"),
    ClaimClass(
        "CIFRA_PRONOSTICO", "alto", ("figure",),
        "a probability: only a figure of forecast-v2 repeated with its citation (figure-text-v1)",
        {}),
    ClaimClass(
        "DETALLE_MEDICO", "alto", (),
        "a diagnosis, a part of the body, a treatment or a time off: never in a chronicle (health-filter-v1)",
        {}),
)
"""The table, in its one order. A new class, a new kind or a new cue is a new version."""

BY_CODE: Final[Mapping[str, ClaimClass]] = {c.code: c for c in CLASSES}
HIGH_RISK: Final = frozenset(c.code for c in CLASSES if c.risk == "alto")
NOT_AUTHORISED: Final = frozenset(c.code for c in CLASSES if not c.authorised_by)


def classes_of_kind(kind: str) -> tuple[str, ...]:
    """The classes a fact of this kind authorises."""
    return tuple(c.code for c in CLASSES if kind in c.authorised_by)


def allowed_classes(kinds: Iterable[str]) -> list[str]:
    """The classes a plan with facts of these kinds may claim: a class enters only with one of its authorising facts."""
    have = set(kinds)
    return [c.code for c in CLASSES if have & set(c.authorised_by)]


def classes_stated(folded: str, lang: str) -> list[str]:
    """The classes whose cues a (folded) sentence carries."""
    return [c.code for c in CLASSES if (p := c.cues.get(lang)) is not None and p.search(folded) is not None]


def authorises(code: str, kinds: Iterable[str]) -> bool:
    """Whether facts of these kinds authorise the class ``code``."""
    c = BY_CODE.get(code)
    return c is not None and bool(set(kinds) & set(c.authorised_by))


def table_hash() -> str:
    """The fingerprint of the table: kept with every plan, so a plan says which table it was made under."""
    body = {"version": VERSION, "kinds": list(KINDS), "classes": [c.as_json() for c in CLASSES]}
    return hashlib.sha256(json.dumps(body, sort_keys=True, ensure_ascii=False).encode()).hexdigest()


def as_table() -> list[dict[str, object]]:
    """The table for the owner's guide and the console: class, risk and the kinds that authorise it."""
    return [{"clase": c.code, "riesgo": c.risk, "hecho_que_la_autoriza": list(c.authorised_by) or ["(ninguno: nunca se autoriza)"],
             "seccion": c.section} for c in CLASSES]


__all__ = ["BY_CODE", "CLASSES", "DESCRIPTIVE", "HIGH_RISK", "KINDS", "NOT_AUTHORISED", "SCENARIO_DECIDED", "VERSION", "ClaimClass",
           "allowed_classes", "as_table", "authorises", "classes_of_kind", "classes_stated", "table_hash"]
