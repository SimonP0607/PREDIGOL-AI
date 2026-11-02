"""A referee's name as the provider wrote it, read once: the one parser and the relations between spellings (plan F3).

The provider's field is a single string and it comes in four shapes, all of them in the stored history::

    M. Oliver                         an initial and a surname
    Michael Oliver, England           a name and its country
    Brooks, John                      SURNAME first, given names after
    Hilfer, Leandro Rey, Argentina    surname first, then the country

``fixture_ingestion`` cuts the string at the FIRST comma (``split_referee``), so a surname-first referee reached
``core.fixture_facts`` as ``referee = 'Brooks'`` and ``referee_country = 'John, England'``: 291 of the 41,507 rows that carry
a country (22 Oct 2026). Putting the two columns back together gives the string the provider wrote, byte for byte, so this
module starts from that and decides what it says. Nothing else in the system parses a referee.

A last part that is a country (``fbi.people.countries``) is the country; any other last part after a first comma is the given
name of a surname-first spelling. The name is returned in the order "given names, surname", which is how the other spellings
of the same person are written, so ``Hilfer, Leandro Rey, Argentina`` and ``Leandro Rey Hilfer`` meet.

The RELATIONS between two spellings - one is an initial and the surname of the other, one is the other with a middle name, one
is a typing variant - are here too, as pure functions over the normalised keys, because the rules that decide who is who
(``fbi.people.referee_identity``) are built out of them and the tests state them one by one.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from fbi.people.countries import country_key, plain

LAYOUTS: Final = ("name", "name_country", "surname_given", "surname_given_country")


@dataclass(frozen=True, slots=True)
class ParsedReferee:
    """What one provider string says."""

    display: str
    """The name, given names first ('Leandro Rey Hilfer'), in the case the provider used."""
    key: str
    """The name compared: lower case, no accents or punctuation ('leandro rey hilfer')."""
    country: str | None
    """The country the string names, as a country key ('argentina'); None when it names none."""
    layout: str


def provider_string(referee: str | None, referee_country: str | None) -> str | None:
    """The string the provider wrote, put back together from the two columns ``fixture_facts`` cut it into."""
    name = (referee or "").strip()
    if not name:
        return None
    country = (referee_country or "").strip()
    return f"{name}, {country}" if country else name


def parse_referee(referee: str | None, referee_country: str | None = None) -> ParsedReferee | None:
    """Read a referee from the two columns of ``core.fixture_facts``; None when there is no name at all."""
    raw = provider_string(referee, referee_country)
    if raw is None:
        return None
    parts = [" ".join(p.split()) for p in raw.split(",")]
    parts = [p for p in parts if p]
    if not parts:
        return None
    country: str | None = None
    if len(parts) >= 2:
        country = country_key(parts[-1])
        if country is not None:
            parts = parts[:-1]
    elif country_key(parts[0]) is not None:
        return None  # the provider wrote a country and no name
    if len(parts) == 1:
        display, layout = parts[0], ("name_country" if country else "name")
    else:
        # A comma after the surname: 'Brooks, John' reads 'John Brooks'; a third part (a second given name) follows the first.
        display = " ".join(parts[1:] + parts[:1])
        layout = "surname_given_country" if country else "surname_given"
    key = plain(display)
    if not key:
        return None
    return ParsedReferee(display=display, key=key, country=country, layout=layout)


# ── relations between spellings (all over keys) ──────────────────────────────────────────────────────────────────────


def tokens(key: str) -> list[str]:
    return key.split()


def is_initial_form(key: str) -> bool:
    """'m oliver': an initial and a surname. Two or more words, the first of them one letter."""
    t = tokens(key)
    return len(t) >= 2 and len(t[0]) == 1


def surname_tail(key: str) -> str:
    """The last word: where two spellings of one person agree before anything else does."""
    t = tokens(key)
    return t[-1] if t else ""


def initial_matches_full(initial_key: str, full_key: str) -> bool:
    """'m oliver' is a spelling of 'michael oliver'; 'j sanchez martinez' of 'jose maria sanchez martinez'.

    The first word of the initial form is the first letter of the full name, and the rest of it is the END of the full name
    (a middle given name is allowed to be missing, a surname is not). The full name is a full name: two or more words, the
    first of them longer than a letter.
    """
    it, ft = tokens(initial_key), tokens(full_key)
    if len(it) < 2 or len(it[0]) != 1 or len(ft) < 2 or len(ft[0]) < 2 or ft[0][0] != it[0]:
        return False
    rest = it[1:]
    return len(rest) <= len(ft) - 1 and ft[len(ft) - len(rest):] == rest


def is_extension(a: str, b: str) -> bool:
    """'danny makkelie' and 'danny desmond makkelie': two full names that begin and end with the same words, the shorter
    being the longer without some of its middle words. One person written twice."""
    ta, tb = tokens(a), tokens(b)
    if len(ta) > len(tb):
        ta, tb = tb, ta
    if a == b or len(ta) < 2 or len(ta[0]) < 2 or len(tb[0]) < 2 or ta[0] != tb[0] or ta[-1] != tb[-1]:
        return False
    rest = iter(tb)
    return all(word in rest for word in ta)


def names_conflict(a: str, b: str) -> bool:
    """Two FULL names that cannot be one person: different names that are neither one the other with a middle name nor a
    typing variant of it (``andres rojas`` / ``antonio rojas``). An initial form conflicts with nothing: it says too little."""
    if a == b or is_initial_form(a) or is_initial_form(b):
        return False
    return not (is_extension(a, b) or is_spelling_variant(a, b))


def _edit_distance_at_most(a: str, b: str, limit: int) -> bool:
    if abs(len(a) - len(b)) > limit:
        return False
    prev = list(range(len(b) + 1))
    for i, ca in enumerate(a, 1):
        cur = [i]
        for j, cb in enumerate(b, 1):
            cur.append(min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (ca != cb)))
        if min(cur) > limit:
            return False
        prev = cur
    return prev[-1] <= limit


def is_spelling_variant(a: str, b: str) -> bool:
    """'christian ballweg' / 'cristian ballweg', 'vassilios fotias' / 'vassilis fotias': the same words but for one that
    differs by a couple of letters and begins alike. Suggests, never decides: two different people can be a letter apart."""
    ta, tb = tokens(a), tokens(b)
    if a == b or len(ta) != len(tb) or len(ta) < 2 or len(ta[0]) < 2 or len(tb[0]) < 2:
        return False
    diff = [(x, y) for x, y in zip(ta, tb, strict=True) if x != y]
    if len(diff) != 1:
        return False
    x, y = diff[0]
    return x[0] == y[0] and min(len(x), len(y)) >= 4 and _edit_distance_at_most(x, y, 2)
