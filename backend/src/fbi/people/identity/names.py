"""One way to compare names (AD-H02): the key every alias is stored and looked up by, and the checks the identity rules use.

``alias_key`` is ``fbi.people.countries.plain`` extended to every script: lower case, no accents on Latin letters, no
punctuation, one space between words - ``James Rodríguez`` and ``James Rodriguez`` give ``james rodriguez`` - but a Cyrillic,
Arabic or Japanese name keeps its letters (``plain`` would erase them) and its own marks (a Japanese voicing mark is a different
sound, not an accent). Latin text gives exactly what ``plain`` gives, so a key made here meets the referee keys of F3.

A name never links by itself (Doc 3: "nunca solo por nombre"). What the rules ask of a name is only that it does not CONTRADICT
an identity that came by id: ``names_compatible`` says whether two sets of names share a surname, or an initial and a surname.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Iterable
from typing import Final

_LETTERS: Final = str.maketrans({"\u00df": "ss", "\u00f8": "o", "\u0111": "d", "\u0142": "l", "\u00e6": "ae",
                                 "\u0153": "oe", "\u00f0": "d", "\u00fe": "th", "\u0131": "i"})
_APOSTROPHES: Final = re.compile("['`\u00b4\u2019\u2018\u02bc]")
_NON_WORD: Final = re.compile(r"[\W_]+")

PARTICLES: Final = frozenset({"de", "da", "do", "dos", "das", "del", "della", "di", "du", "la", "le", "van", "von", "der",
                              "den", "ter", "ten", "y", "e", "al", "el", "bin", "ben", "ibn", "jr", "junior", "filho",
                              "neto", "sobrinho", "ii", "iii"})
"""Words that are part of a name but say nothing about who: never the token two names are judged to share."""

CLUB_WORDS: Final = frozenset({"fc", "cf", "sc", "ac", "ca", "cd", "cs", "fk", "sk", "nk", "bk", "if", "afc", "club",
                               "clube", "football", "futbol", "fútbol", "calcio", "sporting", "athletic", "atletico",
                               "deportivo", "sport", "sports", "real", "united", "city", "the", "1", "ii", "u19", "u20",
                               "u21", "u23", "women", "w", "de", "la", "el", "del", "do", "da", "and", "of", "stadium",
                               "estadio", "stadion", "stade", "arena", "park", "league", "liga", "cup", "copa",
                               "primera", "division", "serie", "national", "team"})
"""Words that a team, competition or stadium name has in common with thousands of others."""


def _is_latin(ch: str) -> bool:
    o = ord(ch)
    return o < 0x0250 or 0x1E00 <= o <= 0x1EFF


def alias_key(text: object) -> str:
    """The key a name is stored and compared by. Empty for a name with no letter or digit."""
    decomposed = unicodedata.normalize("NFKD", str(text or ""))
    kept: list[str] = []
    base_latin = False
    for ch in decomposed:
        if unicodedata.combining(ch):
            if base_latin:
                continue  # an accent on a Latin letter
            kept.append(ch)
            continue
        base_latin = _is_latin(ch)
        kept.append(ch)
    s = unicodedata.normalize("NFC", "".join(kept)).casefold().translate(_LETTERS)
    s = _APOSTROPHES.sub("", s)
    return " ".join(_NON_WORD.sub(" ", s).split())


def tokens(text: object) -> list[str]:
    return alias_key(text).split()


SCRIPTS: Final = ("latin", "cyrillic", "greek", "arabic", "hebrew", "cjk", "hangul", "other")


def script_of(text: str) -> str:
    """The writing system of a name, by its first letter: what tells a transliteration from a spelling."""
    for ch in text:
        if not ch.isalpha():
            continue
        if _is_latin(ch):
            return "latin"
        name = unicodedata.name(ch, "")
        for prefix, script in (("CYRILLIC", "cyrillic"), ("GREEK", "greek"), ("ARABIC", "arabic"), ("HEBREW", "hebrew"),
                               ("CJK", "cjk"), ("HIRAGANA", "cjk"), ("KATAKANA", "cjk"), ("HANGUL", "hangul")):
            if name.startswith(prefix):
                return script
        return "other"
    return "other"


def _person_tokens(names: Iterable[str | None]) -> tuple[set[str], set[tuple[str, str]]]:
    """The surname-like words of a person's names, and the (initial, word) pairs of names written as an initial and a
    surname (``M. Salah`` -> ('m', 'salah')). A surname-like word has two letters or more, is not a particle and is not the
    FIRST word of a name of several words (a given name: two Mohameds are not one man); a one-word name (``Pedri``,
    ``Sy``) is all surname."""
    words: set[str] = set()
    initials: set[tuple[str, str]] = set()
    for name in names:
        if not name:
            continue
        parts = alias_key(str(name).replace(".", ". ")).split()
        meaningful = [p for p in parts if len(p) >= 2 and p not in PARTICLES]
        if len(meaningful) == 1:
            words.add(meaningful[0])
        for i, part in enumerate(parts):
            if len(part) == 1 and i + 1 < len(parts):
                initials.update((part, w) for w in parts[i + 1:] if len(w) >= 2 and w not in PARTICLES)
            elif i > 0 and len(part) >= 2 and part not in PARTICLES:
                words.add(part)
    return words, initials


def names_compatible(ours: Iterable[str | None], theirs: Iterable[str | None], *, person: bool = True) -> bool:
    """Whether two sets of names could be the same entity: they share a meaningful word (a surname for a person), or an
    initial and a surname of one fit a full name of the other. ``False`` is a doubt for a person, never a decision.

    ``person=False`` (teams, competitions, stadiums) ignores the words every club has (``FC``, ``Club``, ``Real``...)."""
    ours, theirs = list(ours), list(theirs)
    if {alias_key(n) for n in ours if n} & {alias_key(n) for n in theirs if n}:
        return True
    if person:
        w1, i1 = _person_tokens(ours)
        w2, i2 = _person_tokens(theirs)
        if w1 & w2:
            return True
        full1 = {alias_key(n) for n in ours if n}
        full2 = {alias_key(n) for n in theirs if n}
        for initial, word in i1:
            if any(_fits(initial, word, f) for f in full2):
                return True
        return any(_fits(initial, word, f) for initial, word in i2 for f in full1)
    a = {t for n in ours for t in tokens(n) if t not in CLUB_WORDS and len(t) >= 3}
    b = {t for n in theirs for t in tokens(n) if t not in CLUB_WORDS and len(t) >= 3}
    if a & b:
        return True
    return any(is_acronym_of(x, y) for x in ours if x for y in theirs if y) or any(
        is_acronym_of(y, x) for x in ours if x for y in theirs if y)


def _initials(name: str) -> str:
    """The letters an acronym of ``name`` is made of: the first letter of each word, every letter of a word that is
    itself an acronym (``Hellerup IK`` -> ``hik``)."""
    out = []
    for word in str(name).replace("-", " ").split():
        letters = alias_key(word).replace(" ", "")
        if not letters:
            continue
        out.append(letters if word.isupper() and len(letters) <= 4 else letters[0])
    return "".join(out)


def is_acronym_of(short: str, name: str) -> bool:
    """``QPR`` and ``Queens Park Rangers``, ``VVOG`` and ``Voetbal Vereniging Ons Genoegen``: the short name, all capitals,
    is the initials of the long one in order (some words of the long one may be skipped, none of the short one)."""
    compact = alias_key(short).replace(" ", "")
    if not 2 <= len(compact) <= 6 or not short.replace(".", "").replace(" ", "").isupper():
        return False
    if len(name.split()) < 2:
        return False
    initials = _initials(name)
    it = iter(initials)
    return all(ch in it for ch in compact)


def _fits(initial: str, word: str, full: str) -> bool:
    parts = full.split()
    return word in parts and any(p.startswith(initial) for p in parts if p != word)
