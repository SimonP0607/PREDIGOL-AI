"""The linking of mentions (IA-088, plan piece AD-C06): which player, team or coach of a match a passage of a page names - or nobody.

WHY. The validator of Research v2 accepts ANY word of a name (``fbi.ai.contracts.claim.name_tokens``): «Copa del **Rey**» counts as naming
Oriol Rey and «Jesús de **Miguel**» as naming Rodrigo Miguel Ferreira Rêgo (RV2b, 15 Nov 2026). And the extractor sees at most 30 players a
team (``entity_research.MAX_PLAYERS``): a player outside the thirty can never be the subject of a claim (24 % of the players of the facts in
clubs, 39 % in national teams, RV2b). A false link turns a fact of another man into an absence of ours; so this module abstains whenever the
name is not unequivocal - abstaining is worth more than guessing.

``name-match-v2`` (``VERSION``). A passage names a candidate when it holds one of these FORMS of one of his names (the provider's name, his
first and last name, the aliases and transliterations of ``core.entity_aliases``), compared by ``fbi.people.identity.names.alias_key`` (lower
case, no accents on Latin letters, other scripts keep their letters):

1. the whole sporting name, its words in a row («Oriol Rey», «Kevin De Bruyne», an alias «Месси»);
2. a DISTINCTIVE surname alone - the last word of a name that is not a particle («Jr.», «de»): «Mbappé», «Cásseres» in «Cásseres Jr.»;
3. when the surname is NOT distinctive (``non_distinctive``: a word that is also a club, a city, a cup, a month or a common word - «Rey»,
   «Copa», «Real», «Santos», «Valencia», «León» - or a word of the names of the teams and the competition of the match), two words of the
   name in a row («Oriol Rey»), never the surname alone.

A team is named by its whole name, an alias, or a word of its own name that is not generic («FC», «Club», «Real»...) and that the other team
of the match does not have.

HOMONYMS. When the form that matched (a surname) is also a form of another candidate of the catalogue, the passage must hold a second signal
that tells them apart - another word of his own names, or the initial of his given name right before the surname («K. Mbappé»). Without it
NOBODY is linked (``ambiguous``): a property test holds that a homonym without a second signal is never linked.

What it does not do: guess. A page in Cyrillic links a player written in Latin letters only through an alias in Cyrillic; there is no
transliteration by code. Injuries: a link says who, never what the injury is.

Pure: nothing is read or written. ``fbi.ai.unified_research`` builds the catalogue (the whole squad - no cap - recent line-ups, signings and
loans, the latest call-up of a national team, the provider's absences, and the aliases) and uses ``mentions_in`` to choose the windows of a page
and ``validate`` to check every claim a model wrote.
"""

from __future__ import annotations

from collections.abc import Iterable, Sequence
from dataclasses import dataclass, field
from itertools import pairwise
from typing import Final, Literal

from fbi.people.identity.names import CLUB_WORDS, alias_key
from fbi.people.identity.names import PARTICLES as NAME_PARTICLES

VERSION: Final = "name-match-v2"
Kind = Literal["PLAYER", "TEAM", "COACH"]

PARTICLES: Final = NAME_PARTICLES | frozenset({"sr", "jnr", "snr", "iv"})
"""Words of a name that never tie a passage to anyone («de», «Jr»)."""
FIXED_NON_DISTINCTIVE: Final = frozenset({
    # the plan's list (AD-C06) and the words that are clubs, cities, cups or titles in the eight languages of the search
    "rey", "copa", "real", "santos", "valencia", "leon", "cruz", "paz", "luz", "sol", "mar", "rio", "rios", "costa", "rica", "rico",
    "victoria", "union", "nacional", "national", "city", "united", "san", "santa", "santo", "cordoba", "granada", "rosario", "madrid",
    "sevilla", "porto", "lima", "bolivar", "independiente", "libertad", "olimpia", "america", "colon", "junior", "quilmes", "campos",
    "bravo", "blanco", "negro", "king", "cup", "pokal", "coupe", "coppa", "taca", "kupa", "league", "liga", "lega", "ligue", "serie",
    "premier", "super", "primera", "segunda", "final", "derby", "clasico", "classico", "club", "sport", "sporting", "athletic", "atletico",
    "deportivo", "estudiantes", "argentinos", "racing", "river", "boca", "palmeiras", "flamengo", "inter", "milan", "roma", "lazio",
    "torino", "napoli", "genoa", "ajax", "celtic", "rangers", "wolves", "everton", "chelsea", "arsenal", "brighton", "fulham",
    # months and week days that are also surnames (Julio, Domingo, Mayo, April...)
    "enero", "febrero", "marzo", "abril", "mayo", "junio", "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
    "january", "february", "march", "april", "may", "june", "july", "august", "september", "october", "november", "december",
    "lunes", "martes", "miercoles", "jueves", "viernes", "sabado", "domingo", "sunday", "monday", "friday", "saturday",
    # common words that are surnames in some country
    "will", "young", "white", "black", "green", "gray", "grey", "long", "little", "rose", "hope", "said", "best", "bueno", "malo",
    "alegre", "fino", "forte", "gol", "goal", "uno", "dos", "tres", "primo", "nunez", "sur", "norte", "este", "oeste",
})
"""Words that a passage holds without naming anybody. The list ``non_distinctive`` uses adds to it the words of the match's own team and
competition names (generated from the catalogue): a page about «Valencia» never names a player called Valencia by that word alone."""
MIN_SURNAME: Final = 3


def words(text: object) -> list[str]:
    """The words of a text as names are compared (``alias_key``)."""
    return alias_key(text).split()


def meaningful(name: str) -> list[str]:
    """The words of a name that can tell who: not a particle, not a single letter (an initial)."""
    return [w for w in words(name) if w not in PARTICLES and len(w) >= 2]


def surname_of(name: str) -> str:
    """The last meaningful word of a name («D. Cásseres Jr.» -> «casseres»), or empty."""
    parts = meaningful(name)
    return parts[-1] if parts else ""


@dataclass(frozen=True, slots=True)
class Candidate:
    """Someone a passage may name: a player (``id`` is the provider's), a team (ours) or a coach (``id`` the team's: the coach OF a team)."""

    kind: Kind
    id: int
    team_id: int
    names: tuple[str, ...]
    """Every name: the provider's first, then first + last, then the aliases (in any script)."""
    side: str = ""
    sources: tuple[str, ...] = ()
    """Why he is a candidate (``squad``, ``season``, ``lineup``, ``transfer``, ``absence``...): for the audit, never for the link."""

    @property
    def name(self) -> str:
        return self.names[0] if self.names else ""

    @property
    def surnames(self) -> frozenset[str]:
        return frozenset(s for n in self.names if (s := surname_of(n)) and len(s) >= MIN_SURNAME)

    @property
    def tokens(self) -> frozenset[str]:
        return frozenset(w for n in self.names for w in meaningful(n))


@dataclass(frozen=True, slots=True)
class Mention:
    who: Candidate
    form: str
    """``full`` (the whole name), ``surname`` (a distinctive surname), ``pair`` (two words of the name in a row), ``team_word``."""
    position: int
    """The index of the first word of the form in the passage."""


@dataclass(frozen=True, slots=True)
class Catalogue:
    """The candidates of a match and the words that do not tell anyone (``non_distinctive``)."""

    candidates: tuple[Candidate, ...]
    stop: frozenset[str] = field(default_factory=frozenset)

    @classmethod
    def of(cls, candidates: Iterable[Candidate], *, context_names: Iterable[str] = ()) -> Catalogue:
        """The catalogue, without a candidate twice (the first one of a kind and id wins), and its list of words that tell nobody."""
        seen: set[tuple[str, int]] = set()
        out: list[Candidate] = []
        for c in candidates:
            if (c.kind, c.id) not in seen and c.names:
                seen.add((c.kind, c.id))
                out.append(c)
        teams = [n for c in out if c.kind == "TEAM" for n in c.names]
        return cls(tuple(out), non_distinctive([*teams, *context_names]))

    def by_key(self, kind: str, entity_id: int) -> Candidate | None:
        return next((c for c in self.candidates if c.kind == kind and c.id == entity_id), None)

    @property
    def players(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.kind == "PLAYER")

    @property
    def teams(self) -> tuple[Candidate, ...]:
        return tuple(c for c in self.candidates if c.kind == "TEAM")


def non_distinctive(context_names: Iterable[str]) -> frozenset[str]:
    """The fixed list, the generic words of club names and every word of the names given (the teams and the competition of the match, a
    stadium, a city): generated from the catalogue, so «Cruz» is not distinctive in a match of Cruz Azul and «Valencia» in one of Valencia."""
    generated = {w for n in context_names for w in words(n) if len(w) >= 2}
    return FIXED_NON_DISTINCTIVE | {alias_key(w) for w in CLUB_WORDS} | generated


def _runs(seq: Sequence[str], text: Sequence[str]) -> list[int]:
    """The positions where ``seq`` appears in ``text`` as consecutive words."""
    n = len(seq)
    if n == 0 or n > len(text):
        return []
    return [i for i in range(len(text) - n + 1) if list(text[i:i + n]) == list(seq)]


def _team_words(team: Candidate, catalogue: Catalogue) -> frozenset[str]:
    others = {w for t in catalogue.teams if t.id != team.id for w in t.tokens}
    return frozenset(w for w in team.tokens if len(w) >= 3 and w not in others and w not in FIXED_NON_DISTINCTIVE
                     and w not in {alias_key(x) for x in CLUB_WORDS})


def _forms(who: Candidate, text: Sequence[str], catalogue: Catalogue) -> list[Mention]:
    """Every form of ``who`` the passage holds (before the homonym rule)."""
    out: list[Mention] = []
    for name in who.names:
        seq = words(name)
        if len([w for w in seq if w not in PARTICLES]) >= 2 or (who.kind != "PLAYER" and seq):
            out.extend(Mention(who, "full", i) for i in _runs(seq, text))
    if who.kind == "TEAM":
        own = _team_words(who, catalogue)
        out.extend(Mention(who, "team_word", i) for i, w in enumerate(text) if w in own)
        return out
    if who.kind == "COACH":
        return out  # a coach is named by his whole name only: his surname alone is the speaker of half the quotes of a page
    for s in who.surnames:
        if s not in catalogue.stop:
            out.extend(Mention(who, "surname", i) for i, w in enumerate(text) if w == s)
    for name in who.names:
        parts = meaningful(name)
        for a, b in pairwise(parts):
            out.extend(Mention(who, "pair", i) for i in _runs([a, b], text))
    for name in who.names:  # a one-word name («Pedri», «Neymar»), distinctive
        parts = meaningful(name)
        if len(parts) == 1 and len(parts[0]) >= MIN_SURNAME and parts[0] not in catalogue.stop:
            out.extend(Mention(who, "surname", i) for i, w in enumerate(text) if w == parts[0])
    return out


def _second_signal(who: Candidate, rivals: Sequence[Candidate], text: Sequence[str], at: int, matched: str) -> bool:
    """Whether the passage tells ``who`` from the candidates that share the matched word: another word of his own names that they do not
    have, anywhere in the passage, or the initial of one of his given names right before the surname («K. Mbappé»)."""
    theirs = {w for r in rivals for w in r.tokens}
    mine = (who.tokens - theirs) - {matched}
    if mine & set(text):
        return True
    if at > 0 and len(text[at - 1]) == 1:
        initial = text[at - 1]
        given = {meaningful(n)[0][0] for n in who.names if len(meaningful(n)) >= 2}
        rival_given = {meaningful(n)[0][0] for r in rivals for n in r.names if len(meaningful(n)) >= 2}
        return initial in given and initial not in rival_given
    return False


def mentions_in(text: object, catalogue: Catalogue) -> list[Mention]:
    """The candidates a passage names without doubt, one mention each (the first), in the order they appear. A candidate whose only form is
    shared with another candidate, without a second signal, is not named - and neither is the other one by that form."""
    seq = words(text)
    if not seq:
        return []
    found: dict[tuple[str, int], Mention] = {}
    by_word: dict[str, list[Candidate]] = {}
    for c in catalogue.candidates:
        if c.kind == "PLAYER":
            for s in c.tokens:
                by_word.setdefault(s, []).append(c)
    for c in catalogue.candidates:
        for m in sorted(_forms(c, seq, catalogue), key=lambda m: (m.form != "full", m.position)):
            if m.form == "surname":
                matched = seq[m.position]
                rivals = [r for r in by_word.get(matched, []) if r.id != c.id]
                if rivals and not _second_signal(c, rivals, seq, m.position, matched):
                    continue
            if m.form == "pair":
                a, b = seq[m.position], seq[m.position + 1]
                rivals = [r for r in catalogue.players if r.id != c.id and _runs([a, b], [w for n in r.names for w in meaningful(n)])]
                if rivals and not _second_signal(c, rivals, seq, m.position, b):
                    continue
            key = (c.kind, c.id)
            if key not in found or m.position < found[key].position:
                found[key] = m
            break
    return sorted(found.values(), key=lambda m: m.position)


def validate(quote: object, who: Candidate, catalogue: Catalogue) -> str | None:
    """Why ``quote`` does not name ``who`` without doubt (``name-match-v2``), or None when it does. ``quote_without_subject``: none of his forms
    is in it (a non-distinctive surname alone is not one of them); ``ambiguous_subject``: his form is also another candidate's and nothing tells
    them apart; ``quote_too_short``: his name and nothing else."""
    seq = words(quote)
    named = {(m.who.kind, m.who.id) for m in mentions_in(quote, catalogue)}
    if (who.kind, who.id) not in named:
        raw = _forms(who, seq, catalogue)
        return "ambiguous_subject" if raw else "quote_without_subject"
    if who.kind == "PLAYER" and all(w in who.tokens or w in PARTICLES or len(w) == 1 for w in seq):
        return "quote_too_short"
    return None


def legacy_tokens_link(quote: object, name: str) -> bool:
    """What the validator of Research v2 accepted (``claim.name_tokens``: any word of three letters or more of the name): kept only to measure
    how many of its links ``name-match-v2`` refuses."""
    from fbi.ai.contracts.claim import name_tokens
    from fbi.ai.contracts.claim import words as claim_words

    tokens = name_tokens(name)
    return any(w in tokens for w in claim_words(str(quote or "")))


__all__ = ["VERSION", "Candidate", "Catalogue", "Mention", "legacy_tokens_link", "mentions_in", "non_distinctive", "surname_of",
           "validate"]
