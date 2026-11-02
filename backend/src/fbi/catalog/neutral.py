"""Whether a match is played at a neutral venue: neither side is at home (plan F0, defect 1; rule ``neutral-v1``).

WHY
---
``core.fixtures.is_neutral`` and ``core.competitions.neutral_venue`` are read by the Elo, the goal models and the ordered
logit, but nothing ever wrote them: a Champions League final, a Copa del Rey final, a World Cup match in a third country
was modelled as if the nominal home side played in front of its own crowd. This module decides, from evidence the data
already holds, which matches are neutral. It is a PURE function of the facts handed to it; ``fbi.catalog.neutral_store``
gathers the facts and stores the verdict, and a models-side switch (off until a backtest justifies it) decides whether
the models read it.

WHAT COUNTS AS EVIDENCE (and what never does)
---------------------------------------------
Precision first. A match is neutral only on POSITIVE evidence; no evidence means "not neutral", never "probably neutral".

* A domestic LEAGUE match is never neutral. A league venue is noisy (a club that plays at another ground while its own
  is rebuilt is still at home) and the league models are the core of the system; a league match played abroad is rare
  enough to leave alone.
* Two NATIONAL sides: the country of the ground against the two countries. In a third country: neutral
  (``third_country``). In either side's country: not (a host nation is at home). A ground whose country could not be
  worked out: not neutral (``venue_country_unknown``).
* Two CLUBS: first, a veto. If the ground is one of the usual grounds of either side (read from that side's own league
  home matches over the four years before the match) or the ground the provider gives as the side's own, or - in a
  round that is not a final or a semi-final - in the same city as one of them (a club that plays elsewhere in town is
  still at home), the match is not neutral. Then one of
    - ``third_country``: the ground is in a country that is neither side's;
    - ``decider_ground``: a final or a third-place match, one match and not the leg of a tie, at a ground that is a home
      of neither side - both sides have a clear home and this is not it;
    - ``semi_pair_ground``: a semi-final, one match and not the leg of a tie, whose twin (the other semi-final of the
      same competition, between two other sides) is played at the same ground within three days - a final four at one
      venue. A semi-final alone proves nothing: a single-match semi-final is often drawn at one side's own ground;
    - ``shared_ground``: several matches of the same competition season, of at least three different nominal home
      sides, at one ground within a few weeks - a competition played at neutral grounds (a cup whose every tie is
      played at a ground of neither side), and both sides have a clear home and this is not it. In a competition of
      clubs from several countries it needs a ground that is not in either side's country (nor, where the country of
      the ground is in doubt, in any country it may be in): a national stadium that several clubs of one country borrow
      is where they are at home.
* A club against a national side, a team whose kind is unknown, a match with no ground named: not neutral.

The provider keeps a venue id for a home match played elsewhere and uses one id for different grounds, so a ground is
identified by what the PAYLOAD names (``fixtures.venue_name`` and ``venue_city``); the id counts only where the store has
checked that it points at that same ground, and the country of a ground only through the checked id or the venues table
(``fbi.core.places`` compares names).

KNOWN LIMITS (they only ever err towards "not neutral", except the last)
* A ground spelled differently in the payload and in the side's own matches ('Parc Olympique Lyonnais' / 'Groupama
  Stadium') is not recognised as the side's home unless the provider's own venue for the side says so; the answer is then
  "no evidence", not neutral - except in a final, where a ground in the side's own city is still called neutral (a
  Wembley final of a London club is neutral and must stay so): a final at a finalist's own ground under another name
  (the 2023 Libertadores final at the Maracanã, Fluminense's) is called neutral. This is one of the few ways the rule
  can be wrong the unsafe way, and it is why the before/after backtest is read on the matches the rule changes, with
  the evidence of each stored.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any

from fbi.core.places import cities_compatible, place_key, same_place

RULE_VERSION = "neutral-v1"

HISTORY_DAYS = 1460
"""How far back a side's league home matches are read to learn its usual grounds."""
HISTORY_N = 30
"""At most this many of the side's most recent league home matches."""
MIN_HISTORY = 3
"""Fewer named home matches than this and the side's home is not known (``Presence.UNKNOWN``), never "elsewhere"."""
MIN_COUNT = 2
MIN_SHARE = 0.15
"""A ground is a usual ground of a side only with at least this many of its home matches AND this share of them: a
single match played elsewhere (a cup tie, a one-off) does not make a ground a home."""
S2_WINDOW_DAYS = 45
S2_AHEAD_DAYS = 2
"""The shared-ground evidence reads matches from this many days before to this many days after the match: a schedule is
known two days ahead, a month and a half before is the past."""
S2_MIN_MATCHES = 3
S2_MIN_TEAMS = 3
TWIN_DAYS = 3
"""A semi-final's twin is the other semi-final of the competition, at the same ground, no further apart than this (the
two semi-finals of a final four are played on the same weekend)."""

FINAL = re.compile(r"^\s*(?:final|(?:\d+(?:st|nd|rd|th) place|third[- ]place)(?: final| play-?off)?)\s*$", re.IGNORECASE)
"""A round that is one match played at a ground chosen for it: a final, a third-place (or fifth-place...) match."""
SEMI = re.compile(r"^\s*semi[- ]?finals?\s*$", re.IGNORECASE)
"""A semi-final. Single-match semi-finals are drawn at a side's own ground as often as they are played at a neutral
one, and two-legged ones are at the clubs' grounds: the round alone says nothing, the twin semi-final does."""

# Why a match is, or is not, neutral. One code per verdict, kept in ``core.fixture_venue_class.basis``.
NEUTRAL_BASES = ("third_country", "decider_ground", "semi_pair_ground", "shared_ground")
NOT_NEUTRAL_BASES = (
    "league",              # domestic league: never neutral by rule
    "no_venue",            # the payload names no ground
    "kind_unknown",        # a side is neither known to be national nor a club
    "mixed_sides",         # a national side against a club
    "country_unknown",     # a national side without a country
    "venue_country_unknown",
    "home_country",        # two national sides, the ground is in the home side's country
    "away_country",        # ... in the away side's country
    "home_ground",         # clubs: the ground is the home side's
    "away_ground",         # clubs: the ground is the away side's
    "no_evidence",         # clubs: nothing says neutral
)


class Presence(StrEnum):
    """Whether a side is at home at the ground of the match."""

    HOME = "home"
    ELSEWHERE = "elsewhere"
    UNKNOWN = "unknown"


@dataclass(frozen=True, slots=True)
class Ground:
    """A ground as the payload of a match names it. ``venue_id`` is set only when the provider's id points at this same
    ground (the store checks the names); ``country`` only when it could be worked out, with ``country_basis`` saying how
    ('venue_id': the checked id; 'venues_table': the ground's name and city against core.venues)."""

    name: str | None = None
    city: str | None = None
    venue_id: int | None = None
    country: str | None = None
    country_basis: str | None = None
    countries: frozenset[str] = frozenset()
    """When ``country`` is not settled (the sources disagree, or none of them knows): every country the sources place the
    ground in, or its city. Not a country to use - a place to look for a host nation: a side of one of these countries
    may be playing at home. Empty when the country is settled, or when nothing names a country at all."""

    @property
    def named(self) -> bool:
        return bool(self.name and self.name.strip())

    @property
    def possible_countries(self) -> frozenset[str]:
        """Every country the ground may be in: the settled one, or the ones the sources name for an unsettled ground."""
        return self.countries | frozenset({self.country} if self.country else ())


@dataclass(frozen=True, slots=True)
class Side:
    """One side of a match. ``history`` is the grounds of its league home matches before this one, newest first (empty
    for a national side, which has no league)."""

    team_id: int
    country: str | None = None
    national: bool | None = None
    history: tuple[Ground, ...] = ()
    country_note: str | None = None
    """Why ``country`` is empty when the label was dropped (it disagreed with the side's own home venue)."""
    homes: tuple[Ground, ...] = ()
    """The ground(s) the provider gives as the side's own (``core.teams.venue_id``): a second witness that a ground is the
    side's home when its league matches spell the ground differently (a renamed stadium, an alias)."""


@dataclass(frozen=True, slots=True)
class Shared:
    """The matches of the same competition season at the same ground within the window around this one, this one
    included: how many, and how many different nominal home sides. ``twins`` counts the OTHER matches of the same round
    at this ground no more than ``TWIN_DAYS`` apart between two sides that are neither of this match's."""

    matches: int
    home_sides: int
    twins: int = 0


@dataclass(frozen=True, slots=True)
class FixtureFacts:
    fixture_id: int
    competition_type: str
    round: str | None
    ground: Ground
    home: Side
    away: Side
    shared: Shared | None = None
    legs: int = 1
    """How many matches the two sides play in this round of this competition season (this one included): 2 is a
    two-legged tie, whose legs are at the clubs' grounds."""


@dataclass(frozen=True, slots=True)
class Classification:
    rule: str
    neutral: bool
    basis: str
    evidence: dict[str, Any] = field(default_factory=dict)


def is_final(round_name: str | None) -> bool:
    """A final or a placement match (third place...): one match, at a ground chosen for it."""
    return bool(round_name) and FINAL.match(round_name or "") is not None


def is_semi(round_name: str | None) -> bool:
    return bool(round_name) and SEMI.match(round_name or "") is not None


def same_ground(a: Ground, b: Ground) -> bool:
    """The same ground: the same checked venue id, or alike names whose cities do not contradict each other. A city
    one side does not give does not count against it; 'Newcastle' and 'Newcastle upon Tyne' do not contradict."""
    if a.venue_id is not None and a.venue_id == b.venue_id:
        return True
    if not a.named or not b.named:
        return False
    if not (same_place(a.name, b.name) or _same_words(a.name, b.name)):
        return False
    return cities_compatible(a.city, b.city)


def _same_words(a: str | None, b: str | None) -> bool:
    """Equal names including their generic words ('Stadionul Municipal' names nothing by its distinctive words, but it
    is equal to itself - the city then decides)."""
    ka, kb = place_key(a), place_key(b)
    return bool(ka) and ka == kb


def usual_grounds(history: Sequence[Ground]) -> list[Ground] | None:
    """The grounds a side calls home: those with at least ``MIN_COUNT`` of its league home matches and at least
    ``MIN_SHARE`` of them. None when the history cannot say - fewer than ``MIN_HISTORY`` named matches, or no ground
    reaches the bar (a side that moves around has no home to be away from)."""
    named = [g for g in history if g.named]
    if len(named) < MIN_HISTORY:
        return None
    clusters: list[list[Any]] = []
    for g in named:
        for c in clusters:
            if same_ground(c[0], g):
                c[1] += 1
                break
        else:
            clusters.append([g, 1])
    usual = [c[0] for c in clusters if c[1] >= MIN_COUNT and c[1] / len(named) >= MIN_SHARE]
    return usual or None


def presence(history: Sequence[Ground], ground: Ground, *, decider: bool,
             homes: Sequence[Ground] = ()) -> tuple[Presence, str]:
    """Whether the side is at home at ``ground``, and in a few words why (kept as evidence). ``homes`` are the grounds the
    provider gives as the side's own. ``decider`` is a round whose ground was chosen for it (a final, a semi-final)."""
    if not ground.named:
        return Presence.UNKNOWN, "the match names no ground"
    usual = usual_grounds(history)
    for u in usual or ():
        if same_ground(u, ground):
            return Presence.HOME, f"a usual ground of the side: {u.name}"
    for h in homes:
        if h.named and same_ground(h, ground):
            return Presence.HOME, f"the ground the provider gives as the side's own: {h.name}"
    if usual is None:
        return Presence.UNKNOWN, "the side's home matches do not say where it plays"
    # A club that plays at another ground of its own city is still at home (a ground under works, a bigger one for a big
    # night). A decider is different: finals are played in the big city's big ground, whoever lives there.
    if not decider and place_key(ground.city):
        for u in (*usual, *homes):
            if place_key(u.city) and cities_compatible(u.city, ground.city):
                return Presence.HOME, f"the same city as a ground of the side: {u.city}"
    return Presence.ELSEWHERE, "not one of the side's usual grounds"


def _verdict(neutral: bool, basis: str, **evidence: Any) -> Classification:
    return Classification(RULE_VERSION, neutral, basis, evidence)


def classify(facts: FixtureFacts) -> Classification:
    """The verdict on one match: neutral or not, why, and the evidence behind it."""
    g, h, a = facts.ground, facts.home, facts.away
    ground: dict[str, Any] = {"name": g.name, "city": g.city, "venue_id": g.venue_id, "country": g.country,
                              "country_basis": g.country_basis}
    if g.countries:
        ground["countries"] = sorted(g.countries)
    if facts.competition_type == "domestic_league":
        return _verdict(False, "league")
    if not g.named and not g.country:
        return _verdict(False, "no_venue", ground=ground)
    if h.national is None or a.national is None:
        return _verdict(False, "kind_unknown", ground=ground)
    if h.national != a.national:
        return _verdict(False, "mixed_sides", ground=ground)
    if h.national:
        return _two_national_sides(facts, ground)
    return _two_clubs(facts, ground)


def _two_national_sides(facts: FixtureFacts, ground: dict[str, Any]) -> Classification:
    g, h, a = facts.ground, facts.home, facts.away
    sides = {"home_country": h.country, "away_country": a.country}
    for key, side in (("home_country_note", h), ("away_country_note", a)):
        if side.country_note:
            sides[key] = side.country_note
    if not h.country or not a.country:
        return _verdict(False, "country_unknown", ground=ground, **sides)
    if not g.country:
        return _verdict(False, "venue_country_unknown", ground=ground, **sides)
    if g.country == h.country:
        return _verdict(False, "home_country", ground=ground, **sides)
    if g.country == a.country:
        return _verdict(False, "away_country", ground=ground, **sides)
    return _verdict(True, "third_country", ground=ground, **sides)


def _two_clubs(facts: FixtureFacts, ground: dict[str, Any]) -> Classification:
    g, h, a = facts.ground, facts.home, facts.away
    final, semi = is_final(facts.round), is_semi(facts.round)
    ph, why_h = presence(h.history, g, decider=final or semi, homes=h.homes)
    pa, why_a = presence(a.history, g, decider=final or semi, homes=a.homes)
    seen: dict[str, Any] = {
        "ground": ground, "round": facts.round, "round_kind": "final" if final else "semi" if semi else None,
        "legs": facts.legs,
        "home": {"country": h.country, "presence": ph.value, "why": why_h, "matches_read": len(h.history)},
        "away": {"country": a.country, "presence": pa.value, "why": why_a, "matches_read": len(a.history)},
    }
    for key, side in (("home", h), ("away", a)):
        if side.country_note:
            seen[key]["country_note"] = side.country_note
    if ph is Presence.HOME:
        return _verdict(False, "home_ground", **seen)
    if pa is Presence.HOME:
        return _verdict(False, "away_ground", **seen)
    both_away = ph is Presence.ELSEWHERE and pa is Presence.ELSEWHERE
    # Two clubs of one country in a cup of that country, at a ground the data puts in another "country", are usually a
    # club of an overseas department playing at home (Coupe de France in Martinique): there the sides' homes must be
    # known, and both elsewhere. In a competition of clubs from several countries a ground in a third country is
    # evidence on its own.
    abroad = bool(g.country and h.country and a.country and g.country not in (h.country, a.country))
    if abroad and (facts.competition_type != "domestic_cup" or both_away):
        return _verdict(True, "third_country", **seen)
    s = facts.shared
    # A tie of two legs is played at the clubs' grounds, whatever the round is called.
    if facts.legs <= 1 and both_away:
        if final:
            return _verdict(True, "decider_ground", **seen)
        if semi and s is not None and s.twins >= 1:
            return _verdict(True, "semi_pair_ground", **seen, shared={"matches": s.matches, "twins": s.twins})
    if s is not None and both_away and s.matches >= S2_MIN_MATCHES and s.home_sides >= S2_MIN_TEAMS:
        # In a competition of clubs from several countries a ground that several clubs of ONE country use is that country's
        # national stadium, borrowed by clubs whose own does not meet the competition's rules (Always Ready in La Paz,
        # Magallanes in Rancagua): they have not left home, and a club of a host country is at home as a host nation is.
        # Only a ground in the country of neither side, or a cup of one country played at grounds chosen for it, is shared
        # in the sense of neutral. A ground whose country is in doubt is tested against every country it may be in: a
        # side of any of them may be the host (the provider files a Saudi club under the Emirates, and Dammam is then
        # "Saudi Arabia or the Emirates"); a ground nothing names a country for cannot be tested.
        sides = {c for c in (h.country, a.country) if c}
        host = facts.competition_type != "domestic_cup" and bool(g.possible_countries & sides)
        shared = {"matches": s.matches, "home_sides": s.home_sides, "host_country": host}
        if not host:
            return _verdict(True, "shared_ground", **seen, shared=shared)
        return _verdict(False, "no_evidence", **seen, shared=shared)
    return _verdict(False, "no_evidence", **seen)
