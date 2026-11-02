"""Neutral venue (plan F0, defect 1): gathering the facts a verdict needs, storing it, and the switch the models read.

``fbi.catalog.neutral`` decides; this module feeds it and keeps the answer.

* ``classify_fixtures`` builds the facts of a set of fixtures from the database - the ground the payload names, the
  country of that ground, each side's usual grounds from its own league home matches BEFORE the match, and the other
  matches of the competition season at the same ground - classifies them and writes ``core.fixture_venue_class``.
  Domestic league matches are left out: they are never neutral and a row for each would say nothing.
* Everything it reads is known before the match: the history ends at the kick-off, the schedule it looks at ends two
  days after it. So the verdict of a played match is the one a forecast made before it could have had, and a backtest
  can use it without leaking the future.
* ``rule_in_force`` is the switch. The models read a verdict only for the rule the newest row of
  ``analytics.neutral_rule_promotion`` names, and that table is empty (rule OFF) until a person promotes a rule that a
  stored before/after backtest (``analytics.neutral_rule_runs``) justified. Nothing here turns the models on.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Any

import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

from fbi.catalog.neutral import (
    HISTORY_DAYS,
    HISTORY_N,
    RULE_VERSION,
    S2_AHEAD_DAYS,
    S2_WINDOW_DAYS,
    TWIN_DAYS,
    Classification,
    FixtureFacts,
    Ground,
    Shared,
    Side,
    classify,
    is_final,
    is_semi,
    same_ground,
)
from fbi.core.clock import now
from fbi.core.places import (
    cities_agree,
    cities_compatible,
    place_key,
    place_words,
    same_place,
    split_place,
)

CHUNK = 2000
"""Fixtures classified per round trip of a backfill."""
MIN_REASON = 10
PROMOTERS = ("owner", "system")

_FACTS_SQL = """
SELECT f.id, f.kickoff_at, f.round, f.competition_season_id, c.competition_type,
       f.venue_id, f.venue_name, f.venue_city, v.name AS v_name, v.city AS v_city, v.country AS v_country,
       f.home_team_id, th.country AS home_country, COALESCE(kh.is_national, th.is_national) AS home_national,
       vh.country AS home_venue_country, th.venue_id AS home_venue_id, vh.name AS home_venue_name,
       vh.city AS home_venue_city,
       f.away_team_id, ta.country AS away_country, COALESCE(ka.is_national, ta.is_national) AS away_national,
       va.country AS away_venue_country, ta.venue_id AS away_venue_id, va.name AS away_venue_name,
       va.city AS away_venue_city
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
  JOIN core.teams ta ON ta.id = f.away_team_id
  LEFT JOIN core.team_kind kh ON kh.team_id = th.id
  LEFT JOIN core.team_kind ka ON ka.team_id = ta.id
  LEFT JOIN core.venues v ON v.id = f.venue_id
  LEFT JOIN core.venues vh ON vh.id = th.venue_id
  LEFT JOIN core.venues va ON va.id = ta.venue_id
 WHERE f.id = ANY(%s) AND c.competition_type <> 'domestic_league'
 ORDER BY f.kickoff_at, f.id
"""

_LEAGUE_COUNTRIES_SQL = """
SELECT f.venue_name, f.venue_city, th.country, count(*) AS n
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  JOIN core.teams th ON th.id = f.home_team_id
 WHERE c.competition_type = 'domestic_league' AND f.venue_name IS NOT NULL AND th.country IS NOT NULL
   AND f.status_group = 'finished'
 GROUP BY 1, 2, 3
"""

_HISTORY_SQL = """
SELECT f.home_team_id AS team_id, f.kickoff_at, f.venue_id, f.venue_name, f.venue_city,
       v.name AS v_name, v.city AS v_city
  FROM core.fixtures f
  JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
  JOIN core.competitions c ON c.id = cs.competition_id
  LEFT JOIN core.venues v ON v.id = f.venue_id
 WHERE f.home_team_id = ANY(%s) AND c.competition_type = 'domestic_league'
   AND f.kickoff_at >= %s AND f.kickoff_at < %s AND f.venue_name IS NOT NULL
   AND f.status_group NOT IN ('cancelled', 'postponed')
 ORDER BY f.home_team_id, f.kickoff_at DESC
"""

_SHARED_SQL = """
SELECT f.id, f.competition_season_id, f.kickoff_at, f.round, f.home_team_id, f.away_team_id,
       f.venue_id, f.venue_name, f.venue_city, v.name AS v_name, v.city AS v_city
  FROM core.fixtures f
  LEFT JOIN core.venues v ON v.id = f.venue_id
 WHERE f.competition_season_id = ANY(%s) AND f.kickoff_at >= %s AND f.kickoff_at < %s
   AND f.venue_name IS NOT NULL AND f.status_group <> 'cancelled'
"""

_LEGS_SQL = """
SELECT f.id, count(*) AS legs
  FROM core.fixtures f
  JOIN core.fixtures g ON g.competition_season_id = f.competition_season_id AND g.round IS NOT DISTINCT FROM f.round
                      AND g.status_group <> 'cancelled'
                      AND ((g.home_team_id = f.home_team_id AND g.away_team_id = f.away_team_id)
                        OR (g.home_team_id = f.away_team_id AND g.away_team_id = f.home_team_id))
 WHERE f.id = ANY(%s)
 GROUP BY f.id
"""

_UPSERT_SQL = """
INSERT INTO core.fixture_venue_class (fixture_id, rule_version, neutral, basis, evidence, classified_at)
VALUES (%s, %s, %s, %s, %s, %s)
ON CONFLICT (fixture_id, rule_version) DO UPDATE
   SET neutral = EXCLUDED.neutral, basis = EXCLUDED.basis, evidence = EXCLUDED.evidence,
       classified_at = EXCLUDED.classified_at
 WHERE (core.fixture_venue_class.neutral, core.fixture_venue_class.basis, core.fixture_venue_class.evidence)
       IS DISTINCT FROM (EXCLUDED.neutral, EXCLUDED.basis, EXCLUDED.evidence)
"""


@dataclass(slots=True)
class Counts:
    """What a pass did: fixtures looked at (league ones are not), rows written (new or changed), and the verdicts."""

    seen: int = 0
    written: int = 0
    neutral: int = 0
    by_basis: Counter[str] = field(default_factory=Counter)

    def add(self, other: Counts) -> None:
        self.seen += other.seen
        self.written += other.written
        self.neutral += other.neutral
        self.by_basis.update(other.by_basis)


class VenueIndex:
    """``core.venues`` by the distinctive words of their names: which country a ground named ``(name, city)`` is in,
    when the table gives one answer. A name of generic words only, or one that two countries share, answers None."""

    def __init__(self, rows: Iterable[tuple[int, str, str | None, str | None]]) -> None:
        self._by_word: dict[str, list[tuple[int, str, str | None, str]]] = {}
        self.cities: dict[str, Counter[str]] = {}
        """How many grounds of the table are filed under each city, by country."""
        for vid, name, city, country in rows:
            if not country:
                continue
            for word in place_words(name):
                self._by_word.setdefault(word, []).append((vid, name, city, country))
            if place_key(city):
                self.cities.setdefault(place_key(city), Counter())[country] += 1

    def lookup(self, name: str | None, city: str | None) -> tuple[str | None, tuple[int, ...]]:
        """(country, the table's venue ids) of the ground of the table that has this name AND this city (both as
        ``split_place`` leaves them). Both cities must be given: a name alone says too little ('The Vale Stadium' is
        also a ground in Portugal). (None, ()) when the table has no such ground or two countries have one."""
        words = place_words(name)
        if not name or not words or not place_key(city):
            return None, ()
        found: dict[int, str] = {}
        for word in words:
            for vid, vname, vcity, vcountry in self._by_word.get(word, ()):
                if same_place(vname, name) and cities_agree(vcity, city):
                    found[vid] = vcountry
        countries = set(found.values())
        return (next(iter(countries)), tuple(sorted(found))) if len(countries) == 1 else (None, ())

    def country(self, name: str | None, city: str | None) -> str | None:
        return self.lookup(name, city)[0]


def load_venue_index(conn: psycopg.Connection[Any]) -> VenueIndex:
    with conn.cursor() as cur:
        cur.execute("SELECT id, name, city, country FROM core.venues WHERE country IS NOT NULL")
        rows: list[tuple[int, str, str | None, str | None]] = []
        for i, n, c, k in cur.fetchall():
            name, city = split_place(n, c)
            if name:
                rows.append((int(i), name, city, str(k)))
        return VenueIndex(rows)


def team_countries(conn: psycopg.Connection[Any]) -> frozenset[str]:
    """The country labels teams carry: a ground's country is compared with a team's only if some team uses that label."""
    with conn.cursor() as cur:
        cur.execute("SELECT DISTINCT country FROM core.teams WHERE country IS NOT NULL")
        return frozenset(str(r[0]) for r in cur.fetchall())


LEAGUE_MIN_MATCHES = 3
LEAGUE_MIN_SHARE = 0.8
CITY_MIN_VENUES = 3
CITY_MIN_SHARE = 0.6
DISPUTED = "disputed"


@dataclass(frozen=True, slots=True)
class Reference:
    """What every verdict of a pass is read against, loaded once: the country labels teams use, ``core.venues`` by
    name, the countries of the sides that played league home matches at each ground, the countries of the teams
    whose home venue (``core.teams.venue_id``) is each venue, and the countries in which league home matches were
    played in each city."""

    labels: frozenset[str]
    venues: VenueIndex
    league: Mapping[tuple[str, str], Mapping[str, int]]
    team_home: Mapping[int, Mapping[str, int]]
    cities: Mapping[str, Mapping[str, int]] = field(default_factory=dict)

    def city_says_otherwise(self, city: str | None, country: str) -> bool:
        """Whether the city itself puts a ground in another country than the one its sources agreed on. Two witnesses:
        the countries in which at least ``LEAGUE_MIN_MATCHES`` league home matches were played under that city's name
        (several for a name two countries share), and the country most grounds of the table are filed under in it (at
        least ``CITY_MIN_VENUES`` grounds, ``CITY_MIN_SHARE`` of them). Neither is evidence for a country; both can
        veto one - the table and the teams filed under a ground can be wrong together (the Kenyan national side's
        'home' in Kampala)."""
        key = place_key(city)
        if not key:
            return False
        played = {c for c, n in self.cities.get(key, {}).items() if n >= LEAGUE_MIN_MATCHES}
        if played and country not in played:
            return True
        filed = self.venues.cities.get(key)
        if filed:
            total = sum(filed.values())
            top, n = max(filed.items(), key=lambda kv: kv[1])
            return total >= CITY_MIN_VENUES and n / total >= CITY_MIN_SHARE and top != country
        return False

    def league_country(self, name: str | None, city: str | None) -> str | None:
        """The country of the sides that played league home matches at this ground: at least ``LEAGUE_MIN_MATCHES`` of
        them and ``LEAGUE_MIN_SHARE`` of the sides. None when no league match was played there; ``DISPUTED`` when the
        matches there disagree."""
        seen = self.league.get((place_key(name), place_key(city)))
        if not seen:
            return None
        total = sum(seen.values())
        top, count = max(seen.items(), key=lambda kv: kv[1])
        return top if total >= LEAGUE_MIN_MATCHES and count / total >= LEAGUE_MIN_SHARE else DISPUTED

    def team_home_country(self, venue_ids: Iterable[int]) -> str | None:
        """The country of the teams whose home venue is one of these venues: None if no team has them as home,
        ``DISPUTED`` if their teams disagree."""
        seen: Counter[str] = Counter()
        for vid in venue_ids:
            seen.update(self.team_home.get(vid, {}))
        if not seen:
            return None
        return next(iter(seen)) if len(seen) == 1 else DISPUTED


def load_reference(conn: psycopg.Connection[Any]) -> Reference:
    league: dict[tuple[str, str], Counter[str]] = {}
    cities: dict[str, Counter[str]] = {}
    team_home: dict[int, Counter[str]] = {}
    with conn.cursor() as cur:
        cur.execute(_LEAGUE_COUNTRIES_SQL)
        for name, city, country, n in cur.fetchall():
            sname, scity = split_place(name, city)
            league.setdefault((place_key(sname), place_key(scity)), Counter())[str(country)] += int(n)
            if place_key(scity):
                cities.setdefault(place_key(scity), Counter())[str(country)] += int(n)
        cur.execute("SELECT venue_id, country, count(*) FROM core.teams WHERE venue_id IS NOT NULL "
                    "AND country IS NOT NULL GROUP BY 1, 2")
        for vid, country, n in cur.fetchall():
            team_home.setdefault(int(vid), Counter())[str(country)] += int(n)
    return Reference(team_countries(conn), load_venue_index(conn), league, team_home, cities)


def possible_countries(ref: Reference, name: str | None, city: str | None, ids: Sequence[int],
                       named: Mapping[str, str]) -> frozenset[str]:
    """Every country an unsettled ground may be in, for the one question "could a side be at home here?": each country
    any source names for it (the venues table, ALL the sides that played league home matches there - not only the
    majority -, the teams whose home it is) and the countries in which league home matches were played under its city's
    name (several of them: a name two countries share). Only labels some team carries, since only a side of such a country
    can be compared. It is a net for a host nation, never a country to use: a wider net only ever turns a neutral into
    "no evidence"."""
    out: set[str] = set(named.values())
    out.update(ref.league.get((place_key(name), place_key(city)), ()))
    for vid in ids:
        out.update(ref.team_home.get(vid, ()))
    out.update(c for c, n in ref.cities.get(place_key(city), {}).items() if n >= LEAGUE_MIN_MATCHES)
    return frozenset(out & ref.labels)


def checked_venue_id(row: Mapping[str, Any]) -> int | None:
    """The provider's venue id, but only where it points at the ground the payload names: the same name and a city that
    does not contradict it. The provider keeps a club's venue id for a home match played elsewhere and uses one id for
    different grounds, so the id alone says nothing."""
    vid, vname = row.get("venue_id"), row.get("venue_name")
    if vid is None or not vname or not row.get("v_name"):
        return None
    table_name, table_city = split_place(row["v_name"], row.get("v_city"))
    name, city = split_place(vname, row.get("venue_city"))
    if same_place(table_name, name) and cities_compatible(table_city, city):
        return int(vid)
    return None


def ground_of(row: Mapping[str, Any], ref: Reference | None) -> Ground:
    """The ground a fixture row names, with its country when sources that do not depend on each other say the same.

    A country is worked out from up to three places: the venues table (by the provider's id, when it points at this
    ground and both cities agree, or by the ground's name and city), the countries of the sides that played LEAGUE home
    matches at the same ground, and the countries of the teams whose home venue it is. The table has a few wrong
    countries (a stadium in Lilongwe filed under Comoros); the other two have their own, border clubs that play in a
    neighbour's league (FC Andorra, in Spain's). So the country is used only where every source that answers says the
    same, and not when two disagree: a ground whose country is in doubt is "unknown", which reads as not neutral. A
    country no team carries as its own label is not used either.

    The sources can also be wrong together: the provider files a ground under the country of the team it was first
    seen with (the Kenyan national side played its home matches in Kampala, so a stadium of Kampala is 'Kenya', and so
    are the teams filed under it). The city is the last witness: if the league matches played under its name, or most of
    the grounds the table files under it, are in another country, the country is in doubt."""
    vid = checked_venue_id(row)
    name, city = split_place(row.get("venue_name"), row.get("venue_city"))
    table_city = split_place(row.get("v_name"), row.get("v_city"))[1]
    if ref is None:
        return Ground(name, city, vid)
    named: dict[str, str] = {}
    ids: tuple[int, ...] = ()
    if vid is not None and row.get("v_country") and cities_agree(table_city, city):
        named["venue_id"], ids = str(row["v_country"]), (vid,)
    elif name:
        table, ids = ref.venues.lookup(name, city)
        if table:
            named["venues_table"] = table
    doubt = False
    for source, answer in (("league_home_matches", ref.league_country(name, city)),
                           ("team_home_venue", ref.team_home_country(ids))):
        if answer == DISPUTED:
            doubt = True
        elif answer is not None:
            named[source] = answer
    countries = set(named.values())
    # Whatever is not settled keeps the countries it may be in, for the host-nation test of the shared-ground evidence.
    maybe = possible_countries(ref, name, city, ids, named)
    if doubt or len(countries) > 1:
        return Ground(name, city, vid, None, DISPUTED, maybe)
    if not countries:
        return Ground(name, city, vid, countries=maybe)
    country = next(iter(countries))
    if country not in ref.labels:
        return Ground(name, city, vid, countries=maybe)
    # The table and the teams filed under it can be wrong together (a stadium of Kampala under Kenya, with the teams
    # that use it): the league matches played in a city of that name say in which country it is.
    if ref.city_says_otherwise(city, country):
        return Ground(name, city, vid, None, DISPUTED, maybe)
    return Ground(name, city, vid, country, "+".join(named))


def side_country(country: object, home_venue_country: object) -> tuple[str | None, str | None]:
    """A side's country label, unless its own home venue says it is somewhere else: the provider mislabels a few teams
    (a Cypriot women's side filed under Romania), and which of the two is wrong is not known, so neither is used."""
    label = None if country is None else str(country)
    venue = None if home_venue_country is None else str(home_venue_country)
    if label and venue and label != venue:
        return None, f"label {label} against the country of its home venue, {venue}"
    return label, None


def _history(rows: Sequence[Mapping[str, Any]]) -> dict[int, list[tuple[datetime, Ground]]]:
    out: dict[int, list[tuple[datetime, Ground]]] = {}
    for r in rows:
        name, city = split_place(r["venue_name"], r["venue_city"])
        out.setdefault(int(r["team_id"]), []).append((r["kickoff_at"], Ground(name, city, checked_venue_id(r))))
    return out


def _before(history: Sequence[tuple[datetime, Ground]] | None, kickoff: datetime) -> tuple[Ground, ...]:
    """A side's league home grounds before ``kickoff``: at most ``HISTORY_N`` of the last ``HISTORY_DAYS`` days, newest
    first (``history`` is newest first)."""
    since = kickoff - timedelta(days=HISTORY_DAYS)
    out: list[Ground] = []
    for at, ground in history or ():
        if at >= kickoff:
            continue
        if at < since or len(out) >= HISTORY_N:
            break
        out.append(ground)
    return tuple(out)


def _shared(own: Ground, row: Mapping[str, Any], others: Sequence[Mapping[str, Any]]) -> Shared | None:
    """The matches of the season at the same ground from ``S2_WINDOW_DAYS`` before to ``S2_AHEAD_DAYS`` after this one,
    this one included, and how many different nominal home sides they have; and its twins: the other matches of the same
    round at that ground no more than ``TWIN_DAYS`` apart, between two sides that are not this match's."""
    if not own.named:
        return None
    kickoff, season_id = row["kickoff_at"], int(row["competition_season_id"])
    since, until = kickoff - timedelta(days=S2_WINDOW_DAYS), kickoff + timedelta(days=S2_AHEAD_DAYS)
    twin_since, twin_until = kickoff - timedelta(days=TWIN_DAYS), kickoff + timedelta(days=TWIN_DAYS)
    mine = {int(row["home_team_id"]), int(row["away_team_id"])}
    matches = twins = 0
    home_sides: set[int] = set()
    for r in others:
        if int(r["competition_season_id"]) != season_id:
            continue
        at = r["kickoff_at"]
        counts = since <= at <= until
        twin = (twin_since <= at <= twin_until and int(r["id"]) != int(row["id"]) and r["round"] == row["round"]
                and not mine & {int(r["home_team_id"]), int(r["away_team_id"])})
        if not (counts or twin):
            continue
        name, city = split_place(r["venue_name"], r["venue_city"])
        if not same_ground(own, Ground(name, city, checked_venue_id(r))):
            continue
        if counts:
            matches += 1
            home_sides.add(int(r["home_team_id"]))
        twins += int(twin)
    return Shared(matches, len(home_sides), twins)


def build_facts(conn: psycopg.Connection[Any], fixture_ids: Sequence[int],
                ref: Reference | None = None) -> list[FixtureFacts]:
    """The facts of the non-league fixtures among ``fixture_ids``, oldest kick-off first."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(_FACTS_SQL, (list(fixture_ids),))
        rows = cur.fetchall()
    if not rows:
        return []
    ref = ref or load_reference(conn)
    club_teams = {int(r[side]) for r in rows for side in ("home_team_id", "away_team_id")
                  if r[side.replace("team_id", "national")] is False}
    first, last = min(r["kickoff_at"] for r in rows), max(r["kickoff_at"] for r in rows)
    history: dict[int, list[tuple[datetime, Ground]]] = {}
    if club_teams:
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_HISTORY_SQL, (sorted(club_teams), first - timedelta(days=HISTORY_DAYS), last))
            history = _history(cur.fetchall())
    both_clubs_rows = [r for r in rows if r["home_national"] is False and r["away_national"] is False]
    seasons = sorted({int(r["competition_season_id"]) for r in both_clubs_rows})
    shared_rows: Sequence[Mapping[str, Any]] = []
    if seasons:
        ahead = max(S2_AHEAD_DAYS, TWIN_DAYS)
        with conn.cursor(row_factory=dict_row) as cur:
            cur.execute(_SHARED_SQL, (seasons, first - timedelta(days=max(S2_WINDOW_DAYS, TWIN_DAYS)),
                                      last + timedelta(days=ahead + 1)))
            shared_rows = cur.fetchall()
    # A final or a semi-final of two legs is played at the clubs' grounds: count the matches of each such pair.
    chosen = [int(r["id"]) for r in both_clubs_rows if is_final(r["round"]) or is_semi(r["round"])]
    legs: dict[int, int] = {}
    if chosen:
        with conn.cursor() as cur:
            cur.execute(_LEGS_SQL, (chosen,))
            legs = {int(i): int(n) for i, n in cur.fetchall()}
    out: list[FixtureFacts] = []
    for r in rows:
        ground = ground_of(r, ref)
        sides: list[Side] = []
        for prefix in ("home", "away"):
            team_id = int(r[f"{prefix}_team_id"])
            national = r[f"{prefix}_national"]
            past = _before(history.get(team_id), r["kickoff_at"]) if national is False else ()
            # a national side's label is the one the venues of its home matches carry (checked on the data); a club's
            # is checked against its own home venue
            country, note = (side_country(r[f"{prefix}_country"], r[f"{prefix}_venue_country"]) if national is False
                             else (r[f"{prefix}_country"], None))
            homes: tuple[Ground, ...] = ()
            if national is False:
                home_name, home_city = split_place(r[f"{prefix}_venue_name"], r[f"{prefix}_venue_city"])
                if home_name:
                    homes = (Ground(home_name, home_city, r[f"{prefix}_venue_id"]),)
            sides.append(Side(team_id, country, national, past, note, homes))
        both_clubs = r["home_national"] is False and r["away_national"] is False
        shared = _shared(ground, r, shared_rows) if both_clubs else None
        out.append(FixtureFacts(int(r["id"]), str(r["competition_type"]), r["round"], ground, sides[0], sides[1],
                                shared, legs.get(int(r["id"]), 1)))
    return out


def store(conn: psycopg.Connection[Any], verdicts: Iterable[tuple[int, Classification]], *,
          at: datetime | None = None) -> Counts:
    """Write the verdicts (only where they are new or changed). The caller commits."""
    counts = Counts()
    stamp = at or now()
    with conn.cursor() as cur:
        for fixture_id, v in verdicts:
            counts.seen += 1
            counts.by_basis[v.basis] += 1
            counts.neutral += int(v.neutral)
            cur.execute(_UPSERT_SQL, (fixture_id, v.rule, v.neutral, v.basis, Jsonb(v.evidence), stamp))
            counts.written += max(cur.rowcount, 0)
    return counts


def _non_league(conn: psycopg.Connection[Any], fixture_ids: Sequence[int]) -> list[int]:
    """The fixtures among these that are not domestic league matches (the only ones with a verdict)."""
    if not fixture_ids:
        return []
    with conn.cursor() as cur:
        cur.execute(
            "SELECT f.id FROM core.fixtures f JOIN core.competition_seasons cs ON cs.id = f.competition_season_id "
            "JOIN core.competitions c ON c.id = cs.competition_id "
            "WHERE f.id = ANY(%s) AND c.competition_type <> 'domestic_league' ORDER BY f.id", (list(fixture_ids),))
        return [int(r[0]) for r in cur.fetchall()]


def classify_fixtures(conn: psycopg.Connection[Any], fixture_ids: Sequence[int], *,
                      at: datetime | None = None, ref: Reference | None = None) -> Counts:
    """Classify these fixtures and store the verdicts. League matches are skipped (never neutral, no row), and a call
    with none left does not even load the reference. The caller commits."""
    total = Counts()
    ids = _non_league(conn, sorted({int(i) for i in fixture_ids}))
    if not ids:
        return total
    ref = ref or load_reference(conn)
    for start in range(0, len(ids), CHUNK):
        facts = build_facts(conn, ids[start:start + CHUNK], ref)
        total.add(store(conn, ((f.fixture_id, classify(f)) for f in facts), at=at))
    return total


def classify_provider_fixtures(conn: psycopg.Connection[Any], provider_fixture_ids: Sequence[int], *,
                               at: datetime | None = None) -> Counts:
    """``classify_fixtures`` for the fixtures a provider payload names (its ids, not ours): what the ingestion calls
    right after it has written them. The caller commits."""
    if not provider_fixture_ids:
        return Counts()
    with conn.cursor() as cur:
        cur.execute("SELECT id FROM core.fixtures WHERE provider_fixture_id = ANY(%s)",
                    (sorted({int(i) for i in provider_fixture_ids}),))
        ids = [int(r[0]) for r in cur.fetchall()]
    return classify_fixtures(conn, ids, at=at)


def unclassified_ids(conn: psycopg.Connection[Any], *, rule_version: str = RULE_VERSION,
                     since: datetime | None = None, until: datetime | None = None) -> list[int]:
    """The non-league fixtures that have no verdict of this rule yet, oldest first."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.id FROM core.fixtures f
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
             WHERE c.competition_type <> 'domestic_league'
               AND (%(since)s::timestamptz IS NULL OR f.kickoff_at >= %(since)s)
               AND (%(until)s::timestamptz IS NULL OR f.kickoff_at < %(until)s)
               AND NOT EXISTS (SELECT 1 FROM core.fixture_venue_class k
                                WHERE k.fixture_id = f.id AND k.rule_version = %(rule)s)
             ORDER BY f.kickoff_at, f.id""",
            {"since": since, "until": until, "rule": rule_version})
        return [int(r[0]) for r in cur.fetchall()]


def non_league_ids(conn: psycopg.Connection[Any], *, since: datetime | None = None,
                   until: datetime | None = None) -> list[int]:
    """Every non-league fixture kicking off in [since, until), oldest first - with or without a verdict."""
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT f.id FROM core.fixtures f
              JOIN core.competition_seasons cs ON cs.id = f.competition_season_id
              JOIN core.competitions c ON c.id = cs.competition_id
             WHERE c.competition_type <> 'domestic_league'
               AND (%(since)s::timestamptz IS NULL OR f.kickoff_at >= %(since)s)
               AND (%(until)s::timestamptz IS NULL OR f.kickoff_at < %(until)s)
             ORDER BY f.kickoff_at, f.id""", {"since": since, "until": until})
        return [int(r[0]) for r in cur.fetchall()]


def classify_everything(conn: psycopg.Connection[Any], *, only_missing: bool = True, since: datetime | None = None,
                        until: datetime | None = None, at: datetime | None = None) -> Counts:
    """Backfill: every non-league fixture (or those without a verdict yet). The caller commits."""
    ids = (unclassified_ids(conn, since=since, until=until) if only_missing
           else non_league_ids(conn, since=since, until=until))
    return classify_fixtures(conn, ids, at=at)


# ------------------------------------------------------------------------------------------------- the switch


@dataclass(frozen=True, slots=True)
class Promotion:
    """One row of the history of the switch: a rule put in force, or the rule retired (``rule_version`` None)."""

    id: int
    promoted_at: datetime
    promoted_by: str
    action: str
    rule_version: str | None
    reason: str
    run_id: int | None
    previous_id: int | None
    evidence: dict[str, Any]


_PROMOTION_COLUMNS = "id, promoted_at, promoted_by, action, rule_version, reason, run_id, previous_id, evidence"


def _promotion(row: Mapping[str, Any]) -> Promotion:
    return Promotion(int(row["id"]), row["promoted_at"], str(row["promoted_by"]), str(row["action"]),
                     None if row["rule_version"] is None else str(row["rule_version"]), str(row["reason"]),
                     None if row["run_id"] is None else int(row["run_id"]),
                     None if row["previous_id"] is None else int(row["previous_id"]), dict(row["evidence"]))


def promoted(conn: psycopg.Connection[Any]) -> Promotion | None:
    """The newest row of the history of the switch (a promotion or a retirement), None if it was never touched."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_PROMOTION_COLUMNS} FROM analytics.neutral_rule_promotion ORDER BY id DESC LIMIT 1")
        row = cur.fetchone()
    return None if row is None else _promotion(row)


def history(conn: psycopg.Connection[Any], *, limit: int = 20) -> list[Promotion]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_PROMOTION_COLUMNS} FROM analytics.neutral_rule_promotion ORDER BY id DESC LIMIT %s",
                    (limit,))
        return [_promotion(r) for r in cur.fetchall()]


def rule_in_force(conn: psycopg.Connection[Any]) -> str | None:
    """The rule the models read neutral verdicts of: None (OFF) until a person promotes one, and again after a
    retirement. This is the only way the verdicts reach a model."""
    p = promoted(conn)
    return None if p is None else p.rule_version


def check_reason(by: str, reason: str) -> str:
    reason = reason.strip()
    if by not in PROMOTERS:
        raise ValueError(f"promoted_by must be one of {PROMOTERS}, not {by!r}")
    if len(reason) < MIN_REASON:
        raise ValueError(f"a decision needs a reason of at least {MIN_REASON} characters")
    return reason


VERDICTS = ("justified", "not_justified", "inconclusive")

_RUN_COLUMNS = "id, created_at, rule_version, protocol, verdict, labels, params, result, code_version, dataset_hash"


@dataclass(frozen=True, slots=True)
class Run:
    """A stored before/after backtest (``analytics.neutral_rule_runs``)."""

    id: int
    created_at: datetime
    rule_version: str
    verdict: str
    labels: dict[str, Any]
    result: dict[str, Any]
    protocol: str = ""
    params: dict[str, Any] = field(default_factory=dict)
    code_version: str | None = None
    dataset_hash: str | None = None


def _run(row: Mapping[str, Any]) -> Run:
    return Run(int(row["id"]), row["created_at"], str(row["rule_version"]), str(row["verdict"]), dict(row["labels"]),
               dict(row["result"]), str(row["protocol"]), dict(row["params"]),
               None if row["code_version"] is None else str(row["code_version"]),
               None if row["dataset_hash"] is None else str(row["dataset_hash"]))


def get_run(conn: psycopg.Connection[Any], run_id: int) -> Run:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} FROM analytics.neutral_rule_runs WHERE id = %s", (run_id,))
        row = cur.fetchone()
    if row is None:
        raise LookupError(f"no backtest run {run_id}")
    return _run(row)


def runs(conn: psycopg.Connection[Any], *, limit: int = 20) -> list[Run]:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"SELECT {_RUN_COLUMNS} FROM analytics.neutral_rule_runs ORDER BY id DESC LIMIT %s", (limit,))
        return [_run(r) for r in cur.fetchall()]


def record_run(conn: psycopg.Connection[Any], *, rule_version: str, protocol: str, verdict: str,
               labels: Mapping[str, Any], params: Mapping[str, Any], result: Mapping[str, Any],
               code_version: str | None = None, dataset_hash: str | None = None, at: datetime | None = None) -> Run:
    """Store a finished before/after backtest. The verdict is the arithmetic of the run itself (``fbi.backtesting
    .neutral_ab.decide``); this only keeps it. The caller commits."""
    if verdict not in VERDICTS:
        raise ValueError(f"a verdict is one of {VERDICTS}, not {verdict!r}")
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(
            f"INSERT INTO analytics.neutral_rule_runs (created_at, rule_version, protocol, verdict, labels, params, "
            f"result, code_version, dataset_hash) VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) RETURNING {_RUN_COLUMNS}",
            (at or now(), rule_version, protocol, verdict, Jsonb(dict(labels)), Jsonb(dict(params)),
             Jsonb(dict(result)), code_version, dataset_hash))
        row = cur.fetchone()
    assert row is not None
    return _run(row)


_LABELS_SQL = """
SELECT count(*) FILTER (WHERE k.neutral),
       md5(COALESCE(string_agg(k.fixture_id::text, ',' ORDER BY k.fixture_id) FILTER (WHERE k.neutral), ''))
  FROM core.fixture_venue_class k
  JOIN core.fixtures f ON f.id = k.fixture_id
 WHERE k.rule_version = %(rule)s AND (%(through)s::timestamptz IS NULL OR f.kickoff_at <= %(through)s)
"""


def label_state(conn: psycopg.Connection[Any], rule_version: str = RULE_VERSION, *,
                through: datetime | None = None) -> dict[str, Any]:
    """A fingerprint of the matches a rule calls neutral, for the fixtures kicking off up to ``through`` (all of them if
    None): how many, and a digest of their ids. A backtest is about exactly these labels, and a promotion is refused if
    they changed after it ran. Only the neutral ones count - a model reads nothing else - and only up to the run's own
    cut-off: the matches ingested since, in the future of the data the run saw, are not what it measured."""
    with conn.cursor() as cur:
        cur.execute(_LABELS_SQL, {"rule": rule_version, "through": through})
        n, digest = cur.fetchone() or (0, "")
    return {"rule_version": rule_version, "through": None if through is None else through.isoformat(),
            "neutral": int(n), "digest": str(digest)}


def labels_through(labels: Mapping[str, Any]) -> datetime | None:
    """The cut-off a stored fingerprint was taken at."""
    raw = labels.get("through")
    return None if raw is None else datetime.fromisoformat(str(raw))


@dataclass(frozen=True, slots=True)
class PromotionResult:
    promotion: Promotion
    changed: bool


def promote(conn: psycopg.Connection[Any], run_id: int, *, by: str, reason: str, who: str | None = None,
            at: datetime | None = None) -> PromotionResult:
    """Put the rule of a stored backtest in force. Refuses a run whose verdict is not ``justified`` and a run whose
    labels are no longer the stored ones. Promoting what is already in force writes nothing. The caller commits."""
    reason = check_reason(by, reason)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('analytics.neutral_rule_promotion'))")
    run = get_run(conn, run_id)
    if run.verdict != "justified":
        raise PermissionError(f"run {run_id} says {run.verdict!r}: only a justified rule can be put in force")
    state = label_state(conn, run.rule_version, through=labels_through(run.labels))
    if state != run.labels:
        raise PermissionError(f"the stored verdicts changed since run {run_id} (then {run.labels}, now {state}): "
                              "run the backtest again")
    current = promoted(conn)
    if current is not None and current.rule_version == run.rule_version and current.run_id == run_id:
        return PromotionResult(current, False)
    evidence = {"run": run_id, "verdict": run.verdict, "labels": run.labels,
                "headline": run.result.get("headline")} | ({} if who is None else {"who": who})
    return PromotionResult(_insert(conn, "promote", run.rule_version, run_id, by, reason, current, evidence, at), True)


def retire(conn: psycopg.Connection[Any], *, by: str, reason: str, who: str | None = None,
           at: datetime | None = None) -> PromotionResult:
    """Switch the rule off again: the models read no neutral verdicts. The verdicts stay. The caller commits."""
    reason = check_reason(by, reason)
    with conn.cursor() as cur:
        cur.execute("SELECT pg_advisory_xact_lock(hashtext('analytics.neutral_rule_promotion'))")
    current = promoted(conn)
    if current is None or current.rule_version is None:
        raise PermissionError("no rule is in force: nothing to retire")
    evidence = {"retired": current.rule_version} | ({} if who is None else {"who": who})
    return PromotionResult(_insert(conn, "retire", None, None, by, reason, current, evidence, at), True)


def _insert(conn: psycopg.Connection[Any], action: str, rule_version: str | None, run_id: int | None, by: str,
            reason: str, current: Promotion | None, evidence: dict[str, Any], at: datetime | None) -> Promotion:
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(f"INSERT INTO analytics.neutral_rule_promotion (promoted_at, promoted_by, action, rule_version, "
                    f"reason, run_id, previous_id, evidence) VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
                    f"RETURNING {_PROMOTION_COLUMNS}",
                    (at or now(), by, action, rule_version, reason, run_id,
                     None if current is None else current.id, Jsonb(evidence)))
        row = cur.fetchone()
    assert row is not None
    return _promotion(row)
