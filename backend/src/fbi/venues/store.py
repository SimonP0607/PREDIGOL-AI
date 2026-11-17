"""AD-H04 (IA-076) against the database: the load of a Wikidata snapshot with its altitudes, the links of matches, the review
queue, the decisions and the coverage.

Only new tables are written (``core.venue_geo_loads``, ``core.venue_geo``, ``core.fixture_venue_links``,
``core.venue_review_queue``, ``core.venue_review_decisions``); ``core.venues`` and ``core.fixtures`` are read, never written. Every
write is in one transaction and, without ``apply``, rolled back: the report then says what would have been written.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Iterable, Mapping, Sequence
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime, timedelta
from typing import Any, Final

import psycopg

from fbi.venues import elevation as dem
from fbi.venues.rules import (
    GEO_RULES,
    LINK_RULES,
    GeoMatch,
    Ground,
    LinkIndex,
    OurVenue,
    Question,
    Unlinked,
    elevation_check,
    link_all,
    match_all,
)
from fbi.venues.wikidata import LICENSE as WD_LICENSE
from fbi.venues.wikidata import Snapshot

LOCK_KEY: Final = "fbi.venue_geo"

TEAM_QIDS_SQL: Final = """
SELECT DISTINCT e.entity_id, e.external_id FROM core.entity_ids_live e
 WHERE e.entity_type = 'team' AND e.system = 'wikidata' AND e.review = 'accepted'"""
"""The Wikidata items of our clubs (AD-H01). Before IA-071 is loaded there are none and nothing is matched."""

VENUES_SQL: Final = """
SELECT v.id, v.name, v.city, v.country, array_agg(DISTINCT t.id) AS team_ids
  FROM core.venues v JOIN core.teams t ON t.venue_id = v.id
 GROUP BY v.id, v.name, v.city, v.country"""


def team_qids(conn: psycopg.Connection[Any]) -> dict[int, list[str]]:
    out: dict[int, list[str]] = {}
    with conn.cursor() as cur:
        cur.execute("SELECT to_regclass('core.entity_ids_live') IS NOT NULL")
        row = cur.fetchone()
        if not (row and row[0]):
            return out
        cur.execute(TEAM_QIDS_SQL)
        for team_id, qid in cur.fetchall():
            out.setdefault(int(team_id), []).append(str(qid))
    return out


def our_venues(conn: psycopg.Connection[Any], qids: Mapping[int, Sequence[str]]) -> list[OurVenue]:
    with conn.cursor() as cur:
        cur.execute(VENUES_SQL)
        rows = cur.fetchall()
    out: list[OurVenue] = []
    for vid, name, city, country, team_ids in rows:
        q = sorted({x for t in team_ids for x in qids.get(int(t), [])}, key=lambda s: int(s[1:]))
        if q:
            out.append(OurVenue(int(vid), str(name), city, country, tuple(q)))
    return out


@dataclass(slots=True)
class LoadReport:
    applied: bool
    load_id: int | None = None
    already_loaded: bool = False
    venues_considered: int = 0
    matched: int = 0
    with_coords: int = 0
    with_elevation: int = 0
    elevation_checks: dict[str, int] = field(default_factory=dict)
    by_method: dict[str, int] = field(default_factory=dict)
    questions: dict[str, int] = field(default_factory=dict)
    dem_tiles_read: int = 0
    dem_bytes_read: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _altitudes(matches: Sequence[GeoMatch], reader: dem.DemReader | None) -> dict[int, dem.Altitude]:
    if reader is None:
        return {}
    points = [(m.venue_id, m.coords[0], m.coords[1]) for m in matches if m.coords]
    return {vid: reader.altitude(lat, lon) for vid, lat, lon in dem.by_tile(points)}


def load(conn: psycopg.Connection[Any], snap: Snapshot, *, snapshot_name: str, actor: str, apply: bool = False,
         reader: dem.DemReader | None = None) -> LoadReport:
    """Match our stadiums to the snapshot, read their altitude and write one load (once per snapshot and rules version)."""
    report = LoadReport(applied=apply)
    with conn.transaction(force_rollback=not apply), conn.cursor() as cur:
        cur.execute("SELECT id FROM core.venue_geo_loads WHERE snapshot_sha256 = %s AND rules_version = %s",
                    (snap.sha256, GEO_RULES))
        row = cur.fetchone()
        if row:
            report.already_loaded, report.load_id = True, int(row[0])
            return report
        venues = our_venues(conn, team_qids(conn))
        report.venues_considered = len(venues)
        matches, questions = match_all(venues, snap)
        alts = _altitudes(matches, reader)
        if reader is not None:
            report.dem_tiles_read, report.dem_bytes_read = reader.tiles_read, reader.bytes_read
        licenses = {"wikidata": WD_LICENSE}
        if reader is not None:
            licenses.update(dem=dem.LICENSE, dem_notice=dem.NOTICE)
        cur.execute(
            "INSERT INTO core.venue_geo_loads (source, snapshot_name, snapshot_sha256, fetched_at, query_version, "
            "rules_version, dem, licenses, loaded_by) VALUES ('wikidata', %s, %s, %s, %s, %s, %s, %s::jsonb, %s) "
            "RETURNING id",
            (snapshot_name, snap.sha256, snap.fetched_at, snap.query_version, GEO_RULES,
             dem.DEM_RELEASE if reader is not None else None, json.dumps(licenses), actor))
        got = cur.fetchone()
        assert got
        load_id = report.load_id = int(got[0])
        for m in matches:
            alt = alts.get(m.venue_id)
            meters = alt.meters if alt is not None else None
            source: str | None = dem.DEM if meters is not None else None
            check = elevation_check(meters, m.elevation_wd) if m.coords else "no_dem"
            ev = dict(m.evidence)
            if alt is not None:
                ev.update(dem_tile=alt.tile, dem_tile_sha256=alt.tile_sha256, dem_pixel=alt.pixel, dem_status=alt.status)
            cur.execute(
                "INSERT INTO core.venue_geo (load_id, venue_id, qid, latitude, longitude, elevation_m, elevation_source, "
                "elevation_check, capacity_wikidata, method, confidence, rules_version, evidence) "
                "VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s::jsonb)",
                (load_id, m.venue_id, m.qid, m.coords[0] if m.coords else None, m.coords[1] if m.coords else None,
                 meters, source, check, m.capacity, m.method, m.confidence, GEO_RULES,
                 json.dumps(ev, sort_keys=True, default=str)))
            report.matched += 1
            report.with_coords += int(m.coords is not None)
            report.with_elevation += int(meters is not None)
            report.elevation_checks[check] = report.elevation_checks.get(check, 0) + 1
            report.by_method[m.method] = report.by_method.get(m.method, 0) + 1
        _ask(cur, questions, GEO_RULES, load_id, report.questions)
        cur.execute("UPDATE core.venue_geo_loads SET counts = %s::jsonb WHERE id = %s",
                    (json.dumps({"matched": report.matched, "with_coords": report.with_coords,
                                 "with_elevation": report.with_elevation, "questions": report.questions}), load_id))
    if not apply:
        report.load_id = None
    return report


def _ask(cur: psycopg.Cursor[Any], questions: Iterable[Question], rules: str, load_id: int | None,
         tally: dict[str, int]) -> None:
    for q in questions:
        cur.execute(
            "INSERT INTO core.venue_review_queue (kind, subject_id, reason, candidates, rules_version, load_id) "
            "VALUES (%s, %s, %s, %s::jsonb, %s, %s) ON CONFLICT (kind, subject_id, reason, rules_version) DO NOTHING",
            (q.kind, q.subject_id, q.reason, json.dumps({"candidates": list(q.candidates), **dict(q.evidence)},
                                                        sort_keys=True, default=str), rules, load_id))
        tally[q.reason] = tally.get(q.reason, 0) + 1


def retire(conn: psycopg.Connection[Any], load_id: int, *, actor: str, note: str, apply: bool = False) -> dict[str, Any]:
    with conn.transaction(force_rollback=not apply), conn.cursor() as cur:
        cur.execute("UPDATE core.venue_geo_loads SET status = 'retired', retired_by = %s, retired_at = now(), "
                    "retire_note = %s WHERE id = %s AND status = 'active'", (actor, note, load_id))
        n = cur.rowcount
    return {"applied": apply, "retired": bool(n), "load_id": load_id}


# ── links of matches ─────────────────────────────────────────────────────────────────────────────────────────────────────

UNLINKED_SQL: Final = """
SELECT f.id, f.home_team_id, f.venue_name, f.venue_city,
       f.is_neutral OR coalesce((SELECT c.neutral FROM core.fixture_venue_class c WHERE c.fixture_id = f.id
                                  ORDER BY c.classified_at DESC LIMIT 1), false) AS neutral
  FROM core.fixtures f
 WHERE f.venue_id IS NULL AND f.status_group <> 'cancelled' AND f.kickoff_at BETWEEN %(since)s AND %(until)s
   AND NOT EXISTS (SELECT 1 FROM core.fixture_venue_links l WHERE l.fixture_id = f.id AND l.rules_version = %(rules)s)"""

HISTORY_SQL: Final = """
SELECT f.home_team_id, f.venue_name, f.venue_city, f.venue_id, count(*)
  FROM core.fixtures f
 WHERE f.venue_id IS NOT NULL AND f.venue_name IS NOT NULL AND f.status_group <> 'cancelled'
   AND (f.home_team_id = ANY(%(teams)s) OR lower(btrim(f.venue_name)) = ANY(%(names)s))
 GROUP BY 1, 2, 3, 4"""
"""What the provider called a stadium it gave an id to: for the home clubs of the matches to link, or under their names."""

GROUNDS_SQL: Final = "SELECT id, name, city FROM core.venues WHERE provider_venue_id IS NULL OR provider_venue_id > 0"
HOME_SQL: Final = "SELECT id, venue_id FROM core.teams WHERE venue_id IS NOT NULL AND id = ANY(%(teams)s)"


@dataclass(slots=True)
class LinkReport:
    applied: bool
    considered: int = 0
    linked: int = 0
    by_method: dict[str, int] = field(default_factory=dict)
    questions: dict[str, int] = field(default_factory=dict)
    nothing_to_go_on: int = 0

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_index(conn: psycopg.Connection[Any], unlinked: Sequence[Unlinked]) -> LinkIndex:
    teams = sorted({u.home_team_id for u in unlinked})
    names = sorted({(u.venue_name or "").strip().lower() for u in unlinked if u.venue_name})
    with conn.cursor() as cur:
        cur.execute(GROUNDS_SQL)
        grounds = [Ground(int(r[0]), str(r[1]), r[2]) for r in cur.fetchall()]
        cur.execute(HOME_SQL, {"teams": teams})
        homes = {int(r[0]): int(r[1]) for r in cur.fetchall()}
        cur.execute(HISTORY_SQL, {"teams": teams, "names": names})
        history = [(int(r[0]), r[1], r[2], int(r[3]), int(r[4])) for r in cur.fetchall()]
    return LinkIndex.build(grounds, homes, history)


def link(conn: psycopg.Connection[Any], *, since: datetime | None = None, until: datetime | None = None,
         apply: bool = False, now: Callable[[], datetime] = lambda: datetime.now(UTC)) -> LinkReport:
    """Link the matches of the window (default: the last 365 days and the next 14) that have a stadium name and no provider id."""
    at = now()
    lo, hi = since or at - timedelta(days=365), until or at + timedelta(days=14)
    report = LinkReport(applied=apply)
    with conn.transaction(force_rollback=not apply), conn.cursor() as cur:
        cur.execute(UNLINKED_SQL, {"since": lo, "until": hi, "rules": LINK_RULES})
        unlinked = [Unlinked(int(r[0]), int(r[1]), r[2], r[3], bool(r[4])) for r in cur.fetchall()]
        report.considered = len(unlinked)
        links, questions, nothing = link_all(unlinked, build_index(conn, unlinked))
        report.nothing_to_go_on = nothing
        for k in links:
            cur.execute(
                "INSERT INTO core.fixture_venue_links (fixture_id, venue_id, method, confidence, rules_version, evidence) "
                "VALUES (%s, %s, %s, %s, %s, %s::jsonb) ON CONFLICT (fixture_id, rules_version, venue_id) DO NOTHING",
                (k.fixture_id, k.venue_id, k.method, k.confidence, LINK_RULES, json.dumps(k.evidence, sort_keys=True)))
            report.linked += cur.rowcount
            report.by_method[k.method] = report.by_method.get(k.method, 0) + 1
        _ask(cur, questions, LINK_RULES, None, report.questions)
    return report


# ── decisions ────────────────────────────────────────────────────────────────────────────────────────────────────────────

DECISIONS: Final = ("accept", "reject", "dismiss", "undo")


def decide(conn: psycopg.Connection[Any], queue_id: int, decision: str, *, actor: str, chosen: str | None = None,
           note: str | None = None, apply: bool = False) -> dict[str, Any]:
    """Answer one question. ``accept`` needs ``chosen`` (a candidate: a QID or a venue id); ``reject`` with ``chosen`` takes a
    link or an item out; ``undo`` takes the newest decision back."""
    if decision not in DECISIONS:
        return {"ok": False, "reason": "unknown_decision"}
    with conn.transaction(force_rollback=not apply), conn.cursor() as cur:
        cur.execute("SELECT kind, candidates FROM core.venue_review_queue WHERE id = %s", (queue_id,))
        row = cur.fetchone()
        if row is None:
            return {"ok": False, "reason": "no_such_question"}
        candidates = [str(c) for c in (row[1] or {}).get("candidates", [])]
        if decision == "accept" and (chosen is None or chosen not in candidates):
            return {"ok": False, "reason": "chosen_is_not_a_candidate", "candidates": candidates}
        cur.execute("INSERT INTO core.venue_review_decisions (queue_id, decision, chosen, decided_by, note) "
                    "VALUES (%s, %s, %s, %s, %s)", (queue_id, decision, chosen, actor, note))
    return {"ok": True, "applied": apply, "queue_id": queue_id, "decision": decision, "chosen": chosen}


# ── figures ──────────────────────────────────────────────────────────────────────────────────────────────────────────────

COVERAGE_SQL: Final = """
WITH used AS (SELECT DISTINCT f.venue_id FROM core.fixtures f
               WHERE f.venue_id IS NOT NULL AND f.status_group <> 'cancelled'
                 AND f.kickoff_at BETWEEN now() - interval '365 days' AND now() + interval '14 days'),
     nxt AS (SELECT f.id, f.venue_id FROM core.fixtures f
              WHERE f.status_group <> 'cancelled' AND f.kickoff_at BETWEEN now() AND now() + interval '14 days')
SELECT (SELECT count(*) FROM core.venues),
       (SELECT count(*) FROM core.venue_geo_live),
       (SELECT count(*) FROM core.venue_geo_live WHERE latitude IS NOT NULL),
       (SELECT count(*) FROM core.venue_geo_live WHERE elevation_m IS NOT NULL),
       (SELECT count(*) FROM used),
       (SELECT count(*) FROM used u JOIN core.venue_geo_live g ON g.venue_id = u.venue_id WHERE g.latitude IS NOT NULL),
       (SELECT count(*) FROM nxt),
       (SELECT count(*) FROM nxt WHERE venue_id IS NOT NULL),
       (SELECT count(*) FROM nxt n JOIN core.fixture_venue_resolved r ON r.fixture_id = n.id WHERE r.venue_id IS NOT NULL),
       (SELECT count(*) FROM core.venue_review_open)"""


def coverage(conn: psycopg.Connection[Any]) -> dict[str, Any]:
    with conn.cursor() as cur:
        cur.execute(COVERAGE_SQL)
        r = cur.fetchone()
    assert r
    keys = ("venues", "venues_with_item", "venues_with_coords", "venues_with_elevation", "venues_used",
            "venues_used_with_coords", "fixtures_next14", "fixtures_next14_provider_id", "fixtures_next14_resolved",
            "questions_open")
    out: dict[str, Any] = dict(zip(keys, (int(x) for x in r), strict=True))
    out["rules"] = {"geo": GEO_RULES, "link": LINK_RULES}
    return out


def link_cities(conn: psycopg.Connection[Any], limit: int = 5000) -> dict[str, int]:
    """Of the inferred links where both cities are known, how many put the match in a city its payload does not name."""
    from fbi.core.places import cities_compatible, split_place

    with conn.cursor() as cur:
        cur.execute("SELECT f.venue_name, f.venue_city, v.city FROM core.fixture_venue_links l "
                    "JOIN core.fixtures f ON f.id = l.fixture_id JOIN core.venues v ON v.id = l.venue_id "
                    "WHERE f.venue_city IS NOT NULL AND v.city IS NOT NULL ORDER BY l.id DESC LIMIT %s", (limit,))
        rows = cur.fetchall()
    other = sum(1 for name, city, vcity in rows if not cities_compatible(split_place(name, city)[1], vcity))
    return {"checked": len(rows), "other_city": other}
