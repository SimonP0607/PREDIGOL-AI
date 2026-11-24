"""The category, language, country and level of a story (IA-100, plan piece AD-G03): ``classify-v2``. By code, from the type of claim, the
entities and the directory - no model (none is needed: the rules cover every story, and a rule can be read and checked). Pure.

CATEGORY - one of the front page's (``vocab.CATEGORIES``), the first rule that applies:

1. the TOPIC: ``fichajes`` -> Fichajes; ``lesiones`` and ``sanciones`` -> Bajas y sanciones; ``declaraciones`` -> Declaraciones;
2. (v2, C-06 1.1) the words of its titles (``GENERAL_RULES``): an award -> Premios; a ceremony, gala or draw -> Ceremonias; a
   controversy, a complaint or a fine -> Polémicas;
3. a national team among its teams -> Selecciones;
4. ``resultados``, ``calendario``, ``alineaciones``, ``convocatorias``, ``reglamento``, ``arbitraje``, ``estadisticas`` -> Competiciones.
   «Resultados y próximos partidos» is NEVER given to a story of the press: that block comes from API-Football's own data (AD-G06/G07);
5. (v2) no team and no player named -> Actualidad (general news);
6. otherwise by its country: Colombia -> Colombia; any other -> Internacional.

LANGUAGE - the most frequent language of its items (the feed's or the page's); without one, the language whose common words its titles
have most (es, en, pt, fr, it, de); without that, the first language of its sources in the directory; at worst ``es`` (the directory's
default, ``source_select.info_of``).

COUNTRY - the country its teams share (as the provider writes it: ``Colombia``); teams of several countries -> ``Internacional``; no team
-> the country of its sources in the directory when they agree; otherwise ``Internacional``.

LEVEL - the ladder of AD-C07 (``fbi.ai.assertions``, ``ladder-v2``) applied to the story's items as assertions of the story's fact: the
authority of each source FOR THIS TYPE OF CLAIM from the directory (``autoridad_por_afirmacion``; a club's ``confirma`` «solo lo propio»
only about its own team), a title written as a rumour is a rumour whatever the source, and two items are ONE origin when they share a
domain, an editorial group or a syndication network, or their titles are near duplicates - so a wire copy reprinted by five outlets is one
origin and never climbs to «Dos orígenes». The rungs map to the store's words: OFICIAL -> oficial, CONFIRMADO -> dos_origenes,
DECLARACION -> declaracion (the statement of one speaker: the outlets that report it are one origin), REPORTE -> un_medio, RUMOR -> rumor.
A story of type ``rumores`` is a rumour, always."""

from __future__ import annotations

import re
from collections import Counter
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import datetime
from typing import Any, Final

from fbi.ai import assertions
from fbi.ai.source_policy import SourcePolicy
from fbi.core.fingerprint import folded
from fbi.news import grouping, vocab
from fbi.people.identity.names import alias_key, names_compatible

VERSION: Final = "classify-v2"
_WORD: Final = re.compile(r"[0-9a-z]+")
COLOMBIA: Final = "Colombia"
INTERNATIONAL: Final = "Internacional"
DEFAULT_LANG: Final = "es"

TOPIC: Final[dict[str, vocab.Category]] = {"fichajes": "fichajes", "lesiones": "bajas_y_sanciones", "sanciones": "bajas_y_sanciones",
                                           "declaraciones": "declaraciones"}
COMPETITION_TYPES: Final = frozenset({"resultados", "calendario", "alineaciones", "convocatorias", "reglamento", "arbitraje",
                                      "estadisticas"})
_GENERAL_WORDS: Final[tuple[tuple[vocab.Category, str], ...]] = (
    ("premios", r"\b(?:balon de oro|ballon d ?or|the best|bota de oro|golden boot|golden ball|premio\w*|premiad\w*|award\w*|"
                r"galardon\w*|pichichi|zamora|jugador del (?:mes|ano)|player of the (?:month|year|season)|mejor jugador|best player)\b"),
    ("ceremonias", r"\b(?:ceremoni\w*|gala|sorteo|homenaje\w*|tribute|inaugura\w*|opening ceremony|despedida|farewell)\b"),
    ("polemicas", r"\b(?:polemic\w*|controvers\w*|escandal\w*|scandal\w*|denuncia\w*|racis\w*|insult\w*|multad\w*|fined|"
                  r"investigad\w*|investigation|protesta\w*|crisis)\b"),
)
GENERAL_RULES: Final[tuple[tuple[vocab.Category, re.Pattern[str]], ...]] = tuple((c, re.compile(p)) for c, p in _GENERAL_WORDS)
"""v2 (C-06 1.1): the general categories by the words of a folded title; the first rule whose words any title of the story has decides."""

LEVEL_OF: Final[dict[str, vocab.Level]] = {"OFICIAL": "oficial", "CONFIRMADO": "dos_origenes", "DECLARACION": "declaracion",
                                           "REPORTE": "un_medio", "RUMOR": "rumor"}

LANG_WORDS: Final[dict[str, frozenset[str]]] = {
    "es": frozenset(["el", "la", "los", "las", "del", "de", "que", "y", "en", "por", "para", "con", "su", "se", "una", "un", "al", "tras", "sin", "ante"]),
    "en": frozenset(["the", "of", "and", "to", "in", "for", "with", "on", "after", "his", "their", "is", "at", "from", "as"]),
    "pt": frozenset(["o", "os", "as", "do", "da", "dos", "das", "em", "no", "na", "que", "para", "com", "por", "um", "uma", "ao"]),
    "fr": frozenset(["le", "la", "les", "des", "du", "de", "et", "pour", "par", "sur", "avec", "dans", "est", "au", "aux"]),
    "it": frozenset(["il", "lo", "gli", "i", "di", "della", "del", "dei", "per", "con", "su", "non", "che", "e"]),
    "de": frozenset(["der", "die", "das", "den", "dem", "des", "ein", "eine", "und", "mit", "von", "zu", "im", "am", "ist", "fur"]),
}


@dataclass(frozen=True, slots=True)
class TeamFacts:
    country: str | None
    is_national: bool
    name: str = ""


@dataclass(frozen=True, slots=True)
class Classified:
    category: vocab.Category
    level: vocab.Level
    lang: str
    country: str
    claim_type: str
    why: str
    """The rule of the level (``fbi.ai.assertions.rung``) and the independent origins counted."""

    def fields(self) -> dict[str, Any]:
        return {"category": self.category, "level": self.level, "lang": self.lang, "country": self.country, "claim_type": self.claim_type}


def guess_lang(titles: Sequence[str | None]) -> str | None:
    words = [w for t in titles for w in folded(t or "").split()]
    if not words:
        return None
    scores = {lang: sum(1 for w in words if w in common) for lang, common in LANG_WORDS.items()}
    best = max(scores.items(), key=lambda kv: (kv[1], kv[0] == DEFAULT_LANG))
    return best[0] if best[1] > 0 else None


def language(items: Sequence[grouping.ItemSignal], source_langs: Sequence[str] = ()) -> str:
    langs = Counter(i.lang for i in items if i.lang)
    if langs:
        return max(langs.items(), key=lambda kv: (kv[1], kv[0] == DEFAULT_LANG, kv[0]))[0]
    return guess_lang([i.title for i in items]) or next(iter(source_langs), DEFAULT_LANG)


def country(items: Sequence[grouping.ItemSignal], teams: Mapping[int, TeamFacts], source_countries: Sequence[str] = ()) -> str:
    found = {(teams[t].country or "").strip() for i in items for t in i.teams if t in teams}
    found.discard("")
    if len(found) == 1:
        return next(iter(found))[:60]
    if len(found) > 1:
        return INTERNATIONAL
    agreed = {c.strip() for c in source_countries if c and c.strip()}
    return next(iter(agreed))[:60] if len(agreed) == 1 else INTERNATIONAL


def general_category(titles: Sequence[str | None]) -> vocab.Category | None:
    """Premios, Ceremonias or Polémicas by the words of the titles (``GENERAL_RULES``), or None."""
    texts = [" ".join(_WORD.findall(folded(t or ""))) for t in titles if t]
    for cat, pattern in GENERAL_RULES:
        if any(pattern.search(text) for text in texts):
            return cat
    return None


def category(kind: str, items: Sequence[grouping.ItemSignal], teams: Mapping[int, TeamFacts], where: str) -> vocab.Category:
    if kind in TOPIC:
        return TOPIC[kind]
    general = general_category([i.title for i in items])
    if general is not None:
        return general
    if any(teams[t].is_national for i in items for t in i.teams if t in teams):
        return "selecciones"
    if kind in COMPETITION_TYPES:
        return "competiciones"
    if not any(i.teams or i.players for i in items):
        return "actualidad"
    return "colombia" if where == COLOMBIA else "internacional"


def _authority(src: assertions.SourceFacts, word: str, team_names: Sequence[str], title: str | None) -> tuple[str, str]:
    """``assertions.authority_for`` for a type of claim written in the directory's own word (the store's types are)."""
    if assertions.RUMOR_CUES.search(" ".join(alias_key(title or "").split())):
        return "solo_rumor", "rumor_cue"
    if not src.authority:
        return "desconocida", "not_in_directory"
    entry = src.authority.get(word) or {}
    level = str(entry.get("level") or "desconocida")
    note = alias_key(entry.get("note") or "")
    if level == "confirma" and ("propio" in note or (src.source_type == "oficial" and src.clubs)):
        own = [src.name, *src.clubs]
        if not team_names or not names_compatible(own, team_names, person=False):
            return "informa", "confirms_only_its_own"
    return level, f"directory:{word}"


def _unsigned(h: int | None) -> int | None:
    return None if h is None else h & ((1 << 64) - 1)


def as_assertions(items: Sequence[grouping.ItemSignal], kind: str, *, policy: SourcePolicy | None, team_names: Sequence[str],
                  story_key: str) -> list[assertions.Assertion]:
    out = []
    for i in items:
        src = assertions.source_facts(policy, i.domain)
        authority, why = _authority(src, kind, team_names, i.title)
        out.append(assertions.Assertion(
            subject_kind="story", subject_id=0, team_id=None, claim_type=kind, url=f"https://{i.domain}/", source=src, authority=authority,
            authority_why=why, seen_at=i.seen_at, published_at=i.published_at,
            # one speaker is one origin, however many outlets report his words
            attributed_to=f"speaker:{story_key}" if kind == "declaraciones" else None, text_hash=_unsigned(i.hash)))
    return out


def level(items: Sequence[grouping.ItemSignal], kind: str, *, policy: SourcePolicy | None, team_names: Sequence[str] = (),
          story_key: str = "st-story") -> tuple[vocab.Level, str]:
    if kind == "rumores" or not items:
        return "rumor", "a rumour is a rumour"
    found = as_assertions(items, kind, policy=policy, team_names=team_names, story_key=story_key)
    rung, why = assertions.rung(found)
    origins = assertions.independent_origins([a for a in found if a.lifts])
    return LEVEL_OF[rung], f"{why}; independent origins {origins}"


def classify(items: Sequence[grouping.ItemSignal], *, policy: SourcePolicy | None, teams: Mapping[int, TeamFacts],
             story_key: str = "st-story", at: datetime | None = None) -> Classified:
    """Every field of a story at once (see the module). ``teams``: what the database knows of the teams its items name."""
    kind = grouping.story_kind(items)
    langs: list[str] = []
    countries: list[str] = []
    if policy is not None:
        for i in items:
            s = policy.by_domain.get(i.domain)
            if s is not None:
                langs += [x.strip().lower() for x in str(s.record.get("idiomas") or "").replace(",", ";").split(";") if x.strip()]
                if s.country:
                    countries.append(s.country)
    where = country(items, teams, countries)
    names = [teams[t].name for i in items for t in i.teams if t in teams and teams[t].name]
    lvl, why = level(items, kind, policy=policy, team_names=names, story_key=story_key)
    return Classified(category(kind, items, teams, where), lvl, language(items, langs)[:3], where, kind, why)


__all__ = ["COLOMBIA", "INTERNATIONAL", "LEVEL_OF", "VERSION", "Classified", "TeamFacts", "as_assertions", "category", "classify", "country",
           "guess_lang", "language", "level"]
