"""The rules of AD-H04 (IA-076), pure and deterministic: which Wikidata item is one of our stadiums (``venue-geo-v1``) and which
stadium a match without a provider id is played at (``venue-link-v1``). They read nothing and write nothing.

A NAME NEVER DECIDES ALONE. A Wikidata item is reached through a CLUB (the item of a club whose ground the stadium is, by
P115); the name or the city then confirms it. A match is linked by what the provider itself said elsewhere (the id it gave
the same name for the same home club, or for the same name in the same city), by the home club's own ground under the same
name, or by the only stadium of that name in that city. Everything else goes to a person, with the candidates.
"""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from typing import Final, Literal

from fbi.core.places import cities_agree, cities_compatible, place_key, same_place, split_place
from fbi.venues.wikidata import HomeStatement, Snapshot, WdVenue

GEO_RULES: Final = "venue-geo-v1"
LINK_RULES: Final = "venue-link-v1"
COORDS_AGREE_KM: Final = 1.0
"""Two coordinates of one item further apart than this are not one place: the item keeps its QID but no coordinates."""
ELEVATION_AGREE_M: Final = 150.0
"""The DEM and Wikidata's P2044 within this are said to agree (P2044 of a stadium is often the city's)."""

_UK: Final = frozenset({"england", "scotland", "wales", "northern ireland"})
_COUNTRY_SAME: Final = {"usa": "united states", "united states of america": "united states",
                        "korea republic": "south korea", "republic of korea": "south korea",
                        "czechia": "czech republic", "turkiye": "turkey", "ivory coast": "cote divoire",
                        "people s republic of china": "china", "russian federation": "russia"}


def country_key(name: object) -> str:
    k = place_key(name)
    if k in _UK:
        return "united kingdom"
    return _COUNTRY_SAME.get(k, k)


def km_between(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lon1, lat2, lon2 = map(math.radians, (a[0], a[1], b[0], b[1]))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lon2 - lon1) / 2) ** 2
    return 6371.0 * 2 * math.asin(math.sqrt(min(1.0, h)))


# ── venue-geo-v1: one of our stadiums -> its Wikidata item ───────────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class OurVenue:
    id: int
    name: str
    city: str | None
    country: str | None
    team_qids: tuple[str, ...]
    """The Wikidata items of the clubs whose ground (``core.teams.venue_id``) this stadium is."""


GeoMethod = Literal["home_venue_name", "home_venue_city"]


@dataclass(frozen=True, slots=True)
class GeoMatch:
    venue_id: int
    qid: str
    method: GeoMethod
    confidence: float
    coords: tuple[float, float] | None
    capacity: int | None
    elevation_wd: float | None
    evidence: Mapping[str, object]


@dataclass(frozen=True, slots=True)
class Question:
    """Something the rules leave to a person: ``subject_id`` (a venue or a fixture), why, and the candidates."""

    kind: Literal["venue_qid", "fixture_venue"]
    subject_id: int
    reason: str
    candidates: tuple[str, ...]
    evidence: Mapping[str, object] = field(default_factory=dict)


def current_homes(statements: Iterable[HomeStatement]) -> list[str]:
    """The venues a club plays at now: not deprecated, with no end date; when the club has a preferred one, only those."""
    live = [s for s in statements if s.rank != "deprecated" and not s.end]
    preferred = [s for s in live if s.rank == "preferred"]
    return sorted({s.venue_qid for s in (preferred or live)}, key=lambda q: int(q[1:]))


def _one_coord(v: WdVenue) -> tuple[tuple[float, float] | None, str]:
    pts = sorted(v.coords)
    if not pts:
        return None, "no_coords"
    if all(km_between(pts[0], p) <= COORDS_AGREE_KM for p in pts[1:]):
        return pts[0], "ok"
    return None, "coords_disagree"


def match_venue(ours: OurVenue, snap: Snapshot) -> GeoMatch | Question | None:
    """The Wikidata item of one of our stadiums, a question for a person, or None when no club of it has a home venue in the
    snapshot (nothing to ask)."""
    cands: list[str] = []
    for team in ours.team_qids:
        for q in current_homes(snap.homes.get(team, [])):
            if q not in cands:
                cands.append(q)
    if not cands:
        return None
    name, city = split_place(ours.name, ours.city)
    ck = country_key(ours.country)
    named, placed, foreign = [], [], []
    for q in cands:
        v = snap.venues.get(q)
        if v is None:
            continue
        if any(same_place(name, n) for n in v.names):
            named.append(q)
        if city and any(cities_agree(city, p) for p in v.places):
            placed.append(q)
        if ck and v.countries and ck not in {country_key(c) for c in v.countries}:
            foreign.append(q)
    evidence: dict[str, object] = {"candidates": cands, "named": named, "city_agrees": placed, "country_differs": foreign,
                                   "team_qids": list(ours.team_qids)}
    if len(named) > 1:
        return Question("venue_qid", ours.id, "several_named", tuple(named), evidence)
    if len(named) == 1:
        q = named[0]
        if q in foreign:
            return Question("venue_qid", ours.id, "country_differs", (q,), evidence)
        return _geo(ours.id, snap.venues[q], "home_venue_name", 0.95 if q in placed or not city else 0.9, evidence)
    if len(cands) == 1 and placed == cands and not foreign:
        return _geo(ours.id, snap.venues[cands[0]], "home_venue_city", 0.8, evidence)
    reason = "several_candidates" if len(cands) > 1 else "unconfirmed_single"
    return Question("venue_qid", ours.id, reason, tuple(cands), evidence)


def _geo(venue_id: int, v: WdVenue, method: GeoMethod, confidence: float, evidence: dict[str, object]) -> GeoMatch:
    coords, coord_state = _one_coord(v)
    caps = sorted(v.capacities)
    elevs = sorted(v.elevations)
    ev = dict(evidence, coords=coord_state, capacities=caps, wikidata_elevations=elevs,
              wikidata_names=sorted(v.names)[:12], wikidata_places=sorted(v.places)[:6])
    return GeoMatch(venue_id, v.qid, method, confidence, coords, caps[0] if len(caps) == 1 else None,
                    elevs[0] if len(elevs) == 1 else None, ev)


def match_all(venues: Iterable[OurVenue], snap: Snapshot) -> tuple[list[GeoMatch], list[Question]]:
    """``match_venue`` for each stadium, then one more check: an item matched to two of our stadiums is kept only for those
    whose NAME matched it (the provider has two ids for one ground); the others become questions (``shared_qid``)."""
    matches: list[GeoMatch] = []
    questions: list[Question] = []
    for ours in sorted(venues, key=lambda v: v.id):
        got = match_venue(ours, snap)
        if isinstance(got, GeoMatch):
            matches.append(got)
        elif isinstance(got, Question):
            questions.append(got)
    per_qid = Counter(m.qid for m in matches)
    kept: list[GeoMatch] = []
    for m in matches:
        if per_qid[m.qid] > 1 and m.method != "home_venue_name":
            questions.append(Question("venue_qid", m.venue_id, "shared_qid", (m.qid,), dict(m.evidence)))
        else:
            kept.append(m)
    return kept, sorted(questions, key=lambda q: (q.subject_id, q.reason))


def elevation_check(dem: float | None, wikidata: float | None) -> str:
    if dem is None:
        return "no_dem"
    if wikidata is None:
        return "no_wikidata"
    return "agrees" if abs(dem - wikidata) <= ELEVATION_AGREE_M else "disagrees"


# ── venue-link-v1: a match without a provider id -> its stadium ──────────────────────────────────────────────────────────

@dataclass(frozen=True, slots=True)
class Ground:
    id: int
    name: str
    city: str | None


@dataclass(frozen=True, slots=True)
class Unlinked:
    fixture_id: int
    home_team_id: int
    venue_name: str | None
    venue_city: str | None
    neutral: bool


LinkMethod = Literal["provider_history_team", "provider_history_city", "home_ground", "venue_name_city"]
CONFIDENCE: Final[Mapping[str, float]] = {"provider_history_team": 0.97, "provider_history_city": 0.93,
                                          "home_ground": 0.9, "venue_name_city": 0.85}


@dataclass(frozen=True, slots=True)
class Link:
    fixture_id: int
    venue_id: int
    method: LinkMethod
    confidence: float
    evidence: Mapping[str, object]


@dataclass(slots=True)
class LinkIndex:
    """What the rules look things up in, built once from the database."""

    grounds: dict[int, Ground] = field(default_factory=dict)
    home_ground: dict[int, int] = field(default_factory=dict)
    """team id -> its ``core.teams.venue_id``."""
    by_team_name: dict[tuple[int, str], Counter[int]] = field(default_factory=dict)
    """(home team, name key) -> how many matches the provider gave each venue id under that name."""
    by_name_city: dict[tuple[str, str], Counter[int]] = field(default_factory=dict)
    by_name: dict[str, list[int]] = field(default_factory=dict)

    @classmethod
    def build(cls, grounds: Iterable[Ground], home_grounds: Mapping[int, int],
              history: Iterable[tuple[int, str | None, str | None, int, int]]) -> LinkIndex:
        """``history``: (home team, venue name, venue city, venue id, matches) of the matches that DO carry a provider id."""
        ix = cls()
        for g in grounds:
            ix.grounds[g.id] = g
            name, _ = split_place(g.name, g.city)
            k = place_key(name)
            if k:
                ix.by_name.setdefault(k, []).append(g.id)
        ix.home_ground = dict(home_grounds)
        for team, vname, vcity, vid, n in history:
            name, city = split_place(vname, vcity)
            k = place_key(name)
            if not k:
                continue
            ix.by_team_name.setdefault((team, k), Counter())[vid] += n
            ck = place_key(city)
            if ck:
                ix.by_name_city.setdefault((k, ck), Counter())[vid] += n
        return ix


def _city_ok(ix: LinkIndex, venue_id: int, city: str | None) -> bool:
    g = ix.grounds.get(venue_id)
    return g is None or cities_compatible(city, g.city)


def link_fixture(u: Unlinked, ix: LinkIndex) -> Link | Question | None:
    """The stadium of one match without a provider id, a question, or None (no name: nothing to go on)."""
    name, city = split_place(u.venue_name, u.venue_city)
    k = place_key(name)
    if not k:
        return None
    ev: dict[str, object] = {"venue_name": u.venue_name, "venue_city": u.venue_city, "neutral": u.neutral}

    seen = ix.by_team_name.get((u.home_team_id, k))
    if seen:
        ids = [vid for vid in sorted(seen) if _city_ok(ix, vid, city)]
        if len(ids) == 1:
            return Link(u.fixture_id, ids[0], "provider_history_team", CONFIDENCE["provider_history_team"],
                        dict(ev, matches=seen[ids[0]]))
        if len(ids) > 1:
            return Question("fixture_venue", u.fixture_id, "history_ambiguous", tuple(str(i) for i in ids), ev)
    ck = place_key(city)
    if ck:
        seen = ix.by_name_city.get((k, ck))
        if seen:
            ids = [vid for vid in sorted(seen) if _city_ok(ix, vid, city)]
            if len(ids) == 1:
                return Link(u.fixture_id, ids[0], "provider_history_city", CONFIDENCE["provider_history_city"],
                            dict(ev, matches=seen[ids[0]]))
            if len(ids) > 1:
                return Question("fixture_venue", u.fixture_id, "history_ambiguous", tuple(str(i) for i in ids), ev)
            # the provider gave this name and city the id of a ground it files in another city (Encamp / Andorra la
            # Vella): a person decides, the rule does not (a spelling in another language is not guessed either)
            return Question("fixture_venue", u.fixture_id, "city_differs", tuple(str(i) for i in sorted(seen)), ev)
    home = ix.home_ground.get(u.home_team_id)
    home_g = ix.grounds.get(home) if home is not None else None
    if home_g is not None and not u.neutral and same_place(name, split_place(home_g.name, home_g.city)[0]) \
            and cities_compatible(city, home_g.city):
        return Link(u.fixture_id, home_g.id, "home_ground", CONFIDENCE["home_ground"], ev)
    if ck:
        same = [vid for vid in ix.by_name.get(k, []) if cities_agree(city, ix.grounds[vid].city)]
        if len(same) == 1:
            return Link(u.fixture_id, same[0], "venue_name_city", CONFIDENCE["venue_name_city"], ev)
        if len(same) > 1:
            return Question("fixture_venue", u.fixture_id, "same_name_same_city", tuple(str(i) for i in same), ev)
    named = ix.by_name.get(k, [])
    if named:
        return Question("fixture_venue", u.fixture_id, "name_without_city" if not ck else "name_other_city",
                        tuple(str(i) for i in named[:10]), ev)
    if home_g is not None and not u.neutral and cities_agree(city, home_g.city):
        return Question("fixture_venue", u.fixture_id, "home_ground_other_name", (str(home_g.id),), ev)
    return None


def link_all(unlinked: Sequence[Unlinked], ix: LinkIndex) -> tuple[list[Link], list[Question], int]:
    """``link_fixture`` for each match: the links, the questions, and how many had nothing to go on."""
    links: list[Link] = []
    questions: list[Question] = []
    nothing = 0
    for u in sorted(unlinked, key=lambda x: x.fixture_id):
        got = link_fixture(u, ix)
        if isinstance(got, Link):
            links.append(got)
        elif isinstance(got, Question):
            questions.append(got)
        else:
            nothing += 1
    return links, questions, nothing
