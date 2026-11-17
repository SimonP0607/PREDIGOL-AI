"""The validator of ``link-v1`` (IA-122, AD-G08): whether a fact may be linked to an evaluation of a match, and how it bears on it. Pure.

THE THREE CONDITIONS (Doc 2, «Regla contra las asociaciones artificiales»), in the order they are checked after the moment and the match:

1. **The entity by its id.** A player by the provider's id, inside the closed world of the match - the squads and recent line-ups of its
   two teams - with PrediGol's own id; or one of the two teams of the match. Nothing links by a word.
2. **A literal quote that names it.** The fact's text must be the source's own words (research v2's claims, the checked quotes of the
   quarantined extractor), not a sentence a model wrote; and it must name the entity: the player's whole name, or an initial and his
   surname (``J. Ejemplo``), or the team's own words. A surname alone never links (``cita_sin_nombre``), and a name another player of the
   two squads also answers to is a homonym without a signal (``homonimo``): refused.
3. **A dated fact inside the match's window.** It needs its publication date, after the previous match of the entity's team (or at most
   ``WINDOW`` before kick-off): a club's news is not hung from all its matches (``fuera_de_ventana``).

Before them: a fact known or published after the moment the evaluation decided as of does not exist for it (``posterior_a_la_decision``),
and a fact of another match is not this match's (``otro_partido``).

THE LEVEL (``LEVEL_OF``), from the status the evidence engine gave it and the tier of its source: ``CONFIRMED`` by an official, competition
or club source is ``oficial``, otherwise ``dos_origenes``; ``PROBABLE`` is ``un_medio``; ``RUMOR`` (and anything unknown) ``rumor``;
``CONTRADICTORY`` has no level, a warning ``contradiccion``.

THE RELATION, by code: a rumour is ``no_usada`` (the code never moves anything on a rumour); a contradiction is ``contexto``; a fact about
the availability of a player a selection depends on (``intel.lineup_dependencies``) is ``en_contra`` of that selection when it lowers its
probability by ``MATERIAL`` or more (an absence of a player it needs; his start, if it needs him out) and ``a_favor`` when it raises it as
much; across the selections, one direction if they agree, ``contexto`` if they do not or if none moves; anything else is ``contexto``.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from decimal import Decimal
from typing import Final, Literal

from fbi.factlinks import VERSION
from fbi.people.identity.names import CLUB_WORDS, PARTICLES, alias_key

Relation = Literal["a_favor", "en_contra", "contexto", "no_usada"]
Level = Literal["oficial", "dos_origenes", "declaracion", "un_medio", "rumor"]
Rejection = Literal["posterior_a_la_decision", "otro_partido", "sin_entidad", "entidad_ajena", "sin_cita_literal", "cita_sin_nombre",
                    "homonimo", "sin_fecha", "fuera_de_ventana"]
SourceType = Literal["oficial", "agencia", "prensa"]
Key = tuple[str, str, Decimal]

RELATIONS: Final = ("a_favor", "en_contra", "contexto", "no_usada")
LEVELS: Final = ("oficial", "dos_origenes", "declaracion", "un_medio", "rumor")
REJECTIONS: Final = ("posterior_a_la_decision", "otro_partido", "sin_entidad", "entidad_ajena", "sin_cita_literal", "cita_sin_nombre",
                     "homonimo", "sin_fecha", "fuera_de_ventana")
SOURCE_TYPES: Final = ("oficial", "agencia", "prensa")
OFFICIAL_TIERS: Final = frozenset({"official", "competition", "club"})
LEVEL_OF: Final[dict[str, Level]] = {"PROBABLE": "un_medio", "RUMOR": "rumor"}
MATERIAL: Final = 0.02
"""The shift of a selection's probability that counts (two points): the evaluation cycle's own (``fbi.evalcycle.dependency.MATERIAL``; a
test holds the two equal)."""
WINDOW: Final = timedelta(days=14)
"""How far before kick-off a fact may be dated when the team played no earlier match."""
ABSENCE: Final = frozenset({"out", "doubtful"})
PRESENCE: Final = frozenset({"available", "starts"})


@dataclass(frozen=True, slots=True)
class Fact:
    """One fact of the match as the evaluation could read it (a row of ``ai.evidence``)."""

    evidence_id: int
    fixture_id: int | None
    team_id: int | None
    provider_player_id: int | None
    kind: str
    assertion: str | None
    text: str
    literal: bool
    """The text is the source's own words: research v2's claim or a checked quote, not a model's summary."""
    published_at: datetime | None
    known_at: datetime
    status: str
    tier: str
    source_name: str
    source_url: str | None
    item_id: int | None = None


@dataclass(frozen=True, slots=True)
class Person:
    """A player of the match's closed world: of one of its two teams."""

    provider_player_id: int
    player_id: int | None
    team_id: int
    names: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class World:
    """What the validator knows of the match at the moment of the evaluation."""

    fixture_id: int
    kickoff_at: datetime
    decided_at: datetime
    teams: Mapping[int, tuple[str, ...]]
    """The two teams of the match (PrediGol's ids) and their names."""
    people: Sequence[Person]
    previous_kickoff: Mapping[int, datetime] = field(default_factory=dict)
    """Each team's previous match before this one."""


@dataclass(frozen=True, slots=True)
class SelectionDependency:
    """What a selection's probability does without each player it depends on, or with him starting (``intel.lineup_dependencies``)."""

    key: Key
    shifts: Mapping[int, tuple[float, float]]
    """provider id -> (shift without him, shift with him starting)."""


@dataclass(frozen=True, slots=True)
class Effect:
    key: Key
    relation: Relation
    shift: float


@dataclass(frozen=True, slots=True)
class Link:
    """The validator's word on one fact: linked (its entity, level and relation) or refused with its reason."""

    fact: Fact
    rejection: Rejection | None
    source_type: SourceType
    entity_type: Literal["team", "player"] | None = None
    entity_id: int | None = None
    team_id: int | None = None
    named_as: str | None = None
    level: Level | None = None
    warning: Literal["contradiccion"] | None = None
    relation: Relation | None = None
    effects: tuple[Effect, ...] = ()
    version: str = VERSION

    @property
    def linked(self) -> bool:
        return self.rejection is None


def source_type_of(tier: str) -> SourceType:
    """``oficial`` for an official, competition or club source; ``prensa`` for the rest. ``agencia`` is in the contract's words, but no
    rule of ``link-v1`` tells a wire agency apart yet."""
    return "oficial" if tier in OFFICIAL_TIERS else "prensa"


def level_of(status: str, tier: str) -> tuple[Level | None, Literal["contradiccion"] | None]:
    if status == "CONFIRMED":
        return ("oficial" if tier in OFFICIAL_TIERS else "dos_origenes"), None
    if status == "CONTRADICTORY":
        return None, "contradiccion"
    return LEVEL_OF.get(status, "rumor"), None


# ── naming ───────────────────────────────────────────────────────────────────────────────────────────────────────────

def _words(text: str) -> list[str]:
    return alias_key(text.replace(".", ". ")).split()


def _contains(haystack: Sequence[str], needle: Sequence[str]) -> bool:
    n = len(needle)
    return n > 0 and any(list(haystack[i:i + n]) == list(needle) for i in range(len(haystack) - n + 1))


def _person_forms(names: Iterable[str]) -> tuple[list[list[str]], list[str]]:
    """The strong forms of a player's names (each whole name; an initial and the surname) and his surnames (a surname alone is weak)."""
    strong: list[list[str]] = []
    surnames: list[str] = []
    for name in names:
        parts = [p for p in _words(name) if p not in PARTICLES or len(p) > 3]
        if not parts:
            continue
        strong.append(parts)
        if len(parts) >= 2:
            strong.append([parts[0][0], parts[-1]])
            surnames.append(parts[-1])
    return strong, surnames


def player_named(quote: str, target: Person, people: Sequence[Person]) -> tuple[str | None, Rejection | None]:
    """(the name the quote names him by, None) or (None, why not): his whole name or initial and surname, and no other player of the
    two squads answering to the same; a surname alone never names him."""
    q = _words(quote)
    strong, surnames = _person_forms(target.names)
    hit = next((form for form in strong if _contains(q, form)), None)
    others = [p for p in people if p.provider_player_id != target.provider_player_id]
    if hit is not None:
        if any(_contains(q, form) and form == hit for p in others for form in _person_forms(p.names)[0]):
            return None, "homonimo"
        return " ".join(hit), None
    found = [s for s in surnames if s in q]
    if found and any(s in _person_forms(p.names)[1] for p in others for s in found):
        return None, "homonimo"
    return None, "cita_sin_nombre"


def _team_form(name: str) -> list[str]:
    words = _words(name)
    own = [w for w in words if w not in CLUB_WORDS]
    return own or words


def team_named(quote: str, team_id: int, teams: Mapping[int, tuple[str, ...]]) -> tuple[str | None, Rejection | None]:
    """The team's own words (its name without the words every club has) in the quote, and not the other team's same words."""
    q = _words(quote)
    hit = next((form for form in (_team_form(n) for n in teams.get(team_id, ())) if _contains(q, form)), None)
    if hit is None:
        return None, "cita_sin_nombre"
    if any(_team_form(n) == hit for other, names in teams.items() if other != team_id for n in names):
        return None, "homonimo"
    return " ".join(hit), None


# ── the relation ─────────────────────────────────────────────────────────────────────────────────────────────────────

def _direction(shift: float) -> Relation:
    if shift >= MATERIAL:
        return "a_favor"
    if shift <= -MATERIAL:
        return "en_contra"
    return "contexto"


def relation_of(fact: Fact, level: Level | None, warning: str | None, deps: Sequence[SelectionDependency]
                ) -> tuple[Relation, tuple[Effect, ...]]:
    if level == "rumor":
        return "no_usada", ()
    if warning is not None:
        return "contexto", ()
    effects: list[Effect] = []
    if fact.provider_player_id is not None and fact.assertion in ABSENCE | PRESENCE:
        for d in deps:
            got = d.shifts.get(fact.provider_player_id)
            if got is None:
                continue
            shift = got[0] if fact.assertion in ABSENCE else got[1]
            effects.append(Effect(d.key, _direction(shift), round(shift, 4)))
    moved = {e.relation for e in effects} - {"contexto"}
    return (moved.pop() if len(moved) == 1 else "contexto"), tuple(effects)


# ── the validator ────────────────────────────────────────────────────────────────────────────────────────────────────

def validate(fact: Fact, world: World, deps: Sequence[SelectionDependency] = ()) -> Link:
    """The validator's word on one fact for one evaluation of the match."""
    kind = source_type_of(fact.tier)

    def refuse(reason: Rejection, **kw: object) -> Link:
        return Link(fact, reason, kind, **kw)  # type: ignore[arg-type]

    if fact.known_at > world.decided_at or (fact.published_at is not None and fact.published_at > world.decided_at):
        return refuse("posterior_a_la_decision")
    if fact.fixture_id != world.fixture_id:
        return refuse("otro_partido")
    person: Person | None = None
    if fact.provider_player_id is not None:
        person = next((p for p in world.people if p.provider_player_id == fact.provider_player_id), None)
        if person is None or person.player_id is None:
            return refuse("entidad_ajena")
        entity: tuple[Literal["team", "player"], int, int] = ("player", person.player_id, person.team_id)
    elif fact.team_id is not None:
        if fact.team_id not in world.teams:
            return refuse("entidad_ajena")
        entity = ("team", fact.team_id, fact.team_id)
    else:
        return refuse("sin_entidad")
    base = {"entity_type": entity[0], "entity_id": entity[1], "team_id": entity[2]}
    if not fact.literal:
        return refuse("sin_cita_literal", **base)
    named, why = (player_named(fact.text, person, world.people) if person is not None
                  else team_named(fact.text, entity[1], world.teams))
    if why is not None:
        return refuse(why, **base)
    if fact.published_at is None:
        return refuse("sin_fecha", **base, named_as=named)
    start = max(world.kickoff_at - WINDOW, world.previous_kickoff.get(entity[2], world.kickoff_at - WINDOW))
    if fact.published_at < start:
        return refuse("fuera_de_ventana", **base, named_as=named)
    level, warning = level_of(fact.status, fact.tier)
    relation, effects = relation_of(fact, level, warning, deps)
    return Link(fact, None, kind, entity[0], entity[1], entity[2], named, level, warning, relation, effects)


def validate_all(facts: Iterable[Fact], world: World, deps: Sequence[SelectionDependency] = ()) -> list[Link]:
    return [validate(f, world, deps) for f in facts]


__all__ = ["LEVELS", "MATERIAL", "REJECTIONS", "RELATIONS", "SOURCE_TYPES", "WINDOW", "Effect", "Fact", "Link", "Person",
           "SelectionDependency", "World", "level_of", "player_named", "relation_of", "source_type_of", "team_named", "validate",
           "validate_all"]
