"""Which ground and which city a name points at: the comparison venue evidence is read with.

The provider spells one ground several ways and keeps one venue id for different grounds, so a place is compared by
what its name distinctly says, never by an id alone (``fbi.api.repositories.fixtures.fixture_venue`` says why). The
neutral-venue rule (``fbi.competitions.neutral``) reads places the same way, so what the match page calls "the same
ground" and what the rule calls "the same ground" cannot drift apart."""

from __future__ import annotations

import re
import unicodedata

GENERIC_PLACE_WORDS = frozenset({
    "estadio", "estadi", "estadium", "stadium", "stadio", "stade", "stadion", "stadionul", "stadyumu", "stadyum",
    "arena", "park", "campo", "field", "ground", "municipal", "sports", "sport", "complex", "centre", "center",
    "de", "del", "la", "el", "los", "las", "do", "da", "dos", "das", "di", "the", "of", "y", "e", "and",
})
"""Words that name the kind of place, not which one: 'Estadio Diego Armando Maradona' and 'Diego Armando Maradona'
are one ground, 'Estadio Banorte' and 'Estadio Azteca' are not said to be (a rename is not guessed)."""

_NON_WORD = re.compile(r"[^a-z0-9]+")


def _plain(x: object) -> str:
    """Lower case, no accents: 'Ciudad de Lanús' -> 'ciudad de lanus'."""
    return unicodedata.normalize("NFKD", str(x or "")).encode("ascii", "ignore").decode().lower()


def place_words(x: object) -> frozenset[str]:
    """The words of a ground's name that say which ground it is (the generic ones dropped)."""
    return frozenset(w for w in _NON_WORD.split(_plain(x)) if w and w not in GENERIC_PLACE_WORDS)


def same_place(a: object, b: object) -> bool:
    """Two spellings of one ground: case, accents, punctuation and the generic words aside, the distinctive words of
    the shorter name all appear in the longer ('Estadio Marcelo Bielsa' / 'Estadio Marcelo Alberto Bielsa')."""
    wa, wb = place_words(a), place_words(b)
    if not wa or not wb:
        return False
    short, long_ = (wa, wb) if len(wa) <= len(wb) else (wb, wa)
    return short <= long_


def _trailing_group(text: str) -> tuple[str, str] | None:
    """('Stadion Feijenoord', 'Rotterdam') for 'Stadion Feijenoord (Rotterdam)'; the group is the LAST top-level one, so
    'New Suez Stadium (as-Suways (Suez))' gives ('New Suez Stadium', 'as-Suways (Suez)'). None when the text does not end
    in a balanced group, or when the group is all there is."""
    s = text.strip()
    if not s.endswith(")"):
        return None
    depth = 0
    for i in range(len(s) - 1, -1, -1):
        if s[i] == ")":
            depth += 1
        elif s[i] == "(":
            depth -= 1
            if depth == 0:
                head, inner = s[:i].strip(), s[i + 1:-1].strip()
                return (head, inner) if head and inner else None
    return None


def split_place(name: object, city: object = None) -> tuple[str | None, str | None]:
    """A ground's name and city as a payload gives them, the trailing parenthetical taken out of the name: the provider
    often writes 'Stadion Feijenoord (Rotterdam)' with no city beside it. The parenthetical is the city when none is
    given; when one is, it is dropped ('Estadio Universitario (UANL)', city Monterrey). Anything else is returned as it
    came, stripped, with None for what is empty."""
    n = None if name is None else (str(name).strip() or None)
    c = None if city is None else (str(city).strip() or None)
    if n:
        group = _trailing_group(n)
        if group:
            n, inner = group
            c = c or inner
    return n, c


def place_key(x: object) -> str:
    """A name or a city as a comparison key: case, accents and punctuation aside ('Saint-Denis', 'saint denis' and
    'Saint Denis' are one). Empty when there is nothing to compare."""
    return " ".join(w for w in _NON_WORD.split(_plain(x)) if w)


def cities_compatible(a: object, b: object) -> bool:
    """Two spellings that do not contradict each other: equal, one of them missing, or the words of one inside the
    other ('Newcastle' / 'Newcastle upon Tyne', 'Stoke' / 'Stoke-on-Trent, Staffordshire'). 'Torino' and 'Turin' are not
    said to be one city: a name in another language is not guessed."""
    ka, kb = place_key(a), place_key(b)
    if not ka or not kb or ka == kb:
        return True
    wa, wb = set(ka.split()), set(kb.split())
    return wa <= wb or wb <= wa


def cities_agree(a: object, b: object) -> bool:
    """Both cities are given and they do not contradict each other. Where a city decides something that is not the
    safe side (the country of a ground), a missing city is not agreement: 'The Vale Stadium' of Birmingham shares its one
    distinctive word with a ground of that name in Portugal."""
    return bool(place_key(a)) and bool(place_key(b)) and cities_compatible(a, b)
