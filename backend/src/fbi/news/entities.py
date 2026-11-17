"""Who an article names, from its title (IA-099, AD-G02): ``news-linker-v1``. The teams only, in a CLOSED world.

The world is the teams of the tracked matches around the pass (three days back, seven ahead: ``fbi.news.pipeline``), with every name the
database knows of each (its own, its short name, its aliases: ``fbi.ai.source_select.Team``). A team is named by a title when ALL the
distinctive words of one of its names are words of the title (``source_select.club_key``: «Atlético Bucaramanga» -> ``{bucaramanga}``). Two
teams of the world that a title names with the same words (homonyms: two «Nacional») are BOTH left out - abstaining is better than guessing.
A name of one distinctive word shorter than four letters is never enough on its own.

Players are not linked here (a title is too short to tell homonyms apart without the squad's second signal): their link comes with the
claims of the article (AD-C06, ``fbi.ai.mentions``), when an authorised source is read. The title is private metadata: it is compared,
never stored again and never sent to a model. Pure."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Final

from fbi.ai.source_select import Team
from fbi.people.identity.names import alias_key

VERSION: Final = "news-linker-v1"
CONFIDENCE: Final = 0.8
MIN_SINGLE_WORD: Final = 4


@dataclass(frozen=True, slots=True)
class Named:
    team_id: int
    name_seen: str
    confidence: float = CONFIDENCE


def _usable(key: frozenset[str]) -> bool:
    return bool(key) and (len(key) >= 2 or len(next(iter(key))) >= MIN_SINGLE_WORD)


def catalogue(teams: Iterable[Team]) -> dict[frozenset[str], set[int]]:
    """Distinctive words of a name -> the teams that have that name (more than one: homonyms)."""
    out: dict[frozenset[str], set[int]] = {}
    for t in teams:
        if t.team_id is None:
            continue
        for key in t.keys:
            if _usable(key):
                out.setdefault(key, set()).add(t.team_id)
    return out


def teams_named(title: str | None, world: dict[frozenset[str], set[int]], names: dict[int, str] | None = None) -> list[Named]:
    """The teams of the world a title names, without homonyms; a name inside a longer one that also matches counts once."""
    words = set(alias_key(title or "").split())
    if not words:
        return []
    hits = [(key, ids) for key, ids in world.items() if key <= words]
    found: dict[int, frozenset[str]] = {}
    doubtful: set[int] = set()
    for key, ids in hits:
        if len(ids) > 1:
            doubtful |= ids
            continue
        (tid,) = tuple(ids)
        if tid not in found or len(key) > len(found[tid]):
            found[tid] = key
    # a key strictly contained in another team's matched key is not a second team («Junior» inside «Junior de Barranquilla» is one)
    out = []
    for tid, key in sorted(found.items()):
        if tid in doubtful:
            continue
        if any(o != tid and key < k for o, k in found.items()):
            continue
        out.append(Named(tid, (names or {}).get(tid, " ".join(sorted(key)))[:120]))
    return out


__all__ = ["CONFIDENCE", "VERSION", "Named", "catalogue", "teams_named"]
