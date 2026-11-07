"""Where a ground is: its city and country against its competition, its matches, the provider and the other grounds.

7 Nov 2026 (plan of the Matches module, finding C1): ``GET /matches/9207``, Valencia v Real Madrid in LaLiga, named
venue 80 "Estadio de Mestalla", "Avenida de Suecia", Spain - in "Valdivia", a city of Chile. No check crossed a
ground's city or country with anything: the fixture comparison looks at the venue id only and the identity sample
compares five random venues without leaving a finding.

The control looks at every ground that hosts a home match of the current season of a tracked domestic league and
says, for each one, when one of these does not hold. Nothing is corrected here (``scripts.repair_venue_city`` proposes
the correction, dry run first):

* **Country.** A ground's country is the competition's or the home club's. A Welsh club plays the English league in
  Wales, Monaco the French one in Monaco: the home club's country covers those. A ground in neither is a finding.
* **City.** A stored city is contradicted by any of three signals, each one evidence a reader can check:

  1. the newest stored provider payload that describes the venue id (``/venues?id``, ``/teams?id`` of a club whose
     ground it is, or the payload the row was written from) names another city - the database is not what the
     provider says (``mismatch``; ``scripts.repair_venue_city`` can restore it from that payload);
  2. most of the fixture payloads that name this same ground (``core.fixtures.venue_city``, home matches of the
     tracked domestic leagues, every season) give another city;
  3. every other ground stored in that city is in another country, and at most half of the fixture payloads that
     name the ground give the city. The case of Mestalla: "Valdivia" is the city of Chilean grounds only. A city's
     name is shared across countries (Córdoba, Mérida, León), so this signal yields to the fixture payloads when most
     of them confirm the city.

  A city the provider and the fixture payloads both give is not a finding, whatever the other grounds say.
* **One fixture's city.** The match page shows the city of the fixture's own payload first
  (``fbi.api.repositories.fixtures.fixture_venue``). A home match whose payload names the club's ground in a city
  that fewer of the club's home matches there name than name the ground's city (the provider's record of it, else the
  fixture payloads' majority when it contradicts the stored city, else the stored city) is a finding on that
  fixture.

Severity: MEDIUM - a wrong city or country is context a page states as fact (the match header), not a number any
model, rating or settlement reads. A disagreement only the fixture payloads raise, against a city the provider's own
record gives, is LOW: the provider spells one ground two ways (a city in two languages is not guessed).
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

import psycopg
from psycopg.rows import dict_row

from fbi.core.places import cities_compatible, place_key, same_place
from fbi.storage.payload_store import PayloadStore, body_hash
from fbi.truth.findings import Finding, Kind, Severity, Tally

DATASET = "venues"
NO_COUNTRY = frozenset({"", "world"})
"""Competition countries that place nothing (API-Football files international club competitions under 'World')."""
PAYLOAD_TRIES = 3
"""Stored payloads read per venue, newest first, before giving up on finding its city in one."""
FIXTURES_LISTED = 20
"""Fixtures named per odd city (the newest), so one wrong ground repeated over seasons does not flood the report."""

SCOPE_SQL = """
SELECT f.venue_id, c.name AS competition, c.country AS competition_country, t.country AS home_country,
       count(*) AS n
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams t ON t.id = f.home_team_id
 WHERE c.is_tracked AND cs.is_current AND c.competition_type = 'domestic_league' AND f.venue_id IS NOT NULL
   AND f.status_group <> 'cancelled'
 GROUP BY 1, 2, 3, 4
"""
"""The grounds in scope: home matches of the current season of a tracked domestic league."""

VENUES_SQL = """
SELECT id, provider_venue_id, name, city, country FROM core.venues WHERE id = ANY(%(ids)s)
"""

ATLAS_SQL = """
SELECT id, name, city, country FROM core.venues
 WHERE city IS NOT NULL AND country IS NOT NULL AND (provider_venue_id IS NULL OR provider_venue_id > 0)
"""
"""Every ground with a city and a country: which countries a city name is the city of."""

FIXTURE_CITIES_SQL = f"""
SELECT f.venue_id, f.home_team_id, f.venue_name, f.venue_city, count(*) AS n,
       (array_agg(f.provider_fixture_id ORDER BY f.kickoff_at DESC))[1:{FIXTURES_LISTED}] AS fixtures
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
 WHERE c.is_tracked AND c.competition_type = 'domestic_league' AND f.venue_id = ANY(%(ids)s)
   AND f.venue_name IS NOT NULL AND f.venue_city IS NOT NULL AND f.status_group <> 'cancelled'
 GROUP BY 1, 2, 3, 4
"""
"""What the fixture payloads called each ground, every season of the tracked domestic leagues."""

PAYLOADS_SQL = """
SELECT v.id AS venue_id, p.hash, p.endpoint, p.fetched_at, p.file_path
  FROM core.venues v JOIN raw.ingestion_payloads p ON p.hash = v.source_payload_hash
 WHERE v.id = ANY(%(ids)s)
UNION
SELECT v.id, p.hash, p.endpoint, p.fetched_at, p.file_path
  FROM core.venues v JOIN raw.ingestion_payloads p
    ON p.endpoint = '/venues' AND p.params ->> 'id' = v.provider_venue_id::text
 WHERE v.id = ANY(%(ids)s) AND p.http_status = 200
UNION
SELECT v.id, p.hash, p.endpoint, p.fetched_at, p.file_path
  FROM core.venues v JOIN core.teams t ON t.venue_id = v.id
  JOIN raw.ingestion_payloads p ON p.endpoint = '/teams' AND p.params ->> 'id' = t.provider_team_id::text
 WHERE v.id = ANY(%(ids)s) AND p.http_status = 200
 ORDER BY 1, 4 DESC
"""
"""The stored provider answers that can describe each venue id, newest first."""


@dataclass(frozen=True, slots=True)
class ProviderVenue:
    """The venue as the newest stored provider payload that describes it says."""

    city: str | None
    country: str | None
    name: str | None
    endpoint: str
    fetched_at: datetime
    payload_hash: str
    file_path: str

    def source(self) -> str:
        return f"{self.endpoint} payload {self.payload_hash[:12]} of {self.fetched_at:%Y-%m-%d}"


@dataclass(frozen=True, slots=True)
class FixtureCity:
    """Home matches of one club whose payloads name a ground and a city the same way."""

    home_team_id: int
    venue_name: str
    city: str
    n: int
    fixtures: tuple[int, ...]
    """Provider fixture ids, newest first (at most ``FIXTURES_LISTED``)."""


@dataclass(frozen=True, slots=True)
class Ground:
    venue_id: int
    """core.venues.id (what ``GET /matches/{id}`` calls the venue's id)."""
    provider_venue_id: int | None
    name: str
    city: str | None
    country: str | None
    competitions: tuple[tuple[str, str | None], ...] = ()
    """(name, country) of the tracked domestic leagues whose current season it hosts."""
    home_countries: tuple[str, ...] = ()
    """Countries of the clubs whose home matches it hosts in those seasons."""
    fixture_cities: tuple[FixtureCity, ...] = ()
    """Only the payloads that name THIS ground (``same_place``): a club's id kept for a match elsewhere says nothing
    about its own ground."""
    provider: ProviderVenue | None = None

    @property
    def label(self) -> str:
        return f"venue {self.provider_venue_id} ({self.name}; core.venues {self.venue_id})"


@dataclass
class Atlas:
    """city key -> country key -> ground ids: which countries a city name is the city of."""

    cities: dict[str, dict[str, set[int]]] = field(default_factory=dict)
    countries: dict[str, str] = field(default_factory=dict)
    """country key -> the country as stored, for the report."""

    @staticmethod
    def of(rows: Iterable[Mapping[str, Any]]) -> Atlas:
        atlas = Atlas()
        for r in rows:
            city, country = place_key(r.get("city")), place_key(r.get("country"))
            if not city or not country:
                continue
            atlas.cities.setdefault(city, {}).setdefault(country, set()).add(int(r["id"]))
            atlas.countries.setdefault(country, str(r["country"]))
        return atlas

    def elsewhere(self, ground: Ground) -> list[str] | None:
        """The other countries whose grounds are in this ground's city, when none of the ground's own country is;
        None when the city is also a city of its country (or nothing is known)."""
        city, country = place_key(ground.city), place_key(ground.country)
        if not city or not country:
            return None
        held = {c: ids - {ground.venue_id} for c, ids in self.cities.get(city, {}).items()}
        held = {c: ids for c, ids in held.items() if ids}
        if not held or country in held:
            return None
        return sorted(self.countries.get(c, c) for c in held)


def same_country(a: object, b: object) -> bool:
    return bool(place_key(a)) and place_key(a) == place_key(b)


def _majority(cities: Sequence[FixtureCity]) -> str | None:
    tally: Counter[str] = Counter()
    spelling: dict[str, str] = {}
    for fc in cities:
        k = place_key(fc.city)
        tally[k] += fc.n
        spelling.setdefault(k, fc.city)
    if not tally:
        return None
    (k, _n), *_ = tally.most_common(1)
    return spelling[k]


def judge_country(g: Ground) -> Finding | None:
    """A ground in neither the competition's country nor the home club's."""
    if not place_key(g.country):
        return None
    leagues = [(name, c) for name, c in g.competitions if place_key(c) not in NO_COUNTRY]
    if not leagues:
        return None
    if any(same_country(g.country, c) for _n, c in leagues) or any(same_country(g.country, h)
                                                                   for h in g.home_countries):
        return None
    name, country = leagues[0]
    homes = ", ".join(sorted(set(g.home_countries))) or "unknown"
    return Finding.of(DATASET, g.label, "country", Kind.INCONSISTENT, Severity.MEDIUM,
                      api=f"{country} ({name})", db=g.country,
                      note=f"the ground hosts {name} home matches, but its country is neither the competition's nor "
                           f"the home club's ({homes})")


@dataclass(frozen=True, slots=True)
class CityVerdict:
    finding: Finding | None
    provider_disagrees: bool = False
    fixtures_disagree: bool = False
    foreign: list[str] | None = None
    expected: str | None = None
    """The city the evidence points at, when one does (the provider's, or the fixture payloads' majority)."""


def judge_city(g: Ground, atlas: Atlas) -> CityVerdict:
    city = g.city
    if not place_key(city):
        return CityVerdict(None)
    p = g.provider
    provider_city = p.city if p is not None and place_key(p.city) else None
    provider_disagrees = provider_city is not None and not cities_compatible(provider_city, city)
    provider_agrees = provider_city is not None and not provider_disagrees
    agreeing = sum(fc.n for fc in g.fixture_cities if cities_compatible(fc.city, city))
    named = sum(fc.n for fc in g.fixture_cities)
    majority = _majority(g.fixture_cities)
    # Most of the fixture payloads that name this ground give another city. "Most", not "all": one wrong match
    # payload can agree with a wrong stored city (one 'Valdivia' among eighteen Mestalla matches saying Valencia).
    fixtures_disagree = (named > 0 and 2 * agreeing < named and majority is not None
                         and not cities_compatible(majority, city))
    foreign = atlas.elsewhere(g)
    foreign_alone = foreign is not None and 2 * agreeing <= named
    if not (provider_disagrees or fixtures_disagree or foreign_alone):
        return CityVerdict(None)
    expected = provider_city if provider_disagrees else (majority if fixtures_disagree else None)
    why = []
    if provider_disagrees:
        assert p is not None
        why.append(f"the newest stored provider record of the venue ({p.source()}) says '{provider_city}'")
    elif provider_agrees:
        assert p is not None
        why.append(f"the provider's own record ({p.source()}) says the same")
    if named:
        cities = ", ".join(f"'{fc.city}' x{fc.n}" for fc in sorted(g.fixture_cities, key=lambda f: -f.n)[:4])
        why.append(f"{agreeing} of the {named} fixture payloads that name this ground give this city ({cities})")
    else:
        why.append("no fixture payload names a city for this ground")
    if foreign is not None:
        why.append(f"'{city}' is otherwise the city of grounds in {', '.join(foreign)} only, none in {g.country}")
    severity = Severity.MEDIUM
    if not provider_disagrees and provider_agrees and foreign is None:
        severity = Severity.LOW  # only the fixtures say otherwise, against the provider's own record
    kind = Kind.MISMATCH if provider_disagrees else Kind.INCONSISTENT
    finding = Finding.of(DATASET, g.label, "city", kind, severity,
                         api=expected if expected else f"a city in {g.country}", db=city,
                         note="; ".join(why) + ". Not corrected here (scripts.repair_venue_city)")
    return CityVerdict(finding, provider_disagrees, fixtures_disagree, foreign, expected)


@dataclass(frozen=True, slots=True)
class OddFixture:
    provider_fixture_id: int
    city: str
    expected: str
    others: int
    """Home matches of the same club at the same ground that name ``expected``."""


def reference_city(g: Ground, verdict: CityVerdict) -> str | None:
    """The city the ground is in, as far as the evidence says: the provider's record, else what most fixture payloads
    say when they contradict the stored city, else the stored city."""
    if g.provider is not None and place_key(g.provider.city):
        return g.provider.city
    if verdict.fixtures_disagree and verdict.expected:
        return verdict.expected
    return g.city if place_key(g.city) else None


def odd_fixtures(g: Ground, reference: str | None) -> list[OddFixture]:
    """Home matches whose payload names the club's ground in a city fewer of the club's home matches there name than
    name ``reference`` - the city no other match of the club at that ground gives."""
    if reference is None:
        return []
    out: list[OddFixture] = []
    by_team: dict[int, list[FixtureCity]] = {}
    for fc in g.fixture_cities:
        by_team.setdefault(fc.home_team_id, []).append(fc)
    for groups in by_team.values():
        agree = [fc for fc in groups if cities_compatible(fc.city, reference)]
        if not agree:
            continue
        others = sum(fc.n for fc in agree)
        expected = max(agree, key=lambda fc: fc.n).city
        for fc in groups:
            if fc in agree or fc.n >= others:
                continue
            out.extend(OddFixture(pid, fc.city, expected, others) for pid in fc.fixtures)
    return out


def judge(g: Ground, atlas: Atlas) -> list[Finding]:
    verdict = judge_city(g, atlas)
    out = [f for f in (judge_country(g), verdict.finding) if f is not None]
    for odd in odd_fixtures(g, reference_city(g, verdict)):
        out.append(Finding.of(
            DATASET, f"fixture {odd.provider_fixture_id} at {g.label}", "venue_city", Kind.INCONSISTENT,
            Severity.MEDIUM, api=odd.expected, db=odd.city,
            note=f"the match page shows this fixture's own city; {odd.others} other home matches of the club at this "
                 f"ground name '{odd.expected}'"))
    return out


def venue_in(body: Mapping[str, Any], provider_venue_id: int) -> dict[str, Any] | None:
    """The venue block with this id in a /teams answer (``{"team", "venue"}`` entries) or a /venues one."""
    for entry in body.get("response") or []:
        if not isinstance(entry, dict):
            continue
        block = entry.get("venue") if isinstance(entry.get("venue"), dict) else entry
        if isinstance(block, dict) and block.get("id") == provider_venue_id:
            return block
    return None


def _text(v: Any) -> str | None:
    return v.strip() if isinstance(v, str) and v.strip() else None


def provider_venues(conn: psycopg.Connection[Any], store: PayloadStore, grounds: Mapping[int, Mapping[str, Any]],
                    problems: list[str]) -> dict[int, ProviderVenue]:
    """venue id -> the newest stored payload (re-hashed against its index) whose block for the venue names a city."""
    if not grounds:
        return {}
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(PAYLOADS_SQL, {"ids": sorted(grounds)})
        rows = cur.fetchall()
    bodies: dict[str, dict[str, Any] | None] = {}
    tried: Counter[int] = Counter()
    out: dict[int, ProviderVenue] = {}
    for r in rows:
        vid = int(r["venue_id"])
        pid = grounds[vid].get("provider_venue_id")
        if vid in out or tried[vid] >= PAYLOAD_TRIES or pid is None:
            continue
        tried[vid] += 1
        h = str(r["hash"])
        if h not in bodies:
            body: dict[str, Any] | None = None
            try:
                raw = store.load(str(r["file_path"])).get("body")
                if body_hash(raw) != h:
                    problems.append(f"{r['file_path']}: does not re-hash to {h[:12]} - not read")
                elif isinstance(raw, dict):
                    body = raw
            except (OSError, ValueError) as exc:
                problems.append(f"{r['file_path']}: {type(exc).__name__} - not read")
            bodies[h] = body
        body = bodies[h]
        block = venue_in(body, int(pid)) if body is not None else None
        if block is None or _text(block.get("city")) is None:
            continue
        out[vid] = ProviderVenue(city=_text(block.get("city")), country=_text(block.get("country")),
                                 name=_text(block.get("name")), endpoint=str(r["endpoint"]),
                                 fetched_at=r["fetched_at"], payload_hash=h, file_path=str(r["file_path"]))
    return out


@dataclass
class Collected:
    grounds: list[Ground]
    atlas: Atlas
    problems: list[str] = field(default_factory=list)
    provider_read: bool = False


def collect(conn: psycopg.Connection[Any], store: PayloadStore | None = None, *,
            venue_ids: Sequence[int] | None = None) -> Collected:
    """Every ground in scope with its evidence. ``store`` None: the provider's stored payloads are not read (the
    first city signal is then silent). ``venue_ids``: only these core.venues ids (still only if in scope)."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(SCOPE_SQL)
        scope = cur.fetchall()
        wanted = set(venue_ids) if venue_ids is not None else None
        comps: dict[int, set[tuple[str, str | None]]] = {}
        homes: dict[int, set[str]] = {}
        for r in scope:
            vid = int(r["venue_id"])
            if wanted is not None and vid not in wanted:
                continue
            comps.setdefault(vid, set()).add((str(r["competition"]), r["competition_country"]))
            if r["home_country"]:
                homes.setdefault(vid, set()).add(str(r["home_country"]))
        ids = sorted(comps)
        if not ids:
            return Collected([], Atlas(), provider_read=store is not None)
        cur.execute(VENUES_SQL, {"ids": ids})
        venues = {int(r["id"]): dict(r) for r in cur.fetchall()}
        cur.execute(ATLAS_SQL)
        atlas = Atlas.of(cur.fetchall())
        cur.execute(FIXTURE_CITIES_SQL, {"ids": ids})
        groups = cur.fetchall()
    problems: list[str] = []
    provider = provider_venues(conn, store, venues, problems) if store is not None else {}
    named: dict[int, list[FixtureCity]] = {}
    for r in groups:
        v = venues.get(int(r["venue_id"]))
        if v is None or not same_place(v["name"], r["venue_name"]):
            continue
        named.setdefault(int(r["venue_id"]), []).append(FixtureCity(
            int(r["home_team_id"]), str(r["venue_name"]), str(r["venue_city"]), int(r["n"]),
            tuple(int(x) for x in r["fixtures"] or ())))
    grounds = [Ground(venue_id=vid, provider_venue_id=v["provider_venue_id"], name=str(v["name"]), city=v["city"],
                      country=v["country"], competitions=tuple(sorted(comps[vid], key=lambda c: c[0])),
                      home_countries=tuple(sorted(homes.get(vid, ()))),
                      fixture_cities=tuple(named.get(vid, ())), provider=provider.get(vid))
               for vid, v in sorted(venues.items())]
    return Collected(grounds, atlas, problems, provider_read=store is not None)


def venue_places(conn: psycopg.Connection[Any], tally: Tally, store: PayloadStore | None = None) -> Collected:
    """The control: one finding per contradiction, into the ``venues`` tally (``audit.truth_findings``)."""
    got = collect(conn, store)
    flagged = 0
    for g in got.grounds:
        tally.compared()
        found = judge(g, got.atlas)
        if found:
            flagged += 1
            tally.extend(found)
        else:
            tally.matched += 1
    with_provider = sum(1 for g in got.grounds if g.provider is not None)
    tally.notes.append(
        f"venue_places: {len(got.grounds):,} grounds of current tracked domestic leagues, {flagged:,} with a city or "
        f"country contradicted; provider record read for {with_provider:,}"
        + ("" if got.provider_read else " (raw store not given: provider records not read)"))
    tally.notes.extend(f"venue_places problem: {p}" for p in got.problems[:10])
    return got
